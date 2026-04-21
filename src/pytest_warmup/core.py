"""Core declaration, preparation, and injection primitives for pytest-warmup."""

from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from inspect import Parameter, Signature, isgeneratorfunction, signature
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable, Mapping
import functools
import json

import pytest

from ._errors import WarmupError
from ._snapshot import (
    WarmupSessionState,
    _best_effort_merge_scoped_document_file,
    _build_preparation_report,
    _build_snapshot_fragment_template,
    _deserialize_overrides,
    _extract_overrides,
    _filter_snapshot_fragment,
    _merge_scoped_document_file,
    _producer_scope_id,
    _resolve_snapshot_fragment,
    _safe_build_failure_report,
    _safe_build_saved_snapshot,
    _validate_snapshot_fragment,
)

WARMUP_BINDING_ATTR = "__warmup_binding__"
WARMUP_BINDINGS_ATTR = "__warmup_bindings__"
WARMUP_BASE_CALLABLE_ATTR = "__warmup_base_callable__"
WARMUP_BASE_SIGNATURE_ATTR = "__warmup_base_signature__"
CURRENT_FIXTURE_REQUEST: ContextVar[pytest.FixtureRequest | None] = ContextVar(
    "warmup_current_fixture_request",
    default=None,
)


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
    """Base class for domain-specific plans that declare and prepare resources.

    Subclasses usually override `prepare_node(...)` for simple one-node-at-a-time
    materialization. The default `prepare(...)` method provides the public
    lifecycle skeleton:

    1. call `before_prepare(nodes)` once for the current batch;
    2. call `prepare_node(node)` for each node and store the returned value;
    3. call `after_prepare(nodes)` once after node preparation.

    Override `prepare(nodes)` directly only when the plan needs custom batch
    orchestration. In that case, each node must be completed with
    `node.set_value(...)` or `node.set_exception(...)`.
    """

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

    def before_prepare(self, nodes: list["WarmupNode"]) -> None:
        """Run once before this plan prepares its current batch.

        `nodes` contains only selected requirements owned by this plan and not
        already satisfied by snapshot values. If `before_prepare(...)` raises, the default
        `prepare(...)` records that exception on every node in the batch and
        skips both `prepare_node(...)` and `after_prepare(...)`.
        """
        del nodes

    def prepare_node(self, node: "WarmupNode") -> object:
        """Materialize one node and return the value injected into tests.

        This is the main extension point for ordinary plans. The default
        `prepare(...)` stores the returned value with `node.set_value(...)`.
        If this method raises, the exception is recorded only on this node and
        remaining nodes continue to prepare.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement prepare_node(...) or prepare(...)"
        )

    def after_prepare(self, nodes: list["WarmupNode"]) -> None:
        """Run once after this plan has attempted to prepare every node.

        This is prepare-phase finalization, not pytest fixture teardown after
        tests finish. It is useful for actions such as forcing synchronization
        or resetting caches after a batch is created. If `after_prepare(...)` raises,
        the default `prepare(...)` records that exception on nodes that currently
        have prepared values, while preserving earlier per-node exceptions.
        """
        del nodes

    def prepare(self, nodes: list["WarmupNode"]) -> None:
        """Prepare a batch of plan-owned nodes.

        The default implementation exposes the standard lifecycle skeleton:
        `before_prepare(nodes)`, `prepare_node(node)` for every node, then
        `after_prepare(nodes)`. Override this method for custom batch orchestration;
        overridden implementations are responsible for completing every node via
        `node.set_value(...)` or `node.set_exception(...)`.
        """
        try:
            self.before_prepare(nodes)
        except Exception as exc:
            for node in nodes:
                node.set_exception(exc)
            return

        for node in nodes:
            try:
                node.set_value(self.prepare_node(node))
            except Exception as exc:
                node.set_exception(exc)

        try:
            self.after_prepare(nodes)
        except Exception as exc:
            for node in nodes:
                if node.has_value:
                    node.set_exception(exc)

    def validate_snapshot_value(
        self,
        requirement: WarmupRequirement,
        raw: object,
    ) -> None:
        """Validate one JSON snapshot value before it is used as an override."""
        del requirement
        _require_json_serializable(raw, context="snapshot value")

    def deserialize_snapshot_value(
        self,
        requirement: WarmupRequirement,
        raw: object,
    ) -> object:
        """Convert one JSON snapshot value into the runtime value used by tests."""
        self.validate_snapshot_value(requirement, raw)
        return raw

    def serialize_snapshot_value(
        self,
        requirement: WarmupRequirement,
        value: object,
    ) -> object:
        """Convert one prepared runtime value into a JSON-safe snapshot payload."""
        del requirement
        _require_json_serializable(value, context="prepared runtime value")
        return value


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


@dataclass
class WarmupNode:
    """One selected resource instance passed to `WarmupPlan` lifecycle hooks.

    `payload` contains plain declaration data from `WarmupPlan.require(...)`.
    `deps` contains already materialized dependency values. A plan must complete
    each node by calling `set_value(...)` or `set_exception(...)` when it
    overrides `WarmupPlan.prepare(...)` directly.
    """

    _runtime_key: str = field(repr=False)
    _requirement: WarmupRequirement = field(repr=False)
    _public_id: str | None = field(repr=False)
    _test_id: str | None = field(repr=False)
    _per_test: bool = field(repr=False)
    payload: Mapping[str, object]
    deps: Mapping[str, object | tuple[object, ...]]
    _runtime: "RuntimeContext | None" = field(default=None, init=False, repr=False)

    @property
    def id(self) -> str | None:
        """Public debug id declared by `WarmupPlan.require(id=...)`, if any."""
        return self._public_id

    @property
    def test_id(self) -> str | None:
        """Collected pytest test nodeid for per-test nodes, otherwise `None`."""
        return self._test_id

    @property
    def is_per_test(self) -> bool:
        """Whether this runtime node is materialized separately per test."""
        return self._per_test

    @property
    def has_value(self) -> bool:
        """Whether this node currently has a prepared value."""
        return self._require_runtime().has_value(self)

    @property
    def has_exception(self) -> bool:
        """Whether this node currently has a recorded preparation exception."""
        return self._require_runtime().has_exception(self)

    @property
    def is_resolved(self) -> bool:
        """Whether this node has either a value or an exception."""
        return self.has_value or self.has_exception

    def set_value(self, value: object) -> None:
        """Record the value that should be injected for this node."""
        self._require_runtime().set_value(self, value)

    def set_exception(self, exc: BaseException) -> None:
        """Record the exception that should be raised when this node is used."""
        self._require_runtime().set_exception(self, exc)

    def _attach_runtime(self, runtime: "RuntimeContext") -> None:
        self._runtime = runtime

    def _detach_runtime(self, runtime: "RuntimeContext") -> None:
        if self._runtime is runtime:
            self._runtime = None

    def _require_runtime(self) -> "RuntimeContext":
        if self._runtime is None:
            raise WarmupError(
                "warmup node values may only be set during active plan.prepare(...)"
            )
        return self._runtime


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
    batch_reports: list[dict[str, object]] = field(default_factory=list)
    _store: ProducedValueStore | None = field(default=None, init=False, repr=False)
    _active_batch: dict[str, WarmupNode] = field(default_factory=dict, init=False, repr=False)

    def start_batch(
        self,
        *,
        nodes: list[WarmupNode],
        store: ProducedValueStore,
    ) -> None:
        self._store = store
        self._active_batch = {node._runtime_key: node for node in nodes}
        for node in nodes:
            node._attach_runtime(self)

    def finish_batch(self) -> None:
        for node in self._active_batch.values():
            node._detach_runtime(self)
        self._active_batch = {}
        self._store = None

    def has_value(self, node: WarmupNode) -> bool:
        store = self._require_active_store()
        self._require_active_node(node)
        return node._runtime_key in store.values_by_runtime_key

    def has_exception(self, node: WarmupNode) -> bool:
        store = self._require_active_store()
        self._require_active_node(node)
        return node._runtime_key in store.exceptions_by_runtime_key

    def set_value(self, node: WarmupNode, value: object) -> None:
        store = self._require_active_store()
        self._require_active_node(node)
        store.values_by_runtime_key[node._runtime_key] = value
        store.exceptions_by_runtime_key.pop(node._runtime_key, None)
        if node._per_test:
            store.per_test_by_requirement[
                (node._requirement, node._test_id or "")
            ] = node._runtime_key
        else:
            store.shared_by_requirement[node._requirement] = node._runtime_key

    def set_exception(self, node: WarmupNode, exc: BaseException) -> None:
        store = self._require_active_store()
        self._require_active_node(node)
        store.exceptions_by_runtime_key[node._runtime_key] = exc
        store.values_by_runtime_key.pop(node._runtime_key, None)
        if node._per_test:
            store.per_test_by_requirement[
                (node._requirement, node._test_id or "")
            ] = node._runtime_key
        else:
            store.shared_by_requirement[node._requirement] = node._runtime_key
        self.trace.append(f"exception:{node._runtime_key}:{exc.__class__.__name__}")

    def _require_active_store(self) -> ProducedValueStore:
        if self._store is None:
            raise WarmupError(
                "warmup node values may only be set during active plan.prepare(...)"
            )
        return self._store

    def _require_active_node(self, node: WarmupNode) -> None:
        if node._runtime_key not in self._active_batch:
            raise WarmupError(
                "runtime operation targets unknown node "
                f"{node._runtime_key!r} outside active batch"
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
    dependency chain, and otherwise fails fast.
    """
    if not isinstance(requirement, WarmupRequirement):
        raise TypeError("warmup_param binding requires a WarmupRequirement")

    binding = WarmupBinding(
        argument_name=argument_name,
        requirement=requirement,
        producer_fixture=producer_fixture,
    )

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        callable_name = getattr(func, "__name__", repr(func))
        base_callable = getattr(func, WARMUP_BASE_CALLABLE_ATTR, func)
        base_signature = getattr(func, WARMUP_BASE_SIGNATURE_ATTR, signature(base_callable))
        existing_bindings = _warmup_bindings_for_callable(func)
        bindings = _normalize_bindings(
            existing_bindings=existing_bindings,
            new_binding=binding,
            callable_name=callable_name,
            base_signature=base_signature,
        )
        resolved_producer_fixture = _select_binding_producer_fixture(bindings, callable_name)
        visible_signature = _build_visible_signature(base_signature, bindings)
        base_callable_expects_request = "request" in base_signature.parameters

        def _inject_bound_arguments(
            *,
            request: pytest.FixtureRequest,
            provided_values: Iterable[object],
        ) -> dict[str, object]:
            for current_binding in bindings:
                _validate_no_fixture_name_collision(
                    request=request,
                    argument_name=current_binding.argument_name,
                )
            prepared_scope = _locate_prepared_scope(
                request,
                provided_values,
                producer_fixture=resolved_producer_fixture,
            )
            return {
                current_binding.argument_name: prepared_scope.value_for(
                    test_id=request.node.nodeid,
                    requirement=current_binding.requirement,
                )
                for current_binding in bindings
            }

        if isgeneratorfunction(base_callable):

            @functools.wraps(func)
            def wrapped(*args: object, **kwargs: object) -> object:
                request = kwargs.pop("request")
                kwargs.update(
                    _inject_bound_arguments(
                        request=request,
                        provided_values=kwargs.values(),
                    )
                )
                if base_callable_expects_request:
                    kwargs["request"] = request
                yield from base_callable(*args, **kwargs)

        else:

            @functools.wraps(func)
            def wrapped(*args: object, **kwargs: object) -> object:
                request = kwargs.pop("request")
                kwargs.update(
                    _inject_bound_arguments(
                        request=request,
                        provided_values=kwargs.values(),
                    )
                )
                if base_callable_expects_request:
                    kwargs["request"] = request
                return base_callable(*args, **kwargs)

        setattr(wrapped, WARMUP_BINDINGS_ATTR, bindings)
        setattr(wrapped, WARMUP_BASE_CALLABLE_ATTR, base_callable)
        setattr(wrapped, WARMUP_BASE_SIGNATURE_ATTR, base_signature)
        if len(bindings) == 1:
            setattr(wrapped, WARMUP_BINDING_ATTR, bindings[0])
        elif hasattr(wrapped, WARMUP_BINDING_ATTR):
            delattr(wrapped, WARMUP_BINDING_ATTR)
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
            require_in_chain=True,
        )
        return named_scope

    if len(found) == 1:
        return found[0]

    for fixture_name in request.fixturenames:
        if fixture_name in {"request", getattr(request, "fixturename", None)}:
            continue
        value = request.getfixturevalue(fixture_name)
        if isinstance(value, PreparedScope):
            found.append(value)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise WarmupError("multiple producer fixtures found in pytest dependency chain")

    raise WarmupError("no producer fixture found in pytest dependency chain")


def _resolve_named_producer_fixture(
    request: pytest.FixtureRequest,
    fixture_name: str,
    *,
    require_in_chain: bool,
) -> PreparedScope:
    fixturedefs = request._fixturemanager.getfixturedefs(fixture_name, request.node)
    if not fixturedefs:
        all_fixturedefs = getattr(request._fixturemanager, "_arg2fixturedefs", {}).get(
            fixture_name
        )
        if all_fixturedefs:
            raise WarmupError(
                f"producer fixture {fixture_name!r} is defined but not available for this pytest request scope"
            )
        raise WarmupError(f"producer fixture {fixture_name!r} was not found")
    if require_in_chain and fixture_name not in request.fixturenames:
        raise WarmupError(f"producer fixture {fixture_name!r} is not in this dependency chain")
    value = request.getfixturevalue(fixture_name)
    if not isinstance(value, PreparedScope):
        raise WarmupError(
            f"producer fixture {fixture_name!r} must return a prepared warmup scope"
        )
    return value

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

    def prepare(self, *, snapshot_id: str | None = None) -> PreparedScope:
        """Prepare the selected warmup graph for the current producer scope."""
        __tracebackhide__ = True
        options = _resolve_prepare_options(self._request.config)
        selected_items = _selected_items_for_scope(self._request, self._state.items)
        selected_roots = _collect_selected_roots(
            selected_items,
            set(self._plans),
            active_producer_fixture=self._request.fixturename,
        )
        normalized_nodes = _normalize_requirements(selected_roots)
        _validate_ids(normalized_nodes)
        effective_per_test = _effective_per_test_modes(normalized_nodes)
        runtime_instances = _build_runtime_instances(
            normalized_nodes,
            selected_roots,
            effective_per_test,
        )
        runtime = RuntimeContext(
            producer_scope=self._request.scope,
            selected_test_ids=tuple(item.nodeid for item in selected_items),
        )
        store = ProducedValueStore()
        scope_id = _producer_scope_id(self._request)
        if options.export_template_file is not None:
            _merge_scoped_document_file(
                options.export_template_file,
                scope_id=scope_id,
                fragment=_build_snapshot_fragment_template(runtime_instances),
            )

        fragment = _resolve_snapshot_fragment(
            request=self._request,
            state=self._state,
            snapshot_id=snapshot_id,
        )
        applicable_fragment = _filter_snapshot_fragment(
            normalized_nodes=normalized_nodes,
            fragment=fragment,
            selected_items=selected_items,
        )
        raw_overrides: dict[str, dict[str, object]] = {"shared": {}, "tests": {}}
        status = "prepared"
        error: BaseException | None = None
        try:
            _validate_snapshot_fragment(
                normalized_nodes,
                runtime_instances,
                applicable_fragment,
                selected_items,
            )
            raw_overrides = _extract_overrides(applicable_fragment)
            overrides = _deserialize_overrides(normalized_nodes, raw_overrides)
            _materialize(
                runtime_instances=runtime_instances,
                normalized_nodes=normalized_nodes,
                store=store,
                runtime=runtime,
                overrides=overrides,
            )
        except BaseException as exc:
            status = "failed"
            error = exc
            if options.save_on_fail_file is not None:
                save_on_fail_payload = _safe_build_saved_snapshot(
                    scope_id=scope_id,
                    normalized_nodes=normalized_nodes,
                    runtime_instances=runtime_instances,
                    store=store,
                    runtime=runtime,
                    error=exc,
                )
                _best_effort_merge_scoped_document_file(
                    options.save_on_fail_file,
                    scope_id=scope_id,
                    fragment=save_on_fail_payload["scopes"][scope_id],
                )
            if options.report_file is not None:
                report_payload = _safe_build_failure_report(
                    scope_id=scope_id,
                    runtime=runtime,
                    selected_roots=selected_roots,
                    normalized_nodes=normalized_nodes,
                    runtime_instances=runtime_instances,
                    effective_per_test=effective_per_test,
                    raw_overrides=raw_overrides,
                    store=store,
                    error=exc,
                )
                _best_effort_merge_scoped_document_file(
                    options.report_file,
                    scope_id=scope_id,
                fragment=report_payload,
                )
            raise

        if options.report_file is not None:
            _merge_scoped_document_file(
                options.report_file,
                scope_id=scope_id,
                fragment=_build_preparation_report(
                    scope_id=scope_id,
                    runtime=runtime,
                    selected_roots=selected_roots,
                    normalized_nodes=normalized_nodes,
                    runtime_instances=runtime_instances,
                    effective_per_test=effective_per_test,
                    raw_overrides=raw_overrides,
                    store=store,
                    status=status,
                    error=error,
                ),
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

    if scope == "package":
        package_path = getattr(request.node, "path", None)
        if package_path is None:
            raise WarmupError("package-scoped producer is missing package path information")
        package_path = Path(str(package_path))
        return [
            item
            for item in items
            if _path_is_within(Path(str(item.path)), package_path)
        ]

    raise WarmupError(f"unsupported producer scope {scope!r}")


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _collect_selected_roots(
    items: list[pytest.Item],
    allowed_plans: set[WarmupPlan],
    *,
    active_producer_fixture: str | None = None,
) -> list[SelectedRoot]:
    collected: list[SelectedRoot] = []
    for item in items:
        for test_binding in _warmup_bindings_for_callable(item.obj):
            if test_binding.requirement.owner_plan not in allowed_plans:
                continue
            if not _binding_matches_prepare_producer(
                test_binding,
                active_producer_fixture=active_producer_fixture,
            ):
                continue
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
            for fixture_binding in _warmup_bindings_for_callable(func):
                if fixture_binding.requirement.owner_plan not in allowed_plans:
                    continue
                if not _binding_matches_prepare_producer(
                    fixture_binding,
                    active_producer_fixture=active_producer_fixture,
                ):
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


def _binding_matches_prepare_producer(
    binding: WarmupBinding,
    *,
    active_producer_fixture: str | None,
) -> bool:
    if active_producer_fixture is None:
        return True
    if binding.producer_fixture is None:
        return True
    return binding.producer_fixture == active_producer_fixture


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
                f"duplicate id {node.public_id!r} within one producer scope; "
                "if this should be the same resource, import and reuse the same "
                "WarmupRequirement object instead of redeclaring it"
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
            plan_nodes = _warmup_nodes_for_instances(pending, store)
            runtime.start_batch(nodes=plan_nodes, store=store)
            started_at = perf_counter()
            try:
                plan.prepare(plan_nodes)
            finally:
                runtime.finish_batch()
            runtime.batch_reports.append(
                {
                    "plan": plan.name,
                    "node_count": len(plan_nodes),
                    "runtime_keys": [node._runtime_key for node in plan_nodes],
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                }
            )
            _validate_batch_completion(plan_nodes, store)


def _warmup_nodes_for_instances(
    instances: list[RuntimeInstance],
    store: ProducedValueStore,
) -> list[WarmupNode]:
    return [
        WarmupNode(
            _runtime_key=instance.runtime_key,
            _requirement=instance.node.requirement,
            _public_id=instance.node.public_id,
            _test_id=instance.test_id,
            _per_test=instance.per_test,
            payload=instance.node.requirement.payload,
            deps=_resolve_dependency_values(instance=instance, store=store),
        )
        for instance in instances
    ]


def _validate_batch_completion(
    nodes: list[WarmupNode],
    store: ProducedValueStore,
) -> None:
    __tracebackhide__ = True
    for node in nodes:
        if node._runtime_key in store.values_by_runtime_key:
            continue
        if node._runtime_key in store.exceptions_by_runtime_key:
            continue
        raise WarmupError(
            f"plan {node._requirement.owner_plan.name!r} did not set a value "
            f"or exception for node {node._runtime_key!r}"
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


@dataclass(frozen=True)
class WarmupPrepareOptions:
    report_file: Path | None
    export_template_file: Path | None
    save_on_fail_file: Path | None


def _resolve_prepare_options(config: pytest.Config) -> WarmupPrepareOptions:
    _debug_artifacts_require_single_process(config)
    return WarmupPrepareOptions(
        report_file=_optional_path(config.getoption("warmup_report")),
        export_template_file=_optional_path(config.getoption("warmup_export_template")),
        save_on_fail_file=_optional_path(config.getoption("warmup_save_on_fail")),
    )


def _optional_path(value: object) -> Path | None:
    if value in {None, ""}:
        return None
    return Path(str(value))


def _debug_artifacts_require_single_process(config: pytest.Config) -> None:
    if not _xdist_enabled(config):
        return
    if any(
        _optional_path(value) is not None
        for value in (
            config.getoption("warmup_export_template"),
            config.getoption("warmup_report"),
            config.getoption("warmup_save_on_fail"),
        )
    ):
        raise WarmupError(
            "debug artifact outputs are not supported when pytest-xdist is active; "
            "disable --warmup-export-template/--warmup-report/--warmup-save-on-fail "
            "or run without xdist"
        )


def _xdist_enabled(config: pytest.Config) -> bool:
    if hasattr(config, "workerinput"):
        return True
    numprocesses = getattr(getattr(config, "option", None), "numprocesses", 0)
    try:
        return int(numprocesses or 0) > 0
    except (TypeError, ValueError):
        return False


def _warmup_bindings_for_callable(func: object) -> tuple[WarmupBinding, ...]:
    bindings = getattr(func, WARMUP_BINDINGS_ATTR, None)
    if bindings is not None:
        return tuple(bindings)
    binding = getattr(func, WARMUP_BINDING_ATTR, None)
    if binding is None:
        return ()
    return (binding,)


def _normalize_bindings(
    *,
    existing_bindings: tuple[WarmupBinding, ...],
    new_binding: WarmupBinding,
    callable_name: str,
    base_signature: Signature,
) -> tuple[WarmupBinding, ...]:
    existing_argument_names = {binding.argument_name for binding in existing_bindings}
    if new_binding.argument_name in existing_argument_names:
        raise WarmupError(
            f"warmup_param argument {new_binding.argument_name!r} is already bound on "
            f"callable {callable_name!r}"
        )
    if new_binding.argument_name not in base_signature.parameters:
        raise WarmupError(
            f"warmup_param argument {new_binding.argument_name!r} is missing from callable "
            f"{callable_name!r}"
        )
    return (*existing_bindings, new_binding)


def _select_binding_producer_fixture(
    bindings: tuple[WarmupBinding, ...],
    callable_name: str,
) -> str | None:
    explicit_fixture_names = {
        binding.producer_fixture
        for binding in bindings
        if binding.producer_fixture is not None
    }
    if len(explicit_fixture_names) > 1:
        raise WarmupError(
            f"warmup_param bindings on callable {callable_name!r} must agree on "
            "producer_fixture when one is specified"
        )
    if explicit_fixture_names:
        return next(iter(explicit_fixture_names))
    return None


def _build_visible_signature(
    base_signature: Signature,
    bindings: tuple[WarmupBinding, ...],
) -> Signature:
    bound_argument_names = {binding.argument_name for binding in bindings}
    visible_parameters = [
        parameter
        for name, parameter in base_signature.parameters.items()
        if name not in bound_argument_names
    ]
    if "request" not in base_signature.parameters:
        visible_parameters.append(
            Parameter(
                "request",
                kind=Parameter.KEYWORD_ONLY,
            )
        )
    return Signature(parameters=visible_parameters)


def _require_json_serializable(value: object, *, context: str) -> None:
    try:
        json.dumps(value)
    except TypeError as exc:
        raise WarmupError(f"{context} is not JSON-serializable") from exc
