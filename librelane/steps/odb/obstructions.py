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
from loguru import logger

from importlib.resources import files
from decimal import Decimal
from typing import ClassVar

from librelane.config import variable
from librelane.state import State

from librelane.steps.step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from librelane.steps.odb.base import OdbpyStep


class ObstructionStep(OdbpyStep):
    """
    Draws or erases obstructions listed by one configuration variable.

    Routing and PDN obstructions are the same operation over different
    variables, so the variable is named by the subclass rather than declared
    here: a subclass that declared both would accept a value for the one it
    does not read.
    """

    obstruction_variable: ClassVar[str] = NotImplemented

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "defutil.py")

    def get_command(self) -> list[str]:
        command = super().get_command()
        if obstructions := self.config[self.obstruction_variable]:
            for obstruction in obstructions:
                command.append("--obstructions")
                command.append(" ".join([str(o) for o in obstruction]))
        return command

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config[self.obstruction_variable] is None:
            logger.info(
                f"'{self.obstruction_variable}' is not defined. Skipping '{self.id}'…"
            )
            return {}, {}
        return super().run(state_in, **kwargs)


@Step.factory.register()
class AddRoutingObstructions(ObstructionStep):
    """
    Adds obstructions on metal layers which prevent shapes from being created in
    the designated areas.
    """

    id = "Odb.AddRoutingObstructions"
    name = "Add Obstructions"
    obstruction_variable = "ROUTING_OBSTRUCTIONS"

    class Config(ObstructionStep.Config):
        ROUTING_OBSTRUCTIONS: (
            list[tuple[str, Decimal, Decimal, Decimal, Decimal]] | None
        ) = variable(
            None,
            description="Add routing obstructions to the design. If set to `None`, this step is skipped."
            + " Format of each obstruction item is a tuple of: layer name, llx, lly, urx, ury.",
            units="µm",
        )

    config: Config

    def get_subcommand(self) -> list[str]:
        return ["add_obstructions"]


@Step.factory.register()
class RemoveRoutingObstructions(AddRoutingObstructions):
    """
    Removes any routing obstructions previously placed by
    <#Odb.AddRoutingObstructions>`_.
    """

    id = "Odb.RemoveRoutingObstructions"
    name = "Remove Obstructions"

    def get_subcommand(self) -> list[str]:
        return ["remove_obstructions"]


@Step.factory.register()
class AddPDNObstructions(ObstructionStep):
    """
    Adds obstructions on metal layers which prevent shapes from being created in
    the designated areas.

    A soft-duplicate of <#Odb.AddRoutingObstructions>`_ , though this one uses
    a different variable name so the obstructions can be restricted for PDN
    steps only.
    """

    id = "Odb.AddPDNObstructions"
    name = "Add PDN obstructions"
    obstruction_variable = "PDN_OBSTRUCTIONS"

    class Config(ObstructionStep.Config):
        PDN_OBSTRUCTIONS: (
            list[tuple[str, Decimal, Decimal, Decimal, Decimal]] | None
        ) = variable(
            None,
            description="Add routing obstructions to the design before PDN stage. If set to `None`, this step is skipped."
            + " Format of each obstruction item is a tuple of: layer name, llx, lly, urx, ury,.",
            units="µm",
        )

    config: Config

    def get_subcommand(self) -> list[str]:
        return ["add_obstructions"]


@Step.factory.register()
class RemovePDNObstructions(AddPDNObstructions):
    """
    Removes any PDN obstructions previously placed by
    <#Odb.RemovePDNObstructions>`_.
    """

    id = "Odb.RemovePDNObstructions"
    name = "Remove PDN obstructions"

    def get_subcommand(self) -> list[str]:
        return ["remove_obstructions"]
