import pytest
from ejecutar_escenarios import run_case, EXPECTED


@pytest.mark.parametrize("case_id", EXPECTED.keys(), ids=EXPECTED.keys())
def test_escenario(case_id):
    assert run_case(case_id)["passed"]
