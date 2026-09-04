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
from delivery_compiler import _story_owner_projection
from models import Diagnostic
from sow_model import (
    NODE_COLLECTIONS,
    TOP_LEVEL_WRITE_OWNER,
    derive_impact_graph,
    owner_projection_sha256,
)
from task_compiler import _task_owner_projection


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
R1_SOURCE_CHECK_IDS = (
    "SOURCE_BLOCK_COVERAGE",
    "SOURCE_ATOMICITY",
    "QUALIFIER_PRESERVATION",
    "SOURCE_CONFLICT",
)
R1_SCOPE_CHECK_IDS = (
    "SOURCE_TO_INPUT",
    "SCOPE_CLOSURE",
    "TECHNICAL_CLASSIFICATION",
    "EPIC_FEATURE_BOUNDARY",
    "DESIGN_SUFFICIENCY",
    "SCOPE_EXPANSION",
    "DELIVERY_POLICY",
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _r1_instruction_binding(relative_path: str) -> dict[str, str]:
    path = SKILL_ROOT / relative_path
    return {"path": relative_path, "sha256": sha256_bytes(path.read_bytes())}


def _r1_estimated_tokens(value: object) -> int:
    return max(1, (len(canonical_json_bytes(value)) + 3) // 4)


def _r1_source_material(
    state: Mapping[str, object],
) -> tuple[
    Mapping[str, object],
    Mapping[str, str],
    list[Mapping[str, object]],
    list[str],
    list[dict[str, object]],
]:
    input_revision = state.get("inputRevision")
    source_contents = state.get("sourceContents")
    if not isinstance(input_revision, Mapping) or not isinstance(
        source_contents, Mapping
    ):
        raise ValueError("R1 source state 无效")
    if validate_contract(
        input_revision,
        "input-revision.schema.json",
        NEXT_SCHEMA_REGISTRY,
    ):
        raise ValueError("R1 input revision 无效")
    if not all(
        isinstance(block_id, str) and isinstance(content, str)
        for block_id, content in source_contents.items()
    ):
        raise ValueError("R1 source contents 无效")
    blocks = _mappings(input_revision.get("blocks"))
    source_roles = {
        str(source["sourceId"]): str(source["role"])
        for source in _mappings(input_revision.get("sources"))
    }
    roots: list[str] = []
    for block in blocks:
        if block.get("extractionDisposition") == "DROPPED":
            continue
        root_id = block.get("primaryCoverageBlockId")
        if not isinstance(root_id, str):
            raise ValueError("R1 coverage root 无效")
        if root_id not in roots:
            roots.append(root_id)
    block_by_id = {
        str(block["blockId"]): block
        for block in blocks
        if isinstance(block.get("blockId"), str)
    }
    normalized_contents = {
        str(block_id): str(content) for block_id, content in source_contents.items()
    }
    for root_id in roots:
        block = block_by_id.get(root_id)
        content = normalized_contents.get(root_id)
        if (
            block is None
            or content is None
            or sha256_bytes(content.encode("utf-8")) != block.get("contentSha256")
        ):
            raise ValueError("R1 coverage root 内容绑定无效")
    inventory = [
        {
            "blockId": block.get("blockId"),
            "sourceId": block.get("sourceId"),
            "sourceRole": source_roles.get(str(block.get("sourceId"))),
            "primaryCoverageBlockId": block.get("primaryCoverageBlockId"),
            "contextBlockIds": list(block.get("contextBlockIds", [])),
            "structuralParentId": block.get("structuralParentId"),
            "extractionDisposition": block.get("extractionDisposition"),
            "locator": block.get("locator"),
        }
        for block in blocks
    ]
    return input_revision, normalized_contents, blocks, roots, inventory


def _r1_source_projection_sha256(input_revision: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "sources": input_revision.get("sources", []),
                "blocks": input_revision.get("blocks", []),
            }
        )
    )


def _r1_source_spec(
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
    source_contents: Mapping[str, str],
    blocks: Sequence[Mapping[str, object]],
    roots: Sequence[str],
    inventory: Sequence[Mapping[str, object]],
    assigned: Sequence[str],
    sequence: int,
    review_plan_sha256: str,
) -> dict[str, object]:
    block_by_id = {str(block["blockId"]): block for block in blocks}
    logical_shard_id = f"r1-source-audit-{sequence:03d}"
    candidate_projection_sha256 = _r1_source_projection_sha256(input_revision)
    coverage_sha256 = sha256_bytes(
        canonical_json_bytes({"coverageRootIds": list(assigned)})
    )
    packet = {
        "contract": "ai-sow-r1-source-audit-packet-v1",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "reviewPlanSha256": review_plan_sha256,
        "candidateProjectionSha256": candidate_projection_sha256,
        "coverageSha256": coverage_sha256,
        "coverageRootIds": list(assigned),
        "allCoverageRootIds": list(roots),
        "fullBlockInventory": [dict(item) for item in inventory],
        "requiredCheckIds": list(R1_SOURCE_CHECK_IDS),
        "authorPatchVisible": False,
        "instructionBindings": [
            _r1_instruction_binding("prompts/fragments/roles/reviewer.md"),
            _r1_instruction_binding("prompts/fragments/outputs/reviewer-result.md"),
            _r1_instruction_binding("prompts/review-source-audit.md"),
            _r1_instruction_binding("references/source-authority.md"),
        ],
    }
    evidence = [
        {
            "evidenceId": root_id,
            "locator": block_by_id[root_id]["locator"],
            "content": source_contents[root_id],
            "sha256": block_by_id[root_id]["contentSha256"],
        }
        for root_id in assigned
    ]
    return {
        "logicalShardId": logical_shard_id,
        "stage": "SOURCE_AUDIT",
        "role": "REVIEWER",
        "promptId": "review-source-audit-v1",
        "promptPath": "prompts/review-source-audit.md",
        "resultPayloadSchema": "contracts/review-repair.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/reviewer.md",
            "prompts/fragments/outputs/reviewer-result.md",
            "references/source-authority.md",
        ],
        "packet": packet,
        "evidenceCatalog": evidence,
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def prepare_r1_source_audit(state: Mapping[str, object]) -> Mapping[str, object]:
    try:
        input_revision, source_contents, blocks, roots, inventory = (
            _r1_source_material(state)
        )
    except (KeyError, TypeError, ValueError):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SOURCE_STATE_INVALID",
                    "R1 Source Audit 输入 revision 或原文绑定无效。",
                    "/state",
                ),
            ),
        }
    budget = state.get("maxInitialPacketTokens")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SOURCE_STATE_INVALID",
                    "R1 Source Audit 初始 packet token 预算无效。",
                    "/maxInitialPacketTokens",
                ),
            ),
        }
    global_material = {
        "coverageRootIds": roots,
        "fullBlockInventory": inventory,
    }
    if _r1_estimated_tokens(global_material) >= budget:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
                    "R1 最小 source inventory 超过安全上下文预算。",
                    "/inputRevision/blocks",
                ),
            ),
        }
    shard_roots: list[list[str]] = []
    current: list[str] = []
    for root_id in roots:
        candidate = [*current, root_id]
        provisional = _r1_source_spec(
            state,
            input_revision,
            source_contents,
            blocks,
            roots,
            inventory,
            candidate,
            len(shard_roots) + 1,
            "0" * 64,
        )
        measured = _r1_estimated_tokens(
            {
                "payload": provisional["packet"],
                "evidenceCatalog": provisional["evidenceCatalog"],
            }
        )
        if current and (measured > budget or len(candidate) > 3):
            shard_roots.append(current)
            current = [root_id]
        else:
            current = candidate
    if current:
        shard_roots.append(current)
    candidate_projection_sha256 = _r1_source_projection_sha256(input_revision)
    review_plan = {
        "contract": "ai-sow-review-plan-v1",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "candidateSha256": candidate_projection_sha256,
        "mode": "FULL",
        "shards": [
            {
                "reviewShardId": f"r1-source-audit-{index:03d}",
                "kind": "SOURCE_AUDIT",
                "logicalThemeId": "r1-source",
                "physicalShardIndex": index - 1,
                "subjectIds": list(assigned),
            }
            for index, assigned in enumerate(shard_roots, 1)
        ],
    }
    plan_diagnostics = validate_contract(
        review_plan,
        "review-repair.schema.json",
        NEXT_SCHEMA_REGISTRY,
    )
    if plan_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": plan_diagnostics,
        }
    review_plan_sha256 = sha256_bytes(canonical_json_bytes(review_plan))
    specs = [
        _r1_source_spec(
            state,
            input_revision,
            source_contents,
            blocks,
            roots,
            inventory,
            assigned,
            index,
            review_plan_sha256,
        )
        for index, assigned in enumerate(shard_roots, 1)
    ]
    estimates = [
        _r1_estimated_tokens(
            {"payload": spec["packet"], "evidenceCatalog": spec["evidenceCatalog"]}
        )
        for spec in specs
    ]
    if len(specs) > 8 or any(value > budget for value in estimates):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
                    "R1 Source Audit 无法在物理 shard 上限内容纳全量 inventory。",
                    "/inputRevision/blocks",
                ),
            ),
        }
    return {
        "outcome": "ACTION_REQUIRED",
        "reviewPlan": review_plan,
        "reviewPlanSha256": review_plan_sha256,
        "sourceProjectionSha256": candidate_projection_sha256,
        "coverageRootIds": list(roots),
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": (),
    }


def validate_r1_source_audit_result(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    logical_shard_id: str,
    result: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(
            result,
            "review-repair.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
    )
    spec = next(
        (
            item
            for item in _mappings(prepared.get("specs"))
            if item.get("logicalShardId") == logical_shard_id
        ),
        None,
    )
    if spec is None:
        diagnostics.append(
            _diagnostic(
                "R1_SOURCE_SHARD_UNKNOWN",
                "R1 Source Audit result 不属于当前 review plan。",
                "/logicalShardId",
            )
        )
        return _sort(diagnostics)
    packet = spec["packet"]
    expected = {
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "SOURCE_AUDIT",
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared["sourceProjectionSha256"],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(R1_SOURCE_CHECK_IDS),
        "sourceAuditCoverageUnion": list(packet["coverageRootIds"]),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "R1_SOURCE_RESULT_BINDING_MISMATCH",
                    "R1 Source Audit result 未绑定当前计划、投影、覆盖或检查项。",
                    f"/{field}",
                )
            )
    findings = _mappings(result.get("findings"))
    _normalized_findings, finding_diagnostics = _normalize_findings(findings)
    diagnostics.extend(finding_diagnostics)
    decision = result.get("decision")
    if (decision == "PASS" and findings) or (decision != "PASS" and not findings):
        diagnostics.append(
            _diagnostic(
                "R1_REVIEW_DECISION_INCONSISTENT",
                "R1 PASS 必须为空 findings，非 PASS 必须包含 finding。",
                "/findings",
            )
        )
    allowed_evidence = set(packet["coverageRootIds"])
    for index, finding in enumerate(findings):
        if not set(finding.get("evidenceIds", [])) <= allowed_evidence:
            diagnostics.append(
                _diagnostic(
                    "R1_FINDING_EVIDENCE_UNREACHABLE",
                    "R1 finding 只能引用当前 shard 可达的原始 evidence。",
                    f"/findings/{index}/evidenceIds",
                )
            )
    return _sort(diagnostics)


def _validated_r1_audit_group(
    state: Mapping[str, object],
) -> tuple[Mapping[str, object], list[tuple[str, Mapping[str, object]]], tuple[Diagnostic, ...]]:
    audit_state = {
        **state,
        "maxInitialPacketTokens": state.get(
            "auditMaxInitialPacketTokens",
            state.get("maxInitialPacketTokens"),
        ),
    }
    prepared = prepare_r1_source_audit(audit_state)
    wrappers = _mappings(state.get("sourceAuditResults"))
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for wrapper in wrappers:
        shard_id = wrapper.get("logicalShardId")
        result = wrapper.get("result")
        if not isinstance(shard_id, str) or not isinstance(result, Mapping):
            continue
        duplicate = duplicate or shard_id in by_shard
        by_shard[shard_id] = result
    required = sorted(
        str(spec["logicalShardId"])
        for spec in _mappings(prepared.get("specs"))
    )
    if (
        prepared.get("outcome") != "ACTION_REQUIRED"
        or duplicate
        or set(by_shard) != set(required)
    ):
        return (
            prepared,
            [],
            (
                _diagnostic(
                    "R1_SOURCE_RESULT_GROUP_INCOMPLETE",
                    "R1 Scope Join 需要每个 Source Audit shard 的唯一 result。",
                    "/sourceAuditResults",
                ),
            ),
        )
    ordered = [(shard_id, by_shard[shard_id]) for shard_id in required]
    diagnostics = tuple(
        diagnostic
        for shard_id, result in ordered
        for diagnostic in validate_r1_source_audit_result(
            audit_state,
            prepared,
            shard_id,
            result,
        )
    )
    return prepared, ordered, _sort(diagnostics)


def prepare_r1_scope_join(state: Mapping[str, object]) -> Mapping[str, object]:
    input_revision = state.get("inputRevision")
    candidate = state.get("scopeCandidate")
    if not isinstance(input_revision, Mapping) or not isinstance(candidate, Mapping):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SCOPE_STATE_INVALID",
                    "R1 Scope Join 缺少 Input Revision 或 Stage 1 candidate。",
                    "/state",
                ),
            ),
        }
    if validate_contract(
        candidate,
        "sow-model.schema.json",
        NEXT_SCHEMA_REGISTRY,
    ):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SCOPE_STATE_INVALID",
                    "R1 Scope Join candidate 合同无效。",
                    "/scopeCandidate",
                ),
            ),
        }
    audit_prepared, ordered, audit_diagnostics = _validated_r1_audit_group(state)
    if audit_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": audit_diagnostics,
        }
    if any(result.get("decision") != "PASS" for _, result in ordered):
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SOURCE_AUDIT_NOT_PASSING",
                    "存在未通过的 R1 Source Audit，Scope Join 不得继续。",
                    "/sourceAuditResults",
                ),
            ),
        }
    budget = state.get("maxInitialPacketTokens")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "R1_SCOPE_STATE_INVALID",
                    "R1 Scope Join 初始 packet token 预算无效。",
                    "/maxInitialPacketTokens",
                ),
            ),
        }
    candidate_projection_sha256 = owner_projection_sha256(candidate, "STAGE_1")
    ordered_hashes = [
        {
            "logicalShardId": shard_id,
            "reviewResultSha256": sha256_bytes(canonical_json_bytes(result)),
        }
        for shard_id, result in ordered
    ]
    coverage_roots = list(audit_prepared["coverageRootIds"])
    coverage_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "coverageRootIds": coverage_roots,
                "orderedAuditResultHashes": ordered_hashes,
                "candidateProjectionSha256": candidate_projection_sha256,
            }
        )
    )
    packet = {
        "contract": "ai-sow-r1-scope-join-packet-v1",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "reviewPlanSha256": audit_prepared["reviewPlanSha256"],
        "candidateProjectionSha256": candidate_projection_sha256,
        "coverageSha256": coverage_sha256,
        "coverageRootIds": coverage_roots,
        "orderedAuditResultHashes": ordered_hashes,
        "sourceAuditResults": [deepcopy(dict(result)) for _, result in ordered],
        "scopeCandidate": deepcopy(dict(candidate)),
        "inputCounts": {
            "coverageRoots": len(coverage_roots),
            "inputItems": len(_mappings(candidate.get("inputItems"))),
            "scopeClosure": len(_mappings(candidate.get("scopeClosure"))),
            "epics": len(_mappings(candidate.get("epics"))),
            "features": len(_mappings(candidate.get("features"))),
            "integrations": len(_mappings(candidate.get("integrations"))),
            "nfrs": len(_mappings(candidate.get("nfrs"))),
        },
        "requiredCheckIds": list(R1_SCOPE_CHECK_IDS),
        "instructionBindings": [
            _r1_instruction_binding("prompts/fragments/roles/reviewer.md"),
            _r1_instruction_binding("prompts/fragments/outputs/reviewer-result.md"),
            _r1_instruction_binding("prompts/review-source-scope.md"),
            _r1_instruction_binding("references/source-authority.md"),
            _r1_instruction_binding("references/epic-authoring.md"),
            _r1_instruction_binding("references/feature-authoring.md"),
            _r1_instruction_binding("references/technical-work-classification.md"),
            _r1_instruction_binding("references/delivery-lifecycle-policy.md"),
        ],
    }
    spec = {
        "logicalShardId": "r1-scope-join-001",
        "stage": "SOURCE_SCOPE",
        "role": "REVIEWER",
        "promptId": "review-source-scope-v1",
        "promptPath": "prompts/review-source-scope.md",
        "resultPayloadSchema": "contracts/review-repair.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/reviewer.md",
            "prompts/fragments/outputs/reviewer-result.md",
            "references/source-authority.md",
            "references/epic-authoring.md",
            "references/feature-authoring.md",
            "references/technical-work-classification.md",
            "references/delivery-lifecycle-policy.md",
        ],
        "packet": packet,
        "evidenceCatalog": [
            {
                "evidenceId": item["blockId"],
                "sha256": item["contentSha256"],
                "locator": item["locator"],
                "content": state["sourceContents"][item["blockId"]],
            }
            for item in _mappings(input_revision.get("blocks"))
            if item.get("blockId") in coverage_roots
        ],
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }
    estimate = _r1_estimated_tokens(
        {"payload": packet, "evidenceCatalog": spec["evidenceCatalog"]}
    )
    if estimate > budget:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
                    "R1 Scope Join packet 超过安全上下文预算，禁止截断 audit union。",
                    "/scopeCandidate",
                ),
            ),
        }
    return {
        "outcome": "ACTION_REQUIRED",
        "reviewPlanSha256": audit_prepared["reviewPlanSha256"],
        "candidateProjectionSha256": candidate_projection_sha256,
        "coverageRootIds": coverage_roots,
        "coverageSha256": coverage_sha256,
        "orderedAuditResultHashes": ordered_hashes,
        "specs": [spec],
        "estimatedInitialPacketTokens": [estimate],
        "diagnostics": (),
    }


def validate_r1_scope_join_result(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(
            result,
            "review-repair.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
    )
    expected = {
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "SOURCE_SCOPE",
        "reviewPlanSha256": prepared.get("reviewPlanSha256"),
        "candidateProjectionSha256": prepared.get(
            "candidateProjectionSha256"
        ),
        "coverageSha256": prepared.get("coverageSha256"),
        "completedCheckIds": list(R1_SCOPE_CHECK_IDS),
        "sourceAuditCoverageUnion": list(prepared.get("coverageRootIds", [])),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "R1_SCOPE_RESULT_BINDING_MISMATCH",
                    "R1 Scope Join result 未绑定当前 audit、Stage 1 投影、覆盖或检查项。",
                    f"/{field}",
                )
            )
    findings = _mappings(result.get("findings"))
    _normalized_findings, finding_diagnostics = _normalize_findings(findings)
    diagnostics.extend(finding_diagnostics)
    decision = result.get("decision")
    if (decision == "PASS" and findings) or (decision != "PASS" and not findings):
        diagnostics.append(
            _diagnostic(
                "R1_REVIEW_DECISION_INCONSISTENT",
                "R1 PASS 必须为空 findings，非 PASS 必须包含 finding。",
                "/findings",
            )
        )
    allowed_evidence = set(prepared.get("coverageRootIds", []))
    candidate = state.get("scopeCandidate")
    known_subjects = (
        {
            str(value)
            for collection in candidate.values()
            if isinstance(collection, list)
            for node in _mappings(collection)
            for key, value in node.items()
            if key.endswith("Id") and isinstance(value, str)
        }
        if isinstance(candidate, Mapping)
        else set()
    )
    for index, finding in enumerate(findings):
        if not set(finding.get("evidenceIds", [])) <= allowed_evidence:
            diagnostics.append(
                _diagnostic(
                    "R1_FINDING_EVIDENCE_UNREACHABLE",
                    "R1 Scope finding 只能引用全量 source audit union。",
                    f"/findings/{index}/evidenceIds",
                )
            )
        if known_subjects and not set(finding.get("subjectIds", [])) <= known_subjects:
            diagnostics.append(
                _diagnostic(
                    "R1_FINDING_SUBJECT_UNKNOWN",
                    "R1 Scope finding 必须绑定当前 Stage 1 candidate 节点。",
                    f"/findings/{index}/subjectIds",
                )
            )
    return _sort(diagnostics)


def r1_results_reusable(
    state: Mapping[str, object],
    scope_result: Mapping[str, object],
) -> bool:
    prepared = prepare_r1_scope_join(state)
    return (
        prepared.get("outcome") == "ACTION_REQUIRED"
        and scope_result.get("decision") == "PASS"
        and not validate_r1_scope_join_result(state, prepared, scope_result)
    )


LAYERED_REVIEW_CHECK_IDS = {
    "STORY_DESIGN": (
        "STORY_OBLIGATION_CLOSURE",
        "STORY_BOUNDARY",
        "AC_OBSERVABILITY",
        "DESIGN_AUTHORITY",
        "POLICY_DELIVERABLE",
    ),
    "TASK_ESTIMATION": (
        "STORY_AC_TASK_COVERAGE",
        "TASK_STANDARD_MATCH",
        "MEASUREMENT_ATOMICITY",
        "EFFECTIVE_START_EVIDENCE",
        "DEPENDENCY_VALIDITY",
    ),
}
THEME_JOIN_CHECK_IDS = (
    "LEAF_RESULT_HASH_CLOSURE",
    "FINDING_PRESERVATION",
    "THEME_DECISION_CONSISTENCY",
)
ADJUDICATION_CHECK_IDS = (
    "PROPOSITION_CLOSED",
    "FINDING_SELECTION_EXPLICIT",
    "OWNER_AND_EVIDENCE_PRESERVED",
)


def _layered_projection(
    candidate: Mapping[str, object], review_kind: str
) -> tuple[dict[str, object], str]:
    if review_kind == "STORY_DESIGN":
        projection = _story_owner_projection(candidate)
    elif review_kind == "TASK_ESTIMATION":
        projection = _task_owner_projection(candidate)
    else:
        raise ValueError(f"unsupported review kind: {review_kind}")
    return projection, sha256_bytes(canonical_json_bytes(projection))


def _layered_checkpoint(
    state: Mapping[str, object], review_kind: str
) -> Mapping[str, object] | None:
    value = state.get(
        "storyAcCheckpoint"
        if review_kind == "STORY_DESIGN"
        else "taskCheckpoint"
    )
    return value if isinstance(value, Mapping) else None


def _layered_material(
    state: Mapping[str, object],
    story: Mapping[str, object],
    review_kind: str,
) -> dict[str, object]:
    candidate = state["candidate"]
    story_id = str(story["storyId"])
    feature_id = str(story["featureId"])
    criteria = [
        deepcopy(dict(item))
        for item in _mappings(candidate.get("acceptanceCriteria"))
        if item.get("storyId") == story_id
    ]
    material: dict[str, object] = {
        "story": deepcopy(dict(story)),
        "acceptanceCriteria": criteria,
        "feature": next(
            (
                deepcopy(dict(item))
                for item in _mappings(candidate.get("features"))
                if item.get("featureId") == feature_id
            ),
            None,
        ),
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
    }
    if review_kind == "TASK_ESTIMATION":
        tasks = [
            deepcopy(dict(item))
            for item in _mappings(candidate.get("tasks"))
            if item.get("storyId") == story_id
        ]
        task_ids = {str(item["taskId"]) for item in tasks}
        material.update(
            {
                "tasks": tasks,
                "dependencies": [
                    deepcopy(dict(item))
                    for item in _mappings(candidate.get("dependencies"))
                    if item.get("fromNodeId") in task_ids
                    or item.get("toNodeId") in task_ids
                ],
                "effectiveStartMatches": [
                    deepcopy(dict(item))
                    for item in _mappings(candidate.get("effectiveStartMatches"))
                    if item.get("taskId") in task_ids
                ],
            }
        )
        source = state.get("taskCatalog")
        by_work_type_id = (
            source.by_work_type_id
            if hasattr(source, "by_work_type_id")
            else {}
        )
        used_ids = sorted({str(item.get("workTypeId")) for item in tasks})
        material["taskStandards"] = [
            deepcopy(dict(by_work_type_id[work_type_id]))
            for work_type_id in used_ids
            if work_type_id in by_work_type_id
        ]
    return material


def _material_subject_ids(material: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    for value in material.values():
        nodes = [value] if isinstance(value, Mapping) else _mappings(value)
        for node in nodes:
            for field, node_id in node.items():
                if (
                    field.endswith("Id")
                    and isinstance(node_id, str)
                    and node_id not in result
                ):
                    result.append(node_id)
                    break
    return result


def _layered_spec(
    state: Mapping[str, object],
    review_kind: str,
    material: Mapping[str, object],
    logical_theme_id: str,
    sequence: int,
    physical_index: int,
    review_plan_sha256: str,
    candidate_projection_sha256: str,
) -> dict[str, object]:
    subject_ids = _material_subject_ids(material)
    shard_id = f"{review_kind.lower().replace('_', '-')}-{sequence:03d}"
    evidence_id = f"review-evidence-{shard_id}"
    content = canonical_json_bytes(material).decode("utf-8")
    coverage_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "reviewKind": review_kind,
                "logicalThemeId": logical_theme_id,
                "subjectIds": subject_ids,
                "evidenceIds": [evidence_id],
                "candidateProjectionSha256": candidate_projection_sha256,
            }
        )
    )
    prompt_name = (
        "review-story-design.md"
        if review_kind == "STORY_DESIGN"
        else "review-task-estimation.md"
    )
    references = (
        [
            "references/story-authoring.md",
            "references/acceptance-criteria.md",
            "references/technical-work-classification.md",
            "references/delivery-lifecycle-policy.md",
        ]
        if review_kind == "STORY_DESIGN"
        else [
            "references/task-authoring.md",
            "references/effective-start-matching.md",
            "references/delivery-work-classification.md",
        ]
    )
    return {
        "logicalShardId": shard_id,
        "stage": review_kind,
        "role": "REVIEWER",
        "promptId": prompt_name.removesuffix(".md") + "-v1",
        "promptPath": f"prompts/{prompt_name}",
        "resultPayloadSchema": "contracts/review-repair.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/reviewer.md",
            "prompts/fragments/outputs/reviewer-result.md",
            *references,
        ],
        "evidenceCatalog": [
            {
                "evidenceId": evidence_id,
                "locator": f"theme:{logical_theme_id}/physical:{physical_index}",
                "content": content,
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
        ],
        "packet": {
            "reviewKind": review_kind,
            "reviewSetId": state["reviewSetId"],
            "runId": state["runId"],
            "reviewPlanSha256": review_plan_sha256,
            "candidateProjectionSha256": candidate_projection_sha256,
            "stageCheckpointSha256": sha256_bytes(
                canonical_json_bytes(_layered_checkpoint(state, review_kind))
            ),
            "logicalThemeId": logical_theme_id,
            "physicalShardIndex": physical_index,
            "subjectIds": subject_ids,
            "evidenceIds": [evidence_id],
            "coverageSha256": coverage_sha256,
            "requiredCheckIds": list(LAYERED_REVIEW_CHECK_IDS[review_kind]),
            "material": deepcopy(dict(material)),
        },
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def prepare_layered_review(
    state: Mapping[str, object], review_kind: str
) -> Mapping[str, object]:
    candidate = state.get("candidate")
    checkpoint = _layered_checkpoint(state, review_kind)
    if (
        review_kind not in LAYERED_REVIEW_CHECK_IDS
        or not isinstance(candidate, Mapping)
        or not isinstance(checkpoint, Mapping)
        or validate_contract(
            checkpoint, "stage-checkpoint.schema.json", NEXT_SCHEMA_REGISTRY
        )
    ):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "LAYERED_REVIEW_STATE_INVALID",
                    "分层评审缺少有效 candidate 或阶段 checkpoint。",
                    "/state",
                ),
            ),
        }
    projection, projection_sha256 = _layered_projection(candidate, review_kind)
    expected_owner_sha = sha256_bytes(canonical_json_bytes(projection))
    if checkpoint.get("ownerProjectionSha256") != expected_owner_sha:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "REVIEW_CHECKPOINT_BINDING_STALE",
                    "阶段 checkpoint 不再绑定当前 Owner projection。",
                    "/checkpoint/ownerProjectionSha256",
                ),
            ),
        }
    stories = _mappings(candidate.get("stories"))
    materials = [
        (
            story,
            _layered_material(state, story, review_kind),
        )
        for story in stories
    ]
    theme_indices: dict[str, int] = defaultdict(int)
    shard_rows: list[dict[str, object]] = []
    for sequence, (story, material) in enumerate(materials, 1):
        theme_id = str(story.get("featureId"))
        physical_index = theme_indices[theme_id]
        theme_indices[theme_id] += 1
        shard_rows.append(
            {
                "sequence": sequence,
                "story": story,
                "material": material,
                "logicalThemeId": theme_id,
                "physicalShardIndex": physical_index,
            }
        )
    if any(count > 8 for count in theme_indices.values()):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "LAYERED_REVIEW_CAPACITY_EXCEEDED",
                    "单个逻辑主题的分层评审不得超过八个物理 shard。",
                    "/candidate/stories",
                ),
            ),
        }
    review_plan = {
        "contract": "ai-sow-review-plan-v1",
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "candidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        "mode": str(state.get("reviewMode", "FULL")),
        "shards": [
            {
                "reviewShardId": f"{review_kind.lower().replace('_', '-')}-{row['sequence']:03d}",
                "kind": review_kind,
                "logicalThemeId": row["logicalThemeId"],
                "physicalShardIndex": row["physicalShardIndex"],
                "subjectIds": _material_subject_ids(row["material"]),
            }
            for row in shard_rows
        ],
    }
    plan_diagnostics = validate_contract(
        review_plan, "review-repair.schema.json", NEXT_SCHEMA_REGISTRY
    )
    if plan_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": plan_diagnostics,
        }
    plan_sha256 = sha256_bytes(canonical_json_bytes(review_plan))
    specs = [
        _layered_spec(
            state,
            review_kind,
            row["material"],
            str(row["logicalThemeId"]),
            int(row["sequence"]),
            int(row["physicalShardIndex"]),
            plan_sha256,
            projection_sha256,
        )
        for row in shard_rows
    ]
    estimates = [
        _r1_estimated_tokens(
            {"payload": spec["packet"], "evidenceCatalog": spec["evidenceCatalog"]}
        )
        for spec in specs
    ]
    budget = state.get("maxInitialPacketTokens")
    if (
        not isinstance(budget, int)
        or isinstance(budget, bool)
        or any(value > budget for value in estimates)
    ):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "specs": [],
            "diagnostics": (
                _diagnostic(
                    "LAYERED_REVIEW_CAPACITY_EXCEEDED",
                    "分层评审无法在安全上下文预算内完成。",
                    "/candidate/stories",
                ),
            ),
        }
    return {
        "outcome": "ACTION_REQUIRED",
        "reviewKind": review_kind,
        "reviewPlan": review_plan,
        "reviewPlanSha256": plan_sha256,
        "candidateProjectionSha256": projection_sha256,
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": (),
    }


def validate_layered_review_result(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    logical_shard_id: str,
    result: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(result, "review-repair.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    spec = next(
        (
            item
            for item in _mappings(prepared.get("specs"))
            if item.get("logicalShardId") == logical_shard_id
        ),
        None,
    )
    if spec is None:
        diagnostics.append(
            _diagnostic(
                "REVIEW_SHARD_UNKNOWN",
                "评审结果不属于当前 review plan。",
                "/logicalShardId",
            )
        )
        return _sort(diagnostics)
    packet = spec["packet"]
    expected = {
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": packet["reviewKind"],
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared["candidateProjectionSha256"],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(packet["requiredCheckIds"]),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "LAYERED_REVIEW_RESULT_BINDING_MISMATCH",
                    "评审结果未绑定当前 plan、projection、coverage 或检查项。",
                    f"/{field}",
                )
            )
    findings = _mappings(result.get("findings"))
    _normalized_findings, finding_diagnostics = _normalize_findings(findings)
    diagnostics.extend(finding_diagnostics)
    if (result.get("decision") == "PASS" and findings) or (
        result.get("decision") != "PASS" and not findings
    ):
        diagnostics.append(
            _diagnostic(
                "LAYERED_REVIEW_DECISION_INCONSISTENT",
                "PASS 必须没有 finding；非 PASS 必须包含 finding。",
                "/findings",
            )
        )
    allowed_subjects = set(packet["subjectIds"])
    allowed_evidence = set(packet["evidenceIds"])
    for index, finding in enumerate(findings):
        if not set(finding.get("subjectIds", [])) <= allowed_subjects:
            diagnostics.append(
                _diagnostic(
                    "REVIEW_FINDING_SUBJECT_UNKNOWN",
                    "finding 只能引用当前物理 shard 的 subject。",
                    f"/findings/{index}/subjectIds",
                )
            )
        if not set(finding.get("evidenceIds", [])) <= allowed_evidence:
            diagnostics.append(
                _diagnostic(
                    "REVIEW_FINDING_EVIDENCE_UNREACHABLE",
                    "finding 只能引用当前物理 shard 可达 evidence。",
                    f"/findings/{index}/evidenceIds",
                )
            )
    return _sort(diagnostics)


def _validated_leaf_results(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    wrappers: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Mapping[str, object]], tuple[Diagnostic, ...]]:
    by_shard: dict[str, Mapping[str, object]] = {}
    diagnostics: list[Diagnostic] = []
    for wrapper in wrappers:
        shard_id = wrapper.get("logicalShardId")
        result = wrapper.get("result")
        if not isinstance(shard_id, str) or not isinstance(result, Mapping):
            continue
        if shard_id in by_shard:
            diagnostics.append(
                _diagnostic(
                    "LEAF_REVIEW_RESULT_DUPLICATE",
                    "每个 leaf shard 只能有一个结果。",
                    f"/leafResults/{shard_id}",
                )
            )
        by_shard[shard_id] = result
    required = {
        str(spec["logicalShardId"])
        for spec in _mappings(prepared.get("specs"))
    }
    if set(by_shard) != required:
        diagnostics.append(
            _diagnostic(
                "LEAF_REVIEW_RESULT_GROUP_INCOMPLETE",
                "Theme Join 前必须收齐全部 leaf review results。",
                "/leafResults",
            )
        )
    for shard_id, result in by_shard.items():
        diagnostics.extend(
            validate_layered_review_result(state, prepared, shard_id, result)
        )
    return by_shard, _sort(diagnostics)


def prepare_theme_joins(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    leaf_results: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    by_shard, diagnostics = _validated_leaf_results(
        state, prepared, leaf_results
    )
    if diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "specs": [],
            "diagnostics": diagnostics,
        }
    shards_by_theme: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for shard in _mappings(prepared.get("reviewPlan", {}).get("shards")):
        shards_by_theme[str(shard["logicalThemeId"])].append(shard)
    specs: list[dict[str, object]] = []
    direct_results: list[dict[str, object]] = []
    for theme_id in sorted(shards_by_theme):
        shards = sorted(
            shards_by_theme[theme_id],
            key=lambda item: int(item["physicalShardIndex"]),
        )
        results = [by_shard[str(item["reviewShardId"])] for item in shards]
        if len(results) == 1:
            direct_results.append(
                {"logicalThemeId": theme_id, "result": deepcopy(dict(results[0]))}
            )
            continue
        leaf_hashes = [
            sha256_bytes(canonical_json_bytes(result)) for result in results
        ]
        findings = [
            deepcopy(dict(finding))
            for result in results
            for finding in _mappings(result.get("findings"))
        ]
        findings, finding_diagnostics = _normalize_findings(findings)
        if finding_diagnostics:
            return {
                "outcome": "OWNER_FIX_REQUIRED",
                "specs": [],
                "directResults": direct_results,
                "diagnostics": finding_diagnostics,
            }
        content = canonical_json_bytes(
            {"leafResults": results, "findings": findings}
        ).decode("utf-8")
        coverage_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "logicalThemeId": theme_id,
                    "leafReviewResultSha256s": leaf_hashes,
                }
            )
        )
        specs.append(
            {
                "logicalShardId": f"theme-join-{len(specs) + 1:03d}",
                "stage": "THEME_JOIN",
                "role": "THEME_JOIN",
                "promptId": "review-theme-join-v1",
                "promptPath": "prompts/review-theme-join.md",
                "resultPayloadSchema": "contracts/review-repair.schema.json",
                "referencePaths": [
                    "prompts/fragments/roles/reviewer.md",
                    "prompts/fragments/outputs/reviewer-result.md",
                ],
                "evidenceCatalog": [
                    {
                        "evidenceId": f"theme-evidence-{len(specs) + 1:03d}",
                        "locator": f"theme:{theme_id}",
                        "content": content,
                        "sha256": sha256_bytes(content.encode("utf-8")),
                    }
                ],
                "packet": {
                    "reviewKind": "THEME_JOIN",
                    "reviewSetId": state["reviewSetId"],
                    "runId": state["runId"],
                    "reviewPlanSha256": prepared["reviewPlanSha256"],
                    "candidateProjectionSha256": prepared[
                        "candidateProjectionSha256"
                    ],
                    "logicalThemeId": theme_id,
                    "leafReviewResultSha256s": leaf_hashes,
                    "leafResults": deepcopy(results),
                    "findingIds": [str(item["findingId"]) for item in findings],
                    "coverageSha256": coverage_sha256,
                    "requiredCheckIds": list(THEME_JOIN_CHECK_IDS),
                },
                "modelProfileId": state["modelProfileId"],
                "modelConfigSha256": state["modelConfigSha256"],
                "maxOutputTokens": state["maxOutputTokens"],
            }
        )
    return {
        "outcome": "ACTION_REQUIRED" if specs else "PASS",
        "specs": specs,
        "directResults": direct_results,
        "diagnostics": (),
    }


def validate_theme_join_result(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    spec: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(result, "review-repair.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    packet = spec["packet"]
    expected = {
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "THEME_JOIN",
        "reviewPlanSha256": prepared["reviewPlanSha256"],
        "candidateProjectionSha256": prepared["candidateProjectionSha256"],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(THEME_JOIN_CHECK_IDS),
        "leafReviewResultSha256s": list(packet["leafReviewResultSha256s"]),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "THEME_JOIN_RESULT_BINDING_MISMATCH",
                    "Theme Join 未绑定全部 leaf hashes 或当前投影。",
                    f"/{field}",
                )
            )
    expected_findings = [
        finding
        for leaf_result in _mappings(packet.get("leafResults"))
        for finding in _mappings(leaf_result.get("findings"))
    ]
    actual_findings = _mappings(result.get("findings"))
    _normalized_actual, finding_diagnostics = _normalize_findings(
        actual_findings
    )
    diagnostics.extend(finding_diagnostics)
    expected_by_id = {
        str(item.get("findingId")): item for item in expected_findings
    }
    actual_by_id = {
        str(item.get("findingId")): item for item in actual_findings
    }
    expected_finding_ids = set(expected_by_id)
    actual_finding_ids = set(actual_by_id)
    if not expected_finding_ids <= actual_finding_ids:
        diagnostics.append(
            _diagnostic(
                "THEME_JOIN_FINDING_DROPPED",
                "Theme Join 不得静默删除 leaf finding。",
                "/findings",
            )
        )
    if actual_finding_ids != expected_finding_ids:
        diagnostics.append(
            _diagnostic(
                "THEME_JOIN_FINDING_SET_MISMATCH",
                "Theme Join findings 必须与 leaf findings 精确同集。",
                "/findings",
            )
        )
    if any(
        canonical_json_bytes(actual_by_id[finding_id])
        != canonical_json_bytes(expected_by_id[finding_id])
        for finding_id in actual_finding_ids & expected_finding_ids
    ):
        diagnostics.append(
            _diagnostic(
                "THEME_JOIN_FINDING_CONTENT_MISMATCH",
                "Theme Join 不得改写 leaf finding 的任何字段。",
                "/findings",
            )
        )
    if (result.get("decision") == "PASS") != (not actual_finding_ids):
        diagnostics.append(
            _diagnostic(
                "THEME_JOIN_DECISION_INCONSISTENT",
                "Theme decision 必须与保留 finding 一致。",
                "/decision",
            )
        )
    return _sort(diagnostics)


def _normalize_findings(
    findings: Sequence[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], tuple[Diagnostic, ...]]:
    """Deduplicate identical cross-review findings and diagnose ID collisions."""

    findings_by_id: dict[str, Mapping[str, object]] = {}
    diagnostics: list[Diagnostic] = []
    normalized: list[Mapping[str, object]] = []
    for finding in findings:
        finding_id = str(finding.get("findingId"))
        existing = findings_by_id.get(finding_id)
        if existing is None:
            findings_by_id[finding_id] = finding
            normalized.append(finding)
            continue
        if canonical_json_bytes(existing) != canonical_json_bytes(finding):
            diagnostics.append(
                _diagnostic(
                    "REVIEW_FINDING_ID_CONFLICT",
                    "同一 findingId 在独立评审结果中绑定了不同内容。",
                    f"/findings/{finding_id}",
                )
            )
    return normalized, _sort(diagnostics)


def prepare_adjudications(
    state: Mapping[str, object], findings: Sequence[Mapping[str, object]]
) -> Mapping[str, object]:
    normalized, finding_diagnostics = _normalize_findings(findings)
    if finding_diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "specs": [],
            "diagnostics": finding_diagnostics,
        }
    findings_by_id: dict[str, Mapping[str, object]] = {}
    by_subject: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for finding in normalized:
        finding_id = str(finding.get("findingId"))
        findings_by_id[finding_id] = finding
        subjects = _ids(finding.get("subjectIds"))
        for subject_id in subjects:
            by_subject[subject_id].append(finding)
    conflicting_by_subject = {
        subject_id: values
        for subject_id, values in by_subject.items()
        if len({str(item.get("summary")) for item in values}) > 1
    }
    parent: dict[str, str] = {}

    def find(finding_id: str) -> str:
        parent.setdefault(finding_id, finding_id)
        while parent[finding_id] != finding_id:
            parent[finding_id] = parent[parent[finding_id]]
            finding_id = parent[finding_id]
        return finding_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for values in conflicting_by_subject.values():
        finding_ids = sorted({str(item["findingId"]) for item in values})
        for finding_id in finding_ids:
            find(finding_id)
        for finding_id in finding_ids[1:]:
            union(finding_ids[0], finding_id)

    component_finding_ids: dict[str, set[str]] = defaultdict(set)
    for finding_id in parent:
        component_finding_ids[find(finding_id)].add(finding_id)
    component_subject_ids: dict[str, set[str]] = defaultdict(set)
    for subject_id, values in conflicting_by_subject.items():
        roots = {find(str(item["findingId"])) for item in values}
        if len(roots) != 1:
            raise ValueError("conflicting subject spans multiple adjudication components")
        component_subject_ids[roots.pop()].add(subject_id)

    conflicting = [
        (
            sorted(component_subject_ids[root]),
            [findings_by_id[item] for item in sorted(finding_ids)],
        )
        for root, finding_ids in sorted(
            component_finding_ids.items(), key=lambda item: min(item[1])
        )
    ]
    specs: list[dict[str, object]] = []
    for subject_ids, values in conflicting:
        finding_ids = sorted(str(item["findingId"]) for item in values)
        proposition_id = "proposition-" + sha256_bytes(
            canonical_json_bytes(
                {
                    "subjectIds": subject_ids,
                    "findingIds": finding_ids,
                }
            )
        )[:16]
        content = canonical_json_bytes(values).decode("utf-8")
        review_plan_sha256 = str(
            state.get(
                "reviewPlanSha256",
                sha256_bytes(
                    canonical_json_bytes(
                        {
                            "reviewSetId": state["reviewSetId"],
                            "runId": state["runId"],
                            "kind": "ADJUDICATION",
                        }
                    )
                ),
            )
        )
        candidate_projection_sha256 = sha256_bytes(
            canonical_json_bytes(state.get("candidate", {}))
        )
        coverage_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "propositionId": proposition_id,
                    "subjectIds": subject_ids,
                    "findingIds": finding_ids,
                }
            )
        )
        specs.append(
            {
                "logicalShardId": f"adjudication-{len(specs) + 1:03d}",
                "stage": "ADJUDICATION",
                "role": "ADJUDICATOR",
                "promptId": "review-adjudication-v1",
                "promptPath": "prompts/review-adjudication.md",
                "resultPayloadSchema": "contracts/review-repair.schema.json",
                "referencePaths": [
                    "prompts/fragments/roles/reviewer.md",
                    "prompts/fragments/outputs/reviewer-result.md",
                ],
                "evidenceCatalog": [
                    {
                        "evidenceId": f"adjudication-evidence-{len(specs) + 1:03d}",
                        "locator": f"subjects:{','.join(subject_ids)}",
                        "content": content,
                        "sha256": sha256_bytes(content.encode("utf-8")),
                    }
                ],
                "packet": {
                    "reviewKind": "ADJUDICATION",
                    "reviewSetId": state["reviewSetId"],
                    "runId": state["runId"],
                    "propositionId": proposition_id,
                    "reviewPlanSha256": review_plan_sha256,
                    "candidateProjectionSha256": candidate_projection_sha256,
                    "coverageSha256": coverage_sha256,
                    "subjectIds": subject_ids,
                    "findingIds": finding_ids,
                    "findings": deepcopy(list(values)),
                    "requiredCheckIds": list(ADJUDICATION_CHECK_IDS),
                },
                "modelProfileId": state["modelProfileId"],
                "modelConfigSha256": state["modelConfigSha256"],
                "maxOutputTokens": state["maxOutputTokens"],
            }
        )
    return {
        "outcome": "ACTION_REQUIRED" if specs else "PASS",
        "specs": specs,
        "diagnostics": (),
    }


def validate_adjudication_result(
    state: Mapping[str, object],
    spec: Mapping[str, object],
    result: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(result, "review-repair.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    packet = spec["packet"]
    expected = {
        "reviewSetId": state["reviewSetId"],
        "runId": state["runId"],
        "kind": "ADJUDICATION",
        "reviewPlanSha256": packet["reviewPlanSha256"],
        "candidateProjectionSha256": packet["candidateProjectionSha256"],
        "coverageSha256": packet["coverageSha256"],
        "completedCheckIds": list(ADJUDICATION_CHECK_IDS),
        "propositionId": packet["propositionId"],
    }
    for field, value in expected.items():
        if result.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "ADJUDICATION_RESULT_BINDING_MISMATCH",
                    "Adjudication 未绑定当前 proposition、findings 或 candidate。",
                    f"/{field}",
                )
            )
    selected = set(_ids(result.get("selectedFindingIds")))
    allowed = set(packet["findingIds"])
    if not selected or not selected <= allowed:
        diagnostics.append(
            _diagnostic(
                "ADJUDICATION_SELECTION_INVALID",
                "selectedFindingIds 必须是当前 proposition 的非空子集。",
                "/selectedFindingIds",
            )
        )
    findings = _mappings(result.get("findings"))
    _normalized_findings, finding_diagnostics = _normalize_findings(findings)
    diagnostics.extend(finding_diagnostics)
    findings_by_id = {str(item.get("findingId")): item for item in findings}
    if set(findings_by_id) != selected:
        diagnostics.append(
            _diagnostic(
                "ADJUDICATION_FINDING_SET_MISMATCH",
                "Adjudication findings 必须精确对应 selectedFindingIds。",
                "/findings",
            )
        )
    packet_findings_by_id = {
        str(item.get("findingId")): item
        for item in _mappings(packet.get("findings"))
    }
    if any(
        finding_id not in packet_findings_by_id
        or canonical_json_bytes(findings_by_id[finding_id])
        != canonical_json_bytes(packet_findings_by_id[finding_id])
        for finding_id in findings_by_id
    ):
        diagnostics.append(
            _diagnostic(
                "ADJUDICATION_FINDING_CONTENT_MISMATCH",
                "Adjudication 只能选择 proposition 中的原始 finding，不得改写字段。",
                "/findings",
            )
        )
    if result.get("decision") == "PASS" or not findings:
        diagnostics.append(
            _diagnostic(
                "ADJUDICATION_DECISION_INCONSISTENT",
                "存在被选 finding 时 Adjudication 不得 PASS。",
                "/decision",
            )
        )
    return _sort(diagnostics)


def _node_owner_index(model: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for collection, id_field in NODE_COLLECTIONS.items():
        if collection in {"scopeClosure", "effectiveStartMatches"}:
            continue
        owner = TOP_LEVEL_WRITE_OWNER[collection]
        for node in _mappings(model.get(collection)):
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                result[node_id] = owner
    for node in _mappings(model.get("scopeClosure")):
        node_id = node.get("inputItemId")
        if isinstance(node_id, str):
            result.setdefault(node_id, "STAGE_1")
    for node in _mappings(model.get("effectiveStartMatches")):
        node_id = node.get("taskId")
        if isinstance(node_id, str):
            result.setdefault(node_id, "STAGE_3")
    return result


def build_repair_plan(
    state: Mapping[str, object], findings: Sequence[Mapping[str, object]]
) -> Mapping[str, object]:
    candidate = state.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("repair state candidate is missing")
    repairable = [
        finding
        for finding in findings
        if finding.get("type") == "OWNER_FIX_REQUIRED"
        and finding.get("owner") in {"STAGE_1", "STAGE_2", "STAGE_3"}
    ]
    if not repairable:
        raise ValueError("repair plan requires at least one Owner finding")
    rank = {"STAGE_1": 1, "STAGE_2": 2, "STAGE_3": 3}
    earliest_owner = min(
        (str(item["owner"]) for item in repairable), key=rank.__getitem__
    )
    owner_index = _node_owner_index(candidate)
    graph = derive_impact_graph(candidate)
    known_ids = set(owner_index)
    findings_by_owner: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for finding in repairable:
        findings_by_owner[str(finding["owner"])].append(finding)
    waves: list[dict[str, object]] = []
    resume = {
        "STAGE_1": "EPIC_FEATURE",
        "STAGE_2": "STORY_AC",
        "STAGE_3": "TASK",
    }
    for owner in sorted(findings_by_owner, key=rank.__getitem__):
        values = findings_by_owner[owner]
        editable = sorted(
            {
                subject_id
                for finding in values
                for subject_id in _ids(finding.get("subjectIds"))
                if owner_index.get(subject_id) == owner
            }
        )
        context = sorted(
            {
                related
                for subject_id in editable
                for related in graph.get(subject_id, ())
                if related not in editable
            }
        )
        locked = sorted(known_ids - set(editable) - set(context))
        waves.append(
            {
                "repairWaveId": f"repair-wave-{len(waves) + 1:03d}",
                "findingIds": sorted(str(item["findingId"]) for item in values),
                "editableNodeIds": editable,
                "contextNodeIds": context,
                "lockedNodeIds": locked,
                "resumePhase": resume[owner],
            }
        )
    plan_core = {
        "contract": "ai-sow-repair-plan-v1",
        "repairPlanId": "repair-" + sha256_bytes(
            canonical_json_bytes(
                {
                    "runId": state["runId"],
                    "candidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
                    "findingIds": sorted(str(item["findingId"]) for item in repairable),
                }
            )
        )[:16],
        "runId": state["runId"],
        "baseCandidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        "earliestOwner": earliest_owner,
        "waves": waves,
    }
    diagnostics = validate_contract(
        plan_core, "review-repair.schema.json", NEXT_SCHEMA_REGISTRY
    )
    if diagnostics:
        raise ValueError("generated repair plan does not satisfy contract")
    return plan_core


def _advance_review_kind(
    state: Mapping[str, object],
    review_kind: str,
    leaf_field: str,
    join_field: str,
) -> Mapping[str, object]:
    prepared = prepare_layered_review(state, review_kind)
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return {
            "status": "FAILED",
            "outcome": prepared.get("outcome", "CONTRACT_UNSUPPORTED"),
            "reviewKind": review_kind,
            "diagnostics": prepared.get("diagnostics", ()),
        }
    wrappers = _mappings(state.get(leaf_field))
    required = {
        str(spec["logicalShardId"])
        for spec in _mappings(prepared.get("specs"))
    }
    received = {
        str(item.get("logicalShardId"))
        for item in wrappers
        if isinstance(item.get("result"), Mapping)
    }
    if received != required:
        return {
            "status": "ACTION_REQUIRED",
            "outcome": "ACTION_REQUIRED",
            "reviewKind": review_kind,
            "stage": review_kind,
            "specs": prepared["specs"],
            "pendingLogicalShardIds": sorted(required - received),
            "prepared": prepared,
            "diagnostics": (),
        }
    by_shard, leaf_diagnostics = _validated_leaf_results(
        state, prepared, wrappers
    )
    if leaf_diagnostics:
        return {
            "status": "FAILED",
            "outcome": "OWNER_FIX_REQUIRED",
            "reviewKind": review_kind,
            "diagnostics": leaf_diagnostics,
        }
    joins = prepare_theme_joins(state, prepared, wrappers)
    join_specs = _mappings(joins.get("specs"))
    join_wrappers = _mappings(state.get(join_field))
    join_by_shard = {
        str(item.get("logicalShardId")): item.get("result")
        for item in join_wrappers
        if isinstance(item.get("result"), Mapping)
    }
    required_joins = {str(spec["logicalShardId"]) for spec in join_specs}
    if set(join_by_shard) != required_joins:
        return {
            "status": "ACTION_REQUIRED",
            "outcome": "ACTION_REQUIRED",
            "reviewKind": "THEME_JOIN",
            "sourceReviewKind": review_kind,
            "stage": "THEME_JOIN",
            "specs": join_specs,
            "pendingLogicalShardIds": sorted(
                required_joins - set(join_by_shard)
            ),
            "prepared": prepared,
            "diagnostics": (),
        }
    join_diagnostics = tuple(
        diagnostic
        for spec in join_specs
        for diagnostic in validate_theme_join_result(
            state,
            prepared,
            spec,
            join_by_shard[str(spec["logicalShardId"])],
        )
    )
    if join_diagnostics:
        return {
            "status": "FAILED",
            "outcome": "OWNER_FIX_REQUIRED",
            "reviewKind": "THEME_JOIN",
            "diagnostics": _sort(join_diagnostics),
        }
    theme_by_shards: dict[str, list[str]] = defaultdict(list)
    for shard in _mappings(prepared.get("reviewPlan", {}).get("shards")):
        theme_by_shards[str(shard["logicalThemeId"])].append(
            str(shard["reviewShardId"])
        )
    join_result_by_theme = {
        str(spec["packet"]["logicalThemeId"]): join_by_shard[
            str(spec["logicalShardId"])
        ]
        for spec in join_specs
    }
    final_results: list[Mapping[str, object]] = []
    for theme_id in sorted(theme_by_shards):
        if theme_id in join_result_by_theme:
            final_results.append(join_result_by_theme[theme_id])
        else:
            shard_ids = theme_by_shards[theme_id]
            if len(shard_ids) == 1:
                final_results.append(by_shard[shard_ids[0]])
    all_hashes = [
        sha256_bytes(canonical_json_bytes(item["result"]))
        for item in wrappers
    ] + [
        sha256_bytes(canonical_json_bytes(item["result"]))
        for item in join_wrappers
    ]
    return {
        "status": "COMPLETE",
        "outcome": "PASS",
        "reviewKind": review_kind,
        "prepared": prepared,
        "finalResults": final_results,
        "findings": [
            deepcopy(dict(finding))
            for result in final_results
            for finding in _mappings(result.get("findings"))
        ],
        "reviewResultSha256s": all_hashes,
        "diagnostics": (),
    }


def advance_layered_review(state: Mapping[str, object]) -> Mapping[str, object]:
    """Advance fresh leaf reviews, theme joins, adjudication and repair routing."""
    completed: list[Mapping[str, object]] = []
    for review_kind, leaf_field, join_field in (
        (
            "STORY_DESIGN",
            "storyDesignReviewResults",
            "storyDesignThemeJoinResults",
        ),
        (
            "TASK_ESTIMATION",
            "taskEstimationReviewResults",
            "taskEstimationThemeJoinResults",
        ),
    ):
        progress = _advance_review_kind(
            state, review_kind, leaf_field, join_field
        )
        if progress.get("status") != "COMPLETE":
            return progress
        completed.append(progress)
    findings, finding_diagnostics = _normalize_findings([
        finding
        for progress in completed
        for finding in _mappings(progress.get("findings"))
    ])
    if finding_diagnostics:
        return {
            "status": "FAILED",
            "outcome": "OWNER_FIX_REQUIRED",
            "reviewKind": "LAYERED_REVIEW",
            "diagnostics": finding_diagnostics,
        }
    review_hashes = [
        value
        for progress in completed
        for value in progress.get("reviewResultSha256s", [])
        if isinstance(value, str)
    ]
    adjudications = prepare_adjudications(state, findings)
    if adjudications.get("diagnostics"):
        return {
            "status": "FAILED",
            "outcome": "OWNER_FIX_REQUIRED",
            "reviewKind": "ADJUDICATION",
            "diagnostics": adjudications["diagnostics"],
        }
    adjudication_specs = _mappings(adjudications.get("specs"))
    if adjudication_specs:
        wrappers = _mappings(state.get("adjudicationResults"))
        by_shard = {
            str(item.get("logicalShardId")): item.get("result")
            for item in wrappers
            if isinstance(item.get("result"), Mapping)
        }
        required = {str(spec["logicalShardId"]) for spec in adjudication_specs}
        if set(by_shard) != required:
            return {
                "status": "ACTION_REQUIRED",
                "outcome": "ACTION_REQUIRED",
                "reviewKind": "ADJUDICATION",
                "stage": "ADJUDICATION",
                "specs": adjudication_specs,
                "pendingLogicalShardIds": sorted(required - set(by_shard)),
                "diagnostics": (),
            }
        adjudication_diagnostics = tuple(
            diagnostic
            for spec in adjudication_specs
            for diagnostic in validate_adjudication_result(
                state, spec, by_shard[str(spec["logicalShardId"])]
            )
        )
        if adjudication_diagnostics:
            return {
                "status": "FAILED",
                "outcome": "OWNER_FIX_REQUIRED",
                "reviewKind": "ADJUDICATION",
                "diagnostics": _sort(adjudication_diagnostics),
            }
        conflicting_subjects = {
            subject_id
            for spec in adjudication_specs
            for subject_id in _ids(spec["packet"].get("subjectIds"))
        }
        findings, finding_diagnostics = _normalize_findings([
            finding
            for finding in findings
            if not conflicting_subjects.intersection(
                _ids(finding.get("subjectIds"))
            )
        ] + [
            deepcopy(dict(finding))
            for result in by_shard.values()
            for finding in _mappings(result.get("findings"))
        ])
        if finding_diagnostics:
            return {
                "status": "FAILED",
                "outcome": "OWNER_FIX_REQUIRED",
                "reviewKind": "ADJUDICATION",
                "diagnostics": finding_diagnostics,
            }
        review_hashes.extend(
            sha256_bytes(canonical_json_bytes(item["result"]))
            for item in wrappers
        )
    if any(item.get("type") == "INPUT_REQUIRED" for item in findings):
        return {
            "status": "INPUT_REQUIRED",
            "outcome": "INPUT_REQUIRED",
            "findings": findings,
            "diagnostics": (),
        }
    if any(item.get("type") == "CONTRACT_GAP" for item in findings):
        return {
            "status": "FAILED",
            "outcome": "CONTRACT_UNSUPPORTED",
            "findings": findings,
            "diagnostics": (),
        }
    if findings:
        return {
            "status": "OWNER_FIX_REQUIRED",
            "outcome": "OWNER_FIX_REQUIRED",
            "findings": findings,
            "repairPlan": build_repair_plan(state, findings),
            "diagnostics": (),
        }
    review_decision = {
        "contract": "ai-sow-layered-review-decision-v1",
        "runId": state["runId"],
        "candidateSha256": sha256_bytes(
            canonical_json_bytes(state["candidate"])
        ),
        "scopeClosureCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["scopeClosureCheckpoint"])
        ),
        "storyAcCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["storyAcCheckpoint"])
        ),
        "taskCheckpointSha256": sha256_bytes(
            canonical_json_bytes(state["taskCheckpoint"])
        ),
        "reviewResultSha256s": review_hashes,
        "decision": "PASS",
    }
    return {
        "status": "PASS",
        "outcome": "READY_FOR_APPROVAL",
        "reviewDecision": review_decision,
        "reviewDecisionSha256": sha256_bytes(
            canonical_json_bytes(review_decision)
        ),
        "diagnostics": (),
    }
