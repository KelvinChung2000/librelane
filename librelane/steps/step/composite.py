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


from ...config import (
    variables_to_model,
)
from ...state import DesignFormat, State
from ...common import (
    slugify,
)

from .composition import compose_step_sequence
from .core import MetricsUpdate, Step, ViewsUpdate

VT = TypeVar("VT")


class CompositeStep(Step):
    """
    A step composed of other steps, run sequentially. The steps are intended
    to run as a unit within a flow and cannot be run separately.

    Composite steps are currently considered an internal object that is not
    ready to be part of the API. The API may change at any time for any reason.

    ``inputs`` and ``config_vars`` are automatically generated based on the
    constituent steps.

    ``outputs`` may be set explicitly. If not set, it is automatically generated
    based on the constituent steps.
    """

    Steps: list[type[Step]] = []

    def __init_subclass__(Self):
        super().__init_subclass__()
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
            step = StepClass(self.config, state, _no_revalidate_conf=True)
            step_dir = self.step_dir / (
                f"{str(i + 1).zfill(ordinal_length)}-{slugify(step.id)}"
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
