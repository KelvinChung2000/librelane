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
import pytest

from librelane.flows.net import Arc, Net, NetError

pytestmark = pytest.mark.all

_DIAMOND_EDGES = {
    "streamout": [],
    "drc": ["streamout"],
    "lvs": ["streamout"],
    "xor": ["drc", "lvs"],
}
_DIAMOND_JOBS = ["streamout", "drc", "lvs", "xor"]


def _diamond() -> Net:
    return Net(_DIAMOND_JOBS, _DIAMOND_EDGES)


def _run_diamond(net: Net) -> None:
    for job in _DIAMOND_JOBS:
        net.consume(job)
        net.fire(job, f"{job}-out")


def test_a_job_with_no_needs_takes_its_input_from_the_source_place():
    net = _diamond()

    assert net.inputs_of("streamout") == (Arc(None, "streamout"),)


def test_a_job_with_no_dependents_deposits_on_the_sink():
    net = _diamond()

    assert net.outputs_of("xor") == (Arc("xor", None),)


def test_a_fan_out_job_has_one_output_arc_per_consumer():
    net = _diamond()

    assert set(net.outputs_of("streamout")) == {
        Arc("streamout", "drc"),
        Arc("streamout", "lvs"),
    }


def test_nothing_is_enabled_until_the_source_is_marked():
    net = _diamond()

    assert net.enabled() == []

    net.put(Arc(None, "streamout"), "initial")

    assert net.enabled() == ["streamout"]


def test_firing_a_fan_out_enables_both_branches():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    assert sorted(net.enabled()) == ["drc", "lvs"]


def test_a_join_is_enabled_only_when_every_input_place_is_marked():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    net.consume("drc")
    net.fire("drc", "drc-out")
    assert net.enabled() == ["lvs"]

    net.consume("lvs")
    net.fire("lvs", "lvs-out")
    assert net.enabled() == ["xor"]


def test_consume_returns_one_token_per_input_place_and_empties_them():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")
    net.consume("drc")
    net.fire("drc", "drc-out")
    net.consume("lvs")
    net.fire("lvs", "lvs-out")

    assert sorted(net.consume("xor")) == ["drc-out", "lvs-out"]
    assert net.enabled() == []


def test_depositing_onto_an_occupied_place_raises():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")

    with pytest.raises(NetError) as exc_info:
        net.put(Arc(None, "streamout"), "again")

    assert "already holds a token" in str(exc_info.value)


def test_the_run_is_complete_when_every_job_has_fired():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")

    assert not net.is_complete()

    _run_diamond(net)

    assert net.is_complete()
    assert net.fired == {"streamout", "drc", "lvs", "xor"}


def test_stalled_names_the_jobs_that_never_became_enabled():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")
    net.consume("drc")
    net.fire("drc", "drc-out")

    assert sorted(net.stalled()) == ["lvs", "xor"]


def test_sink_tokens_names_every_leaf_and_the_token_it_left():
    # Two leaves, so the flow's final state is a join rather than one token.
    net = Net(
        ["streamout", "drc", "lvs"],
        {"streamout": [], "drc": ["streamout"], "lvs": ["streamout"]},
    )
    net.put(Arc(None, "streamout"), "initial")
    for job in ["streamout", "drc", "lvs"]:
        net.consume(job)
        net.fire(job, f"{job}-out")

    assert net.sink_tokens() == {"drc": "drc-out", "lvs": "lvs-out"}


def test_sink_tokens_raises_while_a_leaf_has_not_fired():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    with pytest.raises(NetError) as exc_info:
        net.sink_tokens()

    assert "xor" in str(exc_info.value)
