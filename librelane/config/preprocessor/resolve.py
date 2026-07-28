# Copyright 2026 LibreLane Contributors
import glob
import os
from decimal import Decimal
from importlib.resources import files
from typing import Any, cast

from lark import Lark, Token, Transformer
from lark.exceptions import VisitError

from .ast import (
    Binary,
    Directive,
    ExprDirective,
    Expression,
    Number,
    RefDirective,
    Symbol,
)


class GlobMatch(list[str]):
    """A glob result whose original unexpanded path remains available."""

    def __init__(self, values: list[str], literal: str) -> None:
        super().__init__(values)
        self.literal = literal


class _ASTBuilder(Transformer):
    def number(self, children: list[Token]) -> Number:
        return Number(Decimal(children[0].value))

    def variable(self, children: list[Token]) -> Symbol:
        return Symbol(children[0].value[1:])

    def add(self, children: list[Expression]) -> Binary:
        return Binary("+", children[0], children[1])

    def subtract(self, children: list[Expression]) -> Binary:
        return Binary("-", children[0], children[1])

    def multiply(self, children: list[Expression]) -> Binary:
        return Binary("*", children[0], children[1])

    def divide(self, children: list[Expression]) -> Binary:
        return Binary("/", children[0], children[1])

    def power(self, children: list[Expression]) -> Binary:
        return Binary("**", children[0], children[1])

    def expr_d(self, children: list[Expression]) -> ExprDirective:
        return ExprDirective(children[0])

    def ref_d(self, children: list[Token]) -> RefDirective:
        return RefDirective(
            children[0].value[1:],
            children[1].value if len(children) > 1 else "",
        )

    def refg_d(self, children: list[Token]) -> RefDirective:
        return RefDirective(
            children[0].value[1:],
            children[1].value if len(children) > 1 else "",
            glob=True,
        )

    def dir_d(self, children: list[Token]) -> RefDirective:
        return RefDirective("DESIGN_DIR", f"/{children[0].value}", glob=True)

    def pdk_dir_d(self, children: list[Token]) -> RefDirective:
        return RefDirective("PDKPATH", f"/{children[0].value}", glob=True)


_parser = Lark.open(
    str(files(__package__).joinpath("grammar.lark")),
    parser="lalr",
    transformer=_ASTBuilder(),
)
_PREFIXES = ("expr::", "ref::", "refg::", "dir::", "pdk_dir::")


def parse_directive(value: str) -> Directive | None:
    if not value.startswith(_PREFIXES):
        return None
    try:
        return cast(Directive, _parser.parse(value))
    except VisitError as error:
        raise error.orig_exc from None


def _evaluate(expression: Expression, resolve_symbol) -> Decimal:
    if isinstance(expression, Number):
        return expression.value
    if isinstance(expression, Symbol):
        value = resolve_symbol(expression.name)
        if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
            raise TypeError(
                f"Referenced variable {expression.name} is not of a valid numeric type: {type(value)}"
            )
        return Decimal(value)
    left = _evaluate(expression.left, resolve_symbol)
    right = _evaluate(expression.right, resolve_symbol)
    if expression.operator == "+":
        return left + right
    if expression.operator == "-":
        return left - right
    if expression.operator == "*":
        return left * right
    if expression.operator == "/":
        return left / right
    return left**right


def resolve_directive(directive: Directive, resolve_symbol) -> Any:
    if isinstance(directive, ExprDirective):
        return _evaluate(directive.expression, resolve_symbol)

    try:
        target = resolve_symbol(directive.symbol)
    except KeyError:
        raise KeyError(f"Referenced variable '{directive.symbol}' not found") from None
    if target is None:
        return None
    if not isinstance(target, (str, os.PathLike)):
        if isinstance(target, (int, float, Decimal)):
            raise TypeError(
                f"Referenced variable {directive.symbol} is a number and not a string: "
                f"use expr::${directive.symbol} if you want to reference this number."
            )
        raise TypeError(
            f"Referenced variable {directive.symbol} is not a valid string: {type(target)}."
        )

    literal = f"{target}{directive.suffix}"
    if not directive.glob:
        return literal

    absolute = os.path.abspath(literal)
    if os.path.exists(absolute):
        matches = [absolute]
    else:
        matches = sorted(path.replace("$", r"\$") for path in glob.glob(absolute))
    return GlobMatch(matches, literal)
