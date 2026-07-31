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

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _xor_argv(mocker, mock_config, **overrides):
    """Runs KLayout.XOR against a stubbed subprocess and returns its argv."""
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps.klayout.checks import XOR

    instance = XOR(config=mock_config, state_in=State(), **overrides)
    instance.step_dir = "/cwd/step"

    state_in = State(
        {
            DesignFormat.MAG_GDS: Path("/cwd/magic.gds"),
            DesignFormat.KLAYOUT_GDS: Path("/cwd/klayout.gds"),
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
