from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.claims import build_claims, claim_metrics, validate_claims
from runtime.diagnostics import diagnostic_codes
from runtime.fact_source import validate_unique_fact_sources
from runtime.patch import apply_operations, patch_audit, validate_patch_audit
from runtime.text_gates import validate_text_gates


def test_text_gates_catch_unanchored_claims_paths_and_bad_counts(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/one.yaml").write_text("kind: Job\n", encoding="utf-8")
    diagnostics = validate_text_gates(
        tmp_path,
        [
            ("/summary", "三个 Job 是唯一实现。"),
            ("/notes", r"记录来自 E:\\ai-sow-e2e\\trace.txt。"),
        ],
        count_anchors=[
            {"path": "/summary", "glob": "deploy/*.yaml", "expr": "files", "expected": 3}
        ],
    )
    assert diagnostic_codes(diagnostics) == {"COUNT_ANCHOR_MISMATCH", "LOCAL_PATH_LEAKED"}


def test_text_gates_reject_unanchored_absolute_claim() -> None:
    diagnostics = validate_text_gates(
        Path.cwd(),
        [("/summary", "不存在任何邮件相关配置。")],
    )
    assert diagnostic_codes(diagnostics) == {"ABSOLUTE_CLAIM_UNANCHORED"}


def test_count_anchor_can_read_deterministic_repo_fact_pointer(tmp_path: Path) -> None:
    facts = tmp_path / ".ai-sow/work/analyze-as-is/repo-facts.json"
    facts.parent.mkdir(parents=True)
    facts.write_text(
        json.dumps(
            {
                "repositories": [
                    {"facts": {"deploymentResources": {"counts": {"Job": 4}}}}
                ]
            }
        ),
        encoding="utf-8",
    )

    diagnostics = validate_text_gates(
        tmp_path,
        [("/summary", "本次调查覆盖的部署资源中有四个 Job。")],
        count_anchors=[
            {
                "path": "/summary",
                "glob": ".ai-sow/work/analyze-as-is/repo-facts.json",
                "expr": "json:/repositories/0/facts/deploymentResources/counts/Job",
                "expected": 4,
            }
        ],
    )

    assert diagnostics == []


def test_fact_source_rejects_duplicate_quantitative_facts() -> None:
    diagnostics = validate_unique_fact_sources(
        [
            ("/topic", "索引覆盖六类材料。索引覆盖六类材料。"),
            ("/evidence", "索引覆盖六类材料。"),
        ]
    )
    assert diagnostic_codes(diagnostics) == {"DUPLICATE_FACT_STATEMENT"}


def test_patch_detects_freeform_edits_and_unsynchronised_references() -> None:
    before = {
        "items": [{"itemId": "item-source", "summary": "旧事实"}],
        "coverage": [{"coverageId": "coverage-one", "itemIds": ["item-source"], "summary": "沿用旧事实"}],
    }
    patch = {
        "operations": [
            {"op": "replace", "path": "/items/0/summary", "value": "新事实", "findingId": "F-1"}
        ],
        "acknowledgedClosureIds": [],
    }
    expected = apply_operations(before, patch["operations"])
    assert "PATCH_CLOSURE_UNSYNCED" in diagnostic_codes(validate_patch_audit(before, expected, patch))

    freeform = json.loads(json.dumps(expected))
    freeform["coverage"][0]["summary"] = "未声明的编辑"
    assert "PATCH_FREEFORM_EDIT_DETECTED" in diagnostic_codes(
        validate_patch_audit(before, freeform, patch)
    )


def test_patch_closure_does_not_bridge_through_external_ids() -> None:
    before = {
        "stories": [
            {"storyId": "story-one", "featureId": "feature-one"},
            {"storyId": "story-two", "featureId": "feature-two"},
        ],
        "acceptanceCriteria": [
            {
                "acceptanceCriterionId": "ac-one",
                "storyId": "story-one",
                "approvalDecisionIds": ["decision-shared"],
            },
            {
                "acceptanceCriterionId": "ac-two",
                "storyId": "story-two",
                "approvalDecisionIds": ["decision-shared"],
            },
        ],
    }
    patch = {
        "operations": [
            {
                "op": "add",
                "path": "/acceptanceCriteria/-",
                "findingId": "F-1",
                "value": {
                    "acceptanceCriterionId": "ac-new",
                    "storyId": "story-one",
                    "approvalDecisionIds": ["decision-shared"],
                },
            }
        ],
        "acknowledgedClosureIds": [],
    }
    after = apply_operations(before, patch["operations"])

    audit = patch_audit(before, after, patch)

    assert audit["changedIds"] == ["ac-new"]
    assert audit["closureIds"] == ["ac-new", "ac-one", "story-one"]
    assert audit["syncSuspects"] == ["ac-one", "story-one"]


def test_patch_closure_diagnostic_exposes_atomic_retry_contract() -> None:
    before = {
        "items": [{"itemId": "item-source", "summary": "旧事实"}],
        "coverage": [
            {"coverageId": "coverage-one", "itemIds": ["item-source"]}
        ],
    }
    patch = {
        "operations": [
            {
                "op": "replace",
                "path": "/items/0/summary",
                "value": "新事实",
                "findingId": "F-1",
            }
        ],
        "acknowledgedClosureIds": [],
    }
    after = apply_operations(before, patch["operations"])

    diagnostics = validate_patch_audit(before, after, patch)
    closure_diagnostic = next(
        item for item in diagnostics if item["code"] == "PATCH_CLOSURE_UNSYNCED"
    )

    assert closure_diagnostic["acknowledgementField"] == "acknowledgedClosureIds"
    assert closure_diagnostic["candidateUpdated"] is False
    assert closure_diagnostic["retryAllowed"] is True
    assert closure_diagnostic["consumesPatchRound"] is False


def test_claim_projection_is_deterministic_and_source_bound(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("客户必须获得唯一编号。\n", encoding="utf-8")
    document = {
        "normalizedItems": [
            {
                "normalizedItemId": "norm-customer-id",
                "statement": "客户必须获得唯一编号。",
                "file": "source.md",
            }
        ]
    }
    first = build_claims("analyze-requirement", [("requirements", document)], project_root=tmp_path)
    second = build_claims("analyze-requirement", [("requirements", document)], project_root=tmp_path)
    assert first == second
    assert validate_claims(first, "analyze-requirement", {"requirements": document}) == []


def test_claim_projection_preserves_stage_enrichment_and_reports_coverage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("四个 Job。\n", encoding="utf-8")
    document = {
        "evidence": [
            {
                "evidenceId": "evidence-jobs",
                "reference": "source.md",
                "summary": "本次调查覆盖的部署资源中有四个 Job。",
            }
        ]
    }
    initial = build_claims("analyze-as-is", [("asis", document)], project_root=tmp_path)
    claim = initial["claims"][0]
    claim["derivedFrom"] = "premise-deployment-jobs"
    claim["anchors"].append(
        {
            "path": "source.md",
            "glob": "source.md",
            "expr": "regex:Job",
            "expected": 1,
        }
    )
    claim["verification"] = {
        "verdict": "PASS",
        "lineReference": "source.md:1",
        "anchorSha256": claim["anchors"][0]["anchorSha256"],
        "verifiedBy": "claim-verifier",
        "verifierModel": "gpt-5.6-luna/low",
    }

    rebuilt = build_claims(
        "analyze-as-is",
        [("asis", document)],
        project_root=tmp_path,
        previous_claims=initial["claims"],
        previous_verified=[
            {
                "claimId": claim["claimId"],
                "textSha256": hashlib.sha256(claim["text"].encode("utf-8")).hexdigest(),
                "anchorPath": "source.md",
                "anchorSha256": claim["anchors"][0]["anchorSha256"],
                "verdict": "PASS",
                "verifiedBy": "claim-verifier",
                "verifierModel": "gpt-5.6-luna/low",
            }
        ],
    )

    assert rebuilt["claims"][0]["derivedFrom"] == "premise-deployment-jobs"
    assert rebuilt["claims"][0]["anchors"][1]["glob"] == "source.md"
    assert claim_metrics(rebuilt) == {
        "totalClaims": 1,
        "verifiedClaims": 1,
        "unverifiedClaims": 0,
        "remainingClaimIds": [],
    }


def test_claim_projection_resolves_reverse_evidence_support_to_item_anchor() -> None:
    document = {
        "items": [
            {
                "asIsItemId": "asis-current-api",
                "summary": "当前 API 已提供读取边界。",
            }
        ],
        "evidence": [
            {
                "evidenceId": "evidence-current-api",
                "reference": "service-api:src/profile.py#ProfileReader",
                "supportsIds": ["asis-current-api"],
                "summary": "代码定义当前读取边界。",
            }
        ],
    }

    projected = build_claims("analyze-as-is", [("asis", document)])
    item_claim = next(
        claim
        for claim in projected["claims"]
        if claim["ownerField"] == "/asis/items/0/summary"
    )

    assert item_claim["kind"] == "FACTUAL"
    assert item_claim["confidence"] == "HIGH"
    assert item_claim["anchors"] == [
        {"path": "service-api:src/profile.py#ProfileReader"}
    ]


def test_claim_projection_hashes_registered_repository_logical_anchor(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "repositories/service-api/src/profile.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("class ProfileReader: pass\n", encoding="utf-8")
    document = {
        "analysisScope": {
            "repositorySnapshots": [
                {"repoId": "service-api", "path": "repositories/service-api"}
            ]
        },
        "items": [
            {"asIsItemId": "asis-current-api", "summary": "当前读取边界存在。"}
        ],
        "evidence": [
            {
                "evidenceId": "evidence-current-api",
                "reference": "service-api:src/profile.py#ProfileReader",
                "supportsIds": ["asis-current-api"],
                "summary": "代码定义当前读取边界。",
            }
        ],
    }

    projected = build_claims(
        "analyze-as-is", [("asis", document)], project_root=tmp_path
    )
    item_claim = next(
        claim
        for claim in projected["claims"]
        if claim["ownerField"] == "/asis/items/0/summary"
    )

    assert item_claim["anchors"][0]["anchorSha256"] == hashlib.sha256(
        anchor.read_bytes()
    ).hexdigest()
