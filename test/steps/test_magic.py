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
import pytest

pytestmark = pytest.mark.all


def test_write_lef_is_pinonly_by_default():
    """A LEF pin larger than the DEF pin fails downstream pin-size prechecks."""
    from librelane.steps.magic import WriteLEF

    assert WriteLEF.Config.model_fields["MAGIC_WRITE_LEF_PINONLY"].default is True


def test_isosub_is_off_by_default():
    from librelane.steps.magic import StreamOut

    assert StreamOut.Config.model_fields["MAGIC_ADD_ISOSUB"].default is False


def test_mag_gds_reads_the_isosub_variable_it_is_gated_on():
    """TclStep puts every config variable in the environment, so a rename on
    either side is only caught by comparing the two."""
    from importlib.resources import files

    from librelane.steps.magic import StreamOut

    script = files("librelane").joinpath("scripts", "magic", "def", "mag_gds.tcl")

    assert "$::env(MAGIC_ADD_ISOSUB)" in script.read_text()
    assert "MAGIC_ADD_ISOSUB" in StreamOut.Config.model_fields


def test_filler_script_uses_the_flow_interpreter(mocker):
    """Issue 45k: Magic.Filler hardcoded "python3" for its own filler
    script, which is not necessarily the interpreter running the flow."""
    import sys
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps.magic import Filler

    settings = {
        "PDK": "dummy",
        "PDK_ROOT": "/pdk",
        "DESIGN_NAME": "whatever",
        "MAGIC_FILLER_SCRIPT": Path("/pdk/dummy/libs.tech/magic/filler.py"),
        "MAGIC_FILLER_OPTIONS": None,
    }

    instance = object.__new__(Filler)
    instance.config = Filler.Config.model_construct(**settings)
    instance.step_dir = "/cwd/filler"
    run_subprocess = mocker.patch.object(instance, "run_subprocess", return_value={})

    state_in = State({DesignFormat.GDS: Path("/cwd/in.gds")})
    instance.run_generic(state_in)

    # run_generic makes two run_subprocess calls: the filler script itself,
    # then klayout to combine the fill and layout. The first is the one that
    # used to hardcode "python3".
    argv = [str(arg) for arg in run_subprocess.call_args_list[0].args[0]]
    assert argv[0] == sys.executable
