from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
from generation_store import publish_success  # noqa: E402
from orchestrator import run_mode  # noqa: E402
from runtime.project_io import ProjectFiles  # noqa: E402


NOW = lambda: datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def fixture(mode: str, name: str) -> dict[str, object]:
    return json.loads((FIXTURES / mode / name).read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def write_request(project: Path) -> str:
    request = fixture("greenfield", "request.json")
    inputs = project / "inputs"
    inputs.mkdir()
    for source in request["sources"]:
        source_path = inputs / f"{source['role'].lower()}.md"
        source_path.write_text(
            f"# {source['role']}\n\n退款申请、审核、结果通知与异常处理。\n",
            encoding="utf-8",
        )
        source["path"] = str(source_path)
    write_json(project / "request.json", request)
    return "request.json"


def decisions(candidate: dict[str, object], collections: dict[str, tuple[str, str]]):
    values = []
    for collection, (object_type, id_field) in collections.items():
        for item in candidate[collection]:
            values.append(
                {
                    "objectType": object_type,
                    "objectId": item[id_field],
                    "disposition": "NEW",
                    "meaningPreserved": False,
                    "rationale": "新对象分配稳定 ID。",
                }
            )
    return {"contract": "ai-sow-id-decisions-v1", "decisions": values}


SCOPE_COLLECTIONS = {
    "epics": ("EPIC", "epicId"),
    "features": ("FEATURE", "featureId"),
    "commitments": ("COMMITMENT", "commitmentId"),
    "effectiveStartItems": ("EFFECTIVE_START_ITEM", "effectiveStartItemId"),
    "designItems": ("DESIGN_ITEM", "designItemId"),
    "designDecisions": ("DESIGN_DECISION", "designDecisionId"),
    "integrations": ("INTEGRATION", "integrationId"),
    "nfrs": ("NFR", "nfrId"),
    "assumptions": ("ASSUMPTION", "assumptionId"),
}
DELIVERY_COLLECTIONS = {
    "stories": ("STORY", "storyId"),
    "acceptanceCriteria": ("ACCEPTANCE_CRITERION", "acceptanceCriterionId"),
    "tasks": ("TASK", "taskId"),
    "dependencies": ("DEPENDENCY", "dependencyId"),
}


def prepare_scope_files(project: Path, result: dict[str, object]) -> None:
    plan = result["runPlan"]
    bundle = fixture("greenfield", "scope.json")
    bundle["inputRevisionId"] = plan["targetRevisionId"]
    anchors = json.loads(
        (project / ".ai-sow/inputs/pending/anchors.json").read_text(encoding="utf-8")
    )
    first_anchor = {}
    for anchor in anchors:
        first_anchor.setdefault(anchor["sourceId"], anchor)
    for collection in SCOPE_COLLECTIONS:
        for item in bundle[collection]:
            item["sourceRefs"] = [
                {
                    "sourceId": first_anchor[ref["sourceId"]]["sourceId"],
                    "anchorId": first_anchor[ref["sourceId"]]["anchorId"],
                    "locator": first_anchor[ref["sourceId"]]["locator"],
                    "sha256": first_anchor[ref["sourceId"]]["sha256"],
                }
                for ref in item.get("sourceRefs", [])
            ]
    candidate = {
        "contract": "ai-sow-scope-slice-v1",
        "inputRevisionId": plan["targetRevisionId"],
        "impactPlanSha256": sha256_bytes(canonical_json_bytes(plan["impact"])),
        "replacesFeatureIds": [item["featureId"] for item in bundle["features"]],
        "newAnchorMappings": [],
        **{name: copy.deepcopy(bundle[name]) for name in SCOPE_COLLECTIONS},
        "responsibilityBoundaries": copy.deepcopy(bundle["responsibilityBoundaries"]),
    }
    write_json(project / "scope.json", candidate)
    write_json(project / "scope-ids.json", decisions(candidate, SCOPE_COLLECTIONS))


def prepare_delivery_files(project: Path, prepared: dict[str, object]) -> None:
    plan = json.loads(
        (project / ".ai-sow/work/run-plan.json").read_text(encoding="utf-8")
    )
    scope = json.loads(
        (project / ".ai-sow/work/scope.candidate.json").read_text(encoding="utf-8")
    )
    bundle = fixture("greenfield", "delivery.json")
    bundle["inputRevisionId"] = plan["targetRevisionId"]
    candidate = {
        "contract": "ai-sow-delivery-slice-v1",
        "inputRevisionId": plan["targetRevisionId"],
        "scopeSha256": sha256_bytes(canonical_json_bytes(scope)),
        "impactPlanSha256": sha256_bytes(canonical_json_bytes(plan["impact"])),
        "replacesFeatureIds": [item["featureId"] for item in scope["features"]],
        **{name: copy.deepcopy(bundle[name]) for name in DELIVERY_COLLECTIONS},
    }
    write_json(project / "delivery.json", candidate)
    write_json(
        project / "delivery-ids.json", decisions(candidate, DELIVERY_COLLECTIONS)
    )


def publish_synthetic_current(project: Path, prepared: dict[str, object]) -> None:
    plan = prepared["runPlan"]
    revision_id = plan["targetRevisionId"]
    generation_id = plan["targetGenerationId"]
    staged = project / "staged-generation"
    scope = canonical_json_bytes(fixture("greenfield", "scope.json"))
    delivery = canonical_json_bytes(fixture("greenfield", "delivery.json"))
    workbook = b"synthetic workbook"
    notes = "合成交付说明。\n".encode()
    for relative, payload in (
        ("data/scope.json", scope),
        ("data/delivery.json", delivery),
        ("output/sow.xlsx", workbook),
        ("output/sow-notes.md", notes),
    ):
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    review = {
        "contract": "ai-sow-final-review-v1",
        "runId": plan["runId"],
        "inputRevisionId": revision_id,
        "scopeSha256": sha256_bytes(scope),
        "deliverySha256": sha256_bytes(delivery),
        "packetSha256": "2" * 64,
        "decision": "PASS",
        "notes": [],
        "questions": [],
    }
    manifest = {
        "contract": "ai-sow-generation-manifest-v1",
        "generationId": generation_id,
        "revisionId": revision_id,
        "inputManifestPath": f".ai-sow/inputs/revisions/{revision_id}/manifest.json",
        "inputManifestSha256": sha256_bytes(
            (project / ".ai-sow/inputs/pending/manifest.json").read_bytes()
        ),
        "scopePath": f".ai-sow/generations/{generation_id}/data/scope.json",
        "scopeSha256": sha256_bytes(scope),
        "deliveryPath": f".ai-sow/generations/{generation_id}/data/delivery.json",
        "deliverySha256": sha256_bytes(delivery),
        "templatePath": ".ai-sow/templates/sow-template.xlsx",
        "templateSha256": sha256_bytes(
            (project / ".ai-sow/templates/sow-template.xlsx").read_bytes()
        ),
        "workbookPath": f".ai-sow/generations/{generation_id}/output/sow.xlsx",
        "workbookSha256": sha256_bytes(workbook),
        "notesPath": f".ai-sow/generations/{generation_id}/output/sow-notes.md",
        "notesSha256": sha256_bytes(notes),
        "scopeCompilerContract": "scope-compiler-v1",
        "deliveryCompilerContract": "delivery-compiler-v1",
        "rendererContract": "generation-renderer-v1",
        "changeCounts": {"features": 1, "stories": 1, "tasks": 1},
        "finalReview": review,
        "finalReviewSha256": sha256_bytes(canonical_json_bytes(review)),
    }
    write_json(staged / "manifest.json", manifest)
    publish_success(
        ProjectFiles.open(project),
        target_revision_id=revision_id,
        target_generation_id=generation_id,
        pending_root=project / ".ai-sow/inputs/pending",
        staged_generation_root=staged,
    )


def test_prepare_initial_project_requests_full_scope(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    result = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    assert result["outcome"] == "READY_FOR_SCOPE"
    assert result["runPlan"]["action"] == "FULL_COMPILE"
    assert (tmp_path / ".ai-sow/work/run-plan.json").is_file()


def test_modes_are_ordered_and_fail_closed(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    write_json(tmp_path / "delivery.json", {})
    write_json(tmp_path / "ids.json", {})
    result = run_mode(
        tmp_path,
        "accept-delivery",
        candidate="delivery.json",
        ids="ids.json",
        now=NOW,
    )
    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "SCOPE_NOT_ACCEPTED"


def test_accept_scope_writes_complete_bundle_and_advances(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    prepare_scope_files(tmp_path, prepared)
    result = run_mode(
        tmp_path,
        "accept-scope",
        candidate="scope.json",
        ids="scope-ids.json",
        now=NOW,
    )
    assert result["outcome"] == "READY_FOR_DELIVERY", result
    assert result["scopeSha256"] == sha256_bytes(
        (tmp_path / ".ai-sow/work/scope.candidate.json").read_bytes()
    )


def test_accept_delivery_binds_exact_scope_and_advances_to_review(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    prepare_scope_files(tmp_path, prepared)
    scope_result = run_mode(
        tmp_path,
        "accept-scope",
        candidate="scope.json",
        ids="scope-ids.json",
        now=NOW,
    )
    assert scope_result["outcome"] == "READY_FOR_DELIVERY", scope_result
    prepare_delivery_files(tmp_path, prepared)
    result = run_mode(
        tmp_path,
        "accept-delivery",
        candidate="delivery.json",
        ids="delivery-ids.json",
        now=NOW,
    )
    assert result["outcome"] == "REVIEW_REQUIRED", result
    assert result["deliverySha256"] == sha256_bytes(
        (tmp_path / ".ai-sow/work/delivery.candidate.json").read_bytes()
    )


def test_prepare_identical_request_reuses_verified_current_outputs(
    tmp_path: Path,
) -> None:
    request_path = write_request(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    publish_synthetic_current(tmp_path, prepared)
    result = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    assert result["outcome"] == "REUSED", result
    assert result["workbookPath"].endswith("/output/sow.xlsx")
    assert not (tmp_path / ".ai-sow/inputs/pending").exists()


def test_stale_scope_candidate_is_rejected(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    prepared = run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    prepare_scope_files(tmp_path, prepared)
    candidate = json.loads((tmp_path / "scope.json").read_text(encoding="utf-8"))
    candidate["impactPlanSha256"] = "0" * 64
    write_json(tmp_path / "scope.json", candidate)
    result = run_mode(
        tmp_path,
        "accept-scope",
        candidate="scope.json",
        ids="scope-ids.json",
        now=NOW,
    )
    assert result["outcome"] == "BLOCKED"
    assert "SCOPE_IMPACT_HASH_MISMATCH" in {
        item["code"] for item in result["diagnostics"]
    }
    assert not (tmp_path / ".ai-sow/work/scope.candidate.json").exists()


def test_status_is_derived_and_read_only(tmp_path: Path) -> None:
    request_path = write_request(tmp_path)
    run_mode(tmp_path, "prepare", request=request_path, now=NOW)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    first = run_mode(tmp_path, "status", now=NOW)
    second = run_mode(tmp_path, "status", now=NOW)
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert first["outcome"] == "READY_FOR_SCOPE"
    assert first["nextMode"] == "accept-scope"
    assert before == after


def test_cli_rejects_relative_project_root(capsys) -> None:
    from orchestrator import main

    exit_code = main(["--project-root", "relative", "--mode", "status"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["outcome"] == "BLOCKED"
    assert payload["diagnostics"][0]["code"] == "PROJECT_ROOT_NOT_ABSOLUTE"


def test_cli_argument_error_emits_one_json_object_without_stderr(capsys) -> None:
    from orchestrator import main

    exit_code = main(["--mode", "status"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert payload["diagnostics"][0]["code"] == "CLI_ARGUMENTS_INVALID"
    assert captured.err == ""
