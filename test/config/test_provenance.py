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
from collections.abc import Mapping
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
    # The three shapes ``migrate_old_config`` produces: a key it renames from
    # one the PDK wrote, one it renames from a key the SCL wrote, and one it
    # synthesises from the PDK tree. None of the three exists under the name
    # the ``.tcl`` files used, so an attribution recorded under that name
    # describes nothing that survives into the configuration.
    Variable("TECH_LEFS", dict[str, Path], description="x", pdk=True),
    Variable("SYNTH_TIEHI_CELL", str, description="x", pdk=True),
    Variable("CELL_VERILOG_MODELS", Optional[list[Path]], description="x", pdk=True),
]


@pytest.fixture
def tiny_pdk(tmp_path):
    """
    A PDK whose two configuration files set overlapping variables.

    ``TEST_LAYERED`` is written by both, so the SCL is the last writer and the
    attribution has to say so. Separate from the shared mock tree in
    ``test.conftest``, whose SCL configuration is empty and therefore cannot
    tell the two layers apart at all.

    ``TECH_LEF`` and ``SYNTH_TIEHI_PORT`` are the two halves of the migration
    case, split across the layers exactly as a real openlane-era PDK splits
    them: measured on sky130A, ``TECH_LEF`` is written by the PDK's own file
    and ``SYNTH_TIEHI_PORT`` by the standard cell library's.

    Returns
    -------
    str
        The PDK root to pass to :meth:`librelane.config.Config.load`.
    """
    root = tmp_path / "pdk"
    librelane_dir = root / "tiny" / "libs.tech" / "librelane"
    (librelane_dir / "tiny_scl").mkdir(parents=True)
    techlef_dir = root / "tiny" / "libs.ref" / "tiny_scl" / "techlef"
    techlef_dir.mkdir(parents=True)
    (techlef_dir / "tiny__nom.tlef").write_text("")
    (librelane_dir / "config.tcl").write_text(
        textwrap.dedent(
            f"""\
            set ::env(STD_CELL_LIBRARY) "tiny_scl"
            set ::env(TEST_FROM_PDK) "from the pdk"
            set ::env(TEST_LAYERED) "from the pdk"
            set ::env(TECH_LEF) "{techlef_dir / "tiny__nom.tlef"}"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text(
        textwrap.dedent(
            """\
            set ::env(TEST_FROM_SCL) "from the scl"
            set ::env(TEST_LAYERED) "from the scl"
            set ::env(SYNTH_TIEHI_PORT) "tiny_conb_1 HI"
            """
        )
    )
    return str(root)


def _provenance(tiny_pdk, design, tmp_path, **load) -> Mapping[str, str]:
    """
    Parameters
    ----------
    tiny_pdk : str
        The PDK root :func:`tiny_pdk` built.
    design : dict
        The design configuration to resolve.
    tmp_path
        The design directory.
    load
        Further keyword arguments for :meth:`librelane.config.Config.load`.

    Returns
    -------
    Mapping[str, str]
        The resolved configuration's own key-to-origin map.
    """
    from librelane.config import Config

    resolved, _ = Config.load(
        design,
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=tiny_pdk,
        **load,
    )
    return resolved.provenance


def test_a_pdk_supplied_value_is_attributed_to_the_pdk(tiny_pdk, tmp_path):
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_FROM_PDK"] == "<pdk>"


def test_an_scl_supplied_value_is_attributed_to_the_scl(tiny_pdk, tmp_path):
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_FROM_SCL"] == "<scl>"


def test_the_scl_outranks_the_pdk_for_a_key_both_write(tiny_pdk, tmp_path):
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_LAYERED"] == "<scl>"


def test_a_design_value_outranks_the_pdk_attribution(tiny_pdk, tmp_path):
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_FROM_PDK": "from the design"},
        tmp_path,
    )

    assert provenance["TEST_FROM_PDK"] == "<mapping>"
    # The keys the design was silent about keep the layer that did write them.
    assert provenance["TEST_FROM_SCL"] == "<scl>"


def test_a_variable_nobody_set_is_attributed_to_nothing(tiny_pdk, tmp_path):
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    # Absence is how a caller reads "default": an entry here would name a
    # source that supplied no value at all.
    assert "TEST_UNSET" not in provenance


def test_the_layers_of_a_document_are_attributed_separately(tiny_pdk, tmp_path):
    """
    The document's own ``with`` block and one job's are two layers. A job that
    sets a variable must not make every value the document supplied read as
    though the job had supplied it.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x"},
        tmp_path,
        flow_values={"TEST_FROM_PDK": "from the document"},
        job_values=("left", {"TEST_FROM_SCL": "from the job"}),
    )

    assert provenance["TEST_FROM_PDK"] == "<flow document>"
    assert provenance["TEST_FROM_SCL"] == "<flow document: left>"


def test_a_command_line_override_outranks_every_other_layer(tiny_pdk, tmp_path):
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_FROM_PDK": "from the design"},
        tmp_path,
        config_override_strings=["TEST_FROM_PDK=from the command line"],
    )

    assert provenance["TEST_FROM_PDK"] == "<command line>"


def test_a_copied_configuration_keeps_what_it_did_not_override(tiny_pdk, tmp_path):
    """
    ``Config.copy`` is a shallow copy, so a key it leaves alone still came
    from wherever it came from. One it overrides did not: naming the old layer
    would attribute a value that layer never wrote.
    """
    from librelane.config import Config

    resolved, _ = Config.load(
        {"DESIGN_NAME": "x"},
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=tiny_pdk,
    )

    copied = resolved.copy(TEST_FROM_PDK="from the API")

    assert copied.provenance["TEST_FROM_PDK"] == "<override>"
    assert copied.provenance["TEST_FROM_SCL"] == "<scl>"


def test_provenance_cannot_be_written_through(tiny_pdk, tmp_path):
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    with pytest.raises(TypeError):
        provenance["TEST_FROM_PDK"] = "somewhere else"  # type: ignore[index]


def test_a_key_the_migration_renamed_keeps_the_layer_that_wrote_its_input(
    tiny_pdk, tmp_path
):
    """
    ``migrate_old_config`` renames ``TECH_LEF`` to ``TECH_LEFS``, and every
    openlane-era PDK reaches that migration -- it is why it exists. Attributing
    the old name and then dropping it for not surviving leaves the surviving
    key looking like a default, so a user asking where ``TECH_LEFS`` came from
    is sent hunting for a declared default to change when the PDK set it.
    """
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TECH_LEFS"] == "<pdk>"


def test_a_renamed_key_is_credited_to_the_layer_whose_file_supplied_it(
    tiny_pdk, tmp_path
):
    """
    The same rename, one layer down. ``SYNTH_TIEHI_PORT`` is written by the
    standard cell library, so ``SYNTH_TIEHI_CELL`` is the SCL's and not the
    PDK's. Flooring every unattributed key to ``<pdk>`` would get this one
    wrong, which is why the attribution is made across the migration rather
    than after it.
    """
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["SYNTH_TIEHI_CELL"] == "<scl>"


def test_a_key_the_migration_synthesised_is_attributed_to_the_pdk(tiny_pdk, tmp_path):
    """
    ``CELL_VERILOG_MODELS`` is globbed out of the PDK tree rather than written
    by any ``.tcl`` file, so it has no old name to be attributed under and is
    the PDK layer's by construction.
    """
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["CELL_VERILOG_MODELS"] == "<pdk>"


def test_a_design_value_still_outranks_a_renamed_pdk_key(tiny_pdk, tmp_path):
    """
    Attributing across the migration must not make the PDK layer outrank the
    design: the map is seeded from the PDK and then written over by every
    source layered after it.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "SYNTH_TIEHI_CELL": "from the design"},
        tmp_path,
    )

    assert provenance["SYNTH_TIEHI_CELL"] == "<mapping>"


def test_every_key_the_pdk_layers_produced_is_attributed(tiny_pdk):
    """
    A totality guard rather than a list of the six renames
    ``migrate_old_config`` performs and the six keys it synthesises. A rename
    added later would silently drop its key's origin again, and the symptom --
    a value that reads as ``default`` when the PDK set it -- is invisible until
    somebody asks.

    Reaches for the private method because the invariant is that method's, and
    no public surface exposes the whole PDK environment before validation drops
    the keys no flow variable claims.
    """
    from librelane.config.config import Config

    environment, _, _, _, origins = Config._Config__get_pdk_raw(
        tiny_pdk, "tiny", "tiny_scl", None
    )

    assert set(environment) - set(origins) == set()
