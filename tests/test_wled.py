"""Tests for `wled.WLED`."""

import asyncio
import string

import aiohttp
import pytest
from aresponses import Response, ResponsesMockServer

from wled import WLED
from wled.exceptions import WLEDConnectionError, WLEDError


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
async def test_presets_cache(aresponses: ResponsesMockServer) -> None:
    """Test presets is fetched only when needed."""

    def make_json(uptime: int, time: str, pmt: int) -> str:
        return string.Template(
            """
            {"info": {"uptime":$uptime,"time":"$time","fs":{"pmt": $pmt}},
            "state":{"bri":127,"on":true,"transition":7,"ps":-1,"pl":-1,
            "nl":{"on":false,"dur":60,"mode":1,"tbri":0,"rem":-1},
            "udpn":{"send":false,"recv":true,"sgrp":1,"rgrp":1},"lor":0,
            "seg":[{"id":0,"start":0,"stop":48,"startY":0,"stopY":19,"len":48,
            "grp":1,"spc":0,"of":0,"on":true,"frz":false,"bri":255,"cct":127,
            "set":0,"lc":1,"col":[[18,22,255],[0,0,0],[0,0,0]],"fx":174,"sx":0,
            "ix":91,"pal":0,"c1":128,"c2":128,"c3":16,"sel":true,"rev":false,
            "mi":false,"rY":false,"mY":false,"tp":false,"o1":false,"o2":false,
            "o3":false,"si":0,"m12":0,"bm":0}]}}
            """
        ).substitute({"uptime": uptime, "time": time, "pmt": pmt})

    # First poll
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=make_json(uptime=17836, time="2026-1-4, 18:32:43", pmt=1767549790),
        ),
    )
    aresponses.add(
        "example.com",
        "/presets.json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"0": {}, "1": {"n": "My Preset" }}',
        ),
    )

    # Second poll, timestamp doesn't change, no fetching
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=make_json(uptime=17836, time="2026-1-4, 18:32:43", pmt=1767549790),
        ),
    )

    # Third poll, user renames a preset, timestamp changes
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=make_json(uptime=17836, time="2026-1-4, 18:32:43", pmt=1767554102),
        ),
    )
    aresponses.add(
        "example.com",
        "/presets.json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"0": {}, "1": {"n": "My New Preset" }}',
        ),
    )

    # Fourth poll, timestamp doesn't change, no fetching
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=make_json(uptime=17836, time="2026-1-4, 18:32:43", pmt=1767554102),
        ),
    )

    # Fifth poll, wled restart
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=make_json(uptime=3, time="2026-1-4, 21:16:51", pmt=0),
        ),
    )
    aresponses.add(
        "example.com",
        "/presets.json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text='{"0": {}, "1": {"n": "My New Preset" }}',
        ),
    )

    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        response = await wled.update()
        assert response.presets[1].name == "My Preset"

        response = await wled.update()
        assert response.presets[1].name == "My Preset"

        response = await wled.update()
        assert response.presets[1].name == "My New Preset"

        response = await wled.update()
        assert response.presets[1].name == "My New Preset"

        response = await wled.update()
        assert response.presets[1].name == "My New Preset"
    aresponses.assert_plan_strictly_followed()
