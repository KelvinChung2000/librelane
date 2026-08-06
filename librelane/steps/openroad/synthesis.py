# Copyright 2026 LibreLane Contributors
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
from importlib.resources import files
from typing import Optional

from librelane.common import process_list_file
from librelane.config import variable
from librelane.state import DesignFormat, State
from librelane.steps.pyosys import VerilogRtlConfig
from librelane.steps.step import MetricsUpdate, Step, ViewsUpdate
from librelane.steps.openroad.base import OpenROADStep
from librelane.steps.tclstep import TclStep


@Step.factory.register()
class Synthesis(OpenROADStep):
    """
    Synthesizes SystemVerilog RTL using OpenROAD's integrated synthesis
    module: slang elaborates the sources (``sv_elaborate``) and the built-in
    mapper implements them with the standard cell library (``synthesize``),
    writing the gate-level netlist out of OpenROAD's own database.

    This is not Yosys: the module is an independent implementation
    contributed by Precision Innovations, with its own intermediate
    representation. Note its current upstream limitations: no latch mapping,
    the hierarchy is always flattened, and macro instance names are not
    preserved -- designs relying on ``SYNTH_HIERARCHY_MODE: keep`` or
    ``MACROS`` should use the ``yosys`` provider.
    """

    id = "OpenROAD.Synthesis"
    name = "Synthesis (OpenROAD Integrated)"

    inputs = []
    outputs = [DesignFormat.NETLIST]

    class Config(VerilogRtlConfig, OpenROADStep.Config):
        SYNTH_REDUCE_NAME_LOSS: bool = variable(
            False,
            description="Disable optimization steps that would cause mass loss of intermediate signal names, trading quality of results for interpretability.",
        )

        SYNTH_NAMING_THRESHOLD: Optional[int] = variable(
            None,
            description="Preserve names on nets whose fanout meets this threshold during optimizations that would otherwise lose them. A lighter-touch alternative to SYNTH_REDUCE_NAME_LOSS.",
            units="cells",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "syn.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        scl_lib_list = self.toolbox.filter_views(self.config, self.config.LIB)
        excluded_cells: set[str] = set(self.config.EXTRA_EXCLUDED_CELLS or [])
        excluded_cells.update(process_list_file(self.config.SYNTH_EXCLUDED_CELL_FILE))
        excluded_cells.update(process_list_file(self.config.PNR_EXCLUDED_CELL_FILE))
        env["_SYNTH_LIBS"] = TclStep.value_to_tcl(
            list(
                self.toolbox.remove_cells_from_lib(
                    frozenset(str(lib) for lib in scl_lib_list),
                    excluded_cells=frozenset(excluded_cells),
                )
            )
        )

        return super().run(state_in, env=env, **kwargs)
