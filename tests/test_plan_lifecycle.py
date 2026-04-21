from __future__ import annotations

from pathlib import Path

import pytest

from pytest_warmup import WarmupNode, WarmupPlan
from pytest_warmup.core import ProducedValueStore, RuntimeContext


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
ROOT_PATH = Path(__file__).resolve().parents[1]


def test_default_prepare_runs_before_prepare_node_and_after_prepare() -> None:
    events: list[tuple[str, object]] = []

    class DemoPlan(WarmupPlan):
        def before_prepare(self, nodes: list[WarmupNode]) -> None:
            events.append(("before_prepare", [node.id for node in nodes]))

        def prepare_node(self, node: WarmupNode) -> object:
            events.append(("prepare_node", node.id))
            return {"id": node.id}

        def after_prepare(self, nodes: list[WarmupNode]) -> None:
            events.append(("after_prepare", [node.id for node in nodes]))

    plan = DemoPlan("demo")
    nodes, store, runtime = _active_nodes(plan, "alpha", "beta")

    try:
        plan.prepare(nodes)
    finally:
        runtime.finish_batch()

    assert events == [
        ("before_prepare", ["alpha", "beta"]),
        ("prepare_node", "alpha"),
        ("prepare_node", "beta"),
        ("after_prepare", ["alpha", "beta"]),
    ]
    assert store.values_by_runtime_key == {
        "node:alpha": {"id": "alpha"},
        "node:beta": {"id": "beta"},
    }
    assert store.exceptions_by_runtime_key == {}


def test_before_prepare_exception_is_recorded_on_every_node() -> None:
    before_error = RuntimeError("before prepare failed")
    events: list[str] = []

    class DemoPlan(WarmupPlan):
        def before_prepare(self, nodes: list[WarmupNode]) -> None:
            events.append("before_prepare")
            raise before_error

        def prepare_node(self, node: WarmupNode) -> object:
            events.append("prepare_node")
            return {"id": node.id}

        def after_prepare(self, nodes: list[WarmupNode]) -> None:
            events.append("after_prepare")

    plan = DemoPlan("demo")
    nodes, store, runtime = _active_nodes(plan, "alpha", "beta")

    try:
        plan.prepare(nodes)
    finally:
        runtime.finish_batch()

    assert events == ["before_prepare"]
    assert store.values_by_runtime_key == {}
    assert store.exceptions_by_runtime_key == {
        "node:alpha": before_error,
        "node:beta": before_error,
    }


def test_after_prepare_exception_is_recorded_only_on_prepared_nodes() -> None:
    node_error = ValueError("node failed")
    after_error = RuntimeError("after prepare failed")

    class DemoPlan(WarmupPlan):
        def prepare_node(self, node: WarmupNode) -> object:
            if node.id == "beta":
                raise node_error
            return {"id": node.id}

        def after_prepare(self, nodes: list[WarmupNode]) -> None:
            raise after_error

    plan = DemoPlan("demo")
    nodes, store, runtime = _active_nodes(plan, "alpha", "beta")

    try:
        plan.prepare(nodes)
    finally:
        runtime.finish_batch()

    assert store.values_by_runtime_key == {}
    assert store.exceptions_by_runtime_key == {
        "node:alpha": after_error,
        "node:beta": node_error,
    }


def test_before_prepare_exception_is_reported_through_pytest_without_internal_error(
    pytester: pytest.Pytester,
) -> None:
    _install_local_project_paths(pytester)
    pytester.makepyfile(
        """
        import pytest
        from pytest_warmup import WarmupPlan, warmup_param

        class DemoPlan(WarmupPlan):
            def value(self, *, id):
                return super().require(payload={}, dependencies={}, id=id)

            def before_prepare(self, nodes):
                raise RuntimeError("before prepare failed")

            def prepare_node(self, node):
                return {"id": node.id}

        demo = DemoPlan("demo")
        alpha = demo.value(id="alpha")
        beta = demo.value(id="beta")

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(demo).prepare()

        @warmup_param("value", alpha)
        def test_alpha(prepare_data, value):
            assert value

        @warmup_param("value", beta)
        def test_beta(prepare_data, value):
            assert value
        """
    )

    result = pytester.runpytest("-q")

    result.assert_outcomes(failed=2)
    stdout = result.stdout.str()
    assert "RuntimeError: before prepare failed" in stdout
    assert "INTERNALERROR" not in stdout
    assert "did not set a value or exception" not in stdout


def test_prepare_node_exception_is_reported_only_for_that_node(
    pytester: pytest.Pytester,
) -> None:
    _install_local_project_paths(pytester)
    pytester.makepyfile(
        """
        import pytest
        from pytest_warmup import WarmupPlan, warmup_param

        class DemoPlan(WarmupPlan):
            def value(self, *, id):
                return super().require(payload={}, dependencies={}, id=id)

            def prepare_node(self, node):
                if node.id == "beta":
                    raise RuntimeError("beta failed")
                return {"id": node.id}

        demo = DemoPlan("demo")
        alpha = demo.value(id="alpha")
        beta = demo.value(id="beta")

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(demo).prepare()

        @warmup_param("value", alpha)
        def test_alpha(prepare_data, value):
            assert value == {"id": "alpha"}

        @warmup_param("value", beta)
        def test_beta(prepare_data, value):
            assert value
        """
    )

    result = pytester.runpytest("-q")

    result.assert_outcomes(passed=1, failed=1)
    stdout = result.stdout.str()
    assert "RuntimeError: beta failed" in stdout
    assert "INTERNALERROR" not in stdout
    assert "did not set a value or exception" not in stdout


def test_after_prepare_exception_is_reported_for_prepared_nodes_without_hiding_node_errors(
    pytester: pytest.Pytester,
) -> None:
    _install_local_project_paths(pytester)
    pytester.makepyfile(
        """
        import pytest
        from pytest_warmup import WarmupPlan, warmup_param

        class DemoPlan(WarmupPlan):
            def value(self, *, id):
                return super().require(payload={}, dependencies={}, id=id)

            def prepare_node(self, node):
                if node.id == "beta":
                    raise ValueError("beta failed")
                return {"id": node.id}

            def after_prepare(self, nodes):
                raise RuntimeError("after prepare failed")

        demo = DemoPlan("demo")
        alpha = demo.value(id="alpha")
        beta = demo.value(id="beta")

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(demo).prepare()

        @warmup_param("value", alpha)
        def test_alpha(prepare_data, value):
            assert value

        @warmup_param("value", beta)
        def test_beta(prepare_data, value):
            assert value
        """
    )

    result = pytester.runpytest("-q")

    result.assert_outcomes(failed=2)
    stdout = result.stdout.str()
    assert "RuntimeError: after prepare failed" in stdout
    assert "ValueError: beta failed" in stdout
    assert "INTERNALERROR" not in stdout
    assert "did not set a value or exception" not in stdout


def test_custom_prepare_must_complete_every_node(pytester: pytest.Pytester) -> None:
    _install_local_project_paths(pytester)
    pytester.makepyfile(
        """
        import pytest
        from pytest_warmup import WarmupPlan, warmup_param

        class DemoPlan(WarmupPlan):
            def value(self, *, id):
                return super().require(payload={}, dependencies={}, id=id)

            def prepare(self, nodes):
                pass

        demo = DemoPlan("demo")
        alpha = demo.value(id="alpha")

        @pytest.fixture(scope="module")
        def prepare_data(warmup_mgr):
            return warmup_mgr.use(demo).prepare()

        @warmup_param("value", alpha)
        def test_alpha(prepare_data, value):
            assert value
        """
    )

    result = pytester.runpytest("-q")

    result.assert_outcomes(errors=1)
    stdout = result.stdout.str()
    assert "plan 'demo' did not set a value or exception for node 'node-1:shared'" in stdout
    assert "INTERNALERROR" not in stdout


def _active_nodes(
    plan: WarmupPlan,
    *ids: str,
) -> tuple[list[WarmupNode], ProducedValueStore, RuntimeContext]:
    nodes: list[WarmupNode] = []
    for public_id in ids:
        requirement = plan.require(
            payload={"id": public_id},
            dependencies={},
            id=public_id,
        )
        nodes.append(
            WarmupNode(
                _runtime_key=f"node:{public_id}",
                _requirement=requirement,
                _public_id=public_id,
                _test_id=None,
                _per_test=False,
                payload=requirement.payload,
                deps={},
            )
        )
    store = ProducedValueStore()
    runtime = RuntimeContext(producer_scope="module", selected_test_ids=("test_demo",))
    runtime.start_batch(nodes=nodes, store=store)
    return nodes, store, runtime


def _install_local_project_paths(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        f"""
        import sys

        sys.path.insert(0, {str(SRC_PATH)!r})
        sys.path.insert(0, {str(ROOT_PATH)!r})
        """
    )
