from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import generation_store  # noqa: E402
from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from generation_store import (  # noqa: E402
    allocate_next_ids,
    cleanup_interrupted_publication,
    load_current,
    publish_success,
)
from models import WorkbookAudit, workbook_audit_value  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


def write_json(path: Path, value: object) -> bytes:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def workbook_verification() -> dict[str, object]:
    return {
        "trustState": "VERIFIED",
        "engine": {"name": "LibreOffice", "version": "LibreOffice test"},
        "storyCount": 1,
        "taskCount": 1,
        "directDays": 1.0,
        "sitDays": 0.0,
        "uatDays": 0.0,
        "totalDays": 1.0,
        "parameterStatuses": [
            {"code": "K_UAT", "status": "待样本校准"}
        ],
        "formulaErrors": [],
    }


def test_workbook_audit_has_one_canonical_manifest_projection() -> None:
    audit = WorkbookAudit(
        trust_state="VERIFIED",
        story_count=1,
        task_count=2,
        direct_days=3.5,
        sit_days=1.0,
        uat_days=0.5,
        total_days=5.0,
        parameter_statuses=(("K_UAT", "待样本校准"),),
        formula_errors=(),
        engine_name="LibreOffice",
        engine_version="LibreOffice test",
    )

    assert workbook_audit_value(audit, require_verified=True) == {
        "trustState": "VERIFIED",
        "engine": {"name": "LibreOffice", "version": "LibreOffice test"},
        "storyCount": 1,
        "taskCount": 2,
        "directDays": 3.5,
        "sitDays": 1.0,
        "uatDays": 0.5,
        "totalDays": 5.0,
        "parameterStatuses": [{"code": "K_UAT", "status": "待样本校准"}],
        "formulaErrors": [],
    }


def test_generation_manifest_does_not_declare_work_review_material_path() -> None:
    schema = json.loads(
        (SKILL_ROOT / "contracts/generation-manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert "reviewMaterialPath" not in schema["properties"]


def stage_input(root: Path, revision_id: str) -> Path:
    pending = root / f"pending-{revision_id}"
    anchors = []
    anchors_bytes = write_json(pending / "anchors.json", anchors)
    write_json(pending / "answers.json", [])
    sources = []
    for role, source_id, name in (
        ("PRD", "prd-main", "prd.md"),
        ("HLD", "hld-main", "hld.md"),
    ):
        payload = f"# {role}\n\nSynthetic scope.\n".encode()
        relative = f"sources/{role.lower()}/{source_id}/{name}"
        target = pending / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        sources.append(
            {
                "sourceId": source_id,
                "role": role,
                "version": "1.0",
                "originalName": name,
                "mediaType": "text/markdown",
                "path": relative,
                "sha256": sha256_bytes(payload),
                "semanticSha256": "1" * 64,
                "anchorCount": 1,
            }
        )
    write_json(
        pending / "manifest.json",
        {
            "contract": "ai-sow-input-manifest-v1",
            "revisionId": revision_id,
            "project": {
                "projectId": "project-store-test",
                "name": "存储测试",
                "plannedEffectiveDate": "2026-10-01",
            },
            "mode": "GREENFIELD",
            "responsibilityBoundaries": [
                {
                    "responsibilityBoundaryId": "responsibility-vendor",
                    "party": "VENDOR",
                    "name": "供应商",
                    "responsibilities": ["交付"],
                }
            ],
            "sources": sources,
            "questions": [],
            "questionnaireAnswers": [],
            "anchorsPath": "anchors.json",
            "anchorsSha256": sha256_bytes(anchors_bytes),
            "recordedAt": "2026-09-02T00:00:00Z",
        },
    )
    return pending


def stage_generation(
    root: Path,
    generation_id: str,
    revision_id: str,
    input_manifest_bytes: bytes,
) -> Path:
    staged = root / f"generation-{generation_id}"
    scope = canonical_json_bytes({"scope": generation_id})
    delivery = canonical_json_bytes({"delivery": generation_id})
    workbook = b"synthetic-xlsx"
    notes = "合成说明\n".encode()
    for relative, payload in (
        ("input/sow-template.xlsx", b"template"),
        ("data/scope.json", scope),
        ("data/delivery.json", delivery),
        ("output/sow.xlsx", workbook),
        ("output/sow-notes.md", notes),
    ):
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    scope_sha = sha256_bytes(scope)
    delivery_sha = sha256_bytes(delivery)
    review = {
        "contract": "ai-sow-final-review-v1",
        "runId": f"run-{generation_id}",
        "inputRevisionId": revision_id,
        "scopeSha256": scope_sha,
        "deliverySha256": delivery_sha,
        "packetSha256": "2" * 64,
        "decision": "PASS",
        "notes": [],
        "questions": [],
    }
    write_json(
        staged / "manifest.json",
        {
            "contract": "ai-sow-generation-manifest-v1",
            "generationId": generation_id,
            "revisionId": revision_id,
            "inputManifestPath": f".ai-sow/inputs/revisions/{revision_id}/manifest.json",
            "inputManifestSha256": sha256_bytes(input_manifest_bytes),
            "scopePath": f".ai-sow/generations/{generation_id}/data/scope.json",
            "scopeSha256": scope_sha,
            "deliveryPath": f".ai-sow/generations/{generation_id}/data/delivery.json",
            "deliverySha256": delivery_sha,
            "templatePath": f".ai-sow/generations/{generation_id}/input/sow-template.xlsx",
            "templateSha256": sha256_bytes(b"template"),
            "workbookPath": f".ai-sow/generations/{generation_id}/output/sow.xlsx",
            "workbookSha256": sha256_bytes(workbook),
            "workbookVerification": workbook_verification(),
            "notesPath": f".ai-sow/generations/{generation_id}/output/sow-notes.md",
            "notesSha256": sha256_bytes(notes),
            "scopeCompilerContract": "scope-compiler-v2",
            "deliveryCompilerContract": "delivery-compiler-v5",
            "rendererContract": "generation-renderer-v7",
            "decision": "PASS",
            "reviewMode": "AUTOMATIC_FINAL_REVIEW",
            "impact": {
                "action": "FULL_COMPILE",
                "baselineGenerationId": None,
                "baselineRevisionId": None,
                "changedSourceIds": [],
                "changedAnchorIds": [],
                "affectedFeatureIds": ["feature-refund-processing"],
                "escalation": "FULL",
                "reasonCodes": ["NO_CURRENT_GENERATION"],
            },
            "changeCounts": {
                "features": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
                "stories": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
                "acceptanceCriteria": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
                "tasks": {"affected": 0, "recomputed": 1, "reused": 0, "deleted": 0, "final": 1},
            },
            "finalReview": review,
            "finalReviewSha256": sha256_bytes(canonical_json_bytes(review)),
            "publicationComplete": True,
        },
    )
    return staged


def staged_success(tmp_path: Path, revision_id: str, generation_id: str):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    files = ProjectFiles.open(project)
    files.write_atomic(".ai-sow/templates/sow-template.xlsx", b"template")
    pending = stage_input(tmp_path, revision_id)
    manifest_bytes = (pending / "manifest.json").read_bytes()
    staged = stage_generation(tmp_path, generation_id, revision_id, manifest_bytes)
    return files, pending, staged


def allow_synthetic_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generation_store,
        "_reaudit_staged_workbook",
        lambda *_args, **_kwargs: None,
    )


def test_publish_success_switches_pointer_after_both_immutable_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    result = publish_success(
        files,
        target_revision_id="000001",
        target_generation_id="000001",
        pending_root=pending,
        staged_generation_root=staged,
    )
    current = files.read_json(".ai-sow/current.json")
    assert result.outcome == "PUBLISHED"
    assert current["revisionId"] == "000001"
    assert current["generationId"] == "000001"
    assert load_current(files).manifest_path.endswith("000001/manifest.json")


def test_publish_requires_template_snapshot_inside_generation_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    manifest_path = staged / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templatePath"] = ".ai-sow/generations/000001/input/sow-template.xlsx"
    manifest["templateSha256"] = sha256_bytes(b"template")
    write_json(manifest_path, manifest)
    (staged / "input/sow-template.xlsx").unlink()

    with pytest.raises(ProjectIOError) as caught:
        publish_success(
            files,
            target_revision_id="000001",
            target_generation_id="000001",
            pending_root=pending,
            staged_generation_root=staged,
        )

    assert caught.value.code == "PROJECT_PATH_MISSING"


def test_load_current_rejects_matching_template_hash_outside_generation_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    publish_success(
        files,
        target_revision_id="000001",
        target_generation_id="000001",
        pending_root=pending,
        staged_generation_root=staged,
    )
    alternate_path = ".ai-sow/templates/matching-template.xlsx"
    files.write_atomic(alternate_path, b"template")
    manifest_path = ".ai-sow/generations/000001/manifest.json"
    manifest = dict(files.read_json(manifest_path))
    manifest["templatePath"] = alternate_path
    files.write_atomic(manifest_path, canonical_json_bytes(manifest))
    current_path = ".ai-sow/current.json"
    current = dict(files.read_json(current_path))
    current["generationManifestSha256"] = sha256_bytes(
        files.read_bytes(manifest_path)
    )
    files.write_atomic(current_path, canonical_json_bytes(current))

    with pytest.raises(ProjectIOError) as caught:
        load_current(files)

    assert caught.value.code == "PROJECT_HASH_CLOSURE_INVALID"


def test_publish_rejects_generation_without_verified_workbook_evidence(
    tmp_path: Path,
) -> None:
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
    del manifest["workbookVerification"]
    write_json(staged / "manifest.json", manifest)

    with pytest.raises(ProjectIOError) as caught:
        publish_success(
            files,
            target_revision_id="000001",
            target_generation_id="000001",
            pending_root=pending,
            staged_generation_root=staged,
        )

    assert caught.value.code == "GENERATION_WORKBOOK_UNVERIFIED"
    assert not (files.root / ".ai-sow/current.json").exists()
    assert not (files.root / ".ai-sow/generations/000001").exists()
    assert not (files.root / generation_store.PUBLICATION_LEDGER).exists()


def test_publish_rejects_forged_verified_evidence_for_non_workbook(
    tmp_path: Path,
) -> None:
    files, pending, staged = staged_success(tmp_path, "000001", "000001")

    with pytest.raises(ProjectIOError) as caught:
        publish_success(
            files,
            target_revision_id="000001",
            target_generation_id="000001",
            pending_root=pending,
            staged_generation_root=staged,
        )

    assert caught.value.code == "GENERATION_WORKBOOK_UNVERIFIED"
    assert not (files.root / ".ai-sow/current.json").exists()
    assert not (files.root / generation_store.PUBLICATION_LEDGER).exists()


def test_load_current_accepts_v1_generation_as_read_only_evidence(
    tmp_path: Path,
) -> None:
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    manifest_path = staged / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["workbookVerification"]
    manifest["scopeCompilerContract"] = "scope-compiler-v1"
    manifest["deliveryCompilerContract"] = "delivery-compiler-v1"
    manifest["rendererContract"] = "generation-renderer-v1"
    manifest["changeCounts"] = {
        "features": {"added": 1, "updated": 0, "removed": 0},
        "recomputedStories": 1,
        "recomputedTasks": 1,
    }
    manifest_bytes = write_json(manifest_path, manifest)
    files.publish_tree_new(pending, ".ai-sow/inputs/revisions/000001")
    files.publish_tree_new(staged, ".ai-sow/generations/000001")
    files.write_atomic(
        ".ai-sow/current.json",
        canonical_json_bytes(
            {
                "contract": "ai-sow-current-v1",
                "generationId": "000001",
                "revisionId": "000001",
                "decision": "PASS",
                "generationManifestPath": ".ai-sow/generations/000001/manifest.json",
                "generationManifestSha256": sha256_bytes(manifest_bytes),
            }
        ),
    )

    current = load_current(files)

    assert current is not None
    assert current.generation_id == "000001"
    assert current.revision_id == "000001"


def test_publish_rejects_manifest_template_hash_that_does_not_match_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
    manifest["templateSha256"] = "0" * 64
    write_json(staged / "manifest.json", manifest)

    with pytest.raises(ProjectIOError) as caught:
        publish_success(
            files,
            target_revision_id="000001",
            target_generation_id="000001",
            pending_root=pending,
            staged_generation_root=staged,
        )

    assert caught.value.code == "PROJECT_HASH_MISMATCH"
    assert not (files.root / ".ai-sow/current.json").exists()
    assert not (files.root / generation_store.PUBLICATION_LEDGER).exists()


def test_crash_before_pointer_swap_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    publish_success(
        files,
        target_revision_id="000001",
        target_generation_id="000001",
        pending_root=pending,
        staged_generation_root=staged,
    )
    previous = files.read_bytes(".ai-sow/current.json")
    pending2 = stage_input(tmp_path, "000002")
    staged2 = stage_generation(
        tmp_path,
        "000002",
        "000002",
        (pending2 / "manifest.json").read_bytes(),
    )

    def fail_replace(*_args, **_kwargs):
        raise ProjectIOError("POINTER_SWAP_FAILED", ".ai-sow/current.json", "failed")

    monkeypatch.setattr(generation_store, "replace_current", fail_replace)
    with pytest.raises(ProjectIOError):
        publish_success(
            files,
            target_revision_id="000002",
            target_generation_id="000002",
            pending_root=pending2,
            staged_generation_root=staged2,
        )
    assert files.read_bytes(".ai-sow/current.json") == previous
    current = load_current(files)
    cleanup_interrupted_publication(files, current)
    assert not (files.root / ".ai-sow/inputs/revisions/000002").exists()
    assert not (files.root / ".ai-sow/generations/000002").exists()
    assert pending2.exists()


def test_immutable_tree_rejects_different_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_synthetic_audit(monkeypatch)
    files, pending, staged = staged_success(tmp_path, "000001", "000001")
    publish_success(
        files,
        target_revision_id="000001",
        target_generation_id="000001",
        pending_root=pending,
        staged_generation_root=staged,
    )
    conflicting_pending = stage_input(tmp_path, "000001")
    conflicting = stage_generation(
        tmp_path,
        "000001",
        "000001",
        (conflicting_pending / "manifest.json").read_bytes(),
    )
    (conflicting / "data/scope.json").write_bytes(b"different")
    with pytest.raises(ProjectIOError) as raised:
        publish_success(
            files,
            target_revision_id="000001",
            target_generation_id="000001",
            pending_root=conflicting_pending,
            staged_generation_root=conflicting,
        )
    assert raised.value.code == "PROJECT_CONTENT_CONFLICT"


def test_allocate_next_ids_reuses_pending_revision_and_ledger_reservation(
    tmp_path: Path,
) -> None:
    files, pending, _staged = staged_success(tmp_path, "000007", "000009")
    files.publish_tree_new(pending, ".ai-sow/inputs/pending")
    files.write_atomic(
        ".ai-sow/work/publication.json",
        canonical_json_bytes(
            {
                "revisionId": "000007",
                "generationId": "000009",
                "publicationComplete": False,
            }
        ),
    )
    assert allocate_next_ids(files, None) == ("000007", "000009")
