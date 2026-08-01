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
    from librelane.flows.flow import FlowError
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
        {"name": "Tiny", "jobs": {"liar": {"steps": ["Test.EngineLiar"]}}}
    )

    # FlowError rather than JobContractError: a contract miss is collected
    # alongside step failures now, because raising it straight out would
    # abandon the futures of jobs still in flight. JobContractError is still
    # what _check_contract raises and is still a FlowError, so this is weaker
    # only in type, not in message.
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_independent_branches_both_run(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    ran: list[str] = []

    @Step.factory.register()
    class Left(Step):
        id = "Test.EngineLeft"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("left")
            return {}, {}

    @Step.factory.register()
    class Right(Step):
        id = "Test.EngineRight"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("right")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Diamond",
            "jobs": {
                "left": {"steps": ["Test.EngineLeft"]},
                "right": {"steps": ["Test.EngineRight"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # Sorted, because the two are concurrent and the order they append in is
    # not a property the engine promises.
    assert sorted(ran) == ["left", "right"]


@pytest.fixture
def two_workers():
    """
    Pins the process-wide pool to two workers for one test.

    Every test below that synchronises two jobs on a barrier needs the pool to
    be at least as wide as the barrier. The real one is sized from the host's
    core count, so a single-core runner would hang the barrier for a reason
    that has nothing to do with the engine.
    """
    from librelane.common import ContextPropagatingThreadPoolExecutor, get_tpe, set_tpe

    previous = get_tpe()
    pool = ContextPropagatingThreadPoolExecutor(max_workers=2)
    set_tpe(pool)
    yield
    set_tpe(previous)
    pool.shutdown()


@pytest.mark.usefixtures("_mock_conf_fs", "two_workers")
@mock_variables([flow_module, step_module])
def test_two_enabled_jobs_run_at_the_same_time(minimal_design, mock_pdk):
    import threading

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    # A barrier, not a sleep: neither job can return until both have arrived,
    # so the run completes if and only if the two really did overlap. Under a
    # sequential engine the first arrival waits alone, the timeout breaks the
    # barrier and the run raises. There is no interleaving this can pass by
    # luck on, and no wall-clock threshold to tune.
    barrier = threading.Barrier(2, timeout=30)

    @Step.factory.register()
    class MeetA(Step):
        id = "Test.EngineMeetA"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            barrier.wait()
            return {}, {}

    @Step.factory.register()
    class MeetB(Step):
        id = "Test.EngineMeetB"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            barrier.wait()
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Meeting",
            "jobs": {
                "a": {"steps": ["Test.EngineMeetA"]},
                "b": {"steps": ["Test.EngineMeetB"]},
            },
        }
    )

    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert not barrier.broken


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_failure_reports_every_failed_job_not_just_the_first(
    minimal_design, mock_pdk
):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step
    from librelane.steps.step.exceptions import StepError

    @Step.factory.register()
    class BadLeft(Step):
        id = "Test.EngineBadLeft"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("left exploded")

    @Step.factory.register()
    class BadRight(Step):
        id = "Test.EngineBadRight"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("right exploded")

    spec = FlowSpec.model_validate(
        {
            "name": "Diamond",
            "jobs": {
                "left": {"steps": ["Test.EngineBadLeft"]},
                "right": {"steps": ["Test.EngineBadRight"]},
            },
        }
    )

    # Both jobs are enabled in the first sweep, so both are submitted before
    # either failure can be observed: the engine only stops enabling work
    # between sweeps. Which one fails first does not change the assertion.
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "left exploded" in message
    assert "right exploded" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_downstream_of_a_failure_does_not_run(minimal_design, mock_pdk):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step
    from librelane.steps.step.exceptions import StepError

    ran: list[str] = []

    @Step.factory.register()
    class Exploder(Step):
        id = "Test.EngineExploder"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("boom")

    @Step.factory.register()
    class Downstream(Step):
        id = "Test.EngineDownstream"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("downstream")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Chain",
            "jobs": {
                "boom": {"steps": ["Test.EngineExploder"]},
                "after": {"needs": ["boom"], "steps": ["Test.EngineDownstream"]},
            },
        }
    )

    # 'after' is enabled only by 'boom' firing, and a failed job never fires,
    # so this holds whatever the thread schedule does.
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError):
        flow.start(tag="t")

    assert ran == []


@pytest.mark.usefixtures("_mock_conf_fs", "two_workers")
@mock_variables([flow_module, step_module])
def test_one_job_s_deferral_does_not_exempt_another_from_its_contract(
    minimal_design, mock_pdk
):
    import threading

    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import DeferredStepError, Step
    from librelane.steps.step.exceptions import StepError

    # The interleaving is the whole test, and it has to be exact. An engine
    # keeping one shared list of deferrals gets the right answer by accident
    # unless 'deferrer' has *recorded* its deferral while 'liar' is still in
    # flight -- and a barrier between the two steps does not achieve that,
    # because both are released together and 'liar' can be resolved on the
    # scheduling thread before 'deferrer' has even finished unwinding.
    #
    # So 'deferrer' gets a second step. The engine records a deferral before
    # moving to the next step of the same job, so reaching Announce proves the
    # deferral is recorded, and 'liar' does not return until it does.
    deferral_recorded = threading.Event()

    @Step.factory.register()
    class Deferrer(Step):
        id = "Test.EngineDeferrer"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise DeferredStepError("the tool reported 3 violations")

    @Step.factory.register()
    class Announce(Step):
        id = "Test.EngineAnnounce"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            deferral_recorded.set()
            return {}, {}

    @Step.factory.register()
    class Liar(Step):
        id = "Test.EngineLiar"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            if not deferral_recorded.wait(timeout=30):
                raise StepError(
                    "'deferrer' never recorded its deferral, so the "
                    "interleaving this test needs did not happen"
                )
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "deferrer": {"steps": ["Test.EngineDeferrer", "Test.EngineAnnounce"]},
                "liar": {"steps": ["Test.EngineLiar"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    # Deferral is a per-job fact. 'deferrer' deferring says nothing about
    # whether 'liar' honoured its contract, so 'liar' is still checked and its
    # miss is what surfaces. A single shared list of deferred errors cannot
    # answer that question, because a length compared before and after cannot
    # tell which job appended.
    message = str(exc_info.value)
    assert "liar" in message
    assert "'nl'" in message


@pytest.mark.usefixtures("_mock_conf_fs", "two_workers")
@mock_variables([flow_module, step_module])
def test_two_jobs_running_one_step_class_do_not_share_a_log(minimal_design, mock_pdk):
    import os
    import threading

    from loguru import logger

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    # Both steps are inside their step_context, and so both step.log sinks are
    # installed, before either logs. Nose-to-tail the collision is not
    # reachable, because the first sink is removed before the second is added.
    barrier = threading.Barrier(2, timeout=30)

    @Step.factory.register()
    class Marker(Step):
        id = "Test.EngineMarker"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            # Taken from the step directory rather than from self.id, because
            # whether self.id distinguishes the two instances is the thing
            # under test and cannot be assumed by the marker that tests it.
            job = os.path.basename(os.path.dirname(self.step_dir))
            barrier.wait()
            logger.info(f"marker for {job}")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Twins",
            "jobs": {
                "a": {"steps": ["Test.EngineMarker"]},
                "b": {"steps": ["Test.EngineMarker"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    a_log = (flow.run_dir / "a" / "1-test-enginemarker" / "step.log").read_text()
    b_log = (flow.run_dir / "b" / "1-test-enginemarker" / "step.log").read_text()

    # The loguru sink behind step.log filters on the running step's id, and
    # LiveLog keys its registry on the same id. Two jobs running one step
    # class shared both, so each job's records landed in the other's step.log
    # as well as its own.
    assert "marker for a" in a_log
    assert "marker for b" not in a_log
    assert "marker for b" in b_log
    assert "marker for a" not in b_log


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_an_error_scheduling_a_job_is_collected_not_raised_from_the_sweep(
    gds_writers, minimal_design, mock_pdk
):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    # 'sink' consumes two predecessors that wrote different GDSIIs, so the
    # join of its *input* raises on the scheduling thread, not in a worker.
    spec = FlowSpec.model_validate(
        {
            "name": "Streamout",
            "jobs": {
                "magic_streamout": {"steps": ["Test.EngineMagicStreamOut"]},
                "klayout_streamout": {"steps": ["Test.EngineKLayoutStreamOut"]},
                "sink": {
                    "needs": ["magic_streamout", "klayout_streamout"],
                    "steps": ["Test.EngineMagicStreamOut"],
                },
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    # Collected, so it carries the "Job '<name>':" prefix every other failure
    # does. Raised straight out of the sweep it would unwind through the
    # progress bar and this run's loguru sinks with jobs still in flight,
    # leaving them writing to sinks that no longer exist.
    assert "Job 'sink':" in str(exc_info.value)
