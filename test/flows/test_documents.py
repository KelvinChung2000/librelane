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


def _assert_orders_its_steps_as_the_flow_did(name: str, flow) -> None:
    """
    Asserts that the document runs the flow's steps, and that every pair of
    jobs its graph still orders is ordered the way the Python flow ordered it.

    Walks the graph rather than the document's job map, so that a job the edges
    cannot reach shows up as a missing step rather than passing on the strength
    of having been declared.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    edges = spec.edges()

    reached = [
        (job_id, step.get_implementation_id())
        for job_id in topological_order(edges)
        for step in jobs[job_id].steps
    ]
    assert sorted(reached) == sorted(_jobs_of_each_step(name))
    assert sorted(implementation for _, implementation in reached) == sorted(
        step.get_implementation_id() for step in flow.Steps
    )

    # Where each job's first step sits in the flow's list. Declaration order is
    # the flow's order, which _flow_gated_pairs asserts outright.
    position: dict[str, int] = {}
    for index, (job_id, _) in enumerate(_jobs_of_each_step(name)):
        position.setdefault(job_id, index)

    for job_id, needs in edges.items():
        for need in needs:
            assert position[need] < position[job_id], (
                f"'{job_id}' needs '{need}', which the {flow.__name__} flow ran "
                f"after it"
            )


def _assert_gds_writers_are_ordered(name: str, expected: list[str]) -> None:
    """
    Asserts that ``expected`` is exactly the set of jobs writing the neutral
    ``gds`` view, and that the graph orders every pair of them.

    Written over the resolved steps rather than over the ``needs`` list, so
    that it pins the property and not the edge: it fails if an ordering edge
    between two writers is dropped, and it also fails if some later change adds
    a writer of ``gds`` on a parallel branch.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    edges = spec.edges()

    producers = sorted(
        job_id
        for job_id, job in jobs.items()
        if any("gds" in {str(view) for view in step.outputs} for step in job.steps)
    )
    # Pinned exactly, because a new writer of 'gds' is a change that has to come
    # back through this reasoning rather than past it.
    assert producers == sorted(expected)

    for first, second in itertools.combinations(producers, 2):
        assert first in ancestors(edges, second) or second in ancestors(edges, first), (
            f"'{first}' and '{second}' both write 'gds' and the graph leaves "
            f"them concurrent, so the PDK's primary tool no longer decides "
            f"which one the later consumers read"
        )


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

    _assert_orders_its_steps_as_the_flow_did(
        "classic.yaml", Flow.factory.get("Classic")
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
    _assert_gds_writers_are_ordered(
        "classic.yaml", ["klayout_streamout", "magic_streamout"]
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


#: Every document shipped so far, paired with the flow class it replaces. The
#: five Open-In flows are single-job documents; the three place-and-route flows
#: carry a config block and a gating table, so the tests below that need one
#: take a narrower list.
_DOCUMENTS = [
    ("classic.yaml", "Classic"),
    ("vhdl_classic.yaml", "VHDLClassic"),
    ("chip.yaml", "Chip"),
    ("open_in_klayout.yaml", "OpenInKLayout"),
    ("open_in_openroad.yaml", "OpenInOpenROAD"),
    ("open_in_openroad_console.yaml", "OpenInOpenROADConsole"),
    ("open_in_opensta_console.yaml", "OpenInOpenSTAConsole"),
    ("open_in_magic.yaml", "OpenInMagic"),
]

_CONFIGURED_DOCUMENTS = [
    ("classic.yaml", "Classic"),
    ("vhdl_classic.yaml", "VHDLClassic"),
    ("chip.yaml", "Chip"),
]


@pytest.mark.parametrize(("document", "flow_name"), _DOCUMENTS)
def test_each_document_runs_the_same_steps_as_the_flow_it_replaces(document, flow_name):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert sorted(_implementation_ids(document)) == sorted(
        step.get_implementation_id() for step in flow.Steps
    )


@pytest.mark.parametrize(("document", "flow_name"), _CONFIGURED_DOCUMENTS)
def test_each_document_gates_exactly_what_the_flow_it_replaces_gates(
    document, flow_name
):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert _gated_pairs(document) == _flow_gated_pairs(document, flow)


@pytest.mark.parametrize(("document", "flow_name"), _CONFIGURED_DOCUMENTS)
def test_each_document_gates_on_the_same_variables_as_the_flow_it_replaces(
    document, flow_name
):
    """
    Stronger than the pair test above, which says only *which* steps are gated:
    a job gated on the wrong boolean, or on the right two in the wrong order, is
    indistinguishable there and visible here.
    """
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert _gating_variables(document) == _flow_gating_variables(document, flow)


@pytest.mark.parametrize(("document", "flow_name"), _CONFIGURED_DOCUMENTS)
def test_each_document_declares_the_flow_s_variables(document, flow_name):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)
    declared = {variable.name for variable in _document(document).config}

    # TOOLS is declared by the engine, not by any document.
    assert declared | {"TOOLS"} == {v.name for v in flow.config_vars}


@pytest.mark.parametrize(
    ("document", "flow_name"),
    [("vhdl_classic.yaml", "VHDLClassic"), ("chip.yaml", "Chip")],
)
def test_each_document_orders_its_steps_as_the_flow_it_replaces_did(
    document, flow_name
):
    """
    The same relaxation the Classic document made, held to the same standard:
    the graph no longer claims the flow's exact sequence, but every pair of jobs
    it *still* orders is ordered the way the Python flow ordered it.
    """
    from librelane.flows import Flow

    _assert_orders_its_steps_as_the_flow_did(document, Flow.factory.get(flow_name))


@pytest.mark.parametrize(
    ("document", "flow_name"),
    [
        ("open_in_klayout.yaml", "OpenInKLayout"),
        ("open_in_openroad.yaml", "OpenInOpenROAD"),
        ("open_in_openroad_console.yaml", "OpenInOpenROADConsole"),
        ("open_in_opensta_console.yaml", "OpenInOpenSTAConsole"),
        ("open_in_magic.yaml", "OpenInMagic"),
    ],
)
def test_each_open_in_document_registers_under_its_class_name(document, flow_name):
    """
    ``SequentialFlow.name`` on these five carries a display string such as
    "Opening in KLayout", but the registration key, and so the string a user
    types after ``--flow``, is the class name. A document's ``name`` is the
    registration key, so it has to survive the migration character for
    character; the display string becomes ``description``.
    """
    spec = _document(document)

    assert spec.name == flow_name
    assert spec.description != ""


@pytest.mark.parametrize(
    ("document", "job_id"),
    [
        ("open_in_klayout.yaml", "open_gui"),
        ("open_in_openroad.yaml", "open_gui"),
        ("open_in_openroad_console.yaml", "open_console"),
        ("open_in_opensta_console.yaml", "open_console"),
        ("open_in_magic.yaml", "open_gui"),
    ],
)
def test_each_open_in_document_names_its_one_job_for_what_it_opens(document, job_id):
    """
    A job id becomes a run directory name, so the two console flows say
    ``open_console`` rather than ``open_gui``: a job id that lies about what it
    runs is a run directory that lies about it too.
    """
    jobs = _document(document).jobs

    assert list(jobs) == [job_id]
    assert jobs[job_id].needs == []


def test_vhdl_classic_pins_the_vhdl_synthesis_provider():
    """
    ``VHDLClassic.Stages`` writes ``Job.synthesis.using("yosys_vhdl")`` where
    ``Classic.Stages`` writes a bare ``Job.synthesis``. Each is mirrored
    faithfully; the bare form in ``classic.yaml`` is not an oversight.
    """
    assert _document("vhdl_classic.yaml").jobs["synthesis"].uses == (
        "synthesis/yosys_vhdl"
    )


def test_vhdl_classic_omits_the_four_jobs_it_cannot_run():
    """
    classic.py's note above ``VHDLClassic.Stages`` names them: the lint stage,
    Odb.SetPowerConnections, Odb.WriteVerilogHeader and the formal equivalence
    stage. Checker.PowerGridViolations is NOT among them and must survive; it
    sat with Odb.WriteVerilogHeader in Classic, so it gets a job of its own.
    """
    jobs = _document("vhdl_classic.yaml").jobs

    assert "lint" not in jobs
    assert "set_power_connections" not in jobs
    assert "write_verilog_header" not in jobs
    assert "formal_equivalence" not in jobs
    assert jobs["power_grid_check"].steps == ["Checker.PowerGridViolations"]


def test_vhdl_classic_still_declares_the_variables_its_jobs_no_longer_read():
    """
    RUN_LINTER and RUN_EQY are inherited from ``Classic.Config`` today, so a
    configuration setting either one is accepted by VHDLClassic today and must
    stay accepted. Dropping them would turn an accepted key into an unknown-key
    error.
    """
    declared = {variable.name for variable in _document("vhdl_classic.yaml").config}

    assert {"RUN_LINTER", "RUN_EQY"} <= declared


def test_vhdl_classic_runs_the_rmp_job_straight_off_the_floorplan():
    """
    With Odb.SetPowerConnections gone, macro placement follows RMP directly.
    """
    edges = _document("vhdl_classic.yaml").edges()

    assert edges["rmp"] == ["floorplan"]
    assert edges["macro_placement"] == ["rmp"]


def test_vhdl_classic_final_checks_waits_for_the_lvs_job():
    """
    Classic reaches lvs through formal_equivalence. VHDLClassic has no formal
    equivalence job, so lvs would be a second sink and its metrics would never
    reach Misc.ReportManufacturability.
    """
    edges = _document("vhdl_classic.yaml").edges()

    needed = {need for needs in edges.values() for need in needs}
    assert set(edges) - needed == {"final_checks"}
    assert "lvs" in edges["final_checks"]


@pytest.mark.parametrize(
    ("document", "producers"),
    [
        ("vhdl_classic.yaml", ["klayout_streamout", "magic_streamout"]),
        (
            "chip.yaml",
            ["chip_finishing", "klayout_streamout", "magic_streamout"],
        ),
    ],
)
def test_no_two_jobs_of_these_documents_write_the_gds_concurrently(document, producers):
    """
    The same argument ``classic.yaml`` records: neither stream-out writes the
    neutral ``gds`` unconditionally, each writes it if its own tool is
    ``PRIMARY_GDSII_STREAMOUT_TOOL`` *or* if nothing has written one yet, and
    only keeping them ordered reproduces "the primary tool owns ``gds``" for
    both settings.

    Chip has a third writer. KLayout.SealRing and KLayout.Filler both consume
    and produce ``gds`` inside ``chip_finishing``, which descends from both
    stream-outs, so it is unambiguously the last writer rather than a
    competitor.
    """
    _assert_gds_writers_are_ordered(document, producers)


@pytest.mark.parametrize("document", ["vhdl_classic.yaml", "chip.yaml"])
def test_no_job_of_these_documents_needs_a_source(document):
    """
    The consequence of the ordering above. With every ``gds`` writer in series,
    neither document has a join whose branches write the same view or metric, so
    nothing has to be tie-broken.
    """
    jobs = _document(document).jobs

    assert {name: job.source for name, job in jobs.items() if job.source} == {}


def test_chip_reads_the_sealed_and_filled_gds_for_signoff():
    """
    KLayout.SealRing and KLayout.Filler both consume and rewrite ``gds``, and
    they run before DRC and LVS today, so those read the finished layout rather
    than the raw stream-out.

    Asserted as reachability rather than as a ``source`` entry. ``source``
    tie-breaks a fan-in, and there is none here: ``chip_finishing`` descends
    from both stream-outs and is the sole predecessor of all three signoff
    jobs, so the only ``gds`` that can arrive at them is its own.
    """
    spec = _document("chip.yaml")
    edges = spec.edges()

    for job in ["magic_drc", "klayout_drc", "lvs"]:
        assert edges[job] == ["chip_finishing"], job

    assert {"magic_streamout", "klayout_streamout"} <= ancestors(
        edges, "chip_finishing"
    )


def test_chip_runs_its_xor_against_the_unfinished_stream_outs():
    """
    KLayout.XOR consumes 'mag_gds' and 'klayout_gds', which the seal ring and
    filler neither read nor write, and it ran before them in ``Chip.Stages``.
    So the XOR branch and the finishing branch are genuinely independent, and
    the document leaves them so.
    """
    edges = _document("chip.yaml").edges()

    assert edges["xor"] == ["klayout_streamout"]
    assert edges["chip_finishing"] == ["klayout_streamout"]
    assert "xor" not in ancestors(edges, "chip_finishing")
    assert "chip_finishing" not in ancestors(edges, "xor")


def test_chip_omits_the_three_entries_a_chip_does_not_need():
    """
    Magic.WriteLEF and Odb.CheckDesignAntennaProperties, which a chip does not
    need because it is not a macro, and Job.io_placement, whose pins are the pad
    ring's bumps.
    """
    jobs = _document("chip.yaml").jobs

    assert "write_lef" not in jobs
    assert "check_antenna_properties" not in jobs
    assert "io_placement" not in jobs
    assert jobs["placement_seed"].steps == [
        "OpenROAD.GlobalPlacementSkipIO",
        "Odb.ApplyDEFTemplate",
    ]


def test_chip_declares_run_rmp_without_running_rmp():
    """
    ``Chip`` inherits ``Classic.Config``, so RUN_RMP and RUN_MAGIC_WRITE_LEF are
    accepted configuration keys today, but ``Chip`` declares its own ``Stages``
    with neither OpenROAD.RMP nor OpenROAD.AddBuffer in it. The variables stay
    declared so an existing configuration keeps loading; the jobs stay absent so
    the document runs what the flow runs.
    """
    spec = _document("chip.yaml")
    declared = {variable.name for variable in spec.config}

    assert {"RUN_RMP", "RUN_MAGIC_WRITE_LEF"} <= declared
    assert "rmp" not in spec.jobs
    assert "add_buffer" not in spec.jobs


def test_chip_finishing_is_ungated():
    """
    All six of its steps are ungated in ``Chip.gating_config_vars``, so the job
    carries no ``if``. Pinned separately from the gating comparison because that
    test compares job-to-step attributions, and an ``if`` wrongly added here
    would also need a variable to hang it on.
    """
    assert _document("chip.yaml").jobs["chip_finishing"].condition is None
