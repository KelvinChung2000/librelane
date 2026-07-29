# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_selectable_stage_has_its_default_provider_registered():
    from librelane.stages import Stage, StageRegistry
    from librelane.stages.taxonomy import STAGE_ORDER

    for stage_id in STAGE_ORDER:
        stage = Stage.factory.get(stage_id)
        for provider in stage.default_providers:
            assert StageRegistry.get(stage_id, provider) is not None, (
                f"{stage_id}: default provider '{provider}' is not registered"
            )


def test_post_route_opt_has_no_provider():
    from librelane.stages import StageRegistry

    assert StageRegistry.providers("post_route_opt") == []


def test_multi_provider_stages_have_two_providers():
    from librelane.stages import StageRegistry

    assert sorted(StageRegistry.providers("streamout")) == ["klayout", "magic"]
    assert sorted(StageRegistry.providers("drc")) == ["klayout", "magic"]


def test_synthesis_has_two_providers():
    from librelane.stages import StageRegistry

    assert sorted(StageRegistry.providers("synthesis")) == ["yosys", "yosys_vhdl"]


def test_yosys_vhdl_does_not_provide_the_json_header():
    """
    Odb.SetPowerConnections and Odb.WriteVerilogHeader both take json_h as a
    hard input (librelane/steps/odb/power.py:49 and :74). Yosys.JsonHeader is a
    VerilogStep and cannot run on VHDL sources. This asymmetry is what Task 12
    turns into a precise error rather than a runtime surprise.
    """
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat

    assert DesignFormat.json_h in StageRegistry.get("synthesis", "yosys").provides
    assert (
        DesignFormat.json_h not in StageRegistry.get("synthesis", "yosys_vhdl").provides
    )


def test_declared_native_views_are_exactly_the_hard_unmet_inputs():
    """
    native_views is an exemption from the registration-time view check, so an
    over-broad declaration silently weakens the contract. Pin it to precisely
    the views each sequence hard-requires and no stage supplies.
    """
    from librelane.stages import Stage
    from librelane.stages.providers import _REGISTRATIONS
    from librelane.steps.step.composition import compose_step_sequence

    for entry in _REGISTRATIONS:
        union = compose_step_sequence(entry["steps"])
        supplied = {
            view
            for stage_id in entry["stages"]
            for view in Stage.factory.get(stage_id).requires
        }
        needed = {
            view.id
            for view in union.unmet_inputs
            if not view.optional and view not in supplied
        }
        declared = {view.id for view in entry.get("native_views", ())}
        assert needed == declared, f"{entry['stages']}:{entry['provider']}"


def test_openroad_carries_odb_across_pnr_boundaries():
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat

    assert StageRegistry.get("global_placement", "openroad").native_views == (
        DesignFormat.odb,
    )
    # pre_pnr_sta runs before any odb exists, so it must not claim one.
    assert StageRegistry.get("pre_pnr_sta", "openroad").native_views == ()
