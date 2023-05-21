# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED


async def main() -> None:
    """Show example on controlling your WLED device."""
    async with WLED("10.10.11.61") as led:
        device = await led.update()
        print(device.info.version)

        print(device.info.leds)
        print(device.state.segments[0])
        # await led.segment(
        #     0,
        # await led.segment(

        # if isinstance(device.state.preset, Preset):

        # if isinstance(device.state.playlist, Playlist):

        # Turn strip on, full brightness


if __name__ == "__main__":
    asyncio.run(main())
