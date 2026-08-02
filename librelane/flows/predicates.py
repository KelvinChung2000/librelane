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
The predicate grammar shared by a job's ``if`` and ``until``.

A predicate is a conjunction of terms joined by the literal ``and``. A term is
either a bare configuration variable name (a :class:`ConfigTerm`, evaluated at
construction against the declared configuration) or a ``metric::<name> <op>
<literal>`` comparison (a :class:`MetricTerm`, evaluated at run time against a
job's observed metrics). This module owns the grammar and its evaluation;
``spec.py`` and ``job.py`` consume the parsed terms and must not grow a second
implementation of the grammar.

This module does not import :mod:`librelane.flows.spec`, because ``spec.py``
imports this module to validate ``if`` and ``until`` at load time. A cycle
between the two would make neither importable.
"""

import operator
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Union

from librelane.common.errors import FlowError


class PredicateError(FlowError):
    """
    Raised when a predicate is malformed: a term that is neither a bare
    configuration variable name nor a well-formed ``metric::`` comparison, an
    unknown operator, or a non-numeric literal. Always raised while parsing,
    before any run directory exists, quoting the offending predicate or term.
    """


@dataclass(frozen=True)
class ConfigTerm:
    """A predicate term that is a bare configuration variable name."""

    name: str


@dataclass(frozen=True)
class MetricTerm:
    """
    A predicate term comparing a metric to a literal.

    Parameters
    ----------
    metric : str
        The metric name, with the ``metric::`` prefix already stripped once
        from the front. May itself contain ``:`` characters, as a
        corner-qualified metric name does.
    op : str
        One of the six comparison operators in ``_OPERATORS``.
    literal : int | Decimal
        The right-hand side, parsed from the term's literal token. An integer
        literal parses to ``int``; a literal with a fractional part parses to
        ``Decimal``.
    """

    metric: str
    op: str
    literal: int | Decimal


#: A predicate term: a configuration variable name evaluated at construction,
#: or a metric comparison evaluated at run time.
Term = Union[ConfigTerm, MetricTerm]

#: The comparison operators a metric term may use, textual rather than
#: symbolic-only so that a message can quote one directly.
_OPERATORS: tuple[str, ...] = ("==", "!=", "<", "<=", ">", ">=")

_COMPARE: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

_METRIC_PREFIX = "metric::"

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

#: An optionally signed integer literal, with no fractional part.
_INTEGER_LITERAL = re.compile(r"[+-]?\d+\Z")

#: An optionally signed decimal literal, with a mandatory fractional part so
#: that an integer literal is never ambiguous between the two patterns.
_DECIMAL_LITERAL = re.compile(r"[+-]?\d+\.\d+\Z")

#: Appended to every malformed-predicate message, so that a message about one
#: bad term still states the whole legal shape rather than only what is wrong
#: with it.
_GRAMMAR = (
    "A predicate is a conjunction of one or more terms joined by the "
    "literal 'and'. A term is either a bare configuration variable name, or "
    f"'metric::<name> <op> <literal>' with <op> one of {list(_OPERATORS)} "
    "and <literal> an optionally signed integer or decimal number."
)


def parse_predicate(text: str) -> tuple[Term, ...]:
    """
    Parses a predicate (an ``if`` or ``until`` string) into its terms.

    The conjunction splitter works at the token level, not by splitting on
    the substring ``" and "``: ``text.split()`` is first split into segments
    at tokens equal to ``and``, and only then is each segment (which may
    itself be a three-token metric term) parsed as one term. This is the
    only implementation of the grammar; ``until`` and ``select`` reuse it
    rather than growing their own.

    Parameters
    ----------
    text : str
        The raw ``if`` or ``until`` string.

    Returns
    -------
    The conjoined terms, in order.

    Raises
    ------
    PredicateError
        If ``text`` is not a well-formed conjunction of terms.
    """
    segments: list[list[str]] = [[]]
    for token in text.split():
        if token == "and":
            segments.append([])
        else:
            segments[-1].append(token)
    if len(segments) == 1 and not segments[0]:
        raise PredicateError(f"Predicate '{text}' is empty. {_GRAMMAR}")
    return tuple(_parse_term(text, segment) for segment in segments)


def _parse_term(predicate: str, segment: list[str]) -> Term:
    if not segment:
        raise PredicateError(
            f"Predicate '{predicate}' has an empty term next to 'and'. {_GRAMMAR}"
        )
    if len(segment) == 1:
        name = segment[0]
        if name.startswith(_METRIC_PREFIX):
            return _parse_metric_term(predicate, segment)
        if _IDENTIFIER.match(name) is None:
            raise PredicateError(
                f"Predicate '{predicate}' has term '{name}', which is not a "
                f"legal configuration variable name. {_GRAMMAR}"
            )
        return ConfigTerm(name)
    if segment[0].startswith(_METRIC_PREFIX):
        return _parse_metric_term(predicate, segment)
    raise PredicateError(
        f"Predicate '{predicate}' has term '{' '.join(segment)}', which is "
        f"neither a bare configuration variable name (one token) nor a "
        f"'metric::' term (three tokens starting with 'metric::'). "
        f"{_GRAMMAR}"
    )


def _parse_metric_term(predicate: str, segment: list[str]) -> MetricTerm:
    if len(segment) != 3:
        raise PredicateError(
            f"Predicate '{predicate}' has metric term "
            f"'{' '.join(segment)}', which is {len(segment)} "
            f"whitespace-separated tokens rather than the three a metric "
            f"term requires. {_GRAMMAR}"
        )
    name = segment[0][len(_METRIC_PREFIX) :]
    if not name:
        raise PredicateError(
            f"Predicate '{predicate}' has metric term "
            f"'{' '.join(segment)}' with an empty metric name after "
            f"'{_METRIC_PREFIX}'. {_GRAMMAR}"
        )
    op = segment[1]
    if op not in _OPERATORS:
        raise PredicateError(
            f"Predicate '{predicate}' has metric term "
            f"'{' '.join(segment)}' with operator '{op}', which is not one "
            f"of {list(_OPERATORS)}. {_GRAMMAR}"
        )
    literal = _parse_literal(predicate, segment[2])
    return MetricTerm(metric=name, op=op, literal=literal)


def _parse_literal(predicate: str, text: str) -> int | Decimal:
    if _INTEGER_LITERAL.match(text):
        return int(text)
    if _DECIMAL_LITERAL.match(text):
        return Decimal(text)
    raise PredicateError(
        f"Predicate '{predicate}' has literal '{text}', which is not an "
        f"optionally signed integer or decimal number. {_GRAMMAR}"
    )


def evaluate_metric_term(
    term: MetricTerm, metrics: Mapping[str, Any], owner: str
) -> bool:
    """
    Evaluates a runtime metric term against a state's observed metrics.

    Parameters
    ----------
    term : MetricTerm
        The term to evaluate.
    metrics : Mapping[str, Any]
        The metrics of the state the term is evaluated against.
    owner : str
        The caller's identity, named in every error this raises: the job for
        an ``if`` term, the gate for an ``until`` term.

    Returns
    -------
    Whether the term holds.

    Raises
    ------
    FlowError
        If ``term.metric`` is absent from ``metrics`` -- absence is not
        false, it is a missing measurement -- or if the observed value is
        not one of ``int``, ``float`` or ``Decimal``. A numeric-looking
        string is not parsed and is refused exactly as any other non-numeric
        value is, because a predicate that silently compared a string to a
        number would be false for a reason no message states. A ``bool`` is
        refused the same way despite being an ``int`` subclass -- a Boolean
        is never a quantity, the same rule this branch's capacity resolvers
        already apply to a pool's capacity -- rather than reaching
        ``Decimal(str(value))`` below and raising a raw, unnamed
        ``decimal.InvalidOperation``.
    """
    if term.metric not in metrics:
        raise FlowError(
            f"{owner} evaluates 'metric::{term.metric} {term.op} "
            f"{term.literal}', but '{term.metric}' is absent from the "
            f"metrics present. Absence is not false; false is a measurement "
            f"and absence is a missing measurement. Metrics present: "
            f"{sorted(metrics)}."
        )
    value = metrics[term.metric]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise FlowError(
            f"{owner} evaluates 'metric::{term.metric} {term.op} "
            f"{term.literal}' against observed value {value!r} of type "
            f"'{type(value).__name__}', which is not a number. Comparisons "
            f"are numeric, for '==' and '!=' as much as for the orderings, "
            f"and a string is never parsed as one even if it looks numeric."
        )
    observed = Decimal(str(value))
    literal = (
        term.literal if isinstance(term.literal, Decimal) else Decimal(term.literal)
    )
    return _COMPARE[term.op](observed, literal)


def config_terms(terms: Iterable[Term]) -> tuple[str, ...]:
    """
    Returns
    -------
    The configuration variable names of the :class:`ConfigTerm` entries in
    ``terms``, in order, with any :class:`MetricTerm` entries dropped.
    """
    return tuple(term.name for term in terms if isinstance(term, ConfigTerm))


def metric_terms(terms: Iterable[Term]) -> tuple[MetricTerm, ...]:
    """
    Returns
    -------
    The :class:`MetricTerm` entries of ``terms``, in order, with any
    :class:`ConfigTerm` entries dropped.
    """
    return tuple(term for term in terms if isinstance(term, MetricTerm))
