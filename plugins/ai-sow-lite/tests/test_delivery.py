"""I1.5 public delivery acceptance with real ingested sources and Office bytes."""
import hashlib
from dataclasses import replace
import json
import os
import shutil
import subprocess
import sys

import pytest

from .support.cli import run_request
from .support import fixtures


@pytest.mark.office
def test_first_delivery_and_retry(tmp_path):
    # A fabricated prepared flag, skipped full check, or duplicate apply must fail.
    assert callable(getattr(fixtures, 'prepare_case', None)), 'prepare_case(Case) is required'
    case = fixtures.build_ingested_case(tmp_path / '合成项目 with spaces')
    prepared = fixtures.prepare_case(case)
    assert not (case.project / '.ai-sow-lite/current.json').exists()
    packet = fixtures.read_json(case.project / prepared['prepared_ref']['path'])
    checked = fixtures.read_json(case.project / packet['check_ref']['path'])
    assert checked['scope'] == 'full' and checked['valid_for_render'] is True
    payload = dict(entrypoint='generate', prepared_path=prepared['prepared_ref']['path'],
                   expected_current=None, plan_path=None)
    first = run_request(case.project, case.request_id, 'apply', payload)
    assert first['ok'], first
    before = {p.relative_to(case.project): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (case.project / '.ai-sow-lite/versions').rglob('*') if p.is_file()}
    again = run_request(case.project, case.request_id, 'apply', payload)
    assert again['ok'], again
    assert again['result']['idempotent'] is True
    assert first['result']['applied_version'] == again['result']['applied_version'] == prepared['version_id']
    assert before == {p.relative_to(case.project): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (case.project / '.ai-sow-lite/versions').rglob('*') if p.is_file()}
    # Lost transient preparation may be retried using the sealed invocation.
    shutil.rmtree((case.project / prepared['prepared_ref']['path']).parent)
    lost = run_request(case.project, case.request_id, 'apply', payload)
    assert lost['ok'] and lost['result']['idempotent'], lost
    assert lost['result']['applied_version'] == first['result']['applied_version']
    assert before == {p.relative_to(case.project): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (case.project / '.ai-sow-lite/versions').rglob('*') if p.is_file()}
    recovered = run_request(case.project, case.request_id, 'recover', dict(target_request_id=case.request_id))
    assert recovered['ok'] and recovered['result']['state'] == 'applied', recovered
    assert recovered['result']['applied_version'] == first['result']['applied_version']


@pytest.mark.office
def test_copy_smoke_delivers_and_removes_its_temporary_workspace(tmp_path):
    # Copy smoke must execute from its own locked venv, audit child reads, and clean up.
    environment = dict(os.environ, TMPDIR=str(tmp_path), TMP=str(tmp_path), TEMP=str(tmp_path))
    process = subprocess.run([sys.executable, str(fixtures.PLUGIN / 'tests/support/smoke_plugin.py'),
                              '--copy-plugin'], cwd=tmp_path, env=environment,
                             capture_output=True, text=True, timeout=240)
    assert process.returncode == 0, (process.stdout, process.stderr)
    result = json.loads(process.stdout)
    assert result['ok'] and result['copied'] and result['locked_environment']
    assert result['cleaned'] and not list(tmp_path.iterdir())
    assert result['delivery']['idempotent'] and result['delivery']['recovered'] == 'applied'
    assert result['delivery']['pending_count'] == 1 and result['delivery']['details'] is True
    assert result['delivery']['template_hash'] == '6abc55d44bc66476a60c2251e18c0dfdb66709e07539c246dfdec3a0373f5332'
    assert result['delivery']['dependency_counts'] == dict(identity=1, originals=3, readings=6, analysis=2, template=1,
                                                         observations=0, history=0)
    assert result['delivery']['tool_duration_ns'] > 0
    assert result['delivery']['total_tokens'] is None
    assert result['audit']['violations'] == 0 and result['audit']['processes'] >= 8
    assert result['audit']['read_counts']['plugin'] > 0 and result['audit']['read_counts']['project'] > 0
    assert result['audit']['office_conversions'] == 1


@pytest.fixture(scope='module')
def real_prepared(tmp_path_factory):
    """Exactly one real Office package, cloned before each deterministic failure."""
    case = fixtures.build_ingested_case(tmp_path_factory.mktemp('real-delivery') / 'project')
    return case, fixtures.prepare_case(case)


@pytest.fixture
def delivery_case(real_prepared, tmp_path):
    source, prepared = real_prepared
    project = tmp_path / '故障项目 with spaces'
    shutil.copytree(source.project, project)
    return replace(source, project=project, candidate_path=project / source.candidate_path.relative_to(source.project)), prepared


@pytest.mark.office
@pytest.mark.parametrize('boundary,activated', [('prepared', False), ('installed', False),
    ('before_replace', False), ('after_replace', True), ('response', True)])
def test_real_package_process_death_recovers_activation_fact(delivery_case, boundary, activated):
    """I1.2's five barriers, now reached through genuine public apply verification."""
    import threading
    from ai_sow_lite.project import commit_lock
    from .support.smoke_plugin import verify_delivery
    case, prepared = delivery_case
    payload = dict(entrypoint='generate', prepared_path=prepared['prepared_ref']['path'],
                   expected_current=None, plan_path=None)
    request = case.file('fault-request.json')
    fixtures.write_json(request, dict(protocol_version='1.0', request_id=case.request_id,
        project_path=str(case.project), operation='apply', payload=payload))
    # Instrument only a test child, with the same exact storage boundaries as I1.2.
    # The normal CLI and real verifier still execute; no production failpoint exists.
    script = r'''
import sys
from ai_sow_lite import cli, project as storage
boundary = sys.argv[2]
name = {'prepared':'_prepare_version', 'installed':'_install_version',
        'before_replace':'replace_current', 'after_replace':'replace_current', 'response':'_applied_result'}[boundary]
original = getattr(storage, name)
def barrier(*args, **kwargs):
    if boundary in ('before_replace', 'response'):
        print('READY', flush=True)
        sys.stdin.readline()
    result = original(*args, **kwargs)
    if boundary not in ('before_replace', 'response'):
        print('READY', flush=True)
        sys.stdin.readline()
    return result
def no_office(event, args):
    if event == 'subprocess.Popen':
        raise AssertionError('Apply must not launch Office or any other subprocess')
sys.addaudithook(no_office)
setattr(storage, name, barrier)
raise SystemExit(cli.main(['--request', sys.argv[1]]))
'''
    environment = dict(os.environ, PYTHONPATH=str(fixtures.PLUGIN / 'runtime'))
    child = subprocess.Popen([sys.executable, '-c', script, str(request), boundary], cwd=case.project,
                             env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    watchdog = threading.Timer(30, child.kill)
    watchdog.start()
    try:
        assert child.stdout.readline().strip() == 'READY', child.stderr.read()
        child.kill()
        child.wait(timeout=10)
        assert child.returncode != 0
        assert child.stderr.read() == ''
    finally:
        watchdog.cancel()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()
    current_path = case.project / '.ai-sow-lite/current.json'
    assert current_path.exists() is activated
    recovered = run_request(case.project, case.request_id, 'recover', dict(target_request_id=case.request_id))
    assert recovered['ok'], recovered
    assert recovered['result']['state'] == ('applied' if activated else 'draft')
    assert recovered['result']['applied_version'] == (prepared['version_id'] if activated else None)
    with commit_lock(case.project):  # Process death releases the kernel lock.
        pass
    retried = run_request(case.project, case.request_id, 'apply', payload)
    assert retried['ok'], retried
    assert retried['result']['idempotent'] is activated
    assert retried['result']['applied_version'] == prepared['version_id']
    assert [p.name for p in (case.project / '.ai-sow-lite/versions').iterdir()] == [prepared['version_id']]
    verify_delivery(case, prepared, retried['result'])


@pytest.mark.office
@pytest.mark.parametrize('category', ['identity', 'original', 'reading', 'excerpt', 'topic', 'registration', 'template'])
@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_real_delivery_rejects_damaged_dependency(delivery_case, category, damage):
    case, prepared = delivery_case
    first = run_request(case.project, case.request_id, 'apply', dict(entrypoint='generate',
        prepared_path=prepared['prepared_ref']['path'], expected_current=None, plan_path=None))
    assert first['ok'], first
    manifest = fixtures.read_json(case.project / first['result']['manifest_ref']['path'])
    selectors = {'identity': lambda p: p.endswith('/project.json'),
        'original': lambda p: '/inputs/originals/' in p,
        'reading': lambda p: p.endswith('/reading.json'), 'excerpt': lambda p: p.endswith('/text.txt'),
        'topic': lambda p: '/analysis/topics/' in p, 'registration': lambda p: '/analysis/registrations/' in p,
        'template': lambda p: p.endswith('/sow-template.xlsx')}
    ref = next(r for r in manifest['dependencies'] if selectors[category](r['path']))
    path = case.project / ref['path']
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'corrupt dependency')
    before = (case.project / '.ai-sow-lite/current.json').read_bytes()
    result = run_request(case.project, case.request_id, 'recover', dict(target_request_id=case.request_id))
    assert not result['ok'] and result['result']['state'] == 'incompatible', result
    assert result['result']['applied_version'] is None and result['diagnostics']
    assert (case.project / '.ai-sow-lite/current.json').read_bytes() == before


def test_copy_read_audit_rejects_external_file_and_symlink(tmp_path):
    workspace = tmp_path / 'workspace'
    (workspace / 'audit').mkdir(parents=True)
    outside = tmp_path / 'other-plugin.py'
    outside.write_text('outside plugin', encoding='utf-8')
    alias = workspace / 'linked-runtime.py'
    alias.symlink_to(outside)
    script = '''
import sys
from pathlib import Path
from tests.support.smoke_plugin import install_read_audit
install_read_audit()
for path in sys.argv[1:]:
    try:
        Path(path).read_bytes()
    except PermissionError:
        continue
    raise AssertionError('Audit allowed an external read')
'''
    environment = dict(os.environ, LITE_SMOKE_WORKSPACE=str(workspace), PYTHONPATH=str(fixtures.PLUGIN))
    result = subprocess.run([sys.executable, '-c', script, str(outside), str(alias)],
                            cwd=workspace, env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    report = json.loads(next((workspace / 'audit').glob('*.json')).read_text())
    assert report['violations'] == 2
