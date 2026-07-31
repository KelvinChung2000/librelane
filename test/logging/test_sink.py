import io

import pytest
from loguru import logger
from rich.console import Console


pytestmark = pytest.mark.all


@pytest.fixture
def terminal(mocker):
    """Points the terminal sink at a console we can read back."""
    from librelane.logging import logger as logger_module

    console = Console(file=io.StringIO(), width=120, force_terminal=True)
    mocker.patch.object(logger_module, "console", console)
    mocker.patch.object(logger_module, "live", logger_module.LiveLog(console))
    logger_module.initialize_logger()
    yield logger_module
    logger_module.initialize_logger()


def rendered(module) -> str:
    return module.live._console.file.getvalue()


def test_subprocess_records_are_buffered_rather_than_printed(terminal, mocker):
    """
    The sink runs on the thread reading a tool's stdout. It must hand off, not
    render, or it stops draining the pipe and blocks the tool.
    """
    spy = mocker.spy(terminal.live._console, "print")

    with terminal.step_context("Yosys.Synthesis"):
        logger.log("SUBPROCESS", "3.2. Executing HIERARCHY pass")
        assert spy.call_count == 0


def test_buffered_subprocess_output_reaches_the_terminal_on_drain(terminal):
    with terminal.step_context("Yosys.Synthesis"):
        logger.log("SUBPROCESS", "3.2. Executing HIERARCHY pass")
        terminal.live.drain()

    assert "3.2. Executing HIERARCHY pass" in rendered(terminal)


def test_step_context_attributes_records_without_an_explicit_bind(terminal):
    """
    Replaces ~30 hand-written logger.bind(step=...) calls, and reaches code
    that never had one -- notably the SUBPROCESS lines emitted by
    DefaultOutputProcessor.
    """
    with terminal.step_context("Yosys.Synthesis"):
        logger.log("SUBPROCESS", "attributed line")

        display = terminal.live.get("Yosys.Synthesis")
        assert display is not None
        assert display.last_line == "attributed line"


def test_leaving_a_step_context_flushes_and_deregisters(terminal):
    with terminal.step_context("Yosys.Synthesis"):
        logger.log("SUBPROCESS", "the-final-line")

    assert "the-final-line" in rendered(terminal)
    assert terminal.live.get("Yosys.Synthesis") is None


def test_warnings_keep_their_styling(terminal):
    with terminal.step_context("Yosys.Synthesis"):
        logger.warning("3 latches inferred")
        terminal.live.drain()

    output = rendered(terminal)
    assert "3 latches inferred" in output
    assert "\x1b[" in output, "styling was lost"


def test_a_warning_never_overtakes_the_output_it_followed(terminal):
    """
    The ordering hazard batching introduces: a styled record printed directly
    while tool output sat in the buffer would appear above lines that came
    first.
    """
    with terminal.step_context("Yosys.Synthesis"):
        logger.log("SUBPROCESS", "tool-line-before")
        logger.warning("the-warning")
        logger.log("SUBPROCESS", "tool-line-after")
        terminal.live.drain()

    output = rendered(terminal)
    assert (
        output.index("tool-line-before")
        < output.index("the-warning")
        < output.index("tool-line-after")
    )


def test_flow_level_records_still_render(terminal):
    """Records emitted outside any step must not be swallowed."""
    logger.info("Starting flow")
    terminal.live.drain()

    assert "Starting flow" in rendered(terminal)


def test_condensed_mode_still_suppresses_subprocess_output(terminal):
    """
    --condensed-mode documents that subprocess logs are suppressed. That is a
    user preference and stays, unlike the manual toggling around parallel
    sections.
    """
    terminal.options.set_condensed_mode(True)
    try:
        with terminal.step_context("Yosys.Synthesis"):
            logger.log("SUBPROCESS", "should-not-appear")
            logger.info("should-appear")
            terminal.live.drain()
    finally:
        terminal.options.set_condensed_mode(False)

    output = rendered(terminal)
    assert "should-not-appear" not in output
    assert "should-appear" in output


def test_flow_scoped_sinks_do_not_collect_another_flows_records(tmp_path):
    """
    Issue 889: Loguru sinks are process-wide. Two flows running at once each
    registered an error.log/warning.log filtered only by level, so every record
    landed in both flows' logs.
    """
    from librelane.logging import (
        additional_sink,
        belongs_to_flow_run,
        flow_context,
    )

    a_log = tmp_path / "a.log"
    b_log = tmp_path / "b.log"

    with flow_context("run-a") as a:
        with additional_sink(a_log, filter=belongs_to_flow_run(a)):
            # Flow A's sink is live while flow B emits, which is exactly the
            # overlap two concurrent flows produce.
            with flow_context("run-b") as b:
                with additional_sink(b_log, filter=belongs_to_flow_run(b)):
                    logger.warning("belongs to b")
            logger.warning("belongs to a")

    assert a_log.read_text() == "belongs to a\n"
    assert b_log.read_text() == "belongs to b\n"


def test_flow_scoped_sinks_still_separate_errors_from_warnings(tmp_path):
    """The level split error.log/warning.log relies on has to survive scoping."""
    from librelane.logging import (
        additional_sink,
        belongs_to_flow_run,
        flow_context,
    )

    warning_log = tmp_path / "warning.log"
    error_log = tmp_path / "error.log"

    with flow_context("run-a") as run:
        with (
            additional_sink(warning_log, filter=belongs_to_flow_run(run, "WARNING")),
            additional_sink(error_log, filter=belongs_to_flow_run(run, "ERROR")),
        ):
            logger.warning("a warning")
            logger.error("an error")

    assert warning_log.read_text() == "a warning\n"
    assert error_log.read_text() == "an error\n"


def test_flow_run_attribution_reaches_worker_threads(tmp_path):
    """
    Steps fan out onto a thread pool, and a new thread starts with an empty
    context, so without propagation their records would be dropped by every
    flow-scoped sink.
    """
    from librelane.common import ContextPropagatingThreadPoolExecutor
    from librelane.logging import (
        additional_sink,
        belongs_to_flow_run,
        flow_context,
    )

    log = tmp_path / "flow.log"

    with flow_context("run-a") as run:
        with additional_sink(log, filter=belongs_to_flow_run(run)):
            with ContextPropagatingThreadPoolExecutor(max_workers=1) as tpe:
                tpe.submit(logger.warning, "from a worker").result()

    assert log.read_text() == "from a worker\n"


def test_process_stats_thread_keeps_its_log_attribution(mocker):
    """
    The resource monitor is a bare Thread, so its one warning would fall
    outside every flow-scoped sink unless it carries the context over itself.
    """
    import psutil

    from librelane.logging import flow_context
    from librelane.steps.step.process_stats import ProcessStatsThread

    seen = {}

    def sink(message):
        seen["flow_run"] = message.record["extra"].get("flow_run")

    # Not one of the two messages the monitor treats as a normal exit, so it
    # actually reaches the logger.warning call.
    error = psutil.Error()
    error.msg = "the tracker fell over"
    process = mocker.MagicMock(spec=psutil.Popen)
    process.status.side_effect = error

    from librelane.logging import additional_sink

    with flow_context("run-a"):
        thread = ProcessStatsThread(process)

    with additional_sink(sink, level="WARNING"):
        thread.start()
        thread.join()

    assert seen["flow_run"] == "run-a"
