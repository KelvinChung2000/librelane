# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


@pytest.fixture
def steps():
    from librelane.config import Variable
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class A(Step):
        id = "Composition.A"
        inputs = [DesignFormat.nl]
        outputs = [DesignFormat.odb]
        config_vars = [Variable("A_VAR", int, "desc", default=1)]

        def run(self, state_in, **kwargs):
            return {}, {}

    class B(Step):
        id = "Composition.B"
        inputs = [DesignFormat.odb]
        outputs = [DesignFormat.def_]
        config_vars = [Variable("B_VAR", int, "desc", default=2)]

        def run(self, state_in, **kwargs):
            return {}, {}

    return A, B


def test_unmet_inputs_exclude_views_produced_earlier(steps):
    from librelane.state import DesignFormat
    from librelane.steps.step.composition import compose_step_sequence

    A, B = steps
    union = compose_step_sequence([A, B])

    assert union.unmet_inputs == [DesignFormat.nl]
    assert set(union.outputs) == {DesignFormat.odb, DesignFormat.def_}
    assert [v.name for v in union.config_vars] == ["A_VAR", "B_VAR"]


def test_unmet_inputs_preserve_first_appearance_order(steps):
    from librelane.state import DesignFormat
    from librelane.steps.step.composition import compose_step_sequence

    A, B = steps
    union = compose_step_sequence([B, A])

    assert union.unmet_inputs == [DesignFormat.odb, DesignFormat.nl]


def test_contradictory_config_vars_raise(steps):
    from librelane.config import Variable
    from librelane.steps import Step
    from librelane.steps.step.composition import compose_step_sequence

    A, _ = steps

    class Conflicting(Step):
        id = "Composition.Conflicting"
        inputs = []
        outputs = []
        config_vars = [Variable("A_VAR", str, "different", default="x")]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(TypeError, match="contradicts an earlier declaration"):
        compose_step_sequence([A, Conflicting])
