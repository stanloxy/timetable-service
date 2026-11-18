from pathlib import Path

import pytest

from tests.e2e.contract import ContractChecker


@pytest.fixture
def contract() -> ContractChecker:
    path = Path(__file__).resolve().parents[3] / "openapi.yaml"
    return ContractChecker.from_file(path)
