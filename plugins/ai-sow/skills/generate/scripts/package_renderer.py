from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes
from models import RenderedPackage
from task_standard_catalog import catalog as load_task_standard_catalog

if __package__:
    from .office_engine import (
        OfficeEngineError,
        recalculate_workbook,
        require_office_engine,
    )
    from .story_notes import render_model_notes
    from .workbook import audit_calculated_workbook, write_workbook
else:
    from office_engine import OfficeEngineError, recalculate_workbook, require_office_engine
    from story_notes import render_model_notes
    from workbook import audit_calculated_workbook, write_workbook


RENDERER_CONTRACT = "generation-renderer-v8"


class PackageRenderError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def prepare_draft(
    reviewed_model: Mapping[str, object],
    *,
    template_path: Path,
    review_decision: Mapping[str, object],
) -> RenderedPackage:
    """Render and Office-verify a reviewed model in an isolated staging root."""
    candidate_sha256 = sha256_bytes(canonical_json_bytes(reviewed_model))
    if review_decision.get("decision") != "PASS":
        raise PackageRenderError(
            "REVIEW_DECISION_INVALID",
            "只有全覆盖终审通过的 sow-model 才能生成候选工件。",
        )
    if review_decision.get("candidateSha256") != candidate_sha256:
        raise PackageRenderError(
            "REVIEW_DECISION_STALE",
            "终审决定未绑定当前 sow-model。",
        )
    required_checkpoint_fields = (
        "scopeClosureCheckpointSha256",
        "storyAcCheckpointSha256",
        "taskCheckpointSha256",
    )
    if any(
        not isinstance(review_decision.get(field), str)
        or len(str(review_decision[field])) != 64
        for field in required_checkpoint_fields
    ):
        raise PackageRenderError(
            "REVIEW_DECISION_INVALID",
            "终审决定缺少完整 Stage checkpoint 绑定。",
        )
    project = reviewed_model.get("project")
    expected_template_sha256 = (
        project.get("templateSha256") if isinstance(project, Mapping) else None
    )
    if expected_template_sha256 != sha256_bytes(Path(template_path).read_bytes()):
        raise PackageRenderError(
            "TEMPLATE_HASH_MISMATCH",
            "候选模板未绑定 reviewed sow-model。",
        )
    root = Path(tempfile.mkdtemp(prefix="ai-sow-draft-"))
    output = root / "output"
    output.mkdir()
    candidate_path = output / "sow.candidate.xlsx"
    workbook_path = output / "sow.xlsx"
    notes_path = output / "sow-notes.md"
    task_catalog = load_task_standard_catalog(Path(template_path))
    try:
        write_workbook(Path(template_path), dict(reviewed_model), candidate_path)
        engine = require_office_engine()
        recalculate_workbook(candidate_path, workbook_path, engine)
        workbook_audit = audit_calculated_workbook(
            workbook_path,
            Path(template_path),
            dict(reviewed_model),
            engine,
        )
        notes_text = render_model_notes(
            reviewed_model,
            review_decision,
            task_catalog,
        )
        notes_path.write_text(notes_text, encoding="utf-8", newline="\n")
        if notes_path.read_text(encoding="utf-8") != notes_text:
            raise PackageRenderError(
                "WORKBOOK_VERIFY_FAILED",
                "说明文件复读失败。",
            )
        candidate_path.unlink(missing_ok=True)
        return RenderedPackage(
            root=str(root),
            workbook_path=str(workbook_path),
            notes_path=str(notes_path),
            workbook_sha256=sha256_bytes(workbook_path.read_bytes()),
            notes_sha256=sha256_bytes(notes_path.read_bytes()),
            files=("output/sow-notes.md", "output/sow.xlsx"),
            workbook_audit=workbook_audit,
        )
    except PackageRenderError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    except OfficeEngineError as error:
        shutil.rmtree(root, ignore_errors=True)
        raise PackageRenderError(error.code, str(error)) from error
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as error:
        shutil.rmtree(root, ignore_errors=True)
        raise PackageRenderError(
            "WORKBOOK_VERIFY_FAILED",
            "候选工件生成或复读失败。",
        ) from error
