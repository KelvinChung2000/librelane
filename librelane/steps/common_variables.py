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
from decimal import Decimal
from typing import Literal

from librelane.config import BaseConfigModel, model_to_variables, variable


class IoLayerConfig(BaseConfigModel):
    IO_PIN_H_LAYER: str = variable(
        description="The metal layer on which to place horizontally-aligned (long side parallel with the horizon) pins alongside the east and west edges of the die.",
        pdk=True,
        deprecated_names=["FP_IO_HLAYER"],
    )

    IO_PIN_V_LAYER: str = variable(
        description="The metal layer on which to place vertically-aligned (long side perpendicular to the horizon) pins alongside the north and south edges of the die.",
        pdk=True,
        deprecated_names=["FP_IO_VLAYER"],
    )

    IO_PIN_V_EXTENSION: Decimal = variable(
        0,
        description="Extends the vertical io pins outside of the die by the specified units.",
        units="µm",
    )

    IO_PIN_H_EXTENSION: Decimal = variable(
        0,
        description="Extends the horizontal io pins outside of the die by the specified units.",
        units="µm",
    )

    IO_PIN_V_THICKNESS_MULT: Decimal = variable(
        2,
        description="A multiplier for vertical pin thickness. Base thickness is the pins layer min width. PDK-overridable because it can be a process constraint, not a preference: a PDK whose routing layers are rectangle-only (LEF58_RECTONLY) cannot legalize a pin drawn wider than the wire that meets it, and must say 1.",
        pdk=True,
    )

    IO_PIN_H_THICKNESS_MULT: Decimal = variable(
        2,
        description="A multiplier for horizontal pin thickness. Base thickness is the pins layer min width. PDK-overridable because it can be a process constraint, not a preference: a PDK whose routing layers are rectangle-only (LEF58_RECTONLY) cannot legalize a pin drawn wider than the wire that meets it, and must say 1.",
        pdk=True,
    )

    IO_PIN_V_LENGTH: Decimal | None = variable(
        None,
        description="\n        The length of the pins with a north or south orientation. If unspecified by a PDK, OpenROAD will use whichever is higher of the following two values:\n            * The pin width\n            * The minimum value satisfying the minimum area constraint given the pin width\n        ",
        units="µm",
        pdk=True,
        deprecated_names=["FP_IO_VLENGTH"],
    )

    IO_PIN_H_LENGTH: Decimal | None = variable(
        None,
        description="\n        The length of the pins with an east or west orientation. If unspecified by a PDK, OpenROAD will use whichever is higher of the following two values:\n            * The pin width\n            * The minimum value satisfying the minimum area constraint given the pin width\n        ",
        units="µm",
        pdk=True,
        deprecated_names=["FP_IO_HLENGTH"],
    )


io_layer_variables = model_to_variables(IoLayerConfig)


class PdnConfig(BaseConfigModel):
    PDN_SKIPTRIM: bool = variable(
        False,
        description="Enables `-skip_trim` option during pdngen which skips the metal trim step, which attempts to remove metal stubs.",
    )

    PDN_CORE_RING: bool = variable(
        False,
        description="Enables adding a core ring around the design. More details on the control variables in the PDK config documentation.",
    )

    PDN_ENABLE_RAILS: bool = variable(
        True,
        description="Enables the creation of rails in the power grid.",
    )

    PDN_HORIZONTAL_HALO: Decimal = variable(
        10,
        description="Sets the horizontal halo around the macros during power grid insertion. Should not exceed `FP_MACRO_HORIZONTAL_HALO`, otherwise cells may be placed in the band between the two where the macro power grid is suppressed.",
        units="µm",
    )

    PDN_VERTICAL_HALO: Decimal = variable(
        10,
        description="Sets the vertical halo around the macros during power grid insertion. Should not exceed `FP_MACRO_VERTICAL_HALO`, otherwise cells may be placed in the band between the two where the macro power grid is suppressed.",
        units="µm",
    )

    PDN_MULTILAYER: bool = variable(
        True,
        description="Controls the layers used in the power grid. If set to false, only the lower layer will be used, which is useful when hardening a macro for integrating into a larger top-level design.",
    )

    PDN_RAIL_OFFSET: Decimal = variable(
        description="The offset for the power distribution network rails for first metal layer.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_RAIL_OFFSET"],
    )

    PDN_VWIDTH: Decimal = variable(
        description="The strap width for the vertical layer in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_VWIDTH"],
    )

    PDN_HWIDTH: Decimal = variable(
        description="The strap width for the horizontal layer in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_HWIDTH"],
    )

    PDN_VSPACING: Decimal = variable(
        description="Intra-spacing (within a set) of vertical straps in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_VSPACING"],
    )

    PDN_HSPACING: Decimal = variable(
        description="Intra-spacing (within a set) of horizontal straps in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_HSPACING"],
    )

    PDN_VPITCH: Decimal = variable(
        description="Inter-distance (between sets) of vertical power straps in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_VPITCH"],
    )

    PDN_HPITCH: Decimal = variable(
        description="Inter-distance (between sets) of horizontal power straps in generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_HPITCH"],
    )

    PDN_VOFFSET: Decimal = variable(
        description="Initial offset for sets of vertical power straps.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_VOFFSET"],
    )

    PDN_HOFFSET: Decimal = variable(
        description="Initial offset for sets of horizontal power straps.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_HOFFSET"],
    )

    PDN_CORE_RING_VWIDTH: Decimal = variable(
        description="The width for the vertical layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_VWIDTH"],
    )

    PDN_CORE_RING_HWIDTH: Decimal = variable(
        description="The width for the horizontal layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_HWIDTH"],
    )

    PDN_CORE_RING_VSPACING: Decimal = variable(
        description="The spacing for the vertical layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_VSPACING"],
    )

    PDN_CORE_RING_HSPACING: Decimal = variable(
        description="The spacing for the horizontal layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_HSPACING"],
    )

    PDN_CORE_RING_VOFFSET: Decimal = variable(
        description="The offset for the vertical layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_VOFFSET"],
    )

    PDN_CORE_RING_HOFFSET: Decimal = variable(
        description="The offset for the horizontal layer in the core ring of generated power distribution networks.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_CORE_RING_HOFFSET"],
    )

    PDN_CORE_RING_CONNECT_TO_PADS: bool = variable(
        False,
        description="If specified, the core side of the pad pins will be connected to the ring.",
        pdk=True,
    )

    PDN_CORE_RING_CONNECT_TO_PAD_LAYERS: list[str] | None = variable(
        None,
        description="Restricts the connection between the core ring and the pad pins to these layers. Only applicable when `PDN_CORE_RING_CONNECT_TO_PADS` is enabled. If unset, every layer a pad pin appears on is eligible.",
        pdk=True,
    )

    PDN_CORE_RING_ALLOW_OUT_OF_DIE: bool = variable(
        True,
        description="If specified, the ring shapes are allowed to be outside the die boundary.",
        pdk=True,
    )

    PDN_RAIL_LAYER: str = variable(
        description="Defines the metal layer used for PDN rails.",
        deprecated_names=["FP_PDN_RAIL_LAYER", "FP_PDN_RAILS_LAYER"],
        pdk=True,
    )

    PDN_RAIL_WIDTH: Decimal = variable(
        description="Defines the width of PDN rails on the `PDN_RAIL_LAYER` layer.",
        units="µm",
        pdk=True,
        deprecated_names=["FP_PDN_RAIL_WIDTH"],
    )

    PDN_HORIZONTAL_LAYER: str = variable(
        description="Defines the horizontal PDN layer.",
        deprecated_names=["FP_PDN_HORIZONTAL_LAYER", "FP_PDN_UPPER_LAYER"],
        pdk=True,
    )

    PDN_VERTICAL_LAYER: str = variable(
        description="Defines the vertical PDN layer.",
        deprecated_names=["FP_PDN_VERTICAL_LAYER", "FP_PDN_LOWER_LAYER"],
        pdk=True,
    )

    PDN_CORE_HORIZONTAL_LAYER: str | None = variable(
        None,
        description="Defines the horizontal PDN layer for the core ring. Falls back to `PDN_HORIZONTAL_LAYER` if undefined.",
        pdk=True,
    )

    PDN_CORE_VERTICAL_LAYER: str | None = variable(
        None,
        description="Defines the vertical PDN layer for the core ring. Falls back to `PDN_VERTICAL_LAYER` if undefined.",
        pdk=True,
    )

    PDN_EXTEND_TO: Literal["core_ring", "boundary"] = variable(
        "core_ring",
        description="Defines how far the stripes and rings extend.",
        pdk=True,
    )

    PDN_ENABLE_PINS: bool = variable(
        True,
        description="If specified, the power straps will be promoted to block pins.",
        pdk=True,
    )


pdn_variables = model_to_variables(PdnConfig)


class RoutingLayerConfig(BaseConfigModel):
    RT_CLOCK_MIN_LAYER: str | None = variable(
        None,
        description="The name of lowest layer to be used in routing the clock net.",
    )

    RT_CLOCK_MAX_LAYER: str | None = variable(
        None,
        description="The name of highest layer to be used in routing the clock net.",
    )

    GRT_ADJUSTMENT: Decimal = variable(
        0.3,
        description="Reduction in the routing capacity of the edges between the cells in the global routing graph for all layers. Values range from 0 to 1.  1 = most reduction, 0 = least reduction.",
    )

    GRT_MACRO_EXTENSION: int = variable(
        0,
        description="Sets the number of GCells added to the blockages boundaries from macros. A GCell is typically defined in terms of Mx routing tracks. The default GCell size is 15 M3 pitches.",
    )

    GRT_LAYER_ADJUSTMENTS: list[Decimal] = variable(
        description="Layer-specific reductions in the routing capacity of the edges between the cells in the global routing graph, delimited by commas. Values range from 0 through 1.",
        pdk=True,
    )


routing_layer_variables = model_to_variables(RoutingLayerConfig)


class DplConfig(BaseConfigModel):
    PL_OPTIMIZE_MIRRORING: bool = variable(
        True,
        description="Specifies whether or not to run an optimize_mirroring pass whenever detailed placement happens. This pass will mirror the cells whenever possible to optimize the design.",
    )

    PL_MAX_DISPLACEMENT_X: int = variable(
        500,
        description="Specifies how far an instance can be moved along the X-axis when finding a site where it can be placed during detailed placement.",
        units="µm",
    )

    PL_MAX_DISPLACEMENT_Y: int = variable(
        100,
        description="Specifies how far an instance can be moved along the Y-axis when finding a site where it can be placed during detailed placement.",
        units="µm",
    )

    DPL_CELL_PADDING: int = variable(
        description="Cell padding value (in sites) for detailed placement. The number will be integer divided by 2 and placed on both sides. Should be <= global placement.",
        units="sites",
        pdk=True,
    )


dpl_variables = model_to_variables(DplConfig)


class GrtConfig(RoutingLayerConfig):
    DIODE_PADDING: int | None = variable(
        None,
        description="Diode cell padding; increases the width of diode cells during placement checks..",
        units="sites",
    )

    GRT_ALLOW_CONGESTION: bool = variable(
        False,
        description="Allow congestion during global routing",
    )

    GRT_ANTENNA_REPAIR_ITERS: int = variable(
        3,
        description="The maximum number of iterations for global antenna repairs.",
    )

    GRT_OVERFLOW_ITERS: int = variable(
        50,
        description="The maximum number of iterations waiting for the overflow to reach the desired value.",
    )

    GRT_ANTENNA_REPAIR_MARGIN: int = variable(
        10,
        description="The margin to over fix antenna violations.",
        units="%",
    )

    GRT_ANTENNA_REPAIR_JUMPER_ONLY: bool = variable(
        False,
        description="Only use jumpers to fix antenna violations. Cannot be used in conjunction with GRT_ANTENNA_REPAIR_DIODE_ONLY.",
    )

    GRT_ANTENNA_REPAIR_DIODE_ONLY: bool = variable(
        False,
        description="Only use antenna diodes to fix antenna violations. Cannot be used in conjunction with GRT_ANTENNA_REPAIR_JUMPER_ONLY.",
    )


grt_variables = routing_layer_variables + model_to_variables(
    GrtConfig,
    include_inherited=False,
)


class RszConfig(DplConfig):
    RSZ_DONT_TOUCH_RX: str = variable(
        "$^",
        description='A single regular expression designating nets or instances as "don\'t touch" by design repairs or resizer optimizations.',
    )

    RSZ_DONT_TOUCH_LIST: list[str] | None = variable(
        None,
        description='A list of nets and instances as "don\'t touch" by design repairs or resizer optimizations.',
    )

    RSZ_CORNERS: list[str] | None = variable(
        None,
        description="Resizer step-specific override for PNR_CORNERS.",
    )


rsz_variables = dpl_variables + model_to_variables(
    RszConfig,
    include_inherited=False,
)
