"""Real clarify packages at serial, cancellation and recovery boundaries."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

from ai_sow_lite import cli, office, project as storage
from ai_sow_lite.contracts import PLUGIN_ROOT
from .support.clarify import (delivered_baseline, prepared_seed, prepared_case, edit_draft, serial_seed,
                              clarify_case, feedback, check_edits)
from .support.fixtures import read_json, write_json


@pytest.fixture(autouse=True)
def forbid_office(monkeypatch, request):
    if request.node.get_closest_marker('office'):
        return
    def forbidden(*args, **kwargs):
        pytest.fail('This lifecycle test must consume existing real prepared output')
    monkeypatch.setattr(office, 'recalculate', forbidden)


def invoke(case, operation, payload):
    # Public envelope/dispatch with real validation and storage; local hooks remain observable.
    return cli.execute(dict(protocol_version='1.0', request_id=case['request_id'],
                            project_path=str(case['project']), operation=operation, payload=payload))


def apply_payload(case):
    return dict(entrypoint='clarify', prepared_path=case['prepared_ref']['path'],
                plan_path=case['confirmed_path'], expected_current=case['current'])


def old_bytes(project):
    return {p.relative_to(project).as_posix(): p.read_bytes()
            for p in (project / '.ai-sow-lite/versions').rglob('*') if p.is_file()}


def assert_retained(project, before):
    assert all((project / relative).read_bytes() == raw for relative, raw in before.items())


def recover_once(case):
    return invoke(case, 'recover', dict(target_request_id=case['request_id']))


@pytest.mark.parametrize('boundary', ['before_render', 'before_lock', 'after_pointer'])
def test_real_clarify_cancellation_obeys_the_visible_commit_point(prepared_case, monkeypatch, boundary):
    case = prepared_case
    project, request_id = case['project'], case['request_id']
    before, pointer = old_bytes(project), (project / '.ai-sow-lite/current.json').read_bytes()
    if boundary == 'before_render':
        storage.cancel_request(project, request_id, 'clarify')
        result = invoke(case, 'render', dict(candidate_path=case['result']['candidate_ref']['path'],
            check_path=case['result']['check_ref']['path'], expected_current=case['current']))
    else:
        if boundary == 'before_lock':
            original = storage.commit_lock
            @contextmanager
            def observed_cancel(root):
                storage.cancel_request(root, request_id, 'clarify')
                with original(root):
                    yield
            monkeypatch.setattr(storage, 'commit_lock', observed_cancel)
        else:
            original = storage.replace_current
            def cancel_after_replace(root, current):
                original(root, current)
                storage.cancel_request(project, request_id, 'clarify')
            monkeypatch.setattr(storage, 'replace_current', cancel_after_replace)
        result = invoke(case, 'apply', apply_payload(case))
    recovered = recover_once(case)
    assert recovered['ok'], recovered
    assert_retained(project, before)
    if boundary == 'after_pointer':
        assert result['ok'], result
        assert recovered['result']['state'] == 'applied'
        assert recovered['result']['applied_version'] == result['result']['applied_version']
        assert read_json(project / '.ai-sow-lite/current.json')['version_id'] == result['result']['applied_version']
    else:
        assert not result['ok'] and 'REQUEST_CANCELLED' in {d['code'] for d in result['diagnostics']}
        assert recovered['result']['state'] == 'cancelled'
        assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer


def test_real_clarify_busy_lock_keeps_prepared_and_allows_same_request_retry(prepared_case):
    case = prepared_case
    before, pointer = old_bytes(case['project']), (case['project'] / '.ai-sow-lite/current.json').read_bytes()
    prepared = (case['project'] / case['prepared_ref']['path']).read_bytes()
    with storage.commit_lock(case['project']):
        rejected = invoke(case, 'apply', apply_payload(case))
    assert not rejected['ok'] and 'WRITE_BUSY' in {d['code'] for d in rejected['diagnostics']}
    assert (case['project'] / '.ai-sow-lite/current.json').read_bytes() == pointer
    assert (case['project'] / case['prepared_ref']['path']).read_bytes() == prepared
    assert recover_once(case)['result']['state'] == 'draft'
    applied = invoke(case, 'apply', apply_payload(case))
    assert applied['ok'], applied
    assert_retained(case['project'], before)


@pytest.mark.parametrize('boundary', ['before_apply', 'after_commit_before_response'])
def test_real_clarify_child_interruption_recovers_once_without_recalculation(prepared_case, boundary):
    """Actual child kill; barriers are controlled callbacks, not simulated host UI cancellation."""
    case = prepared_case
    project = case['project']
    before, pointer = old_bytes(project), (project / '.ai-sow-lite/current.json').read_bytes()
    request = dict(protocol_version='1.0', request_id=case['request_id'], project_path=str(project),
                   operation='apply', payload=apply_payload(case))
    path = project.parent / 'interrupted-apply.json'
    write_json(path, request)
    script = r'''
import sys
from pathlib import Path
from ai_sow_lite import cli, office, project as storage
from ai_sow_lite.contracts import load_json
request, boundary = load_json(Path(sys.argv[1])), sys.argv[2]
def forbidden(*args, **kwargs):
    raise AssertionError('Existing prepared package must not call Office')
office.recalculate = forbidden
def barrier():
    print('AT_BOUNDARY', flush=True)
    sys.stdin.readline()
if boundary == 'before_apply':
    barrier()
else:
    original = storage._commit_version
    def committed(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier()
        return result
    storage._commit_version = committed
cli.execute(request)
'''
    env = dict(os.environ, PYTHONPATH=str(PLUGIN_ROOT / 'runtime'), PYTHONDONTWRITEBYTECODE='1')
    child = subprocess.Popen([sys.executable, '-c', script, str(path), boundary], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    watchdog = threading.Timer(30, child.kill)
    watchdog.start()
    try:
        assert child.stdout.readline().strip() == 'AT_BOUNDARY'
        child.kill()
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode != 0 and stdout == '' and stderr == ''
    finally:
        watchdog.cancel()
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    recovered = recover_once(case)
    committed = boundary == 'after_commit_before_response'
    assert recovered['ok'] and recovered['result']['state'] == ('applied' if committed else 'draft')
    assert not list((project / '.ai-sow-lite/work/clarify' / case['request_id']).glob('cancelled.json'))
    if not committed:
        assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer
    # Real child death must release the lock; retry is exactly the same invocation.
    with storage.commit_lock(project):
        pass
    repeated = invoke(case, 'apply', apply_payload(case))
    assert repeated['ok'] and repeated['result']['idempotent'] == committed, repeated
    assert_retained(project, before)


def test_real_clarify_post_commit_observation_failure_keeps_applied_fact(prepared_case, monkeypatch):
    from ai_sow_lite import telemetry
    case = prepared_case
    append = telemetry.append_event
    failures = []
    def fail_end(project, event):
        if event['event_type'] == 'lifecycle' and event['data'].get('phase') == 'end':
            assert read_json(project / '.ai-sow-lite/current.json') != case['current']
            failures.append(event['event_id'])
            raise OSError('controlled observation failure after real apply')
        return append(project, event)
    monkeypatch.setattr(telemetry, 'append_event', fail_end)
    applied = invoke(case, 'apply', apply_payload(case))
    assert applied['ok'] and failures, applied
    assert applied['result']['observation']['recording'] == 'degraded'
    pointer = (case['project'] / '.ai-sow-lite/current.json').read_bytes()
    monkeypatch.setattr(telemetry, 'append_event', append)
    assert recover_once(case)['result']['applied_version'] == applied['result']['applied_version']
    assert invoke(case, 'apply', apply_payload(case))['result']['idempotent']
    assert (case['project'] / '.ai-sow-lite/current.json').read_bytes() == pointer


@pytest.fixture
def serial_chain(tmp_path, serial_seed):
    record = serial_seed
    source, project = Path(record['project']), tmp_path / 'serial project'
    assert read_json(source / '.ai-sow-lite/current.json') == record['final_current']
    assert len(record['requests']) == 2
    shutil.copytree(source, project)
    for item in record['requests']:
        current = item['applied_current']
        manifest = project / f".ai-sow-lite/versions/{current['version_id']}/manifest.json"
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == current['manifest_hash']
        if item.get('actual_envelope_path'):
            envelope = read_json(Path(item['actual_envelope_path']))
            assert envelope['request_id'] == item['request_id'] and envelope['payload'] == item['payload']
    assert record['requests'][0]['payload']['expected_current'] == record['base_current']
    assert record['requests'][1]['payload']['expected_current'] == record['requests'][0]['applied_current']
    return dict(record, project=project)


def registered_dependencies(project, manifest):
    """Independently enumerate adopted business sources, not a generated check report."""
    directory = project / '.ai-sow-lite/versions' / manifest['version_id']
    inputs = read_json(directory / 'input-records.json')['items']
    proof = directory / 'confirmation.json'
    paths = set()
    if proof.exists():
        # Old delivered manifests are not retroactively upgraded by the confirmation dependency fix.
        # Still check their archived source binding against the actual original bytes.
        source = read_json(proof)['input_record']
        assert hashlib.sha256((project / source['relative_path']).read_bytes()).hexdigest() == source['content_hash']
    for entry in inputs:
        paths.add(entry['relative_path'])
        reading_ref = read_json(project / str(Path(entry['relative_path']).parent / 'reading-ref.json'))
        paths.add(reading_ref['path'])
        reading = read_json(project / reading_ref['path'])
        paths.update(item['file_ref']['path'] for item in reading['excerpts'])
    for version in manifest['topic_version_ids']:
        root = Path('.ai-sow-lite/analysis/topics') / version
        paths.add((root / 'analysis.json').as_posix())
        registration = read_json(project / root / 'registration-ref.json')
        paths.add(registration['path'])
    return {path: hashlib.sha256((project / path).read_bytes()).hexdigest() for path in paths}


def test_old_generate_retry_after_clarify_uses_applied_intent_and_preserves_latest(serial_chain):
    project = serial_chain['project']
    original = read_json(project / '.ai-sow-lite/versions' /
                         serial_chain['base_current']['version_id'] / 'manifest.json')
    request_id = original['request_id']
    area = project / '.ai-sow-lite/work/generate' / request_id
    payload = read_json(area / 'application.json')
    before = old_bytes(project)
    pointer = (project / '.ai-sow-lite/current.json').read_bytes()
    case = dict(project=project, request_id=request_id)
    repeated = invoke(case, 'apply', payload)
    assert repeated['ok'] and repeated['result']['idempotent'], repeated
    assert repeated['result']['applied_version'] == original['version_id']
    assert repeated['result']['current_version'] == serial_chain['final_current']['version_id']

    # A valid but different semantic candidate cannot reuse the original successful intent.
    prepared = read_json(project / payload['prepared_path'])
    candidate_path = project / prepared['candidate_ref']['path']
    candidate = read_json(candidate_path)
    model_path = project / candidate['model_path']
    model = read_json(model_path)
    model['tasks'][0]['notes'] += '（受控不同意图）'
    write_json(model_path, model)
    from ai_sow_lite.validation import check_candidate
    report = check_candidate(project, candidate_path, 'full', None)
    assert report['valid_for_render'], report
    assert report['candidate_digest'] != original['candidate_digest']
    changed = invoke(case, 'apply', payload)
    assert not changed['ok'] and 'REQUEST_ID_CONFLICT' in {d['code'] for d in changed['diagnostics']}
    assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer
    assert_retained(project, before)


def test_two_delivered_serial_changes_keep_history_and_reject_stale_and_changed_old_intent(serial_chain):
    chain, project = serial_chain, serial_chain['project']
    before = old_bytes(project)
    final_pointer = (project / '.ai-sow-lite/current.json').read_bytes()
    first, second = chain['requests']
    # The session fixture (or explicit capture) already performed both real render/apply cycles.
    # Select its first immutable version only in this clone to build a draft that will go stale.
    write_json(project / '.ai-sow-lite/current.json', first['applied_current'])
    one = dict(project=project, request_id=first['request_id'])
    applied = invoke(one, 'apply', first['payload'])
    assert applied['ok'] and applied['result']['idempotent'], applied
    assert read_json(project / '.ai-sow-lite/current.json') == first['applied_current']
    latest_prefix = f".ai-sow-lite/versions/{chain['final_current']['version_id']}/"
    prior_bytes = {path: raw for path, raw in before.items() if not path.startswith(latest_prefix)}
    prior = project / '.ai-sow-lite/versions' / first['applied_current']['version_id']
    manifest = read_json(prior / 'manifest.json')
    expected_dependencies = {path: hashlib.sha256(raw).hexdigest() for path, raw in prior_bytes.items()}
    expected_dependencies.update(registered_dependencies(project, manifest))

    # A finite draft starts against the first successful current, then becomes stale serially.
    story = read_json(prior / 'model.json')['stories'][0]
    stale = dict(project=project, request_id=str(uuid4()), current=first['applied_current'], ids={'S-01': story['id']})
    storage.ensure_request(project, stale['request_id'], 'clarify')
    draft = edit_draft(stale, [dict(op='replace', collection='stories', object_id=story['id'],
                                   field='notes', value=story['notes'] + '（受控待讨论说明）')])
    path = f".ai-sow-lite/work/clarify/{stale['request_id']}/edit-draft.json"
    write_json(project / path, draft)
    checked = invoke(stale, 'check', dict(edit_path=path, scope='full'))
    assert checked['ok'], checked
    stale_files = {key: (project / checked['result'][key]['path']).read_bytes()
                   for key in ('candidate_ref', 'plan_ref', 'check_ref')}

    # Restore the exact actually delivered pointer, not a new application of a pre-fix package.
    (project / '.ai-sow-lite/current.json').write_bytes(final_pointer)
    two = dict(project=project, request_id=second['request_id'])
    applied = invoke(two, 'apply', second['payload'])
    assert applied['ok'] and applied['result']['idempotent'], applied
    assert read_json(project / '.ai-sow-lite/current.json') == chain['final_current']
    current_bytes = (project / '.ai-sow-lite/current.json').read_bytes()
    latest = project / '.ai-sow-lite/versions' / chain['final_current']['version_id']
    latest_manifest = read_json(latest / 'manifest.json')
    dependencies = {ref['path']: ref['sha256'] for ref in latest_manifest['dependencies']}
    expected_dependencies.update(registered_dependencies(project, latest_manifest))
    assert expected_dependencies.items() <= dependencies.items()
    original_plan = read_json(project / second['payload']['plan_path'])
    assert read_json(latest / 'plan.json') == original_plan
    assert (latest / 'plan.json').read_bytes() == (project / second['payload']['plan_path']).read_bytes()
    old_model = read_json(prior / 'model.json')
    from ai_sow_lite.validation import diff_bundle
    new_model = read_json(latest / 'model.json')
    actual = diff_bundle(old_model, new_model)
    model_collections = {'epics', 'features', 'stories', 'acs', 'tasks', 'dependencies', 'lineage'}
    assert actual == [change for change in original_plan['changes'] if change['collection'] in model_collections]
    for collection in ('epics', 'features', 'stories', 'tasks', 'dependencies'):
        old_items = {item['id']: item for item in old_model[collection]}
        new_items = {item['id']: item for item in new_model[collection]}
        changed_ids = {change['object_id'] for change in original_plan['changes'] if change['collection'] == collection}
        assert [key for key in old_items if key in new_items] == [key for key in new_items if key in old_items]
        assert all(new_items[key] == item for key, item in old_items.items() if key not in changed_ids)
    assert_retained(project, before)
    assert_retained(project, prior_bytes)
    rejected = invoke(stale, 'render', dict(candidate_path=checked['result']['candidate_ref']['path'],
        check_path=checked['result']['check_ref']['path'], expected_current=stale['current']))
    assert not rejected['ok'] and 'BASE_STALE' in {d['code'] for d in rejected['diagnostics']}
    assert all((project / checked['result'][key]['path']).read_bytes() == raw for key, raw in stale_files.items())
    recovered = recover_once(one)
    assert recovered['ok'] and recovered['result']['applied_version'] == first['applied_current']['version_id']
    repeated = invoke(one, 'apply', first['payload'])
    assert repeated['ok'] and repeated['result']['idempotent'], repeated
    assert repeated['result']['current_version'] == chain['final_current']['version_id']
    changed = deepcopy(first['payload'])
    changed['plan_path'] = str(Path(changed['plan_path']).with_name('plan.json'))
    conflict = invoke(one, 'apply', changed)
    assert not conflict['ok'] and 'REQUEST_ID_CONFLICT' in {d['code'] for d in conflict['diagnostics']}
    assert (project / '.ai-sow-lite/current.json').read_bytes() == current_bytes


def test_smoke_verifier_consumes_real_clarify_and_rejects_missing_history_dependency(prepared_case):
    from .support.fixtures import Case
    from .support.smoke_plugin import verify_delivery
    case, project = prepared_case, prepared_case['project']
    before = old_bytes(project)
    rendered = invoke(case, 'render', dict(candidate_path=case['result']['candidate_ref']['path'],
        check_path=case['result']['check_ref']['path'], expected_current=case['current']))
    assert rendered['ok'], rendered
    applied = invoke(case, 'apply', apply_payload(case))
    assert applied['ok'], applied
    candidate_path = project / case['result']['candidate_ref']['path']
    candidate = read_json(candidate_path)
    consumer = Case(project, case['request_id'], candidate_path, candidate['template_hash'], case['ids'])
    result = verify_delivery(consumer, rendered['result'], applied['result'],
                             confirmation_path=case['confirmed_path'], previous_files=before)
    assert result['dependency_counts']['history'] == len(before)
    assert result['confirmation'] == 'registered-source-bound'
    # A self-consistent rewritten manifest still cannot omit a real predecessor file.
    path = project / applied['result']['manifest_ref']['path']
    manifest = read_json(path)
    missing = next(p for p in before if p.endswith('/model.json'))
    manifest['dependencies'] = [ref for ref in manifest['dependencies'] if ref['path'] != missing]
    write_json(path, manifest)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    applied['result']['manifest_ref']['sha256'] = digest
    write_json(project / '.ai-sow-lite/current.json', dict(version_id=manifest['version_id'], manifest_hash=digest))
    with pytest.raises(AssertionError, match='dependencies'):
        verify_delivery(consumer, rendered['result'], applied['result'],
                        confirmation_path=case['confirmed_path'], previous_files=before)


@pytest.mark.office
@pytest.mark.skipif(os.name == 'nt', reason='Actual POSIX SIGINT proof; Windows signal delivery remains unknown')
def test_observed_cancel_during_real_office_signal_cleans_only_owned_process(clarify_case):
    """Controller records observed cancellation and signals the real CLI; no host UI claim."""
    import json
    import signal
    import time
    case, project = clarify_case, clarify_case['project']
    before, pointer = old_bytes(project), (project / '.ai-sow-lite/current.json').read_bytes()
    identity = feedback(case, '仅将资料查询备注改为“保留现有范围”。\n')
    checked = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value='保留现有范围')], [identity]))
    assert checked['ok'], checked
    path = project.parent / 'office-interrupt.json'
    write_json(path, dict(protocol_version='1.0', request_id=case['request_id'], project_path=str(project),
        operation='render', payload=dict(candidate_path=checked['result']['candidate_ref']['path'],
            check_path=checked['result']['check_ref']['path'], expected_current=case['current'])))
    script = r'''
import json, subprocess, sys
from ai_sow_lite import cli, office
Original = subprocess.Popen
class ObservedOffice(Original):
    def communicate(self, *args, **kwargs):
        if '--convert-to' in self.args and not getattr(self, 'announced', False):
            self.announced = True
            print(json.dumps({'office_pid': self.pid}), flush=True)
        return super().communicate(*args, **kwargs)
office.subprocess.Popen = ObservedOffice
raise SystemExit(cli.main(['--request', sys.argv[1]]))
'''
    env = dict(os.environ, PYTHONPATH=str(PLUGIN_ROOT / 'runtime'), PYTHONDONTWRITEBYTECODE='1')
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    child = subprocess.Popen([sys.executable, '-c', script, str(path)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    watchdog = threading.Timer(30, child.kill)
    watchdog.start()
    try:
        message = json.loads(child.stdout.readline())
        pid = message['office_pid']
        os.kill(pid, 0)  # Actual native conversion process exists before cancellation.
        storage.cancel_request(project, case['request_id'], 'clarify')
        child.send_signal(signal.SIGINT)
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode in (-signal.SIGINT, 130), (child.returncode, stdout, stderr)
        assert 'KeyboardInterrupt' in stderr
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(.05)
        else:
            pytest.fail('Owned Office conversion survived SIGINT cleanup')
        assert unrelated.poll() is None
    finally:
        watchdog.cancel()
        for process in (child, unrelated):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
    area = project / '.ai-sow-lite/work/clarify' / case['request_id']
    assert not list(area.rglob('.office-*'))
    assert not list(area.rglob('prepared.json'))
    attempt = read_json(area / 'render-attempt.json')
    assert attempt['prepared_ref'] is None
    recovered = recover_once(case)
    assert recovered['ok'] and recovered['result']['state'] == 'cancelled', recovered
    assert (project / '.ai-sow-lite/current.json').read_bytes() == pointer
    assert_retained(project, before)


def test_applied_confirmation_original_remains_bound_when_recovering(prepared_case):
    case, project = prepared_case, prepared_case['project']
    applied = invoke(case, 'apply', apply_payload(case))
    assert applied['ok'], applied
    directory = project / '.ai-sow-lite/versions' / applied['result']['applied_version']
    proof = read_json(directory / 'confirmation.json')
    path = project / proof['input_record']['relative_path']
    path.write_text('受控篡改：这不是此前登记的执行确认。\n', encoding='utf-8')
    observed = recover_once(case)
    assert not observed['ok'] and 'EVIDENCE_MISSING' in {d['code'] for d in observed['diagnostics']}, observed
