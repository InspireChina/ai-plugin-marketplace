import os
import tempfile
from pathlib import Path

import pytest

from .support.fixtures import build_contract_case


@pytest.fixture
def contract_case(tmp_path):
    return build_contract_case(tmp_path / "合成项目 with spaces")


def _symlinks_available():
    """Creating a symlink on Windows needs Developer Mode or elevation."""
    if os.name != "nt":
        return True
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            (root / "link").symlink_to(root / "target", target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS_AVAILABLE = _symlinks_available()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Turn an unprivileged symlink failure into a skip, never into a pass.

    These cases assert that link-based escapes stay rejected. Without the
    privilege the escape cannot even be constructed, so the case proves
    nothing either way and must not be silently reported as passing.
    """
    try:
        return (yield)
    except OSError as error:
        if SYMLINKS_AVAILABLE or getattr(error, "winerror", None) != 1314:
            raise
        pytest.skip("Symlink creation requires Developer Mode or elevation on Windows")
