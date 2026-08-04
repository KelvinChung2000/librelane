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
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from collections.abc import Mapping

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

#: The keys that name the process rather than configure the design: they are
#: seeded by the loader, exposed to ``expr::``/``dir::`` resolution and emitted
#: by every PDK's ``config.tcl``. Nothing declares them as configuration
#: variables, so every pass that reports on keys it does not recognise has to
#: pass over these -- which is why this is derived from :data:`Keys` and read
#: from here rather than restated as a literal set at each of those passes.
SPECIAL_KEYS: frozenset[str] = frozenset(vars(Keys).values())

PROCESS_INFO_ALLOWLIST = [
    Keys.pdk,
    Keys.scl,
    Keys.pad,
    f"{Keys.scl}_OPT",
]


Scalar = str | int | Decimal | float | bool | None
Valid = Scalar | dict | list


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
