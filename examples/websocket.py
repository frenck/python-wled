# pylint: disable=W0621
"""Asynchronous Python client for WLED."""

import asyncio

from wled import WLED, Device


async def main() -> None:
    """Show example on WebSocket usage with WLED."""
    async with WLED("10.10.11.135") as led:
        await led.connect()
        if led.connected:
            print("connected!")

        def something_updated(device: Device) -> None:
            """Call when WLED reports a state change."""  # noqa
            print("Received an update from WLED")
            print(device.state)
            print(device.info)

        # Start listening
        asyncio.create_task(led.listen(callback=something_updated))

        # Now we wait...
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
