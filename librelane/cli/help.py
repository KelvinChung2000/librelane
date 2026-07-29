# Copyright 2025 LibreLane Contributors
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
from typing import Annotated

import rich.console
import rich.markdown
import typer

from ..flows import Flow
from ..steps import Step


cli = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)


@cli.command()
def main(
    step_or_flow: Annotated[
        str, typer.Argument(help="The registered step or flow ID to describe.")
    ],
) -> None:
    """Display detailed help for a registered step or flow."""
    # Steps and flows expose their help as Markdown via get_help_md(); rendering
    # it is this frontend's job, so the terminal presentation lives here rather
    # than in the library. Step.display_help()/Flow.display_help() remain for
    # notebook users, who need IPython rendering instead.
    if target_flow := Flow.factory.get(step_or_flow):
        help_md = target_flow.get_help_md()
    elif target_step := Step.factory.get(step_or_flow):
        help_md = target_step.get_help_md()
    else:
        typer.echo(f"Unknown Flow or Step '{step_or_flow}'.", err=True)
        raise typer.Exit(-1)

    rich.console.Console().print(rich.markdown.Markdown(help_md))


if __name__ == "__main__":
    cli()
