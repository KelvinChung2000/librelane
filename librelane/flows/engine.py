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
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from loguru import logger
from rapidfuzz import fuzz, process, utils

from librelane.common import Filter, get_tpe, slugify
from librelane.config import (
    AnyConfig,
    AnyConfigs,
    Config,
    universal_flow_config_variables,
    variable,
)
from librelane.jobs import JobContractError, extract_tools
from librelane.state import State
from librelane.steps import DeferredStepError, Step, StepError, StepException
from librelane.flows.explanation import (
    Explanation,
    JobDisposition,
    VariableDisposition,
)
from librelane.flows.flow import Flow, FlowError, FlowException
from librelane.flows.job import ResolvedJob, ToolSelection, resolve_jobs
from librelane.flows.join import join_sink_states, join_states
from librelane.flows.net import Net
from librelane.flows.resume import resume_key, reusable_state, write_entry
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_graph import ancestors, descendants, topological_order
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
        The state the named step would have consumed. It is the run's final
        state, for the same reason it is in
        :class:`librelane.flows.sequential.SequentialFlow`: the flow stopped
        there, so the last thing it knows about the design is what that step
        was about to be handed.
    """

    def __init__(self, path: pathlib.Path, state: State) -> None:
        super().__init__(f"Wrote a reproducible to '{path}'.")
        self.path = path
        self.state = state


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
        here, exactly as
        :class:`librelane.flows.sequential.SequentialFlow` counts it.
    """

    name: str
    steps: list[Step] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    reused: int = 0
    executed: int = 0


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
    """

    Steps: list[type[Step]] = []

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
                "come from the PDK."
            ),
        )

    def __init__(
        self,
        spec: FlowSpec,
        config: AnyConfigs,
        *,
        config_override_strings: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        validate_against_registry(spec)
        self.spec = spec
        self.jobs = resolve_jobs(
            spec,
            self._selected_tools(config, config_override_strings),
        )
        self.Steps = [step for job in self.jobs.values() for step in job.steps]
        # Flow.__init__ builds the Config from get_all_config_variables(), which
        # reads config_vars; resolves the flow name from the class when the
        # instance has not set one; and layers 'values' into the loader's
        # sources. All three assignments must precede it.
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
        #: One resolved configuration per job that declares a ``with`` block.
        self.job_configs = self._resolve_job_configs(
            config,
            config_override_strings,
            kwargs,
        )

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

    @staticmethod
    def _selected_tools(
        config: AnyConfigs,
        config_override_strings: Sequence[str] | None,
    ) -> Mapping[str, ToolSelection]:
        """
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
            # Already validated, so TOOLS is present and typed. Checked before
            # Mapping, which a resolved Config also satisfies.
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
        )

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
            subgraph.
        """
        # They compose in a fixed order: --target restricts the graph first,
        # and --skip and --invalidate then apply within the restriction.
        # Naming a job outside it is an error rather than a silent no-op,
        # because the option would otherwise do nothing at all and say nothing
        # about it.
        edges = self.spec.edges()

        selected = self._target_subgraph(edges, target)
        restricted_by = "--target"

        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")
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
            # silently discarded. This mirrors SequentialFlow.run.
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
        forced: set[str] = set()
        for name in invalidated:
            forced.add(name)
            forced |= descendants(edges, name) & selected

        # 'selected' is closed under 'needs' -- ancestors() is the transitive
        # closure of it -- so dropping the unselected keys cannot leave a
        # dangling predecessor behind, and every remaining 'needs' list is
        # already a list of selected jobs.
        net = Net(
            [name for name in self.jobs if name in selected],
            {name: needs for name, needs in edges.items() if name in selected},
        )
        for arc in net.arcs:
            if arc.producer is None:
                net.put(arc, initial_state)

        self.progress_bar.set_max_stage_count(len(selected))
        steps_run: list[Step] = []
        deferred: list[str] = []
        failures: list[str] = []
        reused_count = 0
        executed_count = 0
        outputs: dict[str, State] = {}
        pending: dict[Future[State], _InFlight] = {}

        # The marking is not thread-safe and is not made so: every call into
        # `net` below happens on this thread. A lock would exist only to
        # protect one dictionary from a scheduler that has no reason to
        # contend for it, so the net is consumed before a job is submitted and
        # fired after its future resolves, and the workers never see it.
        while True:
            fired_pass_through = False
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
                        job = self.jobs[name]
                        tokens = self._tokens_for(net, job)
                        state_in = join_states(tokens, job.source, name)
                        self.progress_bar.start_stage(name)
                        started = True
                        reason = self._pass_through_reason(job, name in skipped)
                        if reason is not None:
                            logger.info(f"Skipping job '{name}': {reason}.")
                            net.fire(name, state_in)
                            outputs[name] = state_in
                            self.progress_bar.end_stage()
                            fired_pass_through = True
                            continue
                        submitted = _InFlight(name)
                        pending[
                            get_tpe().submit(
                                self._run_job,
                                job,
                                state_in,
                                submitted,
                                name in forced,
                                reproducible_at,
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
                    # path puts it there, and on this path at all because
                    # SequentialFlow's --reproducible breaks out of its step
                    # loop into the same tail: the run stopped, and what it
                    # knows about the design is worth writing down either way.
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
        # views and SequentialFlow snapshots them. What follows is then in
        # sequential.py's order: snapshot, raise, report, and a run that is
        # about to fail therefore never announces that it reused anything or
        # that it is complete.
        final = self._final_state(net, outputs, selected)
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
        skip: Iterable[str] | None = None,
        variables: bool = False,
    ) -> Explanation:
        """
        Parameters
        ----------
        target : Iterable[str] | None
            As :meth:`run`.
        skip : Iterable[str] | None
            As :meth:`run`.
        variables : bool
            Also report every configuration variable, its value, the layer that
            supplied it and the jobs that can read it. Asked for rather than
            always answered, because it is a larger question than which jobs
            run and it can only be answered by a flow whose configuration was
            resolved against its own variable list. Nothing is filtered when
            it is asked: every variable gets a row, defaults included.

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
            If any named job is not declared, or if ``skip`` names a job
            ``target`` already excluded. :meth:`run` refuses the same
            arguments, and an explanation that answered where the run would
            raise would be describing an invocation that cannot happen.

        Resume is deliberately not reported, for the reason given on
        :meth:`librelane.flows.SequentialFlow.explain`. A resume verdict depends
        on content fingerprints of files that later jobs in the same run will
        rewrite, so it cannot be known before the run.
        """
        edges = self.spec.edges()
        selected = self._target_subgraph(edges, target)
        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")
        self._reject_outside(skipped, selected, "--target")

        dispositions: list[JobDisposition] = []
        for job_id in topological_order(edges):
            job = self.jobs[job_id]
            needs = tuple(job.needs)
            if job_id not in selected:
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
            # The same call the run makes, so the two cannot disagree about
            # which variable stopped a job or how its absence is worded.
            reason = self._pass_through_reason(job, job_id in skipped)
            if reason is None:
                dispositions.append(
                    JobDisposition(job_id, needs, True, "will run", None)
                )
            else:
                mechanism = "skip" if job_id in skipped else "condition"
                dispositions.append(
                    JobDisposition(job_id, needs, False, reason, mechanism)
                )
        return Explanation(
            steps=(),
            unselected_jobs=(),
            jobs=tuple(dispositions),
            variables=self._variable_dispositions() if variables else (),
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

            Not narrowed by ``--target`` or ``--skip``. Which jobs *can* read a
            variable is a property of the document and the configuration, and
            an invocation that runs fewer of them does not change it.
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
        """
        groups: list[tuple[Any, str, list[str]]] = []
        for job_id in reach:
            # A job that declares no 'with' block has no configuration of its
            # own, exactly as in _run_job.
            config = self.job_configs.get(job_id, self.config)
            resolved = (config[name], config.provenance.get(name, "default"))
            for value, origin, group in groups:
                if (value, origin) == resolved:
                    group.append(job_id)
                    break
            else:
                groups.append((*resolved, [job_id]))
        if not groups:
            return [
                (self.config[name], self.config.provenance.get(name, "default"), ())
            ]
        return [(value, origin, tuple(group)) for value, origin, group in groups]

    def _target_subgraph(
        self, edges: dict[str, list[str]], target: Iterable[str] | None
    ) -> set[str]:
        """
        Parameters
        ----------
        edges : dict[str, list[str]]
            This document's job dependency map.
        target : Iterable[str] | None
            The jobs ``--target`` named, or ``None`` for the whole graph.

        Returns
        -------
        The named jobs and their transitive ancestors, or every job when
        nothing was named. Shared with :meth:`explain` rather than written
        twice, because an explanation that drew a different subgraph from the
        run it describes would be worse than no explanation.

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
            selected.add(name)
            selected |= ancestors(edges, name)
        return selected

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
            document.
        """
        for name in names:
            if name not in self.jobs:
                raise FlowException(
                    f"{option} names '{name}', which flow "
                    f"'{self.spec.name}' does not declare. Declared jobs: "
                    f"{sorted(self.jobs)}."
                )

    def _resolve_reproducible(self, name: str) -> tuple[str, int]:
        """
        Parameters
        ----------
        name : str
            Either ``<step id>`` or ``<job id>/<step id>``. The step half is
            matched case-insensitively and accepts ``fnmatch`` wildcards,
            exactly as :meth:`librelane.flows.SequentialFlow._resolve_step_id`
            matches the same argument. Both are kept because this is the switch
            people reach for once something has already gone wrong, and losing
            either of them on the document path would be a regression in the
            worst place to have one.

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
        return matches[0]

    @staticmethod
    def _near_miss(step_id: str, candidates: Iterable[str]) -> str:
        """
        Parameters
        ----------
        step_id : str
            The step id that matched nothing.
        candidates : Iterable[str]
            Every step id this run could have reached.

        Returns
        -------
        str
            A sentence naming the closest step id above the score cutoff, or
            the empty string when nothing is close enough to be worth offering.
        """
        match_tuple = process.extractOne(
            step_id,
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
            variable for variable in job.conditions if not self.config[variable]
        ]
        if false_variables:
            names = ", ".join(f"'{variable}'" for variable in false_variables)
            verb = "is" if len(false_variables) == 1 else "are"
            return f"{names} {verb} false"
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
        Runs one job's steps in order. Called on a worker thread, so
        ``submitted`` is this job's own record and no other thread reads it
        until the future resolves.

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
        current = state_in
        # A job that declares no 'with' block has no configuration of its own,
        # and the flow's is the whole answer for it.
        config = self.job_configs.get(job.id, self.config)
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
                # step class used more than once in a flow; the job is what
                # distinguishes them.
                id=f"{cls.id} ({job.id})",
            )
            step_dir = self.dir_for_job_step(job, index, step)
            if (job.id, index) == reproducible_at:
                # Before the resume check, and without the rmtree below: the
                # step is not going to run, so neither reusing its previous
                # result nor deleting it is meaningful. It is also not appended
                # to 'steps', because it never ran, which is what SequentialFlow
                # does for the same request.
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
            except StepError as e:
                raise FlowError(str(e)) from None
            else:
                write_entry(step_dir, step, key)
            submitted.executed += 1
        return current

    def dir_for_job_step(
        self, job: ResolvedJob, index: int, step: Step
    ) -> pathlib.Path:
        """
        Returns
        -------
        ``<run_dir>/<job id>/<n>-<step slug>``.

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
        :meth:`_run_job` gives each instance an id naming its job so the
        logging layer can tell two concurrent runs of one step class apart,
        and that name is already the directory this path sits in. Spelling it
        twice would give ``left/1-test-first-left`` and, worse, would move
        every existing step directory the first time a job was renamed.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to name a step directory before the flow started."
            )
        return self.run_dir / job.id / f"{index + 1}-{slugify(type(step).id)}"

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
        stock configuration a hard error, and would be a stricter rule than the
        ``SequentialFlow`` this engine is meant to be equivalent to, which
        contract-checks no bare step at all.

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
