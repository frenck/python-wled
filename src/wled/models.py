"""Models for WLED."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from operator import attrgetter
from typing import Any

from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializationStrategy

from .const import LightCapability, LiveDataOverride, NightlightMode, SyncGroup
from .exceptions import WLEDError
from .utils import get_awesome_version

NAME_GETTER = attrgetter("name")


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
    """Object holding an palette in WLED.

    Args:
    ----
        data: The data from the WLED device API.

    Returns:
    -------
        A palette object.

    """

    name: str
    palette_id: int


@dataclass
class Segment:
    """Object holding segment state in WLED.

    Args:
    ----
        data: The data from the WLED device API.

    Returns:
    -------
        A segment object.

    """

    brightness: int
    clones: int
    color_primary: tuple[int, int, int, int] | tuple[int, int, int]
    color_secondary: tuple[int, int, int, int] | tuple[int, int, int]
    color_tertiary: tuple[int, int, int, int] | tuple[int, int, int]
    effect: Effect
    intensity: int
    length: int
    on: bool
    palette: Palette
    reverse: bool
    segment_id: int
    selected: bool
    speed: int
    start: int
    stop: int

    @staticmethod
    # pylint: disable-next=too-many-arguments
    def from_dict(  # noqa: PLR0913
        segment_id: int,
        data: dict[str, Any],
        *,
        effects: dict[int, Effect],
        palettes: dict[int, Palette],
        state_on: bool,
        state_brightness: int,
    ) -> Segment:
        """Return Segment object from WLED API response.

        Args:
        ----
            segment_id: The ID of the LED strip segment.
            data: The segment data received from the WLED device.
            effects: An indexed dict of Effect objects.
            palettes: An indexed dict of Palette objects.
            state_on: Boolean the represents the on/off state of this segment.
            state_brightness: The brightness level of this segment.

        Returns:
        -------
            An Segment object.

        """
        start = data.get("start", 0)
        stop = data.get("stop", 0)
        length = data.get("len", (stop - start))

        colors = data.get("col", [])
        primary_color, secondary_color, tertiary_color = (0, 0, 0)
        try:
            primary_color = tuple(colors.pop(0))  # type: ignore[assignment]
            secondary_color = tuple(colors.pop(0))  # type: ignore[assignment]
            tertiary_color = tuple(colors.pop(0))  # type: ignore[assignment]
        except IndexError:
            pass

        effect = effects.get(data.get("fx", 0)) or Effect(effect_id=0, name="Unknown")
        palette = palettes.get(data.get("pal", 0)) or Palette(
            palette_id=0, name="Unknown"
        )

        return Segment(
            brightness=data.get("bri", state_brightness),
            clones=data.get("cln", -1),
            color_primary=primary_color,  # type: ignore[arg-type]
            color_secondary=secondary_color,  # type: ignore[arg-type]
            color_tertiary=tertiary_color,  # type: ignore[arg-type]
            effect=effect,
            intensity=data.get("ix", 0),
            length=length,
            on=data.get("on", state_on),
            palette=palette,
            reverse=data.get("rev", False),
            segment_id=segment_id,
            selected=data.get("sel", False),
            speed=data.get("sx", 0),
            start=start,
            stop=stop,
        )


@dataclass(frozen=True, kw_only=True)
class Leds:
    """Object holding leds info from WLED."""

    count: int = 0
    """Total LED count."""

    fps: int = 0
    """Current frames per second."""

    light_capabilities: LightCapability = field(
        default=LightCapability.NONE, metadata=field_options(alias="lc")
    )
    """Capabilities of the light."""

    max_power: int = field(default=0, metadata=field_options(alias="maxpwr"))
    """Maximum power budget in milliamps for the ABL. 0 if ABL is disabled."""

    max_segments: int = field(default=0, metadata=field_options(alias="maxseg"))
    """Maximum number of segments supported by this version."""

    power: int = field(default=0, metadata=field_options(alias="pwr"))
    """
    Current LED power usage in milliamps as determined by the ABL.
    0 if ABL is disabled.
    """

    segment_light_capabilities: list[LightCapability] = field(
        default_factory=list, metadata=field_options(alias="seglc")
    )
    """Capabilities of each segment."""


@dataclass(frozen=True, kw_only=True)
class Wifi(BaseModel):
    """Object holding Wi-Fi information from WLED.

    Args:
    ----
        data: The data from the WLED device API.

    Returns:
    -------
        A Wi-Fi object.

    """

    bssid: str = "00:00:00:00:00:00"
    channel: int = 0
    rssi: int = 0
    signal: int = 0


@dataclass(frozen=True, kw_only=True)
class Filesystem(BaseModel):
    """Object holding Filesystem information from WLED.

    Args:
    ----
        data: The data from the WLED device API.

    Returns:
    -------
        A Filesystem object.

    """

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

    architecture: str = field(default="Unknown", metadata=field_options(alias="arch"))
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

    filesystem: Filesystem | None = field(
        default=None, metadata=field_options(alias="fs")
    )
    """Info about the embedded LittleFS filesystem."""

    free_heap: int = field(default=0, metadata=field_options(alias="freeheap"))
    """Bytes of heap memory (RAM) currently available. Problematic if <10k."""

    ip: str = ""  # pylint: disable=invalid-name
    """The IP address of this instance. Empty string if not connected."""

    leds: Leds = field(default=Leds())
    """Contains info about the LED setup."""

    live_ip: str = field(default="Unknown", metadata=field_options(alias="lip"))
    """Realtime data source IP address."""

    live_mode: str = field(default="Unknown", metadata=field_options(alias="lm"))
    """Info about the realtime data source."""

    live: bool = False
    """Realtime data source active via UDP or E1.31."""

    mac_address: str = ""
    """
    The hexadecimal hardware MAC address of the light,
    lowercase and without colons.
    """

    name: str = "WLED Light"
    """Friendly name of the light. Intended for display in lists and titles."""

    pallet_count: int = 0
    """Number of palettes configured."""

    product: str = "DIY Light"
    """The product name. Always FOSS for standard installations."""

    udp_port: int = field(default=0, metadata=field_options(alias="udpport"))
    """The UDP port for realtime packets and WLED broadcast."""

    uptime: timedelta = timedelta(0)
    """Uptime of the device."""

    version: AwesomeVersion | None = field(
        default=None, metadata=field_options(alias="ver")
    )
    """Version of the WLED software."""

    version_latest_beta: AwesomeVersion | None = None
    """Latest beta version available."""

    version_latest_stable: AwesomeVersion | None = None
    """Latest stable version available."""

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

        # We can tweak the architecture name based on the filesystem size.
        if obj.filesystem is not None and obj.architecture == "esp8266":
            if obj.filesystem.total <= 256:
                obj.architecture = "esp01"
            elif obj.filesystem.total <= 512:
                obj.architecture = "esp02"

        return obj


@dataclass
class State:
    """Object holding the state of WLED."""

    brightness: int
    nightlight: Nightlight
    on: bool
    playlist: Playlist | int | None
    preset: Preset | int | None
    segments: list[Segment]
    sync: UDPSync
    transition: int
    lor: LiveDataOverride

    @property
    def playlist_active(self) -> bool:
        """Return if a playlist is currently active.

        Returns
        -------
            True if there is currently a playlist active, False otherwise.

        """
        return self.playlist == -1

    @property
    def preset_active(self) -> bool:
        """Return if a preset is currently active.

        Returns
        -------
            True is a preset is currently active, False otherwise.

        """
        return self.preset == -1

    @staticmethod
    def from_dict(
        data: dict[str, Any],
        effects: dict[int, Effect],
        palettes: dict[int, Palette],
        presets: dict[int, Preset],
        playlists: dict[int, Playlist],
    ) -> State:
        """Return State object from WLED API response.

        Args:
        ----
            data: The state response received from the WLED device API.
            effects: A dict index of effect objects.
            palettes: A dict index of palette objects.
            presets: A dict index of preset objects.
            playlists: A dict index of playlist objects.

        Returns:
        -------
            A State object.

        """
        brightness = data.get("bri", 1)
        on = data.get("on", False)
        lor = data.get("lor", 0)

        segments = [
            Segment.from_dict(
                segment_id=segment_id,
                data=segment,
                effects=effects,
                palettes=palettes,
                state_on=on,
                state_brightness=brightness,
            )
            for segment_id, segment in enumerate(data.get("seg", []))
        ]

        playlist = data.get("pl", -1)
        preset = data.get("ps", -1)
        if presets:
            playlist = playlists.get(playlist)
            preset = presets.get(preset)

        return State(
            brightness=brightness,
            nightlight=Nightlight.from_dict(data.get("nl", {})),
            on=on,
            playlist=playlist,
            preset=preset,
            segments=segments,
            sync=UDPSync.from_dict(data.get("udpn", {})),
            transition=data.get("transition", 0),
            lor=LiveDataOverride(lor),
        )


@dataclass
class Preset:
    """Object representing a WLED preset."""

    preset_id: int
    name: str
    quick_label: str | None

    on: bool
    transition: int
    main_segment: Segment | None
    segments: list[Segment]

    @staticmethod
    def from_dict(
        preset_id: int,
        data: dict[str, Any],
        effects: dict[int, Effect],
        palettes: dict[int, Palette],
    ) -> Preset:
        """Return Preset object from WLED API response.

        Args:
        ----
            preset_id: The ID of the preset.
            data: The data from the WLED device API.
            effects: A indexed dict of effect objects.
            palettes: A indexed dict of palette object.

        Returns:
        -------
            A Preset object.

        """
        segment_data = data.get("seg", [])
        if not isinstance(segment_data, list):
            # Some older versions of WLED have an single segment
            # instead of a list.
            segment_data = [segment_data]

        segments = [
            Segment.from_dict(
                segment_id=segment_id,
                data=segment,
                effects=effects,
                palettes=palettes,
                state_on=False,
                state_brightness=0,
            )
            for segment_id, segment in enumerate(segment_data)
        ]

        try:
            main_segment = segments[data.get("mainseg", 0)]
        except IndexError:
            main_segment = None

        return Preset(
            main_segment=main_segment,
            name=data.get("n", str(preset_id)),
            on=data.get("on", False),
            preset_id=preset_id,
            quick_label=data.get("ql"),
            segments=segments,
            transition=data.get("transition", 0),
        )


@dataclass
class PlaylistEntry:
    """Object representing a entry in a WLED playlist."""

    duration: int
    entry_id: int
    preset: Preset | None
    transition: int


@dataclass
class Playlist:
    """Object representing a WLED playlist."""

    end: Preset | None
    entries: list[PlaylistEntry]
    name: str
    playlist_id: int
    repeat: int
    shuffle: bool

    @staticmethod
    def from_dict(
        playlist_id: int,
        data: dict[str, Any],
        presets: dict[int, Preset],
    ) -> Playlist:
        """Return Playlist object from WLED API response.

        Args:
        ----
            playlist_id: The ID of the playlist.
            data: The data from the WLED device API.
            presets: A list of preset objects.

        Returns:
        -------
            A Playlist object.

        """
        playlist = data.get("playlist", {})
        entries_durations = playlist.get("dur", [])
        entries_presets = playlist.get("ps", [])
        entries_transitions = playlist.get("transition", [])

        entries = [
            PlaylistEntry(
                entry_id=entry_id,
                duration=entries_durations[entry_id],
                transition=entries_transitions[entry_id],
                preset=presets.get(preset_id),
            )
            for entry_id, preset_id in enumerate(entries_presets)
        ]

        end = presets.get(playlist.get("end"))

        return Playlist(
            playlist_id=playlist_id,
            shuffle=playlist.get("r", False),
            name=data.get("n", str(playlist_id)),
            repeat=playlist.get("repeat", 0),
            end=end,
            entries=entries,
        )


class Device:
    """Object holding all information of WLED."""

    effects: list[Effect]
    info: Info
    palettes: list[Palette]
    playlists: list[Playlist]
    presets: list[Preset]
    state: State

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize an empty WLED device class.

        Args:
        ----
            data: The full API response from a WLED device.

        Raises:
        ------
            WLEDError: In case the given API response is incomplete in a way
                that a Device object cannot be constructed from it.

        """
        self._indexed_effects: dict[int, Effect] = {}
        self._indexed_palettes: dict[int, Palette] = {}
        self._indexed_presets: dict[int, Preset] = {}
        self._indexed_playlists: dict[int, Playlist] = {}

        self.effects = []
        self.palettes = []
        self.playlists = []
        self.presets = []

        # Check if all elements are in the passed dict, else raise an Error
        if any(
            k not in data and data[k] is not None
            for k in ("effects", "palettes", "info", "state")
        ):
            msg = "WLED data is incomplete, cannot construct device object"
            raise WLEDError(msg)
        self.update_from_dict(data)

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
        if _effects := data.get("effects"):
            self._indexed_effects = {
                effect_id: Effect(effect_id=effect_id, name=effect)
                for effect_id, effect in enumerate(_effects)
            }
            self.effects = sorted(self._indexed_effects.values(), key=NAME_GETTER)

        if _palettes := data.get("palettes"):
            self._indexed_palettes = {
                palette_id: Palette(palette_id=palette_id, name=palette)
                for palette_id, palette in enumerate(_palettes)
            }
            self.palettes = sorted(self._indexed_palettes.values(), key=NAME_GETTER)

        if _presets := data.get("presets"):
            # The preset data contains both presets and playlists,
            # we split those out, so we can handle those correctly.
            self._indexed_presets = {
                int(preset_id): Preset.from_dict(
                    int(preset_id),
                    preset,
                    self._indexed_effects,
                    self._indexed_palettes,
                )
                for preset_id, preset in _presets.items()
                if "playlist" not in preset
                or not ("ps" in preset["playlist"] and preset["playlist"]["ps"])
            }
            # Nobody cares about 0.
            self._indexed_presets.pop(0, None)
            self.presets = sorted(self._indexed_presets.values(), key=NAME_GETTER)

            self._indexed_playlists = {
                int(playlist_id): Playlist.from_dict(
                    int(playlist_id), playlist, self._indexed_presets
                )
                for playlist_id, playlist in _presets.items()
                if "playlist" in playlist
                and "ps" in playlist["playlist"]
                and playlist["playlist"]["ps"]
            }
            # Nobody cares about 0.
            self._indexed_playlists.pop(0, None)
            self.playlists = sorted(self._indexed_playlists.values(), key=NAME_GETTER)

        if _info := data.get("info"):
            self.info = Info.from_dict(_info)

        if _state := data.get("state"):
            self.state = State.from_dict(
                _state,
                self._indexed_effects,
                self._indexed_palettes,
                self._indexed_presets,
                self._indexed_playlists,
            )

        return self
