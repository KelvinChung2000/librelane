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
The shipped workflow documents' own test file.

Until phase 5 this pinned each document against the Python flow it replaced.
Those flows are gone, so what is pinned here now is the documents themselves:
that each one resolves, that its graph orders and gates what it claims to, and
that the registry answers for every document the package ships.
"""

import itertools
from importlib.resources import files

import pytest

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.steps.odb.base import OdbpyStep
from librelane.steps.openroad.base import OpenROADStep

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec, load_flow_spec
from librelane.flows.spec_graph import ancestors, topological_order
from librelane.flows.spec_validation import validate_against_registry
from librelane.jobs import JobRegistry

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


def _shipped_documents() -> list[str]:
    """
    Every ``.yaml`` document shipped inside :mod:`librelane.flows`, discovered.

    Deliberately not a hand-written list. The framework-metric guard below was
    added for ``classic.yaml`` and extended to two more by name, and in the gap
    ``vhdl_classic.yaml`` shipped carrying the very defect the guard exists to
    catch -- it was found by hand, not by the suite. A list someone has to
    remember to extend is the same defect one level up, so the parametrisation
    reads the package instead.
    """
    return sorted(
        path.name
        for path in files("librelane.flows").iterdir()
        if path.name.endswith(".yaml")
    )


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


#: The metrics every OpenROAD invocation writes and nothing declares.
#:
#: ``OpenROADStep.get_command`` and ``OdbpyStep.get_command`` both pass an
#: unconditional ``-metrics``, and OpenROAD's logger fills these in. No step,
#: job template or registration mentions them -- ``grep`` across ``librelane``
#: finds nothing -- so every load-time check reasons from contracts that cannot
#: see them, and :mod:`librelane.flows.join` is what discovers the disagreement,
#: on the first real run, after the tools have been invoked. Modelled here as
#: implicit outputs, which is where the special case belongs.
_FRAMEWORK_METRICS = (
    "flow__warnings__count",
    "flow__errors__count",
    "flow__warnings__type_count",
)


def _produced_by(name: str, tools: dict[str, str] | None = None) -> dict[str, set[str]]:
    """
    Every key each job writes, under the provider selection ``tools`` names.

    Three sources, because no one of them is complete:

    * the job's declared contract, which for a ``uses:`` job is its template's
      ``provides`` and ``metrics`` unioned with its selected registration's;
    * **every step's own ``outputs``**, which the contract does not cover. For
      a ``uses:`` job the contract reads the *template*, so 19 of the
      ~46 jobs in each shipped document write views it cannot see -- ``odb``
      and ``pnl`` across the PNR chain, ``sdf`` and ``lib`` from the STA jobs,
      ``mag`` from ``magic_streamout``, ``spice`` from ``lvs``. Declaring less
      than you write is allowed (``Step.outputs`` is a permission, not an
      obligation), so the contract is a floor;
    * the framework metrics, if any step is OpenROAD-backed.

    Modelling only the first would make this guard a subset of the rule it
    exists to enforce -- which is the mistake that produced two of this
    phase's defects. The union is measured to change no verdict today; it is
    here so that it still holds when a later document is not so lucky.

    Read off :func:`librelane.flows.job.resolve_jobs` rather than off the
    document, so that every key it reports is a key the *selected* provider
    writes. ``TOOLS`` is what makes the distinction load-bearing: the ``lvs``
    job's ``klayout`` provider opens with ``OpenROAD.WriteCDL``, so a selection
    naming it puts framework metrics on a branch that carries none by default.
    A guard reading the document's declared providers would never see it.

    The metric half stays incomplete and cannot be fixed here: steps carry no
    metric declaration at all, so an inline ``steps:`` job is modelled as
    writing none. ``librelane.flows.spec_validation``'s own
    ``_check_fan_in_is_unambiguous`` shares that blind spot.
    """
    produced = {}
    for job_id, job in resolve_jobs(_document(name), tools).items():
        keys = {str(view) for view in job.provides} | set(job.metrics)
        for step in job.steps:
            keys.update(view.id for view in step.outputs)
        if any(issubclass(step, (OpenROADStep, OdbpyStep)) for step in job.steps):
            keys.update(_FRAMEWORK_METRICS)
        produced[job_id] = keys
    return produced


def _join_conflicts(
    name: str, tools: dict[str, str] | None = None
) -> list[tuple[str, str, list[str]]]:
    """
    Replays :mod:`librelane.flows.join`'s rule symbolically over a document.

    Returns
    -------
    list[tuple[str, str, list[str]]]
        One ``(consumer, key, origins)`` triple per unresolved conflict.

    The rule this checks is the general one, of which "no OpenROAD-backed job
    has a concurrent peer" is only a proper subset:

        No job may rewrite a view or metric that a concurrent peer inherits
        from their common ancestor.

    ``join.py`` compares *values*, not declarations, so what matters per key is
    which job last wrote it on each incoming branch. This walks
    ``topological_order`` carrying exactly that -- a ``key -> writing job`` map
    per token -- and flags any job whose predecessors disagree, plus the
    implicit join that forms the final state.

    Written as a replay rather than as a structural rule because
    ``_check_fan_in_is_unambiguous`` is the structural rule and this is the
    class of defect it cannot see: it subtracts the shared ancestors before
    intersecting, so a key produced in the shared prefix and *re-produced* on
    exactly one exclusive branch gives an empty intersection and passes.

    Every job is modelled as enabled. A gated-off job passes ``state_in``
    through unchanged (``engine.py``), which changes which job an origin names
    but cannot introduce a disagreement that the all-enabled graph does not
    already have somewhere; the all-enabled graph is also the shipped default.
    """
    spec = _document(name)
    edges = spec.edges()
    produced = _produced_by(name, tools)

    conflicts: list[tuple[str, str, list[str]]] = []
    carried: dict[str, dict[str, str]] = {}

    def merge(
        consumer: str, branches: list[str], source: dict[str, str]
    ) -> dict[str, str]:
        incoming: dict[str, list[tuple[str, str]]] = {}
        for branch in branches:
            for key, origin in carried[branch].items():
                incoming.setdefault(key, []).append((branch, origin))

        merged: dict[str, str] = {}
        for key, contributors in sorted(incoming.items()):
            origins = {origin for _, origin in contributors}
            if len(origins) == 1:
                merged[key] = next(iter(origins))
                continue
            # A 'source' settles it only by naming a predecessor that actually
            # contributed, which is what join.py's resolver requires.
            chosen = [
                origin for branch, origin in contributors if branch == source.get(key)
            ]
            if not chosen:
                conflicts.append((consumer, key, sorted(origins)))
            merged[key] = chosen[0] if chosen else sorted(origins)[0]
        return merged

    for job_id in topological_order(edges):
        job = spec.jobs[job_id]
        state = merge(job_id, list(job.needs), job.source)
        for key in produced[job_id]:
            state[key] = job_id
        carried[job_id] = state

    if spec.final is None:
        needed = {need for job in spec.jobs.values() for need in job.needs}
        sinks = [job_id for job_id in spec.jobs if job_id not in needed]
        # No job's 'source' can settle a sink conflict, so an empty mapping is
        # not a simplification here: join_sink_states has none to read.
        merge("<the final state>", sinks, {})

    return conflicts


def _alternate_providers(name: str) -> list[tuple[str, str]]:
    """
    Returns
    -------
    list[tuple[str, str]]
        One ``(job id, provider)`` pair per ``TOOLS`` entry that would change
        something: every registered provider of every ``uses`` job's stage,
        other than the one the document already resolves to.

    Derived from the registries rather than written down, so a provider
    registered later is covered without anyone remembering to name it. An
    inline ``steps`` job is excluded because ``TOOLS`` rejects it outright.
    """
    spec = _document(name)
    resolved = resolve_jobs(spec)
    alternates = []
    for job_id, job in spec.jobs.items():
        if job.steps is not None:
            continue
        uses = job.uses if job.uses is not None else job_id
        template_id = uses.partition("/")[0]
        for provider in JobRegistry.providers(template_id):
            if provider != resolved[job_id].provider:
                alternates.append((job_id, provider))
    return alternates


#: The single-key ``TOOLS`` selections a shipped document does not survive,
#: measured with :func:`_join_conflicts` rather than predicted, mapped to the
#: keys each one collides on.
#:
#: Every entry is a property of the *document*, not of ``TOOLS``: the selection
#: puts a second writer of some key onto one of two concurrent branches, and
#: ``join_states`` has no way to choose between them. Two shapes appear.
#:
#: Re-pointing one ``drc`` job at the other's tool makes both jobs run the same
#: deck and write the same metric, concurrently. A configuration migrated from
#: the old stage-keyed ``TOOLS`` is the likely way to write one by accident:
#: ``{"drc": "klayout"}`` does not become ``{"magic_drc": "klayout"}``, it
#: becomes ``RUN_MAGIC_DRC: false``, because the two jobs are what the two
#: booleans gate.
#:
#: Selecting the ``klayout`` provider of ``lvs`` opens that job with
#: ``OpenROAD.WriteCDL``, whose framework metrics its concurrent peers inherit
#: unchanged from the last OpenROAD-backed job above the fan-out. Neither
#: ``librelane.flows.spec_validation`` nor this guard's pre-selection form
#: could see it: the metrics are declared nowhere, and the provider is named
#: nowhere in the document.
#:
#: Pinned rather than left to be discovered on a real run, and pinned as an
#: equality so that a selection becoming safe fails here too. Nothing in the
#: engine rejects these at load time; that check does not exist yet.
_SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE = {
    ("chip.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("chip.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("chip.yaml", "lvs", "klayout"): list(sorted(_FRAMEWORK_METRICS)),
    ("classic.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("classic.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("classic.yaml", "lvs", "klayout"): list(sorted(_FRAMEWORK_METRICS)),
    ("vhdl_classic.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("vhdl_classic.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("vhdl_classic.yaml", "lvs", "klayout"): list(sorted(_FRAMEWORK_METRICS)),
}


def _assert_no_join_conflicts(name: str) -> None:
    conflicts = _join_conflicts(name)
    assert not conflicts, "\n".join(
        f"'{consumer}' joins branches that wrote '{key}' from different jobs "
        f"{origins}, so join_states raises JoinConflictError on the first real "
        f"run. Every branch of a fan-out must descend from the last job that "
        f"writes each key the branches share."
        for consumer, key, origins in conflicts
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


#: The eight documents that replaced the eight Python flow classes, written out
#: rather than discovered, so that a document *disappearing* fails here too.
#: :func:`test_the_document_list_names_every_shipped_document` is what stops the
#: literal going stale in the other direction.
_SHIPPED_DOCUMENTS = [
    "classic.yaml",
    "vhdl_classic.yaml",
    "chip.yaml",
    "open_in_klayout.yaml",
    "open_in_openroad.yaml",
    "open_in_openroad_console.yaml",
    "open_in_opensta_console.yaml",
    "open_in_magic.yaml",
]


@pytest.mark.parametrize("document", _SHIPPED_DOCUMENTS)
def test_every_shipped_document_resolves(document):
    """
    What is left of the comparison tests this file used to carry, now that
    there is no Python flow to compare against: every shipped document loads,
    validates against the registries, and resolves to jobs that all have steps.

    Deliberately weaker than what it replaces. With one mechanism, the thing
    worth pinning is that the document is valid, not that it matches something
    that no longer exists.
    """
    spec = _document(document)
    jobs = resolve_jobs(spec)

    assert jobs
    assert all(job.steps for job in jobs.values())


def test_the_document_list_names_every_shipped_document():
    """
    A literal cannot fail for a document nobody remembered to add to it, which
    is exactly the hole that left two Open-In flows without documents until
    phase 4. Until phase 5 the derived guard against that was
    ``test_every_registered_flow_class_has_a_document_standing_in_for_it``,
    which compared the class registry against the document registry; with no
    flow classes left there is nothing to compare against, so what is derived
    here instead is the package's own contents.
    """
    assert set(_SHIPPED_DOCUMENTS) == set(_shipped_documents())


def test_classic_declares_the_jobs_it_is_known_for():
    jobs = _document("classic.yaml").jobs

    for name in [
        "synthesis",
        "floorplan",
        "cts",
        "detailed_routing",
        "magic_streamout",
        "klayout_streamout",
        "magic_drc",
        "lvs",
        "signoff_sta",
    ]:
        assert name in jobs


def test_the_console_documents_run_the_console_steps():
    """
    Issue 532: the interactive sessions are reachable the same way the GUI ones
    are, i.e. `librelane --last-run --flow ...`. Read off the resolved
    documents; until phase 5 this was read off ``OpenInOpenROADConsole.Steps``
    and ``OpenInOpenSTAConsole.Steps`` in ``test/flows/test_flow.py``.
    """
    assert _implementation_ids("open_in_openroad_console.yaml") == [
        "OpenROAD.OpenConsole"
    ]
    assert _implementation_ids("open_in_opensta_console.yaml") == [
        "OpenROAD.OpenSTAConsole"
    ]


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


def test_no_classic_gds_consumer_needs_a_source():
    """
    Narrower than a global "no job has a ``source``", deliberately. That claim
    reached past what a declared-contract argument can establish -- the
    framework's undeclared ``flow__*`` metrics are a counterexample it could
    not have detected -- so it is made only where the analysis backs it: the
    six consumers of ``gds``, whose producers this file proves are ordered.
    """
    jobs = _document("classic.yaml").jobs

    for job in ["render", "write_lef", "xor", "magic_drc", "klayout_drc", "lvs"]:
        assert jobs[job].source == {}, job


def test_classic_s_signoff_checks_fan_out_from_the_last_openroad_job():
    """
    The fan-out point is ``check_antenna_properties``, the last OpenROAD-backed
    job, rather than the last stream-out. ``render`` and ``write_lef`` sit
    between the two on the chain, in flow order, and are cheap.
    """
    edges = _document("classic.yaml").edges()

    assert edges["render"] == ["klayout_streamout"]
    assert edges["write_lef"] == ["render"]
    for job in ["xor", "magic_drc", "klayout_drc", "lvs"]:
        assert edges[job] == ["check_antenna_properties"], job


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


@pytest.mark.parametrize(
    ("document", "registered_name"),
    [
        ("open_in_klayout.yaml", "OpenInKLayout"),
        ("open_in_openroad.yaml", "OpenInOpenROAD"),
        ("open_in_openroad_console.yaml", "OpenInOpenROADConsole"),
        ("open_in_opensta_console.yaml", "OpenInOpenSTAConsole"),
        ("open_in_magic.yaml", "OpenInMagic"),
    ],
)
def test_each_open_in_document_registers_under_the_name_users_type(
    document, registered_name
):
    """
    The five Open-In flows used to be Python flow classes whose ``name``
    carried a display string such as "Opening in KLayout", while the
    registration key -- the string a user types after ``--flow`` -- was the
    class name. A document's ``name`` is the registration key, so these had to
    survive the migration character for character; the display string became
    ``description``.
    """
    spec = _document(document)

    assert spec.name == registered_name
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
    The ``VHDLClassic`` class named them: the lint stage,
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
    ``VHDLClassic`` inherited RUN_LINTER and RUN_EQY from ``Classic.Config``, so
    a configuration setting either one was accepted and must stay accepted.
    Dropping them would turn an accepted key into an unknown-key error.
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
    filler neither read nor write. So the XOR compares the two raw stream-outs,
    exactly as it did in ``Chip.Stages``, where it ran before the six finishing
    steps.

    ``xor`` nonetheless runs *in series* before ``chip_finishing`` rather than
    beside it. The edge is an ordering edge, not a data edge: no view XOR reads
    comes from ``chip_finishing``. It exists because ``chip_finishing``
    rewrites 'gds' while ``render`` and ``xor`` carry the stream-out's, and
    concurrent branches holding two 'gds' values make ``join_states`` raise.
    An earlier revision of this document left them concurrent and did raise.
    """
    spec = _document("chip.yaml")
    edges = spec.edges()
    jobs = resolve_jobs(spec)

    assert edges["xor"] == ["render"]
    assert edges["chip_finishing"] == ["xor"]

    # The data claim the ordering does not rest on, pinned so that a step gaining
    # a 'gds' input or a 'klayout_gds' output has to come back through here.
    xor_reads = {str(view) for step in jobs["xor"].steps for view in step.inputs}
    assert xor_reads == {"mag_gds", "klayout_gds"}

    finishing = {
        str(view)
        for step in jobs["chip_finishing"].steps
        for view in (*step.inputs, *step.outputs)
    }
    assert finishing == {"gds"}


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
    ``Chip`` inherited ``Classic.Config``, so RUN_RMP and RUN_MAGIC_WRITE_LEF
    were accepted configuration keys, but it declared its own ``Stages`` with
    neither OpenROAD.RMP nor OpenROAD.AddBuffer in it. The variables stay
    declared so an existing configuration keeps loading; the jobs stay absent so
    the document runs what the flow ran.
    """
    spec = _document("chip.yaml")
    declared = {variable.name for variable in spec.config}

    assert {"RUN_RMP", "RUN_MAGIC_WRITE_LEF"} <= declared
    assert "rmp" not in spec.jobs
    assert "add_buffer" not in spec.jobs


def test_chip_finishing_is_ungated():
    """
    None of its six steps was gated by the ``Chip`` flow class this document
    replaces, so the job carries no ``if``. Pinned separately from the gating
    comparison because that
    test compares job-to-step attributions, and an ``if`` wrongly added here
    would also need a variable to hang it on.
    """
    assert _document("chip.yaml").jobs["chip_finishing"].condition is None


@pytest.mark.parametrize("document", _shipped_documents())
def test_no_shipped_document_has_a_join_conflict(document):
    """
    The guard for the class of defect, applied to every shipped document.

    See :func:`_join_conflicts` for the invariant. It is the general rule --
    no job may rewrite a key a concurrent peer inherits from their common
    ancestor -- rather than the OpenROAD-only subset an earlier version of this
    guard encoded. That subset passed ``chip.yaml``, which raised on ``gds``:
    ``chip_finishing`` rewrote it while ``render`` and ``xor`` carried
    ``klayout_streamout``'s, and all five branches met at ``final_checks``.

    Runs over :func:`_shipped_documents`, so a document added later is covered
    without anyone remembering to name it here -- which is how
    ``vhdl_classic.yaml`` shipped with the framework-metric defect while a
    by-name guard was already in the file.

    ``classic.yaml`` and ``vhdl_classic.yaml`` keep render, write_lef and
    check_antenna_properties on the chain and fan out below them, because
    Odb.CheckDesignAntennaProperties rewrites the framework counts.
    ``chip.yaml`` chains render, xor and chip_finishing in flow order, so the
    one job that rewrites ``gds`` after the stream-outs is an ancestor of every
    remaining branch. The ``open_in_*`` documents are single-job and have no
    concurrency to violate.
    """
    _assert_no_join_conflicts(document)


def test_which_alternate_tools_selections_a_shipped_document_survives():
    """
    The same replay, run once per selection ``TOOLS`` can express.

    It has to be the *resolved* jobs that are walked, not the document's own
    ``uses`` providers, because that is the only place a selection is visible.
    See :data:`_SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE` for what each failing
    entry means and why nothing catches it earlier.
    """
    measured = {}
    for document in _shipped_documents():
        for job_id, provider in _alternate_providers(document):
            conflicts = _join_conflicts(document, {job_id: provider})
            if conflicts:
                measured[(document, job_id, provider)] = sorted(
                    {key for _, key, _ in conflicts}
                )

    assert measured == _SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE


def test_the_alternate_selection_guard_has_selections_to_run_over():
    """
    The enumeration above is derived, so this pins that it found something. A
    helper returning nothing would make the equality vacuous, and a vacuous
    guard reads as coverage.
    """
    enumerated = {
        (document, job_id, provider)
        for document in _shipped_documents()
        for job_id, provider in _alternate_providers(document)
    }

    # Exercised: the swap that is safe because the two jobs are in series, the
    # one that is safe because nothing else writes what it writes, and one that
    # is not safe at all.
    assert ("classic.yaml", "magic_streamout", "klayout") in enumerated
    assert ("classic.yaml", "synthesis", "yosys_vhdl") in enumerated
    assert ("classic.yaml", "lvs", "klayout") in enumerated
    # The five open_in documents have one single-provider job each, so they
    # contribute nothing and the three configured documents are the whole set.
    assert {document for document, _, _ in enumerated} == {
        "chip.yaml",
        "classic.yaml",
        "vhdl_classic.yaml",
    }


def test_the_shipped_document_guard_covers_every_document():
    """
    The parametrisation is derived, so this pins that it found them all.

    A discovery helper that silently returns an empty or partial list would
    make every case above vacuous, and a vacuous guard is worse than none
    because it reads as coverage.
    """
    discovered = set(_shipped_documents())
    assert "classic.yaml" in discovered
    assert "vhdl_classic.yaml" in discovered
    assert "chip.yaml" in discovered
    assert len(discovered) >= 8


def test_every_document_is_registered_under_its_name():
    from librelane.flows import Flow

    for name in [
        "Classic",
        "VHDLClassic",
        "Chip",
        "OpenInKLayout",
        "OpenInOpenROAD",
        "OpenInOpenROADConsole",
        "OpenInOpenSTAConsole",
        "OpenInMagic",
    ]:
        registered = Flow.factory.get(name)
        assert isinstance(registered, FlowSpec)
        assert registered.name == name


def test_the_factory_registers_every_shipped_document():
    """
    Derived from :func:`_shipped_documents` rather than from the list above, so
    that a document added to the package without reaching the registry fails
    here. The list above pins the names; this pins that none was skipped.
    """
    from librelane.flows import Flow

    for document in _shipped_documents():
        name = _document(document).name
        assert Flow.factory.get(name) is not None, document


def test_the_factory_lists_exactly_the_shipped_documents():
    """
    ``list()`` used to union the document registry with the class registry, so
    a name in it was not necessarily a document. The class registry is gone, so
    the list is now exactly the shipped documents -- which is what lets every
    caller that iterates it look each name up without a ``None`` check.
    """
    from librelane.flows import Flow

    assert Flow.factory.list() == sorted(
        _document(document).name for document in _shipped_documents()
    )


def test_a_name_no_document_claims_is_looked_up_as_none():
    """
    ``get`` answers for the document registry and for nothing else.
    """
    from librelane.flows import Flow

    assert isinstance(Flow.factory.get("Classic"), FlowSpec)
    assert Flow.factory.get("NoSuchFlow") is None


def test_registering_a_document_twice_is_an_error():
    """
    Two documents claiming one name would make ``--flow`` ambiguous, and the
    loser would be whichever the registration loop reached second. The
    duplicate is refused instead.
    """
    from librelane.flows import Flow
    from librelane.flows.flow import FlowException

    spec = Flow.factory.get("Classic")

    with pytest.raises(FlowException, match="already"):
        Flow.factory.register(spec)


def test_a_document_is_rejected_at_import_if_it_is_malformed(tmp_path):
    from librelane.flows.spec import FlowSpecError

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\njobs:\n  a:\n    needs: [nope]\n    uses: lint\n")

    with pytest.raises(FlowSpecError):
        load_flow_spec(bad)


def test_help_for_a_document_lists_its_jobs_and_their_providers():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Jobs" in help_md
    assert "| `detailed_routing` | `detailed_routing` | `openroad` |" in help_md
    assert "| `magic_streamout` | `streamout` | `magic` |" in help_md
    assert "| `xor` | inline steps | | |" in help_md


def test_help_for_a_document_lists_its_steps():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Included Steps" in help_md
    assert "`Yosys.Synthesis`" in help_md


def test_help_for_a_document_declares_its_own_variables():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Flow-specific Configuration Variables" in help_md
    assert "RUN_LINTER" in help_md


def _variables_section(help_md: str) -> str:
    """The rendered variable table, cut out of a help document."""
    start = help_md.index("#### Flow-specific Configuration Variables")
    return help_md[start : help_md.index("#### Jobs", start)]


def test_help_for_a_document_documents_the_tools_variable():
    """
    ``TOOLS`` is declared by the engine and by no document, so a table built
    from ``spec.config`` alone leaves it out. Every rendered help tells the
    reader to set it, and the flow reference publishes eight of those
    pointers, so the variable they point at has to be on the page with its
    type, its default and its description.

    The class each document replaces carried it: it declared ``TOOLS`` on its
    own configuration model, which put the variable at the head of ``Classic``'s
    list.
    """
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "`TOOLS`" in _variables_section(help_md)


def test_help_documents_the_tools_variable_for_a_document_declaring_none():
    """
    The engine's variables are a fact about running a document at all, not
    about which variables that document adds, so the section appears even for
    a document whose own ``config`` list is empty.
    """
    from librelane.flows.engine import Workflow

    spec = _document("open_in_klayout.yaml")

    assert not spec.config
    assert "`TOOLS`" in _variables_section(Workflow.help_md_for_document(spec))


def test_help_for_a_multi_provider_job_names_every_selected_provider():
    """
    ``ResolvedJob.provider`` is every selected provider joined by ``+``, which
    is one string and not one provider. No shipped document leaves a
    two-default template unpinned -- ``classic.yaml`` splits ``streamout`` and
    ``drc`` into a job per tool -- so this is written against a document
    constructed here, and it pins that the Alternatives column subtracts *both*
    selected providers rather than listing them as alternatives to themselves.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec(
        name="TwoProviderStreamOut",
        jobs={"streamout": {"uses": "streamout"}},
    )

    help_md = Workflow.help_md_for_document(spec)

    assert "| `streamout` | `streamout` | `magic`, `klayout` | none |" in help_md
