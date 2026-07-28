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
import json
from pathlib import Path
from typing import Annotated

import typer

from ..common import get_latest_file


cli = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)


@cli.callback()
def state_cli() -> None:
    """Inspect state files produced by LibreLane runs."""


@cli.command()
def latest(
    run_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="A LibreLane run directory.",
        ),
    ],
    extract_metrics_to: Annotated[
        Path | None,
        typer.Option(
            "--extract-metrics-to",
            file_okay=True,
            dir_okay=False,
            help="Also write the latest state's metrics to this JSON file.",
        ),
    ] = None,
) -> None:
    """Print the path to the latest state in a run directory."""
    if latest_state := get_latest_file(str(run_dir), "state_*.json"):
        try:
            with open(latest_state, encoding="utf8") as state_file:
                state = json.load(state_file)
        except json.JSONDecodeError as error:
            typer.echo(
                f"Latest state at {latest_state} is invalid: {error}",
                err=True,
            )
            raise typer.Exit(1) from error

        typer.echo(latest_state, nl=False)
        if extract_metrics_to is not None:
            with extract_metrics_to.open("w", encoding="utf8") as output:
                json.dump(state["metrics"], output)
        return

    typer.echo("No state_*.json files found", err=True)
    raise typer.Exit(1)


if __name__ == "__main__":
    cli()
