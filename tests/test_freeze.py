"""Tests for WLED models with and without the freeze property applied."""
import json
import aiohttp
import pytest
from pathlib import Path

from wled.models import State, Device
from wled import WLED
from aresponses import ResponsesMockServer


FIXTURE_DIR = Path(__file__).parent / "fixtures"

def load_fixture(file_name: str) -> dict:
    """Load a fixture file from the fixtures directory."""
    fixture_path = FIXTURE_DIR / file_name
    return json.loads(fixture_path.read_text())

def test_read_freeze_state() -> None:
    """Test frozen segment is parsed correctly."""
    data = load_fixture("test_device_data.json")

    model_instance = State.from_dict(data["state"])

    assert model_instance.segments[0].freeze is True
    # assert explicit frz: false
    assert model_instance.segments[1].freeze is False
    # assert default freeze=false from models.py
    assert model_instance.segments[2].freeze is False
    assert model_instance.segments[3].freeze is False

@pytest.mark.asyncio
async def test_write_freeze_state(mocker, aresponses: ResponsesMockServer) -> None:
    """Test WLED.segment sends correct freeze payload"""
    data = load_fixture("test_device_data.json")
    aresponses.add(
        "example.com",
        "/json/state",
        "POST",
        aresponses.Response(status=200, text="OK"),
    )
    async with aiohttp.ClientSession() as session:
        wled = WLED("example.com", session=session)
        request_spy = mocker.spy(wled, 'request')

        wled._device = Device.from_dict(data)
        response = await wled.segment(0, freeze=True)
        
        request_spy.assert_called_once()
        args, kwargs = request_spy.call_args
        assert isinstance(kwargs["data"]["seg"][0]["frz"], bool)
        assert kwargs["data"]["seg"][0]["frz"] is True
        assert response is None
