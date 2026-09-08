"""Mechanical preservation of Owner-selected candidate roots; no business decisions."""
from __future__ import annotations

import json
import re
from contracts import InvalidActionResult, canonical_json_bytes, normalize_result_sets
from models import AttemptDiagnostic


def repair_baseline(packet, action_contract_id):
    refs = [ref['canonicalContent'] for ref in packet.get('contextRefs', ())
            if str(ref.get('refId', '')).startswith('repair-from-attempt-')]
    if not refs:
        return None
    if len(refs) != 1:
        raise ValueError('候选修复必须绑定唯一前次失败。')
    content = refs[0].get('preservationBase', refs[0])
    try:
        if content['diagnostic']['code'] == 'INVALID_JSON': return None
        result = json.loads(content['rawOutputUtf8'])
        return normalize_result_sets(action_contract_id, result), content['diagnostic']
    except (ValueError, KeyError, TypeError, AttributeError):
        # Invalid JSON is retained as raw evidence, never certified as a valid partial candidate.
        return None


def preserve_roots(previous, current, collection, root_keys, *, allow_new=None, mutable_fields=()):
    """Freeze unrelated objects and outer fields; Owner supplies the dependency closure."""
    if (not isinstance(previous, dict) or not isinstance(previous.get(collection), list)
            or not all(isinstance(row, dict) and isinstance(row.get('localKey'), str)
                       for row in previous[collection])):
        return
    def by_key(rows):
        values = {}
        for row in rows: values.setdefault(row['localKey'], []).append(row)
        return {key: sorted(value, key=canonical_json_bytes) for key, value in values.items()}
    roots = by_key(previous[collection])
    replacements = by_key(current[collection])
    protected = {key: rows for key, rows in roots.items() if key not in root_keys}
    changed = sorted(key for key, rows in protected.items() if replacements.get(key) != rows)
    changed.extend(sorted(key for key, rows in replacements.items() if key not in roots
        and not (allow_new is not None and all(allow_new(row) for row in rows))))
    outside = {key: value for key, value in previous.items() if key not in {collection, *mutable_fields}}
    if outside != {key: value for key, value in current.items() if key not in {collection, *mutable_fields}}:
        changed.append('$candidate')
    if changed:
        raise InvalidActionResult('修复改变了诊断范围之外的结果；恢复所列对象的原值后再提交。',
            diagnostic=AttemptDiagnostic('REPAIR_SCOPE_VIOLATION', '/' + collection, tuple(changed)))



# v1 is deliberately mechanical. Owners supply every grant and verification rule.
from copy import deepcopy
from collections import Counter
from collections.abc import Mapping, Sequence, Callable
from jsonschema import Draft202012Validator
from contracts import sha256_bytes, parse_repair_document, load_schema_registry
from pathlib import Path


def _digest(value):
    return sha256_bytes(canonical_json_bytes(value))

def repair_progress_sha256(base_candidate, diagnostic, group, evidence, patch_payload=None):
    """Stable no-progress identity over facts and authorized write footprints."""
    slots={slot['slotId']:slot for slot in group['slots']}
    authorization=[]
    for slot in slots.values():
        authorization.append({
            'operation':slot['operation'],'collection':slot['collection'],
            'objectId':slot['objectId'],'field':slot.get('field'),
            'inputObjectIds':sorted(slot.get('inputObjectIds',())),
            'valueSchema':slot.get('valueSchema'),'referenceLimits':slot.get('referenceLimits',()),
            'maxNewObjects':slot.get('maxNewObjects'),'outputNamespace':slot.get('outputNamespace'),
            'referenceClosure':sorted(slot.get('referenceClosure',())),
            'alternativeSet':slot.get('alternativeSet')})
    issue_ids=set(group['issueIds'])
    issues=[{'code':issue['code'],'subjects':issue['subjects'],'paths':sorted(issue['paths']),
             'repairClass':issue['repairClass']}
            for issue in diagnostic['issues'] if issue['issueId'] in issue_ids]
    proposal=None
    if patch_payload is not None:
        try:
            patch=_read_candidate(patch_payload)
        except InvalidActionResult:
            proposal={'rawSha256':sha256_bytes(patch_payload)}
        else:
            operations=[]
            for operation in patch.get('operations',()):
                slot=slots.get(operation.get('slotId'))
                if slot is None:
                    operations.append({'unauthorized':operation})
                    continue
                operations.append({'footprint':next(item for item in authorization
                    if item['operation']==slot['operation'] and item['collection']==slot['collection']
                    and item['objectId']==slot['objectId'] and item['field']==slot.get('field')),
                    'hasValue':'value' in operation,'value':operation.get('value')})
            proposal=sorted(operations,key=canonical_json_bytes)
    value={'contract':'ai-sow-repair-progress-v1','baseCandidateSha256':sha256_bytes(base_candidate),
        'issues':sorted(issues,key=canonical_json_bytes),'blockedChecks':sorted(diagnostic['blockedChecks']),
        'authorization':sorted(authorization,key=canonical_json_bytes),
        'evidenceSha256s':sorted(_digest(item) for item in evidence),'proposal':proposal}
    return _digest(value)


def _read_candidate(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise InvalidActionResult('候选包含重复 JSON 属性。')
            result[key] = value
        return result
    def constant(value): raise InvalidActionResult('候选数字必须有限。')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError) as error:
        raise InvalidActionResult('候选不是可安全解析的 JSON。') from error


def _pointer_part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def _at(value, pointer):
    if not pointer: return value
    for segment in pointer[1:].split('/'):
        segment = segment.replace('~1', '/').replace('~0', '~')
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


def index_candidate(raw: bytes, *, inherited=()) -> list[dict]:
    """Every occurrence has a distinct address; receipts carry anonymous identities."""
    value = _read_candidate(raw)
    prior = {row['path']: row for row in inherited}
    result = []
    seed = sha256_bytes(raw)
    reserved={row['objectId'] for row in inherited}
    used=set()
    def visit(node, path, collection, identity=None):
        if isinstance(node, dict):
            object_id = identity or ('$' if not path else path[1:])
            old = prior.get(path)
            if old is not None:
                object_id = old['objectId']
            elif object_id in reserved or object_id in used:
                object_id='repair-object-'+_digest([seed,path,object_id])
            while object_id in used:
                object_id='repair-object-'+_digest([seed,path,object_id])
            used.add(object_id)
            result.append({'objectId': object_id, 'collection': collection, 'path': path, 'sha256': _digest(node)})
            for key, child in node.items():
                if isinstance(child, (dict, list)):
                    visit(child, path + '/' + _pointer_part(key), path[1:] + '/' + key if path else key)
        elif isinstance(node, list):
            keys = [row.get('localKey', row.get('scenarioId', row.get('coverageRootId'))) if isinstance(row, dict) else None for row in node]
            counts = Counter(key for key in keys if isinstance(key, str))
            for i, child in enumerate(node):
                key = keys[i]
                identity = collection + '/' + key if isinstance(key, str) and counts[key] == 1 else 'repair-object-' + _digest([seed, collection, i])
                visit(child, path + '/' + str(i), collection, identity)
    visit(value, '', '$')
    ids = [row['objectId'] for row in result]
    if len(set(ids)) != len(ids):
        duplicates=sorted(key for key,count in Counter(ids).items() if count>1)
        raise InvalidActionResult('对象索引身份冲突：'+','.join(duplicates))
    return result


def _slot_value(candidate, index, slot):
    operation = slot['operation']
    if operation == 'APPEND_OBJECT':
        return _at(candidate, '' if slot['collection'] == '$' else '/' + slot['collection'])
    if operation == 'TRANSFORM_ROOTS':
        return [_at(candidate, index[key]['path']) for key in slot['inputObjectIds']]
    target = _at(candidate, index[slot['objectId']]['path'])
    if operation in {'SET_FIELD', 'REMOVE_FIELD'}:
        field = slot['field']
        return target[field] if field in target else {'$repairMissing': True}
    if operation == 'SET_FIELDS':
        return {field:target.get(field,{'$repairMissing':True}) for field in slot['fields']}
    return target

def _pointer_prefix(left, right):
    return left == right or not left or not right or right.startswith(left + '/') or left.startswith(right + '/')


def _collection_path(collection):
    return '' if collection == '$' else '/' + collection


def _slot_footprint(index, slot):
    operation = slot['operation']
    if operation in {'SET_FIELD', 'REMOVE_FIELD'}:
        return index[slot['objectId']]['path'] + '/' + _pointer_part(slot['field'])
    if operation == 'SET_FIELDS':
        return index[slot['objectId']]['path']
    return _collection_path(slot['collection'])


def _identity(node):
    if not isinstance(node, dict):
        return None
    for field in ('localKey', 'scenarioId', 'coverageRootId', 'id'):
        value = node.get(field)
        if isinstance(value, str):
            return field, value
    return None


def _identity_counts(value):
    found = Counter()
    def visit(node, path):
        if isinstance(node, list):
            for row in node:
                identity = _identity(row)
                if identity is not None:
                    found[(path, *identity)] += 1
            for i, row in enumerate(node):
                visit(row, path + '/' + str(i))
        elif isinstance(node, dict):
            for key, row in node.items():
                visit(row, path + '/' + _pointer_part(key))
    visit(value, '')
    return found




def _check_plan(base, plan):
    if sha256_bytes(base) != plan['baseCandidateSha256'] or plan['protectedSha256'] != sha256_bytes(base):
        raise InvalidActionResult('补丁基线已漂移。')
    candidate = _read_candidate(base)
    if index_candidate(base, inherited=plan['objectIndex']) != plan['objectIndex']:
        raise InvalidActionResult('修复对象索引与基线不一致。')
    report, origin = plan['diagnostic'], plan['origin']
    inherited = report.get('objectIndex')
    previous_receipt = origin.get('previousReceiptSha256')
    if bool(inherited) != bool(previous_receipt):
        raise InvalidActionResult('继承对象身份必须绑定紧邻的成功 RepairReceipt。')
    if inherited is not None and inherited != plan['objectIndex']:
        raise InvalidActionResult('修复计划改变了继承对象身份。')
    if _digest(report) != plan['diagnosticSha256'] or report['candidateSha256'] != sha256_bytes(base):
        raise InvalidActionResult('诊断未绑定当前候选。')
    for key in ('inputRevisionSha256', 'sourceAttemptRecordSha256'):
        if report[key] != origin[key]:
            raise InvalidActionResult('诊断来源与原始工作不一致。')
    issues = {issue['issueId']: issue for issue in report['issues']}
    if len(issues) != len(report['issues']):
        raise InvalidActionResult('问题身份重复。')
    index = {row['objectId']: row for row in plan['objectIndex']}
    group_ids, slot_ids = set(), set()
    for group in plan['groups']:
        if group['groupId'] in group_ids or not group['issueIds'] or not set(group['issueIds']) <= issues.keys():
            raise InvalidActionResult('修复组必须绑定唯一身份和实际问题。')
        group_ids.add(group['groupId'])
        footprints = []
        collection_mutations = set()
        for read in group['readSet']:
            if read['objectId'] not in index:
                raise InvalidActionResult('只读对象不存在。')
        targets = set()
        group_slot_ids = {slot['slotId'] for slot in group['slots']}
        if len(group_slot_ids) != len(group['slots']):
            raise InvalidActionResult('槽位重复。')
        for slot in group['slots']:
            if slot['slotId'] in slot_ids:
                raise InvalidActionResult('槽位重复。')
            slot_ids.add(slot['slotId'])
            op = slot['operation']
            if op in {'SET_FIELD', 'REMOVE_FIELD'}:
                if not slot.get('field') or '/' in slot['field']:
                    raise InvalidActionResult('字段槽位不能使用任意路径。')
                if (op == 'SET_FIELD' and slot['field'] in {'localKey', 'scenarioId', 'coverageRootId', 'id'}
                        and slot['field'] in _at(candidate, index[slot['objectId']]['path'])):
                    raise InvalidActionResult('字段槽位不能改写已有身份。')
            elif op == 'SET_FIELDS':
                fields=slot.get('fields')
                if (not isinstance(fields,list) or len(fields)<2 or len(set(fields))!=len(fields)
                        or any(not isinstance(field,str) or not field or '/' in field
                               or field in {'localKey','scenarioId','coverageRootId','id'} for field in fields)):
                    raise InvalidActionResult('联合字段槽位必须声明有限且不含身份的属性。')
            elif 'field' in slot or 'fields' in slot:
                raise InvalidActionResult('非字段操作不能携带字段授权。')
            if op in {'SET_FIELD', 'SET_FIELDS', 'REMOVE_FIELD', 'REMOVE_OBJECT'}:
                if slot['objectId'] not in index or index[slot['objectId']]['collection'] != slot['collection']:
                    raise InvalidActionResult('槽位目标不存在或越出集合。')
                if op == 'REMOVE_FIELD' and slot['field'] not in _at(candidate, index[slot['objectId']]['path']):
                    raise InvalidActionResult('只能删除明确存在的字段。')
                if op == 'REMOVE_OBJECT' and not isinstance(_at(candidate, index[slot['objectId']]['path'].rsplit('/', 1)[0]), list):
                    raise InvalidActionResult('只能删除明确的集合成员。')
            if op == 'APPEND_OBJECT' and slot['objectId'] in index:
                raise InvalidActionResult('新增槽位不能复用既有对象身份。')
            if op == 'TRANSFORM_ROOTS':
                if not slot.get('inputObjectIds') or not slot.get('outputNamespace') or 'referenceClosure' not in slot:
                    raise InvalidActionResult('root 变换必须给出输入、输出和引用闭包。')
                if set(slot['referenceClosure']) != group_slot_ids - {slot['slotId']}:
                    raise InvalidActionResult('root 变换引用闭包必须完整覆盖原子组的关联槽位。')
                if any(key not in index or index[key]['collection'] != slot['collection'] for key in slot['inputObjectIds']):
                    raise InvalidActionResult('root 变换输入越界。')
            if op in {'APPEND_OBJECT', 'TRANSFORM_ROOTS'}:
                collection = _at(candidate, _collection_path(slot['collection']))
                if not isinstance(collection, list) or not slot.get('maxNewObjects'):
                    raise InvalidActionResult('新增必须绑定集合与有限额度。')
            if op not in {'REMOVE_FIELD', 'REMOVE_OBJECT'}:
                if 'valueSchema' not in slot:
                    raise InvalidActionResult('写入值缺少 Owner Schema。')
                try:
                    Draft202012Validator.check_schema(slot['valueSchema'])
                except Exception as error:
                    raise InvalidActionResult('槽位 Schema 无效。') from error
            target = (slot['objectId'], tuple(slot.get('fields', (slot.get('field', '$'),))))
            if target in targets:
                raise InvalidActionResult('原子组写集合重叠。')
            targets.add(target)
            try:
                old = _slot_value(candidate, index, slot)
            except (KeyError, IndexError, TypeError):
                raise InvalidActionResult('槽位无法从基线定位。')
            if _digest(old) != slot['oldValueSha256']:
                raise InvalidActionResult('槽位旧值 hash 漂移。')
            footprint = _slot_footprint(index, slot)
            if any(_pointer_prefix(footprint, existing) for existing in footprints):
                raise InvalidActionResult('修复写集合存在祖先、子项或重复重叠。')
            footprints.append(footprint)
            if op in {'APPEND_OBJECT', 'REMOVE_OBJECT', 'TRANSFORM_ROOTS'}:
                collection_path = _collection_path(slot['collection'])
                if collection_path in collection_mutations:
                    raise InvalidActionResult('同一计划不能重复修改集合成员。')
                collection_mutations.add(collection_path)
    return candidate, index


def build_repair_plan(base_candidate: bytes, diagnostic: Mapping[str, object], groups: Sequence[Mapping[str, object]], *, origin: Mapping[str, object]) -> bytes:
    plan = {'contract': 'ai-sow-candidate-repair-plan-v1', 'baseCandidateSha256': sha256_bytes(base_candidate),
            'diagnosticSha256': _digest(diagnostic), 'diagnostic': deepcopy(diagnostic), 'origin': deepcopy(origin),
            'objectIndex': index_candidate(base_candidate, inherited=diagnostic.get('objectIndex', ())),
            'groups': deepcopy(list(groups)), 'protectedSha256': sha256_bytes(base_candidate)}
    raw = canonical_json_bytes(plan)
    parse_repair_document(raw, 'RepairPlan')
    _check_plan(base_candidate, plan)
    return raw


def apply_repair_patch(base_candidate: bytes, plan_payload: bytes, patch_payload: bytes, *, group_id: str,
                       verify_group: Callable[[bytes, Mapping[str, object]], None]) -> tuple[bytes, bytes]:
    plan = parse_repair_document(plan_payload, 'RepairPlan')
    patch = parse_repair_document(patch_payload, 'PatchResult')
    candidate, index = _check_plan(base_candidate, plan)
    if (patch['repairPlanSha256'] != sha256_bytes(plan_payload) or patch['baseCandidateSha256'] != sha256_bytes(base_candidate)
            or patch['groupId'] != group_id): raise InvalidActionResult('补丁未绑定本组授权。')
    groups = [group for group in plan['groups'] if group['groupId'] == group_id]
    if len(groups) != 1: raise InvalidActionResult('未知修复组。')
    group = groups[0]
    slots = {slot['slotId']: slot for slot in group['slots']}
    operations = {op['slotId']: op for op in patch['operations']}
    required={key for key,slot in slots.items() if 'alternativeSet' not in slot}
    alternatives={slot['alternativeSet'] for slot in slots.values() if 'alternativeSet' in slot}
    if (len(operations)!=len(patch['operations']) or not operations.keys()<=slots.keys() or not required<=operations.keys()
        or any(sum(slots[key].get('alternativeSet')==choice for key in operations)!=1 for choice in alternatives)):
        raise InvalidActionResult('操作须覆盖必需槽位，并从每个 Owner 替代集合恰选一个；不能重复或扩权。')
    merged = deepcopy(candidate)
    # Identity follows the actual object references through deletion and insertion.
    objects = {key: _at(merged, entry['path']) for key, entry in index.items()}
    changes = []
    for slot_id, slot in slots.items():
        if slot_id not in operations:continue
        operation = operations[slot_id]
        op = slot['operation']
        deletes_value = op in {'REMOVE_FIELD', 'REMOVE_OBJECT'}
        if ('value' in operation) == deletes_value:
            raise InvalidActionResult('槽位 value 与操作类型不符。')
        value = deepcopy(operation.get('value'))
        if not deletes_value:
            if list(Draft202012Validator(slot['valueSchema'], registry=load_schema_registry(Path(__file__).parents[1])).iter_errors(value)):
                raise InvalidActionResult('槽位值不符合 Owner Schema。')
            for limit in slot.get('referenceLimits', ()):
                actual = value.get(limit['field']) if isinstance(value, dict) else value
                if not isinstance(actual, list) or any(item not in limit['allowedValues'] for item in actual) or any(item not in actual for item in limit['retainedValues']):
                    raise InvalidActionResult('引用超出授权或丢失旧引用。')
        if op == 'SET_FIELD':
            objects[slot['objectId']][slot['field']] = value
        elif op == 'SET_FIELDS':
            objects[slot['objectId']].update(value)
        elif op == 'REMOVE_FIELD':
            del objects[slot['objectId']][slot['field']]
        elif op == 'REMOVE_OBJECT':
            parent = _at(merged, index[slot['objectId']]['path'].rsplit('/', 1)[0])
            parent[:] = [row for row in parent if row is not objects[slot['objectId']]]
        elif op == 'APPEND_OBJECT':
            collection = _at(merged, '' if slot['collection'] == '$' else '/' + slot['collection'])
            if not isinstance(value, dict): raise InvalidActionResult('新增槽位只接受一个对象。')
            collection.append(value)
        else:
            if not isinstance(value, list) or len(value) > slot['maxNewObjects']:
                raise InvalidActionResult('root 变换超出新增额度。')
            old_keys = {objects[key].get('localKey') for key in slot['inputObjectIds']}
            for row in value:
                if not isinstance(row, dict) or not str(row.get('localKey', '')).startswith(slot['outputNamespace']) or row.get('localKey') in old_keys:
                    raise InvalidActionResult('实质 root 变换必须使用新的授权身份。')
            collection = _at(merged, '' if slot['collection'] == '$' else '/' + slot['collection'])
            removed = {id(objects[key]) for key in slot['inputObjectIds']}
            insert_at = min(i for i, row in enumerate(collection) if id(row) in removed)
            retained = [row for row in collection if id(row) not in removed]
            collection[:] = retained[:insert_at] + value + retained[insert_at:]
        changes.append({'slotId': slot_id, 'beforeSha256': slot['oldValueSha256'], 'afterSha256': _digest(value)})
    # Identity counts are collection-scoped and occurrence-aware. Existing
    # malformed duplicates may remain for another group, but a patch cannot
    # add another duplicate through any supported identity field.
    before_identities = _identity_counts(candidate)
    if any(count > 1 and count > before_identities[key] for key, count in _identity_counts(merged).items()):
        raise InvalidActionResult('补丁引入或复用集合内对象身份。')
    raw = canonical_json_bytes(merged)
    if raw == canonical_json_bytes(candidate): raise InvalidActionResult('补丁没有有效变化。')
    verify_group(raw, group)
    # Persisted receipts, rather than content equality, preserve anonymous occurrences.
    inherited = []
    def locate(node, path):
        if isinstance(node, dict):
            for key, original in objects.items():
                if node is original: inherited.append({**index[key], 'path': path})
            for key, child in node.items(): locate(child, path + '/' + _pointer_part(key))
        elif isinstance(node, list):
            for i, child in enumerate(node): locate(child, path + '/' + str(i))
    locate(merged, '')
    receipt = {'contract': 'ai-sow-candidate-repair-receipt-v1', 'baseCandidateSha256': sha256_bytes(base_candidate),
               'repairPlanSha256': sha256_bytes(plan_payload), 'patchSha256': sha256_bytes(patch_payload),
               'groupId': group_id, 'mergedCandidateSha256': sha256_bytes(raw), 'changes': changes,
               'objectIndex': index_candidate(raw, inherited=inherited),
               'verifiedObligations': group['verificationObligations']}
    receipt_raw = canonical_json_bytes(receipt)
    parse_repair_document(receipt_raw, 'RepairReceipt')
    return raw, receipt_raw


def resolve_candidate(author_raw: bytes, chain: Sequence[Mapping[str, bytes]], *,
                      verify_group: Callable[[bytes, Mapping[str, object]], None],
                      verify_candidate: Callable[[bytes], None]) -> tuple[bytes, bytes]:
    if not chain: raise InvalidActionResult('Resolution 需要真实补丁链。')
    current, entries, origin = author_raw, [], None
    previous_index = None
    for item in chain:
        if set(item) != {'plan', 'patch', 'receipt', 'record', 'envelope', 'packet'}:
            raise InvalidActionResult('补丁来源链缺少物理记录。')
        plan = parse_repair_document(item['plan'], 'RepairPlan')
        record, envelope, packet = (_read_candidate(item[key]) for key in ('record', 'envelope', 'packet'))
        this_origin = plan['origin']
        identity_keys=('runId','inputRevisionSha256','originLogicalWorkId','sourceKind',
            'sourceActionContractId','sourceAttemptRecordSha256','stageKind')
        if this_origin['sourceKind']=='SEMANTIC_REVIEW':
            identity_keys+=('reviewDecisionSha256','reviewCandidateSha256','semanticSourceSha256')
        if origin is not None and any(this_origin[k] != origin[k] for k in identity_keys):
            raise InvalidActionResult('补丁链改变了原始工作身份。')
        if origin is not None and this_origin['repairRound'] < origin['repairRound']:
            raise InvalidActionResult('补丁链重置累计次数。')
        if previous_index is None:
            if 'previousReceiptSha256' in this_origin:
                raise InvalidActionResult('首个修复计划不能声明前序 RepairReceipt。')
        else:
            if this_origin.get('previousReceiptSha256') != sha256_bytes(chain[len(entries) - 1]['receipt']):
                raise InvalidActionResult('补丁链未绑定紧邻的成功 RepairReceipt。')
        origin = this_origin
        if previous_index is not None and plan['objectIndex'] != previous_index:
            raise InvalidActionResult('补丁链丢失对象身份。')
        if (record.get('outcome') != 'SUCCEEDED' or record.get('envelopeSha256') != sha256_bytes(item['envelope'])
                or record.get('rawSha256') != sha256_bytes(item['patch']) or record.get('normalizedResultSha256') != sha256_bytes(item['receipt'])
                or envelope.get('actionContractId') != 'CANDIDATE_PATCH-v1' or envelope.get('packetSha256') != sha256_bytes(item['packet'])
                or envelope.get('runId') != origin['runId'] or envelope.get('logicalWorkId') == origin['originLogicalWorkId']):
            raise InvalidActionResult('Resolution 物理来源角色或 hash 无效。')
        contexts = [ref.get('canonicalContent') for ref in packet.get('contextRefs', ()) if ref.get('refId') == 'candidate-repair-plan-v1']
        if len(contexts) != 1 or contexts[0].get('repairPlanSha256') != sha256_bytes(item['plan']):
            raise InvalidActionResult('发行 packet 未绑定 RepairPlan。')
        patch = parse_repair_document(item['patch'], 'PatchResult')
        normalized_patch = canonical_json_bytes(patch)
        current, receipt = apply_repair_patch(current, item['plan'], normalized_patch, group_id=patch['groupId'], verify_group=verify_group)
        if receipt != item['receipt']: raise InvalidActionResult('RepairReceipt 无法重放。')
        previous_index = json.loads(receipt)['objectIndex']
        entries.append({key + 'Sha256': sha256_bytes(item[key]) for key in ('plan','patch','receipt','record','envelope','packet')})
    verify_candidate(current)
    resolution = canonical_json_bytes({'contract':'ai-sow-candidate-resolution-v1','origin':origin,
        'authorRawSha256':sha256_bytes(author_raw),'chain':entries,'ownerIrSha256':sha256_bytes(current)})
    parse_repair_document(resolution, 'CandidateResolution')
    return current, resolution


def schema_at(action_contract_id, path):
    """Resolve an Owner's frozen Schema at a data location, without semantic rules."""
    from contracts import action_contract_binding, load_schema_registry
    from pathlib import Path
    root = Path(__file__).parents[1]
    contract, _ = action_contract_binding(root, action_contract_id)
    resolver = load_schema_registry(root).resolver()
    resolved = resolver.lookup(contract['resultSchema']['id'])
    schema, resolver = resolved.contents, resolved.resolver
    for part in path.strip('/').split('/') if path else ():
        while isinstance(schema, dict) and '$ref' in schema:
            resolved = resolver.lookup(schema['$ref']); schema, resolver = resolved.contents, resolved.resolver
        part = part.replace('~1','/').replace('~0','~')
        schema = schema.get('items', {}) if schema.get('type') == 'array' else schema.get('properties', {}).get(part, {})
    def absolute(node):
        if isinstance(node, list): return [absolute(item) for item in node]
        if not isinstance(node, dict): return node
        if '$ref' in node:
            resolved = resolver.lookup(node['$ref'])
            # Owner contracts have finite IR structures; recursively preserve resolved restrictions.
            return absolute(resolved.contents)
        return {key:absolute(value) for key,value in node.items()}
    return absolute(schema)


def schema_issues(action_contract_id, candidate, owner):
    from contracts import action_contract_binding, load_schema_registry
    from pathlib import Path
    root = Path(__file__).parents[1]
    contract, _ = action_contract_binding(root, action_contract_id)
    errors = list(Draft202012Validator({'$ref':contract['resultSchema']['id']},registry=load_schema_registry(root)).iter_errors(candidate))
    issues = []
    for error in errors:
        parts = list(error.absolute_path)
        if error.validator == 'required':
            for field in error.validator_value:
                if field not in error.instance:
                    issues.append(make_issue('SCHEMA_REQUIRED', '/'+'/'.join(_pointer_part(p) for p in [*parts,field]), owner,
                        {'missing':True}, '补齐本 Owner Schema 要求的字段。'))
        elif error.validator == 'additionalProperties' and isinstance(error.instance, dict):
            properties = error.schema.get('properties', {})
            patterns = error.schema.get('patternProperties', {})
            unexpected = [
                field for field in error.instance
                if field not in properties
                and not any(re.search(pattern, field) for pattern in patterns)
            ]
            for field in unexpected:
                path = '/' + '/'.join(_pointer_part(p) for p in [*parts, field])
                issues.append(make_issue(
                    'SCHEMA_ADDITIONALPROPERTIES', path, owner,
                    error.instance[field], '删除本 Owner Schema 未授权字段。'))
        else:
            issues.append(make_issue('SCHEMA_'+str(error.validator).upper(), '/'+'/'.join(_pointer_part(p) for p in parts), owner,
                error.instance, '满足本 Owner 冻结 Schema 的 '+str(error.validator)+' 约束。'))
    return issues


def make_issue(code, path, owner, observed=None, expected='满足当前 Owner 的冻结引用与交付义务。', *, subjects=(), repair_class='DATA', caused_by=()):
    identity = [owner, code, path, list(subjects)]
    return {'issueId':'issue-'+_digest(identity)[:24], 'code':code, 'subjects':list(subjects), 'paths':[path],
            'observed':observed, 'expectedConstraint':expected,'evidenceRefs':[],'dependencyRefs':[],
            'repairOwner':owner,'repairClass':repair_class,'causedBy':list(caused_by)}


def diagnostic_report(candidate, issues, *, owner, checker_file, packet, origin=None, blocked=(), domains=()):
    from pathlib import Path
    origin = origin or {}
    input_hash = origin.get('inputRevisionSha256')
    if input_hash is None:
        def find(node):
            if isinstance(node, dict):
                if isinstance(node.get('inputRevisionSha256'), str): return node['inputRevisionSha256']
                for value in node.values():
                    match = find(value)
                    if match: return match
            if isinstance(node, list):
                for value in node:
                    match = find(value)
                    if match: return match
        input_hash = find(packet) or _digest(packet)
    return {'candidateSha256':sha256_bytes(candidate), 'inputRevisionSha256':input_hash,
        'sourceAttemptRecordSha256':origin.get('sourceAttemptRecordSha256', _digest(packet)),
        'owner':owner,'checkerFingerprint':sha256_bytes(Path(checker_file).read_bytes()),
        'checkedDomains':sorted(set(domains)), 'blockedChecks':sorted(set(blocked)),
        'issues':sorted({i['issueId']:i for i in issues}.values(),key=lambda i:i['issueId'])}


def located_slots(candidate, action_contract_id, paths, *, inherited=(), remove=False):
    """Translate Owner-selected field locations into frozen mechanical grants."""
    raw = candidate if isinstance(candidate, bytes) else canonical_json_bytes(candidate)
    value = _read_candidate(raw)
    index = index_candidate(raw, inherited=inherited)
    by_path = {row['path']:row for row in index}
    slots = []
    for path in sorted(set(paths)):
        parent, _, field = path.rpartition('/')
        if parent not in by_path or not field or field.isdigit(): continue
        field = field.replace('~1','/').replace('~0','~')
        row = by_path[parent]
        target = _at(value, parent)
        if not remove and field in {'localKey','scenarioId','coverageRootId','id'} and field in target: continue
        if remove:
            if field not in target: continue
            slots.append({
                'slotId':'slot-'+_digest([row['objectId'],field])[:24],
                'operation':'REMOVE_FIELD','collection':row['collection'],
                'objectId':row['objectId'],'field':field,
                'oldValueSha256':_digest(target[field])})
            continue
        old = target.get(field, {'$repairMissing':True})
        schema = schema_at(action_contract_id,path)
        if not schema: continue
        slots.append({'slotId':'slot-'+_digest([row['objectId'],field])[:24],'operation':'SET_FIELD',
            'collection':row['collection'],'objectId':row['objectId'],'field':field,
            'oldValueSha256':_digest(old),'valueSchema':schema})
    return slots


def group_fields(candidate, report, action_contract_id, paths_by_issue):
    """Group intersecting Owner grants atomically; shared fields cannot race."""
    groups = []
    for issue in report['issues']:
        slots = located_slots(
            candidate, action_contract_id,
            paths_by_issue.get(issue['issueId'], ()),
            inherited=report.get('objectIndex', ()),
            remove=issue['code'] == 'SCHEMA_ADDITIONALPROPERTIES')
        if not slots: continue
        overlap = [g for g in groups if {s['slotId'] for s in g['slots']} & {s['slotId'] for s in slots}]
        ids = [issue['issueId']]
        for old in overlap:
            ids.extend(old['issueIds']); slots.extend(old['slots']); groups.remove(old)
        slots = list({s['slotId']:s for s in slots}.values())
        groups.append({'groupId':'group-'+_digest(sorted(ids))[:24], 'issueIds':sorted(ids),
            'readSet':[{'objectId':s['objectId'],'fields':[s['field']]} for s in slots],
            'slots':slots,'verificationObligations':sorted(ids)})
    return groups


def verify_group_progress(base_report, new_report, group):
    """A local commit must close its obligations and introduce no independent errors."""
    before = {item['issueId'] for item in base_report['issues']}
    after = {item['issueId'] for item in new_report['issues']}
    if set(group['issueIds']) & after or not after <= before:
        raise InvalidActionResult('本组问题未关闭或补丁引入新的独立问题。')
    if set(new_report['blockedChecks']) - set(base_report['blockedChecks']):
        raise InvalidActionResult('补丁阻断了先前可执行的完整检查。')


def issues_from_diagnostics(diagnostics, owner, candidate):
    index = index_candidate(canonical_json_bytes(candidate))
    result = []
    for diagnostic in diagnostics:
        keys = getattr(diagnostic, 'subject_ids', ()) or getattr(diagnostic, 'details', {}).get('subjectIds', ())
        subjects = [{'objectId':row['objectId']} for row in index if any(
            row['objectId'].endswith('/'+key) for key in keys)]
        path=getattr(diagnostic,'path','') or '/'
        try: observed = _at(candidate, path)
        except (KeyError, ValueError, IndexError, TypeError): observed = None
        result.append(make_issue(diagnostic.code, path, owner, observed,
            getattr(diagnostic, 'message', None) or '满足本 Owner 的冻结引用与交付义务。', subjects=subjects))
    return result


def patch_context(packet):
    refs=[ref['canonicalContent'] for ref in packet.get('contextRefs',()) if ref.get('refId')=='candidate-repair-plan-v1']
    if len(refs)!=1: raise InvalidActionResult('Patch 必须绑定唯一版本化修复计划。')
    return refs[0]


def replay_candidate_ledger(ledger, packets, plans, *, owner_callbacks, events=(), bases=None, semantic_sources=None):
    """Derive heads and resolutions exclusively from immutable physical Attempts.

    owner_callbacks(source envelope, original packet) returns diagnose, plan, full
    verification functions. No Owner rules or I/O live in this replay mechanism.
    """
    from dataclasses import replace
    from action_ledger import attempt_record_value
    heads, resolutions, results = {}, {}, {}
    patches=[]
    for envelope in ledger.envelopes_by_sha256.values():
        if envelope.value['actionContractId']!='CANDIDATE_PATCH-v1':continue
        packet_raw=packets[envelope.value['packetSha256']]
        view=patch_context(json.loads(packet_raw));plan_raw=plans[view['repairPlanSha256']]
        if sha256_bytes(plan_raw)!=view['repairPlanSha256']:raise InvalidActionResult('修复授权 hash 漂移。')
        plan=parse_repair_document(plan_raw,'RepairPlan');origin=plan['origin']
        record=next((r for r in ledger.attempt_records.values() if r.envelope_sha256==envelope.sha256),None)
        patches.append((origin['repairRound'], origin['originLogicalWorkId'], plan, plan_raw, envelope, packet_raw, record))
    if patches:
        from contracts import action_contract_binding
        contract_sha=action_contract_binding(Path(__file__).parents[1],'CANDIDATE_PATCH-v1')[1]
        schema_sha=sha256_bytes((Path(__file__).parents[1]/'contracts/candidate-repair.schema.json').read_bytes())
        selections=[event for event in events if getattr(event,'type',event.get('type') if isinstance(event,dict) else None)=='CANDIDATE_REPAIR_PROTOCOL_SELECTED']
        for logical in {entry[1] for entry in patches}:
            lineage=[entry for entry in patches if entry[1]==logical]
            issued_by_envelope={}
            for event in events:
                event_type=event.type if hasattr(event,'type') else event['type']
                payload=event.payload if hasattr(event,'payload') else event['payload']
                if event_type=='ACTION_ISSUED':
                    sequence=event.sequence if hasattr(event,'sequence') else event['sequence']
                    issued_by_envelope.setdefault(payload['envelopeSha256'],[]).append(sequence)
            if any(len(issued_by_envelope.get(entry[4].sha256,()))!=1 for entry in lineage):
                raise InvalidActionResult('Patch ACTION_ISSUED 事件缺失或重复。')
            first=min(lineage,key=lambda entry:issued_by_envelope[entry[4].sha256][0])
            origin=first[2]['origin']
            expected={'originLogicalWorkId':logical,'sourceAttemptRecordSha256':origin['sourceAttemptRecordSha256'],
                'sourceActionContractId':origin['sourceActionContractId'],
                'selectionKind':'SEMANTIC_REVIEW' if origin['sourceKind']=='SEMANTIC_REVIEW' else 'AUTHOR_FAILURE',
                'repairRound':origin['repairRound'],'candidatePatchActionContractSha256':contract_sha,
                'candidateRepairSchemaSha256':schema_sha}
            matches=[]
            for event in selections:
                payload=event.payload if hasattr(event,'payload') else event['payload']
                if payload['originLogicalWorkId']==logical:matches.append((event,payload))
            if len(matches)!=1 or matches[0][1]!=expected:
                raise InvalidActionResult('候选修复协议选择事件缺失、重复或 hash 漂移。')
            first_issued=issued_by_envelope[first[4].sha256][0]
            selection_sequence=matches[0][0].sequence if hasattr(matches[0][0],'sequence') else matches[0][0]['sequence']
            if selection_sequence+1!=first_issued:
                raise InvalidActionResult('协议选择必须紧邻 lineage 首个 Patch ACTION_ISSUED。')
    bases=bases or {};semantic_sources=semantic_sources or {}
    bound_bases = {}
    bound_semantic_sources = {}
    def source_base(plan):
        origin=plan['origin'];source=ledger.attempt_records.get(origin['sourceAttemptRecordSha256'])
        if source is None:
            raise InvalidActionResult('候选修复缺少物理来源 Attempt。')
        source_envelope=ledger.envelopes_by_sha256[source.envelope_sha256]
        if source_envelope.value['actionContractId']!=origin['sourceActionContractId']:
            raise InvalidActionResult('候选修复来源合同漂移。')
        if origin['sourceKind']=='AUTHOR_FAILURE':
            if source.outcome!='FAILED' or source.raw_sha256 is None:
                raise InvalidActionResult('Author 接续缺少原始失败候选。')
            return ledger.raw_outputs[source.raw_sha256],None
        if source.outcome!='SUCCEEDED' or source.normalized_result_sha256 is None:
            raise InvalidActionResult('语义接续必须绑定成功的非 PASS Review。')
        semantic_raw=semantic_sources.get(origin['semanticSourceSha256'])
        base=bases.get(plan['baseCandidateSha256'])
        if semantic_raw is None or base is None:
            raise InvalidActionResult('语义接续缺少 base 或来源描述符。')
        if not isinstance(semantic_raw,bytes):semantic_raw=canonical_json_bytes(semantic_raw)
        if not isinstance(base,bytes):base=canonical_json_bytes(base)
        bound_bases[plan['baseCandidateSha256']] = base
        bound_semantic_sources[origin['semanticSourceSha256']] = semantic_raw
        semantic=_read_candidate(semantic_raw)
        review_raw=ledger.normalized_results[source.normalized_result_sha256]
        review=_read_candidate(review_raw)
        if (sha256_bytes(semantic_raw)!=origin['semanticSourceSha256']
                or sha256_bytes(base)!=plan['baseCandidateSha256']
                or semantic['ownerIRSha256']!=sha256_bytes(base)
                or semantic['reviewAttemptRecordSha256']!=origin['sourceAttemptRecordSha256']
                or semantic['reviewDecisionSha256']!=origin['reviewDecisionSha256']
                or semantic['reviewCandidateSha256']!=origin['reviewCandidateSha256']
                or semantic['reviewDecision']!=review or review.get('decision')=='PASS'
                or source_envelope.value['baseCandidateSha256']!=origin['reviewCandidateSha256']):
            raise InvalidActionResult('语义 Review、base 或来源描述符绑定无效。')
        return base,semantic
    pending=list(patches)
    while pending:
        ready=[]
        for entry in pending:
            _,logical,plan,_,_,_,record=entry
            initial,_=source_base(plan)
            source=ledger.attempt_records[plan['origin']['sourceAttemptRecordSha256']]
            current,chain,_=heads.get(logical,(initial,[],None))
            previous_receipt_sha256=sha256_bytes(chain[-1]['receipt']) if chain else None
            if plan['origin'].get('previousReceiptSha256')!=previous_receipt_sha256:
                continue
            if sha256_bytes(current)==plan['baseCandidateSha256']:
                ready.append(entry)
        if not ready:
            raise InvalidActionResult('补丁链缺少前驱、Receipt 绑定或基线发生漂移。')
        entry=min(ready,key=lambda e:(bool(e[6] and e[6].outcome=='SUCCEEDED'),e[0],e[4].value['attempt'],e[4].value['actionId']))
        pending.remove(entry)
        _,logical,plan,plan_raw,envelope,packet_raw,record=entry
        origin=plan['origin'];source=ledger.attempt_records[origin['sourceAttemptRecordSha256']]
        source_envelope=ledger.envelopes_by_sha256[source.envelope_sha256]
        if ((origin['sourceKind']=='AUTHOR_FAILURE' and source.logical_work_id!=logical)
            or any(envelope.value[k]!=source_envelope.value[k] for k in ('runId','stageKind','inputRevisionSha256','baseCandidateSha256','upstreamCheckpointSha256s'))
            or envelope.value['budgetPolicySha256']!=origin['budgetPolicySha256']):
            raise InvalidActionResult('接续改变了来源、Owner 或冻结输入。')
        author_raw,semantic_source=source_base(plan)
        current,chain,old_index=heads.get(logical,(author_raw,[],None))
        diagnose, make_plan, verify_full=owner_callbacks(
            source_envelope.value,json.loads(packets[source_envelope.value['packetSha256']]),
            semantic_source=semantic_source)
        report=diagnose(current,origin)
        if old_index is not None:
            report['objectIndex']=old_index
        expected_plan=make_plan(current,report,origin)
        if expected_plan!=plan_raw:
            raise InvalidActionResult('RepairPlan 不能由 Owner 的原始候选和诊断重建。')
        if record is None or record.outcome!='SUCCEEDED':
            continue
        item={'plan':plan_raw,'patch':ledger.raw_outputs[record.raw_sha256],
              'receipt':ledger.normalized_results[record.normalized_result_sha256],
              'record':canonical_json_bytes(attempt_record_value(record)), 'envelope':canonical_json_bytes(envelope.value),'packet':packet_raw}
        patch=parse_repair_document(item['patch'],'PatchResult')
        normalized_patch=canonical_json_bytes(patch)
        merged,receipt=apply_repair_patch(current,plan_raw,normalized_patch,group_id=patch['groupId'],
            verify_group=lambda raw,group:verify_group_progress(report,diagnose(raw,origin),group))
        if receipt!=item['receipt']:
            raise InvalidActionResult('已保存 receipt 不能重放。')
        chain=[*chain,item];heads[logical]=(merged,chain,json.loads(receipt)['objectIndex'])
        if not diagnose(merged,origin)['issues']:
            # Each group was independently revalidated above; resolution repeats
            # mechanical merging with the corresponding frozen report as well.
            chain_by_group={json.loads(i['patch'])['groupId']:i for i in chain}
            def replay_group(raw,group):
                bound=json.loads(chain_by_group[group['groupId']]['plan'])
                verify_group_progress(bound['diagnostic'],diagnose(raw,bound['origin']),group)
            final,resolution=resolve_candidate(author_raw,chain,verify_group=replay_group,verify_candidate=verify_full)
            resolutions[logical]=resolution;results[sha256_bytes(resolution)]=final
    return replace(ledger,candidate_resolutions=resolutions,resolved_candidates=results,repair_heads=heads,
                   candidate_repair_bases=bound_bases,
                   candidate_repair_semantic_sources=bound_semantic_sources,
                   normalized_results={**ledger.normalized_results, **{sha256_bytes(raw):raw for raw in results.values()}})


def append_object_group(raw, collection, value_schema, issue_ids, *, group_id, alternatives=()):
    """Mechanical constructor; Owner supplies the collection, schema and obligations."""
    candidate=_read_candidate(raw);rows=_at(candidate,'' if collection=='$' else '/'+collection)
    slot={'slotId':'append-'+group_id,'operation':'APPEND_OBJECT','collection':collection,
          'objectId':'new-'+group_id,'oldValueSha256':_digest(rows),'valueSchema':value_schema,'maxNewObjects':1}
    return {'groupId':group_id,'issueIds':list(issue_ids),'readSet':[],'slots':[slot,*alternatives],
            'verificationObligations':list(issue_ids)}


def remove_object_group(raw, entry, issue_ids):
    return {'groupId':'remove-'+_digest([entry['objectId'],issue_ids])[:24],'issueIds':list(issue_ids),
        'readSet':[{'objectId':entry['objectId'],'fields':[]}],
        'slots':[{'slotId':'remove-'+entry['objectId'],'operation':'REMOVE_OBJECT',
                  'collection':entry['collection'],'objectId':entry['objectId'],'oldValueSha256':entry['sha256']}],
        'verificationObligations':list(issue_ids)}


def transform_roots_group(raw, entries, schema, issue_ids, *, namespace, maximum, reference_slots=()):
    collection=entries[0]['collection']
    slot={'slotId':'transform-'+_digest([e['objectId'] for e in entries])[:24],'operation':'TRANSFORM_ROOTS',
        'collection':collection,'objectId':entries[0]['objectId'],'inputObjectIds':[e['objectId'] for e in entries],
        'oldValueSha256':_digest([_at(_read_candidate(raw),e['path']) for e in entries]),
        'valueSchema':{'type':'array','items':schema,'minItems':1,'maxItems':maximum},'maxNewObjects':maximum,
        'outputNamespace':namespace,'referenceClosure':[s['slotId'] for s in reference_slots]}
    return {'groupId':slot['slotId'],'issueIds':list(issue_ids),
        'readSet':[{'objectId':e['objectId'],'fields':list(_at(_read_candidate(raw),e['path']))} for e in entries],
        'slots':[slot,*reference_slots],'verificationObligations':list(issue_ids)}
