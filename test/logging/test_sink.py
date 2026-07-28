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
