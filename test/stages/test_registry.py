# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


# Module-scoped: Stage.factory is a process-wide singleton, so registering the
# same id once per test would raise on the second use.
@pytest.fixture(scope="module")
def alpha_stage():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    return Stage(
        id="registry_alpha",
        full_name="Registry Alpha",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
    ).register()


@pytest.fixture(scope="module")
def beta_stage():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    return Stage(
        id="registry_beta",
        full_name="Registry Beta",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
    ).register()


def test_registration_is_retrievable(alpha_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="mock",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert StageRegistry.get("registry_alpha", "mock") is registration
    assert StageRegistry.providers("registry_alpha") == ["mock"]
    assert registration.spanning is False


def test_spanning_registration_covers_every_stage(alpha_stage, beta_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha", "registry_beta"],
        provider="mock_span",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert registration.spanning is True
    assert StageRegistry.get("registry_alpha", "mock_span") is registration
    assert StageRegistry.get("registry_beta", "mock_span") is registration


def test_unknown_stage_id_raises(mock_steps):
    from librelane.stages import StageError, StageRegistry

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="no stage with id 'not_a_stage'"):
        StageRegistry.register(
            stages=["not_a_stage"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_duplicate_provider_for_stage_raises(alpha_stage, mock_steps):
    from librelane.stages import StageError, StageRegistry

    MockPlace, MockRoute = mock_steps
    StageRegistry.register(
        stages=["registry_alpha"],
        provider="dup",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )
    with pytest.raises(StageError, match="already registered"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="dup",
            steps=[MockRoute],
            namespaces=["MOCK_"],
        )


def test_missing_canonical_variable_raises(mock_steps):
    from librelane.config import Variable
    from librelane.stages import Stage, StageError, StageRegistry
    from librelane.state import DesignFormat

    Stage(
        id="registry_canonical",
        full_name="Registry Canonical",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        config_vars=(Variable("TARGET_DENSITY_PCT", float, "desc", default=50.0),),
    ).register()

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="does not declare canonical variable"):
        StageRegistry.register(
            stages=["registry_canonical"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_unnamespaced_variable_raises(alpha_stage):
    from librelane.config import Variable
    from librelane.stages import StageError, StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class Rogue(Step):
        id = "Test.MockRogue"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        config_vars = [Variable("WIDGET_COUNT", int, "desc", default=3)]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(StageError, match="WIDGET_COUNT"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="rogue",
            steps=[Rogue],
            namespaces=["MOCK_"],
        )


def test_unmet_input_outside_requires_raises(alpha_stage):
    from librelane.stages import StageError, StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsGDS(Step):
        id = "Test.MockNeedsGDS"
        inputs = [DesignFormat.gds]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(StageError, match="consumes view 'gds'"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="needsgds",
            steps=[NeedsGDS],
            namespaces=["MOCK_"],
        )


def test_native_view_exempts_an_unmet_input(alpha_stage):
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsODB(Step):
        id = "Test.MockNeedsODB"
        inputs = [DesignFormat.odb]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="needsodb",
        steps=[NeedsODB],
        namespaces=["MOCK_"],
        native_views=[DesignFormat.odb],
    )
    assert registration.native_views == (DesignFormat.odb,)


def test_unprovided_view_raises(mock_steps):
    from librelane.stages import Stage, StageError, StageRegistry
    from librelane.state import DesignFormat

    Stage(
        id="registry_provides_gds",
        full_name="Registry Provides GDS",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.gds,),
    ).register()

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="never produces view 'gds'"):
        StageRegistry.register(
            stages=["registry_provides_gds"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_tagged_steps_carry_span_and_provider(alpha_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="tagged",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )
    tagged = registration.tagged_steps()

    assert tagged[0]._stage_span == ("registry_alpha",)
    assert tagged[0]._stage_provider == "tagged"
    assert tagged[0].id == "Test.MockPlace"
    assert tagged[0].get_implementation_id() == "Test.MockPlace"
