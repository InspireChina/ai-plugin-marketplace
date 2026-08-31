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
CONTEXT_SCRIPT = SKILL_ROOT / "scripts/prepare_context.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_review.py"
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
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.2",),
    validation_path=".ai-sow/validation/analyze-as-is.json",
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-as-is.md"),),
    outputs=(("asIs", ".ai-sow/data/analyze-as-is/asis.json"),),
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
    "projectId": "project-design-test",
    "name": "设计交接测试",
    "pluginVersion": "0.1.0-beta.1",
    "templateVersion": "1.3",
}
SOURCE_PATH = ".ai-sow/inputs/analyze-requirement/customer-profile.md"
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
    "items": [
        {
            "asIsItemId": "asis-customer-api",
            "topic": "APPLICATION",
            "itemType": "COMPONENT",
            "name": "现有客户接口",
            "summary": "当前接口提供只读客户档案能力。",
            "repositoryIds": [],
        }
    ],
    "commitments": [],
    "effectiveStartItems": [
        {
            "effectiveStartItemId": "effective-start-customer-api",
            "sourceItemIds": ["asis-customer-api"],
            "commitmentIds": [],
        }
    ],
    "coverage": [
        {
            "featureId": "feature-customer-profile",
            "status": "PARTIAL",
            "effectiveStartItemIds": ["effective-start-customer-api"],
            "commitmentIds": [],
            "uncertaintyIds": [],
        }
    ],
    "uncertainties": [],
    "evidence": [
        {
            "evidenceId": "evidence-customer-api",
            "kind": "DOCUMENT",
            "reference": "requirements:feature-customer-profile",
            "summary": "获批需求和调查记录确认当前接口边界。",
            "supportsIds": ["asis-customer-api", "effective-start-customer-api"],
        }
    ],
}


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_bytes(root: Path, relative: str, payload: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def write_json(root: Path, relative: str, value: object) -> Path:
    return write_bytes(root, relative, json_bytes(value))


def fixture(name: str) -> dict[str, object]:
    return json.loads((SKILL_ROOT / f"fixtures/{name}").read_text(encoding="utf-8"))


def questionnaire_absent_artifact() -> Artifact:
    logical = canonical_json_bytes({"declaration": "NOT_REQUIRED"})
    return Artifact("questionnaire", "QUESTIONNAIRE_PRESENCE", "questionnaire:NOT_REQUIRED", sha256_bytes(logical))


def publish_requirements(root: Path, requirements: dict[str, object] | None = None) -> None:
    files = ProjectFiles.open(root)
    source = files.read_bytes(SOURCE_PATH)
    value = copy.deepcopy(requirements or REQUIREMENTS)
    value["sourceDocuments"][0]["sha256"] = sha256_bytes(source)  # type: ignore[index]
    publish_owner(
        files,
        REQUIREMENT_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("source:source-document-customer-profile", "FILE", SOURCE_PATH, sha256_bytes(source)),
            questionnaire_absent_artifact(),
        ),
        {"requirements": json_bytes(value)},
    )


def publish_asis(root: Path, value: dict[str, object] | None = None) -> None:
    files = ProjectFiles.open(root)
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact(
                "requirementsValidation",
                "FILE",
                ".ai-sow/validation/analyze-requirement.json",
                sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json")),
            ),
            Artifact(
                "requirements",
                "FILE",
                ".ai-sow/data/analyze-requirement/requirements.json",
                sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json")),
            ),
            questionnaire_absent_artifact(),
        ),
        {"asIs": json_bytes(value or ASIS)},
    )


def design_review(
    design: dict[str, object],
    technical: dict[str, object],
    *,
    hld: str = "PASSED",
    go_live: str = "PASSED",
    omit_concern: str | None = None,
    rebind: dict[str, str] | None = None,
) -> str:
    design_ids = [
        *(entry["designItemId"] for entry in design["designItems"]),  # type: ignore[index]
        *(entry["architectureDeltaId"] for entry in design["architectureDeltas"]),  # type: ignore[index]
        *(entry["designDecisionId"] for entry in design["decisions"]),  # type: ignore[index]
    ]
    technical_ids = [
        *(entry["epicId"] for entry in technical["epics"]),  # type: ignore[index]
        *(entry["featureId"] for entry in technical["features"]),  # type: ignore[index]
    ]
    rows = []
    for concern in GO_LIVE_CONCERNS:
        if concern == omit_concern:
            continue
        if concern == "PRODUCTION_SCOPE":
            row = (
                concern,
                "IN_SCOPE",
                "feature-profile-api",
                "—",
                "—",
                "项目负责客户档案 API，客户负责生产审批。",
                "获批技术范围要求该 API 达到生产可用。",
            )
        else:
            row = (
                concern,
                "NOT_APPLICABLE",
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
            "Upstream: analyze-requirement, analyze-as-is\n"
            f"Previous Receipt SHA-256: analyze-requirement={rebind['oldRequirements']}, "
            f"analyze-as-is={rebind['oldAsIs']}\n"
            f"Current Receipt SHA-256: analyze-requirement={rebind['newRequirements']}, "
            f"analyze-as-is={rebind['newAsIs']}\n"
            f"Impact Rationale: {'、'.join([*design_ids, *technical_ids])} 均确认不受影响。\n"
        )
    return (
        "# 目标设计评审\n\n"
        "## 目标设计\n\n目标方案已形成。\n\n"
        f"Design IDs: {', '.join(design_ids)}\n"
        f"Technical IDs: {', '.join(technical_ids)}\n\n"
        "## Architecture Delta\n\n架构变化已核对。\n\n"
        "## Design Decision\n\n设计决策已核对。\n\n"
        "## Scope\n\n全部 Feature 已处置。\n\n"
        "## TECHNICAL requirements\n\n来源与派生技术需求已核对。\n\n"
        "## 高阶设计覆盖门禁\n\n"
        f"HLD Coverage: {hld}\n\n"
        "## 上线范围门禁\n\n"
        "| Concern | Disposition | Feature IDs | Effective Start IDs | Evidence IDs | 责任边界 | 依据 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
        f"Go-live Assessment: {go_live}\n\n"
        "## 审查与批准\n\nReviewer: PASS\nUser Approval: APPROVED\n"
        + impact
    )


def prepare(root: Path) -> tuple[bytes, bytes]:
    design = fixture("design.valid.json")
    technical = fixture("requirements.valid.json")
    write_json(root, ".ai-sow/project.json", PROJECT)
    write_bytes(root, SOURCE_PATH, b"Customer profile source.\n")
    write_bytes(root, ".ai-sow/reviews/analyze-requirement.md", b"Questionnaire: NOT_REQUIRED\n")
    publish_requirements(root)
    write_bytes(root, ".ai-sow/reviews/analyze-as-is.md", b"Questionnaire: NOT_REQUIRED\n")
    publish_asis(root)
    design_payload = (json.dumps(design, ensure_ascii=False, indent=3) + "\n").encode()
    technical_payload = (json.dumps(technical, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    write_bytes(root, ".ai-sow/work/generate-design/design.candidate.json", design_payload)
    write_bytes(root, ".ai-sow/work/generate-design/requirements.candidate.json", technical_payload)
    write_bytes(root, ".ai-sow/reviews/generate-design.md", design_review(design, technical).encode())
    return design_payload, technical_payload


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
        text=True, encoding="utf-8",
        check=False,
    )


STAGING_ROOT = ".ai-sow/.stage-0123456789ab"


def managed_path(root: Path, logical_path: str) -> Path:
    staged = root / STAGING_ROOT / logical_path.removeprefix(".ai-sow/")
    return staged if staged.exists() else root / logical_path


def run_context(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTEXT_SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def run_renderer(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def write_review_source(root: Path, *, omit_concern: str | None = None) -> None:
    concerns = []
    for concern in GO_LIVE_CONCERNS:
        if concern == omit_concern:
            continue
        if concern == "PRODUCTION_SCOPE":
            concerns.append(
                {
                    "basis": "获批技术范围要求该 API 达到生产可用。",
                    "concern": concern,
                    "disposition": "IN_SCOPE",
                    "effectiveStartIds": [],
                    "evidenceIds": [],
                    "featureIds": ["feature-profile-api"],
                    "responsibilityBoundary": "项目负责客户档案 API，客户负责生产审批。",
                }
            )
        else:
            concerns.append(
                {
                    "basis": "已确认该关注点与当前范围无关。",
                    "concern": concern,
                    "disposition": "NOT_APPLICABLE",
                    "effectiveStartIds": [],
                    "evidenceIds": [],
                    "featureIds": [],
                    "responsibilityBoundary": "该关注点不进入本项目责任边界。",
                }
            )
    write_json(
        root,
        ".ai-sow/work/generate-design/review-source.json",
        {
            "architectureDeltaReview": "架构变化已逐项相对 Effective Start 核对。",
            "concerns": concerns,
            "designDecisionReview": "设计决策、证据和类型化义务已逐项核对。",
            "scopeReview": "全部 BUSINESS 与 TECHNICAL Feature 已唯一处置。",
            "targetDesign": "目标方案、系统边界、关键流程、数据与质量目标已形成。",
            "technicalRequirementsReview": "SOURCE_INPUT 与 DESIGN_DERIVED 技术需求已核对。",
        },
    )


def prepare_review_candidate(
    root: Path,
    *,
    omit_concern: str | None = None,
) -> tuple[bytes, bytes, bytes]:
    design, technical = prepare(root)
    (root / ".ai-sow/reviews/generate-design.md").unlink()
    context = run_context(root)
    assert context.returncode == 0, context.stdout
    write_review_source(root, omit_concern=omit_concern)
    rendered = run_renderer(root)
    assert rendered.returncode == 0, rendered.stdout
    review = (root / ".ai-sow/work/generate-design/review.candidate.md").read_bytes()
    return design, technical, review


def test_renderer_owns_candidate_structure_counts(tmp_path: Path) -> None:
    design_bytes, technical_bytes, review_bytes = prepare_review_candidate(tmp_path)
    design = json.loads(design_bytes)
    technical = json.loads(technical_bytes)
    review = review_bytes.decode("utf-8")
    assert (
        "Structure Counts: "
        f"designItems={len(design['designItems'])}, "
        f"architectureDeltas={len(design['architectureDeltas'])}, "
        f"decisions={len(design['decisions'])}, "
        f"scopeDecisions={len(design['scopeDecisions'])}, "
        f"technicalEpics={len(technical['epics'])}, "
        f"technicalFeatures={len(technical['features'])}"
    ) in review
    assert "### BUSINESS / TECHNICAL Boundary Matrix" in review
    assert (
        "| feature-customer-profile | feature-profile-api | NONE | END_TO_END | "
        "SINGLE_END_TO_END_OWNER |"
    ) in review

    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/review-source.json",
        lambda value: value.update(
            {"architectureDeltaReview": "共九项架构变化，均已完成核对。"}
        ),
    )
    blocked = run_renderer(tmp_path)
    assert blocked.returncode == 2
    assert "must not manually state candidate object counts" in blocked.stdout


def test_renderer_requires_explicit_boundary_for_overlapping_technical_features(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    (tmp_path / ".ai-sow/reviews/generate-design.md").unlink()
    context = run_context(tmp_path)
    assert context.returncode == 0, context.stdout
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/requirements.candidate.json",
        lambda value: value["features"].append(
            {
                "featureId": "feature-profile-environment",
                "epicId": "epic-platform",
                "name": "客户档案环境配置",
                "description": "交付客户档案 API 的环境配置结果。",
                "source": {
                    "type": "SOURCE_INPUT",
                    "sourceDocumentIds": ["source-document-customer-profile"],
                    "sourceReferences": ["section:technical-platform"],
                },
            }
        ),
    )
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        lambda value: value["scopeDecisions"].append(
            {
                "featureId": "feature-profile-environment",
                "decision": "IN_SCOPE",
                "rationale": "环境配置需要独立验收。",
                "designItemIds": ["design-customer-profile"],
                "effectiveStartItemIds": [],
                "requiredIntegrationBoundary": "NONE",
                "requiredDecisionKinds": [],
            }
        ),
    )
    write_review_source(tmp_path)

    blocked = run_renderer(tmp_path)

    assert blocked.returncode == 2
    assert "feature-profile-api" in blocked.stdout
    assert "feature-profile-environment" in blocked.stdout

    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/review-source.json",
        lambda value: value.update(
            {
                "featureBoundaryReview": [
                    {
                        "featureIds": [
                            "feature-profile-api",
                            "feature-profile-environment",
                        ],
                        "nonOverlapRationale": (
                            "前者验收 API 业务操作边界，后者只验收环境配置就绪结果。"
                        ),
                    }
                ]
            }
        ),
    )

    rendered = run_renderer(tmp_path)

    assert rendered.returncode == 0, rendered.stdout
    review = (
        tmp_path / ".ai-sow/work/generate-design/review.candidate.md"
    ).read_text(encoding="utf-8")
    assert "## Feature Boundary Review" in review
    assert "前者验收 API 业务操作边界" in review


def test_design_boundary_matrix_rejects_duplicate_end_to_end(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)

    def duplicate_end_to_end_owner(value: dict[str, object]) -> None:
        business_scope = next(
            entry
            for entry in value["scopeDecisions"]  # type: ignore[index]
            if entry["featureId"] == "feature-customer-profile"
        )
        business_scope["requiredIntegrationBoundary"] = "END_TO_END"

    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        duplicate_end_to_end_owner,
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DESIGN_BOUNDARY_END_TO_END_DUPLICATE" in codes(result)
    diagnostic = next(
        entry
        for entry in json.loads(result.stdout)["diagnostics"]
        if entry["code"] == "DESIGN_BOUNDARY_END_TO_END_DUPLICATE"
    )
    assert diagnostic["featureIds"] == [
        "feature-customer-profile",
        "feature-profile-api",
    ]


def bind_review_packet(root: Path) -> str:
    packet = (root / ".ai-sow/work/generate-design/review-packet.json").read_bytes()
    digest = sha256_bytes(packet)
    for filename, algorithm, decision in (
        ("reviewer.json", "ai-sow-owner-reviewer-v1", "PASS"),
        ("approval.json", "ai-sow-owner-approval-v1", "APPROVED"),
    ):
        write_bytes(
            root,
            f".ai-sow/work/generate-design/{filename}",
            canonical_json_bytes(
                {
                    "algorithm": algorithm,
                    "decision": decision,
                    "owner": "generate-design",
                    "packetSha256": digest,
                }
            ),
        )
    return digest


def payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {entry["code"] for entry in payload(result)["diagnostics"]}  # type: ignore[index]


def mutate_json(root: Path, relative: str, mutation: object) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)  # type: ignore[operator]
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_prepare_context_closes_business_asis_uncertainty_start_and_source_anchors(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    (tmp_path / ".ai-sow/reviews/generate-design.md").unlink()

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout
    context_root = tmp_path / ".ai-sow/work/generate-design/context"
    manifest = json.loads((context_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "ai-sow-generate-design-context-v1"
    assert [entry["name"] for entry in manifest["fragments"]] == [
        "businessRequirements",
        "asIsCoverage",
        "uncertainties",
        "effectiveStart",
        "sourceAnchors",
    ]
    assert manifest["reviewClaims"]["status"] == "READY"
    assert manifest["reviewClaims"]["fragment"]["name"] == "claims"
    business = json.loads((context_root / "business-requirements.json").read_text(encoding="utf-8"))
    assert business["features"] == REQUIREMENTS["features"]
    assert set(business) == {"epics", "features"}
    starts = json.loads((context_root / "effective-start.json").read_text(encoding="utf-8"))
    assert starts["effectiveStartItems"] == ASIS["effectiveStartItems"]
    assert set(starts) == {"effectiveStartItems", "items", "commitments"}
    anchors = json.loads((context_root / "source-anchors.json").read_text(encoding="utf-8"))
    assert anchors["sourceDocuments"][0]["sourceDocumentId"] == (
        "source-document-customer-profile"
    )
    assert anchors["normalizedItems"] == REQUIREMENTS["normalizedItems"]
    assert anchors["evidence"] == ASIS["evidence"]
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/design.json").exists()


def test_prepare_context_accepts_asis_repository_document_receipt(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    asis = copy.deepcopy(ASIS)
    repository = {
        "repoId": "customer-portal",
        "path": "repositories/customer-portal",
        "revision": "a" * 40,
        "dirty": False,
    }
    evidence_path = "repositories/customer-portal/docs/current-state.md"
    evidence_payload = b"# Current state\n\nThe profile API is read-only.\n"
    asis["analysisScope"]["mode"] = "BROWNFIELD"  # type: ignore[index]
    asis["analysisScope"]["repositorySnapshots"] = [repository]  # type: ignore[index]
    asis["evidence"] = [
        {
            "evidenceId": "evidence-customer-api",
            "kind": "DOCUMENT",
            "reference": "customer-portal:docs/current-state.md#L3",
            "summary": "现状登记确认接口只读边界。",
            "supportsIds": ["asis-customer-api", "effective-start-customer-api"],
        }
    ]
    write_bytes(tmp_path, evidence_path, evidence_payload)
    files = ProjectFiles.open(tmp_path)
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact(
                "project",
                "FILE",
                ".ai-sow/project.json",
                sha256_bytes(files.read_bytes(".ai-sow/project.json")),
            ),
            Artifact(
                "requirementsValidation",
                "FILE",
                ".ai-sow/validation/analyze-requirement.json",
                sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json")),
            ),
            Artifact(
                "requirements",
                "FILE",
                ".ai-sow/data/analyze-requirement/requirements.json",
                sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json")),
            ),
            Artifact(
                "repository:customer-portal",
                "CANONICAL_JSON",
                "repository:customer-portal",
                sha256_bytes(canonical_json_bytes(repository)),
            ),
            Artifact(
                "evidence:evidence-customer-api",
                "FILE",
                evidence_path,
                sha256_bytes(evidence_payload),
            ),
            questionnaire_absent_artifact(),
        ),
        {"asIs": json_bytes(asis)},
    )

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"
    anchors = json.loads(
        (
            tmp_path
            / ".ai-sow/work/generate-design/context/source-anchors.json"
        ).read_text(encoding="utf-8")
    )
    assert anchors["repositorySnapshots"] == [repository]
    assert anchors["evidence"][0]["resolvedPath"] == evidence_path


def test_review_mode_binds_both_candidates_without_formal_writes(tmp_path: Path) -> None:
    design, technical, review = prepare_review_candidate(tmp_path)

    result = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "REVIEW_REQUIRED"
    packet = json.loads(
        (tmp_path / ".ai-sow/work/generate-design/review-packet.json").read_text(encoding="utf-8")
    )
    assert packet["algorithm"] == "ai-sow-owner-review-packet-v1"
    assert packet["review"]["sha256"] == sha256_bytes(review)
    assert packet["candidateOutputs"] == [
        {
            "name": "design",
            "path": ".ai-sow/work/generate-design/design.candidate.json",
            "sha256": sha256_bytes(design),
            "targetPath": ".ai-sow/data/generate-design/design.json",
        },
        {
            "name": "technicalRequirements",
            "path": ".ai-sow/work/generate-design/requirements.candidate.json",
            "sha256": sha256_bytes(technical),
            "targetPath": ".ai-sow/data/generate-design/requirements.json",
        },
    ]
    assert packet["riskSummary"]["path"] == (
        ".ai-sow/work/generate-design/risk-summary.md"
    )
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/design.json").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/requirements.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-design.json").exists()


def test_publish_approved_requires_bindings_and_keeps_formal_paths_absent(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 2
    assert {"REVIEWER_BINDING_MISSING", "APPROVAL_BINDING_MISSING"}.issubset(
        codes(result)
    )
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/design.json").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/requirements.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-design.json").exists()


def test_publish_approved_preserves_both_candidate_and_review_byte_streams(
    tmp_path: Path,
) -> None:
    design, technical, review = prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert (tmp_path / ".ai-sow/reviews/generate-design.md").read_bytes() == review
    assert (tmp_path / ".ai-sow/data/generate-design/design.json").read_bytes() == design
    assert (
        tmp_path / ".ai-sow/data/generate-design/requirements.json"
    ).read_bytes() == technical
    receipt = payload(result)["receipt"]
    assert receipt["validatorContractVersion"] == "0.3"
    assert [entry["sha256"] for entry in receipt["outputs"]] == [
        sha256_bytes(design),
        sha256_bytes(technical),
    ]
    assert receipt["reviews"][0]["sha256"] == sha256_bytes(review)


def test_publish_approved_rejects_second_candidate_drift_before_formal_writes(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    technical = tmp_path / ".ai-sow/work/generate-design/requirements.candidate.json"
    technical.write_bytes(technical.read_bytes() + b" ")

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 2
    assert "REVIEW_PACKET_CANDIDATE_STALE" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/design.json").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/requirements.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-design.json").exists()


def test_publish_approved_rejects_context_fragment_drift_before_formal_writes(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    write_bytes(
        tmp_path,
        ".ai-sow/work/generate-design/context/source-anchors.json",
        canonical_json_bytes({"drifted": True}),
    )

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 2
    assert "CONTEXT_FRAGMENT_STALE" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/design.json").exists()
    assert not (tmp_path / ".ai-sow/data/generate-design/requirements.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-design.json").exists()


def test_review_mode_fail_closes_incomplete_hld_go_live_professional_assessment(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path, omit_concern="OBSERVABILITY")

    result = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-design/review.candidate.md",
    )

    assert result.returncode == 2
    assert "GO_LIVE_CONCERN_MISSING" in codes(result)
    assert not (tmp_path / ".ai-sow/work/generate-design/review-packet.json").exists()
    assert not (tmp_path / ".ai-sow/reviews/generate-design.md").exists()


def test_check_accepts_source_input_and_design_derived_requirements(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"
    assert not (tmp_path / ".ai-sow/validation/generate-design.json").exists()


def test_check_accepts_work_only_review_override_and_ignores_default_review(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-design/review.md"
    review = (tmp_path / ".ai-sow/reviews/generate-design.md").read_bytes()
    write_bytes(tmp_path, review_path, review)
    write_bytes(tmp_path, ".ai-sow/reviews/generate-design.md", b"default review must not be read\n")

    result = run_validator(tmp_path, review_path=review_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"


def test_check_reports_override_path_for_review_and_gate_diagnostics(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-design/review.md"
    review = (tmp_path / ".ai-sow/reviews/generate-design.md").read_text(encoding="utf-8")
    write_bytes(
        tmp_path,
        review_path,
        review.replace("Reviewer: PASS", "Reviewer: FAIL").replace(
            "HLD Coverage: PASSED",
            "HLD Coverage: BLOCKED",
        ).encode(),
    )

    result = run_validator(tmp_path, review_path=review_path)

    diagnostics = payload(result)["diagnostics"]
    by_code = {entry["code"]: entry for entry in diagnostics}  # type: ignore[index]
    assert by_code["REVIEW_NOT_PASSED"]["path"] == review_path
    assert by_code["HLD_GATE_NOT_PASSED"]["path"] == review_path


@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_write_modes_block_review_override(tmp_path: Path, mode: str) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/20260825-design/review.md"
    write_bytes(
        tmp_path,
        review_path,
        (tmp_path / ".ai-sow/reviews/generate-design.md").read_bytes(),
    )
    write_bytes(tmp_path, ".ai-sow/validation/generate-design.json", b"baseline validation\n")

    result = run_validator(tmp_path, mode, review_path=review_path)

    assert result.returncode == 2
    assert codes(result) == {"REVIEW_PATH_MODE_INVALID"}
    assert (tmp_path / ".ai-sow/validation/generate-design.json").read_bytes() == b"baseline validation\n"


def test_check_blocks_non_posix_or_non_project_review_override(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path, review_path="../review.md")

    assert result.returncode == 2
    assert codes(result) == {"REVIEW_PATH_INVALID"}


def test_publish_preserves_both_candidate_byte_streams_and_names_outputs(tmp_path: Path) -> None:
    design_bytes, technical_bytes = prepare(tmp_path)

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-design/design.json").read_bytes() == design_bytes
    assert managed_path(tmp_path, ".ai-sow/data/generate-design/requirements.json").read_bytes() == technical_bytes
    receipt = payload(result)["receipt"]
    assert [entry["name"] for entry in receipt["outputs"]] == ["design", "technicalRequirements"]  # type: ignore[index]
    assert [entry["name"] for entry in receipt["inputs"]] == [  # type: ignore[index]
        "project",
        "requirementsValidation",
        "requirements",
        "asIsValidation",
        "asIs",
    ]


def test_failed_publish_preserves_both_existing_stable_outputs(tmp_path: Path) -> None:
    prepare(tmp_path)
    stable_design = write_bytes(tmp_path, ".ai-sow/data/generate-design/design.json", b'{"old":"design"}\n').read_bytes()
    stable_technical = write_bytes(tmp_path, ".ai-sow/data/generate-design/requirements.json", b'{"old":"technical"}\n').read_bytes()
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        lambda value: value["scopeDecisions"][1].update({"designItemIds": []}),
    )

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 2
    assert (tmp_path / ".ai-sow/data/generate-design/design.json").read_bytes() == stable_design
    assert (tmp_path / ".ai-sow/data/generate-design/requirements.json").read_bytes() == stable_technical
    report = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-design.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False and "compilationReceipt" not in report


@pytest.mark.parametrize("owner", ["analyze-requirement", "analyze-as-is"])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("missing", "UPSTREAM_HANDOFF_MISSING"),
        ("invalid", "UPSTREAM_HANDOFF_INVALID"),
        ("stale", "UPSTREAM_HANDOFF_STALE"),
        ("unsupported", "UPSTREAM_CONTRACT_UNSUPPORTED"),
    ],
)
def test_routes_four_handoff_failures_without_candidate_replay(
    tmp_path: Path,
    owner: str,
    failure: str,
    expected: str,
) -> None:
    prepare(tmp_path)
    validation = tmp_path / f".ai-sow/validation/{owner}.json"
    output = tmp_path / (
        ".ai-sow/data/analyze-requirement/requirements.json"
        if owner == "analyze-requirement"
        else ".ai-sow/data/analyze-as-is/asis.json"
    )
    if failure == "missing":
        validation.unlink()
    elif failure == "stale":
        output.write_bytes(output.read_bytes() + b" ")
    else:
        report = json.loads(validation.read_text(encoding="utf-8"))
        if failure == "invalid":
            report["passed"] = False
        else:
            report["compilationReceipt"]["validatorContractVersion"] = "99"
        validation.write_text(json.dumps(report), encoding="utf-8")
    write_bytes(tmp_path, ".ai-sow/work/generate-design/design.candidate.json", b"not-json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert codes(result) == {expected}
    assert payload(result)["diagnostics"][0]["upstreamOwner"] == owner  # type: ignore[index]


def test_does_not_replay_upstream_business_type_rule(tmp_path: Path) -> None:
    prepare(tmp_path)
    requirements = copy.deepcopy(REQUIREMENTS)
    requirements["epics"][0]["type"] = "TECHNICAL"  # type: ignore[index]
    publish_requirements(tmp_path, requirements)
    publish_asis(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "SOURCE_REQUIREMENT_TYPE_INVALID" not in codes(result)


def test_requires_typed_scope_obligation(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        lambda value: value["scopeDecisions"][1]["requiredDecisionKinds"].append("PROVIDER_TARGET"),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "SCOPE_OBLIGATION_MISSING" in codes(result)


def test_requires_evidence_for_typed_decision(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        lambda value: value["decisions"][0].update({"evidenceIds": []}),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DECISION_EVIDENCE_REQUIRED" in codes(result)


def test_rejects_unknown_architecture_delta_effective_start(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/design.candidate.json",
        lambda value: value["architectureDeltas"][0].update({"effectiveStartItemIds": ["effective-start-unknown"]}),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "EFFECTIVE_START_REF_UNKNOWN" in codes(result)


def test_rejects_unknown_design_decision_in_derived_requirement(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/requirements.candidate.json",
        lambda value: value["features"][0]["source"].update({"designDecisionIds": ["decision-unknown"]}),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DESIGN_DECISION_REF_UNKNOWN" in codes(result)


def test_rejects_unknown_related_business_feature(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/requirements.candidate.json",
        lambda value: value["features"][0].update(
            {"relatedBusinessFeatureIds": ["feature-does-not-exist"]}
        ),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "BUSINESS_FEATURE_REF_UNKNOWN" in codes(result)


def test_rejects_generic_derived_non_delivery_impact(tmp_path: Path) -> None:
    prepare(tmp_path)
    rationale = (
        "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | 系统 -> 会受到影响"
    )
    mutate_json(
        tmp_path,
        ".ai-sow/work/generate-design/requirements.candidate.json",
        lambda value: value["features"][0]["source"].update({"rationale": rationale}),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DERIVED_RATIONALE_IMPACT_GENERIC" in codes(result)


def test_rejects_hld_gate_not_passed(tmp_path: Path) -> None:
    prepare(tmp_path)
    design = fixture("design.valid.json")
    technical = fixture("requirements.valid.json")
    write_bytes(tmp_path, ".ai-sow/reviews/generate-design.md", design_review(design, technical, hld="BLOCKED").encode())

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "HLD_GATE_NOT_PASSED" in codes(result)


def test_rejects_incomplete_ten_concern_go_live_matrix(tmp_path: Path) -> None:
    prepare(tmp_path)
    design = fixture("design.valid.json")
    technical = fixture("requirements.valid.json")
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-design.md",
        design_review(design, technical, omit_concern="OBSERVABILITY").encode(),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_CONCERN_MISSING" in codes(result)


def test_rejects_review_id_drift(tmp_path: Path) -> None:
    prepare(tmp_path)
    review = tmp_path / ".ai-sow/reviews/generate-design.md"
    review.write_text(review.read_text(encoding="utf-8").replace("design-customer-profile", "design-other", 1), encoding="utf-8")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "REVIEW_ID_SET_MISMATCH" in codes(result)


def input_hash(report: dict[str, object], name: str) -> str:
    matches = [entry for entry in report["compilationReceipt"]["inputs"] if entry["name"] == name]  # type: ignore[index]
    assert len(matches) == 1
    return matches[0]["sha256"]


def test_rebind_updates_both_upstreams_without_changing_either_output(tmp_path: Path) -> None:
    design_bytes, technical_bytes = prepare(tmp_path)
    published = run_validator(tmp_path, "publish")
    assert published.returncode == 0, published.stdout
    old_report = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-design.json").read_text(encoding="utf-8")
    )
    old_hashes = {
        "oldRequirements": input_hash(old_report, "requirementsValidation"),
        "oldAsIs": input_hash(old_report, "asIsValidation"),
    }
    write_bytes(tmp_path, SOURCE_PATH, b"Customer profile source changed without semantic impact.\n")
    publish_requirements(tmp_path)
    publish_asis(tmp_path)
    new_requirements = sha256_bytes((tmp_path / ".ai-sow/validation/analyze-requirement.json").read_bytes())
    new_asis = sha256_bytes((tmp_path / ".ai-sow/validation/analyze-as-is.json").read_bytes())
    design = fixture("design.valid.json")
    technical = fixture("requirements.valid.json")
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-design.md",
        design_review(
            design,
            technical,
            rebind={**old_hashes, "newRequirements": new_requirements, "newAsIs": new_asis},
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-design/design.json").read_bytes() == design_bytes
    assert managed_path(tmp_path, ".ai-sow/data/generate-design/requirements.json").read_bytes() == technical_bytes
    rebound = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-design.json").read_text(encoding="utf-8")
    )
    assert input_hash(rebound, "requirementsValidation") == new_requirements
    assert input_hash(rebound, "asIsValidation") == new_asis


def test_rebind_rejects_changed_stable_output_bytes(tmp_path: Path) -> None:
    prepare(tmp_path)
    published = run_validator(tmp_path, "publish")
    assert published.returncode == 0, published.stdout
    old_report = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-design.json").read_text(encoding="utf-8")
    )
    old_hashes = {
        "oldRequirements": input_hash(old_report, "requirementsValidation"),
        "oldAsIs": input_hash(old_report, "asIsValidation"),
    }
    write_bytes(tmp_path, SOURCE_PATH, b"Changed source.\n")
    publish_requirements(tmp_path)
    publish_asis(tmp_path)
    stable_design = managed_path(tmp_path, ".ai-sow/data/generate-design/design.json")
    stable_design.write_bytes(stable_design.read_bytes() + b" ")
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-design.md",
        design_review(
            fixture("design.valid.json"),
            fixture("requirements.valid.json"),
            rebind={
                **old_hashes,
                "newRequirements": sha256_bytes((tmp_path / ".ai-sow/validation/analyze-requirement.json").read_bytes()),
                "newAsIs": sha256_bytes((tmp_path / ".ai-sow/validation/analyze-as-is.json").read_bytes()),
            },
        ).encode(),
    )

    result = run_validator(tmp_path, "rebind")

    assert result.returncode == 2
    assert "OWNER_REBIND_OUTPUT_CHANGED" in codes(result)


def test_skill_defines_review_candidate_publish_stop_flow() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        "完整 Reviewer Agent",
        "prepare_context.py",
        "render_review.py",
        "--mode review",
        "--mode publish-approved",
        "--mode check",
        "--mode publish",
        "--mode rebind",
        "review-packet.json",
        "approval.json",
        "不继承当前完整聊天",
        "scripts/apply_patch.py",
        "patch-audit.json",
        "轻量 fresh-context Reviewer",
        "不加载完整来源或 round-1 历史",
        "requirements.candidate.json",
        "推荐用户显式调用 `generate-story`",
        "然后停止",
        "affectsEstimate = true",
        "独立服务容量模型或单独支持 SOW",
        "不得仅因实现机制新增 Feature",
        "不得要求下游修改已批准的 Story/AC",
        "第一条项目命令必须是下方公开的 `prepare_context.py`",
        "`rg`、`rg --files`、`find`、`git status`",
        "context/manifest.json",
        "resolvedPath",
        "contracts/design.schema.json",
        "contracts/technical-requirements.schema.json",
        "不得用 `ls`、glob、`rg` 或目录枚举寻找 Schema",
        "不得手写 Design Item、Architecture Delta",
        "`Structure Counts`",
        "featureBoundaryReview",
        "可独立验收的非重叠结果",
        "category: DECISION",
        "correctionOwner: null",
        "requiresUserDecision: true",
    ):
        assert required in contract
    assert "一次整体修复" not in contract
    for forbidden in ("Worker", "Validator", "Orchestrator"):
        assert forbidden not in contract
    assert "当前 Stage 是本 Skill 的唯一用户接口" in contract
    assert "外层 Stage、一个 Reviewer 和一次 hash-bound 用户批准" in contract
    assert "Stage 直接调用本 Owner 的确定性脚本" in contract


def test_patch_wrapper_owns_both_design_candidates() -> None:
    wrapper = (SKILL_ROOT / "scripts/apply_patch.py").read_text(encoding="utf-8")

    assert 'additional_candidates=(f"{WORK_ROOT}/requirements.candidate.json",)' in wrapper


def test_local_review_gate_has_no_runtime_or_cross_skill_import() -> None:
    text = (SKILL_ROOT / "scripts/review_gates.py").read_text(encoding="utf-8")
    assert "runtime.review_gates" not in text
    assert "skills." not in text
    assert "skills/" not in text
