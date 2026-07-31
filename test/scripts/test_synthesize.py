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
import importlib
import sys
from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.fixture
def synthesize(monkeypatch):
    """Import the pyosys synthesis script without a Yosys installation.

    The script is run by Yosys' own interpreter with its directory on
    PYTHONPATH, so it imports its neighbours by bare name.
    """
    monkeypatch.setitem(sys.modules, "ys_common", SimpleNamespace(ys=mock.Mock()))
    monkeypatch.setitem(
        sys.modules,
        "construct_abc_script",
        SimpleNamespace(ABCScriptCreator=mock.Mock()),
    )
    return importlib.import_module("librelane.scripts.pyosys.synthesize")


def _passes(design):
    return [call.args[0] for call in design.run_pass.call_args_list]


def _run_synth(synthesize, **overrides):
    design = mock.Mock()
    # The opt loops repeat until this reports no further progress.
    design.scratchpad_get_bool.return_value = False
    kwargs = {
        "keep_hierarchy_min_cost": None,
        "keep_hierarchy_instances": [],
        "keep_hierarchy_modules": [],
    }
    kwargs.update(overrides)
    synthesize.librelane_synth(design, "top", False, "/tmp/reports", **kwargs)
    return _passes(design)


def test_arith_tree_runs_after_alumacc(synthesize):
    passes = _run_synth(synthesize, arith_tree=True)

    assert "arith_tree" in passes
    assert passes.index("arith_tree") == passes.index("alumacc") + 1


def test_arith_tree_can_be_turned_off(synthesize):
    passes = _run_synth(synthesize, arith_tree=False)

    assert "arith_tree" not in passes
    assert "alumacc" in passes
