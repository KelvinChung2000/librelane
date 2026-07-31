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
"""The :class:`Stage` dataclass, its factory, and the shared contract constants."""

import builtins
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import ClassVar

from librelane.common.errors import FlowError
from librelane.state import DesignFormat


class StageError(RuntimeError):
    """
    Raised when a stage or a stage registration is itself malformed. This is a
    programming error in a provider package and surfaces at import time.
    """


class StageResolutionError(FlowError):
    """
    Raised when a configuration cannot be resolved to a concrete step list:
    an unknown provider, an inconsistent span selection, a missing PDK
    variable, or an unsatisfiable view dependency.
    """


class StageContractError(FlowError):
    """
    Raised at runtime when a stage completes without having produced every
    view or metric it declared.
    """


class StageMetaclass(type):
    def __getattr__(Self, key: str):
        stage = Self.factory.get(key)
        if stage is not None:
            return stage
        raise AttributeError("Unknown Stage attribute", key, Self)


@dataclass(frozen=True)
class Stage(metaclass=StageMetaclass):
    """
    A named phase of a flow. A stage is the unit of tool substitution and of
    independent gating. It never executes anything: a provider registration
    binds it to a sequence of concrete steps.

    Parameters
    ----------
    id : str
        A lowercase alphanumeric/underscore identifier, for example
        ``detailed_routing``. This is what appears in the ``TOOLS``
        configuration key. It is not accepted by ``--from``/``--to``, which
        resolve concrete step IDs only; re-entering a flow at a stage is not
        implemented.
    full_name : str
        A human-readable name.
    default_provider : str | tuple[str, ...] | None
        The provider used when ``TOOLS`` does not name
        one. A tuple of provider names is legal only for a
        :attr:`multi_provider` stage. ``None`` is legal only when
        :attr:`optional` is ``True``, in which case the stage is unselected and
        contributes no steps.
    requires : tuple[DesignFormat, ...]
        The neutral views the stage consumes at its boundary.
        A provider may additionally consume its own native views, declared on
        the registration.
    provides : tuple[DesignFormat, ...]
        The neutral views every provider of this stage must have
        produced by the time the stage completes. Enforced at runtime.
    metrics : tuple[str, ...]
        The metric names every provider of this stage must have
        produced by the time it completes. Enforced at runtime.
    gating_config_var : str | None
        A Boolean flow configuration variable that, when
        false, skips every step of this stage.
    multi_provider : bool
        Whether ``TOOLS`` may name a list of providers for
        this stage, whose sequences are concatenated in listed order.
    optional : bool
        Whether the stage may be left unselected. Only legal for
        stages whose :attr:`provides` no later stage requires.
    """

    id: str
    full_name: str
    default_provider: str | tuple[str, ...] | None
    requires: tuple[DesignFormat, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...] = field(default=())
    gating_config_var: str | None = None
    multi_provider: bool = False
    optional: bool = False

    def __hash__(self):
        return hash(self.id)

    def __str__(self) -> str:
        return self.id

    @property
    def default_providers(self) -> tuple[str, ...]:
        """
        Returns
        -------
        tuple[str, ...]
            :attr:`default_provider` normalized to a tuple. Empty when
            the stage is unselected by default.
        """
        if self.default_provider is None:
            return ()
        if isinstance(self.default_provider, str):
            return (self.default_provider,)
        return tuple(self.default_provider)

    def using(self, provider: "str | Sequence[str]") -> "Stage":
        """
        Pins the tool this stage runs, for use in a flow's ``Stages`` list::

            Stages = [..., Stage.synthesis.using("yosys_vhdl"), ...]

        Parameters
        ----------
        provider : str | Sequence[str]
            The provider name, or several for a
            :attr:`multi_provider` stage, whose sequences are concatenated in
            listed order.

        Returns
        -------
        Stage
            A copy of this stage whose :attr:`default_provider` is
            ``provider``. The copy is deliberately *not* registered: it keeps
            this stage's ``id``, so a ``TOOLS`` entry naming that id still
            overrides the pin, because resolution consults ``TOOLS`` before
            ``default_provider``. A pin is a flow's default, not a lock.

        Raises
        ------
        StageError
            If several providers are named for a stage that runs
            exactly one tool, or if no provider is named at all.

        Naming a list is the multi-provider idiom, and is how a flow pins several
        tools to one stage. It is legal only for a :attr:`multi_provider` stage.

        The provider is not checked against the registry here. Registration
        order follows import order, so a check at flow-definition time would be
        fragile; resolution rejects an unknown provider naming the registered
        alternatives instead.
        """
        if not isinstance(provider, str):
            provider = tuple(provider)
            if not self.multi_provider:
                raise StageError(
                    f"Stage '{self.id}' does not accept a list of providers: it "
                    f"runs exactly one tool. Got {list(provider)}."
                )
            if len(provider) == 0:
                raise StageError(
                    f"Stage '{self.id}': 'using' was given an empty provider "
                    f"list. To skip a stage, use its gating variable; there is "
                    f"no way to select nothing."
                )
        return replace(self, default_provider=provider)

    def register(self) -> "Stage":
        """
        Adds this stage to the registry. Raises :class:`StageError` if a stage
        with the same id is already registered, or if the stage is internally
        inconsistent.
        """
        if self.default_provider is None and not self.optional:
            raise StageError(
                f"Stage '{self.id}' has no default_provider but is not marked "
                f"optional. Only optional stages may be left unselected."
            )
        if len(self.default_providers) > 1 and not self.multi_provider:
            raise StageError(
                f"Stage '{self.id}' defaults to several providers "
                f"{list(self.default_providers)} but is not multi_provider."
            )
        self.__class__.factory.register(self)
        return self

    class StageFactory(object):
        """
        A factory singleton for Stages, allowing them to be registered and
        then retrieved by a string id.
        """

        _registry: ClassVar[dict[str, "Stage"]] = {}

        @classmethod
        def register(Self, stage: "Stage") -> "Stage":
            if stage.id in Self._registry:
                raise StageError(f"Stage '{stage.id}' is already registered.")
            Self._registry[stage.id] = stage
            return stage

        @classmethod
        def get(Self, id: str) -> "Stage | None":
            return Self._registry.get(id)

        @classmethod
        def list(Self) -> builtins.list[str]:
            return list(Self._registry.keys())

    factory: ClassVar = StageFactory


#: The view contract shared by every in-place place-and-route transform: a
#: stage that takes a placed-or-routed design and returns one, changing the
#: layout but not the set of views. Declared once and reused rather than
#: restated on each of the fifteen stages that share it.
PNR_IN_PLACE_REQUIRES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)

PNR_IN_PLACE_PROVIDES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)
