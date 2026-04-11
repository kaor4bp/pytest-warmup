from __future__ import annotations

import pytest_warmup


def test_public_surface_stays_narrow() -> None:
    assert hasattr(pytest_warmup, "__version__")
    assert hasattr(pytest_warmup, "WarmupPlan")
    assert hasattr(pytest_warmup, "WarmupRequirement")
    assert hasattr(pytest_warmup, "WarmupError")
    assert hasattr(pytest_warmup, "warmup_param")

    assert not hasattr(pytest_warmup, "PreparedScope")
    assert not hasattr(pytest_warmup, "RuntimeContext")
    assert not hasattr(pytest_warmup, "PlanNode")
    assert not hasattr(pytest_warmup, "ProducedValueStore")
