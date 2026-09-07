"""Finite execution recovery retains successful deterministic stage outputs."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest
TEST_LAYER='integration'
ROOT=Path(__file__).parents[1]
for directory in (ROOT/'scripts',ROOT/'tests',ROOT.parents[1]):
    if str(directory) not in sys.path:sys.path.insert(0,str(directory))
from test_orchestrator import orchestrator_module as api, write_run_store_request, write_budget_policy
from runtime.project_io import ProjectFiles
from contracts import canonical_json_bytes


@pytest.mark.parametrize('kind', ['MATERIALIZE','VALIDATE','OFFICE','RENDER'])
def test_failed_step_resumes_without_recomputing_completed_output(tmp_path,kind):
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path)
    first=canonical_json_bytes({'stable':'completed upstream'})
    assert api._deterministic_step(files,state,'MATERIALIZE',lambda:first,stage='TASK',revision=1)==first
    def fail():raise OSError('temporary read failure')
    with pytest.raises(ValueError):api._deterministic_step(files,state,kind,fail,stage='ARTIFACT',revision=1)
    event=api._read_run_events(files,state['runId'])[-1]
    assert event.payload['stageKind']=='ARTIFACT'
    assert event.payload['diagnostic']['path']==f'/ARTIFACT/1/{kind}'
    raw=canonical_json_bytes({'artifact':'recovered'})
    assert api._deterministic_step(files,state,kind,lambda:raw,stage='ARTIFACT',revision=1)==raw
    assert api._deterministic_step(files,state,'MATERIALIZE',lambda:pytest.fail('upstream rerun'),stage='TASK',revision=1)==first


def test_deterministic_cap_preserves_failure_and_resumes_with_finite_increase(tmp_path):
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path);calls=[]
    def fail():calls.append(1);raise OSError('blocked read')
    for _ in range(2):
        with pytest.raises(ValueError):api._deterministic_step(files,state,'OFFICE',fail,stage='ARTIFACT',revision=1)
    from stage_planner import StagePlanningBlocked
    with pytest.raises(StagePlanningBlocked):api._deterministic_step(files,state,'OFFICE',fail,stage='ARTIFACT',revision=1)
    assert len(calls)==2
    policy=api._effective_budget_policy(files,state['runId'])[1]
    increased={**policy,'maxDeterministicAttempts':3}
    api._validate_budget_replacement(policy,increased);api._publish_budget_policy(files,state['runId'],increased)
    assert api._deterministic_step(files,state,'OFFICE',lambda:b'recovered',stage='ARTIFACT',revision=1)==b'recovered'
    failures=[event for event in api._read_run_events(files,state['runId']) if event.type=='DETERMINISTIC_STEP_FINISHED' and event.payload['outcome']=='FAILED']
    assert [event.payload['attempt'] for event in failures]==[1,2]


def test_missing_success_cache_does_not_remove_recomputation_limit(tmp_path):
    from contracts import sha256_bytes
    from stage_planner import StagePlanningBlocked
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path);raw=b'completed'
    api._deterministic_step(files,state,'OFFICE',lambda:raw,stage='ARTIFACT',revision=1)
    cache=tmp_path/f".ai-sow/work/runs/{state['runId']}/step-recovery/ARTIFACT/1/OFFICE/{sha256_bytes(raw)}.json"
    cache.unlink();calls=[]
    def fail():calls.append(1);raise OSError('retry failure')
    for _ in range(2):
        with pytest.raises(ValueError):api._deterministic_step(files,state,'OFFICE',fail,stage='ARTIFACT',revision=1)
    with pytest.raises(StagePlanningBlocked):api._deterministic_step(files,state,'OFFICE',fail,stage='ARTIFACT',revision=1)
    assert len(calls)==2
    cache.write_bytes(raw)
    assert api._deterministic_step(files,state,'OFFICE',fail,stage='ARTIFACT',revision=1)==raw
    assert len(calls)==2


@pytest.mark.parametrize('owner', ['scope_compiler','prior_state','delivery_compiler','task_compiler'])
def test_owner_input_gate_keeps_its_wait_classification_and_diagnostic(tmp_path,owner):
    import importlib
    names={'scope_compiler':'ScopeInputRequired','prior_state':'PriorInputRequired',
           'delivery_compiler':'StoryInputRequired','task_compiler':'TaskInputRequired'}
    error_type=getattr(importlib.import_module(owner),names[owner])
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path)
    def require_input():raise error_type('需要现有输入之外的用户事实')
    with pytest.raises(error_type):api._deterministic_step(files,state,'MATERIALIZE',require_input,stage='SCOPE',revision=1)
    failure=api._read_run_events(files,state['runId'])[-1].payload
    assert failure['outcome']=='FAILED' and failure['diagnostic']['path']=='/SCOPE/1/MATERIALIZE'


def test_step_fingerprint_change_invalidates_only_affected_cache(tmp_path):
    from contracts import sha256_bytes
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path);calls=[]
    prefix=b'unchanged-owner-output'
    def fingerprint(data,tool):return {'contract':'ai-sow-step-fingerprint-v1','inputSha256':sha256_bytes(data),
        'parametersSha256':'1'*64,'implementationSha256':'2'*64,'toolSha256':tool*64}
    first=fingerprint(b'workbook-a','3')
    api._deterministic_step(files,state,'MATERIALIZE',lambda:prefix,stage='TASK',revision=1,fingerprint=first)
    def render():calls.append('render');return b'locally-verified-step-output'
    for _ in range(2):assert api._deterministic_step(files,state,'RENDER',render,stage='ARTIFACT',revision=1,fingerprint=first)==b'locally-verified-step-output'
    assert calls==['render']
    changed=fingerprint(b'workbook-b','3')
    api._deterministic_step(files,state,'RENDER',render,stage='ARTIFACT',revision=1,fingerprint=changed)
    assert calls==['render','render']
    changed_tool=fingerprint(b'workbook-b','4')
    api._deterministic_step(files,state,'RENDER',render,stage='ARTIFACT',revision=1,fingerprint=changed_tool)
    assert calls==['render','render','render']
    assert api._deterministic_step(files,state,'MATERIALIZE',lambda:pytest.fail('unrelated prefix rerun'),stage='TASK',revision=1,fingerprint=first)==prefix


def test_office_tool_fingerprint_is_path_free_and_deterministic(tmp_path,monkeypatch):
    from contracts import sha256_bytes
    binary=tmp_path/'custom-soffice';binary.write_bytes(b'office-binary')
    monkeypatch.setenv('AI_SOW_OFFICE_BIN',str(binary))
    first=api._office_tool_fingerprint();second=api._office_tool_fingerprint()
    assert first==second=={'selectionSource':'AI_SOW_OFFICE_BIN',
        'executableBasename':'custom-soffice','executableSha256':sha256_bytes(b'office-binary'),
        'platform':first['platform'],'normalizedArguments':['--headless']}
    assert str(tmp_path) not in canonical_json_bytes(first).decode()


def test_render_implementation_change_does_not_invalidate_office_fingerprint(monkeypatch):
    from contracts import sha256_bytes
    original=Path.read_bytes
    office_before=api._step_fingerprint('workbook',parameters={'kind':'OFFICE'},
        implementations=['office_engine.py'],tool={'selectionSource':'test'})
    render_before=api._step_fingerprint('workbook',parameters={'kind':'RENDER'},
        implementations=['package_renderer.py','office_engine.py'],tool={'selectionSource':'test'})
    def changed(path):
        raw=original(path)
        return raw+b'\nrender-only-change' if path.name=='package_renderer.py' else raw
    monkeypatch.setattr(Path,'read_bytes',changed)
    office_after=api._step_fingerprint('workbook',parameters={'kind':'OFFICE'},
        implementations=['office_engine.py'],tool={'selectionSource':'test'})
    render_after=api._step_fingerprint('workbook',parameters={'kind':'RENDER'},
        implementations=['package_renderer.py','office_engine.py'],tool={'selectionSource':'test'})
    assert office_after==office_before
    assert render_after['implementationSha256']!=render_before['implementationSha256']


def test_old_success_without_fingerprint_is_not_reused_by_new_path(tmp_path):
    from contracts import sha256_bytes
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path);calls=[]
    api._deterministic_step(files,state,'RENDER',lambda:b'old',stage='ARTIFACT',revision=1)
    fingerprint={'contract':'ai-sow-step-fingerprint-v1','inputSha256':sha256_bytes(b'input'),
        'parametersSha256':'1'*64,'implementationSha256':'2'*64,'toolSha256':'3'*64}
    result=api._deterministic_step(files,state,'RENDER',
        lambda:(calls.append(1) or b'new'),stage='ARTIFACT',revision=1,fingerprint=fingerprint)
    assert result==b'new' and calls==[1]


def test_two_outputs_for_one_fingerprint_are_a_conflict(tmp_path):
    from contracts import sha256_bytes
    state=api.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))['state']
    files=ProjectFiles.open(tmp_path)
    fingerprint={'contract':'ai-sow-step-fingerprint-v1','inputSha256':sha256_bytes(b'input'),
        'parametersSha256':'1'*64,'implementationSha256':'2'*64,'toolSha256':'3'*64}
    api._deterministic_step(files,state,'RENDER',lambda:b'first',
        stage='ARTIFACT',revision=1,fingerprint=fingerprint)
    api._append_run_event(files,state['runId'],'DETERMINISTIC_STEP_FINISHED',{
        'stepKind':'RENDER','outcome':'SUCCEEDED','startedAtUtc':'2026-09-07T00:00:00Z',
        'endedAtUtc':'2026-09-07T00:00:01Z','stageKind':'ARTIFACT','semanticRevision':1,
        'outputSha256':sha256_bytes(b'second'),'stepFingerprint':fingerprint})
    with pytest.raises(ValueError,match='冲突'):
        api._step_output_hash(files,state,'ARTIFACT',1,'RENDER',fingerprint=fingerprint)
