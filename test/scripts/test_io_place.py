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
"""
``min_area_dbu2`` is the one place io_place.py depends on the *type* of an odb
return value: ``dbTechLayer.getArea`` returned µm² as a float until OpenROAD
early 2026 and DBU² as an integer since. Getting the branch wrong inflates the
default pin length by dbu² (10⁶ at the usual 1000 DBU/µm), which placed I/O
pins hundreds of millimetres off-die — every port net then failed slew/cap
checks and repair_design buffered the design past 100% utilization.
"""
import runpy
import sys
from types import SimpleNamespace

import click
import pytest

pytestmark = pytest.mark.all

SCRIPT = "librelane/scripts/odbpy/io_place.py"


@pytest.fixture
def io_place_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "odb", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "reader",
        SimpleNamespace(click_odb=lambda function: function, click=click),
    )
    monkeypatch.setitem(
        sys.modules,
        "ioplace_parser",
        # sorter()'s annotation and body read these at module-exec time.
        SimpleNamespace(Order=SimpleNamespace(busMajor=0, bitMajor=1)),
    )
    return runpy.run_path(SCRIPT, run_name="io_place")


def layer_with_area(area):
    return SimpleNamespace(getArea=lambda: area)


def test_a_float_area_is_um2_and_scales_by_dbu_squared(io_place_module):
    # sky130 met2: 0.0676 µm² at 1000 DBU/µm.
    min_area_dbu2 = io_place_module["min_area_dbu2"]
    assert min_area_dbu2(layer_with_area(0.0676), 1000) == pytest.approx(67600)


def test_an_integer_area_is_already_dbu2_and_passes_through(io_place_module):
    min_area_dbu2 = io_place_module["min_area_dbu2"]
    assert min_area_dbu2(layer_with_area(67600), 1000) == 67600


def test_the_integer_branch_does_not_rescale_large_areas(io_place_module):
    # The regression shape: treating an already-DBU² integer as µm² would
    # return 6.76e10 here, the ~2×10⁸-DBU pin length seen off-die.
    min_area_dbu2 = io_place_module["min_area_dbu2"]
    assert min_area_dbu2(layer_with_area(67600), 1000) < 1_000_000
