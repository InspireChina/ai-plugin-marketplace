from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


GO_LIVE_CONCERNS = (
    "PRODUCTION_SCOPE",
    "ENVIRONMENT_CONFIGURATION",
    "DEPLOYMENT_CUTOVER_ROLLBACK",
    "DATA_MIGRATION",
    "PRODUCTION_VALIDATION",
    "OBSERVABILITY",
    "OPERATIONS_HANDOVER",
    "POST_GO_LIVE_SUPPORT",
    "USER_ENABLEMENT",
    "LEGACY_RETIREMENT",
)
REVIEW_COLUMNS = (
    "Concern",
    "Disposition",
    "Feature IDs",
    "Effective Start IDs",
    "Evidence IDs",
    "责任边界",
    "依据",
)
DISPOSITIONS = {"IN_SCOPE", "FULLY_COVERED", "OUT_OF_SCOPE", "NOT_APPLICABLE"}
EMPTY_VALUES = {"", "-", "—", "N/A", "NONE", "NOT_APPLICABLE"}
GENERIC_RATIONALES = {
    "已覆盖",
    "完全覆盖",
    "现状满足",
    "无需交付",
    "already covered",
    "fully covered",
}
ID_SPLITTER = re.compile(r"(?:<br\s*/?>|[,，、;；\s]+)", re.IGNORECASE)


def diag(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@dataclass(frozen=True)
class GoLiveConcern:
    concern: str
    disposition: str
    feature_ids: tuple[str, ...]
    effective_start_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    responsibility_boundary: str
    basis: str


def _section_bodies(text: str, title: str) -> list[str]:
    return [
        match.group("body")
        for match in re.finditer(
            rf"(?ms)^## {re.escape(title)}[ \t]*\r?\n(?P<body>.*?)(?=^##[ \t]+|\Z)",
            text,
        )
    ]


def _gate_status(section: str, label: str, prefix: str) -> list[dict[str, str]]:
    values = re.findall(rf"(?m)^{re.escape(label)}\s*:\s*([^\s]+)\s*$", section)
    if not values:
        return [diag(f"{prefix}_STATUS_MISSING", f"{label} must be declared inside its gate section")]
    if len(values) != 1:
        return [diag(f"{prefix}_STATUS_DUPLICATE", f"{label} must be declared exactly once")]
    return [] if values[0] == "PASSED" else [diag(f"{prefix}_NOT_PASSED", f"{label} must be PASSED")]


def _ids(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    return () if stripped.upper() in EMPTY_VALUES else tuple(part for part in ID_SPLITTER.split(stripped) if part)


def parse_design_review(text: str) -> tuple[dict[str, GoLiveConcern], list[dict[str, str]]]:
    diagnostics: list[dict[str, str]] = []
    hld = _section_bodies(text, "高阶设计覆盖门禁")
    if not hld:
        diagnostics.append(diag("HLD_GATE_SECTION_MISSING", "review must contain 高阶设计覆盖门禁"))
    elif len(hld) != 1:
        diagnostics.append(diag("HLD_GATE_SECTION_DUPLICATE", "review must contain one 高阶设计覆盖门禁"))
    else:
        diagnostics.extend(_gate_status(hld[0], "HLD Coverage", "HLD_GATE"))
    go_live = _section_bodies(text, "上线范围门禁")
    if not go_live:
        diagnostics.append(diag("GO_LIVE_GATE_SECTION_MISSING", "review must contain 上线范围门禁"))
    elif len(go_live) != 1:
        diagnostics.append(diag("GO_LIVE_GATE_SECTION_DUPLICATE", "review must contain one 上线范围门禁"))
    else:
        diagnostics.extend(_gate_status(go_live[0], "Go-live Assessment", "GO_LIVE_GATE"))

    rows: list[GoLiveConcern] = []
    header_seen = False
    for raw in (go_live[0] if len(go_live) == 1 else "").splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells == REVIEW_COLUMNS:
            header_seen = True
            continue
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if not header_seen:
            continue
        if len(cells) != 7:
            diagnostics.append(diag("GO_LIVE_MATRIX_ROW_INVALID", f"go-live matrix row must have seven columns: {line}"))
            continue
        concern, disposition, feature_text, start_text, evidence_text, boundary, basis = cells
        if concern not in GO_LIVE_CONCERNS:
            diagnostics.append(diag("GO_LIVE_CONCERN_UNKNOWN", f"unknown go-live Concern: {concern}"))
            continue
        if disposition not in DISPOSITIONS:
            diagnostics.append(diag("GO_LIVE_DISPOSITION_INVALID", f"invalid Disposition for {concern}: {disposition}"))
        if boundary.strip().upper() in EMPTY_VALUES:
            diagnostics.append(diag("GO_LIVE_RESPONSIBILITY_MISSING", f"responsibility boundary is required for {concern}"))
        if basis.strip().upper() in EMPTY_VALUES:
            diagnostics.append(diag("GO_LIVE_BASIS_MISSING", f"basis is required for {concern}"))
        rows.append(GoLiveConcern(concern, disposition, _ids(feature_text), _ids(start_text), _ids(evidence_text), boundary, basis))
    if not header_seen:
        diagnostics.append(diag("GO_LIVE_MATRIX_HEADER_INVALID", "go-live matrix must use the fixed seven-column header"))
    counts = Counter(row.concern for row in rows)
    for concern in GO_LIVE_CONCERNS:
        if counts[concern] == 0:
            diagnostics.append(diag("GO_LIVE_CONCERN_MISSING", f"missing go-live Concern: {concern}"))
        elif counts[concern] > 1:
            diagnostics.append(diag("GO_LIVE_CONCERN_DUPLICATE", f"duplicate go-live Concern: {concern}"))
    return {row.concern: row for row in rows if counts[row.concern] == 1}, diagnostics


def _evidence_supports_start(
    start_id: str,
    starts: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    allowed: set[str] | None = None,
) -> bool:
    start = starts.get(start_id)
    if start is None:
        return False
    supported = {start_id, *start.get("sourceItemIds", [])}
    return any(
        (allowed is None or entry.get("evidenceId") in allowed)
        and bool(supported.intersection(entry.get("supportsIds", [])))
        for entry in evidence
    )


def _fully_covered(
    feature_id: str,
    feature_type: str,
    scope: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    start_ids = scope.get("effectiveStartItemIds", [])
    starts = {entry.get("effectiveStartItemId"): entry for entry in asis.get("effectiveStartItems", []) if isinstance(entry, dict)}
    evidence = [entry for entry in asis.get("evidence", []) if isinstance(entry, dict)]
    if not start_ids:
        diagnostics.append(diag("FULLY_COVERED_START_MISSING", f"FULLY_COVERED Feature must reference Effective Start: {feature_id}"))
    for start_id in start_ids:
        if start_id in starts and not _evidence_supports_start(start_id, starts, evidence):
            diagnostics.append(diag("FULLY_COVERED_EVIDENCE_MISSING", f"Effective Start lacks supporting Evidence for {feature_id}: {start_id}"))
    rationale = str(scope.get("rationale", ""))
    if len(re.sub(r"[^\w]+", "", rationale, flags=re.UNICODE)) < 16 or rationale.strip().casefold() in GENERIC_RATIONALES:
        diagnostics.append(diag("FULLY_COVERED_RATIONALE_GENERIC", f"FULLY_COVERED rationale must explain complete target coverage: {feature_id}"))
    if feature_type == "BUSINESS":
        coverage = [entry for entry in asis.get("coverage", []) if isinstance(entry, dict) and entry.get("featureId") == feature_id]
        if len(coverage) != 1 or coverage[0].get("status") != "COMPLETE" or set(coverage[0].get("effectiveStartItemIds", [])) != set(start_ids):
            diagnostics.append(diag("FULLY_COVERED_COVERAGE_INVALID", f"BUSINESS FULLY_COVERED requires matching COMPLETE Coverage: {feature_id}"))
    return diagnostics


def validate_hld_coverage(
    feature_types: dict[str, str],
    scopes: dict[str, dict[str, Any]],
    design: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    item_ids = {entry.get("designItemId") for entry in design.get("designItems", []) if isinstance(entry, dict)}
    start_ids = {entry.get("effectiveStartItemId") for entry in asis.get("effectiveStartItems", []) if isinstance(entry, dict)}

    def refs(values: object, known: set[object], code: str, owner: str) -> None:
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value not in known:
                    diagnostics.append(diag(code, f"unknown reference from {owner}: {value}"))

    counts = Counter(entry.get("featureId") for entry in design.get("scopeDecisions", []) if isinstance(entry, dict))
    for feature_id in feature_types:
        if counts[feature_id] == 0:
            diagnostics.append(diag("SCOPE_MISSING", f"missing scope decision: {feature_id}"))
        elif counts[feature_id] > 1:
            diagnostics.append(diag("SCOPE_DUPLICATE", f"duplicate scope decision: {feature_id}"))
    for feature_id, scope in scopes.items():
        if feature_id not in feature_types:
            diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown scoped Feature: {feature_id}"))
            continue
        refs(scope.get("designItemIds", []), item_ids, "DESIGN_ITEM_REF_UNKNOWN", f"ScopeDecision {feature_id}")
        refs(scope.get("effectiveStartItemIds", []), start_ids, "EFFECTIVE_START_REF_UNKNOWN", f"ScopeDecision {feature_id}")
        if scope.get("decision") == "IN_SCOPE" and not scope.get("designItemIds"):
            diagnostics.append(diag("IN_SCOPE_DESIGN_COVERAGE_MISSING", f"IN_SCOPE Feature must reference a DesignItem: {feature_id}"))
        if scope.get("decision") == "FULLY_COVERED":
            diagnostics.extend(_fully_covered(feature_id, feature_types[feature_id], scope, asis))

    carry_forward = {
        feature_id
        for commitment in asis.get("commitments", [])
        if isinstance(commitment, dict) and commitment.get("treatment") == "CARRY_FORWARD"
        for feature_id in commitment.get("relatedFeatureIds", [])
    }
    for feature_id in carry_forward:
        if scopes.get(feature_id, {}).get("decision") == "FULLY_COVERED":
            diagnostics.append(diag("CARRY_FORWARD_SCOPE_INVALID", f"CARRY_FORWARD work cannot be FULLY_COVERED: {feature_id}"))
    for uncertainty in asis.get("uncertainties", []):
        if isinstance(uncertainty, dict) and uncertainty.get("affectsEstimate") is True:
            diagnostics.append(diag("ESTIMATE_UNCERTAINTY_UNRESOLVED", f"estimate-affecting uncertainty blocks HLD coverage: {uncertainty.get('uncertaintyId', '<unknown>')}"))

    referenced: set[str] = set()
    for scope in design.get("scopeDecisions", []):
        if isinstance(scope, dict):
            referenced.update(scope.get("designItemIds", []))
    for decision in design.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        decision_id = str(decision.get("designDecisionId", "<unknown>"))
        items = decision.get("designItemIds", [])
        features = decision.get("relatedFeatureIds", [])
        referenced.update(items)
        refs(items, item_ids, "DESIGN_ITEM_REF_UNKNOWN", f"DesignDecision {decision_id}")
        refs(features, set(feature_types), "FEATURE_REF_UNKNOWN", f"DesignDecision {decision_id}")
        refs(decision.get("effectiveStartItemIds", []), start_ids, "EFFECTIVE_START_REF_UNKNOWN", f"DesignDecision {decision_id}")
        if not items:
            diagnostics.append(diag("DESIGN_DECISION_ITEM_MISSING", f"DesignDecision must reference a DesignItem: {decision_id}"))
        if not features:
            diagnostics.append(diag("DESIGN_DECISION_FEATURE_MISSING", f"DesignDecision must reference a Feature: {decision_id}"))
    for delta in design.get("architectureDeltas", []):
        if not isinstance(delta, dict):
            continue
        delta_id = str(delta.get("architectureDeltaId", "<unknown>"))
        item_id = delta.get("designItemId")
        if isinstance(item_id, str):
            referenced.add(item_id)
            refs([item_id], item_ids, "DESIGN_ITEM_REF_UNKNOWN", f"ArchitectureDelta {delta_id}")
        refs(delta.get("effectiveStartItemIds", []), start_ids, "EFFECTIVE_START_REF_UNKNOWN", f"ArchitectureDelta {delta_id}")
        if delta.get("changeType") != "NEW" and not delta.get("effectiveStartItemIds"):
            diagnostics.append(diag("ARCHITECTURE_DELTA_START_MISSING", f"non-NEW ArchitectureDelta must reference Effective Start: {delta_id}"))
    for item_id in sorted(value for value in item_ids - referenced if isinstance(value, str)):
        diagnostics.append(diag("DESIGN_ITEM_ORPHANED", f"DesignItem must be referenced by scope, decision, or delta: {item_id}"))
    return diagnostics


def validate_go_live_matrix(
    concerns: dict[str, GoLiveConcern],
    feature_types: dict[str, str],
    scopes: dict[str, dict[str, Any]],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    starts = {entry.get("effectiveStartItemId"): entry for entry in asis.get("effectiveStartItems", []) if isinstance(entry, dict)}
    evidence = {entry.get("evidenceId"): entry for entry in asis.get("evidence", []) if isinstance(entry, dict)}
    for concern_name, row in concerns.items():
        if concern_name == "PRODUCTION_SCOPE" and row.disposition == "NOT_APPLICABLE":
            diagnostics.append(diag("PRODUCTION_SCOPE_NOT_APPLICABLE", "PRODUCTION_SCOPE must not be NOT_APPLICABLE"))
        if row.disposition in {"IN_SCOPE", "FULLY_COVERED"} and not row.feature_ids:
            diagnostics.append(diag("GO_LIVE_FEATURE_MISSING", f"{row.disposition} Concern must reference a Feature: {concern_name}"))
        for feature_id in row.feature_ids:
            if feature_id not in feature_types:
                diagnostics.append(diag("FEATURE_REF_UNKNOWN", f"unknown go-live Feature for {concern_name}: {feature_id}"))
                continue
            scope = scopes.get(feature_id)
            if scope is None:
                diagnostics.append(diag("SCOPE_MISSING", f"go-live Feature lacks ScopeDecision: {feature_id}"))
            elif row.disposition != "NOT_APPLICABLE" and scope.get("decision") != row.disposition:
                diagnostics.append(diag("GO_LIVE_SCOPE_MISMATCH", f"Concern and ScopeDecision disagree for {feature_id}: {row.disposition}/{scope.get('decision')}"))
        if row.disposition == "IN_SCOPE" and not any(feature_types.get(value) == "TECHNICAL" for value in row.feature_ids):
            diagnostics.append(diag("GO_LIVE_TECHNICAL_FEATURE_MISSING", f"IN_SCOPE Concern needs a TECHNICAL Feature: {concern_name}"))
        if row.disposition == "FULLY_COVERED":
            union = {
                start_id
                for feature_id in row.feature_ids
                for scope in [scopes.get(feature_id)]
                if scope is not None and scope.get("decision") == "FULLY_COVERED"
                for start_id in scope.get("effectiveStartItemIds", [])
            }
            if set(row.effective_start_ids) != union:
                diagnostics.append(diag("GO_LIVE_SCOPE_START_MISMATCH", f"Concern Effective Start references must equal ScopeDecision references: {concern_name}"))
            if not row.effective_start_ids or not row.evidence_ids:
                diagnostics.append(diag("GO_LIVE_FULLY_COVERED_PROOF_MISSING", f"FULLY_COVERED Concern needs Effective Start and Evidence: {concern_name}"))
            allowed = set(row.evidence_ids)
            for evidence_id in row.evidence_ids:
                if evidence_id not in evidence:
                    diagnostics.append(diag("EVIDENCE_REF_UNKNOWN", f"unknown Evidence for {concern_name}: {evidence_id}"))
            for start_id in row.effective_start_ids:
                if start_id not in starts:
                    diagnostics.append(diag("EFFECTIVE_START_REF_UNKNOWN", f"unknown Effective Start for {concern_name}: {start_id}"))
                elif not _evidence_supports_start(start_id, starts, list(evidence.values()), allowed):
                    diagnostics.append(diag("GO_LIVE_EVIDENCE_MISMATCH", f"listed Evidence does not support {start_id} for {concern_name}"))
    production = concerns.get("PRODUCTION_SCOPE")
    if production is not None and (not production.feature_ids or not any(feature_types.get(value) == "TECHNICAL" for value in production.feature_ids)):
        diagnostics.append(diag("PRODUCTION_SCOPE_FEATURE_MISSING", "PRODUCTION_SCOPE must reference a TECHNICAL Feature"))
    migration = concerns.get("DATA_MIGRATION")
    if production is not None and migration is not None and migration.disposition == "IN_SCOPE" and set(production.feature_ids).intersection(migration.feature_ids):
        diagnostics.append(diag("DATA_MIGRATION_FEATURE_NOT_INDEPENDENT", "DATA_MIGRATION must use a Feature independent from PRODUCTION_SCOPE"))
    return diagnostics


def validate_design_gates(
    source: dict[str, Any],
    technical: dict[str, Any],
    design: dict[str, Any],
    asis: dict[str, Any],
    review_text: str,
) -> list[dict[str, str]]:
    concerns, diagnostics = parse_design_review(review_text)
    feature_types = {
        **{entry["featureId"]: "BUSINESS" for entry in source.get("features", []) if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)},
        **{entry["featureId"]: "TECHNICAL" for entry in technical.get("features", []) if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)},
    }
    scopes = {entry["featureId"]: entry for entry in design.get("scopeDecisions", []) if isinstance(entry, dict) and isinstance(entry.get("featureId"), str)}
    diagnostics.extend(validate_hld_coverage(feature_types, scopes, design, asis))
    diagnostics.extend(validate_go_live_matrix(concerns, feature_types, scopes, asis))
    return diagnostics
