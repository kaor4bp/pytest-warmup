# Contributing

This repository is still in an early alpha phase. The most important contribution rule is to keep the public API narrow and explicit.

## Development Setup

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

## Verification

Run the local checks before proposing changes:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m build
./.venv/bin/python -m twine check dist/*
```

Before publishing or cutting a release candidate, also do one external-user smoke check from the built wheel: create a fresh virtual environment, install the wheel from `dist/`, and run one of the example tests without editable-install path hacks.

For the repository-side release flow, see [`docs/publishing.md`](docs/publishing.md).

## Scope Rules

Changes are welcome, but the package should stay focused on:

- requirement declaration through `WarmupPlan.require(...)`;
- explicit producer preparation through `warmup_mgr.use(...).prepare(...)`;
- injection through `@warmup_param(...)`;
- file-based snapshot overrides;
- batch preparation and distribution of expensive test resources.

The package should not grow into:

- a general factory framework;
- a generic snapshot assertion library;
- a service/container orchestration framework;
- a domain-specific toolkit.

## Public API Hygiene

Before widening the public surface, check whether the change can stay internal instead.

In particular, keep these internal unless there is a strong reason otherwise:

- graph normalization helpers;
- runtime/store implementation details;
- test-support demo plans;
- fake external API helpers.
