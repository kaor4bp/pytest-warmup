from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_basic_usage_example_runs(pytester: pytest.Pytester) -> None:
    example_code = (ROOT / "examples" / "basic_usage.py").read_text(encoding="utf-8")
    snapshot_text = (ROOT / "examples" / "warmup.snapshot.json").read_text(encoding="utf-8")

    pytester.makepyfile(test_basic_usage_example=example_code)
    pytester.path.joinpath("warmup.snapshot.json").write_text(snapshot_text, encoding="utf-8")

    result = pytester.runpytest(
        "--warmup-snapshot-for=basic-usage=warmup.snapshot.json",
        "-q",
    )
    result.assert_outcomes(passed=1)


def test_autoresolve_usage_example_runs(pytester: pytest.Pytester) -> None:
    example_code = (ROOT / "examples" / "autoresolve_usage.py").read_text(encoding="utf-8")
    snapshot_text = (ROOT / "examples" / "warmup.snapshot.json").read_text(encoding="utf-8")

    pytester.makepyfile(test_autoresolve_usage_example=example_code)
    pytester.path.joinpath("warmup.snapshot.json").write_text(snapshot_text, encoding="utf-8")

    result = pytester.runpytest(
        "--warmup-snapshot-for=autoresolve-usage=warmup.snapshot.json",
        "-q",
    )
    result.assert_outcomes(passed=1)


def test_named_producer_usage_example_runs(pytester: pytest.Pytester) -> None:
    example_code = (ROOT / "examples" / "named_producer_usage.py").read_text(
        encoding="utf-8"
    )

    pytester.makepyfile(test_named_producer_usage_example=example_code)

    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)
