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
Merging the states a job's predecessors produced into the one state it runs on.

One rule covers views and metrics both. Equal values merge silently, unequal
values are a conflict the document must resolve with ``source``. A view or
metric inherited from a common ancestor is identical down both branches and
needs no declaration; a key two branches wrote differently is genuinely
ambiguous, and guessing would silently pick one tool's output over another's.

``source`` is a tie-breaker, not a routing directive. It is read only for a key
whose contributing predecessors disagree. A key exactly one predecessor carries
is unambiguous and is taken without ``source`` entering into it, which is what
lets a gated-off producer pass through carrying nothing while a consumer that
names it in ``source`` still runs.

``source`` keys are plain strings for the same reason the rule is one rule. A
view is addressed by its id and a metric by its name, and one rule over both
namespaces cannot be expressed by a mapping keyed on
:class:`librelane.state.DesignFormat`.
"""

from collections.abc import Callable
from typing import Any

from librelane.common.errors import FlowError
from librelane.state import State


class JoinConflictError(FlowError):
    """
    Raised when two of a job's predecessors produced different values for one
    view or metric and the document did not declare which to use, or when a
    declared ``source`` cannot be honoured.
    """


#: How one contested key is settled: given the namespace, the key and every
#: ``(producer, value)`` pair that disagreed, either return the winning value
#: or raise. The two callers differ in exactly this, and in nothing else, so it
#: is the only thing the shared merge is parameterized on. A job join can be
#: settled by the job's ``source``; a sink join cannot be settled at all and
#: always raises, because the sink is not a job and has no ``source``.
_Resolve = Callable[[str, str, list[tuple[str, Any]]], Any]


def join_states(
    tokens: dict[str, State],
    source: dict[str, str],
    job: str,
) -> State:
    """
    Merges the states one job's predecessors produced into the one it runs on.

    Parameters
    ----------
    tokens : dict[str, State]
        Each predecessor's output state, keyed by the producing job.
    source : dict[str, str]
        The job's declared per-key resolution. A key is a view id or
        a metric name.
    job : str
        The consuming job, named in errors.

    Returns
    -------
    The merged state.

    Raises
    ------
    JoinConflictError
        On a conflict the document did not declare a ``source``
        for, or on a ``source`` that names a job which contributed no value to
        the conflict it was meant to resolve.
    FlowError
        If ``tokens`` is empty. Every job consumes at least one place, so this
        does not arise from any document; returning an empty state instead
        would hand the job a silently defaulted input.
    """
    if not tokens:
        raise FlowError(
            f"Job '{job}' was given no predecessor states to join, so there is "
            f"no state to run it on."
        )
    if len(tokens) == 1:
        return next(iter(tokens.values()))
    return _join(tokens, _job_resolver(job, source))


def join_sink_states(
    tokens: dict[str, State],
    flow: str,
    excluded_final: str | None = None,
) -> State:
    """
    Merges the states the flow's leaf jobs left on their sink places.

    Separate from :func:`join_states`, and not a call into it with a
    stand-in job name, because the two conflicts have different remedies and
    only one of them exists here. No job's ``source`` can settle a sink
    conflict: the join is not a job, so there is no ``source`` mapping to read.
    The document's top-level ``final`` key is what names the state the flow
    returns, and it is what this error prescribes. The wording deliberately
    matches
    :func:`librelane.flows.spec_validation._check_sink_join_is_unambiguous`,
    which catches the *declared* half of the same conflict at load time; this
    is the run-time backstop for a leaf that returned a view its contract never
    mentioned.

    Parameters
    ----------
    tokens : dict[str, State]
        Each leaf job's output state, keyed by that job.
    flow : str
        The flow's name, named in errors.
    excluded_final : str | None
        The job the document's ``final`` names, when this run left it out of
        the graph. Prescribing ``final`` is only a remedy for a document that
        does not declare one; a run narrowed away from a declared ``final``
        reaches this join with its remedy already written down and unusable,
        and telling its author to write it again would send them to a line of
        YAML that is already correct.

    Returns
    -------
    The merged state.

    Raises
    ------
    JoinConflictError
        If two leaves produced different values for one view or metric.
    FlowError
        If ``tokens`` is empty. A net with at least one job always has at least
        one sink place, so this does not arise from any document; returning an
        empty state instead would make the flow report success with nothing in
        hand.
    """
    if not tokens:
        raise FlowError(
            f"The final state of flow '{flow}' was joined from no leaf jobs, "
            f"so there is no state to return."
        )
    if len(tokens) == 1:
        return next(iter(tokens.values()))
    return _join(tokens, _sink_resolver(flow, excluded_final))


def _job_resolver(job: str, source: dict[str, str]) -> _Resolve:
    """
    Returns
    -------
    A resolver that settles a contested key from ``source``.

    ``source`` is the job's whole mapping, covering both namespaces. It is read
    only here, for a key whose contributors disagree, because a key exactly one
    predecessor carries is not ambiguous and there is nothing for a
    conflict-resolution parameter to resolve.
    """

    def resolve(kind: str, key: str, produced: list[tuple[str, Any]]) -> Any:
        producers = [producer for producer, _ in produced]
        chosen = source.get(key)
        if chosen is None:
            raise JoinConflictError(
                f"Job '{job}' joins {producers}, which produced different "
                f"values for {kind} '{key}'. Declare which one it comes from "
                f"with 'source: {{{key}: {producers[0]}}}' or "
                f"'source: {{{key}: {producers[1]}}}'."
            )
        for producer, value in produced:
            if producer == chosen:
                return value
        raise JoinConflictError(
            f"Job '{job}' sources {kind} '{key}' from '{chosen}', which "
            f"contributed no value for it to this join. The predecessors "
            f"that disagree on '{key}' are {producers}."
        )

    return resolve


def _sink_resolver(flow: str, excluded_final: str | None) -> _Resolve:
    """
    Returns
    -------
    A resolver that always raises, naming ``final`` as the remedy -- or, when
    the run excluded the ``final`` the document already declares, naming the
    flow control that excluded it.
    """

    def resolve(kind: str, key: str, produced: list[tuple[str, Any]]) -> Any:
        producers = [producer for producer, _ in produced]
        opening = (
            f"The final state of flow '{flow}' joins leaf jobs {producers}, "
            f"which produced different values for {kind} '{key}'. No job's "
            f"'source' can resolve this, because the join is not a job."
        )
        if excluded_final is None:
            raise JoinConflictError(
                f"{opening} Declare the top-level 'final' key naming the job "
                f"whose state the flow returns, for example "
                f"'final: {producers[0]}'."
            )
        raise JoinConflictError(
            f"{opening} This flow declares 'final: {excluded_final}', but "
            f"this run's --target left that job out, so the graph that ran "
            f"has these leaves instead and the document's rule does not "
            f"reach them. Add '{excluded_final}' to --target, or narrow "
            f"--target to one of {producers}."
        )

    return resolve


def _join(tokens: dict[str, State], resolve: _Resolve) -> State:
    """Merges both namespaces of two or more states under one resolver."""
    views = _merge(
        {name: dict(state) for name, state in tokens.items()},
        "view",
        resolve,
    )
    metrics = _merge(
        {name: dict(state.metrics) for name, state in tokens.items()},
        "metric",
        resolve,
    )
    return State(views, metrics=metrics)


def _merge(
    contributions: dict[str, dict[str, Any]],
    kind: str,
    resolve: _Resolve,
) -> dict[str, Any]:
    """
    Merges one namespace, either the views or the metrics.

    Gathers each key's contributors first, then decides per key. ``resolve`` is
    consulted only for a key whose contributors disagree.
    """
    contributors: dict[str, list[tuple[str, Any]]] = {}
    for producer, mapping in contributions.items():
        for key, value in mapping.items():
            contributors.setdefault(key, []).append((producer, value))

    merged: dict[str, Any] = {}
    for key, produced in contributors.items():
        first = produced[0][1]
        if all(value == first for _, value in produced):
            merged[key] = first
            continue
        merged[key] = resolve(kind, key, produced)
    return merged
