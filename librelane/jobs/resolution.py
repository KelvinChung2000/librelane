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
"""Turning a ``Stages`` list plus a ``TOOLS`` mapping into a flat step list."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Union

from rapidfuzz import fuzz, process, utils

from librelane.state import DesignFormat
from librelane.steps import Step

from librelane.jobs.registry import Registration, JobRegistry
from librelane.jobs.job import Job, JobResolutionError

#: An entry in a flow's ``Stages`` list: either a job to be expanded, or a
#: plain step that sits at a job boundary.
JobEntry = Union[Job, type[Step]]

#: A ``TOOLS`` value: one provider, or several for a multi-provider job.
ToolSelection = Union[str, Sequence[str]]


@dataclass(frozen=True)
class ProviderContract:
    """
    What one provider of a job promises on its own account: the views and
    metrics its :class:`librelane.jobs.Registration` declares beyond the job's.

    Held separately from the job's own contract because the two have different
    scopes on a ``multi_provider`` job. Each provider of ``drc`` runs its own
    deck and contracts its own metric, so gating one off must not excuse the
    other; the job's own contract, by contrast, is satisfied by the providers
    jointly.
    """

    provider: str
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedSpan:
    """
    One job, bound to the providers chosen for it and to the contract that
    must hold when it completes.

    Parameters
    ----------
    provides : tuple[DesignFormat, ...]
        The views the *job* owes once it completes, which its
        selected providers satisfy jointly.
    metrics : tuple[str, ...]
        Likewise for metrics.
    providers : tuple[ProviderContract, ...]
        One entry per selected provider, in the order their step
        sequences were concatenated, carrying what that provider owes alone.
    """

    job_ids: tuple[str, ...]
    providers: tuple[ProviderContract, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]
    gating_config_var: str | None

    @property
    def provider(self) -> str:
        """
        Returns
        -------
        str
            The selected provider names as one string, joined by ``+`` for
            a multi-provider job.
        """
        return "+".join(contract.provider for contract in self.providers)

    def contract_for(self, provider: str) -> ProviderContract:
        """
        Returns
        -------
        ProviderContract
            The named provider's own contract.

        Raises
        ------
        JobResolutionError
            If this resolution did not select that
            provider, which means the step tags and the resolution disagree.
        """
        for contract in self.providers:
            if contract.provider == provider:
                return contract
        raise JobResolutionError(
            f"job {list(self.job_ids)}: this resolution selected "
            f"{[contract.provider for contract in self.providers]}, not "
            f"'{provider}'. A step tagged for a provider the resolution did not "
            f"select is a programming error, not a configuration mistake."
        )


@dataclass(frozen=True)
class Resolution:
    steps: list[type[Step]]
    spans: list[ResolvedSpan]
    unselected: tuple[str, ...]


def _selection_for(
    job: Job,
    tools: Mapping[str, ToolSelection],
) -> tuple[str, ...] | None:
    """
    Returns
    -------
    tuple[str, ...] | None
        The provider names chosen for this job, or ``None`` if the
        job is unselected.
    """
    if job.id not in tools:
        return job.default_providers or None

    value = tools[job.id]
    if isinstance(value, str):
        return (value,)
    if not job.multi_provider:
        raise JobResolutionError(
            f"job '{job.id}' does not accept a list of providers: it runs "
            f"exactly one tool. Got {list(value)}."
        )
    if len(value) == 0:
        raise JobResolutionError(
            f"job '{job.id}': TOOLS names an empty provider list. To skip "
            f"a job, use its gating variable; there is no way to select "
            f"nothing."
        )
    return tuple(value)


def _registration_for(job: Job, provider: str) -> Registration:
    registration = JobRegistry.get(job.id, provider)
    if registration is None:
        available = JobRegistry.providers(job.id)
        if available:
            detail = f"Registered providers for this job: {sorted(available)}."
        else:
            detail = "No provider is registered for this job."
        raise JobResolutionError(
            f"job '{job.id}': no provider named '{provider}' is registered. {detail}"
        )
    return registration


def _check_tool_keys(
    tools: Mapping[str, ToolSelection],
    known: Sequence[str],
) -> None:
    for key in tools:
        if key in known:
            continue
        suggestion = ""
        match = process.extractOne(
            key,
            list(known),
            scorer=fuzz.partial_ratio,
            score_cutoff=80,
            processor=utils.default_process,
        )
        if match is not None:
            suggestion = f" Did you mean: '{match[0]}'?"
        raise JobResolutionError(
            f"TOOLS names '{key}', which is not a job in this flow.{suggestion}"
        )


def resolve(
    entries: Sequence[JobEntry],
    tools: Mapping[str, ToolSelection],
) -> Resolution:
    """
    Expands a flow's ``Stages`` list into a flat list of concrete step classes,
    choosing a provider per job from ``tools`` and falling back to each
    job's ``default_provider`` where ``tools`` is silent.

    Parameters
    ----------
    entries : Sequence[JobEntry]
        The flow's ``Stages`` list: ``Job`` objects interleaved
        with plain ``Step`` classes.
    tools : Mapping[str, ToolSelection]
        The resolved ``TOOLS`` mapping.

    Raises
    ------
    JobResolutionError
        On any unknown job key, unknown provider,
        or misuse of a list value.
    """
    job_ids = [entry.id for entry in entries if isinstance(entry, Job)]
    _check_tool_keys(tools, job_ids)

    steps: list[type[Step]] = []
    spans: list[ResolvedSpan] = []
    unselected: list[str] = []

    for entry in entries:
        if not isinstance(entry, Job):
            steps.append(entry)
            continue

        providers = _selection_for(entry, tools)
        if providers is None:
            unselected.append(entry.id)
            continue

        contracts: list[ProviderContract] = []
        for provider in providers:
            registration = _registration_for(entry, provider)
            steps.extend(registration.tagged_steps())
            contracts.append(
                ProviderContract(
                    provider=provider,
                    provides=tuple(
                        sorted(set(registration.provides), key=lambda view: view.id)
                    ),
                    metrics=tuple(sorted(set(registration.metrics))),
                )
            )

        spans.append(
            ResolvedSpan(
                job_ids=(entry.id,),
                providers=tuple(contracts),
                provides=tuple(sorted(set(entry.provides), key=lambda view: view.id)),
                metrics=tuple(sorted(set(entry.metrics))),
                gating_config_var=entry.gating_config_var,
            )
        )

    return Resolution(steps, spans, tuple(unselected))
