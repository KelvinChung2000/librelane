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
from ...resources import package_path
from decimal import Decimal
from typing import (
    Optional,
)


from ...config import Variable
from ..step import (
    Step,
)

from .resizer import ResizerStep


@Step.factory.register()
class RepairDesignPostGPL(ResizerStep):
    """
    Runs a number of design "repairs" on a global-placed ODB file.
    """

    id = "OpenROAD.RepairDesignPostGPL"
    name = "Repair Design (Post-Global Placement)"

    config_vars = ResizerStep.config_vars + [
        Variable(
            "DESIGN_REPAIR_BUFFER_INPUT_PORTS",
            bool,
            "Specifies whether or not to insert buffers on input ports when design repairs are run.",
            default=True,
            deprecated_names=["PL_RESIZER_BUFFER_INPUT_PORTS"],
        ),
        Variable(
            "DESIGN_REPAIR_BUFFER_OUTPUT_PORTS",
            bool,
            "Specifies whether or not to insert buffers on output ports when design repairs are run.",
            default=True,
            deprecated_names=["PL_RESIZER_BUFFER_OUTPUT_PORTS"],
        ),
        Variable(
            "DESIGN_REPAIR_TIE_FANOUT",
            bool,
            "Specifies whether or not to repair tie cells fanout when design repairs are run.",
            default=True,
            deprecated_names=["PL_RESIZER_REPAIR_TIE_FANOUT"],
        ),
        Variable(
            "DESIGN_REPAIR_TIE_SEPARATION",
            bool,
            "Allows tie separation when performing design repairs.",
            default=False,
            deprecated_names=["PL_RESIZER_TIE_SEPERATION"],
        ),
        Variable(
            "DESIGN_REPAIR_MAX_WIRE_LENGTH",
            Decimal,
            "Specifies the maximum wire length cap used by resizer to insert buffers during design repair. If set to 0, no buffers will be inserted.",
            default=0,
            units="µm",
            deprecated_names=["PL_RESIZER_MAX_WIRE_LENGTH"],
        ),
        Variable(
            "DESIGN_REPAIR_MAX_SLEW_PCT",
            Decimal,
            "Specifies a margin for the slews during design repair.",
            default=20,
            units="%",
            deprecated_names=["PL_RESIZER_MAX_SLEW_MARGIN"],
        ),
        Variable(
            "DESIGN_REPAIR_MAX_CAP_PCT",
            Decimal,
            "Specifies a margin for the capacitances during design repair.",
            default=20,
            units="%",
            deprecated_names=["PL_RESIZER_MAX_CAP_MARGIN"],
        ),
        Variable(
            "DESIGN_REPAIR_REMOVE_BUFFERS",
            bool,
            "Invokes OpenROAD's remove_buffers command to remove buffers from synthesis, which gives OpenROAD more flexibility when buffering nets.",
            default=False,
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "repair_design.tcl")


@Step.factory.register()
class RepairDesign(RepairDesignPostGPL):
    """
    This is identical to OpenROAD.RepairDesignPostGPL. It is retained for backwards compatibility.
    """

    id = "OpenROAD.RepairDesign"
    name = "Repair Design (Post-Global Placement)"


@Step.factory.register()
class RepairDesignPostGRT(ResizerStep):
    """
    Runs a number of design "repairs" on a global-routed ODB file.
    """

    id = "OpenROAD.RepairDesignPostGRT"
    name = "Repair Design (Post-Global Routing)"

    config_vars = ResizerStep.config_vars + [
        Variable(
            "GRT_DESIGN_REPAIR_RUN_GRT",
            bool,
            "Enables running GRT before and after running resizer",
            default=True,
        ),
        Variable(
            "GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH",
            Decimal,
            "Specifies the maximum wire length cap used by resizer to insert buffers during post-grt design repair. If set to 0, no buffers will be inserted.",
            default=0,
            units="µm",
            deprecated_names=["GLB_RESIZER_MAX_WIRE_LENGTH"],
        ),
        Variable(
            "GRT_DESIGN_REPAIR_MAX_SLEW_PCT",
            Decimal,
            "Specifies a margin for the slews during post-grt design repair.",
            default=10,
            units="%",
            deprecated_names=["GLB_RESIZER_MAX_SLEW_MARGIN"],
        ),
        Variable(
            "GRT_DESIGN_REPAIR_MAX_CAP_PCT",
            Decimal,
            "Specifies a margin for the capacitances during design post-grt repair.",
            default=10,
            units="%",
            deprecated_names=["GLB_RESIZER_MAX_CAP_MARGIN"],
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath(
            "scripts", "openroad", "repair_design_postgrt.tcl"
        )


@Step.factory.register()
class ResizerTimingPostCTS(ResizerStep):
    """
    First attempt to meet timing requirements for a cell based on basic timing
    information after clock tree synthesis.

    Standard cells may be resized, and buffer cells may be inserted to ensure
    that no hold violations exist and no setup violations exist at the current
    clock.
    """

    id = "OpenROAD.ResizerTimingPostCTS"
    name = "Resizer Timing Optimizations (Post-Clock Tree Synthesis)"

    config_vars = ResizerStep.config_vars + [
        Variable(
            "PL_RESIZER_HOLD_SLACK_MARGIN",
            Decimal,
            "Specifies a time margin for the slack when fixing hold violations. Normally the resizer will stop when it reaches zero slack. This option allows you to overfix.",
            default=0.1,
            units="ns",
        ),
        Variable(
            "PL_RESIZER_SETUP_SLACK_MARGIN",
            Decimal,
            "Specifies a time margin for the slack when fixing setup violations.",
            default=0.05,
            units="ns",
        ),
        Variable(
            "PL_RESIZER_HOLD_MAX_BUFFER_PCT",
            Decimal,
            "Specifies a max number of buffers to insert to fix hold violations. This number is calculated as a percentage of the number of instances in the design.",
            default=50,
            deprecated_names=["PL_RESIZER_HOLD_MAX_BUFFER_PERCENT"],
        ),
        Variable(
            "PL_RESIZER_SETUP_MAX_BUFFER_PCT",
            Decimal,
            "Specifies a max number of buffers to insert to fix setup violations. This number is calculated as a percentage of the number of instances in the design.",
            default=50,
            units="%",
            deprecated_names=["PL_RESIZER_SETUP_MAX_BUFFER_PERCENT"],
        ),
        Variable(
            "PL_RESIZER_ALLOW_SETUP_VIOS",
            bool,
            "Allows the creation of setup violations when fixing hold violations. Setup violations are less dangerous as they simply mean a chip may not run at its rated speed, however, chips with hold violations are essentially dead-on-arrival.",
            default=False,
        ),
        Variable(
            "PL_RESIZER_SETUP_GATE_CLONING",
            bool,
            "Enables gate cloning when attempting to fix setup violations",
            default=True,
            deprecated_names=["PL_RESIZER_GATE_CLONING"],
        ),
        Variable(
            "PL_RESIZER_SETUP_BUFFERING",
            bool,
            "Rebuffering and load splitting during setup fixing.",
            default=True,
        ),
        Variable(
            "PL_RESIZER_SETUP_BUFFER_REMOVAL",
            bool,
            "Buffer removal transform during setup fixing.",
            default=True,
        ),
        Variable(
            "PL_RESIZER_SETUP_REPAIR_TNS_PCT",
            Optional[Decimal],
            "Percentage of violating endpoints to repair during setup fixing.",
            units="%",
        ),
        Variable(
            "PL_RESIZER_SETUP_MAX_UTIL_PCT",
            Optional[Decimal],
            "Defines the percentage of core area used during setup fixing.",
            units="%",
        ),
        Variable(
            "PL_RESIZER_HOLD_REPAIR_TNS_PCT",
            Optional[Decimal],
            "Percentage of violating endpoints to repair during hold fixing.",
            units="%",
        ),
        Variable(
            "PL_RESIZER_HOLD_MAX_UTIL_PCT",
            Optional[Decimal],
            "Defines the percentage of core area used during hold fixing.",
            units="%",
        ),
        Variable(
            "PL_RESIZER_FIX_HOLD_FIRST",
            bool,
            "Experimental: attempt to fix hold violations before setup violations, which may lead to better timing results.",
            default=False,
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "rsz_timing_postcts.tcl")


@Step.factory.register()
class ResizerTimingPostGRT(ResizerStep):
    """
    Second attempt to meet timing requirements for a cell based on timing
    information after estimating resistance and capacitance values based on
    global routing.

    Standard cells may be resized, and buffer cells may be inserted to ensure
    that no hold violations exist and no setup violations exist at the current
    clock.
    """

    id = "OpenROAD.ResizerTimingPostGRT"
    name = "Resizer Timing Optimizations (Post-Global Routing)"

    config_vars = ResizerStep.config_vars + [
        Variable(
            "GRT_RESIZER_HOLD_SLACK_MARGIN",
            Decimal,
            "Specifies a time margin for the slack when fixing hold violations. Normally the resizer will stop when it reaches zero slack. This option allows you to overfix.",
            default=0.05,
            units="ns",
            deprecated_names=["GLB_RESIZER_HOLD_SLACK_MARGIN"],
        ),
        Variable(
            "GRT_RESIZER_SETUP_SLACK_MARGIN",
            Decimal,
            "Specifies a time margin for the slack when fixing setup violations.",
            default=0.025,
            units="ns",
            deprecated_names=["GLB_RESIZER_SETUP_SLACK_MARGIN"],
        ),
        Variable(
            "GRT_RESIZER_HOLD_MAX_BUFFER_PCT",
            Decimal,
            "Specifies a max number of buffers to insert to fix hold violations. This number is calculated as a percentage of the number of instances in the design.",
            default=50,
            units="%",
            deprecated_names=["GLB_RESIZER_HOLD_MAX_BUFFER_PERCENT"],
        ),
        Variable(
            "GRT_RESIZER_SETUP_MAX_BUFFER_PCT",
            Decimal,
            "Specifies a max number of buffers to insert to fix setup violations. This number is calculated as a percentage of the number of instances in the design.",
            default=50,
            units="%",
            deprecated_names=["GLB_RESIZER_SETUP_MAX_BUFFER_PERCENT"],
        ),
        Variable(
            "GRT_RESIZER_ALLOW_SETUP_VIOS",
            bool,
            "Allows setup violations when fixing hold.",
            default=False,
            deprecated_names=["GLB_RESIZER_ALLOW_SETUP_VIOS"],
        ),
        Variable(
            "GRT_RESIZER_SETUP_GATE_CLONING",
            bool,
            "Enables gate cloning when attempting to fix setup violations",
            default=True,
            deprecated_names=["GRT_RESIZER_GATE_CLONING"],
        ),
        Variable(
            "GRT_RESIZER_RUN_GRT",
            bool,
            "Gates running global routing after resizer steps. May be useful to disable for designs where global routing takes non-trivial time.",
            default=True,
        ),
        Variable(
            "GRT_RESIZER_SETUP_BUFFERING",
            bool,
            "Rebuffering and load splitting during setup fixing.",
            default=True,
        ),
        Variable(
            "GRT_RESIZER_SETUP_BUFFER_REMOVAL",
            bool,
            "Buffer removal transform during setup fixing.",
            default=True,
        ),
        Variable(
            "GRT_RESIZER_SETUP_REPAIR_TNS_PCT",
            Optional[Decimal],
            "Percentage of violating endpoints to repair during setup fixing.",
            units="%",
        ),
        Variable(
            "GRT_RESIZER_SETUP_MAX_UTIL_PCT",
            Optional[Decimal],
            "Defines the percentage of core area used during setup fixing.",
            units="%",
        ),
        Variable(
            "GRT_RESIZER_HOLD_REPAIR_TNS_PCT",
            Optional[Decimal],
            "Percentage of violating endpoints to repair during hold fixing.",
            units="%",
        ),
        Variable(
            "GRT_RESIZER_HOLD_MAX_UTIL_PCT",
            Optional[Decimal],
            "Defines the percentage of core area used during hold fixing.",
            units="%",
        ),
        Variable(
            "GRT_RESIZER_FIX_HOLD_FIRST",
            bool,
            "Experimental: attempt to fix hold violations before setup violations, which may lead to better timing results.",
            default=False,
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath("scripts", "openroad", "rsz_timing_postgrt.tcl")
