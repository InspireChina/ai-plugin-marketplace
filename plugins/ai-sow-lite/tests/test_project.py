"""Local storage tests; controlled packages do not certify Office delivery."""
from uuid import uuid4

import pytest

from ai_sow_lite.contracts import PLUGIN_ROOT, load_json
from .support.fixtures import write_json


def test_initialize_is_idempotent_and_refuses_identity_drift(tmp_path):
    from ai_sow_lite.project import initialize, StorageError
    template = PLUGIN_ROOT / 'assets/sow-template.xlsx'
    project = tmp_path / 'project'
    first = initialize(project, 'new', template)
    assert initialize(project, 'new', template) == first
    assert not (project / '.ai-sow-lite/current.json').exists()
    with pytest.raises(StorageError, match='PROJECT_ID_CONFLICT'):
        initialize(project, 'existing', template)


def test_checkpoint_preserves_known_counts_and_rejects_reset(tmp_path):
    from ai_sow_lite.project import initialize, ensure_request, save_checkpoint, StorageError
    initialize(tmp_path, 'new', PLUGIN_ROOT / 'assets/sow-template.xlsx')
    request = str(uuid4())
    checkpoint = ensure_request(tmp_path, request, 'generate')
    checkpoint.update(additional_investigation_batches=1, repair_batches=2, last_progress='已读取材料')
    save_checkpoint(tmp_path, checkpoint)
    assert ensure_request(tmp_path, request, 'generate')['repair_batches'] == 2
    checkpoint['repair_batches'] = 0
    with pytest.raises(StorageError, match='LOOP_LIMIT_REACHED'):
        save_checkpoint(tmp_path, checkpoint)


def test_missing_checkpoint_queries_once_then_stops_without_reset(tmp_path, monkeypatch):
    from ai_sow_lite import project as storage
    storage.initialize(tmp_path, 'new', PLUGIN_ROOT / 'assets/sow-template.xlsx')
    request = str(uuid4())
    storage.ensure_request(tmp_path, request, 'generate')
    path = tmp_path / f'.ai-sow-lite/work/generate/{request}/checkpoint.json'
    path.unlink()
    calls = []
    recover = storage.recover_request
    def observed(*args):
        calls.append(args)
        return recover(*args)
    monkeypatch.setattr(storage, 'recover_request', observed)
    for _ in range(2):
        with pytest.raises(storage.StorageError, match='CHECKPOINT_UNKNOWN'):
            storage.ensure_request(tmp_path, request, 'generate')
    assert len(calls) == 1
    assert not path.exists()


def test_commit_first_version_and_idempotence_precede_preparation(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    first = storage._commit_version(**package)
    pointer = load_json(tmp_path / '.ai-sow-lite/current.json')
    assert first['applied_version'] == package['manifest']['version_id']
    assert first['idempotent'] is False
    assert first['current_version'] == first['applied_version']
    # A response retry can succeed without exporting or reading vanished work files.
    import shutil
    shutil.rmtree(package['prepared_directory'])
    again = storage._commit_version(**package)
    assert again['idempotent'] is True
    assert again['applied_version'] == first['applied_version']
    assert load_json(tmp_path / '.ai-sow-lite/current.json') == pointer


def test_serial_history_returns_original_result_without_rollback(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    first = storage_package(tmp_path)
    storage._commit_version(**first)
    pointer = load_json(tmp_path / '.ai-sow-lite/current.json')
    second = storage_package(tmp_path, expected_current=pointer)
    applied = storage._commit_version(**second)
    assert applied['current_version'] == second['manifest']['version_id']
    old = storage._commit_version(**first)
    assert old['applied_version'] == first['manifest']['version_id']
    assert old['current_version'] == second['manifest']['version_id']
    assert storage.recover_request(tmp_path, first['request_id'])['applied_version'] == first['manifest']['version_id']
    assert load_json(tmp_path / '.ai-sow-lite/current.json')['version_id'] == second['manifest']['version_id']


def test_fresh_generate_and_stale_serial_request_cannot_overwrite_current(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    first = storage_package(tmp_path)
    storage._commit_version(**first)
    current = load_json(tmp_path / '.ai-sow-lite/current.json')
    fresh = storage_package(tmp_path)
    with pytest.raises(storage.StorageError, match='BASE_STALE'):
        storage._commit_version(**fresh)
    second = storage_package(tmp_path, expected_current=current)
    stale = storage_package(tmp_path, expected_current=current)
    storage._commit_version(**second)
    with pytest.raises(storage.StorageError, match='BASE_STALE'):
        storage._commit_version(**stale)


def test_same_request_different_intent_is_rejected(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    storage._commit_version(**package)
    package['manifest']['intent_digest'] = 'json-v1:' + '0' * 64
    with pytest.raises(storage.StorageError, match='REQUEST_ID_CONFLICT'):
        storage._commit_version(**package)


def test_cancelled_late_package_and_cancel_after_apply(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    cancelled = storage_package(tmp_path)
    storage.cancel_request(tmp_path, cancelled['request_id'], 'generate')
    with pytest.raises(storage.StorageError, match='REQUEST_CANCELLED'):
        storage._commit_version(**cancelled)
    assert storage.recover_request(tmp_path, cancelled['request_id'])['state'] == 'cancelled'
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()
    successful = storage_package(tmp_path)
    storage._commit_version(**successful)
    storage.cancel_request(tmp_path, successful['request_id'], 'generate')
    assert storage.recover_request(tmp_path, successful['request_id'])['state'] == 'applied'


def test_corrupt_current_and_orphan_versions_are_not_success(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package, write_json
    import shutil
    package = storage_package(tmp_path)
    destination = tmp_path / '.ai-sow-lite/versions' / package['manifest']['version_id']
    shutil.copytree(package['prepared_directory'], destination)
    from ai_sow_lite.contracts import canonical_json_bytes
    (destination / 'manifest.json').write_bytes(canonical_json_bytes(package['manifest']))
    assert storage.recover_request(tmp_path, package['request_id'])['state'] == 'draft'
    storage._commit_version(**package)
    (destination / 'sow.xlsx').write_bytes(b'corrupt')
    assert storage.recover_request(tmp_path, package['request_id'])['state'] == 'incompatible'


@pytest.mark.parametrize('boundary,applied', [('prepared', False), ('installed', False), ('before_replace', False),
                                            ('after_replace', True), ('response', True)])
def test_process_interruption_preserves_activation_fact(tmp_path, boundary, applied):
    """Real child termination at deterministic monkeypatched save boundaries; no sleeps."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package, write_json
    package = storage_package(tmp_path)
    serializable = {k: str(v) if isinstance(v, Path) else v for k, v in package.items()}
    config = tmp_path / 'package.json'
    write_json(config, serializable)
    script = r'''
import json, sys
from pathlib import Path
from ai_sow_lite import project as storage
package=json.loads(Path(sys.argv[1]).read_text())
package['project']=Path(package['project'])
package['prepared_directory']=Path(package['prepared_directory'])
boundary=sys.argv[2]
name={'prepared':'_prepare_version','installed':'_install_version','before_replace':'replace_current',
      'after_replace':'replace_current','response':'_applied_result'}[boundary]
original=getattr(storage,name)
def barrier(*args,**kwargs):
    if boundary in ('before_replace','response'):
        print('READY',flush=True)
        sys.stdin.readline()
    result=original(*args,**kwargs)
    if boundary not in ('before_replace','response'):
        print('READY',flush=True)
        sys.stdin.readline()
    return result
setattr(storage,name,barrier)
storage._commit_version(**package)
'''
    environment = dict(os.environ, PYTHONPATH=str(PLUGIN_ROOT / 'runtime'))
    child = subprocess.Popen([sys.executable, '-c', script, str(config), boundary],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=environment)
    try:
        # A watchdog bounds failed barriers without a sleep-based scheduling assumption.
        import threading
        watchdog = threading.Timer(20, child.kill)
        watchdog.start()
        assert child.stdout.readline().strip() == 'READY', child.stderr.read()
        child.kill()
        child.wait(timeout=10)
    finally:
        watchdog.cancel()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stdin.close(); child.stdout.close(); child.stderr.close()
    recovered = storage.recover_request(tmp_path, package['request_id'])
    assert recovered['state'] == ('applied' if applied else 'draft')
    assert (tmp_path / '.ai-sow-lite/current.json').exists() == applied
    # The process death must release the operating-system lock immediately.
    with storage.commit_lock(tmp_path):
        pass
    retry = storage._commit_version(**package)
    assert retry['applied_version'] == package['manifest']['version_id']
    assert retry['idempotent'] == applied


def test_lock_busy_returns_immediately_and_preserves_current(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    with storage.commit_lock(tmp_path):
        with pytest.raises(storage.StorageError, match='WRITE_BUSY'):
            storage._commit_version(**package)
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()


def test_after_replace_or_post_apply_record_failure_still_reports_applied(tmp_path, monkeypatch):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    replace = storage.replace_current
    def replace_then_fail(*args):
        replace(*args)
        raise OSError('response unknown after replacement')
    monkeypatch.setattr(storage, 'replace_current', replace_then_fail)
    result = storage._commit_version(**package)
    assert result['applied_version'] == package['manifest']['version_id']
    assert storage.recover_request(tmp_path, package['request_id'])['state'] == 'applied'


def test_file_fsync_failure_before_replace_keeps_previous_pointer(tmp_path, monkeypatch):
    import os
    from ai_sow_lite import project as storage
    tmp_path.joinpath('current.json').write_bytes(b'previous pointer')
    def failed(_):
        raise OSError('fsync failure')
    monkeypatch.setattr(os, 'fsync', failed)
    with pytest.raises(OSError):
        storage.replace_current(tmp_path, dict(version_id=str(uuid4()), manifest_hash='0' * 64))
    assert tmp_path.joinpath('current.json').read_bytes() == b'previous pointer'
    assert not list(tmp_path.glob('.current-*.tmp'))


def test_platform_directory_flush_is_reported_honestly(tmp_path):
    import os
    from ai_sow_lite.project import fsync_directory
    assert fsync_directory(tmp_path) == (os.name != 'nt')


def test_public_clarify_cannot_accept_fabricated_confirmation(tmp_path):
    from .support.cli import run_request
    request = str(uuid4())
    response = run_request(tmp_path, request, 'apply', dict(entrypoint='clarify', prepared_path='fake.json',
                           expected_current=None, plan_path='fake-plan.json'))
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'OPERATION_UNSUPPORTED'
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()


def test_post_apply_response_failure_does_not_report_unapplied(tmp_path, monkeypatch):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    def failed(*args):
        raise OSError('post-apply response/log failure')
    monkeypatch.setattr(storage, '_applied_result', failed)
    result = storage._commit_version(**package)
    assert result['applied_version'] == package['manifest']['version_id']


@pytest.mark.parametrize('mutation,code', [('file', 'EVIDENCE_MISSING'), ('intent', 'REQUEST_ID_CONFLICT'),
                                           ('cancel', 'REQUEST_CANCELLED')])
def test_commit_rechecks_snapshot_intent_and_cancel_under_lock(tmp_path, monkeypatch, mutation, code):
    from contextlib import contextmanager
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    lock = storage.commit_lock
    @contextmanager
    def changed(project):
        with lock(project):
            area = package['prepared_directory'].parent
            if mutation == 'file':
                next(area.glob('.prepared-*/sow.xlsx')).write_bytes(b'changed')
            elif mutation == 'intent':
                (area / 'intent.json').write_bytes(b'{}')
            else:
                storage.cancel_request(project, package['request_id'], 'generate')
            yield
    monkeypatch.setattr(storage, 'commit_lock', changed)
    with pytest.raises(storage.StorageError, match=code):
        storage._commit_version(**package)
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()


def test_history_recovery_requires_actual_hash_bound_base_chain(tmp_path):
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    first = storage_package(tmp_path)
    storage._commit_version(**first)
    pointer = load_json(tmp_path / '.ai-sow-lite/current.json')
    second = storage_package(tmp_path, expected_current=pointer)
    storage._commit_version(**second)
    old_manifest = tmp_path / f".ai-sow-lite/versions/{first['manifest']['version_id']}/manifest.json"
    old_manifest.write_bytes(b'corrupt history')
    assert storage.recover_request(tmp_path, first['request_id'])['state'] == 'incompatible'
    # An arbitrary request result index cannot override the broken current/history chain.
    write_json(tmp_path / '.ai-sow-lite/requests/index.json', {first['request_id']:first['manifest']['version_id']})
    assert storage.recover_request(tmp_path, first['request_id'])['state'] == 'incompatible'


def test_preparation_refuses_a_different_filesystem(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from ai_sow_lite import project as storage
    from .support.fixtures import storage_package
    package = storage_package(tmp_path)
    real_stat = Path.stat
    def changed(path, *args, **kwargs):
        snapshot = real_stat(path, *args, **kwargs)
        if path == package['prepared_directory']:
            return SimpleNamespace(**{k: getattr(snapshot, k) for k in dir(snapshot) if k.startswith('st_') and k != 'st_dev'}, st_dev=snapshot.st_dev + 1)
        return snapshot
    monkeypatch.setattr(Path, 'stat', changed)
    with pytest.raises(storage.StorageError, match='IO_FAILED'):
        storage._commit_version(**package)
    assert not (tmp_path / '.ai-sow-lite/current.json').exists()


def test_public_generate_requires_real_i13_verifier_and_has_no_bypass(tmp_path):
    from ai_sow_lite.contracts import canonical_json_bytes, file_sha256
    from .support.cli import run_request
    from .support.fixtures import build_ingested_case
    case = build_ingested_case(tmp_path / 'project')
    check = run_request(case.project, case.request_id, 'check', dict(
        candidate_path=case.candidate_path.relative_to(case.project).as_posix(), scope='full', plan_path=None))
    def ref(path):
        return dict(path=path.relative_to(case.project).as_posix(), sha256=file_sha256(path))
    package_dir = case.file('prepared')
    package_dir.mkdir()
    files = []
    for name in ('model.json', 'pending-items.json', 'decisions.json', 'projection.json', 'sow.xlsx', 'summary.md', 'pending-items.md'):
        target = package_dir / name
        target.write_bytes(case.file(name).read_bytes() if case.file(name).exists() else b'controlled storage placeholder')
        files.append(ref(target))
    verification = package_dir / 'verification.json'
    verification.write_bytes(b'{"valid":true}')
    prepared = dict(schema_version='1.0', version_id=str(uuid4()), candidate_ref=ref(case.candidate_path),
                    check_ref=check['result']['check_ref'], expected_current=None, files=files,
                    template_hash=case.template_hash, projection_version='lite-projection-v1',
                    office_identity='fabricated', verification_ref=ref(verification))
    path = package_dir / 'prepared.json'
    path.write_bytes(canonical_json_bytes(prepared))
    payload = dict(entrypoint='generate', prepared_path=path.relative_to(case.project).as_posix(),
                   expected_current=None, plan_path=None)
    response = run_request(case.project, case.request_id, 'apply', payload)
    assert not response['ok']
    assert response['diagnostics'][0]['code'] == 'OPERATION_UNSUPPORTED'
    assert response['diagnostics'][0]['target']['field'] == 'verification_ref'
    bypass = run_request(case.project, case.request_id, 'apply', dict(payload, skip_verification=True))
    assert bypass['diagnostics'][0]['code'] == 'PROTOCOL_INVALID'
    assert not (case.project / '.ai-sow-lite/current.json').exists()


def test_public_recovery_distinguishes_corruption_with_diagnostics(tmp_path):
    from .support.cli import run_request
    from .support.fixtures import storage_package
    from ai_sow_lite.project import _commit_version
    package = storage_package(tmp_path)
    _commit_version(**package)
    (tmp_path / '.ai-sow-lite/current.json').write_bytes(b'{broken')
    response = run_request(tmp_path, str(uuid4()), 'recover', dict(target_request_id=package['request_id']))
    assert not response['ok']
    assert response['result']['state'] == 'incompatible'
    assert response['diagnostics'][0]['code'] == 'VERSION_INCOMPATIBLE'


def test_unknown_checkpoint_counters_survive_restart_without_becoming_zero(tmp_path):
    from ai_sow_lite import project as storage
    storage.initialize(tmp_path, 'new', PLUGIN_ROOT / 'assets/sow-template.xlsx')
    request = str(uuid4())
    cp = storage.ensure_request(tmp_path, request, 'generate')
    cp['repair_batches'] = None
    storage.save_checkpoint(tmp_path, cp)
    with pytest.raises(storage.StorageError, match='CHECKPOINT_UNKNOWN'):
        storage.ensure_request(tmp_path, request, 'generate')
    assert load_json(tmp_path / f'.ai-sow-lite/work/generate/{request}/checkpoint.json')['repair_batches'] is None
