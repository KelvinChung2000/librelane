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


def make_request(tmp_path: Path, **overrides):
    """
    A :class:`librelane.cli.run.FlowRequest` with every field at a neutral
    value, so a test names only the field it is about.

    Parameters
    ----------
    tmp_path : Path
        Somewhere to point the PDK root at.
    **overrides
        Fields to replace.

    Returns
    -------
    librelane.cli.run.FlowRequest
        The request.
    """
    from dataclasses import replace

    from librelane.cli.run import FlowRequest
    from librelane.cli.runtime import ResolvedPdkOptions

    neutral = FlowRequest(
        config_files=(),
        flow_name=None,
        pdk=ResolvedPdkOptions(
            pdk_root=str(tmp_path), pdk="sky130A", scl=None, pad=None
        ),
        tag=None,
        last_run=False,
        target=(),
        invalidate=(),
        skip=(),
        explain=False,
        explain_variables=False,
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
    return replace(neutral, **overrides)


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
        from librelane.cli.run import select_flow

        config = tmp_path / "config.json"
        config.write_text(json.dumps({"meta": meta}), encoding="utf8")
        return select_flow(make_request(tmp_path, config_files=(str(config),)))

    def test_a_step_list_is_rejected(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """
        A list of step IDs used to build an anonymous flow. `Meta` is a plain
        dataclass and validates nothing, so without an explicit rejection the
        list falls through the `isinstance` test and silently runs Classic --
        a different flow than the configuration named.

        The rejection lists the registered flows, because naming one is the
        only thing a user can do here: a flow is a document, and only the
        documents this package ships are registered.
        """
        import typer

        with pytest.raises(typer.Exit) as raised:
            self._select(tmp_path, {"version": 2, "flow": ["Yosys.Synthesis"]})

        assert raised.value.exit_code == 1
        assert "Classic" in caplog.text
        assert "VHDLClassic" in caplog.text

    def test_a_registered_flow_name_is_accepted(self, tmp_path: Path):
        selected = self._select(tmp_path, {"version": 2, "flow": "Classic"})

        assert selected.name == "Classic"

    def test_an_unknown_flow_name_is_still_rejected(self, tmp_path: Path):
        import typer

        with pytest.raises(typer.Exit) as raised:
            self._select(tmp_path, {"version": 2, "flow": "NoSuchFlow"})

        assert raised.value.exit_code == 1

    @pytest.mark.parametrize("source", ["meta", "flag"])
    def test_an_unknown_flow_name_lists_the_registered_flows(
        self,
        source: str,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """
        A name that does not resolve is exactly the moment a user needs to see
        what does. `--flow` is also screened by `validate_flow_name`, but
        `meta.flow` is not screened anywhere else, and `select_flow` is called
        directly by `librelane run`.
        """
        import typer

        from librelane.cli.run import select_flow

        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")
        request = make_request(
            tmp_path,
            config_files=(str(config),),
            flow_name="NoSuchFlow" if source == "flag" else None,
        )
        if source == "meta":
            config.write_text(
                json.dumps({"meta": {"version": 2, "flow": "NoSuchFlow"}}),
                encoding="utf8",
            )

        with pytest.raises(typer.Exit):
            select_flow(request)

        assert "Classic" in caplog.text
        assert "VHDLClassic" in caplog.text


class TestFlowControlArguments:
    """
    What ``--target``, ``--invalidate``, ``--skip`` and ``--reproducible`` hand
    to :meth:`librelane.flows.engine.Workflow.run`.

    :class:`librelane.cli.run.FlowRequest` stores them as tuples, and an empty
    tuple is not what ``run`` reads as "unset": ``target=()`` selects no jobs
    at all, builds an empty net and dies in the sink join, while
    ``target=None`` runs the whole graph. The normalisation therefore has to
    happen at this boundary, and it is what these pin.
    """

    def _started(self, mocker, tmp_path: Path, **overrides) -> dict:
        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        run_module.start_flow(
            make_request(tmp_path, config_files=("config.json",), **overrides)
        )
        return workflow.return_value.start.call_args.kwargs

    def test_an_unspecified_target_is_none_and_not_an_empty_tuple(
        self, mocker, tmp_path: Path
    ):
        started = self._started(mocker, tmp_path)

        assert started["target"] is None
        assert started["invalidate"] is None
        assert started["skip"] is None

    def test_a_specified_target_reaches_the_workflow(self, mocker, tmp_path: Path):
        started = self._started(
            mocker,
            tmp_path,
            target=("floorplan", "cts"),
            invalidate=("synthesis",),
            skip=("lint",),
        )

        assert started["target"] == ["floorplan", "cts"]
        assert started["invalidate"] == ["synthesis"]
        assert started["skip"] == ["lint"]

    def test_every_flow_control_keyword_is_a_named_parameter_of_run(self):
        """
        `Flow.start` forwards `**kwargs` into `run` unchanged, and
        `Workflow.run` has to keep a `**kwargs` of its own because `start`
        always passes `initial_state_given=` and `starting_ordinal=`. A
        misspelled keyword is therefore accepted and does nothing, and this
        layer is the only one that can refuse it.
        """
        from librelane.cli.run import (
            _WORKFLOW_RUN_PARAMETERS,
            bind_workflow_arguments,
        )

        assert bind_workflow_arguments(target=None, skip=None) == {
            "target": None,
            "skip": None,
        }

        # The claim in the name: every keyword the CLI forwards is a real
        # named parameter of Workflow.run. Asserted against the set derived
        # from run's signature, so renaming a parameter on the engine fails
        # here rather than being swallowed by its '**kwargs'. Without this the
        # test passed under such a rename -- the two _started tests caught it,
        # not the one advertising it.
        assert {
            "target",
            "invalidate",
            "skip",
            "reproducible",
        } <= _WORKFLOW_RUN_PARAMETERS

    def test_a_keyword_run_does_not_declare_is_refused(self):
        from librelane.cli.run import bind_workflow_arguments

        with pytest.raises(AssertionError, match="targt"):
            bind_workflow_arguments(targt=["floorplan"])


class TestFlowConstructionErrors:
    """
    What reaches the terminal when building the workflow fails.

    Constructing it resolves the document against the registries and resolves
    ``TOOLS`` against the document, and both report a mistake as a
    :class:`librelane.flows.FlowError`. Every one of those messages names the
    offending key and the legal alternatives, which is worth nothing if it
    arrives as the last line of a traceback.
    """

    def test_a_job_resolution_error_is_reported_and_not_a_traceback(
        self, mocker, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        import typer

        import librelane.cli.run as run_module
        from librelane.jobs import JobResolutionError

        mocker.patch.object(run_module, "select_flow")
        mocker.patch.object(
            run_module,
            "Workflow",
            side_effect=JobResolutionError(
                "TOOLS names 'syntheis', which is not a job of flow 'Classic'. "
                "Did you mean: 'synthesis'?"
            ),
        )

        with pytest.raises(typer.Exit) as raised:
            run_module.start_flow(make_request(tmp_path, config_files=("config.json",)))

        assert raised.value.exit_code == 1
        assert "Did you mean: 'synthesis'?" in caplog.text

    def test_a_malformed_document_is_reported_and_not_a_traceback(
        self, mocker, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """
        The same handler, reached from the other half of construction: a
        document validated against the registries raises ``FlowSpecError``,
        which is a ``FlowError`` and not the ``ValueError`` the neighbouring
        handler catches.
        """
        import typer

        import librelane.cli.run as run_module
        from librelane.flows.spec import FlowSpecError

        mocker.patch.object(run_module, "select_flow")
        mocker.patch.object(
            run_module,
            "Workflow",
            side_effect=FlowSpecError("job 'lint' uses stage 'lnt', which…"),
        )

        with pytest.raises(typer.Exit) as raised:
            run_module.start_flow(make_request(tmp_path, config_files=("config.json",)))

        assert raised.value.exit_code == 1
        assert "which…" in caplog.text


class TestJobExplanationTable:
    def test_explain_prints_a_job_table(self):
        from librelane.cli.run import format_job_explanation
        from librelane.flows import Explanation, JobDisposition

        rendered = format_job_explanation(
            Explanation(
                jobs=(
                    JobDisposition("lint", (), True, "will run", None),
                    JobDisposition("synthesis", ("lint",), True, "will run", None),
                    JobDisposition(
                        "klayout_streamout",
                        ("ir_drop",),
                        False,
                        "'RUN_KLAYOUT_STREAMOUT' is false",
                        "condition",
                    ),
                ),
            )
        )

        assert "JOB" in rendered
        assert "NEEDS" in rendered
        assert "klayout_streamout" in rendered
        assert "condition" in rendered
        assert "Jobs contributing no steps" not in rendered

    def test_the_mechanism_column_fits_the_longest_mechanism(self):
        """
        ``not-in-reproducible`` is longer than the column a fixed width left
        for it, and one overflowing row shifts the two columns after it out of
        line with every other row in the table.
        """
        from librelane.cli.run import format_job_explanation
        from librelane.flows import Explanation, JobDisposition

        rendered = format_job_explanation(
            Explanation(
                jobs=(
                    JobDisposition("lint", (), True, "will run", None),
                    JobDisposition(
                        "final_checks",
                        ("lint",),
                        False,
                        "--reproducible runs only 'lint' and its ancestors",
                        "not-in-reproducible",
                    ),
                ),
            )
        )

        header, *rows = rendered.splitlines()
        reason_column = header.index("REASON")
        assert [row[reason_column:] for row in rows] == [
            "will run",
            "--reproducible runs only 'lint' and its ancestors",
        ]

    def test_explain_renders_the_job_half_and_exits(self, mocker, tmp_path: Path):
        """
        `--explain` must reach `format_job_explanation` and exit before the
        run, so that asking what a flow would do never starts one.
        """
        import typer

        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        formatter = mocker.patch.object(run_module, "format_job_explanation")

        with pytest.raises(typer.Exit) as raised:
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain=True,
                    target=("floorplan",),
                    skip=("lint",),
                )
            )

        assert raised.value.exit_code == 0
        workflow.return_value.explain.assert_called_once_with(
            target=["floorplan"],
            invalidate=None,
            skip=["lint"],
            reproducible=None,
            variables=False,
        )
        formatter.assert_called_once_with(workflow.return_value.explain.return_value)
        workflow.return_value.start.assert_not_called()

    def test_every_run_shaping_option_reaches_explain(self, mocker, tmp_path: Path):
        """
        `--reproducible` and `--invalidate` shape the run as surely as
        `--target` does: the first restricts the graph to one job and its
        ancestors, and both refuse a name the document does not declare. An
        explanation that did not see them would describe a different
        invocation from the one the same command line would perform.
        """
        import typer

        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        mocker.patch.object(run_module, "format_job_explanation")

        with pytest.raises(typer.Exit):
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain=True,
                    invalidate=("synthesis",),
                    reproducible="synthesis/Yosys.Synthesis",
                )
            )

        workflow.return_value.explain.assert_called_once_with(
            target=None,
            invalidate=["synthesis"],
            skip=None,
            reproducible="synthesis/Yosys.Synthesis",
            variables=False,
        )

    def test_a_refusal_from_explain_is_reported_and_not_a_traceback(
        self, mocker, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        """
        `--explain` refuses whatever the run refuses, and the same mistyped
        `--target` that prints one line without `--explain` printed a
        traceback with it: the call sat outside every handler in `start_flow`.
        """
        import typer

        import librelane.cli.run as run_module
        from librelane.flows import FlowException

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        workflow.return_value.explain.side_effect = FlowException(
            "--target names 'no_such_job'"
        )

        with pytest.raises(typer.Exit) as raised:
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain=True,
                    target=("no_such_job",),
                )
            )

        assert raised.value.exit_code == 1
        assert "no_such_job" in caplog.text

    def test_an_unconstrained_explain_passes_none_not_an_empty_tuple(
        self, mocker, tmp_path: Path
    ):
        """
        The same normalisation `start_flow` does for a run, on the explain
        path. `FlowRequest` stores tuples, and an empty one is not `None`: it
        would select no jobs at all, so every row would read "not in the
        --target subgraph" and `--explain` would be useless without failing.
        """
        import typer

        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        mocker.patch.object(run_module, "format_job_explanation")

        with pytest.raises(typer.Exit):
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain=True,
                )
            )

        workflow.return_value.explain.assert_called_once_with(
            target=None,
            invalidate=None,
            skip=None,
            reproducible=None,
            variables=False,
        )


class TestVariableExplanationTable:
    def test_explain_variables_renders_the_variable_half_and_exits(
        self, mocker, tmp_path: Path
    ):
        """
        `--explain-variables` selects the variables table rather than filtering
        rows out of the job table, so on its own it prints that table and only
        that one, and it is what asks the flow for the rows at all.
        """
        import typer

        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        workflow = mocker.patch.object(run_module, "Workflow")
        jobs = mocker.patch.object(run_module, "format_job_explanation")
        variables = mocker.patch.object(run_module, "format_variable_explanation")

        with pytest.raises(typer.Exit) as raised:
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain_variables=True,
                )
            )

        assert raised.value.exit_code == 0
        workflow.return_value.explain.assert_called_once_with(
            target=None,
            invalidate=None,
            skip=None,
            reproducible=None,
            variables=True,
        )
        variables.assert_called_once_with(workflow.return_value.explain.return_value)
        jobs.assert_not_called()
        workflow.return_value.start.assert_not_called()

    def test_both_explain_options_print_both_tables(self, mocker, tmp_path: Path):
        import typer

        import librelane.cli.run as run_module

        mocker.patch.object(run_module, "select_flow")
        mocker.patch.object(run_module, "Workflow")
        jobs = mocker.patch.object(run_module, "format_job_explanation")
        variables = mocker.patch.object(run_module, "format_variable_explanation")

        with pytest.raises(typer.Exit):
            run_module.start_flow(
                make_request(
                    tmp_path,
                    config_files=("config.json",),
                    explain=True,
                    explain_variables=True,
                )
            )

        jobs.assert_called_once()
        variables.assert_called_once()

    def test_explain_variables_reaches_the_request(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        import librelane.cli.run as run_module

        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")
        captured: dict = {}
        monkeypatch.setattr(
            run_module, "start_flow", lambda request: captured.update(request=request)
        )

        result = runner.invoke(
            cli,
            [
                "--manual-pdk",
                "--pdk-root",
                str(tmp_path),
                "--explain-variables",
                str(config),
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["request"].explain_variables is True
        assert captured["request"].explain is False


class TestWorkflowOptionsAreParsed:
    @pytest.mark.parametrize(
        ("argv", "field", "expected"),
        [
            (["--target", "floorplan", "-T", "cts"], "target", ("floorplan", "cts")),
            (["--invalidate", "synthesis"], "invalidate", ("synthesis",)),
            (["-F", "synthesis"], "invalidate", ("synthesis",)),
            ([], "target", ()),
        ],
    )
    def test_option_reaches_the_request(
        self,
        argv: list[str],
        field: str,
        expected: tuple[str, ...],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import librelane.cli.run as run_module

        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")
        captured: dict = {}
        monkeypatch.setattr(
            run_module, "start_flow", lambda request: captured.update(request=request)
        )

        result = runner.invoke(
            cli,
            [
                "--manual-pdk",
                "--pdk-root",
                str(tmp_path),
                *argv,
                str(config),
            ],
        )

        assert result.exit_code == 0, result.output
        assert getattr(captured["request"], field) == expected

    @pytest.mark.parametrize("removed", ["--from", "--to"])
    def test_the_sequential_window_options_are_gone(self, removed: str):
        """
        A step window is not expressible over a graph, so `--from` and `--to`
        are replaced rather than reinterpreted. They must fail as unknown
        options, not be quietly accepted and dropped.
        """
        result = runner.invoke(cli, ["run", removed, "whatever"])

        assert result.exit_code != 0
        assert "No such option" in Text.from_ansi(result.output).plain


class TestExplainOption:
    def test_explain_reaches_the_request(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """
        --explain short-circuits inside start_flow, which this test replaces,
        so it pins that the flag reaches the request. The table itself is
        covered by test/flows/test_explain.py.
        """
        import librelane.cli.run as run_module

        config = tmp_path / "config.json"
        config.write_text("{}", encoding="utf8")
        captured: dict = {}
        monkeypatch.setattr(
            run_module, "start_flow", lambda request: captured.update(request=request)
        )

        result = runner.invoke(
            cli,
            [
                "--manual-pdk",
                "--pdk-root",
                str(tmp_path),
                "--explain",
                str(config),
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["request"].explain is True


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
