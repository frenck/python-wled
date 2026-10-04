"""Entry point shim for the optional WLED CLI.

Kept as a standalone module so the console script remains importable
regardless of whether the ``cli`` extra is installed: if the CLI
dependencies (``typer``, ``rich``, ``zeroconf``) are missing we raise a
friendly ``SystemExit`` with an install hint instead of a bare
``ImportError``.
"""

from __future__ import annotations

_CLI_EXTRA_MODULES = frozenset({"typer", "rich", "zeroconf"})


def main() -> None:
    """Invoke the Typer CLI with a graceful error if extras are missing."""
    try:
        # Deferred import so the console script remains importable even
        # when the optional ``cli`` extra is not installed.
        # pylint: disable-next=import-outside-toplevel
        from wled.cli import cli  # noqa: PLC0415
    except ModuleNotFoundError as err:
        # Only convert to a friendly install hint when the *optional* deps
        # are missing. Anything else (like a renamed internal module) must
        # still surface as a real error for debugging.
        missing_module: str = err.name or ""
        missing_root = missing_module.split(".", 1)[0]  # pylint: disable=no-member
        if missing_root not in _CLI_EXTRA_MODULES:
            raise

        msg = (
            "The WLED CLI requires the 'cli' extra. "
            "Install it with: pip install 'wled[cli]'"
        )
        raise SystemExit(msg) from err

    cli()
