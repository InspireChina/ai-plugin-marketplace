"""Actual process receipts must account for every smoke CLI invocation."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

PLUGIN = Path(__file__).resolve().parents[1]


def audit_environment(tmp_path, startup=None):
    from ai_sow_lite.project import initialize
    workspace = tmp_path / 'audit-workspace'
    audit = workspace / 'audit'
    audit.mkdir(parents=True)
    source = startup or ('from tests.support.smoke_plugin import install_read_audit\n'
                         'install_read_audit()\n')
    (audit / 'sitecustomize.py').write_text(source, encoding='utf-8')
    environment = dict(os.environ, LITE_SMOKE_WORKSPACE=str(workspace),
                       PYTHONPATH=os.pathsep.join(map(str, [audit, PLUGIN / 'runtime', PLUGIN])),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    initialize(workspace / '项目 with spaces', 'new', PLUGIN / 'assets/sow-template.xlsx')
    return workspace, environment


def invoke_current(workspace, environment):
    from .support.process_audit import run_process
    request = dict(protocol_version='1.0', request_id=str(uuid4()),
                   project_path=str(workspace / '项目 with spaces'), operation='inspect',
                   payload=dict(view='current', selector={}, limit=10, cursor=None))
    path = workspace / f'{request["request_id"]}.json'
    path.write_text(json.dumps(request), encoding='utf-8')
    process = run_process([sys.executable, str(PLUGIN / 'scripts/lite.py'), '--request', str(path)],
                          operation='inspect', cwd=workspace, env=environment,
                          capture_output=True, text=True, encoding='utf-8', timeout=30)
    reply = json.loads(process.stdout)
    assert reply['operation'] == 'inspect' and reply['ok'], reply
    return process


def test_actual_cli_receipts_reconcile_and_one_missing_receipt_fails(tmp_path):
    from .support.process_audit import reconcile_audits
    workspace, environment = audit_environment(tmp_path)
    for _ in range(2):
        invoke_current(workspace, environment)
    result = reconcile_audits(workspace)
    assert result['processes'] == result['invocations'] == 2
    assert result['violations'] == result['office_conversions'] == 0
    assert result['read_counts']['plugin'] > 0
    next((workspace / 'audit').glob('*.json')).unlink()
    with pytest.raises(AssertionError, match='receipt'):
        reconcile_audits(workspace)


def test_read_audit_works_without_posix_access_mode_constant(tmp_path):
    from .support.process_audit import reconcile_audits
    startup = ('import os\n'
               'if hasattr(os, "O_ACCMODE"): del os.O_ACCMODE\n'
               'from tests.support.smoke_plugin import install_read_audit\n'
               'install_read_audit()\n')
    workspace, environment = audit_environment(tmp_path, startup)
    invoke_current(workspace, environment)
    result = reconcile_audits(workspace)
    assert result['read_counts']['plugin'] > 0 and result['violations'] == 0


def test_sitecustomize_failure_cannot_be_hidden_by_a_successful_cli_exit(tmp_path):
    from .support.process_audit import reconcile_audits
    workspace, environment = audit_environment(tmp_path, 'raise RuntimeError("synthetic audit startup fault")\n')
    process = invoke_current(workspace, environment)
    assert process.returncode == 0 and 'synthetic audit startup fault' in process.stderr
    with pytest.raises(AssertionError, match='stderr'):
        reconcile_audits(workspace)


@pytest.mark.parametrize(('field', 'value', 'message'), [
    ('pid', -1, 'PID mismatch'),
    ('operation', 'render', 'operation mismatch'),
])
def test_count_matching_receipt_must_belong_to_the_observed_process(tmp_path, field, value, message):
    from .support.process_audit import reconcile_audits
    workspace, environment = audit_environment(tmp_path)
    invoke_current(workspace, environment)
    path = next((workspace / 'audit').glob('*.json'))
    receipt = json.loads(path.read_text(encoding='utf-8'))
    receipt[field] = value
    path.write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises(AssertionError, match=message):
        reconcile_audits(workspace)
