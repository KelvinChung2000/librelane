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

    Parameters
    ----------
    step_id : str
        The step's ID, as it appears in the resolved step list.
    will_run : bool
        Whether this invocation would execute the step.
    reason : str
        A sentence naming the cause, suitable for printing.
    mechanism : str | None
        ``None`` when :attr:`will_run` is true, and otherwise
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
class JobDisposition:
    """
    Why one job will or will not run its steps, for one prospective invocation.

    Parameters
    ----------
    job_id : str
        The document's job key.
    needs : tuple[str, ...]
        The job's declared incoming edges, so the table can show the graph
        without a second query.
    will_run : bool
        Whether this invocation would execute the job's steps.

        Not whether the job fires. A job excluded by ``condition`` or by
        ``skip`` still fires: it consumes its input tokens and deposits its
        input state unchanged on each of its output places, having run
        nothing, so every job downstream of it runs exactly as it would have.
        Only ``not-in-target`` takes the job out of the graph, and with it
        every descendant that is not an ancestor of some other target.
    reason : str
        A sentence naming the cause, suitable for printing.
    mechanism : str | None
        ``None`` when :attr:`will_run` is true, and otherwise
        one of ``condition``, ``skip`` or ``not-in-target``.

        Those three are the only values a job entry can carry, because they
        are the only mechanisms that exclude a job the document declares.
        ``TOOLS`` is not among them: it re-points a job at another provider
        and so changes which steps the job runs, never whether the job is
        there. Every declared job therefore has an entry, including the ones
        that will not run, which is the question an explanation is asked.
    """

    job_id: str
    needs: tuple[str, ...]
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class Explanation:
    """
    What a prospective invocation of this flow would do.

    Parameters
    ----------
    steps : tuple[StepDisposition, ...]
        One entry per step in the resolved step list, in execution
        order.
    unselected_jobs : tuple[str, ...]
        Jobs that contributed no steps, because
        ``TOOLS`` left them out or because their default provider is ``None``.
        These cannot be step entries, having no steps. Always empty for a flow
        that declares ``Steps`` directly and so has no jobs.
    jobs : tuple[JobDisposition, ...]
        One entry per job the document declares, in topological order. Empty
        for a ``SequentialFlow``, which has jobs no more than a ``Workflow``
        has stages. Both halves live here until phase 5 deletes the first.
    """

    steps: tuple[StepDisposition, ...]
    unselected_jobs: tuple[str, ...]
    jobs: tuple[JobDisposition, ...] = ()
