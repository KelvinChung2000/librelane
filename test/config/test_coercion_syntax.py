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
How a string reaching a list- or dictionary-typed variable is read.

The syntax belongs to the source that wrote the value, not to the variable: a
PDK's ``config.tcl`` holds Tcl text, a ``--config-override`` is written on a
shell command line, and a YAML, JSON or Python mapping carries a list as a
list. One flag used to answer both questions at once, so a command-line value
for any product-typed variable was split as a Tcl list and every JSON object
given to one died on ``uneven Tcl dictionary``.

A PDK is the only Tcl source left. Design configurations were readable as Tcl
too -- a ``.tcl`` design file, or any document declaring ``meta.version`` 1 --
and both are gone.
"""

import json
import textwrap

import pytest

from librelane.common import Path
from librelane.config import Variable

pytestmark = pytest.mark.all


#: The smallest variable list these loads resolve against, with one variable
#: of each shape whose coercion is in question.
_VARIABLES = [
    Variable("PDK_ROOT", str, description="x"),
    Variable("PDK", str, description="x"),
    Variable("DESIGN_DIR", Path, description="x"),
    Variable("DESIGN_NAME", str, description="x"),
    Variable("STD_CELL_LIBRARY", str, description="x", pdk=True),
    Variable("TEST_DICT", dict[str, str] | None, description="x", default=None),
    Variable("TEST_LIST", list[str] | None, description="x", default=None),
    # The PDK layer keeps only the variables that declare themselves its own,
    # so the Tcl-coercion tests below -- whose one surviving source is a PDK's
    # 'config.tcl' -- need product-typed variables it will not drop.
    Variable(
        "TEST_PDK_DICT", dict[str, str] | None, description="x", default=None, pdk=True
    ),
    Variable(
        "TEST_PDK_LIST", list[str] | None, description="x", default=None, pdk=True
    ),
    Variable("TEST_SCALAR", str | None, description="x", default=None),
    Variable("TEST_NUMBER", int | None, description="x", default=None),
    Variable(
        "TEST_RENAMED_LIST",
        list[str] | None,
        description="x",
        default=None,
        deprecated_names=["TEST_RENAMED_LIST_LEGACY"],
    ),
]


@pytest.fixture
def tiny_pdk(tmp_path):
    """
    A PDK with nothing in it but the standard cell library every load needs.

    Returns
    -------
    str
        The PDK root to pass to :meth:`librelane.config.Config.load`.
    """
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    (librelane_dir / "config.tcl").write_text(
        'set ::env(STD_CELL_LIBRARY) "tiny_scl"\n'
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text("")
    return str(root)


@pytest.fixture
def pdk_writing(tmp_path):
    """
    Builds a PDK whose ``config.tcl`` writes the given body, on top of the
    standard cell library every load needs.

    A PDK's ``config.tcl`` is the one source whose values are still Tcl text --
    it is the only configuration format any PDK ships, including the ones under
    ``libs.tech/librelane`` -- so it is what the Tcl coercion tests drive.
    """

    def build(body: str) -> str:
        root = tmp_path / "pdk_writing"
        librelane_dir = root / "tiny" / "libs.tech" / "librelane"
        (librelane_dir / "tiny_scl").mkdir(parents=True)
        (librelane_dir / "config.tcl").write_text(
            'set ::env(STD_CELL_LIBRARY) "tiny_scl"\n' + textwrap.dedent(body)
        )
        (librelane_dir / "tiny_scl" / "config.tcl").write_text("")
        return str(root)

    return build


@pytest.fixture
def design_dir(tmp_path):
    directory = tmp_path / "design"
    directory.mkdir()
    return directory


def _resolve(tiny_pdk, sources, design_dir, **load):
    from librelane.config import Config

    resolved, _ = Config.load(
        sources,
        _VARIABLES,
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


# --- the command line -------------------------------------------------------


def test_a_dictionary_from_the_command_line_is_json(tiny_pdk, design_dir):
    """The repro: every product-typed variable set with '-c' used to die here."""
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_DICT={"a": "1", "b": "2"}'],
    )

    assert resolved["TEST_DICT"] == {"a": "1", "b": "2"}


def test_a_list_from_the_command_line_is_json(tiny_pdk, design_dir):
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_LIST=["p", "q"]'],
    )

    assert resolved["TEST_LIST"] == ["p", "q"]


def test_a_tcl_list_from_the_command_line_is_not_a_second_accepted_syntax(
    tiny_pdk, design_dir
):
    """
    The command line has one syntax for a product type. A space-separated Tcl
    list used to be the only thing it took; taking both would be the fallback
    this design exists to remove.
    """
    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=["TEST_LIST=p q r"],
    )

    assert "TEST_LIST" in error
    assert "JSON" in error


def test_a_malformed_json_value_names_the_syntax_and_the_key(tiny_pdk, design_dir):
    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=["TEST_DICT={a: 1}"],
    )

    assert "TEST_DICT" in error
    assert "JSON" in error


def test_a_scalar_from_the_command_line_is_the_text_as_written(tiny_pdk, design_dir):
    """
    Which syntax applies is decided by the variable's declared type before the
    text is looked at, so a scalar is never JSON and never has to be quoted.
    """
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=["TEST_SCALAR=a b c", "TEST_NUMBER=4"],
    )

    assert resolved["TEST_SCALAR"] == "a b c"
    assert resolved["TEST_NUMBER"] == 4


# --- Tcl sources: the PDK ---------------------------------------------------


def test_a_pdk_still_reads_lists_and_dictionaries_as_tcl(pdk_writing, design_dir):
    """
    Every PDK ships its configuration as Tcl -- sky130A and gf180mcu under
    'libs.tech/openlane', ihp-sg13g2 under 'libs.tech/librelane' -- so a
    space-separated string it writes is still a list.
    """
    pdk_root = pdk_writing(
        """
        set ::env(TEST_PDK_DICT) "a 1 b 2"
        set ::env(TEST_PDK_LIST) "p q r"
        """
    )

    resolved = _resolve(pdk_root, [{"DESIGN_NAME": "x"}], design_dir)

    assert resolved["TEST_PDK_DICT"] == {"a": "1", "b": "2"}
    assert resolved["TEST_PDK_LIST"] == ["p", "q", "r"]


def test_an_uneven_tcl_dictionary_names_the_syntax_and_the_key(
    pdk_writing, design_dir
):
    pdk_root = pdk_writing('set ::env(TEST_PDK_DICT) "a 1 b"\n')

    [error] = _errors(pdk_root, [{"DESIGN_NAME": "x"}], design_dir)

    assert "TEST_PDK_DICT" in error
    assert "uneven Tcl dictionary" in error


def test_a_design_source_overrides_a_pdk_value_in_its_own_syntax(
    pdk_writing, design_dir
):
    """
    The syntax belongs to the source that wrote the value. A design file is
    read as written even where the PDK wrote the same key as Tcl text.
    """
    pdk_root = pdk_writing('set ::env(TEST_PDK_LIST) "p q r"\n')

    resolved = _resolve(
        pdk_root, [{"DESIGN_NAME": "x", "TEST_PDK_LIST": ["s", "t"]}], design_dir
    )

    assert resolved["TEST_PDK_LIST"] == ["s", "t"]


# --- typed sources ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a 1 b 2", '{"a": "1"}'],
    ids=["tcl-text", "json-text"],
)
def test_a_typed_source_takes_no_string_for_a_dictionary(tiny_pdk, design_dir, value):
    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x", "TEST_DICT": value}],
        design_dir,
    )

    assert "TEST_DICT" in error


def test_a_yaml_source_takes_no_string_for_a_list(tiny_pdk, design_dir):
    path = design_dir / "config.yaml"
    path.write_text("DESIGN_NAME: x\nTEST_LIST: p q r\n")

    [error] = _errors(tiny_pdk, [str(path)], design_dir)

    assert "TEST_LIST" in error


def test_a_flow_document_takes_no_string_for_a_list(tiny_pdk, design_dir):
    from librelane.config import ConfigSource

    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        under=[ConfigSource({"TEST_LIST": "p q r"}, "<flow document>", "mapping")],
    )

    assert "TEST_LIST" in error


# --- the last writer decides ------------------------------------------------


def test_the_command_line_overrides_a_pdk_value_in_its_own_syntax(
    pdk_writing, design_dir
):
    pdk_root = pdk_writing('set ::env(TEST_PDK_DICT) "a 1 b 2"\n')

    resolved = _resolve(
        pdk_root,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_PDK_DICT={"c": "3"}'],
    )

    assert resolved["TEST_PDK_DICT"] == {"c": "3"}


def test_a_typed_source_after_a_pdk_value_does_not_inherit_tcl_syntax(
    pdk_writing, design_dir
):
    """A stale entry for the PDK would silently split the mapping's text."""
    pdk_root = pdk_writing('set ::env(TEST_PDK_LIST) "p q r"\n')

    [error] = _errors(
        pdk_root, [{"DESIGN_NAME": "x", "TEST_PDK_LIST": "x y z"}], design_dir
    )

    assert "TEST_PDK_LIST" in error


def test_a_deprecated_name_from_the_command_line_keeps_the_command_line_syntax(
    tiny_pdk, design_dir
):
    """
    A rename moves the value onto another key, so the syntax has to move with
    it or the renamed value is read as though nobody had written it.
    """
    resolved = _resolve(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        config_override_strings=['TEST_RENAMED_LIST_LEGACY=["p", "q"]'],
    )

    assert resolved["TEST_RENAMED_LIST"] == ["p", "q"]


# --- design documents are never Tcl -----------------------------------------


def test_a_json_document_without_meta_does_not_read_its_strings_as_tcl(
    tiny_pdk, design_dir
):
    """
    ``meta.version`` 1 used to declare the whole document openlane-era, whose
    values were Tcl text whichever container carried them, and a '.json' file
    without a 'meta' key was exactly that. Both are gone: a design file means
    what it says, so a string reaching a list variable is an error.
    """
    path = design_dir / "config.json"
    path.write_text(json.dumps({"DESIGN_NAME": "x", "TEST_LIST": "p q r"}))

    [error] = _errors(tiny_pdk, [str(path)], design_dir)

    assert "TEST_LIST" in error


def test_an_explicit_meta_version_1_is_not_a_way_back_to_tcl(tiny_pdk, design_dir):
    """Declaring the old version does not restore the old reading."""
    path = design_dir / "config.json"
    path.write_text(
        json.dumps({"meta": {"version": 1}, "DESIGN_NAME": "x", "TEST_LIST": "p q r"})
    )

    [error] = _errors(tiny_pdk, [str(path)], design_dir)

    assert "TEST_LIST" in error


def test_the_command_line_is_json_for_a_document_without_meta(tiny_pdk, design_dir):
    """The command line is not part of the document either way."""
    path = design_dir / "config.json"
    path.write_text(json.dumps({"DESIGN_NAME": "x"}))

    resolved = _resolve(
        tiny_pdk,
        [str(path)],
        design_dir,
        config_override_strings=['TEST_DICT={"a": "1"}'],
    )

    assert resolved["TEST_DICT"] == {"a": "1"}
