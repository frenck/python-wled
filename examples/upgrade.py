# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio
import sys

from wled import WLED, WLEDReleases


async def main() -> None:
    """Show example on upgrade your WLED device."""
#    async with WLEDReleases("MoonModules/WLED") as releases:
    async with WLEDReleases() as releases:
        latest = await releases.releases()
        print(f"Latest stable version: {latest.stable}")
        print(f"Latest beta version: {latest.beta}")

    if not latest.stable:
        print("No stable version found")
        return

    async with WLED(sys.argv[1]) as led:
        device = await led.update()
        print(f"Current version: {device.info.version}")
        print(f"Current release: {device.info.release}")

        print("Upgrading WLED....")
        await led.upgrade(version=latest.stable,repo=latest.repo) # stable not default option

        print("Waiting for WLED to come back....")
        await asyncio.sleep(5)

        device = await led.update()
        print(f"Current version: {device.info.version}")


if __name__ == "__main__":
    asyncio.run(main())
