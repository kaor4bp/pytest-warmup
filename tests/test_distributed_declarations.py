from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_imported_shared_requirement_object_across_files_is_allowed(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from requirements_lib import facility, inventory, program

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="session", autouse=True)
        def assert_counts():
            yield
            assert facility.api.create_facility_calls == 1
            assert program.api.create_program_calls == 1
            assert inventory.api.create_products_calls == 1
        """,
    )
    pytester.makepyfile(
        requirements_lib="""
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)
        """,
        test_file_a="""
        from requirements_lib import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_alpha_a(prepare_data, products):
            assert products["qty"] == 10
        """,
        test_file_b="""
        from requirements_lib import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_alpha_b(prepare_data, products):
            assert products["upc"] == "123"
        """,
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=2)


def test_redeclared_same_id_across_files_fails_fast(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from requirements_common import facility, inventory, program

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """,
    )
    pytester.makepyfile(
        requirements_common="""
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        """,
        test_file_a="""
        from requirements_common import inventory, program_main
        from pytest_warmup import warmup_param

        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @warmup_param("products", products_alpha)
        def test_alpha_a(prepare_data, products):
            assert products
        """,
        test_file_b="""
        from requirements_common import inventory, program_main
        from pytest_warmup import warmup_param

        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @warmup_param("products", products_alpha)
        def test_alpha_b(prepare_data, products):
            assert products
        """,
    )
    result = pytester.runpytest("-q")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*duplicate id 'products_alpha' within one producer scope*"])


def test_redeclared_same_id_with_different_dependency_shape_across_files_fails_fast(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from requirements_common import facility, inventory, program

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """,
    )
    pytester.makepyfile(
        requirements_common="""
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        program_backup = program.require(program_profile="BACKUP", facility=facility_de, id="program_backup")
        """,
        test_file_a="""
        from requirements_common import inventory, program_main
        from pytest_warmup import warmup_param

        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @warmup_param("products", products_alpha)
        def test_alpha_a(prepare_data, products):
            assert products
        """,
        test_file_b="""
        from requirements_common import inventory, program_backup
        from pytest_warmup import warmup_param

        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_backup)

        @warmup_param("products", products_alpha)
        def test_alpha_b(prepare_data, products):
            assert products
        """,
    )
    result = pytester.runpytest("-q")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*duplicate id 'products_alpha' within one producer scope*"])


def test_different_ids_with_same_shape_across_files_stay_distinct_nodes(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from requirements_common import facility, inventory, program

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @pytest.fixture(scope="session", autouse=True)
        def assert_counts():
            yield
            assert facility.api.create_facility_calls == 1
            assert program.api.create_program_calls == 1
            assert inventory.api.create_products_calls == 2
        """,
    )
    pytester.makepyfile(
        requirements_common="""
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        """,
        test_file_a="""
        from requirements_common import inventory, program_main
        from pytest_warmup import warmup_param

        products_alpha_a = inventory.require(qty=10, upc="123", id="products_alpha_a", program=program_main)

        @warmup_param("products", products_alpha_a)
        def test_alpha_a(prepare_data, products):
            assert products["qty"] == 10
        """,
        test_file_b="""
        from requirements_common import inventory, program_main
        from pytest_warmup import warmup_param

        products_alpha_b = inventory.require(qty=10, upc="123", id="products_alpha_b", program=program_main)

        @warmup_param("products", products_alpha_b)
        def test_alpha_b(prepare_data, products):
            assert products["upc"] == "123"
        """,
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=2)


def test_same_id_across_different_plans_in_one_producer_scope_fails_fast(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")

        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="shared_id")
        products_alpha = inventory.require(qty=10, upc="123", id="shared_id", program=program_main)

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        """
        from pytest_warmup import warmup_param
        from conftest import products_alpha

        @warmup_param("products", products_alpha)
        def test_conflict(prepare_data, products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*duplicate id 'shared_id' within one producer scope*"])


def test_same_id_in_different_producer_scopes_is_allowed(
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
        test_file_a="""
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
        def test_alpha_a(prepare_data, products):
            assert products["qty"] == 10
        """,
        test_file_b="""
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
        def test_alpha_b(prepare_data, products):
            assert products["upc"] == "123"
        """,
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=2)
