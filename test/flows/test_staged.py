# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


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
