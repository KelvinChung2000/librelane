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
The gate on converting a PDK to descriptors: reading it either way resolves to
the same configuration.

A converted PDK ships both a ``config.tcl`` tree and a descriptor tree, and the
descriptors are only correct if every variable they resolve to is the value the
Tcl program produced. Origin labels are excluded because they are the one thing
the two paths are meant to disagree about in shape -- the descriptor path reads
them off the merge, the Tcl path off an environment diff -- but not in content:
they are compared separately, and a value that moved layers is reported.

Today no installed PDK carries a ``pdk.yaml``, so the per-PDK cases skip. They
arm themselves the moment the converter (``tools/pdk_import.py``) writes one
into an installed tree. :func:`assert_paths_agree` is the assertion itself, so
that the conversion work can call it directly on a tree it has just written.
"""

import contextlib
import os
import textwrap
from typing import Any
from unittest import mock

import pytest

pytestmark = pytest.mark.all


#: The PDKs the descriptor conversion covers, as (ciel family, variant). The
#: family names the directory Ciel installs the variants into, which is what a
#: PDK root is.
_SHIPPED_PDKS = [
    ("sky130", "sky130A"),
    ("gf180mcu", "gf180mcuD"),
    ("ihp-sg13g2", "ihp-sg13g2"),
]


def pdk_variables() -> list:
    """
    Every variable a PDK is allowed to supply a value for.

    Not just :data:`librelane.config.flow.pdk_variables`: a step declares PDK
    variables of its own -- the KLayout views, the Magic tech file, the OpenROAD
    RC layers -- and those are exactly the ones a hand-checked conversion is
    likely to miss, so a parity check that left them out would pass on a
    descriptor tree that cannot run a flow.

    Returns
    -------
    list[librelane.config.Variable]
        The variables, deduplicated by name.
    """
    import librelane.steps  # noqa: F401  -- registers every built-in step
    from librelane.config.flow import flow_common_variables
    from librelane.steps import Step

    by_name = {
        variable.name: variable for variable in flow_common_variables if variable.pdk
    }
    for step_id in Step.factory.list():
        step = Step.factory.get(step_id)
        if step is None:  # pragma: no cover -- a factory listing is exhaustive
            continue
        for variable in step.config_vars:
            if variable.pdk:
                by_name.setdefault(variable.name, variable)
    return list(by_name.values())


def resolve_pdk(
    pdk_root: str,
    pdk: str,
    variables: list,
    *,
    descriptors: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Resolve one PDK layer through one of the two reading paths.

    Parameters
    ----------
    pdk_root : str
        Where the PDK is installed.
    pdk : str
        The variant to read.
    variables : list[librelane.config.Variable]
        The variable list to compile against.
    descriptors : bool
        Read the descriptors if the PDK has any. ``False`` reads the
        ``config.tcl`` tree even when it does, which is the whole point: the two
        paths cannot be compared on a converted PDK otherwise.

    Returns
    -------
    tuple[dict[str, Any], dict[str, str]]
        The resolved values and each one's origin label.
    """
    from librelane.config import Config, config as config_module

    reader = (
        contextlib.nullcontext()
        if descriptors
        else mock.patch.object(config_module, "read_pdk_descriptor", return_value=None)
    )
    # Memoized on its arguments, which are identical for the two calls this
    # function makes across a comparison.
    Config._Config__get_pdk_raw.cache_clear()
    try:
        with reader:
            values, _, _, _, origins = Config._Config__get_pdk_config(
                pdk=pdk,
                scl=None,
                pad=None,
                pdk_root=pdk_root,
                flow_pdk_vars=variables,
            )
    finally:
        Config._Config__get_pdk_raw.cache_clear()
    return dict(values), dict(origins)


def assert_paths_agree(pdk_root: str, pdk: str) -> None:
    """
    Assert that a PDK's descriptors resolve to what its ``config.tcl`` does.

    Parameters
    ----------
    pdk_root : str
        Where the PDK is installed.
    pdk : str
        The variant to read. It must carry both a descriptor tree and a
        ``config.tcl`` tree, which is what a PDK mid-conversion looks like.
    """
    variables = pdk_variables()
    from_tcl, tcl_origins = resolve_pdk(pdk_root, pdk, variables, descriptors=False)
    from_yaml, yaml_origins = resolve_pdk(pdk_root, pdk, variables, descriptors=True)

    missing = sorted(set(from_tcl) - set(from_yaml))
    added = sorted(set(from_yaml) - set(from_tcl))
    differing = {
        name: (from_tcl[name], from_yaml[name])
        for name in sorted(set(from_tcl) & set(from_yaml))
        if from_tcl[name] != from_yaml[name]
    }
    assert (missing, added, differing) == ([], [], {}), (
        f"the descriptors of '{pdk}' do not resolve to what its config.tcl does"
    )
    # Reported rather than asserted: a value that moved layers resolves to the
    # same thing, so it is not a conversion error -- but it does mean a key was
    # written into a different file than the one that used to set it, which is
    # worth seeing while the conversion is being written.
    moved = {
        name: (tcl_origins.get(name), yaml_origins.get(name))
        for name in from_yaml
        if tcl_origins.get(name) != yaml_origins.get(name)
    }
    if moved:  # pragma: no cover -- nothing to print when the layers agree
        print(f"note: layers differ for {len(moved)} keys of '{pdk}': {moved}")


def _installed_pdk_root(family: str, variant: str, override: str | None) -> str | None:
    """
    Where the given PDK variant is installed, or ``None`` if it is not.

    Parameters
    ----------
    family : str
        The Ciel family, which names the directory under the Ciel home that
        holds its variants.
    variant : str
        The variant to look for.
    override : str | None
        A PDK root named by ``--pdk-root``, which is taken as holding the
        variants directly.
    """
    if override is not None:
        roots = [override]
    else:
        try:
            import ciel

            home = ciel.get_ciel_home(None)
        except ImportError:  # pragma: no cover -- Ciel is a hard dependency
            home = os.path.expanduser(os.path.join("~", ".ciel"))
        roots = [os.path.join(home, family)]
    for root in roots:
        if os.path.isdir(os.path.join(root, variant)):
            return root
    return None


@pytest.mark.parametrize(("family", "variant"), _SHIPPED_PDKS)
def test_a_shipped_pdk_resolves_the_same_either_way(request, family, variant):
    from librelane.config.descriptor import descriptor_path

    pdk_root = _installed_pdk_root(family, variant, request.config.option.pdk_root)
    if pdk_root is None:
        pytest.skip(f"the PDK '{variant}' is not installed")
    if not os.path.exists(descriptor_path(os.path.join(pdk_root, variant))):
        pytest.skip(f"the PDK '{variant}' ships no descriptors yet")

    assert_paths_agree(pdk_root, variant)


@pytest.fixture
def converted_pdk(tmp_path):
    """
    A PDK carrying both trees, saying the same thing twice.

    What a real one looks like mid-conversion, in miniature: this is what arms
    :func:`assert_paths_agree` before any real PDK has been converted, so that
    the harness is known to compare something rather than merely to skip.

    Returns
    -------
    str
        The PDK root to compare against.
    """
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    views = root / "tiny" / "libs.ref" / "tiny_scl"
    (views / "techlef").mkdir(parents=True)
    (views / "lef").mkdir(parents=True)
    (views / "techlef" / "tiny__nom.tlef").write_text("")
    (views / "lef" / "tiny_scl.lef").write_text("")

    (librelane_dir / "config.tcl").write_text(
        textwrap.dedent(
            f"""\
            if {{ ![info exists ::env(STD_CELL_LIBRARY)] }} {{
                set ::env(STD_CELL_LIBRARY) "tiny_scl"
            }}
            set ::env(TECH_LEFS) "nom {views / "techlef" / "tiny__nom.tlef"}"
            set ::env(CELL_LEFS) "{views / "lef" / "tiny_scl.lef"}"
            set ::env(DEFAULT_CORNER) "nom_tt_025C_1v80"
            set ::env(EXAMPLE_PDK_VAR) "42"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text("")
    (librelane_dir / "pdk.yaml").write_text(
        textwrap.dedent(
            """\
            meta:
              format: 1
              scls: [tiny_scl]
            STD_CELL_LIBRARY: tiny_scl
            DEFAULT_CORNER: nom_tt_025C_1v80
            EXAMPLE_PDK_VAR: 42
            """
        )
    )
    (librelane_dir / "tiny_scl" / "scl.yaml").write_text(
        textwrap.dedent(
            """\
            meta: {format: 1}
            TECH_LEFS:
              nom: pdk_dir::libs.ref/tiny_scl/techlef/tiny__nom.tlef
            CELL_LEFS: [pdk_dir::libs.ref/tiny_scl/lef/tiny_scl.lef]
            """
        )
    )
    return str(root)


def test_the_harness_sees_the_two_paths_agree(converted_pdk):
    with mock.patch(f"{__name__}.pdk_variables", _MOCK_PDK_VARIABLES):
        assert_paths_agree(converted_pdk, "tiny")

    # A comparison of two empty configurations passes as readily as a
    # comparison of two right ones, so what was compared is part of the claim.
    values, origins = resolve_pdk(
        converted_pdk, "tiny", _MOCK_PDK_VARIABLES(), descriptors=True
    )
    assert set(values) >= {"STD_CELL_LIBRARY", "TECH_LEFS", "EXAMPLE_PDK_VAR"}
    assert origins["TECH_LEFS"] == "<scl>"


def test_the_harness_sees_a_descriptor_that_says_something_else(
    converted_pdk, tmp_path
):
    """
    The other half: a harness that cannot fail proves nothing about a
    conversion it passes.
    """
    descriptor = tmp_path / "pdk" / "tiny" / "libs.tech" / "librelane" / "pdk.yaml"
    descriptor.write_text(
        descriptor.read_text().replace("EXAMPLE_PDK_VAR: 42", "EXAMPLE_PDK_VAR: 43")
    )

    with mock.patch(f"{__name__}.pdk_variables", _MOCK_PDK_VARIABLES):
        with pytest.raises(AssertionError, match="EXAMPLE_PDK_VAR"):
            assert_paths_agree(converted_pdk, "tiny")


def _MOCK_PDK_VARIABLES() -> list:
    """The mock tree's variables, standing in for a real flow's PDK variables."""
    return [variable for variable in pytest.COMMON_FLOW_VARS if variable.pdk]
