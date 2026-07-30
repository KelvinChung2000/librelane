import json
import pathlib

import pytest

from librelane.config import Variable
from librelane.flows import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def ResumeSteps():
    """
    Three steps that record how many times each has executed, so a test can
    assert reuse directly rather than inferring it.
    """
    from librelane.common import Path
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
            runs[self.id] = runs.get(self.id, 0) + 1
            out_file = pathlib.Path(self.step_dir) / "whatever.json"
            out_file.write_text(
                json.dumps({"produced_by": self.id, "from": self.payload(state_in)})
            )
            return {DesignFormat.JSON_HEADER: Path(out_file)}, {}

    class First(Base):
        id = "Test.First"
        config_vars = [Variable("DUMMY_VARIABLE", type=str, description="x")]

        def payload(self, state_in: State) -> str:
            # Test.First has no input, so its configuration is what its output
            # is derived from.
            return str(self.config["DUMMY_VARIABLE"])

    class Second(Base):
        id = "Test.Second"
        inputs = [DesignFormat.JSON_HEADER]

    class Third(Base):
        id = "Test.Third"
        inputs = [DesignFormat.JSON_HEADER]

    return (First, Second, Third), runs


@pytest.fixture
def ResumeFlow(ResumeSteps):
    from librelane.flows import SequentialFlow

    (First, Second, Third), runs = ResumeSteps

    class ResumeFlow(SequentialFlow):
        Steps = [First, Second, Third]

    def make():
        return ResumeFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    return make, runs


def step_dirs(tag="T"):
    return sorted(
        entry.name
        for entry in pathlib.Path(f"/cwd/runs/{tag}").iterdir()
        if entry.is_dir() and entry.name != "final" and entry.name != "tmp"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_step_directories_are_positional(ResumeFlow):
    """
    A step's directory must not depend on how many earlier steps happened to
    run, or a resumed run cannot find its own prior output.
    """
    make, _ = ResumeFlow
    make().start(tag="T")

    assert step_dirs() == ["1-test-first", "2-test-second", "3-test-third"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_skipped_step_leaves_its_position_empty(ResumeFlow):
    """
    Today's dense counter would name the third step 2-. Positional numbering
    leaves the gap, which is the point: Test.Third keeps its directory whether
    or not Test.Second ran.
    """
    make, _ = ResumeFlow
    make().start(tag="T", skip=["Test.Second"])

    assert step_dirs() == ["1-test-first", "3-test-third"]


@pytest.mark.usefixtures("_mock_conf_fs")
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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_resumed_run_executes_nothing(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")
    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_resumed_run_adds_no_directories(ResumeFlow):
    """The old behaviour appended a whole second pass into the same tag."""
    make, _ = ResumeFlow
    make().start(tag="T")
    before = step_dirs()

    make().start(last_run=True)

    assert step_dirs() == before


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_config_reruns_from_that_step_onward(ResumeFlow):
    """
    DUMMY_VARIABLE belongs to Test.First only, but re-running it changes
    Test.Second's input state, so the invalidation has to cascade.
    """
    from librelane.flows import SequentialFlow

    make, runs = ResumeFlow
    make().start(tag="T")

    (First, Second, Third) = make().Steps

    class Changed(SequentialFlow):
        Steps = [First, Second, Third]

    Changed(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "DIFFERENT",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    ).start(tag="T")

    assert runs == {"Test.First": 2, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_edited_input_file_reruns_the_flow(ResumeFlow):
    """
    Every path is unchanged; only the bytes of /cwd/src/a.v moved. This is
    the case a path-equality design reuses wrongly.
    """
    make, runs = ResumeFlow
    pathlib.Path("/cwd/src/a.v").write_text("module top(); endmodule")
    make().start(tag="T")

    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")
    make().start(tag="T")

    assert runs["Test.First"] == 2


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_crash_resumes_at_the_failing_step(ResumeSteps):
    from librelane.flows import FlowError, SequentialFlow
    from librelane.steps import StepError

    (First, Second, Third), runs = ResumeSteps
    fail = {"now": True}

    class Flaky(Second):
        id = "Test.Second"

        def run(self, state_in, **kwargs):
            if fail["now"]:
                raise StepError("boom")
            return super().run(state_in, **kwargs)

    class CrashFlow(SequentialFlow):
        Steps = [First, Flaky, Third]

    def make():
        return CrashFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs == {"Test.First": 1}

    fail["now"] = False
    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_deleted_output_view_reruns_only_its_step(ResumeFlow):
    """
    Test.Third is not dragged along, and that is the payoff of hashing
    contents rather than counting executions. Test.Second regenerated a
    byte-identical view, so Test.Third's input is the input it already ran on
    and its recorded result is still the right answer.
    """
    make, runs = ResumeFlow
    make().start(tag="T")
    pathlib.Path("/cwd/runs/T/2-test-second/whatever.json").unlink()

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 2, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_reused_step_counts_as_executed_for_the_stage_contract(ResumeFlow):
    """
    StagedFlow._after_step skips the contract check unless every step in the
    stage executed. A reused step really did produce its views, so reporting
    it as not executed would disable the check the contract exists for.
    """
    make, _ = ResumeFlow
    make().start(tag="T")

    seen = []
    subject = make()
    original = type(subject)._after_step

    def record(self, step, state, executed):
        seen.append((step.id, executed))
        return original(self, step, state, executed)

    type(subject)._after_step = record
    try:
        subject.start(last_run=True)
    finally:
        type(subject)._after_step = original

    assert seen == [
        ("Test.First", True),
        ("Test.Second", True),
        ("Test.Third", True),
    ]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_overwrite_discards_the_run_directory(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", overwrite=True)

    assert runs == {"Test.First": 2, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_reruns_that_step_even_though_its_key_matches(ResumeFlow):
    """
    The remedy for the one thing the key does not cover: a CAD tool upgraded
    in place under an unchanged LibreLane version.
    """
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(last_run=True, frm="Test.Second")

    assert runs == {"Test.First": 1, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_refuses_when_an_earlier_step_is_stale(ResumeFlow):
    """
    Better to name the stale step than to proceed with an empty state and
    fail later on a missing input.
    """
    from librelane.flows import FlowException

    make, _ = ResumeFlow
    make().start(tag="T")
    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")

    with pytest.raises(FlowException, match="Test.First"):
        make().start(last_run=True, frm="Test.Second")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_on_a_fresh_tag_refuses(ResumeFlow):
    from librelane.flows import FlowException

    make, _ = ResumeFlow

    with pytest.raises(FlowException, match="Test.First"):
        make().start(tag="FRESH", frm="Test.Second")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_deferred_error_step_runs_again_and_raises_again(ResumeSteps):
    """
    A step that deferred an error never wrote an entry, so it re-runs. That is
    what keeps a deferred failure from being silently reused as a success.
    """
    from librelane.flows import FlowError, SequentialFlow
    from librelane.steps import DeferredStepError

    (First, Second, Third), runs = ResumeSteps

    class Deferring(Second):
        id = "Test.Second"

        def run(self, state_in, **kwargs):
            runs[self.id] = runs.get(self.id, 0) + 1
            raise DeferredStepError("deferred boom")

    class DeferFlow(SequentialFlow):
        Steps = [First, Deferring, Third]

    def make():
        return DeferFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs["Test.Second"] == 1

    with pytest.raises(FlowError):
        make().start(last_run=True)

    assert runs["Test.Second"] == 2, (
        "a deferred-error step was reused instead of re-run"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_skipping_a_step_invalidates_the_steps_after_it(ResumeFlow):
    """
    Skipping changes what the next step receives, so it cannot be reused.
    """
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", skip=["Test.Second"])

    assert runs["Test.First"] == 1, "the step before the skip should be reused"
    assert runs["Test.Second"] == 1, "the skipped step should not run"
    assert runs["Test.Third"] == 2, "the step after the skip must not be reused"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_to_then_resume_continues_rather_than_restarting(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T", to="Test.Second")
    assert runs == {"Test.First": 1, "Test.Second": 1}

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_shorter_step_list_leaves_the_orphaned_directory_alone(ResumeSteps):
    """
    Resuming a tag with a different step list shifts positions. Directories
    belonging to no current position are never read and never deleted.
    """
    from librelane.flows import SequentialFlow

    (First, Second, Third), runs = ResumeSteps

    class Long(SequentialFlow):
        Steps = [First, Second, Third]

    class Short(SequentialFlow):
        Steps = [First, Second]

    config = {
        "DESIGN_NAME": "WHATEVER",
        "DUMMY_VARIABLE": "PINGAS",
        "VERILOG_FILES": ["/cwd/src/a.v"],
    }
    kwargs = dict(design_dir="/cwd", pdk="dummy", scl="dummy_scl", pdk_root="/pdk")

    Long(config, **kwargs).start(tag="T")
    Short(config, **kwargs).start(tag="T")

    assert pathlib.Path("/cwd/runs/T/3-test-third").is_dir(), (
        "an orphaned step directory must not be deleted"
    )
    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}, (
        "the shorter list must reuse the steps it still has"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_explicit_initial_state_stands_in_for_the_steps_before_from(ResumeFlow):
    """
    The ECO workflow documented in ``docs/source/usage/using_ecos.md``: hand a
    step the state a previous run produced and start there, in a fresh tag.

    The steps before it must not be resolved from cache. There is nothing in a
    fresh tag to resolve, and resolving would discard the very state the user
    supplied.
    """
    from librelane.state import State

    make, runs = ResumeFlow
    make().start(tag="SOURCE")
    handoff = State.loads(
        pathlib.Path("/cwd/runs/SOURCE/1-test-first/state_out.json").read_text()
    )

    make().start(tag="ECO", with_initial_state=handoff, frm="Test.Second")

    assert runs == {"Test.First": 1, "Test.Second": 2, "Test.Third": 2}
    produced = json.loads(
        pathlib.Path("/cwd/runs/ECO/2-test-second/whatever.json").read_text()
    )
    assert (
        produced["from"]
        == pathlib.Path("/cwd/runs/SOURCE/1-test-first/whatever.json").read_text()
    ), "Test.Second did not receive the state it was handed"
