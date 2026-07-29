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

import os
import fnmatch
from typing import (
    Union,
)
from collections.abc import Iterable

from deprecated.sphinx import deprecated
from rapidfuzz import process, fuzz, utils

from .flow import Flow, FlowException, FlowError
from ..common import Filter
from ..state import State
from ..steps import (
    Step,
    StepError,
    StepException,
    DeferredStepError,
)

Substitution = Union[str, type[Step], None]
SubstitutionsObject = Union[
    dict[str, Substitution],
    list[tuple[str, Substitution]],
]


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

    :param Substitute: Substitute all instances of one `Step` type by another `Step`
        type in the :attr:`.Steps` attribute for this instance only.

        You may also use the string Step IDs in place of a `Step` type object.

        Duplicate ID normalization is re-run after substitutions.

    :param args: Arguments for :class:`Flow`.
    :param kwargs: Keyword arguments for :class:`Flow`.

    :cvar gating_config_vars: A mapping from step ID (wildcards) to lists of
        Boolean variable names. All Boolean variables must be True for a step with
        a specific ID to execute.

    :cvar Substitutions: Consumed by the subclass initializer - allows for a
        quick interface where steps can be removed, replaced, appended or
        prepended. After subclass intialization, it is set to ``None``, and
        a new subclass must be created to modify substitutions further.

        The list of substitutions may be specified as either a dictionary
        or a list of tuples: while the former is more terse, the latter is
        allows using the same key more than once.

        The substitutions are mappings from Step IDs or objects to Step IDs,
        objects, or ``None``. In case of ``None``, the step in question is
        removed.

        In case the key is specified as a string, you may add ``-`` as a prefix
        to the Step ID to indicate you want to insert a step before the step
        in question, and similary ``+`` indicates you want to insert a step
        after the step in question. You may not prepend or append ``None``.

        Step IDs are made unique after every substitution, i.e., whenever the
        substitution occurs, the first instance of a Step in a sequential flow
        shall have its ID unadulterated, while the next instance will have
        ``-1``, the one after ``-2``, etc. If ``-1`` is removed, the previous
        ``-2`` shall become ``-1``, for example.
    """

    Substitutions: SubstitutionsObject | None = None
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
        if Self.Substitutions:
            Self.__substitute_in_place(Self, Self.Substitutions)
            Self.Substitutions = None

        Self._validate_gating_config_vars(Self)

    @staticmethod
    def _validate_gating_config_vars(target: SequentialFlow | type[SequentialFlow]):
        """
        Checks that every gating key names at least one step in ``target`` and
        that every gating variable is a declared Boolean.

        Separate from ``__init_subclass__`` so that :class:`StagedFlow` can
        re-run it after generating gating entries from stage gates, which it can
        only do once step IDs have been normalized and substitutions applied.
        Takes a target, like ``_normalize_step_ids``, because instance-level
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

    @classmethod
    @deprecated(
        "use .Make",
        version="3.0.0",
        action="once",
    )
    def make(Self, step_ids: list[str]) -> type[SequentialFlow]:
        return Self.Make(step_ids)

    @classmethod
    def Substitute(Self, Substitutions: SubstitutionsObject) -> type[SequentialFlow]:
        """
        Convenience method to quickly subclass a sequential flow and add
        Substitutions to it.

        The new flow shall be named ``{previous_flow_name}'``.

        :param Substitutions: The substitutions to use for the new subclass.
        """
        return type(Self.__name__ + "'", (Self,), {"Substitutions": Substitutions})

    @staticmethod
    def __substitute_in_place(
        target: type[SequentialFlow],
        Substitutions: SubstitutionsObject | None,
    ):
        if Substitutions is None:
            return Substitutions
        if isinstance(Substitutions, dict):
            for key, item in Substitutions.items():
                target.__substitute_step(target, key, item)
        else:
            for key, item in Substitutions:
                target.__substitute_step(target, key, item)

    @staticmethod
    def __substitute_step(
        target: SequentialFlow | type[SequentialFlow],
        id: str,
        with_step: str | type[Step] | None,
    ):
        step_indices: list[int] = []
        mode = "replace"
        if id.startswith("+"):
            id = id[1:]
            mode = "append"
            if with_step is None:
                raise FlowException("Cannot prepend or append None.")
        elif id.startswith("-"):
            id = id[1:]
            mode = "prepend"
            if with_step is None:
                raise FlowException("Cannot prepend or append None.")

        for i, step in enumerate(target.Steps):
            if (
                step.id
                != NotImplemented  # Will be validated later by initialization: ignore for now
                and fnmatch.fnmatch(step.id.lower(), id.lower())
            ):
                step_indices.append(i)
        if len(step_indices) == 0:
            if with_step is None:
                raise FlowException(
                    f"Could not remove '{id}': no steps with ID '{id}' found in flow"
                )
            raise FlowException(
                f"Could not {mode} '{id}' with '{with_step}': no steps with ID '{id}' found in flow."
            )

        if with_step is None:
            for index in reversed(step_indices):
                del target.Steps[index]
        else:
            if isinstance(with_step, str):
                with_step_opt = Step.factory.get(with_step)
                if with_step_opt is None:
                    raise FlowException(
                        f"Could not {mode} '{id}' with '{with_step}': no replacement step with ID '{with_step}' found."
                    )
                with_step = with_step_opt

            for i in step_indices:
                if mode == "replace":
                    target.Steps[i] = with_step
                elif mode == "append":
                    target.Steps.insert(i + 1, with_step)
                elif mode == "prepend":
                    target.Steps.insert(i, with_step)
        target._normalize_step_ids(target)

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

    def run(
        self,
        initial_state: State,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
        reproducible: str | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        logger.debug(f"Starting run ▶ '{self.run_dir}'")
        step_ids = {cls.id.lower(): cls.id for cls in reversed(self.Steps)}
        skipped_ids: list[str] = []

        def resolve_step(matchable: str | None, multiple_ok: bool = False):
            nonlocal step_ids
            dangerous_fuzzy_matching = (
                os.getenv(
                    "_i_want_librelane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks",
                    None,
                )
                == "1"
            )
            if matchable is None:
                return None
            ids = list(Filter([matchable.lower()]).filter(step_ids))
            if len(ids) > 0:
                if multiple_ok:
                    return [step_ids[id] for id in ids]
                if len(ids) > 1:
                    raise FlowException(f"{matchable} matched multiple steps.")
                if len(ids) == 1:
                    return step_ids[ids[0]]
            else:
                matchTuple = process.extractOne(
                    matchable,
                    step_ids,
                    scorer=fuzz.partial_ratio,
                    score_cutoff=80,
                    processor=utils.default_process,
                )
                suggestion = ""
                if matchTuple is not None:
                    match, _, _ = matchTuple
                    if dangerous_fuzzy_matching:
                        return [match] if multiple_ok else match
                    else:
                        suggestion = f" Did you mean: '{match}'?"
                raise FlowException(
                    f"Failed to process '{matchable}': no step(s) with ID '{matchable}' found in flow.{suggestion}"
                )

        frm_resolved = resolve_step(frm)

        to_resolved = resolve_step(to)

        reproducible_resolved = resolve_step(reproducible)

        if skipped_steps := skip:
            for skipped_step in skipped_steps:
                skipped_ids += resolve_step(skipped_step, multiple_ok=True)

        step_count = len(self.Steps)
        self.progress_bar.set_max_stage_count(step_count)

        step_list = []

        logger.info("Starting…")

        executing = frm is None
        deferred_errors = []

        gating_cvars_expanded: dict[str, list[str]] = {}
        for key, value in self.gating_config_vars.items():
            if key in step_ids.values():
                gating_cvars_expanded[key] = value
                continue
            matched = list(Filter([key]).filter(step_ids.values()))
            if not matched:
                # Checked per key rather than against gating_cvars_expanded,
                # whose entries are matched step IDs and so never contain a
                # wildcard key even when it matched.
                raise FlowException(
                    f"Gating key '{key}' matches no step in this run. A gating "
                    f"key that matches nothing silently fails to gate anything."
                )
            for id in matched:
                gating_cvars_expanded[id] = value

        current_state = initial_state
        for cls in self.Steps:
            step = cls(config=self.config, state_in=current_state)
            if frm_resolved is not None and frm_resolved == step.id:
                executing = True

            gated = False
            if gating_cvars := gating_cvars_expanded.get(step.id):
                for variable in gating_cvars:
                    if not self.config[variable]:
                        logger.info(
                            f"Gating variable for step '{step.id}' set to 'False'- the step will be skipped."
                        )
                        gated = True

            self.progress_bar.start_stage(step.name)
            increment_ordinal = True
            if not executing or cls.id in skipped_ids or gated:
                logger.info(f"Skipping step '{step.name}'…")
                increment_ordinal = False
            elif cls.id == reproducible_resolved:
                step.create_reproducible(self.dir_for_step(step) / "reproducible")
                break
            else:
                step_list.append(step)
                try:
                    current_state = step.start(
                        toolbox=self.toolbox,
                        step_dir=self.dir_for_step(step),
                    )
                except StepException as e:
                    raise FlowException(str(e)) from None
                except DeferredStepError as e:
                    deferred_errors.append(str(e))
                except StepError as e:
                    raise FlowError(str(e)) from None

            self.progress_bar.end_stage(increment_ordinal=increment_ordinal)

            # increment_ordinal is already False on every non-executing path
            # and True only when the step actually ran, so it is exactly the
            # executed signal with no new bookkeeping.
            self._after_step(step, current_state, increment_ordinal)

            if to_resolved and to_resolved == step.id:
                executing = False

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

        logger.success("Flow complete.")
        return (current_state, step_list)
