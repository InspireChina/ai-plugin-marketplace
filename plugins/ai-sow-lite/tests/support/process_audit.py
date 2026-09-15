"""Opt-in test process accounting; not plugin runtime telemetry or a sandbox."""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4


def run_process(command, *, operation, env=None, timeout=180, capture_output=True, **kwargs):
    environment = dict(os.environ if env is None else env)
    root = environment.get('LITE_SMOKE_WORKSPACE')
    if not root:
        return subprocess.run(command, env=env, timeout=timeout, capture_output=capture_output, **kwargs)
    assert capture_output, 'Audit needs captured startup and exit stderr'
    invocation = str(uuid4())
    environment.update(LITE_SMOKE_INVOCATION=invocation, LITE_SMOKE_OPERATION=operation)
    directory = Path(root) / 'invocations'
    directory.mkdir(exist_ok=True)
    path = directory / f'{invocation}.json'
    with subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs) as process:
        record = dict(invocation_id=invocation, pid=process.pid, operation=operation,
                      returncode=None, stderr=None)
        path.write_text(json.dumps(record), encoding='utf-8')
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            record.update(returncode=process.returncode, stderr=stderr,
                          timed_out=True)
            path.write_text(json.dumps(record), encoding='utf-8')
            raise
        record.update(returncode=process.returncode, stderr=stderr)
        path.write_text(json.dumps(record), encoding='utf-8')
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def reconcile_audits(workspace):
    """Require one receipt per observed invocation, including the smoke worker."""
    invocations = [json.loads(p.read_text(encoding='utf-8'))
                   for p in (workspace / 'invocations').glob('*.json')]
    receipts = [json.loads(p.read_text(encoding='utf-8'))
                for p in (workspace / 'audit').glob('*.json')]
    assert invocations, 'No observed process invocations'
    for record in invocations:
        assert record['returncode'] is not None, 'Process exit was not observed'
        assert record['stderr'] == '', 'Process startup/exit stderr was not empty'
        assert not record.get('timed_out'), 'Process timed out'
    expected = {record['invocation_id']: record for record in invocations}
    actual = {record['invocation_id']: record for record in receipts}
    assert len(expected) == len(invocations), 'Duplicate invocation identity'
    assert len(actual) == len(receipts), 'Duplicate audit receipt identity'
    assert actual.keys() == expected.keys(), 'Missing or unexpected audit receipt'
    counts = Counter()
    for identity, receipt in actual.items():
        invocation = expected[identity]
        # The observed pid is the launched process. Where that launch is a Windows
        # venv trampoline, the interpreter writing the receipt is its direct child,
        # so the observed pid is the receipt's parent. Accept exactly those two
        # identities -- an unrelated process still fails.
        assert invocation['pid'] in (receipt['pid'], receipt.get('parent_pid')), 'Audit receipt PID mismatch'
        assert receipt['operation'] == invocation['operation'], 'Audit receipt operation mismatch'
        counts.update(receipt['read_counts'])
    return dict(processes=len(receipts), invocations=len(invocations),
                violations=sum(r['violations'] for r in receipts),
                office_conversions=sum(r['office_conversions'] for r in receipts),
                read_counts=dict(counts),
                scope='One-to-one Python invocation/receipt audit after startup; Office native reads are not traced')
