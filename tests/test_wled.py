"""Tests for `wled.WLED`."""
import asyncio
from collections.abc import Generator
from unittest.mock import patch

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from wled import WLED
from wled.exceptions import WLEDConnectionError, WLEDError


@pytest.fixture(autouse=True)
def mock_get_version_from_github() -> Generator[None, None, None]:
    """Patch out connection to GitHub."""
    with patch(
        "wled.WLED.get_wled_versions_from_github",
        return_value={"version_latest_stable": None, "version_latest_beta": None},
        side_effect=WLEDConnectionError
    ):
        yield


@pytest.mark.asyncio
async def test_json_request(aresponses: ResponsesMockServer) -> None:
    """Test JSON response is handled correctly."""
    aresponses.add(
        "example.com",
        "/",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled.request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_text_request(aresponses: ResponsesMockServer) -> None:
    """Test non JSON response is handled correctly."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled.request("/")
        assert response == "OK"


@pytest.mark.asyncio
async def test_internal_session(aresponses: ResponsesMockServer) -> None:
    """Test JSON response is handled correctly."""
    aresponses.add(
        "example.com",
        "/",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"status": "ok"}',
        ),
    )
    async with WLED("example.com") as wled:
        response = await wled.request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_post_request(aresponses: ResponsesMockServer) -> None:
    """Test POST requests are handled correctly."""
    aresponses.add(
        "example.com", "/", "POST", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled.request("/", method="POST")
        assert response == "OK"


@pytest.mark.asyncio
async def test_backoff(aresponses: ResponsesMockServer) -> None:
    """Test requests are handled with retries."""

    async def response_handler(_: aiohttp.ClientResponse) -> Response:
        """Response handler for this test."""
        await asyncio.sleep(0.2)
        return aresponses.Response(body="Goodmorning!")

    aresponses.add(
        "example.com",
        "/",
        "GET",
        response_handler,
        repeat=2,
    )
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(status=200, text="OK")
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session, request_timeout=0.1)
        response = await wled.request("/")
        assert response == "OK"


@pytest.mark.asyncio
async def test_timeout(aresponses: ResponsesMockServer) -> None:
    """Test request timeout from WLED."""
    # Faking a timeout by sleeping
    async def response_handler(_: aiohttp.ClientResponse) -> Response:
        """Response handler for this test."""
        await asyncio.sleep(0.2)
        return aresponses.Response(body="Goodmorning!")

    # Backoff will try 3 times
    aresponses.add("example.com", "/", "GET", response_handler)
    aresponses.add("example.com", "/", "GET", response_handler)
    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session, request_timeout=0.1)
        with pytest.raises(WLEDConnectionError):
            assert await wled.request("/")


@pytest.mark.asyncio
async def test_http_error400(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 404 response handling."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(text="OMG PUPPIES!", status=404)
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        with pytest.raises(WLEDError):
            assert await wled.request("/")


@pytest.mark.asyncio
async def test_http_error500(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 500 response handling."""
    aresponses.add(
        "example.com",
        "/",
        "GET",
        aresponses.Response(
            body=b'{"status":"nok"}',
            status=500,
            headers={"Content-Type": "application/json"},
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        with pytest.raises(WLEDError):
            assert await wled.request("/")


@pytest.mark.asyncio
async def test_state_on(aresponses: ResponsesMockServer) -> None:
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.9.1"}}'
            ),
        ),
    )
    aresponses.add(
        "example.com",
        "/json/info",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"ver": "1.0"}',
        ),
    )
    aresponses.add(
        "example.com",
        "/json/state",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"on": false}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.state.on
        device = await wled.update()
        assert not device.state.on


@pytest.mark.asyncio
async def test_state_on_si_request(aresponses: ResponsesMockServer) -> None:
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )
    aresponses.add(
        "example.com",
        "/json/si",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"state": {"on": false},"info": {"ver": "1.0"}}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.state.on
        device = await wled.update()
        assert not device.state.on


@pytest.mark.asyncio
async def test_empty_responses(aresponses: ResponsesMockServer) -> None:
    """Test empty responses for WLED device state."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.8.6"}}'
            ),
        ),
    )
    aresponses.add(
        "example.com",
        "/json/info",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        ),
    )
    aresponses.add(
        "example.com",
        "/json/info",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"ver": "1.0"}',
        ),
    )
    aresponses.add(
        "example.com",
        "/json/state",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        ),
    )
    aresponses.add(
        "example.com",
        "/json/info",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"ver": "1.0"}',
        ),
    )
    aresponses.add(
        "example.com",
        "/json/state",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"on": false}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        await wled.update()


@pytest.mark.asyncio
async def test_empty_si_responses(aresponses: ResponsesMockServer) -> None:
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )
    aresponses.add(
        "example.com",
        "/json/si",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        ),
    )
    aresponses.add(
        "example.com",
        "/json/si",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"state": {"on": false}, "info": {"ver": "1.0"}}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        await wled.update()


@pytest.mark.asyncio
async def test_empty_full_responses(aresponses: ResponsesMockServer) -> None:
    """Test failure handling of full data request WLED device state."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        ),
    )
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()


@pytest.mark.asyncio
async def test_si_request_version_based(aresponses: ResponsesMockServer) -> None:
    """Test for supporting SI requests based on version data."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        assert wled._supports_si_request  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_not_supporting_si_request_version_based(
    aresponses: ResponsesMockServer,
) -> None:
    """Test for supporting SI requests based on version data."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.9.1"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        assert not wled._supports_si_request  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_si_request_probing_based(aresponses: ResponsesMockServer) -> None:
    """Test for supporting SI requests based on probing."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "INVALID VERSION NUMBER"}}'
            ),
        ),
    )

    aresponses.add(
        "example.com",
        "/json/si",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"yes": true}',
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        assert wled._supports_si_request  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_not_supporting_si_request_probing_based(
    aresponses: ResponsesMockServer,
) -> None:
    """Test for supporting SI requests based on probing."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "INVALID VERSION NUMBER"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.update()
        assert not wled._supports_si_request  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_info_contains_wv_true(aresponses: ResponsesMockServer) -> None:
    """Test for determining if wv is used and set to true."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {'
                '"ver": "0.11.1",'
                '"leds": {'
                '"count": 120,'
                '"rgbw": true,'
                '"wv": true'
                "}}}"
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.info.leds.wv


@pytest.mark.asyncio
async def test_info_contains_wv_false(aresponses: ResponsesMockServer) -> None:
    """Test for determining if wv is used and set to false."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {'
                '"ver": "0.11.1",'
                '"leds": {'
                '"count": 120,'
                '"rgbw": true,'
                '"wv": false'
                "}}}"
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert not device.info.leds.wv


@pytest.mark.asyncio
async def test_info_contains_no_wv(aresponses: ResponsesMockServer) -> None:
    """Test for determining if wv is used and set to false."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true},'
                '"effects": [], "palettes": [],'
                '"info": {'
                '"ver": "0.8.4",'
                '"leds": {'
                '"count": 120,'
                '"rgbw": true'
                "}}}"
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.info.leds.wv


@pytest.mark.asyncio
async def test_live_override_state_off(aresponses: ResponsesMockServer) -> None:
    """Test request of current WLED live override mode."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true, "lor": 0},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.state.lor == 0


@pytest.mark.asyncio
async def test_live_override_state_on(aresponses: ResponsesMockServer) -> None:
    """Test request of current WLED live override mode."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true, "lor": 1},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.state.lor == 1


@pytest.mark.asyncio
async def test_live_override_state_off_until_reboot(
    aresponses: ResponsesMockServer,
) -> None:
    """Test request of current WLED live override mode."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=(
                '{"state": {"on": true, "lor": 2},'
                '"effects": [], "palettes": [],'
                '"info": {"ver": "0.10.0"}}'
            ),
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert device.state.lor == 2


@pytest.mark.asyncio
async def test_reset(aresponses: ResponsesMockServer) -> None:
    """Test rebooting WLED device works."""
    aresponses.add(
        "example.com",
        "/reset",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "text/html"},
            text="<!DOCTYPE html>",
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.reset()
