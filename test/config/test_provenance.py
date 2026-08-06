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
    # A variable a design writes inside a 'pdk::'/'scl::' block. The block is a
    # section of the file that carried it and not a layer of its own, so the
    # file is what an origin has to name.
    Variable("TEST_SCOPED", Optional[str], description="x"),
    # The three shapes ``migrate_old_config`` produces: a key it renames from
    # one the PDK wrote, one it renames from a key the SCL wrote, and one it
    # synthesises from the PDK tree. None of the three exists under the name
    # the ``.tcl`` files used, so an attribution recorded under that name
    # describes nothing that survives into the configuration.
    Variable("TECH_LEFS", dict[str, Path], description="x", pdk=True),
    Variable("SYNTH_TIEHI_CELL", str, description="x", pdk=True),
    Variable("CELL_VERILOG_MODELS", Optional[list[Path]], description="x", pdk=True),
    # The design layer's own renames. 'flow_common_variables' carries twenty-odd
    # deprecated aliases and an openlane-era design configuration is exactly the
    # one that still uses them, so this is the layer a user edits.
    #
    # TEST_RENAMED is also written by the PDK, which is the harder case: the
    # origin does not go missing, it names a real layer that did not supply the
    # value. TEST_RENAMED_UNSET is the case where it goes missing instead.
    Variable(
        "TEST_RENAMED",
        str,
        description="x",
        pdk=True,
        deprecated_names=["TEST_RENAMED_LEGACY"],
    ),
    Variable(
        "TEST_RENAMED_UNSET",
        Optional[str],
        description="x",
        deprecated_names=["TEST_RENAMED_UNSET_LEGACY"],
    ),
    Variable(
        "TEST_TRANSLATED",
        Optional[int],
        description="x",
        deprecated_names=[("TEST_TRANSLATED_LEGACY", lambda value: int(value) * 2)],
    ),
    # The PDK layer's own renames, which are a second pass entirely: 'compile'
    # reads a variable's deprecated names off the merged PDK environment, and
    # a real PDK reaches it constantly -- sky130A writes FP_WELLTAP_CELL,
    # CELLS_LEF, MAGIC_TECH_FILE and the nineteen FP_PDN_* names.
    #
    # TEST_PDK_RENAMED is the missing-origin half. TEST_PDK_ALIAS_LAYERED is
    # the wrong-origin half: the SCL writes the deprecated name, so its value
    # is the one that wins, while the PDK's entry for the current name is the
    # one an attribution recorded before the rename would report.
    Variable(
        "TEST_PDK_RENAMED",
        str,
        description="x",
        pdk=True,
        deprecated_names=["TEST_PDK_RENAMED_LEGACY"],
    ),
    Variable(
        "TEST_PDK_ALIAS_LAYERED",
        str,
        description="x",
        pdk=True,
        deprecated_names=["TEST_PDK_ALIAS_LAYERED_LEGACY"],
    ),
    # DIODE_INSERTION_STRATEGY is not a rename but a migration of one key into
    # three, and it is the one an openlane-era configuration is most likely to
    # carry, since the docs have a section on migrating it.
    Variable("GRT_REPAIR_ANTENNAS", bool, description="x", default=False),
    Variable("RUN_HEURISTIC_DIODE_INSERTION", bool, description="x", default=False),
    Variable("DIODE_ON_PORTS", str, description="x", default="none"),
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

    ``TEST_PDK_RENAMED_LEGACY`` and ``TEST_PDK_ALIAS_LAYERED_LEGACY`` are
    deprecated names, written here rather than their current ones because a
    fixture that only ever writes a current name cannot exercise the PDK-side
    alias path at all -- and that is the path that loses forty-two keys'
    origins on a real PDK.

    Every PDK variable in :data:`_VARIABLES` is written by one of the two
    files, which is what makes the totality guard over ``__get_pdk_config``
    meaningful: a variable nobody writes resolves to its declared default and
    would rightly have no origin.

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
            set ::env(TEST_RENAMED) "from the pdk"
            set ::env(TEST_PDK_RENAMED_LEGACY) "from the pdk"
            set ::env(TEST_PDK_ALIAS_LAYERED) "from the pdk"
            """
        )
    )
    (librelane_dir / "tiny_scl" / "config.tcl").write_text(
        textwrap.dedent(
            """\
            set ::env(TEST_FROM_SCL) "from the scl"
            set ::env(TEST_LAYERED) "from the scl"
            set ::env(SYNTH_TIEHI_PORT) "tiny_conb_1 HI"
            set ::env(TEST_PDK_ALIAS_LAYERED_LEGACY) "from the scl"
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
    return _resolve(tiny_pdk, design, tmp_path, **load).provenance


def _resolve(tiny_pdk, design, tmp_path, **load):
    """
    The same call as :func:`_provenance`, returning the whole configuration
    for the tests that assert on a value as well as on where it came from.

    Returns
    -------
    librelane.config.Config
        The resolved configuration.
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
    return resolved


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


def test_an_iteration_value_outranks_the_design(tiny_pdk, tmp_path):
    """
    A loop's or a sweep's schedule is the one layer that does not honour
    design-always-wins: it is the loop's algorithm, declared once in the flow
    document, and a design that pinned the scheduled variable must not
    silently flatten the schedule to one fixed value.
    """
    resolved = _resolve(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_FROM_PDK": "from the design"},
        tmp_path,
        iteration_values=("sta", 2, {"TEST_FROM_PDK": "from iteration 2"}),
    )

    assert resolved["TEST_FROM_PDK"] == "from iteration 2"
    assert resolved.provenance["TEST_FROM_PDK"] == "<flow document: sta, iteration 2>"


def test_a_command_line_override_outranks_an_iteration_value(tiny_pdk, tmp_path):
    resolved = _resolve(
        tiny_pdk,
        {"DESIGN_NAME": "x"},
        tmp_path,
        iteration_values=("sta", 2, {"TEST_FROM_PDK": "from iteration 2"}),
        config_override_strings=["TEST_FROM_PDK=from the command line"],
    )

    assert resolved["TEST_FROM_PDK"] == "from the command line"
    assert resolved.provenance["TEST_FROM_PDK"] == "<command line>"


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
    A totality guard rather than a list of the renames ``migrate_old_config``
    performs, the keys it synthesises and the deprecated names ``compile``
    reads. A rename added later would silently drop its key's origin again, and
    the symptom -- a value that reads as ``default`` when the PDK set it -- is
    invisible until somebody asks.

    Asserted over ``__get_pdk_config``'s output rather than ``__get_pdk_raw``'s
    because ``compile`` renames a second time, in between the two: an
    assertion on the raw environment cannot see the pass that consumed
    forty-two of sky130A's keys. The fixture writes every PDK variable, so a
    key without an origin here is one whose origin was lost and not one that
    was never set.

    Reaches for the private method because the invariant is that method's: no
    public surface returns the PDK layers' contribution on its own, separate
    from the design layered over it.
    """
    from librelane.config.config import Config

    processed, _, _, _, origins = Config._Config__get_pdk_config(
        "tiny",
        "tiny_scl",
        None,
        tiny_pdk,
        [variable for variable in _VARIABLES if variable.pdk],
    )

    assert set(processed) - set(origins) == set()


def test_a_pdk_value_under_a_deprecated_name_is_attributed_to_the_pdk(
    tiny_pdk, tmp_path
):
    """
    ``compile`` prefers a variable's deprecated names over its current one, so
    a PDK writing ``FP_WELLTAP_CELL`` supplies ``WELLTAP_CELL``. Attributing
    under the name the ``.tcl`` file wrote leaves the surviving key with no
    origin, and absence is how ``default`` is spelled -- so
    ``--explain-variables`` prints a path inside the PDK tree and calls it a
    default.
    """
    provenance = _provenance(tiny_pdk, {"DESIGN_NAME": "x"}, tmp_path)

    assert provenance["TEST_PDK_RENAMED"] == "<pdk>"


def test_the_current_pdk_name_outranks_a_deprecated_one_in_the_map_too(
    tiny_pdk, tmp_path
):
    """
    The SCL writes the deprecated name and the PDK the current one. Since the
    PDK layer moved onto the same model-based validation as the design layer,
    one precedence rule holds everywhere: the current name wins, and the map
    names the layer that wrote it. (Variable.compile used to invert this at
    the PDK layer only, preferring the deprecated name.) Real openlane-era
    PDKs write only the old names, which pdk_compat migrates before this
    question can arise.
    """
    from librelane.config import Config

    resolved, _ = Config.load(
        {"DESIGN_NAME": "x"},
        _VARIABLES,
        design_dir=str(tmp_path),
        pdk="tiny",
        pdk_root=tiny_pdk,
    )

    assert resolved["TEST_PDK_ALIAS_LAYERED"] == "from the pdk"
    assert resolved.provenance["TEST_PDK_ALIAS_LAYERED"] == "<pdk>"


def test_a_design_value_under_a_deprecated_name_is_attributed_to_the_design(
    tiny_pdk, tmp_path
):
    """
    ``translate_deprecated_names`` renames the design layer's keys and the
    value wins, so the origin has to move with it. Leaving the origin under the
    dead name does not merely lose it here: the PDK also writes
    ``TEST_RENAMED``, so the map names a layer that did not supply the value,
    which is harder for a user to disbelieve than being told ``default``.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_RENAMED_LEGACY": "from the design"},
        tmp_path,
    )

    assert provenance["TEST_RENAMED"] == "<mapping>"


def test_a_renamed_design_value_no_other_layer_wrote_is_not_a_default(
    tiny_pdk, tmp_path
):
    """
    The same rename where no other layer writes the current name. The origin
    goes missing rather than being wrong, and absence is how ``default`` is
    spelled -- so a user is told nobody set a value they set themselves.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_RENAMED_UNSET_LEGACY": "from the design"},
        tmp_path,
    )

    assert provenance["TEST_RENAMED_UNSET"] == "<mapping>"


def test_an_origin_follows_a_value_the_rename_also_transformed(tiny_pdk, tmp_path):
    """
    A deprecated name may carry a translation function, so the value under the
    current name is not the one the design wrote. The design still wrote it.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "TEST_TRANSLATED_LEGACY": 21},
        tmp_path,
    )

    assert provenance["TEST_TRANSLATED"] == "<mapping>"


def test_the_keys_a_migration_synthesises_are_attributed_to_what_it_read(
    tiny_pdk, tmp_path
):
    """
    ``DIODE_INSERTION_STRATEGY`` is migrated into three keys inside
    ``validate_mapping``, one layer deeper than the rename above. All three owe
    their values to the design.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x", "DIODE_INSERTION_STRATEGY": 3},
        tmp_path,
    )

    assert provenance["GRT_REPAIR_ANTENNAS"] == "<mapping>"
    assert provenance["RUN_HEURISTIC_DIODE_INSERTION"] == "<mapping>"
    assert provenance["DIODE_ON_PORTS"] == "<mapping>"


def test_a_command_line_override_under_a_deprecated_name_keeps_its_origin(
    tiny_pdk, tmp_path
):
    """
    The rename is a property of the key, not of the layer that wrote it, so
    whichever layer the deprecated name came from is the one the current name
    belongs to.
    """
    provenance = _provenance(
        tiny_pdk,
        {"DESIGN_NAME": "x"},
        tmp_path,
        config_override_strings=["TEST_RENAMED_LEGACY=from the command line"],
    )

    assert provenance["TEST_RENAMED"] == "<command line>"


def test_every_value_the_design_supplied_is_attributed_to_the_design(
    tiny_pdk, tmp_path
):
    """
    A totality guard over the design layer, covering ``__load_dict`` rather
    than ``__get_pdk_raw``. It reads the aliases off the variable list instead
    of naming them, so an alias added later is covered without being listed --
    and a rename whose origin is dropped shows up as the PDK's, or as a
    default, for a value the design set.
    """
    aliases = {
        (item if isinstance(item, str) else item[0]): variable.name
        for variable in _VARIABLES
        for item in variable.deprecated_names
    }
    assert aliases, "the fixture list must carry aliases for this to guard anything"

    design = {"DESIGN_NAME": "x"}
    for alias in aliases:
        design[alias] = 1 if alias == "TEST_TRANSLATED_LEGACY" else "from the design"

    provenance = _provenance(tiny_pdk, design, tmp_path)

    assert {
        current: provenance.get(current, "<<ABSENT -- reads as default>>")
        for current in aliases.values()
    } == {current: "<mapping>" for current in aliases.values()}


def _yaml_source(path, body):
    """
    Parameters
    ----------
    path : pathlib.Path
        Where to write the file.
    body : str
        Its contents, dedented before writing.

    Returns
    -------
    str
        The path as :meth:`librelane.config.Config.load` takes it, which is
        also the name it attributes the file's keys to.
    """
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_a_value_from_a_scoped_section_is_attributed_to_the_file(tiny_pdk, tmp_path):
    """
    ``pdk::``/``scl::`` sections are the common idiom -- the shipped spm
    configuration writes four of them -- and a key promoted out of one belongs
    to the file that carried the section. Attributing under the section's own
    key instead leaves the promoted key with no origin, and absence is how
    ``default`` is spelled, so a user is told nobody set a value their own file
    sets.
    """
    resolved = _resolve(
        tiny_pdk,
        {
            "DESIGN_NAME": "x",
            "pdk::tiny": {"TEST_SCOPED": "from the section"},
        },
        tmp_path,
    )

    assert resolved["TEST_SCOPED"] == "from the section"
    assert resolved.provenance["TEST_SCOPED"] == "<mapping>"


def test_a_deprecated_name_inside_a_scoped_section_keeps_its_origin(tiny_pdk, tmp_path):
    """
    The two migrations compose: the key is promoted out of the section under
    the name the file wrote, and the rename then moves both the value and the
    origin onto the current name.
    """
    resolved = _resolve(
        tiny_pdk,
        {
            "DESIGN_NAME": "x",
            "scl::tiny_scl": {"TEST_RENAMED_UNSET_LEGACY": "from the section"},
        },
        tmp_path,
    )

    assert resolved["TEST_RENAMED_UNSET"] == "from the section"
    assert resolved.provenance["TEST_RENAMED_UNSET"] == "<mapping>"


def test_a_command_line_override_beats_a_scoped_section(tiny_pdk, tmp_path):
    """
    The shipped spm configuration's shape: a key written both at the top level
    and inside a matching ``pdk::`` block. An override lands on the existing
    top-level key and so keeps its position, above the section -- and expanding
    the section over the merged mapping then overwrites it. The user is given
    neither the value they asked for nor an origin that admits it.
    """
    resolved = _resolve(
        tiny_pdk,
        {
            "DESIGN_NAME": "x",
            "TEST_SCOPED": "from the top level",
            "pdk::tiny": {"TEST_SCOPED": "from the section"},
        },
        tmp_path,
        config_override_strings=["TEST_SCOPED=from the command line"],
    )

    assert resolved["TEST_SCOPED"] == "from the command line"
    assert resolved.provenance["TEST_SCOPED"] == "<command line>"


def test_a_scoped_section_beats_its_own_files_top_level_value(tiny_pdk, tmp_path):
    """
    Within one file the section wins wherever it is written. Every shipped
    configuration puts its sections last, so this is only observable when one
    is moved -- which is exactly when a silent change of meaning is worst.
    """
    resolved = _resolve(
        tiny_pdk,
        {
            "DESIGN_NAME": "x",
            "pdk::tiny": {"TEST_SCOPED": "from the section"},
            "TEST_SCOPED": "from the top level",
        },
        tmp_path,
    )

    assert resolved["TEST_SCOPED"] == "from the section"
    assert resolved.provenance["TEST_SCOPED"] == "<mapping>"


def test_a_later_files_plain_value_beats_an_earlier_files_scoped_one(
    tiny_pdk, tmp_path
):
    """
    Precedence between two sources is the order they were given in, and a
    section is not a way for an earlier file to outrank a later one. Expanding
    sections over the merged mapping decides this by where the merge happened
    to put each key instead.
    """
    first = _yaml_source(
        tmp_path / "first.yaml",
        """\
        DESIGN_NAME: x
        TEST_SCOPED: from the first file
        pdk::tiny:
          TEST_SCOPED: from the first file's section
        """,
    )
    second = _yaml_source(
        tmp_path / "second.yaml",
        """\
        TEST_SCOPED: from the second file
        """,
    )

    resolved = _resolve(tiny_pdk, [first, second], tmp_path)

    assert resolved["TEST_SCOPED"] == "from the second file"
    assert resolved.provenance["TEST_SCOPED"] == second


def test_a_section_matching_neither_the_pdk_nor_the_scl_is_dropped(tiny_pdk, tmp_path):
    resolved = _resolve(
        tiny_pdk,
        {
            "DESIGN_NAME": "x",
            "TEST_SCOPED": "from the top level",
            "pdk::other": {"TEST_SCOPED": "from another pdk"},
            "scl::other_scl": {"TEST_UNSET": "from another scl"},
        },
        tmp_path,
    )

    assert resolved["TEST_SCOPED"] == "from the top level"
    assert resolved["TEST_UNSET"] is None
    assert "TEST_UNSET" not in resolved.provenance
