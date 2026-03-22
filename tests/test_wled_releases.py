"""Tests for `wled.WLEDReleases`."""

from __future__ import annotations

from typing import Any

import aiohttp
import orjson
import pytest
from aresponses import ResponsesMockServer

from wled import WLEDReleases
from wled.exceptions import WLEDError

GITHUB_HOST = "api.github.com"
GITHUB_PATH = "/repos/Aircoookie/WLED/releases"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("releases_data", "expected_stable", "expected_beta"),
    [
        pytest.param(
            [
                {"tag_name": "v0.15.0", "prerelease": False},
                {"tag_name": "v0.15.0-b3", "prerelease": True},
                {"tag_name": "v0.14.4", "prerelease": False},
            ],
            "0.15.0",
            "0.15.0-b3",
            id="stable_and_beta",
        ),
        pytest.param(
            [
                {"tag_name": "v0.15.0", "prerelease": False},
                {"tag_name": "v0.14.4", "prerelease": False},
            ],
            "0.15.0",
            None,
            id="stable_only",
        ),
        pytest.param(
            [
                {"tag_name": "v0.15.0-b3", "prerelease": True},
            ],
            None,
            "0.15.0-b3",
            id="beta_only",
        ),
    ],
)
async def test_releases(
    aresponses: ResponsesMockServer,
    releases_data: list[dict[str, Any]],
    expected_stable: str | None,
    expected_beta: str | None,
) -> None:
    """Test that stable and beta versions are correctly parsed."""
    aresponses.add(
        GITHUB_HOST,
        GITHUB_PATH,
        "GET",
        aresponses.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=orjson.dumps(releases_data).decode(),
        ),
    )
    async with aiohttp.ClientSession() as session:
        client = WLEDReleases(session=session)
        releases = await client.releases()
        assert releases.stable == expected_stable
        assert releases.beta == expected_beta


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 429, 500])
async def test_releases_http_error(
    aresponses: ResponsesMockServer,
    status_code: int,
) -> None:
    """Test that WLEDError is raised on HTTP error responses from GitHub."""
    aresponses.add(
        GITHUB_HOST,
        GITHUB_PATH,
        "GET",
        aresponses.Response(
            status=status_code,
            headers={"Content-Type": "application/json"},
            text='{"message": "error"}',
        ),
    )
    async with aiohttp.ClientSession() as session:
        client = WLEDReleases(session=session)
        with pytest.raises(WLEDError):
            await client.releases()
