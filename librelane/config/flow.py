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
import pathlib
from importlib.resources import files

from decimal import Decimal
from typing import Literal, Optional, Union
from collections.abc import Sequence

from librelane.config.legacy import Macro
from librelane.config.model import BaseConfigModel, model_to_variables, variable
from librelane.common import Path


def _prefix_to_wildcard(prefixes_raw: str | Sequence[str]):
    prefixes = prefixes_raw
    if isinstance(prefixes, str):
        prefixes = prefixes.split()
    return [f"{prefix}*" for prefix in prefixes]


class PdkConfig(BaseConfigModel):
    STD_CELL_LIBRARY: str = variable(
        description="Specifies the default standard cell library to be used under the specified PDK. Must be a valid C identifier, i.e., matches the regular expression `[_a-zA-Z][_a-zA-Z0-9]+`.",
        pdk=True,
    )

    VDD_PIN: str = variable(
        description="The power pin for the cells.",
        pdk=True,
    )

    GND_PIN: str = variable(
        description="The ground pin for the cells.",
        pdk=True,
    )

    TECH_LEFS: dict[str, Path] = variable(
        description="Map of corner patterns to technology LEF files. A corner not matched here will not be supported by OpenRCX in the default flow.",
        pdk=True,
    )

    PRIMARY_GDSII_STREAMOUT_TOOL: str = variable(
        description="Specify the primary GDSII streamout tool for this PDK. For most open-source PDKs, that would be 'magic'.",
        pdk=True,
        deprecated_names=["PRIMARY_SIGNOFF_TOOL"],
    )

    DEFAULT_MAX_TRAN: Optional[Decimal] = variable(
        None,
        description="Defines the default maximum transition value used in Synthesis and CTS.\nA minimum of 0.1 * CLOCK_PERIOD and this variable, if defined, is used.",
        units="ns",
        pdk=True,
    )

    DEFAULT_CORNER: str = variable(
        description="The interconnect/process/voltage/temperature corner (IPVT) to use the characterized lib files compatible with by default.",
        pdk=True,
    )

    STA_CORNERS: list[str] = variable(
        description="A list of fully qualified IPVT (Interconnect, transistor Process, Voltage, and Temperature) timing corners on which to conduct multi-corner static timing analysis.",
        pdk=True,
    )

    RT_MIN_LAYER: str = variable(
        description="The lowest metal layer to route on.",
        pdk=True,
    )

    RT_MAX_LAYER: str = variable(
        description="The highest metal layer to route on.",
        pdk=True,
    )

    ISOSUB_LAYER: Optional[tuple[int, int]] = variable(
        None,
        description="The GDSII layer and datatype pair for the isolated substrate (subcut) layer, if the PDK has one.",
        pdk=True,
    )


pdk_variables = model_to_variables(PdkConfig)


class SclConfig(BaseConfigModel):
    SCL_GROUND_PINS: list[str] = variable(
        description="SCL-specific ground pins",
        deprecated_names=["STD_CELL_GROUND_PINS"],
        pdk=True,
    )

    SCL_POWER_PINS: list[str] = variable(
        description="SCL-specific power pins",
        deprecated_names=["STD_CELL_POWER_PINS"],
        pdk=True,
    )

    TRISTATE_CELLS: Optional[list[str]] = variable(
        None,
        description="A list of cell names or wildcards of tri-state buffers.",
        deprecated_names=[("TRISTATE_CELL_PREFIX", _prefix_to_wildcard)],
        pdk=True,
    )

    FILL_CELLS: list[str] = variable(
        description="A list of cell names or wildcards of fill cells to be used in fill insertion.",
        pdk=True,
        deprecated_names=["FILL_CELL"],
    )

    DECAP_CELLS: list[str] = variable(
        description="A list of cell names or wildcards of decap cells to be used in fill insertion.",
        pdk=True,
        deprecated_names=["DECAP_CELL"],
    )

    LIB: dict[str, list[Path]] = variable(
        description="A map from corner patterns to a list of associated liberty files. Exactly one entry must match the `DEFAULT_CORNER`.",
        pdk=True,
    )

    CELL_LEFS: list[Path] = variable(
        description="Path(s) to the cells' LEF file(s).",
        deprecated_names=["CELLS_LEF"],
        pdk=True,
    )

    CELL_GDS: list[Path] = variable(
        description="Path(s) to the cells' GDSII file(s).",
        deprecated_names=["GDS_FILES", "CELLS_GDS"],
        pdk=True,
    )

    CELL_VERILOG_MODELS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to cells' Verilog model(s)",
        pdk=True,
    )

    CELL_BB_VERILOG_MODELS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to cells' black-box Verilog model(s)",
        pdk=True,
    )

    CELL_SPICE_MODELS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to cells' SPICE model(s)",
        pdk=True,
    )

    CELL_CDLS: Optional[list[Path]] = variable(
        None,
        description="A circuit-design language view of the standard cell library.",
        pdk=True,
        deprecated_names=["STD_CELL_LIBRARY_CDL"],
    )

    SYNTH_EXCLUDED_CELL_FILE: Path = variable(
        description="Path to a text file containing a list of (wildcards matching) cells to be excluded from the lib file in synthesis alone.",
        deprecated_names=["NO_SYNTH_CELL_LIST", "SYNTH_EXCLUSION_CELL_LIST"],
        pdk=True,
    )

    PNR_EXCLUDED_CELL_FILE: Path = variable(
        description="Path to a text file containing a list of undesirable or bad (DRC-failed or complex pinout) cells or wildcards matching cells to be excluded from synthesis AND PnR.",
        deprecated_names=["DRC_EXCLUDE_CELL_LIST", "PNR_EXCLUSION_CELL_LIST"],
        pdk=True,
    )

    OUTPUT_CAP_LOAD: Decimal = variable(
        description="Defines the capacitive load on the output ports.",
        units="fF",
        deprecated_names=["SYNTH_CAP_LOAD"],
        pdk=True,
    )

    MAX_FANOUT_CONSTRAINT: Optional[int] = variable(
        None,
        description="The max load that the output ports can drive to be used as a constraint on Synthesis and CTS. If not provided, the constraint is not set in the SDC file, which will fall back to the value set by the liberty file.",
        units="cells",
        deprecated_names=["SYNTH_MAX_FANOUT"],
        pdk=True,
    )

    MAX_TRANSITION_CONSTRAINT: Optional[Decimal] = variable(
        None,
        description="The max transition time (slew) from high to low or low to high on cell inputs in ns to be used as a constraint on Synthesis and CTS. If not provided, it is calculated at runtime as `10%` of the provided clock period, unless that exceeds the PDK's `DEFAULT_MAX_TRAN` value.",
        units="ns",
        deprecated_names=["SYNTH_MAX_TRAN"],
        pdk=True,
    )

    MAX_CAPACITANCE_CONSTRAINT: Optional[Decimal] = variable(
        None,
        description="The maximum capacitance constraint. If not provided, the constraint is not set in the SDC file which will fall back to the value set by the liberty file",
        units="pF",
        pdk=True,
    )

    CLOCK_UNCERTAINTY_CONSTRAINT: Decimal = variable(
        description="Specifies a value for the clock uncertainty/jitter for timing analysis.",
        units="ns",
        deprecated_names=["SYNTH_CLOCK_UNCERTAINTY"],
        pdk=True,
    )

    CLOCK_TRANSITION_CONSTRAINT: Decimal = variable(
        description="Specifies a value for the clock transition/slew for timing analysis.",
        units="ns",
        deprecated_names=["SYNTH_CLOCK_TRANSITION"],
        pdk=True,
    )

    TIME_DERATING_CONSTRAINT: Decimal = variable(
        description="Specifies a derating factor to multiply the path delays with. It specifies the upper and lower ranges of timing.",
        units="%",
        deprecated_names=["SYNTH_TIMING_DERATE"],
        pdk=True,
    )

    IO_DELAY_CONSTRAINT: Decimal = variable(
        description="Specifies the percentage of the clock period used in the input/output delays.",
        units="%",
        deprecated_names=["IO_PCT"],
        pdk=True,
    )

    SYNTH_DRIVING_CELL: str = variable(
        description="The cell to drive the input ports, used in synthesis and static timing analysis, in the format `{cell}/{port}`.",
        pdk=True,
    )

    SYNTH_CLK_DRIVING_CELL: Optional[str] = variable(
        None,
        description="The cell to drive the clock input ports, used in synthesis and static timing analysis, in the format `{cell}/{port}`. If not specified, `SYNTH_DRIVING_CELL` will be used.",
        pdk=True,
    )

    SYNTH_TIEHI_CELL: str = variable(
        description="Defines the tie high cell followed by the port that implements the tie high functionality, in the format `{cell}/{port}`.",
        pdk=True,
    )

    SYNTH_TIELO_CELL: str = variable(
        description="Defines the tie high cell followed by the port that implements the tie low functionality, in the format `{cell}/{port}`.",
        pdk=True,
    )

    SYNTH_BUFFER_CELL: str = variable(
        description="Defines a buffer port to be used by yosys during synthesis: in the format `{cell}/{input_port}/{output_port}`",
        pdk=True,
    )

    PLACE_SITE: str = variable(
        description="Defines the primary placement site in placement as specified in the technology LEF files, to generate the placement grid.",
        pdk=True,
    )

    CELL_PAD_EXCLUDE: list[str] = variable(
        description="Defines a list of cells to be excluded from cell padding.",
        pdk=True,
    )

    DIODE_CELL: Optional[str] = variable(
        None,
        description="Defines a diode cell used to fix antenna violations, in the format `{cell}/{port}`. If not defined, steps should not attempt to repair the antenna effect by inserting diode cells.",
        pdk=True,
    )

    WELLTAP_CELL: Optional[str] = variable(
        None,
        description="Defines the cell used for tap insertion. If not defined, steps should not attempt to insert welltap cells.",
        pdk=True,
        deprecated_names=["FP_WELLTAP_CELL"],
    )

    ENDCAP_CELL: Optional[str] = variable(
        None,
        description="Defines the so-called 'end-cap' cell- class of decap cells placed at either sides of a design, if available.",
        pdk=True,
        deprecated_names=["FP_ENDCAP_CELL"],
    )


scl_variables = model_to_variables(SclConfig)


class OptionConfig(BaseConfigModel):
    DESIGN_DIR: Path = variable(
        description="The directory of the design. Should be set via command-line arguments or :meth:`Config.load` flags and not actual configuration files. If using a configuration file, ``DESIGN_DIR`` will be the directory where that file exists.",
    )

    PDK_ROOT: Path = variable(
        description="The home path of all PDKs. Should be set via command-line arguments or :meth:`Config.load` flags and not actual configuration files.",
    )

    DESIGN_NAME: str = variable(
        description="The name of the top level module of the design. Must be a valid C identifier, i.e., matches the regular expression `[_a-zA-Z][_a-zA-Z0-9]+`.",
    )

    PDK: str = variable(
        "sky130A",
        description="Specifies the process design kit (PDK). Must be a valid C identifier, i.e., matches the regular expression `[_a-zA-Z][_a-zA-Z0-9]+`.",
    )

    CLOCK_PERIOD: Decimal = variable(
        10.0,
        description="The clock period for the design.",
        units="ns",
    )

    CLOCK_PORT: Union[None, str, list[str]] = variable(
        description="The name(s) of the design's clock port(s).",
    )

    CLOCK_NET: Union[None, str, list[str]] = variable(
        description="The name of the net input to root clock buffer. If unset, it is presumed to be equal to CLOCK_PORT.",
    )

    VDD_NETS: Optional[list[str]] = variable(
        None,
        description="Specifies the power nets/pins to be used when creating the power grid for the design.",
    )

    GND_NETS: Optional[list[str]] = variable(
        None,
        description="Specifies the ground nets/pins to be used when creating the power grid for the design.",
    )

    DIE_AREA: Optional[tuple[Decimal, Decimal, Decimal, Decimal]] = variable(
        None,
        description='Specific die area to be used in floorplanning. Specified as a 4-corner rectangle "x0 y0 x1 y1".',
        units="µm",
    )

    EXTRA_EXCLUDED_CELLS: Optional[list[str]] = variable(
        None,
        description="Wildcards matching additional cells to exclude from both synthesis and PnR.",
        deprecated_names=["RSZ_DONT_USE_CELLS", "DONT_USE_CELLS"],
    )

    MACROS: Optional[dict[str, Macro]] = variable(
        None,
        description="A dictionary of Macro definition objects. See {py:class}`librelane.config.Macro` for more info.",
    )

    EXTRA_LEFS: Optional[list[Path]] = variable(
        None,
        description="Specifies miscellaneous LEF files to be loaded indiscriminately whenever LEFs are loaded.",
    )

    EXTRA_VERILOG_MODELS: Optional[list[Path]] = variable(
        None,
        description="Specifies miscellaneous Verilog models to be loaded indiscriminately during synthesis.",
        deprecated_names=["VERILOG_FILES_BLACKBOX"],
    )

    EXTRA_SPICE_MODELS: Optional[list[Path]] = variable(
        None,
        description="Specifies miscellaneous SPICE models to be loaded indiscriminately whenever SPICE models are loaded.",
    )

    EXTRA_CDLS: Optional[list[Path]] = variable(
        None,
        description="Specifies miscellaneous CDL netlists to be loaded indiscriminately whenever CDL netlists are loaded.",
    )

    EXTRA_LIBS: Optional[list[Path]] = variable(
        None,
        description="Specifies LIB files of pre-hardened macros used in the current design, used during timing analyses (and during parasitics-based STA as a fallback). These are loaded indiscriminately for all timing corners.",
    )

    EXTRA_GDS: Optional[list[Path]] = variable(
        None,
        description="Specifies GDS files of pre-hardened macros used in the current design, used during tape-out.",
        deprecated_names=["EXTRA_GDS_FILES"],
    )

    FALLBACK_SDC: Path = variable(
        pathlib.Path(str(files("librelane").joinpath("scripts", "base.sdc"))),
        description="A fallback SDC file for when a step-specific SDC file is not defined.",
        deprecated_names=["FALLBACK_SDC_FILE", "BASE_SDC_FILE", "SDC_FILE"],
    )


option_variables = model_to_variables(OptionConfig)


#: The eight LEF orientations, as OpenROAD's ``make_io_sites`` names them.
PadRotation = Literal["R0", "MY", "R90", "MXR90", "R180", "MX", "R270", "MYR90"]


class PadConfig(BaseConfigModel):
    PAD_GDS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to IO pad GDS file(s).",
        pdk=True,
    )

    PAD_LEFS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to IO pad LEF file(s).",
        pdk=True,
    )

    PAD_VERILOG_MODELS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to IO pads' Verilog model(s)",
        pdk=True,
    )

    PAD_SPICE_MODELS: Optional[list[Path]] = variable(
        None,
        description="Path(s) to IO pads' SPICE model(s)",
        pdk=True,
    )

    PAD_CDLS: Optional[list[Path]] = variable(
        None,
        description="A circuit-design language view of the io pad library.",
        pdk=True,
    )

    PAD_LIBS: Optional[dict[str, list[Path]]] = variable(
        None,
        description="A map from corner patterns to a list of associated liberty files. Exactly one entry must match the `DEFAULT_CORNER`.",
        pdk=True,
    )

    PAD_CORNER: Optional[list[str]] = variable(
        None,
        description="The pad corner cell.",
        pdk=True,
    )

    PAD_FILLERS: Optional[list[str]] = variable(
        None,
        description="A list of pad filler cells.",
        pdk=True,
    )

    PAD_SITE_NAME: Optional[str] = variable(
        None,
        description="Name of the pad site.",
        units="µm",
        pdk=True,
    )

    PAD_CORNER_SITE_NAME: Optional[str] = variable(
        None,
        description="Name of the corner site.",
        units="µm",
        pdk=True,
    )

    PAD_FAKE_SITES: Optional[dict[str, tuple[Decimal, Decimal]]] = variable(
        None,
        description="A dict of fake pad sites and their width and height tuple. Use this if the LEF does not include the site definitions for the IO pads.",
        units="µm",
        pdk=True,
    )

    PAD_BONDPAD_NAME: Optional[str] = variable(
        None,
        description="Name of the bondpad cell, if empty, bondpads won't be placed.",
        pdk=True,
    )

    PAD_BONDPAD_WIDTH: Optional[Decimal] = variable(
        None,
        description="Width of the bondpad.",
        units="µm",
        pdk=True,
    )

    PAD_BONDPAD_HEIGHT: Optional[Decimal] = variable(
        None,
        description="Height of the bondpad.",
        units="µm",
        pdk=True,
    )

    PAD_BONDPAD_OFFSETS: Optional[dict[str, tuple[Decimal, Decimal]]] = variable(
        None,
        description="A dict of pad master names or regular expressions to their bondpad (offset_x, offset_y) tuple.",
        pdk=True,
    )

    PAD_PLACE_IO_TERMINALS: Optional[list[str]] = variable(
        None,
        description="Place I/O terminals for these master/pin combinations.",
        pdk=True,
    )

    PAD_EDGE_SPACING: Optional[Decimal] = variable(
        0,
        description="Distance from the padring to the die boundary. Used to account for the sealring when placing the pads.",
        units="µm",
        pdk=True,
    )

    PAD_ROTATION_HORIZONTAL: PadRotation = variable(
        "R0",
        description="Rotation to apply to the horizontal pad sites so the pad cells are placed the right way up.",
        pdk=True,
    )

    PAD_ROTATION_VERTICAL: PadRotation = variable(
        "R0",
        description="Rotation to apply to the vertical pad sites so the pad cells are placed the right way up.",
        pdk=True,
    )

    PAD_ROTATION_CORNER: PadRotation = variable(
        "R0",
        description="Rotation to apply to the corner pad sites so the corner cells are placed the right way up.",
        pdk=True,
    )


pad_variables = model_to_variables(PadConfig)

flow_common_variables = pdk_variables + scl_variables + option_variables + pad_variables
