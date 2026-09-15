"""A newly observed prototype can support a bounded revision after actual registration."""
import os
from pathlib import Path
from uuid import uuid4

import pytest

from .support.clarify import clarify_case, delivered_baseline, edit_draft, check_edits
from .support.cli import run_request
from .support.fixtures import read_json, write_json
from .test_prototype_records import package, ref, analysis_for

# Each case registers a real prototype package first, which needs POSIX
# directory-fd / no-follow reads; Windows refuses with OPERATION_UNSUPPORTED.
pytestmark = pytest.mark.skipif(
    not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")),
    reason="Prototype directory ingest requires POSIX fd/no-follow support")


def observed_revision(case, tmp_path):
    project, request = case['project'], case['request_id']
    source = package(tmp_path)
    reply = run_request(project, request, 'ingest', dict(kind='sources', entrypoint='clarify',
        project_type='new', sources=[dict(source_path=str(source), input_id=None,
            material_types=['prototype'], uses=['to-be-scope'], use_regions=[])]))
    assert reply['ok'], reply
    entry = reply['result']['input_refs'][0]
    work = project / f'.ai-sow-lite/work/clarify/{request}'
    attachment = work / 'capture.txt'
    attachment.write_bytes(b'SYNTHETIC observation, not a real browser capture\n')
    identity = str(uuid4())
    record = dict(schema_version='1.0', observation_id=identity, input_version_id=entry['input_version_id'],
        entrypoint='index.html', preconditions='Controlled storage test.', actions=[],
        observed_at='2026-09-10T00:00:00Z', result='Observed prototype text used by this revision.',
        resource_refs=[ref(project, project / Path(entry['relative_path']).parent / 'resources/index.html')],
        attachments=[ref(project, attachment)], limitations='Synthetic; no claim of real UI behavior.')
    original = work / 'observation.json'
    write_json(original, record)
    evidence_source = dict(input_version_id=entry['input_version_id'], locator=dict(kind='observation',
        observation_id=identity, attachment=ref(project, attachment)['path']), excerpt_hash=ref(project, original)['sha256'])
    analysis = analysis_for(entry, evidence_source, [ref(project, original)])
    analysis['topics'][0]['related_object_ids'] = [case['ids']['S-01']]
    ap = work / 'observation-analysis.json'
    write_json(ap, analysis)
    result = run_request(project, request, 'ingest', dict(kind='analysis', entrypoint='clarify',
        analysis_path=ap.relative_to(project).as_posix()))
    assert result['ok'], result
    draft = edit_draft(case, [dict(op='replace', collection='stories', object_id=case['ids']['S-01'],
        field='notes', value='本次备注采用已登记的原型观察。')], [entry['input_version_id']])
    draft['additional_refs'].update(topic_version_ids=result['result']['topic_version_ids'],
                                    evidence_ids=result['result']['evidence_ids'])
    draft['read_boundary']['topic_version_ids'] = result['result']['topic_version_ids']
    return draft, original, attachment, result['result']['topic_version_ids'][0]


def test_new_observation_topic_supports_clarify_with_immutable_dependencies(clarify_case, tmp_path):
    case = clarify_case
    draft, original, attachment, topic = observed_revision(case, tmp_path)
    reply = check_edits(case, draft)
    assert reply['ok'], reply
    result = reply['result']
    candidate = read_json(case['project'] / result['candidate_ref']['path'])
    assert topic in candidate['topic_version_ids']
    check = read_json(case['project'] / result['check_ref']['path'])
    paths = {r['path'] for r in check['dependencies']}
    assert f'.ai-sow-lite/analysis/topics/{topic}/registration-ref.json' in paths
    assert any('/analysis/observations/' in p and p.endswith('/observation.json') for p in paths)
    assert any('/analysis/observations/' in p and '/attachments/' in p for p in paths)
    assert original.relative_to(case['project']).as_posix() not in paths
    assert attachment.relative_to(case['project']).as_posix() not in paths
    original.unlink()
    attachment.unlink()
    assert check_edits(case, draft)['ok']  # registered copies survive work cleanup
    assert read_json(case['project'] / '.ai-sow-lite/current.json') == case['current']


@pytest.mark.parametrize('damage', ['registration', 'observation', 'attachment'])
def test_clarify_observation_dependencies_cannot_be_replaced(clarify_case, tmp_path, damage):
    case = clarify_case
    draft, _, _, topic = observed_revision(case, tmp_path)
    project = case['project']
    if damage == 'registration':
        path = project / f'.ai-sow-lite/analysis/topics/{topic}/registration-ref.json'
        path.unlink()
    else:
        stored = read_json(project / f'.ai-sow-lite/analysis/topics/{topic}/analysis.json')
        path = project / stored['observations'][0]['path']
        if damage == 'attachment':
            path = path.parent / 'attachments/0/capture.txt'
        path.write_bytes(b'changed actual observation source\n')
    reply = check_edits(case, draft)
    assert not reply['ok']
    assert any(d['code'] == 'EVIDENCE_MISSING' for d in reply['diagnostics']), reply
    assert read_json(project / '.ai-sow-lite/current.json') == case['current']
