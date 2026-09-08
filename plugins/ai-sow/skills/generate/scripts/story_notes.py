from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from models import TaskStandardCatalog


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def assumption_note_text(item: Mapping[str, object]) -> str:
    parts = (
        f"{item['type']}（{item['status']}）：{item['name']}",
        f"处置：{item['handling']}",
        f"估算边界：{item['estimateBoundary']}",
        f"变化触发：{item['changeTrigger']}",
    )
    return "；".join(str(part).rstrip("。；") for part in parts)


def _common_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s。；，、,:：;]+", "", normalized)


def story_note_projection(
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, object]]:
    """Project only object-specific assumptions once and expose the decision to review."""
    first_story_by_feature: dict[str, str] = {}
    for story in _mappings(delivery.get("stories")):
        feature_id = story.get("featureId")
        story_id = story.get("storyId")
        if isinstance(feature_id, str) and isinstance(story_id, str):
            first_story_by_feature.setdefault(feature_id, story_id)

    candidates: list[tuple[str, str, str]] = []
    suppressed: set[str] = set()
    for item in _mappings(scope.get("assumptions")):
        assumption_id = item.get("assumptionId")
        if not isinstance(assumption_id, str):
            continue
        feature_ids = list(dict.fromkeys(_ids(item.get("featureIds"))))
        if len(feature_ids) != 1 or feature_ids[0] not in first_story_by_feature:
            suppressed.add(assumption_id)
            continue
        candidates.append(
            (assumption_id, feature_ids[0], assumption_note_text(item))
        )

    features_by_text: dict[str, set[str]] = {}
    for _assumption_id, feature_id, text in candidates:
        features_by_text.setdefault(_common_key(text), set()).add(feature_id)

    kept_by_feature: dict[str, list[tuple[str, str]]] = {}
    for assumption_id, feature_id, text in candidates:
        if len(features_by_text[_common_key(text)]) > 1:
            suppressed.add(assumption_id)
            continue
        kept_by_feature.setdefault(feature_id, []).append((assumption_id, text))

    assignments: dict[str, str] = {}
    projected: list[dict[str, object]] = []
    for feature_id, story_id in first_story_by_feature.items():
        items = kept_by_feature.get(feature_id, [])
        if not items:
            continue
        assignments[story_id] = "\n".join(text for _assumption_id, text in items)
        projected.append(
            {
                "assumptionIds": [assumption_id for assumption_id, _text in items],
                "featureId": feature_id,
                "storyId": story_id,
            }
        )

    return assignments, {
        "projected": projected,
        "suppressedProjectLevelAssumptionIds": sorted(suppressed),
    }


def model_story_note_projection(
    model: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, object]]:
    """Project model annotations once without inventing scope decisions."""
    stories = _mappings(model.get("stories"))
    first_story_by_feature: dict[str, str] = {}
    for story in sorted(stories, key=lambda item: str(item.get("storyId", ""))):
        feature_id = story.get("featureId")
        story_id = story.get("storyId")
        if isinstance(feature_id, str) and isinstance(story_id, str):
            first_story_by_feature.setdefault(feature_id, story_id)
    known_story_ids = {
        str(story["storyId"])
        for story in stories
        if isinstance(story.get("storyId"), str)
    }
    by_story: dict[str, list[str]] = {}
    projected: list[dict[str, object]] = []
    suppressed: list[str] = []
    for annotation in sorted((
        _mappings(model.get("scopeAnnotations"))
        + _mappings(model.get("deliveryAnnotations"))
        + _mappings(model.get("estimationAnnotations"))
    ), key=lambda item: str(item.get("annotationId", ""))):
        annotation_id = annotation.get("annotationId")
        text = annotation.get("text")
        subject_ids = _ids(annotation.get("subjectIds"))
        if not isinstance(annotation_id, str) or not isinstance(text, str):
            continue
        target_story_ids = sorted(
            {
                subject_id
                for subject_id in subject_ids
                if subject_id in known_story_ids
            }
            | {
                first_story_by_feature[subject_id]
                for subject_id in subject_ids
                if subject_id in first_story_by_feature
            }
        )
        if not target_story_ids:
            suppressed.append(annotation_id)
            continue
        target_story_id = target_story_ids[0]
        by_story.setdefault(target_story_id, []).append(text)
        projected.append(
            {
                "annotationId": annotation_id,
                "storyId": target_story_id,
            }
        )
    return (
        {
            story_id: "\n".join(values)
            for story_id, values in sorted(by_story.items())
        },
        {
            "projected": projected,
            "suppressedProjectLevelAnnotationIds": sorted(suppressed),
        },
    )


def _lines(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values] or ["- 无"]


def render_model_notes(
    model: Mapping[str, object],
    review_decision: Mapping[str, object],
    task_catalog: TaskStandardCatalog,
) -> str:
    """Render concentrated, auditable defaults and exclusions for approval."""
    policy_instances = _mappings(model.get("policyInstances"))
    default_policies = [
        f"{item['policyInstanceId']} / {item['policyId']}"
        for item in policy_instances
        if item.get("inclusionPolicy") == "DEFAULT_INCLUDED"
    ]
    decisions = _mappings(model.get("decisions"))
    excluded = [
        f"{item['decisionId']} / {', '.join(_ids(item.get('subjectIds')))}"
        for item in decisions
        if item.get("kind") == "EXCLUDED_BY_USER"
    ]
    tasks = _mappings(model.get("tasks"))
    defaults = [
        f"默认新建：{item['taskId']}"
        for item in tasks
        if item.get("workMode") == "新建"
    ] + [
        f"M 档：{item['taskId']}"
        for item in tasks
        if item.get("complexity") == "M"
    ]
    boundaries = [
        f"{item['taskId']}：{item['actualMeasurementScope']}"
        for item in tasks
        if isinstance(item.get("actualMeasurementScope"), str)
    ]
    annotations = [
        f"{item['category']} / {item['annotationId']}：{item['text']}"
        for collection in (
            "scopeAnnotations",
            "deliveryAnnotations",
            "estimationAnnotations",
        )
        for item in _mappings(model.get(collection))
    ]
    project = model.get("project")
    project_id = project.get("projectId") if isinstance(project, Mapping) else None
    sections = [
        (
            "生成与评审",
            [
                f"项目：{project_id}",
                "renderer：generation-renderer-v13",
                f"终审：{review_decision.get('decision')}",
                f"Task Standard：{task_catalog.semantic_sha256}",
            ],
        ),
        ("默认纳入的自动化与上线工程", default_policies),
        ("用户排除与输入决定", excluded),
        ("默认工作方式与复杂度", defaults),
        ("实际计量与责任边界", boundaries),
        ("假设、排除、风险与变化触发", annotations),
    ]
    lines = ["# SOW 生成说明", ""]
    for heading, values in sections:
        lines.extend([f"## {heading}", "", *_lines(values), ""])
    return "\n".join(lines).rstrip() + "\n"
