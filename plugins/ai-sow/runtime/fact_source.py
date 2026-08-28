from __future__ import annotations

import re
from collections.abc import Iterable

from runtime.diagnostics import diagnostic


QUANTITATIVE_PATTERN = re.compile(
    r"(?:\d[\d,]*|[一二两三四五六七八九十]+)\s*"
    r"(?:个|条|份|处|项|套|类|种|文件|节点|边)"
)


def _sentences(value: str) -> list[str]:
    return [
        re.sub(r"\s+", "", sentence).strip("。；")
        for sentence in re.split(r"[。；\r\n]+", value)
        if sentence.strip()
    ]


def validate_unique_fact_sources(
    fields: Iterable[tuple[str, str]],
) -> list[dict[str, object]]:
    """Reject repeated quantitative facts and accidental repeated sentences."""

    diagnostics: list[dict[str, object]] = []
    owners: dict[str, list[str]] = {}
    for path, value in fields:
        seen_here: set[str] = set()
        for sentence in _sentences(value):
            if sentence in seen_here:
                diagnostics.append(
                    diagnostic(
                        "DUPLICATE_FACT_STATEMENT",
                        "the same fact sentence is repeated in one field",
                        path,
                    )
                )
            seen_here.add(sentence)
            if QUANTITATIVE_PATTERN.search(sentence):
                owners.setdefault(sentence, []).append(path)
    for sentence, paths in sorted(owners.items()):
        unique_paths = sorted(set(paths))
        if len(unique_paths) > 1:
            diagnostics.append(
                diagnostic(
                    "DUPLICATE_FACT_STATEMENT",
                    f"quantitative fact has multiple owners: {', '.join(unique_paths)}",
                    unique_paths[0],
                    duplicatePaths=unique_paths[1:],
                )
            )
    return diagnostics
