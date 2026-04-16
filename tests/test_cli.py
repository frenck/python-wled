"""Tests for the WLED CLI module and AsyncTyper."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from awesomeversion import AwesomeVersion
from typer import Exit
from typer.testing import CliRunner

from wled import Device, Releases
from wled.cli import cli
from wled.cli.async_typer import AsyncTyper
from wled.exceptions import WLEDConnectionError, WLEDUnsupportedVersionError

from .conftest import full_device_data

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wled_mock(device: Device) -> MagicMock:
    """Create a mock WLED instance that acts as an async context manager."""
    mock_instance = AsyncMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    mock_instance.update = AsyncMock(return_value=device)
    return MagicMock(return_value=mock_instance)


def _make_wled_error_mock(exc: Exception) -> MagicMock:
    """Create a mock WLED that raises an exception on update()."""
    mock_instance = AsyncMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    mock_instance.update = AsyncMock(side_effect=exc)
    return MagicMock(return_value=mock_instance)


def _device() -> Device:
    """Return a Device object constructed from test fixtures."""
    return Device.from_dict(full_device_data())


def _device_no_presets() -> Device:
    """Return a Device with empty presets and playlists."""
    data = full_device_data()
    data["presets"] = {"0": {}}
    return Device.from_dict(data)


# ---------------------------------------------------------------------------
# AsyncTyper unit tests
# ---------------------------------------------------------------------------


def test_async_typer_command_wraps_async() -> None:
    """AsyncTyper.command wraps an async function so typer can call it."""
    app = AsyncTyper()
    called = False

    # Need two commands so typer treats it as a group with subcommands
    @app.command("hello")
    async def hello_cmd() -> None:
        nonlocal called
        called = True

    @app.command("other")
    async def other_cmd() -> None:
        pass

    test_runner = CliRunner()
    result = test_runner.invoke(app, ["hello"])
    assert result.exit_code == 0
    assert called


def test_async_typer_command_wraps_sync() -> None:
    """AsyncTyper.command passes sync functions through unchanged."""
    app = AsyncTyper()
    called = False

    @app.command("sync-hello")  # ty: ignore[invalid-argument-type]
    def sync_hello_cmd() -> None:
        nonlocal called
        called = True

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    test_runner = CliRunner()
    result = test_runner.invoke(app, ["sync-hello"])
    assert result.exit_code == 0
    assert called


def test_async_typer_callback_wraps_async() -> None:
    """AsyncTyper.callback wraps an async callback."""
    app = AsyncTyper()
    called = False

    @app.callback(invoke_without_command=True)
    async def my_callback() -> None:
        nonlocal called
        called = True

    test_runner = CliRunner()
    result = test_runner.invoke(app, [])
    assert result.exit_code == 0
    assert called


def test_async_typer_callback_wraps_sync() -> None:
    """AsyncTyper.callback passes sync callbacks through."""
    app = AsyncTyper()
    called = False

    @app.callback(invoke_without_command=True)  # ty: ignore[invalid-argument-type]
    def my_sync_callback() -> None:
        nonlocal called
        called = True

    test_runner = CliRunner()
    result = test_runner.invoke(app, [])
    assert result.exit_code == 0
    assert called


def test_async_typer_error_handler_registered() -> None:
    """error_handler registers an exception handler on the app."""
    app = AsyncTyper()

    def handle_value_error(_: ValueError) -> None:
        pass

    app.error_handler(ValueError)(handle_value_error)

    assert ValueError in app.error_handlers
    assert app.error_handlers[ValueError] is handle_value_error


def test_async_typer_error_handler_called() -> None:
    """When a registered exception is raised, the handler is invoked."""
    app = AsyncTyper()
    handler_called = False

    @app.error_handler(RuntimeError)
    def handle_runtime(_: RuntimeError) -> None:
        nonlocal handler_called
        handler_called = True

    @app.command("fail")  # ty: ignore[invalid-argument-type]
    def fail_cmd() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    # CliRunner calls .main() which bypasses __call__, so call the app
    # directly via __call__ to exercise the error handler code path.
    app(["fail"], standalone_mode=False)
    assert handler_called


def test_async_typer_unhandled_exception_re_raises() -> None:
    """An exception without a handler is re-raised."""
    app = AsyncTyper()

    @app.command("fail")  # ty: ignore[invalid-argument-type]
    def fail_cmd() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    test_runner = CliRunner()
    result = test_runner.invoke(app, ["fail"])
    assert result.exit_code != 0


def test_async_typer_exit_re_raises() -> None:
    """Exit exceptions are re-raised, not caught by the error handler."""
    app = AsyncTyper()

    @app.error_handler(Exception)
    def handle_all(_: Exception) -> None:
        pass

    @app.command("exit-cmd")  # ty: ignore[invalid-argument-type]
    def exit_cmd() -> None:
        raise Exit(code=0)

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    test_runner = CliRunner()
    result = test_runner.invoke(app, ["exit-cmd"])
    assert result.exit_code == 0


def test_async_typer_no_error_handlers_attr() -> None:
    """When error_handlers has not been set, unhandled exceptions re-raise."""
    app = AsyncTyper()

    @app.command("fail")  # ty: ignore[invalid-argument-type]
    def fail_cmd() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    test_runner = CliRunner()
    result = test_runner.invoke(app, ["fail"])
    assert result.exit_code != 0


def test_async_typer_call_delegates_to_super() -> None:
    """__call__ delegates to Typer.__call__ when no exception occurs."""
    app = AsyncTyper()
    called = False

    @app.command("ok")  # ty: ignore[invalid-argument-type]
    def ok_cmd() -> None:
        nonlocal called
        called = True

    @app.command("other")  # ty: ignore[invalid-argument-type]
    def other_cmd() -> None:
        pass

    app(["ok"], standalone_mode=False)
    assert called


# ---------------------------------------------------------------------------
# CLI help / no-args
# ---------------------------------------------------------------------------


def test_cli_no_args_shows_help() -> None:
    """Running CLI without arguments shows help."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "WLED CLI" in result.output


def test_cli_help_lists_commands() -> None:
    """Running CLI with --help lists available commands."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "info" in result.output
    assert "effects" in result.output
    assert "scan" in result.output
    assert "releases" in result.output


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_info_command(mock_wled_cls: MagicMock) -> None:
    """The info command prints device information."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    assert "WLED device information" in result.output
    assert device.info.name in result.output
    assert str(device.info.version) in result.output
    assert device.info.mac_address in result.output
    assert device.info.architecture in result.output


@patch("wled.cli.WLED")
def test_info_command_shows_wifi(mock_wled_cls: MagicMock) -> None:
    """The info command includes Wi-Fi details when present."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    assert "Wi-Fi BSSID" in result.output
    assert "Wi-Fi channel" in result.output


@patch("wled.cli.WLED")
def test_info_command_no_wifi(mock_wled_cls: MagicMock) -> None:
    """The info command works when wifi info is None."""
    device = _device()
    device.info.wifi = None  # type: ignore[assignment]
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    assert "WLED device information" in result.output
    assert "Wi-Fi BSSID" not in result.output


@patch("wled.cli.WLED")
def test_info_websocket_none(mock_wled_cls: MagicMock) -> None:
    """Websocket is shown as Disabled when None."""
    device = _device()
    device.info.websocket = None  # type: ignore[assignment]
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    assert "Disabled" in result.output


@patch("wled.cli.WLED")
def test_info_websocket_clients(mock_wled_cls: MagicMock) -> None:
    """Websocket shows client count when present."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    assert "client(s)" in result.output


@patch("wled.cli.WLED")
def test_info_live_status(mock_wled_cls: MagicMock) -> None:
    """The info command shows live mode status."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])
    assert result.exit_code == 0
    # live is false in fixture
    assert "No" in result.output


# ---------------------------------------------------------------------------
# effects command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_effects_command(mock_wled_cls: MagicMock) -> None:
    """The effects command lists effects from the device."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["effects", "--host", "example.com"])
    assert result.exit_code == 0
    assert "Solid" in result.output
    assert "Blink" in result.output
    assert "Breathe" in result.output


# ---------------------------------------------------------------------------
# palettes command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_palettes_command(mock_wled_cls: MagicMock) -> None:
    """The palettes command lists palettes from the device."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["palettes", "--host", "example.com"])
    assert result.exit_code == 0
    assert "Default" in result.output
    assert "Random Cycle" in result.output
    assert "Primary Color" in result.output


# ---------------------------------------------------------------------------
# playlists command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_playlists_command(mock_wled_cls: MagicMock) -> None:
    """The playlists command lists playlists from the device."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["playlists", "--host", "example.com"])
    assert result.exit_code == 0
    assert "My Playlist" in result.output


@patch("wled.cli.WLED")
def test_playlists_command_no_playlists(mock_wled_cls: MagicMock) -> None:
    """The playlists command shows a message when there are no playlists."""
    device = _device_no_presets()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["playlists", "--host", "example.com"])
    assert result.exit_code == 0
    assert "no playlists" in result.output


# ---------------------------------------------------------------------------
# presets command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_presets_command(mock_wled_cls: MagicMock) -> None:
    """The presets command lists presets from the device."""
    device = _device()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["presets", "--host", "example.com"])
    assert result.exit_code == 0
    assert "My Preset" in result.output


@patch("wled.cli.WLED")
def test_presets_command_no_presets(mock_wled_cls: MagicMock) -> None:
    """The presets command shows a message when there are no presets."""
    device = _device_no_presets()
    mock_wled_cls.return_value = _make_wled_mock(device).return_value

    result = runner.invoke(cli, ["presets", "--host", "example.com"])
    assert result.exit_code == 0
    assert "no presets" in result.output


# ---------------------------------------------------------------------------
# releases command
# ---------------------------------------------------------------------------


@patch("wled.cli.WLEDReleases")
def test_releases_command(mock_releases_cls: MagicMock) -> None:
    """The releases command shows stable and beta versions."""
    mock_instance = AsyncMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=False)
    mock_instance.releases = AsyncMock(
        return_value=Releases(
            stable=AwesomeVersion("0.14.0"),
            beta=AwesomeVersion("0.15.0b1"),
        ),
    )
    mock_releases_cls.return_value = mock_instance

    result = runner.invoke(cli, ["releases"])
    assert result.exit_code == 0
    assert "Stable" in result.output
    assert "Beta" in result.output
    assert "0.14.0" in result.output
    assert "0.15.0b1" in result.output


# ---------------------------------------------------------------------------
# scan command
# ---------------------------------------------------------------------------


@patch("wled.cli.AsyncZeroconf")
@patch("wled.cli.AsyncServiceBrowser")
def test_scan_command_keyboard_interrupt(
    mock_browser_cls: MagicMock,
    mock_zeroconf_cls: MagicMock,
) -> None:
    """The scan command starts and handles KeyboardInterrupt gracefully."""
    mock_zc_instance = MagicMock()
    mock_zc_instance.zeroconf = MagicMock()
    mock_zc_instance.async_close = AsyncMock()
    mock_zeroconf_cls.return_value = mock_zc_instance

    mock_browser = AsyncMock()
    mock_browser.async_cancel = AsyncMock()
    mock_browser_cls.return_value = mock_browser

    # Make the forever.wait() raise KeyboardInterrupt to simulate Ctrl-C
    async def mock_wait(_self: asyncio.Event) -> None:
        raise KeyboardInterrupt

    with patch.object(asyncio.Event, "wait", mock_wait):
        result = runner.invoke(cli, ["scan"])

    assert "Scanning for WLED devices" in result.output
    assert "stopping scan" in result.output


# ---------------------------------------------------------------------------
# Error handlers (must go through AsyncTyper.__call__ to trigger)
# ---------------------------------------------------------------------------


@patch("wled.cli.WLED")
def test_connection_error_handler(mock_wled_cls: MagicMock) -> None:
    """WLEDConnectionError is caught and shows an error panel."""
    mock_wled_cls.return_value = _make_wled_error_mock(
        WLEDConnectionError("fail"),
    ).return_value

    result = runner.invoke(cli, ["info", "--host", "example.com"])

    # CliRunner calls .main() which bypasses __call__. The exception
    # propagates through asyncio.run and click catches it as a generic error.
    # Instead we exercise the error handler via __call__ directly.
    assert result.exit_code != 0


@patch("wled.cli.console")
@patch("wled.cli.WLED")
def test_connection_error_handler_via_call(
    mock_wled_cls: MagicMock,
    mock_console: MagicMock,
) -> None:
    """WLEDConnectionError triggers the connection error handler via __call__."""
    mock_wled_cls.return_value = _make_wled_error_mock(
        WLEDConnectionError("fail"),
    ).return_value

    with pytest.raises(SystemExit, match="1"):
        cli(["info", "--host", "example.com"], standalone_mode=False)

    # Verify the error panel was printed
    mock_console.print.assert_called()
    panel_arg = mock_console.print.call_args[0][0]
    assert "Connection error" in panel_arg.title


@patch("wled.cli.console")
@patch("wled.cli.WLED")
def test_unsupported_version_error_handler_via_call(
    mock_wled_cls: MagicMock,
    mock_console: MagicMock,
) -> None:
    """WLEDUnsupportedVersionError triggers the version error handler."""
    mock_wled_cls.return_value = _make_wled_error_mock(
        WLEDUnsupportedVersionError("too old"),
    ).return_value

    with pytest.raises(SystemExit, match="1"):
        cli(["info", "--host", "example.com"], standalone_mode=False)

    # Verify the error panel was printed
    mock_console.print.assert_called()
    panel_arg = mock_console.print.call_args[0][0]
    assert "Unsupported version" in panel_arg.title
