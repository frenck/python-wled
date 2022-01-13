"""Asynchronous Python client for WLED."""
from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aiohttp
import async_timeout
import backoff  # type: ignore
from awesomeversion import AwesomeVersion, AwesomeVersionException
from cachetools import TTLCache
from yarl import URL

from .exceptions import (
    WLEDConnectionClosed,
    WLEDConnectionError,
    WLEDConnectionTimeoutError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDUpgradeError,
)
from .models import Device, Live, Playlist, Preset

VERSION_CACHE: TTLCache = TTLCache(maxsize=16, ttl=7200)


@dataclass
class WLED:
    """Main class for handling connections with WLED."""

    host: str
    request_timeout: float = 8.0
    session: aiohttp.client.ClientSession | None = None

    _client: aiohttp.ClientWebSocketResponse | None = None
    _close_session: bool = False
    _device: Device | None = None
    _supports_si_request: bool | None = None
    _supports_presets: bool | None = None

    @property
    def connected(self) -> bool:
        """Return if we are connect to the WebSocket of a WLED device.

        Returns:
            True if we are connected to the WebSocket of a WLED device,
            False otherwise.
        """
        return self._client is not None and not self._client.closed

    async def connect(self) -> None:
        """Connect to the WebSocket of a WLED device.

        Raises:
            WLEDError: The configured WLED device, does not support WebSocket
                communications.
            WLEDConnectionError: Error occurred while communicating with
                the WLED device via the WebSocket.
        """
        if self.connected:
            return

        if not self._device:
            await self.update()

        if not self.session or not self._device or self._device.info.websocket is None:
            raise WLEDError(
                "The WLED device at {self.host} does not support WebSockets"
            )

        url = URL.build(scheme="ws", host=self.host, port=80, path="/ws")

        try:
            self._client = await self.session.ws_connect(url=url, heartbeat=30)
        except (
            aiohttp.WSServerHandshakeError,
            aiohttp.ClientConnectionError,
            socket.gaierror,
        ) as exception:
            raise WLEDConnectionError(
                "Error occurred while communicating with WLED device"
                f" on WebSocket at {self.host}"
            ) from exception

    async def listen(self, callback: Callable[[Device], None]) -> None:
        """Listen for events on the WLED WebSocket.

        Args:
            callback: Method to call when a state update is received from
                the WLED device.

        Raises:
            WLEDError: Not connected to a WebSocket.
            WLEDConnectionError: An connection error occurred while connected
                to the WLED device.
            WLEDConnectionClosed: The WebSocket connection to the remote WLED
                has been closed.
        """
        if not self._client or not self.connected or not self._device:
            raise WLEDError("Not connected to a WLED WebSocket")

        while not self._client.closed:
            message = await self._client.receive()

            if message.type == aiohttp.WSMsgType.ERROR:
                raise WLEDConnectionError(self._client.exception())

            if message.type == aiohttp.WSMsgType.TEXT:
                message_data = message.json()
                device = self._device.update_from_dict(data=message_data)
                callback(device)

            if message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                raise WLEDConnectionClosed(
                    f"Connection to the WLED WebSocket on {self.host} has been closed"
                )

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket of a WLED device."""
        if not self._client or not self.connected:
            return

        await self._client.close()

    @backoff.on_exception(backoff.expo, WLEDConnectionError, max_tries=3, logger=None)
    async def request(
        self,
        uri: str = "",
        method: str = "GET",
        data: dict | None = None,
    ) -> Any:
        """Handle a request to a WLED device.

        A generic method for sending/handling HTTP requests done gainst
        the WLED device.

        Args:
            uri: Request URI, for example `/json/si`.
            method: HTTP method to use for the request.E.g., "GET" or "POST".
            data: Dictionary of data to send to the WLED device.

        Returns:
            A Python dictionary (JSON decoded) with the response from the
            WLED device.

        Raises:
            WLEDConnectionError: An error occurred while communitcation with
                the WLED device.
            WLEDConnectionTimeoutError: A timeout occurred while communicating
                with the WLED device.
            WLEDError: Received an unexpected response from the WLED device.
        """
        url = URL.build(scheme="http", host=self.host, port=80, path=uri)

        headers = {
            "Accept": "application/json, text/plain, */*",
        }

        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True

        # If updating the state, always request for a state response
        if method == "POST" and uri == "/json/state" and data is not None:
            data["v"] = True

        try:
            async with async_timeout.timeout(self.request_timeout):
                response = await self.session.request(
                    method,
                    url,
                    json=data,
                    headers=headers,
                )
        except asyncio.TimeoutError as exception:
            raise WLEDConnectionTimeoutError(
                f"Timeout occurred while connecting to WLED device at {self.host}"
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise WLEDConnectionError(
                f"Error occurred while communicating with WLED device at {self.host}"
            ) from exception

        content_type = response.headers.get("Content-Type", "")
        if (response.status // 100) in [4, 5]:
            contents = await response.read()
            response.close()

            if content_type == "application/json":
                raise WLEDError(response.status, json.loads(contents.decode("utf8")))
            raise WLEDError(response.status, {"message": contents.decode("utf8")})

        if "application/json" in content_type:
            response_data = await response.json()
            if (
                method == "POST"
                and uri == "/json/state"
                and self._device is not None
                and data is not None
            ):
                self._device.update_from_dict(data={"state": response_data})
            return response_data

        return await response.text()

    @backoff.on_exception(
        backoff.expo, WLEDEmptyResponseError, max_tries=3, logger=None
    )
    async def update(self, full_update: bool = False) -> Device:
        """Get all information about the device in a single call.

        This method updates all WLED information available with a single API
        call.

        Args:
            full_update: Force a full update from the WLED Device.

        Returns:
            WLED Device data.

        Raises:
            WLEDEmptyResponseError: The WLED device returned an empty response.
        """
        if self._device is None or full_update:
            if not (data := await self.request("/json")):
                raise WLEDEmptyResponseError(
                    f"WLED device at {self.host} returned an empty API"
                    " response on full update"
                )

            # Try to get presets, introduced in WLED 0.11
            try:
                presets = await self.request("/presets.json")
                data["presets"] = presets
                self._supports_presets = True
            except WLEDError:
                self._supports_presets = False

            versions = await self.get_wled_versions_from_github()
            data["info"].update(versions)

            self._device = Device(data)

            # Try to figure out if this version supports
            # a single info and state call
            try:
                self._supports_si_request = self._device.info.version >= AwesomeVersion(
                    "0.10.0"
                )
            except AwesomeVersionException:
                # Could be a manual build one? Lets poll for it
                try:
                    await self.request("/json/si")
                    self._supports_si_request = True
                except WLEDError:
                    self._supports_si_request = False

            return self._device

        if self._supports_presets:
            if not (presets := await self.request("/presets.json")):
                raise WLEDEmptyResponseError(
                    f"WLED device at {self.host} returned an empty API"
                    " response on presets update"
                )
            self._device.update_from_dict({"presets": presets})

        # Handle legacy state and update in separate requests
        if not self._supports_si_request:
            if not (info := await self.request("/json/info")):
                raise WLEDEmptyResponseError(
                    f"WLED device at {self.host} returned an empty API"
                    " response on info update"
                )

            if not (state := await self.request("/json/state")):
                raise WLEDEmptyResponseError(
                    f"WLED device {self.host} returned an empty API"
                    " response on state update"
                )

            with suppress(WLEDError):
                versions = await self.get_wled_versions_from_github()
                info.update(versions)

            self._device.update_from_dict({"info": info, "state": state})
            return self._device

        if not (state_info := await self.request("/json/si")):
            raise WLEDEmptyResponseError(
                f"WLED device at {self.host} returned an empty API"
                " response on state & info update"
            )

        with suppress(WLEDError):
            versions = await self.get_wled_versions_from_github()
            state_info["info"].update(versions)

        self._device.update_from_dict(state_info)

        return self._device

    async def master(
        self,
        *,
        brightness: int | None = None,
        on: bool | None = None,
        transition: int | None = None,
    ):
        """Change master state of a WLED Light device.

        Args:
            brightness: The brightness of the light master, between 0 and 255.
            on: A boolean, true to turn the master light on, false otherwise.
            transition: Duration of the crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.
        """
        state: dict[str, bool | int] = {}

        if brightness is not None:
            state["bri"] = brightness

        if on is not None:
            state["on"] = on

        if transition is not None:
            state["tt"] = transition

        await self.request("/json/state", method="POST", data=state)

    async def segment(  # pylint: disable=too-many-locals, too-many-branches
        self,
        segment_id: int,
        *,
        brightness: int | None = None,
        clones: int | None = None,
        color_primary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        color_secondary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        color_tertiary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        effect: int | str | None = None,
        intensity: int | None = None,
        length: int | None = None,
        on: bool | None = None,
        palette: int | str | None = None,
        reverse: bool | None = None,
        selected: bool | None = None,
        speed: int | None = None,
        start: int | None = None,
        stop: int | None = None,
        transition: int | None = None,
    ) -> None:
        """Change state of a WLED Light segment.

        Args:
            segment_id: The ID of the segment to adjust.
            brightness: The brightness of the segment, between 0 and 255.
            clones: Deprecated.
            color_primary: The primary color of this segment.
            color_secondary: The secondary color of this segment.
            color_tertiary: The tertiary color of this segment.
            effect: The effect number (or name) to use on this segment.
            intensity: The effect intensity to use on this segment.
            length: The length of this segment.
            on: A boolean, true to turn this segment on, false otherwise.
            palette: the palette number or name to use on this segment.
            reverse: Flips the segment, causing animations to change direction.
            selected: Selected segments will have their state (color/FX) updated
                by APIs that don't support segments.
            speed: The relative effect speed, between 0 and 255.
            start: LED the segment starts at.
            stop: LED the segment stops at, not included in range. If stop is
                set to a lower or equal value than start (setting to 0 is
                recommended), the segment is invalidated and deleted.
            transition:  Duration of the crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.

        Raises:
            WLEDError: Something went wrong setting the segment state.
        """
        if self._device is None:
            await self.update()

        if self._device is None:
            raise WLEDError("Unable to communicate with WLED to get the current state")

        state = {}
        segment = {
            "bri": brightness,
            "cln": clones,
            "fx": effect,
            "ix": intensity,
            "len": length,
            "on": on,
            "pal": palette,
            "rev": reverse,
            "sel": selected,
            "start": start,
            "stop": stop,
            "sx": speed,
        }

        # > WLED 0.10.0, does not support segment control on/bri.
        # Luckily, the same release introduced si requests.
        # Therefore, we can use that capability check to decide.
        if not self._supports_si_request:
            # This device does not support on/bri in the segment
            del segment["on"]
            del segment["bri"]
            state = {
                "bri": brightness,
                "on": on,
            }

        # Find effect if it was based on a name
        if effect is not None and isinstance(effect, str):
            segment["fx"] = next(
                (
                    item.effect_id
                    for item in self._device.effects
                    if item.name.lower() == effect.lower()
                ),
                None,
            )

        # Find palette if it was based on a name
        if palette is not None and isinstance(palette, str):
            segment["pal"] = next(
                (
                    item.palette_id
                    for item in self._device.palettes
                    if item.name.lower() == palette.lower()
                ),
                None,
            )

        # Filter out not set values
        state = {k: v for k, v in state.items() if v is not None}
        segment = {k: v for k, v in segment.items() if v is not None}

        # Determine color set
        colors = []
        if color_primary is not None:
            colors.append(color_primary)
        elif color_secondary is not None or color_tertiary is not None:
            colors.append(self._device.state.segments[segment_id].color_primary)

        if color_secondary is not None:
            colors.append(color_secondary)
        elif color_tertiary is not None:
            colors.append(self._device.state.segments[segment_id].color_secondary)

        if color_tertiary is not None:
            colors.append(color_tertiary)

        if colors:
            segment["col"] = colors  # type: ignore

        if segment:
            segment["id"] = segment_id
            state["seg"] = [segment]  # type: ignore

        if transition is not None:
            state["tt"] = transition

        await self.request("/json/state", method="POST", data=state)

    async def transition(self, transition: int) -> None:
        """Set the default transition time for manual control.

        Args:
            transition: Duration of the default crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.
        """
        await self.request(
            "/json/state", method="POST", data={"transition": transition}
        )

    async def preset(self, preset: int | str | Preset) -> None:
        """Set a preset on a WLED device.

        Args:
            preset: The preset to activate on this WLED device.
        """
        # Find preset if it was based on a name
        if self._device and self._device.presets and isinstance(preset, str):
            preset = next(
                (
                    item.preset_id
                    for item in self._device.presets
                    if item.name.lower() == preset.lower()
                ),
                preset,
            )

        if isinstance(preset, Preset):
            preset = preset.preset_id

        await self.request("/json/state", method="POST", data={"ps": preset})

    async def playlist(self, playlist: int | str | Playlist) -> None:
        """Set a playlist on a WLED device.

        Args:
            playlist: The playlist to activate on this WLED device.
        """

        # Find playlist if it was based on a name
        if self._device and self._device.playlists and isinstance(playlist, str):
            playlist = next(
                (
                    item.playlist_id
                    for item in self._device.playlists
                    if item.name.lower() == playlist.lower()
                ),
                playlist,
            )

        if isinstance(playlist, Playlist):
            playlist = playlist.playlist_id

        await self.request("/json/state", method="POST", data={"ps": playlist})

    async def live(self, live: Live) -> None:
        """Set the live override mode on a WLED device.

        Args:
            live: The live override mode to set on this WLED device.
        """
        await self.request("/json/state", method="POST", data={"lor": live.value})

    async def sync(
        self, *, send: bool | None = None, receive: bool | None = None
    ) -> None:
        """Set the sync status of the WLED device.

        Args:
            send: Send WLED broadcast (UDP sync) packet on state change.
            receive: Receive broadcast packets.
        """
        sync = {"send": send, "recv": receive}
        sync = {k: v for k, v in sync.items() if v is not None}
        await self.request("/json/state", method="POST", data={"udpn": sync})

    async def nightlight(
        self,
        *,
        duration: int | None = None,
        fade: bool | None = None,
        on: bool | None = None,
        target_brightness: int | None = None,
    ) -> None:
        """Control the nightlight function of a WLED device.

        Args:
            duration: Duration of nightlight in minutes.
            fade: If true, the light will gradually dim over the course of the
                nightlight duration. If false, it will instantly turn to the
                target brightness once the duration has elapsed.
            on: A boolean, true to turn the nightlight on, false otherwise.
            target_brightness: Target brightness of nightlight, between 0 and 255.
        """
        nightlight = {
            "dur": duration,
            "fade": fade,
            "on": on,
            "tbri": target_brightness,
        }

        # Filter out not set values
        nightlight = {k: v for k, v in nightlight.items() if v is not None}

        state: dict[str, Any] = {"nl": nightlight}
        if on:
            state["on"] = True

        await self.request("/json/state", method="POST", data=state)

    async def upgrade(self, *, version: str | AwesomeVersion) -> None:
        """Upgrades WLED device to the specified version.

        Args:
            version: The version to upgrade to.

        Raises:
            WLEDUpgradeError: If the upgrade has failed.
            WLEDConnectionTimeoutError: When a connection timeout occurs.
            WLEDConnectionError: When a connection error occurs.
        """
        if self._device is None:
            await self.update()

        if self.session is None or self._device is None:
            raise WLEDUpgradeError("Unexpected upgrade error; No session or device")

        if self._device.info.architecture not in {"esp8266", "esp32"}:
            raise WLEDUpgradeError("Upgrade is only supported on ESP8266 and ESP32")

        if not self._device.info.version:
            raise WLEDUpgradeError("Current version is unknown, cannot perform upgrade")

        if self._device.info.version == version:
            raise WLEDUpgradeError("Device already running the requested version")

        # Determine if this is an Ethernet board
        ethernet = ""
        if (
            self._device.info.architecture == "esp32"
            and self._device.info.wifi is not None
            and not self._device.info.wifi.bssid
            and self._device.info.version
            and self._device.info.version >= "0.10.0"
        ):
            ethernet = "_Ethernet"

        url = URL.build(scheme="http", host=self.host, port=80, path="/update")
        update_file = (
            f"WLED_{version}_{self._device.info.architecture.upper()}{ethernet}.bin"
        )
        download_url = f"https://github.com/Aircoookie/WLED/releases/download/v{version}/{update_file}"

        try:
            async with async_timeout.timeout(self.request_timeout * 10):
                async with self.session.get(
                    download_url, raise_for_status=True
                ) as download:
                    form = aiohttp.FormData()
                    form.add_field("file", await download.read(), filename=update_file)
                    await self.session.post(url, data=form)
        except asyncio.TimeoutError as exception:
            raise WLEDConnectionTimeoutError(
                "Timeout occurred while fetching WLED version information from GitHub"
            ) from exception
        except aiohttp.ClientResponseError as exception:
            if exception.status == 404:
                raise WLEDUpgradeError(
                    f"Requested WLED version '{version}' does not exists"
                ) from exception
            raise WLEDUpgradeError(
                f"Could not download requested WLED version '{version}' from {download_url}"
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise WLEDConnectionError(
                "Timeout occurred while communicating with GitHub for WLED version information"
            ) from exception

    @backoff.on_exception(backoff.expo, WLEDConnectionError, max_tries=3, logger=None)
    async def get_wled_versions_from_github(self) -> dict[str, str | None]:
        """Fetch WLED version information from GitHub.

        Returns:
            A dictionary of WLED versions, with the key being the version type.

        Raises:
            WLEDConnectionTimeoutError: Timeout occurred while fetching WLED
                version information from GitHub.
            WLEDConnectionError: Timeout occurred while communicating with
                GitHub for WLED version information.
            WLEDError: Didn't get a JSON response from GitHub while retrieving
                version information.
        """
        with suppress(KeyError):
            return {
                "version_latest_stable": VERSION_CACHE["stable"],
                "version_latest_beta": VERSION_CACHE["beta"],
            }

        if self.session is None:
            return {"version_latest_stable": None, "version_latest_beta": None}

        try:
            async with async_timeout.timeout(self.request_timeout):
                response = await self.session.get(
                    "https://api.github.com/repos/Aircoookie/WLED/releases",
                    headers={"Accept": "application/json"},
                )
        except asyncio.TimeoutError as exception:
            raise WLEDConnectionTimeoutError(
                "Timeout occurred while fetching WLED version information from GitHub"
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise WLEDConnectionError(
                "Timeout occurred while communicating with GitHub for WLED version"
            ) from exception

        content_type = response.headers.get("Content-Type", "")
        if (response.status // 100) in [4, 5]:
            contents = await response.read()
            response.close()

            if content_type == "application/json":
                raise WLEDError(response.status, json.loads(contents.decode("utf8")))
            raise WLEDError(response.status, {"message": contents.decode("utf8")})

        if "application/json" not in content_type:
            raise WLEDError(
                "Didn't get a JSON response from GitHub while retrieving version information"
            )

        releases = await response.json()
        version_latest = None
        version_latest_beta = None
        for release in releases:
            if release["prerelease"] is False and version_latest is None:
                version_latest = release["tag_name"].lstrip("vV")
            if release["prerelease"] is True and version_latest_beta is None:
                version_latest_beta = release["tag_name"].lstrip("vV")
            if version_latest is not None and version_latest_beta is not None:
                break

        # Cache results
        VERSION_CACHE["stable"] = version_latest
        VERSION_CACHE["beta"] = version_latest_beta

        return {
            "version_latest_stable": version_latest,
            "version_latest_beta": version_latest_beta,
        }

    async def reset(self) -> None:
        """Reboot WLED device."""
        await self.request("/reset")

    async def close(self) -> None:
        """Close open client (WebSocket) session."""
        await self.disconnect()
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> WLED:
        """Async enter.

        Returns:
            The WLED object.
        """
        return self

    async def __aexit__(self, *_exc_info) -> None:
        """Async exit.

        Args:
            _exc_info: Exec type.
        """
        await self.close()
