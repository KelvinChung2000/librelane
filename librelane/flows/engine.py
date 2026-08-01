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

import pathlib
import shutil
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field

from loguru import logger

from librelane.common import get_tpe, slugify
from librelane.state import State
from librelane.steps import DeferredStepError, Step, StepError, StepException
from librelane.flows.flow import Flow, FlowError, FlowException
from librelane.flows.job import Job, resolve_jobs
from librelane.flows.join import join_states
from librelane.flows.net import Net
from librelane.flows.resume import resume_key, reusable_state, write_entry
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_validation import validate_against_registry


class JobContractError(FlowError):
    """
    Raised when a job completes without having produced a view or metric it
    declared.
    """


@dataclass
class _InFlight:
    """
    One submitted job, and the two lists its worker writes into.

    The lists belong to this record rather than to the run, so a worker shares
    nothing with another worker or with the main thread. The main thread merges
    them into the run's lists when the future resolves, which is also what
    keeps a deferral a fact about *this* job: a single shared list's length,
    compared before and after, cannot say which job appended to it once two
    jobs run at once.

    Parameters
    ----------
    name
        The job's id.
    steps
        Every step the job constructed, in the order it ran them.
    deferred
        The message of every error a step of this job deferred.
    """

    name: str
    steps: list[Step] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)


class Workflow(Flow):
    """
    Runs a :class:`librelane.flows.spec.FlowSpec`.

    Parameters
    ----------
    spec
        The document to run. Validated against the registries here, so
        a document constructed in Python gets the same checks a loaded one does.
    """

    Steps: list[type[Step]] = []

    def __init__(self, spec: FlowSpec, *args, **kwargs) -> None:
        validate_against_registry(spec)
        self.spec = spec
        self.jobs = resolve_jobs(spec)
        self.Steps = [step for job in self.jobs.values() for step in job.steps]
        # Flow.__init__ builds the Config from get_all_config_variables(), which
        # reads config_vars, and resolves the flow name from the class when the
        # instance has not set one. Both assignments must precede it.
        self.config_vars = [variable.to_variable() for variable in spec.config]
        self.name = spec.name
        super().__init__(*args, **kwargs)

    def run(
        self,
        initial_state: State,
        skip: Iterable[str] | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        Parameters
        ----------
        initial_state : State
            The state deposited on every source place.
        skip : Iterable[str] | None
            Job ids to pass through without running.

        Returns
        -------
        ``(final_state, steps_run)``
        """
        skipped = set(skip or ())
        for name in skipped:
            if name not in self.jobs:
                raise FlowException(
                    f"--skip names '{name}', which flow '{self.spec.name}' "
                    f"does not declare. Declared jobs: {sorted(self.jobs)}."
                )

        net = Net(list(self.jobs), self.spec.edges())
        for arc in net.arcs:
            if arc.producer is None:
                net.put(arc, initial_state)

        self.progress_bar.set_max_stage_count(len(self.jobs))
        steps_run: list[Step] = []
        deferred: list[str] = []
        failures: list[str] = []
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
                                submitted.steps,
                                submitted.deferred,
                            )
                        ] = submitted
                    except Exception as e:
                        failures.append(f"Job '{name}': {e}")
                        # Only if it started. The token read and the input
                        # join run before start_stage, and ending a stage that
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
        # otherwise a genuine failure would be reported as a stall.
        if not net.is_complete():
            raise FlowException(
                f"Flow '{self.spec.name}' stalled: no job is enabled and "
                f"{sorted(net.stalled())} never ran."
            )
        if deferred:
            raise FlowError("\n".join(deferred))
        return self._final_state(net, outputs), steps_run

    def _final_state(self, net: Net, outputs: dict[str, State]) -> State:
        """
        Returns
        -------
        The flow's final state, either the output of the job the
        document's ``final`` key names, or the join of every leaf's token.

        Raises
        ------
        JoinConflictError
            If two leaves disagree and no ``final`` is declared.
        NetError
            If a sink place is unmarked, which
            :meth:`librelane.flows.net.Net.sink_tokens` raises and which means
            the leaf feeding it never fired.
        """
        if self.spec.final is not None:
            assert self.spec.final in outputs, (
                "checked by FlowSpec._check_final_names_a_job"
            )
            return outputs[self.spec.final]
        return join_states(
            net.sink_tokens(),
            {},
            f"the final state of flow '{self.spec.name}'",
        )

    def _tokens_for(self, net: Net, job: Job) -> dict[str, State]:
        arcs = net.inputs_of(job.id)
        tokens = net.consume(job.id)
        return {
            (arc.producer if arc.producer is not None else "<initial state>"): token
            for arc, token in zip(arcs, tokens)
        }

    def _pass_through_reason(self, job: Job, skipped: bool) -> str | None:
        """
        Returns
        -------
        Why this job fires without running, or ``None`` if it runs.
        A conjunction is false when any one of its variables is false, and the
        reason names every false one so a document author does not have to
        flip them one at a time.
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
        job: Job,
        state_in: State,
        steps: list[Step],
        deferred: list[str],
    ) -> State:
        """
        Runs one job's steps in order. Called on a worker thread, so ``steps``
        and ``deferred`` are this job's own lists and no other thread reads
        them until the future resolves.

        Parameters
        ----------
        job : Job
            The job to run.
        state_in : State
            The state its first step consumes.
        steps : list[Step]
            Appended to with every step constructed, in the order run.
        deferred : list[str]
            Appended to with the message of every error a step deferred.

        Returns
        -------
        The state the job's last step produced.

        Raises
        ------
        FlowError
            If a step raised :class:`librelane.steps.StepError`.
        FlowException
            If a step raised :class:`librelane.steps.StepException`.
        """
        current = state_in
        for index, cls in enumerate(job.steps):
            step = cls(
                config=self.config,
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
            assert self.fingerprinter is not None
            key = resume_key(step, current, self.fingerprinter)
            reused = reusable_state(step_dir, key, self.fingerprinter)
            if reused is not None:
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                steps.append(step)
                current = reused
                continue
            shutil.rmtree(step_dir, ignore_errors=True)
            steps.append(step)
            try:
                current = step.start(toolbox=self.toolbox, step_dir=step_dir)
            except StepException as e:
                raise FlowException(str(e)) from None
            except DeferredStepError as e:
                deferred.append(str(e))
            except StepError as e:
                raise FlowError(str(e)) from None
            else:
                write_entry(step_dir, step, key)
        return current

    def dir_for_job_step(self, job: Job, index: int, step: Step) -> pathlib.Path:
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

    def _check_contract(self, job: Job, state: State) -> None:
        for view in job.provides:
            if state.get_by_df(view) is None:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing view "
                    f"'{view}', which it declares. Provider: "
                    f"{job.provider or 'inline steps'}."
                )
        for metric in job.metrics:
            if metric not in state.metrics:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing metric "
                    f"'{metric}', which it declares. Provider: "
                    f"{job.provider or 'inline steps'}."
                )
