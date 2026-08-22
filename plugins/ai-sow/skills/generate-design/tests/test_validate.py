from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "validate.py"


def write_json(root: Path, relative: str, payload: object) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def diagnostic_codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {
        item["code"]
        for item in json.loads(result.stdout)["diagnostics"]
    }


def write_design_review(
    root: Path,
    *,
    hld_status: str = "PASSED",
    go_live_status: str = "PASSED",
) -> Path:
    rows = [
        (
            "PRODUCTION_SCOPE",
            "IN_SCOPE",
            "feature-profile-api",
            "—",
            "—",
            "本项目负责客户档案 API 的生产范围，客户负责生产审批。",
            "已批准的技术范围要求该 API 达到生产可用。",
        )
    ]
    rows.extend(
        (
            concern,
            "NOT_APPLICABLE",
            "—",
            "—",
            "—",
            "该关注点不进入本项目责任边界。",
            "已确认该关注点与本次客户档案 API 范围无关。",
        )
        for concern in GO_LIVE_CONCERNS[1:]
    )
    table = "\n".join(
        "| " + " | ".join(row) + " |"
        for row in rows
    )
    review = (
        "## 高阶设计覆盖门禁\n\n"
        f"HLD Coverage: {hld_status}\n\n"
        "## 上线范围门禁\n\n"
        "| Concern | Disposition | Feature IDs | Effective Start IDs | "
        "Evidence IDs | 责任边界 | 依据 |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{table}\n\n"
        f"Go-live Assessment: {go_live_status}\n"
    )
    path = root / ".ai-sow/reviews/generate-design.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review, encoding="utf-8")
    return path


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def prepare(root: Path) -> Path:
    source = {
        "sourceDocuments": [
            {
                "sourceDocumentId": "source-document-customer-profile",
                "file": ".ai-sow/inputs/analyze-requirement/customer-profile.md",
                "originalName": "customer-profile.md",
                "sha256": "67b0178e923a4ee85f67ab1553d6a0fc20e619a049ff1706c4af00d37d2dfd9a",
            }
        ],
        "normalizedItems": [],
        "epics": [
            {
                "epicId": "epic-customer-management",
                "type": "BUSINESS",
            }
        ],
        "features": [
            {
                "featureId": "feature-customer-profile",
                "epicId": "epic-customer-management",
            }
        ],
    }
    source_input = root / ".ai-sow/inputs/analyze-requirement/customer-profile.md"
    source_input.parent.mkdir(parents=True)
    source_input.write_bytes(b"Customer profile source document.\n")
    source_path = write_json(root, ".ai-sow/data/analyze-requirement/requirements.json", source)
    write_json(
        root,
        ".ai-sow/data/analyze-as-is/asis.json",
        {
            "topicAssessments": [
                {
                    "topic": "DELIVERY_CONSTRAINTS",
                    "status": "ASSESSED",
                    "summary": "The prior commitment remains delivery scope.",
                    "uncertaintyIds": [],
                }
            ],
            "commitments": [
                {
                    "commitmentId": "commitment-loyalty-profile",
                    "implementationStatus": "NOT_IMPLEMENTED",
                    "treatment": "CARRY_FORWARD",
                    "relatedFeatureIds": ["feature-customer-profile"],
                }
            ],
            "items": [
                {
                    "asIsItemId": "asis-customer-api",
                    "topic": "APPLICATION",
                    "itemType": "COMPONENT",
                    "name": "现有客户接口",
                    "summary": "已部署的客户接口提供当前客户档案读取能力。",
                    "repositoryIds": [],
                }
            ],
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
                    "commitmentIds": ["commitment-loyalty-profile"],
                    "uncertaintyIds": ["uncertainty-profile-hosting"],
                }
            ],
            "uncertainties": [
                {
                    "uncertaintyId": "uncertainty-profile-hosting",
                    "topic": "PLATFORM",
                    "impact": "Hosting choice changes the deployment design.",
                    "affectsEstimate": False,
                    "relatedFeatureIds": ["feature-customer-profile"],
                }
            ],
            "evidence": [
                {
                    "evidenceId": "evidence-customer-api",
                    "kind": "CODE",
                    "reference": "customer-api:src/profile.py#reader",
                    "summary": "代码证明当前客户接口已实现档案读取能力。",
                    "supportsIds": ["asis-customer-api"],
                }
            ],
        },
    )
    write_json(
        root,
        ".ai-sow/data/generate-design/design.json",
        json.loads((SKILL_ROOT / "fixtures/design.valid.json").read_text()),
    )
    write_json(
        root,
        ".ai-sow/data/generate-design/requirements.json",
        json.loads((SKILL_ROOT / "fixtures/requirements.valid.json").read_text()),
    )
    write_design_review(root)
    return source_path


def test_validates_separate_design_outputs_without_modifying_source(tmp_path: Path) -> None:
    source_path = prepare(tmp_path)
    source_before = source_path.read_bytes()

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["outcome"] == "OK"
    assert source_path.read_bytes() == source_before


def test_rejects_unknown_design_decision_in_derived_requirements(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["source"]["designDecisionIds"] = ["decision-not-found"]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DESIGN_DECISION_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_accepts_source_input_and_design_derived_technical_provenance(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_accepts_fully_covered_business_feature_without_design_item(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    asis_path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["commitments"] = []
    asis["coverage"][0].update(
        {
            "status": "COMPLETE",
            "commitmentIds": [],
            "uncertaintyIds": [],
        }
    )
    asis["uncertainties"] = []
    asis_path.write_text(json.dumps(asis))
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    design["scopeDecisions"][0].update(
        {
            "decision": "FULLY_COVERED",
            "rationale": (
                "现有客户接口已经完整满足客户档案读取目标，且没有剩余交付工作。"
            ),
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-customer-api"],
        }
    )
    design_path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_in_scope_feature_without_design_item(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(path.read_text())
    design["scopeDecisions"][0]["designItemIds"] = []
    path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_rejects_review_without_hld_passed_declaration(tmp_path: Path) -> None:
    prepare(tmp_path)
    write_design_review(tmp_path, hld_status="BLOCKED")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "HLD_GATE_NOT_PASSED" in diagnostic_codes(result)


def test_rejects_review_without_go_live_passed_declaration(tmp_path: Path) -> None:
    prepare(tmp_path)
    write_design_review(tmp_path, go_live_status="BLOCKED")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_GATE_NOT_PASSED" in diagnostic_codes(result)


def test_ignores_markdown_tables_after_go_live_gate_section(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text()
        + "\n## 其他评审\n\n| 项目 | 结论 |\n|---|---|\n| 命名 | 通过 |\n"
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_hld_status_declared_outside_hld_section(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review = review_path.read_text()
    review_path.write_text(
        review.replace("HLD Coverage: PASSED\n\n", "")
        + "\n## 其他评审\n\nHLD Coverage: PASSED\n"
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "HLD_GATE_STATUS_MISSING" in diagnostic_codes(result)


def test_rejects_duplicate_go_live_status_in_gate_section(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "Go-live Assessment: PASSED\n",
            "Go-live Assessment: PASSED\nGo-live Assessment: PASSED\n",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_GATE_STATUS_DUPLICATE" in diagnostic_codes(result)


def test_rejects_missing_go_live_concern(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        "\n".join(
            line
            for line in review_path.read_text().splitlines()
            if "| OBSERVABILITY |" not in line
        )
        + "\n"
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_CONCERN_MISSING" in diagnostic_codes(result)


def test_rejects_production_scope_without_technical_feature(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api |",
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-customer-profile |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "PRODUCTION_SCOPE_FEATURE_MISSING" in diagnostic_codes(result)


def test_accepts_fully_covered_technical_feature_without_business_coverage(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    technical_scope = next(
        scope
        for scope in design["scopeDecisions"]
        if scope["featureId"] == "feature-profile-api"
    )
    technical_scope.update(
        {
            "decision": "FULLY_COVERED",
            "rationale": "现有客户接口已经提供目标 API 所需的完整操作边界和稳定运行能力。",
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-customer-api"],
        }
    )
    design_path.write_text(json.dumps(design))
    asis_path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["evidence"][0]["supportsIds"].append("effective-start-customer-api")
    asis_path.write_text(json.dumps(asis))
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | — | — |",
            "| PRODUCTION_SCOPE | FULLY_COVERED | feature-profile-api | "
            "effective-start-customer-api | evidence-customer-api |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_go_live_fully_covered_start_mismatching_scope(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    technical_scope = next(
        scope
        for scope in design["scopeDecisions"]
        if scope["featureId"] == "feature-profile-api"
    )
    technical_scope.update(
        {
            "decision": "FULLY_COVERED",
            "rationale": "现有客户接口已经提供目标 API 所需的完整操作边界和稳定运行能力。",
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-customer-api"],
        }
    )
    design_path.write_text(json.dumps(design))
    asis_path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["effectiveStartItems"].append(
        {
            "effectiveStartItemId": "effective-start-unrelated",
            "sourceItemIds": ["asis-customer-api"],
            "commitmentIds": [],
        }
    )
    asis["evidence"][0]["supportsIds"].append("effective-start-unrelated")
    asis_path.write_text(json.dumps(asis))
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | — | — |",
            "| PRODUCTION_SCOPE | FULLY_COVERED | feature-profile-api | "
            "effective-start-unrelated | evidence-customer-api |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_SCOPE_START_MISMATCH" in diagnostic_codes(result)


def test_accepts_multi_feature_fully_covered_row_with_union_of_scope_starts(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    requirements_path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements["features"].append(
        {
            "featureId": "feature-production-secondary",
            "epicId": "epic-platform",
            "name": "第二生产边界",
            "description": "表达第二个已经由现状完整覆盖的生产技术边界。",
            "source": {
                "type": "SOURCE_INPUT",
                "sourceDocumentIds": ["source-document-customer-profile"],
                "sourceReferences": ["section:technical-platform"],
            },
        }
    )
    requirements_path.write_text(json.dumps(requirements))
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    technical_scope = next(
        scope
        for scope in design["scopeDecisions"]
        if scope["featureId"] == "feature-profile-api"
    )
    technical_scope.update(
        {
            "decision": "FULLY_COVERED",
            "rationale": "现有客户接口已经完整满足第一项生产技术边界且无需新增交付。",
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-customer-api"],
        }
    )
    design["scopeDecisions"].append(
        {
            "featureId": "feature-production-secondary",
            "decision": "FULLY_COVERED",
            "rationale": "现有第二生产组件已经完整满足该技术边界且无需新增交付。",
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-production-secondary"],
        }
    )
    design_path.write_text(json.dumps(design))
    asis_path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["effectiveStartItems"].append(
        {
            "effectiveStartItemId": "effective-start-production-secondary",
            "sourceItemIds": ["asis-customer-api"],
            "commitmentIds": [],
        }
    )
    asis["evidence"].append(
        {
            "evidenceId": "evidence-production-secondary",
            "kind": "DOCUMENT",
            "reference": "customer-api:docs/production.md#secondary",
            "summary": "生产说明证明第二项技术边界已经完整存在。",
            "supportsIds": ["effective-start-production-secondary"],
        }
    )
    asis["evidence"][0]["supportsIds"].append("effective-start-customer-api")
    asis_path.write_text(json.dumps(asis))
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | — | — |",
            "| PRODUCTION_SCOPE | FULLY_COVERED | feature-profile-api, "
            "feature-production-secondary | effective-start-customer-api, "
            "effective-start-production-secondary | evidence-customer-api, "
            "evidence-production-secondary |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_skill_routes_purchased_support_capacity_outside_task_model() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text()

    for required_rule in (
        "affectsEstimate = true",
        "独立服务容量模型或单独支持 SOW",
        "保持 `BLOCKED`",
    ):
        assert required_rule in contract


def test_rejects_data_migration_feature_reused_as_production_scope(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    review_path = tmp_path / ".ai-sow/reviews/generate-design.md"
    review_path.write_text(
        review_path.read_text().replace(
            "| DATA_MIGRATION | NOT_APPLICABLE | — | — | — |",
            "| DATA_MIGRATION | IN_SCOPE | feature-profile-api | — | — |",
        )
    )

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DATA_MIGRATION_FEATURE_NOT_INDEPENDENT" in diagnostic_codes(result)


def test_rejects_design_decision_without_feature_or_design_item(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(path.read_text())
    design["decisions"][0]["designItemIds"] = []
    design["decisions"][0]["relatedFeatureIds"] = []
    path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_rejects_orphan_design_item(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(path.read_text())
    design["designItems"].append(
        {
            "designItemId": "design-orphan-quality",
            "type": "QUALITY",
            "name": "孤立质量设计",
            "summary": "没有任何范围、决策或架构变化引用。",
        }
    )
    path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DESIGN_ITEM_ORPHANED" in diagnostic_codes(result)


def test_rejects_non_new_architecture_delta_without_effective_start(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(path.read_text())
    design["architectureDeltas"][0]["effectiveStartItemIds"] = []
    path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_rejects_fully_covered_scope_without_supporting_evidence(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    asis_path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    asis = json.loads(asis_path.read_text())
    asis["commitments"] = []
    asis["coverage"][0].update(
        {"status": "COMPLETE", "commitmentIds": [], "uncertaintyIds": []}
    )
    asis["uncertainties"] = []
    asis["evidence"] = []
    asis_path.write_text(json.dumps(asis))
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    design["scopeDecisions"][0].update(
        {
            "decision": "FULLY_COVERED",
            "rationale": "现有客户接口已经完整满足全部目标要求。",
            "designItemIds": [],
            "effectiveStartItemIds": ["effective-start-customer-api"],
        }
    )
    design_path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "FULLY_COVERED_EVIDENCE_MISSING" in diagnostic_codes(result)


def test_rejects_unregistered_source_document_in_technical_provenance(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["epics"][0]["source"]["sourceDocumentIds"] = [
        "source-document-unknown"
    ]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SOURCE_DOCUMENT_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_business_epic_in_technical_requirements(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["epics"][0]["type"] = "BUSINESS"
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SCHEMA_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_non_business_source_epic(tmp_path: Path) -> None:
    source_path = prepare(tmp_path)
    payload = json.loads(source_path.read_text())
    payload["epics"][0]["type"] = "TECHNICAL"
    source_path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SOURCE_REQUIREMENT_TYPE_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_unknown_technical_epic_reference(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["epicId"] = "epic-unknown"
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "EPIC_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_duplicate_technical_epic_id(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["epics"].append(json.loads(json.dumps(payload["epics"][0])))
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "ID_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_duplicate_technical_feature_id(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    duplicate = json.loads(json.dumps(payload["features"][0]))
    duplicate["source"] = {
        "type": "SOURCE_INPUT",
        "sourceDocumentIds": ["source-document-customer-profile"],
        "sourceReferences": ["section:technical-platform"],
    }
    payload["features"].append(duplicate)
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "ID_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_duplicate_design_derived_feature_rationale(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    duplicate = json.loads(json.dumps(payload["features"][0]))
    duplicate["featureId"] = "feature-profile-api-read"
    duplicate["source"]["rationale"] = duplicate["source"]["rationale"].replace(
        "decision-profile-api 使用",
        "decision-profile-api   使用",
    )
    payload["features"].append(duplicate)
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    design["scopeDecisions"].append(
        {
            "featureId": "feature-profile-api-read",
            "decision": "IN_SCOPE",
            "rationale": "The duplicate derivation must be rejected.",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
        }
    )
    path.write_text(json.dumps(payload))
    design_path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DERIVED_RATIONALE_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize(
    "rationale",
    [
        (
            "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
            "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
            "无法通过统一边界创建或检索客户档案"
        ),
        (
            "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
            "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
            "无法通过统一边界创建或检索客户档案"
        ),
        (
            "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
            "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界"
        ),
    ],
)
def test_rejects_derived_rationale_missing_required_clause(
    tmp_path: Path,
    rationale: str,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["source"]["rationale"] = rationale
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SCHEMA_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_derived_rationale_without_referenced_decision_id(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["source"]["rationale"] = (
        "设计决策/Decision: 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "无法通过统一边界创建或检索客户档案"
    )
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DERIVED_RATIONALE_DECISION_REF_MISSING"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_derived_rationale_with_only_longer_decision_id_prefix(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["source"]["rationale"] = (
        "设计决策/Decision: decision-profile-api-v2 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "无法通过统一边界创建或检索客户档案"
    )
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DERIVED_RATIONALE_DECISION_REF_MISSING"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_generic_non_delivery_impact(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    payload["features"][0]["source"]["rationale"] = (
        "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | 系统 -> 会受到影响"
    )
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DERIVED_RATIONALE_IMPACT_GENERIC"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_derived_rationales_that_only_substitute_entity_names(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    payload = json.loads(path.read_text())
    duplicate = json.loads(json.dumps(payload["features"][0]))
    duplicate["featureId"] = "feature-order-api"
    duplicate["name"] = "订单操作 API"
    duplicate["description"] = "通过稳定的 API 创建和检索订单。"
    duplicate["source"]["rationale"] = (
        "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 订单操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | Order Portal -> "
        "无法通过统一边界创建或检索记录"
    )
    payload["features"][0]["source"]["rationale"] = (
        "设计决策/Decision: decision-profile-api 使用专用 API 边界处理客户档案操作；"
        "产生原因/Cause: 客户档案操作 API 需要为 UI 与未来渠道提供统一操作边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "无法通过统一边界创建或检索记录"
    )
    payload["features"].append(duplicate)
    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    design["scopeDecisions"].append(
        {
            "featureId": "feature-order-api",
            "decision": "IN_SCOPE",
            "rationale": "The order interface is independently in scope.",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
        }
    )
    path.write_text(json.dumps(payload))
    design_path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "DERIVED_RATIONALE_TEMPLATE_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_derived_rationale_template_when_all_entities_are_substituted(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    requirements_path = tmp_path / ".ai-sow/data/generate-design/requirements.json"
    requirements = json.loads(requirements_path.read_text())
    requirements["features"][0]["source"]["rationale"] = (
        "设计决策/Decision: decision-profile-api 公开客户档案 API 要求 "
        "feature-profile-api 客户档案操作 API 使用统一边界；"
        "产生原因/Cause: decision-profile-api 公开客户档案 API 要求 "
        "feature-profile-api 客户档案操作 API 形成统一交付边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "decision-profile-api 公开客户档案 API 将无法承载 "
        "feature-profile-api 客户档案操作 API"
    )
    order_feature = json.loads(json.dumps(requirements["features"][0]))
    order_feature["featureId"] = "feature-order-api"
    order_feature["name"] = "订单操作 API"
    order_feature["description"] = "通过稳定的 API 创建和检索订单。"
    order_feature["source"]["designDecisionIds"] = ["decision-order-api"]
    order_feature["source"]["rationale"] = (
        "设计决策/Decision: decision-order-api 公开订单 API 要求 "
        "feature-order-api 订单操作 API 使用统一边界；"
        "产生原因/Cause: decision-order-api 公开订单 API 要求 "
        "feature-order-api 订单操作 API 形成统一交付边界；"
        "不交付影响/Non-delivery impact: 接口/API | Order Portal -> "
        "decision-order-api 公开订单 API 将无法承载 feature-order-api 订单操作 API"
    )
    requirements["features"].append(order_feature)

    design_path = tmp_path / ".ai-sow/data/generate-design/design.json"
    design = json.loads(design_path.read_text())
    order_decision = json.loads(json.dumps(design["decisions"][0]))
    order_decision["designDecisionId"] = "decision-order-api"
    order_decision["title"] = "公开订单 API"
    order_decision["decision"] = "使用专用 API 边界处理订单操作。"
    order_decision["rationale"] = "UI 和未来渠道需要统一订单边界。"
    design["decisions"].append(order_decision)
    design["scopeDecisions"].append(
        {
            "featureId": "feature-order-api",
            "decision": "IN_SCOPE",
            "rationale": "The order interface is independently in scope.",
            "designItemIds": ["design-customer-profile"],
            "effectiveStartItemIds": [],
        }
    )
    requirements_path.write_text(json.dumps(requirements))
    design_path.write_text(json.dumps(design))

    result = run_validator(tmp_path)

    assert result.returncode == 2, result.stdout
    assert any(
        item["code"] == "DERIVED_RATIONALE_TEMPLATE_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rationale_signature_preserves_meaningful_non_entity_ids() -> None:
    spec = importlib.util.spec_from_file_location("generate_design_signature", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    feature = {
        "featureId": "feature-profile-api",
        "name": "客户档案操作 API",
        "source": {"designDecisionIds": ["decision-profile-api"]},
    }
    profile_sync = module.DERIVED_RATIONALE_PATTERN.fullmatch(
        "设计决策/Decision: decision-profile-api 公开客户档案 API 使用统一边界；"
        "产生原因/Cause: integration-profile-sync 要求统一同步交付边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "integration-profile-sync 将无法同步客户档案"
    )
    order_events = module.DERIVED_RATIONALE_PATTERN.fullmatch(
        "设计决策/Decision: decision-profile-api 公开客户档案 API 使用统一边界；"
        "产生原因/Cause: integration-order-events 要求统一同步交付边界；"
        "不交付影响/Non-delivery impact: 接口/API | Customer Portal -> "
        "integration-order-events 将无法同步客户档案"
    )
    assert profile_sync is not None
    assert order_events is not None

    profile_signature = module.rationale_template_signature(
        feature,
        profile_sync,
        {"decision-profile-api": "公开客户档案 API"},
    )
    order_signature = module.rationale_template_signature(
        feature,
        order_events,
        {"decision-profile-api": "公开客户档案 API"},
    )

    assert profile_signature != order_signature


def test_rejects_old_subfeature_design_references(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    payload = json.loads(path.read_text())
    payload["decisions"][0]["relatedSubFeatureIds"] = payload["decisions"][0].pop(
        "relatedFeatureIds"
    )
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SCHEMA_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_fully_covered_scope_with_carry_forward_commitment(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    payload = json.loads(path.read_text())
    payload["scopeDecisions"][0]["decision"] = "FULLY_COVERED"
    payload["scopeDecisions"][0]["effectiveStartItemIds"] = [
        "effective-start-customer-api"
    ]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "CARRY_FORWARD_SCOPE_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_commitment_id_as_architecture_delta_baseline(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    payload = json.loads(path.read_text())
    payload["architectureDeltas"][0]["effectiveStartItemIds"] = [
        "commitment-loyalty-profile"
    ]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "EFFECTIVE_START_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize("symlink_kind", ["directory", "report"])
def test_blocks_validation_output_symlink_escape(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    prepare(tmp_path)
    validation_path = tmp_path / ".ai-sow/validation/generate-design.json"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-validation"
    outside.mkdir()
    if symlink_kind == "directory":
        validation_path.parent.symlink_to(outside, target_is_directory=True)
    else:
        validation_path.parent.mkdir(parents=True)
        validation_path.symlink_to(outside / "escaped.json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "BLOCKED"
    assert any(item["code"] == "OUTPUT_PATH_UNSAFE" for item in payload["diagnostics"])
    assert list(outside.iterdir()) == []


def test_portable_directory_snapshot_rejects_windows_reparse_point() -> None:
    spec = importlib.util.spec_from_file_location("generate_design_reparse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o755,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    path = SimpleNamespace(stat=lambda *, follow_symlinks: snapshot)

    with pytest.raises(OSError, match="reparse point"):
        module._safe_directory_snapshot(path)


def test_portable_report_write_rejects_windows_reparse_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_path = tmp_path / ".ai-sow/validation/generate-design.json"
    validation_path.parent.mkdir(parents=True)
    validation_path.write_text("original\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("generate_design_report_reparse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_stat = Path.stat

    def stat_with_reparse(path: Path, *, follow_symlinks: bool = True) -> object:
        snapshot = original_stat(path, follow_symlinks=follow_symlinks)
        if path == validation_path and not follow_symlinks:
            return SimpleNamespace(
                st_mode=snapshot.st_mode,
                st_dev=snapshot.st_dev,
                st_ino=snapshot.st_ino,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return snapshot

    monkeypatch.setattr(Path, "stat", stat_with_reparse)

    with pytest.raises(OSError, match="reparse point"):
        module._write_validation_report_portable(
            tmp_path,
            validation_path,
            "replacement\n",
        )
    assert validation_path.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("race_kind", ["directory", "report"])
@pytest.mark.parametrize("writer_backend", ["native", "portable"])
def test_blocks_validation_symlink_swap_after_safety_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    race_kind: str,
    writer_backend: str,
) -> None:
    prepare(tmp_path)
    validation_path = tmp_path / ".ai-sow/validation/generate-design.json"
    validation_path.parent.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()
    original_validation_dir = validation_path.parent.with_name("validation-before-race")
    spec = importlib.util.spec_from_file_location("generate_design_race", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if writer_backend == "portable":
        monkeypatch.setattr(
            module,
            "write_validation_report",
            module._write_validation_report_portable,
        )
    original_check = module.validation_output_diagnostic

    def check_then_swap(project_root: Path, report_path: Path) -> dict[str, str] | None:
        result = original_check(project_root, report_path)
        assert result is None
        if race_kind == "directory":
            validation_path.parent.rename(original_validation_dir)
            validation_path.parent.symlink_to(outside, target_is_directory=True)
        else:
            validation_path.symlink_to(outside / "escaped.json")
        return result

    monkeypatch.setattr(module, "validation_output_diagnostic", check_then_swap)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--project-root", str(tmp_path)],
    )

    returncode = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert returncode == 2
    assert payload["outcome"] == "BLOCKED"
    assert any(item["code"] == "OUTPUT_UNWRITABLE" for item in payload["diagnostics"])
    assert list(outside.iterdir()) == []
