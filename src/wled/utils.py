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


def _internal_cct_blend(cct_blend: int) -> int:
    """Return WLED's internal CCT blend (-127 to 127) for a blend in percent."""
    cct_blend = max(-100, min(100, cct_blend))
    return int((cct_blend * 127 + (50 if cct_blend >= 0 else -50)) / 100)


def split_white(white: int, cct: int, *, cct_blend: int) -> tuple[int, int]:
    """Return how WLED splits a white value over warm and cold white.

    The same calculation as WLED's own (Bus::calculateCCT in WLED 16.0),
    for LEDs with separate warm and cold white channels.

    Args:
    ----
        white: The white value, between 0 and 255.
        cct: The color temperature, between 0 (warm) and 255 (cold).
        cct_blend: How warm and cold white blend, in percent, as the
            LED configuration of the device has it.

    Returns:
    -------
        The warm and cold white values, between 0 and 255.

    """
    blend = _internal_cct_blend(cct_blend)
    if blend < 0:
        # Exclusive: one white at each end, blending only in the middle.
        # The blend is at least -127, so this width is at least 1.
        width = 255 - 2 * -blend
        warm = int((255 + blend - cct) * 255 / width)
        cold = 255 - warm
    elif blend:
        # Additive: both whites towards the middle.
        warm = int((255 - cct) * 255 / (255 - blend))
        cold = int(cct * 255 / (255 - blend))
    else:
        warm = 255 - cct
        cold = cct

    warm = max(0, min(255, warm))
    cold = max(0, min(255, cold))
    return white * warm // 255, white * cold // 255


def combine_white(warm: int, cold: int, *, cct_blend: int) -> tuple[int, int]:
    """Return the white value and color temperature closest to warm and cold white.

    The reverse of `split_white()`: what to send WLED for the given warm and
    cold white. Not every combination can be made exactly; this returns the
    closest one. Without any white, the color temperature doesn't matter,
    and is returned as the middle (127).

    Args:
    ----
        warm: The warm white value, between 0 and 255.
        cold: The cold white value, between 0 and 255.
        cct_blend: How warm and cold white blend, in percent, as the
            LED configuration of the device has it.

    Returns:
    -------
        The white value and the color temperature, both between 0 and 255.

    """
    if not warm and not cold:
        return 0, 127

    best: tuple[int, int, int] | None = None
    for cct in range(256):
        full_warm, full_cold = split_white(255, cct, cct_blend=cct_blend)
        # The white value that gives the brightest of the two whites.
        white = max(
            round(warm * 255 / full_warm) if full_warm else 0,
            round(cold * 255 / full_cold) if full_cold else 0,
        )
        white = min(white, 255)
        got_warm, got_cold = split_white(white, cct, cct_blend=cct_blend)
        error = abs(got_warm - warm) + abs(got_cold - cold)
        if best is None or error < best[0]:
            best = (error, white, cct)

    assert best is not None  # noqa: S101
    return best[1], best[2]
