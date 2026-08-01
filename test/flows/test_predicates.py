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
from decimal import Decimal

import pytest

from librelane.common.errors import FlowError
from librelane.flows.predicates import (
    ConfigTerm,
    MetricTerm,
    PredicateError,
    config_terms,
    evaluate_metric_term,
    metric_terms,
    parse_predicate,
)

pytestmark = pytest.mark.all


def test_a_bare_identifier_parses_to_a_config_term():
    assert parse_predicate("RUN_LINTER") == (ConfigTerm("RUN_LINTER"),)


@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">", ">="])
def test_each_operator_parses(op):
    assert parse_predicate(f"metric::x {op} 1") == (
        MetricTerm(metric="x", op=op, literal=1),
    )


def test_a_signed_integer_literal_parses_to_int():
    assert parse_predicate("metric::x == -3") == (
        MetricTerm(metric="x", op="==", literal=-3),
    )
    assert parse_predicate("metric::x == +3") == (
        MetricTerm(metric="x", op="==", literal=3),
    )


def test_a_decimal_literal_parses_to_decimal():
    term = parse_predicate("metric::x >= 0.5")[0]
    assert isinstance(term, MetricTerm)
    assert term.literal == Decimal("0.5")


def test_a_mixed_conjunction_parses_both_kinds_in_order():
    terms = parse_predicate("A and metric::x >= 0 and B")
    assert terms == (
        ConfigTerm("A"),
        MetricTerm(metric="x", op=">=", literal=0),
        ConfigTerm("B"),
    )


def test_a_metric_name_with_internal_colons_parses():
    """
    A corner-qualified metric name contains no whitespace, only ':', so it
    parses as a single token with the 'metric::' prefix stripped once from
    the front rather than split on.
    """
    terms = parse_predicate("metric::timing__setup__ws:corner:nom == 0")
    assert terms == (
        MetricTerm(metric="timing__setup__ws:corner:nom", op="==", literal=0),
    )


def test_two_tokens_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("metric::x >=")

    assert "metric::x >=" in str(exc_info.value)


def test_four_tokens_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("metric::x >= 1 2")

    assert "metric::x >= 1 2" in str(exc_info.value)


def test_an_unknown_operator_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("metric::x => 1")

    message = str(exc_info.value)
    assert "=>" in message


def test_a_non_numeric_literal_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("metric::x == abc")

    assert "abc" in str(exc_info.value)


def test_an_empty_metric_name_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("metric:: > 1")

    message = str(exc_info.value)
    assert "empty" in message.lower()


@pytest.mark.parametrize("predicate", ["and A", "A and", "A and and B"])
def test_and_at_an_edge_is_rejected(predicate):
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate(predicate)

    assert "and" in str(exc_info.value)


def test_an_empty_predicate_is_rejected():
    with pytest.raises(PredicateError):
        parse_predicate("")


def test_a_three_token_segment_not_metric_prefixed_is_rejected():
    with pytest.raises(PredicateError) as exc_info:
        parse_predicate("A or B")

    assert "A or B" in str(exc_info.value)


@pytest.mark.parametrize(
    ("op", "literal", "value", "expected"),
    [
        ("==", 3, 3, True),
        ("==", 3, 4, False),
        ("!=", 3, 4, True),
        ("!=", 3, 3, False),
        ("<", 3, 2, True),
        ("<", 3, 3, False),
        ("<=", 3, 3, True),
        ("<=", 3, 4, False),
        (">", 3, 4, True),
        (">", 3, 3, False),
        (">=", 3, 3, True),
        (">=", 3, 2, False),
    ],
)
def test_evaluate_metric_term_for_each_operator(op, literal, value, expected):
    term = MetricTerm(metric="x", op=op, literal=literal)
    assert evaluate_metric_term(term, {"x": value}, "job 'j'") is expected


def test_evaluate_metric_term_missing_metric_names_owner_and_present_metrics():
    term = MetricTerm(metric="x", op="==", literal=0)
    with pytest.raises(FlowError) as exc_info:
        evaluate_metric_term(term, {"y": 1, "z": 2}, "job 'j'")

    message = str(exc_info.value)
    assert "job 'j'" in message
    assert "x" in message
    assert "['y', 'z']" in message


def test_evaluate_metric_term_refuses_a_string_observed_value():
    term = MetricTerm(metric="x", op="==", literal=0)
    with pytest.raises(FlowError) as exc_info:
        evaluate_metric_term(term, {"x": "0"}, "job 'j'")

    message = str(exc_info.value)
    assert "x" in message
    assert "str" in message


def test_evaluate_metric_term_compares_float_and_decimal_exactly():
    term = MetricTerm(metric="x", op="==", literal=Decimal("0.1"))
    assert evaluate_metric_term(term, {"x": 0.1}, "job 'j'") is True
    assert evaluate_metric_term(term, {"x": Decimal("0.1")}, "job 'j'") is True


def test_config_terms_extracts_only_config_term_names_in_order():
    terms = parse_predicate("A and metric::x >= 0 and B")
    assert config_terms(terms) == ("A", "B")


def test_metric_terms_extracts_only_metric_terms_in_order():
    terms = parse_predicate("A and metric::x >= 0 and metric::y < 1")
    assert metric_terms(terms) == (
        MetricTerm(metric="x", op=">=", literal=0),
        MetricTerm(metric="y", op="<", literal=1),
    )
