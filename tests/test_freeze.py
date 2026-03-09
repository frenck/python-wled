"""Tests for WLED models with and without the freeze property applied."""
import json
from pathlib import Path

from wled.models import State

ROOT_DIR = Path(__file__).parent.parent
FIXTURE_DIR = ROOT_DIR / "tests" / "fixtures"

def load_fixture(file_name: str) -> dict:
    """Load a fixture file from the fixtures directory."""
    fixture_path = FIXTURE_DIR / file_name
    return json.loads(fixture_path.read_text())


def test_state_with_frozen_segment() -> None:
    """Test frozen segment is parsed correctly."""
    data = load_fixture("state_with_segment_and_freeze.json")
    model_instance = State.from_dict(data)

    assert model_instance.segments[0].freeze is True
    assert model_instance.segments[1].freeze is False