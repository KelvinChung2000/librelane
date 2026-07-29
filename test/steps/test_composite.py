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

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _composite(mock_config):
    from librelane.config import variable
    from librelane.steps import Step
    from librelane.steps.step.composite import CompositeStep

    class Child(Step):
        id = "Test.CompositeChild"
        inputs = []
        outputs = []

        class Config(Step.Config):
            CHILD_KNOB: int = variable(3, description="Anything.")

        def run(self, state_in, **kwargs):
            return {}, {"test__child_knob": self.config.CHILD_KNOB}

    class Parent(CompositeStep):
        id = "Test.Composite"
        outputs = []
        Steps = [Child]

    from librelane.state import State

    return Parent(config=mock_config, state_in=State())


def test_composite_with_no_steps_is_rejected():
    """
    The inherited empty default would otherwise produce a composite whose run()
    iterates nothing and reports success.
    """
    from librelane.steps.step.composite import CompositeStep

    with pytest.raises(TypeError, match="declares no 'Steps'"):

        class Empty(CompositeStep):
            id = "Test.EmptyComposite"
            outputs = []


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_composite_children_do_not_reread_the_pdk(mock_config):
    """A reproducible's PDK_ROOT holds only copied files, never libs.tech."""
    from librelane.config import Config

    parent = _composite(mock_config)

    # Exactly what a reproducible looks like: the PDK config the loader would
    # want to re-read is not there. The reproducible runs in a fresh process,
    # so drop the memoized read that would otherwise hide its absence.
    os.remove("/pdk/dummy/libs.tech/librelane/config.tcl")
    Config._Config__get_pdk_raw.cache_clear()

    state_out = parent.start(step_dir="/cwd/composite")

    assert state_out.metrics["test__child_knob"] == 3


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_composite_children_still_receive_their_variables(mock_config):
    parent = _composite(mock_config)

    state_out = parent.start(step_dir="/cwd/composite2")

    assert state_out.metrics["test__child_knob"] == 3
