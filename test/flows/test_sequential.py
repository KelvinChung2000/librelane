# Copyright 2023 Efabless Corporation
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

from librelane.flows import flow as flow_module, sequential as sequential_flow_module
from librelane.steps import Step, step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_sequential_flow(MetricIncrementer: type[Step]):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [
            MetricIncrementer,
            MetricIncrementer,
            MetricIncrementer,
            MetricIncrementer,
        ]

    flow = Dummy(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    assert [step.id for step in flow.Steps] == [
        "Test.MetricIncrementer",
        "Test.MetricIncrementer-1",
        "Test.MetricIncrementer-2",
        "Test.MetricIncrementer-3",
    ], "SequentialFlow did not increment IDs properly for duplicate steps"

    state = flow.start()
    assert state.metrics["counter"] == 4, "SequentialFlow did not run properly"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_custom_seqflow(MetricIncrementer):
    from librelane.flows import SequentialFlow

    MyFlow = SequentialFlow.Make(
        [
            "Test.MetricIncrementer",
            "Test.MetricIncrementer",
            "Test.MetricIncrementer",
            "Test.MetricIncrementer",
        ]
    )

    for step in MyFlow.Steps:
        assert issubclass(step, MetricIncrementer), (
            "CustomSequentialFlow could not properly import Steps by id"
        )

    flow = MyFlow(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    state = flow.start()
    assert state.metrics["counter"] == 4, "CustomSequentialFlow did not run properly"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_custom_seqflow_bad_id(MetricIncrementer):
    from librelane.flows import SequentialFlow

    with pytest.raises(TypeError, match="No step found with id"):
        SequentialFlow.Make(
            [
                "Test.MetricIncrementer",
                "Test.MetricIncrementer",
                "Test.NotARealIncrement",
                "Test.MetricIncrementer",
            ]
        )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_flow_control(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class OtherMetricIncrementer(MetricIncrementer):
        id = "Test.OtherMetricIncrementer"
        counter_name = "other_counter"

    class AnotherMetricIncrementer(MetricIncrementer):
        id = "Test.AnotherMetricIncrementer"
        counter_name = "another_counter"

    class YetAnotherMetricIncrementer(MetricIncrementer):
        id = "Test.YetAnotherMetricIncrementer"
        counter_name = "yet_another_counter"

    class LastMetricIncrementer(MetricIncrementer):
        id = "Test.LastMetricIncrementer"
        counter_name = "last_another_counter"

    class Dummy(SequentialFlow):
        Steps = [
            MetricIncrementer,
            OtherMetricIncrementer,
            AnotherMetricIncrementer,
            YetAnotherMetricIncrementer,
            LastMetricIncrementer,
        ]

    flow = Dummy(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    # --from takes the steps before it from their previous results rather than
    # skipping them, so the tag has to have been run once for there to be a
    # result to take. Starting from the middle of a tag that was never run is
    # an error, covered by test_from_on_a_fresh_tag_refuses.
    flow.start(tag="FLOW_CONTROL")

    state = flow.start(
        tag="FLOW_CONTROL",
        frm="test.othermetricincrementer",
        to="test.lastmetricincrement*",
        skip=["test.*another*"],
    )
    assert list(state.metrics.keys()) == [
        "counter",
        "other_counter",
        "last_another_counter",
    ], "flow control did not yield the expected results"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_wildcard_gating(MetricIncrementer):
    from librelane.flows import SequentialFlow
    from librelane.config import Variable

    class OtherMetricIncrementer(MetricIncrementer):
        id = "Test.OtherMetricIncrementer"

    class AnotherMetricIncrementer(MetricIncrementer):
        id = "Test.AnotherMetricIncrementer"

    class YetAnotherMetricIncrementer(MetricIncrementer):
        id = "Test.YetAnotherMetricIncrementer"

    class LastMetricIncrementer(MetricIncrementer):
        id = "Test.LastMetricIncrementer"

    class Dummy(SequentialFlow):
        Steps = [
            MetricIncrementer,
            OtherMetricIncrementer,
            AnotherMetricIncrementer,
            YetAnotherMetricIncrementer,
            LastMetricIncrementer,
        ]

        config_vars = [
            Variable("TEST_GATING_VARIABLE", bool, description="x", default=False)
        ]

        gating_config_vars = {"*AnotherMetric*": ["TEST_GATING_VARIABLE"]}

    flow = Dummy(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    state = flow.start()
    assert state.metrics["counter"] == 3, "Gating variable did not work properly"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_gating_validation(MetricIncrementer):
    from librelane.flows import SequentialFlow
    from librelane.config import Variable

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

        config_vars = [
            Variable("TEST_GATING_VARIABLE", bool, description="x", default=False),
            Variable("BAD_GATING_VARIABLE", int, description="x", default=0),
        ]

    with pytest.raises(TypeError, match="does not match any declared config_vars"):

        class _Test1(Dummy):
            gating_config_vars = {"Test.MetricIncrementer": ["DOESNT_MATCH_ANYTHING"]}

    with pytest.raises(TypeError, match="is not a Boolean"):

        class _Test2(Dummy):
            gating_config_vars = {"Test.MetricIncrementer": ["BAD_GATING_VARIABLE"]}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_from_works_when_an_earlier_step_is_gated(MetricIncrementer):
    """
    A gated step never reached the execute path, so it wrote no resume entry.
    Requiring one from it made --from unusable on any flow with a gate turned
    off, which is every real configuration.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.Gated"
        counter_name = "gated_counter"

    class Later(MetricIncrementer):
        id = "Test.Later"
        counter_name = "later_counter"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated, Later]

        config_vars = [Variable("TEST_GATE", bool, description="x", default=False)]

        gating_config_vars = {"Test.Gated": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    flow.start(tag="GATED_FROM")

    state = flow.start(tag="GATED_FROM", frm="Test.Later")
    # Metrics do not accumulate across runs: each run's state chain starts
    # empty, so Later increments from zero both times. What is being pinned is
    # that the run reaches Later at all, having reused the step before the gate
    # and passed over the gate itself without demanding a resume entry from it.
    assert state.metrics["counter"] == 1
    assert state.metrics["later_counter"] == 1


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_reproducible_of_a_gated_step_raises_naming_the_gate(MetricIncrementer):
    """
    Packaging a reproducible for a step this configuration would never execute
    is a contradiction. It used to be resolved by discarding the request and
    running the whole flow instead, with no message.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow, FlowException

    class Gated(MetricIncrementer):
        id = "Test.GatedRepro"
        counter_name = "gated_counter"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated]

        config_vars = [Variable("TEST_GATE", bool, description="x", default=False)]

        gating_config_vars = {"Test.GatedRepro": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    with pytest.raises(FlowException, match="TEST_GATE"):
        flow.start(reproducible="Test.GatedRepro")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_each_skip_reason_names_its_cause(MetricIncrementer, caplog):
    """
    Three unrelated mechanisms used to emit the identical 'Skipping step' line,
    so a user reading a log could not tell which one had fired.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.GatedReason"

    class Skipped(MetricIncrementer):
        id = "Test.SkippedReason"

    class Windowed(MetricIncrementer):
        id = "Test.WindowedReason"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated, Skipped, Windowed]

        config_vars = [Variable("TEST_GATE", bool, description="x", default=False)]

        gating_config_vars = {"Test.GatedReason": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    flow.start(skip=["Test.SkippedReason"], to="Test.SkippedReason")

    assert "TEST_GATE" in caplog.text
    assert "--skip" in caplog.text
    assert "--to" in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_overlapping_gating_keys_union_rather_than_overwrite(MetricIncrementer):
    """
    A wildcard key and an exact key matching the same step both apply. Taking
    the last one in iteration order silently dropped the other, which on a
    StagedFlow means dropping the stage gate a flow never wrote by hand and
    cannot see.
    """
    from librelane.flows import SequentialFlow

    expanded = SequentialFlow._expand_gating_config_vars(
        {
            "Test.Alpha": ["EXACT_GATE"],
            "Test.Alph*": ["WILDCARD_GATE"],
        },
        ["Test.Alpha", "Test.Beta"],
    )

    assert expanded["Test.Alpha"] == ["EXACT_GATE", "WILDCARD_GATE"]
    assert "Test.Beta" not in expanded


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_gating_union_is_order_independent():
    from librelane.flows import SequentialFlow

    forward = SequentialFlow._expand_gating_config_vars(
        {"Test.Alph*": ["WILDCARD_GATE"], "Test.Alpha": ["EXACT_GATE"]},
        ["Test.Alpha"],
    )

    assert sorted(forward["Test.Alpha"]) == ["EXACT_GATE", "WILDCARD_GATE"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_gating_union_deduplicates():
    from librelane.flows import SequentialFlow

    expanded = SequentialFlow._expand_gating_config_vars(
        {"Test.Alpha": ["SHARED_GATE"], "Test.Alph*": ["SHARED_GATE"]},
        ["Test.Alpha"],
    )

    assert expanded["Test.Alpha"] == ["SHARED_GATE"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_a_mistyped_step_id_raises_and_suggests(MetricIncrementer, monkeypatch):
    """
    The suggestion stays; proceeding on the guess does not. The environment
    variable that used to make a near miss run anyway is gone, so setting it
    changes nothing.
    """
    from librelane.flows import SequentialFlow, FlowException

    monkeypatch.setenv(
        "_i_want_librelane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks",
        "1",
    )

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    with pytest.raises(FlowException, match="Did you mean"):
        flow.start(frm="Test.MetricIncrementerr")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_resolve_step_id_is_reachable_without_running(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    assert flow._resolve_step_id("test.metricincrementer") == "Test.MetricIncrementer"
    assert flow._resolve_step_id(None) is None
    assert flow._resolve_step_id("test.*", multiple_ok=True) == [
        "Test.MetricIncrementer"
    ]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_the_run_gets_an_aggregate_runtimes_csv(MetricIncrementer: type[Step]):
    """
    Issue 812: every step drops a runtime.txt in its own directory, so asking
    "what was slow?" meant walking every step directory and collating by hand.
    """
    import csv
    import pathlib

    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, MetricIncrementer]

    flow = Dummy(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    flow.start()

    with open(pathlib.Path(flow.run_dir) / "runtimes.csv", encoding="utf8") as f:
        rows = list(csv.DictReader(f))

    assert [row["step_id"] for row in rows] == [
        "Test.MetricIncrementer",
        "Test.MetricIncrementer-1",
    ]
    for row in rows:
        # The step directory is what lines a row up with the run on disk.
        assert row["step_dir"]
        assert float(row["elapsed_seconds"]) >= 0.0
        assert row["elapsed"].count(":") == 2
