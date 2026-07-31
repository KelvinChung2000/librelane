import io
import pathlib
import re

import pytest
from rich.console import Console

from librelane.flows import flow
from librelane.steps import step


mock_variables = pytest.mock_variables

pytestmark = pytest.mark.all


def run_noisy_flow(mocker, tag):
    """Runs a flow whose step emits a warning and an error, returns the terminal."""
    from librelane.flows import SequentialFlow
    from librelane.logging import logger as logger_module
    from librelane.steps import Step

    console = Console(file=io.StringIO(), width=200, color_system=None)
    mocker.patch.object(logger_module, "console", console)
    mocker.patch.object(
        logger_module, "live", logger_module.LiveLog(console, autostart=False)
    )
    logger_module.initialize_logger()

    class NoisyStep(Step):
        id = "Test.NoisyStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            from loguru import logger

            logger.info("something uninteresting")
            logger.warning("a warning that scrolled past")
            logger.error("an error that scrolled past")
            return {}, {}

    class NoisyFlow(SequentialFlow):
        Steps = [NoisyStep]

    try:
        NoisyFlow(
            {
                "meta": {"version": 1},
                "DESIGN_NAME": "WHATEVER",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        ).start(tag=tag)
        logger_module.live.drain()
        return console.file.getvalue()
    finally:
        logger_module.initialize_logger()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_errors_are_restated_at_the_end_of_the_run(mocker):
    """
    Warnings were already replayed at flow end; errors were not, so an error
    early in a long run could scroll away unseen.
    """
    output = run_noisy_flow(mocker, "ERRSUM")

    tail = output[output.index("a warning that scrolled past") :]
    assert "an error that scrolled past" in tail


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_summary_says_which_step_an_issue_came_from(mocker):
    output = run_noisy_flow(mocker, "STEPSUM")

    assert "Test.NoisyStep" in output


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_summary_points_into_the_step_log(mocker):
    """
    The terminal is a live view; the step log is the durable record. A summary
    that cannot be followed back to the log leaves you grepping.
    """
    output = run_noisy_flow(mocker, "PTRSUM")

    pointers = re.findall(r"(\S*step\.log):(\d+)", output)
    assert pointers, f"summary carried no step.log pointer:\n{output}"

    path_text, line_no = pointers[0]
    log_path = pathlib.Path(path_text)
    if not log_path.is_absolute():
        # Pointers are relative to the working directory, as a user would type
        # them straight into a pager.
        log_path = pathlib.Path.cwd() / path_text
    assert log_path.exists(), f"pointer names a file that does not exist: {log_path}"

    lines = log_path.read_text().splitlines()
    assert 1 <= int(line_no) <= len(lines), "pointer is out of range for the log"
    assert "scrolled past" in lines[int(line_no) - 1], (
        f"pointer line {line_no} does not hold the issue: {lines[int(line_no) - 1]!r}"
    )
