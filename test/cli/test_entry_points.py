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
"""
Regression net for the consolidated ``librelane.cli`` package.

Console scripts cannot be exercised as installed binaries here, because the
virtualenv is shared and is not reinstalled between runs. Instead every
``[project.scripts]`` target is resolved and invoked in-process, which is the
same object the installed wrapper would call.
"""

import importlib.util
import json
import subprocess
import sys
import tomllib
from importlib import import_module
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from librelane.cli.config import cli as config_cli
from librelane.cli.help import cli as help_cli
from librelane.cli.main import cli as main_cli
from librelane.cli.metrics import cli as metrics_cli
from librelane.cli.state import cli as state_cli
from librelane.cli.steps import cli as steps_cli


pytestmark = pytest.mark.all

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every module that must stay executable as ``python -m <module>``, with the
# in-repo consumer that forces us to keep it.
SUPPORTED_MODULE_INVOCATIONS = {
    # librelane/cli/main.py re-enters the container as `python3 -m librelane`,
    # and Readme.md / the installation docs document it.
    "librelane": "--version",
    # librelane/steps/step/*.py bakes `python3 -m librelane.steps` into the
    # run_ol.sh of every reproducible ever generated, including shipped ones.
    "librelane.steps": "--help",
    # .github/scripts/compare_metrics.js invokes this and has no console script.
    "librelane.common.metrics": "--help",
    # The consolidated package's own entry point.
    "librelane.cli": "--version",
}

# Module invocations deliberately dropped: nothing in docs/, test/, nix/,
# Makefile, or .github/ ever referenced them.
DROPPED_MODULE_INVOCATIONS = ["librelane.config", "librelane.state", "librelane.help"]


def _is_runnable_as_module(module: str) -> bool:
    try:
        return importlib.util.find_spec(f"{module}.__main__") is not None
    except ModuleNotFoundError:
        # Raised instead of returning None when the parent package is gone.
        return False


def _console_scripts() -> dict[str, str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as pyproject:
        return tomllib.load(pyproject)["project"]["scripts"]


def _resolve(target: str):
    module_name, _, attribute = target.partition(":")
    return getattr(import_module(module_name), attribute)


class TestConsoleScripts:
    def test_every_console_script_is_declared_in_the_cli_package(self):
        offenders = {
            name: target
            for name, target in _console_scripts().items()
            if not target.startswith("librelane.cli.")
        }

        assert offenders == {}, (
            "every user-facing frontend must be declared from librelane.cli"
        )

    def test_expected_console_scripts_exist(self):
        assert set(_console_scripts()) == {
            "librelane",
            "librelane.steps",
            "librelane.config",
            "librelane.state",
            "librelane.help",
            "librelane.env_info",
        }

    @pytest.mark.parametrize("name", sorted(_console_scripts()))
    def test_console_script_target_resolves(self, name: str):
        assert callable(_resolve(_console_scripts()[name]))


class TestHelpOutput:
    @pytest.mark.parametrize(
        ("app", "expected"),
        [
            (main_cli, "--with-initial-state"),
            (steps_cli, "create-reproducible"),
            (config_cli, "create-config"),
            (state_cli, "latest"),
            (help_cli, "step_or_flow"),
            (metrics_cli, "compare-multiple"),
        ],
    )
    def test_app_help_exits_zero(self, app: typer.Typer, expected: str):
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0, result.output
        assert expected in result.stdout


class TestRealSubcommands:
    def test_main_version(self):
        result = runner.invoke(main_cli, ["--version"])

        assert result.exit_code == 0, result.output
        assert "LibreLane v" in result.stdout

    def test_steps_create_reproducible(self):
        result = runner.invoke(steps_cli, ["create-reproducible", "--help"])

        assert result.exit_code == 0, result.output
        assert "--include-pdk" in result.stdout

    def test_config_create_config(self):
        result = runner.invoke(config_cli, ["create-config", "--help"])

        assert result.exit_code == 0, result.output
        assert "--clock-period" in result.stdout

    def test_state_latest(self, tmp_path: Path):
        state = tmp_path / "state_0.json"
        state.write_text(json.dumps({"metrics": {"answer": 42}}), encoding="utf8")
        metrics_out = tmp_path / "metrics.json"

        result = runner.invoke(
            state_cli,
            ["latest", str(tmp_path), "--extract-metrics-to", str(metrics_out)],
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == str(state)
        assert json.loads(metrics_out.read_text(encoding="utf8")) == {"answer": 42}

    def test_help_renders_a_registered_flow(self):
        result = runner.invoke(help_cli, ["Classic"])

        assert result.exit_code == 0, result.output
        assert "Classic" in result.stdout

    def test_help_rejects_an_unknown_target(self):
        result = runner.invoke(help_cli, ["NotARealStepOrFlow"])

        assert result.exit_code != 0

    def test_metrics_compare(self, tmp_path: Path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text(json.dumps({"design__instance__count": 10}), encoding="utf8")
        b.write_text(json.dumps({"design__instance__count": 20}), encoding="utf8")

        result = runner.invoke(metrics_cli, ["compare", str(a), str(b)])

        assert result.exit_code == 0, result.output

    def test_env_info(self, capsys: pytest.CaptureFixture[str]):
        _resolve(_console_scripts()["librelane.env_info"])()

        assert "kernel:" in capsys.readouterr().out


class TestModuleInvocations:
    @pytest.mark.parametrize(
        ("module", "argument"), sorted(SUPPORTED_MODULE_INVOCATIONS.items())
    )
    def test_supported_module_invocation(self, module: str, argument: str):
        result = subprocess.run(
            [sys.executable, "-m", module, argument],
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
        )

        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("module", DROPPED_MODULE_INVOCATIONS)
    def test_dropped_module_invocation(self, module: str):
        assert not _is_runnable_as_module(module)


class TestLibraryIsNotCoupledToTheCli:
    def test_help_package_is_gone(self):
        assert importlib.util.find_spec("librelane.help") is None

    def test_importing_flows_does_not_import_typer(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import librelane.flows, sys; print('typer' in sys.modules)",
            ],
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False", (
            "librelane.flows must be usable without pulling in the CLI layer"
        )

    def test_top_level_package_does_not_export_a_cli(self):
        import librelane

        assert not hasattr(librelane, "env_info_cli")

    def test_env_info_module_stays_dependency_free(self):
        """
        librelane/env_info.py is deliberately runnable with nothing installed,
        so the bug-report template can survey a broken environment.
        """
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "librelane" / "env_info.py")],
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "kernel:" in result.stdout


class TestTopLevelAppShape:
    def test_librelane_takes_config_files_not_subcommands(self, tmp_path: Path):
        """
        The reason the sub-CLIs are not attached with ``add_typer``: the top
        level app must keep parsing its first positional argument as a config
        file, which a multi-command Typer group cannot do.
        """
        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")

        result = runner.invoke(main_cli, [str(config)])

        assert "No such command" not in result.output
