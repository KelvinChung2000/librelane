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
from typing import Literal, Optional, Union


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
    from librelane.config.variable import is_optional

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
    from librelane.config.variable import some_of

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


@pytest.fixture
def variable():
    from librelane.common import Path
    from librelane.config import Variable

    return Variable(
        "EXAMPLE",
        Optional[list[Path]],
        description="x",
        deprecated_names=["OLD_EXAMPLE"],
    )


@pytest.mark.usefixtures("_mock_fs")
def test_compile(variable):
    from librelane.common import GenericDict

    valid_input = GenericDict({"EXAMPLE": ["/cwd/a", "/cwd/b"]})
    warning_list = []
    used_name, paths = variable.compile(
        valid_input,
        warning_list,
    )
    assert used_name == "EXAMPLE", "valid input returned incorrect used name"
    assert [str(path) for path in paths] == [
        "/cwd/a",
        "/cwd/b",
    ], "valid input resolved paths incorrectly"
    assert len(warning_list) == 0, "valid input generated warning"


def test_compile_dataclass():
    from librelane.common import GenericDict
    from librelane.config import Variable

    @dataclass
    class MyClass:
        a: int
        b: str

    variable = Variable("MY_VARIABLE", MyClass, description="x")

    _, value = variable.compile(
        GenericDict({"MY_VARIABLE": {"a": 4, "b": "potato"}}), []
    )

    assert value == MyClass(a=4, b="potato"), "Failed to deserialize dataclass"


def test_compile_required():
    from librelane.common import GenericDict
    from librelane.config import Variable

    variable = Variable("MY_VARIABLE", int, description="x")

    with pytest.raises(
        ValueError,
        match=r"Required variable 'MY_VARIABLE' did not get a specified value",
    ):
        variable.compile(GenericDict({}), [])


@pytest.mark.usefixtures("_mock_fs")
def test_compile_deprecated(variable):
    from librelane.common import GenericDict

    deprecated_valid_input = GenericDict(
        {
            "OLD_EXAMPLE": [
                "/cwd/a",
                "/cwd/b",
            ]
        }
    )
    warning_list = []
    used_name, paths = variable.compile(
        deprecated_valid_input,
        warning_list,
    )
    assert used_name == "OLD_EXAMPLE", (
        "deprecated valid input returned incorrect used name"
    )
    assert [str(path) for path in paths] == [
        "/cwd/a",
        "/cwd/b",
    ], "deprecated valid input returned paths resolved incorrectly"
    assert len(warning_list) == 1, "use of deprecated names did not produce a warning"


@pytest.fixture
def test_enum():
    from enum import IntEnum

    class TestEnum(IntEnum):
        AValue = 0
        AnotherValue = 1

    return TestEnum


def test_compile_validators():
    from librelane.config import Variable
    from librelane.common import GenericDict

    def zero_to_one_validator(variable: Variable, input, _):
        if input < 0 or input > 1:
            raise ValueError(
                f"Value {input} for {variable.name} is invalid: must be between zero and one"
            )
        return input

    def zero_to_one_updater(variable: Variable, input, warning_list_ref):
        if input < 0:
            warning_list_ref.append(
                f"Value for {variable.name} less than 0. Setting to 0."
            )
            return type(input)(0)
        if input > 1:
            warning_list_ref.append(
                f"Value for {variable.name} higher than 1. Setting to 1."
            )
            return type(input)(1)
        return input

    checked = Variable(
        "TEST_VARIABLE_VALIDATOR", Decimal, "x", validator=zero_to_one_validator
    )

    warning_list_ref = []
    checked.compile(
        GenericDict({"TEST_VARIABLE_VALIDATOR": Decimal("0.5")}), warning_list_ref
    )

    with pytest.raises(ValueError, match="(must be between zero and one)"):
        checked.compile(
            GenericDict({"TEST_VARIABLE_VALIDATOR": Decimal("1.1")}), warning_list_ref
        )

    updated = Variable(
        "TEST_VARIABLE_UPDATER", Decimal, "x", validator=zero_to_one_updater
    )

    _, result = updated.compile(
        GenericDict({"TEST_VARIABLE_UPDATER": Decimal("0.5")}), warning_list_ref
    )
    assert result == Decimal("0.5"), "updater modified valid value"

    _, result = updated.compile(
        GenericDict({"TEST_VARIABLE_UPDATER": Decimal("24601")}), warning_list_ref
    )
    assert result == Decimal("1"), "updater did not modify out of scope value"
    assert len(warning_list_ref), "invalid updated value did not emit a warning"


@pytest.fixture
def variable_set(variable, test_enum):
    from librelane.config import Variable

    return [
        variable,
        Variable(
            "LIST_VAR",
            list[int],
            description="x",
        ),
        Variable(
            "TUPLE_2_VAR",
            tuple[int, int],
            description="x",
        ),
        Variable(
            "TUPLE_3_VAR",
            tuple[int, int, int],
            description="x",
        ),
        Variable(
            "TUPLE_4_VAR",
            tuple[str, int, int],
            description="x",
        ),
        Variable(
            "DICT_VAR",
            dict[str, str],
            description="x",
        ),
        Variable(
            "OTHER_DICT_VAR",
            dict[str, str],
            description="x",
        ),
        Variable(
            "ANOTHER_DICT_VAR",
            dict[str, str],
            description="x",
        ),
        Variable(
            "TCL_DICT_VAR",
            dict[str, str],
            description="x",
        ),
        Variable(
            "NESTED_DICT_VAR",
            dict[str, dict[str, dict[str, Decimal]]],
            description="x",
        ),
        Variable(
            "UNION_VAR",
            Union[int, dict[str, str]],
            description="x",
        ),
        Variable(
            "UNION_VAR_2",
            int | dict[str, str],
            description="x",
        ),
        Variable(
            "LITERAL_VAR",
            Literal["yes"],
            description="x",
            default="yes",
        ),
        Variable(
            "BOOL_VAR",
            bool,
            description="x",
        ),
        Variable(
            "ENUM_VAR",
            test_enum,
            description="x",
        ),
        Variable(
            "NUMBER_VAR",
            Decimal,
            description="x",
        ),
    ]


@pytest.mark.usefixtures("_mock_fs")
def test_compile_invalid(variable_set: list):
    from librelane.common import GenericDict

    invalid_input = GenericDict(
        {
            "EXAMPLE": [
                "/cwd/a",
                "/cwd/c",
            ],
            "LIST_VAR": {},
            "TUPLE_2_VAR": [1, {}],
            "TUPLE_3_VAR": [1, 4],
            "TUPLE_4_VAR": [1, 4],
            "DICT_VAR": ["1"],
            "OTHER_DICT_VAR": "bad tcl dictionary",
            "ANOTHER_DICT_VAR": ["1", "2", "3"],
            "TCL_DICT_VAR": "key1 'shell quoted'",
            "NESTED_DICT_VAR": "nom_* {met1 {res}}",
            "UNION_VAR": "lol",
            "UNION_VAR_2": "lol",
            "LITERAL_VAR": "no",
            "BOOL_VAR": "No",
            "ENUM_VAR": "NotAValue",
            "NUMBER_VAR": "v",
        }
    )
    warning_list = []

    for variable in variable_set:
        print(f"* Testing {variable.name} ({variable.type})…")
        with pytest.raises(
            ValueError,
            match="(is invalid)|(does not exist)",
        ):
            variable.compile(
                invalid_input,
                warning_list,
                permissive_typing=True,
            )


@pytest.mark.usefixtures("_mock_fs")
def test_compile_permissive(variable_set: list, test_enum: type):
    from librelane.common import GenericDict

    permissive_valid_input = GenericDict(
        {
            "EXAMPLE": "/cwd/a /cwd/b",
            "LIST_VAR": "4,5,6",
            "TUPLE_2_VAR": "1 2",
            "TUPLE_3_VAR": "1;2;3",
            "TUPLE_4_VAR": "asd;2;3",
            "DICT_VAR": "key1 value1 key2 value2",
            "OTHER_DICT_VAR": "key1 {value with spaces} key2 {[exec {touch ignored}]}",
            "ANOTHER_DICT_VAR": ["key1", "value1", "key2", "value2"],
            "TCL_DICT_VAR": "key1 value1 key2 value2",
            "NESTED_DICT_VAR": "nom_* {met1 {res 0.1 cap 0.2}}",
            "UNION_VAR": "4",
            "UNION_VAR_2": "4",
            "BOOL_VAR": "0",
            "ENUM_VAR": "AValue",
            "NUMBER_VAR": "90123",
        }
    )

    final = {}

    for variable in variable_set:
        _, value = variable.compile(
            permissive_valid_input,
            [],
            permissive_typing=True,
        )
        final[variable.name] = value

    assert final == {
        "EXAMPLE": [pathlib.Path("/cwd/a"), pathlib.Path("/cwd/b")],
        "LIST_VAR": [4, 5, 6],
        "TUPLE_2_VAR": (1, 2),
        "TUPLE_3_VAR": (1, 2, 3),
        "TUPLE_4_VAR": ("asd", 2, 3),
        "DICT_VAR": {"key1": "value1", "key2": "value2"},
        "OTHER_DICT_VAR": {
            "key1": "value with spaces",
            "key2": "[exec {touch ignored}]",
        },
        "ANOTHER_DICT_VAR": {"key1": "value1", "key2": "value2"},
        "TCL_DICT_VAR": {"key1": "value1", "key2": "value2"},
        "NESTED_DICT_VAR": {
            "nom_*": {
                "met1": {
                    "res": Decimal("0.1"),
                    "cap": Decimal("0.2"),
                }
            }
        },
        "UNION_VAR": 4,
        "UNION_VAR_2": 4,
        "BOOL_VAR": False,
        "ENUM_VAR": test_enum["AValue"],
        "NUMBER_VAR": Decimal("90123"),
        "LITERAL_VAR": "yes",
    }, "Permissive parsing mode returned an unexpected result"

    for variable in variable_set:
        if variable.name in ["LITERAL_VAR", "ENUM_VAR"]:
            continue
        print(f"* Testing {variable.name} ({variable.type})…")
        with pytest.raises(ValueError, match="Refusing"):
            variable.compile(
                permissive_valid_input,
                [],
            )
