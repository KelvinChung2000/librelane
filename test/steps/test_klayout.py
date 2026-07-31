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


def _stream_out_argv(mocker, **config_overrides):
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps.klayout.views import StreamOut

    # A real instance would need a PDK supplying every KLAYOUT_* variable; the
    # run() path under test reads only these six.
    settings = {
        "PDK": "dummy",
        "DESIGN_NAME": "whatever",
        "KLAYOUT_CONFLICT_RESOLUTION": "RenameCell",
        "KLAYOUT_ADD_ISOSUB": False,
        "ISOSUB_LAYER": None,
        "PRIMARY_GDSII_STREAMOUT_TOOL": "magic",
    }
    settings.update(config_overrides)

    instance = object.__new__(StreamOut)
    instance.config = StreamOut.Config.model_construct(**settings)
    instance.step_dir = "/cwd/streamout"
    mocker.patch.object(instance, "get_cli_args", return_value=[])
    run_pya_script = mocker.patch.object(instance, "run_pya_script")

    state_in = State({DesignFormat.DEF: Path("/cwd/design.def")})
    instance.run(state_in)

    return [str(arg) for arg in run_pya_script.call_args.args[0]]


def test_isosub_is_not_drawn_by_default(mocker):
    argv = _stream_out_argv(mocker)

    assert "--isosub-layer" not in argv


def test_isosub_layer_and_datatype_are_passed_separately(mocker):
    """A single joined argument was one parse away from the wrong datatype."""
    argv = _stream_out_argv(mocker, KLAYOUT_ADD_ISOSUB=True, ISOSUB_LAYER=(81, 53))

    assert argv[argv.index("--isosub-layer") + 1] == "81"
    assert argv[argv.index("--isosub-datatype") + 1] == "53"


def test_isosub_without_a_pdk_layer_is_an_error(mocker):
    """Warning and streaming out anyway would ship a GDS silently missing the
    layer the caller asked for."""
    from librelane.steps.step import StepError

    with pytest.raises(StepError, match="ISOSUB_LAYER"):
        _stream_out_argv(mocker, KLAYOUT_ADD_ISOSUB=True)
