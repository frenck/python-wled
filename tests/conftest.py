"""Common fixtures and helpers for WLED tests."""

import json
from collections.abc import AsyncGenerator, Callable, Generator
from pathlib import Path
from typing import Any

import aiohttp
import pytest
import pytest_asyncio
from aioresponses import aioresponses

from wled import WLED

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FixtureLoader = Callable[[str], Any]


def load_fixture_json(name: str) -> Any:
    """Load a JSON fixture file by name (without extension)."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def full_device_data() -> dict[str, Any]:
    """Return complete device data with presets merged in."""
    data = load_fixture_json("wled")
    data["presets"] = load_fixture_json("presets")
    return data


def mock_json_and_presets(
    mocked: aioresponses,
    wled_data: dict[str, Any] | None = None,
    presets_data: dict[str, Any] | None = None,
) -> None:
    """Register the two GET endpoints that WLED.update() calls."""
    if wled_data is None:
        wled_data = load_fixture_json("wled")
    mocked.get(
        "http://example.com/json",
        status=200,
        body=json.dumps(wled_data),
        content_type="application/json",
    )
    if presets_data is None:
        presets_data = load_fixture_json("presets")
    mocked.get(
        "http://example.com/presets.json",
        status=200,
        body=json.dumps(presets_data),
        content_type="application/json",
    )


@pytest.fixture
def load_fixture() -> FixtureLoader:
    """Return a helper that loads a JSON fixture by name."""
    return load_fixture_json


@pytest.fixture
def responses() -> Generator[aioresponses, None, None]:
    """Yield an aioresponses instance that patches aiohttp client sessions."""
    with aioresponses() as mocker:
        yield mocker


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession, None]:
    """Yield a new aiohttp client session."""
    async with aiohttp.ClientSession() as aio_session:
        yield aio_session


@pytest_asyncio.fixture
async def wled() -> AsyncGenerator[WLED, None]:
    """Yield a WLED client wired to example.com with default settings."""
    wled_instance = WLED("example.com")
    yield wled_instance
    await wled_instance.close()
