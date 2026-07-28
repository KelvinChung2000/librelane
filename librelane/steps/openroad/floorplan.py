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
import textwrap
from decimal import Decimal
from enum import Enum
from glob import glob
from typing import (
    Literal,
    Optional,
    TypeAlias,
)

import yaml

from ...common import (
    Path,
    aggregate_metrics,
)
from ...config import Variable, variable
from ...state import DesignFormat, State
from ..common_variables import (
    IoLayerConfig,
    PdnConfig,
)
from ..step import (
    MetricsUpdate,
    Step,
    StepException,
    ViewsUpdate,
)

from .base import OpenROADStep, old_to_new_tracks, pdn_macro_migrator


@Step.factory.register()
class Floorplan(OpenROADStep):
    """
    Creates DEF and ODB files with the initial floorplan based on the Yosys netlist.
    """

    id = "OpenROAD.Floorplan"
    name = "Floorplan Init"
    long_name = "Floorplan Initialization"

    inputs = [DesignFormat.NETLIST]

    class Config(OpenROADStep.Config):
        FP_FLIP_SITES: Optional[list[str]] = variable(
            None,
            description="Flip these sites vertically. Useful in niche alignment scenarios where single-height cells have ground at the south side and double-height cells have power at the south side, causing a short. In that situation, flipping the sites for single-height cells resolves the issue.",
            pdk=True,
        )

        FP_TRACKS_INFO: Path = variable(
            description="A path to the a classic OpenROAD `.tracks` file. Used by the floorplanner to generate tracks.",
            deprecated_names=["TRACKS_INFO_FILE"],
            pdk=True,
        )

        FP_SIZING: Literal["absolute", "relative"] = variable(
            "relative",
            description="Sizing mode for floorplanning",
        )

        FP_ASPECT_RATIO: Decimal = variable(
            1,
            description="The core's aspect ratio (height / width).",
        )

        FP_CORE_UTIL: Decimal = variable(
            50,
            description="The core utilization percentage.",
            units="%",
        )

        FP_OBSTRUCTIONS: Optional[list[tuple[Decimal, Decimal, Decimal, Decimal]]] = (
            variable(
                None,
                description="Obstructions applied at floorplanning stage. Placement sites are never generated at these locations, which guarantees that it will remain empty throughout the entire flow.",
                units="µm",
            )
        )

        PL_SOFT_OBSTRUCTIONS: Optional[
            list[tuple[Decimal, Decimal, Decimal, Decimal]]
        ] = variable(
            None,
            description="Soft placement blockages applied at the floorplanning stage. Areas that are soft-blocked will not be used by the initial placer, however, later phases such as buffer insertion or clock tree synthesis are still allowed to place cells in this area.",
            units="µm",
        )

        CORE_AREA: Optional[tuple[Decimal, Decimal, Decimal, Decimal]] = variable(
            None,
            description="Specifies a core area (i.e. die area minus margins) to be used in floorplanning."
            + " It must be paired with `DIE_AREA`.",
            units="µm",
        )

        BOTTOM_MARGIN_MULT: Decimal = variable(
            4,
            description="The core margin, in multiples of site heights, from the bottom boundary."
            + " If `DIEA_AREA` and `CORE_AREA` are set, this variable has no effect.",
        )

        TOP_MARGIN_MULT: Decimal = variable(
            4,
            description="The core margin, in multiples of site heights, from the top boundary."
            + " If `DIE_AREA` and `CORE_AREA` are set, this variable has no effect.",
        )

        LEFT_MARGIN_MULT: Decimal = variable(
            12,
            description="The core margin, in multiples of site widths, from the left boundary."
            + " If `DIE_AREA` are `CORE_AREA` are set, this variable has no effect.",
        )

        RIGHT_MARGIN_MULT: Decimal = variable(
            12,
            description="The core margin, in multiples of site widths, from the right boundary."
            + " If `DIE_AREA` are `CORE_AREA` are set, this variable has no effect.",
        )

        EXTRA_SITES: Optional[list[str]] = variable(
            None,
            description="Explicitly specify sites other than `PLACE_SITE` to create rows for. If the alternate-site standard cells properly declare the `SITE` property, you do not need to provide this explicitly.",
            pdk=True,
        )

    config: Config

    class Mode(str, Enum):
        TEMPLATE = "template"
        ABSOULTE = "absolute"
        RELATIVE = "relative"

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "floorplan.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        path = self.config.FP_TRACKS_INFO
        tracks_info_str = open(path).read()
        tracks_commands = old_to_new_tracks(tracks_info_str)
        new_tracks_info = os.path.join(self.step_dir, "config.tracks")
        with open(new_tracks_info, "w") as f:
            f.write(tracks_commands)

        kwargs, env = self.extract_env(kwargs)
        env["TRACKS_INFO_FILE_PROCESSED"] = new_tracks_info
        return super().run(state_in, env=env, **kwargs)


PPLMode: TypeAlias = Literal["matching", "annealing", "random_equidistant"]


def _validate_io_ppl_mode(
    variable: Variable, input: PPLMode, warning_list_ref: list[str]
):
    if input == "random_equidistant":
        warning_list_ref.append(
            f"The mode '{input}' for {variable.name} has been removed. Please update your configuration to use 'matching' instead."
        )
        return "matching"
    return input


@Step.factory.register()
class PadRing(OpenROADStep):
    """
    Assembles a pad ring on a floor-planned ODB file using OpenROAD's built-in pad placer.
    """

    id = "OpenROAD.PadRing"
    name = "Pad Ring Generation"

    class Config(OpenROADStep.Config):
        PDN_CONNECT_MACROS_TO_GRID: bool = variable(
            True,
            description="Enables the connection of macros to the top level power grid.",
            deprecated_names=["FP_PDN_ENABLE_MACROS_GRID"],
        )

        PDN_MACRO_CONNECTIONS: Optional[list[str]] = variable(
            None,
            description="Specifies explicit power connections of internal macros to the top level power grid, in the format: regex matching macro instance names, power domain vdd and ground net names, and macro vdd and ground pin names `<instance_name_rx> <vdd_net> <gnd_net> <vdd_pin> <gnd_pin>`.",
            deprecated_names=[("FP_PDN_MACRO_HOOKS", pdn_macro_migrator)],
        )

        PDN_ENABLE_GLOBAL_CONNECTIONS: bool = variable(
            True,
            description="Enables the creation of global connections in PDN generation.",
            deprecated_names=["FP_PDN_ENABLE_GLOBAL_CONNECTIONS"],
        )

        PAD_CFG: Optional[Path] = variable(
            None,
            description="A custom pad configuration file. If not provided, the default pad config will be used.",
        )

        PAD_SOUTH: Optional[list[str]] = variable(
            None,
            description="The pad instance names for the south pad row.",
        )

        PAD_EAST: Optional[list[str]] = variable(
            None,
            description="The pad instance names for the east pad row.",
        )

        PAD_NORTH: Optional[list[str]] = variable(
            None,
            description="The pad instance names for the north pad row.",
        )

        PAD_WEST: Optional[list[str]] = variable(
            None,
            description="The pad instance names for the west pad row.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "pad.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        if self.config.PAD_CFG is None:
            env["PAD_CFG"] = files("librelane").joinpath(
                "scripts", "openroad", "common", "pad_cfg.tcl"
            )
            logger.info(
                f"'PAD_CFG' not explicitly set, setting it to {env['PAD_CFG']}…"
            )

        return super().run(state_in, env=env, **kwargs)


@Step.factory.register()
class IOPlacement(OpenROADStep):
    """
    Places I/O pins on a floor-planned ODB file using OpenROAD's built-in placer.

    If ``IO_PIN_ORDER_CFG`` is not ``None``, this step is skipped (for
    compatibility with OpenLane.)
    """

    id = "OpenROAD.IOPlacement"
    name = "I/O Placement"

    class Config(IoLayerConfig, OpenROADStep.Config):
        IO_PIN_CORNER_AVOIDANCE: Optional[Decimal] = variable(
            None,
            description="The distance from each corner within which pin placement should be avoided.",
            units="µm",
        )

        IO_PIN_PLACEMENT_MODE: PPLMode = variable(
            "matching",
            description="Decides the mode of the random IO placement option.",
            deprecated_names=["FP_PPL_MODE"],
            validator=_validate_io_ppl_mode,
        )

        IO_PIN_MIN_DISTANCE: Optional[Decimal] = variable(
            None,
            description="The minimum distance between two pins. The unit is microns or routing tracks, depending on whether IO_PIN_MIN_DISTANCE_IN_TRACKS is set. If unspecified by a PDK, OpenROAD will use the length of two routing tracks.",
            units="µm or routing tracks",
            pdk=True,
            deprecated_names=["FP_IO_MIN_DISTANCE"],
        )

        IO_PIN_MIN_DISTANCE_IN_TRACKS: Optional[bool] = variable(
            None,
            description="Setting this variable to true allows IO_PIN_MIN_DISTANCE to be set in number of tracks instead of microns.",
            pdk=True,
        )

        IO_PIN_ORDER_CFG: Optional[Path] = variable(
            None,
            description="Path to a custom pin configuration file.",
            deprecated_names=["FP_PIN_ORDER_CFG"],
        )

        IO_EXCLUDE_PIN_REGION: Optional[list[str]] = variable(
            None,
            description="List of regions where pins cannot be placed. The regions are strings in the format `{edge}:{interval}` where edge is `top|bottom|left|right` and the interval is either `*` to exclude the entire edge or `{begin}-{end}` to exclude a part of the edge, where `begin` and `end` are either absolute distance values or themselves `*` to denote the very start or end of an edge.",
            units="µm",
        )

        FP_DEF_TEMPLATE: Optional[Path] = variable(
            None,
            description="Points to the DEF file to be used as a template.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "ioplacer.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.IO_PIN_ORDER_CFG is not None:
            logger.info(f"IO_PIN_ORDER_CFG is set. Skipping '{self.id}'…")
            return {}, {}
        if self.config.FP_DEF_TEMPLATE is not None:
            logger.info(
                f"I/O pins were loaded from {self.config.FP_DEF_TEMPLATE}. Skipping {self.id}…"
            )
            return {}, {}

        return super().run(state_in, **kwargs)


@Step.factory.register()
class TapEndcapInsertion(OpenROADStep):
    """
    Places welltap cells across a floorplan, as well as endcap cells at the
    edges of the floorplan.
    """

    id = "OpenROAD.TapEndcapInsertion"
    name = "Tap/Decap Insertion"

    class Config(OpenROADStep.Config):
        FP_TAPCELL_DIST: Optional[Decimal] = variable(
            None,
            description="The distance between tap cell columns. Must be specified if WELLTAP_CELL is specified.",
            units="µm",
            pdk=True,
        )

        FP_MACRO_HORIZONTAL_HALO: Decimal = variable(
            10,
            description="Specify the horizontal halo size around macros.",
            units="µm",
            deprecated_names=["FP_TAP_HORIZONTAL_HALO"],
        )

        FP_MACRO_VERTICAL_HALO: Decimal = variable(
            10,
            description="Specify the vertical halo size around macros.",
            units="µm",
            deprecated_names=["FP_TAP_VERTICAL_HALO"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "tapcell.tcl")

    def run(self, state_in, **kwargs):
        if self.config.WELLTAP_CELL is not None and self.config.FP_TAPCELL_DIST is None:
            raise StepException("FP_TAPCELL_DIST must be set if WELLTAP_CELL is set.")
        return super().run(state_in, **kwargs)


@Step.factory.register()
class UnplaceAll(OpenROADStep):
    """
    Sets placement status of *all* instances to NONE.

    Useful in flows where a preliminary placement is needed as a pre-requisite
    to something else but that placement must be discarded.
    """

    id = "OpenROAD.UnplaceAll"
    name = "Unplace All"

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "ungpl.tcl")


def get_psm_error_count(rpt: io.TextIOWrapper) -> int:
    sio = io.StringIO()

    # Turn almost-YAML into YAML
    VIO_TYPE_PFX = "violation type: "
    for line in rpt:
        if line.startswith(VIO_TYPE_PFX):
            vio_type = line[len(VIO_TYPE_PFX) :].strip()
            sio.write(f"- type: {vio_type}\n")
        elif "bbox = " in line:
            sio.write(f"    {textwrap.dedent(line.replace('bbox = ', '- bbox ='))}")
        else:
            sio.write(f"  {textwrap.dedent(line)}")

    sio.seek(0)
    violations = yaml.load(sio, Loader=yaml.SafeLoader) or []
    return sum(len(violation["srcs"]) for violation in violations)


@Step.factory.register()
class GeneratePDN(OpenROADStep):
    """
    Creates a power distribution network on a floorplanned ODB file.
    """

    id = "OpenROAD.GeneratePDN"
    name = "Generate PDN"
    long_name = "Power Distribution Network Generation"

    class Config(PdnConfig, OpenROADStep.Config):
        PDN_CFG: Optional[Path] = variable(
            None,
            description="A custom PDN configuration file. If not provided, the default PDN config will be used.",
            deprecated_names=["FP_PDN_CFG"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "pdn.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        if self.config.PDN_CFG is None:
            env["PDN_CFG"] = files("librelane").joinpath(
                "scripts", "openroad", "common", "pdn_cfg.tcl"
            )
            logger.info(
                f"'PDN_CFG' not explicitly set, setting it to {env['PDN_CFG']}…"
            )
        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)

        alerts = self.alerts or []
        error_reports = glob(os.path.join(self.step_dir, "*-grid-errors.rpt"))
        for report in error_reports:
            net = os.path.basename(report).split("-", maxsplit=1)[0]
            no_terminals = any(
                alert.code == "PSM-0025" and alert.message.startswith(net)
                for alert in alerts
            )
            if no_terminals:
                count = 1
            else:
                count = get_psm_error_count(open(report, encoding="utf8"))
            metrics_updates[f"design__power_grid_violation__count__net:{net}"] = count

        metric_updates_with_aggregates = aggregate_metrics(
            metrics_updates,
            {"design__power_grid_violation__count": (0, lambda x: sum(x))},
        )

        return views_updates, metric_updates_with_aggregates
