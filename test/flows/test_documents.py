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

import itertools
from importlib.resources import files

import pytest

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec, load_flow_spec
from librelane.flows.spec_graph import ancestors, topological_order
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


def test_the_classic_document_runs_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert sorted(_implementation_ids("classic.yaml")) == sorted(
        step.get_implementation_id() for step in Classic.Steps
    )


def test_the_classic_document_orders_its_steps_as_the_classic_flow_did():
    """
    The document is a graph, so it no longer claims the flow's exact sequence:
    six signoff branches leave the last stream-out together and the flow's list
    had to put them in some arbitrary order. What survives the relaxation, and
    is what the migration actually owes, is the weaker claim: every pair of
    jobs the graph *still* orders is ordered the way the Python flow ordered
    it. A 'needs' edge pointing backwards through ``Classic.Steps`` fails here.
    Two jobs the graph leaves independent are free, which is the whole point.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)
    edges = spec.edges()

    # Walking the graph rather than the document's job map, so that a job the
    # edges cannot reach would show up as a missing step rather than pass on
    # the strength of having been declared.
    reached = [
        (job_id, step.get_implementation_id())
        for job_id in topological_order(edges)
        for step in jobs[job_id].steps
    ]
    assert sorted(reached) == sorted(_jobs_of_each_step("classic.yaml"))
    assert sorted(implementation for _, implementation in reached) == sorted(
        step.get_implementation_id() for step in Classic.Steps
    )

    # Where each job's first step sits in the flow's list. Declaration order is
    # the flow's order, which _flow_gated_pairs asserts outright.
    position: dict[str, int] = {}
    for index, (job_id, _) in enumerate(_jobs_of_each_step("classic.yaml")):
        position.setdefault(job_id, index)

    for job_id, needs in edges.items():
        for need in needs:
            assert position[need] < position[job_id], (
                f"'{job_id}' needs '{need}', which the Classic flow ran after it"
            )


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


def test_no_two_classic_jobs_write_the_gds_concurrently():
    """
    The one edge in the signoff tail that is deliberately not relaxed, and the
    reason is ``PRIMARY_GDSII_STREAMOUT_TOOL``.

    Neither stream-out writes the neutral ``gds`` view unconditionally. Each
    writes it if its own tool is the PDK's primary one, *or* if nothing has
    written one yet. Ordered, that reproduces "the primary tool owns ``gds``"
    for both settings and asks the graph to know nothing: with
    ``PRIMARY=magic`` Magic writes it and KLayout declines to clobber it, and
    with ``PRIMARY=klayout`` Magic writes it because nothing has and KLayout
    then overwrites it. Either way the winner is the PDK's primary tool.

    Concurrent, both stream-outs would see an incoming state with no ``gds``,
    both would take that second arm and write one, and the join would have to
    choose. ``JobSpec.source`` maps a view to a *job name*, so no static entry
    can say "whichever job ``PRIMARY_GDSII_STREAMOUT_TOOL`` names", and either
    choice silently changes what Magic.WriteLEF, KLayout.Render, Magic.DRC,
    KLayout.DRC and Magic.SpiceExtraction read on half the PDKs. That is a
    limit of the mechanism, not something this document can work around.

    Written over the resolved steps rather than over the ``needs`` list, so
    that it pins the property and not the edge: it fails if
    ``klayout_streamout`` loses ``needs: [magic_streamout]``, and it also fails
    if some later change adds a third writer of ``gds`` on a parallel branch.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)
    edges = spec.edges()

    producers = sorted(
        job_id
        for job_id, job in jobs.items()
        if any("gds" in {str(view) for view in step.outputs} for step in job.steps)
    )
    # Pinned exactly, because a new writer of 'gds' anywhere in Classic is a
    # change that has to come back through this reasoning rather than past it.
    assert producers == ["klayout_streamout", "magic_streamout"]

    for first, second in itertools.combinations(producers, 2):
        assert first in ancestors(edges, second) or second in ancestors(edges, first), (
            f"'{first}' and '{second}' both write 'gds' and the graph leaves "
            f"them concurrent, so the PDK's primary tool no longer decides "
            f"which one the later consumers read"
        )


def test_no_classic_job_needs_a_source():
    """
    The consequence of the ordering above. Keeping the two ``gds`` producers in
    series leaves the document with no join whose branches write the same view
    or metric, so nothing has to be tie-broken. A ``source`` appearing here
    means a fan-in was introduced whose semantics this test's sibling argues
    cannot be expressed.
    """
    jobs = _document("classic.yaml").jobs

    assert {name: job.source for name, job in jobs.items() if job.source} == {}


def test_classic_s_signoff_checks_fan_out_from_the_last_streamout():
    edges = _document("classic.yaml").edges()

    for job in ["render", "write_lef", "xor", "magic_drc", "klayout_drc", "lvs"]:
        assert edges[job] == ["klayout_streamout"], job


def test_classic_s_signoff_checks_are_independent_of_each_other():
    edges = _document("classic.yaml").edges()

    assert "klayout_drc" not in ancestors(edges, "magic_drc")
    assert "magic_drc" not in ancestors(edges, "klayout_drc")
    assert "magic_drc" not in ancestors(edges, "lvs")
    assert "xor" not in ancestors(edges, "magic_drc")


def test_classic_s_antenna_property_check_waits_for_the_lef_writer():
    """
    The one data edge in the signoff tail that is not a stream-out edge.
    Odb.CheckDesignAntennaProperties consumes 'lef', and Magic.WriteLEF is the
    only step in Classic that produces one.
    """
    edges = _document("classic.yaml").edges()

    assert edges["check_antenna_properties"] == ["write_lef"]


def test_classic_s_final_checks_is_the_only_sink():
    edges = _document("classic.yaml").edges()

    needed = {need for needs in edges.values() for need in needs}
    assert set(edges) - needed == {"final_checks"}


def test_classic_s_final_checks_waits_for_every_metric_it_reports():
    """
    Misc.ReportManufacturability reads LVS, DRC and antenna metrics out of
    state_in.metrics and warns for each one it cannot find, so final_checks has
    to descend from every job that produces them.

    Written against ancestry rather than direct edges, because signoff_sta and
    lvs reach final_checks through the stream-outs and formal_equivalence
    respectively.
    """
    edges = _document("classic.yaml").edges()

    assert {
        "signoff_sta",
        "xor",
        "magic_drc",
        "klayout_drc",
        "lvs",
        "check_antenna_properties",
    } <= ancestors(edges, "final_checks")
