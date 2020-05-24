"""Models for WLED."""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from .exceptions import WLEDError


@dataclass(frozen=True)
class Nightlight:
    """Object holding nightlight state in WLED."""

    duration: int
    fade: bool
    on: bool
    target_brightness: int

    @staticmethod
    def from_dict(data) -> "Nightlight":
        """Return Nightlight object from WLED API response."""
        nightlight = data.get("nl", {})
        return Nightlight(
            duration=nightlight.get("dur", 1),
            fade=nightlight.get("fade", False),
            on=nightlight.get("on", False),
            target_brightness=nightlight.get("tbri"),
        )


@dataclass(frozen=True)
class Sync:
    """Object holding sync state in WLED."""

    send: bool
    receive: bool

    @staticmethod
    def from_dict(data) -> "Sync":
        """Return Sync object from WLED API response."""
        sync = data.get("udpn", {})
        return Sync(send=sync.get("send", False), receive=sync.get("recv", False))


@dataclass(frozen=True)
class Effect:
    """Object holding an effect in WLED."""

    effect_id: int
    name: str


@dataclass(frozen=True)
class Palette:
    """Object holding an palette in WLED."""

    palette_id: int
    name: str


@dataclass(frozen=True)
class Segment:
    """Object holding segment state in WLED."""

    segment_id: int
    start: int
    stop: int
    length: int
    color_primary: Union[Tuple[int, int, int, int], Tuple[int, int, int]]
    color_secondary: Union[Tuple[int, int, int, int], Tuple[int, int, int]]
    color_tertiary: Union[Tuple[int, int, int, int], Tuple[int, int, int]]
    effect: Effect
    speed: int
    intensity: int
    palette: Palette
    selected: bool
    reverse: bool
    clones: int

    @staticmethod
    def from_dict(
        segment_id: int, data: dict, effects: List[Effect], palettes: List[Palette]
    ) -> "Segment":
        """Return Segment object from WLED API response."""
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
            segment_id=segment_id,
            start=start,
            stop=stop,
            length=length,
            color_primary=primary_color,  # type: ignore
            color_secondary=secondary_color,  # type: ignore
            color_tertiary=tertiary_color,  # type: ignore
            effect=effect,
            speed=data.get("sx", 0),
            intensity=data.get("ix", 0),
            palette=palette,
            selected=data.get("sel", False),
            reverse=data.get("reverse", False),
            clones=data.get("cln", -1),
        )


@dataclass(frozen=True)
class Leds:
    """Object holding leds info from WLED."""

    count: int
    rgbw: bool
    pin: int
    power: int
    max_power: int
    max_segments: int

    @staticmethod
    def from_dict(data: dict):
        """Return Leds object from WLED API response."""
        leds = data.get("leds", {})
        return Leds(
            count=leds.get("count", 0),
            rgbw=leds.get("rgbw", False),
            pin=leds.get("pin", 0),
            power=leds.get("pwr", 0),
            max_power=leds.get("maxpwr", 0),
            max_segments=leds.get("maxseg", 0),
        )


@dataclass(frozen=True)
class Wifi:
    """Object holding Wi-Fi information from WLED."""

    bssid: str
    channel: int
    rssi: int
    signal: int

    @staticmethod
    def from_dict(data: dict):
        """Return Wifi object form WLED API response."""
        if "wifi" not in data:
            return None
        wifi = data.get("wifi", {})
        return Wifi(
            bssid=wifi.get("bssid", "00:00:00:00:00:00"),
            channel=wifi.get("channel", 0),
            rssi=wifi.get("rssi", 0),
            signal=wifi.get("signal", 0),
        )


@dataclass(frozen=True)
class Info:
    """Object holding information from WLED."""

    architecture: str
    arduino_core_version: str
    brand: str
    build_type: str
    effect_count: int
    free_heap: int
    leds: Leds
    live: bool
    live_mode: str
    live_ip: str
    mac_address: str
    name: str
    pallet_count: int
    product: str
    udp_port: int
    uptime: int
    version_id: str
    version: str
    wifi: Optional[Wifi]

    @staticmethod
    def from_dict(data: dict):
        """Return Info object from WLED API response."""
        return Info(
            architecture=data.get("arch", "Unknown"),
            arduino_core_version=data.get("core", "Unknown").replace("_", "."),
            brand=data.get("brand", "WLED"),
            build_type=data.get("btype", "Unknown"),
            effect_count=data.get("fxcount", 0),
            free_heap=data.get("freeheap", 0),
            leds=Leds.from_dict(data),
            live=data.get("live", False),
            live_mode=data.get("lm", "Unknown"),
            live_ip=data.get("lip", "Unknown"),
            mac_address=data.get("mac", ""),
            name=data.get("name", "WLED Light"),
            pallet_count=data.get("palcount", 0),
            product=data.get("product", "DIY Light"),
            udp_port=data.get("udpport", 0),
            uptime=data.get("uptime", 0),
            version_id=data.get("vid", "Unknown"),
            version=data.get("ver", "Unknown"),
            wifi=Wifi.from_dict(data),
        )


@dataclass(frozen=True)
class State:
    """Object holding the state of WLED."""

    nightlight: Nightlight
    sync: Sync
    segments: List[Segment]
    on: bool
    brightness: int
    transition: int
    preset: int
    playlist: int

    @property
    def playlist_active(self) -> bool:
        """Return if a playlist is currently active."""
        return self.playlist == -1

    @property
    def preset_active(self) -> bool:
        """Return if a preset is currently active."""
        return self.preset == -1

    @staticmethod
    def from_dict(data, effects: List[Effect], palettes: List[Palette]) -> "State":
        """Return State object from WLED API response."""
        segments = [
            Segment.from_dict(segment_id, segment, effects, palettes)
            for segment_id, segment in enumerate(data.get("seg", []))
        ]

        return State(
            nightlight=Nightlight.from_dict(data),
            sync=Sync.from_dict(data),
            segments=segments,
            on=data.get("on", False),
            brightness=data.get("bri", 1),
            transition=data.get("transition", 0),
            preset=data.get("ps", -1),
            playlist=data.get("pl", -1),
        )


class Device:
    """Object holding all information of WLED."""

    effects: List[Effect] = []
    info: Info
    palettes: List[Palette] = []
    state: State

    def __init__(self, data: dict):
        """Initialize an empty WLED device class."""
        # Check if all elements are in the passed dict, else raise an Error
        if any(
            k not in data and data[k] is not None
            for k in ["effects", "palettes", "info", "state"]
        ):
            raise WLEDError("WLED data is incomplete, cannot construct device object")
        self.update_from_dict(data)

    def update_from_dict(self, data: dict) -> "Device":
        """Return Device object from WLED API response."""
        if "effects" in data and data["effects"]:
            effects = [
                Effect(effect_id=effect_id, name=effect)
                for effect_id, effect in enumerate(data["effects"])
            ]
            effects.sort(key=lambda x: x.name)
            self.effects = effects

        if "palettes" in data and data["palettes"]:
            palettes = [
                Palette(palette_id=palette_id, name=palette)
                for palette_id, palette in enumerate(data["palettes"])
            ]
            palettes.sort(key=lambda x: x.name)
            self.palettes = palettes

        if "info" in data and data["info"]:
            self.info = Info.from_dict(data["info"])

        if "state" in data and data["state"]:
            self.state = State.from_dict(data["state"], self.effects, self.palettes)

        return self
