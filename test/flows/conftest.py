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
