"""Asynchronous Python client for WLED.

Adaptation of the snippet/code from:
- https://github.com/tiangolo/typer/issues/88#issuecomment-1613013597
- https://github.com/argilla-io/argilla/blob/e77ca86c629a492019f230ac55ebde207b280xc9c/src/argilla/cli/typer_ext.py
"""

#  Copyright 2021-present, the Recognai S.L. team.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from __future__ import annotations

import asyncio
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    ParamSpec,
    TypeVar,
)

from typer import Exit
from typer import Typer as SyncTyper

if TYPE_CHECKING:
    from typer.core import TyperCommand, TyperGroup

_P = ParamSpec("_P")
_R = TypeVar("_R")

HandleErrorFunc = Callable[[Any], None]


class AsyncTyper(SyncTyper):
    """A Typer subclass that supports async."""

    error_handlers: dict[type[Exception], HandleErrorFunc]

    # pylint: disable-next=too-many-arguments, too-many-locals
    def callback(  # type: ignore[override] # noqa: PLR0913
        self,
        name: str | None = None,
        *,
        cls: type[TyperGroup] | None = None,
        invoke_without_command: bool = False,
        no_args_is_help: bool = False,
        subcommand_metavar: str | None = None,
        chain: bool = False,
        result_callback: Callable[..., Any] | None = None,
        context_settings: dict[Any, Any] | None = None,
        # pylint: disable-next=redefined-builtin
        help: str | None = None,  # noqa: A002
        epilog: str | None = None,
        short_help: str | None = None,
        options_metavar: str = "[OPTIONS]",
        add_help_option: bool = True,
        hidden: bool = False,
        deprecated: bool = False,
        rich_help_panel: str | None = None,
    ) -> Callable[
        [Callable[_P, Coroutine[Any, Any, _R]]],
        Callable[_P, Coroutine[Any, Any, _R]],
    ]:
        """Create a new typer callback."""
        super_callback = super().callback(
            name,
            cls=cls,
            invoke_without_command=invoke_without_command,
            no_args_is_help=no_args_is_help,
            subcommand_metavar=subcommand_metavar,
            chain=chain,
            result_callback=result_callback,
            context_settings=context_settings,
            help=help,
            epilog=epilog,
            short_help=short_help,
            options_metavar=options_metavar,
            add_help_option=add_help_option,
            hidden=hidden,
            deprecated=deprecated,
            rich_help_panel=rich_help_panel,
        )

        def decorator(
            func: Callable[_P, Coroutine[Any, Any, _R]],
        ) -> Callable[_P, Coroutine[Any, Any, _R]]:
            if asyncio.iscoroutinefunction(func):

                @wraps(func)
                def sync_func(*_args: _P.args, **_kwargs: _P.kwargs) -> _R:
                    return asyncio.run(func(*_args, **_kwargs))

                super_callback(sync_func)
            else:
                super_callback(func)

            return func

        return decorator

    # pylint: disable-next=too-many-arguments
    def command(  # type: ignore[override] # noqa: PLR0913
        self,
        name: str | None = None,
        *,
        cls: type[TyperCommand] | None = None,
        context_settings: dict[Any, Any] | None = None,
        # pylint: disable-next=redefined-builtin
        help: str | None = None,  # noqa: A002
        epilog: str | None = None,
        short_help: str | None = None,
        options_metavar: str = "[OPTIONS]",
        add_help_option: bool = True,
        no_args_is_help: bool = False,
        hidden: bool = False,
        deprecated: bool = False,
        # Rich settings
        rich_help_panel: str | None = None,
    ) -> Callable[
        [Callable[_P, Coroutine[Any, Any, _R]]],
        Callable[_P, Coroutine[Any, Any, _R]],
    ]:
        """Create a new typer command."""
        super_command = super().command(
            name,
            cls=cls,
            context_settings=context_settings,
            help=help,
            epilog=epilog,
            short_help=short_help,
            options_metavar=options_metavar,
            add_help_option=add_help_option,
            no_args_is_help=no_args_is_help,
            hidden=hidden,
            deprecated=deprecated,
            rich_help_panel=rich_help_panel,
        )

        def decorator(
            func: Callable[_P, Coroutine[Any, Any, _R]],
        ) -> Callable[_P, Coroutine[Any, Any, _R]]:
            if asyncio.iscoroutinefunction(func):

                @wraps(func)
                def sync_func(*_args: _P.args, **_kwargs: _P.kwargs) -> _R:
                    return asyncio.run(func(*_args, **_kwargs))

                super_command(sync_func)
            else:
                super_command(func)

            return func

        return decorator

    def error_handler(self, exc: type[Exception]) -> Callable[[HandleErrorFunc], None]:
        """Register an error handler for a given exception."""
        if not hasattr(self, "error_handlers"):
            self.error_handlers = {}

        def decorator(func: HandleErrorFunc) -> None:
            self.error_handlers[exc] = func

        return decorator

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the typer app."""
        try:
            return super().__call__(*args, **kwargs)
        except Exit:
            raise
        # pylint: disable-next=broad-except
        except Exception as e:
            if (
                not hasattr(self, "error_handlers")
                or (handler := self.error_handlers.get(type(e))) is None
            ):
                raise
            return handler(e)
