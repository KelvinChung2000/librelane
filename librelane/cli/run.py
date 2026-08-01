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
from inspect import Parameter, signature
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
from typing import Any

from loguru import logger
import typer

from librelane import common
from librelane.__version__ import __version__
from librelane.config import Config, InvalidConfig, PassedDirectoryError
from librelane.container import run_in_container
from librelane.flows import (
    Explanation,
    Flow,
    FlowError,
    FlowException,
    VariableDisposition,
)
from librelane.flows.engine import Workflow
from librelane.flows.spec import FlowSpec
from librelane.state import DesignFormat, State
from librelane.cli.options import (
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
    InitialStateElementOption,
    InitialStateFilesOption,
    InvalidateOption,
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
    ExplainVariablesOption,
    SkipOption,
    SmokeTestOption,
    TargetOption,
    UseCielOption,
)
from librelane.cli.runtime import (
    DEFAULT_JOBS,
    ResolvedPdkOptions,
    apply_runtime_options,
    load_initial_state,
    resolve_pdk_options,
    validate_flow_name,
)


def _named_parameters(method: Any) -> frozenset[str]:
    """
    Returns
    -------
    frozenset[str]
        Every parameter ``method`` declares by name, which is to say every
        keyword it can be relied on to read rather than swallow.
    """
    return frozenset(
        name
        for name, parameter in signature(method).parameters.items()
        if parameter.kind is not Parameter.VAR_KEYWORD
    )


#: Every keyword this module may hand to a workflow to shape a run: one both
#: :meth:`librelane.flows.engine.Workflow.run` and
#: :meth:`librelane.flows.engine.Workflow.explain` declare by name. Read from
#: the engine rather than restated, so that renaming one there is caught here
#: rather than turning a command-line option into a silent no-op, and
#: intersected because the same keywords go to both: one the explanation did
#: not declare would describe a different invocation from the one the run
#: performs. See :func:`bind_workflow_arguments` for why that is possible at
#: all.
_WORKFLOW_RUN_PARAMETERS = _named_parameters(Workflow.run) & _named_parameters(
    Workflow.explain
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
    target: tuple[str, ...]
    invalidate: tuple[str, ...]
    skip: tuple[str, ...]
    explain: bool
    explain_variables: bool
    overwrite: bool
    reproducible: str | None
    initial_state: State | None
    initial_state_overrides: tuple[str, ...]
    config_overrides: tuple[str, ...]
    design_dir: str | None
    force_run_dir: str | None
    save_views_to: str | None
    ef_save_views_to: str | None


def select_flow(request: FlowRequest) -> FlowSpec:
    """
    Picks the flow document named by ``--flow``, else by the configuration
    file's ``meta`` object, else Classic.

    Parameters
    ----------
    request : FlowRequest
        The gathered invocation.

    Returns
    -------
    FlowSpec
        The document to run.
    """
    target_flow: FlowSpec | None = Flow.factory.get("Classic")

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
                        f"configuration file's 'meta' object. Registered "
                        f"flows: {', '.join(Flow.factory.list())}."
                    )
                    raise typer.Exit(1)

    if request.flow_name is not None:
        if found := Flow.factory.get(request.flow_name):
            target_flow = found
        else:
            logger.error(
                f"Unknown flow '{request.flow_name}'. Registered flows: "
                f"{', '.join(Flow.factory.list())}."
            )
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
        overrides[design_format] = Path(path)

    return type(state)(state, overrides=overrides)


def format_job_explanation(explanation: Explanation) -> str:
    """
    Renders the job half of an :class:`librelane.flows.Explanation` as a
    fixed-width table.

    Parameters
    ----------
    explanation : Explanation
        What the workflow reported.

    Returns
    -------
    str
        The table, without a trailing newline.
    """
    # Every width is measured over the header as well as the rows. A column
    # whose widest value is narrower than its own title -- a document of jobs
    # with short names, or one nothing depends on -- would otherwise leave the
    # header a character wider than the rows beneath it, and each column after
    # it out of line. The mechanism is measured for the same reason a constant
    # would not do: 'not-in-reproducible' is wider than any column width
    # somebody would have picked by hand.
    width = max([len("JOB"), *(len(d.job_id) for d in explanation.jobs)])
    needs_width = max(
        [len("NEEDS"), *(len(" ".join(d.needs) or "-") for d in explanation.jobs)]
    )
    mechanism_width = max(
        [len("MECHANISM"), *(len(d.mechanism or "") for d in explanation.jobs)]
    )
    lines = [
        f"{'JOB'.ljust(width)}  RUN  {'MECHANISM'.ljust(mechanism_width)} "
        f"{'NEEDS'.ljust(needs_width)}  REASON"
    ]
    for disposition in explanation.jobs:
        mark = "yes" if disposition.will_run else "no "
        mechanism = (disposition.mechanism or "").ljust(mechanism_width)
        needs = (" ".join(disposition.needs) or "-").ljust(needs_width)
        lines.append(
            f"{disposition.job_id.ljust(width)}  {mark}  {mechanism} "
            f"{needs}  {disposition.reason}"
        )
    return "\n".join(lines)


#: How many job names the reach column spells out before it rolls them up into
#: the class that declares the variable. Thirteen variables are declared on
#: ``OpenROADStep`` and read by 31 of Classic's jobs, and 31 names per row is
#: not something a reader takes in; "read by all 31 OpenROAD-based jobs" is the
#: same fact in a form they can. At or below this, the names are strictly more
#: information than the class, so they are what gets printed.
_MAX_LISTED_REACH = 4

#: How wide the value column may grow. A handful of PDK variables hold nested
#: tables thousands of characters long, and one of them sets the column width
#: for every other row in the table.
_MAX_RENDERED_VALUE = 60


def _format_reach(disposition: VariableDisposition) -> str:
    """
    Parameters
    ----------
    disposition : VariableDisposition
        The row to describe.

    Returns
    -------
    str
        Who can read this variable, as one of the three answers a reach has:
        every job because the variable is universal, every job of one step
        family, or a list of job ids.
    """
    if disposition.universal:
        # "all 1 jobs" on a single-job document reads as a rendering bug and
        # invites the reader to wonder what the other jobs are.
        if len(disposition.reach) == 1:
            return "universal, read by the only job"
        return f"universal, read by all {len(disposition.reach)} jobs"
    if not disposition.reach:
        return "the flow itself"
    if (
        disposition.declared_by is not None
        and len(disposition.reach) > _MAX_LISTED_REACH
    ):
        return (
            f"read by all {len(disposition.reach)} {disposition.declared_by}-based jobs"
        )
    return ", ".join(disposition.reach)


def format_variable_explanation(explanation: Explanation) -> str:
    """
    Renders the variable half of an :class:`librelane.flows.Explanation` as a
    fixed-width table.

    Every row is printed, including the variables sitting at their defaults. A
    variable at its default is exactly what somebody debugging an unexpected
    value is looking for, and a table that dropped those rows could not say
    whether a variable was defaulted or never declared.

    Parameters
    ----------
    explanation : Explanation
        What the workflow reported.

    Returns
    -------
    str
        The table, without a trailing newline.
    """
    header = ("VARIABLE", "VALUE", "ORIGIN", "REACH")
    rows = [
        (
            disposition.name,
            _truncated(str(disposition.value)),
            disposition.origin,
            _format_reach(disposition),
        )
        for disposition in explanation.variables
    ]
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
        for row in (header, *rows)
    )


def _truncated(value: str) -> str:
    """
    Returns
    -------
    str
        ``value``, cut to :data:`_MAX_RENDERED_VALUE` characters with an
        ellipsis marking what was left out.
    """
    if len(value) <= _MAX_RENDERED_VALUE:
        return value
    return value[: _MAX_RENDERED_VALUE - 1] + "…"


def bind_workflow_arguments(**arguments: Any) -> dict[str, Any]:
    """
    Checks that every flow-control keyword this module hands to
    :meth:`librelane.flows.Flow.start` and to
    :meth:`librelane.flows.engine.Workflow.explain` is one both
    :meth:`librelane.flows.engine.Workflow.run` and ``explain`` declare by
    name.

    ``Flow.start`` forwards its ``**kwargs`` into ``run`` unchanged, and ``run``
    must keep a ``**kwargs`` of its own because ``start`` always passes
    ``initial_state_given=`` and ``starting_ordinal=``. A misspelled keyword is
    therefore accepted in silence and does nothing at all, and the command line
    is the only layer that can refuse it.

    Parameters
    ----------
    **arguments
        The keywords to bind.

    Returns
    -------
    dict[str, Any]
        The same keywords, once every one of them is bound.

    Raises
    ------
    AssertionError
        If any keyword would land in ``run``'s ``**kwargs``, or is not one
        ``explain`` declares. This is a defect in LibreLane rather than in an
        invocation: nothing a user types reaches these names.
    """
    unbound = sorted(set(arguments) - _WORKFLOW_RUN_PARAMETERS)
    assert not unbound, (
        f"{unbound} is not a named parameter of both Workflow.run and "
        f"Workflow.explain, so it would be swallowed by run's '**kwargs' or "
        f"refused by explain. Please report this as a bug."
    )
    return arguments


def start_flow(request: FlowRequest) -> None:
    """Build the requested flow, run it, and save any requested view snapshots."""
    try:
        if not request.config_files:
            logger.error("No config file(s) have been provided.")
            raise typer.Exit(1)

        initial_state = apply_initial_state_overrides(request)

        flow = Workflow(
            select_flow(request),
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
    except FlowError as error:
        # Resolving the document against the registries and resolving `TOOLS`
        # against the document both raise this, and neither is a `ValueError`.
        # Every one of those messages names the offending key and the legal
        # alternatives, which is worth nothing arriving as the last line of a
        # traceback.
        logger.error(error)
        logger.error("LibreLane will now quit.")
        raise typer.Exit(1) from error

    # `run` reads `None` as "unrestricted" and an empty collection as
    # "restricted to nothing": `target=()` selects no job at all, builds an
    # empty net and dies in the sink join. The request holds tuples, so this is
    # where an option nobody gave has to become `None` again.
    #
    # Bound once and handed to whichever of the two runs, because `explain`
    # describes the invocation these arguments make: an explanation that saw
    # fewer of them than the run would describe a different invocation, and
    # would say every job runs where the run in fact stops at the first.
    flow_control = bind_workflow_arguments(
        target=list(request.target) or None,
        invalidate=list(request.invalidate) or None,
        skip=list(request.skip) or None,
        reproducible=request.reproducible,
    )

    if request.explain or request.explain_variables:
        try:
            explanation = flow.explain(
                variables=request.explain_variables, **flow_control
            )
        except FlowException as error:
            # `explain` refuses whatever `run` refuses, so the same mistyped
            # option that prints one line without `--explain` has to print one
            # line with it.
            logger.error(error)
            logger.error("LibreLane will now quit.")
            raise typer.Exit(1) from error
        # Each option selects a table; neither filters the other's rows. Given
        # both, both are printed, jobs first, because the reach column of the
        # variable table names the jobs of the one above it.
        if request.explain:
            typer.echo(format_job_explanation(explanation))
        if request.explain_variables:
            typer.echo(format_variable_explanation(explanation))
        raise typer.Exit(0)

    try:
        state_out = flow.start(
            tag=request.tag,
            last_run=request.last_run,
            with_initial_state=initial_state,
            _force_run_dir=request.force_run_dir,
            overwrite=request.overwrite,
            **flow_control,
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
            target=(),
            invalidate=(),
            reproducible=None,
            skip=(),
            explain=False,
            explain_variables=False,
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
    target: TargetOption = None,
    invalidate: InvalidateOption = None,
    skip: SkipOption = None,
    explain: ExplainOption = False,
    explain_variables: ExplainVariablesOption = False,
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
        target=tuple(target or []),
        invalidate=tuple(invalidate or []),
        skip=tuple(skip or []),
        explain=explain,
        explain_variables=explain_variables,
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
