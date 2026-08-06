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
"""Enough of OpenROAD, in a bare Tcl interpreter, to run the RC scripts.

``common/set_rc.tcl`` and ``dump_rc.tcl`` are the two places where LibreLane
decides what the ``LAYERS_RC`` and ``VIAS_R`` numbers mean, and both are
sensitive to the units the embedded OpenSTA happens to be in. Neither needs a
design, a PDK or a router to exercise that: they need ``set_layer_rc``, a
handful of ``est::`` accessors and a technology database to read defaults from.

The stubs below model those faithfully enough for the units to be checked.
``set_layer_rc`` in particular converts its arguments out of the active user
interface units and into SI before storing them, exactly as OpenROAD does::

    set res [expr [sta::resistance_ui_sta $res] / [sta::distance_ui_sta 1.0]]

so what the tests assert on is the ohm/m and F/m OpenROAD would end up with,
which is the only figure that affects RC estimation.

The scale factors and the single-precision storage below were measured against
the pinned OpenROAD, ``dcf3613`` of 2026-02-17, rather than assumed.
"""

import pathlib
import statistics
import struct
import tkinter

import pytest

SCRIPTS = (
    pathlib.Path(__file__).parent.parent.parent / "librelane" / "scripts" / "openroad"
)

# SI units per user interface unit, i.e. what ``sta::unit_scale`` returns.
#
# The signoff scripts under ``scripts/openroad/sta/`` pin these with
# ``set_cmd_units -resistance kOhm -capacitance pF -distance um``. The PnR
# scripts never call ``set_cmd_units``, so there they are whatever the first
# liberty file declared. sky130's liberty declares kohm and pF, which is why
# the two have always agreed there; gf180mcu's declares ohm, which is where
# issue 996 was found.
#
# These are the numbers OpenSTA really reports, not their nominal values:
# it holds pF and um at single precision, so they are not exactly 1e-12 and
# 1e-6. Anything asserting that the fix leaves an already-correct PDK alone has
# to work with the real figures.
LIBRELANE_STANDARD_UNITS = {
    "resistance": 1000.0,
    "capacitance": 9.999999960041972e-13,
    "distance": 9.999999974752427e-7,
}
OHM_LIBERTY_UNITS = dict(LIBRELANE_STANDARD_UNITS, resistance=1.0)


def as_stored(value):
    """Round as OpenROAD's layer RC store does, to single precision.

    Reading 892857.1428571428 ohm/m back out of odb gives 892857.125, so the
    store is a float rather than a double. It matters here because it is well
    coarser than the difference between the scale factors above and their
    nominal values.
    """
    return struct.unpack("f", struct.pack("f", value))[0]


# ``sta::parse_key_args`` has to be written in Tcl because it reaches into its
# caller's frame. Only the flags matter to the scripts under test.
_PARSE_KEY_ARGS = """
namespace eval sta {
    proc parse_key_args {name args_var keys_var keys_list flags_var flags_list} {
        upvar 1 $args_var arguments
        upvar 1 $flags_var flags
        foreach flag $flags_list {
            if { [lsearch $arguments $flag] != -1 } {
                set flags($flag) 1
            }
        }
    }
}
"""


def _options(arguments):
    return dict(zip(arguments[::2], arguments[1::2]))


class OpenROADStubs:
    """A Tcl interpreter carrying stubbed OpenROAD commands.

    ``routing_layers`` are ``(name, direction, resistance, capacitance)`` and
    ``cut_layers`` are ``(name, resistance)``, both in SI units, because that is
    how odb holds the technology LEF values.
    """

    def __init__(self, units, corners, routing_layers, cut_layers):
        self.units = units
        self.corners = list(corners)
        self.routing_layers = list(routing_layers)
        self.cut_layers = list(cut_layers)
        self.stored = []
        self.output = []
        # What ``set_layer_rc -corner`` writes and the ``est::layer_*``
        # accessors read back, keyed by corner and layer name, in SI units.
        self.corner_rc = {}

        self.interpreter = tkinter.Tcl()
        self.interpreter.eval(_PARSE_KEY_ARGS)
        self._install_layers()
        self._install_commands()
        self.interpreter.eval("set ::env(SET_RC_VERBOSE) 0")

    # -- technology database ------------------------------------------------

    def _install_layers(self):
        self.handles = {}
        for name, direction, _, _ in self.routing_layers:
            self.handles[name] = self._make_layer(name, direction, 0.0)
        for name, resistance in self.cut_layers:
            self.handles[name] = self._make_layer(name, "CUT", resistance)

    def _make_layer(self, name, direction, resistance):
        properties = {
            "getName": name,
            "getDirection": direction,
            "getResistance": resistance,
        }
        handle = f"layer::{name}"
        self.interpreter.createcommand(handle, lambda method: properties[method])
        return handle

    def _name_of(self, handle):
        return handle.rsplit("::", 1)[1]

    def _get_layers(self, *arguments):
        keyword = "-type" if "-type" in arguments else "-types"
        kind = arguments[arguments.index(keyword) + 1]
        names = (
            [name for name, _, _, _ in self.routing_layers]
            if kind == "ROUTING"
            else [name for name, _ in self.cut_layers]
        )
        if "-map" in arguments:
            return tuple(names)
        return tuple(self.handles[name] for name in names)

    def _dblayer_wire_rc(self, handle):
        name = self._name_of(handle)
        return next(
            (resistance, capacitance)
            for layer, _, resistance, capacitance in self.routing_layers
            if layer == name
        )

    # -- set_layer_rc -------------------------------------------------------

    def _set_layer_rc(self, *arguments):
        options = _options(arguments)
        record = {"corner": options["-corner"], "arguments": options}
        if "-via" in options:
            record["via"] = options["-via"]
            # ohm per cut
            record["resistance"] = as_stored(
                float(options["-resistance"]) * self.units["resistance"]
            )
            self.corner_rc[options["-corner"], options["-via"]] = (
                record["resistance"],
                0.0,
            )
        else:
            record["layer"] = options["-layer"]
            # ohm/m and F/m
            record["resistance"] = as_stored(
                float(options["-resistance"])
                * self.units["resistance"]
                / self.units["distance"]
            )
            record["capacitance"] = as_stored(
                float(options["-capacitance"])
                * self.units["capacitance"]
                / self.units["distance"]
            )
            self.corner_rc[options["-corner"], options["-layer"]] = (
                record["resistance"],
                record["capacitance"],
            )
        self.stored.append(record)

    def _layer_value(self, index):
        def accessor(handle, corner):
            return self.corner_rc[corner, self._name_of(handle)][index]

        return accessor

    def _wire_average(self, index):
        def accessor(corner):
            return statistics.fmean(
                self.corner_rc[corner, name][index]
                for name, _, _, _ in self.routing_layers
            )

        return accessor

    # -- reporting ----------------------------------------------------------

    def _puts(self, *arguments):
        self.output.append(arguments[-1])

    def _report_units(self):
        for unit, scale in sorted(self.units.items()):
            self.output.append(f"  {unit} {scale}")

    def reports(self):
        """The ``lln_report_begin``/``lln_report_end`` blocks the script
        emitted, by name. The stubs installed by :meth:`stub_io_tcl` mark the
        boundaries in the output stream."""
        collected = {}
        current = None
        for line in self.output:
            if line.startswith("__LLN_REPORT_BEGIN__ "):
                current = line.split(None, 1)[1]
                collected[current] = []
            elif line == "__LLN_REPORT_END__":
                current = None
            elif current is not None:
                collected[current].append(line)
        return collected

    def _install_commands(self):
        create = self.interpreter.createcommand
        create("sta::unit_scale", lambda name: self.units[name])
        create("lln::get_corner_names", lambda: tuple(self.corners))
        create(
            "lln::get_corner_dict",
            lambda: tuple(item for corner in self.corners for item in (corner, corner)),
        )
        create("get_layers", self._get_layers)
        create("est::dblayer_wire_rc", self._dblayer_wire_rc)
        create("est::layer_resistance", self._layer_value(0))
        create("est::layer_capacitance", self._layer_value(1))
        create("est::wire_signal_resistance", self._wire_average(0))
        create("est::wire_signal_capacitance", self._wire_average(1))
        create("est::wire_clk_resistance", self._wire_average(0))
        create("est::wire_clk_capacitance", self._wire_average(1))
        create("set_layer_rc", self._set_layer_rc)
        create("set_wire_rc", lambda *arguments: None)
        create("report_units", self._report_units)
        # Everything dump_rc.tcl does before it reaches the RC values.
        for name in ("read_pnr_libs", "read_lefs", "read_def", "set_global_vars"):
            create(name, lambda *arguments: None)

    def capture_output(self):
        self.interpreter.eval("rename puts {}")
        self.interpreter.createcommand("puts", self._puts)

    def stub_io_tcl(self):
        """Make ``source`` skip ``common/io.tcl`` and nothing else.

        ``io.tcl`` is the readers, and every one of them needs a live OpenROAD
        with a design in it. Whatever else a script sources, ``set_rc.tcl``
        included, is the real file.
        """

        def source(path):
            if path.endswith("common/io.tcl"):
                return ""
            return self.interpreter.eval(pathlib.Path(path).read_text(encoding="utf8"))

        self.interpreter.eval("rename source {}")
        self.interpreter.createcommand("source", source)
        # io.tcl's report redirection, reduced to boundary markers in the
        # captured output so reports() can carve the blocks back out.
        self.interpreter.createcommand(
            "lln_report_begin",
            lambda name: self.output.append(f"__LLN_REPORT_BEGIN__ {name}"),
        )
        self.interpreter.createcommand(
            "lln_report_tee_begin",
            lambda name: self.output.append(f"__LLN_REPORT_BEGIN__ {name}"),
        )
        self.interpreter.createcommand(
            "lln_report_end",
            lambda: self.output.append("__LLN_REPORT_END__"),
        )
        self.interpreter.eval(f"set ::env(SCRIPTS_DIR) {SCRIPTS.parent}")
        self.interpreter.eval("set ::env(CURRENT_DEF) design.def")

    def source(self, script):
        self.interpreter.eval((SCRIPTS / script).read_text(encoding="utf8"))


@pytest.fixture(name="as_stored")
def as_stored_fixture():
    return as_stored


@pytest.fixture
def unit_systems():
    """The units signoff pins, and the ones a liberty declaring ohm leaves
    behind under PnR."""
    return LIBRELANE_STANDARD_UNITS, OHM_LIBERTY_UNITS


@pytest.fixture
def openroad_stubs():
    """A two-corner technology with one routing layer and one cut layer.

    Only one corner is given custom RC values, so a single run covers both the
    ``LAYERS_RC`` path and the technology LEF fallback that fills in the rest.
    """

    def build(units):
        return OpenROADStubs(
            units=units,
            corners=("nom_tt", "nom_ss"),
            routing_layers=[("met1", "HORIZONTAL", 1.5e8, 3e-7)],
            cut_layers=[("via1", 12.0)],
        )

    return build
