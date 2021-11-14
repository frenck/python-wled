# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED


async def main():
    """Show example on upgrade your WLED device."""
    async with WLED("10.10.11.54") as led:
        device = await led.update()
        print(f"Latest stable version: {device.info.version_latest_stable}")
        print(f"Latest beta version: {device.info.version_latest_beta}")
        print(f"Current version: {device.info.version}")

        print("Upgrading WLED....")
        await led.upgrade(version="0.13.0-b4")

        print("Waiting for WLED to come back....")
        await asyncio.sleep(5)

        device = await led.update(full_update=True)
        print(f"Current version: {device.info.version}")


if __name__ == "__main__":
    asyncio.run(main())
