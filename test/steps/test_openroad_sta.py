# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import pathlib
import textwrap
import tkinter

import pytest

pytestmark = pytest.mark.all

_CORNER_TCL = (
    pathlib.Path(__file__).parent.parent.parent
    / "librelane"
    / "scripts"
    / "openroad"
    / "sta"
    / "corner.tcl"
)


def _fmax_block():
    """The maximum-frequency calculation, lifted out of corner.tcl.

    The rest of the script needs a live OpenSTA, but this block only reads the
    clock list and the setup worst slack, so it can be run on its own against
    stubs.

    The block sits inside the per-corner loop, so it is indented. It is found
    by its first and last lines at whatever indentation it currently has, and
    dedented before being handed to the interpreter.
    """
    lines = _CORNER_TCL.read_text(encoding="utf8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip() == "set clocks [all_clocks]"
    )
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    end = next(i for i, line in enumerate(lines[start:], start) if line == indent + "}")
    return textwrap.dedent("\n".join(lines[start : end + 1]))


def _run_fmax(clock_periods, setup_ws):
    """Run the block with the given clocks, and return the metrics it wrote."""
    written = {}
    interpreter = tkinter.Tcl()
    interpreter.createcommand("all_clocks", lambda: tuple(map(str, clock_periods)))
    # A clock is stubbed as its own period, so get_property just echoes it.
    interpreter.createcommand("get_property", lambda clock, prop: clock)
    interpreter.createcommand(
        "write_metric_num", lambda name, value: written.__setitem__(name, float(value))
    )
    interpreter.eval(f"set corner_name nom_tt_025C_1v80\nset ws {setup_ws}")
    interpreter.eval(_fmax_block())
    return written


def test_fmax_is_the_clock_period_less_the_setup_slack():
    written = _run_fmax(clock_periods=[10.0], setup_ws=6.0)

    assert written == {"timing__clock__fmax__corner:nom_tt_025C_1v80": 250.0}


def test_fmax_is_not_reported_when_the_design_has_several_clocks():
    """The setup worst slack is design-wide, so there is no one period to
    subtract it from."""
    written = _run_fmax(clock_periods=[10.0, 20.0], setup_ws=6.0)

    assert written == {}


def test_fmax_is_not_reported_when_there_are_no_timing_paths():
    """worst_slack reports infinity, which would make the period negative."""
    written = _run_fmax(clock_periods=[10.0], setup_ws=1e30)

    assert written == {}


def test_fmax_aggregates_to_the_slowest_corner():
    """A design is only as fast as its worst corner, so the overall figure is
    the smallest of the per-corner ones."""
    from librelane.common.metrics import aggregate_metrics

    aggregated = aggregate_metrics(
        {
            "timing__clock__fmax__corner:nom_tt_025C_1v80": 248.43,
            "timing__clock__fmax__corner:nom_ss_100C_1v60": 170.23,
            "timing__clock__fmax__corner:nom_ff_n40C_1v95": 300.03,
        }
    )

    assert aggregated["timing__clock__fmax"] == 170.23


def test_fmax_is_green_when_the_target_is_met():
    from librelane.steps.openroad.sta import format_frequency_against_target

    assert format_frequency_against_target(248.43, 100.0) == "[green]248.4300"


def test_fmax_is_red_when_the_target_is_missed():
    """The metric stays a true frequency; the table decides the colour by
    comparing it against 1/CLOCK_PERIOD."""
    from librelane.steps.openroad.sta import format_frequency_against_target

    assert format_frequency_against_target(83.5, 100.0) == "[red]83.5000"


def test_fmax_is_blank_when_the_corner_reported_none():
    from librelane.steps.openroad.sta import format_frequency_against_target

    assert format_frequency_against_target(None, 100.0) == "[gray]?"
