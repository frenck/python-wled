# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED, Preset


async def main():
    """Show example on controlling your WLED device."""
    async with WLED("10.10.11.135") as led:
        device = await led.update()
        print(device.info.version)

        if isinstance(device.state.preset, Preset):
            print(f"Preset active! Name: {device.state.preset.name}")

        # Turn strip on, full brightness
        await led.master(on=True, brightness=255)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
