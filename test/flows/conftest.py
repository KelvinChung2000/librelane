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
import os

import pytest

from test.conftest import MockConfTree


@pytest.fixture(autouse=True, scope="module")
def _isolated_step_registry():
    """
    The mock ``Test.*`` steps these fixtures register go into the global step
    factory, which nothing unregisters from -- so they leaked into whichever
    later test enumerated the registry, most visibly the deliberate-update
    variable count, which then failed or passed by worker scheduling.

    Module-scoped: registrations made by module-scoped fixtures must survive
    the tests that share them; only the module's departure sweeps them.
    """
    from librelane.steps import Step

    registry = Step.factory._StepFactory__registry
    snapshot = dict(registry)
    yield
    registry.clear()
    registry.update(snapshot)


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
def minimal_design(mock_conf_dir: MockConfTree):
    """
    The smallest design configuration the mock tree supports. Paired with
    :func:`mock_pdk`, which supplies the keyword half of a flow constructor.

    Parameters
    ----------
    mock_conf_dir : MockConfTree
        The real-filesystem mock tree, whose design directory the Verilog
        source is taken from. Real rather than faked because the engine runs
        its jobs on a thread pool and pyfakefs is single-threaded by design.

    Returns
    -------
    dict
        A design configuration, passed to a flow constructor positionally.
    """
    return {
        "DESIGN_NAME": "WHATEVER",
        "VERILOG_FILES": [os.path.join(mock_conf_dir.cwd, "src", "a.v")],
    }


@pytest.fixture
def mock_pdk(mock_conf_dir: MockConfTree):
    """
    The PDK keyword arguments that resolve against the mock tree. Spread into
    a flow constructor as ``**mock_pdk``.

    Parameters
    ----------
    mock_conf_dir : MockConfTree
        The real-filesystem mock tree, whose two roots these arguments name.

    Returns
    -------
    dict
        Keyword arguments for a flow constructor.
    """
    return {
        "design_dir": mock_conf_dir.cwd,
        "pdk": "dummy",
        "scl": "dummy_scl",
        "pdk_root": mock_conf_dir.pdk_root,
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
