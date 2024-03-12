"""Tests for `wled.Device`."""

from __future__ import annotations

from typing import Any

import pytest

from wled import Device
from wled.exceptions import WLEDError


def test_init_valid_empty_dict() -> None:
    """Test device can be created from basic json."""
    testdata: dict[str, Any] = {"effects": [], "palettes": [], "info": {}, "state": {}}
    device = Device(testdata)
    assert device is not None
    assert isinstance(device, Device)


@pytest.mark.parametrize(
    "test_dict",
    [
        {},
        {"effects": None, "palettes": [], "info": {}, "state": {}},
        {"effects": [], "palettes": None, "info": {}, "state": {}},
        {"effects": [], "palettes": [], "info": None, "state": {}},
        {"effects": [], "palettes": [], "info": {}, "state": None},
        {"palettes": [], "info": {}, "state": {}},
        {"effects": [], "info": {}, "state": {}},
        {"effects": [], "palettes": [], "state": {}},
        {"effects": [], "palettes": [], "info": {}},
    ],
)
def test_init_faulty_dict(test_dict: dict[str, Any]) -> None:
    """Test construction properly errors out on missing or empty keys."""
    with pytest.raises(WLEDError, match=r"WLED data is incomplete.*"):
        Device(test_dict)
