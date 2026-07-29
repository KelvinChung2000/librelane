# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_defaults_expand_every_stage():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    entries = [Stage.factory.get("global_placement"), Stage.factory.get("cts")]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.CTS",
    ]
    assert [span.provider for span in resolution.spans] == ["openroad", "openroad"]
    assert resolution.unselected == ()


def test_plain_steps_pass_through_untagged():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve
    from librelane.steps import OpenROAD

    entries = [Stage.factory.get("cts"), OpenROAD.STAMidPNR]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.CTS",
        "OpenROAD.STAMidPNR",
    ]
    assert not hasattr(resolution.steps[1], "_stage_span")
    assert len(resolution.spans) == 1


def test_unselected_optional_stage_contributes_nothing():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve([Stage.factory.get("post_route_opt")], {})

    assert resolution.steps == []
    assert resolution.unselected == ("post_route_opt",)


def test_naming_a_provider_activates_an_unselected_stage():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="post_route_opt"):
        resolve(
            [Stage.factory.get("post_route_opt")],
            {"post_route_opt": "nonexistent_tool"},
        )


def test_tools_override_selects_a_different_provider():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve(
        [Stage.factory.get("synthesis")],
        {"synthesis": "yosys_vhdl"},
    )

    assert [step.id for step in resolution.steps][0] == "Yosys.VHDLSynthesis"


def test_unknown_provider_lists_the_registered_ones():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="yosys_vhdl"):
        resolve([Stage.factory.get("synthesis")], {"synthesis": "genus"})


def test_unknown_stage_key_suggests_a_correction():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="Did you mean: 'synthesis'"):
        resolve([Stage.factory.get("synthesis")], {"synthsis": "yosys"})


def test_list_value_on_single_provider_stage_is_rejected():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="does not accept a list"):
        resolve([Stage.factory.get("cts")], {"cts": ["openroad", "openroad"]})


def test_multi_provider_stage_concatenates_in_listed_order():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve(
        [Stage.factory.get("streamout")],
        {"streamout": ["klayout", "magic"]},
    )

    assert [step.id for step in resolution.steps] == [
        "KLayout.StreamOut",
        "KLayout.Render",
        "Magic.StreamOut",
    ]


def test_multi_provider_stage_accepts_a_single_provider():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve([Stage.factory.get("drc")], {"drc": "klayout"})

    # The provider owns the checker that reads its metric, so selecting one tool
    # of the stage brings its checker and leaves the other tool's behind.
    assert [step.id for step in resolution.steps] == [
        "KLayout.DRC",
        "Checker.KLayoutDRC",
    ]
    assert resolution.spans[0].metrics == ("klayout__drc_error__count",)


def test_using_pins_a_provider_without_registering_a_new_stage():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    pinned = Stage.factory.get("synthesis").using("yosys_vhdl")

    assert pinned.id == "synthesis"
    assert pinned.default_providers == ("yosys_vhdl",)
    assert [step.id for step in resolve([pinned], {}).steps] == [
        "Yosys.VHDLSynthesis",
        "Checker.YosysUnmappedCells",
        "Checker.YosysSynthChecks",
        "Checker.NetlistAssignStatements",
    ]
    # The registered stage is untouched: 'using' returns a copy, so pinning a
    # provider in one flow's Stages list cannot leak into another's.
    assert Stage.factory.get("synthesis").default_providers == ("yosys",)


def test_tools_overrides_a_pinned_provider():
    """
    Resolution consults TOOLS before default_provider, so a pin is a default
    rather than a lock and needs no override logic of its own.
    """
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    pinned = Stage.factory.get("synthesis").using("yosys_vhdl")
    resolution = resolve([pinned], {"synthesis": "yosys"})

    assert [step.id for step in resolution.steps][0] == "Yosys.JsonHeader"


def test_using_a_list_on_a_multi_provider_stage_pins_both():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    pinned = Stage.factory.get("streamout").using(["klayout", "magic"])

    assert [step.id for step in resolve([pinned], {}).steps] == [
        "KLayout.StreamOut",
        "KLayout.Render",
        "Magic.StreamOut",
    ]


def test_using_a_list_on_a_single_provider_stage_is_rejected():
    from librelane.stages import Stage, StageError

    with pytest.raises(StageError, match="does not accept a list of providers"):
        Stage.factory.get("cts").using(["openroad", "openroad"])


def test_using_an_empty_list_is_rejected():
    """
    An empty pin would resolve to no providers, which for a non-optional stage
    silently drops it from the flow.
    """
    from librelane.stages import Stage, StageError

    with pytest.raises(StageError, match="empty provider list"):
        Stage.factory.get("streamout").using([])
