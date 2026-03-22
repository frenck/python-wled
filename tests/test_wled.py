"""Tests for `wled.WLED`."""

import asyncio
from typing import Any

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from wled import WLED
from wled.exceptions import WLEDConnectionError, WLEDError
from wled.models import Device


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
        "example.com",
        "/",
        "GET",
        aresponses.Response(status=200, text="OK"),
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
        "example.com",
        "/",
        "POST",
        aresponses.Response(status=200, text="OK"),
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
        "example.com",
        "/",
        "GET",
        aresponses.Response(status=200, text="OK"),
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
        "example.com",
        "/",
        "GET",
        aresponses.Response(text="OMG PUPPIES!", status=404),
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
@pytest.mark.usefixtures("device_fixture")
async def test_update_returns_device() -> None:
    """Test that update() fetches device data and returns a Device object."""
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        device = await wled.update()
        assert isinstance(device, Device)
        assert device.info.name == "WLED ID-10"
        assert len(device.effects) == 187


@pytest.mark.asyncio
async def test_master_turn_on(aresponses: ResponsesMockServer) -> None:
    """Test that master(on=True) sends the correct JSON payload."""
    captured: dict[str, Any] = {}

    async def capture_handler(request: aiohttp.web.BaseRequest) -> Response:
        captured["data"] = await request.json()
        return aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"on": true}',
        )

    aresponses.add("example.com", "/json/state", "POST", capture_handler)
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.master(on=True)
        assert captured["data"]["on"] is True


@pytest.mark.asyncio
async def test_master_brightness(aresponses: ResponsesMockServer) -> None:
    """Test that master(brightness=128) sends the correct JSON payload."""
    captured: dict[str, Any] = {}

    async def capture_handler(request: aiohttp.web.BaseRequest) -> Response:
        captured["data"] = await request.json()
        return aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"bri": 128}',
        )

    aresponses.add("example.com", "/json/state", "POST", capture_handler)
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.master(brightness=128)
        assert captured["data"]["bri"] == 128


@pytest.mark.asyncio
async def test_master_with_transition(aresponses: ResponsesMockServer) -> None:
    """Test that master() with all params sends the correct JSON payload."""
    captured: dict[str, Any] = {}

    async def capture_handler(request: aiohttp.web.BaseRequest) -> Response:
        captured["data"] = await request.json()
        return aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"on": true, "bri": 255, "tt": 4}',
        )

    aresponses.add("example.com", "/json/state", "POST", capture_handler)
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        await wled.master(on=True, brightness=255, transition=4)
        assert captured["data"]["on"] is True
        assert captured["data"]["bri"] == 255
        assert captured["data"]["tt"] == 4
