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
from pathlib import Path

import pytest

from librelane.cli import steps as steps_cli
from librelane.cli.metrics import parse_table_verbosity
from librelane.common.metrics.util import TableVerbosity


pytestmark = pytest.mark.all


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("none", TableVerbosity.NONE),
        ("ALL", TableVerbosity.ALL),
        ("2", TableVerbosity.WORSE),
    ],
)
def test_parse_table_verbosity(value: str, expected: TableVerbosity):
    assert parse_table_verbosity(value) is expected


def test_create_reproducible_uses_explicit_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = tmp_path / "config.json"
    state_in = tmp_path / "state_in.json"
    output = tmp_path / "reproducible"
    calls = {}

    class FakeStep:
        def create_reproducible(self, output, include_pdk, *, flatten):
            calls["create"] = (output, include_pdk, flatten)

    def fake_load(id, config, state_in, pdk_root=None):
        calls["load"] = (config, state_in)
        return FakeStep()

    monkeypatch.setattr(steps_cli, "load_step_from_inputs", fake_load)

    steps_cli.create_reproducible(
        step_dir_arg=None,
        output=output,
        step_dir=None,
        id=None,
        config=config,
        state_in=state_in,
        include_pdk=False,
        flatten=True,
    )

    assert calls["load"] == (config, state_in)
    assert calls["create"] == (output, False, True)


# --- filter_env_for_script (#599 prep) ---


def _filter(found_env, current_env=None, **kwargs):
    from librelane.cli.steps import filter_env_for_script

    return filter_env_for_script(
        found_env,
        current_env or {},
        already_set=kwargs.pop("already_set", set()),
        canon_scripts_dir=kwargs.pop("canon_scripts_dir", "/install/scripts"),
        target_scripts_dir=kwargs.pop("target_scripts_dir", "./scripts"),
    )


def test_ejected_env_stringifies_path_objects(tmp_path):
    """Steps put path objects into the environment unstringified -- TECH_LEF
    and PDK_ROOT among them -- and the filter then does string work on them.
    A pathlib.Path used to reach .startswith and raise AttributeError."""
    import pathlib

    from librelane.common import Path

    real = tmp_path / "tech.lef"
    real.write_text("")

    result = _filter(
        {
            "COMMON_PATH": Path(str(real)),
            "PATHLIB_PATH": pathlib.Path(real),
            "PLAIN": "unchanged",
        }
    )

    assert result["COMMON_PATH"] == str(real)
    assert result["PATHLIB_PATH"] == str(real)
    assert result["PLAIN"] == "unchanged"
    assert all(isinstance(value, str) for value in result.values())


def test_ejected_env_drops_entries_the_ambient_environment_already_has(tmp_path):
    """The skip compares against os.environ, which holds str. A path object
    that did not compare equal would be needlessly re-emitted."""
    import pathlib

    real = tmp_path / "pdk"
    real.mkdir()

    result = _filter(
        {"PDK_ROOT": pathlib.Path(real)},
        current_env={"PDK_ROOT": str(real)},
    )

    assert "PDK_ROOT" not in result


def test_ejected_env_repoints_the_scripts_directory(tmp_path):
    import pathlib

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "a.tcl"
    script.write_text("")

    result = _filter(
        {"A_SCRIPT": pathlib.Path(script)},
        canon_scripts_dir=str(scripts),
        target_scripts_dir="./scripts",
    )

    assert result["A_SCRIPT"] == "./scripts/a.tcl"


def test_ejected_env_never_overwrites_what_the_script_sets_itself():
    result = _filter({"STEP_DIR": "/somewhere"}, already_set={"STEP_DIR"})

    assert "STEP_DIR" not in result
