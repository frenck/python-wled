"""Asynchronous Python client for WLED."""

from __future__ import annotations

import asyncio
import hashlib
import re
import socket
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

import aiohttp
import backoff
import orjson
from yarl import URL

from .const import (
    DEFAULT_REPO,
    SYNC_RECEIVE_BY_GROUPS_VERSION,
    NightlightMode,
    SyncGroup,
)
from .exceptions import (
    WLEDConnectionClosedError,
    WLEDConnectionError,
    WLEDConnectionTimeoutError,
    WLEDEmptyResponseError,
    WLEDError,
    WLEDInvalidResponseError,
    WLEDStatusError,
    WLEDUpgradeError,
)
from .models import Device, Playlist, Preset, Releases, SegmentUpdate
from .utils import get_awesome_version

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from awesomeversion import AwesomeVersion

    from .const import LiveDataOverride
    from .models import ColorTuple, Info


def _decode_response(
    method: str, uri: str, *, status: int, content_type: str, contents: bytes
) -> Any:
    """Return the decoded body of a WLED response, or raise its error."""
    is_error = status // 100 in [4, 5]
    kind = "error response" if is_error else "response"

    try:
        response_data: Any = contents.decode("utf-8")
    except UnicodeDecodeError as exception:
        msg = f"Received a non-UTF-8 {kind} from request: {method} {uri}"
        raise WLEDInvalidResponseError(msg, method=method, path=uri) from exception

    is_json = "application/json" in content_type
    if is_json:
        try:
            response_data = orjson.loads(response_data)
        except orjson.JSONDecodeError as exception:
            msg = f"Received an invalid JSON {kind} from request: {method} {uri}"
            raise WLEDInvalidResponseError(msg, method=method, path=uri) from exception

    if is_error:
        # A JSON error is passed on as the device sent it; plain text is
        # wrapped, as it always was.
        body = response_data if is_json else {"message": response_data}
        raise WLEDStatusError(
            status, body, method=method, path=uri, status=status, body=body
        )

    return response_data


def _is_not_retryable(exception: Exception) -> bool:
    """Return whether a failed request is not worth trying again.

    Connection errors are retried, and so is a 503: older WLED versions
    answer with it while they're busy handling another request.
    """
    return isinstance(exception, WLEDStatusError) and exception.status != 503


# WLED keeps transitions in milliseconds in 16 bits, so anything above this
# many units of 100ms wraps around to a short transition.
_MAX_TRANSITION = 655


def _transition(transition: int) -> int:
    """Return a transition WLED can hold, in units of 100ms."""
    return max(0, min(transition, _MAX_TRANSITION))


def _resolve_by_name(name: str, ids_by_name: dict[str, int], kind: str) -> int:
    """Return the ID of a preset or playlist given by name, or by ID as text.

    WLED reads a name it gets for "ps" as a number, and one starting with "r"
    as a random preset, so an unknown name must never be sent along.
    """
    # isdecimal, unlike isdigit, only accepts what int() takes.
    if name.isdecimal():
        return int(name)

    for item_name, item_id in ids_by_name.items():
        if item_name.lower() == name.lower():
            return item_id

    msg = f"Unknown {kind}: {name!r}"
    raise WLEDError(msg)


# The heading WLED shows after it accepted a firmware upload (since 0.14).
_UPDATE_SUCCESSFUL = "Update successful!"


def _verify_upload_accepted(status: int, page: str) -> None:
    """Raise if WLED did not accept a firmware upload.

    The status code alone can't be trusted: WLED has been seen to answer a
    rejected upload (like one from outside the local subnet) with a 200. The
    HTML page it answers with, `<h2>Heading</h2>Detail<br>...`, is the real
    verdict.
    """
    if status < 400 and _UPDATE_SUCCESSFUL in page:
        return

    reason = f"HTTP {status}"
    if match := re.search(r"<h2>(.*?)</h2>\s*([^<]*)", page, re.DOTALL):
        reason = " ".join(part.strip() for part in match.groups() if part.strip())

    msg = f"WLED device did not accept the firmware upload: {reason}"
    raise WLEDUpgradeError(msg)


# A plain "owner/name" pair, as GitHub names repositories. Deliberately a bit
# looser than GitHub's own rules: the point is keeping slashes, dot segments,
# and URL syntax out of the download URL, not policing names.
_GITHUB_REPO = re.compile(r"[A-Za-z0-9][\w-]{0,38}/(?!\.\.?$)[\w.-]{1,100}", re.ASCII)


def _firmware_repo(requested: str | None, info: Info) -> str:
    """Return the GitHub repository to download the firmware from.

    Without an explicit choice, this is the repository the device reports.
    It ends up in the download URL, so it has to be a plain "owner/name"
    pair; anything else could point the download somewhere else.
    """
    repo = (requested if requested is not None else info.repo).strip()
    repo = repo or DEFAULT_REPO

    if not _GITHUB_REPO.fullmatch(repo):
        msg = f"Invalid firmware repository: {repo!r}"
        raise WLEDUpgradeError(msg)

    return repo


def _firmware_file_name(info: Info, version: str | AwesomeVersion) -> str:
    """Return the name of the firmware file for a device and version."""
    # Determine if this is a 2M ESP8266 board.
    # See issue `https://github.com/wled/WLED/issues/3257`
    gzip = ".gz" if info.architecture == "esp02" else ""

    # If the device reports its release name, use it to build the
    # correct firmware filename. Otherwise fall back to architecture.
    if info.release is not None:
        return f"{info.brand}_{version}_{info.release}.bin{gzip}"

    # Determine if this is an Ethernet board
    ethernet = ""
    if (
        info.architecture == "esp32"
        and info.wifi is not None
        and not info.wifi.bssid
        and info.version
        and info.version >= "0.10.0"
    ):
        ethernet = "_Ethernet"

    architecture = info.architecture.upper()
    return f"WLED_{version}_{architecture}{ethernet}.bin{gzip}"


# A release version as WLED tags them (without the "v"), like 0.15.0 or
# 16.0.0-b1. It ends up in the download URL, so nothing else gets through.
_FIRMWARE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?", re.ASCII)

# GitHub publishes release asset digests as "sha256:<hex>".
_SHA256_DIGEST = re.compile(r"sha256:([0-9a-f]{64})", re.ASCII)


def _firmware_version(version: str | AwesomeVersion) -> str:
    """Return the version to upgrade to, refusing anything that isn't one."""
    if not _FIRMWARE_VERSION.fullmatch(str(version)):
        msg = f"Invalid firmware version: {str(version)!r}"
        raise WLEDUpgradeError(msg)

    return str(version)


@dataclass
class _FirmwareAsset:
    """A firmware file in a GitHub release."""

    name: str
    sha256: str | None = None


@dataclass
class _PresetsVersion:
    """Tracks preset modification state to avoid unnecessary fetches."""

    modified_timestamp: int
    boot_time: int


@dataclass
class _CatalogVersion:
    """Tracks the effects and palettes lists to avoid unnecessary fetches."""

    effect_count: int
    palette_count: int
    boot_time: int


@dataclass
class WLED:
    """Main class for handling connections with WLED."""

    host: str
    request_timeout: float = 8.0
    session: aiohttp.client.ClientSession | None = None

    _client: aiohttp.ClientWebSocketResponse | None = None
    _close_session: bool = False
    _device: Device | None = None
    _presets_version: _PresetsVersion | None = None
    _catalog_version: _CatalogVersion | None = None
    _catalog: dict[str, list[Any] | None] = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        """Return if we are connected to the WebSocket of a WLED device.

        Returns
        -------
            True if we are connected to the WebSocket of a WLED device,
            False otherwise.

        """
        return self._client is not None and not self._client.closed

    async def connect(self) -> None:
        """Connect to the WebSocket of a WLED device.

        Raises
        ------
            WLEDError: The configured WLED device does not support WebSocket
                communications.
            WLEDConnectionError: Error occurred while communicating with
                the WLED device via the WebSocket.

        """
        if self.connected:
            return

        if not self._device:
            await self.update()

        if not self.session or not self._device or self._device.info.websocket is None:
            msg = f"The WLED device at {self.host} does not support WebSockets"
            raise WLEDError(msg)

        url = URL.build(scheme="ws", host=self.host, port=80, path="/ws")

        try:
            self._client = await self.session.ws_connect(url=url, heartbeat=30)
        except (
            aiohttp.WSServerHandshakeError,
            aiohttp.ClientConnectionError,
            socket.gaierror,
        ) as exception:
            msg = (
                "Error occurred while communicating with WLED device"
                f" on WebSocket at {self.host}"
            )
            raise WLEDConnectionError(msg) from exception

    async def listen(self, callback: Callable[[Device], None]) -> None:
        """Listen for events on the WLED WebSocket.

        Args:
        ----
            callback: Method to call when a state update is received from
                the WLED device.

        Raises:
        ------
            WLEDError: Not connected to a WebSocket.
            WLEDConnectionError: A connection error occurred while connected
                to the WLED device.
            WLEDConnectionClosedError: The WebSocket connection to the remote WLED
                has been closed.
            WLEDEmptyResponseError: The WLED device returned an empty response
                when fetching presets.
            WLEDInvalidResponseError: The WLED device returned an invalid response
                when fetching presets.
            WLEDStatusError: The WLED device returned a 4xx/5xx HTTP status
                when fetching presets.

        """
        if not self._client or not self.connected or not self._device:
            msg = "Not connected to a WLED WebSocket"
            raise WLEDError(msg)

        # Whether the state was asked for again after the device reported
        # being busy; asked once, the device sends its state when it can.
        asked_again = False
        while not self._client.closed:
            message = await self._client.receive()

            if message.type == aiohttp.WSMsgType.ERROR:
                raise WLEDConnectionError(self._client.exception())

            if message.type == aiohttp.WSMsgType.TEXT:
                message_data = message.json()

                # A busy device sends an error instead of its state; ask for
                # the state again rather than reporting the old one. Only once:
                # a device that stays busy answers every request with another
                # error.
                if isinstance(message_data, dict) and "state" not in message_data:
                    if not asked_again:
                        await self._client.send_json({"v": True})
                        asked_again = True
                    continue

                asked_again = False

                changed, new_version = self._check_presets_changed(message_data)
                if changed:
                    if not (presets := await self.request("/presets.json")):
                        msg = (
                            f"WLED device at {self.host} returned an empty API"
                            " response on presets update"
                        )
                        raise WLEDEmptyResponseError(
                            msg, method="GET", path="/presets.json"
                        )
                    message_data["presets"] = presets

                device = self._device.update_from_dict(data=message_data)
                self._presets_version = new_version
                callback(device)

            if message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                msg = f"Connection to the WLED WebSocket on {self.host} has been closed"
                raise WLEDConnectionClosedError(msg)

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket of a WLED device."""
        if not self._client or not self.connected:
            return

        await self._client.close()

    @backoff.on_exception(
        backoff.expo,
        (WLEDConnectionError, WLEDStatusError),
        max_tries=3,
        giveup=_is_not_retryable,
        logger=None,
    )
    async def request(
        self,
        uri: str = "",
        method: str = "GET",
        data: dict[str, Any] | None = None,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        """Handle a request to a WLED device.

        A generic method for sending/handling HTTP requests against
        the WLED device.

        Args:
        ----
            uri: Request URI, for example `/json/si`.
            method: HTTP method to use for the request. E.g., "GET" or "POST".
            data: Dictionary of data to send to the WLED device.
            params: Query parameters to add to the URL, for example
                `{"page": 1}`. A query string in `uri` won't work: it gets
                encoded as part of the path.

        Returns:
        -------
            A Python dictionary (JSON decoded) with the response from the
            WLED device.

        Raises:
        ------
            WLEDConnectionError: An error occurred while communicating with
                the WLED device.
            WLEDConnectionTimeoutError: A timeout occurred while communicating
                with the WLED device.
            WLEDError: Received an unexpected response from the WLED device.

        """
        url = URL.build(scheme="http", host=self.host, port=80, path=uri, query=params)

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
            # The timeout covers reading the response too: a device that drops
            # off the network halfway through shouldn't hang the request.
            async with (
                asyncio.timeout(self.request_timeout),
                self.session.request(
                    method,
                    url,
                    data=orjson.dumps(data) if data is not None else None,
                    headers=headers | {"Content-Type": "application/json"}
                    if data is not None
                    else headers,
                ) as response,
            ):
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                contents = await response.read()
        except TimeoutError as exception:
            msg = f"Timeout occurred while connecting to WLED device at {self.host}"
            raise WLEDConnectionTimeoutError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error occurred while communicating with WLED device at {self.host}"
            raise WLEDConnectionError(msg) from exception

        response_data = _decode_response(
            method, uri, status=status, content_type=content_type, contents=contents
        )

        if "application/json" in content_type and (
            method == "POST"
            and uri == "/json/state"
            and self._device is not None
            and data is not None
        ):
            self._device.update_from_dict(data={"state": response_data})

        return response_data

    @backoff.on_exception(
        backoff.expo,
        WLEDEmptyResponseError,
        max_tries=3,
        logger=None,
    )
    async def update(self) -> Device:
        """Get all information about the device in a single call.

        This method updates all WLED information available with a single API
        call.

        Returns
        -------
            WLED Device data.

        Raises
        ------
            WLEDEmptyResponseError: The WLED device returned an empty response.
            WLEDInvalidResponseError: The WLED device returned an invalid response.
            WLEDStatusError: The WLED device returned a 4xx/5xx HTTP status.

        """
        # Once the complete effects and palettes lists are cached, the state
        # and info are all that's needed; /json would send the lists along on
        # every update. Until then, its lists are the fallback.
        path = (
            "/json/si" if {"effects", "palettes"} <= self._catalog.keys() else "/json"
        )
        if not (data := await self.request(path)):
            msg = (
                f"WLED device at {self.host} returned an empty API"
                " response on full update"
            )
            raise WLEDEmptyResponseError(msg, method="GET", path=path)

        changed, new_version = self._check_presets_changed(data)
        if changed:
            if not (presets := await self.request("/presets.json")):
                msg = (
                    f"WLED device at {self.host} returned an empty API"
                    " response on presets update"
                )
                raise WLEDEmptyResponseError(msg, method="GET", path="/presets.json")
            data["presets"] = presets

        # On ESP8266 devices, /json can be cut off when it doesn't fit the
        # output buffer, losing part of the effects list and all palettes
        # (WLED issue #5674). The dedicated endpoints don't have that problem.
        catalog_changed, new_catalog_version = self._check_catalog_changed(data)
        if catalog_changed and not await self._fetch_catalog():
            # Try the missing list(s) again on the next update.
            new_catalog_version = None

        # Prefer the complete lists over the ones from /json, on every update.
        # Device rebuilds the custom and usermod palettes from the fresh info
        # each time it gets a palettes list, so those stay current as well.
        data.update(self._catalog)

        if not self._device:
            self._device = Device.from_dict(data)
        else:
            self._device.update_from_dict(data)

        self._presets_version = new_version
        self._catalog_version = new_catalog_version
        return self._device

    async def master(
        self,
        *,
        brightness: int | None = None,
        on: bool | None = None,
        transition: int | None = None,
    ) -> None:
        """Change master state of a WLED Light device.

        Args:
        ----
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
            state["tt"] = _transition(transition)

        await self.request("/json/state", method="POST", data=state)

    # pylint: disable-next=too-many-arguments,too-many-locals
    async def segment(  # noqa: PLR0913
        self,
        segment_id: int,
        *,
        brightness: int | None = None,
        clones: int | None = None,
        color_primary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        color_secondary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        color_tertiary: tuple[int, int, int, int] | tuple[int, int, int] | None = None,
        custom1: int | None = None,
        custom2: int | None = None,
        custom3: int | None = None,
        effect: int | str | None = None,
        freeze: bool | None = None,
        individual: Sequence[
            int | Sequence[int] | tuple[int, int, int, int] | tuple[int, int, int]
        ]
        | None = None,
        intensity: int | None = None,
        length: int | None = None,
        name: str | None = None,
        on: bool | None = None,
        option1: bool | None = None,
        option2: bool | None = None,
        option3: bool | None = None,
        palette: int | str | None = None,
        reverse: bool | None = None,
        selected: bool | None = None,
        speed: int | None = None,
        start: int | None = None,
        stop: int | None = None,
        transition: int | None = None,
        cct: int | None = None,
    ) -> None:
        """Change state of a WLED Light segment.

        Args:
        ----
            segment_id: The ID of the segment to adjust.
            brightness: The brightness of the segment, between 0 and 255.
            clones: Deprecated.
            color_primary: The primary color of this segment.
            color_secondary: The secondary color of this segment.
            color_tertiary: The tertiary color of this segment.
            custom1: Effect custom slider 1, between 0 and 255.
            custom2: Effect custom slider 2, between 0 and 255.
            custom3: Effect custom slider 3, between 0 and 31.
            effect: The effect number (or name) to use on this segment.
            freeze: Freeze the current segment state.
            individual: A list of colors to use for each LED in the segment.
            intensity: The effect intensity to use on this segment.
            length: The length of this segment.
            name: The name of the segment. Pass an empty string to clear the
                name. None leaves the name unchanged.
            on: A boolean, true to turn this segment on, false otherwise.
            option1: Effect option 1.
            option2: Effect option 2.
            option3: Effect option 3.
            palette: The palette number or name to use on this segment.
            reverse: Flips the segment, causing animations to change direction.
            selected: Selected segments will have their state (color/FX) updated
                by APIs that don't support segments.
            speed: The relative effect speed, between 0 and 255.
            start: LED the segment starts at.
            stop: LED the segment stops at, not included in range. If stop is
                set to a lower or equal value than start (setting to 0 is
                recommended), the segment is invalidated and deleted.
            transition: Duration of the crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.
            cct: White spectrum color temperature.

        Raises:
        ------
            WLEDError: Something went wrong setting the segment state.

        """
        update = SegmentUpdate(
            segment_id=segment_id,
            brightness=brightness,
            clones=clones,
            color_primary=color_primary,
            color_secondary=color_secondary,
            color_tertiary=color_tertiary,
            cct=cct,
            custom1=custom1,
            custom2=custom2,
            custom3=custom3,
            effect=effect,
            freeze=freeze,
            individual=individual,
            intensity=intensity,
            length=length,
            name=name,
            on=on,
            option1=option1,
            option2=option2,
            option3=option3,
            palette=palette,
            reverse=reverse,
            selected=selected,
            speed=speed,
            start=start,
            stop=stop,
        )
        await self.segments([update], transition=transition)

    async def segments(
        self,
        updates: Iterable[SegmentUpdate],
        *,
        transition: int | None = None,
    ) -> None:
        """Change the state of several WLED Light segments at once.

        All changes go to the device in a single request, so they take
        effect together, with one transition.

        Args:
        ----
            updates: The changes to apply, one per segment.
            transition: Duration of the crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.

        Raises:
        ------
            WLEDError: Something went wrong setting the segment state.

        """
        if self._device is None:
            await self.update()

        if self._device is None:
            msg = "Unable to communicate with WLED to get the current state"
            raise WLEDError(msg)

        state: dict[str, Any] = {}
        if segments := [
            segment
            for update in updates
            if (segment := self._segment_payload(self._device, update))
        ]:
            state["seg"] = segments

        if transition is not None:
            state["tt"] = _transition(transition)

        await self.request("/json/state", method="POST", data=state)

    @staticmethod
    def _segment_payload(device: Device, update: SegmentUpdate) -> dict[str, Any]:
        """Return the JSON API payload for one segment update.

        Returns an empty dict when the update doesn't change anything.
        """
        segment: dict[str, Any] = {
            "bri": update.brightness,
            "c1": update.custom1,
            "c2": update.custom2,
            "c3": update.custom3,
            "cln": update.clones,
            "frz": update.freeze,
            "fx": update.effect,
            "i": update.individual,
            "ix": update.intensity,
            "len": update.length,
            "n": update.name,
            "o1": update.option1,
            "o2": update.option2,
            "o3": update.option3,
            "on": update.on,
            "pal": update.palette,
            "rev": update.reverse,
            "sel": update.selected,
            "start": update.start,
            "stop": update.stop,
            "sx": update.speed,
            "cct": update.cct,
        }

        # Effects and palettes can be given by name; an unknown name is left
        # out rather than sent along.
        if isinstance(update.effect, str):
            segment["fx"] = next(
                (
                    item.effect_id
                    for item in device.effects.values()
                    if item.name.lower() == update.effect.lower()
                ),
                None,
            )
        if isinstance(update.palette, str):
            segment["pal"] = next(
                (
                    item.palette_id
                    for item in device.palettes.values()
                    if item.name.lower() == update.palette.lower()
                ),
                None,
            )

        segment = {key: value for key, value in segment.items() if value is not None}

        if colors := WLED._segment_colors(device, update):
            segment["col"] = colors

        if segment:
            segment["id"] = update.segment_id

        return segment

    @staticmethod
    def _segment_colors(device: Device, update: SegmentUpdate) -> list[ColorTuple]:
        """Return the color list for a segment update.

        WLED takes the colors as a list, so setting only a later one means
        the earlier ones have to be sent along; those come from the current
        state of the segment.
        """
        # A segment we don't know (yet) has no current colors to fall back on.
        segment = device.state.segments.get(update.segment_id)
        current = segment.color if segment else None

        colors: list[ColorTuple] = []
        if update.color_primary is not None:
            colors.append(update.color_primary)
        elif update.color_secondary is not None or update.color_tertiary is not None:
            colors.append(current.primary if current else (0, 0, 0))

        if update.color_secondary is not None:
            colors.append(update.color_secondary)
        elif update.color_tertiary is not None:
            colors.append(
                current.secondary if current and current.secondary else (0, 0, 0)
            )

        if update.color_tertiary is not None:
            colors.append(update.color_tertiary)

        return colors

    async def transition(self, transition: int) -> None:
        """Set the default transition time for manual control.

        Args:
        ----
            transition: Duration of the default crossfade between different
                colors/brightness levels. One unit is 100ms, so a value of 4
                results in a transition of 400ms.

        """
        await self.request(
            "/json/state",
            method="POST",
            data={"transition": _transition(transition)},
        )

    async def preset(self, preset: int | str | Preset) -> None:
        """Set a preset on a WLED device.

        Args:
        ----
            preset: The preset to activate on this WLED device.

        """
        if isinstance(preset, Preset):
            preset = preset.preset_id
        elif isinstance(preset, str):
            presets = self._device.presets.values() if self._device else ()
            preset = _resolve_by_name(
                preset, {item.name: item.preset_id for item in presets}, "preset"
            )

        await self.request("/json/state", method="POST", data={"ps": preset})

    async def playlist(self, playlist: int | str | Playlist) -> None:
        """Set a playlist on a WLED device.

        Args:
        ----
            playlist: The playlist to activate on this WLED device.

        """
        if isinstance(playlist, Playlist):
            playlist = playlist.playlist_id
        elif isinstance(playlist, str):
            playlists = self._device.playlists.values() if self._device else ()
            playlist = _resolve_by_name(
                playlist,
                {item.name: item.playlist_id for item in playlists},
                "playlist",
            )

        await self.request("/json/state", method="POST", data={"ps": playlist})

    async def live(self, live: LiveDataOverride) -> None:
        """Set the live override mode on a WLED device.

        Args:
        ----
            live: The live override mode to set on this WLED device.

        """
        await self.request("/json/state", method="POST", data={"lor": live.value})

    async def sync(
        self,
        *,
        send: bool | None = None,
        receive: bool | None = None,
        send_groups: SyncGroup | None = None,
        receive_groups: SyncGroup | None = None,
    ) -> None:
        """Set the sync status of the WLED device.

        Args:
        ----
            send: Send WLED broadcast (UDP sync) packet on state change.
            receive: Receive broadcast packets. Since WLED 0.15, receiving is
                on when there are receive groups, so turning it on keeps the
                current receive groups, or uses the send groups if there are
                none (falling back to group 1), and turning it off clears them.
            send_groups: Groups to send WLED broadcast packets to.
            receive_groups: Groups to receive WLED broadcast packets from.
                Takes precedence over receive.

        """
        sync: dict[str, bool | int] = {}
        if send is not None:
            sync["send"] = send
        if send_groups is not None:
            sync["sgrp"] = int(send_groups)
        if receive_groups is not None:
            sync["rgrp"] = int(receive_groups)
        elif receive is not None:
            sync |= await self._sync_receive(receive=receive, send_groups=send_groups)

        await self.request("/json/state", method="POST", data={"udpn": sync})

    async def _sync_receive(
        self, *, receive: bool, send_groups: SyncGroup | None
    ) -> dict[str, bool | int]:
        """Return what turns receiving sync on or off for this device.

        The send groups are the ones being set along with this change, if any;
        those are the ones to receive from when there are no receive groups.
        """
        if self._device is None:
            await self.update()

        device = self._device
        version = device.info.version if device else None
        if (
            device is None
            or version is None
            or get_awesome_version(f"{version.major}.{version.minor}.{version.patch}")
            < SYNC_RECEIVE_BY_GROUPS_VERSION
        ):
            return {"recv": receive}

        if not receive:
            return {"rgrp": 0}

        sync = device.state.sync
        groups = (
            sync.receive_groups or send_groups or sync.send_groups or SyncGroup.GROUP1
        )
        return {"rgrp": int(groups)}

    async def nightlight(
        self,
        *,
        duration: int | None = None,
        fade: bool | None = None,
        mode: NightlightMode | None = None,
        on: bool | None = None,
        target_brightness: int | None = None,
    ) -> None:
        """Control the nightlight function of a WLED device.

        Args:
        ----
            duration: Duration of nightlight in minutes.
            fade: If true, the light will gradually dim over the course of the
                nightlight duration. If false, it will instantly turn to the
                target brightness once the duration has elapsed. A shorthand
                for the fade and instant modes; mode takes precedence.
            mode: How the light gets to the target brightness: instantly,
                fading, fading the color too, or as a sunrise.
            on: A boolean, true to turn the nightlight on, false otherwise.
            target_brightness: Target brightness of nightlight, between 0 and 255.

        """
        # WLED has no "fade" setting; fading is one of the nightlight modes.
        if mode is None and fade is not None:
            mode = NightlightMode.FADE if fade else NightlightMode.INSTANT

        nightlight = {
            "dur": duration,
            "mode": mode,
            "on": on,
            "tbri": target_brightness,
        }

        # Filter out not set values
        nightlight = {k: v for k, v in nightlight.items() if v is not None}
        await self.request("/json/state", method="POST", data={"nl": nightlight})

    async def audio_reactive(self, *, on: bool) -> None:
        """Control the AudioReactive usermod of a WLED device.

        Args:
        ----
            on: A boolean, true to enable the AudioReactive usermod,
                false otherwise.

        """
        # The AudioReactive usermod reports its state in the `on` field,
        # but accepts state changes in the `enabled` field.
        await self.request(
            "/json/state",
            method="POST",
            data={"AudioReactive": {"enabled": on}},
        )

    async def upgrade(
        self,
        *,
        version: str | AwesomeVersion,
        repo: str | None = None,
    ) -> None:
        """Upgrade WLED device to the specified version.

        Args:
        ----
            version: The version to upgrade to.
            repo: GitHub repository to download firmware from. If not specified,
                the repository reported by the device firmware is used.

        Raises:
        ------
            WLEDUpgradeError: If the upgrade has failed.
            WLEDConnectionTimeoutError: When a connection timeout occurs.
            WLEDConnectionError: When a connection error occurs.

        """
        if self._device is None:
            await self.update()

        if self.session is None or self._device is None:
            msg = "Unexpected upgrade error; No session or device"
            raise WLEDUpgradeError(msg)

        if self._device.info.architecture not in {
            "esp01",
            "esp02",
            "esp32",
            "esp8266",
            "esp32-c3",
            "esp32-s2",
            "esp32-s3",
        }:
            msg = (
                "Upgrade is only supported on ESP01, ESP02, ESP32, ESP8266, "
                "ESP32-C3, ESP32-S2, and ESP32-S3 devices"
            )
            raise WLEDUpgradeError(msg)

        if not self._device.info.version:
            msg = "Current version is unknown, cannot perform upgrade"
            raise WLEDUpgradeError(msg)

        if self._device.info.version == version:
            msg = "Device already running the requested version"
            raise WLEDUpgradeError(msg)

        repo = _firmware_repo(repo, self._device.info)
        version = _firmware_version(version)

        session = self.session
        asset = await self._find_firmware_asset(
            session, repo, version, self._device.info
        )
        firmware = await self._download_firmware(session, repo, version, asset)
        await self._upload_firmware(session, asset.name, firmware)

    async def _find_firmware_asset(
        self, session: aiohttp.ClientSession, repo: str, version: str, info: Info
    ) -> _FirmwareAsset:
        """Pick the firmware file for this device from the GitHub release.

        When the release can't be looked up (GitHub API down or rate
        limited), fall back to the file name we expect, without a digest to
        verify it against. The download then tells whether it exists.
        """
        expected = _firmware_file_name(info, version)
        assets = await self._fetch_release_assets(session, repo, version)
        if assets is None:
            return _FirmwareAsset(expected)

        if expected not in assets and info.release is not None:
            # Forks don't always prefix their files with the brand the device
            # reports, so settle for the one file matching version and release.
            suffix = expected.removeprefix(info.brand)
            matches = [name for name in assets if name.endswith(suffix)]
            if len(matches) == 1:
                expected = matches[0]

        if expected not in assets:
            msg = f"Requested firmware file {expected} does not exist"
            raise WLEDUpgradeError(msg)

        digest = _SHA256_DIGEST.fullmatch(str(assets[expected].get("digest")))
        return _FirmwareAsset(expected, digest.group(1) if digest else None)

    async def _fetch_release_assets(
        self, session: aiohttp.ClientSession, repo: str, version: str
    ) -> dict[str, dict[str, Any]] | None:
        """Return the assets of a GitHub release by name, if GitHub tells us."""
        url = URL.build(
            scheme="https",
            host="api.github.com",
            path=f"/repos/{repo}/releases/tags/v{version}",
        )
        try:
            async with (
                asyncio.timeout(self.request_timeout),
                session.get(
                    url, headers={"Accept": "application/vnd.github+json"}
                ) as response,
            ):
                if response.status == 404:
                    msg = f"WLED version {version} does not exist in {repo}"
                    raise WLEDUpgradeError(msg)
                if response.status != 200:
                    return None
                release = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, socket.gaierror, ValueError):
            return None

        assets = release.get("assets") if isinstance(release, dict) else None
        if not isinstance(assets, list):
            return None

        return {
            asset["name"]: asset
            for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)
        }

    async def _download_firmware(
        self,
        session: aiohttp.ClientSession,
        repo: str,
        version: str,
        asset: _FirmwareAsset,
    ) -> bytes:
        """Download a firmware file, and verify it if GitHub gave a digest."""
        # Built from validated parts, never from a URL found in the metadata.
        url = URL.build(
            scheme="https",
            host="github.com",
            path=f"/{repo}/releases/download/v{version}/{asset.name}",
        )
        try:
            async with (
                asyncio.timeout(self.request_timeout * 10),
                session.get(url, raise_for_status=True) as response,
            ):
                firmware = await response.read()
        except TimeoutError as exception:
            msg = "Timeout occurred while downloading the firmware from GitHub"
            raise WLEDConnectionTimeoutError(msg) from exception
        except aiohttp.ClientResponseError as exception:
            if exception.status == 404:
                msg = f"Requested firmware file {asset.name} does not exist"
                raise WLEDUpgradeError(msg) from exception
            msg = f"Could not download requested WLED version '{version}' from {url}"
            raise WLEDUpgradeError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = "Error occurred while downloading the firmware from GitHub"
            raise WLEDConnectionError(msg) from exception

        if asset.sha256 and hashlib.sha256(firmware).hexdigest() != asset.sha256:
            msg = (
                f"Firmware file {asset.name} does not match the digest GitHub"
                " published for it; refusing to install it"
            )
            raise WLEDUpgradeError(msg)

        return firmware

    async def _upload_firmware(
        self, session: aiohttp.ClientSession, file_name: str, firmware: bytes
    ) -> None:
        """Upload a firmware file to the device, and check it got accepted."""
        url = URL.build(scheme="http", host=self.host, port=80, path="/update")
        form = aiohttp.FormData()
        form.add_field("file", firmware, filename=file_name)
        try:
            async with (
                asyncio.timeout(self.request_timeout * 10),
                session.post(url, data=form) as response,
            ):
                status = response.status
                page = await response.text(errors="replace")
        except TimeoutError as exception:
            msg = f"Timeout occurred while uploading the firmware to {self.host}"
            raise WLEDConnectionTimeoutError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error occurred while uploading the firmware to {self.host}"
            raise WLEDConnectionError(msg) from exception

        _verify_upload_accepted(status, page)

    async def reset(self) -> None:
        """Reboot WLED device."""
        await self.request("/reset")

    async def close(self) -> None:
        """Close open client (WebSocket) session."""
        await self.disconnect()
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The WLED object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exception info.

        """
        await self.close()

    def _check_presets_changed(
        self, data: dict[str, Any]
    ) -> tuple[bool, _PresetsVersion | None]:
        """Check if presets have changed since the last check.

        Compares the preset modification timestamp (pmt) and approximate
        boot time to detect changes. Boot time tracking is needed because
        pmt is stored in volatile memory and resets to 0 on device restart.

        Returns
        -------
            A tuple of (changed, new_version). If the version cannot be
            determined from the data, returns (True, None) to trigger a
            safe refetch.

        """
        if not isinstance(data, dict) or "info" not in data:
            # No info in message (e.g. state-only WebSocket update),
            # presets can't have changed.
            return (False, self._presets_version)

        info = data["info"]
        # A pmt of 0 is a valid version: the device reports 0 until it saves
        # a preset or learns the time, which without NTP may never happen.
        if (
            (uptime := info.get("uptime")) is None
            or not isinstance(fs := info.get("fs"), dict)
            or (pmt := fs.get("pmt")) is None
        ):
            return (True, None)

        try:
            new_version = _PresetsVersion(
                modified_timestamp=int(pmt),
                boot_time=int(time.time()) - int(uptime),
            )
        except (ValueError, TypeError):
            return (True, None)

        if self._presets_version is None:
            return (True, new_version)

        changed = (
            self._presets_version.modified_timestamp != new_version.modified_timestamp
            or abs(self._presets_version.boot_time - new_version.boot_time) > 2
        )
        return (changed, new_version)

    def _check_catalog_changed(
        self, data: dict[str, Any]
    ) -> tuple[bool, _CatalogVersion | None]:
        """Check if the effects or palettes lists have changed.

        Compares the effect and built-in palette counts, and the approximate
        boot time. A shift in boot time of more than 2 seconds means the
        device restarted, which can come with a firmware update and thus new
        effects or palettes. Custom and usermod palettes don't need tracking:
        those are rebuilt from the device info on every update.

        Returns
        -------
            A tuple of (changed, new_version). If the version cannot be
            determined from the data, returns (True, None) to trigger a
            safe refetch.

        """
        info = data.get("info") if isinstance(data, dict) else None
        if not isinstance(info, dict):
            return (True, None)

        try:
            new_version = _CatalogVersion(
                effect_count=int(info["fxcount"]),
                palette_count=int(info["palcount"]),
                boot_time=int(time.time()) - int(info["uptime"]),
            )
        except (KeyError, TypeError, ValueError):
            return (True, None)

        if self._catalog_version is None:
            return (True, new_version)

        changed = (
            self._catalog_version.effect_count != new_version.effect_count
            or self._catalog_version.palette_count != new_version.palette_count
            or abs(self._catalog_version.boot_time - new_version.boot_time) > 2
        )
        return (changed, new_version)

    async def _fetch_catalog(self) -> bool:
        """Fetch the complete effects, palettes, and effect metadata lists.

        Each list is fetched on its own, so one failing endpoint doesn't
        throw away the others. When the device answers with an error or
        something unexpected, the previously cached list (if any) is kept.
        A connection error still propagates: if the device is gone, the
        update should fail.

        Returns
        -------
            True if all lists were fetched, False if any needs a retry.

        """
        complete = True
        for key in ("effects", "palettes", "fxdata"):
            try:
                value = await self.request(f"/json/{key}")
            except WLEDConnectionError:
                raise
            except WLEDError:
                complete = False
                continue

            # Some less capable devices have no palettes and return `null`,
            # which Device already knows how to handle.
            if isinstance(value, list) or (key == "palettes" and value is None):
                self._catalog[key] = value
            else:
                complete = False

        return complete


@dataclass
class WLEDReleases:
    """Get version information for WLED."""

    repo: str = DEFAULT_REPO
    request_timeout: float = 8.0
    session: aiohttp.client.ClientSession | None = None

    _client: aiohttp.ClientWebSocketResponse | None = None
    _close_session: bool = False

    @backoff.on_exception(backoff.expo, WLEDConnectionError, max_tries=3, logger=None)
    async def releases(self) -> Releases:  # noqa: PLR0912  # pylint: disable=too-many-branches
        """Fetch WLED version information from GitHub.

        Returns
        -------
            A dictionary of WLED versions, with the key being the version type.

        Raises
        ------
            WLEDConnectionTimeoutError: Timeout occurred while fetching WLED
                version information from GitHub.
            WLEDConnectionError: Error occurred while communicating with
                GitHub for WLED version information.
            WLEDError: Didn't get a JSON response from GitHub while retrieving
                version information.

        """
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                response = await self.session.get(
                    f"https://api.github.com/repos/{self.repo}/releases",
                    headers={"Accept": "application/json"},
                )
        except TimeoutError as exception:
            msg = (
                "Timeout occurred while fetching WLED releases information from GitHub"
            )
            raise WLEDConnectionTimeoutError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = "Error occurred while communicating with GitHub for WLED releases"
            raise WLEDConnectionError(msg) from exception

        content_type = response.headers.get("Content-Type", "")
        contents = await response.read()
        if response.status // 100 in [4, 5]:
            response.close()

            if content_type == "application/json":
                raise WLEDError(response.status, orjson.loads(contents))
            raise WLEDError(response.status, {"message": contents.decode("utf8")})

        if "application/json" not in content_type:
            msg = "No JSON response from GitHub while retrieving WLED releases"
            raise WLEDError(msg)

        releases = orjson.loads(contents)
        version_stable = None
        version_beta = None
        version_nightly = None
        for release in releases:
            tag = release["tag_name"]

            # Nightly release uses a fixed "nightly" tag with the version
            # embedded in the asset filenames (e.g. WLED_17.0.0-dev_ESP32.bin).
            # The publish date is appended to distinguish daily builds.
            if tag == "nightly" and version_nightly is None:
                for asset in release.get("assets", []):
                    if match := re.search(r"WLED_(.+?)_", asset.get("name", "")):
                        version_nightly = match.group(1)
                        break
                if version_nightly and (published := release.get("published_at", "")):
                    version_nightly += published[:10].replace("-", "")
                continue

            if (
                release["prerelease"] is False
                and "b" not in tag.lower()
                and version_stable is None
            ):
                version_stable = tag.lstrip("vV")
            if (
                release["prerelease"] is True or "b" in tag.lower()
            ) and version_beta is None:
                version_beta = tag.lstrip("vV")

            if version_stable is not None and version_beta is not None:
                break

        return Releases.from_dict(
            {
                "beta": version_beta or "",
                "nightly": version_nightly or "",
                "repo": self.repo,
                "stable": version_stable or "",
            }
        )

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The WLEDReleases object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exception info.

        """
        await self.close()
