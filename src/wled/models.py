"""Models for WLED."""

from __future__ import annotations

from dataclasses import dataclass, field
from operator import attrgetter
from typing import TYPE_CHECKING, Any

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin

from .const import LightCapability, LiveDataOverride, NightlightMode, SyncGroup
from .exceptions import WLEDError
from .utils import get_awesome_version

if TYPE_CHECKING:
    from awesomeversion import AwesomeVersion

NAME_GETTER = attrgetter("name")


class BaseModel(DataClassORJSONMixin):
    """Base model for all WLED models."""

    # pylint: disable-next=too-few-public-methods
    class Config(BaseConfig):
        """Mashumaro configuration."""

        omit_none = True
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


@dataclass
class Leds:
    """Object holding leds info from WLED."""

    cct: bool
    count: int
    fps: int | None
    light_capabilities: LightCapability | None
    max_power: int
    max_segments: int
    power: int
    rgbw: bool
    wv: bool
    segment_light_capabilities: list[LightCapability] | None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Leds:
        """Return Leds object from WLED API response.

        Args:
        ----
            data: The data from the WLED device API.

        Returns:
        -------
            A Leds object.

        """
        leds = data.get("leds", {})

        light_capabilities = None
        segment_light_capabilities = None
        if "lc" in leds and "seglc" in leds:
            light_capabilities = LightCapability(leds["lc"])
            segment_light_capabilities = [
                LightCapability(item) for item in leds["seglc"]
            ]

        return Leds(
            cct=bool(leds.get("cct")),
            count=leds.get("count", 0),
            fps=leds.get("fps", None),
            light_capabilities=light_capabilities,
            max_power=leds.get("maxpwr", 0),
            max_segments=leds.get("maxseg", 0),
            power=leds.get("pwr", 0),
            rgbw=leds.get("rgbw", False),
            segment_light_capabilities=segment_light_capabilities,
            wv=bool(leds.get("wv", True)),
        )


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


@dataclass
class Filesystem:
    """Object holding Filesystem information from WLED.

    Args:
    ----
        data: The data from the WLED device API.

    Returns:
    -------
        A Filesystem object.

    """

    total: int
    used: int
    free: int
    percentage: int

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Filesystem | None:
        """Return Filesystem object form WLED API response.

        Args:
        ----
            data: The response from the WLED API.

        Returns:
        -------
            An Filesystem object.

        """
        if "fs" not in data:
            return None
        filesystem = data.get("fs", {})
        total = filesystem.get("t", 1)
        used = filesystem.get("u", 1)
        return Filesystem(
            total=total,
            used=used,
            free=(total - used),
            percentage=round((used / total) * 100),
        )


@dataclass
class Info:  # pylint: disable=too-many-instance-attributes
    """Object holding information from WLED."""

    architecture: str
    arduino_core_version: str
    brand: str
    build_type: str
    effect_count: int
    filesystem: Filesystem | None
    free_heap: int
    ip: str  # pylint: disable=invalid-name
    leds: Leds
    live_ip: str
    live_mode: str
    live: bool
    mac_address: str
    name: str
    pallet_count: int
    product: str
    udp_port: int
    uptime: int
    version_id: str
    version: AwesomeVersion | None
    version_latest_beta: AwesomeVersion | None
    version_latest_stable: AwesomeVersion | None
    websocket: int | None
    wifi: Wifi | None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Info:
        """Return Info object from WLED API response.

        Args:
        ----
            data: The data from the WLED device API.

        Returns:
        -------
            A info object.

        """
        if (websocket := data.get("ws")) == -1:
            websocket = None

        if version := data.get("ver"):
            version = get_awesome_version(version)
            if not version.valid:
                version = None

        if version_latest_stable := data.get("version_latest_stable"):
            version_latest_stable = get_awesome_version(version_latest_stable)

        if version_latest_beta := data.get("version_latest_beta"):
            version_latest_beta = get_awesome_version(version_latest_beta)

        arch = data.get("arch", "Unknown")
        if (
            (filesystem := Filesystem.from_dict(data)) is not None
            and arch == "esp8266"
            and filesystem.total
        ):
            if filesystem.total <= 256:
                arch = "esp01"
            elif filesystem.total <= 512:
                arch = "esp02"

        return Info(
            architecture=arch,
            arduino_core_version=data.get("core", "Unknown").replace("_", "."),
            brand=data.get("brand", "WLED"),
            build_type=data.get("btype", "Unknown"),
            effect_count=data.get("fxcount", 0),
            filesystem=filesystem,
            free_heap=data.get("freeheap", 0),
            ip=data.get("ip", "Unknown"),
            leds=Leds.from_dict(data),
            live_ip=data.get("lip", "Unknown"),
            live_mode=data.get("lm", "Unknown"),
            live=data.get("live", False),
            mac_address=data.get("mac", ""),
            name=data.get("name", "WLED Light"),
            pallet_count=data.get("palcount", 0),
            product=data.get("product", "DIY Light"),
            udp_port=data.get("udpport", 0),
            uptime=data.get("uptime", 0),
            version_id=data.get("vid", "Unknown"),
            version=version,
            version_latest_beta=version_latest_beta,
            version_latest_stable=version_latest_stable,
            websocket=websocket,
            wifi=Wifi.from_dict(data["wifi"]) if "wifi" in data else None,
        )


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
