from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import (
    Artifact,
    OwnerContract,
    canonical_json_bytes,
    match_owner,
    publish_owner,
    rebind_owner,
    sha256_bytes,
    validate_no_change_candidate,
)
from runtime.project_io import ProjectFiles, ProjectIOError


CONTRACT = OwnerContract(
    subject="sample-owner",
    contract_ids=("urn:ai-sow:sample:output:0.2",),
    validation_path=".ai-sow/validation/sample-owner.json",
    reviews=(("approvedReview", ".ai-sow/reviews/sample-owner.md"),),
    outputs=(("result", ".ai-sow/data/sample-owner/result.json"),),
)


def prepare_project(tmp_path: Path) -> tuple[ProjectFiles, tuple[Artifact, ...]]:
    files = ProjectFiles.open(tmp_path)
    project = canonical_json_bytes({"projectId": "sample-project"})
    review = b"# Review\n\nReviewer: PASS\n"
    files.write_atomic(".ai-sow/project.json", project)
    files.write_atomic(".ai-sow/reviews/sample-owner.md", review)
    inputs = (
        Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(project)),
        Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(b"NOT_REQUIRED"),
        ),
    )
    return files, inputs


def diagnostic_codes(result) -> set[str]:
    return {str(item["code"]) for item in result.diagnostics}


def test_canonical_json_bytes_are_deterministic_utf8() -> None:
    left = canonical_json_bytes({"名称": "客户门户", "items": [2, 1]})
    right = canonical_json_bytes({"items": [2, 1], "名称": "客户门户"})
    assert left == right
    assert left.endswith(b"\n")
    assert "客户门户" in left.decode("utf-8")


def test_publish_owner_writes_named_receipt_last_and_match_accepts_it(tmp_path: Path) -> None:
    files, inputs = prepare_project(tmp_path)
    candidate = canonical_json_bytes({"result": "已批准"})
    report = publish_owner(files, CONTRACT, inputs, {"result": candidate})
    assert report["owner"] == "sample-owner"
    assert report["passed"] is True
    assert report["diagnostics"] == []
    receipt = report["compilationReceipt"]
    assert receipt == {
        "algorithm": "ai-sow-owner-v1",
        "subject": "sample-owner",
        "validatorContractVersion": "0.3",
        "contractIds": ["urn:ai-sow:sample:output:0.2"],
        "inputs": [
            {"name": "project", "kind": "FILE", "path": ".ai-sow/project.json", "sha256": inputs[0].sha256},
            {"name": "questionnaire", "kind": "QUESTIONNAIRE_PRESENCE", "identity": "questionnaire:NOT_REQUIRED", "sha256": inputs[1].sha256},
        ],
        "reviews": [
            {"name": "approvedReview", "path": ".ai-sow/reviews/sample-owner.md", "sha256": sha256_bytes(files.read_bytes(".ai-sow/reviews/sample-owner.md"))}
        ],
        "outputs": [
            {"name": "result", "path": ".ai-sow/data/sample-owner/result.json", "sha256": sha256_bytes(candidate)}
        ],
    }
    assert files.read_bytes(".ai-sow/data/sample-owner/result.json") == candidate
    assert match_owner(files, CONTRACT, inputs).ok is True


def test_identical_publication_reuses_report_bytes(tmp_path: Path) -> None:
    files, inputs = prepare_project(tmp_path)
    candidate = canonical_json_bytes({"result": "same"})
    publish_owner(files, CONTRACT, inputs, {"result": candidate})
    before = files.read_bytes(CONTRACT.validation_path)
    before_stat = files.resolve(CONTRACT.validation_path).stat()
    publish_owner(files, CONTRACT, inputs, {"result": candidate})
    assert files.read_bytes(CONTRACT.validation_path) == before
    assert files.resolve(CONTRACT.validation_path).stat().st_mtime_ns == before_stat.st_mtime_ns


def test_changed_publication_replaces_owner_output_then_updates_report(tmp_path: Path) -> None:
    files, inputs = prepare_project(tmp_path)
    first = canonical_json_bytes({"revision": 1})
    second = canonical_json_bytes({"revision": 2})
    publish_owner(files, CONTRACT, inputs, {"result": first})

    report = publish_owner(files, CONTRACT, inputs, {"result": second})

    assert files.read_bytes(".ai-sow/data/sample-owner/result.json") == second
    assert report["compilationReceipt"]["outputs"][0]["sha256"] == sha256_bytes(second)
    assert match_owner(files, CONTRACT, inputs).ok is True


def test_multi_output_interruption_leaves_old_report_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, inputs = prepare_project(tmp_path)
    contract = OwnerContract(
        subject="sample-owner",
        contract_ids=("urn:ai-sow:sample:pair:0.2",),
        validation_path=".ai-sow/validation/sample-owner.json",
        reviews=CONTRACT.reviews,
        outputs=(
            ("first", ".ai-sow/data/sample-owner/first.json"),
            ("second", ".ai-sow/data/sample-owner/second.json"),
        ),
    )
    first_revision = {
        "first": canonical_json_bytes({"revision": 1, "output": "first"}),
        "second": canonical_json_bytes({"revision": 1, "output": "second"}),
    }
    second_revision = {
        "first": canonical_json_bytes({"revision": 2, "output": "first"}),
        "second": canonical_json_bytes({"revision": 2, "output": "second"}),
    }
    publish_owner(files, contract, inputs, first_revision)
    report_before = files.read_bytes(contract.validation_path)
    original_write = ProjectFiles.write_atomic

    def fail_second_output(
        current: ProjectFiles,
        relative_path: str,
        payload: bytes,
    ) -> None:
        if relative_path == contract.outputs[1][1] and payload == second_revision["second"]:
            raise ProjectIOError("TEST_INTERRUPTION", relative_path, "simulated interruption")
        original_write(current, relative_path, payload)

    monkeypatch.setattr(ProjectFiles, "write_atomic", fail_second_output)
    with pytest.raises(ProjectIOError) as raised:
        publish_owner(files, contract, inputs, second_revision)
    assert raised.value.code == "TEST_INTERRUPTION"
    assert files.read_bytes(contract.validation_path) == report_before
    assert match_owner(files, contract, inputs).ok is False
    assert diagnostic_codes(match_owner(files, contract, inputs)) == {
        "UPSTREAM_HANDOFF_STALE"
    }


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (("missing", "UPSTREAM_HANDOFF_MISSING"), ("invalid", "UPSTREAM_HANDOFF_INVALID"), ("unsupported", "UPSTREAM_CONTRACT_UNSUPPORTED"), ("stale", "UPSTREAM_HANDOFF_STALE")),
)
def test_match_owner_returns_only_stable_handoff_errors(tmp_path: Path, mutation: str, expected: str) -> None:
    files, inputs = prepare_project(tmp_path)
    candidate = canonical_json_bytes({"result": "published"})
    publish_owner(files, CONTRACT, inputs, {"result": candidate})
    if mutation == "missing":
        files.resolve(CONTRACT.validation_path).unlink()
    elif mutation == "invalid":
        files.write_atomic(CONTRACT.validation_path, b'{"passed":false}\n')
    elif mutation == "unsupported":
        report = files.read_json(CONTRACT.validation_path)
        assert isinstance(report, dict)
        report["compilationReceipt"]["validatorContractVersion"] = "9.9"
        files.write_atomic(CONTRACT.validation_path, canonical_json_bytes(report))
    else:
        files.write_atomic(".ai-sow/data/sample-owner/result.json", b"changed")
    result = match_owner(files, CONTRACT, inputs)
    assert result.ok is False
    assert diagnostic_codes(result) == {expected}
    assert result.diagnostics[0]["upstreamOwner"] == "sample-owner"
    assert str(tmp_path) not in json.dumps(result.diagnostics)


def test_rebind_updates_inputs_and_review_without_changing_output_bytes(tmp_path: Path) -> None:
    files, old_inputs = prepare_project(tmp_path)
    candidate = canonical_json_bytes({"result": "stable"})
    publish_owner(files, CONTRACT, old_inputs, {"result": candidate})
    output_before = files.read_bytes(".ai-sow/data/sample-owner/result.json")
    new_project = canonical_json_bytes({"projectId": "sample-project", "revision": 2})
    files.write_atomic(".ai-sow/project.json", new_project)
    files.write_atomic(".ai-sow/reviews/sample-owner.md", b"# Review\n\nImpact: NO_CHANGE\n\nReviewer: PASS\n")
    new_inputs = (
        Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(new_project)),
        old_inputs[1],
    )
    report = rebind_owner(files, CONTRACT, new_inputs)
    assert files.read_bytes(".ai-sow/data/sample-owner/result.json") == output_before
    assert report["compilationReceipt"]["inputs"][0]["sha256"] == sha256_bytes(new_project)
    assert match_owner(files, CONTRACT, new_inputs).ok is True


def test_rebind_fails_when_stable_output_bytes_changed(tmp_path: Path) -> None:
    files, inputs = prepare_project(tmp_path)
    publish_owner(files, CONTRACT, inputs, {"result": canonical_json_bytes({"result": "stable"})})
    report_before = files.read_bytes(CONTRACT.validation_path)
    files.write_atomic(".ai-sow/data/sample-owner/result.json", b"changed")
    with pytest.raises(ProjectIOError) as raised:
        rebind_owner(files, CONTRACT, inputs)
    assert raised.value.code == "OWNER_REBIND_OUTPUT_CHANGED"
    assert files.read_bytes(CONTRACT.validation_path) == report_before


def test_no_change_candidate_requires_changed_inputs_and_exact_stable_bytes(
    tmp_path: Path,
) -> None:
    files, old_inputs = prepare_project(tmp_path)
    candidate = canonical_json_bytes({"result": "stable"})
    publish_owner(files, CONTRACT, old_inputs, {"result": candidate})

    with pytest.raises(ProjectIOError) as unchanged:
        validate_no_change_candidate(files, CONTRACT, old_inputs, {"result": candidate})
    assert unchanged.value.code == "REBIND_INPUT_UNCHANGED"

    new_project = canonical_json_bytes({"projectId": "sample-project", "revision": 2})
    files.write_atomic(".ai-sow/project.json", new_project)
    new_inputs = (
        Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(new_project)),
        old_inputs[1],
    )
    outputs = validate_no_change_candidate(
        files,
        CONTRACT,
        new_inputs,
        {"result": candidate},
    )
    assert outputs == [
        {
            "name": "result",
            "path": ".ai-sow/data/sample-owner/result.json",
            "sha256": sha256_bytes(candidate),
        }
    ]

    with pytest.raises(ProjectIOError) as changed:
        validate_no_change_candidate(
            files,
            CONTRACT,
            new_inputs,
            {"result": canonical_json_bytes({"result": "changed"})},
        )
    assert changed.value.code == "OWNER_NO_CHANGE_CANDIDATE_CHANGED"
