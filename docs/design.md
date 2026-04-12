# Design Scope

`pytest-warmup` is intentionally narrow.

The package is meant for test suites where expensive external-domain objects should be prepared in batches and then distributed into tests through explicit pytest producer fixtures.

The preferred shape is still an ordinary producer fixture in the pytest dependency chain. As a narrow convenience, `@warmup_param(...)` may also resolve a producer through an explicit `producer_fixture="..."` name that already exists in that dependency chain, or through a project-local `warmup_autoresolve_producer` fixture.

Producer resolution rules:

1. `producer_fixture="..."` wins when present, but the named fixture must already be part of the pytest dependency chain.
2. Otherwise, one prepared producer discovered in the dependency chain is accepted.
3. Otherwise, `warmup_autoresolve_producer` is used as a narrow fallback.
4. Otherwise, producer resolution fails fast.

This keeps the default explicit while still allowing two controlled convenience paths.

Supported producer scopes are `session`, `package`, `module`, `class`, and `function`.

## What the Package Owns

- declaration of resource requirements through `WarmupPlan.require(...)`;
- graph normalization from selected warmup bindings;
- owner-plan batch preparation ordering;
- injection of materialized values through `@warmup_param(...)`;
- file-based snapshot overrides through `--warmup-snapshot` and `--warmup-snapshot-for`;
- debug exports through `--warmup-export-template`, `--warmup-report`, and `--warmup-save-on-fail`, all emitted as versioned scoped documents.

## What the Package Does Not Own

- domain-specific plan subclasses such as inventory, billing, logistics, or infrastructure plans;
- inline code-based debug overrides;
- generic snapshot assertion tooling;
- container orchestration or service emulation frameworks;
- hidden global autouse preparation.

## Public API Boundary

The intended public surface is deliberately small:

- `WarmupPlan`
- `WarmupRequirement`
- `WarmupError`
- `warmup_param`
- the `warmup_mgr` fixture exposed by the pytest plugin

Internal graph/runtime types are implementation details and should stay private.

## Requirement Identity

- Requirement identity is object identity.
- Reusing the same requirement object means the same logical node.
- Calling `require(...)` again creates a different declaration, even if the payload is identical.
- Public `id` values are addressable debug keys, not merge keys.
- If two tests should share one resource, declare it once and import that same requirement object.
- Do not invent merge keys, payload-based equivalence, or implicit declaration coalescing.

This package intentionally keeps the mapping strict:

- one spec object -> one logical node;
- one reused imported object -> one reused resource;
- one redeclared object -> one new node.

That explicit rule is easier to debug than clever equivalence heuristics, and it keeps duplicate-id failures actionable instead of ambiguous.

## Binding Model

- One callable may carry multiple `@warmup_param(...)` bindings.
- Those bindings still resolve through one producer path.
- If an explicit `producer_fixture="..."` is used on one binding, stacked bindings on that callable must agree on the same producer fixture.

The package does not add a separate batching DSL here. `WarmupPlan.prepare(nodes, runtime)` already receives the relevant nodes for that plan, so domain plans can batch external work without inventing core-level merge semantics.

## Snapshot Override Shape

The primary snapshot input is a versioned scoped bundle:

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

One producer may also declare `snapshot_id="..."` and receive one targeted snapshot fragment from
`--warmup-snapshot-for <snapshot_id>=<path>`. That fragment uses the same `shared` / `tests` shape,
but without the outer `scopes` object.

Rules:

- snapshot parsing happens once per pytest session, but producer materialization still happens at the
  producer fixture scope;
- `scope_id` is computed from the producer scope, the current container nodeid, and the producer fixture name;
- shared nodes are addressed by `id`;
- per-test nodes are addressed by `tests[nodeid][id]`;
- entries use `{}` for addressable nodes without an explicit override and `{"value": ...}` for an explicit override;
- declarations that are effectively per-test may not be overridden through `shared`;
- if one producer matches both a scoped bundle section and a targeted `snapshot_id` fragment, preparation fails fast;
- if `--warmup-snapshot-for SNAPSHOT_ID=...` is provided, at least one producer in the current run must execute `prepare(snapshot_id=SNAPSHOT_ID)`, or the run ends with a CLI-usage error;
- `--warmup-export-template` writes the same versioned scoped shape for the currently selected graph;
- `--warmup-report` writes a versioned scoped report keyed by producer `scope_id`;
- `--warmup-save-on-fail` writes the same versioned scoped shape with any values that were already materialized.
- these debug outputs merge multiple producer scopes within one process but intentionally fail fast when pytest-xdist is active, because one shared output path is not a safe cross-worker contract.

Snapshot conversion is plan-local through:

- `validate_snapshot_value(...)`
- `deserialize_snapshot_value(...)`
- `serialize_snapshot_value(...)`
