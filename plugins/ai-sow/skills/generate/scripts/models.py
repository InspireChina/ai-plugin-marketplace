from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


ProjectMode = Literal["GREENFIELD", "BROWNFIELD"]
RunAction = Literal[
    "REUSE", "RENDER_ONLY", "FULL_COMPILE", "SLICE_COMPILE", "RESUME_PENDING"
]
ReviewDecision = Literal["PASS", "PASS_WITH_NOTES", "BLOCKED"]


@dataclass(frozen=True)
class SourceRequest:
    source_id: str
    role: Literal["PRD", "HLD", "PRIOR_SOW", "SUPPLEMENT"]
    path: Path
    version: str


@dataclass(frozen=True)
class InputRequest:
    project_id: str
    project_name: str
    planned_effective_date: str
    mode: ProjectMode
    responsibility_boundaries: tuple[Mapping[str, str], ...]
    sources: tuple[SourceRequest, ...]
    questionnaire_answers: tuple[Mapping[str, str], ...]
    current_state_delta: Mapping[str, object] | None


@dataclass(frozen=True)
class AnchorChange:
    source_id: str
    anchor_id: str
    change: Literal["ADDED", "MODIFIED", "REMOVED", "MOVED_UNCHANGED"]
    previous_sha256: str | None
    current_sha256: str | None


@dataclass(frozen=True)
class InputChangeSet:
    exact_match: bool
    source_changes: tuple[AnchorChange, ...]
    answer_ids: tuple[str, ...]
    responsibility_ids: tuple[str, ...]


@dataclass(frozen=True)
class ImpactPlan:
    action: RunAction
    baseline_generation_id: str | None
    baseline_revision_id: str | None
    changed_source_ids: tuple[str, ...]
    changed_anchor_ids: tuple[str, ...]
    affected_feature_ids: tuple[str, ...]
    escalation: Literal["NONE", "FEATURE", "DOMAIN", "FULL"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RunPlan:
    run_id: str
    pending_manifest_path: str
    action: RunAction
    target_revision_id: str
    target_generation_id: str | None
    impact: ImpactPlan
    scope_compiler_contract: str
    delivery_compiler_contract: str
    renderer_contract: str


@dataclass(frozen=True)
class PublicationResult:
    outcome: Literal["PUBLISHED", "REUSED", "BLOCKED"]
    decision: ReviewDecision | None
    generation_id: str | None
    revision_id: str | None
    workbook_path: str | None
    notes_path: str | None
    feature_counts: Mapping[str, int]
    recomputed_story_count: int
    recomputed_task_count: int
    questions: tuple[str, ...]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str
    details: Mapping[str, object]


@dataclass(frozen=True)
class SourceAnchor:
    anchor_id: str
    source_id: str
    kind: Literal["HEADING", "PARAGRAPH", "TABLE_ROW", "SHEET_ROW"]
    locator: str
    normalized_text: str
    sha256: str


@dataclass(frozen=True)
class IntakeResult:
    outcome: Literal["READY", "BLOCKED"]
    pending_manifest_path: str
    anchors_path: str
    changes: InputChangeSet
    diagnostics: tuple[Diagnostic, ...]
    questions: tuple[str, ...]


@dataclass(frozen=True)
class CurrentGeneration:
    generation_id: str
    revision_id: str
    manifest_path: str
    scope_path: str
    delivery_path: str
    workbook_path: str
    notes_path: str


@dataclass(frozen=True)
class ScopeCompilation:
    bundle: Mapping[str, object]
    bundle_sha256: str
    impact: ImpactPlan
    metrics: Mapping[str, int]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class BaseUnitRule:
    base_unit: str
    allowed_work_modes: tuple[str, ...]
    allowed_complexities: tuple[Literal["S", "M", "L"], ...]


@dataclass(frozen=True)
class TemplateCatalog:
    template_sha256: str
    base_units: Mapping[str, BaseUnitRule]


@dataclass(frozen=True)
class DeliveryCompilation:
    bundle: Mapping[str, object]
    bundle_sha256: str
    metrics: Mapping[str, int]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ReviewPacketResult:
    outcome: Literal["REVIEW_REQUIRED", "BLOCKED"]
    packet_path: str | None
    packet_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    questions: tuple[str, ...]


@dataclass(frozen=True)
class FinalReviewResult:
    decision: ReviewDecision
    review_path: str
    review_sha256: str
    notes: tuple[str, ...]
    questions: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class RenderedPackage:
    root: str
    workbook_path: str
    notes_path: str
    workbook_sha256: str
    notes_sha256: str
    files: tuple[str, ...]
