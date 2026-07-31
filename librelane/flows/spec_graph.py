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
Graph math over a job dependency map, with no LibreLane types involved.

Every function takes ``edges``, a mapping from a node to the list of nodes it
directly depends on. This is the same direction as a workflow document's
``needs`` key, so a ``FlowSpec``'s job map converts without inversion.

Kept free of domain imports so it can be tested exhaustively on its own, and
because the command-line surface consumes :func:`ancestors` for ``--target``
and :func:`descendants` for ``--invalidate``.
"""

import graphlib


def topological_order(edges: dict[str, list[str]]) -> list[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.

    Returns
    -------
    Every node, with each node's dependencies appearing before it.

    Raises
    ------
    graphlib.CycleError
        If the graph contains a cycle. The offending
        nodes are in ``args[1]``.
    """
    return list(graphlib.TopologicalSorter(edges).static_order())


def ancestors(edges: dict[str, list[str]], node: str) -> set[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    node : str
        The node to walk back from.

    Returns
    -------
    Every transitive predecessor of ``node``, excluding ``node``.
    """
    return _reachable(edges, node)


def descendants(edges: dict[str, list[str]], node: str) -> set[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    node : str
        The node to walk forward from.

    Returns
    -------
    Every transitive successor of ``node``, excluding ``node``.
    """
    return _reachable(_reverse(edges), node)


def _reverse(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    inverted: dict[str, list[str]] = {name: [] for name in edges}
    for name, predecessors in edges.items():
        for predecessor in predecessors:
            inverted[predecessor].append(name)
    return inverted


def _reachable(edges: dict[str, list[str]], node: str) -> set[str]:
    found: set[str] = set()
    frontier = list(edges[node])
    while frontier:
        current = frontier.pop()
        if current in found:
            continue
        found.add(current)
        frontier.extend(edges[current])
    found.discard(node)
    return found
