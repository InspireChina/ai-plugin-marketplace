from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_CASES = (
    (PLUGIN_ROOT / "skills/analyze-requirement/scripts/validate.py", True),
    (PLUGIN_ROOT / "skills/analyze-as-is/scripts/validate.py", True),
    (PLUGIN_ROOT / "skills/generate-design/scripts/validate.py", True),
    (PLUGIN_ROOT / "skills/generate-story/scripts/validate.py", True),
    (PLUGIN_ROOT / "skills/generate-task/scripts/validate.py", True),
    (PLUGIN_ROOT / "skills/generate-sow/scripts/generate_sow.py", False),
)
OWNER_SCRIPTS = tuple(script for script, owner_validator in SCRIPT_CASES if owner_validator)


def load_script(script: Path, index: int) -> object:
    spec = importlib.util.spec_from_file_location(f"staging_cli_{index}", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(script.parent))
    return module


@pytest.mark.parametrize(("script", "owner_validator"), SCRIPT_CASES)
def test_staging_root_flag_selects_overlay_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    script: Path,
    owner_validator: bool,
) -> None:
    module = load_script(script, SCRIPT_CASES.index((script, owner_validator)))
    project_root = tmp_path / "project"
    staging_root = ".ai-sow/.stage-0123456789ab"
    calls: list[tuple[Path, str]] = []

    def open_view(base: Path, staging: str) -> object:
        calls.append((base, staging))
        raise module.ProjectIOError("STAGING_VIEW_SELECTED", ".", "staging view selected")

    monkeypatch.setattr(module.ProjectFiles, "open_view", staticmethod(open_view), raising=False)
    argv = [
        str(script),
        "--project-root",
        str(project_root),
        "--staging-root",
        staging_root,
    ]
    if owner_validator:
        argv.extend(("--mode", "check"))
    monkeypatch.setattr(sys, "argv", argv)

    assert module.main() == 2
    assert calls == [(project_root, staging_root)]
    result = json.loads(capsys.readouterr().out)
    assert result["diagnostics"][0]["code"] == "STAGING_VIEW_SELECTED"


@pytest.mark.parametrize(("script", "owner_validator"), SCRIPT_CASES)
def test_omitted_staging_root_preserves_normal_project_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    script: Path,
    owner_validator: bool,
) -> None:
    module = load_script(script, SCRIPT_CASES.index((script, owner_validator)))
    project_root = tmp_path / "project"
    calls: list[Path] = []

    def open_project(root: Path) -> object:
        calls.append(root)
        raise module.ProjectIOError("PROJECT_VIEW_SELECTED", ".", "project view selected")

    monkeypatch.setattr(module.ProjectFiles, "open", staticmethod(open_project))
    argv = [str(script), "--project-root", str(project_root)]
    if owner_validator:
        argv.extend(("--mode", "check"))
    monkeypatch.setattr(sys, "argv", argv)

    assert module.main() == 2
    assert calls == [project_root]
    result = json.loads(capsys.readouterr().out)
    assert result["diagnostics"][0]["code"] == "PROJECT_VIEW_SELECTED"


@pytest.mark.parametrize("script", OWNER_SCRIPTS)
@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_review_override_blocks_before_staging_view_or_candidate_read(
    tmp_path: Path,
    script: Path,
    mode: str,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".ai-sow").mkdir(parents=True)
    staging_root = ".ai-sow/.stage-deadbeefcafe"
    review_path = ".ai-sow/work/reconcile/run/review.md"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--project-root",
            str(project_root),
            "--staging-root",
            staging_root,
            "--mode",
            mode,
            "--review-path",
            review_path,
        ],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["diagnostics"] == [
        {
            "code": "REVIEW_PATH_MODE_INVALID",
                "message": "--review-path override is allowed only in check, review, or publish-approved mode",
            "path": review_path,
        }
    ]
    assert not (project_root / staging_root).exists()
