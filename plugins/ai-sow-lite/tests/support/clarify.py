"""Real delivered baseline reuse; no raw-Agent semantic claim."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from .cli import run_request
from .fixtures import build_ingested_case, prepare_case, read_json, write_json


_SESSION_CASES = pytest.StashKey[dict]()


@pytest.fixture(scope='session')
def delivered_baseline(tmp_path_factory, request):
    cache = request.config.stash.setdefault(_SESSION_CASES, {})
    if 'baseline' in cache:
        return cache['baseline']
    metadata = os.environ.get('AI_SOW_LITE_TEST_BASELINE')
    if metadata:
        record = read_json(Path(metadata))
        project = Path(record['project'])
        assert read_json(project / '.ai-sow-lite/current.json') == record['current']
        for path, digest in record['output_hashes'].items():
            assert hashlib.sha256((project / path).read_bytes()).hexdigest() == digest
        return project, record['ids']
    case = build_ingested_case(tmp_path_factory.mktemp('clarify-delivered') / 'project')
    prepared = prepare_case(case)
    applied = run_request(case.project, case.request_id, 'apply', dict(entrypoint='generate',
        prepared_path=prepared['prepared_ref']['path'], plan_path=None, expected_current=None))
    assert applied['ok'], applied
    cache['baseline'] = case.project, case.ids
    return cache['baseline']


@pytest.fixture
def clarify_case(tmp_path, delivered_baseline):
    original, ids = delivered_baseline
    return clone_case(original, ids, tmp_path / 'clarify project')


def clone_case(original, ids, project):
    shutil.copytree(original, project)
    request = str(uuid4())
    from ai_sow_lite.project import ensure_request
    ensure_request(project, request, 'clarify')
    return dict(project=project, ids=deepcopy(ids), request_id=request,
                current=read_json(project / '.ai-sow-lite/current.json'))


def feedback(case, text):
    project, request = case['project'], case['request_id']
    source = project.parent / ('feedback-' + str(uuid4()) + '.md')
    source.write_text(text, encoding='utf-8')
    reply = run_request(project, request, 'ingest', dict(kind='sources', entrypoint='clarify',
        project_type='new', sources=[dict(source_path=str(source), input_id=None,
            material_types=['answer'], uses=['to-be-scope'], use_regions=[])]))
    assert reply['ok'], reply
    return reply['result']['input_refs'][0]['input_version_id']


def edit_draft(case, edits, additional_inputs=()):
    return dict(schema_version='1.0', plan_id=str(uuid4()), revision=1,
        base_version_id=case['current']['version_id'], edits=edits,
        read_selectors=[dict(view='objects', selector=dict(collection='stories',
            object_ids=[case['ids']['S-01']]))],
        read_boundary=dict(input_version_ids=list(additional_inputs), topic_version_ids=[],
            object_ids=[case['ids']['S-01']], depth='current'),
        conditions=[], unresolved_items=[], change_summary='仅修改资料查询的备注。',
        additional_refs=dict(input_version_ids=list(additional_inputs), topic_version_ids=[], evidence_ids=[]))


def check_edits(case, draft):
    path = Path('.ai-sow-lite/work/clarify') / case['request_id'] / 'edit-draft.json'
    write_json(case['project'] / path, draft)
    return run_request(case['project'], case['request_id'], 'check', dict(edit_path=path.as_posix(), scope='full'))


def confirm_plan(case, result):
    """Test controller actually supplies execution text after reading the concrete plan."""
    from ai_sow_lite.contracts import semantic_digest
    plan = read_json(case['project'] / result['plan_ref']['path'])
    content = {key: plan[key] for key in ('plan_id', 'revision', 'base_version_id', 'changes', 'read_set',
        'write_set', 'read_boundary', 'conditions', 'unresolved_items', 'change_summary')}
    digest = semantic_digest(content)
    identity = feedback(case, f"确认执行刚展示的方案 {plan['plan_id']} 修订 {plan['revision']}，内容摘要 {digest}。\n")
    locator = dict(kind='text_lines', start_line=1, end_line=1)
    observed = run_request(case['project'], case['request_id'], 'inspect', dict(view='regions',
        selector=dict(input_version_id=identity, locator=locator)))
    assert observed['ok'], observed
    plan['confirmation'] = dict(digest=digest, input_ref=dict(input_version_id=identity, locator=locator,
        excerpt_hash=observed['result']['coverage']['excerpt_hash']), shown_plan_ref=result['plan_ref'],
        selected_changes=deepcopy(plan['changes']))
    path = Path(result['plan_ref']['path']).with_name('confirmed-plan.json')
    write_json(case['project'] / path, plan)
    return path.as_posix(), identity


def adopt_feedback(case, text, target):
    identity = feedback(case, text + '\n')
    locator = dict(kind='text_lines', start_line=1, end_line=1)
    observed = run_request(case['project'], case['request_id'], 'inspect', dict(view='regions',
        selector=dict(input_version_id=identity, locator=locator)))
    assert observed['ok'], observed
    source = dict(input_version_id=identity, locator=locator, excerpt_hash=observed['result']['coverage']['excerpt_hash'])
    evidence, topic, version = (str(uuid4()) for _ in range(3))
    analysis = dict(schema_version='1.0', observations=[], evidence=[dict(id=evidence, kind='statement', text=text,
        source_refs=[source], basis_refs=[], limitations='')], topics=[dict(topic_id=topic, topic_version_id=version,
        title='本次明确反馈', input_version_ids=[identity], uses=['to-be-scope'], covered_regions=[source],
        uncovered_regions=[], evidence_refs=[evidence], related_object_ids=[target], external_responsibilities='',
        limitations='', conclusion=text, historical_items=[])])
    path = Path('.ai-sow-lite/work/clarify') / case['request_id'] / 'feedback-analysis.json'
    write_json(case['project'] / path, analysis)
    registered = run_request(case['project'], case['request_id'], 'ingest', dict(kind='analysis', entrypoint='clarify',
        analysis_path=path.as_posix()))
    assert registered['ok'], registered
    return dict(input_version_ids=[identity], topic_version_ids=[version], evidence_ids=[evidence])


def complexity_draft(case, complexity):
    old = case['project'] / '.ai-sow-lite/versions' / case['current']['version_id']
    task = next(t for t in read_json(old / 'model.json')['tasks'] if t['id'] == case['ids']['T-06'])
    text = f'资料迁移复杂度采用 {complexity}；记录条数仍未知，保留原迁移范围和责任。'
    refs = adopt_feedback(case, text, task['id'])
    evidence = refs['evidence_ids'][0]
    basis = deepcopy(task['classification_basis'])
    basis[0]['evidence_refs'].append(evidence)
    basis[0]['rationale'] = text + '其他分类沿用原有依据。'
    decision = dict(id=str(uuid4()), kind='scope_decision', text=text, evidence_refs=[evidence],
                    applies_to=[dict(object_id=task['id'], field='complexity')])
    edits = [dict(op='replace', collection='tasks', object_id=task['id'], field=field, value=value)
             for field, value in [('complexity', complexity), ('classification_basis', basis), ('notes', text)]]
    edits += [dict(op='replace', collection='pending_items', object_id=case['ids']['P-01'], field=field, value=value)
              for field, value in [('status', 'resolved'), ('current_handling', text), ('resolution', dict(
                  decision_id=decision['id'], request_id=case['request_id'], summary=text))]]
    edits.append(dict(op='add', collection='decisions', object_id=decision['id'], field=None, value=decision))
    draft = edit_draft(case, edits, refs['input_version_ids'])
    draft['additional_refs'] = refs
    draft['change_summary'] = text
    draft['read_selectors'] = [dict(view='objects', selector=dict(collection='tasks', object_ids=[task['id']])),
                              dict(view='inputs', selector=dict(input_version_ids=refs['input_version_ids']))]
    draft['read_boundary']['object_ids'] = [task['id']]
    draft['read_boundary']['topic_version_ids'] = refs['topic_version_ids']
    return draft


@pytest.fixture(scope='session')
def prepared_seed(tmp_path_factory, delivered_baseline, request):
    cache = request.config.stash.setdefault(_SESSION_CASES, {})
    if 'prepared' in cache:
        return cache['prepared']
    capture = os.environ.get('AI_SOW_LITE_TEST_PREPARED')
    if capture:
        return read_json(Path(capture))
    project, ids = delivered_baseline
    case = clone_case(project, ids, tmp_path_factory.mktemp('clarify-preview') / 'project')
    prepare_notes_change(case, '保留已有验收范围')
    cache['prepared'] = dict(case, project=str(case['project']))
    return cache['prepared']


def prepare_notes_change(case, notes):
    """One real preview, then actual controller confirmation; no Office on apply."""
    identity = feedback(case, f'请仅将资料查询备注改为“{notes}”。\n')
    reply = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value=notes)], [identity]))
    assert reply['ok'], reply
    result = reply['result']
    rendered = run_request(case['project'], case['request_id'], 'render', dict(candidate_path=result['candidate_ref']['path'],
        check_path=result['check_ref']['path'], expected_current=case['current']))
    assert rendered['ok'], rendered
    confirmed, _ = confirm_plan(case, result)
    case.update(result=result, prepared_ref=rendered['result']['prepared_ref'], confirmed_path=confirmed)
    return rendered['result']


@pytest.fixture
def prepared_case(tmp_path, prepared_seed):
    """Clone real prepared bytes. A completed capture is rewound only in this test copy."""
    return clone_prepared(prepared_seed, tmp_path / 'prepared project')


def clone_prepared(prepared_seed, project):
    case = deepcopy(prepared_seed)
    case['project'] = project
    shutil.copytree(prepared_seed['project'], case['project'])
    if 'applied_current' in case:
        write_json(case['project'] / '.ai-sow-lite/current.json', case['current'])
        shutil.rmtree(case['project'] / '.ai-sow-lite/versions' / case['applied_current']['version_id'])
        work = case['project'] / '.ai-sow-lite/work/clarify' / case['request_id']
        for name in ('application.json', 'intent.json'):
            (work / name).unlink(missing_ok=True)
    case['confirmed_path'] = Path(case['result']['plan_ref']['path']).with_name('confirmed-plan.json').as_posix()
    return case


@pytest.fixture(scope='session')
def serial_seed(tmp_path_factory, request):
    metadata = os.environ.get('AI_SOW_LITE_TEST_SERIAL_CHAIN')
    if metadata:
        return read_json(Path(metadata))
    cache = request.config.stash.setdefault(_SESSION_CASES, {})
    if 'serial' in cache:
        return cache['serial']
    first = clone_prepared(request.getfixturevalue('prepared_seed'),
                           tmp_path_factory.mktemp('clarify-serial') / 'project')
    project = first['project']
    record = dict(project=str(project), base_current=first['current'], requests=[])
    for index in range(2):
        if index == 0:
            case = first
        else:
            from ai_sow_lite.project import ensure_request
            request_id = str(uuid4())
            ensure_request(project, request_id, 'clarify')
            case = dict(project=project, ids=first['ids'], request_id=request_id,
                        current=read_json(project / '.ai-sow-lite/current.json'))
            prepare_notes_change(case, '沿用当前验收范围，保留复核记录')
        payload = dict(entrypoint='clarify', prepared_path=case['prepared_ref']['path'],
                       plan_path=case['confirmed_path'], expected_current=case['current'])
        applied = run_request(project, case['request_id'], 'apply', payload)
        assert applied['ok'], applied
        record['requests'].append(dict(request_id=case['request_id'], payload=payload,
            applied_current=read_json(project / '.ai-sow-lite/current.json')))
    record['final_current'] = record['requests'][-1]['applied_current']
    cache['serial'] = record
    return record


def controlled_base_change(case, filename, value):
    """Mechanical-only augmentation; not a claim of a new Office-delivered baseline."""
    project = case['project']
    directory = project / '.ai-sow-lite/versions' / case['current']['version_id']
    write_json(directory / filename, value)
    manifest = read_json(directory / 'manifest.json')
    for ref in manifest['files']:
        if Path(ref['path']).name == filename:
            ref['sha256'] = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
    write_json(directory / 'manifest.json', manifest)
    case['current']['manifest_hash'] = hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest()
    write_json(project / '.ai-sow-lite/current.json', case['current'])
