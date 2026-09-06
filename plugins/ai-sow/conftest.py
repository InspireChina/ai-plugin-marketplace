"""Explicit, mutually exclusive test layers; selection never skips a failure."""
import pytest

LAYERS = {"unit", "integration", "e2e"}


def pytest_collection_modifyitems(items):
    for item in items:
        explicit = {marker.name for marker in item.iter_markers() if marker.name in LAYERS}
        if len(explicit) > 1:
            raise pytest.UsageError(f"Conflicting test layers: {item.nodeid}")
        if not explicit:
            layer = getattr(item.module, "TEST_LAYER", None)
            if layer not in LAYERS:
                raise pytest.UsageError(f"Declare TEST_LAYER or an explicit layer marker: {item.nodeid}")
            item.add_marker(getattr(pytest.mark, layer))
