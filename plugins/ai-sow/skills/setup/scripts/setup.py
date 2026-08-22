from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any


PLUGIN_VERSION = "0.1.0-beta.1"
SOW_STANDARD_VERSION = "1.3"


class BlockedError(ValueError):
    """A fail-closed setup condition that the caller must resolve."""


def emit(outcome: str, summary: str, **details: Any) -> None:
    print(json.dumps({"outcome": outcome, "summary": summary, **details}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize a minimal AI SOW project")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--repair", action="store_true")
    return parser.parse_args()


def reject_symlink_chain(project_root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(project_root)
    except ValueError as error:
        raise BlockedError(f"managed path is outside project root: {target}") from error
    current = project_root
    for segment in relative.parts:
        current /= segment
        if current.is_symlink():
            raise BlockedError(f"managed write path contains a symlink: {current}")


def install_project_shell(
    project_root: Path,
    project: dict[str, Any],
    template_bytes: bytes,
    *,
    publish_manifest: bool,
) -> Path:
    ai_sow = project_root / ".ai-sow"
    project_path = ai_sow / "project.json"
    template_path = ai_sow / "templates" / "sow-template.xlsx"
    directories = (
        ai_sow / "templates",
        ai_sow / "work",
        ai_sow / "data",
        ai_sow / "reviews",
        ai_sow / "validation",
        ai_sow / "outputs",
        ai_sow / "inputs",
        ai_sow / "runtime" / "setup",
    )
    for path in (ai_sow, project_path, template_path, *directories):
        reject_symlink_chain(project_root, path)

    if os.name == "posix" and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"):
        return install_project_shell_posix(
            project_root,
            project,
            template_bytes,
            publish_manifest=publish_manifest,
        )

    if template_path.exists() and template_path.read_bytes() != template_bytes:
        raise BlockedError(f"existing setup-owned template has conflicting content: {template_path}")

    ai_sow.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".setup-staging-", dir=ai_sow))
    try:
        staged_template = staging / "sow-template.xlsx"
        staged_template.write_bytes(template_bytes)
        if hashlib.sha256(staged_template.read_bytes()).digest() != hashlib.sha256(
            template_bytes
        ).digest():
            raise OSError("staged template hash verification failed")

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        if not template_path.exists():
            staged_template.replace(template_path)
        if publish_manifest:
            staged_project = staging / "project.json"
            staged_project.write_text(
                json.dumps(project, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            staged_project.replace(project_path)
        return template_path
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def open_directory_at(parent_fd: int, name: str, *, create: bool = False) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return os.open(name, flags, dir_fd=parent_fd)


def open_directory_chain(parent_fd: int, parts: tuple[str, ...], *, create: bool) -> int:
    current_fd = os.dup(parent_fd)
    try:
        for part in parts:
            next_fd = open_directory_at(current_fd, part, create=create)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def read_file_at(parent_fd: int, name: str) -> bytes | None:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        file_fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    try:
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = -1
            return stream.read()
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def publish_file_at(parent_fd: int, name: str, payload: bytes, *, label: str) -> bool:
    existing = read_file_at(parent_fd, name)
    if existing is not None:
        if existing != payload:
            raise BlockedError(f"existing {label} has conflicting content: {name}")
        return False

    temporary = f".setup-{uuid.uuid4().hex}.tmp"
    published = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    file_fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(file_fd, "wb") as stream:
            file_fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            published = True
        except FileExistsError:
            raced = read_file_at(parent_fd, name)
            if raced != payload:
                raise BlockedError(f"existing {label} has conflicting content: {name}")
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    return published


def same_directory_at(parent_fd: int, name: str, anchored_fd: int) -> bool:
    try:
        current_fd = open_directory_at(parent_fd, name)
    except OSError:
        return False
    try:
        current = os.fstat(current_fd)
        anchored = os.fstat(anchored_fd)
        return (current.st_dev, current.st_ino) == (anchored.st_dev, anchored.st_ino)
    finally:
        os.close(current_fd)


def same_directory_chain_at(
    parent_fd: int,
    parts: tuple[str, ...],
    anchored_fd: int,
) -> bool:
    try:
        current_fd = open_directory_chain(parent_fd, parts, create=False)
    except OSError:
        return False
    try:
        current = os.fstat(current_fd)
        anchored = os.fstat(anchored_fd)
        return (current.st_dev, current.st_ino) == (anchored.st_dev, anchored.st_ino)
    finally:
        os.close(current_fd)


def install_project_shell_posix(
    project_root: Path,
    project: dict[str, Any],
    template_bytes: bytes,
    *,
    publish_manifest: bool,
) -> Path:
    """Publish setup-owned files relative to no-follow directory handles."""
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        root_flags |= os.O_CLOEXEC
    root_fd = os.open(project_root, root_flags)
    ai_sow_fd = -1
    templates_fd = -1
    manifest_published = False
    try:
        ai_sow_fd = open_directory_at(root_fd, ".ai-sow", create=True)
        directory_parts = (
            ("templates",),
            ("work",),
            ("data",),
            ("reviews",),
            ("validation",),
            ("outputs",),
            ("inputs",),
            ("runtime", "setup"),
        )
        for parts in directory_parts:
            directory_fd = open_directory_chain(ai_sow_fd, parts, create=True)
            os.close(directory_fd)

        templates_fd = open_directory_chain(ai_sow_fd, ("templates",), create=False)
        publish_file_at(
            templates_fd,
            "sow-template.xlsx",
            template_bytes,
            label="setup-owned template",
        )

        def managed_directories_are_current() -> bool:
            return (
                same_directory_at(root_fd, ".ai-sow", ai_sow_fd)
                and same_directory_chain_at(
                    ai_sow_fd,
                    ("templates",),
                    templates_fd,
                )
            )

        if not managed_directories_are_current():
            raise BlockedError("managed setup directory changed during setup")

        if publish_manifest:
            manifest_published = publish_file_at(
                ai_sow_fd,
                "project.json",
                (json.dumps(project, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                label="project manifest",
            )

        if not managed_directories_are_current():
            if manifest_published:
                try:
                    os.unlink("project.json", dir_fd=ai_sow_fd)
                except FileNotFoundError:
                    pass
            raise BlockedError("managed setup directory changed during setup")
        return project_root / ".ai-sow/templates/sow-template.xlsx"
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise BlockedError("managed setup path changed to a symlink") from error
        raise
    finally:
        if templates_fd >= 0:
            os.close(templates_fd)
        if ai_sow_fd >= 0:
            os.close(ai_sow_fd)
        os.close(root_fd)


def main() -> int:
    args = parse_args()
    try:
        import openpyxl
        from jsonschema import Draft202012Validator
    except ImportError as error:
        emit(
            "NEEDS_INPUT",
            f"missing Python dependency: {error.name}",
            nextStep="Run `uv sync --locked` from the plugin repository, then rerun setup.",
        )
        return 2

    skill_root = Path(__file__).resolve().parents[1]
    asset_path = skill_root / "assets" / "sow-template.xlsx"
    schema_path = skill_root / "contracts" / "project.schema.json"
    try:
        template_bytes = asset_path.read_bytes()
        workbook = openpyxl.load_workbook(BytesIO(template_bytes), data_only=False)
        try:
            checked = BytesIO()
            workbook.save(checked)
        finally:
            workbook.close()

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        project_root = args.project_root.resolve(strict=True)
        ai_sow = project_root / ".ai-sow"
        project_path = ai_sow / "project.json"
        reject_symlink_chain(project_root, ai_sow)
        reject_symlink_chain(project_root, project_path)
        is_existing_project = project_path.exists()
        if is_existing_project and not args.repair:
            emit("BLOCKED", "project already exists", outputs=[str(project_path)])
            return 2

        if is_existing_project:
            try:
                existing = json.loads(project_path.read_text(encoding="utf-8"))
                validator.validate(existing)
            except Exception as error:
                raise BlockedError(f"registered project manifest is invalid: {error}") from error
            identity = (args.project_id, args.name)
            registered_identity = (
                existing["projectId"],
                existing["name"],
            )
            if identity != registered_identity:
                emit("BLOCKED", "repair identity does not match registered project")
                return 2
            template_path = install_project_shell(
                project_root,
                existing,
                template_bytes,
                publish_manifest=False,
            )
        else:
            requested = {
                "projectId": args.project_id,
                "name": args.name,
                "pluginVersion": PLUGIN_VERSION,
                "sowStandardVersion": SOW_STANDARD_VERSION,
            }
            errors = sorted(validator.iter_errors(requested), key=lambda item: list(item.path))
            if errors:
                emit(
                    "BLOCKED",
                    "project metadata is invalid",
                    diagnostics=[error.message for error in errors],
                )
                return 2
            template_path = install_project_shell(
                project_root,
                requested,
                template_bytes,
                publish_manifest=True,
            )

        emit(
            "OK",
            "AI SOW project is ready",
            outputs=[str(project_path), str(template_path)],
            nextStep="Run analyze-requirement.",
        )
        return 0
    except BlockedError as error:
        emit("BLOCKED", str(error))
        return 2
    except Exception as error:
        emit("ERROR", str(error))
        return 3


if __name__ == "__main__":
    sys.exit(main())
