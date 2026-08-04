# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane
#
# Copyright 2024 Efabless Corporation
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
import sys
import json
import fnmatch
import shutil
import pathlib
from decimal import Decimal
from abc import abstractmethod
from typing import Literal

from librelane.steps.step import (
    MetricGate,
    MetricsUpdate,
    Step,
    StepError,
    ViewsUpdate,
)

from librelane.config import BaseConfigModel, Variable, model_to_variables, variable
from librelane.state import State, DesignFormat
from librelane.common import Path, process_list_file

starts_with_whitespace = re.compile(r"^\s+.+$")

yosys_cell_rx = r"cell\s+\S+\s+\((\S+)\)"


def _check_any_tristate(
    cells: list[str],
    tristate_patterns: list[str],
):
    for cell in cells:
        for tristate_pattern in tristate_patterns:
            if fnmatch.fnmatch(cell, tristate_pattern):
                return True

    return False


def _parse_yosys_check(
    report_path: str,
    tristate_patterns: list[str] | None = None,
    tristate_okay: bool = False,
    elaborate_only: bool = False,
) -> int:
    """
    Counts the problems Yosys' ``check`` pass reported, skipping the classes of
    problem the configuration declares acceptable.

    Every problem that is counted is also logged, together with the report it
    came from. Yosys writes two ``check`` reports per run and only the earlier
    one, ``pre_synth_chk.rpt``, feeds this count, so a bare count sent readers
    to the later ``chk.rpt``, which routinely says zero problems.

    See https://github.com/librelane/librelane/issues/824.
    """
    logger.log("VERBOSE", f"Parsing synthesis checks from '{report_path}'…")
    counted: list[str] = []
    last_warning = None
    current_warning = None

    tristate_patterns = tristate_patterns or []

    with open(report_path) as report:
        for line in report:
            if line.startswith("Warning:") or line.startswith("Found and reported"):
                last_warning = current_warning
                current_warning = line
                if last_warning is None:
                    continue

                cells = re.findall(yosys_cell_rx, last_warning)

                if elaborate_only and "but has no driver" in last_warning:
                    logger.debug("Ignoring undriven cell in elaborate-only mode:")
                    logger.debug(last_warning)
                elif tristate_okay and (
                    ("tribuf" in last_warning)
                    or _check_any_tristate(cells, tristate_patterns)
                ):
                    logger.debug("Ignoring tristate-related error:")
                    logger.debug(last_warning)
                else:
                    counted.append(last_warning)
            elif (
                starts_with_whitespace.match(line) is not None
                and current_warning is not None
            ):
                current_warning += line
            else:
                pass

    if counted:
        logger.warning(f"Yosys reported {len(counted)} problem(s) in '{report_path}':")
        for warning in counted:
            logger.warning(warning.rstrip())

    return len(counted)


class VerilogRtlConfig(BaseConfigModel):
    VERILOG_FILES: list[Path] = variable(
        description="The paths of the design's Verilog files.",
    )

    VERILOG_DEFINES: list[str] | None = variable(
        None,
        description="Preprocessor defines for input Verilog files.",
    )

    VERILOG_POWER_DEFINE: str | None = variable(
        "USE_POWER_PINS",
        description="Specifies the name of the define used to guard power and ground connections in the input RTL.",
    )

    VERILOG_INCLUDE_DIRS: list[Path] | None = variable(
        None,
        description="Specifies the Verilog `include` directories.",
    )

    SYNTH_PARAMETERS: list[str] | None = variable(
        None,
        description="Key-value pairs to be `chparam`ed in Yosys, in the format `key1=value1`.",
    )

    USE_SLANG: bool = variable(
        False,
        description="Use the Slang frontend to process files, which has better SystemVerilog parsing capabilities but is not as battle-tested as the default Yosys friend.",
    )

    SLANG_ARGUMENTS: list[str] | None = variable(
        None,
        description="Pass arguments to the Slang frontend.",
    )


verilog_rtl_cfg_vars = model_to_variables(VerilogRtlConfig)

DesignFormat(
    "json_h",
    "h.json",
    "Design JSON Header File",
    alts=["JSON_HEADER"],
).register()


def _validate_icg(variable: Variable, input: str | None, warning_list_ref: list[str]):
    if input is not None:
        components = input.split("/")
        if len(components) != 4:
            raise ValueError(
                f"{variable.name} must be in the form '<cell>/<ce>/<clk>/<gclk>'"
            )
    return input


class PyosysStep(Step):
    class Config(Step.Config):
        SYNTH_LATCH_MAP: Path | None = variable(
            None,
            description="A path to a file containing the latch mapping for Yosys.",
            pdk=True,
        )

        SYNTH_TRISTATE_MAP: Path | None = variable(
            None,
            description="A path to a file containing the tri-state buffer mapping for Yosys.",
            deprecated_names=["TRISTATE_BUFFER_MAP"],
            pdk=True,
        )

        SYNTH_CSA_MAP: Path | None = variable(
            None,
            description="A path to a file containing the carry-select adder mapping for Yosys.",
            deprecated_names=["CARRY_SELECT_ADDER_MAP"],
            pdk=True,
        )

        SYNTH_RCA_MAP: Path | None = variable(
            None,
            description="A path to a file containing the ripple-carry adder mapping for Yosys.",
            deprecated_names=["RIPPLE_CARRY_ADDER_MAP"],
            pdk=True,
        )

        SYNTH_FA_MAP: Path | None = variable(
            None,
            description="A path to a file containing the full adder mapping for Yosys.",
            deprecated_names=["FULL_ADDER_MAP"],
            pdk=True,
        )

        SYNTH_CLOCKGATE_MIN_WIDTH: int | None = variable(
            None,
            description="If set to a value, a group of flip-flops with size >= SYNTH_CLOCKGATE_MIN_WIDTH and an enable signal are clock-gated instead.",
        )

        SYNTH_CLOCKGATE_POSEDGE_ICG: str | None = variable(
            None,
            description="The integrated clock gate cell used for positive-edge flip-flops, in the format `<cell>/<active-high clock enable port>/<clk port>/<gated clk port>`.",
            pdk=True,
            validator=_validate_icg,
        )

        SYNTH_CLOCKGATE_NEGEDGE_ICG: str | None = variable(
            None,
            description="The integrated clock gate cell used for positive-edge flip-flops, in the format `<cell>/<active-high clock enable port>/<clk port>/<gated clk port>`.",
            pdk=True,
            validator=_validate_icg,
        )

        YOSYS_LOG_LEVEL: Literal["ALL", "WARNING", "ERROR"] = variable(
            "ALL",
            description="Which log level for Yosys. At WARNING or higher, the initialization splash is also disabled.",
        )

        SYNTH_CORNER: str | None = variable(
            None,
            description="A fully qualified IPVT corner to use during synthesis. If unspecified, the value for `DEFAULT_CORNER` from the PDK will be used.",
            pdk=True,
        )

        SYNTH_SHOW: bool = variable(
            False,
            description="Generate a graphviz DOT file for the design. This will fail on a completely empty design.",
        )

    config: Config

    @classmethod
    def get_yosys_path(Self) -> str:
        return os.getenv("_LLN_OVERRIDE_YOSYS", "yosys")

    @abstractmethod
    def get_script_path(self) -> str:
        pass

    def get_command(self, state_in: State) -> list[str]:
        script_path = self.get_script_path()
        # HACK: Get Colab working
        yosys_bin = self.get_yosys_path()
        if "google.colab" in sys.modules:
            yosys_bin = shutil.which("yosys") or "yosys"
        cmd = [yosys_bin, "-y", script_path]
        if self.config.YOSYS_LOG_LEVEL != "ALL":
            cmd += ["-Q"]
        if self.config.YOSYS_LOG_LEVEL == "WARNING":
            cmd += ["-q"]
        elif self.config.YOSYS_LOG_LEVEL == "ERROR":
            cmd += ["-qq"]
        cmd += ["--"]
        cmd += ["--config-in", os.path.join(self.step_dir, "config.json")]
        return cmd

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        cmd = self.get_command(state_in)
        kwargs, env = self.extract_env(kwargs)
        # HACK: Get Colab working
        if "google.colab" in sys.modules:
            env.pop("PATH", "")
        env["PYTHONPATH"] = ":".join(
            (
                env.get("PYTHONPATH", ""),
                str(files("librelane").joinpath("scripts", "pyosys")),
            )
        )
        subprocess_result = super().run_subprocess(cmd, env=env, **kwargs)
        return {}, subprocess_result["generated_metrics"]


class VerilogStep(PyosysStep):
    power_defines: bool = False

    # No Verilog RTL variables here: this class is about power defines, not
    # about reading RTL, and VHDLSynthesis derives from it.
    class Config(PyosysStep.Config):
        pass

    config: Config

    def get_command(self, state_in: State) -> list[str]:
        cmd = super().get_command(state_in)

        blackbox_models = []
        scl_lib_list = self.toolbox.filter_views(
            self.config, self.config.LIB, self.config.get("SYNTH_CORNER")
        )

        if self.power_defines:
            if self.config.CELL_VERILOG_MODELS is not None:
                blackbox_models.extend(
                    [
                        self.toolbox.create_blackbox_model(
                            frozenset(self.config.CELL_VERILOG_MODELS),
                            frozenset(["USE_POWER_PINS"]),
                        )
                    ]
                )
            if self.config.PAD_VERILOG_MODELS is not None:
                blackbox_models.extend(
                    [
                        self.toolbox.create_blackbox_model(
                            frozenset(self.config.PAD_VERILOG_MODELS),
                            frozenset(["USE_POWER_PINS"]),
                        )
                    ]
                )
        else:
            blackbox_models.extend(str(f) for f in scl_lib_list)

        # Priorities from higher to lower
        format_list = (
            [
                DesignFormat.VERILOG_HEADER,
                DesignFormat.POWERED_NETLIST,
                DesignFormat.NETLIST,
                DesignFormat.LIB,
            ]
            if self.power_defines
            else [
                DesignFormat.VERILOG_HEADER,
                DesignFormat.NETLIST,
                DesignFormat.POWERED_NETLIST,
                DesignFormat.LIB,
            ]
        )
        macro_lib_views = []
        for view, format in self.toolbox.get_macro_views_by_priority(
            self.config, format_list
        ):
            blackbox_models.append(str(view))
            if format == DesignFormat.LIB:
                macro_lib_views.append(str(view))

        if libs := self.config.get("EXTRA_LIBS"):
            blackbox_models.extend(str(f) for f in libs)
        if models := self.config.get("EXTRA_VERILOG_MODELS"):
            blackbox_models.extend(str(f) for f in models)

        excluded_cells: set[str] = set(self.config.EXTRA_EXCLUDED_CELLS or [])
        excluded_cells.update(process_list_file(self.config.SYNTH_EXCLUDED_CELL_FILE))
        excluded_cells.update(process_list_file(self.config.PNR_EXCLUDED_CELL_FILE))

        # Copied, not aliased: remove_cells_from_lib is memoized, so extending
        # its return value in place would corrupt the entry every later call
        # with the same arguments receives.
        libs_synth = list(
            self.toolbox.remove_cells_from_lib(
                frozenset([str(lib) for lib in scl_lib_list]),
                excluded_cells=frozenset(excluded_cells),
            )
        )
        # ABC and dfflibmap only ever saw the standard cell library, so a macro
        # had no area and no timing during synthesis.
        if extra_libs := self.config.get("EXTRA_LIBS"):
            libs_synth.extend(str(f) for f in extra_libs)
        libs_synth.extend(macro_lib_views)
        libs_synth = list(dict.fromkeys(libs_synth))

        extra_path = os.path.join(self.step_dir, "extra.json")
        with open(extra_path, "w") as f:
            json.dump({"blackbox_models": blackbox_models, "libs_synth": libs_synth}, f)
        cmd.extend(["--extra-in", extra_path])
        return cmd


@Step.factory.register()
class JsonHeader(VerilogStep):
    """
    Extracts a high-level hierarchical view of the circuit in JSON format,
    including power connections. The power connections are used in later steps
    to ensure macros and cells are connected as desired.
    """

    id = "Yosys.JsonHeader"
    name = "Generate JSON Header"
    long_name = "Generate JSON Header"

    inputs = []
    outputs = [DesignFormat.JSON_HEADER]

    class Config(VerilogRtlConfig, VerilogStep.Config):
        pass

    config: Config

    power_defines = True

    def get_script_path(self) -> str:
        return str(files("librelane").joinpath("scripts", "pyosys", "json_header.py"))

    def get_command(self, state_in: State) -> list[str]:
        out_file = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.JSON_HEADER.extension}",
        )
        return super().get_command(state_in) + ["--output", out_file]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        out_file = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.JSON_HEADER.extension}",
        )
        views_updates, metrics_updates = super().run(state_in, **kwargs)
        views_updates[DesignFormat.JSON_HEADER] = pathlib.Path(out_file)
        return views_updates, metrics_updates


class SynthesisCommon(VerilogStep):
    inputs = []  # The input RTL is part of the configuration
    outputs = [DesignFormat.NETLIST]

    # Both stop the flow where it stands rather than deferring: an unmapped
    # cell or a check error means the netlist this step just wrote is not
    # trustworthy, so nothing downstream of it is worth running.
    gates = (
        MetricGate(
            "design__instance_unmapped__count",
            "unmapped Yosys instances",
            error_on_var="ERROR_ON_UNMAPPED_CELLS",
            deferred=False,
        ),
        MetricGate(
            "synthesis__check_error__count",
            "Yosys check errors",
            error_on_var="ERROR_ON_SYNTH_CHECKS",
            deferred=False,
        ),
    )

    class Config(VerilogStep.Config):
        ERROR_ON_UNMAPPED_CELLS: bool = variable(
            True,
            description="Checks for unmapped cells after synthesis and quits immediately if so.",
        )

        ERROR_ON_SYNTH_CHECKS: bool = variable(
            True,
            description="Quits the flow immediately if one or more synthesis check errors are flagged. This checks for combinational loops and/or wires with no drivers. The flagged problems are logged by the synthesis step and listed in its `reports/pre_synth_chk.rpt`.",
        )

        ERROR_ON_NL_ASSIGN_STATEMENTS: bool = variable(
            True,
            description="Whether to emit an error or simply warn about the existence",
        )

        SYNTH_CHECKS_ALLOW_TRISTATE: bool = variable(
            True,
            description="Ignore multiple-driver warnings if they are connected to tri-state buffers on a best-effort basis.",
        )

        SYNTH_AUTONAME: bool = variable(
            False,
            description="Generates names for netlist instances. This results in instance names that can be extremely long, but are more human-readable.",
        )

        SYNTH_STRATEGY: Literal[
            "AREA 0",
            "AREA 1",
            "AREA 2",
            "AREA 3",
            "DELAY 0",
            "DELAY 1",
            "DELAY 2",
            "DELAY 3",
            "DELAY 4",
        ] = variable(
            "AREA 0",
            description="Strategies for abc logic synthesis and technology mapping. AREA strategies usually result in a more compact design, while DELAY strategies usually result in a design that runs at a higher frequency. Please note that there is no way to know which strategy is the best before trying them.",
        )

        SYNTH_ABC_BUFFERING: bool = variable(
            False,
            description="Enables `abc` cell buffering.",
        )

        SYNTH_ABC_LEGACY_REFACTOR: bool = variable(
            False,
            description="Replaces the ABC command `drf -l` with `refactor` which matches older versions of LibreLane but is more unstable.",
        )

        SYNTH_ABC_LEGACY_REWRITE: bool = variable(
            False,
            description="Replaces the ABC command `drw -l` with `rewrite` which matches older versions of LibreLane but is more unstable.",
        )

        SYNTH_ABC_DFF: bool = variable(
            False,
            description="Passes D-flipflop cells through ABC for optimization (which can for example, eliminate identical flip-flops).",
        )

        SYNTH_ABC_USE_MFS3: bool = variable(
            False,
            description="Experimental: attempts a SAT-based remapping in all area and delay strategies before 'retime', which may improve PPA results.",
        )

        SYNTH_ABC_AREA_USE_NF: bool = variable(
            False,
            description="Experimental: uses the &nf delay-based mapper with a very high value instead of the amap area mapper, which may be better in some scenarios at recovering area.",
        )

        SYNTH_ABC_STRATEGY_SCRIPT: Path | None = variable(
            None,
            description="Custom ABC strategy script. Runs instead of the default script for the selected 'SYNTH_STRATEGY'. All other 'SYNTH_ABC_*' variables except 'SYNTH_ABC_DFF' will have no effect.",
        )

        SYNTH_DIRECT_WIRE_BUFFERING: bool = variable(
            True,
            description="Enables inserting buffer cells for directly connected wires.",
        )

        SYNTH_SPLITNETS: bool = variable(
            True,
            description="Splits multi-bit nets into single-bit nets. Easier to trace but may not be supported by all tools.",
        )

        SYNTH_SIZING: bool = variable(
            False,
            description="Enables `abc` cell sizing (instead of buffering).",
        )

        SYNTH_HIERARCHY_MODE: Literal["flatten", "deferred_flatten", "keep"] = variable(
            "flatten",
            description="Affects how hierarchy is maintained throughout and after synthesis. 'flatten' flattens it during and after synthesis. 'deferred_flatten' flattens it after synthesis. 'keep' never flattens it. Please note that when using the Slang plugin, you need to pass '--keep-hierarchy' to `SLANG_ARGUMENTS` separately. To keep the hierarchy partially, use one of the flattening options and set the 'keep_hierarchy' attribute on instances or modules via: `SYNTH_KEEP_HIERARCHY_INSTANCES`, `SYNTH_KEEP_HIERARCHY_MODULES` or `SYNTH_KEEP_HIERARCHY_MIN_COST`.",
        )

        SYNTH_KEEP_HIERARCHY_MIN_COST: int | None = variable(
            None,
            description="Sets the 'keep_hierarchy' attribute on modules where the gate count is estimated to exceed the specified threshold. This prevents larger modules from being flattened. This variable only affects the design when 'flatten' is called through `SYNTH_HIERARCHY_MODE`.",
        )

        SYNTH_KEEP_HIERARCHY_INSTANCES: list[str] | None = variable(
            None,
            description="A list of instances for which to set the 'keep_hierarchy' attribute. This variable only affects the design when 'flatten' is called through `SYNTH_HIERARCHY_MODE`.",
        )

        SYNTH_KEEP_HIERARCHY_MODULES: list[str] | None = variable(
            None,
            description="A list of modules for which to set the 'keep_hierarchy' attribute. This variable only affects the design when 'flatten' is called through `SYNTH_HIERARCHY_MODE`.",
        )

        SYNTH_SHARE_RESOURCES: bool = variable(
            True,
            description="A flag that enables yosys to reduce the number of cells by determining shareable resources and merging them.",
        )

        SYNTH_ADDER_TYPE: Literal["YOSYS", "FA", "RCA", "CSA"] = variable(
            "YOSYS",
            description="Adder type to which the $add and $sub operators are mapped to.  Possible values are `YOSYS/FA/RCA/CSA`; where `YOSYS` refers to using Yosys internal adder definition, `FA` refers to full-adder structure, `RCA` refers to ripple carry adder structure, and `CSA` refers to carry select adder.",
        )

        SYNTH_EXTRA_MAPPING_FILE: Path | None = variable(
            None,
            description="Points to an extra techmap file for yosys that runs right after yosys `synth` before generic techmap.",
        )

        SYNTH_ELABORATE_ONLY: bool = variable(
            False,
            description='"Elaborate" the design only without attempting any logic mapping. Useful when dealing with structural Verilog netlists.',
        )

        SYNTH_MUL_BOOTH: bool = variable(
            False,
            description="Runs the booth pass as part of synthesis: See https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/booth.html",
        )

        SYNTH_TIE_UNDEFINED: Literal["high", "low"] | None = variable(
            "low",
            description="Whether to tie undefined values low or high. Explicitly provide null if you wish to simply leave them undriven.",
        )

        SYNTH_WRITE_NOATTR: bool = variable(
            True,
            description="If true, Verilog-2001 attributes are omitted from output netlists. Some utilities do not support attributes.",
        )

        SYNTH_NORMALIZE_SINGLE_BIT_VECTORS: bool = variable(
            True,
            description="If true, vectors with the shape [0:0] are converted to normal wires in the netlist. If disabled, even one-width pins will be suffixed [0] in the layout when imported by most PnR tools.",
        )

        SYNTH_ARITH_TREE: bool = variable(
            True,
            description="Runs the arith_tree pass as part of synthesis: See https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/index_passes_techmap.html#cmd-arith_tree",
        )

    config: Config

    def get_script_path(self) -> str:
        return str(files("librelane").joinpath("scripts", "pyosys", "synthesize.py"))

    def get_command(self, state_in: State) -> list[str]:
        out_file = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.NETLIST.extension}",
        )
        return super().get_command(state_in) + ["--output", out_file]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        out_file = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.NETLIST.extension}",
        )

        view_updates, metric_updates = super().run(state_in, **kwargs)

        stats_file = os.path.join(self.step_dir, "reports", "stat.json")
        stats_str = open(stats_file).read()
        stats = json.loads(stats_str, parse_float=Decimal)

        metric_updates["design__instance__count"] = stats["design"]["num_cells"]
        if chip_area := stats["design"].get("area"):  # needs nonzero area
            metric_updates["design__instance__area"] = chip_area

        cells = stats["design"]["num_cells_by_type"]
        safe = ["$assert"]
        unmapped_cells = [
            cells[y] for y in cells.keys() if y not in safe and y.startswith("$")
        ]
        metric_updates["design__instance_unmapped__count"] = sum(unmapped_cells)

        check_error_count_file = os.path.join(
            self.step_dir, "reports", "pre_synth_chk.rpt"
        )
        metric_updates["synthesis__check_error__count"] = 0
        if os.path.exists(check_error_count_file):
            metric_updates["synthesis__check_error__count"] = _parse_yosys_check(
                check_error_count_file,
                self.config.TRISTATE_CELLS,
                self.config.SYNTH_CHECKS_ALLOW_TRISTATE,
                self.config.SYNTH_ELABORATE_ONLY,
            )

        view_updates[DesignFormat.NETLIST] = pathlib.Path(out_file)

        # Last, next to where the gates run, and for the same reason: the
        # netlist is produced first and then examined.
        self._check_assign_statements(out_file)

        return view_updates, metric_updates

    def _check_assign_statements(self, netlist_path: str) -> None:
        """
        ``assign`` statements are known to cause bugs in some PnR tools, so
        the netlist this step just wrote is scanned for them line by line.
        This isn't a :class:`~librelane.steps.step.MetricGate`: there's no
        metric to threshold, just a text pattern to flag, and the value of
        the check is in the per-line ``file:line`` locations it logs.
        """
        assign_rx = re.compile(r"^\s*\bassign\b")
        emit_error = self.config.ERROR_ON_NL_ASSIGN_STATEMENTS
        found = False
        with open(netlist_path, "r", encoding="utf8") as f:
            for i, line in enumerate(f, start=1):
                if assign_rx.search(line) is not None:
                    found = True
                    step_logger = logger.bind(step=self.id)
                    (step_logger.error if emit_error else step_logger.warning)(
                        f"{os.path.relpath(netlist_path)}:{i}: assign statement found in netlist"
                    )
        if found and emit_error:
            raise StepError("One or more assign statements found in the netlist.")


@Step.factory.register()
class Synthesis(SynthesisCommon):
    """
    Performs synthesis and technology mapping on Verilog RTL files
    using Yosys and ABC, emitting a netlist.

    Some metrics will also be extracted and updated, namely:

    * ``design__instance__count``
    * ``design__instance_unmapped__count``
    * ``design__instance__area``

    Note that Yosys steps do not currently support gzipped standard cell dotlib
    files. They are however supported for macros:

    https://github.com/YosysHQ/yosys/issues/4830
    """

    id = "Yosys.Synthesis"
    name = "Synthesis"

    class Config(VerilogRtlConfig, SynthesisCommon.Config):
        pass

    config: Config


@Step.factory.register()
class Resynthesis(SynthesisCommon):
    """
    Like ``Synthesis``, but operates on the input netlist instead of RTL files.
    Useful to process/elaborate on netlists generated by tools other than Yosys.

    Some metrics will also be extracted and updated, namely:

    * ``design__instance__count``
    * ``design__instance_unmapped__count``
    * ``design__instance__area``

    Note that Yosys steps do not currently support gzipped standard cell dotlib
    files. They are however supported for macros:

    https://github.com/YosysHQ/yosys/issues/4830
    """

    id = "Yosys.Resynthesis"
    name = "Resynthesis"

    class Config(SynthesisCommon.Config):
        pass

    config: Config

    inputs = [DesignFormat.NETLIST]

    def get_command(self, state_in):
        return super().get_command(state_in) + [state_in[DesignFormat.NETLIST]]


@Step.factory.register()
class VHDLSynthesis(SynthesisCommon):
    """
    Performs synthesis and technology mapping on VHDL files
    using Yosys, GHDL and ABC, emitting a netlist.

    Some metrics will also be extracted and updated, namely:

    * ``design__instance__count``
    * ``design__instance_unmapped__count``
    * ``design__instance__area``

    Note that Yosys steps do not currently support gzipped standard cell dotlib
    files. They are however supported for macros:

    https://github.com/YosysHQ/yosys/issues/4830
    """

    id = "Yosys.VHDLSynthesis"
    name = "Synthesis (VHDL)"

    class Config(SynthesisCommon.Config):
        VHDL_FILES: list[Path] = variable(
            description="The paths of the design's VHDL files.",
        )

        GHDL_ARGUMENTS: list[str] | None = variable(
            None,
            description="Pass arguments to the ghdl frontend.",
        )

    config: Config
