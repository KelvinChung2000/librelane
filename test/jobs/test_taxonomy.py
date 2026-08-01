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


def test_optional_jobs_only_feed_other_optional_jobs():
    """
    An optional job may be skipped. If a *mandatory* later job required
    something only that optional job provides, the flow would be
    unconditionally broken whenever the gate were turned off, and no
    configuration could rescue it.

    An optional consumer is a different matter: the combination is legal as
    long as both gates agree, and the static view availability preflight
    rejects the disagreeing case by name before the run starts. `extraction`
    (RUN_SPEF_EXTRACTION) feeding `signoff_sta` (RUN_MCSTA) and `ir_drop`
    (RUN_IRDROP_REPORT) is exactly that case.
    """
    from librelane.jobs import Job
    from librelane.jobs.taxonomy import JOB_ORDER

    for index, job_id in enumerate(JOB_ORDER):
        job = Job.factory.get(job_id)
        if not job.optional:
            continue
        mandatory_later_requirements = set()
        for later_id in JOB_ORDER[index + 1 :]:
            later = Job.factory.get(later_id)
            if later.optional:
                continue
            mandatory_later_requirements.update(later.requires)
        exclusive = set(job.provides) - {
            view
            for earlier_id in JOB_ORDER[:index]
            for view in Job.factory.get(earlier_id).provides
        }
        assert not (exclusive & mandatory_later_requirements), job_id


def test_extraction_only_feeds_optional_consumers():
    """
    Pins the one case the invariant above deliberately permits, so that
    turning `signoff_sta` or `ir_drop` into a mandatory job fails loudly
    here rather than at some user's runtime.
    """
    from librelane.jobs import Job
    from librelane.state import DesignFormat

    assert Job.factory.get("extraction").optional
    assert DesignFormat.spef in Job.factory.get("extraction").provides
    for consumer in ("signoff_sta", "ir_drop"):
        job = Job.factory.get(consumer)
        assert DesignFormat.spef in job.requires, consumer
        assert job.optional, consumer


def test_gating_variables_are_unique():
    from librelane.jobs import Job
    from librelane.jobs.taxonomy import JOB_ORDER

    gates = [
        Job.factory.get(job_id).gating_config_var
        for job_id in JOB_ORDER
        if Job.factory.get(job_id).gating_config_var is not None
    ]
    assert len(gates) == len(set(gates))
    assert len(gates) == 15


def test_multi_provider_jobs():
    from librelane.jobs import Job
    from librelane.jobs.taxonomy import JOB_ORDER

    multi = [job_id for job_id in JOB_ORDER if Job.factory.get(job_id).multi_provider]
    assert multi == ["streamout", "drc"]
