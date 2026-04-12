from __future__ import annotations

from pathlib import Path


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_module_scope_producer_respects_keyword_deselection(
    pytester,
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

        from pytest_warmup import warmup_param
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(
            program_profile="MAIN",
            facility=facility_de,
            id="program_main",
        )
        products_first = inventory.require(
            qty=10,
            upc="111",
            id="products_first",
            program=program_main,
            is_per_test=True,
        )
        products_second = inventory.require(
            qty=20,
            upc="222",
            id="products_second",
            program=program_main,
            is_per_test=True,
        )

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @warmup_param("products", products_first)
        def test_first(prepare_data, products):
            del prepare_data, products
            assert inventory.api.create_products_calls == 1

        @warmup_param("products", products_second)
        def test_second(prepare_data, products):
            del prepare_data, products
            assert inventory.api.create_products_calls == 1
        """
    )
    result = pytester.runpytest("-q", "-k", "first")
    result.assert_outcomes(passed=1, deselected=1)

