from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    load_schema_registry,
    sha256_bytes,
    validate_contract,
    validate_final_review,
)
from delivery_compiler import compile_delivery, read_template_catalog  # noqa: E402
from generation_store import load_current  # noqa: E402
from models import (  # noqa: E402
    Diagnostic,
    FinalReviewResult,
    ImpactPlan,
    ReviewPacketResult,
)
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402
from scope_compiler import compile_scope, impact_plan_sha256  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_schema_registry(SKILL_ROOT)
RUN_PLAN_PATH = ".ai-sow/work/run-plan.json"
SCOPE_SLICE_PATH = ".ai-sow/work/scope-slice.candidate.json"
SCOPE_IDS_PATH = ".ai-sow/work/scope-id-decisions.json"
SCOPE_PATH = ".ai-sow/work/scope.candidate.json"
DELIVERY_SLICE_PATH = ".ai-sow/work/delivery-slice.candidate.json"
DELIVERY_IDS_PATH = ".ai-sow/work/delivery-id-decisions.json"
DELIVERY_PATH = ".ai-sow/work/delivery.candidate.json"
PACKET_PATH = ".ai-sow/work/review-packet.json"
REVIEW_PATH = ".ai-sow/work/final-review.json"
TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    value = files.read_json(path)
    if not isinstance(value, Mapping):
        raise ProjectIOError("PROJECT_CONTRACT_INVALID", path, "JSON 必须是对象。")
    return value


def _input_mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(files.root).as_posix()
        except ValueError as error:
            raise ProjectIOError(
                "PROJECT_PATH_OUTSIDE_ROOT", path, "终审结果必须位于项目目录内。"
            ) from error
    else:
        relative = path
    return _mapping(files, relative)


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _impact(value: object) -> ImpactPlan:
    if not isinstance(value, Mapping):
        raise ValueError("invalid impact")
    return ImpactPlan(
        action=value["action"],  # type: ignore[arg-type]
        baseline_generation_id=value.get("baselineGenerationId"),  # type: ignore[arg-type]
        baseline_revision_id=value.get("baselineRevisionId"),  # type: ignore[arg-type]
        changed_source_ids=tuple(_ids(value.get("changedSourceIds"))),
        changed_anchor_ids=tuple(_ids(value.get("changedAnchorIds"))),
        affected_feature_ids=tuple(_ids(value.get("affectedFeatureIds"))),
        escalation=value["escalation"],  # type: ignore[arg-type]
        reason_codes=tuple(_ids(value.get("reasonCodes"))),
    )


def _previous_bundles(files: ProjectFiles):
    current = load_current(files)
    if current is None:
        return current, None, None, None
    manifest = _mapping(files, current.manifest_path)
    return (
        current,
        _mapping(files, current.scope_path),
        _mapping(files, current.delivery_path),
        manifest,
    )


def _artifact(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "sha256": sha256_bytes(payload)}


def _all_object_ids(bundle: Mapping[str, object], *, delivery: bool) -> set[str]:
    fields = (
        (
            ("stories", "storyId"),
            ("acceptanceCriteria", "acceptanceCriterionId"),
            ("tasks", "taskId"),
            ("dependencies", "dependencyId"),
        )
        if delivery
        else (
            ("epics", "epicId"),
            ("features", "featureId"),
            ("commitments", "commitmentId"),
            ("effectiveStartItems", "effectiveStartItemId"),
            ("designItems", "designItemId"),
            ("designDecisions", "designDecisionId"),
            ("integrations", "integrationId"),
            ("nfrs", "nfrId"),
            ("assumptions", "assumptionId"),
            ("responsibilityBoundaries", "responsibilityBoundaryId"),
        )
    )
    return {
        str(item[field])
        for collection, field in fields
        for item in _mappings(bundle.get(collection))
        if isinstance(item.get(field), str)
    }


def _decision_summary(*ledgers: Mapping[str, object]) -> dict[str, list[str]]:
    result = {"createdIds": [], "changedIds": [], "preservedIds": []}
    for ledger in ledgers:
        for decision in _mappings(ledger.get("decisions")):
            object_id = decision.get("objectId")
            if not isinstance(object_id, str):
                continue
            disposition = decision.get("disposition")
            if disposition == "NEW":
                result["createdIds"].append(object_id)
            elif disposition == "CHANGED":
                result["changedIds"].append(object_id)
            elif disposition in {"UNCHANGED", "CLARIFIED"}:
                result["preservedIds"].append(object_id)
    return {key: sorted(set(values)) for key, values in result.items()}


def _source_ref_inventory(
    manifest: Mapping[str, object],
    scope: Mapping[str, object],
    manifest_root: str,
) -> list[dict[str, object]]:
    source_paths = {
        str(source["sourceId"]): f"{manifest_root}/{source['path']}"
        for source in _mappings(manifest.get("sources"))
        if isinstance(source.get("sourceId"), str) and isinstance(source.get("path"), str)
    }
    inventory: dict[tuple[str, str, str], dict[str, object]] = {}
    for collection in (
        "epics",
        "features",
        "commitments",
        "effectiveStartItems",
        "designItems",
        "designDecisions",
        "integrations",
        "nfrs",
        "assumptions",
    ):
        for item in _mappings(scope.get(collection)):
            for ref in _mappings(item.get("sourceRefs")):
                source_id = ref.get("sourceId")
                anchor_id = ref.get("anchorId")
                sha256 = ref.get("sha256")
                if not all(isinstance(value, str) for value in (source_id, anchor_id, sha256)):
                    continue
                inventory[(str(source_id), str(anchor_id), str(sha256))] = {
                    "sourceId": source_id,
                    "anchorId": anchor_id,
                    "locator": ref.get("locator"),
                    "sha256": sha256,
                    "snapshotPath": source_paths.get(str(source_id), ""),
                }
    return [inventory[key] for key in sorted(inventory)]


def build_review_packet(files: ProjectFiles) -> ReviewPacketResult:
    run_plan = _mapping(files, RUN_PLAN_PATH)
    scope_slice = _mapping(files, SCOPE_SLICE_PATH)
    scope_ids = _mapping(files, SCOPE_IDS_PATH)
    scope = _mapping(files, SCOPE_PATH)
    delivery_slice = _mapping(files, DELIVERY_SLICE_PATH)
    delivery_ids = _mapping(files, DELIVERY_IDS_PATH)
    delivery = _mapping(files, DELIVERY_PATH)
    impact = _impact(run_plan.get("impact"))
    manifest_path = str(run_plan["pendingManifestPath"])
    manifest = _mapping(files, manifest_path)
    manifest_root = str(Path(manifest_path).parent)
    anchors_path = f"{manifest_root}/{manifest['anchorsPath']}"
    anchors = files.read_json(anchors_path)
    if not isinstance(anchors, list):
        anchors = []
    current, previous_scope, previous_delivery, previous_manifest = _previous_bundles(files)

    diagnostics: list[Diagnostic] = []
    diagnostics.extend(validate_contract(run_plan, "run-plan.schema.json", SCHEMA_REGISTRY))
    scope_compilation = compile_scope(
        manifest,
        anchors,
        previous_scope,
        scope_slice,
        scope_ids,
        impact,
    )
    diagnostics.extend(scope_compilation.diagnostics)
    if canonical_json_bytes(scope_compilation.bundle) != canonical_json_bytes(scope):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_SCOPE_RECOMPILE_MISMATCH",
                "完整 Scope 与其切片、ID 决定及运行计划不一致。",
                SCOPE_PATH,
            )
        )
    template = read_template_catalog(files.resolve(TEMPLATE_PATH))
    delivery_compilation = compile_delivery(
        scope,
        previous_delivery,
        delivery_slice,
        delivery_ids,
        impact,
        template,
    )
    diagnostics.extend(delivery_compilation.diagnostics)
    if canonical_json_bytes(delivery_compilation.bundle) != canonical_json_bytes(delivery):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_DELIVERY_RECOMPILE_MISMATCH",
                "完整 Delivery 与其切片、ID 决定及运行计划不一致。",
                DELIVERY_PATH,
            )
        )
    if diagnostics:
        return ReviewPacketResult(
            outcome="BLOCKED",
            packet_path=None,
            packet_sha256=None,
            diagnostics=_sort(diagnostics),
            questions=(),
        )

    previous_ids: set[str] = set()
    if previous_scope is not None:
        previous_ids.update(_all_object_ids(previous_scope, delivery=False))
    if previous_delivery is not None:
        previous_ids.update(_all_object_ids(previous_delivery, delivery=True))
    current_ids = _all_object_ids(scope, delivery=False) | _all_object_ids(
        delivery, delivery=True
    )
    summary = _decision_summary(scope_ids, delivery_ids)
    summary.update(
        {
            "removedIds": sorted(previous_ids - current_ids),
            "affectedFeatureIds": sorted(
                set(_ids(scope_slice.get("replacesFeatureIds")))
                or set(impact.affected_feature_ids)
            ),
        }
    )
    prior = None
    if current is not None and previous_manifest is not None:
        prior = {
            "generationId": current.generation_id,
            "revisionId": current.revision_id,
            "scopeSha256": previous_manifest.get("scopeSha256"),
            "deliverySha256": previous_manifest.get("deliverySha256"),
        }
    packet = {
        "contract": "ai-sow-final-review-packet-v1",
        "runId": run_plan["runId"],
        "inputRevisionId": run_plan["targetRevisionId"],
        "impact": run_plan["impact"],
        "artifacts": {
            "inputManifest": _artifact(manifest_path, files.read_bytes(manifest_path)),
            "scope": _artifact(SCOPE_PATH, files.read_bytes(SCOPE_PATH)),
            "delivery": _artifact(DELIVERY_PATH, files.read_bytes(DELIVERY_PATH)),
            "scopeIdDecisions": _artifact(SCOPE_IDS_PATH, files.read_bytes(SCOPE_IDS_PATH)),
            "deliveryIdDecisions": _artifact(
                DELIVERY_IDS_PATH, files.read_bytes(DELIVERY_IDS_PATH)
            ),
            "template": _artifact(TEMPLATE_PATH, files.read_bytes(TEMPLATE_PATH)),
        },
        "bundles": {
            "inputManifest": manifest,
            "scope": scope,
            "delivery": delivery,
        },
        "sourceRefInventory": _source_ref_inventory(manifest, scope, manifest_root),
        "changeSummary": summary,
        "priorCurrent": prior,
        "mechanicalSummary": {
            "passed": True,
            "diagnosticCount": 0,
            "checks": [
                "CONTRACTS",
                "SOURCE_REFS",
                "SCOPE_RECOMPILE",
                "DELIVERY_RECOMPILE",
                "ID_DECISIONS",
                "TEMPLATE_COMPATIBILITY",
            ],
        },
    }
    payload = canonical_json_bytes(packet)
    files.write_atomic(PACKET_PATH, payload)
    return ReviewPacketResult(
        outcome="REVIEW_REQUIRED",
        packet_path=PACKET_PATH,
        packet_sha256=sha256_bytes(payload),
        diagnostics=(),
        questions=(),
    )


def _normalized_questions(value: Mapping[str, object]) -> dict[str, object]:
    result = dict(value)
    questions: list[dict[str, object]] = []
    seen: set[str] = set()
    for question in _mappings(value.get("questions")):
        text = question.get("question")
        if not isinstance(text, str):
            questions.append(dict(question))
            continue
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        item = dict(question)
        item["question"] = normalized
        questions.append(item)
    result["questions"] = questions
    return result


def _note_subjects(
    scope: Mapping[str, object], delivery: Mapping[str, object]
) -> dict[str, set[str]]:
    assumptions = {
        str(item["assumptionId"])
        for item in _mappings(scope.get("assumptions"))
        if isinstance(item.get("assumptionId"), str)
    }
    responsibilities = {
        str(item["responsibilityBoundaryId"])
        for item in _mappings(scope.get("responsibilityBoundaries"))
        if isinstance(item.get("responsibilityBoundaryId"), str)
    }
    exclusions = {
        str(item["featureId"])
        for item in _mappings(scope.get("features"))
        if isinstance(item.get("featureId"), str)
        and isinstance(item.get("scopeDecision"), Mapping)
        and item["scopeDecision"].get("decision") != "IN_SCOPE"
    }
    design_tasks = {
        str(item["taskId"])
        for item in _mappings(delivery.get("tasks"))
        if item.get("taskKind") == "DESIGN" and isinstance(item.get("taskId"), str)
    }
    estimate_boundaries: set[str] = set()
    change_triggers: set[str] = set()
    for collection, id_field in (
        ("commitments", "commitmentId"),
        ("effectiveStartItems", "effectiveStartItemId"),
        ("integrations", "integrationId"),
        ("nfrs", "nfrId"),
        ("assumptions", "assumptionId"),
    ):
        for item in _mappings(scope.get(collection)):
            object_id = item.get(id_field)
            if not isinstance(object_id, str):
                continue
            if isinstance(item.get("estimateBoundary"), str) and item["estimateBoundary"].strip():
                estimate_boundaries.add(object_id)
            if (
                isinstance(item.get("changeTrigger"), str)
                and item["changeTrigger"].strip()
            ) or (isinstance(item.get("trigger"), str) and item["trigger"].strip()):
                change_triggers.add(object_id)
    return {
        "ASSUMPTION": assumptions,
        "RESPONSIBILITY": responsibilities,
        "EXCLUSION": exclusions,
        "DESIGN_TASK": design_tasks,
        "ESTIMATE_BOUNDARY": estimate_boundaries,
        "CHANGE_TRIGGER": change_triggers,
    }


def _review_result(
    value: Mapping[str, object],
    payload: bytes,
    diagnostics: Sequence[Diagnostic],
) -> FinalReviewResult:
    failed = bool(diagnostics)
    decision = "BLOCKED" if failed else value.get("decision", "BLOCKED")
    notes = tuple(
        str(item["sowNotesText"])
        for item in _mappings(value.get("notes"))
        if isinstance(item.get("sowNotesText"), str)
    )
    questions = tuple(
        str(item["question"])
        for item in _mappings(value.get("questions"))
        if isinstance(item.get("question"), str)
    )
    return FinalReviewResult(
        decision=decision,  # type: ignore[arg-type]
        review_path=REVIEW_PATH,
        review_sha256=sha256_bytes(payload),
        notes=notes,
        questions=questions,
        diagnostics=_sort(diagnostics),
    )


def record_review(files: ProjectFiles, review_result_path: str) -> FinalReviewResult:
    packet = _mapping(files, PACKET_PATH)
    packet_payload = files.read_bytes(PACKET_PATH)
    packet_sha = sha256_bytes(packet_payload)
    raw = _input_mapping(files, review_result_path)
    value = _normalized_questions(raw)
    payload = canonical_json_bytes(value)

    try:
        existing = files.read_bytes(REVIEW_PATH)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
    else:
        if existing != payload:
            return _review_result(
                value,
                payload,
                (
                    _diagnostic(
                        "FINAL_REVIEW_CONFLICT",
                        "同一 review packet 已存在不同终审结果。",
                        REVIEW_PATH,
                    ),
                ),
            )
        return _review_result(value, payload, ())

    diagnostics = list(
        validate_final_review(
            value, SCHEMA_REGISTRY, expected_packet_sha256=packet_sha
        )
    )
    artifacts = packet.get("artifacts")
    scope_artifact = artifacts.get("scope") if isinstance(artifacts, Mapping) else None
    delivery_artifact = artifacts.get("delivery") if isinstance(artifacts, Mapping) else None
    if (
        value.get("runId") != packet.get("runId")
        or value.get("inputRevisionId") != packet.get("inputRevisionId")
        or not isinstance(scope_artifact, Mapping)
        or value.get("scopeSha256") != scope_artifact.get("sha256")
        or not isinstance(delivery_artifact, Mapping)
        or value.get("deliverySha256") != delivery_artifact.get("sha256")
    ):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_BINDING_MISMATCH",
                "终审结果未绑定当前运行、输入、Scope 或 Delivery。",
            )
        )
    bundles = packet.get("bundles")
    scope = bundles.get("scope") if isinstance(bundles, Mapping) else None
    delivery = bundles.get("delivery") if isinstance(bundles, Mapping) else None
    if isinstance(scope, Mapping) and isinstance(delivery, Mapping):
        allowed = _note_subjects(scope, delivery)
        for index, note in enumerate(_mappings(value.get("notes"))):
            category = note.get("category")
            subject_ids = set(_ids(note.get("subjectIds")))
            if not isinstance(category, str) or not subject_ids or not subject_ids <= allowed.get(category, set()):
                diagnostics.append(
                    _diagnostic(
                        "FINAL_REVIEW_NOTE_UNBOUND",
                        "终审说明必须绑定该类别真实存在的固定边界。",
                        f"/notes/{index}/subjectIds",
                    )
                )
    if diagnostics:
        return _review_result(value, payload, diagnostics)
    files.write_atomic(REVIEW_PATH, payload)
    return _review_result(value, payload, ())
