from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_explicit_producer_scope_mismatch_uses_pytest_fail_fast(
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="session")
        @warmup_param("products", products_alpha)
        def alpha_products(prepare_data, products):
            return products

        def test_items(alpha_products):
            assert alpha_products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*ScopeMismatch: You tried to access the module scoped fixture prepare_data with a session scoped request object*"]
    )


def test_autoresolve_producer_scope_mismatch_uses_pytest_fail_fast(
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="module")
        def warmup_autoresolve_producer(prepare_data):
            return prepare_data

        @pytest.fixture(scope="session")
        @warmup_param("products", products_alpha)
        def alpha_products(products):
            return products

        def test_items(alpha_products):
            assert alpha_products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*producer fixture 'warmup_autoresolve_producer' is defined but not available for this pytest request scope*"]
    )
