from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

from contracts import (
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_contract,
)
from models import (
    CompilerProgress,
    CompilerResult,
    Diagnostic,
)
from scope_compiler import validate_scope_closure_checkpoint
from sow_model import apply_replacement, validate as validate_sow_model


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
STORY_AC_REQUIRED_CHECK_IDS = (
    "OBLIGATION_PROJECTION_BOUND",
    "ASSIGNED_OBLIGATIONS_CLOSED",
    "QUALIFIERS_PRESERVED",
    "INDEPENDENT_BOUNDARIES_SEPARATED",
    "DESIGN_AUTHORITY_PRESERVED",
    "STAGE_2_WRITE_SCOPE",
)
STORY_AC_CHECKPOINT_CHECK_IDS = (
    "SCOPE_CHECKPOINT_BOUND",
    "EFFECTIVE_POLICY_DECISION_BOUND",
    "OBLIGATION_PROJECTION_BOUND",
    "STORY_AC_COVERAGE_COMPLETE",
    "STAGE_2_ACTIONS_BOUND",
)
STAGE_2_COLLECTIONS = frozenset(
    {"stories", "acceptanceCriteria", "deliveryAnnotations"}
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _unique(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in result:
            result.append(value)
    return result


def _story_token_estimate(value: object) -> int:
    return max(1, (len(canonical_json_bytes(value)) + 3) // 4)


def _policy_decision_map(
    model: Mapping[str, object],
    effective_policy_decisions: object,
) -> dict[str, str]:
    expected = {
        str(item["policyInstanceId"]): item
        for item in _mappings(model.get("policyInstances"))
        if isinstance(item.get("policyInstanceId"), str)
    }
    if isinstance(effective_policy_decisions, Mapping):
        raw = dict(effective_policy_decisions)
    elif isinstance(effective_policy_decisions, list):
        raw = {
            str(item.get("policyInstanceId")): item.get("decision")
            for item in _mappings(effective_policy_decisions)
        }
    else:
        raise ValueError("effective policy decisions must be a mapping or list")
    if set(raw) != set(expected) or any(
        value not in {"INCLUDED", "EXCLUDED"} for value in raw.values()
    ):
        raise ValueError("effective policy decisions must cover every policy instance")
    for policy_instance_id, decision in raw.items():
        policy = expected[policy_instance_id]
        if decision == "EXCLUDED" and policy.get("inclusionPolicy") in {
            "REQUIRED",
            "SOURCE_GATED",
        }:
            raise ValueError("required or source-gated policy instance cannot be excluded")
    return {key: str(raw[key]) for key in sorted(raw)}


def _story_boundary_key(
    closure: Mapping[str, object],
) -> str:
    qualifiers = [
        value
        for value in _ids(closure.get("preservedQualifiers"))
        if any(
            marker in value
            for marker in (
                "独立",
                "责任方",
                "验收边界",
                "发布边界",
                "定制",
                "custom",
                "responsibility",
                "acceptance",
                "release",
            )
        )
    ]
    boundary = {
        "assignedFeatureIds": list(_ids(closure.get("assignedFeatureIds"))),
        "crossFeatureRuleIds": list(_ids(closure.get("crossFeatureRuleIds"))),
        "crossFeatureTargetIds": list(
            _ids(closure.get("crossFeatureTargetIds"))
        ),
        "requiredQualifierRefs": list(
            _ids(closure.get("requiredQualifierRefs"))
        ),
        "independentQualifiers": qualifiers,
    }
    digest = sha256_bytes(canonical_json_bytes(boundary))[:16]
    return f"story-boundary-{digest}"


def _coverage_set(
    input_item: Mapping[str, object],
    closure: Mapping[str, object],
) -> list[str]:
    qualifiers = [
        *_ids(closure.get("preservedQualifiers")),
        *_ids(input_item.get("thresholds")),
        *_ids(input_item.get("applicableScopes")),
    ]
    if any("九个服务" in value for value in qualifiers):
        return [f"service-{index:02d}" for index in range(1, 10)]
    explicit = _unique(
        [
            *_ids(closure.get("requiredQualifierRefs")),
            *_ids(closure.get("crossFeatureTargetIds")),
        ]
    )
    return explicit or list(_ids(closure.get("assignedFeatureIds")))


def derive_story_obligations(
    model: Mapping[str, object],
    effective_policy_decisions: object,
) -> Mapping[str, object]:
    """Deterministically project frozen Stage 1 scope into Story/AC obligations."""
    decisions = _policy_decision_map(model, effective_policy_decisions)
    input_by_id = {
        str(item["inputItemId"]): item
        for item in _mappings(model.get("inputItems"))
        if isinstance(item.get("inputItemId"), str)
    }
    feature_by_id = {
        str(item["featureId"]): item
        for item in _mappings(model.get("features"))
        if isinstance(item.get("featureId"), str)
    }
    design_ids = {
        str(item["designItemId"])
        for item in _mappings(model.get("designItems"))
        if isinstance(item.get("designItemId"), str)
    }
    obligations: list[dict[str, object]] = []
    for closure in _mappings(model.get("scopeClosure")):
        if closure.get("deliveryDisposition") != "STORY_AC_REQUIRED":
            continue
        input_id = closure.get("inputItemId")
        input_item = input_by_id.get(str(input_id))
        if input_item is None:
            continue
        feature_ids = list(_ids(closure.get("assignedFeatureIds")))
        design_refs = _unique(
            [
                *(
                    value
                    for value in _ids(closure.get("targetNodeIds"))
                    if value in design_ids
                ),
                *(
                    ref
                    for feature_id in feature_ids
                    for ref in _ids(feature_by_id.get(feature_id, {}).get("designRefs"))
                ),
            ]
        )
        obligation_id = f"story-obligation-requirement-{input_id}"
        obligations.append(
            {
                "obligationId": obligation_id,
                "kind": "REQUIREMENT",
                "subjectId": input_id,
                "assignedFeatureIds": feature_ids,
                "requirementRefs": [input_id],
                "designRefs": design_refs,
                "policyRefs": [],
                "coverageSet": _coverage_set(input_item, closure),
                "qualifiers": list(_ids(closure.get("preservedQualifiers"))),
                "crossFeatureRuleIds": list(
                    _ids(closure.get("crossFeatureRuleIds"))
                ),
                "crossFeatureTargetIds": list(
                    _ids(closure.get("crossFeatureTargetIds"))
                ),
                "sourceRefs": deepcopy(list(_mappings(closure.get("sourceRefs")))),
                "storyBoundaryKey": _story_boundary_key(closure),
                "affinityKey": "feature-affinity-"
                + sha256_bytes(canonical_json_bytes(feature_ids))[:16],
            }
        )
    for instance in _mappings(model.get("policyInstances")):
        instance_id = instance.get("policyInstanceId")
        if not isinstance(instance_id, str) or decisions.get(instance_id) != "INCLUDED":
            continue
        feature_ids = [
            value
            for value in _ids(instance.get("targetNodeIds"))
            if value in feature_by_id
        ]
        design_refs = _unique(
            [
                ref
                for feature_id in feature_ids
                for ref in _ids(feature_by_id.get(feature_id, {}).get("designRefs"))
            ]
        )
        obligations.append(
            {
                "obligationId": f"story-obligation-policy-{instance_id}",
                "kind": "DELIVERY_POLICY",
                "subjectId": instance_id,
                "assignedFeatureIds": feature_ids,
                "requirementRefs": [],
                "designRefs": design_refs,
                "policyRefs": [instance_id],
                "coverageSet": feature_ids,
                "qualifiers": [],
                "crossFeatureRuleIds": [],
                "crossFeatureTargetIds": [],
                "sourceRefs": deepcopy(list(_mappings(instance.get("sourceRefs")))),
                "storyBoundaryKey": f"story-boundary-policy-{instance_id}",
                "affinityKey": "feature-affinity-"
                + sha256_bytes(canonical_json_bytes(feature_ids))[:16],
            }
        )
    obligations.sort(key=lambda item: str(item["obligationId"]))
    routing = [
        {
            "obligationId": item["obligationId"],
            "kind": item["kind"],
            "assignedFeatureIds": item["assignedFeatureIds"],
            "storyBoundaryKey": item["storyBoundaryKey"],
            "affinityKey": item["affinityKey"],
        }
        for item in obligations
    ]
    projection_core = {
        "contract": "ai-sow-story-obligation-projection-v1",
        "algorithmVersion": "1",
        "effectivePolicyDecisions": decisions,
        "obligations": obligations,
        "obligationIds": [str(item["obligationId"]) for item in obligations],
        "routing": routing,
    }
    return {
        **projection_core,
        "projectionSha256": sha256_bytes(canonical_json_bytes(projection_core)),
    }


def _story_evidence(
    model: Mapping[str, object],
    obligations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    input_by_id = {
        str(item["inputItemId"]): item
        for item in _mappings(model.get("inputItems"))
        if isinstance(item.get("inputItemId"), str)
    }
    policy_by_id = {
        str(item["policyInstanceId"]): item
        for item in _mappings(model.get("policyInstances"))
        if isinstance(item.get("policyInstanceId"), str)
    }
    evidence: list[dict[str, object]] = []
    for obligation in obligations:
        subject_id = str(obligation["subjectId"])
        value = (
            input_by_id.get(subject_id)
            if obligation.get("kind") == "REQUIREMENT"
            else policy_by_id.get(subject_id)
        )
        if value is None:
            continue
        content = canonical_json_bytes(value).decode("utf-8")
        refs = _mappings(value.get("sourceRefs"))
        locator = (
            str(refs[0].get("locator"))
            if refs
            else f"policy-instance:{subject_id}"
        )
        evidence.append(
            {
                "evidenceId": str(obligation["obligationId"]),
                "locator": locator,
                "content": content,
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
        )
    return evidence


def _story_action_error(
    outcome: str,
    code: str,
    message: str,
    path: str,
) -> Mapping[str, object]:
    return {
        "outcome": outcome,
        "actionKind": "STORY_AC",
        "specs": [],
        "diagnostics": [
            {"code": code, "message": message, "path": path, "details": {}}
        ],
    }


def _story_spec(
    state: Mapping[str, object],
    projection: Mapping[str, object],
    obligations: Sequence[Mapping[str, object]],
    sequence: int,
) -> dict[str, object]:
    evidence = _story_evidence(state["baseCandidate"], obligations)
    obligation_ids = [str(item["obligationId"]) for item in obligations]
    return {
        "logicalShardId": f"story-ac-{sequence:03d}",
        "stage": "STORY_AC",
        "role": "AUTHOR",
        "promptId": "stage2-story-ac-v1",
        "promptPath": "prompts/stage2-story-ac.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/story-authoring.md",
            "references/acceptance-criteria.md",
            "references/delivery-decomposition.md",
            "references/delivery-lifecycle-policy.md",
        ],
        "evidenceCatalog": evidence,
        "packet": {
            "scopeClosureCheckpointSha256": sha256_bytes(
                canonical_json_bytes(state["scopeClosureCheckpoint"])
            ),
            "obligationProjectionSha256": projection["projectionSha256"],
            "effectivePolicyDecisionSha256": sha256_bytes(
                canonical_json_bytes(projection["effectivePolicyDecisions"])
            ),
            "assignedObligationIds": obligation_ids,
            "assignedObligations": deepcopy(list(obligations)),
            "assignedEvidenceIds": obligation_ids,
            "projectObligationRouting": deepcopy(list(projection["routing"])),
            "requiredCheckIds": list(STORY_AC_REQUIRED_CHECK_IDS),
            "allowedWriteCollections": sorted(STAGE_2_COLLECTIONS),
        },
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def prepare_action(
    state: Mapping[str, object],
    action_kind: str,
) -> Mapping[str, object]:
    if action_kind != "STORY_AC":
        return _story_action_error(
            "CONTRACT_UNSUPPORTED",
            "COMPILER_ACTION_KIND_UNSUPPORTED",
            "Delivery Compiler 只接受 STORY_AC action kind。",
            "/actionKind",
        )
    candidate = state.get("baseCandidate")
    checkpoint = state.get("scopeClosureCheckpoint")
    if not isinstance(candidate, Mapping) or not isinstance(checkpoint, Mapping):
        return _story_action_error(
            "CONTRACT_UNSUPPORTED",
            "STORY_AC_STATE_INVALID",
            "Story/AC action 缺少基础 candidate 或 ScopeClosureCheckpoint。",
            "/state",
        )
    checkpoint_state = {
        **state,
        "candidate": candidate,
        "upstreamCheckpointSha256s": list(
            checkpoint.get("upstreamCheckpointSha256s", [])
        ),
    }
    checkpoint_diagnostics = validate_scope_closure_checkpoint(
        checkpoint, checkpoint_state
    )
    stage_one_candidate = deepcopy(dict(candidate))
    for collection in (
        "stories",
        "acceptanceCriteria",
        "deliveryAnnotations",
        "tasks",
        "dependencies",
        "effectiveStartMatches",
        "estimationAnnotations",
    ):
        stage_one_candidate[collection] = []
    if checkpoint.get("candidateSha256") != sha256_bytes(
        canonical_json_bytes(stage_one_candidate)
    ):
        checkpoint_diagnostics = (
            *checkpoint_diagnostics,
            _diagnostic(
                "SCOPE_CHECKPOINT_BINDING_STALE",
                "ScopeClosureCheckpoint 不绑定当前 candidate 的精确 Stage 1 状态。",
                "/candidateSha256",
            ),
        )
    if checkpoint_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "actionKind": "STORY_AC",
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
    try:
        projection = derive_story_obligations(
            candidate, state.get("effectivePolicyDecisions")
        )
    except ValueError as error:
        return _story_action_error(
            "CONTRACT_UNSUPPORTED",
            "EFFECTIVE_POLICY_DECISION_INVALID",
            str(error),
            "/effectivePolicyDecisions",
        )
    token_budget = state.get("maxInitialPacketTokens")
    if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1:
        return _story_action_error(
            "CONTRACT_UNSUPPORTED",
            "STORY_AC_STATE_INVALID",
            "Story/AC 初始 packet token 预算无效。",
            "/maxInitialPacketTokens",
        )
    # Feature affinity, rather than source order or a fixed feature count, is the
    # batching seam. Greedy packing may place several affinity groups in one shard.
    affinity_groups: list[list[Mapping[str, object]]] = []
    by_affinity: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for obligation in projection["obligations"]:
        by_affinity[str(obligation["affinityKey"])].append(obligation)
    affinity_groups.extend(by_affinity[key] for key in sorted(by_affinity))
    batches: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    for group in affinity_groups:
        candidate_batch = [*current, *group]
        candidate_spec = _story_spec(
            state, projection, candidate_batch, len(batches) + 1
        )
        estimate = _story_token_estimate(
            {
                "logicalShardId": candidate_spec["logicalShardId"],
                "payload": candidate_spec["packet"],
                "evidenceCatalog": candidate_spec["evidenceCatalog"],
            }
        )
        if current and estimate > token_budget:
            batches.append(current)
            current = list(group)
        else:
            current = candidate_batch
    if current:
        batches.append(current)
    specs = [
        _story_spec(state, projection, batch, index)
        for index, batch in enumerate(batches, 1)
    ]
    estimates = [
        _story_token_estimate(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
        for spec in specs
    ]
    if len(specs) > 8 or any(value > token_budget for value in estimates):
        return _story_action_error(
            "CONTRACT_UNSUPPORTED",
            "STORY_AC_CAPACITY_EXCEEDED",
            "Story/AC obligations 无法在安全上下文预算和八个 shard 内完整分配。",
            "/baseCandidate/scopeClosure",
        )
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "STORY_AC",
        "obligationProjection": projection,
        "obligationProjectionSha256": projection["projectionSha256"],
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": [],
    }


def story_join_required(prepared: Mapping[str, object]) -> bool:
    """Return whether the frozen Story action group needs a sibling join."""
    return len(_mappings(prepared.get("specs"))) > 1


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


def _validate_story_record(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    record: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    specs = {
        str(spec["logicalShardId"]): spec
        for spec in _mappings(prepared.get("specs"))
    }
    spec = specs.get(str(record.get("logicalShardId")))
    if spec is None:
        diagnostics.append(
            _diagnostic(
                "STORY_AC_SHARD_UNKNOWN",
                "Story/AC record 不属于当前冻结 action group。",
                "/logicalShardId",
            )
        )
        return _sort_diagnostics(diagnostics)
    expected_bindings = {
        "runId": state.get("runId"),
        "packetSha256": _packet_sha256(spec),
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(state.get("inputRevision"))
        ),
        "baseCandidateSha256": state.get("baseCandidateSha256"),
        "modelProfileId": state.get("modelProfileId"),
        "modelConfigSha256": state.get("modelConfigSha256"),
    }
    for field, expected in expected_bindings.items():
        if record.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "STORY_AC_RECORD_BINDING_MISMATCH",
                    "Story/AC record 与冻结 candidate、packet 或模型配置不匹配。",
                    f"/{field}",
                )
            )
    submission = record.get("submission")
    if record.get("status") != "SUCCESS" or not isinstance(submission, Mapping):
        diagnostics.append(
            _diagnostic(
                "STORY_AC_RECORD_NOT_SUCCESSFUL",
                "Story/AC 只接受成功 ActionRecord。",
                "/status",
            )
        )
        return _sort_diagnostics(diagnostics)
    if submission.get("resultKind") != "PATCH":
        diagnostics.append(
            _diagnostic(
                "STORY_AC_RESULT_KIND_INVALID",
                "Story/AC action 必须返回 PATCH。",
                "/submission/resultKind",
            )
        )
    if record.get("submissionSha256") != sha256_bytes(
        canonical_json_bytes(submission)
    ):
        diagnostics.append(
            _diagnostic(
                "STORY_AC_SUBMISSION_HASH_MISMATCH",
                "Story/AC submission hash 与内容不匹配。",
                "/submissionSha256",
            )
        )
    packet = spec["packet"]
    if submission.get("reviewedEvidenceIds") != packet["assignedEvidenceIds"]:
        diagnostics.append(
            _diagnostic(
                "STORY_AC_EVIDENCE_MISMATCH",
                "Story/AC 必须复核当前 shard 的全部义务证据。",
                "/submission/reviewedEvidenceIds",
            )
        )
    self_check = submission.get("selfCheck")
    if not isinstance(self_check, Mapping) or self_check.get(
        "completedCheckIds"
    ) != list(STORY_AC_REQUIRED_CHECK_IDS):
        diagnostics.append(
            _diagnostic(
                "STORY_AC_SELF_CHECK_INCOMPLETE",
                "Story/AC 必须完成全部冻结检查项。",
                "/submission/selfCheck/completedCheckIds",
            )
        )
    replacement = submission.get("replacementSet")
    if not isinstance(replacement, Mapping):
        return _sort_diagnostics(diagnostics)
    for position, wrapper in enumerate(_mappings(replacement.get("upserts"))):
        if wrapper.get("collection") not in STAGE_2_COLLECTIONS:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Story/AC action 只能写 stories、acceptanceCriteria、deliveryAnnotations。",
                    f"/submission/replacementSet/upserts/{position}",
                )
            )
    for key in [
        *(
            replacement.get("expectedNodeHashes", {}).keys()
            if isinstance(replacement.get("expectedNodeHashes"), Mapping)
            else []
        ),
        *(
            replacement.get("deletes", [])
            if isinstance(replacement.get("deletes"), list)
            else []
        ),
    ]:
        if str(key).split(":", 1)[0] not in STAGE_2_COLLECTIONS:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Story/AC action 不得修改其他 Owner 的区域。",
                    "/submission/replacementSet",
                )
            )
    return _sort_diagnostics(diagnostics)


def accept_result(
    state: Mapping[str, object],
    record: Mapping[str, object],
) -> CompilerProgress:
    prepared = prepare_action(state, "STORY_AC")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return CompilerProgress(
            "FAILED",
            (),
            (
                _diagnostic(
                    "STORY_AC_PREPARE_FAILED",
                    "Story/AC action 未成功冻结。",
                    "/state",
                ),
            ),
        )
    diagnostics = _validate_story_record(state, prepared, record)
    if diagnostics:
        return CompilerProgress("FAILED", (), diagnostics)
    accepted = [
        item
        for item in state.get("acceptedRecords", [])
        if isinstance(item, Mapping)
    ]
    completed = {
        str(item.get("logicalShardId"))
        for item in [*accepted, record]
        if item.get("status") == "SUCCESS"
    }
    required = [
        str(spec["logicalShardId"])
        for spec in _mappings(prepared.get("specs"))
    ]
    pending = tuple(item for item in required if item not in completed)
    return CompilerProgress(
        "ACTION_REQUIRED" if pending else "CHECKPOINT_READY",
        pending,
        (),
    )


def _obligation_coverage_diagnostics(
    model: Mapping[str, object],
    projection: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    stories = _mappings(model.get("stories"))
    criteria = _mappings(model.get("acceptanceCriteria"))
    criteria_by_story: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for criterion in criteria:
        criteria_by_story[str(criterion.get("storyId"))].append(criterion)
    boundary_keys_by_story: defaultdict[str, set[str]] = defaultdict(set)
    allowed_design_by_story: defaultdict[str, set[str]] = defaultdict(set)
    for obligation in _mappings(projection.get("obligations")):
        subject_id = str(obligation.get("subjectId"))
        requirement_refs = set(_ids(obligation.get("requirementRefs")))
        policy_refs = set(_ids(obligation.get("policyRefs")))
        assigned_features = set(_ids(obligation.get("assignedFeatureIds")))
        required_coverage = set(_ids(obligation.get("coverageSet")))
        matching_stories = [
            story
            for story in stories
            if story.get("featureId") in assigned_features
            and requirement_refs.issubset(set(_ids(story.get("requirementRefs"))))
            and policy_refs.issubset(set(_ids(story.get("policyRefs"))))
            and required_coverage.issubset(set(_ids(story.get("coverageSet"))))
            and (
                bool(requirement_refs)
                or bool(policy_refs)
            )
        ]
        closed = False
        for story in matching_stories:
            story_id = str(story.get("storyId"))
            matching_criteria = [
                criterion
                for criterion in criteria_by_story[story_id]
                if requirement_refs.issubset(
                    set(_ids(criterion.get("requirementRefs")))
                )
                and policy_refs.issubset(set(_ids(criterion.get("policyRefs"))))
                and required_coverage.issubset(
                    set(_ids(criterion.get("coverageSet")))
                )
            ]
            combined_text = "\n".join(
                str(item.get("text", "")) for item in matching_criteria
            )
            if matching_criteria and all(
                qualifier in combined_text
                for qualifier in _ids(obligation.get("qualifiers"))
            ):
                closed = True
                boundary_keys_by_story[story_id].add(
                    str(obligation.get("storyBoundaryKey"))
                )
                allowed_design_by_story[story_id].update(
                    _ids(obligation.get("designRefs"))
                )
        if not closed:
            diagnostics.append(
                _diagnostic(
                    "STORY_OBLIGATION_UNCLOSED",
                    "Story/AC 未关闭确定性派生的义务及其限定词。",
                    f"/obligations/{obligation.get('obligationId')}",
                )
            )
    for story_id, boundary_keys in boundary_keys_by_story.items():
        non_policy = {
            key for key in boundary_keys if not key.startswith("story-boundary-policy-")
        }
        if len(non_policy) > 1:
            diagnostics.append(
                _diagnostic(
                    "INDEPENDENT_STORY_BOUNDARIES_MERGED",
                    "独立责任、验收或发布边界不得合并为同一 Story。",
                    f"/stories/{story_id}",
                )
            )
    for story in stories:
        story_id = str(story.get("storyId"))
        if story_id not in allowed_design_by_story:
            continue
        allowed = allowed_design_by_story[story_id]
        referenced = set(_ids(story.get("designRefs")))
        referenced.update(
            ref
            for criterion in criteria_by_story[story_id]
            for ref in _ids(criterion.get("designRefs"))
        )
        for design_id in sorted(referenced - allowed):
            diagnostics.append(
                _diagnostic(
                    "STORY_DESIGN_REF_NOT_AUTHORIZED",
                    "Story/AC 只能引用 obligation 投影允许的批准设计。",
                    f"/stories/{story_id}/designRefs/{design_id}",
                )
            )
    return _sort_diagnostics(diagnostics)


def apply_ready_group(
    state: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> CompilerResult:
    base_candidate = state.get("baseCandidate")
    if not isinstance(base_candidate, Mapping):
        diagnostic = _diagnostic(
            "STORY_AC_STATE_INVALID",
            "Story/AC 缺少基础 candidate。",
            "/baseCandidate",
        )
        return CompilerResult({}, "", {}, (diagnostic,))
    prepared = prepare_action(state, "STORY_AC")
    specs = _mappings(prepared.get("specs"))
    required = [str(spec["logicalShardId"]) for spec in specs]
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for record in records:
        shard_id = str(record.get("logicalShardId"))
        duplicate = duplicate or shard_id in by_shard
        by_shard[shard_id] = record
    if (
        prepared.get("outcome") != "ACTION_REQUIRED"
        or duplicate
        or set(by_shard) != set(required)
    ):
        diagnostic = _diagnostic(
            "STORY_AC_GROUP_INCOMPLETE",
            "Story/AC group 必须包含每个冻结 shard 的一条成功 record。",
            "/records",
        )
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            (diagnostic,),
        )
    diagnostics = tuple(
        diagnostic
        for shard_id in required
        for diagnostic in _validate_story_record(
            state, prepared, by_shard[shard_id]
        )
    )
    if diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    combined = {
        "expectedNodeHashes": {},
        "upserts": [],
        "deletes": [],
    }
    for shard_id in required:
        replacement = by_shard[shard_id]["submission"]["replacementSet"]
        for key, value in replacement["expectedNodeHashes"].items():
            if key in combined["expectedNodeHashes"]:
                diagnostics += (
                    _diagnostic(
                        "STORY_AC_REPLACEMENT_OVERLAP",
                        "不同 Story/AC shard 不得修改同一既有节点。",
                        f"/records/{shard_id}/expectedNodeHashes/{key}",
                    ),
                )
            combined["expectedNodeHashes"][key] = value
        combined["upserts"].extend(replacement["upserts"])
        combined["deletes"].extend(replacement["deletes"])
    if diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    outcome = apply_replacement(
        base_candidate, combined, owner_stage="STAGE_2"
    )
    if outcome.diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            outcome.diagnostics,
        )
    model_diagnostics = validate_sow_model(
        outcome.candidate, "STAGE_2", registry=NEXT_SCHEMA_REGISTRY
    )
    coverage_diagnostics = _obligation_coverage_diagnostics(
        outcome.candidate, prepared["obligationProjection"]
    )
    all_diagnostics = _sort_diagnostics(
        [*model_diagnostics, *coverage_diagnostics]
    )
    if all_diagnostics:
        return CompilerResult(
            outcome.candidate,
            outcome.candidate_sha256,
            {},
            all_diagnostics,
        )
    checkpoint = {
        "kind": "STORY_AC_CANDIDATE",
        "obligationProjectionSha256": prepared[
            "obligationProjectionSha256"
        ],
        "obligationCounts": {
            "required": len(prepared["obligationProjection"]["obligations"]),
            "closed": len(prepared["obligationProjection"]["obligations"]),
        },
        "outstandingIds": [],
        "recordSha256s": [
            sha256_bytes(canonical_json_bytes(by_shard[shard_id]))
            for shard_id in required
        ],
    }
    return CompilerResult(
        outcome.candidate,
        outcome.candidate_sha256,
        checkpoint,
        (),
    )


def _story_owner_projection(model: Mapping[str, object]) -> dict[str, object]:
    return {
        collection: deepcopy(list(_mappings(model.get(collection))))
        for collection in (
            "stories",
            "acceptanceCriteria",
            "deliveryAnnotations",
        )
    }


def _story_coverage_sha256(
    model: Mapping[str, object],
    projection: Mapping[str, object],
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "obligationIds": projection.get("obligationIds", []),
                "routing": projection.get("routing", []),
                "stories": [
                    {
                        "storyId": item.get("storyId"),
                        "featureId": item.get("featureId"),
                        "coverageSet": item.get("coverageSet"),
                        "requirementRefs": item.get("requirementRefs"),
                        "designRefs": item.get("designRefs"),
                        "policyRefs": item.get("policyRefs"),
                    }
                    for item in _mappings(model.get("stories"))
                ],
                "acceptanceCriteria": [
                    {
                        "acceptanceCriterionId": item.get(
                            "acceptanceCriterionId"
                        ),
                        "storyId": item.get("storyId"),
                        "text": item.get("text"),
                        "coverageSet": item.get("coverageSet"),
                        "requirementRefs": item.get("requirementRefs"),
                        "designRefs": item.get("designRefs"),
                        "policyRefs": item.get("policyRefs"),
                    }
                    for item in _mappings(model.get("acceptanceCriteria"))
                ],
            }
        )
    )


def _story_action_record_hashes(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
) -> tuple[list[str], tuple[Diagnostic, ...]]:
    records = _mappings(state.get("storyActionRecords"))
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for record in records:
        shard_id = str(record.get("logicalShardId"))
        duplicate = duplicate or shard_id in by_shard
        by_shard[shard_id] = record
    required = [
        str(spec["logicalShardId"])
        for spec in _mappings(prepared.get("specs"))
    ]
    if duplicate or set(by_shard) != set(required):
        return [], (
            _diagnostic(
                "STORY_AC_ACTION_PROOF_INCOMPLETE",
                "STORY_AC checkpoint 必须绑定全部且仅绑定冻结的 Story action records。",
                "/storyActionRecords",
            ),
        )
    diagnostics = tuple(
        diagnostic
        for shard_id in required
        for diagnostic in _validate_story_record(
            state, prepared, by_shard[shard_id]
        )
    )
    return [
        sha256_bytes(canonical_json_bytes(by_shard[shard_id]))
        for shard_id in required
    ], _sort_diagnostics(diagnostics)


def _story_review_result_hashes(state: Mapping[str, object]) -> list[str]:
    results = sorted(
        _mappings(state.get("storyReviewResults")),
        key=lambda item: str(item.get("logicalShardId", "")),
    )
    return [
        sha256_bytes(
            canonical_json_bytes(
                item.get("result")
                if isinstance(item.get("result"), Mapping)
                else item
            )
        )
        for item in results
    ]


def _story_checkpoint_material(
    state: Mapping[str, object],
) -> tuple[dict[str, object], tuple[Diagnostic, ...]]:
    candidate = state.get("candidate")
    base_candidate = state.get("baseCandidate")
    scope_checkpoint = state.get("scopeClosureCheckpoint")
    if not (
        isinstance(candidate, Mapping)
        and isinstance(base_candidate, Mapping)
        and isinstance(scope_checkpoint, Mapping)
    ):
        return {}, (
            _diagnostic(
                "STORY_AC_CHECKPOINT_STATE_INVALID",
                "STORY_AC checkpoint 缺少 candidate、Stage 1 candidate 或 Scope checkpoint。",
                "/state",
            ),
        )
    prepared = prepare_action(state, "STORY_AC")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        diagnostics = tuple(
            _diagnostic(
                str(item.get("code")),
                str(item.get("message")),
                str(item.get("path", "")),
            )
            for item in _mappings(prepared.get("diagnostics"))
        )
        return {}, diagnostics or (
            _diagnostic(
                "STORY_AC_PREPARE_FAILED",
                "无法重放 Story/AC action group。",
                "/state",
            ),
        )
    action_hashes, action_diagnostics = _story_action_record_hashes(
        state, prepared
    )
    diagnostics: list[Diagnostic] = list(action_diagnostics)
    diagnostics.extend(
        validate_sow_model(
            candidate, "STAGE_2", registry=NEXT_SCHEMA_REGISTRY
        )
    )
    diagnostics.extend(
        _obligation_coverage_diagnostics(
            candidate, prepared["obligationProjection"]
        )
    )
    if not action_diagnostics:
        joined = apply_ready_group(state, _mappings(state.get("storyActionRecords")))
        diagnostics.extend(joined.diagnostics)
        if (
            not joined.diagnostics
            and canonical_json_bytes(_story_owner_projection(joined.model))
            != canonical_json_bytes(_story_owner_projection(candidate))
        ):
            diagnostics.append(
                _diagnostic(
                    "STORY_AC_CANDIDATE_RECORD_MISMATCH",
                    "当前 Story/AC candidate 不是冻结 sibling records 一次性 Join 的结果。",
                    "/candidate",
                )
            )
    decisions = prepared["obligationProjection"]["effectivePolicyDecisions"]
    scope_checkpoint_sha256 = sha256_bytes(
        canonical_json_bytes(scope_checkpoint)
    )
    upstream = [scope_checkpoint_sha256]
    if state.get("upstreamCheckpointSha256s", upstream) != upstream:
        diagnostics.append(
            _diagnostic(
                "STORY_AC_UPSTREAM_CHECKPOINT_MISMATCH",
                "STORY_AC checkpoint 的唯一直接上游必须是当前 Scope checkpoint。",
                "/upstreamCheckpointSha256s",
            )
        )
    material = {
        "sourceManifestSha256": scope_checkpoint.get(
            "sourceManifestSha256"
        ),
        "ownerProjectionSha256": sha256_bytes(
            canonical_json_bytes(_story_owner_projection(candidate))
        ),
        "coverageSha256": _story_coverage_sha256(
            candidate, prepared["obligationProjection"]
        ),
        "policyDefinitionSha256": scope_checkpoint.get(
            "policyDefinitionSha256"
        ),
        "actionRecordSha256s": action_hashes,
        "reviewResultSha256s": _story_review_result_hashes(state),
        "upstreamCheckpointSha256s": upstream,
        "effectivePolicyDecisionSha256": sha256_bytes(
            canonical_json_bytes(decisions)
        ),
        "obligationProjectionSha256": prepared[
            "obligationProjectionSha256"
        ],
        "obligationCounts": {
            "required": len(prepared["obligationProjection"]["obligations"]),
            "closed": (
                len(prepared["obligationProjection"]["obligations"])
                if not any(
                    item.code == "STORY_OBLIGATION_UNCLOSED"
                    for item in diagnostics
                )
                else 0
            ),
        },
        "outstandingIds": [
            str(item["obligationId"])
            for item in prepared["obligationProjection"]["obligations"]
            if any(
                diagnostic.code == "STORY_OBLIGATION_UNCLOSED"
                and diagnostic.path.endswith(str(item["obligationId"]))
                for diagnostic in diagnostics
            )
        ],
    }
    material["obligationCounts"]["closed"] = (
        material["obligationCounts"]["required"]
        - len(material["outstandingIds"])
    )
    return material, _sort_diagnostics(diagnostics)


def build_story_ac_checkpoint(
    state: Mapping[str, object],
) -> Mapping[str, object]:
    material, diagnostics = _story_checkpoint_material(state)
    if diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "checkpoint": None,
            "diagnostics": diagnostics,
        }
    candidate = state["candidate"]
    checkpoint = {
        "contract": "ai-sow-stage-checkpoint-v1",
        "kind": "STORY_AC",
        "runId": state["runId"],
        "stage": "STORY_AC",
        "candidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        **material,
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(STORY_AC_CHECKPOINT_CHECK_IDS),
        "decision": "PASS",
    }
    contract_diagnostics = validate_contract(
        checkpoint,
        "stage-checkpoint.schema.json",
        NEXT_SCHEMA_REGISTRY,
    )
    if contract_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "checkpoint": None,
            "diagnostics": contract_diagnostics,
        }
    return {
        "outcome": "READY_FOR_TASK",
        "checkpoint": checkpoint,
        "checkpointSha256": sha256_bytes(canonical_json_bytes(checkpoint)),
        "diagnostics": (),
    }


def validate_story_ac_checkpoint(
    checkpoint: Mapping[str, object],
    state: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(
            checkpoint,
            "stage-checkpoint.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
    )
    material, material_diagnostics = _story_checkpoint_material(state)
    diagnostics.extend(material_diagnostics)
    expected = {
        "runId": state.get("runId"),
        **material,
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(STORY_AC_CHECKPOINT_CHECK_IDS),
    }
    for field, value in expected.items():
        if checkpoint.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "STORY_AC_CHECKPOINT_BINDING_STALE",
                    "STORY_AC checkpoint 不再绑定当前 Stage 2 投影或证明闭包。",
                    f"/{field}",
                )
            )
    return _sort_diagnostics(diagnostics)
