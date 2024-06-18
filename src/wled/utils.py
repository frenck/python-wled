"""Asynchronous Python client for WLED."""

from functools import lru_cache

from awesomeversion import AwesomeVersion


@lru_cache
def get_awesome_version(version: str) -> AwesomeVersion:
    """Return a cached AwesomeVersion object."""
    return AwesomeVersion(version)
