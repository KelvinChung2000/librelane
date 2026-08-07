# Copyright 2026 LibreLane Contributors
"""Union member order under permissive (Tcl) typing -- issue 993.

The five ``KLAYOUT_*_OPTIONS`` variables are ``pdk=True``, so they are
validated permissively straight out of a PDK's ``config.tcl``, where every
value is a string. The member order of their unions is therefore the entire
resolution rule for them.
"""

from decimal import Decimal
from typing import get_args

import pytest

from librelane.config import Variable
from librelane.config.loading.sources import CoercionSyntax
from librelane.config.validation import validate_mapping


def _validated(variable, raw, permissive=True, syntax=CoercionSyntax.TCL):
    values, diagnostics, _ = validate_mapping(
        {variable.name: raw},
        [variable],
        permissive=permissive,
        syntaxes={variable.name: syntax},
        on_unknown_key=None,
    )
    assert not diagnostics.rendered_errors(), diagnostics.rendered_errors()
    return values[variable.name]


def _declared_variable(step_id: str, name: str) -> Variable:
    from librelane.steps import Step

    step = Step.factory.get(step_id)
    assert step is not None, f"step '{step_id}' is not registered"
    for variable in step.config_vars:
        if variable.name == name:
            return variable
    raise AssertionError(f"'{name}' is not declared by '{step_id}'")


def _klayout_option_variables() -> list[Variable]:
    from librelane.steps import Step

    found = {}
    for step_id in Step.factory.list():
        step = Step.factory.get(step_id)
        assert step is not None
        for variable in step.config_vars:
            if variable.name.startswith("KLAYOUT_") and variable.name.endswith(
                "_OPTIONS"
            ):
                found[variable.name] = variable
    assert len(found) == 5, (
        f"expected five KLayout option variables, got {sorted(found)}"
    )
    return list(found.values())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # sky130A/B ship exactly this dictionary in libs.tech/openlane/config.tcl.
        (
            "beol 1 feol 1 floating_metal 0 seal 1 offgrid 1",
            {
                "beol": 1,
                "feol": 1,
                "floating_metal": 0,
                "seal": 1,
                "offgrid": 1,
            },
        ),
        # ihp-sg13g2 ships these two.
        (
            "no_recommended true run_mode deep",
            {"no_recommended": True, "run_mode": "deep"},
        ),
        # A count is a count, and a decimal is neither an int nor a bool.
        ("threads 8 ratio 5.5", {"threads": 8, "ratio": "5.5"}),
    ],
)
def test_klayout_options_resolve_to_the_narrowest_member(raw, expected):
    """A Tcl ``1`` is the number one, not ``True``."""
    for variable in _klayout_option_variables():
        compiled = _validated(variable, raw)
        assert compiled == expected, f"{variable.name} coerced {raw!r} wrongly"
        for key, value in expected.items():
            assert type(compiled[key]) is type(value), (
                f"{variable.name}[{key}] has type {type(compiled[key]).__name__}, "
                f"expected {type(value).__name__}"
            )


def test_klayout_option_unions_declare_int_before_bool_and_str_last():
    for variable in _klayout_option_variables():
        _, value_type = get_args(variable.some)
        members = [member.__name__ for member in get_args(value_type)]
        assert members == ["int", "bool", "str"], (
            f"{variable.name} declares its union as {members}"
        )


@pytest.mark.parametrize("permissive", [True, False])
@pytest.mark.parametrize("numeric_type", [int, Decimal])
def test_a_boolean_is_never_a_quantity(numeric_type, permissive):
    """``int(True)`` is 1, which would let ``bool`` be swallowed by ``int``."""
    variable = Variable("N", numeric_type, "a number")
    _, diagnostics, _ = validate_mapping(
        {"N": True},
        [variable],
        permissive=permissive,
        on_unknown_key=None,
    )
    errors = diagnostics.rendered_errors()
    assert errors, f"True was accepted for {numeric_type.__name__}"


def test_a_boolean_still_wins_the_union_over_int():
    """With ``int`` declared first, a real ``bool`` must still stay a ``bool``."""
    variable = _declared_variable("KLayout.DRC", "KLAYOUT_DRC_OPTIONS")
    for permissive in (True, False):
        compiled = _validated(
            variable,
            {"feol": True, "seal": 3},
            permissive=permissive,
            syntax=CoercionSyntax.TYPED,
        )
        assert compiled == {"feol": True, "seal": 3}
        assert type(compiled["feol"]) is bool
        assert type(compiled["seal"]) is int
