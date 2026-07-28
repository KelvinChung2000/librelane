import io
import pathlib

import pytest
from rich.console import Console

from librelane.flows import flow
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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_records_inside_a_step_are_attributed_without_an_explicit_bind():
    """
    Step.start establishes the step context, so code that never called
    logger.bind(step=...) is still attributed. That reaches the places that
    could not bind at all -- notably the SUBPROCESS lines emitted by
    DefaultOutputProcessor, which has no step of its own to name.
    """
    from loguru import logger

    from librelane.flows import SequentialFlow
    from librelane.steps import Step

    seen: dict[str, str | None] = {}

    class UnboundStep(Step):
        id = "Test.UnboundStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            logger.info("no explicit bind here")
            logger.log("SUBPROCESS", "raw tool output")
            return {}, {}

    class UnboundFlow(SequentialFlow):
        Steps = [UnboundStep]

    sink_id = logger.add(
        lambda message: seen.setdefault(
            str(message.record["message"]), message.record["extra"].get("step")
        ),
        format="{message}",
        level=0,
    )
    try:
        UnboundFlow(
            {
                "meta": {"version": 1},
                "DESIGN_NAME": "WHATEVER",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        ).start(tag="UNBOUND")
    finally:
        logger.remove(sink_id)

    assert seen["no explicit bind here"] == "Test.UnboundStep"
    assert seen["raw tool output"] == "Test.UnboundStep"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_step_header_is_ordered_with_the_output_it_heads(captured_terminal):
    """
    Step.start used to print console.rule() directly while output sat in the
    buffer, so the header would appear detached from the lines it introduces.
    Routing it through the buffer keeps the two together.
    """
    from librelane.flows import SequentialFlow
    from librelane.steps import Step

    console, live = captured_terminal

    class HeadedStep(Step):
        id = "Test.HeadedStep"
        inputs = []
        outputs = []
        long_name = "Headed Step Long Name"

        def run(self, state_in, **kwargs):
            from loguru import logger

            logger.log("SUBPROCESS", "the-tool-output")
            return {}, {}

    class HeadedFlow(SequentialFlow):
        Steps = [HeadedStep]

    HeadedFlow(
        {
            "meta": {"version": 1},
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    ).start(tag="HEADED")
    live.drain()
    output = console.file.getvalue()

    assert "Headed Step Long Name" in output
    assert "the-tool-output" in output
    assert output.index("Headed Step Long Name") < output.index("the-tool-output")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_each_step_gets_its_own_log_file():
    """
    Per-step logs are what the end-of-run summary points into, and what you can
    tail while a parallel run is in flight. flow.log blends every step together
    with no way to slice it apart.
    """
    from loguru import logger

    from librelane.flows import SequentialFlow
    from librelane.steps import Step

    class TalkativeStep(Step):
        id = "Test.TalkativeStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            logger.info("belongs to the step log")
            logger.warning("a warning worth keeping")
            return {}, {}

    class TalkativeFlow(SequentialFlow):
        Steps = [TalkativeStep]

    TalkativeFlow(
        {
            "meta": {"version": 1},
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    ).start(tag="TALKATIVE")

    run_dir = pathlib.Path("/cwd/runs/TALKATIVE")
    step_logs = sorted(run_dir.glob("*-talkativestep/step.log"))
    assert step_logs, f"no per-step log written; run dir held {list(run_dir.iterdir())}"

    contents = step_logs[0].read_text()
    assert "belongs to the step log" in contents
    assert "a warning worth keeping" in contents
