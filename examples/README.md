# Examples

This directory contains neutral examples for the public package.

- [`basic_usage.py`](basic_usage.py) shows the smallest useful producer/consumer shape without snapshot overrides.
- [`fixture_binding_usage.py`](fixture_binding_usage.py) shows fixture-side binding through the normal producer dependency chain plus a targeted snapshot override.
- [`named_producer_usage.py`](named_producer_usage.py) shows how `producer_fixture="..."` disambiguates two producers that are already present in the pytest dependency chain.
- [`warmup.snapshot.json`](warmup.snapshot.json) shows the versioned targeted snapshot fragment used by the examples through `--warmup-snapshot-for`.

The examples are intentionally anonymized and do not represent any internal domain model.

These examples show the intended producer patterns:

- explicit producer dependency as the default path;
- `producer_fixture="..."` when you need to disambiguate between producers that are already present in the pytest dependency chain.
