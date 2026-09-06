from __future__ import annotations

TEST_LAYER = "unit"

import sys
from pathlib import Path
import pytest
SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def test_evidence_bound_id_preserves_order_and_nfc_but_changes_identity_basis():
    from stable_ids import stable_entity_id
    base = ("scope-entity-id-v1", "FEATURE", "epic-a", ["source:a", "source:b"], ("BUSINESS",))
    identity = stable_entity_id(*base)
    assert identity.startswith("feature-") and len(identity) == len("feature-") + 64
    assert stable_entity_id(*base[:3], list(reversed(base[3])), base[4]) == identity
    for changes in [("scope-entity-id-v2", *base[1:]), (base[0], "EPIC", *base[2:]),
                    (*base[:2], "epic-b", *base[3:]), (*base[:3], ["source:a", "source:c"], base[4]),
                    (*base[:4], ("TECHNICAL",))]:
        assert stable_entity_id(*changes) != identity
    assert stable_entity_id(*base[:3], ["source:café"], base[4]) == stable_entity_id(*base[:3], ["source:cafe\u0301"], base[4])
    for discriminator in [("arbitrary free text",), ("BUSINESS", "EXTRA"), (), "BUSINESS"]:
        with pytest.raises(ValueError):
            stable_entity_id(*base[:4], discriminator)
    for anchors in [[], [""], ["a", "a"], ["café", "cafe\u0301"]]:
        with pytest.raises(ValueError):
            stable_entity_id(*base[:3], anchors, base[4])


def test_prior_visible_id_preservation_requires_unchanged_unique_verified_one_to_one():
    from stable_ids import PriorMatch, preserve_prior_id
    from dataclasses import replace
    match = PriorMatch("ONE_TO_ONE", "feature-visible-7", True, True, False)
    assert preserve_prior_id(match) == "feature-visible-7"
    for changed in [replace(match, relation_kind=kind) for kind in ["SPLIT", "MERGE", "AMBIGUOUS"]] + [
        replace(match, identity_changed=True), replace(match, semantic_match_unique=False),
        replace(match, prior_visible_id_valid=False), replace(match, prior_visible_id=None),
        replace(match, prior_visible_id="not an ID")]:
        assert preserve_prior_id(changed) is None


@pytest.mark.integration
def test_evidence_bound_id_prior_converges_without_changing_accepted_identity(tmp_path):
    from contracts import canonical_json_bytes, sha256_bytes
    from stable_ids import stable_entity_id
    sys.path.insert(0, str(Path(__file__).parent))
    from test_prior_state import workbook_fixture, decision_for, revision_for
    from prior_state import inventory_prior_workbook, materialize_prior_snapshot
    path = tmp_path / "prior.xlsx"
    workbook_fixture(path)
    inventory = inventory_prior_workbook(path)
    decision = decision_for([inventory])
    anchors = [{"sourceId": "source-0", "priorEvidenceId": decision["entities"][0]["evidenceIds"][0]}]
    expected = "prior-" + sha256_bytes(canonical_json_bytes({"idSchemaVersion": "prior-entity-id-v1", "entityKind": "CONTRACT_ENTITY", "sortedEvidenceAnchors": anchors, "controlledDiscriminator": ["CONTRACT_ENTITY"]}))
    unified = stable_entity_id("prior-entity-id-v1", "CONTRACT_ENTITY", None,
        [canonical_json_bytes(anchor).decode() for anchor in anchors], ("CONTRACT_ENTITY",))
    snapshot = materialize_prior_snapshot([inventory], decision, input_revision_bytes=revision_for([inventory]))
    assert unified == expected == snapshot["entities"][0]["entityId"]
