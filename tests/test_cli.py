"""Tests for the WLED CLI module and AsyncTyper."""

# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from typer import Exit
from typer.main import get_command
from typer.testing import CliRunner

from wled import Device, Releases
from wled.cli import cli
from wled.cli.async_typer import AsyncTyper
from wled.exceptions import WLEDConnectionError, WLEDUnsupportedVersionError

from .conftest import full_device_data

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic Rich rendering for stable snapshots."""
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for invoking the Typer app."""
    return CliRunner()


def _device() -> Device:
    """Return a Device object constructed from test fixtures."""
    return Device.from_dict(full_device_data())


def _device_no_presets() -> Device:
    """Return a Device with empty presets and playlists."""
    data = full_device_data()
    data["presets"] = {"0": {}}
    return Device.from_dict(data)


def _device_no_wifi() -> Device:
    """Return a Device without Wi-Fi info."""
    data = full_device_data()
    data["info"]["wifi"] = None
    return Device.from_dict(data)


def _device_websocket_none() -> Device:
    """Return a Device with websocket disabled (ws: -1)."""
    data = full_device_data()
    data["info"]["ws"] = -1
    return Device.from_dict(data)


def _mock_wled(device: Device) -> MagicMock:
    """Create a mock WLED that returns the given device."""
    instance = AsyncMock()
    instance.__aenter__.return_value = instance
    instance.__aexit__.return_value = None
    instance.update.return_value = device
    return MagicMock(return_value=instance)


def _mock_releases(*, stable: str = "0.14.0", beta: str = "0.15.0b1") -> MagicMock:
    """Create a mock WLEDReleases that returns the given versions."""
    releases = Releases.from_dict({"stable": stable, "beta": beta})
    instance = AsyncMock()
    instance.__aenter__.return_value = instance
    instance.__aexit__.return_value = None
    instance.releases.return_value = releases
    return MagicMock(return_value=instance)


def _invoke(
    runner: CliRunner,
    args: list[str],
    device: Device | None = None,
) -> tuple[int, str]:
    """Invoke a WLED CLI command with a mocked WLED client."""
    mock = _mock_wled(device or _device())
    with patch("wled.cli.WLED", mock):
        result = runner.invoke(cli, args)
    return result.exit_code, result.output


# ---------------------------------------------------------------------------
# AsyncTyper unit tests
# ---------------------------------------------------------------------------


def test_async_typer_command_wraps_async() -> None:
    """Test that AsyncTyper wraps async command functions for sync execution."""
    app = AsyncTyper()

    @app.command("greet")
    async def greet() -> None:
        pass

    assert asyncio.iscoroutinefunction(greet)


def test_async_typer_command_wraps_sync() -> None:
    """Test that AsyncTyper passes through sync command functions."""
    app = AsyncTyper()

    @app.command("greet")  # ty: ignore[invalid-argument-type]
    def greet() -> None:
        pass

    assert not asyncio.iscoroutinefunction(greet)


def test_async_typer_callback_wraps_async() -> None:
    """Test that AsyncTyper wraps async callback functions."""
    app = AsyncTyper()

    @app.callback()
    async def main() -> None:
        pass

    assert asyncio.iscoroutinefunction(main)


def test_async_typer_callback_wraps_sync() -> None:
    """Test that AsyncTyper passes through sync callback functions."""
    app = AsyncTyper()

    @app.callback()  # ty: ignore[invalid-argument-type]
    def main() -> None:
        pass

    assert not asyncio.iscoroutinefunction(main)


def test_async_typer_error_handler_registered() -> None:
    """Test that error handlers are registered correctly."""
    app = AsyncTyper()

    @app.error_handler(ValueError)
    def handle_value_error(_: ValueError) -> None:
        pass

    assert ValueError in app.error_handlers  # pylint: disable=protected-access


def test_async_typer_error_handler_called() -> None:
    """Test that registered error handler is called on matching exception."""
    app = AsyncTyper(add_completion=False)
    handler_called = False

    @app.error_handler(RuntimeError)
    def handle_runtime(_: RuntimeError) -> None:
        nonlocal handler_called
        handler_called = True

    @app.command()  # ty: ignore[invalid-argument-type]
    def fail() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    # CliRunner bypasses __call__, so invoke directly
    app([], standalone_mode=False)
    assert handler_called


def test_async_typer_unhandled_exception_re_raises() -> None:
    """Test that unhandled exceptions are re-raised."""
    app = AsyncTyper(add_completion=False)

    @app.command()  # ty: ignore[invalid-argument-type]
    def fail() -> None:
        msg = "unhandled"
        raise TypeError(msg)

    result = CliRunner().invoke(app, [])
    assert result.exit_code != 0


def test_async_typer_exit_re_raises() -> None:
    """Test that typer.Exit is re-raised, not caught by error handlers."""
    app = AsyncTyper(add_completion=False)

    @app.error_handler(Exception)
    def catch_all(_: Exception) -> None:
        pass

    @app.command()  # ty: ignore[invalid-argument-type]
    def quit_cmd() -> None:
        raise Exit(code=42)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 42


def test_async_typer_no_error_handlers_attr() -> None:
    """Test that __call__ works when error_handlers hasn't been initialized."""
    app = AsyncTyper(add_completion=False)

    @app.command()  # ty: ignore[invalid-argument-type]
    def ok() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    result = CliRunner().invoke(app, [])
    assert result.exit_code != 0


def test_async_typer_call_normal() -> None:
    """Test normal delegation through __call__."""
    app = AsyncTyper(add_completion=False)

    @app.command()  # ty: ignore[invalid-argument-type]
    def hello() -> None:
        pass

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# CLI structure test
# ---------------------------------------------------------------------------


def test_cli_structure(snapshot: SnapshotAssertion) -> None:
    """The CLI exposes the expected commands and options."""
    group = get_command(cli)
    assert isinstance(group, click.Group)
    structure = {
        name: sorted(param.name for param in subcommand.params)
        for name, subcommand in sorted(group.commands.items())
    }
    assert structure == snapshot


# ---------------------------------------------------------------------------
# CLI command tests (snapshot output)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stable_terminal")
def test_info_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Info command prints device information table."""
    exit_code, output = _invoke(runner, ["info", "--host", "example.com"])
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_info_command_no_wifi(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Info command handles device without Wi-Fi."""
    exit_code, output = _invoke(
        runner, ["info", "--host", "example.com"], _device_no_wifi()
    )
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_info_command_websocket_none(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Info command shows 'Disabled' for websocket=None."""
    exit_code, output = _invoke(
        runner, ["info", "--host", "example.com"], _device_websocket_none()
    )
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_effects_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Effects command prints effects table."""
    exit_code, output = _invoke(runner, ["effects", "--host", "example.com"])
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_palettes_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Palettes command prints palettes table."""
    exit_code, output = _invoke(runner, ["palettes", "--host", "example.com"])
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_playlists_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Playlists command prints playlists table."""
    exit_code, output = _invoke(runner, ["playlists", "--host", "example.com"])
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_playlists_command_empty(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Playlists command handles no playlists."""
    exit_code, output = _invoke(
        runner, ["playlists", "--host", "example.com"], _device_no_presets()
    )
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_presets_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Presets command prints presets table."""
    exit_code, output = _invoke(runner, ["presets", "--host", "example.com"])
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_presets_command_empty(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Presets command handles no presets."""
    exit_code, output = _invoke(
        runner, ["presets", "--host", "example.com"], _device_no_presets()
    )
    assert exit_code == 0
    assert output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_releases_command(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Releases command prints release information."""
    mock = _mock_releases()
    with patch("wled.cli.WLEDReleases", mock):
        result = runner.invoke(cli, ["releases"])
    assert result.exit_code == 0
    assert result.output == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_scan_command_keyboard_interrupt(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Scan command handles KeyboardInterrupt gracefully."""
    mock_zeroconf = AsyncMock()
    mock_zeroconf.zeroconf = MagicMock()

    mock_browser = AsyncMock()

    # Make Event.wait() raise KeyboardInterrupt immediately
    mock_event = MagicMock()
    mock_event.wait = AsyncMock(side_effect=KeyboardInterrupt)

    with (
        patch("wled.cli.AsyncZeroconf", return_value=mock_zeroconf),
        patch("wled.cli.AsyncServiceBrowser", return_value=mock_browser),
        patch("asyncio.Event", return_value=mock_event),
    ):
        result = runner.invoke(cli, ["scan"])

    assert result.exit_code == 0
    assert result.output == snapshot


# ---------------------------------------------------------------------------
# Error handler tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stable_terminal")
def test_connection_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Connection error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[WLEDConnectionError]  # pylint: disable=protected-access
    with pytest.raises(SystemExit) as exc_info:
        handler(WLEDConnectionError("fail"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


@pytest.mark.usefixtures("stable_terminal")
def test_unsupported_version_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Unsupported version error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[WLEDUnsupportedVersionError]  # pylint: disable=protected-access
    with pytest.raises(SystemExit) as exc_info:
        handler(WLEDUnsupportedVersionError("old"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot
