# pytest-warmup

`pytest-warmup` is a pytest plugin for batch preparation and distribution of expensive test resources.

Use it when ordinary fixture-by-fixture setup becomes too slow or too hard to reason about because objects are expensive to create, depend on one another, or require extra orchestration after creation.

Typical cases:

- creating external-domain objects in batches before a module or session runs;
- waiting for synchronization, indexing, or propagation after creation;
- reusing one prepared upstream object across multiple tests;
- creating per-test instances only where the declaration explicitly asks for it;
- replacing selected prepared values from a snapshot file for debugging;
- exporting the selected warmup graph into a snapshot template or report.

## Installation

```bash
pip install pytest-warmup
```

## Public API

This package is intentionally narrow:

- `WarmupPlan`
- `WarmupNode`
- `WarmupRequirement`
- `WarmupError`
- `@warmup_param(...)`
- `warmup_mgr.use(...).prepare(...)`

## Quick Start

Declare resource requirements in plan classes:

```python
from pytest_warmup import WarmupNode, WarmupPlan, WarmupRequirement


class ProfilePlan(WarmupPlan):
    def require(
        self,
        *,
        profile_name: str,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"profile_name": profile_name},
            dependencies={},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare_node(self, node: WarmupNode) -> dict[str, object]:
        return {
            "profile_id": f"profile-{node.payload['profile_name']}",
            "profile_name": node.payload["profile_name"],
        }
```

Build requirements from those plans:

```python
profile = ProfilePlan("profile")
profile_main = profile.require(profile_name="main", id="profile_main")
```

Create one explicit producer fixture. Producer fixtures may use pytest's
`session`, `package`, `module`, `class`, or `function` scopes:

```python
import pytest


@pytest.fixture(scope="module")
def prepare_data(warmup_mgr):
    return warmup_mgr.use(profile).prepare()
```

Inject the prepared resource into a test or fixture:

```python
from pytest_warmup import warmup_param


@warmup_param("prepared_profile", profile_main)
def test_profile(prepare_data, prepared_profile):
    assert prepared_profile["profile_id"].startswith("profile-")
```

Multiple `@warmup_param(...)` bindings on one callable are supported when they all resolve through the same producer path:

```python
@warmup_param("prepared_program", program_main)
@warmup_param("prepared_products", products_alpha)
def test_profile(prepare_data, prepared_program, prepared_products):
    assert prepared_products["program_id"] == prepared_program["program_id"]
```

`is_per_test=True` on a requirement means that requirement is materialized separately for each collected test item. If omitted, the requirement inherits per-test behavior from upstream dependencies, otherwise it stays shared within the producer scope.

## Plan Lifecycle

For ordinary plans, implement `prepare_node(...)` and return the prepared value:

```python
class ProgramPlan(WarmupPlan):
    def prepare_node(self, node: WarmupNode) -> Program:
        facility = node.deps["facility"]
        return create_program(facility=facility, name=node.payload["name"])
```

`WarmupPlan.prepare(...)` provides the default lifecycle:

1. `before_prepare(nodes)` runs once before the batch; if it raises, every node in the batch receives that exception.
2. `prepare_node(node)` runs for each node; if it raises, only that node receives the exception.
3. `after_prepare(nodes)` runs once after node preparation; if it raises, nodes that currently have prepared values receive that exception.

`after_prepare(...)` is prepare-phase finalization, not pytest fixture teardown after tests finish. Use it for actions such as forcing synchronization or resetting caches before tests consume prepared values.

Override `prepare(nodes)` directly when the plan needs custom batch orchestration. In that mode, complete every node explicitly:

```python
class OrderPlan(WarmupPlan):
    def prepare(self, nodes: list[WarmupNode]) -> None:
        for node in nodes:
            try:
                value = create_order(inventory=node.deps["inventory"])
                node.set_value(value)
            except Exception as exc:
                node.set_exception(exc)
```

Migration note: older prototypes used `prepare(nodes, runtime)` and
`runtime.set(...)`. The public extension API is now `prepare_node(node)` for
ordinary plans, or `prepare(nodes)` with `node.set_value(...)` /
`node.set_exception(...)` for custom batch plans.

For full runnable examples, see:

- [`examples/basic_usage.py`](examples/basic_usage.py) for the smallest explicit producer/test flow
- [`examples/fixture_binding_usage.py`](examples/fixture_binding_usage.py) for fixture-side binding plus targeted snapshot override
- [`examples/named_producer_usage.py`](examples/named_producer_usage.py)

## Requirement Identity And Reuse

`pytest-warmup` keeps requirement identity explicit:

- one declaration object means one logical requirement node;
- importing and reusing the same `WarmupRequirement` object means the same resource;
- calling `require(...)` again creates a different declaration, even if the payload is identical;
- public `id` values are addressable debug keys for overrides and diagnostics, not merge keys.

If two tests should share the same resource, declare it once and import that same requirement object where needed. Do not try to make two separate declarations collapse through a merge key or through matching payloads.

If you hit a duplicate-id error and the intent was reuse, the fix is to import the already-declared `WarmupRequirement` object instead of redeclaring it.

## Producer Patterns

The default model stays explicit: a test or fixture depends on a producer fixture in the ordinary pytest dependency chain.

Recommended order:

1. use an explicit producer argument for the default, most readable path;
2. use `producer_fixture="..."` only to disambiguate between producers that are already present in the pytest dependency chain.

Producer resolution rules:

1. if `producer_fixture="..."` is provided, that fixture must already be part of the pytest dependency chain and is used as the producer;
2. otherwise, if the dependency chain already contains exactly one prepared producer, that producer is used;
3. otherwise, producer resolution fails fast.

Producer resolution does not bypass normal pytest scope rules. A narrower producer is still invalid for a wider-scope consumer.

The same explicit producer choice also constrains graph selection during `prepare(...)`. If one module contains multiple producer fixtures for the same plan, bindings that declare `producer_fixture="prepare_data_a"` only contribute roots to `prepare_data_a`; they are not silently prepared by sibling producers in the same scope.

## Snapshot File Overrides

Debug replacement is file-based and CLI-driven.

There are two supported paths:

- one scoped bundle for the whole run:
  - `pytest --warmup-snapshot=path/to/warmup.snapshot.json`
- one targeted fragment for a producer that declares `snapshot_id="..."`:
  - `pytest --warmup-snapshot-for inventory-main=path/to/inventory.snapshot.json`

Scoped bundle shape:

```json
{
  "version": 1,
  "scopes": {
    "module:tests/test_module.py::prepare_data": {
      "shared": {
        "profile_main": {
          "value": {
            "profile_id": "debug-profile"
          }
        }
      },
      "tests": {
        "tests/test_module.py::test_case": {
          "items_alpha": {
            "value": {
              "items_id": "debug-items"
            }
          }
        }
      }
    }
  }
}
```

Targeted fragment shape:

```json
{
  "version": 1,
  "shared": {
    "profile_main": {
      "value": {
        "profile_id": "debug-profile"
      }
    }
  },
  "tests": {}
}
```

Rules:

- `scope_id` is computed from the producer scope, a stable container anchor, and the producer fixture name;
- module, class, function, and session scopes use the usual pytest nodeid-style anchor; package scope uses the package path anchor, for example `package:pkg::prepare_data`;
- shared nodes are addressed by `id`;
- per-test nodes are addressed by `tests[nodeid][id]`;
- declarations that are effectively per-test may not be overridden through `shared`;
- an empty object means "this node is addressable here, but no explicit override value is provided";
- `{"value": ...}` means "use this explicit override value";
- if one producer matches both a scoped bundle section and a targeted `snapshot_id` fragment, preparation fails fast instead of applying precedence magic.
- if `--warmup-snapshot-for SNAPSHOT_ID=...` is provided, at least one producer in the current run must execute `prepare(snapshot_id=SNAPSHOT_ID)`, or the run fails with a CLI-usage error.

Plans may validate, deserialize, and serialize snapshot values by overriding:

- `WarmupPlan.validate_snapshot_value(...)`
- `WarmupPlan.deserialize_snapshot_value(...)`
- `WarmupPlan.serialize_snapshot_value(...)`

This keeps snapshot semantics plan-local instead of pushing domain conversion logic into the plugin core.

## CLI Helpers

The plugin also exposes a small debug-oriented CLI surface:

- `--warmup-snapshot PATH`
  Load a versioned scoped snapshot bundle for the whole run.
- `--warmup-snapshot-for SNAPSHOT_ID=PATH`
  Attach one versioned snapshot fragment to one producer `snapshot_id`.
- `--warmup-export-template PATH`
  Write a versioned scoped snapshot template for the selected graph and continue the test run.
- `--warmup-report PATH`
  Write a versioned scoped JSON report describing selected roots, normalized nodes, runtime instances, overrides, trace, and batch timings.
- `--warmup-save-on-fail PATH`
  If warmup preparation fails, write a versioned scoped snapshot containing whatever was already materialized.

These debug artifact outputs are single-process tools. When pytest-xdist is active, `--warmup-export-template`, `--warmup-report`, and `--warmup-save-on-fail` fail fast instead of pretending that one shared output file is safe across workers.

## Troubleshooting

Common producer-resolution errors usually mean one of these:

- `no producer fixture found in pytest dependency chain ...`
  The decorated test or fixture is not connected to any producer fixture that prepares the selected warmup graph.
- `multiple producer fixtures found in pytest dependency chain`
  The current dependency chain exposes more than one prepared producer. Simplify the chain or use `producer_fixture="..."` to pick one explicitly.
- `producer fixture '...' is not in this dependency chain`
  The named producer exists, but the current test or fixture does not depend on it through ordinary pytest wiring.
- `producer fixture '...' must return a prepared warmup scope`
  The selected fixture returned an ordinary value instead of the prepared scope returned by `warmup_mgr.use(...).prepare(...)`.
- `... cannot be shared because dependency ... is per-test`
  A shared declaration depends on a branch that is effectively per-test. Either inherit that branch or split the declaration differently.
- `duplicate id '...' within one producer scope`
  `id` is not a merge key. If reuse was intended, import and reuse the same `WarmupRequirement` object instead of redeclaring it.

## Scope Boundary

`pytest-warmup` is not trying to be:

- a general-purpose factory framework;
- a generic snapshot assertion library;
- a container or infrastructure manager;
- a hidden autouse preparation layer;
- a domain-specific toolkit.

It focuses on one problem: batch creation and targeted distribution of expensive test resources.

Further design details live in:

- [`docs/design.md`](docs/design.md)
- [`docs/publishing.md`](docs/publishing.md)
- [`examples/README.md`](examples/README.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`CHANGELOG.md`](CHANGELOG.md)

## Development

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
./.venv/bin/python -m pytest -q
python scripts/run_compat.py --list
./.venv/bin/python -m build
```

Before publishing, also do one smoke check from the built wheel in a fresh virtual environment.

## Attribution

The initial code, tests, and documentation in this repository were generated and iteratively refined with ChatGPT/Codex plus collaborating agents.

Named collaborating agents from the design and spike process:

- Lovelace is an adversarial, QA-minded reviewer focused on user-facing clarity. She pushed the ergonomics tests, debug/override edge cases, and the API critiques that kept the package honest from a user perspective.
- Herschel is a graph-minded, skeptical contributor who prefers explicit execution boundaries over hidden magic. He drove the selected-roots to reachable-subgraph execution model and kept edge-case behavior small and defensible.
- Chandrasekhar is a no-magic, contract-first contributor focused on clear binding and injection rules. He helped shape the public injection model and the readable fail-fast behavior around overrides and producer discovery.
- Pauli is a direct, readability-first contributor who focused on the debug surface and shared-vs-per-test semantics. He helped keep snapshot addressing and distributed-declaration behavior explicit and testable.
- Kuhn is a pragmatic builder who prefers simple, reviewable orchestration over framework cleverness. He contributed to the manager/runtime seams and the explicit lifecycle shape used by the public prototype.

All generated material still requires human review. The repository treats generated output as draft engineering work, not as an authority.
