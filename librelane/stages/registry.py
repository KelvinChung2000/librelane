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

from ..config import Variable
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

    :param stages: The stage ids covered, in flow order. Length greater than
        one means the provider cannot decompose this span; see the
        "Spanning providers" section of the design document.
    :param provider: The tool name, for example ``openroad``. Not a vendor
        name.
    :param steps: The ordered step sequence that implements the span.
    :param namespaces: Accepted configuration variable prefixes for steps in
        this sequence. New providers declare exactly one, tool-named prefix;
        the ``openroad`` provider declares the several legacy prefixes that
        predate this design.
    :param requires_pdk_vars: Configuration variable names that must be
        non-``None`` in the resolved configuration for this provider to run.
        Checked by the PDK view preflight.
    :param provides: Views this provider guarantees beyond the stage's own
        ``provides``.
    :param metrics: Metric names this provider guarantees beyond the stage's
        own ``metrics``.
    :param native_views: Tool-native views this provider carries across stage
        boundaries itself, for example OpenROAD's ``odb``. Exempt from the
        registration-time view check; validated instead by the static view
        availability check at resolution.
    """

    stages: tuple[str, ...]
    provider: str
    steps: tuple[type[Step], ...]
    namespaces: tuple[str, ...]
    requires_pdk_vars: tuple[str, ...] = ()
    provides: tuple[DesignFormat, ...] = ()
    metrics: tuple[str, ...] = ()
    native_views: tuple[DesignFormat, ...] = ()

    @property
    def spanning(self) -> bool:
        return len(self.stages) > 1

    def tagged_steps(self) -> builtins.list[type[Step]]:
        """
        Returns the step sequence with each class subclassed to carry
        ``_stage_span`` and ``_stage_provider``.

        Tagging by subclass rather than by index range is what makes the
        boundary map survive duplicate-ID normalization and ``Substitutions``:
        ``Step.with_id`` also subclasses, so the tag is inherited, while a
        substituted-in step class carries no tag and is correctly treated as a
        plain step.
        """
        return [
            type(
                step.__name__,
                (step,),
                {
                    "_stage_span": self.stages,
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
        stages: Sequence[str],
        provider: str,
        steps: Sequence[type[Step]],
        namespaces: Sequence[str],
        requires_pdk_vars: Sequence[str] = (),
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
            stages=tuple(stages),
            provider=provider,
            steps=tuple(steps),
            namespaces=tuple(namespaces),
            requires_pdk_vars=tuple(requires_pdk_vars),
            provides=tuple(provides),
            metrics=tuple(metrics),
            native_views=tuple(native_views),
        )

        if len(registration.stages) == 0:
            raise StageError(f"Provider '{provider}' registered against no stages.")
        if len(registration.steps) == 0:
            raise StageError(
                f"Provider '{provider}' registered for "
                f"{list(registration.stages)} with no steps. A provider that "
                f"runs nothing cannot satisfy a stage contract."
            )

        resolved: builtins.list[Stage] = []
        for stage_id in registration.stages:
            stage = Stage.factory.get(stage_id)
            if stage is None:
                raise StageError(
                    f"Provider '{provider}': no stage with id '{stage_id}' is "
                    f"registered. Known stages: {sorted(Stage.factory.list())}"
                )
            key = (stage_id, provider)
            if key in Self._by_stage_and_provider:
                raise StageError(
                    f"Provider '{provider}' is already registered for stage "
                    f"'{stage_id}'."
                )
            resolved.append(stage)

        Self.__check_contract(registration, resolved)

        for stage_id in registration.stages:
            Self._by_stage_and_provider[(stage_id, provider)] = registration
        Self._all.append(registration)
        return registration

    @classmethod
    def __check_contract(
        Self,
        registration: Registration,
        stages: Sequence[Stage],
    ) -> None:
        union = compose_step_sequence(registration.steps)
        declared = {variable.name for variable in union.config_vars}

        canonical: dict[str, Variable] = {}
        for stage in stages:
            for variable in stage.config_vars:
                canonical[variable.name] = variable

        # Canonical variable coverage.
        for name in canonical:
            if name not in declared:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"{list(registration.stages)} does not declare canonical "
                    f"variable '{name}'. A user who set it would have that "
                    f"setting silently discarded."
                )

        # Namespace discipline.
        for variable in union.config_vars:
            if variable.name in canonical:
                continue
            if variable.name in _COMMON_VARIABLE_NAMES:
                continue
            if any(
                variable.name.startswith(prefix) for prefix in registration.namespaces
            ):
                continue
            raise StageError(
                f"Provider '{registration.provider}' for "
                f"{list(registration.stages)} declares variable "
                f"'{variable.name}', which is neither canonical for these "
                f"stages, nor a common flow variable, nor prefixed with any "
                f"of {list(registration.namespaces)}."
            )

        # View plausibility.
        allowed_inputs = set(registration.native_views)
        for stage in stages:
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
                    f"{list(registration.stages)} consumes view '{view.id}', "
                    f"which is neither in the stages' 'requires' nor declared "
                    f"as one of its native_views."
                )

        promised = set(registration.provides)
        for stage in stages:
            promised.update(stage.provides)
        produced = set(union.outputs)
        for view in promised:
            if view not in produced:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"{list(registration.stages)} never produces view "
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
            if stage in registration.stages
        ]

    @classmethod
    def list(Self) -> builtins.list[Registration]:
        return list(Self._all)
