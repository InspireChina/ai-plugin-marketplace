from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.diagnostics import diagnostic


LOCAL_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/(?:Users|home|private|tmp|var/folders)/)"
)
ABSOLUTE_CLAIM_PATTERN = re.compile(
    r"(?:唯一(?:路径|实现|实现类|配置|方式|来源)|所有|任何|不存在|"
    r"逐字(?:同形|一致)?|同形|完全一致|一律|均(?:为|由|未|不|已)|仅(?:有|由|使用|包含))"
)
COUNT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[一二两三四五六七八九十]|\d+)\s*"
    r"(?:个|条|份|处|项|套|类|种)(?![A-Za-z0-9])"
)
DEFAULT_LIMITED_PREFIXES = (
    "本次调查覆盖的",
    "本次已登记的",
    "在本次调查覆盖的",
    "在已登记的",
    "根据已登记的",
)


def text_fields(
    value: object,
    *,
    fields: set[str] | None = None,
    path: str = "",
) -> list[tuple[str, str]]:
    """Project selected string leaves to JSON-pointer-like paths."""

    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            if isinstance(child, str) and (fields is None or key in fields):
                result.append((child_path, child))
            elif isinstance(child, (dict, list)):
                result.extend(text_fields(child, fields=fields, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}/{index}"
            if isinstance(child, str) and fields is None:
                result.append((child_path, child))
            elif isinstance(child, (dict, list)):
                result.extend(text_fields(child, fields=fields, path=child_path))
    return result


def _safe_matches(project_root: Path, pattern: str) -> list[Path]:
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("glob must be project-relative and remain inside the project")
    resolved_root = project_root.resolve()
    matches: list[Path] = []
    for match in project_root.glob(pattern):
        resolved = match.resolve()
        if not resolved.is_relative_to(resolved_root):
            raise ValueError("glob resolves outside the project")
        if match.is_file():
            matches.append(match)
    return sorted(matches)


def evaluate_count_anchor(project_root: Path, anchor: Mapping[str, Any]) -> int:
    matches = _safe_matches(project_root, str(anchor.get("glob", "")))
    expr = str(anchor.get("expr", "files"))
    if expr == "files":
        return len(matches)
    if expr == "lines":
        return sum(
            len(path.read_text(encoding="utf-8").splitlines()) for path in matches
        )
    if expr.startswith("json:"):
        if len(matches) != 1:
            raise ValueError("JSON count anchor must resolve exactly one file")
        value: object = json.loads(matches[0].read_text(encoding="utf-8"))
        for raw in expr.removeprefix("json:").strip("/").split("/"):
            part = raw.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]  # type: ignore[index]
        if isinstance(value, bool):
            raise ValueError("JSON count anchor cannot resolve a boolean")
        if isinstance(value, int):
            return value
        if isinstance(value, (list, dict)):
            return len(value)
        raise ValueError("JSON count anchor must resolve an integer, array, or object")
    if expr.startswith("regex:"):
        pattern = re.compile(expr.removeprefix("regex:"), re.MULTILINE)
        return sum(
            len(pattern.findall(path.read_text(encoding="utf-8"))) for path in matches
        )
    raise ValueError(f"unsupported count anchor expression: {expr}")


def validate_text_gates(
    project_root: Path,
    fields: Iterable[tuple[str, str]],
    *,
    count_anchors: Sequence[Mapping[str, Any]] = (),
    limited_prefixes: Sequence[str] = DEFAULT_LIMITED_PREFIXES,
    absolute_claim_paths: set[str] | None = None,
) -> list[dict[str, object]]:
    """Validate local-path privacy and evidence-bound absolute/count claims."""

    diagnostics: list[dict[str, object]] = []
    anchors_by_path: dict[str, list[Mapping[str, Any]]] = {}
    for anchor in count_anchors:
        path = anchor.get("path")
        if isinstance(path, str):
            anchors_by_path.setdefault(path, []).append(anchor)
        try:
            actual = evaluate_count_anchor(project_root, anchor)
            expected = anchor.get("expected")
            if not isinstance(expected, int) or actual != expected:
                diagnostics.append(
                    diagnostic(
                        "COUNT_ANCHOR_MISMATCH",
                        f"count anchor expected {expected!r} but resolved {actual}",
                        str(path or ""),
                    )
                )
        except (
            OSError,
            UnicodeError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            json.JSONDecodeError,
            re.error,
        ) as exc:
            diagnostics.append(
                diagnostic(
                    "COUNT_ANCHOR_MISMATCH",
                    f"count anchor could not be evaluated: {exc}",
                    str(path or ""),
                )
            )

    for path, value in fields:
        if LOCAL_PATH_PATTERN.search(value):
            diagnostics.append(
                diagnostic(
                    "LOCAL_PATH_LEAKED",
                    "free text contains a machine-local absolute path",
                    path,
                )
            )
        if anchors_by_path.get(path):
            continue
        if absolute_claim_paths is not None and path not in absolute_claim_paths:
            continue
        for sentence in re.split(r"(?<=[。；])|[\r\n]+", value):
            sentence = sentence.strip()
            if not sentence or sentence.startswith(tuple(limited_prefixes)):
                continue
            if ABSOLUTE_CLAIM_PATTERN.search(sentence) or COUNT_PATTERN.search(sentence):
                diagnostics.append(
                    diagnostic(
                        "ABSOLUTE_CLAIM_UNANCHORED",
                        "absolute or quantitative claim requires a count anchor or limited wording",
                        path,
                    )
                )
                break
    return diagnostics
