from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PathExpectation = Literal["file", "dir", "any"]
_STAGING_ROOT_PATTERN = re.compile(r"\.ai-sow/\.stage-[0-9a-f]{12}")


class ProjectIOError(ValueError):
    """A deterministic project-path or publication failure."""

    def __init__(self, code: str, relative_path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.relative_path = relative_path


def _is_reparse(snapshot: os.stat_result) -> bool:
    attributes = getattr(snapshot, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _is_unsafe(snapshot: os.stat_result) -> bool:
    return stat.S_ISLNK(snapshot.st_mode) or _is_reparse(snapshot)


# 未启用长路径支持的 Windows 把路径限制在 MAX_PATH 之内。调用方用 managed_path_budget
# 计算某个根目录还能容纳多长的相对路径，并自行决定所需长度。
WINDOWS_MAX_PATH = 260
_ERROR_FILENAME_EXCED_RANGE = 206
_LONG_PATH_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"


def windows_long_paths_enabled() -> bool:
    """Report whether this machine lets processes use paths beyond MAX_PATH."""
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _LONG_PATH_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except OSError:
        return False
    return bool(value)


def managed_path_budget(root: Path) -> int | None:
    """Return the managed-suffix length `root` still allows, or None when unlimited."""
    if os.name != "nt" or windows_long_paths_enabled():
        return None
    return WINDOWS_MAX_PATH - len(str(Path(root).absolute())) - 1


def _path_too_long(error: OSError, relative_path: str) -> "ProjectIOError | None":
    if getattr(error, "winerror", None) != _ERROR_FILENAME_EXCED_RANGE:
        return None
    return ProjectIOError(
        "PROJECT_PATH_TOO_LONG",
        relative_path,
        "project path exceeds the Windows MAX_PATH limit; shorten the project root "
        "or enable Windows long path support",
    )


@dataclass(frozen=True)
class ProjectFiles:
    root: Path

    @classmethod
    def open(cls, root: Path) -> "ProjectFiles":
        candidate = Path(root).absolute()
        try:
            snapshot = candidate.lstat()
        except OSError as error:
            raise ProjectIOError(
                "PROJECT_ROOT_INVALID",
                ".",
                "project root must be an existing regular directory",
            ) from error
        if not stat.S_ISDIR(snapshot.st_mode) or _is_unsafe(snapshot):
            raise ProjectIOError(
                "PROJECT_ROOT_INVALID",
                ".",
                "project root must be an existing regular directory",
            )
        return cls(candidate)

    @classmethod
    def open_view(cls, base_root: Path, staging_root: str) -> "ProjectView":
        base = cls.open(base_root)
        cls._parts(staging_root)
        if _STAGING_ROOT_PATTERN.fullmatch(staging_root) is None:
            raise ProjectIOError(
                "STAGING_ROOT_INVALID",
                staging_root,
                "staging root must match .ai-sow/.stage-<12 lower hex>",
            )
        formal_root = base.resolve(".ai-sow", expect="dir")
        candidate = formal_root / staging_root.removeprefix(".ai-sow/")
        try:
            candidate.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise ProjectIOError(
                "STAGING_ROOT_INVALID",
                staging_root,
                "staging root must be a project-internal regular directory",
            ) from error
        try:
            snapshot = candidate.lstat()
        except OSError as error:
            raise ProjectIOError(
                "STAGING_ROOT_INVALID",
                staging_root,
                "staging root must be a project-internal regular directory",
            ) from error
        if (
            not stat.S_ISDIR(snapshot.st_mode)
            or _is_unsafe(snapshot)
            or snapshot.st_dev != formal_root.lstat().st_dev
        ):
            raise ProjectIOError(
                "STAGING_ROOT_INVALID",
                staging_root,
                "staging root must be a project-internal regular directory",
            )
        return ProjectView(
            base=base,
            staging=cls.open(candidate),
            staging_root=staging_root,
        )

    @staticmethod
    def _parts(relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or "\\" in relative_path:
            raise ProjectIOError(
                "PROJECT_PATH_INVALID",
                str(relative_path),
                "path must be a POSIX project-relative path",
            )
        parts = tuple(relative_path.split("/"))
        if (
            not relative_path
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or (parts and parts[0].endswith(":"))
        ):
            raise ProjectIOError(
                "PROJECT_PATH_INVALID",
                relative_path,
                "path must be a POSIX project-relative path without traversal",
            )
        return parts

    def _existing_path(
        self,
        relative_path: str,
        *,
        expect: PathExpectation,
    ) -> Path:
        parts = self._parts(relative_path)
        current = self.root
        for index, part in enumerate(parts):
            current = current / part
            try:
                snapshot = current.lstat()
            except FileNotFoundError as error:
                raise ProjectIOError(
                    "PROJECT_PATH_MISSING",
                    relative_path,
                    f"project path does not exist: {relative_path}",
                ) from error
            if _is_unsafe(snapshot):
                raise ProjectIOError(
                    "PROJECT_PATH_UNSAFE",
                    relative_path,
                    f"project path contains a symlink or reparse point: {relative_path}",
                )
            if index < len(parts) - 1 and not stat.S_ISDIR(snapshot.st_mode):
                raise ProjectIOError(
                    "PROJECT_PATH_TYPE",
                    relative_path,
                    f"project path parent is not a directory: {relative_path}",
                )
        snapshot = current.lstat()
        if expect == "file" and not stat.S_ISREG(snapshot.st_mode):
            raise ProjectIOError(
                "PROJECT_PATH_TYPE",
                relative_path,
                f"project path is not a regular file: {relative_path}",
            )
        if expect == "dir" and not stat.S_ISDIR(snapshot.st_mode):
            raise ProjectIOError(
                "PROJECT_PATH_TYPE",
                relative_path,
                f"project path is not a directory: {relative_path}",
            )
        return current

    def resolve(
        self,
        relative_path: str,
        *,
        expect: PathExpectation = "file",
    ) -> Path:
        if expect not in {"file", "dir", "any"}:
            raise ValueError(f"unsupported path expectation: {expect}")
        return self._existing_path(relative_path, expect=expect)

    def ensure_dir(self, relative_path: str) -> Path:
        parts = self._parts(relative_path)
        current = self.root
        for part in parts:
            current = current / part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as error:
                too_long = _path_too_long(error, relative_path)
                if too_long is None:
                    raise
                raise too_long from error
            snapshot = current.lstat()
            if _is_unsafe(snapshot):
                raise ProjectIOError(
                    "PROJECT_PATH_UNSAFE",
                    relative_path,
                    f"project directory contains a symlink or reparse point: {relative_path}",
                )
            if not stat.S_ISDIR(snapshot.st_mode):
                raise ProjectIOError(
                    "PROJECT_PATH_TYPE",
                    relative_path,
                    f"project directory path is not a directory: {relative_path}",
                )
        return current

    def read_bytes(self, relative_path: str) -> bytes:
        return self.resolve(relative_path, expect="file").read_bytes()

    def read_json(self, relative_path: str) -> object:
        try:
            return json.loads(self.read_bytes(relative_path).decode("utf-8"))
        except ProjectIOError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectIOError(
                "PROJECT_JSON_INVALID",
                relative_path,
                f"project JSON is invalid: {relative_path}",
            ) from error

    def _target(self, relative_path: str) -> Path:
        parts = self._parts(relative_path)
        parent_relative = "/".join(parts[:-1])
        parent = self.root if not parent_relative else self.ensure_dir(parent_relative)
        target = parent / parts[-1]
        try:
            snapshot = target.lstat()
        except FileNotFoundError:
            return target
        if _is_unsafe(snapshot):
            raise ProjectIOError(
                "PROJECT_PATH_UNSAFE",
                relative_path,
                f"project target is a symlink or reparse point: {relative_path}",
            )
        if not stat.S_ISREG(snapshot.st_mode):
            raise ProjectIOError(
                "PROJECT_PATH_TYPE",
                relative_path,
                f"project target is not a regular file: {relative_path}",
            )
        return target

    def write_atomic(self, relative_path: str, payload: bytes) -> None:
        target = self._target(relative_path)
        if target.exists() and target.read_bytes() == payload:
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        except OSError as error:
            too_long = _path_too_long(error, relative_path)
            if too_long is None:
                raise
            raise too_long from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def publish_new(
        self,
        relative_path: str,
        payload: bytes,
    ) -> Literal["CREATED", "REUSED"]:
        target = self._target(relative_path)
        if target.exists():
            if target.read_bytes() == payload:
                return "REUSED"
            raise ProjectIOError(
                "PROJECT_CONTENT_CONFLICT",
                relative_path,
                f"existing project file has different content: {relative_path}",
            )

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if self.read_bytes(relative_path) == payload:
                    return "REUSED"
                raise ProjectIOError(
                    "PROJECT_CONTENT_CONFLICT",
                    relative_path,
                    f"existing project file has different content: {relative_path}",
                )
            return "CREATED"
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProjectView:
    """A flat staging-first view over managed ``.ai-sow`` project files."""

    base: ProjectFiles
    staging: ProjectFiles
    staging_root: str

    _CONTROL_ROOT = ".project-io"
    _TOMBSTONE_ROOT = f"{_CONTROL_ROOT}/tombstones"

    def _parts(self, relative_path: str) -> tuple[str, ...]:
        parts = ProjectFiles._parts(relative_path)
        staging_namespace = "/".join(parts[:2])
        if (
            parts[0] == self._CONTROL_ROOT
            or (
                parts[0] == ".ai-sow"
                and len(parts) > 1
                and parts[1] == self._CONTROL_ROOT
            )
            or _STAGING_ROOT_PATTERN.fullmatch(staging_namespace) is not None
        ):
            raise ProjectIOError(
                "PROJECT_PATH_INVALID",
                relative_path,
                "path uses a reserved staging-view namespace",
            )
        return parts

    @staticmethod
    def _staging_relative(parts: tuple[str, ...]) -> str | None:
        if parts[0] != ".ai-sow" or len(parts) == 1:
            return None
        return "/".join(parts[1:])

    def _staging_target(self, relative_path: str) -> tuple[tuple[str, ...], str]:
        parts = self._parts(relative_path)
        staging_relative = self._staging_relative(parts)
        if staging_relative is None:
            raise ProjectIOError(
                "PROJECT_PATH_INVALID",
                relative_path,
                "staging-view writes require a logical .ai-sow project path",
            )
        return parts, staging_relative

    @classmethod
    def _marker_path(cls, parts: tuple[str, ...]) -> str:
        digest = hashlib.sha256("/".join(parts).encode("utf-8")).hexdigest()
        return f"{cls._TOMBSTONE_ROOT}/{digest}"

    @staticmethod
    def _marker_payload(parts: tuple[str, ...]) -> bytes:
        return f"{'/'.join(parts)}\n".encode("utf-8")

    @staticmethod
    def _missing(relative_path: str) -> ProjectIOError:
        return ProjectIOError(
            "PROJECT_PATH_MISSING",
            relative_path,
            f"project path does not exist: {relative_path}",
        )

    def _is_tombstoned(self, parts: tuple[str, ...]) -> bool:
        marker = self._marker_path(parts)
        try:
            self.staging.resolve(marker, expect="file")
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                return False
            raise
        if self.staging.read_bytes(marker) != self._marker_payload(parts):
            raise ProjectIOError(
                "PROJECT_TOMBSTONE_INVALID",
                "/".join(parts),
                "staging tombstone does not match its project path",
            )
        return True

    def is_tombstoned(self, relative_path: str) -> bool:
        parts = self._parts(relative_path)
        if self._staging_relative(parts) is None:
            return False
        return self._is_tombstoned(parts)

    def _clear_tombstone(self, parts: tuple[str, ...]) -> None:
        marker = self._marker_path(parts)
        try:
            target = self.staging.resolve(marker, expect="file")
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                return
            raise
        target.unlink()

    def _activate_staged_path(self, parts: tuple[str, ...]) -> None:
        self._clear_tombstone(parts)

    @staticmethod
    def _optional_path(files: ProjectFiles, relative_path: str) -> Path | None:
        try:
            return files.resolve(relative_path, expect="any")
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                return None
            raise

    def resolve(
        self,
        relative_path: str,
        *,
        expect: PathExpectation = "file",
    ) -> Path:
        if expect not in {"file", "dir", "any"}:
            raise ValueError(f"unsupported path expectation: {expect}")
        parts = self._parts(relative_path)
        staging_relative = self._staging_relative(parts)
        if staging_relative is None:
            return self.base.resolve(relative_path, expect=expect)
        if self._is_tombstoned(parts):
            raise self._missing(relative_path)
        try:
            return self.staging.resolve(staging_relative, expect=expect)
        except ProjectIOError as error:
            if error.code != "PROJECT_PATH_MISSING":
                raise
        return self.base.resolve(relative_path, expect=expect)

    def ensure_dir(self, relative_path: str) -> Path:
        parts, staging_relative = self._staging_target(relative_path)
        directory = self.staging.ensure_dir(staging_relative)
        self._activate_staged_path(parts)
        return directory

    def read_bytes(self, relative_path: str) -> bytes:
        return self.resolve(relative_path, expect="file").read_bytes()

    def read_json(self, relative_path: str) -> object:
        try:
            return json.loads(self.read_bytes(relative_path).decode("utf-8"))
        except ProjectIOError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectIOError(
                "PROJECT_JSON_INVALID",
                relative_path,
                f"project JSON is invalid: {relative_path}",
            ) from error

    def write_atomic(self, relative_path: str, payload: bytes) -> None:
        parts, staging_relative = self._staging_target(relative_path)
        self.staging.write_atomic(staging_relative, payload)
        self._activate_staged_path(parts)

    def publish_new(
        self,
        relative_path: str,
        payload: bytes,
    ) -> Literal["CREATED", "REUSED"]:
        parts, staging_relative = self._staging_target(relative_path)
        try:
            current = self.read_bytes(relative_path)
        except ProjectIOError as error:
            if error.code != "PROJECT_PATH_MISSING":
                raise
        else:
            if current == payload:
                return "REUSED"
            raise ProjectIOError(
                "PROJECT_CONTENT_CONFLICT",
                relative_path,
                f"existing project file has different content: {relative_path}",
            )
        outcome = self.staging.publish_new(staging_relative, payload)
        self._activate_staged_path(parts)
        return outcome

    def tombstone(self, relative_path: str) -> None:
        parts, staging_relative = self._staging_target(relative_path)
        base_target = self._optional_path(self.base, relative_path)
        staged_target = self._optional_path(self.staging, staging_relative)
        for target in (base_target, staged_target):
            if target is not None and not stat.S_ISREG(target.lstat().st_mode):
                raise ProjectIOError(
                    "PROJECT_PATH_TYPE",
                    relative_path,
                    f"tombstone target is not a regular file: {relative_path}",
                )
        self.staging.write_atomic(
            self._marker_path(parts),
            self._marker_payload(parts),
        )
        if staged_target is not None:
            staged_target.unlink()
