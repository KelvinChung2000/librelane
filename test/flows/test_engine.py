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


@pytest.fixture(scope="module")
def contract_job():
    """
    A job template with a hand-curated contract, and five providers for it.

    Every other job in this module is an inline ``steps`` job, and an inline
    job is deliberately exempt from the output-contract check: its ``provides``
    is derived from its steps' ``outputs``, which a step declares as a
    permission rather than an obligation. Only a ``uses`` job carries a
    contract someone wrote down on purpose, so only a ``uses`` job can exercise
    :meth:`librelane.flows.engine.Workflow._check_contract` at all -- including
    its metric half, which nothing else in the phase reaches, because an inline
    job's ``metrics`` is always empty.

    Module-scoped: ``Job.factory`` is a process-wide singleton, so
    registering the same id once per test would raise on the second use.

    Returns
    -------
    The :class:`threading.Event` the ``blocking`` provider's step waits on
    before returning, so a test can pin an interleaving against it.
    """
    import pathlib
    import threading

    from librelane.jobs import Job, JobRegistry
    from librelane.state import DesignFormat
    from librelane.steps import DeferredStepError, Step

    Job(
        id="engine_contract",
        full_name="Engine Contract",
        default_provider="honest",
        requires=(),
        provides=(DesignFormat.nl,),
        metrics=("engine__contract",),
    ).register()

    released = threading.Event()

    class Base(Step):
        inputs = []
        # Declared by every provider, because JobRegistry checks the template's
        # 'provides' against its provider's *declared* outputs at registration.
        # Whether a provider then actually writes the view is the run-time
        # question these tests are about.
        outputs = [DesignFormat.nl]

        def netlist(self) -> dict:
            out = pathlib.Path(self.step_dir) / "design.nl.v"
            out.write_text("module top(); endmodule")
            return {DesignFormat.nl: out}

    @Step.factory.register()
    class Honest(Base):
        id = "Test.ContractHonest"

        def run(self, state_in, **kwargs):
            return self.netlist(), {"engine__contract": 1}

    @Step.factory.register()
    class NoView(Base):
        id = "Test.ContractNoView"

        def run(self, state_in, **kwargs):
            return {}, {"engine__contract": 1}

    @Step.factory.register()
    class NoMetric(Base):
        id = "Test.ContractNoMetric"

        def run(self, state_in, **kwargs):
            return self.netlist(), {}

    @Step.factory.register()
    class Deferring(Base):
        id = "Test.ContractDeferring"

        def run(self, state_in, **kwargs):
            raise DeferredStepError("the tool reported 3 violations")

    @Step.factory.register()
    class Blocking(Base):
        id = "Test.ContractBlocking"

        def run(self, state_in, **kwargs):
            from librelane.steps.step.exceptions import StepError

            if not released.wait(timeout=30):
                raise StepError(
                    "the sibling job never released this one, so the "
                    "interleaving the test needs did not happen"
                )
            return {}, {"engine__contract": 1}

    for provider, step in (
        ("honest", Honest),
        ("no_view", NoView),
        ("no_metric", NoMetric),
        ("deferring", Deferring),
        ("blocking", Blocking),
    ):
        JobRegistry.register(
            job="engine_contract",
            provider=provider,
            steps=[step],
            namespaces=["ENGINE_CONTRACT_"],
        )

    return released


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


@mock_variables([flow_module, step_module])
def test_a_uses_job_honours_its_template_derived_contract(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"work": {"uses": "engine_contract/honest"}}}
    )

    final = Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    # Both halves of the contract came from the template, not from the step:
    # the provider's only declaration is 'outputs', which says nothing about
    # metrics at all.
    assert final[DesignFormat.nl] is not None
    assert final.metrics["engine__contract"] == 1


@mock_variables([flow_module, step_module])
def test_a_uses_job_that_does_not_produce_its_declared_view_raises(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"liar": {"uses": "engine_contract/no_view"}}}
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
    assert "'nl'" in message
    # The provider is the actionable half: 'engine_contract' has five of them
    # and only this one broke its promise.
    assert "Provider: no_view" in message


@mock_variables([flow_module, step_module])
def test_a_uses_job_that_does_not_produce_its_declared_metric_raises(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"quiet": {"uses": "engine_contract/no_metric"}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "quiet" in message
    assert "'engine__contract'" in message
    assert "Provider: no_metric" in message


@mock_variables([flow_module, step_module])
def test_an_inline_job_is_exempt_from_the_output_contract(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class Optional(Step):
        id = "Test.EngineOptional"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"maybe": {"steps": ["Test.EngineOptional"]}}}
    )

    # Step.outputs is documented as the views a step *may* emit.
    # Odb.DiodesOnPorts declares five and emits none whenever DIODE_ON_PORTS is
    # "none", which is the default, so asserting an inline job's derived
    # 'provides' would make a stock configuration a hard error -- and a
    # stricter rule than the SequentialFlow this engine is equivalent to, which
    # contract-checks no bare step at all. A 'uses' job, whose contract someone
    # curated by hand, is still checked.
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")


@mock_variables([flow_module, step_module])
def test_a_pass_through_job_is_exempt_from_the_output_contract(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_LIAR", False)],
            "jobs": {
                "liar": {"uses": "engine_contract/no_view", "if": "RUN_LIAR"},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)

    # The job's template declares 'nl' and the job produces nothing, but it
    # never ran, so there is no contract to have broken. Raising here would
    # make every gated-off job in a document a hard error.
    flow.start(tag="t")


@mock_variables([flow_module, step_module])
def test_a_deferred_error_is_not_replaced_by_a_contract_error(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.engine import JobContractError, Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"deferrer": {"uses": "engine_contract/deferring"}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    # The step deferred, so it never produced the 'nl' its template declares.
    # The deferred error is the real diagnosis and must be what surfaces.
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
    # 'uses' either one also unions in Job.streamout.provides, so two
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
    # The remedy, which is the half a document author acts on. Spec lines
    # 96-100: no job's 'source' can resolve a sink conflict, because the sink
    # is not a job, which is exactly why the document has a top-level 'final'.
    # Routing this join through the job-join message prescribed 'source' and
    # named a whole English sentence where a job id belongs.
    assert "final: " in message
    assert "'source' can resolve this" in message
    assert "source: {" not in message
    # The flow's name, not a sentence about it wrapped in the quotes that a job
    # id would have carried.
    assert "flow 'Streamout'" in message
    assert "Job 'the final state" not in message


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


@pytest.mark.usefixtures("two_workers")
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


@pytest.mark.usefixtures("two_workers")
@mock_variables([flow_module, step_module])
def test_one_job_s_deferral_does_not_exempt_another_from_its_contract(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.flow import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import DeferredStepError, Step

    # The interleaving is the whole test, and it has to be exact. An engine
    # keeping one shared list of deferrals gets the right answer by accident
    # unless 'deferrer' has *recorded* its deferral while 'liar' is still in
    # flight -- and a barrier between the two steps does not achieve that,
    # because both are released together and 'liar' can be resolved on the
    # scheduling thread before 'deferrer' has even finished unwinding.
    #
    # So 'deferrer' gets a second step. The engine records a deferral before
    # moving to the next step of the same job, so reaching Announce proves the
    # deferral is recorded, and 'liar' -- the 'blocking' provider, which waits
    # on the very event Announce sets -- does not return until it does.
    #
    # 'liar' is a 'uses' job now: an inline job carries no contract to be
    # exempted from, so only a curated one can make this question meaningful.
    deferral_recorded = contract_job
    deferral_recorded.clear()

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

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "deferrer": {"steps": ["Test.EngineDeferrer", "Test.EngineAnnounce"]},
                "liar": {"uses": "engine_contract/blocking"},
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


@pytest.mark.usefixtures("two_workers")
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


@mock_variables([flow_module, step_module])
def test_a_job_that_omits_uses_runs_the_template_its_id_names(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat

    # The document's central convenience, and the reason the spec's own sample
    # 'classic.yaml' writes 'lint:' and 'floorplan:' with nothing under them.
    # It has to survive all the way to a run: Workflow.__init__ calls
    # resolve_jobs, so a job that could not be resolved would not merely fail
    # to run, it would kill the document on construction.
    spec = FlowSpec.model_validate({"name": "Tiny", "jobs": {"engine_contract": {}}})

    final = Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert final[DesignFormat.nl] is not None
    assert final.metrics["engine__contract"] == 1


@mock_variables([flow_module, step_module])
def test_a_resumed_workflow_executes_nothing(minimal_design, mock_pdk):
    import pathlib

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    runs: dict[str, int] = {}

    class Base(Step):
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]

        def payload(self, state_in: State) -> str:
            """
            What this step's output is derived from, so that a re-run really
            would change the next step's input and a broken resume would
            cascade rather than stopping at one step.
            """
            incoming = state_in.get(DesignFormat.JSON_HEADER)
            if incoming is None:
                return ""
            return pathlib.Path(str(incoming)).read_text()

        def run(self, state_in, **kwargs):
            runs[type(self).id] = runs.get(type(self).id, 0) + 1
            out = pathlib.Path(self.step_dir) / "whatever.json"
            out.write_text(
                f'{{"by": "{type(self).id}", "from": {self.payload(state_in)!r}}}'
            )
            return {DesignFormat.JSON_HEADER: out}, {}

    @Step.factory.register()
    class Upstream(Base):
        id = "Test.EngineResumeUpstream"

    @Step.factory.register()
    class Downstream(Base):
        id = "Test.EngineResumeDownstream"
        inputs = [DesignFormat.JSON_HEADER]

    document = {
        "name": "Resume",
        "jobs": {
            "up": {"steps": ["Test.EngineResumeUpstream"]},
            "down": {
                "needs": ["up"],
                "steps": ["Test.EngineResumeDownstream"],
            },
        },
    }

    def make():
        return Workflow(FlowSpec.model_validate(document), minimal_design, **mock_pdk)

    make().start(tag="t")
    assert runs == {
        "Test.EngineResumeUpstream": 1,
        "Test.EngineResumeDownstream": 1,
    }

    make().start(tag="t")

    # Resume is the no-regression pin phase 4 depends on. It works through
    # Workflow today because dir_for_job_step is keyed on the job rather than
    # on a global step counter, which is exactly what a concurrent engine
    # cannot have; nothing pinned it until now.
    assert runs == {
        "Test.EngineResumeUpstream": 1,
        "Test.EngineResumeDownstream": 1,
    }


@mock_variables([flow_module, step_module])
def test_target_excludes_the_jobs_downstream_of_the_named_one(
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
    flow.start(tag="target", target=["first"])

    # 'second' is not skipped and not gated: it is not a node of the run at
    # all, so it neither fires nor stalls it.
    assert order == ["Test.EngineFirst"]


@mock_variables([flow_module, step_module])
def test_target_pulls_in_the_named_job_s_ancestors(
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
    flow.start(tag="target", target=["second"])

    assert order == ["Test.EngineFirst", "Test.EngineSecond"]


@mock_variables([flow_module, step_module])
def test_target_naming_an_unknown_job_is_an_error(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="unknown", target=["nope"])

    message = str(exc_info.value)
    assert "nope" in message
    assert "first" in message


@mock_variables([flow_module, step_module])
def test_invalidate_naming_an_unknown_job_is_an_error(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="unknown", invalidate=["nope"])

    message = str(exc_info.value)
    assert "--invalidate" in message
    assert "nope" in message
    assert "first" in message


@mock_variables([flow_module, step_module])
def test_skip_outside_the_target_subgraph_is_an_error(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

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
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="outside", target=["first"], skip=["second"])

    assert "second" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_invalidate_outside_the_target_subgraph_is_an_error(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

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
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="outside", target=["first"], invalidate=["second"])

    assert "second" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_target_runs_a_job_whose_ancestor_is_skipped(
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

    # An ancestor is inside the subgraph, so skipping it is legal, and it
    # still fires as a pass-through. Suppressing the firing instead would
    # leave the target itself waiting forever on a token nobody deposits.
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="target-skip", target=["second"], skip=["first"])

    assert order == ["Test.EngineSecond"]


@mock_variables([flow_module, step_module])
def test_invalidate_forces_a_job_and_its_descendants_to_rerun(
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

    Workflow(spec, minimal_design, **mock_pdk).start(tag="invalidate")
    order.clear()

    Workflow(spec, minimal_design, **mock_pdk).start(
        tag="invalidate", invalidate=["first"]
    )

    assert order == ["Test.EngineFirst", "Test.EngineSecond"]


@mock_variables([flow_module, step_module])
def test_invalidate_leaves_the_named_job_s_ancestors_reusable(
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

    Workflow(spec, minimal_design, **mock_pdk).start(tag="invalidate-leaf")
    order.clear()

    Workflow(spec, minimal_design, **mock_pdk).start(
        tag="invalidate-leaf", invalidate=["second"]
    )

    # The cache is invalidated forwards only. This is also the control for the
    # test above: 'first' really was reusable, so its re-run there was the
    # forcing and not a resume that never worked for these steps.
    assert order == ["Test.EngineSecond"]


@mock_variables([flow_module, step_module])
def test_a_targeted_run_joins_its_own_sinks_when_final_is_outside_it(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "final": "second",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="final-outside", target=["first"])

    # 'final' names the job whose output is the whole document's final state.
    # A --target that excludes it runs a different graph, and that graph's
    # final state is the join of its own leaves.
    assert final.metrics["first"] == 1
    assert "second" not in final.metrics


@mock_variables([flow_module, step_module])
def test_the_engine_reads_tools_before_resolving_its_configuration(
    contract_job, minimal_design, mock_pdk
):
    """
    The pre-pass exists because the step set has to be known before the
    configuration is validated: the steps are what declare the variables. This
    pins that TOOLS taken from the raw configuration mapping, which is not a
    resolved Config yet, is what self.Steps is built from.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"contract": {"uses": "engine_contract/honest"}}}
    )

    flow = Workflow(
        spec,
        dict(minimal_design, TOOLS={"contract": "no_metric"}),
        **mock_pdk,
    )

    assert [step.id for step in flow.Steps] == ["Test.ContractNoMetric"]
    assert flow.jobs["contract"].provider == "no_metric"


@mock_variables([flow_module, step_module])
def test_the_engine_declares_tools_itself(contract_job, minimal_design, mock_pdk):
    """
    No document declares TOOLS, so the engine's own Config must reach the
    resolved configuration alongside the document's variables. Assigning only
    the document's would make a configuration setting TOOLS an unknown key.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [{"name": "RUN_IT", "type": "bool", "description": "x"}],
            "jobs": {"contract": {"uses": "engine_contract/honest"}},
        }
    )

    flow = Workflow(
        spec,
        dict(minimal_design, RUN_IT=True, TOOLS={"contract": "no_metric"}),
        **mock_pdk,
    )

    assert flow.config["TOOLS"] == {"contract": "no_metric"}
    assert flow.config["RUN_IT"] is True


@mock_variables([flow_module, step_module])
def test_the_engine_reads_tools_out_of_an_already_resolved_configuration(
    contract_job, minimal_design, mock_pdk
):
    """
    A resolved Config skips the pre-pass, because the value is already there
    and typed. The two paths must agree, or a flow reconstructed from a
    resolved configuration -- which is how a reproducible re-runs -- would
    silently run the default provider.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"contract": {"uses": "engine_contract/honest"}}}
    )

    resolved = Workflow(
        spec,
        dict(minimal_design, TOOLS={"contract": "no_metric"}),
        **mock_pdk,
    ).config

    assert [step.id for step in Workflow(spec, resolved).Steps] == [
        "Test.ContractNoMetric"
    ]


@mock_variables([flow_module, step_module])
def test_the_engine_rejects_a_tools_key_naming_no_job(
    contract_job, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.jobs import JobResolutionError

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"contract": {"uses": "engine_contract/honest"}}}
    )

    with pytest.raises(JobResolutionError, match="contracts"):
        Workflow(spec, dict(minimal_design, TOOLS={"contracts": "honest"}), **mock_pdk)


@mock_variables([flow_module, step_module])
def test_reproducible_stops_before_the_named_step(
    counting_steps, minimal_design, mock_pdk, mocker
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, First, _ = counting_steps
    created = mocker.patch.object(First, "create_reproducible")
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
    flow.start(tag="repro", reproducible="first/Test.EngineFirst")

    # Neither the named step nor anything downstream of its job: the step is
    # replaced by the reproducible, and 'second' is not a node of the run.
    assert order == []
    assert created.call_count == 1


@mock_variables([flow_module, step_module])
def test_reproducible_runs_the_named_job_s_ancestors(
    counting_steps, minimal_design, mock_pdk, mocker
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, Second = counting_steps
    mocker.patch.object(Second, "create_reproducible")
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
    flow.start(tag="repro-ancestors", reproducible="second/Test.EngineSecond")

    # A reproducible is only reproducible if it is handed the input the step
    # would really have received, so the ancestors have to run for it.
    assert order == ["Test.EngineFirst"]


@mock_variables([flow_module, step_module])
def test_reproducible_returns_the_state_the_named_step_would_have_consumed(
    counting_steps, minimal_design, mock_pdk, mocker
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    _, _, Second = counting_steps
    mocker.patch.object(Second, "create_reproducible")
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
    final = flow.start(tag="repro-state", reproducible="second/Test.EngineSecond")

    # The run stopped at the named step, so the last thing it knows is the
    # state that step was about to be given. This is what SequentialFlow
    # returns for the same request.
    assert final.metrics["first"] == 1
    assert "second" not in final.metrics


@mock_variables([flow_module, step_module])
def test_reproducible_is_written_under_the_named_step_s_directory(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

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
    flow.start(tag="repro-dir", reproducible="second/Test.EngineSecond")

    # The real Step.create_reproducible, not a mock: what makes '<job>/<step>'
    # the natural address is that the reproducible lands inside the directory
    # that address already names, and only running it proves that.
    written = flow.run_dir / "second" / "1-test-enginesecond" / "reproducible"
    assert (written / "run_ol.sh").is_file()
    # The state 'first' produced, carried into the reproducible rather than
    # the empty state a run starts from.
    assert '"first": 1' in (written / "state_in.json").read_text()


@mock_variables([flow_module, step_module])
def test_reproducible_for_a_step_in_several_jobs_is_ambiguous(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "once": {"steps": ["Test.EngineFirst"]},
                "twice": {"needs": ["once"], "steps": ["Test.EngineFirst"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="ambiguous", reproducible="Test.EngineFirst")

    message = str(exc_info.value)
    assert "once" in message
    assert "twice" in message


@mock_variables([flow_module, step_module])
def test_reproducible_naming_a_step_no_job_runs_is_an_error(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="unknown-step", reproducible="first/Test.EngineSecond")

    message = str(exc_info.value)
    assert "Test.EngineSecond" in message
    assert "first" in message


@mock_variables([flow_module, step_module])
def test_reproducible_for_a_job_a_false_condition_stops_is_refused(
    counting_steps,
    minimal_design,
    mock_pdk,
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {"first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}},
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="gated", reproducible="first/Test.EngineFirst")

    assert "RUN_FIRST" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_reproducible_for_a_skipped_job_is_refused(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="skipped", reproducible="first/Test.EngineFirst", skip=["first"])

    message = str(exc_info.value)
    assert "--skip" in message
    assert "first" in message


@mock_variables([flow_module, step_module])
def test_reproducible_and_target_together_are_refused(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(
            tag="both",
            target=["first"],
            reproducible="first/Test.EngineFirst",
        )

    assert "--reproducible" in str(exc_info.value)
    assert "--target" in str(exc_info.value)
