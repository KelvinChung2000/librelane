from typing import Optional, Union

from librelane.common import GenericDict
from librelane.config import Variable


def test_optional_and_pep604_produce_equivalent_variables():
    """Optional[int] and int | None must compile values identically."""
    old = Variable("OLD", Optional[int], "legacy spelling", default=None)
    new = Variable("NEW", int | None, "pep604 spelling", default=None)

    assert old.some == new.some, "some_of disagrees across union spellings"
    assert old.optional == new.optional, "optionality disagrees"

    for value in (5, None, "7"):
        _, old_value = old.compile(
            GenericDict({"OLD": value}), [], permissive_typing=True
        )
        _, new_value = new.compile(
            GenericDict({"NEW": value}), [], permissive_typing=True
        )
        assert old_value == new_value, (
            f"compile disagrees across union spellings for {value!r}"
        )


def test_multi_arg_union_equivalent():
    old = Variable("OLD", Union[int, str], "legacy spelling")
    new = Variable("NEW", int | str, "pep604 spelling")

    assert old.some == new.some
    for value in (5, "x"):
        _, old_value = old.compile(GenericDict({"OLD": value}), [])
        _, new_value = new.compile(GenericDict({"NEW": value}), [])
        assert old_value == new_value
