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
import pytest

from librelane.flows import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _bool_var(name: str, default: bool) -> dict:
    return {
        "name": name,
        "type": "bool",
        "description": "x",
        "default": default,
    }


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_jobs_fire_in_topological_order(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
                "first": {"steps": ["Test.EngineFirst"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineFirst", "Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_document_name_is_the_flow_name(
    counting_steps, minimal_design, mock_pdk, mocker
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    progress_bar = mocker.spy(flow_module, "FlowProgressBar")
    flow = Workflow(spec, minimal_design, **mock_pdk)

    assert flow.name == "Tiny"
    # The attribute alone does not pin the ordering this test exists to
    # protect: flow.py:487-489 substitutes the class name only while `name` is
    # still NotImplemented, so assigning it after super().__init__ would leave
    # flow.name == "Tiny" as well. What the ordering protects is the progress
    # bar Flow.__init__ builds from self.name at flow.py:509, whose name is
    # what a terminal shows, so assert on how it was constructed.
    assert progress_bar.call_args_list == [mocker.call("Tiny")]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_false_condition_passes_state_through_without_running(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # 'first' did not run, but 'second' still did: the token was released.
    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_conjunction_runs_the_job_only_when_every_variable_is_true(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_A", True), _bool_var("RUN_B", False)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_A and RUN_B"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_conjunction_whose_variables_are_all_true_runs_the_job(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_A", True), _bool_var("RUN_B", True)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_A and RUN_B"},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineFirst"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_skipped_job_passes_state_through_without_running(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t", skip=["first"])

    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_step_writes_into_its_job_s_directory(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # slugify("Test.EngineFirst") is "test-enginefirst".
    assert (flow.run_dir / "first" / "1-test-enginefirst").is_dir()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_that_does_not_produce_its_contract_raises(minimal_design, mock_pdk):
    from librelane.flows.engine import JobContractError, Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class Liar(Step):
        id = "Test.EngineLiar"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"liar": {"steps": ["Test.EngineLiar"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(JobContractError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "liar" in message
    # Quoted, because the bare substring "nl" also occurs in the message's
    # "inline steps" provider text, so it would hold even if the view were
    # never interpolated.
    assert "'nl'" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_pass_through_job_is_exempt_from_the_output_contract(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class Liar(Step):
        id = "Test.EngineLiar"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_LIAR", False)],
            "jobs": {
                "liar": {"steps": ["Test.EngineLiar"], "if": "RUN_LIAR"},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)

    # The job declares 'nl' and produces nothing, but it never ran, so there is
    # no contract to have broken. Raising here would make every gated-off job
    # in a document a hard error.
    flow.start(tag="t")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_deferred_error_is_not_replaced_by_a_contract_error(minimal_design, mock_pdk):
    from librelane.flows.engine import JobContractError, Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import DeferredStepError, Step

    @Step.factory.register()
    class Deferrer(Step):
        id = "Test.EngineDeferrer"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            raise DeferredStepError("the tool reported 3 violations")

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"deferrer": {"steps": ["Test.EngineDeferrer"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    # The step deferred, so it never produced the 'nl' it declares. The
    # deferred error is the real diagnosis and must be what surfaces.
    assert "the tool reported 3 violations" in str(exc_info.value)
    assert not isinstance(exc_info.value, JobContractError)


@pytest.fixture
def gds_writers():
    """
    Two steps that each write their own GDSII, so two leaves disagree on 'gds'.
    """
    import os
    import pathlib

    from librelane.state import DesignFormat
    from librelane.steps import Step

    # outputs = [] rather than [DesignFormat.gds]: 'gds' is what the step
    # actually returns, not what it declares. Declaring it would make the two
    # jobs' contracts collide, which phase 1's
    # spec_validation._check_sink_join_is_unambiguous already catches at load
    # time (correctly), and this fixture exists to exercise the run-time
    # backstop instead.
    #
    # Not the streamout case, despite the resemblance. Magic.StreamOut and
    # KLayout.StreamOut both declare 'gds' in their real outputs, and a job
    # 'uses' either one also unions in Stage.streamout.provides, so two
    # streamout leaves are caught at load time, not here. What this models is
    # the narrower gap that makes the run-time check load-bearing at all:
    # Step.start validates declared inputs only and nothing anywhere checks
    # that a step's views_updates is a subset of its declared outputs, so a
    # step can return a view its contract never mentioned.
    @Step.factory.register()
    class MagicLike(Step):
        id = "Test.EngineMagicStreamOut"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            out = os.path.join(self.step_dir, "a.gds")
            open(out, "w", encoding="utf8").write("magic")
            return {DesignFormat.gds: pathlib.Path(out)}, {}

    @Step.factory.register()
    class KLayoutLike(Step):
        id = "Test.EngineKLayoutStreamOut"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            out = os.path.join(self.step_dir, "a.gds")
            open(out, "w", encoding="utf8").write("klayout")
            return {DesignFormat.gds: pathlib.Path(out)}, {}

    return MagicLike, KLayoutLike


def _two_streamouts(final: str | None = None) -> dict:
    document: dict = {
        "name": "Streamout",
        "jobs": {
            "magic_streamout": {"steps": ["Test.EngineMagicStreamOut"]},
            "klayout_streamout": {"steps": ["Test.EngineKLayoutStreamOut"]},
        },
    }
    if final is not None:
        document["final"] = final
    return document


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_final_state_is_the_join_of_the_leaves(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    # Two leaves whose metrics differ in name but not in value, so the join
    # merges rather than conflicting and the result carries both.
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"steps": ["Test.EngineSecond"]},
            },
        }
    )

    final = Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert final.metrics["first"] == 1
    assert final.metrics["second"] == 1


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_two_leaves_with_conflicting_views_are_a_run_time_conflict(
    gds_writers, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.join import JoinConflictError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_streamouts())

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(JoinConflictError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "gds" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_final_names_the_job_whose_state_is_returned(
    gds_writers, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat

    spec = FlowSpec.model_validate(_two_streamouts(final="klayout_streamout"))

    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert str(final[DesignFormat.gds]).startswith(
        str(flow.run_dir / "klayout_streamout")
    )
