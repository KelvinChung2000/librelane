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

import pytest
import yaml

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.engine.spec_include import common_directory, share_directory
from librelane.engine.job import resolve_jobs
from librelane.engine.predicates import config_terms
from librelane.engine.selection_validation import (
    FRAMEWORK_METRICS,
    JoinConflict,
    join_conflicts,
)
from librelane.engine.spec import FlowSpec, load_flow_spec
from librelane.engine.spec_graph import ancestors
from librelane.engine.spec_validation import validate_against_registry
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
    spec = load_flow_spec(str(share_directory().joinpath(name)))
    validate_against_registry(spec)
    return spec


def _shipped_documents() -> list[str]:
    """
    Every ``.yaml`` document shipped in ``librelane/share/``, discovered.

    That directory only. ``share/common/`` holds the fragments the documents
    include with ``common::``, which are not flows and cannot be loaded alone;
    they are checked here through the documents that include them, and against
    the schema in ``test_spec_schema.py``.

    Deliberately not a hand-written list. The framework-metric guard below was
    added for ``classic.yaml`` and extended to two more by name, and in the gap
    ``vhdl_classic.yaml`` shipped carrying the very defect the guard exists to
    catch -- it was found by hand, not by the suite. A list someone has to
    remember to extend is the same defect one level up, so the parametrisation
    reads the package instead.
    """
    return sorted(
        path.name for path in share_directory().iterdir() if path.name.endswith(".yaml")
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


def _gating_variables(name: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """
    Returns
    -------
    list[tuple[str, str, tuple[str, ...]]]
        One ``(job id, implementation id, condition variables)`` triple per
        resolved step, in document order.

    Stronger than a set of ``(job id, implementation id)`` pairs, which says
    only *which* steps are gated: a job gated on the wrong boolean, or on the
    right two booleans in the wrong order, is indistinguishable there and
    visible here. Proved by mutation, not assumed: swapping ``cts``'s ``if``
    from ``RUN_CTS`` to ``RUN_DRT``, a different declared boolean, left every
    set-of-pairs comparison this file used to carry green.

    Recovered from git history rather than rewritten: this is the function
    commit c67331bb deleted as dead code, unchanged, from the last revision
    where it still had callers (its callers -- which compared it against the
    Python flows' ``gating_config_vars`` table -- were deleted earlier, at
    7a3ee0b1, when the flow classes themselves went). ``spec.jobs`` and
    ``jobs[job_id].conditions`` mean exactly what they meant there; only its
    former counterpart, ``_flow_gating_variables``, is gone for good, because
    there is no longer a Python flow to derive it from.

    ``conditions`` is projected through :func:`~librelane.engine.predicates.config_terms`
    since spec 3 retyped ``ResolvedJob.conditions`` to carry parsed predicate
    terms rather than bare names: no shipped document declares a ``metric::``
    term, so this is the same set of names it always was, read off the
    configuration half of the (possibly mixed) conjunction.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return [
        (job_id, step.get_implementation_id(), config_terms(jobs[job_id].conditions))
        for job_id in spec.jobs
        for step in jobs[job_id].steps
    ]


def _join_conflicts(
    name: str, tools: dict[str, str] | None = None
) -> list[JoinConflict]:
    """
    Replays :mod:`librelane.engine.join`'s rule over a document, with every job
    modelled as enabled.

    Returns
    -------
    list[JoinConflict]
        One entry per unresolved conflict.

    The replay itself is
    :func:`librelane.engine.selection_validation.join_conflicts`, which this file
    is where it was written: it started as a guard over the shipped documents
    and became a library function once the engine gained a load-time check that
    has to ask the same question of a user's ``TOOLS`` entry. Calling it rather
    than keeping a copy is the point -- two implementations of one rule would
    let the shipped documents be guarded against a rule the engine does not
    enforce, or the reverse.

    ``enabled`` is every job. That is the right question *here* and the wrong
    one at load time. A gated-off job passes ``state_in`` through unchanged, so
    gating can only move a branch's last writer backwards, and two branches that
    disagree under some gating already disagree with everything enabled: the
    all-enabled replay reports a superset. A superset is what a guard over the
    shipped defaults wants, since those defaults do enable everything; the
    engine's load-time refusal takes the real gating instead, because there an
    over-report is a rejected configuration that would have run.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec, tools)
    return join_conflicts(spec, jobs, set(jobs))


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
#: ``librelane.engine.spec_validation`` nor this guard's pre-selection form
#: could see it: the metrics are declared nowhere, and the provider is named
#: nowhere in the document.
#:
#: Pinned rather than left to be discovered on a real run, and pinned as an
#: equality so that a selection becoming safe fails here too. What the engine
#: does about them is ``test/engine/test_selection_validation.py``'s subject;
#: this file pins that the replay still measures them.
_SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE = {
    ("chip.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("chip.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("chip.yaml", "lvs", "klayout"): list(sorted(FRAMEWORK_METRICS)),
    ("classic.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("classic.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("classic.yaml", "lvs", "klayout"): list(sorted(FRAMEWORK_METRICS)),
    ("vhdl_classic.yaml", "klayout_drc", "magic"): ["magic__drc_error__count"],
    ("vhdl_classic.yaml", "magic_drc", "klayout"): ["klayout__drc_error__count"],
    ("vhdl_classic.yaml", "lvs", "klayout"): list(sorted(FRAMEWORK_METRICS)),
}


def _assert_no_join_conflicts(name: str) -> None:
    conflicts = _join_conflicts(name)
    assert not conflicts, "\n".join(
        f"'{conflict.consumer}' joins branches that wrote '{conflict.key}' from "
        f"different jobs {list(conflict.origins)}, so join_states raises "
        f"JoinConflictError on the first real run. Every branch of a fan-out "
        f"must descend from the last job that writes each key the branches "
        f"share."
        for conflict in conflicts
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


#: Every shipped document, written out rather than discovered, so that a
#: document *disappearing* fails here too.
#: :func:`test_the_document_list_names_every_shipped_document` is what stops the
#: literal going stale in the other direction.
#:
#: The five Open-In documents are not missing from this list: a viewer is not a
#: flow, and `librelane open` runs those steps now. test/cli/test_open_in.py
#: covers them.
_SHIPPED_DOCUMENTS = [
    "classic.yaml",
    "vhdl_classic.yaml",
    "chip.yaml",
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


#: Every job's ``if`` conjunction in ``classic.yaml``, read off the YAML by
#: hand and sanity-checked one at a time against the document's own comments
#: -- not generated by running the loader, which would pin whatever gating bug
#: already shipped rather than catch one. A job the document does not gate is
#: listed with the empty tuple, matching ``ResolvedJob.conditions``, rather
#: than omitted, so that a job losing or gaining an ``if`` is visible either
#: way.
#:
#: Two entries are conjunctions rather than single variables, and both are
#: pinned in the order the YAML writes them: ``heuristic_diode_insertion``
#: carries the antenna-repair job's own gate alongside its specific one, and
#: ``xor`` carries three, because ``KLayout.XOR`` genuinely cannot run unless
#: both stream-outs fired.
_CLASSIC_JOB_CONDITIONS: dict[str, tuple[str, ...]] = {
    "lint": ("RUN_LINTER",),
    "synthesis": (),
    "pre_pnr_sta": (),
    "floorplan": (),
    "rmp": ("RUN_RMP",),
    "set_power_connections": (),
    "macro_placement": (),
    "tapcell_insertion": ("RUN_TAP_ENDCAP_INSERTION",),
    "power_grid": (),
    "io_placement": (),
    "add_buffer": (),
    "global_placement": (),
    "post_gpl_checks": (),
    "post_gpl_repair": ("RUN_POST_GPL_DESIGN_REPAIR",),
    "detailed_placement": (),
    "cts": ("RUN_CTS",),
    "sta_mid_pnr_2": (),
    "post_cts_opt": ("RUN_POST_CTS_RESIZER_TIMING",),
    "sta_mid_pnr_3": (),
    "global_routing": (),
    "post_grt_repair": ("RUN_POST_GRT_DESIGN_REPAIR",),
    "diodes_on_ports": ("RUN_ANTENNA_REPAIR",),
    "heuristic_diode_insertion": (
        "RUN_ANTENNA_REPAIR",
        "RUN_HEURISTIC_DIODE_INSERTION",
    ),
    "repair_antennas": ("RUN_ANTENNA_REPAIR",),
    "post_grt_opt": ("RUN_POST_GRT_RESIZER_TIMING",),
    "sta_mid_pnr_4": (),
    "detailed_routing": ("RUN_DRT",),
    "routing_reports": (),
    "fill_insertion": ("RUN_FILL_INSERTION",),
    "cell_frequency_tables": (),
    "extraction": ("RUN_SPEF_EXTRACTION",),
    "signoff_sta": ("RUN_MCSTA",),
    "ir_drop": ("RUN_IRDROP_REPORT",),
    "magic_streamout": ("RUN_MAGIC_STREAMOUT",),
    "klayout_streamout": ("RUN_KLAYOUT_STREAMOUT",),
    "render": (),
    "write_lef": ("RUN_MAGIC_WRITE_LEF",),
    "check_antenna_properties": ("RUN_MAGIC_WRITE_LEF",),
    "xor": ("RUN_KLAYOUT_XOR", "RUN_MAGIC_STREAMOUT", "RUN_KLAYOUT_STREAMOUT"),
    "magic_drc": ("RUN_MAGIC_DRC",),
    "klayout_drc": ("RUN_KLAYOUT_DRC",),
    "lvs": ("RUN_LVS",),
    "formal_equivalence": ("RUN_EQY",),
    "final_checks": (),
}

#: The same, for ``vhdl_classic.yaml``. Identical to Classic's wherever a job
#: is shared -- the document's own header comment says the gating is
#: unchanged -- minus the three jobs this flow omits (``lint``,
#: ``set_power_connections``, ``formal_equivalence``), which is why this is
#: not written as a filter over :data:`_CLASSIC_JOB_CONDITIONS`: a document is
#: a self-contained declaration, and the migration this file now pins is of
#: the document, not of a relationship between two documents.
_VHDL_CLASSIC_JOB_CONDITIONS: dict[str, tuple[str, ...]] = {
    "synthesis": (),
    "pre_pnr_sta": (),
    "floorplan": (),
    "rmp": ("RUN_RMP",),
    "macro_placement": (),
    "tapcell_insertion": ("RUN_TAP_ENDCAP_INSERTION",),
    "power_grid": (),
    "io_placement": (),
    "add_buffer": (),
    "global_placement": (),
    "post_gpl_checks": (),
    "post_gpl_repair": ("RUN_POST_GPL_DESIGN_REPAIR",),
    "detailed_placement": (),
    "cts": ("RUN_CTS",),
    "sta_mid_pnr_2": (),
    "post_cts_opt": ("RUN_POST_CTS_RESIZER_TIMING",),
    "sta_mid_pnr_3": (),
    "global_routing": (),
    "post_grt_repair": ("RUN_POST_GRT_DESIGN_REPAIR",),
    "diodes_on_ports": ("RUN_ANTENNA_REPAIR",),
    "heuristic_diode_insertion": (
        "RUN_ANTENNA_REPAIR",
        "RUN_HEURISTIC_DIODE_INSERTION",
    ),
    "repair_antennas": ("RUN_ANTENNA_REPAIR",),
    "post_grt_opt": ("RUN_POST_GRT_RESIZER_TIMING",),
    "sta_mid_pnr_4": (),
    "detailed_routing": ("RUN_DRT",),
    "routing_reports": (),
    "fill_insertion": ("RUN_FILL_INSERTION",),
    "cell_frequency_tables": (),
    "extraction": ("RUN_SPEF_EXTRACTION",),
    "signoff_sta": ("RUN_MCSTA",),
    "ir_drop": ("RUN_IRDROP_REPORT",),
    "magic_streamout": ("RUN_MAGIC_STREAMOUT",),
    "klayout_streamout": ("RUN_KLAYOUT_STREAMOUT",),
    "render": (),
    "write_lef": ("RUN_MAGIC_WRITE_LEF",),
    "check_antenna_properties": ("RUN_MAGIC_WRITE_LEF",),
    "xor": ("RUN_KLAYOUT_XOR", "RUN_MAGIC_STREAMOUT", "RUN_KLAYOUT_STREAMOUT"),
    "magic_drc": ("RUN_MAGIC_DRC",),
    "klayout_drc": ("RUN_KLAYOUT_DRC",),
    "lvs": ("RUN_LVS",),
    "final_checks": (),
}

#: The same, for ``chip.yaml``. ``chip_finishing`` is ungated -- pinned here
#: with an empty tuple, and separately by
#: :func:`test_chip_finishing_is_ungated`, which this does not make redundant:
#: that test pins the property in isolation, this pins it as part of the
#: document's whole gating listing so a mutation there cannot hide among
#: correct neighbours.
_CHIP_JOB_CONDITIONS: dict[str, tuple[str, ...]] = {
    "lint": ("RUN_LINTER",),
    "synthesis": (),
    "pre_pnr_sta": (),
    "floorplan": (),
    "set_power_connections": (),
    "pad_ring": (),
    "macro_placement": (),
    "tapcell_insertion": ("RUN_TAP_ENDCAP_INSERTION",),
    "power_grid": (),
    "placement_seed": (),
    "global_placement": (),
    "post_gpl_checks": (),
    "post_gpl_repair": ("RUN_POST_GPL_DESIGN_REPAIR",),
    "detailed_placement": (),
    "cts": ("RUN_CTS",),
    "sta_mid_pnr_2": (),
    "post_cts_opt": ("RUN_POST_CTS_RESIZER_TIMING",),
    "sta_mid_pnr_3": (),
    "global_routing": (),
    "post_grt_repair": ("RUN_POST_GRT_DESIGN_REPAIR",),
    "diodes_on_ports": ("RUN_ANTENNA_REPAIR",),
    "heuristic_diode_insertion": (
        "RUN_ANTENNA_REPAIR",
        "RUN_HEURISTIC_DIODE_INSERTION",
    ),
    "repair_antennas": ("RUN_ANTENNA_REPAIR",),
    "post_grt_opt": ("RUN_POST_GRT_RESIZER_TIMING",),
    "sta_mid_pnr_4": (),
    "detailed_routing": ("RUN_DRT",),
    "routing_reports": (),
    "fill_insertion": ("RUN_FILL_INSERTION",),
    "cell_frequency_tables": (),
    "extraction": ("RUN_SPEF_EXTRACTION",),
    "signoff_sta": ("RUN_MCSTA",),
    "ir_drop": ("RUN_IRDROP_REPORT",),
    "magic_streamout": ("RUN_MAGIC_STREAMOUT",),
    "klayout_streamout": ("RUN_KLAYOUT_STREAMOUT",),
    "render": (),
    "xor": ("RUN_KLAYOUT_XOR", "RUN_MAGIC_STREAMOUT", "RUN_KLAYOUT_STREAMOUT"),
    "chip_finishing": (),
    "magic_drc": ("RUN_MAGIC_DRC",),
    "klayout_drc": ("RUN_KLAYOUT_DRC",),
    "lvs": ("RUN_LVS",),
    "formal_equivalence": ("RUN_EQY",),
    "final_checks": (),
}

_JOB_CONDITIONS_BY_DOCUMENT: dict[str, dict[str, tuple[str, ...]]] = {
    "classic.yaml": _CLASSIC_JOB_CONDITIONS,
    "vhdl_classic.yaml": _VHDL_CLASSIC_JOB_CONDITIONS,
    "chip.yaml": _CHIP_JOB_CONDITIONS,
}


def _golden_gating_variables(
    name: str, conditions: dict[str, tuple[str, ...]]
) -> list[tuple[str, str, tuple[str, ...]]]:
    """
    Expands a hand-written ``{job id: condition variables}`` mapping into the
    shape :func:`_gating_variables` returns, broadcasting each job's
    conditions across every step it resolves to.

    The ``(job id, implementation id)`` half of each triple is read off
    :func:`_jobs_of_each_step` rather than written by hand: it is structural,
    already exercised by the tests elsewhere in this file that name exact step
    lists (``jobs["post_gpl_checks"].steps == [...]`` and its siblings), and
    getting it wrong here would not hide a gating defect -- only the condition
    half, supplied by the caller, does that, which is why that half and only
    that half is read off the YAML by hand.

    Raises if ``conditions`` names a job the document does not have, or omits
    one it does, so a document gaining or losing a job cannot silently narrow
    what this checks.
    """
    pairs = _jobs_of_each_step(name)
    named = {job_id for job_id, _ in pairs}
    missing = named - set(conditions)
    extra = set(conditions) - named
    assert not missing, (
        f"{name}: the golden conditions mapping is missing {sorted(missing)}"
    )
    assert not extra, (
        f"{name}: the golden conditions mapping names jobs the document does not have {sorted(extra)}"
    )
    return [
        (job_id, implementation, conditions[job_id]) for job_id, implementation in pairs
    ]


@pytest.mark.parametrize("document", _SHIPPED_DOCUMENTS)
def test_each_document_gates_exactly_the_variables_read_off_its_yaml(document):
    """
    The pin this file lost when phase 5 deleted the Python flows: a
    golden, order-sensitive ``(job id, implementation id, condition tuple)``
    listing per shipped document, checked against :func:`_gating_variables`.

    Order-sensitive and per-step, not a set of ``(job id, implementation id)``
    pairs: a job gated on a plausible-wrong variable -- ``RUN_DRT`` where
    ``RUN_CTS`` was meant, both declared booleans -- resolves to a different
    ``ResolvedJob.conditions`` and is caught here, where a set of gated pairs
    cannot see it, because *that* the job is gated does not change.
    ``FlowSpec._check_conditions_are_declared_booleans`` catches an
    *undeclared* variable at load time; this is the check for the declared
    but wrong one, which nothing else in the suite makes.

    See :data:`_CLASSIC_JOB_CONDITIONS`, :data:`_VHDL_CLASSIC_JOB_CONDITIONS`
    and :data:`_CHIP_JOB_CONDITIONS` for the golden values themselves, each
    read off its document's YAML by hand rather than off the loader's output.
    """
    conditions = _JOB_CONDITIONS_BY_DOCUMENT[document]
    assert _gating_variables(document) == _golden_gating_variables(document, conditions)


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


def test_vhdl_classic_pins_the_vhdl_synthesis_provider():
    """
    A VHDL front end is the whole reason this document exists, so it names the
    provider rather than leaving it to ``TOOLS``. ``classic.yaml`` leaves the
    same job bare and takes the template's default, ``yosys``; that is not an
    oversight, and this pins the difference.
    """
    assert _document("vhdl_classic.yaml").jobs["synthesis"].uses == (
        "synthesis/yosys_vhdl"
    )


def test_vhdl_classic_omits_the_four_jobs_it_cannot_run():
    """
    The ``VHDLClassic`` class named them: the lint stage,
    Odb.SetPowerConnections, Odb.WriteVerilogHeader and the formal equivalence
    stage. Only the one step is dropped from ``post_gpl_checks``, which
    otherwise runs here exactly as it does in ``classic.yaml``:
    OpenROAD.STAMidPNR is not a Verilog step.
    """
    jobs = _document("vhdl_classic.yaml").jobs

    assert "lint" not in jobs
    assert "set_power_connections" not in jobs
    assert "formal_equivalence" not in jobs

    assert jobs["post_gpl_checks"].steps == ["OpenROAD.STAMidPNR"]
    assert "Odb.WriteVerilogHeader" not in jobs["post_gpl_checks"].steps


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
    exactly as it did in the ``Chip`` flow this document replaced, where it ran
    before the six finishing steps.

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
    The ``Chip`` flow this document replaced inherited ``Classic``'s
    configuration, so RUN_RMP and RUN_MAGIC_WRITE_LEF were accepted keys, but
    it ran neither OpenROAD.RMP nor OpenROAD.AddBuffer. The variables stay
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
    remaining branch.
    """
    _assert_no_join_conflicts(document)


def test_which_alternate_tools_selections_a_shipped_document_survives():
    """
    The same replay, run once per selection ``TOOLS`` can express.

    It has to be the *resolved* jobs that are walked, not the document's own
    ``uses`` providers, because that is the only place a selection is visible.
    See :data:`_SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE` for what each failing
    entry means and why no check reading declared contracts can see it.
    """
    measured = {}
    for document in _shipped_documents():
        for job_id, provider in _alternate_providers(document):
            conflicts = _join_conflicts(document, {job_id: provider})
            if conflicts:
                measured[(document, job_id, provider)] = sorted(
                    {conflict.key for conflict in conflicts}
                )

    assert measured == _SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE


def test_the_replay_the_documents_are_guarded_by_is_the_engine_s_own():
    """
    The one thing that stops this file's guard and the engine's load-time
    refusal drifting apart: they are the same function.

    Pinned as an identity rather than left implicit, because a later edit that
    inlines a "small" private copy here would leave both green while the shipped
    documents were being checked against a rule nothing enforces.
    """
    conflicts = _join_conflicts("classic.yaml", {"magic_drc": "klayout"})

    assert conflicts
    assert all(isinstance(conflict, JoinConflict) for conflict in conflicts)


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
    # Every shipped document is configured, so all three appear.
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
    assert discovered == {"classic.yaml", "vhdl_classic.yaml", "chip.yaml"}


def test_every_document_is_registered_under_its_name():
    from librelane.engine import Flow

    for name in ["Classic", "VHDLClassic", "Chip"]:
        registered = Flow.factory.get(name)
        assert isinstance(registered, FlowSpec)
        assert registered.name == name


def test_the_factory_registers_every_shipped_document():
    """
    Derived from :func:`_shipped_documents` rather than from the list above, so
    that a document added to the package without reaching the registry fails
    here. The list above pins the names; this pins that none was skipped.
    """
    from librelane.engine import Flow

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
    from librelane.engine import Flow

    assert Flow.factory.list() == sorted(
        _document(document).name for document in _shipped_documents()
    )


def test_the_common_library_is_included_and_not_registered():
    """
    ``common/`` holds what the three documents declare identically. A fragment
    there is not a flow: it has no name to be registered under, and the
    registration loop does not descend into the directory, so nothing has to
    filter it out. Every one of them is reached, because every one of them is
    included -- and reached the way any other document would reach it, through
    ``common::``, rather than by the path that only works from in here.
    """
    from librelane.engine import Flow

    library = sorted(
        path.name
        for path in common_directory().iterdir()
        if path.name.endswith(".yaml")
    )
    assert library, "the documents below claim to include something"

    included = {
        entry
        for document in _SHIPPED_DOCUMENTS
        for entry in yaml.safe_load(
            share_directory().joinpath(document).read_text(encoding="utf8")
        )["include"]
    }
    assert included == {f"common::{name}" for name in library}
    assert Flow.factory.list() == ["Chip", "Classic", "VHDLClassic"]


def test_a_name_no_document_claims_is_looked_up_as_none():
    """
    ``get`` answers for the document registry and for nothing else.
    """
    from librelane.engine import Flow

    assert isinstance(Flow.factory.get("Classic"), FlowSpec)
    assert Flow.factory.get("NoSuchFlow") is None


def test_registering_a_document_twice_is_an_error():
    """
    Two documents claiming one name would make ``--flow`` ambiguous, and the
    loser would be whichever the registration loop reached second. The
    duplicate is refused instead.
    """
    from librelane.engine import Flow
    from librelane.engine.flow import FlowException

    spec = Flow.factory.get("Classic")

    with pytest.raises(FlowException, match="already"):
        Flow.factory.register(spec)


def test_a_document_is_rejected_at_import_if_it_is_malformed(tmp_path):
    from librelane.engine.spec import FlowSpecError

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\njobs:\n  a:\n    needs: [nope]\n    uses: lint\n")

    with pytest.raises(FlowSpecError):
        load_flow_spec(bad)


def test_help_for_a_document_lists_its_jobs_and_their_providers():
    from librelane.engine.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Jobs" in help_md
    assert "| `detailed_routing` | `detailed_routing` | `openroad` |" in help_md
    assert "| `magic_streamout` | `streamout` | `magic` |" in help_md
    assert "| `xor` | inline steps | | |" in help_md


def test_help_for_a_document_lists_its_steps():
    from librelane.engine.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Included Steps" in help_md
    assert "`Yosys.Synthesis`" in help_md


def test_help_for_a_document_declares_its_own_variables():
    from librelane.engine.engine import Workflow

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
    from librelane.engine.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "`TOOLS`" in _variables_section(help_md)


def test_help_documents_the_tools_variable_for_a_document_declaring_none():
    """
    The engine's variables are a fact about running a document at all, not
    about which variables that document adds, so the section appears even for
    a document whose own ``config`` list is empty.
    """
    from librelane.engine.engine import Workflow

    spec = FlowSpec.model_validate({"name": "NoVariables", "jobs": {"floorplan": {}}})
    validate_against_registry(spec)

    assert not spec.config
    assert "`TOOLS`" in _variables_section(Workflow.help_md_for_document(spec))


def test_help_names_the_other_provider_of_a_template_as_an_alternative():
    """
    The Alternatives column is every registration for the job's template other
    than the selected one, so a job never appears as an alternative to itself.
    ``classic.yaml`` runs ``streamout`` under two jobs, each pinning one of the
    template's two providers, so each row names the other tool -- which is
    exactly what a reader needs to write a ``TOOLS`` entry for that job.
    """
    from librelane.engine.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "| `magic_streamout` | `streamout` | `magic` | `klayout` |" in help_md
    assert "| `klayout_streamout` | `streamout` | `klayout` | `magic` |" in help_md
    assert "| `lint` | `lint` | `verilator` | none |" in help_md
