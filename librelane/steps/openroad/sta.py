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
import json
import subprocess
from concurrent.futures import Future
from dataclasses import dataclass
from decimal import Decimal
from math import inf
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

import rich
import rich.table

from librelane.common import (
    Path,
    TclUtils,
    _get_process_limit,
    ContextPropagatingThreadPoolExecutor,
    aggregate_metrics,
    mkdirp,
)
from librelane.config import Macro, variable
from librelane.logging import console, options
from librelane.state import DesignFormat, State
from librelane.steps.step import (
    MetricsUpdate,
    Step,
    StepException,
    ViewsUpdate,
)
from librelane.steps.tclstep import TclStep

from librelane.steps.openroad.base import OpenROADStep


@Step.factory.register()
class STAMidPNR(OpenROADStep):
    """
    Performs `Static Timing Analysis <https://en.wikipedia.org/wiki/Static_timing_analysis>`_
    using OpenROAD on an OpenROAD database, mid-PnR, with estimated values for
    parasitics.
    """

    id = "OpenROAD.STAMidPNR"
    name = "STA (Mid-PnR)"
    long_name = "Static Timing Analysis (Mid-PnR)"

    inputs = [DesignFormat.ODB]
    outputs = []

    class Config(OpenROADStep.Config):
        STA_MIDPNR_CORNERS: Optional[list[str]] = variable(
            None,
            description="Mid-PnR STA step-specific override for the timing corners to report. If unset, `STA_CORNERS` is used, which is what the resizer steps around this one analyze.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "sta", "corner.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        corners = self.config.STA_MIDPNR_CORNERS or self.config.STA_CORNERS

        # The script writes one report directory per corner, and the output
        # processor opens the report files without creating directories.
        for corner in corners:
            mkdirp(os.path.join(self.step_dir, corner))

        return super().run(state_in, corners=corners, env=env, **kwargs)


class OpenSTAStep(OpenROADStep):
    @dataclass(frozen=True)
    class CornerFileList:
        libs: tuple[str, ...]
        netlists: tuple[str, ...]
        spefs: tuple[tuple[str, str], ...]
        extra_spefs_backcompat: tuple[tuple[str, str], ...] | None = None
        current_corner_spef: str | None = None

        def set_env(self, env: dict[str, Any]):
            env["_CURRENT_CORNER_LIBS"] = TclStep.value_to_tcl(self.libs)
            env["_CURRENT_CORNER_NETLISTS"] = TclStep.value_to_tcl(self.netlists)
            env["_CURRENT_CORNER_SPEFS"] = TclStep.value_to_tcl(self.spefs)
            if self.extra_spefs_backcompat is not None:
                env["_CURRENT_CORNER_EXTRA_SPEFS_BACKCOMPAT"] = TclStep.value_to_tcl(
                    self.extra_spefs_backcompat
                )
            if self.current_corner_spef is not None:
                env["_CURRENT_SPEF_BY_CORNER"] = self.current_corner_spef

    inputs = [DesignFormat.NETLIST]

    def get_command(self) -> list[str]:
        return ["sta", "-no_splash", "-exit", self.get_script_path()]

    def layout_preview(self) -> str | None:
        return None

    def _get_corner_files(
        self: Step,
        timing_corner: str | None = None,
        prioritize_nl: bool = False,
    ) -> tuple[str, CornerFileList]:
        (
            timing_corner,
            libs,
            netlists,
            spefs,
        ) = self.toolbox.get_timing_files_categorized(
            self.config,
            prioritize_nl=prioritize_nl,
            timing_corner=timing_corner,
        )
        state_in = self.state_in.result()

        name = timing_corner
        current_corner_spef = None
        input_spef_dict = state_in.get(DesignFormat.SPEF)
        if input_spef_dict is not None and len(input_spef_dict):
            if not isinstance(input_spef_dict, dict):
                raise StepException(
                    "Malformed input state: value for 'spef' is not a dictionary"
                )

            current_corner_spefs = self.toolbox.filter_views(
                self.config, input_spef_dict, timing_corner
            )
            if len(current_corner_spefs) < 1:
                raise StepException(
                    f"No SPEF file compatible with corner '{timing_corner}' found."
                )
            elif len(current_corner_spefs) > 1:
                logger.bind(step=self.id).warning(
                    f"Multiple SPEF files compatible with corner '{timing_corner}' found. The first one encountered will be used."
                )
            current_corner_spef = str(current_corner_spefs[0])

        extra_spefs_backcompat_raw = None
        if extra_spef_list := self.config.get("EXTRA_SPEFS"):
            extra_spefs_backcompat_raw = []
            logger.bind(step=self.id).warning(
                "The configuration variable 'EXTRA_SPEFS' is deprecated. It is recommended to use the new 'MACROS' configuration variable."
            )
            if len(extra_spef_list) % 4 != 0:
                raise StepException(
                    "Invalid value for 'EXTRA_SPEFS': Element count not divisible by four. It is recommended that you migrate your configuration to use the new 'MACROS' configuration variable."
                )
            for i in range(len(extra_spef_list) // 4):
                start = i * 4
                module, min, nom, max = (
                    extra_spef_list[start],
                    extra_spef_list[start + 1],
                    extra_spef_list[start + 2],
                    extra_spef_list[start + 3],
                )
                mapping = {
                    "min_*": [min],
                    "nom_*": [nom],
                    "max_*": [max],
                }
                spef = str(
                    self.toolbox.filter_views(
                        self.config, mapping, timing_corner=timing_corner
                    )[0]
                )
                extra_spefs_backcompat_raw.append((module, spef))

        extra_spefs_backcompat = None
        if extra_spefs_backcompat_raw is not None:
            extra_spefs_backcompat = tuple(extra_spefs_backcompat_raw)

        return (
            name,
            OpenSTAStep.CornerFileList(
                libs=tuple([str(lib) for lib in libs]),
                netlists=tuple([str(netlist) for netlist in netlists]),
                spefs=tuple([(pair[0], str(pair[1])) for pair in spefs]),
                extra_spefs_backcompat=extra_spefs_backcompat,
                current_corner_spef=current_corner_spef,
            ),
        )


@Step.factory.register()
class OpenSTAConsole(OpenSTAStep):
    """
    Loads the netlist, the timing models and, if available, the parasitics for
    one corner into an interactive OpenSTA console, so paths can be reported by
    hand.

    The corner is the PDK's default corner unless ``DEFAULT_CORNER`` says
    otherwise.

    The step ends when the console does, i.e., on ``exit`` or an end-of-file.
    """

    id = "OpenROAD.OpenSTAConsole"
    name = "Open In OpenSTA Console"

    inputs = [
        DesignFormat.NETLIST,
        DesignFormat.SPEF.mkOptional(),
    ]
    outputs = []

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "sta", "console.tcl")

    def get_command(self) -> list[str]:
        # No -exit: the point of the step is that OpenSTA keeps reading commands
        # from the terminal once the script is done.
        return ["sta", "-no_splash", str(self.get_script_path())]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        corner_name, file_list = self._get_corner_files(prioritize_nl=True)
        file_list.set_env(env)
        env["_CURRENT_CORNER_NAME"] = corner_name

        env = self.prepare_env(env, state_in)

        # Not run_subprocess: the console needs the terminal's stdin, stdout
        # and stderr, which the output processors would take away.
        self.run_interactive_subprocess(self.get_command(), env=env)

        return {}, {}


@Step.factory.register()
class CheckMacroInstances(OpenSTAStep):
    """
    Checks if all macro instances declared in the configuration are, in fact,
    in the design, emitting an error otherwise.

    Nested macros (macros within macros) are supported provided netlist views
    are available for the macro.
    """

    id = "OpenROAD.CheckMacroInstances"
    name = "Check Macro Instances"
    outputs = []

    class Config(OpenROADStep.Config):
        pass

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts", "openroad", "sta", "check_macro_instances.tcl"
        )

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        macros: dict[str, Macro] | None = self.config.MACROS
        if macros is None:
            logger.info("No macros found, skipping instance check…")
            return {}, {}

        macro_instance_pairs = []
        for macro_name, data in macros.items():
            for instance_name in data.instances:
                macro_instance_pairs.append(instance_name)
                macro_instance_pairs.append(macro_name)
            for views, view_label in ((data.lib, "LIB"), (data.spef, "SPEF")):
                self.toolbox.check_corner_granularity(
                    self.config,
                    views,
                    corners=self.config.STA_CORNERS,
                    label=f"Macro '{macro_name}' {view_label}",
                )

        env["_check_macro_instances"] = TclUtils.join(macro_instance_pairs)

        corner_name, file_list = self._get_corner_files(prioritize_nl=True)
        file_list.set_env(env)
        env["_CURRENT_CORNER_NAME"] = corner_name

        return super().run(state_in, env=env, **kwargs)


def format_frequency_against_target(
    frequency: int | float | Decimal | None,
    target_fmax: float,
) -> str:
    """Render a maximum frequency, red when it falls short of the target.

    Parameters
    ----------
    frequency
        The reported maximum frequency in MHz, or None if the corner did not
        report one.
    target_fmax
        The frequency the design asked for, in MHz.

    Returns
    -------
    str
        The frequency to four decimal places, tagged with a rich colour.
    """
    if frequency is None:
        return "[gray]?"
    frequency = round(float(frequency), 4)
    formatted_frequency = f"{frequency:.4f}"
    if frequency < target_fmax:
        return f"[red]{formatted_frequency}"
    else:
        return f"[green]{formatted_frequency}"


class MultiCornerSTA(OpenSTAStep):
    # SDF only. The corner script writes no views: an SDF per corner is added
    # to the state by STAPrePNR.run, and a LIB per corner by STAPostPNR.run.
    # Declaring an SDC here claimed a view nothing in this class ever produces,
    # which the pre-PnR STA stage contract then promised on its behalf.
    outputs = [DesignFormat.SDF]

    class Config(OpenSTAStep.Config):
        STA_MACRO_PRIORITIZE_NL: bool = variable(
            True,
            description="Prioritize the use of Netlists + SPEF files over LIB files if available for Macros. Useful if extraction was done using OpenROAD, where SPEF files are far more accurate.",
        )

        STA_MAX_VIOLATOR_COUNT: Optional[int] = variable(
            None,
            description="Maximum number of violators to list in violator_list.rpt",
        )

        EXTRA_SPEFS: Optional[list[str | Path]] = variable(
            None,
            description="A variable that only exists for backwards compatibility with LibreLane <2.0.0 and should not be used by new designs.",
        )

        STA_THREADS: Optional[int] = variable(
            None,
            description="The maximum number of STA corners to run in parallel. If unset, this will be equal to your machine's thread count.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "sta", "corner.tcl")

    def run_corner(
        self,
        state_in: State,
        current_env: dict[str, Any],
        corner: str,
        corner_dir: str,
    ) -> dict[str, Any]:
        logger.info(f"Starting STA for the {corner} timing corner…")
        current_env["_CURRENT_CORNER_NAME"] = corner
        log_path = os.path.join(corner_dir, "sta.log")

        try:
            subprocess_result = self.run_subprocess(
                self.get_command(),
                log_to=log_path,
                env=current_env,
                silent=True,
                # The script names its reports '<corner>/<report>', so the
                # report directory is the step directory and the reports land
                # in corner_dir, where they have always been.
                report_dir=self.step_dir,
            )

            generated_metrics = subprocess_result["generated_metrics"]

            logger.info(f"Finished STA for the {corner} timing corner.")
        except subprocess.CalledProcessError as e:
            logger.bind(step=self.id).error(
                f"Failed STA for the {corner} timing corner:"
            )
            raise e

        return generated_metrics

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env = self.prepare_env(env, state_in)

        tpe = ContextPropagatingThreadPoolExecutor(
            max_workers=self.config.STA_THREADS or _get_process_limit()
        )

        futures: dict[str, Future[MetricsUpdate]] = {}
        files_so_far: dict[OpenSTAStep.CornerFileList, str] = {}
        corners_used: set[str] = set()
        for corner in self.config.STA_CORNERS:
            _, file_list = self._get_corner_files(
                corner, prioritize_nl=self.config.STA_MACRO_PRIORITIZE_NL
            )
            if previous := files_so_far.get(file_list):
                logger.info(
                    f"Skipping corner {corner} for STA (identical to {previous} at this stage)…"
                )
                continue
            files_so_far[file_list] = corner
            corners_used.add(corner)

            current_env = env.copy()
            file_list.set_env(current_env)

            corner_dir = os.path.join(self.step_dir, corner)
            mkdirp(corner_dir)

            futures[corner] = tpe.submit(
                self.run_corner,
                state_in,
                current_env,
                corner,
                corner_dir,
            )

        metrics_updates: MetricsUpdate = {}
        for corner, updates_future in futures.items():
            metrics_updates.update(updates_future.result())

        metric_updates_with_aggregates = aggregate_metrics(metrics_updates)

        def format_count(count: int | float | Decimal | None) -> str:
            if count is None:
                return "[gray]?"
            count = int(count)
            if count == 0:
                return f"[green]{count}"
            else:
                return f"[red]{count}"

        def format_slack(slack: int | float | Decimal | None) -> str:
            if slack is None:
                return "[gray]?"
            if slack == float(inf):
                return "[gray]N/A"
            slack = round(float(slack), 4)
            formatted_slack = f"{slack:.4f}"
            if slack < 0:
                return f"[red]{formatted_slack}"
            else:
                return f"[green]{formatted_slack}"

        # The frequency the design asked for. A corner reporting less than this
        # missed its target.
        target_fmax = 1000 / float(self.config.CLOCK_PERIOD)

        def format_frequency(frequency: int | float | Decimal | None) -> str:
            return format_frequency_against_target(frequency, target_fmax)

        table = rich.table.Table()
        table.add_column("Corner/Group", width=20)
        table.add_column("Hold Worst Slack")
        table.add_column("Reg to Reg Paths")
        table.add_column("Hold TNS")
        table.add_column("Hold Vio Count")
        table.add_column("of which reg to reg")
        table.add_column("Setup Worst Slack")
        table.add_column("Reg to Reg Paths")
        table.add_column("Setup TNS")
        table.add_column("Setup Vio Count")
        table.add_column("of which reg to reg")
        table.add_column("Max Cap Violations")
        table.add_column("Max Slew Violations")
        table.add_column("Max Frequency (MHz)")
        for corner in ["Overall"] + self.config.STA_CORNERS:
            modifier = ""
            if corner != "Overall":
                if corner not in corners_used:
                    continue
                modifier = f"__corner:{corner}"
            row = [corner]
            for metric in [
                "timing__hold__ws",
                "timing__hold_r2r__ws",
                "timing__hold__tns",
                "timing__hold_vio__count",
                "timing__hold_r2r_vio__count",
                "timing__setup__ws",
                "timing__setup_r2r__ws",
                "timing__setup__tns",
                "timing__setup_vio__count",
                "timing__setup_r2r_vio__count",
                "design__max_cap_violation__count",
                "design__max_slew_violation__count",
                "timing__clock__fmax",
            ]:
                formatter: Callable[[int | float | Decimal | None], str]
                if metric.endswith("count"):
                    formatter = format_count
                elif metric == "timing__clock__fmax":
                    formatter = format_frequency
                else:
                    formatter = format_slack
                row.append(
                    formatter(metric_updates_with_aggregates.get(f"{metric}{modifier}"))
                )
            table.add_row(*row)

        if not options.get_condensed_mode():
            console.print(table)
        file_console = rich.console.Console(
            file=open(os.path.join(self.step_dir, "summary.rpt"), "w", encoding="utf8"),
            width=160,
        )
        file_console.print(table)

        return {}, metric_updates_with_aggregates


@Step.factory.register()
class STAPrePNR(MultiCornerSTA):
    """
    Performs hierarchical `Static Timing Analysis <https://en.wikipedia.org/wiki/Static_timing_analysis>`_
    using OpenSTA on the pre-PnR Verilog netlist, with all available timing information
    for standard cells and macros for multiple corners.

    If timing information is not available for a Macro, the macro in question
    will be black-boxed.

    During this step, the special variable `OPENLANE_SDC_IDEAL_CLOCKS` is
    exposed to SDC files with a value of `1`. We encourage PNR SDC files to use
    ideal clocks at this stage based on this variable's existence and value.
    """

    id = "OpenROAD.STAPrePNR"
    name = "STA (Pre-PnR)"
    long_name = "Static Timing Analysis (Pre-PnR)"

    def prepare_env(self, env: dict, state: State) -> dict:
        env = super().prepare_env(env, state)
        env["OPENLANE_SDC_IDEAL_CLOCKS"] = "1"
        return env

    def run_corner(
        self, state_in: State, current_env: dict[str, Any], corner: str, corner_dir: str
    ) -> dict[str, Any]:
        current_env["_SDF_SAVE_DIR"] = corner_dir
        return super().run_corner(state_in, current_env, corner, corner_dir)

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates, metrics_updates = super().run(state_in, **kwargs)

        sdf_dict = state_in.get(DesignFormat.SDF, {})
        if not isinstance(sdf_dict, dict):
            raise StepException(
                "Malformed input state: incoming value for SDF is not a dictionary."
            )

        sdf_dict = sdf_dict.copy()

        for corner in self.config.STA_CORNERS:
            sdf = os.path.join(
                self.step_dir, corner, f"{self.config.DESIGN_NAME}__{corner}.sdf"
            )
            if os.path.isfile(sdf):
                sdf_dict[corner] = Path(sdf)

        views_updates[DesignFormat.SDF] = sdf_dict

        return views_updates, metrics_updates


@Step.factory.register()
class STAPostPNR(STAPrePNR):
    """
    Performs multi-corner `Static Timing Analysis <https://en.wikipedia.org/wiki/Static_timing_analysis>`_
    using OpenSTA on the post-PnR Verilog netlist, with extracted parasitics for
    both the top-level module and any associated macros.

    During this step, the special variable `OPENLANE_SDC_IDEAL_CLOCKS` is
    exposed to SDC files with a value of `0`. We encourage PNR SDC files to use
    propagated clocks at this stage based on this variable's existence and value.
    """

    id = "OpenROAD.STAPostPNR"
    name = "STA (Post-PnR)"
    long_name = "Static Timing Analysis (Post-PnR)"

    class Config(STAPrePNR.Config):
        SIGNOFF_SDC_FILE: Optional[Path] = variable(
            None,
            description="Specifies the SDC file for STA during signoff",
        )

    config: Config

    inputs = STAPrePNR.inputs + [
        DesignFormat.SPEF,
        DesignFormat.ODB.mkOptional(),
    ]
    outputs = STAPrePNR.outputs + [DesignFormat.LIB]

    def prepare_env(self, env: dict, state: State) -> dict:
        env = super().prepare_env(env, state)
        if signoff_sdc_file := self.config.SIGNOFF_SDC_FILE:
            env["_SDC_IN"] = signoff_sdc_file
        env["OPENLANE_SDC_IDEAL_CLOCKS"] = "0"
        return env

    def filter_unannotated_report(
        self,
        corner: str,
        corner_dir: str,
        env: dict,
        checks_report: str,
        odb_design: str,
    ):
        tech_lefs = self.toolbox.filter_views(self.config, self.config.TECH_LEFS)
        if len(tech_lefs) != 1:
            raise StepException(
                "Misconfigured SCL: 'TECH_LEFS' must return exactly one Tech LEF for its default timing corner."
            )

        lefs = ["--input-lef", tech_lefs[0]]
        for lef in self.config.CELL_LEFS:
            lefs.append("--input-lef")
            lefs.append(lef)
        if extra_lefs := self.config.EXTRA_LEFS:
            for lef in extra_lefs:
                lefs.append("--input-lef")
                lefs.append(lef)
        if pad_lefs := self.config.PAD_LEFS:
            for lef in pad_lefs:
                lefs.append("--input-lef")
                lefs.append(lef)
        metrics_path = os.path.join(corner_dir, "filter_unannotated_metrics.json")
        filter_unannotated_cmd = [
            self.get_openroad_path(),
            "-exit",
            "-no_splash",
            "-metrics",
            metrics_path,
            "-python",
            files("librelane").joinpath("scripts", "odbpy", "filter_unannotated.py"),
            "--corner",
            corner,
            "--checks-report",
            checks_report,
            odb_design,
        ] + lefs

        subprocess_result = self.run_subprocess(
            filter_unannotated_cmd,
            log_to=os.path.join(corner_dir, "filter_unannotated.log"),
            env=env,
            silent=True,
            report_dir=corner_dir,
        )

        generated_metrics = subprocess_result["generated_metrics"]

        if os.path.exists(metrics_path):
            or_metrics_out = json.loads(open(metrics_path).read())
            generated_metrics.update(or_metrics_out)

        return generated_metrics

    def run_corner(
        self,
        state_in: State,
        current_env: dict[str, Any],
        corner: str,
        corner_dir: str,
    ) -> MetricsUpdate:
        current_env["_LIB_SAVE_DIR"] = corner_dir
        metrics_updates = super().run_corner(state_in, current_env, corner, corner_dir)
        filter_unannotated_metrics = {}
        if odb := state_in[DesignFormat.ODB]:
            try:
                filter_unannotated_metrics = self.filter_unannotated_report(
                    corner=corner,
                    checks_report=os.path.join(corner_dir, "checks.rpt"),
                    corner_dir=corner_dir,
                    env=current_env,
                    odb_design=str(odb),
                )
            except subprocess.CalledProcessError as e:
                logger.bind(step=self.id).error(
                    f"Failed filtering unannotated nets for the {corner} timing corner."
                )
                raise e
        return {**metrics_updates, **filter_unannotated_metrics}

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates, metrics_updates = super().run(state_in, **kwargs)
        lib_dict = state_in.get(DesignFormat.LIB, {})
        if not isinstance(lib_dict, dict):
            raise StepException(
                "Malformed input state: value for LIB is not a dictionary."
            )

        lib_dict.copy()

        for corner in self.config.STA_CORNERS:
            lib = os.path.join(
                self.step_dir, corner, f"{self.config.DESIGN_NAME}__{corner}.lib"
            )
            lib_dict[corner] = Path(lib)

        views_updates[DesignFormat.LIB] = lib_dict
        return views_updates, metrics_updates
