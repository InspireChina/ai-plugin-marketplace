from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts/reconcile.py"
SPEC = importlib.util.spec_from_file_location("ai_sow_reconcile", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RECONCILE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RECONCILE
SPEC.loader.exec_module(RECONCILE)


RUN_ID = "a1b2c3d4e5f6"
PROJECT_VALUE = {
    "projectId": "sample-project",
    "name": "示例项目",
    "pluginVersion": "0.1.0-beta.2",
    "sowStandardVersion": "1.3",
}
TEMPLATE_PAYLOAD = b"authoritative-template"
ANALYSIS_SCOPE: dict[str, Any] = {
    "mode": "BROWNFIELD",
    "repositorySnapshots": [
        {
            "repoId": "sample-repository",
            "revision": "0" * 40,
        }
    ],
    "priorSowSnapshots": [
        {
            "priorSowId": "prior-sow",
            "sha256": "1" * 64,
        }
    ],
}
PREPARED_CANDIDATE_PATHS = {
    "analyze-requirement": (".ai-sow/work/analyze-requirement/requirements.candidate.json",),
    "analyze-as-is": (".ai-sow/work/analyze-as-is/asis.candidate.json",),
    "generate-design": (
        ".ai-sow/work/generate-design/design.candidate.json",
        ".ai-sow/work/generate-design/requirements.candidate.json",
    ),
    "generate-story": (".ai-sow/work/generate-story/delivery.candidate.json",),
    "generate-task": (".ai-sow/work/generate-task/estimate.candidate.json",),
}


def test_skill_freezes_preapproval_closure_and_postapproval_publisher_only() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "当前 Stage Agent 是本 Skill 的唯一用户接口" in skill
    assert "ai-sow-reconciliation-review-packet-v1" in skill
    assert "ai-sow-reconciliation-reviewer-v1" in skill
    assert "--mode assemble" in skill
    assert "批准后只运行" in skill
    assert (
        skill.index("--mode assemble")
        < skill.index("Reviewer 只读取")
        < skill.index("批准后只运行")
    )
    for forbidden in (
        "一个 Worker Agent、一个 Reviewer Agent 和一个 Validator Agent",
        "批准后按以下顺序完成",
        "批准后 Worker 编译",
    ):
        assert forbidden not in skill


def write(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def owner_review(review_hash: str, owner: str, revision: int) -> bytes:
    return (
        f"# {owner}\n\n"
        f"Revision: {revision}\n"
        f"Reconciliation Run ID: {RUN_ID}\n"
        f"Reconciliation Review SHA-256: {review_hash}\n"
    ).encode()


def owner_receipt(
    owner: Any,
    project_payload: bytes,
    review_payload: bytes,
    outputs: dict[str, bytes],
    *,
    extra_inputs: list[dict[str, str]] | None = None,
) -> bytes:
    inputs = [
        {
            "name": "project",
            "kind": "FILE",
            "path": ".ai-sow/project.json",
            "sha256": RECONCILE.sha256_bytes(project_payload),
        }
    ]
    inputs.extend(extra_inputs or [])
    report = {
        "owner": owner.name,
        "passed": True,
        "diagnostics": [],
        "compilationReceipt": {
            "algorithm": "ai-sow-owner-v1",
            "subject": owner.name,
            "validatorContractVersion": "0.3",
            "contractIds": [f"urn:test:{owner.name}:0.1"],
            "inputs": inputs,
            "reviews": [
                {
                    "name": "approvedReview",
                    "path": owner.review,
                    "sha256": RECONCILE.sha256_bytes(review_payload),
                }
            ],
            "outputs": [
                {
                    "name": owner.output_names[index],
                    "path": output_path,
                    "sha256": RECONCILE.sha256_bytes(outputs[output_path]),
                }
                for index, output_path in enumerate(owner.outputs)
            ],
        },
    }
    return RECONCILE.canonical_json_bytes(report)


def holistic_review(
    owners: list[dict[str, str]],
    output_hashes: dict[str, tuple[str, str]],
    *,
    story_change: str = "NO_CHANGE",
    story_diff: str = "NONE",
    reviewer_pass: bool = True,
) -> bytes:
    rows = "\n".join(
        f"| {entry['owner']} | {entry['impact']} | "
        f"{output_hashes[entry['owner']][0]} | {output_hashes[entry['owner']][1]} | "
        "ids | 已完成整体复核。 |"
        for entry in owners
    )
    return (
        "# AI SOW 影响集整体评审\n\n"
        f"Run ID: {RUN_ID}\n"
        f"Correction Owner: {owners[0]['owner']}\n"
        f"Impact Suffix: {', '.join([*(entry['owner'] for entry in owners), 'generate-sow'])}\n\n"
        "| Owner | Impact | Before Output SHA-256 | After Output SHA-256 | Stable IDs | Rationale |\n"
        "|---|---|---|---|---|---|\n"
        f"{rows}\n\n"
        f"Story/AC Outcome Change: {story_change}\n"
        f"Story/AC Exact Diff: {story_diff}\n"
        + ("Reviewer: PASS\n" if reviewer_pass else "")
    ).encode()


def build_project(
    tmp_path: Path,
    *,
    start_owner: str = "generate-task",
    impacts: dict[str, str] | None = None,
    story_change: str = "NO_CHANGE",
    story_diff: str = "NONE",
    prepared: bool = False,
) -> tuple[Path, dict[str, object]]:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    project_payload = RECONCILE.canonical_json_bytes(PROJECT_VALUE)
    write(project, ".ai-sow/project.json", project_payload)
    write(project, ".ai-sow/templates/sow-template.xlsx", TEMPLATE_PAYLOAD)

    suffix = RECONCILE.owner_suffix(start_owner)
    impact_values = impacts or {
        spec.name: "CHANGED" if spec.name == start_owner else "NO_CHANGE"
        for spec in suffix
    }
    owner_entries = [
        {"owner": spec.name, "impact": impact_values[spec.name]} for spec in suffix
    ]

    output_payloads: dict[str, tuple[dict[str, bytes], dict[str, bytes]]] = {}
    output_hashes: dict[str, tuple[str, str]] = {}

    def output_payload(owner_name: str, index: int, revision: int) -> bytes:
        value: dict[str, object] = {
            "owner": owner_name,
            "output": index,
            "revision": revision,
        }
        if owner_name == "analyze-as-is":
            value["analysisScope"] = ANALYSIS_SCOPE
        return RECONCILE.canonical_json_bytes(value)

    for spec in RECONCILE.OWNER_SPECS:
        before_outputs = {
            path: output_payload(spec.name, index, 1)
            for index, path in enumerate(spec.outputs)
        }
        impact = impact_values.get(spec.name)
        after_outputs = {
            path: (
                output_payload(spec.name, index, 2)
                if impact == "CHANGED" and index == 0
                else payload
            )
            for index, (path, payload) in enumerate(before_outputs.items())
        }
        output_payloads[spec.name] = (before_outputs, after_outputs)
        if spec.name in {entry["owner"] for entry in owner_entries}:
            output_hashes[spec.name] = (
                "; ".join(
                    f"{name}={RECONCILE.sha256_bytes(before_outputs[path])}"
                    for name, path in zip(spec.output_names, spec.outputs, strict=True)
                ),
                "; ".join(
                    f"{name}={RECONCILE.sha256_bytes(after_outputs[path])}"
                    for name, path in zip(spec.output_names, spec.outputs, strict=True)
                ),
            )
    review_payload = holistic_review(
        owner_entries,
        output_hashes,
        story_change=story_change,
        story_diff=story_diff,
        reviewer_pass=not prepared,
    )
    review_hash = RECONCILE.sha256_bytes(review_payload)
    review_path = f".ai-sow/work/reconcile/{RUN_ID}/review.md"
    write(project, review_path, review_payload)

    approval_path = f".ai-sow/work/reconcile/{RUN_ID}/approval.json"
    approval_payload = RECONCILE.canonical_json_bytes(
        {
            "algorithm": RECONCILE.APPROVAL_ALGORITHM,
            "decision": "APPROVED",
            "reviewSha256": review_hash,
            "runId": RUN_ID,
        }
    )
    if not prepared:
        write(project, approval_path, approval_payload)
    staging_view = RECONCILE.ProjectFiles.open_view(
        project,
        f".ai-sow/.stage-{RUN_ID}",
    )

    scoped_names = {spec.name for spec in suffix}
    operations: list[dict[str, object]] = []
    for spec in RECONCILE.OWNER_SPECS:
        before_review = f"# {spec.name}\n\nRevision: 1\n".encode()
        before_outputs, after_outputs = output_payloads[spec.name]
        write(project, spec.review, before_review)
        for path, payload in before_outputs.items():
            write(project, path, payload)
        before_receipt = owner_receipt(
            spec, project_payload, before_review, before_outputs
        )
        write(project, spec.receipt, before_receipt)

        if spec.name not in scoped_names:
            continue
        after_review = owner_review(review_hash, spec.name, 2)
        after_receipt = owner_receipt(
            spec, project_payload, after_review, after_outputs
        )
        if prepared and impact_values[spec.name] == "CHANGED":
            for candidate_path, output_path in zip(
                PREPARED_CANDIDATE_PATHS[spec.name], spec.outputs, strict=True
            ):
                write(project, candidate_path, after_outputs[output_path])
        after_payloads = {
            spec.review: after_review,
            **after_outputs,
            spec.receipt: after_receipt,
        }
        before_payloads = {
            spec.review: before_review,
            **before_outputs,
            spec.receipt: before_receipt,
        }
        for path in spec.ordered_paths:
            staging_view.write_atomic(path, after_payloads[path])
            operations.append(
                {
                    "owner": spec.name,
                    "action": "WRITE",
                    "path": path,
                    "before": {
                        "state": "FILE",
                        "sha256": RECONCILE.sha256_bytes(before_payloads[path]),
                    },
                    "after": {
                        "state": "FILE",
                        "sha256": RECONCILE.sha256_bytes(after_payloads[path]),
                    },
                }
            )

    operations_by_path = {
        str(item["path"]): item for item in operations if isinstance(item, dict)
    }

    def final_payload(logical_path: str) -> bytes:
        if logical_path in operations_by_path:
            return (project / RECONCILE.stage_path(RUN_ID, logical_path)).read_bytes()
        return (project / logical_path).read_bytes()

    def fingerprint_entry(name: str, package_path: str, payload: bytes) -> dict[str, str]:
        return {
            "name": name,
            "path": package_path,
            "sha256": RECONCILE.sha256_bytes(payload),
        }

    fingerprint_payload = {
        "algorithm": "ai-sow-package-v1",
        "generatorContract": "receipt-only-beta2-v1",
        "projectIdentity": {
            key: PROJECT_VALUE[key]
            for key in ("projectId", "pluginVersion", "sowStandardVersion")
        },
        "project": fingerprint_entry(
            "project",
            ".ai-sow/project.json",
            project_payload,
        ),
        "inputs": [
            fingerprint_entry(name, package_path, final_payload(logical_path))
            for name, logical_path, package_path in RECONCILE.PACKAGE_INPUT_BINDINGS
        ],
        "reviews": [
            fingerprint_entry(name, package_path, final_payload(logical_path))
            for name, logical_path, package_path in RECONCILE.PACKAGE_REVIEW_BINDINGS
        ],
        "validationReceipts": [
            fingerprint_entry(name, package_path, final_payload(logical_path))
            for name, logical_path, package_path in RECONCILE.PACKAGE_RECEIPT_BINDINGS
        ],
        "template": fingerprint_entry(
            "template",
            "sources/templates/sow-template.xlsx",
            TEMPLATE_PAYLOAD,
        ),
    }
    package_fingerprint = RECONCILE.sha256_bytes(
        RECONCILE.canonical_json_bytes(fingerprint_payload)
    )
    package_id = f"sow-sha256-{package_fingerprint}"
    staged_package = f".ai-sow/.stage-{RUN_ID}/outputs/{package_id}"
    logical_package = f".ai-sow/outputs/{package_id}"
    workbook_payload = b"validated-workbook"
    staging_view.write_atomic(f"{logical_package}/sow.xlsx", workbook_payload)

    def package_digest(package_path: str, payload: bytes) -> dict[str, str]:
        staging_view.write_atomic(f"{logical_package}/{package_path}", payload)
        return {"path": package_path, "sha256": RECONCILE.sha256_bytes(payload)}

    package_inputs = {
        name: package_digest(package_path, final_payload(logical_path))
        for name, logical_path, package_path in RECONCILE.PACKAGE_INPUT_BINDINGS
    }
    package_reviews = {
        name: package_digest(package_path, final_payload(logical_path))
        for name, logical_path, package_path in RECONCILE.PACKAGE_REVIEW_BINDINGS
    }
    package_receipts = {
        name: package_digest(package_path, final_payload(logical_path))
        for name, logical_path, package_path in RECONCILE.PACKAGE_RECEIPT_BINDINGS
    }
    template = package_digest("sources/templates/sow-template.xlsx", TEMPLATE_PAYLOAD)
    package_manifest = {
        "packageId": package_id,
        "fingerprintAlgorithm": "ai-sow-package-v1",
        "generationFingerprint": package_fingerprint,
        "generatedWorkbookSha256": RECONCILE.sha256_bytes(workbook_payload),
        "projectId": PROJECT_VALUE["projectId"],
        "pluginVersion": PROJECT_VALUE["pluginVersion"],
        "sowStandardVersion": PROJECT_VALUE["sowStandardVersion"],
        "projectMode": ANALYSIS_SCOPE["mode"],
        "repositories": [
            {
                "repoId": item["repoId"],
                "setupRevision": item["revision"],
            }
            for item in ANALYSIS_SCOPE["repositorySnapshots"]
        ],
        "priorSows": [
            {
                "priorSowId": item["priorSowId"],
                "sha256": item["sha256"],
            }
            for item in ANALYSIS_SCOPE["priorSowSnapshots"]
        ],
        "inputs": package_inputs,
        "reviews": package_reviews,
        "template": template,
        "validationReceipts": package_receipts,
    }
    staging_view.write_atomic(
        f"{logical_package}/manifest.json",
        RECONCILE.canonical_json_bytes(package_manifest),
    )
    tree_hash = RECONCILE.package_tree_sha256(project / staged_package)

    manifest: dict[str, object] = {
        "algorithm": RECONCILE.ALGORITHM,
        "contractVersion": RECONCILE.CONTRACT_VERSION,
        "runId": RUN_ID,
        "startOwner": start_owner,
        "owners": owner_entries,
        "review": {"path": review_path, "sha256": review_hash},
        "approval": {
            "path": approval_path,
            "sha256": RECONCILE.sha256_bytes(approval_payload),
        },
        "writerMode": "SINGLE_WRITER",
        "package": {
            "packageId": package_id,
            "stagedPath": staged_package,
            "finalPath": f".ai-sow/outputs/{package_id}",
            "treeSha256": tree_hash,
        },
        "operations": operations,
    }
    if prepared:
        assembled = RECONCILE.assemble(project, RUN_ID)
        assert assembled["outcome"] == "OK"
        manifest = json.loads(
            (project / f".ai-sow/work/reconcile/{RUN_ID}/redo.json").read_text(
                encoding="utf-8"
            )
        )
    else:
        save_manifest(project, manifest)
    return project, manifest


def write_packet_authorization(project: Path) -> str:
    packet_path = f".ai-sow/work/reconcile/{RUN_ID}/review-packet.json"
    packet_sha256 = RECONCILE.sha256_bytes((project / packet_path).read_bytes())
    work_root = f".ai-sow/work/reconcile/{RUN_ID}"
    write(
        project,
        f"{work_root}/reviewer.json",
        RECONCILE.canonical_json_bytes(
            {
                "algorithm": RECONCILE.REVIEWER_ALGORITHM,
                "decision": "PASS",
                "packetSha256": packet_sha256,
                "runId": RUN_ID,
            }
        ),
    )
    write(
        project,
        f"{work_root}/approval.json",
        RECONCILE.canonical_json_bytes(
            {
                "algorithm": RECONCILE.APPROVAL_ALGORITHM,
                "decision": "APPROVED",
                "packetSha256": packet_sha256,
                "runId": RUN_ID,
            }
        ),
    )
    return packet_sha256


def save_manifest(project: Path, manifest: dict[str, object]) -> None:
    write(
        project,
        f".ai-sow/work/reconcile/{RUN_ID}/redo.json",
        RECONCILE.canonical_json_bytes(manifest),
    )


def operation(manifest: dict[str, object], path: str) -> dict[str, object]:
    operations = manifest["operations"]
    assert isinstance(operations, list)
    return next(item for item in operations if isinstance(item, dict) and item["path"] == path)


def package_id(manifest: dict[str, object]) -> str:
    package = manifest["package"]
    assert isinstance(package, dict)
    return str(package["packageId"])


def package_root(project: Path, manifest: dict[str, object]) -> Path:
    package = manifest["package"]
    assert isinstance(package, dict)
    return project / str(package["stagedPath"])


def refresh_package_tree(project: Path, manifest: dict[str, object]) -> None:
    package = manifest["package"]
    assert isinstance(package, dict)
    package["treeSha256"] = RECONCILE.package_tree_sha256(
        package_root(project, manifest)
    )
    save_manifest(project, manifest)


def refresh_staged_receipt(
    project: Path,
    manifest: dict[str, object],
    owner_name: str,
    *,
    extra_inputs: list[dict[str, str]],
) -> None:
    owner = RECONCILE.OWNER_BY_NAME[owner_name]
    project_payload = (project / ".ai-sow/project.json").read_bytes()
    review_payload = (project / RECONCILE.stage_path(RUN_ID, owner.review)).read_bytes()
    outputs = {
        path: (project / RECONCILE.stage_path(RUN_ID, path)).read_bytes()
        for path in owner.outputs
    }
    receipt_payload = owner_receipt(
        owner,
        project_payload,
        review_payload,
        outputs,
        extra_inputs=extra_inputs,
    )
    write(project, RECONCILE.stage_path(RUN_ID, owner.receipt), receipt_payload)
    receipt_operation = operation(manifest, owner.receipt)
    receipt_operation["after"] = {
        "state": "FILE",
        "sha256": RECONCILE.sha256_bytes(receipt_payload),
    }
    save_manifest(project, manifest)


def run(project: Path, mode: str = "check") -> dict[str, object]:
    return RECONCILE.execute(
        project, f".ai-sow/work/reconcile/{RUN_ID}/redo.json", mode
    )


def test_assemble_freezes_complete_staged_closure_before_authorization(
    tmp_path: Path,
) -> None:
    impacts = {
        "generate-story": "CHANGED",
        "generate-task": "NO_CHANGE",
    }
    project, manifest = build_project(
        tmp_path,
        start_owner="generate-story",
        impacts=impacts,
        story_change="CHANGED",
        story_diff="story-1: before -> after",
        prepared=True,
    )

    work_root = project / f".ai-sow/work/reconcile/{RUN_ID}"
    assert manifest["contractVersion"] == RECONCILE.PREPARED_CONTRACT_VERSION
    assert (work_root / "redo.json").is_file()
    assert (work_root / "diff.json").is_file()
    assert (work_root / "risk-summary.md").is_file()
    assert (work_root / "review-packet.json").is_file()
    assert not (work_root / "reviewer.json").exists()
    assert not (work_root / "approval.json").exists()
    assert not (project / f".ai-sow/.stage-{RUN_ID}/.ai-sow").exists()

    packet = json.loads((work_root / "review-packet.json").read_text(encoding="utf-8"))
    assert packet["algorithm"] == RECONCILE.PACKET_ALGORITHM
    assert packet["runId"] == RUN_ID
    assert packet["startOwner"] == "generate-story"
    assert {item["owner"] for item in packet["stagedArtifacts"]} == {
        "generate-story",
        "generate-task",
    }
    assert packet["candidates"] == [
        {
            "owner": "generate-story",
            "path": ".ai-sow/work/generate-story/delivery.candidate.json",
            "sha256": packet["candidates"][0]["sha256"],
        }
    ]
    assert packet["package"]["treeSha256"] == manifest["package"]["treeSha256"]
    assert packet["redo"]["sha256"] == RECONCILE.sha256_bytes(
        (work_root / "redo.json").read_bytes()
    )
    assert packet["receiptInputs"]

    story = RECONCILE.OWNER_BY_NAME["generate-story"]
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    assert b'"revision":1' in (project / story.outputs[0]).read_bytes()
    assert b'"revision":2' in (
        project / RECONCILE.stage_path(RUN_ID, story.outputs[0])
    ).read_bytes()
    assert (project / task.outputs[0]).read_bytes() == (
        project / RECONCILE.stage_path(RUN_ID, task.outputs[0])
    ).read_bytes()
    assert not (project / str(manifest["package"]["finalPath"])).exists()  # type: ignore[index]

    with pytest.raises(RECONCILE.ReconcileError) as error:
        run(project)
    assert error.value.code == "RECONCILIATION_REVIEWER_MISSING"

    packet_sha256 = write_packet_authorization(project)
    checked = run(project)
    assert checked["publication"] == "CHECKED"
    assert checked["packetSha256"] == packet_sha256
    published = run(project, "publish")
    assert published["publication"] == "PUBLISHED"


@pytest.mark.parametrize(
    "drift",
    ["candidate", "owner-review", "input", "package", "manifest"],
)
def test_preapproved_packet_drift_blocks_publication(
    tmp_path: Path,
    drift: str,
) -> None:
    project, manifest = build_project(tmp_path, prepared=True)
    write_packet_authorization(project)
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    if drift == "candidate":
        write(
            project,
            PREPARED_CANDIDATE_PATHS["generate-task"][0],
            b"candidate drift",
        )
    elif drift == "owner-review":
        write(project, RECONCILE.stage_path(RUN_ID, task.review), b"review drift")
    elif drift == "input":
        write(project, ".ai-sow/project.json", b"input drift")
    elif drift == "package":
        package = manifest["package"]
        assert isinstance(package, dict)
        write(project, f"{package['stagedPath']}/sow.xlsx", b"package drift")
    else:
        redo = project / f".ai-sow/work/reconcile/{RUN_ID}/redo.json"
        redo.write_bytes(redo.read_bytes() + b" ")

    with pytest.raises(RECONCILE.ReconcileError):
        run(project, "publish")
    assert not (project / f".ai-sow/outputs/{package_id(manifest)}").exists()


def test_prepared_packet_requires_exact_reviewer_and_approval_sidecars(
    tmp_path: Path,
) -> None:
    project, _ = build_project(tmp_path, prepared=True)
    packet_sha256 = write_packet_authorization(project)
    (project / f".ai-sow/work/reconcile/{RUN_ID}/approval.json").unlink()
    with pytest.raises(RECONCILE.ReconcileError) as error:
        run(project)
    assert error.value.code == "RECONCILIATION_APPROVAL_MISSING"

    write(
        project,
        f".ai-sow/work/reconcile/{RUN_ID}/approval.json",
        RECONCILE.canonical_json_bytes(
            {
                "algorithm": RECONCILE.APPROVAL_ALGORITHM,
                "decision": "APPROVED",
                "packetSha256": "f" * 64,
                "runId": RUN_ID,
            }
        ),
    )
    with pytest.raises(RECONCILE.ReconcileError) as error:
        run(project)
    assert error.value.code == "RECONCILIATION_APPROVAL_INVALID"
    assert packet_sha256 != "f" * 64


def test_check_and_publish_use_one_fixed_suffix_and_finish_with_task_receipt(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    assert not (project / f".ai-sow/.stage-{RUN_ID}/.ai-sow").exists()
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    receipt_before = (project / task.receipt).read_bytes()

    checked = run(project)

    assert checked["publication"] == "CHECKED"
    assert (project / task.receipt).read_bytes() == receipt_before
    published = run(project, "publish")
    assert published["publication"] == "PUBLISHED"
    assert published["packagePublication"] == "CREATED"
    assert (
        project / f".ai-sow/outputs/{package_id(manifest)}/sow.xlsx"
    ).read_bytes() == b"validated-workbook"
    assert RECONCILE.sha256_bytes((project / task.receipt).read_bytes()) == operation(
        manifest, task.receipt
    )["after"]["sha256"]

    repeated = run(project, "publish")
    assert repeated["publication"] == "REUSED"
    assert repeated["writtenOperations"] == 0


def test_no_change_rebind_preserves_stable_output_bytes(tmp_path: Path) -> None:
    project, _ = build_project(
        tmp_path, impacts={"generate-task": "NO_CHANGE"}
    )
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    before = (project / task.outputs[0]).read_bytes()

    result = run(project, "publish")

    assert result["outcome"] == "OK"
    assert (project / task.outputs[0]).read_bytes() == before


def test_task_cannot_publish_delivery_or_skip_owned_path_order(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    operations = manifest["operations"]
    assert isinstance(operations, list)
    operations[1]["path"] = ".ai-sow/data/generate-story/delivery.json"
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "MANIFEST_OPERATION_SET_INVALID"


def test_approved_review_hash_matrix_blocks_candidate_and_redo_replacement(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    output_path = task.outputs[0]
    staged_path = RECONCILE.stage_path(RUN_ID, output_path)
    replacement = RECONCILE.canonical_json_bytes(
        {"owner": task.name, "output": 0, "revision": 3}
    )
    write(project, staged_path, replacement)
    output_operation = operation(manifest, output_path)
    output_operation["after"] = {
        "state": "FILE",
        "sha256": RECONCILE.sha256_bytes(replacement),
    }
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "HOLISTIC_REVIEW_OUTPUT_HASH_MISMATCH"


def test_review_matrix_rejects_approved_old_new_placeholders(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    review_binding = manifest["review"]
    approval_binding = manifest["approval"]
    assert isinstance(review_binding, dict) and isinstance(approval_binding, dict)
    review_path = str(review_binding["path"])
    lines = (project / review_path).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("| generate-task |"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells[2] = "old"
            cells[3] = "new"
            lines[index] = "| " + " | ".join(cells) + " |"
    review_payload = ("\n".join(lines) + "\n").encode()
    review_hash = RECONCILE.sha256_bytes(review_payload)
    write(project, review_path, review_payload)
    review_binding["sha256"] = review_hash
    approval_path = str(approval_binding["path"])
    approval_payload = RECONCILE.canonical_json_bytes(
        {
            "algorithm": RECONCILE.APPROVAL_ALGORITHM,
            "decision": "APPROVED",
            "reviewSha256": review_hash,
            "runId": RUN_ID,
        }
    )
    write(project, approval_path, approval_payload)
    approval_binding["sha256"] = RECONCILE.sha256_bytes(approval_payload)
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "HOLISTIC_REVIEW_OUTPUT_HASH_MISMATCH"


def test_staged_only_receipt_file_input_blocks_batch(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    input_path = ".ai-sow/inputs/staged-only.md"
    write(project, RECONCILE.stage_path(RUN_ID, input_path), b"not in baseline")
    refresh_staged_receipt(
        project,
        manifest,
        "generate-task",
        extra_inputs=[
            {
                "name": "stagedOnly",
                "kind": "FILE",
                "path": input_path,
                "sha256": RECONCILE.sha256_bytes(b"not in baseline"),
            }
        ],
    )

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "STAGED_ONLY_RECEIPT_INPUT"
    assert not (project / f".ai-sow/outputs/{package_id(manifest)}").exists()


def test_receipt_rejects_unsupported_input_kind(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    refresh_staged_receipt(
        project,
        manifest,
        "generate-task",
        extra_inputs=[
            {
                "name": "unsupported",
                "kind": "BLOB",
                "identity": "blob:unsupported",
                "sha256": "b" * 64,
            }
        ],
    )

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "FINAL_RECEIPT_INVALID"


def test_approval_must_bind_exact_run_and_review_hash(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    approval_path = f".ai-sow/work/reconcile/{RUN_ID}/approval.json"
    changed = {
        "algorithm": RECONCILE.APPROVAL_ALGORITHM,
        "decision": "APPROVED",
        "reviewSha256": "f" * 64,
        "runId": RUN_ID,
    }
    changed_payload = RECONCILE.canonical_json_bytes(changed)
    write(project, approval_path, changed_payload)
    approval = manifest["approval"]
    assert isinstance(approval, dict)
    approval["sha256"] = RECONCILE.sha256_bytes(changed_payload)
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "APPROVAL_BINDING_MISMATCH"


@pytest.mark.parametrize("mode", ["check", "publish"])
def test_missing_approval_blocks_before_package_or_owner_publication(
    tmp_path: Path,
    mode: str,
) -> None:
    project, manifest = build_project(tmp_path)
    before = {
        str(item["path"]): (project / str(item["path"])).read_bytes()
        for item in manifest["operations"]
        if isinstance(item, dict)
    }
    approval = manifest["approval"]
    assert isinstance(approval, dict)
    (project / str(approval["path"])).unlink()

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project, mode)

    assert captured.value.code == "APPROVAL_INVALID"
    assert not (project / f".ai-sow/outputs/{package_id(manifest)}").exists()
    assert {
        path: (project / path).read_bytes() for path in before
    } == before


def test_holistic_correction_owner_must_match_manifest_start_owner(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    review = manifest["review"]
    approval = manifest["approval"]
    assert isinstance(review, dict) and isinstance(approval, dict)
    review_path = str(review["path"])
    review_payload = (project / review_path).read_bytes().replace(
        b"Correction Owner: generate-task",
        b"Correction Owner: generate-story",
    )
    review_hash = RECONCILE.sha256_bytes(review_payload)
    write(project, review_path, review_payload)
    review["sha256"] = review_hash
    approval_path = str(approval["path"])
    approval_payload = RECONCILE.canonical_json_bytes(
        {
            "algorithm": RECONCILE.APPROVAL_ALGORITHM,
            "decision": "APPROVED",
            "reviewSha256": review_hash,
            "runId": RUN_ID,
        }
    )
    write(project, approval_path, approval_payload)
    approval["sha256"] = RECONCILE.sha256_bytes(approval_payload)
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "HOLISTIC_REVIEW_OWNER_MISMATCH"


def test_third_hash_conflict_blocks_before_package_or_owner_publication(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    write(project, task.review, b"third-state")
    estimate_before = (project / task.outputs[0]).read_bytes()

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project, "publish")

    assert captured.value.code == "THIRD_HASH_CONFLICT"
    assert not (project / f".ai-sow/outputs/{package_id(manifest)}").exists()
    assert (project / task.outputs[0]).read_bytes() == estimate_before


def test_forward_recovery_accepts_only_an_after_prefix(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    operations = manifest["operations"]
    assert isinstance(operations, list)
    first = operations[0]
    assert isinstance(first, dict)
    staged = RECONCILE.stage_path(RUN_ID, str(first["path"]))
    write(project, str(first["path"]), (project / staged).read_bytes())

    recovered = run(project, "publish")

    assert recovered["publication"] == "RECOVERED"
    assert recovered["writtenOperations"] == len(operations) - 1

    project2, manifest2 = build_project(tmp_path / "out-of-order")
    operations2 = manifest2["operations"]
    assert isinstance(operations2, list)
    second = operations2[1]
    assert isinstance(second, dict)
    staged2 = RECONCILE.stage_path(RUN_ID, str(second["path"]))
    write(project2, str(second["path"]), (project2 / staged2).read_bytes())

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project2)

    assert captured.value.code == "PUBLISH_SEQUENCE_CONFLICT"


def test_package_failure_leaves_all_owner_paths_at_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, manifest = build_project(tmp_path)
    before = {
        str(item["path"]): (project / str(item["path"])).read_bytes()
        for item in manifest["operations"]
        if isinstance(item, dict)
    }

    def fail_package(*_args: object, **_kwargs: object) -> None:
        raise RECONCILE.ReconcileError(
            "PACKAGE_PUBLICATION_UNSUPPORTED",
            f".ai-sow/outputs/{package_id(manifest)}",
            "simulated package failure",
        )

    monkeypatch.setattr(RECONCILE, "publish_package", fail_package)
    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project, "publish")

    assert captured.value.code == "PACKAGE_PUBLICATION_UNSUPPORTED"
    assert {
        path: (project / path).read_bytes() for path in before
    } == before


def test_package_manifest_must_be_canonical_and_bind_identity_and_workbook_bytes(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    manifest_path = package_root(project, manifest) / "manifest.json"
    package_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    refresh_package_tree(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "PACKAGE_MANIFEST_NOT_CANONICAL"

    project2, manifest2 = build_project(tmp_path / "workbook")
    package2 = manifest2["package"]
    assert isinstance(package2, dict)
    write(
        project2,
        f"{package2['stagedPath']}/sow.xlsx",
        b"wrong-workbook",
    )
    refresh_package_tree(project2, manifest2)

    with pytest.raises(RECONCILE.ReconcileError) as workbook_error:
        run(project2)

    assert workbook_error.value.code == "PACKAGE_WORKBOOK_HASH_MISMATCH"



def test_fake_but_self_consistent_package_fingerprint_is_blocked(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    old_root = package_root(project, manifest)
    fake_fingerprint = "f" * 64
    assert fake_fingerprint != package_id(manifest).removeprefix("sow-sha256-")
    fake_package_id = f"sow-sha256-{fake_fingerprint}"
    package = manifest["package"]
    assert isinstance(package, dict)
    fake_staged_path = f".ai-sow/.stage-{RUN_ID}/outputs/{fake_package_id}"
    fake_root = project / fake_staged_path
    old_root.rename(fake_root)
    package_manifest_path = fake_root / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["generationFingerprint"] = fake_fingerprint
    package_manifest["packageId"] = fake_package_id
    package_manifest_path.write_bytes(RECONCILE.canonical_json_bytes(package_manifest))
    package.update(
        {
            "packageId": fake_package_id,
            "stagedPath": fake_staged_path,
            "finalPath": f".ai-sow/outputs/{fake_package_id}",
        }
    )
    refresh_package_tree(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "PACKAGE_FINGERPRINT_MISMATCH"


def test_package_template_digest_must_match_formal_template(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    root = package_root(project, manifest)
    changed_template = b"tampered-package-template"
    (root / "sources/templates/sow-template.xlsx").write_bytes(changed_template)
    package_manifest_path = root / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["template"]["sha256"] = RECONCILE.sha256_bytes(  # type: ignore[index]
        changed_template
    )
    package_manifest_path.write_bytes(RECONCILE.canonical_json_bytes(package_manifest))
    refresh_package_tree(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "PACKAGE_TEMPLATE_HASH_MISMATCH"


def test_package_metadata_and_asis_projection_must_match_final_view(
    tmp_path: Path,
) -> None:
    project, manifest = build_project(tmp_path)
    root = package_root(project, manifest)
    package_manifest_path = root / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["projectId"] = "drifted-project"
    package_manifest_path.write_bytes(RECONCILE.canonical_json_bytes(package_manifest))
    refresh_package_tree(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as metadata_error:
        run(project)

    assert metadata_error.value.code == "PACKAGE_METADATA_MISMATCH"

    project2, manifest2 = build_project(tmp_path / "asis")
    root2 = package_root(project2, manifest2)
    package_manifest_path2 = root2 / "manifest.json"
    package_manifest2 = json.loads(package_manifest_path2.read_text(encoding="utf-8"))
    package_manifest2["projectMode"] = "GREENFIELD"
    package_manifest_path2.write_bytes(
        RECONCILE.canonical_json_bytes(package_manifest2)
    )
    refresh_package_tree(project2, manifest2)

    with pytest.raises(RECONCILE.ReconcileError) as asis_error:
        run(project2)

    assert asis_error.value.code == "PACKAGE_ASIS_PROJECTION_MISMATCH"


def test_package_receipt_digest_must_match_final_owner_view(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    root = package_root(project, manifest)
    receipt_path = root / "validation/generate-task.json"
    wrong_receipt = RECONCILE.canonical_json_bytes({"not": "the final receipt"})
    receipt_path.write_bytes(wrong_receipt)
    package_manifest_path = root / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["validationReceipts"]["generateTask"]["sha256"] = (  # type: ignore[index]
        RECONCILE.sha256_bytes(wrong_receipt)
    )
    package_manifest_path.write_bytes(RECONCILE.canonical_json_bytes(package_manifest))
    refresh_package_tree(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "PACKAGE_FINAL_VIEW_HASH_MISMATCH"


def test_delete_publishes_only_an_existing_owner_optional_path(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path, start_owner="analyze-requirement")
    questionnaire = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire_payload = b"approved questionnaire superseded by the changed requirements"
    write(project, questionnaire, questionnaire_payload)
    operations = manifest["operations"]
    assert isinstance(operations, list)
    operations.insert(
        0,
        {
            "owner": "analyze-requirement",
            "action": "DELETE",
            "path": questionnaire,
            "before": {
                "state": "FILE",
                "sha256": RECONCILE.sha256_bytes(questionnaire_payload),
            },
            "after": {"state": "MISSING"},
        },
    )
    staging_view = RECONCILE.ProjectFiles.open_view(
        project,
        f".ai-sow/.stage-{RUN_ID}",
    )
    staging_view.tombstone(questionnaire)
    save_manifest(project, manifest)

    result = run(project, "publish")

    assert result["publication"] == "PUBLISHED"
    assert not (project / questionnaire).exists()


def test_delete_without_tombstone_is_blocked(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path, start_owner="analyze-requirement")
    questionnaire = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire_payload = b"questionnaire still visible through the base layer"
    write(project, questionnaire, questionnaire_payload)
    operations = manifest["operations"]
    assert isinstance(operations, list)
    operations.insert(
        0,
        {
            "owner": "analyze-requirement",
            "action": "DELETE",
            "path": questionnaire,
            "before": {
                "state": "FILE",
                "sha256": RECONCILE.sha256_bytes(questionnaire_payload),
            },
            "after": {"state": "MISSING"},
        },
    )
    save_manifest(project, manifest)

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "DELETE_TOMBSTONE_REQUIRED"


def test_manifest_must_be_canonical_json(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    manifest_path = f".ai-sow/work/reconcile/{RUN_ID}/redo.json"
    write(
        project,
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
    )

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "REDO_MANIFEST_NOT_CANONICAL"


def test_owner_review_must_bind_approved_holistic_hash(tmp_path: Path) -> None:
    project, manifest = build_project(tmp_path)
    task = RECONCILE.OWNER_BY_NAME["generate-task"]
    staged_review = RECONCILE.stage_path(RUN_ID, task.review)
    changed_review = (project / staged_review).read_bytes().replace(
        str(manifest["review"]["sha256"]).encode(), b"f" * 64
    )
    write(project, staged_review, changed_review)
    review_operation = operation(manifest, task.review)
    review_operation["after"] = {
        "state": "FILE",
        "sha256": RECONCILE.sha256_bytes(changed_review),
    }
    refresh_staged_receipt(
        project, manifest, "generate-task", extra_inputs=[]
    )

    with pytest.raises(RECONCILE.ReconcileError) as captured:
        run(project)

    assert captured.value.code == "OWNER_REVIEW_HASH_MISMATCH"
