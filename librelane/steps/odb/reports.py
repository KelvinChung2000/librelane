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
from decimal import Decimal
from typing import Optional

from librelane.config import variable
from librelane.state import DesignFormat, State

from librelane.steps.step import (
    MetricGate,
    MetricsUpdate,
    Step,
    ViewsUpdate,
)
from librelane.steps.tclstep import TclStep

from librelane.steps.odb.base import OdbpyStep


@Step.factory.register()
class CheckMacroAntennaProperties(OdbpyStep):
    """
    Prints warnings if the LEF views of macros are missing antenna information.
    """

    id = "Odb.CheckMacroAntennaProperties"
    name = "Check Antenna Properties of Macros Pins in Their LEF Views"
    inputs = OdbpyStep.inputs
    outputs = []

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts",
            "odbpy",
            "check_antenna_properties.py",
        )

    def get_cells(self) -> list[str]:
        macros = self.config.MACROS
        cells = []
        if macros:
            cells = list(macros.keys())
        return cells

    def get_report_path(self) -> str:
        return os.path.join(self.step_dir, "report.yaml")

    def get_command(self) -> list[str]:
        args = ["--report-file", self.get_report_path()]
        for name in self.get_cells():
            args += ["--cell-name", name]
        return super().get_command() + args

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if not self.get_cells():
            logger.info(f"No cells provided, skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)


@Step.factory.register()
class CheckDesignAntennaProperties(CheckMacroAntennaProperties):
    """
    Prints warnings if the LEF view of the design is missing antenna information.
    """

    id = "Odb.CheckDesignAntennaProperties"
    name = "Check Antenna Properties of Pins in The Generated Design LEF view"
    inputs = CheckMacroAntennaProperties.inputs + [DesignFormat.LEF]

    def get_cells(self) -> list[str]:
        return [self.config.DESIGN_NAME]


@Step.factory.register()
class ReportWireLength(OdbpyStep):
    """
    Outputs a CSV of long wires, printed by length. Useful as a design aid to
    detect when one wire is connected to too many things.
    """

    outputs = []

    id = "Odb.ReportWireLength"
    name = "Report Wire Length"
    outputs = []

    # WIRE_LENGTH_THRESHOLD is a PDK's business rather than a fixed zero, so
    # the gate is deferred: an over-length wire doesn't invalidate anything
    # downstream needs from this state, it's a design-quality signal.
    gates = (
        MetricGate(
            "route__wirelength__max",
            "threshold-surpassing long wires",
            error_on_var="ERROR_ON_LONG_WIRE",
            threshold_var="WIRE_LENGTH_THRESHOLD",
        ),
    )

    class Config(OdbpyStep.Config):
        ERROR_ON_LONG_WIRE: bool = variable(
            True,
            description="Checks if any wire length exceeds the threshold set in the PDK. If so, an error is raised at the end of the flow.",
            deprecated_names=["QUIT_ON_LONG_WIRE"],
        )

        WIRE_LENGTH_THRESHOLD: Optional[Decimal] = variable(
            None,
            description="A value above which wire lengths generate warnings.",
            units="µm",
            pdk=True,
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "wire_lengths.py")

    def get_command(self) -> list[str]:
        return super().get_command() + [
            "--human-readable",
            "--report-out",
            os.path.join(self.step_dir, "wire_lengths.csv"),
        ]


@Step.factory.register()
class ReportDisconnectedPins(OdbpyStep):
    """
    Creates a table of disconnected pins in the design, updating metrics as
    appropriate.

    Disconnected pins may be marked "critical" if they are very likely to
    result in a dead design. We determine if a pin is critical as follows:

    * For the top-level macro: for these four kinds of pins: inputs, outputs,
      power inouts, and ground inouts, at least one of each kind must be
      connected or else all pins of a certain kind are counted as critical
      disconnected pins.
    * For instances:
        * Any unconnected input is a critical disconnected pin.
        * If there isn't at least one output connected, all disconnected
          outputs are critical disconnected pins.
        * Any disconnected power inout pins are critical disconnected pins.

    The metrics ``design__disconnected_pin__count`` and
    ``design__critical_disconnected_pin__count`` is updated. If any critical
    disconnected pins are found, the step raises an error of its own -- see
    ``ERROR_ON_DISCONNECTED_PINS``.
    """

    id = "Odb.ReportDisconnectedPins"
    name = "Report Disconnected Pins"

    # Immediate, not deferred: a critical disconnected pin is very likely to
    # produce a dead design, so nothing downstream is worth running against
    # a state this broken.
    gates = (
        MetricGate(
            "design__critical_disconnected_pin__count",
            "critical disconnected pins",
            error_on_var="ERROR_ON_DISCONNECTED_PINS",
            deferred=False,
        ),
    )

    class Config(OdbpyStep.Config):
        IGNORE_DISCONNECTED_MODULES: Optional[list[str]] = variable(
            None,
            description="Modules (or cells) to ignore when checking for disconnected pins.",
            pdk=True,
        )

        ERROR_ON_DISCONNECTED_PINS: bool = variable(
            True,
            description="Checks for disconnected instance pins after detailed routing and quits immediately if so.",
            deprecated_names=["QUIT_ON_DISCONNECTED_PINS"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "disconnected_pins.py")

    def get_command(self) -> list[str]:
        command = super().get_command()
        if ignored_modules := self.config.IGNORE_DISCONNECTED_MODULES:
            for module in ignored_modules:
                command.append("--ignore-module")
                command.append(module)
        command.append("--write-full-table-to")
        command.append(os.path.join(self.step_dir, "full_disconnected_pins_table.txt"))
        return command


@Step.factory.register()
class CellFrequencyTables(OdbpyStep):
    """
    Creates a number of tables to show the cell frequencies by:

    - Cells
    - Buffer cells only
    - Cell Function*
    - Standard Cell Library*

    * These tables only return meaningful info with PDKs distributed in the
      Open_PDKs format, i.e., all cells are named ``{scl}__{cell_fn}_{size}``.
    """

    id = "Odb.CellFrequencyTables"
    name = "Generate Cell Frequency Tables"

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts",
            "odbpy",
            "cell_frequency.py",
        )

    def get_buffer_list_file(self):
        return os.path.join(self.step_dir, "buffer_list.txt")

    def get_buffer_list_script(self):
        return files("librelane").joinpath("scripts", "openroad", "buffer_list.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        env_copy = env.copy()
        lib_list = self.toolbox.filter_views(self.config, self.config.LIB)
        env_copy["_PNR_LIBS"] = TclStep.value_to_tcl(lib_list)
        super().run_subprocess(
            [
                self.get_openroad_path(),
                "-no_splash",
                "-exit",
                self.get_buffer_list_script(),
            ],
            env=env_copy,
            log_to=self.get_buffer_list_file(),
        )
        return super().run(state_in, env=env, **kwargs)

    def get_command(self) -> list[str]:
        command = super().get_command()
        command.append("--buffer-list")
        command.append(self.get_buffer_list_file())
        command.append("--out-dir")
        command.append(os.fspath(self.step_dir))
        return command
