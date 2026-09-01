from __future__ import annotations

import hashlib
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
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


def write_json(path: Path, value: object) -> bytes:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


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
            "templatePath": ".ai-sow/templates/sow-template.xlsx",
            "templateSha256": hashlib.sha256(b"template").hexdigest(),
            "workbookPath": f".ai-sow/generations/{generation_id}/output/sow.xlsx",
            "workbookSha256": sha256_bytes(workbook),
            "notesPath": f".ai-sow/generations/{generation_id}/output/sow-notes.md",
            "notesSha256": sha256_bytes(notes),
            "scopeCompilerContract": "scope-compiler-v1",
            "deliveryCompilerContract": "delivery-compiler-v1",
            "rendererContract": "generation-renderer-v1",
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
                "features": {"added": 1, "updated": 0, "removed": 0},
                "recomputedStories": 1,
                "recomputedTasks": 1,
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


def test_publish_success_switches_pointer_after_both_immutable_trees(
    tmp_path: Path,
) -> None:
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


def test_crash_before_pointer_swap_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_immutable_tree_rejects_different_bytes(tmp_path: Path) -> None:
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
