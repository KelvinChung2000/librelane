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

from ...resources import package_path
from decimal import Decimal
from typing import Optional

from ...config import Variable
from ...state import State

from ..step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OdbpyStep


@Step.factory.register()
class AddRoutingObstructions(OdbpyStep):
    """
    Adds obstructions on metal layers which prevent shapes from being created in
    the designated areas.
    """

    id = "Odb.AddRoutingObstructions"
    name = "Add Obstructions"
    config_vars = [
        Variable(
            "ROUTING_OBSTRUCTIONS",
            Optional[list[tuple[str, Decimal, Decimal, Decimal, Decimal]]],
            "Add routing obstructions to the design. If set to `None`, this step is skipped."
            + " Format of each obstruction item is a tuple of: layer name, llx, lly, urx, ury.",
            units="µm",
            default=None,
            deprecated_names=["GRT_OBS"],
        ),
    ]

    def get_obstruction_variable(self):
        return self.config_vars[0]

    def get_script_path(self):
        return package_path().joinpath("scripts", "odbpy", "defutil.py")

    def get_subcommand(self) -> list[str]:
        return ["add_obstructions"]

    def get_command(self) -> list[str]:
        command = super().get_command()
        if obstructions := self.config[self.config_vars[0].name]:
            for obstruction in obstructions:
                command.append("--obstructions")
                command.append(" ".join([str(o) for o in obstruction]))
        return command

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config[self.get_obstruction_variable().name] is None:
            logger.info(
                f"'{self.get_obstruction_variable().name}' is not defined. Skipping '{self.id}'…"
            )
            return {}, {}
        return super().run(state_in, **kwargs)


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
class AddPDNObstructions(AddRoutingObstructions):
    """
    Adds obstructions on metal layers which prevent shapes from being created in
    the designated areas.

    A soft-duplicate of <#Odb.AddRoutingObstructions>`_ , though this one uses
    a different variable name so the obstructions can be restricted for PDN
    steps only.
    """

    id = "Odb.AddPDNObstructions"
    name = "Add PDN obstructions"

    config_vars = [
        Variable(
            "PDN_OBSTRUCTIONS",
            Optional[list[tuple[str, Decimal, Decimal, Decimal, Decimal]]],
            "Add routing obstructions to the design before PDN stage. If set to `None`, this step is skipped."
            + " Format of each obstruction item is a tuple of: layer name, llx, lly, urx, ury,.",
            units="µm",
            default=None,
        ),
    ]


@Step.factory.register()
class RemovePDNObstructions(RemoveRoutingObstructions):
    """
    Removes any PDN obstructions previously placed by
    <#Odb.RemovePDNObstructions>`_.
    """

    id = "Odb.RemovePDNObstructions"
    name = "Remove PDN obstructions"

    config_vars = AddPDNObstructions.config_vars
