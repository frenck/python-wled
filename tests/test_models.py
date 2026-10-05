"""Tests for `wled.models` and related utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from awesomeversion import AwesomeVersion
from syrupy.assertion import SnapshotAssertion

from wled import Device, Playlist, Preset, Releases
from wled.const import DEFAULT_REPO, BuildOption, LightCapability
from wled.exceptions import WLEDUnsupportedVersionError
from wled.models import (
    AwesomeVersionSerializationStrategy,
    Color,
    EffectMetadata,
    Filesystem,
    Info,
    Matrix,
    SegmentUpdate,
    SensorReading,
    State,
    TimedeltaSerializationStrategy,
    TimestampSerializationStrategy,
)
from wled.utils import get_awesome_version

from .conftest import FIXTURES_DIR, full_device_data, load_fixture_json

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FF9900", (255, 153, 0)),
        ("#FF9900", (255, 153, 0)),
        ("ff990011", (255, 153, 0, 17)),
        ({"r": 255, "g": 153, "b": 0}, (255, 153, 0)),
        ({"r": 1, "g": 2, "b": 3, "w": 4}, (1, 2, 3, 4)),
        ([1, 2, 3], [1, 2, 3]),
        ([255], (255, 0, 0)),
        ([1, 2], (1, 2, 0)),
    ],
)
def test_color_deserialize_forms(raw: object, expected: object) -> None:
    """Test every fixed color form WLED takes is understood."""
    color = Color._deserialize([raw])  # pylint: disable=protected-access

    assert color.primary == expected


@pytest.mark.parametrize(
    "raw",
    [
        "r",
        2700,
        "XYZ123",
        "0xFFFF",
        [],
        [1, 2, 3, 4, 5],
        # WLED keeps the current value of a channel an object leaves out.
        {"r": 255, "g": 153},
        {"r": None, "g": 0, "b": 0},
    ],
)
def test_color_deserialize_unusable_primary(raw: object) -> None:
    """Test a primary color that isn't a fixed color is refused."""
    with pytest.raises(ValueError, match="Unusable primary color"):
        Color._deserialize([raw])  # pylint: disable=protected-access


def test_color_deserialize_unusable_secondary() -> None:
    """Test a later color that isn't a fixed color is left out."""
    color = Color._deserialize(["FF0000", "r"])  # pylint: disable=protected-access

    assert color.primary == (255, 0, 0)
    assert color.secondary is None


def test_segment_without_usable_colors() -> None:
    """Test a segment with a random primary color is parsed without colors."""
    base = _base_state()
    segment = base["seg"][0] | {"col": ["r", "r", "r"]}

    state = State.from_dict(_base_state(seg=[segment]))

    assert state.segments[0].color is None


# =========================================================================
# Filesystem model
# =========================================================================


def test_filesystem_free_space() -> None:
    """Test free space calculation."""
    fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
    assert fs.free == 52


def test_filesystem_without_size() -> None:
    """Test the percentages of a filesystem reported without a size are 0."""
    filesystem = Filesystem.from_dict({"t": 0, "u": 0, "pmt": 0})

    assert filesystem.free_percentage == 0
    assert filesystem.used_percentage == 0


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


def test_info_repo_defaults_to_default_repo() -> None:
    """Test repo defaults to DEFAULT_REPO when not present."""
    info = Info.from_dict(_base_info())
    assert info.repo == DEFAULT_REPO


def test_info_repo_uses_device_value_when_present() -> None:
    """Test repo is deserialized from the device response."""
    info = Info.from_dict(_base_info(repo="MoonModules/WLED"))
    assert info.repo == "MoonModules/WLED"


def test_info_sensor() -> None:
    """Test sensor is deserialized into SensorReading objects."""
    info = Info.from_dict(
        _base_info(sensor={"temperature": [77, "F"], "humidity": [42.5, "%"]})
    )

    assert isinstance(info.sensor, dict)
    assert info.sensor["temperature"] == SensorReading(value=77, unit="F")
    assert info.sensor["humidity"] == SensorReading(value=42.5, unit="%")


def test_info_sensor_serializes_back_to_list() -> None:
    """Test SensorReading serializes back to the [value, unit] shape."""
    info = Info.from_dict(_base_info(sensor={"temperature": [77, "F"]}))

    assert info.to_dict()["sensor"] == {"temperature": [77, "F"]}


def test_info_sensor_skips_malformed_entries() -> None:
    """Test malformed sensor entries are skipped, not breaking parsing."""
    info = Info.from_dict(
        _base_info(
            sensor={
                "temperature": [77, "F"],
                "too_short": [77],
                "too_long": [77, "F", "extra"],
                "is_dict": {"value": 77},
                "is_null": None,
                "null_unit": [77, None],
                "dict_unit": [77, {"unit": "F"}],
            }
        )
    )

    assert info.sensor is not None
    assert info.sensor == {"temperature": SensorReading(value=77, unit="F")}


def test_info_sensor_from_usermods() -> None:
    """Test the sensor readings the WLED usermods report are all parsed."""
    # As the Temperature, Internal Temperature v2, SHT, and PIR sensor switch
    # usermods write them; note the padded unit and the bare motion value.
    info = Info.from_dict(
        _base_info(
            sensor={
                "temperature": [21.5, "°C"],
                "Internal Temperature": [41.2, "°C"],
                "temp": [21.4, "°C"],
                "humidity": [45.1, " RH"],
                "motion": True,
            }
        )
    )

    assert info.sensor == {
        "temperature": SensorReading(value=21.5, unit="°C"),
        "Internal Temperature": SensorReading(value=41.2, unit="°C"),
        "temp": SensorReading(value=21.4, unit="°C"),
        "humidity": SensorReading(value=45.1, unit="RH"),
        "motion": SensorReading(value=True),
    }


def test_info_sensor_bare_value_serializes_back() -> None:
    """Test a reading without a unit serializes back to its bare value."""
    info = Info.from_dict(_base_info(sensor={"motion": False}))

    assert info.to_dict()["sensor"] == {"motion": False}


def test_info_sensor_drops_non_dict_value() -> None:
    """Test a non-dict sensor value is dropped instead of breaking parsing."""
    info = Info.from_dict(_base_info(sensor="temperature"))

    assert info.sensor is None


def test_info_sensor_drops_null_value() -> None:
    """Test a null sensor value is dropped instead of breaking parsing."""
    info = Info.from_dict(_base_info(sensor=None))

    assert info.sensor is None


def test_info_sensor_absent() -> None:
    """Test sensor is None when not present in the payload."""
    info = Info.from_dict(_base_info())

    assert info.sensor is None


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


def test_state_segments_keep_reported_ids_with_gaps() -> None:
    """Test segments are keyed by their reported ID, not their position."""
    # WLED leaves inactive segments out, so deleting segment 1 of three
    # leaves IDs 0 and 2 in the list.
    base = _base_state()
    segment = base["seg"][0]
    data = _base_state(
        seg=[segment | {"id": 0}, segment | {"id": 2, "start": 20, "stop": 30}]
    )

    state = State.from_dict(data)

    assert set(state.segments) == {0, 2}
    assert state.segments[2].segment_id == 2
    assert state.segments[2].start == 20


def test_state_segment_without_id_falls_back_to_position() -> None:
    """Test a segment that doesn't report its ID is keyed by its position."""
    base = _base_state()
    segment = {key: value for key, value in base["seg"][0].items() if key != "id"}

    state = State.from_dict(_base_state(seg=[segment]))

    assert state.segments[0].segment_id == 0


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


def test_state_audio_reactive_absent() -> None:
    """Test audio_reactive is None when the usermod is not installed."""
    state = State.from_dict(_base_state())
    assert state.audio_reactive is None


@pytest.mark.parametrize("on", [True, False])
def test_state_audio_reactive_present(on: bool) -> None:
    """Test audio_reactive state is deserialized when the usermod is present."""
    state = State.from_dict(_base_state(AudioReactive={"on": on}))
    assert state.audio_reactive is not None
    assert state.audio_reactive.on is on


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
                "transition": [10, 20],
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
                "transition": [10, 20, 30],
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
                "transition": 5,
                "end": 0,
                "r": True,
            },
        }
    )
    assert len(playlist.entries) == 2
    assert all(e.transition == 5 for e in playlist.entries)


def test_playlist_no_transition() -> None:
    """Test a playlist without a transition leaves it to the device."""
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
    assert playlist.entries[0].transition is None


def test_playlist_defaults_and_padding_like_wled() -> None:
    """Test missing and short lists are filled in the way WLED does."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 6,
            "playlist": {
                "ps": [1, 2, 3],
                "transition": [5],
            },
        }
    )

    assert [entry.duration for entry in playlist.entries] == [100, 100, 100]
    assert [entry.transition for entry in playlist.entries] == [5, 5, 5]


def test_playlist_short_and_long_lists() -> None:
    """Test a short list is padded with its last value, a long one cut off."""
    playlist = Playlist.from_dict(
        {
            "playlist_id": 7,
            "playlist": {
                "ps": [1, 2, 3],
                "dur": [30, 40],
                "transition": [1, 2, 3, 4, 5],
            },
        }
    )

    assert [entry.duration for entry in playlist.entries] == [30, 40, 40]
    assert [entry.transition for entry in playlist.entries] == [1, 2, 3]


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
    assert device.effects[3].name == "Breathe"
    assert 2 not in device.effects  # RSVD placeholder is filtered out

    # Palettes (3 standard + 2 custom)
    assert len(device.palettes) == 5
    assert device.palettes[0].name == "Default"
    assert device.palettes[255].custom is True
    assert device.palettes[255].name == "Custom 1"

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


def test_device_beta_of_minimum_version_allowed() -> None:
    """Test that a beta of the minimum required version is accepted."""
    data = full_device_data()
    data["info"]["ver"] = "0.14.0-b1"
    device = Device.from_dict(data)
    assert device.info.version is not None


def test_device_beta_below_minimum_version_rejected() -> None:
    """Test that a beta below the minimum required version is rejected."""
    data = full_device_data()
    data["info"]["ver"] = "0.13.0-b1"
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
    device.update_from_dict({"effects": ["NewEffect1", "RSVD", "NewEffect2"]})
    assert len(device.effects) == 2
    assert 1 not in device.effects
    assert device.effects[0].name == "NewEffect1"
    assert device.effects[2].name == "NewEffect2"


def test_device_update_from_dict_filters_null_effects() -> None:
    """Test update_from_dict filters null effects."""
    data = full_device_data()
    device = Device.from_dict(data)
    device.update_from_dict({"effects": ["NewEffect1", None, "NewEffect2"]})
    assert len(device.effects) == 2
    assert 1 not in device.effects
    assert device.effects[0].name == "NewEffect1"
    assert device.effects[2].name == "NewEffect2"


def test_device_filters_reserved_effects() -> None:
    """Test that RSVD placeholder effects are filtered out."""
    data = full_device_data()
    data["effects"] = ["Solid", "RSVD", "Breathe", "RSVD"]
    device = Device.from_dict(data)
    assert len(device.effects) == 2
    assert 1 not in device.effects
    assert 3 not in device.effects
    assert device.effects[0].name == "Solid"
    assert device.effects[2].name == "Breathe"


def test_device_filters_null_effects() -> None:
    """Test that null effects are filtered out."""
    data = full_device_data()
    data["effects"] = ["Solid", None, "Breathe"]
    device = Device.from_dict(data)
    assert len(device.effects) == 2
    assert 1 not in device.effects
    assert device.effects[0].name == "Solid"
    assert device.effects[2].name == "Breathe"


def test_device_filters_null_palettes() -> None:
    """Test that null palettes are filtered out."""
    data = full_device_data()
    data["info"]["cpalcount"] = 0
    data["info"]["umpalcount"] = 0
    data["info"]["umpalnames"] = []
    data["palettes"] = ["Default", None, "Party"]
    device = Device.from_dict(data)
    assert len(device.palettes) == 2
    assert 1 not in device.palettes
    assert device.palettes[0].name == "Default"
    assert device.palettes[2].name == "Party"


@pytest.mark.parametrize(
    ("version", "expected_palette_ids"),
    [
        ("0.14.0", [255, 254]),
        ("15.0.0", [255, 254]),
        ("16.0.0b1", [200, 199]),
        ("16.0.0", [200, 199]),
        ("16.5.0", [200, 199]),
        ("17.0.0", [200, 199]),
    ],
    ids=lambda x: x[0],
)
def test_device_custom_palette_ids_by_version(
    version: str, expected_palette_ids: list[int]
) -> None:
    """Test custom palette IDs depend on WLED firmware version."""
    data = full_device_data()
    data["info"]["ver"] = version
    device = Device.from_dict(data)
    # cpalcount is 2 in fixture, so check both IDs
    assert device.palettes[expected_palette_ids[0]].custom is True
    assert device.palettes[expected_palette_ids[0]].name == "Custom 1"
    assert device.palettes[expected_palette_ids[1]].custom is True
    assert device.palettes[expected_palette_ids[1]].name == "Custom 2"


@pytest.mark.parametrize(
    ("version", "expected_custom_ids"),
    [
        ("0.14.0", [255, 254]),
        ("16.0.0", [200, 199]),
    ],
)
def test_device_update_from_dict_palettes(
    version: str, expected_custom_ids: list[int]
) -> None:
    """Test update_from_dict updates palettes based on firmware version."""
    data = full_device_data()
    data["info"]["ver"] = version
    device = Device.from_dict(data)
    device.update_from_dict({"palettes": ["NewPalette"]})
    # 1 standard + 2 custom (from cpalcount in fixture)
    assert len(device.palettes) == 3
    assert device.palettes[0].name == "NewPalette"
    assert device.palettes[expected_custom_ids[0]].custom is True
    assert device.palettes[expected_custom_ids[1]].custom is True


def test_device_update_from_dict_filters_null_palettes() -> None:
    """Test update_from_dict filters null palettes."""
    data = full_device_data()
    data["info"]["cpalcount"] = 0
    data["info"]["umpalcount"] = 0
    data["info"]["umpalnames"] = []
    device = Device.from_dict(data)
    device.update_from_dict({"palettes": ["Default", None, "Party"]})
    assert len(device.palettes) == 2
    assert 1 not in device.palettes
    assert device.palettes[0].name == "Default"
    assert device.palettes[2].name == "Party"


@pytest.mark.parametrize("playlist", [[], {}, {"ps": []}, None, "not a playlist"])
def test_device_preset_without_usable_playlist(playlist: object) -> None:
    """Test a preset with an empty or odd playlist value stays a preset."""
    data = full_device_data()
    data["presets"] = {"1": {"n": "Example", "playlist": playlist}}

    device = Device.from_dict(data)
    assert device.presets[1].name == "Example"
    assert device.playlists == {}

    device.update_from_dict({"presets": {"2": {"n": "Other", "playlist": playlist}}})
    assert device.presets[2].name == "Other"
    assert device.playlists == {}


def test_device_usermod_palettes() -> None:
    """Test usermod palettes are correctly added to device palettes."""
    data = full_device_data()
    # Usermod palettes are available in WLED >= 16.0.0
    data["info"]["ver"] = "16.0.0"
    data["info"]["umpalcount"] = 2
    data["info"]["umpalnames"] = ["Plasma Effect", "Rainbow Shift"]
    device = Device.from_dict(data)
    # 3 standard + 2 custom (ID 200, 199) + 2 usermod (ID 255, 254) = 7
    assert len(device.palettes) == 7
    assert device.palettes[255].custom is False
    assert device.palettes[255].name == "Plasma Effect"
    assert device.palettes[254].custom is False
    assert device.palettes[254].name == "Rainbow Shift"
    assert device.palettes[200].custom is True
    assert device.palettes[200].name == "Custom 1"


def test_device_update_from_dict_usermod_palettes() -> None:
    """Test update_from_dict re-synthesizes usermod palettes from self.info."""
    data = full_device_data()
    data["info"]["ver"] = "16.0.0"
    data["info"]["umpalcount"] = 2
    data["info"]["umpalnames"] = ["Plasma Effect", "Rainbow Shift"]
    device = Device.from_dict(data)

    # Verify initial state has usermod palettes
    assert device.palettes[255].custom is False
    assert device.palettes[255].name == "Plasma Effect"
    assert device.palettes[254].custom is False
    assert device.palettes[254].name == "Rainbow Shift"
    assert device.palettes[200].custom is True

    # Update with new palette list (re-synthesizes all palettes)
    device.update_from_dict({"palettes": ["NewPalette"]})

    # Verify standard palette was updated
    assert device.palettes[0].name == "NewPalette"

    # Verify usermod palettes were re-synthesized with stored names from self.info
    assert device.palettes[255].custom is False
    assert device.palettes[255].name == "Plasma Effect"
    assert device.palettes[254].custom is False
    assert device.palettes[254].name == "Rainbow Shift"

    # Verify custom palettes still present with correct IDs
    assert device.palettes[200].custom is True
    assert device.palettes[200].name == "Custom 1"


def test_device_usermod_palettes_count_bounded() -> None:
    """Test usermod palette count is bounded to 55 slots."""
    data = full_device_data()
    data["info"]["ver"] = "16.0.0"
    data["info"]["umpalcount"] = 60  # Exceeds max of 55
    data["info"]["umpalnames"] = [f"Palette {i}" for i in range(60)]
    device = Device.from_dict(data)
    # Verify only 55 usermod palettes are generated (IDs 255..201)
    assert device.palettes[255].name == "Palette 0"
    assert device.palettes[201].name == "Palette 54"
    # ID 200 is reserved for custom palettes, should not be a usermod palette
    assert device.palettes[200].custom is True
    # Count: 3 built-in + 2 custom + 55 usermod = 60
    assert len(device.palettes) == 60


def test_device_usermod_palettes_null_names() -> None:
    """Test usermod palettes with null names use fallback."""
    data = full_device_data()
    data["info"]["ver"] = "16.0.0"
    data["info"]["umpalcount"] = 2
    data["info"]["umpalnames"] = None  # JSON null
    device = Device.from_dict(data)
    # Should not raise TypeError; fallback names should be used
    assert len(device.palettes) == 7  # 3 built-in + 2 custom + 2 usermod
    assert device.palettes[255].name == "Usermod 1"
    assert device.palettes[254].name == "Usermod 2"
    assert device.palettes[255].custom is False


def test_device_usermod_palettes_pre_v16_skipped() -> None:
    """Test usermod palettes are not synthesized on pre-16.0.0 firmware."""
    data = full_device_data()
    data["info"]["ver"] = "15.0.0"
    data["info"]["umpalcount"] = 2
    data["info"]["umpalnames"] = ["Plasma Effect", "Rainbow Shift"]
    device = Device.from_dict(data)
    # Usermod palettes should not be present on pre-16 firmware
    # Count: 3 built-in + 2 custom (at IDs 255, 254 for pre-16) = 5
    assert len(device.palettes) == 5
    assert 255 in device.palettes
    assert device.palettes[255].custom is True  # Custom palette, not usermod
    assert device.palettes[255].name == "Custom 1"
    assert 254 in device.palettes
    assert device.palettes[254].custom is True
    assert device.palettes[254].name == "Custom 2"


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
    releases = Releases.from_dict(
        {
            "stable": "0.14.0",
            "beta": "0.15.0b1",
            "nightly": "17.0.0-dev",
            "repo": "wled/WLED",
        }
    )
    assert releases.stable is not None
    assert releases.beta is not None
    assert releases.nightly is not None
    assert releases.repo == "wled/WLED"


def test_releases_none_values() -> None:
    """Test Releases with None values."""
    releases = Releases.from_dict(
        {"stable": "", "beta": "", "nightly": "", "repo": "wled/WLED"}
    )
    assert releases.stable is None
    assert releases.beta is None
    assert releases.nightly is None


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
    snapshot_dataclass: SnapshotAssertion,
) -> None:
    """Test Device parsing against real-world WLED responses."""
    data = load_fixture_json(fixture)
    data["presets"] = {}
    device = Device.from_dict(data)
    assert device == snapshot_dataclass


_VERSIONS_DIR = FIXTURES_DIR / "versions"


@pytest.mark.parametrize(
    "version_fixture",
    [p.stem for p in sorted(_VERSIONS_DIR.glob("*.json"))],
)
def test_device_version_fixture(
    version_fixture: str,
    snapshot_dataclass: SnapshotAssertion,
) -> None:
    """Test Device parsing against real /json.

    The responses were captured from each WLED release.
    """
    data = load_fixture_json(f"versions/{version_fixture}")
    device = Device.from_dict(data)
    assert device == snapshot_dataclass


# =========================================================================
# Effect metadata
# =========================================================================


@pytest.mark.parametrize(
    ("raw", "sliders", "options", "colors", "palette", "flags", "defaults"),
    [
        # No metadata: WLED shows its default controls.
        (
            "",
            {"speed": "Effect speed", "intensity": "Effect intensity"},
            {},
            {0: "Fx", 1: "Bg", 2: "Cs"},
            True,
            (False, False),
            {},
        ),
        # Blink: a named second slider, two colors, a palette, 1D.
        (
            "!,Duty cycle;!,!;!;01",
            {"speed": "Effect speed", "intensity": "Duty cycle"},
            {},
            {0: "Fx", 1: "Bg"},
            True,
            (False, False),
            {},
        ),
        # Copy Segment: skips the speed slider, has options, 1D and 2D.
        (
            (
                ",Color shift,Lighten,Brighten,ID,Axis(2D),FullStack(last frame);;;12;"
                "ix=0,c1=0,c2=0,c3=0"
            ),
            {
                "intensity": "Color shift",
                "custom1": "Lighten",
                "custom2": "Brighten",
                "custom3": "ID",
            },
            {"option1": "Axis(2D)", "option2": "FullStack(last frame)"},
            {},
            False,
            (False, False),
            {"ix": 0, "c1": 0, "c2": 0, "c3": 0},
        ),
        # Only the background color, by position.
        (
            "!;,!;!;01",
            {"speed": "Effect speed"},
            {},
            {1: "Bg"},
            True,
            (False, False),
            {},
        ),
        # A 2D effect reacting to volume, without a palette.
        (
            "Speed;!;;2v",
            {"speed": "Speed"},
            {},
            {0: "Fx"},
            False,
            (True, True),
            {},
        ),
        # Defaults, skipping one that isn't a number.
        (
            "!,!;;!;1;sx=24,pal=50,bad=x",
            {"speed": "Effect speed", "intensity": "Effect intensity"},
            {},
            {},
            True,
            (False, False),
            {"sx": 24, "pal": 50},
        ),
    ],
    ids=["none", "blink", "copy_segment", "background_only", "2d_audio", "defaults"],
)
def test_effect_metadata(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    raw: str,
    sliders: dict,
    options: dict,
    colors: dict,
    palette: bool,
    flags: tuple[bool, bool],
    defaults: dict,
) -> None:
    """Test effect metadata is read the way WLED's own interface reads it."""
    metadata = EffectMetadata._deserialize(raw)  # pylint: disable=protected-access

    assert metadata.sliders == sliders
    assert metadata.options == options
    assert metadata.colors == colors
    assert metadata.palette is palette
    assert (metadata.requires_matrix, metadata.audio_reactive) == flags
    assert metadata.defaults == defaults
    assert metadata._serialize() == raw  # pylint: disable=protected-access


def test_device_effects_get_their_metadata() -> None:
    """Test each effect gets the metadata at its own index, RSVD included."""
    data = full_device_data()
    data["effects"] = ["Solid", "Blink", "RSVD", "Matrix"]
    data["fxdata"] = ["", "!,Duty cycle;!,!;!;01", "", "!;;!;2"]

    device = Device.from_dict(data)

    assert set(device.effects) == {0, 1, 3}
    assert device.effects[1].metadata is not None
    assert device.effects[1].metadata.sliders["intensity"] == "Duty cycle"
    assert device.effects[3].metadata is not None
    assert device.effects[3].metadata.requires_matrix

    device.update_from_dict(
        {"effects": ["Solid", "Blink"], "fxdata": ["", "Rate;!;;2"]}
    )
    assert device.effects[1].metadata is not None
    assert device.effects[1].metadata.sliders == {"speed": "Rate"}


def test_device_effects_without_usable_metadata() -> None:
    """Test effects without metadata, or with broken metadata, get None."""
    data = full_device_data()
    data["effects"] = ["Solid", "Blink", "Breathe"]
    data["fxdata"] = ["", None]

    device = Device.from_dict(data)

    assert device.effects[0].metadata is not None
    assert device.effects[1].metadata is None
    assert device.effects[2].metadata is None


@pytest.mark.parametrize(
    ("matrix", "expected"),
    [({"w": 16, "h": 8}, Matrix(width=16, height=8)), (None, None)],
    ids=["matrix", "strip"],
)
def test_leds_matrix(matrix: dict | None, expected: Matrix | None) -> None:
    """Test the matrix size is reported for a 2D setup, and None for a strip."""
    data = full_device_data()
    if matrix is not None:
        data["info"]["leds"]["matrix"] = matrix

    device = Device.from_dict(data)

    assert device.info.leds.matrix == expected


def test_solid_effect_uses_the_primary_color_only() -> None:
    """Test Solid, which has no metadata, gets what WLED's interface gives it."""
    data = full_device_data()
    data["effects"] = ["Solid", "Blink"]
    data["fxdata"] = ["", ""]

    device = Device.from_dict(data)

    solid = device.effects[0].metadata
    assert solid is not None
    assert solid.sliders == {}
    assert solid.colors == {0: "Fx"}
    assert solid.palette is False
    # Other effects without metadata keep the default controls.
    assert device.effects[1].metadata is not None
    assert device.effects[1].metadata.sliders == {
        "speed": "Effect speed",
        "intensity": "Effect intensity",
    }


@pytest.mark.parametrize(
    ("segment_lc", "seglc", "expected"),
    [
        # WLED 16.0 reports it on the segment itself.
        (3, [7], LightCapability.RGB_COLOR | LightCapability.WHITE_CHANNEL),
        # Older versions only list it in the LED info.
        (None, [7], LightCapability(7)),
        # Without either, it isn't known.
        (None, [], None),
    ],
)
def test_segment_light_capabilities(
    segment_lc: int | None, seglc: list[int], expected: LightCapability | None
) -> None:
    """Test segment capabilities come from the segment, or the LED info."""
    data = full_device_data()
    data["info"]["leds"]["seglc"] = seglc
    if segment_lc is not None:
        data["info"]["ver"] = "16.0.0"
        data["state"]["seg"][0]["lc"] = segment_lc

    device = Device.from_dict(data)

    assert device.state.segments[0].light_capabilities == expected


@pytest.mark.parametrize("keys", [("info", "state"), ("info",)])
@pytest.mark.parametrize(
    ("seglc", "expected"), [([1], LightCapability.RGB_COLOR), ([], None)]
)
def test_segment_light_capabilities_after_an_update(
    keys: tuple[str, ...], seglc: list[int], expected: LightCapability | None
) -> None:
    """Test segment capabilities follow the LED info, also without a new state."""
    device = Device.from_dict(full_device_data())
    data = full_device_data()
    data["info"]["leds"]["seglc"] = seglc

    device.update_from_dict({key: data[key] for key in keys})

    assert device.state.segments[0].light_capabilities == expected


@pytest.mark.parametrize(
    ("opt", "expected"),
    [
        (
            79,
            BuildOption.OTA
            | BuildOption.ADALIGHT
            | BuildOption.HUE_SYNC
            | BuildOption.FILESYSTEM
            | BuildOption.ALEXA,
        ),
        (8, BuildOption.FILESYSTEM),
        (None, BuildOption.NONE),
    ],
)
def test_info_build_options(opt: int | None, expected: BuildOption) -> None:
    """Test the build options are read from the info."""
    data = full_device_data()
    if opt is not None:
        data["info"]["opt"] = opt

    device = Device.from_dict(data)

    assert device.info.build_options == expected
    assert (BuildOption.OTA in device.info.build_options) == bool(
        expected & BuildOption.OTA
    )


def test_wifi_without_a_connection() -> None:
    """Test a device without Wi-Fi connection reports no signal, not 100%."""
    data = full_device_data()
    data["info"]["wifi"] = {
        "bssid": "00:00:00:00:00:00",
        "rssi": 0,
        "signal": 100,
        "channel": 0,
        "ap": True,
    }

    device = Device.from_dict(data)

    assert device.info.wifi is not None
    assert device.info.wifi.rssi is None
    assert device.info.wifi.signal is None
    assert device.info.wifi.access_point


def test_segment_update_clones_is_deprecated() -> None:
    """Test setting clones on a segment update warns that it's ignored."""
    with pytest.warns(DeprecationWarning, match="clones"):
        SegmentUpdate(segment_id=0, clones=1)
