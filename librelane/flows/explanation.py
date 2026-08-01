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
from typing import Any


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
        Whether this invocation would execute any of the job's steps.

        Not whether the job fires. A job excluded by ``condition`` or by
        ``skip`` still fires: it consumes its input tokens and deposits its
        input state unchanged on each of its output places, having run
        nothing, so every job downstream of it runs exactly as it would have.
        ``not-in-target`` and ``not-in-reproducible`` take the job out of the
        graph, and with it every descendant that is not an ancestor of some
        other selected job.
    reason : str
        A sentence naming the cause, suitable for printing.
    mechanism : str | None
        ``None`` when the job runs in full, and otherwise one of
        ``condition``, ``skip``, ``not-in-target``, ``not-in-reproducible`` or
        ``reproducible``.

        Those five are the only values a job entry can carry, because they are
        the only mechanisms that stop a job the document declares from running
        as it otherwise would. ``TOOLS`` is not among them: it re-points a job
        at another provider and so changes which steps the job runs, never
        whether the job is there. Every declared job therefore has an entry,
        including the ones that will not run, which is the question an
        explanation is asked.

        ``reproducible`` is the one value that can accompany a true
        :attr:`will_run`. It marks the job whose step ``--reproducible``
        named: the steps ahead of that one run and the run then stops, so the
        job neither runs in full nor is excluded.
    """

    job_id: str
    needs: tuple[str, ...]
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class VariableDisposition:
    """
    One configuration variable's value, where it came from, and which jobs can
    read it.

    Parameters
    ----------
    name : str
        The variable's name.
    value : Any
        The value the jobs in :attr:`reach` resolved it to.
    origin : str
        The layer that supplied that value, or ``default`` if none did.
    universal : bool
        True when the variable is in
        :data:`librelane.config.universal_flow_config_variables`, and so is
        readable by every step whatever any step declares. Kept apart from a
        reach that happens to be every job, because a variable readable
        everywhere by construction is a different fact from one every job in
        this particular document reads.
    reach : tuple[str, ...]
        The jobs that can read it, in the order the document declares them.
        Every job when :attr:`universal` is set, and empty for a variable read
        before any job exists to read it, such as ``TOOLS`` or a variable a
        job's ``if`` names.

        A variable two jobs resolve differently -- which is what a per-job
        ``with`` block is for -- has one entry per distinct value, each
        reaching the jobs that see that value. A single entry could only
        report one of the two, and would name whichever job the reader was not
        asking about.
    declared_by : str | None
        The step class every job in :attr:`reach` inherits the variable from,
        where they all inherit it from the same one. ``None`` when two classes
        declare it separately, when no step declares it, and whenever
        :attr:`universal` is set, since a universal variable's reach is not
        explained by any class.

        Named by step ID where the class has one, and by class name where it
        is abstract and so has none: thirteen variables are declared on
        ``OpenROADStep`` and read by every OpenROAD step below it, and naming
        the family is the same fact as listing its members.
    """

    name: str
    value: Any
    origin: str
    universal: bool
    reach: tuple[str, ...]
    declared_by: str | None


@dataclass(frozen=True)
class Explanation:
    """
    What a prospective invocation of this flow would do.

    Parameters
    ----------
    jobs : tuple[JobDisposition, ...]
        One entry per job the document declares, in topological order.
    variables : tuple[VariableDisposition, ...]
        One entry per configuration variable the flow resolves, plus one more
        for each further value a job resolved it to. Empty when the caller
        asked for the job table only.
    """

    jobs: tuple[JobDisposition, ...] = ()
    variables: tuple[VariableDisposition, ...] = ()
