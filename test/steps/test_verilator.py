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
import os

import pytest

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _lint_command(mock_config, mocker, **overrides):
    """Run Verilator.Lint with the tool stubbed out; return the argv it built."""
    from librelane.state import State
    from librelane.steps.verilator import Lint

    instance = Lint(config=mock_config, state_in=State(), **overrides)

    # These two are flow-wide PDK variables, which the mocked variable set
    # replaces; supply them so run() can read them off the model.
    raw = instance.config.to_raw_dict()
    for name in ("CELL_VERILOG_MODELS", "PAD_VERILOG_MODELS", "EXTRA_VERILOG_MODELS"):
        raw.setdefault(name, None)
    instance.config = type(instance.config).model_construct(**raw)

    instance.step_dir = "/cwd/step"
    os.makedirs(instance.step_dir, exist_ok=True)

    mocker.patch.object(instance, "toolbox", mocker.MagicMock())
    instance.toolbox.get_macro_views_by_priority.return_value = []

    log_path = os.path.join(instance.step_dir, "verilator-lint.log")
    with open(log_path, "w") as f:
        f.write("")
    mocker.patch.object(instance, "get_log_path", return_value=log_path)

    run_subprocess = mocker.patch.object(
        instance,
        "run_subprocess",
        return_value={"returncode": 0, "generated_metrics": {}},
    )

    instance.run(State())

    run_subprocess.assert_called_once()
    return [str(arg) for arg in run_subprocess.call_args.args[0]]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_linter_arguments_forwarded(mock_config, mocker):
    argv = _lint_command(
        mock_config,
        mocker,
        LINTER_ARGUMENTS=["--no-timing", "-Wno-WIDTHEXPAND"],
    )

    assert "--no-timing" in argv
    assert "-Wno-WIDTHEXPAND" in argv


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_linter_arguments_win_over_defaults(mock_config, mocker):
    """A user argument must come after the ones LibreLane builds, so it overrides."""
    argv = _lint_command(mock_config, mocker, LINTER_ARGUMENTS=["--no-timing"])

    assert argv.index("--no-timing") > argv.index("--Wall")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_no_linter_arguments_by_default(mock_config, mocker):
    argv = _lint_command(mock_config, mocker)

    assert "--no-timing" not in argv
    assert "None" not in argv
