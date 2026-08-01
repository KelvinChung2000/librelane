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
Where each value in a resolved configuration came from.

The design sources and the command line are layered by ``layer_mappings``,
which records the last writer of every key. The PDK and the SCL are merged
separately, by ``Config.__get_pdk_config``, so a value they supply has to be
attributed there or it is attributed nowhere -- and a caller asking for a
variable's origin would be told ``default``, which is a wrong answer rather
than a missing one.
"""

import textwrap
from typing import Optional

import pytest

from librelane.config import Variable
from librelane.common import Path

pytestmark = pytest.mark.all


#: The smallest variable list a ``Config.load`` call resolves against. Written
#: out rather than borrowed from ``test.conftest.COMMON_FLOW_VARS``, because
#: these tests need PDK variables whose values they choose.
_VARIABLES = [
    Variable("PDK_ROOT", str, description="x"),
    Variable("PDK", str, description="x"),
    Variable("DESIGN_DIR", Path, description="x"),
    Variable("DESIGN_NAME", str, description="x"),
    Variable("STD_CELL_LIBRARY", str, description="x", pdk=True),
    Variable("TEST_FROM_PDK", str, description="x", pdk=True),
    Variable("TEST_FROM_SCL", str, description="x", pdk=True),
    Variable("TEST_LAYERED", str, description="x", pdk=True),
    Variable("TEST_UNSET", Optional[str], description="x"),
]


@pytest.fixture
def tiny_pdk(tmp_path):
    """
    A PDK whose two configuration files set overlapping variables.

    ``TEST_LAYERED`` is written by both, so the SCL is the last writer and the
    attribution has to say so. Separate from the shared mock tree in
    ``test.conftest``, whose SCL configuration is empty and therefore cannot
    tell the two layers apart at all.

    Returns
    -------
    str
        The PDK root to pass to :meth:`librelane.config.Config.load`.
    """
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    (librelane_dir / "config.tcl").write_text(
        textwrap.dedent(
            """\
            set ::env(STD_CELL_LIBRARY) "tiny_scl"
            set ::env(TEST_FROM_PDK) "from the pdk"
            set ::env(TEST_LAYERED) "from the pdk"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text(
        textwrap.dedent(
            """\
            set ::env(TEST_FROM_SCL) "from the scl"
            set ::env(TEST_LAYERED) "from the scl"
            """
        )
    )
    return str(root)


def _provenance(mocker, tiny_pdk, design, tmp_path) -> dict:
    """
    Parameters
    ----------
    mocker
        The ``pytest-mock`` fixture.
    tiny_pdk : str
        The PDK root :func:`tiny_pdk` built.
    design : dict
        The design configuration to resolve.
    tmp_path
        The design directory.

    Returns
    -------
    dict
        The key-to-origin map ``Config.load`` hands to ``validate_mapping``.
        Read off the call rather than off the returned configuration, because
        nothing exposes it on a ``Config`` yet.
    """
    from librelane.config import Config
    from librelane.config import config as config_module

    spy = mocker.patch.object(
        config_module,
        "validate_mapping",
        wraps=config_module.validate_mapping,
    )
    Config.load(
        design,
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=tiny_pdk,
    )
    return dict(spy.call_args.kwargs["provenance"])


def test_a_pdk_supplied_value_is_attributed_to_the_pdk(mocker, tiny_pdk, tmp_path):
    provenance = _provenance(mocker, tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_FROM_PDK"] == "<pdk>"


def test_an_scl_supplied_value_is_attributed_to_the_scl(mocker, tiny_pdk, tmp_path):
    provenance = _provenance(mocker, tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_FROM_SCL"] == "<scl>"


def test_the_scl_outranks_the_pdk_for_a_key_both_write(mocker, tiny_pdk, tmp_path):
    provenance = _provenance(mocker, tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_LAYERED"] == "<scl>"


def test_a_design_value_outranks_the_pdk_attribution(mocker, tiny_pdk, tmp_path):
    provenance = _provenance(
        mocker,
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_FROM_PDK": "from the design"},
        tmp_path,
    )

    assert provenance["TEST_FROM_PDK"] == "<mapping>"
    # The keys the design was silent about keep the layer that did write them.
    assert provenance["TEST_FROM_SCL"] == "<scl>"


def test_a_variable_nobody_set_is_attributed_to_nothing(mocker, tiny_pdk, tmp_path):
    provenance = _provenance(mocker, tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    # Absence is how a caller reads "default": an entry here would name a
    # source that supplied no value at all.
    assert "TEST_UNSET" not in provenance
