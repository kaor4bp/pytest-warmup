"""Internal error types shared across pytest-warmup modules."""


class WarmupError(ValueError):
    """Raised when warmup declaration, preparation, or injection fails fast."""

    pass
