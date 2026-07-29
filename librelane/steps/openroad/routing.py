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
from loguru import logger

from importlib.resources import files
import io
import os
import re
import pathlib
from dataclasses import dataclass
from typing import (
    Optional,
)

import rich
import rich.table

from ...common import (
    DRC as DRCObject,
    mkdirp,
)
from ...config import variable
from ...logging import console, options
from ...state import DesignFormat, State
from ..common_variables import (
    DplConfig,
    GrtConfig,
)
from ..step import (
    CompositeStep,
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OpenROADStep


@Step.factory.register()
class CheckAntennas(OpenROADStep):
    """
    Runs OpenROAD to check if one or more long nets may constitute an
    `antenna risk <https://en.wikipedia.org/wiki/Antenna_effect>`_.

    The metric ``route__antenna_violation__count`` will be updated with the number of violating nets.
    """

    id = "OpenROAD.CheckAntennas"
    name = "Check Antennas"

    # default inputs
    outputs = []

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "antenna_check.tcl")

    def __summarize_antenna_report(self, report_file: str, output_file: str):
        """
        Extracts the list of violating nets from an ARC report file"
        """

        class AntennaViolation:
            def __init__(self, net, pin, required_ratio, partial_ratio, layer):
                self.net = net
                self.pin = pin
                self.required_ratio = float(required_ratio)
                self.partial_ratio = float(partial_ratio)
                self.layer = layer
                self.partial_to_required = self.partial_ratio / self.required_ratio

            def __lt__(self, other):
                return self.partial_to_required < other.partial_to_required

        net_pattern = re.compile(r"\s*Net:\s*(\S+)")
        required_ratio_pattern = re.compile(r"\s*Required ratio:\s+([\d.]+)")
        partial_ratio_pattern = re.compile(r"\s*Partial area ratio:\s+([\d.]+)")
        layer_pattern = re.compile(r"\s*Layer:\s+(\S+)")
        pin_pattern = re.compile(r"\s*Pin:\s+(\S+)")

        required_ratio = None
        layer = None
        partial_ratio = None
        required_ratio = None
        pin = None
        net = None
        violations: list[AntennaViolation] = []

        net_pattern = re.compile(r"\s*Net:\s*(\S+)")
        required_ratio_pattern = re.compile(r"\s*Required ratio:\s+([\d.]+)")
        partial_ratio_pattern = re.compile(r"\s*Partial area ratio:\s+([\d.]+)")
        layer_pattern = re.compile(r"\s*Layer:\s+(\S+)")
        pin_pattern = re.compile(r"\s*Pin:\s+(\S+)")

        with open(report_file, "r") as f:
            for line in f:
                pin_new = pin_pattern.match(line)
                required_ratio_new = required_ratio_pattern.match(line)
                partial_ratio_new = partial_ratio_pattern.match(line)
                layer_new = layer_pattern.match(line)
                net_new = net_pattern.match(line)
                required_ratio = (
                    required_ratio_new.group(1)
                    if required_ratio_new is not None
                    else required_ratio
                )
                partial_ratio = (
                    partial_ratio_new.group(1)
                    if partial_ratio_new is not None
                    else partial_ratio
                )
                layer = layer_new.group(1) if layer_new is not None else layer
                pin = pin_new.group(1) if pin_new is not None else pin
                net = net_new.group(1) if net_new is not None else net

                if "VIOLATED" in line:
                    violations.append(
                        AntennaViolation(
                            net=net,
                            pin=pin,
                            partial_ratio=partial_ratio,
                            layer=layer,
                            required_ratio=required_ratio,
                        )
                    )

        violations.sort(reverse=True)

        # Partial/Required:  2.36, Required:  3091.96, Partial:  7298.29,
        # Net: net384, Pin: _22354_/A, Layer: met5
        table = rich.table.Table()
        decimal_places = 2
        row = []
        table.add_column("P / R")
        table.add_column("Partial")
        table.add_column("Required")
        table.add_column("Net")
        table.add_column("Pin")
        table.add_column("Layer")
        for violation in violations:
            row = [
                f"{violation.partial_to_required:.{decimal_places}f}",
                f"{violation.partial_ratio:.{decimal_places}f}",
                f"{violation.required_ratio:.{decimal_places}f}",
                f"{violation.net}",
                f"{violation.pin}",
                f"{violation.layer}",
            ]
            table.add_row(*row)

        if not options.get_condensed_mode() and len(violations):
            console.print(table)
        file_console = rich.console.Console(
            file=open(output_file, "w", encoding="utf8"), width=160
        )
        file_console.print(table)

    def __get_antenna_nets(self, report: io.TextIOWrapper) -> int:
        pattern = re.compile(r"Net:\s*(\w+)")
        count = 0

        for line in report:
            line = line.strip()
            m = pattern.match(line)
            if m is None:
                continue
            count += 1

        return count

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        report_dir = os.path.join(self.step_dir, "reports")
        report_path = os.path.join(report_dir, "antenna.rpt")
        report_summary_path = os.path.join(report_dir, "antenna_summary.rpt")
        kwargs, env = self.extract_env(kwargs)
        env["_ANTENNA_REPORT"] = report_path

        mkdirp(os.path.join(self.step_dir, "reports"))

        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)
        metrics_updates["route__antenna_violation__count"] = self.__get_antenna_nets(
            open(report_path)
        )
        self.__summarize_antenna_report(report_path, report_summary_path)

        return views_updates, metrics_updates


@Step.factory.register()
class GlobalRouting(OpenROADStep):
    """
    The initial phase of routing. Given a detailed-placed ODB file, this
    phase starts assigning coarse-grained routing "regions" for each net so they
    may be later connected to wires.

    Estimated capacitance and resistance values are much more accurate for
    global routing.
    """

    id = "OpenROAD.GlobalRouting"
    name = "Global Routing"

    outputs = [DesignFormat.ODB, DesignFormat.DEF]

    class Config(DplConfig, GrtConfig, OpenROADStep.Config):
        pass

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "grt.tcl")


@Step.factory.register()
class _DiodeInsertion(GlobalRouting):
    """
    Inserts antenna diodes using global-routing information.

    Intended to run as part of :class:`RepairAntennas` rather than on its own,
    but registered nonetheless: it writes its own ``config.json`` naming this
    ID, and a reproducible made from that directory cannot be loaded unless
    the factory can resolve it.
    """

    id = "OpenROAD.DiodeInsertion"
    name = "Diode Insertion"

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "antenna_repair.tcl")


@Step.factory.register()
class RepairAntennas(CompositeStep):
    """
    Applies `antenna effect <https://en.wikipedia.org/wiki/Antenna_effect>`_
    mitigations using global-routing information, then re-runs detailed placement
    and global routing to legalize any inserted diodes.

    An antenna check is once again performed, updating the
    ``route__antenna_violation__count`` metric.
    """

    id = "OpenROAD.RepairAntennas"
    name = "Antenna Repair"

    Steps = [_DiodeInsertion, CheckAntennas]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.DIODE_CELL is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}

        return super().run(state_in, **kwargs)


@dataclass
class NDR:
    """
    :param spacing: The spacing of the non-default rule.
        This can be a single value that applies to all layers, or 'layer' 'spacing' pairs.
        The single value can be given in µm or a as multiplier, such as `*3`, to multiply the default spacing by 3.
        Alternatively, pairs can be given as `spacing: [li1, 0.51, met1, 0.42, met2, 0.42, met3, 0.9, met4, 0.9, met5, 4.8]`.
    :param width: The width of the non-default rule.
        This can be a single value that applies to all layers, or 'layer' 'width' pairs.
        The single value can be given in µm or a as multiplier, such as `*3`, to multiply the default width by 3.
        Alternatively, pairs can be given as `width: [li1, 0.51, met1, 0.42, met2, 0.42, met3, 0.9, met4, 0.9, met5, 4.8]`.
    :param via: The allowed vias for the non-default rule. If not specified, the default vias will be used.
        For example: `via: [L1M1_PR_R, M1M2_PR_R, M2M3_PR_R, M3M4_PR_R, M4M5_PR_R]`
    """

    spacing: list[str]
    width: list[str]
    via: list[str] | None


@Step.factory.register()
class DetailedRouting(OpenROADStep):
    """
    The latter phase of routing. This transforms the abstract nets from global
    routing into wires on the metal layers that respect all design rules, avoids
    creating accidental shorts, and ensures all wires are connected.

    This is by far the longest part of a typical flow, taking hours, days or weeks
    on larger designs.

    After this point, all cells connected to a net can no longer be moved or
    removed without a custom-written step of some kind that will also rip up
    wires.
    """

    id = "OpenROAD.DetailedRouting"
    name = "Detailed Routing"

    class Config(GrtConfig, OpenROADStep.Config):
        DRT_OPT_ITERS: int = variable(
            64,
            description="Specifies the maximum number of optimization iterations during Detailed Routing in TritonRoute.",
        )

        DRT_SAVE_SNAPSHOTS: bool = variable(
            False,
            description="Experimental: saves an odb snapshot of the layout each routing iteration. This increases disk usage considerably but is useful for debugging.",
        )

        DRT_ANTENNA_REPAIR_ITERS: int = variable(
            3,
            description="The maximum number of iterations to run antenna repair. Set to a positive integer to attempt to repair antennas and then re-run DRT as appropriate.",
        )

        DRT_ANTENNA_REPAIR_MARGIN: int = variable(
            10,
            description="The margin to over fix antenna violations.",
            units="%",
            deprecated_names=["DRT_ANTENNA_MARGIN"],
        )

        DRT_ANTENNA_REPAIR_JUMPER_ONLY: bool = variable(
            False,
            description="Only use jumpers to fix antenna violations. Cannot be used in conjunction with DRT_ANTENNA_REPAIR_DIODE_ONLY.",
        )

        DRT_ANTENNA_REPAIR_DIODE_ONLY: bool = variable(
            False,
            description="Only use antenna diodes to fix antenna violations. Cannot be used in conjunction with DRT_ANTENNA_REPAIR_JUMPER_ONLY.",
        )

        DRT_SAVE_DRC_REPORT_ITERS: Optional[int] = variable(
            None,
            description="Write a DRC report every N iterations. If DRT_SAVE_SNAPSHOTS is enabled, there is an implicit default value of 1.",
        )

        NON_DEFAULT_RULES: Optional[dict[str, NDR]] = variable(
            None,
            description="Specify non-default rules. Can be used to change the width, spacing and vias of a net.",
        )

        DRT_ASSIGN_NDR: Optional[dict[str, str]] = variable(
            None,
            description="Specify which nets should be assigned to which non-default rule. The net name is a regular expression. Use '^name$' to match an exact name.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "drt.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)

        drc_paths = list(pathlib.Path(self.step_dir).rglob("*.drc*"))
        for path in drc_paths:
            drc, _ = DRCObject.from_openroad(
                open(path, encoding="utf8"), self.config.DESIGN_NAME
            )

            drc.to_klayout_xml(open(pathlib.Path(str(path) + ".xml"), "wb"))
        #        if violation_count > 0:
        #            logger.bind(step=self.id).warning(
        #                f"DRC errors found after routing. View the report file at {report_path}.\nView KLayout xml file at {klayout_db_path}"
        #            )

        return views_updates, metrics_updates
