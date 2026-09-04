from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


ReviewDecision = Literal["PASS", "PASS_WITH_NOTES", "BLOCKED"]


@dataclass(frozen=True)
class PublicationResult:
    outcome: Literal["PUBLISHED", "REUSED", "BLOCKED"]
    decision: ReviewDecision | None
    generation_id: str | None
    revision_id: str | None
    workbook_path: str | None
    notes_path: str | None
    change_counts: Mapping[str, Mapping[str, int]]
    questions: tuple[str, ...]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str
    details: Mapping[str, object]


@dataclass(frozen=True)
class DiagnosticClassification:
    category: Literal[
        "INPUT_REQUIRED",
        "OWNER_FIX_REQUIRED",
        "CONTRACT_UNSUPPORTED",
        "SYSTEM_FAILED",
        "CONTROL",
    ]
    owner: Literal[
        "INPUT", "STAGE_1", "STAGE_2", "STAGE_3", "REVIEW", "PUBLISH", "ORCHESTRATOR"
    ]
    retryable: bool


# The persisted mapping remains authoritative and is validated against JSON Schema.
# These frozen DTOs only make module boundaries explicit; they do not duplicate the
# persisted contracts as mutable Python object graphs.
@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    role: str
    raw_sha256: str
    parser_id: str
    parser_version: str
    blocks: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class InputRevisionResult:
    value: Mapping[str, object] | None
    path: str | None
    sha256: str | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ActionEnvelope:
    value: Mapping[str, object]
    path: str
    sha256: str


@dataclass(frozen=True)
class ActionRecord:
    value: Mapping[str, object]
    path: str
    sha256: str


@dataclass(frozen=True)
class RunState:
    value: Mapping[str, object]


@dataclass(frozen=True)
class RouteDecision:
    route: Literal["REUSE", "RENDER_ONLY", "FULL_COMPILE", "DELTA_COMPILE"]
    lowest_recovery_stage: Literal[
        "STAGE_1", "STAGE_2", "STAGE_3", "REVIEW", "RENDER"
    ] | None
    changed: tuple[str, ...]
    reused: tuple[str, ...]
    invalidated: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    proof_sha256: str


@dataclass(frozen=True)
class CompilerProgress:
    outcome: Literal["ACTION_REQUIRED", "CHECKPOINT_READY", "INPUT_REQUIRED", "FAILED"]
    expected_action_ids: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class CompilerResult:
    model: Mapping[str, object]
    model_sha256: str
    checkpoint: Mapping[str, object]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ReplacementOutcome:
    candidate: Mapping[str, object]
    candidate_sha256: str
    active_projection: Mapping[str, object]
    active_projection_sha256: str
    proof_sha256: str
    changed_node_ids: tuple[str, ...]
    reused_node_ids: tuple[str, ...]
    invalidated_node_ids: tuple[str, ...]
    invalidated_checkpoint_ids: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ReviewProgress:
    outcome: Literal["ACTION_REQUIRED", "PASS", "OWNER_FIX_REQUIRED", "INPUT_REQUIRED", "FAILED"]
    expected_action_ids: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class TaskStandardCatalog:
    template_sha256: str
    semantic_sha256: str
    rows: tuple[Mapping[str, object], ...]
    by_work_type_id: Mapping[str, Mapping[str, object]]

    @property
    def task_catalog_semantic_sha256(self) -> str:
        return self.semantic_sha256


@dataclass(frozen=True)
class CatalogHydration:
    requested_work_type_ids: tuple[str, ...]
    query_terms: tuple[str, ...]
    candidate_work_type_ids: tuple[str, ...]
    neighbor_work_type_ids: tuple[str, ...]
    challenger_work_type_ids: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]
    semantic_sha256: str
    evidence: Mapping[str, object]

    @property
    def selected_work_type_ids(self) -> tuple[str, ...]:
        return self.requested_work_type_ids

    @property
    def task_catalog_semantic_sha256(self) -> str:
        return self.semantic_sha256


@dataclass(frozen=True)
class SourceAnchor:
    anchor_id: str
    source_id: str
    kind: Literal[
        "HEADING", "PARAGRAPH", "TABLE_ROW", "SHEET_ROW", "QUESTION_ANSWER"
    ]
    locator: str
    normalized_text: str
    sha256: str


@dataclass(frozen=True)
class CurrentGeneration:
    generation_id: str
    manifest_path: str
    workbook_path: str
    notes_path: str


@dataclass(frozen=True)
class WorkbookAudit:
    trust_state: Literal["CANDIDATE", "VERIFIED"]
    story_count: int
    task_count: int
    direct_days: float | None
    sit_days: float | None
    uat_days: float | None
    total_days: float | None
    parameter_statuses: tuple[tuple[str, str], ...]
    formula_errors: tuple[str, ...]
    engine_name: str | None
    engine_version: str | None


def workbook_audit_value(
    audit: WorkbookAudit, *, require_verified: bool = False
) -> dict[str, object]:
    if require_verified and (
        audit.trust_state != "VERIFIED"
        or audit.engine_name is None
        or audit.engine_version is None
        or audit.direct_days is None
        or audit.sit_days is None
        or audit.uat_days is None
        or audit.total_days is None
    ):
        raise ValueError("workbook audit is not verified")
    return {
        "trustState": audit.trust_state,
        "engine": {"name": audit.engine_name, "version": audit.engine_version},
        "storyCount": audit.story_count,
        "taskCount": audit.task_count,
        "directDays": audit.direct_days,
        "sitDays": audit.sit_days,
        "uatDays": audit.uat_days,
        "totalDays": audit.total_days,
        "parameterStatuses": [
            {"code": code, "status": status}
            for code, status in audit.parameter_statuses
        ],
        "formulaErrors": list(audit.formula_errors),
    }


@dataclass(frozen=True)
class OfficeRoundtrip:
    engine: Mapping[str, str]
    output_path: str


@dataclass(frozen=True)
class RenderedPackage:
    root: str
    workbook_path: str
    notes_path: str
    workbook_sha256: str
    notes_sha256: str
    files: tuple[str, ...]
    workbook_audit: WorkbookAudit
