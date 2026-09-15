#!/usr/bin/env python3
"""Read-only I4.3 ledger checks; file presence never proves scenario semantics.

Ledger 1.0 has exactly schema_version, scenarios and mechanisms. Each scenario
has id, owner, earliest_increment (the entire D09 cell), state, evidence_refs
and limitation. covered_by_mechanism also requires mechanism_refs, a nonempty
list of {id, applicability}. Mechanisms have id, state, evidence_refs and
limitation; they may be verified, unsupported or conditional, never a chain.

References are canonical plugin-relative POSIX file paths, without fragments
or URLs. Verified mechanisms and verified/covered scenarios need evidence.
Unsupported/conditional records need a limitation beyond a bare placeholder.
Specificity, applicability and the truth of evidence still require human review.
No ledger, evidence, scenario state or design source is written by this tool.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re


D09 = "docs/design/detailed/D09-validation-and-implementation.md"
CATALOG = "docs/design/08-scenario-catalog.md"
EXPECTED_SCENARIOS = 163
STATES = ("verified", "covered_by_mechanism", "unsupported", "conditional")
MECHANISM_STATES = ("verified", "unsupported", "conditional")
IDENTIFIER = re.compile(r"([A-Z]+)([0-9]{2})")
PLACEHOLDERS = {
    "tbd", "todo", "n/a", "na", "none", "null", "unknown", "-", "...",
    "待补", "待定", "未验证", "待验证", "未实现", "未支持", "未知", "无",
}


class CoverageError(ValueError):
    """The ledger or its authoritative design source cannot be checked."""


def _plugin_file(plugin_root: Path, reference: object, code: str) -> Path:
    if (not isinstance(reference, str) or not reference or reference != reference.strip()
            or any(character in reference for character in ("\\", ":", "#", "?"))
            or any(ord(character) < 32 for character in reference)):
        raise CoverageError(f"{code}: 引用必须是插件内 POSIX 文件路径：{reference!r}")
    path = PurePosixPath(reference)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != reference:
        raise CoverageError(f"{code}: 路径必须相对插件且不含跳转：{reference!r}")
    try:
        root = plugin_root.resolve()
        resolved = (root / reference).resolve()
        if not resolved.is_relative_to(root):
            raise CoverageError(f"{code}: 引用跳出插件：{reference!r}")
        if not resolved.is_file():
            raise CoverageError(f"{code}: 引用文件不存在：{reference!r}")
    except (OSError, RuntimeError) as exc:
        raise CoverageError(f"{code}: 无法解析引用 {reference!r}：{exc}") from exc
    return resolved


def _table_rows(text: str, header: tuple[str, ...]) -> tuple[int, list[list[str]]]:
    """Read the specified Markdown tables, rejecting truncated/malformed rows."""
    rows: list[list[str]] = []
    tables = 0
    width = 0
    separator = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            if separator:
                raise CoverageError("SOURCE_TABLE: 表头后缺少 Markdown 分隔行")
            width = 0
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if tuple(cells[:len(header)]) == header:
            tables += 1
            width = len(cells)
            separator = True
            continue
        if not width:
            continue
        if len(cells) != width:
            raise CoverageError("SOURCE_TABLE: 权威表格列数不一致")
        if separator:
            if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                raise CoverageError("SOURCE_TABLE: 权威表格分隔行无效")
            separator = False
        else:
            rows.append(cells)
    if not tables or separator:
        raise CoverageError(f"SOURCE_TABLE: 权威表格缺失或不完整：{' / '.join(header)}")
    return tables, rows


def _expand_ids(cell: str) -> list[str]:
    identifiers: list[str] = []
    for term in cell.split("、"):
        endpoints = term.strip().split("—")
        matches = [IDENTIFIER.fullmatch(endpoint) for endpoint in endpoints]
        if len(matches) not in (1, 2) or not all(matches):
            raise CoverageError(f"SOURCE_RANGE: 场景 ID 或闭区间无效：{term!r}")
        first, last = matches[0], matches[-1]
        start, end = int(first[2]), int(last[2])
        if first[1] != last[1] or start < 1 or end < start:
            raise CoverageError(f"SOURCE_RANGE: 场景区间跨前缀或倒序：{term!r}")
        identifiers.extend(f"{first[1]}{number:02}" for number in range(start, end + 1))
    return identifiers


def parse_scenario_index(d09_text: str, catalog_text: str) -> dict[str, dict[str, str]]:
    """Cross-check 08 IDs against D09 owners and full earliest-increment cells."""
    _, catalog_rows = _table_rows(catalog_text, ("ID",))
    catalog_ids: set[str] = set()
    for row in catalog_rows:
        identifier = row[0]
        if not IDENTIFIER.fullmatch(identifier):
            raise CoverageError(f"SOURCE_RANGE: 08 目录的场景 ID 无效：{identifier!r}")
        if identifier in catalog_ids:
            raise CoverageError(f"SOURCE_DUPLICATE_ID: 08 目录重复：{identifier}")
        catalog_ids.add(identifier)
    if len(catalog_ids) != EXPECTED_SCENARIOS:
        raise CoverageError(f"SOURCE_COUNT: 08 目录应有 {EXPECTED_SCENARIOS} 个唯一场景，实际 {len(catalog_ids)}")

    tables, assignments = _table_rows(d09_text, ("场景", "主责", "最早增量"))
    if tables != 1:
        raise CoverageError("SOURCE_TABLE: D09 必须只有一份主责分配表")
    result: dict[str, dict[str, str]] = {}
    for row in assignments:
        ids, owner, stage = row[:3]
        if not re.fullmatch(r"D[0-9]{2}[A-Z]?", owner) or not stage:
            raise CoverageError(f"SOURCE_TABLE: D09 缺少有效主责或最早增量：{ids}")
        for identifier in _expand_ids(ids):
            if identifier in result:
                raise CoverageError(f"SOURCE_DUPLICATE_ID: D09 重复分配：{identifier}")
            result[identifier] = {"owner": owner, "earliest_increment": stage}
    if set(result) != catalog_ids:
        missing = ", ".join(sorted(catalog_ids - result.keys())) or "无"
        extra = ", ".join(sorted(result.keys() - catalog_ids)) or "无"
        raise CoverageError(f"SOURCE_ID_MISMATCH: D09 对照 08 目录缺少 [{missing}]，多出 [{extra}]")
    return result


def load_scenario_index(plugin_root: Path) -> dict[str, dict[str, str]]:
    """Load only the selected plugin's two authoritative design documents."""
    try:
        d09 = _plugin_file(plugin_root, D09, "SOURCE_PATH").read_text(encoding="utf-8")
        catalog = _plugin_file(plugin_root, CATALOG, "SOURCE_PATH").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CoverageError(f"SOURCE_READ: 权威文件无法读取：{exc}") from exc
    return parse_scenario_index(d09, catalog)


def _shape(value: object, required: set[str], optional: set[str], label: str,
           errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"SHAPE: {label} 必须是 JSON object")
        return False
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        errors.append(f"SHAPE: {label} 缺少字段 {sorted(missing)}；未知字段 {sorted(map(str, extra))}")
        return False
    return True


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _specific_text(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().lower() not in PLACEHOLDERS
            and any(character.isalnum() for character in value))


def _evidence_and_limitation(row: dict, plugin_root: Path, label: str, errors: list[str]) -> None:
    state = row.get("state")
    refs = row.get("evidence_refs")
    if not isinstance(refs, list) or (state in ("verified", "covered_by_mechanism") and not refs):
        errors.append(f"EVIDENCE: {label} 必须列出 evidence_refs；verified/covered 状态至少一项")
    else:
        for reference in refs:
            try:
                _plugin_file(plugin_root, reference, "EVIDENCE")
            except CoverageError as exc:
                errors.append(f"EVIDENCE: {label}：{exc}")
    limitation = row.get("limitation")
    if (not isinstance(limitation, str)
            or (state in ("unsupported", "conditional") and not _specific_text(limitation))):
        errors.append(f"LIMITATION: {label} 必须写明具体限制，不能只留空或填占位词")


def validate_ledger(ledger: object, plugin_root: Path) -> list[str]:
    """Return structural/reference diagnostics without changing any state or file."""
    errors: list[str] = []
    if not _shape(ledger, {"schema_version", "scenarios", "mechanisms"}, set(), "ledger", errors):
        return errors
    if ledger["schema_version"] != "1.0":
        errors.append("SCHEMA_VERSION: ledger schema_version 必须是 1.0")
    if not isinstance(ledger["scenarios"], list) or not isinstance(ledger["mechanisms"], list):
        return [*errors, "SHAPE: scenarios 和 mechanisms 必须是数组"]
    try:
        index = load_scenario_index(plugin_root)
    except CoverageError as exc:
        return [*errors, str(exc)]

    core = {"id", "state", "evidence_refs", "limitation"}
    mechanisms: dict[str, dict] = {}
    for number, row in enumerate(ledger["mechanisms"]):
        label = f"mechanisms[{number}]"
        if not _shape(row, core, set(), label, errors):
            continue
        identifier = row["id"]
        if not _identifier(identifier):
            errors.append(f"ID: {label} 的 id 必须是非空字符串")
            continue
        if identifier in mechanisms:
            errors.append(f"DUPLICATE_MECHANISM: 机制重复声明：{identifier}")
        else:
            mechanisms[identifier] = row
        if row["state"] not in MECHANISM_STATES:
            errors.append(f"STATE: {label} 机制只能是 verified/unsupported/conditional，不支持覆盖链")
        _evidence_and_limitation(row, plugin_root, label, errors)

    seen: set[str] = set()
    for number, row in enumerate(ledger["scenarios"]):
        label = f"scenarios[{number}]"
        if not _shape(row, core | {"owner", "earliest_increment"}, {"mechanism_refs"}, label, errors):
            continue
        identifier = row["id"]
        if not _identifier(identifier):
            errors.append(f"ID: {label} 的 id 必须是非空字符串")
            continue
        label = identifier
        if identifier in seen:
            errors.append(f"DUPLICATE_SCENARIO: 场景重复：{identifier}")
        seen.add(identifier)
        if identifier not in index:
            errors.append(f"UNKNOWN_SCENARIO: 08/D09 未声明该场景：{identifier}")
        else:
            if row["owner"] != index[identifier]["owner"]:
                errors.append(f"OWNER_MISMATCH: {identifier} owner 应为 {index[identifier]['owner']}")
            if row["earliest_increment"] != index[identifier]["earliest_increment"]:
                errors.append(f"STAGE_MISMATCH: {identifier} earliest_increment 应为 {index[identifier]['earliest_increment']}")
        state = row["state"]
        if state not in STATES:
            errors.append(f"STATE: {identifier} 的 state 无效")
        _evidence_and_limitation(row, plugin_root, label, errors)
        if state != "covered_by_mechanism":
            if "mechanism_refs" in row:
                errors.append(f"MECHANISM_REFS: {identifier} 只有 covered_by_mechanism 可声明 mechanism_refs")
            continue
        refs = row.get("mechanism_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"MECHANISM_REFS: {identifier} 必须引用至少一个直接 verified 的机制")
            continue
        for reference in refs:
            if not _shape(reference, {"id", "applicability"}, set(), f"{identifier}.mechanism_refs", errors):
                continue
            mechanism_id = reference["id"]
            if not _identifier(mechanism_id) or mechanism_id not in mechanisms:
                errors.append(f"UNKNOWN_MECHANISM: {identifier} 引用了未声明机制 {mechanism_id!r}")
            elif mechanisms[mechanism_id]["state"] != "verified":
                errors.append(f"MECHANISM_NOT_VERIFIED: {identifier} 引用的机制 {mechanism_id} 未声明 verified")
            if not _specific_text(reference["applicability"]):
                errors.append(f"APPLICABILITY: {identifier} 必须解释该机制如何适用于本场景")
    if index.keys() - seen:
        errors.append(f"MISSING_SCENARIO: 缺少场景：{', '.join(sorted(index.keys() - seen))}")
    return errors


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CoverageError(f"LEDGER_JSON: JSON 属性重复：{key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise CoverageError(f"LEDGER_JSON: 不接受非标准 JSON 数字：{value}")


def main(argv: list[str] | None = None) -> int:
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    parser = argparse.ArgumentParser(description="只读核对场景 ledger 结构及包内引用，不验证业务语义。")
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ledger", required=True, help="相对 plugin-root 的 POSIX JSON 文件路径")
    args = parser.parse_args(argv)
    try:
        path = _plugin_file(args.plugin_root, args.ledger, "LEDGER_PATH")
        ledger = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object,
                            parse_constant=_reject_json_constant)
        errors = validate_ledger(ledger, args.plugin_root)
    except CoverageError as exc:
        errors = [str(exc)]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors = [f"LEDGER_JSON: 无法读取有效 JSON ledger：{exc}"]
    report = {"ok": not errors, "semantic_verification": "not_performed", "errors": errors}
    if not errors:
        report["scenario_count"] = len(ledger["scenarios"])
        report["state_counts"] = {state: sum(row["state"] == state for row in ledger["scenarios"]) for state in STATES}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
