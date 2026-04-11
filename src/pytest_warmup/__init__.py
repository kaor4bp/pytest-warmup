"""Public package surface for pytest-warmup."""

from importlib.metadata import version as _package_version

from .core import (
    WarmupError,
    WarmupPlan,
    WarmupRequirement,
    warmup_param,
)

__version__ = _package_version("pytest-warmup")

__all__ = [
    "__version__",
    "WarmupError",
    "WarmupPlan",
    "WarmupRequirement",
    "warmup_param",
]
