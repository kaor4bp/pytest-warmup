# Changelog

## Unreleased

- Added multi-binding support for stacking multiple `@warmup_param(...)` decorators on one callable.
- Added pytest CLI options:
  - `--warmup-snapshot`
  - `--warmup-snapshot-for`
  - `--warmup-export-template`
  - `--warmup-report`
  - `--warmup-save-on-fail`
- Added plan-local snapshot hooks on `WarmupPlan` for validation, deserialization, and serialization.
- Replaced the old `prepare(snapshot_file=...)` override path with:
  - one versioned scoped snapshot bundle loaded through `--warmup-snapshot`
  - one targeted snapshot fragment attached through `prepare(snapshot_id=...)` and `--warmup-snapshot-for`
- Moved snapshot parsing to session level while keeping materialization at the producer fixture scope.
- Switched snapshot entries to an addressable map with optional explicit `value` payloads.
- Added fail-fast validation for unused `--warmup-snapshot-for SNAPSHOT_ID=...` targets in the current run.
- Made debug artifact outputs (`export-template`, `report`, `save-on-fail`) emit versioned scoped documents and merge multiple producer scopes in one process.
- Added fail-fast protection for debug artifact outputs under pytest-xdist instead of pretending that one shared output file is safe across workers.
- Improved duplicate-id guidance so reuse points back to importing the same `WarmupRequirement` object instead of redeclaring it.
- Clarified the package identity model in the documentation: one spec object means one logical node, and `id` is not a merge key.

## 0.1.1

- Initial public alpha extraction from the prototype workspace.
- Explicit `WarmupPlan.require(...)` declaration model.
- `@warmup_param(...)` injection for fixtures and test functions.
- Optional producer conveniences through `producer_fixture="..."` and a project-local `warmup_autoresolve_producer` fixture.
- File-based snapshot overrides through `prepare(snapshot_file=...)`.
- Initial validation coverage for cycles, producer-chain errors, distributed declarations, snapshot file failures, and package surface boundaries.
- Public-package hygiene: executable examples, built-wheel smoke testing, and `twine check` validation.
- Trusted Publishing workflow and release documentation for GitHub Actions based PyPI publication.
