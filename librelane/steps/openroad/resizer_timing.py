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
from importlib.resources import files
from decimal import Decimal
from typing import (
    Optional,
)


from librelane.config import variable
from librelane.steps.step import (
    Step,
)

from librelane.steps.openroad.resizer import ResizerStep


@Step.factory.register()
class AddBuffer(ResizerStep):
    """
    Inserts buffers on the input and output ports of the design, before global
    placement, so that global placement knows about them and places the logic
    around them accordingly.

    Buffering the ports after global placement instead leaves the port buffers
    wherever the cells they drive are not, which costs routing time on
    area-constrained designs.
    """

    id = "OpenROAD.AddBuffer"
    name = "Add Buffers on Ports"

    class Config(ResizerStep.Config):
        DESIGN_REPAIR_BUFFER_INPUT_PORTS: bool = variable(
            True,
            description="Specifies whether or not to insert buffers on input ports.",
            deprecated_names=["PL_RESIZER_BUFFER_INPUT_PORTS"],
        )

        DESIGN_REPAIR_BUFFER_OUTPUT_PORTS: bool = variable(
            True,
            description="Specifies whether or not to insert buffers on output ports.",
            deprecated_names=["PL_RESIZER_BUFFER_OUTPUT_PORTS"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "buffer_ports.tcl")


@Step.factory.register()
class RepairDesignPostGPL(ResizerStep):
    """
    Runs a number of design "repairs" on a global-placed ODB file.

    Port buffering is not one of them: it belongs to
    :class:`AddBuffer`, which runs before global placement.
    """

    id = "OpenROAD.RepairDesignPostGPL"
    name = "Repair Design (Post-Global Placement)"

    class Config(ResizerStep.Config):
        DESIGN_REPAIR_TIE_FANOUT: bool = variable(
            True,
            description="Specifies whether or not to repair tie cells fanout when design repairs are run.",
            deprecated_names=["PL_RESIZER_REPAIR_TIE_FANOUT"],
        )

        DESIGN_REPAIR_TIE_SEPARATION: bool = variable(
            False,
            description="Allows tie separation when performing design repairs.",
            deprecated_names=["PL_RESIZER_TIE_SEPERATION"],
        )

        DESIGN_REPAIR_MAX_WIRE_LENGTH: Decimal = variable(
            0,
            description="Specifies the maximum wire length cap used by resizer to insert buffers during design repair. If set to 0, no buffers will be inserted.",
            units="µm",
            deprecated_names=["PL_RESIZER_MAX_WIRE_LENGTH"],
        )

        DESIGN_REPAIR_MAX_SLEW_PCT: Decimal = variable(
            20,
            description="Specifies a margin for the slews during design repair.",
            units="%",
            deprecated_names=["PL_RESIZER_MAX_SLEW_MARGIN"],
        )

        DESIGN_REPAIR_MAX_CAP_PCT: Decimal = variable(
            20,
            description="Specifies a margin for the capacitances during design repair.",
            units="%",
            deprecated_names=["PL_RESIZER_MAX_CAP_MARGIN"],
        )

        DESIGN_REPAIR_REMOVE_BUFFERS: bool = variable(
            False,
            description="Invokes OpenROAD's remove_buffers command to remove buffers from synthesis, which gives OpenROAD more flexibility when buffering nets.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "openroad", "repair_design.tcl")


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

    class Config(ResizerStep.Config):
        GRT_DESIGN_REPAIR_RUN_GRT: bool = variable(
            True,
            description="Enables running GRT before and after running resizer",
        )

        GRT_DESIGN_REPAIR_MAX_WIRE_LENGTH: Decimal = variable(
            0,
            description="Specifies the maximum wire length cap used by resizer to insert buffers during post-grt design repair. If set to 0, no buffers will be inserted.",
            units="µm",
            deprecated_names=["GLB_RESIZER_MAX_WIRE_LENGTH"],
        )

        GRT_DESIGN_REPAIR_MAX_SLEW_PCT: Decimal = variable(
            10,
            description="Specifies a margin for the slews during post-grt design repair.",
            units="%",
            deprecated_names=["GLB_RESIZER_MAX_SLEW_MARGIN"],
        )

        GRT_DESIGN_REPAIR_MAX_CAP_PCT: Decimal = variable(
            10,
            description="Specifies a margin for the capacitances during design post-grt repair.",
            units="%",
            deprecated_names=["GLB_RESIZER_MAX_CAP_MARGIN"],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath(
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

    class Config(ResizerStep.Config):
        PL_RESIZER_HOLD_SLACK_MARGIN: Decimal = variable(
            0.1,
            description="Specifies a time margin for the slack when fixing hold violations. Normally the resizer will stop when it reaches zero slack. This option allows you to overfix.",
            units="ns",
        )

        PL_RESIZER_SETUP_SLACK_MARGIN: Decimal = variable(
            0.05,
            description="Specifies a time margin for the slack when fixing setup violations.",
            units="ns",
        )

        PL_RESIZER_HOLD_MAX_BUFFER_PCT: Decimal = variable(
            50,
            description="Specifies a max number of buffers to insert to fix hold violations. This number is calculated as a percentage of the number of instances in the design.",
            deprecated_names=["PL_RESIZER_HOLD_MAX_BUFFER_PERCENT"],
        )

        PL_RESIZER_SETUP_MAX_BUFFER_PCT: Decimal = variable(
            50,
            description="Specifies a max number of buffers to insert to fix setup violations. This number is calculated as a percentage of the number of instances in the design.",
            units="%",
            deprecated_names=["PL_RESIZER_SETUP_MAX_BUFFER_PERCENT"],
        )

        PL_RESIZER_ALLOW_SETUP_VIOS: bool = variable(
            False,
            description="Allows the creation of setup violations when fixing hold violations. Setup violations are less dangerous as they simply mean a chip may not run at its rated speed, however, chips with hold violations are essentially dead-on-arrival.",
        )

        PL_RESIZER_SETUP_GATE_CLONING: bool = variable(
            True,
            description="Enables gate cloning when attempting to fix setup violations",
            deprecated_names=["PL_RESIZER_GATE_CLONING"],
        )

        PL_RESIZER_SETUP_BUFFERING: bool = variable(
            True,
            description="Rebuffering and load splitting during setup fixing.",
        )

        PL_RESIZER_SETUP_BUFFER_REMOVAL: bool = variable(
            True,
            description="Buffer removal transform during setup fixing.",
        )

        PL_RESIZER_SETUP_REPAIR_TNS_PCT: Optional[Decimal] = variable(
            None,
            description="Percentage of violating endpoints to repair during setup fixing.",
            units="%",
        )

        PL_RESIZER_SETUP_MAX_UTIL_PCT: Optional[Decimal] = variable(
            None,
            description="Defines the percentage of core area used during setup fixing.",
            units="%",
        )

        PL_RESIZER_HOLD_REPAIR_TNS_PCT: Optional[Decimal] = variable(
            None,
            description="Percentage of violating endpoints to repair during hold fixing.",
            units="%",
        )

        PL_RESIZER_HOLD_MAX_UTIL_PCT: Optional[Decimal] = variable(
            None,
            description="Defines the percentage of core area used during hold fixing.",
            units="%",
        )

        PL_RESIZER_FIX_HOLD_FIRST: bool = variable(
            False,
            description="Experimental: attempt to fix hold violations before setup violations, which may lead to better timing results.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts", "openroad", "rsz_timing_postcts.tcl"
        )


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

    class Config(ResizerStep.Config):
        GRT_RESIZER_HOLD_SLACK_MARGIN: Decimal = variable(
            0.05,
            description="Specifies a time margin for the slack when fixing hold violations. Normally the resizer will stop when it reaches zero slack. This option allows you to overfix.",
            units="ns",
            deprecated_names=["GLB_RESIZER_HOLD_SLACK_MARGIN"],
        )

        GRT_RESIZER_SETUP_SLACK_MARGIN: Decimal = variable(
            0.025,
            description="Specifies a time margin for the slack when fixing setup violations.",
            units="ns",
            deprecated_names=["GLB_RESIZER_SETUP_SLACK_MARGIN"],
        )

        GRT_RESIZER_HOLD_MAX_BUFFER_PCT: Decimal = variable(
            50,
            description="Specifies a max number of buffers to insert to fix hold violations. This number is calculated as a percentage of the number of instances in the design.",
            units="%",
            deprecated_names=["GLB_RESIZER_HOLD_MAX_BUFFER_PERCENT"],
        )

        GRT_RESIZER_SETUP_MAX_BUFFER_PCT: Decimal = variable(
            50,
            description="Specifies a max number of buffers to insert to fix setup violations. This number is calculated as a percentage of the number of instances in the design.",
            units="%",
            deprecated_names=["GLB_RESIZER_SETUP_MAX_BUFFER_PERCENT"],
        )

        GRT_RESIZER_ALLOW_SETUP_VIOS: bool = variable(
            False,
            description="Allows setup violations when fixing hold.",
            deprecated_names=["GLB_RESIZER_ALLOW_SETUP_VIOS"],
        )

        GRT_RESIZER_SETUP_GATE_CLONING: bool = variable(
            True,
            description="Enables gate cloning when attempting to fix setup violations",
            deprecated_names=["GRT_RESIZER_GATE_CLONING"],
        )

        GRT_RESIZER_RUN_GRT: bool = variable(
            True,
            description="Gates running global routing after resizer steps. May be useful to disable for designs where global routing takes non-trivial time.",
        )

        GRT_RESIZER_SETUP_BUFFERING: bool = variable(
            True,
            description="Rebuffering and load splitting during setup fixing.",
        )

        GRT_RESIZER_SETUP_BUFFER_REMOVAL: bool = variable(
            True,
            description="Buffer removal transform during setup fixing.",
        )

        GRT_RESIZER_SETUP_REPAIR_TNS_PCT: Optional[Decimal] = variable(
            None,
            description="Percentage of violating endpoints to repair during setup fixing.",
            units="%",
        )

        GRT_RESIZER_SETUP_MAX_UTIL_PCT: Optional[Decimal] = variable(
            None,
            description="Defines the percentage of core area used during setup fixing.",
            units="%",
        )

        GRT_RESIZER_HOLD_REPAIR_TNS_PCT: Optional[Decimal] = variable(
            None,
            description="Percentage of violating endpoints to repair during hold fixing.",
            units="%",
        )

        GRT_RESIZER_HOLD_MAX_UTIL_PCT: Optional[Decimal] = variable(
            None,
            description="Defines the percentage of core area used during hold fixing.",
            units="%",
        )

        GRT_RESIZER_FIX_HOLD_FIRST: bool = variable(
            False,
            description="Experimental: attempt to fix hold violations before setup violations, which may lead to better timing results.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts", "openroad", "rsz_timing_postgrt.tcl"
        )
