# Version fixtures

This directory contains API response fixtures for successive WLED releases.

## Purpose

Make it easy to compare which API fields are present across different WLED versions — e.g. when a new field was introduced, an old one was removed, or the response structure changed.

This directory also serves as a single reference point for raw API responses, making it easier to diagnose cross-version compatibility issues. Even fields that are not currently used by the library may prove valuable in the future, so full responses are captured rather than trimmed to what is needed today.

## File format

Each file corresponds to one WLED release and contains the response from the `/json` endpoint
(which combines `state`, `info`, `effects`, and `palettes` in a single request).

To capture a fixture for a device running a given version:

```bash
curl http://<device-ip>/json | python3 -m json.tool > tests/fixtures/versions/<version>.json
```

## Version selection criteria

- **Variant:** Plain (standard)
- **Excluded:** AudioReactive, Ethernet, and other special-purpose builds
- **Source:** [install.wled.me](https://install.wled.me) — the official WLED installer
- **Goal:** every available Plain stable release (pre-release and beta versions are excluded)
