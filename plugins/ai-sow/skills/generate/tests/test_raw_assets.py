from __future__ import annotations

import hashlib
import re
from pathlib import Path


SKILL_ROOT = Path(__file__).parents[1]
ASSETS = SKILL_ROOT / "assets"
PRD_TEMPLATE = ASSETS / "prd-template.md"
HLD_TEMPLATE = ASSETS / "hld-template.md"
QUESTIONNAIRE = ASSETS / "greenfield-questionnaire.md"
SOW_TEMPLATE = ASSETS / "sow-template.xlsx"
REQUIRED_PRD_SECTIONS = {
    "项目背景与问题",
    "目标与成功指标",
    "In Scope",
    "Out of Scope",
    "用户与角色",
    "核心业务场景",
    "Feature、业务结果、业务规则与验收意图",
    "优先级与阶段",
    "业务约束、依赖与假设",
    "业务数据、合规与外部参与方",
}
REQUIRED_HLD_SECTIONS = {
    "系统上下文与责任",
    "目标架构",
    "关键业务流",
    "跨系统 Integration",
    "数据、迁移、保留与安全分类",
    "NFR",
    "环境、部署与切换",
    "关键技术决策",
    "待设计事项",
}


def markdown_headings(path: Path) -> set[str]:
    return {
        match.group(1).strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := re.match(r"^#{2,6}\s+(.+)$", line))
    }


def test_prd_and_hld_assets_express_every_required_semantic_section() -> None:
    assert REQUIRED_PRD_SECTIONS <= markdown_headings(PRD_TEMPLATE)
    assert REQUIRED_HLD_SECTIONS <= markdown_headings(HLD_TEMPLATE)


def test_templates_do_not_request_internal_compilation_artifacts() -> None:
    prd = PRD_TEMPLATE.read_text(encoding="utf-8")
    hld = HLD_TEMPLATE.read_text(encoding="utf-8")
    for forbidden in ("Coverage Matrix", "Story 分解", "Task 分解"):
        assert forbidden not in prd
    for forbidden in ("Coverage Matrix", "字段级接口", "类设计"):
        assert forbidden not in hld


def test_greenfield_questionnaire_is_minimal() -> None:
    text = QUESTIONNAIRE.read_text(encoding="utf-8")
    assert {"责任边界", "环境准备", "第三方依赖", "数据迁移责任"} <= set(
        re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
    )
    assert text.count("？") == 4


def test_bundled_sow_template_keeps_authoritative_bytes() -> None:
    assert hashlib.sha256(SOW_TEMPLATE.read_bytes()).hexdigest() == (
        "6c90f4782acf7b1beb372a7b5f8aa78079f677160c39349bf561883b5592bfa0"
    )
