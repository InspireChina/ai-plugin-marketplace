from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


PLUGIN_ROOT = Path(__file__).parents[3]
SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts/validate.py"
CONTEXT_SCRIPT = SKILL_ROOT / "scripts/prepare_context.py"
FACTS_SCRIPT = SKILL_ROOT / "scripts/project_facts.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_review.py"
GREENFIELD_FIXTURE = SKILL_ROOT / "fixtures/asis.valid.json"
BROWNFIELD_FIXTURE = SKILL_ROOT / "fixtures/asis.brownfield.valid.json"
E2E_DESCRIPTOR = SKILL_ROOT / "fixtures/e2e-cases/explicit-architecture.json"
SOURCE_BYTES = "客户需要统一创建、查询和维护客户档案。\n".encode()
PRIOR_SOW_BYTES = b"Phase one prior SOW fixture.\n"

if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.handoff import Artifact, OwnerContract, canonical_json_bytes, publish_owner, sha256_bytes
from runtime.project_io import ProjectFiles


REQUIREMENT_CONTRACT = OwnerContract(
    subject="analyze-requirement",
    contract_ids=("urn:ai-sow:analyze-requirement:source-requirements:0.1",),
    validation_path=".ai-sow/validation/analyze-requirement.json",
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-requirement.md"),),
    outputs=(("requirements", ".ai-sow/data/analyze-requirement/requirements.json"),),
)


def write_bytes(project_root: Path, relative: str, payload: bytes) -> None:
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def write_json(project_root: Path, relative: str, payload: object) -> bytes:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode() + b"\n"
    write_bytes(project_root, relative, content)
    return content


def project_payload() -> dict[str, str]:
    return {
        "projectId": "customer-portal",
        "name": "客户门户",
        "pluginVersion": "0.1.0-beta.1",
        "sowStandardVersion": "1.3",
    }


def requirements_payload() -> dict[str, Any]:
    return {
        "sourceDocuments": [
            {
                "sourceDocumentId": "source-document-customer-profile",
                "name": "客户档案需求输入",
                "file": ".ai-sow/inputs/analyze-requirement/customer-profile.txt",
                "originalName": "customer-profile.txt",
                "sha256": hashlib.sha256(SOURCE_BYTES).hexdigest(),
            }
        ],
        "normalizedItems": [
            {
                "normalizedItemId": "norm-customer-profile",
                "sourceDocumentId": "source-document-customer-profile",
                "name": "客户档案",
                "statement": "客户需要维护客户档案。",
            }
        ],
        "epics": [
            {
                "epicId": "epic-customer-management",
                "type": "BUSINESS",
                "name": "客户管理",
                "description": "统一维护客户信息。",
                "source": {"type": "SOURCE_INPUT", "normalizedItemIds": ["norm-customer-profile"]},
            }
        ],
        "features": [
            {
                "featureId": "feature-customer-profile",
                "epicId": "epic-customer-management",
                "name": "客户档案维护",
                "description": "用户创建并查询客户档案。",
                "source": {"type": "SOURCE_INPUT", "normalizedItemIds": ["norm-customer-profile"]},
            }
        ],
    }


def publish_requirement(
    project_root: Path,
    payload: dict[str, Any] | None = None,
    *,
    review_suffix: str = "",
) -> None:
    data = payload or requirements_payload()
    project = write_json(project_root, ".ai-sow/project.json", project_payload())
    write_bytes(
        project_root,
        ".ai-sow/inputs/analyze-requirement/customer-profile.txt",
        SOURCE_BYTES,
    )
    write_bytes(
        project_root,
        ".ai-sow/reviews/analyze-requirement.md",
        ("Questionnaire: NOT_REQUIRED\nReviewer: PASS\nUser Approval: APPROVED\n" + review_suffix).encode(),
    )
    files = ProjectFiles.open(project_root)
    inputs = (
        Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(project)),
        Artifact(
            "source:source-document-customer-profile",
            "FILE",
            ".ai-sow/inputs/analyze-requirement/customer-profile.txt",
            sha256_bytes(SOURCE_BYTES),
        ),
        Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            "questionnaire:NOT_REQUIRED",
            sha256_bytes(canonical_json_bytes({"declaration": "NOT_REQUIRED"})),
        ),
    )
    publish_owner(
        files,
        REQUIREMENT_CONTRACT,
        inputs,
        {"requirements": json.dumps(data, ensure_ascii=False, indent=2).encode() + b"\n"},
    )


def stable_ids(payload: dict[str, Any]) -> list[str]:
    return [
        *(entry["asIsItemId"] for entry in payload["items"]),
        *(entry["commitmentId"] for entry in payload["commitments"]),
        *(entry["effectiveStartItemId"] for entry in payload["effectiveStartItems"]),
        *(entry["uncertaintyId"] for entry in payload["uncertainties"]),
        *(entry["evidenceId"] for entry in payload["evidence"]),
    ]


def approved_review(
    payload: dict[str, Any],
    *,
    questionnaire: str = "NOT_REQUIRED",
    questionnaire_ids: str = "NONE",
    questionnaire_records: str = "",
    impact: str | None = None,
    previous_receipt_sha256: str | None = None,
    current_receipt_sha256: str | None = None,
    impact_rationale: str | None = None,
) -> str:
    ids = stable_ids(payload)

    def name_projection(collection: str, id_field: str, id_header: str) -> str:
        rows = payload[collection]
        return "\n".join(
            [
                f"| {id_header} | 名称 |",
                "|---|---|",
                *(
                    f"| {entry[id_field]} | {entry['name']} |"
                    for entry in rows
                ),
            ]
        )

    impact_line = ""
    if impact:
        impact_line = (
            "Upstream: analyze-requirement\n"
            f"Previous Receipt SHA-256: {previous_receipt_sha256 or '0' * 64}\n"
            f"Current Receipt SHA-256: {current_receipt_sha256 or '0' * 64}\n"
            f"Impact: {impact}\n"
            f"Impact Rationale: {impact_rationale or '确认不受影响的稳定 ID: ' + (', '.join(ids) if ids else 'NONE') + '。'}\n"
        )
    sections = (
        ("调查范围", "本次调查范围与登记输入已确认。"),
        ("九个 Topic", "九个 Topic 均已逐项评估。"),
        ("Item", "当前 Item 结论已核对。"),
        (
            "Commitment",
            "往期承诺与处置已核对。\n\n"
            + name_projection("commitments", "commitmentId", "Commitment"),
        ),
        ("Effective Start", "生效起点已确认。"),
        ("Coverage", "每个 BUSINESS Feature 均有 Coverage。"),
        (
            "Uncertainty",
            "不确定性及估算影响已记录。\n\n"
            + name_projection("uncertainties", "uncertaintyId", "Uncertainty"),
        ),
        (
            "Evidence",
            "结论均有证据或明确不确定性。\n\n"
            + name_projection("evidence", "evidenceId", "Evidence"),
        ),
        (
            "问卷记录",
            f"Questionnaire: {questionnaire}\nQuestionnaire IDs: {questionnaire_ids}"
            + (f"\n\n{questionnaire_records.strip()}" if questionnaire_records else ""),
        ),
        (
            "审查与批准",
            f"Stable IDs: {', '.join(ids) if ids else 'NONE'}\n{impact_line}Reviewer: PASS\nUser Approval: APPROVED",
        ),
    )
    return "# 现状评审\n\n" + "\n\n".join(
        f"## {heading}\n\n{body}" for heading, body in sections
    ) + "\n"


def prepare_greenfield(project_root: Path) -> dict[str, Any]:
    project_root.mkdir(parents=True, exist_ok=True)
    publish_requirement(project_root)
    payload = json.loads(GREENFIELD_FIXTURE.read_text(encoding="utf-8"))
    write_json(project_root, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    write_premises(project_root)
    write_bytes(project_root, ".ai-sow/reviews/analyze-as-is.md", approved_review(payload).encode())
    return payload


def prepare_brownfield(project_root: Path) -> dict[str, Any]:
    project_root.mkdir(parents=True, exist_ok=True)
    publish_requirement(project_root)
    repository = project_root / "repositories/service-api"
    (repository / "src/customer").mkdir(parents=True)
    (repository / "src/customer/profile.py").write_text(
        "class CustomerProfileReader:\n    pass\n",
        encoding="utf-8",
    )
    write_bytes(
        project_root,
        ".ai-sow/inputs/analyze-as-is/prior-sows/sow-phase-one.md",
        PRIOR_SOW_BYTES,
    )
    payload = json.loads(BROWNFIELD_FIXTURE.read_text(encoding="utf-8"))
    write_json(project_root, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    write_premises(project_root)
    write_bytes(project_root, ".ai-sow/reviews/analyze-as-is.md", approved_review(payload).encode())
    return payload


def write_premises(project_root: Path) -> None:
    write_json(
        project_root,
        ".ai-sow/work/analyze-as-is/premises.json",
        {
            "algorithm": "ai-sow-review-premises-v1",
            "owner": "analyze-as-is",
            "hypothesis": "沿用已确认的客户档案起点并补齐目标能力。",
            "factFamilies": [
                "modules",
                "deploymentResources",
                "criticalConfiguration",
                "springProfiles",
                "migrationTables",
                "ciWorkflows",
            ],
            "premises": [
                {
                    "premiseId": "premise-existing-customer-start",
                    "text": "已登记现状足以作为客户档案工作的起点。",
                    "falsificationMethod": "核对登记仓库和往期承诺。",
                    "verdict": "SUPPORTED",
                    "impact": "可继续形成现状起点与差异。",
                    "anchorPaths": [],
                }
            ],
        },
    )


def run_validator(
    project_root: Path,
    mode: str,
    *,
    review_override: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--project-root",
        str(project_root),
        "--mode",
        mode,
        "--candidate",
        ".ai-sow/work/analyze-as-is/asis.candidate.json",
    ]
    if review_override is not None:
        command.extend(("--review-path", review_override))
    if mode in {"publish", "rebind"}:
        command.extend(("--staging-root", STAGING_ROOT))
    return subprocess.run(
        command,
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


STAGING_ROOT = ".ai-sow/.stage-0123456789ab"


def managed_path(project_root: Path, logical_path: str) -> Path:
    staged = project_root / STAGING_ROOT / logical_path.removeprefix(".ai-sow/")
    return staged if staged.exists() else project_root / logical_path


def run_context(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CONTEXT_SCRIPT),
            "--project-root",
            str(project_root),
        ],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def run_renderer(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--project-root",
            str(project_root),
        ],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def run_project_facts(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FACTS_SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def prepare_review_candidate(project_root: Path) -> tuple[bytes, bytes]:
    payload = prepare_brownfield(project_root)
    resolve_estimate_readiness(payload)
    write_json(project_root, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    (project_root / ".ai-sow/reviews/analyze-as-is.md").unlink()
    context = run_context(project_root)
    assert context.returncode == 0, context.stdout + context.stderr
    rendered = run_renderer(project_root)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    return (
        (project_root / ".ai-sow/work/analyze-as-is/asis.candidate.json").read_bytes(),
        (project_root / ".ai-sow/work/analyze-as-is/review.candidate.md").read_bytes(),
    )


def resolve_estimate_readiness(payload: dict[str, Any]) -> None:
    resolved_ids = {
        entry["uncertaintyId"]
        for entry in payload["uncertainties"]
        if entry["affectsEstimate"] is True
    }
    for entry in payload["uncertainties"]:
        if entry["uncertaintyId"] in resolved_ids:
            entry["affectsEstimate"] = False
    for assessment in payload["topicAssessments"]:
        if resolved_ids.intersection(assessment["uncertaintyIds"]):
            assessment["status"] = "BOUNDARY_DECLARED"


def bind_review_packet(project_root: Path) -> str:
    packet = (project_root / ".ai-sow/work/analyze-as-is/review-packet.json").read_bytes()
    digest = sha256_bytes(packet)
    for path, algorithm, decision in (
        (
            ".ai-sow/work/analyze-as-is/reviewer.json",
            "ai-sow-owner-reviewer-v1",
            "PASS",
        ),
        (
            ".ai-sow/work/analyze-as-is/approval.json",
            "ai-sow-owner-approval-v1",
            "APPROVED",
        ),
    ):
        write_bytes(
            project_root,
            path,
            canonical_json_bytes(
                {
                    "algorithm": algorithm,
                    "decision": decision,
                    "owner": "analyze-as-is",
                    "packetSha256": digest,
                }
            ),
        )
    return digest


def write_candidate(project_root: Path, payload: dict[str, Any]) -> None:
    write_json(project_root, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    write_bytes(project_root, ".ai-sow/reviews/analyze-as-is.md", approved_review(payload).encode())


def codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {entry["code"] for entry in json.loads(result.stdout)["diagnostics"]}


def validation_report(project_root: Path) -> dict[str, Any]:
    return json.loads(
        managed_path(project_root, ".ai-sow/validation/analyze-as-is.json").read_text(encoding="utf-8")
    )


def test_review_template_has_complete_contract() -> None:
    text = (SKILL_ROOT / "references/review-template.md").read_text(encoding="utf-8")
    for section in (
        "调查范围", "九个 Topic", "Item", "Commitment", "Effective Start",
        "Coverage", "Uncertainty", "Evidence", "问卷记录", "审查与批准",
    ):
        assert f"## {section}" in text
    for declaration in (
        "Questionnaire:", "Questionnaire IDs:", "Stable IDs:",
        "Reviewer: PASS", "User Approval: APPROVED",
    ):
        assert declaration in text
    assert "Finding 严重度下限" in text
    assert "只报告违反合同" in text
    assert "只在 Evidence 摘要或对应工作记录中维护一份权威陈述" in text
    assert "ID 和名称" in text


def test_renderer_projects_named_review_identities(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)

    result = run_renderer(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    review = (
        tmp_path / ".ai-sow/work/analyze-as-is/review.candidate.md"
    ).read_text(encoding="utf-8")
    for section, collection, id_field in (
        ("Commitment", "commitments", "commitmentId"),
        ("Uncertainty", "uncertainties", "uncertaintyId"),
        ("Evidence", "evidence", "evidenceId"),
    ):
        assert f"| {section} | 名称 |" in review
        for entry in payload[collection]:
            assert f"| {entry[id_field]} | {entry['name']} |" in review


def test_check_rejects_missing_named_review_identity(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/analyze-as-is.md"
    entry = payload["uncertainties"][0]
    review_path.write_text(
        review_path.read_text(encoding="utf-8").replace(
            f"| {entry['uncertaintyId']} | {entry['name']} |",
            f"| {entry['uncertaintyId']} | 名称未投影 |",
        ),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "REVIEW_NAME_PROJECTION_MISSING" in codes(result)


@pytest.mark.parametrize("fixture", ["greenfield", "brownfield"])
def test_check_accepts_canonical_fixture_without_writes(tmp_path: Path, fixture: str) -> None:
    (prepare_greenfield if fixture == "greenfield" else prepare_brownfield)(tmp_path)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").exists()
    assert not (tmp_path / ".ai-sow/validation/analyze-as-is.json").exists()


def test_check_accepts_work_review_override_and_reports_its_path(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    work_review = ".ai-sow/work/analyze-as-is/reconcile-review.md"
    work_review_path = tmp_path / work_review
    write_bytes(tmp_path, work_review, approved_review(payload).encode())
    write_bytes(tmp_path, ".ai-sow/reviews/analyze-as-is.md", b"not the approved review")

    result = run_validator(tmp_path, "check", review_override=work_review)

    assert result.returncode == 0, result.stdout + result.stderr
    write_bytes(
        tmp_path,
        work_review,
        approved_review(payload).replace("Reviewer: PASS", "Reviewer: FINDINGS").encode(),
    )
    result = run_validator(tmp_path, "check", review_override=work_review)
    finding = next(
        item
        for item in json.loads(result.stdout)["diagnostics"]
        if item["code"] == "REVIEW_NOT_PASSED"
    )
    assert finding["path"] == work_review
    assert work_review_path.exists()


def test_check_without_override_still_reads_formal_review(tmp_path: Path) -> None:
    prepare_greenfield(tmp_path)
    write_bytes(
        tmp_path,
        ".ai-sow/work/analyze-as-is/reconcile-review.md",
        b"not an approved review",
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_non_default_review_path_is_rejected_by_legacy_write_modes(
    tmp_path: Path, mode: str,
) -> None:
    payload = prepare_greenfield(tmp_path)
    work_review = ".ai-sow/work/analyze-as-is/reconcile-review.md"
    write_bytes(tmp_path, work_review, approved_review(payload).encode())
    write_bytes(tmp_path, ".ai-sow/validation/analyze-as-is.json", b"baseline validation\n")

    result = run_validator(tmp_path, mode, review_override=work_review)

    assert result.returncode == 2
    finding = next(
        item
        for item in json.loads(result.stdout)["diagnostics"]
        if item["code"] == "REVIEW_PATH_MODE_INVALID"
    )
    assert finding["message"] == (
        "--review-path override is allowed only in check, review, or publish-approved mode"
    )
    assert finding["path"] == work_review
    assert (tmp_path / ".ai-sow/validation/analyze-as-is.json").read_bytes() == b"baseline validation\n"


@pytest.mark.parametrize("unsafe", ["/tmp/review.md", "../review.md", r"work\review.md"])
def test_check_rejects_unsafe_review_path(tmp_path: Path, unsafe: str) -> None:
    prepare_greenfield(tmp_path)

    result = run_validator(tmp_path, "check", review_override=unsafe)

    assert result.returncode == 2
    assert json.loads(result.stdout)["diagnostics"] == [
        {
            "code": "REVIEW_PATH_INVALID",
            "message": "--review-path must be a POSIX project-relative path without traversal",
            "path": unsafe,
        }
    ]


def test_publish_preserves_candidate_bytes_and_binds_named_inputs(tmp_path: Path) -> None:
    prepare_brownfield(tmp_path)
    candidate = (tmp_path / ".ai-sow/work/analyze-as-is/asis.candidate.json").read_bytes()

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/analyze-as-is/asis.json").read_bytes() == candidate
    receipt = validation_report(tmp_path)["compilationReceipt"]
    assert receipt["validatorContractVersion"] == "0.3"
    assert receipt["contractIds"] == ["urn:ai-sow:analyze-as-is:asis:0.2"]
    assert {entry["name"] for entry in receipt["inputs"]} == {
        "project", "requirementsValidation", "requirements",
        "repository:service-api", "priorSow:sow-phase-one",
        "evidence:evidence-customer-api-code", "questionnaire",
    }


def test_upstream_check_succeeds_without_candidate_and_is_read_only(tmp_path: Path) -> None:
    publish_requirement(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = run_validator(tmp_path, "upstream-check")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {
        "outcome": "OK",
        "summary": "analyze-requirement handoff is valid",
        "diagnostics": [],
        "outputs": [],
    }
    assert not (tmp_path / ".ai-sow/work/analyze-as-is/asis.candidate.json").exists()
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_upstream_check_reports_handoff_error_without_candidate_diagnostic(
    tmp_path: Path,
) -> None:
    publish_requirement(tmp_path)
    (tmp_path / ".ai-sow/validation/analyze-requirement.json").unlink()

    result = run_validator(tmp_path, "upstream-check")

    assert result.returncode == 2
    assert codes(result) == {"UPSTREAM_HANDOFF_MISSING"}
    assert "CANDIDATE_UNREADABLE" not in result.stdout


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("missing", "UPSTREAM_HANDOFF_MISSING"),
        ("invalid", "UPSTREAM_HANDOFF_INVALID"),
        ("stale", "UPSTREAM_HANDOFF_STALE"),
        ("unsupported", "UPSTREAM_CONTRACT_UNSUPPORTED"),
    ),
)
def test_requirement_handoff_reports_only_four_stable_errors(
    tmp_path: Path, mutation: str, expected: str,
) -> None:
    prepare_greenfield(tmp_path)
    report_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    if mutation == "missing":
        report_path.unlink()
    elif mutation == "invalid":
        report_path.write_text('{"owner":"analyze-requirement"}\n', encoding="utf-8")
    elif mutation == "stale":
        requirements = tmp_path / ".ai-sow/data/analyze-requirement/requirements.json"
        requirements.write_bytes(requirements.read_bytes() + b" ")
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["compilationReceipt"]["validatorContractVersion"] = "0.2"
        report_path.write_text(json.dumps(report), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert codes(result) == {expected}
    diagnostic = json.loads(result.stdout)["diagnostics"][0]
    assert diagnostic["upstreamOwner"] == "analyze-requirement"
    assert not any(code.startswith(("SOURCE_", "EPIC_", "NORMALIZED_")) for code in codes(result))


def test_requirement_handoff_rejects_tampered_empty_input_set(tmp_path: Path) -> None:
    prepare_greenfield(tmp_path)
    report_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["compilationReceipt"]["inputs"] = []
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert codes(result) == {"UPSTREAM_HANDOFF_INVALID"}


def test_requirement_handoff_rejects_extra_missing_input_as_invalid(tmp_path: Path) -> None:
    prepare_greenfield(tmp_path)
    report_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["compilationReceipt"]["inputs"].append(
        {
            "name": "extra",
            "kind": "FILE",
            "path": ".ai-sow/missing-extra.txt",
            "sha256": "0" * 64,
        }
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert codes(result) == {"UPSTREAM_HANDOFF_INVALID"}


def test_requirement_output_structure_change_is_stale(tmp_path: Path) -> None:
    prepare_greenfield(tmp_path)
    requirements_path = tmp_path / ".ai-sow/data/analyze-requirement/requirements.json"
    requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
    requirements["sourceDocuments"].append(
        {
            "sourceDocumentId": "source-document-late",
            "name": "后补需求输入",
            "file": ".ai-sow/inputs/analyze-requirement/late.txt",
            "originalName": "late.txt",
            "sha256": "0" * 64,
        }
    )
    requirements_path.write_text(json.dumps(requirements), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert codes(result) == {"UPSTREAM_HANDOFF_STALE"}


def test_invalid_report_owner_precedes_changed_output(tmp_path: Path) -> None:
    prepare_greenfield(tmp_path)
    report_path = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["owner"] = "wrong-owner"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    requirements = tmp_path / ".ai-sow/data/analyze-requirement/requirements.json"
    requirements.write_bytes(requirements.read_bytes() + b" ")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert codes(result) == {"UPSTREAM_HANDOFF_INVALID"}


def test_does_not_replay_requirement_business_diagnostics(tmp_path: Path) -> None:
    requirements = requirements_payload()
    requirements["normalizedItems"][0]["sourceDocumentId"] = "source-document-unknown"
    publish_requirement(tmp_path, requirements)
    payload = json.loads(GREENFIELD_FIXTURE.read_text(encoding="utf-8"))
    write_json(tmp_path, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    write_bytes(tmp_path, ".ai-sow/reviews/analyze-as-is.md", approved_review(payload).encode())

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("topic", "TOPIC_ASSESSMENTS_INVALID"),
        ("uncertainty", "TOPIC_UNCERTAINTY_REQUIRED"),
        ("coverage", "COVERAGE_MISSING"),
        ("effective-start", "EFFECTIVE_START_COMMITMENT_INELIGIBLE"),
        ("commitment", "COMMITMENT_TREATMENT_INVALID"),
        ("evidence", "EVIDENCE_REF_UNKNOWN"),
    ),
)
def test_owner_local_relations_fail_closed(tmp_path: Path, mutation: str, expected: str) -> None:
    payload = prepare_brownfield(tmp_path)
    if mutation == "topic":
        payload["topicAssessments"].pop()
    elif mutation == "uncertainty":
        payload["topicAssessments"][4]["uncertaintyIds"] = []
    elif mutation == "coverage":
        payload["coverage"] = []
    elif mutation == "effective-start":
        payload["effectiveStartItems"][0]["commitmentIds"] = ["commitment-loyalty-profile"]
    elif mutation == "commitment":
        payload["commitments"][0]["implementationStatus"] = "IMPLEMENTED"
    else:
        payload["evidence"][0]["supportsIds"] = ["asis-unknown"]
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert expected in codes(result)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("uncertainty-topic-backlink", "UNCERTAINTY_TOPIC_UNLINKED"),
        (
            "coverage-rationale-commitment",
            "COVERAGE_RATIONALE_CITES_UNLISTED_COMMITMENT",
        ),
        ("count-word", "COUNT_WORD_MISMATCH"),
        ("cross-object-number", "CROSS_OBJECT_NUMBER_DRIFT"),
        ("effective-start-stable-id", "DISPLAY_SUMMARY_STABLE_ID"),
    ),
)
def test_narrative_consistency_checks_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    if mutation == "uncertainty-topic-backlink":
        payload["topicAssessments"][4]["status"] = "RELEVANT_INVESTIGATED"
        payload["topicAssessments"][4]["uncertaintyIds"] = []
    elif mutation == "coverage-rationale-commitment":
        payload["coverage"][0]["commitmentIds"] = []
        payload["coverage"][0]["rationale"] = (
            "当前 API 可复用，但 commitment-loyalty-profile 仍属于延续范围。"
        )
    elif mutation == "count-word":
        payload["topicAssessments"][2]["summary"] = (
            "已核对四类材料：源码、配置、部署、契约、工作流、脚本。"
        )
    elif mutation == "cross-object-number":
        payload["evidence"][0]["summary"] = (
            "CodeGraph 索引覆盖 120 个文件和 800 个节点。"
        )
        payload["topicAssessments"][2]["summary"] = (
            "evidence-customer-api-code 显示 CodeGraph 索引覆盖 121 个文件和 800 个节点。"
        )
    else:
        payload["effectiveStartItems"][0]["summary"] = (
            "项目开工时可依赖 asis-customer-api，但不含写入能力。"
        )
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert expected in codes(result)


def test_registered_prior_sow_and_evidence_anchor_are_attested(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    prior = tmp_path / payload["analysisScope"]["priorSowSnapshots"][0]["file"]
    prior.write_bytes(b"tampered\n")
    (tmp_path / "repositories/service-api/src/customer/profile.py").unlink()

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert {"PRIOR_SOW_HASH_MISMATCH", "ANCHOR_FILE_MISSING"}.issubset(codes(result))


def test_registered_repository_document_anchor_is_attested(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    write_bytes(
        tmp_path,
        "repositories/service-api/docs/operations.md",
        b"Operational test assets are available.\n",
    )
    payload["evidence"].append(
        {
            "evidenceId": "evidence-operations-document",
            "name": "运维测试资产文档",
            "kind": "DOCUMENT",
            "reference": "service-api:docs/operations.md",
            "summary": "仓库文档记录了当前运维测试资产。",
            "supportsIds": ["asis-customer-api"],
        }
    )
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("kind", "reference", "expected"),
    (
        ("PRIOR_SOW", "prior-sow:sow-does-not-exist#section=scope", "PRIOR_SOW_EVIDENCE_REF_UNKNOWN"),
        ("DOCUMENT", "requirements:feature-does-not-exist", "REQUIREMENT_EVIDENCE_REF_UNKNOWN"),
    ),
)
def test_logical_evidence_references_are_closed(
    tmp_path: Path,
    kind: str,
    reference: str,
    expected: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    evidence = next(entry for entry in payload["evidence"] if entry["kind"] == kind)
    evidence["reference"] = reference
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert expected in codes(result)


def test_commitment_source_reference_must_match_its_registered_prior_sow(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["sourceReference"] = "prior-sow:other-sow#section=customer-profile"
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "PRIOR_SOW_COMMITMENT_REF_INVALID" in codes(result)


def test_runtime_evidence_cannot_use_requirement_logical_reference(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    evidence = payload["evidence"][0]
    evidence["kind"] = "RUNTIME"
    evidence["runtimeOutcome"] = "PASSED"
    evidence["reference"] = "requirements:feature-does-not-exist"
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "RUNTIME_EVIDENCE_PATH_INVALID" in codes(result)


def test_runtime_evidence_requires_owned_runtime_record_path(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    evidence = payload["evidence"][0]
    evidence["kind"] = "RUNTIME"
    evidence["runtimeOutcome"] = "PASSED"
    evidence["reference"] = ".ai-sow/project.json"
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "RUNTIME_EVIDENCE_PATH_INVALID" in codes(result)


def test_runtime_evidence_record_is_bound_as_receipt_input(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    evidence = payload["evidence"][0]
    evidence["kind"] = "RUNTIME"
    evidence["runtimeOutcome"] = "PASSED"
    evidence["reference"] = ".ai-sow/work/analyze-as-is/runtime-profile-check.md#result"
    write_bytes(
        tmp_path,
        ".ai-sow/work/analyze-as-is/runtime-profile-check.md",
        b"Runtime verification result: PASSED\n",
    )
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    receipt = validation_report(tmp_path)["compilationReceipt"]
    bound = next(entry for entry in receipt["inputs"] if entry["name"] == f"evidence:{evidence['evidenceId']}")
    assert bound["path"] == ".ai-sow/work/analyze-as-is/runtime-profile-check.md"


def test_frozen_anchor_mutation_returns_anchor_missing(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    descriptor = json.loads(E2E_DESCRIPTOR.read_text(encoding="utf-8"))
    mutation = next(case for case in descriptor["negativeCases"] if case["caseId"] == "N10")
    evidence_id = mutation["mutation"]["selector"]["evidenceId"]
    payload["analysisScope"]["repositorySnapshots"].append(
        {
            "repoId": "customer-portal",
            "name": "客户门户代码仓库",
            "path": "repositories/customer-portal",
            "revision": "c" * 40,
            "dirty": False,
        }
    )
    (tmp_path / "repositories/customer-portal").mkdir()
    payload["evidence"].append(
        {
            "evidenceId": evidence_id,
            "name": "冻结描述符缺失代码证据",
            "kind": "CODE",
            "reference": mutation["mutation"]["value"],
            "summary": "冻结描述符用于验证缺失代码 anchor 会被阻断。",
            "supportsIds": ["asis-customer-api"],
        }
    )
    write_candidate(tmp_path, payload)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "ANCHOR_FILE_MISSING" in codes(result)


def questionnaire_record(
    answer: str = "UNKNOWN",
    *,
    evidence_reference: str = "UNKNOWN",
    effective_date: str = "UNKNOWN",
) -> str:
    return f"""# 现状证据问卷

Question ID: data-03
Answer: {answer}
Owner: 数据治理团队
Evidence reference: {evidence_reference}
Effective date: {effective_date}
"""


def test_selected_questionnaire_unknown_requires_linked_uncertainty(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    questionnaire = ".ai-sow/work/analyze-as-is/questionnaire.md"
    write_bytes(tmp_path, questionnaire, questionnaire_record().encode())
    write_bytes(
        tmp_path, ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            questionnaire=questionnaire,
            questionnaire_ids="data-03",
            questionnaire_records=questionnaire_record(),
        ).encode(),
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout


def test_selected_confirmed_questionnaire_compiles_to_evidence(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["topicAssessments"][4]["status"] = "RELEVANT_INVESTIGATED"
    payload["topicAssessments"][4]["uncertaintyIds"] = []
    payload["coverage"][0]["uncertaintyIds"] = []
    payload["uncertainties"] = []
    payload["evidence"].append(
        {
            "evidenceId": "evidence-retention-decision",
            "name": "客户档案保留期决定",
            "kind": "QUESTIONNAIRE",
            "reference": "questionnaire:data-03",
            "summary": "数据治理团队确认客户档案保留三年，自 2026-08-25 生效。",
            "supportsIds": ["feature-customer-profile"],
        }
    )
    write_candidate(tmp_path, payload)
    questionnaire = ".ai-sow/work/analyze-as-is/questionnaire.md"
    write_bytes(
        tmp_path,
        questionnaire,
        questionnaire_record(
            "客户档案保留三年",
            evidence_reference="policy:customer-retention-v1",
            effective_date="2026-08-25",
        ).encode(),
    )
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            questionnaire=questionnaire,
            questionnaire_ids="data-03",
            questionnaire_records=questionnaire_record(
                "客户档案保留三年",
                evidence_reference="policy:customer-retention-v1",
                effective_date="2026-08-25",
            ),
        ).encode(),
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout


def test_questionnaire_rejects_unknown_catalog_id_and_review_record_mismatch(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["evidence"].append(
        {
            "evidenceId": "evidence-fake-question",
            "name": "未知问卷问题证据",
            "kind": "QUESTIONNAIRE",
            "reference": "questionnaire:fake-99",
            "summary": "该记录故意使用不属于权威目录的问题 ID。",
            "supportsIds": ["feature-customer-profile"],
        }
    )
    write_candidate(tmp_path, payload)
    questionnaire = ".ai-sow/work/analyze-as-is/questionnaire.md"
    record = questionnaire_record(
        "已确认",
        evidence_reference="policy:fake",
        effective_date="2026-08-25",
    ).replace("data-03", "fake-99")
    write_bytes(tmp_path, questionnaire, record.encode())
    review_record = record.replace("Answer: 已确认", "Answer: 评审中被改写")
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            questionnaire=questionnaire,
            questionnaire_ids="fake-99",
            questionnaire_records=review_record,
        ).encode(),
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert {"QUESTIONNAIRE_ID_UNKNOWN", "REVIEW_QUESTIONNAIRE_RECORD_MISMATCH"}.issubset(codes(result))


def test_questionnaire_presence_and_selected_id_set_fail_closed(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    write_bytes(tmp_path, ".ai-sow/work/analyze-as-is/questionnaire.md", questionnaire_record().encode())
    write_bytes(tmp_path, ".ai-sow/reviews/analyze-as-is.md", approved_review(payload).encode())

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "QUESTIONNAIRE_PRESENCE_CONFLICT" in codes(result)


def test_rebind_updates_inputs_without_changing_stable_bytes(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    stable = managed_path(tmp_path, ".ai-sow/data/analyze-as-is/asis.json")
    before = stable.read_bytes()
    requirement_validation = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    previous_hash = hashlib.sha256(requirement_validation.read_bytes()).hexdigest()
    publish_requirement(tmp_path, review_suffix="Impact note: Requirement review metadata updated.\n")
    current_hash = hashlib.sha256(requirement_validation.read_bytes()).hexdigest()
    write_bytes(
        tmp_path, ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            impact="NO_CHANGE",
            previous_receipt_sha256=previous_hash,
            current_receipt_sha256=current_hash,
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 0, result.stdout
    assert stable.read_bytes() == before


def test_rebind_rejects_unchanged_inputs(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    current = hashlib.sha256(
        (tmp_path / ".ai-sow/validation/analyze-requirement.json").read_bytes()
    ).hexdigest()
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            impact="NO_CHANGE",
            previous_receipt_sha256=current,
            current_receipt_sha256=current,
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 2
    assert "REBIND_INPUT_UNCHANGED" in codes(result)


def test_rebind_rejects_rationale_without_owned_stable_ids(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    validation = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    previous = hashlib.sha256(validation.read_bytes()).hexdigest()
    publish_requirement(tmp_path, review_suffix="Impact note: changed.\n")
    current = hashlib.sha256(validation.read_bytes()).hexdigest()
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            impact="NO_CHANGE",
            previous_receipt_sha256=previous,
            current_receipt_sha256=current,
            impact_rationale="x",
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 2
    assert "REVIEW_IMPACT_RATIONALE_INVALID" in codes(result)


def test_rebind_requires_exact_stable_id_tokens(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["evidence"].append(
        {
            "evidenceId": "evidence-greenfield-requirement-extra",
            "name": "补充业务需求证据",
            "kind": "DOCUMENT",
            "reference": "requirements:feature-customer-profile",
            "summary": "第二条证据用于验证稳定 ID 必须按完整 token 核对。",
            "supportsIds": ["feature-customer-profile"],
        }
    )
    write_candidate(tmp_path, payload)
    assert run_validator(tmp_path, "publish").returncode == 0
    validation = tmp_path / ".ai-sow/validation/analyze-requirement.json"
    previous = hashlib.sha256(validation.read_bytes()).hexdigest()
    publish_requirement(tmp_path, review_suffix="Impact note: changed.\n")
    current = hashlib.sha256(validation.read_bytes()).hexdigest()
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/analyze-as-is.md",
        approved_review(
            payload,
            impact="NO_CHANGE",
            previous_receipt_sha256=previous,
            current_receipt_sha256=current,
            impact_rationale="确认不受影响的稳定 ID: evidence-greenfield-requirement-extra。",
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 2
    assert "REVIEW_IMPACT_RATIONALE_INVALID" in codes(result)


def test_publish_rejects_no_change_and_failed_publish_preserves_stable(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    stable = managed_path(tmp_path, ".ai-sow/data/analyze-as-is/asis.json")
    before = stable.read_bytes()
    payload["coverage"] = []
    write_candidate(tmp_path, payload)
    write_bytes(
        tmp_path, ".ai-sow/reviews/analyze-as-is.md",
        approved_review(payload, impact="NO_CHANGE").encode(),
    )

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 2
    assert stable.read_bytes() == before
    report = validation_report(tmp_path)
    assert report["passed"] is False
    assert "compilationReceipt" not in report
    assert "REVIEW_NO_CHANGE_MODE_INVALID" in codes(result)


def test_prepare_context_writes_owner_local_evidence_closure(tmp_path: Path) -> None:
    prepare_brownfield(tmp_path)

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    context_root = tmp_path / ".ai-sow/work/analyze-as-is/context"
    manifest = json.loads((context_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "ai-sow-analyze-as-is-context-v1"
    assert [entry["name"] for entry in manifest["fragments"]] == [
        "requirements",
        "investigationScope",
        "evidenceInventory",
        "premises",
        "repoFacts",
    ]
    assert manifest["reviewClaims"]["status"] == "READY"
    assert manifest["reviewClaims"]["fragment"]["name"] == "claims"
    assert manifest["selectedTopicIds"] == [
        "SYSTEM_CONTEXT",
        "CAPABILITY",
        "APPLICATION",
        "INTEGRATION",
        "DATA",
        "PLATFORM",
        "SECURITY_COMPLIANCE",
        "OPERATIONS_QUALITY",
        "DELIVERY_CONSTRAINTS",
    ]
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in context_root.glob("*.json")
    )
    assert str(tmp_path) not in serialized
    assert "class CustomerProfileReader" not in serialized
    assert "Phase one prior SOW fixture" not in serialized


def test_project_facts_projects_selected_families_without_source_content(tmp_path: Path) -> None:
    prepare_brownfield(tmp_path)
    repo = tmp_path / "repositories/service-api"
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / "deploy").mkdir()
    (repo / "db").mkdir()
    (repo / "application.yml").write_text(
        "outbox.relay.strategy: scheduler\nspring.profiles.active: stub\n",
        encoding="utf-8",
    )
    (repo / "deploy/jobs.yaml").write_text(
        "kind: Job\nmetadata:\n  name: migrate\n---\nkind: CronJob\nmetadata:\n  name: sweep\n",
        encoding="utf-8",
    )
    (repo / "db/V1.sql").write_text(
        "create table outbox_event(id bigint);\n",
        encoding="utf-8",
    )
    (repo / ".github/workflows/ci.yml").write_text(
        "jobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )

    result = run_project_facts(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    facts = json.loads(
        (tmp_path / ".ai-sow/work/analyze-as-is/repo-facts.json").read_text(encoding="utf-8")
    )
    projected = facts["repositories"][0]["facts"]
    assert projected["deploymentResources"]["counts"] == {"CronJob": 1, "Job": 1}
    assert projected["criticalConfiguration"]["values"][0]["value"] == "scheduler"
    assert projected["springProfiles"]["values"][0]["value"] == "stub"
    assert projected["migrationTables"]["tables"][0]["table"] == "outbox_event"
    assert projected["ciWorkflows"]["workflows"][0]["jobs"] == ["test"]
    assert "create table" not in json.dumps(facts)


def test_review_mode_writes_bound_packet_without_formal_publication(tmp_path: Path) -> None:
    candidate, review = prepare_review_candidate(tmp_path)

    result = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["outcome"] == "REVIEW_REQUIRED"
    packet_path = tmp_path / ".ai-sow/work/analyze-as-is/review-packet.json"
    risk_path = tmp_path / ".ai-sow/work/analyze-as-is/risk-summary.md"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["algorithm"] == "ai-sow-owner-review-packet-v1"
    assert packet["candidateOutputs"] == [
        {
            "name": "asIs",
            "path": ".ai-sow/work/analyze-as-is/asis.candidate.json",
            "sha256": sha256_bytes(candidate),
            "targetPath": ".ai-sow/data/analyze-as-is/asis.json",
        }
    ]
    assert packet["review"] == {
        "path": ".ai-sow/work/analyze-as-is/review.candidate.md",
        "sha256": sha256_bytes(review),
    }
    assert packet["riskSummary"]["sha256"] == sha256_bytes(risk_path.read_bytes())
    assert "Estimate-affecting Uncertainties: 0" in risk_path.read_text(encoding="utf-8")
    assert not (tmp_path / ".ai-sow/reviews/analyze-as-is.md").exists()
    assert not (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").exists()
    assert not (tmp_path / ".ai-sow/validation/analyze-as-is.json").exists()


def test_design_readiness_blocks_unresolved_estimate_uncertainty(
    tmp_path: Path,
) -> None:
    prepare_brownfield(tmp_path)
    (tmp_path / ".ai-sow/reviews/analyze-as-is.md").unlink()
    assert run_context(tmp_path).returncode == 0
    assert run_renderer(tmp_path).returncode == 0

    result = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )

    assert result.returncode == 2
    assert "DESIGN_READINESS_ESTIMATE_UNCERTAINTY_UNRESOLVED" in codes(result)
    assert not (tmp_path / ".ai-sow/work/analyze-as-is/review-packet.json").exists()


def test_publish_approved_requires_both_sidecars_without_formal_writes(tmp_path: Path) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )

    assert result.returncode == 2
    assert {"REVIEWER_BINDING_MISSING", "APPROVAL_BINDING_MISSING"}.issubset(codes(result))
    assert not (tmp_path / ".ai-sow/reviews/analyze-as-is.md").exists()
    assert not (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").exists()
    assert not (tmp_path / ".ai-sow/validation/analyze-as-is.json").exists()


def test_publish_approved_preserves_candidate_review_and_receipt_contract(tmp_path: Path) -> None:
    candidate, review = prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".ai-sow/reviews/analyze-as-is.md").read_bytes() == review
    assert (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").read_bytes() == candidate
    receipt = json.loads(result.stdout)["receipt"]
    assert receipt["validatorContractVersion"] == "0.3"
    assert receipt["reviews"][0]["sha256"] == sha256_bytes(review)
    assert receipt["outputs"][0]["sha256"] == sha256_bytes(candidate)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("candidate", "REVIEW_PACKET_CANDIDATE_STALE"),
        ("context", "CONTEXT_FRAGMENT_STALE"),
        ("input", "CONTEXT_INPUT_STALE"),
        ("review", "REVIEW_PACKET_REVIEW_STALE"),
        ("reviewer", "REVIEWER_BINDING_INVALID"),
        ("approval", "APPROVAL_BINDING_INVALID"),
    ),
)
def test_publish_approved_rejects_drift_before_formal_writes(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    if mutation == "candidate":
        path = tmp_path / ".ai-sow/work/analyze-as-is/asis.candidate.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["coverage"][0]["rationale"] = "候选在批准后发生漂移。"
        path.write_bytes(canonical_json_bytes(value))
    elif mutation == "context":
        write_bytes(
            tmp_path,
            ".ai-sow/work/analyze-as-is/context/evidence-inventory.json",
            canonical_json_bytes({"drifted": True}),
        )
    elif mutation == "input":
        anchor = tmp_path / "repositories/service-api/src/customer/profile.py"
        anchor.write_bytes(anchor.read_bytes() + b"# drift\n")
    elif mutation == "review":
        path = tmp_path / ".ai-sow/work/analyze-as-is/review.candidate.md"
        path.write_bytes(path.read_bytes().replace(b"Mode: BROWNFIELD", b"Mode: BROWNFIELD (drift)"))
    else:
        path = tmp_path / f".ai-sow/work/analyze-as-is/{mutation}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["packetSha256"] = "0" * 64
        path.write_bytes(canonical_json_bytes(value))

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )

    assert result.returncode == 2
    assert expected in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/analyze-as-is.md").exists()
    assert not (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").exists()
    assert not (tmp_path / ".ai-sow/validation/analyze-as-is.json").exists()


def test_candidate_first_lifecycle_preserves_selected_questionnaire_records(
    tmp_path: Path,
) -> None:
    payload = prepare_brownfield(tmp_path)
    resolve_estimate_readiness(payload)
    write_json(tmp_path, ".ai-sow/work/analyze-as-is/asis.candidate.json", payload)
    questionnaire = questionnaire_record()
    write_bytes(
        tmp_path,
        ".ai-sow/work/analyze-as-is/questionnaire.md",
        questionnaire.encode(),
    )
    (tmp_path / ".ai-sow/reviews/analyze-as-is.md").unlink()
    context = run_context(tmp_path)
    rendered = run_renderer(tmp_path)

    assert context.returncode == 0, context.stdout + context.stderr
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    review = (
        tmp_path / ".ai-sow/work/analyze-as-is/review.candidate.md"
    ).read_text(encoding="utf-8")
    assert "Questionnaire IDs: data-03" in review
    assert questionnaire.strip() in review
    result = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-as-is/review.candidate.md",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reviewer_contract_catches_professional_evidence_privacy_failure() -> None:
    template = (SKILL_ROOT / "references/review-template.md").read_text(encoding="utf-8")
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "九个 Topic" in template
    assert "源码或完整工具输出" in template
    assert "本机绝对路径" in template
    assert "Reviewer" in skill and "证据边界" in skill
    assert "复用外层当前 Stage、一个 Reviewer 和一次 hash-bound 用户批准" in skill
    assert "确定性 Owner 命令由外层 Stage 直接调用" in skill
    assert "## 机械门禁输入合同" in skill
    assert "项目根下的相对子目录" in skill
    assert "category: MECHANICAL" in skill
    assert "correctionOwner: analyze-requirement" in skill
    assert "requiresUserDecision: false" in skill
    assert "单一 Worker、Reviewer、Validator" not in skill
