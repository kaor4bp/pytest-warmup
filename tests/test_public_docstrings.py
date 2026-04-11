from __future__ import annotations

import pytest_warmup


def test_public_symbols_have_docstrings() -> None:
    public_symbols = [
        pytest_warmup.WarmupError,
        pytest_warmup.WarmupPlan,
        pytest_warmup.WarmupRequirement,
        pytest_warmup.warmup_param,
    ]

    for symbol in public_symbols:
        assert symbol.__doc__
        assert symbol.__doc__.strip()
