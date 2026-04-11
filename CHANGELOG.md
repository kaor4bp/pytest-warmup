# Changelog

## Unreleased

- Initial public alpha extraction from the prototype workspace.
- Explicit `WarmupPlan.require(...)` declaration model.
- `@warmup_param(...)` injection for fixtures and test functions.
- Optional producer conveniences through `producer_fixture="..."` and a project-local `warmup_autoresolve_producer` fixture.
- File-based snapshot overrides through `prepare(snapshot_file=...)`.
- Initial validation coverage for cycles, producer-chain errors, distributed declarations, snapshot file failures, and package surface boundaries.
- Public-package hygiene: executable examples, built-wheel smoke testing, and `twine check` validation.
- Trusted Publishing workflow and release documentation for GitHub Actions based PyPI publication.
