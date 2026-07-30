# Copyright 2023 Efabless Corporation
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
from __future__ import annotations

from loguru import logger

import shutil
from collections.abc import Iterable

from rapidfuzz import process, fuzz, utils

from .explanation import Explanation, StepDisposition
from .flow import Flow, FlowException, FlowError
from .resume import resume_key, reusable_state, write_entry
from ..common import Filter
from ..state import State
from ..steps import (
    Step,
    StepError,
    StepException,
    DeferredStepError,
)


class SequentialFlow(Flow):
    """
    The simplest Flow, running each Step as a stage, serially,
    with nothing happening in parallel and no significant inter-step
    processing.

    All subclasses of this flow have to do is override the :attr:`.Steps` abstract property
    and it would automatically handle the rest. See `Classic` in Built-in Flows for an example.

    It should be noted, for Steps with duplicate IDs, all Steps other than the
    first one will technically be subclassed with no change other than to simply
    set the ID to the previous step's ID with a suffix: i.e. the second instance
    of ``Test.MyStep`` will have an ID of ``Test.MyStep1``, and so on.

    :param args: Arguments for :class:`Flow`.
    :param kwargs: Keyword arguments for :class:`Flow`.

    :cvar gating_config_vars: A mapping from step ID (wildcards) to lists of
        Boolean variable names. All Boolean variables must be True for a step with
        a specific ID to execute.
    """

    gating_config_vars: dict[str, list[str]] = {}

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        self.Steps = self.Steps.copy()  # Break global reference
        super().__init__(*args, **kwargs)

    # ---

    def __init_subclass__(Self, scm_type=None, name=None, **kwargs):
        super().__init_subclass__(**kwargs)
        Self.Steps = Self.Steps.copy()  # Break global reference
        Self.config_vars = Self.config_vars.copy()
        Self.gating_config_vars = Self.gating_config_vars.copy()
        Self._normalize_step_ids(Self)
        Self._validate_gating_config_vars(Self)

    @staticmethod
    def _validate_gating_config_vars(target: SequentialFlow | type[SequentialFlow]):
        """
        Checks that every gating key names at least one step in ``target`` and
        that every gating variable is a declared Boolean.

        Separate from ``__init_subclass__`` so that :class:`StagedFlow` can
        re-run it after generating gating entries from stage gates, which it can
        only do once step IDs have been normalized. Takes a target, like
        ``_normalize_step_ids``, because instance-level
        ``TOOLS`` rebuilds ``Steps`` on the instance rather than the class.
        """
        name = getattr(target, "__qualname__", type(target).__qualname__)
        variables_by_name = {}
        for variable in target.config_vars:
            variables_by_name[variable.name] = variable

        step_id_set = set()
        for step in target.Steps:
            step_id_set.add(step.id)

        for id, variable_names in target.gating_config_vars.items():
            matching_steps = list(Filter([id]).filter(step_id_set))
            if id not in step_id_set and len(matching_steps) < 1:
                raise TypeError(
                    f"Gating key '{id}' in Flow '{name}' matches no step in "
                    f"the flow. A gating key that matches nothing silently "
                    f"fails to gate anything."
                )
            for var_name in variable_names:
                if var_name not in variables_by_name:
                    raise TypeError(
                        f"Gating variable '{var_name}' for Step '{id}' does not match any declared config_vars in Flow '{name}'"
                    )
                if variables_by_name[var_name].type != bool:
                    raise TypeError(
                        f"Gating variable '{var_name}' in Flow '{name}' is not a Boolean"
                    )

    @staticmethod
    def _expand_gating_config_vars(
        gating_config_vars: dict[str, list[str]],
        step_ids: Iterable[str],
    ) -> dict[str, list[str]]:
        """
        Expands gating keys, which may be exact step IDs or wildcards, against
        a concrete step ID list.

        A step matched by more than one key, whether exact or wildcard, is
        gated by the deduplicated union of their lists, order-preserving. The
        run loop requires every variable in a step's list to be true, so the
        union reads as "all of the conditions that named this step apply",
        which is the only reading under which a wildcard a flow author wrote
        cannot silently displace a stage gate generated for the same step.

        Shared between :meth:`run` and
        :meth:`librelane.flows.StagedFlow._preflight_views`, so that the
        preflight can never evaluate a different set of gates than the run it
        is meant to predict.

        :raises FlowException: If a gating key matches no step in ``step_ids``.
        """
        step_id_list = list(step_ids)
        expanded: dict[str, list[str]] = {}
        for key, value in gating_config_vars.items():
            if key in step_id_list:
                matched = [key]
            else:
                matched = list(Filter([key]).filter(step_id_list))
                if not matched:
                    # Checked per key rather than against `expanded`, whose
                    # entries are matched step IDs and so never contain a
                    # wildcard key even when it matched.
                    raise FlowException(
                        f"Gating key '{key}' matches no step in this run. A "
                        f"gating key that matches nothing silently fails to "
                        f"gate anything."
                    )
            for id in matched:
                expanded[id] = list(dict.fromkeys(expanded.get(id, []) + list(value)))
        return expanded

    def _after_step(self, step: Step, state: State, executed: bool) -> None:
        """
        Called once for every step in :attr:`Steps`, after it has run or been
        skipped. ``executed`` is False when the step was gated, skipped, or
        excluded by ``--from``/``--to``.

        Does nothing here. :class:`librelane.flows.StagedFlow` uses it to check
        the stage contract at each stage boundary. Note that
        ``create_reproducible`` breaks out of the run loop before this is
        reached, which is correct: a reproducible does not execute the flow.
        """

    @classmethod
    def Make(Self, step_ids: list[str]) -> type[SequentialFlow]:
        Step_list = []
        for name in step_ids:
            step = Step.factory.get(name)
            if step is None:
                raise TypeError(f"No step found with id '{name}'")
            Step_list.append(step)

        class CustomSequentialFlow(SequentialFlow):
            name = "Custom Sequential Flow"
            Steps = Step_list

        return CustomSequentialFlow

    @staticmethod
    def _normalize_step_ids(target: SequentialFlow | type[SequentialFlow]):
        ids_used: set[str] = set()

        for i, step in enumerate(target.Steps):
            counter = 0
            imp_id = step.get_implementation_id()
            id = imp_id
            if (
                id == NotImplemented
            ):  # Will be validated later by initialization: ignore for now
                continue
            while id in ids_used:
                counter += 1
                id = f"{imp_id}-{counter}"
            if id != step.id:
                target.Steps[i] = step.with_id(id)
            ids_used.add(id)

    def _step_ids_by_lowercase(self) -> dict[str, str]:
        """
        :returns: A mapping from each step's lowercased ID to the real one.
            Built in reverse so that the first step wins any collision, which
            duplicate-ID normalization should already have made impossible.
        """
        return {cls.id.lower(): cls.id for cls in reversed(self.Steps)}

    def _resolve_step_id(
        self,
        matchable: str | None,
        multiple_ok: bool = False,
    ) -> str | list[str] | None:
        """
        Resolves one ``--from``, ``--to``, ``--skip`` or ``--reproducible``
        argument against this flow's step list. Matching is case-insensitive
        and accepts wildcards.

        :param matchable: The argument, or ``None``.
        :param multiple_ok: Whether a key matching several steps is legal, as
            it is for ``--skip``.
        :returns: ``None``, a step ID, or a list of them when ``multiple_ok``.
        :raises FlowException: If the argument matches no step, or matches
            several when ``multiple_ok`` is false. A near miss above the fuzzy
            score cutoff is named in the message as a suggestion, and is not
            acted on: a flow that ran a step the user did not name is worse
            than one that stopped.
        """
        if matchable is None:
            return None
        step_ids = self._step_ids_by_lowercase()
        ids = list(Filter([matchable.lower()]).filter(step_ids))
        if len(ids) > 0:
            if multiple_ok:
                return [step_ids[id] for id in ids]
            if len(ids) > 1:
                raise FlowException(f"{matchable} matched multiple steps.")
            return step_ids[ids[0]]

        match_tuple = process.extractOne(
            matchable,
            step_ids,
            scorer=fuzz.partial_ratio,
            score_cutoff=80,
            processor=utils.default_process,
        )
        suggestion = ""
        if match_tuple is not None:
            match, _, _ = match_tuple
            suggestion = f" Did you mean: '{match}'?"
        raise FlowException(
            f"Failed to process '{matchable}': no step(s) with ID "
            f"'{matchable}' found in flow.{suggestion}"
        )

    def explain(
        self,
        *,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
    ) -> Explanation:
        """
        :param frm: As :meth:`run`.
        :param to: As :meth:`run`.
        :param skip: As :meth:`run`.
        :returns: One entry per step in this flow's resolved step list, in
            execution order, stating whether the step will run under this
            configuration and these flow-control arguments, and if not, which
            mechanism excluded it, together with the stages that contributed no
            steps at all.

        Resume is deliberately not reported. A resume verdict depends on
        content fingerprints of files that later steps in the same run will
        rewrite, so it cannot be known before the run. This says what the flow
        will attempt, not which attempts will be served from cache.
        """
        frm_resolved = self._resolve_step_id(frm)
        to_resolved = self._resolve_step_id(to)
        skipped_ids: list[str] = []
        for skipped_step in skip or []:
            resolved = self._resolve_step_id(skipped_step, multiple_ok=True)
            # `skipped_step` is never None and `multiple_ok` is set, so the
            # other two arms of the return type are unreachable here.
            assert isinstance(resolved, list)
            skipped_ids += resolved

        gating = self._expand_gating_config_vars(
            self.gating_config_vars,
            [cls.id for cls in self.Steps],
        )

        dispositions: list[StepDisposition] = []
        executing = frm is None
        stopped = False
        for cls in self.Steps:
            if frm_resolved is not None and frm_resolved == cls.id:
                executing = True

            gated_by = [
                variable
                for variable in gating.get(cls.id, [])
                if not self.config[variable]
            ]
            if gated_by:
                disposition = StepDisposition(
                    cls.id,
                    False,
                    f"gated off by {', '.join(gated_by)}",
                    "gate",
                )
            elif cls.id in skipped_ids:
                disposition = StepDisposition(cls.id, False, "named by --skip", "skip")
            elif stopped:
                disposition = StepDisposition(
                    cls.id, False, f"after --to '{to_resolved}'", "window"
                )
            elif not executing:
                disposition = StepDisposition(
                    cls.id, False, f"before --from '{frm_resolved}'", "window"
                )
            else:
                disposition = StepDisposition(cls.id, True, "will run", None)
            dispositions.append(disposition)

            if to_resolved and to_resolved == cls.id:
                executing = False
                stopped = True

        return Explanation(tuple(dispositions), ())

    def run(
        self,
        initial_state: State,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
        reproducible: str | None = None,
        initial_state_given: bool = False,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        Runs the flow's steps in order, reusing each step whose configuration
        and input state are unchanged from a previous run of the same tag.

        :param initial_state: The state handed to the first step.
        :param frm: Force re-execution from this step onward, ignoring any
            reusable result for it and every step after it.

            Steps before it are taken from their previous results. If any of them
            has no reusable result, a :class:`FlowException` is raised naming it,
            because its output state is then unavailable and there is nothing
            honest to run the rest of the flow on.

            This is the remedy for the one thing a resume key does not cover: a
            CAD tool upgraded in place, or a script edited in a development
            checkout, under an unchanged LibreLane version.

            When ``initial_state_given`` is set, the steps before it are skipped
            instead, because the caller has supplied what they would have
            produced.
        :param to: Stop after this step.
        :param skip: Step IDs to skip. A skipped step changes what the steps
            after it receive, so they cannot be reused either.
        :param reproducible: Create a reproducible for this step instead of
            running the rest of the flow.
        :param initial_state_given: Whether ``initial_state`` was supplied by the
            caller rather than being the empty state a run starts from. It is
            what stands in for the steps before ``frm``, so they are neither
            re-run nor resolved from their previous results.
        :returns: ``(final_state, steps_run)``
        """
        logger.debug(f"Starting run ▶ '{self.run_dir}'")
        skipped_ids: list[str] = []

        frm_resolved = self._resolve_step_id(frm)

        to_resolved = self._resolve_step_id(to)

        reproducible_resolved = self._resolve_step_id(reproducible)

        if skipped_steps := skip:
            for skipped_step in skipped_steps:
                resolved = self._resolve_step_id(skipped_step, multiple_ok=True)
                # `skipped_step` is never None and `multiple_ok` is set, so the
                # other two arms of the return type are unreachable here.
                assert isinstance(resolved, list)
                skipped_ids += resolved

        step_count = len(self.Steps)
        self.progress_bar.set_max_stage_count(step_count)

        step_list = []

        logger.info("Starting…")

        executing = frm is None
        deferred_errors = []
        reused_count = 0
        executed_count = 0
        forced = False
        stopped = False

        gating_cvars_expanded = self._expand_gating_config_vars(
            self.gating_config_vars,
            [cls.id for cls in self.Steps],
        )

        current_state = initial_state
        for position, cls in enumerate(self.Steps):
            step = cls(config=self.config, state_in=current_state)
            step_dir = self.dir_for_step(step, position=position)
            if frm_resolved is not None and frm_resolved == step.id:
                executing = True
                forced = True

            gated_by = [
                variable
                for variable in gating_cvars_expanded.get(step.id, [])
                if not self.config[variable]
            ]
            explicitly_skipped = cls.id in skipped_ids

            self.progress_bar.start_stage(step.name)
            executed = True
            if cls.id == reproducible_resolved:
                # Ahead of every skip test, so that a request for a step this
                # configuration would never execute is diagnosed rather than
                # silently discarded.
                if gated_by:
                    raise FlowException(
                        f"Cannot create a reproducible for step '{step.id}': it "
                        f"is gated off by {', '.join(gated_by)}, so this "
                        f"configuration would never execute it. Set "
                        f"{' and '.join(gated_by)} to true, or name another step."
                    )
                if explicitly_skipped:
                    raise FlowException(
                        f"Cannot create a reproducible for step '{step.id}': it "
                        f"is named by --skip, so this run would never execute "
                        f"it. Drop it from --skip, or name another step."
                    )
                step.create_reproducible(step_dir / "reproducible")
                break
            elif gated_by:
                logger.info(
                    f"Skipping step '{step.name}': gated off by {', '.join(gated_by)}."
                )
                executed = False
            elif explicitly_skipped:
                logger.info(f"Skipping step '{step.name}': named by --skip.")
                executed = False
            elif stopped:
                # Past --to. Nothing downstream will ask for this step's output,
                # so unlike the steps before --from it does not have to be
                # resolved at all.
                logger.info(f"Skipping step '{step.name}': after --to '{to_resolved}'.")
                executed = False
            elif not executing and initial_state_given:
                # Before --from, but the caller handed us the state that stands
                # in for these steps. Resolving them would discard it.
                logger.info(
                    f"Skipping step '{step.name}': before --from "
                    f"'{frm_resolved}', and an initial state was supplied."
                )
                executed = False
            elif not executing:
                # Before --from. The step is not re-run, but the next step needs
                # its output, so it has to come from cache. There is nowhere else
                # for it to come from now that a run's state is not reconstructed
                # by modification time.
                assert self.fingerprinter is not None
                key = resume_key(step, current_state, self.fingerprinter)
                reused = reusable_state(step_dir, key, self.fingerprinter)
                if reused is None:
                    raise FlowException(
                        f"Cannot start from '{frm_resolved}': step '{step.id}' "
                        f"comes earlier and has no reusable result, so its "
                        f"output state is unavailable. Re-run without --from, "
                        f"or use --overwrite to start the tag clean."
                    )
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                current_state = reused
                step_list.append(step)
                reused_count += 1
            else:
                assert self.fingerprinter is not None
                key = resume_key(step, current_state, self.fingerprinter)
                reused = (
                    None
                    if forced
                    else reusable_state(step_dir, key, self.fingerprinter)
                )
                if reused is not None:
                    logger.info(f"Reusing '{step.name}' from a previous run…")
                    step.step_dir = step_dir
                    step.state_out = reused
                    current_state = reused
                    step_list.append(step)
                    reused_count += 1
                else:
                    shutil.rmtree(step_dir, ignore_errors=True)
                    step_list.append(step)
                    try:
                        current_state = step.start(
                            toolbox=self.toolbox,
                            step_dir=step_dir,
                        )
                    except StepException as e:
                        raise FlowException(str(e)) from None
                    except DeferredStepError as e:
                        # current_state keeps its pre-failure value, while
                        # executed stays True, so the _after_step hook below
                        # sees the step as executed against a state that never
                        # received its output. That matters to
                        # librelane.flows.StagedFlow, which checks a stage
                        # contract there: a provider whose final step both emits
                        # a contracted metric and defers an error would raise
                        # StageContractError and bury the real deferred error.
                        # No provider does today.
                        deferred_errors.append(str(e))
                    except StepError as e:
                        raise FlowError(str(e)) from None
                    else:
                        # Only on a clean return. A step that deferred an error
                        # gets no entry, so it runs again next time and raises
                        # again, with no bookkeeping needed to remember that.
                        write_entry(step_dir, step, key)
                    executed_count += 1

            self.progress_bar.end_stage(increment_ordinal=executed)

            # A reused step produced its views and metrics as surely as one that
            # just ran, and they are in the state being checked, so the stage
            # contract still applies to it.
            self._after_step(step, current_state, executed)

            if to_resolved and to_resolved == step.id:
                executing = False
                stopped = True

        assert self.run_dir is not None
        logger.debug(f"Run concluded ▶ '{self.run_dir}'")
        final_views_path = self.run_dir / "final"
        try:
            current_state.save_snapshot(final_views_path)
        except Exception as e:
            raise FlowException(f"Failed to save final views: {e}")

        if len(deferred_errors) != 0:
            raise FlowError(
                "One or more deferred errors were encountered:\n"
                + "\n".join(deferred_errors)
            )

        if reused_count:
            logger.info(
                f"Reused {reused_count} step(s) from a previous run; "
                f"executed {executed_count}."
            )

        logger.success("Flow complete.")
        return (current_state, step_list)
