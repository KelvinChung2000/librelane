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
The workflow document checks that need the providers a run actually selected.

:mod:`librelane.flows.spec_validation` reads what a document *declares*, and it
has to: it runs before ``TOOLS`` has been consulted, so the only providers it
can see are the ones the document's ``uses`` keys name. Everything here reads
what a run actually resolved -- the selected registration's steps, views and
metrics, and the ``if`` conditions the configuration has already answered --
which is the only vantage point from which a ``TOOLS`` entry is visible at all.

Two checks live here.

:func:`lost_views` is the view availability preflight, made configuration-aware:
a selection that removes the only producer of a view some job still requires is
refused, rather than being discovered by the first step that reaches for it.

:func:`join_conflicts` replays :mod:`librelane.flows.join`'s rule symbolically,
which is the only way to see a key two concurrent jobs both write. It was a
guard inside ``test/flows/test_documents.py`` first, over the shipped documents
under their declared providers; it is a library function because the same replay
answers the same question about a user's ``TOOLS`` selection, and answering it
at load is strictly better than raising ``JoinConflictError`` an hour into a
run.

Soundness, which is the whole difficulty of moving the replay here
-------------------------------------------------------------------

As a test over the shipped documents, the replay is allowed to over-report: a
false conflict is a loud failure a maintainer adjudicates. As a load-time
refusal it is not, because an over-report rejects a configuration that would
have run, which is worse than the mid-run failure it replaces. Two things follow,
and both are load-bearing:

* Everything here reasons over the jobs that **will run**. A job whose ``if``
  is false fires as a pass-through (:meth:`librelane.flows.engine.Workflow.run`)
  and writes nothing, so it cannot collide with anything. The
  ``test/flows/test_documents.py`` form models every job as enabled, and that is
  a strict over-approximation rather than a different rule: gating a job off can
  only move a branch's last writer for a key *backwards* along that branch, and
  two branches whose last writers differ under some gating already differ with
  everything enabled. So the all-enabled replay reports a superset, which is
  right for a guard over the shipped defaults and wrong for a hard error.
  ``{"magic_drc": "klayout"}`` under ``RUN_MAGIC_DRC: false`` is the case that
  makes the difference concrete: the two DRC jobs cannot collide because only
  one of them runs.
* :func:`lost_views` is a **differential** against the document's own providers
  rather than an absolute availability rule. ``spec_validation`` presumes that a
  view no job in the document produces arrives in the initial state, which is
  what lets a document start mid-flow from ``--with-initial-state``; an absolute
  rule here would revoke that presumption for every document. So the question
  asked is narrower and needs no presumption: *did the selection remove a
  producer the document had?* A view that was never produced in-document is
  outside it either way.

The initial state, which is known before the flow exists
--------------------------------------------------------

``--with-initial-state`` is the one invocation-shaped input this module does
model, and the reason is that it is available before there is a flow to refuse:
:func:`librelane.cli.run.start_flow` loads and merges the named state files,
folds every ``--initial-state-element-override`` into them, and only then
constructs the :class:`librelane.flows.engine.Workflow`. So the view set a state
supplies is an ordinary constructor input, threaded from there through
:func:`validate_selection` into :func:`lost_views` as a fourth resolution input.

It has to be, because the differential above is not the whole answer. A run that
starts from a state already carrying ``json_h`` does not care that its selection
stopped producing ``json_h``, and refusing it at load is precisely the false
rejection this module is otherwise built to avoid: ``{"synthesis":
"yosys_vhdl"}`` on ``classic.yaml`` is a configuration that runs, given that
state. Those views are available to every job rather than to the descendants of
one, because the initial state is the common ancestor of the whole graph, so
they enter the availability question unconditionally.

:func:`supplied_views` is where a state becomes that set, and it counts a view
as supplied when the state maps it to something other than ``None`` -- the rule
:meth:`librelane.steps.Step.start` applies to a non-optional input on the real
state. Mirroring it is what keeps the load-time verdict and the run-time one the
same verdict rather than two rules that mostly agree.

Neither check models ``--target``, ``--skip`` or ``--reproducible``. Unlike the
initial state, those shape one invocation rather than the configuration, and
they are not known when a
:class:`librelane.flows.engine.Workflow` is constructed. ``--skip`` makes a job
pass through, so it can only remove a conflict, which leaves this check
over-reporting for that one invocation; the configuration is still one no
unskipped run can execute. ``--target`` can *introduce* a sink join by excluding
the job ``final`` names, which is under-reporting, and which
:func:`librelane.flows.join.join_sink_states` catches at run time with a message
naming the excluded job.
"""

import dataclasses
from collections.abc import Mapping, Set
from dataclasses import dataclass

from loguru import logger

from librelane.jobs import JobRegistry, JobResolutionError
from librelane.state import DesignFormat, State
from librelane.steps.odb.base import OdbpyStep
from librelane.steps.openroad.base import OpenROADStep

from librelane.flows.job import ResolvedJob, resolve_jobs
from librelane.flows.predicates import MetricTerm, config_terms, metric_terms
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_graph import ancestors, topological_order

#: The metrics every OpenROAD invocation writes and nothing declares.
#:
#: :meth:`librelane.steps.openroad.base.OpenROADStep.get_command` and
#: :meth:`librelane.steps.odb.base.OdbpyStep.get_command` both pass an
#: unconditional ``-metrics``, and OpenROAD's logger fills these in. No step, job
#: template or registration mentions them -- ``grep`` across ``librelane`` finds
#: nothing -- so every check reasoning from declared contracts is blind to them,
#: and :mod:`librelane.flows.join` is what discovers the disagreement, on the
#: first real run, after the tools have been invoked. Modelled here as implicit
#: outputs, which is where the special case belongs.
FRAMEWORK_METRICS = (
    "flow__warnings__count",
    "flow__errors__count",
    "flow__warnings__type_count",
)

#: The name :func:`join_conflicts` gives the implicit join that forms a flow's
#: final state, which is not a job and so has no id of its own.
SINK_JOIN = "<the final state>"


@dataclass(frozen=True)
class JoinConflict:
    """
    One key that reaches a join carrying values from two different jobs.

    Parameters
    ----------
    consumer
        The job whose incoming branches disagree, or :data:`SINK_JOIN`.
    key
        The view id or metric name they disagree about. One rule covers both,
        because ``join.py`` merges views and metrics alike.
    origins
        The jobs that last wrote the key on each incoming branch, sorted.
    """

    consumer: str
    key: str
    origins: tuple[str, ...]


@dataclass(frozen=True)
class LostView:
    """
    One view a selection stopped producing that a job still requires.

    Parameters
    ----------
    consumer
        The job that requires the view and will not receive it.
    view
        The view's id.
    producers
        The jobs that produce it under the document's own providers and no
        longer do under the selected ones, sorted. These are exactly the
        ``TOOLS`` entries to undo.
    """

    consumer: str
    view: str
    producers: tuple[str, ...]


def supplied_views(state: State | None) -> set[str]:
    """
    The views an initial state hands the run before its first job.

    Parameters
    ----------
    state : State | None
        The state ``--with-initial-state`` named, once
        ``--initial-state-element-override`` has been folded into it, or
        ``None`` when the run was given no initial state at all.

    Returns
    -------
    set[str]
        The ids of the views it supplies. A state that maps a view to ``None``
        supplies nothing for it, which is the same reading
        :meth:`librelane.steps.Step.start` gives that key when it decides
        whether a non-optional input is missing.

    ``None`` answers with the empty set because a run given no initial state is
    given no views, which is the reading that makes every no-state verdict in
    this module identical to the one it gave before a state could be passed at
    all.
    """
    if state is None:
        return set()
    return {view for view, element in state.items() if element is not None}


def validate_selection(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str] = frozenset(),
    rings: Mapping[str, tuple[str, ...]] | None = None,
) -> None:
    """
    Refuses a provider selection this document cannot run.

    Parameters
    ----------
    spec : FlowSpec
        The document, for its graph, its name and its ``final`` key.
    jobs : Mapping[str, ResolvedJob]
        Its jobs as :func:`librelane.flows.job.resolve_jobs` resolved them,
        under the ``TOOLS`` selection being validated. One entry per
        *original* job, ring members included individually: this module, not
        the caller, does the ring folding below.
    enabled : Set[str]
        The ids of the jobs whose ``if`` conditions this configuration makes
        true. A job outside it fires as a pass-through and writes nothing. For
        a ring, this is the gate id alone, counted enabled iff the gate's own
        ``if`` holds -- see :meth:`librelane.flows.engine.Workflow._enabled_jobs`.
    initial_views : Set[str]
        The views this run's initial state supplies, from
        :func:`supplied_views`. Empty for a run given no initial state, which is
        what makes that run's verdicts exactly the ones it got before this
        module could be told about a state.
    rings : Mapping[str, tuple[str, ...]] | None
        Every ring's gate id mapped to its members, as
        :meth:`librelane.flows.spec.FlowSpec.rings` returns. ``None`` or empty
        for a document with no ring, which is every document before this
        parameter existed, so an omitted ``rings`` reproduces exactly the
        verdicts this module gave before it could be told about one.

        This module owns the ring-folding math, rather than the caller
        pre-folding ``jobs``: :func:`join_conflicts` and :func:`lost_views`
        already walk :meth:`~librelane.flows.spec.FlowSpec.collapsed_edges`,
        whose node space is one entry per ring (keyed by its gate) and one
        per ordinary job, so the ``jobs`` view handed to them has to have
        exactly that same node space or the two would disagree about what
        the graph's nodes even are. See :func:`_fold_rings`.

    Raises
    ------
    JobResolutionError
        If the selection removes a view some enabled job requires, or puts two
        writers of one key on branches the graph runs concurrently. The message
        names the key or view, the jobs involved, and every provider that would
        work instead.

    Also logs a warning, never a refusal, for every producer whose runtime
    (``metric::``) term a consumer needing it does not repeat in its own
    ``if``. See :func:`unrepeated_runtime_terms`.
    """
    rings = rings or {}
    folded = _fold_rings(spec, jobs, rings)
    _warn_unrepeated_runtime_terms(folded)
    lost = lost_views(spec, folded, enabled, initial_views)
    if lost:
        # The message-building path below gets the *unfolded* 'jobs', not
        # 'folded': a remedy search re-resolves a candidate TOOLS selection,
        # and only the unfolded view still carries every ring member's own
        # provider for _effective_tools to read. See _alternatives_that_work.
        raise JobResolutionError(
            _lost_view_message(spec, jobs, enabled, initial_views, lost[0], rings)
        )
    conflicts = join_conflicts(spec, folded, enabled)
    if conflicts:
        raise JobResolutionError(
            _conflict_message(spec, jobs, enabled, initial_views, conflicts[0], rings)
        )


def _fold_rings(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    rings: Mapping[str, tuple[str, ...]],
) -> dict[str, ResolvedJob]:
    """
    Replaces every ring's members with one pseudo-job, keyed by the gate id.

    Parameters
    ----------
    spec : FlowSpec
        The document, for :meth:`~librelane.flows.spec.FlowSpec.collapsed_edges`,
        which is the authority on a ring's external ``needs``: re-deriving it
        here, separately, would risk disagreeing with the graph
        :func:`join_conflicts` and :func:`lost_views` actually walk.
    jobs : Mapping[str, ResolvedJob]
        Every original job, ring members included individually.
    rings : Mapping[str, tuple[str, ...]]
        Every ring's gate id mapped to its members.

    Returns
    -------
    dict[str, ResolvedJob]
        ``jobs``, unchanged, when ``rings`` is empty. Otherwise every
        non-member job carried through as-is, and one pseudo-job per ring,
        keyed by its gate id and built from the gate's own ``ResolvedJob``
        (which already carries the gate's own ``conditions``, ``provides``
        and ``metrics`` -- only the gate's output ever leaves the loop, so
        those three are exactly the ring's, unaltered) with three fields
        replaced:

        * ``requires``: the union, over every member, of views that member
          requires (or accepts as a native view) and no member of the same
          ring provides -- folding a member's ``native_views`` into this
          union too and zeroing the pseudo-job's own, so
          :func:`_required_views` (which unions the two) reads exactly this
          set and nothing doubled.
        * ``needs``: the collapsed node's own needs, read off
          ``spec.collapsed_edges()`` rather than re-derived.
        * ``source``: the ring-entry member's (``rings[gate][0]``) -- the
          member :meth:`librelane.flows.engine.Workflow._run_loop` joins the
          ring's external tokens under on pass 1.
    """
    if not rings:
        return dict(jobs)
    collapsed = spec.collapsed_edges()
    member_of = {member: gate for gate, members in rings.items() for member in members}
    folded: dict[str, ResolvedJob] = {}
    for job_id, job in jobs.items():
        gate = member_of.get(job_id)
        if gate is None:
            folded[job_id] = job
            continue
        if job_id != gate:
            # Absorbed into the ring's one pseudo-job, built below when this
            # loop reaches the gate itself.
            continue
        members = rings[gate]
        member_jobs = [jobs[member] for member in members]
        provided_ids: set[str] = set()
        for member_job in member_jobs:
            provided_ids.update(str(view) for view in member_job.provides)
            for step in member_job.steps:
                provided_ids.update(view.id for view in step.outputs)
        required_by_id: dict[str, DesignFormat] = {}
        for member_job in member_jobs:
            for view in (*member_job.requires, *member_job.native_views):
                if view.optional:
                    continue
                view_id = str(view)
                if view_id in provided_ids:
                    continue
                required_by_id.setdefault(view_id, view)
        folded[gate] = dataclasses.replace(
            job,
            requires=tuple(
                required_by_id[view_id] for view_id in sorted(required_by_id)
            ),
            needs=tuple(collapsed[gate]),
            source=dict(jobs[members[0]].source),
            native_views=(),
        )
    return folded


def unrepeated_runtime_terms(
    jobs: Mapping[str, ResolvedJob],
) -> list[tuple[str, str, tuple[MetricTerm, ...]]]:
    """
    Every producer a job needs whose runtime term the job does not repeat.

    Parameters
    ----------
    jobs : Mapping[str, ResolvedJob]
        The document's resolved jobs.

    Returns
    -------
    list[tuple[str, str, tuple[MetricTerm, ...]]]
        One ``(consumer, producer, terms)`` triple per producer named in some
        job's ``needs`` whose ``if`` carries a runtime (``metric::``) term the
        consumer's own ``if`` does not carry, in document order over the
        consumer and then over its ``needs``. ``terms`` is the producer's
        runtime terms the consumer is missing, not the consumer's own.

    A producer whose runtime term decides false fires as a pass-through and
    writes nothing, so the state its consumer receives is whatever state the
    producer's own predecessors gave it, unchanged. A consumer that repeats
    the exact term in its own ``if`` -- :class:`~librelane.flows.predicates.MetricTerm`
    compared by dataclass equality, so the same metric under a different
    operator or literal does not count -- inherits the same disposition and
    sees a coherent story either way. One that does not is silently exposed
    to a state the document never says it is prepared for. This is not
    refused: a document may intend exactly that, a consumer content with
    whatever a pass-through leaves behind, so :func:`validate_selection` logs
    a warning over this rather than raising.
    """
    findings: list[tuple[str, str, tuple[MetricTerm, ...]]] = []
    for consumer_id, consumer in jobs.items():
        consumer_terms = set(metric_terms(consumer.conditions))
        for producer_id in consumer.needs:
            producer_terms = metric_terms(jobs[producer_id].conditions)
            missing = tuple(
                term for term in producer_terms if term not in consumer_terms
            )
            if missing:
                findings.append((consumer_id, producer_id, missing))
    return findings


def _warn_unrepeated_runtime_terms(jobs: Mapping[str, ResolvedJob]) -> None:
    for consumer_id, producer_id, missing in unrepeated_runtime_terms(jobs):
        names = " and ".join(
            f"metric::{term.metric} {term.op} {term.literal}" for term in missing
        )
        logger.warning(
            f"Job '{consumer_id}' needs '{producer_id}', whose 'if' has "
            f"runtime term(s) {names} that '{consumer_id}' does not repeat "
            f"in its own 'if'. A false term fires '{producer_id}' as a "
            f"pass-through, which writes nothing, so '{consumer_id}' would "
            f"then run against exactly the state '{producer_id}' itself "
            f"received."
        )


def join_conflicts(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
) -> list[JoinConflict]:
    """
    Replays :mod:`librelane.flows.join`'s rule symbolically over a resolution.

    Parameters
    ----------
    spec : FlowSpec
        The document, for its graph and its ``final`` key.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs.
    enabled : Set[str]
        The jobs that will run. Pass every job id to ask the question of the
        graph rather than of a configuration, which is what the shipped
        documents' own guard does.

    Returns
    -------
    list[JoinConflict]
        One entry per unresolved conflict, in topological order.

    The rule this checks is the general one, of which "no OpenROAD-backed job
    has a concurrent peer" is only a proper subset:

        No job may rewrite a view or metric that a concurrent peer inherits from
        their common ancestor.

    ``join.py`` compares *values*, not declarations, so what matters per key is
    which job last wrote it on each incoming branch. This walks
    :func:`librelane.flows.spec_graph.topological_order` carrying exactly that --
    a ``key -> writing job`` map per token -- and flags any job whose
    predecessors disagree, plus the implicit join that forms the final state.

    Written as a replay rather than as a structural rule because
    ``spec_validation._check_fan_in_is_unambiguous`` is the structural rule and
    this is the class of defect it cannot see: it subtracts the shared ancestors
    before intersecting, so a key produced in the shared prefix and *re-produced*
    on exactly one exclusive branch gives an empty intersection and passes.

    Walks :meth:`~librelane.flows.spec.FlowSpec.collapsed_edges` rather than
    :meth:`~librelane.flows.spec.FlowSpec.edges`, so a ring's back edge -- a
    real cycle in the declared graph -- cannot reach
    :func:`~librelane.flows.spec_graph.topological_order`, which refuses one.
    ``jobs`` has to share that same collapsed node space for the walk to make
    sense at all, which is exactly what :func:`validate_selection` guarantees
    by folding every ring into one pseudo-job, keyed by its gate, before
    either of this module's two checks ever runs.
    """
    edges = spec.collapsed_edges()
    produced = produced_keys(jobs, enabled)

    conflicts: list[JoinConflict] = []
    carried: dict[str, dict[str, str]] = {}

    def merge(
        consumer: str, branches: list[str], source: Mapping[str, str]
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
                conflicts.append(JoinConflict(consumer, key, tuple(sorted(origins))))
            merged[key] = chosen[0] if chosen else sorted(origins)[0]
        return merged

    for job_id in topological_order(edges):
        job = jobs[job_id]
        state = merge(job_id, list(job.needs), job.source)
        for key in produced[job_id]:
            state[key] = job_id
        carried[job_id] = state

    if spec.final is None:
        needed = {need for job in jobs.values() for need in job.needs}
        sinks = [job_id for job_id in jobs if job_id not in needed]
        # No job's 'source' can settle a sink conflict, so an empty mapping is
        # not a simplification here: join_sink_states has none to read.
        merge(SINK_JOIN, sinks, {})

    return conflicts


def lost_views(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str] = frozenset(),
) -> list[LostView]:
    """
    The views this selection stopped producing that some job still requires.

    Parameters
    ----------
    spec : FlowSpec
        The document. Re-resolved here under no ``TOOLS`` at all, which is the
        baseline every verdict is measured against.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs, under the selection being validated.
    enabled : Set[str]
        The jobs that will run.
    initial_views : Set[str]
        The views the run's initial state supplies, which are available to every
        job because the state is the common ancestor of the whole graph. A view
        among them is not lost however thoroughly the selection stopped
        producing it: the run has it before its first job starts. Empty for a
        run given no initial state.

    Returns
    -------
    list[LostView]
        One entry per ``(job, view)`` pair that the document's own providers
        make available upstream of the job and neither the selected ones nor the
        initial state do, in document order.

    A differential rather than an absolute rule, for the reason this module's
    docstring gives: ``spec_validation`` presumes a view no job produces arrives
    in the initial state, and that presumption is what lets a document start
    mid-flow. Asking only what the *selection* removed needs no presumption at
    all, so nothing that loaded before this check existed stops loading because
    of it.

    Requirements include a registration's ``native_views``. A tool-native view
    such as OpenROAD's ``odb`` is exempt from the registration-time check
    precisely because it crosses job boundaries rather than being named in the
    job's tool-neutral ``requires``; this is where that exemption is answered
    for, over the steps a run actually resolved.

    Walks :meth:`~librelane.flows.spec.FlowSpec.collapsed_edges`, for the
    reason :func:`join_conflicts` gives: ``ancestors`` below cannot run over a
    graph with a real cycle in it.

    ``baseline`` below is **not** folded through a ring the way ``jobs`` is
    by :func:`validate_selection`'s caller: it is a fresh, untooled
    resolution used only to ask what the document's own providers could
    produce, and folding it would need this function to also accept
    ``rings`` and re-derive the same pseudo-jobs :func:`_fold_rings` already
    builds once, for a baseline that only ever *widens* what counts as
    ``recoverable`` below -- and this module's own docstring already prefers
    under-reporting to over-reporting. A non-gate ring member's own
    contribution to the baseline is therefore invisible here, which can only
    make a real lost view go unflagged, never flag one that is not; the same
    direction of imprecision :func:`_alternatives_that_work`'s unfolded
    remedy search below has, for the same reason.
    """
    edges = spec.collapsed_edges()
    baseline = resolve_jobs(spec)
    selected_views = _produced_views(jobs, enabled)
    baseline_views = _produced_views(baseline, enabled)

    lost: list[LostView] = []
    for job_id, job in jobs.items():
        if job_id not in enabled:
            continue
        upstream = ancestors(edges, job_id)
        available = _union(selected_views, upstream) | set(initial_views)
        recoverable = _union(baseline_views, upstream)
        for view in sorted(_required_views(job) - available):
            if view not in recoverable:
                continue
            producers = tuple(
                sorted(
                    other
                    for other in upstream
                    if view in baseline_views[other]
                    and view not in selected_views[other]
                )
            )
            lost.append(LostView(job_id, view, producers))
    return lost


def produced_keys(
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
) -> dict[str, set[str]]:
    """
    Every key each job writes, under the providers ``jobs`` resolved to.

    Parameters
    ----------
    jobs : Mapping[str, ResolvedJob]
        The resolved jobs.
    enabled : Set[str]
        The jobs that will run. A job outside it fires as a pass-through and
        writes nothing, so it is mapped to the empty set rather than dropped:
        the replay indexes every job.

    Returns
    -------
    dict[str, set[str]]
        Each job id mapped to every view id and metric name it writes. Views and
        metrics share one set because the join rule is one rule over both.

    Three sources, because no one of them is complete:

    * the job's resolved contract, which is its template's ``provides`` and
      ``metrics`` unioned with its selected registration's;
    * **every step's own ``outputs``**, which the contract does not cover. For a
      ``uses`` job the contract reads the *template*, so 19 of the ~46 jobs in
      each shipped document write views it cannot see -- ``odb`` and ``pnl``
      across the PNR chain, ``sdf`` and ``lib`` from the STA jobs, ``mag`` from
      ``magic_streamout``, ``spice`` from ``lvs``. Declaring less than you write
      is allowed (``Step.outputs`` is a permission, not an obligation), so the
      contract is a floor;
    * :data:`FRAMEWORK_METRICS`, if any step is OpenROAD-backed.

    Modelling only the first would make this a subset of the rule it exists to
    enforce, which is the mistake that produced two of the defects it now
    catches.

    The metric half stays incomplete and cannot be fixed here: steps carry no
    metric declaration at all, so an inline ``steps`` job is modelled as writing
    none. ``spec_validation._check_fan_in_is_unambiguous`` shares that blind
    spot.
    """
    produced: dict[str, set[str]] = {}
    for job_id, job in jobs.items():
        if job_id not in enabled:
            produced[job_id] = set()
            continue
        keys = {str(view) for view in job.provides} | set(job.metrics)
        for step in job.steps:
            keys.update(view.id for view in step.outputs)
        if any(issubclass(step, (OpenROADStep, OdbpyStep)) for step in job.steps):
            keys.update(FRAMEWORK_METRICS)
        produced[job_id] = keys
    return produced


def _produced_views(
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
) -> dict[str, set[str]]:
    """
    Returns
    -------
    dict[str, set[str]]
        The view half of :func:`produced_keys`. Kept apart because a metric is
        not a view: nothing declares a required metric, so the availability
        question is only ever asked of views.
    """
    produced: dict[str, set[str]] = {}
    for job_id, job in jobs.items():
        if job_id not in enabled:
            produced[job_id] = set()
            continue
        views = {str(view) for view in job.provides}
        for step in job.steps:
            views.update(view.id for view in step.outputs)
        produced[job_id] = views
    return produced


def _required_views(job: ResolvedJob) -> set[str]:
    """
    Returns
    -------
    set[str]
        Every view this job cannot start without: its template's ``requires``,
        or its steps' ``inputs`` when it lists them inline, plus its
        registration's ``native_views``.

        An optional input is satisfiable by absence, so it is not a requirement
        and does not appear. The flag lives on the view and ``str()`` reduces a
        view to its id, which an optional view shares with its base, so the flag
        has to be read before the set is built or it is gone.
    """
    required = {str(view) for view in job.requires if not view.optional}
    required.update(str(view) for view in job.native_views if not view.optional)
    return required


def _union(table: Mapping[str, set[str]], names: Set[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        result.update(table[name])
    return result


def _effective_tools(jobs: Mapping[str, ResolvedJob]) -> dict[str, str]:
    """
    Returns
    -------
    dict[str, str]
        The ``TOOLS`` mapping that reproduces ``jobs`` exactly: every job with a
        provider, mapped to the provider it resolved to. Written out in full
        rather than carried alongside, so that a remedy can re-resolve the
        document with one entry changed and everything else held fixed, without
        this module having to be told what the user originally wrote.
    """
    return {
        job_id: job.provider for job_id, job in jobs.items() if job.provider is not None
    }


def _alternatives_that_work(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str],
    job_id: str,
    rings: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """
    Parameters
    ----------
    spec : FlowSpec
        The document.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs, under the selection being refused, **unfolded**:
        one entry per original job, ring members included. Needed unfolded
        because :func:`_effective_tools` below reads every job's own
        provider off it, and a folded view has no entry at all for a
        non-gate ring member -- its provider would silently revert to the
        template's default in every candidate this function builds.
    enabled : Set[str]
        The jobs that will run. Unchanged by a provider swap: an ``if`` is the
        document's, and no registration contributes one.
    initial_views : Set[str]
        The views the run's initial state supplies. Also unchanged by a provider
        swap, and passed on for the same reason ``enabled`` is: a candidate is
        offered on the strength of coming out clean *for this run*, so it has to
        be measured under everything this run has. A provider that works only
        because the state carries the view it stopped producing is a provider
        that works.
    job_id : str
        The job to offer another provider for. Always a gate id or an
        ordinary job id, never a bare ring member: the folded jobs
        :func:`join_conflicts` and :func:`lost_views` actually replayed have
        no other kind of key to report a conflict or a lost view against.
    rings : Mapping[str, tuple[str, ...]]
        Every ring's gate id mapped to its members, so each re-resolved
        candidate can be folded the same way before it is checked --
        :func:`join_conflicts` needs its ``jobs`` to share
        :meth:`~librelane.flows.spec.FlowSpec.collapsed_edges`'s node space,
        the same requirement :func:`validate_selection` documents.

    Returns
    -------
    list[str]
        Every other registered provider of that job's template under which the
        whole document comes out clean, in registration order. Measured by
        re-running both checks rather than reasoned about, because "clean for
        this key" is not the same claim as "clean", and only the second one is
        worth printing.

        A provider whose registration is not
        :attr:`librelane.jobs.registry.Registration.runnable` is never offered,
        whatever the graph says about it. The sixteen commercial scaffolds are
        the case: once a caller imports
        :mod:`librelane.jobs.providers_vendor`, ``drc`` gains ``calibre``,
        ``icv`` and ``pegasus``, every one of which resolves and replays
        perfectly cleanly -- they contribute the right steps with the right
        contracts, and their ``run`` raises ``NotImplementedError``. Offering
        one as the fix for a rejected selection would send a reader from an
        error they could have acted on to one they cannot.

        Selecting a scaffold outright is still legal, and this function is not
        the place to change that: refusing to *recommend* an alternative is a
        statement about this message, and refusing to *permit* one would be a
        statement about the opt-in, which exists precisely so that those
        providers can be selected and filled in.
    """
    job = jobs[job_id]
    if job.provider is None:
        return []
    template_id = (spec.jobs[job_id].uses or job_id).partition("/")[0]
    tools = _effective_tools(jobs)
    working = []
    for provider in JobRegistry.providers(template_id):
        if provider == job.provider:
            continue
        registration = JobRegistry.get(template_id, provider)
        assert registration is not None, "providers() lists what get() answers for"
        if not registration.runnable:
            continue
        candidate = _fold_rings(
            spec, resolve_jobs(spec, {**tools, job_id: provider}), rings
        )
        if lost_views(spec, candidate, enabled, initial_views):
            continue
        if join_conflicts(spec, candidate, enabled):
            continue
        working.append(provider)
    return working


def _remedies(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str],
    swappable: Set[str],
    gateable: Set[str],
    rings: Mapping[str, tuple[str, ...]],
) -> str:
    """
    Parameters
    ----------
    spec : FlowSpec
        The document.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs, unfolded -- see :func:`_alternatives_that_work`,
        which is the one place in this call chain that needs them that way.
    enabled : Set[str]
        The jobs that will run.
    initial_views : Set[str]
        The views the run's initial state supplies, for the provider search to
        measure its candidates under.
    swappable : Set[str]
        The jobs whose provider is the thing to change.
    gateable : Set[str]
        The jobs whose absence from the run would settle it. Not the same set:
        for two jobs colliding on a key, dropping either one settles it, but for
        a view a selection stopped producing, dropping the *producer* changes
        nothing and dropping the *consumer* is the answer.
    rings : Mapping[str, tuple[str, ...]]
        Every ring's gate id mapped to its members, threaded through to
        :func:`_alternatives_that_work`.

    Returns
    -------
    str
        One clause per remedy: each provider that works, and each ``if``
        variable that would take a job out of the run. The second kind is
        offered because it is the real answer for the shipped near-miss --
        ``{"drc": "klayout"}`` migrates to ``RUN_MAGIC_DRC: false``, not to a
        ``TOOLS`` entry -- and the empty string when neither kind exists, so a
        message never trails off into an empty list.

    The two kinds are held to different standards, which is worth stating
    because they read alike in the output. A provider remedy is *measured*:
    the document is re-resolved under it, both checks are re-run, and it is
    dropped if it is not runnable. A gating remedy is *enumerated*: every
    configuration variable in the job's ``if`` is listed, because any one of
    them being false removes the job, which settles a collision by
    construction and settles a lost view whenever the consumer is what is
    dropped. A runtime (``metric::``) term is not offered here: nobody can
    "set" a metric comparison the way a configuration variable is set, so it
    names nothing a caller could act on. Nothing re-runs the checks for it,
    so a gating remedy is a claim about this failure and not, as a provider
    remedy is, about the whole document.
    """
    lines = []
    for job_id in sorted(swappable):
        for provider in _alternatives_that_work(
            spec, jobs, enabled, initial_views, job_id, rings
        ):
            lines.append(f"set TOOLS['{job_id}'] to '{provider}'")
    for job_id in sorted(gateable):
        for condition in config_terms(jobs[job_id].conditions):
            lines.append(
                f"set '{condition}' to false, which takes '{job_id}' out of the run"
            )
    if not lines:
        return ""
    return " Remedies: " + "; ".join(lines) + "."


def _conflict_message(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str],
    conflict: JoinConflict,
    rings: Mapping[str, tuple[str, ...]],
) -> str:
    where = (
        "the final state of the flow"
        if conflict.consumer == SINK_JOIN
        else f"job '{conflict.consumer}'"
    )
    origins = " and ".join(f"'{origin}'" for origin in conflict.origins)
    return (
        f"Flow '{spec.name}' cannot run the selected providers: jobs {origins} "
        f"both write '{conflict.key}' and the graph runs them concurrently, so "
        f"{where} would receive two values for it and "
        f"librelane.flows.join has no rule for choosing. The run would stop "
        f"with a JoinConflictError."
        + _remedies(
            spec,
            jobs,
            enabled,
            initial_views,
            set(conflict.origins),
            set(conflict.origins),
            rings,
        )
    )


def _lost_view_message(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str],
    lost: LostView,
    rings: Mapping[str, tuple[str, ...]],
) -> str:
    producers = " and ".join(f"'{producer}'" for producer in lost.producers)
    return (
        f"Flow '{spec.name}' cannot run the selected providers: job "
        f"'{lost.consumer}' requires view '{lost.view}', which the document's "
        f"own providers produce in {producers} and the selected ones produce "
        f"nowhere before it. The run would stop at the first step reaching for "
        f"it."
        + _remedies(
            spec,
            jobs,
            enabled,
            initial_views,
            set(lost.producers),
            {lost.consumer},
            rings,
        )
    )
