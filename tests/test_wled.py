"""Tests for `wled.WLED`."""

import aiohttp
import pytest
from aioresponses import aioresponses

from wled import WLED
from wled.exceptions import WLEDConnectionError, WLEDError


@pytest.mark.asyncio
async def test_json_request() -> None:
    """Test JSON response is handled correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/")
            assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_text_request() -> None:
    """Test non-JSON response is handled correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/")
            assert response == "OK"


@pytest.mark.asyncio
async def test_internal_session() -> None:
    """Test internal session is created and works correctly."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=200,
            body='{"status": "ok"}',
            content_type="application/json",
        )
        async with WLED("example.com") as wled:
            response = await wled.request("/")
            assert response["status"] == "ok"


@pytest.mark.asyncio
async def test_post_request() -> None:
    """Test POST requests are handled correctly."""
    with aioresponses() as mocked:
        mocked.post(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            response = await wled.request("/", method="POST")
            assert response == "OK"


@pytest.mark.asyncio
async def test_backoff() -> None:
    """Test requests are handled with retries."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            status=200,
            body="OK",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session, request_timeout=0.1)
            response = await wled.request("/")
            assert response == "OK"


@pytest.mark.asyncio
async def test_timeout() -> None:
    """Test request timeout from WLED."""
    with aioresponses() as mocked:
        # Backoff will try 3 times
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        mocked.get(
            "http://example.com/",
            exception=TimeoutError(),
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session, request_timeout=0.1)
            with pytest.raises(WLEDConnectionError):
                assert await wled.request("/")


@pytest.mark.asyncio
async def test_http_error404() -> None:
    """Test HTTP 404 response handling."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=404,
            body="OMG PUPPIES!",
            content_type="text/plain",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            with pytest.raises(WLEDError):
                assert await wled.request("/")


@pytest.mark.asyncio
async def test_http_error500() -> None:
    """Test HTTP 500 response handling."""
    with aioresponses() as mocked:
        mocked.get(
            "http://example.com/",
            status=500,
            body='{"status":"nok"}',
            content_type="application/json",
        )
        async with aiohttp.ClientSession() as session:
            wled = WLED("example.com", session=session)
            with pytest.raises(WLEDError):
                assert await wled.request("/")
