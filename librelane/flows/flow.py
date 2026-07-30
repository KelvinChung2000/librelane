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
from __future__ import annotations

from loguru import logger
import os
import glob
import shutil
import fnmatch
import datetime
import textwrap
import pathlib
from contextlib import ExitStack
from dataclasses import dataclass
from abc import abstractmethod, ABC
from concurrent.futures import Future
from functools import wraps
from typing import (
    ClassVar,
    TypeVar,
)
from collections.abc import Sequence, Callable

from rich.progress import (
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
    TaskID,
)
from rich.text import Text
import rich.console
from librelane.common.types import Path

from ..config import (
    AnyConfigs,
    BaseConfigModel,
    Config,
    Variable,
    model_to_variables,
    universal_flow_config_variables,
)
from ..state import State, DesignFormat
from ..steps import Step
from ..logging import (
    LiveLog,
    additional_sink,
    console as default_console,
    live as default_live,
    options,
)
from ..common import (
    get_tpe,
    mkdirp,
    protected,
    final,
    slugify,
    Fingerprinter,
    Toolbox,
)
import builtins


# Defined in ``common.errors`` so that ``stages`` can derive from them without
# importing the ``flows`` package, which depends on ``stages``. Re-exported here
# because this is their documented import site.
from ..common.errors import FlowError, FlowException  # noqa: E402, F401


T = TypeVar("T", bound=Callable)


def ensure_progress_started(method: T) -> Callable:
    """
    If a method of :class:`FlowProgressBar`decorated with `ensure_started`
    and :meth:`start` had not been called yet, a :class:`FlowException` will be
    thrown.

    The docstring will also be amended to reflect that fact.

    :param method: The method of :class:`FlowProgressBar` in question.
    """

    @wraps(method)
    def _impl(obj: FlowProgressBar, *method_args, **method_kwargs):
        if not obj.started:
            raise FlowException(
                f"Attempted to call method '{method}' before initializing progress bar"
            )
        return method(obj, *method_args, **method_kwargs)

    if method.__doc__ is None:
        method.__doc__ = ""

    method.__doc__ = (
        "This method may not be called before the progress bar is started.\n"
        + method.__doc__
    )

    return _impl


class _StepActivityColumn(ProgressColumn):
    """
    Renders a step row's most recent log line.

    The text is read here, during Rich's refresh, rather than pushed by
    whoever produced the line. That is what keeps the bar's cost proportional
    to the refresh rate instead of to how much output a tool produces.
    """

    def __init__(self, live: LiveLog) -> None:
        super().__init__()
        self._live = live

    def render(self, task: Task) -> Text:
        display = self._live.get(str(task.description))
        if display is None or not display.last_line:
            return Text("")
        return Text(display.last_line, style="dim", no_wrap=True, overflow="ellipsis")


class FlowProgressBar(object):
    """
    A wrapper for a flow's progress bar, rendered using Rich at the bottom of
    interactive terminals.
    """

    def __init__(
        self,
        flow_name: str,
        starting_ordinal: int = 1,
        live: LiveLog | None = None,
        console: rich.console.Console | None = None,
    ) -> None:
        self.__flow_name: str = flow_name
        self.__stages_completed: int = 0
        self.__max_stage: int = 0
        self.__task_id: TaskID = TaskID(-1)
        self.__ordinal: int = starting_ordinal
        self.__live = live if live is not None else default_live
        #: Row per in-flight step, keyed by step ID.
        self.step_row_ids: dict[str, TaskID] = {}
        self.__progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            _StepActivityColumn(self.__live),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console if console is not None else default_console,
            disable=not options.get_show_progress_bar(),
        )

    def start(self):
        """
        Starts rendering the progress bar.
        """
        self.__progress.start()
        self.__task_id = self.__progress.add_task(
            f"{self.__flow_name}",
        )
        # Rows follow the live-step registry, so they appear and disappear
        # without any flow having to announce its fan-out.
        self.__live.add_listener(self.sync_step_rows)

    def end(self):
        """
        Stops rendering the progress bar.
        """
        self.__live.remove_listener(self.sync_step_rows)
        for task_id in self.step_row_ids.values():
            self.__progress.remove_task(task_id)
        self.step_row_ids.clear()
        self.__progress.stop()
        self.__task_id = TaskID(-1)

    def refresh(self):
        """Forces a render. Rich otherwise refreshes on its own schedule."""
        self.__progress.refresh()

    def sync_step_rows(self):
        """
        Reconciles the rows against the steps currently running.

        Only membership is reconciled here. The text of a row is pulled by
        :class:`_StepActivityColumn` during Rich's own refresh, so a tool
        emitting a hundred thousand lines costs the bar nothing.
        """
        if self.__task_id == TaskID(-1):
            return
        current = {display.step_id for display in self.__live.snapshot()}
        for step_id in current - self.step_row_ids.keys():
            self.step_row_ids[step_id] = self.__progress.add_task(
                step_id,
                total=None,
            )
        for step_id in self.step_row_ids.keys() - current:
            self.__progress.remove_task(self.step_row_ids.pop(step_id))

    @property
    def started(self) -> bool:
        """
        :returns: If the progress bar has started or not
        """
        return self.__task_id != TaskID(-1)

    @ensure_progress_started
    def set_max_stage_count(self, count: int):
        """
        A helper function, used to set the total number of stages the progress
        bar is expected to keep tally of.

        :param count: The total number of stages.
        """
        self.__max_stage = count
        self.__progress.update(self.__task_id, total=count)

    @ensure_progress_started
    def start_stage(self, name: str):
        """
        Starts a new stage, updating the progress bar appropriately.

        :param name: The name of the stage.
        """
        self.__progress.update(
            self.__task_id,
            description=f"{self.__flow_name} - Stage {self.__stages_completed + 1} - {name}",
        )

    @ensure_progress_started
    def end_stage(self, *, increment_ordinal: bool = True):
        """
        Ends the current stage, updating the progress bar appropriately.

        :param increment_ordinal: Increment the step ordinal, which is used in the creation of step directories.

            You may want to set this to ``False`` if the stage is being skipped.

            Please note that step ordinal is not equal to stages- a skipped step
            increments the stage but not the step ordinal.
        """
        self.__stages_completed += 1
        if increment_ordinal:
            self.__ordinal += 1
        self.__progress.update(self.__task_id, completed=float(self.__stages_completed))

    @ensure_progress_started
    def get_ordinal_prefix(self) -> str:
        """
        :returns: A string with the current step ordinal, which can be
            used to create a step directory.
        """
        max_stage_digits = len(str(self.__max_stage))
        return f"{str(self.__ordinal).zfill(max_stage_digits)}-"


class Flow(ABC):
    """
    An abstract base class for a flow.

    Flows encapsulate a the running of multiple :class:`Step`\\s in any order.
    The sequence (or lack thereof) of running the steps is left to the Flow
    itself.

    The Flow ABC offers a number of convenience functions, including handling the
    progress bar at the bottom of the terminal, which shows what stage the flow
    is currently in and the remaining stages.

    :param config: Either a resolved :class:`librelane.config.Config` object, or an
        input to :meth:`librelane.config.Config.load`.

    :param name: An optional string name for the Flow itself, and not a run of it.

        If not provided, there are two fallbacks:

        * The value of the ``name`` property (``NotImplemented`` by default)
        * The name of the concrete ``Flow`` class

    :param config_override_strings: See :meth:`librelane.config.Config.load`
    :param pdk: See :meth:`librelane.config.Config.load`
    :param pdk_root: See :meth:`librelane.config.Config.load`
    :param scl: See :meth:`librelane.config.Config.load`
    :param pad: See :meth:`librelane.config.Config.load`
    :param design_dir: See :meth:`librelane.config.Config.load`

    :cvar Steps:
        A list of :class:`Step` **types** used by the Flow (not Step objects.)

        Subclasses of :class:`Flow` are expected to override the default value
        as a class member- but subclasses may allow this value to be further
        overridden during construction (and only then.)

        :class:`Flow` subclasses without the ``Steps`` class property declared
        are considered abstract and cannot be initialized.

    :cvar config_vars:
        A list of **flow-specific** configuration variables. These configuration
        variables are used entirely within the logic of the flow itself and
        are not exposed to ``Step``\\(s).

    :ivar step_objects:
        A list of :class:`Step` **objects** from the last run of the flow,
        if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar run_dir:
        The directory of the last run of the flow, if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar toolbox:
        The :class:`Toolbox` of the last run of the flow, if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar config_resolved_path:
        The path to the serialization of the resolved configuration for the
        last run of the flow.

        If :meth:`start` is called again, the reference is destroyed.
    """

    class _StepIssueSink:
        """
        Collects warnings and errors for replay once the run is over.

        The terminal is a live view, so an issue early in a long run scrolls
        away. Each collected issue keeps a pointer into the step's own log --
        the durable record -- so it can be followed rather than grepped for.
        """

        @dataclass
        class Record:
            message: str
            level: str = "WARNING"
            step: str | None = None
            step_log: str | None = None
            repeats: int = 0
            similar: int = 0

            def locate(self) -> str:
                """
                :returns: A ``path:line`` pointer into the step log, or the bare
                    path when the message cannot be found in it.
                """
                if self.step_log is None:
                    return ""
                try:
                    lines = pathlib.Path(self.step_log).read_text().splitlines()
                except OSError:
                    return ""
                relative = os.path.relpath(self.step_log)
                for number, line in enumerate(lines, start=1):
                    if self.message.splitlines()[0] in line:
                        return f"{relative}:{number}"
                return relative

            def __str__(self) -> str:
                prefix = ""
                if self.step is not None:
                    prefix = f"[{self.step}] "
                postfix = ""
                if self.repeats + self.similar:
                    postfix = f" (and {self.repeats + self.similar} similar messages)"
                pointer = self.locate()
                if pointer:
                    postfix = f"{postfix} ▸ {pointer}"
                return f"{prefix}{self.message}{postfix}"

        def __init__(self) -> None:
            self.warnings: dict[str, Flow._StepIssueSink.Record] = {}
            self.errors: dict[str, Flow._StepIssueSink.Record] = {}

        def __call__(self, message) -> None:
            record = message.record
            extra = record["extra"]
            level = record["level"].name
            collected = self.errors if level in ("ERROR", "CRITICAL") else self.warnings
            text = str(record["message"])
            key = extra.get("key", text)
            if key in collected:
                existing = collected[key]
                if text == existing.message:
                    existing.repeats += 1
                else:
                    existing.similar += 1
            else:
                collected[key] = Flow._StepIssueSink.Record(
                    text,
                    level=level,
                    step=extra.get("step"),
                    step_log=extra.get("step_log"),
                )

    #: Retained under its former name for external callers.
    _StepWarningSink = _StepIssueSink

    name: str = NotImplemented
    Steps: list[type[Step]] = NotImplemented  # Override
    config_vars: list[Variable] = []

    class Config(BaseConfigModel):
        pass

    step_objects: list[Step] | None = None
    run_dir: pathlib.Path | None = None
    toolbox: Toolbox | None = None

    #: Content identity for files this run's steps depend on. Assigned by
    #: :meth:`start` and shared by every step, so a PDK view referenced by
    #: twenty steps is read once.
    fingerprinter: Fingerprinter | None = None

    config_resolved_path: pathlib.Path | None = None

    def __init_subclass__(cls):
        if "Config" in cls.__dict__ and "config_vars" not in cls.__dict__:
            cls.config_vars = model_to_variables(cls.Config)
        return super().__init_subclass__()

    def __init__(
        self,
        config: AnyConfigs,
        *,
        name: str | None = None,
        pdk: str | None = None,
        pdk_root: str | None = None,
        scl: str | None = None,
        pad: str | None = None,
        design_dir: str | None = None,
        config_override_strings: Sequence[str] | None = None,
    ):
        if self.__class__.Steps == NotImplemented:
            raise NotImplementedError(
                f"Abstract flow {self.__class__.__qualname__} does not implement the .Steps property and cannot be initialized."
            )
        for step in self.Steps:
            step.assert_concrete("used in a Flow")

        self.name = (
            self.__class__.__name__ if self.name == NotImplemented else self.name
        )
        if name is not None:
            self.name = name

        self.Steps = self.Steps.copy()  # Break global reference

        if not isinstance(config, Config):
            config, design_dir = Config.load(
                config_in=config,
                flow_config_vars=self.get_all_config_variables(),
                config_override_strings=config_override_strings,
                pdk=pdk,
                pdk_root=pdk_root,
                scl=scl,
                pad=pad,
                design_dir=design_dir,
            )

        self.config: Config = config
        self.design_dir = pathlib.Path(self.config["DESIGN_DIR"])
        self.progress_bar = FlowProgressBar(self.name)

    @classmethod
    def get_help_md(Self, myst_anchors: bool = False) -> str:  # pragma: no cover
        """
        :returns: rendered Markdown help for this Flow
        """
        doc_string = ""
        if Self.__doc__:
            doc_string = textwrap.dedent(Self.__doc__)

        flow_anchor = f"(flow-{slugify(Self.__name__, lower=True)})="

        result = (
            textwrap.dedent(
                f"""\
                {flow_anchor * myst_anchors}
                ### {Self.__name__}

                ```{{eval-rst}}
                %s
                ```

                #### Using from the CLI

                ```sh
                librelane --flow {Self.__name__} [...]
                ```

                #### Importing

                ```python
                from librelane.flows import Flow

                {Self.__name__} = Flow.factory.get("{Self.__name__}")
                ```
                """
            )
            % doc_string
        )
        flow_config_vars = Self.config_vars

        if len(flow_config_vars):
            config_var_anchors = f"({slugify(Self.__name__, lower=True)}-config-vars)="
            result += textwrap.dedent(
                f"""
                {config_var_anchors * myst_anchors}
                #### Flow-specific Configuration Variables
                """
            )
            result += Variable._render_table_md(
                flow_config_vars,
                myst_anchor_owner_id=Self.__name__ if myst_anchors else None,
            )
            result += "\n"

        if len(Self.Steps):
            result += "#### Included Steps\n"
            for step in Self.Steps:
                imp_id = step.get_implementation_id()
                if myst_anchors:
                    result += f"* [`{step.id}`](./step_config_vars.md#step-{slugify(imp_id, lower=True)})\n"
                else:
                    variant_str = ""
                    if imp_id != step.id:
                        variant_str = f" (implementation: `{imp_id}`)"
                    result += f"* `{step.id}`{variant_str}\n"

        return result

    @classmethod
    def display_help(Self):  # pragma: no cover
        """
        Displays Markdown help for a given flow.

        If in an IPython environment, it's rendered using ``IPython.display``.
        Otherwise, it's rendered using ``rich.markdown``.
        """
        try:
            get_ipython()  # type: ignore

            import IPython.display

            IPython.display.display(IPython.display.Markdown(Self.get_help_md()))
        except NameError:
            from rich.markdown import Markdown

            default_console.log(Markdown(Self.get_help_md()))

    def get_all_config_variables(self) -> list[Variable]:
        """
        :returns: All configuration variables for this Flow, including
            universal configuration variables, flow-specific configuration
            variables and step-specific configuration variables.
        """
        flow_variables_by_name: dict[str, tuple[Variable, str]] = {
            variable.name: (variable, "universal flow variables")
            for variable in universal_flow_config_variables
        }

        for variable in self.config_vars:
            if flow_variables_by_name.get(variable.name) is not None:
                existing_variable, source = flow_variables_by_name[variable.name]
                if variable != existing_variable:
                    raise FlowException(
                        f"Misconfigured flow: Unrelated variables in {source} and flow-specific variables share a name: {variable.name}"
                    )
            flow_variables_by_name[variable.name] = (
                variable,
                "flow-specific variables",
            )

        for step_cls in self.Steps:
            for variable in step_cls.config_vars:
                if flow_variables_by_name.get(variable.name) is not None:
                    existing_variable, existing_step = flow_variables_by_name[
                        variable.name
                    ]
                    if variable != existing_variable:
                        raise FlowException(
                            f"Misconfigured flow: Unrelated variables in {existing_step} and {step_cls.__name__} share a name: {variable.name}"
                        )
                flow_variables_by_name[variable.name] = (variable, step_cls.__name__)

        return [variable for variable, _ in flow_variables_by_name.values()]

    @final
    def start(
        self,
        with_initial_state: State | None = None,
        tag: str | None = None,
        last_run: bool = False,
        _force_run_dir: str | os.PathLike[str] | None = None,
        *,
        overwrite: bool = False,
        **kwargs,
    ) -> State:
        """
        The entry point for a flow.

        :param with_initial_state: An optional initial state object to use.
            If not provided, an empty state object is created.

            Resuming a run does not seed this. Each step resolves its own input
            from the step before it, and reuses its own previous result when
            that input and its configuration are unchanged.

        :param tag: A name for this invocation of the flow. If not provided,
            one based on a date string will be created.

            This tag is used to create the "run directory", which will be placed
            under the directory ``runs/`` in the design directory.
        :param last_run: Use the latest run (by modification time) as the tag.

            If no runs exist, a :class:`FlowException` will be raised.

            If ``last_run`` and ``tag`` are both set, a :class:`FlowException` will
            also be raised.
        :param overwrite: If true and a run with the desired tag was found, its
            contents are deleted and the flow starts clean. If false, the run is
            resumed: every step whose configuration and input are unchanged
            reuses its previous result.

        :returns: ``(success, state_list)``
        """

        if last_run and tag is not None:
            raise FlowException("tag and last_run cannot be used simultaneously.")

        tag = tag or datetime.datetime.now().astimezone().strftime(
            "RUN_%Y-%m-%d_%H-%M-%S"
        )
        if last_run:
            runs_dir = self.design_dir / "runs"
            runs = list(runs_dir.iterdir()) if runs_dir.is_dir() else []
            latest_run = max(
                runs,
                key=lambda run: run.stat().st_mtime,
                default=None,
            )

            if latest_run is not None:
                tag = latest_run.name
            else:
                raise FlowException("last_run used without any existing runs")

        # Stored until next start()
        self.run_dir = pathlib.Path(
            _force_run_dir or self.design_dir / "runs" / tag
        ).resolve()
        initial_state = with_initial_state or State()

        self.step_objects = []
        starting_ordinal = 1
        try:
            entries = [entry.name for entry in self.run_dir.iterdir()]
            if len(entries) == 0:
                raise FileNotFoundError(self.run_dir)  # Treat as non-existent directory
            elif overwrite:
                logger.log("VERBOSE", f"Removing '{self.run_dir}'…")
                shutil.rmtree(self.run_dir)
                raise FileNotFoundError(self.run_dir)  # Treat as non-existent directory

            logger.info(f"Using existing run at '{tag}' with the '{self.name}' flow.")

            # Extract maximum step ordinal + load finished steps
            entries_sorted = sorted(
                filter(
                    lambda x: "-" in x and x.split("-", maxsplit=1)[0].isdigit(),
                    entries,
                ),
                key=lambda x: int(x.split("-", maxsplit=1)[0]),
            )
            for entry in entries_sorted:
                try:
                    extracted_ordinal = int(entry.split("-", maxsplit=1)[0])
                except ValueError:
                    continue

                starting_ordinal = max(starting_ordinal, extracted_ordinal + 1)

        except NotADirectoryError:
            raise FlowException(
                f"Run directory for '{tag}' already exists as a file and not a directory."
            )
        except FileNotFoundError:
            logger.info(
                f"Starting a new run of the '{self.name}' flow with the tag '{tag}'."
            )
            self.run_dir.mkdir(parents=True, exist_ok=True)

        # Stored until next start()
        self.toolbox = Toolbox(os.fspath(self.run_dir / "tmp"))
        self.fingerprinter = Fingerprinter()

        issue_handler = Flow._StepIssueSink()
        try:
            with ExitStack() as sink_stack:
                sink_stack.enter_context(
                    additional_sink(issue_handler, level="WARNING")
                )
                for level in ["WARNING", "ERROR"]:
                    sink_stack.enter_context(
                        additional_sink(
                            self.run_dir / f"{level.lower()}.log",
                            mode="a+",
                            # Exactly one level, so error.log stays out of
                            # warning.log. Loguru's ``level`` is a minimum and
                            # its ``filter`` dict form keys on the module name,
                            # so neither expresses this.
                            filter=lambda record, level=level: (
                                record["level"].name == level
                            ),
                        )
                    )
                sink_stack.enter_context(
                    additional_sink(
                        self.run_dir / "flow.log",
                        mode="a+",
                        level="VERBOSE",
                    )
                )

                for diagnostic in self.config.diagnostics:
                    if diagnostic.severity.value == "error":
                        logger.error(diagnostic.message)
                    elif diagnostic.severity.value in ("warning", "deprecation"):
                        logger.warning(diagnostic.message)
                    else:
                        logger.info(diagnostic.message)

                self.config_resolved_path = self.run_dir / "resolved.json"
                self.config_resolved_path.write_text(self.config.dumps())

                self.progress_bar = FlowProgressBar(
                    self.name, starting_ordinal=starting_ordinal
                )
                self.progress_bar.start()
                try:
                    final_state, step_objects = self.run(
                        initial_state=initial_state,
                        initial_state_given=with_initial_state is not None,
                        starting_ordinal=starting_ordinal,
                        **kwargs,
                    )
                finally:
                    self.progress_bar.end()

                # Stored until next start()
                self.step_objects += step_objects

        finally:
            # Replayed after the run because the terminal is a live view: an
            # issue raised early in a long flow has long since scrolled away.
            if len(issue_handler.warnings):
                logger.warning("The following warnings were generated by the flow:")
                for record in issue_handler.warnings.values():
                    logger.warning(f"{record}")
            if len(issue_handler.errors):
                logger.error("The following errors were generated by the flow:")
                for record in issue_handler.errors.values():
                    logger.error(f"{record}")

        return final_state

    @protected
    @abstractmethod
    def run(
        self,
        initial_state: State,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        The core of the Flow. Subclasses of flow are expected to override this
        method.

        :param initial_state: An initial state object to use.
        :returns: A tuple of states and instantiated step objects for inspection.
        """
        pass

    @protected
    def dir_for_step(self, step: Step, position: int | None = None) -> pathlib.Path:
        """
        May only be called while :attr:`run_dir` is not None, i.e., the flow
        has started. Otherwise, a :class:`FlowException` is raised.

        :param step: The step to name a directory for.
        :param position: The step's index in :attr:`Steps`, if the flow has a
            fixed step list. Passing it makes the directory depend on the step's
            position rather than on how many earlier steps happened to run, which
            is what lets a resumed run find its own prior output.

            A flow that builds its steps in a data-dependent loop has no fixed
            position for a step, so it omits this and keeps the running counter.
        :returns: A directory within the run directory for a specific step.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to call dir_for_step on a flow that has not been started."
            )
        if position is None:
            prefix = self.progress_bar.get_ordinal_prefix()
        else:
            width = len(str(len(self.Steps)))
            prefix = f"{position + 1:0{width}d}-"
        return self.run_dir / f"{prefix}{slugify(step.id)}"

    @protected
    def start_step(
        self,
        step: Step,
        *args,
        **kwargs,
    ) -> State:
        """
        A helper function that handles passing parameters to :mod:`Step.start`.'

        It is essentially equivalent to:

        .. code-block:: python

            step.start(
                toolbox=self.toolbox,
                step_dir=self.dir_for_step(step),
            )


        See :meth:`Step.start` for more info.

        :param step: The step object to run
        :param args: Arguments to `step.start`
        :param kwargs: Keyword arguments to `step.start`
        """

        kwargs["toolbox"] = self.toolbox
        kwargs["step_dir"] = self.dir_for_step(step)

        return step.start(*args, **kwargs)

    @protected
    def start_step_async(
        self,
        step: Step,
        *args,
        **kwargs,
    ) -> Future[State]:
        """
        An asynchronous equivalent to :meth:`start_step`.

        :param step: The step object to run
        :param args: Arguments to `step.start`
        :param kwargs: Keyword arguments to `step.start`
        :returns: A ``Future`` encapsulating a State object, which can be used
            as an input to the next step (where the next step will wait for the
            ``Future`` to be realized before calling :meth:`Step.run`)
        """

        kwargs["toolbox"] = self.toolbox
        kwargs["step_dir"] = self.dir_for_step(step)

        return get_tpe().submit(step.start, *args, **kwargs)

    def _save_snapshot_ef(self, path: str | os.PathLike):
        if (
            self.step_objects is None
            or self.toolbox is None
            or self.config_resolved_path is None
        ):
            raise RuntimeError(
                "Flow was not run before attempting to save views in the Efabless format."
            )

        if len(self.step_objects) == 0:
            # No steps, no data
            return

        last_step = self.step_objects[-1]
        last_state = last_step.state_out

        if last_state is None:
            raise FlowException(
                f"Misconfigured flow: Step {last_step.id} was appended to step objects without having been run first."
            )

        # 1. Copy Files
        last_state.validate()
        logger.info(
            f"Saving views in the Efabless/Caravel User Project format to '{os.path.abspath(path)}'…"
        )
        mkdirp(path)

        supported_formats = {
            DesignFormat.POWERED_NETLIST: (os.path.join("verilog", "gl"), "v"),
            DesignFormat.DEF: ("def", "def"),
            DesignFormat.LEF: ("lef", "lef"),
            DesignFormat.SPEF: (os.path.join("spef", "multicorner"), "spef"),
            DesignFormat.LIB: (os.path.join("lib", "multicorner"), "lib"),
            DesignFormat.GDS: ("gds", "gds"),
            DesignFormat.MAG: ("mag", "mag"),
        }

        def visitor(key, value, top_key, _, __):
            df = DesignFormat.factory.get(top_key)
            assert df is not None
            if df not in supported_formats:
                return

            subdirectory, extension = supported_formats[df]

            target_dir = os.path.join(path, subdirectory)
            if not isinstance(value, Path):
                if isinstance(value, dict):
                    assert self.toolbox is not None, (
                        "toolbox check was not executed properly"
                    )
                    default_corner_view = self.toolbox.filter_views(self.config, value)
                    default_corner_target_dir = os.path.dirname(target_dir)
                    mkdirp(default_corner_target_dir)
                    if len(default_corner_view) == 1:
                        target_basename = f"{self.config['DESIGN_NAME']}.{extension}"
                        target_path = os.path.join(
                            default_corner_target_dir, target_basename
                        )
                        shutil.copyfile(
                            default_corner_view[0], target_path, follow_symlinks=True
                        )
                    else:
                        for file in default_corner_view:
                            shutil.copyfile(file, target_dir, follow_symlinks=True)
                return

            target_basename = os.path.basename(str(value))
            target_basename = target_basename[: -len(df.extension)] + extension
            target_path = os.path.join(target_dir, target_basename)
            mkdirp(target_dir)
            shutil.copyfile(value, target_path, follow_symlinks=True)

        last_state._walk(last_state.to_raw_dict(metrics=False), path, visit=visitor)

        # 2. Copy Logs, Reports, & Signoff Information
        def copy_dir_contents(from_dir, to_dir, filter="*"):
            for file in os.listdir(from_dir):
                file_path = os.path.join(from_dir, file)
                if os.path.isdir(file_path):
                    continue
                if fnmatch.fnmatch(file, filter):
                    shutil.copyfile(
                        file_path, os.path.join(to_dir, file), follow_symlinks=True
                    )

        def find_one(pattern):
            result = glob.glob(pattern)
            if len(result) == 0:
                return None
            return result[0]

        signoff_dir = os.path.join(path, "signoff", self.config["DESIGN_NAME"])
        openlane_signoff_dir = os.path.join(signoff_dir, "openlane-signoff")
        mkdirp(openlane_signoff_dir)

        ## resolved.json
        shutil.copyfile(
            self.config_resolved_path,
            os.path.join(openlane_signoff_dir, "resolved.json"),
            follow_symlinks=True,
        )

        ## metrics
        with open(os.path.join(signoff_dir, "metrics.csv"), "w", encoding="utf8") as f:
            last_state.metrics_to_csv(f)

        ## flow logs
        mkdirp(openlane_signoff_dir)
        copy_dir_contents(self.run_dir, openlane_signoff_dir, "*.log")

        ### step-specific signoff logs and reports
        for step in self.step_objects:
            reports_dir = os.path.join(step.step_dir, "reports")
            step_imp_id = step.get_implementation_id()
            if step_imp_id == "Magic.DRC":
                if drc_rpt := find_one(os.path.join(reports_dir, "*.rpt")):
                    shutil.copyfile(
                        drc_rpt, os.path.join(openlane_signoff_dir, "drc.rpt")
                    )
                if drc_xml := find_one(os.path.join(reports_dir, "*.xml")):
                    # Despite the name, this is the Magic DRC report simply
                    # converted into a KLayout-compatible format. Confusing!
                    drc_xml_out = os.path.join(openlane_signoff_dir, "drc.klayout.xml")
                    with (
                        open(drc_xml, encoding="utf8") as i,
                        open(drc_xml_out, "w", encoding="utf8") as o,
                    ):
                        o.write(
                            "<!-- Despite the name, this is the Magic DRC report in KLayout format. -->\n"
                        )
                        shutil.copyfileobj(i, o)
            if step_imp_id == "Netgen.LVS":
                if lvs_rpt := find_one(os.path.join(reports_dir, "*.rpt")):
                    shutil.copyfile(
                        lvs_rpt, os.path.join(openlane_signoff_dir, "lvs.rpt")
                    )
            if step_imp_id.endswith("DRC") or step_imp_id.endswith("LVS"):
                copy_dir_contents(step.step_dir, openlane_signoff_dir, "*.log")
            if step_imp_id.endswith("CheckAntennas"):
                if os.path.exists(reports_dir):
                    copy_dir_contents(
                        reports_dir, openlane_signoff_dir, "antenna_summary.rpt"
                    )
            if step_imp_id.endswith("STAPostPNR"):
                timing_report_folder = os.path.join(
                    openlane_signoff_dir, "timing-reports"
                )
                mkdirp(timing_report_folder)
                copy_dir_contents(step.step_dir, timing_report_folder, "*summary.rpt")
                for dir in os.listdir(step.step_dir):
                    dir_path = os.path.join(step.step_dir, dir)
                    if not os.path.isdir(dir_path):
                        continue
                    target = os.path.join(timing_report_folder, dir)
                    mkdirp(target)
                    copy_dir_contents(dir_path, target, "*.rpt")

        # 3. SDF
        #   (This one, as with many things in the Efabless format, is special)
        if sdf := last_state[DesignFormat.SDF]:
            assert isinstance(sdf, dict), "SDF is not a dictionary"
            for corner, view in sdf.items():
                assert isinstance(view, Path), "SDF state out returned multiple paths"
                target_dir = os.path.join(signoff_dir, "sdf", corner)
                mkdirp(target_dir)
                shutil.copyfile(
                    view, os.path.join(target_dir, f"{self.config['DESIGN_NAME']}.sdf")
                )

    class FlowFactory(object):
        """
        A factory singleton for Flows, allowing Flow types to be registered and then
        retrieved by name.

        See
        `Factory (object-oriented programming) on Wikipedia <https://en.wikipedia.org/wiki/Factory_(object-oriented_programming)>`_
        for a primer.
        """

        __registry: ClassVar[dict[str, type[Flow]]] = {}

        @classmethod
        def register(
            Self, registered_name: str | None = None
        ) -> Callable[[type[Flow]], type[Flow]]:
            """
            A decorator that adds a flow type to the registry.

            :param registered_name: An optional registered name for the flow.

                If not specified, the flow will be referred to by its Python
                class name.
            """

            def decorator(cls: type[Flow]) -> type[Flow]:
                name = cls.__name__
                if registered_name is not None:
                    name = registered_name
                Self.__registry[name] = cls
                return cls

            return decorator

        @classmethod
        def get(Self, name: str) -> type[Flow] | None:
            """
            Retrieves a Flow type from the registry using a lookup string.

            :param name: The registered name of the Flow. Case-sensitive.
            """
            return Self.__registry.get(name)

        @classmethod
        def list(Self) -> builtins.list[str]:
            """
            :returns: A list of strings representing all registered flows.
            """
            return list(Self.__registry.keys())

    factory = FlowFactory
