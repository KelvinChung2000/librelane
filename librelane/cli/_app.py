# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The pieces every LibreLane frontend is built from.

This module holds no commands. It exists so the six command groups share one
Typer configuration instead of six copies of the same constructor call, and so
the root app's "bare config file means run" dispatch lives in exactly one place.
"""

from typing import TYPE_CHECKING, Any

import typer
from typer.core import TyperGroup


if TYPE_CHECKING:
    # Typer 0.27 vendors Click, and TyperGroup.parse_args is typed against the
    # vendored Context rather than click.Context. Typer re-exports no public
    # alias for it (typer.Context is a different, command-signature type), so
    # the annotation below is quoted and this import never runs.
    from typer._click.core import Context


# Arguments the root group handles itself. Everything else that is not the name
# of a subcommand belongs to `run`, so these must not be rewritten into it.
ROOT_FLAGS = frozenset({"-h", "--help", "--version", "--bare-version"})

DEFAULT_COMMAND = "run"


class DefaultToRunGroup(TyperGroup):
    """
    A group that reads ``librelane <config.json>`` as ``librelane run <config.json>``.

    LibreLane's original command line took configuration files as bare
    positional arguments, and every reproducible, container re-entry, CI job and
    documented invocation still spells it that way. A plain Typer group would
    reject those, so the first argument is inspected: if it names a subcommand
    or is one of :data:`ROOT_FLAGS`, it is dispatched normally, and otherwise
    ``run`` is inserted ahead of it.

    The one ambiguity is a configuration file or design directory whose name is
    exactly that of a subcommand. ``librelane run run`` disambiguates it.
    """

    def parse_args(self, ctx: "Context", args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and args[0] not in ROOT_FLAGS:
            args = [DEFAULT_COMMAND, *args]
        return super().parse_args(ctx, args)


def make_app(help: str | None = None, **kwargs: Any) -> typer.Typer:
    """Build a Typer app with the settings every LibreLane frontend shares."""
    settings: dict[str, Any] = {
        "add_completion": False,
        "no_args_is_help": True,
        "pretty_exceptions_enable": False,
        "rich_markup_mode": "rich",
        "context_settings": {"help_option_names": ["-h", "--help"]},
        "help": help,
    }
    settings.update(kwargs)
    return typer.Typer(**settings)


def make_group(help: str | None = None, **kwargs: Any) -> typer.Typer:
    """
    Build an app that stays a command group even when it holds one command.

    Typer folds a single-command app into that command, which would quietly
    turn ``librelane.state latest RUN_DIR`` into ``librelane.state RUN_DIR``
    and read "latest" as the run directory. Registering a callback pins the
    group open, so a group with one command today survives gaining a second.
    """
    app = make_app(help=help, **kwargs)
    app.callback()(lambda: None)
    return app
