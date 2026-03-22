"""Tests for `wled.models` — verified through the /json and /presets.json endpoints."""

from __future__ import annotations

from datetime import timedelta

import aiohttp
import orjson
import pytest
from aresponses import ResponsesMockServer

from wled import WLED
from wled.const import NightlightMode
from wled.exceptions import WLEDUnsupportedVersionError

from .conftest import load_fixture


@pytest.mark.asyncio
@pytest.mark.usefixtures("device_fixture")
async def test_device_info() -> None:
    """Test that device info fields are correctly parsed from /json."""
    async with aiohttp.ClientSession() as session:
        device = await WLED("example.com", session=session).update()
        assert device.info.name == "WLED ID-10"
        assert device.info.architecture == "esp32"
        assert str(device.info.version) == "0.15.3"
        assert device.info.ip == "10.10.10.137"
        assert len(device.effects) == 187
        assert len(device.palettes) == 71


@pytest.mark.asyncio
@pytest.mark.usefixtures("device_fixture")
async def test_device_uptime() -> None:
    """Test that uptime is deserialized as timedelta."""
    async with aiohttp.ClientSession() as session:
        device = await WLED("example.com", session=session).update()
        assert isinstance(device.info.uptime, timedelta)
        assert device.info.uptime == timedelta(seconds=2490989)


@pytest.mark.asyncio
@pytest.mark.usefixtures("device_fixture")
async def test_device_segments() -> None:
    """Test that segment data is fully parsed from /json."""
    async with aiohttp.ClientSession() as session:
        device = await WLED("example.com", session=session).update()
        assert len(device.state.segments) == 2
        seg = device.state.segments[0]
        assert seg.segment_id == 0
        assert seg.start == 0
        assert seg.stop == 29
        assert seg.color is not None
        assert seg.color.primary == [100, 100, 255, 0]
        assert seg.selected is True
        assert seg.reverse is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("device_fixture")
async def test_device_nightlight() -> None:
    """Test that nightlight mode enum and duration are correctly parsed."""
    async with aiohttp.ClientSession() as session:
        device = await WLED("example.com", session=session).update()
        assert device.state.nightlight.mode == NightlightMode.FADE
        assert device.state.nightlight.duration == 60


@pytest.mark.asyncio
@pytest.mark.usefixtures("device_fixture")
async def test_device_presets() -> None:
    """Test that presets are parsed from /presets.json into a keyed dict."""
    async with aiohttp.ClientSession() as session:
        device = await WLED("example.com", session=session).update()
        assert 1 in device.presets
        assert device.presets[1].name == "Solid"
        # Preset 0 is a placeholder and is always dropped
        assert 0 not in device.presets


@pytest.mark.asyncio
async def test_unsupported_version(aresponses: ResponsesMockServer) -> None:
    """Test that WLEDUnsupportedVersionError is raised for firmware < 0.14.0."""
    data = load_fixture("get_json.json")
    data["info"]["ver"] = "0.13.0"
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=orjson.dumps(data).decode(),
        ),
    )
    aresponses.add(
        "example.com",
        "/presets.json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=orjson.dumps(load_fixture("get_presets.json")).decode(),
        ),
    )
    async with aiohttp.ClientSession() as session:
        with pytest.raises(WLEDUnsupportedVersionError):
            await WLED("example.com", session=session).update()
