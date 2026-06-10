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


@pytest.mark.parametrize(
    ("status", "body", "content_type"),
    [
        (404, "OMG KITTIENS!", "text/plain"),
        (500, '{"status":"nok"}', "application/json"),
    ],
    ids=["404", "500"],
)
async def test_http_error(
    responses: aioresponses, wled: WLED, status: int, body: str, content_type: str
) -> None:
    """Test HTTP error response handling."""
    responses.get(
        "http://example.com/",
        status=status,
        body=body,
        content_type=content_type,
    )

    with pytest.raises(WLEDError):
        assert await wled.request("/")


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"\xff\xfe", "text/plain"),
        (b"not-json", "application/json"),
    ],
)
async def test_http_error_invalid_response(
    responses: aioresponses, wled: WLED, body: bytes, content_type: str
) -> None:
    """Test HTTP error with unparsable body raises WLEDInvalidResponseError."""
    responses.get(
        "http://example.com/",
        status=500,
        body=body,
        content_type=content_type,
    )
    with pytest.raises(WLEDInvalidResponseError, match=r"GET /"):
        await wled.request("/")


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


@pytest.mark.parametrize("body", ["AAAA", b"\xff\xfe"])
async def test_update_corrupt_json_response(
    responses: aioresponses, wled: WLED, body: str | bytes
) -> None:
    """Test update() raises on corrupt (invalid JSON or non-UTF-8) /json response."""
    responses.get(
        "http://example.com/json",
        status=200,
        body=body,
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError, match=r"GET /json"):
        await wled.update()


@pytest.mark.parametrize("body", ["AAAA", b"\xff\xfe"])
async def test_update_corrupt_presets_response(
    responses: aioresponses, wled: WLED, body: str | bytes
) -> None:
    """Test update() raises on corrupt /presets.json response."""
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
        body=body,
        content_type="application/json",
    )
    with pytest.raises(WLEDInvalidResponseError, match=r"GET /presets\.json"):
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

    # First update: fetches /json, /json/effects, /presets.json
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/effects",
        status=200,
        body=json.dumps(wled_data["effects"]),
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


async def test_update_skips_effects_when_unchanged(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() skips /json/effects when effect count and boot time unchanged."""
    wled_data = load_fixture_json("wled")
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fxcount"] += 1
    changed_data["effects"] = wled_data["effects"] + ["New Effect"]

    with patch("wled.wled.time.time", return_value=1_000_000.0):
        # First update: fetches /json, /json/effects, /presets.json
        mock_json_and_presets(responses, wled_data)
        # Second update: same fxcount and boot_time — only /json fetched
        responses.get(
            "http://example.com/json",
            status=200,
            body=json.dumps(wled_data),
            content_type="application/json",
        )
        # Third update: fxcount increased — /json/effects refetched with extra effect
        responses.get(
            "http://example.com/json",
            status=200,
            body=json.dumps(changed_data),
            content_type="application/json",
        )
        responses.get(
            "http://example.com/json/effects",
            status=200,
            body=json.dumps(changed_data["effects"]),
            content_type="application/json",
        )

        device1 = await wled.update()
        assert device1.info.effect_count == wled_data["info"]["fxcount"]
        initial_effect_count = len(device1.effects)

        device2 = await wled.update()
        assert device2.info.effect_count == wled_data["info"]["fxcount"]
        assert len(device2.effects) == initial_effect_count  # no re-fetch, unchanged

        device3 = await wled.update()
        assert device3.info.effect_count == changed_data["info"]["fxcount"]
        # "New Effect" added after fxcount bump — re-fetch brought it in
        assert len(device3.effects) == initial_effect_count + 1


async def test_update_refetches_effects_after_device_restart(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() refetches effects when a device restart is detected."""
    wled_data = load_fixture_json("wled")
    restarted_data = json.loads(json.dumps(wled_data))
    restarted_data["info"]["uptime"] = 5  # uptime reset — device just booted
    restarted_data["effects"] = wled_data["effects"] + ["Post Restart Effect"]

    mock_json_and_presets(responses, wled_data)
    # After restart uptime drops from 32489 → 5, so boot_time shifts by ~32484s
    mock_json_and_presets(responses, restarted_data)

    device1 = await wled.update()
    assert device1.info.effect_count == wled_data["info"]["fxcount"]

    device2 = await wled.update()
    # Refetch was triggered by boot_time shift, not fxcount — verify by content
    assert any(e.name == "Post Restart Effect" for e in device2.effects.values())


async def test_update_uses_effects_endpoint_for_full_list(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() uses /json/effects to get the complete effects list.

    Simulates the ESP8266 /json buffer overflow (WLED issue #5674): /json
    returns a truncated effects list while /json/effects returns the full one.
    """
    wled_data = load_fixture_json("wled")
    full_effects = wled_data["effects"]
    # Truncate list — simulates ESP8266 /json buffer overflow
    wled_data["effects"] = full_effects[:1]

    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/effects",
        status=200,
        body=json.dumps(full_effects),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: /json still truncated, fxcount unchanged — no /json/effects stub.
    # The cached full list must survive and not be overwritten by the truncated payload.
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )

    device = await wled.update()
    assert len(device.effects) == 3  # full list from /json/effects

    device = await wled.update()
    assert len(device.effects) == 3  # still full — truncated /json did not overwrite


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


@pytest.mark.parametrize(
    ("kwargs", "expected_payload"),
    [
        ({"brightness": 200}, {"bri": 200, "v": True}),
        ({"on": True}, {"on": True, "v": True}),
        ({"transition": 10}, {"tt": 10, "v": True}),
        (
            {"brightness": 100, "on": True, "transition": 5},
            {"bri": 100, "on": True, "tt": 5, "v": True},
        ),
    ],
    ids=["brightness", "on", "transition", "all_params"],
)
async def test_master(
    responses: aioresponses, wled: WLED, kwargs: dict, expected_payload: dict
) -> None:
    """Test setting master parameters."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.master(**kwargs)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        expected_payload,
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


@pytest.mark.parametrize(
    ("kwargs", "expected_seg"),
    [
        ({"brightness": 200, "on": True}, {"bri": 200, "on": True, "id": 0}),
        ({"effect": "Blink"}, {"fx": 1, "id": 0}),
        ({"palette": "Random Cycle"}, {"pal": 1, "id": 0}),
        ({"color_primary": (255, 0, 0)}, {"col": [[255, 0, 0]], "id": 0}),
        (
            {"color_secondary": (0, 255, 0)},
            {"col": [[255, 159, 0], [0, 255, 0]], "id": 0},
        ),
        (
            {"color_tertiary": (0, 0, 255)},
            {"col": [[255, 159, 0], [0, 0, 0], [0, 0, 255]], "id": 0},
        ),
        (
            {
                "color_primary": (255, 0, 0),
                "color_secondary": (0, 255, 0),
                "color_tertiary": (0, 0, 255),
            },
            {"col": [[255, 0, 0], [0, 255, 0], [0, 0, 255]], "id": 0},
        ),
        (
            {"individual": [(255, 0, 0), (0, 255, 0)]},
            {"i": [[255, 0, 0], [0, 255, 0]], "id": 0},
        ),
        # The name parameter cases
        ({"name": "Curtain"}, {"n": "Curtain", "id": 0}),
        ({"name": ""}, {"n": "", "id": 0}),
        ({"name": None, "brightness": 200}, {"bri": 200, "id": 0}),
    ],
    ids=[
        "basic",
        "effect_by_name",
        "palette_by_name",
        "color_primary",
        "color_secondary",
        "color_tertiary",
        "all_colors",
        "individual",
        "name_set",
        "name_clear_empty_string",
        "name_none_explicit",
    ],
)
async def test_segment(
    responses: aioresponses, wled: WLED, kwargs: dict, expected_seg: dict
) -> None:
    """Test segment control."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(0, **kwargs)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [expected_seg], "v": True},
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


@pytest.mark.parametrize(
    ("preset_input", "expected_ps"),
    [
        (1, 1),
        ("My Preset", 1),
        ("NonExistent", "NonExistent"),
    ],
    ids=["by_id", "by_name", "name_not_found"],
)
async def test_preset(
    responses: aioresponses, wled: WLED, preset_input: int | str, expected_ps: int | str
) -> None:
    """Test setting preset by ID, name, or non-existent name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.preset(preset_input)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"ps": expected_ps, "v": True},
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


@pytest.mark.parametrize(
    ("playlist_input", "expected_ps"),
    [
        (2, 2),
        ("My Playlist", 2),
        ("NonExistent", "NonExistent"),
    ],
    ids=["by_id", "by_name", "name_not_found"],
)
async def test_playlist(
    responses: aioresponses,
    wled: WLED,
    playlist_input: int | str,
    expected_ps: int | str,
) -> None:
    """Test setting playlist by ID, name, or non-existent name."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.playlist(playlist_input)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"ps": expected_ps, "v": True},
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


@pytest.mark.parametrize(
    ("kwargs", "expected_payload"),
    [
        ({"send": True}, {"udpn": {"send": True}, "v": True}),
        ({"receive": True}, {"udpn": {"recv": True}, "v": True}),
    ],
    ids=["send", "receive"],
)
async def test_sync(
    responses: aioresponses, wled: WLED, kwargs: dict, expected_payload: dict
) -> None:
    """Test setting sync parameters."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.sync(**kwargs)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        expected_payload,
    )


@pytest.mark.parametrize(
    ("kwargs", "expected_nl"),
    [
        ({"on": True}, {"on": True}),
        (
            {"duration": 30, "fade": True, "on": True, "target_brightness": 50},
            {"dur": 30, "fade": True, "on": True, "tbri": 50},
        ),
    ],
    ids=["on", "all_params"],
)
async def test_nightlight(
    responses: aioresponses, wled: WLED, kwargs: dict, expected_nl: dict
) -> None:
    """Test setting nightlight parameters."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.nightlight(**kwargs)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"nl": expected_nl, "v": True},
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
