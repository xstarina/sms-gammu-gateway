"""Application-level exceptions."""


class GatewayError(RuntimeError):
    """Configuration error that prevents the gateway from starting."""
