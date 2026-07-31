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
import os
import re
import subprocess
from concurrent.futures import Future
from decimal import Decimal
from typing import (
    Optional,
)


from librelane.common import (
    Path,
    _get_process_limit,
    ContextPropagatingThreadPoolExecutor,
    mkdirp,
)
from librelane.config import variable
from librelane.state import DesignFormat, State
from librelane.steps.step import (
    MetricsUpdate,
    Step,
    StepException,
    ViewsUpdate,
)

from librelane.steps.openroad.base import OpenROADStep
from librelane.steps.openroad.sta import OpenSTAStep


@Step.factory.register()
class LayoutSTA(OpenROADStep):
    """
    Performs `Static Timing Analysis <https://en.wikipedia.org/wiki/Static_timing_analysis>`_
    using OpenROAD on the ODB layout in its current state.
    """

    id = "OpenROAD.LayoutSTA"
    name = "Layout STA"
    long_name = "Layout Static Timing Analysis"

    inputs = [DesignFormat.ODB]
    outputs = []

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "sta.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env["RUN_STANDALONE"] = "1"
        return super().run(state_in, env=env, **kwargs)


@Step.factory.register()
class FillInsertion(OpenROADStep):
    """
    Fills gaps in the floorplan with filler and decap cells.

    This is run after detailed placement. After this point, the design is basically
    completely hardened.
    """

    id = "OpenROAD.FillInsertion"
    name = "Fill Insertion"

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "fill.tcl")


@Step.factory.register()
class RCX(OpenROADStep):
    """
    This extracts `parasitic <https://en.wikipedia.org/wiki/Parasitic_element_(electrical_networks)>`_
    electrical values from a detailed-placed circuit. These can be used to create
    basically the highest accurate STA possible for a given design.
    """

    id = "OpenROAD.RCX"
    name = "Parasitics (RC) Extraction"
    long_name = "Parasitic Resistance/Capacitance Extraction"

    class Config(OpenROADStep.Config):
        RCX_MERGE_VIA_WIRE_RES: bool = variable(
            True,
            description="If enabled, the via and wire resistances will be merged.",
        )

        RCX_SDC_FILE: Optional[Path] = variable(
            None,
            description="Specifies SDC file to be used for RCX-based STA, which can be different from the one used for implementation.",
        )

        RCX_RULESETS: dict[str, Path] = variable(
            description="Map of corner patterns to OpenRCX extraction rules.",
            pdk=True,
        )

        STA_THREADS: Optional[int] = variable(
            None,
            description="The maximum number of STA corners to run in parallel. If unset, this will be equal to your machine's thread count.",
        )

    config: Config

    inputs = [DesignFormat.DEF]
    outputs = [DesignFormat.SPEF]

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "rcx.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env = self.prepare_env(env, state_in)

        def run_corner(corner: str):
            nonlocal env
            current_env = env.copy()

            rcx_ruleset = self.config.RCX_RULESETS.get(corner)
            if rcx_ruleset is None:
                logger.bind(step=self.id).warning(
                    f"RCX ruleset for corner {corner} not found. The corner may be ill-defined."
                )
                return None

            corner_sanitized = corner.strip("*_")
            corner_dir = os.path.join(self.step_dir, corner_sanitized)
            mkdirp(corner_dir)

            tech_lefs = self.toolbox.filter_views(
                self.config, self.config.TECH_LEFS, corner
            )
            if len(tech_lefs) < 1:
                logger.bind(step=self.id).warning(
                    f"No tech lef for timing corner {corner} found."
                )
                return None
            elif len(tech_lefs) > 1:
                logger.bind(step=self.id).warning(
                    f"Multiple tech lefs found for timing corner {corner}. Only the first one matched will be used."
                )

            current_env["RCX_LEF"] = tech_lefs[0]
            current_env["RCX_RULESET"] = rcx_ruleset

            out = os.path.join(
                corner_dir, f"{self.config.DESIGN_NAME}.{corner_sanitized}.spef"
            )
            current_env["SAVE_SPEF"] = out

            corner_qualifier = f"the {corner} corner"
            if "*" in corner:
                corner_qualifier = f"corners matching {corner}"

            log_path = os.path.join(corner_dir, "rcx.log")
            logger.info(f"Running RCX for {corner_qualifier} ({log_path})…")

            try:
                self.run_subprocess(
                    self.get_command(),
                    log_to=log_path,
                    env=current_env,
                    silent=True,
                )
                logger.info(f"Finished RCX for {corner_qualifier}.")
            except subprocess.CalledProcessError as e:
                logger.bind(step=self.id).error(
                    f"Failed RCX for the {corner_qualifier}:"
                )
                raise e

            return out

        tpe = ContextPropagatingThreadPoolExecutor(
            max_workers=self.config.STA_THREADS or _get_process_limit()
        )

        futures: dict[str, Future[str]] = {}
        for corner in self.config.RCX_RULESETS:
            futures[corner] = tpe.submit(
                run_corner,
                corner,
            )

        views_updates: ViewsUpdate = {}
        metrics_updates: MetricsUpdate = {}

        spef_dict = state_in.get(DesignFormat.SPEF, {})
        if not isinstance(spef_dict, dict):
            raise StepException(
                "Malformed input state: value for SPEF is not a dictionary."
            )

        for corner, future in futures.items():
            if result := future.result():
                spef_dict[corner] = Path(result)

        views_updates[DesignFormat.SPEF] = spef_dict

        return views_updates, metrics_updates


@Step.factory.register()
class IRDropReport(OpenROADStep):
    """
    Performs static IR-drop analysis on the power distribution network. For power
    nets, this constitutes a decrease in voltage, and for ground nets, it constitutes
    an increase in voltage.
    """

    id = "OpenROAD.IRDropReport"
    name = "IR Drop Report"
    long_name = "Generate IR Drop Report"

    inputs = [DesignFormat.ODB, DesignFormat.SPEF]
    outputs = []

    class Config(OpenROADStep.Config):
        VSRC_LOC_FILES: Optional[dict[str, Path]] = variable(
            None,
            description="Map of power and ground nets to OpenROAD PSM location files. See [this](https://github.com/The-OpenROAD-Project/OpenROAD/tree/master/src/psm#commands) for more info.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "irdrop.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        from decimal import Decimal

        assert state_in[DesignFormat.SPEF] is not None
        if not isinstance(state_in[DesignFormat.SPEF], dict):
            raise StepException(
                "Malformed input state: value for SPEF is not a dictionary."
            )

        kwargs, env = self.extract_env(kwargs)

        input_spef_dict = state_in[DesignFormat.SPEF]
        assert input_spef_dict is not None  # Checked by start
        if not isinstance(input_spef_dict, dict):
            raise StepException(
                "Malformed input state: value for 'spef' is not a dictionary"
            )

        spefs_in = self.toolbox.filter_views(self.config, input_spef_dict)
        if len(spefs_in) > 1:
            raise StepException(
                "Found more than one input SPEF file for the default corner."
            )
        elif len(spefs_in) < 1:
            raise StepException("No SPEF file found for the default corner.")

        libs_in = self.toolbox.filter_views(self.config, self.config.LIB)

        if self.config.VSRC_LOC_FILES is None:
            logger.bind(step=self.id).warning(
                "'VSRC_LOC_FILES' was not given a value, which may make the results of IR drop analysis inaccurate. If you are not integrating a top-level chip for manufacture, you may ignore this warning, otherwise, see the documentation for 'VSRC_LOC_FILES'."
            )

        if voltage := self.toolbox.get_lib_voltage(str(libs_in[0])):
            env["LIB_VOLTAGE"] = str(voltage)

        env["CURRENT_SPEF_DEFAULT_CORNER"] = str(spefs_in[0])
        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)

        report = open(os.path.join(self.step_dir, "irdrop.rpt")).read()

        logger.log("VERBOSE", report)

        voltage_rx = re.compile(r"Worstcase voltage\s*:\s*([\d\.\+\-e]+)\s*V")
        avg_drop_rx = re.compile(r"Average IR drop\s*:\s*([\d\.\+\-e]+)\s*V")
        worst_drop_rx = re.compile(r"Worstcase IR drop\s*:\s*([\d\.\+\-e]+)\s*V")

        if m := voltage_rx.search(report):
            value_float = float(m[1])
            value_dec = Decimal(value_float)
            metrics_updates["ir__voltage__worst"] = value_dec
        else:
            raise Exception(
                "OpenROAD IR Drop Log format has changed- please file an issue."
            )

        if m := avg_drop_rx.search(report):
            value_float = float(m[1])
            value_dec = Decimal(value_float)
            metrics_updates["ir__drop__avg"] = value_dec
        else:
            raise Exception(
                "OpenROAD IR Drop Log format has changed- please file an issue."
            )

        if m := worst_drop_rx.search(report):
            value_float = float(m[1])
            value_dec = Decimal(value_float)
            metrics_updates["ir__drop__worst"] = value_dec
        else:
            raise Exception(
                "OpenROAD IR Drop Log format has changed- please file an issue."
            )

        return views_updates, metrics_updates


@Step.factory.register()
class CutRows(OpenROADStep):
    """
    Cut floorplan rows with respect to placed macros.
    """

    id = "OpenROAD.CutRows"
    name = "Cut Rows"

    inputs = [DesignFormat.ODB]
    outputs = [
        DesignFormat.ODB,
        DesignFormat.DEF,
    ]

    class Config(OpenROADStep.Config):
        FP_MACRO_HORIZONTAL_HALO: Decimal = variable(
            10,
            description="Specify the horizontal halo size around macros, within which standard cell rows are cut away.",
            units="µm",
            deprecated_names=["FP_TAP_HORIZONTAL_HALO"],
        )

        FP_MACRO_VERTICAL_HALO: Decimal = variable(
            10,
            description="Specify the vertical halo size around macros, within which standard cell rows are cut away.",
            units="µm",
            deprecated_names=["FP_TAP_VERTICAL_HALO"],
        )

        FP_PRUNE_THRESHOLD: Optional[Decimal] = variable(
            None,
            description='If specified, all rows smaller in width than this value will be removed. This helps avoid "islets" of cells that are hard to route and connect to PDNs.',
            pdk=True,
            units="µm",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "cut_rows.tcl")


@Step.factory.register()
class WriteCDL(OpenROADStep):
    """
    Write CDL view of an ODB design
    """

    id = "OpenROAD.WriteCDL"
    name = "Write CDL"
    outputs = [DesignFormat.CDL]

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "write_cdl.tcl")


# Resizer Steps


## ABC


@Step.factory.register()
class DEFtoODB(OpenROADStep):
    """
    Converts a DEF view to an ODB view.

    Useful if you have a custom step that manipulates the layout outside of
    OpenROAD, but you would like to update the OpenROAD database.
    """

    id = "OpenROAD.DEFtoODB"
    name = "DEF to OpenDB"

    inputs = [DesignFormat.DEF]
    outputs = [DesignFormat.ODB]

    def get_script_path(self) -> str:
        return str(
            files("librelane").joinpath("scripts", "openroad", "write_views.tcl")
        )


@Step.factory.register()
class OpenGUI(OpenSTAStep):
    """
    Opens the ODB view in the OpenROAD GUI. Useful to inspect some parameters,
    such as routing density, timing paths, clock tree and whatnot.
    The LIBs are loaded by default and the SPEFs if available.
    """

    id = "OpenROAD.OpenGUI"
    name = "Open In GUI"

    inputs = [
        DesignFormat.ODB,
        DesignFormat.SPEF.mkOptional(),
    ]
    outputs = []

    def get_script_path(self) -> str:
        return str(files("librelane").joinpath("scripts", "openroad", "gui.tcl"))

    def get_command(self) -> list[str]:
        return [
            "openroad",
            "-no_splash",
            "-gui",
            self.get_script_path(),
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        corner_name, file_list = self._get_corner_files(prioritize_nl=True)
        file_list.set_env(env)
        env["_CURRENT_CORNER_NAME"] = corner_name

        env = self.prepare_env(env, state_in)

        command = self.get_command()
        self.run_subprocess(
            command,
            env=env,
            **kwargs,
        )

        return {}, {}


@Step.factory.register()
class DumpRCValues(OpenROADStep):
    """
    Creates three reports:

    * Initial Database Layer RC Values (from Tech LEF)
    * Modified Database Layer RC Values
    * Modified Resizer Layer RC Values
    """

    id = "OpenROAD.DumpRCValues"
    name = "Dump RC Values"

    inputs = [DesignFormat.DEF]

    def get_script_path(self) -> str:
        return str(files("librelane").joinpath("scripts", "openroad", "dump_rc.tcl"))
