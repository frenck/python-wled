"""Exceptions for WLED."""


class WLEDError(Exception):
    """Generic WLED exception."""


class WLEDConnectionError(WLEDError):
    """WLED connection exception."""


class WLEDConnectionTimeoutError(WLEDConnectionError):
    """WLED connection timeout exception."""


class WLEDConnectionClosedError(WLEDConnectionError):
    """WLED WebSocket connection has been closed."""


class WLEDStatusError(WLEDError):
    """WLED HTTP status error exception (4xx/5xx status codes)."""

    def __init__(
        self,
        *args: object,
        method: str | None = None,
        path: str | None = None,
        status: int | None = None,
        body: object = None,
    ) -> None:
        """Initialize WLEDStatusError."""
        super().__init__(*args)
        self.method = method
        self.path = path
        self.status = status
        self.body = body


class WLEDResponseError(WLEDError):
    """WLED response error exception."""

    def __init__(
        self,
        *args: object,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        """Initialize WLEDResponseError."""
        super().__init__(*args)
        self.method = method
        self.path = path


class WLEDEmptyResponseError(WLEDResponseError):
    """WLED empty API response exception."""


class WLEDInvalidResponseError(WLEDResponseError):
    """WLED invalid API response exception."""


class WLEDUnsupportedVersionError(WLEDError):
    """WLED version is unsupported."""


class WLEDUpgradeError(WLEDError):
    """WLED upgrade exception."""
