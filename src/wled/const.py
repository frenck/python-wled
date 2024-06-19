"""Asynchronous Python client for WLED."""

from enum import IntEnum, IntFlag

from awesomeversion import AwesomeVersion

MIN_REQUIRED_VERSION = AwesomeVersion("0.14.0")


class LightCapability(IntFlag):
    """Enumeration representing the capabilities of a light in WLED."""

    NONE = 0
    RGB_COLOR = 1
    WHITE_CHANNEL = 2
    COLOR_TEMPERATURE = 4
    MANUAL_WHITE = 8

    # These are not used, but are reserved for future use.
    # WLED specifications documents we should expect them,
    # therefore, we include them here.
    RESERVED_2 = 16
    RESERVED_3 = 32
    RESERVED_4 = 64
    RESERVED_5 = 128


class LiveDataOverride(IntEnum):
    """Enumeration representing live override mode from WLED."""

    OFF = 0
    ON = 1
    OFF_UNTIL_REBOOT = 2


class NightlightMode(IntEnum):
    """Enumeration representing nightlight mode from WLED."""

    INSTANT = 0
    FADE = 1
    COLOR_FADE = 2
    SUNRISE = 3


class SyncGroup(IntFlag):
    """Bitfield for udp sync groups 1-8."""

    NONE = 0
    GROUP1 = 1
    GROUP2 = 2
    GROUP3 = 4
    GROUP4 = 8
    GROUP5 = 16
    GROUP6 = 32
    GROUP7 = 64
    GROUP8 = 128
