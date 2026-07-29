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
from decimal import Decimal

import pytest

from librelane.scripts.pyosys.construct_abc_script import ABCScriptCreator


def _config(**overrides):
    config = {
        "CLOCK_PERIOD": Decimal("10"),
        "SYNTH_ABC_LEGACY_REFACTOR": False,
        "SYNTH_ABC_LEGACY_REWRITE": False,
        "SYNTH_ABC_USE_MFS3": False,
        "SYNTH_ABC_AREA_USE_NF": False,
        "SYNTH_ABC_BUFFERING": True,
        "SYNTH_SIZING": False,
        "MAX_FANOUT_CONSTRAINT": None,
        "MAX_TRANSITION_CONSTRAINT": None,
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize("strategy", ["AREA 3", "DELAY 4", "AREA 0"])
def test_no_fanout_flag_when_constraint_unset(tmp_path, strategy):
    """An unset MAX_FANOUT_CONSTRAINT must omit ABC's -N, not stringify None."""
    creator = ABCScriptCreator(_config())
    script = open(creator.generate_abc_script(str(tmp_path), strategy)).read()

    assert "None" not in script
    assert "-N" not in script
    assert "buffer" in script


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("AREA 3", "buffer -c -N 12"),
        ("DELAY 4", "buffer -c -N 12"),
        ("AREA 0", "buffer -N 12"),
    ],
)
def test_fanout_flag_passed_through_when_set(tmp_path, strategy, expected):
    creator = ABCScriptCreator(_config(MAX_FANOUT_CONSTRAINT=12))
    script = open(creator.generate_abc_script(str(tmp_path), strategy)).read()

    assert expected in script


def test_max_transition_still_emitted_without_fanout(tmp_path):
    """The two constraints are independent -- one being unset must not drop the other."""
    creator = ABCScriptCreator(
        _config(MAX_TRANSITION_CONSTRAINT=Decimal("0.75")),
    )
    script = open(creator.generate_abc_script(str(tmp_path), "AREA 0")).read()

    assert "buffer -S 750" in script
    assert "-N" not in script
