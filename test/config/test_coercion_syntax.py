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
``.tcl`` file's values are Tcl text, a ``--config-override`` is written on a
shell command line, and a YAML, JSON or Python mapping carries a list as a
list. One flag used to answer both questions at once, so a command-line value
for any product-typed variable was split as a Tcl list and every JSON object
given to one died on ``uneven Tcl dictionary``.
"""

import json
import textwrap
from typing import Optional

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
    Variable("TEST_DICT", Optional[dict[str, str]], description="x", default=None),
    Variable("TEST_LIST", Optional[list[str]], description="x", default=None),
    Variable("TEST_SCALAR", Optional[str], description="x", default=None),
    Variable("TEST_NUMBER", Optional[int], description="x", default=None),
    Variable(
        "TEST_RENAMED_LIST",
        Optional[list[str]],
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


def _tcl(design_dir, body: str, name: str = "config.tcl") -> str:
    path = design_dir / name
    path.write_text(textwrap.dedent(body))
    return str(path)


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


# --- Tcl sources ------------------------------------------------------------


def test_a_tcl_source_still_reads_lists_and_dictionaries_as_tcl(tiny_pdk, design_dir):
    """
    A '.tcl' file on its own puts the whole load in permissive mode. Layering a
    mapping after it does not -- 'meta' comes from the last source -- so this
    is the per-key path, which is the one the split changes.
    """
    tcl = _tcl(
        design_dir,
        """\
        set ::env(DESIGN_NAME) "x"
        set ::env(TEST_DICT) "a 1 b 2"
        set ::env(TEST_LIST) "p q r"
        """,
    )

    resolved = _resolve(tiny_pdk, [tcl, {"TEST_SCALAR": "y"}], design_dir)

    assert resolved["TEST_DICT"] == {"a": "1", "b": "2"}
    assert resolved["TEST_LIST"] == ["p", "q", "r"]


def test_a_tcl_source_alone_still_reads_lists_and_dictionaries_as_tcl(
    tiny_pdk, design_dir
):
    tcl = _tcl(
        design_dir,
        """\
        set ::env(DESIGN_NAME) "x"
        set ::env(TEST_DICT) "a 1 b 2"
        set ::env(TEST_LIST) "p q r"
        """,
    )

    resolved = _resolve(tiny_pdk, [tcl], design_dir)

    assert resolved["TEST_DICT"] == {"a": "1", "b": "2"}
    assert resolved["TEST_LIST"] == ["p", "q", "r"]


def test_an_uneven_tcl_dictionary_names_the_syntax_and_the_key(tiny_pdk, design_dir):
    tcl = _tcl(
        design_dir,
        """\
        set ::env(DESIGN_NAME) "x"
        set ::env(TEST_DICT) "a 1 b"
        """,
    )

    [error] = _errors(tiny_pdk, [tcl, {"TEST_SCALAR": "y"}], design_dir)

    assert "TEST_DICT" in error
    assert "uneven Tcl dictionary" in error


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
    [error] = _errors(
        tiny_pdk,
        [{"DESIGN_NAME": "x"}],
        design_dir,
        flow_values={"TEST_LIST": "p q r"},
    )

    assert "TEST_LIST" in error


# --- the last writer decides ------------------------------------------------


def test_the_command_line_overrides_a_tcl_source_in_its_own_syntax(
    tiny_pdk, design_dir
):
    tcl = _tcl(
        design_dir,
        """\
        set ::env(DESIGN_NAME) "x"
        set ::env(TEST_DICT) "a 1 b 2"
        """,
    )

    resolved = _resolve(
        tiny_pdk,
        [tcl],
        design_dir,
        config_override_strings=['TEST_DICT={"c": "3"}'],
    )

    assert resolved["TEST_DICT"] == {"c": "3"}


def test_a_typed_source_after_a_tcl_source_does_not_inherit_tcl_syntax(
    tiny_pdk, design_dir
):
    """A stale entry for the Tcl file would silently split the mapping's text."""
    tcl = _tcl(
        design_dir,
        """\
        set ::env(DESIGN_NAME) "x"
        set ::env(TEST_LIST) "p q r"
        """,
    )

    [error] = _errors(tiny_pdk, [tcl, {"TEST_LIST": "x y z"}], design_dir)

    assert "TEST_LIST" in error


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


# --- openlane-era documents -------------------------------------------------


def test_a_meta_version_1_document_still_reads_its_strings_as_tcl(tiny_pdk, design_dir):
    """
    ``meta.version`` 1 declares the whole document openlane-era, whose values
    are Tcl text whichever container carried them. A '.json' file without a
    'meta' key is exactly that, and this is what the deleted global permissive
    flag did for it.
    """
    path = design_dir / "config.json"
    path.write_text(json.dumps({"DESIGN_NAME": "x", "TEST_LIST": "p q r"}))

    resolved = _resolve(tiny_pdk, [str(path)], design_dir)

    assert resolved["TEST_LIST"] == ["p", "q", "r"]


def test_the_command_line_is_json_even_for_an_openlane_era_document(
    tiny_pdk, design_dir
):
    """The command line is not part of the document, so its version says
    nothing about how a value typed into a shell is written."""
    path = design_dir / "config.json"
    path.write_text(json.dumps({"DESIGN_NAME": "x"}))

    resolved = _resolve(
        tiny_pdk,
        [str(path)],
        design_dir,
        config_override_strings=['TEST_DICT={"a": "1"}'],
    )

    assert resolved["TEST_DICT"] == {"a": "1"}
