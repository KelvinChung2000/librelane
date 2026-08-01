# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


# Module-scoped: Job.factory is a process-wide singleton, so registering the
# same id once per test would raise on the second use.
@pytest.fixture(scope="module")
def alpha_job():
    from librelane.jobs import Job
    from librelane.state import DesignFormat

    return Job(
        id="registry_alpha",
        full_name="Registry Alpha",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
    ).register()


def test_registration_is_retrievable(alpha_job, mock_steps):
    from librelane.jobs import JobRegistry

    MockPlace, _ = mock_steps
    registration = JobRegistry.register(
        job="registry_alpha",
        provider="mock",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert JobRegistry.get("registry_alpha", "mock") is registration
    assert JobRegistry.providers("registry_alpha") == ["mock"]
    assert registration.job == "registry_alpha"


def test_unknown_job_id_raises(mock_steps):
    from librelane.jobs import JobDefinitionError, JobRegistry

    MockPlace, _ = mock_steps
    with pytest.raises(JobDefinitionError, match="no job with id 'not_a_job'"):
        JobRegistry.register(
            job="not_a_job",
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_duplicate_provider_for_job_raises(alpha_job, mock_steps):
    from librelane.jobs import JobDefinitionError, JobRegistry

    MockPlace, MockRoute = mock_steps
    JobRegistry.register(
        job="registry_alpha",
        provider="dup",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )
    with pytest.raises(JobDefinitionError, match="already registered"):
        JobRegistry.register(
            job="registry_alpha",
            provider="dup",
            steps=[MockRoute],
            namespaces=["MOCK_"],
        )


def test_unnamespaced_variable_raises(alpha_job):
    from librelane.config import variable
    from librelane.jobs import JobDefinitionError, JobRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class Rogue(Step):
        id = "Test.MockRogue"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        class Config(Step.Config):
            WIDGET_COUNT: int = variable(3, description="desc")

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(JobDefinitionError, match="WIDGET_COUNT"):
        JobRegistry.register(
            job="registry_alpha",
            provider="rogue",
            steps=[Rogue],
            namespaces=["MOCK_"],
        )


def test_unmet_input_outside_requires_raises(alpha_job):
    from librelane.jobs import JobDefinitionError, JobRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsGDS(Step):
        id = "Test.MockNeedsGDS"
        inputs = [DesignFormat.gds]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(JobDefinitionError, match="consumes view 'gds'"):
        JobRegistry.register(
            job="registry_alpha",
            provider="needsgds",
            steps=[NeedsGDS],
            namespaces=["MOCK_"],
        )


def test_native_view_exempts_an_unmet_input(alpha_job):
    from librelane.jobs import JobRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsODB(Step):
        id = "Test.MockNeedsODB"
        inputs = [DesignFormat.odb]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    registration = JobRegistry.register(
        job="registry_alpha",
        provider="needsodb",
        steps=[NeedsODB],
        namespaces=["MOCK_"],
        native_views=[DesignFormat.odb],
    )
    assert registration.native_views == (DesignFormat.odb,)


def test_unprovided_view_raises(mock_steps):
    from librelane.jobs import Job, JobDefinitionError, JobRegistry
    from librelane.state import DesignFormat

    Job(
        id="registry_provides_gds",
        full_name="Registry Provides GDS",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.gds,),
    ).register()

    MockPlace, _ = mock_steps
    with pytest.raises(JobDefinitionError, match="never produces view 'gds'"):
        JobRegistry.register(
            job="registry_provides_gds",
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_registration_names_exactly_one_job(alpha_job, mock_steps):
    """
    The registry used to accept a jobs tuple the resolver rejected outright.
    A shape no consumer accepts is not a feature.
    """
    from librelane.jobs import Registration, JobRegistry

    MockPlace, _ = mock_steps
    registration = JobRegistry.register(
        job="registry_alpha",
        provider="single",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert registration.job == "registry_alpha"
    assert not hasattr(registration, "jobs")
    assert not hasattr(registration, "spanning")
    assert not hasattr(Registration, "spanning")
