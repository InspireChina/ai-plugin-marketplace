from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import generation_store  # noqa: E402
from generation_store import promote  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


def staged_v8_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from test_orchestrator import (  # noqa: PLC0415
        fixture_renderer,
        reviewed_artifact_state,
    )
    import orchestrator as orchestrator_module  # noqa: PLC0415

    project = tmp_path / "v8-project"
    project.mkdir()
    files = ProjectFiles.open(project)
    state = reviewed_artifact_state()
    monkeypatch.setattr(orchestrator_module, "prepare_draft", fixture_renderer(tmp_path))
    prepared = orchestrator_module.prepare_artifact(
        state,
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )
    manifest = files.read_json(prepared["artifactManifestPath"])
    approval = {
        "contract": "ai-sow-approval-v1",
        "runId": manifest["runId"],
        "artifactManifestSha256": prepared["artifactManifestSha256"],
        "reviewDecisionSha256": manifest["reviewDecisionSha256"],
        "candidateSha256": manifest["candidateSha256"],
        "sourceManifestSha256": manifest["sourceManifestSha256"],
        "templateSha256": manifest["templateSha256"],
        "effectivePolicyDecisionSha256": manifest[
            "effectivePolicyDecisionSha256"
        ],
        "decision": "APPROVE",
        "approvedAt": "2026-09-04T00:00:00Z",
    }
    return files, prepared, manifest, approval


def test_promote_is_byte_identical_and_self_contained_after_run_work_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, prepared, _manifest, approval = staged_v8_artifact(tmp_path, monkeypatch)
    draft_workbook = files.read_bytes(prepared["workbookPath"])
    draft_notes = files.read_bytes(prepared["notesPath"])

    result = promote(
        prepared["artifactManifestSha256"], approval, files=files
    )

    assert result.outcome == "PUBLISHED"
    assert files.read_bytes(result.workbook_path) == draft_workbook
    assert files.read_bytes(result.notes_path) == draft_notes
    current = files.read_json(".ai-sow/current.json")
    generation = files.read_json(current["generationManifestPath"])
    assert generation["rendererContract"] == "generation-renderer-v8"
    generation_root = Path(current["generationManifestPath"]).parent.as_posix()
    for relative in (
        "data/sow-model.json",
        "input/sow-template.xlsx",
        "input/effective-policy-decision.json",
        "proof/review-decision.json",
        "proof/scope-closure-checkpoint.json",
        "proof/story-ac-checkpoint.json",
        "proof/task-checkpoint.json",
        "proof/artifact-manifest.json",
        "proof/approval.json",
    ):
        files.resolve(f"{generation_root}/{relative}")
    files.remove_managed_tree(
        ".ai-sow/work", allowed_roots=(".ai-sow/work",)
    )
    assert files.read_json(current["generationManifestPath"])[
        "artifactManifestSha256"
    ] == prepared["artifactManifestSha256"]


def test_promote_rejects_stale_approval_and_preserves_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, prepared, _manifest, approval = staged_v8_artifact(tmp_path, monkeypatch)
    stale = {**approval, "candidateSha256": "0" * 64}

    with pytest.raises(ProjectIOError) as caught:
        promote(prepared["artifactManifestSha256"], stale, files=files)

    assert caught.value.code == "APPROVAL_BINDING_MISMATCH"
    assert not (files.root / ".ai-sow/current.json").exists()


def test_v8_promote_never_calls_renderer_or_office(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, prepared, _manifest, approval = staged_v8_artifact(tmp_path, monkeypatch)

    assert not hasattr(generation_store, "prepare_draft")
    assert not hasattr(generation_store, "require_office_engine")

    result = promote(
        prepared["artifactManifestSha256"], approval, files=files
    )

    assert result.outcome == "PUBLISHED"


def test_generation_staging_never_uses_external_mkdtemp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile  # noqa: PLC0415

    files, prepared, _manifest, approval = staged_v8_artifact(tmp_path, monkeypatch)
    monkeypatch.setattr(
        tempfile,
        "mkdtemp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("external mkdtemp used")
        ),
    )

    result = promote(prepared["artifactManifestSha256"], approval, files=files)

    assert result.outcome == "PUBLISHED"
    assert not any((tmp_path / "v8-project/.ai-sow").glob(".generation-stage-*"))


def test_v8_crash_before_current_swap_preserves_last_known_good(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_orchestrator import (  # noqa: PLC0415
        fixture_renderer,
        reviewed_artifact_state,
    )
    import orchestrator as orchestrator_module  # noqa: PLC0415

    files, first, _manifest, first_approval = staged_v8_artifact(tmp_path, monkeypatch)
    promote(first["artifactManifestSha256"], first_approval, files=files)
    current_before = files.read_bytes(".ai-sow/current.json")
    monkeypatch.setattr(
        orchestrator_module,
        "prepare_draft",
        fixture_renderer(tmp_path / "second-render"),
    )
    second = orchestrator_module.prepare_artifact(
        reviewed_artifact_state(),
        files,
        template_path=SKILL_ROOT / "assets/sow-template.xlsx",
    )
    second_manifest = files.read_json(second["artifactManifestPath"])
    second_approval = {
        **first_approval,
        "artifactManifestSha256": second["artifactManifestSha256"],
        "reviewDecisionSha256": second_manifest["reviewDecisionSha256"],
        "candidateSha256": second_manifest["candidateSha256"],
        "sourceManifestSha256": second_manifest["sourceManifestSha256"],
        "templateSha256": second_manifest["templateSha256"],
        "effectivePolicyDecisionSha256": second_manifest[
            "effectivePolicyDecisionSha256"
        ],
    }

    def fail_swap(*_args, **_kwargs):
        raise ProjectIOError(
            "POINTER_SWAP_FAILED", ".ai-sow/current.json", "failed"
        )

    monkeypatch.setattr(generation_store, "replace_current", fail_swap)
    with pytest.raises(ProjectIOError):
        promote(second["artifactManifestSha256"], second_approval, files=files)

    assert files.read_bytes(".ai-sow/current.json") == current_before
