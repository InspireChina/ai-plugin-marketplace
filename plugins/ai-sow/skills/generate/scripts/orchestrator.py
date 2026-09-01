from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    load_schema_registry,
    sha256_bytes,
    validate_contract,
    validate_final_review,
    validate_generation_hash_closure,
)
from delivery_compiler import compile_delivery, read_template_catalog  # noqa: E402
from final_review import build_review_packet, record_review  # noqa: E402
from generation_store import (  # noqa: E402
    allocate_next_ids,
    cleanup_interrupted_publication,
    load_current,
    publish_success,
)
from impact import compute_impact_plan, finalize_impact_plan  # noqa: E402
from intake import IntakeRequestError, load_request, prepare_pending  # noqa: E402
from models import CurrentGeneration, Diagnostic, ImpactPlan, RunPlan  # noqa: E402
from package_renderer import PackageRenderError, render_package  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402
from scope_compiler import compile_scope, impact_plan_sha256  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_schema_registry(SKILL_ROOT)
TEMPLATE_ASSET = SKILL_ROOT / "assets/sow-template.xlsx"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"
WORK_ROOT = ".ai-sow/work"
RUN_PLAN_PATH = f"{WORK_ROOT}/run-plan.json"
SCOPE_SLICE_PATH = f"{WORK_ROOT}/scope-slice.candidate.json"
SCOPE_IDS_PATH = f"{WORK_ROOT}/scope-id-decisions.json"
SCOPE_PATH = f"{WORK_ROOT}/scope.candidate.json"
DELIVERY_SLICE_PATH = f"{WORK_ROOT}/delivery-slice.candidate.json"
DELIVERY_IDS_PATH = f"{WORK_ROOT}/delivery-id-decisions.json"
DELIVERY_PATH = f"{WORK_ROOT}/delivery.candidate.json"
REVIEW_PACKET_PATH = f"{WORK_ROOT}/review-packet.json"
FINAL_REVIEW_PATH = f"{WORK_ROOT}/final-review.json"
GENERATION_ROOT = f"{WORK_ROOT}/generation"
DISCLAIMER = "本次生成不代表客户签署、验收完成或产生法律效力。"


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _diagnostic_value(value: Diagnostic) -> dict[str, object]:
    return {
        "code": value.code,
        "message": value.message,
        "path": value.path,
        "details": dict(value.details),
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


def _impact_value(plan: ImpactPlan) -> dict[str, object]:
    return {
        "action": plan.action,
        "baselineGenerationId": plan.baseline_generation_id,
        "baselineRevisionId": plan.baseline_revision_id,
        "changedSourceIds": list(plan.changed_source_ids),
        "changedAnchorIds": list(plan.changed_anchor_ids),
        "affectedFeatureIds": list(plan.affected_feature_ids),
        "escalation": plan.escalation,
        "reasonCodes": list(plan.reason_codes),
    }


def _impact_from_value(value: object) -> ImpactPlan:
    if not isinstance(value, Mapping):
        raise ValueError("impact is not an object")
    return ImpactPlan(
        action=value["action"],  # type: ignore[arg-type]
        baseline_generation_id=value.get("baselineGenerationId"),  # type: ignore[arg-type]
        baseline_revision_id=value.get("baselineRevisionId"),  # type: ignore[arg-type]
        changed_source_ids=tuple(value.get("changedSourceIds", ())),  # type: ignore[arg-type]
        changed_anchor_ids=tuple(value.get("changedAnchorIds", ())),  # type: ignore[arg-type]
        affected_feature_ids=tuple(value.get("affectedFeatureIds", ())),  # type: ignore[arg-type]
        escalation=value["escalation"],  # type: ignore[arg-type]
        reason_codes=tuple(value.get("reasonCodes", ())),  # type: ignore[arg-type]
    )


def _run_plan_value(plan: RunPlan) -> dict[str, object]:
    return {
        "contract": "ai-sow-run-plan-v1",
        "runId": plan.run_id,
        "pendingManifestPath": plan.pending_manifest_path,
        "action": plan.action,
        "targetRevisionId": plan.target_revision_id,
        "targetGenerationId": plan.target_generation_id,
        "impact": _impact_value(plan.impact),
        "scopeCompilerContract": plan.scope_compiler_contract,
        "deliveryCompilerContract": plan.delivery_compiler_contract,
        "rendererContract": plan.renderer_contract,
    }


def _plan_from_value(value: object) -> RunPlan:
    diagnostics = validate_contract(value, "run-plan.schema.json", SCHEMA_REGISTRY)
    if diagnostics or not isinstance(value, Mapping):
        raise ProjectIOError("RUN_PLAN_INVALID", RUN_PLAN_PATH, "运行计划合同无效。")
    return RunPlan(
        run_id=str(value["runId"]),
        pending_manifest_path=str(value["pendingManifestPath"]),
        action=value["action"],  # type: ignore[arg-type]
        target_revision_id=str(value["targetRevisionId"]),
        target_generation_id=(
            str(value["targetGenerationId"])
            if value.get("targetGenerationId") is not None
            else None
        ),
        impact=_impact_from_value(value["impact"]),
        scope_compiler_contract=str(value["scopeCompilerContract"]),
        delivery_compiler_contract=str(value["deliveryCompilerContract"]),
        renderer_contract=str(value["rendererContract"]),
    )


def _write_plan(files: ProjectFiles, plan: RunPlan) -> dict[str, object]:
    value = _run_plan_value(plan)
    diagnostics = validate_contract(value, "run-plan.schema.json", SCHEMA_REGISTRY)
    if diagnostics:
        raise ProjectIOError("RUN_PLAN_INVALID", RUN_PLAN_PATH, "运行计划合同无效。")
    files.write_atomic(RUN_PLAN_PATH, canonical_json_bytes(value))
    return value


def _ensure_template(files: ProjectFiles) -> None:
    try:
        files.resolve(TEMPLATE_PATH)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
        files.publish_new(TEMPLATE_PATH, TEMPLATE_ASSET.read_bytes())


def _previous_bundles(
    files: ProjectFiles, current: CurrentGeneration | None
) -> tuple[Mapping[str, object] | None, Mapping[str, object] | None]:
    if current is None:
        return None, None
    return _mapping(files, current.scope_path), _mapping(files, current.delivery_path)


def _current_contract_changes(
    files: ProjectFiles, current: CurrentGeneration | None
) -> tuple[bool, bool, bool]:
    if current is None:
        return False, False, False
    manifest = _mapping(files, current.manifest_path)
    template_changed = manifest.get("templateSha256") != sha256_bytes(
        files.read_bytes(TEMPLATE_PATH)
    )
    renderer_changed = manifest.get("rendererContract") != "generation-renderer-v1"
    compiler_changed = (
        manifest.get("scopeCompilerContract") != "scope-compiler-v1"
        or manifest.get("deliveryCompilerContract") != "delivery-compiler-v1"
    )
    return template_changed, renderer_changed, compiler_changed


def _remove_fixed_file(files: ProjectFiles, path: str) -> None:
    target = files.root / path
    try:
        target.lstat()
    except FileNotFoundError:
        return
    files.resolve(path, expect="file").unlink()


def _clear_downstream(files: ProjectFiles, *, keep_scope: bool = False) -> None:
    paths = [
        DELIVERY_SLICE_PATH,
        DELIVERY_IDS_PATH,
        DELIVERY_PATH,
        REVIEW_PACKET_PATH,
        FINAL_REVIEW_PATH,
    ]
    if not keep_scope:
        paths[:0] = [SCOPE_SLICE_PATH, SCOPE_IDS_PATH, SCOPE_PATH]
    for path in paths:
        _remove_fixed_file(files, path)
    try:
        files.remove_managed_tree(GENERATION_ROOT, allowed_roots=(WORK_ROOT,))
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise


def _clear_staged_generation(files: ProjectFiles) -> None:
    files.remove_managed_tree(GENERATION_ROOT, allowed_roots=(WORK_ROOT,))


def _pending_is_valid(files: ProjectFiles, plan: RunPlan) -> bool:
    try:
        manifest = _mapping(files, plan.pending_manifest_path)
    except ProjectIOError:
        return False
    return manifest.get("revisionId") == plan.target_revision_id


def _scope_is_current(files: ProjectFiles, plan: RunPlan) -> bool:
    try:
        scope = _mapping(files, SCOPE_PATH)
        scope_slice = _mapping(files, SCOPE_SLICE_PATH)
    except ProjectIOError:
        return False
    return (
        scope.get("inputRevisionId") == plan.target_revision_id
        and scope_slice.get("inputRevisionId") == plan.target_revision_id
        and scope_slice.get("impactPlanSha256") == impact_plan_sha256(plan.impact)
        and not validate_contract(scope, "scope-bundle.schema.json", SCHEMA_REGISTRY)
    )


def _delivery_is_current(files: ProjectFiles, plan: RunPlan) -> bool:
    try:
        scope = _mapping(files, SCOPE_PATH)
        delivery = _mapping(files, DELIVERY_PATH)
        delivery_slice = _mapping(files, DELIVERY_SLICE_PATH)
    except ProjectIOError:
        return False
    scope_hash = sha256_bytes(canonical_json_bytes(scope))
    return (
        delivery.get("inputRevisionId") == plan.target_revision_id
        and delivery.get("scopeSha256") == scope_hash
        and delivery_slice.get("impactPlanSha256") == impact_plan_sha256(plan.impact)
        and delivery_slice.get("scopeSha256") == scope_hash
        and not validate_contract(delivery, "delivery-bundle.schema.json", SCHEMA_REGISTRY)
    )


def prepare_run(
    project_root: Path,
    request_path: str,
    *,
    now: Callable[[], datetime],
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    current = load_current(files)
    cleanup_interrupted_publication(files, current)
    pending_before = _optional_json(files, ".ai-sow/inputs/pending/manifest.json")
    plan_before = _optional_json(files, RUN_PLAN_PATH)
    pending_run = isinstance(pending_before, Mapping) and isinstance(plan_before, Mapping)
    revision_id, generation_id = allocate_next_ids(files, current)
    try:
        request = load_request(files, request_path, SCHEMA_REGISTRY)
    except IntakeRequestError as error:
        return _result("BLOCKED", "输入请求未通过校验。", diagnostics=error.diagnostics)
    intake = prepare_pending(files, request, revision_id=revision_id, now=now)
    if intake.outcome == "BLOCKED":
        return _result(
            "BLOCKED",
            "输入尚不足以继续编译。",
            diagnostics=intake.diagnostics,
            questions=list(intake.questions),
            pendingManifestPath=intake.pending_manifest_path,
        )

    _ensure_template(files)
    previous_scope, previous_delivery = _previous_bundles(files, current)
    template_changed, renderer_changed, compiler_changed = _current_contract_changes(
        files, current
    )
    impact = compute_impact_plan(
        intake.changes,
        previous_scope=previous_scope,
        previous_delivery=previous_delivery,
        baseline_generation_id=current.generation_id if current else None,
        baseline_revision_id=current.revision_id if current else None,
        template_changed=template_changed,
        renderer_changed=renderer_changed,
        compiler_contract_changed=compiler_changed,
        pending_run=pending_run,
    )
    if impact.action == "REUSE":
        assert current is not None
        files.remove_managed_tree(
            ".ai-sow/inputs/pending", allowed_roots=(".ai-sow/inputs/pending",)
        )
        return _result(
            "REUSED",
            "输入与当前有效交付完全一致。",
            generationId=current.generation_id,
            revisionId=current.revision_id,
            workbookPath=current.workbook_path,
            notesPath=current.notes_path,
            disclaimer=DISCLAIMER,
        )

    render_only = impact.action == "RENDER_ONLY"
    target_revision_id = current.revision_id if render_only and current else revision_id
    pending_manifest_path = (
        f".ai-sow/inputs/revisions/{target_revision_id}/manifest.json"
        if render_only
        else intake.pending_manifest_path
    )
    if render_only:
        files.remove_managed_tree(
            ".ai-sow/inputs/pending", allowed_roots=(".ai-sow/inputs/pending",)
        )
    plan = RunPlan(
        run_id=f"run-{target_revision_id}-{generation_id}",
        pending_manifest_path=pending_manifest_path,
        action=impact.action,
        target_revision_id=target_revision_id,
        target_generation_id=generation_id,
        impact=impact,
        scope_compiler_contract="scope-compiler-v1",
        delivery_compiler_contract="delivery-compiler-v1",
        renderer_contract="generation-renderer-v1",
    )
    plan_value = _write_plan(files, plan)
    if not pending_run:
        _clear_downstream(files)
    if render_only:
        return _result(
            "READY_TO_RENDER",
            "语义范围未变化，只需按当前模板重新渲染。",
            runPlan=plan_value,
            nextMode="publish",
        )
    return _result(
        "READY_FOR_SCOPE",
        "输入与影响边界已准备，可编写 Scope 切片。",
        runPlan=plan_value,
        nextMode="accept-scope",
        pendingAnchorsPath=intake.anchors_path,
    )


def accept_scope(
    project_root: Path,
    candidate_path: str,
    id_decisions_path: str,
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = _plan_from_value(files.read_json(RUN_PLAN_PATH))
    if plan.action in {"REUSE", "RENDER_ONLY"}:
        return _blocked("SCOPE_NOT_REQUIRED", "当前运行不需要 Scope 编译。")
    if not _pending_is_valid(files, plan):
        return _blocked("RUN_PLAN_STALE", "运行计划与 pending 输入不一致。", RUN_PLAN_PATH)
    candidate = dict(_input_mapping(files, candidate_path))
    id_decisions = _input_mapping(files, id_decisions_path)
    if candidate.get("impactPlanSha256") != impact_plan_sha256(plan.impact):
        return _blocked(
            "SCOPE_IMPACT_HASH_MISMATCH",
            "Scope 切片未绑定当前运行计划。",
            "/impactPlanSha256",
        )
    current = load_current(files)
    previous_scope, previous_delivery = _previous_bundles(files, current)
    final_impact = finalize_impact_plan(
        plan.impact, candidate, previous_scope, previous_delivery
    )
    if final_impact != plan.impact:
        plan = RunPlan(
            run_id=plan.run_id,
            pending_manifest_path=plan.pending_manifest_path,
            action=plan.action,
            target_revision_id=plan.target_revision_id,
            target_generation_id=plan.target_generation_id,
            impact=final_impact,
            scope_compiler_contract=plan.scope_compiler_contract,
            delivery_compiler_contract=plan.delivery_compiler_contract,
            renderer_contract=plan.renderer_contract,
        )
        _write_plan(files, plan)
        candidate["impactPlanSha256"] = impact_plan_sha256(final_impact)
    manifest = _mapping(files, plan.pending_manifest_path)
    pending_root = str(Path(plan.pending_manifest_path).parent)
    anchors = files.read_json(f"{pending_root}/{manifest['anchorsPath']}")
    if not isinstance(anchors, list):
        return _blocked("INPUT_ANCHORS_INVALID", "pending 锚点文件无效。")
    compilation = compile_scope(
        manifest,
        anchors,
        previous_scope,
        candidate,
        id_decisions,
        plan.impact,
    )
    if compilation.diagnostics:
        return _result(
            "BLOCKED", "Scope 编译未通过。", diagnostics=compilation.diagnostics
        )
    _clear_downstream(files, keep_scope=True)
    files.write_atomic(SCOPE_SLICE_PATH, canonical_json_bytes(candidate))
    files.write_atomic(SCOPE_IDS_PATH, canonical_json_bytes(id_decisions))
    files.write_atomic(SCOPE_PATH, canonical_json_bytes(compilation.bundle))
    return _result(
        "READY_FOR_DELIVERY",
        "完整 Scope 已接受，可编写 Delivery 切片。",
        nextMode="accept-delivery",
        scopePath=SCOPE_PATH,
        scopeSha256=compilation.bundle_sha256,
        metrics=dict(compilation.metrics),
    )


def accept_delivery(
    project_root: Path,
    candidate_path: str,
    id_decisions_path: str,
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        plan = _plan_from_value(files.read_json(RUN_PLAN_PATH))
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return _blocked("SCOPE_NOT_ACCEPTED", "必须先准备并接受 Scope。")
        raise
    if not _scope_is_current(files, plan):
        return _blocked("SCOPE_NOT_ACCEPTED", "必须先接受与当前计划一致的 Scope。")
    candidate = _input_mapping(files, candidate_path)
    id_decisions = _input_mapping(files, id_decisions_path)
    scope = _mapping(files, SCOPE_PATH)
    current = load_current(files)
    _previous_scope, previous_delivery = _previous_bundles(files, current)
    compilation = compile_delivery(
        scope,
        previous_delivery,
        candidate,
        id_decisions,
        plan.impact,
        read_template_catalog(files.resolve(TEMPLATE_PATH)),
    )
    if compilation.diagnostics:
        return _result(
            "BLOCKED", "Delivery 编译未通过。", diagnostics=compilation.diagnostics
        )
    _clear_downstream(files, keep_scope=True)
    files.write_atomic(DELIVERY_SLICE_PATH, canonical_json_bytes(candidate))
    files.write_atomic(DELIVERY_IDS_PATH, canonical_json_bytes(id_decisions))
    files.write_atomic(DELIVERY_PATH, canonical_json_bytes(compilation.bundle))
    return _result(
        "REVIEW_REQUIRED",
        "完整 Delivery 已接受，下一步准备跨层终审。",
        nextMode="prepare-review",
        deliveryPath=DELIVERY_PATH,
        deliverySha256=compilation.bundle_sha256,
        metrics=dict(compilation.metrics),
    )


def prepare_review(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = _plan_from_value(files.read_json(RUN_PLAN_PATH))
    if not _scope_is_current(files, plan) or not _delivery_is_current(files, plan):
        return _blocked(
            "DELIVERY_NOT_ACCEPTED",
            "必须先接受与当前计划一致的 Scope 和 Delivery。",
        )
    result = build_review_packet(files)
    if result.outcome == "BLOCKED":
        return _result(
            "BLOCKED",
            "跨层终审的机械预检未通过。",
            diagnostics=result.diagnostics,
            questions=list(result.questions),
        )
    return _result(
        "REVIEW_REQUIRED",
        "终审 packet 已准备，需要一次全新上下文评审。",
        nextMode="accept-review",
        packetPath=result.packet_path,
        packetSha256=result.packet_sha256,
        reviewerInstructionPath="references/final-review.md",
    )


def accept_review(project_root: Path, review_result_path: str) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = _plan_from_value(files.read_json(RUN_PLAN_PATH))
    if not _delivery_is_current(files, plan):
        return _blocked("DELIVERY_NOT_ACCEPTED", "当前 Delivery 尚未接受。")
    try:
        files.resolve(REVIEW_PACKET_PATH)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return _blocked("REVIEW_PACKET_MISSING", "必须先准备终审 packet。")
        raise
    result = record_review(files, review_result_path)
    if result.diagnostics:
        return _result(
            "BLOCKED",
            "终审结果未通过合同校验。",
            diagnostics=result.diagnostics,
            questions=list(result.questions),
        )
    if result.decision == "BLOCKED":
        return _result(
            "BLOCKED",
            "终审发现会改变范围、验收或估算的缺失事实。",
            questions=list(result.questions),
            reviewPath=result.review_path,
            reviewSha256=result.review_sha256,
        )
    return _result(
        "READY_TO_RENDER",
        "终审已通过，可渲染确定性交付包。",
        nextMode="publish",
        decision=result.decision,
        notes=list(result.notes),
        reviewPath=result.review_path,
        reviewSha256=result.review_sha256,
    )


def _object_map(
    bundle: Mapping[str, object] | None,
    collection: str,
    id_field: str,
) -> dict[str, Mapping[str, object]]:
    if bundle is None:
        return {}
    return {
        str(item[id_field]): item
        for item in _mappings(bundle.get(collection))
        if isinstance(item.get(id_field), str)
    }


def _changed_ids(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
    collection: str,
    id_field: str,
) -> tuple[set[str], set[str], set[str]]:
    before = _object_map(previous, collection, id_field)
    after = _object_map(current, collection, id_field)
    added = set(after) - set(before)
    removed = set(before) - set(after)
    updated = {
        object_id
        for object_id in set(before) & set(after)
        if canonical_json_bytes(before[object_id]) != canonical_json_bytes(after[object_id])
    }
    return added, updated, removed


def _publication_counts(
    previous_scope: Mapping[str, object] | None,
    previous_delivery: Mapping[str, object] | None,
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
) -> dict[str, object]:
    added, updated, removed = _changed_ids(
        previous_scope, scope, "features", "featureId"
    )
    story_changes = _changed_ids(
        previous_delivery, delivery, "stories", "storyId"
    )
    task_changes = _changed_ids(previous_delivery, delivery, "tasks", "taskId")
    return {
        "features": {
            "added": len(added),
            "updated": len(updated),
            "removed": len(removed),
        },
        "recomputedStories": len(set().union(*story_changes)),
        "recomputedTasks": len(set().union(*task_changes)),
    }


def _valid_review_for_publication(
    files: ProjectFiles,
    plan: RunPlan,
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
) -> tuple[Mapping[str, object] | None, tuple[Diagnostic, ...]]:
    try:
        review = _mapping(files, FINAL_REVIEW_PATH)
        packet_sha = sha256_bytes(files.read_bytes(REVIEW_PACKET_PATH))
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None, (
                _diagnostic(
                    "FINAL_REVIEW_NOT_ACCEPTED", "发布前必须完成通过的跨层终审。"
                ),
            )
        raise
    diagnostics = list(
        validate_final_review(
            review, SCHEMA_REGISTRY, expected_packet_sha256=packet_sha
        )
    )
    if review.get("decision") not in {"PASS", "PASS_WITH_NOTES"}:
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_NOT_ACCEPTED", "只有通过的终审才能进入发布。"
            )
        )
    if (
        review.get("runId") != plan.run_id
        or review.get("inputRevisionId") != plan.target_revision_id
        or review.get("scopeSha256") != sha256_bytes(canonical_json_bytes(scope))
        or review.get("deliverySha256") != sha256_bytes(canonical_json_bytes(delivery))
    ):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_BINDING_MISMATCH",
                "终审未绑定当前运行的输入、Scope 或 Delivery。",
            )
        )
    return review, tuple(
        sorted(diagnostics, key=lambda item: (item.path, item.code, item.message))
    )


def publish_run(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan = _plan_from_value(files.read_json(RUN_PLAN_PATH))
    if plan.target_generation_id is None:
        return _blocked("GENERATION_ID_MISSING", "运行计划缺少目标 generation ID。")
    current = load_current(files)
    previous_scope, previous_delivery = _previous_bundles(files, current)
    review_mode = "AUTOMATIC_FINAL_REVIEW"
    pending_root: Path | None

    if plan.action == "RENDER_ONLY":
        if current is None:
            return _blocked("CURRENT_GENERATION_MISSING", "仅渲染需要有效 current。")
        current_manifest = _mapping(files, current.manifest_path)
        scope = _mapping(files, current.scope_path)
        delivery = _mapping(files, current.delivery_path)
        review_value = current_manifest.get("finalReview")
        if not isinstance(review_value, Mapping):
            return _blocked("FINAL_REVIEW_NOT_ACCEPTED", "current 缺少有效终审。")
        review = review_value
        review_sha = str(current_manifest["finalReviewSha256"])
        review_mode = "REUSED_SCOPE_REVIEW"
        pending_root = None
        counts = {
            "features": {"added": 0, "updated": 0, "removed": 0},
            "recomputedStories": 0,
            "recomputedTasks": 0,
        }
    else:
        if not _scope_is_current(files, plan) or not _delivery_is_current(files, plan):
            return _blocked(
                "DELIVERY_NOT_ACCEPTED", "发布前必须接受当前 Scope 和 Delivery。"
            )
        scope = _mapping(files, SCOPE_PATH)
        delivery = _mapping(files, DELIVERY_PATH)
        review, diagnostics = _valid_review_for_publication(
            files, plan, scope, delivery
        )
        if diagnostics or review is None:
            return _result(
                "BLOCKED", "终审尚未允许发布。", diagnostics=diagnostics
            )
        review_sha = sha256_bytes(files.read_bytes(FINAL_REVIEW_PATH))
        pending_root = files.resolve(
            str(Path(plan.pending_manifest_path).parent), expect="dir"
        )
        counts = _publication_counts(
            previous_scope, previous_delivery, scope, delivery
        )

    input_manifest = _mapping(files, plan.pending_manifest_path)
    try:
        _clear_staged_generation(files)
        rendered = render_package(
            generation_id=plan.target_generation_id,
            template_path=files.resolve(TEMPLATE_PATH),
            output_root=files.root / GENERATION_ROOT,
            input_manifest=input_manifest,
            scope=scope,
            delivery=delivery,
            review=review,
        )
    except PackageRenderError as error:
        return _blocked(error.code, str(error), GENERATION_ROOT)

    staged_root = Path(rendered.root)
    data_root = staged_root / "data"
    data_root.mkdir()
    scope_payload = canonical_json_bytes(scope)
    delivery_payload = canonical_json_bytes(delivery)
    (data_root / "scope.json").write_bytes(scope_payload)
    (data_root / "delivery.json").write_bytes(delivery_payload)
    generation_root = f".ai-sow/generations/{plan.target_generation_id}"
    manifest = {
        "contract": "ai-sow-generation-manifest-v1",
        "generationId": plan.target_generation_id,
        "revisionId": plan.target_revision_id,
        "inputManifestPath": (
            f".ai-sow/inputs/revisions/{plan.target_revision_id}/manifest.json"
        ),
        "inputManifestSha256": sha256_bytes(
            files.read_bytes(plan.pending_manifest_path)
        ),
        "scopePath": f"{generation_root}/data/scope.json",
        "scopeSha256": sha256_bytes(scope_payload),
        "deliveryPath": f"{generation_root}/data/delivery.json",
        "deliverySha256": sha256_bytes(delivery_payload),
        "templatePath": TEMPLATE_PATH,
        "templateSha256": sha256_bytes(files.read_bytes(TEMPLATE_PATH)),
        "workbookPath": f"{generation_root}/output/sow.xlsx",
        "workbookSha256": rendered.workbook_sha256,
        "notesPath": f"{generation_root}/output/sow-notes.md",
        "notesSha256": rendered.notes_sha256,
        "scopeCompilerContract": plan.scope_compiler_contract,
        "deliveryCompilerContract": plan.delivery_compiler_contract,
        "rendererContract": plan.renderer_contract,
        "decision": review["decision"],
        "reviewMode": review_mode,
        "impact": _impact_value(plan.impact),
        "changeCounts": counts,
        "finalReview": review,
        "finalReviewSha256": review_sha,
        "publicationComplete": True,
    }
    manifest_diagnostics = validate_generation_hash_closure(
        manifest, SCHEMA_REGISTRY
    )
    if manifest_diagnostics:
        return _result(
            "BLOCKED",
            "generation manifest 未通过发布前校验。",
            diagnostics=manifest_diagnostics,
        )
    (staged_root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    publication = publish_success(
        files,
        target_revision_id=plan.target_revision_id,
        target_generation_id=plan.target_generation_id,
        pending_root=pending_root,
        staged_generation_root=staged_root,
    )
    return _result(
        "PUBLISHED",
        "已发布新的不可变 SOW generation。",
        decision=publication.decision,
        featureCounts=dict(publication.feature_counts),
        recomputedStoryCount=publication.recomputed_story_count,
        recomputedTaskCount=publication.recomputed_task_count,
        workbookPath=publication.workbook_path,
        notesPath=publication.notes_path,
        disclaimer=DISCLAIMER,
    )


def status(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    plan_value = _optional_json(files, RUN_PLAN_PATH)
    if plan_value is None:
        current = load_current(files)
        if current is None:
            return _blocked("RUN_NOT_PREPARED", "尚未准备生成运行。")
        return _result(
            "REUSED",
            "当前有效交付可用。",
            nextMode="prepare",
            generationId=current.generation_id,
            revisionId=current.revision_id,
            workbookPath=current.workbook_path,
            notesPath=current.notes_path,
            disclaimer=DISCLAIMER,
        )
    plan = _plan_from_value(plan_value)
    if not _pending_is_valid(files, plan):
        return _blocked("RUN_PLAN_STALE", "运行计划与输入不一致。", RUN_PLAN_PATH)
    if plan.action == "RENDER_ONLY":
        return _result(
            "READY_TO_RENDER",
            "当前运行只需渲染。",
            nextMode="publish",
            missingArtifacts=[],
        )
    if not _scope_is_current(files, plan):
        return _result(
            "READY_FOR_SCOPE",
            "等待接受 Scope 切片。",
            nextMode="accept-scope",
            missingArtifacts=[SCOPE_SLICE_PATH, SCOPE_IDS_PATH, SCOPE_PATH],
        )
    if not _delivery_is_current(files, plan):
        return _result(
            "READY_FOR_DELIVERY",
            "等待接受 Delivery 切片。",
            nextMode="accept-delivery",
            missingArtifacts=[DELIVERY_SLICE_PATH, DELIVERY_IDS_PATH, DELIVERY_PATH],
        )
    final_review = _optional_json(files, FINAL_REVIEW_PATH)
    if final_review is None:
        packet_exists = _optional_json(files, REVIEW_PACKET_PATH) is not None
        return _result(
            "REVIEW_REQUIRED",
            "Delivery 已就绪，等待跨层终审。",
            nextMode="accept-review" if packet_exists else "prepare-review",
            missingArtifacts=[FINAL_REVIEW_PATH]
            if packet_exists
            else [REVIEW_PACKET_PATH, FINAL_REVIEW_PATH],
        )
    packet = _optional_json(files, REVIEW_PACKET_PATH)
    if not isinstance(packet, Mapping):
        return _blocked("REVIEW_PACKET_MISSING", "终审结果缺少对应 review packet。")
    review_diagnostics = validate_final_review(
        final_review,
        SCHEMA_REGISTRY,
        expected_packet_sha256=sha256_bytes(files.read_bytes(REVIEW_PACKET_PATH)),
    )
    if review_diagnostics:
        return _result(
            "BLOCKED",
            "终审结果与当前 review packet 不一致。",
            diagnostics=review_diagnostics,
        )
    if not isinstance(final_review, Mapping) or final_review.get("decision") == "BLOCKED":
        questions = [
            str(item["question"])
            for item in _mappings(final_review.get("questions"))
            if isinstance(item.get("question"), str)
        ] if isinstance(final_review, Mapping) else []
        return _result(
            "BLOCKED",
            "终审仍有阻塞问题。",
            questions=questions,
            nextMode="prepare",
        )
    return _result(
        "READY_TO_RENDER",
        "终审结果已存在，等待渲染。",
        nextMode="publish",
        missingArtifacts=[GENERATION_ROOT],
    )


def run_mode(
    project_root: Path,
    mode: str,
    *,
    request: str | None = None,
    candidate: str | None = None,
    ids: str | None = None,
    review: str | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    clock = now or (lambda: datetime.now(UTC))
    try:
        if mode == "prepare":
            if request is None or candidate is not None or ids is not None or review is not None:
                return _blocked("CLI_ARGUMENTS_INVALID", "prepare 只接受 --request。")
            return prepare_run(project_root, request, now=clock)
        if mode == "accept-scope":
            if candidate is None or ids is None or request is not None or review is not None:
                return _blocked(
                    "CLI_ARGUMENTS_INVALID", "accept-scope 必须提供 --candidate 和 --ids。"
                )
            return accept_scope(project_root, candidate, ids)
        if mode == "accept-delivery":
            if candidate is None or ids is None or request is not None or review is not None:
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "accept-delivery 必须提供 --candidate 和 --ids。",
            )
            return accept_delivery(project_root, candidate, ids)
        if mode == "prepare-review":
            if any(value is not None for value in (request, candidate, ids, review)):
                return _blocked("CLI_ARGUMENTS_INVALID", "prepare-review 不接受工件参数。")
            return prepare_review(project_root)
        if mode == "accept-review":
            if review is None or any(
                value is not None for value in (request, candidate, ids)
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID", "accept-review 必须且只提供 --review。"
                )
            return accept_review(project_root, review)
        if mode == "publish":
            if any(value is not None for value in (request, candidate, ids, review)):
                return _blocked("CLI_ARGUMENTS_INVALID", "publish 不接受工件参数。")
            return publish_run(project_root)
        if mode == "status":
            if any(value is not None for value in (request, candidate, ids, review)):
                return _blocked("CLI_ARGUMENTS_INVALID", "status 不接受工件参数。")
            return status(project_root)
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
            "prepare",
            "accept-scope",
            "accept-delivery",
            "prepare-review",
            "accept-review",
            "publish",
            "status",
        ),
    )
    parser.add_argument("--request")
    parser.add_argument("--candidate")
    parser.add_argument("--ids")
    parser.add_argument("--review")
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
            candidate=arguments.candidate,
            ids=arguments.ids,
            review=arguments.review,
        )
        exit_code = 0 if result["outcome"] != "BLOCKED" else 2
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
