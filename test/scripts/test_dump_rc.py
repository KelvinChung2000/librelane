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
"""``dump_rc.tcl`` run against the stubs in ``conftest.py``.

The step exists so that somebody debugging RC estimation can see what the
technology LEF holds and what LibreLane made of it. A report that silently
repeats another one under a title claiming to show something else defeats that.
"""

import itertools
import re

import pytest


@pytest.fixture
def rc_reports(openroad_stubs, unit_systems):
    """The reports ``dump_rc.tcl`` emits, under the units signoff pins."""
    stubs = openroad_stubs(unit_systems[0])
    stubs.interpreter.eval("set ::env(_LAYER_RC_0) {nom_tt met1 0.1 0.2}")
    stubs.interpreter.eval("set ::env(_VIA_R_0) {nom_tt via1 0.5}")
    stubs.stub_io_tcl()
    stubs.capture_output()
    stubs.source("dump_rc.tcl")
    return stubs.reports()


def untitled(lines):
    """A report's content, less the one line naming it."""
    return [line for line in lines if not re.fullmatch(r"== .+ ==", line)]


def section(lines, heading):
    body = lines[lines.index(heading) + 1 :]
    end = next(
        (index for index, line in enumerate(body) if line.startswith("=== ")),
        len(body),
    )
    return body[:end]


def row(lines, name):
    [fields] = [line.split() for line in lines if line.split()[:1] == [name]]
    return [float(field) for field in fields[2:]]


def test_no_report_repeats_another_under_a_different_title(rc_reports):
    """``set_layer_rc`` only writes the odb layer store when ``-corner`` is
    absent, and ``set_rc.tcl`` always passes it. So a second pass over
    ``est::dblayer_wire_rc`` after sourcing it cannot show anything the first
    pass did not, whatever the title says."""
    duplicates = [
        (left, right)
        for left, right in itertools.combinations(sorted(rc_reports), 2)
        if untitled(rc_reports[left]) == untitled(rc_reports[right])
    ]

    assert duplicates == []


def test_the_reports_are_the_ones_the_step_documents(rc_reports):
    assert sorted(rc_reports) == ["resizer_values_after.rpt", "tlef_values.rpt"]


def test_the_overrides_are_visible_in_the_per_corner_report(rc_reports):
    """Which is the report to read, and the one place the applied values show
    up. 0.1 kOhm/um and 0.2 pF/um for the corner LAYERS_RC named, and the
    technology LEF's 0.15 kOhm/um and 0.3 pF/um for the corner it did not."""
    resizer = rc_reports["resizer_values_after.rpt"]

    assert row(section(resizer, "=== Corner nom_tt ==="), "met1") == pytest.approx(
        [0.1, 0.2]
    )
    assert row(section(resizer, "=== Corner nom_ss ==="), "met1") == pytest.approx(
        [0.15, 0.3]
    )
    assert row(rc_reports["tlef_values.rpt"], "met1") == pytest.approx([0.15, 0.3])
