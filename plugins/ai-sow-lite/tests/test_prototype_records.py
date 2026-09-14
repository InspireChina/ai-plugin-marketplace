"""Mechanical package/observation consumers; no browser or semantic acceptance claims."""
import hashlib
import os
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from ai_sow_lite.contracts import canonical_json_bytes, schema_validator
from .support.cli import run_request
from .support.fixtures import read_json, write_json
from .test_inputs import sources_payload, inspect

# Prototype ingest needs POSIX directory-fd / no-follow reads; Windows Python
# exposes none of them, so the runtime refuses with OPERATION_UNSUPPORTED and
# these boundary cases have nothing to exercise.
pytestmark = pytest.mark.skipif(
    not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")),
    reason="Prototype directory ingest requires POSIX fd/no-follow support")


def ref(project, path):
    return dict(path=path.relative_to(project).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def package(tmp_path):
    source = tmp_path / 'package'
    (source / 'assets').mkdir(parents=True)
    (source / 'index.html').write_bytes(b'<!doctype html>\r\n<p>local only</p>\n')
    (source / 'assets/app.js').write_bytes(b'// static source; never executed\nthrow Error("must not execute");\n')
    (source / 'assets/state.bin').write_bytes(b'\x00\x01retained')
    return source


def registered(tmp_path):
    source = package(tmp_path)
    project, request = tmp_path / 'project', str(uuid4())
    payload = sources_payload(source)
    payload['sources'][0]['material_types'] = ['prototype']
    response = run_request(project, request, 'ingest', payload)
    assert response['ok'], response
    return project, request, source, response['result']['input_refs'][0], payload


def analysis_for(entry, source, observations=(), count=1):
    evidence = dict(id=str(uuid4()), kind='observation' if source['locator']['kind'] == 'observation' else 'statement',
                    text='合成机械记录，仅测试不可变定位。', source_refs=[source], basis_refs=[], limitations='不证明浏览器观察或业务语义。')
    topics = [dict(topic_id=str(uuid4()), topic_version_id=str(uuid4()), title='机械记录',
                   input_version_ids=[entry['input_version_id']], uses=['to-be-scope'], covered_regions=[source],
                   uncovered_regions=[], evidence_refs=[evidence['id']], related_object_ids=[],
                   external_responsibilities='', limitations='无真实浏览器执行。', conclusion='只登记来源。', historical_items=[])
              for _ in range(count)]
    return dict(schema_version='1.0', topics=topics, evidence=[evidence], observations=list(observations))


def submit(project, request, analysis):
    assert not list(schema_validator('artifacts', 'analysis').iter_errors(analysis))
    path = project / f'.ai-sow-lite/work/generate/{request}/prototype-analysis.json'
    write_json(path, analysis)
    return run_request(project, request, 'ingest', dict(kind='analysis', entrypoint='generate', analysis_path=path.relative_to(project).as_posix()))


def observation_draft(project, request, entry):
    work = project / f'.ai-sow-lite/work/generate/{request}'
    attachment = work / 'capture.txt'
    attachment.write_bytes(b'SYNTHETIC RECORD: not a browser capture\r\n')
    identity = str(uuid4())
    resource = project / Path(entry['relative_path']).parent / 'resources/index.html'
    record = dict(schema_version='1.0', observation_id=identity, input_version_id=entry['input_version_id'],
                  entrypoint='index.html#list', preconditions='合成测试，不打开浏览器。', actions=[],
                  observed_at='2026-09-10T00:00:00Z', result='合成观察记录的存储测试。',
                  resource_refs=[ref(project, resource)], attachments=[ref(project, attachment)], limitations='无浏览器执行；不能作为真实观察验收。')
    path = work / 'observation.json'
    write_json(path, record)
    source = dict(input_version_id=entry['input_version_id'], locator=dict(kind='observation', observation_id=identity, attachment=record['attachments'][0]['path']), excerpt_hash=ref(project, path)['sha256'])
    return path, attachment, record, source


def test_package_exact_manifest_source_locator_and_reuse(tmp_path):
    project, request, source, entry, payload = registered(tmp_path)
    expected = [dict(path=p.relative_to(source).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(source.rglob('*')) if p.is_file()]
    assert entry['format'] == 'prototype' and entry['resources'] == expected
    assert (project / entry['relative_path']).read_bytes() == canonical_json_bytes(expected)
    assert entry['content_hash'] == hashlib.sha256(canonical_json_bytes(expected)).hexdigest()
    directory = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id']), limit=1)
    assert directory['ok'], directory
    assert directory['result']['matched_count'] == 3 and directory['result']['next_cursor']
    assert directory['result']['coverage']['limitations']
    locator = dict(kind='text_lines', path='index.html', start_line=1, end_line=2)
    response = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'], locator=locator))
    assert response['ok'], response
    assert ''.join(i['text'] for i in response['result']['items']).encode() == (source / 'index.html').read_bytes()
    assert response['result']['coverage']['excerpt_hash'] == hashlib.sha256((source / 'index.html').read_bytes()).hexdigest()
    again = run_request(project, request, 'ingest', payload)
    assert again['ok'] and again['result']['input_refs'] == [entry]
    assert len(list((project / '.ai-sow-lite/inputs/originals').iterdir())) == 1
    old = (project / entry['relative_path']).read_bytes()
    (source / 'assets/app.js').write_bytes(b'changed\n')
    payload['sources'][0]['input_id'] = entry['input_id']
    changed = run_request(project, request, 'ingest', payload)
    assert changed['ok'] and changed['result']['input_refs'][0]['input_version_id'] != entry['input_version_id']
    assert (project / entry['relative_path']).read_bytes() == old


def test_observation_roundtrip_preserves_bytes_attachments_and_shared_topics(tmp_path):
    project, request, _, entry, _ = registered(tmp_path)
    path, attachment, record, source = observation_draft(project, request, entry)
    raw, attachment_raw = path.read_bytes(), attachment.read_bytes()
    analysis = analysis_for(entry, source, [ref(project, path)], count=2)
    response = submit(project, request, analysis)
    assert response['ok'], response
    expected_path = f".ai-sow-lite/analysis/observations/{record['observation_id']}/observation.json"
    assert (project / expected_path).read_bytes() == raw
    for topic in analysis['topics']:
        stored = read_json(project / f".ai-sow-lite/analysis/topics/{topic['topic_version_id']}/analysis.json")
        assert stored['observations'] == [dict(path=expected_path, sha256=hashlib.sha256(raw).hexdigest())]
    assert submit(project, request, analysis)['ok']
    shutil.rmtree(path.parent)
    observed = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'], locator=source['locator']))
    assert observed['ok'], observed
    coverage = observed['result']['coverage']
    assert coverage['excerpt_hash'] == source['excerpt_hash']
    assert (project / coverage['attachment_refs'][0]['path']).read_bytes() == attachment_raw
    assert observed['result']['items'][0]['result'] == record['result']
    assert len(list((project / '.ai-sow-lite/analysis/observations').iterdir())) == 1


@pytest.mark.parametrize('damage', ['missing', 'changed', 'wrong-input', 'static-hash', 'unlisted'])
def test_invalid_observation_rejected_with_legal_analysis_and_preserved_current(tmp_path, damage):
    project, request, _, entry, _ = registered(tmp_path)
    path, attachment, record, source = observation_draft(project, request, entry)
    if damage == 'missing':
        attachment.unlink()
    elif damage == 'changed':
        attachment.write_bytes(b'changed')
    elif damage == 'wrong-input':
        record['input_version_id'] = str(uuid4())
        write_json(path, record)
        source['excerpt_hash'] = ref(project, path)['sha256']
    elif damage == 'static-hash':
        source['excerpt_hash'] = entry['content_hash']
    current = project / '.ai-sow-lite/current.json'
    current.write_bytes(b'preserved current sentinel; not claiming an applied version')
    before = current.read_bytes()
    analysis = analysis_for(entry, source, [] if damage == 'unlisted' else [ref(project, path)])
    response = submit(project, request, analysis)
    assert not response['ok'] and 'EVIDENCE_MISSING' in {d['code'] for d in response['diagnostics']}, response
    assert current.read_bytes() == before
    assert (project / entry['relative_path']).is_file()
    assert not (project / '.ai-sow-lite/analysis/index.json').exists()


def check_empty_candidate(project, request, entry, analysis, *, topic_index=None):
    work = project / f'.ai-sow-lite/work/generate/{request}'
    model = dict(schema_version='1.0', epics=[], features=[], stories=[], tasks=[], dependencies=[], lineage=[])
    for name, data in [('model.json', model), ('pending-items.json', dict(schema_version='1.0', items=[])),
                       ('decisions.json', dict(schema_version='1.0', items=[]))]:
        write_json(work / name, data)
    topics = analysis['topics'] if topic_index is None else [analysis['topics'][topic_index]]
    candidate = dict(schema_version='1.0', entrypoint='generate', base_version_id=None,
                     model_path=(work / 'model.json').relative_to(project).as_posix(),
                     pending_items_path=(work / 'pending-items.json').relative_to(project).as_posix(),
                     decisions_path=(work / 'decisions.json').relative_to(project).as_posix(),
                     input_version_ids=list(dict.fromkeys(i for t in topics for i in t['input_version_ids'])),
                     topic_version_ids=[t['topic_version_id'] for t in topics],
                     evidence_ids=list(dict.fromkeys(e for t in topics for e in t['evidence_refs'])),
                     template_hash=read_json(project / '.ai-sow-lite/project.json')['template_hash'])
    path = work / 'candidate.json'
    write_json(path, candidate)
    # Mechanically legal empty candidate only; not a material-sufficiency decision.
    return run_request(project, request, 'check', dict(candidate_path=path.relative_to(project).as_posix(), scope='full', plan_path=None))


def test_all_resources_and_observation_attachments_are_real_check_dependencies(tmp_path):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, record, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source, [ref(project, path)])
    assert submit(project, request, analysis)['ok']
    checked = check_empty_candidate(project, request, entry, analysis)
    assert checked['ok'], checked
    report = read_json(project / checked['result']['check_ref']['path'])
    deps = {r['path']: r['sha256'] for r in report['dependencies']}
    area = Path(entry['relative_path']).parent.as_posix()
    for name in ['index.html', 'assets/app.js', 'assets/state.bin']:
        actual = project / f'{area}/resources/{name}'
        assert deps[actual.relative_to(project).as_posix()] == hashlib.sha256(actual.read_bytes()).hexdigest()
    obs_area = f".ai-sow-lite/analysis/observations/{record['observation_id']}"
    assert f'{obs_area}/observation.json' in deps and f'{obs_area}/attachments/0/capture.txt' in deps
    assert f'{obs_area}/registration-ref.json' in deps
    original = project / f'{area}/resources/assets/state.bin'
    original.write_bytes(b'changed unused binary')
    failed = check_empty_candidate(project, request, entry, analysis)
    assert not failed['ok'] and 'EVIDENCE_MISSING' in {d['code'] for d in failed['diagnostics']}


@pytest.mark.parametrize('damage', ['attachment-missing', 'attachment-changed', 'attachment-symlink', 'observation-changed', 'resource-symlink', 'resource-escape'])
def test_registered_provenance_damage_is_rejected_by_check(tmp_path, damage):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, record, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source, [ref(project, path)])
    assert submit(project, request, analysis)['ok']
    assert check_empty_candidate(project, request, entry, analysis)['ok']
    root = project / f".ai-sow-lite/analysis/observations/{record['observation_id']}"
    if damage.startswith('attachment'):
        target = root / 'attachments/0/capture.txt'
        if damage == 'attachment-changed':
            target.write_bytes(b'altered')
        else:
            raw = target.read_bytes()
            target.unlink()
            if damage == 'attachment-symlink':
                outside = tmp_path / 'same.txt'
                outside.write_bytes(raw)
                target.symlink_to(outside)
    elif damage == 'observation-changed':
        (root / 'observation.json').write_bytes(b'{}')
    elif damage == 'resource-symlink':
        target = project / Path(entry['relative_path']).parent / 'resources/index.html'
        outside = tmp_path / 'same.html'
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
    else:
        index = read_json(project / '.ai-sow-lite/inputs/index.json')
        index['items'][0]['resources'][0]['path'] = '../escaped.js'
        write_json(project / '.ai-sow-lite/inputs/index.json', index)
    failed = check_empty_candidate(project, request, entry, analysis)
    assert not failed['ok'] and 'EVIDENCE_MISSING' in {d['code'] for d in failed['diagnostics']}, failed


@pytest.mark.parametrize('member', ['file-link', 'directory-link', 'fifo', 'colon', 'root-link', 'depth', 'members', 'bytes'])
def test_bounded_directory_rejects_unsafe_or_oversize_members(tmp_path, member):
    import os
    source = package(tmp_path)
    if member in ('file-link', 'directory-link'):
        (source / 'linked').symlink_to(source / ('index.html' if member == 'file-link' else 'assets'))
    elif member == 'root-link':
        link = tmp_path / 'linked'
        link.symlink_to(source, target_is_directory=True)
        source = link
    elif member == 'fifo':
        os.mkfifo(source / 'pipe')
    elif member == 'colon':
        (source / 'bad:name.js').write_bytes(b'ignored')
    elif member == 'depth':
        (source / '/'.join(['deep'] * 17)).mkdir(parents=True)
    elif member == 'members':
        for i in range(2049):
            (source / str(i)).mkdir()
    else:
        with (source / 'oversize.bin').open('wb') as stream:
            stream.truncate(50 * 1024 * 1024 + 1)
    response = run_request(tmp_path / 'project', str(uuid4()), 'ingest', sources_payload(source))
    expected = 'RESULT_TOO_LARGE' if member in ('depth', 'members', 'bytes') else 'PATH_UNSAFE'
    assert not response['ok'] and expected in {d['code'] for d in response['diagnostics']}, response
    assert read_json(tmp_path / 'project/.ai-sow-lite/inputs/index.json')['items'] == []


def test_prototype_use_regions_keep_exact_path_and_long_line_paginates(tmp_path):
    project, request, source, entry, payload = registered(tmp_path)
    locator = dict(kind='text_lines', path='assets/app.js', start_line=1, end_line=2)
    payload['sources'][0]['use_regions'] = [dict(material_type='prototype', use='to-be-scope', locators=[locator])]
    response = run_request(project, request, 'ingest', payload)
    assert response['ok'], response
    assert response['result']['input_refs'][0]['use_regions'][0]['locators'] == [locator]
    (source / 'index.html').write_text('中' * 50000 + '\r\n', encoding='utf-8', newline='')
    payload['sources'][0]['input_id'] = entry['input_id']
    response = run_request(project, request, 'ingest', payload)
    assert response['ok']
    version = response['result']['input_refs'][0]['input_version_id']
    selector = dict(input_version_id=version, locator=dict(kind='text_lines', path='index.html', start_line=1, end_line=1))
    cursor, fragments = None, []
    for _ in range(30):
        reply = inspect(project, request, 'regions', selector, cursor=cursor)
        assert reply['ok'], reply
        assert len(canonical_json_bytes(reply)) <= 64 * 1024
        fragments += [i['text'] for i in reply['result']['items']]
        cursor = reply['result']['next_cursor']
        if cursor is None:
            break
    assert cursor is None and ''.join(fragments) == '中' * 50000 + '\r\n'


def test_observation_id_collision_cannot_replace_existing_bytes(tmp_path):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, record, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source, [ref(project, path)])
    assert submit(project, request, analysis)['ok']
    record['result'] = '不同含义不能复用原 ID。'
    write_json(path, record)
    source['excerpt_hash'] = ref(project, path)['sha256']
    changed = analysis_for(entry, source, [ref(project, path)])
    reply = submit(project, request, changed)
    assert not reply['ok'] and 'IDENTITY_CONFLICT' in {d['code'] for d in reply['diagnostics']}, reply


def test_new_observation_requires_new_topic_version(tmp_path):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, _, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source, [ref(project, path)])
    assert submit(project, request, analysis)['ok']
    path.rename(path.with_name('first.json'))
    analysis['observations'] = [ref(project, path.with_name('first.json'))]
    other, _, _, _ = observation_draft(project, request, entry)
    analysis['observations'].append(ref(project, other))
    reply = submit(project, request, analysis)
    assert not reply['ok'] and 'IDENTITY_CONFLICT' in {d['code'] for d in reply['diagnostics']}, reply


def test_split_topics_retain_only_their_adopted_input_observations(tmp_path):
    project, request, source_dir, entry, payload = registered(tmp_path)
    path, _, _, source = observation_draft(project, request, entry)
    first = analysis_for(entry, source, [ref(project, path)])
    path.rename(path.with_name('first.json'))
    first['observations'] = [ref(project, path.with_name('first.json'))]
    (source_dir / 'index.html').write_bytes(b'<p>second version</p>\n')
    second_entry = run_request(project, request, 'ingest', payload)['result']['input_refs'][0]
    path, _, _, source2 = observation_draft(project, request, second_entry)
    second = analysis_for(second_entry, source2, [ref(project, path)])
    combined = {key: first[key] + second[key] for key in ('topics', 'evidence', 'observations')}
    combined['schema_version'] = '1.0'
    assert submit(project, request, combined)['ok']
    checked = check_empty_candidate(project, request, entry, combined, topic_index=0)
    assert checked['ok'], checked
    report = read_json(project / checked['result']['check_ref']['path'])
    assert not any(second_entry['input_version_id'] in d['path'] for d in report['dependencies'])


def test_executable_reference_consumer_roundtrip(tmp_path):
    import re
    import sys
    project, request, _, entry, _ = registered(tmp_path)
    path, attachment, record, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source)
    plugin = Path(__file__).resolve().parents[1]
    guide = (plugin / 'references/prototype-inputs.md').read_text(encoding='utf-8')
    blocks = re.findall(r'```python\n(.*?)\n```', guide, flags=re.S)
    assert len(blocks) == 1
    namespace = dict(project=project, request_id=request, python=sys.executable,
                     lite_script=plugin / 'scripts/lite.py', analysis=analysis,
                     observation_path=path, observation_input_version_id=entry['input_version_id'])
    exec(compile(blocks[0], 'prototype-inputs.md example', 'exec'), namespace)
    observed = namespace['observed_region']
    assert observed['items'][0] == record
    assert observed['coverage']['excerpt_hash'] == ref(project, path)['sha256']
    copied = project / observed['coverage']['attachment_refs'][0]['path']
    assert copied.read_bytes() == attachment.read_bytes()
    assert check_empty_candidate(project, request, entry, analysis)['ok']


def test_same_workbook_history_and_draft_regions_have_separate_consumers(tmp_path):
    from openpyxl import Workbook
    source = tmp_path / 'history-and-draft.xlsx'
    book = Workbook()
    history = book.active
    history.title = '历史'
    history.append(['范围', '说明'])
    history.append(['订单查询', '上一期只交付订单列表。'])
    draft = book.create_sheet('本期草稿')
    draft.append(['范围', '说明'])
    draft.append(['订单详情', '本期草稿拟补订单详情，需结合 PRD/HLD 判断。'])
    book.save(source)
    book.close()
    project, request = tmp_path / 'project', str(uuid4())
    payload = sources_payload(source, project_type='existing')
    payload['sources'][0].update(material_types=['prior-sow', 'draft'], uses=['as-is', 'to-be-scope'])
    first = run_request(project, request, 'ingest', payload)
    assert first['ok'], first
    entry = first['result']['input_refs'][0]
    reading = read_json(project / first['result']['reading_refs'][0]['path'])
    analyses = []
    for sheet, role, use, expected in [('历史', 'prior-sow', 'as-is', '订单查询'), ('本期草稿', 'draft', 'to-be-scope', '订单详情')]:
        region = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'],
                         locator=dict(kind='xlsx_range', sheet=sheet, range='A2:B2', read_id=reading['read_id'])))
        assert region['ok'], region
        result = region['result']
        assert result['items'][0]['value']['value'] == expected
        locator = result['coverage']['locator']
        payload['sources'][0]['use_regions'].append(dict(material_type=role, use=use, locators=[locator]))
        evidence_source = dict(input_version_id=entry['input_version_id'], locator=locator,
                               excerpt_hash=result['coverage']['excerpt_hash'])
        analysis = analysis_for(entry, evidence_source)
        analysis['topics'][0]['uses'] = [use]
        analyses.append(analysis)
    again = run_request(project, request, 'ingest', payload)
    assert again['ok'] and again['result']['reading_refs'] == first['result']['reading_refs']
    assert len(list((project / '.ai-sow-lite/inputs/originals').iterdir())) == 1
    assert len(again['result']['input_refs'][0]['use_regions']) == 2
    for analysis in analyses:
        assert submit(project, request, analysis)['ok']
    history_topics = inspect(project, request, 'topics', {'uses': ['as-is']})['result']['items']
    draft_topics = inspect(project, request, 'topics', {'uses': ['to-be-scope']})['result']['items']
    assert [t['topic_version_id'] for t in history_topics] == [analyses[0]['topics'][0]['topic_version_id']]
    assert [t['topic_version_id'] for t in draft_topics] == [analyses[1]['topics'][0]['topic_version_id']]
    assert history_topics[0]['covered_regions'][0]['locator']['sheet'] == '历史'
    assert draft_topics[0]['covered_regions'][0]['locator']['sheet'] == '本期草稿'


@pytest.mark.parametrize('damage', ['raw-analysis', 'split-analysis', 'topic-registration'])
def test_check_binds_observation_topic_to_original_analysis_registration(tmp_path, damage):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, _, source = observation_draft(project, request, entry)
    analysis = analysis_for(entry, source, [ref(project, path)])
    registered_analysis = submit(project, request, analysis)
    assert registered_analysis['ok']
    assert check_empty_candidate(project, request, entry, analysis)['ok']
    topic_area = project / f".ai-sow-lite/analysis/topics/{analysis['topics'][0]['topic_version_id']}"
    if damage == 'raw-analysis':
        target = project / registered_analysis['result']['analysis_ref']['path']
        target.write_bytes(target.read_bytes() + b' ')
    elif damage == 'split-analysis':
        target = topic_area / 'analysis.json'
        stored = read_json(target)
        stored['evidence'][0]['text'] = 'changed without new immutable identity'
        write_json(target, stored)
    else:
        (topic_area / 'registration-ref.json').unlink()
    reply = check_empty_candidate(project, request, entry, analysis)
    assert not reply['ok'] and 'EVIDENCE_MISSING' in {d['code'] for d in reply['diagnostics']}, reply


def test_oversized_observation_inspect_points_to_whole_saved_record(tmp_path):
    project, request, _, entry, _ = registered(tmp_path)
    path, _, record, source = observation_draft(project, request, entry)
    record['result'] = '长记录' * 15000
    write_json(path, record)
    source['excerpt_hash'] = ref(project, path)['sha256']
    assert submit(project, request, analysis_for(entry, source, [ref(project, path)]))['ok']
    reply = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'], locator=source['locator']))
    assert not reply['ok'] and reply['diagnostics'][0]['code'] == 'RESULT_TOO_LARGE'
    assert reply['diagnostics'][0]['preserved_paths'] == [f".ai-sow-lite/analysis/observations/{record['observation_id']}/observation.json"]
    assert len(canonical_json_bytes(reply)) <= 64 * 1024
