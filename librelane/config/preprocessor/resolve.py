# Copyright 2026 LibreLane Contributors
import glob
import os
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from collections.abc import Mapping
from typing import Any, TypeAlias, cast

from lark import Lark, Token, Transformer
from lark.exceptions import VisitError


# The parsed shape of one directive. Declared here, beside the parser that is
# the only thing that builds these and the evaluator that is the only thing
# that reads them, rather than in a module of its own -- nothing outside this
# file has ever named one.
@dataclass(frozen=True)
class Number:
    value: Decimal


@dataclass(frozen=True)
class Symbol:
    name: str


@dataclass(frozen=True)
class Binary:
    operator: str
    left: "Expression"
    right: "Expression"


Expression: TypeAlias = Number | Symbol | Binary


@dataclass(frozen=True)
class ExprDirective:
    expression: Expression


@dataclass(frozen=True)
class RefDirective:
    symbol: str
    suffix: str = ""
    glob: bool = False


Directive: TypeAlias = ExprDirective | RefDirective


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


# Resolving a whole mapping, as against one directive. This drives the two
# functions above -- it is the only caller of either -- walking every scalar in
# dependency order so a directive may name a key written later in the file, and
# naming the cycle when one refers back to itself. It lived in a module of its
# own whose every import came from this one.


class SymbolCycleError(ValueError):
    pass


def resolve_symbols(
    mapping: Mapping[str, Any],
    seeds: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve every scalar through a dependency graph, including forward refs."""

    nodes: dict[str, Any] = {}
    children: dict[str, list[tuple[str | int, str]]] = {}

    def collect(value: Any, path: str) -> None:
        nodes[path] = value
        if isinstance(value, Mapping):
            child_paths = []
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                child_paths.append((key, child))
                collect(item, child)
            children[path] = child_paths
        elif isinstance(value, list):
            child_paths = []
            for index, item in enumerate(value):
                child = f"{path}[{index}]"
                child_paths.append((index, child))
                collect(item, child)
            children[path] = child_paths

    for key, value in mapping.items():
        collect(value, key)

    resolved: dict[str, Any] = {
        key: value for key, value in seeds.items() if key not in nodes
    }
    visiting: list[str] = []

    def resolve(path: str) -> Any:
        if path in resolved:
            return resolved[path]
        if path not in nodes:
            raise KeyError(path)
        if path in visiting:
            start = visiting.index(path)
            cycle = visiting[start:] + [path]
            raise SymbolCycleError(
                "Configuration reference cycle: " + " -> ".join(cycle)
            )

        visiting.append(path)
        value = nodes[path]
        if isinstance(value, Mapping):
            final: Any = {key: resolve(child) for key, child in children[path]}
        elif isinstance(value, list):
            final = [resolve(child) for _, child in children[path]]
        elif isinstance(value, str) and (directive := parse_directive(value)):
            final = resolve_directive(directive, resolve)
        else:
            final = value
        visiting.pop()
        resolved[path] = final
        return final

    return {key: resolve(key) for key in mapping}
