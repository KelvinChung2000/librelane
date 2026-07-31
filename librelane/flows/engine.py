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

from loguru import logger

from librelane.common import slugify
from librelane.state import State
from librelane.steps import DeferredStepError, Step, StepError, StepException
from librelane.flows.flow import Flow, FlowError, FlowException
from librelane.flows.job import Job, resolve_jobs
from librelane.flows.join import join_states
from librelane.flows.net import Net
from librelane.flows.resume import resume_key, reusable_state, write_entry
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_graph import topological_order
from librelane.flows.spec_validation import validate_against_registry


class JobContractError(FlowError):
    """
    Raised when a job completes without having produced a view or metric it
    declared.
    """


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
        outputs: dict[str, State] = {}

        for name in topological_order(self.spec.edges()):
            job = self.jobs[name]
            tokens = self._tokens_for(net, job)
            state_in = join_states(tokens, job.source, name)

            self.progress_bar.start_stage(name)
            reason = self._pass_through_reason(job, name in skipped)
            if reason is not None:
                logger.info(f"Skipping job '{name}': {reason}.")
                state_out = state_in
            else:
                already_deferred = len(deferred)
                state_out = self._run_job(job, state_in, steps_run, deferred)
                # A job that deferred an error did not complete, so its output
                # contract is not a meaningful thing to assert: the deferring
                # step's views are missing precisely because it failed.
                # Checking anyway would raise JobContractError here and the
                # deferred errors collected below would never surface,
                # replacing the real diagnosis with a misleading one.
                if len(deferred) == already_deferred:
                    self._check_contract(job, state_out)
            self.progress_bar.end_stage()

            net.fire(name, state_out)
            outputs[name] = state_out

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
        steps_run: list[Step],
        deferred: list[str],
    ) -> State:
        current = state_in
        for index, cls in enumerate(job.steps):
            step = cls(config=self.config, state_in=current)
            step_dir = self.dir_for_job_step(job, index, step)
            assert self.fingerprinter is not None
            key = resume_key(step, current, self.fingerprinter)
            reused = reusable_state(step_dir, key, self.fingerprinter)
            if reused is not None:
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                steps_run.append(step)
                current = reused
                continue
            shutil.rmtree(step_dir, ignore_errors=True)
            steps_run.append(step)
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
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to name a step directory before the flow started."
            )
        return self.run_dir / job.id / f"{index + 1}-{slugify(step.id)}"

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
