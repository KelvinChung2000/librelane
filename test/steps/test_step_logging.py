import io
import os
import pathlib

import pytest
from rich.console import Console

from librelane.engine import flow
from librelane.steps import step


mock_variables = pytest.mock_variables

pytestmark = pytest.mark.all


@pytest.fixture
def captured_terminal(mocker):
    """
    Redirects the terminal sink to a readable console.

    A fixture rather than inline patching so the sink is rebuilt against the
    real console *after* the mocker unwinds. Restoring it inside the test body
    leaves the global sink bound to a console that is about to disappear, which
    corrupts later tests.
    """
    from librelane.logging import logger as logger_module

    console = Console(file=io.StringIO(), width=120, color_system=None)
    live = logger_module.LiveLog(console, autostart=False)
    mocker.patch.object(logger_module, "console", console)
    mocker.patch.object(logger_module, "live", live)
    logger_module.initialize_logger()
    yield console, live
    mocker.stopall()
    logger_module.initialize_logger()


def _one_step_workflow(name: str, step_id: str, mock_conf_dir):
    """
    A workflow whose single job runs one step, against the mock design tree.

    Parameters
    ----------
    name : str
        The document's name. Its lowercase form is the job id, and so the
        directory the step's own directory sits in.
    step_id : str
        The registered id of the step the job runs.
    mock_conf_dir : MockConfTree
        The real-filesystem mock tree. Real rather than faked because a
        workflow runs its jobs on a thread pool, which pyfakefs cannot serve.
    """
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": name, "jobs": {name.lower(): {"steps": [step_id]}}}
    )
    return Workflow(
        spec,
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": [os.path.join(mock_conf_dir.cwd, "src", "a.v")],
        },
        design_dir=mock_conf_dir.cwd,
        pdk="dummy",
        scl="dummy_scl",
        pdk_root=mock_conf_dir.pdk_root,
    )


@mock_variables([flow, step])
def test_records_inside_a_step_are_attributed_without_an_explicit_bind(mock_conf_dir):
    """
    Step.start establishes the step context, so code that never called
    logger.bind(step=...) is still attributed. That reaches the places that
    could not bind at all -- notably the SUBPROCESS lines emitted by
    DefaultOutputProcessor, which has no step of its own to name.

    What is bound is the *instance's* id, which a workflow builds as
    ``<step id> (<job id>)`` so that two concurrent runs of one step class can
    be told apart in a shared log. Asserting the class id instead would pass
    while every line of a parallel run named the same step.
    """
    from loguru import logger

    from librelane.steps import Step

    seen: dict[str, str | None] = {}

    @Step.factory.register()
    class UnboundStep(Step):
        id = "Test.UnboundStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            logger.info("no explicit bind here")
            logger.log("SUBPROCESS", "raw tool output")
            return {}, {}

    sink_id = logger.add(
        lambda message: seen.setdefault(
            str(message.record["message"]), message.record["extra"].get("step")
        ),
        format="{message}",
        level=0,
    )
    try:
        _one_step_workflow("Unbound", "Test.UnboundStep", mock_conf_dir).start(
            tag="UNBOUND"
        )
    finally:
        logger.remove(sink_id)

    assert seen["no explicit bind here"] == "Test.UnboundStep (unbound)"
    assert seen["raw tool output"] == "Test.UnboundStep (unbound)"


@mock_variables([flow, step])
def test_the_step_header_is_ordered_with_the_output_it_heads(
    captured_terminal, mock_conf_dir
):
    """
    Step.start used to print console.rule() directly while output sat in the
    buffer, so the header would appear detached from the lines it introduces.
    Routing it through the buffer keeps the two together.
    """
    from librelane.steps import Step

    console, live = captured_terminal

    @Step.factory.register()
    class HeadedStep(Step):
        id = "Test.HeadedStep"
        inputs = []
        outputs = []
        long_name = "Headed Step Long Name"

        def run(self, state_in, **kwargs):
            from loguru import logger

            logger.log("SUBPROCESS", "the-tool-output")
            return {}, {}

    _one_step_workflow("Headed", "Test.HeadedStep", mock_conf_dir).start(tag="HEADED")
    live.drain()
    output = console.file.getvalue()

    assert "Headed Step Long Name" in output
    assert "the-tool-output" in output
    assert output.index("Headed Step Long Name") < output.index("the-tool-output")


@mock_variables([flow, step])
def test_each_step_gets_its_own_log_file(mock_conf_dir):
    """
    Per-step logs are what the end-of-run summary points into, and what you can
    tail while a parallel run is in flight. flow.log blends every step together
    with no way to slice it apart.
    """
    from loguru import logger

    from librelane.steps import Step

    @Step.factory.register()
    class TalkativeStep(Step):
        id = "Test.TalkativeStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            logger.info("belongs to the step log")
            logger.warning("a warning worth keeping")
            return {}, {}

    flow = _one_step_workflow("Talkative", "Test.TalkativeStep", mock_conf_dir)
    flow.start(tag="TALKATIVE")

    run_dir = pathlib.Path(flow.run_dir)
    step_logs = sorted(run_dir.glob("1-talkative/*-test-talkativestep/step.log"))
    assert step_logs, f"no per-step log written; run dir held {list(run_dir.iterdir())}"

    contents = step_logs[0].read_text()
    assert "belongs to the step log" in contents
    assert "a warning worth keeping" in contents


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_default_subprocess_log_is_named_after_the_step_class(mock_config):
    """
    A flow may give an instance a per-run id -- ``Workflow`` names the job in
    it so two concurrent runs of one step class can be told apart in the logs
    -- and ``get_log_path`` used to slugify that, so the default subprocess log
    silently became ``netgen-lvs-signoff.log``. The step directory already
    names the job, and the newcomers' guide tells readers to open these files
    by name.
    """
    from librelane.state import State
    from librelane.steps import Step

    class Loud(Step):
        id = "Test.LoudStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    disambiguated = Loud(
        config=mock_config,
        state_in=State(),
        id="Test.LoudStep (signoff)",
    )
    disambiguated.step_dir = pathlib.Path("/cwd/runs/X/signoff/1-test-loudstep")

    assert disambiguated.id == "Test.LoudStep (signoff)"
    assert disambiguated.get_log_path().endswith("/test-loudstep.log")
