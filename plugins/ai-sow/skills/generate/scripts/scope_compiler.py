from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
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
from sow_model import (
    NODE_COLLECTIONS,
    apply_replacement,
    owner_projection_sha256,
    validate as validate_sow_model,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
SOURCE_SCAN_REQUIRED_CHECK_IDS = (
    "SOURCE_BLOCK_COVERAGE",
    "SOURCE_ATOMICITY",
    "QUALIFIER_PRESERVATION",
    "SOURCE_CONFLICT",
)
SOURCE_SCAN_INPUT_ITEM_FIELDS = {
    "inputItemId",
    "kind",
    "text",
    "conditions",
    "thresholds",
    "prohibitions",
    "applicableScopes",
    "sourceRefs",
}
SOURCE_SCAN_INPUT_KINDS = {
    "REQUIREMENT",
    "DESIGN_DECISION",
    "CONSTRAINT",
    "RESPONSIBILITY",
    "EXCLUSION",
    "CONFLICT_CANDIDATE",
}
SCOPE_PROPOSAL_REQUIRED_CHECK_IDS = (
    "GLOBAL_INVENTORY_REVIEW",
    "BOUNDARY_PROPOSAL",
    "CROSS_SHARD_AFFINITY",
    "NO_FINAL_OWNERSHIP",
)
SCOPE_JOIN_REQUIRED_CHECK_IDS = (
    "GLOBAL_SCOPE_CLOSURE",
    "SOURCE_AUTHORITY",
    "DESIGN_AUTHORITY",
    "DELIVERY_POLICY",
    "WORK_CLASS_SOURCE_ORTHOGONAL",
)
STAGE_1_JOIN_COLLECTIONS = {
    "inputItems",
    "scopeClosure",
    "epics",
    "features",
    "designItems",
    "integrations",
    "nfrs",
    "policyInstances",
    "scopeAnnotations",
}
APPROVED_DESIGN_ROLES = {"HLD", "ADR"}
REQUIRED_POLICY_INCLUSIONS = {
    "policy-sit-automation": "DEFAULT_INCLUDED",
    "policy-uat-automation": "DEFAULT_INCLUDED",
    "policy-go-live": "REQUIRED",
}
STAGE_1_REPAIR_CHECK_IDS = (
    "FINDING_ADDRESS",
    "OWNER_WRITE_SCOPE",
    "LOCKED_NODE_PRESERVATION",
    "R1_RECHECK_REQUIRED",
)


def _mappings(value: object) -> list[Mapping[str, object]]:
    return (
        [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _diagnostic_value(
    value: Diagnostic,
    *,
    category: str = "CONTRACT_UNSUPPORTED",
) -> dict[str, object]:
    return {
        "code": value.code,
        "category": category,
        "owner": "STAGE_1",
        "retryable": False,
        "message": value.message,
        "subjectIds": list(value.details.get("subjectIds", ())),
    }


def _estimated_tokens(value: object) -> int:
    return max(1, (len(canonical_json_bytes(value)) + 3) // 4)


def _instruction_binding(relative_path: str) -> dict[str, str]:
    path = SKILL_ROOT / relative_path
    return {
        "path": relative_path,
        "sha256": sha256_bytes(path.read_bytes()),
    }


def _source_scan_error(
    code: str,
    message: str,
    path: str,
) -> dict[str, object]:
    diagnostic = _diagnostic(code, message, path)
    return {
        "outcome": "CONTRACT_UNSUPPORTED",
        "actionKind": "SOURCE_SCAN",
        "coverageRootIds": [],
        "inventorySha256": None,
        "specs": [],
        "estimatedInitialPacketTokens": [],
        "diagnostics": [_diagnostic_value(diagnostic)],
    }


def _source_scan_material(
    state: Mapping[str, object],
) -> tuple[
    Mapping[str, object],
    Mapping[str, str],
    list[Mapping[str, object]],
    list[str],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    input_revision = state.get("inputRevision")
    source_contents = state.get("sourceContents")
    base_candidate = state.get("baseCandidate")
    if not (
        state.get("contract") == "ai-sow-scope-compiler-state-v1"
        and isinstance(input_revision, Mapping)
        and isinstance(source_contents, Mapping)
        and isinstance(base_candidate, Mapping)
        and state.get("baseCandidateSha256")
        == sha256_bytes(canonical_json_bytes(base_candidate))
    ):
        raise ValueError("scope compiler state 绑定无效")
    revision_diagnostics = validate_contract(
        input_revision,
        "input-revision.schema.json",
        NEXT_SCHEMA_REGISTRY,
    )
    if revision_diagnostics:
        raise ValueError("input revision 合同无效")
    if not all(
        isinstance(block_id, str) and isinstance(content, str)
        for block_id, content in source_contents.items()
    ):
        raise ValueError("source content 映射无效")
    blocks = _mappings(input_revision.get("blocks"))
    sources = _mappings(input_revision.get("sources"))
    block_by_id = {
        str(block["blockId"]): block
        for block in blocks
        if isinstance(block.get("blockId"), str)
    }
    role_by_source = {
        str(source["sourceId"]): str(source["role"])
        for source in sources
        if isinstance(source.get("sourceId"), str)
        and isinstance(source.get("role"), str)
    }
    coverage_roots: list[str] = []
    for block in blocks:
        if block.get("extractionDisposition") == "DROPPED":
            continue
        root_id = block.get("primaryCoverageBlockId")
        if not isinstance(root_id, str) or root_id not in block_by_id:
            raise ValueError("coverage root 不存在")
        if root_id not in coverage_roots:
            coverage_roots.append(root_id)
    inventory = [
        {
            "blockId": block.get("blockId"),
            "sourceId": block.get("sourceId"),
            "sourceRole": role_by_source.get(str(block.get("sourceId"))),
            "primaryCoverageBlockId": block.get("primaryCoverageBlockId"),
            "contextBlockIds": list(block.get("contextBlockIds", [])),
            "structuralParentId": block.get("structuralParentId"),
            "extractionDisposition": block.get("extractionDisposition"),
            "locator": block.get("locator"),
        }
        for block in blocks
    ]
    structure_counts = []
    for source in sources:
        source_id = str(source.get("sourceId"))
        source_blocks = [
            block for block in blocks if block.get("sourceId") == source_id
        ]
        root_ids = {
            str(block.get("primaryCoverageBlockId"))
            for block in source_blocks
            if block.get("extractionDisposition") != "DROPPED"
        }
        structure_counts.append(
            {
                "sourceId": source_id,
                "sourceRole": source.get("role"),
                "blockCount": len(source_blocks),
                "coverageRootCount": len(root_ids),
                "contextOnlyCount": sum(
                    block.get("extractionDisposition") == "CONTEXT_ONLY"
                    for block in source_blocks
                ),
                "droppedCount": sum(
                    block.get("extractionDisposition") == "DROPPED"
                    for block in source_blocks
                ),
            }
        )
    normalized_contents = {
        str(block_id): str(content) for block_id, content in source_contents.items()
    }
    for root_id in coverage_roots:
        block = block_by_id[root_id]
        content = normalized_contents.get(root_id)
        if (
            content is None
            or sha256_bytes(content.encode("utf-8")) != block.get("contentSha256")
        ):
            raise ValueError("coverage root 内容或 hash 无效")
    return (
        input_revision,
        normalized_contents,
        blocks,
        coverage_roots,
        inventory,
        structure_counts,
    )


def _source_scan_spec(
    *,
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
    source_contents: Mapping[str, str],
    block_by_id: Mapping[str, Mapping[str, object]],
    coverage_roots: Sequence[str],
    inventory: Sequence[Mapping[str, object]],
    structure_counts: Sequence[Mapping[str, object]],
    assigned_root_ids: Sequence[str],
    sequence: int,
) -> dict[str, object]:
    logical_shard_id = f"source-scan-{sequence:03d}"
    input_revision_sha256 = sha256_bytes(canonical_json_bytes(input_revision))
    instruction_bindings = [
        _instruction_binding("prompts/fragments/roles/author.md"),
        _instruction_binding("prompts/fragments/outputs/author-result.md"),
        _instruction_binding("prompts/stage1-source-scan.md"),
        _instruction_binding("references/source-authority.md"),
    ]
    packet = {
        "contract": "ai-sow-source-scan-packet-v1",
        "actionKind": "SOURCE_SCAN",
        "inputRevisionSha256": input_revision_sha256,
        "baseCandidateSha256": state["baseCandidateSha256"],
        "sourceBlockIds": list(assigned_root_ids),
        "coverageRootIds": list(assigned_root_ids),
        "allCoverageRootIds": list(coverage_roots),
        "fullBlockInventory": [dict(item) for item in inventory],
        "sourceStructureCounts": [dict(item) for item in structure_counts],
        "requiredCheckIds": list(SOURCE_SCAN_REQUIRED_CHECK_IDS),
        "allowedWriteCollections": ["inputItems"],
        "instructionBindings": instruction_bindings,
    }
    evidence = []
    for root_id in assigned_root_ids:
        block = block_by_id[root_id]
        evidence.append(
            {
                "evidenceId": root_id,
                "locator": block["locator"],
                "content": source_contents[root_id],
                "sha256": block["contentSha256"],
            }
        )
    return {
        "logicalShardId": logical_shard_id,
        "stage": "EPIC_FEATURE",
        "role": "AUTHOR",
        "promptId": "stage1-source-scan-v1",
        "promptPath": "prompts/stage1-source-scan.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/source-authority.md",
        ],
        "evidenceCatalog": evidence,
        "packet": packet,
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def _action_error(
    action_kind: str,
    outcome: str,
    code: str,
    message: str,
    path: str,
    *,
    category: str = "CONTRACT_UNSUPPORTED",
) -> dict[str, object]:
    diagnostic = _diagnostic(code, message, path)
    return {
        "outcome": outcome,
        "actionKind": action_kind,
        "specs": [],
        "estimatedInitialPacketTokens": [],
        "diagnostics": [_diagnostic_value(diagnostic, category=category)],
    }


def _scope_material(
    state: Mapping[str, object],
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    list[Mapping[str, object]],
    dict[str, str],
    dict[str, str],
]:
    input_revision = state.get("inputRevision")
    base_candidate = state.get("baseCandidate")
    if not (
        state.get("contract") == "ai-sow-scope-compiler-state-v1"
        and isinstance(input_revision, Mapping)
        and isinstance(base_candidate, Mapping)
        and state.get("baseCandidateSha256")
        == sha256_bytes(canonical_json_bytes(base_candidate))
    ):
        raise ValueError("scope compiler state 绑定无效")
    if validate_contract(
        input_revision,
        "input-revision.schema.json",
        NEXT_SCHEMA_REGISTRY,
    ):
        raise ValueError("input revision 合同无效")
    if validate_contract(
        base_candidate,
        "sow-model.schema.json",
        NEXT_SCHEMA_REGISTRY,
    ):
        raise ValueError("base candidate 合同无效")
    input_items = _mappings(base_candidate.get("inputItems"))
    if not input_items:
        raise ValueError("scope proposal 缺少 input items")
    item_ids = [item.get("inputItemId") for item in input_items]
    if not all(isinstance(item_id, str) for item_id in item_ids) or len(
        item_ids
    ) != len(set(item_ids)):
        raise ValueError("input item inventory 无效")
    source_role_by_id = {
        str(source["sourceId"]): str(source["role"])
        for source in _mappings(input_revision.get("sources"))
    }
    source_status_by_id = {
        str(source["sourceId"]): str(source["status"])
        for source in _mappings(input_revision.get("sources"))
    }
    return (
        input_revision,
        base_candidate,
        input_items,
        source_role_by_id,
        source_status_by_id,
    )


def _scope_proposal_spec(
    *,
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
    input_items: Sequence[Mapping[str, object]],
    source_role_by_id: Mapping[str, str],
    assigned_item_ids: Sequence[str],
    sequence: int,
) -> dict[str, object]:
    item_by_id = {str(item["inputItemId"]): item for item in input_items}
    all_ids = [str(item["inputItemId"]) for item in input_items]
    logical_shard_id = f"scope-proposal-{sequence:03d}"
    instruction_bindings = [
        _instruction_binding("prompts/fragments/roles/author.md"),
        _instruction_binding("prompts/fragments/outputs/author-result.md"),
        _instruction_binding("prompts/stage1-scope-proposal.md"),
        _instruction_binding("references/source-authority.md"),
        _instruction_binding("references/epic-authoring.md"),
        _instruction_binding("references/feature-authoring.md"),
        _instruction_binding("references/technical-work-classification.md"),
        _instruction_binding("references/delivery-lifecycle-policy.md"),
    ]
    boundary_summaries = [
        {
            "inputItemId": str(item["inputItemId"]),
            "kind": item["kind"],
            "applicableScopes": list(item["applicableScopes"]),
        }
        for item in input_items
    ]
    packet = {
        "contract": "ai-sow-scope-proposal-packet-v1",
        "actionKind": "SCOPE_PROPOSAL",
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(input_revision)
        ),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "inputItemIdInventory": all_ids,
        "assignedInputItemIds": list(assigned_item_ids),
        "localInputItems": [
            deepcopy(dict(item_by_id[item_id])) for item_id in assigned_item_ids
        ],
        "boundarySummaries": boundary_summaries,
        "sourceRoleById": dict(source_role_by_id),
        "requiredCheckIds": list(SCOPE_PROPOSAL_REQUIRED_CHECK_IDS),
        "allowedWriteCollections": [],
        "mayFinalizeFeatureOwnership": False,
        "instructionBindings": instruction_bindings,
    }
    evidence = [
        {
            "evidenceId": item_id,
            "locator": item_by_id[item_id]["sourceRefs"][0]["locator"],
            "content": item_by_id[item_id]["text"],
            "sha256": sha256_bytes(str(item_by_id[item_id]["text"]).encode("utf-8")),
        }
        for item_id in assigned_item_ids
    ]
    return {
        "logicalShardId": logical_shard_id,
        "stage": "EPIC_FEATURE",
        "role": "AUTHOR",
        "promptId": "stage1-scope-proposal-v1",
        "promptPath": "prompts/stage1-scope-proposal.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/source-authority.md",
            "references/epic-authoring.md",
            "references/feature-authoring.md",
            "references/technical-work-classification.md",
            "references/delivery-lifecycle-policy.md",
        ],
        "evidenceCatalog": evidence,
        "packet": packet,
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }


def _prepare_scope_proposal(
    state: Mapping[str, object],
) -> Mapping[str, object]:
    try:
        (
            input_revision,
            _base_candidate,
            input_items,
            source_role_by_id,
            _source_status_by_id,
        ) = _scope_material(state)
    except (KeyError, TypeError, ValueError):
        return _action_error(
            "SCOPE_PROPOSAL",
            "CONTRACT_UNSUPPORTED",
            "SCOPE_PROPOSAL_STATE_INVALID",
            "Scope Proposal 输入、candidate 或来源角色绑定无效。",
            "/state",
        )
    token_budget = state.get("maxInitialPacketTokens")
    if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1:
        return _action_error(
            "SCOPE_PROPOSAL",
            "CONTRACT_UNSUPPORTED",
            "SCOPE_PROPOSAL_STATE_INVALID",
            "Scope Proposal 初始 packet token 预算无效。",
            "/maxInitialPacketTokens",
        )
    input_ids = [str(item["inputItemId"]) for item in input_items]
    global_material = {
        "inputItemIdInventory": input_ids,
        "boundarySummaries": [
            {
                "inputItemId": item["inputItemId"],
                "kind": item["kind"],
                "applicableScopes": item["applicableScopes"],
            }
            for item in input_items
        ],
    }
    if _estimated_tokens(global_material) >= token_budget:
        return _action_error(
            "SCOPE_PROPOSAL",
            "CONTRACT_UNSUPPORTED",
            "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
            "最小全量 InputItem inventory 与边界摘要超过安全上下文预算。",
            "/baseCandidate/inputItems",
        )
    shard_ids: list[list[str]] = []
    current: list[str] = []
    for input_id in input_ids:
        candidate_ids = [*current, input_id]
        candidate_spec = _scope_proposal_spec(
            state=state,
            input_revision=input_revision,
            input_items=input_items,
            source_role_by_id=source_role_by_id,
            assigned_item_ids=candidate_ids,
            sequence=len(shard_ids) + 1,
        )
        measured = _estimated_tokens(
            {
                "logicalShardId": candidate_spec["logicalShardId"],
                "payload": candidate_spec["packet"],
                "evidenceCatalog": candidate_spec["evidenceCatalog"],
            }
        )
        if current and (measured > token_budget or len(candidate_ids) > 3):
            shard_ids.append(current)
            current = [input_id]
        else:
            current = candidate_ids
    if current:
        shard_ids.append(current)
    specs = [
        _scope_proposal_spec(
            state=state,
            input_revision=input_revision,
            input_items=input_items,
            source_role_by_id=source_role_by_id,
            assigned_item_ids=item_ids,
            sequence=index,
        )
        for index, item_ids in enumerate(shard_ids, 1)
    ]
    estimates = [
        _estimated_tokens(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
        for spec in specs
    ]
    if len(specs) > 8 or any(value > token_budget for value in estimates):
        return _action_error(
            "SCOPE_PROPOSAL",
            "CONTRACT_UNSUPPORTED",
            "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
            "Scope Proposal 无法在物理 shard 上限内容纳全量 inventory。",
            "/baseCandidate/inputItems",
        )
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "SCOPE_PROPOSAL",
        "inputItemIds": input_ids,
        "inventorySha256": sha256_bytes(canonical_json_bytes(global_material)),
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": [],
    }


def prepare_action(
    state: Mapping[str, object],
    action_kind: str,
) -> Mapping[str, object]:
    if action_kind == "SCOPE_PROPOSAL":
        return _prepare_scope_proposal(state)
    if action_kind == "SCOPE_JOIN":
        return _prepare_scope_join(state)
    if action_kind != "SOURCE_SCAN":
        return _source_scan_error(
            "COMPILER_ACTION_KIND_UNSUPPORTED",
            "当前 Scope Compiler 尚不支持该 action kind。",
            "/actionKind",
        )
    try:
        (
            input_revision,
            source_contents,
            blocks,
            coverage_roots,
            inventory,
            structure_counts,
        ) = _source_scan_material(state)
    except (KeyError, TypeError, ValueError):
        return _source_scan_error(
            "SOURCE_SCAN_STATE_INVALID",
            "Source Scan 输入、candidate 或来源内容绑定无效。",
            "/state",
        )
    token_budget = state.get("maxInitialPacketTokens")
    if (
        not isinstance(token_budget, int)
        or isinstance(token_budget, bool)
        or token_budget < 1
    ):
        return _source_scan_error(
            "SOURCE_SCAN_STATE_INVALID",
            "Source Scan 初始 packet token 预算无效。",
            "/maxInitialPacketTokens",
        )
    block_by_id = {str(block["blockId"]): block for block in blocks}
    common_inventory = {
        "coverageRootIds": coverage_roots,
        "fullBlockInventory": inventory,
        "sourceStructureCounts": structure_counts,
    }
    if _estimated_tokens(common_inventory) >= token_budget:
        return _source_scan_error(
            "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
            "最小全量 source block inventory 与结构计数超过安全上下文预算。",
            "/inputRevision/blocks",
        )

    shard_root_ids: list[list[str]] = []
    current: list[str] = []
    for root_id in coverage_roots:
        candidate_roots = [*current, root_id]
        candidate_spec = _source_scan_spec(
            state=state,
            input_revision=input_revision,
            source_contents=source_contents,
            block_by_id=block_by_id,
            coverage_roots=coverage_roots,
            inventory=inventory,
            structure_counts=structure_counts,
            assigned_root_ids=candidate_roots,
            sequence=len(shard_root_ids) + 1,
        )
        packet_measure = {
            "logicalShardId": candidate_spec["logicalShardId"],
            "payload": candidate_spec["packet"],
            "evidenceCatalog": candidate_spec["evidenceCatalog"],
        }
        if current and _estimated_tokens(packet_measure) > token_budget:
            shard_root_ids.append(current)
            current = [root_id]
        else:
            current = candidate_roots
    if current:
        shard_root_ids.append(current)
    specs = [
        _source_scan_spec(
            state=state,
            input_revision=input_revision,
            source_contents=source_contents,
            block_by_id=block_by_id,
            coverage_roots=coverage_roots,
            inventory=inventory,
            structure_counts=structure_counts,
            assigned_root_ids=assigned,
            sequence=index,
        )
        for index, assigned in enumerate(shard_root_ids, 1)
    ]
    estimates = [
        _estimated_tokens(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
        for spec in specs
    ]
    if len(specs) > 8 or any(value > token_budget for value in estimates):
        return _source_scan_error(
            "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
            "Source Scan 无法在物理 shard 上限内容纳全量 inventory 与分配 block。",
            "/inputRevision/blocks",
        )
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "SOURCE_SCAN",
        "coverageRootIds": list(coverage_roots),
        "inventorySha256": sha256_bytes(canonical_json_bytes(common_inventory)),
        "specs": specs,
        "estimatedInitialPacketTokens": estimates,
        "diagnostics": [],
    }


def _source_scan_packet_sha256(spec: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "logicalShardId": spec["logicalShardId"],
                "payload": spec["packet"],
                "evidenceCatalog": spec["evidenceCatalog"],
            }
        )
    )


def _validate_source_scan_record(
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
    logical_shard_id = record.get("logicalShardId")
    spec = specs.get(str(logical_shard_id))
    if spec is None:
        diagnostics.append(
            _diagnostic(
                "SOURCE_SCAN_SHARD_UNKNOWN",
                "Source Scan record 不属于当前冻结 action group。",
                "/logicalShardId",
            )
        )
        return _sort_diagnostics(diagnostics)
    input_revision = state["inputRevision"]
    expected_bindings = {
        "runId": state["runId"],
        "packetSha256": _source_scan_packet_sha256(spec),
        "inputRevisionSha256": sha256_bytes(canonical_json_bytes(input_revision)),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
    }
    for field, expected in expected_bindings.items():
        if record.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_SCAN_RECORD_BINDING_MISMATCH",
                    "Source Scan record 与当前 revision、candidate、packet 或模型配置不匹配。",
                    f"/{field}",
                )
            )
    if record.get("status") != "SUCCESS":
        diagnostics.append(
            _diagnostic(
                "SOURCE_SCAN_RECORD_NOT_SUCCESSFUL",
                "Source Scan 只接受已成功封存的 ActionRecord。",
                "/status",
            )
        )
    submission = record.get("submission")
    if not isinstance(submission, Mapping) or submission.get("resultKind") != (
        "SOURCE_SCAN_PATCH"
    ):
        diagnostics.append(
            _diagnostic(
                "SOURCE_SCAN_RESULT_KIND_INVALID",
                "Source Scan 必须返回 SOURCE_SCAN_PATCH。",
                "/submission/resultKind",
            )
        )
        return _sort_diagnostics(diagnostics)
    assigned = tuple(spec["packet"]["coverageRootIds"])
    coverage = _mappings(submission.get("blockCoverage"))
    covered_ids = [str(item.get("blockId")) for item in coverage]
    if len(covered_ids) != len(set(covered_ids)) or set(covered_ids) != set(
        assigned
    ):
        diagnostics.append(
            _diagnostic(
                "SOURCE_BLOCK_COVERAGE_INCOMPLETE",
                "每个分配的 source coverage root 必须恰好有一个 READ 或 PARSE_ISSUE 处置。",
                "/submission/blockCoverage",
            )
        )
    reviewed = submission.get("reviewedEvidenceIds")
    if not isinstance(reviewed, list) or set(reviewed) != set(assigned):
        diagnostics.append(
            _diagnostic(
                "SOURCE_REVIEWED_EVIDENCE_MISMATCH",
                "reviewedEvidenceIds 必须精确覆盖当前 shard 分配的 source blocks。",
                "/submission/reviewedEvidenceIds",
            )
        )
    self_check = submission.get("selfCheck")
    completed = self_check.get("completedCheckIds") if isinstance(self_check, Mapping) else None
    if completed != list(SOURCE_SCAN_REQUIRED_CHECK_IDS):
        diagnostics.append(
            _diagnostic(
                "SOURCE_SCAN_SELF_CHECK_INCOMPLETE",
                "Source Scan 必须完成全部冻结检查项。",
                "/submission/selfCheck/completedCheckIds",
            )
        )
    replacement = submission.get("replacementSet")
    if not isinstance(replacement, Mapping):
        return _sort_diagnostics(diagnostics)
    expected_hashes = replacement.get("expectedNodeHashes")
    deletes = replacement.get("deletes")
    upserts = replacement.get("upserts")
    if not (
        isinstance(expected_hashes, Mapping)
        and all(str(key).startswith("inputItems:") for key in expected_hashes)
        and isinstance(deletes, list)
        and all(
            isinstance(key, str) and key.startswith("inputItems:")
            for key in deletes
        )
        and isinstance(upserts, list)
    ):
        diagnostics.append(
            _diagnostic(
                "OWNER_WRITE_SCOPE_VIOLATION",
                "Source Scan replacement 只允许写 inputItems。",
                "/submission/replacementSet",
            )
        )
        return _sort_diagnostics(diagnostics)
    block_index = {
        str(block["blockId"]): block
        for block in _mappings(input_revision.get("blocks"))
    }
    for position, wrapper in enumerate(upserts):
        if not isinstance(wrapper, Mapping) or wrapper.get("collection") != (
            "inputItems"
        ):
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Source Scan 不得写 Epic、Feature、Story、Task 或其他集合。",
                    f"/submission/replacementSet/upserts/{position}",
                )
            )
            continue
        node = wrapper.get("node")
        if not (
            isinstance(node, Mapping)
            and set(node) == SOURCE_SCAN_INPUT_ITEM_FIELDS
            and node.get("kind") in SOURCE_SCAN_INPUT_KINDS
            and isinstance(node.get("inputItemId"), str)
            and isinstance(node.get("text"), str)
            and node.get("text")
            and all(
                isinstance(node.get(field), list)
                and all(isinstance(item, str) and item for item in node[field])
                for field in (
                    "conditions",
                    "thresholds",
                    "prohibitions",
                    "applicableScopes",
                )
            )
        ):
            diagnostics.append(
                _diagnostic(
                    "SOURCE_INPUT_ITEM_INVALID",
                    "Source Scan InputItem 字段、kind 或限定词无效。",
                    f"/submission/replacementSet/upserts/{position}/node",
                )
            )
            continue
        source_refs = _mappings(node.get("sourceRefs"))
        if not source_refs:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_REF_BINDING_INVALID",
                    "InputItem 必须保留至少一个精确 SourceRef。",
                    f"/submission/replacementSet/upserts/{position}/node/sourceRefs",
                )
            )
            continue
        for ref in source_refs:
            block_id = ref.get("blockId")
            block = block_index.get(str(block_id))
            if not (
                block_id in assigned
                and block is not None
                and ref
                == {
                    "sourceId": block.get("sourceId"),
                    "blockId": block.get("blockId"),
                    "sha256": block.get("contentSha256"),
                    "locator": block.get("locator"),
                }
            ):
                diagnostics.append(
                    _diagnostic(
                        "SOURCE_REF_BINDING_INVALID",
                        "InputItem SourceRef 必须精确绑定当前 shard 的 Input Revision block。",
                        f"/submission/replacementSet/upserts/{position}/node/sourceRefs",
                    )
                )
    return _sort_diagnostics(diagnostics)


def _validate_scope_proposal_record(
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
                "SCOPE_PROPOSAL_SHARD_UNKNOWN",
                "Scope Proposal record 不属于当前冻结 action group。",
                "/logicalShardId",
            )
        )
        return _sort_diagnostics(diagnostics)
    expected_bindings = {
        "runId": state["runId"],
        "packetSha256": _source_scan_packet_sha256(spec),
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(state["inputRevision"])
        ),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
    }
    for field, expected in expected_bindings.items():
        if record.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_PROPOSAL_RECORD_BINDING_MISMATCH",
                    "Scope Proposal record 与当前 revision、candidate、packet 或模型配置不匹配。",
                    f"/{field}",
                )
            )
    if record.get("status") != "SUCCESS":
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_RECORD_NOT_SUCCESSFUL",
                "Scope Proposal 只接受已成功封存的 ActionRecord。",
                "/status",
            )
        )
    submission = record.get("submission")
    if not isinstance(submission, Mapping) or submission.get("resultKind") != (
        "SCOPE_PROPOSAL"
    ):
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_RESULT_KIND_INVALID",
                "Scope Proposal 必须返回 SCOPE_PROPOSAL。",
                "/submission/resultKind",
            )
        )
        return _sort_diagnostics(diagnostics)
    if record.get("submissionSha256") != sha256_bytes(
        canonical_json_bytes(submission)
    ):
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_SUBMISSION_HASH_MISMATCH",
                "Scope Proposal submission hash 与内容不匹配。",
                "/submissionSha256",
            )
        )
    assigned = list(spec["packet"]["assignedInputItemIds"])
    if submission.get("inputItemIds") != assigned:
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_INPUT_COVERAGE_MISMATCH",
                "Scope Proposal inputItemIds 必须按冻结顺序精确覆盖本 shard。",
                "/submission/inputItemIds",
            )
        )
    if submission.get("reviewedEvidenceIds") != assigned:
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_EVIDENCE_MISMATCH",
                "Scope Proposal 必须复核本 shard 的全部 InputItem evidence。",
                "/submission/reviewedEvidenceIds",
            )
        )
    boundary_candidates = _mappings(submission.get("boundaryCandidates"))
    covered = [
        str(input_id)
        for boundary in boundary_candidates
        for input_id in boundary.get("inputItemIds", [])
        if isinstance(input_id, str)
    ]
    if sorted(covered) != sorted(assigned) or len(covered) != len(set(covered)):
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_BOUNDARY_COVERAGE_MISMATCH",
                "每个分配的 InputItem 必须恰好进入一个候选边界。",
                "/submission/boundaryCandidates",
            )
        )
    boundary_ids = [str(item.get("boundaryId")) for item in boundary_candidates]
    if len(boundary_ids) != len(set(boundary_ids)):
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_BOUNDARY_ID_DUPLICATE",
                "候选边界 ID 在 shard 内必须唯一。",
                "/submission/boundaryCandidates",
            )
        )
    global_ids = set(spec["packet"]["inputItemIdInventory"])
    for position, affinity in enumerate(
        _mappings(submission.get("crossShardAffinities"))
    ):
        affinity_ids = affinity.get("inputItemIds")
        if not isinstance(affinity_ids, list) or not set(affinity_ids) <= global_ids:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_PROPOSAL_AFFINITY_UNKNOWN_INPUT",
                    "跨 shard affinity 只能引用全量 InputItem inventory。",
                    f"/submission/crossShardAffinities/{position}/inputItemIds",
                )
            )
    self_check = submission.get("selfCheck")
    completed = (
        self_check.get("completedCheckIds")
        if isinstance(self_check, Mapping)
        else None
    )
    if completed != list(SCOPE_PROPOSAL_REQUIRED_CHECK_IDS):
        diagnostics.append(
            _diagnostic(
                "SCOPE_PROPOSAL_SELF_CHECK_INCOMPLETE",
                "Scope Proposal 必须完成全部冻结检查项。",
                "/submission/selfCheck/completedCheckIds",
            )
        )
    return _sort_diagnostics(diagnostics)


def _proposal_group(
    state: Mapping[str, object],
) -> tuple[Mapping[str, object], dict[str, Mapping[str, object]], tuple[Diagnostic, ...]]:
    proposal_state = {
        **state,
        "maxInitialPacketTokens": state.get(
            "proposalMaxInitialPacketTokens",
            state.get("maxInitialPacketTokens"),
        ),
    }
    prepared = _prepare_scope_proposal(proposal_state)
    specs = _mappings(prepared.get("specs"))
    records = _mappings(state.get("proposalRecords"))
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for record in records:
        shard_id = str(record.get("logicalShardId"))
        duplicate = duplicate or shard_id in by_shard
        by_shard[shard_id] = record
    required = [str(spec["logicalShardId"]) for spec in specs]
    if (
        prepared.get("outcome") != "ACTION_REQUIRED"
        or duplicate
        or set(by_shard) != set(required)
    ):
        return (
            prepared,
            by_shard,
            (
                _diagnostic(
                    "SCOPE_PROPOSAL_GROUP_INCOMPLETE",
                    "Scope Join 要求每个冻结 proposal shard 的一条成功 record。",
                    "/proposalRecords",
                ),
            ),
        )
    diagnostics = tuple(
        diagnostic
        for shard_id in required
        for diagnostic in _validate_scope_proposal_record(
            proposal_state,
            prepared,
            by_shard[shard_id],
        )
    )
    return prepared, by_shard, _sort_diagnostics(diagnostics)


def _prepare_scope_join(state: Mapping[str, object]) -> Mapping[str, object]:
    try:
        (
            input_revision,
            base_candidate,
            input_items,
            source_role_by_id,
            source_status_by_id,
        ) = _scope_material(state)
    except (KeyError, TypeError, ValueError):
        return _action_error(
            "SCOPE_JOIN",
            "CONTRACT_UNSUPPORTED",
            "SCOPE_JOIN_STATE_INVALID",
            "Scope Join 输入、candidate 或来源角色绑定无效。",
            "/state",
        )
    conflict_ids = [
        str(item["inputItemId"])
        for item in input_items
        if item.get("kind") == "CONFLICT_CANDIDATE"
    ]
    if conflict_ids:
        diagnostic = _diagnostic(
            "SOURCE_SEMANTIC_CONFLICT",
            "来源存在语义冲突，必须由输入 Owner 明确裁决，不能静默选择优先来源。",
            "/baseCandidate/inputItems",
        )
        diagnostic = Diagnostic(
            code=diagnostic.code,
            message=diagnostic.message,
            path=diagnostic.path,
            details={"subjectIds": conflict_ids},
        )
        return {
            "outcome": "INPUT_REQUIRED",
            "actionKind": "SCOPE_JOIN",
            "specs": [],
            "estimatedInitialPacketTokens": [],
            "diagnostics": [
                _diagnostic_value(diagnostic, category="INPUT_REQUIRED")
            ],
        }
    proposal_prepared, proposals_by_shard, proposal_diagnostics = _proposal_group(
        state
    )
    if proposal_diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "actionKind": "SCOPE_JOIN",
            "specs": [],
            "estimatedInitialPacketTokens": [],
            "diagnostics": [
                _diagnostic_value(item) for item in proposal_diagnostics
            ],
        }
    token_budget = state.get("maxInitialPacketTokens")
    if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1:
        return _action_error(
            "SCOPE_JOIN",
            "CONTRACT_UNSUPPORTED",
            "SCOPE_JOIN_STATE_INVALID",
            "Scope Join 初始 packet token 预算无效。",
            "/maxInitialPacketTokens",
        )
    required_shards = [
        str(spec["logicalShardId"])
        for spec in _mappings(proposal_prepared.get("specs"))
    ]
    policy_path = SKILL_ROOT / "contracts" / "delivery-policy-v1.json"
    policies = json.loads(policy_path.read_text(encoding="utf-8"))
    instruction_bindings = [
        _instruction_binding("prompts/fragments/roles/author.md"),
        _instruction_binding("prompts/fragments/outputs/author-result.md"),
        _instruction_binding("prompts/stage1-scope-join.md"),
        _instruction_binding("references/source-authority.md"),
        _instruction_binding("references/epic-authoring.md"),
        _instruction_binding("references/feature-authoring.md"),
        _instruction_binding("references/technical-work-classification.md"),
        _instruction_binding("references/delivery-lifecycle-policy.md"),
        {
            "path": "contracts/delivery-policy-v1.json",
            "sha256": sha256_bytes(policy_path.read_bytes()),
        },
    ]
    input_ids = [str(item["inputItemId"]) for item in input_items]
    responsibility_boundary_ids = list(
        base_candidate.get("project", {}).get("responsibilityBoundaries", [])
    )
    packet = {
        "contract": "ai-sow-scope-join-packet-v1",
        "actionKind": "SCOPE_JOIN",
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(input_revision)
        ),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "inputItemIds": input_ids,
        "inputItems": [deepcopy(dict(item)) for item in input_items],
        "responsibilityBoundaryIds": responsibility_boundary_ids,
        "scopeProposals": [
            deepcopy(dict(proposals_by_shard[shard_id]["submission"]))
            for shard_id in required_shards
        ],
        "proposalRecordSha256s": [
            sha256_bytes(canonical_json_bytes(proposals_by_shard[shard_id]))
            for shard_id in required_shards
        ],
        "sourceRoleById": dict(source_role_by_id),
        "sourceStatusById": dict(source_status_by_id),
        "inputCounts": {
            "inputItems": len(input_items),
            "scopeProposals": len(required_shards),
            "sources": len(source_role_by_id),
        },
        "deliveryPolicy": policies,
        "requiredCheckIds": list(SCOPE_JOIN_REQUIRED_CHECK_IDS),
        "allowedWriteCollections": sorted(STAGE_1_JOIN_COLLECTIONS),
        "instructionBindings": instruction_bindings,
    }
    evidence = [
        {
            "evidenceId": str(item["inputItemId"]),
            "locator": item["sourceRefs"][0]["locator"],
            "content": item["text"],
            "sha256": sha256_bytes(str(item["text"]).encode("utf-8")),
        }
        for item in input_items
    ]
    spec = {
        "logicalShardId": "scope-join-001",
        "stage": "EPIC_FEATURE",
        "role": "AUTHOR",
        "promptId": "stage1-scope-join-v1",
        "promptPath": "prompts/stage1-scope-join.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/source-authority.md",
            "references/epic-authoring.md",
            "references/feature-authoring.md",
            "references/technical-work-classification.md",
            "references/delivery-lifecycle-policy.md",
            "contracts/delivery-policy-v1.json",
        ],
        "evidenceCatalog": evidence,
        "packet": packet,
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }
    estimate = _estimated_tokens(
        {
            "logicalShardId": spec["logicalShardId"],
            "payload": spec["packet"],
            "evidenceCatalog": spec["evidenceCatalog"],
        }
    )
    if estimate > token_budget:
        return _action_error(
            "SCOPE_JOIN",
            "CONTRACT_UNSUPPORTED",
            "GLOBAL_SCOPE_CAPACITY_EXCEEDED",
            "全局 Scope Join packet 超过安全上下文预算，禁止截断或局部合并。",
            "/baseCandidate/inputItems",
        )
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "SCOPE_JOIN",
        "inputItemIds": input_ids,
        "specs": [spec],
        "estimatedInitialPacketTokens": [estimate],
        "diagnostics": [],
    }


def _validate_scope_join_record(
    state: Mapping[str, object],
    prepared: Mapping[str, object],
    record: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    specs = _mappings(prepared.get("specs"))
    spec = specs[0] if len(specs) == 1 else None
    if spec is None or record.get("logicalShardId") != spec.get("logicalShardId"):
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_SHARD_UNKNOWN",
                "Scope Join record 不属于当前冻结 action。",
                "/logicalShardId",
            )
        )
        return _sort_diagnostics(diagnostics)
    expected_bindings = {
        "runId": state["runId"],
        "packetSha256": _source_scan_packet_sha256(spec),
        "inputRevisionSha256": sha256_bytes(
            canonical_json_bytes(state["inputRevision"])
        ),
        "baseCandidateSha256": state["baseCandidateSha256"],
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
    }
    for field, expected in expected_bindings.items():
        if record.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_JOIN_RECORD_BINDING_MISMATCH",
                    "Scope Join record 与当前 revision、candidate、packet 或模型配置不匹配。",
                    f"/{field}",
                )
            )
    if record.get("status") != "SUCCESS":
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_RECORD_NOT_SUCCESSFUL",
                "Scope Join 只接受已成功封存的 ActionRecord。",
                "/status",
            )
        )
    submission = record.get("submission")
    if not isinstance(submission, Mapping) or submission.get("resultKind") != "PATCH":
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_RESULT_KIND_INVALID",
                "Scope Join 必须返回 PATCH。",
                "/submission/resultKind",
            )
        )
        return _sort_diagnostics(diagnostics)
    if record.get("submissionSha256") != sha256_bytes(
        canonical_json_bytes(submission)
    ):
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_SUBMISSION_HASH_MISMATCH",
                "Scope Join submission hash 与内容不匹配。",
                "/submissionSha256",
            )
        )
    input_ids = list(prepared.get("inputItemIds", []))
    if submission.get("reviewedEvidenceIds") != input_ids:
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_EVIDENCE_MISMATCH",
                "Scope Join 必须复核全部 InputItem evidence。",
                "/submission/reviewedEvidenceIds",
            )
        )
    self_check = submission.get("selfCheck")
    completed = (
        self_check.get("completedCheckIds")
        if isinstance(self_check, Mapping)
        else None
    )
    if completed != list(SCOPE_JOIN_REQUIRED_CHECK_IDS):
        diagnostics.append(
            _diagnostic(
                "SCOPE_JOIN_SELF_CHECK_INCOMPLETE",
                "Scope Join 必须完成全部冻结检查项。",
                "/submission/selfCheck/completedCheckIds",
            )
        )
    replacement = submission.get("replacementSet")
    if not isinstance(replacement, Mapping):
        return _sort_diagnostics(diagnostics)
    expected_hashes = replacement.get("expectedNodeHashes")
    upserts = replacement.get("upserts")
    deletes = replacement.get("deletes")
    if not (
        isinstance(expected_hashes, Mapping)
        and isinstance(upserts, list)
        and isinstance(deletes, list)
    ):
        return _sort_diagnostics(diagnostics)
    for key in [*expected_hashes, *deletes]:
        collection = str(key).split(":", 1)[0]
        if collection not in STAGE_1_JOIN_COLLECTIONS:
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Scope Join 只能写 Stage 1 区域。",
                    "/submission/replacementSet",
                )
            )
    for position, wrapper in enumerate(upserts):
        if not isinstance(wrapper, Mapping) or wrapper.get("collection") not in (
            STAGE_1_JOIN_COLLECTIONS
        ):
            diagnostics.append(
                _diagnostic(
                    "OWNER_WRITE_SCOPE_VIOLATION",
                    "Scope Join 不得写 Story、AC、Task 或其他 Owner 区域。",
                    f"/submission/replacementSet/upserts/{position}",
                )
            )
    input_revision = state["inputRevision"]
    source_by_id = {
        str(source["sourceId"]): source
        for source in _mappings(input_revision.get("sources"))
    }
    block_by_id = {
        str(block["blockId"]): block
        for block in _mappings(input_revision.get("blocks"))
    }
    for position, wrapper in enumerate(upserts):
        if not isinstance(wrapper, Mapping) or wrapper.get("collection") not in {
            "designItems",
            "integrations",
            "nfrs",
        }:
            continue
        node = wrapper.get("node")
        for ref in _mappings(node.get("sourceRefs") if isinstance(node, Mapping) else None):
            source = source_by_id.get(str(ref.get("sourceId")))
            block = block_by_id.get(str(ref.get("blockId")))
            exact_ref = (
                block is not None
                and ref
                == {
                    "sourceId": block.get("sourceId"),
                    "blockId": block.get("blockId"),
                    "sha256": block.get("contentSha256"),
                    "locator": block.get("locator"),
                }
            )
            if not (
                exact_ref
                and source is not None
                and source.get("role") in APPROVED_DESIGN_ROLES
                and source.get("status") == "APPROVED"
            ):
                diagnostics.append(
                    _diagnostic(
                        "DESIGN_SOURCE_AUTHORITY_VIOLATION",
                        "DesignItem、Integration 和 NFR 只能由批准 HLD/ADR 的精确 SourceRef 证明。",
                        f"/submission/replacementSet/upserts/{position}/node/sourceRefs",
                    )
                )
    if diagnostics:
        return _sort_diagnostics(diagnostics)
    outcome = apply_replacement(
        state["baseCandidate"],
        replacement,
        owner_stage="STAGE_1",
    )
    diagnostics.extend(outcome.diagnostics)
    if outcome.diagnostics:
        return _sort_diagnostics(diagnostics)
    candidate = outcome.candidate
    input_by_id = {
        str(item["inputItemId"]): item
        for item in _mappings(candidate.get("inputItems"))
    }
    closures = _mappings(candidate.get("scopeClosure"))
    closure_by_id = {
        str(item["inputItemId"]): item
        for item in closures
        if isinstance(item.get("inputItemId"), str)
    }
    if len(closures) != len(closure_by_id) or set(closure_by_id) != set(input_by_id):
        diagnostics.append(
            _diagnostic(
                "SCOPE_CLOSURE_NON_UNIQUE",
                "每个 InputItem 必须且只能有一个全局 Scope closure。",
                "/scopeClosure",
            )
        )
    for input_id, item in input_by_id.items():
        closure = closure_by_id.get(input_id)
        if closure is None:
            continue
        if closure.get("sourceRefs") != item.get("sourceRefs"):
            diagnostics.append(
                _diagnostic(
                    "SCOPE_CLOSURE_SOURCE_MISMATCH",
                    "Scope closure 必须保留 InputItem 的精确 SourceRef。",
                    f"/scopeClosure/{input_id}/sourceRefs",
                )
            )
        qualifiers = [
            value
            for field in (
                "conditions",
                "thresholds",
                "prohibitions",
                "applicableScopes",
            )
            for value in item.get(field, [])
            if isinstance(value, str)
        ]
        if closure.get("preservedQualifiers") != list(dict.fromkeys(qualifiers)):
            diagnostics.append(
                _diagnostic(
                    "SCOPE_QUALIFIER_COVERAGE_MISMATCH",
                    "Scope closure 必须按原顺序无损保留条件、阈值、禁止项和适用范围。",
                    f"/scopeClosure/{input_id}/preservedQualifiers",
                )
            )
        source_ids = {
            str(ref.get("sourceId")) for ref in _mappings(item.get("sourceRefs"))
        }
        is_requirement_union = item.get("kind") == "REQUIREMENT" and any(
            source_by_id.get(source_id, {}).get("role") == "PRD"
            or (
                source_by_id.get(source_id, {}).get("role") == "DEMO"
                and source_by_id.get(source_id, {}).get("status") == "SELECTED"
            )
            for source_id in source_ids
        )
        if is_requirement_union and closure.get("disposition") in {
            "OUT_OF_SCOPE",
            "CONFLICT",
        }:
            diagnostics.append(
                _diagnostic(
                    "REQUIREMENT_UNION_DROPPED",
                    "PRD 与选入 Demo 的需求并集不得被静默丢弃。",
                    f"/scopeClosure/{input_id}/disposition",
                )
            )
    policies = _mappings(candidate.get("policyInstances"))
    by_policy: dict[str, list[Mapping[str, object]]] = {}
    for item in policies:
        by_policy.setdefault(str(item.get("policyId")), []).append(item)
    for policy_id, inclusion in REQUIRED_POLICY_INCLUSIONS.items():
        values = by_policy.get(policy_id, [])
        if len(values) != 1 or values[0].get("inclusionPolicy") != inclusion:
            diagnostics.append(
                _diagnostic(
                    "DELIVERY_POLICY_INSTANCE_MISSING",
                    "实施型 SOW 必须精确实例化默认自动化与必需上线政策。",
                    f"/policyInstances/{policy_id}",
                )
            )
    migration_required = any(
        item.get("kind") != "EXCLUSION"
        and any(term in str(item.get("text", "")) for term in ("迁移", "持续同步"))
        for item in input_by_id.values()
    )
    migration_values = by_policy.get("policy-data-migration", [])
    if migration_required:
        if (
            len(migration_values) != 1
            or migration_values[0].get("inclusionPolicy") != "SOURCE_GATED"
            or not migration_values[0].get("sourceRefs")
        ):
            diagnostics.append(
                _diagnostic(
                    "DELIVERY_POLICY_INSTANCE_MISSING",
                    "来源明确提出迁移时必须实例化 SOURCE_GATED migration 政策。",
                    "/policyInstances/policy-data-migration",
                )
            )
    elif migration_values:
        diagnostics.append(
            _diagnostic(
                "DELIVERY_POLICY_SOURCE_GATE_VIOLATION",
                "来源未提出迁移或持续同步时不得实例化 migration 政策。",
                "/policyInstances/policy-data-migration",
            )
        )
    return _sort_diagnostics(diagnostics)


def accept_result(
    state: Mapping[str, object],
    record: Mapping[str, object],
) -> CompilerProgress:
    action_kind = str(state.get("actionKind", "SOURCE_SCAN"))
    prepared = prepare_action(state, action_kind)
    if prepared.get("outcome") != "ACTION_REQUIRED":
        diagnostic = _diagnostic(
            f"{action_kind}_PREPARE_FAILED",
            f"{action_kind} action 未成功冻结。",
            "/state",
        )
        return CompilerProgress("FAILED", (), (diagnostic,))
    if action_kind == "SCOPE_PROPOSAL":
        diagnostics = _validate_scope_proposal_record(state, prepared, record)
    elif action_kind == "SCOPE_JOIN":
        diagnostics = _validate_scope_join_record(state, prepared, record)
    else:
        diagnostics = _validate_source_scan_record(state, prepared, record)
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


def _apply_scope_proposal_group(
    state: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> CompilerResult:
    base_candidate = state.get("baseCandidate")
    if not isinstance(base_candidate, Mapping):
        diagnostic = _diagnostic(
            "SCOPE_PROPOSAL_STATE_INVALID",
            "Scope Proposal 缺少基础 candidate。",
            "/baseCandidate",
        )
        return CompilerResult({}, "", {}, (diagnostic,))
    prepared = _prepare_scope_proposal(state)
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
            "SCOPE_PROPOSAL_GROUP_INCOMPLETE",
            "Scope Proposal group 必须包含每个冻结 shard 的一条成功 record。",
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
        for diagnostic in _validate_scope_proposal_record(
            state,
            prepared,
            by_shard[shard_id],
        )
    )
    if diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    checkpoint = {
        "kind": "SCOPE_PROPOSAL",
        "inputItemIds": list(prepared["inputItemIds"]),
        "inventorySha256": prepared["inventorySha256"],
        "proposalRecordSha256s": [
            sha256_bytes(canonical_json_bytes(by_shard[shard_id]))
            for shard_id in required
        ],
    }
    return CompilerResult(
        deepcopy(dict(base_candidate)),
        sha256_bytes(canonical_json_bytes(base_candidate)),
        checkpoint,
        (),
    )


def _apply_scope_join_group(
    state: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> CompilerResult:
    base_candidate = state.get("baseCandidate")
    if not isinstance(base_candidate, Mapping):
        diagnostic = _diagnostic(
            "SCOPE_JOIN_STATE_INVALID",
            "Scope Join 缺少基础 candidate。",
            "/baseCandidate",
        )
        return CompilerResult({}, "", {}, (diagnostic,))
    prepared = _prepare_scope_join(state)
    if prepared.get("outcome") != "ACTION_REQUIRED" or len(records) != 1:
        diagnostic = _diagnostic(
            "SCOPE_JOIN_GROUP_INCOMPLETE",
            "Scope Join group 必须包含唯一冻结 action 的一条成功 record。",
            "/records",
        )
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            (diagnostic,),
        )
    record = records[0]
    diagnostics = _validate_scope_join_record(state, prepared, record)
    if diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            diagnostics,
        )
    submission = record["submission"]
    outcome = apply_replacement(
        base_candidate,
        submission["replacementSet"],
        owner_stage="STAGE_1",
    )
    if outcome.diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            outcome.diagnostics,
        )
    checkpoint = {
        "kind": "SCOPE_JOIN",
        "inputItemIds": list(prepared["inputItemIds"]),
        "coverageSha256": sha256_bytes(
            canonical_json_bytes(
                {
                    "inputItemIds": prepared["inputItemIds"],
                    "requiredCheckIds": list(SCOPE_JOIN_REQUIRED_CHECK_IDS),
                }
            )
        ),
        "recordSha256s": [sha256_bytes(canonical_json_bytes(record))],
    }
    return CompilerResult(
        outcome.candidate,
        outcome.candidate_sha256,
        checkpoint,
        (),
    )


SCOPE_CHECKPOINT_CHECK_IDS = (
    "SOURCE_SCAN_COMPLETE",
    "R1_SOURCE_PASS",
    "SCOPE_CLOSURE_COMPLETE",
    "DESIGN_COVERAGE_SUFFICIENT",
    "R1_SCOPE_PASS",
    "POLICY_DEFINITION_BOUND",
)


def _scope_source_manifest_sha256(input_revision: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "sources": input_revision.get("sources", []),
                "blocks": input_revision.get("blocks", []),
            }
        )
    )


def _scope_coverage_sha256(candidate: Mapping[str, object]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "inputItemIds": [
                    item.get("inputItemId")
                    for item in _mappings(candidate.get("inputItems"))
                ],
                "scopeClosure": candidate.get("scopeClosure", []),
                "designItems": candidate.get("designItems", []),
                "integrations": candidate.get("integrations", []),
                "nfrs": candidate.get("nfrs", []),
                "policyInstances": candidate.get("policyInstances", []),
            }
        )
    )


def _ordered_hashes(
    values: Sequence[Mapping[str, object]],
    *,
    order_field: str,
    payload_field: str | None = None,
) -> list[str]:
    ordered = sorted(values, key=lambda item: str(item.get(order_field, "")))
    return [
        sha256_bytes(
            canonical_json_bytes(
                item.get(payload_field) if payload_field is not None else item
            )
        )
        for item in ordered
    ]


def _scope_checkpoint_proof(
    state: Mapping[str, object],
    candidate: Mapping[str, object],
    input_revision: Mapping[str, object],
) -> tuple[dict[str, object], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    source_records = _mappings(state.get("actionRecords"))
    valid_source_records = [
        record
        for record in source_records
        if record.get("status") == "SUCCESS"
        and isinstance(record.get("submission"), Mapping)
        and record["submission"].get("resultKind") == "SOURCE_SCAN_PATCH"
        and not validate_contract(
            record,
            "action.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
    ]
    if not valid_source_records:
        diagnostics.append(
            _diagnostic(
                "SOURCE_SCAN_INCOMPLETE",
                "Stage 1 checkpoint 缺少成功且合同有效的 Source Scan ActionRecord。",
                "/actionRecords",
            )
        )
    source_results = _mappings(state.get("r1SourceResults"))
    normalized_source_results: list[Mapping[str, object]] = []
    for wrapper in source_results:
        result = wrapper.get("result")
        if isinstance(result, Mapping):
            normalized_source_results.append(result)
    roots: list[str] = []
    for block in _mappings(input_revision.get("blocks")):
        if block.get("extractionDisposition") == "DROPPED":
            continue
        root_id = block.get("primaryCoverageBlockId")
        if isinstance(root_id, str) and root_id not in roots:
            roots.append(root_id)
    audit_union = [
        root_id
        for wrapper in sorted(
            source_results,
            key=lambda item: str(item.get("logicalShardId", "")),
        )
        for root_id in (
            wrapper.get("result", {}).get("sourceAuditCoverageUnion", [])
            if isinstance(wrapper.get("result"), Mapping)
            else []
        )
        if isinstance(root_id, str)
    ]
    if (
        not normalized_source_results
        or any(
            result.get("kind") != "SOURCE_AUDIT"
            or result.get("decision") != "PASS"
            or validate_contract(
                result,
                "review-repair.schema.json",
                NEXT_SCHEMA_REGISTRY,
            )
            for result in normalized_source_results
        )
        or audit_union != roots
        or len(audit_union) != len(set(audit_union))
    ):
        diagnostics.append(
            _diagnostic(
                "R1_SOURCE_AUDIT_INCOMPLETE",
                "R1 Source Audit 必须 PASS 且 coverage union 精确覆盖全部来源 roots。",
                "/r1SourceResults",
            )
        )
    r1_scope_result = state.get("r1ScopeResult")
    candidate_projection_sha256 = owner_projection_sha256(candidate, "STAGE_1")
    ordered_audit_hashes = [
        {
            "logicalShardId": str(wrapper.get("logicalShardId")),
            "reviewResultSha256": sha256_bytes(
                canonical_json_bytes(wrapper.get("result"))
            ),
        }
        for wrapper in sorted(
            source_results,
            key=lambda item: str(item.get("logicalShardId", "")),
        )
        if isinstance(wrapper.get("result"), Mapping)
    ]
    expected_r1_coverage_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "coverageRootIds": roots,
                "orderedAuditResultHashes": ordered_audit_hashes,
                "candidateProjectionSha256": candidate_projection_sha256,
            }
        )
    )
    if not (
        isinstance(r1_scope_result, Mapping)
        and not validate_contract(
            r1_scope_result,
            "review-repair.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        and r1_scope_result.get("kind") == "SOURCE_SCOPE"
        and r1_scope_result.get("decision") == "PASS"
        and r1_scope_result.get("candidateProjectionSha256")
        == candidate_projection_sha256
        and r1_scope_result.get("coverageSha256")
        == expected_r1_coverage_sha256
        and r1_scope_result.get("sourceAuditCoverageUnion") == roots
        and r1_scope_result.get("completedCheckIds")
        == [
            "SOURCE_TO_INPUT",
            "SCOPE_CLOSURE",
            "TECHNICAL_CLASSIFICATION",
            "EPIC_FEATURE_BOUNDARY",
            "DESIGN_SUFFICIENCY",
            "SCOPE_EXPANSION",
            "DELIVERY_POLICY",
        ]
    ):
        diagnostics.append(
            _diagnostic(
                "R1_SCOPE_REVIEW_STALE",
                "R1 Scope Join 必须 PASS 并绑定当前 Stage 1 投影与全部 audit leaf。",
                "/r1ScopeResult",
            )
        )
    proof = {
        "sourceManifestSha256": _scope_source_manifest_sha256(input_revision),
        "ownerProjectionSha256": candidate_projection_sha256,
        "coverageSha256": _scope_coverage_sha256(candidate),
        "policyDefinitionSha256": input_revision.get("deliveryPolicySha256"),
        "actionRecordSha256s": _ordered_hashes(
            source_records,
            order_field="logicalShardId",
        ),
        "reviewResultSha256s": [
            *_ordered_hashes(
                source_results,
                order_field="logicalShardId",
                payload_field="result",
            ),
            *(
                [sha256_bytes(canonical_json_bytes(r1_scope_result))]
                if isinstance(r1_scope_result, Mapping)
                else []
            ),
        ],
    }
    return proof, _sort_diagnostics(diagnostics)


def _design_gap_question(
    candidate: Mapping[str, object],
    closure: Mapping[str, object],
) -> dict[str, object]:
    input_id = str(closure.get("inputItemId"))
    checked = [
        str(ref.get("blockId"))
        for ref in _mappings(closure.get("sourceRefs"))
        if isinstance(ref.get("blockId"), str)
    ]
    identity = sha256_bytes(
        canonical_json_bytes(
            {
                "candidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
                "inputItemId": input_id,
                "checkedEvidenceIds": checked,
            }
        )
    )[:16]
    return {
        "questionId": f"design-gap-{identity}",
        "subjectIds": [input_id],
        "question": "请在批准的 HLD/ADR 中补充该范围的目标系统、组件、集成、数据、部署、NFR 与责任边界。",
        "whyAsked": "需求范围已成立，但当前批准设计不足以支持 Story、验收和 Task 拆分。",
        "answerDetermines": [
            "Story 技术边界与验收依据",
            "Task 类型、责任和复杂度",
        ],
        "unansweredConsequence": "Stage 1 保持阻断，不生成 Story/AC 或正式 SOW。",
        "requiredSourceRole": "APPROVED_DESIGN",
        "checkedEvidenceIds": checked,
    }


def _mechanical_design_coverage_diagnostics(
    candidate: Mapping[str, object],
    input_revision: Mapping[str, object],
) -> tuple[Diagnostic, ...]:
    source_by_id = {
        str(source["sourceId"]): source
        for source in _mappings(input_revision.get("sources"))
    }
    block_by_id = {
        str(block["blockId"]): block
        for block in _mappings(input_revision.get("blocks"))
    }
    design_nodes: dict[str, Mapping[str, object]] = {}
    for collection, id_field in (
        ("designItems", "designItemId"),
        ("integrations", "integrationId"),
        ("nfrs", "nfrId"),
    ):
        for node in _mappings(candidate.get(collection)):
            node_id = node.get(id_field)
            if isinstance(node_id, str):
                design_nodes[node_id] = node

    def approved(ref: Mapping[str, object]) -> bool:
        source = source_by_id.get(str(ref.get("sourceId")))
        block = block_by_id.get(str(ref.get("blockId")))
        return bool(
            source is not None
            and source.get("role") in APPROVED_DESIGN_ROLES
            and source.get("status") == "APPROVED"
            and block is not None
            and ref
            == {
                "sourceId": block.get("sourceId"),
                "blockId": block.get("blockId"),
                "sha256": block.get("contentSha256"),
                "locator": block.get("locator"),
            }
        )

    diagnostics: list[Diagnostic] = []
    for closure in _mappings(candidate.get("scopeClosure")):
        if closure.get("mechanicalCoverage") != "COMPLETE":
            continue
        refs = list(_mappings(closure.get("sourceRefs")))
        for target_id in closure.get("targetNodeIds", []):
            target = design_nodes.get(str(target_id))
            if target is not None:
                refs.extend(_mappings(target.get("sourceRefs")))
        if not any(approved(ref) for ref in refs):
            diagnostics.append(
                _diagnostic(
                    "DESIGN_MECHANICAL_COVERAGE_INVALID",
                    "mechanicalCoverage=COMPLETE 必须由批准设计的可达精确 SourceRef 证明。",
                    f"/scopeClosure/{closure.get('inputItemId')}/mechanicalCoverage",
                )
            )
    return _sort_diagnostics(diagnostics)


def build_scope_closure_checkpoint(
    state: Mapping[str, object],
) -> Mapping[str, object]:
    candidate = state.get("candidate")
    input_revision = state.get("inputRevision")
    run_id = state.get("runId")
    if not (
        isinstance(candidate, Mapping)
        and isinstance(input_revision, Mapping)
        and isinstance(run_id, str)
    ):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": (
                _diagnostic(
                    "SCOPE_CHECKPOINT_STATE_INVALID",
                    "Stage 1 checkpoint 输入状态无效。",
                    "/state",
                ),
            ),
        }
    if validate_contract(
        input_revision,
        "input-revision.schema.json",
        NEXT_SCHEMA_REGISTRY,
    ):
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": (
                _diagnostic(
                    "SCOPE_CHECKPOINT_STATE_INVALID",
                    "Stage 1 checkpoint Input Revision 合同无效。",
                    "/inputRevision",
                ),
            ),
        }
    closures = _mappings(candidate.get("scopeClosure"))
    blocking = [
        item
        for item in closures
        if item.get("disposition") == "CONFLICT"
        or item.get("deliveryDisposition") == "BLOCKED"
    ]
    if blocking:
        return {
            "outcome": "INPUT_REQUIRED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": tuple(
                _diagnostic(
                    "SCOPE_CLOSURE_BLOCKED",
                    "Scope conflict 或 BLOCKED delivery disposition 不得进入 Stage 2。",
                    f"/scopeClosure/{item.get('inputItemId')}",
                )
                for item in blocking
            ),
        }
    design_gaps = [
        item
        for item in closures
        if item.get("designCoverageStatus") in {"MISSING", "CONFLICT"}
        or item.get("mechanicalCoverage") == "MISSING"
        or item.get("semanticSufficiency") in {"INSUFFICIENT", "NOT_REVIEWED"}
    ]
    if design_gaps:
        return {
            "outcome": "INPUT_REQUIRED",
            "checkpoint": None,
            "questions": [
                _design_gap_question(candidate, item) for item in design_gaps
            ],
            "diagnostics": tuple(
                _diagnostic(
                    "DESIGN_COVERAGE_INSUFFICIENT",
                    "设计机械覆盖或独立语义充分性未通过。",
                    f"/scopeClosure/{item.get('inputItemId')}/designCoverageStatus",
                )
                for item in design_gaps
            ),
        }
    model_diagnostics = validate_sow_model(
        candidate,
        "STAGE_1",
        registry=NEXT_SCHEMA_REGISTRY,
    )
    if model_diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": model_diagnostics,
        }
    mechanical_diagnostics = _mechanical_design_coverage_diagnostics(
        candidate,
        input_revision,
    )
    if mechanical_diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": mechanical_diagnostics,
        }
    proof, proof_diagnostics = _scope_checkpoint_proof(
        state,
        candidate,
        input_revision,
    )
    if proof_diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": proof_diagnostics,
        }
    checkpoint = {
        "contract": "ai-sow-stage-checkpoint-v1",
        "kind": "SCOPE_CLOSURE",
        "runId": run_id,
        "stage": "EPIC_FEATURE",
        "candidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        **proof,
        "upstreamCheckpointSha256s": list(
            state.get("upstreamCheckpointSha256s", [])
        ),
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(SCOPE_CHECKPOINT_CHECK_IDS),
        "decision": "PASS",
    }
    diagnostics = validate_contract(
        checkpoint,
        "stage-checkpoint.schema.json",
        NEXT_SCHEMA_REGISTRY,
    )
    if diagnostics:
        return {
            "outcome": "CONTRACT_UNSUPPORTED",
            "checkpoint": None,
            "questions": [],
            "diagnostics": diagnostics,
        }
    return {
        "outcome": "READY_FOR_STORY_AC",
        "checkpoint": checkpoint,
        "checkpointSha256": sha256_bytes(canonical_json_bytes(checkpoint)),
        "scopeProjectionSha256": proof["ownerProjectionSha256"],
        "questions": [],
        "diagnostics": (),
    }


def validate_scope_closure_checkpoint(
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
    candidate = state.get("candidate")
    input_revision = state.get("inputRevision")
    if not isinstance(candidate, Mapping) or not isinstance(input_revision, Mapping):
        diagnostics.append(
            _diagnostic(
                "SCOPE_CHECKPOINT_STATE_INVALID",
                "无法验证 Stage 1 checkpoint 的当前状态。",
                "/state",
            )
        )
        return _sort_diagnostics(diagnostics)
    proof, proof_diagnostics = _scope_checkpoint_proof(
        state,
        candidate,
        input_revision,
    )
    diagnostics.extend(proof_diagnostics)
    expected = {
        "runId": state.get("runId"),
        "sourceManifestSha256": proof["sourceManifestSha256"],
        "ownerProjectionSha256": proof["ownerProjectionSha256"],
        "coverageSha256": proof["coverageSha256"],
        "policyDefinitionSha256": proof["policyDefinitionSha256"],
        "actionRecordSha256s": proof["actionRecordSha256s"],
        "reviewResultSha256s": proof["reviewResultSha256s"],
        "upstreamCheckpointSha256s": list(
            state.get("upstreamCheckpointSha256s", [])
        ),
        "validatorContractSha256": sha256_bytes(
            (SKILL_ROOT / "contracts/sow-model.schema.json").read_bytes()
        ),
        "completedCheckIds": list(SCOPE_CHECKPOINT_CHECK_IDS),
    }
    for field, value in expected.items():
        if checkpoint.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "SCOPE_CHECKPOINT_BINDING_STALE",
                    "ScopeClosureCheckpoint 不再绑定当前 Stage 1 投影或证明闭包。",
                    f"/{field}",
                )
            )
    return _sort_diagnostics(diagnostics)


def apply_ready_group(
    state: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> CompilerResult:
    action_kind = str(state.get("actionKind", "SOURCE_SCAN"))
    if action_kind == "SCOPE_PROPOSAL":
        return _apply_scope_proposal_group(state, records)
    if action_kind == "SCOPE_JOIN":
        return _apply_scope_join_group(state, records)
    base_candidate = state.get("baseCandidate")
    if not isinstance(base_candidate, Mapping):
        diagnostic = _diagnostic(
            "SOURCE_SCAN_STATE_INVALID",
            "Source Scan 缺少基础 candidate。",
            "/baseCandidate",
        )
        return CompilerResult({}, "", {}, (diagnostic,))
    prepared = prepare_action(state, "SOURCE_SCAN")
    specs = _mappings(prepared.get("specs"))
    required = [str(spec["logicalShardId"]) for spec in specs]
    by_shard: dict[str, Mapping[str, object]] = {}
    duplicate = False
    for record in records:
        shard_id = str(record.get("logicalShardId"))
        if shard_id in by_shard:
            duplicate = True
        by_shard[shard_id] = record
    if (
        prepared.get("outcome") != "ACTION_REQUIRED"
        or duplicate
        or set(by_shard) != set(required)
    ):
        diagnostic = _diagnostic(
            "SOURCE_SCAN_GROUP_INCOMPLETE",
            "Source Scan group 必须包含每个冻结 logical shard 的一条成功 record。",
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
        for diagnostic in _validate_source_scan_record(
            state,
            prepared,
            by_shard[shard_id],
        )
    )
    if diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    upserts: list[object] = []
    deletes: list[object] = []
    expected_hashes: dict[str, object] = {}
    for shard_id in required:
        submission = by_shard[shard_id]["submission"]
        replacement = submission["replacementSet"]
        upserts.extend(deepcopy(replacement["upserts"]))
        deletes.extend(deepcopy(replacement["deletes"]))
        for key, value in replacement["expectedNodeHashes"].items():
            if key in expected_hashes and expected_hashes[key] != value:
                diagnostic = _diagnostic(
                    "SOURCE_SCAN_EXPECTED_HASH_CONFLICT",
                    "Source Scan sibling 对同一既有 InputItem 的 expected hash 不一致。",
                    f"/expectedNodeHashes/{key}",
                )
                return CompilerResult(
                    deepcopy(dict(base_candidate)),
                    sha256_bytes(canonical_json_bytes(base_candidate)),
                    {},
                    (diagnostic,),
                )
            expected_hashes[str(key)] = value
    outcome = apply_replacement(
        base_candidate,
        {
            "expectedNodeHashes": expected_hashes,
            "upserts": upserts,
            "deletes": deletes,
        },
        owner_stage="STAGE_1_SOURCE_SCAN",
    )
    if outcome.diagnostics:
        return CompilerResult(
            deepcopy(dict(base_candidate)),
            sha256_bytes(canonical_json_bytes(base_candidate)),
            {},
            outcome.diagnostics,
        )
    coverage_root_ids = list(prepared["coverageRootIds"])
    checkpoint = {
        "kind": "SOURCE_SCAN",
        "coverageRootIds": coverage_root_ids,
        "coverageSha256": sha256_bytes(
            canonical_json_bytes(
                {
                    "coverageRootIds": coverage_root_ids,
                    "requiredCheckIds": list(SOURCE_SCAN_REQUIRED_CHECK_IDS),
                }
            )
        ),
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


def prepare_repair_action(
    state: Mapping[str, object],
    repair_plan: Mapping[str, object],
    findings: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    candidate = state.get("baseCandidate")
    waves = _mappings(repair_plan.get("waves"))
    if (
        not isinstance(candidate, Mapping)
        or repair_plan.get("earliestOwner") != "STAGE_1"
        or len(waves) != 1
        or waves[0].get("resumePhase") != "EPIC_FEATURE"
    ):
        return _action_error(
            "REPAIR",
            "CONTRACT_UNSUPPORTED",
            "STAGE_1_REPAIR_PLAN_INVALID",
            "Stage 1 repair 必须绑定唯一、可执行的 Owner wave。",
            "/repairPlan",
        )
    wave = waves[0]
    finding_ids = list(wave["findingIds"])
    by_id = {
        str(item.get("findingId")): item
        for item in findings
        if item.get("owner") == "STAGE_1"
    }
    if set(finding_ids) != set(by_id):
        return _action_error(
            "REPAIR",
            "CONTRACT_UNSUPPORTED",
            "STAGE_1_REPAIR_FINDINGS_INVALID",
            "Stage 1 repair wave 与 finding 集合不一致。",
            "/findings",
        )
    evidence = [
        {
            "evidenceId": finding_id,
            "locator": f"review-finding:{finding_id}",
            "content": canonical_json_bytes(by_id[finding_id]).decode("utf-8"),
            "sha256": sha256_bytes(canonical_json_bytes(by_id[finding_id])),
        }
        for finding_id in finding_ids
    ]
    spec = {
        "logicalShardId": str(wave["repairWaveId"]),
        "stage": "REPAIR",
        "role": "AUTHOR",
        "promptId": "repair-stage1-v1",
        "promptPath": "prompts/repair-stage1.md",
        "resultPayloadSchema": "contracts/action.schema.json",
        "referencePaths": [
            "prompts/fragments/roles/author.md",
            "prompts/fragments/outputs/author-result.md",
            "references/epic-authoring.md",
            "references/feature-authoring.md",
            "references/source-authority.md",
        ],
        "evidenceCatalog": evidence,
        "packet": {
            "repairPlan": deepcopy(dict(repair_plan)),
            "findings": [deepcopy(dict(by_id[item])) for item in finding_ids],
            "baseCandidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
            "editableNodeIds": list(wave["editableNodeIds"]),
            "contextNodeIds": list(wave["contextNodeIds"]),
            "lockedNodeIds": list(wave["lockedNodeIds"]),
            "candidate": deepcopy(dict(candidate)),
            "requiredCheckIds": list(STAGE_1_REPAIR_CHECK_IDS),
            "allowedWriteCollections": sorted(STAGE_1_JOIN_COLLECTIONS),
        },
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "maxOutputTokens": state["maxOutputTokens"],
    }
    return {
        "outcome": "ACTION_REQUIRED",
        "actionKind": "REPAIR",
        "specs": [spec],
        "diagnostics": (),
    }


def apply_repair_action_group(
    state: Mapping[str, object],
    repair_plan: Mapping[str, object],
    findings: Sequence[Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
) -> CompilerResult:
    candidate = state.get("baseCandidate")
    if not isinstance(candidate, Mapping):
        return CompilerResult(
            {},
            "",
            {},
            (_diagnostic("STAGE_1_REPAIR_STATE_INVALID", "repair 缺少基础 candidate。", "/baseCandidate"),),
        )
    prepared = prepare_repair_action(state, repair_plan, findings)
    specs = _mappings(prepared.get("specs"))
    if prepared.get("outcome") != "ACTION_REQUIRED" or len(specs) != 1 or len(records) != 1:
        return CompilerResult(
            deepcopy(dict(candidate)),
            sha256_bytes(canonical_json_bytes(candidate)),
            {},
            (_diagnostic("STAGE_1_REPAIR_GROUP_INCOMPLETE", "repair group 必须包含唯一成功 record。", "/records"),),
        )
    spec = specs[0]
    record = records[0]
    diagnostics = list(validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY))
    expected = {
        "runId": state["runId"],
        "logicalShardId": spec["logicalShardId"],
        "packetSha256": sha256_bytes(
            canonical_json_bytes(
                {
                    "logicalShardId": spec["logicalShardId"],
                    "payload": spec["packet"],
                    "evidenceCatalog": spec["evidenceCatalog"],
                }
            )
        ),
        "inputRevisionSha256": sha256_bytes(canonical_json_bytes(state["inputRevision"])),
        "baseCandidateSha256": sha256_bytes(canonical_json_bytes(candidate)),
        "modelProfileId": state["modelProfileId"],
        "modelConfigSha256": state["modelConfigSha256"],
        "status": "SUCCESS",
    }
    for field, value in expected.items():
        if record.get(field) != value:
            diagnostics.append(
                _diagnostic(
                    "STAGE_1_REPAIR_RECORD_BINDING_MISMATCH",
                    "repair record 未绑定当前 plan、candidate、revision 或模型配置。",
                    f"/{field}",
                )
            )
    submission = record.get("submission")
    if not isinstance(submission, Mapping) or submission.get("resultKind") != "PATCH":
        diagnostics.append(
            _diagnostic("STAGE_1_REPAIR_RESULT_INVALID", "repair 必须返回 PATCH。", "/submission")
        )
        return CompilerResult(
            deepcopy(dict(candidate)),
            sha256_bytes(canonical_json_bytes(candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    if submission.get("reviewedEvidenceIds") != list(
        spec["packet"]["repairPlan"]["waves"][0]["findingIds"]
    ):
        diagnostics.append(
            _diagnostic("STAGE_1_REPAIR_EVIDENCE_MISMATCH", "repair 必须覆盖全部 finding。", "/submission/reviewedEvidenceIds")
        )
    self_check = submission.get("selfCheck")
    if not isinstance(self_check, Mapping) or self_check.get("completedCheckIds") != list(
        STAGE_1_REPAIR_CHECK_IDS
    ):
        diagnostics.append(
            _diagnostic("STAGE_1_REPAIR_SELF_CHECK_INCOMPLETE", "repair 必须完成全部冻结检查。", "/submission/selfCheck")
        )
    replacement = submission.get("replacementSet")
    editable = set(spec["packet"]["editableNodeIds"])
    targets: set[str] = set()
    if isinstance(replacement, Mapping):
        for wrapper in _mappings(replacement.get("upserts")):
            collection = wrapper.get("collection")
            node = wrapper.get("node")
            id_field = NODE_COLLECTIONS.get(str(collection))
            if isinstance(node, Mapping) and id_field is not None:
                node_id = node.get(id_field)
                if isinstance(node_id, str):
                    targets.add(node_id)
        deletes = replacement.get("deletes")
        if isinstance(deletes, list):
            targets.update(
                str(item).split(":", 1)[1]
                for item in deletes
                if isinstance(item, str) and ":" in item
            )
    if not targets or not targets <= editable:
        diagnostics.append(
            _diagnostic(
                "STAGE_1_REPAIR_SCOPE_VIOLATION",
                "repair 必须且只能修改 wave 的 editable nodes。",
                "/submission/replacementSet",
            )
        )
    if diagnostics or not isinstance(replacement, Mapping):
        return CompilerResult(
            deepcopy(dict(candidate)),
            sha256_bytes(canonical_json_bytes(candidate)),
            {},
            _sort_diagnostics(diagnostics),
        )
    outcome = apply_replacement(candidate, replacement, owner_stage="STAGE_1")
    return CompilerResult(
        outcome.candidate,
        outcome.candidate_sha256,
        {
            "kind": "STAGE_1_REPAIR",
            "repairPlanSha256": sha256_bytes(canonical_json_bytes(repair_plan)),
            "changedNodeIds": list(outcome.changed_node_ids),
        },
        outcome.diagnostics,
    )
