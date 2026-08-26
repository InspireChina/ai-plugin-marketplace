from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts/validate.py"
PREPARE_CONTEXT = SKILL_ROOT / "scripts/prepare_context.py"
RENDER_REVIEW = SKILL_ROOT / "scripts/render_review.py"
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
ASIS_CONTRACT = OwnerContract(
    subject="analyze-as-is",
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.1",),
    validation_path=".ai-sow/validation/analyze-as-is.json",
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-as-is.md"),),
    outputs=(("asIs", ".ai-sow/data/analyze-as-is/asis.json"),),
)
DESIGN_CONTRACT = OwnerContract(
    subject="generate-design",
    contract_ids=(
        "urn:ai-sow:generate-design:design:0.2",
        "urn:ai-sow:generate-design:technical-requirements:0.2",
    ),
    validation_path=".ai-sow/validation/generate-design.json",
    reviews=(("approvedReview", ".ai-sow/reviews/generate-design.md"),),
    outputs=(
        ("design", ".ai-sow/data/generate-design/design.json"),
        ("technicalRequirements", ".ai-sow/data/generate-design/requirements.json"),
    ),
)
GO_LIVE_CONCERNS = (
    "PRODUCTION_SCOPE",
    "ENVIRONMENT_CONFIGURATION",
    "DEPLOYMENT_CUTOVER_ROLLBACK",
    "DATA_MIGRATION",
    "PRODUCTION_VALIDATION",
    "OBSERVABILITY",
    "OPERATIONS_HANDOVER",
    "POST_GO_LIVE_SUPPORT",
    "USER_ENABLEMENT",
    "LEGACY_RETIREMENT",
)
PROJECT = {
    "projectId": "project-story-test",
    "name": "Story 交接测试",
    "pluginVersion": "0.1.0",
    "templateVersion": "1.3",
}
SOURCE_PATH = ".ai-sow/inputs/analyze-requirement/customer-profile.md"
QUESTIONNAIRE_PATH = ".ai-sow/reviews/analyze-requirement-questionnaire.md"
REQUIREMENTS = {
    "sourceDocuments": [
        {
            "sourceDocumentId": "source-document-customer-profile",
            "file": SOURCE_PATH,
            "originalName": "customer-profile.md",
            "sha256": "0" * 64,
        }
    ],
    "normalizedItems": [],
    "epics": [{"epicId": "epic-customer-management", "type": "BUSINESS"}],
    "features": [{"featureId": "feature-customer-profile", "epicId": "epic-customer-management"}],
}
ASIS = {
    "analysisScope": {
        "mode": "GREENFIELD",
        "asOfDate": "2026-08-25",
        "repositorySnapshots": [],
        "priorSowSnapshots": [],
        "includedSystems": ["客户门户"],
        "includedAreas": ["客户档案"],
        "excludedAreas": [],
    },
    "topicAssessments": [],
    "items": [{"asIsItemId": "asis-customer-api"}],
    "commitments": [
        {
            "commitmentId": "commitment-loyalty-profile",
            "implementationStatus": "NOT_IMPLEMENTED",
            "treatment": "CARRY_FORWARD",
            "relatedFeatureIds": ["feature-customer-profile"],
        }
    ],
    "effectiveStartItems": [
        {
            "effectiveStartItemId": "effective-start-customer-api",
            "sourceItemIds": ["asis-customer-api"],
            "commitmentIds": [],
        }
    ],
    "coverage": [],
    "uncertainties": [],
    "evidence": [
        {
            "evidenceId": "evidence-customer-api",
            "kind": "DOCUMENT",
            "reference": "requirements:feature-customer-profile",
        }
    ],
}
DESIGN = {
    "designItems": [
        {
            "designItemId": "design-customer-profile",
            "type": "COMPONENT",
            "name": "客户档案组件",
            "summary": "负责客户档案的创建和检索。",
        }
    ],
    "architectureDeltas": [
        {
            "architectureDeltaId": "delta-customer-profile",
            "name": "客户档案组件调整",
            "changeType": "ADJUST",
            "designItemId": "design-customer-profile",
            "effectiveStartItemIds": ["effective-start-customer-api"],
            "summary": "调整现有客户接口以交付客户档案范围。",
        }
    ],
    "decisions": [
        {
            "designDecisionId": "decision-profile-api",
            "name": "公开客户档案 API",
            "decision": "使用专用 API 边界处理客户档案操作。",
            "rationale": "客户门户和未来渠道需要统一边界。",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": ["effective-start-customer-api"],
            "relatedFeatureIds": ["feature-customer-profile", "feature-profile-api"],
            "decisionKind": "INTEGRATION_BOUNDARY",
            "evidenceIds": ["evidence-customer-api"],
            "adapterCompletesDelivery": False,
        }
    ],
    "scopeDecisions": [
        {
            "featureId": "feature-customer-profile",
            "decision": "IN_SCOPE",
            "rationale": "客户档案仍需交付。",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
            "requiredIntegrationBoundary": "NONE",
            "requiredDecisionKinds": [],
        },
        {
            "featureId": "feature-profile-api",
            "decision": "IN_SCOPE",
            "rationale": "客户档案 API 仍需交付。",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
            "requiredIntegrationBoundary": "END_TO_END",
            "requiredDecisionKinds": ["INTEGRATION_BOUNDARY"],
        },
    ],
}
TECHNICAL = {
    "epics": [
        {
            "epicId": "epic-platform",
            "type": "TECHNICAL",
            "name": "平台边界",
            "description": "明确客户档案平台边界。",
            "source": {
                "type": "SOURCE_INPUT",
                "sourceDocumentIds": ["source-document-customer-profile"],
                "sourceReferences": ["section:technical-platform"],
            },
        }
    ],
    "features": [
        {
            "featureId": "feature-profile-api",
            "epicId": "epic-platform",
            "name": "客户档案操作 API",
            "description": "通过稳定 API 创建和检索客户档案。",
            "relatedBusinessFeatureIds": ["feature-customer-profile"],
            "source": {
                "type": "DESIGN_DERIVED",
                "designDecisionIds": ["decision-profile-api"],
                "effectiveStartItemIds": ["effective-start-customer-api"],
                "rationale": "设计决策产生客户档案 API。",
            },
        }
    ],
}


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_bytes(root: Path, relative: str, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def fixture(name: str) -> dict[str, object]:
    return json.loads((SKILL_ROOT / f"fixtures/{name}").read_text(encoding="utf-8"))


def absent_questionnaire() -> Artifact:
    return Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        "questionnaire:NOT_REQUIRED",
        sha256_bytes(canonical_json_bytes({"declaration": "NOT_REQUIRED"})),
    )


def publish_requirements(
    root: Path,
    *,
    questionnaire: bytes | None = None,
    value: dict[str, object] | None = None,
) -> None:
    files = ProjectFiles.open(root)
    source = files.read_bytes(SOURCE_PATH)
    requirements = copy.deepcopy(value or REQUIREMENTS)
    requirements["sourceDocuments"][0]["sha256"] = sha256_bytes(source)  # type: ignore[index]
    q_artifact = absent_questionnaire()
    if questionnaire is not None:
        write_bytes(root, QUESTIONNAIRE_PATH, questionnaire)
        q_artifact = Artifact(
            "questionnaire",
            "QUESTIONNAIRE_PRESENCE",
            f"questionnaire:{QUESTIONNAIRE_PATH}",
            sha256_bytes(questionnaire),
        )
    write_bytes(
        root,
        ".ai-sow/reviews/analyze-requirement.md",
        f"Questionnaire: {QUESTIONNAIRE_PATH if questionnaire is not None else 'NOT_REQUIRED'}\n".encode(),
    )
    publish_owner(
        files,
        REQUIREMENT_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("source:source-document-customer-profile", "FILE", SOURCE_PATH, sha256_bytes(source)),
            q_artifact,
        ),
        {"requirements": json_bytes(requirements)},
    )


def publish_asis(root: Path, value: dict[str, object] | None = None) -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/analyze-as-is.md", b"Questionnaire: NOT_REQUIRED\n")
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("requirementsValidation", "FILE", ".ai-sow/validation/analyze-requirement.json", sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json"))),
            Artifact("requirements", "FILE", ".ai-sow/data/analyze-requirement/requirements.json", sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json"))),
            absent_questionnaire(),
        ),
        {"asIs": json_bytes(value or ASIS)},
    )


def publish_design(
    root: Path,
    *,
    review: bytes = b"Design review approved.\n",
    design_payload: bytes | None = None,
    technical_payload: bytes | None = None,
) -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/generate-design.md", review)
    publish_owner(
        files,
        DESIGN_CONTRACT,
        tuple(
            Artifact(name, "FILE", path, sha256_bytes(files.read_bytes(path)))
            for name, path in (
                ("project", ".ai-sow/project.json"),
                ("requirementsValidation", ".ai-sow/validation/analyze-requirement.json"),
                ("requirements", ".ai-sow/data/analyze-requirement/requirements.json"),
                ("asIsValidation", ".ai-sow/validation/analyze-as-is.json"),
                ("asIs", ".ai-sow/data/analyze-as-is/asis.json"),
            )
        ),
        {
            "design": design_payload if design_payload is not None else json_bytes(DESIGN),
            "technicalRequirements": technical_payload if technical_payload is not None else json_bytes(TECHNICAL),
        },
    )


def stable_ids(delivery: dict[str, object]) -> list[str]:
    return [
        *(entry["gapId"] for entry in delivery["gaps"]),  # type: ignore[index]
        *(entry["storyId"] for entry in delivery["stories"]),  # type: ignore[index]
        *(entry["acceptanceCriterionId"] for entry in delivery["acceptanceCriteria"]),  # type: ignore[index]
        *(entry["integrationId"] for entry in delivery["integrations"]),  # type: ignore[index]
        *(entry["assumptionId"] for entry in delivery["assumptions"]),  # type: ignore[index]
    ]


def story_review(
    delivery: dict[str, object],
    *,
    questionnaire_map: str = "NONE",
    omit_concern: str | None = None,
    rebind: dict[str, str] | None = None,
) -> str:
    rows = []
    for concern in GO_LIVE_CONCERNS:
        if concern == omit_concern:
            continue
        if concern == "PRODUCTION_SCOPE":
            row = (
                concern,
                "IN_SCOPE",
                "feature-profile-api",
                "gap-profile-api",
                "story-profile-api",
                "—",
                "项目负责 API 生产交付，客户负责生产审批。",
                "获批技术范围要求该能力达到生产可用。",
            )
        else:
            row = (
                concern,
                "NOT_APPLICABLE",
                "—",
                "—",
                "—",
                "—",
                "该关注点不进入本项目责任边界。",
                "已确认该关注点与当前范围无关。",
            )
        rows.append("| " + " | ".join(row) + " |")
    impact = ""
    if rebind is not None:
        impact = (
            "\nImpact: NO_CHANGE\n"
            "Upstream: generate-design\n"
            f"Previous Receipt SHA-256: generate-design={rebind['old']}\n"
            f"Current Receipt SHA-256: generate-design={rebind['new']}\n"
            f"Impact Rationale: {'、'.join(stable_ids(delivery))} 均确认不受影响。\n"
        )
    return (
        "# 交付 Story 评审\n\n"
        "## Feature → Gap → Story\n\n差距和 Story 已核对。\n\n"
        f"Stable IDs: {', '.join(stable_ids(delivery))}\n\n"
        "## Acceptance Criteria\n\nAC 已核对。\n\n"
        "## Integration\n\n集成边界已核对。\n\n"
        "## Assumption / Risk\n\n假设和风险已核对。\n\n"
        "## Questionnaire consumption\n\n"
        f"Questionnaire Map: {questionnaire_map}\n\n"
        "## 上线映射\n\n"
        "| Concern | Disposition | Feature IDs | Gap IDs | Story IDs | Assumption/Risk IDs | 责任边界 | 依据 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\nGo-live Mapping: PASSED\n\n"
        "## 审查与批准\n\nReviewer: PASS\nUser Approval: APPROVED\n"
        + impact
    )


def prepare(
    root: Path,
    *,
    questionnaire: bytes | None = None,
    requirements: dict[str, object] | None = None,
    design: dict[str, object] | None = None,
    technical: dict[str, object] | None = None,
    delivery: dict[str, object] | None = None,
) -> bytes:
    write_bytes(root, ".ai-sow/project.json", json_bytes(PROJECT))
    write_bytes(root, SOURCE_PATH, b"Customer profile source.\n")
    publish_requirements(root, questionnaire=questionnaire, value=requirements)
    publish_asis(root)
    publish_design(
        root,
        design_payload=json_bytes(design) if design is not None else None,
        technical_payload=json_bytes(technical) if technical is not None else None,
    )
    delivery = copy.deepcopy(delivery or fixture("delivery.valid.json"))
    questionnaire_map = "NONE"
    if questionnaire is not None:
        delivery["assumptions"][0]["handling"] += " 来源：analyze-requirement-questionnaire#ARQ-001。"  # type: ignore[index]
        questionnaire_map = "ARQ-001=assumption-profile-hosting->story-profile-hosting-discovery"
    candidate = (json.dumps(delivery, ensure_ascii=False, indent=3) + "\n").encode()
    write_bytes(root, ".ai-sow/work/generate-story/delivery.candidate.json", candidate)
    write_bytes(root, ".ai-sow/reviews/generate-story.md", story_review(delivery, questionnaire_map=questionnaire_map).encode())
    return candidate


def questionnaire_bytes() -> bytes:
    return (
        "# 需求澄清问卷\n\n"
        "### ARQ-001\n\n"
        "| 字段 | 内容 |\n|---|---|\n"
        "| Question ID | ARQ-001 |\n"
        "| Answer | 采用客户管理团队默认托管边界 |\n"
        "| Status | APPROVED_DEFAULT |\n"
        "| Decision date | 2026-08-25 |\n"
        "| Decision evidence | 用户确认默认处理并保留为交付假设。 |\n"
        "| Disposition | ASSUMPTION_CANDIDATE |\n"
    ).encode()


def run_validator(
    root: Path,
    mode: str = "check",
    *,
    review_path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--project-root", str(root), "--mode", mode]
    if review_path is not None:
        command.extend(("--review-path", review_path))
    if mode in {"publish", "rebind"}:
        command.extend(("--staging-root", STAGING_ROOT))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


STAGING_ROOT = ".ai-sow/.stage-0123456789ab"


def managed_path(root: Path, logical_path: str) -> Path:
    staged = root / STAGING_ROOT / logical_path.removeprefix(".ai-sow/")
    return staged if staged.exists() else root / logical_path


def run_script(script: Path, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--project-root", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def design_review() -> bytes:
    rows = []
    for concern in GO_LIVE_CONCERNS:
        if concern == "PRODUCTION_SCOPE":
            values = (
                concern,
                "IN_SCOPE",
                "feature-profile-api",
                "—",
                "—",
                "项目负责 API 生产交付，客户负责生产审批。",
                "获批技术范围要求该能力达到生产可用。",
            )
        else:
            values = (
                concern,
                "NOT_APPLICABLE",
                "—",
                "—",
                "—",
                "该关注点不进入本项目责任边界。",
                "已确认该关注点与当前范围无关。",
            )
        rows.append("| " + " | ".join(values) + " |")
    return (
        "# 目标设计评审\n\n"
        "## 高阶设计覆盖门禁\n\nHLD Coverage: PASSED\n\n"
        "## 上线范围门禁\n\n"
        "| Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\nGo-live Assessment: PASSED\n"
    ).encode()


def prepare_candidate_first(root: Path) -> tuple[bytes, bytes]:
    candidate = prepare(root)
    publish_design(root, review=design_review())
    (root / ".ai-sow/reviews/generate-story.md").unlink()
    prepared = run_script(PREPARE_CONTEXT, root)
    assert prepared.returncode == 0, prepared.stdout
    rendered = run_script(
        RENDER_REVIEW,
        root,
        "--candidate",
        ".ai-sow/work/generate-story/delivery.candidate.json",
        "--output",
        ".ai-sow/work/generate-story/review.candidate.md",
    )
    assert rendered.returncode == 0, rendered.stdout
    review = (root / ".ai-sow/work/generate-story/review.candidate.md").read_bytes()
    return candidate, review


def bind_review_packet(root: Path) -> str:
    packet = root / ".ai-sow/work/generate-story/review-packet.json"
    packet_hash = sha256_bytes(packet.read_bytes())
    write_bytes(
        root,
        ".ai-sow/work/generate-story/reviewer.json",
        canonical_json_bytes(
            {
                "algorithm": "ai-sow-owner-reviewer-v1",
                "decision": "PASS",
                "owner": "generate-story",
                "packetSha256": packet_hash,
            }
        ),
    )
    write_bytes(
        root,
        ".ai-sow/work/generate-story/approval.json",
        canonical_json_bytes(
            {
                "algorithm": "ai-sow-owner-approval-v1",
                "decision": "APPROVED",
                "owner": "generate-story",
                "packetSha256": packet_hash,
            }
        ),
    )
    return packet_hash


def result_payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {entry["code"] for entry in result_payload(result)["diagnostics"]}  # type: ignore[index]


def mutate(root: Path, relative: str, change: object) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)  # type: ignore[operator]
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_check_accepts_feature_gap_story_ac_integration_and_assumption(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert result_payload(result)["outcome"] == "OK"
    assert not (tmp_path / ".ai-sow/validation/generate-story.json").exists()


def test_check_accepts_work_only_review_override_and_ignores_default_review(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-story/review.md"
    review = (tmp_path / ".ai-sow/reviews/generate-story.md").read_bytes()
    write_bytes(tmp_path, review_path, review)
    write_bytes(tmp_path, ".ai-sow/reviews/generate-story.md", b"default review must not be read\n")

    result = run_validator(tmp_path, review_path=review_path)

    assert result.returncode == 0, result.stdout
    assert result_payload(result)["outcome"] == "OK"


def test_check_reports_override_path_for_review_and_mapping_diagnostics(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-story/review.md"
    review = (tmp_path / ".ai-sow/reviews/generate-story.md").read_text(encoding="utf-8")
    write_bytes(
        tmp_path,
        review_path,
        review.replace("Reviewer: PASS", "Reviewer: FAIL").replace(
            "Go-live Mapping: PASSED",
            "Go-live Mapping: BLOCKED",
        ).encode(),
    )

    result = run_validator(tmp_path, review_path=review_path)

    diagnostics = result_payload(result)["diagnostics"]
    by_code = {entry["code"]: entry for entry in diagnostics}  # type: ignore[index]
    assert by_code["REVIEW_NOT_PASSED"]["path"] == review_path
    assert by_code["GO_LIVE_MAPPING_NOT_PASSED"]["path"] == review_path


@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_write_modes_block_review_override(tmp_path: Path, mode: str) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-story/review.md"
    write_bytes(
        tmp_path,
        review_path,
        (tmp_path / ".ai-sow/reviews/generate-story.md").read_bytes(),
    )
    write_bytes(tmp_path, ".ai-sow/validation/generate-story.json", b"baseline validation\n")

    result = run_validator(tmp_path, mode, review_path=review_path)

    assert result.returncode == 2
    assert codes(result) == {"REVIEW_PATH_MODE_INVALID"}
    assert (tmp_path / ".ai-sow/validation/generate-story.json").read_bytes() == b"baseline validation\n"


def test_check_blocks_non_posix_or_non_project_review_override(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path, review_path="..\\review.md")

    assert result.returncode == 2
    assert codes(result) == {"REVIEW_PATH_INVALID"}


def test_publish_preserves_candidate_bytes_and_exact_inputs(tmp_path: Path) -> None:
    candidate = prepare(tmp_path)

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-story/delivery.json").read_bytes() == candidate
    receipt = result_payload(result)["receipt"]
    assert [entry["name"] for entry in receipt["outputs"]] == ["delivery"]  # type: ignore[index]
    assert [entry["name"] for entry in receipt["inputs"]] == [  # type: ignore[index]
        "project",
        "requirementsValidation",
        "requirements",
        "asIsValidation",
        "asIs",
        "designValidation",
        "design",
        "technicalRequirements",
    ]


def test_review_mode_writes_bound_story_packet_without_formal_publication(tmp_path: Path) -> None:
    candidate, review = prepare_candidate_first(tmp_path)

    result = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert result_payload(result)["outcome"] == "REVIEW_REQUIRED"
    packet = json.loads(
        (tmp_path / ".ai-sow/work/generate-story/review-packet.json").read_text()
    )
    assert packet["algorithm"] == "ai-sow-owner-review-packet-v1"
    assert packet["candidateOutputs"] == [
        {
            "name": "delivery",
            "path": ".ai-sow/work/generate-story/delivery.candidate.json",
            "sha256": sha256_bytes(candidate),
            "targetPath": ".ai-sow/data/generate-story/delivery.json",
        }
    ]
    assert packet["review"]["sha256"] == sha256_bytes(review)
    assert not (tmp_path / ".ai-sow/reviews/generate-story.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-story/delivery.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-story.json").exists()


def test_publish_approved_requires_bindings_without_formal_writes(tmp_path: Path) -> None:
    prepare_candidate_first(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )

    assert result.returncode == 2
    assert {"REVIEWER_BINDING_MISSING", "APPROVAL_BINDING_MISSING"}.issubset(codes(result))
    assert not (tmp_path / ".ai-sow/reviews/generate-story.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-story/delivery.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-story.json").exists()


def test_publish_approved_preserves_story_candidate_and_review_bytes(tmp_path: Path) -> None:
    candidate, review = prepare_candidate_first(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert (tmp_path / ".ai-sow/reviews/generate-story.md").read_bytes() == review
    assert (tmp_path / ".ai-sow/data/generate-story/delivery.json").read_bytes() == candidate
    receipt = result_payload(result)["receipt"]
    assert receipt["validatorContractVersion"] == "0.3"  # type: ignore[index]


def test_publish_approved_rejects_context_drift_before_formal_writes(tmp_path: Path) -> None:
    prepare_candidate_first(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    write_bytes(
        tmp_path,
        ".ai-sow/work/generate-story/context/design.json",
        canonical_json_bytes({"drifted": True}),
    )

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-story/review.candidate.md",
    )

    assert result.returncode == 2
    assert "CONTEXT_FRAGMENT_STALE" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-story.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-story/delivery.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-story.json").exists()


@pytest.mark.parametrize("owner", ["analyze-requirement", "analyze-as-is", "generate-design"])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("missing", "UPSTREAM_HANDOFF_MISSING"),
        ("invalid", "UPSTREAM_HANDOFF_INVALID"),
        ("stale", "UPSTREAM_HANDOFF_STALE"),
        ("unsupported", "UPSTREAM_CONTRACT_UNSUPPORTED"),
    ],
)
def test_routes_three_owner_handoff_failures_without_candidate_replay(
    tmp_path: Path,
    owner: str,
    failure: str,
    expected: str,
) -> None:
    prepare(tmp_path)
    validation = tmp_path / f".ai-sow/validation/{owner}.json"
    output = tmp_path / {
        "analyze-requirement": ".ai-sow/data/analyze-requirement/requirements.json",
        "analyze-as-is": ".ai-sow/data/analyze-as-is/asis.json",
        "generate-design": ".ai-sow/data/generate-design/design.json",
    }[owner]
    if failure == "missing":
        validation.unlink()
    elif failure == "stale":
        output.write_bytes(output.read_bytes() + b" ")
    else:
        report = json.loads(validation.read_text())
        if failure == "invalid":
            report["passed"] = False
        else:
            report["compilationReceipt"]["validatorContractVersion"] = "99"
        validation.write_text(json.dumps(report))
    write_bytes(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", b"not-json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert codes(result) == {expected}
    assert result_payload(result)["diagnostics"][0]["upstreamOwner"] == owner  # type: ignore[index]


def test_prepare_context_accepts_repository_anchored_document_evidence(
    tmp_path: Path,
) -> None:
    write_bytes(tmp_path, ".ai-sow/project.json", json_bytes(PROJECT))
    write_bytes(tmp_path, SOURCE_PATH, b"Customer profile source.\n")
    publish_requirements(tmp_path)

    repository = {
        "repoId": "customer-portal",
        "path": "repositories/customer-portal",
    }
    evidence_path = "repositories/customer-portal/docs/current-state.md"
    write_bytes(tmp_path, evidence_path, b"Customer API evidence.\n")
    asis = copy.deepcopy(ASIS)
    asis["analysisScope"]["repositorySnapshots"] = [repository]  # type: ignore[index]
    asis["evidence"] = [
        {
            "evidenceId": "evidence-customer-api",
            "kind": "DOCUMENT",
            "reference": "customer-portal:docs/current-state.md#customer-api",
        }
    ]
    write_bytes(tmp_path, ".ai-sow/reviews/analyze-as-is.md", b"Questionnaire: NOT_REQUIRED\n")
    files = ProjectFiles.open(tmp_path)
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("requirementsValidation", "FILE", ".ai-sow/validation/analyze-requirement.json", sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json"))),
            Artifact("requirements", "FILE", ".ai-sow/data/analyze-requirement/requirements.json", sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json"))),
            Artifact("repository:customer-portal", "CANONICAL_JSON", "repository:customer-portal", sha256_bytes(canonical_json_bytes(repository))),
            Artifact("evidence:evidence-customer-api", "FILE", evidence_path, sha256_bytes(files.read_bytes(evidence_path))),
            absent_questionnaire(),
        ),
        {"asIs": json_bytes(asis)},
    )
    publish_design(tmp_path, review=design_review())

    result = run_script(PREPARE_CONTEXT, tmp_path)

    assert result.returncode == 0, result.stdout


def test_prepare_context_projects_relevant_design_decisions(tmp_path: Path) -> None:
    prepare(tmp_path)
    publish_design(tmp_path, review=design_review())

    result = run_script(PREPARE_CONTEXT, tmp_path)

    assert result.returncode == 0, result.stdout
    fragment = json.loads(
        (tmp_path / ".ai-sow/work/generate-story/context/design.json").read_text()
    )
    assert fragment["decisions"] == DESIGN["decisions"]


def test_does_not_replay_design_hld_or_go_live_gate(tmp_path: Path) -> None:
    prepare(tmp_path)
    publish_design(root=tmp_path, review=b"HLD Coverage: BLOCKED\nGo-live Assessment: BLOCKED\n")

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert not {code for code in codes(result) if code.startswith("HLD_") or code.startswith("GO_LIVE_GATE")}


def test_does_not_rediagnose_unrelated_as_is_internal_entities(tmp_path: Path) -> None:
    prepare(tmp_path)
    asis = copy.deepcopy(ASIS)
    asis["topicAssessments"] = "not-an-array"
    publish_asis(tmp_path, asis)
    publish_design(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "SHAPE_INVALID" not in codes(result)


@pytest.mark.parametrize(
    ("payload_argument", "output_path"),
    [
        ("design_payload", ".ai-sow/data/generate-design/design.json"),
        ("technical_payload", ".ai-sow/data/generate-design/requirements.json"),
    ],
)
def test_attributes_unreadable_design_outputs_to_owner_and_path(
    tmp_path: Path,
    payload_argument: str,
    output_path: str,
) -> None:
    prepare(tmp_path)
    overrides = {payload_argument: b"not-json"}
    publish_design(tmp_path, **overrides)  # type: ignore[arg-type]

    result = run_validator(tmp_path)

    assert result.returncode == 2
    diagnostic = result_payload(result)["diagnostics"][0]  # type: ignore[index]
    assert diagnostic["code"] == "UPSTREAM_HANDOFF_INVALID"
    assert diagnostic["upstreamOwner"] == "generate-design"
    assert diagnostic["path"] == output_path


def test_rejects_unknown_gap_feature_reference(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", lambda value: value["gaps"][0].update({"featureId": "feature-unknown"}))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "FEATURE_REF_UNKNOWN" in codes(result)


def test_rejects_unknown_gap_commitment_reference(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", lambda value: value["gaps"][0].update({"commitmentIds": ["commitment-unknown"]}))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "COMMITMENT_REF_UNKNOWN" in codes(result)


def test_rejects_unknown_ac_design_decision_reference(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", lambda value: value["acceptanceCriteria"][1].update({"approvalDecisionIds": ["decision-unknown"]}))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DECISION_REF_UNKNOWN" in codes(result)


def test_rejects_missing_gap_story_or_acceptance_criterion(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", lambda value: value["acceptanceCriteria"].pop())

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "AC_COVERAGE_MISSING" in codes(result)


def test_rejects_integration_boundary_mismatch(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate(tmp_path, ".ai-sow/work/generate-story/delivery.candidate.json", lambda value: value["integrations"][0].update({"deliveryBoundary": "PORT_ONLY"}))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "INTEGRATION_BOUNDARY_MISMATCH" in codes(result)


def test_rejects_technical_aggregate_integration_that_repeats_related_business_targets(
    tmp_path: Path,
) -> None:
    requirements = copy.deepcopy(REQUIREMENTS)
    requirements["features"].append(  # type: ignore[index]
        {"featureId": "feature-customer-export", "epicId": "epic-customer-management"}
    )
    design = copy.deepcopy(DESIGN)
    design["scopeDecisions"].append(  # type: ignore[index]
        {
            "featureId": "feature-customer-export",
            "decision": "IN_SCOPE",
            "rationale": "客户导出仍需交付。",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
            "requiredIntegrationBoundary": "END_TO_END",
            "requiredDecisionKinds": ["INTEGRATION_BOUNDARY"],
        }
    )
    design["decisions"][0]["relatedFeatureIds"].append("feature-customer-export")  # type: ignore[index]
    technical = copy.deepcopy(TECHNICAL)
    technical["features"][0]["relatedBusinessFeatureIds"].append(  # type: ignore[index]
        "feature-customer-export"
    )
    delivery = fixture("delivery.valid.json")
    delivery["stories"][0]["requiredIntegrationBoundary"] = "END_TO_END"
    delivery["gaps"].append(
        {
            "gapId": "gap-customer-export",
            "featureId": "feature-customer-export",
            "name": "客户导出交付差距",
            "description": "客户导出端到端结果尚未交付。",
            "commitmentIds": [],
        }
    )
    delivery["stories"].append(
        {
            "storyId": "story-customer-export",
            "gapId": "gap-customer-export",
            "name": "交付客户导出",
            "description": "交付客户导出端到端结果。",
            "uatRelevant": True,
            "requiredIntegrationBoundary": "END_TO_END",
        }
    )
    delivery["acceptanceCriteria"].append(
        {
            "acceptanceCriterionId": "ac-customer-export",
            "storyId": "story-customer-export",
            "sequence": 1,
            "name": "客户导出可取得完整结果。",
            "decisionGate": "REQUIRED",
            "approvalDecisionIds": ["decision-profile-api"],
        }
    )
    delivery["integrations"].extend(
        [
            {
                "integrationId": "integration-customer-profile-business",
                "name": "客户档案接口集成",
                "storyId": "story-customer-profile",
                "source": "Customer Portal（客户门户）",
                "target": "Customer API（客户接口）",
                "trigger": "查看客户档案",
                "direction": "OUTBOUND",
                "purpose": "取得客户档案",
                "owner": "INTERNAL",
                "deliveryBoundary": "END_TO_END",
                "targetKind": "SYSTEM",
                "decisionIds": ["decision-profile-api"],
            },
            {
                "integrationId": "integration-customer-export-business",
                "name": "客户导出接口集成",
                "storyId": "story-customer-export",
                "source": "Customer Portal（客户门户）",
                "target": "Customer Export API（客户导出接口）",
                "trigger": "导出客户档案",
                "direction": "OUTBOUND",
                "purpose": "取得客户导出结果",
                "owner": "INTERNAL",
                "deliveryBoundary": "END_TO_END",
                "targetKind": "SYSTEM",
                "decisionIds": ["decision-profile-api"],
            },
        ]
    )
    delivery["integrations"][0]["target"] = (
        "Customer API（客户接口）、Customer Export API（客户导出接口）"
    )

    prepare(
        tmp_path,
        requirements=requirements,
        design=design,
        technical=technical,
        delivery=delivery,
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "INTEGRATION_SCOPE_OVERLAP" in codes(result)


def test_consumes_approved_default_exactly_once(tmp_path: Path) -> None:
    prepare(tmp_path, questionnaire=questionnaire_bytes())

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_review_stable_ids_are_an_order_independent_set(tmp_path: Path) -> None:
    prepare(tmp_path)
    delivery = fixture("delivery.valid.json")
    expected = ", ".join(stable_ids(delivery))
    reordered = ", ".join(reversed(stable_ids(delivery)))
    review = tmp_path / ".ai-sow/reviews/generate-story.md"
    review.write_text(review.read_text().replace(f"Stable IDs: {expected}", f"Stable IDs: {reordered}"))

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_questionnaire_story_ids_are_an_order_independent_set(tmp_path: Path) -> None:
    prepare(tmp_path, questionnaire=questionnaire_bytes())
    delivery = json.loads((tmp_path / ".ai-sow/work/generate-story/delivery.candidate.json").read_text())
    next(
        story
        for story in delivery["stories"]
        if story["storyId"] == "story-customer-profile"
    )["assumptionId"] = "assumption-profile-hosting"
    write_bytes(
        tmp_path,
        ".ai-sow/work/generate-story/delivery.candidate.json",
        json_bytes(delivery),
    )
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-story.md",
        story_review(
            delivery,
            questionnaire_map=(
                "ARQ-001=assumption-profile-hosting->"
                "story-customer-profile,story-profile-hosting-discovery"
            ),
        ).encode(),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_unconsumed_approved_default(tmp_path: Path) -> None:
    prepare(tmp_path, questionnaire=questionnaire_bytes())
    mutate(
        tmp_path,
        ".ai-sow/work/generate-story/delivery.candidate.json",
        lambda value: value["assumptions"][0].update({"handling": "在部署设计批准前解决。"}),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "QUESTIONNAIRE_CONSUMPTION_INVALID" in codes(result)


def test_rejects_incomplete_ten_concern_mapping(tmp_path: Path) -> None:
    prepare(tmp_path)
    delivery = fixture("delivery.valid.json")
    write_bytes(tmp_path, ".ai-sow/reviews/generate-story.md", story_review(delivery, omit_concern="OBSERVABILITY").encode())

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_CONCERN_MISSING" in codes(result)


def test_rejects_in_scope_concern_without_delivery_mapping(tmp_path: Path) -> None:
    prepare(tmp_path)
    review = tmp_path / ".ai-sow/reviews/generate-story.md"
    review.write_text(
        review.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | gap-profile-api | "
            "story-profile-api | — |",
            "| PRODUCTION_SCOPE | IN_SCOPE | — | — | — | — |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_IN_SCOPE_MAPPING_MISSING" in codes(result)


def test_accepts_concern_mapped_only_through_assumption_story_gap(tmp_path: Path) -> None:
    prepare(tmp_path)
    review = tmp_path / ".ai-sow/reviews/generate-story.md"
    review.write_text(
        review.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | gap-profile-api | "
            "story-profile-api | — |",
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-customer-profile | gap-customer-profile | "
            "— | assumption-profile-hosting |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def input_hash(report: dict[str, object], name: str) -> str:
    matches = [entry for entry in report["compilationReceipt"]["inputs"] if entry["name"] == name]  # type: ignore[index]
    assert len(matches) == 1
    return matches[0]["sha256"]


def test_rebind_changes_design_receipt_without_changing_delivery_bytes(tmp_path: Path) -> None:
    candidate = prepare(tmp_path)
    published = run_validator(tmp_path, "publish")
    assert published.returncode == 0, published.stdout
    old_report = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-story.json").read_text()
    )
    old_design = input_hash(old_report, "designValidation")
    publish_design(tmp_path, review=b"Design review approved after wording update.\n")
    new_design = sha256_bytes((tmp_path / ".ai-sow/validation/generate-design.json").read_bytes())
    delivery = fixture("delivery.valid.json")
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-story.md",
        story_review(delivery, rebind={"old": old_design, "new": new_design}).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-story/delivery.json").read_bytes() == candidate
    rebound = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-story.json").read_text()
    )
    assert input_hash(rebound, "designValidation") == new_design


def test_skill_uses_review_candidate_publish_and_stop_flow() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        "当前 Stage Agent",
        "fresh-context Reviewer",
        "scripts/prepare_context.py",
        "scripts/render_review.py",
        "ai-sow-owner-review-packet-v1",
        "ai-sow-owner-reviewer-v1",
        "ai-sow-owner-approval-v1",
        "--mode review",
        "--mode publish-approved",
        "--mode check",
        "--mode rebind",
        "delivery.candidate.json",
        "只推荐用户显式调用 `generate-task`",
        "然后 STOP",
        "不得重新执行 Design 的 HLD/Go-live 门禁",
        "Concern -> Feature -> Gap -> Story/Assumption/Risk",
        "已批准的 Story/AC 是业务交付合同",
        "不得为实现机制创建 Gap、Story 或 AC",
    ):
        assert required in contract


def test_review_template_documents_complete_stable_ids_and_rebind_declarations() -> None:
    template = (SKILL_ROOT / "references/review-template.md").read_text(encoding="utf-8")
    for required in (
        "Stable IDs: gap-example, story-example, ac-example, integration-example, assumption-example",
        "Impact: NO_CHANGE",
        "Upstream: generate-design",
        "Previous Receipt SHA-256: generate-design=<old-hash>",
        "Current Receipt SHA-256: generate-design=<new-hash>",
        "Impact Rationale: gap-example、story-example、ac-example、integration-example、assumption-example",
    ):
        assert required in template


def test_validator_does_not_import_any_review_gate() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "review_gates" not in text
