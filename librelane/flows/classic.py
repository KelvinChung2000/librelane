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
from librelane.flows.flow import Flow
from librelane.flows.staged import StagedFlow
from librelane.config import variable
from librelane.jobs import Job

# Netgen, Verilator and Yosys no longer appear here: their steps are named by
# the provider registrations in librelane/jobs/providers.py, which is what
# makes them substitutable from configuration.
from librelane.steps import (
    OpenROAD,
    Magic,
    KLayout,
    Odb,
    Checker,
    Misc,
)


@Flow.factory.register()
class Classic(StagedFlow):
    """
    A flow of type :class:`librelane.flows.SequentialFlow` that is the most
    similar to the original OpenLane flow, running the Verilog RTL through
    Yosys, OpenROAD, KLayout and Magic to produce a valid GDSII for simpler designs.

    This is the default when using LibreLane via the command-line.
    """

    Stages = [
        Job.lint,
        Job.synthesis,
        Job.pre_pnr_sta,
        Job.floorplan,
        OpenROAD.RMP,
        # A plain step rather than part of the floorplan job, because it
        # hard-requires the Verilog header only Verilog synthesis emits. A flow
        # whose synthesis frontend cannot produce one omits this entry.
        Odb.SetPowerConnections,
        Job.macro_placement,
        OpenROAD.CutRows,
        Job.tapcell_insertion,
        Job.power_grid,
        Odb.AddRoutingObstructions,
        Job.io_placement,
        # Before global placement, deliberately: the port buffers exist by the
        # time placement runs, so the logic is placed around them (#917).
        OpenROAD.AddBuffer,
        Job.global_placement,
        Odb.WriteVerilogHeader,
        Checker.PowerGridViolations,
        OpenROAD.STAMidPNR,
        Job.post_gpl_repair,
        Odb.ManualGlobalPlacement,
        Job.detailed_placement,
        Job.cts,
        OpenROAD.STAMidPNR,
        Job.post_cts_opt,
        OpenROAD.STAMidPNR,
        Job.global_routing,
        Job.post_grt_repair,
        Job.antenna_repair,
        Job.post_grt_opt,
        OpenROAD.STAMidPNR,
        Job.detailed_routing,
        Odb.ReportDisconnectedPins,
        Checker.DisconnectedPins,
        Odb.ReportWireLength,
        Checker.WireLength,
        Job.post_route_opt,
        Job.fill_insertion,
        Odb.CellFrequencyTables,
        Job.extraction,
        Job.signoff_sta,
        Job.ir_drop,
        Job.streamout,
        # Not part of the streamout job: its inputs are optional and its
        # outputs are empty, so it satisfies no part of the job's 'gds'
        # contract and carries no view across the job boundary. It is also
        # ungated where KLayout.StreamOut is gated, which a job-level 'if'
        # cannot express while the two share a registration.
        KLayout.Render,
        Magic.WriteLEF,
        Odb.CheckDesignAntennaProperties,
        KLayout.XOR,
        Checker.XOR,
        Job.drc,
        Job.lvs,
        Job.formal_equivalence,
        Checker.SetupViolations,
        Checker.HoldViolations,
        Checker.MaxSlewViolations,
        Checker.MaxCapViolations,
        Misc.ReportManufacturability,
    ]

    class Config(StagedFlow.Config):
        RUN_TAP_ENDCAP_INSERTION: bool = variable(
            True,
            description="Enables the OpenROAD.TapEndcapInsertion step.",
            deprecated_names=["TAP_DECAP_INSERTION", "RUN_TAP_DECAP_INSERTION"],
        )

        RUN_RMP: bool = variable(
            False,
            description="Enables local resynthesis after floorplanning using the OpenROAD.RMP step. This is experimental and changes the netlist every later step works on.",
        )

        RUN_POST_GPL_DESIGN_REPAIR: bool = variable(
            True,
            description="Enables resizer design repair after global placement using the OpenROAD.RepairDesignPostGPL step.",
            deprecated_names=["PL_RESIZER_DESIGN_OPTIMIZATIONS", "RUN_REPAIR_DESIGN"],
        )

        RUN_POST_GRT_DESIGN_REPAIR: bool = variable(
            False,
            description="Enables resizer design repair after global routing using the OpenROAD.RepairDesignPostGRT step. This is experimental and may result in hangs and/or extended run times.",
        )

        RUN_CTS: bool = variable(
            True,
            description="Enables clock tree synthesis using the OpenROAD.CTS step.",
            deprecated_names=["CLOCK_TREE_SYNTH"],
        )

        RUN_POST_CTS_RESIZER_TIMING: bool = variable(
            True,
            description="Enables resizer timing optimizations after clock tree synthesis using the OpenROAD.ResizerTimingPostCTS step.",
            deprecated_names=["PL_RESIZER_TIMING_OPTIMIZATIONS"],
        )

        RUN_POST_GRT_RESIZER_TIMING: bool = variable(
            False,
            description="Enables resizer timing optimizations after global routing using the OpenROAD.ResizerTimingPostGRT step. This is experimental and may result in hangs and/or extended run times.",
            deprecated_names=["GLB_RESIZER_TIMING_OPTIMIZATIONS"],
        )

        RUN_HEURISTIC_DIODE_INSERTION: bool = variable(
            False,
            description="Enables the Odb.HeuristicDiodeInsertion step.",
        )

        RUN_ANTENNA_REPAIR: bool = variable(
            True,
            description="Enables the OpenROAD.RepairAntennas step.",
            deprecated_names=["GRT_REPAIR_ANTENNAS"],
        )

        RUN_DRT: bool = variable(
            True,
            description="Enables the OpenROAD.DetailedRouting step.",
        )

        RUN_FILL_INSERTION: bool = variable(
            True,
            description="Enables the OpenROAD.FillInsertion step.",
        )

        RUN_MCSTA: bool = variable(
            True,
            description="Enables multi-corner static timing analysis using the OpenROAD.STAPostPNR step.",
            deprecated_names=["RUN_SPEF_STA"],
        )

        RUN_SPEF_EXTRACTION: bool = variable(
            True,
            description="Enables parasitics extraction using the OpenROAD.RCX step.",
        )

        RUN_IRDROP_REPORT: bool = variable(
            True,
            description="Enables generation of an IR Drop report using the OpenROAD.IRDropReport step.",
        )

        RUN_LVS: bool = variable(
            True,
            description="Enables the Netgen.LVS step.",
        )

        RUN_MAGIC_STREAMOUT: bool = variable(
            True,
            description="Enables the Magic.StreamOut step to generate GDSII.",
            deprecated_names=["RUN_MAGIC"],
        )

        RUN_KLAYOUT_STREAMOUT: bool = variable(
            True,
            description="Enables the KLayout.StreamOut step to generate GDSII.",
            deprecated_names=["RUN_KLAYOUT"],
        )

        RUN_MAGIC_WRITE_LEF: bool = variable(
            True,
            description="Enables the Magic.WriteLEF step.",
            deprecated_names=["MAGIC_GENERATE_LEF"],
        )

        RUN_KLAYOUT_XOR: bool = variable(
            True,
            description="Enables running the KLayout.XOR step on the two GDSII files generated by Magic and Klayout. Stream-outs for both KLayout and Magic should have already run, and the PDK must support both signoff tools.",
        )

        RUN_MAGIC_DRC: bool = variable(
            True,
            description="Enables the Magic.DRC step.",
        )

        RUN_KLAYOUT_DRC: bool = variable(
            True,
            description="Enables the KLayout.DRC step.",
        )

        RUN_EQY: bool = variable(
            False,
            description="Enables the formal equivalence job, i.e. the Yosys.EQY step. Has no effect in VHDLClassic, which does not run that job.",
        )

        RUN_LINTER: bool = variable(
            True,
            description="Enables the lint job, i.e. the Verilator.Lint step and associated checker steps. Has no effect in VHDLClassic, which does not run that job.",
            deprecated_names=["RUN_VERILATOR"],
        )

    # Fifteen entries that used to live here are now generated from the job
    # taxonomy's gating_config_var, so they gate whichever provider is selected
    # rather than only the OpenROAD step that happened to be named. What remains
    # is the gates that address one tool *inside* a multi_provider job, or a
    # plain step that is not part of any job.
    gating_config_vars = {
        "OpenROAD.RMP": ["RUN_RMP"],
        "Odb.HeuristicDiodeInsertion": ["RUN_HEURISTIC_DIODE_INSERTION"],
        "Magic.StreamOut": ["RUN_MAGIC_STREAMOUT"],
        "KLayout.StreamOut": ["RUN_KLAYOUT_STREAMOUT"],
        "Magic.WriteLEF": ["RUN_MAGIC_WRITE_LEF"],
        "Magic.DRC": ["RUN_MAGIC_DRC"],
        "KLayout.DRC": ["RUN_KLAYOUT_DRC"],
        "Checker.MagicDRC": ["RUN_MAGIC_DRC"],
        "Checker.KLayoutDRC": ["RUN_KLAYOUT_DRC"],
        "KLayout.XOR": [
            "RUN_KLAYOUT_XOR",
            "RUN_MAGIC_STREAMOUT",
            "RUN_KLAYOUT_STREAMOUT",
        ],
        "Checker.XOR": [
            "RUN_KLAYOUT_XOR",
            "RUN_MAGIC_STREAMOUT",
            "RUN_KLAYOUT_STREAMOUT",
        ],
    }


@Flow.factory.register()
class VHDLClassic(Classic):
    """
    A variant of Classic that accepts VHDL files for Synthesis instead of
    Verilog files (and removes the Verilog linting, equivalence-checking and
    power-header steps, none of which can run without Verilog sources.)

    It subclasses :class:`Classic` for the configuration variables, which are
    genuinely shared, but declares its own ``Stages``: it is a different flow,
    not a differently configured one.
    """

    #: Written out in full rather than derived from ``Classic.Stages`` by
    #: filtering, deliberately. A flow is a self-contained declaration of what
    #: it runs; a filter expression over another flow's list is a substitution
    #: map wearing a different hat, and reintroduces exactly the coupling this
    #: list exists to remove. The differences from ``Classic`` are the pinned
    #: synthesis provider and the four omitted entries: ``Job.lint``,
    #: ``Odb.SetPowerConnections``, ``Odb.WriteVerilogHeader`` and
    #: ``Job.formal_equivalence``.
    Stages = [
        Job.synthesis.using("yosys_vhdl"),
        Job.pre_pnr_sta,
        Job.floorplan,
        OpenROAD.RMP,
        Job.macro_placement,
        OpenROAD.CutRows,
        Job.tapcell_insertion,
        Job.power_grid,
        Odb.AddRoutingObstructions,
        Job.io_placement,
        OpenROAD.AddBuffer,
        Job.global_placement,
        Checker.PowerGridViolations,
        OpenROAD.STAMidPNR,
        Job.post_gpl_repair,
        Odb.ManualGlobalPlacement,
        Job.detailed_placement,
        Job.cts,
        OpenROAD.STAMidPNR,
        Job.post_cts_opt,
        OpenROAD.STAMidPNR,
        Job.global_routing,
        Job.post_grt_repair,
        Job.antenna_repair,
        Job.post_grt_opt,
        OpenROAD.STAMidPNR,
        Job.detailed_routing,
        Odb.ReportDisconnectedPins,
        Checker.DisconnectedPins,
        Odb.ReportWireLength,
        Checker.WireLength,
        Job.post_route_opt,
        Job.fill_insertion,
        Odb.CellFrequencyTables,
        Job.extraction,
        Job.signoff_sta,
        Job.ir_drop,
        Job.streamout,
        # Not part of the streamout job: its inputs are optional and its
        # outputs are empty, so it satisfies no part of the job's 'gds'
        # contract and carries no view across the job boundary. It is also
        # ungated where KLayout.StreamOut is gated, which a job-level 'if'
        # cannot express while the two share a registration.
        KLayout.Render,
        Magic.WriteLEF,
        Odb.CheckDesignAntennaProperties,
        KLayout.XOR,
        Checker.XOR,
        Job.drc,
        Job.lvs,
        Checker.SetupViolations,
        Checker.HoldViolations,
        Checker.MaxSlewViolations,
        Checker.MaxCapViolations,
        Misc.ReportManufacturability,
    ]
