"""Tests for `wled`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from awesomeversion import AwesomeVersion

from wled import WLED, Device, Playlist, Preset, Releases
from wled.const import (
    LightCapability,
    LiveDataOverride,
    NightlightMode,
    SyncGroup,
)
from wled.exceptions import (
    WLEDConnectionClosedError,
    WLEDConnectionError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDUnsupportedVersionError,
    WLEDUpgradeError,
)
from wled.models import (
    AwesomeVersionSerializationStrategy,
    Color,
    Effect,
    Filesystem,
    Info,
    Nightlight,
    Palette,
    PlaylistEntry,
    Segment,
    State,
    TimedeltaSerializationStrategy,
    TimestampSerializationStrategy,
    UDPSync,
)
from wled.utils import get_awesome_version
from wled.wled import WLEDReleases

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

WLED_JSON: dict[str, Any] = {
    "state": {
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
    },
    "info": {
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
    },
    "effects": ["Solid", "Blink", "Breathe"],
    "palettes": ["Default", "Random Cycle", "Primary Color"],
}

PRESETS_JSON: dict[str, Any] = {
    "0": {},
    "1": {
        "n": "My Preset",
        "on": True,
        "bri": 128,
        "transition": 7,
        "mainseg": 0,
        "seg": [{"col": [[255, 0, 0]]}],
    },
    "2": {
        "n": "My Playlist",
        "playlist": {
            "ps": [1],
            "dur": [100],
            "transitions": [10],
            "end": 0,
            "r": False,
            "repeat": 3,
        },
    },
}


def _full_device_data() -> dict[str, Any]:
    """Return complete device data with presets merged in."""
    data = json.loads(json.dumps(WLED_JSON))
    data["presets"] = json.loads(json.dumps(PRESETS_JSON))
    return data


def _mock_json_and_presets(mocked: aioresponses) -> None:
    """Register the two GET endpoints that WLED.update() calls."""
    mocked.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(WLED_JSON),
        content_type="application/json",
    )
    mocked.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(PRESETS_JSON),
        content_type="application/json",
    )


# =========================================================================
# Section 1: Existing tests (preserved)
# =========================================================================


async def test_json_request() -> None:
    """Test JSON response is handled correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/")
            assert response["status"] == "ok"


async def test_text_request() -> None:
    """Test non-JSON response is handled correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/")
            assert response == "OK"


async def test_internal_session() -> None:
    """Test internal session is created and works correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with WLED("example.com") as wled:
            response = await wled.request("/")
            assert response["status"] == "ok"


async def test_post_request() -> None:
    """Test POST requests are handled correctly."""
    with aioresponses() as mocked:
        mocked.post(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/", method="POST")
            assert response == "OK"


async def test_backoff() -> None:
    """Test requests are handled with retries."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session, request_timeout=0.1)
            response = await wled.request("/")
            assert response == "OK"


async def test_timeout() -> None:
    """Test request timeout from WLED."""
    with aioresponses() as mocked:
        # Backoff will try 3 times
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session, request_timeout=0.1)
            with pytest.raises(WLEDConnectionError):
                assert await wled.request("/")


async def test_http_error404() -> None:
    """Test HTTP 404 response handling."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=404,
            body="OMG PUPPIES!",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            with pytest.raises(WLEDError):
                assert await wled.request("/")


async def test_http_error500() -> None:
    """Test HTTP 500 response handling."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=500,
            body='{"status":"nok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            with pytest.raises(WLEDError):
                assert await wled.request("/")


# =========================================================================
# Section 2: Serialization strategies
# =========================================================================


class TestAwesomeVersionSerializationStrategy:
    """Tests for AwesomeVersionSerializationStrategy."""

    def test_serialize_none(self) -> None:
        """Test serializing None returns empty string."""
        strategy = AwesomeVersionSerializationStrategy()
        assert strategy.serialize(None) == ""

    def test_serialize_version(self) -> None:
        """Test serializing an AwesomeVersion."""
        strategy = AwesomeVersionSerializationStrategy()
        version = AwesomeVersion("0.14.0")
        assert strategy.serialize(version) == "0.14.0"

    def test_deserialize_valid(self) -> None:
        """Test deserializing a valid version string."""
        strategy = AwesomeVersionSerializationStrategy()
        result = strategy.deserialize("0.14.0")
        assert result is not None
        assert isinstance(result, AwesomeVersion)
        assert str(result) == "0.14.0"

    def test_deserialize_invalid(self) -> None:
        """Test deserializing an invalid version string returns None."""
        strategy = AwesomeVersionSerializationStrategy()
        result = strategy.deserialize("")
        assert result is None


class TestTimedeltaSerializationStrategy:
    """Tests for TimedeltaSerializationStrategy."""

    def test_serialize(self) -> None:
        """Test serializing a timedelta to seconds."""
        strategy = TimedeltaSerializationStrategy()
        td = timedelta(hours=1, minutes=30)
        assert strategy.serialize(td) == 5400

    def test_deserialize(self) -> None:
        """Test deserializing seconds to timedelta."""
        strategy = TimedeltaSerializationStrategy()
        result = strategy.deserialize(3600)
        assert result == timedelta(seconds=3600)


class TestTimestampSerializationStrategy:
    """Tests for TimestampSerializationStrategy."""

    def test_serialize(self) -> None:
        """Test serializing a datetime to timestamp."""
        strategy = TimestampSerializationStrategy()
        dt = datetime(2023, 12, 8, 16, 33, 23, tzinfo=UTC)
        result = strategy.serialize(dt)
        assert result == dt.timestamp()

    def test_deserialize(self) -> None:
        """Test deserializing a timestamp to datetime."""
        strategy = TimestampSerializationStrategy()
        result = strategy.deserialize(1702050803.0)
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC


# =========================================================================
# Section 3: Color model
# =========================================================================


class TestColor:
    """Tests for Color serialization and deserialization."""

    def test_serialize_primary_only(self) -> None:
        """Test serializing with only primary color."""
        color = Color(primary=(255, 0, 0))
        result = color._serialize()
        assert result == [(255, 0, 0)]

    def test_serialize_primary_and_secondary(self) -> None:
        """Test serializing with primary and secondary colors."""
        color = Color(primary=(255, 0, 0), secondary=(0, 255, 0))
        result = color._serialize()
        assert result == [(255, 0, 0), (0, 255, 0)]

    def test_serialize_all_three_colors(self) -> None:
        """Test serializing with all three colors."""
        color = Color(
            primary=(255, 0, 0), secondary=(0, 255, 0), tertiary=(0, 0, 255)
        )
        result = color._serialize()
        assert result == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]

    def test_serialize_tertiary_without_secondary(self) -> None:
        """Test serializing with tertiary but no secondary omits tertiary."""
        color = Color(primary=(255, 0, 0), tertiary=(0, 0, 255))
        result = color._serialize()
        assert result == [(255, 0, 0)]

    def test_deserialize_tuple_colors(self) -> None:
        """Test deserializing tuple colors."""
        color = Color._deserialize([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        assert color.primary == (255, 0, 0)
        assert color.secondary == (0, 255, 0)
        assert color.tertiary == (0, 0, 255)

    def test_deserialize_hex_color(self) -> None:
        """Test deserializing hex color strings."""
        color = Color._deserialize(["#FF0000", "#00FF00"])
        assert color.primary == (255, 0, 0)
        assert color.secondary == (0, 255, 0)

    def test_deserialize_mixed(self) -> None:
        """Test deserializing mixed hex and tuple colors."""
        color = Color._deserialize(["#FF9900", (0, 0, 0)])
        assert color.primary == (255, 153, 0)
        assert color.secondary == (0, 0, 0)


# =========================================================================
# Section 4: Filesystem model
# =========================================================================


class TestFilesystem:
    """Tests for Filesystem cached properties."""

    def test_free_space(self) -> None:
        """Test free space calculation."""
        fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
        assert fs.free == 52

    def test_free_percentage(self) -> None:
        """Test free percentage calculation."""
        fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
        assert fs.free_percentage == 81

    def test_used_percentage(self) -> None:
        """Test used percentage calculation."""
        fs = Filesystem.from_dict({"u": 12, "t": 64, "pmt": 1702050803.0})
        assert fs.used_percentage == 19


# =========================================================================
# Section 5: Info model
# =========================================================================


class TestInfo:
    """Tests for Info model deserialization."""

    def _base_info(self, **overrides: Any) -> dict[str, Any]:
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

    def test_websocket_minus_one_becomes_none(self) -> None:
        """Test websocket value of -1 is converted to None."""
        info = Info.from_dict(self._base_info(ws=-1))
        assert info.websocket is None

    def test_websocket_zero(self) -> None:
        """Test websocket value of 0 stays 0."""
        info = Info.from_dict(self._base_info(ws=0))
        assert info.websocket == 0

    def test_architecture_lowered(self) -> None:
        """Test architecture is lowercased."""
        info = Info.from_dict(self._base_info(arch="ESP32"))
        assert info.architecture == "esp32"

    def test_esp01_detection(self) -> None:
        """Test esp01 detection based on filesystem total <= 256."""
        info = Info.from_dict(
            self._base_info(
                arch="esp8266",
                fs={"u": 10, "t": 256, "pmt": 1702050803.0},
            )
        )
        assert info.architecture == "esp01"

    def test_esp02_detection(self) -> None:
        """Test esp02 detection based on filesystem total <= 512."""
        info = Info.from_dict(
            self._base_info(
                arch="esp8266",
                fs={"u": 10, "t": 512, "pmt": 1702050803.0},
            )
        )
        assert info.architecture == "esp02"

    def test_esp8266_large_fs_stays_esp8266(self) -> None:
        """Test esp8266 with large fs stays as esp8266."""
        info = Info.from_dict(
            self._base_info(
                arch="esp8266",
                fs={"u": 10, "t": 1024, "pmt": 1702050803.0},
            )
        )
        assert info.architecture == "esp8266"

    def test_uptime_as_timedelta(self) -> None:
        """Test uptime is deserialized as timedelta."""
        info = Info.from_dict(self._base_info(uptime=32489))
        assert info.uptime == timedelta(seconds=32489)

    def test_version_deserialized(self) -> None:
        """Test version is deserialized as AwesomeVersion."""
        info = Info.from_dict(self._base_info(ver="0.14.0"))
        assert info.version is not None
        assert str(info.version) == "0.14.0"


# =========================================================================
# Section 6: State model
# =========================================================================


class TestState:
    """Tests for State model deserialization."""

    def _base_state(self, **overrides: Any) -> dict[str, Any]:
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

    def test_segment_indexing(self) -> None:
        """Test segments are converted from list to indexed dict."""
        state = State.from_dict(self._base_state())
        assert isinstance(state.segments, dict)
        assert 0 in state.segments
        assert state.segments[0].segment_id == 0

    def test_multiple_segments_indexed(self) -> None:
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
        state = State.from_dict(self._base_state(seg=[seg1, seg2]))
        assert 0 in state.segments
        assert 1 in state.segments
        assert state.segments[0].segment_id == 0
        assert state.segments[1].segment_id == 1

    def test_playlist_id_minus_one_becomes_none(self) -> None:
        """Test playlist_id -1 is converted to None."""
        state = State.from_dict(self._base_state(pl=-1))
        assert state.playlist_id is None

    def test_preset_id_minus_one_becomes_none(self) -> None:
        """Test preset_id -1 is converted to None."""
        state = State.from_dict(self._base_state(ps=-1))
        assert state.preset_id is None

    def test_playlist_id_positive(self) -> None:
        """Test positive playlist_id is kept."""
        state = State.from_dict(self._base_state(pl=5))
        assert state.playlist_id == 5

    def test_preset_id_positive(self) -> None:
        """Test positive preset_id is kept."""
        state = State.from_dict(self._base_state(ps=3))
        assert state.preset_id == 3


# =========================================================================
# Section 7: Preset model
# =========================================================================


class TestPreset:
    """Tests for Preset model deserialization."""

    def test_basic_preset(self) -> None:
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

    def test_preset_empty_name_uses_id(self) -> None:
        """Test preset with empty name defaults to preset ID as string."""
        preset = Preset.from_dict(
            {
                "preset_id": 42,
                "n": "",
                "on": False,
            }
        )
        assert preset.name == "42"

    def test_preset_no_name_uses_id(self) -> None:
        """Test preset without name key defaults to preset ID as string."""
        preset = Preset.from_dict(
            {
                "preset_id": 7,
            }
        )
        assert preset.name == "7"

    def test_preset_seg_single_to_list(self) -> None:
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
# Section 8: Playlist model
# =========================================================================


class TestPlaylist:
    """Tests for Playlist model deserialization."""

    def test_basic_playlist(self) -> None:
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

    def test_playlist_single_duration(self) -> None:
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

    def test_playlist_single_transition(self) -> None:
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

    def test_playlist_no_transitions(self) -> None:
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

    def test_playlist_empty_name_uses_id(self) -> None:
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

    def test_playlist_no_name_uses_id(self) -> None:
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
# Section 9: Device model
# =========================================================================


class TestDevice:
    """Tests for Device model."""

    def test_from_dict_full(self) -> None:
        """Test full Device deserialization from dict."""
        data = _full_device_data()
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

    def test_unsupported_version(self) -> None:
        """Test that unsupported firmware version raises error."""
        data = _full_device_data()
        data["info"]["ver"] = "0.8.0"
        with pytest.raises(WLEDUnsupportedVersionError):
            Device.from_dict(data)

    def test_null_palettes(self) -> None:
        """Test that None palettes results in empty dict."""
        data = _full_device_data()
        data["palettes"] = None
        device = Device.from_dict(data)
        assert device.palettes == {}

    def test_no_effects(self) -> None:
        """Test device with no effects list."""
        data = _full_device_data()
        data.pop("effects", None)
        device = Device.from_dict(data)
        assert device.effects == {}

    def test_no_palettes_key(self) -> None:
        """Test device with no palettes key at all defaults to empty dict."""
        data = _full_device_data()
        # Remove the key entirely (not set to None)
        data.pop("palettes", None)
        device = Device.from_dict(data)
        assert device.palettes == {}

    def test_no_presets(self) -> None:
        """Test device with no presets."""
        data = _full_device_data()
        data.pop("presets", None)
        device = Device.from_dict(data)
        assert device.presets == {}
        assert device.playlists == {}

    def test_update_from_dict_effects(self) -> None:
        """Test update_from_dict updates effects."""
        data = _full_device_data()
        device = Device.from_dict(data)
        device.update_from_dict({"effects": ["NewEffect1", "NewEffect2"]})
        assert len(device.effects) == 2
        assert device.effects[0].name == "NewEffect1"

    def test_update_from_dict_palettes(self) -> None:
        """Test update_from_dict updates palettes."""
        data = _full_device_data()
        device = Device.from_dict(data)
        device.update_from_dict({"palettes": ["NewPalette"]})
        assert len(device.palettes) == 1
        assert device.palettes[0].name == "NewPalette"

    def test_update_from_dict_presets(self) -> None:
        """Test update_from_dict updates presets and playlists."""
        data = _full_device_data()
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

    def test_update_from_dict_info(self) -> None:
        """Test update_from_dict updates info."""
        data = _full_device_data()
        device = Device.from_dict(data)
        new_info = json.loads(json.dumps(WLED_JSON["info"]))
        new_info["name"] = "Updated WLED"
        device.update_from_dict({"info": new_info})
        assert device.info.name == "Updated WLED"

    def test_update_from_dict_state(self) -> None:
        """Test update_from_dict updates state."""
        data = _full_device_data()
        device = Device.from_dict(data)
        new_state = json.loads(json.dumps(WLED_JSON["state"]))
        new_state["on"] = False
        device.update_from_dict({"state": new_state})
        assert device.state.on is False

    def test_update_from_dict_returns_self(self) -> None:
        """Test update_from_dict returns the device itself."""
        data = _full_device_data()
        device = Device.from_dict(data)
        result = device.update_from_dict({})
        assert result is device

    def test_preset_with_empty_playlist_ps(self) -> None:
        """Test that a preset with empty playlist ps list is treated as preset."""
        data = _full_device_data()
        data["presets"]["3"] = {
            "n": "Empty PL",
            "playlist": {"ps": [], "dur": [], "end": 0, "r": False},
        }
        device = Device.from_dict(data)
        # Should be classified as a preset (not a playlist) because ps is empty
        assert 3 in device.presets
        assert 3 not in device.playlists

    def test_update_from_dict_preset_with_empty_playlist_ps(self) -> None:
        """Test update_from_dict handles preset with empty playlist ps."""
        data = _full_device_data()
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
# Section 10: WLED client - update() method
# =========================================================================


class TestWLEDUpdate:
    """Tests for WLED.update() method."""

    async def test_update_creates_device(self) -> None:
        """Test that update() creates a Device from API responses."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                device = await wled.update()
                assert isinstance(device, Device)
                assert device.info.name == "WLED"
                assert device.state.on is True

    async def test_update_uses_existing_device(self) -> None:
        """Test that subsequent update() calls use update_from_dict."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            _mock_json_and_presets(mocked)
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                device1 = await wled.update()
                device2 = await wled.update()
                assert device1 is device2

    async def test_update_empty_json_response(self) -> None:
        """Test update() raises on empty /json response."""
        with aioresponses() as mocked:
            # Backoff on update() retries 3 times for WLEDEmptyResponseError
            for _ in range(3):
                mocked.get(
                    "http://example.com/json",
                    status=200,
                    body="",
                    content_type="text/plain",
                )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                with pytest.raises(WLEDEmptyResponseError):
                    await wled.update()

    async def test_update_empty_presets_response(self) -> None:
        """Test update() raises on empty /presets.json response."""
        with aioresponses() as mocked:
            # Backoff on update() retries 3 times for WLEDEmptyResponseError
            for _ in range(3):
                mocked.get(
                    "http://example.com/json",
                    status=200,
                    body=json.dumps(WLED_JSON),
                    content_type="application/json",
                )
                mocked.get(
                    "http://example.com/presets.json",
                    status=200,
                    body="",
                    content_type="text/plain",
                )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                with pytest.raises(WLEDEmptyResponseError):
                    await wled.update()


# =========================================================================
# Section 11: WLED client - master() method
# =========================================================================


class TestWLEDMaster:
    """Tests for WLED.master() method."""

    async def test_master_brightness(self) -> None:
        """Test setting master brightness."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body='{"on": true, "bri": 200}',
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.master(brightness=200)

    async def test_master_on(self) -> None:
        """Test setting master on/off."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body='{"on": true}',
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.master(on=True)

    async def test_master_transition(self) -> None:
        """Test setting master transition."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body='{"on": true}',
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.master(transition=10)

    async def test_master_all_params(self) -> None:
        """Test setting all master parameters at once."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body='{"on": true, "bri": 100}',
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.master(brightness=100, on=True, transition=5)


# =========================================================================
# Section 12: WLED client - segment() method
# =========================================================================


class TestWLEDSegment:
    """Tests for WLED.segment() method."""

    async def _get_wled_with_device(
        self, mocked: aioresponses, session: aiohttp.ClientSession
    ) -> WLED:
        """Create a WLED instance with a loaded device."""
        _mock_json_and_presets(mocked)
        wled = WLED("example.com", session=session)
        await wled.update()
        return wled

    async def test_segment_basic(self) -> None:
        """Test basic segment control."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, brightness=200, on=True)

    async def test_segment_effect_by_name(self) -> None:
        """Test setting segment effect by name."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, effect="Blink")

    async def test_segment_palette_by_name(self) -> None:
        """Test setting segment palette by name."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, palette="Random Cycle")

    async def test_segment_color_primary(self) -> None:
        """Test setting primary color."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, color_primary=(255, 0, 0))

    async def test_segment_color_secondary_only(self) -> None:
        """Test setting secondary color fills primary from current state."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, color_secondary=(0, 255, 0))

    async def test_segment_color_tertiary_only(self) -> None:
        """Test setting tertiary color fills primary and secondary."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, color_tertiary=(0, 0, 255))

    async def test_segment_all_colors(self) -> None:
        """Test setting all three colors at once."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(
                    0,
                    color_primary=(255, 0, 0),
                    color_secondary=(0, 255, 0),
                    color_tertiary=(0, 0, 255),
                )

    async def test_segment_with_transition(self) -> None:
        """Test setting segment with transition."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, brightness=100, transition=5)

    async def test_segment_calls_update_when_no_device(self) -> None:
        """Test segment() calls update() if no device loaded."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.segment(0, on=True)

    async def test_segment_no_device_raises(self) -> None:
        """Test segment() raises if update cannot load device."""
        with aioresponses() as mocked:
            # update() succeeds but returns empty -> triggers empty response error
            # Mock to return valid data for the first update() call,
            # but we need to make _device remain None.
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                # Patch update to do nothing (leave _device as None)
                with patch.object(wled, "update", new_callable=AsyncMock):
                    with pytest.raises(WLEDError, match="Unable to communicate"):
                        await wled.segment(0, on=True)

    async def test_segment_individual(self) -> None:
        """Test setting individual LED colors."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, individual=[(255, 0, 0), (0, 255, 0)])

    async def test_segment_color_tertiary_no_secondary_in_state(self) -> None:
        """Test tertiary color when segment has no secondary color in state."""
        with aioresponses() as mocked:
            # Build device data where the segment color has no secondary
            wled_data = json.loads(json.dumps(WLED_JSON))
            wled_data["state"]["seg"][0]["col"] = [[255, 0, 0]]
            mocked.get(
                "http://example.com/json",
                status=200,
                body=json.dumps(wled_data),
                content_type="application/json",
            )
            mocked.get(
                "http://example.com/presets.json",
                status=200,
                body=json.dumps(PRESETS_JSON),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, color_tertiary=(0, 0, 255))

    async def test_segment_secondary_no_color_in_state(self) -> None:
        """Test secondary color when segment has no color at all in state."""
        with aioresponses() as mocked:
            # Build device data where the segment has no col
            wled_data = json.loads(json.dumps(WLED_JSON))
            del wled_data["state"]["seg"][0]["col"]
            mocked.get(
                "http://example.com/json",
                status=200,
                body=json.dumps(wled_data),
                content_type="application/json",
            )
            mocked.get(
                "http://example.com/presets.json",
                status=200,
                body=json.dumps(PRESETS_JSON),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                # color is None, so it should use (0,0,0) fallback
                await wled.segment(0, color_secondary=(0, 255, 0))

    async def test_segment_tertiary_no_color_in_state(self) -> None:
        """Test tertiary color when segment has no color at all in state."""
        with aioresponses() as mocked:
            # Build device data where the segment has no col
            wled_data = json.loads(json.dumps(WLED_JSON))
            del wled_data["state"]["seg"][0]["col"]
            mocked.get(
                "http://example.com/json",
                status=200,
                body=json.dumps(wled_data),
                content_type="application/json",
            )
            mocked.get(
                "http://example.com/presets.json",
                status=200,
                body=json.dumps(PRESETS_JSON),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.segment(0, color_tertiary=(0, 0, 255))


# =========================================================================
# Section 13: WLED client - preset/playlist/transition/live/sync/nightlight
# =========================================================================


class TestWLEDPresetPlaylist:
    """Tests for WLED.preset() and WLED.playlist() methods."""

    async def _get_wled_with_device(
        self, mocked: aioresponses, session: aiohttp.ClientSession
    ) -> WLED:
        """Create a WLED instance with a loaded device."""
        _mock_json_and_presets(mocked)
        wled = WLED("example.com", session=session)
        await wled.update()
        return wled

    async def test_preset_by_id(self) -> None:
        """Test setting a preset by integer ID."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.preset(1)

    async def test_preset_by_name(self) -> None:
        """Test setting a preset by name."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.preset("My Preset")

    async def test_preset_by_object(self) -> None:
        """Test setting a preset using a Preset object."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                preset_obj = wled._device.presets[1]
                await wled.preset(preset_obj)

    async def test_preset_name_not_found(self) -> None:
        """Test setting a preset by name that does not exist passes string."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.preset("NonExistent")

    async def test_playlist_by_id(self) -> None:
        """Test setting a playlist by integer ID."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.playlist(2)

    async def test_playlist_by_name(self) -> None:
        """Test setting a playlist by name."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.playlist("My Playlist")

    async def test_playlist_by_object(self) -> None:
        """Test setting a playlist using a Playlist object."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                playlist_obj = wled._device.playlists[2]
                await wled.playlist(playlist_obj)

    async def test_playlist_name_not_found(self) -> None:
        """Test setting a playlist by name that does not exist passes string."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.post(
                    "http://example.com/json/state",
                    status=200,
                    body="{}",
                    content_type="application/json",
                )
                await wled.playlist("NonExistent")


class TestWLEDTransition:
    """Tests for WLED.transition() method."""

    async def test_transition(self) -> None:
        """Test setting default transition."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.transition(10)


class TestWLEDLive:
    """Tests for WLED.live() method."""

    async def test_live(self) -> None:
        """Test setting live data override."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.live(LiveDataOverride.ON)


class TestWLEDSync:
    """Tests for WLED.sync() method."""

    async def test_sync_send(self) -> None:
        """Test setting sync send."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.sync(send=True)

    async def test_sync_receive(self) -> None:
        """Test setting sync receive."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.sync(receive=True)


class TestWLEDNightlight:
    """Tests for WLED.nightlight() method."""

    async def test_nightlight_on(self) -> None:
        """Test turning on nightlight."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.nightlight(on=True)

    async def test_nightlight_all_params(self) -> None:
        """Test nightlight with all parameters."""
        with aioresponses() as mocked:
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.nightlight(
                    duration=30, fade=True, on=True, target_brightness=50
                )


# =========================================================================
# Section 14: WLED client - reset, close, context manager, connected
# =========================================================================


class TestWLEDLifecycle:
    """Tests for WLED reset, close, context manager, and connected property."""

    async def test_reset(self) -> None:
        """Test reset method calls /reset."""
        with aioresponses() as mocked:
            mocked.get(
                "http://example.com/reset",
                status=200,
                body="OK",
                content_type="text/plain",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.reset()

    async def test_close_with_internal_session(self) -> None:
        """Test close() closes internally created session."""
        with aioresponses() as mocked:
            mocked.get(
                "http://example.com/",
                status=200,
                body='{"status": "ok"}',
                content_type="application/json",
            )
            wled = WLED("example.com")
            await wled.request("/")
            assert wled.session is not None
            assert wled._close_session is True
            await wled.close()

    async def test_close_with_external_session(self) -> None:
        """Test close() does not close externally provided session."""
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            assert wled._close_session is False
            await wled.close()
            assert not session.closed

    async def test_context_manager(self) -> None:
        """Test async context manager."""
        with aioresponses() as mocked:
            mocked.get(
                "http://example.com/",
                status=200,
                body='{"status": "ok"}',
                content_type="application/json",
            )
            async with WLED("example.com") as wled:
                response = await wled.request("/")
                assert response["status"] == "ok"

    async def test_connected_no_client(self) -> None:
        """Test connected returns False when no WebSocket client."""
        wled = WLED("example.com")
        assert wled.connected is False

    async def test_connected_with_closed_client(self) -> None:
        """Test connected returns False when client is closed."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = True
        wled._client = mock_client
        assert wled.connected is False

    async def test_connected_with_open_client(self) -> None:
        """Test connected returns True when client is open."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        wled._client = mock_client
        assert wled.connected is True


# =========================================================================
# Section 15: WLED client - connect() and listen()
# =========================================================================


class TestWLEDWebSocket:
    """Tests for WLED WebSocket connect/listen methods."""

    async def test_connect_already_connected(self) -> None:
        """Test connect() returns immediately when already connected."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        wled._client = mock_client
        await wled.connect()
        # Should return without doing anything

    async def test_connect_no_websocket_support(self) -> None:
        """Test connect() raises when device has no WebSocket support."""
        with aioresponses() as mocked:
            # Build data with ws=-1 (no websocket support)
            wled_data = json.loads(json.dumps(WLED_JSON))
            wled_data["info"]["ws"] = -1
            mocked.get(
                "http://example.com/json",
                status=200,
                body=json.dumps(wled_data),
                content_type="application/json",
            )
            mocked.get(
                "http://example.com/presets.json",
                status=200,
                body=json.dumps(PRESETS_JSON),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()
                with pytest.raises(WLEDError, match="does not support WebSockets"):
                    await wled.connect()

    async def test_connect_connection_error(self) -> None:
        """Test connect() raises WLEDConnectionError on connection failure."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()
                with patch.object(
                    session,
                    "ws_connect",
                    side_effect=aiohttp.ClientConnectionError("fail"),
                ):
                    with pytest.raises(WLEDConnectionError):
                        await wled.connect()

    async def test_connect_calls_update_when_no_device(self) -> None:
        """Test connect() calls update() if no device is loaded."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                # Device has ws=0, so connect should try to ws_connect
                with patch.object(
                    session, "ws_connect", new_callable=AsyncMock
                ) as mock_ws:
                    mock_ws.return_value = MagicMock(closed=False)
                    await wled.connect()
                    mock_ws.assert_called_once()

    async def test_listen_not_connected(self) -> None:
        """Test listen() raises when not connected."""
        wled = WLED("example.com")
        with pytest.raises(WLEDError, match="Not connected"):
            await wled.listen(lambda _: None)

    async def test_listen_error_message(self) -> None:
        """Test listen() raises on error message."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.ERROR
        mock_client.receive = AsyncMock(return_value=mock_msg)
        mock_client.exception.return_value = Exception("test error")
        wled._client = mock_client
        wled._device = Device.from_dict(_full_device_data())
        with pytest.raises(WLEDConnectionError):
            await wled.listen(lambda _: None)

    async def test_listen_text_message(self) -> None:
        """Test listen() handles text message and calls callback."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        wled._client = mock_client
        wled._device = Device.from_dict(_full_device_data())

        state_update = json.dumps({"state": WLED_JSON["state"]})
        text_msg = MagicMock()
        text_msg.type = aiohttp.WSMsgType.TEXT
        text_msg.json.return_value = json.loads(state_update)

        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSE

        mock_client.receive = AsyncMock(side_effect=[text_msg, close_msg])

        callback = MagicMock()
        with pytest.raises(WLEDConnectionClosedError):
            await wled.listen(callback)

        callback.assert_called_once()

    async def test_listen_closed_message(self) -> None:
        """Test listen() raises on close message."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        wled._client = mock_client
        wled._device = Device.from_dict(_full_device_data())

        close_msg = MagicMock()
        close_msg.type = aiohttp.WSMsgType.CLOSED

        mock_client.receive = AsyncMock(return_value=close_msg)

        with pytest.raises(WLEDConnectionClosedError):
            await wled.listen(lambda _: None)

    async def test_disconnect(self) -> None:
        """Test disconnect() closes the WebSocket client."""
        wled = WLED("example.com")
        mock_client = MagicMock()
        mock_client.closed = False
        mock_client.close = AsyncMock()
        wled._client = mock_client
        await wled.disconnect()
        mock_client.close.assert_called_once()

    async def test_disconnect_not_connected(self) -> None:
        """Test disconnect() is a no-op when not connected."""
        wled = WLED("example.com")
        await wled.disconnect()  # Should not raise


# =========================================================================
# Section 16: WLED client - request details
# =========================================================================


class TestWLEDRequest:
    """Tests for WLED.request() edge cases."""

    async def test_post_state_adds_v_true(self) -> None:
        """Test POST to /json/state adds v=True to data."""
        state_response = json.dumps(WLED_JSON["state"])
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body=state_response,
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.update()  # Need device for state update path
                await wled.request(
                    "/json/state", method="POST", data={"on": True}
                )

    async def test_client_error_raises_connection_error(self) -> None:
        """Test aiohttp.ClientError raises WLEDConnectionError."""
        with aioresponses() as mocked:
            mocked.get(
                "http://example.com/test",
                exception=aiohttp.ClientError("fail"),
            )
            mocked.get(
                "http://example.com/test",
                exception=aiohttp.ClientError("fail"),
            )
            mocked.get(
                "http://example.com/test",
                exception=aiohttp.ClientError("fail"),
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                with pytest.raises(WLEDConnectionError):
                    await wled.request("/test")


# =========================================================================
# Section 17: WLED client - upgrade() method
# =========================================================================


class TestWLEDUpgrade:
    """Tests for WLED.upgrade() method."""

    async def _get_wled_with_device(
        self,
        mocked: aioresponses,
        session: aiohttp.ClientSession,
        arch: str = "esp32",
        version: str = "0.14.0",
        wifi_bssid: str = "AA:BB:CC:DD:EE:FF",
    ) -> WLED:
        """Create a WLED instance with a specific architecture."""
        wled_data = json.loads(json.dumps(WLED_JSON))
        wled_data["info"]["arch"] = arch
        wled_data["info"]["ver"] = version
        if wifi_bssid is not None:
            wled_data["info"]["wifi"]["bssid"] = wifi_bssid
        mocked.get(
            "http://example.com/json",
            status=200,
            body=json.dumps(wled_data),
            content_type="application/json",
        )
        mocked.get(
            "http://example.com/presets.json",
            status=200,
            body=json.dumps(PRESETS_JSON),
            content_type="application/json",
        )
        wled = WLED("example.com", session=session)
        await wled.update()
        return wled

    async def test_upgrade_unsupported_architecture(self) -> None:
        """Test upgrade raises for unsupported architecture."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(
                    mocked, session, arch="unknown_arch"
                )
                with pytest.raises(WLEDUpgradeError, match="only supported"):
                    await wled.upgrade(version="0.15.0")

    async def test_upgrade_same_version(self) -> None:
        """Test upgrade raises when already on requested version."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                with pytest.raises(WLEDUpgradeError, match="already running"):
                    await wled.upgrade(version="0.14.0")

    async def test_upgrade_no_version(self) -> None:
        """Test upgrade raises when current version is unknown."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                # Build device with invalid version
                wled_data = json.loads(json.dumps(WLED_JSON))
                wled_data["info"]["ver"] = "0.14.0"
                mocked.get(
                    "http://example.com/json",
                    status=200,
                    body=json.dumps(wled_data),
                    content_type="application/json",
                )
                mocked.get(
                    "http://example.com/presets.json",
                    status=200,
                    body=json.dumps(PRESETS_JSON),
                    content_type="application/json",
                )
                wled = WLED("example.com", session=session)
                await wled.update()
                # Manually set version to None
                wled._device.info.version = None
                with pytest.raises(WLEDUpgradeError, match="version is unknown"):
                    await wled.upgrade(version="0.15.0")

    async def test_upgrade_calls_update_when_no_device(self) -> None:
        """Test upgrade() calls update() if no device loaded."""
        with aioresponses() as mocked:
            _mock_json_and_presets(mocked)
            # Mock the download and upload
            mocked.get(
                "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                status=200,
                body=b"fake firmware",
            )
            mocked.post(
                "http://example.com/update",
                status=200,
                body="OK",
                content_type="text/plain",
            )
            async with aiohttp.ClientSession() as session:
                wled = WLED("example.com", session=session)
                await wled.upgrade(version="0.15.0")

    async def test_upgrade_no_session_raises(self) -> None:
        """Test upgrade raises when there is no session and no device."""
        wled = WLED("example.com")
        # Set _device to None and session to None; update is mocked to do nothing
        with patch.object(wled, "update", new_callable=AsyncMock):
            with pytest.raises(WLEDUpgradeError, match="Unexpected"):
                await wled.upgrade(version="0.15.0")

    async def test_upgrade_success(self) -> None:
        """Test successful upgrade."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                    status=200,
                    body=b"fake firmware",
                )
                mocked.post(
                    "http://example.com/update",
                    status=200,
                    body="OK",
                    content_type="text/plain",
                )
                await wled.upgrade(version="0.15.0")

    async def test_upgrade_ethernet_board(self) -> None:
        """Test upgrade with Ethernet board (empty bssid)."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(
                    mocked, session, wifi_bssid=""
                )
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32_Ethernet.bin",
                    status=200,
                    body=b"fake firmware",
                )
                mocked.post(
                    "http://example.com/update",
                    status=200,
                    body="OK",
                    content_type="text/plain",
                )
                await wled.upgrade(version="0.15.0")

    async def test_upgrade_esp02_gzip(self) -> None:
        """Test upgrade for esp02 (2M ESP8266) includes .gz suffix."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled_data = json.loads(json.dumps(WLED_JSON))
                wled_data["info"]["arch"] = "esp8266"
                wled_data["info"]["ver"] = "0.14.0"
                # Small filesystem for esp02 detection
                wled_data["info"]["fs"]["t"] = 512
                mocked.get(
                    "http://example.com/json",
                    status=200,
                    body=json.dumps(wled_data),
                    content_type="application/json",
                )
                mocked.get(
                    "http://example.com/presets.json",
                    status=200,
                    body=json.dumps(PRESETS_JSON),
                    content_type="application/json",
                )
                wled = WLED("example.com", session=session)
                await wled.update()
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP02.bin.gz",
                    status=200,
                    body=b"fake firmware",
                )
                mocked.post(
                    "http://example.com/update",
                    status=200,
                    body="OK",
                    content_type="text/plain",
                )
                await wled.upgrade(version="0.15.0")

    async def test_upgrade_404(self) -> None:
        """Test upgrade with 404 download raises WLEDUpgradeError."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.99.0/WLED_0.99.0_ESP32.bin",
                    status=404,
                )
                with pytest.raises(WLEDUpgradeError, match="does not exist"):
                    await wled.upgrade(version="0.99.0")

    async def test_upgrade_other_http_error(self) -> None:
        """Test upgrade with non-404 HTTP error raises WLEDUpgradeError."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                    status=500,
                )
                with pytest.raises(WLEDUpgradeError, match="Could not download"):
                    await wled.upgrade(version="0.15.0")

    async def test_upgrade_connection_error(self) -> None:
        """Test upgrade with connection error raises WLEDConnectionError."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                    exception=aiohttp.ClientError("fail"),
                )
                with pytest.raises(WLEDConnectionError):
                    await wled.upgrade(version="0.15.0")

    async def test_upgrade_timeout(self) -> None:
        """Test upgrade with timeout raises WLEDConnectionTimeoutError."""
        with aioresponses() as mocked:
            async with aiohttp.ClientSession() as session:
                wled = await self._get_wled_with_device(mocked, session)
                wled.request_timeout = 0.001
                mocked.get(
                    "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                    exception=TimeoutError(),
                )
                from wled.exceptions import WLEDConnectionTimeoutError

                with pytest.raises(WLEDConnectionTimeoutError):
                    await wled.upgrade(version="0.15.0")


# =========================================================================
# Section 18: WLEDReleases class
# =========================================================================


class TestWLEDReleases:
    """Tests for WLEDReleases class."""

    async def test_releases_success(self) -> None:
        """Test successful release fetching."""
        releases_data = [
            {
                "tag_name": "v0.15.0",
                "prerelease": False,
            },
            {
                "tag_name": "v0.15.0b1",
                "prerelease": True,
            },
        ]
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body=json.dumps(releases_data),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                releases = await wled_releases.releases()
                assert isinstance(releases, Releases)
                assert releases.stable is not None
                assert str(releases.stable) == "0.15.0"
                assert releases.beta is not None
                assert str(releases.beta) == "0.15.0b1"

    async def test_releases_with_b_in_tag_name(self) -> None:
        """Test releases with 'b' in tag name are treated as beta."""
        releases_data = [
            {
                "tag_name": "v0.14.1b2",
                "prerelease": False,
            },
            {
                "tag_name": "v0.14.0",
                "prerelease": False,
            },
        ]
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body=json.dumps(releases_data),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                releases = await wled_releases.releases()
                assert releases.beta is not None
                assert str(releases.beta) == "0.14.1b2"
                assert releases.stable is not None
                assert str(releases.stable) == "0.14.0"

    async def test_releases_no_beta(self) -> None:
        """Test releases when no beta is available."""
        releases_data = [
            {
                "tag_name": "v0.14.0",
                "prerelease": False,
            },
        ]
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body=json.dumps(releases_data),
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                releases = await wled_releases.releases()
                assert releases.stable is not None
                assert releases.beta is None

    async def test_releases_context_manager(self) -> None:
        """Test WLEDReleases as context manager."""
        releases_data = [
            {"tag_name": "v0.14.0", "prerelease": False},
        ]
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body=json.dumps(releases_data),
                content_type="application/json",
            )
            async with WLEDReleases() as wled_releases:
                releases = await wled_releases.releases()
                assert releases.stable is not None

    async def test_releases_internal_session(self) -> None:
        """Test WLEDReleases creates internal session."""
        releases_data = [
            {"tag_name": "v0.14.0", "prerelease": False},
        ]
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body=json.dumps(releases_data),
                content_type="application/json",
            )
            wled_releases = WLEDReleases()
            assert wled_releases.session is None
            releases = await wled_releases.releases()
            assert wled_releases.session is not None
            assert wled_releases._close_session is True
            await wled_releases.close()

    async def test_releases_close_external_session(self) -> None:
        """Test close() does not close externally provided session."""
        async with aiohttp.ClientSession() as session:
            wled_releases = WLEDReleases(session=session)
            await wled_releases.close()
            assert not session.closed

    async def test_releases_http_error(self) -> None:
        """Test releases raises WLEDError on HTTP error."""
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=500,
                body='{"message": "error"}',
                content_type="application/json",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                with pytest.raises(WLEDError):
                    await wled_releases.releases()

    async def test_releases_http_error_text(self) -> None:
        """Test releases raises WLEDError on HTTP error with text."""
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=403,
                body="Forbidden",
                content_type="text/plain",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                with pytest.raises(WLEDError):
                    await wled_releases.releases()

    async def test_releases_non_json_response(self) -> None:
        """Test releases raises WLEDError on non-JSON response."""
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                status=200,
                body="Not JSON",
                content_type="text/plain",
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                with pytest.raises(WLEDError, match="No JSON"):
                    await wled_releases.releases()

    async def test_releases_timeout(self) -> None:
        """Test releases raises on timeout."""
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=TimeoutError(),
            )
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=TimeoutError(),
            )
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=TimeoutError(),
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session, request_timeout=0.1)
                from wled.exceptions import WLEDConnectionTimeoutError

                with pytest.raises(WLEDConnectionError):
                    await wled_releases.releases()

    async def test_releases_connection_error(self) -> None:
        """Test releases raises on connection error."""
        with aioresponses() as mocked:
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=aiohttp.ClientError("fail"),
            )
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=aiohttp.ClientError("fail"),
            )
            mocked.get(
                "https://api.github.com/repos/Aircoookie/WLED/releases",
                exception=aiohttp.ClientError("fail"),
            )
            async with aiohttp.ClientSession() as session:
                wled_releases = WLEDReleases(session=session)
                with pytest.raises(WLEDConnectionError):
                    await wled_releases.releases()


# =========================================================================
# Section 19: Utils
# =========================================================================


class TestUtils:
    """Tests for utility functions."""

    def test_get_awesome_version(self) -> None:
        """Test get_awesome_version returns AwesomeVersion."""
        version = get_awesome_version("0.14.0")
        assert isinstance(version, AwesomeVersion)
        assert str(version) == "0.14.0"

    def test_get_awesome_version_cached(self) -> None:
        """Test get_awesome_version returns cached result."""
        v1 = get_awesome_version("1.2.3")
        v2 = get_awesome_version("1.2.3")
        assert v1 is v2


# =========================================================================
# Section 20: Releases model
# =========================================================================


class TestReleasesModel:
    """Tests for Releases model."""

    def test_releases_from_dict(self) -> None:
        """Test Releases deserialization."""
        releases = Releases.from_dict(
            {"stable": "0.14.0", "beta": "0.15.0b1"}
        )
        assert releases.stable is not None
        assert releases.beta is not None

    def test_releases_none_values(self) -> None:
        """Test Releases with None values."""
        releases = Releases.from_dict({"stable": "", "beta": ""})
        assert releases.stable is None
        assert releases.beta is None


# =========================================================================
# Section: Real-world fixture tests (from Home Assistant core)
# =========================================================================


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES_DIR / name).read_text())


class TestRealWorldFixtures:
    """Test parsing real-world WLED device responses from HA core fixtures."""

    def test_rgb_device(self) -> None:
        """Test parsing a real RGB WLED device response."""
        data = _load_fixture("rgb.json")
        data["presets"] = {}
        device = Device.from_dict(data)

        assert device.info.name == "WLED RGB Light"
        assert device.info.version == AwesomeVersion("0.14.4")
        assert device.info.architecture == "esp32"
        assert device.info.mac_address == "aabbccddeeff"
        assert device.info.websocket is None  # ws: -1 becomes None
        assert device.info.leds.count == 30
        assert device.info.leds.max_segments == 32
        assert device.info.wifi is not None
        assert device.info.wifi.signal == 100
        assert device.info.wifi.channel == 11
        assert device.info.filesystem.total == 983
        assert device.info.filesystem.used == 12

        # State assertions
        assert device.state.on is True
        assert device.state.brightness == 128
        assert device.state.playlist_id is None  # pl: -1 becomes None
        assert device.state.preset_id is None  # ps: -1 becomes None

        # Two segments
        assert len(device.state.segments) == 2
        seg0 = device.state.segments[0]
        seg1 = device.state.segments[1]
        assert seg0.on is True
        assert seg0.selected is False
        assert seg0.color is not None
        assert list(seg0.color.primary) == [127, 172, 255]
        assert seg1.selected is True
        assert seg1.reverse is True
        assert seg1.effect_id == 3
        assert seg1.palette_id == 1

        # Effects and palettes
        assert len(device.effects) == 187
        assert device.effects[0].name == "Solid"
        assert device.effects[1].name == "Blink"
        assert len(device.palettes) == 71
        assert device.palettes[0].name == "Default"

    def test_rgbw_device(self) -> None:
        """Test parsing a real RGBW WLED device response."""
        data = _load_fixture("rgbw.json")
        data["presets"] = {}
        device = Device.from_dict(data)

        assert device.info.name == "WLED RGBW Light"
        assert device.info.websocket is None  # ws: -1

        # RGBW colors have 4 bytes
        seg = device.state.segments[0]
        assert seg.color is not None
        assert list(seg.color.primary) == [255, 0, 0, 139]
        assert list(seg.color.secondary) == [0, 0, 0, 0]
        assert list(seg.color.tertiary) == [0, 0, 0, 0]

    def test_cct_device(self) -> None:
        """Test parsing a real CCT WLED device response."""
        data = _load_fixture("cct.json")
        data["presets"] = {}
        device = Device.from_dict(data)

        assert device.info.name == "WLED CCT light"
        assert device.info.version == AwesomeVersion("0.15.0-b3")
        assert device.info.websocket == 1  # ws: 1 stays as-is

        # Active preset
        assert device.state.preset_id == 2
        assert device.state.playlist_id is None

        # CCT segment has a 4-byte color
        seg = device.state.segments[0]
        assert seg.cct == 53
        assert seg.color is not None
        assert list(seg.color.primary) == [0, 0, 0, 255]

    def test_rgb_websocket_device(self) -> None:
        """Test parsing an RGB device with WebSocket support."""
        data = _load_fixture("rgb_websocket.json")
        data["presets"] = {}
        device = Device.from_dict(data)

        assert device.info.name == "WLED WebSocket"
        assert device.info.websocket == 0  # ws: 0 means supported, 0 clients
        assert device.info.version == AwesomeVersion("0.99.0")

    def test_rgb_single_segment_device(self) -> None:
        """Test parsing an RGB device with a single segment."""
        data = _load_fixture("rgb_single_segment.json")
        data["presets"] = {}
        device = Device.from_dict(data)

        assert device.info.name == "WLED RGB Light"
        assert device.info.version == AwesomeVersion("1.0.0b4")
        assert len(device.state.segments) == 1

        seg = device.state.segments[0]
        assert seg.on is True
        assert seg.selected is True
        assert seg.color is not None
        assert list(seg.color.primary) == [127, 172, 255]

    @pytest.mark.parametrize(
        "fixture",
        [
            "rgb.json",
            "rgbw.json",
            "cct.json",
            "rgb_websocket.json",
            "rgb_single_segment.json",
        ],
    )
    def test_fixture_parses_without_errors(self, fixture: str) -> None:
        """Test that all fixtures parse without errors and produce valid devices."""
        data = _load_fixture(fixture)
        data["presets"] = {}
        device = Device.from_dict(data)

        # All devices must have valid info and state
        assert device.info is not None
        assert device.state is not None
        assert device.info.version is not None
        assert len(device.effects) > 0
        assert len(device.palettes) > 0
