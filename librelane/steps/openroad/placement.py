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

from ...resources import package_path
from decimal import Decimal
from typing import (
    Optional,
)


from ...common import (
    Path,
)
from ...config import Variable
from ...state import State
from ..common_variables import (
    dpl_variables,
    routing_layer_variables,
    rsz_variables,
)
from ..step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OpenROADStep
from .floorplan import PPLMode, _validate_io_ppl_mode


class _GlobalPlacement(OpenROADStep):
    config_vars = (
        OpenROADStep.config_vars
        + routing_layer_variables
        + rsz_variables
        + [
            Variable(
                "PL_TARGET_DENSITY_PCT",
                Optional[Decimal],
                "The desired placement density of cells. If not specified, the value will be equal to (`FP_CORE_UTIL` + 5 * `GPL_CELL_PADDING` + 10).",
                units="%",
                deprecated_names=[
                    ("PL_TARGET_DENSITY", lambda d: Decimal(d) * Decimal("100"))
                ],
            ),
            Variable(
                "PL_SKIP_INITIAL_PLACEMENT",
                bool,
                "Specifies whether the placer should run initial placement or not.",
                default=False,
            ),
            Variable(
                "PL_WIRE_LENGTH_COEF",
                Decimal,
                "Global placement initial wirelength coefficient."
                + " Decreasing the variable will modify the initial placement of the standard cells to reduce the wirelengths",
                default=0.25,
                deprecated_names=["PL_WIRELENGTH_COEF"],
            ),
            Variable(
                "PL_MIN_PHI_COEFFICIENT",
                Optional[Decimal],
                "Sets a lower bound on the µ_k variable in the GPL algorithm. Useful if global placement diverges. See https://openroad.readthedocs.io/en/latest/main/src/gpl/README.html",
            ),
            Variable(
                "PL_MAX_PHI_COEFFICIENT",
                Optional[Decimal],
                "Sets a upper bound on the µ_k variable in the GPL algorithm. Useful if global placement diverges.See https://openroad.readthedocs.io/en/latest/main/src/gpl/README.html",
            ),
            Variable(
                "FP_CORE_UTIL",
                Decimal,
                "The core utilization percentage.",
                default=50,
                units="%",
            ),
            Variable(
                "GPL_CELL_PADDING",
                int,
                "Cell padding value (in sites) for global placement. The number will be integer divided by 2 and placed on both sides.",
                units="sites",
                pdk=True,
            ),
            Variable(
                "PL_KEEP_RESIZE_BELOW_OVERFLOW",
                Optional[Decimal],
                "Only applicable when PL_TIMING_DRIVEN is enabled. When the overflow is below the set value, timing-driven iterations will retain the resizer changes instead of reverting them. Allowed values are 0 to 1. If not set, a nonzero default value from OpenROAD will be used",
            ),
        ]
    )

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "gpl.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        if self.config["PL_TARGET_DENSITY_PCT"] is None:
            util = self.config["FP_CORE_UTIL"]
            metrics_util = state_in.metrics.get("design__instance__utilization")
            if metrics_util is not None:
                util = metrics_util * 100

            expr = util + (5 * self.config["GPL_CELL_PADDING"]) + 10
            expr = min(expr, 100)
            env["PL_TARGET_DENSITY_PCT"] = f"{expr}"
            logger.info(
                f"'PL_TARGET_DENSITY_PCT' not explicitly set, using dynamically calculated target density: {expr}…"
            )
        return super().run(state_in, env=env, **kwargs)


@Step.factory.register()
class GlobalPlacement(_GlobalPlacement):
    """
    Performs a somewhat nebulous initial placement for standard cells in a
    floorplan. While the placement is not concrete, it is enough to start
    accounting for issues such as fanout, transition time, et cetera.
    """

    id = "OpenROAD.GlobalPlacement"
    name = "Global Placement"

    config_vars = _GlobalPlacement.config_vars + [
        Variable(
            "PL_TIMING_DRIVEN",
            bool,
            "Specifies whether the placer should use timing-driven placement.",
            default=False,
            deprecated_names=["PL_TIME_DRIVEN"],
        ),
        Variable(
            "PL_ROUTABILITY_DRIVEN",
            bool,
            "Specifies whether the placer should use routability driven placement.",
            default=True,
        ),
        Variable(
            "PL_ROUTABILITY_OVERFLOW_THRESHOLD",
            Optional[Decimal],
            "Sets overflow threshold for routability mode.",
        ),
    ]


@Step.factory.register()
class GlobalPlacementSkipIO(_GlobalPlacement):
    """
    Performs preliminary global placement as a basis for pin placement.

    This is useful for flows where the:
    * Cells are placed
    * I/Os are placed to match the cells
    * Cells are then re-placed for an optimal placement
    """

    id = "OpenROAD.GlobalPlacementSkipIO"
    name = "Global Placement Skip IO"

    config_vars = _GlobalPlacement.config_vars + [
        Variable(
            "IO_PIN_PLACEMENT_MODE",
            PPLMode,
            "Decides the mode of the random IO placement option.",
            default="matching",
            deprecated_names=["FP_PPL_MODE"],
            validator=_validate_io_ppl_mode,
        ),
        # Only used by this step to skip:
        Variable(
            "IO_PIN_ORDER_CFG",
            Optional[Path],
            "Path to a custom pin configuration file.",
            deprecated_names=["FP_PIN_ORDER_CFG"],
        ),
        Variable(
            "FP_DEF_TEMPLATE",
            Optional[Path],
            "Points to the DEF file to be used as a template.",
        ),
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        if self.config["FP_DEF_TEMPLATE"] is not None:
            logger.info(
                f"I/O pins were loaded from {self.config['FP_DEF_TEMPLATE']}. Returning state unaltered…"
            )
            return {}, {}
        if self.config["IO_PIN_ORDER_CFG"] is not None:
            logger.info(
                f"I/O pins to be placed from {self.config['IO_PIN_ORDER_CFG']}. Returning state unaltered…"
            )
            return {}, {}
        env["__PL_SKIP_IO"] = "1"
        return super().run(state_in, env=env, **kwargs)


@Step.factory.register()
class DetailedPlacement(OpenROADStep):
    """
    Performs "detailed placement" on an ODB file with global placement. This results
    in a concrete and legal placement of all cells.
    """

    id = "OpenROAD.DetailedPlacement"
    name = "Detailed Placement"

    config_vars = OpenROADStep.config_vars + dpl_variables

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "dpl.tcl")
