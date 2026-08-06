# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_selectable_job_has_its_default_provider_registered():
    from librelane.jobs import Job, JobRegistry
    from librelane.jobs.taxonomy import JOB_ORDER

    for job_id in JOB_ORDER:
        job = Job.factory.get(job_id)
        if job.default_provider is None:
            continue
        assert JobRegistry.get(job_id, job.default_provider) is not None, (
            f"{job_id}: default provider '{job.default_provider}' is not registered"
        )


def test_post_route_opt_has_no_provider():
    from librelane.jobs import JobRegistry

    assert JobRegistry.providers("post_route_opt") == []


def test_streamout_and_drc_each_have_two_providers():
    """
    Both are registered for both phases, which is what lets a document declare
    two jobs against one template and run both tools.
    """
    from librelane.jobs import JobRegistry

    assert sorted(JobRegistry.providers("streamout")) == ["klayout", "magic"]
    assert sorted(JobRegistry.providers("drc")) == ["klayout", "magic"]


def test_synthesis_has_two_providers():
    from librelane.jobs import JobRegistry

    assert sorted(JobRegistry.providers("synthesis")) == ["yosys", "yosys_vhdl"]


def test_lvs_offers_klayout_as_an_alternative_to_netgen():
    """
    Every shipped document declares ``lvs`` once, so its two providers are
    alternatives and exactly one runs. That is what lets both write the job's
    contracted ``design__lvs_error__count`` without either overwriting the
    other, the same licence ``Pegasus.LVS`` takes.

    The klayout sequence carries ``OpenROAD.WriteCDL`` for the same reason the
    netgen sequence carries ``Magic.SpiceExtraction``: the comparison needs a
    schematic-side netlist in the tool's own idiom, and no job promises one.
    ``lvs.requires`` is unchanged by this, so a flow that never selects klayout
    is not made to write a CDL it has no use for.
    """
    from librelane.jobs import JobRegistry
    from librelane.steps import KLayout, OpenROAD

    assert sorted(JobRegistry.providers("lvs")) == ["klayout", "netgen"]
    assert JobRegistry.get("lvs", "klayout").steps == (
        OpenROAD.WriteCDL,
        KLayout.LVS,
    )


def test_yosys_vhdl_does_not_provide_the_json_header():
    """
    Odb.SetPowerConnections and Odb.WriteVerilogHeader both take json_h as a
    hard input (librelane/steps/odb/power.py:49 and :74). Yosys.JsonHeader is a
    VerilogStep and cannot run on VHDL sources. This asymmetry is what Task 12
    turns into a precise error rather than a runtime surprise.
    """
    from librelane.jobs import JobRegistry
    from librelane.state import DesignFormat

    assert DesignFormat.json_h in JobRegistry.get("synthesis", "yosys").provides
    assert (
        DesignFormat.json_h not in JobRegistry.get("synthesis", "yosys_vhdl").provides
    )


def test_each_drc_provider_carries_the_limit_on_its_own_metric():
    """
    A DRC provider is one step now, because the limit on the count travels
    with the tool that measured it rather than following behind as a separate
    ``Checker.*``. That used to be a real orphan: deselecting magic removed
    Magic.DRC and left Checker.MagicDRC demanding a magic__drc_error__count
    nothing emitted, which the view preflight could not catch because a
    checker declared no inputs. A gate cannot be orphaned -- there is nowhere
    for it to be, other than on the step.
    """
    from librelane.jobs import JobRegistry
    from librelane.steps import KLayout, Magic

    assert JobRegistry.get("drc", "magic").steps == (Magic.DRC,)
    assert JobRegistry.get("drc", "klayout").steps == (KLayout.DRC,)

    assert [gate.metric for gate in Magic.DRC.gates] == ["magic__drc_error__count"]
    assert [gate.metric for gate in KLayout.DRC.gates] == ["klayout__drc_error__count"]


def test_a_tool_specific_metric_is_limited_inside_its_own_registration():
    """
    The mechanical form of the step-ownership invariant, on the metric side.

    A metric a registration declares that its jobs do not is by definition
    tool-specific: only that provider emits it. Whatever fails the run on it
    therefore only makes sense when that provider was selected, so it has to
    live in the same registration, where deselecting the tool removes both
    together.

    Since the limit is a gate on the measuring step, this now reads as "the
    step that emits it also limits it", and a vendor provider added later is
    held to it for free.
    """
    from librelane.jobs import Job
    from librelane.jobs.providers import _REGISTRATIONS
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
    # librelane.jobs.providers_vendor, whose import registers every
    # commercial provider as a side effect and would defeat the opt-in
    # boundary test/jobs/test_providers_vendor.py pins.
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
        contracted_by_job = set(Job.factory.get(entry["job"]).metrics)
        tool_specific = set(entry.get("metrics", ())) - contracted_by_job
        gated = {gate.metric for step in entry["steps"] for gate in step.gates}
        assert tool_specific <= gated, (
            f"{entry['job']}:{entry['provider']} declares "
            f"{sorted(tool_specific - gated)}, which no step in the sequence "
            f"limits. A limit placed anywhere else in a flow would outlive the "
            f"tool it applies to."
        )


def test_declared_native_views_are_exactly_the_hard_unmet_inputs():
    """
    native_views is an exemption from the registration-time view check, so an
    over-broad declaration silently weakens the contract. Pin it to precisely
    the views each sequence hard-requires and no job supplies.
    """
    from librelane.jobs import Job
    from librelane.jobs.providers import _REGISTRATIONS
    from librelane.steps.step.composition import compose_step_sequence

    for entry in _REGISTRATIONS:
        union = compose_step_sequence(entry["steps"])
        supplied = set(Job.factory.get(entry["job"]).requires)
        needed = {
            view.id
            for view in union.unmet_inputs
            if not view.optional and view not in supplied
        }
        declared = {view.id for view in entry.get("native_views", ())}
        assert needed == declared, f"{entry['job']}:{entry['provider']}"


def test_openroad_carries_odb_across_pnr_boundaries():
    from librelane.jobs import JobRegistry
    from librelane.state import DesignFormat

    assert JobRegistry.get("global_placement", "openroad").native_views == (
        DesignFormat.odb,
    )
    # pre_pnr_sta runs before any odb exists, so it must not claim one.
    assert JobRegistry.get("pre_pnr_sta", "openroad").native_views == ()


def test_the_odb_editing_steps_belong_to_the_job_whose_odb_they_edit():
    """
    Each of these three edits an odb, OpenROAD's native database, so none of
    them means anything unless its job resolved to OpenROAD. Every shipped
    document ran each one immediately beside the job it is registered with, so
    membership costs no document its ordering and buys the ownership rule: point
    the job at another tool and the step goes with it, rather than being left
    behind demanding an odb nothing produced.
    """
    from librelane.jobs import JobRegistry
    from librelane.steps import Odb, OpenROAD

    assert JobRegistry.get("macro_placement", "openroad").steps == (
        Odb.ManualMacroPlacement,
        OpenROAD.RTLMacroPlacer,
        OpenROAD.CutRows,
    )
    assert JobRegistry.get("power_grid", "openroad").steps == (
        Odb.AddPDNObstructions,
        OpenROAD.GeneratePDN,
        Odb.RemovePDNObstructions,
        Odb.AddRoutingObstructions,
    )
    assert JobRegistry.get("detailed_placement", "openroad").steps == (
        Odb.ManualGlobalPlacement,
        OpenROAD.DetailedPlacement,
    )


def test_add_buffer_is_not_a_member_of_the_global_placement_provider():
    """
    The counter-case, and the reason consuming an odb is not on its own enough
    to make a step a provider's.

    OpenROAD.AddBuffer edits an odb like the three above, but chip.yaml runs
    global placement and deliberately does not run it: a chip's ports are the
    pad ring's bumps, which the pad cells have already buffered. A step two
    documents want and a third refuses is the document's choice, so it stays a
    job the document lists. Fold it in here and Chip silently starts buffering
    its bumps.
    """
    from librelane.jobs import JobRegistry
    from librelane.steps import OpenROAD

    assert (
        OpenROAD.AddBuffer not in JobRegistry.get("global_placement", "openroad").steps
    )


def test_the_klayout_drc_metric_is_optional_not_contracted():
    """
    KLayout.DRC skips itself on PDKs that ship no KLAYOUT_DRC_RUNSET, so its
    metric cannot be a completion-time obligation: a stock gf180mcu run died
    with a job-contract error at klayout_drc. It stays declared as optional so
    join validation still sees that both DRC providers write the same name.
    """
    from librelane.jobs import JobRegistry

    registration = JobRegistry.get("drc", "klayout")

    assert registration.metrics == ()
    assert registration.optional_metrics == ("klayout__drc_error__count",)


def test_an_optional_metric_is_exempt_from_the_completion_contract():
    """
    The two halves of ``optional_metrics``, against the real engine code: the
    completion-time contract check accepts a state without the metric, and
    join validation still counts it as a write.
    """
    from dataclasses import replace

    from librelane.flows.engine import Workflow
    from librelane.flows.job import ResolvedJob
    from librelane.flows.selection_validation import produced_keys
    from librelane.state import State

    job = ResolvedJob(
        id="klayout_drc",
        needs=(),
        source={},
        conditions=(),
        requires=(),
        provides=(),
        metrics=(),
        optional_metrics=("klayout__drc_error__count",),
        steps=(),
        provider="klayout",
        native_views=(),
        until_terms=(),
        iterations=({},),
        max_passes=None,
        select=None,
        resources=(),
    )

    # Skipped step, empty state: must not raise.
    Workflow._check_contract(None, job, State())

    # A required metric on the same job still is an obligation.
    required = replace(job, metrics=("klayout__drc_error__count",))
    from librelane.flows.engine import JobContractError

    try:
        Workflow._check_contract(None, required, State())
    except JobContractError:
        pass
    else:
        raise AssertionError("a required metric's absence must raise")

    # Join validation counts the optional metric as a write either way.
    keys = produced_keys({"klayout_drc": job}, {"klayout_drc"})
    assert "klayout__drc_error__count" in keys["klayout_drc"]
