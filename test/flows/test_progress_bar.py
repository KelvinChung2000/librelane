import io

import pytest
from rich.console import Console


pytestmark = pytest.mark.all


@pytest.fixture
def real_progress(mocker):
    """
    Undoes the suite-wide MockProgress so the actual Rich bar is exercised.
    """
    from librelane.flows import flow as flow_module

    import rich.progress

    mocker.patch.object(flow_module, "Progress", rich.progress.Progress)
    return flow_module


def make_bar(flow_module, live):
    console = Console(file=io.StringIO(), width=160, force_terminal=True)
    bar = flow_module.FlowProgressBar("Classic", live=live, console=console)
    bar.start()
    return bar, console


@pytest.fixture
def live():
    from librelane.logging.live import LiveLog

    console = Console(file=io.StringIO(), width=160, force_terminal=True)
    return LiveLog(console, autostart=False)


def test_a_running_step_gets_its_own_row(real_progress, live):
    """
    The bar had exactly one task, so a flow fanning out nine steps showed
    "Stage 1, 0/1" for the whole run with no sign of what was in flight.
    """
    bar, _ = make_bar(real_progress, live)
    try:
        live.register("synthesis-AREA 0", title="Synthesis (AREA 0)")
        bar.sync_step_rows()

        assert "synthesis-AREA 0" in bar.step_row_ids
    finally:
        bar.end()


def test_every_concurrent_step_gets_a_row(real_progress, live):
    bar, _ = make_bar(real_progress, live)
    try:
        for strategy in ("AREA 0", "DELAY 2", "DELAY 4"):
            live.register(f"synthesis-{strategy}")
        bar.sync_step_rows()

        assert len(bar.step_row_ids) == 3
    finally:
        bar.end()


def test_a_finished_step_loses_its_row(real_progress, live):
    bar, _ = make_bar(real_progress, live)
    try:
        live.register("synthesis-AREA 0")
        bar.sync_step_rows()
        live.unregister("synthesis-AREA 0")
        bar.sync_step_rows()

        assert bar.step_row_ids == {}
    finally:
        bar.end()


def test_a_row_shows_the_step_s_latest_line(real_progress, live):
    """
    The suppressed tool chatter becomes the liveness signal: a row that has been
    spinning for eight minutes should still say what the tool is doing.
    """
    bar, console = make_bar(real_progress, live)
    try:
        live.register("synthesis-AREA 0")
        live.submit("synthesis-AREA 0", "3.3. Executing PROC pass")
        bar.sync_step_rows()
        bar.refresh()

        assert "Executing PROC pass" in console.file.getvalue()
    finally:
        bar.end()


def test_rows_do_not_require_the_producer_to_update_them(real_progress, live, mocker):
    """
    The row text is pulled by Rich's own refresh, so a tool emitting 100k lines
    costs no progress-bar work at all. Producers calling update() per line would
    put the bottleneck straight back.
    """
    bar, _ = make_bar(real_progress, live)
    try:
        live.register("synthesis-AREA 0")
        bar.sync_step_rows()

        spy = mocker.spy(bar._FlowProgressBar__progress, "update")
        for i in range(1000):
            live.submit("synthesis-AREA 0", f"line-{i}")

        assert spy.call_count == 0
    finally:
        bar.end()


def test_the_overall_flow_task_still_tracks_stages(real_progress, live):
    """The existing single-task behaviour must survive the addition of rows."""
    bar, _ = make_bar(real_progress, live)
    try:
        bar.set_max_stage_count(4)
        bar.start_stage("Synthesis")
        bar.end_stage()

        assert bar.get_ordinal_prefix() == "2-"
    finally:
        bar.end()
