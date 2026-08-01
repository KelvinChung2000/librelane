# Copyright 2025 LibreLane Contributors
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
from librelane.flows.classic import Classic
from librelane.jobs import Job
from librelane.steps import (
    OpenROAD,
    KLayout,
    Odb,
    Checker,
    Misc,
)


@Flow.factory.register()
class Chip(Classic):
    """
    A flow of type :class:`librelane.flows.SequentialFlow` that is used
    to implement complete chip designs. This includes pad ring generation,
    seal ring generation, filler insertion, and density check.

    It subclasses :class:`Classic` for the configuration variables, which are
    genuinely shared, but declares its own ``Stages``.
    """

    #: Written out in full rather than derived from ``Classic.Stages``, for the
    #: reason given on ``VHDLClassic.Stages``. The differences from ``Classic``
    #: are ``OpenROAD.PadRing`` after ``Odb.SetPowerConnections``, the six
    #: finishing steps after ``Checker.XOR``, and three omissions:
    #: ``Magic.WriteLEF`` and ``Odb.CheckDesignAntennaProperties``, which a chip
    #: does not need because it is not a macro, and ``Job.io_placement``,
    #: whose pins are the pad ring's bumps.
    #:
    #: ``Job.io_placement`` is omitted rather than pinned to another provider,
    #: and the two steps of it a chip still needs are listed here as plain
    #: steps. ``OpenROAD.GlobalPlacementSkipIO`` seeds placement before the pins
    #: exist and ``Odb.ApplyDEFTemplate`` copies a pin arrangement from a
    #: template, neither of which places a pin itself. The cost is that this
    #: flow has no ``io_placement`` boundary and so cannot swap that job's
    #: tool from ``TOOLS``.
    Stages = [
        Job.lint,
        Job.synthesis,
        Job.pre_pnr_sta,
        Job.floorplan,
        Odb.SetPowerConnections,
        OpenROAD.PadRing,
        Job.macro_placement,
        OpenROAD.CutRows,
        Job.tapcell_insertion,
        Job.power_grid,
        Odb.AddRoutingObstructions,
        OpenROAD.GlobalPlacementSkipIO,
        Odb.ApplyDEFTemplate,
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
        KLayout.XOR,
        Checker.XOR,
        KLayout.Antenna,
        Checker.KLayoutAntenna,
        KLayout.SealRing,
        KLayout.Filler,
        KLayout.Density,
        Checker.KLayoutDensity,
        Job.drc,
        Job.lvs,
        Job.formal_equivalence,
        Checker.SetupViolations,
        Checker.HoldViolations,
        Checker.MaxSlewViolations,
        Checker.MaxCapViolations,
        Misc.ReportManufacturability,
    ]

    #: ``Classic`` gates ``Magic.WriteLEF`` with ``RUN_MAGIC_WRITE_LEF``, and
    #: this flow has no such step, so that entry is dropped. The rest are
    #: restated rather than inherited because ``_explicit_gating_config_vars``
    #: is what a subclass inherits and a gating key naming no step raises.
    gating_config_vars = {
        "Odb.HeuristicDiodeInsertion": ["RUN_HEURISTIC_DIODE_INSERTION"],
        "Magic.StreamOut": ["RUN_MAGIC_STREAMOUT"],
        "KLayout.StreamOut": ["RUN_KLAYOUT_STREAMOUT"],
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
