from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).parents[1]
OWNER_APPROVAL_PATHS = {
    "analyze-requirement": ".ai-sow/work/analyze-requirement/approval.json",
    "analyze-as-is": ".ai-sow/work/analyze-as-is/approval.json",
    "generate-design": ".ai-sow/work/generate-design/approval.json",
    "generate-story": ".ai-sow/work/generate-story/approval.json",
    "generate-task": ".ai-sow/work/generate-task/approval.json",
}
OWNER_REVIEWER_PATHS = {
    owner: path.replace("approval.json", "reviewer.json")
    for owner, path in OWNER_APPROVAL_PATHS.items()
}
PACKET_SHA256 = "a" * 64


def run_approval(owner: str, project_root: Path, packet_sha256: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "skills" / owner / "scripts" / "validate.py"),
            "--project-root",
            str(project_root),
            "--mode",
            "write-approval",
            "--packet-sha256",
            packet_sha256,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def run_reviewer(owner: str, project_root: Path, packet_sha256: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "skills" / owner / "scripts" / "validate.py"),
            "--project-root",
            str(project_root),
            "--mode",
            "write-reviewer",
            "--packet-sha256",
            packet_sha256,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("owner", OWNER_APPROVAL_PATHS)
def test_owner_writes_canonical_approval_without_other_inputs(
    tmp_path: Path,
    owner: str,
) -> None:
    result = run_approval(owner, tmp_path, PACKET_SHA256)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "outcome": "OK",
        "summary": f"{owner} approval sidecar is ready",
        "diagnostics": [],
        "outputs": [OWNER_APPROVAL_PATHS[owner]],
        "packetSha256": PACKET_SHA256,
    }
    expected = json.dumps(
        {
            "algorithm": "ai-sow-owner-approval-v1",
            "decision": "APPROVED",
            "owner": owner,
            "packetSha256": PACKET_SHA256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    assert (tmp_path / OWNER_APPROVAL_PATHS[owner]).read_bytes() == expected
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()) == [
        OWNER_APPROVAL_PATHS[owner]
    ]


@pytest.mark.parametrize("owner", OWNER_APPROVAL_PATHS)
def test_owner_rejects_invalid_packet_hash_without_writing(
    tmp_path: Path,
    owner: str,
) -> None:
    result = run_approval(owner, tmp_path, "not-a-packet-hash")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert payload["diagnostics"] == [
        {
            "code": "PACKET_SHA256_INVALID",
            "message": "--packet-sha256 must be exactly 64 lowercase hexadecimal characters",
        }
    ]
    assert not list(tmp_path.rglob("approval.json"))


@pytest.mark.parametrize("owner", OWNER_REVIEWER_PATHS)
def test_owner_writes_canonical_reviewer_without_other_inputs(
    tmp_path: Path,
    owner: str,
) -> None:
    result = run_reviewer(owner, tmp_path, PACKET_SHA256)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "outcome": "OK",
        "summary": f"{owner} reviewer sidecar is ready",
        "diagnostics": [],
        "outputs": [OWNER_REVIEWER_PATHS[owner]],
        "packetSha256": PACKET_SHA256,
    }
    expected = json.dumps(
        {
            "algorithm": "ai-sow-owner-reviewer-v1",
            "decision": "PASS",
            "owner": owner,
            "packetSha256": PACKET_SHA256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    assert (tmp_path / OWNER_REVIEWER_PATHS[owner]).read_bytes() == expected
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()) == [
        OWNER_REVIEWER_PATHS[owner]
    ]


@pytest.mark.parametrize("owner", OWNER_REVIEWER_PATHS)
def test_owner_rejects_invalid_reviewer_packet_hash_without_writing(
    tmp_path: Path,
    owner: str,
) -> None:
    result = run_reviewer(owner, tmp_path, "not-a-packet-hash")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert payload["diagnostics"] == [
        {
            "code": "PACKET_SHA256_INVALID",
            "message": "--packet-sha256 must be exactly 64 lowercase hexadecimal characters",
        }
    ]
    assert not list(tmp_path.rglob("reviewer.json"))
