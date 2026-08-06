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
"""The metric and report procs of ``common/io.tcl``, in a bare interpreter.

``write_metric_*`` speaks two channels: a JSON record appended to the
``_LLN_METRICS_JSONL`` sidecar, and a ``Writing metric`` echo for the log.
While a ``lln_report_begin`` redirect is open the echo is suppressed — the
redirect captures ``puts``, so an echo would land inside the report file
(observed as ``Writing metric`` lines inside signoff timing reports before
this was pinned). The sidecar write must happen either way.
"""

import json
import pathlib
import tkinter

import pytest

IO_TCL = (
    pathlib.Path(__file__).parent.parent.parent
    / "librelane"
    / "scripts"
    / "openroad"
    / "common"
    / "io.tcl"
)


@pytest.fixture
def io_interp(tmp_path):
    interp = tkinter.Tcl()
    output = []

    # Capture stdout puts only; channel writes (the sidecar's `puts $f`)
    # must keep reaching their file.
    interp.eval("rename puts _lln_real_puts")
    interp.createcommand("_lln_capture", lambda line: output.append(line))
    interp.eval(
        "proc puts {args} {"
        "  if {[llength $args] == 1} { _lln_capture [lindex $args 0] }"
        "  else { _lln_real_puts {*}$args }"
        "}"
    )
    # io.tcl's own top-level sources need a live OpenROAD environment;
    # nothing under test here depends on them.
    interp.eval("rename source {}")
    interp.createcommand("source", lambda path: None)
    interp.eval("set ::env(_TCL_ENV_IN) /dev/null")
    interp.eval("set ::env(SCRIPTS_DIR) /dev/null")
    # Standalone-OpenSTA branch of the report redirect: no utl:: namespace,
    # and the redirect commands themselves are not what is under test.
    interp.eval("namespace eval sta {}")
    interp.createcommand("sta::redirect_file_begin", lambda path: None)
    interp.createcommand("sta::redirect_file_end", lambda: None)

    sidecar = tmp_path / "step.metrics.jsonl"
    interp.eval(f"set ::env(_LLN_METRICS_JSONL) {sidecar}")
    interp.eval(f"set ::env(_LLN_REPORT_DIR) {tmp_path / 'reports'}")
    interp.eval(IO_TCL.read_text(encoding="utf8"))

    return interp, output, sidecar


def sidecar_records(sidecar):
    return [
        json.loads(line) for line in sidecar.read_text(encoding="utf8").splitlines()
    ]


def test_write_metric_echoes_outside_reports(io_interp):
    interp, output, sidecar = io_interp

    interp.eval('write_metric_int "design__instance__count" 42')

    assert "Writing metric design__instance__count: 42" in output
    assert sidecar_records(sidecar) == [
        {"name": "design__instance__count", "value": 42}
    ]


def test_write_metric_inside_report_writes_sidecar_but_not_the_report(io_interp):
    interp, output, sidecar = io_interp

    interp.eval('lln_report_begin "corner/ws.max.rpt"')
    interp.eval('write_metric_num "timing__setup__ws__corner:nom" 4.25')
    interp.eval("lln_report_end")
    interp.eval('write_metric_int "after__report" 1')

    assert not any("timing__setup__ws" in line for line in output)
    assert "Writing metric after__report: 1" in output
    assert sidecar_records(sidecar) == [
        {"name": "timing__setup__ws__corner:nom", "value": 4.25},
        {"name": "after__report", "value": 1},
    ]
