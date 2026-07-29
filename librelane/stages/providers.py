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
"""
Provider registrations for the open-source toolchain.

Every sequence here is a partition of today's ``Classic.Steps``. The golden
equivalence test in ``test/flows/test_staged_equivalence.py`` is what pins
them down; if a sequence is wrong, that test fails.

The registrations are declared as data and applied in a loop at the bottom of
the module. Keeping them as data is what let the ``namespaces`` and
``native_views`` values be derived mechanically from each sequence's actual
declarations rather than guessed.
"""

from ..state import DesignFormat
from ..steps import (
    Checker,
    KLayout,
    Magic,
    Netgen,
    Odb,
    OpenROAD,
    Verilator,
    Yosys,
)

from .registry import StageRegistry

#: Accepted configuration variable prefixes and names for the OpenROAD step
#: family. The prefixes predate this design and are not renamed by it; the bare
#: names are variables that never acquired a prefix. Declared once for the whole
#: family rather than per stage, because these steps share a base config model.
#:
#: Every entry was produced by enumerating what the sequences actually declare,
#: not by guessing. A variable that is neither canonical for its stage nor a
#: common flow variable nor matched here is rejected at registration.
_OPENROAD_NAMESPACES = (
    # Legacy per-phase prefixes.
    "FP_",
    "PL_",
    "GPL_",
    "DPL_",
    "CTS_",
    "GRT_",
    "DRT_",
    "RSZ_",
    "RT_",
    "PDN_",
    "RCX_",
    "STA_",
    "IR_",
    "IO_",
    "DIODE_",
    "DESIGN_REPAIR_",
    # Corner and parasitic setup shared by every OpenROAD step.
    "CLOCK_WIRE_RC_LAYERS",
    "DEDUPLICATE_CORNERS",
    "LAYERS_RC",
    "OPENROAD_THREADS",
    "PNR_CORNERS",
    "PNR_SDC_FILE",
    "SET_RC_VERBOSE",
    "SIGNAL_WIRE_RC_LAYERS",
    "VIAS_R",
    # Unprefixed variables belonging to individual OpenROAD phases.
    "EXTRA_SPEFS",
    "SIGNOFF_SDC_FILE",
    "BOTTOM_MARGIN_MULT",
    "TOP_MARGIN_MULT",
    "LEFT_MARGIN_MULT",
    "RIGHT_MARGIN_MULT",
    "CORE_AREA",
    "EXTRA_SITES",
    "MACRO_PLACEMENT_CFG",
    "ERRORS_ON_UNMATCHED_IO",
    "HEURISTIC_ANTENNA_THRESHOLD",
    "ERROR_ON_TR_DRC",
    "NON_DEFAULT_RULES",
    "ROUTING_OBSTRUCTIONS",
    "VSRC_LOC_FILES",
)

#: Magic reads the same technology and cell-view variables in every step that
#: uses it, including the Magic-based extraction inside the ``lvs`` sequence.
_MAGIC_NAMESPACES = ("MAGIC", "CELL_MAG")

#: The Yosys synthesis variables shared by the Verilog and VHDL frontends.
_YOSYS_NAMESPACES = (
    "SYNTH_",
    "YOSYS_",
    "ERROR_ON_NL_ASSIGN_STATEMENTS",
    "ERROR_ON_SYNTH_CHECKS",
    "ERROR_ON_UNMAPPED_CELLS",
)

#: OpenROAD's ``odb`` is a tool-native database handed from one OpenROAD step to
#: the next. It is not a neutral view, so it is declared rather than promoted
#: into any stage's ``requires``; the static view availability preflight is what
#: verifies an OpenROAD stage is actually preceded by one that produces it.
_ODB = (DesignFormat.odb,)

_REGISTRATIONS: list[dict] = [
    {
        "stages": ["lint"],
        "provider": "verilator",
        "steps": [
            Verilator.Lint,
            Checker.LintTimingConstructs,
            Checker.LintErrors,
            Checker.LintWarnings,
        ],
        "namespaces": ("LINTER_", "ERROR_ON_LINTER_", "VERILOG_"),
    },
    {
        "stages": ["synthesis"],
        "provider": "yosys",
        "steps": [
            Yosys.JsonHeader,
            Yosys.Synthesis,
            Checker.YosysUnmappedCells,
            Checker.YosysSynthChecks,
            Checker.NetlistAssignStatements,
        ],
        "namespaces": _YOSYS_NAMESPACES + ("VERILOG_", "SLANG_", "USE_SLANG"),
        "provides": [DesignFormat.json_h],
    },
    {
        "stages": ["synthesis"],
        "provider": "yosys_vhdl",
        "steps": [
            Yosys.VHDLSynthesis,
            Checker.YosysUnmappedCells,
            Checker.YosysSynthChecks,
            Checker.NetlistAssignStatements,
        ],
        "namespaces": _YOSYS_NAMESPACES + ("GHDL_", "VHDL_"),
    },
    {
        "stages": ["pre_pnr_sta"],
        "provider": "openroad",
        "steps": [
            OpenROAD.CheckSDCFiles,
            OpenROAD.CheckMacroInstances,
            OpenROAD.STAPrePNR,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "stages": ["floorplan"],
        "provider": "openroad",
        # Odb.SetPowerConnections used to be the last step here, which forced
        # this registration to declare json_h as a native view. That made a
        # Verilog-only step a mandatory member of a tool-neutral stage: a VHDL
        # flow needs floorplanning but has no Verilog header, and had no way to
        # say "floorplan, but not that step". It is a plain step in Classic's
        # Stages list now, so a flow that cannot run it simply omits it.
        "steps": [
            OpenROAD.Floorplan,
            OpenROAD.DumpRCValues,
            Odb.CheckMacroAntennaProperties,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "stages": ["macro_placement"],
        "provider": "openroad",
        "steps": [Odb.ManualMacroPlacement],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["tapcell_insertion"],
        "provider": "openroad",
        "steps": [OpenROAD.TapEndcapInsertion],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["power_grid"],
        "provider": "openroad",
        "steps": [
            Odb.AddPDNObstructions,
            OpenROAD.GeneratePDN,
            Odb.RemovePDNObstructions,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["io_placement"],
        "provider": "openroad",
        "steps": [
            OpenROAD.GlobalPlacementSkipIO,
            OpenROAD.IOPlacement,
            Odb.CustomIOPlacement,
            Odb.ApplyDEFTemplate,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["global_placement"],
        "provider": "openroad",
        "steps": [OpenROAD.GlobalPlacement],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["post_gpl_repair"],
        "provider": "openroad",
        "steps": [OpenROAD.RepairDesignPostGPL],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["detailed_placement"],
        "provider": "openroad",
        "steps": [OpenROAD.DetailedPlacement],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["cts"],
        "provider": "openroad",
        "steps": [OpenROAD.CTS],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["post_cts_opt"],
        "provider": "openroad",
        "steps": [OpenROAD.ResizerTimingPostCTS],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["global_routing"],
        "provider": "openroad",
        "steps": [OpenROAD.GlobalRouting, OpenROAD.CheckAntennas],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["post_grt_repair"],
        "provider": "openroad",
        "steps": [OpenROAD.RepairDesignPostGRT],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["antenna_repair"],
        "provider": "openroad",
        "steps": [
            Odb.DiodesOnPorts,
            Odb.HeuristicDiodeInsertion,
            OpenROAD.RepairAntennas,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["post_grt_opt"],
        "provider": "openroad",
        "steps": [OpenROAD.ResizerTimingPostGRT],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["detailed_routing"],
        "provider": "openroad",
        "steps": [
            OpenROAD.DetailedRouting,
            Odb.RemoveRoutingObstructions,
            OpenROAD.CheckAntennas,
            Checker.TrDRC,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["fill_insertion"],
        "provider": "openroad",
        "steps": [OpenROAD.FillInsertion],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["extraction"],
        "provider": "openroad",
        "steps": [OpenROAD.RCX],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "stages": ["signoff_sta"],
        "provider": "openroad",
        "steps": [OpenROAD.STAPostPNR],
        "namespaces": _OPENROAD_NAMESPACES,
        # OpenROAD.STAPostPNR takes odb only optionally, so it is not declared
        # native here: this stage can run on a boundary that carries no odb.
    },
    {
        "stages": ["ir_drop"],
        "provider": "openroad",
        "steps": [OpenROAD.IRDropReport],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "stages": ["streamout"],
        "provider": "magic",
        "steps": [Magic.StreamOut],
        "namespaces": _MAGIC_NAMESPACES,
        "provides": [DesignFormat.mag_gds],
    },
    {
        "stages": ["streamout"],
        "provider": "klayout",
        "steps": [KLayout.StreamOut, KLayout.Render],
        "namespaces": ("KLAYOUT_",),
        "provides": [DesignFormat.klayout_gds],
    },
    # Each DRC provider owns the checker that reads its metric. A checker
    # declares no inputs, so the view preflight cannot catch it being orphaned;
    # ownership is the only thing that removes it along with the tool it checks.
    {
        "stages": ["drc"],
        "provider": "magic",
        "steps": [Magic.DRC, Checker.MagicDRC],
        "namespaces": _MAGIC_NAMESPACES + ("ERROR_ON_MAGIC_DRC",),
        "metrics": ["magic__drc_error__count"],
    },
    {
        "stages": ["drc"],
        "provider": "klayout",
        "steps": [KLayout.DRC, Checker.KLayoutDRC],
        "namespaces": ("KLAYOUT_", "ERROR_ON_KLAYOUT_DRC"),
        "metrics": ["klayout__drc_error__count"],
    },
    {
        "stages": ["lvs"],
        "provider": "netgen",
        "steps": [
            Magic.SpiceExtraction,
            Checker.IllegalOverlap,
            Netgen.LVS,
            Checker.LVS,
        ],
        "namespaces": _MAGIC_NAMESPACES
        + ("NETGEN_", "LVS_", "ERROR_ON_ILLEGAL_OVERLAPS", "ERROR_ON_LVS_ERROR"),
        "metrics": ["magic__illegal_overlap__count"],
    },
    {
        "stages": ["formal_equivalence"],
        "provider": "yosys",
        "steps": [Yosys.EQY],
        "namespaces": _YOSYS_NAMESPACES
        + ("EQY_", "VERILOG_", "SLANG_", "USE_SLANG", "MACRO_PLACEMENT_CFG"),
    },
]


for _entry in _REGISTRATIONS:
    StageRegistry.register(**_entry)
