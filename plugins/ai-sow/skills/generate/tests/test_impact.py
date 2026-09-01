from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from impact import compute_impact_plan, finalize_impact_plan  # noqa: E402
from models import AnchorChange, InputChangeSet  # noqa: E402


def source_ref(source: str, anchor: str, digest: str) -> dict[str, str]:
    return {
        "sourceId": source,
        "anchorId": anchor,
        "locator": f"heading:{anchor}",
        "sha256": digest,
    }


@pytest.fixture
def previous_scope() -> dict[str, object]:
    return {
        "features": [
            {
                "featureId": "feature-refund",
                "domainId": "domain-payments",
                "epicId": "epic-payments",
                "sourceRefs": [source_ref("prd-main", "anchor-refund", "1" * 64)],
                "responsibilityBoundaryIds": ["responsibility-vendor"],
            },
            {
                "featureId": "feature-ledger",
                "domainId": "domain-payments",
                "epicId": "epic-payments",
                "sourceRefs": [source_ref("prd-main", "anchor-ledger", "2" * 64)],
                "responsibilityBoundaryIds": ["responsibility-vendor"],
            },
        ],
        "epics": [
            {
                "epicId": "epic-payments",
                "sourceRefs": [source_ref("prd-main", "anchor-epic", "3" * 64)],
            }
        ],
        "designItems": [],
        "designDecisions": [],
        "commitments": [],
        "effectiveStartItems": [],
        "integrations": [
            {
                "integrationId": "integration-payment",
                "featureIds": ["feature-refund", "feature-ledger"],
                "sourceRefs": [
                    source_ref("hld-main", "anchor-payment-integration", "4" * 64)
                ],
            }
        ],
        "nfrs": [],
        "assumptions": [],
    }


@pytest.fixture
def previous_delivery() -> dict[str, object]:
    return {
        "stories": [
            {
                "storyId": "story-refund",
                "featureIds": ["feature-refund"],
            },
            {
                "storyId": "story-ledger",
                "featureIds": ["feature-ledger"],
            },
        ],
        "tasks": [
            {
                "taskId": "task-refund",
                "storyId": "story-refund",
                "designItemIds": [],
                "integrationIds": [],
                "nfrIds": [],
                "dependsOnTaskIds": [],
            },
            {
                "taskId": "task-ledger",
                "storyId": "story-ledger",
                "designItemIds": [],
                "integrationIds": [],
                "nfrIds": [],
                "dependsOnTaskIds": [],
            },
        ],
        "dependencies": [],
    }


def changes(*items: AnchorChange, exact: bool = False) -> InputChangeSet:
    return InputChangeSet(
        exact_match=exact,
        source_changes=tuple(items),
        answer_ids=(),
        responsibility_ids=(),
    )


def compute_case(scope, delivery, case: str):
    kwargs = {
        "previous_scope": scope,
        "previous_delivery": delivery,
        "baseline_generation_id": "000001",
        "baseline_revision_id": "000001",
    }
    if case == "unchanged":
        return compute_impact_plan(changes(exact=True), **kwargs)
    if case == "template-only":
        return compute_impact_plan(changes(exact=True), template_changed=True, **kwargs)
    if case == "prd-feature-edit":
        isolated_scope = copy.deepcopy(scope)
        isolated_scope["integrations"] = []
        return compute_impact_plan(
            changes(
                AnchorChange(
                    "prd-main",
                    "anchor-refund",
                    "MODIFIED",
                    "1" * 64,
                    "5" * 64,
                )
            ),
            **{**kwargs, "previous_scope": isolated_scope},
        )
    if case == "shared-integration":
        return compute_impact_plan(
            changes(
                AnchorChange(
                    "hld-main",
                    "anchor-payment-integration",
                    "MODIFIED",
                    "4" * 64,
                    "6" * 64,
                )
            ),
            **kwargs,
        )
    if case == "compiler-contract-change":
        return compute_impact_plan(
            changes(exact=True), compiler_contract_changed=True, **kwargs
        )
    raise AssertionError(case)


@pytest.mark.parametrize(
    ("case", "action", "affected"),
    [
        ("unchanged", "REUSE", set()),
        ("template-only", "RENDER_ONLY", set()),
        ("prd-feature-edit", "SLICE_COMPILE", {"feature-refund"}),
        ("shared-integration", "SLICE_COMPILE", {"feature-refund", "feature-ledger"}),
        (
            "compiler-contract-change",
            "FULL_COMPILE",
            {"feature-refund", "feature-ledger"},
        ),
    ],
)
def test_run_plan_matrix(
    previous_scope, previous_delivery, case: str, action: str, affected: set[str]
) -> None:
    plan = compute_case(previous_scope, previous_delivery, case)
    assert plan.action == action
    assert set(plan.affected_feature_ids) == affected


def test_moved_heading_does_not_seed_recompilation(previous_scope, previous_delivery) -> None:
    plan = compute_impact_plan(
        changes(
            AnchorChange(
                "prd-main",
                "anchor-refund",
                "MOVED_UNCHANGED",
                "1" * 64,
                "1" * 64,
            )
        ),
        previous_scope=previous_scope,
        previous_delivery=previous_delivery,
        baseline_generation_id="000001",
        baseline_revision_id="000001",
    )
    assert plan.action == "SLICE_COMPILE"
    assert plan.affected_feature_ids == ()
    assert plan.escalation == "NONE"


def test_task_dependency_expands_feature_closure(previous_scope, previous_delivery) -> None:
    delivery = copy.deepcopy(previous_delivery)
    delivery["dependencies"] = [
        {
            "predecessorTaskId": "task-refund",
            "successorTaskId": "task-ledger",
        }
    ]
    plan = compute_impact_plan(
        changes(
            AnchorChange(
                "prd-main",
                "anchor-refund",
                "MODIFIED",
                "1" * 64,
                "5" * 64,
            )
        ),
        previous_scope=previous_scope,
        previous_delivery=delivery,
        baseline_generation_id="000001",
        baseline_revision_id="000001",
    )
    assert set(plan.affected_feature_ids) == {"feature-refund", "feature-ledger"}


def test_unmapped_structured_change_escalates_to_full(
    previous_scope, previous_delivery
) -> None:
    change_set = InputChangeSet(False, (), ("question-unknown",), ())
    plan = compute_impact_plan(
        change_set,
        previous_scope=previous_scope,
        previous_delivery=previous_delivery,
        baseline_generation_id="000001",
        baseline_revision_id="000001",
    )
    assert plan.escalation == "FULL"
    assert set(plan.affected_feature_ids) == {"feature-refund", "feature-ledger"}


def test_added_ambiguous_anchor_widens_feature_to_domain(
    previous_scope, previous_delivery
) -> None:
    provisional = compute_impact_plan(
        changes(AnchorChange("prd-main", "anchor-new", "ADDED", None, "7" * 64)),
        previous_scope=previous_scope,
        previous_delivery=previous_delivery,
        baseline_generation_id="000001",
        baseline_revision_id="000001",
    )
    candidate = {
        "features": [],
        "newAnchorMappings": [
            {
                "sourceRef": source_ref("prd-main", "anchor-new", "7" * 64),
                "featureId": "feature-refund",
                "domainId": "domain-payments",
                "confidence": "DOMAIN",
            }
        ],
    }
    final = finalize_impact_plan(
        provisional,
        candidate,
        previous_scope,
        previous_delivery,
    )
    assert final.escalation == "DOMAIN"
    assert set(final.affected_feature_ids) == {"feature-refund", "feature-ledger"}


def test_unknown_added_anchor_mapping_widens_to_full(
    previous_scope, previous_delivery
) -> None:
    provisional = compute_impact_plan(
        changes(AnchorChange("prd-main", "anchor-new", "ADDED", None, "7" * 64)),
        previous_scope=previous_scope,
        previous_delivery=previous_delivery,
        baseline_generation_id="000001",
        baseline_revision_id="000001",
    )
    final = finalize_impact_plan(
        provisional,
        {
            "features": [],
            "newAnchorMappings": [
                {
                    "sourceRef": source_ref("prd-main", "anchor-new", "7" * 64),
                    "domainId": "domain-payments",
                    "confidence": "UNKNOWN",
                }
            ],
        },
        previous_scope,
        previous_delivery,
    )
    assert final.escalation == "FULL"
