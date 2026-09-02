from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts/validate.py"
CONTEXT_SCRIPT = SKILL_ROOT / "scripts/prepare_context.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_review.py"
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from read_template import read_contract  # noqa: E402
from prepare_context import asis_context, design_context  # noqa: E402
from runtime.handoff import (  # noqa: E402
    Artifact,
    OwnerContract,
    canonical_json_bytes,
    publish_owner,
    sha256_bytes,
)
from runtime.project_io import ProjectFiles  # noqa: E402


PROJECT = {
    "projectId": "project-task-tests",
    "projectName": "Task validator tests",
    "pluginVersion": "0.1.0-beta.1",
    "sowStandardVersion": "1.3",
}
SOURCE_PATH = "sources/task-source.md"
REQUIREMENTS = {
    "sourceDocuments": [{"sourceDocumentId": "source-task", "file": SOURCE_PATH}],
    "features": [],
}
ASIS = {
    "analysisScope": {"repositorySnapshots": [], "priorSowSnapshots": []},
    "evidence": [],
    "commitments": [],
    "effectiveStartItems": [
        {
            "effectiveStartItemId": "effective-start-customer-api",
            "name": "生效起点的 Customer API（客户接口）",
            "summary": "已运行的内部客户接口保持不变。",
        },
        {
            "effectiveStartItemId": "effective-start-hosting-architecture",
            "name": "现有客户档案托管架构方案",
            "summary": "既有架构方案已定义主边界，待补充环境和部署责任。",
        },
    ],
}
DESIGN = {"decisions": [], "scopeDecisions": []}
TECHNICAL = {"features": []}
DELIVERY = {
    "stories": [
        {"storyId": "story-customer-profile", "featureId": "feature-customer-profile"},
        {"storyId": "story-profile-api", "featureId": "feature-profile-api"},
        {"storyId": "story-profile-hosting-discovery", "featureId": "feature-customer-profile"},
    ],
    "acceptanceCriteria": [
        {"acceptanceCriterionId": "ac-profile-visible", "storyId": "story-customer-profile"},
        {"acceptanceCriterionId": "ac-profile-api", "storyId": "story-profile-api"},
        {
            "acceptanceCriterionId": "ac-profile-hosting-decision",
            "storyId": "story-profile-hosting-discovery",
        },
    ],
    "integrations": [
        {
            "integrationId": "integration-profile-api",
            "storyId": "story-profile-api",
            "owner": "INTERNAL",
        }
    ],
    "assumptions": [],
}

REQUIREMENT_CONTRACT = OwnerContract(
    subject="analyze-requirement",
    contract_ids=("urn:ai-sow:analyze-requirement:source-requirements:0.1",),
    validation_path=".ai-sow/validation/analyze-requirement.json",
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-requirement.md"),),
    outputs=(("requirements", ".ai-sow/data/analyze-requirement/requirements.json"),),
)
ASIS_CONTRACT = OwnerContract(
    subject="analyze-as-is",
    contract_ids=("urn:ai-sow:analyze-as-is:asis:0.2",),
    validation_path=".ai-sow/validation/analyze-as-is.json",
    reviews=(("approvedReview", ".ai-sow/reviews/analyze-as-is.md"),),
    outputs=(("asIs", ".ai-sow/data/analyze-as-is/asis.json"),),
)
DESIGN_CONTRACT = OwnerContract(
    subject="generate-design",
    contract_ids=(
        "urn:ai-sow:generate-design:design:0.2",
        "urn:ai-sow:generate-design:technical-requirements:0.2",
    ),
    validation_path=".ai-sow/validation/generate-design.json",
    reviews=(("approvedReview", ".ai-sow/reviews/generate-design.md"),),
    outputs=(
        ("design", ".ai-sow/data/generate-design/design.json"),
        ("technicalRequirements", ".ai-sow/data/generate-design/requirements.json"),
    ),
)
STORY_CONTRACT = OwnerContract(
    subject="generate-story",
    contract_ids=("urn:ai-sow:generate-story:delivery:0.4",),
    validation_path=".ai-sow/validation/generate-story.json",
    reviews=(("approvedReview", ".ai-sow/reviews/generate-story.md"),),
    outputs=(("delivery", ".ai-sow/data/generate-story/delivery.json"),),
)


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write_bytes(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def fixture() -> dict[str, object]:
    return json.loads((SKILL_ROOT / "fixtures/estimate.valid.json").read_text(encoding="utf-8"))


def test_template_reader_accepts_the_four_sheet_standard_authority() -> None:
    contract = read_contract(SKILL_ROOT / "fixtures/sow-template.xlsx")
    assert len(contract["baseUnits"]) == 37
    assert len({unit["taskFamily"] for unit in contract["baseUnits"].values()}) == 13
    assert set(contract["complexities"]) == {"S", "M", "L"}


def absent_questionnaire() -> Artifact:
    return Artifact(
        "questionnaire",
        "QUESTIONNAIRE_PRESENCE",
        "questionnaire:NOT_REQUIRED",
        sha256_bytes(canonical_json_bytes({"declaration": "NOT_REQUIRED"})),
    )


def publish_requirements(root: Path) -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/analyze-requirement.md", b"Questionnaire: NOT_REQUIRED\n")
    publish_owner(
        files,
        REQUIREMENT_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("source:source-task", "FILE", SOURCE_PATH, sha256_bytes(files.read_bytes(SOURCE_PATH))),
            absent_questionnaire(),
        ),
        {"requirements": json_bytes(REQUIREMENTS)},
    )


def publish_asis(
    root: Path,
    value: dict[str, object] | None = None,
    *,
    output_payload: bytes | None = None,
) -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/analyze-as-is.md", b"Questionnaire: NOT_REQUIRED\n")
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("requirementsValidation", "FILE", ".ai-sow/validation/analyze-requirement.json", sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json"))),
            Artifact("requirements", "FILE", ".ai-sow/data/analyze-requirement/requirements.json", sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json"))),
            absent_questionnaire(),
        ),
        {"asIs": output_payload if output_payload is not None else json_bytes(value or ASIS)},
    )


def publish_design(root: Path, value: dict[str, object] | None = None, *, review: bytes = b"Design approved.\n") -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/generate-design.md", review)
    publish_owner(
        files,
        DESIGN_CONTRACT,
        tuple(
            Artifact(name, "FILE", path, sha256_bytes(files.read_bytes(path)))
            for name, path in (
                ("project", ".ai-sow/project.json"),
                ("requirementsValidation", ".ai-sow/validation/analyze-requirement.json"),
                ("requirements", ".ai-sow/data/analyze-requirement/requirements.json"),
                ("asIsValidation", ".ai-sow/validation/analyze-as-is.json"),
                ("asIs", ".ai-sow/data/analyze-as-is/asis.json"),
            )
        ),
        {
            "design": json_bytes(value or DESIGN),
            "technicalRequirements": json_bytes(TECHNICAL),
        },
    )


def publish_story(
    root: Path,
    value: dict[str, object] | None = None,
    *,
    review: bytes = b"Story approved.\n",
    output_payload: bytes | None = None,
) -> None:
    files = ProjectFiles.open(root)
    write_bytes(root, ".ai-sow/reviews/generate-story.md", review)
    publish_owner(
        files,
        STORY_CONTRACT,
        tuple(
            Artifact(name, "FILE", path, sha256_bytes(files.read_bytes(path)))
            for name, path in (
                ("project", ".ai-sow/project.json"),
                ("requirementsValidation", ".ai-sow/validation/analyze-requirement.json"),
                ("requirements", ".ai-sow/data/analyze-requirement/requirements.json"),
                ("asIsValidation", ".ai-sow/validation/analyze-as-is.json"),
                ("asIs", ".ai-sow/data/analyze-as-is/asis.json"),
                ("designValidation", ".ai-sow/validation/generate-design.json"),
                ("design", ".ai-sow/data/generate-design/design.json"),
                ("technicalRequirements", ".ai-sow/data/generate-design/requirements.json"),
            )
        ),
        {"delivery": output_payload if output_payload is not None else json_bytes(value or DELIVERY)},
    )


def stable_ids(estimate: dict[str, object]) -> list[str]:
    return [task["taskId"] for task in estimate["tasks"]]  # type: ignore[index]


def mapped_ids(estimate: dict[str, object], key: str, value: str) -> str:
    groups: dict[str, list[str]] = {}
    for task in estimate["tasks"]:  # type: ignore[index]
        identifiers = task[key] if isinstance(task[key], list) else [task[key]]
        for identifier in identifiers:
            groups.setdefault(identifier, []).append(task[value])
    return "; ".join(f"{identifier}={','.join(ids)}" for identifier, ids in groups.items())


def task_review(
    estimate: dict[str, object],
    template_hash: str,
    *,
    rebind: dict[str, str] | None = None,
) -> str:
    tasks = estimate["tasks"]  # type: ignore[index]
    integration_map = "; ".join(
        f"{task['integrationId']}={task['taskId']}" for task in tasks if "integrationId" in task
    )
    effective_starts = sorted(
        task["matchedEffectiveStartItemId"]
        for task in tasks
        if task.get("matchedEffectiveStartItemId")
    )
    impact = ""
    if rebind:
        impact = (
            "\nImpact: NO_CHANGE\n"
            "Upstream: generate-story\n"
            f"Previous Receipt SHA-256: generate-story={rebind['old']}\n"
            f"Current Receipt SHA-256: generate-story={rebind['new']}\n"
            f"Impact Rationale: {'、'.join(stable_ids(estimate))} 均确认不受影响。\n"
        )
    return (
        "# Task 拆分评审\n\n"
        "## Story → Task\n\n"
        f"Story Map: {mapped_ids(estimate, 'storyId', 'taskId')}\n"
        f"AC Map: {mapped_ids(estimate, 'acceptanceCriterionIds', 'taskId')}\n"
        f"Stable IDs: {', '.join(stable_ids(estimate))}\n\n"
        "## 基础单元\n\n"
        f"Base Units: {', '.join(sorted({task['baseUnit'] for task in tasks}))}\n\n"
        "## 工作模式\n\n"
        f"Work Modes: {', '.join(sorted({task['workMode'] for task in tasks}))}\n\n"
        "## 复杂度\n\n"
        f"Complexities: {', '.join(sorted({task['complexity'] for task in tasks}))}\n\n"
        "## 现状依据\n\n"
        f"Effective Start IDs: {', '.join(effective_starts) if effective_starts else 'NONE'}\n\n"
        "## Integration 一对一\n\n"
        f"Integration Map: {integration_map if integration_map else 'NONE'}\n\n"
        "## 遗漏 / 重叠 / 排除理由\n\n"
        "Scope Review: PASSED\n\n"
        "## 估算前提\n\n"
        f"Template SHA-256: {template_hash}\n\n"
        "## 审查与批准\n\n"
        "Reviewer: PASS\nUser Approval: APPROVED\n"
        + impact
    )


def prepare(root: Path, *, delivery: dict[str, object] | None = None) -> bytes:
    write_bytes(root, ".ai-sow/project.json", json_bytes(PROJECT))
    write_bytes(root, SOURCE_PATH, b"Task source.\n")
    template = root / ".ai-sow/templates/sow-template.xlsx"
    template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL_ROOT / "fixtures/sow-template.xlsx", template)
    publish_requirements(root)
    publish_asis(root)
    publish_design(root)
    publish_story(root, delivery)
    estimate = fixture()
    candidate = (json.dumps(estimate, ensure_ascii=False, indent=3) + "\n").encode()
    write_bytes(root, ".ai-sow/work/generate-task/estimate.candidate.json", candidate)
    write_bytes(
        root,
        ".ai-sow/reviews/generate-task.md",
        task_review(estimate, sha256_bytes(template.read_bytes())).encode(),
    )
    return candidate


def run_validator(
    root: Path,
    mode: str = "check",
    *,
    review_path: str | None = None,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), "--project-root", str(root), "--mode", mode]
    if review_path is not None:
        command.extend(("--review-path", review_path))
    if mode in {"publish", "rebind"}:
        command.extend(("--staging-root", STAGING_ROOT))
    command.extend(extra)
    return subprocess.run(
        command,
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


STAGING_ROOT = ".ai-sow/.stage-0123456789ab"


def managed_path(root: Path, logical_path: str) -> Path:
    staged = root / STAGING_ROOT / logical_path.removeprefix(".ai-sow/")
    return staged if staged.exists() else root / logical_path


def run_context(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTEXT_SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def run_renderer(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--project-root", str(root)],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )


def prepare_review_candidate(
    root: Path,
    *,
    delivery: dict[str, object] | None = None,
) -> tuple[bytes, bytes]:
    candidate = prepare(root, delivery=delivery)
    context = run_context(root)
    assert context.returncode == 0, context.stdout
    stable_review = root / ".ai-sow/reviews/generate-task.md"
    stable_review.unlink()
    rendered = run_renderer(root)
    assert rendered.returncode == 0, rendered.stdout
    review = (root / ".ai-sow/work/generate-task/review.candidate.md").read_bytes()
    return candidate, review


def bind_review_packet(root: Path) -> str:
    packet = (root / ".ai-sow/work/generate-task/review-packet.json").read_bytes()
    digest = sha256_bytes(packet)
    write_bytes(
        root,
        ".ai-sow/work/generate-task/reviewer.json",
        canonical_json_bytes(
            {
                "algorithm": "ai-sow-owner-reviewer-v1",
                "decision": "PASS",
                "owner": "generate-task",
                "packetSha256": digest,
            }
        ),
    )
    write_bytes(
        root,
        ".ai-sow/work/generate-task/approval.json",
        canonical_json_bytes(
            {
                "algorithm": "ai-sow-owner-approval-v1",
                "decision": "APPROVED",
                "owner": "generate-task",
                "packetSha256": digest,
            }
        ),
    )
    return digest


def payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    return {diagnostic["code"] for diagnostic in payload(result)["diagnostics"]}  # type: ignore[index]


def mutate_candidate(root: Path, change: object) -> None:
    path = root / ".ai-sow/work/generate-task/estimate.candidate.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)  # type: ignore[operator]
    path.write_bytes(json_bytes(value))


def test_template_reader_exposes_rules_without_copying_calculation_values() -> None:
    contract = read_contract(SKILL_ROOT / "fixtures/sow-template.xlsx")

    assert len(contract["baseUnits"]) == 37
    assert len({unit["taskFamilyId"] for unit in contract["baseUnits"].values()}) == 13
    assert set(contract) == {"baseUnits", "taskOptions", "complexities"}
    serialized = json.dumps(contract, ensure_ascii=False)
    assert "complexityFactors" not in serialized
    assert "M档人天" not in serialized
    assert "ROUND_STORY" not in serialized


def test_fixture_covers_three_modes_three_complexities_and_integration() -> None:
    estimate = fixture()

    assert {task["workMode"] for task in estimate["tasks"]} == {"新建", "调整", "接入复用"}  # type: ignore[index]
    assert {task["complexity"] for task in estimate["tasks"]} == {"S", "M", "L"}  # type: ignore[index]
    assert [task["integrationId"] for task in estimate["tasks"] if "integrationId" in task] == ["integration-profile-api"]  # type: ignore[index]


def test_check_accepts_story_task_ac_modes_complexity_and_integration(tmp_path: Path) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_rejects_task_trace_that_cannot_reach_feature(tmp_path: Path) -> None:
    delivery = copy.deepcopy(DELIVERY)
    delivery["stories"][0].pop("featureId")  # type: ignore[index]
    prepare(tmp_path, delivery=delivery)

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert "TASK_TRACE_UNREACHABLE" in codes(result)


def test_prepare_context_writes_owner_local_reference_closure_without_calculation_values(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout
    report = payload(result)
    assert report["outcome"] == "OK"
    context_root = tmp_path / ".ai-sow/work/generate-task/context"
    manifest = json.loads((context_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["algorithm"] == "ai-sow-generate-task-context-v1"
    assert [entry["name"] for entry in manifest["inputArtifacts"]] == [
        "project",
        "asIsValidation",
        "asIs",
        "designValidation",
        "design",
        "technicalRequirements",
        "deliveryValidation",
        "delivery",
        "template",
    ]
    assert [entry["path"] for entry in manifest["fragments"]] == [
        ".ai-sow/work/generate-task/context/delivery.json",
        ".ai-sow/work/generate-task/context/design.json",
        ".ai-sow/work/generate-task/context/as-is.json",
        ".ai-sow/work/generate-task/context/technical-requirements.json",
        ".ai-sow/work/generate-task/context/template-catalog.json",
    ]
    assert manifest["reviewClaims"]["status"] == "READY"
    assert manifest["reviewClaims"]["fragment"]["path"] == (
        ".ai-sow/work/generate-task/claims.json"
    )
    assert manifest["selectedEffectiveStartItemIds"] == [
        "effective-start-customer-api",
        "effective-start-hosting-architecture",
    ]
    serialized = (context_root / "template-catalog.json").read_text(encoding="utf-8")
    assert "M档人天" not in serialized
    assert "complexityFactors" not in serialized
    assert "ROUND_STORY" not in serialized


def test_renderer_surfaces_potential_instance_collision_without_merging_distinct_units(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)

    def add_query_tasks(value: dict[str, object]) -> None:
        tasks = value["tasks"]  # type: ignore[index]
        tasks.extend(
            [
                {
                    "taskId": "task-profile-query-api",
                    "storyId": "story-customer-profile",
                    "acceptanceCriterionIds": ["ac-profile-visible"],
                    "name": "调整客户档案查询 API",
                    "baseUnit": "BU-BUSINESS-SERVICE-API",
                    "workMode": "调整",
                    "workModeRationale": "调整现有客户档案查询接口。",
                    "complexity": "M",
                    "matchedEffectiveStartItemId": "effective-start-customer-api",
                    "rationale": "按一个客户档案查询业务操作计数。",
                },
                {
                    "taskId": "task-profile-query-projection",
                    "storyId": "story-profile-hosting-discovery",
                    "acceptanceCriterionIds": ["ac-profile-hosting-decision"],
                    "name": "调整客户档案查询投影",
                    "baseUnit": "BU-BUSINESS-SERVICE-API",
                    "workMode": "调整",
                    "workModeRationale": "调整现有客户档案读模型投影。",
                    "complexity": "M",
                    "matchedEffectiveStartItemId": "effective-start-customer-api",
                    "rationale": "按一个客户档案详情和列表接口组计数。",
                },
            ]
        )

    mutate_candidate(tmp_path, add_query_tasks)
    rendered = run_renderer(tmp_path)
    assert rendered.returncode == 0, rendered.stdout
    review_path = tmp_path / ".ai-sow/work/generate-task/review.candidate.md"
    review = review_path.read_text(encoding="utf-8")
    assert (
        "Potential Instance Collisions: "
        "BU-BUSINESS-SERVICE-API@effective-start-customer-api="
        "task-profile-query-api,task-profile-query-projection"
    ) in review

    def separate_read_model(value: dict[str, object]) -> None:
        value["tasks"][-1]["baseUnit"] = "BU-DATA-MODEL"  # type: ignore[index]

    mutate_candidate(tmp_path, separate_read_model)
    rendered = run_renderer(tmp_path)
    assert rendered.returncode == 0, rendered.stdout
    review = review_path.read_text(encoding="utf-8")
    assert "Potential Instance Collisions: NONE" in review


def test_prepare_context_accepts_repository_anchored_document_evidence(
    tmp_path: Path,
) -> None:
    write_bytes(tmp_path, ".ai-sow/project.json", json_bytes(PROJECT))
    write_bytes(tmp_path, SOURCE_PATH, b"Task source.\n")
    template = tmp_path / ".ai-sow/templates/sow-template.xlsx"
    template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL_ROOT / "fixtures/sow-template.xlsx", template)
    publish_requirements(tmp_path)

    repository = {
        "repoId": "customer-portal",
        "path": "repositories/customer-portal",
    }
    evidence_path = "repositories/customer-portal/docs/current-state.md"
    write_bytes(tmp_path, evidence_path, b"Customer API evidence.\n")
    asis = copy.deepcopy(ASIS)
    asis["analysisScope"]["repositorySnapshots"] = [repository]  # type: ignore[index]
    asis["evidence"] = [
        {
            "evidenceId": "evidence-customer-api",
            "kind": "DOCUMENT",
            "reference": "customer-portal:docs/current-state.md#customer-api",
        }
    ]
    write_bytes(tmp_path, ".ai-sow/reviews/analyze-as-is.md", b"Questionnaire: NOT_REQUIRED\n")
    files = ProjectFiles.open(tmp_path)
    publish_owner(
        files,
        ASIS_CONTRACT,
        (
            Artifact("project", "FILE", ".ai-sow/project.json", sha256_bytes(files.read_bytes(".ai-sow/project.json"))),
            Artifact("requirementsValidation", "FILE", ".ai-sow/validation/analyze-requirement.json", sha256_bytes(files.read_bytes(".ai-sow/validation/analyze-requirement.json"))),
            Artifact("requirements", "FILE", ".ai-sow/data/analyze-requirement/requirements.json", sha256_bytes(files.read_bytes(".ai-sow/data/analyze-requirement/requirements.json"))),
            Artifact("repository:customer-portal", "CANONICAL_JSON", "repository:customer-portal", sha256_bytes(canonical_json_bytes(repository))),
            Artifact("evidence:evidence-customer-api", "FILE", evidence_path, sha256_bytes(files.read_bytes(evidence_path))),
            absent_questionnaire(),
        ),
        {"asIs": json_bytes(asis)},
    )
    publish_design(tmp_path)
    publish_story(tmp_path)

    result = run_context(tmp_path)

    assert result.returncode == 0, result.stdout


def test_context_closure_includes_related_design_decision_and_evidence() -> None:
    delivery = {
        "stories": [{"featureId": "feature-customer-profile"}],
        "integrations": [{"decisionIds": ["decision-profile-api"]}],
    }
    design = {
        "scopeDecisions": [
            {
                "featureId": "feature-customer-profile",
                "designItemIds": ["design-customer-profile"],
                "effectiveStartItemIds": ["effective-start-customer-api"],
            }
        ],
        "designItems": [{"designItemId": "design-customer-profile"}],
        "architectureDeltas": [
            {
                "designItemId": "design-customer-profile",
                "effectiveStartItemIds": ["effective-start-customer-api"],
            }
        ],
        "decisions": [
            {
                "designDecisionId": "decision-profile-api",
                "designItemIds": ["design-customer-profile"],
                "relatedFeatureIds": ["feature-customer-profile"],
                "effectiveStartItemIds": ["effective-start-customer-api"],
                "evidenceIds": ["evidence-customer-api"],
            }
        ],
    }
    technical = {
        "features": [
            {
                "featureId": "feature-customer-profile",
                "source": {
                    "designDecisionIds": ["decision-profile-api"],
                    "effectiveStartItemIds": ["effective-start-customer-api"],
                },
            }
        ]
    }
    asis = {
        "effectiveStartItems": [
            {"effectiveStartItemId": "effective-start-customer-api"}
        ],
        "evidence": [
            {
                "evidenceId": "evidence-customer-api",
                "supportsIds": ["feature-customer-profile"],
            }
        ],
    }

    selected_design, feature_ids, effective_start_ids, evidence_ids = design_context(
        delivery, design, technical
    )
    selected_asis = asis_context(
        delivery,
        asis,
        effective_start_ids,
        feature_ids,
        evidence_ids,
    )

    assert [item["designDecisionId"] for item in selected_design["decisions"]] == [
        "decision-profile-api"
    ]
    assert [item["evidenceId"] for item in selected_asis["evidence"]] == [
        "evidence-customer-api"
    ]


def test_review_mode_writes_hash_bound_packet_without_formal_publication(tmp_path: Path) -> None:
    candidate, review = prepare_review_candidate(tmp_path)

    result = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    report = payload(result)
    assert report["outcome"] == "REVIEW_REQUIRED"
    packet_path = tmp_path / ".ai-sow/work/generate-task/review-packet.json"
    risk_path = tmp_path / ".ai-sow/work/generate-task/risk-summary.md"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet["algorithm"] == "ai-sow-owner-review-packet-v1"
    assert packet["status"] == "READY_FOR_REVIEW"
    assert packet["review"] == {
        "path": ".ai-sow/work/generate-task/review.candidate.md",
        "sha256": sha256_bytes(review),
    }
    assert packet["candidateOutputs"] == [
        {
            "name": "estimate",
            "path": ".ai-sow/work/generate-task/estimate.candidate.json",
            "sha256": sha256_bytes(candidate),
            "targetPath": ".ai-sow/data/generate-task/estimate.json",
        }
    ]
    assert packet["context"]["manifest"]["path"] == (
        ".ai-sow/work/generate-task/context/manifest.json"
    )
    assert [entry["name"] for entry in packet["context"]["fragments"]] == [
        "delivery",
        "design",
        "asIs",
        "technicalRequirements",
        "templateCatalog",
    ]
    assert packet["context"]["reviewClaims"]["status"] == "READY"
    assert packet["context"]["reviewClaims"]["fragment"]["name"] == "claims"
    assert packet["riskSummary"]["sha256"] == sha256_bytes(risk_path.read_bytes())
    assert "Task Count: 3" in risk_path.read_text(encoding="utf-8")
    assert not (tmp_path / ".ai-sow/reviews/generate-task.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_review_mode_projects_open_delivery_risks_into_bound_summary(tmp_path: Path) -> None:
    delivery = copy.deepcopy(DELIVERY)
    delivery["assumptions"] = [
        {
            "assumptionId": "assumption-profile-api-availability",
            "handling": "按确认窗口执行联调",
            "name": "会员主数据服务联调期间可用",
            "responsibilityBoundary": "会员主数据团队提供测试端点",
            "status": "已明确",
            "trigger": "联调开始",
            "type": "假设",
        },
        {
            "assumptionId": "assumption-risk-payment-certification",
            "handling": "延期时调整退款联调顺序",
            "name": "支付网关退款认证可能延迟",
            "responsibilityBoundary": "资金管理部提交企业材料",
            "status": "待确认",
            "trigger": "SIT 第 2 周仍未通过",
            "type": "风险",
        },
    ]
    prepare_review_candidate(tmp_path, delivery=delivery)

    result = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    summary = (
        tmp_path / ".ai-sow/work/generate-task/risk-summary.md"
    ).read_text(encoding="utf-8")
    assert "Open Delivery Risks: 1" in summary
    assert (
        "| assumption-risk-payment-certification | 支付网关退款认证可能延迟 | "
        "SIT 第 2 周仍未通过 | 资金管理部提交企业材料 | 延期时调整退款联调顺序 |"
    ) in summary
    assert "assumption-profile-api-availability" not in summary


def test_publish_approved_requires_reviewer_and_user_bindings_without_formal_writes(
    tmp_path: Path,
) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 2
    assert {"REVIEWER_BINDING_MISSING", "APPROVAL_BINDING_MISSING"}.issubset(codes(result))
    assert not (tmp_path / ".ai-sow/reviews/generate-task.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_publish_approved_preserves_exact_candidate_review_and_receipt_contract(
    tmp_path: Path,
) -> None:
    candidate, review = prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 0, result.stdout
    assert (tmp_path / ".ai-sow/reviews/generate-task.md").read_bytes() == review
    assert managed_path(tmp_path, ".ai-sow/data/generate-task/estimate.json").read_bytes() == candidate
    receipt = payload(result)["receipt"]
    assert receipt["validatorContractVersion"] == "0.3"
    assert receipt["reviews"][0]["sha256"] == sha256_bytes(review)
    assert receipt["outputs"][0]["sha256"] == sha256_bytes(candidate)


def test_publish_approved_accepts_hash_bound_no_change_candidate(tmp_path: Path) -> None:
    candidate, _ = prepare_review_candidate(tmp_path)
    review_path = ".ai-sow/work/generate-task/review.candidate.md"
    reviewed = run_validator(tmp_path, "review", review_path=review_path)
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    published = run_validator(tmp_path, "publish-approved", review_path=review_path)
    assert published.returncode == 0, published.stdout

    previous_report = json.loads(
        (tmp_path / ".ai-sow/validation/generate-task.json").read_text(encoding="utf-8")
    )
    old_story = input_hash(previous_report, "deliveryValidation")
    publish_story(tmp_path, review=b"Story approved after wording update.\n")
    new_story = sha256_bytes(
        (tmp_path / ".ai-sow/validation/generate-story.json").read_bytes()
    )
    estimate = json.loads(candidate)
    template_hash = sha256_bytes(
        (tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes()
    )
    write_bytes(
        tmp_path,
        review_path,
        task_review(
            estimate,
            template_hash,
            rebind={"old": old_story, "new": new_story},
        ).encode(),
    )
    context = run_context(tmp_path)
    assert context.returncode == 0, context.stdout

    reviewed = run_validator(tmp_path, "review", review_path=review_path)
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    rebound = run_validator(tmp_path, "publish-approved", review_path=review_path)

    assert rebound.returncode == 0, rebound.stdout
    assert (tmp_path / ".ai-sow/data/generate-task/estimate.json").read_bytes() == candidate
    report = json.loads(
        (tmp_path / ".ai-sow/validation/generate-task.json").read_text(encoding="utf-8")
    )
    assert input_hash(report, "deliveryValidation") == new_story
    assert report["compilationReceipt"]["outputs"][0]["sha256"] == sha256_bytes(candidate)


def test_publish_approved_rejects_packet_drift_before_formal_writes(tmp_path: Path) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    mutate_candidate(tmp_path, lambda value: value["tasks"][0].update({"name": "漂移后的任务"}))

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 2
    assert "REVIEW_PACKET_CANDIDATE_STALE" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-task.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_publish_approved_rejects_unknown_packet_fields(tmp_path: Path) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    packet_path = tmp_path / ".ai-sow/work/generate-task/review-packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["unrecognized"] = True
    packet_path.write_bytes(canonical_json_bytes(packet))
    bind_review_packet(tmp_path)

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 2
    assert "REVIEW_PACKET_INVALID" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-task.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_publish_approved_rejects_context_fragment_drift(tmp_path: Path) -> None:
    prepare_review_candidate(tmp_path)
    reviewed = run_validator(
        tmp_path,
        "review",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )
    assert reviewed.returncode == 0, reviewed.stdout
    bind_review_packet(tmp_path)
    write_bytes(
        tmp_path,
        ".ai-sow/work/generate-task/context/delivery.json",
        canonical_json_bytes({"drifted": True}),
    )

    result = run_validator(
        tmp_path,
        "publish-approved",
        review_path=".ai-sow/work/generate-task/review.candidate.md",
    )

    assert result.returncode == 2
    assert "CONTEXT_FRAGMENT_STALE" in codes(result)
    assert not (tmp_path / ".ai-sow/reviews/generate-task.md").exists()
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert not (tmp_path / ".ai-sow/validation/generate-task.json").exists()


def test_publish_preserves_candidate_bytes_and_exact_inputs(tmp_path: Path) -> None:
    candidate = prepare(tmp_path)

    result = run_validator(tmp_path, "publish")

    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-task/estimate.json").read_bytes() == candidate
    receipt = payload(result)["receipt"]
    assert [entry["name"] for entry in receipt["outputs"]] == ["estimate"]  # type: ignore[index]
    assert [entry["name"] for entry in receipt["inputs"]] == [  # type: ignore[index]
        "project", "asIsValidation", "asIs", "designValidation", "design",
        "technicalRequirements", "deliveryValidation", "delivery", "template",
    ]


@pytest.mark.parametrize("owner", ["analyze-as-is", "generate-design", "generate-story"])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("missing", "UPSTREAM_HANDOFF_MISSING"),
        ("invalid", "UPSTREAM_HANDOFF_INVALID"),
        ("stale", "UPSTREAM_HANDOFF_STALE"),
        ("unsupported", "UPSTREAM_CONTRACT_UNSUPPORTED"),
    ],
)
def test_routes_three_owner_handoff_failures(tmp_path: Path, owner: str, failure: str, expected: str) -> None:
    prepare(tmp_path)
    validation = tmp_path / f".ai-sow/validation/{owner}.json"
    output = tmp_path / {
        "analyze-as-is": ".ai-sow/data/analyze-as-is/asis.json",
        "generate-design": ".ai-sow/data/generate-design/design.json",
        "generate-story": ".ai-sow/data/generate-story/delivery.json",
    }[owner]
    if failure == "missing":
        validation.unlink()
    elif failure == "stale":
        output.write_bytes(output.read_bytes() + b" ")
    else:
        report = json.loads(validation.read_text(encoding="utf-8"))
        if failure == "invalid":
            report["passed"] = False
        else:
            report["compilationReceipt"]["validatorContractVersion"] = "99"
        validation.write_bytes(json_bytes(report))
    write_bytes(tmp_path, ".ai-sow/work/generate-task/estimate.candidate.json", b"not-json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    assert codes(result) == {expected}
    assert payload(result)["diagnostics"][0]["upstreamOwner"] == owner  # type: ignore[index]


def test_does_not_replay_design_or_story_internal_business_rules(tmp_path: Path) -> None:
    prepare(tmp_path)
    design = copy.deepcopy(DESIGN)
    design["scopeDecisions"] = "not-an-array"
    delivery = copy.deepcopy(DELIVERY)
    delivery["assumptions"] = "not-an-array"
    publish_design(tmp_path, design, review=b"HLD Coverage: BLOCKED\nGo-live Assessment: BLOCKED\n")
    publish_story(tmp_path, delivery)

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert not {code for code in codes(result) if code.startswith("HLD_") or code.startswith("GO_LIVE_")}


@pytest.mark.parametrize(
    ("owner", "output_path"),
    [
        ("analyze-as-is", ".ai-sow/data/analyze-as-is/asis.json"),
        ("generate-story", ".ai-sow/data/generate-story/delivery.json"),
    ],
)
def test_attributes_unreadable_consumed_outputs_to_owner_and_path(
    tmp_path: Path,
    owner: str,
    output_path: str,
) -> None:
    prepare(tmp_path)
    if owner == "analyze-as-is":
        publish_asis(tmp_path, output_payload=b"not-json")
        publish_design(tmp_path)
        publish_story(tmp_path)
    else:
        publish_story(tmp_path, output_payload=b"not-json")

    result = run_validator(tmp_path)

    assert result.returncode == 2
    diagnostic = payload(result)["diagnostics"][0]  # type: ignore[index]
    assert diagnostic["code"] == "UPSTREAM_HANDOFF_INVALID"
    assert diagnostic["upstreamOwner"] == owner
    assert diagnostic["path"] == output_path


def test_rejects_story_without_task(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_candidate(tmp_path, lambda value: value["tasks"].pop())
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "TASK_COVERAGE_MISSING" in codes(result)


def test_rejects_missing_or_unknown_ac_coverage(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_candidate(tmp_path, lambda value: value["tasks"][0].update({"acceptanceCriterionIds": ["ac-unknown"]}))
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert {"AC_REF_UNKNOWN", "AC_COVERAGE_MISSING"} <= codes(result)


def test_allows_multiple_tasks_to_contribute_to_same_ac(tmp_path: Path) -> None:
    prepare(tmp_path)
    def add_contributing_task(value: dict[str, object]) -> None:
        task = copy.deepcopy(value["tasks"][0])  # type: ignore[index]
        task["taskId"] = "task-customer-profile-state-binding"
        task["name"] = "实现客户档案状态绑定"
        task["rationale"] = "客户档案状态绑定是独立的界面交互实例，并与页面共同满足同一业务验收条件。"
        value["tasks"].append(task)  # type: ignore[index]

    mutate_candidate(tmp_path, add_contributing_task)
    candidate_path = tmp_path / ".ai-sow/work/generate-task/estimate.candidate.json"
    estimate = json.loads(candidate_path.read_text(encoding="utf-8"))
    template_hash = sha256_bytes((tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes())
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-task.md",
        task_review(estimate, template_hash).encode("utf-8"),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"


def test_rejects_unconfigured_base_unit_work_mode_pair(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_candidate(
        tmp_path,
        lambda value: value["tasks"][0].update(
            {"workMode": "接入复用", "workModeEvidence": value["tasks"][1]["workModeEvidence"]}
        ),
    )
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "TASK_OPTION_NOT_CONFIGURED" in codes(result)


def test_rejects_unknown_effective_start_and_evidence_mismatch(tmp_path: Path) -> None:
    prepare(tmp_path)

    def change(value: dict[str, object]) -> None:
        task = value["tasks"][2]  # type: ignore[index]
        task["matchedEffectiveStartItemId"] = "effective-start-unknown"
        task["workModeEvidence"]["effectiveStartItemId"] = "effective-start-unknown"

    mutate_candidate(tmp_path, change)
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "EFFECTIVE_START_REF_UNKNOWN" in codes(result)


def test_rejects_noncanonical_reuse_commitment(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_candidate(tmp_path, lambda value: value["tasks"][1].update({"workModeRationale": "复用现有 API。"}))
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "WORK_MODE_REUSE_NOT_ESTIMABLE" in codes(result)


def test_rejects_reuse_work_types_out_of_contract_order(tmp_path: Path) -> None:
    prepare(tmp_path)

    def change(value: dict[str, object]) -> None:
        task = value["tasks"][1]  # type: ignore[index]
        evidence = task["workModeEvidence"]
        evidence["projectSideWorkTypes"] = ["AUTHENTICATE", "MAP", "ADAPT"]
        evidence["projectSideWorkCommitment"] = "本项目负责并交付：认证、映射、适配"
        task["workModeRationale"] = (
            "生效起点的 Customer API（客户接口）保持不变；本项目负责并交付：认证、映射、适配。"
        )

    mutate_candidate(tmp_path, change)
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "WORK_MODE_REUSE_NOT_ESTIMABLE" in codes(result)


def test_adjustment_accepts_as_is_regression_assets_for_quality_work(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)
    asis = copy.deepcopy(ASIS)
    asis["effectiveStartItems"][1]["summary"] = (  # type: ignore[index]
        "既有一期回归资产和恢复演练可供本期质量验证调整。"
    )
    publish_asis(tmp_path, asis)
    publish_design(tmp_path)
    publish_story(tmp_path)

    def change(value: dict[str, object]) -> None:
        task = value["tasks"][2]  # type: ignore[index]
        task["baseUnit"] = "BU-AUTOMATION-CASES"
        task["name"] = "调整现有客户档案托管架构方案回归资产"
        task["rationale"] = "约十条现有客户档案托管场景作为一个可重复执行的回归资产组。"

    mutate_candidate(tmp_path, change)
    estimate = json.loads(
        (tmp_path / ".ai-sow/work/generate-task/estimate.candidate.json").read_text(
            encoding="utf-8"
        )
    )
    template_hash = sha256_bytes(
        (tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes()
    )
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-task.md",
        task_review(estimate, template_hash).encode("utf-8"),
    )

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout


def test_adjustment_asset_diagnostic_recommends_new_work_mode(
    tmp_path: Path,
) -> None:
    prepare(tmp_path)

    def change(value: dict[str, object]) -> None:
        task = value["tasks"][2]  # type: ignore[index]
        task["baseUnit"] = "BU-DATA-MIGRATION"
        task["name"] = "调整现有客户档案托管架构方案的数据迁移"
        task["rationale"] = "一个源对象到目标对象的迁移实例。"

    mutate_candidate(tmp_path, change)
    estimate = json.loads(
        (tmp_path / ".ai-sow/work/generate-task/estimate.candidate.json").read_text(
            encoding="utf-8"
        )
    )
    template_hash = sha256_bytes(
        (tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes()
    )
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-task.md",
        task_review(estimate, template_hash).encode("utf-8"),
    )

    result = run_validator(tmp_path)

    diagnostic = next(
        entry
        for entry in payload(result)["diagnostics"]  # type: ignore[index]
        if entry["code"] == "WORK_MODE_ADJUSTMENT_ASSET_UNSPECIFIED"
    )
    assert "otherwise use 新建" in diagnostic["message"]


def test_rejects_catalog_copied_complexity_rationale(tmp_path: Path) -> None:
    prepare(tmp_path)
    catalog = read_contract(SKILL_ROOT / "fixtures/sow-template.xlsx")
    standard = catalog["baseUnits"]["BU-ARCHITECTURE-DESIGN"]["complexityStandards"]["L"]
    mutate_candidate(tmp_path, lambda value: value["tasks"][2].update({"complexityRationale": standard}))
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "COMPLEXITY_RATIONALE_GENERIC" in codes(result)


def test_rejects_integration_without_integration_task(tmp_path: Path) -> None:
    prepare(tmp_path)
    mutate_candidate(tmp_path, lambda value: value["tasks"][1].pop("integrationId"))
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert {"INTEGRATION_ID_REQUIRED", "INTEGRATION_COVERAGE_MISSING"} <= codes(result)


def test_rejects_duplicate_integration_task(tmp_path: Path) -> None:
    prepare(tmp_path)

    def change(value: dict[str, object]) -> None:
        duplicate = copy.deepcopy(value["tasks"][1])  # type: ignore[index]
        duplicate["taskId"] = "task-profile-api-integration-duplicate"
        duplicate["name"] = "重复接入内部客户档案 API"
        value["tasks"].append(duplicate)  # type: ignore[index]

    mutate_candidate(tmp_path, change)
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert "INTEGRATION_COVERAGE_DUPLICATE" in codes(result)


def test_rejects_review_scope_or_template_hash_drift(tmp_path: Path) -> None:
    prepare(tmp_path)
    review = tmp_path / ".ai-sow/reviews/generate-task.md"
    review.write_text(
        review.read_text(encoding="utf-8")
        .replace("Scope Review: PASSED", "Scope Review: BLOCKED")
        .replace("Template SHA-256: ", "Template SHA-256: 0000"),
        encoding="utf-8",
    )
    result = run_validator(tmp_path)
    assert result.returncode == 2
    assert {"REVIEW_SCOPE_NOT_PASSED", "REVIEW_TEMPLATE_HASH_MISMATCH"} <= codes(result)


def test_check_uses_work_only_review_path_override(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/run-0123456789ab/generate-task.review.md"
    override = tmp_path / review_path
    override.parent.mkdir(parents=True)
    override.write_bytes((tmp_path / ".ai-sow/reviews/generate-task.md").read_bytes())
    (tmp_path / ".ai-sow/reviews/generate-task.md").write_text(
        "default review must not be used\n",
        encoding="utf-8",
    )

    result = run_validator(tmp_path, review_path=review_path)

    assert result.returncode == 0, result.stdout
    assert payload(result)["outcome"] == "OK"


def test_review_override_diagnostics_name_actual_path(tmp_path: Path) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/run-0123456789ab/generate-task.review.md"
    override = tmp_path / review_path
    override.parent.mkdir(parents=True)
    override.write_text("invalid candidate review\n", encoding="utf-8")

    result = run_validator(tmp_path, review_path=review_path)

    assert result.returncode == 2
    assert payload(result)["diagnostics"]
    assert {
        diagnostic["path"]
        for diagnostic in payload(result)["diagnostics"]  # type: ignore[index]
    } == {review_path}


@pytest.mark.parametrize("mode", ["publish", "rebind"])
def test_review_path_override_is_rejected_by_legacy_write_modes(tmp_path: Path, mode: str) -> None:
    prepare(tmp_path)
    review_path = ".ai-sow/work/reconcile/run-0123456789ab/generate-task.review.md"
    validation = tmp_path / ".ai-sow/validation/generate-task.json"
    validation.write_bytes(b"baseline validation\n")

    result = run_validator(tmp_path, mode, review_path=review_path)

    assert result.returncode == 2
    diagnostic = payload(result)["diagnostics"][0]  # type: ignore[index]
    assert diagnostic == {
        "code": "REVIEW_PATH_MODE_INVALID",
        "message": "--review-path override is allowed only in check, review, or publish-approved mode",
        "path": review_path,
    }
    assert not (tmp_path / ".ai-sow/data/generate-task/estimate.json").exists()
    assert validation.read_bytes() == b"baseline validation\n"


@pytest.mark.parametrize("review_path", ["/tmp/review.md", "../review.md", r"work\\review.md"])
def test_check_rejects_non_project_relative_posix_review_path(
    tmp_path: Path,
    review_path: str,
) -> None:
    prepare(tmp_path)

    result = run_validator(tmp_path, review_path=review_path)

    assert result.returncode == 2
    diagnostic = payload(result)["diagnostics"][0]  # type: ignore[index]
    assert diagnostic["code"] == "REVIEW_PATH_INVALID"
    assert diagnostic["path"] == review_path


def input_hash(report: dict[str, object], name: str) -> str:
    entries = report["compilationReceipt"]["inputs"]  # type: ignore[index]
    matches = [entry for entry in entries if entry["name"] == name]
    assert len(matches) == 1
    return matches[0]["sha256"]


def test_rebind_changes_story_receipt_without_changing_estimate_bytes(tmp_path: Path) -> None:
    candidate = prepare(tmp_path)
    published = run_validator(tmp_path, "publish")
    assert published.returncode == 0, published.stdout
    old_report = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-task.json").read_text(
            encoding="utf-8"
        )
    )
    old_story = input_hash(old_report, "deliveryValidation")
    publish_story(tmp_path, review=b"Story approved after wording update.\n")
    new_story = sha256_bytes((tmp_path / ".ai-sow/validation/generate-story.json").read_bytes())
    estimate = fixture()
    template_hash = sha256_bytes((tmp_path / ".ai-sow/templates/sow-template.xlsx").read_bytes())
    write_bytes(
        tmp_path,
        ".ai-sow/reviews/generate-task.md",
        task_review(estimate, template_hash, rebind={"old": old_story, "new": new_story}).encode(),
    )
    result = run_validator(tmp_path, "rebind")
    assert result.returncode == 0, result.stdout
    assert managed_path(tmp_path, ".ai-sow/data/generate-task/estimate.json").read_bytes() == candidate
    rebound = json.loads(
        managed_path(tmp_path, ".ai-sow/validation/generate-task.json").read_text(
            encoding="utf-8"
        )
    )
    assert input_hash(rebound, "deliveryValidation") == new_story


def test_schema_forbids_calculation_outputs() -> None:
    schema = (SKILL_ROOT / "contracts/estimate.schema.json").read_text(encoding="utf-8")
    for removed in ("professionalDomain", "activity", "quantity", "baseEffort", "taskEffort", "sitEstimates"):
        assert f'"{removed}"' not in schema
    assert "<effectiveStartItemName>保持不变；<projectSideWorkCommitment>。" in schema


def test_skill_uses_review_candidate_publish_stop_and_local_template() -> None:
    contract = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for required in (
        "Reviewer Agent", "render_review.py", "--mode review", "--mode publish-approved", "--mode rebind",
        "estimate.candidate.json", "只推荐用户显式调用 `generate-sow`", "PM 补充项",
        "然后 STOP", "fixtures/sow-template.xlsx", "不得重新诊断 Story 或 Design",
        "review-packet.json", "approval.json", "不继承当前完整聊天",
        "SAME_INSTANCE", "DISTINCT_DELIVERY_OBJECTS", "STORY_OWNER_RETURN_REQUIRED",
        "TASK_LOCAL_CORRECTION", "最多两次成功 patch",
        "category: DECISION", "category: UPSTREAM", "correctionOwner: generate-story",
        "correctionOwner: generate-design", "requiresUserDecision: true",
    ):
        assert required in contract
    assert "Validator Agent" not in contract
    assert "Worker Agent" not in contract
    assert contract.count("read_template.py") == 1


def test_review_template_documents_task_maps_and_rebind_declarations() -> None:
    template = (SKILL_ROOT / "references/review-template.md").read_text(encoding="utf-8")
    for required in (
        "Story Map: story-example=task-example",
        "AC Map: ac-example=task-example",
        "Stable IDs: task-example",
        "Integration Map: integration-example=task-example",
        "Scope Review: PASSED",
        "Potential Instance Collisions:",
        "SAME_INSTANCE / DISTINCT_DELIVERY_OBJECTS / REUSE_CONSUMER",
        "Template SHA-256: <64-lowercase-hex>",
        "Impact: NO_CHANGE",
        "Previous Receipt SHA-256: generate-story=<old-hash>",
        "Current Receipt SHA-256: generate-story=<new-hash>",
    ):
        assert required in template


def test_validator_has_no_cross_skill_or_review_gate_dependency() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "review_gates" not in text
    assert "skills/generate-" not in text
