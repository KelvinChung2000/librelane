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


def _dfs_postorder(edges: dict[str, list[str]]) -> list[str]:
    """
    An iterative depth-first postorder over every node of ``edges``,
    following each node's own dependency list.
    """
    visited: set[str] = set()
    order: list[str] = []
    for start in edges:
        if start in visited:
            continue
        visited.add(start)
        # Each stack entry is a node paired with how many of its
        # dependencies have already been pushed, so the loop can resume a
        # partially explored node instead of re-walking its whole list.
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, index = stack[-1]
            dependencies = edges[node]
            if index < len(dependencies):
                stack[-1] = (node, index + 1)
                dependency = dependencies[index]
                if dependency not in visited:
                    visited.add(dependency)
                    stack.append((dependency, 0))
            else:
                order.append(node)
                stack.pop()
    return order


def _weakly_connected_component(
    start: str, edges: dict[str, list[str]], visited: set[str]
) -> list[str]:
    component: list[str] = [start]
    visited.add(start)
    frontier = [start]
    while frontier:
        current = frontier.pop()
        for neighbor in edges[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                component.append(neighbor)
                frontier.append(neighbor)
    return component


def nontrivial_sccs(edges: dict[str, list[str]]) -> list[list[str]]:
    """
    Kosaraju's algorithm: a postorder depth-first search over ``edges``,
    then a second depth-first search over the reversed graph, visiting
    nodes in decreasing postorder finish time. Each tree of the second
    search is one strongly connected component.

    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.

    Returns
    -------
    Every strongly connected component of size 2 or more, plus every
    component of size 1 whose sole member lists itself among its own
    dependencies (a self-loop). Each component is sorted, and the
    components are ordered by their smallest member, so the result is
    deterministic regardless of dict iteration order.
    """
    postorder = _dfs_postorder(edges)
    reverse_edges = _reverse(edges)
    visited: set[str] = set()
    components: list[list[str]] = []
    for node in reversed(postorder):
        if node in visited:
            continue
        component = sorted(_weakly_connected_component(node, reverse_edges, visited))
        is_self_loop = len(component) == 1 and component[0] in edges[component[0]]
        if len(component) >= 2 or is_self_loop:
            components.append(component)
    components.sort(key=lambda component: component[0])
    return components


def ring_order(edges: dict[str, list[str]], scc: list[str]) -> list[str] | None:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    scc : list[str]
        A strongly connected component, as returned by
        :func:`nontrivial_sccs`.

    Returns
    -------
    The members of ``scc``, ordered so that each node is followed by the
    node that needs it -- the pass-independent ring order, not yet rotated
    to any particular starting job. ``None`` if ``scc`` is not a simple
    ring: a strongly connected component in which every member has exactly
    one predecessor inside the component. A component that fails this,
    because some member has a chord (two intra-component predecessors) or
    is the shared node of two cycles (which is the same failure: that node
    has two intra-component predecessors, one per cycle), is not a legal
    loop.

    A single-member component is a ring of one -- a self-loop -- only if
    that member lists itself among its own dependencies; the starting
    point is that member.

    For a larger ring, the starting point is ``scc``'s sorted-first member,
    so the result is deterministic; a caller that wants the order rotated
    to start elsewhere (a gate's successor, for the pass execution order)
    does the rotation itself.
    """
    members = frozenset(scc)
    intra_predecessors = {
        node: [dependency for dependency in edges[node] if dependency in members]
        for node in scc
    }
    if any(len(predecessors) != 1 for predecessors in intra_predecessors.values()):
        return None
    if len(scc) == 1:
        node = scc[0]
        return [node] if intra_predecessors[node] == [node] else None
    successor: dict[str, str] = {}
    for node, predecessors in intra_predecessors.items():
        predecessor = predecessors[0]
        # A member needing itself, inside a component of more than one node,
        # is not a ring: a ring's edges close a single cycle through every
        # member, and a self-edge closes no one else's. A predecessor
        # claimed by two different successors is the chord/figure-eight
        # case: that predecessor has two intra-component successors, so the
        # intra-component edges are not a single cycle.
        if predecessor == node or predecessor in successor:
            return None
        successor[predecessor] = node
    start = sorted(scc)[0]
    order = [start]
    current = start
    while len(order) < len(scc):
        next_node = successor.get(current)
        if next_node is None or next_node in order:
            return None
        order.append(next_node)
        current = next_node
    if successor.get(order[-1]) != start:
        return None
    return order


def collapse(
    edges: dict[str, list[str]], member_ring: dict[str, str]
) -> dict[str, list[str]]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    member_ring : dict[str, str]
        Every ring member mapped to its ring's id. A node absent from this
        mapping is not a ring member and is carried through unchanged.

    Returns
    -------
    ``edges``, with every node and every dependency replaced by its ring id
    where ``member_ring`` names one. An edge that becomes a self-edge this
    way (both endpoints collapsing to the same ring) is dropped, because it
    is an edge internal to the ring rather than one crossing its boundary.
    A ring id's dependency list is the union of its members' outside
    dependencies, deduplicated in first-seen order.
    """
    collapsed: dict[str, list[str]] = {}
    for node, dependencies in edges.items():
        collapsed_node = member_ring.get(node, node)
        bucket = collapsed.setdefault(collapsed_node, [])
        seen = set(bucket)
        for dependency in dependencies:
            collapsed_dependency = member_ring.get(dependency, dependency)
            if collapsed_dependency == collapsed_node:
                continue
            if collapsed_dependency in seen:
                continue
            bucket.append(collapsed_dependency)
            seen.add(collapsed_dependency)
    return collapsed
