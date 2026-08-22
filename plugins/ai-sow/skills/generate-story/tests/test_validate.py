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
FIXTURE = SKILL_ROOT / "fixtures/delivery.valid.json"


def write_json(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_design_review(root: Path, *, go_live_status: str = "PASSED") -> None:
    concerns = (
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
    rows = [
        "| PRODUCTION_SCOPE | IN_SCOPE | feature-profile-api | — | — | "
        "本项目负责生产范围，客户负责生产审批。 | 已批准技术范围要求生产可用。 |"
    ]
    rows.extend(
        f"| {concern} | NOT_APPLICABLE | — | — | — | "
        "该关注点不进入本项目责任边界。 | 已确认与当前范围无关。 |"
        for concern in concerns[1:]
    )
    review = (
        "## 高阶设计覆盖门禁\n\nHLD Coverage: PASSED\n\n"
        "## 上线范围门禁\n\n"
        "| Concern | Disposition | Feature IDs | Effective Start IDs | "
        "Evidence IDs | 责任边界 | 依据 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\nGo-live Assessment: {go_live_status}\n"
    )
    path = root / ".ai-sow/reviews/generate-design.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review, encoding="utf-8")


def diagnostic_codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {
        item["code"]
        for item in json.loads(result.stdout)["diagnostics"]
    }


def prepare(root: Path) -> None:
    write_json(root, ".ai-sow/data/analyze-requirement/requirements.json", {"features": [{"featureId": "feature-customer-profile"}]})
    write_json(root, ".ai-sow/data/analyze-as-is/asis.json", {
        "items": [
            {"asIsItemId": "asis-customer-api"},
        ],
        "topicAssessments": [
            {
                "topic": "INTEGRATION",
                "status": "ASSESSED",
                "summary": "Customer Portal calls the internally owned Customer API.",
                "uncertaintyIds": [],
            },
            {
                "topic": "PLATFORM",
                "status": "INSUFFICIENT_EVIDENCE",
                "summary": "The hosting boundary is not confirmed.",
                "uncertaintyIds": ["uncertainty-profile-hosting"],
            },
        ],
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
                "impact": "Hosting changes deployment design and ownership.",
                "relatedFeatureIds": ["feature-customer-profile"],
            }
        ],
        "evidence": [
            {
                "evidenceId": "evidence-profile-integration",
                "reference": "service-api:docs/integration.md#profile",
                "supportsIds": ["effective-start-customer-api"],
            }
        ],
    })
    write_json(root, ".ai-sow/data/generate-design/requirements.json", {"features": [{"featureId": "feature-profile-api"}]})
    write_json(root, ".ai-sow/data/generate-design/design.json", {
        "designItems": [
            {
                "designItemId": "design-customer-profile",
                "type": "COMPONENT",
                "name": "客户档案组件",
                "summary": "负责客户档案交付。",
            }
        ],
        "architectureDeltas": [],
        "decisions": [],
        "scopeDecisions": [
            {
                "featureId": "feature-customer-profile",
                "decision": "IN_SCOPE",
                "rationale": "客户档案仍需交付。",
                "designItemIds": ["design-customer-profile"],
                "effectiveStartItemIds": [],
            },
            {
                "featureId": "feature-profile-api",
                "decision": "IN_SCOPE",
                "rationale": "客户档案 API 仍需交付。",
                "designItemIds": ["design-customer-profile"],
                "effectiveStartItemIds": [],
            },
        ],
    })
    write_json(root, ".ai-sow/data/generate-story/delivery.json", json.loads(FIXTURE.read_text()))
    write_design_review(root)


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_accepts_feature_gap_story_and_ac_coverage(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["outcome"] == "OK"


def test_skill_contract_covers_go_live_story_decomposition() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text()

    for required_rule in (
        "上线准备",
        "发布切换",
        "生产验证与运维移交",
        "旧功能下线条件适用时单独生成 Story",
        "数据迁移 TECHNICAL Feature 单独生成 Gap 和迁移 Story",
        "POST_GO_LIVE_SUPPORT",
        "uatRelevant = false",
        "不生成开放式缺陷 Story",
        "affectsEstimate = true",
        "独立服务容量模型或单独支持 SOW",
        "返回 `generate-design`",
        "Concern -> Feature -> Gap -> Story/Assumption/Risk",
        "自由文本无法可靠证明时保持 fail closed",
    ):
        assert required_rule in contract


def test_committed_example_keeps_out_of_scope_production_out_of_delivery() -> None:
    project = SKILL_ROOT.parent / "generate-sow/fixtures/project/.ai-sow"
    design = json.loads(
        (project / "data/generate-design/design.json").read_text()
    )
    delivery = json.loads(
        (project / "data/generate-story/delivery.json").read_text()
    )

    production_scope = next(
        scope
        for scope in design["scopeDecisions"]
        if scope["featureId"] == "feature-production-scope"
    )
    assert production_scope["decision"] == "OUT_OF_SCOPE"
    assert "feature-production-scope" not in {
        gap["featureId"] for gap in delivery["gaps"]
    }


def test_rejects_delivery_when_go_live_gate_is_not_passed(tmp_path: Path) -> None:
    prepare(tmp_path)
    write_design_review(tmp_path, go_live_status="BLOCKED")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "GO_LIVE_GATE_NOT_PASSED" in diagnostic_codes(result)


def test_rejects_unknown_design_item_reference_in_shared_gate(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-design/design.json"
    payload = json.loads(path.read_text())
    payload["scopeDecisions"][0]["designItemIds"] = ["design-item-missing"]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "DESIGN_ITEM_REF_UNKNOWN" in diagnostic_codes(result)


def test_rejects_missing_gap_for_in_scope_feature(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["gaps"] = payload["gaps"][:1]
    payload["stories"] = payload["stories"][:1]
    payload["acceptanceCriteria"] = payload["acceptanceCriteria"][:1]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "GAP_COVERAGE_MISSING"
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize(
    ("collection", "field", "invalid_id"),
    [
        ("gaps", "gapId", "wrong-gap"),
        ("stories", "storyId", "wrong-story"),
        ("acceptanceCriteria", "acceptanceCriterionId", "wrong-ac"),
        ("integrations", "integrationId", "wrong-integration"),
        ("assumptions", "assumptionId", "wrong-assumption"),
    ],
)
def test_schema_enforces_delivery_entity_id_prefixes(
    tmp_path: Path,
    collection: str,
    field: str,
    invalid_id: str,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload[collection][0][field] = invalid_id
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SCHEMA_INVALID" and invalid_id in item["message"]
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_non_contiguous_acceptance_criterion_sequences(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["acceptanceCriteria"][0]["sequence"] = 2
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "AC_SEQUENCE_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_allows_story_without_integration(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["integrations"] = []
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_integration_with_unknown_story(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["integrations"][0]["storyId"] = "story-missing"
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "INTEGRATION_STORY_REF_UNKNOWN"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_allows_integration_for_any_story(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["integrations"][0]["storyId"] = "story-customer-profile"
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_rejects_removed_story_type(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["stories"][0]["type"] = "FUNC"
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "SCHEMA_INVALID"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_allows_one_assumption_entity_to_relate_to_multiple_stories(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/generate-story/delivery.json"
    payload = json.loads(path.read_text())
    payload["assumptionStories"].append({
        "assumptionId": "assumption-profile-hosting",
        "storyId": "story-customer-profile",
    })
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_requires_as_is_input_for_delivery_gap_validation(tmp_path: Path) -> None:
    prepare(tmp_path)
    (tmp_path / ".ai-sow/data/analyze-as-is/asis.json").unlink()

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "INPUT_UNREADABLE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_empty_as_is_object(tmp_path: Path) -> None:
    prepare(tmp_path)
    write_json(tmp_path, ".ai-sow/data/analyze-as-is/asis.json", {})

    result = run_validator(tmp_path)

    assert result.returncode == 2
    diagnostics = json.loads(result.stdout)["diagnostics"]
    assert any(
        item["code"] == "SHAPE_INVALID" and "items must be an array" in item["message"]
        for item in diagnostics
    )


def test_rejects_non_array_as_is_collection(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    payload = json.loads(path.read_text())
    payload["commitments"] = {}
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert {
        "code": "SHAPE_INVALID",
        "message": "commitments must be an array",
    } in json.loads(result.stdout)["diagnostics"]


def test_rejects_duplicate_source_feature_coverage(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    payload = json.loads(path.read_text())
    payload["coverage"].append(dict(payload["coverage"][0]))
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "COVERAGE_DUPLICATE"
        for item in json.loads(result.stdout)["diagnostics"]
    )


def test_rejects_missing_source_feature_coverage(tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    payload = json.loads(path.read_text())
    payload["coverage"] = []
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == "COVERAGE_MISSING"
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize(
    ("field", "reference", "expected_code"),
    [
        ("effectiveStartItemIds", "effective-start-unknown", "EFFECTIVE_START_REF_UNKNOWN"),
        ("commitmentIds", "commitment-unknown", "COMMITMENT_REF_UNKNOWN"),
        ("uncertaintyIds", "uncertainty-unknown", "UNCERTAINTY_REF_UNKNOWN"),
    ],
)
def test_rejects_unknown_as_is_coverage_reference(
    tmp_path: Path,
    field: str,
    reference: str,
    expected_code: str,
) -> None:
    prepare(tmp_path)
    path = tmp_path / ".ai-sow/data/analyze-as-is/asis.json"
    payload = json.loads(path.read_text())
    payload["coverage"][0][field] = [reference]
    path.write_text(json.dumps(payload))

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert any(
        item["code"] == expected_code
        for item in json.loads(result.stdout)["diagnostics"]
    )


@pytest.mark.parametrize("symlink_kind", ["directory", "report"])
def test_blocks_validation_output_symlink_escape(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    prepare(tmp_path)
    validation_path = tmp_path / ".ai-sow/validation/generate-story.json"
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
    spec = importlib.util.spec_from_file_location("generate_story_reparse", SCRIPT)
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
    validation_path = tmp_path / ".ai-sow/validation/generate-story.json"
    validation_path.parent.mkdir(parents=True)
    validation_path.write_text("original\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("generate_story_report_reparse", SCRIPT)
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
    validation_path = tmp_path / ".ai-sow/validation/generate-story.json"
    validation_path.parent.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()
    original_validation_dir = validation_path.parent.with_name("validation-before-race")
    spec = importlib.util.spec_from_file_location("generate_story_race", SCRIPT)
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
