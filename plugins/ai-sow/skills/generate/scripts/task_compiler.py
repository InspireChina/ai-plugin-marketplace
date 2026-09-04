from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

from contracts import canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from delivery_compiler import (
    _story_coverage_sha256,
    _story_owner_projection,
    derive_story_obligations,
)
from models import CompilerProgress, CompilerResult, Diagnostic, TaskStandardCatalog
from sow_model import apply_replacement, validate as validate_sow_model
from task_standard_catalog import compact_index, hydrate


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
STAGE_3_COLLECTIONS = frozenset(
    {"tasks", "dependencies", "effectiveStartMatches", "estimationAnnotations"}
)
TASK_REQUIRED_CHECK_IDS = (
    "STORY_AC_CHECKPOINT_BOUND",
    "TASK_STANDARD_SELECTED",
    "TASK_STANDARD_RULE_HYDRATED",
    "TASK_MEASUREMENT_ATOMIC",
    "STORY_AC_COVERED",
    "EFFECTIVE_START_DECIDED",
    "STAGE_3_WRITE_SCOPE",
)
TASK_CHECKPOINT_CHECK_IDS = (
    "STORY_AC_CHECKPOINT_BOUND",
    "TASK_COVERAGE_COMPLETE",
    "TASK_CATALOG_BOUND",
    "ESTIMATION_METHOD_BOUND",
    "EFFECTIVE_START_BOUND",
    "STAGE_3_ACTIONS_BOUND",
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _estimate_tokens(value: object) -> int:
    return max(1, (len(canonical_json_bytes(value)) + 3) // 4)


def _stage_one_candidate(model: Mapping[str, object]) -> dict[str, object]:
    result = deepcopy(dict(model))
    for collection in (
        "stories",
        "acceptanceCriteria",
        "deliveryAnnotations",
        "tasks",
        "dependencies",
        "effectiveStartMatches",
        "estimationAnnotations",
    ):
        result[collection] = []
    return result


def _validate_story_checkpoint_for_task(
    state: Mapping[str, object],
    candidate: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    checkpoint = state["storyAcCheckpoint"]
    scope_checkpoint = state["scopeClosureCheckpoint"]
    diagnostics = list(
        validate_contract(
            checkpoint, "stage-checkpoint.schema.json", NEXT_SCHEMA_REGISTRY
        )
    )
    try:
        projection = derive_story_obligations(
            candidate, state.get("effectivePolicyDecisions")
        )
    except ValueError:
        return (
            _diagnostic(
                "STORY_AC_CHECKPOINT_BINDING_STALE",
                "无法按当前 effective policy decision 重算 Story obligations。",
                "/effectivePolicyDecisions",
            ),
        )
    expected = {
        "runId": state.get("runId"),
        "ownerProjectionSha256": sha256_bytes(
            canonical_json_bytes(_story_owner_projection(candidate))
        ),
        "coverageSha256": _story_coverage_sha256(candidate, projection),
        "policyDefinitionSha256": candidate.get("project", {}).get(
            "policyDefinitionSha256"
        ),
        "effectivePolicyDecisionSha256": sha256_bytes(
            canonical_json_bytes(projection["effectivePolicyDecisions"])
        ),
        "obligationProjectionSha256": projection["projectionSha256"],
        "upstreamCheckpointSha256s": [
            sha256_bytes(canonical_json_bytes(scope_checkpoint))
        ],
    }
    for field, value in expected.items():
        if checkpoint.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "STORY_AC_CHECKPOINT_BINDING_STALE",
                    "STORY_AC checkpoint 不再绑定当前 Stage 2 投影。",
                    f"/{field}",
                )
            )
    return _sort(diagnostics)


def _error(outcome: str, code: str, message: str, path: str) -> Mapping[str, object]:
    return {
        "outcome": outcome,
        "actionKind": "TASK",
        "specs": [],
        "diagnostics": [
            {"code": code, "message": message, "path": path, "details": {}}
        ],
    }


def hydrate_catalog(
    state: Mapping[str, object],
    selected_work_type_ids: Sequence[str],
    query: str,
):
    """Host-neutral Task Standard hydration; no CLI or conversation state required."""
    source = state.get("taskCatalog")
    if not isinstance(source, TaskStandardCatalog):
        raise ValueError("taskCatalog must be a validated TaskStandardCatalog")
    return hydrate(source, selected_work_type_ids, query)


def _story_material(
    candidate: Mapping[str, object], story: Mapping[str, object]
) -> dict[str, object]:
    story_id = str(story["storyId"])
    feature_id = str(story["featureId"])
    feature = next(
        (
            item
            for item in _mappings(candidate.get("features"))
            if item.get("featureId") == feature_id
        ),
        None,
    )
    return {
        "story": deepcopy(dict(story)),
        "acceptanceCriteria": [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("acceptanceCriteria"))
            if item.get("storyId") == story_id
        ],
        "feature": deepcopy(dict(feature)) if isinstance(feature, Mapping) else None,
        "designItems": [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("designItems"))
            if feature_id in item.get("featureIds", [])
        ],
        "integrations": [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("integrations"))
            if feature_id in item.get("featureIds", [])
        ],
        "nfrs": [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("nfrs"))
            if feature_id in item.get("featureIds", [])
        ],
        "policyInstances": [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("policyInstances"))
            if item.get("policyInstanceId") in story.get("policyRefs", [])
        ],
    }


def _story_evidence(materials: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for material in materials:
        story = material["story"]
        story_id = str(story["storyId"])
        content = canonical_json_bytes(material).decode("utf-8")
        result.append(
            {
                "evidenceId": f"task-input-{story_id}",
                "locator": f"story:{story_id}",
                "content": content,
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
        )
    return result


def _task_spec(
    state: Mapping[str, object],
    compact: Sequence[Mapping[str, object]],
    materials: Sequence[Mapping[str, object]],
    sequence: int,
) -> dict[str, object]:
    story_ids = [str(item["story"]["storyId"]) for item in materials]
    evidence = _story_evidence(materials)
    return {
        "logicalShardId": f"task-{sequence:03d}",
        "stage": "TASK",
        "role": "AUTHOR",
        "promptId": "stage3-task-v1",
        "promptPath": "prompts/stage3-task.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/task-authoring.md",
            "references/effective-start-matching.md",
            "references/delivery-work-classification.md",
            "references/delivery-lifecycle-policy.md",
        ],
        "evidenceCatalog": evidence,
        "packet": {
            "storyAcCheckpointSha256": sha256_bytes(
                canonical_json_bytes(state["storyAcCheckpoint"])
            ),
            "taskCatalogSemanticSha256": state[
                "taskCatalog"
            ].task_catalog_semantic_sha256,
            "taskEstimationMethodSha256": state[
                "taskEstimationMethodSha256"
            ],
            "priorSowInputSha256": state["priorSowInputSha256"],
            "assignedStoryIds": story_ids,
            "assignedStories": deepcopy(list(materials)),
            "assignedEvidenceIds": [item["evidenceId"] for item in evidence],
            "taskStandardCompactIndex": deepcopy(list(compact)),
            "catalogHydration": {
                "operation": "hydrate-task-standard",
                "maxRounds": 2,
                "selectionKey": "工作类型ID",
            },
            "requiredCheckIds": list(TASK_REQUIRED_CHECK_IDS),
            "allowedWriteCollections": sorted(STAGE_3_COLLECTIONS),
        },
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def prepare_action(state: Mapping[str, object], action_kind: str) -> Mapping[str, object]:
    if action_kind != "TASK":
        return _error(
            "CONTRACT_UNSUPPORTED",
            "COMPILER_ACTION_KIND_UNSUPPORTED",
            "Task Compiler 只接受 TASK action kind。",
            "/actionKind",
        )
    candidate = state.get("baseCandidate")
    checkpoint = state.get("storyAcCheckpoint")
    source = state.get("taskCatalog")
    if not (
        isinstance(candidate, Mapping)
        and isinstance(checkpoint, Mapping)
        and isinstance(source, TaskStandardCatalog)
    ):
        return _error(
            "CONTRACT_UNSUPPORTED",
            "TASK_STATE_INVALID",
            "Task action 缺少 Story candidate、STORY_AC checkpoint 或有效目录。",
            "/state",
        )
    checkpoint_diagnostics = _validate_story_checkpoint_for_task(state, candidate)
    if checkpoint_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "actionKind": "TASK",
            "specs": [],
            "diagnostics": [
                {
                    "code": item.code,
                    "message": item.message,
                    "path": item.path,
                    "details": dict(item.details),
                }
                for item in checkpoint_diagnostics
            ],
        }
    if source.template_sha256 != candidate.get("project", {}).get("templateSha256"):
        return _error(
            "CONTRACT_UNSUPPORTED",
            "TASK_TEMPLATE_BINDING_MISMATCH",
            "Task Standard Catalog 必须来自 Input Revision 绑定的同一模板。",
            "/taskCatalog/templateSha256",
        )
    if state.get("priorSowInputSha256") not in {
        "NOT_PROVIDED",
        *state.get("inputRevision", {}).get("priorSowSha256s", []),
    }:
        return _error(
            "CONTRACT_UNSUPPORTED",
            "PRIOR_SOW_BINDING_MISMATCH",
            "priorSowInputSha256 未绑定当前 Input Revision。",
            "/priorSowInputSha256",
        )
    token_budget = state.get("maxInitialPacketTokens")
    if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1:
        return _error(
            "CONTRACT_UNSUPPORTED",
            "TASK_STATE_INVALID",
            "Task 初始 packet token 预算无效。",
            "/maxInitialPacketTokens",
        )
    compact = [dict(item) for item in compact_index(source)]
    materials = [
        _story_material(candidate, story)
        for story in _mappings(candidate.get("stories"))
    ]
    batches: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    for material in materials:
        attempted = [*current, material]
        spec = _task_spec(state, compact, attempted, len(batches) + 1)
        estimate = _estimate_tokens(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
        if current and estimate > token_budget:
            batches.append(current)
            current = [material]
        else:
            current = attempted
    if current:
        batches.append(current)
    specs = [
        _task_spec(state, compact, batch, index)
        for index, batch in enumerate(batches, 1)
    ]
    estimates = [
        _estimate_tokens(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
        for spec in specs
    ]
    if len(specs) > 8 or any(value > token_budget for value in estimates):
        return _error(
            "CONTRACT_UNSUPPORTED",
            "TASK_CAPACITY_EXCEEDED",
            "Task stories 与 compact catalog 无法在安全上下文预算内完整分配。",
            "/baseCandidate/stories",
        )
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "TASK",
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": [],
    }


def _packet_sha256(spec: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
    )


def _validate_task_nodes(
    state: Mapping[str, object],
    spec: Mapping[str, object],
    replacement: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    source: TaskStandardCatalog = state["taskCatalog"]
    assigned_story_ids = set(_ids(spec["packet"].get("assignedStoryIds")))
    base = state["baseCandidate"]
    ac_story = {
        str(item["acceptanceCriterionId"]): str(item["storyId"])
        for item in _mappings(base.get("acceptanceCriteria"))
    }
    tasks: dict[str, Mapping[str, object]] = {}
    matches: dict[str, Mapping[str, object]] = {}
    for position, wrapper in enumerate(_mappings(replacement.get("upserts"))):
        collection = wrapper.get("collection")
        node = wrapper.get("node")
        if collection not in STAGE_3_COLLECTIONS:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Task action 只能写 Stage 3 区域。",
                    f"/replacementSet/upserts/{position}",
                )
            )
            continue
        if not isinstance(node, Mapping):
            continue
        if collection == "tasks":
            task_id = str(node.get("taskId"))
            tasks[task_id] = node
            work_type_id = node.get("workTypeId")
            row = source.by_work_type_id.get(str(work_type_id))
            if row is None:
                diagnostics.append(
                    _diagnostic(
                        "TASK_STANDARD_UNKNOWN",
                        "Task 必须选择当前模板目录中的工作类型。",
                        f"/tasks/{task_id}/workTypeId",
                    )
                )
            else:
                if node.get("rowSemanticSha256") != row.get("rowSemanticSha256"):
                    diagnostics.append(
                        _diagnostic(
                            "TASK_STANDARD_HASH_MISMATCH",
                            "Task rowSemanticSha256 与当前模板规则不一致。",
                            f"/tasks/{task_id}/rowSemanticSha256",
                        )
                    )
                mode = node.get("workMode")
                if row.get(f"{mode}适用") is not True:
                    diagnostics.append(
                        _diagnostic(
                            "TASK_WORK_MODE_NOT_ALLOWED",
                            "当前工作类型不允许候选 workMode。",
                            f"/tasks/{task_id}/workMode",
                        )
                    )
            if node.get("storyId") not in assigned_story_ids:
                diagnostics.append(
                    _diagnostic(
                        "TASK_STORY_NOT_ASSIGNED",
                        "Task 只能属于当前 shard 分配的 Story。",
                        f"/tasks/{task_id}/storyId",
                    )
                )
            for ac_id in _ids(node.get("acceptanceCriterionIds")):
                if ac_story.get(ac_id) != node.get("storyId"):
                    diagnostics.append(
                        _diagnostic(
                            "TASK_AC_STORY_MISMATCH",
                            "Task 引用的 AC 必须属于同一 Story。",
                            f"/tasks/{task_id}/acceptanceCriterionIds/{ac_id}",
                        )
                    )
        elif collection == "effectiveStartMatches":
            matches[str(node.get("taskId"))] = node
    for task_id, task in tasks.items():
        match = matches.get(task_id)
        expected = {
            "新建": "NO_MATCH_NEW",
            "调整": "MATCHED_ADJUSTMENT",
            "接入复用": "MATCHED_REUSE",
        }.get(str(task.get("workMode")))
        if match is None or match.get("decision") != expected:
            diagnostics.append(
                _diagnostic(
                    "TASK_EFFECTIVE_START_MODE_MISMATCH",
                    "每个 Task 的 workMode 必须由同 Task 的 Effective Start 决定支持。",
                    f"/tasks/{task_id}/workMode",
                )
            )
        if task.get("workMode") in {"调整", "接入复用"} and (
            match is None
            or not _ids(match.get("candidateIds"))
            or not _ids(match.get("checkedLocators"))
        ):
            diagnostics.append(
                _diagnostic(
                    "TASK_EFFECTIVE_START_EVIDENCE_MISSING",
                    "调整或接入复用必须绑定具体起点对象与已检查证据位置。",
                    f"/effectiveStartMatches/{task_id}",
                )
            )
        if (
            state.get("priorSowInputSha256") == "NOT_PROVIDED"
            and task.get("workMode") != "新建"
        ):
            diagnostics.append(
                _diagnostic(
                    "TASK_EFFECTIVE_START_MODE_MISMATCH",
                    "没有 Prior SOW 或当前起点证据时只能使用新建。",
                    f"/tasks/{task_id}/workMode",
                )
            )
    if set(tasks) != set(matches):
        diagnostics.append(
            _diagnostic(
                "TASK_EFFECTIVE_START_SET_MISMATCH",
                "effectiveStartMatches 必须与当前 shard Task 一一对应。",
                "/effectiveStartMatches",
            )
        )
    return _sort(diagnostics)


def _validate_record(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    record: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    specs = {
        str(item["logicalShardId"]): item
        for item in _mappings(prepared.get("specs"))
    }
    spec = specs.get(str(record.get("logicalShardId")))
    if spec is None:
        diagnostics.append(
            _diagnostic(
                "TASK_SHARD_UNKNOWN",
                "Task record 不属于当前冻结 action group。",
                "/logicalShardId",
            )
        )
        return _sort(diagnostics)
    expected = {
        "runId": state.get("runId"),
        "packetSha256": _packet_sha256(spec),
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(state.get("inputRevision"))
        ),
        "baseCandidateSha256": state.get("baseCandidateSha256"),
        "modelProfileId": state.get("modelProfileId"),
        "modelConfigSha256": state.get("modelConfigSha256"),
    }
    for field, value in expected.items():
        if record.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "TASK_RECORD_BINDING_MISMATCH",
                    "Task record 与当前冻结输入不匹配。",
                    f"/{field}",
                )
            )
    submission = record.get("submission")
    if record.get("status") != "SUCCESS" or not isinstance(submission, Mapping):
        diagnostics.append(
            _diagnostic(
                "TASK_RECORD_NOT_SUCCESSFUL",
                "Task Compiler 只接受成功 ActionRecord。",
                "/status",
            )
        )
        return _sort(diagnostics)
    if submission.get("resultKind") != "PATCH":
        diagnostics.append(
            _diagnostic(
                "TASK_RESULT_KIND_INVALID", "Task action 必须返回 PATCH。", "/submission/resultKind"
            )
        )
    if record.get("submissionSha256") != sha256_bytes(canonical_json_bytes(submission)):
        diagnostics.append(
            _diagnostic(
                "TASK_SUBMISSION_HASH_MISMATCH",
                "Task submission hash 与内容不一致。",
                "/submissionSha256",
            )
        )
    if submission.get("reviewedEvidenceIds") != spec["packet"]["assignedEvidenceIds"]:
        diagnostics.append(
            _diagnostic(
                "TASK_EVIDENCE_MISMATCH",
                "Task action 必须复核全部 assigned Story evidence。",
                "/submission/reviewedEvidenceIds",
            )
        )
    self_check = submission.get("selfCheck")
    if not isinstance(self_check, Mapping) or self_check.get("completedCheckIds") != list(
        TASK_REQUIRED_CHECK_IDS
    ):
        diagnostics.append(
            _diagnostic(
                "TASK_SELF_CHECK_INCOMPLETE",
                "Task action 必须完成全部冻结检查项。",
                "/submission/selfCheck/completedCheckIds",
            )
        )
    replacement = submission.get("replacementSet")
    if isinstance(replacement, Mapping):
        diagnostics.extend(_validate_task_nodes(state, spec, replacement))
        for key in [
            *(replacement.get("expectedNodeHashes", {}).keys() if isinstance(replacement.get("expectedNodeHashes"), Mapping) else []),
            *(replacement.get("deletes", []) if isinstance(replacement.get("deletes"), list) else []),
        ]:
            if str(key).split(":", 1)[0] not in STAGE_3_COLLECTIONS:
                diagnostics.append(
                    _diagnostic(
                        "OWNER_WRITE_SCOPE_VIOLATION",
                        "Task action 不得修改其他 Owner 的区域。",
                        "/submission/replacementSet",
                    )
                )
    return _sort(diagnostics)


def accept_result(state: Mapping[str, object], record: Mapping[str, object]) -> CompilerProgress:
    prepared = prepare_action(state, "TASK")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return CompilerProgress(
            "FAILED", (), (_diagnostic("TASK_PREPARE_FAILED", "Task action 未成功冻结。", "/state"),)
        )
    diagnostics = _validate_record(state, prepared, record)
    if diagnostics:
        return CompilerProgress("FAILED", (), diagnostics)
    completed = {
        str(item.get("logicalShardId"))
        for item in [
            *_mappings(state.get("acceptedRecords")),
            record,
        ]
        if item.get("status") == "SUCCESS"
    }
    required = [str(item["logicalShardId"]) for item in prepared["specs"]]
    pending = tuple(item for item in required if item not in completed)
    return CompilerProgress("ACTION_REQUIRED" if pending else "CHECKPOINT_READY", pending, ())


def _task_coverage_diagnostics(model: Mapping[str, object]) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    tasks = _mappings(model.get("tasks"))
    matches = {
        str(item.get("taskId")): item
        for item in _mappings(model.get("effectiveStartMatches"))
    }
    criteria_by_story: defaultdict[str, set[str]] = defaultdict(set)
    for criterion in _mappings(model.get("acceptanceCriteria")):
        criteria_by_story[str(criterion.get("storyId"))].add(
            str(criterion.get("acceptanceCriterionId"))
        )
    for story in _mappings(model.get("stories")):
        story_id = str(story.get("storyId"))
        story_tasks = [item for item in tasks if item.get("storyId") == story_id]
        covered = {
            ac_id
            for task in story_tasks
            for ac_id in _ids(task.get("acceptanceCriterionIds"))
        }
        if not story_tasks or covered != criteria_by_story[story_id]:
            diagnostics.append(
                _diagnostic(
                    "TASK_STORY_AC_COVERAGE_INCOMPLETE",
                    "每个 Story 的全部且仅其自身 AC 必须由至少一个 Task 覆盖。",
                    f"/stories/{story_id}",
                )
            )
        for field, task_field, code in (
            ("designRefs", "designItemIds", "TASK_STORY_DESIGN_COVERAGE_INCOMPLETE"),
            ("policyRefs", "policyInstanceIds", "TASK_STORY_POLICY_COVERAGE_INCOMPLETE"),
        ):
            required = set(_ids(story.get(field)))
            actual = {
                value
                for task in story_tasks
                for value in _ids(task.get(task_field))
            }
            if not required.issubset(actual):
                diagnostics.append(
                    _diagnostic(
                        code,
                        "Story 引用的批准设计与交付政策必须由同 Story Task 落实。",
                        f"/stories/{story_id}/{field}",
                    )
                )
    for integration in _mappings(model.get("integrations")):
        integration_id = str(integration.get("integrationId"))
        owners = [
            task
            for task in tasks
            if integration_id in task.get("integrationIds", [])
            and task.get("workTypeId") in {"IN-INTEGRATION", "IN-IDENTITY"}
        ]
        if len(owners) != 1:
            diagnostics.append(
                _diagnostic(
                    "TASK_INTEGRATION_OWNER_NON_UNIQUE",
                    "每个已批准 Integration 必须由唯一集成 Task 负责。",
                    f"/integrations/{integration_id}",
                )
            )
    for task in tasks:
        task_id = str(task.get("taskId"))
        decision = matches.get(task_id, {}).get("decision")
        expected = {
            "新建": "NO_MATCH_NEW",
            "调整": "MATCHED_ADJUSTMENT",
            "接入复用": "MATCHED_REUSE",
        }.get(str(task.get("workMode")))
        if decision != expected:
            diagnostics.append(
                _diagnostic(
                    "TASK_EFFECTIVE_START_MODE_MISMATCH",
                    "Task 与 Effective Start decision 不一致。",
                    f"/tasks/{task_id}/workMode",
                )
            )
    if set(matches) != {str(item.get("taskId")) for item in tasks}:
        diagnostics.append(
            _diagnostic(
                "TASK_EFFECTIVE_START_SET_MISMATCH",
                "每个 Task 必须恰有一个 Effective Start decision。",
                "/effectiveStartMatches",
            )
        )
    return _sort(diagnostics)


def apply_ready_group(
    state: Mapping[str, object], records: Sequence[Mapping[str, object]]
) -> CompilerResult:
    base = state.get("baseCandidate")
    if not isinstance(base, Mapping):
        return CompilerResult({}, "", {}, (_diagnostic("TASK_STATE_INVALID", "缺少 Task 基础 candidate。", "/baseCandidate"),))
    prepared = prepare_action(state, "TASK")
    required = [str(item["logicalShardId"]) for item in _mappings(prepared.get("specs"))]
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for record in records:
        shard_id = str(record.get("logicalShardId"))
        duplicate = duplicate or shard_id in by_shard
        by_shard[shard_id] = record
    if prepared.get("outcome") != "ACTION_REQUIRED" or duplicate or set(by_shard) != set(required):
        return CompilerResult(
            deepcopy(dict(base)),
            sha256_bytes(canonical_json_bytes(base)),
            {},
            (_diagnostic("TASK_GROUP_INCOMPLETE", "Task group 必须包含全部冻结 sibling records。", "/records"),),
        )
    diagnostics = tuple(
        item
        for shard_id in required
        for item in _validate_record(state, prepared, by_shard[shard_id])
    )
    if diagnostics:
        return CompilerResult(deepcopy(dict(base)), sha256_bytes(canonical_json_bytes(base)), {}, _sort(diagnostics))
    combined: dict[str, object] = {"expectedNodeHashes": {}, "upserts": [], "deletes": []}
    for shard_id in required:
        replacement = by_shard[shard_id]["submission"]["replacementSet"]
        for key, value in replacement["expectedNodeHashes"].items():
            if key in combined["expectedNodeHashes"]:
                diagnostics += (_diagnostic("TASK_REPLACEMENT_OVERLAP", "Task shards 不得修改同一节点。", f"/records/{shard_id}/{key}"),)
            combined["expectedNodeHashes"][key] = value
        combined["upserts"].extend(replacement["upserts"])
        combined["deletes"].extend(replacement["deletes"])
    if diagnostics:
        return CompilerResult(deepcopy(dict(base)), sha256_bytes(canonical_json_bytes(base)), {}, _sort(diagnostics))
    outcome = apply_replacement(base, combined, owner_stage="STAGE_3")
    if outcome.diagnostics:
        return CompilerResult(deepcopy(dict(base)), sha256_bytes(canonical_json_bytes(base)), {}, outcome.diagnostics)
    diagnostics = _sort(
        [
            *validate_sow_model(outcome.candidate, "STAGE_3", registry=NEXT_SCHEMA_REGISTRY),
            *_task_coverage_diagnostics(outcome.candidate),
        ]
    )
    if diagnostics:
        return CompilerResult(outcome.candidate, outcome.candidate_sha256, {}, diagnostics)
    return CompilerResult(
        outcome.candidate,
        outcome.candidate_sha256,
        {
            "kind": "TASK_CANDIDATE",
            "coverageSha256": _task_coverage_sha256(outcome.candidate),
            "recordSha256s": [
                sha256_bytes(canonical_json_bytes(by_shard[shard_id]))
                for shard_id in required
            ],
        },
        (),
    )


def _task_owner_projection(model: Mapping[str, object]) -> dict[str, object]:
    return {
        collection: deepcopy(list(_mappings(model.get(collection))))
        for collection in sorted(STAGE_3_COLLECTIONS)
    }


def _task_coverage_sha256(model: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "storyAc": [
                    {
                        "storyId": story.get("storyId"),
                        "acceptanceCriterionIds": [
                            item.get("acceptanceCriterionId")
                            for item in _mappings(model.get("acceptanceCriteria"))
                            if item.get("storyId") == story.get("storyId")
                        ],
                    }
                    for story in _mappings(model.get("stories"))
                ],
                "tasks": model.get("tasks", []),
                "integrations": [
                    item.get("integrationId")
                    for item in _mappings(model.get("integrations"))
                ],
                "effectiveStartMatches": model.get("effectiveStartMatches", []),
            }
        )
    )


def _task_checkpoint_material(
    state: Mapping[str, object],
) -> tuple[dict[str, object], tuple[Diagnostic, ...]]:
    candidate = state.get("candidate")
    source = state.get("taskCatalog")
    checkpoint = state.get("storyAcCheckpoint")
    if not (
        isinstance(candidate, Mapping)
        and isinstance(source, TaskStandardCatalog)
        and isinstance(checkpoint, Mapping)
    ):
        return {}, (_diagnostic("TASK_CHECKPOINT_STATE_INVALID", "Task checkpoint 输入状态无效。", "/state"),)
    task_diagnostics = list(
        validate_sow_model(candidate, "STAGE_3", registry=NEXT_SCHEMA_REGISTRY)
    )
    task_diagnostics.extend(_task_coverage_diagnostics(candidate))
    prepared = prepare_action(state, "TASK")
    records = _mappings(state.get("taskActionRecords"))
    required = [str(item["logicalShardId"]) for item in _mappings(prepared.get("specs"))]
    by_shard = {str(item.get("logicalShardId")): item for item in records}
    if prepared.get("outcome") != "ACTION_REQUIRED" or len(by_shard) != len(records) or set(by_shard) != set(required):
        task_diagnostics.append(
            _diagnostic("TASK_ACTION_PROOF_INCOMPLETE", "Task checkpoint 缺少完整冻结 ActionRecord 集。", "/taskActionRecords")
        )
        action_hashes: list[str] = []
    else:
        for shard_id in required:
            task_diagnostics.extend(_validate_record(state, prepared, by_shard[shard_id]))
        action_hashes = [
            sha256_bytes(canonical_json_bytes(by_shard[shard_id]))
            for shard_id in required
        ]
        replay = apply_ready_group(state, records)
        task_diagnostics.extend(replay.diagnostics)
        if not replay.diagnostics and canonical_json_bytes(_task_owner_projection(replay.model)) != canonical_json_bytes(_task_owner_projection(candidate)):
            task_diagnostics.append(
                _diagnostic("TASK_CANDIDATE_RECORD_MISMATCH", "Task candidate 不是冻结 records 一次性 Join 的结果。", "/candidate")
            )
    used_ids = sorted({str(item.get("workTypeId")) for item in _mappings(candidate.get("tasks"))})
    used_rows = [
        {
            "workTypeId": work_type_id,
            "rowSemanticSha256": source.by_work_type_id[work_type_id]["rowSemanticSha256"],
        }
        for work_type_id in used_ids
        if work_type_id in source.by_work_type_id
    ]
    if len(used_rows) != len(used_ids):
        task_diagnostics.append(
            _diagnostic("TASK_STANDARD_UNKNOWN", "Task checkpoint 引用了未知工作类型。", "/tasks")
        )
    matches = sorted(
        _mappings(candidate.get("effectiveStartMatches")),
        key=lambda item: str(item.get("taskId")),
    )
    effective_decisions = [
        {
            "taskId": item.get("taskId"),
            "decision": item.get("decision"),
            "evidenceSha256": sha256_bytes(canonical_json_bytes(item)),
        }
        for item in matches
    ]
    upstream = [sha256_bytes(canonical_json_bytes(checkpoint))]
    review_results = sorted(
        _mappings(state.get("taskReviewResults")),
        key=lambda item: str(item.get("logicalShardId", "")),
    )
    material = {
        "sourceManifestSha256": checkpoint.get("sourceManifestSha256"),
        "ownerProjectionSha256": sha256_bytes(canonical_json_bytes(_task_owner_projection(candidate))),
        "coverageSha256": _task_coverage_sha256(candidate),
        "policyDefinitionSha256": checkpoint.get("policyDefinitionSha256"),
        "actionRecordSha256s": action_hashes,
        "reviewResultSha256s": [
            sha256_bytes(canonical_json_bytes(item.get("result") if isinstance(item.get("result"), Mapping) else item))
            for item in review_results
        ],
        "upstreamCheckpointSha256s": upstream,
        "effectivePolicyDecisionSha256": checkpoint.get("effectivePolicyDecisionSha256"),
        "taskCatalogSemanticSha256": source.task_catalog_semantic_sha256,
        "taskEstimationMethodSha256": state.get("taskEstimationMethodSha256"),
        "priorSowInputSha256": state.get("priorSowInputSha256"),
        "usedTaskStandards": used_rows,
        "effectiveStartMatchDecisions": effective_decisions,
    }
    return material, _sort(task_diagnostics)


def build_task_checkpoint(state: Mapping[str, object]) -> Mapping[str, object]:
    material, diagnostics = _task_checkpoint_material(state)
    if diagnostics:
        return {"outcome": "OWNER_FIX_REQUIRED", "checkpoint": None, "diagnostics": diagnostics}
    checkpoint = {
        "contract": "ai-sow-stage-checkpoint-v1",
        "kind": "TASK",
        "runId": state["runId"],
        "stage": "TASK",
        "candidateSha256": sha256_bytes(canonical_json_bytes(state["candidate"])),
        **material,
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(TASK_CHECKPOINT_CHECK_IDS),
        "decision": "PASS",
    }
    contract_diagnostics = validate_contract(checkpoint, "stage-checkpoint.schema.json", NEXT_SCHEMA_REGISTRY)
    if contract_diagnostics:
        return {"outcome": "CONTRACT_UNSUPPORTED", "checkpoint": None, "diagnostics": contract_diagnostics}
    return {
        "outcome": "READY_FOR_REVIEW",
        "checkpoint": checkpoint,
        "checkpointSha256": sha256_bytes(canonical_json_bytes(checkpoint)),
        "diagnostics": (),
    }


def validate_task_checkpoint(
    checkpoint: Mapping[str, object], state: Mapping[str, object]
) -> tuple[Diagnostic, ...]:
    diagnostics = list(validate_contract(checkpoint, "stage-checkpoint.schema.json", NEXT_SCHEMA_REGISTRY))
    material, material_diagnostics = _task_checkpoint_material(state)
    diagnostics.extend(material_diagnostics)
    expected = {
        "runId": state.get("runId"),
        **material,
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(TASK_CHECKPOINT_CHECK_IDS),
    }
    for field, value in expected.items():
        if checkpoint.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "TASK_CHECKPOINT_BINDING_STALE",
                    "TASK checkpoint 不再绑定当前 Stage 3 投影或证明闭包。",
                    f"/{field}",
                )
            )
    return _sort(diagnostics)
