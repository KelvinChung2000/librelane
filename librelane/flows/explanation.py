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
"""What a prospective invocation of a flow would do, without running it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDisposition:
    """
    Why one step will or will not run, for one prospective invocation.

    :param step_id: The step's ID, as it appears in the resolved step list.
    :param will_run: Whether this invocation would execute the step.
    :param reason: A sentence naming the cause, suitable for printing.
    :param mechanism: ``None`` when :attr:`will_run` is true, and otherwise
        one of ``gate``, ``skip`` or ``window``.

        Those three are the only values a step entry can carry, because they
        are the only mechanisms that exclude a step which is present in the
        resolved list. A step dropped by a ``TOOLS`` selection is not in the
        list at all and so has no entry, which is why provider selection is
        not among them.
    """

    step_id: str
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class Explanation:
    """
    What a prospective invocation of this flow would do.

    :param steps: One entry per step in the resolved step list, in execution
        order.
    :param unselected_stages: Stages that contributed no steps, because
        ``TOOLS`` left them out or because their default provider is ``None``.
        These cannot be step entries, having no steps. Always empty for a flow
        that declares ``Steps`` directly and so has no stages.
    """

    steps: tuple[StepDisposition, ...]
    unselected_stages: tuple[str, ...]
