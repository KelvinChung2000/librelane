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
Coercion for a union whose members include a list, tuple or dictionary.

A union is the one annotation that does not say on its own whether an incoming
string is text or a document: ``CLOCK_PORT`` is ``None | str | list[str]``, so
both readings are declared. ``_shape`` used to answer "neither" and hand the
string to Pydantic, whose smart union kept it a string -- ``-c
'CLOCK_PORT=["a","b"]'`` named one clock port, called ``["a","b"]``, under
every syntax. The rules pinned here decide the member before validation runs,
and never guess: a string that enters a parse either parses or raises.
"""

import textwrap
from decimal import Decimal
from typing import Annotated, Optional, Union

import pytest

from librelane.common import Path
from librelane.config.loading.sources import CoercionSyntax
from librelane.config.types import CoercionError, _shape

pytestmark = pytest.mark.all


#: ``CLOCK_PORT``/``CLOCK_NET``'s annotation, and the shape this whole
#: mechanism exists for: a scalar member and a product member together.
WITH_STR = Union[None, str, list[str]]
#: A union with a scalar member that is not ``str``. Text is not a member, so
#: Tcl -- where every value is a word list -- reads it as the product.
WITHOUT_STR = Union[None, int, list[str]]
#: A union with no scalar member at all. There is nothing for an unparsable
#: string to be.
ONLY_PRODUCTS = Union[None, list[str], dict[str, str]]


# --- JSON syntax (the command line) -----------------------------------------


def test_a_json_array_becomes_the_list_member():
    """The repro. Pydantic's smart union would keep the string."""
    assert _shape('["a","b"]', WITH_STR, CoercionSyntax.JSON) == ["a", "b"]


def test_a_json_array_becomes_the_list_member_when_padded():
    """The prefix is looked for on the stripped text, as a shell may pad it."""
    assert _shape('  ["a"]  ', WITH_STR, CoercionSyntax.JSON) == ["a"]


def test_text_without_a_product_prefix_is_the_scalar_member():
    assert _shape("clk", WITH_STR, CoercionSyntax.JSON) == "clk"


def test_text_that_looks_like_neither_is_still_the_scalar_member():
    """A clock port with a space in it is a bad name, not a Tcl list."""
    assert _shape("clk a", WITH_STR, CoercionSyntax.JSON) == "clk a"


def test_broken_json_after_a_product_prefix_never_falls_back_to_the_scalar():
    """
    The '[' committed the value to being an array. Reading the wreckage as a
    string is the fallback this design exists to remove: it would name a clock
    port ``["a"``.
    """
    with pytest.raises(CoercionError) as raised:
        _shape('["a"', WITH_STR, CoercionSyntax.JSON)

    assert "JSON" in str(raised.value)
    assert '["a"' in str(raised.value)


def test_a_json_object_no_member_takes_is_an_error():
    """Every coercion error quotes the text, not only the grammar."""
    with pytest.raises(CoercionError) as raised:
        _shape('{"a": "b"}', WITH_STR, CoercionSyntax.JSON)

    assert "no member" in str(raised.value)
    assert '{"a": "b"}' in str(raised.value)


def test_a_json_object_chooses_the_dictionary_member_over_the_list_member():
    """Two product members are told apart by the document's own shape."""
    assert _shape('{"a": "b"}', ONLY_PRODUCTS, CoercionSyntax.JSON) == {"a": "b"}


def test_a_json_array_chooses_the_list_member_over_the_dictionary_member():
    assert _shape('["a"]', ONLY_PRODUCTS, CoercionSyntax.JSON) == ["a"]


def test_two_members_of_the_same_shape_are_ambiguous_rather_than_guessed():
    with pytest.raises(CoercionError) as raised:
        _shape("[1, 2]", Union[list[int], tuple[int, int]], CoercionSyntax.JSON)

    assert "cannot be told" in str(raised.value)
    assert "[1, 2]" in str(raised.value)


def test_a_union_with_no_scalar_member_refuses_a_non_product_string():
    with pytest.raises(CoercionError) as raised:
        _shape("a b", ONLY_PRODUCTS, CoercionSyntax.JSON)

    assert "JSON" in str(raised.value)
    assert "a b" in str(raised.value)


def test_a_non_str_scalar_member_still_takes_the_text_as_written():
    """
    A plain ``int`` variable takes ``-c N=4`` as written, so a union that
    offers ``int`` may not be stricter than ``int`` alone.
    """
    assert _shape("4", WITHOUT_STR, CoercionSyntax.JSON) == "4"


def test_elements_of_a_parsed_document_are_not_parsed_again():
    """A JSON document is read whole, so a string inside one stays a string."""
    assert _shape('["a b", "c"]', WITH_STR, CoercionSyntax.JSON) == ["a b", "c"]


# --- Tcl syntax -------------------------------------------------------------


def test_a_tcl_string_stays_a_string_when_the_union_offers_one():
    """
    Historic behaviour for a CLOCK_PORT-shaped union, and the reason a Tcl
    value may not simply be split: every Tcl value is a word list, so a
    one-word list and the word itself are the same text.
    """
    assert _shape("a b", WITH_STR, CoercionSyntax.TCL) == "a b"


def test_a_tcl_string_that_looks_like_json_is_still_a_string():
    """Tcl has no JSON. The source decides the grammar, not the text."""
    assert _shape('["a","b"]', WITH_STR, CoercionSyntax.TCL) == '["a","b"]'


def test_a_tcl_string_splits_when_the_union_offers_no_string_member():
    assert _shape("a b", WITHOUT_STR, CoercionSyntax.TCL) == ["a", "b"]


def test_a_tcl_string_is_ambiguous_between_two_product_members():
    with pytest.raises(CoercionError, match="cannot be told"):
        _shape("a b", ONLY_PRODUCTS, CoercionSyntax.TCL)


def test_an_annotated_string_member_is_still_a_string_member():
    """
    ``Annotated[str, ...]`` is a string to every source, so it must claim Tcl
    text exactly as a bare ``str`` does. The alias has to be unwrapped to see
    it: ``librelane.common.Path`` is an ``Annotated`` alias too, which is why
    the test is worth having.
    """
    annotated = Union[None, Annotated[str, "meta"], list[str]]

    assert _shape("a b", annotated, CoercionSyntax.TCL) == "a b"
    assert _shape("a b", WITH_STR, CoercionSyntax.TCL) == "a b"


def test_a_path_member_does_not_claim_tcl_text_the_way_a_string_does():
    """``Path`` is an alias for ``pathlib.Path``, not for ``str``."""
    assert _shape("a b", Union[None, Path, list[Path]], CoercionSyntax.TCL) == [
        "a",
        "b",
    ]


# --- the two syntaxes disagree about non-string scalars, on purpose ---------


def test_a_non_string_scalar_claims_command_line_text_but_not_tcl_text():
    """
    The grammars are the reason. A command-line value with no leading bracket
    is unambiguously not a document, so ``int`` may take it as written -- a
    union offering ``int`` may not be stricter than ``int`` alone. Every Tcl
    value is a word list, so ``4`` and the one-word list ``4`` are the same
    text and only a declared ``str`` can claim it.
    """
    assert _shape("4", WITHOUT_STR, CoercionSyntax.JSON) == "4"
    assert _shape("4", WITHOUT_STR, CoercionSyntax.TCL) == ["4"]


# --- typed sources ----------------------------------------------------------


def test_a_typed_source_carries_a_list_as_a_list():
    assert _shape(["a", "b"], WITH_STR, CoercionSyntax.TYPED) == ["a", "b"]


def test_a_typed_source_carries_a_string_as_a_string():
    assert _shape("clk", WITH_STR, CoercionSyntax.TYPED) == "clk"


def test_a_typed_source_does_not_parse_a_string_that_looks_like_json():
    """These grammars carry a list as a list, so a string was meant as one."""
    assert _shape('["a","b"]', WITH_STR, CoercionSyntax.TYPED) == '["a","b"]'


def test_a_typed_list_is_shaped_by_the_member_it_matches():
    """
    A union may not skip the coercion the same product type gets alone: the
    legacy exact float-to-Decimal conversion is inside the list member.
    """
    shaped = _shape([1.5, 2], Union[None, str, list[Decimal]], CoercionSyntax.TYPED)

    assert shaped == [Decimal("1.5"), Decimal("2")]
    assert all(isinstance(item, Decimal) for item in shaped)


def test_a_typed_value_no_product_member_matches_is_left_for_pydantic():
    """Not a parse, so there is nothing here that has to commit to a member."""
    assert _shape(5, WITH_STR, CoercionSyntax.TYPED) == 5


def test_a_typed_list_matching_two_members_is_left_for_pydantic():
    """
    Ambiguity is an error only where a string had to be committed to one
    reading. A real list is already the shape it was written as.
    """
    value = [1, 2]
    assert (
        _shape(value, Union[list[int], tuple[int, int]], CoercionSyntax.TYPED) is value
    )


def test_a_typed_source_refuses_a_string_no_member_can_hold():
    with pytest.raises(CoercionError) as raised:
        _shape("a b", ONLY_PRODUCTS, CoercionSyntax.TYPED)

    assert "a b" in str(raised.value)


# --- unions with no product member are untouched ----------------------------


@pytest.mark.parametrize(
    "syntax",
    [CoercionSyntax.TCL, CoercionSyntax.JSON, CoercionSyntax.TYPED],
)
@pytest.mark.parametrize("value", ["1", "a b", '["a"]'])
def test_a_union_of_scalars_is_left_for_pydantic(value, syntax):
    """
    ``KLAYOUT_*_OPTIONS``' ``int | bool | str`` has nothing to parse into, so
    member order stays the whole resolution rule for it (issue 993).
    """
    assert _shape(value, Union[int, bool, str], syntax) == value


@pytest.mark.parametrize(
    "syntax",
    [CoercionSyntax.TCL, CoercionSyntax.JSON, CoercionSyntax.TYPED],
)
def test_an_optional_of_one_member_is_unchanged(syntax):
    """``None | str`` is not a choice between members; the None is dropped."""
    assert _shape("a b", Optional[str], syntax) == "a b"


# --- nested unions ----------------------------------------------------------


def test_a_union_nested_in_a_dictionary_value_is_coerced_too():
    """``TOOLS`` is ``dict[str, str | list[str]]``: the choice is per entry."""
    shaped = _shape(
        '{"lvs": "netgen", "synthesis": ["yosys", "yosys_vhdl"]}',
        Optional[dict[str, str | list[str]]],
        CoercionSyntax.JSON,
    )

    assert shaped == {"lvs": "netgen", "synthesis": ["yosys", "yosys_vhdl"]}


def test_a_string_inside_a_json_document_is_not_parsed_as_a_nested_document():
    """
    The outer document was read whole, so ``["a"]`` written *inside* it is the
    three characters a JSON string holds, not another array.
    """
    shaped = _shape(
        '{"lvs": "[\\"a\\"]"}',
        Optional[dict[str, str | list[str]]],
        CoercionSyntax.JSON,
    )

    assert shaped == {"lvs": '["a"]'}


def test_a_union_nested_in_a_tcl_dictionary_value_keeps_its_string_member():
    shaped = _shape(
        "lvs netgen",
        Optional[dict[str, str | list[str]]],
        CoercionSyntax.TCL,
    )

    assert shaped == {"lvs": "netgen"}


# --- end to end, through a real load ----------------------------------------


def _variables():
    """The smallest variable list a load resolves against, plus the unions."""
    from librelane.common import Path
    from librelane.config import Variable
    from librelane.config.flow import OptionConfig

    return [
        Variable(
            "CLOCK_PORT",
            OptionConfig.model_fields["CLOCK_PORT"].annotation,
            description="the shipped annotation, not a copy of it",
            default=None,
        ),
        Variable("PDK_ROOT", str, description="x"),
        Variable("PDK", str, description="x"),
        Variable("DESIGN_DIR", Path, description="x"),
        Variable("DESIGN_NAME", str, description="x"),
        Variable("STD_CELL_LIBRARY", str, description="x", pdk=True),
        Variable("TEST_UNION", WITH_STR, description="x", default=None),
        # A PDK's 'config.tcl' is the only Tcl source left, and the PDK layer
        # keeps only the variables that declare themselves its own.
        Variable("TEST_PDK_UNION", WITH_STR, description="x", default=None, pdk=True),
        Variable(
            "TEST_RENAMED_UNION",
            WITH_STR,
            description="x",
            default=None,
            deprecated_names=["TEST_RENAMED_UNION_LEGACY"],
        ),
    ]


@pytest.fixture
def tiny_pdk(tmp_path):
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    (librelane_dir / "config.tcl").write_text(
        'set ::env(STD_CELL_LIBRARY) "tiny_scl"\n'
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text("")
    return str(root)


@pytest.fixture
def design_dir(tmp_path):
    directory = tmp_path / "design"
    directory.mkdir()
    return directory


def _resolve(tiny_pdk, sources, design_dir, **load):
    from librelane.config import Config

    resolved, _ = Config.load(
        sources,
        _variables(),
        design_dir=str(design_dir),
        pdk="tiny",
        pdk_root=tiny_pdk,
        **load,
    )
    return resolved


def _errors(tiny_pdk, sources, design_dir, **load) -> list[str]:
    from librelane.config import InvalidConfig

    with pytest.raises(InvalidConfig) as raised:
        _resolve(tiny_pdk, sources, design_dir, **load)
    return list(raised.value.errors)


def test_a_union_from_the_command_line_resolves_to_the_list(tiny_pdk, design_dir):
    """The whole issue, end to end: Pydantic used to keep the string."""
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_UNION=["a", "b"]'],
    )

    assert resolved["TEST_UNION"] == ["a", "b"]


def test_a_union_from_the_command_line_still_takes_a_bare_name(tiny_pdk, design_dir):
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=["TEST_UNION=clk"],
    )

    assert resolved["TEST_UNION"] == "clk"


def test_broken_json_for_a_union_names_the_key_and_the_grammar(tiny_pdk, design_dir):
    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_UNION=["a"'],
    )

    assert "TEST_UNION" in error
    assert "JSON" in error


def test_a_renamed_union_carries_the_command_line_syntax(tiny_pdk, design_dir):
    """A rename moves the value onto another key; the syntax moves with it."""
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_RENAMED_UNION_LEGACY=["p", "q"]'],
    )

    assert resolved["TEST_RENAMED_UNION"] == ["p", "q"]


def test_a_union_from_a_pdk_stays_a_string(tmp_path, design_dir):
    """
    A PDK ships Tcl, where every value is a word list, so the reading has to be
    decided by the annotation rather than by the text: a union with a ``str``
    member keeps the string.
    """
    root = tmp_path / "pdk_union"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    (librelane_dir / "config.tcl").write_text(
        textwrap.dedent(
            """\
            set ::env(STD_CELL_LIBRARY) "tiny_scl"
            set ::env(TEST_PDK_UNION) "a b"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text("")

    resolved = _resolve(str(root), [{"DESIGN_NAME": "x"}], design_dir)

    assert resolved["TEST_PDK_UNION"] == "a b"


def test_a_union_from_a_yaml_source_carries_a_list_as_a_list(tiny_pdk, design_dir):
    path = design_dir / "config.yaml"
    path.write_text("DESIGN_NAME: x\nTEST_UNION:\n  - a\n  - b\n")

    resolved = _resolve(tiny_pdk, [str(path)], design_dir)

    assert resolved["TEST_UNION"] == ["a", "b"]


def test_a_union_from_a_yaml_source_carries_a_string_as_a_string(tiny_pdk, design_dir):
    path = design_dir / "config.yaml"
    path.write_text("DESIGN_NAME: x\nTEST_UNION: clk\n")

    resolved = _resolve(tiny_pdk, [str(path)], design_dir)

    assert resolved["TEST_UNION"] == "clk"


@pytest.mark.parametrize(
    ("written", "expected"),
    [('["a", "b"]', ["a", "b"]), ("clk", "clk")],
    ids=["array", "name"],
)
def test_the_shipped_clock_port_resolves_both_readings(
    tiny_pdk, design_dir, written, expected
):
    """
    The variable the issue was reported against, carrying the annotation
    :class:`librelane.config.flow.OptionConfig` actually declares rather than a
    copy of it, so a change to the declaration cannot leave this passing.
    """
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=[f"CLOCK_PORT={written}"],
    )

    assert resolved["CLOCK_PORT"] == expected
