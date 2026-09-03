from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
PLUGIN_ROOT = Path(__file__).parents[3]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from candidate_builder import (  # noqa: E402
    build_id_decisions,
    refresh_scope_candidate,
)
from models import ImpactPlan, RunPlan  # noqa: E402


def test_id_decisions_are_derived_from_semantic_comparison() -> None:
    previous = {
        "stories": [
            {"storyId": "story-same", "name": "相同标题", "featureId": "feature-a"},
            {"storyId": "story-clear", "name": "原标题", "featureId": "feature-b"},
        ],
        "acceptanceCriteria": [],
        "tasks": [],
        "dependencies": [],
    }
    candidate = {
        "stories": [
            {"storyId": "story-same", "name": "相同标题", "featureId": "feature-a"},
            {"storyId": "story-clear", "name": "澄清后的标题", "featureId": "feature-b"},
            {"storyId": "story-new", "name": "新增标题", "featureId": "feature-c"},
        ],
        "acceptanceCriteria": [],
        "tasks": [],
        "dependencies": [],
    }

    ledger, diagnostics = build_id_decisions(candidate, previous, stage="delivery")

    assert diagnostics == ()
    assert [item["disposition"] for item in ledger["decisions"]] == [
        "UNCHANGED",
        "CLARIFIED",
        "NEW",
    ]
    assert ledger["decisions"][0]["previousId"] == "story-same"
    assert ledger["decisions"][1]["previousId"] == "story-clear"
    assert "previousId" not in ledger["decisions"][2]


def test_same_id_cannot_hide_a_semantic_change() -> None:
    previous = {
        "stories": [
            {"storyId": "story-a", "name": "标题", "featureId": "feature-a"}
        ]
    }
    candidate = {
        "stories": [
            {"storyId": "story-a", "name": "标题", "featureId": "feature-b"}
        ]
    }

    ledger, diagnostics = build_id_decisions(candidate, previous, stage="delivery")

    assert ledger["decisions"] == []
    assert [item.code for item in diagnostics] == [
        "CANDIDATE_STABLE_ID_SEMANTICS_CHANGED"
    ]
    assert diagnostics[0].path == "/stories/story-a"


def test_refresh_scope_candidate_rebinds_static_fields_after_impact_expands() -> None:
    plan = RunPlan(
        run_id="run-000002-000002",
        pending_manifest_path=".ai-sow/inputs/pending/manifest.json",
        action="SLICE_COMPILE",
        target_revision_id="000002",
        target_generation_id="000002",
        template_snapshot_path=".ai-sow/work/run-template.xlsx",
        template_sha256="a" * 64,
        impact=ImpactPlan(
            action="SLICE_COMPILE",
            baseline_generation_id="000001",
            baseline_revision_id="000001",
            changed_source_ids=("source-a",),
            changed_anchor_ids=("anchor-a",),
            affected_feature_ids=("feature-a", "feature-b"),
            escalation="DOMAIN",
            reason_codes=("SHARED_SCOPE_EXPANDED",),
        ),
        scope_compiler_contract="scope-compiler-v2",
        delivery_compiler_contract="delivery-compiler-v5",
        renderer_contract="generation-renderer-v7",
    )
    authored = {
        "contract": "tampered",
        "inputRevisionId": "000001",
        "impactPlanSha256": "0" * 64,
        "replacesFeatureIds": ["wrong-feature"],
        "newAnchorMappings": [{"confidence": "UNKNOWN"}],
        "epics": [{"epicId": "epic-a"}],
        "responsibilityBoundaries": [{"responsibilityBoundaryId": "wrong"}],
    }
    manifest = {
        "responsibilityBoundaries": [
            {"responsibilityBoundaryId": "responsibility-vendor"}
        ]
    }

    refreshed = refresh_scope_candidate(plan, manifest, authored)

    assert refreshed["contract"] == "ai-sow-scope-slice-v1"
    assert refreshed["inputRevisionId"] == "000002"
    assert refreshed["impactPlanSha256"] != "0" * 64
    assert refreshed["replacesFeatureIds"] == ["feature-a", "feature-b"]
    assert refreshed["responsibilityBoundaries"] == manifest[
        "responsibilityBoundaries"
    ]
    assert refreshed["newAnchorMappings"] == authored["newAnchorMappings"]
    assert refreshed["epics"] == authored["epics"]
