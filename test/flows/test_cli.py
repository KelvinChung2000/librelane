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
from pathlib import Path
import os

import pytest
import typer
from typer.testing import CliRunner

from librelane.__main__ import cli
from librelane.common import get_tpe, set_tpe
from librelane.common.metrics.__main__ import cli as metrics_cli
from librelane.config.__main__ import cli as config_cli
from librelane.flows.cli import (
    apply_runtime_options,
    load_initial_state,
    normalize_sequential_controls,
    resolve_pdk_options,
)
from librelane.help.__main__ import cli as help_cli
from librelane.logging import get_log_level, reset_log_level
from librelane.state.__main__ import cli as state_cli
from librelane.steps.__main__ import cli as steps_cli


pytestmark = pytest.mark.all
runner = CliRunner()


def test_cli_help():
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Flow configuration options" in result.stdout
    assert "--with-initial-state" in result.stdout
    assert "Containerization options" in result.stdout


@pytest.mark.parametrize(
    ("app", "expected"),
    [
        (steps_cli, "create-reproducible"),
        (config_cli, "create-config"),
        (state_cli, "latest"),
        (help_cli, "step_or_flow"),
        (metrics_cli, "compare-multiple"),
    ],
)
def test_companion_cli_help(app: typer.Typer, expected: str):
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert expected in result.stdout


def test_no_args_prints_help_without_resolving_pdk():
    result = runner.invoke(cli)

    assert result.exit_code == 2
    assert "Usage:" in result.stdout


def test_only_flag():
    frm, to = normalize_sequential_controls("first", "last", "this-step")

    assert frm == "this-step"
    assert to == "this-step"


def test_log_level_flag():
    apply_runtime_options(
        log_level="30",
        show_progress_bar=None,
        condensed=False,
        jobs=None,
    )
    assert get_log_level() == 30
    reset_log_level()

    with pytest.raises(typer.BadParameter, match="invalid logging level"):
        apply_runtime_options(
            log_level="NOT A REAL LOG LEVEL",
            show_progress_bar=None,
            condensed=False,
            jobs=None,
        )


def test_worker_count():
    tpe_backup = get_tpe()
    try:
        apply_runtime_options(
            log_level=None,
            show_progress_bar=None,
            condensed=False,
            jobs=3,
        )
        assert get_tpe()._max_workers == 3
    finally:
        set_tpe(tpe_backup)


def test_initial_state(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    state_in = tmp_path / "state_in.json"
    state_in.write_text('{"metrics": {"hi": true}}', encoding="utf8")
    bad_json = tmp_path / "bad_json.json"
    bad_json.write_text('{"metrics": {"hi": true}', encoding="utf8")
    non_dict = tmp_path / "non_dict.json"
    non_dict.write_text("[]", encoding="utf8")

    state = load_initial_state([state_in])
    assert state is not None
    assert state.metrics["hi"]

    with pytest.raises(typer.Exit):
        load_initial_state([bad_json])
    assert "Invalid JSON" in caplog.text
    caplog.clear()

    with pytest.raises(typer.Exit):
        load_initial_state([non_dict])
    assert "is not a dictionary" in caplog.text


def test_manual_pdk_consumes_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("PDK_ROOT", str(tmp_path))
    monkeypatch.setenv("PDK", "sky130A")
    monkeypatch.setenv("STD_CELL_LIBRARY", "sky130_fd_sc_hd")
    monkeypatch.setenv("PAD_CELL_LIBRARY", "sky130_fd_io")

    resolved = resolve_pdk_options(
        use_ciel=False,
        pdk_root=tmp_path,
        pdk="sky130A",
        scl="sky130_fd_sc_hd",
        pad="sky130_fd_io",
    )

    assert resolved.pdk_root == str(tmp_path)
    assert "PDK_ROOT" not in os.environ
    assert "PDK" not in os.environ
    assert "STD_CELL_LIBRARY" not in os.environ
    assert "PAD_CELL_LIBRARY" not in os.environ


def test_main_cli_normalizes_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import librelane.__main__ as main_module

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf8")
    captured = {}

    def fake_run(ctx, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(main_module, "run", fake_run)
    result = runner.invoke(
        cli,
        [
            "--manual-pdk",
            "--pdk-root",
            str(tmp_path),
            "--only",
            "this-step",
            str(config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["frm"] == "this-step"
    assert captured["to"] == "this-step"
