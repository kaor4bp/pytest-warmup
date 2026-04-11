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

## What the Package Owns

- declaration of resource requirements through `WarmupPlan.require(...)`;
- graph normalization from selected warmup bindings;
- owner-plan batch preparation ordering;
- injection of materialized values through `@warmup_param(...)`;
- file-based snapshot overrides through `prepare(snapshot_file=...)`.

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

## Snapshot Override Shape

The current JSON shape is:

```json
{
  "shared": {
    "profile_main": {
      "profile_id": "debug-profile"
    }
  },
  "tests": {
    "tests/test_module.py::test_case": {
      "items_alpha": {
        "items_id": "debug-items"
      }
    }
  }
}
```

Rules:

- shared nodes are addressed by `id`;
- per-test nodes are addressed by `tests[nodeid][id]`;
- declarations that are effectively per-test may not be overridden through `shared`.
