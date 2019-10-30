"""Exceptions for WLED."""


class WLEDError(Exception):
    """Generic WLED exception."""

    pass


class WLEDConnectionError(WLEDError):
    """WLED connection exception."""

    pass
