"""Private snapshot and debug-artifact helpers for pytest-warmup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Mapping
import json

import pytest

from ._errors import WarmupError

if TYPE_CHECKING:
    from .core import (
        NormalizedNode,
        ProducedValueStore,
        RuntimeContext,
        RuntimeInstance,
        SelectedRoot,
        WarmupRequirement,
    )


@dataclass
class WarmupSessionState:
    items: list[pytest.Item] = field(default_factory=list)
    snapshot_inputs: "SessionSnapshotInputs | None" = None
    snapshot_signature: tuple[Path | None, tuple[str, ...]] | None = None
    snapshot_id_owners: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotFragment:
    shared: Mapping[str, Mapping[str, object]]
    tests: Mapping[str, Mapping[str, Mapping[str, object]]]


@dataclass(frozen=True)
class SessionSnapshotInputs:
    scoped_fragments: Mapping[str, SnapshotFragment]
    targeted_fragments: Mapping[str, SnapshotFragment]


def _session_snapshot_inputs(
    config: pytest.Config,
    state: WarmupSessionState,
) -> SessionSnapshotInputs:
    __tracebackhide__ = True
    signature = _snapshot_signature(config)
    if state.snapshot_inputs is not None and state.snapshot_signature == signature:
        return state.snapshot_inputs
    scoped_path, targeted_specs = signature
    scoped_fragments: dict[str, SnapshotFragment] = {}
    if scoped_path is not None:
        scoped_fragments = _load_scoped_snapshot_bundle(scoped_path)
    targeted_fragments = _load_targeted_snapshot_fragments(targeted_specs)
    state.snapshot_inputs = SessionSnapshotInputs(
        scoped_fragments=scoped_fragments,
        targeted_fragments=targeted_fragments,
    )
    state.snapshot_signature = signature
    state.snapshot_id_owners.clear()
    return state.snapshot_inputs


def _snapshot_signature(config: pytest.Config) -> tuple[Path | None, tuple[str, ...]]:
    return (
        _optional_path(config.getoption("warmup_snapshot")),
        tuple(config.getoption("warmup_snapshot_for") or ()),
    )


def _optional_path(value: object) -> Path | None:
    if value is None:
        return None
    rendered = str(value).strip()
    if not rendered:
        return None
    return Path(rendered)


def _load_scoped_snapshot_bundle(path: Path) -> dict[str, SnapshotFragment]:
    raw = _load_json_object(path, context="snapshot file")
    version = raw.get("version")
    if version != 1:
        raise WarmupError("snapshot file field 'version' must be 1")
    allowed_keys = {"version", "scopes"}
    unexpected_keys = sorted(set(raw) - allowed_keys)
    if unexpected_keys:
        raise WarmupError(
            f"snapshot file contains unexpected top-level fields: {unexpected_keys!r}"
        )
    scopes = raw.get("scopes", {})
    if not isinstance(scopes, Mapping):
        raise WarmupError("snapshot file field 'scopes' must be a mapping")
    normalized: dict[str, SnapshotFragment] = {}
    for scope_id, value in scopes.items():
        normalized_scope_id = str(scope_id)
        if normalized_scope_id in normalized:
            raise WarmupError(f"duplicate snapshot scope id {normalized_scope_id!r}")
        normalized[normalized_scope_id] = _normalize_snapshot_fragment_mapping(
            value,
            context=f"snapshot scope {normalized_scope_id!r}",
        )
    return normalized


def _load_targeted_snapshot_fragments(
    specs: tuple[str, ...],
) -> dict[str, SnapshotFragment]:
    normalized: dict[str, SnapshotFragment] = {}
    for spec in specs:
        snapshot_id, path = _parse_snapshot_target_spec(spec)
        if snapshot_id in normalized:
            raise WarmupError(f"duplicate CLI snapshot target for snapshot_id {snapshot_id!r}")
        raw = _load_json_object(path, context=f"targeted snapshot file for {snapshot_id!r}")
        version = raw.get("version")
        if version != 1:
            raise WarmupError(
                f"targeted snapshot file for {snapshot_id!r} must set 'version' to 1"
            )
        allowed_keys = {"version", "shared", "tests"}
        unexpected_keys = sorted(set(raw) - allowed_keys)
        if unexpected_keys:
            raise WarmupError(
                f"targeted snapshot file for {snapshot_id!r} contains unexpected top-level "
                f"fields: {unexpected_keys!r}"
            )
        normalized[snapshot_id] = _normalize_snapshot_fragment_mapping(
            {key: value for key, value in raw.items() if key != "version"},
            context=f"targeted snapshot file for {snapshot_id!r}",
        )
    return normalized


def _parse_snapshot_target_spec(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise WarmupError("snapshot target must use the form '<snapshot_id>=<path>'")
    snapshot_id, raw_path = spec.split("=", 1)
    normalized_snapshot_id = snapshot_id.strip()
    normalized_path = raw_path.strip()
    if not normalized_snapshot_id:
        raise WarmupError("snapshot target is missing snapshot_id before '='")
    if not normalized_path:
        raise WarmupError("snapshot target is missing file path after '='")
    return normalized_snapshot_id, Path(normalized_path)


def _load_json_object(path: Path, *, context: str) -> Mapping[str, object]:
    __tracebackhide__ = True
    if not path.exists():
        raise WarmupError(f"{context} does not exist: {str(path)!r}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WarmupError(f"{context} {str(path)!r} is not valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise WarmupError(f"{context} content must be a JSON object")
    return raw


def _normalize_snapshot_fragment_mapping(
    fragment: object,
    *,
    context: str,
) -> SnapshotFragment:
    __tracebackhide__ = True
    if not isinstance(fragment, Mapping):
        raise WarmupError(f"{context} must be a mapping")
    allowed_keys = {"shared", "tests"}
    unexpected_keys = sorted(set(fragment) - allowed_keys)
    if unexpected_keys:
        raise WarmupError(f"{context} contains unexpected fields: {unexpected_keys!r}")
    shared = fragment.get("shared", {})
    tests = fragment.get("tests", {})
    if not isinstance(shared, Mapping):
        raise WarmupError(f"{context} field 'shared' must be a mapping")
    if not isinstance(tests, Mapping):
        raise WarmupError(f"{context} field 'tests' must be a mapping")
    normalized_shared = {
        str(public_id): _normalize_snapshot_entry(
            value,
            context=f"{context} shared entry {public_id!r}",
        )
        for public_id, value in shared.items()
    }
    normalized_tests: dict[str, dict[str, dict[str, object]]] = {}
    for test_id, values in tests.items():
        normalized_test_id = str(test_id)
        if not isinstance(values, Mapping):
            raise WarmupError(f"{context} per-test entry {normalized_test_id!r} must be a mapping")
        normalized_tests[normalized_test_id] = {
            str(public_id): _normalize_snapshot_entry(
                value,
                context=(
                    f"{context} per-test entry {normalized_test_id!r} override "
                    f"{public_id!r}"
                ),
            )
            for public_id, value in values.items()
        }
    return SnapshotFragment(
        shared=normalized_shared,
        tests=normalized_tests,
    )


def _normalize_snapshot_entry(
    entry: object,
    *,
    context: str,
) -> dict[str, object]:
    __tracebackhide__ = True
    if not isinstance(entry, Mapping):
        raise WarmupError(f"{context} must be a mapping")
    allowed_keys = {"value"}
    unexpected_keys = sorted(set(entry) - allowed_keys)
    if unexpected_keys:
        raise WarmupError(f"{context} contains unexpected fields: {unexpected_keys!r}")
    normalized: dict[str, object] = {}
    if "value" in entry:
        normalized["value"] = entry["value"]
    return normalized


def _empty_snapshot_fragment() -> SnapshotFragment:
    return SnapshotFragment(shared={}, tests={})


def _producer_scope_id(request: pytest.FixtureRequest) -> str:
    anchor = _request_scope_anchor(request)
    if anchor:
        return f"{request.scope}:{anchor}::{request.fixturename}"
    return f"{request.scope}::{request.fixturename}"


def _producer_fixture_identity(request: pytest.FixtureRequest) -> str:
    anchor = _request_scope_anchor(request) or request.scope
    return f"{anchor}::{request.fixturename}"


def _request_scope_anchor(request: pytest.FixtureRequest) -> str:
    anchor = request.node.nodeid
    if anchor:
        return anchor
    fixturedef = getattr(request, "_fixturedef", None)
    baseid = getattr(fixturedef, "baseid", "") or ""
    if baseid:
        return baseid
    node_path = getattr(request.node, "path", None)
    if node_path is not None:
        path = Path(str(node_path))
        try:
            return path.relative_to(Path(str(request.config.rootpath))).as_posix()
        except ValueError:
            return path.as_posix()
    return ""


def _resolve_snapshot_fragment(
    *,
    request: pytest.FixtureRequest,
    state: WarmupSessionState,
    snapshot_id: str | None,
) -> SnapshotFragment:
    __tracebackhide__ = True
    inputs = _session_snapshot_inputs(request.config, state)
    scope_id = _producer_scope_id(request)
    targeted_fragment: SnapshotFragment | None = None
    if snapshot_id is not None:
        owner = _producer_fixture_identity(request)
        existing_owner = state.snapshot_id_owners.get(snapshot_id)
        if existing_owner is None:
            state.snapshot_id_owners[snapshot_id] = owner
        elif existing_owner != owner:
            raise WarmupError(
                f"snapshot_id {snapshot_id!r} is already used by producer {existing_owner!r}"
            )
        targeted_fragment = inputs.targeted_fragments.get(snapshot_id)
    scoped_fragment = inputs.scoped_fragments.get(scope_id)
    if targeted_fragment is not None and scoped_fragment is not None:
        raise WarmupError(
            f"producer scope {scope_id!r} matches both --warmup-snapshot and "
            f"--warmup-snapshot-for {snapshot_id!r}"
        )
    if targeted_fragment is not None:
        return targeted_fragment
    if scoped_fragment is not None:
        return scoped_fragment
    return _empty_snapshot_fragment()


def finalize_snapshot_target_usage(
    config: pytest.Config,
    state: WarmupSessionState,
) -> str | None:
    """Return an error message when CLI-targeted snapshot ids were never used."""
    __tracebackhide__ = True
    targeted_specs = tuple(config.getoption("warmup_snapshot_for") or ())
    if not targeted_specs:
        return None
    inputs = _session_snapshot_inputs(config, state)
    unused_ids = sorted(
        snapshot_id
        for snapshot_id in inputs.targeted_fragments
        if snapshot_id not in state.snapshot_id_owners
    )
    if not unused_ids:
        return None
    rendered_ids = ", ".join(repr(snapshot_id) for snapshot_id in unused_ids)
    return (
        "unused --warmup-snapshot-for targets: "
        f"{rendered_ids}; no producer executed prepare(snapshot_id=...) "
        "with these ids in this run"
    )


def _filter_snapshot_fragment(
    *,
    normalized_nodes: tuple["NormalizedNode", ...],
    fragment: SnapshotFragment,
    selected_items: list[pytest.Item],
) -> SnapshotFragment:
    public_ids = {node.public_id for node in normalized_nodes if node.public_id is not None}
    selected_test_ids = {item.nodeid for item in selected_items}
    filtered_shared = {
        public_id: dict(entry)
        for public_id, entry in fragment.shared.items()
        if public_id in public_ids
    }
    filtered_tests: dict[str, dict[str, dict[str, object]]] = {}
    for test_id, values in fragment.tests.items():
        if test_id not in selected_test_ids:
            continue
        filtered_values = {
            public_id: dict(entry)
            for public_id, entry in values.items()
            if public_id in public_ids
        }
        if filtered_values:
            filtered_tests[test_id] = filtered_values
    return SnapshotFragment(
        shared=filtered_shared,
        tests=filtered_tests,
    )


def _validate_snapshot_fragment(
    normalized_nodes: tuple["NormalizedNode", ...],
    runtime_instances: tuple["RuntimeInstance", ...],
    fragment: SnapshotFragment,
    selected_items: list[pytest.Item],
) -> None:
    __tracebackhide__ = True
    public_ids = {node.public_id for node in normalized_nodes if node.public_id is not None}
    requirement_by_public_id = {
        node.public_id: node.requirement for node in normalized_nodes if node.public_id is not None
    }
    per_test_ids = {
        instance.node.public_id
        for instance in runtime_instances
        if instance.per_test and instance.node.public_id is not None
    }
    selected_test_ids = {item.nodeid for item in selected_items}

    for public_id, entry in fragment.shared.items():
        if public_id not in public_ids:
            raise WarmupError(f"unknown shared override id {public_id!r}")
        if public_id in per_test_ids:
            raise WarmupError(
                f"shared override {public_id!r} targets a per-test runtime node"
            )
        if "value" in entry:
            requirement_by_public_id[public_id].owner_plan.validate_snapshot_value(
                requirement_by_public_id[public_id],
                entry["value"],
            )

    for test_id, values in fragment.tests.items():
        if test_id not in selected_test_ids:
            raise WarmupError(f"unknown test id in overrides: {test_id!r}")
        for public_id, entry in values.items():
            if public_id not in public_ids:
                raise WarmupError(f"unknown per-test override id {public_id!r}")
            if "value" in entry:
                requirement_by_public_id[public_id].owner_plan.validate_snapshot_value(
                    requirement_by_public_id[public_id],
                    entry["value"],
                )


def _extract_overrides(fragment: SnapshotFragment) -> dict[str, dict[str, object]]:
    shared = {
        public_id: entry["value"]
        for public_id, entry in fragment.shared.items()
        if "value" in entry
    }
    tests: dict[str, dict[str, object]] = {}
    for test_id, values in fragment.tests.items():
        extracted_values = {
            public_id: entry["value"]
            for public_id, entry in values.items()
            if "value" in entry
        }
        if extracted_values:
            tests[test_id] = extracted_values
    return {"shared": shared, "tests": tests}


def _deserialize_overrides(
    normalized_nodes: tuple["NormalizedNode", ...],
    overrides: Mapping[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    requirement_by_public_id = {
        node.public_id: node.requirement for node in normalized_nodes if node.public_id is not None
    }
    shared: dict[str, object] = {}
    for public_id, raw_value in overrides["shared"].items():
        requirement = requirement_by_public_id[public_id]
        shared[public_id] = requirement.owner_plan.deserialize_snapshot_value(
            requirement,
            raw_value,
        )
    tests: dict[str, dict[str, object]] = {}
    for test_id, values in overrides["tests"].items():
        tests[test_id] = {}
        for public_id, raw_value in values.items():
            requirement = requirement_by_public_id[public_id]
            tests[test_id][public_id] = requirement.owner_plan.deserialize_snapshot_value(
                requirement,
                raw_value,
            )
    return {"shared": shared, "tests": tests}


def _build_snapshot_fragment_template(
    runtime_instances: tuple["RuntimeInstance", ...],
) -> dict[str, object]:
    shared: dict[str, dict[str, object]] = {}
    tests: dict[str, dict[str, dict[str, object]]] = {}
    for instance in runtime_instances:
        public_id = instance.node.public_id
        if public_id is None:
            continue
        if instance.per_test:
            test_id = instance.test_id or ""
            tests.setdefault(test_id, {})[public_id] = {}
            continue
        shared[public_id] = {}
    return {
        "shared": dict(sorted(shared.items())),
        "tests": {test_id: dict(sorted(values.items())) for test_id, values in sorted(tests.items())},
    }


def _build_saved_snapshot_fragment(
    *,
    normalized_nodes: tuple["NormalizedNode", ...],
    runtime_instances: tuple["RuntimeInstance", ...],
    store: "ProducedValueStore",
) -> dict[str, object]:
    fragment = _build_snapshot_fragment_template(runtime_instances)
    for node in normalized_nodes:
        if node.public_id is None:
            continue
        runtime_key = store.shared_by_requirement.get(node.requirement)
        if runtime_key is None:
            continue
        if runtime_key in store.exceptions_by_runtime_key:
            continue
        fragment["shared"][node.public_id]["value"] = node.owner_plan.serialize_snapshot_value(
            node.requirement,
            store.values_by_runtime_key[runtime_key],
        )
    for (requirement, test_id), runtime_key in sorted(store.per_test_by_requirement.items()):
        if runtime_key in store.exceptions_by_runtime_key:
            continue
        if requirement.id is None:
            continue
        fragment["tests"].setdefault(test_id, {}).setdefault(requirement.id, {})["value"] = requirement.owner_plan.serialize_snapshot_value(
            requirement,
            store.values_by_runtime_key[runtime_key],
        )
    return fragment


def _build_scoped_snapshot_document(
    *,
    scope_id: str,
    fragment: Mapping[str, object],
) -> dict[str, object]:
    return {
        "version": 1,
        "scopes": {
            scope_id: _json_friendly(dict(fragment)),
        },
    }


def _build_preparation_report(
    *,
    scope_id: str,
    runtime: "RuntimeContext",
    selected_roots: list["SelectedRoot"],
    normalized_nodes: tuple["NormalizedNode", ...],
    runtime_instances: tuple["RuntimeInstance", ...],
    effective_per_test: Mapping["WarmupRequirement", bool],
    raw_overrides: Mapping[str, dict[str, object]],
    store: "ProducedValueStore",
    status: str,
    error: BaseException | None,
) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "status": status,
        "producer_scope": runtime.producer_scope,
        "selected_test_ids": list(runtime.selected_test_ids),
        "selected_roots": [
            {
                "consumer_id": root.consumer_id,
                "source_kind": root.source_kind,
                "source_name": root.source_name,
                "argument_name": root.binding.argument_name,
                "plan": root.binding.requirement.owner_plan.name,
                "public_id": root.binding.requirement.id,
                "producer_fixture": root.binding.producer_fixture,
            }
            for root in selected_roots
        ],
        "normalized_nodes": [
            {
                "node_key": node.node_key,
                "plan": node.owner_plan.name,
                "public_id": node.public_id,
                "payload": _json_friendly(dict(node.requirement.payload)),
                "dependency_keys": list(node.dependency_keys),
                "declared_per_test": node.requirement.is_per_test,
                "effective_per_test": effective_per_test[node.requirement],
            }
            for node in normalized_nodes
        ],
        "runtime_instances": [
            {
                "runtime_key": instance.runtime_key,
                "node_key": instance.node.node_key,
                "plan": instance.node.owner_plan.name,
                "public_id": instance.node.public_id,
                "test_id": instance.test_id,
                "per_test": instance.per_test,
                "dependency_runtime_keys": {
                    key: list(value) if isinstance(value, tuple) else value
                    for key, value in instance.dependency_runtime_keys.items()
                },
                "status": _runtime_instance_status(instance, store),
            }
            for instance in runtime_instances
        ],
        "overrides": {
            "shared": _json_friendly(dict(raw_overrides["shared"])),
            "tests": _json_friendly(
                {test_id: dict(values) for test_id, values in raw_overrides["tests"].items()}
            ),
        },
        "batch_reports": list(runtime.batch_reports),
        "trace": list(runtime.trace),
        "error": _error_metadata(error) if error is not None else None,
    }


def _runtime_instance_status(
    instance: "RuntimeInstance",
    store: "ProducedValueStore",
) -> str:
    runtime_key = instance.runtime_key
    if runtime_key in store.exceptions_by_runtime_key:
        return "exception"
    if runtime_key in store.values_by_runtime_key:
        return "value"
    return "pending"


def _error_metadata(error: BaseException) -> dict[str, str]:
    return {
        "type": error.__class__.__name__,
        "message": str(error),
    }


def _write_json_file(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _best_effort_write_json_file(path: Path, payload: object) -> None:
    try:
        _write_json_file(path, payload)
    except Exception:
        return


def _merge_scoped_document_file(
    path: Path,
    *,
    scope_id: str,
    fragment: Mapping[str, object],
) -> None:
    scopes = _read_existing_scoped_document_sections(path)
    scopes[scope_id] = _json_friendly(dict(fragment))
    _write_json_file(
        path,
        {
            "version": 1,
            "scopes": dict(sorted(scopes.items())),
        },
    )


def _best_effort_merge_scoped_document_file(
    path: Path,
    *,
    scope_id: str,
    fragment: Mapping[str, object],
) -> None:
    try:
        _merge_scoped_document_file(path, scope_id=scope_id, fragment=fragment)
    except Exception:
        return


def _read_existing_scoped_document_sections(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = _load_json_object(path, context="debug artifact file")
    version = raw.get("version")
    if version != 1:
        raise WarmupError("debug artifact file field 'version' must be 1")
    scopes = raw.get("scopes", {})
    if not isinstance(scopes, Mapping):
        raise WarmupError("debug artifact file field 'scopes' must be a mapping")
    normalized: dict[str, object] = {}
    for scope_id, fragment in scopes.items():
        if not isinstance(fragment, Mapping):
            raise WarmupError(f"debug artifact scope {scope_id!r} must be a mapping")
        normalized[str(scope_id)] = _json_friendly(dict(fragment))
    return normalized


def _safe_build_saved_snapshot(
    *,
    scope_id: str,
    normalized_nodes: tuple["NormalizedNode", ...],
    runtime_instances: tuple["RuntimeInstance", ...],
    store: "ProducedValueStore",
    runtime: "RuntimeContext",
    error: BaseException,
) -> dict[str, object]:
    del runtime, error
    try:
        return _build_scoped_snapshot_document(
            scope_id=scope_id,
            fragment=_build_saved_snapshot_fragment(
                normalized_nodes=normalized_nodes,
                runtime_instances=runtime_instances,
                store=store,
            ),
        )
    except Exception:
        return _build_scoped_snapshot_document(
            scope_id=scope_id,
            fragment=_build_snapshot_fragment_template(runtime_instances),
        )


def _safe_build_failure_report(
    *,
    scope_id: str,
    runtime: "RuntimeContext",
    selected_roots: list["SelectedRoot"],
    normalized_nodes: tuple["NormalizedNode", ...],
    runtime_instances: tuple["RuntimeInstance", ...],
    effective_per_test: Mapping["WarmupRequirement", bool],
    raw_overrides: Mapping[str, dict[str, object]],
    store: "ProducedValueStore",
    error: BaseException,
) -> dict[str, object]:
    try:
        return _build_preparation_report(
            scope_id=scope_id,
            runtime=runtime,
            selected_roots=selected_roots,
            normalized_nodes=normalized_nodes,
            runtime_instances=runtime_instances,
            effective_per_test=effective_per_test,
            raw_overrides=raw_overrides,
            store=store,
            status="failed",
            error=error,
        )
    except Exception as report_error:
        return {
            "scope_id": scope_id,
            "status": "failed",
            "producer_scope": runtime.producer_scope,
            "selected_test_ids": list(runtime.selected_test_ids),
            "error": _error_metadata(error),
            "report_error": _error_metadata(report_error),
            "trace": list(runtime.trace),
        }


def _json_friendly(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_friendly(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_friendly(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value
