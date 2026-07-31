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

from librelane.common import (
    DRC as DRCObject,
    mkdirp,
)
from librelane.config import variable
from librelane.logging import console, options
from librelane.state import DesignFormat, State
from librelane.steps.common_variables import (
    DplConfig,
    GrtConfig,
)
from librelane.steps.step import (
    CompositeStep,
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from librelane.steps.openroad.base import OpenROADStep


@dataclass
class AntennaViolation:
    """A single violated antenna ratio check, as reported by OpenROAD's
    ``check_antennas -verbose``.

    Attributes
    ----------
    net
        The name of the violating net.
    pin
        The pin of the gate the violation was attributed to.
    layer
        The routing layer the ratio was computed on.
    check
        Which rule was violated, as OpenROAD names it: ``Gate area``,
        ``Cumulative area``, ``Side area`` or ``Cumulative side area``.
    calculated_ratio
        The ratio OpenROAD computed. Depending on ``check``, this is a partial
        (PAR/PSR) or a cumulative (CAR/CSR) area ratio.
    required_ratio
        The ratio the PDK's antenna rule allows.
    """

    net: str
    pin: str
    layer: str
    check: str
    calculated_ratio: float
    required_ratio: float

    @property
    def calculated_to_required(self) -> float:
        """How far past the limit this violation is, as a multiple of it."""
        return self.calculated_ratio / self.required_ratio

    def __lt__(self, other: "AntennaViolation") -> bool:
        return self.calculated_to_required < other.calculated_to_required


# OpenROAD emits, per net/pin/layer, a calculated/required pair for each of PAR
# ("Partial area ratio" / "Gate area"), CAR ("Cumulative area ratio" /
# "Cumulative area"), PSR ("Partial area ratio" / "Side area") and CSR
# ("Cumulative area ratio" / "Cumulative side area"). The "(VIOLATED)" marker
# sits on the "Required ratio:" line and the calculated value is always on the
# line immediately above it, so a violation is attributed by pairing the two
# rather than by remembering the last "Partial area ratio" seen.
_net_pattern = re.compile(r"\s*Net:\s*(\S+)")
_pin_pattern = re.compile(r"\s*Pin:\s+(\S+)")
_layer_pattern = re.compile(r"\s*Layer:\s+(\S+)")
_calculated_ratio_pattern = re.compile(
    r"\s*(?:Partial|Cumulative) area ratio:\s+([\d.]+)"
)
_required_ratio_pattern = re.compile(r"\s*Required ratio:\s+([\d.]+)\s*\(([^)]+)\)")


def parse_antenna_report(report_file: str) -> list[AntennaViolation]:
    """Extract the violated ratio checks from an OpenROAD antenna report.

    Parameters
    ----------
    report_file
        Path to the report written by ``check_antennas -verbose``.

    Returns
    -------
    list[AntennaViolation]
        The violations, worst (highest calculated-to-required ratio) first.

    Raises
    ------
    ValueError
        If a ``(VIOLATED)`` marker appears before any line the violation could
        be attributed to, which means the report format has changed.
    """
    net: Optional[str] = None
    pin: Optional[str] = None
    layer: Optional[str] = None
    calculated_ratio: Optional[float] = None
    violations: list[AntennaViolation] = []

    with open(report_file, "r", encoding="utf8") as f:
        for line_number, line in enumerate(f, start=1):
            if net_match := _net_pattern.match(line):
                net = net_match.group(1)
            elif pin_match := _pin_pattern.match(line):
                pin = pin_match.group(1)
            elif layer_match := _layer_pattern.match(line):
                layer = layer_match.group(1)
            elif calculated_match := _calculated_ratio_pattern.match(line):
                calculated_ratio = float(calculated_match.group(1))
            elif required_match := _required_ratio_pattern.match(line):
                if "VIOLATED" not in line:
                    continue
                if (
                    calculated_ratio is None
                    or net is None
                    or pin is None
                    or layer is None
                ):
                    raise ValueError(
                        f"Could not attribute the violation in the antenna report "
                        f"{report_file} at line {line_number}: no net, pin, layer "
                        f"and calculated ratio precede it. The report format has "
                        f"likely changed."
                    )
                violations.append(
                    AntennaViolation(
                        net=net,
                        pin=pin,
                        layer=layer,
                        check=required_match.group(2),
                        calculated_ratio=calculated_ratio,
                        required_ratio=float(required_match.group(1)),
                    )
                )

    violations.sort(reverse=True)
    return violations


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
        Extracts the list of violating nets from an ARC report file
        """
        violations = parse_antenna_report(report_file)

        # Ratio / Required:  2.36, Required:  3091.96, Ratio:  7298.29,
        # Check: Cumulative area, Net: net384, Pin: _22354_/A, Layer: met5
        table = rich.table.Table()
        decimal_places = 2
        table.add_column("Ratio / Required")
        table.add_column("Ratio")
        table.add_column("Required")
        table.add_column("Check")
        table.add_column("Net")
        table.add_column("Pin")
        table.add_column("Layer")
        for violation in violations:
            row = [
                f"{violation.calculated_to_required:.{decimal_places}f}",
                f"{violation.calculated_ratio:.{decimal_places}f}",
                f"{violation.required_ratio:.{decimal_places}f}",
                f"{violation.check}",
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
    Parameters
    ----------
    spacing : list[str]
        The spacing of the non-default rule.
        This can be a single value that applies to all layers, or 'layer' 'spacing' pairs.
        The single value can be given in µm or a as multiplier, such as `*3`, to multiply the default spacing by 3.
        Alternatively, pairs can be given as `spacing: [li1, 0.51, met1, 0.42, met2, 0.42, met3, 0.9, met4, 0.9, met5, 4.8]`.
    width : list[str]
        The width of the non-default rule.
        This can be a single value that applies to all layers, or 'layer' 'width' pairs.
        The single value can be given in µm or a as multiplier, such as `*3`, to multiply the default width by 3.
        Alternatively, pairs can be given as `width: [li1, 0.51, met1, 0.42, met2, 0.42, met3, 0.9, met4, 0.9, met5, 4.8]`.
    via : list[str] | None
        The allowed vias for the non-default rule. If not specified, the default vias will be used.
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
