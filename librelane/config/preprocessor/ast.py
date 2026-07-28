# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias


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
