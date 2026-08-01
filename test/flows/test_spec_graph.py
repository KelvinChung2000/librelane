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
import graphlib

import pytest

from librelane.flows.spec_graph import (
    ancestors,
    collapse,
    descendants,
    nontrivial_sccs,
    ring_order,
    topological_order,
)

pytestmark = pytest.mark.all

# streamout fans out to drc and lvs, which fan back in to xor.
_DIAMOND = {
    "streamout": [],
    "drc": ["streamout"],
    "lvs": ["streamout"],
    "xor": ["drc", "lvs"],
}


def test_topological_order_puts_every_predecessor_first():
    order = topological_order(_DIAMOND)

    assert order.index("streamout") < order.index("drc")
    assert order.index("streamout") < order.index("lvs")
    assert order.index("drc") < order.index("xor")
    assert order.index("lvs") < order.index("xor")
    assert sorted(order) == ["drc", "lvs", "streamout", "xor"]


def test_topological_order_raises_on_a_cycle_naming_its_members():
    with pytest.raises(graphlib.CycleError) as exc_info:
        topological_order({"a": ["b"], "b": ["a"]})

    assert set(exc_info.value.args[1]) >= {"a", "b"}


def test_ancestors_are_transitive_and_exclude_the_node():
    assert ancestors(_DIAMOND, "xor") == {"drc", "lvs", "streamout"}
    assert ancestors(_DIAMOND, "drc") == {"streamout"}
    assert ancestors(_DIAMOND, "streamout") == set()


def test_descendants_are_transitive_and_exclude_the_node():
    assert descendants(_DIAMOND, "streamout") == {"drc", "lvs", "xor"}
    assert descendants(_DIAMOND, "drc") == {"xor"}
    assert descendants(_DIAMOND, "xor") == set()


def test_disjoint_branches_are_not_each_other_s_relatives():
    assert "lvs" not in ancestors(_DIAMOND, "drc")
    assert "lvs" not in descendants(_DIAMOND, "drc")


def test_nontrivial_sccs_ignores_an_acyclic_graph():
    assert nontrivial_sccs(_DIAMOND) == []


def test_nontrivial_sccs_finds_a_two_ring():
    edges = {"a": ["b"], "b": ["a"]}

    assert nontrivial_sccs(edges) == [["a", "b"]]


def test_nontrivial_sccs_finds_a_three_ring():
    # x needs z, y needs x, z needs y: a single cycle through all three.
    edges = {"x": ["z"], "y": ["x"], "z": ["y"]}

    assert nontrivial_sccs(edges) == [["x", "y", "z"]]


def test_nontrivial_sccs_finds_a_self_loop():
    edges = {"job": ["job"], "other": []}

    assert nontrivial_sccs(edges) == [["job"]]


def test_a_size_one_component_with_no_self_edge_is_not_reported():
    edges = {"a": [], "b": ["a"]}

    assert nontrivial_sccs(edges) == []


def test_ring_order_orders_a_two_ring_each_node_followed_by_its_consumer():
    edges = {"a": ["b"], "b": ["a"]}

    order = ring_order(edges, ["a", "b"])

    assert order == ["a", "b"]


def test_ring_order_orders_a_three_ring_deterministically_from_the_smallest_member():
    edges = {"x": ["z"], "y": ["x"], "z": ["y"]}

    order = ring_order(edges, ["x", "y", "z"])

    assert order == ["x", "y", "z"]
    assert order[1] in edges[order[0]] or order[0] in edges[order[1]]


def test_ring_order_orders_a_self_loop_as_a_ring_of_one():
    edges = {"job": ["job"]}

    assert ring_order(edges, ["job"]) == ["job"]


def test_ring_order_rejects_a_figure_eight_sharing_one_node():
    # Two cycles sharing 'x': a-x-b-a, and x-d-c-x. 'x' ends up with two
    # intra-component predecessors, one per cycle, so it is not one ring.
    edges = {
        "a": ["x"],
        "x": ["b", "d"],
        "b": ["a"],
        "d": ["c"],
        "c": ["x"],
    }
    scc = nontrivial_sccs(edges)[0]

    assert ring_order(edges, scc) is None


def test_ring_order_rejects_a_chord():
    # a-b-c-a is a simple ring, but 'c' also needs 'a' directly, giving it
    # two intra-component predecessors.
    edges = {"a": ["c"], "b": ["a"], "c": ["b", "a"]}
    scc = nontrivial_sccs(edges)[0]

    assert scc == ["a", "b", "c"]
    assert ring_order(edges, scc) is None


def test_collapse_merges_a_ring_and_dedupes_its_outside_edges():
    # 'p' feeds both ring members; 'q' consumes the ring through 'a'.
    edges = {
        "p": [],
        "a": ["b", "p"],
        "b": ["a", "p"],
        "q": ["a"],
    }

    collapsed = collapse(edges, {"a": "R", "b": "R"})

    assert collapsed == {"p": [], "R": ["p"], "q": ["R"]}
    # The collapsed map is acyclic, as spec 3 requires: no CycleError.
    assert set(topological_order(collapsed)) == {"p", "R", "q"}


def test_collapse_leaves_a_document_with_no_ring_untouched():
    assert collapse(_DIAMOND, {}) == _DIAMOND
