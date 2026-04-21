"""Public package surface for pytest-warmup."""

from importlib.metadata import version as _package_version

from ._errors import WarmupError
from .core import (
    WarmupNode,
    WarmupPlan,
    WarmupRequirement,
    warmup_param,
)

__version__ = _package_version("pytest-warmup")

__all__ = [
    "__version__",
    "WarmupError",
    "WarmupNode",
    "WarmupPlan",
    "WarmupRequirement",
    "warmup_param",
]
