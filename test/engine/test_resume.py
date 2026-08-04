import json
import pathlib

import pytest

from librelane.config import variable
from librelane.flows import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

#: Three jobs, one step each, chained so that re-running any of them changes
#: what the next one receives. A one-job document could not show a cascade at
#: all, which is half of what resume has to get right.
DOCUMENT = {
    "name": "Resume",
    "jobs": {
        "first": {"steps": ["Test.ResumeFirst"]},
        "second": {"needs": ["first"], "steps": ["Test.ResumeSecond"]},
        "third": {"needs": ["second"], "steps": ["Test.ResumeThird"]},
    },
}


@pytest.fixture
def ResumeSteps():
    """
    Three steps that record how many times each has executed, so a test can
    assert reuse directly rather than inferring it.
    """
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    runs: dict[str, int] = {}

    class Base(Step):
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]

        def payload(self, state_in: State) -> str:
            """
            What this step's output is derived from.

            Every step's output depends on its input, as a real step's does. A
            step whose output ignored its input would regenerate a byte-identical
            view after re-running, the step after it would then correctly stay
            valid, and no test here could observe a cascade at all.
            """
            incoming = state_in[DesignFormat.JSON_HEADER]
            if incoming is None:
                return ""
            return pathlib.Path(str(incoming)).read_text()

        def run(self, state_in: State, **kwargs):
            # The class's id, not the instance's: a workflow names the job in
            # each instance's id, and which step executed is the question.
            runs[type(self).id] = runs.get(type(self).id, 0) + 1
            out_file = pathlib.Path(self.step_dir) / "whatever.json"
            out_file.write_text(
                json.dumps(
                    {"produced_by": type(self).id, "from": self.payload(state_in)}
                )
            )
            return {DesignFormat.JSON_HEADER: pathlib.Path(out_file)}, {}

    @Step.factory.register()
    class First(Base):
        id = "Test.ResumeFirst"

        class Config(Base.Config):
            DUMMY_VARIABLE: str = variable(description="x")

        def payload(self, state_in: State) -> str:
            # Test.ResumeFirst has no input, so its configuration is what its
            # output is derived from.
            return str(self.config["DUMMY_VARIABLE"])

    @Step.factory.register()
    class Second(Base):
        id = "Test.ResumeSecond"
        inputs = [DesignFormat.JSON_HEADER]

    @Step.factory.register()
    class Third(Base):
        id = "Test.ResumeThird"
        inputs = [DesignFormat.JSON_HEADER]

    return (First, Second, Third), runs


@pytest.fixture
def ResumeFlow(ResumeSteps, minimal_design, mock_pdk):
    """
    Returns
    -------
    ``(make, runs)``, where ``make`` builds a fresh :class:`Workflow` over
    :data:`DOCUMENT` and ``runs`` counts each step's executions.

    A factory rather than one instance, because resuming is what a *second*
    invocation does, and an instance that carried its first run's state into
    the second would not be exercising the path a user takes.
    """
    _, runs = ResumeSteps

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    def make():
        return Workflow(
            FlowSpec.model_validate(DOCUMENT),
            {**minimal_design, "DUMMY_VARIABLE": "PINGAS"},
            **mock_pdk,
        )

    return make, runs


def job_dirs(run_dir) -> list[str]:
    """Every directory the run wrote, relative to the run directory."""
    root = pathlib.Path(run_dir)
    return sorted(
        str(entry.relative_to(root))
        for entry in root.rglob("*")
        if entry.is_dir() and entry.name != "tmp"
    )


@mock_variables([flow, step])
def test_the_flow_owns_one_fingerprinter_per_run(ResumeFlow):
    """
    The memo is what keeps a PDK's liberty files read once rather than once
    per step, so the instance has to outlive a single step.
    """
    from librelane.common import Fingerprinter

    make, _ = ResumeFlow
    subject = make()
    assert subject.fingerprinter is None

    subject.start(tag="T")

    assert isinstance(subject.fingerprinter, Fingerprinter)


@mock_variables([flow, step])
def test_a_resumed_run_adds_no_directories(ResumeFlow):
    """The old behaviour appended a whole second pass into the same tag."""
    make, _ = ResumeFlow
    first = make()
    first.start(tag="T")
    before = job_dirs(first.run_dir)

    make().start(last_run=True)

    assert job_dirs(first.run_dir) == before


@mock_variables([flow, step])
def test_an_edited_input_file_reruns_the_flow(ResumeFlow, mock_conf_dir):
    """
    Every path is unchanged; only the bytes of the design's Verilog moved.
    This is the case a path-equality design reuses wrongly.
    """
    make, runs = ResumeFlow
    source = pathlib.Path(mock_conf_dir.cwd) / "src" / "a.v"
    source.write_text("module top(); endmodule")
    make().start(tag="T")

    source.write_text("module top(); wire w; endmodule")
    make().start(tag="T")

    assert runs["Test.ResumeFirst"] == 2


@mock_variables([flow, step])
def test_a_crash_resumes_at_the_failing_job(ResumeSteps, ResumeFlow):
    from librelane.flows import FlowError
    from librelane.steps import Step, StepError

    (_, Second, _), runs = ResumeSteps
    make, _ = ResumeFlow
    fail = {"now": True}

    @Step.factory.register()
    class Flaky(Second):
        id = "Test.ResumeSecond"

        def run(self, state_in, **kwargs):
            if fail["now"]:
                raise StepError("boom")
            return super().run(state_in, **kwargs)

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs == {"Test.ResumeFirst": 1}

    fail["now"] = False
    make().start(last_run=True)

    assert runs == {
        "Test.ResumeFirst": 1,
        "Test.ResumeSecond": 1,
        "Test.ResumeThird": 1,
    }


@mock_variables([flow, step])
def test_a_deleted_output_view_reruns_only_its_step(ResumeFlow):
    """
    Test.ResumeThird is not dragged along, and that is the payoff of hashing
    contents rather than counting executions. Test.ResumeSecond regenerated a
    byte-identical view, so Test.ResumeThird's input is the input it already
    ran on and its recorded result is still the right answer.
    """
    make, runs = ResumeFlow
    first = make()
    first.start(tag="T")
    (
        pathlib.Path(first.run_dir) / "second" / "1-test-resumesecond" / "whatever.json"
    ).unlink()

    make().start(last_run=True)

    assert runs == {
        "Test.ResumeFirst": 1,
        "Test.ResumeSecond": 2,
        "Test.ResumeThird": 1,
    }


@mock_variables([flow, step])
def test_overwrite_discards_the_run_directory(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", overwrite=True)

    assert runs == {
        "Test.ResumeFirst": 2,
        "Test.ResumeSecond": 2,
        "Test.ResumeThird": 2,
    }


@mock_variables([flow, step])
def test_a_deferred_error_step_runs_again_and_raises_again(ResumeSteps, ResumeFlow):
    """
    A step that deferred an error never wrote an entry, so it re-runs. That is
    what keeps a deferred failure from being silently reused as a success.
    """
    from librelane.flows import FlowError
    from librelane.steps import DeferredStepError, Step

    (_, Second, _), runs = ResumeSteps
    make, _ = ResumeFlow

    @Step.factory.register()
    class Deferring(Second):
        id = "Test.ResumeSecond"

        def run(self, state_in, **kwargs):
            runs[type(self).id] = runs.get(type(self).id, 0) + 1
            raise DeferredStepError("deferred boom")

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs["Test.ResumeSecond"] == 1

    with pytest.raises(FlowError):
        make().start(last_run=True)

    assert runs["Test.ResumeSecond"] == 2, (
        "a deferred-error step was reused instead of re-run"
    )


@mock_variables([flow, step])
def test_skipping_a_job_invalidates_the_jobs_after_it(ResumeFlow):
    """
    A skipped job passes its input state through unchanged, so the job after
    it receives something other than what it ran on and cannot be reused.
    """
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", skip=["second"])

    assert runs["Test.ResumeFirst"] == 1, "the job before the skip should be reused"
    assert runs["Test.ResumeSecond"] == 1, "the skipped job should not run"
    assert runs["Test.ResumeThird"] == 2, "the job after the skip must not be reused"


@mock_variables([flow, step])
def test_a_targeted_run_then_resume_continues_rather_than_restarting(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T", target=["second"])
    assert runs == {"Test.ResumeFirst": 1, "Test.ResumeSecond": 1}

    make().start(last_run=True)

    assert runs == {
        "Test.ResumeFirst": 1,
        "Test.ResumeSecond": 1,
        "Test.ResumeThird": 1,
    }


@mock_variables([flow, step])
def test_an_explicit_initial_state_is_what_the_first_job_consumes(
    ResumeFlow, ResumeSteps, minimal_design, mock_pdk
):
    """
    ``--with-initial-state`` hands a step the state a previous run produced.
    The engine deposits it on every source place, so it is what the graph's
    first job reads rather than something the run overwrites before anyone
    looks at it.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import State

    make, _ = ResumeFlow
    source = make()
    source.start(tag="SOURCE")
    produced_by_first = pathlib.Path(source.run_dir) / "first" / "1-test-resumefirst"
    handoff = State.loads((produced_by_first / "state_out.json").read_text())

    # A one-job document whose only step consumes the handed view, so that what
    # it received is written down where the test can read it back.
    consumer = Workflow(
        FlowSpec.model_validate(
            {"name": "Handoff", "jobs": {"only": {"steps": ["Test.ResumeSecond"]}}}
        ),
        minimal_design,
        **mock_pdk,
    )
    consumer.start(tag="ECO", with_initial_state=handoff)

    consumed = json.loads(
        (pathlib.Path(consumer.run_dir) / "only" / "1-test-resumesecond")
        .joinpath("whatever.json")
        .read_text()
    )
    assert consumed["from"] == (produced_by_first / "whatever.json").read_text(), (
        "the first job did not receive the state it was handed"
    )
