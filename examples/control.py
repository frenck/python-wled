# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED


async def main(loop):
    """Show example on controlling your WLED device."""
    async with WLED("wled-frenck.local", loop=loop) as led:
        device = await led.update()
        print(device.info.version)

        # Turn strip on, full brightness
        await led.light(on=True, brightness=255)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
