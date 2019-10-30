"""Tests for `wled.WLED`."""
import asyncio

import aiohttp
import pytest
from wled import WLED
from wled.__version__ import __version__
from wled.exceptions import WLEDConnectionError, WLEDError


@pytest.mark.asyncio
async def test_json_request(event_loop, aresponses):
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
    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_authenticated_request(event_loop, aresponses):
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
    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED(
            "example.com",
            username="frenck",
            password="zerocool",
            session=session,
            loop=event_loop,
        )
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_text_request(event_loop, aresponses):
    """Test non JSON response is handled correctly."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        response = await wled._request("/")
        assert response == "OK"


@pytest.mark.asyncio
async def test_internal_session(event_loop, aresponses):
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
    async with WLED("example.com", loop=event_loop) as wled:
        response = await wled._request("/")
        assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_internal_eventloop(aresponses):
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
async def test_post_request(event_loop, aresponses):
    """Test POST requests are handled correctly."""
    aresponses.add(
        "example.com", "/", "POST", aresponses.Response(status=200, text="OK")
    )
    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        response = await wled._request("/", method="POST")
        assert response == "OK"


@pytest.mark.asyncio
async def test_request_port(event_loop, aresponses):
    """Test WLED running on non-standard port."""
    aresponses.add(
        "example.com:3333",
        "/",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=200),
    )

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", port=3333, session=session, loop=event_loop)
        response = await wled._request("/")
        assert response == "OMG PUPPIES!"


@pytest.mark.asyncio
async def test_request_base_path(event_loop, aresponses):
    """Test WLED running on different base path."""
    aresponses.add(
        "example.com",
        "/admin/status",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=200),
    )

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", base_path="/admin", session=session, loop=event_loop)
        response = await wled._request("status")
        assert response == "OMG PUPPIES!"


@pytest.mark.asyncio
async def test_request_user_agent(event_loop, aresponses):
    """Test WLED client sending correct user agent headers."""
    # Handle to run asserts on request in
    async def response_handler(request):
        assert request.headers["User-Agent"] == f"PythonWLED/{__version__}"
        return aresponses.Response(text="TEDDYBEAR", status=200)

    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", base_path="/", session=session, loop=event_loop)
        await wled._request("/")


@pytest.mark.asyncio
async def test_request_custom_user_agent(event_loop, aresponses):
    """Test WLED client sending correct user agent headers."""
    # Handle to run asserts on request in
    async def response_handler(request):
        assert request.headers["User-Agent"] == "LoremIpsum/1.0"
        return aresponses.Response(text="TEDDYBEAR", status=200)

    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED(
            "example.com",
            base_path="/",
            session=session,
            loop=event_loop,
            user_agent="LoremIpsum/1.0",
        )
        await wled._request("/")


@pytest.mark.asyncio
async def test_timeout(event_loop, aresponses):
    """Test request timeout from WLED."""
    # Faking a timeout by sleeping
    async def response_handler(_):
        await asyncio.sleep(2)
        return aresponses.Response(body="Goodmorning!")

    aresponses.add("example.com", "/", "GET", response_handler)

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop, request_timeout=1)
        with pytest.raises(WLEDConnectionError):
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_http_error400(event_loop, aresponses):
    """Test HTTP 404 response handling."""
    aresponses.add(
        "example.com", "/", "GET", aresponses.Response(text="OMG PUPPIES!", status=404)
    )

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        with pytest.raises(WLEDError):
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_http_error500(event_loop, aresponses):
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

    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        with pytest.raises(WLEDError):
            assert await wled._request("/")


@pytest.mark.asyncio
async def test_state_on(event_loop, aresponses):
    """Test request of current WLED device state."""
    aresponses.add(
        "example.com",
        "/json/",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"state": {"on": true}}',
        ),
    )
    aresponses.add(
        "example.com",
        "/json/",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"state": {"on": false}}',
        ),
    )
    async with aiohttp.ClientSession(loop=event_loop) as session:
        wled = WLED("example.com", session=session, loop=event_loop)
        device = await wled.update()
        assert device.state.on
        device = await wled.update()
        assert not device.state.on
