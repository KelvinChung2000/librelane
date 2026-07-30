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


def test_each_drc_provider_owns_its_own_checker():
    """
    A checker that reads one tool's metric only makes sense when that tool was
    selected, so it belongs inside that tool's registration. Left as a plain step
    in the flow, deselecting magic used to leave Checker.MagicDRC demanding
    magic__drc_error__count that nothing emitted. The view preflight cannot catch
    that class of orphan, because a checker declares no inputs, so ownership is
    the only fix.
    """
    from librelane.stages import StageRegistry
    from librelane.steps import Checker, KLayout, Magic

    assert StageRegistry.get("drc", "magic").steps == (Magic.DRC, Checker.MagicDRC)
    assert StageRegistry.get("drc", "klayout").steps == (
        KLayout.DRC,
        Checker.KLayoutDRC,
    )


def test_a_tool_specific_metric_is_checked_inside_its_own_registration():
    """
    The mechanical form of the step-ownership invariant, on the metric side.

    A metric a registration declares that its stages do not is by definition
    tool-specific: only that provider emits it. The step that fails the run on it
    therefore only makes sense when that provider was selected, so it has to live
    in the same registration, where deselecting the tool removes them together.

    This is the check that condemned Checker.MagicDRC and Checker.KLayoutDRC as
    plain steps of the flow, and the one a vendor provider added later is held to
    for free. Note what it does *not* condemn: a checker for a metric the stage
    contracts, such as Checker.TrDRC, is tool-neutral and belongs inside a
    registration for a different reason -- membership is what gives it the
    stage's gating variable.
    """
    from librelane.stages import Stage
    from librelane.stages.providers import _REGISTRATIONS
    from librelane.steps import (
        calibre,
        conformal,
        dc,
        fc,
        fm,
        genus,
        icc2,
        icv,
        innovus,
        pegasus,
        pt,
        quantus,
        starrc,
        tempus,
        vc_spyglass,
        voltus,
    )

    # Read each vendor module's data directly rather than importing
    # librelane.stages.providers_vendor, whose import registers every
    # commercial provider as a side effect and would defeat the opt-in
    # boundary test/stages/test_providers_vendor.py pins.
    vendor_registrations = [
        entry
        for module in (
            calibre,
            conformal,
            dc,
            fc,
            fm,
            genus,
            icc2,
            icv,
            innovus,
            pegasus,
            pt,
            quantus,
            starrc,
            tempus,
            vc_spyglass,
            voltus,
        )
        for entry in module.REGISTRATIONS
    ]

    for entry in _REGISTRATIONS + vendor_registrations:
        contracted_by_stage = set(Stage.factory.get(entry["stage"]).metrics)
        tool_specific = set(entry.get("metrics", ())) - contracted_by_stage
        checked = {
            metric
            for step in entry["steps"]
            if (metric := getattr(step, "metric_name", None)) is not None
        }
        assert tool_specific <= checked, (
            f"{entry['stage']}:{entry['provider']} declares "
            f"{sorted(tool_specific - checked)}, which nothing in the sequence "
            f"checks. A checker for it elsewhere in a flow would outlive the "
            f"tool it checks."
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
        supplied = set(Stage.factory.get(entry["stage"]).requires)
        needed = {
            view.id
            for view in union.unmet_inputs
            if not view.optional and view not in supplied
        }
        declared = {view.id for view in entry.get("native_views", ())}
        assert needed == declared, f"{entry['stage']}:{entry['provider']}"


def test_openroad_carries_odb_across_pnr_boundaries():
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat

    assert StageRegistry.get("global_placement", "openroad").native_views == (
        DesignFormat.odb,
    )
    # pre_pnr_sta runs before any odb exists, so it must not claim one.
    assert StageRegistry.get("pre_pnr_sta", "openroad").native_views == ()
