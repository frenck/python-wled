"""Asynchronous Python client for WLED."""

from enum import IntEnum, IntFlag

from awesomeversion import AwesomeVersion

DEFAULT_REPO = "wled/WLED"

MIN_REQUIRED_VERSION = AwesomeVersion("0.14.0")

CUSTOM_PALETTE_ID_CHANGE_VERSION = AwesomeVersion("16.0.0")

# Since 0.15, WLED no longer takes "recv" to turn receiving sync on or off;
# receiving is on when there are receive groups ("rgrp").
SYNC_RECEIVE_BY_GROUPS_VERSION = AwesomeVersion("0.15.0")


class BuildOption(IntFlag):
    """Enumeration representing the features a WLED build was compiled with."""

    NONE = 0
    OTA = 1
    ADALIGHT = 2
    HUE_SYNC = 4
    FILESYSTEM = 8
    CRONIXIE = 16
    ALEXA = 64
    DEBUG = 128
    NETWORK_DEBUG = 256


class LightCapability(IntFlag):
    """Enumeration representing the capabilities of a light in WLED."""

    NONE = 0
    RGB_COLOR = 1
    WHITE_CHANNEL = 2
    COLOR_TEMPERATURE = 4
    MANUAL_WHITE = 8

    # These are not used, but are reserved for future use.
    # WLED specification documents indicate we should expect them,
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


class SoundSimulationType(IntEnum):
    """Enumeration representing sound simulation types for audio effects."""

    BEAT_SIN = 0
    WE_WILL_ROCK_YOU = 1
    TEN_THREE = 2
    FOURTEEN_THREE = 3


class SyncGroup(IntFlag):
    """Bitfield for UDP sync groups 1-8."""

    NONE = 0
    GROUP1 = 1
    GROUP2 = 2
    GROUP3 = 4
    GROUP4 = 8
    GROUP5 = 16
    GROUP6 = 32
    GROUP7 = 64
    GROUP8 = 128
