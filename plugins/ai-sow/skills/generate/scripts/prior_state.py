from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import re
import json

from contracts import canonical_json_bytes, sha256_bytes, load_schema_registry, validate_contract, InvalidActionResult
from contracts import prior_dependencies as _prior_dependencies
from models import ContextRefDescriptor
from stable_ids import stable_entity_id

PriorWorkbookInventory = dict[str, object]


SKILL_ROOT = Path(__file__).parents[1]


def prior_decision_schema(decision):
    return "prior-state-decision-v2.schema.json" if "unextractedEvidence" in decision else "prior-state-decision.schema.json"


def prior_context(source_id, inventory):
    return {"sourceId": source_id, "workbookSha256": inventory["workbookSha256"], "evidence": [
        {key: row[key] for key in ("priorEvidenceId", "sheet", "absoluteA1Range")} for row in inventory["evidence"]]}


def _context_anchors(context, evidence):
    source_id = context["sourceId"]
    rows = {key[1]: row for key, row in evidence.items() if key[0] == source_id}
    if (not rows or context["workbookSha256"] != next(iter(rows.values()))["workbookSha256"]
            or len(context["evidence"]) != len(rows)
            or {canonical_json_bytes(row) for row in context["evidence"]} != {
                canonical_json_bytes({key: row[key] for key in ("priorEvidenceId", "sheet", "absoluteA1Range")}) for row in rows.values()}):
        raise ValueError("Prior context 索引必须完整绑定本 revision 的同一来源原文。")
    return {(source_id, key) for key in rows}


def hydrate_prior_evidence(packet, requested, *, inventories, input_revision_bytes):
    evidence = _inventory_evidence(inventories, _verified_revision(input_revision_bytes))
    anchors = set()

    def visit(value):
        if isinstance(value, list):
            for row in value: visit(row)
        elif isinstance(value, dict):
            if "priorContext" in value:
                anchors.update(_context_anchors(value["priorContext"], evidence))
            for row in value.values(): visit(row)
    visit(packet)
    result = {}
    for source_id, key in sorted(anchors):
        if key in requested:
            # Identical XLSX bytes can be explicitly selected under two source IDs.
            result.setdefault(key, {"kind": "PRIOR_EVIDENCE", "evidence": []})["evidence"].append(evidence[(source_id, key)])
    return result


def resolve_prior_root(plan, ledger, result_refs):
    works = {work["logicalWorkId"]: work for work in plan["works"] if work["packetPlan"]["actionKind"] in {"PRIOR_ANALYZE", "PRIOR_CONSOLIDATE"}}
    if not works:
        if result_refs:
            raise ValueError("零 prior 不接受 result ref。")
        return None
    if plan["stageKind"] != "SCOPE" or len({work["logicalWorkId"] for work in plan["works"]}) != len(plan["works"]):
        raise ValueError("Prior 需要完整唯一的 SCOPE StagePlan。")
    effective_records = {}
    for logical_id, work in works.items():
        packet = work["packetPlan"]
        dependencies = packet["dependencyLogicalWorkIds"]
        if not set(dependencies) <= works.keys() or len(dependencies) != len(set(dependencies)):
            raise ValueError("Prior dependency 不在冻结 Prior DAG 中。")
        if (packet["actionKind"] == "PRIOR_ANALYZE" and dependencies) or (packet["actionKind"] == "PRIOR_CONSOLIDATE" and len(dependencies) < 2):
            raise ValueError("Prior leaf/consolidation 拓扑无效。")
        expected_id = "logical-" + sha256_bytes(canonical_json_bytes({"stageKind": plan["stageKind"], "packetPlanSha256": sha256_bytes(canonical_json_bytes(packet))}))
        allowed_contracts = {packet["actionKind"] + "-v1", packet["actionKind"] + "-v2"}
        if packet["actionKind"] == "PRIOR_ANALYZE":
            allowed_contracts.add("PRIOR_ANALYZE-v3")
        if logical_id != expected_id or packet["actionContractId"] not in allowed_contracts:
            raise ValueError("Prior PacketPlan 身份或 Action kind 漂移。")
        envelopes = [item for item in ledger.envelopes_by_sha256.values() if item.value["logicalWorkId"] == logical_id]
        if not envelopes:
            raise ValueError("Prior dependency 缺少 Attempt。")
        latest = max((item.value["revision"], item.value["attempt"]) for item in envelopes)
        effective = [item for item in envelopes if (item.value["revision"], item.value["attempt"]) == latest]
        if len(effective) != 1 or effective[0].value["actionContractId"] != packet["actionContractId"] or effective[0].value["actionContractSha256"] != packet["actionContractSha256"]:
            raise ValueError("Prior effective Attempt kind 或合同不一致。")
        records = [(digest, record) for digest, record in ledger.attempt_records.items() if record.envelope_sha256 == effective[0].sha256 and record.outcome == "SUCCEEDED"]
        from action_ledger import effective_result
        effective_records[logical_id] = effective_result(ledger,logical_id)
    consumed = {key for work in works.values() for key in work["packetPlan"]["dependencyLogicalWorkIds"]}
    roots = set(works) - consumed
    if len(roots) != 1 or len(result_refs) != 1:
        raise ValueError("Prior 必须形成唯一 root ref。")
    root_id = next(iter(roots))
    ref = result_refs[0]
    if ref.logical_work_id != root_id:
        raise ValueError("Prior root logicalWorkId 不匹配。")
    digest, result = effective_records[root_id]
    if (digest != ref.result_sha256 or result.normalized_result_sha256 != sha256_bytes(ref.normalized_result)
            or getattr(result,'source_attempt_record_sha256',None) != ref.source_attempt_record_sha256):
        raise ValueError("Prior root ref 未由唯一 effective normalized result 证明。")
    return ref


def validate_bound_prior_context(action_kind, packet, *, inventories, input_revision_bytes: bytes):
    revision = _verified_revision(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    _packet_date(action_kind, packet, input_revision_bytes, revision)
    _packet_sources(action_kind, packet, evidence)
    dependencies = _prior_dependencies(action_kind, packet)
    keys = []
    for dependency in dependencies:
        if validate_contract(dependency, prior_decision_schema(dependency), load_schema_registry(SKILL_ROOT)):
            raise ValueError("冻结 Prior dependency schema 无效。")
        try:
            _validate_decision(dependency, evidence)
        except InvalidActionResult as error:
            raise ValueError("冻结 Prior dependency 引用无效。") from error
        keys.extend(item["localKey"] for item in dependency["entities"])
    if len(keys) != len(set(keys)):
        raise ValueError("冻结 Prior dependencies 重复 entity localKey。")


def _packet_date(action_kind, packet, input_revision_bytes, revision):
    if action_kind not in {"PRIOR_ANALYZE", "PRIOR_CONSOLIDATE"}:
        raise ValueError("未知 Prior Action。")
    refs = [item for item in packet["contextRefs"] if item["refId"] == "PROJECT_EFFECTIVE_START" or item["canonicalContent"].get("kind") == "PROJECT_EFFECTIVE_START"]
    expected = {"kind": "PROJECT_EFFECTIVE_START", "inputRevisionSha256": sha256_bytes(input_revision_bytes), "plannedEffectiveDate": revision["project"]["plannedEffectiveDate"]}
    if len(refs) != 1 or refs[0] != {"refId": "PROJECT_EFFECTIVE_START", "canonicalContent": expected, "contentSha256": sha256_bytes(canonical_json_bytes(expected))}:
        raise ValueError("Prior packet 必须恰有一个绑定 immutable revision 的 PROJECT_EFFECTIVE_START。")


def _packet_sources(action_kind, packet, evidence):
    items = packet["workItems"]
    if len({item["workItemId"] for item in items}) != len(items) or (action_kind == "PRIOR_ANALYZE" and not items):
        raise ValueError("冻结 Prior workItems 必须完整且唯一。")
    for item in items:
        payload = item["payload"]
        ids = payload["evidenceIds"]
        if not ids or len(ids) != len(set(ids)) or any((payload["sourceId"], evidence_id) not in evidence for evidence_id in ids):
            raise ValueError("冻结 Prior work item source/evidence 未获本 revision 授权。")
        if "priorContext" in payload:
            if payload["priorContext"]["sourceId"] != payload["sourceId"]:
                raise ValueError("Prior context 不得扩展到其它 work item 来源。")
            _context_anchors(payload["priorContext"], evidence)


def _decision_authority(decision, evidence):
    entities = {item["localKey"]: item for item in decision["entities"]}
    cited = decision["entities"] + decision.get("unextractedEvidence", [])
    sources = {item["sourceId"] for item in cited + decision["unsupportedRegions"]}
    anchors = {(item["sourceId"], evidence_id) for item in cited for evidence_id in item["evidenceIds"]}
    for relation in decision["sourceRelations"]:
        endpoints = {relation["sourceAId"], relation["sourceBId"]}
        sources.update(endpoints)
        anchors.update((source_id, evidence_id) for source_id in endpoints for evidence_id in relation["evidenceIds"] if (source_id, evidence_id) in evidence)
    for relation in decision["entitySupersessions"]:
        endpoints = {entities[key]["sourceId"] for key in relation["predecessorLocalKeys"] + relation["successorLocalKeys"]}
        anchors.update((source_id, evidence_id) for source_id in endpoints for evidence_id in relation["evidenceIds"] if (source_id, evidence_id) in evidence)
    return sources, anchors


def _preserve_prior_rows(previous, current, collection, editable, *, expansion=None, allow_new=None, replacements=0):
    """Compare anonymous rows mechanically; the Owner selects the affected rows."""
    from models import AttemptDiagnostic
    remaining = list(current.get(collection, []))
    for index, row in enumerate(previous.get(collection, [])):
        if index in editable:
            continue
        match = next((i for i, value in enumerate(remaining) if value == row), None)
        if match is None and expansion is not None:
            match = next((i for i, value in enumerate(remaining) if expansion(row, value)), None)
        if match is None:
            raise InvalidActionResult('Prior 修复改变了未定位的行。', diagnostic=AttemptDiagnostic(
                'REPAIR_SCOPE_VIOLATION', f'/{collection}/{index}', ()))
        remaining.pop(match)
    if sum(not (allow_new is not None and allow_new(row)) for row in remaining) > replacements:
        raise InvalidActionResult('Prior 修复新增了影响范围之外的行。', diagnostic=AttemptDiagnostic(
            'REPAIR_SCOPE_VIOLATION', '/' + collection, ()))


def _prior_evidence_expansion(before, after, allowed):
    old, new = set(before.get('evidenceIds', [])), set(after.get('evidenceIds', []))
    return (old <= new and new - old <= allowed
            and {key: value for key, value in before.items() if key != 'evidenceIds'}
            == {key: value for key, value in after.items() if key != 'evidenceIds'})


def _preserve_prior_candidate(action_kind, packet, result, evidence=None):
    from collections import Counter
    from copy import deepcopy
    from candidate_repair import repair_baseline, preserve_roots
    # Consolidate already enforces immutable dependency entities; Analyze owns its candidate entities.
    if action_kind != 'PRIOR_ANALYZE': return
    baseline = repair_baseline(packet, 'PRIOR_ANALYZE-v1')
    if baseline is None: return
    previous, diagnostic = baseline
    if not diagnostic['code'].startswith('PRIOR_'): return
    roots = set(diagnostic['subjectIds'])
    assigned = {(item['payload']['sourceId'], eid) for item in packet['workItems']
                for eid in item['payload']['evidenceIds']}
    coverage = diagnostic['code'] == 'PRIOR_EVIDENCE_COVERAGE_INVALID'
    missing, invalid_explanations, repairable_explanations = set(), set(), set()
    if coverage:
        gaps = _prior_coverage_gaps(packet, previous, evidence or dict.fromkeys(assigned))
        missing = gaps['missing']
        invalid_explanations = gaps['invalidRows']
        repairable_explanations = gaps['repairable']
    entities = {row['localKey']: row for row in previous['entities']}
    new_keys = {row['localKey'] for row in result['entities']} - entities.keys()
    def sources(row, collection):
        if collection == 'sourceRelations': return {row['sourceAId'], row['sourceBId']}
        if collection == 'entitySupersessions':
            return {entities[key]['sourceId'] for key in row['predecessorLocalKeys'] + row['successorLocalKeys'] if key in entities}
        return {row['sourceId']}
    def expansion(before, after, collection):
        allowed = {eid for source, eid in missing if source in sources(before, collection)}
        return coverage and _prior_evidence_expansion(before, after, allowed)
    def missing_row(row, allowed):
        return bool(row['evidenceIds']) and {(row['sourceId'], eid) for eid in row['evidenceIds']} <= allowed
    mutable = set()
    path = diagnostic['path'].split('/')
    for collection in ('sourceRelations', 'unextractedEvidence', 'unsupportedRegions', 'entitySupersessions'):
        selected = ({int(path[2])} if len(path) > 2 and path[1] == collection and path[2].isdigit() else set())
        editable = set(selected)
        if collection == 'unextractedEvidence': editable.update(invalid_explanations)
        related = lambda row: bool((roots | new_keys).intersection(row['predecessorLocalKeys'] + row['successorLocalKeys']))
        if collection == 'entitySupersessions':
            editable.update(index for index, row in enumerate(previous[collection]) if related(row))
        def allowed(row):
            if collection == 'entitySupersessions': return related(row)
            if coverage and collection == 'unextractedEvidence': return missing_row(row, missing | repairable_explanations)
            if coverage and collection == 'unsupportedRegions': return (row['sourceId'], row['regionId']) in missing
            return False
        _preserve_prior_rows(previous, result, collection, editable,
            expansion=(lambda before, after: expansion(before, after, collection)) if collection != 'unsupportedRegions' else None,
            allow_new=allowed, replacements=len(selected))
        mutable.add(collection)
    adjusted = deepcopy(previous)
    replacements = {row['localKey']: row for row in result['entities']}
    for index, row in enumerate(previous['entities']):
        replacement = replacements.get(row['localKey'])
        if replacement is not None and expansion(row, replacement, 'entities'):
            adjusted['entities'][index] = replacement
    preserve_roots(adjusted, result, 'entities', roots, mutable_fields=mutable,
        allow_new=lambda row: (coverage and missing_row(row, missing)) or any(
            old['localKey'] in roots and old['sourceId'] == row['sourceId']
            and set(row['evidenceIds']) <= set(old['evidenceIds']) for old in previous['entities']))


def validate_bound_prior_result(action_kind, packet, normalized_result: bytes, *, inventories, input_revision_bytes: bytes):
    revision = _canonical_value(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    _packet_date(action_kind, packet, input_revision_bytes, revision)
    _packet_sources(action_kind, packet, evidence)
    dependencies = _prior_dependencies(action_kind, packet)
    result = json.loads(normalized_result)
    _preserve_prior_candidate(action_kind,packet,result,evidence)
    sources = {item["payload"]["sourceId"] for item in packet["workItems"]}
    anchors = {(item["payload"]["sourceId"], evidence_id) for item in packet["workItems"] for evidence_id in item["payload"]["evidenceIds"]}
    assigned = set(anchors)
    if "unextractedEvidence" in result:
        for item in packet["workItems"]:
            if "priorContext" in item["payload"]:
                anchors.update(_context_anchors(item["payload"]["priorContext"], evidence))
    source_owners = defaultdict(set)
    for index, dependency in enumerate(dependencies):
        dependency_sources, dependency_anchors = _decision_authority(dependency, evidence)
        sources.update(dependency_sources)
        anchors.update(dependency_anchors)
        for source_id in dependency_sources:
            source_owners[source_id].add(index)
    _validate_decision(result, {key: evidence[key] for key in anchors}, source_ids=sources)
    if action_kind == "PRIOR_ANALYZE":
        from models import AttemptDiagnostic
        for index, entity in enumerate(result["entities"]):
            matches = [item for item in packet["workItems"] if entity["localKey"].startswith(item["workItemId"] + ":")]
            owner = matches[0]['payload'] if len(matches)==1 else None
            allowed = set(owner['evidenceIds']) if owner else set()
            owner_anchors = allowed.intersection(entity['evidenceIds'])
            if owner and "unextractedEvidence" in result and "priorContext" in owner:
                allowed.update(eid for _, eid in _context_anchors(owner["priorContext"], evidence))
            elif owner and owner.get('priorInputLayout')=='ai-sow-prior-row-partition-v1':
                sheet = owner['sheet']['sheet']
                for item in packet['workItems']:
                    payload=item['payload']
                    if (payload.get('priorInputLayout')=='ai-sow-prior-row-partition-v1'
                            and payload['sourceId']==owner['sourceId'] and payload['sheet']['sheet']==sheet):
                        allowed.update(eid for eid in payload['evidenceIds']
                            if evidence[(payload['sourceId'],eid)]['sheet']==sheet)
            if (owner is None or entity['sourceId']!=owner['sourceId'] or not owner_anchors or not set(entity['evidenceIds'])<=allowed
                    or any(anchor['evidenceId'] not in owner_anchors for anchor in entity.get('cellAnchors', []))):
                raise InvalidActionResult("Prior 实体须绑定所属工作项主证据；上下文仅限冻结授权的同一来源。",
                    diagnostic=AttemptDiagnostic('PRIOR_ENTITY_PARTITION_BINDING_INVALID',f'/entities/{index}',(entity['localKey'],)))
        if "unextractedEvidence" in result:
            gaps = _prior_coverage_gaps(packet, result, evidence)
            if any(gaps[key] for key in ('missing', 'duplicate', 'unassigned', 'alreadyUsed')):
                raise InvalidActionResult("Prior 分配证据必须完整引用或说明；未提取说明不得重复、越权或重述已引用证据。",
                    diagnostic=AttemptDiagnostic('PRIOR_EVIDENCE_COVERAGE_INVALID','/unextractedEvidence',()))
    else:
        expected_entities = [item for dependency in dependencies for item in dependency["entities"]]
        if sorted(result["entities"], key=canonical_json_bytes) != sorted(expected_entities, key=canonical_json_bytes):
            raise InvalidActionResult("Consolidation 必须原样保留全部 dependency entities/evidence。")
        expected_regions = {canonical_json_bytes(item) for dependency in dependencies for item in dependency["unsupportedRegions"]}
        if {canonical_json_bytes(item) for item in result["unsupportedRegions"]} != expected_regions:
            raise InvalidActionResult("Consolidation 不得丢失或新增 unsupportedRegions。")
        expected_explanations = [item for dependency in dependencies for item in dependency.get("unextractedEvidence", [])]
        if sorted(result.get("unextractedEvidence", []), key=canonical_json_bytes) != sorted(expected_explanations, key=canonical_json_bytes):
            raise InvalidActionResult("Consolidation 不得丢失或改写未提取说明。")
        key_owner = {item["localKey"]: index for index, dependency in enumerate(dependencies) for item in dependency["entities"]}
        for collection in ("sourceRelations", "entitySupersessions"):
            expected = {canonical_json_bytes(item) for dependency in dependencies for item in dependency[collection]}
            actual = [canonical_json_bytes(item) for item in result[collection]]
            if not expected <= set(actual) or len(actual) != len(set(actual)):
                raise InvalidActionResult("Consolidation 必须无损保留已声明关系且不得重复。")
            for item in result[collection]:
                if canonical_json_bytes(item) in expected:
                    continue
                if collection == "sourceRelations":
                    first, second = source_owners[item["sourceAId"]], source_owners[item["sourceBId"]]
                    cross_dependency = bool(first and second) and not (first & second)
                else:
                    cross_dependency = len({key_owner[key] for key in item["predecessorLocalKeys"] + item["successorLocalKeys"]}) > 1
                if not cross_dependency:
                    raise InvalidActionResult("Consolidation 只能补充跨 dependency 关系。")


class PriorInputRequired(ValueError):
    wait = "WAITING_INPUT"
    code = "PRIOR_STATE_INPUT_REQUIRED"


def _replacement_ready(entities, relations, predecessor_key, successor_key):
    graph, predecessors, successors = defaultdict(set), set(), set()
    for relation in relations:
        before, after = set(relation[predecessor_key]), set(relation[successor_key])
        statuses = {entities[key]["deliveryStatus"] for key in after}
        if not before or not after or before & predecessors or after & successors or statuses not in ({"CURRENT_BY_CONTRACT"}, {"FUTURE"}):
            raise PriorInputRequired("FULL replacement 重叠或时间状态无法唯一判断。")
        predecessors.update(before)
        successors.update(after)
        for key in before:
            graph[key].update(after)
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise PriorInputRequired("FULL replacement 存在循环。")
        if key in visited:
            return
        visiting.add(key)
        for successor in graph.get(key, ()):
            visit(successor)
        visiting.remove(key)
        visited.add(key)

    for key in list(graph):
        visit(key)


def _require_ready(decision, inventories):
    if decision["unsupportedRegions"] or any(inventory["unsupportedSurfaces"] for inventory in inventories) or any(item["relation"] == "CONFLICT" for item in decision["sourceRelations"]):
        raise PriorInputRequired("往期合同存在未消解冲突或未读取业务表面。")
    _replacement_ready({item["localKey"]: item for item in decision["entities"]}, decision["entitySupersessions"], "predecessorLocalKeys", "successorLocalKeys")


def derive_effective_prior(snapshot):
    canonical = _canonical_sources({item["sourceId"] for item in snapshot["entities"]}, snapshot["sourceRelations"])
    by_id = {item["entityId"]: item for item in snapshot["entities"]}
    if any(item["relation"] == "CONFLICT" for item in snapshot["sourceRelations"]):
        raise PriorInputRequired("存在未消解冲突。")
    _replacement_ready(by_id, snapshot["entitySupersessions"], "predecessorIds", "successorIds")
    active = {item["entityId"] for item in snapshot["entities"] if item["deliveryStatus"] == "CURRENT_BY_CONTRACT" and canonical[item["sourceId"]] == item["sourceId"]}
    for relation in snapshot["entitySupersessions"]:
        if all(by_id[entity_id]["deliveryStatus"] == "CURRENT_BY_CONTRACT" for entity_id in relation["successorIds"]):
            active.difference_update(relation["predecessorIds"])
    return {"activeEntityIds": sorted(active)}


def _canonical_sources(source_ids, relations):
    parent = {source_id: source_id for source_id in source_ids}
    for relation in relations:
        parent.setdefault(relation["sourceAId"], relation["sourceAId"])
        parent.setdefault(relation["sourceBId"], relation["sourceBId"])

    def root(source_id):
        while parent[source_id] != source_id:
            source_id = parent[source_id]
        return source_id

    for relation in relations:
        if relation["relation"] == "DUPLICATE":
            first, second = root(relation["sourceAId"]), root(relation["sourceBId"])
            parent[max(first, second)] = min(first, second)
    return {source_id: root(source_id) for source_id in parent}


def verify_prior_decision(inventories, final_decision, *, input_revision_bytes: bytes):
    revision = _verified_revision(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    if validate_contract(final_decision, prior_decision_schema(final_decision), load_schema_registry(SKILL_ROOT)):
        raise InvalidActionResult("Prior decision 未通过 schema 校验。")
    _validate_decision(final_decision, evidence)
    _require_ready(final_decision, inventories)


def _inventory_evidence(inventories, revision):
    sources = [source for source in revision["sources"] if source["role"] == "PRIOR_SOW"]
    if not sources or len({source["sourceId"] for source in revision["sources"]}) != len(revision["sources"]):
        raise ValueError("快照需要唯一、已授权的 PRIOR_SOW 来源。")
    by_hash = {inventory["workbookSha256"]: inventory for inventory in inventories}
    if len(by_hash) != len(inventories) or set(by_hash) != {source["rawSha256"] for source in sources}:
        raise ValueError("Inventory 必须恰好覆盖本 revision 的 PRIOR_SOW 字节。")
    evidence = {}
    for source in sources:
        for item in by_hash[source["rawSha256"]]["evidence"]:
            basis = {key: item[key] for key in ("workbookSha256", "sheet", "absoluteA1Range", "canonicalCellValuesSha256")}
            if item["workbookSha256"] != source["rawSha256"] or sha256_bytes(canonical_json_bytes(item["canonicalCellValues"])) != item["canonicalCellValuesSha256"] or sha256_bytes(canonical_json_bytes(basis)) != item["priorEvidenceId"]:
                raise ValueError("冻结 inventory 的 evidence hash 不一致。")
            key = (source["sourceId"], item["priorEvidenceId"])
            if key in evidence:
                raise ValueError("冻结 inventory 重复 evidence。")
            evidence[key] = {"sourceId": source["sourceId"], **item}
    return evidence


def _validate_decision(decision, evidence, *, source_ids=None):
    if set(decision) not in ({"entities", "sourceRelations", "entitySupersessions", "unsupportedRegions"},
                             {"entities", "sourceRelations", "entitySupersessions", "unsupportedRegions", "unextractedEvidence"}):
        raise InvalidActionResult("只接受 PriorStateDecision；Demo Observation 不能进入 As-Is。")
    current_path='';current_keys=()
    def reject(message):
        from models import AttemptDiagnostic
        raise InvalidActionResult(message, diagnostic=AttemptDiagnostic('PRIOR_BINDING_INVALID', current_path, current_keys))
    keys = [item["localKey"] for item in decision["entities"]]
    current_path='/entities';current_keys=tuple(sorted({key for key in keys if keys.count(key)>1}))
    if len(keys) != len(set(keys)):
        reject("Prior entity localKey 必须全局唯一。")
    for index, item in enumerate(decision['entities']):
        current_path='/entities/'+str(index);current_keys=(item['localKey'],)
        if not item["evidenceIds"] or len(item["evidenceIds"]) != len(set(item["evidenceIds"])) or any((item["sourceId"], evidence_id) not in evidence for evidence_id in item["evidenceIds"]):
            reject("Prior entity 必须引用自身已授权来源证据。")
        for anchor in item.get("cellAnchors", []):
            if (anchor["evidenceId"] not in item["evidenceIds"]
                    or not any(cell["address"] == anchor["address"] for cell in evidence[(item["sourceId"], anchor["evidenceId"])]["canonicalCellValues"])):
                reject("Prior cell anchor 必须定位自身引用证据中实际存在的单元格。")
        if "visiblePriorId" in item:
            visible = item["visiblePriorId"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", visible) or not any(cell["value"] == visible for evidence_id in item["evidenceIds"] for cell in evidence[(item["sourceId"], evidence_id)]["canonicalCellValues"]):
                reject("visiblePriorId 必须是所选证据中的合法 whole-cell ID literal。")
    current_path='/unsupportedRegions';current_keys=()
    if source_ids is None:
        source_ids = {key[0] for key in evidence}
    for index, region in enumerate(decision["unsupportedRegions"]):
        current_path = "/unsupportedRegions/" + str(index)
        if region["sourceId"] not in source_ids:
            reject("unsupportedRegions 必须引用已授权 Prior 来源。")
    for index, item in enumerate(decision.get('unextractedEvidence', [])):
        current_path='/unextractedEvidence/'+str(index);current_keys=()
        if (not item["evidenceIds"] or len(item["evidenceIds"]) != len(set(item["evidenceIds"]))
                or any((item["sourceId"], eid) not in evidence for eid in item["evidenceIds"])):
            reject("未提取说明必须引用自身已授权来源证据。")
    pairs = set()
    for index, relation in enumerate(decision['sourceRelations']):
        current_path='/sourceRelations/'+str(index);current_keys=()
        pair = (relation["sourceAId"], relation["sourceBId"])
        if pair[0] >= pair[1] or not set(pair) <= source_ids or pair in pairs:
            reject("source relation 端点必须已授权、排序且唯一。")
        pairs.add(pair)
        if not relation["evidenceIds"] or any(not any((source_id, evidence_id) in evidence for source_id in pair) for evidence_id in relation["evidenceIds"]):
            reject("source relation 缺少端点来源证据。")
    canonical = _canonical_sources(source_ids, decision["sourceRelations"])
    by_key = {item["localKey"]: item for item in decision["entities"]}
    for index, relation in enumerate(decision['entitySupersessions']):
        current_path='/entitySupersessions/'+str(index);current_keys=()
        endpoints = relation["predecessorLocalKeys"] + relation["successorLocalKeys"]
        if not set(endpoints) <= by_key.keys():
            reject("FULL replacement 端点必须引用已声明实体。")
        endpoint_sources = {by_key[key]["sourceId"] for key in endpoints}
        if any(canonical[source_id] != source_id for source_id in endpoint_sources):
            reject("DUPLICATE 分量中的 replacement 只能引用 canonical source entity。")
        if not relation["evidenceIds"] or any(not any((source_id, evidence_id) in evidence for source_id in endpoint_sources) for evidence_id in relation["evidenceIds"]):
            reject("FULL replacement 缺少端点来源替代证据。")


def prior_entity_ids(final_decision):
    """One identity mapping for Snapshot, Scope and ChangeGraph; never key by row alone."""
    ids = {}
    canonical = _canonical_sources({item["sourceId"] for item in final_decision["entities"]}, final_decision["sourceRelations"])
    claims = defaultdict(list)
    for item in final_decision["entities"]:
        if "visiblePriorId" in item and canonical[item["sourceId"]] == item["sourceId"]:
            claims[item["visiblePriorId"]].append(item["localKey"])
    for item in final_decision["entities"]:
        anchors = [{"sourceId": item["sourceId"], "priorEvidenceId": evidence_id} for evidence_id in sorted(item["evidenceIds"])]
        if item.get("cellAnchors"):
            anchors = [{"sourceId": item["sourceId"], "priorEvidenceId": anchor["evidenceId"], "address": anchor["address"]}
                       for anchor in sorted(item["cellAnchors"], key=canonical_json_bytes)]
        entity_id = stable_entity_id("prior-entity-id-v2" if item.get("cellAnchors") else "prior-entity-id-v1", item["entityKind"], None,
                                    [canonical_json_bytes(anchor).decode("utf-8") for anchor in anchors], ("CONTRACT_ENTITY",))
        visible_id = item.get("visiblePriorId")
        if visible_id is not None and claims[visible_id] == [item["localKey"]]:
            entity_id = visible_id
        ids[item["localKey"]] = entity_id
    if len(set(ids.values())) != len(ids):
        raise PriorInputRequired("证据锚点不足以区分合同实体，最终 ID 发生碰撞。")
    return ids


def materialize_prior_snapshot(inventories, final_decision, *, input_revision_bytes: bytes):
    revision = _canonical_value(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    _validate_decision(final_decision, evidence)
    _require_ready(final_decision, inventories)
    ids = prior_entity_ids(final_decision)
    entities = [{"entityId": ids[item["localKey"]], **{key: item[key] for key in
                ("sourceId", "entityKind", "semanticSummary", "deliveryStatus", "evidenceIds")}} for item in final_decision["entities"]]
    used = {(item["sourceId"], eid) for item in final_decision["entities"] for eid in item["evidenceIds"]}
    supersessions = [{"predecessorIds": sorted(ids[key] for key in item["predecessorLocalKeys"]), "successorIds": sorted(ids[key] for key in item["successorLocalKeys"]), "evidenceIds": item["evidenceIds"]} for item in final_decision["entitySupersessions"]]
    relation_evidence = {evidence_id for collection in ("sourceRelations", "entitySupersessions") for item in final_decision[collection] for evidence_id in item["evidenceIds"]}
    used.update(key for key in evidence if key[1] in relation_evidence)
    return {"contractVersion": "prior-state-snapshot-v1", "inputRevisionSha256": sha256_bytes(input_revision_bytes), "evidence": [evidence[key] for key in sorted(used)], "entities": sorted(entities, key=lambda item: item["entityId"]), "sourceRelations": final_decision["sourceRelations"], "entitySupersessions": supersessions}


def _canonical_value(payload: bytes):
    value = json.loads(payload.decode("utf-8"))
    if canonical_json_bytes(value) != payload:
        raise ValueError("需要严格 canonical JSON bytes。")
    return value


def _verified_revision(payload: bytes):
    value = _canonical_value(payload)
    if validate_contract(value, "input-revision.schema.json", load_schema_registry(SKILL_ROOT)):
        raise ValueError("InputRevision 未通过 schema 校验。")
    return value


def build_project_effective_start_context(input_revision_bytes: bytes) -> ContextRefDescriptor:
    revision = _verified_revision(input_revision_bytes)
    return ContextRefDescriptor("PROJECT_EFFECTIVE_START", canonical_json_bytes({"kind": "PROJECT_EFFECTIVE_START", "inputRevisionSha256": sha256_bytes(input_revision_bytes), "plannedEffectiveDate": revision["project"]["plannedEffectiveDate"]}))


def inventory_prior_workbook(path: Path) -> PriorWorkbookInventory:
    from source_readers import inventory_xlsx

    inventory = inventory_xlsx(path)
    evidence = []
    for sheet in inventory["sheets"]:
        rows = defaultdict(list)
        for cell in sheet["cells"]:
            rows[int(re.search(r"\d+$", cell["address"]).group())].append(cell)
        for row, cells in sorted(rows.items()):
            basis = {"workbookSha256": inventory["workbookSha256"], "sheet": sheet["sheet"], "absoluteA1Range": cells[0]["address"] + ":" + cells[-1]["address"], "canonicalCellValuesSha256": sha256_bytes(canonical_json_bytes(cells))}
            evidence.append({"priorEvidenceId": sha256_bytes(canonical_json_bytes(basis)), **basis, "canonicalCellValues": cells})
    return {**inventory, "evidence": evidence}


def _prior_coverage_gaps(packet, result, evidence):
    """One coverage difference calculation for validation, preservation and diagnostics."""
    from collections import Counter
    assigned={(item['payload']['sourceId'],eid) for item in packet['workItems'] for eid in item['payload']['evidenceIds']}
    _,used=_decision_authority({**result,'unextractedEvidence':[]},evidence)
    explained=Counter((row['sourceId'],eid) for row in result.get('unextractedEvidence',[]) for eid in row['evidenceIds'])
    unsupported={(row['sourceId'],row['regionId']) for row in result['unsupportedRegions']}
    duplicate={key for key,count in explained.items() if count>1}
    unassigned=explained.keys()-assigned;already_used=explained.keys()&used
    invalid=duplicate|unassigned|already_used
    invalid_rows={i for i,row in enumerate(result.get('unextractedEvidence',[]))
                  if {(row['sourceId'],eid) for eid in row['evidenceIds']}&invalid}
    repairable={(result['unextractedEvidence'][i]['sourceId'],eid) for i in invalid_rows
                for eid in result['unextractedEvidence'][i]['evidenceIds']}&assigned-used
    return {'missing':assigned-used-explained.keys()-unsupported,'duplicate':duplicate,
            'unassigned':unassigned,'alreadyUsed':already_used,'invalidRows':invalid_rows,'repairable':repairable}


def diagnose_candidate(action_kind, packet, candidate, **owner_context):
    from candidate_repair import schema_issues, diagnostic_report, issues_from_diagnostics, make_issue
    from contracts import current_action_contract_id, assemble_prior_result
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    contract_id=owner_context.get('action_contract_id',current_action_contract_id(action_kind))
    issues=schema_issues(contract_id,value,'PRIOR');blocked=['PRIOR_BINDINGS'] if issues else []
    full=value
    if not issues:
        if contract_id=='PRIOR_CONSOLIDATE-v2': full=assemble_prior_result(packet,value,skill_root=SKILL_ROOT)
        evidence=_inventory_evidence(owner_context['inventories'],_verified_revision(owner_context['input_revision_bytes']))
        # The same bound validator remains the final authority. Coverage is collected
        # independently, so one bad explanation cannot hide the full missing set.
        try:validate_bound_prior_result(action_kind,packet,canonical_json_bytes(full),
                inventories=owner_context['inventories'],input_revision_bytes=owner_context['input_revision_bytes'])
        except InvalidActionResult as error:
            if error.diagnostic.code!='PRIOR_EVIDENCE_COVERAGE_INVALID':
                issues+=issues_from_diagnostics(error.diagnostic.findings or [error.diagnostic],'PRIOR',full)
    # Coverage depends on reference arrays, not unrelated free-text fields. It
    # can still run when Schema reports a missing reason or duplicate evidence.
    safe_coverage=(action_kind=='PRIOR_ANALYZE' and isinstance(full,dict)
        and all(isinstance(full.get(k),list) for k in ('entities','sourceRelations','entitySupersessions','unsupportedRegions','unextractedEvidence'))
        and all(isinstance(row,dict) and isinstance(row.get('sourceId'),str) and isinstance(row.get('evidenceIds'),list)
                and all(isinstance(e,str) for e in row['evidenceIds']) for row in full['entities']+full['unextractedEvidence'])
        and all(isinstance(row,dict) and isinstance(row.get('sourceId'),str) and isinstance(row.get('regionId'),str) for row in full['unsupportedRegions']))
    if safe_coverage:
        evidence=_inventory_evidence(owner_context['inventories'],_verified_revision(owner_context['input_revision_bytes']))
        try:
            gaps=_prior_coverage_gaps(packet,full,evidence)
        except (KeyError,TypeError):
            blocked.append('PRIOR_COVERAGE')
        else:
            codes={'missing':'MISSING','duplicate':'DUPLICATE','unassigned':'UNASSIGNED','alreadyUsed':'ALREADY_USED'}
            for kind,suffix in codes.items():
                for source,eid in sorted(gaps[kind]):
                    paths=[f'/unextractedEvidence/{i}/evidenceIds' for i,row in enumerate(full['unextractedEvidence'])
                           if row['sourceId']==source and eid in row['evidenceIds']] or ['/unextractedEvidence']
                    issue=make_issue('PRIOR_EVIDENCE_'+suffix,paths[0],'PRIOR',{'sourceId':source,'evidenceId':eid},
                        '每条已分配证据须有唯一、真实且有原文依据的处置。',subjects=[{'sourceId':source,'evidenceId':eid}])
                    issue['paths']=paths
                    if (source,eid) in evidence:issue['evidenceRefs']=[{'refId':eid,'sha256':sha256_bytes(canonical_json_bytes(evidence[(source,eid)]))}]
                    issues.append(issue)
    return diagnostic_report(raw,issues,owner='PRIOR',checker_file=__file__,packet=packet,
        origin=owner_context.get('origin'),blocked=blocked,domains=['SCHEMA','PRIOR_BINDINGS','PRIOR_COVERAGE'] if not blocked else ['SCHEMA'])


def plan_candidate_repair(action_kind, packet, candidate, report, *, origin, **owner_context):
    from candidate_repair import group_fields, build_repair_plan, schema_at
    from contracts import current_action_contract_id
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    contract_id=owner_context.get('action_contract_id',current_action_contract_id(action_kind))
    selected={issue['issueId']:issue['paths'] for issue in report['issues'] if issue['code']!='PRIOR_EVIDENCE_MISSING'}
    groups=group_fields(raw,report,contract_id,selected)
    for issue in report['issues']:
        if issue['code']!='PRIOR_EVIDENCE_MISSING':continue
        subject=issue['subjects'][0];source,eid=subject['sourceId'],subject['evidenceId']
        # A missing row gets a new disposition. Original explanations/entities stay
        # byte-for-byte protected; the model must justify it from the bound row.
        schema=schema_at(contract_id,'/unextractedEvidence/0')
        schema={**schema,'properties':{**schema['properties'], 'sourceId':{'const':source},
                    'evidenceIds':{'type':'array','items':{'const':eid},'minItems':1,'maxItems':1}}}
        slot={'slotId':'append-'+issue['issueId'],'operation':'APPEND_OBJECT','collection':'unextractedEvidence',
            'objectId':'new-'+issue['issueId'],'oldValueSha256':sha256_bytes(canonical_json_bytes(value['unextractedEvidence'])),
            'valueSchema':schema,'maxNewObjects':1}
        choice='disposition-'+issue['issueId'];slot['alternativeSet']=choice
        entity_schema=schema_at(contract_id,'/entities/0')
        item=next(item for item in packet['workItems'] if item['payload']['sourceId']==source and eid in item['payload']['evidenceIds'])
        entity_schema={**entity_schema,'properties':{**entity_schema['properties'],
            'localKey':{'type':'string','pattern':'^'+re.escape(item['workItemId']+':')},
            'sourceId':{'const':source},'evidenceIds':{'type':'array','items':{'const':eid},'minItems':1,'maxItems':1}}}
        entity_slot={**slot,'slotId':'entity-'+issue['issueId'],'objectId':'entity-'+issue['issueId'],'collection':'entities',
            'oldValueSha256':sha256_bytes(canonical_json_bytes(value['entities'])),'valueSchema':entity_schema}
        groups.append({'groupId':'group-'+issue['issueId'],'issueIds':[issue['issueId']], 'readSet':[],
            'slots':[slot,entity_slot],'verificationObligations':[issue['issueId']]})
    if not groups:raise InvalidActionResult('Prior 缺口尚无精确领域槽位；保留候选等待明确证据。')
    return build_repair_plan(raw,report,groups,origin=origin)
