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

from typing import (
    TypeVar,
)


from librelane.config import (
    variables_to_model,
)
from librelane.state import DesignFormat, State
from librelane.common import (
    slugify,
)

from librelane.steps.step.composition import compose_step_sequence
from librelane.steps.step.core import MetricsUpdate, Step, ViewsUpdate

VT = TypeVar("VT")


class CompositeStep(Step):
    """
    A step composed of other steps, run sequentially as one unit. Constituent
    steps cannot be run, gated, or resumed separately, and may be private to
    the composite.

    A composite is a transaction: either the whole sequence ran or none of it
    did. Use one when several steps only make sense together, for example an
    insertion pass followed by the placement legalization that makes its
    output valid, or a vendor tool's write-scripts, invoke and read-back
    sequence. The alternative, exposing the parts individually, invites a flow
    to run half of them.

    A :class:`librelane.jobs.Registration` also binds one job to several
    steps, but keeps them individually addressable, which is what lets a job
    gate be lowered onto each of them. A composite instead hides its
    constituents behind one identifier, one configuration model, one directory
    and one resume unit. See ``docs/source/usage/writing_tool_backends.md``.

    ``inputs`` and ``config_vars`` are automatically generated based on the
    constituent steps.

    ``outputs`` may be set explicitly. If not set, it is automatically generated
    based on the constituent steps. Note that :meth:`run` propagates a view only
    if it is listed in ``outputs``, so an incomplete explicit ``outputs`` drops
    views rather than erroring.
    """

    Steps: list[type[Step]] = []

    def __init_subclass__(Self):
        super().__init_subclass__()
        if not Self.Steps:
            # Without this, the inherited empty default makes a composite that
            # reports success having done nothing: run() iterates no children
            # and returns empty updates. A typo in the attribute name is enough
            # to cause it.
            raise TypeError(
                f"CompositeStep subclass '{Self.__qualname__}' declares no "
                f"'Steps'. A composite with no constituent steps would run "
                f"nothing and report success."
            )
        union = compose_step_sequence(Self.Steps)
        Self.inputs = union.unmet_inputs
        if Self.outputs == NotImplemented:  # Allow for setting explicit outputs
            Self.outputs = union.outputs
        Self.config_vars = union.config_vars
        Self.install_config_model(
            variables_to_model(
                f"{Self.__name__}Config",
                Self.config_vars,
                base=Step.Config,
            )
        )

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        state = state_in
        step_count = len(self.Steps)
        ordinal_length = len(str(step_count - 1))
        for i, StepClass in enumerate(self.Steps):
            # The composite's own model is the union of every constituent's
            # config_vars, so each child's variables are already present and
            # already validated. Revalidating would re-read the PDK, which a
            # reproducible cannot do: its PDK_ROOT points at the copied
            # ./files tree, which holds only the files the config referenced.
            step = StepClass(
                self.config,
                state,
                _config_mode="trusted",
                # The logging layer keys a running step on its id: the loguru
                # filter behind step.log, LiveLog's registry, the progress
                # row. A child carries its own class id, so two jobs running
                # the same composite at once would give their children
                # identical keys and each child's records would land in both
                # step.log files -- the same collision the composite's own id
                # is disambiguated against, one level down. Deriving from
                # self.id rather than from the class carries whatever
                # disambiguation the composite was given through to its
                # children.
                id=f"{StepClass.id} ({self.id})",
            )
            # slugify of the class id, not the instance's: the id above names
            # the composite, and the composite's own directory is already the
            # parent of this one.
            step_dir = self.step_dir / (
                f"{str(i + 1).zfill(ordinal_length)}-{slugify(StepClass.id)}"
            )
            state = step.start(
                toolbox=self.toolbox,
                step_dir=step_dir,
                _no_rule=True,
            )

        views_updates: dict = {}
        metrics_updates: dict = {}
        for key in state:
            if (
                state_in.get(key) != state.get(key)
                and DesignFormat.factory.get(key) in self.outputs
            ):
                views_updates[key] = state[key]
        for key in state.metrics:
            if state_in.metrics.get(key) != state.metrics.get(key):
                metrics_updates[key] = state.metrics[key]

        return views_updates, metrics_updates
