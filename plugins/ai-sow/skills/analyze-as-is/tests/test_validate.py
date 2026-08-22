from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


SKILL_ROOT = Path(__file__).parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "validate.py"
GREENFIELD_FIXTURE = SKILL_ROOT / "fixtures" / "asis.valid.json"
BROWNFIELD_FIXTURE = SKILL_ROOT / "fixtures" / "asis.brownfield.valid.json"
REVISION = "b" * 40
PRIOR_SOW_BYTES = b"Phase one prior SOW fixture.\n"
SHA256 = hashlib.sha256(PRIOR_SOW_BYTES).hexdigest()


def write_json(project_root: Path, relative: str, payload: object) -> None:
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_validator(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def source_requirements() -> dict[str, object]:
    return {"features": [{"featureId": "feature-customer-profile"}]}


def prepare_project(project_root: Path) -> None:
    write_json(
        project_root,
        ".ai-sow/project.json",
        {
            "projectId": "customer-portal",
            "name": "Customer Portal",
            "pluginVersion": "0.1.0-beta.1",
            "sowStandardVersion": "1.3",
        },
    )
    write_json(
        project_root,
        ".ai-sow/data/analyze-requirement/requirements.json",
        source_requirements(),
    )


def prepare_greenfield(project_root: Path) -> dict[str, Any]:
    prepare_project(project_root)
    return json.loads(GREENFIELD_FIXTURE.read_text(encoding="utf-8"))


def prepare_brownfield(project_root: Path) -> dict[str, Any]:
    repository = project_root / "repositories/service-api"
    repository.mkdir(parents=True)
    prior_sow = project_root / ".ai-sow/inputs/analyze-as-is/prior-sows/sow-phase-one.md"
    prior_sow.parent.mkdir(parents=True)
    prior_sow.write_bytes(PRIOR_SOW_BYTES)
    prepare_project(project_root)
    return json.loads(BROWNFIELD_FIXTURE.read_text(encoding="utf-8"))


def validate_payload(project_root: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    write_json(project_root, ".ai-sow/data/analyze-as-is/asis.json", payload)
    return run_validator(project_root)


def diagnostic_codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {entry["code"] for entry in json.loads(result.stdout)["diagnostics"]}


def semantic_diagnostic_codes(
    payload: dict[str, Any],
    project: dict[str, Any],
    source: dict[str, Any],
) -> set[str]:
    spec = importlib.util.spec_from_file_location("analyze_as_is_validate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        entry["code"]
        for entry in module.validate_semantics(payload, project, source)
    }


def test_accepts_topic_complete_greenfield_baseline(tmp_path: Path) -> None:
    result = validate_payload(tmp_path, prepare_greenfield(tmp_path))

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["outcome"] == "OK"


def test_accepts_evidence_backed_brownfield_baseline(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["outcome"] == "OK"
    assert payload["items"][0]["asIsItemId"].startswith("asis-")
    assert payload["commitments"][0]["commitmentId"].startswith("commitment-")
    assert payload["effectiveStartItems"][0]["effectiveStartItemId"].startswith(
        "effective-start-"
    )
    assert payload["uncertainties"][0]["uncertaintyId"].startswith("uncertainty-")
    assert payload["evidence"][0]["evidenceId"].startswith("evidence-")


def test_uncertainty_requires_explicit_estimate_impact_flag(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["uncertainties"][0].pop("affectsEstimate")

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


@pytest.mark.parametrize(
    ("collection", "field", "wrong_id"),
    [
        ("items", "asIsItemId", "item-customer-api"),
        ("commitments", "commitmentId", "commit-loyalty-profile"),
        ("effectiveStartItems", "effectiveStartItemId", "start-customer-api"),
        ("uncertainties", "uncertaintyId", "unc-data-retention"),
        ("evidence", "evidenceId", "proof-customer-api-code"),
    ],
)
def test_rejects_wrong_stable_as_is_entity_prefix(
    tmp_path: Path,
    collection: str,
    field: str,
    wrong_id: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload[collection][0][field] = wrong_id

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


@pytest.mark.parametrize(
    ("collection", "index", "field", "wrong_ids"),
    [
        ("topicAssessments", 4, "uncertaintyIds", ["unc-data-retention"]),
        ("commitments", 0, "affectedItemIds", ["item-customer-api"]),
        ("effectiveStartItems", 0, "sourceItemIds", ["item-customer-api"]),
        ("effectiveStartItems", 0, "commitmentIds", ["commit-loyalty-profile"]),
        ("coverage", 0, "effectiveStartItemIds", ["start-customer-api"]),
        ("coverage", 0, "commitmentIds", ["commit-loyalty-profile"]),
        ("coverage", 0, "uncertaintyIds", ["unc-data-retention"]),
        ("evidence", 0, "supportsIds", ["item-customer-api"]),
    ],
)
def test_rejects_wrong_stable_as_is_reference_prefix(
    tmp_path: Path,
    collection: str,
    index: int,
    field: str,
    wrong_ids: list[str],
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload[collection][index][field] = wrong_ids

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_accepts_project_root_repository_snapshot(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["analysisScope"]["repositorySnapshots"][0]["path"] = "."

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout


def test_validator_is_self_contained_without_setup_skill_tree(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    payload = prepare_greenfield(project_root)
    write_json(project_root, ".ai-sow/data/analyze-as-is/asis.json", payload)
    isolated_skill = tmp_path / "isolated/analyze-as-is"
    shutil.copytree(SKILL_ROOT, isolated_skill)

    result = subprocess.run(
        [
            sys.executable,
            str(isolated_skill / "scripts/validate.py"),
            "--project-root",
            str(project_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_rejects_tampered_analysis_scope_prior_sow(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    (tmp_path / ".ai-sow/inputs/analyze-as-is/prior-sows/sow-phase-one.md").write_bytes(
        b"tampered after setup\n"
    )

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "PRIOR_SOW_HASH_MISMATCH" in diagnostic_codes(result)


def test_rejects_analysis_scope_repository_path_escape(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-repository"
    payload["analysisScope"]["repositorySnapshots"][0]["path"] = f"../{outside.name}"
    outside.mkdir()

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_rejects_analysis_scope_repository_symlink_escape(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    repository = tmp_path / "repositories/service-api"
    repository.rmdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside-repository"
    outside.mkdir()
    repository.symlink_to(outside, target_is_directory=True)

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "REGISTERED_PATH_INVALID" in diagnostic_codes(result)


def test_rejects_duplicate_analysis_scope_snapshot_ids(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["analysisScope"]["repositorySnapshots"].append(
        payload["analysisScope"]["repositorySnapshots"][0].copy()
    )

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "INTAKE_ID_DUPLICATE" in diagnostic_codes(result)


def test_rejects_analysis_scope_prior_sow_hash_mismatch(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["analysisScope"]["priorSowSnapshots"][0]["sha256"] = "0" * 64

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "PRIOR_SOW_HASH_MISMATCH" in diagnostic_codes(result)


def test_rejects_brownfield_scope_without_repository_or_prior_sow(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["analysisScope"]["repositorySnapshots"] = []
    payload["analysisScope"]["priorSowSnapshots"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "BROWNFIELD_INPUT_REQUIRED" in diagnostic_codes(result)


@pytest.mark.parametrize("symlink_kind", ["directory", "report"])
def test_blocks_validation_output_symlink_escape(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    payload = prepare_greenfield(tmp_path)
    write_json(tmp_path, ".ai-sow/data/analyze-as-is/asis.json", payload)
    validation_path = tmp_path / ".ai-sow/validation/analyze-as-is.json"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-validation"
    outside.mkdir()
    if symlink_kind == "directory":
        validation_path.parent.symlink_to(outside, target_is_directory=True)
    else:
        validation_path.parent.mkdir(parents=True)
        validation_path.symlink_to(outside / "escaped.json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert json.loads(result.stdout)["outcome"] == "BLOCKED"
    assert "OUTPUT_PATH_UNSAFE" in diagnostic_codes(result)
    assert list(outside.iterdir()) == []


def test_portable_directory_snapshot_rejects_windows_reparse_point() -> None:
    spec = importlib.util.spec_from_file_location("analyze_as_is_reparse", SCRIPT)
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
    validation_path = tmp_path / ".ai-sow/validation/analyze-as-is.json"
    validation_path.parent.mkdir(parents=True)
    validation_path.write_text("original\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("analyze_as_is_report_reparse", SCRIPT)
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
    payload = prepare_greenfield(tmp_path)
    write_json(tmp_path, ".ai-sow/data/analyze-as-is/asis.json", payload)
    validation_path = tmp_path / ".ai-sow/validation/analyze-as-is.json"
    validation_path.parent.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()
    original_validation_dir = validation_path.parent.with_name("validation-before-race")
    spec = importlib.util.spec_from_file_location("analyze_as_is_race", SCRIPT)
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
    assert "OUTPUT_UNWRITABLE" in {item["code"] for item in payload["diagnostics"]}
    assert list(outside.iterdir()) == []


def test_rejects_missing_topic_assessment(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["topicAssessments"].pop()

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "TOPIC_ASSESSMENTS_INVALID" in diagnostic_codes(result)


def test_rejects_insufficient_topic_without_uncertainty(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["topicAssessments"][4]["status"] = "INSUFFICIENT_EVIDENCE"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "TOPIC_UNCERTAINTY_REQUIRED" in diagnostic_codes(result)


def test_rejects_unknown_prior_sow_commitment(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["priorSowId"] = "sow-unknown"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "PRIOR_SOW_REF_UNKNOWN" in diagnostic_codes(result)


def test_rejects_commitment_status_treatment_mismatch(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["implementationStatus"] = "IMPLEMENTED"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COMMITMENT_TREATMENT_INVALID" in diagnostic_codes(result)


def test_rejects_effective_start_using_carry_forward_commitment(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["effectiveStartItems"][0]["commitmentIds"] = ["commitment-loyalty-profile"]

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "EFFECTIVE_START_COMMITMENT_INELIGIBLE" in diagnostic_codes(result)


def test_rejects_source_less_effective_start_in_schema_and_semantics(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["effectiveStartItems"][0]["sourceItemIds"] = []
    payload["effectiveStartItems"][0]["commitmentIds"] = []
    project = json.loads((tmp_path / ".ai-sow/project.json").read_text())

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)
    assert "EFFECTIVE_START_SOURCE_REQUIRED" in semantic_diagnostic_codes(
        payload,
        project,
        source_requirements(),
    )


def test_rejects_carry_forward_commitment_missing_from_coverage(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["coverage"][0]["commitmentIds"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "CARRY_FORWARD_COVERAGE_MISSING" in diagnostic_codes(result)


def test_rejects_brownfield_item_without_evidence(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["supportsIds"] = ["feature-customer-profile"]

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "BROWNFIELD_ITEM_EVIDENCE_MISSING" in diagnostic_codes(result)


def test_rejects_greenfield_item_without_document_or_questionnaire_evidence(
    tmp_path: Path,
) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["items"] = [
        {
            "asIsItemId": "asis-enterprise-idp",
            "topic": "APPLICATION",
            "itemType": "COMPONENT",
            "name": "Enterprise IdP",
            "summary": "The shared enterprise IdP is a bounded dependency.",
            "repositoryIds": [],
        }
    ]
    payload["effectiveStartItems"] = [
        {
            "effectiveStartItemId": "effective-start-enterprise-idp",
            "topic": "APPLICATION",
            "itemType": "COMPONENT",
            "name": "Enterprise IdP dependency",
            "summary": "The registered shared service is required at Effective Start.",
            "sourceItemIds": ["asis-enterprise-idp"],
            "commitmentIds": [],
        }
    ]
    payload["coverage"][0]["status"] = "PARTIAL"
    payload["coverage"][0]["effectiveStartItemIds"] = [
        "effective-start-enterprise-idp"
    ]
    payload["evidence"] = [
        {
            "evidenceId": "evidence-enterprise-idp-code",
            "kind": "CODE",
            "reference": "requirements:feature-customer-profile",
            "summary": "A code-like record must not establish a Greenfield current Item.",
            "supportsIds": ["asis-enterprise-idp"],
        }
    ]

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "GREENFIELD_ITEM_EVIDENCE_INVALID" in diagnostic_codes(result)


def test_accepts_greenfield_item_with_document_evidence(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["items"] = [
        {
            "asIsItemId": "asis-enterprise-idp",
            "topic": "APPLICATION",
            "itemType": "COMPONENT",
            "name": "Enterprise IdP",
            "summary": "The shared enterprise IdP is a bounded dependency.",
            "repositoryIds": [],
        }
    ]
    payload["effectiveStartItems"] = [
        {
            "effectiveStartItemId": "effective-start-enterprise-idp",
            "topic": "APPLICATION",
            "itemType": "COMPONENT",
            "name": "Enterprise IdP dependency",
            "summary": "The registered shared service is required at Effective Start.",
            "sourceItemIds": ["asis-enterprise-idp"],
            "commitmentIds": [],
        }
    ]
    payload["coverage"][0]["status"] = "PARTIAL"
    payload["coverage"][0]["effectiveStartItemIds"] = [
        "effective-start-enterprise-idp"
    ]
    payload["evidence"] = [
        {
            "evidenceId": "evidence-enterprise-idp-setup",
            "kind": "DOCUMENT",
            "reference": "requirements:feature-customer-profile",
            "summary": "The registered setup document confirms the shared dependency.",
            "supportsIds": ["asis-enterprise-idp"],
        }
    ]

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout


def test_rejects_unknown_evidence_support_id(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["supportsIds"].append("asis-unknown")

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "EVIDENCE_REF_UNKNOWN" in diagnostic_codes(result)


def test_rejects_runtime_evidence_without_outcome(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["kind"] = "RUNTIME"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_accepts_runtime_evidence_with_outcome(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["kind"] = "RUNTIME"
    payload["evidence"][0]["runtimeOutcome"] = "PASSED"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout


def test_rejects_runtime_outcome_on_non_runtime_evidence(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["runtimeOutcome"] = "PASSED"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


@pytest.mark.parametrize(
    ("collection", "index", "field", "reference"),
    [
        ("commitments", 0, "sourceReference", "prior-sow:sow-phase-one#section=customer-profile"),
        ("commitments", 0, "sourceReference", "docs/prior-sow.md#section=customer-profile"),
        ("evidence", 0, "reference", "service-api:src/customer/profile.py#CustomerProfileReader"),
        ("evidence", 0, "reference", "service-api/src/customer/profile.py#CustomerProfileReader"),
    ],
)
def test_accepts_logical_and_repo_relative_stable_references(
    tmp_path: Path,
    collection: str,
    index: int,
    field: str,
    reference: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload[collection][index][field] = reference

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout


def test_accepts_standard_code_line_range_anchor(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["reference"] = "service-api:src/file.py#L12-L20"

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("collection", "index", "field", "reference"),
    [
        ("commitments", 0, "sourceReference", "/tmp/prior-sow.md"),
        ("evidence", 0, "reference", "C:\\repo\\src\\customer.py"),
        ("commitments", 0, "sourceReference", "\\\\server\\share\\prior-sow.md"),
        ("evidence", 0, "reference", "//server/share/customer.py"),
        ("commitments", 0, "sourceReference", "FILE://server/share/prior-sow.md"),
        ("evidence", 0, "reference", "FiLe://server/share/customer.py"),
        (
            "commitments",
            0,
            "sourceReference",
            "prior-sow:sow-phase-one\nfull source payload",
        ),
        (
            "evidence",
            0,
            "reference",
            "service-api:src/customer.py\nclass Customer: pass",
        ),
    ],
)
def test_rejects_absolute_or_multiline_stable_references(
    tmp_path: Path,
    collection: str,
    index: int,
    field: str,
    reference: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload[collection][index][field] = reference

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


@pytest.mark.parametrize(
    "reference",
    [
        "service-api:src/../secret.py#L1",
        "service-api:./src/file.py#L1",
        "service-api/src/../secret.py#L1",
        "./service-api/src/file.py#L1",
        "prior-sow:../phase-one#section=scope",
        "service-api:src/file.py#L12;src/other.py#L2",
    ],
)
def test_rejects_traversal_or_multiple_stable_reference_anchors(
    tmp_path: Path,
    reference: str,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["evidence"][0]["reference"] = reference

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "SCHEMA_INVALID" in diagnostic_codes(result)


def test_rejects_wrong_feature_carry_forward_coverage(tmp_path: Path) -> None:
    payload = prepare_brownfield(tmp_path)
    source = source_requirements()
    source["features"].append({"featureId": "feature-other-scope"})
    write_json(tmp_path, ".ai-sow/data/analyze-requirement/requirements.json", source)
    payload["coverage"][0]["commitmentIds"] = []
    payload["coverage"].append(
        {
            "featureId": "feature-other-scope",
            "status": "MISSING",
            "effectiveStartItemIds": [],
            "commitmentIds": ["commitment-loyalty-profile"],
            "uncertaintyIds": [],
            "rationale": "The unrelated scope must not absorb this commitment.",
        }
    )

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COMMITMENT_COVERAGE_FEATURE_MISMATCH" in diagnostic_codes(result)
    assert "COMMITMENT_COVERAGE_MISSING" in diagnostic_codes(result)


def test_rejects_commitment_related_feature_missing_reverse_coverage(
    tmp_path: Path,
) -> None:
    payload = prepare_brownfield(tmp_path)
    source = source_requirements()
    source["features"].append({"featureId": "feature-other-scope"})
    write_json(tmp_path, ".ai-sow/data/analyze-requirement/requirements.json", source)
    payload["commitments"][0]["relatedFeatureIds"].append("feature-other-scope")
    payload["coverage"].append(
        {
            "featureId": "feature-other-scope",
            "status": "MISSING",
            "effectiveStartItemIds": [],
            "commitmentIds": [],
            "uncertaintyIds": [],
            "rationale": "The reverse commitment link is intentionally missing.",
        }
    )

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COMMITMENT_COVERAGE_MISSING" in diagnostic_codes(result)


def test_rejects_needs_decision_commitment_without_linked_uncertainty_coverage(
    tmp_path: Path,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["implementationStatus"] = "UNVERIFIED"
    payload["commitments"][0]["treatment"] = "NEEDS_DECISION"
    payload["coverage"][0]["uncertaintyIds"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COMMITMENT_DECISION_CHAIN_MISSING" in diagnostic_codes(result)


def test_rejects_carry_forward_commitment_without_related_feature(
    tmp_path: Path,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["relatedFeatureIds"] = []
    payload["coverage"][0]["commitmentIds"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "CARRY_FORWARD_FEATURE_REQUIRED" in diagnostic_codes(result)


def test_rejects_decision_commitment_using_unrelated_uncertainty(
    tmp_path: Path,
) -> None:
    payload = prepare_brownfield(tmp_path)
    payload["commitments"][0]["implementationStatus"] = "UNVERIFIED"
    payload["commitments"][0]["treatment"] = "NEEDS_DECISION"
    payload["uncertainties"][0]["relatedFeatureIds"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COMMITMENT_DECISION_CHAIN_MISSING" in diagnostic_codes(result)


def test_rejects_missing_source_feature_coverage(tmp_path: Path) -> None:
    payload = prepare_greenfield(tmp_path)
    payload["coverage"] = []

    result = validate_payload(tmp_path, payload)

    assert result.returncode == 2
    assert "COVERAGE_MISSING" in diagnostic_codes(result)
