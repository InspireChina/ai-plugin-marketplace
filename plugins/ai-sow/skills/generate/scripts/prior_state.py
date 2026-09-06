from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import re
import json

from contracts import canonical_json_bytes, sha256_bytes, load_schema_registry, validate_contract, InvalidActionResult
from models import ContextRefDescriptor
from stable_ids import stable_entity_id

PriorWorkbookInventory = dict[str, object]


SKILL_ROOT = Path(__file__).parents[1]


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
        if logical_id != expected_id or packet["actionContractId"] != packet["actionKind"] + "-v1":
            raise ValueError("Prior PacketPlan 身份或 Action kind 漂移。")
        envelopes = [item for item in ledger.envelopes_by_sha256.values() if item.value["logicalWorkId"] == logical_id]
        if not envelopes:
            raise ValueError("Prior dependency 缺少 Attempt。")
        latest = max((item.value["revision"], item.value["attempt"]) for item in envelopes)
        effective = [item for item in envelopes if (item.value["revision"], item.value["attempt"]) == latest]
        if len(effective) != 1 or effective[0].value["actionContractId"] != packet["actionContractId"] or effective[0].value["actionContractSha256"] != packet["actionContractSha256"]:
            raise ValueError("Prior effective Attempt kind 或合同不一致。")
        records = [(digest, record) for digest, record in ledger.attempt_records.items() if record.envelope_sha256 == effective[0].sha256 and record.outcome == "SUCCEEDED"]
        if len(records) != 1:
            raise ValueError("Prior dependency 尚无唯一 effective success。")
        effective_records[logical_id] = records[0]
    consumed = {key for work in works.values() for key in work["packetPlan"]["dependencyLogicalWorkIds"]}
    roots = set(works) - consumed
    if len(roots) != 1 or len(result_refs) != 1:
        raise ValueError("Prior 必须形成唯一 root ref。")
    root_id = next(iter(roots))
    ref = result_refs[0]
    if ref.logical_work_id != root_id:
        raise ValueError("Prior root logicalWorkId 不匹配。")
    digest, record = effective_records[root_id]
    if digest != ref.attempt_record_sha256 or record.normalized_result_sha256 != sha256_bytes(ref.normalized_result):
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
        if validate_contract(dependency, "prior-state-decision.schema.json", load_schema_registry(SKILL_ROOT)):
            raise ValueError("冻结 Prior dependency schema 无效。")
        try:
            _validate_decision(dependency, evidence)
        except InvalidActionResult as error:
            raise ValueError("冻结 Prior dependency 引用无效。") from error
        keys.extend(item["localKey"] for item in dependency["entities"])
    if len(keys) != len(set(keys)):
        raise ValueError("冻结 Prior dependencies 重复 entity localKey。")


def _prior_dependencies(action_kind, packet):
    dependencies = []
    for ref in packet["contextRefs"]:
        body = ref["canonicalContent"]
        if body.get("kind") == "DEPENDENCY_RESULT":
            if set(ref) != {"refId", "canonicalContent"} or set(body) != {"kind", "logicalWorkId", "attemptRecordSha256", "normalizedResult"} or ref["refId"] != "dependency-result-" + body["logicalWorkId"]:
                raise ValueError("Prior dependency 必须使用唯一 planner wrapper。")
            dependencies.append(body["normalizedResult"])
    if (action_kind == "PRIOR_ANALYZE" and dependencies) or (action_kind == "PRIOR_CONSOLIDATE" and len(dependencies) < 2):
        raise ValueError("Prior Analyze/Consolidate dependency 数量无效。")
    return dependencies


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


def _decision_authority(decision, evidence):
    entities = {item["localKey"]: item for item in decision["entities"]}
    sources = {item["sourceId"] for item in decision["entities"] + decision["unsupportedRegions"]}
    anchors = {(item["sourceId"], evidence_id) for item in decision["entities"] for evidence_id in item["evidenceIds"]}
    for relation in decision["sourceRelations"]:
        endpoints = {relation["sourceAId"], relation["sourceBId"]}
        sources.update(endpoints)
        anchors.update((source_id, evidence_id) for source_id in endpoints for evidence_id in relation["evidenceIds"] if (source_id, evidence_id) in evidence)
    for relation in decision["entitySupersessions"]:
        endpoints = {entities[key]["sourceId"] for key in relation["predecessorLocalKeys"] + relation["successorLocalKeys"]}
        anchors.update((source_id, evidence_id) for source_id in endpoints for evidence_id in relation["evidenceIds"] if (source_id, evidence_id) in evidence)
    return sources, anchors


def validate_bound_prior_result(action_kind, packet, normalized_result: bytes, *, inventories, input_revision_bytes: bytes):
    revision = _canonical_value(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    _packet_date(action_kind, packet, input_revision_bytes, revision)
    _packet_sources(action_kind, packet, evidence)
    dependencies = _prior_dependencies(action_kind, packet)
    result = json.loads(normalized_result)
    sources = {item["payload"]["sourceId"] for item in packet["workItems"]}
    anchors = {(item["payload"]["sourceId"], evidence_id) for item in packet["workItems"] for evidence_id in item["payload"]["evidenceIds"]}
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
            if owner and owner.get('priorInputLayout')=='ai-sow-prior-row-partition-v1':
                sheet = owner['sheet']['sheet']
                for item in packet['workItems']:
                    payload=item['payload']
                    if (payload.get('priorInputLayout')=='ai-sow-prior-row-partition-v1'
                            and payload['sourceId']==owner['sourceId'] and payload['sheet']['sheet']==sheet):
                        allowed.update(eid for eid in payload['evidenceIds']
                            if evidence[(payload['sourceId'],eid)]['sheet']==sheet)
            if owner is None or entity['sourceId']!=owner['sourceId'] or not owner_anchors or not set(entity['evidenceIds'])<=allowed:
                raise InvalidActionResult("Prior 实体须绑定所属分区证据；只可跨同一请求中同来源、同 Sheet 的已授权行分区。",
                    diagnostic=AttemptDiagnostic('PRIOR_ENTITY_PARTITION_BINDING_INVALID',f'/entities/{index}',(entity['localKey'],)))
    else:
        expected_entities = [item for dependency in dependencies for item in dependency["entities"]]
        if sorted(result["entities"], key=canonical_json_bytes) != sorted(expected_entities, key=canonical_json_bytes):
            raise InvalidActionResult("Consolidation 必须原样保留全部 dependency entities/evidence。")
        expected_regions = {canonical_json_bytes(item) for dependency in dependencies for item in dependency["unsupportedRegions"]}
        if {canonical_json_bytes(item) for item in result["unsupportedRegions"]} != expected_regions:
            raise InvalidActionResult("Consolidation 不得丢失或新增 unsupportedRegions。")
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
    if validate_contract(final_decision, "prior-state-decision.schema.json", load_schema_registry(SKILL_ROOT)):
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
    if set(decision) != {"entities", "sourceRelations", "entitySupersessions", "unsupportedRegions"}:
        raise InvalidActionResult("只接受 PriorStateDecision；Demo Observation 不能进入 As-Is。")
    keys = [item["localKey"] for item in decision["entities"]]
    if len(keys) != len(set(keys)):
        raise InvalidActionResult("Prior entity localKey 必须全局唯一。")
    for item in decision["entities"]:
        if not item["evidenceIds"] or len(item["evidenceIds"]) != len(set(item["evidenceIds"])) or any((item["sourceId"], evidence_id) not in evidence for evidence_id in item["evidenceIds"]):
            raise InvalidActionResult("Prior entity 必须引用自身已授权来源证据。")
        if "visiblePriorId" in item:
            visible = item["visiblePriorId"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", visible) or not any(cell["value"] == visible for evidence_id in item["evidenceIds"] for cell in evidence[(item["sourceId"], evidence_id)]["canonicalCellValues"]):
                raise InvalidActionResult("visiblePriorId 必须是所选证据中的合法 whole-cell ID literal。")
    if source_ids is None:
        source_ids = {key[0] for key in evidence}
    if any(region["sourceId"] not in source_ids for region in decision["unsupportedRegions"]):
        raise InvalidActionResult("unsupportedRegions 必须引用已授权 Prior 来源。")
    pairs = set()
    for relation in decision["sourceRelations"]:
        pair = (relation["sourceAId"], relation["sourceBId"])
        if pair[0] >= pair[1] or not set(pair) <= source_ids or pair in pairs:
            raise InvalidActionResult("source relation 端点必须已授权、排序且唯一。")
        pairs.add(pair)
        if not relation["evidenceIds"] or any(not any((source_id, evidence_id) in evidence for source_id in pair) for evidence_id in relation["evidenceIds"]):
            raise InvalidActionResult("source relation 缺少端点来源证据。")
    canonical = _canonical_sources(source_ids, decision["sourceRelations"])
    by_key = {item["localKey"]: item for item in decision["entities"]}
    for relation in decision["entitySupersessions"]:
        endpoints = relation["predecessorLocalKeys"] + relation["successorLocalKeys"]
        if not set(endpoints) <= by_key.keys():
            raise InvalidActionResult("FULL replacement 端点必须引用已声明实体。")
        endpoint_sources = {by_key[key]["sourceId"] for key in endpoints}
        if any(canonical[source_id] != source_id for source_id in endpoint_sources):
            raise InvalidActionResult("DUPLICATE 分量中的 replacement 只能引用 canonical source entity。")
        if not relation["evidenceIds"] or any(not any((source_id, evidence_id) in evidence for source_id in endpoint_sources) for evidence_id in relation["evidenceIds"]):
            raise InvalidActionResult("FULL replacement 缺少端点来源替代证据。")


def materialize_prior_snapshot(inventories, final_decision, *, input_revision_bytes: bytes):
    revision = _canonical_value(input_revision_bytes)
    evidence = _inventory_evidence(inventories, revision)
    _validate_decision(final_decision, evidence)
    _require_ready(final_decision, inventories)
    entities, used, ids = [], set(), {}
    canonical = _canonical_sources({key[0] for key in evidence}, final_decision["sourceRelations"])
    claims = defaultdict(list)
    for item in final_decision["entities"]:
        if "visiblePriorId" in item and canonical[item["sourceId"]] == item["sourceId"]:
            claims[item["visiblePriorId"]].append(item["localKey"])
    for item in final_decision["entities"]:
        anchors = [{"sourceId": item["sourceId"], "priorEvidenceId": evidence_id} for evidence_id in sorted(item["evidenceIds"])]
        entity_id = stable_entity_id("prior-entity-id-v1", item["entityKind"], None,
                                    [canonical_json_bytes(anchor).decode("utf-8") for anchor in anchors], ("CONTRACT_ENTITY",))
        visible_id = item.get("visiblePriorId")
        if visible_id is not None and claims[visible_id] == [item["localKey"]]:
            entity_id = visible_id
        entities.append({"entityId": entity_id, **{key: item[key] for key in ("sourceId", "entityKind", "semanticSummary", "deliveryStatus", "evidenceIds")}})
        ids[item["localKey"]] = entities[-1]["entityId"]
        used.update((item["sourceId"], evidence_id) for evidence_id in item["evidenceIds"])
    if len(set(ids.values())) != len(ids):
        raise PriorInputRequired("证据锚点不足以区分合同实体，最终 ID 发生碰撞。")
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
