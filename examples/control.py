# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED, Playlist, Preset


async def main() -> None:
    """Show example on controlling your WLED device."""
    async with WLED("10.10.11.135") as led:
        device = await led.update()
        print(device.info.version)

        if isinstance(device.state.preset, Preset):
            print(f"Preset active! Name: {device.state.preset.name}")

        if isinstance(device.state.playlist, Playlist):
            print(f"Playlist active! Name: {device.state.playlist.name}")

        # Turn strip on, full brightness
        await led.master(on=True, brightness=255)


if __name__ == "__main__":
    asyncio.run(main())
