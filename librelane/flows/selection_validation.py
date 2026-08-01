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

from collections.abc import Mapping, Set
from dataclasses import dataclass

from librelane.jobs import JobRegistry, JobResolutionError
from librelane.state import State
from librelane.steps.odb.base import OdbpyStep
from librelane.steps.openroad.base import OpenROADStep

from librelane.flows.job import ResolvedJob, resolve_jobs
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
) -> None:
    """
    Refuses a provider selection this document cannot run.

    Parameters
    ----------
    spec : FlowSpec
        The document, for its graph, its name and its ``final`` key.
    jobs : Mapping[str, ResolvedJob]
        Its jobs as :func:`librelane.flows.job.resolve_jobs` resolved them,
        under the ``TOOLS`` selection being validated.
    enabled : Set[str]
        The ids of the jobs whose ``if`` conditions this configuration makes
        true. A job outside it fires as a pass-through and writes nothing.
    initial_views : Set[str]
        The views this run's initial state supplies, from
        :func:`supplied_views`. Empty for a run given no initial state, which is
        what makes that run's verdicts exactly the ones it got before this
        module could be told about a state.

    Raises
    ------
    JobResolutionError
        If the selection removes a view some enabled job requires, or puts two
        writers of one key on branches the graph runs concurrently. The message
        names the key or view, the jobs involved, and every provider that would
        work instead.
    """
    lost = lost_views(spec, jobs, enabled, initial_views)
    if lost:
        raise JobResolutionError(
            _lost_view_message(spec, jobs, enabled, initial_views, lost[0])
        )
    conflicts = join_conflicts(spec, jobs, enabled)
    if conflicts:
        raise JobResolutionError(
            _conflict_message(spec, jobs, enabled, initial_views, conflicts[0])
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
    """
    edges = spec.edges()
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
    """
    edges = spec.edges()
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
) -> list[str]:
    """
    Parameters
    ----------
    spec : FlowSpec
        The document.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs, under the selection being refused.
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
        The job to offer another provider for.

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
        candidate = resolve_jobs(spec, {**tools, job_id: provider})
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
) -> str:
    """
    Parameters
    ----------
    spec : FlowSpec
        The document.
    jobs : Mapping[str, ResolvedJob]
        Its resolved jobs.
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
    variable in the job's ``if`` is listed, because any one of them being false
    removes the job, which settles a collision by construction and settles a
    lost view whenever the consumer is what is dropped. Nothing re-runs the
    checks for it, so a gating remedy is a claim about this failure and not,
    as a provider remedy is, about the whole document.
    """
    lines = []
    for job_id in sorted(swappable):
        for provider in _alternatives_that_work(
            spec, jobs, enabled, initial_views, job_id
        ):
            lines.append(f"set TOOLS['{job_id}'] to '{provider}'")
    for job_id in sorted(gateable):
        for condition in jobs[job_id].conditions:
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
        )
    )


def _lost_view_message(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    enabled: Set[str],
    initial_views: Set[str],
    lost: LostView,
) -> str:
    producers = " and ".join(f"'{producer}'" for producer in lost.producers)
    return (
        f"Flow '{spec.name}' cannot run the selected providers: job "
        f"'{lost.consumer}' requires view '{lost.view}', which the document's "
        f"own providers produce in {producers} and the selected ones produce "
        f"nowhere before it. The run would stop at the first step reaching for "
        f"it."
        + _remedies(
            spec, jobs, enabled, initial_views, set(lost.producers), {lost.consumer}
        )
    )
