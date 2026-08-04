# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
A step finding its configuration rather than being handed it, and the one
place that still has to know the difference: what a step is *recorded* as
having read.
"""

import pytest

from librelane.config import variable
from librelane.engine import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def AmbientSteps():
    """
    Two steps declaring a variable each, so that "the union covers both" and
    "each is recorded with only its own" are distinguishable.
    """
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    class First(Step):
        id = "Test.AmbientFirst"
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]

        class Config(Step.Config):
            FIRST_VARIABLE: str = variable(description="x")

        def run(self, state_in: State, **kwargs):
            return {}, {}

    class Second(Step):
        id = "Test.AmbientSecond"
        inputs = []
        outputs = []

        class Config(Step.Config):
            SECOND_VARIABLE: str = variable(description="x")

        def run(self, state_in: State, **kwargs):
            return {}, {}

    return First, Second


def _scope_over(steps, **overrides):
    from librelane.config import Config, build_scope

    variables = list(
        {
            declared.name: declared
            for cls in steps
            for declared in cls.get_all_config_variables()
        }.values()
    )
    resolved, _ = Config.load(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
            "FIRST_VARIABLE": "one",
            "SECOND_VARIABLE": "two",
            **overrides,
        },
        variables,
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    return build_scope(resolved, variables)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_step_reads_the_scope_it_runs_under(AmbientSteps):
    from librelane.config import use_config
    from librelane.state import State

    First, _ = AmbientSteps

    with use_config(_scope_over(AmbientSteps)):
        built = First(state_in=State())

    assert built.config.FIRST_VARIABLE == "one"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_step_reads_the_singleton_when_no_scope_is_open(AmbientSteps):
    from librelane.config import set_current_config
    from librelane.state import State

    First, _ = AmbientSteps

    set_current_config(_scope_over(AmbientSteps, FIRST_VARIABLE="published"))

    assert First(state_in=State()).config.FIRST_VARIABLE == "published"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_every_step_in_a_scope_shares_one_model(AmbientSteps):
    """
    The point of the shared model: two steps under one scope read one
    validated object, so neither pays to re-validate what the other already
    did. What differs between them is the view, which holds no values.
    """
    from librelane.config import use_config
    from librelane.state import State

    First, Second = AmbientSteps

    with use_config(_scope_over(AmbientSteps)) as scope:
        first = First(state_in=State())
        second = Second(state_in=State())

    assert first.config.shared is second.config.shared is scope.typed
    assert first.config.FIRST_VARIABLE == "one"
    assert second.config.SECOND_VARIABLE == "two"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_step_may_not_read_a_variable_it_does_not_declare(AmbientSteps):
    """
    The model is the union of every step's variables, so another step's is
    sitting right there. Reading it would work for exactly as long as the step
    ran inside a flow: ``Step.load`` -- a reproducible, a re-run -- hands a
    step only what it declares.
    """
    from librelane.config import use_config
    from librelane.state import State
    from librelane.steps.step.config_view import UndeclaredVariable

    First, _ = AmbientSteps

    with use_config(_scope_over(AmbientSteps)):
        first = First(state_in=State())

    with pytest.raises(UndeclaredVariable, match="does not declare"):
        first.config.SECOND_VARIABLE
    with pytest.raises(KeyError):
        first.config["SECOND_VARIABLE"]
    assert "SECOND_VARIABLE" not in first.config
    # An AttributeError, so that 'getattr(config, name, default)' and every
    # 'hasattr' check still behave.
    assert getattr(first.config, "SECOND_VARIABLE", "fallback") == "fallback"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_step_is_recorded_with_only_the_variables_it_declares(AmbientSteps):
    """
    ``config`` is the union; ``own_config_dict`` is not. The resume key, the
    step's ``config.json`` and the reproducible all read the latter, so an edit
    to a variable a step does not declare leaves it alone.
    """
    from librelane.config import use_config
    from librelane.state import State

    First, Second = AmbientSteps

    with use_config(_scope_over(AmbientSteps)):
        first = First(state_in=State())
        second = Second(state_in=State())

    assert first.own_config_dict()["FIRST_VARIABLE"] == "one"
    assert "SECOND_VARIABLE" not in first.own_config_dict()
    assert second.own_config_dict()["SECOND_VARIABLE"] == "two"
    assert "FIRST_VARIABLE" not in second.own_config_dict()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_unrelated_variable_does_not_change_a_steps_resume_key(AmbientSteps):
    from librelane.common import Fingerprinter
    from librelane.config import use_config
    from librelane.engine.resume import resume_key
    from librelane.state import State

    First, _ = AmbientSteps
    fingerprinter = Fingerprinter()

    with use_config(_scope_over(AmbientSteps)):
        before = resume_key(First(state_in=State()), State(), fingerprinter)
    with use_config(_scope_over(AmbientSteps, SECOND_VARIABLE="edited")):
        after = resume_key(First(state_in=State()), State(), fingerprinter)
    with use_config(_scope_over(AmbientSteps, FIRST_VARIABLE="edited")):
        own = resume_key(First(state_in=State()), State(), fingerprinter)

    assert before == after, "a variable the step does not declare moved its key"
    assert before != own, "a variable the step does declare did not move its key"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_explicit_configuration_still_wins(AmbientSteps):
    """
    The parameter did not go away. A step handed one -- as ``Step.load`` hands
    a reproducible's -- reads that and not whatever the process holds.
    """
    from librelane.config import Config, set_current_config, use_config
    from librelane.state import State

    First, _ = AmbientSteps

    passed, _ = Config.load(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
            "FIRST_VARIABLE": "explicit",
        },
        First.get_all_config_variables(),
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    set_current_config(_scope_over(AmbientSteps, FIRST_VARIABLE="singleton"))
    with use_config(_scope_over(AmbientSteps, FIRST_VARIABLE="scoped")):
        built = First(passed, State())

    assert built.config.FIRST_VARIABLE == "explicit"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_overrides_do_not_leak_into_the_shared_model(AmbientSteps):
    """
    A per-step override cannot be written onto the model every other step in
    the scope is reading, so a step given one gets a configuration of its own.
    """
    from librelane.config import current_config, use_config
    from librelane.state import State

    First, _ = AmbientSteps

    with use_config(_scope_over(AmbientSteps)) as scope:
        overridden = First(state_in=State(), FIRST_VARIABLE="mine")
        plain = First(state_in=State())

        assert overridden.config.FIRST_VARIABLE == "mine"
        assert overridden.config is not scope.typed
        assert plain.config.FIRST_VARIABLE == "one"
        assert current_config().FIRST_VARIABLE == "one"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_step_with_nothing_current_says_so(AmbientSteps):
    from librelane.state import State

    First, _ = AmbientSteps

    with pytest.raises(TypeError, match="Missing required argument 'config'"):
        First(state_in=State())
