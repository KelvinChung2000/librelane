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
"""A sequential flow whose step list is expanded from a list of stages."""

from dataclasses import dataclass, replace
from collections.abc import Iterable, Mapping, Sequence
from typing import Optional, Union

from loguru import logger

from librelane.common import Filter, parse_metric_modifiers
from librelane.config import Config as ResolvedConfig, variable
from librelane.stages.registry import StageRegistry
from librelane.stages.resolution import (
    Resolution,
    ResolvedSpan,
    StageEntry,
    ToolSelection,
    resolve,
)
from librelane.stages.stage import (
    Stage,
    StageContractError,
    StageResolutionError,
)
from librelane.stages.tools import extract_tools
from librelane.state import DesignFormat, State
from librelane.steps import Step

from librelane.flows.explanation import Explanation
from librelane.flows.sequential import SequentialFlow


@dataclass(frozen=True)
class Boundary:
    """
    A contiguous run of resolved steps belonging to one stage, and the contract
    that must hold once its last step completes.

    Parameters
    ----------
    provider : str
        The provider whose obligation this boundary carries. A
        single name for a boundary covering one provider's steps, and the
        selected names joined by ``+`` for one covering a whole
        ``multi_provider`` stage.
    """

    stage_ids: tuple[str, ...]
    provider: str
    step_ids: tuple[str, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]

    @property
    def last_step_id(self) -> str:
        return self.step_ids[-1]


class StagedFlow(SequentialFlow):
    """
    A :class:`SequentialFlow` whose step list is expanded from a list of
    :class:`librelane.stages.Stage` objects, so the tool used for each phase
    can be chosen from configuration rather than by subclassing the flow.

    Attributes
    ----------
    Stages : list[StageEntry]
        The flow in stage terms. Entries are either ``Stage``
        objects, which expand to whichever provider is selected, or plain
        ``Step`` classes, which are provider-neutral utilities and boundary
        observations. A plain step entry is only meaningful at a stage
        boundary.

    ``Steps`` is expanded from ``Stages`` at class-definition time using each
    stage's ``default_provider``, so it is a fully populated list at import and
    every existing ``SequentialFlow`` facility keeps working unchanged:
    ``get_help_md``, step IDs and step directory names.
    """

    Stages: list[StageEntry] = []

    #: Overridden from ``Flow``, where it is ``NotImplemented``. ``StagedFlow``
    #: populates it from ``Stages``, but the class body of ``StagedFlow``
    #: itself runs ``SequentialFlow.__init_subclass__``, which copies ``Steps``
    #: unconditionally.
    Steps: list[type[Step]] = []

    #: The gating entries a flow author wrote by hand, as opposed to those
    #: generated from stage gates. Kept apart because generated entries name
    #: concrete step IDs and so must be rebuilt for every subclass: a subclass
    #: declaring its own ``Stages`` produces different ones, which would
    #: otherwise leave an inherited entry naming a step that is not in the
    #: flow.
    _explicit_gating_config_vars: dict[str, list[str]] = {}

    #: The resolution ``Steps`` was expanded from. Its spans carry the
    #: ``provides`` and ``metrics`` of the providers actually selected, which
    #: the taxonomy alone does not know. Empty for a subclass that declares
    #: ``Steps`` directly and so has no stages.
    _resolution: Resolution = Resolution([], [], ())

    class Config(SequentialFlow.Config):
        TOOLS: Optional[dict[str, Union[str, list[str]]]] = variable(
            None,
            description=(
                "A mapping from stage id to the provider (tool) implementing "
                "it, for example {'synthesis': 'genus'}. Only overrides need "
                "listing; an unnamed stage uses its default provider. Must be a "
                "literal mapping, as it is read before the configuration "
                "preprocessor runs, and so cannot come from the PDK."
            ),
        )

    def __init_subclass__(Self, scm_type=None, name=None, **kwargs):
        if "Stages" in Self.__dict__:
            Self.Stages = list(Self.Stages)
            resolution = resolve(Self.Stages, {})
            Self.Steps = resolution.steps
            Self._resolution = resolution
            Self.__report_unselected(resolution)
        elif "Steps" not in Self.__dict__ and not Self.Stages:
            # Steps defaults to [] rather than NotImplemented so that defining
            # StagedFlow itself does not trip SequentialFlow.__init_subclass__.
            # That default would otherwise turn a forgotten Stages list into a
            # flow that runs nothing, which is exactly the silent failure the
            # NotImplemented sentinel exists to prevent.
            raise TypeError(
                f"StagedFlow subclass '{Self.__qualname__}' declares neither "
                f"'Stages' nor 'Steps'. Declare 'Stages' to expand a flow from "
                f"the stage taxonomy, or 'Steps' to bypass it."
            )

        if "gating_config_vars" in Self.__dict__:
            Self._explicit_gating_config_vars = dict(Self.gating_config_vars)
        Self.gating_config_vars = dict(Self._explicit_gating_config_vars)

        # Step IDs are only final once the base class has normalized
        # duplicates, so gates cannot be generated until after.
        super().__init_subclass__(scm_type=scm_type, name=name, **kwargs)
        Self._apply_stage_gating(Self)
        Self._validate_gating_config_vars(Self)

    def __init__(
        self,
        config,
        *,
        config_override_strings: Sequence[str] | None = None,
        **kwargs,
    ):
        tools = self.__selected_tools(config, config_override_strings)
        # Resolved unconditionally, not only when tools overrides something,
        # so that _resolution is always populated by the time the preflights
        # run below: their spans are the only place a selected provider's PDK
        # requirements and native views live. Compared against the class-level
        # resolution, not self.Steps, because a bypassed flow (Steps declared
        # directly, no Stages) has a self.Steps that legitimately differs from
        # what resolving its (possibly empty)
        # Stages produces; _resolution is what __init_subclass__ actually
        # derived Steps from, and is the correct baseline for "did TOOLS
        # change anything".
        resolution = resolve(self.Stages, tools)
        reexpanded = [step.id for step in resolution.steps] != [
            step.id for step in self._resolution.steps
        ]
        # Assigned before the re-expansion below rather than after, because
        # _apply_stage_gating reads each stage's gate off the spans.
        self._resolution = resolution
        if reexpanded:
            # Re-expansion happens before super().__init__, because that is
            # where get_all_config_variables() reads self.Steps to build the
            # model configuration is validated against. The whole reason the
            # TOOLS pre-pass exists is that the step set has to be known first.
            self.Steps = resolution.steps
            self._normalize_step_ids(self)
            self._apply_stage_gating(self)
            self.__prune_deselected_gates(self)

        super().__init__(
            config,
            config_override_strings=config_override_strings,
            **kwargs,
        )

        self.__executed_step_ids: set[str] = set()
        # A list per step, not one boundary: the last provider's boundary and the
        # boundary covering the whole stage necessarily end on the same step.
        self.__boundaries_by_last_step: dict[str, list[Boundary]] = {}
        for boundary in self._boundaries(self):
            self.__boundaries_by_last_step.setdefault(boundary.last_step_id, []).append(
                boundary
            )
        self._preflight_views()

    def _preflight_views(self) -> None:
        """
        Walks the resolved step list checking that every non-optional input a
        step consumes is produced by some earlier step.

        Steps whose gating variables are false in the resolved configuration are
        excluded, because they will not run. Gating is evaluated here rather
        than at run time so that a configuration which removes a producer, such
        as selecting a synthesis provider that emits no Verilog header, fails
        before any tool is invoked.
        """
        available: set[str] = set()
        last_stage = "<start of flow>"
        gates_by_step_id = self.__gates_by_step_id()

        for step in self.Steps:
            gates = gates_by_step_id.get(step.id, [])
            if any(not self.config[gate] for gate in gates):
                continue
            for view in step.inputs:
                # An optional input is satisfiable by absence.
                # DesignFormat.mkOptional() returns a copy with a flag set,
                # which compares unequal to the base view, so the flag has to
                # be tested before the membership check.
                if view.optional or view.id in available:
                    continue
                raise StageResolutionError(
                    f"step '{step.id}' consumes view '{view.id}', which no "
                    f"earlier step in this configuration produces. The last "
                    f"stage before it is {last_stage}. "
                    f"{self.__how_to_produce(view)}"
                )
            for view in step.outputs:
                available.add(view.id)
            span = getattr(step, "_stage_span", None)
            if span is not None:
                last_stage = (
                    f"'{span[-1]}' (provider '{getattr(step, '_stage_provider', '?')}')"
                )

    @staticmethod
    def __how_to_produce(view: DesignFormat) -> str:
        """
        Returns
        -------
        str
            The remedial half of a preflight error: which registered
            provider declares this view, so the reader is not left working out
            for themselves which tool they dropped.

        Searches both ``provides`` and ``native_views``. A view such as
        OpenROAD's ``odb`` never appears in any registration's ``provides``:
        it is carried natively across a provider's own stage boundaries
        rather than produced as a neutral output. Omitting ``native_views``
        would misreport an orphaned consumer of such a view as one no
        registration declares at all, which is false and leaves the reader
        with no lead on which tool they dropped.
        """
        provides_producers = sorted(
            {
                f"provider '{registration.provider}' of stage '{registration.stage}'"
                for registration in StageRegistry.list()
                if view in registration.provides
            }
        )
        native_producers = sorted(
            {
                f"provider '{registration.provider}' of stage "
                f"'{registration.stage}' (natively, as an internal carry-over "
                f"between its own steps rather than a declared neutral output)"
                for registration in StageRegistry.list()
                if view in registration.native_views
            }
        )
        producers = provides_producers + native_producers
        if producers:
            return (
                f"View '{view.id}' is declared by {' and '.join(producers)}, "
                f"which this configuration did not select. Select it in TOOLS, "
                f"or use a flow whose stages do not include this step."
            )
        return (
            f"No provider registration declares view '{view.id}', so the step "
            f"that would have produced it was removed by a gating variable or "
            f"by a provider selection."
        )

    def __gates_by_step_id(self) -> dict[str, list[str]]:
        """
        Returns
        -------
        dict[str, list[str]]
            The gating variables in force for each step ID, expanded by
            the same :meth:`SequentialFlow._expand_gating_config_vars` helper
            :meth:`SequentialFlow.run` uses.

        Sharing the helper, rather than re-implementing wildcard expansion
        here, is what keeps the preflight from disagreeing with the run it is
        meant to predict: a step excluded by a wildcard gate must be excluded
        from the view walk as well, and a colliding exact and wildcard key
        must union to the same variable list in both places.
        """
        step_ids = [step.id for step in self.Steps]
        return self._expand_gating_config_vars(self.gating_config_vars, step_ids)

    @staticmethod
    def _boundaries(target) -> list[Boundary]:
        """
        Every contract to check for ``target``, with each boundary's contract
        taken from the resolution rather than from the taxonomy. Only the
        resolution knows which providers were selected, and a
        :class:`librelane.stages.Registration` may declare ``provides`` and
        ``metrics`` beyond its stage's.

        There are two contracts per stage, at two granularities, because the two
        say different things on a ``multi_provider`` stage:

        * The stage's own ``provides``/``metrics``, checked once the whole stage
          has run. This obligation is satisfied by the selected providers
          jointly: both ``streamout`` tools stream out, but only the one named
          by ``PRIMARY_GDSII_STREAMOUT_TOOL`` writes the neutral ``gds`` view.
        * Each provider's own, checked once that provider's steps have run, so
          that gating one tool of a stage off leaves the other still answerable
          for its metric.

        For a single-provider stage the two cover the same steps and their union
        is the whole contract, so no special case is needed.
        """
        result: list[Boundary] = []
        for boundary in StagedFlow.stage_boundaries(target.Steps):
            span = StagedFlow._span_for(target, boundary)
            result.append(
                replace(boundary, provides=span.provides, metrics=span.metrics)
            )
        for boundary in StagedFlow.provider_boundaries(target.Steps):
            contract = StagedFlow._span_for(target, boundary).contract_for(
                boundary.provider
            )
            result.append(
                replace(boundary, provides=contract.provides, metrics=contract.metrics)
            )
        return result

    @staticmethod
    def _span_for(target, boundary: Boundary) -> ResolvedSpan:
        """
        Returns
        -------
        ResolvedSpan
            The resolved span the steps of ``boundary`` were expanded from.

        Raises
        ------
        StageResolutionError
            If the resolution does not cover that
            stage, which means the step tags and the resolution disagree.

        Every tagged step in a ``StagedFlow``'s ``Steps`` came out of that flow's
        own resolution, whether directly or through ``Step.with_id``, so a
        miss here is a programming error rather than a configuration mistake. It has to be loud either way, because both callers
        would otherwise carry on with an unenforced contract or an ungated stage.
        """
        for span in target._resolution.spans:
            if span.stage_ids == boundary.stage_ids:
                return span
        name = getattr(target, "__qualname__", type(target).__qualname__)
        raise StageResolutionError(
            f"flow '{name}' has steps tagged for stage "
            f"{list(boundary.stage_ids)}, which its own resolution does not "
            f"cover. A 'Steps' list may not be assembled out of the steps "
            f"another flow's 'Stages' expanded to."
        )

    def _after_step(self, step: Step, state: State, executed: bool) -> None:
        if executed:
            self.__executed_step_ids.add(step.id)
        # Note for a backend author: on a DeferredStepError,
        # SequentialFlow.run leaves current_state at its pre-failure value while
        # still reporting the step as executed, so a boundary ending on a step
        # that both emits a contracted metric and defers an error is checked
        # against a state that cannot contain the metric. It would then raise
        # StageContractError and bury the real deferred error. No provider is
        # affected today: every contracted metric is emitted by a step earlier in
        # its provider's sequence than the checker that defers.
        for boundary in self.__boundaries_by_last_step.get(step.id, []):
            if not all(
                step_id in self.__executed_step_ids for step_id in boundary.step_ids
            ):
                # A run that did not execute every step cannot be held to its
                # contract: the views and metrics were never attempted.
                logger.debug(
                    f"stage {list(boundary.stage_ids)}, provider "
                    f"'{boundary.provider}': not every step ran, contract not "
                    f"checked"
                )
                continue
            self.__check_contract(boundary, state)

    @staticmethod
    def __check_contract(boundary: Boundary, state: State) -> None:
        missing_views = [
            view.id for view in boundary.provides if state.get(view.id) is None
        ]
        # Compared on base names, so a provider emitting only modified variants
        # of a contracted metric, as GeneratePDN does per net, still satisfies it.
        produced = {parse_metric_modifiers(name)[0] for name in state.metrics}
        missing_metrics = [name for name in boundary.metrics if name not in produced]
        if not missing_views and not missing_metrics:
            return
        parts = []
        if missing_views:
            parts.append(f"views {missing_views}")
        if missing_metrics:
            parts.append(f"metrics {missing_metrics}")
        raise StageContractError(
            f"stage {list(boundary.stage_ids)}, provider "
            f"'{boundary.provider}', completed without producing "
            f"{' and '.join(parts)}. It is contracted to produce them; a stage "
            f"whose contract is not met cannot be handed to the next stage."
        )

    @classmethod
    def __selected_tools(
        Self,
        config,
        config_override_strings: Sequence[str] | None,
    ) -> Mapping[str, ToolSelection]:
        """
        Returns
        -------
        Mapping[str, ToolSelection]
            The ``TOOLS`` mapping, read from raw sources by the pre-pass
            or taken directly from an already-resolved configuration.
        """
        if isinstance(config, ResolvedConfig):
            # Already validated, so TOOLS is present and typed. Checked before
            # Mapping, which a resolved Config also satisfies.
            return dict(config.get("TOOLS") or {})
        sources = list(config) if isinstance(config, (list, tuple)) else [config]
        return extract_tools(
            sources,
            config_override_strings=config_override_strings,
        )

    @staticmethod
    def __prune_deselected_gates(target) -> None:
        """
        Drops gating entries naming a step the resolved provider did not
        produce.

        Correct only at instance time. A flow's hand-written gating keys are
        validated against the default expansion when the class is defined, so a
        key matching nothing *here* names a step that a provider selection
        removed, for example ``Magic.StreamOut`` once ``TOOLS`` picks klayout
        alone for ``streamout``. Such a gate is moot rather than wrong, and
        erroring on it would make provider selection unusable for precisely the
        multi-tool stages it exists to serve.
        """
        step_ids = [step.id for step in target.Steps]
        kept: dict[str, list[str]] = {}
        for key, value in target.gating_config_vars.items():
            if key in step_ids or list(Filter([key]).filter(step_ids)):
                kept[key] = value
                continue
            logger.debug(
                f"gating key '{key}' names no selected step; the gate is moot "
                f"under this TOOLS selection and was dropped"
            )
        target.gating_config_vars = kept

    @staticmethod
    def _apply_stage_gating(target) -> None:
        """
        Turns each stage's ``gating_config_var`` into step-level gating entries
        covering every step of the provider resolved for ``target``.

        Reusing the existing step-level mechanism rather than adding a parallel
        one means gating behaves identically whichever provider is selected,
        which is the whole point: ``RUN_CTS`` gates the ``cts`` stage no matter
        what implements it.

        Takes a target rather than binding to a class because instance-level
        ``TOOLS`` rebuilds ``Steps`` on the instance.

        The gate is read off the resolution rather than looked back up from
        ``Stage.factory``, so that a flow placing a modified copy of a stage in
        its ``Stages`` list, as ``replace(Stage.cts, gating_config_var="MY_GATE")``,
        is gated by the variable it asked for. The registered stage is a default,
        not the authority, in the same way ``Stage.using`` makes a pinned provider
        a default.
        """
        generated: dict[str, list[str]] = {}
        for boundary in StagedFlow.stage_boundaries(target.Steps):
            gate = StagedFlow._span_for(target, boundary).gating_config_var
            if gate is None:
                continue
            for step_id in boundary.step_ids:
                generated.setdefault(step_id, []).append(gate)

        merged = generated
        for key, value in target._explicit_gating_config_vars.items():
            # dict.fromkeys deduplicates while preserving order, so a variable
            # that is both a stage gate and an explicit entry appears once.
            merged[key] = list(dict.fromkeys(merged.get(key, []) + list(value)))
        target.gating_config_vars = merged

    def explain(
        self,
        *,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
    ) -> Explanation:
        """
        As :meth:`librelane.flows.SequentialFlow.explain`, additionally
        reporting the stages that contributed no steps. Those are announced
        only at debug level during construction, so nothing else surfaces them.
        """
        return replace(
            super().explain(frm=frm, to=to, skip=skip),
            unselected_stages=tuple(self._resolution.unselected),
        )

    @classmethod
    def describe_stages(Self) -> list[tuple[str, Optional[str]]]:
        """
        Returns
        -------
        list[tuple[str, Optional[str]]]
            One entry per stage in ``Stages``, in flow order, pairing the
            stage id with the provider selected for it by default. The
            provider is ``None`` for an unselected optional stage, and several
            names joined by ``", "`` for a multi-provider stage.
        """
        described: list[tuple[str, Optional[str]]] = []
        for entry in Self.Stages:
            if not isinstance(entry, Stage):
                continue
            providers = entry.default_providers
            described.append((entry.id, ", ".join(providers) if providers else None))
        return described

    @classmethod
    def get_help_md(Self, myst_anchors: bool = False) -> str:  # pragma: no cover
        result = super().get_help_md(myst_anchors=myst_anchors)
        if not Self.Stages:
            return result
        result += "\n#### Stages\n\n"
        result += (
            "Set the `TOOLS` configuration variable to change the tool used "
            "for any of these. See "
            "[Swapping Tools](./swapping_tools.md).\n\n"
        )
        result += "| Stage | Default provider | Alternatives |\n"
        result += "| --- | --- | --- |\n"
        for stage_id, default in Self.describe_stages():
            selected = set((default or "").split(", "))
            others = [
                provider
                for provider in StageRegistry.providers(stage_id)
                if provider not in selected
            ]
            default_cell = (
                ", ".join(f"`{name}`" for name in default.split(", "))
                if default
                else "none selected"
            )
            others_cell = (
                ", ".join(f"`{name}`" for name in others) if others else "none"
            )
            result += f"| `{stage_id}` | {default_cell} | {others_cell} |\n"
        return result

    @staticmethod
    def __report_unselected(resolution: Resolution) -> None:
        for stage_id in resolution.unselected:
            logger.debug(f"stage '{stage_id}': no provider selected, skipped")

    @classmethod
    def stage_boundaries(Self, steps: list[type[Step]]) -> list[Boundary]:
        """
        Recovers the stage boundary map from a final step list by scanning for
        contiguous runs of steps carrying the same ``_stage_span`` tag.

        One boundary per stage: for a ``multi_provider`` stage its ``step_ids``
        are every selected provider's steps and its ``provider`` is their names
        joined by ``+``. See :meth:`provider_boundaries` for the finer grouping.

        The contract is left empty, because only the resolution knows which
        providers were selected and what each of them promised;
        :meth:`_boundaries` fills it in from there.
        """
        return Self.__runs(steps, lambda span, provider: span)

    @classmethod
    def provider_boundaries(Self, steps: list[type[Step]]) -> list[Boundary]:
        """
        As :meth:`stage_boundaries`, but one boundary per provider of a stage
        rather than one per stage, by grouping on the ``_stage_provider`` tag as
        well as ``_stage_span``.

        This is the granularity at which a provider's own contract has to be
        checked. A boundary whose steps did not all run cannot be held to its
        contract, which is what lets ``RUN_MAGIC_STREAMOUT=false`` work at all.
        At stage granularity that escape is far too wide on a ``multi_provider``
        stage: gating one of the two ``drc`` tools off would excuse the other
        from producing its metric, on a stage whose whole point is that each
        provider checks the design independently.
        """
        return Self.__runs(steps, lambda span, provider: (span, provider))

    @staticmethod
    def __runs(steps: list[type[Step]], key) -> list[Boundary]:
        """
        Scans ``steps`` for contiguous runs whose tags agree under ``key``.

        Reading the tags off the classes rather than remembering index ranges
        is what makes this survive duplicate-ID normalization: ``Step.with_id``
        subclasses, so the tag is inherited, while an untagged plain step
        correctly falls outside every boundary.
        """
        boundaries: list[Boundary] = []
        current_key: object = None
        current_span: tuple[str, ...] | None = None
        current_providers: list[str] = []
        current_ids: list[str] = []

        def flush():
            if current_span is None:
                return
            boundaries.append(
                Boundary(
                    stage_ids=current_span,
                    provider="+".join(current_providers),
                    step_ids=tuple(current_ids),
                    provides=(),
                    metrics=(),
                )
            )

        for step in steps:
            span: tuple[str, ...] | None = getattr(step, "_stage_span", None)
            provider: str | None = getattr(step, "_stage_provider", None)
            step_key = key(span, provider) if span is not None else None
            if step_key != current_key:
                flush()
                current_key = step_key
                current_span = span
                current_providers = []
                current_ids = []
            if span is None:
                continue
            # Both tags are written together by
            # StageRegistration.tagged_steps, so a step carrying a span carries
            # a provider. Stated rather than guarded: a None here would mean the
            # tagging itself is broken, and "+".join would fail further away.
            assert provider is not None
            if provider not in current_providers:
                current_providers.append(provider)
            current_ids.append(step.id)
        flush()

        return [boundary for boundary in boundaries if boundary.stage_ids]
