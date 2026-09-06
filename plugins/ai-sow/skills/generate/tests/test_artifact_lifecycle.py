"""Real artifact producers and publication proof closure."""
import json
import sys
from pathlib import Path
import pytest

TEST_LAYER = 'e2e'
ROOT = Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts')); sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT.parents[1]))
from contracts import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles
import generation_store
import orchestrator


@pytest.fixture(scope='session')
def verified_artifact(tmp_path_factory):
    from test_e2e import drive_fixture_host
    project = tmp_path_factory.mktemp('verified-artifact')
    result, trace = drive_fixture_host(project)
    assert result['outcome'] == 'REQUEST_APPROVAL', result
    return project, result, trace


def test_artifact_manifest_deep_binding_and_promotion_gate(verified_artifact):
    project, result, trace = verified_artifact
    files = ProjectFiles.open(project)
    assert callable(getattr(generation_store,'validate_artifact_manifest',None)), 'deep manifest validator missing'
    path = result['artifactManifestPath']; digest = result['artifactManifestSha256']
    manifest = generation_store.validate_artifact_manifest(files,path,digest)
    assert not (project/'.ai-sow/current.json').exists()
    root = str(Path(path).parent)
    targets = ['sow-model.json','sow-template.xlsx','proof-bundle.json','verification.json','sow.xlsx',manifest['renders'][0]['path']]
    for target in targets:
        local = project/root/target; original = local.read_bytes()
        try:
            local.write_bytes(original+b'corruption')
            with pytest.raises(ValueError): generation_store.validate_artifact_manifest(files,path,digest)
            assert not (project/'.ai-sow/current.json').exists()
        finally: local.write_bytes(original)
    for field in ('candidateSha256','stageCheckpointSha256s','priorStateSha256','templateSha256','rendererSha256',
                  'office','workbookVerification','structureFormulaSha256','renders','visualReview','workbook'):
        bad = json.loads(canonical_json_bytes(manifest))
        if field == 'stageCheckpointSha256s': bad[field][0] = '0'*64
        elif field == 'renders': bad[field][0]['sha256'] = '0'*64
        elif field == 'visualReview': bad[field]['attemptRecordSha256'] = '0'*64
        elif field == 'workbook': bad[field]['sha256'] = '0'*64
        elif field == 'office': bad[field]['exitCode'] = 1
        elif field == 'workbookVerification': bad[field]['engineVersion'] = 'LibreOffice 0.0 forged'
        else: bad[field] = '0'*64
        original = files.read_bytes(path)
        try:
            (project/path).write_bytes(canonical_json_bytes(bad))
            with pytest.raises(ValueError): generation_store.validate_artifact_manifest(files,path,sha256_bytes(canonical_json_bytes(bad)))
        finally: (project/path).write_bytes(original)


def test_visible_sheet_review_packet_and_attempt_binding(verified_artifact):
    project,result,trace = verified_artifact; files = ProjectFiles.open(project)
    manifest = files.read_json(result['artifactManifestPath'])
    proof = files.read_json(str(Path(result['artifactManifestPath']).parent/'proof-bundle.json'))
    visual = [a for a in proof['actions'] if a['envelope']['actionContractId']=='ARTIFACT_VISUAL_REVIEW-v1']
    assert len(visual) == 1
    action = visual[0]
    assert action['envelope']['revision'] == 1 and action['envelope']['stageKind'] == 'ARTIFACT'
    assert sha256_bytes(canonical_json_bytes(action['record'])) == manifest['visualReview']['attemptRecordSha256']
    body = action['packet']['workItems'][0]['payload']
    assert body['visibleSheets'] == manifest['visibleSheets']
    assert body['identity']['orderedRenderSha256s'] == [r['sha256'] for r in manifest['renders']]
    assert body['identity']['workbookSha256'] == manifest['workbook']['sha256']


def test_render_only_repair_reuses_verified_workbook_and_keeps_failed_visual_proof(tmp_path,monkeypatch):
    from test_e2e import drive_fixture_host
    from test_orchestrator import submit_prototype,prototype_payload,write_json
    from stage_driver import stage_result
    import package_renderer
    with monkeypatch.context() as setup:
        setup.setattr(orchestrator,'_advance_artifact',lambda files,state:{'outcome':'ARTIFACT_READY','state':state,'nextAction':None})
        ready,_=drive_fixture_host(tmp_path,terminal_outcomes=('ARTIFACT_READY',))
    with monkeypatch.context() as legacy:
        legacy.setattr(package_renderer,'office_page_viewports',lambda page:[page])
        first=orchestrator.run_mode(tmp_path,'resume')
    assert first['outcome']=='ACTIVE',first
    action=first['nextAction'];body=prototype_payload(tmp_path,action)
    packet=json.loads((tmp_path/action['packetPath']).read_bytes())
    failed=stage_result('ARTIFACT_VISUAL_REVIEW',packet)
    failed['sheets'][-1]['checks']['readability']='FAIL';failed['sheets'][-1]['decision']='FAIL'
    failed['sheets'][-1]['findings']=['长宽表单页预览不可读。'];failed['overallDecision']='FAIL'
    record=submit_prototype(tmp_path,action,failed)['record']
    stopped=orchestrator.run_mode(tmp_path,'resume');assert stopped['outcome']=='MANUAL_REVIEW_REQUIRED'
    root=tmp_path/'.ai-sow/work/runs'/action['runId']
    frozen={p:p.read_bytes() for directory in ('stages','artifact-steps','artifacts','actions') for p in (root/directory).rglob('*') if p.is_file()}
    answer={'contract':'ai-sow-artifact-repair-authorization-v1','runId':action['runId'],
        'terminalStateSha256':sha256_bytes(canonical_json_bytes(stopped['state'])),'candidateSha256':stopped['state']['currentCandidateSha256'],
        'visualReviewAttemptRecordSha256':sha256_bytes(canonical_json_bytes(record)),'rendererSha256':orchestrator._renderer_sha256(),
        'repairFromStep':'RENDER','decision':'仅重建可读预览并重新视觉验收，复用已验证 Excel。',
        'provenance':'SIMULATED_USER','authorization':'用户授权修复已生成结果。'}
    write_json(tmp_path/'render-repair.json',answer)
    def prefix_forbidden(*args,**kwargs): raise AssertionError('already verified artifact prefix was regenerated')
    with monkeypatch.context() as guard:
        for name in ('project_artifact','calculate_artifact','verify_artifact'): guard.setattr(package_renderer,name,prefix_forbidden)
        repaired=orchestrator.run_mode(tmp_path,'resume',decision='render-repair.json')
        assert repaired['outcome']=='ACTIVE',repaired
        new=repaired['nextAction'];new_body=prototype_payload(tmp_path,new)
        assert new['actionId']!=action['actionId'] and new_body['workbook']['sha256']==body['workbook']['sha256']
        assert orchestrator.run_mode(tmp_path,'resume',decision='render-repair.json')['nextAction']['actionId']==new['actionId']
        assert all(p.read_bytes()==raw for p,raw in frozen.items())
        passed=stage_result('ARTIFACT_VISUAL_REVIEW',json.loads((tmp_path/new['packetPath']).read_bytes()))
        submit_prototype(tmp_path,new,passed)
        final=orchestrator.run_mode(tmp_path,'resume');assert final['outcome']=='REQUEST_APPROVAL',final
    manifest=generation_store.validate_artifact_manifest(ProjectFiles.open(tmp_path),final['artifactManifestPath'],final['artifactManifestSha256'])
    assert manifest['workbook']['sha256']==body['workbook']['sha256']
    proof=json.loads((tmp_path/Path(final['artifactManifestPath']).parent/'proof-bundle.json').read_bytes())
    assert proof['artifactRevision']==2 and proof['artifactStepRevisions']['OFFICE']==1 and proof['artifactStepRevisions']['RENDER']==2
    assert len([a for a in proof['actions'] if a['envelope']['actionContractId']=='ARTIFACT_VISUAL_REVIEW-v1'])==2
    files=ProjectFiles.open(tmp_path)
    revision_path=f".ai-sow/inputs/revisions/{proof['inputRevision']['revisionId']}/manifest.json"
    collected=generation_store.collect_artifact_proof(files,{'runId':action['runId']},revision_path)
    assert collected==proof
    assert generation_store.collect_artifact_proof(files,
        {'runId':action['runId'],'currentCandidateSha256':'0'*64},revision_path)==proof
    model=json.loads((tmp_path/Path(final['artifactManifestPath']).parent/'sow-model.json').read_bytes())
    for target in ('prefix-revision','missing-stop','missing-authorization','revision-reset'):
        bad=json.loads(canonical_json_bytes(proof))
        key=next(iter(bad['artifactRepairAuthorizations']))
        if target=='prefix-revision': bad['artifactStepRevisions']['OFFICE']=2
        elif target=='missing-stop': bad['artifactRepairAuthorizations'][key]['terminalState']={}
        elif target=='missing-authorization': bad['artifactRepairAuthorizations']={}
        else: bad['artifactRevision']=1
        with pytest.raises(ValueError): generation_store.verify_artifact_proof(bad,model,manifest)


@pytest.mark.parametrize('boundary',['before_office','during_office','before_reopen'])
def test_real_artifact_active_time_guard_budget_increase_and_recovery(tmp_path,monkeypatch,boundary):
    from datetime import datetime, UTC, timedelta
    from test_e2e import drive_fixture_host, drive_result_host
    import package_renderer
    original_advance = orchestrator._advance_artifact
    with monkeypatch.context() as setup:
        setup.setattr(orchestrator,'_advance_artifact',lambda files,state:{'outcome':'ARTIFACT_READY','state':state,'nextAction':None})
        ready,_ = drive_fixture_host(tmp_path,terminal_outcomes=('ARTIFACT_READY',))
    calls=[]; offset=[0]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return datetime.now(tz)+timedelta(seconds=offset[0])
    monkeypatch.setattr(orchestrator,'datetime',Clock)
    project = package_renderer.project_artifact; calculate=package_renderer.calculate_artifact
    reopen = package_renderer.verify_artifact
    def projected(*args,**kwargs):
        result=project(*args,**kwargs);calls.append('projection')
        if boundary=='before_office':offset[0]+=3601
        return result
    def calculated(*args,**kwargs):
        result=calculate(*args,**kwargs);calls.append('office')
        if (boundary=='during_office' and calls.count('office')==1) or (boundary=='before_reopen' and calls.count('office')==2):offset[0]+=3601
        return result
    def reopened(*args,**kwargs):
        result=reopen(*args,**kwargs);calls.append('reopen');return result
    monkeypatch.setattr(package_renderer,'project_artifact',projected)
    monkeypatch.setattr(package_renderer,'calculate_artifact',calculated)
    monkeypatch.setattr(package_renderer,'verify_artifact',reopened)
    waiting=orchestrator.run_mode(tmp_path,'resume')
    assert waiting['outcome']=='WAITING_INPUT',waiting
    expected={'before_office':['projection'],'during_office':['projection','office'],'before_reopen':['projection','office','office']}[boundary]
    assert calls==expected
    run=tmp_path/'.ai-sow/work/runs'/ready['state']['runId']
    events=[json.loads(p.read_bytes()) for p in sorted((run/'events').glob('*.json'))]
    performed=[e['payload'] for e in events if e['type']=='DETERMINISTIC_STEP_FINISHED' and e['payload'].get('stageKind')=='ARTIFACT']
    assert len(performed)==len(expected) and all(e['outcome']=='SUCCEEDED' for e in performed)
    assert (datetime.fromisoformat(performed[-1]['endedAtUtc'])-datetime.fromisoformat(performed[-1]['startedAtUtc'])).total_seconds()>=3601
    completed={p:p.read_bytes() for p in (run/'artifact-steps').glob('*/*.json')}
    assert not list(run.glob('artifacts/*/artifact-manifest.json'))
    assert not (tmp_path/'.ai-sow/current.json').exists()
    assert orchestrator.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'
    assert calls==expected
    policy=json.loads((tmp_path/'budget.json').read_bytes());policy['maxActiveSeconds']=8000
    (tmp_path/'larger-budget.json').write_bytes(canonical_json_bytes(policy))
    append=orchestrator._append_run_event
    def after_policy(*args,**kwargs):
        result=append(*args,**kwargs)
        if args[2]=='RUN_BUDGET_POLICY_PUBLISHED': raise RuntimeError('crash after policy publication')
        return result
    with monkeypatch.context() as crash:
        crash.setattr(orchestrator,'_append_run_event',after_policy)
        with pytest.raises(RuntimeError):orchestrator.run_mode(tmp_path,'resume',budget_policy='larger-budget.json')
    resumed=orchestrator.run_mode(tmp_path,'resume')
    result,_=drive_result_host(tmp_path,resumed)
    assert result['outcome']=='REQUEST_APPROVAL',result
    assert calls.count('projection')==1 and calls.count('office')==2 and calls.count('reopen')==1
    assert all(p.read_bytes()==raw for p,raw in completed.items())
    assert not (tmp_path/'.ai-sow/current.json').exists()


@pytest.mark.parametrize('case',['repair','fail'])
def test_visible_sheet_review_public_preseal_retry_and_failure_gate(tmp_path,case):
    from test_e2e import drive_fixture_host,_submission
    def response(action,packet):
        value=_submission(action,packet)
        if action['actionContractId']=='ARTIFACT_VISUAL_REVIEW-v1' and action['revision']==1:
            if case=='repair':value['sheets'].pop()
            else:
                value['sheets'][0].update(decision='FAIL',findings=['末行裁切'])
                value['sheets'][0]['checks']['clipping']='FAIL';value['overallDecision']='FAIL'
        return value
    result,trace=drive_fixture_host(tmp_path,submission_factory=response,terminal_outcomes=('REQUEST_APPROVAL','MANUAL_REVIEW_REQUIRED'))
    visuals=[a for a in trace if a['actionContractId']=='ARTIFACT_VISUAL_REVIEW-v1']
    assert len({a['logicalWorkId'] for a in visuals})==1
    if case=='repair':
        assert result['outcome']=='REQUEST_APPROVAL'
        assert [a['revision'] for a in visuals]==[1,2]
        record=json.loads((tmp_path/Path(visuals[0]['packetPath']).parent/'record.json').read_bytes())
        assert record['outcome']=='FAILED' and record['failureKind']=='INVALID_IR'
    else:
        assert result['outcome']=='MANUAL_REVIEW_REQUIRED'
        assert len(visuals)==1
        assert not list(tmp_path.glob('.ai-sow/work/runs/*/artifacts/*/artifact-manifest.json'))
        record=json.loads((tmp_path/Path(visuals[0]['packetPath']).parent/'record.json').read_bytes())
        assert record['outcome']=='SUCCEEDED'
    assert not (tmp_path/'.ai-sow/current.json').exists()


@pytest.mark.parametrize('kind',['MATERIALIZE','OFFICE','RENDER','FINAL_VALIDATE'])
def test_real_artifact_completed_event_missing_output_recovers_exact_bytes(tmp_path,monkeypatch,kind):
    from test_e2e import drive_fixture_host,drive_result_host
    original=ProjectFiles.publish_new;hit=[]
    def interrupted(self,path,payload):
        if '/artifact-steps/'+kind+'/' in path and not hit:
            hit.append(path);raise RuntimeError('after completed event before output')
        return original(self,path,payload)
    with monkeypatch.context() as crash:
        crash.setattr(ProjectFiles,'publish_new',interrupted)
        with pytest.raises(RuntimeError):drive_fixture_host(tmp_path)
    assert len(hit)==1 and not (tmp_path/hit[0]).exists()
    result,_=drive_result_host(tmp_path,orchestrator.run_mode(tmp_path,'resume'))
    assert result['outcome']=='REQUEST_APPROVAL',result
    events=[json.loads(p.read_bytes()) for p in tmp_path.glob('.ai-sow/work/runs/*/events/*.json')]
    completed=[e['payload'] for e in events if e['type']=='DETERMINISTIC_STEP_FINISHED'
        and e['payload'].get('stageKind')=='ARTIFACT' and e['payload']['stepKind']==kind]
    assert len(completed)==2 and all(e['outcome']=='SUCCEEDED' for e in completed)
    assert len({e['outputSha256'] for e in completed})==1
    assert sha256_bytes((tmp_path/hit[0]).read_bytes())==completed[0]['outputSha256']
    assert completed[0]['startedAtUtc']!=completed[1]['startedAtUtc']
