# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED


async def main() -> None:
    """Show example on controlling your WLED device."""
    async with WLED("10.10.11.31") as led:
        device = await led.update()
        print(device.info.version)
        print(device.state)

        if device.state.on:
            print("Turning off WLED....")
            await led.master(on=False)
        else:
            print("Turning on WLED....")
            await led.master(on=True)

        device = await led.update()
        print(device.state)


if __name__ == "__main__":
    asyncio.run(main())
