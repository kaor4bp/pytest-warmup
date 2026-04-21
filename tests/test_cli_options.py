from __future__ import annotations

import json
from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_cli_snapshot_file_is_used_for_prepare(
    pytester: pytest.Pytester,
) -> None:
    snapshot_path = pytester.path / "cli.snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": {
                    "module:test_snapshot_override_file.py::prepare_data": {
                        "shared": {
                            "program_main": {
                                "value": {
                                    "program_id": "debug-program-1",
                                    "facility_id": "facility-debug",
                                }
                            },
                            "products_alpha": {
                                "value": {
                                    "batch_id": "debug-products-1",
                                    "program_id": "debug-program-1",
                                    "qty": 10,
                                    "upc": "123",
                                }
                            },
                        },
                        "tests": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        test_snapshot_override_file="""
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_snapshot_override(prepare_data, products):
            del prepare_data
            assert products["batch_id"] == "debug-products-1"
            assert products["program_id"] == "debug-program-1"
        """
    )
    result = pytester.runpytest(f"--warmup-snapshot={snapshot_path}", "-q")
    result.assert_outcomes(passed=1)


def test_cli_scoped_snapshot_supports_multiple_producer_scopes(
    pytester: pytest.Pytester,
) -> None:
    snapshot_path = pytester.path / "multi.snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": {
                    "module:test_scope_a.py::prepare_a": {
                        "shared": {
                            "products_alpha_a": {
                                "value": {
                                    "batch_id": "debug-a",
                                    "program_id": "program-a",
                                    "qty": 10,
                                    "upc": "123",
                                }
                            }
                        },
                        "tests": {},
                    },
                    "module:test_scope_b.py::prepare_b": {
                        "shared": {
                            "products_alpha_b": {
                                "value": {
                                    "batch_id": "debug-b",
                                    "program_id": "program-b",
                                    "qty": 20,
                                    "upc": "456",
                                }
                            }
                        },
                        "tests": {},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility_a = FacilityPlan("facility_a")
        program_a = ProgramPlan("program_a")
        inventory_a = InventoryPlan("inventory_a")
        facility_de_a = facility_a.require(country="DE", id="facility_de_a")
        program_main_a = program_a.require(program_profile="MAIN", facility=facility_de_a, id="program_main_a")
        products_alpha_a = inventory_a.require(qty=10, upc="123", id="products_alpha_a", program=program_main_a)

        facility_b = FacilityPlan("facility_b")
        program_b = ProgramPlan("program_b")
        inventory_b = InventoryPlan("inventory_b")
        facility_de_b = facility_b.require(country="DE", id="facility_de_b")
        program_main_b = program_b.require(program_profile="MAIN", facility=facility_de_b, id="program_main_b")
        products_alpha_b = inventory_b.require(qty=20, upc="456", id="products_alpha_b", program=program_main_b)

        @pytest.fixture(scope="module")
        def prepare_a(warmup_mgr):
            return warmup_mgr.use(facility_a, program_a, inventory_a).prepare()

        @pytest.fixture(scope="module")
        def prepare_b(warmup_mgr):
            return warmup_mgr.use(facility_b, program_b, inventory_b).prepare()
        """
    )
    pytester.makepyfile(
        test_scope_a="""
        from conftest import products_alpha_a
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha_a)
        def test_scope_a(prepare_a, products):
            del prepare_a
            assert products["batch_id"] == "debug-a"
        """,
        test_scope_b="""
        from conftest import products_alpha_b
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha_b)
        def test_scope_b(prepare_b, products):
            del prepare_b
            assert products["batch_id"] == "debug-b"
        """,
    )
    result = pytester.runpytest(f"--warmup-snapshot={snapshot_path}", "-q")
    result.assert_outcomes(passed=2)


def test_cli_snapshot_for_conflicts_with_scoped_snapshot_for_same_producer(
    pytester: pytest.Pytester,
) -> None:
    scoped_path = pytester.path / "scoped.snapshot.json"
    scoped_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": {
                    "module:test_conflict.py::prepare_data": {
                        "shared": {
                            "products_alpha": {
                                "value": {
                                    "batch_id": "debug-scoped",
                                    "program_id": "program-scoped",
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
    targeted_path = pytester.path / "targeted.snapshot.json"
    targeted_path.write_text(
        json.dumps(
            {
                "version": 1,
                "shared": {
                    "products_alpha": {
                        "value": {
                            "batch_id": "debug-targeted",
                            "program_id": "program-targeted",
                            "qty": 10,
                            "upc": "123",
                        }
                    }
                },
                "tests": {},
            }
        ),
        encoding="utf-8",
    )
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare(snapshot_id="inventory-main")
        """
    )
    pytester.makepyfile(
        test_conflict="""
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_conflict(prepare_data, products):
            del prepare_data, products
        """
    )
    result = pytester.runpytest(
        f"--warmup-snapshot={scoped_path}",
        f"--warmup-snapshot-for=inventory-main={targeted_path}",
        "-q",
    )
    result.assert_outcomes(errors=1)
    assert "matches both --warmup-snapshot and --warmup-snapshot-for 'inventory-main'" in result.stdout.str()


def test_cli_snapshot_for_fails_when_target_id_is_unused(
    pytester: pytest.Pytester,
) -> None:
    targeted_path = pytester.path / "targeted.snapshot.json"
    targeted_path.write_text(
        json.dumps(
            {
                "version": 1,
                "shared": {
                    "products_alpha": {
                        "value": {
                            "batch_id": "debug-targeted",
                            "program_id": "program-targeted",
                            "qty": 10,
                            "upc": "123",
                        }
                    }
                },
                "tests": {},
            }
        ),
        encoding="utf-8",
    )
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        test_unused_target="""
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_unused_target(prepare_data, products):
            del prepare_data
            assert products["qty"] == 10
        """
    )
    result = pytester.runpytest(
        f"--warmup-snapshot-for=inventory-main={targeted_path}",
        "-q",
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert (
        "unused --warmup-snapshot-for targets: 'inventory-main'; "
        "no producer executed prepare(snapshot_id=...) with these ids in this run"
    ) in result.stdout.str()


def test_cli_export_template_writes_selected_graph_snapshot(
    pytester: pytest.Pytester,
) -> None:
    export_path = pytester.path / "template.snapshot.json"
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        program_per_test = program.require(
            program_profile="SECONDARY",
            facility=facility_de,
            id="program_per_test",
            is_per_test=True,
        )
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)
        products_beta = inventory.require(qty=20, upc="456", id="products_beta", program=program_per_test)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        test_template="""
        import pytest
        from conftest import products_alpha, products_beta
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_shared(prepare_data, products):
            del prepare_data
            assert products["qty"] == 10

        @warmup_param("products", products_beta)
        @pytest.mark.parametrize("label", ["one", "two"])
        def test_per_test(prepare_data, products, label):
            del prepare_data, label
            assert products["qty"] == 20
        """
    )
    result = pytester.runpytest(f"--warmup-export-template={export_path}", "-q")
    result.assert_outcomes(passed=3)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    scope_payload = payload["scopes"]["module:test_template.py::prepare_data"]
    assert set(scope_payload["shared"]) == {"facility_de", "program_main", "products_alpha"}
    assert set(scope_payload["tests"]) == {
        "test_template.py::test_per_test[one]",
        "test_template.py::test_per_test[two]",
    }
    assert set(scope_payload["tests"]["test_template.py::test_per_test[one]"]) == {
        "program_per_test",
        "products_beta",
    }
    assert scope_payload["shared"]["facility_de"] == {}
    assert scope_payload["tests"]["test_template.py::test_per_test[one]"]["products_beta"] == {}


def test_cli_report_writes_structured_json_report(
    pytester: pytest.Pytester,
) -> None:
    report_path = pytester.path / "warmup.report.json"
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        test_report_file="""
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_report(prepare_data, products):
            del prepare_data
            assert products["qty"] == 10
        """
    )
    result = pytester.runpytest(f"--warmup-report={report_path}", "-q")
    result.assert_outcomes(passed=1)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    scope_payload = payload["scopes"]["module:test_report_file.py::prepare_data"]
    assert scope_payload["status"] == "prepared"
    assert scope_payload["producer_scope"] == "module"
    assert scope_payload["selected_test_ids"] == ["test_report_file.py::test_report"]
    assert scope_payload["selected_roots"][0]["public_id"] == "products_alpha"
    assert scope_payload["batch_reports"]


def test_cli_report_merges_multiple_producer_scopes(
    pytester: pytest.Pytester,
) -> None:
    report_path = pytester.path / "warmup.report.json"
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan

        facility_a = FacilityPlan("facility_a")
        program_a = ProgramPlan("program_a")
        inventory_a = InventoryPlan("inventory_a")
        facility_de_a = facility_a.require(country="DE", id="facility_de_a")
        program_main_a = program_a.require(program_profile="MAIN", facility=facility_de_a, id="program_main_a")
        products_alpha_a = inventory_a.require(qty=10, upc="123", id="products_alpha_a", program=program_main_a)

        facility_b = FacilityPlan("facility_b")
        program_b = ProgramPlan("program_b")
        inventory_b = InventoryPlan("inventory_b")
        facility_de_b = facility_b.require(country="DE", id="facility_de_b")
        program_main_b = program_b.require(program_profile="MAIN", facility=facility_de_b, id="program_main_b")
        products_alpha_b = inventory_b.require(qty=20, upc="456", id="products_alpha_b", program=program_main_b)

        @pytest.fixture(scope="module")
        def prepare_a(warmup_mgr):
            return warmup_mgr.use(facility_a, program_a, inventory_a).prepare()

        @pytest.fixture(scope="module")
        def prepare_b(warmup_mgr):
            return warmup_mgr.use(facility_b, program_b, inventory_b).prepare()
        """
    )
    pytester.makepyfile(
        test_scope_a="""
        from conftest import products_alpha_a
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha_a)
        def test_scope_a(prepare_a, products):
            del prepare_a
            assert products["qty"] == 10
        """,
        test_scope_b="""
        from conftest import products_alpha_b
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha_b)
        def test_scope_b(prepare_b, products):
            del prepare_b
            assert products["qty"] == 20
        """,
    )
    result = pytester.runpytest(f"--warmup-report={report_path}", "-q")
    result.assert_outcomes(passed=2)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload["scopes"]) == {
        "module:test_scope_a.py::prepare_a",
        "module:test_scope_b.py::prepare_b",
    }
    assert payload["scopes"]["module:test_scope_a.py::prepare_a"]["selected_test_ids"] == [
        "test_scope_a.py::test_scope_a"
    ]
    assert payload["scopes"]["module:test_scope_b.py::prepare_b"]["selected_test_ids"] == [
        "test_scope_b.py::test_scope_b"
    ]


def test_debug_artifact_outputs_fail_fast_when_xdist_like_mode_is_enabled(
    pytester: pytest.Pytester,
) -> None:
    report_path = pytester.path / "warmup.report.json"
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
        program_main = program.require(program_profile="MAIN", facility=facility_de, id="program_main")
        products_alpha = inventory.require(qty=10, upc="123", id="products_alpha", program=program_main)

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr, pytestconfig):
            pytestconfig.option.numprocesses = 2
            return warmup_mgr.use(facility, program, inventory).prepare()
        """
    )
    pytester.makepyfile(
        """
        from conftest import products_alpha
        from pytest_warmup import warmup_param

        @warmup_param("products", products_alpha)
        def test_report(prepare_data, products):
            del prepare_data, products
        """
    )
    result = pytester.runpytest(f"--warmup-report={report_path}", "-q")
    result.assert_outcomes(errors=1)
    assert "debug artifact outputs are not supported when pytest-xdist is active" in result.stdout.str()


def test_cli_save_on_fail_writes_partial_snapshot(
    pytester: pytest.Pytester,
) -> None:
    snapshot_path = pytester.path / "failed.snapshot.json"
    pytester.makeconftest(
        f"""
        import sys
        import pytest

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        from pytest_warmup import WarmupPlan

        class DemoPlan(WarmupPlan):
            def value(self, *, label, id=None):
                return super().require(payload={{"label": label}}, dependencies={{}}, id=id)

            def prepare(self, nodes):
                for node in nodes:
                    if node.id == "beta":
                        raise RuntimeError("boom")
                    node.set_value({{"label": node.payload["label"]}})

        demo = DemoPlan("demo")
        alpha = demo.value(label="alpha", id="alpha")
        beta = demo.value(label="beta", id="beta")

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(demo).prepare()
        """
    )
    pytester.makepyfile(
        """
        from conftest import alpha, beta
        from pytest_warmup import warmup_param

        @warmup_param("beta_value", beta)
        @warmup_param("alpha_value", alpha)
        def test_prepare_fails(prepare_data, alpha_value, beta_value):
            del prepare_data, alpha_value, beta_value
            assert False
        """
    )
    result = pytester.runpytest(f"--warmup-save-on-fail={snapshot_path}", "-q")
    result.assert_outcomes(errors=1)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["scopes"]) == 1
    scope_payload = next(iter(payload["scopes"].values()))
    assert scope_payload["shared"]["alpha"] == {"value": {"label": "alpha"}}
    assert scope_payload["shared"]["beta"] == {}
