# Copyright 2026 LibreLane Contributors
import pytest

from librelane.flows import flow as flow_module, sequential as sequential_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

#: The minimum a Classic instance needs to reach the point where Steps are
#: expanded, under the mock PDK the conftest fixture installs.
_MINIMAL_DESIGN = {
    "DESIGN_NAME": "WHATEVER",
    "VERILOG_FILES": ["/cwd/src/a.v"],
}
_MOCK_PDK = {
    "design_dir": "/cwd",
    "pdk": "dummy",
    "scl": "dummy_scl",
    "pdk_root": "/pdk",
}


@pytest.fixture
def SmallStaged():
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage
    from librelane.steps import OpenROAD

    class SmallStaged(StagedFlow):
        Stages = [
            Stage.global_placement,
            OpenROAD.STAMidPNR,
            Stage.detailed_placement,
            Stage.cts,
        ]

        class Config(StagedFlow.Config):
            # The cts stage declares RUN_CTS as its gate, so any flow including
            # that stage has to declare the variable.
            RUN_CTS: bool = variable(True, description="test gate")

    return SmallStaged


def test_steps_are_populated_at_class_definition(SmallStaged):
    assert [step.id for step in SmallStaged.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.STAMidPNR",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_boundaries_exclude_plain_steps(SmallStaged):
    boundaries = SmallStaged.stage_boundaries(SmallStaged.Steps)

    assert [b.stage_ids for b in boundaries] == [
        ("global_placement",),
        ("detailed_placement",),
        ("cts",),
    ]
    assert [b.last_step_id for b in boundaries] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_substitute_still_works(SmallStaged):
    Substituted = SmallStaged.Substitute({"OpenROAD.CTS": None})

    assert "OpenROAD.CTS" not in [step.id for step in Substituted.Steps]
    assert [b.stage_ids for b in Substituted.stage_boundaries(Substituted.Steps)] == [
        ("global_placement",),
        ("detailed_placement",),
    ]


def test_duplicate_normalization_preserves_tags():
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Doubled(StagedFlow):
        Stages = [
            Stage.factory.get("global_placement"),
            Stage.factory.get("global_placement"),
        ]

    assert [step.id for step in Doubled.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    ]
    boundaries = Doubled.stage_boundaries(Doubled.Steps)
    assert len(boundaries) == 1
    assert boundaries[0].step_ids == (
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    )


def test_subclass_declaring_neither_stages_nor_steps_is_rejected():
    """
    StagedFlow.Steps defaults to [] so that defining StagedFlow itself does
    not trip SequentialFlow.__init_subclass__. Without this check that default
    would silently produce a flow that runs nothing.
    """
    from librelane.flows import StagedFlow

    with pytest.raises(TypeError, match="declares neither 'Stages' nor 'Steps'"):

        class Empty(StagedFlow):
            pass


def test_stage_gate_applies_to_every_step_of_the_stage():
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Gated(StagedFlow):
        Stages = [Stage.antenna_repair]

        class Config(StagedFlow.Config):
            RUN_ANTENNA_REPAIR: bool = variable(True, description="test gate")

    assert Gated.gating_config_vars == {
        "Odb.DiodesOnPorts": ["RUN_ANTENNA_REPAIR"],
        "Odb.HeuristicDiodeInsertion": ["RUN_ANTENNA_REPAIR"],
        "OpenROAD.RepairAntennas": ["RUN_ANTENNA_REPAIR"],
    }


def test_gating_key_matching_no_step_is_rejected():
    from librelane.config import variable
    from librelane.flows import SequentialFlow
    from librelane.steps import OpenROAD

    with pytest.raises(TypeError, match="matches no step"):

        class Bad(SequentialFlow):
            Steps = [OpenROAD.CTS]
            gating_config_vars = {"OpenROAD.NotAStep": ["RUN_CTS"]}

            class Config(SequentialFlow.Config):
                RUN_CTS: bool = variable(True, description="test gate")


def test_subclass_may_declare_steps_directly():
    from librelane.flows import StagedFlow
    from librelane.steps import OpenROAD

    class Bypassed(StagedFlow):
        Steps = [OpenROAD.STAMidPNR]

    assert [step.id for step in Bypassed.Steps] == ["OpenROAD.STAMidPNR"]
    assert Bypassed.stage_boundaries(Bypassed.Steps) == []


def _classic_with_tools(mock_config, tools):
    """
    Instantiates Classic from an already-resolved configuration, which skips
    Config.load. The mock variable set the fixtures install collides with real
    step variables (DIODE_ON_PORTS), so the real flow cannot be validated under
    them; the pre-pass that reads TOOLS out of raw sources is covered by
    test/stages/test_tools_extraction.py instead.
    """
    from librelane.flows import Flow

    return Flow.factory.get("Classic")(mock_config.copy(TOOLS=tools))


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_tools_reexpands_at_instance_time(mock_config):
    from librelane.flows import Flow

    flow = _classic_with_tools(mock_config, {"streamout": "klayout"})

    ids = [step.id for step in flow.Steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids
    assert [step.id for step in Flow.factory.get("Classic").Steps] != ids, (
        "class-level Steps must not be mutated"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_reexpansion_regenerates_gating_for_the_selected_provider(mock_config):
    flow = _classic_with_tools(mock_config, {"streamout": "klayout"})

    assert "Magic.StreamOut" not in flow.gating_config_vars
    assert flow.gating_config_vars["KLayout.StreamOut"] == ["RUN_KLAYOUT_STREAMOUT"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_default_run_does_not_reexpand(mock_config):
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = Classic(mock_config)

    assert [step.id for step in flow.Steps] == [step.id for step in Classic.Steps]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_gates_for_a_deselected_tool_are_dropped_not_rejected(mock_config):
    """
    Selecting one tool of a multi_provider stage removes the other's steps,
    leaving Classic's hand-written per-tool gates with nothing to name. That
    makes them moot, not wrong: rejecting them would make TOOLS unusable for
    exactly the stages it exists to serve.
    """
    flow = _classic_with_tools(mock_config, {"drc": "klayout"})

    assert "Magic.DRC" not in flow.gating_config_vars
    assert "Magic.DRC" not in [step.id for step in flow.Steps]
    assert flow.gating_config_vars["KLayout.DRC"] == ["RUN_KLAYOUT_DRC"]

    # Checker.MagicDRC is a plain step in Classic.Stages rather than part of the
    # drc stage, so deselecting magic leaves it running against a metric Magic
    # never emitted. Asserted so the gap is visible: closing it means moving the
    # per-tool checkers into their provider registrations, which reorders steps.
    assert "Checker.MagicDRC" in flow.gating_config_vars


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_unknown_provider_is_rejected_with_the_registered_names():
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    Classic = Flow.factory.get("Classic")
    with pytest.raises(StageResolutionError, match="no provider named 'genus'"):
        Classic({**_MINIMAL_DESIGN, "TOOLS": {"synthesis": "genus"}}, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_unknown_stage_key_is_rejected_with_a_suggestion():
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    Classic = Flow.factory.get("Classic")
    with pytest.raises(StageResolutionError, match="Did you mean: 'synthesis'"):
        Classic({**_MINIMAL_DESIGN, "TOOLS": {"synthesys": "yosys"}}, **_MOCK_PDK)
