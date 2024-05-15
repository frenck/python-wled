"""Asynchronous Python client for WLED."""

import asyncio

from rich.console import Console
from rich.live import Live
from rich.table import Table
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .async_typer import AsyncTyper

cli = AsyncTyper(help="WLED CLI", no_args_is_help=True, add_completion=False)
console = Console()


@cli.command("scan")
async def test() -> None:
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
