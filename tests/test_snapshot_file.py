from __future__ import annotations

from pathlib import Path

import pytest


ROOT_PATH = Path(__file__).resolve().parents[1]


def test_missing_snapshot_file_fails_fast(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        f"""
        import sys
        from pathlib import Path
        import pytest

        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan
        from pytest_warmup import warmup_param

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")
        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            snapshot_file = Path(__file__).with_name("missing.snapshot.json")
            return warmup_mgr.use(facility, program, inventory).prepare(snapshot_file=snapshot_file)
        """
    )
    pytester.makepyfile(
        """
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_alpha(prepare_data, products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    assert "snapshot file does not exist" in result.stdout.str()


def test_invalid_snapshot_file_fails_fast(pytester: pytest.Pytester) -> None:
    pytester.path.joinpath("broken.snapshot.json").write_text("{not-json", encoding="utf-8")
    pytester.makeconftest(
        f"""
        import sys
        from pathlib import Path
        import pytest

        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan
        from pytest_warmup import warmup_param

        facility = FacilityPlan("facility")
        program = ProgramPlan("program")
        inventory = InventoryPlan("inventory")
        facility_de = facility.require(country="DE", id="facility_de")
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="session")
        def prepare_data(warmup_mgr):
            snapshot_file = Path(__file__).with_name("broken.snapshot.json")
            return warmup_mgr.use(facility, program, inventory).prepare(snapshot_file=snapshot_file)
        """
    )
    pytester.makepyfile(
        """
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_alpha(prepare_data, products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    assert "is not valid JSON" in result.stdout.str()
