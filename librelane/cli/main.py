# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane
#
# Copyright 2023 Efabless Corporation
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
The ``librelane`` command: one entry point, one subcommand per frontend.

This module only assembles the app. Each subcommand's options and behaviour
live in its own module, and each of those modules also exposes the group as a
standalone app so the deprecated console scripts in
:mod:`librelane.cli._deprecated` keep working.
"""

from textwrap import dedent

import typer

from librelane.__version__ import __version__
from librelane.plugins import discovered_plugins
from librelane.cli._app import DefaultToRunGroup, make_app
from librelane.cli.config import cli as config_cli
from librelane.cli.env_info import show_env_info
from librelane.cli.flow import cli as flow_cli
from librelane.cli.help import show_help
from librelane.cli.metrics import cli as metrics_cli
from librelane.cli.open_in import open_in
from librelane.cli.options import BareVersionOption, VersionOption
from librelane.cli.run import run
from librelane.cli.state import cli as state_cli
from librelane.cli.steps import cli as steps_cli


def version_message() -> str:
    return dedent(
        f"""
        LibreLane v{__version__}

        Copyright ©2025-2026 LibreLane Contributors

        Adapted from OpenLane 2.0
        Copyright ©2020-2025 Efabless Corporation

        Available under the Apache License, version 2. Included with the source code,
        but you can also get a copy at https://www.apache.org/licenses/LICENSE-2.0

        Included tools and utilities may be distributed under stricter licenses.
        """
    ).strip()


def print_version() -> None:
    typer.echo(version_message())

    if discovered_plugins:
        typer.echo("Discovered plugins:")
        for name, module in discovered_plugins.items():
            if hasattr(module, "__version__"):
                typer.echo(f"{name} -> {module.__version__}")
            else:
                typer.echo(name)


cli = make_app(
    cls=DefaultToRunGroup,
    # The root prints its own help for a bare invocation so the exit code stays
    # a usage error rather than a success.
    no_args_is_help=False,
    help=dedent(
        """
        The LibreLane hardening flow.

        Configuration files may be passed straight to [b]librelane[/b]:
        [b]librelane config.json[/b] is [b]librelane run config.json[/b].
        """
    ).strip(),
)


@cli.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: VersionOption = False,
    bare_version: BareVersionOption = False,
) -> None:
    if bare_version:
        typer.echo(__version__, nl=False)
        raise typer.Exit()
    if version:
        print_version()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(2)


cli.command("run", no_args_is_help=True)(run)
cli.command("open", no_args_is_help=True)(open_in)
cli.command("help")(show_help)
cli.command("env-info")(show_env_info)
cli.add_typer(steps_cli, name="steps")
cli.add_typer(config_cli, name="config")
cli.add_typer(state_cli, name="state")
cli.add_typer(metrics_cli, name="metrics")
cli.add_typer(flow_cli, name="flow")


if __name__ == "__main__":
    cli()
