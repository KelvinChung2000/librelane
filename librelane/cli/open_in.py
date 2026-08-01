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
The ``librelane open`` command: load a finished run into a tool.

Opening a run in a viewer is not a flow. It runs one step, produces no view
and no metric, advances nothing, and its whole purpose is to hand the terminal
or the display to another program and wait. Five one-job workflow documents
used to say this -- ``OpenInKLayout`` and its four siblings -- which put a
viewer on the ``--flow`` list beside ``Classic`` and gave it a run directory,
a net, a join and a resume key it had no use for.

What replaces them is this module: one table of viewers and one command that
runs the step the table names.
"""

import os
import pathlib
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

import typer
from loguru import logger

from librelane.common import Toolbox, get_latest_file, mkdirp
from librelane.config import Config, InvalidConfig, universal_flow_config_variables
from librelane.cli.options import (
    ConfigFilesArgument,
    ConfigOverridesOption,
    CondensedOption,
    DesignDirOption,
    InitialStateFilesOption,
    LastRunOption,
    LogLevelOption,
    PadOption,
    PdkOption,
    PdkRootOption,
    RunTagOption,
    SclOption,
    UseCielOption,
)
from librelane.cli.runtime import (
    apply_runtime_options,
    load_initial_state,
    resolve_pdk_options,
)
from librelane.state import State
from librelane.steps import Step
from librelane.steps.step import StepError, StepException


class ViewerName(str, Enum):
    """
    What a user types after ``librelane open``.

    Spelled in lowercase with dashes, like every other thing the command line
    accepts, rather than in the ``OpenInOpenSTAConsole`` casing the deleted
    documents registered under.
    """

    klayout = "klayout"
    magic = "magic"
    openroad = "openroad"
    openroad_console = "openroad-console"
    opensta_console = "opensta-console"


@dataclass(frozen=True)
class Viewer:
    """
    One tool a finished run can be opened in.

    Parameters
    ----------
    step_id : str
        The registered step that opens it. It is expected to declare no
        outputs: this command discards whatever it returns, because a viewer
        that changed the run's state would need the run directory's ordering
        rules, and then it would be a flow after all.
    summary : str
        What the user sees in ``--help``, one line, no trailing full stop.
    """

    step_id: str
    summary: str


#: Every viewer, keyed by what the user types. Adding one is a line here plus a
#: member of :class:`ViewerName`; there is no second place to register it.
VIEWERS: dict[ViewerName, Viewer] = {
    ViewerName.klayout: Viewer(
        "KLayout.OpenGUI",
        "the KLayout GUI, on the GDS if the state has one and the DEF otherwise",
    ),
    ViewerName.magic: Viewer(
        "Magic.OpenGUI",
        "the Magic GUI, on the GDS or the DEF",
    ),
    ViewerName.openroad: Viewer(
        "OpenROAD.OpenGUI",
        "the OpenROAD GUI, on the ODB",
    ),
    ViewerName.openroad_console: Viewer(
        "OpenROAD.OpenConsole",
        "an interactive OpenROAD Tcl console, on the ODB",
    ),
    ViewerName.opensta_console: Viewer(
        "OpenROAD.OpenSTAConsole",
        "an interactive OpenSTA console, on the netlist and its parasitics",
    ),
}


#: Built from :data:`VIEWERS` so that adding a viewer documents it, rather than
#: leaving a second list to fall out of step with the first.
_VIEWER_HELP = "The tool to open the run in. " + "; ".join(
    f"[b]{name.value}[/b] opens {VIEWERS[name].summary}" for name in ViewerName
)

ViewerArgument = Annotated[
    ViewerName,
    typer.Argument(
        show_default=False,
        help=_VIEWER_HELP,
    ),
]


def resolve_run_dir(design_dir: pathlib.Path, tag: str | None, last_run: bool):
    """
    Pick the run directory to open.

    Parameters
    ----------
    design_dir : pathlib.Path
        The resolved ``DESIGN_DIR``, whose ``runs/`` holds every run.
    tag : str | None
        The run tag named by ``--run-tag``.
    last_run : bool
        Whether ``--last-run`` was given.

    Returns
    -------
    pathlib.Path
        The run directory.

    Raises
    ------
    typer.Exit
        If neither option was given, if both were, or if the named run does
        not exist. There is no default: a viewer with nothing to view is not
        a useful thing to start, so the command says which runs there are
        instead of opening an empty window.
    """
    runs_dir = design_dir / "runs"
    available = (
        sorted(entry.name for entry in runs_dir.iterdir() if entry.is_dir())
        if runs_dir.is_dir()
        else []
    )

    if last_run:
        if not available:
            logger.error(f"No runs exist under '{runs_dir}'.")
            raise typer.Exit(1)
        return max(
            (runs_dir / name for name in available),
            key=lambda run: run.stat().st_mtime,
        )

    if tag is None:
        logger.error(
            "One of '--run-tag' or '--last-run' is required: this command opens "
            "a run that has already happened."
        )
        if available:
            logger.info(f"Available runs: {', '.join(available)}.")
        raise typer.Exit(1)

    run_dir = runs_dir / tag
    if not run_dir.is_dir():
        logger.error(f"No run tagged '{tag}' exists under '{runs_dir}'.")
        if available:
            logger.info(f"Available runs: {', '.join(available)}.")
        raise typer.Exit(1)
    return run_dir


def resolve_state(run_dir: pathlib.Path, given: State | None) -> State:
    """
    Pick the state to open.

    Parameters
    ----------
    run_dir : pathlib.Path
        The run directory chosen by :func:`resolve_run_dir`.
    given : State | None
        The state ``--with-initial-state`` supplied, if any.

    Returns
    -------
    State
        ``given`` when it was supplied, else the most recently written state
        in the run, which is the same file ``librelane state latest`` prints.
        That is what makes the bare form open the design as the run left it.

    Raises
    ------
    typer.Exit
        If the run holds no state at all, which means nothing in it ever
        completed a step.
    """
    if given is not None:
        return given

    latest = get_latest_file(run_dir, "state_*.json")
    if latest is None:
        logger.error(
            f"No state was found in '{run_dir}', so there is nothing to open. "
            f"Name one explicitly with '--with-initial-state'."
        )
        raise typer.Exit(1)

    logger.info(f"Opening the state at '{latest}'.")
    state = load_initial_state([latest])
    assert state is not None, "load_initial_state returns None only for an empty list"
    return state


def open_in(
    viewer: ViewerArgument,
    config_files: ConfigFilesArgument = None,
    tag: RunTagOption = None,
    last_run: LastRunOption = False,
    with_initial_state_files: InitialStateFilesOption = None,
    config_override_strings: ConfigOverridesOption = None,
    design_dir: DesignDirOption = None,
    use_ciel: UseCielOption = True,
    pdk_root: PdkRootOption = None,
    pdk: PdkOption = "sky130A",
    scl: SclOption = None,
    pad: PadOption = None,
    log_level: LogLevelOption = None,
    condensed: CondensedOption = False,
) -> None:
    """
    Open a finished run in a GUI or an interactive console.

    The run is named by [b]--run-tag[/b] or [b]--last-run[/b], and the state
    opened is the last one that run wrote unless
    [b]--with-initial-state[/b] names another.
    """
    if tag is not None and last_run:
        raise typer.BadParameter("--run-tag and --last-run are mutually exclusive")
    if not config_files:
        logger.error("No config file(s) have been provided.")
        raise typer.Exit(1)

    apply_runtime_options(
        log_level=log_level,
        # A viewer runs one step and then waits for a human. A progress bar
        # over that is a bar that fills once and then sits at 100% for as long
        # as the window is open, on top of the console the step may itself be
        # trying to use.
        show_progress_bar=False,
        condensed=condensed,
        jobs=None,
    )

    selected = VIEWERS[viewer]
    Target = Step.factory.get(selected.step_id)
    assert Target is not None, (
        f"'{selected.step_id}' is not registered, so the VIEWERS table names a "
        f"step that does not exist."
    )

    resolved_pdk = resolve_pdk_options(
        use_ciel=use_ciel,
        pdk_root=pdk_root,
        pdk=pdk,
        scl=scl,
        pad=pad,
    )

    try:
        # Only this step's variables, plus the universal ones every step reads.
        # A flow would add every other step's here; nothing else is going to
        # run, so nothing else's configuration has to resolve, and a design
        # whose unrelated variable is malformed still opens.
        config, _ = Config.load(
            config_in=[str(path) for path in config_files],
            flow_config_vars=[
                *universal_flow_config_variables,
                *Target.config_vars,
            ],
            config_override_strings=list(config_override_strings or []),
            pdk=resolved_pdk.pdk,
            pdk_root=resolved_pdk.pdk_root,
            scl=resolved_pdk.scl,
            pad=resolved_pdk.pad,
            design_dir=str(design_dir) if design_dir is not None else None,
        )
    except InvalidConfig as error:
        for warning in error.warnings:
            logger.warning(warning)
        logger.error(f"Errors occurred while loading {error.config}.")
        for config_error in error.errors:
            logger.error(config_error)
        raise typer.Exit(1) from error
    except ValueError as error:
        logger.error(error)
        raise typer.Exit(1) from error

    run_dir = resolve_run_dir(pathlib.Path(config["DESIGN_DIR"]), tag, last_run)
    state_in = resolve_state(run_dir, load_initial_state(with_initial_state_files))

    # Inside the run being looked at, so the tool's log sits with the design it
    # was opened on, and named for the viewer rather than with a step ordinal:
    # nothing here is a step of that run, and reopening should reuse the
    # directory rather than leave one behind per look.
    step_dir = run_dir / f"open-{viewer.value}"
    mkdirp(step_dir)

    step = Target(config=config, state_in=state_in)
    try:
        step.start(
            toolbox=Toolbox(os.fspath(step_dir / "tmp")),
            step_dir=step_dir,
        )
    except StepException as error:
        logger.error(f"An unexpected error occurred while opening {viewer.value}:")
        logger.error(error)
        raise typer.Exit(1) from error
    except StepError as error:
        logger.error(f"An error occurred while opening {viewer.value}:")
        logger.error(error)
        raise typer.Exit(1) from error
