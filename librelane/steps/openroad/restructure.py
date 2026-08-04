# Copyright 2026 LibreLane Contributors
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
import os
from decimal import Decimal
from importlib.resources import files
from typing import Literal

from librelane.common import process_list_file
from librelane.config import variable
from librelane.state import State
from librelane.steps.openroad.base import OpenROADStep
from librelane.steps.step import MetricsUpdate, Step, StepError, ViewsUpdate
from librelane.steps.tclstep import TclStep


@Step.factory.register()
class RMP(OpenROADStep):
    """
    Resynthesizes clouds of logic in-place using OpenROAD's ``rmp`` module,
    which hands them to ABC and keeps the result if it is an improvement.

    ``RMP_TARGET`` picks what "improvement" means. ``area`` reduces cell area
    and may degrade timing; ``timing`` reduces delay on the paths selected by
    ``RMP_SLACK_THRESHOLD`` and ``RMP_DEPTH_THRESHOLD`` and may increase area.

    ABC remaps the extracted logic with no knowledge of the buffering the
    netlist arrived with, so by default the step follows the resynthesis with
    ``remove_buffers`` and leaves rebuffering to the repair and resizer steps
    that run on the placed design.

    This step is experimental. It is part of the Classic flow but disabled by
    default; set ``RUN_RMP`` to enable it.
    """

    id = "OpenROAD.RMP"
    name = "Restructure"
    long_name = "Local Resynthesis"

    class Config(OpenROADStep.Config):
        RMP_CORNER: str | None = variable(
            None,
            description="IPVT corner whose liberty file is handed to ABC during restructuring. If unspecified, the value for `DEFAULT_CORNER` from the PDK will be used.",
        )

        RMP_TARGET: Literal["timing", "area"] = variable(
            "area",
            description="What restructuring optimizes for. In area mode, the focus is area reduction, and timing may degrade. In timing mode, delay is likely reduced, but the area may increase.",
        )

        RMP_SLACK_THRESHOLD: Decimal | None = variable(
            None,
            description="Specifies a (setup) timing slack value below which timing paths need to be analyzed for restructuring. Only meaningful when `RMP_TARGET` is `timing`.",
            units="ns",
        )

        RMP_DEPTH_THRESHOLD: int | None = variable(
            None,
            description="Specifies the path depth above which a timing path would be considered for restructuring. Only meaningful when `RMP_TARGET` is `timing`.",
        )

        RMP_REMOVE_BUFFERS: bool = variable(
            True,
            description="Invokes OpenROAD's remove_buffers command after restructuring, so that the buffer trees are rebuilt from the placed design rather than left as a mixture of the pre- and post-resynthesis ones.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "restructure.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        lib_list = self.toolbox.filter_views(
            self.config, self.config.LIB, self.config.RMP_CORNER
        )

        excluded_cells: set[str] = set(self.config.EXTRA_EXCLUDED_CELLS or [])
        excluded_cells.update(process_list_file(self.config.SYNTH_EXCLUDED_CELL_FILE))
        excluded_cells.update(process_list_file(self.config.PNR_EXCLUDED_CELL_FILE))

        trimmed_libs = self.toolbox.remove_cells_from_lib(
            frozenset([str(lib) for lib in lib_list]),
            excluded_cells=frozenset(excluded_cells),
        )

        # OpenROAD's restructure takes exactly one -liberty_file, which it
        # passes to a single ABC read_lib. There is no correct way to pick one
        # of several, so say so instead of silently restructuring against a
        # fraction of the standard cell library.
        corner = self.config.RMP_CORNER or self.config.DEFAULT_CORNER
        if len(trimmed_libs) != 1:
            raise StepError(
                f"OpenROAD's restructure accepts exactly one liberty file, but corner '{corner}' has {len(trimmed_libs)}."
            )

        env["_RMP_LIB"] = TclStep.value_to_tcl(trimmed_libs[0])
        env["_RMP_ABC_LOG"] = TclStep.value_to_tcl(
            os.path.join(self.step_dir, "abc.log")
        )

        return super().run(state_in, env=env, **kwargs)
