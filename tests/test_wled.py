"""Tests for `wled.wled` (WLED client)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import orjson
import pytest
from aioresponses import aioresponses
from yarl import URL

from wled import WLED, Device, Releases, SegmentUpdate
from wled.const import DEFAULT_REPO, LiveDataOverride, NightlightMode, SyncGroup
from wled.exceptions import (
    WLEDConnectionClosedError,
    WLEDConnectionError,
    WLEDConnectionTimeoutError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDInvalidResponseError,
    WLEDStatusError,
    WLEDUpgradeError,
)
from wled.wled import WLEDReleases

from .conftest import (
    full_device_data,
    load_fixture_json,
    mock_catalog,
    mock_json_and_presets,
)


def requests_to(responses: aioresponses, path: str) -> int:
    """Return how often a path on the device was requested."""
    if not responses.requests:
        return 0

    return sum(
        len(calls)
        for (_, url), calls in responses.requests.items()
        if url.host == "example.com" and url.path == path
    )


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


async def test_request_with_params(responses: aioresponses, wled: WLED) -> None:
    """Test query parameters end up in the query string, not the path."""
    responses.get(
        "http://example.com/json/palx?page=2",
        status=200,
        body='{"m": 9, "p": {}}',
        content_type="application/json",
    )

    response = await wled.request("/json/palx", params={"page": 2})

    assert response["m"] == 9
    assert responses.requests
    assert next(iter(responses.requests))[1].query == {"page": "2"}


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
    ("status", "body", "content_type", "expected_body"),
    [
        (404, "Not Found", "text/plain", {"message": "Not Found"}),
        (500, '{"error":"oops"}', "application/json", {"error": "oops"}),
    ],
    ids=["404-text", "500-json"],
)
async def test_http_error_raises_status_error(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    responses: aioresponses,
    wled: WLED,
    status: int,
    body: str,
    content_type: str,
    expected_body: dict,
) -> None:
    """Test HTTP error raises WLEDStatusError with structured attributes."""
    responses.get(
        "http://example.com/json",
        status=status,
        body=body,
        content_type=content_type,
    )
    with pytest.raises(WLEDStatusError) as exc_info:
        await wled.request("/json")
    err = exc_info.value
    assert err.method == "GET"
    assert err.path == "/json"
    assert err.status == status
    assert err.body == expected_body
    assert err.args == (status, expected_body)


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
    mock_json_and_presets(responses, cached=True)

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


@pytest.mark.parametrize(
    ("status", "body", "content_type"),
    [
        (200, "AAAA", "application/json"),
        (200, b"\xff\xfe", "application/json"),
        (200, "", "application/json"),
        (200, "", "text/plain"),
        (200, "[1, 2]", "application/json"),
        (404, "Not Found", "text/plain"),
    ],
)
async def test_update_keeps_presets_when_the_file_is_unusable(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    responses: aioresponses,
    wled: WLED,
    status: int,
    body: str | bytes,
    content_type: str,
) -> None:
    """Test an unusable presets file keeps the presets, and is tried again."""
    wled_data = load_fixture_json("wled")
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fs"]["pmt"] = 9999999999.0

    # First update: the presets load fine.
    mock_json_and_presets(responses, wled_data)
    # Second update: the presets changed, but the file can't be used.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: changed_data[key] for key in ("state", "info")}),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=status,
        body=body,
        content_type=content_type,
    )
    # Third update: nothing changed, but the presets are fetched again.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: changed_data[key] for key in ("state", "info")}),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps({"0": {}, "1": {"n": "Updated Preset"}}),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.presets[1].name == "My Preset"

    device = await wled.update()
    assert device.presets[1].name == "My Preset"

    device = await wled.update()
    assert device.presets[1].name == "Updated Preset"
    assert requests_to(responses, "/presets.json") == 3


async def test_update_without_a_usable_presets_file(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a device without a usable presets file can still be set up."""
    wled_data = load_fixture_json("wled")
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, wled_data["effects"], wled_data["palettes"])
    responses.get(
        "http://example.com/presets.json",
        status=404,
        body="Not Found",
        content_type="text/plain",
    )

    device = await wled.update()

    assert device.presets == {}
    assert device.playlists == {}


async def test_update_raises_when_presets_connection_fails(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() still fails when the device is gone while fetching presets."""
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(load_fixture_json("wled")),
        content_type="application/json",
    )
    for _ in range(3):
        responses.get(
            "http://example.com/presets.json",
            exception=aiohttp.ClientError("gone"),
        )

    with pytest.raises(WLEDConnectionError):
        await wled.update()


async def test_update_skips_presets_when_unchanged(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() skips fetching presets.json when presets haven't changed."""
    wled_data = load_fixture_json("wled")

    # First update: fetches /json, /presets.json, and the effects and palettes
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, wled_data["effects"], wled_data["palettes"])
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: same pmt and uptime, only /json fetched
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    # Third update: pmt changed, fetches /presets.json again
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fs"]["pmt"] = 9999999999.0
    responses.get(
        "http://example.com/json/si",
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
    """Test update() refetches presets when the device reports no version."""
    wled_data = load_fixture_json("wled")
    del wled_data["info"]["fs"]["pmt"]

    mock_json_and_presets(responses, wled_data)
    mock_json_and_presets(responses, wled_data, cached=True)

    await wled.update()
    await wled.update()

    # Without a version to compare, every update fetches the presets again.
    assert requests_to(responses, "/presets.json") == 2


async def test_update_skips_effects_when_unchanged(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() skips /json/effects when effect count and boot time unchanged."""
    wled_data = load_fixture_json("wled")
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fxcount"] += 1
    changed_data["effects"] = wled_data["effects"] + ["New Effect"]

    # First update: fetches /json, /presets.json, and the effects and palettes
    mock_json_and_presets(responses, wled_data)
    # Second update: same fxcount and boot_time — only /json fetched
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    # Third update: fxcount increased — /json/effects refetched with extra effect
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(changed_data),
        content_type="application/json",
    )
    mock_catalog(responses, changed_data["effects"], changed_data["palettes"])

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
    mock_json_and_presets(responses, restarted_data, cached=True)

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
    mock_catalog(responses, full_effects, wled_data["palettes"])
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: /json still truncated, fxcount unchanged — no /json/effects stub.
    # The cached full list must survive and not be overwritten by the truncated payload.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )

    device = await wled.update()
    assert len(device.effects) == 3  # full list from /json/effects

    device = await wled.update()
    assert len(device.effects) == 3  # still full — truncated /json did not overwrite


def catalog_requests(responses: aioresponses) -> int:
    """Return how often the effects list was fetched from its own endpoint."""
    if not responses.requests:
        return 0

    return len(
        responses.requests.get(("GET", URL("http://example.com/json/effects")), [])
    )


async def test_update_uses_palettes_endpoint_when_json_is_cut_off(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() gets all palettes when /json stops before the palettes."""
    wled_data = load_fixture_json("wled")
    full_effects = wled_data["effects"]
    full_palettes = wled_data["palettes"]

    # Simulates the ESP8266 buffer overflow: the response stops halfway the
    # effects list, so the palettes are missing entirely.
    wled_data["effects"] = full_effects[:1]
    del wled_data["palettes"]

    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, full_effects, full_palettes)
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )

    device = await wled.update()

    assert [device.palettes[i].name for i in range(len(full_palettes))] == (
        full_palettes
    )


@pytest.mark.parametrize(
    ("effects_status", "effects_body", "palettes_body", "failed"),
    [
        (500, "Internal Server Error", ["Default"], "effects"),
        (200, {"not": "a list"}, ["Default"], "effects"),
        (200, None, "not a list", "palettes"),
    ],
)
async def test_update_falls_back_when_catalog_is_unusable(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    responses: aioresponses,
    wled: WLED,
    effects_status: int,
    effects_body: object,
    palettes_body: object,
    failed: str,
) -> None:
    """Test update() uses the /json lists when the catalog endpoints fail."""
    wled_data = load_fixture_json("wled")
    if effects_body is None:
        effects_body = wled_data["effects"]

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
    responses.get(
        "http://example.com/json/effects",
        status=effects_status,
        body=json.dumps(effects_body) if effects_status == 200 else effects_body,
        content_type="application/json" if effects_status == 200 else "text/plain",
    )
    responses.get(
        "http://example.com/json/palettes",
        status=200,
        body=json.dumps(palettes_body),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/fxdata",
        status=200,
        body="[]",
        content_type="application/json",
    )
    # Second update: the catalog is fetched again, and now it works.
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, wled_data["effects"], wled_data["palettes"])

    device = await wled.update()
    assert len(device.effects) == 3
    assert device.palettes[0].name == "Default"

    # Only the list that failed is fetched again.
    await wled.update()
    working = "palettes" if failed == "effects" else "effects"
    assert requests_to(responses, f"/json/{failed}") == 2
    assert requests_to(responses, f"/json/{working}") == 1


async def test_update_raises_when_catalog_connection_fails(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() fails when the device is unreachable for the catalog."""
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
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    for _ in range(3):
        responses.get(
            "http://example.com/json/effects",
            exception=aiohttp.ClientError("gone"),
        )

    with pytest.raises(WLEDConnectionError):
        await wled.update()


async def test_update_accepts_device_without_palettes(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() handles devices that report no palettes at all."""
    wled_data = load_fixture_json("wled")
    wled_data["palettes"] = None
    wled_data["info"]["cpalcount"] = 0

    mock_json_and_presets(responses, wled_data)
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.palettes == {}

    # A device without palettes must not trigger a refetch on every update.
    await wled.update()
    assert catalog_requests(responses) == 1


async def test_update_refetches_catalog_when_info_incomplete(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() refetches the catalog when it can't tell what changed."""
    wled_data = load_fixture_json("wled")
    del wled_data["info"]["uptime"]

    mock_json_and_presets(responses, wled_data)
    mock_json_and_presets(responses, wled_data, cached=True)

    await wled.update()
    await wled.update()

    assert catalog_requests(responses) == 2


@pytest.mark.parametrize("data", ["not a dict", {}, {"info": None}])
def test_check_catalog_changed_without_info(wled: WLED, data: Any) -> None:
    """Test the catalog check asks for a refetch when info is unusable."""
    # pylint: disable-next=protected-access
    assert wled._check_catalog_changed(data) == (True, None)


async def test_update_picks_up_custom_palettes_without_refetch(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() shows a custom palette added on the device right away."""
    wled_data = load_fixture_json("wled")
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["cpalcount"] += 1

    mock_json_and_presets(responses, wled_data)
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(changed_data),
        content_type="application/json",
    )

    device = await wled.update()
    custom_before = sum(palette.custom for palette in device.palettes.values())

    device = await wled.update()
    custom_after = sum(palette.custom for palette in device.palettes.values())

    assert custom_after == custom_before + 1
    assert catalog_requests(responses) == 1


async def test_update_picks_up_renamed_usermod_palettes(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() follows usermod palette names that change in place."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["ver"] = "16.0.0"
    wled_data["info"]["umpalcount"] = 1
    wled_data["info"]["umpalnames"] = ["Plasma"]
    renamed_data = json.loads(json.dumps(wled_data))
    renamed_data["info"]["umpalnames"] = ["Lava"]

    mock_json_and_presets(responses, wled_data)
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(renamed_data),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.palettes[255].name == "Plasma"

    device = await wled.update()
    assert device.palettes[255].name == "Lava"


async def test_update_keeps_effects_when_only_palettes_fail(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a failing palettes endpoint doesn't cost the complete effects."""
    wled_data = load_fixture_json("wled")
    full_effects = wled_data["effects"]
    wled_data["effects"] = full_effects[:1]

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
    responses.get(
        "http://example.com/json/effects",
        status=200,
        body=json.dumps(full_effects),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/palettes",
        status=500,
        body="Internal Server Error",
        content_type="text/plain",
    )
    responses.get(
        "http://example.com/json/fxdata",
        status=200,
        body="[]",
        content_type="application/json",
    )

    device = await wled.update()

    assert len(device.effects) == 3
    assert device.palettes[0].name == "Default"


async def test_update_keeps_cached_catalog_when_refetch_fails(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a failed refetch doesn't replace complete lists by truncated ones."""
    wled_data = load_fixture_json("wled")
    truncated_data = json.loads(json.dumps(wled_data))
    truncated_data["info"]["fxcount"] += 1
    truncated_data["effects"] = wled_data["effects"][:1]
    del truncated_data["palettes"]

    mock_json_and_presets(responses, wled_data)
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps(truncated_data),
        content_type="application/json",
    )
    for endpoint in ("effects", "palettes", "fxdata"):
        responses.get(
            f"http://example.com/json/{endpoint}",
            status=500,
            body="Internal Server Error",
            content_type="text/plain",
        )

    await wled.update()
    device = await wled.update()

    assert len(device.effects) == 3
    assert [device.palettes[i].name for i in range(3)] == wled_data["palettes"]


async def test_update_fetches_effect_metadata(
    responses: aioresponses, wled: WLED
) -> None:
    """Test update() fetches the effect metadata and attaches it."""
    wled_data = load_fixture_json("wled")
    fxdata = ["", "!,Duty cycle;!,!;!;01", "", "!;;!;2"]
    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, wled_data["effects"], wled_data["palettes"], fxdata)
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )

    device = await wled.update()

    assert device.effects[1].metadata is not None
    assert device.effects[1].metadata.sliders["intensity"] == "Duty cycle"
    assert device.effects[3].metadata is not None
    assert device.effects[3].metadata.requires_matrix


async def test_update_without_effect_metadata(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a failing metadata endpoint leaves the metadata out, nothing else."""
    wled_data = load_fixture_json("wled")
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
        "http://example.com/json/palettes",
        status=200,
        body=json.dumps(wled_data["palettes"]),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/fxdata",
        status=500,
        body="Internal Server Error",
        content_type="text/plain",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )

    device = await wled.update()

    assert len(device.effects) == 3
    assert all(effect.metadata is None for effect in device.effects.values())


async def test_update_retries_only_the_effect_metadata(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a failed metadata fetch is retried without the other lists."""
    wled_data = load_fixture_json("wled")
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
        "http://example.com/json/palettes",
        status=200,
        body=json.dumps(wled_data["palettes"]),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/fxdata",
        status=500,
        body="Internal Server Error",
        content_type="text/plain",
    )
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: the metadata endpoint has recovered.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: wled_data[key] for key in ("state", "info")}),
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/fxdata",
        status=200,
        body=json.dumps(["", "!,Duty cycle;!,!;!;01", "", ""]),
        content_type="application/json",
    )

    await wled.update()
    device = await wled.update()

    assert device.effects[1].metadata is not None
    assert device.effects[1].metadata.sliders["intensity"] == "Duty cycle"
    assert requests_to(responses, "/json/fxdata") == 2
    assert requests_to(responses, "/json/effects") == 1
    assert requests_to(responses, "/json/palettes") == 1


@pytest.mark.parametrize("failed", ["effects", "fxdata"])
async def test_update_drops_metadata_that_no_longer_fits(
    responses: aioresponses, wled: WLED, failed: str
) -> None:
    """Test metadata from an older catalog isn't paired with other effects."""
    wled_data = load_fixture_json("wled")
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["fxcount"] += 1
    changed_data["effects"] = ["New Effect", *wled_data["effects"]]
    old_fxdata = ["", "!,Duty cycle;!,!;!;01", ""]

    responses.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    mock_catalog(responses, wled_data["effects"], wled_data["palettes"], old_fxdata)
    responses.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(load_fixture_json("presets")),
        content_type="application/json",
    )
    # Second update: the catalog changed, and one of the two lists fails.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: changed_data[key] for key in ("state", "info")}),
        content_type="application/json",
    )
    for key, body in (
        ("effects", changed_data["effects"]),
        ("palettes", changed_data["palettes"]),
        ("fxdata", ["", "", "", ""]),
    ):
        if key == failed:
            responses.get(
                f"http://example.com/json/{key}",
                status=500,
                body="Internal Server Error",
                content_type="text/plain",
            )
        else:
            responses.get(
                f"http://example.com/json/{key}",
                status=200,
                body=json.dumps(body),
                content_type="application/json",
            )
    # Third update: both recover, and are fetched again together.
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: changed_data[key] for key in ("state", "info")}),
        content_type="application/json",
    )
    mock_catalog(responses, changed_data["effects"], changed_data["palettes"])

    device = await wled.update()
    assert device.effects[1].metadata is not None

    device = await wled.update()
    assert all(effect.metadata is None for effect in device.effects.values())

    device = await wled.update()
    assert device.effects[0].name == "New Effect"
    assert all(effect.metadata is not None for effect in device.effects.values())
    assert requests_to(responses, "/json/effects") == 2 + (failed == "effects")
    assert requests_to(responses, "/json/fxdata") == 3
    assert requests_to(responses, "/json/palettes") == 2


def mock_cfg(responses: aioresponses, **kwargs: Any) -> None:
    """Register the device's configuration endpoint."""
    responses.get("http://example.com/json/cfg", **kwargs)


def mock_si(responses: aioresponses, data: dict[str, Any]) -> None:
    """Register a state and info update."""
    responses.get(
        "http://example.com/json/si",
        status=200,
        body=json.dumps({key: data[key] for key in ("state", "info")}),
        content_type="application/json",
    )


async def test_update_fetches_led_config(responses: aioresponses, wled: WLED) -> None:
    """Test the LED setup is fetched once, keeping only that from the config."""
    wled_data = load_fixture_json("wled")
    mock_json_and_presets(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(
            {"nw": {"ins": [{"ssid": "Secret"}]}}
            | load_fixture_json("led_config/wled-16.0.0-ws2805")
        ),
        content_type="application/json",
    )
    mock_si(responses, wled_data)

    device = await wled.update()
    device = await wled.update()

    assert device.led_config is not None
    assert device.led_config.outputs[0].has_cct
    assert requests_to(responses, "/json/cfg") == 1
    # Nothing but the LED setup is kept, like the network settings.
    assert "Secret" not in repr(wled._catalog)  # pylint: disable=protected-access


async def test_update_without_led_config(responses: aioresponses, wled: WLED) -> None:
    """Test a device without the config endpoint isn't asked for it again."""
    wled_data = load_fixture_json("wled")
    mock_json_and_presets(responses, wled_data)
    mock_cfg(responses, status=404, body="Not Found", content_type="text/plain")
    mock_si(responses, wled_data)

    device = await wled.update()
    device = await wled.update()

    assert device.led_config is None
    assert requests_to(responses, "/json/cfg") == 1


async def test_update_led_config_connection_error(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a connection error on the config doesn't fail the update."""
    wled_data = load_fixture_json("wled")
    mock_json_and_presets(responses, wled_data)
    for _ in range(3):
        mock_cfg(responses, exception=aiohttp.ClientError("gone"))
    # Second update: the config is asked for again, and now it answers.
    mock_si(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(load_fixture_json("led_config/wled-16.0.0-ws2812")),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.led_config is None

    device = await wled.update()
    assert device.led_config is not None


async def test_update_led_config_after_led_setup_change(
    responses: aioresponses, wled: WLED
) -> None:
    """Test the config is fetched again when the light capabilities change."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["leds"]["lc"] = 1
    wled_data["info"]["leds"]["seglc"] = [1]
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["leds"]["lc"] = 7
    changed_data["info"]["leds"]["seglc"] = [7]
    mock_json_and_presets(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(load_fixture_json("led_config/wled-16.0.0-ws2812")),
        content_type="application/json",
    )
    # Second update: the LED type changed to one with warm and cold white.
    mock_si(responses, changed_data)
    mock_catalog(responses, changed_data["effects"], changed_data["palettes"])
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(load_fixture_json("led_config/wled-16.0.0-ws2805")),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.led_config is not None
    assert not device.led_config.outputs[0].has_cct

    device = await wled.update()
    assert device.led_config is not None
    assert device.led_config.outputs[0].has_cct
    assert requests_to(responses, "/json/cfg") == 2


async def test_update_led_config_retried_after_an_error(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a config the device couldn't send isn't known, and is asked again."""
    wled_data = load_fixture_json("wled")
    mock_json_and_presets(responses, wled_data)
    mock_cfg(responses, status=500, body="Oops", content_type="text/plain")
    mock_si(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(load_fixture_json("led_config/wled-16.0.0-ws2812")),
        content_type="application/json",
    )

    device = await wled.update()
    assert device.led_config is None

    device = await wled.update()
    assert device.led_config is not None


async def test_update_led_config_not_known_when_refetch_fails(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a changed LED setup that can't be fetched isn't reported as the old one."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["leds"]["lc"] = 1
    wled_data["info"]["leds"]["seglc"] = [1]
    changed_data = json.loads(json.dumps(wled_data))
    changed_data["info"]["leds"]["lc"] = 7
    changed_data["info"]["leds"]["seglc"] = [7]
    mock_json_and_presets(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(load_fixture_json("led_config/wled-16.0.0-ws2812")),
        content_type="application/json",
    )
    mock_si(responses, changed_data)
    mock_catalog(responses, changed_data["effects"], changed_data["palettes"])
    for _ in range(3):
        mock_cfg(responses, exception=aiohttp.ClientError("gone"))

    device = await wled.update()
    assert device.led_config is not None

    device = await wled.update()
    assert device.led_config is None


async def test_update_led_config_looked_at_again_now_and_then(
    responses: aioresponses, wled: WLED
) -> None:
    """Test the config is fetched again after a while, like for a new blend."""
    wled_data = load_fixture_json("wled")
    ws2805 = load_fixture_json("led_config/wled-16.0.0-ws2805")
    reblended = json.loads(json.dumps(ws2805))
    reblended["hw"]["led"]["cb"] = 80
    mock_json_and_presets(responses, wled_data)
    mock_cfg(
        responses, status=200, body=json.dumps(ws2805), content_type="application/json"
    )
    mock_si(responses, wled_data)
    mock_si(responses, wled_data)
    mock_cfg(
        responses,
        status=200,
        body=json.dumps(reblended),
        content_type="application/json",
    )

    with patch("wled.wled.time.monotonic", return_value=1000.0):
        device = await wled.update()
    with patch("wled.wled.time.monotonic", return_value=1100.0):
        device = await wled.update()
    assert device.led_config is not None
    assert device.led_config.cct_blend == 30
    assert requests_to(responses, "/json/cfg") == 1

    with patch("wled.wled.time.monotonic", return_value=1400.0):
        device = await wled.update()
    assert device.led_config is not None
    assert device.led_config.cct_blend == 80
    assert requests_to(responses, "/json/cfg") == 2


async def test_update_polls_state_and_info_once_catalog_is_cached(
    responses: aioresponses, wled: WLED
) -> None:
    """Test later updates skip the effects and palettes lists of /json."""
    mock_json_and_presets(responses)
    mock_json_and_presets(responses, cached=True)

    await wled.update()
    await wled.update()

    assert requests_to(responses, "/json") == 1
    assert requests_to(responses, "/json/si") == 1


async def test_update_keeps_presets_when_their_version_is_zero(
    responses: aioresponses, wled: WLED
) -> None:
    """Test presets aren't fetched again while the device reports pmt 0."""
    # Without NTP, a device reports a pmt of 0 until a preset is saved.
    wled_data = load_fixture_json("wled")
    wled_data["info"]["fs"]["pmt"] = 0
    mock_json_and_presets(responses, wled_data)
    mock_json_and_presets(responses, wled_data, cached=True)

    await wled.update()
    await wled.update()

    assert requests_to(responses, "/presets.json") == 1


@pytest.mark.parametrize("body", [[1, 2], "busy", 3, None])
async def test_json_error_body_is_passed_on_as_sent(
    responses: aioresponses, wled: WLED, body: object
) -> None:
    """Test a JSON error body that isn't an object comes through unchanged."""
    responses.get(
        "http://example.com/json/state",
        status=500,
        body=json.dumps(body),
        content_type="application/json",
    )

    with pytest.raises(WLEDStatusError) as exc_info:
        await wled.request("/json/state")

    assert exc_info.value.body == body


async def test_request_retries_when_device_is_busy(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a busy answer from older WLED versions is tried again."""
    responses.get(
        "http://example.com/json/state",
        status=503,
        body='{"error": 3}',
        content_type="application/json",
    )
    responses.get(
        "http://example.com/json/state",
        status=200,
        body='{"on": true}',
        content_type="application/json",
    )

    assert await wled.request("/json/state") == {"on": True}


async def test_request_gives_up_when_device_stays_busy(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a device that stays busy ends with its status error."""
    for _ in range(3):
        responses.get(
            "http://example.com/json/state",
            status=503,
            body='{"error": 3}',
            content_type="application/json",
        )

    with pytest.raises(WLEDStatusError) as exc_info:
        await wled.request("/json/state")

    assert exc_info.value.status == 503


async def test_request_timeout_covers_reading_the_response(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a response that stalls halfway still times out."""
    wled.request_timeout = 0.05
    for _ in range(3):
        responses.get(
            "http://example.com/json",
            status=200,
            body="{}",
            content_type="application/json",
        )

    async def stalled_read(*_: Any) -> bytes:
        await asyncio.sleep(5)
        return b"{}"

    with (
        patch("aiohttp.ClientResponse.read", stalled_read),
        pytest.raises(WLEDConnectionTimeoutError),
    ):
        await wled.request("/json")


async def test_listen_asks_again_when_device_is_busy(wled: WLED) -> None:
    """Test listen() asks for the state again instead of reporting old data."""
    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    mock_client.send_json = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    # A busy device sends an error instead of its state.
    busy_msg = MagicMock()
    busy_msg.type = aiohttp.WSMsgType.TEXT
    busy_msg.json.return_value = {"error": 3}

    close_msg = MagicMock()
    close_msg.type = aiohttp.WSMsgType.CLOSE

    state_msg = MagicMock()
    state_msg.type = aiohttp.WSMsgType.TEXT
    state_msg.json.return_value = {"state": full_device_data()["state"]}

    # Still busy when asked again; then the device sends its state, and later
    # turns busy once more.
    mock_client.receive = AsyncMock(
        side_effect=[busy_msg, busy_msg, busy_msg, state_msg, busy_msg, close_msg]
    )

    callback = MagicMock()
    with pytest.raises(WLEDConnectionClosedError):
        await wled.listen(callback)

    # Asked once per busy streak, not once per error.
    assert mock_client.send_json.await_count == 2
    mock_client.send_json.assert_awaited_with({"v": True})
    callback.assert_called_once()


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


async def test_listen_keeps_presets_when_the_file_is_unusable(
    responses: aioresponses, wled: WLED
) -> None:
    """Test listen() keeps the presets when the presets file can't be used."""
    wled_data = load_fixture_json("wled")

    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access
    presets = wled._device.presets  # pylint: disable=protected-access

    text_msg = MagicMock()
    text_msg.type = aiohttp.WSMsgType.TEXT
    text_msg.json.return_value = wled_data

    close_msg = MagicMock()
    close_msg.type = aiohttp.WSMsgType.CLOSE

    mock_client.receive = AsyncMock(side_effect=[text_msg, close_msg])

    responses.get(
        "http://example.com/presets.json",
        status=200,
        body="",
        content_type="text/plain",
    )

    callback = MagicMock()
    with pytest.raises(WLEDConnectionClosedError):
        await wled.listen(callback)

    callback.assert_called_once()
    assert callback.call_args.args[0].presets == presets
    # Not marked as seen, so the next message tries the presets again.
    assert wled._presets_version is None  # pylint: disable=protected-access


async def test_listen_invalid_json_message(wled: WLED) -> None:
    """Test listen() raises a WLED error for a message that isn't valid JSON."""
    mock_client = MagicMock()
    mock_client.closed = False
    mock_client.close = AsyncMock()
    wled._client = mock_client  # pylint: disable=protected-access
    wled._device = Device.from_dict(full_device_data())  # pylint: disable=protected-access

    text_msg = MagicMock()
    text_msg.type = aiohttp.WSMsgType.TEXT
    text_msg.json.side_effect = json.JSONDecodeError("Expecting value", "{", 1)
    mock_client.receive = AsyncMock(return_value=text_msg)

    with pytest.raises(WLEDInvalidResponseError, match="WebSocket"):
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


@pytest.mark.parametrize(
    ("kwargs", "expected_seg"),
    [
        (
            {"custom1": 10, "custom2": 200, "custom3": 31},
            {"c1": 10, "c2": 200, "c3": 31, "id": 0},
        ),
        (
            {"option1": True, "option2": False, "option3": True},
            {"o1": True, "o2": False, "o3": True, "id": 0},
        ),
    ],
    ids=["custom_sliders", "options"],
)
async def test_segment_effect_parameters(
    responses: aioresponses, wled: WLED, kwargs: dict, expected_seg: dict
) -> None:
    """Test the effect sliders and options are sent, including a false option."""
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


async def test_segments_effect_parameters(responses: aioresponses, wled: WLED) -> None:
    """Test SegmentUpdate carries the effect sliders and options too."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segments([SegmentUpdate(segment_id=0, custom1=64, option3=True)])

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [{"c1": 64, "o3": True, "id": 0}], "v": True},
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


async def test_segment_colors_use_the_segment_with_that_id(
    responses: aioresponses, wled: WLED
) -> None:
    """Test partial colors fall back on the segment with that ID, not position."""
    wled_data = load_fixture_json("wled")
    first = wled_data["state"]["seg"][0]
    wled_data["state"]["seg"] = [
        first | {"id": 0, "col": [[1, 1, 1]]},
        first | {"id": 2, "col": [[2, 2, 2]]},
    ]
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(2, color_secondary=(0, 255, 0))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [{"col": [[2, 2, 2], [0, 255, 0]], "id": 2}], "v": True},
    )


async def test_segment_colors_for_an_unknown_segment(
    responses: aioresponses, wled: WLED
) -> None:
    """Test partial colors on a segment that isn't in the state don't crash."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segment(5, color_tertiary=(0, 0, 255))

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [{"col": [[0, 0, 0], [0, 0, 0], [0, 0, 255]], "id": 5}], "v": True},
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


async def test_segments_in_one_request(responses: aioresponses, wled: WLED) -> None:
    """Test several segment updates go out together, with one transition."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segments(
        [
            SegmentUpdate(segment_id=0, effect="breathe", color_primary=(255, 0, 0)),
            SegmentUpdate(segment_id=1, on=False, palette="Random Cycle"),
        ],
        transition=10,
    )

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {
            "seg": [
                {"fx": 3, "col": [[255, 0, 0]], "id": 0},
                {"on": False, "pal": 1, "id": 1},
            ],
            "tt": 10,
            "v": True,
        },
    )


async def test_segments_skips_updates_without_changes(
    responses: aioresponses, wled: WLED
) -> None:
    """Test an update that changes nothing is left out of the request."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segments(
        [
            SegmentUpdate(segment_id=0, brightness=10),
            SegmentUpdate(segment_id=1, effect="No such effect"),
        ]
    )

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [{"bri": 10, "id": 0}], "v": True},
    )


async def test_segments_without_updates(responses: aioresponses, wled: WLED) -> None:
    """Test a transition alone is still sent without any segment updates."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.segments([], transition=7)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"tt": 7, "v": True},
    )


@pytest.mark.parametrize(
    ("preset_input", "expected_ps"),
    [
        (1, 1),
        ("My Preset", 1),
        ("my preset", 1),
        ("5", 5),
    ],
    ids=["by_id", "by_name", "by_name_any_case", "by_id_as_text"],
)
async def test_preset(
    responses: aioresponses, wled: WLED, preset_input: int | str, expected_ps: int | str
) -> None:
    """Test setting a preset by ID or by name."""
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
        ("7", 7),
    ],
    ids=["by_id", "by_name", "by_id_as_text"],
)
async def test_playlist(
    responses: aioresponses,
    wled: WLED,
    playlist_input: int | str,
    expected_ps: int | str,
) -> None:
    """Test setting a playlist by ID or by name."""
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


async def test_next_playlist_entry(responses: aioresponses, wled: WLED) -> None:
    """Test skipping to the next entry of the running playlist."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.next_playlist_entry()

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"np": True, "v": True},
    )


async def test_segment_clones_is_not_sent(responses: aioresponses, wled: WLED) -> None:
    """Test the deprecated clones warns, and isn't sent to the device."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    with pytest.warns(DeprecationWarning, match="clones") as warned:
        await wled.segment(0, clones=1, on=True)

    # Once, and pointing at the caller rather than at the library.
    assert len(warned) == 1
    assert warned[0].filename == __file__

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"seg": [{"id": 0, "on": True}], "v": True},
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
        (
            {"send_groups": SyncGroup.GROUP1 | SyncGroup.GROUP3},
            {"udpn": {"sgrp": 5}, "v": True},
        ),
        (
            {"receive": False, "receive_groups": SyncGroup.GROUP2},
            {"udpn": {"rgrp": 2}, "v": True},
        ),
    ],
    ids=["send", "send_groups", "receive_groups_win"],
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
            {"dur": 30, "mode": 1, "on": True, "tbri": 50},
        ),
        ({"fade": False}, {"mode": 0}),
        ({"mode": NightlightMode.SUNRISE}, {"mode": 3}),
        ({"mode": NightlightMode.COLOR_FADE, "fade": False}, {"mode": 2}),
    ],
    ids=["on", "all_params", "no_fade", "mode", "mode_wins_over_fade"],
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


@pytest.mark.parametrize("method", ["preset", "playlist"])
async def test_unknown_preset_or_playlist_name(
    responses: aioresponses, wled: WLED, method: str
) -> None:
    """Test an unknown name is refused rather than sent to the device."""
    # WLED would read a name starting with "r" as a random preset.
    await prepare_wled_with_device(responses, wled)

    with pytest.raises(WLEDError, match="Unknown"):
        await getattr(wled, method)("relax")


@pytest.mark.parametrize(
    ("version", "receive", "sync_state", "expected"),
    [
        ("0.14.0", True, {}, {"recv": True}),
        ("0.14.0", False, {}, {"recv": False}),
        ("16.0.0", False, {"rgrp": 6}, {"rgrp": 0}),
        ("16.0.0", True, {"rgrp": 6, "sgrp": 1}, {"rgrp": 6}),
        ("16.0.0", True, {"rgrp": 0, "sgrp": 4}, {"rgrp": 4}),
        ("16.0.0", True, {"rgrp": 0, "sgrp": 0}, {"rgrp": 1}),
        ("0.15.0-b1", False, {"rgrp": 1}, {"rgrp": 0}),
    ],
    ids=[
        "0.14_on",
        "0.14_off",
        "groups_off",
        "groups_keep_current",
        "groups_from_send_groups",
        "groups_fallback",
        "groups_on_beta",
    ],
)
async def test_sync_receive(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    responses: aioresponses,
    wled: WLED,
    version: str,
    receive: bool,
    sync_state: dict,
    expected: dict,
) -> None:
    """Test receiving sync is switched the way the firmware version takes it."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["ver"] = version
    wled_data["state"]["udpn"] |= sync_state
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.sync(receive=receive)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"udpn": expected, "v": True},
    )


@pytest.mark.parametrize(
    ("version", "expected"),
    [("16.0.0", {"rgrp": 1}), (None, {"recv": True})],
    ids=["loads_the_device_first", "unknown_version"],
)
async def test_sync_receive_without_loaded_device(
    responses: aioresponses, wled: WLED, version: str | None, expected: dict
) -> None:
    """Test receive looks up the device first, and handles an unknown version."""
    wled_data = load_fixture_json("wled")
    if version is None:
        del wled_data["info"]["ver"]
    else:
        wled_data["info"]["ver"] = version
    wled_data["state"]["udpn"] |= {"rgrp": 0, "sgrp": 1}
    mock_json_and_presets(responses, wled_data)
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
        {"udpn": expected, "v": True},
    )


async def test_sync_receive_uses_send_groups_set_along(
    responses: aioresponses, wled: WLED
) -> None:
    """Test turning receive on uses the send groups set in the same call."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["ver"] = "16.0.0"
    wled_data["state"]["udpn"] |= {"rgrp": 0, "sgrp": 1}
    await prepare_wled_with_device(responses, wled, wled_data=wled_data)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.sync(send_groups=SyncGroup.GROUP4, receive=True)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"udpn": {"sgrp": 8, "rgrp": 8}, "v": True},
    )


async def test_preset_name_with_digit_like_characters(
    responses: aioresponses, wled: WLED
) -> None:
    """Test a name of characters that look like digits is looked up by name."""
    await prepare_wled_with_device(responses, wled)

    with pytest.raises(WLEDError, match="Unknown preset"):
        await wled.preset("²")


@pytest.mark.parametrize(
    ("call", "key", "expected"),
    [
        ("master", "tt", 655),
        ("transition", "transition", 655),
        ("segments", "tt", 655),
    ],
)
async def test_transition_is_clamped(
    responses: aioresponses, wled: WLED, call: str, key: str, expected: int
) -> None:
    """Test a transition beyond what WLED can hold is capped, not wrapped."""
    await prepare_wled_with_device(responses, wled)
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    if call == "master":
        await wled.master(transition=700)
    elif call == "transition":
        await wled.transition(700)
    else:
        await wled.segments([], transition=700)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {key: expected, "v": True},
    )


@pytest.mark.parametrize("on", [True, False])
async def test_audio_reactive(responses: aioresponses, wled: WLED, on: bool) -> None:
    """Test setting AudioReactive usermod state."""
    responses.post(
        "http://example.com/json/state",
        status=200,
        body="{}",
        content_type="application/json",
    )

    await wled.audio_reactive(on=on)

    assert_post_payload(
        responses,
        "http://example.com/json/state",
        {"AudioReactive": {"enabled": on}, "v": True},
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


# What WLED answers to a firmware upload, trimmed to the part that matters.
UPDATE_SUCCESSFUL_PAGE = (
    "<!DOCTYPE html><html><body><h2>Update successful!</h2>Rebooting..."
    "<script>setTimeout(RP,11000)</script></body></html>"
)
ACCESS_DENIED_PAGE = (
    "<!DOCTYPE html><html><body><h2>Access Denied</h2>"
    "Client is not on local subnet.<br><br><button>Back</button></body></html>"
)
UPDATE_FAILED_PAGE = (
    "<!DOCTYPE html><html><body><h2>Update failed!</h2>"
    "Firmware release name mismatch<br><br><button>Back</button></body></html>"
)


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
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
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
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
    )
    await wled.upgrade(version="0.15.0")


@pytest.mark.parametrize(
    ("info_override", "call_kwargs", "download_repo"),
    [
        pytest.param(
            {"repo": "MoonModules/WLED"}, {}, "MoonModules/WLED", id="device_repo"
        ),
        pytest.param(
            {"repo": "MoonModules/WLED"},
            {"repo": DEFAULT_REPO},
            DEFAULT_REPO,
            id="explicit_repo",
        ),
        pytest.param({"repo": " "}, {}, DEFAULT_REPO, id="blank_device_repo"),
        pytest.param({}, {}, DEFAULT_REPO, id="missing_device_repo"),
        pytest.param(
            {"repo": "FORK_A/WLED"},
            {"repo": "FORK_B/WLED"},
            "FORK_B/WLED",
            id="migrate_to_fork",
        ),
    ],
)
async def test_upgrade_repo_selection(
    responses: aioresponses,
    wled: WLED,
    info_override: dict,
    call_kwargs: dict,
    download_repo: str,
) -> None:
    """Test upgrade selects the expected firmware repository."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    wled_data["info"]["ver"] = "0.14.0"
    wled_data["info"].update(info_override)
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    responses.get(
        f"https://github.com/{download_repo}/releases/download/v0.15.0/"
        "WLED_0.15.0_ESP32.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
    )
    await wled.upgrade(version="0.15.0", **call_kwargs)


async def test_upgrade_uses_release_name(responses: aioresponses, wled: WLED) -> None:
    """Test upgrade names the firmware after the brand and release name."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    wled_data["info"]["ver"] = "0.14.0"
    wled_data["info"]["brand"] = "QuinLED"
    wled_data["info"]["release"] = "Dig2Go"
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/"
        "QuinLED_0.15.0_Dig2Go.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
    )

    await wled.upgrade(version="0.15.0")


@pytest.mark.parametrize(
    "repo",
    [
        "../..",
        "wled/..",
        "wled/WLED/../../evil/repo",
        "wled",
        "evil.com/WLED",
        "wled/WLED?x=1",
        "wled/WLED#x",
        "wled/WLÉD",
    ],
)
async def test_upgrade_rejects_invalid_repo(
    responses: aioresponses, wled: WLED, repo: str
) -> None:
    """Test upgrade refuses a repository that isn't a plain owner/name pair."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    wled_data["info"]["ver"] = "0.14.0"
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    with pytest.raises(WLEDUpgradeError, match="Invalid firmware repository"):
        await wled.upgrade(version="0.15.0", repo=repo)


async def test_upgrade_without_a_known_repo(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade asks for a repository when the device's isn't known."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    wled_data["info"]["ver"] = "0.14.0"
    wled_data["info"]["product"] = "Some Fork"
    wled_data["info"]["repo"] = "unknown"
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    with pytest.raises(WLEDUpgradeError, match="pass the repository"):
        await wled.upgrade(version="0.15.0")

    # With the repository given, it upgrades as usual.
    responses.get(
        "https://github.com/some/fork/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
    )
    await wled.upgrade(version="0.15.0", repo="some/fork")


FIRMWARE = b"fake firmware"
FIRMWARE_SHA256 = hashlib.sha256(FIRMWARE).hexdigest()


def mock_release(
    responses: aioresponses,
    assets: list[dict[str, Any]],
    *,
    repo: str = DEFAULT_REPO,
    version: str = "0.15.0",
) -> None:
    """Register the GitHub API answer for a release and its assets."""
    responses.get(
        f"https://api.github.com/repos/{repo}/releases/tags/v{version}",
        status=200,
        body=json.dumps({"tag_name": f"v{version}", "assets": assets}),
        content_type="application/json",
    )


def mock_download_and_upload(
    responses: aioresponses,
    file_name: str,
    *,
    repo: str = DEFAULT_REPO,
    version: str = "0.15.0",
) -> None:
    """Register the firmware download and a successful upload to the device."""
    responses.get(
        f"https://github.com/{repo}/releases/download/v{version}/{file_name}",
        status=200,
        body=FIRMWARE,
    )
    responses.post(
        "http://example.com/update",
        status=200,
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
    )


def downloaded(responses: aioresponses, url: str) -> bool:
    """Return whether the given URL was fetched."""
    return bool(responses.requests and responses.requests.get(("GET", URL(url))))


async def test_upgrade_finds_fork_asset_by_release_name(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade finds a fork's file when it isn't prefixed with the brand."""
    wled_data = load_fixture_json("wled")
    wled_data["info"].update(
        {
            "arch": "esp32",
            "ver": "16.0.0",
            "brand": "QuinLED",
            "release": "Dig2Go-Audioreactive",
            "repo": "intermittech/QuinLED-Firmware",
        }
    )
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    repo = "intermittech/QuinLED-Firmware"
    mock_release(
        responses,
        [
            {"name": "WLED_16.0.1_Dig2Go.bin"},
            {"name": "WLED_16.0.1_Dig2Go-Audioreactive.bin"},
        ],
        repo=repo,
        version="16.0.1",
    )
    mock_download_and_upload(
        responses, "WLED_16.0.1_Dig2Go-Audioreactive.bin", repo=repo, version="16.0.1"
    )

    await wled.upgrade(version="16.0.1")

    assert downloaded(
        responses,
        f"https://github.com/{repo}/releases/download/v16.0.1/"
        "WLED_16.0.1_Dig2Go-Audioreactive.bin",
    )


@pytest.mark.parametrize(
    ("info", "assets", "expected"),
    [
        # The exact file WLED names after brand, version, and release name.
        ({}, [{"name": "WLED_16.0.1_ESP32.bin"}], True),
        # A fork's file, prefixed differently, found by version and release.
        (
            {"product": "MoonModules", "release": "esp32_4MB_V4_M"},
            [{"name": "WLEDMM_16.0.1_esp32_4MB_V4_M.bin"}],
            True,
        ),
        # A custom build has no file in the release.
        (
            {"product": "MoonModules", "release": "Apollo_M-1-Rev2"},
            [{"name": "WLEDMM_16.0.1_esp32_4MB_V4_M.bin"}],
            False,
        ),
        # More than one candidate is no answer either.
        (
            {"brand": "Fork", "release": "ESP32"},
            [{"name": "A_16.0.1_ESP32.bin"}, {"name": "B_16.0.1_ESP32.bin"}],
            False,
        ),
    ],
)
async def test_firmware_available(
    responses: aioresponses,
    wled: WLED,
    info: dict[str, str],
    assets: list[dict[str, Any]],
    *,
    expected: bool,
) -> None:
    """Test firmware_available() tells whether a release has this device's file."""
    wled_data = load_fixture_json("wled")
    wled_data["info"].update({"arch": "esp32", "ver": "16.0.0", "release": "ESP32"})
    wled_data["info"].update(info)
    mock_json_and_presets(responses, wled_data)
    device = await wled.update()
    assert device.info.repo is not None
    mock_release(responses, assets, repo=device.info.repo, version="16.0.1")

    assert await wled.firmware_available(version="16.0.1") is expected


async def test_firmware_available_without_a_known_repo(
    responses: aioresponses, wled: WLED
) -> None:
    """Test firmware_available() is False when the device's repo isn't known."""
    wled_data = load_fixture_json("wled")
    wled_data["info"].update({"arch": "esp32", "product": "Some Fork"})
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    assert await wled.firmware_available(version="16.0.1") is False

    # With the repository given, it looks there.
    mock_release(
        responses,
        [{"name": "WLED_16.0.1_ESP32.bin"}],
        repo="some/fork",
        version="16.0.1",
    )
    assert await wled.firmware_available(version="16.0.1", repo="some/fork") is True


async def test_firmware_available_unsupported_architecture(
    responses: aioresponses, wled: WLED
) -> None:
    """Test firmware_available() is False for a device upgrade() can't flash."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "rp2040"
    mock_json_and_presets(responses, wled_data)
    await wled.update()

    assert await wled.firmware_available(version="16.0.1") is False


async def test_firmware_available_release_does_not_exist(
    responses: aioresponses, wled: WLED
) -> None:
    """Test firmware_available() is False for a version without a release."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    responses.get(
        f"https://api.github.com/repos/{DEFAULT_REPO}/releases/tags/v99.0.0",
        status=404,
        body="{}",
        content_type="application/json",
    )

    assert await wled.firmware_available(version="99.0.0") is False


async def test_firmware_available_when_github_cant_tell(
    responses: aioresponses, wled: WLED
) -> None:
    """Test firmware_available() raises when GitHub can't be asked."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    responses.get(
        f"https://api.github.com/repos/{DEFAULT_REPO}/releases/tags/v16.0.1",
        status=403,
        body='{"message": "API rate limit exceeded"}',
        content_type="application/json",
    )

    with pytest.raises(WLEDError, match="Could not look up"):
        await wled.firmware_available(version="16.0.1")


async def test_firmware_available_no_session_raises() -> None:
    """Test firmware_available() raises when there is no session and no device."""
    wled = WLED("example.com")
    with (
        patch.object(wled, "update", new_callable=AsyncMock),
        pytest.raises(WLEDError, match="Unexpected"),
    ):
        await wled.firmware_available(version="16.0.1")


async def test_firmware_available_updates_first(
    responses: aioresponses, wled: WLED
) -> None:
    """Test firmware_available() fetches the device first when needed."""
    wled_data = load_fixture_json("wled")
    wled_data["info"]["arch"] = "esp32"
    mock_json_and_presets(responses, wled_data)
    mock_release(responses, [{"name": "WLED_16.0.1_ESP32.bin"}], version="16.0.1")

    assert await wled.firmware_available(version="16.0.1") is True


async def test_upgrade_refuses_ambiguous_fork_asset(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade doesn't guess when several files match the release name."""
    wled_data = load_fixture_json("wled")
    wled_data["info"].update(
        {"arch": "esp32", "ver": "0.14.0", "brand": "QuinLED", "release": "Dig2Go"}
    )
    mock_json_and_presets(responses, wled_data)
    await wled.update()
    mock_release(
        responses,
        [{"name": "WLED_0.15.0_Dig2Go.bin"}, {"name": "Other_0.15.0_Dig2Go.bin"}],
    )

    with pytest.raises(
        WLEDUpgradeError, match=re.escape("QuinLED_0.15.0_Dig2Go.bin does not")
    ):
        await wled.upgrade(version="0.15.0")


@pytest.mark.parametrize(
    "digest",
    [f"sha256:{FIRMWARE_SHA256}", None, "md5:0123456789abcdef", "sha256:short"],
)
async def test_upgrade_with_usable_or_missing_digest(
    responses: aioresponses, wled: WLED, digest: str | None
) -> None:
    """Test upgrade installs a matching file, and one without a usable digest."""
    await prepare_wled_for_upgrade(responses, wled)
    mock_release(responses, [{"name": "WLED_0.15.0_ESP32.bin", "digest": digest}])
    mock_download_and_upload(responses, "WLED_0.15.0_ESP32.bin")

    await wled.upgrade(version="0.15.0")


async def test_upgrade_refuses_firmware_not_matching_digest(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade refuses a download that doesn't match GitHub's digest."""
    await prepare_wled_for_upgrade(responses, wled)
    mock_release(
        responses, [{"name": "WLED_0.15.0_ESP32.bin", "digest": f"sha256:{'0' * 64}"}]
    )
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=FIRMWARE,
    )

    with pytest.raises(WLEDUpgradeError, match="does not match the digest"):
        await wled.upgrade(version="0.15.0")

    # Nothing may have been sent to the device.
    assert responses.requests
    assert ("POST", URL("http://example.com/update")) not in responses.requests


async def test_upgrade_release_does_not_exist(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade reports a version that has no release on GitHub."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases/tags/v0.99.0",
        status=404,
        body='{"message": "Not Found"}',
        content_type="application/json",
    )

    with pytest.raises(
        WLEDUpgradeError, match=re.escape("0.99.0 does not exist in wled/WLED")
    ):
        await wled.upgrade(version="0.99.0")


async def test_upgrade_release_asset_does_not_exist(
    responses: aioresponses, wled: WLED
) -> None:
    """Test upgrade reports a release without a file for this device."""
    await prepare_wled_for_upgrade(responses, wled)
    mock_release(responses, [{"name": "WLED_0.15.0_ESP8266.bin"}])

    with pytest.raises(
        WLEDUpgradeError, match=re.escape("WLED_0.15.0_ESP32.bin does not exist")
    ):
        await wled.upgrade(version="0.15.0")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (403, '{"message": "API rate limit exceeded"}'),
        (200, "not json"),
        (200, '{"assets": null}'),
        (200, "[]"),
    ],
)
async def test_upgrade_falls_back_when_release_lookup_fails(
    responses: aioresponses, wled: WLED, status: int, body: str
) -> None:
    """Test upgrade still works by file name when GitHub's API can't help."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://api.github.com/repos/wled/WLED/releases/tags/v0.15.0",
        status=status,
        body=body,
        content_type="application/json",
    )
    mock_download_and_upload(responses, "WLED_0.15.0_ESP32.bin")

    await wled.upgrade(version="0.15.0")


@pytest.mark.parametrize(
    "version",
    ["0.15.0/../../../evil/repo/releases/download/v1.0.0", "latest", "v0.15.0", ""],
)
async def test_upgrade_rejects_invalid_version(
    responses: aioresponses, wled: WLED, version: str
) -> None:
    """Test upgrade refuses a version that could change the download URL."""
    await prepare_wled_for_upgrade(responses, wled)

    with pytest.raises(WLEDUpgradeError, match="Invalid firmware version"):
        await wled.upgrade(version=version)


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (aiohttp.ClientError("gone"), WLEDConnectionError),
        (TimeoutError(), WLEDConnectionTimeoutError),
    ],
)
async def test_upgrade_upload_fails(
    responses: aioresponses,
    wled: WLED,
    exception: Exception,
    expected: type[Exception],
) -> None:
    """Test an upload failure names the device, not GitHub."""
    await prepare_wled_for_upgrade(responses, wled)
    mock_release(responses, [{"name": "WLED_0.15.0_ESP32.bin"}])
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=FIRMWARE,
    )
    responses.post("http://example.com/update", exception=exception)

    with pytest.raises(
        expected, match=re.escape("uploading the firmware to example.com")
    ):
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
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
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
        body=UPDATE_SUCCESSFUL_PAGE,
        content_type="text/html",
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


@pytest.mark.parametrize(
    ("status", "page", "reason"),
    [
        # Seen in the wild: a rejected upload answered with a 200 (#2092).
        (200, ACCESS_DENIED_PAGE, "Access Denied Client is not on local subnet."),
        (401, ACCESS_DENIED_PAGE, "Access Denied Client is not on local subnet."),
        (500, UPDATE_FAILED_PAGE, "Update failed! Firmware release name mismatch"),
        (200, "", "HTTP 200"),
        (500, UPDATE_SUCCESSFUL_PAGE, "Update successful! Rebooting..."),
    ],
)
async def test_upgrade_rejected_by_device(
    responses: aioresponses,
    wled: WLED,
    status: int,
    page: str,
    reason: str,
) -> None:
    """Test upgrade raises when the device doesn't accept the upload."""
    await prepare_wled_for_upgrade(responses, wled)
    responses.get(
        "https://github.com/wled/WLED/releases/download/v0.15.0/WLED_0.15.0_ESP32.bin",
        status=200,
        body=b"fake firmware",
    )
    responses.post(
        "http://example.com/update",
        status=status,
        body=page,
        content_type="text/html",
    )

    with pytest.raises(WLEDUpgradeError) as exc_info:
        await wled.upgrade(version="0.15.0")

    assert str(exc_info.value) == (
        f"WLED device did not accept the firmware upload: {reason}"
    )


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
