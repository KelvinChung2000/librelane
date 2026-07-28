# Copyright 2023 Efabless Corporation
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
import os
import tkinter

import pytest
from pyfakefs.fake_filesystem_unittest import Patcher

pytestmark = pytest.mark.all


@pytest.fixture
def _mock_fs():
    with Patcher() as patcher:
        patcher.fs.create_dir("/cwd")
        os.chdir("/cwd")
        yield


def _tcl_scalar(tcl_value: str) -> str:
    from librelane.common import TclUtils

    result = TclUtils.split(tcl_value)
    assert len(result) == 1
    return result[0]


def test_escape():
    from librelane.common import TclUtils

    values = [
        "ringo",
        "r ingo",
        "[expr ringo]",
        "[expr $ringo]",
        "[expr \\$ringo]",
        "semi; [expr 1]",
        "line one\nline two",
        "unmatched {",
        "",
        " ",
    ]
    for value in values:
        assert _tcl_scalar(TclUtils.escape(value)) == value


@pytest.mark.usefixtures("_mock_fs")
def test_join():
    from librelane.common import TclUtils

    very_wild_list = [
        "{}{}{{}}{}{}{}{}{}{}{",
        "dollar\\ sign",
        "actual dollar $ign",
        '[exec {touch "need legal advice?"}]',
        '\\[exec {touch "better call saul"}]',
    ]

    very_wild_list_escaped = TclUtils.join(very_wild_list)
    assert TclUtils.split(very_wild_list_escaped) == very_wild_list

    interpreter = tkinter.Tcl()
    interpreter.eval(
        f"""
        set very_wild_variable [list {very_wild_list_escaped}]
        set length [llength $very_wild_variable]
        foreach i $very_wild_variable {{
            puts $i
        }}
        """
    )

    assert os.listdir("/cwd") == [], "Arbitrary code execution"
    assert interpreter.getvar("length") == 5, "Tcl list not escaped properly"


@pytest.mark.usefixtures("_mock_fs")
def test_split():
    from librelane.common import TclUtils

    result = TclUtils.split(
        r"key1 {value with spaces} key2 {[exec {touch should_not_exist}]}"
    )

    assert result == [
        "key1",
        "value with spaces",
        "key2",
        "[exec {touch should_not_exist}]",
    ]
    assert os.listdir("/cwd") == [], "Tcl list splitting evaluated commands"

    with pytest.raises(ValueError, match="Invalid Tcl list"):
        TclUtils.split("{unmatched")


def test_eval_env():
    from librelane.common import TclUtils

    env_backup = os.environ.copy()

    result = TclUtils._eval_env(
        {"DESIGN_DIR": "/cwd", "PDK": "sky130A", "TMPDIR": "/cwd"},
        """
        if { ![info exists ::env(STD_CELL_LIBRARY)] } {
            set ::env(STD_CELL_LIBRARY) "sky130_fd_sc_hd"
        }
        if { $::env(STD_CELL_LIBRARY) == "sky130_fd_sc_hd" } {
            set ::env(WHATEVER) 1
        } else {
            set ::env(WHATEVER) 0
        }
        """,
    )

    expected = {
        "DESIGN_DIR": "/cwd",
        "PDK": "sky130A",
        "TMPDIR": "/cwd",
        "WHATEVER": "1",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
    }

    assert result == expected, "conditional evaluation test failed"

    assert os.environ == env_backup, "_eval_env leaked environment changes"

    os.environ["STD_CELL_LIBRARY"] = "sky130_fd_sc_hd"

    TclUtils._eval_env(
        {},
        """
        set ::env(STD_CELL_LIBRARY) "sky130_fd_sc_hs"
        """,
    )

    assert os.getenv("STD_CELL_LIBRARY") == "sky130_fd_sc_hd", (
        "env_from_tcl unset a previously set environment variable"
    )

    del os.environ["STD_CELL_LIBRARY"]

    assert result == expected


def test_eval_env_preserves_structured_inputs_and_captures_nested_dicts():
    from librelane.common import TclUtils

    existing_lib = {"nom_*": ["a.lib", "b with spaces.lib"]}
    result = TclUtils._eval_env(
        {"LIB": existing_lib},
        """
        set ::env(LAYERS_RC) [dict create]
        dict set ::env(LAYERS_RC) nom_* met1 res 0.1
        dict set ::env(LAYERS_RC) nom_* met1 cap 0.2
        """,
    )

    assert result["LIB"] == existing_lib

    corners = TclUtils.split(result["LAYERS_RC"])
    assert corners[0] == "nom_*"
    layers = TclUtils.split(corners[1])
    assert layers[0] == "met1"
    values = TclUtils.split(layers[1])
    assert dict(zip(values[::2], values[1::2])) == {"res": "0.1", "cap": "0.2"}
