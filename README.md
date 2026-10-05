# Python: WLED API Client

[![GitHub Release][releases-shield]][releases]
[![Python Versions][python-versions-shield]][pypi]
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE.md)

[![Build Status][build-shield]][build]
[![Code Coverage][codecov-shield]][codecov]
[![OpenSSF Scorecard][scorecard-shield]][scorecard]
[![Open in Dev Containers][devcontainer-shield]][devcontainer]

[![Sponsor Frenck via GitHub Sponsors][github-sponsors-shield]][github-sponsors]

[![Support Frenck on Patreon][patreon-shield]][patreon]

Asynchronous Python client for WLED.

## About

This package allows you to control and monitor [WLED][wled] devices
programmatically. It talks to the device's JSON API, can follow its state
live over a WebSocket, and can upgrade its firmware. It is the library behind
the WLED integration in [Home Assistant][home-assistant].

## Installation

```bash
pip install wled
```

To install with the optional CLI:

```bash
pip install "wled[cli]"
```

## CLI

The optional CLI lets you control WLED devices directly from the terminal.
The `--host` option can also be set with the `WLED_HOST` environment
variable, and the commands that show information take `--json` to print
machine-readable JSON instead of a table.

```bash
# Show device information
wled info --host wled-frenck.local

# Show the current state of the device and its segments
wled state --host wled-frenck.local

# Turn the light on or off, or set its brightness (0-255)
wled on --host wled-frenck.local
wled off --host wled-frenck.local
wled brightness --host wled-frenck.local --brightness 128

# List the effects, palettes, presets, and playlists on the device
wled effects --host wled-frenck.local
wled palettes --host wled-frenck.local
wled presets --host wled-frenck.local
wled playlists --host wled-frenck.local

# Activate a preset or playlist, by name or ID
wled preset --host wled-frenck.local --preset "Movie night"
wled playlist --host wled-frenck.local --playlist 1

# Show the latest WLED releases
wled releases

# Set the host once, and get JSON for scripting
export WLED_HOST=wled-frenck.local
wled state --json

# Upgrade the firmware, and restart the device
wled upgrade --host wled-frenck.local --version 0.15.3
wled reset --host wled-frenck.local

# Scan the network for WLED devices (uses mDNS/Zeroconf)
wled scan
```

## Usage

The client is an async context manager; every API call is a coroutine.
`update()` returns a `Device` with the info, state, effects, palettes,
presets, and playlists of the device. Later calls update that same object
in place, so you can hold on to it.

```python
import asyncio

from wled import WLED


async def main() -> None:
    """Show example of controlling your WLED device."""
    async with WLED("wled-frenck.local") as led:
        device = await led.update()
        print(device.info.version)

        # Turn the light on, at full brightness
        await led.master(on=True, brightness=255)


if __name__ == "__main__":
    asyncio.run(main())
```

### Light control

`master()` controls the light as a whole; `segment()` controls a single
segment. Effects and palettes can be given by name or by ID, and colors as
RGB or RGBW tuples. Transitions are in units of 100ms. Effects with more
settings than speed and intensity take `custom1` to `custom3` for their extra
sliders and `option1` to `option3` for their checkboxes.

```python
async with WLED("wled-frenck.local") as led:
    await led.update()

    # Dim the whole light over 2 seconds
    await led.master(brightness=64, transition=20)

    # Set the first segment to a red, fast "Rainbow" effect
    await led.segment(
        0,
        on=True,
        color_primary=(255, 0, 0),
        effect="Rainbow",
        palette="Party",
        speed=200,
    )

    # Activate a preset or a playlist, by name or ID
    await led.preset("Movie night")
    await led.playlist(1)
    await led.next_playlist_entry()
```

Each effect also tells which of those controls it uses, through
`effect.metadata`: its sliders and options with their labels, its color
slots, whether it uses a palette, needs a 2D matrix (see
`device.info.leds.matrix`), or reacts to sound. That's the information to
show only the controls that matter for the chosen effect. Segments do the
same for colors: `segment.light_capabilities` says whether the LEDs in it do
RGB, a white channel, or color temperature.

To change several segments at once, so they switch together with one
transition, pass a `SegmentUpdate` for each to `segments()`:

```python
from wled import SegmentUpdate

await led.segments(
    [
        SegmentUpdate(segment_id=0, effect="Rainbow"),
        SegmentUpdate(segment_id=1, color_primary=(0, 0, 255)),
    ],
    transition=10,
)
```

### Nightlight, sync, and usermods

```python
async with WLED("wled-frenck.local") as led:
    # Fade to a low brightness over 30 minutes
    await led.nightlight(on=True, duration=30, fade=True, target_brightness=5)

    # Send and receive UDP sync with other WLED devices
    await led.sync(send=True, receive=True)

    # Toggle the AudioReactive usermod, if the device has it
    device = await led.update()
    if device.state.audio_reactive is not None:
        await led.audio_reactive(on=not device.state.audio_reactive.on)
```

### Live updates

Instead of polling, you can follow the device over its WebSocket. The
callback receives the updated `Device` on every change.

```python
import asyncio

from wled import WLED, Device


async def main() -> None:
    """Show example of following a WLED device live."""
    async with WLED("wled-frenck.local") as led:
        await led.update()
        await led.connect()

        def on_update(device: Device) -> None:
            print(device.state.on, device.state.brightness)

        # Runs until the connection closes
        await led.listen(callback=on_update)


if __name__ == "__main__":
    asyncio.run(main())
```

### Firmware upgrades

`upgrade()` downloads the firmware from a GitHub release and uploads it to
the device. It checks the device's answer, and raises `WLEDUpgradeError` when
the device rejects the upload (for example, with OTA updates locked or from
outside its local subnet).

```python
from wled import WLED, WLEDReleases

async with WLED("wled-frenck.local") as led:
    device = await led.update()

    async with WLEDReleases(repo=device.info.repo) as wled_releases:
        releases = await wled_releases.releases()

    # Only move forward: a device on a newer beta or nightly stays put
    current = device.info.version
    if releases.stable and current and releases.stable > current:
        await led.upgrade(version=releases.stable)
```

By default, the firmware comes from the repository the device reports as
`device.info.repo`; older firmware that doesn't report one falls back to
`wled/WLED`. Pass `repo` to `upgrade()` to pick another one.

The release is looked up through the GitHub API, and the download is checked
against the SHA256 digest GitHub publishes for it; a firmware file that
doesn't match is never sent to the device. When GitHub's API can't be
reached (for example, when rate limited), the upgrade continues without that
check.

#### Publishing custom firmware

Vendors and integrators can distribute their own WLED builds through the same
upgrade flow. Compile the firmware with metadata for the repository, brand,
and release name, and attach it to a GitHub release, named after the WLED
convention:

```text
{brand}_{version}_{release}.bin
```

- `brand`: the brand the device reports in `device.info.brand` (`WLED` by
  default).
- `version`: the release tag without the leading `v`, like `0.15.0` for the
  tag `v0.15.0`.
- `release`: the release name the device reports in `device.info.release`,
  like `ESP32` or `ESP32_Ethernet`.

If your files keep the `WLED_` prefix while the device reports another brand,
that works too, as long as only one file in the release matches the version
and release name. The official [WLED releases][wled-releases] show the format
in practice.

### Error handling

Everything the library raises derives from `WLEDError`:

- `WLEDConnectionError`: the device couldn't be reached, with
  `WLEDConnectionTimeoutError` for timeouts and `WLEDConnectionClosedError`
  for a closed WebSocket.
- `WLEDStatusError`: the device answered with an HTTP error; `status` and
  `body` hold what it said.
- `WLEDResponseError`: the device answered, but with nothing usable
  (`WLEDEmptyResponseError`, `WLEDInvalidResponseError`).
- `WLEDUnsupportedVersionError`: the firmware is older than this library
  supports.
- `WLEDUpgradeError`: a firmware upgrade failed.

`WLEDStatusError` and `WLEDResponseError` also carry the `method` and `path`
of the request that failed.

```python
from wled import WLED, WLEDConnectionError, WLEDError

async with WLED("wled-frenck.local") as led:
    try:
        await led.update()
    except WLEDConnectionError:
        print("WLED is unreachable")
    except WLEDError as err:
        print(f"WLED had a problem: {err}")
```

## Changelog & Releases

This repository keeps a change log using [GitHub's releases][releases]
functionality.

Releases are based on [Semantic Versioning][semver], and use the format
of `MAJOR.MINOR.PATCH`. In a nutshell, the version will be incremented
based on the following:

- `MAJOR`: Incompatible or major changes.
- `MINOR`: Backwards-compatible new features and enhancements.
- `PATCH`: Backwards-compatible bugfixes and package updates.

## Contributing

This is an active open-source project. We are always open to people who want to
use the code or contribute to it.

We've set up a separate document for our
[contribution guidelines](.github/CONTRIBUTING.md).

Thank you for being involved! :heart_eyes:

## Setting up development environment

The easiest way to start is by opening a CodeSpace here on GitHub, or by using
the [Dev Container][devcontainer] feature of Visual Studio Code.

[![Open in Dev Containers][devcontainer-shield]][devcontainer]

This Python project is fully managed using the [Poetry][poetry] dependency
manager but also relies on the use of Node.js for certain checks during
development.

You need at least:

- Python 3.11+
- [Poetry][poetry-install]
- Node.js 24+ (including NPM)

To install all packages, including all development requirements:

```bash
npm install
poetry install --all-extras
```

As this repository uses the [prek][prek] framework, all changes
are linted and tested with each commit. You can run all checks and tests
manually, using the following command:

```bash
poetry run prek run --all-files
```

To run just the Python tests:

```bash
poetry run pytest
```

## Authors & contributors

The original setup of this repository is by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributors' page][contributors].

## License

MIT License

Copyright (c) 2019-2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[build-shield]: https://github.com/frenck/python-wled/actions/workflows/tests.yaml/badge.svg
[build]: https://github.com/frenck/python-wled/actions/workflows/tests.yaml
[codecov-shield]: https://codecov.io/gh/frenck/python-wled/branch/main/graph/badge.svg
[codecov]: https://codecov.io/gh/frenck/python-wled
[contributors]: https://github.com/frenck/python-wled/graphs/contributors
[devcontainer-shield]: https://img.shields.io/static/v1?label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode
[devcontainer]: https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/frenck/python-wled
[frenck]: https://github.com/frenck
[github-sponsors-shield]: https://frenck.dev/wp-content/uploads/2019/12/github_sponsor.png
[github-sponsors]: https://github.com/sponsors/frenck
[license-shield]: https://img.shields.io/github/license/frenck/python-wled.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[patreon-shield]: https://frenck.dev/wp-content/uploads/2019/12/patreon.png
[patreon]: https://www.patreon.com/frenck
[poetry-install]: https://python-poetry.org/docs/#installation
[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[project-stage-shield]: https://img.shields.io/badge/project%20stage-experimental-yellow.svg
[pypi]: https://pypi.org/project/wled/
[python-versions-shield]: https://img.shields.io/pypi/pyversions/wled
[releases-shield]: https://img.shields.io/github/release/frenck/python-wled.svg
[releases]: https://github.com/frenck/python-wled/releases
[scorecard]: https://scorecard.dev/viewer/?uri=github.com/frenck/python-wled
[scorecard-shield]: https://api.scorecard.dev/projects/github.com/frenck/python-wled/badge
[semver]: http://semver.org/spec/v2.0.0.html
[wled-releases]: https://github.com/wled/WLED/releases
[wled]: https://github.com/wled/WLED
[home-assistant]: https://www.home-assistant.io
