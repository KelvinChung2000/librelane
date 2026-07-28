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
import json
import time
import psutil
import subprocess
import pathlib
from signal import Signals
from decimal import Decimal
from inspect import isabstract
from abc import abstractmethod, ABC
from concurrent.futures import Future
from typing import (
    Any,
    ClassVar,
    TYPE_CHECKING,
    TypeVar,
    cast,
)
from collections.abc import Callable, Sequence


from ...config import (
    BaseConfigModel,
    Config as ConfigMap,
    Variable,
    model_to_variables,
    variables_to_model,
)
from ...config.flow import OptionConfig, PadConfig, PdkConfig, SclConfig
from ...state import DesignFormat, State, InvalidState, StateElement
from ...common import (
    GenericImmutableDict,
    GenericDictEncoder,
    Toolbox,
    slugify,
    final,
    protected,
    format_elapsed_time,
)
from ...logging import step_context
from ...__version__ import __version__

from .exceptions import StepError, StepException, StepNotFound, StepSignalled
from .factory import StepFactory
from .output_processor import DefaultOutputProcessor, OutputProcessor
from .reporting import ReportingMixin
from .subprocess_exec import SubprocessMixin

VT = TypeVar("VT")


REPORT_START_LOCUS = "%OL_CREATE_REPORT"
REPORT_END_LOCUS = "%OL_END_REPORT"
METRIC_LOCUS = "%OL_METRIC"

GlobalToolbox = Toolbox(os.fspath(pathlib.Path.cwd() / "librelane_run" / "tmp"))
ViewsUpdate = dict[DesignFormat, StateElement]
MetricsUpdate = dict[str, Any]


class Step(ReportingMixin, SubprocessMixin, ABC):
    """
    An abstract base class for Step objects.

    Steps encapsulate a subroutine that acts upon certain classes of formats
    in an input state and returns a new output state with updated design format
    paths and/or metrics.

    Warning: The initializer for Step is not thread-safe. Please use it on the main
    thread and then, if you're using a Flow object, use ``start_step_async``, or
    if you're not, you may use ``start`` in another thread. That part's fine.

    :param config: A configuration object.

        If running in interactive mode, you can set this to ``None``, but it is
        otherwise required.

    :param state_in: The state object this step will use as an input.

        The state may also be a ``Future[State]``, in which case,
        the ``start()`` call will block until that Future is realized.
        This allows you to chain a number of asynchronous steps.

        See https://en.wikipedia.org/wiki/Futures_and_promises for a primer.

        If running in interactive mode, you can set this to ``None``, where it
        will use the last generated state, but it is otherwise required.

    :param step_dir: A "scratch directory" for the step. Required.

        You may omit this argument as ``None`` if "flow" is specified.

    :param id: A string ID for the Step. The convention is f"{a}.{b}", where the
        first is common between all Steps using the same tools.

        The ID should be in ``UpperCamelCase``.

        While this is technically a class variable, instances allowed to change it
        per-instance to disambiguate when the same step is used multiple times
        in a flow.

        :class:`Step` subclasses without the ``id`` class property declared
        are considered abstract and cannot be initialized or used in a :class:`Flow`.

    :param name: A short name for the Step, used in progress bars and
        the like.

        While this is technically an instance variable, it is expected for every
        subclass to override this variable and instances are only to change it
        to disambiguate when the same step is used multiple times in a flow.

    :param long_name: A longer descriptive for the Step, used to delimit
        logs.

        While this is technically an instance variable, it is expected for every
        subclass to override this variable and instances are only to change it
        to disambiguate when the same step is used multiple times in a flow.

    :param flow: Deprecated: the parent flow. Ignored if passed.

    :cvar inputs: A list of :class:`librelane.state.DesignFormat` objects that
        are required for this step. These will be validated by the :meth:`start`
        method.

        :class:`Step` subclasses without the ``inputs`` class property declared
        are considered abstract and cannot be initialized or used in a :class:`Flow`.

    :cvar outputs: A list of :class:`librelane.state.DesignFormat` objects that
        may be emitted by this step. A step is not allowed to modify design
        formats not declared in ``outputs``.

        :class:`Step` subclasses without the ``outputs`` class property declared
        are considered abstract and cannot be initialized or used in a :class:`Flow`.

    :cvar config_vars: A list of configuration :class:`librelane.config.Variable` objects
        to be used to alter the behavior of this Step.

    :cvar output_processors: A default set of
        :class:`librelane.steps.OutputProcessor` classes for use with
        :meth:`run_subprocess`.

    :ivar state_out:
        The last output state from running this step object, if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar start_time:
        The last starting time from running this step object, if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar end_time:
        The last ending time from running this step object, if it exists.

        If :meth:`start` is called again, the reference is destroyed.

    :ivar config_path:
        Path to the last step-specific `config.json` generated while running
        this step object, if it exists.

        If :meth:`start` is called again, the path will be replaced.

    :ivar toolbox:
        The last :class:`Toolbox` used while running this step object, if it
        exists.

        If :meth:`start` is called again, the reference is destroyed.
    """

    # Class Variables
    id: str = NotImplemented
    inputs: ClassVar[list[DesignFormat]] = NotImplemented
    outputs: ClassVar[list[DesignFormat]] = NotImplemented
    output_processors: ClassVar[list[type[OutputProcessor]]] = [DefaultOutputProcessor]
    config_vars: ClassVar[list[Variable]] = []

    if TYPE_CHECKING:
        # Every step is also handed the flow's common variables, which reach
        # the model as extras rather than declared fields. Spelling them out
        # for the type checker keeps `self.config.DESIGN_NAME` and friends
        # checked, without freezing the variable list a flow may substitute.
        class Config(PdkConfig, SclConfig, OptionConfig, PadConfig):
            pass

    else:

        class Config(BaseConfigModel):
            pass

    _config_model_cache: ClassVar[
        "tuple[tuple[tuple[str, Any, Any], ...], type[Step.Config]] | None"
    ] = None

    # Instance Variables
    name: str
    long_name: str
    state_in: Future[State]
    config: Config

    ## Stateful
    toolbox: Toolbox = GlobalToolbox
    state_out: State | None = None
    start_time: float | None = None
    end_time: float | None = None
    step_dir: pathlib.Path
    config_path: pathlib.Path | None = None

    # These are mutable class variables. However, they will only be used
    # when steps are run outside of a Flow, pretty much.
    counter: ClassVar[int] = 1
    # End Mutable Global Variables

    def __init__(
        self,
        config: ConfigMap | BaseConfigModel | None = None,
        state_in: State | None | Future[State] = None,
        *,
        id: str | None = None,
        name: str | None = None,
        long_name: str | None = None,
        flow: Any | None = None,
        _config_quiet: bool = False,
        _no_revalidate_conf: bool = False,
        _no_filter_conf: bool = False,
        **kwargs,
    ):
        self.__class__.assert_concrete()

        if flow is not None:
            logger.bind(step=self.id).warning(
                f"Passing 'flow' to a Step class's initializer is deprecated. Please update the flow '{type(flow).__name__}'."
            )

        if id is not None:
            self.id = id

        if config is None:
            if current_interactive := ConfigMap.current_interactive:
                config = current_interactive
            else:
                raise TypeError("Missing required argument 'config'")
        elif isinstance(config, BaseConfigModel):
            config = ConfigMap(
                config.to_raw_dict(),
                meta=config.meta,
                diagnostics=config.diagnostics,
            )

        if state_in is None:
            if ConfigMap.current_interactive is not None:
                raise TypeError(
                    "Using an implicit input state in interactive mode is no longer supported- pass the last state in as follows: `state_in=last_step.state_out`"
                )
            else:
                raise TypeError("Missing required argument 'state_in'")

        if name is not None:
            self.name = name
        elif not hasattr(self, "name"):
            self.name = self.__class__.__name__

        if long_name is not None:
            self.long_name = long_name
        elif not hasattr(self, "long_name"):
            self.long_name = self.name

        if _no_filter_conf and _no_revalidate_conf:
            raise ValueError(
                "Cannot pass both _no_filter_conf and _no_revalidate_conf as True"
            )

        if _no_revalidate_conf:
            filtered_config = config.copy_filtered(
                self.get_all_config_variables(),
                include_flow_variables=False,  # get_all_config_variables() gets them anyway
            )
        elif _no_filter_conf:
            filtered_config = config.copy()
        else:
            filtered_config = config.with_increment(
                self.get_all_config_variables(),
                kwargs,
                _config_quiet,
            )
        model_type = self._get_config_model()
        raw_filtered = filtered_config.to_raw_dict(include_meta=False)
        if _no_revalidate_conf:
            typed_config = model_type.model_construct(**raw_filtered)
        else:
            typed_config = model_type.model_validate(raw_filtered, strict=True)
        self.config = typed_config.attach_context(
            diagnostics=filtered_config.diagnostics,
            meta=filtered_config.meta,
        )

        state_in_future: Future[State] = Future()
        if isinstance(state_in, State):
            state_in_future.set_result(state_in)
        else:
            state_in_future = state_in
        self.state_in = state_in_future

    def __init_subclass__(cls):
        if "Config" in cls.__dict__ and "config_vars" not in cls.__dict__:
            cls.config_vars = model_to_variables(cls.Config)
        cls._config_model_cache = None
        if hasattr(cls, "flow_control_variable"):
            logger.warning(
                f"Step '{cls.__name__}' uses deprecated property 'flow_control_variable'. Flow control should now be done using the Flow class's 'gating_config_vars' property."
            )
        if cls.id != NotImplemented:
            if f".{cls.__name__}" not in cls.id:
                logger.debug(f"Step '{cls.__name__}' has a non-matching ID: '{cls.id}'")

    @classmethod
    def install_config_model(Self, model: type[BaseConfigModel]) -> None:
        """
        Replaces this step's nested ``Config`` with a generated model.

        Composite and checker steps derive their variables from other steps or
        from class attributes, so their model has no written-out class for a
        type checker to see. Installing it dynamically keeps ``Config`` usable
        as a base class everywhere else.

        :param model: The generated model, which must derive from the
            ``Config`` of the step being specialized.
        """
        setattr(Self, "Config", model)

    @classmethod
    def _get_config_model(Self) -> "type[Step.Config]":
        if "Config" in Self.__dict__ or "config_vars" not in Self.__dict__:
            return Self.Config
        fingerprint = tuple(
            (variable.name, variable.type, variable.default)
            for variable in Self.get_all_config_variables()
        )
        cached = Self._config_model_cache
        if cached is None or cached[0] != fingerprint:
            model = cast(
                "type[Step.Config]",
                variables_to_model(
                    f"{Self.__name__}Config",
                    Self.get_all_config_variables(),
                    base=Step.Config,
                ),
            )
            Self._config_model_cache = (fingerprint, model)
            return model
        return cached[1]

    @classmethod
    def get_implementation_id(Self) -> str:
        if hasattr(Self, "_implementation_id"):
            return getattr(Self, "_implementation_id")
        return Self.id

    @classmethod
    def assert_concrete(Self, action: str = "initialized"):
        """
        Checks if the Step class in question is concrete, with abstract methods
        AND ``NotImplemented`` classes implemented and declared respectively.

        Should be called before any ``Step`` subclass is used.

        If the class is not concrete, a ``NotImplementedError`` is raised.

        :param action: The action to be attempted, to be included in the
            ``NotImplementedError`` message.
        """
        if isabstract(Self):
            raise NotImplementedError(
                f"Abstract step {Self.__qualname__} has one or more methods not implemented ({' '.join(Self.__abstractmethods__)}) and cannot be {action}"
            )

        for attr in ["id", "inputs", "outputs"]:
            if not hasattr(Self, attr) or getattr(Self, attr) == NotImplemented:
                raise NotImplementedError(
                    f"Abstract step {Self.__qualname__} does not implement the .{attr} property and cannot be {action}"
                )

    @classmethod
    def _load_config_from_file(
        Self, config_path: str | os.PathLike, pdk_root: str = "."
    ) -> ConfigMap:
        config, _ = ConfigMap.load(
            config_in=json.loads(open(config_path).read(), parse_float=Decimal),
            flow_config_vars=Self.get_all_config_variables(),
            design_dir=".",
            pdk_root=pdk_root,
            _load_pdk_configs=False,
        )
        return config

    @classmethod
    def load(
        Self,
        config: str | os.PathLike | ConfigMap,
        state_in: str | os.PathLike | State,
        pdk_root: str | None = None,
    ) -> Step:
        """
        Creates a step object, but instead of using a Flow or a global state,
        the config_path and input state are deserialized from JSON files.

        Useful for re-running steps that have already run.

        :param config:
            (Path to) a **Step-filtered** configuration

            The step will not tolerate variables unrelated to this specific step.
        :param state: (Path to) a valid input state
        :param pdk_root: The PDK root, which is needed for some utilities.

            If your utility doesn't require it, just keep the default value
            as-is.
        :returns: The created step object
        """
        if Self.id == NotImplemented:  # If abstract
            id, Target = Step.factory.from_step_config(config)
            if id is None:
                raise StepNotFound(
                    "Attempted to initialize abstract Step, and no step ID was found in the configuration."
                )
            if Target is None:
                raise StepNotFound(
                    "Attempted to initialize abstract Step, and Step designated in configuration file not found.",
                    id=id,
                )
            return Target.load(config, state_in, pdk_root)

        pdk_root = pdk_root or "."
        if not isinstance(config, ConfigMap):
            config = Self._load_config_from_file(config, pdk_root)
        if not isinstance(state_in, State):
            state_in = State.loads(pathlib.Path(state_in).read_text())
        return Self(
            config=config,
            state_in=state_in,
            _no_revalidate_conf=True,
        )

    @classmethod
    def load_finished(
        Self,
        step_dir: str | os.PathLike[str],
        pdk_root: str | None = None,
        search_steps: list[type[Step]] | None = None,
    ) -> "Step":
        step_path = pathlib.Path(step_dir)
        config_path = step_path / "config.json"
        state_in_path = step_path / "state_in.json"
        state_out_path = step_path / "state_out.json"
        for file in config_path, state_in_path, state_out_path:
            if not file.is_file():
                raise FileNotFoundError(file)

        try:
            step_object = Self.load(config_path, state_in_path, pdk_root)
        except StepNotFound as e:
            if e.id is not None:
                search_steps = search_steps or []
                Matched: type[Step] | None = None
                for step in search_steps:
                    if step.get_implementation_id() == e.id:
                        Matched = step
                        break
                if Matched is None:
                    raise e from None
                step_object = Matched.load(config_path, state_in_path, pdk_root)
            else:
                raise e from None
        step_object.step_dir = step_path
        step_object.state_out = State.loads(state_out_path.read_text())
        return step_object

    @classmethod
    def get_all_config_variables(Self) -> list[Variable]:
        # Resolve this through the public package at call time. Besides keeping
        # the historical module-level API intact, this lets callers patch the
        # variable list on ``librelane.steps.step`` as they could before this
        # module became a package.
        from . import universal_flow_config_variables

        variables_by_name: dict[str, Variable] = {
            variable.name: variable for variable in universal_flow_config_variables
        }
        for variable in Self.config_vars:
            if existing_variable := variables_by_name.get(variable.name):
                if variable != existing_variable:
                    raise StepException(
                        f"Misconstructed step: Unrelated variable exists with the same name as one in the common Flow variables: {variable.name}"
                    )
            else:
                variables_by_name[variable.name] = variable

        return list(variables_by_name.values())

    @final
    def start(
        self,
        toolbox: Toolbox | None = None,
        step_dir: str | os.PathLike[str] | None = None,
        _no_rule: bool = False,
        **kwargs,
    ) -> State:
        """
        Begins execution on a step.

        This method is final and should not be subclassed.

        :param toolbox: The flow's :class:`Toolbox` object, required.

            If running in interactive mode, you may omit this argument as ``None``\\,
            where a global toolbox will be used instead.

            If running inside a flow, you may also omit this argument as ``None``\\,
            where the flow's toolbox will used to be instead.

        :param \\*\\*kwargs: Passed on to subprocess execution: useful if you want to
            redirect stdin, stdout, etc.

        :returns: An altered State object.
        """

        if step_dir is None:
            if ConfigMap.current_interactive is not None:
                self.step_dir = (
                    pathlib.Path.cwd()
                    / "librelane_run"
                    / f"{Step.counter}-{slugify(self.id)}"
                )
                Step.counter += 1
            else:
                raise TypeError("Missing required argument 'step_dir'")
        else:
            self.step_dir = pathlib.Path(step_dir)

        # Established before any work so that everything below -- including
        # subprocess output, which carries no binding of its own -- is
        # attributed to this step, and so the step's block header is emitted in
        # order with its output rather than printed around it.
        self.step_dir.mkdir(parents=True, exist_ok=True)
        with step_context(
            self.id,
            self.long_name,
            log_path=self.step_dir / "step.log",
        ):
            return self.__start(toolbox=toolbox, _no_rule=_no_rule, **kwargs)

    def __start(
        self,
        toolbox: Toolbox | None = None,
        _no_rule: bool = False,
        **kwargs,
    ) -> State:
        if toolbox is None:
            if ConfigMap.current_interactive is not None:
                pass
            else:
                self.toolbox = Toolbox(os.fspath(self.step_dir))
        else:
            self.toolbox = toolbox

        state_in_result = self.state_in.result()

        hyperlinks = (
            os.getenv(
                "_i_want_librelane_to_hyperlink_things_for_some_reason",
                None,
            )
            == "1"
        )
        link_start = ""
        link_end = ""
        if hyperlinks:
            link_start = f"[link=file://{self.step_dir.resolve()}]"
            link_end = "[/link]"

        logger.log(
            "VERBOSE",
            f"Running '{self.id}' at {link_start}'{os.path.relpath(self.step_dir)}'{link_end}…",
        )

        self.step_dir.mkdir(parents=True, exist_ok=True)
        (self.step_dir / "state_in.json").write_text(state_in_result.dumps())

        self.config_path = self.step_dir / "config.json"
        with self.config_path.open("w") as f:
            config_mut = self.config.to_raw_dict()
            config_mut["meta"] = {
                "librelane_version": __version__,
                "step": self.__class__.get_implementation_id(),
            }
            f.write(json.dumps(config_mut, cls=GenericDictEncoder, indent=4))

        logger.debug(f"Step directory ▶ '{self.step_dir}'")
        self.start_time = time.time()

        for input in self.inputs:
            value = state_in_result.get_by_df(input)
            if value is None and not input.optional:
                raise StepException(
                    f"{type(self).__name__}: missing required input '{input.id}'"
                ) from None

        try:
            views_updates, metrics_updates = self.run(state_in_result, **kwargs)
        except subprocess.CalledProcessError as e:
            if e.returncode is not None and e.returncode < 0:
                raise StepSignalled(
                    f"{self.name}: Interrupted ({Signals(-e.returncode).name})"
                ) from None
            else:
                raise StepError(
                    f"{self.name}: subprocess {e.args} failed", underlying_error=e
                ) from None

        metrics = GenericImmutableDict(
            state_in_result.metrics, overrides=metrics_updates
        )

        self.state_out = state_in_result.__class__(
            state_in_result, overrides=views_updates, metrics=metrics
        )

        try:
            self.state_out.validate()
        except InvalidState as e:
            raise StepException(
                f"Step {self.name} generated invalid state: {e}"
            ) from None

        (self.step_dir / "state_out.json").write_text(self.state_out.dumps())

        self.end_time = time.time()
        (self.step_dir / "runtime.txt").write_text(
            format_elapsed_time(self.end_time - self.start_time)
        )

        return self.state_out

    @protected
    @abstractmethod
    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        """
        The "core" of a step.

        This step is considered per-object private, i.e., if a Step's run is
        called anywhere outside of the same object's :meth:`start`\\, its behavior
        is undefined.

        :param state_in: The input state.

            Note that ``self.state_in`` is stored as a future and would need to be
            resolved before use first otherwise.

            For reference, ``start()`` is responsible for resolving it
            for ``.run()``\\.

        :param \\*\\*kwargs: Passed on to subprocess execution: useful if you want to
            redirect stdin, stdout, etc.
        """
        pass

    @protected
    def get_log_path(self) -> str:
        return super().get_log_path()

    @protected
    def run_subprocess(
        self,
        cmd: Sequence[str | os.PathLike],
        log_to: str | os.PathLike | None = None,
        silent: bool = False,
        report_dir: str | os.PathLike | None = None,
        env: dict[str, Any] | None = None,
        *,
        check: bool = True,
        output_processing: Sequence[type[OutputProcessor]] | None = None,
        _popen_callable: Callable[..., psutil.Popen] = psutil.Popen,
        **kwargs,
    ) -> dict[str, Any]:
        return super().run_subprocess(
            cmd,
            log_to,
            silent,
            report_dir,
            env,
            check=check,
            output_processing=output_processing,
            _popen_callable=_popen_callable,
            **kwargs,
        )

    @protected
    def extract_env(self, kwargs) -> tuple[dict, dict[str, str]]:
        return super().extract_env(kwargs)

    @classmethod
    def with_id(Self, id: str) -> type["Step"]:
        """
        Syntactic sugar for creating a subclass of a step with a different ID.

        Useful in flows, where you want different IDs for different instance of the
        same step.
        """
        return type(
            Self.__name__,
            (Self,),
            {"id": id, "_implementation_id": Self.get_implementation_id()},
        )

    StepFactory = StepFactory
    factory = StepFactory
