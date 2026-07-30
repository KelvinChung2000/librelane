# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane
#
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
"""
The ``librelane run`` subcommand: turn configuration files into a flow run.

This is also what a bare ``librelane <config.json>`` dispatches to, via
:class:`librelane.cli._app.DefaultToRunGroup`.
"""

from dataclasses import dataclass, replace
import glob
from importlib.resources import files
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

from loguru import logger
import typer

from .. import common
from ..__version__ import __version__
from ..config import Config, InvalidConfig, PassedDirectoryError
from ..container import run_in_container
from ..flows import Explanation, Flow, FlowError, FlowException, SequentialFlow
from ..state import DesignFormat, State
from .options import (
    CondensedOption,
    ConfigFilesArgument,
    ConfigOverridesOption,
    ContainerizedOption,
    ContainerMountsOption,
    ContainerTtyOption,
    DesignDirOption,
    EfSaveViewsOption,
    FlowNameOption,
    ForceRunDirOption,
    FromOption,
    InitialStateElementOption,
    InitialStateFilesOption,
    JobsOption,
    LastRunOption,
    LogLevelOption,
    OverwriteOption,
    PadOption,
    PdkOption,
    PdkRootOption,
    ReproducibleOption,
    RunExampleOption,
    RunTagOption,
    SaveViewsOption,
    SclOption,
    ShowProgressBarOption,
    ExplainOption,
    SkipOption,
    SmokeTestOption,
    ToOption,
    UseCielOption,
)
from .runtime import (
    DEFAULT_JOBS,
    ResolvedPdkOptions,
    apply_runtime_options,
    load_initial_state,
    resolve_pdk_options,
    validate_flow_name,
)


@dataclass(frozen=True)
class FlowRequest:
    """
    Everything :func:`start_flow` needs, gathered once.

    Bundling these keeps the two callers -- a normal run and a bundled example
    run -- from having to restate twenty parameters, and lets the example path
    say precisely which of them it discards via :func:`dataclasses.replace`.
    """

    config_files: tuple[str, ...]
    flow_name: str | None
    pdk: ResolvedPdkOptions
    tag: str | None
    last_run: bool
    frm: str | None
    to: str | None
    skip: tuple[str, ...]
    explain: bool
    overwrite: bool
    reproducible: str | None
    initial_state: State | None
    initial_state_overrides: tuple[str, ...]
    config_overrides: tuple[str, ...]
    design_dir: str | None
    force_run_dir: str | None
    save_views_to: str | None
    ef_save_views_to: str | None


def select_flow(request: FlowRequest) -> type[Flow]:
    """Pick the flow class named by --flow, else by the config file's meta object."""
    target_flow: type[Flow] | None = Flow.factory.get("Classic")

    for config_file in request.config_files:
        if meta := Config.get_meta(config_file):
            if meta.flow is not None:
                # `Meta` is a plain dataclass, so narrowing the annotation does
                # not reject a list on its own. Falling through would silently
                # run Classic instead of what the configuration named.
                if not isinstance(meta.flow, str):
                    logger.error(
                        f"'meta.flow' must name a registered flow, but got a "
                        f"{type(meta.flow).__name__}. Building an anonymous "
                        f"flow from a list of step IDs is no longer supported; "
                        f"declare a flow class and name it here instead."
                    )
                    raise typer.Exit(1)
                if found := Flow.factory.get(meta.flow):
                    target_flow = found
                else:
                    logger.error(
                        f"Unknown flow '{meta.flow}' specified in the "
                        "configuration file's 'meta' object."
                    )
                    raise typer.Exit(1)

    if request.flow_name is not None:
        if found := Flow.factory.get(request.flow_name):
            target_flow = found
        else:
            logger.error(f"Unknown flow '{request.flow_name}'.")
            raise typer.Exit(1)

    assert target_flow is not None, (
        "Target flow is unexpectedly None. Please report this as a bug."
    )
    return target_flow


def apply_initial_state_overrides(request: FlowRequest) -> State | None:
    """Fold every ``DESIGN_FORMAT_ID=PATH`` override into the initial state."""
    if not request.initial_state_overrides:
        return request.initial_state

    state = request.initial_state if request.initial_state is not None else State()
    overrides = {}
    for element in request.initial_state_overrides:
        design_format_id, separator, path = element.partition("=")
        if not separator:
            logger.error(f"Invalid initial state element override: '{element}'.")
            raise typer.Exit(1)
        design_format = DesignFormat.factory.get(design_format_id)
        if design_format is None:
            logger.error(f"Invalid design format ID: '{design_format_id}'.")
            raise typer.Exit(1)
        overrides[design_format] = common.Path(path)

    return type(state)(state, overrides=overrides)


def format_explanation(explanation: Explanation) -> str:
    """
    Renders an :class:`librelane.flows.Explanation` as a fixed-width table.

    :param explanation: What the flow reported.
    :returns: The table, without a trailing newline.
    """
    width = max((len(d.step_id) for d in explanation.steps), default=0)
    lines = [f"{'STEP'.ljust(width)}  RUN  MECHANISM  REASON"]
    for disposition in explanation.steps:
        mark = "yes" if disposition.will_run else "no "
        mechanism = (disposition.mechanism or "").ljust(9)
        lines.append(
            f"{disposition.step_id.ljust(width)}  {mark}  {mechanism}  "
            f"{disposition.reason}"
        )
    if explanation.unselected_stages:
        lines.append("")
        lines.append(
            "Stages contributing no steps: " + ", ".join(explanation.unselected_stages)
        )
    return "\n".join(lines)


def start_flow(request: FlowRequest) -> None:
    """Build the requested flow, run it, and save any requested view snapshots."""
    try:
        if not request.config_files:
            logger.error("No config file(s) have been provided.")
            raise typer.Exit(1)

        target_flow = select_flow(request)
        initial_state = apply_initial_state_overrides(request)

        flow = target_flow(
            list(request.config_files),
            pdk_root=request.pdk.pdk_root,
            pdk=request.pdk.pdk,
            scl=request.pdk.scl,
            pad=request.pdk.pad,
            config_override_strings=list(request.config_overrides),
            design_dir=request.design_dir,
        )
    except PassedDirectoryError as error:
        logger.error(error)
        logger.info(
            "If this is a design directory, pass it alongside valid configuration "
            f"files as '--design-dir {error.config}'."
        )
        raise typer.Exit(1) from error
    except InvalidConfig as error:
        if error.warnings:
            logger.warning("The following warnings have been generated:")
            for warning in error.warnings:
                logger.warning(warning)
        logger.error(f"Errors occurred while loading {error.config}.")
        for config_error in error.errors:
            logger.error(config_error)

        logger.error("LibreLane will now quit. Please check your configuration.")
        raise typer.Exit(1) from error
    except ValueError as error:
        logger.error(error)
        logger.debug(traceback.format_exc())
        logger.error("LibreLane will now quit.")
        raise typer.Exit(1) from error

    if request.explain:
        if not isinstance(flow, SequentialFlow):
            logger.error(
                f"--explain requires a sequential flow; '{type(flow).__name__}' "
                f"writes its own run() and has no step list to predict."
            )
            raise typer.Exit(1)
        typer.echo(
            format_explanation(
                flow.explain(
                    frm=request.frm,
                    to=request.to,
                    skip=list(request.skip),
                )
            )
        )
        raise typer.Exit(0)

    try:
        state_out = flow.start(
            tag=request.tag,
            last_run=request.last_run,
            frm=request.frm,
            to=request.to,
            skip=request.skip,
            with_initial_state=initial_state,
            reproducible=request.reproducible,
            _force_run_dir=request.force_run_dir,
            overwrite=request.overwrite,
        )
    except FlowException as error:
        logger.error(f"The flow encountered an unexpected error:\n{error}")
        logger.error("LibreLane will now quit.")
        raise typer.Exit(1) from error
    except FlowError as error:
        logger.error(f"The flow encountered the following error:\n{error}")
        logger.error("LibreLane will now quit.")
        raise typer.Exit(2) from error

    if request.save_views_to:
        state_out.save_snapshot(request.save_views_to)
    if request.ef_save_views_to:
        flow._save_snapshot_ef(request.ef_save_views_to)


def run_included_example(
    request: FlowRequest,
    smoke_test: bool,
    example: str | None,
) -> None:
    """Copy a bundled example next to the user, run it, and report the outcome."""
    value = "spm" if smoke_test else example
    assert value is not None, "neither --smoke-test nor --run-example was given"

    example_resource = files("librelane").joinpath("examples", value)
    if not example_resource.is_dir():
        typer.echo(f"Unknown example '{value}'.", err=True)
        raise typer.Exit(1)

    final_path = os.path.join(os.getcwd(), value)
    if smoke_test:
        # The smoke test proves the installation works, so it runs the example
        # exactly as shipped: every option that would steer the flow elsewhere
        # is dropped, and the results are thrown away afterwards.
        final_path = os.path.join(tempfile.mkdtemp("librelane"), "smoke_test_design")
        request = replace(
            request,
            flow_name=None,
            pdk=replace(request.pdk, scl=None, pad=None),
            tag=None,
            last_run=False,
            frm=None,
            to=None,
            reproducible=None,
            skip=(),
            explain=False,
            initial_state=None,
            config_overrides=(),
            force_run_dir=None,
            design_dir=None,
        )

    status = 0
    try:
        if os.path.isdir(final_path):
            typer.echo(f"A directory named {value} already exists.", err=True)
            raise typer.Exit(1)

        common.recreate_tree(example_resource, final_path)
        config_file = glob.glob(os.path.join(final_path, "config.*"))[0]
        start_flow(replace(request, config_files=(config_file,)))
        if smoke_test:
            logger.info("Smoke test passed.")
    except KeyboardInterrupt:
        if smoke_test:
            logger.info("Smoke test aborted.")
        status = -1
    finally:
        if smoke_test:
            shutil.rmtree(final_path, ignore_errors=True)

    raise typer.Exit(status)


def run_containerized(
    *,
    pdk_root: Path | None,
    mounts: list[str],
    tty: bool,
) -> None:
    """Re-enter this invocation inside the matching LibreLane container image."""
    try:
        containerized_index = next(
            index
            for index, argument in enumerate(sys.argv)
            if argument in {"--dockerized", "--containerized"}
        )
    except StopIteration as error:
        raise RuntimeError("containerized invocation flag was not found") from error

    argv = sys.argv[containerized_index + 1 :]
    final_argv = ["zsh"] if not argv else ["python3", "-m", "librelane", *argv]
    container_image = os.getenv(
        "LIBRELANE_IMAGE_OVERRIDE", f"ghcr.io/librelane/librelane:{__version__}"
    )

    try:
        run_in_container(
            container_image,
            final_argv,
            pdk_root=str(pdk_root) if pdk_root is not None else None,
            other_mounts=mounts,
            tty=tty,
        )
    except ValueError as error:
        logger.error(error)
        raise typer.Exit(1) from error
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        logger.error(error)
        raise typer.Exit(1) from error

    raise typer.Exit(0)


def run(
    config_files: ConfigFilesArgument = None,
    flow_name: FlowNameOption = None,
    config_override_strings: ConfigOverridesOption = None,
    with_initial_state_files: InitialStateFilesOption = None,
    initial_state_element_override: InitialStateElementOption = None,
    design_dir: DesignDirOption = None,
    tag: RunTagOption = None,
    last_run: LastRunOption = False,
    frm: FromOption = None,
    to: ToOption = None,
    skip: SkipOption = None,
    explain: ExplainOption = False,
    overwrite: OverwriteOption = False,
    reproducible: ReproducibleOption = None,
    log_level: LogLevelOption = None,
    show_progress_bar: ShowProgressBarOption = None,
    condensed: CondensedOption = False,
    jobs: JobsOption = DEFAULT_JOBS,
    use_ciel: UseCielOption = True,
    pdk_root: PdkRootOption = None,
    pdk: PdkOption = "sky130A",
    scl: SclOption = None,
    pad: PadOption = None,
    view_save_path: SaveViewsOption = None,
    ef_view_save_path: EfSaveViewsOption = None,
    docker_mounts: ContainerMountsOption = None,
    docker_tty: ContainerTtyOption = True,
    dockerized: ContainerizedOption = False,
    smoke_test: SmokeTestOption = False,
    run_example: RunExampleOption = None,
    force_run_dir: ForceRunDirOption = None,
) -> None:
    """
    Run a LibreLane flow using one or more design configuration files.

    The configuration files may also be passed to [b]librelane[/b] directly,
    without naming this subcommand.
    """
    selected_actions = sum((dockerized, smoke_test, run_example is not None))
    if selected_actions > 1:
        raise typer.BadParameter(
            "--dockerized, --smoke-test, and --run-example are mutually exclusive"
        )
    if tag is not None and last_run:
        raise typer.BadParameter("--run-tag and --last-run are mutually exclusive")

    if dockerized:
        run_containerized(
            pdk_root=pdk_root,
            mounts=docker_mounts or [],
            tty=docker_tty,
        )

    apply_runtime_options(
        log_level=log_level,
        show_progress_bar=show_progress_bar,
        condensed=condensed,
        jobs=jobs,
    )
    request = FlowRequest(
        config_files=tuple(str(path) for path in config_files or []),
        flow_name=validate_flow_name(flow_name),
        pdk=resolve_pdk_options(
            use_ciel=use_ciel,
            pdk_root=pdk_root,
            pdk=pdk,
            scl=scl,
            pad=pad,
        ),
        tag=tag,
        last_run=last_run,
        frm=frm,
        to=to,
        skip=tuple(skip or []),
        explain=explain,
        overwrite=overwrite,
        reproducible=reproducible,
        initial_state=load_initial_state(with_initial_state_files),
        initial_state_overrides=tuple(initial_state_element_override or []),
        config_overrides=tuple(config_override_strings or []),
        design_dir=str(design_dir) if design_dir is not None else None,
        force_run_dir=str(force_run_dir) if force_run_dir is not None else None,
        save_views_to=str(view_save_path) if view_save_path is not None else None,
        ef_save_views_to=(
            str(ef_view_save_path) if ef_view_save_path is not None else None
        ),
    )

    if smoke_test or run_example is not None:
        run_included_example(request, smoke_test, run_example)
    else:
        start_flow(request)
