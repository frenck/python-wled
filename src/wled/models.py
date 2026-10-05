"""Models for WLED."""

from __future__ import annotations

import string
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any

from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializableType, SerializationStrategy

from .const import (
    CUSTOM_PALETTE_ID_CHANGE_VERSION,
    DEFAULT_REPO,
    MIN_REQUIRED_VERSION,
    SEGMENT_LIGHT_CAPABILITIES_VERSION,
    BuildOption,
    LightCapability,
    LiveDataOverride,
    NightlightMode,
    SoundSimulationType,
    SyncGroup,
)
from .exceptions import WLEDUnsupportedVersionError
from .utils import get_awesome_version

if TYPE_CHECKING:
    from collections.abc import Sequence

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
WLED_USERMOD_PALETTE_MAX_COUNT = (
    WLED_USERMOD_PALETTE_ID_BASE - WLED_CUSTOM_PALETTE_ID_BASE
)


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
    def _deserialize(cls, value: list[Any]) -> Color:
        colors = [_parse_color(color) for color in value]
        if not colors or colors[0] is None:
            msg = f"Unusable primary color: {value!r}"
            raise ValueError(msg)

        return cls(*colors)  # ty: ignore[invalid-argument-type]


def _spread_over_entries(
    value: Any, count: int, *, default: int | None
) -> list[int | None]:
    """Spread a playlist setting over its entries, the way WLED does.

    WLED takes one value for all entries, or a list with one per entry. It
    pads a list that's too short with its last value and ignores the excess
    of a list that's too long.
    """
    if not isinstance(value, list):
        return [value if isinstance(value, int) else default] * count

    values: list[int | None] = [item for item in value if isinstance(item, int)]
    values = values[:count] or [default]
    return values + [values[-1]] * (count - len(values))


def _parse_color(
    color: Any,
) -> tuple[int, int, int, int] | tuple[int, int, int] | None:
    """Return a color in any of the forms WLED knows as RGB(W) values.

    WLED takes a list of channel values, a hex string (RRGGBB or RRGGBBWW),
    or an object with r, g, b, and w keys. It also takes "r" for a random
    color and a color temperature in Kelvin; neither is a fixed color, so
    those, like anything unknown, return None.
    """
    if isinstance(color, (list, tuple)) and 1 <= len(color) <= 4:
        if len(color) >= 3:
            # What the device reports itself, as the tuple the type promises.
            return tuple(color)

        # WLED fills in the missing channels with 0.
        return (*color, *[0] * (3 - len(color)))  # ty: ignore[invalid-return-type]

    if isinstance(color, dict):
        return _color_from_channels(color)

    if isinstance(color, str):
        # Older WLED versions, and hand-written presets, prefix a #.
        return _color_from_hex(color.removeprefix("#"))

    return None


def _color_from_channels(
    channels: dict[str, Any],
) -> tuple[int, int, int, int] | tuple[int, int, int] | None:
    """Return the color for an object of channel values, like {"r": 255}.

    WLED keeps the current value of every channel the object leaves out,
    which isn't known here; only an object that sets r, g, and b is a fixed
    color.
    """
    red, green, blue = (channels.get(channel) for channel in "rgb")
    white = channels.get("w", 0)
    if not (
        isinstance(red, int)
        and isinstance(green, int)
        and isinstance(blue, int)
        and isinstance(white, int)
    ):
        return None

    if "w" in channels:
        return (red, green, blue, white)

    return (red, green, blue)


def _color_from_hex(
    hex_color: str,
) -> tuple[int, int, int, int] | tuple[int, int, int] | None:
    """Return the color for a RRGGBB or RRGGBBWW hex string, if it is one."""
    if len(hex_color) not in (6, 8) or not all(
        character in string.hexdigits for character in hex_color
    ):
        return None

    value = int(hex_color, 16)
    if len(hex_color) == 8:
        return (value >> 24, value >> 16 & 0xFF, value >> 8 & 0xFF, value & 0xFF)

    return (value >> 16, value >> 8 & 0xFF, value & 0xFF)


# The effect controls in metadata order, by the names python-wled uses for
# them, with the labels WLED shows when the metadata doesn't name them.
_EFFECT_SLIDERS = (
    ("speed", "Effect speed"),
    ("intensity", "Effect intensity"),
    ("custom1", "Custom 1"),
    ("custom2", "Custom 2"),
    ("custom3", "Custom 3"),
)
_EFFECT_OPTIONS = (
    ("option1", "Option 1"),
    ("option2", "Option 2"),
    ("option3", "Option 3"),
)
_EFFECT_COLORS = ("Fx", "Bg", "Cs")


@dataclass(frozen=True, kw_only=True)
class EffectMetadata(SerializableType):
    """Which controls an effect uses, from WLED's effect metadata.

    WLED describes each effect in a string like `!,Duty cycle;!,!;!;01`:
    its sliders and options, colors, palette, flags, and defaults, separated
    by semicolons. This follows how WLED's own interface reads it.
    """

    sliders: dict[str, str]
    """The sliders the effect uses, like speed or custom1, with their label."""

    options: dict[str, str]
    """The options the effect uses, like option1, with their label."""

    colors: dict[int, str]
    """The color slots the effect uses, by index, with their label."""

    palette: bool
    """Whether the effect uses a palette."""

    requires_matrix: bool
    """Whether the effect needs a 2D matrix, rather than a strip."""

    audio_reactive: bool
    """Whether the effect reacts to sound."""

    defaults: dict[str, int]
    """Values that work well for the effect, by their JSON API key, like sx."""

    raw: str = ""
    """The metadata string as WLED sent it."""

    def _serialize(self) -> str:
        return self.raw

    @classmethod
    def _deserialize(cls, value: str) -> EffectMetadata:
        # Without metadata, WLED shows its default controls.
        if not value:
            return cls(
                sliders=dict(_EFFECT_SLIDERS[:2]),
                options={},
                colors=dict(enumerate(_EFFECT_COLORS)),
                palette=True,
                requires_matrix=False,
                audio_reactive=False,
                defaults={},
                raw=value,
            )

        sections = value.split(";")
        controls, colors, palette, flags, defaults = (
            sections[index] if index < len(sections) else "" for index in range(5)
        )
        labels = controls.split(",") if controls else []
        color_labels = colors.split(",") if colors else []
        palette_label = palette.split(",")[0]

        return cls(
            sliders=_used_labels(_EFFECT_SLIDERS, labels),
            options=_used_labels(_EFFECT_OPTIONS, labels[len(_EFFECT_SLIDERS) :]),
            colors={
                index: _EFFECT_COLORS[index] if label == "!" else label
                for index, label in enumerate(color_labels[: len(_EFFECT_COLORS)])
                if label
            },
            # A palette section that's empty or a plain number means no palette.
            palette=bool(palette_label) and not palette_label.isdecimal(),
            requires_matrix="2" in flags and "1" not in flags,
            audio_reactive="v" in flags or "f" in flags,
            defaults=_effect_defaults(defaults),
            raw=value,
        )


def _used_labels(
    controls: tuple[tuple[str, str], ...], labels: list[str]
) -> dict[str, str]:
    """Return the controls a metadata section uses, with their label."""
    return {
        name: default if label == "!" else label
        for (name, default), label in zip(controls, labels, strict=False)
        if label
    }


def _effect_defaults(section: str) -> dict[str, int]:
    """Return the defaults of a metadata section, like sx=24,pal=50."""
    defaults: dict[str, int] = {}
    for item in section.split(","):
        key, _, value = item.partition("=")
        if key and value.lstrip("-").isdecimal():
            defaults[key] = int(value)

    return defaults


@dataclass
class SensorReading(SerializableType):
    """Object holding a single sensor reading provided by a WLED usermod.

    Most usermods report a reading as ``[value, unit]``; some, like the PIR
    sensor switch, report a bare value without a unit.
    """

    value: Any
    unit: str | None = None

    def _serialize(self) -> Any:
        return self.value if self.unit is None else [self.value, self.unit]

    @classmethod
    def _deserialize(cls, value: Any) -> SensorReading:
        if isinstance(value, (list, tuple)):
            # Some usermods pad the unit with spaces, like " RH".
            return cls(value=value[0], unit=value[1].strip())
        return cls(value=value)


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
class AudioReactive(BaseModel):
    """Object holding the AudioReactive usermod state in WLED.

    The AudioReactive usermod reports its state in the `AudioReactive`
    key of the state object. Note that the state is reported in the `on`
    field, while changing the state is done using the `enabled` field.
    """

    on: bool = field(default=False)
    """AudioReactive currently enabled."""


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

    metadata: EffectMetadata | None = None
    """Which controls the effect uses, from WLED's effect metadata.

    None when the device didn't provide the metadata.
    """


@dataclass(frozen=True, kw_only=True)
class Palette(BaseModel):
    """Object holding a palette in WLED."""

    custom: bool = False
    name: str
    palette_id: int


# An RGB or RGBW color, with each channel between 0 and 255.
ColorTuple = tuple[int, int, int, int] | tuple[int, int, int]


@dataclass(frozen=True, kw_only=True)
class SegmentUpdate:
    """A change to apply to one segment, for `WLED.segments()`.

    Every field left at None leaves that part of the segment unchanged.
    """

    segment_id: int
    """The ID of the segment to change."""

    brightness: int | None = None
    """The brightness of the segment, between 0 and 255."""

    clones: int | None = None
    """Deprecated: WLED ignores this, and it will be removed."""

    color_primary: ColorTuple | None = None
    """The primary color of the segment."""

    color_secondary: ColorTuple | None = None
    """The secondary color of the segment."""

    color_tertiary: ColorTuple | None = None
    """The tertiary color of the segment."""

    cct: int | None = None
    """White spectrum color temperature."""

    custom1: int | None = None
    """Effect custom slider 1, between 0 and 255."""

    custom2: int | None = None
    """Effect custom slider 2, between 0 and 255."""

    custom3: int | None = None
    """Effect custom slider 3, between 0 and 31."""

    effect: int | str | None = None
    """The effect to use, by ID or by name."""

    freeze: bool | None = None
    """Freeze the current state of the segment."""

    individual: Sequence[int | Sequence[int] | ColorTuple] | None = None
    """A list of colors to use for each LED in the segment."""

    intensity: int | None = None
    """The effect intensity, between 0 and 255."""

    length: int | None = None
    """The length of the segment."""

    name: str | None = None
    """The name of the segment; an empty string clears it."""

    on: bool | None = None
    """True to turn the segment on, false to turn it off."""

    option1: bool | None = None
    """Effect option 1."""

    option2: bool | None = None
    """Effect option 2."""

    option3: bool | None = None
    """Effect option 3."""

    palette: int | str | None = None
    """The palette to use, by ID or by name."""

    reverse: bool | None = None
    """Flip the segment, so animations change direction."""

    selected: bool | None = None
    """Whether APIs without segment support change this segment too."""

    speed: int | None = None
    """The relative effect speed, between 0 and 255."""

    start: int | None = None
    """The LED the segment starts at."""

    stop: int | None = None
    """The LED the segment stops at, not included.

    Setting it at or below `start` (0 is recommended) deletes the segment.
    """

    def __post_init__(self) -> None:
        """Warn about the deprecated fields that are used."""
        if self.clones is not None:
            warnings.warn(
                "Segment clones are no longer supported by WLED and are ignored",
                DeprecationWarning,
                stacklevel=3,
            )


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
    """Deprecated: WLED no longer reports this, so it is always -1."""

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

    light_capabilities: LightCapability | None = field(
        default=None, metadata=field_options(alias="lc")
    )
    """What the LEDs in this segment can do, like RGB or a white channel.

    WLED reports this since 16.0. For older versions, the device fills it in
    from the per segment list in the LED info.
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

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Segment object."""
        # Presets can hold colors that aren't fixed, like a random "r" or a
        # Kelvin temperature. Without a usable primary color, treat the segment
        # as having no colors rather than failing on it.
        colors = d.get("col")
        if isinstance(colors, list) and (not colors or _parse_color(colors[0]) is None):
            return {key: value for key, value in d.items() if key != "col"}

        return d


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
    """The total current limit in milliamperes for the brightness limiter.

    0 when there is no total limit. Since 0.15, limits can also be set per
    LED output instead, and those aren't included here.
    """

    max_segments: int = field(default=0, metadata=field_options(alias="maxseg"))
    """Maximum number of segments supported by this version."""

    power: int = field(default=0, metadata=field_options(alias="pwr"))
    """The estimated current draw in milliamperes.

    Only estimated while the brightness limiter is in use. Since 0.15, it
    includes the controller itself (about 80 mA for an ESP8266, 120 mA for
    an ESP32), so without the limiter it's that amount instead of 0.
    """

    rgbw: bool = False
    """True if the LEDs are 4-channel (RGB + White)."""

    segment_light_capabilities: list[LightCapability] = field(
        default_factory=list, metadata=field_options(alias="seglc")
    )
    """Capabilities of each segment."""

    matrix: Matrix | None = None
    """The size of the 2D matrix the LEDs form; None for a strip."""

    wv: bool = False
    """True if the white channel slider should be displayed."""


@dataclass(frozen=True, kw_only=True)
class Matrix(BaseModel):
    """Object holding the size of a 2D LED matrix in WLED."""

    width: int = field(metadata=field_options(alias="w"))
    """The number of LEDs across."""

    height: int = field(metadata=field_options(alias="h"))
    """The number of LEDs down."""


@dataclass(kw_only=True)
class Wifi(BaseModel):
    """Object holding Wi-Fi information from WLED."""

    access_point: bool = field(default=False, metadata=field_options(alias="ap"))
    """True if the device's own access point is active."""

    bssid: str = "00:00:00:00:00:00"
    channel: int = 0

    rssi: int | None = None
    """The signal strength in dBm; None when not connected to a network."""

    signal: int | None = None
    """The signal quality in percent; None when not connected to a network."""

    @classmethod
    def __post_deserialize__(cls, obj: Wifi) -> Wifi:
        """Post deserialize hook for Wifi object."""
        # Without a Wi-Fi connection, like on a wired device, WLED reports
        # an RSSI of 0 dBm, which it then turns into a 100% signal.
        if not obj.rssi:
            obj.rssi = None
            obj.signal = None

        return obj


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
            The free percentage of the filesystem, or 0 when the device
            reports no filesystem (it reports a size of 0 when it fails to
            mount one).

        """
        if not self.total:
            return 0

        return round((self.free / self.total) * 100)

    @cached_property
    def used_percentage(self) -> int:
        """Return the used percentage of the filesystem.

        Returns
        -------
            The used percentage of the filesystem, or 0 when the device
            reports no filesystem (it reports a size of 0 when it fails to
            mount one).

        """
        if not self.total:
            return 0

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

    build_options: BuildOption = field(
        default=BuildOption.NONE, metadata=field_options(alias="opt")
    )
    """The features this build was compiled with, like OTA updates."""

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

    usermod_palette_names: list[str] | None = field(
        default=None, metadata=field_options(alias="umpalnames")
    )
    """Names of usermod palettes."""

    product: str = "DIY Light"
    """The product name. Always FOSS for standard installations."""

    repo: str = DEFAULT_REPO
    """GitHub repository in 'owner/repository' format."""

    release: str | None = None
    """The release name of the firmware build.

    When present, used to determine the correct firmware filename during
    upgrades (e.g. "ESP32", "ESP32_Ethernet", "ESP8266_160").
    """

    sync_toggle_receive: bool = field(
        default=False, metadata=field_options(alias="str")
    )
    """If true, UI toggling also toggles sync receive."""

    sensor: dict[str, SensorReading] | None = None
    """Optional additional sensors provided by usermods."""

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
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Info object."""
        sensor = d.get("sensor")
        if not isinstance(sensor, dict):
            # Remove malformed top-level sensor object
            return {key: value for key, value in d.items() if key != "sensor"}

        # Since usermods are free to put anything in the sensor field, only keep
        # entries that are a [value, unit] pair with a string unit, or a bare
        # value without a unit (like the PIR sensor switch reports motion).
        return d | {
            "sensor": {
                name: entry
                for name, entry in sensor.items()
                if (
                    isinstance(entry, (list, tuple))
                    and len(entry) == 2
                    and isinstance(entry[1], str)
                )
                or isinstance(entry, (bool, int, float, str))
            }
        }

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

    audio_reactive: AudioReactive | None = field(
        default=None, metadata=field_options(alias="AudioReactive")
    )
    """AudioReactive usermod state.

    `None` if the AudioReactive usermod is not installed on the device.
    """

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
        # Key the segments by the ID the device reports. WLED leaves inactive
        # segments out of the list, so once a segment in the middle is deleted,
        # the position in the list no longer matches the ID. The position is
        # only a fallback for a segment that doesn't report its ID.
        segments: dict[int, dict[str, Any]] = {}
        for position, segment in enumerate(d.get("seg", [])):
            segment_id = segment.get("id")
            if not isinstance(segment_id, int):
                segment_id = position
            segments[segment_id] = segment | {"id": segment_id}

        return d | {"seg": segments}

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
            return d | {"seg": [d["seg"]]}

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
    transition: int | None = None
    """The transition to this entry, in units of 100ms.

    None when the playlist doesn't set one; the device then uses its default
    transition.
    """


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
        d = d | d["playlist"]
        # The presets, durations, and transitions are separate lists in the
        # playlist data; combine them into one entry per preset.
        presets = d.get("ps", [])
        durations = _spread_over_entries(d.get("dur"), len(presets), default=100)
        # Without a transition, WLED uses its own default transition.
        transitions = _spread_over_entries(
            d.get("transition"), len(presets), default=None
        )

        d["entries"] = [
            {
                "entry_id": entry_id,
                "ps": preset,
                "dur": duration,
                "transition": transition,
            }
            for entry_id, (preset, duration, transition) in enumerate(
                zip(presets, durations, transitions, strict=True)
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
        umpalnames: list[str] | None,
        version: AwesomeVersion | None,
    ) -> dict[int, dict[str, Any]]:
        """Build usermod palettes dict.

        Args:
        ----
            umpalcount: Number of usermod palettes.
            umpalnames: List of usermod palette names (None if not present in JSON).
            version: The firmware version (gating feature to >= 16.0.0).

        Returns:
        -------
            A dict of usermod palette entries keyed by palette ID.

        """
        is_v16_plus = (
            version is not None
            and get_awesome_version(f"{version.major}.{version.minor}.{version.patch}")
            >= CUSTOM_PALETTE_ID_CHANGE_VERSION
        )
        if not is_v16_plus:
            return {}
        names = umpalnames or []
        result: dict[int, dict[str, Any]] = {}
        safe_count = min(umpalcount, WLED_USERMOD_PALETTE_MAX_COUNT)
        for i in range(safe_count):
            palette_id = WLED_USERMOD_PALETTE_ID_BASE - i
            palette_name = names[i] if i < len(names) else f"Usermod {i + 1}"
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

    # Both the initial deserialize and update_from_dict() turn the raw lists
    # from the device into these dicts, so the rules live in one place.

    @staticmethod
    def _effects_from_names(
        names: list[Any], metadata: Any = None
    ) -> dict[int, dict[str, Any]]:
        """Return the effects by ID, skipping placeholders and junk.

        Effects named RSVD are placeholders in the firmware. Names that
        aren't strings have been seen when a device cuts off its response.
        The effect metadata, when the device provided it, is a list in the
        same order as the names.
        """
        if not isinstance(metadata, list):
            metadata = []
        elif metadata:
            # Solid has no metadata in the firmware; WLED's own interface
            # fills it in as using the primary color only.
            metadata = [";!;", *metadata[1:]]

        effects: dict[int, dict[str, Any]] = {}
        for effect_id, name in enumerate(names):
            if not isinstance(name, str) or "RSVD" in name:
                continue

            effects[effect_id] = {"effect_id": effect_id, "name": name}
            if effect_id < len(metadata) and isinstance(metadata[effect_id], str):
                effects[effect_id]["metadata"] = metadata[effect_id]

        return effects

    @classmethod
    def _palettes_from_names(  # pylint: disable=too-many-arguments
        cls,
        names: list[Any],
        *,
        custom_count: int,
        usermod_count: int,
        usermod_names: list[str] | None,
        version: AwesomeVersion | None,
    ) -> dict[int, dict[str, Any]]:
        """Return all palettes by ID: built-in, custom, and usermod ones."""
        built_in_palettes = {
            palette_id: {"palette_id": palette_id, "name": name}
            for palette_id, name in enumerate(names)
            if isinstance(name, str)
        }
        custom_palettes = cls._build_custom_palettes(custom_count, version)
        usermod_palettes = cls._build_usermod_palettes(
            usermod_count, usermod_names, version
        )
        return built_in_palettes | custom_palettes | usermod_palettes

    @staticmethod
    def _split_presets(
        raw: dict[str, Any],
    ) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
        """Split the preset data into presets and playlists, by ID.

        WLED keeps both in the same file; a playlist is a preset with a
        non-empty list of presets to play. ID 0 is a placeholder.
        """
        presets: dict[int, dict[str, Any]] = {}
        playlists: dict[int, dict[str, Any]] = {}
        for raw_id, entry in raw.items():
            # WLED only writes numbered presets, but the file can be edited by
            # hand or by other tools. Anything else isn't a preset.
            try:
                entry_id = int(raw_id)
            except (TypeError, ValueError):
                continue

            if not entry_id or not isinstance(entry, dict):
                continue

            # Anything other than a dict with presets in it, like an empty
            # list, leaves the entry a plain preset.
            playlist = entry.get("playlist")
            if isinstance(playlist, dict) and playlist.get("ps"):
                model, target = Playlist, playlists
                item = entry | {"playlist_id": entry_id}
            else:
                model, target = Preset, presets
                item = entry | {"preset_id": entry_id}

            # One entry that can't be read, like a playlist with a single
            # number instead of a list of presets, shouldn't take the others
            # down with it.
            try:
                model.from_dict(item)
            except (LookupError, TypeError, ValueError):
                continue

            target[entry_id] = item

        return presets, playlists

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for Device object."""
        # Work on a copy, so the data handed in stays as it was.
        d = dict(d)

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
            d["effects"] = cls._effects_from_names(_effects, d.get("fxdata"))

        if _palettes := d.get("palettes"):
            info = d.get("info", {})
            d["palettes"] = cls._palettes_from_names(
                _palettes,
                custom_count=info.get("cpalcount", 0),
                usermod_count=info.get("umpalcount", 0),
                usermod_names=info.get("umpalnames"),
                version=version,
            )
        elif _palettes is None:
            # Some less capable devices don't have palettes and
            # will return `null`.
            # Refs:
            # - https://github.com/home-assistant/core/issues/123506
            # - https://github.com/wled/WLED/issues/1974
            d["palettes"] = {}

        if _presets := d.get("presets"):
            d["presets"], d["playlists"] = cls._split_presets(_presets)

        return d

    @classmethod
    def __post_deserialize__(cls, obj: Device) -> Device:
        """Post deserialize hook for Device object."""
        obj._fill_segment_light_capabilities()  # pylint: disable=protected-access
        return obj

    def _fill_segment_light_capabilities(self) -> None:
        """Fill in the light capabilities of segments on WLED before 16.0.

        Older versions only list them in the LED info, one entry for each
        active segment, in the same order as the segments in the state. They
        are taken from there on every update, so they follow the LED info
        when it changes on its own.
        """
        version = self.info.version
        if (
            version is not None
            and get_awesome_version(f"{version.major}.{version.minor}.{version.patch}")
            >= SEGMENT_LIGHT_CAPABILITIES_VERSION
        ):
            return

        # A segment the LED info has no entry for is unknown, also when it
        # had one before.
        capabilities = self.info.leds.segment_light_capabilities
        for position, segment in enumerate(self.state.segments.values()):
            segment.light_capabilities = (
                capabilities[position] if position < len(capabilities) else None
            )

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
            effects = self._effects_from_names(_effects, data.get("fxdata"))
            self.effects = {
                effect_id: Effect.from_dict(effect)
                for effect_id, effect in effects.items()
            }

        if _palettes := data.get("palettes"):
            palettes = self._palettes_from_names(
                _palettes,
                custom_count=self.info.custom_palette_count,
                usermod_count=self.info.usermod_palette_count,
                usermod_names=self.info.usermod_palette_names,
                version=self.info.version,
            )
            self.palettes = {
                palette_id: Palette(**palette)
                for palette_id, palette in palettes.items()
            }

        # An empty presets file means there are no presets (anymore).
        if (_presets := data.get("presets")) is not None:
            presets, playlists = self._split_presets(_presets)
            self.presets = {
                preset_id: Preset.from_dict(preset)
                for preset_id, preset in presets.items()
            }
            self.playlists = {
                playlist_id: Playlist.from_dict(playlist)
                for playlist_id, playlist in playlists.items()
            }

        if _state := data.get("state"):
            self.state = State.from_dict(_state)

        self._fill_segment_light_capabilities()
        return self


@dataclass(frozen=True, kw_only=True)
class Releases(BaseModel):
    """Object holding WLED releases information."""

    beta: AwesomeVersion | None
    nightly: AwesomeVersion | None
    repo: str
    stable: AwesomeVersion | None
