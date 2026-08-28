from __future__ import annotations

from typing import Any

from runtime.claims import claim_metrics
from runtime.diagnostics import diagnostic
from runtime.project_io import ProjectFiles, ProjectIOError


DEFAULT_REVIEW_DEPTH = {
    "analyze-requirement": "factual",
    "analyze-as-is": "full",
    "generate-design": "full",
    "generate-story": "factual",
    "generate-task": "factual",
}
OWNER_NAMES = frozenset(DEFAULT_REVIEW_DEPTH)
INVESTIGATION_MODES = {"hypothesis", "exhaustive"}
REVIEW_DEPTHS = {"mechanical", "factual", "full"}


def valid_owner_controls(project: dict[str, Any]) -> bool:
    controls = project.get("ownerControls", {})
    if not isinstance(controls, dict) or not set(controls).issubset(OWNER_NAMES):
        return False
    for value in controls.values():
        if not isinstance(value, dict) or not set(value).issubset(
            {"investigationMode", "reviewDepth", "tokenBudget"}
        ):
            return False
        if value.get("investigationMode", "hypothesis") not in INVESTIGATION_MODES:
            return False
        if value.get("reviewDepth", "factual") not in REVIEW_DEPTHS:
            return False
        budget = value.get("tokenBudget")
        if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool) or budget < 1):
            return False
    return True


def owner_control(project: dict[str, Any], owner: str) -> dict[str, object]:
    configured = project.get("ownerControls", {})
    selected = configured.get(owner, {}) if isinstance(configured, dict) else {}
    if not isinstance(selected, dict):
        selected = {}
    return {
        "investigationMode": selected.get("investigationMode", "hypothesis"),
        "reviewDepth": selected.get("reviewDepth", DEFAULT_REVIEW_DEPTH.get(owner, "factual")),
        "tokenBudget": selected.get("tokenBudget"),
    }


def validate_manifest_controls(
    files: ProjectFiles,
    manifest: dict[str, object],
    *,
    owner: str,
    project_path: str,
    claims_path: str,
    manifest_path: str,
) -> list[dict[str, object]]:
    try:
        project = files.read_json(project_path)
        claims = files.read_json(claims_path)
    except ProjectIOError as error:
        return [diagnostic(error.code, str(error), error.relative_path)]
    if not isinstance(project, dict):
        return [diagnostic("PROJECT_INVALID", "project must be a JSON object", project_path)]
    diagnostics: list[dict[str, object]] = []
    if not valid_owner_controls(project):
        diagnostics.append(
            diagnostic(
                "PROJECT_SCHEMA_INVALID",
                "project Owner controls are invalid",
                project_path,
            )
        )
    if manifest.get("ownerControl") != owner_control(project, owner):
        diagnostics.append(
            diagnostic(
                "CONTEXT_CONTROL_STALE",
                "context Owner controls do not match project.json",
                manifest_path,
            )
        )
    if manifest.get("claimMetrics") != claim_metrics(claims):
        diagnostics.append(
            diagnostic(
                "CONTEXT_CLAIM_METRICS_STALE",
                "context claim metrics do not match claims.json",
                manifest_path,
            )
        )
    return diagnostics
