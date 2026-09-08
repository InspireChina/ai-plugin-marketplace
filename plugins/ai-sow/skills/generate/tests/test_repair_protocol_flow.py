"""Local issuance/submit/replay seam; never runs Scope materialization or downstream."""
from __future__ import annotations
import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
import pytest
TEST_LAYER='integration'
ROOT=Path(__file__).parents[1]
for directory in (ROOT/'scripts',ROOT/'tests',ROOT.parents[1]):
    if str(directory) not in sys.path:sys.path.insert(0,str(directory))
from test_orchestrator import orchestrator_module as api,write_run_store_request,write_budget_policy
from test_action_ledger import successful_completion
from runtime.project_io import ProjectFiles
from contracts import canonical_json_bytes as encode,sha256_bytes as digest
from action_ledger import effective_result_bytes,resolved_result


def local_failed_work(tmp_path, *, max_action_revisions=4):
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path,maxConcurrency=1,maxActionRevisions=max_action_revisions))['state']
    files=ProjectFiles.open(tmp_path)
    # This seam prepares the skeleton and issues only the first Source Scan.
    # No Author result, materialization, Review, or downstream stage is executed.
    response=api._start_public_pipeline(files,state)
    action=response['nextAction'];assert action['actionContractId']=='SOURCE_SCAN-v1'
    packet=json.loads(files.read_bytes(action['packetPath']))
    from ir_samples import scan_ir
    good=[entry for item in packet['workItems'] for entry in scan_ir(item['payload']['coverageRootId'])]
    good[0]['facts'].append({**copy.deepcopy(good[0]['facts'][0]),'localKey':'second','statement':'保留第二条真实来源内的结果。'})
    bad=copy.deepcopy(good)
    for row in bad[0]['facts']:row['statement']=''
    completion=successful_completion(encode(bad))
    result=api.submit(tmp_path,action['actionId'],completion)
    assert result['outcome']=='RECORDED',result
    assert result['record']['outcome']=='FAILED'
    return files,action,bad,good,completion


def current_action(files):
    marker=api._read_active_marker(files);state=api._recover_active_run(files,marker)
    return api._next_model_action(files,state)


def patch_for(files,action,good,*,bad=False):
    from candidate_repair import patch_context,_at
    view=patch_context(json.loads(files.read_bytes(action['packetPath'])))
    plan=json.loads(files.read_bytes(f".ai-sow/work/runs/{action['runId']}/candidate-repairs/plans/{view['repairPlanSha256']}.json"))
    index={r['objectId']:r for r in plan['objectIndex']}
    operations=[{'slotId':s['slotId'],'value':'' if bad else _at(good,index[s['objectId']]['path'])[s['field']]} for s in view['group']['slots']]
    return json.dumps({'repairPlanSha256':view['repairPlanSha256'],'baseCandidateSha256':view['baseCandidateSha256'],
                       'groupId':view['group']['groupId'],'operations':operations},ensure_ascii=False,indent=2).encode()


def finish_local_work(files,action,good):
    for _ in range(3):
        ledger=api._load_action_ledger(files,action['runId'])
        if effective_result_bytes(ledger,action['logicalWorkId']) is not None:return ledger
        patch=current_action(files);assert patch['actionContractId']=='CANDIDATE_PATCH-v1'
        result=api.submit(files.root,patch['actionId'],successful_completion(patch_for(files,patch,good)))
        assert result['outcome']=='RECORDED',result
    raise AssertionError('局部工作未在固定补丁数内关闭。')


def test_patch_resolution_does_not_rewrite_author_failure(tmp_path):
    files,author,bad,good,completion=local_failed_work(tmp_path)
    path=f".ai-sow/work/runs/{author['runId']}/actions/{author['actionId']}/record.json"
    before=files.read_bytes(path);raw_before=files.read_bytes(path.replace('record.json','raw-output.bin'))
    ledger=finish_local_work(files,author,good)
    assert json.loads(before)['outcome']=='FAILED' and files.read_bytes(path)==before
    assert files.read_bytes(path.replace('record.json','raw-output.bin'))==raw_before
    result=resolved_result(ledger,author['logicalWorkId'],verify_resolution=lambda proof:ledger.resolved_candidates[digest(proof)])
    assert json.loads(result)==good
    assert sum(r.usage.charged_tokens for r in ledger.attempt_records.values())==14*len(ledger.attempt_records)




def test_repair_adoption_keeps_budget_and_issued_actions(tmp_path):
    files,author,bad,good,_=local_failed_work(tmp_path)
    envelope_bytes=files.read_bytes(api._action_paths(author['runId'],author['actionId'])['envelope'])
    policy=api._effective_budget_policy(files,author['runId'])
    patch=current_action(files)
    assert patch['logicalWorkId']!=author['logicalWorkId'] and patch['revision']==1
    assert patch['actionContractId']=='CANDIDATE_PATCH-v1'
    finish_local_work(files,author,good)
    assert files.read_bytes(api._action_paths(author['runId'],author['actionId'])['envelope'])==envelope_bytes
    assert api._effective_budget_policy(files,author['runId'])==policy


def test_patch_request_omits_protected_collections(tmp_path):
    files,author,bad,good,_=local_failed_work(tmp_path)
    patch=current_action(files);packet=files.read_bytes(patch['packetPath'])
    assert b'rawOutputUtf8' not in packet and b'preservationBase' not in packet
    assert b'objectIndex' not in packet and b'protectedSha256' not in packet
    assert b'"facts"' not in packet
    request=api.read_provider_request(tmp_path,patch['actionId'])
    assert b'rawOutputUtf8' not in request


def local_portable_proof(files,author):
    from package_renderer import encode_binary
    from candidate_repair import patch_context
    ledger=api._load_action_ledger(files,author['runId']);actions=[];plans={}
    for env in ledger.envelopes_by_sha256.values():
        value=env.value;paths=api._action_paths(author['runId'],value['actionId'])
        record=files.read_json(paths['record']);packet=files.read_json(paths['packet'])
        actions.append({'envelope':dict(value),'packet':packet,'record':record,
            'raw':encode_binary(files.read_bytes(paths['raw'])) if record['rawSha256'] else None,
            'normalized':encode_binary(files.read_bytes(paths['normalized'])) if record['normalizedResultSha256'] else None})
        if value['actionContractId']=='CANDIDATE_PATCH-v1':
            h=patch_context(packet)['repairPlanSha256'];plans[h]=files.read_json(f".ai-sow/work/runs/{author['runId']}/candidate-repairs/plans/{h}.json")
    return {'actions':actions,'candidateRepairPlans':plans,
            'candidateResolutions':{key:json.loads(raw) for key,raw in ledger.candidate_resolutions.items()},
            'inputRevision':files.read_json(api._read_active_marker(files)['inputRevisionPath']),
            'events':[api.run_event_value(e) for e in api._read_run_events(files,author['runId'])]}


@pytest.mark.parametrize('target',['plan','patch','receipt','author','record','missing',
    'selection','index','resolution'])
def test_resolution_proof_rejects_tampering(tmp_path,target):
    from generation_store import _proof_ledger
    files,author,bad,good,_=local_failed_work(tmp_path);finish_local_work(files,author,good)
    proof=local_portable_proof(files,author)
    ledger,_=_proof_ledger(proof)
    assert json.loads(effective_result_bytes(ledger,author['logicalWorkId']))==good
    changed=copy.deepcopy(proof);patch=next(a for a in changed['actions'] if a['envelope']['actionContractId']=='CANDIDATE_PATCH-v1')
    author_action=next(a for a in changed['actions'] if a['envelope']['actionId']==author['actionId'])
    if target=='plan':next(iter(changed['candidateRepairPlans'].values()))['groups'][0]['slots'][0]['field']='qualifiers'
    elif target=='patch':patch['raw']=author_action['raw']
    elif target=='receipt':patch['normalized']=author_action['raw']
    elif target=='author':next(a for a in changed['actions'] if a['envelope']['actionId']==author['actionId'])['raw']=patch['raw']
    elif target=='record':patch['record']['usage']['inputTokens']+=1
    elif target=='selection':
        next(event for event in changed['events'] if event['type']=='CANDIDATE_REPAIR_PROTOCOL_SELECTED'
             )['payload']['candidateRepairSchemaSha256']='0'*64
    elif target=='index':
        from package_renderer import decode_binary,encode_binary
        value=json.loads(decode_binary(patch['normalized']));value['objectIndex'][0]['sha256']='0'*64
        patch['normalized']=encode_binary(encode(value))
    elif target=='resolution':
        next(iter(changed['candidateResolutions'].values()))['ownerIrSha256']='0'*64
    else:changed['actions'].remove(patch)
    roots={key:digest(raw) for key,raw in ledger.candidate_resolutions.items()}
    with pytest.raises((ValueError,KeyError)):_proof_ledger(changed,expected_resolutions=roots)


def plan_for_action(files,action):
    from candidate_repair import patch_context
    view=patch_context(json.loads(files.read_bytes(action['packetPath'])))
    return json.loads(files.read_bytes(
        f".ai-sow/work/runs/{action['runId']}/candidate-repairs/plans/{view['repairPlanSha256']}.json"))




def test_source_scan_missing_disposition_repairs_conditional_fields_atomically(tmp_path):
    files,author,_,good,_=local_failed_work(tmp_path)
    candidate=copy.deepcopy(good)
    index=next(i for i,row in enumerate(candidate) if row['facts'])
    candidate[index].pop('disposition')
    candidate[index].pop('noRelevantReason',None)
    raw=encode(candidate)
    packet=json.loads(files.read_bytes(author['packetPath']))
    origin={
        'runId':author['runId'],
        'inputRevisionSha256':author['inputRevisionSha256'],
        'originLogicalWorkId':author['logicalWorkId'],
        'sourceKind':'AUTHOR_FAILURE',
        'sourceActionContractId':'SOURCE_SCAN-v1',
        'sourceAttemptRecordSha256':'1'*64,
        'stageKind':'SCOPE',
        'repairRound':2,
        'budgetPolicySha256':author['budgetPolicySha256'],
    }
    from scope_compiler import diagnose_candidate,plan_candidate_repair
    from candidate_repair import apply_repair_patch,verify_group_progress
    report=diagnose_candidate(
        'SOURCE_SCAN',packet,raw,origin=origin,
        action_contract_id='SOURCE_SCAN-v1')
    plan_raw=plan_candidate_repair(
        'SOURCE_SCAN',packet,raw,report,origin=origin,
        action_contract_id='SOURCE_SCAN-v1')
    plan=json.loads(plan_raw)
    group=next(group for group in plan['groups']
        if any(issue['paths']==[f'/{index}/disposition']
               for issue in report['issues'] if issue['issueId'] in group['issueIds']))
    assert len(group['slots'])==1
    slot=group['slots'][0]
    assert slot['operation']=='SET_FIELDS'
    assert slot['fields']==['disposition','facts','noRelevantReason']
    reason='标题不包含可执行需求、约束或假设。'
    patch=encode({
        'repairPlanSha256':digest(plan_raw),
        'baseCandidateSha256':digest(raw),
        'groupId':group['groupId'],
        'operations':[{'slotId':slot['slotId'],'value':{
            'disposition':'NO_RELEVANT_FACT',
            'facts':[],
            'noRelevantReason':reason}}]})
    def verify(merged,current_group):
        updated=diagnose_candidate(
            'SOURCE_SCAN',packet,merged,origin=origin,
            action_contract_id='SOURCE_SCAN-v1')
        verify_group_progress(report,updated,current_group)
    merged,_=apply_repair_patch(
        raw,plan_raw,patch,group_id=group['groupId'],verify_group=verify)
    assert json.loads(merged)[index]=={
        'coverageRootId':candidate[index]['coverageRootId'],
        'disposition':'NO_RELEVANT_FACT',
        'facts':[],
        'noRelevantReason':reason}


def test_source_scan_batches_disjoint_schema_repairs_into_one_patch(tmp_path):
    files,author,_,good,_=local_failed_work(tmp_path)
    assert len(good)>=2
    candidate=copy.deepcopy(good)
    candidate[0].update(facts=[],reason='标题未陈述可交付事实。',decision='NO_RELEVANT_FACT')
    candidate[1].update(facts=[],reason='审批状态未陈述可交付事实。',decision='NO_RELEVANT_FACT')
    raw=encode(candidate)
    packet=json.loads(files.read_bytes(author['packetPath']))
    origin={
        'runId':author['runId'],
        'inputRevisionSha256':author['inputRevisionSha256'],
        'originLogicalWorkId':author['logicalWorkId'],
        'sourceKind':'AUTHOR_FAILURE',
        'sourceActionContractId':'SOURCE_SCAN-v1',
        'sourceAttemptRecordSha256':'1'*64,
        'stageKind':'SCOPE',
        'repairRound':2,
        'budgetPolicySha256':author['budgetPolicySha256'],
    }
    from scope_compiler import diagnose_candidate,plan_candidate_repair
    from candidate_repair import apply_repair_patch,verify_group_progress
    report=diagnose_candidate(
        'SOURCE_SCAN',packet,raw,origin=origin,
        action_contract_id='SOURCE_SCAN-v1')
    plan_raw=plan_candidate_repair(
        'SOURCE_SCAN',packet,raw,report,origin=origin,
        action_contract_id='SOURCE_SCAN-v1')
    plan=json.loads(plan_raw)
    assert len(report['issues'])==6
    assert len(plan['groups'])==1
    group=plan['groups'][0]
    assert len(group['slots'])==6
    assert {slot['operation'] for slot in group['slots']}=={'SET_FIELDS','REMOVE_FIELD'}
    patch=encode({
        'repairPlanSha256':digest(plan_raw),
        'baseCandidateSha256':digest(raw),
        'groupId':group['groupId'],
        'operations':[{'slotId':slot['slotId'],**(
            {'value':slot['valueSchema']['const']}
            if slot['operation']=='SET_FIELDS' else {})}
            for slot in group['slots']]})
    def verify(merged,current_group):
        updated=diagnose_candidate(
            'SOURCE_SCAN',packet,merged,origin=origin,
            action_contract_id='SOURCE_SCAN-v1')
        verify_group_progress(report,updated,current_group)
    merged,_=apply_repair_patch(
        raw,plan_raw,patch,group_id=group['groupId'],verify_group=verify)
    for row in json.loads(merged)[:2]:
        assert 'reason' not in row and 'decision' not in row
        assert row['disposition']=='NO_RELEVANT_FACT'
        assert row['facts']==[] and row['noRelevantReason']


def test_failed_patch_revision_resumes_the_patch_leaf_repeatedly(tmp_path):
    files,author,_,good,_=local_failed_work(tmp_path,max_action_revisions=2)
    patch=current_action(files)
    assert patch['actionContractId']=='CANDIDATE_PATCH-v1' and patch['revision']==1
    from candidate_repair import patch_context
    view=patch_context(json.loads(files.read_bytes(patch['packetPath'])))
    invalid=successful_completion(encode({
        'repairPlanSha256':view['repairPlanSha256'],
        'baseCandidateSha256':view['baseCandidateSha256'],
        'groupId':view['group']['groupId'],
        'operations':[],
        'diagnostics':[{'code':'SEMANTIC_EVIDENCE_INSUFFICIENT'}]}))
    assert api.submit(tmp_path,patch['actionId'],invalid)['record']['failureKind']=='INVALID_IR'
    assert api.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'

    third_result=api.run_mode(
        tmp_path,'resume',
        budget_policy=write_budget_policy(
            tmp_path,maxConcurrency=1,maxActionRevisions=3))
    assert third_result['outcome']=='ACTIVE',third_result
    third=third_result['nextAction']
    assert third['actionContractId']=='CANDIDATE_PATCH-v1'
    assert plan_for_action(files,third)['origin']['repairRound']==3
    assert api.submit(
        tmp_path,third['actionId'],
        successful_completion(patch_for(files,third,good,bad=True)))['record']['failureKind']=='INVALID_IR'
    paused=api.run_mode(tmp_path,'resume')
    assert paused['outcome']=='WAITING_INPUT',paused
    events=api._read_run_events(files,author['runId'])
    latest_wait=next(event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED')
    assert not any(event.type=='WAITING_INPUT_EXITED'
        and event.payload['waitId']==latest_wait.payload['waitId'] for event in events)

    fourth_result=api.run_mode(
        tmp_path,'resume',
        budget_policy=write_budget_policy(
            tmp_path,maxConcurrency=1,maxActionRevisions=4))
    assert fourth_result['outcome']=='ACTIVE',fourth_result
    fourth=fourth_result['nextAction']
    assert fourth['actionContractId']=='CANDIDATE_PATCH-v1'
    assert plan_for_action(files,fourth)['origin']['repairRound']==4
    assert fourth['actionId'] not in {
        patch['actionId'],third['actionId'],author['actionId']}
    selections=[
        event for event in api._read_run_events(files,author['runId'])
        if event.type=='CANDIDATE_REPAIR_PROTOCOL_SELECTED']
    assert len(selections)==1
    assert selections[0].payload['repairRound']==2

def test_equivalent_ineffective_patch_stops_without_budget_exhaustion(tmp_path):
    files,author,_,good,_=local_failed_work(tmp_path)
    first=current_action(files);bad_patch=patch_for(files,first,good,bad=True)
    response=api.submit(tmp_path,first['actionId'],successful_completion(bad_patch))
    assert response['outcome']=='RECORDED',response
    second=current_action(files)
    assert api.submit(tmp_path,second['actionId'],successful_completion(patch_for(files,second,good,bad=True)))['outcome']=='RECORDED'
    marker=api._read_active_marker(files);state=api._recover_active_run(files,marker)
    assert state['wait']=='INPUT'
    entered=[event for event in api._read_run_events(files,author['runId']) if event.type=='WAITING_INPUT_ENTERED']
    assert entered[-1].payload['reasonCode']=='CANDIDATE_REPAIR_NO_PROGRESS'


def test_input_contract_and_budget_stops_remain_distinct(tmp_path):
    from ir_samples import scan_ir
    from models import AttemptDiagnostic
    input_root=tmp_path/'input';input_root.mkdir()
    state=api.start(input_root,write_run_store_request(input_root),write_budget_policy(input_root,maxConcurrency=1))['state']
    files=ProjectFiles.open(input_root);action=api._start_public_pipeline(files,state)['nextAction']
    completion=replace(successful_completion(),raw_output=None,failure_kind='INPUT_REQUIRED',
        diagnostic=AttemptDiagnostic('REAL_SOURCE_REQUIRED','',()))
    assert api.submit(input_root,action['actionId'],completion)['outcome']=='RECORDED'
    assert api._recover_active_run(files,api._read_active_marker(files))['wait']=='INPUT'

    contract_root=tmp_path/'contract';contract_root.mkdir()
    state=api.start(contract_root,write_run_store_request(contract_root),write_budget_policy(contract_root,maxConcurrency=1))['state']
    files=ProjectFiles.open(contract_root);action=api._start_public_pipeline(files,state)['nextAction']
    packet=json.loads(files.read_bytes(action['packetPath']))
    bad=[entry for item in packet['workItems'] for entry in scan_ir(item['payload']['coverageRootId'])]
    bad={'unsupportedRootShape':True}
    assert api.submit(contract_root,action['actionId'],successful_completion(encode(bad)))['outcome']=='RECORDED'
    contract_state=api._recover_active_run(files,api._read_active_marker(files))
    assert contract_state['phase']=='DONE' and contract_state['result']=='CONTRACT_UNSUPPORTED'

    budget_root=tmp_path/'budget';budget_root.mkdir()
    state=api.start(budget_root,write_run_store_request(budget_root),
        write_budget_policy(budget_root,maxConcurrency=1,maxActionRevisions=2))['state']
    files=ProjectFiles.open(budget_root);action=api._start_public_pipeline(files,state)['nextAction']
    packet=json.loads(files.read_bytes(action['packetPath']))
    bad=[entry for item in packet['workItems'] for entry in scan_ir(item['payload']['coverageRootId'])]
    bad[0]['facts'][0]['statement']=''
    assert api.submit(budget_root,action['actionId'],successful_completion(encode(bad)))['outcome']=='RECORDED'
    first_patch=current_action(files)
    assert api.submit(budget_root,first_patch['actionId'],
        successful_completion(patch_for(files,first_patch,bad,bad=True)))['outcome']=='RECORDED'
    assert [event for event in api._read_run_events(files,action['runId'])
            if event.type=='WAITING_INPUT_ENTERED'][-1].payload['reasonCode']=='BUDGET_EXHAUSTED'


@pytest.mark.parametrize('interruption',['raw','receipt','record','state-pointer'])
def test_candidate_repair_transaction_recovery(tmp_path,monkeypatch,interruption):
    files,author,_,good,_=local_failed_work(tmp_path)
    patch=current_action(files);payload=patch_for(files,patch,good)
    paths=api._action_paths(author['runId'],patch['actionId'])
    original_publish=ProjectFiles.publish_new
    original_recover=api._recover_active_run
    fired=False
    if interruption!='state-pointer':
        target=paths['normalized' if interruption=='receipt' else interruption]
        def interrupted_publish(self,path,content):
            nonlocal fired
            result=original_publish(self,path,content)
            if path==target and not fired:
                fired=True
                raise RuntimeError('injected publication interruption')
            return result
        monkeypatch.setattr(ProjectFiles,'publish_new',interrupted_publish)
    else:
        def interrupted_recover(*args,**kwargs):
            nonlocal fired
            if not fired:
                fired=True
                raise RuntimeError('injected state pointer interruption')
            return original_recover(*args,**kwargs)
        monkeypatch.setattr(api,'_recover_active_run',interrupted_recover)
    with pytest.raises(RuntimeError):
        api.submit(tmp_path,patch['actionId'],successful_completion(payload))
    monkeypatch.setattr(ProjectFiles,'publish_new',original_publish)
    monkeypatch.setattr(api,'_recover_active_run',original_recover)
    assert api.submit(tmp_path,patch['actionId'],successful_completion(payload))['outcome']=='RECORDED'
    matching_issued=[event for event in api._read_run_events(files,author['runId'])
                     if event.type=='ACTION_ISSUED' and event.payload['logicalWorkId']==patch['logicalWorkId']]
    assert len(matching_issued)==1
    records=[record for record in api._load_action_ledger(files,author['runId']).attempt_records.values()
             if record.logical_work_id==patch['logicalWorkId']]
    assert len(records)==1


def test_semantic_review_issues_candidate_patch_and_requires_fresh_review():
    from action_ledger import ActionLedger,attempt_record_value
    from candidate_repair import apply_repair_patch,replay_candidate_ledger
    from contracts import InvalidActionResult
    from final_review import (candidate_repair_replacement,control_identity,
        semantic_repair_lineage)
    from owner_callbacks import candidate_owner_callbacks
    from ir_samples import complete_scope_ir
    from models import ActionEnvelope,AttemptRecord,AttemptTiming,RunEvent,Usage
    from test_scope_compiler import synthesis_packet
    owner_packet=synthesis_packet();original=complete_scope_ir();owner_raw=encode(original)
    key='feature-a';review_candidate='5'*64
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'BOUNDARY',
        'path':'/features/0','subjectIds':[key],'evidenceIds':[],'message':'名称应明确交付结果。'}]}
    review_raw=encode(review);review_packet=encode({'workItems':[{'workItemId':'review','payload':{
        'candidateSha256':review_candidate,'ownerIndex':{key:{'id':'feature-id','path':'/features/0'}}}}],
        'contextRefs':[]})
    _,review_contract_sha=__import__('contracts').action_contract_binding(ROOT,'SOURCE_SCOPE-v1')
    review_envelope_value={'runId':'run-semantic','stageKind':'SCOPE','inputRevisionSha256':'1'*64,
        'baseCandidateSha256':review_candidate,'upstreamCheckpointSha256s':[],
        'budgetPolicySha256':'2'*64,'actionContractId':'SOURCE_SCOPE-v1','actionContractSha256':review_contract_sha,
        'logicalWorkId':'review-logical','groupId':'review-group','actionId':'review-action','revision':1,'attempt':1,
        'packetSha256':digest(review_packet)}
    review_envelope_raw=encode(review_envelope_value);review_envelope_sha=digest(review_envelope_raw)
    usage=Usage('PROVIDER_REPORTED',10,4,3,1);timing=AttemptTiming('2026-09-07T00:00:00Z','2026-09-07T00:00:01Z')
    review_record=AttemptRecord('review-logical',1,1,review_envelope_sha,'SUCCEEDED',None,None,
        digest(review_raw),digest(review_raw),usage,timing)
    review_record_sha=digest(encode(attempt_record_value(review_record)))
    _,patch_contract_sha=__import__('contracts').action_contract_binding(ROOT,'CANDIDATE_PATCH-v1')
    lineage=semantic_repair_lineage('SCOPE',digest(review_raw),patch_contract_sha)
    descriptor={'stageKind':'SCOPE','ownerPacket':owner_packet,'ownerIRSha256':digest(owner_raw),
        'ownerActionContractId':'SCOPE_SYNTHESIS-v1','ownerIndex':{key:{'id':'feature-id','path':'/features/0'}},
        'reviewDecision':review,'reviewDecisionSha256':digest(review_raw),
        'reviewAttemptRecordSha256':review_record_sha,'reviewCandidateSha256':review_candidate}
    descriptor_raw=encode(descriptor);semantic_sha=digest(descriptor_raw)
    origin={'runId':'run-semantic','inputRevisionSha256':'1'*64,'originLogicalWorkId':lineage,
        'sourceKind':'SEMANTIC_REVIEW','sourceActionContractId':'SOURCE_SCOPE-v1',
        'sourceAttemptRecordSha256':review_record_sha,'stageKind':'SCOPE','repairRound':2,
        'budgetPolicySha256':'2'*64,'reviewDecisionSha256':digest(review_raw),
        'reviewCandidateSha256':review_candidate,'semanticSourceSha256':semantic_sha}
    callbacks=candidate_owner_callbacks(review_envelope_value,json.loads(review_packet),semantic_source=descriptor)
    report=callbacks[0](owner_raw,origin);plan_raw=callbacks[1](owner_raw,report,origin);plan=json.loads(plan_raw)
    group=plan['groups'][0];slot=group['slots'][0]
    repaired_row=copy.deepcopy(original['decisions'][0])
    repaired_row['localKey']=key+':repair:clear';repaired_row['boundaryEvidence']['name']='已明确的订单查询能力'
    patch=encode({'repairPlanSha256':digest(plan_raw),'baseCandidateSha256':digest(owner_raw),
        'groupId':group['groupId'],'operations':[{'slotId':slot['slotId'],'value':[repaired_row]}]})
    merged,receipt=apply_repair_patch(owner_raw,plan_raw,patch,group_id=group['groupId'],
        verify_group=lambda raw,current:callbacks[0](raw,origin)['issues'] and
            (_ for _ in ()).throw(ValueError('semantic mechanical validation failed')))
    patch_packet=encode(api._patch_request_packet(plan_raw,group['groupId'],json.loads(review_packet),
        evidence_values=[{'kind':'SEMANTIC_REVIEW_FINDINGS','value':review['findings']}]))
    patch_envelope_value={**review_envelope_value,'actionContractId':'CANDIDATE_PATCH-v1',
        'actionContractSha256':patch_contract_sha,'logicalWorkId':'candidate-patch-logical',
        'groupId':'patch-group','actionId':'patch-action','packetSha256':digest(patch_packet)}
    patch_envelope_raw=encode(patch_envelope_value);patch_envelope_sha=digest(patch_envelope_raw)
    patch_record=AttemptRecord('candidate-patch-logical',1,1,patch_envelope_sha,'SUCCEEDED',None,None,
        digest(patch),digest(receipt),usage,timing)
    patch_record_sha=digest(encode(attempt_record_value(patch_record)))
    ledger=ActionLedger(
        envelopes_by_sha256={review_envelope_sha:ActionEnvelope(review_envelope_value,'review.json',review_envelope_sha),
            patch_envelope_sha:ActionEnvelope(patch_envelope_value,'patch.json',patch_envelope_sha)},
        attempt_records={review_record_sha:review_record,patch_record_sha:patch_record},
        raw_outputs={digest(review_raw):review_raw,digest(patch):patch},
        normalized_results={digest(review_raw):review_raw,digest(receipt):receipt})
    schema_sha=digest((ROOT/'contracts/candidate-repair.schema.json').read_bytes())
    events=[RunEvent('run-semantic',1,'ACTION_ISSUED','2026-09-07T00:00:00Z',
                {'actionId':'review-action','logicalWorkId':'review-logical','envelopeSha256':review_envelope_sha}),
        RunEvent('run-semantic',2,'CANDIDATE_REPAIR_PROTOCOL_SELECTED','2026-09-07T00:00:01Z',
            {'originLogicalWorkId':lineage,'sourceAttemptRecordSha256':review_record_sha,
             'sourceActionContractId':'SOURCE_SCOPE-v1','selectionKind':'SEMANTIC_REVIEW','repairRound':2,
             'candidatePatchActionContractSha256':patch_contract_sha,'candidateRepairSchemaSha256':schema_sha}),
        RunEvent('run-semantic',3,'ACTION_ISSUED','2026-09-07T00:00:02Z',
            {'actionId':'patch-action','logicalWorkId':'candidate-patch-logical','envelopeSha256':patch_envelope_sha})]
    replayed=replay_candidate_ledger(ledger,{digest(review_packet):review_packet,digest(patch_packet):patch_packet},
        {digest(plan_raw):plan_raw},owner_callbacks=lambda e,p,semantic_source=None:
            candidate_owner_callbacks(e,p,semantic_source=semantic_source),events=events,
        bases={digest(owner_raw):owner_raw},semantic_sources={semantic_sha:descriptor_raw})
    assert json.loads(effective_result_bytes(replayed,lineage))==json.loads(merged)
    replacement=candidate_repair_replacement('SCOPE',original,json.loads(merged),review)
    assert replacement['decisions'][0]['localKey'].startswith(key+':repair:')
    _,review_contract_sha=__import__('contracts').action_contract_binding(ROOT,'SOURCE_SCOPE-v1')
    fresh_logical,_=control_identity('SCOPE','REVIEW',digest(merged),review_contract_sha)
    assert fresh_logical!='review-logical'


    replay_args=({digest(review_packet):review_packet,digest(patch_packet):patch_packet},
        {digest(plan_raw):plan_raw})
    with pytest.raises(InvalidActionResult):
        replay_candidate_ledger(ledger,*replay_args,owner_callbacks=lambda e,p,semantic_source=None:
            candidate_owner_callbacks(e,p,semantic_source=semantic_source),events=events,
            bases={digest(owner_raw):encode({'forged':True})},semantic_sources={semantic_sha:descriptor_raw})
    forged_descriptor=copy.deepcopy(descriptor);forged_descriptor['reviewCandidateSha256']='0'*64
    with pytest.raises(InvalidActionResult):
        replay_candidate_ledger(ledger,*replay_args,owner_callbacks=lambda e,p,semantic_source=None:
            candidate_owner_callbacks(e,p,semantic_source=semantic_source),events=events,
            bases={digest(owner_raw):owner_raw},semantic_sources={semantic_sha:encode(forged_descriptor)})
    forged_events=copy.deepcopy(events)
    forged_events[1]=replace(forged_events[1],payload={**forged_events[1].payload,
        'candidateRepairSchemaSha256':'0'*64})
    with pytest.raises(InvalidActionResult):
        replay_candidate_ledger(ledger,*replay_args,owner_callbacks=lambda e,p,semantic_source=None:
            candidate_owner_callbacks(e,p,semantic_source=semantic_source),events=forged_events,
            bases={digest(owner_raw):owner_raw},semantic_sources={semantic_sha:descriptor_raw})


def test_review_format_repair_cannot_supply_author_pass():
    from contracts import InvalidActionResult
    from owner_callbacks import candidate_owner_callbacks
    from test_candidate_repair_protocol import field_case
    reviewer_envelope={'actionContractId':'SOURCE_SCOPE-v1'}
    reviewer_packet={'workItems':[],'contextRefs':[]}
    _,_,_,origin=field_case()
    origin={**origin,'sourceActionContractId':'SOURCE_SCOPE-v1'}
    candidate=encode({'findings':[]})
    diagnose,plan,_=candidate_owner_callbacks(reviewer_envelope,reviewer_packet)
    report=diagnose(candidate,origin);repair_plan=json.loads(plan(candidate,report,origin))
    assert report['owner']=='REVIEWER'
    assert {slot.get('field') for group in repair_plan['groups'] for slot in group['slots']}=={'decision','findings'}
    from scope_compiler import diagnose_candidate,plan_candidate_repair
    from test_scope_compiler import scan_ir_packet
    author_packet=scan_ir_packet();author_origin={**origin,'sourceActionContractId':'SOURCE_SCAN-v1'}
    author_candidate=encode({'decision':'PASS'})
    author_report=diagnose_candidate('SOURCE_SCAN',author_packet,author_candidate,origin=author_origin)
    with pytest.raises(InvalidActionResult):
        plan_candidate_repair('SOURCE_SCAN',author_packet,author_candidate,author_report,origin=author_origin)
