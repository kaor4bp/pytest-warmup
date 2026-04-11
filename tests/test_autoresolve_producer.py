from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_autoresolve_producer_fixture_supports_direct_test_binding(
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

        @pytest.fixture
        def warmup_autoresolve_producer(prepare_data):
            return prepare_data

        @warmup_param("products", products_alpha)
        def test_items(products):
            assert products["qty"] == 10
            assert products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_autoresolve_producer_fixture_supports_fixture_binding(
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

        @pytest.fixture
        def warmup_autoresolve_producer(prepare_data):
            return prepare_data

        @pytest.fixture
        @warmup_param("products", products_alpha)
        def alpha_products(products):
            return products

        def test_items(alpha_products):
            assert alpha_products["qty"] == 10
            assert alpha_products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_named_producer_fixture_allows_explicit_selection(pytester: pytest.Pytester) -> None:
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

        @warmup_param("products", products_alpha, producer_fixture="prepare_data")
        def test_items(prepare_data, products):
            del prepare_data
            assert products["qty"] == 10
            assert products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_named_producer_fixture_can_disambiguate_multiple_producers(
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

        @warmup_param("products", products_alpha, producer_fixture="prepare_data_a")
        def test_items(helper_a, helper_b, products):
            assert products["qty"] == 10
            assert products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_explicit_chain_producer_wins_over_autoresolve_fallback(
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
        def alternate_prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture
        def warmup_autoresolve_producer(alternate_prepare_data):
            return alternate_prepare_data

        @warmup_param("products", products_alpha)
        def test_items(prepare_data, products):
            del prepare_data
            assert products["qty"] == 10
            assert products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)
