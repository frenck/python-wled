"""Models for WLED."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from awesomeversion import AwesomeVersion, AwesomeVersionStrategy

from .exceptions import WLEDError


@dataclass
class Nightlight:
    """Object holding nightlight state in WLED."""

    duration: int
    fade: bool
    on: bool
    mode: NightlightMode
    target_brightness: int

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Nightlight:
        """Return Nightlight object from WLED API response.

        Args:
            data: The data from the WLED device API.

        Returns:
            A Nightlight object.
        """
        nightlight = data.get("nl", {})

        # Handle deprecated fade property for Nightlight
        mode = nightlight.get("mode")
        fade = nightlight.get("fade", False)
        if mode is not None:
            fade = mode != NightlightMode.INSTANT
        if mode is None:
            mode = NightlightMode.FADE if fade else NightlightMode.INSTANT

        return Nightlight(
            duration=nightlight.get("dur", 1),
            fade=fade,
            mode=NightlightMode(mode),
            on=nightlight.get("on", False),
            target_brightness=nightlight.get("tbri", 0),
        )


@dataclass
class Sync:
    """Object holding sync state in WLED."""

    receive: bool
    send: bool

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Sync:
        """Return Sync object from WLED API response.

        Args:
            data: The data from the WLED device API.

        Returns:
            A sync object.
        """
        sync = data.get("udpn", {})
        return Sync(send=sync.get("send", False), receive=sync.get("recv", False))


@dataclass
class Effect:
    """Object holding an effect in WLED."""

    effect_id: int
    name: str


@dataclass
class Palette:
    """Object holding an palette in WLED.

    Args:
        data: The data from the WLED device API.

    Returns:
        A palette object.
    """

    name: str
    palette_id: int


@dataclass
class Segment:
    """Object holding segment state in WLED.

    Args:
        data: The data from the WLED device API.

    Returns:
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
    def from_dict(
        segment_id: int,
        data: dict[str, Any],
        *,
        effects: list[Effect],
        palettes: list[Palette],
        state_on: bool,
        state_brightness: int,
    ) -> Segment:
        """Return Segment object from WLED API response.

        Args:
            segment_id: The ID of the LED strip segment.
            data: The segment data received from the WLED device.
            effects: A list of Effect objects.
            palettes: A list of Palette objects.
            state_on: Boolean the represents the on/off state of this segment.
            state_brightness: The brightness level of this segment.

        Returns:
            An Segment object.
        """
        start = data.get("start", 0)
        stop = data.get("stop", 0)
        length = data.get("len", (stop - start))

        colors = data.get("col", [])
        primary_color, secondary_color, tertiary_color = (0, 0, 0)
        try:
            primary_color = tuple(colors.pop(0))  # type: ignore
            secondary_color = tuple(colors.pop(0))  # type: ignore
            tertiary_color = tuple(colors.pop(0))  # type: ignore
        except IndexError:
            pass

        effect = next(
            (item for item in effects if item.effect_id == data.get("fx", 0)),
            Effect(effect_id=0, name="Unknown"),
        )
        palette = next(
            (item for item in palettes if item.palette_id == data.get("pal", 0)),
            Palette(palette_id=0, name="Unknown"),
        )

        return Segment(
            brightness=data.get("bri", state_brightness),
            clones=data.get("cln", -1),
            color_primary=primary_color,  # type: ignore
            color_secondary=secondary_color,  # type: ignore
            color_tertiary=tertiary_color,  # type: ignore
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

    count: int
    fps: int | None
    max_power: int
    max_segments: int
    power: int
    rgbw: bool
    wv: bool

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Leds:
        """Return Leds object from WLED API response.

        Args:
            data: The data from the WLED device API.

        Returns:
            A Leds object.
        """
        leds = data.get("leds", {})
        return Leds(
            count=leds.get("count", 0),
            fps=leds.get("fps", None),
            max_power=leds.get("maxpwr", 0),
            max_segments=leds.get("maxseg", 0),
            power=leds.get("pwr", 0),
            rgbw=leds.get("rgbw", False),
            wv=leds.get("wv", True),
        )


@dataclass
class Wifi:
    """Object holding Wi-Fi information from WLED.

    Args:
        data: The data from the WLED device API.

    Returns:
        A Wi-Fi object.
    """

    bssid: str
    channel: int
    rssi: int
    signal: int

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Wifi | None:
        """Return Wifi object form WLED API response.

        Args:
            data: The response from the WLED API.

        Returns:
            An Wifi object.
        """
        if "wifi" not in data:
            return None
        wifi = data.get("wifi", {})
        return Wifi(
            bssid=wifi.get("bssid", "00:00:00:00:00:00"),
            channel=wifi.get("channel", 0),
            rssi=wifi.get("rssi", 0),
            signal=wifi.get("signal", 0),
        )


@dataclass
class Filesystem:
    """Object holding Filesystem information from WLED.

    Args:
        data: The data from the WLED device API.

    Returns:
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
            data: The response from the WLED API.

        Returns:
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
            data: The data from the WLED device API.

        Returns:
            A info object.
        """
        if (websocket := data.get("ws")) == -1:
            websocket = None

        if version := data.get("ver"):
            version = AwesomeVersion(version)
            # If version straight is unknown, ditch it.
            if version.strategy == AwesomeVersionStrategy.UNKNOWN:
                version = None

        if version_latest_stable := data.get("version_latest_stable"):
            version_latest_stable = AwesomeVersion(version_latest_stable)

        if version_latest_beta := data.get("version_latest_beta"):
            version_latest_beta = AwesomeVersion(version_latest_beta)

        return Info(
            architecture=data.get("arch", "Unknown"),
            arduino_core_version=data.get("core", "Unknown").replace("_", "."),
            brand=data.get("brand", "WLED"),
            build_type=data.get("btype", "Unknown"),
            effect_count=data.get("fxcount", 0),
            filesystem=Filesystem.from_dict(data),
            free_heap=data.get("freeheap", 0),
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
            wifi=Wifi.from_dict(data),
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
    sync: Sync
    transition: int
    lor: Live

    @property
    def playlist_active(self) -> bool:
        """Return if a playlist is currently active.

        Returns:
            True if there is currently a playlist active, False otherwise.
        """
        return self.playlist == -1

    @property
    def preset_active(self) -> bool:
        """Return if a preset is currently active.

        Returns:
            True is a preset is currently active, False otherwise.
        """
        return self.preset == -1

    @staticmethod
    def from_dict(
        data: dict[str, Any],
        effects: list[Effect],
        palettes: list[Palette],
        presets: list[Preset],
        playlists: list[Playlist],
    ) -> State:
        """Return State object from WLED API response.

        Args:
            data: The state response received from the WLED device API.
            effects: A list of effect objects.
            palettes: A list of palette objects.
            presets: A list of preset objects.
            playlists: A list of playlist objects.

        Returns:
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
            preset = next(
                (item for item in presets if item.preset_id == data.get("ps")),
                None,
            )

            playlist = next(
                (item for item in playlists if item.playlist_id == data.get("pl")),
                None,
            )

        return State(
            brightness=brightness,
            nightlight=Nightlight.from_dict(data),
            on=on,
            playlist=playlist,
            preset=preset,
            segments=segments,
            sync=Sync.from_dict(data),
            transition=data.get("transition", 0),
            lor=Live(lor),
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
        effects: list[Effect],
        palettes: list[Palette],
    ) -> Preset:
        """Return Preset object from WLED API response.

        Args:
            preset_id: The ID of the preset.
            data: The data from the WLED device API.
            effects: A list of effect objects.
            palettes: A list of palette object.

        Returns:
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

        main_segment = next(
            (item for item in segments if item.segment_id == data.get("mainseg", 0)),
            None,
        )

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
        presets: list[Preset],
    ) -> Playlist:
        """Return Playlist object from WLED API response.

        Args:
            playlist_id: The ID of the playlist.
            data: The data from the WLED device API.
            presets: A list of preset objects.

        Returns:
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
                preset=next(
                    (item for item in presets if item.preset_id == preset_id), None
                ),
            )
            for entry_id, preset_id in enumerate(entries_presets)
        ]

        end = next(
            (item for item in presets if item.preset_id == playlist.get("end")),
            None,
        )

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

    effects: list[Effect] = []
    info: Info
    palettes: list[Palette] = []
    playlists: list[Playlist] = []
    presets: list[Preset] = []
    state: State

    def __init__(self, data: dict) -> None:
        """Initialize an empty WLED device class.

        Args:
            data: The full API response from a WLED device.

        Raises:
            WLEDError: In case the given API response is incomplete in a way
                that a Device object cannot be constructed from it.
        """
        # Check if all elements are in the passed dict, else raise an Error
        if any(
            k not in data and data[k] is not None
            for k in ("effects", "palettes", "info", "state")
        ):
            raise WLEDError("WLED data is incomplete, cannot construct device object")
        self.update_from_dict(data)

    def update_from_dict(self, data: dict) -> Device:
        """Return Device object from WLED API response.

        Args:
            data: Update the device object with the data received from a
                WLED device API.

        Returns:
            The updated Device object.
        """
        if _effects := data.get("effects"):
            effects = [
                Effect(effect_id=effect_id, name=effect)
                for effect_id, effect in enumerate(_effects)
            ]
            effects.sort(key=lambda x: x.name)
            self.effects = effects

        if _palettes := data.get("palettes"):
            palettes = [
                Palette(palette_id=palette_id, name=palette)
                for palette_id, palette in enumerate(_palettes)
            ]
            palettes.sort(key=lambda x: x.name)
            self.palettes = palettes

        if _presets := data.get("presets"):
            # The preset data contains both presets and playlists,
            # we split those out, so we can handle those correctly.

            # Nobody cares about 0.
            _presets.pop("0", None)

            presets = [
                Preset.from_dict(int(preset_id), preset, self.effects, self.palettes)
                for preset_id, preset in _presets.items()
                if "playlist" not in preset
                or not ("ps" in preset["playlist"] and preset["playlist"]["ps"])
            ]
            presets.sort(key=lambda x: x.name)
            self.presets = presets

            playlists = [
                Playlist.from_dict(int(playlist_id), playlist, self.presets)
                for playlist_id, playlist in _presets.items()
                if "playlist" in playlist
                and "ps" in playlist["playlist"]
                and playlist["playlist"]["ps"]
            ]
            playlists.sort(key=lambda x: x.name)
            self.playlists = playlists

        if _info := data.get("info"):
            self.info = Info.from_dict(_info)

        if _state := data.get("state"):
            self.state = State.from_dict(
                _state, self.effects, self.palettes, self.presets, self.playlists
            )

        return self


class Live(IntEnum):
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
