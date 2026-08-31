from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.claims import (
    FACT_VERIFIER_ROUTE,
    JUDGMENT_REVIEWER_ROUTE,
    build_claims,
    claim_metrics,
    validate_claims,
)
from runtime.authorization import publish_file_transaction
from runtime.context_pages import (
    PAGE_BYTE_BUDGET,
    PAGE_TOKEN_BUDGET,
    context_budget,
    expected_context_fragment,
    read_protocol,
    write_context_fragment,
)
from runtime.diagnostics import diagnostic_codes
from runtime.fact_source import validate_unique_fact_sources
from runtime.patch import (
    DIFF_REVIEW_BYTE_BUDGET,
    apply_operations,
    patch_audit,
    validate_patch_audit,
)
from runtime.project_io import ProjectFiles
from runtime.review_checks import artifact_metrics, prepare_claims, record_reviewer_judgment
from runtime.text_gates import validate_text_gates


def test_context_pages_bind_order_hash_budget_and_truncation_recovery(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    value = {"text": "证据" * 9_000}

    entry = write_context_fragment(
        files,
        "evidence",
        ".ai-sow/work/owner/context/evidence.json",
        value,
    )

    assert entry == expected_context_fragment(
        files,
        "evidence",
        ".ai-sow/work/owner/context/evidence.json",
    )
    assert len(entry["pages"]) > 1
    assert [page["order"] for page in entry["pages"]] == list(
        range(1, len(entry["pages"]) + 1)
    )
    assert all(page["bytes"] <= PAGE_BYTE_BUDGET for page in entry["pages"])
    assert all(page["estimatedTokens"] <= PAGE_TOKEN_BUDGET for page in entry["pages"])
    assert context_budget()["tokenEstimator"] == "utf8-bytes-upper-bound-v1"
    assert read_protocol()["truncatedPageStatus"] == "NOT_READ"
    assert "first unread page" in read_protocol()["recovery"]


def test_input_context_does_not_publish_empty_review_claims_before_candidate(
    tmp_path: Path,
) -> None:
    files = ProjectFiles.open(tmp_path)

    claims = prepare_claims(
        files,
        tmp_path,
        "generate-story",
        (("delivery", ".ai-sow/work/generate-story/delivery.candidate.json"),),
        ".ai-sow/work/generate-story/claims.json",
    )

    assert claims == {
        "algorithm": "ai-sow-review-claims-v1",
        "owner": "generate-story",
        "status": "PENDING_CANDIDATE",
    }
    assert not (tmp_path / ".ai-sow/work/generate-story/claims.json").exists()


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


def test_text_gates_accept_source_anchored_non_quantitative_absolute_claim() -> None:
    diagnostics = validate_text_gates(
        Path.cwd(),
        [("/constraints", "只有获授权的业务角色可以维护客户档案。")],
        absolute_claim_paths={"/constraints"},
        evidence_anchor_paths={"/constraints"},
    )

    assert diagnostics == []


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


def test_patch_diff_review_contains_changed_fields_direct_closure_and_ac_mapping() -> None:
    before = {
        "stories": [
            {
                "storyId": "story-one",
                "featureId": "feature-one",
                "summary": "旧摘要",
            }
        ],
        "acceptanceCriteria": [
            {
                "acceptanceCriterionId": "ac-one",
                "storyId": "story-one",
                "description": "旧验收",
            }
        ],
    }
    patch = {
        "operations": [
            {
                "op": "replace",
                "path": "/stories/0/summary",
                "value": "新摘要",
                "findingId": "F-1",
            }
        ],
        "acknowledgedClosureIds": ["ac-one"],
    }
    after = apply_operations(before, patch["operations"])

    audit = patch_audit(before, after, patch)

    assert audit["diffReview"]["changedFields"] == [
        {"after": "新摘要", "before": "旧摘要", "path": "/stories/0/summary"}
    ]
    assert audit["diffReview"]["directClosureIds"] == ["ac-one"]
    assert audit["diffReview"]["acceptanceMappings"] == [
        {
            "acceptanceCriterionId": "ac-one",
            "featureId": "feature-one",
            "storyId": "story-one",
        }
    ]


def test_patch_rejects_diff_review_over_hard_budget() -> None:
    before = {"items": [{"itemId": "item-one", "summary": "短文本"}]}
    patch = {
        "operations": [
            {
                "op": "replace",
                "path": "/items/0/summary",
                "value": "变更" * DIFF_REVIEW_BYTE_BUDGET,
                "findingId": "F-1",
            }
        ],
        "acknowledgedClosureIds": [],
    }
    after = apply_operations(before, patch["operations"])

    assert "PATCH_DIFF_BUDGET_EXCEEDED" in diagnostic_codes(
        validate_patch_audit(before, after, patch)
    )


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


def test_file_transaction_restores_prior_bytes_after_partial_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = ProjectFiles.open(tmp_path)
    first = ".ai-sow/work/generate-story/first.json"
    second = ".ai-sow/work/generate-story/second.json"
    files.write_atomic(first, b"first-before\n")
    files.write_atomic(second, b"second-before\n")
    original_write = ProjectFiles.write_atomic
    calls = 0

    def fail_second_write(
        target: ProjectFiles,
        relative_path: str,
        payload: bytes,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected transaction failure")
        original_write(target, relative_path, payload)

    monkeypatch.setattr(ProjectFiles, "write_atomic", fail_second_write)

    with pytest.raises(OSError, match="injected transaction failure"):
        publish_file_transaction(
            files,
            {first: b"first-after\n", second: b"second-after\n"},
            [],
        )

    assert files.read_bytes(first) == b"first-before\n"
    assert files.read_bytes(second) == b"second-before\n"


def test_artifact_metrics_are_deterministic_and_candidate_derived() -> None:
    delivery = {
        "stories": [{"storyId": "story-one"}, {"storyId": "story-two"}],
        "acceptanceCriteria": [{"acceptanceCriterionId": "ac-one"}],
        "metadata": {"ignored": True},
    }

    metrics = artifact_metrics({"delivery": delivery})

    assert metrics["algorithm"] == "ai-sow-artifact-metrics-v1"
    assert metrics["documents"]["delivery"]["collections"] == {
        "acceptanceCriteria": 1,
        "stories": 2,
    }
    assert len(metrics["documents"]["delivery"]["canonicalSha256"]) == 64


def test_reviewer_judgment_cannot_flip_for_the_same_packet(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    packet_sha256 = "a" * 64
    common = {
        "files": files,
        "owner": "generate-story",
        "packet_sha256": packet_sha256,
        "journal_directory": ".ai-sow/work/generate-story/review-judgments",
        "reviewer_path": ".ai-sow/work/generate-story/reviewer.json",
        "reviewer_algorithm": "ai-sow-owner-reviewer-v1",
    }

    diagnostics, outputs, judgment_path = record_reviewer_judgment(
        decision="BLOCKED",
        finding_ids=["GST-JR-007"],
        **common,
    )
    assert diagnostics == []
    assert outputs == [judgment_path]

    diagnostics, outputs, _ = record_reviewer_judgment(
        decision="PASS",
        finding_ids=[],
        **common,
    )
    assert outputs == []
    assert diagnostics[0]["code"] == "REVIEW_JUDGMENT_CONFLICT"
    assert diagnostics[0]["previousDecision"] == "BLOCKED"
    assert diagnostics[0]["attemptedDecision"] == "PASS"
    assert not (tmp_path / ".ai-sow/work/generate-story/reviewer.json").exists()


def test_reviewer_pass_is_idempotent_and_binds_legacy_sidecar(tmp_path: Path) -> None:
    files = ProjectFiles.open(tmp_path)
    common = {
        "files": files,
        "owner": "generate-story",
        "packet_sha256": "b" * 64,
        "decision": "PASS",
        "finding_ids": [],
        "journal_directory": ".ai-sow/work/generate-story/review-judgments",
        "reviewer_path": ".ai-sow/work/generate-story/reviewer.json",
        "reviewer_algorithm": "ai-sow-owner-reviewer-v1",
    }

    first = record_reviewer_judgment(**common)
    second = record_reviewer_judgment(**common)

    assert first == second
    reviewer = json.loads(
        (tmp_path / ".ai-sow/work/generate-story/reviewer.json").read_text(encoding="utf-8")
    )
    assert reviewer == {
        "algorithm": "ai-sow-owner-reviewer-v1",
        "decision": "PASS",
        "owner": "generate-story",
        "packetSha256": "b" * 64,
    }


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
    assert first["claims"][0]["reviewRoute"] == FACT_VERIFIER_ROUTE
    assert validate_claims(first, "analyze-requirement", {"requirements": document}) == []


def test_claim_routes_facts_to_low_cost_verifier_and_judgment_to_deep_reviewer(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text("当前接口已存在。\n", encoding="utf-8")
    document = {
        "evidence": [
            {
                "evidenceId": "evidence-interface",
                "reference": "source.md",
                "summary": "当前接口已存在。",
            }
        ],
        "decisions": [
            {
                "decisionId": "decision-target",
                "rationale": "目标方案采用异步事件。",
            }
        ],
    }

    claims = build_claims("generate-story", [("delivery", document)], project_root=tmp_path)

    assert [claim["reviewRoute"] for claim in claims["claims"]] == [
        FACT_VERIFIER_ROUTE,
        JUDGMENT_REVIEWER_ROUTE,
    ]
    metrics = claim_metrics(claims)
    assert metrics["remainingClaimIdsByRoute"][FACT_VERIFIER_ROUTE] == [
        claims["claims"][0]["claimId"]
    ]
    assert metrics["remainingClaimIdsByRoute"][JUDGMENT_REVIEWER_ROUTE] == [
        claims["claims"][1]["claimId"]
    ]


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
        "remainingClaimIdsByRoute": {
            FACT_VERIFIER_ROUTE: [],
            JUDGMENT_REVIEWER_ROUTE: [],
        },
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
