from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.patch import apply_operations, patch_audit


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts/validate.py"
CONTEXT_SCRIPT = SKILL_ROOT / "scripts/prepare_context.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_review.py"
APPLY_PATCH_SCRIPT = SKILL_ROOT / "scripts/apply_patch.py"
FIXTURE = SKILL_ROOT / "fixtures/requirements.valid.json"
REVIEW_TEMPLATE = SKILL_ROOT / "references/review-template.md"
E2E_DESCRIPTOR = SKILL_ROOT / "fixtures/e2e-cases/explicit-architecture.json"
SOURCE_BYTES = "客户需要统一创建、查询和维护客户档案，并要求关键字段完整可追溯。\n".encode()
STAGING_ROOT = ".ai-sow/.stage-0123456789ab"


def managed_path(project_root: Path, logical_path: str) -> Path:
    staged = project_root / STAGING_ROOT / logical_path.removeprefix(".ai-sow/")
    return staged if staged.exists() else project_root / logical_path


def candidate_path(project_root: Path) -> Path:
    return project_root / ".ai-sow/work/analyze-requirement/requirements.candidate.json"


def stable_path(project_root: Path) -> Path:
    return managed_path(project_root, ".ai-sow/data/analyze-requirement/requirements.json")


def validation_path(project_root: Path) -> Path:
    return managed_path(project_root, ".ai-sow/validation/analyze-requirement.json")


def review_path(project_root: Path) -> Path:
    return project_root / ".ai-sow/reviews/analyze-requirement.md"


def source_disposition_path(project_root: Path) -> Path:
    return project_root / ".ai-sow/work/analyze-requirement/source-disposition.json"


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
        ".ai-sow/work/analyze-requirement/requirements.candidate.json",
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


def run_context(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTEXT_SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def run_renderer(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def stable_ids(payload: dict[str, object]) -> list[str]:
    return [
        *(item["sourceDocumentId"] for item in payload["sourceDocuments"]),
        *(item["normalizedItemId"] for item in payload["normalizedItems"]),
        *(item["epicId"] for item in payload["epics"]),
        *(item["featureId"] for item in payload["features"]),
    ]


def approved_review(
    payload: dict[str, object],
    *,
    questionnaire: str = "NOT_REQUIRED",
    approval: str = "APPROVED",
    impact: str | None = None,
) -> str:
    impact_line = f"\nImpact: {impact}\n" if impact else ""
    return f"""# 业务需求评审

## 来源与归一化

来源已登记，归一化条目逐项保留来源关系。

## 来源处置

所有决策相关来源陈述均已分类并绑定当前业务范围或后续设计输入。

## Epic 与 Feature

业务目标已分解为可独立评审的 Epic 与 Feature。

## 范围边界

仅包含获批 BUSINESS 范围，技术实现留给设计阶段。

## 问卷状态

Questionnaire: {questionnaire}

## 稳定 ID 映射

Stable IDs: {", ".join(stable_ids(payload))}

## 输入充分性

当前来源足以支持本阶段业务结论。

## 审查与批准
{impact_line}
Reviewer: PASS
User Approval: {approval}
"""


def questionnaire_record(
    *,
    status: str = "APPROVED_DEFAULT",
    blocking: str = "NO：已确认不阻塞",
    disposition: str = "ASSUMPTION_CANDIDATE",
) -> str:
    return f"""# 需求澄清问卷

### ARQ-001

| 字段 | 内容 |
|---|---|
| Question ID | ARQ-001 |
| Type | GAP |
| Source | source-document-customer-profile §业务规则 |
| Gap or conflict | 客户档案保留期限尚未形成业务规则。 |
| Business impact | 可能影响后续归档范围，但不改变当前客户档案交付范围。 |
| Options | 保留三年；由运营另行确认。 |
| Recommendation | 先按保留三年形成交付假设。 |
| Rationale | 不阻塞当前范围评审，并保留运营确认责任。 |
| Answer | 同意暂按保留三年处理。 |
| Status | {status} |
| Blocking | {blocking} |
| Decision date | 2026-08-25 |
| Decision evidence | 用户在业务需求评审中确认该默认处理。 |
| Disposition | {disposition} |
"""


def prepare_valid(project_root: Path) -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["sourceDocuments"][0]["sha256"] == hashlib.sha256(SOURCE_BYTES).hexdigest()
    (project_root / ".ai-sow").mkdir()
    (project_root / ".ai-sow/project.json").write_text(
        json.dumps(
            {
                "projectId": "customer-portal",
                "name": "客户门户",
                "pluginVersion": "0.1.0-beta.1",
                "sowStandardVersion": "1.3",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = project_root / payload["sourceDocuments"][0]["file"]
    source.parent.mkdir(parents=True)
    source.write_bytes(SOURCE_BYTES)
    candidate = candidate_path(project_root)
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    disposition = {
        "schemaVersion": "0.1",
        "items": [
            {
                "dispositionId": f"source-disposition-{item['normalizedItemId'].removeprefix('norm-')}",
                "sourceDocumentId": item["sourceDocumentId"],
                    "sourceReference": f"业务需求/{item['name']}",
                "summary": item["statement"],
                "disposition": "BUSINESS",
                "targetIds": [item["normalizedItemId"]],
                "rationale": "该陈述直接形成可追溯的 BUSINESS normalized item。",
            }
            for item in payload["normalizedItems"]
        ],
    }
    disposition_path = source_disposition_path(project_root)
    disposition_path.parent.mkdir(parents=True, exist_ok=True)
    disposition_path.write_text(
        json.dumps(disposition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    review = review_path(project_root)
    review.parent.mkdir(parents=True)
    review.write_text(approved_review(payload), encoding="utf-8")
    return payload


def write_candidate(project_root: Path, payload: dict[str, object]) -> None:
    candidate_path(project_root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def diagnostics(result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    return json.loads(result.stdout)["diagnostics"]


def prepare_review_candidate(project_root: Path) -> tuple[bytes, bytes]:
    prepare_valid(project_root)
    assert run_context(project_root).returncode == 0
    review_path(project_root).unlink()
    rendered = run_renderer(project_root)
    assert rendered.returncode == 0, rendered.stdout
    review = project_root / ".ai-sow/work/analyze-requirement/review.candidate.md"
    return candidate_path(project_root).read_bytes(), review.read_bytes()


def bind_review_packet(project_root: Path) -> str:
    packet_path = project_root / ".ai-sow/work/analyze-requirement/review-packet.json"
    packet_hash = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    bindings = (
        ("reviewer.json", "ai-sow-owner-reviewer-v1", "PASS"),
        ("approval.json", "ai-sow-owner-approval-v1", "APPROVED"),
    )
    for filename, algorithm, decision in bindings:
        path = project_root / ".ai-sow/work/analyze-requirement" / filename
        # 必须写字节：write_text 在 Windows 上会把 "\n" 翻译成 "\r\n"，破坏 canonical JSON。
        path.write_bytes(
            (
                json.dumps(
                    {
                        "algorithm": algorithm,
                        "decision": decision,
                        "owner": "analyze-requirement",
                        "packetSha256": packet_hash,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
    return packet_hash


def test_review_template_exists_and_declares_required_machine_fields() -> None:
    text = REVIEW_TEMPLATE.read_text(encoding="utf-8")
    for heading in (
        "来源与归一化",
        "来源处置",
        "Epic 与 Feature",
        "范围边界",
        "问卷状态",
        "稳定 ID 映射",
        "输入充分性",
        "审查与批准",
    ):
        assert f"## {heading}" in text
    assert "Questionnaire:" in text
    assert "Stable IDs:" in text
    assert "Reviewer: PASS" in text
    assert "User Approval: APPROVED" in text


def test_context_requires_source_disposition_inventory(tmp_path: Path) -> None:
    prepare_valid(tmp_path)
    source_disposition_path(tmp_path).unlink()

    result = run_context(tmp_path)

    assert result.returncode == 2
    assert "SOURCE_DISPOSITION_MISSING" in {
        item["code"] for item in json.loads(result.stdout)["diagnostics"]
    }


def test_review_projects_design_input_and_cross_domain_scope_boundary(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    disposition = json.loads(source_disposition_path(tmp_path).read_text(encoding="utf-8"))
    disposition["items"].extend(
        [
            {
                "dispositionId": "source-disposition-profile-api",
                "sourceDocumentId": "source-document-customer-profile",
                "sourceReference": "技术边界/客户档案接口",
                "summary": "客户档案能力通过稳定接口供下游系统调用。",
                "disposition": "DESIGN_INPUT",
                "targetIds": [],
                "rationale": "由 generate-design 决定接口认证、契约和适配方案。",
            },
            {
                "dispositionId": "source-disposition-existing-platforms",
                "sourceDocumentId": "source-document-customer-profile",
                "sourceReference": "范围边界/既有平台",
                "summary": "本期沿用既有平台，只交付相关业务能力的集成边界。",
                "disposition": "SCOPE_BOUNDARY",
                "targetIds": [item["featureId"] for item in payload["features"]],
                "rationale": "该共同边界适用于登记维护与查询两个业务领域。",
            },
        ]
    )
    source_disposition_path(tmp_path).write_text(
        json.dumps(disposition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    assert run_context(tmp_path).returncode == 0
    result = run_renderer(tmp_path)

    assert result.returncode == 0, result.stdout
    review = (
        tmp_path / ".ai-sow/work/analyze-requirement/review.candidate.md"
    ).read_text(encoding="utf-8")
    assert "## 来源处置" in review
    assert "DESIGN_INPUT" in review
    assert "source-disposition-profile-api" in review
    assert "source-disposition-existing-platforms" in review
    assert ", ".join(item["featureId"] for item in payload["features"]) in review
    assert payload["epics"][0]["involvedSystemsData"] in review
    assert payload["epics"][0]["targetOutcome"] in review
    assert payload["features"][0]["involvedSystemsData"] in review
    assert payload["features"][0]["constraintsNfr"] in review


def test_review_projects_questionnaire_answer_status_disposition_and_default_count(
    tmp_path: Path,
) -> None:
    prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(questionnaire_record(), encoding="utf-8")

    assert run_context(tmp_path).returncode == 0
    result = run_renderer(tmp_path)

    assert result.returncode == 0, result.stdout
    review = (
        tmp_path / ".ai-sow/work/analyze-requirement/review.candidate.md"
    ).read_text(encoding="utf-8")
    assert "| ARQ-001 | APPROVED_DEFAULT | 同意暂按保留三年处理。 | ASSUMPTION_CANDIDATE |" in review
    assert "Approved Default Items: 1" in review


def test_questionnaire_derived_requirement_claims_bind_question_anchor(
    tmp_path: Path,
) -> None:
    payload = prepare_valid(tmp_path)
    feature_id = payload["features"][0]["featureId"]
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(
        questionnaire_record(
            status="CLOSED",
            disposition=f"INCORPORATED_BUSINESS:{feature_id}",
        ),
        encoding="utf-8",
    )

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout
    claims = json.loads(
        (tmp_path / ".ai-sow/work/analyze-requirement/claims.json").read_text(
            encoding="utf-8"
        )
    )["claims"]
    constraint_claim = next(
        claim
        for claim in claims
        if claim["ownerField"] == "/requirements/features/0/constraintsNfr"
    )
    assert any(
        anchor["path"].endswith("analyze-requirement-questionnaire.md#ARQ-001")
        for anchor in constraint_claim["anchors"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("design-target", "SOURCE_DISPOSITION_INVALID"),
        ("boundary-normalized-target", "SOURCE_DISPOSITION_INVALID"),
        ("business-uncovered", "SOURCE_DISPOSITION_BUSINESS_UNCOVERED"),
    ),
)
def test_source_disposition_relationships_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    prepare_valid(tmp_path)
    disposition = json.loads(source_disposition_path(tmp_path).read_text(encoding="utf-8"))
    if mutation == "design-target":
        disposition["items"][0]["disposition"] = "DESIGN_INPUT"
    elif mutation == "boundary-normalized-target":
        disposition["items"][0]["disposition"] = "SCOPE_BOUNDARY"
    else:
        disposition["items"].pop()
    source_disposition_path(tmp_path).write_text(
        json.dumps(disposition, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_context(tmp_path)

    assert result.returncode == 2
    assert expected in {item["code"] for item in json.loads(result.stdout)["diagnostics"]}


def test_check_accepts_canonical_fixture_without_writing_stable_artifacts(tmp_path: Path) -> None:
    prepare_valid(tmp_path)

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["outcome"] == "OK"
    assert not stable_path(tmp_path).exists()
    assert not validation_path(tmp_path).exists()


def test_check_accepts_work_review_override_and_reports_its_path(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    work_review = ".ai-sow/work/analyze-requirement/reconcile-review.md"
    work_review_path = tmp_path / work_review
    work_review_path.write_text(approved_review(payload), encoding="utf-8")
    review_path(tmp_path).write_text("not the approved review", encoding="utf-8")

    result = run_validator(tmp_path, "check", review_override=work_review)

    assert result.returncode == 0, result.stdout + result.stderr
    work_review_path.write_text(
        approved_review(payload).replace("Reviewer: PASS", "Reviewer: FINDINGS"),
        encoding="utf-8",
    )
    result = run_validator(tmp_path, "check", review_override=work_review)
    finding = next(item for item in diagnostics(result) if item["code"] == "REVIEW_NOT_PASSED")
    assert finding["path"] == work_review


def test_check_without_override_still_reads_formal_review(tmp_path: Path) -> None:
    prepare_valid(tmp_path)
    work_review = tmp_path / ".ai-sow/work/analyze-requirement/reconcile-review.md"
    work_review.write_text("not an approved review", encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_non_default_review_path_is_rejected_by_legacy_write_modes(tmp_path: Path, mode: str) -> None:
    payload = prepare_valid(tmp_path)
    work_review = ".ai-sow/work/analyze-requirement/reconcile-review.md"
    (tmp_path / work_review).write_text(approved_review(payload), encoding="utf-8")
    validation_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    validation_path(tmp_path).write_bytes(b"baseline validation\n")

    result = run_validator(tmp_path, mode, review_override=work_review)

    assert result.returncode == 2
    finding = next(item for item in diagnostics(result) if item["code"] == "REVIEW_PATH_MODE_INVALID")
    assert finding["message"] == (
        "--review-path override is allowed only in check, review, or publish-approved mode"
    )
    assert finding["path"] == work_review
    assert validation_path(tmp_path).read_bytes() == b"baseline validation\n"


@pytest.mark.parametrize("unsafe", ["/tmp/review.md", "../review.md", r"work\review.md"])
def test_check_rejects_unsafe_review_path(tmp_path: Path, unsafe: str) -> None:
    prepare_valid(tmp_path)

    result = run_validator(tmp_path, "check", review_override=unsafe)

    assert result.returncode == 2
    assert diagnostics(result) == [
        {
            "code": "REVIEW_PATH_INVALID",
            "message": "--review-path must be a POSIX project-relative path without traversal",
            "path": unsafe,
        }
    ]


def test_publish_preserves_candidate_bytes_and_writes_receipt_0_3(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    candidate = candidate_path(tmp_path).read_bytes()

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert stable_path(tmp_path).read_bytes() == candidate
    report = json.loads(validation_path(tmp_path).read_text(encoding="utf-8"))
    receipt = report["compilationReceipt"]
    assert report["owner"] == "analyze-requirement"
    assert receipt["algorithm"] == "ai-sow-owner-v1"
    assert receipt["validatorContractVersion"] == "0.3"
    assert receipt["contractIds"] == [
        "urn:ai-sow:analyze-requirement:source-requirements:0.1"
    ]
    assert receipt["outputs"] == [
        {
            "name": "requirements",
            "path": ".ai-sow/data/analyze-requirement/requirements.json",
            "sha256": hashlib.sha256(candidate).hexdigest(),
        }
    ]
    assert {item["name"] for item in receipt["inputs"]} == {
        "project",
        "source:source-document-customer-profile",
        "questionnaire",
    }
    questionnaire = next(item for item in receipt["inputs"] if item["name"] == "questionnaire")
    assert questionnaire["identity"] == "questionnaire:NOT_REQUIRED"
    assert set(stable_ids(payload))


def test_changed_publish_replaces_stable_candidate_bytes(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    first = stable_path(tmp_path).read_bytes()
    payload["features"][0]["description"] = "用户创建客户档案后可查看已保存信息，并收到明确的成功反馈。"
    write_candidate(tmp_path, payload)
    review_path(tmp_path).write_text(approved_review(payload), encoding="utf-8")

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert stable_path(tmp_path).read_bytes() == candidate_path(tmp_path).read_bytes()
    assert stable_path(tmp_path).read_bytes() != first


def test_publish_rejects_no_change_impact_and_preserves_stable_bytes(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    stable_before = stable_path(tmp_path).read_bytes()
    payload["features"][0]["description"] = "客户档案创建后展示已保存字段和明确结果。"
    write_candidate(tmp_path, payload)
    review_path(tmp_path).write_text(approved_review(payload, impact="NO_CHANGE"), encoding="utf-8")

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 2
    assert "REVIEW_NO_CHANGE_MODE_INVALID" in {item["code"] for item in diagnostics(result)}
    assert stable_path(tmp_path).read_bytes() == stable_before


def test_publish_requires_reviewer_pass_and_user_approval(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    review_path(tmp_path).write_text(
        approved_review(payload, approval="PENDING").replace("Reviewer: PASS", "Reviewer: FINDINGS"),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 2
    codes = {item["code"] for item in diagnostics(result)}
    assert {"REVIEW_NOT_PASSED", "USER_APPROVAL_MISSING"}.issubset(codes)
    assert not stable_path(tmp_path).exists()
    report = json.loads(validation_path(tmp_path).read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert "compilationReceipt" not in report


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("technical", "SCHEMA_INVALID"),
        ("unknown-source", "SOURCE_DOCUMENT_REF_UNKNOWN"),
        ("unknown-normalized", "NORMALIZED_ITEM_REF_UNKNOWN"),
        ("unknown-epic", "EPIC_REF_UNKNOWN"),
        ("empty-epic", "EPIC_WITHOUT_FEATURE"),
        ("unused-normalized", "NORMALIZED_ITEM_UNUSED"),
    ),
)
def test_owner_local_business_rules_fail_closed(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    payload = prepare_valid(tmp_path)
    if mutation == "technical":
        payload["epics"][0]["type"] = "TECHNICAL"
    elif mutation == "unknown-source":
        payload["normalizedItems"][0]["sourceDocumentId"] = "source-document-unknown"
    elif mutation == "unknown-normalized":
        payload["features"][0]["source"]["normalizedItemIds"] = ["norm-unknown"]
    elif mutation == "unknown-epic":
        payload["features"][0]["epicId"] = "epic-unknown"
    elif mutation == "empty-epic":
        payload["features"] = []
    else:
        payload["normalizedItems"].append(
            {
                "normalizedItemId": "norm-unused",
                "sourceDocumentId": payload["sourceDocuments"][0]["sourceDocumentId"],
                "name": "未使用条目",
                "statement": "该条目没有进入任何获批业务结论。",
            }
        )
    write_candidate(tmp_path, payload)
    review_path(tmp_path).write_text(approved_review(payload), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert code in {item["code"] for item in diagnostics(result)}


def test_source_hash_and_review_id_set_are_bound(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    source = tmp_path / payload["sourceDocuments"][0]["file"]
    source.write_bytes(b"changed")
    review_path(tmp_path).write_text(
        approved_review(payload).replace(payload["features"][0]["featureId"], "feature-missing"),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    codes = {item["code"] for item in diagnostics(result)}
    assert {"SOURCE_DOCUMENT_HASH_MISMATCH", "REVIEW_ID_SET_MISMATCH"}.issubset(codes)


def test_questionnaire_approved_default_is_valid_and_hash_bound(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(questionnaire_record(), encoding="utf-8")
    review_path(tmp_path).write_text(
        approved_review(
            payload,
            questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md",
        ),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    receipt = json.loads(validation_path(tmp_path).read_text(encoding="utf-8"))["compilationReceipt"]
    declaration = next(item for item in receipt["inputs"] if item["name"] == "questionnaire")
    assert declaration["kind"] == "QUESTIONNAIRE_PRESENCE"
    assert declaration["sha256"] == hashlib.sha256(questionnaire.read_bytes()).hexdigest()


def test_frozen_explicit_architecture_questionnaire_is_valid(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    descriptor = json.loads(E2E_DESCRIPTOR.read_text(encoding="utf-8"))
    operation = next(
        item
        for item in descriptor["positive"]["operations"]
        if item["selector"].get("path") == ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    )
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(operation["value"], encoding="utf-8")
    review_path(tmp_path).write_text(
        approved_review(payload, questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md"),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("old", "new", "code"),
    (
        ("| Type | GAP |", "| Type | TECHNICAL |", "QUESTIONNAIRE_TYPE_INVALID"),
        (
            "| Blocking | NO：已确认不阻塞 |",
            "| Blocking | NO |",
            "QUESTIONNAIRE_BLOCKING_INVALID",
        ),
        (
            "| Decision evidence | 用户在业务需求评审中确认该默认处理。 |",
            "| Decision evidence | 已批准 |",
            "QUESTIONNAIRE_DECISION_EVIDENCE_GENERIC",
        ),
        (
            "| Status | APPROVED_DEFAULT |",
            "| Status | APPROVED_DEFAULT |\n| Status | CLOSED |",
            "QUESTIONNAIRE_FIELD_DUPLICATE",
        ),
    ),
)
def test_questionnaire_field_grammar_fails_closed(
    tmp_path: Path,
    old: str,
    new: str,
    code: str,
) -> None:
    payload = prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(questionnaire_record().replace(old, new), encoding="utf-8")
    review_path(tmp_path).write_text(
        approved_review(payload, questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md"),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert code in {item["code"] for item in diagnostics(result)}


def test_questionnaire_blocking_diagnostic_shows_canonical_format(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(
        questionnaire_record().replace(
            "| Blocking | NO：已确认不阻塞 |",
            "| Blocking | NO —— 已确认不阻塞 |",
        ),
        encoding="utf-8",
    )
    review_path(tmp_path).write_text(
        approved_review(
            payload,
            questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md",
        ),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    diagnostic = next(
        item
        for item in diagnostics(result)
        if item["code"] == "QUESTIONNAIRE_BLOCKING_INVALID"
    )
    assert "YES：<理由>" in diagnostic["message"]
    assert "NO：<理由>" in diagnostic["message"]


def test_questionnaire_not_required_rejects_existing_questionnaire(tmp_path: Path) -> None:
    prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(questionnaire_record(status="OPEN"), encoding="utf-8")

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert "QUESTIONNAIRE_PRESENCE_CONFLICT" in {item["code"] for item in diagnostics(result)}


@pytest.mark.parametrize(
    ("status", "blocking", "disposition", "code"),
    (
        ("OPEN", "YES：该问题会改变业务范围", "NO_CHANGE", "QUESTIONNAIRE_NOT_FINAL"),
        (
            "APPROVED_DEFAULT",
            "YES：该问题会改变业务范围",
            "ASSUMPTION_CANDIDATE",
            "QUESTIONNAIRE_BLOCKING_DEFAULT",
        ),
        (
            "CLOSED",
            "YES：该问题会改变业务范围",
            "INCORPORATED_BUSINESS:feature-unknown",
            "QUESTIONNAIRE_BUSINESS_REF_UNKNOWN",
        ),
    ),
)
def test_questionnaire_invalid_terminal_state_blocks(
    tmp_path: Path,
    status: str,
    blocking: str,
    disposition: str,
    code: str,
) -> None:
    payload = prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(
        questionnaire_record(status=status, blocking=blocking, disposition=disposition),
        encoding="utf-8",
    )
    review_path(tmp_path).write_text(
        approved_review(payload, questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md"),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "check")

    assert result.returncode == 2
    assert code in {item["code"] for item in diagnostics(result)}


def test_rebind_updates_questionnaire_and_review_without_changing_stable_bytes(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    stable_before = stable_path(tmp_path).read_bytes()
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(questionnaire_record(), encoding="utf-8")
    review_path(tmp_path).write_text(
        approved_review(
            payload,
            questionnaire=".ai-sow/reviews/analyze-requirement-questionnaire.md",
            impact="NO_CHANGE",
        ),
        encoding="utf-8",
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 0, result.stdout
    assert stable_path(tmp_path).read_bytes() == stable_before
    receipt = json.loads(validation_path(tmp_path).read_text(encoding="utf-8"))["compilationReceipt"]
    assert next(item for item in receipt["inputs"] if item["name"] == "questionnaire")[
        "sha256"
    ] == hashlib.sha256(questionnaire.read_bytes()).hexdigest()


def test_failed_publish_preserves_last_stable_output_and_writes_failure_report(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    assert run_validator(tmp_path, "publish").returncode == 0
    stable_before = stable_path(tmp_path).read_bytes()
    payload["features"][0]["epicId"] = "epic-unknown"
    write_candidate(tmp_path, payload)
    review_path(tmp_path).write_text(approved_review(payload), encoding="utf-8")

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 2
    assert stable_path(tmp_path).read_bytes() == stable_before
    report = json.loads(validation_path(tmp_path).read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert "compilationReceipt" not in report


def test_prepare_context_and_review_packet_bind_all_owner_inputs_without_formal_writes(
    tmp_path: Path,
) -> None:
    candidate, review = prepare_review_candidate(tmp_path)

    result = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["outcome"] == "REVIEW_REQUIRED"
    packet_path = tmp_path / ".ai-sow/work/analyze-requirement/review-packet.json"
    risk_path = tmp_path / ".ai-sow/work/analyze-requirement/risk-summary.md"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["algorithm"] == "ai-sow-owner-review-packet-v1"
    assert packet["candidateOutputs"] == [
        {
            "name": "requirements",
            "path": ".ai-sow/work/analyze-requirement/requirements.candidate.json",
            "sha256": hashlib.sha256(candidate).hexdigest(),
            "targetPath": ".ai-sow/data/analyze-requirement/requirements.json",
        }
    ]
    assert packet["review"]["sha256"] == hashlib.sha256(review).hexdigest()
    assert packet["context"]["manifest"]["path"] == (
        ".ai-sow/work/analyze-requirement/context/manifest.json"
    )
    assert [entry["name"] for entry in packet["inputArtifacts"]] == [
        "project",
        "source:source-document-customer-profile",
        "questionnaire",
    ]
    assert packet["riskSummary"]["sha256"] == hashlib.sha256(risk_path.read_bytes()).hexdigest()
    assert "Open Critical Questionnaire Items: 0" in risk_path.read_text(encoding="utf-8")
    assert not review_path(tmp_path).exists()
    assert not stable_path(tmp_path).exists()
    assert not validation_path(tmp_path).exists()


def test_publish_approved_requires_reviewer_and_approval_without_formal_writes(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    assert run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    ).returncode == 0

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    )

    assert result.returncode == 2
    codes = {item["code"] for item in diagnostics(result)}
    assert {"REVIEWER_BINDING_MISSING", "APPROVAL_BINDING_MISSING"}.issubset(codes)
    assert not review_path(tmp_path).exists()
    assert not stable_path(tmp_path).exists()
    assert not validation_path(tmp_path).exists()


def test_publish_approved_preserves_exact_candidate_and_review_bytes(tmp_path: Path) -> None:
    candidate, review = prepare_review_candidate(tmp_path)
    assert run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    ).returncode == 0
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert review_path(tmp_path).read_bytes() == review
    assert stable_path(tmp_path).read_bytes() == candidate
    receipt = json.loads(result.stdout)["receipt"]
    assert receipt["validatorContractVersion"] == "0.3"
    assert receipt["reviews"][0]["sha256"] == hashlib.sha256(review).hexdigest()
    assert receipt["outputs"][0]["sha256"] == hashlib.sha256(candidate).hexdigest()


@pytest.mark.parametrize("drift", ["candidate", "context"])
def test_publish_approved_rejects_packet_or_context_drift_before_formal_writes(
    tmp_path: Path,
    drift: str,
) -> None:
    prepare_review_candidate(tmp_path)
    assert run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    ).returncode == 0
    bind_review_packet(tmp_path)
    if drift == "candidate":
        payload = json.loads(candidate_path(tmp_path).read_text(encoding="utf-8"))
        payload["features"][0]["description"] = "漂移后的业务结论。"
        write_candidate(tmp_path, payload)
        expected = "REVIEW_PACKET_CANDIDATE_STALE"
    else:
        context = tmp_path / ".ai-sow/work/analyze-requirement/context/source-index.json"
        context.write_text("{}\n", encoding="utf-8")
        expected = "CONTEXT_FRAGMENT_STALE"

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    )

    assert result.returncode == 2
    assert expected in {item["code"] for item in diagnostics(result)}
    assert not review_path(tmp_path).exists()
    assert not stable_path(tmp_path).exists()
    assert not validation_path(tmp_path).exists()


def test_open_critical_questionnaire_blocks_before_reviewer_packet(tmp_path: Path) -> None:
    payload = prepare_valid(tmp_path)
    questionnaire = tmp_path / ".ai-sow/reviews/analyze-requirement-questionnaire.md"
    questionnaire.write_text(
        questionnaire_record(
            status="OPEN",
            blocking="YES：该问题会改变业务范围",
            disposition="NO_CHANGE",
        ),
        encoding="utf-8",
    )
    review_path(tmp_path).unlink()

    result = run_context(tmp_path)

    assert result.returncode == 2
    assert "QUESTIONNAIRE_NOT_FINAL" in {
        item["code"] for item in json.loads(result.stdout)["diagnostics"]
    }
    assert set(stable_ids(payload))
    assert not (tmp_path / ".ai-sow/work/analyze-requirement/review-packet.json").exists()
    assert not review_path(tmp_path).exists()
    assert not stable_path(tmp_path).exists()
    assert not validation_path(tmp_path).exists()


def test_requirement_multi_document_patch_commits_candidates_and_post_check_atomically(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    requirements_path = candidate_path(tmp_path)
    disposition_path = source_disposition_path(tmp_path)
    requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
    disposition = json.loads(disposition_path.read_text(encoding="utf-8"))
    requirement_operations = [
        {
            "op": "replace",
            "path": "/features/0/description",
            "value": requirements["features"][0]["description"] + "评审补充。",
            "findingId": "ARQ-F-1",
        }
    ]
    disposition_operations = [
        {
            "op": "replace",
            "path": "/items/0/rationale",
            "value": disposition["items"][0]["rationale"] + "评审补充。",
            "findingId": "ARQ-F-1",
        }
    ]

    def document_patch(
        path: str,
        before: dict[str, object],
        operations: list[dict[str, object]],
    ) -> dict[str, object]:
        after = apply_operations(before, operations)
        draft = {"operations": operations, "acknowledgedClosureIds": []}
        return {
            "path": path,
            "operations": operations,
            "acknowledgedClosureIds": patch_audit(before, after, draft)[
                "syncSuspects"
            ],
        }

    patch_path = tmp_path / ".ai-sow/work/analyze-requirement/multi-patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "documents": [
                    document_patch(
                        ".ai-sow/work/analyze-requirement/requirements.candidate.json",
                        requirements,
                        requirement_operations,
                    ),
                    document_patch(
                        ".ai-sow/work/analyze-requirement/source-disposition.json",
                        disposition,
                        disposition_operations,
                    ),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit_path = ".ai-sow/work/analyze-requirement/multi-patch-audit.json"

    result = subprocess.run(
        [
            sys.executable,
            str(APPLY_PATCH_SCRIPT),
            "--project-root",
            str(tmp_path),
            "--patch",
            ".ai-sow/work/analyze-requirement/multi-patch.json",
            "--audit",
            audit_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["patchRoundConsumed"] is True
    assert "评审补充。" in requirements_path.read_text(encoding="utf-8")
    assert "评审补充。" in disposition_path.read_text(encoding="utf-8")
    audit = json.loads((tmp_path / audit_path).read_text(encoding="utf-8"))
    assert audit["algorithm"] == "ai-sow-multi-field-patch-v1"
    assert len(audit["documents"]) == 2


def test_review_mode_preserves_existing_formal_bytes(tmp_path: Path) -> None:
    prepare_valid(tmp_path)
    formal_review = review_path(tmp_path).read_bytes()
    stable_path(tmp_path).parent.mkdir(parents=True)
    stable_path(tmp_path).write_bytes(b"previous stable requirements\n")
    validation_path(tmp_path).parent.mkdir(parents=True)
    validation_path(tmp_path).write_bytes(b"previous validation receipt\n")
    assert run_context(tmp_path).returncode == 0
    assert run_renderer(tmp_path).returncode == 0

    result = run_validator(
        tmp_path,
        "review",
        review_override=".ai-sow/work/analyze-requirement/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert review_path(tmp_path).read_bytes() == formal_review
    assert stable_path(tmp_path).read_bytes() == b"previous stable requirements\n"
    assert validation_path(tmp_path).read_bytes() == b"previous validation receipt\n"


def test_skill_contract_uses_full_then_lightweight_reviewers_and_candidate_first_publication() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        "Stage Agent",
        "fresh Reviewer Agent",
        "不继承当前完整聊天",
        "字段级 finding 修复",
        "scripts/apply_patch.py",
        "patch-audit.json",
        "轻量 fresh-context Reviewer",
        "不加载完整来源或 round-1 历史",
        "prepare_context.py",
        "render_review.py",
        "--mode review",
        "--mode publish-approved",
        "review-packet.json",
        "reviewer.json",
        "approval.json",
        "然后 STOP",
    ):
        assert required in contract
    assert "最多一次整体修复" not in contract
    assert "Validator Agent" not in contract
    assert "Worker Agent" not in contract


def test_skill_contract_requires_full_source_disposition_and_direct_skill_paths() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for required in (
        ".ai-sow/work/analyze-requirement/source-disposition.json",
        "BUSINESS",
        "DESIGN_INPUT",
        "SCOPE_BOUNDARY",
        "EXCLUDED",
        "每条会影响业务范围、结果、规则、验收意图、方案边界或交付边界的明确来源陈述",
        "每个 `normalizedItem` 都必须由至少一条 `BUSINESS` 处置",
        "不能绑定 `norm-*`",
        "YES：<非空理由>",
        "不得运行 `git status`",
        "不得复读 `scripts/*.py` 实现",
        '"<skill-root>/contracts/source-requirements.schema.json"',
    ):
        assert required in contract
    questionnaire = (
        SKILL_ROOT / "references/requirement-clarification-questionnaire.md"
    ).read_text(encoding="utf-8")
    assert "YES：<非空理由>" in questionnaire
    assert "NO：<非空理由>" in questionnaire
