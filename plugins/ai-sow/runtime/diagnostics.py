from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def diagnostic(
    code: str,
    message: str,
    path: str = "",
    **details: Any,
) -> dict[str, object]:
    """Build the canonical diagnostic shape shared by Owner validators."""

    value: dict[str, object] = {"code": code, "message": message}
    if path:
        value["path"] = path
    value.update(details)
    return value


def diagnostic_codes(values: Iterable[dict[str, object]]) -> set[str]:
    return {
        code
        for value in values
        if isinstance((code := value.get("code")), str)
    }
