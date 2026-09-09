import pytest
from .support.fixtures import build_contract_case


@pytest.fixture
def contract_case(tmp_path):
    return build_contract_case(tmp_path / "合成项目 with spaces")
