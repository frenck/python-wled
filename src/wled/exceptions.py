"""Exceptions for WLED."""


class WLEDError(Exception):
    """Generic WLED exception."""


class WLEDEmptyResponseError(Exception):
    """WLED empty API response exception."""


class WLEDConnectionError(WLEDError):
    """WLED connection exception."""


class WLEDConnectionTimeoutError(WLEDConnectionError):
    """WLED connection Timeout exception."""


class WLEDConnectionClosedError(WLEDConnectionError):
    """WLED WebSocket connection has been closed."""


class WLEDUnsupportedVersionError(WLEDError):
    """WLED version is unsupported."""


class WLEDUpgradeError(WLEDError):
    """WLED upgrade exception."""
