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
The no-regression pin for the migration. Each document must resolve to the same
steps, under the same gates, as the Python flow it replaces.
"""

from importlib.resources import files

import pytest

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec, load_flow_spec
from librelane.flows.spec_validation import validate_against_registry

pytestmark = pytest.mark.all


def _document(name: str) -> FlowSpec:
    """
    Loads a shipped document and checks every name it borrows from a registry.

    ``load_flow_spec`` runs the structural checks only;
    ``validate_against_registry`` is the separate registry-backed pass that
    ``Workflow.__init__`` runs. Both are needed here, because ``resolve_jobs``
    asserts rather than raises on a name that does not resolve, so skipping the
    second pass would turn a misspelled step into a bare ``AssertionError``.
    """
    spec = load_flow_spec(str(files("librelane.flows").joinpath(name)))
    validate_against_registry(spec)
    return spec


def _jobs_of_each_step(name: str) -> list[tuple[str, str]]:
    """
    Returns
    -------
    list[tuple[str, str]]
        One ``(job id, implementation id)`` pair per resolved step, in the
        order the document declares its jobs.

    Declaration order is not semantic to the engine, which runs the graph. It
    is used here only to line the document up against the flat list the Python
    flow declares, so that a step appearing in several jobs, as
    ``OpenROAD.STAMidPNR`` does four times, is still attributable to one job.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return [
        (job_id, step.get_implementation_id())
        for job_id in spec.jobs
        for step in jobs[job_id].steps
    ]


def _implementation_ids(name: str) -> list[str]:
    return [implementation for _, implementation in _jobs_of_each_step(name)]


def _gated_pairs(name: str) -> set[tuple[str, str]]:
    """
    Every ``(job id, implementation id)`` the document gates behind an ``if``.

    ``ResolvedJob.conditions`` is a ``tuple[str, ...]``, the ``if`` conjunction
    already split into variable names, so an ungated job carries the empty
    tuple rather than ``None``. Test emptiness, not ``is not None``.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return {
        (job_id, step.get_implementation_id())
        for job_id, job in jobs.items()
        if job.conditions
        for step in job.steps
    }


def _gating_variables(name: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """
    Returns
    -------
    list[tuple[str, str, tuple[str, ...]]]
        One ``(job id, implementation id, condition variables)`` triple per
        resolved step, in document order.

    Stronger than :func:`_gated_pairs`, which says only *which* steps are
    gated: a job gated on the wrong boolean, or on the right two booleans in
    the wrong order, is indistinguishable there and visible here.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return [
        (job_id, step.get_implementation_id(), jobs[job_id].conditions)
        for job_id in spec.jobs
        for step in jobs[job_id].steps
    ]


def _flow_gating_variables(
    name: str,
    flow,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """
    The same list, derived from the Python flow's expanded gating table by
    pairing it with the document's jobs position by position.
    """
    gating = flow._expand_gating_config_vars(
        flow.gating_config_vars, [step.id for step in flow.Steps]
    )
    return [
        (job_id, implementation, tuple(gating.get(step.id, [])))
        for (job_id, implementation), step in zip(_jobs_of_each_step(name), flow.Steps)
    ]


def _flow_gated_pairs(name: str, flow) -> set[tuple[str, str]]:
    """
    The same set, derived from the Python flow, by pairing its flat step list
    with the document's jobs position by position.
    """
    pairs = _jobs_of_each_step(name)
    assert [implementation for _, implementation in pairs] == [
        step.get_implementation_id() for step in flow.Steps
    ], "the document and the flow do not run the same steps in the same order"

    gating = flow._expand_gating_config_vars(
        flow.gating_config_vars, [step.id for step in flow.Steps]
    )
    return {
        (job_id, implementation)
        for (job_id, implementation), step in zip(pairs, flow.Steps)
        if step.id in gating
    }


def test_the_classic_document_declares_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert _implementation_ids("classic.yaml") == [
        step.get_implementation_id() for step in Classic.Steps
    ]


def test_the_classic_document_gates_exactly_what_the_classic_flow_gates():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert _gated_pairs("classic.yaml") == _flow_gated_pairs("classic.yaml", Classic)


def test_the_classic_document_gates_on_the_same_variables_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert _gating_variables("classic.yaml") == _flow_gating_variables(
        "classic.yaml", Classic
    )


def test_the_classic_document_declares_the_classic_flow_s_variables():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    declared = {variable.name for variable in _document("classic.yaml").config}

    # TOOLS is declared by the engine, not by any document.
    assert declared | {"TOOLS"} == {v.name for v in Classic.config_vars}


def test_the_classic_document_omits_the_unimplemented_post_route_opt_job():
    """
    Job.post_route_opt has no default provider and no registered provider, so
    it contributes no step to Classic.Steps and a bare 'uses' naming it is a
    load error. It is the only such template.
    """
    assert "post_route_opt" not in _document("classic.yaml").jobs
