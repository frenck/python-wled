"""Tests for `wled.wled` (WLED client)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from wled import WLED, Device, Releases
from wled.const import LiveDataOverride
from wled.exceptions import (
    WLEDConnectionClosedError,
    WLEDConnectionError,
    WLEDConnectionTimeoutError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDUpgradeError,
)
from wled.wled import WLEDReleases

from .conftest import full_device_data, load_fixture_json, mock_json_and_presets

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
# Section 10: WLED client - update() method
# =========================================================================


async def test_update_creates_device() -> None:
    """Test that update() creates a Device from API responses."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            device = await wled.update()
            assert isinstance(device, Device)
            assert device.info.name == "WLED"
            assert device.state.on is True


async def test_update_uses_existing_device() -> None:
    """Test that subsequent update() calls use update_from_dict."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        mock_json_and_presets(mocked)
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            device1 = await wled.update()
            device2 = await wled.update()
            assert device1 is device2


async def test_update_empty_json_response() -> None:
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


async def test_update_empty_presets_response() -> None:
    """Test update() raises on empty /presets.json response."""
    with aioresponses() as mocked:
        # Backoff on update() retries 3 times for WLEDEmptyResponseError
        for _ in range(3):
            mocked.get(
                "http://example.com/json",
                status=200,
                body=json.dumps(load_fixture_json("wled")),
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


async def test_master_brightness() -> None:
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


async def test_master_on() -> None:
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


async def test_master_transition() -> None:
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


async def test_master_all_params() -> None:
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


async def _get_wled_with_device(
    mocked: aioresponses, session: aiohttp.ClientSession
) -> WLED:
    """Create a WLED instance with a loaded device."""
    mock_json_and_presets(mocked)
    wled = WLED("example.com", session=session)
    await wled.update()
    return wled


async def test_segment_basic() -> None:
    """Test basic segment control."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, brightness=200, on=True)


async def test_segment_effect_by_name() -> None:
    """Test setting segment effect by name."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, effect="Blink")


async def test_segment_palette_by_name() -> None:
    """Test setting segment palette by name."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, palette="Random Cycle")


async def test_segment_color_primary() -> None:
    """Test setting primary color."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, color_primary=(255, 0, 0))


async def test_segment_color_secondary_only() -> None:
    """Test setting secondary color fills primary from current state."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, color_secondary=(0, 255, 0))


async def test_segment_color_tertiary_only() -> None:
    """Test setting tertiary color fills primary and secondary."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, color_tertiary=(0, 0, 255))


async def test_segment_all_colors() -> None:
    """Test setting all three colors at once."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
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


async def test_segment_with_transition() -> None:
    """Test setting segment with transition."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, brightness=100, transition=5)


async def test_segment_calls_update_when_no_device() -> None:
    """Test segment() calls update() if no device loaded."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        mocked.post(
            "http://example.com/json/state",
            status=200,
            body="{}",
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            await wled.segment(0, on=True)


async def test_segment_no_device_raises() -> None:
    """Test segment() raises if update cannot load device."""
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        # Patch update to do nothing (leave _device as None)
        with (
            patch.object(wled, "update", new_callable=AsyncMock),
            pytest.raises(WLEDError, match="Unable to communicate"),
        ):
            await wled.segment(0, on=True)


async def test_segment_individual() -> None:
    """Test setting individual LED colors."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.segment(0, individual=[(255, 0, 0), (0, 255, 0)])


async def test_segment_color_tertiary_no_secondary_in_state() -> None:
    """Test tertiary color when segment has no secondary color in state."""
    with aioresponses() as mocked:
        # Build device data where the segment color has no secondary
        wled_data = load_fixture_json("wled")
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
            body=json.dumps(load_fixture_json("presets")),
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


async def test_segment_secondary_no_color_in_state() -> None:
    """Test secondary color when segment has no color at all in state."""
    with aioresponses() as mocked:
        # Build device data where the segment has no col
        wled_data = load_fixture_json("wled")
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
            body=json.dumps(load_fixture_json("presets")),
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


async def test_segment_tertiary_no_color_in_state() -> None:
    """Test tertiary color when segment has no color at all in state."""
    with aioresponses() as mocked:
        # Build device data where the segment has no col
        wled_data = load_fixture_json("wled")
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
            body=json.dumps(load_fixture_json("presets")),
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


async def test_preset_by_id() -> None:
    """Test setting a preset by integer ID."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.preset(1)


async def test_preset_by_name() -> None:
    """Test setting a preset by name."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.preset("My Preset")


async def test_preset_by_object() -> None:
    """Test setting a preset using a Preset object."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            assert wled._device is not None  # pylint: disable=protected-access
            preset_obj = wled._device.presets[1]  # pylint: disable=protected-access
            await wled.preset(preset_obj)


async def test_preset_name_not_found() -> None:
    """Test setting a preset by name that does not exist passes string."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.preset("NonExistent")


async def test_playlist_by_id() -> None:
    """Test setting a playlist by integer ID."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.playlist(2)


async def test_playlist_by_name() -> None:
    """Test setting a playlist by name."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.playlist("My Playlist")


async def test_playlist_by_object() -> None:
    """Test setting a playlist using a Playlist object."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            assert wled._device is not None  # pylint: disable=protected-access
            playlist_obj = wled._device.playlists[2]  # pylint: disable=protected-access
            await wled.playlist(playlist_obj)


async def test_playlist_name_not_found() -> None:
    """Test setting a playlist by name that does not exist passes string."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device(mocked, session)
            mocked.post(
                "http://example.com/json/state",
                status=200,
                body="{}",
                content_type="application/json",
            )
            await wled.playlist("NonExistent")


async def test_transition() -> None:
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


async def test_live() -> None:
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


async def test_sync_send() -> None:
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


async def test_sync_receive() -> None:
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


async def test_nightlight_on() -> None:
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


async def test_nightlight_all_params() -> None:
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
            await wled.nightlight(duration=30, fade=True, on=True, target_brightness=50)


# =========================================================================
# Section 14: WLED client - reset, close, context manager, connected
# =========================================================================


async def test_reset() -> None:
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


async def test_close_with_internal_session() -> None:
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
        assert wled._close_session is True  # pylint: disable=protected-access
        await wled.close()


async def test_close_with_external_session() -> None:
    """Test close() does not close externally provided session."""
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        assert wled._close_session is False  # pylint: disable=protected-access
        await wled.close()
        assert not session.closed


async def test_context_manager() -> None:
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


async def test_connected_no_client() -> None:
    """Test connected returns False when no WebSocket client."""
    wled = WLED("example.com")
    assert wled.connected is False


async def test_connected_with_closed_client() -> None:
    """Test connected returns False when client is closed."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = True
    wled._client = mock_client  # pylint: disable=protected-access
    assert wled.connected is False


async def test_connected_with_open_client() -> None:
    """Test connected returns True when client is open."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    wled._client = mock_client  # pylint: disable=protected-access
    assert wled.connected is True


# =========================================================================
# Section 15: WLED client - connect() and listen()
# =========================================================================


async def test_connect_already_connected() -> None:
    """Test connect() returns immediately when already connected."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    wled._client = mock_client  # pylint: disable=protected-access
    await wled.connect()
    # Should return without doing anything


async def test_connect_no_websocket_support() -> None:
    """Test connect() raises when device has no WebSocket support."""
    with aioresponses() as mocked:
        # Build data with ws=-1 (no websocket support)
        wled_data = load_fixture_json("wled")
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
            body=json.dumps(load_fixture_json("presets")),
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            await wled.update()
            with pytest.raises(WLEDError, match="does not support WebSockets"):
                await wled.connect()


async def test_connect_connection_error() -> None:
    """Test connect() raises WLEDConnectionError on connection failure."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            await wled.update()
            with (
                patch.object(
                    session,
                    "ws_connect",
                    side_effect=aiohttp.ClientConnectionError("fail"),
                ),
                pytest.raises(WLEDConnectionError),
            ):
                await wled.connect()


async def test_connect_calls_update_when_no_device() -> None:
    """Test connect() calls update() if no device is loaded."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            # Device has ws=0, so connect should try to ws_connect
            with patch.object(session, "ws_connect", new_callable=AsyncMock) as mock_ws:
                mock_ws.return_value = MagicMock(closed=False)
                await wled.connect()
                mock_ws.assert_called_once()


async def test_listen_not_connected() -> None:
    """Test listen() raises when not connected."""
    wled = WLED("example.com")
    with pytest.raises(WLEDError, match="Not connected"):
        await wled.listen(lambda _: None)


async def test_listen_error_message() -> None:
    """Test listen() raises on error message."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    mock_msg = MagicMock()
    mock_msg.type = aiohttp.WSMsgType.ERROR
    mock_client.receive = AsyncMock(return_value=mock_msg)
    mock_client.exception.return_value = Exception("test error")
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access
    with pytest.raises(WLEDConnectionError):
        await wled.listen(lambda _: None)


async def test_listen_text_message() -> None:
    """Test listen() handles text message and calls callback."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    state_update = json.dumps({"state": load_fixture_json("wled")["state"]})
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


async def test_listen_closed_message() -> None:
    """Test listen() raises on close message."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    close_msg = MagicMock()
    close_msg.type = aiohttp.WSMsgType.CLOSED

    mock_client.receive = AsyncMock(return_value=close_msg)

    with pytest.raises(WLEDConnectionClosedError):
        await wled.listen(lambda _: None)


async def test_disconnect() -> None:
    """Test disconnect() closes the WebSocket client."""
    wled = WLED("example.com")
    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    await wled.disconnect()
    mock_client.close.assert_called_once()


async def test_disconnect_not_connected() -> None:
    """Test disconnect() is a no-op when not connected."""
    wled = WLED("example.com")
    await wled.disconnect()  # Should not raise


# =========================================================================
# Section 16: WLED client - request details
# =========================================================================


async def test_post_state_adds_v_true() -> None:
    """Test POST to /json/state adds v=True to data."""
    state_response = json.dumps(load_fixture_json("wled")["state"])
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
        mocked.post(
            "http://example.com/json/state",
            status=200,
            body=state_response,
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            await wled.update()  # Need device for state update path
            await wled.request("/json/state", method="POST", data={"on": True})


async def test_client_error_raises_connection_error() -> None:
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


async def _get_wled_with_device_for_upgrade(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    mocked: aioresponses,
    session: aiohttp.ClientSession,
    arch: str = "esp32",
    version: str = "0.14.0",
    wifi_bssid: str = "AA:BB:CC:DD:EE:FF",
) -> WLED:
    """Create a WLED instance with a specific architecture."""
    wled_data = load_fixture_json("wled")
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
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    wled = WLED("example.com", session=session)
    await wled.update()
    return wled


async def test_upgrade_unsupported_architecture() -> None:
    """Test upgrade raises for unsupported architecture."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(
                mocked, session, arch="unknown_arch"
            )
            with pytest.raises(WLEDUpgradeError, match="only supported"):
                await wled.upgrade(version="0.15.0")


async def test_upgrade_same_version() -> None:
    """Test upgrade raises when already on requested version."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
            with pytest.raises(WLEDUpgradeError, match="already running"):
                await wled.upgrade(version="0.14.0")


async def test_upgrade_no_version() -> None:
    """Test upgrade raises when current version is unknown."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            # Build device with invalid version
            wled_data = load_fixture_json("wled")
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
                body=json.dumps(load_fixture_json("presets")),
                content_type="application/json",
            )
            wled = WLED("example.com", session=session)
            await wled.update()
            assert wled._device is not None  # pylint: disable=protected-access
            # Manually set version to None
            wled._device.info.version = None  # pylint: disable=protected-access
            with pytest.raises(WLEDUpgradeError, match="version is unknown"):
                await wled.upgrade(version="0.15.0")


async def test_upgrade_calls_update_when_no_device() -> None:
    """Test upgrade() calls update() if no device loaded."""
    with aioresponses() as mocked:
        mock_json_and_presets(mocked)
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


async def test_upgrade_no_session_raises() -> None:
    """Test upgrade raises when there is no session and no device."""
    wled = WLED("example.com")
    # Set _device to None and session to None; update is mocked to do nothing
    with (
        patch.object(wled, "update", new_callable=AsyncMock),
        pytest.raises(WLEDUpgradeError, match="Unexpected"),
    ):
        await wled.upgrade(version="0.15.0")


async def test_upgrade_success() -> None:
    """Test successful upgrade."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
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


async def test_upgrade_ethernet_board() -> None:
    """Test upgrade with Ethernet board (empty bssid)."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(
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


async def test_upgrade_esp02_gzip() -> None:
    """Test upgrade for esp02 (2M ESP8266) includes .gz suffix."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled_data = load_fixture_json("wled")
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
                body=json.dumps(load_fixture_json("presets")),
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


async def test_upgrade_404() -> None:
    """Test upgrade with 404 download raises WLEDUpgradeError."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
            mocked.get(
                "https://github.com/Aircoookie/WLED/releases/download/v0.99.0/WLED_0.99.0_ESP32.bin",
                status=404,
            )
            with pytest.raises(WLEDUpgradeError, match="does not exist"):
                await wled.upgrade(version="0.99.0")


async def test_upgrade_other_http_error() -> None:
    """Test upgrade with non-404 HTTP error raises WLEDUpgradeError."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
            mocked.get(
                "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                status=500,
            )
            with pytest.raises(WLEDUpgradeError, match="Could not download"):
                await wled.upgrade(version="0.15.0")


async def test_upgrade_connection_error() -> None:
    """Test upgrade with connection error raises WLEDConnectionError."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
            mocked.get(
                "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                exception=aiohttp.ClientError("fail"),
            )
            with pytest.raises(WLEDConnectionError):
                await wled.upgrade(version="0.15.0")


async def test_upgrade_timeout() -> None:
    """Test upgrade with timeout raises WLEDConnectionTimeoutError."""
    with aioresponses() as mocked:
        async with aiohttp.ClientSession() as session:
            wled = await _get_wled_with_device_for_upgrade(mocked, session)
            wled.request_timeout = 0.001
            mocked.get(
                "https://github.com/Aircoookie/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
                exception=TimeoutError(),
            )
            with pytest.raises(WLEDConnectionTimeoutError):
                await wled.upgrade(version="0.15.0")


# =========================================================================
# Section 18: WLEDReleases class
# =========================================================================


async def test_releases_success() -> None:
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


async def test_releases_with_b_in_tag_name() -> None:
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


async def test_releases_no_beta() -> None:
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


async def test_releases_context_manager() -> None:
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


async def test_releases_internal_session() -> None:
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
        await wled_releases.releases()
        assert wled_releases.session is not None
        assert wled_releases._close_session is True  # pylint: disable=protected-access
        await wled_releases.close()


async def test_releases_close_external_session() -> None:
    """Test close() does not close externally provided session."""
    async with aiohttp.ClientSession() as session:
        wled_releases = WLEDReleases(session=session)
        await wled_releases.close()
        assert not session.closed


async def test_releases_http_error() -> None:
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


async def test_releases_http_error_text() -> None:
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


async def test_releases_non_json_response() -> None:
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


async def test_releases_timeout() -> None:
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

            with pytest.raises(WLEDConnectionError):
                await wled_releases.releases()


async def test_releases_connection_error() -> None:
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
