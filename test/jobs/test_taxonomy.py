# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_job_in_order_is_registered():
    from librelane.jobs import Job
    from librelane.jobs.taxonomy import JOB_ORDER

    for job_id in JOB_ORDER:
        assert Job.factory.get(job_id) is not None, job_id


def test_taxonomy_has_twenty_seven_jobs():
    from librelane.jobs.taxonomy import JOB_ORDER

    assert len(JOB_ORDER) == 27
    assert len(set(JOB_ORDER)) == 27


def test_only_post_route_opt_is_unselected():
    from librelane.jobs import Job
    from librelane.jobs.taxonomy import JOB_ORDER

    unselected = [
        job_id
        for job_id in JOB_ORDER
        if Job.factory.get(job_id).default_provider is None
    ]
    assert unselected == ["post_route_opt"]


def test_the_two_templates_with_two_providers_agree_with_pdk_compat():
    """
    ``streamout`` and ``drc`` are the two phases every shipped document runs
    under both Magic and KLayout, as two jobs pinning a provider each. Nothing
    shipped reaches the default, so this is what a *new* document taking one of
    these templates bare would get, and it has to agree with the tool
    ``pdk_compat`` fills ``PRIMARY_GDSII_STREAMOUT_TOOL`` with -- otherwise a
    lone ``uses: streamout`` would stream out with a tool the PDK does not
    consider primary. Both sides are exercised here so they fail together
    rather than drifting apart (today, that tool is "magic").
    """
    from librelane.config.pdk_compat import migrate_old_config
    from librelane.jobs import Job

    minimal_sky130_config = {
        "PDK_ROOT": "/pdk_root",
        "PDK": "sky130A",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
        "LIB": "/pdk_root/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
    }
    primary_streamout_tool = migrate_old_config(minimal_sky130_config)[
        "PRIMARY_GDSII_STREAMOUT_TOOL"
    ]

    assert Job.factory.get("streamout").default_provider == primary_streamout_tool
    assert Job.factory.get("drc").default_provider == primary_streamout_tool
