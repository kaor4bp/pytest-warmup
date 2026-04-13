from __future__ import annotations

import json
from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_dependency_chain_supports_direct_test_binding(
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

        @warmup_param("products", products_alpha)
        def test_items(prepare_data, products):
            assert products["qty"] == 10
            assert products["program_id"].startswith("program-")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_dependency_chain_supports_fixture_binding(
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
        @warmup_param("products", products_alpha)
        def alpha_products(prepare_data, products):
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


def test_named_producer_fixture_limits_prepare_to_current_producer(
    pytester: pytest.Pytester,
) -> None:
    report_path = pytester.path / "producer-report.json"
    pytester.makeconftest(
        f"""
        import sys

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)
        products_beta = inventory.require(qty=20, upc="456", id="products_beta", program=program_main)
        """
    )
    pytester.makepyfile(
        test_multi_producer="""
        import pytest
        from conftest import facility, inventory, products_alpha, products_beta, program
        from pytest_warmup import warmup_param

        @pytest.fixture(scope="module")
        def prepare_data_a(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="module")
        def prepare_data_b(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture
        @warmup_param("products", products_alpha, producer_fixture="prepare_data_a")
        def alpha_products(prepare_data_a, products):
            del prepare_data_a
            return products

        @pytest.fixture
        @warmup_param("products", products_beta, producer_fixture="prepare_data_b")
        def beta_products(prepare_data_b, products):
            del prepare_data_b
            return products

        def test_alpha(alpha_products):
            assert alpha_products["qty"] == 10

        def test_beta(beta_products):
            assert beta_products["qty"] == 20
        """
    )
    result = pytester.runpytest(f"--warmup-report={report_path}", "-q")
    result.assert_outcomes(passed=2)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    scopes = payload["scopes"]
    alpha_scope = scopes["module:test_multi_producer.py::prepare_data_a"]
    beta_scope = scopes["module:test_multi_producer.py::prepare_data_b"]
    assert [root["public_id"] for root in alpha_scope["selected_roots"]] == [
        "products_alpha"
    ]
    assert [root["public_id"] for root in beta_scope["selected_roots"]] == [
        "products_beta"
    ]
