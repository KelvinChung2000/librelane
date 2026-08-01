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

from dataclasses import dataclass

from librelane.flows.spec import FlowSpec, JobSpec, parse_condition
from librelane.stages import Stage, StageRegistry
from librelane.state import DesignFormat
from librelane.steps import Step


@dataclass(frozen=True)
class Job:
    """
    A resolved job, a document's declaration bound to a registered template.

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


def resolve_jobs(spec: FlowSpec) -> dict[str, Job]:
    """
    Parameters
    ----------
    spec : FlowSpec
        A document that has passed ``validate_against_registry``.

    Returns
    -------
    Each job id mapped to its resolved :class:`Job`, in document
    order.
    """
    return {name: _resolve(name, job) for name, job in spec.jobs.items()}


def _resolve(name: str, spec: JobSpec) -> Job:
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
        return Job(
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
    # does not reject the "neither" case -- the template ids live in the stage
    # registry, which the model layer does not import -- and
    # spec_validation._require_implementation admits it whenever the id
    # resolves, so a validated document reaches here with 'uses' still None.
    uses = spec.uses if spec.uses is not None else name
    stage_id, _, named = uses.partition("/")
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    providers = (named,) if named else stage.default_providers

    steps = []
    provides = set(stage.provides)
    metrics = set(stage.metrics)
    for provider in providers:
        registration = StageRegistry.get(stage_id, provider)
        assert registration is not None, "checked by _check_uses"
        steps.extend(registration.steps)
        provides.update(registration.provides)
        metrics.update(registration.metrics)

    return Job(
        id=name,
        needs=tuple(spec.needs),
        source=dict(spec.source),
        conditions=conditions,
        requires=tuple(stage.requires),
        provides=tuple(sorted(provides, key=str)),
        metrics=tuple(sorted(metrics)),
        steps=tuple(steps),
        provider="+".join(providers),
    )
