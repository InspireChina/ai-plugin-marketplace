from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from read_template import read_contract


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
EXISTING_OBJECT_NEW_WORK = {
    "数据迁移",
    "系统功能下线",
    "同一根因问题整改",
}
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


def validation_output_diagnostic(
    root: Path,
    validation_path: Path,
) -> dict[str, str] | None:
    for path in (root / ".ai-sow", validation_path.parent, validation_path):
        if path.is_symlink():
            return diag(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path must not be a symlink: {path}",
            )
        try:
            path.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return diag(
                "OUTPUT_PATH_UNSAFE",
                f"validation output path is outside project root: {path}",
            )
    return None


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _is_windows_reparse_point(snapshot: os.stat_result) -> bool:
    attributes = getattr(snapshot, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _safe_directory_snapshot(path: Path) -> os.stat_result:
    snapshot = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(snapshot.st_mode) or _is_windows_reparse_point(snapshot):
        raise OSError(
            f"validation output directory is unsafe or a reparse point: {path}"
        )
    return snapshot


def _safe_regular_file_snapshot(path: Path) -> os.stat_result:
    snapshot = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(snapshot.st_mode) or _is_windows_reparse_point(snapshot):
        raise OSError(
            f"validation output report is unsafe or a reparse point: {path}"
        )
    return snapshot


def _write_validation_report_portable(project_root: Path, validation_path: Path, content: str) -> None:
    ai_sow = project_root / ".ai-sow"
    ai_sow_snapshot = _safe_directory_snapshot(ai_sow)
    validation_path.parent.mkdir(exist_ok=True)
    if not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)):
        raise OSError("validation output parent changed before write")
    validation_snapshot = _safe_directory_snapshot(validation_path.parent)
    try:
        previous_file_snapshot = _safe_regular_file_snapshot(validation_path)
    except FileNotFoundError:
        previous_file_snapshot = None
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    if previous_file_snapshot is None:
        flags |= os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(validation_path, flags, 0o666)
    try:
        file_snapshot = os.fstat(file_descriptor)
        current_path_snapshot = _safe_regular_file_snapshot(validation_path)
        if not _same_file(file_snapshot, current_path_snapshot) or (previous_file_snapshot is not None and not _same_file(previous_file_snapshot, file_snapshot)) or not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)) or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent)):
            raise OSError("validation output path changed before write")
        os.ftruncate(file_descriptor, 0)
        payload = content.encode("utf-8")
        while payload:
            payload = payload[os.write(file_descriptor, payload) :]
        os.fsync(file_descriptor)
        if not _same_file(ai_sow_snapshot, _safe_directory_snapshot(ai_sow)) or not _same_file(validation_snapshot, _safe_directory_snapshot(validation_path.parent)) or not _same_file(file_snapshot, _safe_regular_file_snapshot(validation_path)):
            raise OSError("validation output path changed during write")
    finally:
        os.close(file_descriptor)


def write_validation_report(project_root: Path, validation_path: Path, content: str) -> None:
    if os.name != "posix":
        _write_validation_report_portable(project_root, validation_path, content)
        return
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    root_fd = os.open(project_root, directory_flags)
    try:
        ai_sow_fd = os.open(".ai-sow", directory_flags, dir_fd=root_fd)
        try:
            try:
                os.mkdir("validation", dir_fd=ai_sow_fd)
            except FileExistsError:
                pass
            validation_fd = os.open("validation", directory_flags, dir_fd=ai_sow_fd)
            try:
                report_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                report_fd = os.open(validation_path.name, report_flags, 0o666, dir_fd=validation_fd)
                try:
                    payload = content.encode("utf-8")
                    while payload:
                        payload = payload[os.write(report_fd, payload) :]
                    os.fsync(report_fd)
                finally:
                    os.close(report_fd)
            finally:
                os.close(validation_fd)
        finally:
            os.close(ai_sow_fd)
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate estimation task inputs")
    parser.add_argument("--project-root", required=True, type=Path)
    root = parser.parse_args().project_root.resolve()
    paths = {
        "delivery": root / ".ai-sow/data/generate-story/delivery.json",
        "asis": root / ".ai-sow/data/analyze-as-is/asis.json",
        "estimate": root / ".ai-sow/data/generate-task/estimate.json",
        "template": root / ".ai-sow/templates/sow-template.xlsx",
    }
    schema_path = Path(__file__).resolve().parents[1] / "contracts/estimate.schema.json"
    diagnostics: list[dict[str, str]] = []
    try:
        delivery: dict[str, Any] = json.loads(paths["delivery"].read_text(encoding="utf-8"))
        asis: dict[str, Any] = json.loads(paths["asis"].read_text(encoding="utf-8"))
        estimate: dict[str, Any] = json.loads(paths["estimate"].read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        template = read_contract(paths["template"])
    except (OSError, json.JSONDecodeError, ValueError) as error:
        diagnostics.append(diag("INPUT_UNREADABLE", str(error)))
        delivery, asis, estimate, schema, template = {}, {}, {}, {}, {}

    if not diagnostics:
        for error in sorted(Draft202012Validator(schema).iter_errors(estimate), key=lambda value: list(value.path)):
            diagnostics.append(diag("SCHEMA_INVALID", error.message))

    if not diagnostics:
        story_ids = {entry["storyId"] for entry in delivery.get("stories", [])}
        integrations = {
            entry["integrationId"]: entry
            for entry in delivery.get("integrations", [])
        }
        effective_starts = {
            entry["effectiveStartItemId"]: entry
            for entry in asis.get("effectiveStartItems", [])
        }
        effective_start_ids = set(effective_starts)
        configured = {tuple(option) for option in template["taskOptions"]}
        base_units = template["baseUnits"]
        integration_units = {
            base_unit["name"]: base_unit_id
            for base_unit_id, base_unit in base_units.items()
            if base_unit["name"] in {"内部系统对接", "外部系统对接"}
        }
        if set(integration_units) != {"内部系统对接", "外部系统对接"}:
            diagnostics.append(
                diag(
                    "TEMPLATE_INTEGRATION_UNIT_MISSING",
                    "template must define internal and external integration base units",
                )
            )

        task_ids = [entry["taskId"] for entry in estimate["tasks"]]
        for value, count in Counter(task_ids).items():
            if count > 1:
                diagnostics.append(diag("ID_DUPLICATE", f"duplicate taskId: {value}"))

        task_descriptions = Counter(
            (entry["storyId"], " ".join(entry["name"].casefold().split()))
            for entry in estimate["tasks"]
        )
        for (story_id, description), count in task_descriptions.items():
            if count > 1:
                diagnostics.append(
                    diag(
                        "TASK_DESCRIPTION_DUPLICATE",
                        f"duplicate normalized Task description for {story_id}: {description}",
                    )
                )

        tasks_by_story = Counter(entry["storyId"] for entry in estimate["tasks"])
        tasks_by_integration: Counter[str] = Counter()
        release_cutovers_by_story: Counter[str] = Counter()
        problem_units_by_story: dict[str, set[str]] = {}
        for task in estimate["tasks"]:
            if task["storyId"] not in story_ids:
                diagnostics.append(diag("STORY_REF_UNKNOWN", f"unknown storyId: {task['storyId']}"))
            option = (task["baseUnit"], task["workMode"])
            if option not in configured:
                diagnostics.append(diag("TASK_OPTION_NOT_CONFIGURED", f"task option is not configured: {option}"))
            if task["complexity"] not in template["complexities"]:
                diagnostics.append(diag("COMPLEXITY_NOT_CONFIGURED", f"complexity is not configured: {task['complexity']}"))
            if rationale_is_generic(task["workModeRationale"]):
                diagnostics.append(
                    diag(
                        "WORK_MODE_RATIONALE_GENERIC",
                        f"work-mode rationale must state concrete current-state facts: {task['taskId']}",
                    )
                )

            base_unit = base_units.get(task["baseUnit"])
            if task["baseUnit"] == RELEASE_CUTOVER_BASE_UNIT_ID:
                release_cutovers_by_story[task["storyId"]] += 1
            if task["baseUnit"] in {
                PROBLEM_DIAGNOSIS_BASE_UNIT_ID,
                ROOT_CAUSE_REMEDIATION_BASE_UNIT_ID,
            }:
                problem_units_by_story.setdefault(task["storyId"], set()).add(
                    task["baseUnit"]
                )
            if task["complexity"] in {"S", "L"} and base_unit is not None:
                rationale = task["complexityRationale"]
                standard = base_unit["complexityStandards"][task["complexity"]]
                if (
                    rationale_is_generic(rationale)
                    or normalized_rationale(rationale) == normalized_rationale(standard)
                ):
                    diagnostics.append(
                        diag(
                            "COMPLEXITY_RATIONALE_GENERIC",
                            f"complexity rationale must state instance facts beyond the catalog standard: {task['taskId']}",
                        )
                    )
            matched_effective_start_ids = task["matchedEffectiveStartItemIds"]
            base_unit_name = base_unit["name"] if base_unit is not None else ""
            new_work_needs_start = base_unit_name in EXISTING_OBJECT_NEW_WORK or (
                base_unit_name == "发布切换"
                and any(
                    marker in task["workModeRationale"]
                    for marker in EXISTING_CUTOVER_MARKERS
                )
            )
            if (
                task["workMode"] in {"调整", "接入复用"}
                or (task["workMode"] == "新建" and new_work_needs_start)
            ) and not matched_effective_start_ids:
                diagnostics.append(diag(
                    "EFFECTIVE_START_REQUIRED",
                    f"workMode requires an Effective Start reference: {task['taskId']}",
                ))
            for reference in matched_effective_start_ids:
                if reference not in effective_start_ids:
                    diagnostics.append(diag(
                        "EFFECTIVE_START_REF_UNKNOWN",
                        f"unknown effectiveStartItemId: {reference}",
                    ))
            task_mode_text = " ".join(
                value
                for value in (
                    task.get("name"),
                    task.get("workModeRationale"),
                    task.get("rationale"),
                )
                if isinstance(value, str)
            )
            mode_evidence = task.get("workModeEvidence")
            evidenced_start: dict[str, Any] | None = None
            if (
                task["workMode"] in {"调整", "接入复用"}
                and isinstance(mode_evidence, dict)
            ):
                evidence_id = mode_evidence.get("effectiveStartItemId")
                evidence_name = mode_evidence.get("effectiveStartItemName")
                if evidence_id not in matched_effective_start_ids:
                    diagnostics.append(
                        diag(
                            "WORK_MODE_EVIDENCE_REF_MISMATCH",
                            "work-mode evidence must reference one matched Effective "
                            f"Start: {task['taskId']}",
                        )
                    )
                referenced_start = effective_starts.get(evidence_id)
                if referenced_start is not None:
                    if evidence_name != referenced_start.get("name"):
                        diagnostics.append(
                            diag(
                                "WORK_MODE_EVIDENCE_NAME_MISMATCH",
                                "work-mode evidence name must exactly match the "
                                f"Effective Start: {task['taskId']}",
                            )
                        )
                    elif evidence_name not in task_mode_text:
                        diagnostics.append(
                            diag(
                                "EFFECTIVE_START_IRRELEVANT",
                                "Task must explicitly name the Effective Start object "
                                f"being changed or reused: {task['taskId']}",
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
                task["workMode"] == "调整"
                and required_asset_markers
                and not any(
                    marker in evidenced_start_text for marker in required_asset_markers
                )
            ):
                diagnostics.append(
                    diag(
                        "WORK_MODE_ADJUSTMENT_ASSET_UNSPECIFIED",
                        f"adjustment must identify the existing asset being changed: {task['taskId']}",
                    )
                )
            if task["workMode"] == "接入复用" and isinstance(mode_evidence, dict):
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
                    or task["workModeRationale"] != expected_rationale
                ):
                    diagnostics.append(
                        diag(
                            "WORK_MODE_REUSE_NOT_ESTIMABLE",
                            "reuse evidence must use the canonical positive project-side "
                            f"delivery commitment: {task['taskId']}",
                        )
                    )

            integration_id = task.get("integrationId")
            if base_unit_name in integration_units:
                if integration_id is None:
                    diagnostics.append(
                        diag(
                            "INTEGRATION_ID_REQUIRED",
                            f"integration Task must reference one Integration: {task['taskId']}",
                        )
                    )
                else:
                    tasks_by_integration[integration_id] += 1
                    integration = integrations.get(integration_id)
                    if integration is None:
                        diagnostics.append(
                            diag(
                                "INTEGRATION_REF_UNKNOWN",
                                f"unknown integrationId: {integration_id}",
                            )
                        )
                    else:
                        if task["storyId"] != integration["storyId"]:
                            diagnostics.append(
                                diag(
                                    "INTEGRATION_STORY_MISMATCH",
                                    f"Task and Integration must reference the same Story: {task['taskId']}/{integration_id}",
                                )
                            )
                        expected_name = (
                            "内部系统对接"
                            if integration["owner"] == "INTERNAL"
                            else "外部系统对接"
                        )
                        if base_unit_name != expected_name:
                            diagnostics.append(
                                diag(
                                    "INTEGRATION_OWNER_MISMATCH",
                                    f"integration ownership requires {expected_name}: {task['taskId']}",
                                )
                            )
            elif integration_id is not None:
                diagnostics.append(
                    diag(
                        "INTEGRATION_ID_FORBIDDEN",
                        f"non-integration Task must not reference an Integration: {task['taskId']}",
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

        for reference in integrations:
            count = tasks_by_integration[reference]
            if count == 0:
                diagnostics.append(
                    diag(
                        "INTEGRATION_COVERAGE_MISSING",
                        f"Integration has no integration Task: {reference}",
                    )
                )
            if count > 1:
                diagnostics.append(
                    diag(
                        "INTEGRATION_COVERAGE_DUPLICATE",
                        f"Integration has multiple integration Tasks: {reference}",
                    )
                )

    validation_path = root / ".ai-sow/validation/generate-task.json"
    output_diagnostic = validation_output_diagnostic(root, validation_path)
    if output_diagnostic:
        diagnostics.append(output_diagnostic)
    else:
        report = {
            "subject": "generate-task",
            "passed": not diagnostics,
            "diagnostics": diagnostics,
        }
        try:
            write_validation_report(
                root,
                validation_path,
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as error:
            diagnostics.append(diag("OUTPUT_UNWRITABLE", str(error)))
    print(json.dumps({
        "outcome": "OK" if not diagnostics else "BLOCKED",
        "summary": "estimate inputs are valid" if not diagnostics else "estimate inputs are invalid",
        "outputs": [str(paths["estimate"]), str(validation_path)],
        "diagnostics": diagnostics,
    }, ensure_ascii=False))
    return 0 if not diagnostics else 2


if __name__ == "__main__":
    sys.exit(main())
