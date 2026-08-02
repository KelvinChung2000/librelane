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
"""The engine that runs a workflow document on a Petri net."""

import os
import pathlib
import shutil
import textwrap
from collections.abc import Iterable, Mapping, Sequence, Set
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional, Union

from loguru import logger
from rapidfuzz import fuzz, process, utils

from librelane.common import Filter, get_tpe, slugify
from librelane.config import (
    AnyConfig,
    AnyConfigs,
    Config,
    Variable,
    universal_flow_config_variables,
    variable,
)
from librelane.jobs import JobContractError, JobRegistry, extract_tools
from librelane.state import State
from librelane.steps import DeferredStepError, Step, StepError, StepException
from librelane.flows.explanation import (
    Explanation,
    JobDisposition,
    VariableDisposition,
)
from librelane.flows.flow import Flow, FlowError, FlowException
from librelane.flows.job import ResolvedJob, ToolSelection, resolve_jobs
from librelane.flows import predicates
from librelane.flows.join import join_sink_states, join_states
from librelane.flows.net import Net
from librelane.flows.resources import ResourcePools
from librelane.flows.resume import resume_key, reusable_state, write_entry
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_graph import ancestors, descendants, topological_order
from librelane.flows.selection_validation import validate_selection
from librelane.flows.spec_validation import validate_against_registry


#: The loader's resolved configuration, under a second name. ``Workflow``
#: declares a nested ``Config`` of its own -- the engine's variable model -- so
#: an annotation written in its class body resolves to that one, and a method
#: returning resolved configurations has to say which ``Config`` it means.
_ResolvedConfig = Config

#: How many job ids an error message spells out before it counts the rest.
#: ``classic.yaml`` declares 48 jobs, and a message that prints all of them
#: buries the one sentence the reader can act on under a paragraph they cannot.
_MAX_LISTED_JOBS = 10


def _listed(names: Iterable[str]) -> str:
    """
    Parameters
    ----------
    names : Iterable[str]
        The job ids to name.

    Returns
    -------
    str
        Every id when there are few enough to read, and otherwise the first
        :data:`_MAX_LISTED_JOBS` of them followed by a count of what was left
        out. Sorted, because a set has no order worth showing.
    """
    ordered = sorted(names)
    if len(ordered) <= _MAX_LISTED_JOBS:
        return str(ordered)
    return f"{ordered[:_MAX_LISTED_JOBS]} and {len(ordered) - _MAX_LISTED_JOBS} more"


def _declaring_class(step: type[Step], name: str) -> str:
    """
    Parameters
    ----------
    step : type[Step]
        A step whose ``config_vars`` carries the variable.
    name : str
        The variable's name.

    Returns
    -------
    str
        The name of the class ``step`` gets the variable from, which is the
        least derived class in its MRO whose ``config_vars`` still carries it.

        A step's ``config_vars`` is derived from its nested ``Config`` model
        and a model inherits its base's fields, so every class below the
        declaring one carries the variable too. The last one going up the
        hierarchy that still has it is therefore the one that declared it.

        Named by step ID where the class has one. An abstract base such as
        ``OpenROADStep`` has none, and is named by its class name, which is
        what the hierarchy calls it.
    """
    declaring: type[Step] | None = None
    for ancestor in step.__mro__:
        if not issubclass(ancestor, Step):
            continue
        if any(declared.name == name for declared in ancestor.config_vars):
            declaring = ancestor
    assert declaring is not None, (
        f"'{name}' is not declared anywhere in '{step.id}', which is only "
        f"reachable if the caller asked about a variable the step does not "
        f"read. Please report this as a bug."
    )
    return declaring.id if declaring.id is not NotImplemented else declaring.__name__


def _document_help_md(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    myst_anchors: bool,
) -> str:
    """
    Renders a workflow document's help as Markdown.

    Parameters
    ----------
    spec : FlowSpec
        The document. Supplies the name, the description, the declared
        configuration variables and each job's ``uses``.
    jobs : Mapping[str, ResolvedJob]
        The document's resolved jobs. Supplies each job's selected provider
        and its steps.
    myst_anchors : bool
        Emit MyST anchors and cross-references, for the documentation build.
        Off for terminal output.

    Returns
    -------
    str
        The rendered Markdown.
    """
    anchor = f"(flow-{slugify(spec.name, lower=True)})=" if myst_anchors else ""
    # Dedented before the description is interpolated, not after: a document's
    # description may be several lines, and a dedent measured over the
    # interpolated text would find no common indent and leave the template's
    # own indentation in the output.
    result = textwrap.dedent(
        """\
        {anchor}
        ### {name}

        {description}

        #### Using from the CLI

        ```sh
        librelane --flow {name} [...]
        ```

        #### Importing

        ```python
        from librelane.flows import Flow
        from librelane.flows.engine import Workflow

        {name} = Flow.factory.get("{name}")
        ```
        """
    ).format(anchor=anchor, name=spec.name, description=spec.description)

    # The engine's own variables ahead of the document's, exactly as
    # Workflow.__init__ composes the two, because a document's accepted
    # configuration is the union and not either half. TOOLS is the whole of the
    # engine's half and no document declares it, so a table built from
    # spec.config alone would leave every reader of the Jobs section below --
    # which tells them to set TOOLS -- with nowhere on the page to learn its
    # shape. Reading the class attribute rather than a literal keeps the two
    # lists one list.
    config_vars = [
        *Workflow.config_vars,
        *(declared.to_variable() for declared in spec.config),
    ]
    if config_vars:
        if myst_anchors:
            result += f"\n({slugify(spec.name, lower=True)}-config-vars)=\n"
        result += "\n#### Flow-specific Configuration Variables\n"
        result += Variable._render_table_md(
            config_vars,
            myst_anchor_owner_id=spec.name if myst_anchors else None,
        )
        result += "\n"

    result += "\n#### Jobs\n\n"
    result += (
        "Set the `TOOLS` configuration variable to change the tool used for "
        "any of these. The key is the job id in the left-hand column. See "
        "[Swapping Tools](../usage/swapping_tools.md).\n\n"
    )
    result += "| Job | Template | Provider | Alternatives |\n"
    result += "| --- | --- | --- | --- |\n"
    for job_id, job in jobs.items():
        if job.provider is None:
            result += f"| `{job_id}` | inline steps | | |\n"
            continue
        # '(uses or job_id)' is not a fallback: it is the document's implicit
        # rule spelled out, that a job declaring neither 'uses' nor 'steps'
        # means the template its own id names, which _require_implementation
        # has already checked.
        template_id = (spec.jobs[job_id].uses or job_id).partition("/")[0]
        # The selected provider is not an alternative to itself, so the last
        # column is every other registration for the same template -- what a
        # TOOLS entry for this job could name instead.
        others = [
            provider
            for provider in JobRegistry.providers(template_id)
            if provider != job.provider
        ]
        others_cell = ", ".join(f"`{name}`" for name in others) if others else "none"
        result += (
            f"| `{job_id}` | `{template_id}` | `{job.provider}` | {others_cell} |\n"
        )

    result += "\n#### Included Steps\n\n"
    for job_id, job in jobs.items():
        result += f"* `{job_id}`\n"
        for step in job.steps:
            implementation = step.get_implementation_id()
            if myst_anchors:
                result += (
                    f"  * [`{step.id}`](./step_config_vars.md#step-"
                    f"{slugify(implementation, lower=True)})\n"
                )
            elif implementation != step.id:
                result += f"  * `{step.id}` (implementation: `{implementation}`)\n"
            else:
                result += f"  * `{step.id}`\n"
    return result


class _ReproducibleCreated(Exception):
    """
    Raised by a worker once it has written a reproducible, so that the job
    unwinds the way an error does without being one.

    It never leaves :meth:`Workflow.run`. A private control-flow exception
    reaching the CLI would be reported as a flow failure, which is the opposite
    of what happened.

    Parameters
    ----------
    path
        Where the reproducible was written.
    state
        The state the named step would have consumed. It is also the run's
        final state: the run stopped there, so the last thing it knows about
        the design is what that step was about to be handed.
    """

    def __init__(self, path: pathlib.Path, state: State) -> None:
        super().__init__(f"Wrote a reproducible to '{path}'.")
        self.path = path
        self.state = state


@dataclass(frozen=True)
class _RunPlan:
    """
    What the run-shaping options select, once they have been composed and
    checked against one another.

    Held apart from :meth:`Workflow.run` so that :meth:`Workflow.explain` can
    describe the same invocation rather than a second, similar one. Every
    refusal these options carry is raised while the plan is built, so an
    explanation raises wherever the run would: an explanation of an invocation
    that cannot happen is worse than no explanation.

    Parameters
    ----------
    selected
        The jobs the run is restricted to, closed under ``needs``.
    skipped
        The jobs ``--skip`` named, all of them inside :attr:`selected`.
    forced
        The jobs that must ignore any reusable result: the ones
        ``--invalidate`` named and their selected descendants.
    reproducible_at
        The job and step index ``--reproducible`` resolved to, or ``None``.
    """

    selected: set[str]
    skipped: set[str]
    forced: set[str]
    reproducible_at: tuple[str, int] | None


@dataclass
class _InFlight:
    """
    One submitted job, and everything its worker writes down about it.

    The record belongs to this submission rather than to the run, so a worker
    shares nothing with another worker or with the main thread. The main thread
    merges it into the run's lists and totals when the future resolves, which is
    also what keeps a deferral a fact about *this* job: a single shared list's
    length, compared before and after, cannot say which job appended to it once
    two jobs run at once. The same argument is why the two counts are per-record
    and summed here rather than being one shared integer each worker increments,
    which is a read-modify-write and would lose counts under concurrency.

    Parameters
    ----------
    name
        The job's id.
    steps
        Every step the job constructed, in the order it ran them.
    deferred
        The message of every error a step of this job deferred.
    reused
        How many steps resolved from a previous run instead of running.
    executed
        How many steps ran. A step that deferred an error ran, so it is counted
        here.
    """

    name: str
    steps: list[Step] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    reused: int = 0
    executed: int = 0


@dataclass
class _SweepProgress:
    """
    One sweep job's ``N`` concurrent pass executions, tracked from submission
    until every one of them has resolved.

    Each pass is its own future, submitted with its own :class:`_InFlight`
    record, so that :meth:`Workflow.run`'s ``wait()`` loop -- which already
    routes one resolved future to one record -- needs no second code path to
    learn a pass finished. What it needs instead is somewhere to hold the
    passes that *have* finished until the last one has, since nothing about
    the sweep -- winner, contract, deferred errors -- can be decided from
    fewer than all of them. This is that somewhere, keyed by the sweep job's
    id in :meth:`Workflow.run`'s local ``sweeps`` mapping.

    Parameters
    ----------
    job
        The sweep job's id.
    expected
        How many passes this sweep declared (``len(job.iterations)``).
    results
        Each pass index (1-based) that finished without raising, mapped to
        its output state.
    errors
        Each pass index that raised, mapped to what it raised.
    records
        Each pass index mapped to its own :class:`_InFlight` record, for
        merging steps, reuse and execution counts into the run's totals once
        the sweep settles -- and, for the winning pass only, its deferred
        errors too.
    """

    job: str
    expected: int
    results: dict[int, State] = field(default_factory=dict)
    errors: dict[int, BaseException] = field(default_factory=dict)
    records: dict[int, _InFlight] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Whether every pass this sweep declared has resolved, one way or the other."""
        return len(self.results) + len(self.errors) == self.expected


@dataclass
class _ParkedJob:
    """
    One ordinary job -- never a ring, see below -- admitted onto the net (its
    input tokens already consumed and joined, its stage already started) but
    not yet given a worker, because :meth:`ResourcePools.try_acquire` could
    not grant its ``resources`` the moment it was checked.

    Retried on every later scheduler wake by :meth:`Workflow._admit_parked`,
    never by blocking the scheduling thread: a parked job holds its tokens
    but no pool slot, so it can neither stall the run nor deadlock against
    anything else waiting, only wait for some running job's completion to
    free a slot.

    A ring never parks here. Its pool use is per member per pass, acquired
    with a *blocking* call from inside its own single worker submission
    (:meth:`Workflow._run_loop`), not admitted from the scheduling thread at
    all -- see that method's own acquire/release wrapping.

    Parameters
    ----------
    job
        The job to run once admitted.
    state_in
        The state its first step consumes.
    submitted
        Its record, created once whether or not parking turns out to be
        needed, so a job's directory-of-record and step list are the same
        either way.
    forced
        As :meth:`Workflow._run_job`.
    """

    job: ResolvedJob
    state_in: State
    submitted: _InFlight
    forced: bool


@dataclass
class _ParkedSweepPass:
    """
    One sweep execution admitted onto the net but not yet given a worker, for
    the same reason and under the same retry rule as :class:`_ParkedJob`.

    A sweep's ``N`` passes are admitted independently -- one
    :meth:`ResourcePools.try_acquire` per pass at fan-out, in
    :meth:`Workflow.run` -- rather than once for the whole sweep, so a
    two-seat pool runs a five-point sweep two passes at a time rather than
    admitting it as one all-or-nothing unit.

    Parameters
    ----------
    job
        The sweep job.
    state_in
        The state every pass reads from, identical across all ``N`` of them.
    submitted
        This pass's own record.
    forced
        As :meth:`Workflow._run_job`.
    pass_index
        This pass's 1-based index.
    config
        This pass's own resolved configuration, i.e.
        ``iteration_configs[(job.id, pass_index)]``.
    """

    job: ResolvedJob
    state_in: State
    submitted: _InFlight
    forced: bool
    pass_index: int
    config: _ResolvedConfig


class Workflow(Flow):
    """
    Runs a :class:`librelane.flows.spec.FlowSpec`.

    Parameters
    ----------
    spec
        The document to run. Validated against the registries here, so
        a document constructed in Python gets the same checks a loaded one does.
    config
        As :meth:`librelane.flows.Flow.__init__`.
    config_override_strings
        As :meth:`librelane.flows.Flow.__init__`. Read twice, once here for
        ``TOOLS`` and once by the loader, for the reason given on
        :mod:`librelane.jobs.tools`.
    initial_views
        The views the state this flow will be started with already supplies, as
        :func:`librelane.flows.selection_validation.supplied_views` reads them
        off it. Only the *availability* question needs them, which is why this
        is a view set and not the state: the state itself belongs to
        :meth:`librelane.flows.Flow.start`, which is given it as
        ``with_initial_state``, and construction has no use for its paths.

        A caller that starts a flow from a state and does not say so here gets
        the verdicts of a run starting from nothing, which is a refusal its run
        would not have earned.
    """

    class Config(Flow.Config):
        TOOLS: Optional[dict[str, Union[str, list[str]]]] = variable(
            None,
            description=(
                "A mapping from job id to the provider (tool) implementing "
                "it, for example {'synthesis': 'yosys_vhdl'}. The key is the "
                "id the document gives the job, which is not always the id of "
                "the stage it uses: classic.yaml runs the 'streamout' stage "
                "under 'magic_streamout' and 'klayout_streamout'. Only "
                "overrides need listing; an unnamed job uses the provider its "
                "'uses' key names. Must be a literal mapping, as it is read "
                "before the configuration preprocessor runs, and so cannot "
                "come from the PDK's own configuration files -- though a "
                "design may scope it per process by writing it inside a "
                "'pdk::' or 'scl::' section, which selection expands."
            ),
        )

    def __init__(
        self,
        spec: FlowSpec,
        config: AnyConfigs,
        *,
        config_override_strings: Sequence[str] | None = None,
        initial_views: Set[str] = frozenset(),
        **kwargs,
    ) -> None:
        validate_against_registry(spec)
        self.spec = spec
        #: Every ring's gate id mapped to its members, in pass order (starting
        #: at the gate's intra-ring successor, ending at the gate). Set before
        #: anything below that reads it: ``_enabled_jobs``, ``validate_selection``
        #: and the two config-resolution passes all need it.
        self.rings = spec.rings()
        #: Every ring member (the gate included) mapped to its own gate id, the
        #: inverse of :attr:`rings` flattened one level, because most of what
        #: follows asks "which ring, if any, is this job part of" rather than
        #: "what are this ring's members".
        self.member_of = {
            member: gate for gate, members in self.rings.items() for member in members
        }
        self.jobs = resolve_jobs(
            spec,
            self._selected_tools(config, config_override_strings, kwargs),
        )
        self.Steps = [step for job in self.jobs.values() for step in job.steps]
        # Flow.__init__ builds the Config from get_all_config_variables(), which
        # reads Steps and config_vars; resolves the flow name from the class
        # when the instance has not set one; and layers 'values' into the
        # loader's sources. All four assignments must precede it.
        #
        # The class's own variables come first, because TOOLS is declared by
        # the engine and by no document: assigning only the document's would
        # leave it out of the model the configuration is validated against, and
        # a configuration that set it would be an unknown key.
        self.config_vars = [
            *type(self).config_vars,
            *(declared.to_variable() for declared in spec.config),
        ]
        self.name = spec.name
        self.values = dict(spec.values)
        super().__init__(
            config,
            config_override_strings=config_override_strings,
            **kwargs,
        )
        # After super().__init__ and before anything else, because it is the
        # first thing that can be asked once self.config exists and the answer
        # decides whether this flow can run at all. It needs all three: the
        # providers, which resolve_jobs settled above; the gating, which is a
        # question about the configuration the loader has only just resolved;
        # and the initial state's views, which the caller has because the state
        # is read before a flow is built.
        # librelane.flows.selection_validation's docstring is where the reasons
        # neither gating nor the initial state can be skipped are written down.
        # 'rings' is passed so that module folds each ring into one pseudo-job
        # before it reasons about the graph -- see its own docstring for why
        # that has to happen there and not here.
        validate_selection(
            spec, self.jobs, self._enabled_jobs(), initial_views, rings=self.rings
        )
        #: One resolved configuration per job that declares a ``with`` block.
        self.job_configs = self._resolve_job_configs(
            config,
            config_override_strings,
            kwargs,
        )
        #: ``(member, pass)`` -> that pass's configuration, for every member of
        #: every ring whose gate declares ``iterations``. Built by the same
        #: mechanism a sweep job's own schedule will use, keyed by the job that
        #: declares the schedule rather than by ring membership.
        self.iteration_configs = self._resolve_iteration_configs(
            config,
            config_override_strings,
            kwargs,
        )
        #: Named resource pools this flow's jobs may contend for. Empty
        #: (never ``None``) when the document declares no ``resources``, so
        #: every acquisition site below calls it unconditionally rather than
        #: checking for its absence first.
        self.pools = self._resolve_resource_pools()

    def _resolve_resource_pools(self) -> ResourcePools:
        """
        Resolves ``self.spec.resources`` into concrete capacities.

        Returns
        -------
        ResourcePools
            One counter per declared pool. A literal capacity is used as
            given: :meth:`~librelane.flows.spec.FlowSpec._check_resource_pool_literal_capacities`
            already refused one below 1 when the document was loaded. A
            capacity naming a configuration variable is read off
            ``self.config``, which by now holds it as an ``int`` --
            :func:`librelane.flows.spec_validation._check_resource_variable_capacities_are_declared_ints`
            already refused a variable not declared with type ``int``.

        Raises
        ------
        FlowException
            If a variable capacity resolves to a value below 1, naming the
            pool, the variable and the resolved value. A pool nothing can
            ever enter is a flow that stalls by declaration, and this is the
            one case only a resolved configuration can know about: a literal
            capacity below 1 is already a load-time error, ahead of this
            point.
        """
        resolved: dict[str, int] = {}
        for pool, capacity in self.spec.resources.items():
            if isinstance(capacity, int):
                resolved[pool] = capacity
                continue
            value = self.config[capacity]
            if value < 1:
                raise FlowException(
                    f"Resource pool '{pool}' declares capacity "
                    f"'{capacity}', which resolves to {value}. A pool's "
                    f"capacity must be at least 1; a pool nothing can ever "
                    f"enter is a flow that stalls by declaration."
                )
            resolved[pool] = value
        return ResourcePools(resolved)

    def _resolve_job_configs(
        self,
        config: AnyConfigs,
        config_override_strings: Sequence[str] | None,
        load_kwargs: Mapping[str, Any],
    ) -> dict[str, _ResolvedConfig]:
        """
        Resolves one configuration per job that declares a ``with`` block.

        Parameters
        ----------
        config : AnyConfigs
            The design configuration, exactly as it was handed to
            ``Flow.__init__``, because the job's values have to be layered into
            the *sources* rather than onto the resolved result: a job's ``with``
            beats the document's and the PDK's, and loses to the design's and to
            ``--config-override``. Only the loader knows which of those supplied
            a given value.
        config_override_strings : Sequence[str] | None
            As :meth:`librelane.flows.Flow.__init__`.
        load_kwargs : Mapping[str, Any]
            The remaining keyword arguments ``Flow.__init__`` received; the
            process selection is read out of it.

        Returns
        -------
        Each job whose ``with`` block is non-empty mapped to its own
        configuration. A job that sets nothing is absent, and
        :meth:`_run_job` hands it ``self.config``.

        There is deliberately no single flattened mapping. The covering rule
        that ``librelane.flows.spec_validation`` enforces is not a uniqueness
        rule -- two Yosys jobs may set different ``SYNTH_STRATEGY`` values --
        so where the feature is used at all, no one mapping can hold what the
        document means.

        Raises
        ------
        FlowException
            If a document with a per-job ``with`` is constructed over an
            already-resolved :class:`librelane.config.Config`. Its sources are
            gone, so the layer cannot be built, and running the job against the
            flow's configuration would discard values the document asked for
            without saying so.
        """
        job_configs: dict[str, _ResolvedConfig] = {}
        for job_id, job in self.spec.jobs.items():
            if not job.values:
                continue
            if isinstance(config, Config):
                raise FlowException(
                    f"Job '{job_id}' of flow '{self.spec.name}' declares a "
                    f"'with' block, but this flow was constructed from a "
                    f"configuration that is already resolved, whose sources "
                    f"are no longer available to layer it into. Pass the "
                    f"design's configuration file or mapping instead."
                )
            resolved, _ = Config.load(
                config_in=config,
                flow_config_vars=self.get_all_config_variables(),
                # Two layers rather than one merged mapping: the job overrides
                # the document, anything neither sets still comes from the
                # document, and each key is attributed to whichever of the two
                # wrote it.
                flow_values=self.values,
                job_values=(job_id, job.values),
                config_override_strings=config_override_strings,
                pdk=load_kwargs.get("pdk"),
                pdk_root=load_kwargs.get("pdk_root"),
                scl=load_kwargs.get("scl"),
                pad=load_kwargs.get("pad"),
                design_dir=str(self.design_dir),
            )
            job_configs[job_id] = resolved
        return job_configs

    def _resolve_iteration_configs(
        self,
        config: AnyConfigs,
        config_override_strings: Sequence[str] | None,
        load_kwargs: Mapping[str, Any],
    ) -> dict[tuple[str, int], _ResolvedConfig]:
        """
        Resolves one configuration per pass, for every ring member of a
        schedule-gated ring and for every ``mode: sweep`` job.

        Parameters
        ----------
        config : AnyConfigs
            As :meth:`_resolve_job_configs`.
        config_override_strings : Sequence[str] | None
            As :meth:`librelane.flows.Flow.__init__`.
        load_kwargs : Mapping[str, Any]
            As :meth:`_resolve_job_configs`.

        Returns
        -------
        ``(job, k)`` (1-based) mapped to that pass's configuration: for every
        member of every ring whose gate schedules, keyed by the member; for
        every sweep job, keyed by the job itself, since a sweep is declared
        on a single job with no ring around it at all. A ring gated by
        ``max`` instead contributes no entries: no pass changes any value, so
        every member of it keeps reading :attr:`job_configs` or
        :attr:`config` on every pass, exactly as a job outside any ring does.

        Keyed by the job that declares ``iterations`` -- the ring's gate, or
        the sweep job itself -- and not by ring membership, which is what
        lets both shapes share one dictionary and one resolution loop below.

        Raises
        ------
        FlowException
            If a gate or a sweep job with a non-empty ``iterations`` is
            constructed over an already-resolved
            :class:`librelane.config.Config`, for the same reason
            :meth:`_resolve_job_configs` refuses one for a ``with`` block: an
            iteration entry has to layer into the sources, and a resolved
            configuration no longer has any.
        """
        configs: dict[tuple[str, int], _ResolvedConfig] = {}
        for gate, members in self.rings.items():
            gate_spec = self.spec.jobs[gate]
            if not gate_spec.iterations:
                continue
            if isinstance(config, Config):
                raise FlowException(
                    f"The ring gated by '{gate}' of flow '{self.spec.name}' "
                    f"declares 'iterations', but this flow was constructed "
                    f"from a configuration that is already resolved, whose "
                    f"sources are no longer available to layer the schedule "
                    f"into. Pass the design's configuration file or mapping "
                    f"instead."
                )
            for member in members:
                member_spec = self.spec.jobs[member]
                job_values = (
                    (member, member_spec.values) if member_spec.values else None
                )
                for k, entry in enumerate(gate_spec.iterations, start=1):
                    resolved, _ = Config.load(
                        config_in=config,
                        flow_config_vars=self.get_all_config_variables(),
                        flow_values=self.values,
                        job_values=job_values,
                        iteration_values=(gate, k, entry),
                        config_override_strings=config_override_strings,
                        pdk=load_kwargs.get("pdk"),
                        pdk_root=load_kwargs.get("pdk_root"),
                        scl=load_kwargs.get("scl"),
                        pad=load_kwargs.get("pad"),
                        design_dir=str(self.design_dir),
                    )
                    configs[(member, k)] = resolved
        for job_id, job_spec in self.spec.jobs.items():
            if job_spec.mode != "sweep" or not job_spec.iterations:
                continue
            if isinstance(config, Config):
                raise FlowException(
                    f"Sweep job '{job_id}' of flow '{self.spec.name}' "
                    f"declares 'iterations', but this flow was constructed "
                    f"from a configuration that is already resolved, whose "
                    f"sources are no longer available to layer the schedule "
                    f"into. Pass the design's configuration file or mapping "
                    f"instead."
                )
            job_values = (job_id, job_spec.values) if job_spec.values else None
            for k, entry in enumerate(job_spec.iterations, start=1):
                resolved, _ = Config.load(
                    config_in=config,
                    flow_config_vars=self.get_all_config_variables(),
                    flow_values=self.values,
                    job_values=job_values,
                    iteration_values=(job_id, k, entry),
                    config_override_strings=config_override_strings,
                    pdk=load_kwargs.get("pdk"),
                    pdk_root=load_kwargs.get("pdk_root"),
                    scl=load_kwargs.get("scl"),
                    pad=load_kwargs.get("pad"),
                    design_dir=str(self.design_dir),
                )
                configs[(job_id, k)] = resolved
        return configs

    @staticmethod
    def _selected_tools(
        config: AnyConfigs,
        config_override_strings: Sequence[str] | None,
        load_kwargs: Mapping[str, Any],
    ) -> Mapping[str, ToolSelection]:
        """
        Parameters
        ----------
        config : AnyConfigs
            The design configuration, exactly as ``Flow.__init__`` will receive
            it.
        config_override_strings : Sequence[str] | None
            As :meth:`librelane.flows.Flow.__init__`.
        load_kwargs : Mapping[str, Any]
            The remaining keyword arguments this constructor received. The
            process selection is read out of it and handed to the pre-pass,
            because a ``pdk::`` or ``scl::`` section's ``TOOLS`` is scoped to
            the process, and ``--pdk``, ``--scl`` and ``--pdk-root`` are how a
            run names one without writing it into the configuration. Passing
            them past this method into ``super().__init__``, as it once did,
            left selection matching those sections against a process it could
            not see.

        Returns
        -------
        The ``TOOLS`` mapping, taken straight from an already-resolved
        configuration, or read out of the raw sources by the pre-pass.

        The pre-pass exists because the step set has to be known before the
        configuration can be validated, since the steps declare the variables.
        A document fixes the *job* set at load, not the step set: ``TOOLS``
        re-points a job at another provider, whose registration is a different
        step sequence declaring different variables. So the circularity is the
        same one, and this runs before ``super().__init__``.
        """
        if isinstance(config, Config):
            # Already validated, so TOOLS is present and typed -- and its
            # sections were expanded on the way, by the same
            # Config.expand_sources the pre-pass below runs, so this branch has
            # nothing left to resolve. Checked before Mapping, which a resolved
            # Config also satisfies.
            return dict(config.get("TOOLS") or {})
        # One source or a layered sequence of them, split the way
        # Config.load splits the same argument, so the pre-pass reads exactly
        # the sources the loader will.
        sources: list[AnyConfig]
        if isinstance(config, (Mapping, str, os.PathLike)):
            sources = [config]
        else:
            sources = list(config)
        return extract_tools(
            sources,
            config_override_strings=config_override_strings,
            design_dir=load_kwargs.get("design_dir"),
            pdk=load_kwargs.get("pdk"),
            pdk_root=load_kwargs.get("pdk_root"),
            scl=load_kwargs.get("scl"),
            pad=load_kwargs.get("pad"),
        )

    # An instance method, because a document's step list, its providers and its
    # per-job structure are facts about the resolved jobs, which no class
    # attribute has. Flow used to declare a classmethod of this name, rendering
    # help from its class docstring and its Steps; phase 5 deleted it, so this
    # is the only renderer left.
    def get_help_md(self, myst_anchors: bool = False) -> str:
        """
        Parameters
        ----------
        myst_anchors : bool
            Emit MyST anchors and cross-references.

        Returns
        -------
        str
            Rendered Markdown help for this workflow, describing the jobs it
            actually resolved, so a ``TOOLS`` override is visible in the
            provider column.
        """
        return _document_help_md(self.spec, self.jobs, myst_anchors)

    @staticmethod
    def help_md_for_document(spec: FlowSpec, myst_anchors: bool = False) -> str:
        """
        Renders a document's help without constructing a workflow.

        Parameters
        ----------
        spec : FlowSpec
            The document to describe.
        myst_anchors : bool
            Emit MyST anchors and cross-references.

        Returns
        -------
        str
            Rendered Markdown help, describing the providers the document
            declares. A configuration is not needed and is not read, so
            ``TOOLS`` plays no part.
        """
        validate_against_registry(spec)
        return _document_help_md(spec, resolve_jobs(spec), myst_anchors)

    def run(
        self,
        initial_state: State,
        target: Iterable[str] | None = None,
        invalidate: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
        reproducible: str | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        Parameters
        ----------
        initial_state : State
            The state deposited on every source place.
        target : Iterable[str] | None
            Run only these jobs and their transitive ancestors. ``None`` runs
            the whole graph.
        invalidate : Iterable[str] | None
            Treat these jobs and their transitive descendants as having no
            reusable result.
        skip : Iterable[str] | None
            Job ids to fire as pass-through without running.
        reproducible : str | None
            Write a reproducible for this step, named either ``<step id>`` or
            ``<job id>/<step id>``, instead of running it. The step's job and
            its ancestors run, and nothing else does.

        Returns
        -------
        ``(final_state, steps_run)``. Under ``reproducible`` the final state is
        the one the named step would have consumed, because the run stopped
        there.

        Raises
        ------
        FlowException
            If any named job is not declared, or lies outside the ``target``
            subgraph; if ``target`` and ``reproducible`` are given together,
            because both say what should run; if ``reproducible`` names a step
            of a job ``skip`` names or a false condition stops, so that this
            run would never execute it; or if it resolves to no step at all or
            to more than one.
        """
        edges = self.spec.collapsed_edges()
        plan = self._plan(edges, target, invalidate, skip, reproducible)

        # 'selected' is member-space (a ring's non-gate members included), so
        # it is intersected with 'edges' own collapsed node space -- a ring's
        # gate id standing in for the whole ring -- rather than iterated
        # directly: a bare member id is not a node this net has, only its
        # gate is. 'selected' is closed under 'needs' either way -- ancestors()
        # is the transitive closure of it -- so dropping the unselected keys
        # cannot leave a dangling predecessor behind, and every remaining
        # 'needs' list is already a list of selected (collapsed) jobs.
        collapsed_selected = set(edges) & plan.selected
        net = Net(
            list(collapsed_selected),
            {
                name: needs
                for name, needs in edges.items()
                if name in collapsed_selected
            },
        )
        for arc in net.arcs:
            if arc.producer is None:
                net.put(arc, initial_state)

        self.progress_bar.set_max_stage_count(len(collapsed_selected))
        steps_run: list[Step] = []
        deferred: list[str] = []
        failures: list[str] = []
        reused_count = 0
        executed_count = 0
        outputs: dict[str, State] = {}
        pending: dict[Future[State], _InFlight] = {}
        #: Every pending future that is one pass of a sweep, mapped to which
        #: sweep job and which pass. Sweep passes still live in ``pending``
        #: too -- one future, one ``_InFlight``, exactly as an ordinary job's
        #: does -- so ``wait()`` needs no second collection to block on; this
        #: is only how a resolved future is told apart from an ordinary job's
        #: once ``wait()`` returns it.
        sweep_futures: dict[Future[State], tuple[str, int]] = {}
        #: Every sweep job currently awaiting its remaining passes, keyed by
        #: job id. An entry is removed the moment its last pass resolves,
        #: whether the sweep goes on to settle cleanly or to fail.
        sweeps: dict[str, _SweepProgress] = {}
        #: Every future currently in ``pending`` that holds a resource pool
        #: grant, mapped to the names it holds -- an ordinary job's or a
        #: sweep pass's own ``resources``. A ring's one future never appears
        #: here: its pool use is internal to ``_run_loop``, acquired and
        #: released per member per pass. Popped and released in the
        #: ``finally`` of whichever branch below settles the future, so a
        #: slot is returned on every exit path, success or failure.
        future_resources: dict[Future[State], tuple[str, ...]] = {}
        #: Ordinary jobs whose tokens are consumed but whose pools were full
        #: the moment they were checked. Retried by ``_admit_parked`` on
        #: every scheduler wake, ahead of ``net.enabled()``.
        parked_jobs: list[_ParkedJob] = []
        #: Sweep passes parked for the same reason, one entry per pass.
        parked_sweep_passes: list[_ParkedSweepPass] = []

        # The marking is not thread-safe and is not made so: every call into
        # `net` below happens on this thread. A lock would exist only to
        # protect one dictionary from a scheduler that has no reason to
        # contend for it, so the net is consumed before a job is submitted and
        # fired after its future resolves, and the workers never see it.
        while True:
            fired_pass_through = False
            # Ahead of 'net.enabled()' and unconditional on 'failures': a
            # parked job or sweep pass was already selected to run before
            # anything failed -- its tokens are consumed -- so it is drained
            # like the rest of 'pending' rather than abandoned, and only the
            # *enabling* of new work below stops once something has failed.
            self._admit_parked(
                parked_jobs,
                parked_sweep_passes,
                plan,
                pending,
                sweep_futures,
                future_resources,
            )
            if not failures:
                for name in net.enabled():
                    # Everything between taking the tokens and handing the job
                    # to the pool can raise on this thread: join_states raises
                    # JoinConflictError, the condition read raises if the
                    # document names a variable the config does not carry, and
                    # net.fire raises NetError, which is a bare RuntimeError.
                    # Letting any of them out would unwind through the progress
                    # bar's end() and the ExitStack owning this run's loguru
                    # sinks while jobs were still running: those jobs would go
                    # on writing into runs/<tag>/ with their sinks already torn
                    # down, and the CLI would hang at exit on the non-daemon
                    # pool. A scheduling error is collected exactly like an
                    # error the job itself raises.
                    started = False
                    try:
                        ring_members = self.rings.get(name)
                        if ring_members is None:
                            job = self.jobs[name]
                            tokens = self._tokens_for(net, job)
                            state_in = join_states(tokens, job.source, name)
                            self.progress_bar.start_stage(name)
                            started = True
                            reason = self._pass_through_reason(
                                job, name in plan.skipped
                            )
                            if reason is None:
                                reason = self._runtime_pass_through_reason(
                                    job, state_in
                                )
                            if reason is not None:
                                logger.info(f"Skipping job '{name}': {reason}.")
                                net.fire(name, state_in)
                                outputs[name] = state_in
                                self.progress_bar.end_stage()
                                fired_pass_through = True
                                continue
                            if job.mode == "sweep":
                                # Fan-out happens here, on this thread, never
                                # inside a worker: a worker blocked waiting on
                                # its own children would deadlock a saturated
                                # pool the moment every thread is one of those
                                # workers. The tokens were already consumed
                                # and joined once, above -- every pass reads
                                # the identical 'state_in' -- and start_stage
                                # already ran once, above too, so the N
                                # futures below are this one stage, not N of
                                # them; end_stage is deferred to settlement.
                                n = len(job.iterations)
                                sweeps[name] = _SweepProgress(name, n)
                                for k in range(1, n + 1):
                                    pass_submitted = _InFlight(f"{name} (pass {k})")
                                    pass_config = self.iteration_configs[(name, k)]
                                    # Each pass is admitted on its own, not
                                    # once for the whole sweep, so a two-seat
                                    # pool runs a five-point sweep two passes
                                    # at a time rather than all five or none.
                                    if self.pools.try_acquire(job.resources):
                                        future = get_tpe().submit(
                                            self._execute_steps,
                                            job,
                                            state_in,
                                            pass_submitted,
                                            name in plan.forced,
                                            plan.reproducible_at,
                                            pass_index=k,
                                            config=pass_config,
                                        )
                                        pending[future] = pass_submitted
                                        sweep_futures[future] = (name, k)
                                        future_resources[future] = job.resources
                                    else:
                                        parked_sweep_passes.append(
                                            _ParkedSweepPass(
                                                job,
                                                state_in,
                                                pass_submitted,
                                                name in plan.forced,
                                                k,
                                                pass_config,
                                            )
                                        )
                                continue
                            submitted = _InFlight(name)
                            # Pool admission is the last decision on this
                            # thread, after every pass-through check: a
                            # pass-through acquires nothing because it runs
                            # nothing, and this point is reached only for a
                            # job that is genuinely about to run.
                            if self.pools.try_acquire(job.resources):
                                future = get_tpe().submit(
                                    self._run_job,
                                    job,
                                    state_in,
                                    submitted,
                                    name in plan.forced,
                                    plan.reproducible_at,
                                )
                                pending[future] = submitted
                                future_resources[future] = job.resources
                            else:
                                parked_jobs.append(
                                    _ParkedJob(
                                        job, state_in, submitted, name in plan.forced
                                    )
                                )
                        else:
                            # A ring's collapsed node: 'name' is the gate id.
                            # An 'if' on the gate is the one place a ring
                            # joins across every member's external tokens at
                            # once, to decide whether the whole loop instance
                            # fires as a single pass-through -- --skip can
                            # never name a member here, checked in _plan, so
                            # 'name in plan.skipped' is always False and kept
                            # only for symmetry with the ordinary path above.
                            gate = name
                            gate_job = self.jobs[gate]
                            member_tokens = self._tokens_for_ring(
                                net, gate, ring_members
                            )
                            flattened: dict[str, State] = {}
                            for member_external in member_tokens.values():
                                flattened.update(member_external)
                            gate_check_state = join_states(
                                flattened, gate_job.source, gate
                            )
                            self.progress_bar.start_stage(gate)
                            started = True
                            reason = self._pass_through_reason(
                                gate_job, gate in plan.skipped
                            )
                            if reason is None:
                                reason = self._runtime_pass_through_reason(
                                    gate_job, gate_check_state
                                )
                            if reason is not None:
                                logger.info(
                                    f"Skipping loop gated by '{gate}': {reason}."
                                )
                                net.fire(gate, gate_check_state)
                                outputs[gate] = gate_check_state
                                self.progress_bar.end_stage()
                                fired_pass_through = True
                                continue
                            submitted = _InFlight(gate)
                            pending[
                                get_tpe().submit(
                                    self._run_loop,
                                    gate,
                                    ring_members,
                                    member_tokens,
                                    submitted,
                                    gate in plan.forced,
                                )
                            ] = submitted
                    except Exception as e:
                        failures.append(f"Job '{name}': {e}")
                        # Only if it started. The token read and the input
                        # join run before start_stage, and ending a job that
                        # never started would count a completion the bar never
                        # announced.
                        if started:
                            self.progress_bar.end_stage()
                        # Stop enabling, like any other failure. The tokens this
                        # job consumed are gone, so it cannot become enabled
                        # again and cannot be scheduled twice.
                        break
            if fired_pass_through:
                # net.enabled() was a snapshot. A pass-through just enabled its
                # descendants, and they are not in it. Sweeping again cannot
                # loop forever, because net.fired only grows and is bounded by
                # the job count.
                continue
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                finished = pending.pop(future)
                sweep_key = sweep_futures.pop(future, None)
                if sweep_key is not None:
                    job_id, k = sweep_key
                    progress = sweeps[job_id]
                    progress.records[k] = finished
                    try:
                        progress.results[k] = future.result()
                    except _ReproducibleCreated as created:  # pragma: no cover
                        # Structurally unreachable: _resolve_reproducible
                        # refuses --reproducible on a sweep job before _plan
                        # ever builds a reproducible_at that could name one,
                        # so no sweep pass's _execute_steps call is ever
                        # handed one to raise this over.
                        raise AssertionError(
                            f"sweep pass {k} of '{job_id}' wrote a "
                            f"reproducible, which --reproducible refuses "
                            f"for a sweep job before this point"
                        ) from created
                    except Exception as e:
                        progress.errors[k] = e
                    finally:
                        # Each pass releases its own grant the moment it
                        # resolves, independent of whether the sweep as a
                        # whole has settled: a two-seat pool holds a
                        # five-point sweep to two *concurrent* passes, not to
                        # two passes total, so a finished pass's seat is what
                        # lets a still-parked one start.
                        self.pools.release(future_resources.pop(future, ()))
                    if not progress.complete:
                        continue
                    del sweeps[job_id]
                    # Unconditional, exactly as an ordinary job's own record
                    # merges into these same totals before its try/except
                    # below: every pass's steps and reuse/execution counts
                    # are real regardless of whether the sweep as a whole
                    # goes on to settle cleanly.
                    for pass_k in sorted(progress.records):
                        steps_run.extend(progress.records[pass_k].steps)
                    reused_count += sum(
                        record.reused for record in progress.records.values()
                    )
                    executed_count += sum(
                        record.executed for record in progress.records.values()
                    )
                    try:
                        winner_state = self._settle_sweep(job_id, progress, deferred)
                        net.fire(job_id, winner_state)
                    except Exception as e:
                        failures.append(f"Job '{job_id}': {e}")
                    else:
                        outputs[job_id] = winner_state
                    finally:
                        self.progress_bar.end_stage()
                    continue
                steps_run.extend(finished.steps)
                deferred.extend(finished.deferred)
                reused_count += finished.reused
                executed_count += finished.executed
                try:
                    state_out = future.result()
                    # A job that deferred an error did not complete, so its
                    # output contract is not a meaningful thing to assert: the
                    # deferring step's views are missing precisely because it
                    # failed. Checking anyway would raise JobContractError and
                    # the deferred errors collected below would never surface,
                    # replacing the real diagnosis with a misleading one. The
                    # question is asked of this job's own deferrals, because a
                    # sibling deferring at the same time says nothing about
                    # whether this job honoured its contract.
                    if not finished.deferred:
                        self._check_contract(self.jobs[finished.name], state_out)
                    net.fire(finished.name, state_out)
                except _ReproducibleCreated as created:
                    # Returning from the middle of the loop abandons no worker.
                    # --reproducible restricted the graph to the named job and
                    # its ancestors, and a job is enabled only once every one
                    # of its predecessors has fired, so by the time this job
                    # was even submitted nothing else was left to run.
                    assert not pending, (
                        "a reproducible unwound while "
                        f"{sorted(other.name for other in pending.values())} "
                        "were still running"
                    )
                    logger.success(f"Wrote a reproducible to '{created.path}'.")
                    # Before the deferred raise, for the reason the ordinary
                    # path puts it there, and on this path at all because the
                    # run stopped: what it knows about the design is worth
                    # writing down either way.
                    self._save_final_snapshot(created.state)
                    if deferred:
                        # The reproducible is written either way, and the
                        # message above says so, but an ancestor that deferred
                        # an error still failed and dropping it here would be
                        # the silent failure --reproducible was moved onto the
                        # engine to avoid.
                        raise FlowError(
                            "One or more deferred errors were encountered:\n"
                            + "\n".join(deferred)
                        ) from None
                    return created.state, steps_run
                except Exception as e:
                    # Collected rather than raised, because raising here would
                    # abandon the jobs still running and hide a second,
                    # independent failure, which is exactly the information
                    # wanted when several jobs run at once. Every exception,
                    # not just FlowError: net.fire raises NetError, which is a
                    # bare RuntimeError, and abandoning the pool is the one
                    # outcome this loop exists to prevent.
                    failures.append(f"Job '{finished.name}': {e}")
                else:
                    outputs[finished.name] = state_out
                finally:
                    # Popped rather than looked up, and defaulted to (): a
                    # ring's own future never entered 'future_resources' at
                    # all (its pool use is internal to '_run_loop'), so this
                    # is a no-op release for it, exactly as an empty
                    # 'resources' tuple is for a job that names no pool.
                    self.pools.release(future_resources.pop(future, ()))
                    self.progress_bar.end_stage()

        if failures:
            raise FlowError("\n".join(failures))
        # A failure leaves its descendants unfired, so this must come second:
        # otherwise a genuine failure would be reported as a stall. 'net' is
        # the restricted net, so the question is whether every *selected* job
        # fired: a job --target excluded is not a node of it and cannot stall
        # it.
        if not net.is_complete():
            raise FlowException(
                f"Flow '{self.spec.name}' stalled: no job is enabled and "
                f"{sorted(net.stalled())} never ran."
            )

        # Ahead of the deferred raise, unlike the two checks above. A run that
        # failed or stalled has no final state to speak of, but a deferred
        # error is by definition one the run continued past, so it produced
        # views worth snapshotting. What follows is then in that order:
        # snapshot, raise, report, and a run that is about to fail therefore
        # never announces that it reused anything or that it is complete.
        final = self._final_state(net, outputs, plan.selected)
        self._save_final_snapshot(final)

        if deferred:
            raise FlowError(
                "One or more deferred errors were encountered:\n" + "\n".join(deferred)
            )

        if reused_count:
            logger.info(
                f"Reused {reused_count} step(s) from a previous run; "
                f"executed {executed_count}."
            )
        logger.success("Flow complete.")
        return final, steps_run

    def explain(
        self,
        *,
        target: Iterable[str] | None = None,
        invalidate: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
        reproducible: str | None = None,
        variables: bool = False,
    ) -> Explanation:
        """
        Parameters
        ----------
        target : Iterable[str] | None
            As :meth:`run`.
        invalidate : Iterable[str] | None
            As :meth:`run`.

            No row changes because of it: it says a cached result may not be
            reused, and reuse is the one verdict an explanation does not report.
            It is taken all the same, because :meth:`run` refuses a name it
            cannot place and an explanation that accepted one would be
            describing an invocation that cannot happen.
        skip : Iterable[str] | None
            As :meth:`run`.
        reproducible : str | None
            As :meth:`run`. It restricts the graph exactly as ``target`` does,
            to the named step's job and that job's ancestors, so every other
            job is reported as excluded by it.
        variables : bool
            Also report every configuration variable, its value, the layer that
            supplied it and the jobs that can read it.

            This selects a second table rather than filtering the first, which
            is what ``--explain-variables`` is on the command line. It is asked
            for rather than always answered because it is a materially larger
            question than which jobs run -- Classic resolves some 800 variables
            against 48 jobs -- and a caller that wants to know why one job is
            missing should not pay for it. Answering it also requires a
            configuration resolved against this flow's own variable list, which
            a caller holding a narrower one does not have.

            Nothing is filtered when it *is* asked: every variable gets a row,
            defaults included, because a variable sitting at its default is
            exactly what somebody debugging an unexpected value is looking for.

        Returns
        -------
        Explanation
            One entry per job the document declares, in topological order,
            stating whether the job will run under this configuration and
            these arguments, and if not, which mechanism excluded it.

            Every declared job gets an entry, including the ones that will not
            run. A job missing from the run is the question this is asked, so
            reporting only the jobs that will run would answer everything
            except it.

        Raises
        ------
        FlowException
            Wherever :meth:`run` would refuse the same arguments, which is
            every condition listed there. An explanation that answered where
            the run would raise would be describing an invocation that cannot
            happen, so the two share one derivation of what the arguments
            select rather than each deriving their own.

        Resume is deliberately not reported. A resume verdict depends on
        content fingerprints of files that later jobs in the same run will
        rewrite, so it cannot be known before the run.
        """
        edges = self.spec.collapsed_edges()
        plan = self._plan(edges, target, invalidate, skip, reproducible)
        reproducible_job = (
            plan.reproducible_at[0] if plan.reproducible_at is not None else None
        )

        dispositions: list[JobDisposition] = []
        for collapsed_id in topological_order(edges):
            ring_members = self.rings.get(collapsed_id)
            # One row per member, in pass order, for a ring; one row for an
            # ordinary job. Every branch below is written once and applies to
            # each id in 'row_ids' uniformly, because every fact this method
            # reports about a ring -- whether it is in the target subgraph,
            # whether its gate's 'if' stops it -- is a fact about the whole
            # loop instance, not about one member.
            row_ids = ring_members if ring_members is not None else (collapsed_id,)
            for job_id in row_ids:
                job = self.jobs[job_id]
                needs = tuple(job.needs)
                if collapsed_id not in plan.selected:
                    # Which option narrowed the graph, and not merely that it
                    # was narrowed. --reproducible restricts it without
                    # --target having been passed at all, and naming --target
                    # there would send a reader looking for an option they
                    # never used.
                    if reproducible_job is not None:
                        dispositions.append(
                            JobDisposition(
                                job_id,
                                needs,
                                False,
                                f"--reproducible runs only '{reproducible_job}' "
                                f"and its ancestors",
                                "not-in-reproducible",
                            )
                        )
                    else:
                        dispositions.append(
                            JobDisposition(
                                job_id,
                                needs,
                                False,
                                "not in the --target subgraph",
                                "not-in-target",
                            )
                        )
                    continue
                if ring_members is not None:
                    gate = collapsed_id
                    gate_job = self.jobs[gate]
                    # A ring member can never itself be named by --skip
                    # (refused in _plan) or by --reproducible (refused in
                    # _resolve_reproducible), so only the gate's own
                    # configuration term can stop the whole loop instance
                    # before it starts, exactly as it does in run().
                    gate_reason = self._pass_through_reason(gate_job, skipped=False)
                    if gate_reason is not None:
                        dispositions.append(
                            JobDisposition(
                                job_id, needs, False, gate_reason, "condition"
                            )
                        )
                        continue
                    bound = len(gate_job.iterations) or gate_job.max_passes
                    loop_reason = (
                        f"gate of the loop, at most {bound} passes"
                        if job_id == gate
                        else f"loop gated by '{gate}', at most {bound} passes"
                    )
                    dispositions.append(
                        JobDisposition(job_id, needs, True, loop_reason, "loop")
                    )
                    continue
                # The same call the run makes, so the two cannot disagree about
                # which variable stopped a job or how its absence is worded.
                reason = self._pass_through_reason(job, job_id in plan.skipped)
                if reason is not None:
                    mechanism = "skip" if job_id in plan.skipped else "condition"
                    dispositions.append(
                        JobDisposition(job_id, needs, False, reason, mechanism)
                    )
                    continue
                if plan.reproducible_at is not None and job_id == reproducible_job:
                    # Reached only for a job that is neither skipped nor
                    # stopped by a condition: the plan refuses a reproducible
                    # for one that is, because this run would never execute
                    # the step.
                    dispositions.append(
                        self._reproducible_disposition(
                            job, needs, plan.reproducible_at[1]
                        )
                    )
                    continue
                runtime_terms = predicates.metric_terms(job.conditions)
                if runtime_terms:
                    # --skip and a false configuration term are decided now,
                    # and both already took the two 'continue's above; a
                    # runtime term is not decided until the run reads the
                    # job's actual input state, so the job counts as enabled
                    # here -- the same optimistic reading _enabled_jobs gives
                    # it -- and this row says so rather than claiming the
                    # answer either way.
                    terms_text = " and ".join(
                        f"metric::{term.metric} {term.op} {term.literal}"
                        for term in runtime_terms
                    )
                    dispositions.append(
                        JobDisposition(
                            job_id,
                            needs,
                            True,
                            f"runtime term(s) {terms_text} are decided at run "
                            f"time against the job's input state",
                            "condition (runtime)",
                        )
                    )
                    continue
                if job.mode == "sweep":
                    assert job.select is not None, (
                        "spec.py requires 'select' on every sweep job"
                    )
                    metric, direction = job.select
                    dispositions.append(
                        JobDisposition(
                            job_id,
                            needs,
                            True,
                            f"sweep of {len(job.iterations)} points, keeps "
                            f"{metric} {direction}",
                            None,
                        )
                    )
                    continue
                dispositions.append(
                    JobDisposition(job_id, needs, True, "will run", None)
                )
        return Explanation(
            jobs=tuple(dispositions),
            variables=self._variable_dispositions() if variables else (),
        )

    def _reproducible_disposition(
        self, job: ResolvedJob, needs: tuple[str, ...], step_index: int
    ) -> JobDisposition:
        """
        Parameters
        ----------
        job : ResolvedJob
            The job whose step ``--reproducible`` named.
        needs : tuple[str, ...]
            Its declared incoming edges, for the row.
        step_index : int
            The named step's index in the job's step list.

        Returns
        -------
        JobDisposition
            What this job does under ``--reproducible``. It is the one job that
            neither runs in full nor is excluded: the steps ahead of the named
            one run, the named one is packaged instead of run, and the run
            stops there. ``will_run`` is therefore true only when some step of
            it runs, which is exactly when the named step is not its first.
        """
        step_id = job.steps[step_index].id
        if step_index == 0:
            return JobDisposition(
                job.id,
                needs,
                False,
                f"--reproducible packages its first step '{step_id}', so no "
                f"step of this job runs",
                "reproducible",
            )
        return JobDisposition(
            job.id,
            needs,
            True,
            f"will run up to '{step_id}', which --reproducible packages "
            f"instead of running",
            "reproducible",
        )

    def _variable_dispositions(self) -> tuple[VariableDisposition, ...]:
        """
        Returns
        -------
        tuple[VariableDisposition, ...]
            One entry per configuration variable this flow resolves, in the
            order :meth:`librelane.flows.Flow.get_all_config_variables` returns
            them, and one further entry for each additional value the jobs
            reading a variable resolved it to.

            Read off the *resolved* jobs and not off the document, so that a
            ``TOOLS`` selection re-pointing a job at another provider is
            reflected in what that job is reported to read.

            Not narrowed by ``--target``, ``--skip`` or ``--reproducible``.
            Which jobs *can* read a variable is a property of the document and
            the configuration, and an invocation that runs fewer of them does
            not change it. So a ``reach`` here may name a job the job table on
            the same screen reports as excluded; the two answer different
            questions and neither is wrong.
        """
        universal = {member.name for member in universal_flow_config_variables}
        readers: dict[str, list[str]] = {}
        declarers: dict[str, set[str]] = {}
        for job_id, job in self.jobs.items():
            for step in job.steps:
                for declared in step.config_vars:
                    readers.setdefault(declared.name, []).append(job_id)
                    declarers.setdefault(declared.name, set()).add(
                        _declaring_class(step, declared.name)
                    )

        every_job = tuple(self.jobs)
        dispositions: list[VariableDisposition] = []
        for declared in self.get_all_config_variables():
            is_universal = declared.name in universal
            reach = (
                every_job
                if is_universal
                # dict.fromkeys deduplicates while keeping declaration order: a
                # job's steps commonly declare one variable more than once.
                else tuple(dict.fromkeys(readers.get(declared.name, [])))
            )
            declaring = declarers.get(declared.name, set())
            for value, origin, group in self._resolutions(declared.name, reach):
                dispositions.append(
                    VariableDisposition(
                        name=declared.name,
                        value=value,
                        origin=origin,
                        universal=is_universal,
                        reach=group,
                        # A universal variable is readable by every step
                        # whatever any class declares, so no class explains its
                        # reach even if some step declares it as well.
                        declared_by=(
                            next(iter(declaring))
                            if len(declaring) == 1 and not is_universal
                            else None
                        ),
                    )
                )
        return tuple(dispositions)

    def _resolutions(
        self, name: str, reach: tuple[str, ...]
    ) -> list[tuple[Any, str, tuple[str, ...]]]:
        """
        Parameters
        ----------
        name : str
            The variable to resolve.
        reach : tuple[str, ...]
            The jobs that can read it.

        Returns
        -------
        list[tuple[Any, str, tuple[str, ...]]]
            Each distinct value the jobs in ``reach`` resolved the variable to
            with the source that supplied it and the jobs that see it, in
            first-seen order.

            One entry for every variable no job's ``with`` block overrides,
            which is every variable of every shipped document, because a job
            that declares no ``with`` reads the flow's own configuration. Two
            when two jobs set it differently, which is what a per-job ``with``
            is for.

            A variable no job reads is answered by the flow's configuration
            alone, reaching nothing: ``TOOLS`` and the variables a job's ``if``
            names are read by the engine before any job exists to read them.

            A member of a ring whose gate schedules (:meth:`_iteration_bound`
            answers non-``None``) is resolved pass by pass, against
            :attr:`iteration_configs` rather than :attr:`job_configs`, because
            that is the configuration each pass actually runs under. If every
            pass resolves ``name`` identically -- true for every variable the
            schedule does not name -- this reports one ordinary entry, exactly
            as a non-ring job's does, rather than the same row repeated once
            per pass. Only a variable the schedule actually changes expands
            into one entry per distinct value, each reached by
            ``"<job> (pass <k>)"`` rather than by the bare job id, so
            ``--explain-variables`` attributes a scheduled value to the pass
            that set it -- the promise the design spec makes for it.
        """

        def resolved_at(config: _ResolvedConfig) -> tuple[Any, str]:
            return (config[name], config.provenance.get(name, "default"))

        groups: list[tuple[Any, str, list[str]]] = []

        def add(resolved: tuple[Any, str], label: str) -> None:
            for value, origin, group in groups:
                if (value, origin) == resolved:
                    group.append(label)
                    return
            groups.append((*resolved, [label]))

        for job_id in reach:
            bound = self._iteration_bound(job_id)
            if bound is None:
                # A job that declares no 'with' block has no configuration of
                # its own, exactly as in _run_job.
                add(resolved_at(self.job_configs.get(job_id, self.config)), job_id)
                continue
            per_pass = [
                resolved_at(self.iteration_configs[(job_id, k)])
                for k in range(1, bound + 1)
            ]
            if all(item == per_pass[0] for item in per_pass):
                add(per_pass[0], job_id)
                continue
            for k, resolved in enumerate(per_pass, start=1):
                add(resolved, f"{job_id} (pass {k})")
        if not groups:
            return [
                (self.config[name], self.config.provenance.get(name, "default"), ())
            ]
        return [(value, origin, tuple(group)) for value, origin, group in groups]

    def _iteration_bound(self, job_id: str) -> int | None:
        """
        Returns
        -------
        The pass bound for ``job_id``, if it schedules: a sweep job with a
        non-empty ``iterations`` (every sweep does, load-time-required), or a
        member of a ring whose gate declares one -- meaning its true per-pass
        configuration lives in :attr:`iteration_configs` rather than
        :attr:`job_configs`. ``None`` for an ordinary job and for a member of
        a ``max``-gated ring, where no pass changes any value and
        :attr:`job_configs` already answers correctly for every pass.
        """
        job = self.jobs[job_id]
        if job.mode == "sweep" and job.iterations:
            return len(job.iterations)
        gate = self.member_of.get(job_id)
        if gate is None:
            return None
        gate_job = self.jobs[gate]
        if not gate_job.iterations:
            return None
        return len(gate_job.iterations)

    def _plan(
        self,
        edges: dict[str, list[str]],
        target: Iterable[str] | None,
        invalidate: Iterable[str] | None,
        skip: Iterable[str] | None,
        reproducible: str | None,
    ) -> _RunPlan:
        """
        Composes the run-shaping options into the selection they describe.

        Parameters
        ----------
        edges : dict[str, list[str]]
            This document's job dependency map.
        target : Iterable[str] | None
            As :meth:`run`.
        invalidate : Iterable[str] | None
            As :meth:`run`.
        skip : Iterable[str] | None
            As :meth:`run`.
        reproducible : str | None
            As :meth:`run`.

        Returns
        -------
        _RunPlan
            What this invocation would run. :meth:`run` executes it and
            :meth:`explain` describes it, from this one derivation, because two
            derivations could disagree about what an invocation does and the
            explanation would be the one nobody could check.

        Raises
        ------
        FlowException
            Wherever the invocation itself is refused; :meth:`run` lists the
            conditions.
        """
        # They compose in a fixed order: --target restricts the graph first,
        # and --skip and --invalidate then apply within the restriction.
        # Naming a job outside it is an error rather than a silent no-op,
        # because the option would otherwise do nothing at all and say nothing
        # about it.
        selected = self._target_subgraph(edges, target)
        restricted_by = "--target"

        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")
        self._reject_skipped_ring_members(skipped)
        invalidated = set(invalidate or ())
        self._require_declared(sorted(invalidated), "--invalidate")

        # After --skip is read, because a request for a step this run would
        # never execute is refused against it, and before the subgraph check
        # below, because --reproducible narrows the subgraph the check is made
        # against.
        reproducible_at: tuple[str, int] | None = None
        if reproducible is not None:
            if target is not None:
                raise FlowException(
                    "--reproducible and --target both say what should run. "
                    "--reproducible already runs the named step's job and its "
                    "ancestors, so drop --target."
                )
            job_id, step_index = self._resolve_reproducible(reproducible)
            # Ahead of every skip test, so that a request for a step this
            # configuration would never execute is diagnosed rather than
            # silently discarded.
            if job_id in skipped:
                raise FlowException(
                    f"Cannot create a reproducible for a step of job "
                    f"'{job_id}': it is named by --skip, so this run would "
                    f"never execute it. Drop it from --skip, or name another "
                    f"step."
                )
            reason = self._pass_through_reason(self.jobs[job_id], skipped=False)
            if reason is not None:
                raise FlowException(
                    f"Cannot create a reproducible for a step of job "
                    f"'{job_id}': {reason}, so this configuration would never "
                    f"execute it. Name another step, or change the condition."
                )
            # The spec says --reproducible is unchanged in meaning and runs the
            # ancestors of the step's job, which is exactly what --target does,
            # so it reuses the restriction rather than adding a second one.
            selected = {job_id} | ancestors(edges, job_id)
            reproducible_at = (job_id, step_index)
            restricted_by = "--reproducible"

        self._reject_outside(skipped | invalidated, selected, restricted_by)

        # Forwards only. A cache entry is invalid because its inputs are not
        # the ones it was written from -- an edited TCL script, a rebuilt tool
        # -- and that is a statement about the named job and everything fed by
        # it. An ancestor's entry is untouched by it, and re-running ancestors
        # would make --invalidate an expensive way to spell --overwrite.
        #
        # 'forced' stays in collapsed-id space (a ring's gate id, never a bare
        # member id): a ring runs as one worker submission, so there is no way
        # to force only one of its members, and the scheduling loop only ever
        # checks a collapsed node's id against it.
        forced: set[str] = set()
        for name in invalidated:
            gate = self.member_of.get(name, name)
            forced.add(gate)
            forced |= descendants(edges, gate) & selected

        return _RunPlan(selected, skipped, forced, reproducible_at)

    def _target_subgraph(
        self, edges: dict[str, list[str]], target: Iterable[str] | None
    ) -> set[str]:
        """
        Parameters
        ----------
        edges : dict[str, list[str]]
            This document's collapsed job dependency map: one node per ring,
            keyed by its gate id, and one per ordinary job.
        target : Iterable[str] | None
            The jobs ``--target`` named, or ``None`` for the whole graph. Any
            ring member -- gate or not -- is mapped to its gate id before the
            ancestor walk, because ``edges`` has no node for a bare member.

        Returns
        -------
        The named jobs and their transitive ancestors, re-expanded so that
        every member of a selected ring is present individually (this is a
        *member*-space result, unlike ``edges``): :meth:`explain` reports one
        row per member, and :meth:`_reject_outside` has to recognise a bare
        member name a caller wrote for ``--skip`` or ``--invalidate`` as
        inside the subgraph its ring belongs to. Every job when nothing was
        named, which is already member-space and needs no expansion. Called
        from :meth:`_plan`, which :meth:`run` and :meth:`explain` share,
        because an explanation that drew a different subgraph from the run it
        describes would be worse than no explanation.

        Raises
        ------
        FlowException
            If any named job is not declared.
        """
        if target is None:
            return set(self.jobs)
        targets = list(target)
        self._require_declared(targets, "--target")
        selected: set[str] = set()
        for name in targets:
            gate = self.member_of.get(name, name)
            selected.add(gate)
            selected |= ancestors(edges, gate)
        return self._expand_rings(selected)

    def _expand_rings(self, collapsed_ids: set[str]) -> set[str]:
        """
        Returns
        -------
        ``collapsed_ids``, with every ring's gate id also standing for its
        other members: a set of collapsed node ids in, a set of individual
        job ids out.
        """
        expanded = set(collapsed_ids)
        for node in collapsed_ids:
            members = self.rings.get(node)
            if members is not None:
                expanded.update(members)
        return expanded

    def _reject_skipped_ring_members(self, skipped: set[str]) -> None:
        """
        Raises
        ------
        FlowException
            If ``--skip`` names any ring member, gate included. A loop whose
            gate never runs can never decide when to exit, so a ring is
            skipped the way the design describes -- by gating the whole loop
            off with an ``if`` on the gate -- and not by naming a member
            here.
        """
        for name in sorted(skipped):
            gate = self.member_of.get(name)
            if gate is None:
                continue
            raise FlowException(
                f"--skip names '{name}', a member of the ring "
                f"{list(self.rings[gate])} gated by '{gate}'. A loop whose "
                f"gate never runs cannot decide when to exit, so --skip "
                f"refuses a ring member. Skip the whole loop by gating it "
                f"with 'if' on the gate '{gate}' instead."
            )

    def _reject_outside(
        self, named: set[str], selected: set[str], restricted_by: str
    ) -> None:
        """
        Parameters
        ----------
        named : set[str]
            The jobs the narrowing-sensitive options named.
        selected : set[str]
            The jobs the run was restricted to.
        restricted_by : str
            Whichever option narrowed the graph. Both ``--target`` and
            ``--reproducible`` do, so a fixed ``--target`` here would tell a
            user who passed only ``--reproducible`` about an option they never
            used.

        Raises
        ------
        FlowException
            If any named job lies outside ``selected``, because the option
            would otherwise do nothing at all and say nothing about it.
        """
        outside = named - selected
        if not outside:
            return
        names = sorted(outside)
        raise FlowException(
            f"{names} {'lies' if len(names) == 1 else 'lie'} outside the "
            f"{restricted_by} subgraph {_listed(selected)}, so naming "
            f"{'it' if len(names) == 1 else 'them'} would do nothing."
        )

    def _save_final_snapshot(self, final: State) -> None:
        """
        Writes ``runs/<tag>/final``: every view of the run's final state, laid
        out by design format, and ``metrics.csv`` and ``metrics.json`` beside
        them.

        Parameters
        ----------
        final : State
            The state to snapshot.

        Raises
        ------
        FlowException
            If the snapshot could not be written.
        """
        assert self.run_dir is not None, "start() assigns it before calling run()"
        try:
            final.save_snapshot(self.run_dir / "final")
        except Exception as error:
            raise FlowException(f"Failed to save final views: {error}")

    def _require_declared(self, names: Iterable[str], option: str) -> None:
        """
        Parameters
        ----------
        names : Iterable[str]
            The job ids an option named.
        option : str
            The option's spelling, for the message.

        Raises
        ------
        FlowException
            If any name is not a job of this document. The message lists the
            declared jobs, so a typo is correctable without opening the
            document, and names the closest one outright, exactly as a
            ``TOOLS`` key naming no job does: the two spellings are of the same
            job ids, and a suggestion for one and none for the other would be
            an accident of where the check lives.
        """
        for name in names:
            if name not in self.jobs:
                raise FlowException(
                    f"{option} names '{name}', which flow "
                    f"'{self.spec.name}' does not declare."
                    + self._near_miss(name, self.jobs)
                    + f" Declared jobs: {sorted(self.jobs)}."
                )

    def _resolve_reproducible(self, name: str) -> tuple[str, int]:
        """
        Parameters
        ----------
        name : str
            Either ``<step id>`` or ``<job id>/<step id>``. The step half is
            matched case-insensitively and accepts ``fnmatch`` wildcards. Both
            forms are kept because this is the switch people reach for once
            something has already gone wrong, and losing either of them would
            be a regression in the worst place to have one.

        Returns
        -------
        tuple[str, int]
            The job that runs the step, and the step's index within that job's
            sequence.

        Raises
        ------
        FlowException
            If nothing matches, or if the match is not unique. Picking one of
            several would write a reproducible for a step the user did not
            name, which is worse than stopping. A near miss above the fuzzy
            score cutoff is offered as a suggestion and never acted on, for the
            same reason.
        """
        job_id, separator, step_id = name.rpartition("/")
        if separator:
            self._require_declared([job_id], "--reproducible")

        # Every step this run could reach, addressed as the argument addresses
        # it: by step id alone once the job half has already selected the jobs.
        candidates = {
            (candidate, index): step.id
            for candidate, job in self.jobs.items()
            if not separator or candidate == job_id
            for index, step in enumerate(job.steps)
        }
        pattern = Filter([step_id.lower()])
        matches = [
            address
            for address, step_candidate in candidates.items()
            if pattern.match(step_candidate.lower())
        ]
        if not matches:
            raise FlowException(
                f"--reproducible names step '{step_id}', which flow "
                f"'{self.spec.name}' does not run"
                + (f" in job '{job_id}'." if separator else ".")
                + self._near_miss(step_id, candidates.values())
            )
        if len(matches) > 1:
            matched_ids = sorted({candidates[address] for address in matches})
            if len(matched_ids) > 1:
                raise FlowException(
                    f"--reproducible names '{step_id}', which matches "
                    f"{matched_ids}. Name exactly one of them."
                )
            raise FlowException(
                f"--reproducible names step '{matched_ids[0]}', which runs in "
                f"{sorted({candidate for candidate, _ in matches})}. Name one "
                f"of them as '<job>/{matched_ids[0]}'."
            )
        job_id, step_index = matches[0]
        gate = self.member_of.get(job_id)
        if gate is not None:
            raise FlowException(
                f"--reproducible names a step of job '{job_id}', a member of "
                f"the ring {list(self.rings[gate])} gated by '{gate}'. Which "
                f"pass it would capture is ambiguous, so this is refused in "
                f"v1. Its pass directory is the escape hatch: inspect "
                f"'runs/<tag>/{job_id}/<k>/...' directly instead."
            )
        if self.jobs[job_id].mode == "sweep":
            raise FlowException(
                f"--reproducible names a step of job '{job_id}', a sweep "
                f"job. Which pass it would capture is ambiguous, so this is "
                f"refused in v1. Its pass directory is the escape hatch: "
                f"inspect 'runs/<tag>/{job_id}/<k>/...' directly instead."
            )
        return matches[0]

    @staticmethod
    def _near_miss(named: str, candidates: Iterable[str]) -> str:
        """
        Parameters
        ----------
        named : str
            The id that matched nothing: a step id from ``--reproducible``, or
            a job id from any option that names one.
        candidates : Iterable[str]
            Every id of that kind the invocation could have named.

        Returns
        -------
        str
            A sentence naming the closest id above the score cutoff, or
            the empty string when nothing is close enough to be worth offering.
        """
        match_tuple = process.extractOne(
            named,
            sorted(set(candidates)),
            scorer=fuzz.partial_ratio,
            score_cutoff=80,
            processor=utils.default_process,
        )
        if match_tuple is None:
            return ""
        return f" Did you mean: '{match_tuple[0]}'?"

    def _final_state(
        self, net: Net, outputs: dict[str, State], selected: set[str]
    ) -> State:
        """
        Parameters
        ----------
        net : Net
            The net that ran, restricted to ``selected``.
        outputs : dict[str, State]
            The state each job that fired produced.
        selected : set[str]
            The jobs this run was restricted to.

        Returns
        -------
        The flow's final state, either the output of the job the
        document's ``final`` key names, or the join of every leaf's token.

        ``final`` names the job whose output is the *document's* final state,
        so it settles the sinks only when it is a job of this run. A
        ``--target`` that excludes it runs a different graph, and that graph's
        final state is the join of its own leaves; there is no output of the
        excluded job to return, and returning the whole document's rule over a
        run that did not follow it would be a lie about what ran.

        Raises
        ------
        JoinConflictError
            If two leaves disagree and no ``final`` reaches this run.
            :func:`librelane.flows.join.join_sink_states` rather than
            :func:`librelane.flows.join.join_states`, because the two remedies
            differ: a job join is settled by that job's ``source``, and a sink
            join can only be settled by the document's top-level ``final``. A
            document that declares one and a run that excluded it is told so
            rather than told to declare it again, which is why the join is
            handed the excluded name.
        NetError
            If a sink place is unmarked, which
            :meth:`librelane.flows.net.Net.sink_tokens` raises and which means
            the leaf feeding it never fired.
        """
        if self.spec.final is not None and self.spec.final in selected:
            assert self.spec.final in outputs, (
                "checked by FlowSpec._check_final_names_a_job, and every "
                "selected job fired or the stall check above would have raised"
            )
            return outputs[self.spec.final]
        # Only reachable when 'final' is undeclared or this run excluded it:
        # the branch above returns for the one case where it is both declared
        # and selected. So the document's own key is exactly the excluded name.
        return join_sink_states(
            net.sink_tokens(), self.spec.name, excluded_final=self.spec.final
        )

    def _tokens_for(self, net: Net, job: ResolvedJob) -> dict[str, State]:
        arcs = net.inputs_of(job.id)
        tokens = net.consume(job.id)
        return {
            (arc.producer if arc.producer is not None else "<initial state>"): token
            for arc, token in zip(arcs, tokens)
        }

    def _tokens_for_ring(
        self, net: Net, gate: str, members: tuple[str, ...]
    ) -> dict[str, dict[str, State]]:
        """
        The member-attributed replacement for :meth:`_tokens_for`, over a
        ring's one collapsed input place per external producer.

        Parameters
        ----------
        net : Net
            The collapsed net.
        gate : str
            The ring's gate id, which is also the collapsed node's id.
        members : tuple[str, ...]
            The ring's members, in pass order.

        Returns
        -------
        Every member mapped to its own external tokens, keyed by producer.
        :meth:`FlowSpec.collapse` deduplicated what could be several members'
        need for the same external producer into one collapsed arc, so this
        walks the *original* ``spec.edges()`` to find, for each arc consumed
        here, every member whose own declared ``needs`` names that arc's
        producer, and broadcasts the one token to each of them -- which is
        why the return type is ``dict[str, State]`` per member rather than
        one flat mapping.
        """
        arcs = net.inputs_of(gate)
        raw_tokens = net.consume(gate)
        tokens: dict[str, dict[str, State]] = {member: {} for member in members}
        original_edges = self.spec.edges()
        member_ids = set(members)
        for arc, token in zip(arcs, raw_tokens):
            if arc.producer is None:
                # No external dependency at all, collapsed or not: every
                # member's own 'needs' is entirely intra-ring (only possible
                # when the ring itself is a graph root), so this is the one
                # source-arc token Net ever gives this node, and it is
                # attributed to the ring-entry member exactly as an ordinary
                # root job's single source-arc token is its whole input: that
                # member's external join seeds pass 1's circulating state.
                tokens[members[0]]["<initial state>"] = token
                continue
            matched = False
            for member in members:
                for need in original_edges[member]:
                    if need in member_ids:
                        continue
                    if self.member_of.get(need, need) == arc.producer:
                        tokens[member][need] = token
                        matched = True
            assert matched, (
                f"collapsed input arc {arc} of the ring gated by '{gate}' "
                f"traces back to no member's own 'needs'; "
                f"FlowSpec.collapsed_edges() and spec.edges() have diverged"
            )
        return tokens

    def _member_config(self, gate: ResolvedJob, member: str, k: int) -> _ResolvedConfig:
        """
        Returns
        -------
        The configuration ``member`` reads on pass ``k``: the pre-resolved
        ``(member, k)`` entry of :attr:`iteration_configs` when the ring's
        gate schedules (``gate.iterations`` is non-empty, in which case every
        member -- not just the gate -- reads a per-pass configuration, per
        the design's "iterations layers onto every member" rule), or
        otherwise this member's own job configuration (or the flow's, if it
        sets none), exactly as an ordinary job outside any ring reads it.
        """
        if gate.iterations:
            return self.iteration_configs[(member, k)]
        return self.job_configs.get(member, self.config)

    def _run_loop(
        self,
        gate: str,
        members: tuple[str, ...],
        tokens: dict[str, dict[str, State]],
        submitted: _InFlight,
        forced: bool,
    ) -> State:
        """
        Runs one ring's passes in order. Called on a worker thread, exactly as
        :meth:`_run_job` is for an ordinary job -- this is the loop
        instance's one submission to the pool, and every member of every pass
        runs sequentially inside it, sharing ``submitted`` so the steps,
        deferrals, reuse and execution counts of the whole loop instance
        aggregate on the one record, the way :meth:`run` already expects a
        submission's record to describe everything that submission did.

        Parameters
        ----------
        gate : str
            The ring's gate id.
        members : tuple[str, ...]
            The ring's members, in pass order: the gate's intra-ring
            successor first, the gate itself last.
        tokens : dict[str, dict[str, State]]
            Every member's own external tokens, from :meth:`_tokens_for_ring`.
        submitted : _InFlight
            This loop instance's record.
        forced : bool
            Whether every pass must ignore any reusable result, exactly as
            :meth:`_run_job`'s own ``forced`` does for an ordinary job.

        Returns
        -------
        The gate's output state on the pass that exits the loop: the pass
        ``until`` was satisfied on, or, on exhaustion, the last pass run.

        Raises
        ------
        FlowError
            If a step of any member raised :class:`librelane.steps.StepError`.
            A step failing inside any pass fails the loop instance the way it
            fails a job.
        FlowException
            If a step of any member raised
            :class:`librelane.steps.StepException`.

        Exhaustion is not one of the raises above: a schedule that runs out
        without ``until`` ever holding is a *deferred* error, appended to
        ``submitted.deferred`` and returned from normally with the last
        pass's state, exactly as a deferred step error is -- the run
        continued past the disappointment and produced real views, and
        :meth:`run`'s existing deferred plumbing is what withholds the
        contract check and fails the flow at the end, after every other job
        has run.
        """
        gate_job = self.jobs[gate]
        bound = len(gate_job.iterations) or gate_job.max_passes
        # spec.py's load-time validators guarantee exactly one positive
        # bound: 'iterations' (non-empty) or 'max' (>= 1).
        assert bound is not None
        assert bound > 0
        entry = members[0]
        # Pass 1's circulating state IS the entry member's external join --
        # no double join -- because that join has not happened anywhere else
        # yet; every later pass's circulating state is some earlier pass's
        # gate output, already a real join.
        circulating = join_states(tokens[entry], self.jobs[entry].source, entry)
        for k in range(1, bound + 1):
            for index, member in enumerate(members):
                member_job = self.jobs[member]
                if k == 1 and index > 0 and tokens[member]:
                    # Only a non-entry member, only on pass 1, and only if it
                    # has external tokens at all: entry's own join already
                    # happened above, and every later pass's members receive
                    # only the circulating state, because their external
                    # tokens were already consumed once, at entry.
                    input_state = join_states(
                        {"<loop>": circulating, **tokens[member]},
                        member_job.source,
                        member,
                    )
                else:
                    input_state = circulating
                if member == gate:
                    # The gate's own 'if' is not asked again here: it was
                    # already decided once, at entry, by run()'s
                    # pre-submission check -- the join of every member's
                    # external tokens under the gate's own source, gating
                    # the whole loop instance rather than this one pass.
                    # Asking a second time, per pass, would silently drop
                    # the gate's own steps (and with them the gate's
                    # output 'until' reads) the moment a runtime term in
                    # the gate's own 'if' changes truth value as the ring's
                    # circulating state evolves -- which is the ordinary
                    # case for a ring, not an edge case.
                    reason = None
                else:
                    reason = self._pass_through_reason(member_job, skipped=False)
                    if reason is None:
                        reason = self._runtime_pass_through_reason(
                            member_job, input_state
                        )
                if reason is not None:
                    logger.info(
                        f"Skipping '{member}' (loop '{gate}', pass {k}): {reason}."
                    )
                    circulating = input_state
                    continue
                config = self._member_config(gate_job, member, k)
                # Blocking, not try-and-park: this already runs on a worker
                # thread, off the scheduling thread entirely, and a waiter
                # here holds no slot of its own while it waits, so it cannot
                # deadlock against a holder that is itself an execution on
                # another worker. Acquired and released per member per pass,
                # not once for the whole ring, so a ten-pass loop does not
                # hold a seat while a member outside this pass runs.
                self.pools.acquire(member_job.resources)
                try:
                    circulating = self._execute_steps(
                        member_job,
                        input_state,
                        submitted,
                        forced,
                        None,
                        pass_index=k,
                        config=config,
                    )
                finally:
                    self.pools.release(member_job.resources)
            gate_output = circulating
            held = [
                predicates.evaluate_metric_term(
                    term, gate_output.metrics, f"Job '{gate}'"
                )
                for term in gate_job.until_terms
            ]
            if all(held):
                return gate_output
            if k < bound:
                continue
            failing = [term for term, ok in zip(gate_job.until_terms, held) if not ok]
            term_text = " and ".join(
                f"metric::{term.metric} {term.op} {term.literal}" for term in failing
            )
            observed_text = " and ".join(
                str(gate_output.metrics.get(term.metric)) for term in failing
            )
            submitted.deferred.append(
                f"Job '{gate}': the loop exhausted its {bound} passes "
                f"without satisfying {term_text} (last observed "
                f"{observed_text})"
            )
            return gate_output
        raise AssertionError(  # pragma: no cover
            "unreachable: the loop above always returns before falling "
            "through, for bound >= 1"
        )

    def _settle_sweep(
        self,
        job_id: str,
        progress: _SweepProgress,
        deferred: list[str],
    ) -> State:
        """
        Decides a completed sweep's winner, once every pass has resolved.

        Called from :meth:`run`'s main scheduling thread, never from a
        worker: every pass already ran to completion (or raised) on its own
        worker thread, and choosing among them is bookkeeping over
        already-finished results, not more work to run concurrently.

        Every pass's own steps, and how many of them were reused from a
        previous run versus executed, are merged into the run's totals by
        the caller, unconditionally, before this method is ever called --
        the same way an ordinary job's own record merges into those same
        totals ahead of its own try/except. Only the *deferred*-error half of
        a pass's bookkeeping depends on which pass wins, so it is decided
        here instead.

        Parameters
        ----------
        job_id : str
            The sweep job's id.
        progress : _SweepProgress
            Its finished passes: every pass's own output or exception, and
            its own :class:`_InFlight` record.
        deferred : list[str]
            The run's own list of deferred-error messages, extended in place
            with the *winner's* deferred messages only. A loser's deferred
            errors are logged as warnings instead, inside this method, and
            never reach this list: the flow does not use that pass's state,
            and failing the run over a result it discarded would punish the
            sweep for exploring, exactly as a losing pass's deferral does not
            fail the sweep either.

        Returns
        -------
        The winning pass's output state.

        Raises
        ------
        FlowError
            If any pass raised, naming the failing pass(es); or if any pass's
            output lacks the ``select`` metric, naming the pass and the
            metric; or if the ``select`` metric's observed value is not a
            number, naming the pass and the value.
        JobContractError
            If any pass's own output -- winner or loser, any pass that did
            not itself defer an error -- fails the job's output contract.
            Every pass is checked, not only the winner's, because a provider
            that only sometimes honours its contract is precisely what the
            contract check exists to catch.
        """
        # (a) Any pass that raised fails the whole job, naming every failing
        # pass; the other passes' results, even the ones that finished
        # cleanly, are discarded -- there is nothing to pick a winner among
        # once the sweep itself did not run cleanly.
        if progress.errors:
            failing = sorted(progress.errors)
            details = "; ".join(f"pass {k}: {progress.errors[k]}" for k in failing)
            raise FlowError(f"sweep pass(es) {failing} failed: {details}")

        # (b) Every pass's own output is contract-checked, skipped only for a
        # pass that itself deferred an error -- the existing rule, applied
        # per pass rather than once.
        job = self.jobs[job_id]
        for k in sorted(progress.results):
            if progress.records[k].deferred:
                continue
            self._check_contract(job, progress.results[k])

        # (c) Any pass whose output lacks the 'select' metric leaves the
        # sweep with nothing to compare, which is a failure of the same kind
        # as a raised pass.
        assert job.select is not None, "spec.py requires 'select' on every sweep job"
        metric, direction = job.select
        values: dict[int, Decimal] = {}
        for k in sorted(progress.results):
            state = progress.results[k]
            if metric not in state.metrics:
                raise FlowError(
                    f"sweep pass {k} does not carry 'select' metric "
                    f"'{metric}'. A sweep that cannot compare its results "
                    f"has no result."
                )
            observed = state.metrics[metric]
            if not isinstance(observed, (int, float, Decimal)):
                raise FlowError(
                    f"sweep pass {k}'s 'select' metric '{metric}' is "
                    f"{observed!r} of type '{type(observed).__name__}', "
                    f"which is not a number. A sweep's keep rule compares "
                    f"numbers, the same way a runtime predicate term does."
                )
            # Decimal(str(value)), not Decimal(value): the same conversion
            # predicates.evaluate_metric_term uses, so a float and a Decimal
            # observation compare exactly rather than through float's binary
            # rounding.
            values[k] = Decimal(str(observed))

        # (d) The winner: minimum or maximum by the metric, ties to the
        # lowest pass index. Comparing with strict '<'/'>' rather than
        # '<='/'>=' is what gives the tie-break its direction: the first
        # (lowest-index) pass to reach a given value is never displaced by a
        # later pass that only equals it.
        winner_k: int | None = None
        best: Decimal | None = None
        for k in sorted(values):
            value = values[k]
            if winner_k is None or best is None:
                winner_k, best = k, value
                continue
            if direction == "min" and value < best:
                winner_k, best = k, value
            elif direction == "max" and value > best:
                winner_k, best = k, value
        assert winner_k is not None, "values is non-empty: progress.results is"

        for k in sorted(progress.records):
            record = progress.records[k]
            if k == winner_k:
                deferred.extend(record.deferred)
            else:
                for message in record.deferred:
                    logger.warning(
                        f"Sweep pass {k} of '{job_id}' (discarded) deferred: {message}"
                    )

        return progress.results[winner_k]

    def _admit_parked(
        self,
        parked_jobs: list[_ParkedJob],
        parked_sweep_passes: list[_ParkedSweepPass],
        plan: _RunPlan,
        pending: dict[Future[State], _InFlight],
        sweep_futures: dict[Future[State], tuple[str, int]],
        future_resources: dict[Future[State], tuple[str, ...]],
    ) -> None:
        """
        Retries every job and sweep pass this run has parked for a full
        resource pool, submitting whichever now fits and leaving the rest
        parked.

        Called once at the top of :meth:`run`'s scheduling loop, on every
        wake: after ``wait()`` returns (something completed and may have
        freed a slot) and after a pass-through sweep loops back around
        (which frees none, but costs nothing extra to re-check). Non-blocking
        throughout -- every admission below is :meth:`ResourcePools.try_acquire`,
        never :meth:`ResourcePools.acquire` -- so this never stalls the
        scheduling thread the way a parked entry itself never stalls the run.

        Parameters
        ----------
        parked_jobs : list[_ParkedJob]
            Mutated in place: admitted entries are removed, the rest kept in
            their original relative order.
        parked_sweep_passes : list[_ParkedSweepPass]
            As ``parked_jobs``, for sweep passes.
        plan : _RunPlan
            This invocation's plan, for ``reproducible_at`` -- the one field
            an admitted job's or sweep pass's submission needs that neither
            :class:`_ParkedJob` nor :class:`_ParkedSweepPass` carries itself,
            since the plan is one constant for the whole run and every
            parked entry shares it.
        pending : dict[Future[State], _InFlight]
            Mutated in place: an admitted entry's future is added, keyed to
            its record, exactly as an immediate submission would be.
        sweep_futures : dict[Future[State], tuple[str, int]]
            Mutated in place: an admitted sweep pass's future is added,
            keyed to its ``(job id, pass)``.
        future_resources : dict[Future[State], tuple[str, ...]]
            Mutated in place: an admitted entry's future is added, keyed to
            the pool names its grant holds, so :meth:`run` releases them when
            the future resolves.
        """
        still_parked: list[_ParkedJob] = []
        for parked in parked_jobs:
            if not self.pools.try_acquire(parked.job.resources):
                still_parked.append(parked)
                continue
            future = get_tpe().submit(
                self._run_job,
                parked.job,
                parked.state_in,
                parked.submitted,
                parked.forced,
                plan.reproducible_at,
            )
            pending[future] = parked.submitted
            future_resources[future] = parked.job.resources
        parked_jobs[:] = still_parked

        still_parked_passes: list[_ParkedSweepPass] = []
        for parked_pass in parked_sweep_passes:
            if not self.pools.try_acquire(parked_pass.job.resources):
                still_parked_passes.append(parked_pass)
                continue
            future = get_tpe().submit(
                self._execute_steps,
                parked_pass.job,
                parked_pass.state_in,
                parked_pass.submitted,
                parked_pass.forced,
                plan.reproducible_at,
                pass_index=parked_pass.pass_index,
                config=parked_pass.config,
            )
            pending[future] = parked_pass.submitted
            sweep_futures[future] = (parked_pass.job.id, parked_pass.pass_index)
            future_resources[future] = parked_pass.job.resources
        parked_sweep_passes[:] = still_parked_passes

    def _enabled_jobs(self) -> set[str]:
        """
        Returns
        -------
        set[str]
            The ids of the jobs this configuration runs, which is every
            ordinary job whose ``if`` conjunction is true, plus one entry per
            ring -- keyed by its gate id -- counted enabled iff the *gate's*
            own ``if`` conjunction is true.

            A ring has no entry of its own to ask this about except its
            gate's: only the gate's ``if`` can stop the whole loop instance
            (:mod:`librelane.flows.selection_validation` folds a ring into
            one pseudo-job keyed the same way, and this is the ``enabled``
            set that folded view is measured against), and a non-gate
            member's own ``if`` gates only that one member's participation in
            a pass, which is a fact about the run, not about whether the loop
            exists in it at all.

        Derived from :meth:`_pass_through_reason` rather than by reading the
        conditions again, so that the load-time checks and the run cannot
        disagree about which jobs a configuration enables. ``--skip`` is
        deliberately not passed: it shapes one invocation and is not known when
        the flow is constructed.
        """
        enabled: set[str] = set()
        for job_id, job in self.jobs.items():
            gate = self.member_of.get(job_id)
            if gate is not None and gate != job_id:
                # A non-gate ring member: represented by its gate below, not
                # by itself.
                continue
            if self._pass_through_reason(job, skipped=False) is None:
                enabled.add(job_id)
        return enabled

    def _pass_through_reason(self, job: ResolvedJob, skipped: bool) -> str | None:
        """
        Returns
        -------
        Why this job fires without running, or ``None`` if it runs.
        A conjunction is false when any one of its variables is false, and the
        reason names every false one so a document author does not have to
        flip them one at a time.

        Read off the flow's configuration and never off the job's own, even
        for a job that sets the gate variable in its ``with`` block. ``if`` is
        the engine's question about whether to fire the job at all, asked
        before the job exists to answer for itself; a job that could switch its
        own gate on would make every ``if`` naming a variable that job also
        sets unconditionally true, which is not a gate. This is a decision, not
        an oversight: a per-job ``with`` changes what the job's *steps* read,
        and nothing else.
        """
        if skipped:
            return "named by --skip"
        false_variables = [
            name
            for name in predicates.config_terms(job.conditions)
            if not self.config[name]
        ]
        if false_variables:
            names = ", ".join(f"'{name}'" for name in false_variables)
            verb = "is" if len(false_variables) == 1 else "are"
            return f"{names} {verb} false"
        return None

    def _runtime_pass_through_reason(
        self, job: ResolvedJob, state_in: State
    ) -> str | None:
        """
        Returns
        -------
        Why this job fires as a pass-through on account of a runtime
        (``metric::``) term in its ``if``, or ``None`` if every one holds.

        Asked only once :meth:`_pass_through_reason` has already answered
        ``None`` for this job: ``--skip`` and a false configuration term are
        decided at construction and win outright, so the scheduling loop asks
        this second, and only when nothing already stopped the job. A runtime
        term is decided only now, against the joined input state, which is
        why this takes ``state_in`` and :meth:`_pass_through_reason` does not.

        Raises
        ------
        FlowError
            Propagated from
            :func:`~librelane.flows.predicates.evaluate_metric_term`: the
            term's metric is absent from ``state_in.metrics``, or its
            observed value is not numeric.
        """
        for term in predicates.metric_terms(job.conditions):
            if predicates.evaluate_metric_term(
                term, state_in.metrics, f"Job '{job.id}'"
            ):
                continue
            observed = state_in.metrics[term.metric]
            return (
                f"metric::{term.metric} {term.op} {term.literal} is false: "
                f"observed {observed}"
            )
        return None

    def _run_job(
        self,
        job: ResolvedJob,
        state_in: State,
        submitted: _InFlight,
        forced: bool,
        reproducible_at: tuple[str, int] | None,
    ) -> State:
        """
        Runs one ordinary job's steps in order, once, on its own
        configuration. The ``pass_index=None`` case of :meth:`_execute_steps`,
        kept as a method of its own because every ordinary job's submission
        calls it by name, and because resolving "this job's own
        configuration" is a one-line derivation :meth:`_execute_steps` should
        not have to make on every caller's behalf -- a ring member's or a
        sweep execution's is resolved per pass instead, by their own callers.

        Parameters
        ----------
        job : ResolvedJob
            The job to run.
        state_in : State
            The state its first step consumes.
        submitted : _InFlight
            This job's record. Its ``steps``, ``deferred``, ``reused`` and
            ``executed`` are filled in here.
        forced : bool
            Whether this job must ignore any reusable result. Required rather
            than defaulting to ``False``, so that a future caller cannot forget
            it and silently consult the cache. A forced step still *writes* its
            entry, so the next run reuses it.
        reproducible_at : tuple[str, int] | None
            The job and step index a reproducible was asked for, or ``None``.
            Required for the same reason ``forced`` is: a caller that forgot it
            would run the step instead of writing a reproducible for it, and
            say nothing.

        Returns
        -------
        The state the job's last step produced.

        Raises
        ------
        FlowError
            If a step raised :class:`librelane.steps.StepError`.
        FlowException
            If a step raised :class:`librelane.steps.StepException`.
        _ReproducibleCreated
            If this job runs the step ``reproducible_at`` names, once the
            reproducible is written. Caught by :meth:`run`.
        """
        # A job that declares no 'with' block has no configuration of its own,
        # and the flow's is the whole answer for it.
        config = self.job_configs.get(job.id, self.config)
        return self._execute_steps(
            job,
            state_in,
            submitted,
            forced,
            reproducible_at,
            pass_index=None,
            config=config,
        )

    def _execute_steps(
        self,
        job: ResolvedJob,
        state_in: State,
        submitted: _InFlight,
        forced: bool,
        reproducible_at: tuple[str, int] | None,
        *,
        pass_index: int | None,
        config: _ResolvedConfig,
    ) -> State:
        """
        Runs one job's steps in order, once. Called on a worker thread, so
        ``submitted`` is this execution's own record and no other thread reads
        it until the future resolves -- true even for a ring's several
        executions across a pass, since :meth:`_run_loop` runs every member
        sequentially inside its own single worker submission and shares one
        ``submitted`` across all of them by design, not because two threads
        ever touch it at once.

        Parameters
        ----------
        job : ResolvedJob
            The job to run.
        state_in : State
            The state its first step consumes.
        submitted : _InFlight
            This execution's record. Its ``steps``, ``deferred``, ``reused``
            and ``executed`` are filled in here. A ring's members share one
            record across every member and every pass, so its counts and
            deferrals describe the whole loop instance, exactly as one
            ordinary job's describes it.
        forced : bool
            Whether this execution must ignore any reusable result.
        reproducible_at : tuple[str, int] | None
            The job and step index a reproducible was asked for, or ``None``.
            Always ``None`` for a ring member or a sweep execution:
            ``--reproducible`` refuses both in v1 before either ever reaches
            here.
        pass_index : int | None
            The 1-based pass this execution is, for a ring member or (task 5)
            a sweep execution, or ``None`` for an ordinary job's only
            execution. Threaded into the step directory
            (:meth:`dir_for_job_step`) and every step instance's id, so pass 3
            of a loop member is distinguishable from pass 2 in both the run
            directory and the log -- the same reason :meth:`_run_job` already
            named each instance after its job, extended one level.
        config : _ResolvedConfig
            The configuration this execution's steps read. An ordinary job's
            own (:meth:`_run_job` resolves it before calling here); a ring
            member's is its iteration config on a scheduled pass or its own
            job config otherwise, resolved by :meth:`_run_loop`, because which
            configuration applies is a fact about the pass, not about the job.

        Returns
        -------
        The state this execution's last step produced.

        Raises
        ------
        FlowError
            If a step raised :class:`librelane.steps.StepError`.
        FlowException
            If a step raised :class:`librelane.steps.StepException`.
        _ReproducibleCreated
            If this execution runs the step ``reproducible_at`` names, once
            the reproducible is written. Caught by :meth:`run`.
        """
        current = state_in
        for index, cls in enumerate(job.steps):
            step = cls(
                config=config,
                state_in=current,
                # The logging layer keys a running step on its id: the loguru
                # sink filter that routes records into the step's own
                # step.log, LiveLog's registry of what is live, and the
                # progress row read off it. Two jobs running the same step
                # class at once would share that key, so each one's records
                # would land in both step.log files, the second registration
                # would overwrite the first's display, and whichever finished
                # first would unregister the other. Step's initializer
                # documents a per-instance id as the way to disambiguate one
                # step class used more than once in a flow; the job (and, for
                # a pass, the pass number) is what distinguishes them.
                id=(
                    f"{cls.id} ({job.id})"
                    if pass_index is None
                    else f"{cls.id} ({job.id}/{pass_index})"
                ),
            )
            step_dir = self.dir_for_job_step(job, index, step, pass_index)
            if (job.id, index) == reproducible_at:
                # Before the resume check, and without the rmtree below: the
                # step is not going to run, so neither reusing its previous
                # result nor deleting it is meaningful. It is also not appended
                # to 'steps', because it never ran.
                written = step_dir / "reproducible"
                step.create_reproducible(written)
                raise _ReproducibleCreated(written, current)
            assert self.fingerprinter is not None
            key = resume_key(step, current, self.fingerprinter)
            reused = (
                None if forced else reusable_state(step_dir, key, self.fingerprinter)
            )
            if reused is not None:
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                submitted.steps.append(step)
                submitted.reused += 1
                current = reused
                continue
            shutil.rmtree(step_dir, ignore_errors=True)
            submitted.steps.append(step)
            try:
                current = step.start(toolbox=self.toolbox, step_dir=step_dir)
            except StepException as e:
                raise FlowException(str(e)) from None
            except DeferredStepError as e:
                submitted.deferred.append(str(e))
                # A deferred error says "flag this at the end, keep going", and
                # where it was raised decides what "keep going" carries on
                # from. A gate raises after run() has returned, so the step has
                # real outputs -- OpenROAD.DetailedRouting reporting DRC
                # violations still routed the design -- and dropping them would
                # hand every later step the views from before it ran. A step
                # that defers from inside run() never reached that point and
                # has none, so the flow carries on with the state it already
                # had. start() clears state_out before running, so the
                # attribute answers which of the two happened and nothing else.
                #
                # Either way the resume entry is withheld, so a resumed run
                # re-runs the step and raises again.
                if step.state_out is not None:
                    current = step.state_out
            except StepError as e:
                raise FlowError(str(e)) from None
            else:
                write_entry(step_dir, step, key)
            submitted.executed += 1
        return current

    def dir_for_job_step(
        self,
        job: ResolvedJob,
        index: int,
        step: Step,
        pass_index: int | None = None,
    ) -> pathlib.Path:
        """
        Returns
        -------
        ``<run_dir>/<job id>/<n>-<step slug>``, or, when ``pass_index`` is not
        ``None``, ``<run_dir>/<job id>/<pass_index>/<n>-<step slug>``: a ring
        member's or (task 5) a sweep execution's own directory for that pass,
        one level below the job's, so pass 3 does not overwrite pass 2's, and
        an ordinary job's directory (``pass_index=None``, the default) is
        untouched and byte-identical to what it always was.

        Keyed by the job rather than by a global counter, because under
        concurrency there is no global step order and a positional prefix would
        change whenever an unrelated edge was added, invalidating resume for
        every step after it.

        The ordinal is not zero-padded, for the same reason. A width derived
        from the step count changes the moment the count crosses a power of
        ten, so appending a tenth step to a nine-step job would rename
        ``1-a``…``9-i`` to ``01-a``…``09-i`` and every one of the nine would
        miss its resume entry and re-run. Unpadded, only the appended step is
        new.

        The slug comes from the *class's* id, not the instance's.
        :meth:`_execute_steps` gives each instance an id naming its job (and,
        for a pass, the pass) so the logging layer can tell two concurrent
        runs of one step class apart, and that name is already the directory
        this path sits in. Spelling it twice would give
        ``left/1-test-first-left`` and, worse, would move every existing step
        directory the first time a job was renamed.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to name a step directory before the flow started."
            )
        job_dir = self.run_dir / job.id
        if pass_index is not None:
            job_dir = job_dir / str(pass_index)
        return job_dir / f"{index + 1}-{slugify(type(step).id)}"

    def _check_contract(self, job: ResolvedJob, state: State) -> None:
        """
        Asserts a completed job produced everything its template promised.

        Only a ``uses`` job has a promise to assert, and the asymmetry is
        deliberate. A template's ``provides`` and ``metrics``, and its
        registration's, are curated by hand next to the provider that has to
        honour them, so every entry is a guarantee. An inline ``steps`` job's ``provides`` is derived in
        :func:`librelane.flows.job.resolve_jobs` as the union of its steps'
        ``outputs``, and :class:`librelane.steps.Step` documents ``outputs`` as
        the views a step *may* emit, not the ones it must: ``Odb.DiodesOnPorts``
        declares five and emits none when ``DIODE_ON_PORTS`` is ``"none"``,
        which is the default. Asserting a derived union would therefore make a
        stock configuration a hard error.

        The derived ``provides`` is still computed and still correct: phase 1's
        reachability analysis reads it as a claim about what a job *can*
        contribute to its successors, which is exactly what a permission is.
        This method is the one place that would read it as an obligation, and
        so it is the one place that does not.

        Parameters
        ----------
        job : ResolvedJob
            The job that completed.
        state : State
            The state it produced.

        Raises
        ------
        JobContractError
            If a ``uses`` job is missing a view or metric its template or
            provider declared.
        """
        if job.provider is None:
            return
        for view in job.provides:
            if state.get_by_df(view) is None:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing view "
                    f"'{view}', which it declares. Provider: {job.provider}."
                )
        for metric in job.metrics:
            if metric not in state.metrics:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing metric "
                    f"'{metric}', which it declares. Provider: {job.provider}."
                )
