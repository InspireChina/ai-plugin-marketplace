from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_action_binding,
    validate_contract,
    validate_state_combination,
)
from delivery_compiler import (  # noqa: E402
    apply_ready_group as apply_story_action_group,
    build_story_ac_checkpoint,
    prepare_action as prepare_delivery_action,
)
from final_review import (  # noqa: E402
    _normalize_findings,
    advance_layered_review,
    build_repair_plan,
    prepare_r1_scope_join,
    prepare_r1_source_audit,
    validate_r1_scope_join_result,
    validate_r1_source_audit_result,
)
from generation_store import load_current, promote  # noqa: E402
from intake import prepare as prepare_input_revision  # noqa: E402
from models import Diagnostic, RouteDecision  # noqa: E402
from package_renderer import PackageRenderError, prepare_draft  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402
from scope_compiler import (  # noqa: E402
    apply_repair_action_group as apply_scope_repair_action_group,
    apply_ready_group as apply_scope_action_group,
    prepare_action as prepare_scope_action,
    build_scope_closure_checkpoint,
    prepare_repair_action as prepare_scope_repair_action,
)
from sow_model import model_skeleton  # noqa: E402
from task_compiler import (  # noqa: E402
    apply_ready_group as apply_task_action_group,
    build_task_checkpoint,
    prepare_action as prepare_task_action,
)
from task_standard_catalog import catalog as load_task_standard_catalog  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
WORK_ROOT = ".ai-sow/work"
ACTIVE_RUN_PATH = f"{WORK_ROOT}/active-run.json"
RUNS_ROOT = f"{WORK_ROOT}/runs"
EXECUTION_POLICY_SHA256 = sha256_bytes(
    (SKILL_ROOT / "contracts" / "execution-policy-v1.json").read_bytes()
)
ROUTE_CONTEXT_CONTRACT = "ai-sow-route-context-v1"
GENERATION_PROOF_CLOSURE_CONTRACT = "ai-sow-generation-proof-closure-v1"
GENERATION_MANIFEST_CONTRACT = "ai-sow-generation-manifest-v2"
RENDERER_FINGERPRINT_PATH = SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json"
_STDLIB_TEMPFILE = tempfile
_PROJECT_TEMP_ROOT: ContextVar[Path | None] = ContextVar(
    "ai_sow_project_temp_root", default=None
)


class _ProjectLocalTempfile:
    """Route unqualified renderer tempdirs through the active project context."""

    @staticmethod
    def _with_project_dir(
        args: tuple[object, ...], kwargs: dict[str, object]
    ) -> dict[str, object]:
        updated = dict(kwargs)
        root = _PROJECT_TEMP_ROOT.get()
        if root is not None and len(args) < 3 and updated.get("dir") is None:
            updated["dir"] = root
        return updated

    def mkdtemp(self, *args: object, **kwargs: object) -> str:
        return _STDLIB_TEMPFILE.mkdtemp(
            *args, **self._with_project_dir(args, kwargs)
        )

    def TemporaryDirectory(  # noqa: N802 - mirrors the stdlib API
        self, *args: object, **kwargs: object
    ) -> tempfile.TemporaryDirectory[str]:
        return _STDLIB_TEMPFILE.TemporaryDirectory(
            *args, **self._with_project_dir(args, kwargs)
        )

    def __getattr__(self, name: str) -> object:
        return getattr(_STDLIB_TEMPFILE, name)


_PROJECT_LOCAL_TEMPFILE = _ProjectLocalTempfile()
# The renderer and workbook are fingerprint-frozen. Their only unqualified
# tempfile calls are permanently routed through a context-local adapter; calls
# outside orchestration retain the stdlib default, while concurrent projects do
# not share mutable TMPDIR or tempfile.tempdir process state.
prepare_draft.__globals__["tempfile"] = _PROJECT_LOCAL_TEMPFILE
_audit_calculated_workbook = prepare_draft.__globals__.get(
    "audit_calculated_workbook"
)
if callable(_audit_calculated_workbook):
    _audit_calculated_workbook.__globals__["tempfile"] = _PROJECT_LOCAL_TEMPFILE


def _prepare_project_local_draft(
    reviewed_model: Mapping[str, object],
    *,
    template_path: Path,
    review_decision: Mapping[str, object],
    temporary_root: Path,
) -> object:
    token = _PROJECT_TEMP_ROOT.set(temporary_root)
    try:
        return prepare_draft(
            reviewed_model,
            template_path=template_path,
            review_decision=review_decision,
        )
    finally:
        _PROJECT_TEMP_ROOT.reset(token)


ROUTE_CONTEXT_FIELDS = frozenset(
    {
        "contract",
        "taskCatalogSemanticSha256",
        "taskEstimationMethodSha256",
        "rendererSha256",
        "effectivePolicyDecisionSha256",
        "checkpointSha256s",
        "reviewDecisionSha256",
        "inputDiagnostics",
    }
)
ROUTING_BASIS_FIELDS = frozenset(
    {
        "semanticInputSha256",
        "templateSha256",
        "deliveryPolicySha256",
        "executionPolicySha256",
        "taskCatalogSemanticSha256",
        "taskEstimationMethodSha256",
        "rendererSha256",
        "effectivePolicyDecisionSha256",
        "scopeClosureCheckpointSha256",
        "storyAcCheckpointSha256",
        "taskCheckpointSha256",
        "reviewDecisionSha256",
    }
)
ROUTE_RECOVERY_STAGE = {
    "semanticInputSha256": "STAGE_1",
    "deliveryPolicySha256": "STAGE_1",
    "scopeClosureCheckpointSha256": "STAGE_1",
    "effectivePolicyDecisionSha256": "STAGE_2",
    "storyAcCheckpointSha256": "STAGE_2",
    "taskCatalogSemanticSha256": "STAGE_3",
    "taskEstimationMethodSha256": "STAGE_3",
    "taskCheckpointSha256": "STAGE_3",
    "reviewDecisionSha256": "REVIEW",
    "templateSha256": "RENDER",
    "rendererSha256": "RENDER",
}
ROUTE_STAGE_RANK = {
    "STAGE_1": 0,
    "STAGE_2": 1,
    "STAGE_3": 2,
    "REVIEW": 3,
    "RENDER": 4,
}
ROUTE_INVALIDATIONS = {
    "STAGE_1": ("SCOPE_CLOSURE", "STORY_AC", "TASK", "REVIEW", "ARTIFACT"),
    "STAGE_2": ("STORY_AC", "TASK", "REVIEW", "ARTIFACT"),
    "STAGE_3": ("TASK", "REVIEW", "ARTIFACT"),
    "REVIEW": ("REVIEW", "ARTIFACT"),
    "RENDER": ("ARTIFACT",),
}
FULL_COMPILE_INVALIDATIONS = (
    "SCOPE_CLOSURE",
    "STORY_AC",
    "TASK",
    "REVIEW",
    "ARTIFACT",
)


def _renderer_sha256() -> str:
    baseline = json.loads(RENDERER_FINGERPRINT_PATH.read_text(encoding="utf-8"))
    files = baseline.get("files") if isinstance(baseline, Mapping) else None
    if not isinstance(files, Mapping):
        raise ProjectIOError(
            "RENDERER_FINGERPRINT_INVALID",
            "contracts/renderer-fingerprint-baseline.json",
            "renderer fingerprint baseline 结构无效。",
        )
    actual = {
        "rendererContract": baseline.get("rendererContract"),
        "files": {
            str(path): sha256_bytes((SKILL_ROOT / str(path)).read_bytes())
            for path in sorted(files)
        },
    }
    return sha256_bytes(canonical_json_bytes(actual))


def advance_stage_one(state: Mapping[str, object]) -> dict[str, object]:
    """Return the next host-neutral Stage 1 transition without running a worker."""
    candidate = state.get("candidate")
    input_items = (
        candidate.get("inputItems") if isinstance(candidate, Mapping) else None
    )
    scope_closure = (
        candidate.get("scopeClosure") if isinstance(candidate, Mapping) else None
    )
    source_records = [
        item
        for item in state.get("actionRecords", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("submission"), Mapping)
        and item["submission"].get("resultKind") == "SOURCE_SCAN_PATCH"
    ] if isinstance(state.get("actionRecords"), list) else []
    proposal_records = [
        item
        for item in state.get("proposalRecords", [])
        if isinstance(item, Mapping)
    ] if isinstance(state.get("proposalRecords"), list) else []
    transitions = (
        (not source_records, "SOURCE_SCAN", "EPIC_FEATURE"),
        (not isinstance(input_items, list) or not input_items, "SOURCE_SCAN", "EPIC_FEATURE"),
        (not proposal_records, "SCOPE_PROPOSAL", "EPIC_FEATURE"),
        (not isinstance(scope_closure, list) or not scope_closure, "SCOPE_JOIN", "EPIC_FEATURE"),
        (not state.get("r1SourceResults"), "R1_SOURCE_INDEPENDENT_SCAN", "SOURCE_AUDIT"),
        (not state.get("r1ScopeResult"), "R1_SCOPE_JOIN", "SOURCE_SCOPE"),
    )
    for required, action_kind, stage in transitions:
        if required:
            return {
                "outcome": "ACTION_REQUIRED",
                "actionKind": action_kind,
                "stage": stage,
                "lowestRecoveryStage": "STAGE_1",
                "nextAction": None,
                "diagnostics": [],
            }
    checkpoint_result = build_scope_closure_checkpoint(state)
    if checkpoint_result.get("outcome") != "READY_FOR_STORY_AC":
        return {
            **checkpoint_result,
            "lowestRecoveryStage": "STAGE_1",
            "nextAction": None,
        }
    return {
        **checkpoint_result,
        "nextPhase": "STORY_AC",
        "lowestRecoveryStage": None,
        "nextAction": None,
    }


def advance_stage_two(state: Mapping[str, object]) -> dict[str, object]:
    """Return the next host-neutral Story/AC transition without invoking a CLI."""
    prepared = prepare_delivery_action(state, "STORY_AC")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return {
            **prepared,
            "lowestRecoveryStage": "STAGE_2",
            "nextAction": None,
        }
    required = [
        str(spec.get("logicalShardId"))
        for spec in prepared.get("specs", [])
        if isinstance(spec, Mapping)
    ]
    records = [
        item
        for item in state.get("storyActionRecords", [])
        if isinstance(item, Mapping)
    ] if isinstance(state.get("storyActionRecords"), list) else []
    completed = {
        str(record.get("logicalShardId"))
        for record in records
        if record.get("status") == "SUCCESS"
    }
    pending = [shard_id for shard_id in required if shard_id not in completed]
    if pending:
        return {
            "outcome": "ACTION_REQUIRED",
            "actionKind": "STORY_AC",
            "stage": "STORY_AC",
            "requiredLogicalShardIds": required,
            "pendingLogicalShardIds": pending,
            "joinRequired": len(required) > 1,
            "specs": prepared["specs"],
            "lowestRecoveryStage": "STAGE_2",
            "nextAction": None,
            "diagnostics": [],
        }
    joined = apply_story_action_group(state, records)
    if joined.diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "candidate": joined.model,
            "lowestRecoveryStage": "STAGE_2",
            "nextAction": None,
            "diagnostics": joined.diagnostics,
        }
    checkpoint_state = {
        **state,
        "candidate": joined.model,
        "storyActionRecords": records,
        "upstreamCheckpointSha256s": [
            sha256_bytes(canonical_json_bytes(state["scopeClosureCheckpoint"]))
        ],
    }
    checkpoint_result = build_story_ac_checkpoint(checkpoint_state)
    if checkpoint_result.get("outcome") != "READY_FOR_TASK":
        return {
            **checkpoint_result,
            "candidate": joined.model,
            "lowestRecoveryStage": "STAGE_2",
            "nextAction": None,
        }
    return {
        **checkpoint_result,
        "candidate": joined.model,
        "nextPhase": "TASK",
        "joinRequired": len(required) > 1,
        "lowestRecoveryStage": None,
        "nextAction": None,
    }


def advance_stage_three(state: Mapping[str, object]) -> dict[str, object]:
    """Return the next host-neutral Task transition without invoking a CLI."""
    prepared = prepare_task_action(state, "TASK")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return {
            **prepared,
            "lowestRecoveryStage": "STAGE_3",
            "nextAction": None,
        }
    required = [
        str(spec.get("logicalShardId"))
        for spec in prepared.get("specs", [])
        if isinstance(spec, Mapping)
    ]
    records = [
        item
        for item in state.get("taskActionRecords", [])
        if isinstance(item, Mapping)
    ] if isinstance(state.get("taskActionRecords"), list) else []
    completed = {
        str(record.get("logicalShardId"))
        for record in records
        if record.get("status") == "SUCCESS"
    }
    pending = [shard_id for shard_id in required if shard_id not in completed]
    if pending:
        return {
            "outcome": "ACTION_REQUIRED",
            "actionKind": "TASK",
            "stage": "TASK",
            "requiredLogicalShardIds": required,
            "pendingLogicalShardIds": pending,
            "joinRequired": len(required) > 1,
            "specs": prepared["specs"],
            "lowestRecoveryStage": "STAGE_3",
            "nextAction": None,
            "diagnostics": [],
        }
    joined = apply_task_action_group(state, records)
    if joined.diagnostics:
        return {
            "outcome": "OWNER_FIX_REQUIRED",
            "candidate": joined.model,
            "lowestRecoveryStage": "STAGE_3",
            "nextAction": None,
            "diagnostics": joined.diagnostics,
        }
    checkpoint_result = build_task_checkpoint(
        {
            **state,
            "candidate": joined.model,
            "taskActionRecords": records,
        }
    )
    if checkpoint_result.get("outcome") != "READY_FOR_REVIEW":
        return {
            **checkpoint_result,
            "candidate": joined.model,
            "lowestRecoveryStage": "STAGE_3",
            "nextAction": None,
        }
    return {
        **checkpoint_result,
        "candidate": joined.model,
        "nextPhase": "REVIEW",
        "joinRequired": len(required) > 1,
        "lowestRecoveryStage": None,
        "nextAction": None,
    }


def advance_review(state: Mapping[str, object]) -> dict[str, object]:
    """Return the next host-neutral fresh review transition."""
    result = dict(advance_layered_review(state))
    if result.get("outcome") == "READY_FOR_APPROVAL":
        result["lowestRecoveryStage"] = None
    else:
        result["lowestRecoveryStage"] = "REVIEW"
    result["nextAction"] = None
    return result


def prepare_artifact(
    state: Mapping[str, object],
    files: ProjectFiles,
    *,
    template_path: Path,
) -> dict[str, object]:
    """Render, verify and atomically freeze one immutable approval artifact."""
    candidate = state.get("candidate")
    review_decision = state.get("reviewDecision")
    task_checkpoint = state.get("taskCheckpoint")
    if not all(
        isinstance(value, Mapping)
        for value in (candidate, review_decision, task_checkpoint)
    ):
        return {
            "outcome": "SYSTEM_FAILED",
            "nextAction": None,
            "diagnostics": [
                {
                    "code": "ARTIFACT_INPUT_INVALID",
                    "message": "候选工件缺少 reviewed model、Task checkpoint 或终审决定。",
                    "path": "",
                    "details": {},
                }
            ],
        }
    assert isinstance(candidate, Mapping)
    assert isinstance(review_decision, Mapping)
    assert isinstance(task_checkpoint, Mapping)
    rendered = None
    render_temp_root: Path | None = None
    try:
        run_id = str(state["runId"])
        render_temp_root = files.ensure_dir(
            f"{RUNS_ROOT}/{run_id}/render-temp"
        )
        rendered = _prepare_project_local_draft(
            candidate,
            template_path=Path(template_path),
            review_decision=review_decision,
            temporary_root=render_temp_root,
        )
        audit = getattr(rendered, "workbook_audit", None)
        if (
            audit is None
            or getattr(audit, "trust_state", None) != "VERIFIED"
            or not getattr(audit, "engine_name", None)
            or not getattr(audit, "engine_version", None)
        ):
            raise PackageRenderError(
                "WORKBOOK_VERIFY_FAILED",
                "候选工作簿没有可信的 Office 复读证明。",
            )
        workbook_path = Path(str(getattr(rendered, "workbook_path")))
        notes_path = Path(str(getattr(rendered, "notes_path")))
        workbook_payload = workbook_path.read_bytes()
        notes_payload = notes_path.read_bytes()
        candidate_payload = canonical_json_bytes(candidate)
        review_payload = canonical_json_bytes(review_decision)
        project = candidate.get("project")
        if not isinstance(project, Mapping):
            raise PackageRenderError(
                "ARTIFACT_INPUT_INVALID", "sow-model 缺少 project 绑定。"
            )
        input_revision = state.get("inputRevision")
        effective_policy_decisions = state.get("effectivePolicyDecisions")
        checkpoints = [
            state.get("scopeClosureCheckpoint"),
            state.get("storyAcCheckpoint"),
            state.get("taskCheckpoint"),
        ]
        if not isinstance(input_revision, Mapping) or not isinstance(
            effective_policy_decisions, Mapping
        ) or not all(isinstance(item, Mapping) for item in checkpoints):
            raise PackageRenderError(
                "ARTIFACT_INPUT_INVALID",
                "候选工件缺少自包含的输入、政策或 Stage checkpoint。",
            )
        input_revision_payload = canonical_json_bytes(input_revision)
        policy_payload = canonical_json_bytes(effective_policy_decisions)
        checkpoint_payloads = [
            canonical_json_bytes(item) for item in checkpoints
        ]
        source_manifest_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "sources": input_revision.get("sources", []),
                    "blocks": input_revision.get("blocks", []),
                }
            )
        )
        if (
            project.get("inputRevisionSha256")
            != sha256_bytes(input_revision_payload)
            or project.get("sourceManifestSha256") != source_manifest_sha256
            or task_checkpoint.get("effectivePolicyDecisionSha256")
            != sha256_bytes(policy_payload)
        ):
            raise PackageRenderError(
                "ARTIFACT_INPUT_STALE",
                "候选工件输入、来源或政策 hash 已漂移。",
            )
        stage_hashes = [
            review_decision.get(field)
            for field in (
                "scopeClosureCheckpointSha256",
                "storyAcCheckpointSha256",
                "taskCheckpointSha256",
            )
        ]
        manifest = {
            "contract": "ai-sow-artifact-manifest-v1",
            "runId": state["runId"],
            "candidateSha256": sha256_bytes(candidate_payload),
            "sourceManifestSha256": source_manifest_sha256,
            "stageCheckpointSha256s": stage_hashes,
            "reviewDecisionSha256": sha256_bytes(review_payload),
            "templateSha256": sha256_bytes(Path(template_path).read_bytes()),
            "effectivePolicyDecisionSha256": task_checkpoint[
                "effectivePolicyDecisionSha256"
            ],
            "taskCatalogSemanticSha256": task_checkpoint[
                "taskCatalogSemanticSha256"
            ],
            "taskEstimationMethodSha256": task_checkpoint[
                "taskEstimationMethodSha256"
            ],
            "rendererContract": "generation-renderer-v8",
            "rendererSha256": _renderer_sha256(),
            "workbook": {
                "path": "sow.xlsx",
                "sha256": sha256_bytes(workbook_payload),
            },
            "notes": {
                "path": "sow-notes.md",
                "sha256": sha256_bytes(notes_payload),
            },
            "workbookVerification": {
                "trustState": "VERIFIED",
                "engineName": audit.engine_name,
                "engineVersion": audit.engine_version,
            },
        }
        diagnostics = validate_contract(
            manifest,
            "artifact-approval.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if diagnostics:
            raise PackageRenderError(
                "ARTIFACT_MANIFEST_INVALID",
                "候选工件 manifest 未通过严格合同校验。",
            )
        manifest_payload = canonical_json_bytes(manifest)
        manifest_sha256 = sha256_bytes(manifest_payload)
        artifacts_relative = f"{RUNS_ROOT}/{run_id}/artifacts"
        artifacts_root = files.ensure_dir(artifacts_relative)
        existing_sequences = [
            int(item.name.split("-", 1)[0])
            for item in artifacts_root.iterdir()
            if item.is_dir()
            and re.fullmatch(r"[0-9]{6}-[0-9a-f]{64}", item.name)
        ]
        sequence = max(existing_sequences, default=0) + 1
        version_name = f"{sequence:06d}-{manifest_sha256}"
        version_relative = f"{artifacts_relative}/{version_name}"
        version_path = artifacts_root / version_name
        staging_path = Path(
            tempfile.mkdtemp(prefix=".artifact-stage-", dir=artifacts_root)
        )
        try:
            staging_files = ProjectFiles.open(staging_path)
            for name, payload in (
                ("sow.xlsx", workbook_payload),
                ("sow-notes.md", notes_payload),
                ("sow-model.json", candidate_payload),
                ("input-revision.json", input_revision_payload),
                ("effective-policy-decision.json", policy_payload),
                ("scope-closure-checkpoint.json", checkpoint_payloads[0]),
                ("story-ac-checkpoint.json", checkpoint_payloads[1]),
                ("task-checkpoint.json", checkpoint_payloads[2]),
                ("sow-template.xlsx", Path(template_path).read_bytes()),
                ("review-decision.json", review_payload),
                ("artifact-manifest.json", manifest_payload),
            ):
                staging_files.write_atomic(name, payload)
            os.replace(staging_path, version_path)
        finally:
            if staging_path.exists():
                shutil.rmtree(staging_path)
        manifest_relative = f"{version_relative}/artifact-manifest.json"
        next_action = {
            "contract": "ai-sow-next-action-v1",
            "kind": "REQUEST_APPROVAL",
            "artifactManifestPath": manifest_relative,
            "artifactManifestSha256": manifest_sha256,
        }
        if validate_contract(next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY):
            raise PackageRenderError(
                "ARTIFACT_NEXT_ACTION_INVALID",
                "候选工件的批准动作未通过严格合同校验。",
            )
        return {
            "outcome": "REQUEST_APPROVAL",
            "artifactManifestPath": manifest_relative,
            "artifactManifestSha256": manifest_sha256,
            "workbookPath": f"{version_relative}/sow.xlsx",
            "notesPath": f"{version_relative}/sow-notes.md",
            "summary": (
                "候选 SOW 已完成 LibreOffice 重算和完整复读；"
                f"请审阅候选说明与工作簿。工件版本：{sequence:06d}。"
            ),
            "nextAction": next_action,
            "lowestRecoveryStage": None,
            "diagnostics": [],
        }
    except (PackageRenderError, OSError, KeyError, TypeError, ValueError) as error:
        code = getattr(error, "code", "WORKBOOK_VERIFY_FAILED")
        return {
            "outcome": "SYSTEM_FAILED",
            "nextAction": None,
            "lowestRecoveryStage": "RENDER",
            "diagnostics": [
                {
                    "code": code,
                    "message": str(error),
                    "path": "",
                    "details": {},
                }
            ],
        }
    finally:
        if rendered is not None:
            root = Path(str(getattr(rendered, "root", "")))
            if root.is_dir():
                shutil.rmtree(root)
        if render_temp_root is not None:
            for empty_directory in (
                render_temp_root,
                render_temp_root.parent,
                render_temp_root.parent.parent,
            ):
                try:
                    empty_directory.rmdir()
                except OSError:
                    break


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _diagnostic_value(value: Diagnostic) -> dict[str, object]:
    return {
        "code": value.code,
        "message": value.message,
        "path": value.path,
        "details": dict(value.details),
    }


def _route_diagnostic(value: object) -> Diagnostic | None:
    if isinstance(value, Diagnostic):
        return value
    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    message = value.get("message")
    path = value.get("path")
    details = value.get("details")
    if not (
        isinstance(code, str)
        and code
        and isinstance(message, str)
        and message
        and isinstance(path, str)
        and isinstance(details, Mapping)
    ):
        return None
    return Diagnostic(code=code, message=message, path=path, details=dict(details))


def _semantic_input_sha256(input_revision: Mapping[str, object]) -> str:
    fields = (
        "requestSha256",
        "priorSowState",
        "priorSowSha256s",
        "sources",
        "blocks",
    )
    if any(field not in input_revision for field in fields):
        raise ValueError("input revision 缺少语义路由字段")
    semantic = {field: input_revision[field] for field in fields}
    sources = input_revision.get("sources")
    if not isinstance(sources, list):
        raise ValueError("input revision sources 合同无效")
    semantic["sources"] = [
        {key: value for key, value in source.items() if key != "path"}
        if isinstance(source, Mapping)
        else source
        for source in sources
    ]
    return sha256_bytes(canonical_json_bytes(semantic))


def _current_routing_basis(
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
) -> dict[str, str]:
    if (
        state.get("contract") != ROUTE_CONTEXT_CONTRACT
        or set(state) != ROUTE_CONTEXT_FIELDS
    ):
        raise ValueError("route context 合同无效")
    checkpoints = state.get("checkpointSha256s")
    if not isinstance(checkpoints, Mapping):
        raise ValueError("route context 缺少 checkpoint hashes")
    basis: dict[str, object] = {
        "semanticInputSha256": _semantic_input_sha256(input_revision),
        "templateSha256": input_revision.get("templateSha256"),
        "deliveryPolicySha256": input_revision.get("deliveryPolicySha256"),
        "executionPolicySha256": input_revision.get("executionPolicySha256"),
        "taskCatalogSemanticSha256": state.get("taskCatalogSemanticSha256"),
        "taskEstimationMethodSha256": state.get("taskEstimationMethodSha256"),
        "rendererSha256": state.get("rendererSha256"),
        "effectivePolicyDecisionSha256": state.get(
            "effectivePolicyDecisionSha256"
        ),
        "scopeClosureCheckpointSha256": checkpoints.get("SCOPE_CLOSURE"),
        "storyAcCheckpointSha256": checkpoints.get("STORY_AC"),
        "taskCheckpointSha256": checkpoints.get("TASK"),
        "reviewDecisionSha256": state.get("reviewDecisionSha256"),
    }
    if set(basis) != ROUTING_BASIS_FIELDS or any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in basis.values()
    ):
        raise ValueError("route context hash 不完整或格式无效")
    return {key: str(value) for key, value in basis.items()}


def _valid_generation_proof_closure(
    current_generation: Mapping[str, object],
) -> bool:
    if (
        set(current_generation)
        != {
            "contract",
            "generationContract",
            "generationId",
            "publicationComplete",
            "selfContained",
            "routingBasis",
            "proofClosure",
        }
        or current_generation.get("contract") != GENERATION_PROOF_CLOSURE_CONTRACT
        or current_generation.get("generationContract")
        != GENERATION_MANIFEST_CONTRACT
        or current_generation.get("publicationComplete") is not True
        or current_generation.get("selfContained") is not True
    ):
        return False
    basis = current_generation.get("routingBasis")
    closure = current_generation.get("proofClosure")
    if not (
        isinstance(basis, Mapping)
        and set(basis) == ROUTING_BASIS_FIELDS
        and all(
            isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value) is not None
            for value in basis.values()
        )
        and isinstance(closure, Mapping)
        and set(closure) == {"stageCheckpoints", "reviewDecision", "artifactManifest"}
    ):
        return False
    checkpoints = closure.get("stageCheckpoints")
    review = closure.get("reviewDecision")
    artifact = closure.get("artifactManifest")
    checkpoint_basis_fields = {
        "SCOPE_CLOSURE": "scopeClosureCheckpointSha256",
        "STORY_AC": "storyAcCheckpointSha256",
        "TASK": "taskCheckpointSha256",
    }
    if not isinstance(checkpoints, Mapping) or set(checkpoints) != set(
        checkpoint_basis_fields
    ):
        return False
    for kind, basis_field in checkpoint_basis_fields.items():
        checkpoint = checkpoints.get(kind)
        if not (
            isinstance(checkpoint, Mapping)
            and set(checkpoint) == {"sha256", "decision"}
            and checkpoint.get("decision") == "PASS"
            and checkpoint.get("sha256") == basis[basis_field]
        ):
            return False
    return bool(
        isinstance(review, Mapping)
        and set(review) == {"sha256", "decision"}
        and review.get("decision") == "PASS"
        and review.get("sha256") == basis["reviewDecisionSha256"]
        and isinstance(artifact, Mapping)
        and set(artifact) == {"sha256", "verified"}
        and artifact.get("verified") is True
        and isinstance(artifact.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", str(artifact["sha256"])) is not None
    )


def _route_decision(
    *,
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
    current_generation: Mapping[str, object] | None,
    route: str,
    lowest_recovery_stage: str | None,
    changed: Sequence[str],
    reused: Sequence[str],
    invalidated: Sequence[str],
    diagnostics: Sequence[Diagnostic] = (),
    legacy_generation_contract: str | None = None,
) -> RouteDecision:
    decision_value = {
        "route": route,
        "lowestRecoveryStage": lowest_recovery_stage,
        "changed": list(changed),
        "reused": list(reused),
        "invalidated": list(invalidated),
        "diagnostics": [_diagnostic_value(item) for item in diagnostics],
    }
    generation_evidence: object
    if legacy_generation_contract is not None:
        generation_evidence = {"contract": legacy_generation_contract}
    else:
        generation_evidence = current_generation
    proof_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "contract": "ai-sow-route-decision-proof-v1",
                "state": state,
                "inputRevision": input_revision,
                "currentGeneration": generation_evidence,
                "decision": decision_value,
            }
        )
    )
    return RouteDecision(
        route=route,  # type: ignore[arg-type]
        lowest_recovery_stage=lowest_recovery_stage,  # type: ignore[arg-type]
        changed=tuple(changed),
        reused=tuple(reused),
        invalidated=tuple(invalidated),
        diagnostics=tuple(diagnostics),
        proof_sha256=proof_sha256,
    )


def plan_route(
    state: Mapping[str, object],
    input_revision: Mapping[str, object],
    current_generation: Mapping[str, object] | None,
) -> RouteDecision:
    """Choose one immutable route from hashes and a self-contained proof closure."""
    input_diagnostic_values = state.get("inputDiagnostics")
    if isinstance(input_diagnostic_values, Sequence) and not isinstance(
        input_diagnostic_values, (str, bytes)
    ):
        input_diagnostics = tuple(
            diagnostic
            for value in input_diagnostic_values
            if (diagnostic := _route_diagnostic(value)) is not None
        )
        if input_diagnostics:
            return _route_decision(
                state=state,
                input_revision=input_revision,
                current_generation=current_generation,
                route="FULL_COMPILE",
                lowest_recovery_stage=None,
                changed=(),
                reused=(),
                invalidated=(),
                diagnostics=input_diagnostics,
            )

    if current_generation is None:
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=None,
            route="FULL_COMPILE",
            lowest_recovery_stage="STAGE_1",
            changed=("generationProofClosure",),
            reused=(),
            invalidated=FULL_COMPILE_INVALIDATIONS,
        )

    generation_contract = current_generation.get("contract")
    if generation_contract != GENERATION_PROOF_CLOSURE_CONTRACT:
        contract_name = (
            generation_contract if isinstance(generation_contract, str) else "INVALID"
        )
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=None,
            route="FULL_COMPILE",
            lowest_recovery_stage="STAGE_1",
            changed=("generationProofClosure",),
            reused=(),
            invalidated=FULL_COMPILE_INVALIDATIONS,
            legacy_generation_contract=contract_name,
        )

    if not _valid_generation_proof_closure(current_generation):
        diagnostic = _diagnostic(
            "GENERATION_PROOF_CLOSURE_INVALID",
            "已发布 generation 的自包含检查点、评审或工件证明无效。",
            "/currentGeneration",
        )
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=current_generation,
            route="FULL_COMPILE",
            lowest_recovery_stage="STAGE_1",
            changed=("generationProofClosure",),
            reused=(),
            invalidated=FULL_COMPILE_INVALIDATIONS,
            diagnostics=(diagnostic,),
        )

    try:
        current_basis = _current_routing_basis(state, input_revision)
    except (TypeError, ValueError):
        diagnostic = _diagnostic(
            "ROUTE_CONTEXT_INVALID",
            "当前输入或路由 hash 上下文不完整。",
            "/routeContext",
        )
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=current_generation,
            route="FULL_COMPILE",
            lowest_recovery_stage="STAGE_1",
            changed=("routeContext",),
            reused=(),
            invalidated=FULL_COMPILE_INVALIDATIONS,
            diagnostics=(diagnostic,),
        )
    baseline_basis = current_generation["routingBasis"]
    changed = tuple(
        sorted(
            field
            for field in ROUTING_BASIS_FIELDS
            if current_basis[field] != baseline_basis[field]
        )
    )
    reused = tuple(sorted(ROUTING_BASIS_FIELDS.difference(changed)))
    if not changed:
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=current_generation,
            route="REUSE",
            lowest_recovery_stage=None,
            changed=(),
            reused=reused,
            invalidated=(),
        )

    if "executionPolicySha256" in changed:
        diagnostic = _diagnostic(
            "ROUTE_HASH_DRIFT_UNSUPPORTED",
            "执行政策变化不能由既有语义证明安全局部恢复。",
            "/inputRevision/executionPolicySha256",
        )
        return _route_decision(
            state=state,
            input_revision=input_revision,
            current_generation=current_generation,
            route="FULL_COMPILE",
            lowest_recovery_stage="STAGE_1",
            changed=changed,
            reused=reused,
            invalidated=FULL_COMPILE_INVALIDATIONS,
            diagnostics=(diagnostic,),
        )

    recovery_stages = tuple(ROUTE_RECOVERY_STAGE[field] for field in changed)
    lowest_recovery_stage = min(
        recovery_stages,
        key=lambda stage: ROUTE_STAGE_RANK[stage],
    )
    render_only = set(changed).issubset({"templateSha256", "rendererSha256"})
    return _route_decision(
        state=state,
        input_revision=input_revision,
        current_generation=current_generation,
        route="RENDER_ONLY" if render_only else "DELTA_COMPILE",
        lowest_recovery_stage=lowest_recovery_stage,
        changed=changed,
        reused=reused,
        invalidated=ROUTE_INVALIDATIONS[lowest_recovery_stage],
    )


def _input_revision_by_sha256(
    files: ProjectFiles, expected_sha256: str
) -> tuple[str, Mapping[str, object]]:
    try:
        root = files.resolve(".ai-sow/inputs/revisions", expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            raise ProjectIOError(
                "INPUT_REVISION_NOT_FOUND",
                ".ai-sow/inputs/revisions",
                "已发布 generation 绑定的 Input Revision 不存在。",
            ) from error
        raise
    matches: list[tuple[str, Mapping[str, object]]] = []
    for path in sorted(root.glob("revision-*/manifest.json")):
        relative = path.relative_to(files.root).as_posix()
        payload = files.read_bytes(relative)
        if sha256_bytes(payload) == expected_sha256:
            matches.append((relative, _mapping(files, relative)))
    if len(matches) != 1:
        raise ProjectIOError(
            "INPUT_REVISION_NOT_UNIQUE",
            ".ai-sow/inputs/revisions",
            "已发布 generation 必须唯一绑定一个不可变 Input Revision。",
        )
    return matches[0]


def _generation_route_materials(
    files: ProjectFiles,
    current: object,
) -> dict[str, object]:
    manifest_path = str(getattr(current, "manifest_path"))
    manifest = _mapping(files, manifest_path)
    generation_root = Path(manifest_path).parent.as_posix()
    input_revision_path, input_revision = _input_revision_by_sha256(
        files, str(manifest["inputRevisionSha256"])
    )
    checkpoint_names = (
        ("SCOPE_CLOSURE", "scope-closure-checkpoint.json"),
        ("STORY_AC", "story-ac-checkpoint.json"),
        ("TASK", "task-checkpoint.json"),
    )
    checkpoints = {
        kind: _mapping(files, f"{generation_root}/proof/{name}")
        for kind, name in checkpoint_names
    }
    checkpoint_hashes = {
        kind: sha256_bytes(canonical_json_bytes(checkpoint))
        for kind, checkpoint in checkpoints.items()
    }
    review_decision = _mapping(files, f"{generation_root}/proof/review-decision.json")
    review_sha256 = sha256_bytes(canonical_json_bytes(review_decision))
    artifact_manifest = _mapping(
        files, f"{generation_root}/proof/artifact-manifest.json"
    )
    artifact_sha256 = sha256_bytes(canonical_json_bytes(artifact_manifest))
    proof = {
        "contract": GENERATION_PROOF_CLOSURE_CONTRACT,
        "generationContract": manifest["contract"],
        "generationId": manifest["generationId"],
        "publicationComplete": manifest["publicationComplete"],
        "selfContained": True,
        "routingBasis": {
            "semanticInputSha256": _semantic_input_sha256(input_revision),
            "templateSha256": manifest["templateSha256"],
            "deliveryPolicySha256": input_revision["deliveryPolicySha256"],
            "executionPolicySha256": input_revision["executionPolicySha256"],
            "taskCatalogSemanticSha256": artifact_manifest[
                "taskCatalogSemanticSha256"
            ],
            "taskEstimationMethodSha256": artifact_manifest[
                "taskEstimationMethodSha256"
            ],
            "rendererSha256": artifact_manifest["rendererSha256"],
            "effectivePolicyDecisionSha256": artifact_manifest[
                "effectivePolicyDecisionSha256"
            ],
            "scopeClosureCheckpointSha256": checkpoint_hashes["SCOPE_CLOSURE"],
            "storyAcCheckpointSha256": checkpoint_hashes["STORY_AC"],
            "taskCheckpointSha256": checkpoint_hashes["TASK"],
            "reviewDecisionSha256": review_sha256,
        },
        "proofClosure": {
            "stageCheckpoints": {
                kind: {"sha256": checkpoint_hashes[kind], "decision": checkpoint["decision"]}
                for kind, checkpoint in checkpoints.items()
            },
            "reviewDecision": {
                "sha256": review_sha256,
                "decision": review_decision["decision"],
            },
            "artifactManifest": {
                "sha256": artifact_sha256,
                "verified": artifact_manifest.get("workbookVerification", {}).get(
                    "trustState"
                )
                == "VERIFIED",
            },
        },
    }
    return {
        "manifest": manifest,
        "generationRoot": generation_root,
        "inputRevisionPath": input_revision_path,
        "inputRevision": input_revision,
        "candidate": _mapping(files, str(manifest["sowModelPath"])),
        "checkpoints": checkpoints,
        "reviewDecision": review_decision,
        "artifactManifest": artifact_manifest,
        "effectivePolicyDecisions": _mapping(
            files, f"{generation_root}/input/effective-policy-decision.json"
        ),
        "proof": proof,
    }


def _route_context_for_revision(
    files: ProjectFiles,
    input_revision_path: str,
    input_revision: Mapping[str, object],
    materials: Mapping[str, object],
) -> dict[str, object]:
    proof = materials["proof"]
    assert isinstance(proof, Mapping)
    basis = proof["routingBasis"]
    assert isinstance(basis, Mapping)
    template_path = files.resolve(
        f"{Path(input_revision_path).parent.as_posix()}/sow-template.xlsx",
        expect="file",
    )
    task_catalog = load_task_standard_catalog(template_path)
    return {
        "contract": ROUTE_CONTEXT_CONTRACT,
        "taskCatalogSemanticSha256": task_catalog.task_catalog_semantic_sha256,
        "taskEstimationMethodSha256": sha256_bytes(
            (SKILL_ROOT / "references/task-authoring.md").read_bytes()
        ),
        "rendererSha256": _renderer_sha256(),
        "effectivePolicyDecisionSha256": basis[
            "effectivePolicyDecisionSha256"
        ],
        "checkpointSha256s": {
            "SCOPE_CLOSURE": basis["scopeClosureCheckpointSha256"],
            "STORY_AC": basis["storyAcCheckpointSha256"],
            "TASK": basis["taskCheckpointSha256"],
        },
        "reviewDecisionSha256": basis["reviewDecisionSha256"],
        "inputDiagnostics": [],
    }


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _result(
    outcome: str,
    summary: str,
    *,
    diagnostics: Sequence[Diagnostic] = (),
    **values: object,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "summary": summary,
        "diagnostics": [_diagnostic_value(item) for item in diagnostics],
        **values,
    }


def _blocked(code: str, message: str, path: str = "") -> dict[str, object]:
    return _result("BLOCKED", message, diagnostics=(_diagnostic(code, message, path),))


def _optional_json(files: ProjectFiles, path: str) -> object | None:
    try:
        return files.read_json(path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    value = files.read_json(path)
    if not isinstance(value, Mapping):
        raise ProjectIOError("PROJECT_CONTRACT_INVALID", path, "JSON 必须是对象。")
    return value


def _input_mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    if Path(path).is_absolute():
        try:
            relative = Path(path).resolve().relative_to(files.root).as_posix()
        except ValueError as error:
            raise ProjectIOError(
                "PROJECT_PATH_OUTSIDE_ROOT", path, "候选文件必须位于项目目录内。"
            ) from error
    else:
        relative = path
    return _mapping(files, relative)


def _managed_request_path(files: ProjectFiles, request_path: str) -> str:
    candidate = Path(request_path)
    if candidate.is_absolute():
        try:
            relative_path = candidate.absolute().relative_to(files.root).as_posix()
        except ValueError as error:
            raise ProjectIOError(
                "PROJECT_PATH_OUTSIDE_ROOT",
                request_path,
                "request 必须位于项目目录内。",
            ) from error
    else:
        relative_path = request_path
    files.resolve(relative_path, expect="file")
    return relative_path


def _run_paths(run_id: str) -> tuple[str, str, str]:
    if not isinstance(run_id, str) or not re.fullmatch(r"run-[0-9a-f]{12}", run_id):
        raise ProjectIOError("RUN_ID_INVALID", str(run_id), "run ID 格式无效。")
    root = f"{RUNS_ROOT}/{run_id}"
    return root, f"{root}/state.json", f"{root}/input-binding.json"


def _state_snapshot_path(run_id: str, state_sha256: str) -> str:
    root, _, _ = _run_paths(run_id)
    if re.fullmatch(r"[0-9a-f]{64}", state_sha256) is None:
        raise ProjectIOError(
            "RUN_STATE_HASH_INVALID", state_sha256, "run state hash 格式无效。"
        )
    return f"{root}/states/state-{state_sha256}.json"


def _active_marker_value(
    *,
    run_id: str,
    request_path: str,
    request_sha256: str,
    input_revision_sha256: str,
    input_revision_path: str,
) -> dict[str, object]:
    _, state_path, binding_path = _run_paths(run_id)
    return {
        "runId": run_id,
        "requestPath": request_path,
        "requestSha256": request_sha256,
        "inputRevisionSha256": input_revision_sha256,
        "inputRevisionPath": input_revision_path,
        "statePath": state_path,
        "bindingPath": binding_path,
        "status": "RESERVED",
        "stateSha256": None,
    }


def _read_active_marker(files: ProjectFiles) -> Mapping[str, object] | None:
    try:
        value = files.read_json(ACTIVE_RUN_PATH)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    required = {
        "runId",
        "requestPath",
        "requestSha256",
        "inputRevisionSha256",
        "inputRevisionPath",
        "statePath",
        "bindingPath",
        "status",
        "stateSha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "active run marker 结构无效。",
        )
    run_id = value.get("runId")
    run_root, initial_state_path, expected_binding_path = _run_paths(str(run_id))
    state_path = value.get("statePath")
    state_path_valid = state_path == initial_state_path or (
        isinstance(state_path, str)
        and re.fullmatch(
            rf"{re.escape(run_root)}/states/state-[0-9a-f]{{64}}\.json",
            state_path,
        )
        is not None
    )
    sha_fields = (value.get("requestSha256"), value.get("inputRevisionSha256"))
    input_revision_path = value.get("inputRevisionPath")
    if (
        not all(
            isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)
            for item in sha_fields
        )
        or not isinstance(input_revision_path, str)
        or re.fullmatch(
            r"\.ai-sow/inputs/revisions/revision-[0-9a-f]{16}/manifest\.json",
            input_revision_path,
        )
        is None
        or not state_path_valid
        or value.get("bindingPath") != expected_binding_path
        or value.get("status") not in {"RESERVED", "ACTIVE"}
        or not isinstance(value.get("requestPath"), str)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "active run marker 绑定无效。",
        )
    state_sha256 = value.get("stateSha256")
    if value.get("status") == "RESERVED" and state_sha256 is not None:
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "预留中的 active run 不得提前绑定 state hash。",
        )
    if value.get("status") == "ACTIVE" and not (
        isinstance(state_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", state_sha256)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "已激活的 active run 必须绑定 state hash。",
        )
    if value.get("status") == "ACTIVE" and state_path != _state_snapshot_path(
        str(run_id), str(state_sha256)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "已激活的 active run 必须指向内容寻址 state snapshot。",
        )
    return value


def _initial_run_state(marker: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract": "ai-sow-run-state-v1",
        "runId": marker["runId"],
        "requestSha256": marker["requestSha256"],
        "route": "FULL_COMPILE",
        "phase": "PREPARE",
        "wait": "NONE",
        "result": None,
        "currentInputRevisionSha256": marker["inputRevisionSha256"],
        "currentCandidateSha256": None,
        "currentCandidatePath": None,
        "expectedActionIds": [],
        "checkpointRefs": [],
        "budget": {
            "executionPolicySha256": EXECUTION_POLICY_SHA256,
            "modelActionsStarted": 0,
            "modelActionsCompleted": 0,
        },
        "resumeFromPhase": None,
    }


def _input_binding(marker: Mapping[str, object]) -> dict[str, object]:
    return {
        "runId": marker["runId"],
        "requestPath": marker["requestPath"],
        "requestSha256": marker["requestSha256"],
        "inputRevisionSha256": marker["inputRevisionSha256"],
        "inputRevisionPath": marker["inputRevisionPath"],
    }


def _validated_run_state(value: object, path: str) -> Mapping[str, object]:
    diagnostics = validate_state_combination(value, NEXT_SCHEMA_REGISTRY)
    if diagnostics or not isinstance(value, Mapping):
        raise ProjectIOError("RUN_STATE_INVALID", path, "run state 合同无效。")
    return value


def _recover_active_run(
    files: ProjectFiles,
    marker: Mapping[str, object],
    *,
    verify_request: bool = True,
) -> Mapping[str, object]:
    request_path = str(marker["requestPath"])
    if (
        verify_request
        and sha256_bytes(files.read_bytes(request_path)) != marker["requestSha256"]
    ):
        raise ProjectIOError(
            "RUN_REQUEST_BINDING_STALE",
            request_path,
            "active run 绑定的 request 已变化。",
        )
    input_revision_path = str(marker["inputRevisionPath"])
    if (
        sha256_bytes(files.read_bytes(input_revision_path))
        != marker["inputRevisionSha256"]
    ):
        raise ProjectIOError(
            "RUN_INPUT_REVISION_HASH_MISMATCH",
            input_revision_path,
            "active run 绑定的 Input Revision 已变化。",
        )

    state_path = str(marker["statePath"])
    expected_state = _initial_run_state(marker)
    try:
        state = _validated_run_state(files.read_json(state_path), state_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING" or marker["status"] != "RESERVED":
            raise
        files.publish_new(state_path, canonical_json_bytes(expected_state))
        state = expected_state
    if (
        state.get("runId") != marker["runId"]
        or state.get("requestSha256") != marker["requestSha256"]
        or state.get("currentInputRevisionSha256") != marker["inputRevisionSha256"]
    ):
        raise ProjectIOError(
            "RUN_STATE_BINDING_INVALID",
            state_path,
            "run state 与 active marker 绑定不一致。",
        )

    binding_path = str(marker["bindingPath"])
    expected_binding = _input_binding(marker)
    try:
        binding = files.read_json(binding_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING" or marker["status"] != "RESERVED":
            raise
        files.publish_new(binding_path, canonical_json_bytes(expected_binding))
        binding = expected_binding
    if binding != expected_binding:
        raise ProjectIOError(
            "RUN_INPUT_BINDING_INVALID",
            binding_path,
            "run input binding 与 active marker 不一致。",
        )

    state_payload = files.read_bytes(state_path)
    state_sha256 = sha256_bytes(state_payload)
    if marker["status"] == "ACTIVE":
        if marker["stateSha256"] != state_sha256:
            raise ProjectIOError(
                "RUN_STATE_HASH_MISMATCH",
                state_path,
                "active marker 未绑定当前 run state。",
            )
        reconciled = _reconcile_active_state(files, marker, state)
        if (
            reconciled.get("phase") == "DONE"
            and reconciled.get("result") == "ABANDONED"
        ):
            current_marker = _read_active_marker(files)
            if current_marker is not None and current_marker.get("runId") == marker.get(
                "runId"
            ):
                active_payload = files.read_bytes(ACTIVE_RUN_PATH)
                files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
        return reconciled

    return _write_active_state(files, marker, state)


def _active_result(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "outcome": "ACTIVE",
        "state": dict(state),
        "diagnostics": [],
    }


def _source_contents_for_revision(
    files: ProjectFiles,
    input_revision_path: str,
    input_revision: Mapping[str, object],
) -> dict[str, str]:
    revision_root = str(Path(input_revision_path).parent.as_posix())
    contents: dict[str, str] = {}
    for block in _mappings(input_revision.get("blocks")):
        block_id = block.get("blockId")
        if not isinstance(block_id, str):
            raise ProjectIOError(
                "INPUT_REVISION_INVALID",
                input_revision_path,
                "Input Revision block 缺少 blockId。",
            )
        value = _mapping(files, f"{revision_root}/blocks/{block_id}.json")
        content = value.get("content")
        if (
            not isinstance(content, str)
            or sha256_bytes(content.encode("utf-8")) != block.get("contentSha256")
        ):
            raise ProjectIOError(
                "INPUT_REVISION_BLOCK_HASH_MISMATCH",
                f"{revision_root}/blocks/{block_id}.json",
                "Input Revision block 正文与 manifest hash 不一致。",
            )
        contents[block_id] = content
    return contents


def _next_model_action(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> Mapping[str, object] | None:
    action_ids = [
        item for item in state.get("expectedActionIds", []) if isinstance(item, str)
    ]
    if state.get("wait") != "MODEL" or not action_ids:
        return None
    envelopes = [
        _mapping(files, _action_paths(str(state["runId"]), action_id)["envelope"])
        for action_id in action_ids
    ]
    if len(envelopes) == 1:
        return envelopes[0]
    group = envelopes[0]["group"]
    assert isinstance(group, Mapping)
    next_action = {
        "contract": "ai-sow-next-action-v1",
        "kind": "MODEL_ACTION_GROUP",
        "groupId": group["groupId"],
        "maxConcurrency": group["maxConcurrency"],
        "groupDeadlineMilliseconds": group["groupDeadlineMilliseconds"],
        "actions": envelopes,
    }
    if validate_contract(next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "NEXT_ACTION_INVALID", "", "已持久化的 MODEL_ACTION_GROUP 合同无效。"
        )
    return next_action


def _public_active_result(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> dict[str, object]:
    return {
        "outcome": "ACTIVE",
        "state": dict(state),
        "nextAction": _next_model_action(files, state),
        "diagnostics": [],
    }


def _start_public_pipeline(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> dict[str, object]:
    """Freeze the first host-neutral action without invoking a model runtime."""
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "当前项目没有 active run。"
        )
    current = dict(state)
    if current.get("phase") != "PREPARE" or current.get("wait") != "NONE":
        return _public_active_result(files, current)
    input_revision_path = str(marker["inputRevisionPath"])
    input_revision = _mapping(files, input_revision_path)
    revision_root = str(Path(input_revision_path).parent.as_posix())
    request = _mapping(files, f"{revision_root}/request.json")
    if current.get("route") == "DELTA_COMPILE" and isinstance(
        current.get("currentCandidatePath"), str
    ):
        candidate = _mapping(files, str(current["currentCandidatePath"]))
        snapshot = {
            "path": current["currentCandidatePath"],
            "sha256": current["currentCandidateSha256"],
        }
    else:
        candidate = model_skeleton(request, input_revision)
        snapshot = _append_candidate_snapshot(files, str(marker["runId"]), candidate)
    compiler_state = {
        "contract": "ai-sow-scope-compiler-state-v1",
        "runId": marker["runId"],
        "inputRevision": input_revision,
        "sourceContents": _source_contents_for_revision(
            files, input_revision_path, input_revision
        ),
        "baseCandidate": candidate,
        "baseCandidateSha256": snapshot["sha256"],
        "maxInitialPacketTokens": 48000,
        "maxOutputTokens": 12000,
        "modelProfileId": "host-selected-author-v1",
        "modelConfigSha256": sha256_bytes(
            canonical_json_bytes(
                {
                    "contract": "ai-sow-host-model-selection-v1",
                    "selection": "HOST_DEFAULT",
                    "contextPolicy": "FRESH_NO_HISTORY",
                }
            )
        ),
        "acceptedRecords": [],
    }
    prepared = prepare_scope_action(compiler_state, "SOURCE_SCAN")
    if prepared.get("outcome") != "ACTION_REQUIRED":
        diagnostics = tuple(
            item
            for item in prepared.get("diagnostics", ())
            if isinstance(item, (Diagnostic, Mapping))
        )
        return {
            "outcome": str(prepared.get("outcome", "CONTRACT_UNSUPPORTED")),
            "nextAction": None,
            "diagnostics": [
                _diagnostic_value(item)
                if isinstance(item, Diagnostic)
                else dict(item)
                for item in diagnostics
            ],
        }
    specs = _mappings(prepared.get("specs"))
    _issue_action_group(
        files,
        str(marker["runId"]),
        specs,
        max_concurrency=min(4, len(specs)),
        group_deadline_milliseconds=600000,
        shard_deadline_milliseconds=480000,
        pipeline_step="SOURCE_SCAN",
    )
    active = _read_active_marker(files)
    if active is None:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "发放 action 后 active run 意外缺失。"
        )
    return _public_active_result(files, _recover_active_run(files, active))


def _pipeline_plans(
    files: ProjectFiles, run_id: str
) -> list[Mapping[str, object]]:
    try:
        groups_root = files.resolve(f"{RUNS_ROOT}/{run_id}/groups", expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return []
        raise
    invalidated_group_ids = {
        str(group_id)
        for transition in _exclusion_transitions(files, run_id)
        for group_id in transition["invalidatedGroupIds"]
    }
    plans: list[Mapping[str, object]] = []
    for path in groups_root.glob("*/plan.json"):
        relative = path.relative_to(files.root).as_posix()
        plan = _mapping(files, relative)
        if (
            plan.get("contract") != "ai-sow-pipeline-action-plan-v1"
            or plan.get("groupId") != path.parent.name
            or not isinstance(plan.get("pipelineStep"), str)
            or not isinstance(plan.get("sequence"), int)
            or not isinstance(plan.get("actionIds"), list)
        ):
            raise ProjectIOError(
                "PIPELINE_PLAN_INVALID", relative, "pipeline action plan 结构无效。"
            )
        if str(plan["groupId"]) in invalidated_group_ids:
            continue
        plans.append(plan)
    return sorted(plans, key=lambda item: (int(item["sequence"]), str(item["groupId"])))


def _exclusion_transitions(
    files: ProjectFiles, run_id: str
) -> list[Mapping[str, object]]:
    root_path = f"{RUNS_ROOT}/{run_id}/invalidations"
    try:
        root = files.resolve(root_path, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return []
        raise
    transitions: list[Mapping[str, object]] = []
    for path in sorted(root.glob("exclusion-*.json")):
        relative = path.relative_to(files.root).as_posix()
        value = _mapping(files, relative)
        required = {
            "contract",
            "runId",
            "decisionSha256",
            "artifactManifestSha256",
            "baseCandidateSha256",
            "candidatePath",
            "candidateSha256",
            "invalidatedGroupIds",
        }
        if (
            set(value) != required
            or value.get("contract") != "ai-sow-exclusion-transition-v1"
            or value.get("runId") != run_id
            or not isinstance(value.get("invalidatedGroupIds"), list)
            or any(
                not isinstance(item, str)
                for item in value.get("invalidatedGroupIds", [])
            )
        ):
            raise ProjectIOError(
                "EXCLUSION_TRANSITION_INVALID",
                relative,
                "exclusion transition 结构无效。",
            )
        candidate_path = str(value["candidatePath"])
        candidate_payload = files.read_bytes(candidate_path)
        if sha256_bytes(candidate_payload) != value.get("candidateSha256"):
            raise ProjectIOError(
                "EXCLUSION_TRANSITION_INVALID",
                candidate_path,
                "exclusion transition 绑定的 candidate 已变化。",
            )
        transitions.append(value)
    return transitions


def _materialize_pending_exclusion_transition(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> None:
    run_id = str(state["runId"])
    decisions_root = f"{RUNS_ROOT}/{run_id}/decisions"
    try:
        root = files.resolve(decisions_root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return
        raise
    existing_hashes = {
        str(item["decisionSha256"])
        for item in _exclusion_transitions(files, run_id)
    }
    for path in sorted(root.glob("exclusion-*.json")):
        relative = path.relative_to(files.root).as_posix()
        decision = _mapping(files, relative)
        payload = canonical_json_bytes(decision)
        decision_sha256 = sha256_bytes(payload)
        if (
            path.name != f"exclusion-{decision_sha256}.json"
            or decision.get("decision") != "EXCLUDE_DEFAULT_AUTOMATION"
            or validate_contract(
                decision, "artifact-approval.schema.json", NEXT_SCHEMA_REGISTRY
            )
        ):
            raise ProjectIOError(
                "EXCLUSION_DECISION_INVALID", relative, "排除决定合同或文件名无效。"
            )
        if decision_sha256 in existing_hashes:
            continue
        if decision.get("candidateSha256") != state.get("currentCandidateSha256"):
            continue
        candidate_path = (
            f"{RUNS_ROOT}/{run_id}/revisions/exclusion-{decision_sha256}/"
            "sow-model.json"
        )
        candidate_payload = files.read_bytes(candidate_path)
        suffix_steps = {
            "STORY_AC",
            "TASK",
            "STORY_DESIGN",
            "STORY_DESIGN_THEME_JOIN",
            "TASK_ESTIMATION",
            "TASK_ESTIMATION_THEME_JOIN",
            "ADJUDICATION",
        }
        invalidated_group_ids = [
            str(plan["groupId"])
            for plan in _pipeline_plans(files, run_id)
            if plan.get("pipelineStep") in suffix_steps
        ]
        transition = {
            "contract": "ai-sow-exclusion-transition-v1",
            "runId": run_id,
            "decisionSha256": decision_sha256,
            "artifactManifestSha256": decision["artifactManifestSha256"],
            "baseCandidateSha256": decision["candidateSha256"],
            "candidatePath": candidate_path,
            "candidateSha256": sha256_bytes(candidate_payload),
            "invalidatedGroupIds": invalidated_group_ids,
        }
        files.publish_new(
            f"{RUNS_ROOT}/{run_id}/invalidations/exclusion-{decision_sha256}.json",
            canonical_json_bytes(transition),
        )


def _pending_abandon_decision(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> bool:
    root_path = f"{RUNS_ROOT}/{state['runId']}/decisions"
    try:
        root = files.resolve(root_path, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return False
        raise
    for path in sorted(root.glob("abandon-*.json")):
        relative = path.relative_to(files.root).as_posix()
        decision = _mapping(files, relative)
        payload = canonical_json_bytes(decision)
        if (
            path.name != f"abandon-{sha256_bytes(payload)}.json"
            or decision.get("decision") != "ABANDON"
            or validate_contract(
                decision, "artifact-approval.schema.json", NEXT_SCHEMA_REGISTRY
            )
        ):
            raise ProjectIOError(
                "ABANDON_DECISION_INVALID", relative, "放弃决定合同或文件名无效。"
            )
        if decision.get("candidateSha256") == state.get("currentCandidateSha256"):
            return True
    return False


def _plan_applied(files: ProjectFiles, run_id: str, plan: Mapping[str, object]) -> bool:
    return _optional_json(
        files, f"{RUNS_ROOT}/{run_id}/groups/{plan['groupId']}/applied.json"
    ) is not None


def _plan_records(
    files: ProjectFiles,
    run_id: str,
    plan: Mapping[str, object],
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for action_id in plan["actionIds"]:
        record = _optional_json(files, _action_paths(run_id, str(action_id))["record"])
        if not isinstance(record, Mapping) or record.get("status") != "SUCCESS":
            raise ProjectIOError(
                "ACTION_GROUP_INCOMPLETE",
                f"{RUNS_ROOT}/{run_id}/groups/{plan['groupId']}",
                "pipeline group 缺少已封存的成功 ActionRecord。",
            )
        result_path = record.get("resultPath")
        submission_sha256 = record.get("submissionSha256")
        if not isinstance(result_path, str) or not isinstance(submission_sha256, str):
            raise ProjectIOError(
                "ACTION_RECORD_INVALID",
                _action_paths(run_id, str(action_id))["record"],
                "成功 ActionRecord 缺少 submission 引用。",
            )
        submission_payload = files.read_bytes(result_path)
        if sha256_bytes(submission_payload) != submission_sha256:
            raise ProjectIOError(
                "ACTION_SUBMISSION_HASH_MISMATCH",
                result_path,
                "ActionRecord 绑定的 submission 已变化。",
            )
        try:
            submission = json.loads(submission_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectIOError(
                "ACTION_SUBMISSION_INVALID",
                result_path,
                "ActionRecord 绑定的 submission 不是有效 JSON。",
            ) from error
        hydrated = {**record, "submission": submission}
        if validate_contract(hydrated, "action.schema.json", NEXT_SCHEMA_REGISTRY):
            raise ProjectIOError(
                "ACTION_RECORD_INVALID",
                _action_paths(run_id, str(action_id))["record"],
                "装载 submission 后的 ActionRecord 合同无效。",
            )
        records.append(hydrated)
    return records


def _records_for_step(
    files: ProjectFiles,
    run_id: str,
    plans: Sequence[Mapping[str, object]],
    step: str,
    *,
    applied_only: bool = True,
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for plan in plans:
        if plan.get("pipelineStep") != step:
            continue
        if applied_only and not _plan_applied(files, run_id, plan):
            continue
        records.extend(_plan_records(files, run_id, plan))
    return records


def _review_wrappers(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "logicalShardId": record["logicalShardId"],
            "result": dict(record["submission"]),
        }
        for record in records
        if isinstance(record.get("submission"), Mapping)
    ]


def _checkpoint_from_state(
    files: ProjectFiles,
    state: Mapping[str, object],
    kind: str,
) -> Mapping[str, object] | None:
    matches = [
        item
        for item in _mappings(state.get("checkpointRefs"))
        if item.get("kind") == kind
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ProjectIOError(
            "CHECKPOINT_REF_INVALID", "", f"{kind} checkpoint 引用必须唯一。"
        )
    checkpoint = _mapping(files, str(matches[0]["path"]))
    if sha256_bytes(canonical_json_bytes(checkpoint)) != matches[0]["sha256"]:
        raise ProjectIOError(
            "CHECKPOINT_HASH_MISMATCH",
            str(matches[0]["path"]),
            f"{kind} checkpoint hash 不匹配。",
        )
    return checkpoint


def _candidate_snapshot_by_sha256(
    files: ProjectFiles,
    run_id: str,
    candidate_sha256: str,
) -> Mapping[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_sha256):
        raise ProjectIOError(
            "RUN_CANDIDATE_HASH_INVALID",
            candidate_sha256,
            "历史 candidate hash 格式无效。",
        )
    candidate_root = f"{RUNS_ROOT}/{run_id}/candidates"
    directory = files.resolve(candidate_root, expect="dir")
    suffix = f"-{candidate_sha256}.json"
    matches: list[str] = []
    for child in directory.iterdir():
        relative = f"{candidate_root}/{child.name}"
        files.resolve(relative, expect="file")
        if re.fullmatch(r"[0-9]{6}-[0-9a-f]{64}\.json", child.name) is None:
            raise ProjectIOError(
                "RUN_CANDIDATE_PATH_INVALID",
                relative,
                "candidate 目录包含非合同文件。",
            )
        if child.name.endswith(suffix):
            matches.append(child.name)
    matches.sort()
    if len(matches) != 1:
        raise ProjectIOError(
            "RUN_CANDIDATE_SNAPSHOT_MISSING",
            candidate_root,
            "阶段 action plan 绑定的历史 candidate 必须且只能存在一份。",
        )
    relative = f"{candidate_root}/{matches[0]}"
    candidate = _mapping(files, relative)
    if sha256_bytes(canonical_json_bytes(candidate)) != candidate_sha256:
        raise ProjectIOError(
            "RUN_CANDIDATE_HASH_MISMATCH",
            relative,
            "历史 candidate 内容与 action plan hash 不匹配。",
        )
    return candidate


def _persist_public_checkpoint(
    files: ProjectFiles,
    state: Mapping[str, object],
    kind: str,
    checkpoint: Mapping[str, object],
) -> Mapping[str, object]:
    run_id = str(state["runId"])
    payload = canonical_json_bytes(checkpoint)
    digest = sha256_bytes(payload)
    relative = f"{RUNS_ROOT}/{run_id}/checkpoints/{kind.lower()}-{digest}.json"
    files.publish_new(relative, payload)
    refs = [
        dict(item)
        for item in _mappings(state.get("checkpointRefs"))
        if item.get("kind") != kind
    ]
    refs.append({"kind": kind, "path": relative, "sha256": digest})
    order = {"SCOPE_CLOSURE": 0, "STORY_AC": 1, "TASK": 2}
    refs.sort(key=lambda item: order[str(item["kind"])])
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "checkpoint 只能写入 active run。"
        )
    return _write_active_state(files, marker, {**state, "checkpointRefs": refs})


def _public_model_config_sha256() -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "contract": "ai-sow-host-model-selection-v1",
                "selection": "HOST_DEFAULT",
                "contextPolicy": "FRESH_NO_HISTORY",
            }
        )
    )


def _public_compiler_state(
    files: ProjectFiles,
    state: Mapping[str, object],
    plans: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "当前项目没有 active run。")
    input_revision_path = str(marker["inputRevisionPath"])
    input_revision = _mapping(files, input_revision_path)
    candidate_path = state.get("currentCandidatePath")
    if not isinstance(candidate_path, str):
        raise ProjectIOError(
            "RUN_CANDIDATE_REQUIRED", str(marker["statePath"]), "pipeline 缺少 candidate。"
        )
    candidate = _mapping(files, candidate_path)
    if sha256_bytes(canonical_json_bytes(candidate)) != state["currentCandidateSha256"]:
        raise ProjectIOError(
            "RUN_CANDIDATE_HASH_MISMATCH", candidate_path, "candidate hash 不匹配。"
        )
    source_records = _records_for_step(files, str(state["runId"]), plans, "SOURCE_SCAN")
    proposal_records = _records_for_step(files, str(state["runId"]), plans, "SCOPE_PROPOSAL")
    r1_source_records = _records_for_step(files, str(state["runId"]), plans, "R1_SOURCE_AUDIT")
    r1_scope_records = [
        *_records_for_step(files, str(state["runId"]), plans, "R1_SCOPE_JOIN"),
        *_records_for_step(files, str(state["runId"]), plans, "R1_SCOPE_RECHECK"),
    ]
    story_records = _records_for_step(files, str(state["runId"]), plans, "STORY_AC")
    task_records = _records_for_step(files, str(state["runId"]), plans, "TASK")
    scope_checkpoint = _checkpoint_from_state(files, state, "SCOPE_CLOSURE")
    story_checkpoint = _checkpoint_from_state(files, state, "STORY_AC")
    task_checkpoint = _checkpoint_from_state(files, state, "TASK")
    excluded_policy_ids = {
        str(subject_id)
        for decision in _mappings(candidate.get("decisions"))
        if decision.get("kind") == "EXCLUDED_BY_USER"
        for subject_id in decision.get("subjectIds", [])
        if isinstance(subject_id, str)
    }
    policy_decisions = {
        str(item["policyInstanceId"]): (
            "EXCLUDED"
            if str(item["policyInstanceId"]) in excluded_policy_ids
            else "INCLUDED"
        )
        for item in _mappings(candidate.get("policyInstances"))
        if isinstance(item.get("policyInstanceId"), str)
    }
    result: dict[str, object] = {
        "contract": "ai-sow-scope-compiler-state-v1",
        "runId": state["runId"],
        "reviewSetId": f"review-{state['runId']}",
        "reviewMode": "DELTA" if state.get("route") == "DELTA_COMPILE" else "FULL",
        "inputRevision": input_revision,
        "sourceContents": _source_contents_for_revision(
            files, input_revision_path, input_revision
        ),
        "baseCandidate": candidate,
        "baseCandidateSha256": state["currentCandidateSha256"],
        "candidate": candidate,
        "scopeCandidate": candidate,
        "maxInitialPacketTokens": 48000,
        "proposalMaxInitialPacketTokens": 48000,
        "auditMaxInitialPacketTokens": 48000,
        "maxOutputTokens": 12000,
        "modelProfileId": "host-selected-author-v1",
        "modelConfigSha256": _public_model_config_sha256(),
        "acceptedRecords": [],
        "actionRecords": source_records,
        "proposalRecords": proposal_records,
        "r1SourceResults": _review_wrappers(r1_source_records),
        "sourceAuditResults": _review_wrappers(r1_source_records),
        "r1ScopeResult": (
            dict(r1_scope_records[-1]["submission"])
            if r1_scope_records
            and isinstance(r1_scope_records[-1].get("submission"), Mapping)
            else None
        ),
        "scopeClosureCheckpoint": scope_checkpoint,
        "effectivePolicyDecisions": policy_decisions,
        "storyActionRecords": story_records,
        "storyAcCheckpoint": story_checkpoint,
        "taskActionRecords": task_records,
        "taskCheckpoint": task_checkpoint,
        "taskCatalog": load_task_standard_catalog(
            _revision_template_path(files, input_revision_path)
        ),
        "taskEstimationMethodSha256": sha256_bytes(
            (SKILL_ROOT / "references/task-authoring.md").read_bytes()
        ),
        "priorSowInputSha256": (
            input_revision.get("priorSowSha256s", [])[0]
            if input_revision.get("priorSowSha256s")
            else "NOT_PROVIDED"
        ),
        "storyDesignReviewResults": _review_wrappers(
            _records_for_step(files, str(state["runId"]), plans, "STORY_DESIGN")
        ),
        "storyDesignThemeJoinResults": _review_wrappers(
            _records_for_step(files, str(state["runId"]), plans, "STORY_DESIGN_THEME_JOIN")
        ),
        "taskEstimationReviewResults": _review_wrappers(
            _records_for_step(files, str(state["runId"]), plans, "TASK_ESTIMATION")
        ),
        "taskEstimationThemeJoinResults": _review_wrappers(
            _records_for_step(files, str(state["runId"]), plans, "TASK_ESTIMATION_THEME_JOIN")
        ),
        "adjudicationResults": _review_wrappers(
            _records_for_step(files, str(state["runId"]), plans, "ADJUDICATION")
        ),
        "upstreamCheckpointSha256s": [],
    }
    return result


def _public_diagnostics(values: object) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return diagnostics
    for item in values:
        if isinstance(item, Diagnostic):
            diagnostics.append(_diagnostic_value(item))
        elif isinstance(item, Mapping):
            diagnostics.append(dict(item))
    return diagnostics


def _public_pipeline_failure(
    outcome: str, diagnostics: object, *, summary: str
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "summary": summary,
        "nextAction": None,
        "diagnostics": _public_diagnostics(diagnostics),
    }


def _issue_public_specs(
    files: ProjectFiles,
    state: Mapping[str, object],
    step: str,
    prepared: Mapping[str, object],
) -> dict[str, object]:
    if prepared.get("outcome") != "ACTION_REQUIRED":
        return _public_pipeline_failure(
            str(prepared.get("outcome", "CONTRACT_UNSUPPORTED")),
            prepared.get("diagnostics", ()),
            summary=f"{step} 未能安全发放。",
        )
    specs = _mappings(prepared.get("specs"))
    pending_ids = {
        str(item)
        for item in prepared.get("pendingLogicalShardIds", [])
        if isinstance(item, str)
    }
    if pending_ids:
        specs = [
            spec
            for spec in specs
            if str(spec.get("logicalShardId")) in pending_ids
        ]
    specs = specs[:8]
    if not specs:
        return _public_pipeline_failure(
            "CONTRACT_UNSUPPORTED", (), summary=f"{step} 未生成任何 action spec。"
        )
    _issue_action_group(
        files,
        str(state["runId"]),
        specs,
        max_concurrency=min(4, len(specs)),
        group_deadline_milliseconds=600000,
        shard_deadline_milliseconds=480000,
        pipeline_step=step,
    )
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "发放 action 后 run 消失。")
    return _public_active_result(files, _recover_active_run(files, marker))


def _seal_public_group(
    files: ProjectFiles,
    state: Mapping[str, object],
    plan: Mapping[str, object],
    model: Mapping[str, object],
) -> None:
    _apply_ready_group(
        files,
        str(state["runId"]),
        str(plan["groupId"]),
        model,
    )


def _apply_public_plan(
    files: ProjectFiles,
    state: Mapping[str, object],
    plans: Sequence[Mapping[str, object]],
    plan: Mapping[str, object],
) -> dict[str, object] | None:
    step = str(plan["pipelineStep"])
    records = _plan_records(files, str(state["runId"]), plan)
    context = _public_compiler_state(files, state, plans)
    if step in {"SOURCE_SCAN", "SCOPE_PROPOSAL", "SCOPE_JOIN"}:
        context["actionKind"] = step
        if step == "SCOPE_JOIN":
            context["proposalRecords"] = _records_for_step(
                files, str(state["runId"]), plans, "SCOPE_PROPOSAL"
            )
        compiled = apply_scope_action_group(context, records)
        if compiled.diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED",
                compiled.diagnostics,
                summary=f"{step} 结果未通过 Owner 校验。",
            )
        _seal_public_group(files, state, plan, compiled.model)
        return None
    if step == "R1_SOURCE_AUDIT":
        prepared = prepare_r1_source_audit(context)
        diagnostics = tuple(
            diagnostic
            for record in records
            for diagnostic in validate_r1_source_audit_result(
                context,
                prepared,
                str(record["logicalShardId"]),
                record["submission"],
            )
        )
        if diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED", diagnostics, summary="R1 Source Audit 未通过。"
            )
        _seal_public_group(files, state, plan, context["candidate"])
        return None
    if step in {"R1_SCOPE_JOIN", "R1_SCOPE_RECHECK"}:
        prepared = prepare_r1_scope_join(context)
        submission = records[0]["submission"]
        diagnostics = validate_r1_scope_join_result(context, prepared, submission)
        if diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED", diagnostics, summary="R1 Scope Join 未通过。"
            )
        _seal_public_group(files, state, plan, context["candidate"])
        return None
    if step == "STAGE_1_REPAIR":
        action_ids = plan.get("actionIds")
        if not isinstance(action_ids, list) or len(action_ids) != 1:
            return _public_pipeline_failure(
                "CONTRACT_UNSUPPORTED", (), summary="Stage 1 repair plan 无效。"
            )
        packet = _mapping(
            files,
            _action_paths(run_id=str(state["runId"]), action_id=str(action_ids[0]))[
                "packet"
            ],
        )
        payload = packet.get("payload")
        if not isinstance(payload, Mapping):
            return _public_pipeline_failure(
                "CONTRACT_UNSUPPORTED", (), summary="Stage 1 repair packet 无效。"
            )
        repair_plan = payload.get("repairPlan")
        findings = payload.get("findings")
        if not isinstance(repair_plan, Mapping):
            return _public_pipeline_failure(
                "CONTRACT_UNSUPPORTED", (), summary="Stage 1 repair 缺少计划。"
            )
        context["baseCandidate"] = context["candidate"]
        context["baseCandidateSha256"] = state["currentCandidateSha256"]
        compiled = apply_scope_repair_action_group(
            context,
            repair_plan,
            _mappings(findings),
            records,
        )
        if compiled.diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED",
                compiled.diagnostics,
                summary="Stage 1 repair 结果未通过 Owner 校验。",
            )
        _seal_public_group(files, state, plan, compiled.model)
        return None
    if step == "STORY_AC":
        context["baseCandidate"] = context["candidate"]
        context["baseCandidateSha256"] = state["currentCandidateSha256"]
        compiled = apply_story_action_group(context, records)
        if compiled.diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED", compiled.diagnostics, summary="Story/AC 结果未通过。"
            )
        _seal_public_group(files, state, plan, compiled.model)
        return None
    if step == "TASK":
        context["baseCandidate"] = context["candidate"]
        context["baseCandidateSha256"] = state["currentCandidateSha256"]
        compiled = apply_task_action_group(context, records)
        if compiled.diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED", compiled.diagnostics, summary="Task 结果未通过。"
            )
        _seal_public_group(files, state, plan, compiled.model)
        return None
    if step in {
        "STORY_DESIGN",
        "STORY_DESIGN_THEME_JOIN",
        "TASK_ESTIMATION",
        "TASK_ESTIMATION_THEME_JOIN",
        "ADJUDICATION",
    }:
        _seal_public_group(files, state, plan, context["candidate"])
        return None
    return _public_pipeline_failure(
        "CONTRACT_UNSUPPORTED", (), summary=f"未知 pipeline step：{step}。"
    )


def _plan_exists(plans: Sequence[Mapping[str, object]], step: str) -> bool:
    return any(plan.get("pipelineStep") == step for plan in plans)


def _candidate_through_stage(
    candidate: Mapping[str, object], stage: str
) -> dict[str, object]:
    projected = deepcopy(dict(candidate))
    if stage == "STAGE_1":
        collections = (
            "stories",
            "acceptanceCriteria",
            "deliveryAnnotations",
            "tasks",
            "dependencies",
            "effectiveStartMatches",
            "estimationAnnotations",
        )
    elif stage == "STAGE_2":
        collections = (
            "tasks",
            "dependencies",
            "effectiveStartMatches",
            "estimationAnnotations",
        )
    else:
        raise ValueError(f"unsupported candidate projection stage: {stage}")
    for collection in collections:
        projected[collection] = []
    return projected


def _plan_for_step(
    plans: Sequence[Mapping[str, object]], step: str
) -> Mapping[str, object]:
    matches = [plan for plan in plans if plan.get("pipelineStep") == step]
    if len(matches) != 1:
        raise ProjectIOError(
            "PIPELINE_PLAN_INVALID",
            "",
            f"{step} action plan 必须且只能存在一份。",
        )
    return matches[0]


def _advance_public_pipeline(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> dict[str, object]:
    run_id = str(state["runId"])
    plans = _pipeline_plans(files, run_id)
    unapplied = [plan for plan in plans if not _plan_applied(files, run_id, plan)]
    if unapplied:
        if len(unapplied) != 1:
            raise ProjectIOError(
                "PIPELINE_PLAN_INVALID", "", "同一 run 只能有一个待应用 action group。"
            )
        failure = _apply_public_plan(files, state, plans, unapplied[0])
        if failure is not None:
            return failure
        marker = _read_active_marker(files)
        if marker is None:
            raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "应用 action 后 run 消失。")
        state = _recover_active_run(files, marker)
        plans = _pipeline_plans(files, run_id)

    context = _public_compiler_state(files, state, plans)
    if not _plan_exists(plans, "SOURCE_SCAN"):
        return _issue_public_specs(
            files, state, "SOURCE_SCAN", prepare_scope_action(context, "SOURCE_SCAN")
        )
    if not _plan_exists(plans, "SCOPE_PROPOSAL"):
        context["actionKind"] = "SCOPE_PROPOSAL"
        return _issue_public_specs(
            files,
            state,
            "SCOPE_PROPOSAL",
            prepare_scope_action(context, "SCOPE_PROPOSAL"),
        )
    if not _plan_exists(plans, "SCOPE_JOIN"):
        context["actionKind"] = "SCOPE_JOIN"
        return _issue_public_specs(
            files,
            state,
            "SCOPE_JOIN",
            prepare_scope_action(context, "SCOPE_JOIN"),
        )
    if not _plan_exists(plans, "R1_SOURCE_AUDIT"):
        return _issue_public_specs(
            files,
            state,
            "R1_SOURCE_AUDIT",
            prepare_r1_source_audit(context),
        )
    if not _plan_exists(plans, "R1_SCOPE_JOIN"):
        return _issue_public_specs(
            files,
            state,
            "R1_SCOPE_JOIN",
            prepare_r1_scope_join(context),
        )
    r1_scope_records = [
        *_records_for_step(files, run_id, plans, "R1_SCOPE_JOIN"),
        *_records_for_step(files, run_id, plans, "R1_SCOPE_RECHECK"),
    ]
    latest_r1_scope = (
        r1_scope_records[-1].get("submission") if r1_scope_records else None
    )
    if isinstance(latest_r1_scope, Mapping) and latest_r1_scope.get("decision") != "PASS":
        findings, finding_diagnostics = _normalize_findings(
            _mappings(latest_r1_scope.get("findings"))
        )
        if finding_diagnostics:
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED",
                finding_diagnostics,
                summary="R1 Scope Review findingId 冲突，不能生成 repair plan。",
            )
        if _plan_exists(plans, "R1_SCOPE_RECHECK"):
            return _public_pipeline_failure(
                "OWNER_FIX_REQUIRED",
                (),
                summary="Stage 1 repair 后的 R1 Scope Recheck 仍未通过。",
            )
        if not _plan_exists(plans, "STAGE_1_REPAIR"):
            repair_plan = build_repair_plan(context, findings)
            prepared_repair = prepare_scope_repair_action(
                context, repair_plan, findings
            )
            return _issue_public_specs(
                files, state, "STAGE_1_REPAIR", prepared_repair
            )
        return _issue_public_specs(
            files,
            state,
            "R1_SCOPE_RECHECK",
            prepare_r1_scope_join(context),
        )
    scope_checkpoint = _checkpoint_from_state(files, state, "SCOPE_CLOSURE")
    if scope_checkpoint is None:
        checkpoint_context = {
            **context,
            "candidate": _candidate_through_stage(context["candidate"], "STAGE_1"),
        }
        checkpoint_result = build_scope_closure_checkpoint(checkpoint_context)
        if checkpoint_result.get("outcome") != "READY_FOR_STORY_AC":
            return _public_pipeline_failure(
                str(checkpoint_result.get("outcome", "CONTRACT_UNSUPPORTED")),
                checkpoint_result.get("diagnostics", ()),
                summary="ScopeClosureCheckpoint 未通过。",
            )
        state = _persist_public_checkpoint(
            files, state, "SCOPE_CLOSURE", checkpoint_result["checkpoint"]
        )
        context = _public_compiler_state(files, state, plans)
        scope_checkpoint = context["scopeClosureCheckpoint"]
    if not _plan_exists(plans, "STORY_AC"):
        context["baseCandidate"] = context["candidate"]
        context["baseCandidateSha256"] = state["currentCandidateSha256"]
        return _issue_public_specs(
            files,
            state,
            "STORY_AC",
            prepare_delivery_action(context, "STORY_AC"),
        )
    story_checkpoint = _checkpoint_from_state(files, state, "STORY_AC")
    if story_checkpoint is None:
        story_plan = _plan_for_step(plans, "STORY_AC")
        story_base_sha256 = str(story_plan["baseCandidateSha256"])
        context["baseCandidate"] = _candidate_snapshot_by_sha256(
            files, run_id, story_base_sha256
        )
        context["baseCandidateSha256"] = story_base_sha256
        context["storyActionRecords"] = _records_for_step(
            files, run_id, plans, "STORY_AC"
        )
        context["upstreamCheckpointSha256s"] = [
            sha256_bytes(canonical_json_bytes(scope_checkpoint))
        ]
        checkpoint_context = {
            **context,
            "candidate": _candidate_through_stage(context["candidate"], "STAGE_2"),
        }
        checkpoint_result = build_story_ac_checkpoint(checkpoint_context)
        if checkpoint_result.get("outcome") != "READY_FOR_TASK":
            return _public_pipeline_failure(
                str(checkpoint_result.get("outcome", "CONTRACT_UNSUPPORTED")),
                checkpoint_result.get("diagnostics", ()),
                summary="StoryAcCheckpoint 未通过。",
            )
        state = _persist_public_checkpoint(
            files, state, "STORY_AC", checkpoint_result["checkpoint"]
        )
        context = _public_compiler_state(files, state, plans)
        story_checkpoint = context["storyAcCheckpoint"]
    if not _plan_exists(plans, "TASK"):
        context["baseCandidate"] = context["candidate"]
        context["baseCandidateSha256"] = state["currentCandidateSha256"]
        return _issue_public_specs(
            files, state, "TASK", prepare_task_action(context, "TASK")
        )
    task_checkpoint = _checkpoint_from_state(files, state, "TASK")
    if task_checkpoint is None:
        task_plan = _plan_for_step(plans, "TASK")
        task_base_sha256 = str(task_plan["baseCandidateSha256"])
        context["baseCandidate"] = _candidate_snapshot_by_sha256(
            files, run_id, task_base_sha256
        )
        context["baseCandidateSha256"] = task_base_sha256
        context["taskActionRecords"] = _records_for_step(files, run_id, plans, "TASK")
        checkpoint_result = build_task_checkpoint(context)
        if checkpoint_result.get("outcome") != "READY_FOR_REVIEW":
            return _public_pipeline_failure(
                str(checkpoint_result.get("outcome", "CONTRACT_UNSUPPORTED")),
                checkpoint_result.get("diagnostics", ()),
                summary="TaskCheckpoint 未通过。",
            )
        state = _persist_public_checkpoint(
            files, state, "TASK", checkpoint_result["checkpoint"]
        )
        context = _public_compiler_state(files, state, plans)

    review = advance_layered_review(context)
    if review.get("outcome") == "ACTION_REQUIRED":
        stage = str(review.get("stage"))
        if stage == "THEME_JOIN":
            step = f"{review['sourceReviewKind']}_THEME_JOIN"
        else:
            step = stage
        return _issue_public_specs(files, state, step, review)
    if review.get("outcome") != "READY_FOR_APPROVAL":
        return _public_pipeline_failure(
            str(review.get("outcome", "CONTRACT_UNSUPPORTED")),
            review.get("diagnostics", ()),
            summary="分层评审未通过。",
        )
    review_decision = review["reviewDecision"]
    review_payload = canonical_json_bytes(review_decision)
    review_sha256 = sha256_bytes(review_payload)
    files.publish_new(
        f"{RUNS_ROOT}/{run_id}/reviews/decision-{review_sha256}.json",
        review_payload,
    )
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "生成 artifact 前 run 消失。")
    artifact = prepare_artifact(
        {
            **context,
            "reviewDecision": review_decision,
            "taskCheckpoint": context["taskCheckpoint"],
        },
        files,
        template_path=_revision_template_path(files, str(marker["inputRevisionPath"])),
    )
    if artifact.get("outcome") != "REQUEST_APPROVAL":
        return artifact
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "生成 artifact 后 run 消失。")
    awaiting = _write_active_state(
        files,
        marker,
        {
            **state,
            "phase": "AWAITING_APPROVAL",
            "wait": "APPROVAL",
            "expectedActionIds": [],
        },
    )
    return {**artifact, "state": dict(awaiting)}


def _drive_public_active(
    project_root: Path,
    result: Mapping[str, object],
) -> dict[str, object]:
    if result.get("outcome") != "ACTIVE" or not isinstance(
        result.get("state"), Mapping
    ):
        return dict(result)
    files = ProjectFiles.open(project_root)
    state = result["state"]
    assert isinstance(state, Mapping)
    if state.get("phase") == "DONE" and isinstance(state.get("result"), str):
        return {
            "outcome": state["result"],
            "state": dict(state),
            "nextAction": None,
            "diagnostics": [],
        }
    if state.get("phase") == "PREPARE" and state.get("wait") == "NONE":
        return _start_public_pipeline(files, state)
    if state.get("wait") == "NONE" and state.get("result") is None:
        return _advance_public_pipeline(files, state)
    return _public_active_result(files, state)


def _reconcile_active_state(
    files: ProjectFiles,
    marker: Mapping[str, object],
    state: Mapping[str, object],
) -> Mapping[str, object]:
    """Replay immutable action facts across a crash before the state pointer swap."""

    run_id = str(state["runId"])
    reconciled = dict(state)
    changed = False
    _materialize_pending_exclusion_transition(files, reconciled)
    if _pending_abandon_decision(files, reconciled):
        reconciled.update(
            {
                "phase": "DONE",
                "wait": "NONE",
                "result": "ABANDONED",
                "expectedActionIds": [],
                "resumeFromPhase": None,
            }
        )
        return _write_active_state(files, marker, reconciled)
    transitions = _exclusion_transitions(files, run_id)
    applied_transition = True
    while applied_transition:
        applied_transition = False
        for transition in transitions:
            if (
                reconciled.get("currentCandidateSha256")
                == transition["baseCandidateSha256"]
            ):
                reconciled.update(
                    {
                        "phase": "STORY_AC",
                        "wait": "NONE",
                        "result": None,
                        "currentCandidateSha256": transition["candidateSha256"],
                        "currentCandidatePath": transition["candidatePath"],
                        "expectedActionIds": [],
                        "checkpointRefs": [],
                        "resumeFromPhase": "STORY_AC",
                    }
                )
                changed = True
                applied_transition = True
                break

    plans = _pipeline_plans(files, run_id)
    unapplied = [plan for plan in plans if not _plan_applied(files, run_id, plan)]

    if (
        reconciled.get("wait") == "NONE"
        and not reconciled.get("expectedActionIds")
        and len(unapplied) == 1
    ):
        plan = unapplied[0]
        action_ids = [
            item for item in plan.get("actionIds", []) if isinstance(item, str)
        ]
        pending_ids = [
            action_id
            for action_id in action_ids
            if _optional_json(files, _action_paths(run_id, action_id)["record"])
            is None
        ]
        if pending_ids:
            envelopes = [
                _mapping(files, _action_paths(run_id, action_id)["envelope"])
                for action_id in action_ids
            ]
            stages = {str(envelope["stage"]) for envelope in envelopes}
            if len(stages) != 1:
                raise ProjectIOError(
                    "PIPELINE_PLAN_INVALID",
                    "",
                    "待恢复 action plan 包含多个 stage。",
                )
            reconciled.update(
                {
                    "phase": _phase_for_action_stage(stages.pop()),
                    "wait": "MODEL",
                    "expectedActionIds": pending_ids,
                }
            )
            budget = dict(reconciled["budget"])
            budget["modelActionsStarted"] = max(
                int(budget["modelActionsStarted"]),
                int(plan["sequence"]) + len(action_ids),
            )
            reconciled["budget"] = budget
            changed = True

    expected_ids = [
        item for item in reconciled.get("expectedActionIds", []) if isinstance(item, str)
    ]
    if reconciled.get("wait") == "MODEL" and expected_ids:
        remaining: list[str] = []
        exhausted = False
        for action_id in expected_ids:
            record = _optional_json(files, _action_paths(run_id, action_id)["record"])
            if record is None:
                remaining.append(action_id)
                continue
            if not isinstance(record, Mapping) or validate_contract(
                record, "action.schema.json", NEXT_SCHEMA_REGISTRY
            ):
                raise ProjectIOError(
                    "ACTION_RECORD_INVALID",
                    _action_paths(run_id, action_id)["record"],
                    "恢复时发现无效 ActionRecord。",
                )
            if record.get("status") == "SUCCESS":
                changed = True
                continue
            if record.get("status") not in {"FAILED", "LATE"}:
                raise ProjectIOError(
                    "ACTION_RECORD_INVALID",
                    _action_paths(run_id, action_id)["record"],
                    "恢复时发现未知 ActionRecord 状态。",
                )
            envelope = _mapping(
                files, _action_paths(run_id, action_id)["envelope"]
            )
            if int(envelope["executionAttempt"]) >= 2:
                exhausted = True
                changed = True
                continue
            transition = _materialize_action_retry(
                files, action_id, envelope, record
            )
            remaining.append(str(transition["retryActionId"]))
            changed = True
        if exhausted:
            reconciled.update(
                {
                    "phase": "DONE",
                    "wait": "NONE",
                    "result": "SYSTEM_FAILED",
                    "expectedActionIds": [],
                    "resumeFromPhase": None,
                }
            )
        elif remaining != expected_ids:
            reconciled["expectedActionIds"] = remaining
            reconciled["wait"] = "MODEL" if remaining else "NONE"

    try:
        records_root = files.resolve(f"{RUNS_ROOT}/{run_id}/actions", expect="dir")
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
    else:
        started_count = sum(
            1 for path in records_root.glob("*/issued.json") if path.is_file()
        )
        completed_count = sum(
            1 for path in records_root.glob("*/record.json") if path.is_file()
        )
        budget = dict(reconciled["budget"])
        rebuilt_started = max(int(budget["modelActionsStarted"]), started_count)
        rebuilt_completed = max(
            int(budget["modelActionsCompleted"]), completed_count
        )
        if (
            rebuilt_started != budget["modelActionsStarted"]
            or rebuilt_completed != budget["modelActionsCompleted"]
        ):
            budget["modelActionsStarted"] = rebuilt_started
            budget["modelActionsCompleted"] = rebuilt_completed
            reconciled["budget"] = budget
            changed = True

    if not changed:
        return state
    return _write_active_state(files, marker, reconciled)


def _write_active_state(
    files: ProjectFiles,
    marker: Mapping[str, object],
    state: Mapping[str, object],
) -> Mapping[str, object]:
    validation_path = str(marker["statePath"])
    validated = _validated_run_state(state, validation_path)
    state_payload = canonical_json_bytes(validated)
    state_sha256 = sha256_bytes(state_payload)
    state_path = _state_snapshot_path(str(validated["runId"]), state_sha256)
    files.publish_new(state_path, state_payload)
    active_marker = {
        **marker,
        "statePath": state_path,
        "status": "ACTIVE",
        "stateSha256": state_sha256,
    }
    files.write_atomic(ACTIVE_RUN_PATH, canonical_json_bytes(active_marker))
    return validated


def _revision_template_path(files: ProjectFiles, input_revision_path: str) -> Path:
    return files.resolve(
        f"{Path(input_revision_path).parent.as_posix()}/sow-template.xlsx",
        expect="file",
    )


def _prepare_render_only(
    files: ProjectFiles,
    state: Mapping[str, object],
    input_revision_path: str,
    input_revision: Mapping[str, object],
    materials: Mapping[str, object],
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "render-only run 不存在。")
    state = _write_active_state(
        files,
        marker,
        {**state, "route": "RENDER_ONLY", "phase": "DRAFT"},
    )
    candidate = deepcopy(materials["candidate"])
    if not isinstance(candidate, dict) or not isinstance(candidate.get("project"), dict):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "已发布 generation 缺少可复用 sow-model project 绑定。",
        )
    source_manifest_sha256 = sha256_bytes(
        canonical_json_bytes(
            {
                "sources": input_revision.get("sources", []),
                "blocks": input_revision.get("blocks", []),
            }
        )
    )
    candidate["project"].update(
        {
            "inputRevisionSha256": sha256_bytes(canonical_json_bytes(input_revision)),
            "sourceManifestSha256": source_manifest_sha256,
            "templateSha256": input_revision["templateSha256"],
        }
    )
    if validate_contract(candidate, "sow-model.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "render-only 重绑定后的 sow-model 合同无效。",
        )
    snapshot = _append_candidate_snapshot(files, str(state["runId"]), candidate)
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "写入 candidate 后 run 消失。")
    state = _recover_active_run(files, marker)
    checkpoints = materials["checkpoints"]
    if not isinstance(checkpoints, Mapping):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "已发布 generation 缺少 Stage checkpoint。",
        )
    for kind in ("SCOPE_CLOSURE", "STORY_AC", "TASK"):
        checkpoint = checkpoints.get(kind)
        if not isinstance(checkpoint, Mapping):
            raise ProjectIOError(
                "GENERATION_PROOF_CLOSURE_INVALID",
                str(materials.get("generationRoot", "")),
                f"已发布 generation 缺少 {kind} checkpoint。",
            )
        state = _persist_public_checkpoint(files, state, kind, checkpoint)
    review_decision = deepcopy(materials["reviewDecision"])
    if not isinstance(review_decision, dict):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "已发布 generation 缺少终审决定。",
        )
    checkpoint_refs = {
        str(item["kind"]): str(item["sha256"])
        for item in _mappings(state.get("checkpointRefs"))
    }
    review_decision.update(
        {
            "runId": state["runId"],
            "candidateSha256": snapshot["sha256"],
            "scopeClosureCheckpointSha256": checkpoint_refs["SCOPE_CLOSURE"],
            "storyAcCheckpointSha256": checkpoint_refs["STORY_AC"],
            "taskCheckpointSha256": checkpoint_refs["TASK"],
        }
    )
    review_payload = canonical_json_bytes(review_decision)
    review_sha256 = sha256_bytes(review_payload)
    files.publish_new(
        f"{RUNS_ROOT}/{state['runId']}/reviews/decision-{review_sha256}.json",
        review_payload,
    )
    artifact = prepare_artifact(
        {
            "runId": state["runId"],
            "candidate": candidate,
            "inputRevision": input_revision,
            "effectivePolicyDecisions": materials["effectivePolicyDecisions"],
            "scopeClosureCheckpoint": checkpoints["SCOPE_CLOSURE"],
            "storyAcCheckpoint": checkpoints["STORY_AC"],
            "taskCheckpoint": checkpoints["TASK"],
            "reviewDecision": review_decision,
        },
        files,
        template_path=_revision_template_path(files, input_revision_path),
    )
    if artifact.get("outcome") != "REQUEST_APPROVAL":
        return artifact
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "render-only 后 run 消失。")
    state = _recover_active_run(files, marker)
    awaiting = _write_active_state(
        files,
        marker,
        {
            **state,
            "phase": "AWAITING_APPROVAL",
            "wait": "APPROVAL",
            "expectedActionIds": [],
        },
    )
    return {**artifact, "state": dict(awaiting)}


def _prepare_delta_compile(
    files: ProjectFiles,
    state: Mapping[str, object],
    input_revision_path: str,
    input_revision: Mapping[str, object],
    materials: Mapping[str, object],
) -> Mapping[str, object]:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "delta run 不存在。")
    state = _write_active_state(files, marker, {**state, "route": "DELTA_COMPILE"})
    candidate = deepcopy(materials["candidate"])
    if not isinstance(candidate, dict):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "已发布 generation 缺少可复用 sow-model。",
        )
    revision_root = Path(input_revision_path).parent.as_posix()
    request = _mapping(files, f"{revision_root}/request.json")
    candidate["project"] = model_skeleton(request, input_revision)["project"]
    if validate_contract(candidate, "sow-model.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "GENERATION_PROOF_CLOSURE_INVALID",
            str(materials.get("generationRoot", "")),
            "delta 重绑定后的 sow-model 合同无效。",
        )
    _append_candidate_snapshot(files, str(state["runId"]), candidate)
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "delta candidate 后 run 消失。")
    return _recover_active_run(files, marker)


def start(project_root: Path, request_path: str) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        managed_request_path = _managed_request_path(files, request_path)
        request_sha256 = sha256_bytes(files.read_bytes(managed_request_path))
        marker = _read_active_marker(files)
        if marker is not None:
            if marker["requestSha256"] != request_sha256:
                return _result(
                    "RUN_IN_PROGRESS",
                    "同一项目已有绑定不同 request 的 active run。",
                    diagnostics=(
                        _diagnostic(
                            "RUN_IN_PROGRESS",
                            "请继续或明确放弃现有 run，不能并行启动第二个顶层 run。",
                            ACTIVE_RUN_PATH,
                        ),
                    ),
                )
            return _active_result(_recover_active_run(files, marker))

        run_id = f"run-{uuid4().hex[:12]}"
        revision = prepare_input_revision(managed_request_path, files=files)
        if revision.value is None or revision.sha256 is None:
            return _result(
                "BLOCKED",
                "输入未通过 Prepare 门禁，未创建 active run。",
                diagnostics=revision.diagnostics,
            )
        current = load_current(files)
        render_only_materials: Mapping[str, object] | None = None
        route_decision: RouteDecision | None = None
        if current is not None:
            current_manifest = _mapping(files, current.manifest_path)
            render_only_materials = _generation_route_materials(files, current)
            route_context = _route_context_for_revision(
                files,
                str(revision.path),
                revision.value,
                render_only_materials,
            )
            route_decision = plan_route(
                route_context,
                revision.value,
                render_only_materials["proof"],
            )
            if route_decision.route == "REUSE":
                next_action = {
                    "contract": "ai-sow-next-action-v1",
                    "kind": "DONE",
                    "result": "REUSED",
                    "generationManifestPath": current.manifest_path,
                }
                if validate_contract(
                    next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY
                ):
                    raise ProjectIOError(
                        "NEXT_ACTION_INVALID",
                        current.manifest_path,
                        "精确重放的 DONE action 合同无效。",
                    )
                return {
                    "outcome": "REUSED",
                    "summary": "输入、模板与已发布 generation 完全一致，直接复用。",
                    "generationManifestPath": current.manifest_path,
                    "nextAction": next_action,
                    "diagnostics": [],
                }
        reservation = _active_marker_value(
            run_id=run_id,
            request_path=managed_request_path,
            request_sha256=request_sha256,
            input_revision_sha256=revision.sha256,
            input_revision_path=str(revision.path),
        )
        if not files.create_exclusive(
            ACTIVE_RUN_PATH, canonical_json_bytes(reservation)
        ):
            marker = _read_active_marker(files)
            if marker is None:
                raise ProjectIOError(
                    "ACTIVE_RUN_RACE",
                    ACTIVE_RUN_PATH,
                    "active run reservation 未能稳定建立。",
                )
            if marker["requestSha256"] != request_sha256:
                return _result(
                    "RUN_IN_PROGRESS",
                    "同一项目已有绑定不同 request 的 active run。",
                    diagnostics=(
                        _diagnostic(
                            "RUN_IN_PROGRESS",
                            "请继续或明确放弃现有 run，不能并行启动第二个顶层 run。",
                            ACTIVE_RUN_PATH,
                        ),
                    ),
                )
            return _active_result(_recover_active_run(files, marker))
        state = _recover_active_run(files, reservation)
        if (
            route_decision is not None
            and route_decision.route == "RENDER_ONLY"
            and render_only_materials is not None
        ):
            return _prepare_render_only(
                files,
                state,
                str(revision.path),
                revision.value,
                render_only_materials,
            )
        if (
            route_decision is not None
            and route_decision.route == "DELTA_COMPILE"
            and render_only_materials is not None
        ):
            state = _prepare_delta_compile(
                files,
                state,
                str(revision.path),
                revision.value,
                render_only_materials,
            )
        return _active_result(state)
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def resume(
    project_root: Path,
    request_path: str | None = None,
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        marker = _read_active_marker(files)
        if marker is None:
            if request_path is not None:
                return start(project_root, request_path)
            return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run。")
        if request_path is not None:
            managed_request_path = _managed_request_path(files, request_path)
            request_sha256 = sha256_bytes(files.read_bytes(managed_request_path))
            if request_sha256 != marker["requestSha256"]:
                revision = prepare_input_revision(managed_request_path, files=files)
                if revision.value is None or revision.sha256 is None:
                    return _result(
                        "BLOCKED",
                        "新输入未通过 Prepare 门禁；现有 run 保持 active。",
                        diagnostics=revision.diagnostics,
                    )
                state = dict(
                    _recover_active_run(files, marker, verify_request=False)
                )
                active = _read_active_marker(files)
                if active is None or active["runId"] != marker["runId"]:
                    raise ProjectIOError(
                        "ACTIVE_RUN_MARKER_MISSING",
                        ACTIVE_RUN_PATH,
                        "切换 Input Revision 前 active run 意外缺失。",
                    )
                terminal_state = {
                    **state,
                    "phase": "DONE",
                    "wait": "NONE",
                    "result": "ABANDONED",
                    "expectedActionIds": [],
                    "resumeFromPhase": None,
                }
                _write_active_state(files, active, terminal_state)
                active_payload = files.read_bytes(ACTIVE_RUN_PATH)
                files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
                return start(project_root, managed_request_path)
        return _active_result(_recover_active_run(files, marker))
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _approval_artifact(
    files: ProjectFiles,
    artifact_manifest_sha256: str,
) -> tuple[str, Mapping[str, object]]:
    if re.fullmatch(r"[0-9a-f]{64}", artifact_manifest_sha256) is None:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_HASH_INVALID",
            str(artifact_manifest_sha256),
            "artifact manifest hash must be lower-case SHA-256",
        )
    try:
        runs_root = files.resolve(RUNS_ROOT, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            raise ProjectIOError(
                "ARTIFACT_MANIFEST_NOT_FOUND",
                RUNS_ROOT,
                "requested artifact manifest was not found",
            ) from error
        raise
    matches: list[tuple[str, Mapping[str, object]]] = []
    for path in sorted(runs_root.glob("*/artifacts/*/artifact-manifest.json")):
        relative = path.relative_to(files.root).as_posix()
        payload = files.read_bytes(relative)
        if sha256_bytes(payload) != artifact_manifest_sha256:
            continue
        value = files.read_json(relative)
        diagnostics = validate_contract(
            value,
            "artifact-approval.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if diagnostics or not isinstance(value, Mapping):
            raise ProjectIOError(
                "ARTIFACT_MANIFEST_INVALID",
                relative,
                "artifact manifest is not contract-valid",
            )
        matches.append((relative, value))
    if not matches:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_NOT_FOUND",
            RUNS_ROOT,
            "requested artifact manifest was not found",
        )
    if len(matches) > 1:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_NOT_UNIQUE",
            RUNS_ROOT,
            "artifact approval must resolve exactly one manifest",
        )
    return matches[0]


def _existing_nonapproval_decision(
    files: ProjectFiles,
    manifest: Mapping[str, object],
    artifact_manifest_sha256: str,
) -> tuple[str, Mapping[str, object]] | None:
    decisions_root = f"{RUNS_ROOT}/{manifest['runId']}/decisions"
    try:
        root = files.resolve(decisions_root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    matches: list[tuple[str, Mapping[str, object]]] = []
    for path in sorted(root.glob("*.json")):
        relative = path.relative_to(files.root).as_posix()
        value = files.read_json(relative)
        if (
            isinstance(value, Mapping)
            and value.get("artifactManifestSha256")
            == artifact_manifest_sha256
        ):
            matches.append((relative, value))
    if len(matches) > 1:
        raise ProjectIOError(
            "ARTIFACT_DECISION_CONFLICT",
            decisions_root,
            "artifact has more than one non-approval decision",
        )
    return matches[0] if matches else None


def _prepare_exclusion_delta(
    files: ProjectFiles,
    *,
    artifact_root: str,
    manifest: Mapping[str, object],
    decision: Mapping[str, object],
    decision_sha256: str,
) -> dict[str, str]:
    candidate_value = files.read_json(f"{artifact_root}/sow-model.json")
    policy_value = files.read_json(
        f"{artifact_root}/effective-policy-decision.json"
    )
    if not isinstance(candidate_value, Mapping) or not isinstance(
        policy_value, Mapping
    ):
        raise ProjectIOError(
            "ARTIFACT_INPUT_INVALID",
            artifact_root,
            "artifact model or effective policy decision is invalid",
        )
    excluded_ids = sorted(
        str(value) for value in decision["excludedPolicyInstanceIds"]
    )
    policy_instances = {
        str(item.get("policyInstanceId")): item
        for item in candidate_value.get("policyInstances", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("policyInstanceId"), str)
    }
    invalid_ids = [
        policy_id
        for policy_id in excluded_ids
        if policy_id not in policy_instances
        or policy_instances[policy_id].get("inclusionPolicy")
        != "DEFAULT_INCLUDED"
        or policy_value.get(policy_id) != "INCLUDED"
    ]
    if invalid_ids:
        raise ProjectIOError(
            "POLICY_EXCLUSION_INVALID",
            artifact_root,
            "only currently included DEFAULT_INCLUDED policies may be excluded",
        )

    next_policy = {str(key): value for key, value in policy_value.items()}
    for policy_id in excluded_ids:
        next_policy[policy_id] = "EXCLUDED"
    next_policy = {key: next_policy[key] for key in sorted(next_policy)}

    next_candidate = dict(candidate_value)
    for collection in (
        "stories",
        "acceptanceCriteria",
        "deliveryAnnotations",
        "tasks",
        "dependencies",
        "effectiveStartMatches",
        "estimationAnnotations",
    ):
        next_candidate[collection] = []
    prior_decisions = [
        dict(item)
        for item in candidate_value.get("decisions", [])
        if isinstance(item, Mapping)
    ]
    next_candidate["decisions"] = [
        *prior_decisions,
        {
            "decisionId": f"decision-excluded-{decision_sha256[:16]}",
            "kind": "EXCLUDED_BY_USER",
            "subjectIds": excluded_ids,
            "decisionSha256": decision_sha256,
        },
    ]
    diagnostics = validate_contract(
        next_candidate,
        "sow-model.schema.json",
        NEXT_SCHEMA_REGISTRY,
    )
    if diagnostics:
        raise ProjectIOError(
            "POLICY_EXCLUSION_DELTA_INVALID",
            artifact_root,
            "excluded policy delta does not satisfy the sow-model contract",
        )

    revision_root = (
        f"{RUNS_ROOT}/{manifest['runId']}/revisions/"
        f"exclusion-{decision_sha256}"
    )
    candidate_path = f"{revision_root}/sow-model.json"
    policy_path = f"{revision_root}/effective-policy-decision.json"
    decision_path = f"{revision_root}/exclusion-decision.json"
    candidate_payload = canonical_json_bytes(next_candidate)
    policy_payload = canonical_json_bytes(next_policy)
    files.publish_new(candidate_path, candidate_payload)
    files.publish_new(policy_path, policy_payload)
    files.publish_new(decision_path, canonical_json_bytes(decision))
    return {
        "candidatePath": candidate_path,
        "candidateSha256": sha256_bytes(candidate_payload),
        "effectivePolicyDecisionPath": policy_path,
        "effectivePolicyDecisionSha256": sha256_bytes(policy_payload),
        "exclusionDecisionPath": decision_path,
    }


def _terminalize_active_run(
    files: ProjectFiles,
    marker: Mapping[str, object],
    *,
    result: str,
) -> Mapping[str, object]:
    state = dict(_recover_active_run(files, marker))
    current_marker = _read_active_marker(files)
    if (
        current_marker is None
        and state.get("phase") == "DONE"
        and state.get("result") == result
    ):
        return state
    if current_marker is None or current_marker.get("runId") != marker.get("runId"):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_MISSING",
            ACTIVE_RUN_PATH,
            "终态切换期间 active run 已变化。",
        )
    terminal_state = _write_active_state(
        files,
        current_marker,
        {
            **state,
            "phase": "DONE",
            "wait": "NONE",
            "result": result,
            "expectedActionIds": [],
            "resumeFromPhase": None,
        },
    )
    active_payload = files.read_bytes(ACTIVE_RUN_PATH)
    files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
    return terminal_state


def _active_artifact(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> tuple[str, Mapping[str, object], str] | None:
    if state.get("phase") != "AWAITING_APPROVAL":
        return None
    root_path = f"{RUNS_ROOT}/{state['runId']}/artifacts"
    try:
        root = files.resolve(root_path, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    matches: list[tuple[str, Mapping[str, object], str]] = []
    for path in sorted(root.glob("*/artifact-manifest.json")):
        relative = path.relative_to(files.root).as_posix()
        payload = files.read_bytes(relative)
        manifest = files.read_json(relative)
        if (
            isinstance(manifest, Mapping)
            and manifest.get("runId") == state.get("runId")
            and manifest.get("candidateSha256")
            == state.get("currentCandidateSha256")
            and not validate_contract(
                manifest,
                "artifact-approval.schema.json",
                NEXT_SCHEMA_REGISTRY,
            )
        ):
            matches.append((relative, manifest, sha256_bytes(payload)))
    if len(matches) != 1:
        raise ProjectIOError(
            "ACTIVE_ARTIFACT_NOT_UNIQUE",
            root_path,
            "批准等待态必须精确绑定一份当前 artifact manifest。",
        )
    return matches[0]


def approve(
    project_root: Path,
    artifact_manifest_sha256: str,
    decision_path: str | None = None,
) -> dict[str, object]:
    """Record one hash-bound decision and promote only exact APPROVE bytes."""
    files = ProjectFiles.open(project_root)
    try:
        manifest_path, manifest = _approval_artifact(
            files, artifact_manifest_sha256
        )
        artifact_root = Path(manifest_path).parent.as_posix()
        approval_path = f"{artifact_root}/approval.json"
        if decision_path is None:
            try:
                existing = files.read_json(approval_path)
            except ProjectIOError as error:
                if error.code != "PROJECT_PATH_MISSING":
                    raise
                existing = None
            if isinstance(existing, Mapping):
                decision = dict(existing)
            else:
                decision = {
                    "contract": "ai-sow-approval-v1",
                    "runId": manifest["runId"],
                    "artifactManifestSha256": artifact_manifest_sha256,
                    "reviewDecisionSha256": manifest["reviewDecisionSha256"],
                    "candidateSha256": manifest["candidateSha256"],
                    "sourceManifestSha256": manifest["sourceManifestSha256"],
                    "templateSha256": manifest["templateSha256"],
                    "effectivePolicyDecisionSha256": manifest[
                        "effectivePolicyDecisionSha256"
                    ],
                    "decision": "APPROVE",
                    "approvedAt": datetime.now(UTC).isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
        else:
            managed_decision_path = _managed_request_path(files, decision_path)
            decision_value = files.read_json(managed_decision_path)
            if not isinstance(decision_value, Mapping):
                raise ProjectIOError(
                    "APPROVAL_INVALID",
                    managed_decision_path,
                    "approval decision must be a JSON object",
                )
            decision = dict(decision_value)
        diagnostics = validate_contract(
            decision,
            "artifact-approval.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if diagnostics:
            raise ProjectIOError(
                "APPROVAL_INVALID",
                decision_path or approval_path,
                "approval decision does not satisfy the strict union",
            )
        for field in (
            "runId",
            "candidateSha256",
            "sourceManifestSha256",
            "reviewDecisionSha256",
            "templateSha256",
            "effectivePolicyDecisionSha256",
        ):
            if decision.get(field) != manifest.get(field):
                raise ProjectIOError(
                    "APPROVAL_BINDING_MISMATCH",
                    decision_path or approval_path,
                    f"approval does not bind artifact field: {field}",
                )
        if decision.get("artifactManifestSha256") != artifact_manifest_sha256:
            raise ProjectIOError(
                "APPROVAL_BINDING_MISMATCH",
                decision_path or approval_path,
                "approval does not bind the selected artifact manifest",
            )
        decision_payload = canonical_json_bytes(decision)
        existing_nonapproval = _existing_nonapproval_decision(
            files,
            manifest,
            artifact_manifest_sha256,
        )
        if existing_nonapproval is not None:
            existing_path, existing_decision = existing_nonapproval
            if canonical_json_bytes(existing_decision) != decision_payload:
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    existing_path,
                    "artifact already has a different terminal or exclusion decision",
                )
        marker = _read_active_marker(files)
        if marker is not None and marker.get("runId") != manifest["runId"]:
            raise ProjectIOError(
                "RUN_NOT_ACTIVE",
                ACTIVE_RUN_PATH,
                "工件决策不能跨越另一个 active run。",
            )
        active_decision_state: Mapping[str, object] | None = None
        if marker is not None:
            active_decision_state = _recover_active_run(files, marker)
            if (
                active_decision_state.get("phase") != "AWAITING_APPROVAL"
                or active_decision_state.get("currentCandidateSha256")
                != manifest["candidateSha256"]
            ):
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    manifest_path,
                    "工件决定只能作用于当前批准等待态的 artifact。",
                )
        if decision["decision"] == "APPROVE":
            if existing_nonapproval is not None:
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    existing_nonapproval[0],
                    "excluded or abandoned artifact cannot be approved",
                )
            files.publish_new(approval_path, decision_payload)
            publication = promote(
                artifact_manifest_sha256,
                decision,
                files=files,
            )
            result = {
                "outcome": publication.outcome,
                "generationId": publication.generation_id,
                "workbookPath": publication.workbook_path,
                "notesPath": publication.notes_path,
                "approvalPath": approval_path,
                "artifactManifestSha256": artifact_manifest_sha256,
                "diagnostics": [],
            }
            if marker is not None:
                state = dict(_recover_active_run(files, marker))
                terminal_state = _write_active_state(
                    files,
                    marker,
                    {
                        **state,
                        "phase": "DONE",
                        "wait": "NONE",
                        "result": "PUBLISHED",
                        "expectedActionIds": [],
                        "resumeFromPhase": None,
                    },
                )
                active_payload = files.read_bytes(ACTIVE_RUN_PATH)
                files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
                result["state"] = dict(terminal_state)
            return result
        decision_sha256 = sha256_bytes(decision_payload)
        run_root = f"{RUNS_ROOT}/{manifest['runId']}"
        if decision["decision"] == "EXCLUDE_DEFAULT_AUTOMATION":
            record_path = (
                f"{run_root}/decisions/exclusion-{decision_sha256}.json"
            )
            delta = _prepare_exclusion_delta(
                files,
                artifact_root=artifact_root,
                manifest=manifest,
                decision=decision,
                decision_sha256=decision_sha256,
            )
            files.publish_new(record_path, decision_payload)
            if marker is not None:
                suffix_steps = {
                    "STORY_AC",
                    "TASK",
                    "STORY_DESIGN",
                    "STORY_DESIGN_THEME_JOIN",
                    "TASK_ESTIMATION",
                    "TASK_ESTIMATION_THEME_JOIN",
                    "ADJUDICATION",
                }
                invalidated_group_ids = [
                    str(plan["groupId"])
                    for plan in _pipeline_plans(files, str(manifest["runId"]))
                    if plan.get("pipelineStep") in suffix_steps
                ]
                transition = {
                    "contract": "ai-sow-exclusion-transition-v1",
                    "runId": manifest["runId"],
                    "decisionSha256": decision_sha256,
                    "artifactManifestSha256": artifact_manifest_sha256,
                    "baseCandidateSha256": manifest["candidateSha256"],
                    "candidatePath": delta["candidatePath"],
                    "candidateSha256": delta["candidateSha256"],
                    "invalidatedGroupIds": invalidated_group_ids,
                }
                files.publish_new(
                    f"{run_root}/invalidations/exclusion-{decision_sha256}.json",
                    canonical_json_bytes(transition),
                )
                current_marker = _read_active_marker(files)
                if current_marker is None:
                    raise ProjectIOError(
                        "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "排除迁移期间 run 消失。"
                    )
                transitioned = _recover_active_run(files, current_marker)
                return _drive_public_active(
                    project_root,
                    _active_result(transitioned),
                )
            return {
                "outcome": "READY_FOR_STORY_AC",
                "nextPhase": "STORY_AC",
                "invalidated": ["STORY_AC", "TASK", "REVIEW", "ARTIFACT"],
                "decisionPath": record_path,
                **delta,
                "lowestRecoveryStage": "STAGE_2",
                "nextAction": None,
                "diagnostics": [],
            }
        record_path = f"{run_root}/decisions/abandon-{decision_sha256}.json"
        files.publish_new(record_path, decision_payload)
        result: dict[str, object] = {
            "outcome": "ABANDONED",
            "decisionPath": record_path,
            "nextAction": None,
            "diagnostics": [],
        }
        if marker is not None:
            result["state"] = dict(
                _terminalize_active_run(files, marker, result="ABANDONED")
            )
        return result
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def abandon(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        marker = _read_active_marker(files)
        if marker is None:
            return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run。")
        state = dict(_recover_active_run(files, marker))
        active_artifact = _active_artifact(files, state)
        decision_path: str | None = None
        if active_artifact is not None:
            _manifest_path, manifest, manifest_sha256 = active_artifact
            decision = {
                "contract": "ai-sow-approval-v1",
                "runId": manifest["runId"],
                "artifactManifestSha256": manifest_sha256,
                "reviewDecisionSha256": manifest["reviewDecisionSha256"],
                "candidateSha256": manifest["candidateSha256"],
                "sourceManifestSha256": manifest["sourceManifestSha256"],
                "templateSha256": manifest["templateSha256"],
                "effectivePolicyDecisionSha256": manifest[
                    "effectivePolicyDecisionSha256"
                ],
                "decision": "ABANDON",
                "reason": "用户通过公共 abandon 操作终止本轮。",
            }
            decision_payload = canonical_json_bytes(decision)
            decision_sha256 = sha256_bytes(decision_payload)
            decision_path = (
                f"{RUNS_ROOT}/{state['runId']}/decisions/"
                f"abandon-{decision_sha256}.json"
            )
            files.publish_new(decision_path, decision_payload)
        current_marker = _read_active_marker(files)
        if current_marker is None:
            raise ProjectIOError(
                "ACTIVE_RUN_MARKER_MISSING",
                ACTIVE_RUN_PATH,
                "active run marker 意外缺失。",
            )
        terminal_state = _terminalize_active_run(
            files, current_marker, result="ABANDONED"
        )
        return {
            "outcome": "ABANDONED",
            "state": dict(terminal_state),
            **({"decisionPath": decision_path} if decision_path else {}),
            "diagnostics": [],
        }
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _append_candidate_snapshot(
    files: ProjectFiles,
    run_id: str,
    model: Mapping[str, object],
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE",
            ACTIVE_RUN_PATH,
            "candidate 只能写入当前 active run。",
        )
    state = dict(_recover_active_run(files, marker))
    payload = canonical_json_bytes(model)
    candidate_sha256 = sha256_bytes(payload)
    if state.get("currentCandidateSha256") == candidate_sha256:
        current_path = str(state["currentCandidatePath"])
        if files.read_bytes(current_path) != payload:
            raise ProjectIOError(
                "RUN_CANDIDATE_HASH_MISMATCH",
                current_path,
                "当前 candidate 文件与 state hash 不一致。",
            )
        return {"path": current_path, "sha256": candidate_sha256}

    run_root, _, _ = _run_paths(run_id)
    candidate_root = f"{run_root}/candidates"
    directory = files.ensure_dir(candidate_root)
    highest_sequence = 0
    for child in directory.iterdir():
        relative = f"{candidate_root}/{child.name}"
        files.resolve(relative, expect="file")
        match = re.fullmatch(r"([0-9]{6})-([0-9a-f]{64})\.json", child.name)
        if match is None:
            raise ProjectIOError(
                "RUN_CANDIDATE_PATH_INVALID",
                relative,
                "candidate 目录包含非合同文件。",
            )
        if sha256_bytes(files.read_bytes(relative)) != match.group(2):
            raise ProjectIOError(
                "RUN_CANDIDATE_HASH_MISMATCH",
                relative,
                "历史 candidate 文件名哈希与内容不一致。",
            )
        highest_sequence = max(highest_sequence, int(match.group(1)))

    sequence = highest_sequence + 1
    candidate_path = f"{candidate_root}/{sequence:06d}-{candidate_sha256}.json"
    files.publish_new(candidate_path, payload)
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE",
            ACTIVE_RUN_PATH,
            "candidate 写入期间 active run 已变化。",
        )
    state.update(
        {
            "currentCandidateSha256": candidate_sha256,
            "currentCandidatePath": candidate_path,
        }
    )
    _write_active_state(files, marker, state)
    return {"path": candidate_path, "sha256": candidate_sha256}


def _action_paths(run_id: str, action_id: str) -> dict[str, str]:
    run_root, _, _ = _run_paths(run_id)
    if not isinstance(action_id, str) or not re.fullmatch(
        r"action-[0-9a-f]{12}", action_id
    ):
        raise ProjectIOError("ACTION_ID_INVALID", str(action_id), "action ID 格式无效。")
    root = f"{run_root}/actions/{action_id}"
    return {
        "root": root,
        "envelope": f"{root}/envelope.json",
        "packet": f"{root}/packet.json",
        "progress": f"{root}/progress.json",
        "output": f"{root}/submission.json",
        "record": f"{root}/record.json",
        "issued": f"{root}/issued.json",
        "retry": f"{root}/retry.json",
    }


def _estimate_tokens(payload: bytes) -> int:
    return (len(payload) + 3) // 4


def _phase_for_action_stage(stage: object) -> str:
    if stage in {"EPIC_FEATURE", "STORY_AC", "TASK", "REPAIR"}:
        return str(stage)
    if stage in {
        "SOURCE_AUDIT",
        "SOURCE_SCOPE",
        "STORY_DESIGN",
        "TASK_ESTIMATION",
        "THEME_JOIN",
        "ADJUDICATION",
    }:
        return "REVIEW"
    raise ProjectIOError("ACTION_STAGE_INVALID", str(stage), "action stage 不受支持。")


def _persist_issued_action(
    files: ProjectFiles,
    envelope: Mapping[str, object],
    packet_payload: bytes,
) -> None:
    run_id = str(envelope["runId"])
    action_id = str(envelope["actionId"])
    paths = _action_paths(run_id, action_id)
    envelope_payload = canonical_json_bytes(envelope)
    envelope_diagnostics = validate_contract(
        envelope, "action.schema.json", NEXT_SCHEMA_REGISTRY
    )
    if envelope_diagnostics:
        raise ProjectIOError(
            "ACTION_ENVELOPE_INVALID",
            paths["envelope"],
            "action envelope 合同无效。",
        )
    packet_sha256 = sha256_bytes(packet_payload)
    if envelope["packetSha256"] != packet_sha256:
        raise ProjectIOError(
            "ACTION_PACKET_HASH_MISMATCH",
            paths["packet"],
            "action packet hash 与 envelope 不一致。",
        )
    issued = {
        "runId": run_id,
        "actionId": action_id,
        "logicalShardId": envelope["logicalShardId"],
        "groupId": envelope["group"]["groupId"],
        "envelopeSha256": sha256_bytes(envelope_payload),
        "packetSha256": packet_sha256,
        "inputRevisionSha256": envelope["inputRevisionSha256"],
        "baseCandidateSha256": envelope["baseCandidateSha256"],
        "resultPath": envelope["outputPath"],
    }
    progress = {
        "runId": run_id,
        "actionId": action_id,
        "envelopeSha256": issued["envelopeSha256"],
        "executionAttempt": envelope["executionAttempt"],
        "hydrationLog": [],
        "executionFacts": None,
    }
    files.publish_new(paths["packet"], packet_payload)
    files.publish_new(paths["envelope"], envelope_payload)
    files.publish_new(paths["issued"], canonical_json_bytes(issued))
    files.publish_new(paths["progress"], canonical_json_bytes(progress))


def _skill_file_binding(relative_path: object) -> dict[str, str]:
    if not isinstance(relative_path, str):
        raise ProjectIOError(
            "ACTION_INSTRUCTION_PATH_INVALID", str(relative_path), "instruction path 必须是字符串。"
        )
    skill_files = ProjectFiles.open(SKILL_ROOT)
    payload = skill_files.read_bytes(relative_path)
    return {"path": relative_path, "sha256": sha256_bytes(payload)}


def _instruction_manifest(spec: Mapping[str, object]) -> dict[str, object]:
    reference_paths = spec.get("referencePaths")
    if not isinstance(reference_paths, list) or not all(
        isinstance(item, str) for item in reference_paths
    ):
        raise ProjectIOError(
            "ACTION_INSTRUCTION_PATH_INVALID", "", "referencePaths 必须是字符串数组。"
        )
    if len(set(reference_paths)) != len(reference_paths):
        raise ProjectIOError(
            "ACTION_INSTRUCTION_PATH_INVALID", "", "referencePaths 不得重复。"
        )
    return {
        "executionEnvelope": _skill_file_binding(
            "prompts/fragments/execution-envelope.md"
        ),
        "prompt": _skill_file_binding(spec.get("promptPath")),
        "references": [_skill_file_binding(path) for path in reference_paths],
    }


def _verify_instruction_manifest(envelope: Mapping[str, object]) -> bool:
    manifest = envelope.get("instructionManifest")
    if not isinstance(manifest, Mapping):
        return False
    try:
        expected = {
            "executionEnvelope": _skill_file_binding(
                "prompts/fragments/execution-envelope.md"
            ),
            "prompt": _skill_file_binding(envelope.get("promptPath")),
            "references": [
                _skill_file_binding(path)
                for path in envelope.get("referencePaths", [])
            ],
        }
    except (ProjectIOError, TypeError):
        return False
    return manifest == expected


def _envelope_for_spec(
    *,
    run_id: str,
    action_id: str,
    input_revision_sha256: str,
    base_candidate_sha256: str,
    group: Mapping[str, object],
    spec: Mapping[str, object],
    packet_sha256: str,
    execution_attempt: int,
) -> dict[str, object]:
    paths = _action_paths(run_id, action_id)
    return {
        "contract": "ai-sow-action-envelope-v1",
        "runId": run_id,
        "actionId": action_id,
        "logicalShardId": spec["logicalShardId"],
        "kind": "MODEL_ACTION",
        "stage": spec["stage"],
        "role": spec["role"],
        "executionAttempt": execution_attempt,
        "group": dict(group),
        "inputRevisionSha256": input_revision_sha256,
        "baseCandidateSha256": base_candidate_sha256,
        "promptId": spec["promptId"],
        "promptPath": spec["promptPath"],
        "packetPath": paths["packet"],
        "packetSha256": packet_sha256,
        "outputPath": paths["output"],
        "recordPath": paths["record"],
        "resultSchema": "contracts/action.schema.json",
        "resultPayloadSchema": spec["resultPayloadSchema"],
        "referencePaths": list(spec["referencePaths"]),
        "instructionManifest": _instruction_manifest(spec),
        "evidenceAllowlist": [
            {
                "evidenceId": item["evidenceId"],
                "sha256": item["sha256"],
                "locator": item["locator"],
            }
            for item in spec["evidenceCatalog"]
        ],
        "executionPolicy": {
            "contextPolicy": "FRESH_NO_HISTORY",
            "inheritConversation": False,
            "contextReuseScope": "WITHIN_ACTION_TOOL_LOOP_ONLY",
            "modelProfileId": spec["modelProfileId"],
            "modelConfigSha256": spec["modelConfigSha256"],
            "tokenAccountingRequirement": "LOCAL_ESTIMATE_MINIMUM",
            "maxOutputTokens": spec["maxOutputTokens"],
            "maxHydrationRounds": 2,
        },
        "hydrateOperation": {"name": "hydrate", "actionId": action_id},
        "submitOperation": {
            "name": "submit",
            "actionId": action_id,
            "resultPath": paths["output"],
        },
    }


def _validated_action_spec(spec: Mapping[str, object]) -> tuple[dict[str, object], bytes]:
    required = {
        "logicalShardId",
        "stage",
        "role",
        "promptId",
        "promptPath",
        "resultPayloadSchema",
        "referencePaths",
        "evidenceCatalog",
        "packet",
        "modelProfileId",
        "modelConfigSha256",
        "maxOutputTokens",
    }
    if set(spec) != required:
        raise ProjectIOError(
            "ACTION_SPEC_INVALID", "", "action spec 字段集合与冻结接口不一致。"
        )
    catalog = spec["evidenceCatalog"]
    if not isinstance(catalog, list):
        raise ProjectIOError(
            "ACTION_SPEC_INVALID", "", "evidenceCatalog 必须是数组。"
        )
    evidence_ids: set[str] = set()
    normalized_catalog: list[dict[str, object]] = []
    for item in catalog:
        if not isinstance(item, Mapping) or set(item) != {
            "evidenceId",
            "locator",
            "content",
            "sha256",
        }:
            raise ProjectIOError(
                "ACTION_SPEC_INVALID", "", "evidenceCatalog item 结构无效。"
            )
        evidence_id = item.get("evidenceId")
        content = item.get("content")
        if (
            not isinstance(evidence_id, str)
            or evidence_id in evidence_ids
            or not isinstance(content, str)
            or item.get("sha256") != sha256_bytes(content.encode("utf-8"))
        ):
            raise ProjectIOError(
                "ACTION_EVIDENCE_INVALID", "", "evidence 内容、ID 或 hash 无效。"
            )
        evidence_ids.add(evidence_id)
        normalized_catalog.append(dict(item))
    packet = {
        "logicalShardId": spec["logicalShardId"],
        "payload": spec["packet"],
        "evidenceCatalog": normalized_catalog,
    }
    return dict(spec), canonical_json_bytes(packet)


def _issue_action_group(
    files: ProjectFiles,
    run_id: str,
    specs: Sequence[Mapping[str, object]],
    *,
    max_concurrency: int,
    group_deadline_milliseconds: int,
    shard_deadline_milliseconds: int,
    pipeline_step: str | None = None,
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "action 只能发给当前 active run。"
        )
    state = dict(_recover_active_run(files, marker))
    if (
        state.get("result") is not None
        or state.get("wait") != "NONE"
        or state.get("expectedActionIds")
    ):
        raise ProjectIOError(
            "RUN_NOT_READY_FOR_ACTION",
            str(marker["statePath"]),
            "run 当前不能发放新的模型 action。",
        )
    base_candidate_sha256 = state.get("currentCandidateSha256")
    if not isinstance(base_candidate_sha256, str):
        raise ProjectIOError(
            "RUN_CANDIDATE_REQUIRED",
            str(marker["statePath"]),
            "发放模型 action 前必须先有基础 candidate。",
        )
    if not specs or len(specs) > 8:
        raise ProjectIOError("ACTION_GROUP_INVALID", "", "action group 大小必须为 1 到 8。")
    if (
        not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or max_concurrency < 1
        or max_concurrency > len(specs)
    ):
        raise ProjectIOError(
            "ACTION_GROUP_INVALID", "", "maxConcurrency 超出 action group 边界。"
        )
    if group_deadline_milliseconds < 1 or shard_deadline_milliseconds < 1:
        raise ProjectIOError("ACTION_GROUP_INVALID", "", "action deadline 必须为正数。")

    prepared = [_validated_action_spec(spec) for spec in specs]
    logical_shard_ids = [str(spec["logicalShardId"]) for spec, _ in prepared]
    if len(set(logical_shard_ids)) != len(logical_shard_ids):
        raise ProjectIOError(
            "ACTION_GROUP_INVALID", "", "logical shard ID 在 group 内必须唯一。"
        )
    stage = prepared[0][0]["stage"]
    if any(spec["stage"] != stage for spec, _ in prepared):
        raise ProjectIOError(
            "ACTION_GROUP_INVALID", "", "同一 action group 必须属于同一 stage。"
        )
    group_id = f"group-{uuid4().hex[:12]}"
    group = {
        "groupId": group_id,
        "requiredLogicalShardIds": logical_shard_ids,
        "maxConcurrency": max_concurrency,
        "groupDeadlineMilliseconds": group_deadline_milliseconds,
        "shardDeadlineMilliseconds": shard_deadline_milliseconds,
    }
    envelopes: list[dict[str, object]] = []
    for spec, packet_payload in prepared:
        action_id = f"action-{uuid4().hex[:12]}"
        envelope = _envelope_for_spec(
            run_id=run_id,
            action_id=action_id,
            input_revision_sha256=str(state["currentInputRevisionSha256"]),
            base_candidate_sha256=base_candidate_sha256,
            group=group,
            spec=spec,
            packet_sha256=sha256_bytes(packet_payload),
            execution_attempt=1,
        )
        _persist_issued_action(files, envelope, packet_payload)
        envelopes.append(envelope)

    if pipeline_step is not None:
        plan = {
            "contract": "ai-sow-pipeline-action-plan-v1",
            "pipelineStep": pipeline_step,
            "sequence": int(state["budget"]["modelActionsStarted"]),
            "groupId": group_id,
            "baseCandidateSha256": base_candidate_sha256,
            "actionIds": [item["actionId"] for item in envelopes],
            "logicalShardIds": logical_shard_ids,
        }
        files.publish_new(
            f"{RUNS_ROOT}/{run_id}/groups/{group_id}/plan.json",
            canonical_json_bytes(plan),
        )

    state.update(
        {
            "phase": _phase_for_action_stage(stage),
            "wait": "MODEL",
            "expectedActionIds": [item["actionId"] for item in envelopes],
        }
    )
    budget = dict(state["budget"])
    budget["modelActionsStarted"] = int(budget["modelActionsStarted"]) + len(envelopes)
    state["budget"] = budget
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_MISSING", ACTIVE_RUN_PATH, "active run marker 意外缺失。"
        )
    _write_active_state(files, marker, state)
    if len(envelopes) == 1:
        return envelopes[0]
    result = {
        "contract": "ai-sow-next-action-v1",
        "kind": "MODEL_ACTION_GROUP",
        "groupId": group_id,
        "maxConcurrency": max_concurrency,
        "groupDeadlineMilliseconds": group_deadline_milliseconds,
        "actions": envelopes,
    }
    if validate_contract(result, "action.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "ACTION_GROUP_INVALID", "", "生成的 action group 合同无效。"
        )
    return result


def _load_action_bundle(
    files: ProjectFiles,
    action_id: str,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
]:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "当前项目没有 active run。")
    state = _recover_active_run(files, marker)
    paths = _action_paths(str(marker["runId"]), action_id)
    envelope = _mapping(files, paths["envelope"])
    issued = _mapping(files, paths["issued"])
    packet = _mapping(files, paths["packet"])
    progress = _mapping(files, paths["progress"])
    envelope_payload = files.read_bytes(paths["envelope"])
    packet_payload = files.read_bytes(paths["packet"])
    if (
        envelope.get("contract") != "ai-sow-action-envelope-v1"
        or validate_contract(envelope, "action.schema.json", NEXT_SCHEMA_REGISTRY)
        or issued.get("envelopeSha256") != sha256_bytes(envelope_payload)
        or issued.get("packetSha256") != sha256_bytes(packet_payload)
        or envelope.get("packetSha256") != issued.get("packetSha256")
        or envelope.get("actionId") != action_id
        or envelope.get("runId") != marker["runId"]
        or progress.get("envelopeSha256") != issued.get("envelopeSha256")
        or not _verify_instruction_manifest(envelope)
    ):
        raise ProjectIOError(
            "ACTION_BINDING_INVALID", paths["envelope"], "action 文件绑定无效或已被修改。"
        )
    return state, envelope, issued, packet, progress


def hydrate(
    project_root: Path,
    action_id: str,
    evidence_ids: Sequence[str],
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        started = time.monotonic_ns()
        state, envelope, _, packet, progress_value = _load_action_bundle(files, action_id)
        if action_id not in state.get("expectedActionIds", []):
            return _blocked(
                "ACTION_NOT_EXPECTED", "该 action 不是当前等待的动作。", "/actionId"
            )
        if not evidence_ids:
            return _blocked(
                "ACTION_HYDRATION_EMPTY", "hydrate 必须请求至少一个 evidence ID。"
            )
        allowlist = {
            str(item["evidenceId"]): item
            for item in _mappings(envelope.get("evidenceAllowlist"))
        }
        requested = list(dict.fromkeys(evidence_ids))
        unknown = [item for item in requested if item not in allowlist]
        if unknown:
            return _blocked(
                "ACTION_EVIDENCE_NOT_ALLOWED",
                "hydrate 请求包含 envelope allowlist 外的 evidence ID。",
                "/evidenceIds",
            )
        progress = dict(progress_value)
        hydration_log = [dict(item) for item in _mappings(progress.get("hydrationLog"))]
        returned_before = {
            str(evidence_id)
            for item in hydration_log
            for evidence_id in item.get("returnedEvidenceIds", [])
            if isinstance(evidence_id, str)
        }
        new_ids = [item for item in requested if item not in returned_before]
        if not new_ids:
            return {
                "outcome": "REUSED",
                "actionId": action_id,
                "evidenceIds": [],
                "evidence": [],
                "diagnostics": [],
            }
        max_rounds = int(envelope["executionPolicy"]["maxHydrationRounds"])
        if len(hydration_log) >= max_rounds:
            return _blocked(
                "ACTION_HYDRATION_LIMIT_EXCEEDED",
                "该 action 已达到 hydration 轮数上限。",
                "/hydrationLog",
            )
        catalog = {
            str(item["evidenceId"]): item
            for item in _mappings(packet.get("evidenceCatalog"))
        }
        evidence: list[dict[str, object]] = []
        for evidence_id in new_ids:
            item = catalog.get(evidence_id)
            if item is None or item.get("sha256") != allowlist[evidence_id].get("sha256"):
                raise ProjectIOError(
                    "ACTION_EVIDENCE_BINDING_INVALID",
                    str(envelope["packetPath"]),
                    "packet evidence 与 envelope allowlist 不一致。",
                )
            content = item.get("content")
            if not isinstance(content, str) or sha256_bytes(content.encode("utf-8")) != item.get(
                "sha256"
            ):
                raise ProjectIOError(
                    "ACTION_EVIDENCE_BINDING_INVALID",
                    str(envelope["packetPath"]),
                    "packet evidence 内容 hash 无效。",
                )
            evidence.append(dict(item))
        response = {
            "actionId": action_id,
            "round": len(hydration_log) + 1,
            "evidence": evidence,
        }
        response_payload = canonical_json_bytes(response)
        hydration_log.append(
            {
                "round": len(hydration_log) + 1,
                "requestedEvidenceIds": requested,
                "returnedEvidenceIds": new_ids,
                "responseSha256": sha256_bytes(response_payload),
                "bytes": len(response_payload),
                "tokens": _estimate_tokens(response_payload),
                "wallMilliseconds": max(0, (time.monotonic_ns() - started) // 1_000_000),
            }
        )
        progress["hydrationLog"] = hydration_log
        paths = _action_paths(str(envelope["runId"]), action_id)
        files.write_atomic(paths["progress"], canonical_json_bytes(progress))
        return {
            "outcome": "HYDRATED",
            "actionId": action_id,
            "evidenceIds": new_ids,
            "evidence": evidence,
            "diagnostics": [],
        }
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_execution_facts(facts: Mapping[str, object]) -> None:
    if set(facts) != {
        "status",
        "failure",
        "timing",
        "modelAttempts",
        "toolAttempts",
        "usage",
        "controlPlaneTokens",
    }:
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_INVALID", "", "execution facts 字段集合无效。"
        )
    timing = facts.get("timing")
    usage = facts.get("usage")
    if (
        facts.get("status") not in {"SUCCESS", "FAILED", "LATE"}
        or not isinstance(timing, Mapping)
        or set(timing)
        != {"queueMilliseconds", "executionMilliseconds", "actionMilliseconds"}
        or not all(_is_non_negative_int(value) for value in timing.values())
        or not _is_non_negative_int(facts.get("modelAttempts"))
        or int(facts["modelAttempts"]) not in {1, 2}
        or not _is_non_negative_int(facts.get("toolAttempts"))
        or not _is_non_negative_int(facts.get("controlPlaneTokens"))
        or not isinstance(usage, Mapping)
        or set(usage)
        != {
            "accountingMode",
            "inputTokens",
            "cachedInputTokens",
            "outputTokens",
            "reasoningTokens",
            "tokenizerId",
            "tokenizerVersion",
        }
        or not all(
            _is_non_negative_int(usage.get(field))
            for field in ("inputTokens", "cachedInputTokens", "outputTokens")
        )
    ):
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_INVALID", "", "execution facts 值无效。"
        )
    mode = usage.get("accountingMode")
    failure = facts.get("failure")
    if facts.get("status") == "SUCCESS":
        if failure is not None:
            raise ProjectIOError(
                "ACTION_EXECUTION_FACTS_INVALID", "", "成功 action 的 failure 必须为 null。"
            )
    elif (
        not isinstance(failure, Mapping)
        or set(failure) != {"code", "message"}
        or not all(isinstance(failure.get(field), str) and failure.get(field) for field in ("code", "message"))
    ):
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_INVALID", "", "失败或迟到 action 必须记录结构化 failure。"
        )
    if mode == "PROVIDER_REPORTED":
        if usage.get("tokenizerId") is not None or usage.get("tokenizerVersion") is not None:
            raise ProjectIOError(
                "ACTION_EXECUTION_FACTS_INVALID", "", "provider usage 不得声明本地 tokenizer。"
            )
        reasoning = usage.get("reasoningTokens")
        if reasoning is not None and not _is_non_negative_int(reasoning):
            raise ProjectIOError(
                "ACTION_EXECUTION_FACTS_INVALID", "", "reasoning token 值无效。"
            )
    elif mode == "LOCALLY_ESTIMATED":
        if (
            usage.get("reasoningTokens") is not None
            or not isinstance(usage.get("tokenizerId"), str)
            or not usage.get("tokenizerId")
            or not isinstance(usage.get("tokenizerVersion"), str)
            or not usage.get("tokenizerVersion")
        ):
            raise ProjectIOError(
                "ACTION_EXECUTION_FACTS_INVALID",
                "",
                "本地估算必须声明 tokenizer 且 hidden reasoning 为 null。",
            )
    else:
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_INVALID", "", "usage accountingMode 无效。"
        )


def _record_action_execution(
    files: ProjectFiles,
    action_id: str,
    facts: Mapping[str, object],
) -> None:
    _, envelope, _, _, progress_value = _load_action_bundle(files, action_id)
    _validate_execution_facts(facts)
    progress = dict(progress_value)
    existing = progress.get("executionFacts")
    if existing is not None and existing != facts:
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_CONFLICT",
            _action_paths(str(envelope["runId"]), action_id)["progress"],
            "execution facts 已封存为不同内容。",
        )
    if existing == facts:
        return
    progress["executionFacts"] = dict(facts)
    files.write_atomic(
        _action_paths(str(envelope["runId"]), action_id)["progress"],
        canonical_json_bytes(progress),
    )


def record_execution(
    project_root: Path,
    action_id: str,
    facts: Mapping[str, object],
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        _record_action_execution(files, action_id, facts)
        return {"outcome": "RECORDED", "actionId": action_id, "diagnostics": []}
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _action_record_value(
    files: ProjectFiles,
    envelope: Mapping[str, object],
    issued: Mapping[str, object],
    progress: Mapping[str, object],
    *,
    submission: Mapping[str, object] | None,
    submission_sha256: str | None,
) -> dict[str, object]:
    execution_facts = progress["executionFacts"]
    if not isinstance(execution_facts, Mapping):
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_MISSING", "", "action 尚未记录执行事实。"
        )
    packet_payload = files.read_bytes(str(envelope["packetPath"]))
    return {
        "contract": "ai-sow-action-record-v1",
        "runId": envelope["runId"],
        "actionId": envelope["actionId"],
        "logicalShardId": envelope["logicalShardId"],
        "envelopeSha256": issued["envelopeSha256"],
        "packetSha256": envelope["packetSha256"],
        "inputRevisionSha256": envelope["inputRevisionSha256"],
        "baseCandidateSha256": envelope["baseCandidateSha256"],
        "modelProfileId": envelope["executionPolicy"]["modelProfileId"],
        "modelConfigSha256": envelope["executionPolicy"]["modelConfigSha256"],
        "executionAttempt": envelope["executionAttempt"],
        "status": execution_facts["status"],
        "timing": execution_facts["timing"],
        "modelAttempts": execution_facts["modelAttempts"],
        "toolAttempts": execution_facts["toolAttempts"],
        "initialPacket": {
            "bytes": len(packet_payload),
            "tokens": _estimate_tokens(packet_payload),
        },
        "hydrationLog": progress["hydrationLog"],
        "usage": execution_facts["usage"],
        "controlPlaneTokens": execution_facts["controlPlaneTokens"],
        "resultPath": envelope["outputPath"],
        "submissionSha256": submission_sha256,
        "failure": execution_facts["failure"],
        "completedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _seal_failed_action(files: ProjectFiles, action_id: str) -> Mapping[str, object]:
    _, envelope, issued, _, progress = _load_action_bundle(files, action_id)
    paths = _action_paths(str(envelope["runId"]), action_id)
    existing = _optional_json(files, paths["record"])
    if existing is not None:
        if not isinstance(existing, Mapping) or existing.get("status") not in {
            "FAILED",
            "LATE",
        }:
            raise ProjectIOError(
                "ACTION_RECORD_CONFLICT", paths["record"], "action 已封存为非失败结果。"
            )
        return existing
    execution_facts = progress.get("executionFacts")
    if not isinstance(execution_facts, Mapping):
        raise ProjectIOError(
            "ACTION_EXECUTION_FACTS_MISSING",
            paths["progress"],
            "retry 前必须记录失败 action 的执行事实。",
        )
    _validate_execution_facts(execution_facts)
    if execution_facts.get("status") not in {"FAILED", "LATE"}:
        raise ProjectIOError(
            "ACTION_EXECUTION_NOT_FAILED",
            paths["progress"],
            "retry 只能消费 FAILED 或 LATE action。",
        )
    record = _action_record_value(
        files,
        envelope,
        issued,
        progress,
        submission=None,
        submission_sha256=None,
    )
    if validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "ACTION_RECORD_INVALID", paths["record"], "失败 ActionRecord 合同无效。"
        )
    files.publish_new(paths["record"], canonical_json_bytes(record))
    return record


def _materialize_action_retry(
    files: ProjectFiles,
    action_id: str,
    envelope: Mapping[str, object],
    failed_record: Mapping[str, object],
) -> Mapping[str, object]:
    """Idempotently bind one failed attempt to its deterministic retry action."""

    run_id = str(envelope["runId"])
    paths = _action_paths(run_id, action_id)
    record_payload = files.read_bytes(paths["record"])
    failed_record_sha256 = sha256_bytes(record_payload)
    if failed_record != json.loads(record_payload.decode("utf-8")):
        raise ProjectIOError(
            "ACTION_RECORD_INVALID", paths["record"], "失败 record 复读不一致。"
        )
    attempt = int(envelope["executionAttempt"])
    if attempt >= 2 or failed_record.get("status") not in {"FAILED", "LATE"}:
        raise ProjectIOError(
            "ACTION_RETRY_INVALID", paths["record"], "当前 attempt 不允许创建 retry。"
        )
    retry_identity = {
        "contract": "ai-sow-action-retry-identity-v1",
        "runId": run_id,
        "actionId": action_id,
        "failedRecordSha256": failed_record_sha256,
        "executionAttempt": attempt + 1,
    }
    retry_action_id = (
        "action-" + sha256_bytes(canonical_json_bytes(retry_identity))[:12]
    )
    retry_paths = _action_paths(run_id, retry_action_id)
    retry_envelope = {
        **envelope,
        "actionId": retry_action_id,
        "executionAttempt": attempt + 1,
        "packetPath": retry_paths["packet"],
        "outputPath": retry_paths["output"],
        "recordPath": retry_paths["record"],
        "hydrateOperation": {"name": "hydrate", "actionId": retry_action_id},
        "submitOperation": {
            "name": "submit",
            "actionId": retry_action_id,
            "resultPath": retry_paths["output"],
        },
    }
    packet_payload = files.read_bytes(paths["packet"])
    _persist_issued_action(files, retry_envelope, packet_payload)
    transition = {
        "contract": "ai-sow-action-retry-v1",
        "runId": run_id,
        "actionId": action_id,
        "failedRecordSha256": failed_record_sha256,
        "retryActionId": retry_action_id,
        "retryEnvelopeSha256": sha256_bytes(canonical_json_bytes(retry_envelope)),
        "executionAttempt": attempt + 1,
    }
    transition_payload = canonical_json_bytes(transition)
    files.publish_new(paths["retry"], transition_payload)
    stored = _mapping(files, paths["retry"])
    if stored != transition:
        raise ProjectIOError(
            "ACTION_RETRY_CONFLICT", paths["retry"], "retry transition 绑定冲突。"
        )
    return transition


def submit(
    project_root: Path,
    action_id: str,
    result_path: str,
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        state, envelope, issued, _, progress = _load_action_bundle(files, action_id)
        paths = _action_paths(str(envelope["runId"]), action_id)
        if result_path != envelope.get("outputPath") or result_path != issued.get(
            "resultPath"
        ):
            return _blocked(
                "ACTION_RESULT_PATH_MISMATCH",
                "submit 只能读取 envelope 锁定的 result path。",
                "/resultPath",
            )
        submission_payload = files.read_bytes(result_path)
        submission_sha256 = sha256_bytes(submission_payload)
        existing_record = _optional_json(files, paths["record"])
        if existing_record is not None:
            if isinstance(existing_record, Mapping) and existing_record.get("status") in {
                "FAILED",
                "LATE",
            }:
                return _blocked(
                    "ACTION_NOT_EXPECTED",
                    "失败或迟到 attempt 已封存，后续 submission 不再接受。",
                    "/actionId",
                )
            if (
                not isinstance(existing_record, Mapping)
                or existing_record.get("submissionSha256") != submission_sha256
                or validate_contract(
                    existing_record, "action.schema.json", NEXT_SCHEMA_REGISTRY
                )
            ):
                return _blocked(
                    "ACTION_SUBMISSION_CONFLICT",
                    "该 action 已封存为不同 submission。",
                    result_path,
                )
            return {
                "outcome": "RECORDED",
                "record": dict(existing_record),
                "diagnostics": [],
            }

        binding_diagnostics = validate_action_binding(
            envelope,
            action_id=action_id,
            envelope_sha256=str(issued["envelopeSha256"]),
            input_revision_sha256=str(state["currentInputRevisionSha256"]),
            base_candidate_sha256=str(state["currentCandidateSha256"]),
            result_path=result_path,
            expected_action_ids=tuple(state.get("expectedActionIds", [])),
        )
        if binding_diagnostics:
            return _result(
                "BLOCKED",
                "action submit 绑定已过期。",
                diagnostics=binding_diagnostics,
            )
        try:
            submission = json.loads(submission_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _blocked(
                "ACTION_SUBMISSION_INVALID", "submission 不是有效 UTF-8 JSON。", result_path
            )
        payload_schema = str(envelope.get("resultPayloadSchema", ""))
        if payload_schema == "contracts/action.schema.json":
            submission_invalid = (
                not isinstance(submission, Mapping)
                or submission.get("contract") != "ai-sow-stage-result-v1"
                or bool(
                    validate_contract(
                        submission, "action.schema.json", NEXT_SCHEMA_REGISTRY
                    )
                )
            )
        elif payload_schema == "contracts/review-repair.schema.json":
            submission_invalid = (
                not isinstance(submission, Mapping)
                or submission.get("contract") != "ai-sow-review-result-v1"
                or bool(
                    validate_contract(
                        submission,
                        "review-repair.schema.json",
                        NEXT_SCHEMA_REGISTRY,
                    )
                )
            )
        else:
            submission_invalid = True
        if submission_invalid:
            return _blocked(
                "ACTION_SUBMISSION_INVALID",
                "submission 未通过 envelope 锁定的结果合同。",
                result_path,
            )
        execution_facts = progress.get("executionFacts")
        if not isinstance(execution_facts, Mapping):
            return _blocked(
                "ACTION_EXECUTION_FACTS_MISSING",
                "submit 前必须记录模型执行事实。",
                paths["progress"],
            )
        _validate_execution_facts(execution_facts)
        if execution_facts.get("status") != "SUCCESS":
            return _blocked(
                "ACTION_EXECUTION_NOT_SUCCESSFUL",
                "只有成功执行的 action 可以封存 submission。",
                paths["progress"],
            )
        record = _action_record_value(
            files,
            envelope,
            issued,
            progress,
            submission=submission,
            submission_sha256=submission_sha256,
        )
        if validate_contract(record, "action.schema.json", NEXT_SCHEMA_REGISTRY):
            raise ProjectIOError(
                "ACTION_RECORD_INVALID", paths["record"], "ActionRecord 合同无效。"
            )
        files.publish_new(paths["record"], canonical_json_bytes(record))
        marker = _read_active_marker(files)
        if marker is None:
            raise ProjectIOError(
                "ACTIVE_RUN_MARKER_MISSING", ACTIVE_RUN_PATH, "active run marker 意外缺失。"
            )
        next_state = dict(state)
        remaining = [
            item for item in state.get("expectedActionIds", []) if item != action_id
        ]
        next_state["expectedActionIds"] = remaining
        next_state["wait"] = "MODEL" if remaining else "NONE"
        budget = dict(next_state["budget"])
        budget["modelActionsCompleted"] = int(budget["modelActionsCompleted"]) + 1
        next_state["budget"] = budget
        _write_active_state(files, marker, next_state)
        return {"outcome": "RECORDED", "record": record, "diagnostics": []}
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _retry_action(files: ProjectFiles, action_id: str) -> dict[str, object]:
    state, envelope, _, _, _ = _load_action_bundle(files, action_id)
    paths = _action_paths(str(envelope["runId"]), action_id)
    record = _optional_json(files, paths["record"])
    if action_id in state.get("expectedActionIds", []):
        record = _seal_failed_action(files, action_id)
        marker = _read_active_marker(files)
        if marker is None:
            raise ProjectIOError(
                "ACTIVE_RUN_MARKER_MISSING",
                ACTIVE_RUN_PATH,
                "active run marker 意外缺失。",
            )
        state = _recover_active_run(files, marker)
    elif not isinstance(record, Mapping) or record.get("status") not in {
        "FAILED",
        "LATE",
    }:
        raise ProjectIOError(
            "ACTION_NOT_EXPECTED", "/actionId", "只能重试当前等待或已封存失败的 action。"
        )

    if state.get("phase") == "DONE" and state.get("result") == "SYSTEM_FAILED":
        return _result(
            "SYSTEM_FAILED",
            "action 已耗尽 execution attempt 预算。",
            diagnostics=(
                _diagnostic(
                    "BUDGET_EXCEEDED",
                    "该 logical shard 已达到两次 execution attempt 上限。",
                    "/executionAttempt",
                ),
            ),
        )
    transition = _optional_json(files, paths["retry"])
    if not isinstance(transition, Mapping):
        raise ProjectIOError(
            "ACTION_RETRY_MISSING", paths["retry"], "失败 action 缺少 retry transition。"
        )
    retry_action_id = str(transition.get("retryActionId", ""))
    if retry_action_id not in state.get("expectedActionIds", []):
        raise ProjectIOError(
            "ACTION_RETRY_CONFLICT", paths["retry"], "retry action 未绑定当前 state。"
        )
    return dict(
        _mapping(
            files,
            _action_paths(str(envelope["runId"]), retry_action_id)["envelope"],
        )
    )


def _apply_ready_group(
    files: ProjectFiles,
    run_id: str,
    group_id: str,
    model: Mapping[str, object],
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "group 只能应用到当前 active run。"
        )
    state = _recover_active_run(files, marker)
    if state.get("expectedActionIds") or state.get("wait") != "NONE":
        raise ProjectIOError(
            "ACTION_GROUP_INCOMPLETE", str(marker["statePath"]), "仍有必需 action 未封存。"
        )
    run_root, _, _ = _run_paths(run_id)
    actions_root = f"{run_root}/actions"
    action_directory = files.resolve(actions_root, expect="dir")
    required_ids: list[str] | None = None
    records: dict[str, tuple[str, Mapping[str, object]]] = {}
    for child in action_directory.iterdir():
        paths = _action_paths(run_id, child.name)
        envelope = _mapping(files, paths["envelope"])
        group = envelope.get("group")
        if not isinstance(group, Mapping) or group.get("groupId") != group_id:
            continue
        current_required = list(group.get("requiredLogicalShardIds", []))
        if required_ids is None:
            required_ids = current_required
        elif required_ids != current_required:
            raise ProjectIOError(
                "ACTION_GROUP_BINDING_INVALID", paths["envelope"], "group shard 清单不一致。"
            )
        record = _optional_json(files, paths["record"])
        if isinstance(record, Mapping) and record.get("status") == "SUCCESS":
            record_payload = files.read_bytes(paths["record"])
            records[str(envelope["logicalShardId"])] = (
                sha256_bytes(record_payload),
                record,
            )
    if required_ids is None or set(records) != set(required_ids):
        raise ProjectIOError(
            "ACTION_GROUP_INCOMPLETE", actions_root, "group 缺少必需 logical shard record。"
        )
    model_payload = canonical_json_bytes(model)
    model_sha256 = sha256_bytes(model_payload)
    apply_path = f"{run_root}/groups/{group_id}/applied.json"
    existing = _optional_json(files, apply_path)
    if existing is not None:
        if not isinstance(existing, Mapping) or existing.get("modelSha256") != model_sha256:
            raise ProjectIOError(
                "ACTION_GROUP_APPLY_CONFLICT", apply_path, "group 已应用为不同模型。"
            )
        return {
            "path": existing["candidatePath"],
            "sha256": existing["candidateSha256"],
        }
    candidate = _append_candidate_snapshot(files, run_id, model)
    applied = {
        "groupId": group_id,
        "modelSha256": model_sha256,
        "recordSha256s": [records[item][0] for item in required_ids],
        "candidatePath": candidate["path"],
        "candidateSha256": candidate["sha256"],
    }
    files.publish_new(apply_path, canonical_json_bytes(applied))
    return candidate


def status(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        marker = _read_active_marker(files)
        if marker is None:
            current = load_current(files)
            if current is None:
                return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run 或有效 generation。")
            next_action = {
                "contract": "ai-sow-next-action-v1",
                "kind": "DONE",
                "result": "REUSED",
                "generationManifestPath": current.manifest_path,
            }
            if validate_contract(next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY):
                raise ProjectIOError(
                    "NEXT_ACTION_INVALID", "", "生成的 DONE action 合同无效。"
                )
            return {
                "outcome": "DONE",
                "nextAction": next_action,
                "diagnostics": [],
            }
        return _active_result(_recover_active_run(files, marker))
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def run_mode(
    project_root: Path,
    mode: str,
    *,
    request: str | None = None,
    action_id: str | None = None,
    result: str | None = None,
    execution: str | None = None,
    evidence_ids: Sequence[str] = (),
    artifact_manifest_sha256: str | None = None,
    decision: str | None = None,
) -> dict[str, object]:
    try:
        supplied = {
            "request": request,
            "action_id": action_id,
            "result": result,
            "execution": execution,
            "artifact_manifest_sha256": artifact_manifest_sha256,
            "decision": decision,
        }
        if mode == "start":
            if request is None or any(
                value is not None
                for name, value in supplied.items()
                if name != "request"
            ) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "start 只接受 --request。")
            return _drive_public_active(project_root, start(project_root, request))
        if mode == "resume":
            if any(
                value is not None
                for name, value in supplied.items()
                if name != "request"
            ) or evidence_ids:
                return _blocked(
                    "CLI_ARGUMENTS_INVALID", "resume 只可选接受 --request。"
                )
            return _drive_public_active(project_root, resume(project_root, request))
        if mode == "hydrate":
            if action_id is None or any(
                value is not None
                for name, value in supplied.items()
                if name != "action_id"
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "hydrate 必须提供 --action-id，且只可附加 --evidence-id。",
                )
            return hydrate(project_root, action_id, evidence_ids)
        if mode == "submit":
            if (
                action_id is None
                or execution is None
                or request is not None
                or artifact_manifest_sha256 is not None
                or decision is not None
                or evidence_ids
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "submit 必须提供 --action-id 和 --execution；成功执行还必须提供 --result。",
                )
            files = ProjectFiles.open(project_root)
            execution_path = _managed_request_path(files, execution)
            execution_facts = files.read_json(execution_path)
            if not isinstance(execution_facts, Mapping):
                return _blocked(
                    "ACTION_EXECUTION_FACTS_INVALID",
                    "execution facts 必须是 JSON object。",
                    execution_path,
                )
            recorded = record_execution(project_root, action_id, execution_facts)
            if recorded.get("outcome") == "BLOCKED":
                return recorded
            if execution_facts.get("status") in {"FAILED", "LATE"}:
                if result is not None:
                    return _blocked(
                        "CLI_ARGUMENTS_INVALID",
                        "失败或迟到执行只提交 --action-id 和 --execution，不读取 result。",
                    )
                retry = _retry_action(files, action_id)
                if retry.get("outcome") == "SYSTEM_FAILED":
                    return retry
                return _drive_public_active(project_root, status(project_root))
            if result is None:
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "成功执行必须提供 envelope 锁定的 --result。",
                )
            submitted = submit(project_root, action_id, result)
            if submitted.get("outcome") != "RECORDED":
                return submitted
            return _drive_public_active(project_root, status(project_root))
        if mode == "approve":
            if (
                artifact_manifest_sha256 is None
                or request is not None
                or action_id is not None
                or result is not None
                or execution is not None
                or evidence_ids
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "approve 必须提供 --artifact-manifest-sha256，且只可附加 --decision。",
                )
            return approve(
                project_root,
                artifact_manifest_sha256,
                decision_path=decision,
            )
        if mode == "abandon":
            if any(value is not None for value in supplied.values()) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "abandon 不接受附加参数。")
            return abandon(project_root)
        if mode == "status":
            if any(value is not None for value in supplied.values()) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "status 不接受工件参数。")
            return _drive_public_active(project_root, status(project_root))
        return _blocked("CLI_MODE_INVALID", "不支持的运行模式。")
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)
    except (OSError, ValueError, KeyError, TypeError):
        return _blocked("ORCHESTRATION_FAILED", "生成编排未能安全完成。")


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(add_help=True, exit_on_error=False)
    parser.add_argument("--project-root", required=True)
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "start",
            "submit",
            "hydrate",
            "resume",
            "approve",
            "abandon",
            "status",
        ),
    )
    parser.add_argument("--request")
    parser.add_argument("--action-id")
    parser.add_argument("--result")
    parser.add_argument("--execution")
    parser.add_argument("--evidence-id", action="append", default=[])
    parser.add_argument("--artifact-manifest-sha256")
    parser.add_argument("--decision")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except (argparse.ArgumentError, ValueError):
        result = _blocked("CLI_ARGUMENTS_INVALID", "命令行参数无效。")
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 2
    root = Path(arguments.project_root)
    if not root.is_absolute():
        result = _blocked(
            "PROJECT_ROOT_NOT_ABSOLUTE", "--project-root 必须是绝对路径。"
        )
        exit_code = 2
    else:
        result = run_mode(
            root,
            arguments.mode,
            request=arguments.request,
            action_id=arguments.action_id,
            result=arguments.result,
            execution=arguments.execution,
            evidence_ids=arguments.evidence_id,
            artifact_manifest_sha256=arguments.artifact_manifest_sha256,
            decision=arguments.decision,
        )
        exit_code = 0 if result["outcome"] != "BLOCKED" else 2
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
