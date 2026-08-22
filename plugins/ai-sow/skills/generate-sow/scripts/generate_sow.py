from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.review_gates import validate_design_gates
from workbook import read_estimation_contract, write_workbook


INPUT_PATHS = {
    "sourceRequirements": ".ai-sow/data/analyze-requirement/requirements.json",
    "asis": ".ai-sow/data/analyze-as-is/asis.json",
    "design": ".ai-sow/data/generate-design/design.json",
    "derivedRequirements": ".ai-sow/data/generate-design/requirements.json",
    "delivery": ".ai-sow/data/generate-story/delivery.json",
    "estimate": ".ai-sow/data/generate-task/estimate.json",
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GENERIC_RATIONALES = {
    "新建任务",
    "按需求新建",
    "按需求调整",
    "接入复用",
    "按需求",
    "工作量较大",
    "复杂度高",
    "复杂度低",
    "简单",
    "复杂",
}
EXISTING_OBJECT_NEW_WORK = {"数据迁移", "系统功能下线", "同一根因问题整改"}
EXISTING_CUTOVER_MARKERS = ("现有", "已有", "当前运行", "生产", "切流", "替换")
REUSE_ACTIVITY_LABELS = {
    "REGISTER": "注册",
    "CONFIGURE": "配置",
    "WRAP": "封装",
    "MAP": "映射",
    "ADAPT": "适配",
    "AUTHENTICATE": "认证",
    "TENANT_SETUP": "租户设置",
    "PERMISSION_SETUP": "权限设置",
    "SPECIALIZED_VERIFY": "专项验证",
}
TEST_ASSET_MARKERS = (
    "测试资产",
    "测试方案",
    "测试范围",
    "测试用例",
    "测试脚本",
    "测试配置",
    "测试框架",
    "自动化框架",
    "兼容矩阵",
    "负载模型",
)
ADJUSTMENT_ASSET_MARKERS = {
    "数据迁移": ("迁移资产", "迁移脚本", "迁移方案", "映射规则"),
    "发布切换": ("切换资产", "切换方案", "切换清单", "发布方案"),
}
RELEASE_CUTOVER_BASE_UNIT_ID = "BU-RELEASE-CUTOVER"
PROBLEM_DIAGNOSIS_BASE_UNIT_ID = "BU-TECH-SUPPORT"
ROOT_CAUSE_REMEDIATION_BASE_UNIT_ID = "BU-ROOT-CAUSE-REMEDIATION"


def diag(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def normalized_rationale(value: str) -> str:
    return re.sub(r"[\s，。；、:：/]+", "", value.casefold())


def rationale_is_generic(value: str) -> bool:
    normalized = normalized_rationale(value)
    return normalized in {
        normalized_rationale(candidate) for candidate in GENERIC_RATIONALES
    }


def adjustment_asset_markers(base_unit: dict[str, Any] | None) -> tuple[str, ...]:
    if base_unit is None:
        return ()
    if base_unit.get("taskFamily") == "质量验证":
        return TEST_ASSET_MARKERS
    return ADJUSTMENT_ASSET_MARKERS.get(str(base_unit.get("name", "")), ())


def safe_project_relative_path(value: object, *, allow_root: bool = False) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\n" in value or "\r" in value:
        return False
    if allow_root and value == ".":
        return True
    path = Path(value)
    return (
        not path.is_absolute()
        and not re.match(r"^[A-Za-z]:", value)
        and value == path.as_posix()
        and all(segment not in {"", ".", ".."} for segment in path.parts)
    )


def resolve_project_input(root: Path, relative: str, label: str) -> Path:
    try:
        resolved = (root / relative).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError(f"{label} is missing or outside project root: {relative}") from error
    return resolved


def reject_managed_symlink_chain(root: Path, target: Path) -> None:
    relative = target.relative_to(root)
    current = root
    for segment in relative.parts:
        current /= segment
        if current.is_symlink():
            raise ValueError(f"managed output path contains a symlink: {current}")


class PosixOutputAnchor:
    """An outputs directory reached only through no-follow directory handles."""

    def __init__(self, root: Path) -> None:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        self.root_fd = os.open(root, flags)
        self.ai_sow_fd = -1
        self.outputs_fd = -1
        try:
            self.ai_sow_fd = os.open(".ai-sow", flags, dir_fd=self.root_fd)
            try:
                os.mkdir("outputs", mode=0o755, dir_fd=self.ai_sow_fd)
            except FileExistsError:
                pass
            self.outputs_fd = os.open("outputs", flags, dir_fd=self.ai_sow_fd)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for attribute in ("outputs_fd", "ai_sow_fd", "root_fd"):
            file_descriptor = getattr(self, attribute, -1)
            if file_descriptor >= 0:
                os.close(file_descriptor)
                setattr(self, attribute, -1)

    @staticmethod
    def same_directory(left_fd: int, right_fd: int) -> bool:
        left = os.fstat(left_fd)
        right = os.fstat(right_fd)
        return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)

    def path_is_still_anchored(self) -> bool:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        current_ai_sow_fd = -1
        current_outputs_fd = -1
        try:
            current_ai_sow_fd = os.open(".ai-sow", flags, dir_fd=self.root_fd)
            current_outputs_fd = os.open(
                "outputs",
                flags,
                dir_fd=current_ai_sow_fd,
            )
            return self.same_directory(self.ai_sow_fd, current_ai_sow_fd) and self.same_directory(
                self.outputs_fd,
                current_outputs_fd,
            )
        except OSError:
            return False
        finally:
            if current_outputs_fd >= 0:
                os.close(current_outputs_fd)
            if current_ai_sow_fd >= 0:
                os.close(current_ai_sow_fd)

    @staticmethod
    def directory_flags() -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        return flags

    @staticmethod
    def copy_tree_into(source: Path, destination_fd: int) -> None:
        for entry in os.scandir(source):
            if entry.is_symlink():
                raise ValueError(f"temporary package contains a symlink: {entry.name}")
            if entry.is_dir(follow_symlinks=False):
                os.mkdir(entry.name, mode=0o700, dir_fd=destination_fd)
                child_fd = os.open(
                    entry.name,
                    PosixOutputAnchor.directory_flags(),
                    dir_fd=destination_fd,
                )
                try:
                    PosixOutputAnchor.copy_tree_into(Path(entry.path), child_fd)
                finally:
                    os.close(child_fd)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError(f"temporary package contains an unsupported entry: {entry.name}")
            source_flags = os.O_RDONLY | os.O_NOFOLLOW
            destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                source_flags |= os.O_CLOEXEC
                destination_flags |= os.O_CLOEXEC
            source_fd = -1
            destination_file_fd = -1
            try:
                with ExitStack() as streams:
                    source_fd = os.open(entry.path, source_flags)
                    source_stream = streams.enter_context(os.fdopen(source_fd, "rb"))
                    source_fd = -1
                    destination_file_fd = os.open(
                        entry.name,
                        destination_flags,
                        0o600,
                        dir_fd=destination_fd,
                    )
                    destination_stream = streams.enter_context(
                        os.fdopen(destination_file_fd, "wb")
                    )
                    destination_file_fd = -1
                    shutil.copyfileobj(source_stream, destination_stream)
                    destination_stream.flush()
                    os.fsync(destination_stream.fileno())
            finally:
                if source_fd >= 0:
                    os.close(source_fd)
                if destination_file_fd >= 0:
                    os.close(destination_file_fd)

    @staticmethod
    def remove_tree_at(parent_fd: int, name: str) -> None:
        try:
            directory_fd = os.open(
                name,
                PosixOutputAnchor.directory_flags(),
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return
        try:
            for child in os.listdir(directory_fd):
                child_stat = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(child_stat.st_mode):
                    PosixOutputAnchor.remove_tree_at(directory_fd, child)
                else:
                    os.unlink(child, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
        os.rmdir(name, dir_fd=parent_fd)

    def copy_then_publish(self, source: Path, name: str) -> None:
        transfer_name = f".transfer-{uuid.uuid4()}"
        os.mkdir(transfer_name, mode=0o700, dir_fd=self.outputs_fd)
        try:
            transfer_fd = os.open(
                transfer_name,
                self.directory_flags(),
                dir_fd=self.outputs_fd,
            )
        except Exception:
            try:
                os.rmdir(transfer_name, dir_fd=self.outputs_fd)
            except OSError:
                pass
            raise
        try:
            self.copy_tree_into(source, transfer_fd)
            current_transfer_fd = os.open(
                transfer_name,
                self.directory_flags(),
                dir_fd=self.outputs_fd,
            )
            try:
                if not self.same_directory(transfer_fd, current_transfer_fd):
                    raise ValueError("managed transfer directory changed during generation")
            finally:
                os.close(current_transfer_fd)
            os.rename(
                transfer_name,
                name,
                src_dir_fd=self.outputs_fd,
                dst_dir_fd=self.outputs_fd,
            )
        finally:
            os.close(transfer_fd)
            self.remove_tree_at(self.outputs_fd, transfer_name)
        shutil.rmtree(source)

    def publish_directory(self, source: Path, name: str) -> None:
        if not self.path_is_still_anchored():
            raise ValueError("managed outputs directory changed during generation")
        try:
            os.stat(name, dir_fd=self.outputs_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"managed output already exists: {name}")
        try:
            os.rename(source, name, dst_dir_fd=self.outputs_fd)
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
            self.copy_then_publish(source, name)
        if not self.path_is_still_anchored():
            raise ValueError("managed outputs directory changed during generation")


def validate_registered_project(
    root: Path,
    project: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    for field in ("projectId", "name", "pluginVersion", "sowStandardVersion"):
        if field not in project:
            diagnostics.append(diag("SHAPE_INVALID", f"project is missing {field}"))
    scope = asis.get("analysisScope")
    if not isinstance(scope, dict):
        diagnostics.append(diag("SHAPE_INVALID", "analysisScope must be an object"))
        return diagnostics
    repositories = scope.get("repositorySnapshots")
    prior_sows = scope.get("priorSowSnapshots")
    if not isinstance(repositories, list):
        diagnostics.append(
            diag("PROJECT_SCHEMA_INVALID", "analysisScope.repositorySnapshots must be an array")
        )
    if not isinstance(prior_sows, list):
        diagnostics.append(
            diag("PROJECT_SCHEMA_INVALID", "analysisScope.priorSowSnapshots must be an array")
        )
    if diagnostics:
        return diagnostics

    if not ID_PATTERN.fullmatch(str(project["projectId"])):
        diagnostics.append(diag("PROJECT_SCHEMA_INVALID", "projectId is invalid"))
    if project["pluginVersion"] != "0.1.0-beta.1":
        diagnostics.append(diag("PROJECT_SCHEMA_INVALID", "pluginVersion must be 0.1.0-beta.1"))
    if project["sowStandardVersion"] != "1.3":
        diagnostics.append(diag("PROJECT_SCHEMA_INVALID", "sowStandardVersion must be 1.3"))
    if scope.get("mode") not in {"GREENFIELD", "BROWNFIELD"}:
        diagnostics.append(diag("PROJECT_SCHEMA_INVALID", "analysisScope.mode is invalid"))

    for index, repository in enumerate(repositories):
        if not isinstance(repository, dict) or (
            not ID_PATTERN.fullmatch(str(repository.get("repoId", "")))
            or not safe_project_relative_path(repository.get("path"), allow_root=True)
            or not REVISION_PATTERN.fullmatch(str(repository.get("revision", "")))
            or not isinstance(repository.get("dirty"), bool)
        ):
            diagnostics.append(
                diag("PROJECT_SCHEMA_INVALID", f"repositorySnapshots[{index}] is invalid")
            )
    for index, prior_sow in enumerate(prior_sows):
        file = prior_sow.get("file") if isinstance(prior_sow, dict) else None
        if not isinstance(prior_sow, dict) or (
            not ID_PATTERN.fullmatch(str(prior_sow.get("priorSowId", "")))
            or not safe_project_relative_path(file)
            or not str(file).startswith(".ai-sow/inputs/analyze-as-is/prior-sows/")
            or not isinstance(prior_sow.get("originalName"), str)
            or not prior_sow.get("originalName")
            or not SHA256_PATTERN.fullmatch(str(prior_sow.get("sha256", "")))
        ):
            diagnostics.append(
                diag("PROJECT_SCHEMA_INVALID", f"priorSowSnapshots[{index}] is invalid")
            )
    if diagnostics:
        return diagnostics

    for repository in repositories:
        raw_path = repository["path"]
        try:
            resolved = (root / raw_path).resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_dir():
                raise ValueError("not a directory")
        except (OSError, ValueError):
            diagnostics.append(
                diag(
                    "REGISTERED_PATH_INVALID",
                    f"registered repository is missing or outside project root: {raw_path}",
                )
            )
    for prior_sow in prior_sows:
        raw_path = prior_sow["file"]
        try:
            resolved = (root / raw_path).resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                raise ValueError("not a file")
        except (OSError, ValueError):
            diagnostics.append(
                diag(
                    "REGISTERED_PATH_INVALID",
                    f"registered prior SOW is missing or outside project root: {raw_path}",
                )
            )
            continue
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != prior_sow["sha256"]:
            diagnostics.append(
                diag(
                    "PRIOR_SOW_HASH_MISMATCH",
                    f"registered prior SOW hash mismatch: {prior_sow['priorSowId']}",
                )
            )
    return diagnostics


def require_entries(
    document: dict[str, Any],
    collection: str,
    fields: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> list[dict[str, Any]]:
    entries = document.get(collection)
    if not isinstance(entries, list):
        diagnostics.append(diag("SHAPE_INVALID", f"{collection} must be an array"))
        return []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            diagnostics.append(diag("SHAPE_INVALID", f"{collection}[{index}] must be an object"))
            continue
        for field in fields:
            if field not in entry:
                diagnostics.append(diag("SHAPE_INVALID", f"{collection}[{index}] is missing {field}"))
    return entries


def require_string_fields(
    document: dict[str, Any],
    path: str,
    fields: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> None:
    for field in fields:
        if field in document and not isinstance(document[field], str):
            diagnostics.append(diag("SHAPE_INVALID", f"{path}.{field} must be a string"))


def require_entry_string_fields(
    entries: list[dict[str, Any]],
    collection: str,
    fields: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> None:
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        require_string_fields(entry, f"{collection}[{index}]", fields, diagnostics)


def require_string_array_fields(
    entries: list[dict[str, Any]],
    collection: str,
    fields: tuple[str, ...],
    diagnostics: list[dict[str, str]],
) -> None:
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        for field in fields:
            if field not in entry:
                continue
            values = entry[field]
            if not isinstance(values, list):
                diagnostics.append(
                    diag("SHAPE_INVALID", f"{collection}[{index}].{field} must be an array")
                )
                continue
            for value_index, value in enumerate(values):
                if not isinstance(value, str):
                    diagnostics.append(
                        diag(
                            "SHAPE_INVALID",
                            f"{collection}[{index}].{field}[{value_index}] must be a string",
                        )
                    )


def validate_inputs(
    values: dict[str, dict[str, Any]],
    project: dict[str, Any],
    estimation_contract: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    source = values["sourceRequirements"]
    derived = values["derivedRequirements"]
    asis = values["asis"]
    design = values["design"]
    delivery = values["delivery"]
    estimate = values["estimate"]

    for field in ("projectId", "name", "pluginVersion", "sowStandardVersion"):
        if field not in project:
            diagnostics.append(diag("SHAPE_INVALID", f"project is missing {field}"))
    require_string_fields(
        project,
        "project",
        ("projectId", "name", "pluginVersion", "sowStandardVersion"),
        diagnostics,
    )
    source_epics = require_entries(
        source, "epics", ("epicId", "type", "name", "description", "source"), diagnostics
    )
    source_features = require_entries(
        source, "features", ("featureId", "epicId", "name", "description", "source"), diagnostics
    )
    derived_epics = require_entries(
        derived, "epics", ("epicId", "type", "name", "description", "source"), diagnostics
    )
    derived_features = require_entries(
        derived, "features", ("featureId", "epicId", "name", "description", "source"), diagnostics
    )
    for index, entry in enumerate([*source_epics, *derived_epics]):
        require_string_fields(
            entry,
            f"epics[{index}]",
            (
                "epicId",
                "type",
                "name",
                "description",
                "involvedSystemsData",
                "targetOutcome",
                "commonConstraintsOutOfScope",
            ),
            diagnostics,
        )
    for index, entry in enumerate([*source_features, *derived_features]):
        require_string_fields(
            entry,
            f"features[{index}]",
            (
                "featureId",
                "epicId",
                "name",
                "description",
                "involvedSystemsData",
                "constraintsNfr",
            ),
            diagnostics,
        )
    analysis_scope = asis.get("analysisScope")
    if not isinstance(analysis_scope, dict):
        diagnostics.append(diag("SHAPE_INVALID", "analysisScope must be an object"))
        analysis_scope = {}
    for field in ("mode", "asOfDate"):
        if field not in analysis_scope:
            diagnostics.append(diag("SHAPE_INVALID", f"analysisScope is missing {field}"))
    require_string_fields(analysis_scope, "analysisScope", ("mode", "asOfDate"), diagnostics)
    repository_snapshots = require_entries(
        analysis_scope,
        "repositorySnapshots",
        ("repoId", "path", "revision", "dirty"),
        diagnostics,
    )
    require_entry_string_fields(
        repository_snapshots,
        "repositorySnapshots",
        ("repoId", "path", "revision"),
        diagnostics,
    )
    prior_sow_snapshots = require_entries(
        analysis_scope,
        "priorSowSnapshots",
        ("priorSowId", "file", "originalName", "sha256"),
        diagnostics,
    )
    require_entry_string_fields(
        prior_sow_snapshots,
        "priorSowSnapshots",
        ("priorSowId", "file", "originalName", "sha256"),
        diagnostics,
    )
    excluded_areas = analysis_scope.get("excludedAreas")
    if not isinstance(excluded_areas, list):
        diagnostics.append(diag("SHAPE_INVALID", "analysisScope.excludedAreas must be an array"))
    else:
        for index, value in enumerate(excluded_areas):
            if not isinstance(value, str):
                diagnostics.append(
                    diag(
                        "SHAPE_INVALID",
                        f"analysisScope.excludedAreas[{index}] must be a string",
                    )
                )
    topic_assessments = require_entries(
        asis,
        "topicAssessments",
        ("topic", "status", "summary"),
        diagnostics,
    )
    asis_items = require_entries(
        asis,
        "items",
        ("asIsItemId", "topic", "itemType", "name", "summary", "repositoryIds"),
        diagnostics,
    )
    commitments = require_entries(
        asis,
        "commitments",
        (
            "commitmentId",
            "priorSowId",
            "sourceReference",
            "topic",
            "changeType",
            "name",
            "summary",
            "implementationStatus",
            "treatment",
            "affectedItemIds",
            "relatedFeatureIds",
        ),
        diagnostics,
    )
    effective_starts = require_entries(
        asis,
        "effectiveStartItems",
        (
            "effectiveStartItemId",
            "topic",
            "itemType",
            "name",
            "summary",
            "sourceItemIds",
            "commitmentIds",
        ),
        diagnostics,
    )
    coverage = require_entries(
        asis,
        "coverage",
        (
            "featureId",
            "status",
            "effectiveStartItemIds",
            "commitmentIds",
            "uncertaintyIds",
            "rationale",
        ),
        diagnostics,
    )
    uncertainties = require_entries(
        asis,
        "uncertainties",
        (
            "uncertaintyId",
            "topic",
            "question",
            "impact",
            "affectsEstimate",
            "owner",
            "recommendedHandling",
            "relatedFeatureIds",
        ),
        diagnostics,
    )
    evidence = require_entries(
        asis,
        "evidence",
        ("evidenceId", "kind", "reference", "summary", "supportsIds"),
        diagnostics,
    )
    require_entry_string_fields(
        topic_assessments,
        "topicAssessments",
        ("topic", "status", "summary"),
        diagnostics,
    )
    require_entry_string_fields(
        asis_items,
        "items",
        ("asIsItemId", "topic", "itemType", "name", "summary"),
        diagnostics,
    )
    require_entry_string_fields(
        commitments,
        "commitments",
        (
            "commitmentId",
            "priorSowId",
            "sourceReference",
            "topic",
            "changeType",
            "name",
            "summary",
            "implementationStatus",
            "treatment",
        ),
        diagnostics,
    )
    require_entry_string_fields(
        effective_starts,
        "effectiveStartItems",
        ("effectiveStartItemId", "topic", "itemType", "name", "summary"),
        diagnostics,
    )
    require_entry_string_fields(
        coverage,
        "coverage",
        ("featureId", "status", "rationale"),
        diagnostics,
    )
    require_entry_string_fields(
        uncertainties,
        "uncertainties",
        (
            "uncertaintyId",
            "topic",
            "question",
            "impact",
            "owner",
            "recommendedHandling",
        ),
        diagnostics,
    )
    for index, uncertainty in enumerate(uncertainties):
        affects_estimate = uncertainty.get("affectsEstimate")
        if not isinstance(affects_estimate, bool):
            diagnostics.append(
                diag(
                    "SHAPE_INVALID",
                    f"uncertainties[{index}].affectsEstimate must be a boolean",
                )
            )
        elif affects_estimate:
            diagnostics.append(
                diag(
                    "ESTIMATE_UNCERTAINTY_UNRESOLVED",
                    "estimate-affecting uncertainty must be resolved before SOW "
                    f"generation: {uncertainty.get('uncertaintyId')}",
                )
            )
    require_entry_string_fields(
        evidence,
        "evidence",
        ("evidenceId", "kind", "reference", "summary"),
        diagnostics,
    )
    runtime_outcomes = {"PASSED", "FAILED", "BLOCKED"}
    for index, entry in enumerate(evidence):
        if entry.get("kind") == "RUNTIME":
            if entry.get("runtimeOutcome") not in runtime_outcomes:
                diagnostics.append(
                    diag(
                        "SHAPE_INVALID",
                        f"evidence[{index}].runtimeOutcome must be PASSED, FAILED, or BLOCKED",
                    )
                )
        elif "runtimeOutcome" in entry:
            diagnostics.append(
                diag(
                    "SHAPE_INVALID",
                    f"evidence[{index}].runtimeOutcome is only valid for RUNTIME evidence",
                )
            )
    require_string_array_fields(asis_items, "items", ("repositoryIds",), diagnostics)
    require_string_array_fields(
        commitments,
        "commitments",
        ("affectedItemIds", "relatedFeatureIds"),
        diagnostics,
    )
    require_string_array_fields(
        effective_starts,
        "effectiveStartItems",
        ("sourceItemIds", "commitmentIds"),
        diagnostics,
    )
    require_string_array_fields(
        coverage,
        "coverage",
        ("effectiveStartItemIds", "commitmentIds", "uncertaintyIds"),
        diagnostics,
    )
    require_string_array_fields(
        uncertainties,
        "uncertainties",
        ("relatedFeatureIds",),
        diagnostics,
    )
    require_string_array_fields(evidence, "evidence", ("supportsIds",), diagnostics)
    for index, entry in enumerate(asis_items):
        if entry.get("itemType") != "INTEGRATION":
            continue
        for field in ("source", "target", "trigger", "direction", "purpose", "owner"):
            if field not in entry:
                diagnostics.append(diag("SHAPE_INVALID", f"items[{index}] is missing {field}"))
        require_string_fields(
            entry,
            f"items[{index}]",
            ("source", "target", "trigger", "direction", "purpose", "owner"),
            diagnostics,
        )
    scopes = require_entries(design, "scopeDecisions", ("featureId", "decision"), diagnostics)
    gaps = require_entries(delivery, "gaps", ("gapId", "featureId", "name", "description"), diagnostics)
    stories = require_entries(delivery, "stories", ("storyId", "gapId", "name", "description", "uatRelevant"), diagnostics)
    criteria = require_entries(delivery, "acceptanceCriteria", ("acceptanceCriterionId", "storyId", "sequence", "result"), diagnostics)
    integrations = require_entries(
        delivery,
        "integrations",
        ("integrationId", "storyId", "source", "target", "trigger", "direction", "purpose", "owner"),
        diagnostics,
    )
    assumptions = require_entries(delivery, "assumptions", ("assumptionId", "type", "name", "trigger", "responsibilityBoundary", "status", "handling"), diagnostics)
    relations = require_entries(delivery, "assumptionStories", ("assumptionId", "storyId"), diagnostics)
    tasks = require_entries(
        estimate,
        "tasks",
        (
            "taskId",
            "storyId",
            "name",
            "baseUnit",
            "workMode",
            "workModeRationale",
            "complexity",
            "matchedEffectiveStartItemIds",
            "rationale",
        ),
        diagnostics,
    )
    if set(estimate) != {"tasks"}:
        diagnostics.append(
            diag(
                "SHAPE_INVALID",
                "estimate may only contain the tasks collection; sitEstimates and calculated fields are not allowed",
            )
        )
    story_fields = {"storyId", "gapId", "name", "description", "uatRelevant"}
    task_fields = {
        "taskId",
        "storyId",
        "name",
        "baseUnit",
        "workMode",
        "workModeRationale",
        "workModeEvidence",
        "complexity",
        "complexityRationale",
        "integrationId",
        "matchedEffectiveStartItemIds",
        "rationale",
    }
    for index, story in enumerate(stories):
        unexpected = sorted(set(story) - story_fields)
        if unexpected:
            diagnostics.append(
                diag("SHAPE_INVALID", f"stories[{index}] has unexpected fields: {unexpected}")
            )
        require_string_fields(
            story,
            f"stories[{index}]",
            ("storyId", "gapId", "name", "description"),
            diagnostics,
        )
        if "uatRelevant" in story and not isinstance(story["uatRelevant"], bool):
            diagnostics.append(
                diag("SHAPE_INVALID", f"stories[{index}].uatRelevant must be a boolean")
            )
    for index, task in enumerate(tasks):
        unexpected = sorted(set(task) - task_fields)
        if unexpected:
            diagnostics.append(
                diag("SHAPE_INVALID", f"tasks[{index}] has unexpected fields: {unexpected}")
            )
        require_string_fields(
            task,
            f"tasks[{index}]",
            (
                "taskId",
                "storyId",
                "name",
                "baseUnit",
                "workMode",
                "workModeRationale",
                "complexity",
                "rationale",
            ),
            diagnostics,
        )
        for optional in ("complexityRationale", "integrationId"):
            if optional in task and not isinstance(task[optional], str):
                diagnostics.append(
                    diag("SHAPE_INVALID", f"tasks[{index}].{optional} must be a string")
                )
        mode_evidence = task.get("workModeEvidence")
        if task.get("workMode") in {"调整", "接入复用"}:
            if not isinstance(mode_evidence, dict):
                diagnostics.append(
                    diag(
                        "SHAPE_INVALID",
                        f"tasks[{index}].workModeEvidence must be an object",
                    )
                )
            else:
                require_string_fields(
                    mode_evidence,
                    f"tasks[{index}].workModeEvidence",
                    ("effectiveStartItemId", "effectiveStartItemName"),
                    diagnostics,
                )
                unexpected_evidence = sorted(
                    set(mode_evidence)
                    - {
                        "effectiveStartItemId",
                        "effectiveStartItemName",
                        "projectSideWorkTypes",
                        "projectSideWorkCommitment",
                    }
                )
                if unexpected_evidence:
                    diagnostics.append(
                        diag(
                            "SHAPE_INVALID",
                            "workModeEvidence has unexpected fields: "
                            f"{unexpected_evidence}",
                        )
                    )
                activities = mode_evidence.get("projectSideWorkTypes")
                if task.get("workMode") == "接入复用":
                    commitment = mode_evidence.get("projectSideWorkCommitment")
                    if (
                        not isinstance(activities, list)
                        or not activities
                        or any(
                            not isinstance(activity, str)
                            or activity not in REUSE_ACTIVITY_LABELS
                            for activity in activities
                        )
                        or len(activities) != len(set(activities))
                        or not isinstance(commitment, str)
                        or not commitment
                    ):
                        diagnostics.append(
                            diag(
                                "SHAPE_INVALID",
                                "reuse workModeEvidence must define unique, supported "
                                "projectSideWorkTypes and a projectSideWorkCommitment: "
                                f"{task.get('taskId')}",
                            )
                        )
                elif activities is not None or "projectSideWorkCommitment" in mode_evidence:
                    diagnostics.append(
                        diag(
                            "SHAPE_INVALID",
                            "adjustment workModeEvidence must omit reuse-only fields: "
                            f"{task.get('taskId')}",
                        )
                    )
        elif mode_evidence is not None:
            diagnostics.append(
                diag(
                    "SHAPE_INVALID",
                    f"new Task must omit workModeEvidence: {task.get('taskId')}",
                )
            )
    require_entry_string_fields(
        integrations,
        "integrations",
        ("integrationId", "storyId", "source", "target", "trigger", "direction", "purpose", "owner"),
        diagnostics,
    )
    require_string_array_fields(
        tasks,
        "tasks",
        ("matchedEffectiveStartItemIds",),
        diagnostics,
    )
    if diagnostics:
        return diagnostics

    epics = [*source_epics, *derived_epics]
    features = [*source_features, *derived_features]
    for entry in source_epics + source_features:
        if entry["source"].get("type") != "SOURCE_INPUT":
            diagnostics.append(diag("SOURCE_TYPE_INVALID", "source requirements must use SOURCE_INPUT"))
    for entry in derived_epics:
        if entry.get("type") != "TECHNICAL" or entry["source"].get("type") not in {
            "SOURCE_INPUT",
            "DESIGN_DERIVED",
        }:
            diagnostics.append(diag("SOURCE_TYPE_INVALID", "design Epics must be TECHNICAL"))
    for entry in derived_features:
        if entry["source"].get("type") not in {
            "SOURCE_INPUT",
            "DESIGN_DERIVED",
        }:
            diagnostics.append(diag("SOURCE_TYPE_INVALID", "design Features must be TECHNICAL"))

    ids = [
        *[entry["epicId"] for entry in epics],
        *[entry["featureId"] for entry in features],
        *[entry["gapId"] for entry in gaps],
        *[entry["storyId"] for entry in stories],
        *[entry["acceptanceCriterionId"] for entry in criteria],
        *[entry["integrationId"] for entry in integrations],
        *[entry["assumptionId"] for entry in assumptions],
        *[entry["taskId"] for entry in tasks],
    ]
    for value, count in Counter(ids).items():
        if count > 1:
            diagnostics.append(diag("ID_DUPLICATE", f"duplicate ID: {value}"))

    epic_ids = {entry["epicId"] for entry in epics}
    feature_ids = {entry["featureId"] for entry in features}
    for entry in features:
        if entry["epicId"] not in epic_ids:
            diagnostics.append(diag("EPIC_REF_UNKNOWN", f"unknown epicId: {entry['epicId']}"))

    actual_scopes = [entry["featureId"] for entry in scopes]
    for reference, count in Counter(actual_scopes).items():
        if count > 1:
            diagnostics.append(diag("SCOPE_DUPLICATE", f"duplicate scope decision: {reference}"))
        if reference not in feature_ids:
            diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown scoped Feature: {reference}"))
    for reference in sorted(feature_ids - set(actual_scopes)):
        diagnostics.append(diag("SCOPE_MISSING", f"missing scope decision: {reference}"))
    in_scope = {entry["featureId"] for entry in scopes if entry["decision"] == "IN_SCOPE"}

    gap_ids = {entry["gapId"] for entry in gaps}
    gaps_by_scope = Counter(entry["featureId"] for entry in gaps)
    for entry in gaps:
        if entry["featureId"] not in in_scope:
            diagnostics.append(diag("GAP_SCOPE_INVALID", f"Gap is not IN_SCOPE: {entry['featureId']}"))
    for reference in sorted(in_scope - set(gaps_by_scope)):
        diagnostics.append(diag("GAP_COVERAGE_MISSING", f"missing Gap for: {reference}"))

    story_ids = {entry["storyId"] for entry in stories}
    stories_by_gap = Counter(entry["gapId"] for entry in stories)
    for entry in stories:
        if entry["gapId"] not in gap_ids:
            diagnostics.append(diag("GAP_REF_UNKNOWN", f"unknown gapId: {entry['gapId']}"))
    for reference in sorted(gap_ids - set(stories_by_gap)):
        diagnostics.append(diag("STORY_COVERAGE_MISSING", f"Gap has no Story: {reference}"))

    integrations_by_id = {entry["integrationId"]: entry for entry in integrations}
    for integration in integrations:
        if integration["storyId"] not in story_ids:
            diagnostics.append(
                diag("STORY_REF_UNKNOWN", f"unknown Story in Integration: {integration['storyId']}")
            )
        if integration["owner"] not in {"INTERNAL", "EXTERNAL"}:
            diagnostics.append(
                diag(
                    "INTEGRATION_OWNER_INVALID",
                    f"Integration owner must be INTERNAL or EXTERNAL: {integration['integrationId']}",
                )
            )

    criteria_by_story = Counter(entry["storyId"] for entry in criteria)
    for entry in criteria:
        if entry["storyId"] not in story_ids:
            diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown Story in AC: {entry['storyId']}"))
    for reference in sorted(story_ids - set(criteria_by_story)):
        diagnostics.append(diag("AC_COVERAGE_MISSING", f"Story has no AC: {reference}"))

    effective_starts_by_id = {
        entry["effectiveStartItemId"]: entry
        for entry in effective_starts
    }
    effective_start_ids = set(effective_starts_by_id)
    configured_options = {
        tuple(option) for option in estimation_contract["taskOptions"]
    }
    base_units = estimation_contract["baseUnits"]
    integration_unit_ids = {
        details["name"]: base_unit_id
        for base_unit_id, details in base_units.items()
        if details["name"] in {"内部系统对接", "外部系统对接"}
    }
    if set(integration_unit_ids) != {"内部系统对接", "外部系统对接"}:
        diagnostics.append(
            diag(
                "TEMPLATE_INTEGRATION_UNIT_MISSING",
                "template must define internal and external integration base units",
            )
        )
    tasks_by_story = Counter(entry["storyId"] for entry in tasks)
    tasks_by_integration: Counter[str] = Counter()
    release_cutovers_by_story: Counter[str] = Counter()
    problem_units_by_story: dict[str, set[str]] = {}
    for entry in tasks:
        if entry["storyId"] not in story_ids:
            diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown Story in Task: {entry['storyId']}"))
        option = (entry["baseUnit"], entry["workMode"])
        if option not in configured_options:
            diagnostics.append(
                diag("TASK_OPTION_NOT_CONFIGURED", f"task option is not configured: {option}")
            )
        if entry["complexity"] not in estimation_contract["complexities"]:
            diagnostics.append(
                diag("COMPLEXITY_NOT_CONFIGURED", f"complexity is not configured: {entry['complexity']}")
            )
        if rationale_is_generic(entry["workModeRationale"]):
            diagnostics.append(
                diag(
                    "WORK_MODE_RATIONALE_GENERIC",
                    f"work-mode rationale must state concrete current-state facts: {entry['taskId']}",
                )
            )
        base_unit = base_units.get(entry["baseUnit"])
        if entry["baseUnit"] == RELEASE_CUTOVER_BASE_UNIT_ID:
            release_cutovers_by_story[entry["storyId"]] += 1
        if entry["baseUnit"] in {
            PROBLEM_DIAGNOSIS_BASE_UNIT_ID,
            ROOT_CAUSE_REMEDIATION_BASE_UNIT_ID,
        }:
            problem_units_by_story.setdefault(entry["storyId"], set()).add(
                entry["baseUnit"]
            )
        complexity_rationale = entry.get("complexityRationale")
        if entry["complexity"] in {"S", "L"}:
            if not isinstance(complexity_rationale, str) or not complexity_rationale.strip():
                diagnostics.append(
                    diag(
                        "COMPLEXITY_RATIONALE_REQUIRED",
                        f"S/L Task requires a complexity rationale: {entry['taskId']}",
                    )
                )
            elif rationale_is_generic(complexity_rationale) or (
                base_unit is not None
                and normalized_rationale(complexity_rationale)
                == normalized_rationale(
                    base_unit["complexityStandards"][entry["complexity"]]
                )
            ):
                diagnostics.append(
                    diag(
                        "COMPLEXITY_RATIONALE_GENERIC",
                        f"complexity rationale must state concrete instance facts: {entry['taskId']}",
                    )
                )
        elif complexity_rationale is not None:
            diagnostics.append(
                diag(
                    "COMPLEXITY_RATIONALE_FORBIDDEN",
                    f"M Task must omit complexityRationale: {entry['taskId']}",
                )
            )
        if not isinstance(entry["matchedEffectiveStartItemIds"], list):
            diagnostics.append(diag("SHAPE_INVALID", f"matchedEffectiveStartItemIds must be an array: {entry['taskId']}"))
        else:
            base_unit_name = base_unit["name"] if base_unit is not None else ""
            new_work_needs_start = base_unit_name in EXISTING_OBJECT_NEW_WORK or (
                base_unit_name == "发布切换"
                and any(marker in entry["workModeRationale"] for marker in EXISTING_CUTOVER_MARKERS)
            )
            if (
                entry["workMode"] in {"调整", "接入复用"}
                or (entry["workMode"] == "新建" and new_work_needs_start)
            ) and not entry["matchedEffectiveStartItemIds"]:
                diagnostics.append(
                    diag(
                        "EFFECTIVE_START_REQUIRED",
                        f"workMode requires an Effective Start reference: {entry['taskId']}",
                    )
                )
            for reference in entry["matchedEffectiveStartItemIds"]:
                if reference not in effective_start_ids:
                    diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown effectiveStartItemId: {reference}"))
            task_mode_text = " ".join(
                value
                for value in (
                    entry.get("name"),
                    entry.get("workModeRationale"),
                    entry.get("rationale"),
                )
                if isinstance(value, str)
            )
            mode_evidence = entry.get("workModeEvidence")
            evidenced_start: dict[str, Any] | None = None
            if (
                entry["workMode"] in {"调整", "接入复用"}
                and isinstance(mode_evidence, dict)
            ):
                evidence_id = mode_evidence.get("effectiveStartItemId")
                evidence_name = mode_evidence.get("effectiveStartItemName")
                if evidence_id not in entry["matchedEffectiveStartItemIds"]:
                    diagnostics.append(
                        diag(
                            "WORK_MODE_EVIDENCE_REF_MISMATCH",
                            "work-mode evidence must reference one matched Effective "
                            f"Start: {entry['taskId']}",
                        )
                    )
                referenced_start = effective_starts_by_id.get(evidence_id)
                if referenced_start is not None:
                    if evidence_name != referenced_start.get("name"):
                        diagnostics.append(
                            diag(
                                "WORK_MODE_EVIDENCE_NAME_MISMATCH",
                                "work-mode evidence name must exactly match the "
                                f"Effective Start: {entry['taskId']}",
                            )
                        )
                    elif evidence_name not in task_mode_text:
                        diagnostics.append(
                            diag(
                                "EFFECTIVE_START_IRRELEVANT",
                                "Task must explicitly name the Effective Start object "
                                f"being changed or reused: {entry['taskId']}",
                            )
                        )
                    else:
                        evidenced_start = referenced_start
            evidenced_start_text = (
                f"{evidenced_start.get('name', '')} "
                f"{evidenced_start.get('summary', '')}"
                if evidenced_start is not None
                else ""
            )
            required_asset_markers = adjustment_asset_markers(base_unit)
            if (
                entry["workMode"] == "调整"
                and required_asset_markers
                and not any(
                    marker in evidenced_start_text for marker in required_asset_markers
                )
            ):
                diagnostics.append(
                    diag(
                        "WORK_MODE_ADJUSTMENT_ASSET_UNSPECIFIED",
                        f"adjustment must identify the existing asset being changed: {entry['taskId']}",
                    )
                )
            if entry["workMode"] == "接入复用" and isinstance(mode_evidence, dict):
                activities = mode_evidence.get("projectSideWorkTypes", [])
                labels = [
                    REUSE_ACTIVITY_LABELS[activity]
                    for activity in activities
                    if activity in REUSE_ACTIVITY_LABELS
                ]
                expected_commitment = "本项目负责并交付：" + "、".join(labels)
                expected_rationale = (
                    f"{mode_evidence.get('effectiveStartItemName', '')}保持不变；"
                    f"{expected_commitment}。"
                )
                if (
                    not activities
                    or len(labels) != len(activities)
                    or mode_evidence.get("projectSideWorkCommitment")
                    != expected_commitment
                    or entry["workModeRationale"] != expected_rationale
                ):
                    diagnostics.append(
                        diag(
                            "WORK_MODE_REUSE_NOT_ESTIMABLE",
                            "reuse evidence must use the canonical positive project-side "
                            f"delivery commitment: {entry['taskId']}",
                        )
                    )
        base_unit_name = base_unit["name"] if base_unit is not None else ""
        integration_id = entry.get("integrationId")
        if base_unit_name in integration_unit_ids:
            if integration_id is None:
                diagnostics.append(
                    diag(
                        "INTEGRATION_ID_REQUIRED",
                        f"integration Task must reference one Integration: {entry['taskId']}",
                    )
                )
            else:
                tasks_by_integration[integration_id] += 1
                integration = integrations_by_id.get(integration_id)
                if integration is None:
                    diagnostics.append(
                        diag("INTEGRATION_REF_UNKNOWN", f"unknown integrationId: {integration_id}")
                    )
                else:
                    if entry["storyId"] != integration["storyId"]:
                        diagnostics.append(
                            diag(
                                "INTEGRATION_STORY_MISMATCH",
                                f"Task and Integration must reference the same Story: {entry['taskId']}/{integration_id}",
                            )
                        )
                    expected_name = {
                        "INTERNAL": "内部系统对接",
                        "EXTERNAL": "外部系统对接",
                    }.get(integration["owner"])
                    if expected_name is not None and base_unit_name != expected_name:
                        diagnostics.append(
                            diag(
                                "INTEGRATION_OWNER_MISMATCH",
                                f"integration ownership requires {expected_name}: {entry['taskId']}",
                            )
                        )
        elif integration_id is not None:
            diagnostics.append(
                diag(
                    "INTEGRATION_ID_FORBIDDEN",
                    f"non-integration Task must not reference an Integration: {entry['taskId']}",
                )
            )
    for story_id, count in release_cutovers_by_story.items():
        if count > 1:
            diagnostics.append(
                diag(
                    "RELEASE_CUTOVER_DUPLICATE",
                    "one Story may contain only one release-cutover instance: "
                    f"{story_id}",
                )
            )
    problem_pair = {
        PROBLEM_DIAGNOSIS_BASE_UNIT_ID,
        ROOT_CAUSE_REMEDIATION_BASE_UNIT_ID,
    }
    for story_id, base_unit_ids in problem_units_by_story.items():
        if problem_pair <= base_unit_ids:
            diagnostics.append(
                diag(
                    "PROBLEM_TASK_OVERLAP",
                    "problem diagnosis and confirmed-root-cause remediation must not "
                    f"both estimate the same Story: {story_id}",
                )
            )
    for reference in sorted(story_ids - set(tasks_by_story)):
        diagnostics.append(diag("TASK_COVERAGE_MISSING", f"Story has no Task: {reference}"))

    for reference in integrations_by_id:
        count = tasks_by_integration[reference]
        if count == 0:
            diagnostics.append(
                diag("INTEGRATION_COVERAGE_MISSING", f"Integration has no integration Task: {reference}")
            )
        elif count > 1:
            diagnostics.append(
                diag("INTEGRATION_COVERAGE_DUPLICATE", f"Integration has multiple integration Tasks: {reference}")
            )

    assumption_ids = {entry["assumptionId"] for entry in assumptions}
    for relation in relations:
        if relation["assumptionId"] not in assumption_ids:
            diagnostics.append(diag("ASSUMPTION_REF_UNKNOWN", f"unknown assumptionId: {relation['assumptionId']}"))
        if relation["storyId"] not in story_ids:
            diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown Story in assumption relation: {relation['storyId']}"))
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a fill-only AI SOW package")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    staging: Path | None = None
    working: Path | None = None
    output_anchor: PosixOutputAnchor | None = None
    try:
        outputs = root / ".ai-sow/outputs"
        reject_managed_symlink_chain(root, outputs)
        package_id = f"sow-{uuid.uuid4()}"
        staging_name = f".staging-{uuid.uuid4()}"
        final = outputs / package_id
        if os.name == "posix" and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW"):
            output_anchor = PosixOutputAnchor(root)
            working = Path(tempfile.mkdtemp(prefix="ai-sow-package-"))
        else:
            outputs.mkdir(parents=True, exist_ok=True)
            staging = outputs / staging_name
            staging.mkdir()
            working = staging

        project_path = resolve_project_input(root, ".ai-sow/project.json", "project metadata")
        template_path = resolve_project_input(
            root,
            ".ai-sow/templates/sow-template.xlsx",
            "project template",
        )
        source_paths = {
            name: resolve_project_input(root, relative, f"{name} input")
            for name, relative in INPUT_PATHS.items()
        }
        review_diagnostics: list[dict[str, str]] = []
        try:
            review_path = resolve_project_input(
                root,
                ".ai-sow/reviews/generate-design.md",
                "generate-design review",
            )
            review_text = review_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            review_text = ""
            review_diagnostics.append(diag("INPUT_UNREADABLE", str(error)))
        project = json.loads(project_path.read_text(encoding="utf-8"))
        staged_paths: dict[str, Path] = {}
        for name, relative in INPUT_PATHS.items():
            destination = working / relative.removeprefix(".ai-sow/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_paths[name], destination)
            staged_paths[name] = destination
        values = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in staged_paths.items()}
        diagnostics = list(review_diagnostics)
        if not diagnostics:
            diagnostics = validate_registered_project(root, project, values["asis"])
        if not diagnostics:
            estimation_contract = read_estimation_contract(template_path)
            diagnostics = validate_inputs(values, project, estimation_contract)
        if not diagnostics:
            diagnostics.extend(
                validate_design_gates(
                    values["sourceRequirements"],
                    values["derivedRequirements"],
                    values["design"],
                    values["asis"],
                    review_text,
                )
            )
        if diagnostics:
            if output_anchor is not None:
                output_anchor.publish_directory(working, staging_name)
                working = None
                staging = outputs / staging_name
            print(json.dumps({
                "outcome": "BLOCKED",
                "summary": "SOW inputs are invalid",
                "staging": str(staging),
                "diagnostics": diagnostics,
            }, ensure_ascii=False))
            return 2

        merged = {
            "epics": [*values["sourceRequirements"]["epics"], *values["derivedRequirements"]["epics"]],
            "features": [*values["sourceRequirements"]["features"], *values["derivedRequirements"]["features"]],
        }
        write_workbook(
            template_path,
            {
                "project": project,
                "requirements": merged,
                "asis": values["asis"],
                "delivery": values["delivery"],
                "estimate": values["estimate"],
            },
            working / "sow.xlsx",
        )
        manifest = {
            "packageId": package_id,
            "projectId": project["projectId"],
            "pluginVersion": project["pluginVersion"],
            "sowStandardVersion": project["sowStandardVersion"],
            "projectMode": values["asis"]["analysisScope"]["mode"],
            "repositories": [
                {
                    "repoId": repository["repoId"],
                    "setupRevision": repository["revision"],
                }
                for repository in values["asis"]["analysisScope"]["repositorySnapshots"]
            ],
            "priorSows": [
                {
                    "priorSowId": prior_sow["priorSowId"],
                    "sha256": prior_sow["sha256"],
                }
                for prior_sow in values["asis"]["analysisScope"]["priorSowSnapshots"]
            ],
            "inputs": INPUT_PATHS,
            "templatePath": ".ai-sow/templates/sow-template.xlsx",
        }
        manifest_path = working / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        schema_path = Path(__file__).resolve().parents[1] / "contracts/manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(json.loads(manifest_path.read_text(encoding="utf-8")))
        for path in staged_paths.values():
            json.loads(path.read_text(encoding="utf-8"))
        if output_anchor is not None:
            output_anchor.publish_directory(working, package_id)
            working = None
        else:
            staging.rename(final)
        print(json.dumps({
            "outcome": "OK",
            "summary": "SOW package generated",
            "outputs": [str(final)],
            "nextStep": "Open sow.xlsx in Excel for calculation and offline review.",
        }, ensure_ascii=False))
        return 0
    except Exception as error:
        payload: dict[str, Any] = {
            "outcome": "ERROR",
            "summary": str(error),
        }
        if staging is not None:
            payload["staging"] = str(staging)
        print(json.dumps(payload, ensure_ascii=False))
        return 3
    finally:
        if output_anchor is not None:
            output_anchor.close()
        if working is not None and working != staging:
            shutil.rmtree(working, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
