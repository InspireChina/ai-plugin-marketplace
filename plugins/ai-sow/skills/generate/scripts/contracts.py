from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from models import Diagnostic, DiagnosticClassification


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_registry(contract_root: Path) -> Registry:
    registry = Registry()
    seen_ids: set[str] = set()
    for path in sorted(contract_root.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Schema 缺少非空 $id：{path.name}")
        if schema_id in seen_ids:
            raise ValueError(f"Schema $id 重复：{schema_id}")
        seen_ids.add(schema_id)
        registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


def load_schema_registry(skill_root: Path) -> Registry:
    return load_registry(skill_root / "contracts")


def _schema_ids(schema_name: str) -> tuple[str, ...]:
    suffix = ".schema.json"
    if not schema_name.endswith(suffix):
        raise ValueError(f"Schema 名称必须以 {suffix} 结尾")
    stem = schema_name.removesuffix(suffix)
    return (f"urn:ai-sow:generate:next:{stem}:1",)


def _schema_contents(schema_name: str, registry: Registry) -> object:
    matches: list[object] = []
    for schema_id in _schema_ids(schema_name):
        resource = registry.get(schema_id)
        if resource is not None:
            matches.append(resource.contents)
    if len(matches) != 1:
        raise LookupError(
            f"Schema 必须由显式注入的单一 registry 唯一解析：{schema_name}"
        )
    return matches[0]


def _json_pointer(parts: object) -> str:
    escaped = [
        str(part).replace("~", "~0").replace("/", "~1") for part in parts  # type: ignore[arg-type]
    ]
    return "/" + "/".join(escaped) if escaped else ""


def _diagnostic(
    code: str,
    path: str,
    message: str,
    **details: object,
) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details=details)


def _sort_diagnostics(diagnostics: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))


def validate_contract(
    value: object,
    schema_name: str,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    try:
        schema = _schema_contents(schema_name, registry)
        errors = tuple(Draft202012Validator(schema, registry=registry).iter_errors(value))
    except (NoSuchResource, LookupError, ValueError) as error:
        return (
            _diagnostic(
                "CONTRACT_REFERENCE_INVALID",
                "",
                "合同引用无法解析。",
                schema=schema_name,
                errorType=type(error).__name__,
            ),
        )

    diagnostics: list[Diagnostic] = []
    for error in errors:
        code = {
            "required": "CONTRACT_REQUIRED",
            "additionalProperties": "CONTRACT_UNEXPECTED_PROPERTY",
        }.get(error.validator, "CONTRACT_INVALID")
        message = {
            "CONTRACT_REQUIRED": "合同缺少必填字段。",
            "CONTRACT_UNEXPECTED_PROPERTY": "合同包含未声明字段。",
            "CONTRACT_INVALID": "合同值不符合 Schema。",
        }[code]
        diagnostics.append(
            _diagnostic(
                code,
                _json_pointer(error.absolute_path),
                message,
                schema=schema_name,
                validator=str(error.validator),
                schemaPath=_json_pointer(error.absolute_schema_path),
            )
        )
    return _sort_diagnostics(diagnostics)


def validate_state_combination(
    value: object,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    diagnostics = list(validate_contract(value, "run-state.schema.json", registry))
    if diagnostics or not isinstance(value, Mapping):
        return _sort_diagnostics(diagnostics)

    budget = value.get("budget")
    if isinstance(budget, Mapping):
        started = budget.get("modelActionsStarted")
        completed = budget.get("modelActionsCompleted")
        if (
            isinstance(started, int)
            and not isinstance(started, bool)
            and isinstance(completed, int)
            and not isinstance(completed, bool)
            and completed > started
        ):
            diagnostics.append(
                _diagnostic(
                    "RUN_BUDGET_COUNT_INVALID",
                    "/budget/modelActionsCompleted",
                    "已完成的模型动作数不得超过已启动数。",
                )
            )

    candidate_sha256 = value.get("currentCandidateSha256")
    candidate_path = value.get("currentCandidatePath")
    if (candidate_sha256 is None) != (candidate_path is None):
        diagnostics.append(
            _diagnostic(
                "RUN_CANDIDATE_BINDING_INCOMPLETE",
                "/currentCandidatePath",
                "当前候选路径与哈希必须同时存在或同时为空。",
            )
        )
    return _sort_diagnostics(diagnostics)


def validate_action_binding(
    envelope: Mapping[str, object],
    *,
    action_id: str,
    envelope_sha256: str,
    input_revision_sha256: str,
    base_candidate_sha256: str,
    result_path: object,
    expected_action_ids: tuple[str, ...],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    envelope_action_id = envelope.get("actionId")
    if action_id != envelope_action_id:
        diagnostics.append(
            _diagnostic(
                "ACTION_ID_MISMATCH",
                "/actionId",
                "提交的 action ID 与 envelope 不一致。",
            )
        )
    if envelope_action_id not in expected_action_ids:
        diagnostics.append(
            _diagnostic(
                "ACTION_NOT_EXPECTED",
                "/actionId",
                "该 action 不是当前 Run State 等待的动作。",
            )
        )
    if envelope_sha256 != sha256_bytes(canonical_json_bytes(envelope)):
        diagnostics.append(
            _diagnostic(
                "ACTION_ENVELOPE_HASH_MISMATCH",
                "",
                "提交未绑定当前 action envelope 的规范哈希。",
            )
        )
    if input_revision_sha256 != envelope.get("inputRevisionSha256"):
        diagnostics.append(
            _diagnostic(
                "ACTION_INPUT_REVISION_STALE",
                "/inputRevisionSha256",
                "提交绑定的 Input Revision 已过期。",
            )
        )
    if base_candidate_sha256 != envelope.get("baseCandidateSha256"):
        diagnostics.append(
            _diagnostic(
                "ACTION_BASE_CANDIDATE_STALE",
                "/baseCandidateSha256",
                "提交绑定的基础候选已过期。",
            )
        )

    submit_operation = envelope.get("submitOperation")
    locked_result_path = (
        submit_operation.get("resultPath")
        if isinstance(submit_operation, Mapping)
        else None
    )
    if result_path != envelope.get("outputPath") or result_path != locked_result_path:
        diagnostics.append(
            _diagnostic(
                "ACTION_RESULT_PATH_MISMATCH",
                "/submitOperation/resultPath",
                "提交路径必须与 envelope 锁定的输出路径完全一致。",
            )
        )
    return _sort_diagnostics(diagnostics)


_DIAGNOSTIC_CLASSIFICATIONS: dict[str, DiagnosticClassification] = {
    "GLOBAL_SCOPE_CAPACITY_EXCEEDED": DiagnosticClassification(
        "CONTRACT_UNSUPPORTED", "STAGE_1", False
    ),
    "SOURCE_SEMANTIC_CONFLICT": DiagnosticClassification(
        "INPUT_REQUIRED", "INPUT", True
    ),
    "DESIGN_COVERAGE_INSUFFICIENT": DiagnosticClassification(
        "INPUT_REQUIRED", "INPUT", True
    ),
    "STORY_COVERAGE_OUTSTANDING": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_2", True
    ),
    "STORY_GLOBAL_JOIN_REQUIRED": DiagnosticClassification("CONTROL", "STAGE_2", True),
    "TASK_STANDARD_TYPE_UNREPRESENTABLE": DiagnosticClassification(
        "CONTRACT_UNSUPPORTED", "STAGE_3", False
    ),
    "TASK_CHALLENGER_NOT_REVIEWED": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "PRIOR_MATCH_SEARCH_INCOMPLETE": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "TASK_X_SPLIT_REQUIRED": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "THEME_JOIN_REQUIRED": DiagnosticClassification("CONTROL", "REVIEW", True),
    "RUN_IN_PROGRESS": DiagnosticClassification("CONTROL", "ORCHESTRATOR", False),
    "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "HOST_CAPABILITY_MISSING": DiagnosticClassification(
        "SYSTEM_FAILED", "ORCHESTRATOR", False
    ),
    "BUDGET_EXCEEDED": DiagnosticClassification(
        "SYSTEM_FAILED", "ORCHESTRATOR", False
    ),
}


def classify_diagnostic(
    code: str,
    *,
    source_sufficient: bool | None = None,
) -> DiagnosticClassification:
    if code == "TASK_TYPE_AMBIGUOUS":
        if source_sufficient is None:
            raise ValueError("TASK_TYPE_AMBIGUOUS 必须提供 source_sufficient")
        if source_sufficient:
            return DiagnosticClassification("OWNER_FIX_REQUIRED", "STAGE_3", True)
        return DiagnosticClassification("INPUT_REQUIRED", "INPUT", True)
    try:
        return _DIAGNOSTIC_CLASSIFICATIONS[code]
    except KeyError as error:
        raise ValueError(f"未知诊断码：{code}") from error
