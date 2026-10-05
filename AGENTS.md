# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. This file
follows the [agents.md](https://agents.md) convention. `CLAUDE.md` is a symlink
to this file, so Claude-compatible tooling reads the same guidance.

## What this project is

python-wled is an asynchronous Python client for [WLED][wled], the firmware that
drives addressable LEDs on ESP8266 and ESP32 boards. It talks to the device's
JSON API over HTTP, can follow live state over a WebSocket, and can upgrade the
firmware from the official GitHub releases. It is the library behind the WLED
integration in Home Assistant.

One `WLED` instance maps to one device. `update()` returns a `Device` that is
kept and updated in place on later calls, so consumers can hold on to it. An
optional CLI ships under the `cli` extra.

## Project layout

| Path                       | Purpose                                                          |
| -------------------------- | ---------------------------------------------------------------- |
| `src/wled/`                | The package                                                      |
| `  wled.py`                | The `WLED` client (HTTP, WebSocket, upgrades) and `WLEDReleases` |
| `  models.py`              | mashumaro dataclasses for the device, state, and info            |
| `  const.py`               | Enums                                                            |
| `  exceptions.py`          | The `WLEDError` hierarchy                                        |
| `  cli/`                   | Optional Typer CLI                                               |
| `  _cli.py`                | Console script entry; install hint without the `cli` extra       |
| `tests/`                   | pytest suite with syrupy snapshots                               |
| `tests/cli/`               | Tests for the CLI                                                |
| `tests/fixtures/versions/` | One real `/json` dump per WLED release                           |
| `tests/fixtures/forks/`    | Real `/json` dumps from WLED forks, like WLED-MM                 |
| `examples/`                | Runnable examples                                                |

## Commands

This is a [Poetry][poetry] project that also uses NodeJS for some checks, with
[prek][prek] running the hooks. Set up and run the gate with:

```bash
npm install
poetry install --extras cli
poetry run prek run --all-files   # lint, format, type, and test hooks
poetry run pytest                 # just the tests
```

During iteration, running a single tool directly is fine and faster:
`poetry run pytest -k ...`, `poetry run ruff check .`, `poetry run ty check src`.
Update snapshots with `poetry run pytest --snapshot-update` and review the
diff before committing it.

## Conventions

- Network and protocol failures surface as `WLEDConnectionError` (or one of
  its subclasses). Bad or unexpected data surfaces as `WLEDError` or one of its
  subclasses. Do not let a raw `aiohttp` or `orjson` exception escape.
- Fields the device does not report decode to `None` or a sensible default.
  WLED adds and drops fields between releases; parsing an older or newer
  firmware must not crash.
- Coverage is enforced at 95%. New code needs tests.
- Every test carries a one-line docstring describing what it verifies.
- Comments explain the why, not the what. Clarity over cleverness, clear names,
  and blank lines between logical steps.

## Writing and voice

English for all public artifacts (commits, PRs, issues). Held to a high bar:
clear, honest, no filler. Avoid:

- AI cheerleading and marketing speak (leverage, synergize, delight).
- Em-dashes and en-dashes anywhere. Use a period, colon, comma, or parentheses;
  hyphen only for compound words. Restructure a sentence rather than reach for one.
- "e.g.", "i.e.", "etc."; write "like", "for example", "such as".
- CAPS for emphasis (use italics); "click" as a verb (use "select").
- "HA"/"HASS"; write "Home Assistant" in full, and never frame it as fragile.
- "master/slave"; use "client/server", "leader/follower", "main/replica".

See [AI_POLICY.md](AI_POLICY.md) for the contribution policy around AI tooling.

## Gotchas

- Presets are fetched separately from `/presets.json`, and only when the
  device signals they changed (modified timestamp or a reboot). `update()`
  carries the previous presets over otherwise.
- WLED 16.0.0 reorganized the palette ID space for custom palettes. The model
  handles both layouts based on the reported firmware version; keep it that way.
- Effects named `RSVD` are firmware placeholders and are filtered out.
- `update()` retries on an empty response, and `request()` retries on a
  connection error (via `python-backoff`). Keep retries out of the callers.
- When a new WLED release ships, add its `/json` dump under
  `tests/fixtures/versions/`. The snapshot tests then cover it automatically.

## Where to read next

- `README.md`: install, usage, and the development setup.
- `tests/test_models.py`: how each firmware version is parsed and snapshotted.

[poetry]: https://python-poetry.org
[prek]: https://github.com/j178/prek
[wled]: https://github.com/wled/WLED
