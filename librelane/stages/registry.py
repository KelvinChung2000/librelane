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
"""The :class:`Registration` dataclass and the :class:`StageRegistry` singleton."""

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from ..config.flow import flow_common_variables
from ..state import DesignFormat
from ..steps import Step
from ..steps.step.composition import compose_step_sequence

from .stage import Stage, StageError

_COMMON_VARIABLE_NAMES = frozenset(variable.name for variable in flow_common_variables)


@dataclass(frozen=True)
class Registration:
    """
    Binds a span of one or more consecutive stages, plus one provider, to an
    ordered sequence of concrete steps.

    :param stage: The stage id this registration implements. Exactly one. A
        provider that cannot decompose a span of stages has no way to say so,
        deliberately: gating, contract checking and provider selection are all
        per-stage.
    :param provider: The tool name, for example ``openroad``. Not a vendor
        name.
    :param steps: The ordered step sequence that implements the span.
    :param namespaces: Accepted configuration variable prefixes for steps in
        this sequence. New providers declare exactly one, tool-named prefix;
        the ``openroad`` provider declares the several legacy prefixes that
        predate this design.
    :param provides: Views this provider guarantees beyond the stage's own
        ``provides``.
    :param metrics: Metric names this provider guarantees beyond the stage's
        own ``metrics``.
    :param native_views: Tool-native views this provider carries across stage
        boundaries itself, for example OpenROAD's ``odb``. Exempt from the
        registration-time view check; validated instead by the static view
        availability check at resolution.
    """

    stage: str
    provider: str
    steps: tuple[type[Step], ...]
    namespaces: tuple[str, ...]
    provides: tuple[DesignFormat, ...] = ()
    metrics: tuple[str, ...] = ()
    native_views: tuple[DesignFormat, ...] = ()

    def tagged_steps(self) -> builtins.list[type[Step]]:
        """
        Returns the step sequence with each class subclassed to carry
        ``_stage_span`` and ``_stage_provider``.

        Tagging by subclass rather than by index range is what makes the
        boundary map survive duplicate-ID normalization:
        ``Step.with_id`` also subclasses, so the tag is inherited, while an
        untagged step class is correctly treated as a plain step.
        """
        return [
            type(
                step.__name__,
                (step,),
                {
                    "_stage_span": (self.stage,),
                    "_stage_provider": self.provider,
                },
            )
            for step in self.steps
        ]


class StageRegistry(object):
    """
    A factory singleton mapping (stage id, provider) pairs to
    :class:`Registration` objects.
    """

    _by_stage_and_provider: ClassVar[dict[tuple[str, str], Registration]] = {}
    _all: ClassVar[builtins.list[Registration]] = []

    @classmethod
    def register(
        Self,
        *,
        stage: str,
        provider: str,
        steps: Sequence[type[Step]],
        namespaces: Sequence[str],
        provides: Sequence[DesignFormat] = (),
        metrics: Sequence[str] = (),
        native_views: Sequence[DesignFormat] = (),
    ) -> Registration:
        """
        Registers a provider implementation for a span of stages, running
        every registration-time contract check. Violations raise
        :class:`StageError`, which surfaces as an import error in the
        offending provider package.
        """
        registration = Registration(
            stage=stage,
            provider=provider,
            steps=tuple(steps),
            namespaces=tuple(namespaces),
            provides=tuple(provides),
            metrics=tuple(metrics),
            native_views=tuple(native_views),
        )

        if len(registration.steps) == 0:
            raise StageError(
                f"Provider '{provider}' registered for "
                f"stage '{registration.stage}' with no steps. A provider that "
                f"runs nothing cannot satisfy a stage contract."
            )

        resolved_stage = Stage.factory.get(registration.stage)
        if resolved_stage is None:
            raise StageError(
                f"Provider '{provider}': no stage with id "
                f"'{registration.stage}' is registered. Known stages: "
                f"{sorted(Stage.factory.list())}"
            )
        key = (registration.stage, provider)
        if key in Self._by_stage_and_provider:
            raise StageError(
                f"Provider '{provider}' is already registered for stage "
                f"'{registration.stage}'."
            )

        Self.__check_contract(registration, resolved_stage)

        Self._by_stage_and_provider[key] = registration
        Self._all.append(registration)
        return registration

    @classmethod
    def __check_contract(
        Self,
        registration: Registration,
        stage: Stage,
    ) -> None:
        union = compose_step_sequence(registration.steps)

        # Namespace discipline.
        for variable in union.config_vars:
            if variable.name in _COMMON_VARIABLE_NAMES:
                continue
            if any(
                variable.name.startswith(prefix) for prefix in registration.namespaces
            ):
                continue
            raise StageError(
                f"Provider '{registration.provider}' for "
                f"stage '{registration.stage}' declares variable "
                f"'{variable.name}', which is neither a common flow variable "
                f"nor prefixed with any of {list(registration.namespaces)}."
            )

        # View plausibility.
        allowed_inputs = set(registration.native_views)
        allowed_inputs.update(stage.requires)
        for view in union.unmet_inputs:
            # An optional input is satisfiable by absence, so it is not a
            # boundary requirement. DesignFormat.mkOptional() returns a copy
            # with a flag set, which compares unequal to the base view, so
            # this check must come before the membership test.
            if view.optional:
                continue
            if view not in allowed_inputs:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"stage '{registration.stage}' consumes view '{view.id}', "
                    f"which is neither in the stage's 'requires' nor declared "
                    f"as one of its native_views."
                )

        promised = set(registration.provides)
        promised.update(stage.provides)
        produced = set(union.outputs)
        for view in promised:
            if view not in produced:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"stage '{registration.stage}' never produces view "
                    f"'{view.id}', which it is contracted to provide."
                )

    @classmethod
    def get(Self, stage: str, provider: str) -> Registration | None:
        return Self._by_stage_and_provider.get((stage, provider))

    @classmethod
    def providers(Self, stage: str) -> builtins.list[str]:
        """
        :returns: Provider names registered for this stage, in registration
            order.
        """
        return [
            registration.provider
            for registration in Self._all
            if registration.stage == stage
        ]

    @classmethod
    def list(Self) -> builtins.list[Registration]:
        return list(Self._all)
