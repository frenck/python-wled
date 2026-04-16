"""Tests for `wled.models` and related utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from awesomeversion import AwesomeVersion
from syrupy.assertion import SnapshotAssertion

from wled import Device, Playlist, Preset, Releases
from wled.exceptions import WLEDUnsupportedVersionError
from wled.models import (
    AwesomeVersionSerializationStrategy,
    Color,
    Filesystem,
    Info,
    State,
    TimedeltaSerializationStrategy,
    TimestampSerializationStrategy,
)
from wled.utils import get_awesome_version

from .conftest import full_device_data, load_fixture_json

# =========================================================================
# Helper functions
# =========================================================================


def _base_info(**overrides: Any) -> dict[str, Any]:
    """Return a minimal info dict with optional overrides."""
    info = {
        "ver": "0.14.0",
        "vid": "2312080",
        "leds": {
            "count": 30,
            "fps": 30,
            "maxpwr": 850,
            "maxseg": 16,
            "pwr": 0,
            "lc": 7,
            "seglc": [7],
        },
        "name": "WLED",
        "udpport": 21324,
        "live": False,
        "lm": "",
        "lip": "",
        "ws": 0,
        "fxcount": 187,
        "palcount": 71,
        "wifi": {
            "bssid": "AA:BB:CC:DD:EE:FF",
            "rssi": -62,
            "signal": 76,
            "channel": 11,
        },
        "fs": {"u": 12, "t": 64, "pmt": 1702050803.0},
        "arch": "esp32",
        "core": "v3.3.6-16",
        "freeheap": 116864,
        "uptime": 32489,
        "mac": "aabbccddeeff",
        "ip": "192.168.1.100",
    }
    info.update(overrides)
    return info


def _base_state(**overrides: Any) -> dict[str, Any]:
    """Return a minimal state dict."""
    state = {
        "on": True,
        "bri": 128,
        "transition": 7,
        "ps": -1,
        "pl": -1,
        "nl": {"on": False, "dur": 60, "mode": 1, "tbri": 0},
        "udpn": {"send": False, "recv": True, "sgrp": 1, "rgrp": 1},
        "lor": 0,
        "seg": [
            {
                "id": 0,
                "start": 0,
                "stop": 30,
                "len": 30,
                "col": [[255, 159, 0], [0, 0, 0], [0, 0, 0]],
                "fx": 0,
                "sx": 128,
                "ix": 128,
                "pal": 0,
                "sel": True,
                "rev": False,
                "on": True,
                "bri": 255,
                "cln": -1,
                "cct": 127,
            }
        ],
    }
    state.update(overrides)
    return state


# =========================================================================
# Serialization strategies
# =========================================================================


def test_awesome_version_serialize_none() -> None:
    """Test serializing None returns empty string."""
    strategy = AwesomeVersionSerializationStrategy()
    assert strategy.serialize(None) == ""


def test_awesome_version_serialize_version() -> None:
    """Test serializing an AwesomeVersion."""
    strategy = AwesomeVersionSerializationStrategy()
    version = AwesomeVersion("0.14.0")
    assert strategy.serialize(version) == "0.14.0"


def test_awesome_version_deserialize_valid() -> None:
    """Test deserializing a valid version string."""
    strategy = AwesomeVersionSerializationStrategy()
    result = strategy.deserialize("0.14.0")
    assert result is not None
    assert isinstance(result, AwesomeVersion)
    assert str(result) == "0.14.0"


def test_awesome_version_deserialize_invalid() -> None:
    """Test deserializing an invalid version string returns None."""
    strategy = AwesomeVersionSerializationStrategy()
    result = strategy.deserialize("")
    assert result is None


def test_timedelta_serialize() -> None:
    """Test serializing a timedelta to seconds."""
    strategy = TimedeltaSerializationStrategy()
    td = timedelta(hours=1, minutes=30)
    assert strategy.serialize(td) == 5400


def test_timedelta_deserialize() -> None:
    """Test deserializing seconds to timedelta."""
    strategy = TimedeltaSerializationStrategy()
    result = strategy.deserialize(3600)
    assert result == timedelta(seconds=3600)


def test_timestamp_serialize() -> None:
    """Test serializing a datetime to timestamp."""
    strategy = TimestampSerializationStrategy()
    dt = datetime(2023, 12, 8, 16, 33, 23, tzinfo=UTC)
    result = strategy.serialize(dt)
    assert result == dt.timestamp()


def test_timestamp_deserialize() -> None:
    """Test deserializing a timestamp to datetime."""
    strategy = TimestampSerializationStrategy()
    result = strategy.deserialize(1702050803.0)
    assert isinstance(result, datetime)
    assert result.tzinfo == UTC


# =========================================================================
# Color model
# =========================================================================


def test_color_serialize_primary_only() -> None:
    """Test serializing with only primary color."""
    color = Color(primary=(255, 0, 0))
    result = color._serialize()  # pylint: disable=protected-access
    assert result == [(255, 0, 0)]


def test_color_serialize_primary_and_secondary() -> None:
    """Test serializing with primary and secondary colors."""
    color = Color(primary=(255, 0, 0), secondary=(0, 255, 0))
    result = color._serialize()  # pylint: disable=protected-access
    assert result == [(255, 0, 0), (0, 255, 0)]


def test_color_serialize_all_three_colors() -> None:
    """Test serializing with all three colors."""
    color = Color(primary=(255, 0, 0), secondary=(0, 255, 0), tertiary=(0, 0, 255))
    result = color._serialize()  # pylint: disable=protected-access
    assert result == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


def test_color_serialize_tertiary_without_secondary() -> None:
    """Test serializing with tertiary but no secondary omits tertiary."""
    color = Color(primary=(255, 0, 0), tertiary=(0, 0, 255))
    result = color._serialize()  # pylint: disable=protected-access
    assert result == [(255, 0, 0)]


def test_color_deserialize_tuple_colors() -> None:
    """Test deserializing tuple colors."""
    color = Color._deserialize([(255, 0, 0), (0, 255, 0), (0, 0, 255)])  # pylint: disable=protected-access
    assert color.primary == (255, 0, 0)
    assert color.secondary == (0, 255, 0)
    assert color.tertiary == (0, 0, 255)


def test_color_deserialize_hex_color() -> None:
    """Test deserializing hex color strings."""
    color = Color._deserialize(["#FF0000", "#00FF00"])  # pylint: disable=protected-access
    assert color.primary == (255, 0, 0)
    assert color.secondary == (0, 255, 0)


def test_color_deserialize_mixed() -> None:
    """Test deserializing mixed hex and tuple colors."""
    color = Color._deserialize(["#FF9900", (0, 0, 0)])  # pylint: disable=protected-access
    assert color.primary == (255, 153, 0)
    assert color.secondary == (0, 0, 0)


# =========================================================================
# Filesystem model
# =========================================================================


def test_filesystem_free_space() -> None:
    """Test free space calculation."""
    fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
    assert fs.free == 52


def test_filesystem_free_percentage() -> None:
    """Test free percentage calculation."""
    fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
    assert fs.free_percentage == 81


def test_filesystem_used_percentage() -> None:
    """Test used percentage calculation."""
    fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
    assert fs.used_percentage == 19


# =========================================================================
# Info model
# =========================================================================


def test_info_websocket_minus_one_becomes_none() -> None:
    """Test websocket value of -1 is converted to None."""
    info = Info.from_dict(_base_info(ws=-1))
    assert info.websocket is None


def test_info_websocket_zero() -> None:
    """Test websocket value of 0 stays 0."""
    info = Info.from_dict(_base_info(ws=0))
    assert info.websocket == 0


def test_info_architecture_lowered() -> None:
    """Test architecture is lowercased."""
    info = Info.from_dict(_base_info(arch="ESP32"))
    assert info.architecture == "esp32"


def test_info_esp01_detection() -> None:
    """Test esp01 detection based on filesystem total <= 256."""
    info = Info.from_dict(
        _base_info(
            arch="esp8266",
            fs={"u": 10, "t": 256, "pmt": 1702050803.0},
        )
    )
    assert info.architecture == "esp01"


def test_info_esp02_detection() -> None:
    """Test esp02 detection based on filesystem total <= 512."""
    info = Info.from_dict(
        _base_info(
            arch="esp8266",
            fs={"u": 10, "t": 512, "pmt": 1702050803.0},
        )
    )
    assert info.architecture == "esp02"


def test_info_esp8266_large_fs_stays_esp8266() -> None:
    """Test esp8266 with large fs stays as esp8266."""
    info = Info.from_dict(
        _base_info(
            arch="esp8266",
            fs={"u": 10, "t": 1024, "pmt": 1702050803.0},
        )
    )
    assert info.architecture == "esp8266"


def test_info_uptime_as_timedelta() -> None:
    """Test uptime is deserialized as timedelta."""
    info = Info.from_dict(_base_info(uptime=32489))
    assert info.uptime == timedelta(seconds=32489)


def test_info_version_deserialized() -> None:
    """Test version is deserialized as AwesomeVersion."""
    info = Info.from_dict(_base_info(ver="0.14.0"))
    assert info.version is not None
    assert str(info.version) == "0.14.0"


# =========================================================================
# State model
# =========================================================================


def test_state_segment_indexing() -> None:
    """Test segments are converted from list to indexed dict."""
    state = State.from_dict(_base_state())
    assert isinstance(state.segments, dict)
    assert 0 in state.segments
    assert state.segments[0].segment_id == 0


def test_state_multiple_segments_indexed() -> None:
    """Test multiple segments get proper indices."""
    seg1 = {
        "start": 0,
        "stop": 15,
        "len": 15,
        "col": [[255, 0, 0]],
        "fx": 0,
        "sx": 128,
        "ix": 128,
        "pal": 0,
        "sel": True,
        "rev": False,
        "on": True,
        "bri": 255,
        "cln": -1,
        "cct": 127,
    }
    seg2 = {
        "start": 15,
        "stop": 30,
        "len": 15,
        "col": [[0, 255, 0]],
        "fx": 1,
        "sx": 64,
        "ix": 64,
        "pal": 1,
        "sel": False,
        "rev": True,
        "on": False,
        "bri": 128,
        "cln": -1,
        "cct": 0,
    }
    state = State.from_dict(_base_state(seg=[seg1, seg2]))
    assert 0 in state.segments
    assert 1 in state.segments
    assert state.segments[0].segment_id == 0
    assert state.segments[1].segment_id == 1


def test_state_playlist_id_minus_one_becomes_none() -> None:
    """Test playlist_id -1 is converted to None."""
    state = State.from_dict(_base_state(pl=-1))
    assert state.playlist_id is None


def test_state_preset_id_minus_one_becomes_none() -> None:
    """Test preset_id -1 is converted to None."""
    state = State.from_dict(_base_state(ps=-1))
    assert state.preset_id is None


def test_state_playlist_id_positive() -> None:
    """Test positive playlist_id is kept."""
    state = State.from_dict(_base_state(pl=5))
    assert state.playlist_id == 5


def test_state_preset_id_positive() -> None:
    """Test positive preset_id is kept."""
    state = State.from_dict(_base_state(ps=3))
    assert state.preset_id == 3


# =========================================================================
# Preset model
# =========================================================================


def test_preset_basic() -> None:
    """Test basic preset deserialization."""
    preset = Preset.from_dict(
        {
            "preset_id": 1,
            "n": "My Preset",
            "on": True,
            "bri": 128,
            "transition": 7,
            "mainseg": 0,
            "seg": [{"col": [[255, 0, 0]]}],
        }
    )
    assert preset.preset_id == 1
    assert preset.name == "My Preset"
    assert preset.on is True


def test_preset_empty_name_uses_id() -> None:
    """Test preset with empty name defaults to preset ID as string."""
    preset = Preset.from_dict(
        {
            "preset_id": 42,
            "n": "",
            "on": False,
        }
    )
    assert preset.name == "42"


def test_preset_no_name_uses_id() -> None:
    """Test preset without name key defaults to preset ID as string."""
    preset = Preset.from_dict(
        {
            "preset_id": 7,
        }
    )
    assert preset.name == "7"


def test_preset_seg_single_to_list() -> None:
    """Test single segment dict is wrapped in a list."""
    preset = Preset.from_dict(
        {
            "preset_id": 1,
            "n": "Test",
            "seg": {"col": [[255, 0, 0]]},
        }
    )
    assert isinstance(preset.segments, list)
    assert len(preset.segments) == 1


# =========================================================================
# Playlist model
# =========================================================================


def test_playlist_basic() -> None:
    """Test basic playlist deserialization."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 2,
            "n": "My Playlist",
            "playlist": {
                "ps": [1, 2],
                "dur": [100, 200],
                "transitions": [10, 20],
                "end": 0,
                "r": False,
                "repeat": 3,
            },
        }
    )
    assert playlist.playlist_id == 2
    assert playlist.name == "My Playlist"
    assert len(playlist.entries) == 2
    assert playlist.entries[0].preset == 1
    assert playlist.entries[0].duration == 100
    assert playlist.entries[0].transition == 10
    assert playlist.entries[1].preset == 2
    assert playlist.entries[1].duration == 200
    assert playlist.entries[1].transition == 20
    assert playlist.repeat == 3


def test_playlist_single_duration() -> None:
    """Test playlist with single duration value (non-list)."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 3,
            "n": "Single Dur",
            "playlist": {
                "ps": [1, 2, 3],
                "dur": 50,
                "transitions": [10, 20, 30],
                "end": 0,
                "r": False,
            },
        }
    )
    assert len(playlist.entries) == 3
    assert all(e.duration == 50 for e in playlist.entries)


def test_playlist_single_transition() -> None:
    """Test playlist with single transition value (non-list)."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 4,
            "n": "Single Trans",
            "playlist": {
                "ps": [1, 2],
                "dur": [100, 200],
                "transitions": 5,
                "end": 0,
                "r": True,
            },
        }
    )
    assert len(playlist.entries) == 2
    assert all(e.transition == 5 for e in playlist.entries)


def test_playlist_no_transitions() -> None:
    """Test playlist without transitions key defaults to zero."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 5,
            "n": "No Trans",
            "playlist": {
                "ps": [1],
                "dur": [100],
                "end": 0,
                "r": False,
            },
        }
    )
    assert len(playlist.entries) == 1
    assert playlist.entries[0].transition == 0


def test_playlist_empty_name_uses_id() -> None:
    """Test playlist with empty name defaults to playlist ID as string."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 10,
            "n": "",
            "playlist": {
                "ps": [1],
                "dur": [100],
                "end": 0,
                "r": False,
            },
        }
    )
    assert playlist.name == "10"


def test_playlist_no_name_uses_id() -> None:
    """Test playlist without name key defaults to playlist ID as string."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 11,
            "playlist": {
                "ps": [1],
                "dur": [100],
                "end": 0,
                "r": False,
            },
        }
    )
    assert playlist.name == "11"


# =========================================================================
# Device model
# =========================================================================


def test_device_from_dict_full() -> None:
    """Test full Device deserialization from dict."""
    data = full_device_data()
    device = Device.from_dict(data)

    # Info
    assert device.info.architecture == "esp32"
    assert device.info.name == "WLED"
    assert device.info.version is not None
    assert str(device.info.version) == "0.14.0"
    assert device.info.websocket == 0

    # State
    assert device.state.on is True
    assert device.state.brightness == 128
    assert device.state.playlist_id is None
    assert device.state.preset_id is None
    assert 0 in device.state.segments

    # Effects
    assert len(device.effects) == 3
    assert device.effects[0].name == "Solid"
    assert device.effects[1].name == "Blink"
    assert device.effects[2].name == "Breathe"

    # Palettes
    assert len(device.palettes) == 3
    assert device.palettes[0].name == "Default"

    # Presets (key 0 is dropped, key 2 has a playlist so excluded)
    assert 1 in device.presets
    assert device.presets[1].name == "My Preset"
    assert 0 not in device.presets

    # Playlists
    assert 2 in device.playlists
    assert device.playlists[2].name == "My Playlist"


def test_device_unsupported_version() -> None:
    """Test that unsupported firmware version raises error."""
    data = full_device_data()
    data["info"]["ver"] = "0.8.0"
    with pytest.raises(WLEDUnsupportedVersionError):
        Device.from_dict(data)


def test_device_null_palettes() -> None:
    """Test that None palettes results in empty dict."""
    data = full_device_data()
    data["palettes"] = None
    device = Device.from_dict(data)
    assert device.palettes == {}


def test_device_no_effects() -> None:
    """Test device with no effects list."""
    data = full_device_data()
    data.pop("effects", None)
    device = Device.from_dict(data)
    assert device.effects == {}


def test_device_no_palettes_key() -> None:
    """Test device with no palettes key at all defaults to empty dict."""
    data = full_device_data()
    data.pop("palettes", None)
    device = Device.from_dict(data)
    assert device.palettes == {}


def test_device_no_presets() -> None:
    """Test device with no presets."""
    data = full_device_data()
    data.pop("presets", None)
    device = Device.from_dict(data)
    assert device.presets == {}
    assert device.playlists == {}


def test_device_update_from_dict_effects() -> None:
    """Test update_from_dict updates effects."""
    data = full_device_data()
    device = Device.from_dict(data)
    device.update_from_dict({"effects": ["NewEffect1", "NewEffect2"]})
    assert len(device.effects) == 2
    assert device.effects[0].name == "NewEffect1"


def test_device_update_from_dict_palettes() -> None:
    """Test update_from_dict updates palettes."""
    data = full_device_data()
    device = Device.from_dict(data)
    device.update_from_dict({"palettes": ["NewPalette"]})
    assert len(device.palettes) == 1
    assert device.palettes[0].name == "NewPalette"


def test_device_update_from_dict_presets() -> None:
    """Test update_from_dict updates presets and playlists."""
    data = full_device_data()
    device = Device.from_dict(data)
    new_presets = {
        "0": {},
        "1": {"n": "Updated Preset", "on": True},
        "3": {
            "n": "New Playlist",
            "playlist": {
                "ps": [1],
                "dur": [50],
                "end": 0,
                "r": False,
            },
        },
    }
    device.update_from_dict({"presets": new_presets})
    assert 1 in device.presets
    assert device.presets[1].name == "Updated Preset"
    assert 0 not in device.presets
    assert 3 in device.playlists
    assert device.playlists[3].name == "New Playlist"


def test_device_update_from_dict_info() -> None:
    """Test update_from_dict updates info."""
    data = full_device_data()
    device = Device.from_dict(data)
    new_info = load_fixture_json("wled")["info"]
    new_info["name"] = "Updated WLED"
    device.update_from_dict({"info": new_info})
    assert device.info.name == "Updated WLED"


def test_device_update_from_dict_state() -> None:
    """Test update_from_dict updates state."""
    data = full_device_data()
    device = Device.from_dict(data)
    new_state = load_fixture_json("wled")["state"]
    new_state["on"] = False
    device.update_from_dict({"state": new_state})
    assert device.state.on is False


def test_device_update_from_dict_returns_self() -> None:
    """Test update_from_dict returns the device itself."""
    data = full_device_data()
    device = Device.from_dict(data)
    result = device.update_from_dict({})
    assert result is device


def test_device_preset_with_empty_playlist_ps() -> None:
    """Test that a preset with empty playlist ps list is treated as preset."""
    data = full_device_data()
    data["presets"]["3"] = {
        "n": "Empty PL",
        "playlist": {"ps": [], "dur": [], "end": 0, "r": False},
    }
    device = Device.from_dict(data)
    assert 3 in device.presets
    assert 3 not in device.playlists


def test_device_update_from_dict_preset_with_empty_playlist_ps() -> None:
    """Test update_from_dict handles preset with empty playlist ps."""
    data = full_device_data()
    device = Device.from_dict(data)
    new_presets = {
        "0": {},
        "5": {
            "n": "Broken PL",
            "playlist": {"ps": [], "dur": [], "end": 0, "r": False},
        },
    }
    device.update_from_dict({"presets": new_presets})
    assert 5 in device.presets
    assert 5 not in device.playlists


# =========================================================================
# Utils
# =========================================================================


def test_get_awesome_version() -> None:
    """Test get_awesome_version returns AwesomeVersion."""
    version = get_awesome_version("0.14.0")
    assert isinstance(version, AwesomeVersion)
    assert str(version) == "0.14.0"


def test_get_awesome_version_cached() -> None:
    """Test get_awesome_version returns cached result."""
    v1 = get_awesome_version("1.2.3")
    v2 = get_awesome_version("1.2.3")
    assert v1 is v2


# =========================================================================
# Releases model
# =========================================================================


def test_releases_from_dict() -> None:
    """Test Releases deserialization."""
    releases = Releases.from_dict({"stable": "0.14.0", "beta": "0.15.0b1"})
    assert releases.stable is not None
    assert releases.beta is not None


def test_releases_none_values() -> None:
    """Test Releases with None values."""
    releases = Releases.from_dict({"stable": "", "beta": ""})
    assert releases.stable is None
    assert releases.beta is None


# =========================================================================
# Real-world fixture snapshot tests
# =========================================================================


@pytest.mark.parametrize(
    "fixture",
    [
        "rgb",
        "rgbw",
        "cct",
        "rgb_websocket",
        "rgb_single_segment",
    ],
)
def test_device_fixture(
    fixture: str,
    snapshot: SnapshotAssertion,
) -> None:
    """Test Device parsing against real-world WLED responses."""
    data = load_fixture_json(fixture)
    data["presets"] = {}
    device = Device.from_dict(data)
    assert device == snapshot
