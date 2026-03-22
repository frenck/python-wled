"""Test configuration and shared fixtures for python-wled."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson
import pytest
from aresponses import ResponsesMockServer


def load_fixture(filename: str) -> Any:
    """Load a JSON fixture file from tests/fixtures/."""
    path = Path(__file__).parent / "fixtures" / filename
    return orjson.loads(path.read_bytes())


@pytest.fixture
def device_fixture(aresponses: ResponsesMockServer) -> None:
    """Add /json and /presets.json fixture responses to aresponses."""
    aresponses.add(
        "example.com",
        "/json",
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=orjson.dumps(load_fixture("get_json.json")).decode(),
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
