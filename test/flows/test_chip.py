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

import pytest

pytestmark = pytest.mark.all

#: Chip's step list, captured from the running flow before it was converted to
#: an explicit Stages list. Any difference between this and what the explicit
#: list expands to is a conversion error, not an improvement.
GOLDEN = [
    "Verilator.Lint",
    "Checker.LintTimingConstructs",
    "Checker.LintErrors",
    "Checker.LintWarnings",
    "Yosys.JsonHeader",
    "Yosys.Synthesis",
    "Checker.YosysUnmappedCells",
    "Checker.YosysSynthChecks",
    "Checker.NetlistAssignStatements",
    "OpenROAD.CheckSDCFiles",
    "OpenROAD.CheckMacroInstances",
    "OpenROAD.STAPrePNR",
    "OpenROAD.Floorplan",
    "OpenROAD.DumpRCValues",
    "Odb.CheckMacroAntennaProperties",
    "Odb.SetPowerConnections",
    "OpenROAD.PadRing",
    "Odb.ManualMacroPlacement",
    "OpenROAD.CutRows",
    "OpenROAD.TapEndcapInsertion",
    "Odb.AddPDNObstructions",
    "OpenROAD.GeneratePDN",
    "Odb.RemovePDNObstructions",
    "Odb.AddRoutingObstructions",
    "OpenROAD.GlobalPlacementSkipIO",
    "Odb.ApplyDEFTemplate",
    "OpenROAD.GlobalPlacement",
    "Odb.WriteVerilogHeader",
    "Checker.PowerGridViolations",
    "OpenROAD.STAMidPNR",
    "OpenROAD.RepairDesignPostGPL",
    "Odb.ManualGlobalPlacement",
    "OpenROAD.DetailedPlacement",
    "OpenROAD.CTS",
    "OpenROAD.STAMidPNR-1",
    "OpenROAD.ResizerTimingPostCTS",
    "OpenROAD.STAMidPNR-2",
    "OpenROAD.GlobalRouting",
    "OpenROAD.CheckAntennas",
    "OpenROAD.RepairDesignPostGRT",
    "Odb.DiodesOnPorts",
    "Odb.HeuristicDiodeInsertion",
    "OpenROAD.RepairAntennas",
    "OpenROAD.ResizerTimingPostGRT",
    "OpenROAD.STAMidPNR-3",
    "OpenROAD.DetailedRouting",
    "Odb.RemoveRoutingObstructions",
    "OpenROAD.CheckAntennas-1",
    "Checker.TrDRC",
    "Odb.ReportDisconnectedPins",
    "Checker.DisconnectedPins",
    "Odb.ReportWireLength",
    "Checker.WireLength",
    "OpenROAD.FillInsertion",
    "Odb.CellFrequencyTables",
    "OpenROAD.RCX",
    "OpenROAD.STAPostPNR",
    "OpenROAD.IRDropReport",
    "Magic.StreamOut",
    "KLayout.StreamOut",
    "KLayout.Render",
    "KLayout.XOR",
    "Checker.XOR",
    "KLayout.Antenna",
    "Checker.KLayoutAntenna",
    "KLayout.SealRing",
    "KLayout.Filler",
    "KLayout.Density",
    "Checker.KLayoutDensity",
    "Magic.DRC",
    "Checker.MagicDRC",
    "KLayout.DRC",
    "Checker.KLayoutDRC",
    "Magic.SpiceExtraction",
    "Checker.IllegalOverlap",
    "Netgen.LVS",
    "Checker.LVS",
    "Yosys.EQY",
    "Checker.SetupViolations",
    "Checker.HoldViolations",
    "Checker.MaxSlewViolations",
    "Checker.MaxCapViolations",
    "Misc.ReportManufacturability",
]


def test_chip_expands_to_the_same_steps_the_substitution_map_produced():
    from librelane.flows import Flow

    Chip = Flow.factory.get("Chip")
    assert [step.id for step in Chip.Steps] == GOLDEN


def test_chip_declares_its_own_stages_rather_than_patching_classic():
    from librelane.flows import Flow

    Chip = Flow.factory.get("Chip")
    Classic = Flow.factory.get("Classic")
    assert "Stages" in Chip.__dict__, (
        "Chip must declare its own Stages list, not inherit Classic's"
    )
    assert Chip.Stages != Classic.Stages
