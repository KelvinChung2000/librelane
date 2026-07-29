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
from collections.abc import Mapping, Sequence
from typing import Optional, Union

from loguru import logger

from ..common import Filter, parse_metric_modifiers
from ..config import Config as ResolvedConfig, variable
from ..stages.resolution import Resolution, StageEntry, ToolSelection, resolve
from ..stages.stage import Stage, StageContractError
from ..stages.tools import extract_tools
from ..state import DesignFormat, State
from ..steps import Step

from .sequential import SequentialFlow


@dataclass(frozen=True)
class Boundary:
    """
    A contiguous run of resolved steps belonging to one stage or span, and the
    contract that must hold once its last step completes.
    """

    stage_ids: tuple[str, ...]
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

    :cvar Stages: The flow in stage terms. Entries are either ``Stage``
        objects, which expand to whichever provider is selected, or plain
        ``Step`` classes, which are provider-neutral utilities and boundary
        observations. A plain step entry is only meaningful at a stage
        boundary.

    ``Steps`` is expanded from ``Stages`` at class-definition time using each
    stage's ``default_provider``, so it is a fully populated list at import and
    every existing ``SequentialFlow`` facility keeps working unchanged:
    ``Substitute``, ``get_help_md``, step IDs and step directory names.
    """

    Stages: list[StageEntry] = []

    #: Overridden from ``Flow``, where it is ``NotImplemented``. ``StagedFlow``
    #: populates it from ``Stages``, but the class body of ``StagedFlow``
    #: itself runs ``SequentialFlow.__init_subclass__``, which copies ``Steps``
    #: unconditionally.
    Steps: list[type[Step]] = []

    #: The gating entries a flow author wrote by hand, as opposed to those
    #: generated from stage gates. Kept apart because generated entries name
    #: concrete step IDs and so must be rebuilt for every subclass:
    #: ``Substitutions`` may have removed the very steps they name, which would
    #: otherwise leave an inherited entry matching nothing.
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

        # Step IDs are only final once the base class has normalized duplicates
        # and applied Substitutions, so gates cannot be generated until after.
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
        if tools:
            # Re-expansion happens before super().__init__, because that is
            # where get_all_config_variables() reads self.Steps to build the
            # model configuration is validated against. The whole reason the
            # TOOLS pre-pass exists is that the step set has to be known first.
            resolution = resolve(self.Stages, tools)
            self.Steps = resolution.steps
            self._normalize_step_ids(self)
            self._apply_stage_gating(self)
            self.__prune_deselected_gates(self)
            self._resolution = resolution

        super().__init__(
            config,
            config_override_strings=config_override_strings,
            **kwargs,
        )

        self.__executed_step_ids: set[str] = set()
        self.__boundary_by_last_step = {
            boundary.last_step_id: boundary for boundary in self.__boundaries()
        }

    def __boundaries(self) -> list[Boundary]:
        """
        The boundary map for the resolved step list, with each boundary's
        contract taken from the span that produced it.

        ``stage_boundaries`` recovers step membership from the tags on the step
        classes, but falls back to the taxonomy for the contract. Only the
        resolution knows which providers were selected, and a
        :class:`librelane.stages.Registration` may declare ``provides`` and
        ``metrics`` beyond its stage's, so the span is the authority here.
        """
        spans = {span.stage_ids: span for span in self._resolution.spans}
        result = []
        for boundary in self.stage_boundaries(self.Steps):
            span = spans.get(boundary.stage_ids)
            if span is not None:
                boundary = replace(
                    boundary, provides=span.provides, metrics=span.metrics
                )
            result.append(boundary)
        return result

    def _after_step(self, step: Step, state: State, executed: bool) -> None:
        if executed:
            self.__executed_step_ids.add(step.id)
        boundary = self.__boundary_by_last_step.get(step.id)
        if boundary is None:
            return
        if not all(
            step_id in self.__executed_step_ids for step_id in boundary.step_ids
        ):
            # A stage that did not run every step cannot be held to its
            # contract: the views and metrics were never attempted.
            logger.debug(
                f"stage {list(boundary.stage_ids)}: not every step ran, "
                f"contract not checked"
            )
            return
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
            f"stage {list(boundary.stage_ids)} completed without producing "
            f"{' and '.join(parts)}. Every provider of these stages is "
            f"contracted to produce them; a stage whose contract is not met "
            f"cannot be handed to the next stage."
        )

    @classmethod
    def __selected_tools(
        Self,
        config,
        config_override_strings: Sequence[str] | None,
    ) -> Mapping[str, ToolSelection]:
        """
        :returns: The ``TOOLS`` mapping, read from raw sources by the pre-pass
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
        """
        generated: dict[str, list[str]] = {}
        for boundary in StagedFlow.stage_boundaries(target.Steps):
            for stage_id in boundary.stage_ids:
                stage = Stage.factory.get(stage_id)
                if stage.gating_config_var is None:
                    continue
                for step_id in boundary.step_ids:
                    generated.setdefault(step_id, []).append(stage.gating_config_var)

        merged = generated
        for key, value in target._explicit_gating_config_vars.items():
            # dict.fromkeys deduplicates while preserving order, so a variable
            # that is both a stage gate and an explicit entry appears once.
            merged[key] = list(dict.fromkeys(merged.get(key, []) + list(value)))
        target.gating_config_vars = merged

    @staticmethod
    def __report_unselected(resolution: Resolution) -> None:
        for stage_id in resolution.unselected:
            logger.debug(f"stage '{stage_id}': no provider selected, skipped")

    @classmethod
    def stage_boundaries(Self, steps: list[type[Step]]) -> list[Boundary]:
        """
        Recovers the stage boundary map from a final step list by scanning for
        contiguous runs of steps carrying the same ``_stage_span`` tag.

        Reading the tags off the classes rather than remembering index ranges
        is what makes this survive duplicate-ID normalization and
        ``Substitutions``: ``Step.with_id`` subclasses, so the tag is
        inherited, while a substituted-in step carries no tag and correctly
        falls outside every boundary.
        """
        boundaries: list[Boundary] = []
        current_span: tuple[str, ...] | None = None
        current_ids: list[str] = []

        def flush():
            if current_span is None:
                return
            provides: set = set()
            metrics: set = set()
            for stage_id in current_span:
                stage = Stage.factory.get(stage_id)
                provides.update(stage.provides)
                metrics.update(stage.metrics)
            boundaries.append(
                Boundary(
                    stage_ids=current_span,
                    step_ids=tuple(current_ids),
                    provides=tuple(sorted(provides, key=lambda view: view.id)),
                    metrics=tuple(sorted(metrics)),
                )
            )

        for step in steps:
            span = getattr(step, "_stage_span", None)
            if span != current_span:
                flush()
                current_span = span
                current_ids = []
            if span is not None:
                current_ids.append(step.id)
        flush()

        return [boundary for boundary in boundaries if boundary.stage_ids]
