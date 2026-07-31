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
import re
import os
import glob
import fnmatch
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Union, cast
from collections.abc import Mapping, Sequence

from lark import Lark, Token, Transformer
from lark.exceptions import UnexpectedCharacters, UnexpectedToken, VisitError

from librelane.common import is_string_like

Keys = SimpleNamespace(
    pdk_root="PDK_ROOT",
    pdk="PDK",
    pdkpath="PDKPATH",
    scl="STD_CELL_LIBRARY",
    pad="PAD_CELL_LIBRARY",
    design_dir="DESIGN_DIR",
)

PROCESS_INFO_ALLOWLIST = [
    Keys.pdk,
    Keys.scl,
    Keys.pad,
    f"{Keys.scl}_OPT",
]


Scalar = Union[str, int, Decimal, float, bool, None]
Valid = Union[Scalar, dict, list]


_EXPRESSION_GRAMMAR = r"""
    ?start: sum
    ?sum: sum "+" product       -> add
        | sum "-" product       -> subtract
        | product
    ?product: product "*" power -> multiply
            | product "/" power -> divide
            | power
    ?power: atom "**" power     -> power
          | atom
    ?atom: NUMBER               -> number
         | VARIABLE             -> variable
         | "(" sum ")"

    NUMBER: /-?\d+\.?\d*/
    VARIABLE: /\$[A-Za-z_][A-Za-z0-9_.\[\]]*/
    %ignore /\s+/
"""

_expression_parser = Lark(_EXPRESSION_GRAMMAR, parser="lalr")


class _ExpressionEvaluator(Transformer):
    def __init__(self, symbols: Mapping[str, Any]) -> None:
        super().__init__()
        self.symbols = symbols

    def number(self, children: list[Token]) -> Decimal:
        return Decimal(children[0].value)

    def variable(self, children: list[Token]) -> Decimal:
        name = children[0].value[1:]
        try:
            value = self.symbols[name]
        except KeyError:
            raise TypeError(f"Configuration variable '{name}' not found.") from None
        if not isinstance(value, (int, float, Decimal)):
            raise TypeError(
                f"Referenced variable {name} is not of a valid numeric type: f{type(value)}"
            )
        return Decimal(value)

    def add(self, children: list[Decimal]) -> Decimal:
        return children[0] + children[1]

    def subtract(self, children: list[Decimal]) -> Decimal:
        return children[0] - children[1]

    def multiply(self, children: list[Decimal]) -> Decimal:
        return children[0] * children[1]

    def divide(self, children: list[Decimal]) -> Decimal:
        return children[0] / children[1]

    def power(self, children: list[Decimal]) -> Decimal:
        return children[0] ** children[1]


class Expr(object):
    @staticmethod
    def evaluate(expression: str, symbols: Mapping[str, Any]) -> Decimal:
        if expression.strip() == "":
            raise ValueError("expression is empty")

        balance = 0
        for character in expression:
            if character == "(":
                balance += 1
            elif character == ")":
                if balance == 0:
                    raise IndexError("list index out of range")
                balance -= 1

        parseable = expression + ")" * balance
        try:
            tree = _expression_parser.parse(parseable)
            return cast(Decimal, _ExpressionEvaluator(symbols).transform(tree))
        except VisitError as e:
            raise e.orig_exc from None
        except UnexpectedCharacters as e:
            remainder = expression[e.pos_in_stream :]
            raise SyntaxError(
                f"Unexpected token at the start of the following string '{remainder}'."
            ) from None
        except UnexpectedToken as e:
            stripped = expression.rstrip()
            if e.token.type == "$END" and stripped.endswith(("+", "-", "*", "/")):
                operator = "**" if stripped.endswith("**") else stripped[-1]
                raise SyntaxError(
                    f"not enough operands for operator '{operator}'"
                ) from None
            if e.pos_in_stream == 0 and stripped[0] in "+-*/":
                operator = "**" if stripped.startswith("**") else stripped[0]
                raise SyntaxError(
                    f"not enough operands for operator '{operator}'"
                ) from None
            if e.token.type in {"NUMBER", "VARIABLE", "LPAR"}:
                raise ValueError("expression reduces to multiple values") from None
            remainder = expression[e.pos_in_stream :]
            raise SyntaxError(
                f"Unexpected token at the start of the following string '{remainder}'."
            ) from None


ref_rx = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_\.\[\]]*)")


def process_string(
    value: str,
    symbols: Mapping[str, Any],
) -> Valid:
    global ref_rx
    EXPR_PREFIX = "expr::"
    REF_PREFIX = "ref::"
    REFG_PREFIX = "refg::"

    DIR_PREFIX = "dir::"
    PDK_DIR_PREFIX = "pdk_dir::"

    mutable: str = value

    if value.startswith(DIR_PREFIX):
        mutable = value.replace(DIR_PREFIX, f"refg::${Keys.design_dir}/")
    elif value.startswith(PDK_DIR_PREFIX):
        mutable = value.replace(PDK_DIR_PREFIX, f"refg::${Keys.pdkpath}/")

    if mutable.startswith(EXPR_PREFIX):
        try:
            return Expr.evaluate(value[len(EXPR_PREFIX) :], symbols)
        except SyntaxError as e:
            raise SyntaxError(f"Invalid expression '{value}': {e}") from None
    elif mutable.startswith(REF_PREFIX) or mutable.startswith(REFG_PREFIX):
        reference = mutable[mutable.index("::") + 2 :]
        match = ref_rx.match(reference)
        if match is None:
            raise SyntaxError(f"Invalid reference string '{reference}'") from None

        reference_variable = match[1]
        if reference_variable not in symbols:
            raise KeyError(
                f"Referenced variable '{reference_variable}' not found"
            ) from None

        target = symbols[reference_variable]
        if target is None:
            return None

        if not is_string_like(target):
            if type(target) in [int, float, Decimal]:
                raise TypeError(
                    f"Referenced variable {reference_variable} is a number and not a string: use expr::{match[0]} if you want to reference this number."
                ) from None
            else:
                raise TypeError(
                    f"Referenced variable {reference_variable} is not a valid string: {type(target)}."
                ) from None

        target = str(target)
        concatenated = reference.replace(match[0], target)

        # Glob only if Refg
        if not mutable.startswith(REFG_PREFIX):
            return concatenated

        ## If we're refg, all returns beyond this point must be of type
        ## List[str]
        final_abspath = os.path.abspath(concatenated)

        # Glob only if it doesn't already resolve to a valid file
        if os.path.exists(final_abspath):
            return [final_abspath]

        files = sorted(glob.glob(final_abspath))
        files_escaped = [file.replace("$", r"\$") for file in files]
        files_escaped.sort()

        if len(files_escaped) == 0:
            files_escaped = [concatenated]

        return files_escaped
    else:
        return mutable


PDK_PREFIX = "pdk::"
SCL_PREFIX = "scl::"


def process_list_recursive(
    input: Sequence[Any],
    ref: list[Any],
    symbols: dict[str, Any],
    *,
    key_path: str = "",
):
    for i, value in enumerate(input):
        current_key_path = f"{key_path}[{i}]"
        processed: Any = None
        if isinstance(value, Mapping):
            processed = {}
            process_dict_recursive(
                value,
                processed,
                symbols,
                key_path=current_key_path,
            )
        elif isinstance(value, Sequence) and not is_string_like(value):
            processed = []
            process_list_recursive(
                value,
                processed,
                symbols,
                key_path=current_key_path,
            )
        elif is_string_like(value):
            processed = process_string(str(value), symbols)
        else:
            processed = value

        if processed is not None:
            ref.append(processed)
            symbols[current_key_path] = processed


def process_dict_recursive(
    input: Mapping[str, Any],
    ref: dict[str, Any],
    symbols: dict[str, Any],
    *,
    key_path: str = "",
):
    for key, value in input.items():
        current_key_path = key
        if key_path != "":
            current_key_path = f"{key_path}.{key}"
        processed: Any = None
        if isinstance(value, Mapping):
            if key.startswith(PDK_PREFIX):
                pdk_match = key[len(PDK_PREFIX) :]
                if fnmatch.fnmatch(ref[Keys.pdk], pdk_match):
                    process_dict_recursive(
                        value,
                        ref,
                        symbols,
                        key_path=key_path,
                    )
            elif key.startswith(SCL_PREFIX):
                scl_match = key[len(SCL_PREFIX) :]
                if ref[Keys.scl] is not None and fnmatch.fnmatch(
                    ref[Keys.scl], scl_match
                ):
                    process_dict_recursive(
                        value,
                        ref,
                        symbols,
                        key_path=key_path,
                    )
            else:
                processed = {}
                process_dict_recursive(
                    value,
                    processed,
                    symbols,
                    key_path=current_key_path,
                )

        elif isinstance(value, Sequence) and not is_string_like(value):
            processed = []
            process_list_recursive(
                value,
                processed,
                symbols,
                key_path=current_key_path,
            )
        elif is_string_like(value):
            processed = process_string(str(value), symbols)
        else:
            processed = value

        if not key.startswith(PDK_PREFIX) and not key.startswith(SCL_PREFIX):
            ref[key] = processed
            symbols[current_key_path] = processed


def process_config_dict(
    config_in: Mapping[str, Any],
    exposed_variables: dict[str, Any],
) -> dict[str, Any]:
    state = dict(exposed_variables)
    symbols = dict(exposed_variables)
    process_dict_recursive(config_in, state, symbols)
    return state


def extract_process_vars(config_in: dict[str, str]) -> dict[str, str]:
    return {
        key: config_in[key]
        for key in PROCESS_INFO_ALLOWLIST
        if config_in.get(key) is not None and config_in.get(key) != ""
    }


def preprocess_dict(
    config_dict: Mapping[str, Any],
    design_dir: str,
    only_extract_process_info: bool = False,
    pdk: str | None = None,
    pdkpath: str | None = None,
    scl: str | None = None,
    pad: str | None = None,
) -> dict[str, Any]:
    if None in (pdk, pdkpath, scl):
        if only_extract_process_info:
            pdkpath = ""
            scl = ""
            pdk = ""
        else:
            raise TypeError(
                "pdk, pdkpath and scl all need to be non-None unless only_extract_process_info is passed"
            )

    base_vars = {
        Keys.pdk: pdk,
        Keys.pdkpath: pdkpath,
        Keys.scl: scl,
        Keys.pad: pad,
        Keys.design_dir: design_dir,
    }

    preprocessed = process_config_dict(
        config_dict,
        base_vars,
    )
    if only_extract_process_info:
        preprocessed = extract_process_vars(preprocessed)

    return preprocessed
