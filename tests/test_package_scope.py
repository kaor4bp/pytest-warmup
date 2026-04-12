from __future__ import annotations

import json
from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_package_scope_producer_supports_shared_preparation(
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
        **{
            "pkg/__init__.py": "",
            "pkg/requirements.py": """
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
                products_alpha = inventory.require(
                    qty=10,
                    upc="123",
                    id="products_alpha",
                    program=program_main,
                )
            """,
            "pkg/conftest.py": """
                import pytest

                from .requirements import facility, inventory, program

                @pytest.fixture(scope="package")
                def prepare_data(warmup_mgr):
                    return warmup_mgr.use(facility, program, inventory).prepare()
            """,
            "pkg/test_a.py": """
                from pytest_warmup import warmup_param
                from .requirements import inventory, products_alpha

                @warmup_param("products", products_alpha)
                def test_a(prepare_data, products):
                    del prepare_data
                    assert products["qty"] == 10
                    assert inventory.api.create_products_calls == 1
            """,
            "pkg/test_b.py": """
                from pytest_warmup import warmup_param
                from .requirements import inventory, products_alpha

                @warmup_param("products", products_alpha)
                def test_b(prepare_data, products):
                    del prepare_data
                    assert products["qty"] == 10
                    assert inventory.api.create_products_calls == 1
            """,
        }
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=2)


def test_package_scope_export_template_uses_package_scope_id(
    pytester: pytest.Pytester,
) -> None:
    export_path = pytester.path / "template.snapshot.json"
    pytester.makeconftest(
        f"""
        import sys

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        """
    )
    pytester.makepyfile(
        **{
            "pkg/__init__.py": "",
            "pkg/requirements.py": """
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
                products_alpha = inventory.require(
                    qty=10,
                    upc="123",
                    id="products_alpha",
                    program=program_main,
                )
            """,
            "pkg/conftest.py": """
                import pytest

                from .requirements import facility, inventory, program

                @pytest.fixture(scope="package")
                def prepare_data(warmup_mgr):
                    return warmup_mgr.use(facility, program, inventory).prepare()
            """,
            "pkg/test_a.py": """
                from pytest_warmup import warmup_param
                from .requirements import products_alpha

                @warmup_param("products", products_alpha)
                def test_a(prepare_data, products):
                    del prepare_data
                    assert products["qty"] == 10
            """,
            "pkg/test_b.py": """
                from pytest_warmup import warmup_param
                from .requirements import products_alpha

                @warmup_param("products", products_alpha)
                def test_b(prepare_data, products):
                    del prepare_data
                    assert products["qty"] == 10
            """,
        }
    )
    result = pytester.runpytest(f"--warmup-export-template={export_path}", "-q")
    result.assert_outcomes(passed=2)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    scope_payload = payload["scopes"]["package:pkg::prepare_data"]
    assert scope_payload["shared"] == {
        "facility_de": {},
        "program_main": {},
        "products_alpha": {},
    }
    assert scope_payload["tests"] == {}


def test_package_scope_snapshot_override_uses_package_scope_id(
    pytester: pytest.Pytester,
) -> None:
    snapshot_path = pytester.path / "package.snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": {
                    "package:pkg::prepare_data": {
                        "shared": {
                            "products_alpha": {
                                "value": {
                                    "batch_id": "debug-package",
                                    "program_id": "debug-program",
                                    "qty": 10,
                                    "upc": "123",
                                }
                            }
                        },
                        "tests": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    pytester.makeconftest(
        f"""
        import sys

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        """
    )
    pytester.makepyfile(
        **{
            "pkg/__init__.py": "",
            "pkg/requirements.py": """
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
                products_alpha = inventory.require(
                    qty=10,
                    upc="123",
                    id="products_alpha",
                    program=program_main,
                )
            """,
            "pkg/conftest.py": """
                import pytest

                from .requirements import facility, inventory, program

                @pytest.fixture(scope="package")
                def prepare_data(warmup_mgr):
                    return warmup_mgr.use(facility, program, inventory).prepare()
            """,
            "pkg/test_a.py": """
                from pytest_warmup import warmup_param
                from .requirements import products_alpha

                @warmup_param("products", products_alpha)
                def test_a(prepare_data, products):
                    del prepare_data
                    assert products["batch_id"] == "debug-package"
                    assert products["program_id"] == "debug-program"
            """,
            "pkg/test_b.py": """
                def test_b():
                    assert True
            """,
        }
    )
    result = pytester.runpytest(f"--warmup-snapshot={snapshot_path}", "-q")
    result.assert_outcomes(passed=2)
