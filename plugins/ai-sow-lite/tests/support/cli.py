"""Exercise the actual one-request CLI with a bounded test-process timeout."""
import json
from pathlib import Path
import sys
import tempfile

PLUGIN = Path(__file__).resolve().parents[2]


def run_request(project: Path, request_id: str, operation: str, payload: dict) -> dict:
    from ai_sow_lite.contracts import canonical_json_bytes, strict_json_loads
    from .process_audit import run_process
    request = dict(protocol_version="1.0", request_id=request_id,
                   project_path=str(project), operation=operation, payload=payload)
    with tempfile.TemporaryDirectory(prefix="lite-cli-") as directory:
        path = Path(directory) / "请求.json"
        path.write_bytes(canonical_json_bytes(request))
        completed = run_process([sys.executable, str(PLUGIN / "scripts/lite.py"), "--request", str(path)],
                                operation=operation, cwd=directory, capture_output=True,
                                text=True, encoding="utf-8", timeout=180)
    body = strict_json_loads(completed.stdout)
    assert set(body) == {"ok", "request_id", "operation", "result", "diagnostics"}
    assert (completed.returncode == 0) == body["ok"], (completed.returncode, body, completed.stderr)
    assert completed.returncode in (0, 1, 2, 3, 4)
    return body
