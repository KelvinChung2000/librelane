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

import typer

from ..flows import Flow
from ..logging import console
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
    if target_flow := Flow.factory.get(step_or_flow):
        target_flow.display_help()
    elif target_step := Step.factory.get(step_or_flow):
        target_step.display_help()
    else:
        console.log(f"Unknown Flow or Step '{step_or_flow}'.")
        raise typer.Exit(-1)


if __name__ == "__main__":
    cli()
