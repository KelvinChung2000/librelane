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


def _stream_out(mocker, incoming_gds=None, **config_overrides):
    """Returns (argv, views_updates) for a StreamOut run."""
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

    views = {DesignFormat.DEF: Path("/cwd/design.def")}
    if incoming_gds is not None:
        views[DesignFormat.GDS] = Path(incoming_gds)
    mocker.patch("librelane.steps.klayout.views.shutil.copy")

    views_updates, _ = instance.run(State(views))

    argv = [str(arg) for arg in run_pya_script.call_args.args[0]]
    return argv, views_updates


def test_isosub_is_not_drawn_by_default(mocker):
    argv, _ = _stream_out(mocker)

    assert "--isosub-layer" not in argv


def test_isosub_layer_and_datatype_are_passed_separately(mocker):
    """A single joined argument was one parse away from the wrong datatype."""
    argv, _ = _stream_out(mocker, KLAYOUT_ADD_ISOSUB=True, ISOSUB_LAYER=(81, 53))

    assert argv[argv.index("--isosub-layer") + 1] == "81"
    assert argv[argv.index("--isosub-datatype") + 1] == "53"


def test_isosub_without_a_pdk_layer_is_an_error(mocker):
    """Warning and streaming out anyway would ship a GDS silently missing the
    layer the caller asked for."""
    from librelane.steps.step import StepError

    with pytest.raises(StepError, match="ISOSUB_LAYER"):
        _stream_out(mocker, KLAYOUT_ADD_ISOSUB=True)


def test_non_primary_streamout_writes_the_gds_when_nothing_else_has(mocker):
    """A custom flow running only KLayout.StreamOut on a PDK whose primary tool
    is magic produced no `gds` view at all. https://github.com/librelane/librelane/issues/683"""
    from librelane.state import DesignFormat

    _, views_updates = _stream_out(mocker, PRIMARY_GDSII_STREAMOUT_TOOL="magic")

    assert DesignFormat.GDS in views_updates


def test_non_primary_streamout_leaves_an_existing_gds_alone(mocker):
    """Magic is primary and already wrote it; KLayout must not clobber it."""
    from librelane.state import DesignFormat

    _, views_updates = _stream_out(
        mocker,
        incoming_gds="/cwd/from-magic.gds",
        PRIMARY_GDSII_STREAMOUT_TOOL="magic",
    )

    assert DesignFormat.GDS not in views_updates


def test_primary_streamout_overwrites_an_existing_gds(mocker):
    """The primary tool wins even if a non-primary one got there first."""
    from librelane.state import DesignFormat

    _, views_updates = _stream_out(
        mocker,
        incoming_gds="/cwd/from-magic.gds",
        PRIMARY_GDSII_STREAMOUT_TOOL="klayout",
    )

    assert DesignFormat.GDS in views_updates
