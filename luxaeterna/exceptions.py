"""Lux Aeterna custom exceptions."""


class LuxAeternaError(Exception):
    """Base exception for Lux Aeterna."""


class BackendError(LuxAeternaError):
    """Raised when a backend operation fails."""


class ConnectionError(BackendError):
    """Raised when a backend cannot connect or loses connection."""


class ChannelError(LuxAeternaError):
    """Raised for invalid channel operations."""


class FixtureError(LuxAeternaError):
    """Raised for fixture configuration or control errors."""
