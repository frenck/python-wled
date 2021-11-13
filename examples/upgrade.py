# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED


async def main():
    """Show example on upgrade your WLED device."""
    async with WLED("10.10.11.54") as led:
        device = await led.update()
        print(device.info)

        await led.upgrade(version="0.13.0-b4")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
