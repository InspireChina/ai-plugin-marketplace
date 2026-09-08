"""Explicit, mutually exclusive test layers with isolated imports."""
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

LAYERS = {"unit", "integration", "e2e"}


def pytest_collection_modifyitems(items):
    for item in items:
        explicit = {marker.name for marker in item.iter_markers() if marker.name in LAYERS}
        if len(explicit) > 1:
            raise pytest.UsageError(f"Conflicting test layers: {item.nodeid}")
        if explicit:
            layer = next(iter(explicit))
        else:
            layer = getattr(item.module, "TEST_LAYER", None)
            if layer not in LAYERS:
                raise pytest.UsageError(f"Declare TEST_LAYER or an explicit layer marker: {item.nodeid}")
            item.add_marker(getattr(pytest.mark, layer))
