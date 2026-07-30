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
Regression net for the ``librelane`` command and its subcommands.

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
from rich.text import Text
from typer.testing import CliRunner

from librelane.cli.main import cli


pytestmark = pytest.mark.all

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every module that must stay executable as ``python -m <module>``, with the
# in-repo consumer that forces us to keep it.
SUPPORTED_MODULE_INVOCATIONS = {
    # librelane/cli/run.py re-enters the container as `python3 -m librelane`,
    # and Readme.md / the installation docs document it.
    "librelane": "--version",
    # librelane/steps/step/reporting.py bakes `python3 -m librelane.steps` into
    # the run_ol.sh of every reproducible ever generated, including shipped ones.
    "librelane.steps": "--help",
    # .github/scripts/compare_metrics.js invokes this and has no console script.
    "librelane.common.metrics": "--help",
    # The CLI package's own entry point.
    "librelane.cli": "--version",
}

# Module invocations deliberately dropped: nothing in docs/, test/, nix/,
# Makefile, or .github/ ever referenced them.
DROPPED_MODULE_INVOCATIONS = ["librelane.config", "librelane.state", "librelane.help"]

# The dotted console scripts that predate subcommands, and what replaced them.
DEPRECATED_SCRIPTS = {
    "librelane.steps": "librelane steps",
    "librelane.config": "librelane config",
    "librelane.state": "librelane state",
    "librelane.help": "librelane help",
    "librelane.env_info": "librelane env-info",
}


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
        assert set(_console_scripts()) == {"librelane", *DEPRECATED_SCRIPTS}

    @pytest.mark.parametrize("name", sorted(_console_scripts()))
    def test_console_script_target_resolves(self, name: str):
        assert callable(_resolve(_console_scripts()[name]))

    @pytest.mark.parametrize("name", sorted(DEPRECATED_SCRIPTS))
    def test_deprecated_scripts_come_from_the_deprecation_module(self, name: str):
        assert _console_scripts()[name].startswith("librelane.cli._deprecated:")


class TestSubcommands:
    """Every area of the CLI is reachable as ``librelane <subcommand>``."""

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["run", "--help"], "--with-initial-state"),
            (["steps", "--help"], "create-reproducible"),
            (["config", "--help"], "create"),
            (["state", "--help"], "latest"),
            (["metrics", "--help"], "compare-multiple"),
            (["help", "--help"], "step_or_flow"),
            (["steps", "create-reproducible", "--help"], "--include-pdk"),
            (["config", "create", "--help"], "--clock-period"),
        ],
    )
    def test_subcommand_help_exits_zero(self, argv: list[str], expected: str):
        result = runner.invoke(cli, argv)

        assert result.exit_code == 0, result.output
        # Rich styles an option name from the inside, so the raw output splits
        # "--with-initial-state" across colour codes whenever colour is on.
        assert expected in Text.from_ansi(result.stdout).plain

    def test_root_help_lists_every_subcommand(self):
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0, result.output
        for subcommand in ("run", "steps", "config", "state", "metrics", "help"):
            assert subcommand in result.stdout

    def test_version(self):
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0, result.output
        assert "LibreLane v" in result.stdout

    def test_bare_version_is_just_the_number(self):
        from librelane.__version__ import __version__

        result = runner.invoke(cli, ["--bare-version"])

        assert result.exit_code == 0, result.output
        assert result.stdout == __version__

    def test_state_latest(self, tmp_path: Path):
        state = tmp_path / "state_0.json"
        state.write_text(json.dumps({"metrics": {"answer": 42}}), encoding="utf8")
        metrics_out = tmp_path / "metrics.json"

        result = runner.invoke(
            cli,
            [
                "state",
                "latest",
                str(tmp_path),
                "--extract-metrics-to",
                str(metrics_out),
            ],
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == str(state)
        assert json.loads(metrics_out.read_text(encoding="utf8")) == {"answer": 42}

    def test_help_renders_a_registered_flow(self):
        result = runner.invoke(cli, ["help", "Classic"])

        assert result.exit_code == 0, result.output
        assert "Classic" in result.stdout

    def test_help_rejects_an_unknown_target(self):
        result = runner.invoke(cli, ["help", "NotARealStepOrFlow"])

        assert result.exit_code != 0

    def test_metrics_compare(self, tmp_path: Path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text(json.dumps({"design__instance__count": 10}), encoding="utf8")
        b.write_text(json.dumps({"design__instance__count": 20}), encoding="utf8")

        result = runner.invoke(cli, ["metrics", "compare", str(a), str(b)])

        assert result.exit_code == 0, result.output

    def test_env_info(self, capsys: pytest.CaptureFixture[str]):
        _resolve(_console_scripts()["librelane.env_info"])()

        assert "kernel:" in capsys.readouterr().out


class TestRunIsTheDefaultCommand:
    """
    ``librelane <config.json>`` must keep meaning ``librelane run <config.json>``.

    Reproducibles, the container re-entry, every CI job and all the installation
    docs spell it without the subcommand, so this is the compatibility contract
    that :class:`librelane.cli._app.DefaultToRunGroup` exists to honour.
    """

    @pytest.fixture
    def config(self, tmp_path: Path) -> Path:
        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")
        return config

    @pytest.fixture
    def captured_request(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        import librelane.cli.run as run_module

        captured: dict = {}
        monkeypatch.setattr(
            run_module, "start_flow", lambda request: captured.update(request=request)
        )
        return captured

    @pytest.mark.parametrize("prefix", [[], ["run"]])
    def test_config_file_reaches_run_with_or_without_the_subcommand(
        self,
        prefix: list[str],
        config: Path,
        captured_request: dict,
        tmp_path: Path,
    ):
        result = runner.invoke(
            cli,
            [*prefix, "--manual-pdk", "--pdk-root", str(tmp_path), str(config)],
        )

        assert result.exit_code == 0, result.output
        assert captured_request["request"].config_files == (str(config),)

    def test_leading_option_still_reaches_run(
        self, config: Path, captured_request: dict, tmp_path: Path
    ):
        """``librelane --flow Classic config.json`` has no leading positional."""
        result = runner.invoke(
            cli,
            [
                "--manual-pdk",
                "--pdk-root",
                str(tmp_path),
                "--flow",
                "Classic",
                str(config),
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured_request["request"].flow_name == "Classic"

    def test_a_subcommand_name_is_not_swallowed_by_run(self):
        result = runner.invoke(cli, ["state", "--help"])

        assert result.exit_code == 0, result.output
        assert "latest" in result.stdout

    @pytest.mark.parametrize(
        "argv",
        [
            ["--smoke-test"],
            ["--run-example", "spm"],
            ["--log-level", "ERROR", "--condensed", "--smoke-test"],
        ],
        ids=["smoke-test", "run-example", "documented-smoke-test"],
    )
    def test_action_flags_reach_run_without_a_subcommand(
        self, argv: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """
        `librelane --smoke-test` and `librelane --run-example spm` appear in the
        installation docs and at several .github/workflows/ci.yml call sites.
        They lead with an option, so nothing positional hints at `run`.
        """
        import librelane.cli.run as run_module

        reached: dict = {}
        monkeypatch.setattr(
            run_module,
            "run_included_example",
            lambda request, smoke_test, example: reached.update(
                smoke_test=smoke_test, example=example
            ),
        )

        result = runner.invoke(
            cli, [*argv, "--manual-pdk", "--pdk-root", str(tmp_path)]
        )

        assert result.exit_code == 0, result.output
        assert reached == {
            "smoke_test": "--smoke-test" in argv,
            "example": "spm" if "--run-example" in argv else None,
        }

    def test_root_flags_are_not_rewritten_into_run(self):
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0, result.output
        assert "LibreLane v" in result.stdout

    def test_unknown_subcommand_is_reported_against_run(self, tmp_path: Path):
        """
        A path that does not exist is a `run` argument error, not "no such
        command" -- the fall-through means there are no unknown subcommands.
        """
        result = runner.invoke(cli, [str(tmp_path / "nope.json")])

        assert result.exit_code != 0
        assert "No such command" not in result.output


class TestMetaFlowSelection:
    """`meta.flow` names a registered flow, and nothing else."""

    def _select(self, tmp_path: Path, meta: dict):
        from librelane.cli.run import FlowRequest, select_flow
        from librelane.cli.runtime import ResolvedPdkOptions

        config = tmp_path / "config.json"
        config.write_text(json.dumps({"meta": meta}), encoding="utf8")
        return select_flow(
            FlowRequest(
                config_files=(str(config),),
                flow_name=None,
                pdk=ResolvedPdkOptions(
                    pdk_root=str(tmp_path), pdk="sky130A", scl=None, pad=None
                ),
                tag=None,
                last_run=False,
                frm=None,
                to=None,
                skip=(),
                overwrite=False,
                reproducible=None,
                initial_state=None,
                initial_state_overrides=(),
                config_overrides=(),
                design_dir=None,
                force_run_dir=None,
                save_views_to=None,
                ef_save_views_to=None,
            )
        )

    def test_a_step_list_is_rejected(self, tmp_path: Path):
        """
        A list of step IDs used to build an anonymous flow. `Meta` is a plain
        dataclass and validates nothing, so without an explicit rejection the
        list falls through the `isinstance` test and silently runs Classic --
        a different flow than the configuration named.
        """
        import typer

        with pytest.raises(typer.Exit) as raised:
            self._select(tmp_path, {"version": 2, "flow": ["Yosys.Synthesis"]})

        assert raised.value.exit_code == 1

    def test_a_registered_flow_name_is_accepted(self, tmp_path: Path):
        selected = self._select(tmp_path, {"version": 2, "flow": "Classic"})

        assert selected.__name__ == "Classic"

    def test_an_unknown_flow_name_is_still_rejected(self, tmp_path: Path):
        import typer

        with pytest.raises(typer.Exit) as raised:
            self._select(tmp_path, {"version": 2, "flow": "NoSuchFlow"})

        assert raised.value.exit_code == 1


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

    def test_reproducibles_can_still_reach_steps(self):
        """
        run_ol.sh calls `python3 -m librelane.steps run --config ... --state-in
        ...`. It must not gain a deprecation warning, since nobody running a
        shipped reproducible can act on one.
        """
        result = subprocess.run(
            [sys.executable, "-m", "librelane.steps", "run", "--help"],
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "deprecated" not in result.stderr


class TestDeprecatedScripts:
    # librelane.env_info is excluded: it is a bare function rather than a Typer
    # app, so that it still runs when LibreLane's dependencies are missing, and
    # it therefore neither parses --help nor exits.
    TYPER_BACKED = sorted(set(DEPRECATED_SCRIPTS) - {"librelane.env_info"})

    @pytest.mark.parametrize("old", TYPER_BACKED)
    def test_deprecated_script_names_its_replacement(
        self,
        old: str,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        entry_point = _resolve(_console_scripts()[old])
        monkeypatch.setattr(sys, "argv", [old, "--help"])

        with pytest.raises(SystemExit):
            entry_point()

        captured = capsys.readouterr()
        assert f"`{old}` is deprecated" in captured.err
        assert f"`{DEPRECATED_SCRIPTS[old]}`" in captured.err

    def test_deprecated_env_info_warns_and_still_surveys(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        entry_point = _resolve(_console_scripts()["librelane.env_info"])
        monkeypatch.setattr(sys, "argv", ["librelane.env_info"])

        entry_point()

        captured = capsys.readouterr()
        assert "`librelane.env_info` is deprecated" in captured.err
        assert "`librelane env-info`" in captured.err
        assert "kernel:" in captured.out

    def test_deprecated_state_script_still_takes_its_subcommand(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        `.github/workflows/ci.yml` runs `librelane.state latest <dir>`.

        A one-command Typer app folds into that command, which would read
        "latest" as the run directory instead of as the subcommand. See
        librelane.cli._app.make_group.
        """
        (tmp_path / "state_0.json").write_text(
            json.dumps({"metrics": {}}), encoding="utf8"
        )
        entry_point = _resolve(_console_scripts()["librelane.state"])
        monkeypatch.setattr(sys, "argv", ["librelane.state", "latest", str(tmp_path)])

        with pytest.raises(SystemExit) as exit_info:
            entry_point()

        assert exit_info.value.code == 0
        assert capsys.readouterr().out.strip() == str(tmp_path / "state_0.json")

    def test_deprecated_config_script_translates_the_old_command_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from librelane.cli import _deprecated

        monkeypatch.setattr(
            sys, "argv", ["librelane.config", "create-config", "--help"]
        )

        with pytest.raises(SystemExit) as exit_info:
            _deprecated.config()

        assert exit_info.value.code == 0
        assert sys.argv[1] == "create"


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

    def test_options_module_is_free_of_librelane_imports(self):
        """
        librelane.cli.options is pure declaration, so a `--help` must not pay
        for loading flows, steps or the PDK machinery.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import librelane.cli.options, sys;"
                "print(any(m.startswith('librelane.flows') or"
                " m.startswith('librelane.steps') for m in sys.modules))",
            ],
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

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
