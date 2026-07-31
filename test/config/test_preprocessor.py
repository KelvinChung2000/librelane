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
import json
import builtins
from decimal import Decimal
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem_unittest import Patcher


pytestmark = pytest.mark.all
EXPRESSION_CASES = Path(__file__).with_name("expression_cases.json")


@pytest.fixture(autouse=True)
def _mock_fs():
    with Patcher() as patcher:
        patcher.fs.create_dir("/cwd")
        patcher.fs.create_file("/cwd/src/a_file.v")
        patcher.fs.create_file("/cwd/src/another_file.v")
        patcher.fs.create_file("/ncwd/src/a_file.v")
        patcher.fs.create_file("/ncwd/src/another_file.v")
        patcher.fs.create_file(
            "/cwd/src/files.f",
            contents=(
                "+incdir+/cwd/src\n"
                "+define+TARGET_SYNTHESIS\n"
                "\n"
                "/cwd/src/a_file.v\n"
                "/cwd/src/another_file.v\n"
            ),
        )
        patcher.fs.create_file("/cwd/src/bad.f", contents="+notadirective+value\n")
        os.chdir("/cwd")
        yield


def test_expr():
    from librelane.config.preprocessor import Expr

    assert Expr.evaluate("5 + 4 * (2 + 1)", {}) == 17, "Order of evaluation failure"

    assert Expr.evaluate("5 + 4 * (2 + $A)", {"A": 20}) == 93, (
        "Variable dereferencing failure"
    )

    assert Expr.evaluate("5 + 4 * (2 + $A[0].B)", {"A[0].B": 1}) == 17, (
        "Deep variable dereferencing failure"
    )

    with pytest.raises(TypeError, match="valid numeric"):
        Expr.evaluate("5 + 4 * (2 + $A)", {"A": "20"}) == 93

    with pytest.raises(ValueError, match="is empty"):
        Expr.evaluate("", {})

    with pytest.raises(ValueError, match="multiple values"):
        Expr.evaluate("(5 + 4) (8 + 10)", {})


@pytest.mark.parametrize(
    ("expression", "symbols", "expected"),
    [
        ("2 ** 3 ** 2", {}, Decimal("512")),
        (" -2 + 3 ", {}, Decimal("1")),
        ("2*-3", {}, Decimal("-6")),
        ("-2**2", {}, Decimal("4")),
        ("2**-2", {}, Decimal("0.25")),
        ("$A[0].B * 2", {"A[0].B": 3}, Decimal("6")),
        ("(1 + 2", {}, Decimal("3")),
    ],
)
def test_expr_characterization(expression, symbols, expected):
    from librelane.config.preprocessor import Expr

    assert Expr.evaluate(expression, symbols) == expected


@pytest.mark.parametrize(
    ("expression", "symbols", "exception", "message"),
    [
        ("1 + @", {}, SyntaxError, "Unexpected token"),
        ("1 +", {}, SyntaxError, "not enough operands"),
        ("1 + 2)", {}, IndexError, "list index out of range"),
        ("1 2", {}, ValueError, "multiple values"),
        ("", {}, ValueError, "is empty"),
        ("--2", {}, SyntaxError, "not enough operands"),
        ("$MISSING", {}, TypeError, "not found"),
        ("$TEXT", {"TEXT": "2"}, TypeError, "valid numeric"),
    ],
)
def test_expr_error_characterization(expression, symbols, exception, message):
    from librelane.config.preprocessor import Expr

    with pytest.raises(exception, match=message):
        Expr.evaluate(expression, symbols)


@pytest.mark.parametrize("case", json.loads(EXPRESSION_CASES.read_text()))
def test_expr_golden_cases(case):
    from librelane.config.preprocessor import Expr, process_string

    expression = case["expression"]
    symbols = case["symbols"]
    if expected := case.get("result"):
        assert Expr.evaluate(expression, symbols) == Decimal(expected)
        assert process_string(f"expr::{expression}", symbols) == Decimal(expected)
        return

    exception = getattr(builtins, case["exception"])
    with pytest.raises(exception) as evaluate_error:
        Expr.evaluate(expression, symbols)
    assert str(evaluate_error.value) == case["message"]

    with pytest.raises(exception) as process_error:
        process_string(f"expr::{expression}", symbols)
    assert str(process_error.value) == case.get("process_message", case["message"])


def test_process_string():
    from librelane.config.preprocessor import process_string

    assert process_string("expr::2 * 2", {}) == 4, "expr:: not working"

    assert process_string("ref::$A", {"A": "B"}) == "B", "ref:: not working"

    with pytest.raises(KeyError, match="not found"):
        process_string("ref::$A", {})

    assert process_string("refg::$DESIGN_DIR/src/a*.v", {"DESIGN_DIR": "/cwd"}) == [
        "/cwd/src/a_file.v",
        "/cwd/src/another_file.v",
    ], "refg:: in design dir not working"

    assert process_string(
        "refg::$DESIGN_DIR/src/a*.v", {"DESIGN_DIR": "/cwd"}
    ) == process_string("dir::src/a*.v", {"DESIGN_DIR": "/cwd"}), (
        "dir:: doesn't match refg::$DESIGN_DIR"
    )

    assert process_string("refg::$A/*", {"A": "B"}) == ["B/*"], (
        "refg:: on non-existent directory not working"
    )
    assert process_string("refg::$A", {"A": "B"}) == ["B"], (
        "refg:: without asterisks or ? did not return the same file path"
    )


mmpt_raw = {
    "meta": {"version": 2},
    "PDK": "sky130A",
    "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
    "DESIGN_NAME": "manual_macro_placement_test",
    "VERILOG_FILES": "dir::src/*.v",
    "MACROS": {
        "spm": {
            "module": "spm",
            "instances": {
                "spm_inst_0": {"location": [10, 150], "orientation": "N"},
                "spm_inst_1": {
                    "location": [
                        "expr::$MACROS.spm.instances.spm_inst_0.location[1]",
                        150.00,
                    ],
                    "orientation": "N",
                },
            },
        },
    },
}


def test_process_info_extraction():
    from librelane.config.preprocessor import preprocess_dict

    process_info = preprocess_dict(
        mmpt_raw,
        "/cwd",
        only_extract_process_info=True,
    )

    assert process_info["PDK"] == "sky130A", (
        "Failed to properly extract PDK info from config"
    )

    assert process_info["STD_CELL_LIBRARY"] == "sky130_fd_sc_hd", (
        "Failed to properly extract PDK info from config"
    )


def test_preprocess_dict():
    from librelane.config.preprocessor import preprocess_dict

    preprocessed = preprocess_dict(
        mmpt_raw,
        "/cwd",
        pdk="sky130A",
        pdkpath="/cwd",
        scl="sky130_fd_sc_hd",
    )
    expected = {
        "PDK": "sky130A",
        "PDKPATH": "/cwd",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
        "PAD_CELL_LIBRARY": None,
        "DESIGN_DIR": "/cwd",
        "meta": {"version": 2},
        "DESIGN_NAME": "manual_macro_placement_test",
        "VERILOG_FILES": ["/cwd/src/a_file.v", "/cwd/src/another_file.v"],
        "MACROS": {
            "spm": {
                "module": "spm",
                "instances": {
                    "spm_inst_0": {"location": [10, 150], "orientation": "N"},
                    "spm_inst_1": {
                        "location": [Decimal("150"), 150.0],
                        "orientation": "N",
                    },
                },
            }
        },
    }
    assert preprocessed == expected, "Preprocessor produced a different result"


def _preprocess_flist(config):
    from librelane.config.preprocessor import preprocess_dict

    return preprocess_dict(
        {
            "meta": {"version": 2},
            "DESIGN_NAME": "flist_test",
            **config,
        },
        "/cwd",
        pdk="sky130A",
        pdkpath="/cwd",
        scl="sky130_fd_sc_hd",
    )


def test_flist_is_folded_into_the_keys_it_names():
    preprocessed = _preprocess_flist({"VERILOG_FLIST_FILES": ["dir::src/files.f"]})

    assert preprocessed["VERILOG_FILES"] == [
        "/cwd/src/a_file.v",
        "/cwd/src/another_file.v",
    ]
    assert preprocessed["VERILOG_INCLUDE_DIRS"] == ["/cwd/src"]
    assert preprocessed["VERILOG_DEFINES"] == ["TARGET_SYNTHESIS"]
    # Nothing downstream knows this key, and unknown keys are rejected.
    assert "VERILOG_FLIST_FILES" not in preprocessed


def test_flist_appends_to_verilog_files_already_given_as_a_string():
    """A list variable may be written as a bare string, so the F-list has to
    widen it rather than append to it."""
    preprocessed = _preprocess_flist(
        {
            "VERILOG_FLIST_FILES": ["dir::src/files.f"],
            "VERILOG_FILES": "/cwd/src/preexisting.v",
        }
    )

    assert preprocessed["VERILOG_FILES"] == [
        "/cwd/src/preexisting.v",
        "/cwd/src/a_file.v",
        "/cwd/src/another_file.v",
    ]


def test_an_unknown_flist_directive_is_an_error():
    with pytest.raises(RuntimeError, match="notadirective"):
        _preprocess_flist({"VERILOG_FLIST_FILES": ["dir::src/bad.f"]})


def test_no_flist_leaves_the_configuration_alone():
    preprocessed = _preprocess_flist({"VERILOG_FILES": "dir::src/*.v"})

    assert preprocessed["VERILOG_FILES"] == [
        "/cwd/src/a_file.v",
        "/cwd/src/another_file.v",
    ]


def test_forward_reference_and_cycle():
    from librelane.config.preprocessor import SymbolCycleError, resolve_symbols

    resolved = resolve_symbols(
        {
            "FIRST": "ref::$SECOND/end",
            "SECOND": "value",
        },
        {},
    )
    assert resolved["FIRST"] == "value/end"

    with pytest.raises(SymbolCycleError, match=r"A -> B -> A"):
        resolve_symbols({"A": "ref::$B", "B": "ref::$A"}, {})


def test_unrecognized_double_colon_is_literal():
    from librelane.config.preprocessor import parse_directive

    assert parse_directive("pkg::type") is None
