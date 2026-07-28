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
from collections.abc import Sequence
import glob
from importlib.resources import files
import marshal
import os
from pathlib import Path
import shutil
import sys
import tempfile
from textwrap import dedent
import traceback
from typing import Annotated, Any

from loguru import logger
import typer

from . import common
from .__version__ import __version__
from .config import Config, InvalidConfig, PassedDirectoryError
from .container import run_in_container
from .flows import Flow, FlowError, FlowException, SequentialFlow
from .flows.cli import (
    DEFAULT_JOBS,
    CondensedOption,
    ConfigFilesArgument,
    ConfigOverridesOption,
    DesignDirOption,
    FlowNameOption,
    FromOption,
    InitialStateElementOption,
    InitialStateFilesOption,
    JobsOption,
    LastRunOption,
    LogLevelOption,
    OnlyOption,
    PadOption,
    PdkOption,
    PdkRootOption,
    ReproducibleOption,
    RunTagOption,
    SclOption,
    ShowProgressBarOption,
    SkipOption,
    ToOption,
    UseCielOption,
    apply_runtime_options,
    load_initial_state,
    normalize_sequential_controls,
    resolve_pdk_options,
    validate_flow_name,
)
from .plugins import discovered_plugins
from .state import DesignFormat, State


COPY_OPTIONS = "Copy final views"
CONTAINER_OPTIONS = "Containerization options"
ACTION_OPTIONS = "Actions"
DEBUG_OPTIONS = "Debug options"


SaveViewsOption = Annotated[
    Path | None,
    typer.Option(
        "--save-views-to",
        file_okay=False,
        dir_okay=True,
        help=("Copy final views here, with each format stored under its corner ID."),
        rich_help_panel=COPY_OPTIONS,
    ),
]
EfSaveViewsOption = Annotated[
    Path | None,
    typer.Option(
        "--ef-save-views-to",
        file_okay=False,
        dir_okay=True,
        help="Copy final views here in the Efabless Caravel-compatible format.",
        rich_help_panel=COPY_OPTIONS,
    ),
]
ContainerMountsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--docker-mount",
        "--container-mount",
        "-m",
        help=(
            "Mount an additional directory or pass a mount specification to the "
            "container engine. May be specified multiple times."
        ),
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
ContainerTtyOption = Annotated[
    bool,
    typer.Option(
        "--docker-tty/--docker-no-tty",
        "--container-tty/--container-no-tty",
        help="Control virtual-terminal allocation for the container.",
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
ContainerizedOption = Annotated[
    bool,
    typer.Option(
        "--dockerized",
        "--containerized",
        help="Run this invocation in the matching LibreLane container image.",
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
VersionOption = Annotated[
    bool,
    typer.Option(
        "--version",
        help="Print version and license information, then exit.",
        is_eager=True,
        rich_help_panel=ACTION_OPTIONS,
    ),
]
BareVersionOption = Annotated[
    bool,
    typer.Option("--bare-version", hidden=True, is_eager=True),
]
SmokeTestOption = Annotated[
    bool,
    typer.Option(
        "--smoke-test",
        help="Run the bundled smoke test and discard its results.",
        rich_help_panel=ACTION_OPTIONS,
    ),
]
RunExampleOption = Annotated[
    str | None,
    typer.Option(
        "--run-example",
        help="Copy and run a bundled LibreLane example.",
        rich_help_panel=ACTION_OPTIONS,
    ),
]
OverwriteOption = Annotated[
    bool,
    typer.Option("--overwrite", help="Overwrite the run if it already exists."),
]
ForceRunDirOption = Annotated[
    Path | None,
    typer.Option(
        "--force-run-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        hidden=True,
        rich_help_panel=DEBUG_OPTIONS,
    ),
]


cli = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
    help=(
        "Run a LibreLane flow from one or more design configuration files.\n\n"
        "Use 'python3 -m librelane.steps --help' for standalone step execution "
        "and reproducible commands."
    ),
)


def run(
    ctx: typer.Context,
    flow_name: str | None,
    pdk_root: str | None,
    pdk: str,
    scl: str | None,
    pad: str | None,
    config_files: Sequence[str],
    tag: str | None,
    last_run: bool,
    frm: str | None,
    to: str | None,
    skip: tuple[str, ...],
    overwrite: bool,
    reproducible: str | None,
    with_initial_state: State | None,
    config_override_strings: list[str],
    _force_run_dir: str | None,
    design_dir: str | None,
    initial_state_element_override: Sequence[str],
    view_save_path: str | None = None,
    ef_view_save_path: str | None = None,
) -> None:
    try:
        if not config_files:
            logger.error("No config file(s) have been provided.")
            raise typer.Exit(1)

        target_flow: type[Flow] | None = Flow.factory.get("Classic")

        for config_file in config_files:
            if meta := Config.get_meta(config_file):
                if isinstance(meta.flow, str):
                    if found := Flow.factory.get(meta.flow):
                        target_flow = found
                    else:
                        logger.error(
                            f"Unknown flow '{meta.flow}' specified in the "
                            "configuration file's 'meta' object."
                        )
                        raise typer.Exit(1)
                elif isinstance(meta.flow, list):
                    target_flow = SequentialFlow.make(meta.flow)
                if meta.substituting_steps is not None:
                    if meta.flow is None:
                        logger.error(
                            "Configuration has substituting_steps set with no flow."
                        )
                        raise typer.Exit(1)
                    assert target_flow is not None, (
                        "run() failed to deduce a target flow; please file an issue"
                    )
                    if issubclass(target_flow, SequentialFlow):
                        target_flow = target_flow.Substitute(meta.substituting_steps)  # type: ignore

        if flow_name is not None:
            if found := Flow.factory.get(flow_name):
                target_flow = found
            else:
                logger.error(f"Unknown flow '{flow_name}'.")
                raise typer.Exit(1)

        if initial_state_element_override:
            if with_initial_state is None:
                with_initial_state = State()
            overrides = {}
            for element in initial_state_element_override:
                element_split = element.split("=", maxsplit=1)
                if len(element_split) < 2:
                    logger.error(
                        f"Invalid initial state element override: '{element}'."
                    )
                    raise typer.Exit(1)
                df_id, path = element_split
                design_format = DesignFormat.factory.get(df_id)
                if design_format is None:
                    logger.error(f"Invalid design format ID: '{df_id}'.")
                    raise typer.Exit(1)
                overrides[design_format] = common.Path(path)

            with_initial_state = type(with_initial_state)(
                with_initial_state,
                overrides=overrides,
            )

        assert target_flow is not None, (
            "Target flow is unexpectedly None. Please report this as a bug."
        )

        kwargs: dict[str, Any] = {
            "pdk_root": pdk_root,
            "pdk": pdk,
            "scl": scl,
            "pad": pad,
            "config_override_strings": config_override_strings,
            "design_dir": design_dir,
        }
        flow = target_flow(config_files, **kwargs)
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

    try:
        state_out = flow.start(
            tag=tag,
            last_run=last_run,
            frm=frm,
            to=to,
            skip=skip,
            with_initial_state=with_initial_state,
            reproducible=reproducible,
            _force_run_dir=_force_run_dir,
            overwrite=overwrite,
        )
    except FlowException as error:
        logger.error(f"The flow encountered an unexpected error:\n{error}")
        logger.error("LibreLane will now quit.")
        raise typer.Exit(1) from error
    except FlowError as error:
        logger.error(f"The flow encountered the following error:\n{error}")
        logger.error("LibreLane will now quit.")
        raise typer.Exit(2) from error

    if view_save_path:
        state_out.save_snapshot(view_save_path)
    if ef_view_save_path:
        flow._save_snapshot_ef(ef_view_save_path)


def version_message() -> str:
    return dedent(
        f"""
        LibreLane v{__version__}

        Copyright ©2025-2026 LibreLane Contributors

        Adapted from OpenLane 2.0
        Copyright ©2020-2025 Efabless Corporation

        Available under the Apache License, version 2. Included with the source code,
        but you can also get a copy at https://www.apache.org/licenses/LICENSE-2.0

        Included tools and utilities may be distributed under stricter licenses.
        """
    ).strip()


def print_version() -> None:
    typer.echo(version_message())

    if discovered_plugins:
        typer.echo("Discovered plugins:")
        for name, module in discovered_plugins.items():
            if hasattr(module, "__version__"):
                typer.echo(f"{name} -> {module.__version__}")
            else:
                typer.echo(name)


def run_included_example(
    ctx: typer.Context,
    smoke_test: bool,
    example: str | None,
    **kwargs: Any,
) -> None:
    assert smoke_test or example is not None
    value = "spm" if smoke_test else example
    assert value is not None

    example_resource = files("librelane").joinpath("examples", value)
    if not example_resource.is_dir():
        typer.echo(f"Unknown example '{value}'.", err=True)
        raise typer.Exit(1)

    status = 0
    final_path = os.path.join(os.getcwd(), value)
    cleanup = False
    if smoke_test:
        temporary_directory = tempfile.mkdtemp("librelane")
        final_path = os.path.join(temporary_directory, "smoke_test_design")
        cleanup = True
        kwargs.update(
            flow_name=None,
            scl=None,
            pad=None,
            tag=None,
            last_run=False,
            frm=None,
            to=None,
            reproducible=None,
            skip=(),
            with_initial_state=None,
            config_override_strings=[],
            _force_run_dir=None,
            design_dir=None,
        )
    try:
        if os.path.isdir(final_path):
            typer.echo(f"A directory named {value} already exists.", err=True)
            raise typer.Exit(1)

        common.recreate_tree(example_resource, final_path)
        config_file = glob.glob(os.path.join(final_path, "config.*"))[0]
        run(ctx, config_files=[config_file], **kwargs)
        if smoke_test:
            logger.info("Smoke test passed.")
    except KeyboardInterrupt:
        if smoke_test:
            logger.info("Smoke test aborted.")
        status = -1
    finally:
        if cleanup:
            shutil.rmtree(final_path, ignore_errors=True)

    raise typer.Exit(status)


def run_containerized(
    *,
    pdk_root: Path | None,
    mounts: list[str],
    tty: bool,
) -> None:
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


@cli.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def main(
    ctx: typer.Context,
    config_files: ConfigFilesArgument = None,
    flow_name: FlowNameOption = None,
    config_override_strings: ConfigOverridesOption = None,
    with_initial_state_files: InitialStateFilesOption = None,
    design_dir: DesignDirOption = None,
    tag: RunTagOption = None,
    last_run: LastRunOption = False,
    frm: FromOption = None,
    to: ToOption = None,
    only: OnlyOption = None,
    skip: SkipOption = None,
    reproducible: ReproducibleOption = None,
    log_level: LogLevelOption = None,
    show_progress_bar: ShowProgressBarOption = None,
    condensed: CondensedOption = False,
    use_ciel: UseCielOption = True,
    pdk_root: PdkRootOption = None,
    pdk: PdkOption = "sky130A",
    scl: SclOption = None,
    pad: PadOption = None,
    jobs: JobsOption = DEFAULT_JOBS,
    initial_state_element_override: InitialStateElementOption = None,
    overwrite: OverwriteOption = False,
    force_run_dir: ForceRunDirOption = None,
    view_save_path: SaveViewsOption = None,
    ef_view_save_path: EfSaveViewsOption = None,
    docker_mounts: ContainerMountsOption = None,
    docker_tty: ContainerTtyOption = True,
    dockerized: ContainerizedOption = False,
    version: VersionOption = False,
    bare_version: BareVersionOption = False,
    smoke_test: SmokeTestOption = False,
    run_example: RunExampleOption = None,
) -> None:
    """Run a LibreLane flow using one or more design configuration files."""
    if bare_version:
        typer.echo(__version__, nl=False)
        raise typer.Exit()
    if version:
        print_version()
        raise typer.Exit()

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
    flow_name = validate_flow_name(flow_name)
    frm, to = normalize_sequential_controls(frm, to, only)
    with_initial_state = load_initial_state(with_initial_state_files)
    resolved_pdk = resolve_pdk_options(
        use_ciel=use_ciel,
        pdk_root=pdk_root,
        pdk=pdk,
        scl=scl,
        pad=pad,
    )

    string_config_files = [str(path) for path in config_files or []]
    run_kwargs: dict[str, Any] = {
        "flow_name": flow_name,
        "pdk_root": resolved_pdk.pdk_root,
        "pdk": resolved_pdk.pdk,
        "scl": resolved_pdk.scl,
        "pad": resolved_pdk.pad,
        "config_files": string_config_files,
        "tag": tag,
        "last_run": last_run,
        "frm": frm,
        "to": to,
        "skip": tuple(skip or []),
        "overwrite": overwrite,
        "reproducible": reproducible,
        "with_initial_state": with_initial_state,
        "config_override_strings": config_override_strings or [],
        "_force_run_dir": str(force_run_dir) if force_run_dir is not None else None,
        "design_dir": str(design_dir) if design_dir is not None else None,
        "initial_state_element_override": initial_state_element_override or [],
        "view_save_path": str(view_save_path) if view_save_path is not None else None,
        "ef_view_save_path": (
            str(ef_view_save_path) if ef_view_save_path is not None else None
        ),
    }

    if len(string_config_files) == 1 and string_config_files[0].endswith(".marshalled"):
        with open(string_config_files[0], "rb") as marshalled_file:
            run_kwargs = marshal.load(marshalled_file)
        run_kwargs.update(
            pdk_root=resolved_pdk.pdk_root,
            pdk=resolved_pdk.pdk,
            scl=resolved_pdk.scl,
            pad=resolved_pdk.pad,
        )

    if smoke_test or run_example is not None:
        run_kwargs.pop("config_files", None)
        run_included_example(ctx, smoke_test, run_example, **run_kwargs)
    else:
        run(ctx, **run_kwargs)


if __name__ == "__main__":
    cli()
