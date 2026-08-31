from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.diagnostics import diagnostic
from runtime.patch import run_patch_cli


OWNER = "generate-story"
WORK_ROOT = ".ai-sow/work/generate-story"


def post_check(project_root: Path, staging_root: str) -> list[dict[str, object]]:
    commands = (
        (
            "prepare-context",
            [
                sys.executable,
                str(Path(__file__).with_name("prepare_context.py")),
                "--project-root",
                str(project_root),
                "--staging-root",
                staging_root,
            ],
        ),
        (
            "render-review",
            [
                sys.executable,
                str(Path(__file__).with_name("render_review.py")),
                "--project-root",
                str(project_root),
                "--staging-root",
                staging_root,
            ],
        ),
        (
            "owner-review",
            [
                sys.executable,
                str(Path(__file__).with_name("validate.py")),
                "--project-root",
                str(project_root),
                "--staging-root",
                staging_root,
                "--mode",
                "review",
                "--candidate",
                f"{WORK_ROOT}/delivery.candidate.json",
                "--review-path",
                f"{WORK_ROOT}/review.candidate.md",
            ],
        ),
    )
    for stage, command in commands:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode == 0:
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
        return [
            diagnostic(
                "PATCH_POST_CHECK_FAILED",
                f"patch transaction failed during {stage}",
                stage=stage,
                postCheckDiagnostics=payload.get("diagnostics", []),
            )
        ]
    return []


if __name__ == "__main__":
    raise SystemExit(
        run_patch_cli(
            OWNER,
            f"{WORK_ROOT}/delivery.candidate.json",
            post_check=post_check,
            packet_path=f"{WORK_ROOT}/review-packet.json",
            reviewer_path=f"{WORK_ROOT}/reviewer.json",
            approval_path=f"{WORK_ROOT}/approval.json",
        )
    )
