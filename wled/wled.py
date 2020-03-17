"""Asynchronous Python client for WLED."""
import asyncio
import json
import socket
from typing import Any, Dict, Mapping, Optional, Tuple, Union

import aiohttp
import async_timeout
from yarl import URL

from .__version__ import __version__
from .exceptions import WLEDConnectionError, WLEDError
from .models import Device


class WLED:
    """Main class for handling connections with WLED."""

    _device: Optional[Device] = None

    def __init__(
        self,
        host: str,
        base_path: str = "/json",
        password: str = None,
        port: int = 80,
        request_timeout: int = 8,
        session: aiohttp.client.ClientSession = None,
        tls: bool = False,
        username: str = None,
        verify_ssl: bool = True,
        user_agent: str = None,
    ) -> None:
        """Initialize connection with WLED."""
        self._session = session
        self._close_session = False

        self.base_path = base_path
        self.host = host
        self.password = password
        self.port = port
        self.socketaddr = None
        self.request_timeout = request_timeout
        self.tls = tls
        self.username = username
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent

        if user_agent is None:
            self.user_agent = f"PythonWLED/{__version__}"

        if self.base_path[-1] != "/":
            self.base_path += "/"

    async def _request(
        self,
        uri: str = "",
        method: str = "GET",
        data: Optional[Any] = None,
        json_data: Optional[dict] = None,
        params: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Handle a request to a WLED device."""
        scheme = "https" if self.tls else "http"
        url = URL.build(
            scheme=scheme, host=self.host, port=self.port, path=self.base_path
        ).join(URL(uri))

        auth = None
        if self.username and self.password:
            auth = aiohttp.BasicAuth(self.username, self.password)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
        }

        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._close_session = True

        # If updating the state, always request for a state response
        if method == "POST" and uri == "state" and json_data is not None:
            json_data["v"] = True

        try:
            with async_timeout.timeout(self.request_timeout):
                response = await self._session.request(
                    method,
                    url,
                    auth=auth,
                    data=data,
                    json=json_data,
                    params=params,
                    headers=headers,
                    ssl=self.verify_ssl,
                )
        except asyncio.TimeoutError as exception:
            raise WLEDConnectionError(
                "Timeout occurred while connecting to WLED device."
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise WLEDConnectionError(
                "Error occurred while communicating with WLED device."
            ) from exception

        content_type = response.headers.get("Content-Type", "")
        if (response.status // 100) in [4, 5]:
            contents = await response.read()
            response.close()

            if content_type == "application/json":
                raise WLEDError(response.status, json.loads(contents.decode("utf8")))
            raise WLEDError(response.status, {"message": contents.decode("utf8")})

        if "application/json" in content_type:
            data = await response.json()
            if (
                method == "POST"
                and uri == "state"
                and self._device is not None
                and json_data is not None
            ):
                self._device.update_from_dict(data={"state": data})
            return data

        return await response.text()

    async def update(self, full_update: bool = False) -> Device:
        """Get all information about the device in a single call."""
        if self._device is None or full_update:
            data = await self._request()
            if data is None:
                raise WLEDError("WLED device returned an empty API response")
            self._device = Device(data)
            return self._device

        info = await self._request("info")
        state = await self._request("state")
        self._device.update_from_dict({"info": info, "state": state})
        return self._device

    async def light(
        self,
        brightness: Optional[int] = None,
        clones: Optional[int] = None,
        color_primary: Optional[
            Union[Tuple[int, int, int, int], Tuple[int, int, int]]
        ] = None,
        color_secondary: Optional[
            Union[Tuple[int, int, int, int], Tuple[int, int, int]]
        ] = None,
        color_tertiary: Optional[
            Union[Tuple[int, int, int, int], Tuple[int, int, int]]
        ] = None,
        effect: Optional[Union[int, str]] = None,
        intensity: Optional[int] = None,
        length: Optional[int] = None,
        on: Optional[bool] = None,
        palette: Optional[Union[int, str]] = None,
        reverse: Optional[bool] = None,
        segment_id: int = 0,
        selected: Optional[bool] = None,
        speed: Optional[int] = None,
        start: Optional[int] = None,
        stop: Optional[int] = None,
        transition: Optional[int] = None,
    ) -> None:
        """Change state of a WLED Light segment."""
        if self._device is None:
            await self.update()

        if self._device is None:
            raise WLEDError("Unable to communicate with WLED to get the current state")

        state = {
            "bri": brightness,
            "on": on,
        }

        segment = {
            "cln": clones,
            "fx": effect,
            "ix": intensity,
            "len": length,
            "pal": palette,
            "rev": reverse,
            "sel": selected,
            "start": start,
            "stop": stop,
            "sx": speed,
        }

        # Find effect if it was based on a name
        if effect is not None and isinstance(effect, str):
            segment["fx"] = next(
                (
                    item.effect_id
                    for item in self._device.effects
                    if item.name == effect
                ),
                None,
            )

        # Find palette if it was based on a name
        if palette is not None and isinstance(palette, str):
            segment["pal"] = next(
                (
                    item.palette_id
                    for item in self._device.palettes
                    if item.name == palette
                ),
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

        await self._request("state", method="POST", json_data=state)

    async def transition(self, transition: int) -> None:
        """Set the default transition time for manual control."""
        await self._request(
            "state", method="POST", json_data={"transition": transition}
        )

    async def preset(self, preset: int) -> None:
        """Set a preset on a WLED device."""
        await self._request("state", method="POST", json_data={"ps": preset})

    async def playlist(self, playlist: int) -> None:
        """Set a running playlist on a WLED device."""
        await self._request("state", method="POST", json_data={"pl": playlist})

    async def sync(
        self, send: Optional[bool] = None, receive: Optional[bool] = None
    ) -> None:
        """Set the sync status of the WLED device."""
        sync = {"send": send, "recv": receive}
        sync = {k: v for k, v in sync.items() if v is not None}
        await self._request("state", method="POST", json_data={"udpn": sync})

    async def nightlight(
        self,
        duration: Optional[int] = None,
        fade: Optional[bool] = None,
        on: Optional[bool] = None,
        target_brightness: Optional[int] = None,
    ) -> None:
        """Control the nightlight function of a WLED device."""
        nightlight = {
            "dur": duration,
            "fade": fade,
            "on": on,
            "tbri": target_brightness,
        }

        # Filter out not set values
        nightlight = {k: v for k, v in nightlight.items() if v is not None}

        state: Dict[str, Any] = {"nl": nightlight}
        if on:
            state["on"] = True

        await self._request("state", method="POST", json_data=state)

    async def close(self) -> None:
        """Close open client session."""
        if self._session and self._close_session:
            await self._session.close()

    async def __aenter__(self) -> "WLED":
        """Async enter."""
        return self

    async def __aexit__(self, *exc_info) -> None:
        """Async exit."""
        await self.close()
