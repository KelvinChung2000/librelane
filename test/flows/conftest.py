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


@pytest.fixture
def MetricIncrementer():
    """
    A step that does nothing but count how many times it ran, so a test can
    assert which steps a flow reached by reading one metric.
    """
    from librelane.steps import Step

    @Step.factory.register()
    class MetricIncrementer(Step):
        id = "Test.MetricIncrementer"
        inputs = []
        outputs = []

        counter_name = "counter"

        def run(self, state_in, **kwargs):
            metric_to_increment = state_in.metrics.get(self.counter_name, 0)
            metric_to_increment += 1
            return {}, {self.counter_name: metric_to_increment}

    return MetricIncrementer


@pytest.fixture
def minimal_design():
    """
    The smallest design configuration ``_mock_conf_fs`` supports. Paired with
    :func:`mock_pdk`, which supplies the keyword half of a flow constructor.
    """
    return {
        "DESIGN_NAME": "WHATEVER",
        "VERILOG_FILES": ["/cwd/src/a.v"],
    }


@pytest.fixture
def mock_pdk():
    """
    The PDK keyword arguments that resolve against the fake filesystem
    ``_mock_conf_fs`` builds. Spread into a flow constructor as ``**mock_pdk``.
    """
    return {
        "design_dir": "/cwd",
        "pdk": "dummy",
        "scl": "dummy_scl",
        "pdk_root": "/pdk",
    }


@pytest.fixture
def counting_steps():
    """
    Two trivially registered steps that record the order they ran in, so a
    test can assert the engine's firing order without invoking a real tool.

    The class's id, not the instance's. A flow is free to give an instance a
    per-run id -- :class:`librelane.flows.engine.Workflow` names the job in it
    so two concurrent runs of one step class can be told apart in the logs --
    and which class ran is what a firing-order assertion is about.

    Returns
    -------
    ``(order, First, Second)``, where ``order`` is the list the
    steps append their class ids to as they run.
    """
    from librelane.steps import Step

    order: list[str] = []

    @Step.factory.register()
    class First(Step):
        id = "Test.EngineFirst"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            order.append(type(self).id)
            return {}, {"first": 1}

    @Step.factory.register()
    class Second(Step):
        id = "Test.EngineSecond"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            order.append(type(self).id)
            return {}, {"second": 1}

    return order, First, Second
