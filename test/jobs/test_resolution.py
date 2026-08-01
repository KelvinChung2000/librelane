# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_defaults_expand_every_job():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    entries = [Job.factory.get("global_placement"), Job.factory.get("cts")]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.CTS",
    ]
    assert [span.provider for span in resolution.spans] == ["openroad", "openroad"]
    assert resolution.unselected == ()


def test_plain_steps_pass_through_untagged():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve
    from librelane.steps import OpenROAD

    entries = [Job.factory.get("cts"), OpenROAD.STAMidPNR]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.CTS",
        "OpenROAD.STAMidPNR",
    ]
    assert not hasattr(resolution.steps[1], "_job_span")
    assert len(resolution.spans) == 1


def test_unselected_optional_job_contributes_nothing():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    resolution = resolve([Job.factory.get("post_route_opt")], {})

    assert resolution.steps == []
    assert resolution.unselected == ("post_route_opt",)


def test_naming_a_provider_activates_an_unselected_job():
    from librelane.jobs import Job, JobResolutionError
    from librelane.jobs.resolution import resolve

    with pytest.raises(JobResolutionError, match="post_route_opt"):
        resolve(
            [Job.factory.get("post_route_opt")],
            {"post_route_opt": "nonexistent_tool"},
        )


def test_tools_override_selects_a_different_provider():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    resolution = resolve(
        [Job.factory.get("synthesis")],
        {"synthesis": "yosys_vhdl"},
    )

    assert [step.id for step in resolution.steps][0] == "Yosys.VHDLSynthesis"


def test_unknown_provider_lists_the_registered_ones():
    from librelane.jobs import Job, JobResolutionError
    from librelane.jobs.resolution import resolve

    with pytest.raises(JobResolutionError, match="yosys_vhdl"):
        resolve([Job.factory.get("synthesis")], {"synthesis": "genus"})


def test_unknown_job_key_suggests_a_correction():
    from librelane.jobs import Job, JobResolutionError
    from librelane.jobs.resolution import resolve

    with pytest.raises(JobResolutionError, match="Did you mean: 'synthesis'"):
        resolve([Job.factory.get("synthesis")], {"synthsis": "yosys"})


def test_list_value_on_single_provider_job_is_rejected():
    from librelane.jobs import Job, JobResolutionError
    from librelane.jobs.resolution import resolve

    with pytest.raises(JobResolutionError, match="does not accept a list"):
        resolve([Job.factory.get("cts")], {"cts": ["openroad", "openroad"]})


def test_multi_provider_job_concatenates_in_listed_order():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    resolution = resolve(
        [Job.factory.get("streamout")],
        {"streamout": ["klayout", "magic"]},
    )

    assert [step.id for step in resolution.steps] == [
        "KLayout.StreamOut",
        "KLayout.Render",
        "Magic.StreamOut",
    ]


def test_multi_provider_job_accepts_a_single_provider():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    resolution = resolve([Job.factory.get("drc")], {"drc": "klayout"})

    # The provider owns the checker that reads its metric, so selecting one tool
    # of the job brings its checker and leaves the other tool's behind.
    assert [step.id for step in resolution.steps] == [
        "KLayout.DRC",
        "Checker.KLayoutDRC",
    ]
    # A metric a registration declares is that provider's own obligation, not
    # the job's, so it hangs off the provider's contract. The distinction is
    # load-bearing on a multi_provider job: the job's own metrics are
    # satisfied by its providers jointly, while each provider answers for its
    # own even when the other tool is gated off.
    assert resolution.spans[0].metrics == ()
    assert [contract.provider for contract in resolution.spans[0].providers] == [
        "klayout"
    ]
    assert resolution.spans[0].providers[0].metrics == ("klayout__drc_error__count",)


def test_using_pins_a_provider_without_registering_a_new_job():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    pinned = Job.factory.get("synthesis").using("yosys_vhdl")

    assert pinned.id == "synthesis"
    assert pinned.default_providers == ("yosys_vhdl",)
    assert [step.id for step in resolve([pinned], {}).steps] == [
        "Yosys.VHDLSynthesis",
        "Checker.YosysUnmappedCells",
        "Checker.YosysSynthChecks",
        "Checker.NetlistAssignStatements",
    ]
    # The registered job is untouched: 'using' returns a copy, so pinning a
    # provider in one flow's Stages list cannot leak into another's.
    assert Job.factory.get("synthesis").default_providers == ("yosys",)


def test_tools_overrides_a_pinned_provider():
    """
    Resolution consults TOOLS before default_provider, so a pin is a default
    rather than a lock and needs no override logic of its own.
    """
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    pinned = Job.factory.get("synthesis").using("yosys_vhdl")
    resolution = resolve([pinned], {"synthesis": "yosys"})

    assert [step.id for step in resolution.steps][0] == "Yosys.JsonHeader"


def test_using_a_list_on_a_multi_provider_job_pins_both():
    from librelane.jobs import Job
    from librelane.jobs.resolution import resolve

    pinned = Job.factory.get("streamout").using(["klayout", "magic"])

    assert [step.id for step in resolve([pinned], {}).steps] == [
        "KLayout.StreamOut",
        "KLayout.Render",
        "Magic.StreamOut",
    ]


def test_using_a_list_on_a_single_provider_job_is_rejected():
    from librelane.jobs import Job, JobDefinitionError

    with pytest.raises(JobDefinitionError, match="does not accept a list of providers"):
        Job.factory.get("cts").using(["openroad", "openroad"])


def test_using_an_empty_list_is_rejected():
    """
    An empty pin would resolve to no providers, which for a non-optional job
    silently drops it from the flow.
    """
    from librelane.jobs import Job, JobDefinitionError

    with pytest.raises(JobDefinitionError, match="empty provider list"):
        Job.factory.get("streamout").using([])
