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
import pathlib

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


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


def _xor_argv(mocker, mock_config, **overrides):
    """Runs KLayout.XOR against a stubbed subprocess and returns its argv."""
    from librelane.state import DesignFormat, State
    from librelane.steps.klayout.checks import XOR

    instance = XOR(config=mock_config, state_in=State(), **overrides)
    instance.step_dir = "/cwd/step"

    state_in = State(
        {
            DesignFormat.MAG_GDS: pathlib.Path("/cwd/magic.gds"),
            DesignFormat.KLAYOUT_GDS: pathlib.Path("/cwd/klayout.gds"),
        }
    )
    run_subprocess = mocker.patch.object(
        XOR, "run_subprocess", return_value={"generated_metrics": {}}
    )
    instance.run(state_in)

    return [str(arg) for arg in run_subprocess.call_args.args[0]]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_xor_does_not_write_a_gds_by_default(mocker, mock_config):
    argv = _xor_argv(mocker, mock_config)

    assert "--gds-output" not in argv


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_xor_writes_a_gds_when_asked(mocker, mock_config):
    """Issue 692: the XOR differences were only ever available as a marker
    database, which cannot be opened as a layout or diffed further."""
    argv = _xor_argv(mocker, mock_config, KLAYOUT_XOR_WRITE_GDS=True)

    assert argv[argv.index("--gds-output") + 1].endswith("/cwd/step/xor.gds")


def test_xor_gds_is_off_by_default():
    from librelane.steps.klayout.checks import XOR

    assert XOR.Config.model_fields["KLAYOUT_XOR_WRITE_GDS"].default is False


def _cli_args(mock_config, **overrides):
    """get_cli_args() off a bare KLayoutStep, which is where --lym is decided."""
    from librelane.state import State
    from librelane.steps.klayout.base import KLayoutStep

    class Probe(KLayoutStep):
        id = "Test.KLayoutProbe"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    instance = Probe(config=mock_config, state_in=State(), **overrides)
    instance.step_dir = "/cwd/step"
    return [str(arg) for arg in instance.get_cli_args()]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_def_layer_map_is_passed_when_the_pdk_has_one(mock_config):
    args = _cli_args(mock_config)

    assert args[args.index("--lym") + 1].endswith("dummy.map")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_def_layer_map_is_omitted_when_the_pdk_has_none(mock_config):
    """Issue 999: asap7 embeds the LEF/DEF mapping in its .lyt. Passing an
    empty --lym would not do -- assigning "" to lefdef_config.map_file clears
    the mapping tech.load() brought in -- so the flag has to be absent."""
    args = _cli_args(mock_config, KLAYOUT_DEF_LAYER_MAP=None)

    assert "--lym" not in args
    # The two views that are still required must survive.
    assert "--lyt" in args
    assert "--lyp" in args


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_def_layer_map_is_optional_in_the_schema():
    from librelane.steps.klayout.base import KLayoutStep

    field = KLayoutStep.Config.model_fields["KLAYOUT_DEF_LAYER_MAP"]

    assert field.default is None
    assert not field.is_required()


# Upstream PRs 964 and 973: KLayout.Render required a DEF it does not need,
# and then erred out when handed neither of its two acceptable inputs.


def _render(mocker, views=None):
    """Returns (argv, views_updates) for a Render run over the given views."""
    from librelane.state import State
    from librelane.steps.klayout.views import Render

    instance = object.__new__(Render)
    instance.config = Render.Config.model_construct(
        PDK="dummy",
        DESIGN_NAME="whatever",
        KLAYOUT_RENDER_GRID_VISBLE=False,
        KLAYOUT_RENDER_SHOW_RULER=False,
        KLAYOUT_RENDER_BACKGROUND_COLOR="white",
        KLAYOUT_RENDER_TEXT_VISIBLE=False,
        KLAYOUT_RENDER_RESOLUTION=1000,
        KLAYOUT_RENDER_OVERSAMPLING=0,
    )
    instance.step_dir = "/cwd/render"
    mocker.patch.object(instance, "get_cli_args", return_value=[])
    run_pya_script = mocker.patch.object(instance, "run_pya_script")

    views_updates, _ = instance.run(State(views or {}))

    argv = (
        [str(arg) for arg in run_pya_script.call_args.args[0]]
        if run_pya_script.called
        else []
    )
    return argv, views_updates


def test_render_takes_both_its_inputs_optionally():
    """Neither view is required: a DEF-only state and a GDS-only state are both
    renderable, so demanding either aborts a flow that could have run."""
    from librelane.state import DesignFormat
    from librelane.steps.klayout.views import Render

    optional = {view.id: view.optional for view in Render.inputs}

    assert optional == {DesignFormat.DEF.id: True, DesignFormat.GDS.id: True}


def test_render_runs_on_a_gds_only_state(mocker):
    from librelane.common import Path
    from librelane.state import DesignFormat

    argv, views_updates = _render(mocker, {DesignFormat.GDS: Path("/cwd/x.gds")})

    assert "/cwd/x.gds" in argv
    assert DesignFormat.KLAYOUT_RENDER in views_updates


def test_render_prefers_the_gds_over_the_def(mocker):
    from librelane.common import Path
    from librelane.state import DesignFormat

    argv, _ = _render(
        mocker,
        {
            DesignFormat.DEF: Path("/cwd/x.def"),
            DesignFormat.GDS: Path("/cwd/x.gds"),
        },
    )

    assert "/cwd/x.gds" in argv
    assert "/cwd/x.def" not in argv


def test_render_with_neither_input_does_nothing(mocker):
    """Both inputs are declared optional, so their absence cannot be an error."""
    argv, views_updates = _render(mocker)

    assert argv == []
    assert views_updates == {}


def test_render_png_returns_none_when_there_was_nothing_to_render(mocker):
    """Toolbox.render_png used to read a fixed path out of the temporary
    directory, which no longer exists when Render declines to run."""
    from librelane.common import Toolbox
    from librelane.config import Config
    from librelane.state import State

    toolbox = object.__new__(Toolbox)
    mocker.patch("librelane.steps.klayout.views.Render.__init__", return_value=None)
    started = mocker.patch(
        "librelane.steps.klayout.views.Render.start", return_value=State()
    )

    assert toolbox.render_png(Config({"DESIGN_NAME": "whatever"}), State()) is None
    assert started.called


def test_render_png_gives_each_render_its_own_step_id(mocker):
    """
    One Toolbox is shared by a whole flow, and under the workflow engine
    several jobs render at once. The logging layer keys a running step on its
    id -- the loguru filter behind step.log, LiveLog's registry, the progress
    row -- so two concurrent renders under a bare class id would write into
    each other's step.log and unregister each other's display. Every other
    site that constructs a step per job was given a per-instance id; this one
    was missed.
    """
    from librelane.common import Toolbox
    from librelane.config import Config
    from librelane.state import State

    toolbox = object.__new__(Toolbox)
    constructed = mocker.patch(
        "librelane.steps.klayout.views.Render.__init__", return_value=None
    )
    mocker.patch("librelane.steps.klayout.views.Render.start", return_value=State())

    config = Config({"DESIGN_NAME": "whatever"})
    toolbox.render_png(config, State())
    toolbox.render_png(config, State())

    ids = [call.kwargs.get("id") for call in constructed.call_args_list]
    assert len(ids) == 2
    assert all(name is not None for name in ids), "no per-instance id was given"
    assert ids[0] != ids[1]
    assert all(name.startswith("KLayout.Render") for name in ids)
