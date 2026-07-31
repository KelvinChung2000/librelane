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
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.all


def test_replace_eco_cells_is_registered():
    """Issue 967: an ECO step that can replace the cell of an instance."""
    import librelane.steps  # noqa: F401
    from librelane.steps import Step

    resolved = Step.factory.get("Odb.ReplaceECOCells")

    assert resolved is not None
    assert resolved.id == "Odb.ReplaceECOCells"


def test_replace_eco_cells_takes_the_three_documented_fields():
    from librelane.steps.odb.eco import ECOCellReplacement

    replacement = ECOCellReplacement(instance="^fanout.*", replace_with="buf_1")

    assert replacement.current_cell is None
    assert (
        ECOCellReplacement(
            instance="^fanout.*", replace_with="buf_1", current_cell="dlyb_1"
        ).current_cell
        == "dlyb_1"
    )


def test_replace_eco_cells_does_nothing_without_the_variable():
    """OpenROAD must not be launched at all for an empty ECO."""
    from librelane.steps.odb.eco import ReplaceECOCells

    step = object.__new__(ReplaceECOCells)
    step.config = SimpleNamespace(REPLACE_ECO_CELLS=None)

    assert step.run(None) == ({}, {})
