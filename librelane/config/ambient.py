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
The configuration a run is currently reading.

A resolved configuration used to be handed down the call chain -- flow to job
to step -- so that every layer in between had to accept and forward a parameter
it did not itself read. This module holds it instead: :func:`current_config`
answers with it from anywhere, and nothing has to thread it.

It is stored in two tiers, because a run does not have exactly one
configuration:

* A **process-wide slot**, set by :func:`set_current_config`. This is the
  singleton, and it is what a REPL, a notebook or a bare ``Step`` sees. A flow
  publishes its resolved configuration here as soon as it has one.
* A **scoped override**, pushed by :func:`use_config`, held in a
  :class:`contextvars.ContextVar`. A job with a ``with`` block and each pass of
  a sweep resolve configurations of their own
  (:attr:`librelane.engine.engine.Workflow.job_configs` and
  :attr:`~librelane.engine.engine.Workflow.iteration_configs`), and those jobs
  run concurrently on :func:`librelane.common.get_tpe`. One slot would let two
  passes of a five-point sweep overwrite each other's configuration mid-run,
  and whichever wrote last would decide what both of them read. A context
  variable is per-execution, and
  :class:`librelane.common.tpe.ContextPropagatingThreadPoolExecutor` copies the
  submitting context into the worker, so a job's override reaches every step it
  runs and reaches nothing else.

The scoped tier wins where both are set. Neither is a place to *edit* a
configuration: what is stored is the same immutable
:class:`librelane.config.Config` the loader produced, and a scope replaces it
wholesale rather than mutating it.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from collections.abc import Iterator

if TYPE_CHECKING:
    from librelane.config.config import Config
    from librelane.config.model import BaseConfigModel


class NoCurrentConfig(RuntimeError):
    """
    Raised when :func:`current_config` is asked for a configuration and neither
    tier holds one: no flow has been constructed, no scope is open and
    :meth:`librelane.config.Config.interactive` has not been called.
    """

    def __init__(self) -> None:
        super().__init__(
            "No configuration is current. Construct a flow, open a scope with "
            "librelane.config.use_config(), or call Config.interactive() "
            "before asking for the current configuration."
        )


class ConfigScope:
    """
    A configuration and the typed model it is read through.

    Both halves are kept because they answer different questions and neither
    derives from the other cheaply. The raw :class:`librelane.config.Config`
    carries :attr:`~librelane.config.Config.provenance`, the diagnostics and
    the ``meta`` block, and is what gets serialized into ``resolved.json``. The
    model is what a step reads attributes off, and building one is expensive
    enough that it is done once per scope and shared, rather than once per
    step.

    The model is built on first access, not at construction. Generating it
    means a Pydantic class with a field per variable -- several hundred for a
    full flow -- and validating against it re-reads the PDK, neither of which a
    flow that is only going to be asked to ``explain()`` itself, print its help
    or list its jobs ever needs. Building it lazily also means the variable
    union underneath it is only demanded of a flow that will actually run
    steps.

    Attributes
    ----------
    raw : Config
        The resolved configuration, exactly as the loader produced it.
    typed : BaseConfigModel
        ``raw`` validated against a model covering every variable in scope: for
        a flow, the union its
        :meth:`~librelane.engine.Flow.get_all_config_variables` collects, which
        is why one model can serve every step the flow runs.
    """

    __slots__ = ("raw", "_model", "_typed", "_lock")

    def __init__(self, raw: "Config", model: Any) -> None:
        """
        Parameters
        ----------
        raw : Config
            The resolved configuration.
        model
            The model to validate it against: a ``BaseConfigModel`` *type*, or
            a zero-argument callable returning one, which is what defers the
            generation described above.
        """
        self.raw = raw
        self._model = model
        self._typed: "BaseConfigModel | None" = None
        # Several jobs run concurrently and any of them may be the first to
        # read a scope they share -- the flow's own, when neither declares a
        # 'with' block. Without this they would each build a model and the last
        # to finish would decide which one every later reader gets, so two
        # steps in one run could hold configurations from different objects.
        self._lock = threading.Lock()

    @property
    def typed(self) -> "BaseConfigModel":
        if self._typed is None:
            with self._lock:
                if self._typed is None:
                    model_type = self._model
                    if not isinstance(model_type, type):
                        model_type = model_type()
                    self._typed = model_type.model_validate(
                        self.raw.to_raw_dict(include_meta=False),
                        strict=True,
                    ).attach_context(
                        diagnostics=self.raw.diagnostics,
                        meta=self.raw.meta,
                    )
        return self._typed

    def __repr__(self) -> str:  # pragma: no cover
        built = "built" if self._typed is not None else "unbuilt"
        return f"ConfigScope({built})"


#: The singleton. Written by :func:`set_current_config` and read whenever no
#: scope is open. A module global rather than a context variable default so
#: that a configuration set on the main thread is visible on a thread that was
#: started without copying its context -- which a notebook, a plugin or a
#: caller's own ``threading.Thread`` may well be.
_current: ConfigScope | None = None

#: The scoped override. Its default is deliberately ``None`` rather than the
#: singleton, so that leaving a scope falls back to whatever the singleton is
#: *then*, not to whatever it was when the context variable was created.
_scoped: contextvars.ContextVar[ConfigScope | None] = contextvars.ContextVar(
    "librelane_current_config",
    default=None,
)


def current_scope() -> ConfigScope | None:
    """
    Returns
    -------
    ConfigScope | None
        The innermost open scope, the process-wide one if none is open, or
        ``None`` if neither is set.
    """
    return _scoped.get() or _current


def current_config() -> "BaseConfigModel":
    """
    The configuration this execution reads, as a typed model.

    Returns
    -------
    BaseConfigModel
        The scoped configuration if one is open, otherwise the process-wide
        one.

    Raises
    ------
    NoCurrentConfig
        If neither tier holds a configuration.
    """
    scope = current_scope()
    if scope is None:
        raise NoCurrentConfig()
    return scope.typed


def current_raw_config() -> "Config":
    """
    The same configuration :func:`current_config` answers with, as the
    untyped :class:`librelane.config.Config` the loader produced -- which is
    what carries provenance, diagnostics and ``meta``.

    Returns
    -------
    Config
        The resolved configuration.

    Raises
    ------
    NoCurrentConfig
        If neither tier holds a configuration.
    """
    scope = current_scope()
    if scope is None:
        raise NoCurrentConfig()
    return scope.raw


def get_current_config() -> "BaseConfigModel | None":
    """
    Returns
    -------
    BaseConfigModel | None
        As :func:`current_config`, but ``None`` instead of raising when
        nothing is current. For callers that treat "no configuration" as an
        ordinary answer rather than a mistake.
    """
    scope = current_scope()
    return None if scope is None else scope.typed


def set_current_config(scope: ConfigScope | None) -> ConfigScope | None:
    """
    Writes the process-wide slot.

    Parameters
    ----------
    scope : ConfigScope | None
        What to publish, or ``None`` to clear it.

    Returns
    -------
    ConfigScope | None
        What was there before, so a caller that means to restore it can.
    """
    global _current
    previous = _current
    _current = scope
    return previous


@contextmanager
def use_config(scope: ConfigScope) -> Iterator[ConfigScope]:
    """
    Makes ``scope`` current for the duration of the block, for this execution
    only.

    Concurrent executions do not see each other's scopes, which is what makes
    this usable for a job's ``with`` block and for a sweep's passes: work
    submitted to a
    :class:`~librelane.common.tpe.ContextPropagatingThreadPoolExecutor` from
    inside the block inherits the scope, and work submitted from outside it
    does not.

    Parameters
    ----------
    scope : ConfigScope
        The configuration to make current.

    Yields
    ------
    ConfigScope
        ``scope``, so that ``with use_config(x) as config:`` reads naturally.
    """
    token = _scoped.set(scope)
    try:
        yield scope
    finally:
        _scoped.reset(token)


def scope_model(
    variables: Any,
    name: str = "AmbientConfig",
    base: Any = None,
) -> Any:
    """
    Generates the model a scope validates against.

    Separate from :func:`build_scope` because generating it is the expensive
    half -- Pydantic builds a class with a field per variable, several hundred
    of them for a full flow -- and a flow that resolves a configuration per job
    and per sweep pass validates many configurations against one such model.

    Parameters
    ----------
    variables : Sequence[librelane.config.variable.Variable]
        Every variable the scope's readers may declare.
    name : str
        A name for the generated model, which shows up in validation errors.
    base : type[BaseConfigModel] | None
        The model to derive from, defaulting to
        :class:`librelane.config.BaseConfigModel`.

        A caller whose readers are steps passes ``Step.Config``, which is what
        :meth:`librelane.engine.Flow.config_model_type` does. It is a parameter
        rather than something looked up here because reaching into
        :mod:`librelane.steps` from :mod:`librelane.config` inverts the
        layering -- steps are built on configuration, not the other way round
        -- and the import had to be function-local to keep that inversion from
        being a cycle.

    Returns
    -------
    type[BaseConfigModel]
        The generated model.
    """
    from librelane.config.model import BaseConfigModel, variables_to_model

    return variables_to_model(name, list(variables), base=base or BaseConfigModel)


def build_scope(
    config: "Config",
    variables: Any = None,
    *,
    model_type: Any = None,
    name: str = "AmbientConfig",
    base: Any = None,
) -> ConfigScope:
    """
    Pairs ``config`` with the model it will be read through.

    Neither generating the model nor validating against it happens here; see
    :attr:`ConfigScope.typed` for why both wait until something reads it.

    Parameters
    ----------
    config : Config
        A resolved configuration.
    variables : Sequence[librelane.config.variable.Variable] | Callable | None
        Every variable the scope's readers may declare, or a callable
        returning them -- which is how a caller keeps the union itself from
        being computed for a flow that never runs. For a flow this is the union
        across its steps, which is what lets one model serve all of them.
        Ignored when ``model_type`` is given.
    model_type : type[BaseConfigModel] | Callable | None
        An already-generated model, from :func:`scope_model`, or a callable
        returning one. Pass one when building several scopes over the same
        variable set: an eight-point sweep resolves eight configurations that
        all cover the same variables.
    name : str
        A name for the generated model, which shows up in validation errors.
    base : type[BaseConfigModel] | None
        The model to derive from. See :func:`scope_model`. Ignored when
        ``model_type`` is given.

    Returns
    -------
    ConfigScope
        The configuration paired with its model.
    """
    if model_type is not None:
        return ConfigScope(config, model_type)
    if variables is None:
        raise TypeError("build_scope needs either 'variables' or 'model_type'")
    return ConfigScope(
        config,
        lambda: scope_model(
            variables() if callable(variables) else variables,
            name,
            base,
        ),
    )


__all__ = [
    "ConfigScope",
    "NoCurrentConfig",
    "build_scope",
    "current_config",
    "current_raw_config",
    "current_scope",
    "get_current_config",
    "scope_model",
    "set_current_config",
    "use_config",
]
