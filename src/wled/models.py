"""Models for WLED."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any

from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializableType, SerializationStrategy

from .const import (
    CUSTOM_PALETTE_ID_CHANGE_VERSION,
    MIN_REQUIRED_VERSION,
    LightCapability,
    LiveDataOverride,
    NightlightMode,
    SoundSimulationType,
    SyncGroup,
)
from .exceptions import WLEDUnsupportedVersionError
from .utils import get_awesome_version

# For palette ID space layout, see:
# https://github.com/wled/WLED/blob/665d66f45eba17b42a30d99689430b7297ff2559/wled00/const.h#L19
# https://github.com/wled/WLED/commit/fd6f568023fca8500e4cb40712b913a8612b827d
# Since WLED 16.0.0, palette ID space was reorganized:
# - Usermod palettes: IDs 255-201 (55 slots)
# - User custom palettes: IDs 200-FIXED_PALETTE_COUNT+1 (129 slots)
# In versions < 16.0.0, custom palettes counted down from 255.
WLED_USERMOD_PALETTE_ID_BASE = 255
WLED_CUSTOM_PALETTE_ID_BASE = 200
WLED_CUSTOM_PALETTE_ID_BASE_LEGACY = 255


class AwesomeVersionSerializationStrategy(SerializationStrategy, use_annotations=True):
    """Serialization strategy for AwesomeVersion objects."""

    def serialize(self, value: AwesomeVersion | None) -> str:
        """Serialize AwesomeVersion object to string."""
        if value is None:
            return ""
        return str(value)

    def deserialize(self, value: str) -> AwesomeVersion | None:
        """Deserialize string to AwesomeVersion object."""
        version = get_awesome_version(value)
        if not version.valid:
            return None
        return version


class TimedeltaSerializationStrategy(SerializationStrategy, use_annotations=True):
    """Serialization strategy for timedelta objects."""

    def serialize(self, value: timedelta) -> int:
        """Serialize timedelta object to seconds."""
        return int(value.total_seconds())

    def deserialize(self, value: int) -> timedelta:
        """Deserialize integer to timedelta object."""
        return timedelta(seconds=value)


class TimestampSerializationStrategy(SerializationStrategy, use_annotations=True):
    """Serialization strategy for datetime objects."""

    def serialize(self, value: datetime) -> float:
        """Serialize datetime object to timestamp."""
        return value.timestamp()

    def deserialize(self, value: float) -> datetime:
        """Deserialize timestamp to datetime object."""
        return datetime.fromtimestamp(value, tz=UTC)


@dataclass
class Color(SerializableType):
    """Object holding color information in WLED."""

    primary: tuple[int, int, int, int] | tuple[int, int, int]
    secondary: tuple[int, int, int, int] | tuple[int, int, int] | None = None
    tertiary: tuple[int, int, int, int] | tuple[int, int, int] | None = None

    def _serialize(self) -> list[tuple[int, int, int, int] | tuple[int, int, int]]:
        colors = [self.primary]
        if self.secondary is not None:
            colors.append(self.secondary)
            if self.tertiary is not None:
                colors.append(self.tertiary)
        return colors

    @classmethod
    def _deserialize(
        cls, value: list[tuple[int, int, int, int] | tuple[int, int, int] | str]
    ) -> Color:
        # Some values in the list can be strings, which indicates that the
        # color is a hex color value.
        return cls(
            *[
                tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
                if isinstance(color, str)
                else color
                for color in value
            ]  # ty: ignore[invalid-argument-type]
        )


class BaseModel(DataClassORJSONMixin):
    """Base model for all WLED models."""

    # pylint: disable-next=too-few-public-methods
    class Config(BaseConfig):
        """Mashumaro configuration."""

        omit_none = True
        serialization_strategy = {  # noqa: RUF012
            AwesomeVersion: AwesomeVersionSerializationStrategy(),
            datetime: TimestampSerializationStrategy(),
            timedelta: TimedeltaSerializationStrategy(),
        }
        serialize_by_alias = True


@dataclass(kw_only=True)
class Nightlight(BaseModel):
    """Object holding nightlight state in WLED."""

    duration: int = field(default=1, metadata=field_options(alias="dur"))
    """Duration of nightlight in minutes."""

    mode: NightlightMode = field(default=NightlightMode.INSTANT)
    """Nightlight mode (available since 0.10.2)."""

    on: bool = field(default=False)
    """Nightlight currently active."""

    remaining: int = field(default=-1, metadata=field_options(alias="rem"))
    """Remaining nightlight duration in seconds. -1 if not active."""

    target_brightness: int = field(default=0, metadata=field_options(alias="tbri"))
    """Target brightness of nightlight feature."""


@dataclass(kw_only=True)
class UDPSync(BaseModel):
    """Object holding UDP sync state in WLED.

    Missing at this point, is the `nn` field. This field allows to skip
    sending a broadcast packet for the current API request; However, this field
    is only used for requests and not part of the state responses.
    """

    receive: bool = field(default=False, metadata=field_options(alias="recv"))
    """Receive broadcast packets."""

    receive_groups: SyncGroup = field(
        default=SyncGroup.NONE, metadata=field_options(alias="rgrp")
    )
    """Groups to receive WLED broadcast packets from."""

    send: bool = field(default=False, metadata=field_options(alias="send"))
    """Send WLED broadcast (UDP sync) packet on state change."""

    send_groups: SyncGroup = field(
        default=SyncGroup.NONE, metadata=field_options(alias="sgrp")
    )
    """Groups to send WLED broadcast packets to."""


@dataclass(frozen=True, kw_only=True)
class Effect(BaseModel):
    """Object holding an effect in WLED."""

    effect_id: int
    name: str


@dataclass(frozen=True, kw_only=True)
class Palette(BaseModel):
    """Object holding a palette in WLED."""

    custom: bool = False
    name: str
    palette_id: int


@dataclass(kw_only=True)
class Segment(BaseModel):
    """Object holding segment state in WLED."""

    brightness: int | str = field(default=0, metadata=field_options(alias="bri"))
    """Brightness of the segment.

    ~ to increment, ~- to decrement. w~40 to increment by 40, wrapping.
    """

    cct: int = field(default=0)
    """White spectrum color temperature.

    0 indicates the warmest possible color temperature,
    255 indicates the coldest temperature.
    """

    clones: int = field(default=-1, metadata=field_options(alias="cln"))
    """The segment this segment clones."""

    color: Color | None = field(default=None, metadata=field_options(alias="col"))
    """The primary, secondary (background) and tertiary colors of the segment.

    Each color is a tuple of 3 or 4 bytes, which represents a RGB(W) color,
    i.e. (255,170,0) or (64,64,64,64).

    WLED can also return hex color values as strings, this library will
    automatically convert those to RGB values to keep the data consistent.
    """

    custom1: int = field(default=128, metadata=field_options(alias="c1"))
    """Effect custom slider 1 value (0-255)."""

    custom2: int = field(default=128, metadata=field_options(alias="c2"))
    """Effect custom slider 2 value (0-255)."""

    custom3: int = field(default=16, metadata=field_options(alias="c3"))
    """Effect custom slider 3 value (0-31)."""

    effect_id: int | str = field(default=0, metadata=field_options(alias="fx"))
    """ID of the effect.

    ~ to increment, ~- to decrement, or "r" for random.
    """

    expand_1d: int = field(default=0, metadata=field_options(alias="m12"))
    """Setting of segment field 'Expand 1D FX' (0-4)."""

    freeze: bool = field(default=False, metadata=field_options(alias="frz"))
    """Freeze the current segment state."""

    grouping: int = field(default=1, metadata=field_options(alias="grp"))
    """How many consecutive LEDs are grouped to the same color."""

    intensity: int | str = field(default=0, metadata=field_options(alias="ix"))
    """Intensity of the segment.

    Effect intensity. ~ to increment, ~- to decrement. ~10 to increment by 10,
    ~-10 to decrement by 10.
    """

    length: int = field(default=0, metadata=field_options(alias="len"))
    """Length of the segment (stop - start).

    Stop has preference, so if it is included, length is ignored.
    """

    mirror: bool = field(default=False, metadata=field_options(alias="mi"))
    """Mirrors the segment (horizontal for 2D)."""

    mirror_y: bool = field(default=False, metadata=field_options(alias="mY"))
    """Mirrors the 2D segment in the vertical dimension."""

    name: str | None = field(default=None, metadata=field_options(alias="n"))
    """User-defined name of the segment."""

    offset: int = field(default=0, metadata=field_options(alias="of"))
    """How many LEDs to rotate the virtual start of the segment."""

    on: bool | None = field(default=None)
    """The on/off state of the segment."""

    option1: bool = field(default=False, metadata=field_options(alias="o1"))
    """Effect option 1."""

    option2: bool = field(default=False, metadata=field_options(alias="o2"))
    """Effect option 2."""

    option3: bool = field(default=False, metadata=field_options(alias="o3"))
    """Effect option 3."""

    palette_id: int | str = field(default=0, metadata=field_options(alias="pal"))
    """ID of the palette.

    ~ to increment, ~- to decrement, or r for random.
    """

    reverse: bool = field(default=False, metadata=field_options(alias="rev"))
    """Flips the segment (horizontal for 2D), causing animations to change direction."""

    reverse_y: bool = field(default=False, metadata=field_options(alias="rY"))
    """Flips the 2D segment in the vertical dimension."""

    segment_id: int | None = field(default=None, metadata=field_options(alias="id"))
    """The ID of the segment."""

    selected: bool = field(default=False, metadata=field_options(alias="sel"))
    """Indicates if the segment is selected.

    Selected segments will have their state (color/FX) updated by APIs that
    don't support segments (e.g. UDP sync, HTTP API).
    """

    set_id: int = field(default=0, metadata=field_options(alias="set"))
    """Group or set ID assigned to the segment (0-3)."""

    sound_simulation: SoundSimulationType = field(
        default=SoundSimulationType.BEAT_SIN, metadata=field_options(alias="si")
    )
    """Sound simulation type for audio enhanced effects."""

    spacing: int = field(default=0, metadata=field_options(alias="spc"))
    """How many LEDs are turned off and skipped between each group."""

    speed: int | str = field(default=0, metadata=field_options(alias="sx"))
    """Relative effect speed.

    ~ to increment, ~- to decrement. ~10 to increment by 10, ~-10 to decrement by 10.
    """

    start: int = 0
    """LED the segment starts at (column for 2D)."""

    start_y: int = field(default=0, metadata=field_options(alias="startY"))
    """Start row from top-left corner of the matrix (2D only)."""

    stop: int = 0
    """LED the segment stops at, not included in range (column for 2D)."""

    stop_y: int = field(default=0, metadata=field_options(alias="stopY"))
    """Stop row from top-left corner of the matrix (2D only)."""

    transpose: bool = field(default=False, metadata=field_options(alias="tp"))
    """Transposes the segment, swapping X and Y dimensions (2D only)."""


@dataclass(kw_only=True)
class Leds:
    """Object holding leds info from WLED."""

    cct: bool = False
    """True if the LEDs support color temperature control."""

    count: int = 0
    """Total LED count."""

    fps: int = 0
    """Current frames per second."""

    light_capabilities: LightCapability = field(
        default=LightCapability.NONE, metadata=field_options(alias="lc")
    )
    """Capabilities of the light."""

    max_power: int = field(default=0, metadata=field_options(alias="maxpwr"))
    """Maximum power budget in milliamperes for the ABL. 0 if ABL is disabled."""

    max_segments: int = field(default=0, metadata=field_options(alias="maxseg"))
    """Maximum number of segments supported by this version."""

    power: int = field(default=0, metadata=field_options(alias="pwr"))
    """
    Current LED power usage in milliamperes as determined by the ABL.
    0 if ABL is disabled.
    """

    rgbw: bool = False
    """True if the LEDs are 4-channel (RGB + White)."""

    segment_light_capabilities: list[LightCapability] = field(
        default_factory=list, metadata=field_options(alias="seglc")
    )
    """Capabilities of each segment."""

    wv: bool = False
    """True if the white channel slider should be displayed."""


@dataclass(kw_only=True)
class Wifi(BaseModel):
    """Object holding Wi-Fi information from WLED."""

    bssid: str = "00:00:00:00:00:00"
    channel: int = 0
    rssi: int = 0
    signal: int = 0


@dataclass(kw_only=True)
class Filesystem(BaseModel):
    """Object holding filesystem information from WLED."""

    last_modified: datetime | None = field(
        default=None, metadata=field_options(alias="pmt")
    )
    """
    Last modification of the presets.json file. Not accurate after boot or
    after using /edit.
    """

    total: int = field(default=1, metadata=field_options(alias="t"))
    """Total space of the filesystem in kilobytes."""

    used: int = field(default=1, metadata=field_options(alias="u"))
    """Used space of the filesystem in kilobytes."""

    @cached_property
    def free(self) -> int:
        """Return the free space of the filesystem in kilobytes.

        Returns
        -------
            The free space of the filesystem.

        """
        return self.total - self.used

    @cached_property
    def free_percentage(self) -> int:
        """Return the free percentage of the filesystem.

        Returns
        -------
            The free percentage of the filesystem.

        """
        return round((self.free / self.total) * 100)

    @cached_property
    def used_percentage(self) -> int:
        """Return the used percentage of the filesystem.

        Returns
        -------
            The used percentage of the filesystem.

        """
        return round((self.used / self.total) * 100)


@dataclass(kw_only=True)
class Info(BaseModel):  # pylint: disable=too-many-instance-attributes
    """Object holding information from WLED."""

    architecture: str = field(default="unknown", metadata=field_options(alias="arch"))
    """Name of the platform."""

    arduino_core_version: str = field(
        default="Unknown", metadata=field_options(alias="core")
    )
    """Version of the underlying (Arduino core) SDK."""

    brand: str = "WLED"
    """The producer/vendor of the light. Always WLED for standard installations."""

    build: str = field(default="Unknown", metadata=field_options(alias="vid"))
    """Build ID (YYMMDDB, B = daily build index)."""

    effect_count: int = field(default=0, metadata=field_options(alias="fxcount"))
    """Number of effects included."""

    filesystem: Filesystem = field(metadata=field_options(alias="fs"))
    """Info about the embedded LittleFS filesystem."""

    free_heap: int = field(default=0, metadata=field_options(alias="freeheap"))
    """Bytes of heap memory (RAM) currently available. Problematic if <10k."""

    ip: str = ""  # pylint: disable=invalid-name
    """The IP address of this instance. Empty string if not connected."""

    leds: Leds = field(default_factory=Leds)
    """Contains info about the LED setup."""

    live_ip: str = field(default="Unknown", metadata=field_options(alias="lip"))
    """Realtime data source IP address."""

    live_mode: str = field(default="Unknown", metadata=field_options(alias="lm"))
    """Info about the realtime data source."""

    live: bool = False
    """Realtime data source active via UDP or E1.31."""

    mac_address: str = field(default="", metadata=field_options(alias="mac"))
    """
    The hexadecimal hardware MAC address of the light,
    lowercase and without colons.
    """

    name: str = "WLED Light"
    """Friendly name of the light. Intended for display in lists and titles."""

    custom_palette_count: int = field(
        default=0, metadata=field_options(alias="cpalcount")
    )
    """Number of custom palettes configured."""

    palette_count: int = field(default=0, metadata=field_options(alias="palcount"))
    """Number of palettes configured."""

    usermod_palette_count: int = field(
        default=0, metadata=field_options(alias="umpalcount")
    )
    """Number of usermod palettes configured."""

    usermod_palette_names: list[str] = field(
        default_factory=list, metadata=field_options(alias="umpalnames")
    )
    """Names of usermod palettes."""

    product: str = "DIY Light"
    """The product name. Always FOSS for standard installations."""

    release: str | None = None
    """The release name of the firmware build.

    When present, used to determine the correct firmware filename during
    upgrades (e.g. "ESP32", "ESP32_Ethernet", "ESP8266_160").
    """

    sync_toggle_receive: bool = field(
        default=False, metadata=field_options(alias="str")
    )
    """If true, UI toggling also toggles sync receive."""

    udp_port: int = field(default=0, metadata=field_options(alias="udpport"))
    """The UDP port for realtime packets and WLED broadcast."""

    uptime: timedelta = timedelta(0)
    """Uptime of the device."""

    version: AwesomeVersion | None = field(
        default=None, metadata=field_options(alias="ver")
    )
    """Version of the WLED software."""

    websocket: int | None = field(default=None, metadata=field_options(alias="ws"))
    """
    Number of currently connected WebSockets clients.
    `None` indicates that WebSockets are unsupported in this build.
    """

    wifi: Wifi | None = None
    """Info about the Wi-Fi connection."""

    @classmethod
    def __post_deserialize__(cls, obj: Info) -> Info:
        """Post deserialize hook for Info object."""
        # If the websocket is disabled in this build, the value will be -1.
        # We want to represent this as None.
        if obj.websocket == -1:
            obj.websocket = None

        # We want the architecture in lower case
        obj.architecture = obj.architecture.lower()

        # We can tweak the architecture name based on the filesystem size.
        if obj.filesystem is not None and obj.architecture == "esp8266":
            if obj.filesystem.total <= 256:
                obj.architecture = "esp01"
            elif obj.filesystem.total <= 512:
                obj.architecture = "esp02"

        return obj


@dataclass(kw_only=True)
class State(BaseModel):
    """Object holding the state of WLED."""

    brightness: int = field(default=1, metadata=field_options(alias="bri"))
    """Brightness of the light.

    If on is false, contains last brightness when light was on (aka brightness
    when on is set to true). Setting bri to 0 is supported but it is
    recommended to use the range 1-255 and use on: false to turn off.

    The state response will never have the value 0 for bri.
    """

    ledmap: int = field(default=0)
    """Currently loaded LED map. 0 is the default map."""

    main_segment_id: int = field(default=0, metadata=field_options(alias="mainseg"))
    """ID of the main segment."""

    nightlight: Nightlight = field(metadata=field_options(alias="nl"))
    """Nightlight state."""

    on: bool = False
    """The on/off state of the light."""

    playlist_id: int | None = field(default=-1, metadata=field_options(alias="pl"))
    """ID of currently set playlist."""

    preset_id: int | None = field(default=-1, metadata=field_options(alias="ps"))
    """ID of currently set preset."""

    segments: dict[int, Segment] = field(
        default_factory=dict, metadata=field_options(alias="seg")
    )
    """Segments are individual parts of the LED strip."""

    sync: UDPSync = field(metadata=field_options(alias="udpn"))
    """UDP sync state."""

    transition: int = 0
    """Duration of the crossfade between different colors/brightness levels.

    One unit is 100ms, so a value of 4 results in a transition of 400ms.
    """

    live_data_override: LiveDataOverride = field(metadata=field_options(alias="lor"))
    """Live data override.

    0 is off, 1 is override until live data ends, 2 is override until ESP reboot.
    """

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for State object."""
        # Segments are not indexed, which is suboptimal for the user.
        # We will add the segment ID to the segment data and convert
        # the segments list to an indexed dict.
        d["seg"] = {
            segment_id: segment | {"id": segment_id}
            for segment_id, segment in enumerate(d.get("seg", []))
        }
        return d

    @classmethod
    def __post_deserialize__(cls, obj: State) -> State:
        """Post deserialize hook for State object."""
        # If no playlist is active, the value will be -1. We want to represent
        # this as None.
        if obj.playlist_id == -1:
            obj.playlist_id = None

        # If no preset is active, the value will be -1. We want to represent
        # this as None.
        if obj.preset_id == -1:
            obj.preset_id = None

        return obj


@dataclass(kw_only=True)
class Preset(BaseModel):
    """Object representing a WLED preset."""

    preset_id: int
    """The ID of the preset."""

    name: str = field(default="", metadata=field_options(alias="n"))
    """The name of the preset."""

    quick_label: str | None = field(default=None, metadata=field_options(alias="ql"))
    """The quick label of the preset."""

    on: bool = False
    """The on/off state of the preset."""

    transition: int = 0
    """Duration of the crossfade between different colors/brightness levels.

    One unit is 100ms, so a value of 4 results in a transition of 400ms.
    """

    main_segment_id: int = field(default=0, metadata=field_options(alias="mainseg"))
    """The main segment of the preset."""

    segments: list[Segment] = field(
        default_factory=list, metadata=field_options(alias="seg")
    )
    """Segments are individual parts of the LED strip."""

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Preset object."""
        # If the segment is a single value, we will convert it to a list.
        if "seg" in d and not isinstance(d["seg"], list):
            d["seg"] = [d["seg"]]

        return d

    @classmethod
    def __post_deserialize__(cls, obj: Preset) -> Preset:
        """Post deserialize hook for Preset object."""
        # If name is empty, we will replace it with the preset ID.
        if not obj.name:
            obj.name = str(obj.preset_id)
        return obj


@dataclass(frozen=True, kw_only=True)
class PlaylistEntry(BaseModel):
    """Object representing an entry in a WLED playlist."""

    duration: int = field(metadata=field_options(alias="dur"))
    entry_id: int
    preset: int = field(metadata=field_options(alias="ps"))
    transition: int


@dataclass(kw_only=True)
class Playlist(BaseModel):
    """Object representing a WLED playlist."""

    end_preset_id: int | None = field(default=None, metadata=field_options(alias="end"))
    """Single preset ID to apply after the playlist finished.

    Has no effect when an indefinite cycle is set. If not provided,
    the light will stay on the last preset of the playlist.
    """

    entries: list[PlaylistEntry]
    """List of entries in the playlist."""

    name: str = field(default="", metadata=field_options(alias="n"))
    """The name of the playlist."""

    playlist_id: int
    """The ID of the playlist."""

    repeat: int = 0
    """Number of times the playlist should repeat."""

    shuffle: bool = field(default=False, metadata=field_options(alias="r"))
    """Shuffle the playlist entries."""

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Playlist object."""
        d |= d["playlist"]
        # Duration, presets and transitions values are separate lists stored
        # in the playlist data. We will combine those into a list of
        # dictionaries, which will make it easier to work with the data.
        item_count = len(d.get("ps", []))

        # If the duration is a single value, we will convert it to a list.
        # with the same length as the presets list.
        if not isinstance(d["dur"], list):
            d["dur"] = [d["dur"]] * item_count

        # If the transition value doesn't exist, we will set it to 0.
        if "transitions" not in d:
            d["transitions"] = [0] * item_count
        # If the transition is a single value, we will convert it to a list.
        # with the same length as the presets list.
        elif not isinstance(d["transitions"], list):
            d["transitions"] = [d["transitions"]] * item_count

        # Now we can easily combine the data into a list of dictionaries.
        d["entries"] = [
            {
                "entry_id": entry_id,
                "ps": ps,
                "dur": dur,
                "transition": transition,
            }
            for entry_id, (ps, dur, transition) in enumerate(
                zip(d["ps"], d["dur"], d["transitions"], strict=True)
            )
        ]

        return d

    @classmethod
    def __post_deserialize__(cls, obj: Playlist) -> Playlist:
        """Post deserialize hook for Playlist object."""
        # If name is empty, we will replace it with the playlist ID.
        if not obj.name:
            obj.name = str(obj.playlist_id)
        return obj


@dataclass(kw_only=True)
class Device(BaseModel):
    """Object holding all information of WLED."""

    info: Info
    state: State

    effects: dict[int, Effect] = field(default_factory=dict)
    palettes: dict[int, Palette] = field(default_factory=dict)
    playlists: dict[int, Playlist] = field(default_factory=dict)
    presets: dict[int, Preset] = field(default_factory=dict)

    @staticmethod
    def _build_usermod_palettes(
        umpalcount: int,
        umpalnames: list[str],
    ) -> dict[int, dict[str, Any]]:
        """Build usermod palettes dict.

        Args:
        ----
            umpalcount: Number of usermod palettes.
            umpalnames: List of usermod palette names.

        Returns:
        -------
            A dict of usermod palette entries keyed by palette ID.

        """
        result: dict[int, dict[str, Any]] = {}
        for i in range(umpalcount):
            palette_id = WLED_USERMOD_PALETTE_ID_BASE - i
            palette_name = umpalnames[i] if i < len(umpalnames) else f"Usermod {i + 1}"
            result[palette_id] = {
                "palette_id": palette_id,
                "name": palette_name,
                "custom": False,
            }
        return result

    @staticmethod
    def _build_custom_palettes(
        cpalcount: int,
        version: AwesomeVersion | None,
    ) -> dict[int, dict[str, Any]]:
        """Build custom palettes dict.

        Args:
        ----
            cpalcount: Number of custom palettes.
            version: The firmware version (used to determine palette ID base).

        Returns:
        -------
            A dict of custom palette entries keyed by palette ID.

        """
        custom_palette_base = (
            WLED_CUSTOM_PALETTE_ID_BASE
            if version
            and get_awesome_version(f"{version.major}.{version.minor}.{version.patch}")
            >= CUSTOM_PALETTE_ID_CHANGE_VERSION
            else WLED_CUSTOM_PALETTE_ID_BASE_LEGACY
        )
        result: dict[int, dict[str, Any]] = {}
        for i in range(cpalcount):
            palette_id = custom_palette_base - i
            result[palette_id] = {
                "palette_id": palette_id,
                "name": f"Custom {i + 1}",
                "custom": True,
            }
        return result

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Device object."""
        # Extract version once at the top to avoid recomputation
        version_str = d.get("info", {}).get("ver")
        version = get_awesome_version(version_str) if version_str else None

        if version:
            # Compare base version (major.minor.patch) to allow pre-release
            # builds (e.g. 0.14.0-b1) of the minimum required version.
            base = get_awesome_version(
                f"{version.major}.{version.minor}.{version.patch}"
            )
            if base < MIN_REQUIRED_VERSION:
                msg = (
                    f"Unsupported firmware version {version_str}. "
                    f"Minimum required version is {MIN_REQUIRED_VERSION}. "
                    f"Please update your WLED device."
                )
                raise WLEDUnsupportedVersionError(msg)

        if _effects := d.get("effects"):
            d["effects"] = {
                effect_id: {"effect_id": effect_id, "name": name}
                for effect_id, name in enumerate(_effects)
                if "RSVD" not in name
            }

        if _palettes := d.get("palettes"):
            built_in_palettes = {
                palette_id: {"palette_id": palette_id, "name": name}
                for palette_id, name in enumerate(_palettes)
            }
            info = d.get("info", {})
            cpalcount = info.get("cpalcount", 0)
            custom_palettes = cls._build_custom_palettes(cpalcount, version)
            usermod_palettes = cls._build_usermod_palettes(
                info.get("umpalcount", 0), info.get("umpalnames", [])
            )
            d["palettes"] = built_in_palettes | custom_palettes | usermod_palettes
        elif _palettes is None:
            # Some less capable devices don't have palettes and
            # will return `null`.
            # Refs:
            # - https://github.com/home-assistant/core/issues/123506
            # - https://github.com/wled/WLED/issues/1974
            d["palettes"] = {}

        if _presets := d.get("presets"):
            _presets = _presets.copy()
            # The preset data contains both presets and playlists,
            # we split those out, so we can handle those correctly.
            d["presets"] = {
                int(preset_id): preset | {"preset_id": int(preset_id)}
                for preset_id, preset in _presets.items()
                if "playlist" not in preset
                or "ps" not in preset["playlist"]
                or not preset["playlist"]["ps"]
            }
            # Nobody cares about 0.
            d["presets"].pop(0, None)

            d["playlists"] = {
                int(playlist_id): playlist | {"playlist_id": int(playlist_id)}
                for playlist_id, playlist in _presets.items()
                if "playlist" in playlist
                and "ps" in playlist["playlist"]
                and playlist["playlist"]["ps"]
            }
            # Nobody cares about 0.
            d["playlists"].pop(0, None)

        return d

    def update_from_dict(self, data: dict[str, Any]) -> Device:
        """Return Device object from WLED API response.

        Args:
        ----
            data: Update the device object with the data received from a
                WLED device API.

        Returns:
        -------
            The updated Device object.

        """
        # Update info first so palette synthesis uses fresh data
        if _info := data.get("info"):
            self.info = Info.from_dict(_info)

        if _effects := data.get("effects"):
            self.effects = {
                effect_id: Effect(effect_id=effect_id, name=name)
                for effect_id, name in enumerate(_effects)
                if "RSVD" not in name
            }

        if _palettes := data.get("palettes"):
            built_in_palettes = {
                palette_id: Palette(palette_id=palette_id, name=name)
                for palette_id, name in enumerate(_palettes)
            }
            custom_palettes = self._build_custom_palettes(
                self.info.custom_palette_count, self.info.version
            )
            usermod_palettes = self._build_usermod_palettes(
                self.info.usermod_palette_count, self.info.usermod_palette_names
            )
            result = {}
            for pal_id, pal_data in (custom_palettes | usermod_palettes).items():
                result[pal_id] = Palette(**pal_data)
            self.palettes = built_in_palettes | result

        if _presets := data.get("presets"):
            # The preset data contains both presets and playlists,
            # we split those out, so we can handle those correctly.
            self.presets = {
                int(preset_id): Preset.from_dict(
                    preset | {"preset_id": int(preset_id)},
                )
                for preset_id, preset in _presets.items()
                if "playlist" not in preset
                or "ps" not in preset["playlist"]
                or not preset["playlist"]["ps"]
            }
            # Nobody cares about 0.
            self.presets.pop(0, None)

            self.playlists = {
                int(playlist_id): Playlist.from_dict(
                    playlist | {"playlist_id": int(playlist_id)}
                )
                for playlist_id, playlist in _presets.items()
                if "playlist" in playlist
                and "ps" in playlist["playlist"]
                and playlist["playlist"]["ps"]
            }
            # Nobody cares about 0.
            self.playlists.pop(0, None)

        if _state := data.get("state"):
            self.state = State.from_dict(_state)

        return self


@dataclass(frozen=True, kw_only=True)
class Releases(BaseModel):
    """Object holding WLED releases information."""

    beta: AwesomeVersion | None
    nightly: AwesomeVersion | None
    repo: str
    stable: AwesomeVersion | None
