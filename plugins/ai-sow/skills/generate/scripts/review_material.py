from __future__ import annotations

from collections.abc import Mapping


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _names(value: object, field: str = "name") -> list[str]:
    return [
        str(item[field]).strip()
        for item in _mappings(value)
        if isinstance(item.get(field), str) and str(item[field]).strip()
    ]


def _section(title: str, values: list[str], empty: str) -> list[str]:
    lines = [f"## {title}"]
    lines.extend(f"- {value}" for value in values)
    if not values:
        lines.append(f"- {empty}")
    return lines


def render_review_material(
    manifest: Mapping[str, object],
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
    final_review: Mapping[str, object] | None = None,
) -> str:
    project = manifest.get("project")
    project_name = (
        str(project.get("name")).strip()
        if isinstance(project, Mapping) and isinstance(project.get("name"), str)
        else "当前项目"
    )
    epics = _mappings(scope.get("epics"))
    features = _mappings(scope.get("features"))
    stories = _mappings(delivery.get("stories"))
    criteria = _mappings(delivery.get("acceptanceCriteria"))
    tasks = _mappings(delivery.get("tasks"))
    included = [
        str(feature["name"]).strip()
        for feature in features
        if isinstance(feature.get("name"), str)
        and (
            not isinstance(feature.get("scopeDecision"), Mapping)
            or feature["scopeDecision"].get("decision") == "IN_SCOPE"
        )
    ]
    excluded = [
        str(feature["name"]).strip()
        for feature in features
        if isinstance(feature.get("name"), str)
        and isinstance(feature.get("scopeDecision"), Mapping)
        and feature["scopeDecision"].get("decision") != "IN_SCOPE"
    ]
    assumptions = _names(scope.get("assumptions"))
    risks = [
        f"{item['name']}：{item['changeTrigger']}"
        for item in _mappings(scope.get("assumptions"))
        if isinstance(item.get("name"), str)
        and isinstance(item.get("changeTrigger"), str)
        and str(item["changeTrigger"]).strip()
    ]
    conclusion = "范围、交付拆分和估算边界已整理，等待独立终审。"
    if isinstance(final_review, Mapping):
        decision = final_review.get("decision")
        if decision == "PASS":
            conclusion = "终审已通过，可进入交付包渲染。"
        elif decision == "PASS_WITH_NOTES":
            conclusion = "终审通过，并已记录需要持续关注的固定边界。"
        elif decision == "BLOCKED":
            conclusion = "终审发现仍需补充的范围、验收或估算事实。"

    lines = [
        f"# {project_name} 终审材料",
        "",
        (
            f"- 本次材料包含 {len(epics)} 个 Epic、{len(features)} 个 Feature、"
            f"{len(stories)} 个 Story、{len(criteria)} 条验收条件和 {len(tasks)} 个 Task。"
        ),
        "",
        "## 结论摘要",
        f"- {conclusion}",
        "",
    ]
    lines.extend(_section("包含范围", included, "本次没有明确的包含范围。"))
    lines.append("")
    lines.extend(_section("不包含范围", excluded, "本次没有明确的不包含范围。"))
    lines.append("")
    lines.extend(_section("重要假设", assumptions, "本次没有需要单列的假设。"))
    lines.append("")
    lines.extend(_section("风险", risks, "本次没有需要单列的风险。"))
    lines.extend(
        (
            "",
            "## 下一步",
            "- 请审阅范围、边界、假设和风险；如仍有会改变范围、验收或估算的事实，请逐项补充。",
            "- 确认无阻断问题后，提交终审结论以继续生成交付包。",
            "",
        )
    )
    return "\n".join(lines)
