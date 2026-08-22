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
DISPOSITIONS = {
    "IN_SCOPE",
    "FULLY_COVERED",
    "OUT_OF_SCOPE",
    "NOT_APPLICABLE",
}
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


@dataclass(frozen=True)
class ReviewGateResult:
    concerns: dict[str, GoLiveConcern]
    diagnostics: tuple[dict[str, str], ...]


def _parse_ids(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if stripped.upper() in EMPTY_VALUES:
        return ()
    return tuple(part for part in ID_SPLITTER.split(stripped) if part)


def _has_text(value: str) -> bool:
    return value.strip().upper() not in EMPTY_VALUES


def _section_bodies(text: str, title: str) -> list[str]:
    return [
        match.group("body")
        for match in re.finditer(
            rf"(?ms)^## {re.escape(title)}[ \t]*\r?\n"
            r"(?P<body>.*?)(?=^##[ \t]+|\Z)",
            text,
        )
    ]


def _status_diagnostics(
    section: str,
    label: str,
    code_prefix: str,
) -> list[dict[str, str]]:
    statuses = re.findall(
        rf"(?m)^{re.escape(label)}\s*:\s*([^\s]+)\s*$",
        section,
    )
    if not statuses:
        return [
            diag(
                f"{code_prefix}_STATUS_MISSING",
                f"{label} must be declared inside its gate section",
            )
        ]
    if len(statuses) > 1:
        return [
            diag(
                f"{code_prefix}_STATUS_DUPLICATE",
                f"{label} must be declared exactly once inside its gate section",
            )
        ]
    if statuses[0] != "PASSED":
        return [diag(f"{code_prefix}_NOT_PASSED", f"{label} must be PASSED")]
    return []


def parse_design_review(text: str) -> ReviewGateResult:
    diagnostics: list[dict[str, str]] = []
    hld_sections = _section_bodies(text, "高阶设计覆盖门禁")
    if not hld_sections:
        diagnostics.append(
            diag("HLD_GATE_SECTION_MISSING", "review must contain 高阶设计覆盖门禁")
        )
    elif len(hld_sections) > 1:
        diagnostics.append(
            diag(
                "HLD_GATE_SECTION_DUPLICATE",
                "review must contain exactly one 高阶设计覆盖门禁 section",
            )
        )
    else:
        diagnostics.extend(
            _status_diagnostics(hld_sections[0], "HLD Coverage", "HLD_GATE")
        )

    go_live_sections = _section_bodies(text, "上线范围门禁")
    if not go_live_sections:
        diagnostics.append(
            diag("GO_LIVE_GATE_SECTION_MISSING", "review must contain 上线范围门禁")
        )
    elif len(go_live_sections) > 1:
        diagnostics.append(
            diag(
                "GO_LIVE_GATE_SECTION_DUPLICATE",
                "review must contain exactly one 上线范围门禁 section",
            )
        )
    else:
        diagnostics.extend(
            _status_diagnostics(
                go_live_sections[0],
                "Go-live Assessment",
                "GO_LIVE_GATE",
            )
        )

    matrix_text = go_live_sections[0] if len(go_live_sections) == 1 else ""
    rows: list[GoLiveConcern] = []
    header_seen = False
    for raw_line in matrix_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells == REVIEW_COLUMNS:
            header_seen = True
            continue
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if not header_seen:
            continue
        if len(cells) != len(REVIEW_COLUMNS):
            diagnostics.append(
                diag(
                    "GO_LIVE_MATRIX_ROW_INVALID",
                    f"go-live matrix row must have {len(REVIEW_COLUMNS)} columns: {line}",
                )
            )
            continue
        concern, disposition, feature_text, start_text, evidence_text, boundary, basis = cells
        if concern not in GO_LIVE_CONCERNS:
            diagnostics.append(
                diag("GO_LIVE_CONCERN_UNKNOWN", f"unknown go-live Concern: {concern}")
            )
            continue
        if disposition not in DISPOSITIONS:
            diagnostics.append(
                diag(
                    "GO_LIVE_DISPOSITION_INVALID",
                    f"invalid Disposition for {concern}: {disposition}",
                )
            )
        if not _has_text(boundary):
            diagnostics.append(
                diag(
                    "GO_LIVE_RESPONSIBILITY_MISSING",
                    f"responsibility boundary is required for {concern}",
                )
            )
        if not _has_text(basis):
            diagnostics.append(
                diag("GO_LIVE_BASIS_MISSING", f"basis is required for {concern}")
            )
        rows.append(
            GoLiveConcern(
                concern=concern,
                disposition=disposition,
                feature_ids=_parse_ids(feature_text),
                effective_start_ids=_parse_ids(start_text),
                evidence_ids=_parse_ids(evidence_text),
                responsibility_boundary=boundary,
                basis=basis,
            )
        )

    if not header_seen:
        diagnostics.append(
            diag(
                "GO_LIVE_MATRIX_HEADER_INVALID",
                "go-live matrix must use the fixed seven-column header",
            )
        )
    counts = Counter(row.concern for row in rows)
    for concern in GO_LIVE_CONCERNS:
        if counts[concern] == 0:
            diagnostics.append(
                diag("GO_LIVE_CONCERN_MISSING", f"missing go-live Concern: {concern}")
            )
        elif counts[concern] > 1:
            diagnostics.append(
                diag(
                    "GO_LIVE_CONCERN_DUPLICATE",
                    f"duplicate go-live Concern: {concern}",
                )
            )
    concerns = {row.concern: row for row in rows if counts[row.concern] == 1}
    return ReviewGateResult(concerns, tuple(diagnostics))


def _significant_length(value: object) -> int:
    return len(re.sub(r"[^\w]+", "", str(value), flags=re.UNICODE))


def _evidence_supports_start(
    start_id: str,
    starts: dict[str, dict[str, Any]],
    evidence_entries: list[dict[str, Any]],
    *,
    allowed_evidence_ids: set[str] | None = None,
) -> bool:
    start = starts.get(start_id)
    if start is None:
        return False
    supported_ids = {start_id, *start.get("sourceItemIds", [])}
    return any(
        (allowed_evidence_ids is None or entry.get("evidenceId") in allowed_evidence_ids)
        and bool(supported_ids.intersection(entry.get("supportsIds", [])))
        for entry in evidence_entries
    )


def _fully_covered_diagnostics(
    feature_id: str,
    feature_type: str,
    scope: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    start_ids = scope.get("effectiveStartItemIds", [])
    starts = {
        entry.get("effectiveStartItemId"): entry
        for entry in asis.get("effectiveStartItems", [])
        if isinstance(entry, dict)
    }
    evidence = [
        entry for entry in asis.get("evidence", []) if isinstance(entry, dict)
    ]
    if not start_ids:
        diagnostics.append(
            diag(
                "FULLY_COVERED_START_MISSING",
                f"FULLY_COVERED Feature must reference Effective Start: {feature_id}",
            )
        )
    for start_id in start_ids:
        if start_id in starts and not _evidence_supports_start(
            start_id,
            starts,
            evidence,
        ):
            diagnostics.append(
                diag(
                    "FULLY_COVERED_EVIDENCE_MISSING",
                    f"Effective Start lacks supporting Evidence for {feature_id}: {start_id}",
                )
            )
    rationale = str(scope.get("rationale", ""))
    if (
        _significant_length(rationale) < 16
        or rationale.strip().casefold() in GENERIC_RATIONALES
    ):
        diagnostics.append(
            diag(
                "FULLY_COVERED_RATIONALE_GENERIC",
                f"FULLY_COVERED rationale must explain complete target coverage: {feature_id}",
            )
        )
    if feature_type == "BUSINESS":
        coverage = [
            entry
            for entry in asis.get("coverage", [])
            if isinstance(entry, dict) and entry.get("featureId") == feature_id
        ]
        if (
            len(coverage) != 1
            or coverage[0].get("status") != "COMPLETE"
            or set(coverage[0].get("effectiveStartItemIds", [])) != set(start_ids)
        ):
            diagnostics.append(
                diag(
                    "FULLY_COVERED_COVERAGE_INVALID",
                    "BUSINESS FULLY_COVERED Feature requires one COMPLETE Coverage "
                    f"with the same Effective Start references: {feature_id}",
                )
            )
    return diagnostics


def validate_hld_coverage(
    feature_types: dict[str, str],
    scopes: dict[str, dict[str, Any]],
    design: dict[str, Any],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    design_item_ids = {
        entry.get("designItemId")
        for entry in design.get("designItems", [])
        if isinstance(entry, dict)
    }
    effective_start_ids = {
        entry.get("effectiveStartItemId")
        for entry in asis.get("effectiveStartItems", [])
        if isinstance(entry, dict)
    }

    def validate_references(
        references: object,
        known: set[object],
        code: str,
        owner: str,
    ) -> None:
        if not isinstance(references, list):
            return
        for reference in references:
            if isinstance(reference, str) and reference not in known:
                diagnostics.append(
                    diag(code, f"unknown reference from {owner}: {reference}")
                )

    scope_counts = Counter(
        entry.get("featureId")
        for entry in design.get("scopeDecisions", [])
        if isinstance(entry, dict)
    )
    for feature_id in feature_types:
        if scope_counts[feature_id] == 0:
            diagnostics.append(
                diag("SCOPE_MISSING", f"missing scope decision: {feature_id}")
            )
        elif scope_counts[feature_id] > 1:
            diagnostics.append(
                diag("SCOPE_DUPLICATE", f"duplicate scope decision: {feature_id}")
            )
    for feature_id, scope in scopes.items():
        if feature_id not in feature_types:
            diagnostics.append(
                diag("FEATURE_REF_UNKNOWN", f"unknown scoped Feature: {feature_id}")
            )
            continue
        validate_references(
            scope.get("designItemIds", []),
            design_item_ids,
            "DESIGN_ITEM_REF_UNKNOWN",
            f"ScopeDecision {feature_id}",
        )
        validate_references(
            scope.get("effectiveStartItemIds", []),
            effective_start_ids,
            "EFFECTIVE_START_REF_UNKNOWN",
            f"ScopeDecision {feature_id}",
        )
        if scope.get("decision") == "IN_SCOPE" and not scope.get("designItemIds"):
            diagnostics.append(
                diag(
                    "IN_SCOPE_DESIGN_COVERAGE_MISSING",
                    f"IN_SCOPE Feature must reference a DesignItem: {feature_id}",
                )
            )
        if scope.get("decision") == "FULLY_COVERED":
            diagnostics.extend(
                _fully_covered_diagnostics(
                    feature_id,
                    feature_types[feature_id],
                    scope,
                    asis,
                )
            )

    carry_forward_ids = {
        entry.get("commitmentId")
        for entry in asis.get("commitments", [])
        if isinstance(entry, dict) and entry.get("treatment") == "CARRY_FORWARD"
    }
    carry_forward_features = {
        feature_id
        for entry in asis.get("commitments", [])
        if isinstance(entry, dict) and entry.get("commitmentId") in carry_forward_ids
        for feature_id in entry.get("relatedFeatureIds", [])
    }
    for coverage in asis.get("coverage", []):
        if isinstance(coverage, dict) and carry_forward_ids.intersection(
            coverage.get("commitmentIds", [])
        ):
            carry_forward_features.add(coverage.get("featureId"))
    for feature_id in carry_forward_features:
        if scopes.get(feature_id, {}).get("decision") == "FULLY_COVERED":
            diagnostics.append(
                diag(
                    "CARRY_FORWARD_SCOPE_INVALID",
                    f"CARRY_FORWARD work cannot be FULLY_COVERED: {feature_id}",
                )
            )

    for uncertainty in asis.get("uncertainties", []):
        if isinstance(uncertainty, dict) and uncertainty.get("affectsEstimate") is True:
            diagnostics.append(
                diag(
                    "ESTIMATE_UNCERTAINTY_UNRESOLVED",
                    "estimate-affecting uncertainty blocks HLD coverage: "
                    f"{uncertainty.get('uncertaintyId', '<unknown>')}",
                )
            )

    referenced_design_items: set[str] = set()
    for scope in design.get("scopeDecisions", []):
        if isinstance(scope, dict):
            referenced_design_items.update(scope.get("designItemIds", []))
    for decision in design.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        item_references = decision.get("designItemIds", [])
        feature_references = decision.get("relatedFeatureIds", [])
        referenced_design_items.update(item_references)
        decision_id = decision.get("designDecisionId", "<unknown>")
        validate_references(
            item_references,
            design_item_ids,
            "DESIGN_ITEM_REF_UNKNOWN",
            f"DesignDecision {decision_id}",
        )
        validate_references(
            feature_references,
            set(feature_types),
            "FEATURE_REF_UNKNOWN",
            f"DesignDecision {decision_id}",
        )
        validate_references(
            decision.get("effectiveStartItemIds", []),
            effective_start_ids,
            "EFFECTIVE_START_REF_UNKNOWN",
            f"DesignDecision {decision_id}",
        )
        if not item_references:
            diagnostics.append(
                diag(
                    "DESIGN_DECISION_ITEM_MISSING",
                    "DesignDecision must reference a DesignItem: "
                    f"{decision.get('designDecisionId', '<unknown>')}",
                )
            )
        if not feature_references:
            diagnostics.append(
                diag(
                    "DESIGN_DECISION_FEATURE_MISSING",
                    "DesignDecision must reference a Feature: "
                    f"{decision.get('designDecisionId', '<unknown>')}",
                )
            )
    for delta in design.get("architectureDeltas", []):
        if not isinstance(delta, dict):
            continue
        design_item_id = delta.get("designItemId")
        delta_id = delta.get("architectureDeltaId", "<unknown>")
        if isinstance(design_item_id, str):
            referenced_design_items.add(design_item_id)
            if design_item_id not in design_item_ids:
                diagnostics.append(
                    diag(
                        "DESIGN_ITEM_REF_UNKNOWN",
                        f"unknown reference from ArchitectureDelta {delta_id}: "
                        f"{design_item_id}",
                    )
                )
        validate_references(
            delta.get("effectiveStartItemIds", []),
            effective_start_ids,
            "EFFECTIVE_START_REF_UNKNOWN",
            f"ArchitectureDelta {delta_id}",
        )
        if delta.get("changeType") != "NEW" and not delta.get("effectiveStartItemIds"):
            diagnostics.append(
                diag(
                    "ARCHITECTURE_DELTA_START_MISSING",
                    "non-NEW ArchitectureDelta must reference Effective Start: "
                    f"{delta.get('architectureDeltaId', '<unknown>')}",
                )
            )
    for design_item_id in sorted(design_item_ids - referenced_design_items):
        diagnostics.append(
            diag(
                "DESIGN_ITEM_ORPHANED",
                f"DesignItem must be referenced by scope, decision, or delta: {design_item_id}",
            )
        )
    return diagnostics


def validate_go_live_matrix(
    concerns: dict[str, GoLiveConcern],
    feature_types: dict[str, str],
    scopes: dict[str, dict[str, Any]],
    asis: dict[str, Any],
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    starts = {
        entry.get("effectiveStartItemId"): entry
        for entry in asis.get("effectiveStartItems", [])
        if isinstance(entry, dict)
    }
    evidence = {
        entry.get("evidenceId"): entry
        for entry in asis.get("evidence", [])
        if isinstance(entry, dict)
    }
    for concern_name, row in concerns.items():
        if concern_name == "PRODUCTION_SCOPE" and row.disposition == "NOT_APPLICABLE":
            diagnostics.append(
                diag(
                    "PRODUCTION_SCOPE_NOT_APPLICABLE",
                    "PRODUCTION_SCOPE must not be NOT_APPLICABLE",
                )
            )
        if row.disposition in {"IN_SCOPE", "FULLY_COVERED"} and not row.feature_ids:
            diagnostics.append(
                diag(
                    "GO_LIVE_FEATURE_MISSING",
                    f"{row.disposition} Concern must reference a Feature: {concern_name}",
                )
            )
        for feature_id in row.feature_ids:
            if feature_id not in feature_types:
                diagnostics.append(
                    diag(
                        "FEATURE_REF_UNKNOWN",
                        f"unknown go-live Feature for {concern_name}: {feature_id}",
                    )
                )
                continue
            scope = scopes.get(feature_id)
            if scope is None:
                diagnostics.append(
                    diag(
                        "SCOPE_MISSING",
                        f"go-live Feature lacks ScopeDecision: {feature_id}",
                    )
                )
            elif row.disposition != "NOT_APPLICABLE" and scope.get("decision") != row.disposition:
                diagnostics.append(
                    diag(
                        "GO_LIVE_SCOPE_MISMATCH",
                        f"Concern and ScopeDecision disagree for {feature_id}: "
                        f"{row.disposition}/{scope.get('decision')}",
                    )
                )
        if row.disposition == "FULLY_COVERED":
            scope_start_union = {
                start_id
                for feature_id in row.feature_ids
                for scope in [scopes.get(feature_id)]
                if scope is not None and scope.get("decision") == "FULLY_COVERED"
                for start_id in scope.get("effectiveStartItemIds", [])
            }
            if set(row.effective_start_ids) != scope_start_union:
                diagnostics.append(
                    diag(
                        "GO_LIVE_SCOPE_START_MISMATCH",
                        "Concern Effective Start references must equal the union of "
                        f"its ScopeDecision references: {concern_name}",
                    )
                )
        if row.disposition == "IN_SCOPE" and not any(
            feature_types.get(feature_id) == "TECHNICAL"
            for feature_id in row.feature_ids
        ):
            diagnostics.append(
                diag(
                    "GO_LIVE_TECHNICAL_FEATURE_MISSING",
                    f"IN_SCOPE Concern needs a TECHNICAL Feature: {concern_name}",
                )
            )
        if row.disposition == "FULLY_COVERED":
            if not row.effective_start_ids or not row.evidence_ids:
                diagnostics.append(
                    diag(
                        "GO_LIVE_FULLY_COVERED_PROOF_MISSING",
                        f"FULLY_COVERED Concern needs Effective Start and Evidence: {concern_name}",
                    )
                )
            allowed_evidence_ids = set(row.evidence_ids)
            for evidence_id in row.evidence_ids:
                if evidence_id not in evidence:
                    diagnostics.append(
                        diag(
                            "EVIDENCE_REF_UNKNOWN",
                            f"unknown Evidence for {concern_name}: {evidence_id}",
                        )
                    )
            evidence_entries = list(evidence.values())
            for start_id in row.effective_start_ids:
                if start_id not in starts:
                    diagnostics.append(
                        diag(
                            "EFFECTIVE_START_REF_UNKNOWN",
                            f"unknown Effective Start for {concern_name}: {start_id}",
                        )
                    )
                elif not _evidence_supports_start(
                    start_id,
                    starts,
                    evidence_entries,
                    allowed_evidence_ids=allowed_evidence_ids,
                ):
                    diagnostics.append(
                        diag(
                            "GO_LIVE_EVIDENCE_MISMATCH",
                            f"listed Evidence does not support {start_id} for {concern_name}",
                        )
                    )

    production = concerns.get("PRODUCTION_SCOPE")
    if production is not None:
        if not production.feature_ids or not any(
            feature_types.get(feature_id) == "TECHNICAL"
            for feature_id in production.feature_ids
        ):
            diagnostics.append(
                diag(
                    "PRODUCTION_SCOPE_FEATURE_MISSING",
                    "PRODUCTION_SCOPE must reference a TECHNICAL Feature",
                )
            )
    migration = concerns.get("DATA_MIGRATION")
    if (
        production is not None
        and migration is not None
        and migration.disposition == "IN_SCOPE"
        and set(production.feature_ids).intersection(migration.feature_ids)
    ):
        diagnostics.append(
            diag(
                "DATA_MIGRATION_FEATURE_NOT_INDEPENDENT",
                "DATA_MIGRATION must use a Feature independent from PRODUCTION_SCOPE",
            )
        )
    return diagnostics


def validate_design_gates(
    source: dict[str, Any],
    technical: dict[str, Any],
    design: dict[str, Any],
    asis: dict[str, Any],
    review_text: str,
) -> list[dict[str, str]]:
    parsed = parse_design_review(review_text)
    feature_types = {
        **{
            feature["featureId"]: "BUSINESS"
            for feature in source.get("features", [])
            if isinstance(feature, dict) and isinstance(feature.get("featureId"), str)
        },
        **{
            feature["featureId"]: "TECHNICAL"
            for feature in technical.get("features", [])
            if isinstance(feature, dict) and isinstance(feature.get("featureId"), str)
        },
    }
    scopes = {
        scope["featureId"]: scope
        for scope in design.get("scopeDecisions", [])
        if isinstance(scope, dict) and isinstance(scope.get("featureId"), str)
    }
    diagnostics = list(parsed.diagnostics)
    diagnostics.extend(validate_hld_coverage(feature_types, scopes, design, asis))
    diagnostics.extend(
        validate_go_live_matrix(parsed.concerns, feature_types, scopes, asis)
    )
    return diagnostics
