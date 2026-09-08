from __future__ import annotations
from action_ledger import CandidateResult, effective_result, effective_result_bytes, source_record_for_result, verify_result_reference

from collections.abc import Mapping, Sequence
import json
from pathlib import Path

from contracts import InvalidActionResult, canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from sow_model import NODE_COLLECTIONS, validate as validate_sow_model
from models import ContextRefDescriptor, AttemptDiagnostic
from stage_planner import AtomicWorkItemDescriptor, PlannedWorkDescriptor, RunBudgetPolicy, make_planned_work


SKILL_ROOT = Path(__file__).resolve().parents[1]
APPROVED_DESIGN_ROLES = {"HLD", "ADR"}
REQUIRED_POLICY_INCLUSIONS = {
    "policy-sit-automation": "DEFAULT_INCLUDED",
    "policy-uat-automation": "DEFAULT_INCLUDED",
    "policy-go-live": "REQUIRED",
}


def _verify_scan_bindings(packet, result, *, diagnostics=None):
    def emit(error):
        if diagnostics is None: raise error
        diagnostics.append(error.diagnostic)
    roots = {item["payload"]["coverageRootId"]: item["payload"] for item in packet["workItems"]}
    actual = [item["coverageRootId"] for item in result]
    missing_or_unknown=set(actual) ^ roots.keys()
    if missing_or_unknown:
        emit(InvalidActionResult("每个已授权 coverage root 必须恰好有事实或显式无关理由。", diagnostic=AttemptDiagnostic(
            'SCAN_COVERAGE_INVALID', '/', tuple(sorted(missing_or_unknown)))))
    seen=set()
    for index,item in enumerate(result):
        root=item["coverageRootId"]
        if root in seen:
            emit(InvalidActionResult("重复 coverage root 必须删除精确 occurrence。", diagnostic=AttemptDiagnostic(
                'SCAN_COVERAGE_DUPLICATE', '/'+str(index), (root,))))
        seen.add(root)
    for decision in result:
        keys = [fact["localKey"] for fact in decision["facts"]]
        if len(keys) != len(set(keys)):
            emit(InvalidActionResult("fact localKey 在同一 coverage root 内必须唯一。", diagnostic=AttemptDiagnostic(
                'SCAN_FACT_ID_DUPLICATE', '/'+decision['coverageRootId']+'/facts', (decision['coverageRootId'],))))
        allowed = set(roots.get(decision["coverageRootId"], {}).get("evidenceIds", []))
        for fact in decision["facts"]:
            if not set(fact["evidenceIds"]) <= allowed:
                emit(InvalidActionResult("事实证据不属于当前 coverage root。", diagnostic=AttemptDiagnostic(
                    'SCAN_EVIDENCE_UNBOUND', '/'+decision['coverageRootId']+'/facts/'+fact['localKey']+'/evidenceIds', (decision['coverageRootId'],))))


def verify_source_scan(packet, result):
    if validate_contract(result, "fact-decision.schema.json", load_registry(SKILL_ROOT / "contracts")):
        raise InvalidActionResult("FactDecisionIR schema 无效。")
    _verify_scan_bindings(packet, result)


class ScopeInputRequired(ValueError):
    wait = "WAITING_INPUT"
    code = "SCOPE_INPUT_REQUIRED"


AUDIT_CATEGORIES = {"THRESHOLD", "NEGATION", "EXCLUSION", "EXCEPTION", "ROLE", "TIME"}


def _prototype_observation_key(round_number, attempt_hash, local_key):
    return "observation-" + sha256_bytes(canonical_json_bytes([round_number, attempt_hash, local_key]))


def _scope_observations(context_refs, ledger):
    """Resolve exact selected handles from immutable Analyze results, never candidate claims."""
    from stage_planner import _effective_success

    observations = {}
    for ref in context_refs:
        value = json.loads(ref.canonical_content)
        if value.get("kind") != "PROTOTYPE_OBSERVATION_REF":
            continue
        if ledger is None:
            raise ValueError("Prototype observation 缺少实际 Attempt ledger。")
        digest = value["attemptRecordSha256"]
        record,raw=verify_result_reference(ledger,value)
        if ledger.envelopes_by_sha256[record.envelope_sha256].value['actionContractId']!='PROTOTYPE_ANALYZE-v1':
            raise ValueError('Prototype observation 来源 Owner 不符。')
        rows = json.loads(raw)["observations"]
        resolved = {_prototype_observation_key(value["round"], digest, row["localKey"]): (value, row) for row in rows}
        if (set(resolved) != set(value["observationKeys"]) or observations.keys() & resolved.keys()
                or set(value["evidenceIds"]) != {eid for row in rows for eid in row["evidenceIds"]}):
            raise ValueError("Prototype observation handle 或来源绑定错误。")
        observations.update(resolved)
    return observations


def _scope_evidence_ids(decision, observations):
    evidence = set(decision["boundaryEvidence"]["evidenceIds"])
    for handle in decision["boundaryEvidence"]["observationKeys"]:
        if handle not in observations:
            raise InvalidActionResult("Scope observation 缺少已绑定的原始结果。")
        evidence.update(observations[handle][1]["evidenceIds"])
    return sorted(evidence)


def prepare_scope_prototype_contexts(inventory, prototype_ledger, ledger):
    """Resolve every sealed round against the actual immutable Attempt chain."""
    from stage_planner import _effective_success
    from prototype_analysis import verify_prototype_trace, verify_prototype_observations

    if prototype_ledger["bundleSha256"] != inventory["bundleSha256"]:
        raise ValueError("Prototype ledger 不属于当前 bundle。")
    if prototype_ledger["sealed"] is not True:
        raise ScopeInputRequired("Prototype discovery 尚未封存。")
    rounds = prototype_ledger["rounds"]
    if not rounds or [item["round"] for item in rounds] != list(range(1, len(rounds) + 1)):
        raise ValueError("Prototype rounds 必须完整且连续。")
    contexts, dispositions, all_attempts, bindings = [], {}, set(), set()
    for round_value in rounds:
        attempt_hashes = round_value["attemptRecordSha256s"]
        if not attempt_hashes or len(set(attempt_hashes)) != len(attempt_hashes) or all_attempts.intersection(attempt_hashes):
            raise ValueError("Prototype round Attempt 引用重复或缺失。")
        all_attempts.update(attempt_hashes)
        success = {}
        works = set()
        for digest in attempt_hashes:
            record = ledger.attempt_records[digest]
            envelope = ledger.envelopes_by_sha256[record.envelope_sha256]
            kind = envelope.value["actionContractId"].removesuffix("-v1")
            if kind == 'CANDIDATE_PATCH':
                from candidate_repair import parse_repair_document
                # Patch origin is proved by ledger replay; no business result is inferred here.
                if not any(digest in {json.loads(raw)['chain'][i]['recordSha256'] for i in range(len(json.loads(raw)['chain']))}
                           for raw in ledger.candidate_resolutions.values()) and record.outcome=='SUCCEEDED':
                    raise ValueError('Prototype 补丁缺少完整 Resolution。')
                continue
            if kind not in {"PROTOTYPE_SCENARIO", "PROTOTYPE_BROWSER", "PROTOTYPE_ANALYZE"}:
                raise ValueError("Prototype round 引用了其他业务 Attempt。")
            bindings.add((envelope.value["runId"], envelope.value["inputRevisionSha256"]))
            works.add(record.logical_work_id)
            result_bytes=effective_result_bytes(ledger,record.logical_work_id)
            if result_bytes is not None:
                effective_digest,effective=effective_result(ledger,record.logical_work_id)
                source=source_record_for_result(ledger,effective_digest)
                if source.envelope_sha256==record.envelope_sha256:
                    if kind in success:raise ValueError('Prototype 有重复有效来源。')
                    success[kind]=(digest,effective,json.loads(result_bytes))
        expected_attempts = {digest for digest, record in ledger.attempt_records.items() if record.logical_work_id in works}
        for logical in works:
            if logical in ledger.candidate_resolutions:
                expected_attempts.update(entry['recordSha256'] for entry in json.loads(ledger.candidate_resolutions[logical])['chain'])
        # Failed physical patches also belong to the sealed round.
        expected_attempts.update(d for d in attempt_hashes if ledger.envelopes_by_sha256[ledger.attempt_records[d].envelope_sha256].value['actionContractId']=='CANDIDATE_PATCH-v1')
        if set(attempt_hashes) != expected_attempts or len(success) != 3:
            raise ScopeInputRequired("Prototype round 的实际 Attempt 链不完整。")
        scenario = success["PROTOTYPE_SCENARIO"][2]
        trace = success["PROTOTYPE_BROWSER"][2]
        digest, record, result = success["PROTOTYPE_ANALYZE"]
        if scenario["round"] != round_value["round"]:
            raise ValueError("Prototype round 身份漂移。")
        trace_evidence = verify_prototype_trace(inventory, scenario, trace)
        if trace_evidence["unresolvedDiscoveryCount"]:
            raise ScopeInputRequired("Prototype 存在尚未解决的发现。")
        verify_prototype_observations(inventory, scenario, trace, result)
        expected_refs = [{"localKey": item["localKey"], "attemptRecordSha256": digest,
            "normalizedResultSha256": record.normalized_result_sha256, "pointer": f"/observations/{index}"}
            for index, item in enumerate(result["observations"])]
        resolution=ledger.candidate_resolutions.get(ledger.attempt_records[digest].logical_work_id)
        if resolution is not None:
            for ref in expected_refs:ref['candidateResolutionSha256']=sha256_bytes(resolution)
        if expected_refs != round_value["observationRefs"]:
            raise ValueError("Prototype observation refs 与实际结果不一致。")
        round_dispositions = {item["interactionId"]: item["disposition"] for item in trace_evidence["interactionDispositions"]}
        for observation in result["observations"]:
            for interaction in observation["interactionIds"]:
                if observation["scopeRelation"] == "NON_SCOPE":
                    round_dispositions[interaction] = "EXCLUDED"
                elif observation["runtimeStatus"] == "CODE_ONLY":
                    round_dispositions.setdefault(interaction, "NOT_EXERCISED")
                elif observation["runtimeStatus"] in {"BROKEN", "NOT_EXERCISED"}:
                    round_dispositions[interaction] = observation["runtimeStatus"]
        expected_dispositions = [{"interactionId": key, "disposition": value} for key, value in sorted(round_dispositions.items())]
        if expected_dispositions != round_value["interactionDispositions"]:
            raise ValueError("Prototype round disposition 与实际证据不一致。")
        dispositions.update(round_dispositions)
        value = {"kind": "PROTOTYPE_OBSERVATION_REF", "round": round_value["round"],
                 "attemptRecordSha256": digest, "normalizedResultSha256": record.normalized_result_sha256,
                 "observationKeys": sorted(_prototype_observation_key(round_value["round"], digest, item["localKey"]) for item in result["observations"]),
                 "evidenceIds": sorted({eid for item in result["observations"] for eid in item["evidenceIds"]})}
        if resolution is not None:value['candidateResolutionSha256']=sha256_bytes(resolution)
        contexts.append(ContextRefDescriptor("prototype-round-" + str(round_value["round"]), canonical_json_bytes(value)))
    if len(bindings) != 1 or set(dispositions) != {item["interactionId"] for item in inventory["interactions"]}:
        raise ScopeInputRequired("Prototype bundle 的输入绑定或交互覆盖不完整。")
    if prototype_ledger["interactionDispositions"] != [{"interactionId": key, "disposition": value} for key, value in sorted(dispositions.items())]:
        raise ValueError("Prototype final disposition 漂移。")
    value = {"kind": "PROTOTYPE_LEDGER", "ledger": prototype_ledger, "inputRevisionSha256": next(iter(bindings))[1]}
    return (ContextRefDescriptor("prototype-ledger", canonical_json_bytes(value)), *contexts)


def _validate_scope_prototype_refs(contexts):
    ledgers = [value for value in contexts if value.get("kind") == "PROTOTYPE_LEDGER"]
    rounds = [value for value in contexts if value.get("kind") == "PROTOTYPE_OBSERVATION_REF"]
    if not ledgers and not rounds:
        return
    if len(ledgers) != 1 or ledgers[0]["ledger"]["sealed"] is not True:
        raise ScopeInputRequired("Scope 需要唯一完整 Prototype ledger。")
    declared = ledgers[0]["ledger"]["rounds"]
    if sorted(item["round"] for item in rounds) != [item["round"] for item in declared]:
        raise ValueError("Scope 必须消费全部 Prototype rounds。")
    for round_value in declared:
        reference = next(item for item in rounds if item["round"] == round_value["round"])
        expected = sorted(_prototype_observation_key(round_value["round"], item["attemptRecordSha256"], item["localKey"]) for item in round_value["observationRefs"])
        if reference["observationKeys"] != expected or reference["attemptRecordSha256"] not in round_value["attemptRecordSha256s"]:
            raise ValueError("Scope Prototype observation refs 不完整。")
        if any(item["attemptRecordSha256"] != reference["attemptRecordSha256"] or item["normalizedResultSha256"] != reference["normalizedResultSha256"] for item in round_value["observationRefs"]):
            raise ValueError("Scope Prototype observation result 绑定漂移。")


PRIOR_PAYLOAD_LIMIT = 64000


def _prior_sheet_payloads(source_id, sheet, evidence, context=None):
    """Keep small legacy packets stable; partition large sheets by complete rows.

    Cell bytes live once in each evidence row. Repeated headings are read-only
    context and do not expand the partition's evidence authority.
    """
    import re

    def row(item):
        return int(re.search(r'\d+', item['absoluteA1Range']).group())

    original = {'sourceId':source_id, 'evidenceIds':sorted(item['priorEvidenceId'] for item in evidence),
        'evidence':sorted(evidence, key=lambda item:item['priorEvidenceId']), 'sheet':sheet}
    limit = PRIOR_PAYLOAD_LIMIT
    if context is not None:
        original['sheet'] = {key:value for key,value in sheet.items() if key!='cells'}
        original['priorContext'] = context
        # 64 KB partitions the row data; the complete shared source index is
        # additional context. The planner still meters the entire provider request.
        limit += len(canonical_json_bytes(context))
    if len(canonical_json_bytes(original)) <= limit:
        return [original]
    ordered = sorted(evidence, key=lambda item:(row(item), item['priorEvidenceId']))
    header_rows = {int(re.search(r'\d+', table['range']).group()) for table in sheet['tables']}
    first_header = min(header_rows, default=row(ordered[0]))
    header_rows.update(row(item) for item in ordered if row(item) <= first_header)
    headers = [item for item in ordered if row(item) in header_rows]
    metadata = {key:value for key,value in sheet.items() if key!='cells'}

    def payload(rows):
        value = {'priorInputLayout':'ai-sow-prior-row-partition-v1', 'sourceId':source_id,
            'evidenceIds':sorted(item['priorEvidenceId'] for item in rows), 'evidence':rows,
            'sheet':metadata, 'headerEvidence':headers}
        if context is not None:
            value['priorContext'] = context
        return value

    chunks, current = [], []
    for item in ordered:
        if current and len(canonical_json_bytes(payload([*current,item]))) > limit:
            chunks.append(payload(current)); current=[]
        current.append(item)
        if len(canonical_json_bytes(payload(current))) > limit:
            from stage_planner import StagePlanningBlocked
            raise StagePlanningBlocked('BUDGET_EXHAUSTED', {'reason': 'PRIOR_ROW_CONTEXT_TOO_LARGE'})
    if current: chunks.append(payload(current))
    return chunks


def _prior_workbook_payloads(source_id, inventory):
    from prior_state import prior_context
    context = prior_context(source_id, inventory)
    evidence = inventory['evidence']
    whole = {'sourceId': source_id, 'evidenceIds': sorted(row['priorEvidenceId'] for row in evidence),
             'evidence': evidence, 'sheets': [{key:value for key,value in sheet.items() if key!='cells'} for sheet in inventory['sheets']],
             'priorContext': context}
    if len(canonical_json_bytes(whole)) <= PRIOR_PAYLOAD_LIMIT:
        return [whole]
    return [payload for sheet in inventory['sheets']
            if (rows := [row for row in evidence if row['sheet'] == sheet['sheet']])
            for payload in _prior_sheet_payloads(source_id, sheet, rows, context)]


def prepare_scope_inputs(input_revision_bytes, source_contents, *, request, prior_inventories=(), prototype_context_refs=()):
    """Derive atomic identities from the immutable revision, never caller labels."""
    from contracts import load_schema_registry
    from prior_state import build_project_effective_start_context

    revision = json.loads(input_revision_bytes)
    if canonical_json_bytes(revision) != input_revision_bytes or validate_contract(revision, "input-revision.schema.json", load_schema_registry(SKILL_ROOT)):
        raise ValueError("Scope 需要完整 canonical InputRevision。")
    if sha256_bytes(canonical_json_bytes(request)) != revision["requestSha256"]:
        raise ValueError("Scope request 与 InputRevision 不匹配。")
    policy_bytes = (SKILL_ROOT / "contracts/delivery-policy-v1.json").read_bytes()
    if sha256_bytes(policy_bytes) != revision["deliveryPolicySha256"]:
        raise ValueError("Scope policy 与 InputRevision 不匹配。")
    sources = {source["sourceId"]: source for source in revision["sources"]}
    blocks = {block["blockId"]: block for block in revision["blocks"]}
    if len(sources) != len(revision["sources"]) or len(blocks) != len(revision["blocks"]):
        raise ValueError("Scope 来源或 block 身份重复。")
    items, contexts = [], []
    roots = {block["primaryCoverageBlockId"] for block in blocks.values()
             if block["extractionDisposition"] != "DROPPED" and sources[block["sourceId"]]["role"] not in {"PRIOR_SOW", "DEMO"}}
    for root in sorted(roots):
        block = blocks[root]
        source = sources[block["sourceId"]]
        selected = [root] + [key for key in block["contextBlockIds"] if key != root]
        evidence_blocks = []
        for key in selected:
            content = source_contents[key]
            if sha256_bytes(content.encode("utf-8")) != blocks[key]["contentSha256"]:
                raise ValueError("Scope source content hash 漂移。")
            evidence_blocks.append({**blocks[key], "content": content})
        payload = {"coverageRootId": root, "sourceRole": source["role"], "evidenceIds": selected,
                   "sourceBlock": evidence_blocks[0], "contextBlocks": evidence_blocks[1:]}
        item_id = "item-" + sha256_bytes(canonical_json_bytes({"scopeWorkItemVersion": "1", "payload": payload}))
        item = AtomicWorkItemDescriptor(item_id, "SOURCE_SCAN", source["role"], source["rawSha256"], source["blockIds"].index(root), payload)
        items.append(item)
        contexts.append(ContextRefDescriptor("source-" + item_id, canonical_json_bytes({"kind": "SOURCE_BLOCK", **payload})))
    prior_sources = [source for source in sources.values() if source["role"] == "PRIOR_SOW"]
    inventories = {inventory["workbookSha256"]: inventory for inventory in prior_inventories}
    if len(inventories) != len(prior_inventories) or set(inventories) != {source["rawSha256"] for source in prior_sources}:
        raise ValueError("Prior inventories 必须恰好覆盖已授权来源。")
    if request["mode"] == "GREENFIELD" and prior_sources:
        raise ValueError("Greenfield 不接受 Prior。")
    for source in sorted(prior_sources, key=lambda source: source["sourceId"]):
        inventory = inventories[source["rawSha256"]]
        if not inventory["evidence"]:
            raise ScopeInputRequired("已授权往期工作簿没有可分析合同区域：" + source["sourceId"])
        for ordinal, payload in enumerate(_prior_workbook_payloads(source['sourceId'], inventory)):
            item_id = "item-" + sha256_bytes(canonical_json_bytes({"scopeWorkItemVersion": "2", "payload": payload}))
            items.append(AtomicWorkItemDescriptor(item_id, "PRIOR_ANALYZE", "PRIOR_SOW", source["rawSha256"], ordinal, payload))
    if prior_sources:
        if not any(item.action_kind == "PRIOR_ANALYZE" for item in items):
            raise ScopeInputRequired("往期工作簿没有可分析的合同区域。")
        contexts.append(build_project_effective_start_context(input_revision_bytes))
    scope_context = {"kind": "SCOPE_CONTEXT", "inputRevisionSha256": sha256_bytes(input_revision_bytes),
                     "project": request["project"], "mode": request["mode"],
                     "responsibilityBoundaries": request["responsibilityBoundaries"], "deliveryPolicy": json.loads(policy_bytes),
                     "sourceDirectory": [{"sourceId": source["sourceId"], "role": source["role"], "status": source["status"], "blockIds": source["blockIds"]}
                                         for source in sorted(sources.values(), key=lambda source: source["sourceId"])]}
    if request.get("declaredChangeContext") is not None:
        scope_context["declaredChangeContext"] = request["declaredChangeContext"]
    contexts.append(ContextRefDescriptor("scope-context", canonical_json_bytes(scope_context)))
    contexts.extend(prototype_context_refs)
    return tuple(items), tuple(contexts)


def build_scope_work_descriptors(
    work_items: Sequence[AtomicWorkItemDescriptor],
    context_refs: Sequence[ContextRefDescriptor],
    budget_policy: RunBudgetPolicy,
    *,
    action_contract_ids: Mapping[str, str] | None = None,
) -> tuple[PlannedWorkDescriptor, ...]:
    from stage_planner import estimate_work_input_tokens, StagePlanningBlocked, run_budget_policy_value
    from contracts import usable_action_input_tokens

    if len({item.work_item_id for item in work_items}) != len(work_items) or len({ref.ref_id for ref in context_refs}) != len(context_refs):
        raise ValueError("Scope item/context 不得重复。")
    if any(item.action_kind not in {"SOURCE_SCAN", "PRIOR_ANALYZE"} for item in work_items):
        raise ValueError("Scope 原子项只允许 Source Scan 或 Prior Analyze。")
    contexts = {ref.ref_id: json.loads(ref.canonical_content) for ref in context_refs}
    _validate_scope_prototype_refs(list(contexts.values()))
    originals = [ref for ref in context_refs if contexts[ref.ref_id].get("kind") == "SOURCE_BLOCK"]
    date = [ref for ref in context_refs if contexts[ref.ref_id].get("kind") == "PROJECT_EFFECTIVE_START"]
    global_context = [ref for ref in context_refs if contexts[ref.ref_id].get("kind") not in {"SOURCE_BLOCK", "PROJECT_EFFECTIVE_START"}]
    source_items = [item for item in work_items if item.action_kind == "SOURCE_SCAN"]
    prior_items = [item for item in work_items if item.action_kind == "PRIOR_ANALYZE"]
    roots = [item.work_item_payload["coverageRootId"] for item in source_items]
    original_roots = [contexts[ref.ref_id]["coverageRootId"] for ref in originals]
    if len(roots) != len(set(roots)) or sorted(roots) != sorted(original_roots):
        raise ValueError("Scope 每个原始覆盖根必须有一个精确 Audit context。")
    for item in source_items:
        matches = [contexts[ref.ref_id] for ref in originals if contexts[ref.ref_id]["coverageRootId"] == item.work_item_payload["coverageRootId"]]
        if len(matches) != 1 or {k: v for k, v in matches[0].items() if k != "kind"} != item.work_item_payload:
            raise ValueError("Audit 原始 SourceBlock 与 Scan payload 不一致。")
    if (bool(prior_items) and len(date) != 1) or (not prior_items and date):
        raise ValueError("每个 Prior packet 必须绑定唯一日期；零 Prior 不生成日期替代输入。")
    usable = usable_action_input_tokens(run_budget_policy_value(budget_policy))
    width = usable // (budget_policy.output_reserve_tokens + budget_policy.reference_overhead_tokens)
    works = []

    def fits(kind, items, refs):
        return estimate_work_input_tokens(kind, items, refs, budget_policy, action_contract_ids=action_contract_ids) <= usable

    def add(kind, items, refs, dependencies):
        if not fits(kind, items, refs):
            raise StagePlanningBlocked("BUDGET_EXHAUSTED")
        descriptor = make_planned_work(kind, items, refs, [item.work_key for item in dependencies])
        works.append(descriptor)
        return descriptor

    def source_refs(items):
        selected = {item.work_item_payload["coverageRootId"] for item in items}
        return [ref for ref in originals if contexts[ref.ref_id]["coverageRootId"] in selected]

    def pack(kind, items, refs):
        ordered = sorted(items, key=lambda item: (item.action_kind, item.source_role, item.source_sha256, item.block_ordinal, item.work_item_id))
        chunks, current = [], []
        for item in ordered:
            proposed = current + [item]
            acceptable = fits(kind, proposed, refs)
            if kind == "SOURCE_SCAN":
                acceptable = acceptable and fits("SOURCE_AUDIT", [], source_refs(proposed))
            if current and not acceptable:
                chunks.append(current)
                current = []
            current.append(item)
            if not fits(kind, current, refs) or (kind == "SOURCE_SCAN" and not fits("SOURCE_AUDIT", [], source_refs(current))):
                actual_kind, actual_items, actual_refs = kind, current, refs
                if fits(kind, current, refs):
                    actual_kind, actual_items, actual_refs = 'SOURCE_AUDIT', [], source_refs(current)
                raise StagePlanningBlocked("BUDGET_EXHAUSTED", {
                    'actionKind':actual_kind, 'unissued':True,
                    'workItemIds':[value.work_item_id for value in current],
                    'estimatedInputTokens':estimate_work_input_tokens(actual_kind, actual_items, actual_refs, budget_policy, action_contract_ids=action_contract_ids),
                    'usableInputTokens':usable})
        if current:
            chunks.append(current)
        return chunks

    def join(kind, leaves, refs):
        while len(leaves) > 1:
            if width < 2:
                raise StagePlanningBlocked("BUDGET_EXHAUSTED")
            next_level = []
            for offset in range(0, len(leaves), width):
                chunk = leaves[offset:offset + width]
                next_level.append(chunk[0] if len(chunk) == 1 else add(kind, [], refs, chunk))
            leaves = next_level
        return leaves

    prior_leaves = [add("PRIOR_ANALYZE", chunk, date, []) for chunk in pack("PRIOR_ANALYZE", prior_items, date)]
    prior_root = join("PRIOR_CONSOLIDATE", prior_leaves, date)
    pairs = []
    for chunk in pack("SOURCE_SCAN", source_items, []):
        scan = add("SOURCE_SCAN", chunk, [], [])
        audit = add("SOURCE_AUDIT", [], source_refs(chunk), [scan])
        pairs.append([scan, audit])
    dependencies = [work for pair in pairs for work in pair] + prior_root
    if len(dependencies) <= width and fits("SCOPE_SYNTHESIS", [], global_context):
        add("SCOPE_SYNTHESIS", [], global_context, dependencies)
    else:
        capacity = (width - len(prior_root)) // 2
        if width < 2 or capacity < 1 or not pairs:
            raise StagePlanningBlocked("BUDGET_EXHAUSTED")
        proposals = [add("SCOPE_PROPOSAL", [], global_context,
                     [work for pair in pairs[offset:offset + capacity] for work in pair] + prior_root)
                     for offset in range(0, len(pairs), capacity)]
        join("SCOPE_JOIN", proposals, global_context)
    return tuple(works)


def _scan_audit_context(packet):
    dependencies = [ref["canonicalContent"] for ref in packet["contextRefs"]
                    if ref["canonicalContent"].get("kind") == "DEPENDENCY_RESULT"]
    blocks = [ref["canonicalContent"] for ref in packet["contextRefs"]
              if ref["canonicalContent"].get("kind") == "SOURCE_BLOCK"]
    if len(dependencies) != 1 or not blocks or packet["workItems"]:
        raise ValueError("Audit 必须依赖唯一 Scan 并重读对应原始块。")
    result = dependencies[0]["normalizedResult"]
    _verify_scan_bindings({"workItems": [{"payload": block} for block in blocks]}, result)
    return {item["coverageRootId"]: item for item in result}, {block["coverageRootId"]: block for block in blocks}


def _verify_audit_bindings(packet, result, *, diagnostics=None):
    def emit(error):
        if diagnostics is None: raise error
        diagnostics.append(error.diagnostic)
    scans, blocks = _scan_audit_context(packet)
    pairs = [(check["coverageRootId"], check["category"]) for check in result["checks"]]
    expected={(root,category) for root in scans for category in AUDIT_CATEGORIES}
    if set(pairs)!=expected:
        emit(InvalidActionResult("每个 coverage root 必须独立审计六类语义。", diagnostic=AttemptDiagnostic(
            'AUDIT_COVERAGE_INVALID', '/checks', tuple(sorted(set(pairs)^expected)))))
    seen=set()
    for index,pair in enumerate(pairs):
        if pair in seen:
            emit(InvalidActionResult("重复 Audit pair 必须删除精确 occurrence。", diagnostic=AttemptDiagnostic(
                'AUDIT_PAIR_DUPLICATE', '/checks/'+str(index), ('|'.join(pair),))))
        seen.add(pair)
    for check in result["checks"]:
        root = check["coverageRootId"]
        if root not in scans: continue
        keys = {fact["localKey"] for fact in scans[root]["facts"]}
        if not set(check["relatedFactKeys"]) <= keys or not set(check["evidenceIds"]) <= set(blocks[root]["evidenceIds"]):
            emit(InvalidActionResult("Audit 的 fact key 或证据不属于对应 Scan/root。", diagnostic=AttemptDiagnostic(
                'AUDIT_REFERENCE_UNBOUND', '/checks/'+root+'/'+check['category'], (root+'|'+check['category'],))))


def verify_source_audit(packet, result):
    if validate_contract(result, "source-audit.schema.json", load_registry(SKILL_ROOT / "contracts")):
        raise InvalidActionResult("SourceAuditIR schema 无效。")
    _verify_audit_bindings(packet, result)
    if any(check["decision"] == "MISSING" for check in result["checks"]):
        raise ScopeInputRequired("Source Audit 发现漏读，不能关闭 Scope。")


def _scope_dependency_catalog(packet):
    facts, prior_keys, evidence, observations = set(), set(), set(), set()
    for ref in packet["contextRefs"]:
        content = ref["canonicalContent"]
        if content.get("kind") == "PROTOTYPE_OBSERVATION_REF":
            observations.update(content["observationKeys"])
            evidence.update(content["evidenceIds"])
        if content.get("kind") != "DEPENDENCY_RESULT":
            continue
        result = content["normalizedResult"]
        if isinstance(result, list):
            for decision in result:
                for fact in decision["facts"]:
                    handle = decision["coverageRootId"] + ":" + fact["localKey"]
                    if handle in facts:
                        raise ValueError("冻结 Scan fact handle 不唯一。")
                    facts.add(handle)
                    evidence.update(fact["evidenceIds"])
        elif "entities" in result:
            prior_keys.update(entity["localKey"] for entity in result["entities"])
            evidence.update(eid for entity in result["entities"] for eid in entity["evidenceIds"])
        elif "decisions" in result:
            for decision in result["decisions"]:
                if facts & set(decision["factIds"]):
                    raise ValueError("冻结 Scope dependencies 重复处置事实。")
                facts.update(decision["factIds"])
                prior_keys.update(decision["priorEntityIds"])
                evidence.update(decision["boundaryEvidence"]["evidenceIds"])
                evidence.update(eid for relation in decision["relations"] for eid in relation["evidenceIds"])
                observations.update(decision["boundaryEvidence"]["observationKeys"])
    return facts, prior_keys, evidence, observations


def _verify_scope_bindings(packet, result, *, diagnostics=None):
    def emit(error):
        if diagnostics is None: raise error
        diagnostics.append(error.diagnostic)
    from models import AttemptDiagnostic
    facts, priors, evidence, observations = _scope_dependency_catalog(packet)
    decisions = result["decisions"]
    keys = {decision["localKey"] for decision in decisions}
    assigned = [fact_id for decision in decisions for fact_id in decision["factIds"]]
    if len(keys) != len(decisions) or len(assigned) != len(set(assigned)) or set(assigned) != facts:
        emit(InvalidActionResult("每个事实必须恰好有一个 Scope disposition，localKey 不得重复。", diagnostic=AttemptDiagnostic(
            'SCOPE_FACT_COVERAGE_INVALID', '/decisions', tuple(sorted({row['localKey'] for row in decisions
                if sum(item['localKey']==row['localKey'] for item in decisions)>1 or any(assigned.count(key)>1 or key not in facts for key in row['factIds'])})))))
    current_key = None
    current_path = '/decisions'
    def reject(message, path):
        emit(InvalidActionResult(message, diagnostic=AttemptDiagnostic('SCOPE_BINDING_INVALID', path,
            (current_key,) if current_key else ())))
    adopted = []
    by_key = {decision["localKey"]: decision for decision in decisions}
    current_evidence, prior_evidence = set(), {}
    for ref in packet["contextRefs"]:
        content = ref["canonicalContent"]
        if content.get("kind") == "SCOPE_CONTEXT":
            current_evidence.update(block for source in content["sourceDirectory"] if source["role"] not in {"PRIOR_SOW", "DEMO"} for block in source["blockIds"])
        elif content.get("kind") == "PROTOTYPE_OBSERVATION_REF":
            current_evidence.update(content["evidenceIds"])
        elif content.get("kind") == "DEPENDENCY_RESULT":
            dependency = content["normalizedResult"]
            if isinstance(dependency, list):
                current_evidence.update(eid for item in dependency for fact in item["facts"] for eid in fact["evidenceIds"])
            elif "entities" in dependency:
                for item in dependency["entities"]:
                    prior_evidence[item["localKey"]] = set(item["evidenceIds"])
    for ref in packet["contextRefs"]:
        content = ref["canonicalContent"]
        if content.get("kind") == "DEPENDENCY_RESULT" and isinstance(content["normalizedResult"], dict):
            for item in content["normalizedResult"].get("decisions", []):
                for key in item["priorEntityIds"]:
                    prior_evidence.setdefault(key, set()).update(set(item["boundaryEvidence"]["evidenceIds"]) - current_evidence)
    used_prior, used_targets = set(), set()
    for decision_index, decision in enumerate(decisions):
        current_key=decision['localKey'];current_path='/decisions/'+str(decision_index)
        boundary = decision["boundaryEvidence"]
        kind = decision["decisionKind"]
        if (not set(decision["priorEntityIds"]) <= priors or not set(boundary["evidenceIds"]) <= evidence
                or not {facet["factId"] for facet in boundary["facetFacts"]} <= facts
                or not set(boundary["observationKeys"]) <= observations):
            emit(InvalidActionResult("Scope boundary 的事实、Prior、原型或来源引用不存在。", diagnostic=AttemptDiagnostic(
                "SCOPE_BOUNDARY_REFERENCE_UNBOUND", f"/decisions/{decision_index}/boundaryEvidence", (decision["localKey"],))))
        adopted.extend(boundary["observationKeys"])
        for relation_index, relation in enumerate(decision["relations"]):
            if not set(relation["targetLocalKeys"]) <= keys or not set(relation["evidenceIds"]) <= evidence:
                emit(InvalidActionResult("Scope relation 的 localKey 或证据不存在。", diagnostic=AttemptDiagnostic(
                    "SCOPE_RELATION_REFERENCE_UNBOUND", f"/decisions/{decision_index}/relations/{relation_index}", (decision["localKey"],))))
            relation_kind = relation["kind"]
            target_kinds = {by_key[key]["decisionKind"] for key in relation["targetLocalKeys"] if key in by_key}
            allowed = {
                "PARENT": ({"FEATURE"}, {"EPIC"}),
                "APPLIES_TO": ({"DESIGN_ITEM", "INTEGRATION", "NFR", "POLICY_INSTANCE"}, {"FEATURE", "EPIC"} if kind == "POLICY_INSTANCE" else {"FEATURE"}),
                "DESIGN": ({"EPIC", "FEATURE"}, {"DESIGN_ITEM"}),
                "POLICY": ({"EPIC", "FEATURE"}, {"POLICY_INSTANCE"}),
            }
            if relation_kind in allowed and (kind not in allowed[relation_kind][0] or not target_kinds <= allowed[relation_kind][1]):
                emit(InvalidActionResult("Scope 关系的来源或目标类型不合法。", diagnostic=AttemptDiagnostic(
                    "SCOPE_RELATION_ENDPOINT_INVALID", f"/decisions/{decision_index}/relations/{relation_index}", (decision["localKey"],))))
            if relation_kind in {"DESIGN", "POLICY"}:
                for target in relation["targetLocalKeys"]:
                    if target not in by_key: continue
                    applications = {key for item in by_key[target]["relations"] if item["kind"] == "APPLIES_TO" for key in item["targetLocalKeys"]}
                    matches_epic_design = relation_kind == "DESIGN" and kind == "EPIC" and any(
                        decision["localKey"] in item["targetLocalKeys"] for key in applications
                        for item in by_key.get(key, {}).get("relations", []) if item["kind"] == "PARENT")
                    if decision["localKey"] not in applications and not matches_epic_design:
                        reject("显式 DESIGN/POLICY 与 APPLIES_TO 端点相互矛盾。", f"{current_path}/relations/{relation_index}/targetLocalKeys")
            if relation_kind in {"REUSE_DEPENDENCY", "ADJUST", "SPLIT", "MERGE"}:
                from change_graph import change_cardinality_supported
                if kind in {"RETIRE", "EXCLUDE"} or not decision["priorEntityIds"] or target_kinds & {"RETIRE", "EXCLUDE"}:
                    reject("变更关系必须连接真实 Prior 和目标实体。", f"{current_path}/relations/{relation_index}/targetLocalKeys")
                if not change_cardinality_supported(relation_kind, len(decision["priorEntityIds"]), len(relation["targetLocalKeys"])):
                    reject("变更关系的 Prior/target 基数不符合 V1 合同。", f"{current_path}/relations/{relation_index}/targetLocalKeys")
                if used_prior.intersection(decision["priorEntityIds"]) or used_targets.intersection(relation["targetLocalKeys"]):
                    reject("同一 Prior 或目标不能进入多个显式变更组。", f"{current_path}/relations/{relation_index}/targetLocalKeys")
                used_prior.update(decision["priorEntityIds"])
                used_targets.update(relation["targetLocalKeys"])
            if relation_kind == "UNCHANGED_IDENTITY" and (relation["targetLocalKeys"] != [decision["localKey"]] or len(decision["priorEntityIds"]) != 1
                    or not any(item["kind"] in {"REUSE_DEPENDENCY", "ADJUST"} and item["targetLocalKeys"] == [decision["localKey"]] for item in decision["relations"])):
                reject("未变身份声明必须绑定本对象的唯一 1:1 匹配。", f"{current_path}/relations/{relation_index}/targetLocalKeys")
        parents = [target for relation in decision["relations"] if relation["kind"] == "PARENT" for target in relation["targetLocalKeys"]]
        if (kind == "FEATURE" and len(parents) != 1) or (kind != "FEATURE" and parents):
            reject("Feature 必须且只能有一个 Epic parent。", current_path+"/relations")
        if decision["priorEntityIds"] and kind != "RETIRE" and not any(item["kind"] in {"REUSE_DEPENDENCY", "ADJUST", "SPLIT", "MERGE"} for item in decision["relations"]):
            reject("已选择的 Prior 必须有显式变更处置。", current_path+"/relations")
        if kind == "RETIRE":
            if (not decision["priorEntityIds"] or used_prior.intersection(decision["priorEntityIds"])
                    or not current_evidence.intersection(boundary["evidenceIds"])
                    or any(not prior_evidence.get(key, set()).intersection(boundary["evidenceIds"]) for key in decision["priorEntityIds"])):
                reject("退役必须有互斥 Prior、对应历史证据与本轮移除证据。", current_path+"/boundaryEvidence/evidenceIds")
            used_prior.update(decision["priorEntityIds"])
        if kind == "POLICY_INSTANCE" and not any(item["kind"] == "APPLIES_TO" for item in decision["relations"]):
            reject("政策实例必须选择实际 Epic/Feature 目标。", current_path+"/relations")
        roles = [facet["role"] for facet in boundary["facetFacts"]]
        required_roles = {"DIRECTION", "METHOD", "PURPOSE"} if kind == "INTEGRATION" else {"TARGET"} if kind == "NFR" else set()
        if set(roles) != required_roles or any(roles.count(role) != 1 for role in required_roles):
            reject("目标边界字段的来源事实不齐备或角色不合法。", current_path+"/boundaryEvidence/facetFacts")
        if (kind == "INTEGRATION") != bool(boundary.get("responsibilityBoundaryIds")):
            reject("仅 Integration 必须选择责任边界。", current_path+"/boundaryEvidence/responsibilityBoundaryIds")
        if kind == "INTEGRATION":
            contexts = [ref["canonicalContent"] for ref in packet["contextRefs"] if ref["canonicalContent"].get("kind") == "SCOPE_CONTEXT"]
            allowed_boundaries = {item["responsibilityBoundaryId"] for context in contexts for item in context["responsibilityBoundaries"]}
            if not set(boundary["responsibilityBoundaryIds"]) <= allowed_boundaries:
                reject("Integration 引用了未声明责任边界。", current_path+"/boundaryEvidence/responsibilityBoundaryIds")
        if kind == "DESIGN_ITEM":
            approved_evidence = {block for ref in packet["contextRefs"] if ref["canonicalContent"].get("kind") == "SCOPE_CONTEXT"
                for source in ref["canonicalContent"]["sourceDirectory"] if source["role"] in APPROVED_DESIGN_ROLES and source["status"] == "APPROVED"
                for block in source["blockIds"]}
            if not set(boundary["evidenceIds"]) <= approved_evidence:
                reject("设计项证据必须属于本轮批准的 HLD/ADR。", current_path+"/boundaryEvidence/evidenceIds")
    if len(adopted) != len(set(adopted)) or set(adopted) != observations:
        holders = tuple(sorted(row['localKey'] for row in decisions if any(
            adopted.count(key) > 1 for key in row['boundaryEvidence']['observationKeys'])))
        emit(InvalidActionResult("每个原型 observation 必须有一个显式 Scope disposition。",
            diagnostic=AttemptDiagnostic('SCOPE_BINDING_INVALID', '/observations', holders)))


def verify_scope_decision(packet, result):
    if validate_contract(result, "scope-decision.schema.json", load_registry(SKILL_ROOT / "contracts")):
        raise InvalidActionResult("ScopeDecisionIR schema 无效。")
    _verify_scope_bindings(packet, result)


def validate_bound_scope_context(action_kind, packet):
    from contracts import load_schema_registry
    if action_kind not in {"SOURCE_SCAN", "SOURCE_AUDIT", "SCOPE_SYNTHESIS", "SCOPE_PROPOSAL", "SCOPE_JOIN"}:
        raise ValueError("未知 Scope action kind。")
    if set(packet) != {"workItems", "contextRefs"}:
        raise ValueError("Scope 只接受唯一 planner packet 表示。")
    registry = load_schema_registry(SKILL_ROOT)
    for ref in packet["contextRefs"]:
        content = ref["canonicalContent"]
        if content.get("kind") != "DEPENDENCY_RESULT":
            if ref["contentSha256"] != sha256_bytes(canonical_json_bytes(content)):
                raise ValueError("冻结 Scope context hash 漂移。")
            continue
        if (set(ref) != {"refId", "canonicalContent"} or set(content) not in ({"kind", "logicalWorkId", "attemptRecordSha256", "normalizedResult"},{"kind", "logicalWorkId", "candidateResolutionSha256", "sourceAttemptRecordSha256", "normalizedResult"})
                or ref["refId"] != "dependency-result-" + content["logicalWorkId"]):
            raise ValueError("Scope dependency wrapper 不符合唯一表示。")
        result = content["normalizedResult"]
        from prior_state import prior_decision_schema
        schema = ("fact-decision.schema.json" if isinstance(result, list) else "source-audit.schema.json" if "checks" in result
                  else prior_decision_schema(result) if "entities" in result else "scope-decision.schema.json")
        if validate_contract(result, schema, registry):
            raise ValueError("冻结 Scope dependency schema 无效。")
    if action_kind == "SOURCE_AUDIT":
        _scan_audit_context(packet)
    elif action_kind.startswith("SCOPE_"):
        _scope_dependency_catalog(packet)


def _preserve_observation_bindings(packet, previous, result):
    """An observation repair can only fill bindings or remove duplicate ownership."""
    from copy import deepcopy
    from candidate_repair import preserve_roots
    _, _, _, observations = _scope_dependency_catalog(packet)
    adopted = [key for row in previous['decisions'] for key in row['boundaryEvidence']['observationKeys']]
    missing = observations - set(adopted)
    duplicated = {key for key in adopted if adopted.count(key) > 1}
    current = {row['localKey']: row for row in result['decisions']}
    adjusted = deepcopy(previous)
    for row in adjusted['decisions']:
        replacement = current.get(row['localKey'])
        if replacement is None: continue
        before, after = row['boundaryEvidence'], replacement['boundaryEvidence']
        old, new = set(before['observationKeys']), set(after['observationKeys'])
        added, removed = new - old, old - new
        allowed_evidence = {eid for ref in packet['contextRefs']
            if ref['canonicalContent'].get('kind') == 'PROTOTYPE_OBSERVATION_REF'
            and added.intersection(ref['canonicalContent']['observationKeys'])
            for eid in ref['canonicalContent']['evidenceIds']}
        old_evidence, new_evidence = set(before['evidenceIds']), set(after['evidenceIds'])
        if added <= missing and removed <= duplicated and old_evidence <= new_evidence and new_evidence - old_evidence <= allowed_evidence:
            before['observationKeys'] = after['observationKeys']
            before['evidenceIds'] = after['evidenceIds']
    preserve_roots(adjusted, result, 'decisions', set())


def _preserve_scope_candidate(action_kind, packet, result):
    from candidate_repair import repair_baseline, preserve_roots
    baseline=repair_baseline(packet, action_kind+'-v1')
    if baseline is None: return
    previous, diagnostic=baseline
    roots=set(diagnostic['subjectIds'])
    if action_kind=='SOURCE_SCAN' and diagnostic['code'].startswith('SCAN_'):
        def wrap(rows): return {'items':[{**row,'localKey':row['coverageRootId']} for row in rows]}
        preserve_roots(wrap(previous),wrap(result),'items',roots,allow_new=lambda row:row['localKey'] in roots)
    elif action_kind=='SOURCE_AUDIT' and diagnostic['code'].startswith('AUDIT_'):
        def wrap(value): return {'checks':[{**row,'localKey':row['coverageRootId']+'|'+row['category']} for row in value['checks']]}
        preserve_roots(wrap(previous),wrap(result),'checks',roots,allow_new=lambda row:row['localKey'] in roots)
    elif action_kind.startswith('SCOPE_') and diagnostic['code'].startswith('SCOPE_'):
        if diagnostic['path'] == '/observations':
            _preserve_observation_bindings(packet, previous, result)
            return
        # Scope owns incoming-reference closure; a Task/Story never uses it to alter Scope.
        while True:
            incoming={row['localKey'] for row in previous['decisions'] if any(
                roots.intersection(rel['targetLocalKeys']) for rel in row['relations'])}
            if incoming <= roots: break
            roots.update(incoming)
        facts, _, _, observations = _scope_dependency_catalog(packet)
        missing=facts-{key for row in previous['decisions'] for key in row['factIds']}
        authorized=missing|{key for row in previous['decisions'] if row['localKey'] in roots for key in row['factIds']}
        preserve_roots(previous,result,'decisions',roots,allow_new=lambda row:
            bool(row['factIds']) and set(row['factIds']) <= authorized)


def validate_bound_scope_result(action_kind, packet, normalized_result):
    """Pure pre-seal binding only; context/schema validation precedes this callback."""
    result = json.loads(normalized_result)
    _preserve_scope_candidate(action_kind, packet, result)
    if action_kind == "SOURCE_SCAN":
        _verify_scan_bindings(packet, result)
    elif action_kind == "SOURCE_AUDIT":
        _verify_audit_bindings(packet, result)
    elif action_kind in {"SCOPE_SYNTHESIS", "SCOPE_PROPOSAL", "SCOPE_JOIN"}:
        _verify_scope_bindings(packet, result)
    else:
        raise ValueError("未知 Scope action kind。")


# Deterministic Owner materialization.
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ScopeMaterialization:
    candidate_bytes: bytes
    change_graph_bytes: bytes
    prior_state_bytes: bytes | None
    identity_by_local_key: Mapping[str, str]
    review_obligations: tuple[Mapping[str, object], ...] = ()


def _complete_scope_results(plan, work_items, context_refs, ledger, budget_policy):
    from stage_planner import validate_stage_plan, materialize_packet, DependencyResultRef, _effective_envelope, bound_action_contract_ids

    descriptors = build_scope_work_descriptors(work_items, context_refs, budget_policy, action_contract_ids=bound_action_contract_ids(plan))
    validate_stage_plan(plan, work_items, context_refs, descriptors, [], budget_policy)
    refs, envelopes, packets, results = {}, {}, {}, {}
    for work in plan["works"]:
        key, packet_plan = work["logicalWorkId"], work["packetPlan"]
        envelope = _effective_envelope(ledger, key)
        if envelope is None or effective_result_bytes(ledger,key) is None:
            raise ScopeInputRequired("Scope plan 尚有未 sealed 的 group/work。")
        digest, result = effective_result(ledger, key)
        if envelope.value["actionContractId"] != packet_plan["actionContractId"] or envelope.value["actionContractSha256"] != packet_plan["actionContractSha256"]:
            raise ValueError("Scope effective Attempt 与冻结合同不一致。")
        normalized = effective_result_bytes(ledger,key)
        if sha256_bytes(normalized) != result.normalized_result_sha256:
            raise ValueError("Scope normalized result hash 漂移。")
        refs[key] = DependencyResultRef(key, digest, normalized,
            result.source_attempt_record_sha256 if isinstance(result,CandidateResult) else None)
        envelopes[key] = envelope
    for work in plan["works"]:
        key, packet_plan = work["logicalWorkId"], work["packetPlan"]
        repair = None
        if envelopes[key].value["revision"] > 1:
            from action_ledger import build_attempt_repair_context
            failures = [digest for digest, record in ledger.attempt_records.items()
                        if record.logical_work_id == key and record.revision == envelopes[key].value["revision"] - 1 and record.failure_kind in {"INVALID_JSON", "INVALID_IR"}]
            if len(failures) != 1:
                raise ValueError("Scope revision 2 没有唯一原始 INVALID_IR Attempt。")
            repair = build_attempt_repair_context(key, failures[0], ledger.attempt_records, ledger.raw_outputs,
                                                 envelopes_by_sha256=ledger.envelopes_by_sha256)
        packet_bytes = materialize_packet(plan, key, envelopes[key].value["revision"], work_items, context_refs,
            [refs[dependency] for dependency in packet_plan["dependencyLogicalWorkIds"]], ledger, repair)
        if sha256_bytes(packet_bytes) != envelopes[key].value["packetSha256"]:
            raise ValueError("Scope Attempt 没有绑定实际计划 packet。")
        packets[key], results[key] = json.loads(packet_bytes), json.loads(refs[key].normalized_result)
    return refs, packets, results


def _scope_source_evidence(work_items):
    evidence = {}
    for item in work_items:
        if item.action_kind != "SOURCE_SCAN":
            continue
        for block in [item.work_item_payload["sourceBlock"], *item.work_item_payload.get("contextBlocks", [])]:
            ref = {"sourceId": block["sourceId"], "blockId": block["blockId"], "sha256": block["contentSha256"], "locator": block["locator"]}
            if block["blockId"] in evidence and evidence[block["blockId"]] != ref:
                raise ValueError("来源证据身份冲突。")
            evidence[block["blockId"]] = ref
    return evidence


def _scope_identity_bindings(decisions, evidence, prior_decision, prior, *, observations=None):
    """The same stable-ID derivation serves conversion and independent root-index proof."""
    from stable_ids import stable_entity_id, PriorMatch, preserve_prior_id
    observations = observations or {}
    prior_by_key = {}
    if prior is not None:
        from prior_state import prior_entity_ids
        prior_ids = prior_entity_ids(prior_decision)
        snapshot_by_id = {item["entityId"]: item for item in prior["entities"]}
        for item in prior_decision["entities"]:
            prior_by_key[item["localKey"]] = (item, snapshot_by_id[prior_ids[item["localKey"]]])
    change_relations = [(decision, relation) for decision in decisions for relation in decision["relations"]
                        if relation["kind"] in {"REUSE_DEPENDENCY", "ADJUST", "SPLIT", "MERGE"}]
    groups_for_target = {}
    for decision, relation in change_relations:
        for key in relation["targetLocalKeys"]:
            groups_for_target.setdefault(key, []).append((decision, relation))
    by_key = {decision["localKey"]: decision for decision in decisions}
    ids, resolving = {}, set()

    def entity_id(key):
        if key in ids:
            return ids[key]
        if key in resolving:
            raise InvalidActionResult("Scope parent 关系存在循环。")
        resolving.add(key)
        decision = by_key[key]
        if decision["decisionKind"] in {"EXCLUDE", "RETIRE"}:
            raise InvalidActionResult("排除和退役处置没有目标实体身份。")
        parent_keys = [parent for relation in decision["relations"] if relation["kind"] == "PARENT" for parent in relation["targetLocalKeys"]]
        if decision["decisionKind"] == "FEATURE" and (len(parent_keys) != 1 or by_key[parent_keys[0]]["decisionKind"] != "EPIC"):
            raise InvalidActionResult("Feature 必须有唯一 Epic parent。")
        if decision["decisionKind"] != "FEATURE" and parent_keys:
            raise InvalidActionResult("只有 Feature 接受 parent。")
        parent = entity_id(parent_keys[0]) if parent_keys else None
        boundary = decision["boundaryEvidence"]
        anchors = [canonical_json_bytes(evidence[eid]).decode("utf-8") for eid in _scope_evidence_ids(decision, observations) if eid in evidence]
        if not anchors:
            raise ScopeInputRequired("当前目标缺少本轮来源身份锚点。")
        identity = stable_entity_id("scope-entity-id-v1", decision["decisionKind"], parent, anchors, (boundary["classification"],))
        matches = groups_for_target.get(key, [])
        if len(matches) == 1:
            source_decision, relation = matches[0]
            prior_keys = source_decision["priorEntityIds"]
            if len(prior_keys) == 1 and prior_keys[0] in prior_by_key:
                original, prior_entity = prior_by_key[prior_keys[0]]
                unchanged = any(item["kind"] == "UNCHANGED_IDENTITY" and item["targetLocalKeys"] == [key] for item in decision["relations"])
                ownership = sum(prior_keys[0] in item["priorEntityIds"] for item, _ in change_relations)
                relation_kind = relation["kind"] if relation["kind"] in {"SPLIT", "MERGE"} else "ONE_TO_ONE"
                match = PriorMatch(relation_kind, original.get("visiblePriorId"),
                    original.get("visiblePriorId") == prior_entity["entityId"], ownership == 1 and len(relation["targetLocalKeys"]) == 1,
                    not unchanged)
                identity = preserve_prior_id(match) or identity
        if identity in ids.values():
            raise ScopeInputRequired("Scope 证据身份碰撞；不能按名称或位置补后缀。")
        resolving.remove(key)
        ids[key] = identity
        return identity

    for key in sorted(by_key):
        if by_key[key]["decisionKind"] not in {"EXCLUDE", "RETIRE"}:
            entity_id(key)
        else:
            anchors = [canonical_json_bytes(evidence[eid]).decode("utf-8")
                for eid in _scope_evidence_ids(by_key[key], observations) if eid in evidence]
            ids[key] = stable_entity_id("scope-entity-id-v1", "ANNOTATION", None, anchors, ("EXCLUSION",))
    return ids, prior_by_key, change_relations, by_key


def scope_review_owner_index(candidate_bytes, decisions, work_items, *, prototype_inventory=None,
                             prior_decision=None, prior_state=None, context_refs=(), ledger=None):
    """Rebuild exact root identities from frozen IR and sources without converting a candidate."""
    evidence = _scope_source_evidence(work_items)
    if prototype_inventory is not None:
        for item in prototype_inventory['evidence']:
            evidence[item['evidenceId']] = {'sourceId':item['sourceId'],'blockId':item['evidenceId'],
                'sha256':item['sha256'],'locator':'file:'+item['relativePath']}
    observations = _scope_observations(context_refs, ledger)
    ids, _, _, roots = _scope_identity_bindings(decisions['decisions'], evidence, prior_decision, prior_state, observations=observations)
    model = json.loads(candidate_bytes)
    collections = {'EPIC':'epics','FEATURE':'features','DESIGN_ITEM':'designItems','INTEGRATION':'integrations',
        'NFR':'nfrs','POLICY_INSTANCE':'policyInstances','EXCLUDE':'scopeAnnotations','RETIRE':'scopeAnnotations'}
    index = {}; expected = {name:set() for name in collections.values()}
    for key, identity in ids.items():
        decision = roots[key]; kind = decision['decisionKind']; collection = collections[kind]
        id_field = NODE_COLLECTIONS[collection]
        matches = [(position,node) for position,node in enumerate(model[collection]) if node[id_field] == identity]
        if len(matches) != 1:
            raise ValueError('Scope root 未唯一映射到原来源和 parent 派生的稳定实体。')
        position, node = matches[0]
        if kind in {'EXCLUDE','RETIRE'}:
            valid = node['text'] == decision['exclusionReason']
        elif kind == 'POLICY_INSTANCE':
            valid = node['policyId'] == decision['boundaryEvidence']['classification']
        elif kind == 'NFR':
            valid = node['category'] == decision['boundaryEvidence']['classification']
        else:
            valid = node['name'] == decision['boundaryEvidence']['name']
        if not valid:
            raise ValueError('Scope root 映射节点正文不匹配 sealed IR。')
        index[key] = {'id':identity,'path':'/'+collection+'/'+str(position)}
        expected[collection].add(identity)
    for collection, identities in expected.items():
        if len(model[collection]) != len(identities) or {node[NODE_COLLECTIONS[collection]] for node in model[collection]} != identities:
            raise ValueError('Scope candidate 存在未绑定 root 的节点。')
    return index


def scope_change_graph(decisions, identities, prior_decision, prior_state):
    """Project changes only from sealed decisions and the independently resolved Prior root."""
    from prior_state import prior_entity_ids
    prior_ids = prior_entity_ids(prior_decision) if prior_decision else {}
    snapshot_ids = {row['entityId'] for row in prior_state['entities']} if prior_state else set()
    if set(prior_ids.values()) != snapshot_ids:
        raise ValueError('Scope Prior 身份必须匹配唯一 Snapshot。')
    graph = {'changeGroups':[], 'retiredPrior':[]}
    for decision in decisions['decisions']:
        if decision['decisionKind']=='RETIRE':
            graph['retiredPrior'].extend({'priorEntityId':prior_ids[key],
                'evidenceIds':sorted(decision['boundaryEvidence']['evidenceIds'])} for key in decision['priorEntityIds'])
        for relation in decision['relations']:
            if relation['kind'] in {'REUSE_DEPENDENCY','ADJUST','SPLIT','MERGE'}:
                graph['changeGroups'].append({'kind':relation['kind'],
                    'priorEntityIds':sorted(prior_ids[key] for key in decision['priorEntityIds']),
                    'targetEntityIds':sorted(identities[key] for key in relation['targetLocalKeys']),
                    'evidenceIds':sorted(relation['evidenceIds'])})
    for rows in graph.values(): rows.sort(key=canonical_json_bytes)
    return graph


def materialize_scope_candidate(input_revision_bytes, request, plan, work_items, context_refs, ledger, budget_policy, *, prior_inventories=(), prototype_inventory=None, semantic_repair=None, semantic_repairs=None):
    from stable_ids import stable_entity_id
    from sow_model import model_skeleton

    refs, packets, results = _complete_scope_results(plan, work_items, context_refs, ledger, budget_policy)
    revision = json.loads(input_revision_bytes)
    expected_revision_hash = sha256_bytes(input_revision_bytes)
    if any(ledger.envelopes_by_sha256[source_record_for_result(ledger,ref.result_sha256).envelope_sha256].value["inputRevisionSha256"] != expected_revision_hash for ref in refs.values()):
        raise ValueError("Scope Attempt 不属于当前 InputRevision。")
    prototype_refs, observation_catalog = (), {}
    selected_demo = {source["sourceId"]: source for source in revision["sources"] if source["role"] == "DEMO"}
    prototype_contexts = [json.loads(ref.canonical_content) for ref in context_refs if json.loads(ref.canonical_content).get("kind") == "PROTOTYPE_LEDGER"]
    if selected_demo or prototype_contexts or prototype_inventory is not None:
        if prototype_inventory is None or len(prototype_contexts) != 1:
            raise ScopeInputRequired("Scope 需要本轮完整的原型 inventory 和 sealed ledger。")
        if {(item["sourceId"], item["sha256"]) for item in prototype_inventory["files"]} != {(source["sourceId"], source["rawSha256"]) for source in selected_demo.values()}:
            raise ValueError("Prototype inventory 与 InputRevision 文件不一致。")
        prototype_refs = prepare_scope_prototype_contexts(prototype_inventory, prototype_contexts[0]["ledger"], ledger)
        if json.loads(prototype_refs[0].canonical_content)["inputRevisionSha256"] != expected_revision_hash:
            raise ValueError("Prototype Attempt 不属于当前 InputRevision。")
        observation_catalog = _scope_observations(prototype_refs, ledger)
    contents = {block["blockId"]: block["content"] for item in work_items if item.action_kind == "SOURCE_SCAN"
                for block in [item.work_item_payload["sourceBlock"], *item.work_item_payload.get("contextBlocks", [])]}
    expected_items, expected_contexts = prepare_scope_inputs(input_revision_bytes, contents, request=request, prior_inventories=prior_inventories, prototype_context_refs=prototype_refs)
    if {item.work_item_id: item for item in work_items} != {item.work_item_id: item for item in expected_items} or {ref.ref_id: ref for ref in context_refs} != {ref.ref_id: ref for ref in expected_contexts}:
        raise ValueError("Scope descriptors 必须完整绑定实际 InputRevision/request。")
    consumed = {dep for work in plan["works"] for dep in work["packetPlan"]["dependencyLogicalWorkIds"]}
    root_ids = set(results) - consumed
    if len(root_ids) != 1:
        raise ValueError("Scope 必须有唯一 root。")
    root = next(iter(root_ids))
    from prior_state import (resolve_prior_root, validate_bound_prior_context, validate_bound_prior_result,
                             verify_prior_decision, materialize_prior_snapshot)
    prior_works = {work["logicalWorkId"]: work for work in plan["works"] if work["packetPlan"]["actionKind"].startswith("PRIOR_")}
    prior_consumed = {dep for work in prior_works.values() for dep in work["packetPlan"]["dependencyLogicalWorkIds"]}
    prior_roots = set(prior_works) - prior_consumed
    prior_ref = resolve_prior_root(plan, ledger, [refs[key] for key in sorted(prior_roots)])
    for key, work in prior_works.items():
        arguments = {"inventories": prior_inventories, "input_revision_bytes": input_revision_bytes}
        validate_bound_prior_context(work["packetPlan"]["actionKind"], packets[key], **arguments)
        validate_bound_prior_result(work["packetPlan"]["actionKind"], packets[key], refs[key].normalized_result, **arguments)
    prior = None
    if prior_ref is not None:
        prior_decision = json.loads(prior_ref.normalized_result)
        verify_prior_decision(prior_inventories, prior_decision, input_revision_bytes=input_revision_bytes)
        prior = materialize_prior_snapshot(prior_inventories, prior_decision, input_revision_bytes=input_revision_bytes)
    fact_catalog = {}
    for work in plan["works"]:
        key, kind = work["logicalWorkId"], work["packetPlan"]["actionKind"]
        if kind == "SOURCE_SCAN":
            verify_source_scan(packets[key], results[key])
            for decision in results[key]:
                for fact in decision["facts"]:
                    fact_catalog[decision["coverageRootId"] + ":" + fact["localKey"]] = fact
        elif kind == "SOURCE_AUDIT":
            verify_source_audit(packets[key], results[key])
        elif kind.startswith("SCOPE_"):
            verify_scope_decision(packets[key], results[key])
    final_decision = results[root]
    repairs=semantic_repairs if semantic_repairs is not None else ([semantic_repair] if semantic_repair else [])
    for repair in repairs:
        from final_review import replace_owner_decisions
        final_decision = replace_owner_decisions('SCOPE', final_decision, *repair)
        verify_scope_decision(packets[root], final_decision)
    decisions = final_decision["decisions"]
    policies = [decision["boundaryEvidence"]["classification"] for decision in decisions if decision["decisionKind"] == "POLICY_INSTANCE"]
    if any(policies.count(policy_id) != 1 for policy_id in REQUIRED_POLICY_INCLUSIONS):
        raise ScopeInputRequired("Scope 必须明确处置默认自动化与必需上线政策。")
    evidence = _scope_source_evidence(work_items)
    if prototype_inventory is not None:
        for item in prototype_inventory["evidence"]:
            evidence[item["evidenceId"]] = {"sourceId": item["sourceId"], "blockId": item["evidenceId"],
                "sha256": item["sha256"], "locator": "file:" + item["relativePath"]}
    model = model_skeleton(request, revision)
    fact_ids = {}
    for handle, fact in sorted(fact_catalog.items()):
        source_refs = [evidence[eid] for eid in sorted(fact["evidenceIds"])]
        entity_id = stable_entity_id("scope-entity-id-v1", "FACT", None,
            [canonical_json_bytes(ref).decode("utf-8") for ref in source_refs], (fact["factKind"],))
        if entity_id in fact_ids.values():
            raise ScopeInputRequired("事实证据不足以区分最终身份。")
        fact_ids[handle] = entity_id
        model["inputItems"].append({"inputItemId": entity_id, "kind": fact["factKind"], "text": fact["statement"],
            "conditions": fact["qualifiers"], "thresholds": [], "prohibitions": [], "applicableScopes": [], "sourceRefs": source_refs})
    ids, prior_by_key, change_relations, by_key = _scope_identity_bindings(
        decisions, evidence, prior_decision if prior is not None else None, prior, observations=observation_catalog)
    policy_rows = {item["policyId"]: item for item in json.loads((SKILL_ROOT / "contracts/delivery-policy-v1.json").read_bytes())["policies"]}
    source_directory = {item["sourceId"]: item for item in revision["sources"]}

    def relation_keys(decision, kind):
        return sorted({target for relation in decision["relations"] if relation["kind"] == kind for target in relation["targetLocalKeys"]})

    def typed_targets(decision, relation, kinds):
        keys = relation_keys(decision, relation)
        if any(by_key[key]["decisionKind"] not in kinds for key in keys):
            raise InvalidActionResult("Scope 关系的目标类型不合法。")
        return [ids[key] for key in keys]

    def facet_values(decision, role, *, multiple=False):
        handles = [item["factId"] for item in decision["boundaryEvidence"]["facetFacts"] if item["role"] == role]
        if not handles or (not multiple and len(handles) != 1):
            raise ScopeInputRequired("目标边界缺少唯一的 " + role + " 来源事实。")
        values = [fact_catalog[handle]["statement"] for handle in sorted(handles)]
        return values if multiple else values[0]

    for decision in decisions:
        key, kind, boundary = decision["localKey"], decision["decisionKind"], decision["boundaryEvidence"]
        source_refs = [evidence[eid] for eid in _scope_evidence_ids(decision, observation_catalog) if eid in evidence]
        features = typed_targets(decision, "APPLIES_TO", {"FEATURE"}) if kind in {"DESIGN_ITEM", "INTEGRATION", "NFR"} else []
        designs = typed_targets(decision, "DESIGN", {"DESIGN_ITEM"})
        if kind in {"EPIC", "FEATURE"}:
            policy_keys = relation_keys(decision, "POLICY")
            policies = typed_targets(decision, "POLICY", {"POLICY_INSTANCE"})
            node = {"name": boundary["name"], "scopeClass": boundary["classification"], "sourceRefs": source_refs,
                    "requirementRefs": sorted(fact_ids[handle] for handle in decision["factIds"]), "designRefs": designs, "policyRefs": policies,
                    "effortPhase": "BUILD", "activationPhase": "BUILD", "inclusionPolicy": "SOURCE_GATED"}
            if policy_keys:
                rows = [policy_rows[by_key[item]["boundaryEvidence"]["classification"]] for item in policy_keys]
                phases = {(row["scopeClass"], row["effortPhase"], row["activationPhase"], row["inclusionPolicy"]) for row in rows}
                if len(phases) != 1 or rows[0]["scopeClass"] != boundary["classification"]:
                    raise ScopeInputRequired("同一实体的政策分类或生命周期存在冲突。")
                for field in ("effortPhase", "activationPhase", "inclusionPolicy"):
                    node[field] = "BUILD" if rows[0][field] == "DEVELOPMENT" else rows[0][field]
            if kind == "EPIC":
                node["epicId"] = ids[key]
                model["epics"].append(node)
            else:
                parent = relation_keys(decision, "PARENT")[0]
                node.update(featureId=ids[key], epicId=ids[parent], scopeDecision="IN_SCOPE")
                model["features"].append(node)
                features = [ids[key]]
        elif kind == "DESIGN_ITEM":
            if not source_refs or any(source_directory[ref["sourceId"]]["role"] not in APPROVED_DESIGN_ROLES or source_directory[ref["sourceId"]]["status"] != "APPROVED" for ref in source_refs):
                raise ScopeInputRequired("设计项只能由本轮批准 HLD/ADR 支持。")
            model["designItems"].append({"designItemId": ids[key], "name": boundary["name"], "featureIds": features, "sourceRefs": source_refs, "status": "APPROVED"})
        elif kind == "INTEGRATION":
            boundaries = {item["responsibilityBoundaryId"] for item in request["responsibilityBoundaries"]}
            selected = boundary.get("responsibilityBoundaryIds", [])
            if not selected or not set(selected) <= boundaries:
                raise ScopeInputRequired("Integration 必须选择 request 中已声明的责任边界。")
            model["integrations"].append({"integrationId": ids[key], "name": boundary["name"], "featureIds": features,
                "sourceRefs": source_refs, "direction": facet_values(decision, "DIRECTION"),
                "method": facet_values(decision, "METHOD"), "purpose": facet_values(decision, "PURPOSE"),
                "responsibilityBoundaryIds": selected, "counterpartyBoundary": boundary["classification"]})
        elif kind == "NFR":
            model["nfrs"].append({"nfrId": ids[key], "category": boundary["classification"], "featureIds": features,
                "sourceRefs": source_refs, "status": "DEFINED", "target": facet_values(decision, "TARGET")})
        elif kind == "POLICY_INSTANCE":
            row = policy_rows[boundary["classification"]]
            targets = typed_targets(decision, "APPLIES_TO", {"EPIC", "FEATURE"})
            if not targets or (row["sourceRoles"] and (not decision["factIds"] or any(source_directory[ref["sourceId"]]["role"] not in row["sourceRoles"] for ref in source_refs))):
                raise ScopeInputRequired("政策必须有实际目标，SOURCE_GATED 政策必须有授权来源事实。")
            model["policyInstances"].append({"policyInstanceId": ids[key], "policyId": row["policyId"],
                "targetNodeIds": targets, "inclusionPolicy": row["inclusionPolicy"], "sourceRefs": source_refs})
        elif kind in {"EXCLUDE", "RETIRE"}:
            model["scopeAnnotations"].append({"annotationId": ids[key],
                "category": "EXCLUSION", "subjectIds": sorted(fact_ids[handle] for handle in decision["factIds"]), "text": decision["exclusionReason"]})
        for handle in decision["factIds"]:
            fact = fact_catalog[handle]
            excluded = kind in {"EXCLUDE", "RETIRE"}
            project_gate = not excluded and fact["factKind"] == "ASSUMPTION"
            design_required = not project_gate and (bool(designs) or kind == "DESIGN_ITEM")
            model["scopeClosure"].append({"inputItemId": fact_ids[handle], "sourceRefs": [evidence[eid] for eid in sorted(fact["evidenceIds"])],
                "disposition": "OUT_OF_SCOPE" if excluded else "PROJECT_GATE" if project_gate else "SCOPE_NODE", "targetNodeIds": [] if excluded else [ids[key]],
                "preservedQualifiers": fact["qualifiers"], "crossFeatureRuleIds": [],
                "mechanicalCoverage": "COMPLETE" if design_required else "NOT_REQUIRED",
                "semanticSufficiency": "SUFFICIENT" if design_required else "NOT_REQUIRED",
                "designCoverageStatus": "SUFFICIENT" if design_required else "NOT_REQUIRED",
                "deliveryDisposition": "NO_DELIVERY" if excluded else "PROJECT_LEVEL_ONLY" if project_gate else "STORY_AC_REQUIRED" if features else "PROJECT_LEVEL_ONLY",
                "assignedFeatureIds": [] if project_gate else features, "requiredQualifierRefs": [], "crossFeatureTargetIds": []})
    for collection, id_field in NODE_COLLECTIONS.items():
        model[collection].sort(key=lambda node: node[id_field])
    for decision in decisions:
        for handle in decision["boundaryEvidence"]["observationKeys"]:
            reference, observation = observation_catalog[handle]
            if decision["decisionKind"] in {"EXCLUDE", "RETIRE"}:
                if observation["scopeRelation"] != "NON_SCOPE":
                    raise ScopeInputRequired("选入原型的目标需求不能静默排除。")
                continue
            if observation["scopeRelation"] == "NON_SCOPE":
                raise InvalidActionResult("NON_SCOPE 原型 observation 不能生成目标范围。")
    graph = scope_change_graph(final_decision, ids, prior_decision if prior is not None else None, prior)
    obligations = scope_review_obligations(final_decision, ids, context_refs, ledger, prior, graph, prior_ref,
                                           prior_work_items=work_items)
    return ScopeMaterialization(canonical_json_bytes(model), canonical_json_bytes(graph),
                                canonical_json_bytes(prior) if prior is not None else None, MappingProxyType(ids), tuple(obligations))


def validate_scope_candidate(material):
    from change_graph import derive_change_views
    candidate = json.loads(material.candidate_bytes)
    prior = json.loads(material.prior_state_bytes) if material.prior_state_bytes is not None else None
    target_ids = [node[field] for collection, field in NODE_COLLECTIONS.items() if collection in {"epics", "features", "designItems", "integrations", "nfrs", "policyInstances"} for node in candidate[collection]]
    derive_change_views(json.loads(material.change_graph_bytes), prior, target_ids)
    return validate_sow_model(candidate, "STAGE_1", registry=load_registry(SKILL_ROOT / "contracts"))


def publish_scope_candidate(files, run_id, material):
    candidate_hash, graph_hash = sha256_bytes(material.candidate_bytes), sha256_bytes(material.change_graph_bytes)
    base = f".ai-sow/work/runs/{run_id}/stages/SCOPE"
    files.publish_new(f"{base}/change-graphs/{graph_hash}.json", material.change_graph_bytes)
    files.publish_new(f"{base}/candidates/{candidate_hash}.json", material.candidate_bytes)
    return {"candidateSha256": candidate_hash, "changeGraphSha256": graph_hash}


def scope_review_obligations(decisions, identity_by_local_key, context_refs, ledger, prior_state, change_graph, prior_root_ref, *, prior_work_items=()):
    """Reconstruct every intent/identity obligation from sealed evidence, without conversion."""
    observations=_scope_observations(context_refs, ledger)
    obligations=[]
    for reference in context_refs:
        value=json.loads(reference.canonical_content)
        if value.get('kind')=='SCOPE_CONTEXT' and value.get('declaredChangeContext') is not None:
            obligations.append({'kind':'DECLARED_CHANGE_CONTEXT','inputRevisionSha256':value['inputRevisionSha256'],
                'declaredChangeContext':value['declaredChangeContext']})
    for decision in decisions['decisions']:
        for key in decision['boundaryEvidence']['observationKeys']:
            reference,observation=observations[key]
            if decision['decisionKind'] not in {'EXCLUDE','RETIRE'} and observation['runtimeStatus']=='CODE_ONLY':
                obligations.append({'kind':'PROTOTYPE_INTENT','round':reference['round'],'localKey':observation['localKey'],
                    'attemptRecordSha256':reference['attemptRecordSha256'],'normalizedResultSha256':reference['normalizedResultSha256'],
                    'sourceEvidenceIds':sorted(observation['evidenceIds']),'targetEntityIds':[identity_by_local_key[decision['localKey']]],'observation':observation})
    if prior_state is not None:
        if prior_root_ref is None: raise ValueError('Prior review obligation 缺少实际 root。')
        prior_hash=sha256_bytes(canonical_json_bytes(prior_state))
        prior_decision = json.loads(prior_root_ref.normalized_result)
        if 'unextractedEvidence' in prior_decision:
            from prior_state import prior_entity_ids
            entity_ids = prior_entity_ids(prior_decision)
            indexes = {item.work_item_payload['sourceId']:item.work_item_payload['priorContext']
                       for item in prior_work_items if item.action_kind == 'PRIOR_ANALYZE'}
            if not indexes:
                raise ValueError('Prior v2 review 缺少冻结来源索引。')
            for source_id, context in sorted(indexes.items()):
                obligations.append({'kind':'PRIOR_EXTRACTION',
                    'reviewInstruction':'对 PRIOR_EXTRACTION，核对每个实体的本项目肯定交付依据，不能把估算目录、模板、示例或重复汇总当成历史能力。unextractedEvidence 仅是 Author 的解释；必须通过其中 evidenceIds 和 priorContext 位置索引调用现有 hydrate 阅读被排除行原文，并结合 priorState 的实体与证据核验。复核转置、跨行、跨 Sheet 限定及 entityAnchors 的实际语义：全局验收、责任、排除和时间条款必须进入相关实体 semanticSummary，不能藏在“未形成实体”理由中。容量不足不能代填 PASS。发现冻结 Prior 抽取错误且当前 Scope root Repair 不能修改时报告 OWNER_BUG，保留原证据，不强行删除依赖或改成无关。',
                    'priorRootAttemptRecordSha256':prior_root_ref.source_attempt_record_sha256 or prior_root_ref.result_sha256,
                    'priorStateSha256':prior_hash,'priorContext':context,
                    'unextractedEvidence':[row for row in prior_decision['unextractedEvidence'] if row['sourceId']==source_id],
                    'entityAnchors':[{'entityId':entity_ids[row['localKey']],'cellAnchors':row['cellAnchors']}
                                     for row in prior_decision['entities'] if row['sourceId']==source_id and row.get('cellAnchors')]})
        for retired in change_graph['retiredPrior']:
            obligations.append({'kind':'PRIOR_IDENTITY','priorEntityIds':[retired['priorEntityId']],'targetEntityIds':[],
                'relationKind':'RETIRE','evidenceIds':retired['evidenceIds'],
                'priorRootAttemptRecordSha256':prior_root_ref.source_attempt_record_sha256 or prior_root_ref.result_sha256,'priorStateSha256':prior_hash,
                'unchangedIdentityClaimed':False})
        for group in change_graph['changeGroups']:
            unchanged=any(relation['kind']=='UNCHANGED_IDENTITY' and
                set(identity_by_local_key[key] for key in relation['targetLocalKeys']).intersection(group['targetEntityIds'])
                for decision in decisions['decisions'] for relation in decision['relations'])
            obligations.append({'kind':'PRIOR_IDENTITY','priorEntityIds':group['priorEntityIds'],'targetEntityIds':group['targetEntityIds'],
                'relationKind':group['kind'],'evidenceIds':group['evidenceIds'],
                'priorRootAttemptRecordSha256':prior_root_ref.source_attempt_record_sha256 or prior_root_ref.result_sha256,'priorStateSha256':prior_hash,
                'unchangedIdentityClaimed':unchanged})
    return tuple(sorted(obligations,key=canonical_json_bytes))


def diagnose_candidate(action_kind, packet, candidate, **owner_context):
    from candidate_repair import schema_issues, diagnostic_report, issues_from_diagnostics
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    issues=schema_issues(owner_context.get('action_contract_id',action_kind+'-v1'),value,'SCOPE')
    blocked=[];domains=['SCHEMA'];diagnostics=[]
    checker={'SOURCE_SCAN':_verify_scan_bindings,'SOURCE_AUDIT':_verify_audit_bindings,
             'SCOPE_SYNTHESIS':_verify_scope_bindings,'SCOPE_PROPOSAL':_verify_scope_bindings,'SCOPE_JOIN':_verify_scope_bindings}[action_kind]
    try:
        checker(packet,value,diagnostics=diagnostics)
    except (KeyError,TypeError,IndexError):
        blocked.append('SCOPE_BINDINGS')
    else:
        domains.append('SCOPE_BINDINGS')
    issues+=issues_from_diagnostics(diagnostics,'SCOPE',value)
    return diagnostic_report(raw,issues,owner='SCOPE',checker_file=__file__,packet=packet,
        origin=owner_context.get('origin'),blocked=blocked,domains=domains)


def plan_candidate_repair(action_kind, packet, candidate, report, *, origin, **owner_context):
    from candidate_repair import group_fields, build_repair_plan
    value=json.loads(candidate) if isinstance(candidate,bytes) else candidate
    selected={}
    for issue in report['issues']:
        path=issue['paths'][0];paths=[path]
        if action_kind=='SOURCE_SCAN' and not issue['code'].startswith('SCHEMA_'):
            parts=path.split('/');matches=[i for i,row in enumerate(value) if row['coverageRootId']==parts[1]]
            if len(matches)==1:
                i=matches[0];path='/'+str(i)
                if len(parts)>3:
                    facts=[j for j,row in enumerate(value[i]['facts']) if row['localKey']==parts[3]]
                    if len(facts)==1:path+='/facts/'+str(facts[0])+'/evidenceIds'
                paths=[path]
        elif action_kind=='SOURCE_AUDIT' and issue['code']=='AUDIT_REFERENCE_UNBOUND':
            parts=path.split('/')
            matches=[i for i,row in enumerate(value['checks']) if row['coverageRootId']==parts[2] and row['category']==parts[3]]
            paths=[f'/checks/{i}/{field}' for i in matches for field in ('relatedFactKeys','evidenceIds')]
        elif issue['code']=='SCOPE_BOUNDARY_REFERENCE_UNBOUND':
            row=value['decisions'][int(path.split('/')[2])];facts,priors,evidence,observations=_scope_dependency_catalog(packet)
            paths=[]
            for field,allowed in [('evidenceIds',evidence),('observationKeys',observations)]:
                if not set(row['boundaryEvidence'][field])<=allowed:paths.append(path+'/'+field)
            if not {f['factId'] for f in row['boundaryEvidence']['facetFacts']}<=facts:paths.append(path+'/facetFacts')
            if not set(row['priorEntityIds'])<=priors:paths.append(path.rsplit('/',1)[0]+'/priorEntityIds')
        elif issue['code'] in {'SCOPE_RELATION_REFERENCE_UNBOUND','SCOPE_RELATION_ENDPOINT_INVALID'}:
            paths=[path+'/targetLocalKeys',path+'/evidenceIds']
        elif issue['code']=='SCOPE_BINDING_INVALID' and path=='/observations':
            holders={subject['objectId'].removeprefix('decisions/') for subject in issue['subjects']}
            paths=[f"/decisions/{i}/boundaryEvidence/observationKeys" for i,row in enumerate(value['decisions'])
                   if not holders or row['localKey'] in holders]
        selected[issue['issueId']]=paths
    contract_id=owner_context.get('action_contract_id',action_kind+'-v1')
    groups=group_fields(candidate,report,contract_id,selected)
    if action_kind=='SOURCE_SCAN':
        from candidate_repair import index_candidate
        raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate)
        index={row['objectId']:row for row in index_candidate(
            raw,inherited=report.get('objectIndex',()))}
        for group in groups:
            for position,slot in enumerate(group['slots']):
                if slot['operation']!='SET_FIELD' or slot.get('field')!='disposition':
                    continue
                row=value[int(index[slot['objectId']]['path'].removeprefix('/'))]
                fields=['disposition','facts','noRelevantReason']
                old={field:row.get(field,{'$repairMissing':True}) for field in fields}
                group['slots'][position]={
                    'slotId':'slot-'+sha256_bytes(canonical_json_bytes(
                        [slot['objectId'],fields]))[:24],
                    'operation':'SET_FIELDS','collection':slot['collection'],
                    'objectId':slot['objectId'],'fields':fields,
                    'oldValueSha256':sha256_bytes(canonical_json_bytes(old)),
                    'valueSchema':{
                        'oneOf':[
                            {'type':'object','additionalProperties':False,
                             'required':['disposition'],
                             'properties':{'disposition':{'const':'FACT'}}},
                            {'type':'object','additionalProperties':False,
                             'required':['disposition','facts','noRelevantReason'],
                             'properties':{
                                 'disposition':{'const':'NO_RELEVANT_FACT'},
                                 'facts':{'const':[]},
                                 'noRelevantReason':{'type':'string','pattern':'\\S'}}},
                        ]}}
                group['readSet']=[
                    {'objectId':slot['objectId'],'fields':fields}
                    if read['objectId']==slot['objectId'] else read
                    for read in group['readSet']]
        for group in groups:
            for position,slot in enumerate(group['slots']):
                if slot['operation']!='SET_FIELD' or slot.get('field')!='facts':
                    continue
                row=value[int(index[slot['objectId']]['path'].removeprefix('/'))]
                if row.get('facts')!=[] or not isinstance(row.get('reason'),str) or not row['reason'].strip():
                    continue
                fields=['disposition','facts','noRelevantReason']
                old={field:row.get(field,{'$repairMissing':True}) for field in fields}
                replacement={
                    'disposition':'NO_RELEVANT_FACT',
                    'facts':[],
                    'noRelevantReason':row['reason']}
                group['slots'][position]={
                    'slotId':'slot-'+sha256_bytes(canonical_json_bytes(
                        [slot['objectId'],fields]))[:24],
                    'operation':'SET_FIELDS','collection':slot['collection'],
                    'objectId':slot['objectId'],'fields':fields,
                    'oldValueSha256':sha256_bytes(canonical_json_bytes(old)),
                    'valueSchema':{'const':replacement}}
                group['readSet']=[
                    {'objectId':slot['objectId'],'fields':fields}
                    if read['objectId']==slot['objectId'] else read
                    for read in group['readSet']]
    observation_issue_ids={issue['issueId'] for issue in report['issues']
                           if issue['code']=='SCOPE_BINDING_INVALID' and issue['paths'][0]=='/observations'}
    for group in groups:
        if observation_issue_ids.intersection(group['issueIds']):
            choice='observation-'+next(iter(observation_issue_ids.intersection(group['issueIds'])))
            for slot in group['slots']:
                slot['alternativeSet']=choice
    from candidate_repair import append_object_group,schema_at,index_candidate,remove_object_group
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate)
    index_rows=index_candidate(raw,inherited=report.get('objectIndex',()))
    for issue in report['issues']:
        if issue['code'] not in {'SCAN_COVERAGE_DUPLICATE','AUDIT_PAIR_DUPLICATE'}:
            continue
        entry=next((row for row in index_rows if row['path']==issue['paths'][0]),None)
        if entry is not None:
            groups.append(remove_object_group(raw,entry,[issue['issueId']]))
    if action_kind=='SOURCE_SCAN' and isinstance(value,list):
        missing={item['payload']['coverageRootId'] for item in packet['workItems']}-{row['coverageRootId'] for row in value}
        issues=[i['issueId'] for i in report['issues'] if i['code']=='SCAN_COVERAGE_INVALID']
        # Coverage is one obligation: all missing roots form one atomic group.
        additions=[]
        for key in sorted(missing):
            schema=schema_at(contract_id,'/0');schema={**schema,'properties':{**schema['properties'],'coverageRootId':{'const':key}}}
            additions.append(append_object_group(raw,'$',schema,issues,group_id='scan-'+key))
        groups.extend(additions)
    elif action_kind=='SOURCE_AUDIT' and isinstance(value,dict) and isinstance(value.get('checks'),list):
        scans,blocks=_scan_audit_context(packet)
        missing={(root,category) for root in scans for category in AUDIT_CATEGORIES}-{(r['coverageRootId'],r['category']) for r in value['checks']}
        issues=[i['issueId'] for i in report['issues'] if i['code']=='AUDIT_COVERAGE_INVALID']
        additions=[]
        for root,category in sorted(missing):
            schema=schema_at(contract_id,'/checks/0');schema={**schema,'properties':{**schema['properties'],'coverageRootId':{'const':root},'category':{'const':category}}}
            additions.append(append_object_group(raw,'checks',schema,issues,group_id='audit-'+root+'-'+category))
        groups.extend(additions)
    if action_kind=='SOURCE_SCAN':
        field_groups=[group for group in groups
            if group['slots'] and all(slot['operation'] in {
                'SET_FIELD','SET_FIELDS','REMOVE_FIELD'} and 'alternativeSet' not in slot
                for slot in group['slots'])]
        others=[group for group in groups if group not in field_groups]
        from candidate_repair import _pointer_prefix,_slot_footprints
        index={row['objectId']:row for row in index_rows}
        batches=[]
        for group in sorted(field_groups,key=lambda item:item['groupId']):
            group_footprints=[
                footprint for slot in group['slots']
                for footprint in _slot_footprints(index,slot)]
            batch=next((entry for entry in batches
                if not any(_pointer_prefix(current,existing)
                           for current in group_footprints for existing in entry[0])),None)
            if batch is None:
                batches.append([list(group_footprints),[group]])
            else:
                batch[0].extend(group_footprints);batch[1].append(group)
        merged=[]
        for _,batch in batches:
            if len(batch)==1:
                merged.append(batch[0]);continue
            issue_ids=sorted({key for group in batch for key in group['issueIds']})
            slots=list({slot['slotId']:slot for group in batch for slot in group['slots']}.values())
            reads={}
            for group in batch:
                for read in group['readSet']:
                    reads.setdefault(read['objectId'],set()).update(read['fields'])
            merged.append({
                'groupId':'group-'+sha256_bytes(canonical_json_bytes(issue_ids))[:24],
                'issueIds':issue_ids,
                'readSet':[{'objectId':key,'fields':sorted(fields)}
                           for key,fields in sorted(reads.items())],
                'slots':slots,
                'verificationObligations':issue_ids})
        groups=[*merged,*others]
    if not groups:raise InvalidActionResult('Scope 缺口需要精确领域授权或输入，不能整阶段替换。')
    return build_repair_plan(candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate),report,groups,origin=origin)


def candidate_repair_context(action_kind, packet, candidate, plan, group):
    value=json.loads(candidate);index={r['objectId']:r for r in plan['objectIndex']}
    paths=[index[slot['objectId']]['path'] for slot in group['slots'] if slot['objectId'] in index]
    if action_kind=='SOURCE_SCAN':
        roots={value[int(path.split('/')[1])]['coverageRootId'] for path in paths if path.split('/')[1].isdigit()}
        roots.update(slot.get('valueSchema',{}).get('properties',{}).get('coverageRootId',{}).get('const')
                     for slot in group['slots'])
        roots.discard(None)
        return [item['payload'] for item in packet['workItems'] if item['payload']['coverageRootId'] in roots]
    facts,roots,evidence=set(),set(),set()
    if action_kind=='SOURCE_AUDIT':
        for path in paths:
            parts=path.split('/')
            if len(parts)>2 and parts[1]=='checks' and parts[2].isdigit():
                roots.add(value['checks'][int(parts[2])]['coverageRootId'])
        roots.update(slot.get('valueSchema',{}).get('properties',{}).get('coverageRootId',{}).get('const')
                     for slot in group['slots'])
        roots.discard(None)
    else:
        for path in paths:
            parts=path.split('/')
            if len(parts)>2 and parts[1]=='decisions' and parts[2].isdigit():
                row=value['decisions'][int(parts[2])]
                facts.update(row['factIds']);evidence.update(row['boundaryEvidence']['evidenceIds'])
    result=[]
    for ref in packet['contextRefs']:
        body=ref['canonicalContent']
        if body.get('kind')=='DEPENDENCY_RESULT' and isinstance(body['normalizedResult'],list):
            for decision in body['normalizedResult']:
                selected=[fact for fact in decision['facts'] if decision['coverageRootId'] in roots or decision['coverageRootId']+':'+fact['localKey'] in facts]
                if selected:result.append({'coverageRootId':decision['coverageRootId'],'facts':selected})
        elif body.get('kind')=='SOURCE_BLOCK' and body.get('coverageRootId') in roots:
            result.append(body)
        elif body.get('kind')=='SCOPE_CONTEXT':
            result.append({key:body[key] for key in ('responsibilityBoundaries','sourceDirectory') if key in body})
    # Related keys and kinds are read-only. They authorize no object replacement.
    if isinstance(value,dict) and 'decisions' in value:
        result.append({'kind':'OWNER_REFERENCE_INDEX','items':[{'localKey':row['localKey'],'decisionKind':row['decisionKind'],
            'name':row['boundaryEvidence']['name']} for row in value['decisions']]})
    return result
