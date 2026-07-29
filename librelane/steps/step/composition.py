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
"""The aggregate view and configuration contract of an ordered step sequence."""

from collections.abc import Sequence
from dataclasses import dataclass

from ...config import Variable
from ...state import DesignFormat

from .core import Step


@dataclass(frozen=True)
class StepSequenceUnion:
    """
    The aggregate view and configuration contract of an ordered sequence of
    steps, treated as if it ran as a unit.

    :param unmet_inputs: Views the sequence consumes that no earlier step in
        the sequence produces, in order of first appearance.
    :param outputs: Every view any step in the sequence produces.
    :param config_vars: Every configuration variable any step in the sequence
        declares, deduplicated, in order of first appearance.
    """

    unmet_inputs: list[DesignFormat]
    outputs: list[DesignFormat]
    config_vars: list[Variable]


def compose_step_sequence(steps: Sequence[type[Step]]) -> StepSequenceUnion:
    """
    Walks an ordered step sequence, accumulating the views it needs from
    outside, the views it produces, and the configuration variables it
    declares.

    :param steps: The ordered step sequence.
    :raises TypeError: If two steps declare a variable of the same name with
        differing definitions.
    """
    available: set[DesignFormat] = set()
    unmet_inputs: list[DesignFormat] = []
    outputs: list[DesignFormat] = []
    config_vars: dict[str, Variable] = {}

    for step in steps:
        for input in step.inputs:
            if input not in available:
                unmet_inputs.append(input)
                available.add(input)
        for output in step.outputs:
            if output not in available:
                available.add(output)
            if output not in outputs:
                outputs.append(output)
        for cvar in step.config_vars:
            existing = config_vars.get(cvar.name)
            if existing is None:
                config_vars[cvar.name] = cvar
            elif existing != cvar:
                raise TypeError(
                    f"Step sequence has mismatching config_vars: {cvar.name} "
                    f"contradicts an earlier declaration"
                )

    return StepSequenceUnion(unmet_inputs, outputs, list(config_vars.values()))
