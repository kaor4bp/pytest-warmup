"""Public package surface for pytest-warmup."""

from importlib.metadata import version as _package_version

from ._errors import WarmupError
from .core import (
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
