import io
import time

import pytest
from rich.console import Console


pytestmark = pytest.mark.all


def make_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=True)


def rendered(console: Console) -> str:
    return console.file.getvalue()


def test_submitting_a_line_does_not_touch_the_console(mocker):
    """
    The producer is the thread draining a tool's stdout pipe. It must not pay
    Rich's rendering cost, because a slow reader stops draining the pipe and
    blocks the tool itself.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    spy = mocker.spy(console, "print")
    live = LiveLog(console, autostart=False)

    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "3.2. Executing HIERARCHY pass")

    assert spy.call_count == 0
    assert rendered(console) == ""


def test_drain_emits_every_submitted_line(mocker):
    """Nothing is dropped: every line submitted reaches the terminal."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")

    for i in range(500):
        live.submit("Yosys.Synthesis", f"line-{i}")
    live.drain()

    output = rendered(console)
    for i in range(500):
        assert f"line-{i}" in output, f"line-{i} was dropped"


def test_drain_coalesces_consecutive_unstyled_lines_into_one_print(mocker):
    """
    The whole performance fix. Rich's per-call overhead -- taking the Live lock,
    clearing and redrawing the live region -- dominates its per-line cost, so a
    batch must cost one ``console.print``, not one per line.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")
    # Prime the block header so the spy counts content prints only.
    live.submit("Yosys.Synthesis", "priming")
    live.drain()

    for i in range(500):
        live.submit("Yosys.Synthesis", f"line-{i}")

    spy = mocker.spy(console, "print")
    live.drain()

    assert spy.call_count == 1


def test_drain_preserves_order_across_styled_and_unstyled_records(mocker):
    """
    Batching must not let a styled record overtake the tool output that
    preceded it. A warning that appears above the lines it followed makes the
    log untrustworthy.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")

    live.submit("Yosys.Synthesis", "before-one")
    live.submit("Yosys.Synthesis", "before-two")
    live.submit("Yosys.Synthesis", "the-warning", style="yellow")
    live.submit("Yosys.Synthesis", "after-one")
    live.drain()

    output = rendered(console)
    positions = [
        output.index(marker)
        for marker in ("before-one", "before-two", "the-warning", "after-one")
    ]
    assert positions == sorted(positions)


def test_styled_records_split_the_batch_but_unstyled_runs_still_coalesce(mocker):
    """
    Two unstyled runs separated by one styled record cost three prints, not
    four -- amortisation survives the presence of styling.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "priming")
    live.drain()

    for i in range(50):
        live.submit("Yosys.Synthesis", f"first-run-{i}")
    live.submit("Yosys.Synthesis", "the-warning", style="yellow")
    for i in range(50):
        live.submit("Yosys.Synthesis", f"second-run-{i}")

    spy = mocker.spy(console, "print")
    live.drain()

    assert spy.call_count == 3


def test_tool_output_is_never_interpreted_as_markup():
    """
    Raw subprocess output routinely contains square brackets. Rendering it with
    markup enabled would swallow them, or raise on a malformed tag.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")

    live.submit("Yosys.Synthesis", "[INFO] cell [0] mapped to [buf_2]")
    live.drain()

    assert "[INFO] cell [0] mapped to [buf_2]" in rendered(console)


def test_librelane_records_keep_their_markup():
    """
    LibreLane's own messages carry markup -- subprocess_exec.py wraps log paths
    in [repr.filename] and optionally [link=...]. Those must still render as
    styling rather than appearing literally.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")

    live.submit(
        "Yosys.Synthesis",
        "Logging subprocess to [repr.filename]'x.log'[/repr.filename]…",
        markup=True,
    )
    live.drain()

    output = rendered(console)
    assert "repr.filename" not in output
    assert "'x.log'" in output


def test_markup_boundaries_split_the_batch_but_runs_still_coalesce(mocker):
    """Tool output either side of an internal message still amortises."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "priming")
    live.drain()

    for i in range(50):
        live.submit("Yosys.Synthesis", f"tool-{i}")
    live.submit("Yosys.Synthesis", "internal message", markup=True)
    for i in range(50):
        live.submit("Yosys.Synthesis", f"more-tool-{i}")

    spy = mocker.spy(console, "print")
    live.drain()

    assert spy.call_count == 3


def test_drain_is_idempotent_when_nothing_is_pending(mocker):
    """An idle tick must not emit blank lines into the scrollback."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")

    spy = mocker.spy(console, "print")
    live.drain()
    live.drain()

    assert spy.call_count == 0
    assert rendered(console) == ""


def test_buffered_lines_are_rendered_without_an_explicit_drain():
    """
    The progress bar cannot be the scheduler: it is disabled under
    --hide-progress-bar, on a non-TTY, and in tests, which are precisely the
    high-output cases. Buffered output would then never reach the terminal.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, interval=0.01)
    try:
        live.register("Yosys.Synthesis")
        live.submit("Yosys.Synthesis", "pumped-line")

        deadline = time.monotonic() + 5.0
        while "pumped-line" not in rendered(console) and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        live.stop()

    assert "pumped-line" in rendered(console)


def test_no_pump_runs_until_something_is_submitted():
    """A library import must not spawn a thread that may never be needed."""
    from librelane.logging.live import LiveLog

    live = LiveLog(make_console(), interval=0.01)
    try:
        assert live.pump_running is False
    finally:
        live.stop()


def test_stop_drains_what_is_still_buffered():
    """Shutdown must not discard the tail of a run."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, interval=1000.0)
    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "tail-line")
    live.stop()

    assert "tail-line" in rendered(console)


def test_a_block_is_headed_by_the_step_it_came_from():
    """
    Replaces the console.rule() that Step.start printed directly. Printing it
    outside the buffer would place it wrongly relative to buffered output, the
    same ordering inversion batching otherwise avoids.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("synthesis-AREA 0", title="Yosys Synthesis (AREA 0)")

    live.submit("synthesis-AREA 0", "some output")
    live.drain()

    assert "Yosys Synthesis (AREA 0)" in rendered(console)


def test_header_is_not_repeated_while_one_step_keeps_producing():
    """
    A serial run drains ten times a second. Re-heading every tick would bury
    the output in headers.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis", title="Yosys Synthesis")

    for tick in range(5):
        live.submit("Yosys.Synthesis", f"tick-{tick}")
        live.drain()

    assert rendered(console).count("Yosys Synthesis") == 1


def test_header_returns_when_another_step_interrupts():
    """In a parallel run the reader must always know whose block this is."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("step-a", title="Step A")
    live.register("step-b", title="Step B")

    live.submit("step-a", "a1")
    live.drain()
    live.submit("step-b", "b1")
    live.drain()
    live.submit("step-a", "a2")
    live.drain()

    assert rendered(console).count("Step A") == 2


def test_unattributed_records_need_no_header():
    """Flow-level messages belong to no step and must not invent one."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)

    live.submit("", "Starting flow")
    live.drain()

    assert "Starting flow" in rendered(console)
    assert "─" not in rendered(console)


def test_last_line_tracks_the_most_recent_submission():
    """Feeds the per-step progress row, which reads it at the refresh tick."""
    from librelane.logging.live import LiveLog

    live = LiveLog(make_console(), autostart=False)
    live.register("Yosys.Synthesis")

    live.submit("Yosys.Synthesis", "3.2. Executing HIERARCHY pass")
    live.submit("Yosys.Synthesis", "3.3. Executing PROC pass")

    assert live.get("Yosys.Synthesis").last_line == "3.3. Executing PROC pass"


def test_last_line_survives_draining():
    """
    The row must keep showing the latest line between ticks, so draining the
    pending buffer cannot clear it.
    """
    from librelane.logging.live import LiveLog

    live = LiveLog(make_console(), autostart=False)
    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "3.3. Executing PROC pass")
    live.drain()

    assert live.get("Yosys.Synthesis").last_line == "3.3. Executing PROC pass"


def test_unregister_flushes_pending_lines(mocker):
    """
    A step that finishes between ticks must not take its last lines with it.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("Yosys.Synthesis")
    live.submit("Yosys.Synthesis", "the-final-line")

    live.unregister("Yosys.Synthesis")

    assert "the-final-line" in rendered(console)
    assert live.get("Yosys.Synthesis") is None


def test_lines_from_concurrent_steps_stay_in_their_own_blocks():
    """
    Interleaved arrival must not produce interleaved output. Each step's lines
    are emitted as a contiguous block so a parallel run stays readable.
    """
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    live.register("synthesis-AREA 0")
    live.register("synthesis-DELAY 2")

    live.submit("synthesis-AREA 0", "area-one")
    live.submit("synthesis-DELAY 2", "delay-one")
    live.submit("synthesis-AREA 0", "area-two")
    live.submit("synthesis-DELAY 2", "delay-two")
    live.drain()

    output = rendered(console)
    assert output.index("area-one") < output.index("area-two") < output.index(
        "delay-one"
    ) or output.index("delay-one") < output.index("delay-two") < output.index(
        "area-one"
    )


def test_every_line_of_every_concurrent_step_is_emitted():
    """No step loses output because another step was also producing."""
    from librelane.logging.live import LiveLog

    console = make_console()
    live = LiveLog(console, autostart=False)
    for step in ("step-a", "step-b", "step-c"):
        live.register(step)
    for i in range(100):
        for step in ("step-a", "step-b", "step-c"):
            live.submit(step, f"{step}-line-{i}")
    live.drain()

    output = rendered(console)
    for i in range(100):
        for step in ("step-a", "step-b", "step-c"):
            assert f"{step}-line-{i}" in output
