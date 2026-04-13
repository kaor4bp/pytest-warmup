from __future__ import annotations

from pathlib import Path

import pytest


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_missing_producer_dependency_chain_fails(pytester: pytest.Pytester) -> None:
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

        @pytest.fixture
        @warmup_param("products", products_alpha)
        def alpha_products(products):
            return products

        def test_fail(alpha_products):
            assert alpha_products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        [
            "*no producer fixture found in pytest dependency chain*"
        ]
    )


def test_shared_requirement_cannot_depend_on_per_test_upstream(pytester: pytest.Pytester) -> None:
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
            is_per_test=True,
        )
        products_alpha = inventory.require(
            qty=10,
            upc="123",
            id="products_alpha",
            program=program_main,
            is_per_test=False,
        )

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(facility, program, inventory).prepare()

        @warmup_param("products", products_alpha)
        def test_conflict(prepare_data, products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*products_alpha cannot be shared because dependency program_main is per-test*"]
    )


def test_same_plan_dependency_cycle_fails_fast(pytester: pytest.Pytester) -> None:
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
        from pytest_warmup import WarmupPlan, warmup_param

        class LoopPlan(WarmupPlan):
            def value(self, *, dep=None, id=None):
                dependencies = {}
                if dep is not None:
                    dependencies["dep"] = dep
                return super().require(payload={"kind": "value"}, dependencies=dependencies, id=id)

            def prepare(self, nodes, runtime):
                for node in nodes:
                    runtime.set(node, {"id": node.public_id})

        loop = LoopPlan("loop")
        first = loop.value(id="first")
        second = loop.value(dep=first, id="second")
        first.dependencies["dep"] = second

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(loop).prepare()

        @warmup_param("value", second)
        def test_cycle(prepare_data, value):
            assert value
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*dependency cycle detected: second -> first -> second*"])


def test_cross_plan_dependency_cycle_fails_fast(pytester: pytest.Pytester) -> None:
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
        from pytest_warmup import WarmupPlan, warmup_param

        class AlphaPlan(WarmupPlan):
            def alpha(self, *, beta=None, id=None):
                dependencies = {}
                if beta is not None:
                    dependencies["beta"] = beta
                return super().require(payload={"kind": "alpha"}, dependencies=dependencies, id=id)

            def prepare(self, nodes, runtime):
                for node in nodes:
                    runtime.set(node, {"id": node.public_id})

        class BetaPlan(WarmupPlan):
            def beta(self, *, alpha=None, id=None):
                dependencies = {}
                if alpha is not None:
                    dependencies["alpha"] = alpha
                return super().require(payload={"kind": "beta"}, dependencies=dependencies, id=id)

            def prepare(self, nodes, runtime):
                for node in nodes:
                    runtime.set(node, {"id": node.public_id})

        alpha = AlphaPlan("alpha")
        beta = BetaPlan("beta")
        alpha_root = alpha.alpha(id="alpha_root")
        beta_root = beta.beta(alpha=alpha_root, id="beta_root")
        alpha_root.dependencies["beta"] = beta_root

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(alpha, beta).prepare()

        @warmup_param("value", beta_root)
        def test_cycle(prepare_data, value):
            assert value
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*dependency cycle detected: beta_root -> alpha_root -> beta_root*"]
    )


def test_named_producer_fixture_must_exist(pytester: pytest.Pytester) -> None:
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

        @warmup_param("products", products_alpha, producer_fixture="prepare_data")
        def test_fail(products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*producer fixture 'prepare_data' was not found*"])


def test_named_producer_fixture_must_return_prepared_scope(pytester: pytest.Pytester) -> None:
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

        @pytest.fixture
        def prepare_data():
            return {"not": "prepared"}

        @warmup_param("products", products_alpha, producer_fixture="prepare_data")
        def test_fail(prepare_data, products):
            del prepare_data
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*producer fixture 'prepare_data' must return a prepared warmup scope*"]
    )


def test_named_producer_fixture_must_be_in_dependency_chain(
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

        @warmup_param("products", products_alpha, producer_fixture="prepare_data")
        def test_fail(products):
            assert products
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        ["*producer fixture 'prepare_data' is not in this dependency chain*"]
    )
