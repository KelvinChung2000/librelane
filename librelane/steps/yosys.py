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

import os
import textwrap
import subprocess
from abc import abstractmethod
from typing import Literal, Optional

from librelane.steps.tclstep import TclStep
from librelane.steps.step import ViewsUpdate, MetricsUpdate, Step, StepException
from librelane.steps.pyosys import (
    PyosysStep,
    JsonHeader,
    VerilogRtlConfig,
    Synthesis,
    VHDLSynthesis,
)

from librelane.config import variable
from librelane.state import State, DesignFormat
from librelane.common import Path, Toolbox, TclUtils, process_list_file

# Re-export for back-compat
JsonHeader
Synthesis
VHDLSynthesis


# This is now only used by EQY since we moved our Yosys scripts to Python.
def _generate_read_deps(
    config: "YosysStep.Config",
    toolbox: Toolbox,
    power_defines: bool = False,
    tcl: bool = True,
) -> str:
    commands = ""

    synth_defines = [
        f"PDK_{config.PDK.replace('-', '_')}",
        f"SCL_{config.STD_CELL_LIBRARY}",
        "__librelane__",
        "__pnr__",
    ]
    synth_defines += config.VERILOG_DEFINES or []
    if tcl:
        commands += "set ::_synlig_defines [list]\n"
    for define in synth_defines:
        commands += f"verilog_defines {TclUtils.escape(f'-D{define}')}\n"
        if tcl:
            commands += (
                f"lappend ::_synlig_defines {TclUtils.escape(f'+define+{define}')}\n"
            )

    scl_lib_list = toolbox.filter_views(config, config.LIB)

    if power_defines:
        if power_define := config.VERILOG_POWER_DEFINE:
            commands += f"verilog_defines {TclUtils.escape(f'-D{power_define}')}\n"
            if tcl:
                commands += f"lappend ::_synlig_defines {TclUtils.escape(f'+define+{power_define}')}\n"

    # Try your best to use powered blackbox models if power_defines is true
    if power_defines:
        if config.CELL_VERILOG_MODELS is not None:
            scl_blackbox_models = toolbox.create_blackbox_model(
                frozenset(config.CELL_VERILOG_MODELS),
                frozenset(["USE_POWER_PINS"]),
            )
            commands += f"read_verilog -sv -lib {scl_blackbox_models}\n"
        if config.PAD_VERILOG_MODELS is not None:
            pad_blackbox_models = toolbox.create_blackbox_model(
                frozenset(config.PAD_VERILOG_MODELS),
                frozenset(["USE_POWER_PINS"]),
            )
            commands += f"read_verilog -sv -lib {pad_blackbox_models}\n"
    else:
        # Fall back to scl_lib_list if you cant
        for lib in scl_lib_list:
            lib_str = TclUtils.escape(str(lib))
            commands += (
                f"read_liberty -lib -ignore_miss_dir -setattr blackbox {lib_str}\n"
            )

    excluded_cells: set[str] = set(config.EXTRA_EXCLUDED_CELLS or [])
    excluded_cells.update(process_list_file(config.SYNTH_EXCLUDED_CELL_FILE))
    excluded_cells.update(process_list_file(config.PNR_EXCLUDED_CELL_FILE))

    lib_synth = toolbox.remove_cells_from_lib(
        frozenset([str(lib) for lib in scl_lib_list]),
        excluded_cells=frozenset(excluded_cells),
    )
    if tcl:
        commands += (
            f"set ::env(SYNTH_LIBS) {TclUtils.escape(TclUtils.join(lib_synth))}\n"
        )

    verilog_include_args = []
    if dirs := config.VERILOG_INCLUDE_DIRS:
        for dir in dirs:
            verilog_include_args.append(f"-I{dir}")

    # Priorities from higher to lower
    format_list = (
        [
            DesignFormat.VERILOG_HEADER,
            DesignFormat.POWERED_NETLIST,
            DesignFormat.NETLIST,
            DesignFormat.LIB,
        ]
        if power_defines
        else [
            DesignFormat.VERILOG_HEADER,
            DesignFormat.NETLIST,
            DesignFormat.POWERED_NETLIST,
            DesignFormat.LIB,
        ]
    )
    for view, format in toolbox.get_macro_views_by_priority(config, format_list):
        view_escaped = TclUtils.escape(str(view))
        if format == DesignFormat.LIB:
            commands += (
                f"read_liberty -lib -ignore_miss_dir -setattr blackbox {view_escaped}\n"
            )
        else:
            commands += f"read_verilog -sv -lib {TclUtils.join(verilog_include_args)} {view_escaped}\n"

    if libs := config.EXTRA_LIBS:
        for lib in libs:
            lib_str = TclUtils.escape(str(lib))
            commands += (
                f"read_liberty -lib -ignore_miss_dir -setattr blackbox {lib_str}\n"
            )

    if models := config.EXTRA_VERILOG_MODELS:
        for model in models:
            model_str = TclUtils.escape(str(model))
            commands += f"read_verilog -sv -lib {TclUtils.join(verilog_include_args)} {model_str}\n"

    return commands


# No longer used by us, kept for back-compat
class YosysStep(TclStep):
    # VerilogRtlConfig, because run() renders _generate_read_deps commands,
    # which read the Verilog source variables.
    class Config(VerilogRtlConfig, Step.Config):
        SYNTH_LATCH_MAP: Optional[Path] = variable(
            None,
            description="A path to a file containing the latch mapping for Yosys.",
            pdk=True,
        )

        SYNTH_TRISTATE_MAP: Optional[Path] = variable(
            None,
            description="A path to a file containing the tri-state buffer mapping for Yosys.",
            deprecated_names=["TRISTATE_BUFFER_MAP"],
            pdk=True,
        )

        SYNTH_CSA_MAP: Optional[Path] = variable(
            None,
            description="A path to a file containing the carry-select adder mapping for Yosys.",
            deprecated_names=["CARRY_SELECT_ADDER_MAP"],
            pdk=True,
        )

        SYNTH_RCA_MAP: Optional[Path] = variable(
            None,
            description="A path to a file containing the ripple-carry adder mapping for Yosys.",
            deprecated_names=["RIPPLE_CARRY_ADDER_MAP"],
            pdk=True,
        )

        SYNTH_FA_MAP: Optional[Path] = variable(
            None,
            description="A path to a file containing the full adder mapping for Yosys.",
            deprecated_names=["FULL_ADDER_MAP"],
            pdk=True,
        )

        YOSYS_LOG_LEVEL: Literal["ALL", "WARNING", "ERROR"] = variable(
            "ALL",
            description="Which log level for Yosys. At WARNING or higher, the initialization splash is also disabled.",
        )

    config: Config

    @classmethod
    def get_yosys_path(Self) -> str:
        return PyosysStep.get_yosys_path()

    @abstractmethod
    def get_script_path(self) -> str:
        pass

    def get_command(self) -> list[str]:
        script_path = self.get_script_path()
        cmd = [self.get_yosys_path(), "-c", script_path]
        if self.config.YOSYS_LOG_LEVEL != "ALL":
            cmd += ["-Q"]
        if self.config.YOSYS_LOG_LEVEL == "WARNING":
            cmd += ["-q"]
        elif self.config.YOSYS_LOG_LEVEL == "ERROR":
            cmd += ["-qq"]
        return cmd

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        power_defines = False
        if "power_defines" in kwargs:
            power_defines = kwargs.pop("power_defines")

        kwargs, env = self.extract_env(kwargs)

        _deps_script = os.path.join(self.step_dir, "_deps.tcl")

        with open(_deps_script, "w") as f:
            f.write(
                _generate_read_deps(
                    self.config, self.toolbox, power_defines=power_defines
                )
            )

        env["_DEPS_SCRIPT"] = _deps_script

        return super().run(state_in, env=env, **kwargs)


@Step.factory.register()
class EQY(Step):
    """
    Experimental: Uses the `EQY <https://github.com/yosyshq/eqy>`_ utility to
    perform an RTL vs. Netlist equivalence check.

    Currently, you are expected to provide your own EQY script if you want this
    to work properly.
    """

    id = "Yosys.EQY"
    name = "Equivalence Check"
    long_name = "RTL/Netlist Equivalence Check"

    inputs = [DesignFormat.NETLIST]
    outputs = []

    class Config(YosysStep.Config):
        EQY_SCRIPT: Optional[Path] = variable(
            None,
            description="The EQY script to use. If unset, a generic EQY script will be generated, but this fails in a number of scenarios.",
        )

        MACRO_PLACEMENT_CFG: Optional[Path] = variable(
            None,
            description="This step will warn if this deprecated variable is used, as it indicates Macros are used without the new Macro object.",
        )

        EQY_FORCE_ACCEPT_PDK: bool = variable(
            False,
            description="Attempt to run EQY even if the PDK's Verilog models are supported by this step. Will likely result in a failure.",
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        processed_pdk = os.path.join(self.step_dir, "formal_pdk.v")

        supported_pdk = self.config.PDK.startswith("sky130A")
        if not supported_pdk and not self.config.EQY_FORCE_ACCEPT_PDK:
            logger.info(
                f"PDK {self.config.PDK} is not supported by the EQY step. Skipping '{self.id}'…"
            )
            return {}, {}

        models = self.config.CELL_VERILOG_MODELS
        if models is None:
            raise StepException(
                "The standard cell library declares no 'CELL_VERILOG_MODELS' to process."
            )

        if supported_pdk:
            subprocess.check_call(
                [
                    "eqy.formal_pdk_proc",
                    "--output",
                    processed_pdk,
                ]
                + [str(model) for model in models]
            )
        else:
            subprocess.check_call(
                ["iverilog", "-E", "-o", processed_pdk, "-DFUNCTIONAL"]
                + [str(model) for model in models]
            )

        eqy_script_path = os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.eqy")

        with open(eqy_script_path, "w", encoding="utf8") as f:
            if eqy_script := self.config.EQY_SCRIPT:
                for line in open(eqy_script, "r", encoding="utf8"):
                    f.write(line)
            else:
                script = textwrap.dedent(
                    """
                    [script]
                    {dep_commands}
                    blackbox

                    [gold]
                    read_verilog -formal -sv {files}

                    [gate]
                    read_verilog -formal -sv {processed_pdk} {nl}

                    [script]
                    hierarchy -top {design_name}
                    proc
                    prep -top {design_name} -flatten

                    memory -nomap
                    async2sync

                    [gold]
                    write_verilog {step_dir}/gold.v
                    
                    [gate]
                    write_verilog {step_dir}/gate.v

                    [strategy sat]
                    use sat
                    depth 5

                    [strategy pdr]
                    use sby
                    engine abc pdr -rfi

                    [strategy bitwuzla]
                    use sby
                    depth 2
                    engine smtbmc bitwuzla
                    """
                ).format(
                    design_name=self.config.DESIGN_NAME,
                    dep_commands=_generate_read_deps(
                        self.config, self.toolbox, tcl=False
                    ),
                    files=TclUtils.join(
                        [str(file) for file in self.config.VERILOG_FILES]
                    ),
                    nl=state_in[DesignFormat.NETLIST],
                    processed_pdk=processed_pdk,
                    step_dir=self.step_dir,
                )
                f.write(script)
        work_dir = os.path.join(self.step_dir, "scratch")

        subprocess_result = self.run_subprocess(
            ["eqy", "-f", eqy_script_path, "-d", work_dir]
        )

        return {}, subprocess_result["generated_metrics"]
