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
from loguru import logger
import os
import csv
import glob
import shutil
import fnmatch
import datetime
import pathlib
import threading
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from abc import abstractmethod, ABC
from concurrent.futures import Future
from functools import wraps
from typing import (
    Any,
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

from librelane.config import (
    AnyConfigs,
    BaseConfigModel,
    Config,
    Variable,
    model_to_variables,
    universal_flow_config_variables,
)
from librelane.state import State, DesignFormat
from librelane.steps import Step
from librelane.flows.spec import FlowSpec
from librelane.logging import (
    LiveLog,
    additional_sink,
    belongs_to_flow_run,
    console as default_console,
    flow_context,
    live as default_live,
    options,
)
from librelane.common import (
    format_elapsed_time,
    get_tpe,
    mkdirp,
    protected,
    final,
    slugify,
    Fingerprinter,
    Toolbox,
)
import builtins


# Defined in ``common.errors`` so that ``jobs`` can derive from them without
# importing the ``flows`` package, which depends on ``jobs``. Re-exported here
# because this is their documented import site.
from librelane.common.errors import FlowError, FlowException  # noqa: E402, F401


T = TypeVar("T", bound=Callable)


def ensure_progress_started(method: T) -> Callable:
    """
    If a method of :class:`FlowProgressBar`decorated with `ensure_started`
    and :meth:`start` had not been called yet, a :class:`FlowException` will be
    thrown.

    The docstring will also be amended to reflect that fact.

    Parameters
    ----------
    method : T
        The method of :class:`FlowProgressBar` in question.
    """

    @wraps(method)
    # The annotation is quoted because this decorator is defined inside the
    # FlowProgressBar class body, where the name does not exist yet. Every
    # Python before 3.14 evaluates parameter annotations at definition time,
    # so an unquoted name makes 'import librelane' itself a NameError there
    # while passing on the 3.14 this repo develops against.
    def _impl(obj: "FlowProgressBar", *method_args, **method_kwargs):
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
        #: Guards :attr:`step_row_ids`.
        #:
        #: :meth:`sync_step_rows` is a :class:`LiveLog` listener, and
        #: ``LiveLog.drain`` calls its listeners outside its own lock.
        #: ``drain`` runs on the log pump *and* synchronously inside
        #: ``LiveLog.unregister``, which every step reaches through
        #: ``step_context``'s ``finally`` on whichever thread ran it. Two steps
        #: finishing at the same instant therefore run this reconciliation
        #: concurrently, and both compute the same set of departed ids: the
        #: loser's ``pop`` raised ``KeyError``, and ``keys() - current`` could
        #: raise ``RuntimeError`` if the other thread inserted mid-iteration.
        #: Neither is a ``FlowError``, so either would escape the engine's
        #: failure collection and abandon every job still running.
        self.__rows_lock = threading.Lock()
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
        with self.__rows_lock:
            for task_id in self.step_row_ids.values():
                self.__progress.remove_task(task_id)
            self.step_row_ids.clear()
            # Inside the lock, and before the Progress is stopped: clearing
            # the task id is what closes sync_step_rows' guard, so a listener
            # that had already passed it and was waiting on this lock would
            # otherwise go on to add rows to a bar that is being torn down.
            self.__task_id = TaskID(-1)
        self.__progress.stop()

    def refresh(self):
        """Forces a render. Rich otherwise refreshes on its own schedule."""
        self.__progress.refresh()

    def sync_step_rows(self):
        """
        Reconciles the rows against the steps currently running.

        Only membership is reconciled here. The text of a row is pulled by
        :class:`_StepActivityColumn` during Rich's own refresh, so a tool
        emitting a hundred thousand lines costs the bar nothing.

        Called concurrently by every thread that finishes a step, so the whole
        reconciliation is taken under :attr:`__rows_lock`. The snapshot is read
        before the lock: ``LiveLog.snapshot`` takes ``LiveLog``'s own lock, and
        taking the two in a fixed order here and nowhere else is what keeps
        that from being an ordering to reason about.
        """
        if self.__task_id == TaskID(-1):
            return
        current = {display.step_id for display in self.__live.snapshot()}
        with self.__rows_lock:
            # Asked again, because the check above is only a cheap early-out:
            # end() clears the task id under this lock, so a listener that
            # passed the guard and then waited here would otherwise add rows
            # to a bar that has been torn down. Under the lock the answer
            # cannot change while it is acted on.
            if self.__task_id == TaskID(-1):
                return
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
        Returns
        -------
        bool
            If the progress bar has started or not
        """
        return self.__task_id != TaskID(-1)

    @ensure_progress_started
    def set_max_stage_count(self, count: int):
        """
        A helper function, used to set the total number of stages the progress
        bar is expected to keep tally of.

        Parameters
        ----------
        count : int
            The total number of stages.
        """
        self.__max_stage = count
        self.__progress.update(self.__task_id, total=count)

    @ensure_progress_started
    def start_stage(self, name: str):
        """
        Starts a new stage, updating the progress bar appropriately.

        Parameters
        ----------
        name : str
            The name of the stage.
        """
        self.__progress.update(
            self.__task_id,
            description=f"{self.__flow_name} - Stage {self.__stages_completed + 1} - {name}",
        )

    @ensure_progress_started
    def end_stage(self, *, increment_ordinal: bool = True):
        """
        Ends the current stage, updating the progress bar appropriately.

        Parameters
        ----------
        increment_ordinal : bool
            Increment the step ordinal, which is used in the creation of step directories.

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
        Returns
        -------
        str
            A string with the current step ordinal, which can be
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

    Parameters
    ----------
    config : AnyConfigs
        Either a resolved :class:`librelane.config.Config` object, or an
        input to :meth:`librelane.config.Config.load`.
    name : str | None
        An optional string name for the Flow itself, and not a run of it.

        If not provided, there are two fallbacks:

        * The value of the ``name`` property (``NotImplemented`` by default)
        * The name of the concrete ``Flow`` class
    config_override_strings : Sequence[str] | None
        See :meth:`librelane.config.Config.load`
    pdk : str | None
        See :meth:`librelane.config.Config.load`
    pdk_root : str | None
        See :meth:`librelane.config.Config.load`
    scl : str | None
        See :meth:`librelane.config.Config.load`
    pad : str | None
        See :meth:`librelane.config.Config.load`
    design_dir : str | None
        See :meth:`librelane.config.Config.load`

    Attributes
    ----------
    Steps : list[type[Step]]
        A list of :class:`Step` **types** the flow will run (not Step objects.)

        Read by :meth:`get_all_config_variables`, which asks each type which
        configuration variables it declares.
        :class:`librelane.flows.engine.Workflow` assigns it from its resolved
        jobs before this class's initializer runs, so the empty default is only
        what a flow that never assigned one contributes.
    config_vars : list[Variable]
        A list of **flow-specific** configuration variables. These configuration
        variables are used entirely within the logic of the flow itself and
        are not exposed to ``Step``\\(s).
    step_objects : list[Step] | None
        A list of :class:`Step` **objects** from the last run of the flow,
        if it exists.

        If :meth:`start` is called again, the reference is destroyed.
    run_dir : pathlib.Path | None
        The directory of the last run of the flow, if it exists.

        If :meth:`start` is called again, the reference is destroyed.
    toolbox : Toolbox | None
        The :class:`Toolbox` of the last run of the flow, if it exists.

        If :meth:`start` is called again, the reference is destroyed.
    config_resolved_path : pathlib.Path | None
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
                Returns
                -------
                str
                    A ``path:line`` pointer into the step log, or the bare
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
            #: :meth:`__call__` is registered as a loguru *callable* sink,
            #: with no ``enqueue``, so loguru invokes it synchronously on
            #: whichever thread emitted the record. Under
            #: :class:`librelane.flows.engine.Workflow` several jobs run at
            #: once and every one of their steps emits into this one object,
            #: so the check-then-act below is a genuine race: two threads that
            #: both find the key absent both construct a ``Record`` and the
            #: second assignment discards the first, losing that message's
            #: ``repeats`` and ``similar`` counts from the end-of-run replay.
            #: ``FlowProgressBar.__rows_lock`` and
            #: ``Fingerprinter.__memo_lock`` guard the other two shared
            #: mutables on the same path.
            self.__lock = threading.Lock()

        def __call__(self, message) -> None:
            record = message.record
            extra = record["extra"]
            level = record["level"].name
            collected = self.errors if level in ("ERROR", "CRITICAL") else self.warnings
            text = str(record["message"])
            key = extra.get("key", text)
            with self.__lock:
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

    #: The step types this flow will run. Not a declaration a subclass is
    #: obliged to make -- :class:`librelane.flows.engine.Workflow` assigns it
    #: from its resolved jobs -- but the list :meth:`get_all_config_variables`
    #: collects configuration variables from, so it must exist by the time
    #: :meth:`__init__` runs.
    Steps: list[type[Step]] = []
    config_vars: list[Variable] = []

    #: Values this flow supplies for configuration variables, from the ``with``
    #: block of a workflow document. Layered under the design configuration and
    #: over the PDK, so a design always wins. A Python flow declares none.
    values: dict[str, Any] = {}

    class Config(BaseConfigModel):
        pass

    step_objects: list[Step] | None = None

    #: The state the last :meth:`start` returned. Assigned there rather than in
    #: a subclass's ``run`` so that every engine has it, and read by
    #: :meth:`_save_snapshot_ef`, which cannot ask the step list for it: on a
    #: graph the last step to finish is an arbitrary leaf, and the flow's final
    #: state is the join of all of them.
    final_state: State | None = None

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
        for step in self.Steps:
            step.assert_concrete("used in a Flow")

        self.name = (
            self.__class__.__name__ if self.name == NotImplemented else self.name
        )
        if name is not None:
            self.name = name

        self.Steps = self.Steps.copy()  # Break global reference
        self.values = dict(self.values)  # Same, for the class-level default

        if not isinstance(config, Config):
            config, design_dir = Config.load(
                config_in=config,
                flow_config_vars=self.get_all_config_variables(),
                flow_values=self.values,
                config_override_strings=config_override_strings,
                pdk=pdk,
                pdk_root=pdk_root,
                scl=scl,
                pad=pad,
                design_dir=design_dir,
            )
        elif self.values:
            # An already-resolved configuration has no sources left to layer
            # under, so the flow's own values could only be applied on top of
            # the design's -- the opposite of what they mean. Refused rather
            # than dropped, so that a document's 'with' block cannot be
            # accepted and then quietly ignored.
            raise FlowException(
                f"Flow '{self.name}' supplies values for "
                f"{sorted(self.values)}, but it was constructed from a "
                f"configuration that is already resolved, which those values "
                f"cannot be layered under. Pass the design's configuration "
                f"file or mapping instead."
            )

        self.config: Config = config
        self.design_dir = pathlib.Path(self.config["DESIGN_DIR"])
        self.progress_bar = FlowProgressBar(self.name)

    def get_all_config_variables(self) -> list[Variable]:
        """
        Returns
        -------
        list[Variable]
            All configuration variables for this Flow, including
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

        Parameters
        ----------
        with_initial_state : State | None
            An optional initial state object to use.
            If not provided, an empty state object is created.

            Resuming a run does not seed this. Each step resolves its own input
            from the step before it, and reuses its own previous result when
            that input and its configuration are unchanged.
        tag : str | None
            A name for this invocation of the flow. If not provided,
            one based on a date string will be created.

            This tag is used to create the "run directory", which will be placed
            under the directory ``runs/`` in the design directory.
        last_run : bool
            Use the latest run (by modification time) as the tag.

            If no runs exist, a :class:`FlowException` will be raised.

            If ``last_run`` and ``tag`` are both set, a :class:`FlowException` will
            also be raised.
        overwrite : bool
            If true and a run with the desired tag was found, its
            contents are deleted and the flow starts clean. If false, the run is
            resumed: every step whose configuration and input are unchanged
            reuses its previous result.

        Returns
        -------
        State
            ``(success, state_list)``
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
            # Loguru sinks are process-wide, so the logs below would otherwise
            # also collect the records of any other flow running at the same
            # time in this process. Every sink this flow registers is scoped to
            # this token, which the steps inherit through the context.
            flow_run = uuid.uuid4().hex
            with ExitStack() as sink_stack:
                sink_stack.enter_context(flow_context(flow_run))
                sink_stack.enter_context(
                    additional_sink(
                        issue_handler,
                        level="WARNING",
                        filter=belongs_to_flow_run(flow_run),
                    )
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
                            filter=belongs_to_flow_run(flow_run, level),
                        )
                    )
                sink_stack.enter_context(
                    additional_sink(
                        self.run_dir / "flow.log",
                        mode="a+",
                        level="VERBOSE",
                        filter=belongs_to_flow_run(flow_run),
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
                self.final_state = final_state
                self._write_runtimes_csv()

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
    def _write_runtimes_csv(self) -> None:
        """
        Writes ``runtimes.csv`` over the run's steps.

        Each step already drops a ``runtime.txt`` in its own directory, so
        answering "what was slow?" meant walking every step directory and
        collating by hand. This is the same numbers in one file.

        A step that was reused from an earlier run rather than executed never
        gets a start time, and is written with empty runtime columns rather
        than omitted: that it was skipped is itself part of the answer.
        """
        if self.run_dir is None or self.step_objects is None:
            raise FlowException(
                "_write_runtimes_csv called outside of a run: "
                "run_dir and step_objects are only set by start()"
            )

        with open(self.run_dir / "runtimes.csv", "w", encoding="utf8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["step_dir", "step_id", "step_name", "elapsed_seconds", "elapsed"]
            )
            for step_object in self.step_objects:
                elapsed_seconds: float | None = None
                if (
                    step_object.start_time is not None
                    and step_object.end_time is not None
                ):
                    elapsed_seconds = step_object.end_time - step_object.start_time
                writer.writerow(
                    [
                        os.path.basename(os.fspath(step_object.step_dir)),
                        step_object.id,
                        step_object.name,
                        "" if elapsed_seconds is None else f"{elapsed_seconds:.3f}",
                        ""
                        if elapsed_seconds is None
                        else format_elapsed_time(elapsed_seconds),
                    ]
                )

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

        Parameters
        ----------
        initial_state : State
            An initial state object to use.

        Returns
        -------
        tuple[State, list[Step]]
            A tuple of states and instantiated step objects for inspection.
        """
        pass

    @protected
    def dir_for_step(self, step: Step) -> pathlib.Path:
        """
        May only be called while :attr:`run_dir` is not None, i.e., the flow
        has started. Otherwise, a :class:`FlowException` is raised.

        The directory is prefixed with the progress bar's current ordinal, so
        it records how many stages had been entered when the step ran.
        :class:`librelane.flows.engine.Workflow` does not use this: a run
        directory keyed on a running counter cannot be resumed once steps run
        concurrently, so it names its own with
        :meth:`librelane.flows.engine.Workflow.dir_for_job_step`.

        Parameters
        ----------
        step : Step
            The step to name a directory for.

        Returns
        -------
        pathlib.Path
            A directory within the run directory for a specific step.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to call dir_for_step on a flow that has not been started."
            )
        prefix = self.progress_bar.get_ordinal_prefix()
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

        Parameters
        ----------
        step : Step
            The step object to run
        args
            Arguments to `step.start`
        kwargs
            Keyword arguments to `step.start`
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

        Warning
        -------
        Submits to the process-wide pool
        :func:`librelane.common.get_tpe` returns, which
        :class:`librelane.flows.engine.Workflow` fills with whole jobs. Call it
        from a flow's own thread, never from inside a job: a worker that
        submits here and waits is waiting for a worker to free up, and the one
        that would is itself.

        Parameters
        ----------
        step : Step
            The step object to run
        args
            Arguments to `step.start`
        kwargs
            Keyword arguments to `step.start`

        Returns
        -------
        Future[State]
            A ``Future`` encapsulating a State object, which can be used
            as an input to the next step (where the next step will wait for the
            ``Future`` to be realized before calling :meth:`Step.run`)
        """

        kwargs["toolbox"] = self.toolbox
        kwargs["step_dir"] = self.dir_for_step(step)

        return get_tpe().submit(step.start, *args, **kwargs)

    def _save_snapshot_ef(self, path: str | os.PathLike):
        if (
            self.final_state is None
            or self.step_objects is None
            or self.toolbox is None
            or self.config_resolved_path is None
        ):
            raise RuntimeError(
                "Flow was not run before attempting to save views in the Efabless format."
            )

        if len(self.step_objects) == 0:
            # No steps, no data
            return

        final_state = self.final_state

        # 1. Copy Files
        final_state.validate()
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
            if not isinstance(value, pathlib.Path):
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

        final_state._walk(final_state.to_raw_dict(metrics=False), path, visit=visitor)

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
            final_state.metrics_to_csv(f)

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
        #
        # get_by_df rather than subscripting: a state that never carried an SDF
        # has no such key, and subscripting raises KeyError instead of yielding
        # the None this 'if' is written to test. A full run always produces one,
        # which is why it went unnoticed -- but --target can now stop the flow
        # before STA, and asking for an Efabless snapshot of that run should
        # write what exists rather than crash.
        if sdf := final_state.get_by_df(DesignFormat.SDF):
            assert isinstance(sdf, dict), "SDF is not a dictionary"
            for corner, view in sdf.items():
                assert isinstance(view, pathlib.Path), (
                    "SDF state out returned multiple paths"
                )
                target_dir = os.path.join(signoff_dir, "sdf", corner)
                mkdirp(target_dir)
                shutil.copyfile(
                    view, os.path.join(target_dir, f"{self.config['DESIGN_NAME']}.sdf")
                )

    class FlowFactory(object):
        """
        A factory singleton for workflow documents, allowing them to be
        registered and then retrieved by name.

        See
        `Factory (object-oriented programming) on Wikipedia <https://en.wikipedia.org/wiki/Factory_(object-oriented_programming)>`_
        for a primer.
        """

        _documents: ClassVar[dict[str, FlowSpec]] = {}

        @classmethod
        def register(Self, spec: FlowSpec) -> FlowSpec:
            """
            Registers a workflow document under its own ``name``.

            Parameters
            ----------
            spec : FlowSpec
                The loaded document.

            Returns
            -------
            FlowSpec
                The same document, so this reads as a pipeline step.

            Raises
            ------
            FlowException
                If a document with that name is already registered.
            """
            if spec.name in Self._documents:
                raise FlowException(
                    f"A flow document named '{spec.name}' is already registered."
                )
            Self._documents[spec.name] = spec
            return spec

        @classmethod
        def get(Self, name: str) -> FlowSpec | None:
            """
            Retrieves a workflow document from the registry using a lookup
            string.

            Parameters
            ----------
            name : str
                The document's ``name``. Case-sensitive.

            Returns
            -------
            FlowSpec | None
                The document registered under this name, or ``None``.
            """
            return Self._documents.get(name)

        @classmethod
        def list(Self) -> builtins.list[str]:
            """
            Returns
            -------
            builtins.list[str]
                Every registered document's name.

                Sorted, because this is what error messages offer the user and
                the import order documents happen to be registered in is not
                worth preserving.
            """
            return sorted(Self._documents)

    factory = FlowFactory
