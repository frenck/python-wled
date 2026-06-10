"""Exceptions for WLED."""


class WLEDError(Exception):
    """Generic WLED exception."""


class WLEDEmptyResponseError(WLEDError):
    """WLED empty API response exception."""

    def __init__(
        self,
        message: str = "",
        *,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        """Initialize WLEDEmptyResponseError."""
        super().__init__(message)
        self.method = method
        self.path = path


class WLEDInvalidResponseError(WLEDError):
    """WLED invalid API response exception."""

    def __init__(
        self,
        message: str = "",
        *,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        """Initialize WLEDInvalidResponseError."""
        super().__init__(message)
        self.method = method
        self.path = path


class WLEDConnectionError(WLEDError):
    """WLED connection exception."""


class WLEDConnectionTimeoutError(WLEDConnectionError):
    """WLED connection timeout exception."""


class WLEDConnectionClosedError(WLEDConnectionError):
    """WLED WebSocket connection has been closed."""


class WLEDUnsupportedVersionError(WLEDError):
    """WLED version is unsupported."""


class WLEDUpgradeError(WLEDError):
    """WLED upgrade exception."""
