from __future__ import annotations

import ast
import copy
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


SKILL_ROOT = Path(__file__).parents[1]
CONTRACTS = SKILL_ROOT / "contracts"
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    classify_diagnostic,
    load_registry,
    load_schema_registry,
    sha256_bytes,
    validate_action_binding,
    validate_contract,
    validate_state_combination,
)
from models import (  # noqa: E402
    ActionEnvelope,
    ActionRecord,
    CatalogHydration,
    CompilerProgress,
    CompilerResult,
    Diagnostic,
    InputRevisionResult,
    ReplacementOutcome,
    ReviewProgress,
    RouteDecision,
    RunState,
    SourceDocument,
    TaskStandardCatalog,
)
from questions import (  # noqa: E402
    question_answer_anchors,
    question_sha256,
    validate_question_answers,
    validate_typed_gap_question,
)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


NEXT_CONTRACTS = CONTRACTS
NEXT_SCHEMA_IDS = {
    "common.schema.json": "urn:ai-sow:generate:next:common:1",
    "request.schema.json": "urn:ai-sow:generate:next:request:1",
    "input-revision.schema.json": "urn:ai-sow:generate:next:input-revision:1",
    "sow-model.schema.json": "urn:ai-sow:generate:next:sow-model:1",
    "run-state.schema.json": "urn:ai-sow:generate:next:run-state:1",
    "action.schema.json": "urn:ai-sow:generate:next:action:1",
    "stage-checkpoint.schema.json": "urn:ai-sow:generate:next:stage-checkpoint:1",
    "review-repair.schema.json": "urn:ai-sow:generate:next:review-repair:1",
    "artifact-approval.schema.json": "urn:ai-sow:generate:next:artifact-approval:1",
    "generation-manifest.schema.json": "urn:ai-sow:generate:next:generation-manifest:1",
    "current.schema.json": "urn:ai-sow:generate:next:current:1",
}
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def next_schemas() -> dict[str, dict[str, object]]:
    return {name: read_json(NEXT_CONTRACTS / name) for name in NEXT_SCHEMA_IDS}


def next_registry(
    values: dict[str, dict[str, object]] | None = None,
) -> Registry:
    result = Registry()
    for schema in (values or next_schemas()).values():
        Draft202012Validator.check_schema(schema)
        result = result.with_resource(
            str(schema["$id"]), Resource.from_contents(schema)
        )
    return result


def validate_next(schema_name: str, value: object) -> None:
    values = next_schemas()
    Draft202012Validator(
        values[schema_name], registry=next_registry(values)
    ).validate(value)


def valid_next_request() -> dict[str, object]:
    return {
        "contract": "ai-sow-generate-request-v2",
        "project": {
            "projectId": "project-training",
            "name": "培训平台",
            "plannedEffectiveDate": "2026-10-01",
        },
        "mode": "GREENFIELD",
        "responsibilityBoundaries": [
            {
                "responsibilityBoundaryId": "responsibility-vendor",
                "party": "VENDOR",
                "name": "供应商交付责任",
                "responsibilities": ["交付范围内实现与验证"],
            }
        ],
        "sources": [
            {
                "sourceId": "prd-main",
                "role": "PRD",
                "path": "inputs/prd.md",
                "status": "APPROVED",
            },
            {
                "sourceId": "hld-main",
                "role": "HLD",
                "path": "inputs/hld.md",
                "status": "APPROVED",
            },
        ],
        "questions": [],
        "questionnaireAnswers": [],
        "currentStateDelta": None,
    }


def valid_input_revision() -> dict[str, object]:
    return {
        "contract": "ai-sow-input-revision-v1",
        "revisionId": "revision-0001",
        "requestSha256": HEX_A,
        "templateSha256": HEX_B,
        "deliveryPolicySha256": HEX_C,
        "executionPolicySha256": "d" * 64,
        "priorSowState": "NOT_PROVIDED",
        "priorSowSha256s": [],
        "sources": [
            {
                "sourceId": "prd-main",
                "role": "PRD",
                "status": "APPROVED",
                "path": "inputs/revisions/revision-0001/sources/prd-main.md",
                "rawSha256": HEX_A,
                "parserId": "markdown-blocks",
                "parserVersion": "1",
                "blockIds": ["block-prd-001"],
            }
        ],
        "blocks": [
            {
                "blockId": "block-prd-001",
                "sourceId": "prd-main",
                "rawSha256": HEX_A,
                "contentSha256": HEX_B,
                "locator": "heading:1",
                "primaryCoverageBlockId": "block-prd-001",
                "contextBlockIds": [],
                "structuralParentId": None,
                "extractionDisposition": "INCLUDED",
                "droppedContentCategories": [],
            }
        ],
    }


@pytest.mark.parametrize(
    "name",
    ["greenfield.json", "demo-extension.json", "brownfield.json"],
)
def test_pipeline_input_revision_fixtures_match_strict_contract(name: str) -> None:
    value = read_json(FIXTURES / "pipeline/input-revisions" / name)
    diagnostics = validate_contract(
        value,
        "input-revision.schema.json",
        load_registry(NEXT_CONTRACTS),
    )
    assert diagnostics == ()


def valid_sow_model() -> dict[str, object]:
    return {
        "contract": "ai-sow-model-v1",
        "project": {
            "projectId": "project-training",
            "mode": "GREENFIELD",
            "inputRevisionSha256": HEX_A,
            "sourceManifestSha256": HEX_B,
            "templateSha256": HEX_C,
            "policyDefinitionSha256": "d" * 64,
            "responsibilityBoundaries": [],
        },
        "inputItems": [],
        "scopeClosure": [],
        "epics": [],
        "features": [],
        "designItems": [],
        "integrations": [],
        "nfrs": [],
        "policyInstances": [],
        "scopeAnnotations": [],
        "stories": [],
        "acceptanceCriteria": [],
        "deliveryAnnotations": [],
        "tasks": [],
        "dependencies": [],
        "effectiveStartMatches": [],
        "estimationAnnotations": [],
        "decisions": [],
    }


def valid_action_envelope() -> dict[str, object]:
    return {
        "contract": "ai-sow-action-envelope-v1",
        "runId": "run-0001",
        "actionId": "action-0007",
        "logicalShardId": "story-feature-006",
        "kind": "MODEL_ACTION",
        "stage": "STORY_AC",
        "role": "AUTHOR",
        "executionAttempt": 1,
        "group": {
            "groupId": "group-story-ac",
            "requiredLogicalShardIds": ["story-feature-006"],
            "maxConcurrency": 1,
            "groupDeadlineMilliseconds": 120000,
            "shardDeadlineMilliseconds": 90000,
        },
        "inputRevisionSha256": HEX_A,
        "baseCandidateSha256": HEX_B,
        "promptId": "stage2-story-ac-v1",
        "promptPath": "prompts/stage2-story-ac.md",
        "packetPath": "work/runs/run-0001/actions/action-0007/packet.json",
        "packetSha256": HEX_C,
        "outputPath": "work/runs/run-0001/actions/action-0007/submission.json",
        "recordPath": "work/runs/run-0001/actions/action-0007/record.json",
        "resultSchema": "stage-result.schema.json",
        "resultPayloadSchema": "story-ac-patch.schema.json",
        "referencePaths": ["references/story-authoring.md"],
        "instructionManifest": {
            "executionEnvelope": {
                "path": "prompts/fragments/execution-envelope.md",
                "sha256": HEX_A,
            },
            "prompt": {"path": "prompts/stage2-story-ac.md", "sha256": HEX_B},
            "references": [
                {"path": "references/story-authoring.md", "sha256": HEX_C}
            ],
        },
        "evidenceAllowlist": [
            {
                "evidenceId": "SRC-PRD:B-001",
                "sha256": HEX_A,
                "locator": "heading:1",
            }
        ],
        "executionPolicy": {
            "contextPolicy": "FRESH_NO_HISTORY",
            "inheritConversation": False,
            "contextReuseScope": "WITHIN_ACTION_TOOL_LOOP_ONLY",
            "modelProfileId": "model-profile-v1",
            "modelConfigSha256": "d" * 64,
            "tokenAccountingRequirement": "LOCAL_ESTIMATE_MINIMUM",
            "maxOutputTokens": 12000,
            "maxHydrationRounds": 2,
        },
        "hydrateOperation": {"name": "hydrate", "actionId": "action-0007"},
        "submitOperation": {
            "name": "submit",
            "actionId": "action-0007",
            "resultPath": "work/runs/run-0001/actions/action-0007/submission.json",
        },
    }


def valid_run_state() -> dict[str, object]:
    return {
        "contract": "ai-sow-run-state-v1",
        "runId": "run-0001",
        "requestSha256": HEX_A,
        "route": "FULL_COMPILE",
        "phase": "STORY_AC",
        "wait": "MODEL",
        "result": None,
        "currentInputRevisionSha256": HEX_B,
        "currentCandidateSha256": HEX_C,
        "currentCandidatePath": "work/runs/run-0001/candidates/0001-" + HEX_C + ".json",
        "expectedActionIds": ["action-0007"],
        "checkpointRefs": [],
        "budget": {
            "executionPolicySha256": "d" * 64,
            "modelActionsStarted": 1,
            "modelActionsCompleted": 0,
        },
        "resumeFromPhase": None,
    }


def checkpoint_value(kind: str) -> dict[str, object]:
    value: dict[str, object] = {
        "contract": "ai-sow-stage-checkpoint-v1",
        "kind": kind,
        "runId": "run-0001",
        "stage": {
            "SCOPE_CLOSURE": "EPIC_FEATURE",
            "STORY_AC": "STORY_AC",
            "TASK": "TASK",
        }[kind],
        "candidateSha256": HEX_A,
        "sourceManifestSha256": HEX_B,
        "ownerProjectionSha256": HEX_C,
        "coverageSha256": "d" * 64,
        "policyDefinitionSha256": "e" * 64,
        "actionRecordSha256s": [HEX_A],
        "reviewResultSha256s": [],
        "upstreamCheckpointSha256s": [],
        "validatorContractSha256": HEX_B,
        "completedCheckIds": ["check-contract"],
        "decision": "PASS",
    }
    if kind == "STORY_AC":
        value.update(
            {
                "effectivePolicyDecisionSha256": "f" * 64,
                "obligationProjectionSha256": HEX_C,
                "obligationCounts": {"required": 2, "closed": 2},
                "outstandingIds": [],
            }
        )
    if kind == "TASK":
        value.update(
            {
                "effectivePolicyDecisionSha256": "f" * 64,
                "taskCatalogSemanticSha256": HEX_C,
                "taskEstimationMethodSha256": "d" * 64,
                "priorSowInputSha256": "NOT_PROVIDED",
                "usedTaskStandards": [],
                "effectiveStartMatchDecisions": [],
            }
        )
    return value


def test_nine_contract_families_have_stable_ids_and_reject_extra_fields() -> None:
    values = next_schemas()
    assert {name: value["$id"] for name, value in values.items()} == NEXT_SCHEMA_IDS
    samples = {
        "request.schema.json": valid_next_request(),
        "input-revision.schema.json": valid_input_revision(),
        "sow-model.schema.json": valid_sow_model(),
        "run-state.schema.json": valid_run_state(),
        "action.schema.json": valid_action_envelope(),
        "stage-checkpoint.schema.json": checkpoint_value("SCOPE_CLOSURE"),
        "review-repair.schema.json": {
            "contract": "ai-sow-review-plan-v1",
            "reviewSetId": "review-0001",
            "runId": "run-0001",
            "candidateSha256": HEX_A,
            "mode": "FULL",
            "shards": [],
        },
        "artifact-approval.schema.json": {
            "contract": "ai-sow-artifact-manifest-v1",
            "runId": "run-0001",
            "candidateSha256": HEX_A,
            "sourceManifestSha256": "9" * 64,
            "stageCheckpointSha256s": [HEX_A, HEX_B, HEX_C],
            "reviewDecisionSha256": HEX_B,
            "templateSha256": HEX_C,
            "effectivePolicyDecisionSha256": "d" * 64,
            "taskCatalogSemanticSha256": "8" * 64,
            "taskEstimationMethodSha256": "7" * 64,
            "rendererContract": "generation-renderer-v8",
            "rendererSha256": "6" * 64,
            "workbook": {
                "path": "work/runs/run-0001/artifacts/sow.xlsx",
                "sha256": HEX_A,
            },
            "notes": {
                "path": "work/runs/run-0001/artifacts/sow-notes.md",
                "sha256": HEX_B,
            },
            "workbookVerification": {
                "trustState": "VERIFIED",
                "engineName": "LibreOffice",
                "engineVersion": "fixture",
            },
        },
        "generation-manifest.schema.json": {
            "contract": "ai-sow-generation-manifest-v2",
            "generationId": "generation-0001",
            "runId": "run-0001",
            "inputRevisionSha256": HEX_A,
            "sowModelPath": "generations/generation-0001/data/sow-model.json",
            "sowModelSha256": HEX_B,
            "stageCheckpointSha256s": [HEX_A, HEX_B, HEX_C],
            "reviewDecisionSha256": "d" * 64,
            "artifactManifestSha256": "e" * 64,
            "approvalSha256": "f" * 64,
            "templateSha256": HEX_C,
            "effectivePolicyDecisionSha256": "1" * 64,
            "rendererContract": "generation-renderer-v8",
            "rendererSha256": "6" * 64,
            "workbookPath": "generations/generation-0001/output/sow.xlsx",
            "workbookSha256": "2" * 64,
            "notesPath": "generations/generation-0001/output/sow-notes.md",
            "notesSha256": "3" * 64,
            "publicationComplete": True,
        },
        "current.schema.json": {
            "contract": "ai-sow-current-v2",
            "generationId": "generation-0001",
            "generationManifestPath": "generations/generation-0001/manifest.json",
            "generationManifestSha256": HEX_A,
        },
    }
    assert set(samples) == set(NEXT_SCHEMA_IDS) - {"common.schema.json"}
    for schema_name, sample in samples.items():
        validate_next(schema_name, sample)
        invalid = copy.deepcopy(sample)
        invalid["unexpected"] = True
        with pytest.raises(ValidationError):
            validate_next(schema_name, invalid)


def test_run_state_rejects_illegal_route_phase_wait_result_combinations() -> None:
    validate_next("run-state.schema.json", valid_run_state())
    invalid = valid_run_state()
    invalid["result"] = "PUBLISHED"
    with pytest.raises(ValidationError):
        validate_next("run-state.schema.json", invalid)

    done = valid_run_state()
    done.update(
        {
            "phase": "DONE",
            "wait": "NONE",
            "result": "PUBLISHED",
            "expectedActionIds": [],
            "resumeFromPhase": None,
        }
    )
    validate_next("run-state.schema.json", done)


def test_action_envelope_requires_fresh_no_history_and_path_locked_submit() -> None:
    value = valid_action_envelope()
    validate_next("action.schema.json", value)

    inherited = copy.deepcopy(value)
    inherited["executionPolicy"]["inheritConversation"] = True
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", inherited)

    escaped = copy.deepcopy(value)
    escaped["submitOperation"]["resultPath"] = "../submission.json"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", escaped)


def test_stage_result_role_unions_reject_cross_role_payloads() -> None:
    source_scan = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SOURCE_SCAN_PATCH",
        "reviewedEvidenceIds": ["block-prd-001"],
        "blockCoverage": [
            {"blockId": "block-prd-001", "disposition": "READ"}
        ],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": [],
            "deletes": [],
        },
        "selfCheck": {
            "completedCheckIds": ["SOURCE_BLOCK_COVERAGE"],
            "unresolvedItems": [],
        },
    }
    validate_next("action.schema.json", source_scan)
    invalid_source_scan = copy.deepcopy(source_scan)
    invalid_source_scan["blockCoverage"][0]["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", invalid_source_scan)

    scope_proposal = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "SCOPE_PROPOSAL",
        "reviewedEvidenceIds": ["input-refund"],
        "inputItemIds": ["input-refund"],
        "boundaryCandidates": [
            {
                "boundaryId": "boundary-refund",
                "inputItemIds": ["input-refund"],
                "boundarySummary": "退款申请与处理结果形成一个候选能力边界。",
                "scopeClass": "BUSINESS",
                "affinityKeys": ["affinity-refund"],
                "independentClosureEvidence": ["可由退款责任方独立验收。"],
            }
        ],
        "crossShardAffinities": [
            {
                "affinityKey": "affinity-refund",
                "inputItemIds": ["input-refund"],
                "rationale": "与退款失败重试属于同一能力。",
            }
        ],
        "selfCheck": {
            "completedCheckIds": ["NO_FINAL_OWNERSHIP"],
            "unresolvedItems": [],
        },
    }
    validate_next("action.schema.json", scope_proposal)
    invalid_scope_proposal = copy.deepcopy(scope_proposal)
    invalid_scope_proposal["featureIds"] = ["feature-refund"]
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", invalid_scope_proposal)

    patch = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": ["SRC-PRD:B-001"],
        "replacementSet": {
            "expectedNodeHashes": {},
            "upserts": [],
            "deletes": [],
        },
        "selfCheck": {"completedCheckIds": [], "unresolvedItems": []},
    }
    validate_next("action.schema.json", patch)
    wrong = copy.deepcopy(patch)
    wrong["missingFact"] = "越权混入 GAP 字段"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", wrong)

    gap = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "GAP_CANDIDATE",
        "missingFact": "批准设计未定义语言回退。",
        "question": "请在批准设计中补充语言回退规则。",
        "whyAsked": "需求已成立但无法形成实施边界。",
        "answerDetermines": ["Story 技术边界"],
        "unansweredConsequence": "阻断正式 SOW。",
        "checkedEvidenceIds": ["SRC-HLD:B-003"],
        "affectedNodeIds": ["FEATURE-006"],
        "impact": "无法形成可估算 Task。",
        "requiredSourceRole": "APPROVED_DESIGN",
    }
    validate_next("action.schema.json", gap)

    diagnostic = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "DIAGNOSTIC_CANDIDATE",
        "diagnosticCandidateType": "CONTRACT_GAP",
        "subjectIds": ["TASK-014"],
        "checkedEvidenceIds": ["TASK_STANDARD_INDEX:ALL"],
        "summary": "已成立的交付对象没有任何可表达的 v6 工作类型。",
        "suggestedDiagnosticCode": "TASK_STANDARD_TYPE_UNREPRESENTABLE",
    }
    validate_next("action.schema.json", diagnostic)
    wrong_diagnostic = copy.deepcopy(diagnostic)
    wrong_diagnostic["missingFact"] = "混入 GAP_CANDIDATE 字段"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", wrong_diagnostic)


def test_next_action_union_never_waits_for_an_empty_model_action_group() -> None:
    first_action = valid_action_envelope()
    second_action = copy.deepcopy(first_action)
    second_action.update(
        {
            "actionId": "action-0008",
            "logicalShardId": "story-feature-007",
            "packetPath": "work/runs/run-0001/actions/action-0008/packet.json",
            "outputPath": "work/runs/run-0001/actions/action-0008/submission.json",
            "recordPath": "work/runs/run-0001/actions/action-0008/record.json",
        }
    )
    second_action["group"]["requiredLogicalShardIds"] = [
        "story-feature-006",
        "story-feature-007",
    ]
    first_action["group"]["requiredLogicalShardIds"] = [
        "story-feature-006",
        "story-feature-007",
    ]
    second_action["group"]["maxConcurrency"] = 2
    first_action["group"]["maxConcurrency"] = 2
    second_action["hydrateOperation"]["actionId"] = "action-0008"
    second_action["submitOperation"].update(
        {
            "actionId": "action-0008",
            "resultPath": second_action["outputPath"],
        }
    )
    for value in (
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "MODEL_ACTION_GROUP",
            "groupId": "group-story-ac",
            "maxConcurrency": 2,
            "groupDeadlineMilliseconds": 120000,
            "actions": [first_action, second_action],
        },
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "REQUEST_INPUT",
            "questions": [
                {
                    "questionId": "confirm-design",
                    "subjectIds": ["FEATURE-006"],
                    "question": "请补充批准设计。",
                    "whyAsked": "当前设计不足以形成实施边界。",
                    "answerDetermines": ["Story 技术边界"],
                    "unansweredConsequence": "阻断正式 SOW。",
                    "requiredSourceRole": "APPROVED_DESIGN",
                    "checkedEvidenceIds": ["SRC-HLD:B-003"],
                }
            ],
        },
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "REQUEST_APPROVAL",
            "artifactManifestPath": "work/runs/run-0001/artifacts/manifest.json",
            "artifactManifestSha256": HEX_A,
        },
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "DONE",
            "result": "PUBLISHED",
            "generationManifestPath": "generations/generation-0001/manifest.json",
        },
    ):
        validate_next("action.schema.json", value)

    empty_group = {
        "contract": "ai-sow-next-action-v1",
        "kind": "MODEL_ACTION_GROUP",
        "groupId": "group-story-ac",
        "maxConcurrency": 2,
        "groupDeadlineMilliseconds": 120000,
        "actions": [],
    }
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", empty_group)


def test_action_record_requires_estimated_usage_to_name_its_tokenizer() -> None:
    record = {
        "contract": "ai-sow-action-record-v1",
        "runId": "run-0001",
        "actionId": "action-0007",
        "logicalShardId": "story-feature-006",
        "envelopeSha256": HEX_A,
        "packetSha256": HEX_B,
        "inputRevisionSha256": HEX_C,
        "baseCandidateSha256": "d" * 64,
        "modelProfileId": "model-profile-v1",
        "modelConfigSha256": "f" * 64,
        "executionAttempt": 1,
        "status": "SUCCESS",
        "timing": {
            "queueMilliseconds": 10,
            "executionMilliseconds": 100,
            "actionMilliseconds": 120,
        },
        "modelAttempts": 1,
        "toolAttempts": 2,
        "initialPacket": {"bytes": 400, "tokens": 100},
        "hydrationLog": [],
        "usage": {
            "accountingMode": "LOCALLY_ESTIMATED",
            "inputTokens": 100,
            "cachedInputTokens": 0,
            "outputTokens": 20,
            "reasoningTokens": None,
            "tokenizerId": "frozen-tokenizer",
            "tokenizerVersion": "1",
        },
        "controlPlaneTokens": 12,
        "resultPath": "work/runs/run-0001/actions/action-0007/submission.json",
        "submissionSha256": "e" * 64,
        "submission": {
            "contract": "ai-sow-stage-result-v1",
            "resultKind": "PATCH",
            "reviewedEvidenceIds": [],
            "replacementSet": {
                "expectedNodeHashes": {},
                "upserts": [],
                "deletes": [],
            },
            "selfCheck": {"completedCheckIds": [], "unresolvedItems": []},
        },
        "failure": None,
        "completedAt": "2026-09-04T00:00:00Z",
    }
    validate_next("action.schema.json", record)
    persisted = copy.deepcopy(record)
    persisted.pop("submission")
    validate_next("action.schema.json", persisted)
    invalid = copy.deepcopy(record)
    invalid["usage"].pop("tokenizerVersion")
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", invalid)


def test_action_record_accepts_hash_bound_reviewer_result_submission() -> None:
    record = {
        "contract": "ai-sow-action-record-v1",
        "runId": "run-0001",
        "actionId": "action-review-0001",
        "logicalShardId": "r1-source-audit-001",
        "envelopeSha256": HEX_A,
        "packetSha256": HEX_B,
        "inputRevisionSha256": HEX_C,
        "baseCandidateSha256": "d" * 64,
        "modelProfileId": "reviewer-r1-v1",
        "modelConfigSha256": "f" * 64,
        "executionAttempt": 1,
        "status": "SUCCESS",
        "timing": {
            "queueMilliseconds": 10,
            "executionMilliseconds": 100,
            "actionMilliseconds": 120,
        },
        "modelAttempts": 1,
        "toolAttempts": 0,
        "initialPacket": {"bytes": 400, "tokens": 100},
        "hydrationLog": [],
        "usage": {
            "accountingMode": "LOCALLY_ESTIMATED",
            "inputTokens": 100,
            "cachedInputTokens": 0,
            "outputTokens": 20,
            "reasoningTokens": None,
            "tokenizerId": "frozen-tokenizer",
            "tokenizerVersion": "1",
        },
        "controlPlaneTokens": 12,
        "resultPath": "work/runs/run-0001/actions/action-review-0001/submission.json",
        "submissionSha256": "e" * 64,
        "submission": {
            "contract": "ai-sow-review-result-v1",
            "reviewResultId": "review-result-r1-001",
            "reviewSetId": "review-0001",
            "runId": "run-0001",
            "kind": "SOURCE_AUDIT",
            "reviewPlanSha256": HEX_A,
            "candidateProjectionSha256": HEX_B,
            "coverageSha256": HEX_C,
            "completedCheckIds": ["SOURCE_BLOCK_COVERAGE"],
            "decision": "PASS",
            "findings": [],
            "sourceAuditCoverageUnion": ["block-prd-001"],
        },
        "failure": None,
        "completedAt": "2026-09-04T00:00:00Z",
    }
    validate_next("action.schema.json", record)


def test_checkpoint_kinds_require_owner_coverage_and_kind_specific_proof() -> None:
    for kind in ("SCOPE_CLOSURE", "STORY_AC", "TASK"):
        value = checkpoint_value(kind)
        validate_next("stage-checkpoint.schema.json", value)
        invalid = copy.deepcopy(value)
        invalid.pop("ownerProjectionSha256")
        with pytest.raises(ValidationError):
            validate_next("stage-checkpoint.schema.json", invalid)

    invalid_story = checkpoint_value("STORY_AC")
    invalid_story.pop("obligationProjectionSha256")
    with pytest.raises(ValidationError):
        validate_next("stage-checkpoint.schema.json", invalid_story)


def test_review_result_roles_and_repair_plan_are_strict_unions() -> None:
    source_audit = {
        "contract": "ai-sow-review-result-v1",
        "reviewResultId": "review-result-001",
        "reviewSetId": "review-0001",
        "runId": "run-0001",
        "kind": "SOURCE_AUDIT",
        "reviewPlanSha256": HEX_A,
        "candidateProjectionSha256": HEX_B,
        "coverageSha256": HEX_C,
        "completedCheckIds": ["source-coverage"],
        "decision": "PASS",
        "findings": [],
        "sourceAuditCoverageUnion": ["block-prd-001"],
    }
    validate_next("review-repair.schema.json", source_audit)
    crossed = copy.deepcopy(source_audit)
    crossed["leafReviewResultSha256s"] = [HEX_A]
    with pytest.raises(ValidationError):
        validate_next("review-repair.schema.json", crossed)

    for kind, extra in (
        ("STORY_DESIGN", {}),
        ("TASK_ESTIMATION", {}),
        ("THEME_JOIN", {"leafReviewResultSha256s": [HEX_A]}),
        (
            "ADJUDICATION",
            {"propositionId": "proposition-001", "selectedFindingIds": ["finding-001"]},
        ),
    ):
        result = {
            **{key: value for key, value in source_audit.items() if key != "sourceAuditCoverageUnion"},
            "kind": kind,
            **extra,
        }
        validate_next("review-repair.schema.json", result)

    missing_join_proof = {
        **{key: value for key, value in source_audit.items() if key != "sourceAuditCoverageUnion"},
        "kind": "THEME_JOIN",
    }
    with pytest.raises(ValidationError):
        validate_next("review-repair.schema.json", missing_join_proof)

    repair = {
        "contract": "ai-sow-repair-plan-v1",
        "repairPlanId": "repair-0001",
        "runId": "run-0001",
        "baseCandidateSha256": HEX_A,
        "earliestOwner": "STAGE_2",
        "waves": [
            {
                "repairWaveId": "wave-001",
                "findingIds": ["finding-001"],
                "editableNodeIds": ["STORY-001"],
                "contextNodeIds": ["FEATURE-001"],
                "lockedNodeIds": ["EPIC-001"],
                "resumePhase": "STORY_AC",
            }
        ],
    }
    validate_next("review-repair.schema.json", repair)


def test_approval_decision_union_distinguishes_approve_exclude_and_abandon() -> None:
    base = {
        "contract": "ai-sow-approval-v1",
        "runId": "run-0001",
        "artifactManifestSha256": HEX_A,
        "reviewDecisionSha256": HEX_B,
        "candidateSha256": HEX_C,
        "sourceManifestSha256": "d" * 64,
        "templateSha256": "e" * 64,
        "effectivePolicyDecisionSha256": "f" * 64,
    }
    for decision, extra in (
        ("APPROVE", {"approvedAt": "2026-09-04T00:00:00Z"}),
        (
            "EXCLUDE_DEFAULT_AUTOMATION",
            {
                "excludedPolicyInstanceIds": ["policy-sit-automation"],
                "reason": "客户选择不纳入默认自动化。",
            },
        ),
        ("ABANDON", {"reason": "用户终止本轮。"}),
    ):
        value = {**base, "decision": decision, **extra}
        validate_next("artifact-approval.schema.json", value)
        wrong = {**value, "foreignDecisionField": True}
        with pytest.raises(ValidationError):
            validate_next("artifact-approval.schema.json", wrong)


def test_policies_pin_delivery_lifecycle_and_execution_limits() -> None:
    delivery = read_json(CONTRACTS / "delivery-policy-v1.json")
    execution = read_json(CONTRACTS / "execution-policy-v1.json")
    assert delivery["contract"] == "ai-sow-delivery-policy-v1"
    assert {item["policyId"] for item in delivery["policies"]} >= {
        "policy-sit-automation",
        "policy-uat-automation",
        "policy-go-live",
        "policy-data-migration",
    }
    assert execution["contract"] == "ai-sow-execution-policy-v1"
    assert execution["contextAllocation"] == {
        "initialPacketRatio": 0.60,
        "hydrationRatio": 0.15,
        "outputRatio": 0.20,
        "safetyMarginRatio": 0.05,
    }
    assert execution["hardLimits"] == {
        "maxHydrationRoundsPerAction": 2,
        "maxExecutionAttemptsPerShard": 2,
        "maxSemanticRepairRoundsPerProposition": 2,
        "maxAdjudicationsPerProposition": 1,
        "maxReviewReshardDepth": 2,
        "maxPhysicalShardsPerLogicalTheme": 8,
    }


def test_pipeline_dtos_are_frozen() -> None:
    dto_types = (
        SourceDocument,
        InputRevisionResult,
        ActionEnvelope,
        ActionRecord,
        RunState,
        RouteDecision,
        CompilerProgress,
        CompilerResult,
        ReplacementOutcome,
        ReviewProgress,
        TaskStandardCatalog,
        CatalogHydration,
    )
    for dto_type in dto_types:
        assert dto_type.__dataclass_params__.frozen, dto_type.__name__

    state = RunState(value=valid_run_state())
    with pytest.raises(FrozenInstanceError):
        state.value = {}  # type: ignore[misc]


def test_action_binding_rejects_stale_envelope_revision_candidate_and_path() -> None:
    envelope = valid_action_envelope()
    envelope_sha256 = sha256_bytes(canonical_json_bytes(envelope))
    valid = {
        "action_id": "action-0007",
        "envelope_sha256": envelope_sha256,
        "input_revision_sha256": HEX_A,
        "base_candidate_sha256": HEX_B,
        "result_path": envelope["outputPath"],
        "expected_action_ids": ("action-0007",),
    }
    assert validate_action_binding(envelope, **valid) == ()

    cases = {
        "action_id": ("action-stale", "ACTION_ID_MISMATCH"),
        "envelope_sha256": (HEX_C, "ACTION_ENVELOPE_HASH_MISMATCH"),
        "input_revision_sha256": (HEX_C, "ACTION_INPUT_REVISION_STALE"),
        "base_candidate_sha256": (HEX_C, "ACTION_BASE_CANDIDATE_STALE"),
        "result_path": ("work/escaped.json", "ACTION_RESULT_PATH_MISMATCH"),
        "expected_action_ids": (("action-other",), "ACTION_NOT_EXPECTED"),
    }
    for field, (wrong_value, expected_code) in cases.items():
        arguments = {**valid, field: wrong_value}
        assert {item.code for item in validate_action_binding(envelope, **arguments)} == {
            expected_code
        }


def test_state_combination_rejects_completed_action_count_above_started() -> None:
    value = valid_run_state()
    assert validate_state_combination(value, next_registry()) == ()
    value["budget"]["modelActionsCompleted"] = 2
    assert {item.code for item in validate_state_combination(value, next_registry())} == {
        "RUN_BUDGET_COUNT_INVALID"
    }


def test_diagnostic_code_maps_to_exact_category_owner_and_retryability() -> None:
    expected = {
        "GLOBAL_SCOPE_CAPACITY_EXCEEDED": ("CONTRACT_UNSUPPORTED", "STAGE_1", False),
        "SOURCE_SEMANTIC_CONFLICT": ("INPUT_REQUIRED", "INPUT", True),
        "DESIGN_COVERAGE_INSUFFICIENT": ("INPUT_REQUIRED", "INPUT", True),
        "STORY_COVERAGE_OUTSTANDING": ("OWNER_FIX_REQUIRED", "STAGE_2", True),
        "STORY_GLOBAL_JOIN_REQUIRED": ("CONTROL", "STAGE_2", True),
        "TASK_STANDARD_TYPE_UNREPRESENTABLE": ("CONTRACT_UNSUPPORTED", "STAGE_3", False),
        "TASK_CHALLENGER_NOT_REVIEWED": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "PRIOR_MATCH_SEARCH_INCOMPLETE": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "TASK_X_SPLIT_REQUIRED": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "THEME_JOIN_REQUIRED": ("CONTROL", "REVIEW", True),
        "RUN_IN_PROGRESS": ("CONTROL", "ORCHESTRATOR", False),
        "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "HOST_CAPABILITY_MISSING": ("SYSTEM_FAILED", "ORCHESTRATOR", False),
        "BUDGET_EXCEEDED": ("SYSTEM_FAILED", "ORCHESTRATOR", False),
    }
    for code, values in expected.items():
        classification = classify_diagnostic(code)
        assert (
            classification.category,
            classification.owner,
            classification.retryable,
        ) == values

    assert classify_diagnostic("TASK_TYPE_AMBIGUOUS", source_sufficient=True).category == (
        "OWNER_FIX_REQUIRED"
    )
    assert classify_diagnostic("TASK_TYPE_AMBIGUOUS", source_sufficient=False).category == (
        "INPUT_REQUIRED"
    )
    with pytest.raises(ValueError, match="source_sufficient"):
        classify_diagnostic("TASK_TYPE_AMBIGUOUS")
    with pytest.raises(ValueError, match="未知诊断码"):
        classify_diagnostic("UNKNOWN_CODE")


def test_question_hash_and_answer_binding_preserve_typed_gap_wording() -> None:
    question = {
        "questionId": "confirm-design",
        "subjectIds": ["FEATURE-006"],
        "question": "请在批准设计中补充语言回退规则。",
        "whyAsked": "需求已成立，但现有设计不能支持实施拆分和验收。",
        "answerDetermines": ["Story 技术边界", "Task 类型和复杂度"],
        "unansweredConsequence": "阻断正式实施型 SOW。",
        "requiredSourceRole": "APPROVED_DESIGN",
        "checkedEvidenceIds": ["SRC-HLD:B-003"],
    }
    assert validate_typed_gap_question(question) == ()
    answer = {
        "questionId": question["questionId"],
        "questionSha256": question_sha256(question),
        "answer": "回退到中文，并由前端负责切换。",
    }
    assert validate_question_answers([question], [answer]) == ()
    anchor = question_answer_anchors([question], [answer])[0]
    for exact_text in (
        question["question"],
        question["whyAsked"],
        *question["answerDetermines"],
        question["unansweredConsequence"],
    ):
        assert exact_text in anchor.normalized_text

    changed = copy.deepcopy(question)
    changed["whyAsked"] += " 这会影响计费边界。"
    assert question_sha256(changed) != question_sha256(question)
    assert {item.code for item in validate_question_answers([changed], [answer])} == {
        "QUESTION_ANSWER_HASH_MISMATCH"
    }

    invalid_role = {**question, "requiredSourceRole": "MODEL_GUESS"}
    assert {item.code for item in validate_typed_gap_question(invalid_role)} == {
        "QUESTION_REQUIRED_SOURCE_ROLE_INVALID"
    }


def test_contracts_module_contains_no_story_task_or_estimation_rules() -> None:
    source = (SCRIPTS / "contracts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not imported_modules.intersection(
        {"scope_compiler", "delivery_compiler", "task_standard_catalog", "workbook"}
    )
    for business_field in (
        '"workMode"',
        '"complexity"',
        '"acceptanceCriteria"',
        '"taskCatalogSemanticSha256"',
    ):
        assert business_field not in source


def test_canonical_registry_contains_only_the_cutover_contracts() -> None:
    runtime_registry = load_schema_registry(SKILL_ROOT)
    next_contract_registry = load_registry(NEXT_CONTRACTS)
    runtime_ids = set(runtime_registry)
    next_ids = set(next_contract_registry)
    assert runtime_ids
    assert next_ids == set(NEXT_SCHEMA_IDS.values())
    assert runtime_ids == next_ids
