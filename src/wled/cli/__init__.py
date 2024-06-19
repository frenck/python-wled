"""Asynchronous Python client for WLED."""

import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from wled import WLED, WLEDReleases

from .async_typer import AsyncTyper

cli = AsyncTyper(help="WLED CLI", no_args_is_help=True, add_completion=False)
console = Console()


@cli.command("info")
async def command_info(
    host: Annotated[
        str,
        typer.Option(
            help="WLED device IP address or hostname",
            prompt="Host address",
            show_default=False,
        ),
    ],
) -> None:
    """Show the latest release information of WLED."""
    with console.status(
        "[cyan]Fetching WLED device information...", spinner="toggle12"
    ):
        async with WLED(host) as led:
            device = await led.update()

    info_table = Table(title="\nWLED device information", show_header=False)
    info_table.add_column("Property", style="cyan bold")
    info_table.add_column("Value", style="green")

    info_table.add_row("Name", device.info.name)
    info_table.add_row("Brand", device.info.brand)
    info_table.add_row("Product", device.info.product)

    info_table.add_section()
    info_table.add_row("IP address", device.info.ip)
    info_table.add_row("MAC address", device.info.mac_address)
    if device.info.wifi:
        info_table.add_row("Wi-Fi BSSID", device.info.wifi.bssid)
        info_table.add_row("Wi-Fi channel", str(device.info.wifi.channel))
        info_table.add_row("Wi-Fi RSSI", f"{device.info.wifi.rssi} dBm")
        info_table.add_row("Wi-Fi signal strength", f"{device.info.wifi.signal}%")

    info_table.add_section()
    info_table.add_row("Version", device.info.version)
    info_table.add_row("Build", str(device.info.build))
    info_table.add_row("Architecture", device.info.architecture)
    info_table.add_row("Arduino version", device.info.arduino_core_version)

    info_table.add_section()
    info_table.add_row("Uptime", f"{int(device.info.uptime.total_seconds())} seconds")
    info_table.add_row("Free heap", f"{device.info.free_heap} bytes")
    info_table.add_row("Total storage", f"{device.info.filesystem.total} bytes")
    info_table.add_row("Used storage", f"{device.info.filesystem.used} bytes")
    info_table.add_row("% Used storage", f"{device.info.filesystem.used_percentage}%")

    info_table.add_section()
    info_table.add_row("Effect count", f"{device.info.effect_count} effects")
    info_table.add_row("Palette count", f"{device.info.palette_count} palettes")

    info_table.add_section()
    info_table.add_row("Sync UDP port", str(device.info.udp_port))
    info_table.add_row(
        "WebSocket",
        "Disabled"
        if device.info.websocket is None
        else f"{device.info.websocket} client(s)",
    )

    info_table.add_section()
    info_table.add_row("Live", "Yes" if device.info.live else "No")
    info_table.add_row("Live IP", device.info.live_ip)
    info_table.add_row("Live mode", device.info.live_mode)

    info_table.add_section()
    info_table.add_row("LED count", f"{device.info.leds.count} LEDs")
    info_table.add_row("LED power", f"{device.info.leds.power} mA")
    info_table.add_row("LED max power", f"{device.info.leds.max_power} mA")

    console.print(info_table)


@cli.command("releases")
async def command_releases() -> None:
    """Show the latest release information of WLED."""
    with console.status(
        "[cyan]Fetching latest release information...", spinner="toggle12"
    ):
        async with WLEDReleases() as releases:
            latest = await releases.releases()

    table = Table(
        title="\n\nFound WLED Releases", header_style="cyan bold", show_lines=True
    )
    table.add_column("Release channel")
    table.add_column("Latest version")
    table.add_column("Release notes")

    table.add_row(
        "Stable",
        latest.stable,
        f"https://github.com/Aircoookie/WLED/releases/v{latest.stable}",
    )
    table.add_row(
        "Beta",
        latest.beta,
        f"https://github.com/Aircoookie/WLED/releases/v{latest.beta}",
    )

    console.print(table)


@cli.command("scan")
async def command_scan() -> None:
    """Scan for WLED devices on the network."""
    zeroconf = AsyncZeroconf()
    background_tasks = set()

    table = Table(
        title="\n\nFound WLED devices", header_style="cyan bold", show_lines=True
    )
    table.add_column("Addresses")
    table.add_column("MAC Address")

    def async_on_service_state_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle service state changes."""
        if state_change is not ServiceStateChange.Added:
            return

        future = asyncio.ensure_future(
            async_display_service_info(zeroconf, service_type, name)
        )
        background_tasks.add(future)
        future.add_done_callback(background_tasks.discard)

    async def async_display_service_info(
        zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:
        """Retrieve and display service info."""
        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000)
        if info is None:
            return

        console.print(f"[cyan bold]Found service {info.server}: is a WLED device 🎉")

        table.add_row(
            f"{str(info.server).rstrip('.')}\n"
            + ", ".join(info.parsed_scoped_addresses()),
            info.properties[b"mac"].decode(),  # type: ignore[union-attr]
        )

    console.print("[green]Scanning for WLED devices...")
    console.print("[red]Press Ctrl-C to exit\n")

    with Live(table, console=console, refresh_per_second=4):
        browser = AsyncServiceBrowser(
            zeroconf.zeroconf,
            "_wled._tcp.local.",
            handlers=[async_on_service_state_change],
        )

        try:
            while True:
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            console.print("\n[green]Control-C pressed, stopping scan")
            await browser.async_cancel()
            await zeroconf.async_close()


if __name__ == "__main__":
    cli()
