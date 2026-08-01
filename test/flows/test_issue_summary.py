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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_flows_logs_exclude_another_concurrent_flows_records(mocker):
    """
    Issue 889: error.log and warning.log filtered on level alone, and Loguru
    sinks are process-wide, so a second flow running at the same time had its
    warnings and errors copied into this flow's logs too.

    The step emits one pair of records normally and one pair from inside
    another flow's context, which is what a concurrent flow looks like to this
    flow's sinks.
    """
    from librelane.flows import SequentialFlow
    from librelane.logging import flow_context
    from librelane.logging import logger as logger_module
    from librelane.steps import Step

    console = Console(file=io.StringIO(), width=200, color_system=None)
    mocker.patch.object(logger_module, "console", console)
    mocker.patch.object(
        logger_module, "live", logger_module.LiveLog(console, autostart=False)
    )
    logger_module.initialize_logger()

    class StepUnderTwoFlows(Step):
        id = "Test.StepUnderTwoFlows"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            from loguru import logger

            logger.warning("mine: a warning")
            logger.error("mine: an error")
            with flow_context("some-other-flow"):
                logger.warning("theirs: a warning")
                logger.error("theirs: an error")
            return {}, {}

    class OneFlow(SequentialFlow):
        Steps = [StepUnderTwoFlows]

    try:
        instance = OneFlow(
            {
                "meta": {"version": 1},
                "DESIGN_NAME": "WHATEVER",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )
        instance.start(tag="two_flows")
        run_dir = pathlib.Path(instance.run_dir)
    finally:
        logger_module.initialize_logger()

    warnings = (run_dir / "warning.log").read_text()
    errors = (run_dir / "error.log").read_text()

    assert "mine: a warning" in warnings
    assert "theirs: a warning" not in warnings
    assert "mine: an error" in errors
    assert "theirs: an error" not in errors
    # The level split has to survive the scoping.
    assert "an error" not in warnings
    assert "a warning" not in errors


def _warning(text: str):
    """
    The smallest thing loguru hands a callable sink: an object with a
    ``record`` mapping. Built by hand rather than emitted through loguru,
    because the interleaving below has to be driven from the test and a real
    emission would drag the whole logging stack into it.
    """
    import types

    return types.SimpleNamespace(
        record={
            "extra": {},
            "level": types.SimpleNamespace(name="WARNING"),
            "message": text,
        }
    )


def test_the_issue_sink_does_not_lose_a_repeat_under_concurrency():
    """
    ``_StepIssueSink.__call__`` is registered as a loguru *callable* sink with
    no ``enqueue``, so loguru runs it synchronously on the emitting thread.
    One step ran at a time before the workflow engine; now every concurrent
    job's steps emit into this one object, and its check-then-act on a plain
    dict loses whichever ``Record`` the second thread overwrites, taking that
    message's ``repeats`` and ``similar`` counts out of the end-of-run replay.
    """
    import threading

    from librelane.flows.flow import Flow

    sink = Flow._StepIssueSink()

    # Forces the exact interleaving the missing lock allowed: the first thread
    # is held between "is this key already collected?" and recording its answer
    # until the second thread has asked the same question, so both see the key
    # absent and the second Record silently replaces the first. Holding at
    # __setitem__ rather than at __contains__ is what makes it deterministic --
    # released at __contains__, the winner runs all the way to its assignment
    # before the GIL is handed over and the race never happens.
    #
    # The wait is bounded, and the bound is the assertion's other half: a
    # correctly locked sink can never let the second thread reach __contains__
    # while the first holds the lock, so the timeout expiring is what the lock
    # working looks like from in here.
    entered = threading.Condition()
    askers = [0]

    class Rendezvous(dict):
        def __contains__(self, key):
            with entered:
                askers[0] += 1
                entered.notify_all()
            return super().__contains__(key)

        def __setitem__(self, key, value):
            with entered:
                entered.wait_for(lambda: askers[0] == 2, timeout=0.5)
            super().__setitem__(key, value)

    sink.warnings = Rendezvous()

    threads = [
        threading.Thread(target=lambda: sink(_warning("the same warning")))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert list(sink.warnings) == ["the same warning"]
    assert sink.warnings["the same warning"].repeats == 1, (
        "one of the two emissions was dropped instead of counted"
    )
