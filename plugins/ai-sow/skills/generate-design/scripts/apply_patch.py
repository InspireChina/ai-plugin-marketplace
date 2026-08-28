from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from runtime.patch import run_patch_cli


if __name__ == "__main__":
    raise SystemExit(
        run_patch_cli(
            "generate-design",
            ".ai-sow/work/generate-design/design.candidate.json",
        )
    )
