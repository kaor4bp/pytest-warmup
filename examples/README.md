# Examples

This directory contains neutral examples for the public package.

- [`basic_usage.py`](basic_usage.py) shows the smallest useful producer/consumer shape.
- [`autoresolve_usage.py`](autoresolve_usage.py) shows the optional `warmup_autoresolve_producer` convenience path for fixture-side binding.
- [`named_producer_usage.py`](named_producer_usage.py) shows how `producer_fixture="..."` disambiguates two producers that are already present in the pytest dependency chain.
- [`warmup.snapshot.json`](warmup.snapshot.json) shows the file-based override format used by the example.

The examples are intentionally anonymized and do not represent any internal domain model.

These examples show the three intended producer patterns:

- explicit producer dependency as the default path;
- `warmup_autoresolve_producer` when you want less producer boilerplate in consumer signatures;
- `producer_fixture="..."` when you need to disambiguate between producers that are already present in the pytest dependency chain.
