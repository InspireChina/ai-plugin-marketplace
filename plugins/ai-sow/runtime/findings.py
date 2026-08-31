from __future__ import annotations

from typing import Literal


OwnerName = Literal[
    "analyze-requirement",
    "analyze-as-is",
    "generate-design",
    "generate-story",
    "generate-task",
]
FindingCategory = Literal["LOCAL", "UPSTREAM", "DECISION", "MECHANICAL"]

OWNER_NAMES = frozenset(
    {
        "analyze-requirement",
        "analyze-as-is",
        "generate-design",
        "generate-story",
        "generate-task",
    }
)
FINDING_CATEGORIES = frozenset({"LOCAL", "UPSTREAM", "DECISION", "MECHANICAL"})
DECISION_TERMS = (
    "范围",
    "责任",
    "商业承诺",
    "容量",
    "驻场",
    "待命",
    "固定班次",
    "服务级别",
    "24×7",
    "24x7",
    "sla",
)


def build_finding(
    finding_id: str,
    discovered_by: OwnerName,
    category: FindingCategory,
    correction_owner: OwnerName | None,
    subject_ids: list[str],
    summary: str,
    requires_user_decision: bool,
) -> dict[str, object]:
    """Build the Owner-agnostic routing metadata for one finding."""
    return {
        "findingId": finding_id,
        "discoveredBy": discovered_by,
        "correctionOwner": correction_owner,
        "category": category,
        "subjectIds": list(subject_ids),
        "summary": summary,
        "requiresUserDecision": requires_user_decision,
    }


def validate_finding_routing(finding: dict[str, object]) -> list[str]:
    """Return deterministic routing diagnostics without reading Owner business data."""
    errors: list[str] = []

    def invalid(message: str) -> None:
        errors.append(f"FINDING_ROUTING_INVALID: {message}")

    required = {
        "findingId",
        "discoveredBy",
        "correctionOwner",
        "category",
        "subjectIds",
        "summary",
        "requiresUserDecision",
    }
    missing = sorted(required - set(finding))
    if missing:
        invalid("missing fields: " + ", ".join(missing))

    finding_id = finding.get("findingId")
    if not isinstance(finding_id, str) or not finding_id.strip():
        invalid("findingId must be a non-empty string")

    discovered_by = finding.get("discoveredBy")
    if discovered_by not in OWNER_NAMES:
        invalid("discoveredBy must name one of the five Owner Skills")

    correction_owner = finding.get("correctionOwner")
    if correction_owner is not None and correction_owner not in OWNER_NAMES:
        invalid("correctionOwner must be null or one of the five Owner Skills")

    category = finding.get("category")
    if category not in FINDING_CATEGORIES:
        invalid("category must be LOCAL, UPSTREAM, DECISION, or MECHANICAL")

    subject_ids = finding.get("subjectIds")
    if (
        not isinstance(subject_ids, list)
        or not subject_ids
        or any(not isinstance(item, str) or not item.strip() for item in subject_ids)
    ):
        invalid("subjectIds must be a non-empty array of non-empty strings")

    summary = finding.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        invalid("summary must be a non-empty string")
        summary_text = ""
    else:
        summary_text = summary.casefold()

    requires_user_decision = finding.get("requiresUserDecision")
    if not isinstance(requires_user_decision, bool):
        invalid("requiresUserDecision must be a boolean")
    if category == "LOCAL" and correction_owner != discovered_by:
        invalid("LOCAL findings must use discoveredBy as correctionOwner")
    if category == "UPSTREAM" and (
        correction_owner is None or correction_owner == discovered_by
    ):
        invalid("UPSTREAM findings must name a different Owner as correctionOwner")
    if category == "DECISION":
        if correction_owner is not None:
            invalid("DECISION findings must use correctionOwner=null")
        if requires_user_decision is not True:
            invalid("DECISION findings require requiresUserDecision=true")
    elif requires_user_decision is True:
        invalid("only DECISION findings may use requiresUserDecision=true")

    if category != "DECISION" and any(
        term in summary_text for term in DECISION_TERMS
    ):
        invalid(
            "scope, responsibility, commercial commitment, or service capacity "
            "findings must use category DECISION"
        )
    return errors
