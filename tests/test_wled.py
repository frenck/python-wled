"""Tests for `wled.wled` (WLED client)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import orjson
import pytest
from aioresponses import aioresponses
from yarl import URL

from wled import WLED, Device, Releases
from wled.const import LiveDataOverride
from wled.exceptions import (
    WLEDConnectionClosedError,
    WLEDConnectionError,
    WLEDConnectionTimeoutError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDInvalidResponseError,
    WLEDUpgradeError,
)
from wled.wled import WLEDReleases

from .conftest import full_device_data, load_fixture_json, mock_json_and_presets


def assert_post_payload(mocked: aioresponses, path: str, expected: dict) -> None:
    """Assert a POST request payload sent to WLED."""
    if not mocked.requests or not (
        requests := mocked.requests.get(("POST", URL(path)))
    ):
        msg = f"No POST request made to {path}"
        raise AssertionError(msg)
    request_call = requests[-1]
    assert orjson.loads(request_call.kwargs["data"]) == expected


# =========================================================================
# Section 1: Existing tests (preserved)
# =========================================================================


async def test_json_request(responses: aioresponses, wled: WLED) -> None:
    """Test JSON response is handled correctly."""
    responses.get(
        "http://example.com/",
        status=200,
        body='{"status": "ok"}',
        content_type="application/json",
    )

    response = await wled.request("/")

    assert response["status"] == "ok"


async def test_text_request(responses: aioresponses, wled: WLED) -> None:
    """Test non-JSON response is handled correctly."""
    responses.get(
        "http://example.com/",
        status=200,
        body="OK",
        content_type="text/plain",
    )

    response = await wled.request("/")

    assert response == "OK"


async def test_internal_session(responses: aioresponses) -> None:
    """Test internal session is created and works correctly."""
    responses.get(
        "http://example.com/",
        status=200,
        body='{"status": "ok"}',
        content_type="application/json",
    )
    async with WLED("example.com") as wled:
        response = await wled.request("/")
        assert response["status"] == "ok"


async def test_post_request(responses: aioresponses, wled: WLED) -> None:
    """Test POST requests are handled correctly."""
    responses.post(
        "http://example.com/",
        status=200,
        body="OK",
        content_type="text/plain",
    )

    response = await wled.request("/", method="POST")

    assert response == "OK"


async def test_backoff(responses: aioresponses, wled: WLED) -> None:
    """Test requests are handled with retries."""
    responses.get("http://example.com/", exception=TimeoutError())
    responses.get("http://example.com/", exception=TimeoutError())
    responses.get(
        "http://example.com/",
        status=200,
        body="OK",
        content_type="text/plain",
    )
    wled.request_timeout = 0.1

    response = await wled.request("/")

    assert response == "OK"


async def test_timeout(responses: aioresponses, wled: WLED) -> None:
    """Test request timeout from WLED."""
    # Backoff will try 3 times
    responses.get("http://example.com/", exception=TimeoutError())
    responses.get("http://example.com/", exception=TimeoutError())
    responses.get("http://example.com/", exception=TimeoutError())
    wled.request_timeout = 0.1

    with pytest.raises(WLEDConnectionError):
        assert await wled.request("/")


async def test_http_error404(responses: aioresponses, wled: WLED) -> None:
    """Test HTTP 404 response handling."""
    responses.get(
        "http://example.com/",
        status=404,
        body="OMG PUPPIES!",
        content_type="text/plain",
    )

    with pytest.raises(WLEDError):
        assert await wled.request("/")


async def test_http_error500(responses: aioresponses, wled: WLED) -> None:
    """Test HTTP 500 response handling."""
    responses.get(
        "http://example.com/",
        status=500,
        body='{"status":"nok"}',
        content_type="application/json",
    )

    with pytest.raises(WLEDError):
        assert await wled.request("/")


# =========================================================================
# Section 10: WLED client - update() method
# =========================================================================


async def test_update_creates_device(responses: aioresponses, wled: WLED) -> None:
    """Test that update() creates a Device from API responses."""
    mock_json_and_presets(responses)

    device = await wled.update()

    assert isinstance(device, Device)
    assert device.info.name == "WLED"
    assert device.state.on is True


async def test_update_uses_existing_device(responses: aioresponses, wled: WLED) -> None:
    """Test that subsequent update() calls use update_from_dict."""
    mock_json_and_presets(responses)
    mock_json_and_presets(responses)

    device1 = await wled.update()
    device2 = await wled.update()

    assert device1 is device2


async def test_update_empty_json_response(responses: aioresponses, wled: WLED) -> None:
    """Test update() raises on empty /json response."""
    # Backoff on update() retries 3 times for WLEDEmptyResponseError
    for _ in range(3):
        responses.get(
            "http://example.com/json",
            status=200,
            body="",
            content_type="text/plain",
        )

    with pytest.raises(WLEDEmptyResponseError):
        await wled.update()


async def test_update_invalid_json_response(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() raises on invalid /json response."""
    responses.get(
        "http://example.com/json",
        status=200,
        body="AAAA",
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError):
        await wled.update()


async def test_update_invalid_presets_response(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() raises on invalid /presets.json response."""
    wled_data = load_fixture_json("wled")
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body="AAAA",
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError):
        await wled.update()


async def test_update_non_utf8_json_response(
    responses: aioresponses,
    wled: WLED,
) -> None:
    """Test update() raises on non-UTF-8 /json response."""
    responses.get(
        "http://example.com/json",
        status=200,
        body=b"\xff\xfe",
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError):
        await wled.update()


async def test_update_non_utf8_presets_response(
    responses: aioresponses,
    wled: WLED,
) -> None:
    """Test update() raises on non-UTF-8 /presets.json response."""
    wled_data = load_fixture_json("wled")
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=b"\xff\xfe",
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError):
        await wled.update()


async def test_update_empty_presets_response(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() raises on empty /presets.json response."""
    # Backoff on update() retries 3 times for WLEDEmptyResponseError
    for _ in range(3):
        responses.get(
            "http://example.com/json",
            status=200,
            body=json.dumps(load_fixture_json("wled")),
            content_type="application/json",
        )
        responses.get(
            "http://example.com/presets.json",
            status=200,
            body="",
            content_type="text/plain",
        )

    with pytest.raises(WLEDEmptyResponseError):
        await wled.update()


async def test_update_skips_presets_when_unchanged(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() skips fetching presets.json when presets haven't changed."""
    wled_data = load_fixture_json("wled")

    # First update: fetches both /json and /presets.json
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: same pmt and uptime, only /json fetched
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    # Third update: pmt changed, fetches /presets.json again
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fs"]["pmt"] = 9999999999.0
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(changed_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps({"0": {}, "1": {"n": "Updated Preset"}}),
        content_type="application/json",
    )

    # First call: presets fetched
    device = await wled.update()
    assert device.presets[1].name == "My Preset"

    # Second call: presets unchanged, not refetched
    device = await wled.update()
    assert device.presets[1].name == "My Preset"

    # Third call: pmt changed, presets refetched
    device = await wled.update()
    assert device.presets[1].name == "Updated Preset"


async def test_update_refetches_presets_when_info_incomplete(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() refetches presets when pmt is zero/missing."""
    wled_data = load_fixture_json("wled")
    # Set pmt to 0 so version can't be determined
    wled_data["info"]["fs"]["pmt"] = 0

    mock_json_and_presets(responses, wled_data)
    # Second call: still no fs, presets refetched again
    mock_json_and_presets(responses, wled_data)

    await wled.update()
    # Without fs/pmt, every update refetches presets
    await wled.update()


async def test_listen_preset_change_via_websocket(
    responses: aioresponses, wled: WLED
) -> None:
    """Test listen() detects preset changes and refetches presets.json."""
    wled_data = load_fixture_json("wled")

    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    # WS message with full info (includes fs.pmt) triggers preset check
    text_msg = MagicMock()
    text_msg.type = aiohttp.WSMsgType.TEXT
    text_msg.json.return_value = wled_data

    close_msg = MagicMock()
    close_msg.type = aiohttp.WSMsgType.CLOSE

    mock_client.receive = AsyncMock(side_effect=[text_msg, close_msg])

    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )

    callback = MagicMock()
    with pytest.raises(WLEDConnectionClosedError):
        await wled.listen(callback)

    callback.assert_called_once()


async def test_listen_preset_change_empty_response(
    responses: aioresponses, wled: WLED
) -> None:
    """Test listen() raises when preset refetch returns empty."""
    wled_data = load_fixture_json("wled")

    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    text_msg = MagicMock()
    text_msg.type = aiohttp.WSMsgType.TEXT
    text_msg.json.return_value = wled_data

    mock_client.receive = AsyncMock(return_value=text_msg)

    responses.get(
        "http://example.com/presets.json",
        status=200,
        body="",
        content_type="text/plain",
    )

    with pytest.raises(WLEDEmptyResponseError):
        await wled.listen(MagicMock())


# =========================================================================
# Section 11: WLED client - master() method
# =========================================================================


async def test_master_brightness(responses: aioresponses, wled: WLED) -> None:
    """Test setting master brightness."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body='{"on": true, "bri": 200}',
        content_type="application/json",
    )

    await wled.master(brightness=200)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"bri": 200, "v": True},
    )


async def test_master_on(responses: aioresponses, wled: WLED) -> None:
    """Test setting master on/off."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body='{"on": true}',
        content_type="application/json",
    )

    await wled.master(on=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"on": True, "v": True},
    )


async def test_master_transition(responses: aioresponses, wled: WLED) -> None:
    """Test setting master transition."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body='{"on": true}',
        content_type="application/json",
    )

    await wled.master(transition=10)

    assert_post_payload(
        responses, "http://example.com/json/state", {"tt": 10, "v": True}
    )


async def test_master_all_params(responses: aioresponses, wled: WLED) -> None:
    """Test setting all master parameters at once."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body='{"on": true, "bri": 100}',
        content_type="application/json",
    )

    await wled.master(brightness=100, on=True, transition=5)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"bri": 100, "on": True, "tt": 5, "v": True},
    )


# =========================================================================
# Section 12: WLED client - segment() method
# =========================================================================


async def prepare_wled_with_device(
    responses: aioresponses,
    wled: WLED,
    wled_data: dict | None = None,
) -> WLED:
    """Prepare a WLED instance with a loaded device."""
    if wled_data is None:
        wled_data = load_fixture_json("wled")
    mock_json_and_presets(responses, wled_data)

    await wled.update()
    return wled


async def test_segment_basic(responses: aioresponses, wled: WLED) -> None:
    """Test basic segment control."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, brightness=200, on=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"bri": 200, "on": True, "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_effect_by_name(responses: aioresponses, wled: WLED) -> None:
    """Test setting segment effect by name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, effect="Blink")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"fx": 1, "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_palette_by_name(responses: aioresponses, wled: WLED) -> None:
    """Test setting segment palette by name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, palette="Random Cycle")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"pal": 1, "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_color_primary(responses: aioresponses, wled: WLED) -> None:
    """Test setting primary color."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, color_primary=(255, 0, 0))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"col": [[255, 0, 0]], "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_color_secondary_only(
    responses: aioresponses, wled: WLED
) -> None:
    """Test setting secondary color fills primary from current state."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, color_secondary=(0, 255, 0))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {
                    "col": [
                        [255, 159, 0],
                        [0, 255, 0],
                    ],
                    "id": 0,
                }
            ],
            "v": True,
        },
    )


async def test_segment_color_tertiary_only(responses: aioresponses, wled: WLED) -> None:
    """Test setting tertiary color fills primary and secondary."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, color_tertiary=(0, 0, 255))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {
                    "col": [
                        [255, 159, 0],
                        [0, 0, 0],
                        [0, 0, 255],
                    ],
                    "id": 0,
                }
            ],
            "v": True,
        },
    )


async def test_segment_all_colors(responses: aioresponses, wled: WLED) -> None:
    """Test setting all three colors at once."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
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

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {
                    "col": [
                        [255, 0, 0],
                        [0, 255, 0],
                        [0, 0, 255],
                    ],
                    "id": 0,
                }
            ],
            "v": True,
        },
    )


async def test_segment_with_transition(responses: aioresponses, wled: WLED) -> None:
    """Test setting segment with transition."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, brightness=100, transition=5)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"bri": 100, "id": 0},
            ],
            "tt": 5,
            "v": True,
        },
    )


async def test_segment_calls_update_when_no_device(
    responses: aioresponses, wled: WLED
) -> None:
    """Test segment() calls update() if no device loaded."""
    mock_json_and_presets(responses)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, on=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"on": True, "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_no_device_raises(wled: WLED) -> None:
    """Test segment() raises if update cannot load device."""
    # Patch update to do nothing (leave _device as None)
    with (
        patch.object(wled, "update", new_callable=AsyncMock),
        pytest.raises(WLEDError, match="Unable to communicate"),
    ):
        await wled.segment(0, on=True)


async def test_segment_individual(responses: aioresponses, wled: WLED) -> None:
    """Test setting individual LED colors."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, individual=[(255, 0, 0), (0, 255, 0)])

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"i": [[255, 0, 0], [0, 255, 0]], "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_color_tertiary_no_secondary_in_state(
    responses: aioresponses, wled: WLED
) -> None:
    """Test tertiary color when segment has no secondary color in state."""
    # Build device data where the segment color has no secondary
    wled_data = load_fixture_json("wled")
    wled_data["state"]["seg"][0]["col"] = [[255, 0, 0]]
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, color_tertiary=(0, 0, 255))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"col": [[255, 0, 0], [0, 0, 0], [0, 0, 255]], "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_secondary_no_color_in_state(
    responses: aioresponses, wled: WLED
) -> None:
    """Test secondary color when segment has no color at all in state."""
    # Build device data where the segment has no col
    wled_data = load_fixture_json("wled")
    del wled_data["state"]["seg"][0]["col"]
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    # color is None, so it should use (0,0,0) fallback
    await wled.segment(0, color_secondary=(0, 255, 0))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"col": [[0, 0, 0], [0, 255, 0]], "id": 0},
            ],
            "v": True,
        },
    )


async def test_segment_tertiary_no_color_in_state(
    responses: aioresponses, wled: WLED
) -> None:
    """Test tertiary color when segment has no color at all in state."""
    # Build device data where the segment has no col
    wled_data = load_fixture_json("wled")
    del wled_data["state"]["seg"][0]["col"]
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, color_tertiary=(0, 0, 255))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"col": [[0, 0, 0], [0, 0, 0], [0, 0, 255]], "id": 0},
            ],
            "v": True,
        },
    )


# =========================================================================
# Section 13: WLED client - preset/playlist/transition/live/sync/nightlight
# =========================================================================


async def test_preset_by_id(responses: aioresponses, wled: WLED) -> None:
    """Test setting a preset by integer ID."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.preset(1)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 1,
            "v": True,
        },
    )


async def test_preset_by_name(responses: aioresponses, wled: WLED) -> None:
    """Test setting a preset by name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.preset("My Preset")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 1,
            "v": True,
        },
    )


async def test_preset_by_object(responses: aioresponses, wled: WLED) -> None:
    """Test setting a preset using a Preset object."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )
    assert wled._device is not None  # pylint: disable=protected-access
    preset_obj = wled._device.presets[1]  # pylint: disable=protected-access
    await wled.preset(preset_obj)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 1,
            "v": True,
        },
    )


async def test_preset_name_not_found(responses: aioresponses, wled: WLED) -> None:
    """Test setting a preset by name that does not exist passes string."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.preset("NonExistent")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": "NonExistent",
            "v": True,
        },
    )


async def test_playlist_by_id(responses: aioresponses, wled: WLED) -> None:
    """Test setting a playlist by integer ID."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.playlist(2)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 2,
            "v": True,
        },
    )


async def test_playlist_by_name(responses: aioresponses, wled: WLED) -> None:
    """Test setting a playlist by name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.playlist("My Playlist")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 2,
            "v": True,
        },
    )


async def test_playlist_by_object(responses: aioresponses, wled: WLED) -> None:
    """Test setting a playlist using a Playlist object."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )
    assert wled._device is not None  # pylint: disable=protected-access
    playlist_obj = wled._device.playlists[2]  # pylint: disable=protected-access

    await wled.playlist(playlist_obj)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": 2,
            "v": True,
        },
    )


async def test_playlist_name_not_found(responses: aioresponses, wled: WLED) -> None:
    """Test setting a playlist by name that does not exist passes string."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.playlist("NonExistent")

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "ps": "NonExistent",
            "v": True,
        },
    )


async def test_transition(responses: aioresponses, wled: WLED) -> None:
    """Test setting default transition."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.transition(10)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"transition": 10, "v": True},
    )


async def test_live(responses: aioresponses, wled: WLED) -> None:
    """Test setting live data override."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.live(LiveDataOverride.ON)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "lor": LiveDataOverride.ON.value,
            "v": True,
        },
    )


async def test_sync_send(responses: aioresponses, wled: WLED) -> None:
    """Test setting sync send."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.sync(send=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "udpn": {"send": True},
            "v": True,
        },
    )


async def test_sync_receive(responses: aioresponses, wled: WLED) -> None:
    """Test setting sync receive."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.sync(receive=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "udpn": {"recv": True},
            "v": True,
        },
    )


async def test_nightlight_on(responses: aioresponses, wled: WLED) -> None:
    """Test turning on nightlight."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.nightlight(on=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "nl": {"on": True},
            "v": True,
        },
    )


async def test_nightlight_all_params(responses: aioresponses, wled: WLED) -> None:
    """Test nightlight with all parameters."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.nightlight(duration=30, fade=True, on=True, target_brightness=50)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "nl": {
                "dur": 30,
                "fade": True,
                "on": True,
                "tbri": 50,
            },
            "v": True,
        },
    )


# =========================================================================
# Section 14: WLED client - reset, close, context manager, connected
# =========================================================================


async def test_reset(responses: aioresponses, wled: WLED) -> None:
    """Test reset method calls /reset."""
    responses.get(
        "http://example.com/reset",
        status=200,
        body="OK",
        content_type="text/plain",
    )

    await wled.reset()


async def test_close_with_internal_session(responses: aioresponses) -> None:
    """Test close() closes internally created session."""
    responses.get(
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


async def test_close_with_external_session(
    session: aiohttp.ClientSession,
) -> None:
    """Test close() does not close externally provided session."""
    wled = WLED("example.com", session=session)
    assert wled._close_session is False  # pylint: disable=protected-access
    await wled.close()
    assert not session.closed


async def test_context_manager(responses: aioresponses) -> None:
    """Test async context manager."""
    responses.get(
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


async def test_connect_no_websocket_support(
    responses: aioresponses, wled: WLED
) -> None:
    """Test connect() raises when device has no WebSocket support."""
    # Build data with ws=-1 (no websocket support)
    wled_data = load_fixture_json("wled")
    wled_data["info"]["ws"] = -1
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    with pytest.raises(WLEDError, match="does not support WebSockets"):
        await wled.connect()


async def test_connect_connection_error(responses: aioresponses, wled: WLED) -> None:
    """Test connect() raises WLEDConnectionError on connection failure."""
    mock_json_and_presets(responses)

    await wled.update()
    assert wled.session is not None
    with (
        patch.object(
            wled.session,
            "ws_connect",
            side_effect=aiohttp.ClientConnectionError("fail"),
        ),
        pytest.raises(WLEDConnectionError),
    ):
        await wled.connect()


async def test_connect_calls_update_when_no_device(
    responses: aioresponses, wled: WLED
) -> None:
    """Test connect() calls update() if no device is loaded."""
    mock_json_and_presets(responses)

    mock_client = MagicMock(closed=False)
    mock_client.close = AsyncMock()

    with patch.object(
        aiohttp.ClientSession, "ws_connect", new_callable=AsyncMock
    ) as mock_ws:
        mock_ws.return_value = mock_client
        assert wled._device is None  # pylint: disable=protected-access
        await wled.connect()
        assert wled._device is not None  # pylint: disable=protected-access


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


async def test_post_state_adds_v_true(responses: aioresponses, wled: WLED) -> None:
    """Test POST to /json/state adds v=True to data."""
    mock_json_and_presets(responses)

    state_response = json.dumps(load_fixture_json("wled")["state"])
    responses.post(
        "http://example.com/json/state",
        status=200,
        body=state_response,
        content_type="application/json",
    )
    await wled.update()  # Need device for state update path
    await wled.request("/json/state", method="POST", data={"on": True})

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"on": True, "v": True},
    )


async def test_client_error_raises_connection_error(
    responses: aioresponses, wled: WLED
) -> None:
    """Test aiohttp.ClientError raises WLEDConnectionError."""
    responses.get("http://example.com/test", exception=aiohttp.ClientError("fail"))
    responses.get("http://example.com/test", exception=aiohttp.ClientError("fail"))
    responses.get("http://example.com/test", exception=aiohttp.ClientError("fail"))

    with pytest.raises(WLEDConnectionError):
        await wled.request("/test")


# =========================================================================
# Section 17: WLED client - upgrade() method
# =========================================================================


async def prepare_wled_for_upgrade(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    responses: aioresponses,
    wled: WLED,
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

    mock_json_and_presets(responses, wled_data)
    await wled.update()
    return wled


async def test_upgrade_unsupported_architecture(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade raises for unsupported architecture."""
    await prepare_wled_for_upgrade(responses, wled, arch="unknown_arch")
    with pytest.raises(WLEDUpgradeError, match="only supported"):
        await wled.upgrade(version="0.15.0")


async def test_upgrade_same_version(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade raises when already on requested version."""
    await prepare_wled_for_upgrade(responses, wled)
    with pytest.raises(WLEDUpgradeError, match="already running"):
        await wled.upgrade(version="0.14.0")


async def test_upgrade_no_version(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade raises when current version is unknown."""
    # Build device with invalid version
    wled_data = load_fixture_json("wled")
    wled_data["info"]["ver"] = "0.14.0"
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    assert wled._device is not None  # pylint: disable=protected-access
    # Manually set version to None
    wled._device.info.version = None  # pylint: disable=protected-access
    with pytest.raises(WLEDUpgradeError, match="version is unknown"):
        await wled.upgrade(version="0.15.0")


async def test_upgrade_calls_update_when_no_device(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade() calls update() if no device loaded."""
    mock_json_and_presets(responses)
    # Mock the download and upload
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body="OK",
        content_type="text/plain",
    )
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


async def test_upgrade_success(responses: aioresponses, wled: WLED) -> None:
    """Test successful upgrade."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body="OK",
        content_type="text/plain",
    )
    await wled.upgrade(version="0.15.0")


async def test_upgrade_ethernet_board(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade with Ethernet board (empty bssid)."""
    await prepare_wled_for_upgrade(responses, wled, wifi_bssid="")
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32_Ethernet.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body="OK",
        content_type="text/plain",
    )
    await wled.upgrade(version="0.15.0")


async def test_upgrade_esp02_gzip(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade for esp02 (2M ESP8266) includes .gz suffix."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp8266"
    wled_data["info"]["ver"] = "0.14.0"
    # Small filesystem for esp02 detection
    wled_data["info"]["fs"]["t"] = 512
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP02.bin.gz",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body="OK",
        content_type="text/plain",
    )
    await wled.upgrade(version="0.15.0")


async def test_upgrade_404(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade with 404 download raises WLEDUpgradeError."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.99.0/WLED_0.99.0_ESP32.bin",
        status=404,
    )
    with pytest.raises(WLEDUpgradeError, match="does not exist"):
        await wled.upgrade(version="0.99.0")


async def test_upgrade_other_http_error(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade with non-404 HTTP error raises WLEDUpgradeError."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=500,
    )
    with pytest.raises(WLEDUpgradeError, match="Could not download"):
        await wled.upgrade(version="0.15.0")


async def test_upgrade_connection_error(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade with connection error raises WLEDConnectionError."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        exception=aiohttp.ClientError("fail"),
    )
    with pytest.raises(WLEDConnectionError):
        await wled.upgrade(version="0.15.0")


async def test_upgrade_timeout(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade with timeout raises WLEDConnectionTimeoutError."""
    await prepare_wled_for_upgrade(responses, wled)
    wled.request_timeout = 0.001
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        exception=TimeoutError(),
    )
    with pytest.raises(WLEDConnectionTimeoutError):
        await wled.upgrade(version="0.15.0")


# =========================================================================
# Section 18: WLEDReleases class
# =========================================================================


async def test_releases_success(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test successful release fetching."""
    releases_data = [
        {
            "tag_name": "nightly",
            "published_at": "2026-04-16T03:19:12Z",
            "prerelease": True,
            "assets": [
                {"name": "WLED_17.0.0-dev_ESP32.bin"},
            ],
        },
        {
            "tag_name": "v0.15.0",
            "prerelease": False,
        },
        {
            "tag_name": "v0.15.0b1",
            "prerelease": True,
        },
    ]
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=200,
        body=json.dumps(releases_data),
        content_type="application/json",
    )
    wled_releases = WLEDReleases(session=session)
    releases = await wled_releases.releases()

    assert isinstance(releases, Releases)
    assert releases.stable is not None
    assert str(releases.stable) == "0.15.0"
    assert releases.beta is not None
    assert str(releases.beta) == "0.15.0b1"
    assert releases.nightly is not None
    assert str(releases.nightly) == "17.0.0-dev20260416"
    assert releases.repo == "wled/WLED"


async def test_releases_custom_repo(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test fetching releases from a custom repository."""
    releases_data = [
        {
            "tag_name": "v0.14.0",
            "prerelease": False,
        },
    ]
    responses.get(
        "https://api.github.com/repos/MoonModules/WLED/releases",
        status=200,
        body=json.dumps(releases_data),
        content_type="application/json",
    )
    wled_releases = WLEDReleases(repo="MoonModules/WLED", session=session)
    releases = await wled_releases.releases()
    assert releases.repo == "MoonModules/WLED"
    assert str(releases.stable) == "0.14.0"


async def test_releases_with_b_in_tag_name(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
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
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=200,
        body=json.dumps(releases_data),
        content_type="application/json",
    )
    wled_releases = WLEDReleases(session=session)
    releases = await wled_releases.releases()
    assert releases.beta is not None
    assert str(releases.beta) == "0.14.1b2"
    assert releases.stable is not None
    assert str(releases.stable) == "0.14.0"


async def test_releases_no_beta(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases when no beta is available."""
    releases_data = [
        {
            "tag_name": "v0.14.0",
            "prerelease": False,
        },
    ]
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=200,
        body=json.dumps(releases_data),
        content_type="application/json",
    )
    wled_releases = WLEDReleases(session=session)
    releases = await wled_releases.releases()
    assert releases.stable is not None
    assert releases.beta is None


async def test_releases_context_manager(responses: aioresponses) -> None:
    """Test WLEDReleases as context manager."""
    releases_data = [
        {"tag_name": "v0.14.0", "prerelease": False},
    ]
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=200,
        body=json.dumps(releases_data),
        content_type="application/json",
    )
    async with WLEDReleases() as wled_releases:
        releases = await wled_releases.releases()
        assert releases.stable is not None


async def test_releases_internal_session(responses: aioresponses) -> None:
    """Test WLEDReleases creates internal session."""
    releases_data = [
        {"tag_name": "v0.14.0", "prerelease": False},
    ]
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
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


async def test_releases_close_external_session(
    session: aiohttp.ClientSession,
) -> None:
    """Test close() does not close externally provided session."""
    wled_releases = WLEDReleases(session=session)
    await wled_releases.close()
    assert not session.closed


async def test_releases_http_error(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases raises WLEDError on HTTP error."""
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=500,
        body='{"message": "error"}',
        content_type="application/json",
    )
    wled_releases = WLEDReleases(session=session)
    with pytest.raises(WLEDError):
        await wled_releases.releases()


async def test_releases_http_error_text(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases raises WLEDError on HTTP error with text."""
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=403,
        body="Forbidden",
        content_type="text/plain",
    )
    wled_releases = WLEDReleases(session=session)
    with pytest.raises(WLEDError):
        await wled_releases.releases()


async def test_releases_non_json_response(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases raises WLEDError on non-JSON response."""
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        status=200,
        body="Not JSON",
        content_type="text/plain",
    )
    wled_releases = WLEDReleases(session=session)
    with pytest.raises(WLEDError, match="No JSON"):
        await wled_releases.releases()


async def test_releases_timeout(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases raises on timeout."""
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases", exception=TimeoutError()
    )
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases", exception=TimeoutError()
    )
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases", exception=TimeoutError()
    )
    wled_releases = WLEDReleases(session=session, request_timeout=0.1)

    with pytest.raises(WLEDConnectionError):
        await wled_releases.releases()


async def test_releases_connection_error(
    responses: aioresponses, session: aiohttp.ClientSession
) -> None:
    """Test releases raises on connection error."""
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        exception=aiohttp.ClientError("fail"),
    )
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        exception=aiohttp.ClientError("fail"),
    )
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases",
        exception=aiohttp.ClientError("fail"),
    )
    wled_releases = WLEDReleases(session=session)
    with pytest.raises(WLEDConnectionError):
        await wled_releases.releases()
