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

from typing import Any

from librelane.common.errors import FlowError
from librelane.state import State


class JoinConflictError(FlowError):
    """
    Raised when two of a job's predecessors produced different values for one
    view or metric and the document did not declare which to use, or when a
    declared ``source`` cannot be honoured.
    """


def join_states(
    tokens: dict[str, State],
    source: dict[str, str],
    job: str,
) -> State:
    """
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
    """
    if len(tokens) == 1:
        return next(iter(tokens.values()))

    views = _merge(
        {name: dict(state) for name, state in tokens.items()},
        source,
        job,
        "view",
    )
    metrics = _merge(
        {name: dict(state.metrics) for name, state in tokens.items()},
        source,
        job,
        "metric",
    )
    return State(views, metrics=metrics)


def _merge(
    contributions: dict[str, dict[str, Any]],
    selected: dict[str, str],
    job: str,
    kind: str,
) -> dict[str, Any]:
    """
    Merges one namespace, either the views or the metrics.

    Gathers each key's contributors first, then decides per key. ``selected``
    is read only for a key whose contributors disagree, because a key exactly
    one predecessor carries is not ambiguous and there is nothing for a
    conflict-resolution parameter to resolve.

    ``selected`` is the job's whole ``source`` mapping, covering both
    namespaces. An entry addressed at the other namespace matches no key here
    and is left to that namespace's own pass.
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

        producers = [producer for producer, _ in produced]
        chosen = selected.get(key)
        if chosen is None:
            raise JoinConflictError(
                f"Job '{job}' joins {producers}, which produced different "
                f"values for {kind} '{key}'. Declare which one it comes from "
                f"with 'source: {{{key}: {producers[0]}}}' or "
                f"'source: {{{key}: {producers[1]}}}'."
            )
        for producer, value in produced:
            if producer == chosen:
                merged[key] = value
                break
        else:
            raise JoinConflictError(
                f"Job '{job}' sources {kind} '{key}' from '{chosen}', which "
                f"contributed no value for it to this join. The predecessors "
                f"that disagree on '{key}' are {producers}."
            )
    return merged
