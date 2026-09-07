from __future__ import annotations
from action_ledger import effective_result, effective_result_bytes
import json

from copy import deepcopy
from pathlib import Path

from contracts import (
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_contract,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]


# Stage seal control: no planned future Review or generic patch transport.
OWNER_COLLECTION = {'SCOPE':'decisions', 'STORY_AC':'stories', 'TASK':'tasks'}
REVIEW_CONTRACT = {'SCOPE':'SOURCE_SCOPE-v1','STORY_AC':'STORY_DESIGN-v1','TASK':'TASK_ESTIMATION-v1'}


def control_identity(stage_kind, action_kind, subject_sha256, action_contract_sha256):
    if stage_kind not in OWNER_COLLECTION or action_kind not in {'REVIEW','REPAIR'}:
        raise ValueError('未知阶段 control identity。')
    key = 'candidateSha256' if action_kind == 'REVIEW' else 'reviewDecisionSha256'
    identity = {'stageKind':stage_kind,'actionKind':action_kind,key:subject_sha256,'actionContractSha256':action_contract_sha256}
    logical = 'logical-' + sha256_bytes(canonical_json_bytes(identity))
    return logical, 'control-group-' + sha256_bytes(canonical_json_bytes({'logicalWorkId':logical}))


def validate_owner_clarification(stage_kind, review, resolution):
    from contracts import load_schema_registry
    if (validate_contract(resolution,'owner-clarification.schema.json',load_schema_registry(SKILL_ROOT))
            or stage_kind != resolution['stageKind'] or review['decision']!='INPUT_REQUIRED'
            or resolution['reviewDecisionSha256']!=sha256_bytes(canonical_json_bytes(review))):
        raise ValueError('澄清必须绑定当前 INPUT_REQUIRED Review 和允许的 Task 实施范围。')



def is_manual_repair(resolution):
    return isinstance(resolution,dict) and resolution.get('contract')=='ai-sow-owner-repair-authorization-v1'


def resolution_field(resolution):
    return 'ownerRepairAuthorization' if is_manual_repair(resolution) else 'ownerClarification'


def owner_resolution(body):
    return body.get('ownerRepairAuthorization',body.get('ownerClarification'))


def review_resolution_fields(repairs):
    fields={}
    for repair in repairs:
        if len(repair)==3 and repair[2] is not None:
            fields[resolution_field(repair[2])]=repair[2]
    return fields


def validate_owner_resolution(stage_kind, review, resolution):
    if not is_manual_repair(resolution):
        return validate_owner_clarification(stage_kind,review,resolution)
    from contracts import load_schema_registry
    if (validate_contract(resolution,'owner-repair-authorization.schema.json',load_schema_registry(SKILL_ROOT))
            or stage_kind!=resolution['stageKind'] or review['decision']!='REPAIRABLE_SEMANTIC'
            or resolution['reviewDecisionSha256']!=sha256_bytes(canonical_json_bytes(review))):
        raise ValueError('继续修复裁定必须绑定本次可修复 Review、Owner 和一个新增候选。')


def repair_action_contract_id(stage, plan):
    """A frozen Author plan owns the matching Repair version, including proof replay."""
    from stage_planner import bound_action_contract_ids
    if stage not in REVIEW_CONTRACT or not isinstance(plan,dict) or plan.get('stageKind') != stage:
        raise ValueError('Repair 合同必须绑定同阶段冻结计划。')
    contracts = bound_action_contract_ids(plan)
    if stage != 'TASK':
        return stage + '_REPAIR-v1'
    selected = contracts.get('TASK')
    if selected not in {'TASK-v1', 'TASK-v2'}:
        raise ValueError('Task Repair 缺少受支持的冻结 Author 合同。')
    return {'TASK-v1': 'TASK_REPAIR-v1', 'TASK-v2': 'TASK_REPAIR-v2'}[selected]


def verify_manual_authorization_records(entries, events, stage, run_id, revision_hash, *, require_repair=False, review_inputs=None, stage_plan=None):
    """Portable proof of the original stop and an explicit, single-candidate continuation."""
    from contracts import load_schema_registry, action_contract_binding
    registry=load_schema_registry(SKILL_ROOT)
    authorized=[event for event in events if event['type']=='OWNER_REPAIR_AUTHORIZED' and event['payload']['stageKind']==stage]
    if len(authorized)!=len(entries): raise ValueError('人工继续裁定事件与正文集合不完整。')
    result={}
    for event in authorized:
        value=event['payload'];key=value['reviewDecisionSha256'];entry=entries.get(key,{})
        answer=entry.get('authorization',{});terminal=entry.get('terminalState',{})
        if (key in result or validate_contract(answer,'owner-repair-authorization.schema.json',registry)
                or validate_contract(terminal,'run-state.schema.json',registry)
                or answer['reviewDecisionSha256']!=key or answer['stageKind']!=stage or answer['runId']!=run_id
                or sha256_bytes(canonical_json_bytes(answer))!=value['authorizationSha256']
                or sha256_bytes(canonical_json_bytes(terminal))!=value['terminalStateSha256']
                or answer['terminalStateSha256']!=value['terminalStateSha256']
                or terminal['runId']!=run_id or terminal['phase']!='DONE' or terminal['result']!='MANUAL_REVIEW_REQUIRED'
                or terminal['currentCandidateSha256']!=answer['candidateSha256']
                or terminal['currentInputRevisionSha256']!=revision_hash):
            raise ValueError('人工继续修复没有完整原终态、候选与授权证明。')
        _,review_contract=action_contract_binding(SKILL_ROOT,REVIEW_CONTRACT[stage])
        repair_id=repair_action_contract_id(stage,stage_plan) if stage=='TASK' else stage+'_REPAIR-v1'
        _,repair_contract=action_contract_binding(SKILL_ROOT,repair_id)
        review_logical,_=control_identity(stage,'REVIEW',answer['candidateSha256'],review_contract)
        repair_logical,_=control_identity(stage,'REPAIR',key,repair_contract)
        before=[item['sequence'] for item in events if item['type']=='ACTION_ISSUED' and item['payload']['logicalWorkId']==review_logical]
        after=[item['sequence'] for item in events if item['type']=='ACTION_ISSUED' and item['payload']['logicalWorkId']==repair_logical]
        if not before or max(before)>=event['sequence'] or (after and min(after)<=event['sequence']) or require_repair and not after:
            raise ValueError('人工裁定必须在实际失败 Review 与其 Repair 发行之间。')
        if review_inputs is not None:
            hashes={sha256_bytes(canonical_json_bytes(packet)) for packet in review_inputs.values()
                if packet['workItems'][0]['payload']['candidateSha256']==answer['candidateSha256']}
            recorded={item['payload'].get('outputSha256') for item in events if item['type']=='DETERMINISTIC_STEP_FINISHED'
                and item['payload'].get('stageKind')==stage and item['payload'].get('semanticRevision')==value['semanticRevision']
                and item['payload']['stepKind']=='MATERIALIZE' and item['payload']['outcome']=='SUCCEEDED'}
            if len(hashes)!=1 or hashes!=recorded: raise ValueError('人工继续未保留实际累计候选次数。')
        result[key]=answer
    return result

def repair_root_keys(stage_kind, original, review, resolution=None):
    """Review roots plus only their same-Owner incoming-reference closure."""
    if resolution is not None: validate_owner_resolution(stage_kind,review,resolution)
    elif review['decision'] != 'REPAIRABLE_SEMANTIC':
        raise ValueError('只有 REPAIRABLE_SEMANTIC 或已批准的精确实施澄清授权修复。')
    collection = OWNER_COLLECTION[stage_kind]
    before = {row['localKey']: row for row in original[collection]}
    keys = {key for finding in review['findings'] for key in finding['subjectIds']}
    if not keys or not keys <= before.keys() or len(before) != len(original[collection]):
        raise ValueError('Repair roots 必须绑定当前 Owner 的唯一 localKeys。')
    if stage_kind == 'SCOPE':
        while True:
            incoming = {key for key, row in before.items() if any(
                keys.intersection(relation['targetLocalKeys']) for relation in row.get('relations', []))}
            if incoming <= keys: break
            keys.update(incoming)
    if is_manual_repair(resolution) and set(resolution['rootKeys'])!=keys:
        raise ValueError('人工继续裁定必须精确绑定本次修复影响集。')
    return sorted(keys)


def repair_key_root(key, authorized_keys):
    if key in authorized_keys: return key
    parents = [root for root in authorized_keys if key.startswith(root + ':repair:')
               and key[len(root + ':repair:'):]]
    return max(parents, key=len) if parents else None


def replace_owner_decisions(stage_kind, original, review, replacements, resolution=None):
    """Replace the authorized subgraph; complete Owner validation closes all obligations."""
    collection = OWNER_COLLECTION[stage_kind]
    keys = set(repair_root_keys(stage_kind, original, review, resolution))
    before = {row['localKey']: row for row in original[collection]}
    after = {row['localKey']: row for row in replacements[collection]}
    if (not after or len(after) != len(replacements[collection])
            or any(repair_key_root(key, keys) is None or key in before and key not in keys for key in after)):
        raise ValueError('Repair 仅允许授权 roots 的完整替换、合并或 :repair: 派生拆分。')
    if is_manual_repair(resolution):
        fields=set(resolution['allowedFields'])
        if set(after)!=keys or any(not fields<=before[key].keys() for key in keys):
            raise ValueError('字段修复必须保留全部授权 roots 和既有字段。')
        for key in keys:
            if ({k:v for k,v in before[key].items() if k not in fields}
                    !={k:v for k,v in after[key].items() if k not in fields}):
                raise ValueError('人工继续修复越过了批准字段。')
        if all(before[key]==after[key] for key in keys): raise ValueError('继续修复不能提交无变化候选。')
    replaced = {key for finding in review['findings'] for key in finding['subjectIds']}
    merged = {key: row for key, row in before.items() if key not in replaced}
    merged.update(after)
    return {collection: [deepcopy(merged[key]) for key in sorted(merged)]}

def semantic_repair_lineage(stage_kind, review_decision_sha256, candidate_patch_action_contract_sha256):
    return 'candidate-repair-'+sha256_bytes(canonical_json_bytes({
        'stageKind':stage_kind,'reviewDecisionSha256':review_decision_sha256,
        'candidatePatchActionContractSha256':candidate_patch_action_contract_sha256}))


def candidate_repair_replacement(stage_kind, original, repaired, review, resolution=None):
    """Project a verified semantic CandidateResolution back to the legacy materializer seam."""
    collection=OWNER_COLLECTION[stage_kind]
    keys=set(repair_root_keys(stage_kind,original,review,resolution))
    affected=[deepcopy(row) for row in repaired[collection] if repair_key_root(row['localKey'],keys) is not None]
    replacement={collection:affected}
    if replace_owner_decisions(stage_kind,original,review,replacement,resolution)!=repaired:
        raise ValueError('CandidateResolution 不能精确重建完整修复后 Owner IR。')
    return replacement


def _semantic_owner_binding(stage, owner_packet, owner_contract_id):
    import scope_compiler,delivery_compiler,task_compiler
    if stage=='SCOPE':
        return (scope_compiler,
            lambda raw:scope_compiler.validate_bound_scope_result('SCOPE_SYNTHESIS',owner_packet,raw))
    if stage=='STORY_AC':
        return delivery_compiler,lambda raw:delivery_compiler.validate_bound_story_result(owner_packet,raw)
    if stage=='TASK':
        return task_compiler,lambda raw:task_compiler.validate_bound_task_result(owner_packet,raw)
    raise ValueError('语义修复只属于三个阶段 Owner。')


def _semantic_candidate_callbacks(envelope, packet, semantic_source):
    from candidate_repair import (append_object_group,build_repair_plan,diagnostic_report,
        group_fields,index_candidate,make_issue,schema_at,transform_roots_group)
    from contracts import InvalidActionResult
    stage=semantic_source['stageKind'];owner_packet=semantic_source['ownerPacket']
    review=semantic_source['reviewDecision'];resolution=semantic_source.get('ownerResolution')
    owner_contract_id=semantic_source['ownerActionContractId']
    owner,bound=_semantic_owner_binding(stage,owner_packet,owner_contract_id)
    collection=OWNER_COLLECTION[stage]
    def semantic_issue(finding):
        root=finding['subjectIds'][0] if finding['subjectIds'] else ''
        path='/'+collection+'/'+root if root else '/'+collection
        issue=make_issue('SEMANTIC_'+finding['code'],path,stage,finding['message'],
            '仅修改 Review 明确定位的 Owner root，并由 fresh Review 重新判断。',
            subjects=[{'objectId':collection+'/'+key} for key in finding['subjectIds']])
        issue['evidenceRefs']=[{'refId':key,'sha256':sha256_bytes(canonical_json_bytes(key))}
                               for key in finding.get('evidenceIds',())]
        return issue
    def mechanical_issues(raw):
        try:
            bound(raw)
        except InvalidActionResult as error:
            diagnostics=error.diagnostic.findings or (error.diagnostic,)
            from candidate_repair import issues_from_diagnostics
            return issues_from_diagnostics(diagnostics,stage,json.loads(raw))
        return []
    def diagnose(raw,origin):
        issues=mechanical_issues(raw)
        if sha256_bytes(raw)==semantic_source['ownerIRSha256']:
            issues.extend(semantic_issue(finding) for finding in review['findings'])
        return diagnostic_report(raw,issues,owner=stage,checker_file=owner.__file__,packet=owner_packet,
            origin=origin,blocked=(),domains=['SCHEMA','OWNER_BINDINGS','SEMANTIC_REVIEW'])
    def plan(raw,report,origin):
        value=json.loads(raw);roots=repair_root_keys(stage,value,review,resolution)
        rows={row['localKey']:i for i,row in enumerate(value[collection])}
        direct={};broad=False
        for finding in review['findings']:
            issue_id=semantic_issue(finding)['issueId']
            paths=[]
            for key in finding['subjectIds']:
                projected=semantic_source['ownerIndex'][key]['path']
                suffix=finding['path'][len(projected):] if finding['path'].startswith(projected) else ''
                if stage=='SCOPE' and suffix=='/name':
                    paths.append(f"/{collection}/{rows[key]}/boundaryEvidence/name")
                elif stage=='STORY_AC' and suffix=='/name':
                    paths.append(f"/{collection}/{rows[key]}/deliverableOutcome")
                elif stage=='TASK' and suffix in {'/name','/deliverableBoundary'}:
                    paths.append(f"/{collection}/{rows[key]}/deliverableBoundary")
                elif stage=='TASK' and suffix=='/complexity':
                    paths.append(f"/{collection}/{rows[key]}/complexityDecision")
                else:
                    broad=True
            direct[issue_id]=paths
        if is_manual_repair(resolution):
            allowed=set(resolution['allowedFields'])
            direct={issue_id:[path for path in paths if path.rsplit('/',1)[-1] in allowed]
                    for issue_id,paths in direct.items()}
            if broad or any(not paths for paths in direct.values()):
                raise InvalidActionResult('人工裁定 finding 不能映射到 allowedFields。')
        if not broad:
            groups=group_fields(raw,report,owner_contract_id,direct)
            if groups:return build_repair_plan(raw,report,groups,origin=origin)
        entries=[entry for entry in index_candidate(raw,inherited=report.get('objectIndex',()))
                 if entry['objectId'] in {collection+'/'+key for key in roots}]
        if len(entries)!=len(roots):
            raise InvalidActionResult('Review root 不能解析为唯一 Owner 对象。')
        schema=schema_at(owner_contract_id,f'/{collection}/0')
        group=transform_roots_group(raw,entries,schema,
            [item['issueId'] for item in report['issues'] if item['code'].startswith('SEMANTIC_')],
            namespace=roots[0]+':repair:',maximum=max(1,len(roots)*2))
        return build_repair_plan(raw,report,[group],origin=origin)
    def full(raw):
        bound(raw)
    return diagnose,plan,full


def review_route(review, *, previous_review=None, resolution=None):
    if resolution is not None:
        validate_owner_resolution(resolution.get('stageKind'),review,resolution)
        return 'REPAIR'
    if review['decision'] == 'PASS':
        if review['findings']: raise ValueError('PASS 不允许 findings。')
        return 'SEAL'
    if not review['findings']: raise ValueError('非 PASS 必须提供 findings。')
    if review['decision'] == 'REPAIRABLE_SEMANTIC':
        # At most two semantic candidate revisions, including the original.
        return 'MANUAL_REVIEW_REQUIRED' if previous_review is not None else 'REPAIR'
    return {'INPUT_REQUIRED':'WAITING_INPUT','CONTRACT_GAP':'CONTRACT_UNSUPPORTED',
            'OWNER_BUG':'MANUAL_REVIEW_REQUIRED'}[review['decision']]


def validate_bound_review_result(packet, normalized_result):
    from contracts import InvalidActionResult
    body = packet['workItems'][0]['payload']
    result = json.loads(normalized_result)
    if result['decision'] == 'REPAIRABLE_SEMANTIC':
        allowed = set(body['ownerIndex'])
        if any(not set(finding['subjectIds']) <= allowed for finding in result['findings']):
            raise InvalidActionResult('Repairable finding 必须使用当前 Owner root localKey。')
    evidence = set(body['evidenceIds'])
    if any(not set(finding['evidenceIds']) <= evidence for finding in result['findings']):
        raise InvalidActionResult('Review finding 使用了未授权来源。')


def validate_review_packet(packet, candidate_bytes, owner_index, obligations):
    body = packet['workItems'][0]['payload']
    if (canonical_json_bytes(body['candidate']) != candidate_bytes
            or body['candidateSha256'] != sha256_bytes(candidate_bytes)
            or body['ownerIndex'] != owner_index or body['reviewObligations'] != list(obligations)):
        raise ValueError('Review packet 缺失义务或未绑定本轮候选/Owner index。')
    if set(packet) != {'workItems','contextRefs'} or len(packet['workItems']) != 1:
        raise ValueError('Review 必须为 fresh singleton packet。')


def stage_checkpoint(stage_kind, input_revision_bytes, stage_plan_bytes, upstream_checkpoint_bytes,
                     candidate_bytes, validator_result_bytes, review_packet_bytes, review_decision_bytes,
                     attempt_hashes, *, prior_state_bytes=None):
    value = {'stageKind':stage_kind, 'inputRevisionSha256':sha256_bytes(input_revision_bytes),
        'stagePlanSha256':sha256_bytes(stage_plan_bytes),
        'upstreamCheckpointSha256s':sorted(sha256_bytes(raw) for raw in upstream_checkpoint_bytes),
        'effectiveAttemptRecordSha256s':sorted(attempt_hashes), 'candidateSha256':sha256_bytes(candidate_bytes),
        'validatorResultSha256':sha256_bytes(validator_result_bytes),'reviewPacketSha256':sha256_bytes(review_packet_bytes),
        'reviewDecisionSha256':sha256_bytes(review_decision_bytes)}
    if prior_state_bytes is not None:
        if stage_kind != 'SCOPE': raise ValueError('Prior snapshot 只在 ScopeCheckpoint 绑定。')
        value['priorStateSha256']=sha256_bytes(prior_state_bytes)
    from contracts import load_schema_registry
    if validate_contract(value,'stage-checkpoint.schema.json',load_schema_registry(SKILL_ROOT)):
        raise ValueError('StageCheckpoint 合同无效。')
    return value


def verify_checkpoint_proof(checkpoint, *, revision_bytes, plan_bytes, upstream_bytes, ledger,
                            candidates, validators, review_inputs, packets, prior_states, manual_authorizations=None, task_repair_verifier=None):
    """Read-only closure over caller-resolved bytes and the strict authorized ledger."""
    from contracts import action_contract_binding, load_schema_registry
    from stage_planner import _effective_success, _effective_envelope
    if validate_contract(checkpoint,'stage-checkpoint.schema.json',load_schema_registry(SKILL_ROOT)):
        raise ValueError('Checkpoint schema 无效。')
    stage=checkpoint['stageKind'];plan=json.loads(plan_bytes)
    if (checkpoint['inputRevisionSha256']!=sha256_bytes(revision_bytes)
            or checkpoint['stagePlanSha256']!=sha256_bytes(plan_bytes) or plan['stageKind']!=stage
            or checkpoint['upstreamCheckpointSha256s']!=sorted(sha256_bytes(raw) for raw in upstream_bytes)
            or plan['upstreamCheckpointSha256s']!=checkpoint['upstreamCheckpointSha256s']):
        raise ValueError('Checkpoint 上游/revision/StagePlan 绑定无效。')
    stage_records={digest:record for digest,record in ledger.attempt_records.items()
                   if ledger.envelopes_by_sha256[record.envelope_sha256].value['stageKind']==stage}
    if set(checkpoint['effectiveAttemptRecordSha256s'])!=set(stage_records):
        raise ValueError('Checkpoint 未绑定实际完整 Attempt 链。')
    allowed={work['logicalWorkId'] for work in plan['works']}
    for work in plan['works']:
        logical=work['logicalWorkId'];packet_plan=work['packetPlan']
        envelope=_effective_envelope(ledger,logical)
        effective_result(ledger,logical)
        if (envelope.value['inputRevisionSha256']!=checkpoint['inputRevisionSha256']
                or envelope.value['actionContractId']!=packet_plan['actionContractId']
                or envelope.value['actionContractSha256']!=packet_plan['actionContractSha256']):
            raise ValueError('计划工作没有有效当前 Attempt。')
        packet=json.loads(packets[envelope.value['packetSha256']])
        if [{'workItemId':item['workItemId'],'payloadSha256':sha256_bytes(canonical_json_bytes(item['payload']))}
                for item in packet['workItems']]!=packet_plan['orderedWorkItems']:
            raise ValueError('实际 packet work items 不匹配冻结计划。')
        base=packet['contextRefs'][:len(packet_plan['contextRefs'])]
        if [{'refId':ref['refId'],'contentSha256':sha256_bytes(canonical_json_bytes(ref['canonicalContent']))}
                for ref in base]!=packet_plan['contextRefs']:
            raise ValueError('实际 packet base contexts 不匹配冻结计划。')
        for dependency in packet_plan['dependencyLogicalWorkIds']:
            digest,record=effective_result(ledger,dependency)
            from action_ledger import dependency_context
            expected=dependency_context(ledger,dependency)
            if expected not in packet['contextRefs']: raise ValueError('实际 packet dependency 绑定不一致。')
    reviews=[]
    for raw in review_inputs.values():
        body=json.loads(raw)['workItems'][0]['payload'];candidate_hash=body['candidateSha256']
        if sha256_bytes(canonical_json_bytes(body['candidate']))!=candidate_hash or candidates.get(candidate_hash)!=canonical_json_bytes(body['candidate']):
            raise ValueError('候选 revision 与 Review input 不一致。')
        _,contract_hash=action_contract_binding(SKILL_ROOT,REVIEW_CONTRACT[stage])
        logical,group=control_identity(stage,'REVIEW',candidate_hash,contract_hash)
        envelope=_effective_envelope(ledger,logical)
        digest,record=effective_result(ledger,logical)
        actual=json.loads(packets[envelope.value['packetSha256']])
        if (actual['workItems']!=json.loads(raw)['workItems'] or envelope.value['groupId']!=group
                or envelope.value['baseCandidateSha256']!=candidate_hash):
            raise ValueError('Review 未绑定 fresh candidate/packet/control identity。')
        allowed.add(logical)
        decision=json.loads(ledger.normalized_results[record.normalized_result_sha256])
        validate_bound_review_result(actual,ledger.normalized_results[record.normalized_result_sha256])
        matches=[raw for raw in validators.values() if json.loads(raw)=={'stageKind':stage,'candidateSha256':candidate_hash,
            'validatorContractSha256':sha256_bytes((SKILL_ROOT/'contracts/sow-model.schema.json').read_bytes()),'diagnostics':[]}]
        if len(matches)!=1: raise ValueError('每个候选 revision 必须有完整有效 validator result。')
        reviews.append((candidate_hash,envelope,record,decision,matches[0]))
    if not reviews: raise ValueError('Stage 缺少实际 Review。')
    finals=[item for item in reviews if item[0]==checkpoint['candidateSha256']]
    if len(finals)!=1: raise ValueError('最终 candidate 不唯一。')
    candidate_hash,envelope,record,decision,validator=finals[0]
    if (decision!={'decision':'PASS','findings':[]} or record.normalized_result_sha256!=checkpoint['reviewDecisionSha256']
            or envelope.value['packetSha256']!=checkpoint['reviewPacketSha256']
            or sha256_bytes(validator)!=checkpoint['validatorResultSha256']):
        raise ValueError('最终 validator/Review/PASS 绑定无效。')
    task_repairs=[];owner_repairs=[];automatic=0;clarified=0;manual_seen=set()
    for old_hash,old_envelope,old_record,old_review,_ in reviews:
        if old_hash==candidate_hash: continue
        if old_review['decision'] not in {'REPAIRABLE_SEMANTIC','INPUT_REQUIRED'}: raise ValueError('无条件语义 Repair 不合法。')
        _,contract_hash=action_contract_binding(SKILL_ROOT,repair_action_contract_id(stage,plan))
        logical,group=control_identity(stage,'REPAIR',old_record.normalized_result_sha256,contract_hash)
        repair_envelope=_effective_envelope(ledger,logical);effective_result(ledger,logical)
        repair_packet=json.loads(packets[repair_envelope.value['packetSha256']])['workItems'][0]['payload']
        if repair_envelope.value['groupId']!=group or repair_packet['reviewDecisionSha256']!=old_record.normalized_result_sha256 or repair_packet['reviewDecision']!=old_review:
            raise ValueError('Repair 未绑定触发 Review 的全部 findings。')
        resolution=owner_resolution(repair_packet)
        if is_manual_repair(resolution):
            validate_owner_resolution(stage,old_review,resolution)
            if (resolution['candidateSha256']!=old_hash
                    or (manual_authorizations or {}).get(old_record.normalized_result_sha256)!=resolution):
                raise ValueError('继续修复未绑定原终态的正式裁定。')
            manual_seen.add(old_record.normalized_result_sha256)
        elif old_review['decision']=='INPUT_REQUIRED':
            validate_owner_clarification(stage,old_review,resolution or {})
            clarified+=1
        else:
            if resolution is not None: raise ValueError('自动修复携带了不适用的裁定。')
            automatic+=1
        _,repair_record=effective_result(ledger,logical)
        replacement=json.loads(ledger.normalized_results[repair_record.normalized_result_sha256])
        replace_owner_decisions(stage,repair_packet['ownerIR'],old_review,replacement,resolution)
        owner_repairs.append((old_hash,repair_packet,replacement))
        if stage == 'TASK':
            _,repair_record = effective_result(ledger,logical)
            task_repairs.append((old_hash,repair_packet,json.loads(effective_result_bytes(ledger,logical))))
        allowed.add(logical)
    if automatic>1 or clarified>1 or manual_seen!=set(manual_authorizations or {}):
        raise ValueError('新增候选必须逐次绑定明确裁定，不能重置自动计数。')
    if task_repairs:
        if task_repair_verifier is None:
            raise ValueError('Task 修复证明缺少 Owner 验证器。')
        author_ir={'tasks':[]}
        for work in plan['works']:
            effective_result(ledger,work['logicalWorkId'])
            for row in json.loads(effective_result_bytes(ledger,work['logicalWorkId']))['tasks']:
                node=deepcopy(row);node['localKey']=work['logicalWorkId']+':'+node['localKey'];author_ir['tasks'].append(node)
        author_ir['tasks'].sort(key=lambda row:row['localKey'])
        resolutions=task_repair_verifier(task_repairs,candidates,revision_bytes,author_ir,candidate_hash)
        for raw in review_inputs.values():
            body=json.loads(raw)['workItems'][0]['payload']
            if {key:body[key] for key in ('ownerClarification','ownerRepairAuthorization') if key in body}!=resolutions.get(body['candidateSha256'],{}):
                raise ValueError('fresh Review 未绑定该候选的批准澄清。')
    elif owner_repairs:
        if stage=='SCOPE':
            works={work['logicalWorkId'] for work in plan['works'] if work['packetPlan']['actionKind'].startswith('SCOPE_')}
            consumed={key for work in plan['works'] if work['logicalWorkId'] in works for key in work['packetPlan']['dependencyLogicalWorkIds']}
            roots=works-consumed
            if len(roots)!=1: raise ValueError('Scope Author root 不唯一。')
            root=roots.pop();effective_result(ledger,root)
            current_ir=json.loads(effective_result_bytes(ledger,root))
        else:
            current_ir={'stories':[]}
            for work in plan['works']:
                effective_result(ledger,work['logicalWorkId'])
                for row in json.loads(effective_result_bytes(ledger,work['logicalWorkId']))['stories']:
                    node=deepcopy(row);node['localKey']=work['logicalWorkId']+':'+node['localKey'];current_ir['stories'].append(node)
            current_ir['stories'].sort(key=lambda row:row['localKey'])
        remaining=list(owner_repairs);operations=[]
        bodies={json.loads(raw)['workItems'][0]['payload']['candidateSha256']:json.loads(raw)['workItems'][0]['payload'] for raw in review_inputs.values()}
        while remaining:
            matches=[entry for entry in remaining if entry[1]['ownerIR']==current_ir]
            if len(matches)!=1: raise ValueError('Owner 修复必须从实际 Author IR 唯一连续恢复。')
            entry=matches[0];remaining.remove(entry);old_hash,body,replacement=entry
            expected=review_resolution_fields(operations)
            if {key:bodies[old_hash][key] for key in ('ownerClarification','ownerRepairAuthorization') if key in bodies[old_hash]}!=expected:
                raise ValueError('Owner Review 未携带累计人工裁定。')
            resolution=owner_resolution(body)
            current_ir=replace_owner_decisions(stage,current_ir,body['reviewDecision'],replacement,resolution)
            operations.append((body['reviewDecision'],replacement,resolution))
        if {key:bodies[candidate_hash][key] for key in ('ownerClarification','ownerRepairAuthorization') if key in bodies[candidate_hash]}!=review_resolution_fields(operations):
            raise ValueError('最终 Owner Review 未绑定累计人工裁定。')
    for digest,record in stage_records.items():
        envelope=ledger.envelopes_by_sha256[record.envelope_sha256]
        if envelope.value['actionContractId'].startswith('PROTOTYPE_'):
            if stage!='SCOPE': raise ValueError('Prototype 只属于 Scope chain。')
            identity=json.loads(packets[envelope.value['packetSha256']])['workItems'][0]['payload']['identity']
            if envelope.value['logicalWorkId']!='logical-'+sha256_bytes(canonical_json_bytes(identity)):
                raise ValueError('Prototype control identity 不一致。')
            allowed.add(envelope.value['logicalWorkId'])
    from candidate_repair import patch_context
    for digest,record in stage_records.items():
        envelope=ledger.envelopes_by_sha256[record.envelope_sha256]
        if envelope.value['actionContractId']=='CANDIDATE_PATCH-v1':
            view=patch_context(json.loads(packets[envelope.value['packetSha256']]))
            origin=view['origin']
            if origin['sourceKind']=='SEMANTIC_REVIEW':
                source=stage_records.get(origin['sourceAttemptRecordSha256'])
                authorized=source is not None and source.logical_work_id in allowed
            else:
                authorized=origin['originLogicalWorkId'] in allowed
            if not authorized:
                raise ValueError('Patch 来源不属于本阶段冻结工作。')
            if origin['originLogicalWorkId'] not in ledger.candidate_resolutions:
                raise ValueError('阶段包含尚未完整关闭的补丁来源。')
            allowed.add(record.logical_work_id)
    if {record.logical_work_id for record in stage_records.values()}!=allowed:
        raise ValueError('Checkpoint 包含未发生的 Repair 或非授权 Attempt。')
    prior_hash=checkpoint.get('priorStateSha256')
    final_body=json.loads(review_inputs[next(key for key,raw in review_inputs.items()
        if json.loads(raw)['workItems'][0]['payload']['candidateSha256']==candidate_hash)])['workItems'][0]['payload']
    if stage=='SCOPE':
        prior=final_body.get('priorState')
        if (prior is None)!=(prior_hash is None) or (prior is not None and prior_states.get(prior_hash)!=canonical_json_bytes(prior)):
            raise ValueError('Scope Prior state hash 缺失或漂移。')


def candidate_owner_callbacks(envelope, packet, *, inventories=(), revision_bytes=None, semantic_source=None):
    """Bind existing professional validators for live and portable candidate proofs."""
    if semantic_source is not None:
        return _semantic_candidate_callbacks(envelope,packet,semantic_source)
    from contracts import normalize_action_result, InvalidActionResult
    from candidate_repair import schema_issues, diagnostic_report, group_fields, build_repair_plan, issues_from_diagnostics
    import scope_compiler, delivery_compiler, task_compiler, prior_state, prototype_analysis
    contract_id=envelope['actionContractId'];kind=contract_id.rpartition('-v')[0]
    context={'action_contract_id':contract_id}
    if kind.startswith('PRIOR_'):
        owner=prior_state;context.update(inventories=inventories,input_revision_bytes=revision_bytes)
        bound=lambda raw:prior_state.validate_bound_prior_result(kind,packet,raw,inventories=inventories,input_revision_bytes=revision_bytes)
    elif kind in {'SOURCE_SCAN','SOURCE_AUDIT','SCOPE_SYNTHESIS','SCOPE_PROPOSAL','SCOPE_JOIN'}:
        owner=scope_compiler;bound=lambda raw:owner.validate_bound_scope_result(kind,packet,raw)
    elif kind=='STORY_AC':
        owner=delivery_compiler;bound=lambda raw:owner.validate_bound_story_result(packet,raw)
    elif kind=='TASK':
        owner=task_compiler;bound=lambda raw:owner.validate_bound_task_result(packet,raw)
    elif kind in {'PROTOTYPE_SCENARIO','PROTOTYPE_ANALYZE'}:
        owner=prototype_analysis;bound=lambda raw:owner.validate_bound_prototype_result(kind,packet['workItems'][0]['payload'],raw,packet=packet)
    elif kind in {'SOURCE_SCOPE','STORY_DESIGN','TASK_ESTIMATION'}:
        owner=None;bound=lambda raw:validate_bound_review_result(packet,raw)
    else:
        raise InvalidActionResult('该执行责任不接受模型字段补丁。')
    def normalize(raw):
        return normalize_action_result(envelope,raw,skill_root=SKILL_ROOT,packet_payload=canonical_json_bytes(packet))
    def full(raw):bound(normalize(raw))
    def diagnose(raw,origin):
        if owner is not None:return owner.diagnose_candidate(kind,packet,raw,origin=origin,**context)
        value=json.loads(raw);issues=schema_issues(contract_id,value,'REVIEWER');blocked=['REVIEW_OBLIGATIONS'] if issues else []
        if not issues:
            try:bound(canonical_json_bytes(value))
            except InvalidActionResult as error:issues+=issues_from_diagnostics(error.diagnostic.findings or [error.diagnostic],'REVIEWER',value)
        return diagnostic_report(raw,issues,owner='REVIEWER',checker_file=__file__,packet=packet,origin=origin,blocked=blocked,domains=['SCHEMA','REVIEW_OBLIGATIONS'] if not blocked else ['SCHEMA'])
    def plan(raw,report,origin):
        if owner is not None:return owner.plan_candidate_repair(kind,packet,raw,report,origin=origin,**context)
        # Review format repair can only be dispatched from an actual Review
        # envelope; Author results cannot acquire Reviewer authority here.
        groups=group_fields(raw,report,contract_id,{i['issueId']:i['paths'] for i in report['issues']})
        if not groups:raise InvalidActionResult('Review 格式缺口不能安全定位，保留完整义务等待 Reviewer。')
        return build_repair_plan(raw,report,groups,origin=origin)
    return diagnose,plan,full
