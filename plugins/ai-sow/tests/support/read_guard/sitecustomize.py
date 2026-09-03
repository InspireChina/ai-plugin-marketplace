from __future__ import annotations

import os
from pathlib import Path


_ORIGINAL_OPEN = Path.open
_ALLOWED = tuple(
    Path(item).resolve()
    for item in os.environ["AI_SOW_ALLOWED_READ_ROOTS"].split(os.pathsep)
    if item
)
_LOG = Path(os.environ["AI_SOW_FORBIDDEN_READ_LOG"])


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _guarded_open(
    self: Path,
    mode: str = "r",
    buffering: int = -1,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
):
    if mode.startswith("r"):
        resolved = self.resolve()
        if not any(_within(resolved, root) for root in _ALLOWED):
            with open(_LOG, "a", encoding="utf-8") as stream:
                stream.write(str(resolved) + "\n")
            raise RuntimeError(
                f"runtime read escaped installed plugin/project roots: {resolved}"
            )
    return _ORIGINAL_OPEN(self, mode, buffering, encoding, errors, newline)


Path.open = _guarded_open
