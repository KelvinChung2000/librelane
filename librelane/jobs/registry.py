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
"""The :class:`Registration` dataclass and the :class:`JobRegistry` singleton."""

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from librelane.config.flow import flow_common_variables
from librelane.state import DesignFormat
from librelane.steps import Step
from librelane.steps.step.composition import compose_step_sequence

from librelane.jobs.job import Job, JobDefinitionError

_COMMON_VARIABLE_NAMES = frozenset(variable.name for variable in flow_common_variables)


@dataclass(frozen=True)
class Registration:
    """
    Binds a span of one or more consecutive jobs, plus one provider, to an
    ordered sequence of concrete steps.

    Parameters
    ----------
    job : str
        The job id this registration implements. Exactly one. A
        provider that cannot decompose a span of jobs has no way to say so,
        deliberately: gating, contract checking and provider selection are all
        per-job.
    provider : str
        The tool name, for example ``openroad``. Not a vendor
        name.
    steps : tuple[type[Step], ...]
        The ordered step sequence that implements the span.
    namespaces : tuple[str, ...]
        Accepted configuration variable prefixes for steps in
        this sequence. New providers declare exactly one, tool-named prefix;
        the ``openroad`` provider declares the several legacy prefixes that
        predate this design.
    provides : tuple[DesignFormat, ...]
        Views this provider guarantees beyond the job's own
        ``provides``.
    metrics : tuple[str, ...]
        Metric names this provider guarantees beyond the job's
        own ``metrics``.
    optional_metrics : tuple[str, ...]
        Metric names this provider writes only when a precondition holds, for
        example ``klayout__drc_error__count``, which ``KLayout.DRC`` writes
        only on PDKs that ship a ``KLAYOUT_DRC_RUNSET``. Counted by
        :func:`librelane.flows.selection_validation.produced_keys` as writes
        for the join rule, and exempt from the completion-time contract check,
        which reads only ``metrics``: an optional metric's absence is the
        consumer's business — ``Misc.ReportManufacturability`` reports it as
        "may have been skipped" — not a contract violation.
    native_views : tuple[DesignFormat, ...]
        Tool-native views this provider carries across job
        boundaries itself, for example OpenROAD's ``odb``. Exempt from the
        registration-time view check below, which would otherwise refuse the
        sequence for consuming a view the job's tool-neutral ``requires`` does
        not name -- and must not name, because a neutral job cannot oblige every
        provider to speak one tool's database.

        Re-validated per run by
        :func:`librelane.flows.selection_validation.lost_views`, which reads
        this tuple off the :class:`librelane.flows.job.ResolvedJob` and treats
        each entry exactly as it treats a declared requirement. That check is a
        differential against the document's own providers, so what a wrong
        declaration costs is bounded but real: naming a view here that the
        provider does not in fact carry adds a requirement nothing has to
        satisfy, and a selection that drops the view's producer is refused for
        a job that never needed it.
    """

    job: str
    provider: str
    steps: tuple[type[Step], ...]
    namespaces: tuple[str, ...]
    provides: tuple[DesignFormat, ...] = ()
    metrics: tuple[str, ...] = ()
    optional_metrics: tuple[str, ...] = ()
    native_views: tuple[DesignFormat, ...] = ()

    @property
    def runnable(self) -> bool:
        """
        Returns
        -------
        bool
            Whether selecting this provider would run anything, which is true
            exactly when every step of it is implemented.

        Derived rather than declared, so that the sixteen commercial tool
        modules carry no per-registration boilerplate and cannot disagree with
        their own steps. :attr:`librelane.steps.Step.implemented` is the one
        place the claim is made, and it is made next to the ``run`` that would
        otherwise have to be called to find out.

        Registering a provider that is not runnable stays legal and is the
        point of :mod:`librelane.jobs.providers_vendor`: the scaffolds exist to
        be selected, inspected and filled in. What reads this is
        :mod:`librelane.flows.selection_validation`, which refuses to *offer*
        one as the remedy for a selection it just rejected. Offering is a
        promise that the alternative works, and permitting is not.
        """
        return all(step.implemented for step in self.steps)


class JobRegistry(object):
    """
    A factory singleton mapping (job id, provider) pairs to
    :class:`Registration` objects.
    """

    _by_job_and_provider: ClassVar[dict[tuple[str, str], Registration]] = {}
    _all: ClassVar[builtins.list[Registration]] = []

    @classmethod
    def register(
        Self,
        *,
        job: str,
        provider: str,
        steps: Sequence[type[Step]],
        namespaces: Sequence[str],
        provides: Sequence[DesignFormat] = (),
        metrics: Sequence[str] = (),
        optional_metrics: Sequence[str] = (),
        native_views: Sequence[DesignFormat] = (),
    ) -> Registration:
        """
        Registers a provider implementation for a span of jobs, running
        every registration-time contract check. Violations raise
        :class:`JobDefinitionError`, which surfaces as an import error in the
        offending provider package.
        """
        registration = Registration(
            job=job,
            provider=provider,
            steps=tuple(steps),
            namespaces=tuple(namespaces),
            provides=tuple(provides),
            metrics=tuple(metrics),
            optional_metrics=tuple(optional_metrics),
            native_views=tuple(native_views),
        )

        if len(registration.steps) == 0:
            raise JobDefinitionError(
                f"Provider '{provider}' registered for "
                f"job '{registration.job}' with no steps. A provider that "
                f"runs nothing cannot satisfy a job contract."
            )

        template = Job.factory.get(registration.job)
        if template is None:
            raise JobDefinitionError(
                f"Provider '{provider}': no job with id "
                f"'{registration.job}' is registered. Known jobs: "
                f"{sorted(Job.factory.list())}"
            )
        key = (registration.job, provider)
        if key in Self._by_job_and_provider:
            raise JobDefinitionError(
                f"Provider '{provider}' is already registered for job "
                f"'{registration.job}'."
            )

        Self.__check_contract(registration, template)

        Self._by_job_and_provider[key] = registration
        Self._all.append(registration)
        return registration

    @classmethod
    def __check_contract(
        Self,
        registration: Registration,
        template: Job,
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
            raise JobDefinitionError(
                f"Provider '{registration.provider}' for "
                f"job '{registration.job}' declares variable "
                f"'{variable.name}', which is neither a common flow variable "
                f"nor prefixed with any of {list(registration.namespaces)}."
            )

        # View plausibility.
        allowed_inputs = set(registration.native_views)
        allowed_inputs.update(template.requires)
        for view in union.unmet_inputs:
            # An optional input is satisfiable by absence, so it is not a
            # boundary requirement. DesignFormat.mkOptional() returns a copy
            # with a flag set, which compares unequal to the base view, so
            # this check must come before the membership test.
            if view.optional:
                continue
            if view not in allowed_inputs:
                raise JobDefinitionError(
                    f"Provider '{registration.provider}' for "
                    f"job '{registration.job}' consumes view '{view.id}', "
                    f"which is neither in the job's 'requires' nor declared "
                    f"as one of its native_views."
                )

        promised = set(registration.provides)
        promised.update(template.provides)
        produced = set(union.outputs)
        for view in promised:
            if view not in produced:
                raise JobDefinitionError(
                    f"Provider '{registration.provider}' for "
                    f"job '{registration.job}' never produces view "
                    f"'{view.id}', which it is contracted to provide."
                )

    @classmethod
    def get(Self, job: str, provider: str) -> Registration | None:
        return Self._by_job_and_provider.get((job, provider))

    @classmethod
    def providers(Self, job: str) -> builtins.list[str]:
        """
        Returns
        -------
        builtins.list[str]
            Provider names registered for this job, in registration
            order.
        """
        return [
            registration.provider
            for registration in Self._all
            if registration.job == job
        ]

    @classmethod
    def list(Self) -> builtins.list[Registration]:
        return list(Self._all)
