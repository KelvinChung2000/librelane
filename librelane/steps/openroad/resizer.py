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
    Literal,
    Optional,
)


from ...common import (
    TclUtils,
)
from ...config import Variable
from ...state import State
from ..common_variables import (
    dpl_variables,
    grt_variables,
    rsz_variables,
)
from ..step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OpenROADStep


class ResizerStep(OpenROADStep):
    config_vars = OpenROADStep.config_vars + grt_variables + rsz_variables

    def run(
        self,
        state_in,
        **kwargs,
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        return super().run(
            state_in,
            corners=self.config["RSZ_CORNERS"] or self.config["STA_CORNERS"],
            env=env,
            **kwargs,
        )


@Step.factory.register()
class CTS(OpenROADStep):
    """
    Creates a `Clock tree <https://en.wikipedia.org/wiki/Clock_signal#Distribution>`_
    for an ODB file with detailed-placed cells, using reasonably accurate resistance
    and capacitance estimations. Detailed Placement is then re-performed to
    accommodate the new cells.
    """

    id = "OpenROAD.CTS"
    name = "Clock Tree Synthesis"

    config_vars = (
        OpenROADStep.config_vars
        + dpl_variables
        + [
            # sink_buffer_max_cap_derate
            Variable(
                "CTS_BALANCE_LEVELS",
                Optional[bool],
                "Attempts to keep a similar number of levels in the clock tree across non-register cells (e.g., clock-gate or inverter).",
            ),
            Variable(
                "CTS_SINK_BUFFER_MAX_CAP_DERATE_PCT",
                Optional[Decimal],
                "Controls automatic buffer selection. To favor strong(weak) drive strength buffers use a small(large) value."
                + "The value of 100 means no derating of max cap limit",
                units="%",
            ),
            Variable(
                "CTS_DELAY_BUFFER_DERATE_PCT",
                Optional[Decimal],
                "This option balances latencies between macro cells and registers by inserting delay buffers"
                + "The value of 100 means all needed delay buffers are inserted",
                units="%",
            ),
            Variable(
                "CTS_OBSTRUCTION_AWARE",
                Optional[bool],
                "Enables obstruction-aware buffering such that clock buffers are not placed on top of blockages or hard macros. "
                + "This option may reduce legalizer displacement, leading to better latency, skew or timing QoR.",
            ),
            Variable(
                "CTS_SINK_CLUSTERING_ENABLE",
                bool,
                "Enables pre-clustering of sinks to create one level of sub-tree before building the H-tree. "
                + "Each cluster is driven by a buffer which becomes the end point of the H-tree structure.",
                default=True,
            ),
            Variable(
                "CTS_SINK_CLUSTERING_SIZE",
                Optional[int],
                "Specifies the maximum number of sinks per cluster.",
            ),
            Variable(
                "CTS_SINK_CLUSTERING_MAX_DIAMETER",
                Optional[Decimal],
                "Specifies the maximum diameter of the sink cluster.",
                units="µm",
            ),
            Variable(
                "CTS_MACRO_CLUSTERING_SIZE",
                Optional[int],
                "Specifies the maximum number of sinks per cluster for the macro tree.",
            ),
            Variable(
                "CTS_MACRO_CLUSTERING_MAX_DIAMETER",
                Optional[Decimal],
                "Specifies the maximum diameter of the sink cluster for the macro tree.",
                units="µm",
            ),
            Variable(
                "CTS_CLK_MAX_WIRE_LENGTH",
                Decimal,
                "Specifies the maximum wire length on the clock net.",
                default=0,
                units="µm",
            ),
            Variable(
                "CTS_DISABLE_POST_PROCESSING",
                bool,
                "Specifies whether or not to disable post cts processing for outlier sinks.",
                default=False,
            ),
            Variable(
                "CTS_DISTANCE_BETWEEN_BUFFERS",
                Decimal,
                "Specifies the distance between buffers when creating the clock tree.",
                default=0,
                units="µm",
            ),
            Variable(
                "CTS_CORNERS",
                Optional[list[str]],
                "Clock tree synthesis step-specific override for PNR_CORNERS.",
            ),
            Variable(
                "CTS_ROOT_BUFFER",
                str,
                "Defines the cell inserted at the root of the clock tree. Used in CTS.",
                pdk=True,
            ),
            Variable(
                "CTS_CLK_BUFFERS",
                list[str],
                "Defines the list of clock buffer names or buffer name wildcards to be used in CTS.",
                deprecated_names=["CTS_CLK_BUFFER_LIST"],
                pdk=True,
            ),
            Variable(
                "CTS_MAX_CAP",
                Optional[Decimal],
                "Overrides the maximum capacitance CTS characterization will test. If omitted, the capacitance is extracted from the lib information of the buffers in CTS_CLK_BUFFERS.",
                units="pF",
            ),
            Variable(
                "CTS_MAX_SLEW",
                Optional[Decimal],
                "Overrides the maximum transition time CTS characterization will test. If omitted, the slew is extracted from the lib information of the buffers in CTS_CLK_BUFFERS.",
                units="ns",
            ),
            Variable(
                "CTS_APPLY_NDR",
                Literal["none", "root_only", "half", "full"],
                "Applies 2X spacing non-default rule to clock nets except leaf-level nets following some strategy. There are four strategy options: 'none', 'root_only', 'half', 'full'.",
                default="half",
            ),
        ]
    )

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "cts.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        if self.config.get("CLOCK_NET") is None:
            if clock_port := self.config["CLOCK_PORT"]:
                if isinstance(clock_port, list):
                    env["CLOCK_NET"] = TclUtils.join(clock_port)
                else:
                    env["CLOCK_NET"] = clock_port
            else:
                logger.bind(step=self.id).warning(
                    "No CLOCK_NET (or CLOCK_PORT) specified. CTS cannot be performed. Returning state unaltered…"
                )
                return {}, {}

        views_updates, metrics_updates = super().run(
            state_in,
            corners=self.config["CTS_CORNERS"] or self.config["STA_CORNERS"],
            env=env,
            **kwargs,
        )

        return views_updates, metrics_updates
