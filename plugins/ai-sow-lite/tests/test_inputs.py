"""Real CLI text registration; no synthetic ingestion records."""
import hashlib
from uuid import uuid4

import pytest

from .support.cli import run_request
from .support.fixtures import read_json, write_json


def sources_payload(*paths, input_id=None, project_type='new'):
    return dict(kind='sources', entrypoint='generate', project_type=project_type, sources=[
        dict(source_path=str(p), input_id=input_id, material_types=['prd'], uses=['to-be-scope'], use_regions=[])
        for p in paths])


def ingest(tmp_path, raw=b'# Title\r\nChinese: \xe4\xb8\xad\xe6\x96\x87\nlast\r'):
    source = tmp_path / 'source.md'
    source.write_bytes(raw)
    project, request = tmp_path / 'project', str(uuid4())
    response = run_request(project, request, 'ingest', sources_payload(source))
    assert response['ok'], response
    return project, request, source, response['result']


def test_first_ingest_copies_actual_bytes_and_reuses_reading(tmp_path):
    project, request, source, result = ingest(tmp_path)
    entry = result['input_refs'][0]
    original = project / entry['relative_path']
    assert original.read_bytes() == source.read_bytes()
    assert entry['content_hash'] == hashlib.sha256(source.read_bytes()).hexdigest()
    reading = read_json(project / result['reading_refs'][0]['path'])
    assert reading['input_version_id'] == entry['input_version_id']
    assert reading['adapter_version'] == 'lite-text-v1'
    assert reading['excerpts'][0]['locator'] == dict(kind='text_lines', start_line=1, end_line=3)
    assert (project / reading['excerpts'][0]['file_ref']['path']).read_bytes() == source.read_bytes()
    again = run_request(project, request, 'ingest', sources_payload(source))
    assert again['result']['input_refs'] == result['input_refs']
    assert again['result']['reading_refs'] == result['reading_refs']
    assert not (project / '.ai-sow-lite/current.json').exists()
    assert read_json(project / result['checkpoint_ref']['path'])['repair_batches'] == 0


def test_partial_failure_keeps_success_and_unreadable_original(tmp_path):
    good, bad = tmp_path / 'good.md', tmp_path / 'bad.md'
    good.write_bytes(b'good\r\n')
    bad.write_bytes(b'\xff\n')
    project = tmp_path / 'project'
    response = run_request(project, str(uuid4()), 'ingest', sources_payload(good, bad, tmp_path / 'missing.md'))
    assert not response['ok']
    assert len(response['result']['input_refs']) == 2  # bytes remain even when text decoding fails
    assert len(response['result']['reading_refs']) == 1
    assert len(response['result']['failures']) == 2
    assert all((project / e['relative_path']).is_file() for e in response['result']['input_refs'])
    assert not (project / '.ai-sow-lite/current.json').exists()


def test_changed_input_gets_new_version_without_overwriting_original(tmp_path):
    project, request, source, result = ingest(tmp_path)
    old = result['input_refs'][0]
    before = (project / old['relative_path']).read_bytes()
    source.write_bytes(b'new material\n')
    response = run_request(project, request, 'ingest', sources_payload(source, input_id=old['input_id']))
    assert response['ok'], response
    new = response['result']['input_refs'][0]
    assert new['input_id'] == old['input_id']
    assert new['input_version_id'] != old['input_version_id']
    assert (project / old['relative_path']).read_bytes() == before


def test_identity_conflict_and_unsupported_formats_are_explicit(tmp_path):
    project, request, source, result = ingest(tmp_path)
    for payload, code in [(sources_payload(source, project_type='existing'), 'PROJECT_ID_CONFLICT'),
                          (sources_payload(source, input_id=str(uuid4())), 'INPUT_ID_CONFLICT')]:
        response = run_request(project, request, 'ingest', payload)
        assert not response['ok']
        assert code in {d['code'] for d in response['diagnostics']}
    for suffix in ['.xlsx', '.pdf', '.docx', '.html']:
        path = tmp_path / ('future' + suffix)
        path.write_bytes(b'not a supported reader')
        response = run_request(project, request, 'ingest', sources_payload(path))
        assert not response['ok']
        assert response['diagnostics'][0]['code'] == 'FORMAT_UNSUPPORTED'
        assert response['result']['reading_refs'] == []


def test_project_symlink_escape_never_writes_outside(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.ai-sow-lite').symlink_to(outside, target_is_directory=True)
    source = tmp_path / 'source.md'
    source.write_bytes(b'text')
    response = run_request(project, str(uuid4()), 'ingest', sources_payload(source))
    assert not response['ok']
    assert list(outside.iterdir()) == []


def test_external_symlink_and_renamed_binary_are_not_text(tmp_path):
    source = tmp_path / 'actual.md'
    source.write_bytes(b'%PDF-1.7\n')
    link = tmp_path / 'link.md'
    link.symlink_to(source)
    for path in [link, source]:
        response = run_request(tmp_path / 'project', str(uuid4()), 'ingest', sources_payload(path))
        assert not response['ok']
        assert response['result']['reading_refs'] == []


def inspect(project, request, view, selector=None, limit=20, cursor=None):
    return run_request(project, request, 'inspect', dict(view=view, selector=selector or {}, limit=limit, cursor=cursor))


def test_inputs_cursor_is_query_and_registry_bound(tmp_path):
    project, request, source, result = ingest(tmp_path)
    source2 = tmp_path / 'second.md'
    source2.write_text('second\n')
    assert run_request(project, request, 'ingest', sources_payload(source2))['ok']
    first = inspect(project, request, 'inputs', limit=1)['result']
    assert (first['matched_count'], first['returned_count'], first['remaining_count']) == (2, 1, 1)
    second = inspect(project, request, 'inputs', limit=1, cursor=first['next_cursor'])['result']
    assert first['items'] != second['items'] and second['next_cursor'] is None
    invalid = inspect(project, request, 'inputs', {'input_version_ids': []}, cursor=first['next_cursor'])
    assert not invalid['ok']
    source.write_text('changed\n')
    assert run_request(project, request, 'ingest', sources_payload(source))['ok']
    stale = inspect(project, request, 'inputs', limit=1, cursor=first['next_cursor'])
    assert stale['diagnostics'][0]['code'] == 'VERSION_INCOMPATIBLE'


def test_region_returns_exact_crlf_and_detects_corrupt_sources(tmp_path):
    project, request, source, result = ingest(tmp_path)
    entry = result['input_refs'][0]
    selector = dict(input_version_id=entry['input_version_id'], locator=dict(kind='text_lines', start_line=1, end_line=2))
    response = inspect(project, request, 'regions', selector, limit=1)
    assert response['ok'], response
    first = response['result']
    assert first['items'][0]['text'] == '# Title\r\n'
    assert first['coverage']['excerpt_hash'] == hashlib.sha256('# Title\r\nChinese: 中文\n'.encode()).hexdigest()
    second = inspect(project, request, 'regions', selector, cursor=first['next_cursor'])['result']
    assert second['items'][0]['text'] == 'Chinese: 中文\n'
    (project / entry['relative_path']).write_bytes(b'corrupted')
    assert inspect(project, request, 'regions', selector)['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'


def test_long_line_has_finite_exact_continuation(tmp_path):
    raw = ('中' * 50000 + '\r\nnext\n').encode()
    project, request, source, result = ingest(tmp_path, raw)
    selector = dict(input_version_id=result['input_refs'][0]['input_version_id'],
                    locator=dict(kind='text_lines', start_line=1, end_line=2))
    fragments, cursor = [], None
    for _ in range(20):
        response = inspect(project, request, 'regions', selector, cursor=cursor)
        assert response['ok'], response
        data = response['result']
        fragments.extend(item['text'] for item in data['items'])
        assert len(''.join(item['text'] for item in data['items']).encode()) <= 64 * 1024
        cursor = data['next_cursor']
        if cursor is None:
            break
    assert cursor is None
    assert ''.join(fragments).encode() == raw


def test_inspect_empty_corrupt_and_future_views_are_distinct(tmp_path):
    project, request, source, result = ingest(tmp_path)
    empty = inspect(project, request, 'topics', {'topic_version_ids': [str(uuid4())]})
    assert empty['ok'] and empty['result']['matched_count'] == 0
    response = inspect(project, request, 'telemetry', {'request_id': request})
    assert response['ok'] and response['result']['report_ref'] is not None
    assert next(m for m in response['result']['items'] if m['name'] == 'total_tokens')['value'] is None
    (project / '.ai-sow-lite/inputs/index.json').write_bytes(b'broken')
    assert not inspect(project, request, 'inputs')['ok']


def test_real_cli_analysis_and_candidate_check(tmp_path):
    from .support.fixtures import build_ingested_case
    case = build_ingested_case(tmp_path / 'project')
    response = run_request(case.project, case.request_id, 'check', dict(
        candidate_path=case.candidate_path.relative_to(case.project).as_posix(), scope='full', plan_path=None))
    assert response['ok'], response
    assert response['result']['valid_for_render'] is True
    assert not (case.project / '.ai-sow-lite/current.json').exists()
    topics = inspect(case.project, case.request_id, 'topics', {'topic_version_ids': [case.ids['topic-version']]})
    assert topics['ok'] and topics['result']['matched_count'] == 1
    analysis_path = case.file('analysis.json')
    data = read_json(analysis_path)
    data['evidence'][0]['text'] += ' conflicts'
    write_json(analysis_path, data)
    conflict = run_request(case.project, case.request_id, 'ingest', dict(kind='analysis', entrypoint='generate',
                           analysis_path=analysis_path.relative_to(case.project).as_posix()))
    assert not conflict['ok']
    assert conflict['diagnostics'][0]['code'] == 'IDENTITY_CONFLICT'


@pytest.mark.parametrize('mutation', ['hash', 'outside', 'observation', 'cycle'])
def test_analysis_rejects_unverified_sources_without_publication(tmp_path, mutation):
    from .support.fixtures import build_ingested_case
    case = build_ingested_case(tmp_path / 'project')
    data = read_json(case.file('analysis.json'))
    data['topics'][0]['topic_version_id'] = str(uuid4())
    if mutation == 'hash':
        data['evidence'][0]['source_refs'][0]['excerpt_hash'] = '0' * 64
    elif mutation == 'outside':
        data['evidence'][0]['source_refs'][0]['locator']['path'] = '../../outside.md'
    elif mutation == 'observation':
        data['observations'] = [dict(path='.ai-sow-lite/work/fake.json', sha256='0' * 64)]
    else:
        data['evidence'][0]['basis_refs'] = [data['evidence'][0]['id']]
    write_json(case.file('bad-analysis.json'), data)
    response = run_request(case.project, case.request_id, 'ingest', dict(kind='analysis', entrypoint='generate',
                           analysis_path=case.file('bad-analysis.json').relative_to(case.project).as_posix()))
    assert not response['ok']
    assert not (case.project / '.ai-sow-lite/analysis/topics' / data['topics'][0]['topic_version_id']).exists()


def test_standards_are_from_pinned_template_and_include_scale_thresholds(tmp_path):
    project, request, source, result = ingest(tmp_path)
    response = inspect(project, request, 'standards', {'work_type_ids': ['AN-IMPACT']})
    assert response['ok'], response
    data = response['result']
    assert data['matched_count'] == 1
    row = data['items'][0]
    assert row['工作类型'] == '需求与变更技术影响分析'
    assert row['S（简单）'] == '1 个受影响技术单元；≤3 个影响点；1 类主要约束；单一责任方'
    assert not {'新建 PD', '调整 PD', '复用 PD'} & row.keys()
    assert data['selected_version']['template_hash'] == read_json(project / '.ai-sow-lite/project.json')['template_hash']
    directory = inspect(project, request, 'standards', limit=1)['result']
    assert directory['matched_count'] > 1 and directory['next_cursor']
    assert set(directory['items'][0]) == {'工作类型 ID', '分类', '工作类型'}


def test_current_and_object_queries_pin_one_version_and_keep_empty_scope(tmp_path):
    from ai_sow_lite.project import _commit_version
    from ai_sow_lite.contracts import canonical_json_bytes
    from .support.fixtures import storage_package, FIXTURES
    package = storage_package(tmp_path)
    # Real business JSON in a deliberately storage-only applied package.
    for name in ['model.json', 'pending-items.json', 'decisions.json']:
        raw = (FIXTURES / 'generate' / name).read_bytes()
        (package['prepared_directory'] / name).write_bytes(raw)
        next(r for r in package['manifest']['files'] if r['path'].endswith('/' + name))['sha256'] = hashlib.sha256(raw).hexdigest()
    _commit_version(**package)
    request = str(uuid4())
    version = package['manifest']['version_id']
    assert inspect(tmp_path, request, 'current')['result']['selected_version']['version_id'] == version
    match = inspect(tmp_path, request, 'objects', {'collection': 'tasks', 'title': '资料查询页'})
    assert match['ok'], match
    assert match['result']['matched_count'] == 1
    task = match['result']['items'][0]
    selected = inspect(tmp_path, request, 'objects', {'collection': 'tasks', 'object_ids': [task['id']]})['result']
    assert selected['items'] == [task]
    pending = inspect(tmp_path, request, 'objects', {'collection': 'pending_items', 'status': 'open'})['result']
    assert pending['matched_count'] == 1 and pending['items'][0]['status'] == 'open'
    query = {'collection': 'dependencies', 'relation': {'object_id': str(uuid4()), 'direction': 'both'}}
    empty = inspect(tmp_path, request, 'objects', query)['result']
    assert empty['items'] == [] and empty['coverage']['selector'] == query
    assert empty['selected_version']['version_id'] == version
    assert not inspect(tmp_path, request, 'objects')['ok']  # no default whole-model dump
    first = inspect(tmp_path, request, 'objects', {'collection': 'tasks', 'title': '查询'}, limit=1)['result']
    second_package = storage_package(tmp_path, expected_current=read_json(tmp_path / '.ai-sow-lite/current.json'))
    for name in ['model.json', 'pending-items.json', 'decisions.json']:
        raw = (package['prepared_directory'] / name).read_bytes()
        (second_package['prepared_directory'] / name).write_bytes(raw)
        next(r for r in second_package['manifest']['files'] if r['path'].endswith('/' + name))['sha256'] = hashlib.sha256(raw).hexdigest()
    _commit_version(**second_package)
    stale = inspect(tmp_path, request, 'objects', {'collection': 'tasks', 'title': '查询'}, limit=1, cursor=first['next_cursor'])
    assert stale['diagnostics'][0]['code'] == 'VERSION_INCOMPATIBLE'
    old = inspect(tmp_path, request, 'objects', {'collection': 'tasks', 'title': '查询', 'version_id': version}, limit=1)
    assert old['ok'] and old['result']['selected_version']['version_id'] == version


def test_explicit_external_directory_alias_is_not_a_project_escape(tmp_path):
    directory = tmp_path / 'actual'
    directory.mkdir()
    (directory / 'input.md').write_text('text\r\n', newline='')
    alias = tmp_path / 'alias'
    alias.symlink_to(directory, target_is_directory=True)
    response = run_request(tmp_path / 'project', str(uuid4()), 'ingest', sources_payload(alias / 'input.md'))
    assert response['ok'], response


@pytest.mark.parametrize('locator', [dict(kind='text_lines', start_line=3, end_line=1),
                                    dict(kind='xlsx_range', sheet='Sheet1', range='A1', read_id=str(uuid4()))])
def test_input_use_regions_never_claim_an_unsupported_or_invalid_locator(tmp_path, locator):
    source = tmp_path / 'source.md'
    source.write_bytes(b'line\n')
    payload = sources_payload(source)
    payload['sources'][0]['use_regions'] = [dict(material_type='prd', use='to-be-scope', locators=[locator])]
    response = run_request(tmp_path / 'project', str(uuid4()), 'ingest', payload)
    assert not response['ok']


def test_added_material_preserves_exhausted_exploration_and_repair_counts(tmp_path):
    from ai_sow_lite.project import ensure_request, save_checkpoint
    project, request, source, result = ingest(tmp_path)
    checkpoint = ensure_request(project, request, 'generate')
    checkpoint.update(additional_investigation_batches=1, repair_batches=2)
    save_checkpoint(project, checkpoint)
    source2 = tmp_path / 'supplement.md'
    source2.write_bytes(b'new fact\n')
    added = run_request(project, request, 'ingest', sources_payload(source2))
    assert added['ok'], added
    after = read_json(project / added['result']['checkpoint_ref']['path'])
    assert after['additional_investigation_batches'] == 1 and after['repair_batches'] == 2


def test_reingest_rechecks_the_saved_excerpt_attachment(tmp_path):
    project, request, source, result = ingest(tmp_path)
    reading = read_json(project / result['reading_refs'][0]['path'])
    (project / reading['excerpts'][0]['file_ref']['path']).write_bytes(b'tampered attachment')
    again = run_request(project, request, 'ingest', sources_payload(source))
    assert not again['ok']
    assert again['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'
    assert again['result']['reading_refs'] == []


def test_duplicate_registry_identity_is_corruption_not_an_empty_or_successful_read(tmp_path):
    project, request, source, result = ingest(tmp_path)
    path = project / '.ai-sow-lite/inputs/index.json'
    data = read_json(path)
    data['items'].append(data['items'][0])
    write_json(path, data)
    response = inspect(project, request, 'inputs')
    assert not response['ok']


def test_protocol_schema_rejects_unknown_fields_for_implemented_payloads(tmp_path):
    from ai_sow_lite.contracts import schema_validator
    for operation, payload in [('ingest', sources_payload(tmp_path / 'file.md')),
                               ('inspect', dict(view='inputs', selector={})),
                               ('recover', dict(target_request_id=str(uuid4()))),
                               ('apply', dict(entrypoint='generate', prepared_path='file.json', expected_current=None, plan_path=None))]:
        request = dict(protocol_version='1.0', request_id=str(uuid4()), project_path=str(tmp_path),
                       operation=operation, payload=dict(payload, invented=True))
        assert list(schema_validator('protocol').iter_errors(request))


def test_existing_topic_version_cannot_advertise_unstored_new_evidence(tmp_path):
    from copy import deepcopy
    from .support.fixtures import build_ingested_case
    case = build_ingested_case(tmp_path / 'project')
    analysis = read_json(case.file('analysis.json'))
    added = deepcopy(analysis['evidence'][0])
    added['id'] = str(uuid4())
    analysis['evidence'].append(added)
    write_json(case.file('analysis.json'), analysis)
    response = run_request(case.project, case.request_id, 'ingest', dict(kind='analysis', entrypoint='generate',
                           analysis_path=case.file('analysis.json').relative_to(case.project).as_posix()))
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'IDENTITY_CONFLICT'


def test_internal_registration_subdirectory_link_cannot_write_elsewhere(tmp_path):
    project, request, source, result = ingest(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    inputs = project / '.ai-sow-lite/inputs'
    import shutil
    shutil.rmtree(inputs / 'originals')
    (inputs / 'originals').symlink_to(outside, target_is_directory=True)
    source.write_bytes(b'new content')
    response = run_request(project, request, 'ingest', sources_payload(source))
    assert not response['ok']
    assert list(outside.iterdir()) == []


def test_reingest_cannot_replace_a_lost_registry_with_an_empty_one(tmp_path):
    project, request, source, result = ingest(tmp_path)
    original = project / result['input_refs'][0]['relative_path']
    before = original.read_bytes()
    index = project / '.ai-sow-lite/inputs/index.json'
    index.unlink()
    response = run_request(project, request, 'ingest', sources_payload(source))
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'
    assert original.read_bytes() == before and not index.exists()


def _review_s1_interrupted_registration(tmp_path, monkeypatch):
    """Fail only the new topic's index write, after real source/analysis ingestion."""
    from ai_sow_lite import inputs
    from ai_sow_lite.cli import execute
    from .support.fixtures import build_ingested_case
    case = build_ingested_case(tmp_path / 'project')
    candidate = read_json(case.file('analysis.json'))
    topic = str(uuid4())
    candidate['topics'][0]['topic_version_id'] = topic
    path = case.file('next-analysis.json')
    write_json(path, candidate)
    request = dict(protocol_version='1.0', request_id=case.request_id, project_path=str(case.project),
                   operation='ingest', payload=dict(kind='analysis', entrypoint='generate',
                   analysis_path=path.relative_to(case.project).as_posix()))
    write = inputs.write_json
    def fail_index(project, relative, *args, **kwargs):
        if relative == '.ai-sow-lite/analysis/index.json':
            raise OSError('one injected index write failure')
        return write(project, relative, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(inputs, 'write_json', fail_index)
        failed = execute(request)
    assert not failed['ok'] and failed['diagnostics'][0]['code'] == 'IO_FAILED'
    area = case.project / '.ai-sow-lite/analysis/topics' / topic
    assert (area / 'analysis.json').is_file() and (area / 'registration-ref.json').is_file()
    assert len(read_json(case.project / '.ai-sow-lite/analysis/index.json')['items']) == 1
    return case, request, topic, area


def test_review_s1_same_candidate_completes_only_missing_index_entry(tmp_path, monkeypatch):
    from ai_sow_lite.cli import execute
    case, request, topic, area = _review_s1_interrupted_registration(tmp_path, monkeypatch)
    before = {p.relative_to(case.project).as_posix(): p.read_bytes() for p in case.project.rglob('*') if p.is_file() and p.relative_to(case.project).parts[:2] != ('.ai-sow-lite', 'telemetry')}
    retry = execute(request)
    assert retry['ok'], retry
    assert topic in retry['result']['topic_version_ids']
    selected = inspect(case.project, case.request_id, 'topics', {'topic_version_ids': [topic]})
    assert selected['ok'] and selected['result']['matched_count'] == 1, selected
    index = read_json(case.project / '.ai-sow-lite/analysis/index.json')['items']
    assert len(index) == 2
    expected = dict(path=(area / 'analysis.json').relative_to(case.project).as_posix(),
                    sha256=hashlib.sha256((area / 'analysis.json').read_bytes()).hexdigest())
    assert index.count(expected) == 1
    after = {p.relative_to(case.project).as_posix(): p.read_bytes() for p in case.project.rglob('*') if p.is_file() and p.relative_to(case.project).parts[:2] != ('.ai-sow-lite', 'telemetry')}
    assert before.keys() == after.keys()
    assert [name for name in before if before[name] != after[name]] == ['.ai-sow-lite/analysis/index.json']


@pytest.mark.parametrize('damage', ['topic_bytes', 'missing_ref', 'wrong_ref', 'changed_candidate'])
def test_review_s1_incomplete_registration_requires_original_bytes_and_ref(tmp_path, monkeypatch, damage):
    from ai_sow_lite.cli import execute
    case, request, topic, area = _review_s1_interrupted_registration(tmp_path, monkeypatch)
    if damage == 'topic_bytes':
        # Semantically identical whitespace still changes the immutable file binding.
        path = area / 'analysis.json'
        path.write_bytes(path.read_bytes() + b'\n')
    elif damage == 'missing_ref':
        (area / 'registration-ref.json').unlink()
    elif damage == 'wrong_ref':
        ref = read_json(area / 'registration-ref.json')
        ref['sha256'] = '0' * 64
        write_json(area / 'registration-ref.json', ref)
    else:
        path = case.project / request['payload']['analysis_path']
        path.write_bytes(path.read_bytes() + b'\n')
    before_index = (case.project / '.ai-sow-lite/analysis/index.json').read_bytes()
    retried = execute(request)
    assert not retried['ok'], retried
    assert (case.project / '.ai-sow-lite/analysis/index.json').read_bytes() == before_index


def test_review_s2_deduplicated_filename_locators_bind_actual_original(tmp_path):
    raw = b'first\r\nsecond\r\n'
    project, request = tmp_path / 'project', str(uuid4())
    results = []
    for name, line in [('a.md', 1), ('b.md', 2)]:
        source = tmp_path / name
        source.write_bytes(raw)
        payload = sources_payload(source)
        payload['sources'][0]['use_regions'] = [dict(material_type='prd', use='to-be-scope', locators=[
            dict(kind='text_lines', path=name, start_line=line, end_line=line)])]
        response = run_request(project, request, 'ingest', payload)
        assert response['ok'], response
        results.append(response['result'])
    first, second = [result['input_refs'][0] for result in results]
    for key in ('input_id', 'input_version_id', 'content_hash', 'relative_path'):
        assert first[key] == second[key]
    assert results[0]['reading_refs'] == results[1]['reading_refs']
    assert (project / first['relative_path']).read_bytes() == raw
    assert inspect(project, request, 'inputs')['result']['matched_count'] == 1
    assert len(second['use_regions']) == 2
    for region in second['use_regions']:
        locator = region['locators'][0]
        response = inspect(project, request, 'regions', dict(input_version_id=second['input_version_id'], locator=locator))
        assert response['ok'], response
        assert response['result']['items'][0]['text'] == raw.decode().splitlines(keepends=True)[locator['start_line'] - 1]
    assert {region['locators'][0]['path'] for region in second['use_regions']} == {'a.md'}
    # The supplied alias was never saved as an original; inspection must stay strict.
    rejected = inspect(project, request, 'regions', dict(input_version_id=second['input_version_id'],
                       locator=dict(kind='text_lines', path='b.md', start_line=2, end_line=2)))
    assert not rejected['ok']
    assert rejected['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'


def _review_query_version(project, expected_current=None, dependencies=()):
    from ai_sow_lite.project import _commit_version
    from .support.fixtures import storage_package, FIXTURES
    package = storage_package(project, expected_current=expected_current)
    # Valid query data in a storage-only package, without an Office delivery claim.
    for name in ['model.json', 'pending-items.json', 'decisions.json']:
        raw = (FIXTURES / 'generate' / name).read_bytes()
        (package['prepared_directory'] / name).write_bytes(raw)
        next(r for r in package['manifest']['files'] if r['path'].endswith('/' + name))['sha256'] = hashlib.sha256(raw).hexdigest()
    package['manifest']['dependencies'].extend(dependencies)
    _commit_version(**package)
    return package


def _review_record_project_reads(monkeypatch, project):
    from pathlib import Path
    original_read = Path.read_bytes
    reads = []

    def recording_read(path):
        if path.is_relative_to(project):
            reads.append(path.relative_to(project).as_posix())
        return original_read(path)

    monkeypatch.setattr(Path, 'read_bytes', recording_read)
    return reads


@pytest.mark.parametrize('view,selector,filename', [
    ('current', {}, None),
    ('objects', {'collection': 'tasks', 'title': '资料查询页'}, 'model.json'),
    ('objects', {'collection': 'pending_items', 'status': 'open'}, 'pending-items.json'),
])
def test_review_q1_inspect_reads_only_bound_manifests_and_selected_data(tmp_path, monkeypatch, view, selector, filename):
    from ai_sow_lite.cli import execute
    project, request, source, result = ingest(tmp_path)
    entry = result['input_refs'][0]
    package = _review_query_version(project, dependencies=[dict(path=entry['relative_path'], sha256=entry['content_hash'])])
    version = package['manifest']['version_id']
    reads = _review_record_project_reads(monkeypatch, project)
    response = execute(dict(protocol_version='1.0', request_id=request, project_path=str(project),
                            operation='inspect', payload=dict(view=view, selector=selector)))
    assert response['ok'], response
    assert response['result']['matched_count'] == 1
    allowed = {'.ai-sow-lite/project.json', '.ai-sow-lite/current.json', f'.ai-sow-lite/versions/{version}/manifest.json'}
    if filename:
        allowed.add(f'.ai-sow-lite/versions/{version}/{filename}')
    assert set(reads) == allowed
    coverage = response['result']['coverage']
    assert coverage['verification_scope'] == ('selected_file' if filename else 'manifest')
    assert coverage['verified_file_ref'] == (next(r for r in package['manifest']['files'] if r['path'].endswith('/' + filename))
                                             if filename else None)


def test_review_q1_explicit_history_reads_bound_chain_and_only_selected_file(tmp_path, monkeypatch):
    from ai_sow_lite.cli import execute
    first = _review_query_version(tmp_path)
    second = _review_query_version(tmp_path, read_json(tmp_path / '.ai-sow-lite/current.json'))
    old, new = [package['manifest']['version_id'] for package in (first, second)]
    selector = dict(collection='tasks', title='资料查询页', version_id=old)
    request = dict(protocol_version='1.0', request_id=str(uuid4()), project_path=str(tmp_path),
                   operation='inspect', payload=dict(view='objects', selector=selector))
    with monkeypatch.context() as patch:
        reads = _review_record_project_reads(patch, tmp_path)
        response = execute(request)
    assert response['ok'], response
    assert response['result']['selected_version']['version_id'] == old
    assert response['result']['matched_count'] == 1
    assert set(reads) == {'.ai-sow-lite/project.json', '.ai-sow-lite/current.json',
                          f'.ai-sow-lite/versions/{new}/manifest.json',
                          f'.ai-sow-lite/versions/{old}/manifest.json', f'.ai-sow-lite/versions/{old}/model.json'}
    # Actual old bytes must still match the dependency bound by the successor manifest.
    old_manifest = tmp_path / f'.ai-sow-lite/versions/{old}/manifest.json'
    old_manifest.write_bytes(old_manifest.read_bytes() + b'\n')
    rejected = execute(request)
    assert not rejected['ok']
    assert rejected['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'


@pytest.mark.parametrize('collection,filename', [('tasks', 'model.json'), ('pending_items', 'pending-items.json')])
def test_review_q1_selected_corrupt_file_is_not_a_valid_or_empty_result(tmp_path, collection, filename):
    package = _review_query_version(tmp_path)
    path = tmp_path / f".ai-sow-lite/versions/{package['manifest']['version_id']}/{filename}"
    path.write_bytes(path.read_bytes() + b'\n')  # Valid JSON, wrong bound bytes.
    response = inspect(tmp_path, str(uuid4()), 'objects', dict(collection=collection, title='no match'))
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'EVIDENCE_MISSING'


@pytest.mark.parametrize('damage', ['original', 'sow.xlsx'])
def test_review_q1_apply_and_recover_keep_full_integrity_checks(tmp_path, damage):
    from ai_sow_lite.project import _commit_version, StorageError
    project, request, source, result = ingest(tmp_path)
    entry = result['input_refs'][0]
    package = _review_query_version(project, dependencies=[dict(path=entry['relative_path'], sha256=entry['content_hash'])])
    path = project / (entry['relative_path'] if damage == 'original' else
                      f".ai-sow-lite/versions/{package['manifest']['version_id']}/sow.xlsx")
    path.write_bytes(b'corrupt unrelated to pointer or selected objects')
    recovered = run_request(project, request, 'recover', dict(target_request_id=package['request_id']))
    assert not recovered['ok'] and recovered['result']['state'] == 'incompatible'
    with pytest.raises(StorageError) as rejected:
        _commit_version(**package)
    assert rejected.value.diagnostics[0]['code'] == 'EVIDENCE_MISSING'
    current = inspect(project, request, 'current')
    assert current['ok'], current
    assert current['result']['coverage']['verification_scope'] == 'manifest'


@pytest.mark.parametrize('title,expected', [('资料记录条数未提供', 1), ('this question is absent', 0)])
def test_review_q2_pending_title_search_uses_question_without_expanding_empty_results(tmp_path, title, expected):
    package = _review_query_version(tmp_path)
    selector = dict(collection='pending_items', title=title)
    response = inspect(tmp_path, str(uuid4()), 'objects', selector)
    assert response['ok'], response
    result = response['result']
    assert result['matched_count'] == result['returned_count'] == expected
    assert result['selected_version']['version_id'] == package['manifest']['version_id']
    assert result['coverage']['selector'] == selector
    assert result['remaining_count'] == 0 and result['next_cursor'] is None
    if expected:
        assert title in result['items'][0]['question']
    else:
        assert result['items'] == []


def test_utf8_bom_is_decoded_once_without_changing_original_bytes(tmp_path):
    raw = b'\xef\xbb\xbf# PRD\r\nvalue\r\n'
    project, request, source, result = ingest(tmp_path, raw)
    entry = result['input_refs'][0]
    assert entry['encoding'] == 'utf-8-sig'
    selected = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'],
                       locator=dict(kind='text_lines', start_line=1, end_line=1)))
    assert selected['result']['items'][0]['text'] == '# PRD\r\n'
    assert (project / entry['relative_path']).read_bytes() == raw
    assert selected['result']['coverage']['excerpt_hash'] == hashlib.sha256(b'# PRD\r\n').hexdigest()


def test_utf16_bom_is_not_guessed_or_transcoded(tmp_path):
    source = tmp_path / 'utf16.md'
    source.write_bytes('hello'.encode('utf-16'))
    response = run_request(tmp_path / 'project', str(uuid4()), 'ingest', sources_payload(source))
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'INPUT_UNAVAILABLE'
    assert response['result']['reading_refs'] == []
    assert response['result']['input_refs']


def test_single_file_prd_hld_has_exact_directory_and_separate_uses(tmp_path):
    from pathlib import Path
    source = Path(__file__).parent / 'fixtures/history/prd-hld.md'
    payload = sources_payload(source)
    payload['sources'][0].update(material_types=['prd', 'hld'], uses=['to-be-scope', 'to-be-architecture'], use_regions=[
        dict(material_type='prd', use='to-be-scope', locators=[dict(kind='text_lines', start_line=1, end_line=2)]),
        dict(material_type='hld', use='to-be-architecture', locators=[dict(kind='text_lines', start_line=3, end_line=4)])])
    project, request = tmp_path / 'project', str(uuid4())
    response = run_request(project, request, 'ingest', payload)
    assert response['ok'], response
    entry = response['result']['input_refs'][0]
    directory = inspect(project, request, 'regions', {'input_version_id': entry['input_version_id']}, limit=1)
    assert directory['ok'], directory
    assert directory['result']['items'][0]['heading'] == 'PRD'
    assert directory['result']['items'][0]['locator'] == dict(kind='text_lines', start_line=1, end_line=2)
    second = inspect(project, request, 'regions', {'input_version_id': entry['input_version_id']}, cursor=directory['result']['next_cursor'])
    assert second['result']['items'][0]['heading'] == 'HLD'
    assert len(entry['use_regions']) == 2
    assert len(list((project / '.ai-sow-lite/inputs/originals').iterdir())) == 1


def test_review_f1_zero_history_scope_counts_all_returned_members(tmp_path):
    sources = []
    for number in range(400):
        source = tmp_path / f'history-{number}.md'
        source.write_text(f'历史范围 {number}\n', encoding='utf-8')
        sources.append(source)
    payload = sources_payload(*sources)
    for source in payload['sources']:
        source.update(uses=['as-is'], material_types=['prior-sow'])
    project, request = tmp_path / 'project', str(uuid4())
    registered = run_request(project, request, 'ingest', payload)
    assert registered['ok'], registered
    response = inspect(project, request, 'topics', {'historical_label': '不存在', 'uses': ['as-is']}, limit=1)
    assert not response['ok'], response
    assert response['diagnostics'][0]['code'] == 'RESULT_TOO_LARGE'
    assert 'coverage' not in response['result'] and 'items' not in response['result']


def test_review_f3_reuses_actual_baseline_bom_registration_and_source_hash(tmp_path):
    import shutil
    from pathlib import Path
    from ai_sow_lite.contracts import PLUGIN_ROOT
    from ai_sow_lite.project import initialize
    fixture = Path(__file__).parent / 'fixtures/history/legacy-bom-dd1e5b3'
    project, request = tmp_path / 'project', str(uuid4())
    initialize(project, 'new', PLUGIN_ROOT / 'assets/sow-template.xlsx')
    shutil.copytree(fixture / 'inputs', project / '.ai-sow-lite/inputs', dirs_exist_ok=True)
    entry = read_json(fixture / 'inputs/index.json')['items'][0]
    source = project / entry['relative_path']
    reading_ref = read_json(source.parent / 'reading-ref.json')
    before = {p.relative_to(project): p.read_bytes() for p in (project / '.ai-sow-lite/inputs').rglob('*') if p.is_file()}
    response = run_request(project, request, 'ingest', sources_payload(source))
    assert response['ok'], response
    assert response['result']['input_refs'] == [entry]
    assert response['result']['reading_refs'] == [reading_ref]
    assert entry['encoding'] == 'utf-8'
    assert before == {p.relative_to(project): p.read_bytes() for p in (project / '.ai-sow-lite/inputs').rglob('*') if p.is_file()}
    locator = dict(kind='text_lines', start_line=1, end_line=1)
    observed = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'], locator=locator))
    assert observed['ok'], observed
    assert observed['result']['items'][0]['text'] == '\ufeff# PRD\r\n'
    expected_hash = hashlib.sha256(b'\xef\xbb\xbf# PRD\r\n').hexdigest()
    assert observed['result']['coverage']['excerpt_hash'] == expected_hash
    evidence_id = str(uuid4())
    source_ref = dict(input_version_id=entry['input_version_id'], locator=locator, excerpt_hash=expected_hash)
    evidence = dict(id=evidence_id, kind='statement', text='旧版来源正文', source_refs=[source_ref], basis_refs=[], limitations='')
    topic = dict(topic_id=str(uuid4()), topic_version_id=str(uuid4()), title='旧版来源兼容', input_version_ids=[entry['input_version_id']],
                 uses=['to-be-scope'], covered_regions=[source_ref], uncovered_regions=[], evidence_refs=[evidence_id], related_object_ids=[],
                 external_responsibilities='', limitations='', conclusion='保留旧版摘录含义。', historical_items=[])
    path = project / f'.ai-sow-lite/work/generate/{request}/analysis.json'
    write_json(path, dict(schema_version='1.0', evidence=[evidence], topics=[topic], observations=[]))
    adopted = run_request(project, request, 'ingest', dict(kind='analysis', entrypoint='generate', analysis_path=path.relative_to(project).as_posix()))
    assert adopted['ok'], adopted
