"""One evidence-bound identity authority; labels and model-local keys are not IDs."""
from __future__ import annotations

import unicodedata
import re
import json
from dataclasses import dataclass
from typing import Literal
from collections.abc import Sequence
from contracts import canonical_json_bytes, sha256_bytes

CONTROLLED_DISCRIMINATORS = {
    "TASK": frozenset({"USER_INTERFACE", "STORY_IMPLEMENTATION", "DESIGN_ITEM", "INTEGRATION", "NFR", "POLICY_INSTANCE"}),
    "STORY": frozenset({"DELIVERABLE_OUTCOME"}),
    "ACCEPTANCE_CRITERION": frozenset({"OBSERVABLE_RESULT"}),
    "CONTRACT_ENTITY": frozenset({"CONTRACT_ENTITY"}),
    "FACT": frozenset({"REQUIREMENT", "RULE", "CONSTRAINT", "EXCLUSION", "ASSUMPTION", "RISK"}),
    "EPIC": frozenset({"BUSINESS", "TECHNICAL", "DELIVERY"}),
    "FEATURE": frozenset({"BUSINESS", "TECHNICAL", "DELIVERY"}),
    "DESIGN_ITEM": frozenset({"COMPONENT", "FLOW", "DATA", "INFRASTRUCTURE", "QUALITY"}),
    "INTEGRATION": frozenset({"INTERNAL", "EXTERNAL"}),
    "NFR": frozenset({"PERFORMANCE", "CAPACITY", "AVAILABILITY", "SECURITY", "PRIVACY", "AUDIT", "RECOVERY", "OBSERVABILITY"}),
    "POLICY_INSTANCE": frozenset({"policy-sit-automation", "policy-uat-automation", "policy-go-live", "policy-data-migration"}),
    "ANNOTATION": frozenset({"EXCLUSION", "ASSUMPTION", "RISK"}),
}
PREFIXES = {"TASK": "task", "STORY": "story", "ACCEPTANCE_CRITERION": "ac", "CONTRACT_ENTITY": "prior", "FACT": "input", "EPIC": "epic", "FEATURE": "feature",
            "DESIGN_ITEM": "design", "INTEGRATION": "integration", "NFR": "nfr", "POLICY_INSTANCE": "policy-instance", "ANNOTATION": "annotation"}


@dataclass(frozen=True)
class PriorMatch:
    relation_kind: Literal["ONE_TO_ONE", "SPLIT", "MERGE", "AMBIGUOUS"]
    prior_visible_id: str | None
    prior_visible_id_valid: bool
    semantic_match_unique: bool
    identity_changed: bool


def preserve_prior_id(match: PriorMatch) -> str | None:
    if (match.relation_kind == "ONE_TO_ONE" and match.prior_visible_id_valid is True
            and match.semantic_match_unique is True and match.identity_changed is False
            and isinstance(match.prior_visible_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", match.prior_visible_id)):
        return match.prior_visible_id
    return None


def _identity_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("身份键必须是非空字符串。")
    return unicodedata.normalize("NFC", value)


def stable_entity_id(
    schema_version: str,
    entity_kind: str,
    parent_identity: str | None,
    evidence_anchors: Sequence[str],
    controlled_discriminator: tuple[str, ...],
) -> str:
    if entity_kind not in CONTROLLED_DISCRIMINATORS or not isinstance(controlled_discriminator, tuple) or len(controlled_discriminator) != 1 or controlled_discriminator[0] not in CONTROLLED_DISCRIMINATORS[entity_kind]:
        raise ValueError("实体类型/discriminator 必须是合同定义的封闭 tuple。")
    if isinstance(evidence_anchors, (str, bytes)):
        raise ValueError("证据锚点必须是集合。")
    anchors = [_identity_key(anchor) for anchor in evidence_anchors]
    if not anchors or len(anchors) != len(set(anchors)):
        raise ValueError("证据锚点不能为空或在 NFC 后重复。")
    basis = {"idSchemaVersion": _identity_key(schema_version), "entityKind": entity_kind,
             "sortedEvidenceAnchors": sorted(anchors), "controlledDiscriminator": list(controlled_discriminator)}
    if entity_kind == "CONTRACT_ENTITY":
        pairs = [json.loads(anchor) for anchor in anchors]
        if parent_identity is not None or any(not isinstance(pair, dict) or set(pair) != {"sourceId", "priorEvidenceId"}
                or not isinstance(pair["sourceId"], str) or not pair["sourceId"]
                or not re.fullmatch(r"[a-f0-9]{64}", str(pair["priorEvidenceId"])) for pair in pairs):
            raise ValueError("Prior 身份锚点必须是 sourceId/priorEvidenceId 对。")
        basis["sortedEvidenceAnchors"] = sorted(pairs, key=lambda pair: (pair["sourceId"], pair["priorEvidenceId"]))
    if parent_identity is not None:
        basis["parentIdentity"] = _identity_key(parent_identity)
    return PREFIXES[entity_kind] + "-" + sha256_bytes(canonical_json_bytes(basis))
