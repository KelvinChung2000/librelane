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
The workflow document checks that need a populated registry.

Kept apart from :mod:`librelane.flows.spec` so the document models stay
testable without importing the step and job packages, whose registries are
process-wide singletons populated by import side effect.
"""

from librelane.common.metrics import Metric
from librelane.config import universal_flow_config_variables
from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec
from librelane.flows.spec_graph import ancestors, descendants
from librelane.jobs import Job, JobRegistry
from librelane.state import DesignFormat
from librelane.steps import Step


def validate_against_registry(spec: FlowSpec) -> None:
    """
    Checks every name a document borrows from a registry.

    Parameters
    ----------
    spec : FlowSpec
        A structurally valid document.

    Raises
    ------
    FlowSpecError
        If a job, provider or step ID does not resolve.
        The message names the legal alternatives.
    """
    for name, job in spec.jobs.items():
        if job.steps is not None:
            _check_steps(name, job.steps)
        else:
            _check_uses(name, _require_implementation(name, job))

    _check_source_keys_resolve(spec)
    views = {name: _produced_views(name, job) for name, job in spec.jobs.items()}
    keys = {name: _produced_keys(name, job) for name, job in spec.jobs.items()}
    _check_sources_can_deliver(spec, keys)
    _check_requirements_are_reachable(spec, views)
    _check_fan_in_is_unambiguous(spec, keys)
    _check_sink_join_is_unambiguous(spec, keys)
    _check_job_values_are_covering(spec)


def _resolved_uses(job_id: str, job: JobSpec) -> str | None:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ``job`` or ``job/provider`` string this job resolves to, or
    ``None`` for an inline ``steps`` job. An omitted ``uses`` resolves to the
    job id, which :func:`_require_implementation` has already confirmed names a
    registered template.
    """
    if job.steps is not None:
        return None
    if job.uses is not None:
        return job.uses
    return job_id


def _require_implementation(job_id: str, job: JobSpec) -> str:
    if job.uses is not None:
        return job.uses
    if Job.factory.get(job_id) is None:
        raise FlowSpecError(
            f"Job '{job_id}' declares neither 'uses' nor 'steps', and its id "
            f"is not a registered job id, so there is nothing to run. "
            f"Add 'uses' to name a registered job and provider, or 'steps' "
            f"to list step IDs inline. Registered job ids: "
            f"{sorted(Job.factory.list())}."
        )
    return job_id


def _check_uses(job: str, uses: str) -> None:
    parts = uses.split("/")
    if len(parts) > 2:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', which is not a job id or "
            f"a 'job/provider' pair."
        )
    job_id = parts[0]
    template = Job.factory.get(job_id)
    if template is None:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', but no job with id "
            f"'{job_id}' is registered. Registered job ids: "
            f"{sorted(Job.factory.list())}."
        )
    if len(parts) == 1:
        if template.default_provider is None:
            raise FlowSpecError(
                f"Job '{job}' declares uses '{uses}', but job '{job_id}' "
                f"has no default provider, so the document must name one. "
                f"Available: {JobRegistry.providers(job_id)}."
            )
        return
    provider = parts[1]
    available = JobRegistry.providers(job_id)
    if provider not in available:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', but no provider "
            f"'{provider}' is registered for job '{job_id}'. Available: "
            f"{available}."
        )


def _check_steps(job: str, steps: list[str]) -> None:
    for step_id in steps:
        if Step.factory.get(step_id) is None:
            raise FlowSpecError(
                f"Job '{job}' lists step '{step_id}', which is not a "
                f"registered step ID."
            )


def _provider_of(uses: str) -> tuple[str, str]:
    job_id, _, provider = uses.partition("/")
    if provider:
        return job_id, provider
    template = Job.factory.get(job_id)
    assert template is not None, "checked by _check_uses"
    # A bare 'uses' means the template's default provider, which _check_uses
    # has already refused to let be absent.
    assert template.default_provider is not None, "checked by _check_uses"
    return job_id, template.default_provider


def _produced_views(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ids of every view this job declares it produces.
    """
    views: set[str] = set()
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            views.update(str(view) for view in step.outputs)
        return views
    job_id, provider = _provider_of(uses)
    template = Job.factory.get(job_id)
    assert template is not None, "checked by _check_uses"
    views.update(str(view) for view in template.provides)
    registration = JobRegistry.get(job_id, provider)
    if registration is not None:
        views.update(str(view) for view in registration.provides)
    return views


def _produced_metrics(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The names of every metric this job declares it produces. An inline
    ``steps`` job declares none, because a step class carries no metric
    declaration. Phase 2's runtime contract check is what covers those.
    """
    uses = _resolved_uses(job_id, job)
    if uses is None:
        return set()
    job_id, provider = _provider_of(uses)
    template = Job.factory.get(job_id)
    assert template is not None, "checked by _check_uses"
    metrics = set(template.metrics)
    registration = JobRegistry.get(job_id, provider)
    if registration is not None:
        metrics.update(registration.metrics)
    return metrics


def _produced_keys(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    Every view id and metric name this job declares, in one set, because the
    join rule and ``source`` treat the two alike.
    """
    return _produced_views(job_id, job) | _produced_metrics(job_id, job)


def _consumed_views(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ids of every view this job requires. An optional input is satisfiable
    by absence, so it is not a requirement and does not appear. Nothing
    declares a consumed metric, so there is no metric equivalent.
    """
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        consumed: list[DesignFormat] = []
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            consumed.extend(step.inputs)
    else:
        template = Job.factory.get(uses.split("/")[0])
        assert template is not None, "checked by _check_uses"
        consumed = list(template.requires)
    # The flag lives on the view, and str() reduces a view to its id, which an
    # optional view shares with its base. So the flag has to be read first, or
    # it is gone by the time the set is built.
    return {str(view) for view in consumed if not view.optional}


def _union(table: dict[str, set[str]], names: set[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        result.update(table[name])
    return result


def _pairs(items: list[str]):
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            yield first, second


def _check_source_keys_resolve(spec: FlowSpec) -> None:
    for name, job in spec.jobs.items():
        for key in job.source:
            if DesignFormat.factory.get(key) is not None:
                continue
            if key in Metric.by_name:
                continue
            raise FlowSpecError(
                f"Job '{name}' sources '{key}', which is neither a registered "
                f"view nor a registered metric. Registered views: "
                f"{sorted(set(DesignFormat.factory.list()))}. Registered "
                f"metrics: {sorted(Metric.by_name)}."
            )


def _check_sources_can_deliver(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        for key, producer in job.source.items():
            # 'producer' is one of this job's needs, checked structurally. Its
            # token carries everything its whole branch produced, so a key it
            # inherited counts, but a key nothing in the branch wrote does not.
            branch = {producer} | ancestors(edges, producer)
            if key in _union(keys, branch):
                continue
            raise FlowSpecError(
                f"Job '{name}' sources '{key}' from '{producer}', but neither "
                f"'{producer}' nor any of its predecessors produces it, so no "
                f"such value ever arrives. '{producer}' and its predecessors "
                f"produce: {sorted(_union(keys, branch))}."
            )


def _check_requirements_are_reachable(
    spec: FlowSpec,
    views: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        predecessors = ancestors(edges, name)
        available = _union(views, predecessors)
        # Views produced somewhere this job could actually have inherited from.
        # Two exclusions, both load-bearing.
        #
        # The job itself, because 14 of the 27 registered templates both
        # require and provide the same views (the PNR_IN_PLACE contract,
        # def/nl/sdc), so counting a job's own output as evidence would reject
        # every one of them whenever no ancestor happens to restate the view.
        #
        # And this job's descendants, because state flows forward only. A
        # downstream PNR_IN_PLACE job providing nl says nothing about whether
        # an upstream job can obtain nl, and counting it rejects every document
        # that starts mid-flow.
        successors = descendants(edges, name)
        elsewhere = _union(
            views,
            {other for other in spec.jobs if other != name and other not in successors},
        )
        for view in sorted(_consumed_views(name, job) - available):
            # A view nothing upstream-eligible produces is presumed to arrive
            # in the initial state, and is checked at run time against the real
            # state.
            if view not in elsewhere:
                continue
            raise FlowSpecError(
                f"Job '{name}' requires view '{view}', which none of its "
                f"predecessors produce. Predecessors: {sorted(predecessors)}."
            )


def _check_fan_in_is_unambiguous(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        if len(job.needs) < 2:
            continue
        branches = {need: ({need} | ancestors(edges, need)) for need in job.needs}
        for first, second in _pairs(job.needs):
            if second in branches[first] or first in branches[second]:
                continue
            shared = branches[first] & branches[second]
            first_keys = _union(keys, branches[first] - shared)
            second_keys = _union(keys, branches[second] - shared)
            for key in sorted(first_keys & second_keys):
                if key in job.source:
                    continue
                raise FlowSpecError(
                    f"Job '{name}' joins '{first}' and '{second}', which both "
                    f"produce '{key}'. Declare which one it comes from with "
                    f"'source: {{{key}: {first}}}' or "
                    f"'source: {{{key}: {second}}}'."
                )


def _steps_of(job_id: str, job: JobSpec) -> list[type[Step]]:
    resolved: list[type[Step]] = []
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            resolved.append(step)
        return resolved
    job_id, provider = _provider_of(uses)
    registration = JobRegistry.get(job_id, provider)
    if registration is not None:
        resolved.extend(registration.steps)
    return resolved


def _reach(spec: FlowSpec) -> dict[str, set[str]]:
    """
    Parameters
    ----------
    spec : FlowSpec
        A document whose names have already resolved.

    Returns
    -------
    Every configuration variable name mapped to the jobs that can read it. A
    universal variable is read by every job, because it sits in every step's
    filtered configuration. Every other variable is read by the jobs whose
    steps declare it.
    """
    reach: dict[str, set[str]] = {}
    for name, job in spec.jobs.items():
        for step in _steps_of(name, job):
            for variable in step.config_vars:
                reach.setdefault(variable.name, set()).add(name)
    for variable in universal_flow_config_variables:
        reach[variable.name] = set(spec.jobs)
    return reach


def _check_job_values_are_covering(spec: FlowSpec) -> None:
    # Keyed by variable rather than by job, because the condition is over the
    # whole document. The jobs setting a variable must be exactly the jobs
    # that read it.
    reach = _reach(spec)
    setters: dict[str, set[str]] = {}
    for name, job in spec.jobs.items():
        for variable_name in job.values:
            setters.setdefault(variable_name, set()).add(name)
    for variable_name, setting in sorted(setters.items()):
        readers = reach.get(variable_name, set())
        uncovered = readers - setting
        if uncovered:
            raise FlowSpecError(
                f"Jobs {sorted(setting)} set '{variable_name}' in their 'with' "
                f"blocks, but jobs {sorted(uncovered)} also read "
                f"'{variable_name}' and do not set it, so those jobs would "
                f"observe a different value with no error anywhere. Every job "
                f"that reads a variable must set it, or none of them may. Set "
                f"it on the document or on the design instead."
            )
        stray = setting - readers
        if stray:
            raise FlowSpecError(
                f"Jobs {sorted(stray)} set '{variable_name}' in their 'with' "
                f"blocks, but no step of those jobs reads '{variable_name}', "
                f"so the value could never take effect. Jobs that read "
                f"'{variable_name}': {sorted(readers)}."
            )


def _check_sink_join_is_unambiguous(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    if spec.final is not None:
        # 'final' names the state to return, so the sinks are not joined.
        return
    edges = spec.edges()
    needed = {need for job in spec.jobs.values() for need in job.needs}
    sinks = [name for name in spec.jobs if name not in needed]
    branches = {sink: ({sink} | ancestors(edges, sink)) for sink in sinks}
    for first, second in _pairs(sinks):
        shared = branches[first] & branches[second]
        first_keys = _union(keys, branches[first] - shared)
        second_keys = _union(keys, branches[second] - shared)
        for key in sorted(first_keys & second_keys):
            raise FlowSpecError(
                f"The final state of flow '{spec.name}' joins leaf jobs "
                f"'{first}' and '{second}', which both produce '{key}'. No "
                f"job's 'source' can resolve this, because the join is not a "
                f"job. Declare the top-level 'final' key naming the job whose "
                f"state the flow returns, for example 'final: {first}'."
            )
