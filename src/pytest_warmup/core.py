"""Core declaration, preparation, and injection primitives for pytest-warmup."""

from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from inspect import Parameter, Signature, isgeneratorfunction, signature
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
import functools
import json

import pytest

WARMUP_BINDING_ATTR = "__warmup_binding__"
AUTORESOLVE_PRODUCER_FIXTURE = "warmup_autoresolve_producer"
CURRENT_FIXTURE_REQUEST: ContextVar[pytest.FixtureRequest | None] = ContextVar(
    "warmup_current_fixture_request",
    default=None,
)


class WarmupError(ValueError):
    """Raised when warmup declaration, preparation, or injection fails fast."""

    pass


@dataclass(frozen=True, eq=False)
class WarmupRequirement:
    """Declarative description of a warmup resource node."""

    owner_plan: "WarmupPlan"
    payload: Mapping[str, object]
    dependencies: Mapping[str, "WarmupRequirement | tuple[WarmupRequirement, ...]"]
    id: str | None = None
    is_per_test: bool | None = None

    def iter_dependency_requirements(self) -> tuple["WarmupRequirement", ...]:
        discovered: list[WarmupRequirement] = []
        for value in self.dependencies.values():
            if isinstance(value, WarmupRequirement):
                discovered.append(value)
                continue
            discovered.extend(value)
        return tuple(discovered)


class WarmupPlan:
    """Base class for domain-specific plans that declare and prepare resources."""

    def __init__(self, name: str) -> None:
        self.name = name

    def require(
        self,
        *,
        payload: Mapping[str, object] | None = None,
        dependencies: Mapping[str, WarmupRequirement | tuple[WarmupRequirement, ...]]
        | None = None,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        """Create a declarative resource requirement owned by this plan.

        `payload` is passed through to the plan unchanged.
        `dependencies` contains already-declared upstream requirements.
        `id` is an addressable debug key, not a merge key.
        `is_per_test` controls whether the requirement should be materialized
        per collected test item or shared within the producer scope.
        """
        return self._build_requirement(
            payload=payload or {},
            dependencies=dependencies or {},
            id=id,
            is_per_test=is_per_test,
        )

    def _build_requirement(
        self,
        *,
        payload: Mapping[str, object],
        dependencies: Mapping[str, WarmupRequirement | tuple[WarmupRequirement, ...]],
        id: str | None,
        is_per_test: bool | None,
    ) -> WarmupRequirement:
        normalized_dependencies: dict[str, WarmupRequirement | tuple[WarmupRequirement, ...]] = {}
        for slot, value in dependencies.items():
            if isinstance(value, WarmupRequirement):
                normalized_dependencies[slot] = value
                continue
            normalized_dependencies[slot] = tuple(value)
        return WarmupRequirement(
            owner_plan=self,
            payload=dict(payload),
            dependencies=normalized_dependencies,
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(
        self,
        nodes: list["PlanNode"],
        runtime: "RuntimeContext",
    ) -> None:
        """Materialize a batch of plan-owned nodes into the active runtime.

        Subclasses should iterate over `nodes`, call external APIs or domain
        helpers as needed, and publish results through `runtime.set(...)` or
        `runtime.set_exception(...)`.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class WarmupBinding:
    argument_name: str
    requirement: WarmupRequirement
    producer_fixture: str | None = None


@dataclass(frozen=True)
class SelectedRoot:
    consumer_id: str
    source_kind: str
    source_name: str
    binding: WarmupBinding


@dataclass(frozen=True)
class NormalizedNode:
    node_key: str
    requirement: WarmupRequirement
    owner_plan: WarmupPlan
    dependency_keys: tuple[str, ...]
    public_id: str | None


@dataclass(frozen=True)
class RuntimeInstance:
    runtime_key: str
    node: NormalizedNode
    test_id: str | None
    per_test: bool
    dependency_runtime_keys: Mapping[str, str | tuple[str, ...]]


@dataclass(frozen=True)
class PlanNode:
    runtime_key: str
    requirement: WarmupRequirement
    public_id: str | None
    test_id: str | None
    per_test: bool
    payload: Mapping[str, object]
    deps: Mapping[str, object | tuple[object, ...]]


@dataclass
class ProducedValueStore:
    values_by_runtime_key: dict[str, object] = field(default_factory=dict)
    exceptions_by_runtime_key: dict[str, BaseException] = field(default_factory=dict)
    shared_by_requirement: dict[WarmupRequirement, str] = field(default_factory=dict)
    per_test_by_requirement: dict[tuple[WarmupRequirement, str], str] = field(
        default_factory=dict
    )

    def value_for(self, requirement: WarmupRequirement, test_id: str) -> object:
        runtime_key = self.per_test_by_requirement.get((requirement, test_id))
        if runtime_key is not None:
            return self.value_for_runtime_key(runtime_key)
        runtime_key = self.shared_by_requirement.get(requirement)
        if runtime_key is None:
            raise WarmupError(
                f"no prepared runtime value for requirement {requirement!r} and test {test_id!r}"
            )
        return self.value_for_runtime_key(runtime_key)

    def value_for_runtime_key(self, runtime_key: str) -> object:
        if runtime_key in self.exceptions_by_runtime_key:
            raise self.exceptions_by_runtime_key[runtime_key]
        return self.values_by_runtime_key[runtime_key]


@dataclass
class RuntimeContext:
    producer_scope: str
    selected_test_ids: tuple[str, ...]
    trace: list[str] = field(default_factory=list)
    _store: ProducedValueStore | None = field(default=None, init=False, repr=False)
    _active_batch: dict[str, PlanNode] = field(default_factory=dict, init=False, repr=False)

    def start_batch(
        self,
        *,
        nodes: list[PlanNode],
        store: ProducedValueStore,
    ) -> None:
        self._store = store
        self._active_batch = {node.runtime_key: node for node in nodes}

    def finish_batch(self) -> None:
        self._active_batch = {}
        self._store = None

    def set(self, node: PlanNode, value: object) -> None:
        store = self._require_active_store()
        self._require_active_node(node)
        store.values_by_runtime_key[node.runtime_key] = value
        if node.per_test:
            store.per_test_by_requirement[(node.requirement, node.test_id or "")] = node.runtime_key
        else:
            store.shared_by_requirement[node.requirement] = node.runtime_key

    def set_exception(self, node: PlanNode, exc: BaseException) -> None:
        store = self._require_active_store()
        self._require_active_node(node)
        store.exceptions_by_runtime_key[node.runtime_key] = exc
        if node.per_test:
            store.per_test_by_requirement[(node.requirement, node.test_id or "")] = node.runtime_key
        else:
            store.shared_by_requirement[node.requirement] = node.runtime_key
        self.trace.append(f"exception:{node.runtime_key}:{exc.__class__.__name__}")

    def _require_active_store(self) -> ProducedValueStore:
        if self._store is None:
            raise WarmupError("runtime.set(...) may only be used during active plan.prepare(...)")
        return self._store

    def _require_active_node(self, node: PlanNode) -> None:
        if node.runtime_key not in self._active_batch:
            raise WarmupError(
                f"runtime operation targets unknown node {node.runtime_key!r} outside active batch"
            )


@dataclass
class PreparedScope:
    runtime: RuntimeContext
    store: ProducedValueStore

    def value_for(self, *, test_id: str, requirement: WarmupRequirement) -> object:
        return self.store.value_for(requirement, test_id)


def warmup_param(
    argument_name: str,
    requirement: WarmupRequirement,
    *,
    producer_fixture: str | None = None,
) -> Callable:
    """Inject a materialized warmup resource into a test or fixture argument.

    The decorated callable receives the prepared value for `requirement`
    through `argument_name`. Producer resolution prefers an explicitly named
    `producer_fixture`, then an already-present prepared producer in the
    dependency chain, and finally the `warmup_autoresolve_producer` fallback
    fixture when available.
    """
    if not isinstance(requirement, WarmupRequirement):
        raise TypeError("warmup_param binding requires a WarmupRequirement")

    binding = WarmupBinding(
        argument_name=argument_name,
        requirement=requirement,
        producer_fixture=producer_fixture,
    )

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        if hasattr(func, WARMUP_BINDING_ATTR):
            raise WarmupError("only one warmup_param binding is supported per decorated callable")

        original_signature = signature(func)
        if argument_name not in original_signature.parameters:
            raise WarmupError(
                f"warmup_param argument {argument_name!r} is missing from callable {func.__name__!r}"
            )

        visible_parameters = [
            parameter
            for name, parameter in original_signature.parameters.items()
            if name != argument_name
        ]
        if "request" not in original_signature.parameters:
            visible_parameters.append(
                Parameter(
                    "request",
                    kind=Parameter.KEYWORD_ONLY,
                )
            )
        visible_signature = Signature(parameters=visible_parameters)

        if isgeneratorfunction(func):

            @functools.wraps(func)
            def wrapped(*args: object, **kwargs: object) -> object:
                request = kwargs.pop("request")
                _validate_no_fixture_name_collision(
                    request=request,
                    argument_name=argument_name,
                )
                prepared_scope = _locate_prepared_scope(
                    request,
                    kwargs.values(),
                    producer_fixture=producer_fixture,
                )
                injected = prepared_scope.value_for(
                    test_id=request.node.nodeid,
                    requirement=requirement,
                )
                kwargs[argument_name] = injected
                yield from func(*args, **kwargs)

        else:

            @functools.wraps(func)
            def wrapped(*args: object, **kwargs: object) -> object:
                request = kwargs.pop("request")
                _validate_no_fixture_name_collision(
                    request=request,
                    argument_name=argument_name,
                )
                prepared_scope = _locate_prepared_scope(
                    request,
                    kwargs.values(),
                    producer_fixture=producer_fixture,
                )
                injected = prepared_scope.value_for(
                    test_id=request.node.nodeid,
                    requirement=requirement,
                )
                kwargs[argument_name] = injected
                return func(*args, **kwargs)

        setattr(wrapped, WARMUP_BINDING_ATTR, binding)
        wrapped.__signature__ = visible_signature
        return wrapped

    return decorator


def _validate_no_fixture_name_collision(
    *, request: pytest.FixtureRequest, argument_name: str
) -> None:
    __tracebackhide__ = True
    fixturedefs = request._fixturemanager.getfixturedefs(argument_name, request.node)
    if fixturedefs:
        raise WarmupError(
            f"warmup_param-injected argument {argument_name!r} collides with ordinary pytest fixture resolution"
        )


def _locate_prepared_scope(
    request: pytest.FixtureRequest,
    provided_values: Iterable[object] = (),
    *,
    producer_fixture: str | None = None,
) -> PreparedScope:
    __tracebackhide__ = True
    found: list[PreparedScope] = []
    for value in provided_values:
        if isinstance(value, PreparedScope):
            found.append(value)
    if len(found) > 1:
        if producer_fixture is None:
            raise WarmupError("multiple producer fixtures found in pytest dependency chain")

    if producer_fixture is not None:
        named_scope = _resolve_named_producer_fixture(
            request,
            producer_fixture,
            required=True,
            require_in_chain=True,
        )
        return named_scope

    if len(found) == 1:
        return found[0]

    for fixture_name in request.fixturenames:
        if fixture_name in {
            "request",
            getattr(request, "fixturename", None),
            AUTORESOLVE_PRODUCER_FIXTURE,
        }:
            continue
        value = request.getfixturevalue(fixture_name)
        if isinstance(value, PreparedScope):
            found.append(value)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise WarmupError("multiple producer fixtures found in pytest dependency chain")

    autoresolved = _resolve_named_producer_fixture(
        request,
        AUTORESOLVE_PRODUCER_FIXTURE,
        required=False,
        require_in_chain=False,
    )
    if autoresolved is not None:
        return autoresolved
    raise WarmupError(
        "no producer fixture found in pytest dependency chain and no "
        "'warmup_autoresolve_producer' fixture is available"
    )


def _resolve_named_producer_fixture(
    request: pytest.FixtureRequest,
    fixture_name: str,
    *,
    required: bool,
    require_in_chain: bool,
) -> PreparedScope | None:
    fixturedefs = request._fixturemanager.getfixturedefs(fixture_name, request.node)
    if not fixturedefs:
        all_fixturedefs = getattr(request._fixturemanager, "_arg2fixturedefs", {}).get(
            fixture_name
        )
        if all_fixturedefs:
            raise WarmupError(
                f"producer fixture {fixture_name!r} is defined but not available for this pytest request scope"
            )
        if required:
            raise WarmupError(f"producer fixture {fixture_name!r} was not found")
        return None
    if require_in_chain and fixture_name not in request.fixturenames:
        raise WarmupError(f"producer fixture {fixture_name!r} is not in this dependency chain")
    value = request.getfixturevalue(fixture_name)
    if not isinstance(value, PreparedScope):
        raise WarmupError(
            f"producer fixture {fixture_name!r} must return a prepared warmup scope"
        )
    return value


@dataclass
class WarmupSessionState:
    items: list[pytest.Item] = field(default_factory=list)


class WarmupManager:
    """Entry point exposed by the pytest plugin for producer fixtures."""

    def __init__(self, state: WarmupSessionState) -> None:
        self._state = state

    def use(self, *plans: WarmupPlan) -> "WarmupPreparationBuilder":
        """Start a preparation builder for the selected plans."""
        request = CURRENT_FIXTURE_REQUEST.get()
        if request is None:
            raise WarmupError("warmup_mgr.use(...) must be called inside a producer fixture")
        return WarmupPreparationBuilder(request, self._state, plans)


class WarmupPreparationBuilder:
    """Collects the producer fixture context needed to prepare selected roots."""

    def __init__(
        self,
        request: pytest.FixtureRequest,
        state: WarmupSessionState,
        plans: tuple[WarmupPlan, ...],
    ) -> None:
        self._request = request
        self._state = state
        self._plans = plans

    def prepare(self, *, snapshot_file: str | Path | None = None) -> PreparedScope:
        """Prepare the selected warmup graph for the current producer scope."""
        __tracebackhide__ = True
        selected_items = _selected_items_for_scope(self._request, self._state.items)
        selected_roots = _collect_selected_roots(selected_items, set(self._plans))
        normalized_nodes = _normalize_requirements(selected_roots)
        _validate_ids(normalized_nodes)
        effective_per_test = _effective_per_test_modes(normalized_nodes)
        runtime_instances = _build_runtime_instances(
            normalized_nodes,
            selected_roots,
            effective_per_test,
        )
        overrides = _load_overrides(snapshot_file)
        _validate_overrides(normalized_nodes, runtime_instances, overrides, selected_items)

        runtime = RuntimeContext(
            producer_scope=self._request.scope,
            selected_test_ids=tuple(item.nodeid for item in selected_items),
        )
        store = ProducedValueStore()
        _materialize(
            runtime_instances=runtime_instances,
            normalized_nodes=normalized_nodes,
            store=store,
            runtime=runtime,
            overrides=overrides,
        )
        return PreparedScope(runtime=runtime, store=store)


def _selected_items_for_scope(
    request: pytest.FixtureRequest,
    items: list[pytest.Item],
) -> list[pytest.Item]:
    __tracebackhide__ = True
    scope = request.scope
    if scope == "session":
        return list(items)

    if scope == "function":
        current_id = request.node.nodeid
        return [item for item in items if item.nodeid == current_id]

    if scope == "module":
        current_path = Path(str(request.node.path))
        return [item for item in items if Path(str(item.path)) == current_path]

    if scope == "class":
        current_class = request.node.cls
        return [item for item in items if item.cls is current_class]

    raise WarmupError(f"unsupported producer scope {scope!r}")


def _collect_selected_roots(
    items: list[pytest.Item],
    allowed_plans: set[WarmupPlan],
) -> list[SelectedRoot]:
    collected: list[SelectedRoot] = []
    for item in items:
        test_binding = getattr(item.obj, WARMUP_BINDING_ATTR, None)
        if test_binding and test_binding.requirement.owner_plan in allowed_plans:
            collected.append(
                SelectedRoot(
                    consumer_id=item.nodeid,
                    source_kind="test",
                    source_name=item.name,
                    binding=test_binding,
                )
            )
        fixture_info = getattr(item, "_fixtureinfo", None)
        if fixture_info is None:
            continue
        for fixture_name, fixturedefs in fixture_info.name2fixturedefs.items():
            if not fixturedefs:
                continue
            fixturedef = fixturedefs[-1]
            func = getattr(fixturedef, "func", None) or getattr(
                fixturedef, "_fixturefunc", None
            )
            fixture_binding = getattr(func, WARMUP_BINDING_ATTR, None)
            if fixture_binding is None:
                continue
            if fixture_binding.requirement.owner_plan not in allowed_plans:
                continue
            collected.append(
                SelectedRoot(
                    consumer_id=item.nodeid,
                    source_kind="fixture",
                    source_name=fixture_name,
                    binding=fixture_binding,
                )
            )
    return collected


def _normalize_requirements(
    selected_roots: list[SelectedRoot],
) -> tuple[NormalizedNode, ...]:
    __tracebackhide__ = True
    seen: dict[WarmupRequirement, NormalizedNode] = {}
    ordered: list[NormalizedNode] = []
    active: set[WarmupRequirement] = set()
    active_path: list[WarmupRequirement] = []

    def visit(requirement: WarmupRequirement) -> None:
        if requirement in seen:
            return
        if requirement in active:
            cycle_start = active_path.index(requirement)
            cycle = active_path[cycle_start:] + [requirement]
            labels = " -> ".join(_requirement_label(item) for item in cycle)
            raise WarmupError(f"dependency cycle detected: {labels}")

        active.add(requirement)
        active_path.append(requirement)
        try:
            dependencies = requirement.iter_dependency_requirements()
            for dependency in dependencies:
                visit(dependency)
            node_key = f"node-{len(seen) + 1}"
            node = NormalizedNode(
                node_key=node_key,
                requirement=requirement,
                owner_plan=requirement.owner_plan,
                dependency_keys=tuple(seen[dependency].node_key for dependency in dependencies),
                public_id=requirement.id,
            )
            seen[requirement] = node
            ordered.append(node)
        finally:
            active_path.pop()
            active.remove(requirement)

    for root in selected_roots:
        visit(root.binding.requirement)
    return tuple(ordered)


def _requirement_label(requirement: WarmupRequirement) -> str:
    if requirement.id is not None:
        return requirement.id
    return f"{requirement.owner_plan.name}@{id(requirement):x}"


def _effective_per_test_modes(
    normalized_nodes: tuple[NormalizedNode, ...],
) -> dict[WarmupRequirement, bool]:
    __tracebackhide__ = True
    effective: dict[WarmupRequirement, bool] = {}
    for node in normalized_nodes:
        upstream_is_per_test = any(
            effective[dependency]
            for dependency in node.requirement.iter_dependency_requirements()
        )
        declared = node.requirement.is_per_test
        if declared is True:
            effective[node.requirement] = True
            continue
        if declared is None:
            effective[node.requirement] = upstream_is_per_test
            continue
        if upstream_is_per_test:
            requirement_label = _requirement_label(node.requirement)
            dependency_labels = ", ".join(
                _requirement_label(dependency)
                for dependency in node.requirement.iter_dependency_requirements()
                if effective[dependency]
            )
            raise WarmupError(
                f"{requirement_label} cannot be shared because dependency {dependency_labels} is per-test"
            )
        effective[node.requirement] = False
    return effective


def _validate_ids(normalized_nodes: tuple[NormalizedNode, ...]) -> None:
    __tracebackhide__ = True
    nodes_by_id: dict[str, WarmupRequirement] = {}
    for node in normalized_nodes:
        if node.public_id is None:
            continue
        existing = nodes_by_id.get(node.public_id)
        if existing is None:
            nodes_by_id[node.public_id] = node.requirement
            continue
        if existing is not node.requirement:
            raise WarmupError(
                f"duplicate id {node.public_id!r} within one producer scope"
            )


def _build_runtime_instances(
    normalized_nodes: tuple[NormalizedNode, ...],
    selected_roots: list[SelectedRoot],
    effective_per_test: Mapping[WarmupRequirement, bool],
) -> tuple[RuntimeInstance, ...]:
    consumer_test_ids_by_requirement: dict[WarmupRequirement, set[str]] = defaultdict(set)
    for root in selected_roots:
        _attach_consumer_test_id(
            requirement=root.binding.requirement,
            consumer_id=root.consumer_id,
            consumer_test_ids_by_requirement=consumer_test_ids_by_requirement,
        )

    runtime_instances: list[RuntimeInstance] = []
    shared_runtime_keys: dict[WarmupRequirement, str] = {}
    per_test_runtime_keys: dict[tuple[WarmupRequirement, str], str] = {}

    for node in normalized_nodes:
        consumer_ids = consumer_test_ids_by_requirement.get(node.requirement, set())
        if effective_per_test[node.requirement]:
            for test_id in sorted(consumer_ids):
                dependency_keys = _resolve_dependency_runtime_keys(
                    requirement=node.requirement,
                    test_id=test_id,
                    shared_runtime_keys=shared_runtime_keys,
                    per_test_runtime_keys=per_test_runtime_keys,
                )
                runtime_key = f"{node.node_key}:{test_id}"
                runtime_instances.append(
                    RuntimeInstance(
                        runtime_key=runtime_key,
                        node=node,
                        test_id=test_id,
                        per_test=True,
                        dependency_runtime_keys=dependency_keys,
                    )
                )
                per_test_runtime_keys[(node.requirement, test_id)] = runtime_key
            continue

        dependency_keys = _resolve_dependency_runtime_keys(
            requirement=node.requirement,
            test_id=None,
            shared_runtime_keys=shared_runtime_keys,
            per_test_runtime_keys=per_test_runtime_keys,
        )
        runtime_key = f"{node.node_key}:shared"
        runtime_instances.append(
            RuntimeInstance(
                runtime_key=runtime_key,
                node=node,
                test_id=None,
                per_test=False,
                dependency_runtime_keys=dependency_keys,
            )
        )
        shared_runtime_keys[node.requirement] = runtime_key

    return tuple(runtime_instances)


def _attach_consumer_test_id(
    *,
    requirement: WarmupRequirement,
    consumer_id: str,
    consumer_test_ids_by_requirement: dict[WarmupRequirement, set[str]],
) -> None:
    if consumer_id in consumer_test_ids_by_requirement[requirement]:
        return
    consumer_test_ids_by_requirement[requirement].add(consumer_id)
    for dependency in requirement.iter_dependency_requirements():
        _attach_consumer_test_id(
            requirement=dependency,
            consumer_id=consumer_id,
            consumer_test_ids_by_requirement=consumer_test_ids_by_requirement,
        )


def _resolve_dependency_runtime_keys(
    *,
    requirement: WarmupRequirement,
    test_id: str | None,
    shared_runtime_keys: Mapping[WarmupRequirement, str],
    per_test_runtime_keys: Mapping[tuple[WarmupRequirement, str], str],
) -> dict[str, str | tuple[str, ...]]:
    resolved: dict[str, str | tuple[str, ...]] = {}
    for slot, value in requirement.dependencies.items():
        if isinstance(value, WarmupRequirement):
            resolved[slot] = _dependency_runtime_key(
                dependency=value,
                test_id=test_id,
                shared_runtime_keys=shared_runtime_keys,
                per_test_runtime_keys=per_test_runtime_keys,
            )
            continue
        resolved[slot] = tuple(
            _dependency_runtime_key(
                dependency=dependency,
                test_id=test_id,
                shared_runtime_keys=shared_runtime_keys,
                per_test_runtime_keys=per_test_runtime_keys,
            )
            for dependency in value
        )
    return resolved


def _dependency_runtime_key(
    *,
    dependency: WarmupRequirement,
    test_id: str | None,
    shared_runtime_keys: Mapping[WarmupRequirement, str],
    per_test_runtime_keys: Mapping[tuple[WarmupRequirement, str], str],
) -> str:
    if test_id is not None and (dependency, test_id) in per_test_runtime_keys:
        return per_test_runtime_keys[(dependency, test_id)]
    if dependency in shared_runtime_keys:
        return shared_runtime_keys[dependency]
    raise WarmupError(f"missing dependency runtime key for {dependency!r}")


def _load_overrides(snapshot_file: str | Path | None) -> dict[str, dict[str, object]]:
    __tracebackhide__ = True
    if snapshot_file is None:
        return {"shared": {}, "tests": {}}
    snapshot_path = Path(snapshot_file)
    if not snapshot_path.exists():
        raise WarmupError(f"snapshot file does not exist: {str(snapshot_path)!r}")
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WarmupError(
            f"snapshot file {str(snapshot_path)!r} is not valid JSON"
        ) from exc
    if not isinstance(raw, Mapping):
        raise WarmupError("snapshot file content must be a JSON object")
    return _normalize_overrides_mapping(raw)


def _normalize_overrides_mapping(overrides: Mapping[str, object]) -> dict[str, dict[str, object]]:
    __tracebackhide__ = True
    shared = overrides.get("shared", {})
    tests = overrides.get("tests", {})
    if not isinstance(shared, Mapping):
        raise WarmupError("snapshot file field 'shared' must be a mapping")
    if not isinstance(tests, Mapping):
        raise WarmupError("snapshot file field 'tests' must be a mapping")
    normalized_tests: dict[str, dict[str, object]] = {}
    for test_id, values in tests.items():
        if not isinstance(values, Mapping):
            raise WarmupError("snapshot file per-test entry must be a mapping")
        normalized_tests[str(test_id)] = dict(values)
    return {"shared": dict(shared), "tests": normalized_tests}


def _validate_overrides(
    normalized_nodes: tuple[NormalizedNode, ...],
    runtime_instances: tuple[RuntimeInstance, ...],
    overrides: Mapping[str, dict[str, object]],
    selected_items: list[pytest.Item],
) -> None:
    __tracebackhide__ = True
    public_ids = {node.public_id for node in normalized_nodes if node.public_id is not None}
    per_test_ids = {
        instance.node.public_id
        for instance in runtime_instances
        if instance.per_test and instance.node.public_id is not None
    }
    selected_test_ids = {item.nodeid for item in selected_items}

    for public_id in overrides["shared"]:
        if public_id not in public_ids:
            raise WarmupError(f"unknown shared override id {public_id!r}")
        if public_id in per_test_ids:
            raise WarmupError(
                f"shared override {public_id!r} targets a per-test runtime node"
            )

        for test_id, values in overrides["tests"].items():
            if test_id not in selected_test_ids:
                raise WarmupError(f"unknown test id in overrides: {test_id!r}")
            for public_id in values:
                if public_id not in public_ids:
                    raise WarmupError(f"unknown per-test override id {public_id!r}")


def _materialize(
    *,
    runtime_instances: tuple[RuntimeInstance, ...],
    normalized_nodes: tuple[NormalizedNode, ...],
    store: ProducedValueStore,
    runtime: RuntimeContext,
    overrides: Mapping[str, dict[str, object]],
) -> None:
    requirement_by_public_id = {
        node.public_id: node.requirement for node in normalized_nodes if node.public_id is not None
    }
    existing_per_test_instances = {
        (instance.node.requirement, instance.test_id or "")
        for instance in runtime_instances
        if instance.per_test
    }

    for test_id, values in overrides["tests"].items():
        for public_id, value in values.items():
            requirement = requirement_by_public_id[public_id]
            if (requirement, test_id) in existing_per_test_instances:
                continue
            runtime_key = f"override:{public_id}:{test_id}"
            store.values_by_runtime_key[runtime_key] = value
            store.per_test_by_requirement[(requirement, test_id)] = runtime_key
            runtime.trace.append(f"override_test:{test_id}:{public_id}")

    plans = _topologically_sorted_plans(normalized_nodes)
    for plan in plans:
        instances = [instance for instance in runtime_instances if instance.node.owner_plan is plan]
        if not instances:
            continue
        pending: list[RuntimeInstance] = []

        for instance in instances:
            public_id = instance.node.public_id
            if public_id is not None and instance.per_test:
                test_overrides = overrides["tests"].get(instance.test_id or "", {})
                if public_id in test_overrides:
                    value = test_overrides[public_id]
                    store.values_by_runtime_key[instance.runtime_key] = value
                    store.per_test_by_requirement[(instance.node.requirement, instance.test_id or "")] = instance.runtime_key
                    runtime.trace.append(f"override_test:{instance.test_id}:{public_id}")
                    continue
            if public_id is not None and not instance.per_test and public_id in overrides["shared"]:
                value = overrides["shared"][public_id]
                store.values_by_runtime_key[instance.runtime_key] = value
                store.shared_by_requirement[instance.node.requirement] = instance.runtime_key
                runtime.trace.append(f"override_shared:{public_id}")
                continue
            pending.append(instance)

        if pending:
            plan_nodes = _plan_nodes_for_instances(pending, store)
            runtime.start_batch(nodes=plan_nodes, store=store)
            try:
                plan.prepare(plan_nodes, runtime)
            finally:
                runtime.finish_batch()
            _validate_batch_completion(plan_nodes, store)


def _plan_nodes_for_instances(
    instances: list[RuntimeInstance],
    store: ProducedValueStore,
) -> list[PlanNode]:
    return [
        PlanNode(
            runtime_key=instance.runtime_key,
            requirement=instance.node.requirement,
            public_id=instance.node.public_id,
            test_id=instance.test_id,
            per_test=instance.per_test,
            payload=instance.node.requirement.payload,
            deps=_resolve_dependency_values(instance=instance, store=store),
        )
        for instance in instances
    ]


def _validate_batch_completion(
    nodes: list[PlanNode],
    store: ProducedValueStore,
) -> None:
    __tracebackhide__ = True
    for node in nodes:
        if node.runtime_key in store.values_by_runtime_key:
            continue
        if node.runtime_key in store.exceptions_by_runtime_key:
            continue
        raise WarmupError(
            f"plan {node.requirement.owner_plan.name!r} did not set a value or exception for node {node.runtime_key!r}"
        )


def _resolve_dependency_values(
    *,
    instance: RuntimeInstance,
    store: ProducedValueStore,
) -> dict[str, object | tuple[object, ...]]:
    resolved: dict[str, object | tuple[object, ...]] = {}
    for slot, runtime_key in instance.dependency_runtime_keys.items():
        if isinstance(runtime_key, tuple):
            resolved[slot] = tuple(
                store.value_for_runtime_key(item_key) for item_key in runtime_key
            )
            continue
        resolved[slot] = store.value_for_runtime_key(runtime_key)
    return resolved


def _topologically_sorted_plans(
    normalized_nodes: tuple[NormalizedNode, ...],
) -> list[WarmupPlan]:
    plan_dependencies: dict[WarmupPlan, set[WarmupPlan]] = defaultdict(set)
    plans: set[WarmupPlan] = set()
    node_by_key = {node.node_key: node for node in normalized_nodes}
    for node in normalized_nodes:
        plans.add(node.owner_plan)
        for dependency_key in node.dependency_keys:
            dependency_plan = node_by_key[dependency_key].owner_plan
            if dependency_plan is node.owner_plan:
                continue
            plan_dependencies[node.owner_plan].add(dependency_plan)

    ready = sorted(
        [plan for plan in plans if not plan_dependencies.get(plan)],
        key=lambda plan: plan.name,
    )
    ordered: list[WarmupPlan] = []
    remaining_dependencies = {plan: set(deps) for plan, deps in plan_dependencies.items()}

    while ready:
        plan = ready.pop(0)
        ordered.append(plan)
        for other_plan in plans:
            dependencies = remaining_dependencies.get(other_plan)
            if not dependencies or plan not in dependencies:
                continue
            dependencies.remove(plan)
            if not dependencies and other_plan not in ordered and other_plan not in ready:
                ready.append(other_plan)
                ready.sort(key=lambda candidate: candidate.name)

    if len(ordered) != len(plans):
        raise WarmupError("cross-plan dependency cycle detected")
    return ordered
