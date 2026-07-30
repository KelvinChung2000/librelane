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

from ..state import DesignFormat
from ..steps import Step

from .registry import Registration, StageRegistry
from .stage import Stage, StageResolutionError

#: An entry in a flow's ``Stages`` list: either a stage to be expanded, or a
#: plain step that sits at a stage boundary.
StageEntry = Union[Stage, type[Step]]

#: A ``TOOLS`` value: one provider, or several for a multi-provider stage.
ToolSelection = Union[str, Sequence[str]]


@dataclass(frozen=True)
class ResolvedSpan:
    """
    One stage, or one contiguous span of stages, bound to the provider chosen
    for it and to the contract that must hold when it completes.
    """

    stage_ids: tuple[str, ...]
    provider: str
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]
    gating_config_var: str | None


@dataclass(frozen=True)
class Resolution:
    steps: list[type[Step]]
    spans: list[ResolvedSpan]
    unselected: tuple[str, ...]


def _selection_for(
    stage: Stage,
    tools: Mapping[str, ToolSelection],
) -> tuple[str, ...] | None:
    """
    :returns: The provider names chosen for this stage, or ``None`` if the
        stage is unselected.
    """
    if stage.id not in tools:
        return stage.default_providers or None

    value = tools[stage.id]
    if isinstance(value, str):
        return (value,)
    if not stage.multi_provider:
        raise StageResolutionError(
            f"stage '{stage.id}' does not accept a list of providers: it runs "
            f"exactly one tool. Got {list(value)}."
        )
    if len(value) == 0:
        raise StageResolutionError(
            f"stage '{stage.id}': TOOLS names an empty provider list. To skip "
            f"a stage, use its gating variable; there is no way to select "
            f"nothing."
        )
    return tuple(value)


def _registration_for(stage: Stage, provider: str) -> Registration:
    registration = StageRegistry.get(stage.id, provider)
    if registration is None:
        available = StageRegistry.providers(stage.id)
        if available:
            detail = f"Registered providers for this stage: {sorted(available)}."
        else:
            detail = "No provider is registered for this stage."
        raise StageResolutionError(
            f"stage '{stage.id}': no provider named '{provider}' is registered. {detail}"
        )
    if registration.spanning:
        raise StageResolutionError(
            f"stage '{stage.id}': provider '{provider}' is a spanning "
            f"registration covering {list(registration.stages)}, which is not "
            f"supported: no provider may cover more than one stage."
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
        raise StageResolutionError(
            f"TOOLS names '{key}', which is not a stage in this flow.{suggestion}"
        )


def resolve(
    entries: Sequence[StageEntry],
    tools: Mapping[str, ToolSelection],
) -> Resolution:
    """
    Expands a flow's ``Stages`` list into a flat list of concrete step classes,
    choosing a provider per stage from ``tools`` and falling back to each
    stage's ``default_provider`` where ``tools`` is silent.

    :param entries: The flow's ``Stages`` list: ``Stage`` objects interleaved
        with plain ``Step`` classes.
    :param tools: The resolved ``TOOLS`` mapping.
    :raises StageResolutionError: On any unknown stage key, unknown provider,
        or misuse of a list value.
    """
    stage_ids = [entry.id for entry in entries if isinstance(entry, Stage)]
    _check_tool_keys(tools, stage_ids)

    steps: list[type[Step]] = []
    spans: list[ResolvedSpan] = []
    unselected: list[str] = []

    for entry in entries:
        if not isinstance(entry, Stage):
            steps.append(entry)
            continue

        providers = _selection_for(entry, tools)
        if providers is None:
            unselected.append(entry.id)
            continue

        span_steps: list[type[Step]] = []
        provides = set(entry.provides)
        metrics = set(entry.metrics)
        for provider in providers:
            registration = _registration_for(entry, provider)
            span_steps.extend(registration.tagged_steps())
            provides.update(registration.provides)
            metrics.update(registration.metrics)

        steps.extend(span_steps)
        spans.append(
            ResolvedSpan(
                stage_ids=(entry.id,),
                provider="+".join(providers),
                provides=tuple(sorted(provides, key=lambda view: view.id)),
                metrics=tuple(sorted(metrics)),
                gating_config_var=entry.gating_config_var,
            )
        )

    return Resolution(steps, spans, tuple(unselected))
