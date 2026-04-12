from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_multiple_warmup_bindings_inject_multiple_values(
    pytester: pytest.Pytester,
) -> None:
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
        program_main = program.require(
            program_profile="MAIN",
            facility=facility_de,
            id="program_main",
        )
        products_alpha = inventory.require(
            qty=10,
            upc="123",
            program=program_main,
            id="products_alpha",
        )

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @warmup_param("program_value", program_main)
        @warmup_param("products", products_alpha)
        def test_multiple_bindings(prepare_data, program_value, products):
            del prepare_data
            assert program_value["program_id"].startswith("program-")
            assert products["program_id"] == program_value["program_id"]
            assert products["qty"] == 10
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_multiple_bindings_must_agree_on_named_producer_fixture(
    pytester: pytest.Pytester,
) -> None:
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
        program_main = program.require(
            program_profile="MAIN",
            facility=facility_de,
            id="program_main",
        )
        products_alpha = inventory.require(
            qty=10,
            upc="123",
            program=program_main,
            id="products_alpha",
        )

        @pytest.fixture(scope="module")
        def prepare_data_a(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="module")
        def prepare_data_b(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @warmup_param("program_value", program_main, producer_fixture="prepare_data_a")
        @warmup_param("products", products_alpha, producer_fixture="prepare_data_b")
        def test_conflict(prepare_data_a, prepare_data_b, program_value, products):
            del prepare_data_a, prepare_data_b, program_value, products
            assert False
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*warmup_param bindings on callable 'test_conflict' must agree on producer_fixture*",
        ]
    )
