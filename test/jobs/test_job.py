# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_job_registers_and_is_retrievable():
    from librelane.jobs import Job
    from librelane.state import DesignFormat

    job = Job(
        id="test_job_alpha",
        full_name="Test Job Alpha",
        default_provider="mock",
        requires=(DesignFormat.nl,),
        provides=(DesignFormat.def_,),
    ).register()

    assert Job.factory.get("test_job_alpha") is job
    assert Job.test_job_alpha is job
    assert "test_job_alpha" in Job.factory.list()


def test_unknown_job_attribute_raises():
    from librelane.jobs import Job

    with pytest.raises(AttributeError):
        Job.no_such_job_exists


def test_duplicate_registration_raises():
    from librelane.jobs import Job, JobDefinitionError
    from librelane.state import DesignFormat

    def make():
        return Job(
            id="test_job_duplicate",
            full_name="Test Job Duplicate",
            default_provider="mock",
            requires=(DesignFormat.nl,),
            provides=(DesignFormat.nl,),
        )

    make().register()
    with pytest.raises(JobDefinitionError, match="already registered"):
        make().register()


def test_a_job_may_register_with_no_default_provider():
    """
    A phase the taxonomy names but no provider package implements yet, which
    is what ``post_route_opt`` is. Registration does not refuse it: a document
    that tries to declare such a job is what gets refused, at load time, by
    ``_check_uses``.
    """
    from librelane.jobs import Job
    from librelane.state import DesignFormat

    job = Job(
        id="test_job_unimplemented",
        full_name="Test Job Unimplemented",
        default_provider=None,
        requires=(DesignFormat.def_,),
        provides=(DesignFormat.def_,),
    ).register()

    assert Job.factory.get("test_job_unimplemented") is job
