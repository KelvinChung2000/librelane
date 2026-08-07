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
import os
import pytest
import pathlib
from decimal import Decimal
from dataclasses import dataclass
from pyfakefs.fake_filesystem_unittest import Patcher
from typing import Optional, Union


pytestmark = pytest.mark.all


@pytest.fixture
def _mock_fs():
    with Patcher() as patcher:
        patcher.fs.create_dir("/cwd")
        os.chdir("/cwd")
        patcher.fs.create_file("/cwd/a")
        patcher.fs.create_file("/cwd/b")
        yield


def test_macro_validation():
    from librelane.config import Macro

    with pytest.raises(ValueError, match="at least one GDSII file"):
        Macro(gds=[], lef=["test"])

    with pytest.raises(ValueError, match="at least one LEF file"):
        Macro(gds=["test"], lef=[])

    with pytest.raises(TypeError, match="got an unexpected keyword argument"):
        Macro(gds=["test"], lef=["test"], lefs=[])


def _array_macro(name_template, **array_overrides):
    from librelane.config import Instance, InstanceArray, Macro, Orientation

    array = {
        "offset": (Decimal("100"), Decimal("100")),
        "step": (Decimal("100"), Decimal("50")),
        "dimensions": (2, 3),
    }
    array.update(array_overrides)
    return Macro(
        gds=["test"],
        lef=["test"],
        instances={
            name_template: Instance(
                orientation=Orientation.N,
                array=InstanceArray(**array),
            )
        },
    )


def test_macro_array_is_expanded_into_one_instance_per_cell():
    """Two rows of three, filled left to right from the bottom."""
    macro = _array_macro("sram_{X}_{Y}")

    assert {name: instance.location for name, instance in macro.instances.items()} == {
        "sram_0_0": (Decimal("100"), Decimal("100")),
        "sram_1_0": (Decimal("200"), Decimal("100")),
        "sram_2_0": (Decimal("300"), Decimal("100")),
        "sram_0_1": (Decimal("100"), Decimal("150")),
        "sram_1_1": (Decimal("200"), Decimal("150")),
        "sram_2_1": (Decimal("300"), Decimal("150")),
    }


def test_macro_array_keeps_the_orientation_and_drops_the_template():
    from librelane.config import Orientation

    macro = _array_macro("sram_{X}_{Y}")

    assert "sram_{X}_{Y}" not in macro.instances
    assert all(
        instance.orientation is Orientation.N for instance in macro.instances.values()
    )
    assert all(instance.array is None for instance in macro.instances.values())


def test_macro_array_supports_the_row_col_and_seq_names():
    macro = _array_macro("sram_r{ROW}c{COL}n{SEQ}")

    assert sorted(macro.instances) == [
        "sram_r0c0n0",
        "sram_r0c1n1",
        "sram_r0c2n2",
        "sram_r1c0n3",
        "sram_r1c1n4",
        "sram_r1c2n5",
    ]


def test_a_macro_array_may_not_also_be_placed_by_hand():
    from librelane.config import Instance, InstanceArray, Macro

    with pytest.raises(RuntimeError, match="both a location and an array"):
        Macro(
            gds=["test"],
            lef=["test"],
            instances={
                "sram_{X}_{Y}": Instance(
                    location=(Decimal("1"), Decimal("1")),
                    array=InstanceArray(
                        offset=(Decimal("0"), Decimal("0")),
                        step=(Decimal("1"), Decimal("1")),
                        dimensions=(2, 2),
                    ),
                )
            },
        )


def test_macros_without_arrays_are_left_alone():
    from librelane.config import Instance, Macro

    macro = Macro(
        gds=["test"],
        lef=["test"],
        instances={"sram": Instance(location=(Decimal("5"), Decimal("6")))},
    )

    assert list(macro.instances) == ["sram"]
    assert macro.instances["sram"].location == (Decimal("5"), Decimal("6"))


def test_macro_from_state():
    from librelane.common import DUMMY_PATH
    from librelane.config import Macro
    from librelane.state import State

    state_in = State(
        {
            "nl": DUMMY_PATH,
            "pnl": DUMMY_PATH,
            "def": DUMMY_PATH,
            "odb": DUMMY_PATH,
            "sdf": {
                "corner_1": DUMMY_PATH,
                "corner_2": DUMMY_PATH,
            },
            "spef": {
                "corner_*": DUMMY_PATH,
            },
            "lib": {
                "corner_1": DUMMY_PATH,
                "corner_2": DUMMY_PATH,
            },
            "gds": DUMMY_PATH,
        },
        metrics={},
    )

    with pytest.raises(
        ValueError,
        match="Macro cannot be made out of input state: View lef is missing",
    ):
        Macro.from_state(state_in)

    state_fixed = State(state_in, overrides={"lef": DUMMY_PATH})
    macro = Macro.from_state(state_fixed)
    assert macro == Macro(
        gds=[pathlib.Path("__librelane_dummy_path")],
        lef=[pathlib.Path("__librelane_dummy_path")],
        instances={},
        nl=[pathlib.Path("__librelane_dummy_path")],
        pnl=[pathlib.Path("__librelane_dummy_path")],
        spef={"corner_*": [pathlib.Path("__librelane_dummy_path")]},
        lib={
            "corner_1": [pathlib.Path("__librelane_dummy_path")],
            "corner_2": [pathlib.Path("__librelane_dummy_path")],
        },
        spice=[],
        sdf={
            "corner_1": [pathlib.Path("__librelane_dummy_path")],
            "corner_2": [pathlib.Path("__librelane_dummy_path")],
        },
        json_h=None,
    ), "Macro was not derived from State correctly"


def test_is_optional():
    from librelane.config.legacy import is_optional

    assert is_optional(int) is False, "is_optional false positive"
    assert is_optional(Optional[int]) is True, "is_optional false negative"
    assert is_optional(Optional[int | dict]) is True, (
        "is_optional composite false negative"
    )
    assert is_optional(Union[None, int, dict]) is True, (
        "is_optional flattened union false negative"
    )
    assert is_optional(int | None) is True
    assert is_optional(int | dict | None) is True


def test_some_of():
    from librelane.config.legacy import some_of

    assert some_of(int) is int, "some_of changed the type of a non-option type"
    assert some_of(list[str]) == list[str], (
        "some_of changed the type of a non-option type"
    )
    assert some_of(Optional[int]) is int, (
        "some_of failed to extract type from option type"
    )
    assert some_of(Optional[dict | list]) == Union[dict, list], (
        "some of failed to properly handle optional union"
    )

    assert some_of(Union[dict, list, None]) == Union[dict, list], (
        "some of failed to properly handle flattened optional union"
    )
    assert some_of(int | None) is int, (
        "some of failed to properly handle PEP 604 optional union"
    )
    assert some_of(dict | list | None) == dict | list, (
        "some of failed to properly handle PEP 604 flattened optional union"
    )


def test_variable_construction():
    from librelane.config import Variable

    variable = Variable(
        "EXAMPLE",
        Optional[int],
        description="My Description",
        deprecated_names=["OLD_EXAMPLE"],
    )

    assert variable.optional, ".optional property incorrectly set"
    assert variable.some is int, ".some property incorrectly set"

    variable_b = Variable(
        "EXAMPLE",
        Optional[int],
        description="My Other Description",
    )

    assert variable == variable_b, (
        "Variable with different description or deprecated_name didn't match"
    )

    variable_c = Variable(
        "EXAMPLE",
        int | None,
        description="My Description",
    )

    assert variable == variable_c, (
        "Variable with different description or deprecated_name didn't match"
    )

    variable_union = Variable(
        "UNION_VAR",
        Union[int, dict[str, str]],
        description="x",
    )
    assert variable_union.type == Union[int, dict[str, str]], (
        "Union magically switched types"
    )

    variable_union_new = Variable(
        "UNION_VAR",
        int | dict[str, str],
        description="x",
    )
    assert variable_union_new.type == int | dict[str, str], (
        "PEP 604 union didn't match typing union"
    )
    assert variable_union.type == variable_union_new.type, (
        "Variable with different union syntax didn't match"
    )
