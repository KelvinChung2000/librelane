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
import os
from typing import Optional

from librelane.common import Path
from librelane.config import variable
from librelane.state import DesignFormat, State

from librelane.steps.step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from librelane.steps.odb.base import OdbpyStep


@Step.factory.register()
class SetPowerConnections(OdbpyStep):
    """
    Uses JSON netlist and module information in Odb to add global power
    connections for macros at the top level of a design.

    If the JSON netlist is hierarchical (e.g. by using a keep hierarchy
    attribute) this Step emits a warning and does not attempt to connect any
    macros instantiated within submodules.
    """

    id = "Odb.SetPowerConnections"
    name = "Set Power Connections"
    inputs = [DesignFormat.JSON_HEADER, DesignFormat.ODB]

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "power_utils.py")

    def get_subcommand(self) -> list[str]:
        return ["set-power-connections"]

    def get_command(self) -> list[str]:
        state_in = self.state_in.result()
        return super().get_command() + [
            "--input-json",
            str(state_in[DesignFormat.JSON_HEADER]),
        ]


@Step.factory.register()
class WriteVerilogHeader(OdbpyStep):
    """
    Writes a Verilog header of the module using information from the generated
    PDN, guarded by the value of ``VERILOG_POWER_DEFINE``, and the JSON header.
    """

    id = "Odb.WriteVerilogHeader"
    name = "Write Verilog Header"
    inputs = [DesignFormat.ODB, DesignFormat.JSON_HEADER]
    outputs = [DesignFormat.VERILOG_HEADER]

    class Config(OdbpyStep.Config):
        VERILOG_POWER_DEFINE: Optional[str] = variable(
            "USE_POWER_PINS",
            description="Specifies the name of the define used to guard power and ground connections in the output Verilog header.",
            deprecated_names=["SYNTH_USE_PG_PINS_DEFINES", "SYNTH_POWER_DEFINE"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "power_utils.py")

    def get_subcommand(self) -> list[str]:
        return ["write-verilog-header"]

    def get_command(self) -> list[str]:
        state_in = self.state_in.result()
        command = super().get_command() + [
            "--output-vh",
            os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.vh"),
            "--input-json",
            str(state_in[DesignFormat.JSON_HEADER]),
        ]
        power_define = self.config.VERILOG_POWER_DEFINE
        if power_define is not None:
            command += ["--power-define", power_define]
        else:
            logger.bind(step=self.id).warning(
                "VERILOG_POWER_DEFINE undefined. Verilog Header will not include power ports."
            )

        return command

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates, metrics_updates = super().run(state_in, **kwargs)
        views_updates[DesignFormat.VERILOG_HEADER] = Path(
            os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.vh")
        )
        return views_updates, metrics_updates
