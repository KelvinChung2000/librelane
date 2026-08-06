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

Every sequence here is a partition of what the ``Classic`` flow class ran. A
golden equivalence test pinned them down against that class; the class and the
test went with phase 5, and ``test/flows/test_documents.py`` is what exercises
these sequences now, through the documents that resolve to them.

The registrations are declared as data and applied in a loop at the bottom of
the module. Keeping them as data is what let the ``namespaces`` and
``native_views`` values be derived mechanically from each sequence's actual
declarations rather than guessed.
"""

from librelane.state import DesignFormat
from librelane.steps import (
    KLayout,
    Magic,
    Netgen,
    Odb,
    OpenROAD,
    Verilator,
    Yosys,
)

from librelane.jobs.registry import JobRegistry

#: Accepted configuration variable prefixes and names for the OpenROAD step
#: family. The prefixes predate this design and are not renamed by it; the bare
#: names are variables that never acquired a prefix. Declared once for the whole
#: family rather than per job, because these steps share a base config model.
#:
#: Every entry was produced by enumerating what the sequences actually declare,
#: not by guessing. A variable that is neither canonical for its job nor a
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
    "MANUAL_GLOBAL_PLACEMENTS",
    "ERRORS_ON_UNMATCHED_IO",
    "HEURISTIC_ANTENNA_THRESHOLD",
    "NON_DEFAULT_RULES",
    "ROUTING_OBSTRUCTIONS",
    "VSRC_LOC_FILES",
    # Limits the OpenROAD steps raise on their own measurements, and the
    # corners the timing ones apply at. These belonged to the deleted
    # 'Checker.*' steps, which is why they read like nobody's namespace: they
    # were nobody's, until each moved onto the step that took the measurement.
    "ERROR_ON_TR_DRC",
    "ERROR_ON_PDN_VIOLATIONS",
    "TIMING_VIOLATION_CORNERS",
    "SETUP_VIOLATION_CORNERS",
    "HOLD_VIOLATION_CORNERS",
    "MAX_SLEW_VIOLATION_CORNERS",
    "MAX_CAP_VIOLATION_CORNERS",
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
#: into any job's ``requires``;
#: :func:`librelane.flows.selection_validation.lost_views` is what verifies an
#: OpenROAD job is actually preceded by one that produces it, over the steps a
#: run resolved rather than over the document's declarations.
_ODB = (DesignFormat.odb,)

_REGISTRATIONS: list[dict] = [
    {
        "job": "lint",
        "provider": "verilator",
        "steps": [Verilator.Lint],
        "namespaces": ("LINTER_", "ERROR_ON_LINTER_", "VERILOG_"),
    },
    {
        "job": "synthesis",
        "provider": "yosys",
        "steps": [Yosys.JsonHeader, Yosys.Synthesis],
        "namespaces": _YOSYS_NAMESPACES + ("VERILOG_", "SLANG_", "USE_SLANG"),
        "provides": [DesignFormat.json_h],
    },
    {
        "job": "synthesis",
        "provider": "yosys_vhdl",
        "steps": [Yosys.VHDLSynthesis],
        "namespaces": _YOSYS_NAMESPACES + ("GHDL_", "VHDL_"),
    },
    {
        "job": "pre_pnr_sta",
        "provider": "openroad",
        "steps": [
            OpenROAD.CheckSDCFiles,
            OpenROAD.CheckMacroInstances,
            OpenROAD.STAPrePNR,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "job": "floorplan",
        "provider": "openroad",
        # Odb.SetPowerConnections used to be the last step here, which forced
        # this registration to declare json_h as a native view. That made a
        # Verilog-only step a mandatory member of a tool-neutral job: a VHDL
        # flow needs floorplanning but has no Verilog header, and had no way to
        # say "floorplan, but not that step". classic.yaml gives it a job of
        # its own listing that one step inline, so vhdl_classic.yaml simply
        # does not declare that job.
        "steps": [
            OpenROAD.Floorplan,
            OpenROAD.DumpRCValues,
            Odb.CheckMacroAntennaProperties,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "job": "macro_placement",
        "provider": "openroad",
        # OpenROAD.CutRows consumes odb, so it only means anything when this
        # job resolved to OpenROAD, which is what makes it a member of this
        # registration rather than a step a document lists. Every document that
        # placed macros ran it immediately afterwards.
        # Manual placement runs first and fixes its instances;
        # OpenROAD.RTLMacroPlacer (opt-in via RUN_RTLMP) then places whatever
        # macros remain unfixed.
        "steps": [Odb.ManualMacroPlacement, OpenROAD.RTLMacroPlacer, OpenROAD.CutRows],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "tapcell_insertion",
        "provider": "openroad",
        "steps": [OpenROAD.TapEndcapInsertion],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "power_grid",
        "provider": "openroad",
        # Odb.AddRoutingObstructions joins its two PDN siblings for the same
        # reason they are here: it edits an odb. Its partner
        # Odb.RemoveRoutingObstructions already sits inside detailed_routing.
        "steps": [
            Odb.AddPDNObstructions,
            OpenROAD.GeneratePDN,
            Odb.RemovePDNObstructions,
            Odb.AddRoutingObstructions,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "io_placement",
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
        "job": "global_placement",
        "provider": "openroad",
        "steps": [OpenROAD.GlobalPlacement],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "post_gpl_repair",
        "provider": "openroad",
        "steps": [OpenROAD.RepairDesignPostGPL],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "detailed_placement",
        "provider": "openroad",
        # Odb.ManualGlobalPlacement first, as every document ran it
        # immediately before detailed placement. It edits an odb, so it is
        # OpenROAD's to run.
        "steps": [Odb.ManualGlobalPlacement, OpenROAD.DetailedPlacement],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "cts",
        "provider": "openroad",
        "steps": [OpenROAD.CTS],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "post_cts_opt",
        "provider": "openroad",
        "steps": [OpenROAD.ResizerTimingPostCTS],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "global_routing",
        "provider": "openroad",
        "steps": [OpenROAD.GlobalRouting, OpenROAD.CheckAntennas],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "post_grt_repair",
        "provider": "openroad",
        "steps": [OpenROAD.RepairDesignPostGRT],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "antenna_repair",
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
        "job": "post_grt_opt",
        "provider": "openroad",
        "steps": [OpenROAD.ResizerTimingPostGRT],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "detailed_routing",
        "provider": "openroad",
        "steps": [
            OpenROAD.DetailedRouting,
            Odb.RemoveRoutingObstructions,
            OpenROAD.CheckAntennas,
        ],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "fill_insertion",
        "provider": "openroad",
        "steps": [OpenROAD.FillInsertion],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "extraction",
        "provider": "openroad",
        "steps": [OpenROAD.RCX],
        "namespaces": _OPENROAD_NAMESPACES,
    },
    {
        "job": "signoff_sta",
        "provider": "openroad",
        "steps": [OpenROAD.STAPostPNR],
        "namespaces": _OPENROAD_NAMESPACES,
        # OpenROAD.STAPostPNR takes odb only optionally, so it is not declared
        # native here: this job can run on a boundary that carries no odb.
    },
    {
        "job": "ir_drop",
        "provider": "openroad",
        "steps": [OpenROAD.IRDropReport],
        "namespaces": _OPENROAD_NAMESPACES,
        "native_views": _ODB,
    },
    {
        "job": "streamout",
        "provider": "magic",
        "steps": [Magic.StreamOut],
        "namespaces": _MAGIC_NAMESPACES,
        "provides": [DesignFormat.mag_gds],
    },
    {
        "job": "streamout",
        "provider": "klayout",
        "steps": [KLayout.StreamOut],
        "namespaces": ("KLAYOUT_",),
        "provides": [DesignFormat.klayout_gds],
    },
    {
        "job": "drc",
        "provider": "magic",
        "steps": [Magic.DRC],
        "namespaces": _MAGIC_NAMESPACES + ("ERROR_ON_MAGIC_DRC",),
        "metrics": ["magic__drc_error__count"],
    },
    {
        "job": "drc",
        "provider": "klayout",
        "steps": [KLayout.DRC],
        "namespaces": ("KLAYOUT_", "ERROR_ON_KLAYOUT_DRC"),
        "metrics": ["klayout__drc_error__count"],
    },
    {
        "job": "lvs",
        "provider": "netgen",
        "steps": [Magic.SpiceExtraction, Netgen.LVS],
        "namespaces": _MAGIC_NAMESPACES
        + ("NETGEN_", "LVS_", "ERROR_ON_ILLEGAL_OVERLAPS", "ERROR_ON_LVS_ERROR"),
        "metrics": ["magic__illegal_overlap__count"],
    },
    # The alternative to the sequence above, not an addition to it. Every
    # shipped document declares `lvs` once, so exactly one of the two providers
    # runs and both are free to write the job's contracted
    # `design__lvs_error__count`. That licence ends the moment a document
    # declares two `lvs` jobs pinning a provider each, the way classic.yaml
    # declares `magic_drc` and `klayout_drc`: both would run and the last to
    # finish would silently win. Issue 696 asks for exactly that, and it would
    # land on two shared names, not one: the metric, and the `spice` view that
    # `Magic.SpiceExtraction` and `KLayout.LVS` both output.
    #
    # A shared name between jobs that run together is not itself the hazard,
    # and a registration-time prohibition on one would be wrong. classic.yaml's
    # `magic_streamout` and `klayout_streamout` both output `gds`, which the
    # flow depends on: every later consumer, Magic.WriteLEF and the signoff
    # steps included, reads the neutral view. What makes that safe is that the
    # two steps implement an explicit precedence rule, keyed on the PDK's
    # `PRIMARY_GDSII_STREAMOUT_TOOL` -- the primary tool always writes `gds`, a
    # non-primary one only when nothing has (steps/magic.py:368,
    # steps/klayout/views.py:236), so the outcome does not depend on which job
    # ran last.
    #
    # Neither the `spice` view nor `design__lvs_error__count` has such a rule:
    # both writers write unconditionally, so two `lvs` jobs running together
    # really would be decided by position, invisibly. The missing piece is an
    # explicit statement of which contributor wins, which is what a document's
    # `source:` key is for, not a ban on sharing.
    #
    # OpenROAD.WriteCDL is inside the sequence for the same reason
    # Magic.SpiceExtraction is inside netgen's: KLayout.LVS compares the layout
    # against a CDL, no job promises one, and `lvs.requires` must not grow a
    # view that only one of the two providers can use. It declares openroad's
    # namespaces to match, exactly as netgen's declares magic's.
    {
        "job": "lvs",
        "provider": "klayout",
        "steps": [OpenROAD.WriteCDL, KLayout.LVS],
        "namespaces": _OPENROAD_NAMESPACES + ("KLAYOUT_", "ERROR_ON_LVS_ERROR"),
        "native_views": _ODB,
    },
    {
        "job": "formal_equivalence",
        "provider": "yosys",
        "steps": [Yosys.EQY],
        "namespaces": _YOSYS_NAMESPACES
        + ("EQY_", "VERILOG_", "SLANG_", "USE_SLANG", "MACRO_PLACEMENT_CFG"),
    },
]


for _entry in _REGISTRATIONS:
    JobRegistry.register(**_entry)
