from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping


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
