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
Reading a PDK from descriptors rather than from a Tcl program.

A PDK that ships ``libs.tech/librelane/pdk.yaml`` is read from that file, its
standard cell library's ``scl.yaml`` and, if it has one, its pad library's
``pad.yaml``. The three are merged in order, so where a value came from is the
file that last wrote it rather than something to recover by diffing
environments -- and the values are native, so they are compiled under strict
typing and a Tcl word list is not a list.

A PDK that ships no ``pdk.yaml`` is read exactly as it was before.

The format is specified in
``docs/superpowers/specs/2026-08-05-pdk-descriptor-format.md``.
"""

import os
import textwrap
from decimal import Decimal

import pytest

from librelane.common import Path
from librelane.config import Variable

pytestmark = pytest.mark.all


#: The smallest variable list these loads resolve against. Written out rather
#: than borrowed from ``test.conftest.COMMON_FLOW_VARS`` because these tests
#: need PDK variables of each shape a descriptor writes: a scalar, a number an
#: ``expr::`` reads, a list of paths and a dictionary of them.
_VARIABLES = [
    Variable("PDK_ROOT", str, description="x"),
    Variable("PDK", str, description="x"),
    Variable("DESIGN_DIR", Path, description="x"),
    Variable("DESIGN_NAME", str, description="x"),
    Variable("STD_CELL_LIBRARY", str, description="x", pdk=True),
    Variable("PAD_CELL_LIBRARY", str | None, description="x", default=None, pdk=True),
    Variable("TEST_FROM_PDK", str, description="x", pdk=True),
    Variable("TEST_FROM_SCL", str, description="x", pdk=True),
    Variable("TEST_FROM_PAD", str | None, description="x", default=None, pdk=True),
    Variable("TEST_LAYERED", str, description="x", pdk=True),
    Variable("TEST_INTERPOLATED", str, description="x", pdk=True),
    Variable("TEST_NUMBER", Decimal, description="x", pdk=True),
    Variable("TEST_EXPR", Decimal, description="x", pdk=True),
    Variable("TEST_LIST", list[str] | None, description="x", default=None, pdk=True),
    Variable("CELL_LEFS", list[Path], description="x", pdk=True),
    Variable("LIB", dict[str, list[Path]], description="x", pdk=True),
]

_PDK_YAML = """\
meta:
  format: 1
  family: tiny
  variant: tiny
  scls: [tiny_scl, tiny_scl_alt]
  pads: [tiny_pad]
STD_CELL_LIBRARY: tiny_scl
PAD_CELL_LIBRARY: tiny_pad
TEST_FROM_PDK: from the pdk
TEST_LAYERED: from the pdk
TEST_INTERPOLATED: ref::$STD_CELL_LIBRARY/suffix
TEST_NUMBER: 0.25
TEST_EXPR: expr::$TEST_NUMBER * 4
"""

_SCL_YAML = """\
meta: {format: 1}
TEST_FROM_SCL: from the scl
TEST_LAYERED: from the scl
CELL_LEFS: [pdk_dir::libs.ref/tiny_scl/lef/*.lef]
LIB:
  "*tt*": [pdk_dir::libs.ref/tiny_scl/lib/tt.lib]
"""

_SCL_ALT_YAML = """\
meta: {format: 1}
TEST_FROM_SCL: from the other scl
TEST_LAYERED: from the other scl
CELL_LEFS: [pdk_dir::libs.ref/tiny_scl/lef/tiny_scl.lef]
LIB:
  "*tt*": [pdk_dir::libs.ref/tiny_scl/lib/tt.lib]
"""

_PAD_YAML = """\
meta: {format: 1}
TEST_FROM_PAD: from the pad
TEST_LAYERED: from the pad
"""


@pytest.fixture(autouse=True)
def _forget_pdk_environments():
    """
    Drop the memoized PDK environment around every test.

    ``Config.__get_pdk_raw`` is memoized on its arguments, and a test that
    rewrites a descriptor and loads the same PDK again would otherwise be
    handed the environment read before the rewrite.
    """
    from librelane.config import Config

    Config._Config__get_pdk_raw.cache_clear()
    yield
    Config._Config__get_pdk_raw.cache_clear()


@pytest.fixture
def descriptor_pdk(tmp_path):
    """
    A PDK described by ``pdk.yaml``, two ``scl.yaml`` files and a ``pad.yaml``.

    ``TEST_LAYERED`` is written by all four, so every layer's precedence is
    observable and the origin of the merged value has exactly one right answer.
    The views the descriptors point at exist on disk, because a ``pdk_dir::``
    reference is glob-expanded against the tree and one that matches nothing
    resolves to the unexpanded path.

    Returns
    -------
    pathlib.Path
        The ``libs.tech/librelane`` directory, whose parents are the PDK root
        the tests load against. Returned rather than the root so that a test
        may rewrite one descriptor.
    """
    librelane_dir = tmp_path / "pdk" / "tiny" / "libs.tech" / "librelane"
    for name in ("tiny_scl", "tiny_scl_alt", "tiny_pad"):
        (librelane_dir / name).mkdir(parents=True)

    views = tmp_path / "pdk" / "tiny" / "libs.ref" / "tiny_scl"
    (views / "lef").mkdir(parents=True)
    (views / "lib").mkdir(parents=True)
    for view in ("lef/tiny_scl.lef", "lef/tiny_scl_ef.lef", "lib/tt.lib"):
        (views / view).write_text("")

    (librelane_dir / "pdk.yaml").write_text(_PDK_YAML)
    (librelane_dir / "tiny_scl" / "scl.yaml").write_text(_SCL_YAML)
    (librelane_dir / "tiny_scl_alt" / "scl.yaml").write_text(_SCL_ALT_YAML)
    (librelane_dir / "tiny_pad" / "pad.yaml").write_text(_PAD_YAML)
    return librelane_dir


@pytest.fixture
def tcl_pdk(tmp_path):
    """
    The same PDK with no descriptors at all, as a ``config.tcl`` pair.

    The fallback these tests assert is not that a Tcl PDK still loads in the
    abstract: it is that it still loads *the way it did*, values written as Tcl
    word lists and all, which is what the descriptor path deliberately does not
    do.

    Returns
    -------
    str
        The PDK root to load against.
    """
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    views = root / "tiny" / "libs.ref" / "tiny_scl"
    (views / "lef").mkdir(parents=True)
    (views / "lib").mkdir(parents=True)
    for view in ("lef/tiny_scl.lef", "lib/tt.lib"):
        (views / view).write_text("")

    (librelane_dir / "config.tcl").write_text(
        textwrap.dedent(
            f"""\
            if {{ ![info exists ::env(STD_CELL_LIBRARY)] }} {{
                set ::env(STD_CELL_LIBRARY) "tiny_scl"
            }}
            set ::env(TEST_FROM_PDK) "from the pdk"
            set ::env(TEST_LAYERED) "from the pdk"
            set ::env(TEST_INTERPOLATED) "tiny_scl/suffix"
            set ::env(TEST_NUMBER) "0.25"
            set ::env(TEST_EXPR) "1"
            set ::env(TEST_LIST) "a b c"
            set ::env(CELL_LEFS) "{views / "lef" / "tiny_scl.lef"}"
            set ::env(LIB) "*tt* {views / "lib" / "tt.lib"}"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text(
        'set ::env(TEST_FROM_SCL) "from the scl"\n'
        'set ::env(TEST_LAYERED) "from the scl"\n'
    )
    return str(root)


def _resolve(pdk_root, tmp_path, **load):
    """
    Resolve a minimal design against a PDK.

    Parameters
    ----------
    pdk_root : str | os.PathLike
        Where the ``tiny`` PDK is installed.
    tmp_path
        The design directory.
    load
        Further keyword arguments for :meth:`librelane.config.Config.load`.

    Returns
    -------
    librelane.config.Config
        The resolved configuration.
    """
    from librelane.config import Config

    resolved, _ = Config.load(
        {"DESIGN_NAME": "x"},
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=str(pdk_root),
        **load,
    )
    return resolved


def _root_of(librelane_dir):
    """The PDK root holding the variant whose descriptors live here."""
    return librelane_dir.parents[2]


def _read(librelane_dir, **arguments):
    """
    The descriptors as the reader returns them, before anything is compiled
    against a variable list.

    Returns
    -------
    librelane.config.descriptor.PdkDescriptor | None
        What :func:`librelane.config.descriptor.read_pdk_descriptor` said.
    """
    from librelane.config.descriptor import read_pdk_descriptor

    root = _root_of(librelane_dir)
    return read_pdk_descriptor(
        str(root / "tiny"),
        pdk_root=str(root),
        pdk="tiny",
        **arguments,
    )


def test_a_key_no_variable_claims_is_carried_as_written(descriptor_pdk):
    """
    The environment is not filtered down to what the current flow declares: a
    key may belong to a step or a plugin that is not loaded, which is why the
    Tcl path carried whatever a ``config.tcl`` set, and dropping it here would
    make a descriptor say less than the file it replaces.
    """
    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML + "TEST_UNCLAIMED: [a, b]\n"
    )

    descriptor = _read(descriptor_pdk)

    assert descriptor is not None
    assert descriptor.values["TEST_UNCLAIMED"] == ["a", "b"]
    assert descriptor.origins["TEST_UNCLAIMED"] == "<scl>"


def test_a_pdk_with_no_descriptor_reads_as_nothing(tcl_pdk):
    """
    What selects the Tcl path: the reader says there is nothing to read rather
    than raising, so a PDK that ships no ``pdk.yaml`` is not a broken one.
    """
    from librelane.config.descriptor import read_pdk_descriptor

    assert (
        read_pdk_descriptor(os.path.join(tcl_pdk, "tiny"), pdk_root=tcl_pdk, pdk="tiny")
        is None
    )


def test_the_layers_merge_in_order(descriptor_pdk, tmp_path):
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert resolved["TEST_FROM_PDK"] == "from the pdk"
    assert resolved["TEST_FROM_SCL"] == "from the scl"
    assert resolved["TEST_FROM_PAD"] == "from the pad"
    # Written by every layer, so the last one read is the one that counts.
    assert resolved["TEST_LAYERED"] == "from the pad"


def test_each_value_is_attributed_to_the_layer_that_wrote_it(descriptor_pdk, tmp_path):
    """
    The merge is the attribution: no environment diffing, no migration to
    follow the renames of, just which file last wrote each key.
    """
    provenance = _resolve(_root_of(descriptor_pdk), tmp_path).provenance

    assert provenance["TEST_FROM_PDK"] == "<pdk>"
    assert provenance["TEST_FROM_SCL"] == "<scl>"
    assert provenance["TEST_FROM_PAD"] == "<pad>"
    assert provenance["TEST_LAYERED"] == "<pad>"
    assert provenance["CELL_LEFS"] == "<scl>"


def test_a_design_value_outranks_the_descriptors(descriptor_pdk, tmp_path):
    from librelane.config import Config

    resolved, _ = Config.load(
        {"DESIGN_NAME": "x", "TEST_FROM_PDK": "from the design"},
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=str(_root_of(descriptor_pdk)),
    )

    assert resolved["TEST_FROM_PDK"] == "from the design"
    assert resolved.provenance["TEST_FROM_PDK"] == "<mapping>"


def test_a_pdk_dir_reference_inside_a_list_is_expanded(descriptor_pdk, tmp_path):
    """
    A directive is legal wherever a string is, which for a PDK's views means
    inside the list a variable is declared as. The Tcl path had nowhere to put
    one: everything it wrote was a word list of absolute paths.
    """
    views = _root_of(descriptor_pdk) / "tiny" / "libs.ref" / "tiny_scl" / "lef"
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert [str(path) for path in resolved["CELL_LEFS"]] == [
        str(views / "tiny_scl.lef"),
        str(views / "tiny_scl_ef.lef"),
    ]


def test_a_pdk_dir_reference_inside_a_dict_value_is_expanded(descriptor_pdk, tmp_path):
    views = _root_of(descriptor_pdk) / "tiny" / "libs.ref" / "tiny_scl" / "lib"
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert {
        corner: [str(path) for path in paths]
        for corner, paths in resolved["LIB"].items()
    } == {"*tt*": [str(views / "tt.lib")]}


def test_a_reference_interpolates_another_variable(descriptor_pdk, tmp_path):
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert resolved["TEST_INTERPOLATED"] == "tiny_scl/suffix"


def test_an_expression_reads_a_number_written_as_a_number(descriptor_pdk, tmp_path):
    """
    A YAML float is a ``Decimal``, so a descriptor's number round-trips exactly
    and an ``expr::`` over it is exact arithmetic rather than binary floating
    point.
    """
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert resolved["TEST_NUMBER"] == Decimal("0.25")
    assert resolved["TEST_EXPR"] == Decimal("1.00")


def test_the_caller_chooses_the_standard_cell_library(descriptor_pdk, tmp_path):
    resolved = _resolve(_root_of(descriptor_pdk), tmp_path, scl="tiny_scl_alt")

    assert resolved["STD_CELL_LIBRARY"] == "tiny_scl_alt"
    assert resolved["TEST_FROM_SCL"] == "from the other scl"
    # The chosen library's descriptor is the one read, and 'pdk_dir::' still
    # resolves against the PDK rather than against it.
    assert len(resolved["CELL_LEFS"]) == 1


def test_a_standard_cell_library_with_no_descriptor_is_refused(
    descriptor_pdk, tmp_path
):
    from librelane.config import InvalidConfig

    with pytest.raises(InvalidConfig, match="scl.yaml' was not found"):
        _resolve(_root_of(descriptor_pdk), tmp_path, scl="tiny_scl_absent")


def test_an_unknown_descriptor_format_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace("format: 1", "format: 2")
    )

    with pytest.raises(InvalidConfig, match="descriptor format '2'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_an_unknown_descriptor_format_in_a_library_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML.replace("format: 1", "format: 9")
    )

    with pytest.raises(InvalidConfig, match="descriptor format '9'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_declared_library_that_is_not_installed_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace("[tiny_scl, tiny_scl_alt]", "[tiny_scl, tiny_scl_alt, ghost]")
    )

    with pytest.raises(InvalidConfig, match="'ghost', which has no"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_an_installed_library_that_is_not_declared_is_refused(descriptor_pdk, tmp_path):
    """
    ``meta.scls`` is what a caller reads to offer a choice of libraries, so one
    that is installed and unlisted is a PDK nobody can be told about -- an
    error at load rather than a surprise at ``--scl``.
    """
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace("[tiny_scl, tiny_scl_alt]", "[tiny_scl]")
    )

    with pytest.raises(InvalidConfig, match="'tiny_scl_alt' has a descriptor"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_descriptor_that_declares_no_libraries_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace("  scls: [tiny_scl, tiny_scl_alt]\n", "")
    )

    with pytest.raises(InvalidConfig, match="does not declare 'meta.scls'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_descriptor_with_no_meta_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text("TEST_FROM_SCL: x\n")

    with pytest.raises(InvalidConfig, match="has no 'meta' section"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_brace_interpolation_is_refused(descriptor_pdk, tmp_path):
    """
    ``${VAR}`` is not a directive spelled awkwardly: nothing resolves it, so it
    would reach a tool as the literal characters an author meant as a path. It
    can only be a mistranscribed ``ref::``, which is worth an error rather than
    a value that fails much later and somewhere else.
    """
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace(
            "TEST_FROM_PDK: from the pdk",
            "TEST_FROM_PDK: ${PDKPATH}/libs.ref",
        )
    )

    with pytest.raises(InvalidConfig, match=r"in 'TEST_FROM_PDK'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_brace_interpolation_inside_a_list_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML.replace(
            "CELL_LEFS: [pdk_dir::libs.ref/tiny_scl/lef/*.lef]",
            "CELL_LEFS: [pdk_dir::libs.ref/tiny_scl/lef/*.lef, "
            '"${PDKPATH}/libs.ref/tiny_scl/lef/tiny_scl.lef"]',
        )
    )

    with pytest.raises(InvalidConfig, match=r"in 'CELL_LEFS\[1\]'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_brace_interpolation_inside_a_dict_value_is_refused(descriptor_pdk, tmp_path):
    from librelane.config import InvalidConfig

    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML.replace(
            '"*tt*": [pdk_dir::libs.ref/tiny_scl/lib/tt.lib]',
            '"*tt*": "${PDKPATH}/libs.ref/tiny_scl/lib/tt.lib"',
        )
    )

    with pytest.raises(InvalidConfig, match=r"in 'LIB.\*tt\*'"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_the_error_says_how_interpolation_is_spelled(descriptor_pdk, tmp_path):
    """
    The author of a descriptor is the one who has to fix this, and the whole
    reason it is an error is that the right spelling is not guessable from the
    wrong one silently working.
    """
    from librelane.config import InvalidConfig

    (descriptor_pdk / "pdk.yaml").write_text(
        _PDK_YAML.replace(
            "TEST_FROM_PDK: from the pdk",
            "TEST_FROM_PDK: ${PDKPATH}/libs.ref",
        )
    )

    with pytest.raises(InvalidConfig) as raised:
        _resolve(_root_of(descriptor_pdk), tmp_path)

    (error,) = raised.value.errors
    assert "'$VAR'" in error
    assert "'ref::', 'refg::' or 'expr::'" in error
    assert "pdk.yaml" in error


def test_a_word_list_written_as_a_string_is_not_a_list(descriptor_pdk, tmp_path):
    """
    A descriptor is a typed source: the one thing it may not do is write a
    product-typed value as text and expect it to be split. Reading it
    permissively is what the Tcl path does because a ``config.tcl`` has no
    other way to write a list.
    """
    from librelane.config import InvalidConfig

    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML + 'TEST_LIST: "a b c"\n'
    )

    with pytest.raises(InvalidConfig, match="'TEST_LIST' under strict typing"):
        _resolve(_root_of(descriptor_pdk), tmp_path)


def test_a_list_written_as_a_list_is_read_as_written(descriptor_pdk, tmp_path):
    (descriptor_pdk / "tiny_scl" / "scl.yaml").write_text(
        _SCL_YAML + "TEST_LIST: [a b, c]\n"
    )

    resolved = _resolve(_root_of(descriptor_pdk), tmp_path)

    assert resolved["TEST_LIST"] == ["a b", "c"]


def test_a_pdk_without_descriptors_is_still_read_as_tcl(tcl_pdk, tmp_path):
    resolved = _resolve(tcl_pdk, tmp_path)

    assert resolved["TEST_FROM_PDK"] == "from the pdk"
    assert resolved["TEST_LAYERED"] == "from the scl"
    assert resolved.provenance["TEST_FROM_SCL"] == "<scl>"
    # The values a 'config.tcl' writes are Tcl text, and the permissive read
    # that makes them into a list and a dictionary is exactly what the
    # descriptor path drops.
    assert resolved["TEST_LIST"] == ["a", "b", "c"]
    assert list(resolved["LIB"]) == ["*tt*"]
