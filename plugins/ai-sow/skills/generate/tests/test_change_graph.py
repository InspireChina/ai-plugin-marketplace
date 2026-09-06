from __future__ import annotations

TEST_LAYER = "unit"

import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))


def prior_snapshot():
    return {"contractVersion": "prior-state-snapshot-v1", "inputRevisionSha256": "a" * 64,
        "entities": [{"entityId": name, "sourceId": source, "entityKind": "CONTRACT_ENTITY",
            "semanticSummary": "已交付能力", "deliveryStatus": "CURRENT_BY_CONTRACT", "evidenceIds": [evidence]}
            for name, source, evidence in [("p-a", "source-a", "1" * 64), ("p-b", "source-b", "1" * 64),
                ("p-old", "source-old", "2" * 64), ("p-new", "source-new", "3" * 64)]],
        "evidence": [{"priorEvidenceId": x * 64} for x in "123"],
        "sourceRelations": [{"sourceAId": "source-a", "sourceBId": "source-b", "relation": "DUPLICATE", "evidenceIds": ["1" * 64]}],
        "entitySupersessions": [{"predecessorIds": ["p-old"], "successorIds": ["p-new"], "evidenceIds": ["3" * 64]}]}


def test_change_graph_closure_uses_effective_prior_and_never_persists_complements():
    from change_graph import derive_change_views
    graph = {"changeGroups": [], "retiredPrior": []}
    prior = prior_snapshot()
    original = copy.deepcopy(graph)
    views = derive_change_views(graph, prior, ["t-new"])
    assert dict(views.target_origin) == {"t-new": "NEW"}
    assert dict(views.prior_fate) == {"p-a": "KEEP", "p-new": "KEEP"}
    assert graph == original
    graph["changeGroups"] = [{"kind": "ADJUST", "priorEntityIds": ["p-a"], "targetEntityIds": ["t-new"], "evidenceIds": ["current-change"]}]
    graph["retiredPrior"] = [{"priorEntityId": "p-new", "evidenceIds": ["3" * 64, "current-removal"]}]
    views = derive_change_views(graph, prior, ["t-new", "t-extra"])
    assert dict(views.target_origin) == {"t-new": "ADJUST", "t-extra": "NEW"}
    assert dict(views.prior_fate) == {"p-a": "ADJUST", "p-new": "RETIRE"}
    for mutation in ["inactive", "unknown_target", "overlap", "no_prior_proof", "no_removal_proof", "persist_keep"]:
        candidate = copy.deepcopy(graph)
        if mutation == "inactive": candidate["changeGroups"][0]["priorEntityIds"] = ["p-b"]
        elif mutation == "unknown_target": candidate["changeGroups"][0]["targetEntityIds"] = ["missing"]
        elif mutation == "overlap": candidate["retiredPrior"][0]["priorEntityId"] = "p-a"
        elif mutation == "no_prior_proof": candidate["retiredPrior"][0]["evidenceIds"] = ["current-removal"]
        elif mutation == "no_removal_proof": candidate["retiredPrior"][0]["evidenceIds"] = ["3" * 64]
        else: candidate["KEEP"] = ["p-a"]
        with pytest.raises(ValueError):
            derive_change_views(candidate, prior, ["t-new"])


def test_change_cardinality_allows_only_one_to_one_split_or_merge():
    from change_graph import derive_change_views
    for kind, prior, target in [("ADJUST", ["p-a"], ["t-a"]), ("REUSE_DEPENDENCY", ["p-a"], ["t-a"]),
        ("SPLIT", ["p-a"], ["t-a", "t-b"]), ("MERGE", ["p-a", "p-new"], ["t-a"])]:
        graph = {"changeGroups": [{"kind": kind, "priorEntityIds": prior,
            "targetEntityIds": target, "evidenceIds": ["source-boundary"]}], "retiredPrior": []}
        views = derive_change_views(graph, prior_snapshot(), target)
        assert set(views.target_origin.values()) == {kind}
    for kind, previous, current in [("ADJUST", ["p-a"], ["t-a", "t-b"]),
        ("SPLIT", ["p-a", "p-new"], ["t-a", "t-b"]), ("MERGE", ["p-a", "p-new"], ["t-a", "t-b"])]:
        graph = {"changeGroups": [{"kind": kind, "priorEntityIds": previous, "targetEntityIds": current, "evidenceIds": ["source-boundary"]}], "retiredPrior": []}
        with pytest.raises(ValueError) as error:
            derive_change_views(graph, prior_snapshot(), current)
        assert error.value.code == "CONTRACT_UNSUPPORTED"
    # Independently source-supported disjoint boundaries need no invented intermediate entity.
    graph = {"changeGroups": [{"kind": "SPLIT", "priorEntityIds": [previous], "targetEntityIds": targets, "evidenceIds": [evidence]}
        for previous, targets, evidence in [("p-a", ["t-a", "t-b"], "source-boundary-a"), ("p-new", ["t-c", "t-d"], "source-boundary-b")]], "retiredPrior": []}
    assert set(derive_change_views(graph, prior_snapshot(), ["t-a", "t-b", "t-c", "t-d"]).target_origin) == {"t-a", "t-b", "t-c", "t-d"}
