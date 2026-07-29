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

from dataclasses import dataclass

from loguru import logger

from ..stages.resolution import Resolution, StageEntry, resolve
from ..stages.stage import Stage
from ..state import DesignFormat
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

    def __init_subclass__(Self, scm_type=None, name=None, **kwargs):
        if "Stages" in Self.__dict__:
            Self.Stages = list(Self.Stages)
            resolution = resolve(Self.Stages, {})
            Self.Steps = resolution.steps
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
        super().__init_subclass__(scm_type=scm_type, name=name, **kwargs)

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
