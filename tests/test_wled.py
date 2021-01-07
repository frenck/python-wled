"""Tests for `wled.WLED`."""
import asyncio

import aiohttp
import pytest

from wled import WLED
from wled.__version__ import __version__
from wled.exceptions import WLEDConnectionError, WLEDError


@pytest.mark.asyncio
async def test_json_request(aresponses):
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
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_authenticated_request(aresponses):
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
        wled = WLED(
            "example.com",
            username="frenck",
            password="zerocool",
            session=session,
        )
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_text_request(aresponses):
    """Test non JSON response is handled correctly."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled._request("/")
        assert response == "OK"


@pytest.mark.asyncio
async def test_internal_session(aresponses):
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
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_post_request(aresponses):
    """Test POST requests are handled correctly."""
    aresponses.add(
        "example.com", "/", "POST", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled._request("/", method="POST")
        assert response == "OK"


@pytest.mark.asyncio
async def test_request_port(aresponses):
    """Test WLED running on non-standard port."""
    aresponses.add(
        "example.com:3333",
        "/",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=200),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", port=3333, session=session)
        response = await wled._request("/")
        assert response == "OMG PUPPIES!"


@pytest.mark.asyncio
async def test_request_base_path(aresponses):
    """Test WLED running on different base path."""
    aresponses.add(
        "example.com",
        "/admin/status",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=200),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", base_path="/admin", session=session)
        response = await wled._request("status")
        assert response == "OMG PUPPIES!"


@pytest.mark.asyncio
async def test_request_user_agent(aresponses):
    """Test WLED client sending correct user agent headers."""
    # Handle to run asserts on request in
    async def response_handler(request):
        assert request.headers["User-Agent"] == f"PythonWLED/{__version__}"
        return aresponses.Response(text="TEDDYBEAR", status=200)

    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", base_path="/", session=session)
        await wled._request("/")


@pytest.mark.asyncio
async def test_request_custom_user_agent(aresponses):
    """Test WLED client sending correct user agent headers."""
    # Handle to run asserts on request in
    async def response_handler(request):
        assert request.headers["User-Agent"] == "LoremIpsum/1.0"
        return aresponses.Response(text="TEDDYBEAR", status=200)

    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession() as session:
        wled = WLED(
            "example.com",
            base_path="/",
            session=session,
            user_agent="LoremIpsum/1.0",
        )
        await wled._request("/")


@pytest.mark.asyncio
async def test_backoff(aresponses):
    """Test requests are handled with retries."""

    async def response_handler(_):
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
        response = await wled._request("/")
        assert response == "OK"


@pytest.mark.asyncio
async def test_timeout(aresponses):
    """Test request timeout from WLED."""
    # Faking a timeout by sleeping
    async def response_handler(_):
        await asyncio.sleep(0.2)
        return aresponses.Response(body="Goodmorning!")

    # Backoff will try 3 times
    aresponses.add("example.com", "/", "GET", response_handler)
    aresponses.add("example.com", "/", "GET", response_handler)
    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session, request_timeout=0.1)
        with pytest.raises(WLEDConnectionError):
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_http_error400(aresponses):
    """Test HTTP 404 response handling."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(text="OMG PUPPIES!", status=404)
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        with pytest.raises(WLEDError):
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_http_error500(aresponses):
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
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_state_on(aresponses):
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
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
async def test_state_on_si_request(aresponses):
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
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
async def test_empty_responses(aresponses):
    """Test empty responses for WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
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
async def test_empty_si_responses(aresponses):
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
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
async def test_empty_full_responses(aresponses):
    """Test failure handling of full data request WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text="{}",
        ),
    )
    aresponses.add(
        "example.com",
        "/json/",
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
async def test_si_request_version_based(aresponses):
    """Test for supporting SI requests based on version data."""
    aresponses.add(
        "example.com",
        "/json/",
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
        assert wled._supports_si_request


@pytest.mark.asyncio
async def test_not_supporting_si_request_version_based(aresponses):
    """Test for supporting SI requests based on version data."""
    aresponses.add(
        "example.com",
        "/json/",
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
        assert not wled._supports_si_request


@pytest.mark.asyncio
async def test_si_request_probing_based(aresponses):
    """Test for supporting SI requests based on probing."""
    aresponses.add(
        "example.com",
        "/json/",
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
        assert wled._supports_si_request


@pytest.mark.asyncio
async def test_not_supporting_si_request_probing_based(aresponses):
    """Test for supporting SI requests based on probing."""
    aresponses.add(
        "example.com",
        "/json/",
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
        assert not wled._supports_si_request


@pytest.mark.asyncio
async def test_raw_request(aresponses):
    """Test for raw requests to WLED."""
    aresponses.add(
        "example.com", "/json/state", "POST", aresponses.Response(status=200, text="OK")
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.raw({"raw": "test"})
