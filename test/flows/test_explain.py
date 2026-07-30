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

from librelane.flows import flow as flow_module, sequential as sequential_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

_MINIMAL_DESIGN = {
    "DESIGN_NAME": "WHATEVER",
    "VERILOG_FILES": ["/cwd/src/a.v"],
}
_MOCK_PDK = {
    "design_dir": "/cwd",
    "pdk": "dummy",
    "scl": "dummy_scl",
    "pdk_root": "/pdk",
}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_every_step_of_an_unconstrained_flow_will_run(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain()

    assert [d.step_id for d in explanation.steps] == ["Test.MetricIncrementer"]
    assert all(d.will_run for d in explanation.steps)
    assert all(d.mechanism is None for d in explanation.steps)
    assert explanation.unselected_stages == ()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_gated_step_names_its_gate(MetricIncrementer):
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.ExplainGated"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated]

        config_vars = [Variable("TEST_GATE", bool, description="x", default=False)]

        gating_config_vars = {"Test.ExplainGated": ["TEST_GATE"]}

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain()

    gated = explanation.steps[1]
    assert gated.step_id == "Test.ExplainGated"
    assert gated.will_run is False
    assert gated.mechanism == "gate"
    assert "TEST_GATE" in gated.reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_skip_and_window_attribute_correctly(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Second(MetricIncrementer):
        id = "Test.ExplainSecond"

    class Third(MetricIncrementer):
        id = "Test.ExplainThird"

    class Fourth(MetricIncrementer):
        id = "Test.ExplainFourth"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Second, Third, Fourth]

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain(
        frm="Test.ExplainSecond",
        to="Test.ExplainThird",
        skip=["Test.ExplainSecond"],
    )

    by_id = {d.step_id: d for d in explanation.steps}
    assert by_id["Test.MetricIncrementer"].mechanism == "window"
    assert "--from" in by_id["Test.MetricIncrementer"].reason
    assert by_id["Test.ExplainSecond"].mechanism == "skip"
    assert by_id["Test.ExplainThird"].will_run is True
    assert by_id["Test.ExplainFourth"].mechanism == "window"
    assert "--to" in by_id["Test.ExplainFourth"].reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_deselected_provider_s_steps_are_absent_not_excluded(mock_config):
    """
    A step dropped by TOOLS is not in the resolved list at all, so it has no
    entry. Provider selection is therefore not among the mechanisms a step
    entry can carry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values.update({"RUN_KLAYOUT_XOR": False, "TOOLS": {"streamout": "klayout"}})
    flow = Classic(mock_config.copy(**values))

    explanation = flow.explain()
    ids = [d.step_id for d in explanation.steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_turning_off_run_cts_excludes_every_step_of_the_stage(mock_config):
    """
    A stage gate is lowered onto each step of the stage, so every step of the
    cts stage reports the same gate. This is the case a user actually hits,
    and the one describe_stages cannot answer.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values["RUN_CTS"] = False
    flow = Classic(mock_config.copy(**values))

    cts = [
        d
        for d in flow.explain().steps
        if d.mechanism == "gate" and "RUN_CTS" in d.reason
    ]
    assert [d.step_id for d in cts] == ["OpenROAD.CTS"]
    assert all(d.will_run is False for d in cts)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_an_unselected_stage_is_reported_separately(mock_config):
    """
    Stage.post_route_opt has a None default provider, so it contributes no
    steps and cannot be a step entry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    flow = Classic(mock_config.copy(**values))

    assert "post_route_opt" in flow.explain().unselected_stages


def test_format_explanation_renders_every_row():
    from librelane.cli.run import format_explanation
    from librelane.flows import Explanation, StepDisposition

    rendered = format_explanation(
        Explanation(
            steps=(
                StepDisposition("Test.Alpha", True, "will run", None),
                StepDisposition("Test.Beta", False, "gated off by RUN_BETA", "gate"),
            ),
            unselected_stages=("post_route_opt",),
        )
    )

    assert "Test.Alpha" in rendered
    assert "Test.Beta" in rendered
    assert "RUN_BETA" in rendered
    assert "gate" in rendered
    assert "post_route_opt" in rendered
