"""Real registered prototype sources reach the workbook consumer, stopping before Office."""
import os
from uuid import uuid4

import pytest

from ai_sow_lite import cli, office, workbook
from .support.fixtures import read_json
from .test_inputs import inspect
from .test_prototype_records import (
    analysis_for, check_empty_candidate, observation_draft, ref, registered, submit,
)

# Every case here starts from a registered prototype package, which needs POSIX
# directory-fd / no-follow reads; Windows refuses with OPERATION_UNSUPPORTED.
pytestmark = pytest.mark.skipif(
    not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")),
    reason="Prototype directory ingest requires POSIX fd/no-follow support")


@pytest.mark.parametrize('kind', ['static', 'observation', 'judgment'])
def test_registered_prototype_labels_reach_real_render_boundary(tmp_path, monkeypatch, kind):
    project, request, _, entry, _ = registered(tmp_path)
    if kind == 'static':
        locator = dict(kind='text_lines', path='assets/app.js', start_line=1, end_line=2)
        region = inspect(project, request, 'regions', dict(input_version_id=entry['input_version_id'], locator=locator))
        assert region['ok'], region
        source = dict(input_version_id=entry['input_version_id'], locator=locator,
                      excerpt_hash=region['result']['coverage']['excerpt_hash'])
        analysis = analysis_for(entry, source)
    else:
        path, _, record, source = observation_draft(project, request, entry)
        source['locator']['region'] = 'initial viewport'
        analysis = analysis_for(entry, source, [ref(project, path)])
        if kind == 'judgment':
            identity = str(uuid4())
            analysis['evidence'].append(dict(id=identity, kind='judgment', text='受控来源回溯测试。',
                source_refs=[], basis_refs=[analysis['evidence'][0]['id']], limitations='不是语义或浏览器验收。'))
            analysis['topics'][0]['evidence_refs'].append(identity)
    assert submit(project, request, analysis)['ok']
    checked = check_empty_candidate(project, request, entry, analysis)
    assert checked['ok'], checked
    candidate_ref = checked['result']['candidate_ref']
    candidate = read_json(project / candidate_ref['path'])
    labels = workbook._evidence_labels(project, candidate)
    label = labels[analysis['evidence'][-1]['id']]
    assert 'manifest.json' not in label
    if kind == 'static':
        assert 'assets/app.js；第 1—2 行' in label
    else:
        assert record['observation_id'] in label
        assert source['locator']['attachment'] in label and 'initial viewport' in label

    class OfficeBoundaryReached(Exception):
        pass

    reached = []
    def stop(source, destination):
        assert source.is_file()
        reached.append(source)
        raise OfficeBoundaryReached

    monkeypatch.setattr(office, 'recalculate', stop)
    result = cli.execute(dict(protocol_version='1.0', request_id=request, project_path=str(project), operation='render',
        payload=dict(candidate_path=candidate_ref['path'], check_path=checked['result']['check_ref']['path'],
                     expected_current=None)))
    assert len(reached) == 1, result
    assert not result['ok'] and result['diagnostics'][0]['code'] == 'INTERNAL_ERROR'
    assert not (project / '.ai-sow-lite/current.json').exists()
