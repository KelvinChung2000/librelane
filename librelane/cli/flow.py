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
"""The ``librelane flow`` subcommand group."""

import json
from pathlib import Path
from typing import Annotated

import typer

from librelane.cli._app import make_group
from librelane.flows.spec_schema import workflow_document_schema


cli = make_group(help="Author LibreLane workflow documents.")


@cli.command()
def schema(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            writable=True,
            help="Write the schema to this file instead of the standard output.",
        ),
    ] = None,
) -> None:
    """
    Print the JSON Schema for a workflow document.

    The schema describes the document surface as this installation sees it: the
    step ids and jobs it enumerates are the ones registered here, plugins
    included. Point an editor at the written file to get completion and
    validation while writing a document.
    """
    document = json.dumps(workflow_document_schema(), indent=2) + "\n"
    if output is None:
        typer.echo(document, nl=False)
        return
    output.write_text(document, encoding="utf8")
    typer.echo(f"Wrote the workflow document schema to '{output}'.")


if __name__ == "__main__":
    cli()
