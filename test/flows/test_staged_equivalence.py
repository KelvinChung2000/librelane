# Copyright 2026 LibreLane Contributors
import json
import os

import pytest

from librelane.flows import Flow

pytestmark = pytest.mark.all

GOLDEN_DIR = os.path.dirname(__file__)


def _step_ids(FlowClass) -> list[str]:
    return [step.id for step in FlowClass.Steps]


def _implementation_ids(FlowClass) -> list[str]:
    return [step.get_implementation_id() for step in FlowClass.Steps]


def _snapshot(FlowClass) -> dict:
    return {
        "step_ids": _step_ids(FlowClass),
        "implementation_ids": _implementation_ids(FlowClass),
        "gating_config_vars": {
            key: list(value)
            for key, value in sorted(FlowClass.gating_config_vars.items())
        },
        "config_var_names": sorted(variable.name for variable in FlowClass.config_vars),
    }


def _load_golden(name: str) -> dict:
    with open(os.path.join(GOLDEN_DIR, name), encoding="utf8") as stream:
        return json.load(stream)


def test_classic_steps_match_golden():
    Classic = Flow.factory.get("Classic")
    assert _snapshot(Classic) == _load_golden("classic_steps.json")


def test_vhdl_classic_steps_match_golden():
    VHDLClassic = Flow.factory.get("VHDLClassic")
    assert _snapshot(VHDLClassic) == _load_golden("vhdl_classic_steps.json")


def test_vhdl_classic_declares_its_own_stages_rather_than_substitutions():
    """
    The strongest available validation that the abstraction does its job: a real
    tool swap between two real tools, expressed as a flow declaring the stages
    it runs and pinning a provider for one of them, reproducing byte-for-byte a
    step list that until now took a Substitutions map to produce.
    """
    from librelane.stages import Stage

    VHDLClassic = Flow.factory.get("VHDLClassic")

    assert "Stages" in VHDLClassic.__dict__, (
        "VHDLClassic must declare its own Stages list, not inherit Classic's"
    )
    synthesis = [
        entry
        for entry in VHDLClassic.Stages
        if isinstance(entry, Stage) and entry.id == "synthesis"
    ]
    assert [entry.default_providers for entry in synthesis] == [("yosys_vhdl",)]
    assert _snapshot(VHDLClassic) == _load_golden("vhdl_classic_steps.json")


GATING_VARIABLES = [
    "RUN_TAP_ENDCAP_INSERTION",
    "RUN_POST_GPL_DESIGN_REPAIR",
    "RUN_POST_GRT_DESIGN_REPAIR",
    "RUN_CTS",
    "RUN_POST_CTS_RESIZER_TIMING",
    "RUN_POST_GRT_RESIZER_TIMING",
    "RUN_HEURISTIC_DIODE_INSERTION",
    "RUN_ANTENNA_REPAIR",
    "RUN_DRT",
    "RUN_FILL_INSERTION",
    "RUN_MCSTA",
    "RUN_SPEF_EXTRACTION",
    "RUN_IRDROP_REPORT",
    "RUN_LVS",
    "RUN_MAGIC_STREAMOUT",
    "RUN_KLAYOUT_STREAMOUT",
    "RUN_MAGIC_WRITE_LEF",
    "RUN_KLAYOUT_XOR",
    "RUN_MAGIC_DRC",
    "RUN_KLAYOUT_DRC",
    "RUN_EQY",
    "RUN_LINTER",
]


def _gated_step_ids(FlowClass, disabled: str) -> list[str]:
    """Step IDs that would be skipped if exactly `disabled` were False."""
    from librelane.common import Filter

    step_ids = [step.id for step in FlowClass.Steps]
    gated = set()
    for key, variables in FlowClass.gating_config_vars.items():
        if disabled not in variables:
            continue
        if key in step_ids:
            gated.add(key)
            continue
        gated.update(Filter([key]).filter(step_ids))
    return sorted(gated)


#: Gating variables whose reach changed when gating moved to the stage level.
#: Each entry is the full set of step IDs skipped after the change. Gating a
#: stage skips every step in it, and these three stages contain steps the old
#: step-level keys did not reach. See Changelog.md for why each is correct.
WIDENED_GATES = {
    "RUN_DRT": [
        "Checker.TrDRC",
        "Odb.RemoveRoutingObstructions",
        "OpenROAD.CheckAntennas-1",
        "OpenROAD.DetailedRouting",
    ],
    "RUN_ANTENNA_REPAIR": [
        "Odb.DiodesOnPorts",
        "Odb.HeuristicDiodeInsertion",
        "OpenROAD.RepairAntennas",
    ],
    "RUN_LVS": [
        "Checker.IllegalOverlap",
        "Checker.LVS",
        "Magic.SpiceExtraction",
        "Netgen.LVS",
    ],
}


def test_unchanged_gates_still_match_golden():
    Classic = Flow.factory.get("Classic")
    golden = _load_golden("classic_gating.json")
    for variable in GATING_VARIABLES:
        if variable in WIDENED_GATES:
            continue
        assert _gated_step_ids(Classic, variable) == golden[variable], variable


def test_widened_gates_have_their_documented_reach():
    Classic = Flow.factory.get("Classic")
    for variable, expected in WIDENED_GATES.items():
        assert _gated_step_ids(Classic, variable) == expected, variable
