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
Binding a document's jobs to the registry, producing the units the engine runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from rapidfuzz import fuzz, process, utils

from librelane.flows.spec import FlowSpec, JobSpec, parse_condition
from librelane.jobs import Job, JobRegistry, JobResolutionError
from librelane.state import DesignFormat
from librelane.steps import Step

#: A ``TOOLS`` value as the pre-pass hands it over. A list is accepted here and
#: rejected with an explanation by :func:`_checked_selections`, rather than
#: being refused by the configuration model with a type error that does not say
#: what replaced it. Not to be confused with
#: :func:`librelane.jobs.resolution._check_tool_keys`, which is the equivalent
#: for the ``StagedFlow`` resolver and takes stage ids.
ToolSelection = str | list[str]


@dataclass(frozen=True)
class ResolvedJob:
    """
    A document's job declaration bound to a registered template.

    Never written by hand. ``needs``, ``source`` and ``conditions`` come from
    the document; ``requires``, ``provides``, ``metrics`` and ``steps`` come
    from the template, or from the steps themselves for an inline job.

    ``source`` is keyed by string rather than by
    :class:`librelane.state.DesignFormat` because the join rule is one rule
    over views and metrics and a metric name is not a view.

    ``conditions`` is the ``if`` conjunction already split into its variable
    names, empty when the job declares no ``if``. The job runs when every named
    variable is true.
    """

    id: str
    needs: tuple[str, ...]
    source: dict[str, str]
    conditions: tuple[str, ...]
    requires: tuple[DesignFormat, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]
    steps: tuple[type[Step], ...]
    provider: str | None


def resolve_jobs(
    spec: FlowSpec,
    tools: Mapping[str, ToolSelection] | None = None,
) -> dict[str, ResolvedJob]:
    """
    Parameters
    ----------
    spec : FlowSpec
        A document that has passed ``validate_against_registry``.
    tools : Mapping[str, ToolSelection] | None
        The ``TOOLS`` mapping, keyed by **job id**. It overrides the provider
        half of that job's ``uses`` and never the stage half, so a job keeps
        the name the document gave it, and it overrides a provider the document
        pinned as well as one it left to the template's default.

    Returns
    -------
    Each job id mapped to its :class:`ResolvedJob`, in document order.

    Raises
    ------
    JobResolutionError
        If ``tools`` names a job the document does not declare, a job that
        lists its steps inline, a list of providers, or a provider no
        registration supplies.
    """
    selections = _checked_selections(tools or {}, spec)
    return {
        name: _resolve(name, job, selections.get(name))
        for name, job in spec.jobs.items()
    }


def _checked_selections(
    tools: Mapping[str, ToolSelection],
    spec: FlowSpec,
) -> dict[str, str]:
    """
    Returns
    -------
    The same mapping, once every key that cannot mean anything for this
    document has been rejected. One provider per job, so the value type is
    narrowed here rather than carried further.

    A key naming a *stage* rather than a job lands in the first case, which is
    the whole point of the re-keying: one stage may run under several job
    names, as ``streamout`` does, and there is no job for the stage id itself
    to name.
    """
    selections: dict[str, str] = {}
    for key, value in tools.items():
        job = spec.jobs.get(key)
        if job is None:
            suggestion = ""
            match = process.extractOne(
                key,
                list(spec.jobs),
                scorer=fuzz.partial_ratio,
                score_cutoff=80,
                processor=utils.default_process,
            )
            if match is not None:
                suggestion = f" Did you mean: '{match[0]}'?"
            raise JobResolutionError(
                f"TOOLS names '{key}', which is not a job of flow "
                f"'{spec.name}'.{suggestion} Declared jobs: "
                f"{sorted(spec.jobs)}."
            )
        if job.steps is not None:
            raise JobResolutionError(
                f"TOOLS names job '{key}', which lists its steps inline and so "
                f"has no provider to override. Only a job with a 'uses' key "
                f"can be re-pointed at another tool."
            )
        if not isinstance(value, str):
            raise JobResolutionError(
                f"TOOLS['{key}'] is a list. One job runs one provider; to run "
                f"two tools, declare two jobs with the same 'uses' stage and "
                f"different providers, as classic.yaml does for streamout."
            )
        selections[key] = value
    return selections


def _resolve(name: str, spec: JobSpec, override: str | None) -> ResolvedJob:
    conditions = () if spec.condition is None else parse_condition(spec.condition)

    if spec.steps is not None:
        steps = []
        for step_id in spec.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            steps.append(step)
        requires: set[DesignFormat] = set()
        provides: set[DesignFormat] = set()
        for step in steps:
            requires.update(step.inputs)
            provides.update(step.outputs)
        return ResolvedJob(
            id=name,
            needs=tuple(spec.needs),
            source=dict(spec.source),
            conditions=conditions,
            requires=tuple(sorted(requires, key=str)),
            provides=tuple(sorted(provides, key=str)),
            metrics=(),
            steps=tuple(steps),
            provider=None,
        )

    # An omitted 'uses' is the document's central convenience: a job whose id
    # is a registered template id means that template, which is why the sample
    # 'lint' and 'floorplan' jobs carry no 'uses' at all. JobSpec deliberately
    # does not reject the "neither" case -- the template ids live in the job
    # registry, which the model layer does not import -- and
    # spec_validation._require_implementation admits it whenever the id
    # resolves, so a validated document reaches here with 'uses' still None.
    uses = spec.uses if spec.uses is not None else name
    template_id, _, named = uses.partition("/")
    template = Job.factory.get(template_id)
    assert template is not None, "checked by _check_uses"
    # TOOLS first, then the document's pin, then the template's defaults. The
    # order is the one the Python flow has: Job.using() returns a copy keeping
    # the same id precisely so a TOOLS entry naming that id still overrides the
    # pin, and a document's 'uses' is that pin written down.
    providers: tuple[str, ...]
    if override is not None:
        providers = (override,)
    elif named:
        providers = (named,)
    else:
        providers = template.default_providers

    steps = []
    provides = set(template.provides)
    metrics = set(template.metrics)
    for provider in providers:
        registration = JobRegistry.get(template_id, provider)
        if registration is None:
            # Not an assertion: validate_against_registry checks the providers
            # the *document* names, and a TOOLS-supplied one has passed nothing.
            raise JobResolutionError(
                f"Job '{name}': no provider named '{provider}' is registered "
                f"for '{template_id}'. Registered providers: "
                f"{JobRegistry.providers(template_id)}."
            )
        steps.extend(registration.steps)
        provides.update(registration.provides)
        metrics.update(registration.metrics)

    return ResolvedJob(
        id=name,
        needs=tuple(spec.needs),
        source=dict(spec.source),
        conditions=conditions,
        requires=tuple(template.requires),
        provides=tuple(sorted(provides, key=str)),
        metrics=tuple(sorted(metrics)),
        steps=tuple(steps),
        provider="+".join(providers),
    )
