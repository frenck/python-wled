"""Asynchronous Python client for WLED."""

import re
from functools import lru_cache

from awesomeversion import AwesomeVersion

# A plain "owner/name" pair, as GitHub names repositories. Deliberately a bit
# looser than GitHub's own rules: the point is keeping slashes, dot segments,
# and URL syntax out of the download URL, not policing names.
_GITHUB_REPO = re.compile(r"[A-Za-z0-9][\w-]{0,38}/(?!\.\.?$)[\w.-]{1,100}", re.ASCII)


def is_github_repo(value: str) -> bool:
    """Return whether a value is a plain GitHub "owner/name" pair."""
    return _GITHUB_REPO.fullmatch(value) is not None


@lru_cache
def get_awesome_version(version: str) -> AwesomeVersion:
    """Return a cached AwesomeVersion object."""
    return AwesomeVersion(version)
