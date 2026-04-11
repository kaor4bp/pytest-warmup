from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_multiple_indirect_producers_fail_fast(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        f"""
        import sys

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        """
    )
    pytester.makepyfile(
        """
        import pytest
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan
        from pytest_warmup import warmup_param

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data_a(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="module")
        def prepare_data_b(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture
        def helper_a(prepare_data_a):
            return prepare_data_a

        @pytest.fixture
        def helper_b(prepare_data_b):
            return prepare_data_b

        @warmup_param("products", products_alpha)
        def test_conflict(helper_a, helper_b, products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*multiple producer fixtures found in pytest dependency chain*"])
