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
"""The ``librelane steps`` subcommand group."""

from loguru import logger

import os
import shlex
import shutil
import datetime
import subprocess
from functools import partial
from pathlib import Path
from typing import Annotated, IO, Any
from collections.abc import Sequence
from importlib.resources import files

import typer

from librelane.steps.step import Step, StepError, StepException
from librelane.__version__ import __version__
from librelane.common import mkdirp, recreate_tree, Toolbox
from librelane.cli._app import make_group
from librelane.cli.options import CondensedOption, LogLevelOption, ShowProgressBarOption
from librelane.cli.runtime import apply_runtime_options


def load_step_from_inputs(
    id: str | None,
    config: str | os.PathLike,
    state_in: str | os.PathLike,
    pdk_root: str | os.PathLike | None = None,
) -> Step:
    Target = Step
    if id is not None:
        if Found := Step.factory.get(id):
            Target = Found
        else:
            logger.error(f"No step registered with id '{id}'.")
            logger.info(
                f"If the step '{id}' is part of a plugin, make sure the plugin's parent directory is in the PYTHONPATH environment variable."
            )
            raise typer.Exit(-1)

    return Target.load(
        config=config,
        state_in=state_in,
        pdk_root=str(pdk_root) if pdk_root is not None else None,
    )


cli = make_group(
    help="Run standalone steps and create filesystem-independent step reproducibles."
)


@cli.command()
def run(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="A step-specific config.json file.",
        ),
    ],
    state_in: Annotated[
        Path,
        typer.Option(
            "--state-in",
            "-i",
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="The input state JSON file.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=False,
            dir_okay=True,
            help="The directory in which to store step artifacts.",
        ),
    ] = Path(
        os.getcwd(),
        datetime.datetime.now().astimezone().strftime("STEP_RUN_%Y-%m-%d_%H-%M-%S"),
    ),
    id: Annotated[
        str | None,
        typer.Option(
            "--id",
            help=(
                "The registered step ID. May be omitted when config.meta.step "
                "provides it."
            ),
        ),
    ] = None,
    pdk_root: Annotated[
        Path | None,
        typer.Option(
            "--pdk-root",
            envvar="PDK_ROOT",
            exists=True,
            file_okay=False,
            dir_okay=True,
            help=("A PDK root for reproducibles that do not include their own PDK."),
        ),
    ] = None,
    log_level: LogLevelOption = None,
    show_progress_bar: ShowProgressBarOption = None,
    condensed: CondensedOption = False,
) -> None:
    """
    Runs a step using a step-specific configuration object and an input state.

    Useful for re-running a step that has already run, or running
    filesystem-independent reproducibles.
    """

    apply_runtime_options(
        log_level=log_level,
        show_progress_bar=show_progress_bar,
        condensed=condensed,
        jobs=None,
    )
    os.environ.pop("PDK_ROOT", None)
    step = load_step_from_inputs(id, config, state_in, pdk_root)

    if step.config.meta.librelane_version != __version__:
        logger.warning(
            "LibreLane version being used is different from the version this step was originally run with. Procceed with caution."
        )

    mkdirp(output)
    toolbox_dir = os.path.join(output, "toolbox_tmp")
    try:
        step.start(
            toolbox=Toolbox(toolbox_dir),
            step_dir=output,
        )
    except StepException as e:
        logger.error("An unexpected error occurred while executing your step:")
        logger.error(e)
        raise typer.Exit(-1) from e
    except StepError as e:
        logger.error("An error occurred while executing your step:")
        logger.error(e)
        raise typer.Exit(-1) from e


@cli.command()
def eject(
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="A step-specific config.json file.",
        ),
    ],
    state_in: Annotated[
        Path,
        typer.Option(
            "--state-in",
            "-i",
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="The input state JSON file.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            help="The ejected run script.",
        ),
    ] = Path("run.sh"),
    id: Annotated[
        str | None,
        typer.Option(
            "--id",
            help=(
                "The registered step ID. May be omitted when config.meta.step "
                "provides it."
            ),
        ),
    ] = None,
) -> None:
    """
    For steps that rely on underlying utilities using a subprocess, this scripts
    "ejects" LibreLane and just returns a shell script that runs this subprocess.

    This is useful for:

    * LibreLane developers and maintainers reporting issues to original tool
      developers
    * Advanced users who are sure that the issue is not LibreLane-specific and
      would like to skip reporting an issue with LibreLane first
    """

    step = load_step_from_inputs(id, config, state_in)

    if step.config.meta.librelane_version != __version__:
        logger.warning(
            "LibreLane version being used is different from the version this step was originally run with. Procceed with caution."
        )

    toolbox_dir = os.path.join(".", "toolbox_tmp")

    found_cmd: Sequence[str | os.PathLike] | None = None
    found_env: dict[str, Any] | None = None
    found_stdin_data: str | bytes | None = None

    class Stop(Exception):
        pass

    def popen_substitute(
        cmd: Sequence[str | os.PathLike],
        env: dict[str, Any] | None = None,
        stdin: IO[Any] | None = None,
        *args,
        **kwargs,
    ) -> subprocess.Popen:
        nonlocal found_env, found_cmd, found_stdin_data
        found_cmd = cmd
        found_env = env
        if found_stdin := stdin:
            found_stdin_data = found_stdin.read()
        raise Stop()

    step.run_subprocess = partial(
        step.run_subprocess,
        _popen_callable=popen_substitute,
    )

    try:
        step.start(
            toolbox=Toolbox(toolbox_dir),
            step_dir=".",
        )
    except Stop:
        pass
    except Exception as e:
        logger.info("An error occurred while attempting to execute the step:")
        logger.error(e)
        logger.info("This may affect the ejection process.")

    if found_cmd is None:
        logger.error(
            "Could not eject: The step did not successfully invoke a subprocess using run_subprocess."
        )
        raise typer.Exit(-1)

    canon_scripts_dir = files("librelane").joinpath("scripts")
    canon_scripts_dir_string = str(canon_scripts_dir)
    target_scripts_dir = os.path.join(".", "scripts")

    try:
        shutil.rmtree(target_scripts_dir)
    except FileNotFoundError:
        pass

    recreate_tree(canon_scripts_dir, target_scripts_dir)
    if chmod := shutil.which("chmod"):
        # Nix's Files aren't writeable
        subprocess.check_call([chmod, "-R", "755", target_scripts_dir])

    current_env = os.environ
    filtered_env = {
        "STEP_DIR": ".",
        "SCRIPTS_DIR": target_scripts_dir,
    }
    if found_env is not None:
        for key, value in found_env.items():
            if (
                value == current_env.get(key)
                or key in filtered_env
                or key in ["PATH", "PYTHONPATH"]
            ):
                continue
            if os.path.isabs(value) and os.path.exists(value):
                if value.startswith(canon_scripts_dir_string):
                    value = value.replace(canon_scripts_dir_string, target_scripts_dir)
            filtered_env[key] = value

    cat_in = ""
    if found_stdin_data:
        mode = "wb"
        if isinstance(found_stdin_data, str):
            mode = "w"
        with open("STDIN", mode) as f:
            f.write(found_stdin_data)
        cat_in = "cat STDIN | "

    found_cmd_filtered = []
    for cmd in found_cmd:
        cmd = str(cmd).replace(canon_scripts_dir_string, target_scripts_dir)
        found_cmd_filtered.append(cmd)

    with open(output, "w", encoding="utf8") as f:
        f.write("#!/bin/sh\n")
        for key, value in filtered_env.items():
            f.write(f"export {key}={shlex.quote(str(value))}\n")
        f.write("\n")
        f.write(cat_in)
        f.write(shlex.join([str(e) for e in found_cmd_filtered]))
        f.write("\n")

    if hasattr(os, "chmod"):
        os.chmod(output, 0o755)

    logger.info("Ejected successfully.")


@cli.command("create-reproducible")
def create_reproducible(
    step_dir_arg: Annotated[
        Path | None,
        typer.Argument(
            file_okay=False,
            dir_okay=True,
            help="A step directory from a previous run.",
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=False,
            dir_okay=True,
            help="The output directory for the reproducible.",
        ),
    ] = Path("reproducible"),
    step_dir: Annotated[
        Path | None,
        typer.Option(
            "--step-dir",
            "-d",
            file_okay=False,
            dir_okay=True,
            help="A step directory from a previous run.",
        ),
    ] = None,
    id: Annotated[
        str | None,
        typer.Option(
            "--id",
            help=(
                "The registered step ID. May be omitted when config.meta.step "
                "provides it."
            ),
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="A step-specific config.json file.",
        ),
    ] = None,
    state_in: Annotated[
        Path | None,
        typer.Option(
            "--state-in",
            "-i",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ] = None,
    include_pdk: Annotated[bool, typer.Option("--include-pdk/--no-include-pdk")] = True,
    flatten: Annotated[bool, typer.Option("--flatten/--no-flatten")] = False,
) -> None:
    """
    Creates a filesystem-independent step reproducible.

    The input can be either:

    * Both a configuration object (--config) and an input state (--state-in)

    * A step directory (--step-dir) generated from a previous run
      * If not provided, the fallbacks are, in order of priority:
        * The first non-flag argument
        * The current working directory

    These reproducibles are filesystem-independent, i.e. they can be run
    on any computer that has the appropriate version of LibreLane installed
    (as well as the underlying utility for that specific step.)

    The reproducible will report an error if LibreLane is not installed and will
    emit a warning if the installed version of LibreLane mismatches the one
    declared in the config file.
    """
    selected_step_dir = step_dir or step_dir_arg
    if selected_step_dir is None and (config is not None or state_in is not None):
        if config is None or state_in is None:
            logger.error(
                "Both --config and --state-in must be provided when --step-dir "
                "is omitted."
            )
            raise typer.Exit(-1)
    else:
        selected_step_dir = selected_step_dir or Path.cwd()
        if config is None:
            config = selected_step_dir / "config.json"
        if state_in is None:
            state_in = selected_step_dir / "state_in.json"

    assert config is not None
    assert state_in is not None
    step = load_step_from_inputs(id, config, state_in)
    step.create_reproducible(output, include_pdk, flatten=flatten)


@cli.command("create-test", hidden=True)
def create_test(
    step_dir_arg: Annotated[
        Path | None,
        typer.Argument(file_okay=False, dir_okay=True),
    ] = None,
    step_dir: Annotated[
        Path | None,
        typer.Option(
            "--step-dir",
            "-d",
            file_okay=False,
            dir_okay=True,
            help="The step directory from which to create the test.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", file_okay=False, dir_okay=True),
    ] = None,
) -> None:
    selected_step_dir = step_dir or step_dir_arg or Path.cwd()
    config = selected_step_dir / "config.json"
    state_in = selected_step_dir / "state_in.json"
    selected_output = output or selected_step_dir / "test"

    step = load_step_from_inputs(None, config, state_in)
    step.create_reproducible(selected_output, include_pdk=False, flatten=True)
    os.remove(selected_output / "run_ol.sh")
    if (selected_output / "base.sdc").exists():
        os.remove(selected_output / "base.sdc")


if __name__ == "__main__":
    cli()
