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
"""
The Petri net a workflow runs on.

There is one place per *arc*, not per job. A job with two consumers deposits one
token on each of its two outgoing places. The alternative, one place per job,
would force a producer to deposit as many tokens as it has consumers and the
scheduler to know that count, leaking fan-out into the encoding. Per-arc keeps
the firing rule literally true as stated, namely consume one token from each
input place and deposit one on each output place.

Tokens are opaque here, so this module has no domain imports and the engine is
free to make a token whatever it needs. In practice a token is a
:class:`librelane.state.State`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


class NetError(RuntimeError):
    """
    Raised when the marking violates an invariant. On an acyclic graph this
    cannot happen, and that is why it is checked. It is what a marking bug in a
    later, cyclic engine trips first.
    """


@dataclass(frozen=True)
class Arc:
    """
    One place, identified by the edge it represents.

    Parameters
    ----------
    producer
        The job that deposits here, or ``None`` for the source
        place that holds the run's initial state.
    consumer
        The job that consumes here, or ``None`` for the sink.
    """

    producer: str | None
    consumer: str | None


class Net:
    """
    A marked Petri net over a job graph.

    Parameters
    ----------
    jobs
        Every job, in any order.
    edges
        A mapping from each job to the jobs it depends on.
    """

    def __init__(self, jobs: Sequence[str], edges: dict[str, list[str]]) -> None:
        self._jobs = tuple(jobs)
        arcs: list[Arc] = []
        has_consumer = {job: False for job in self._jobs}
        for job in self._jobs:
            predecessors = edges.get(job, [])
            if not predecessors:
                arcs.append(Arc(None, job))
            for predecessor in predecessors:
                arcs.append(Arc(predecessor, job))
                has_consumer[predecessor] = True
        for job in self._jobs:
            if not has_consumer[job]:
                arcs.append(Arc(job, None))
        self.arcs = tuple(arcs)
        consumers = {arc.consumer for arc in arcs}
        assert consumers.issuperset(self._jobs), (
            "every job has at least one input place. all() over no input "
            "places is vacuously true, so a job with none is enabled with "
            "nothing to consume: what holds it back today is only the "
            "'has not fired' test, which the source arc above makes "
            "unnecessary and which a net that fires a transition more than "
            "once would not have"
        )
        self._marking: dict[Arc, Any] = {}
        self.fired: set[str] = set()

    def inputs_of(self, job: str) -> tuple[Arc, ...]:
        """Every place this job consumes from."""
        return tuple(arc for arc in self.arcs if arc.consumer == job)

    def outputs_of(self, job: str) -> tuple[Arc, ...]:
        """Every place this job deposits onto."""
        return tuple(arc for arc in self.arcs if arc.producer == job)

    def put(self, arc: Arc, token: Any) -> None:
        """
        Deposits one token on one place.

        Parameters
        ----------
        arc
            The place to deposit onto.
        token
            The token to deposit.

        Raises
        ------
        NetError
            If the place already holds a token.
        """
        if arc in self._marking:
            raise NetError(
                f"Place {arc} already holds a token, and a place holds at most "
                f"one. Either the same arc was built twice or its producer "
                f"fired twice."
            )
        self._marking[arc] = token

    def enabled(self) -> list[str]:
        """
        Returns
        -------
        Every job whose input places all hold a token and which has
        not already fired, in the order the jobs were declared.
        """
        return [
            job
            for job in self._jobs
            if job not in self.fired
            and all(arc in self._marking for arc in self.inputs_of(job))
        ]

    def consume(self, job: str) -> list[Any]:
        """
        Removes and returns one token from each of this job's input places.

        Parameters
        ----------
        job
            The job consuming its input tokens.

        Returns
        -------
        One token per input place, in the order those places were declared.

        Raises
        ------
        NetError
            If any input place is unmarked.
        """
        tokens = []
        for arc in self.inputs_of(job):
            if arc not in self._marking:
                raise NetError(
                    f"Job '{job}' cannot consume: place {arc} holds no token."
                )
            tokens.append(self._marking.pop(arc))
        return tokens

    def fire(self, job: str, token: Any) -> None:
        """
        Deposits ``token`` on each of this job's output places and records the
        firing. Call after :meth:`consume`.

        Parameters
        ----------
        job
            The job that fired.
        token
            The single output state, copied onto every output place.
        """
        for arc in self.outputs_of(job):
            self.put(arc, token)
        self.fired.add(job)

    def sink_tokens(self) -> dict[str, Any]:
        """
        Returns
        -------
        The token each leaf job left on its sink place, keyed by that
        job. Nothing consumes a sink place, so these are the tokens the flow's
        final state is joined from.

        Raises
        ------
        NetError
            If any sink place is unmarked, which means the job
            that feeds it has not fired.
        """
        tokens: dict[str, Any] = {}
        for arc in self.arcs:
            if arc.consumer is not None:
                continue
            assert arc.producer is not None, "a sink arc always names a producer"
            if arc not in self._marking:
                raise NetError(
                    f"Sink place {arc} holds no token, so job "
                    f"'{arc.producer}' has not fired."
                )
            tokens[arc.producer] = self._marking[arc]
        return tokens

    def is_complete(self) -> bool:
        """Whether every job has fired."""
        return self.fired == set(self._jobs)

    def stalled(self) -> list[str]:
        """
        Returns
        -------
        Every job that has not fired, for the error raised when no
        transition is enabled and the run is not complete.
        """
        return [job for job in self._jobs if job not in self.fired]
