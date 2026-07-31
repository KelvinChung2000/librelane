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

from librelane.flows.spec_graph import ancestors, descendants, topological_order

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
