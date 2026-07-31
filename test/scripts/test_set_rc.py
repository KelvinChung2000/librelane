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
"""``common/set_rc.tcl`` run against the stubs in ``conftest.py``.

Issue 996. ``set_layer_rc`` reads its arguments in whatever units the embedded
OpenSTA is in. The signoff scripts pin those with ``set_cmd_units``; the PnR
scripts, which are fifteen of the sixteen places this file is sourced from, do
not. So the same ``LAYERS_RC`` dictionary has to mean the same thing under both.
"""

import pytest


def run_set_rc(stubs):
    stubs.interpreter.eval("set ::env(_LAYER_RC_0) {nom_tt met1 0.1 0.2}")
    stubs.interpreter.eval("set ::env(_VIA_R_0) {nom_tt via1 0.5}")
    stubs.source("common/set_rc.tcl")
    return stubs.stored


def stored_for(records, corner, **match):
    [record] = [
        item
        for item in records
        if item["corner"] == corner
        and all(item.get(key) == value for key, value in match.items())
    ]
    return record


@pytest.fixture
def both_unit_systems(openroad_stubs, unit_systems):
    """The same configuration, once under the units signoff pins and once under
    a liberty file that declares ohm rather than kOhm."""
    return tuple(run_set_rc(openroad_stubs(units)) for units in unit_systems)


def test_custom_layer_rc_does_not_depend_on_the_liberty_resistance_unit(
    both_unit_systems,
):
    """0.1 kOhm/um is 1e8 ohm/m no matter what the liberty file says.

    Before the fix the value was handed to ``set_layer_rc`` verbatim, so under a
    liberty declaring ohm it was stored as 1e5 ohm/m, a thousand times too
    small.
    """
    signoff, ohm_liberty = both_unit_systems

    assert stored_for(signoff, "nom_tt", layer="met1")["resistance"] == pytest.approx(
        1e8
    )
    assert stored_for(ohm_liberty, "nom_tt", layer="met1")[
        "resistance"
    ] == pytest.approx(1e8)


def test_custom_layer_capacitance_does_not_depend_on_the_liberty_units(
    both_unit_systems,
):
    """0.2 pF/um is 2e-7 F/m. Both PDKs in tree already declare pF, so this one
    holds either way; it is here so that the capacitance conversion cannot be
    dropped without a failure."""
    signoff, ohm_liberty = both_unit_systems

    assert stored_for(signoff, "nom_tt", layer="met1")["capacitance"] == pytest.approx(
        2e-7
    )
    assert stored_for(ohm_liberty, "nom_tt", layer="met1")[
        "capacitance"
    ] == pytest.approx(2e-7)


def test_custom_via_resistance_does_not_depend_on_the_liberty_resistance_unit(
    both_unit_systems,
):
    """``VIAS_R`` is per cut rather than per unit length, but had the same
    defect."""
    signoff, ohm_liberty = both_unit_systems

    assert stored_for(signoff, "nom_tt", via="via1")["resistance"] == pytest.approx(500)
    assert stored_for(ohm_liberty, "nom_tt", via="via1")["resistance"] == pytest.approx(
        500
    )


def test_the_two_unit_systems_now_store_identical_values(both_unit_systems):
    """Not merely close. Every value the script applies, custom and fallback
    alike, comes out the same to the last bit under both."""
    signoff, ohm_liberty = both_unit_systems

    def values(records):
        return [
            (record.get("layer"), record.get("via"), record["corner"])
            + (record["resistance"], record.get("capacitance"))
            for record in records
        ]

    assert values(signoff) == values(ohm_liberty)


def test_a_kohm_pf_um_liberty_stores_exactly_what_it_did_before(
    openroad_stubs, unit_systems, as_stored
):
    """The safety half of the fix, and the reason it is not a flow change for
    any PDK that was already correct.

    ``LAYERS_RC`` is a PDK variable, so a fix that moved sky130 would move every
    design on it. The resistance factor is exactly 1.0 here. The capacitance and
    distance factors are not, because OpenSTA holds pF and um at single
    precision, but they are off by a few parts in a thousand million and the
    layer RC store is itself a float, so the value that lands in it is
    unchanged.
    """
    units = unit_systems[0]
    stored = run_set_rc(openroad_stubs(units))

    def passed_verbatim(value, unit):
        return as_stored(value * units[unit] / units["distance"])

    layer = stored_for(stored, "nom_tt", layer="met1")
    assert layer["resistance"] == passed_verbatim(0.1, "resistance")
    assert layer["capacitance"] == passed_verbatim(0.2, "capacitance")
    assert stored_for(stored, "nom_tt", via="via1")["resistance"] == as_stored(
        0.5 * units["resistance"]
    )


def test_the_tech_lef_fallback_round_trips_whatever_odb_holds(both_unit_systems):
    """The fallback path reads odb in SI and scales it into the active units, so
    it is already correct in both unit systems. Pinned because the other
    candidate fix for 996, dropping that scaling, would break it."""
    for records in both_unit_systems:
        fallback = stored_for(records, "nom_ss", layer="met1")
        assert fallback["resistance"] == pytest.approx(1.5e8)
        assert fallback["capacitance"] == pytest.approx(3e-7)
        assert stored_for(records, "nom_ss", via="via1")["resistance"] == pytest.approx(
            12.0
        )


def test_every_override_names_a_corner(both_unit_systems):
    """Which is why the odb layer store is never written: ``set_layer_rc`` only
    updates it when ``-corner`` is absent. ``dump_rc.tcl`` relies on this."""
    for records in both_unit_systems:
        assert all("-corner" in record["arguments"] for record in records)
