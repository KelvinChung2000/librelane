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
import runpy
import sys
from types import SimpleNamespace
from unittest import mock

import click
import pytest


SCRIPT = "librelane/scripts/odbpy/power_utils.py"


def fake_mterm(name: str, sigtype: str):
    return SimpleNamespace(getName=lambda: name, getSigType=lambda: sigtype)


def load_design(monkeypatch, connections, pg_pins):
    """
    Builds a ``Design`` over a one-instance netlist, with the OpenROAD-only
    modules stubbed out.

    ``connections`` is the instance's Yosys connection dictionary, i.e. a map
    from port name to a list of bit indices. Yosys writes an empty list for a
    port that the Verilog leaves explicitly open, as in ``.VGND()``.
    """
    monkeypatch.setitem(
        sys.modules,
        "reader",
        SimpleNamespace(
            OdbReader=object,
            click_odb=lambda function: function,
            click=click,
            odb=None,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "odb", SimpleNamespace(dbMTerm=object, dbRegion=object)
    )
    monkeypatch.setitem(sys.modules, "utl", SimpleNamespace())

    master = SimpleNamespace(
        getMTerms=lambda: [fake_mterm(name, sigtype) for name, sigtype in pg_pins]
    )

    reader = mock.Mock()
    reader.block.getName.return_value = "top"
    reader.block.getNets.return_value = []
    reader.db.findMaster.return_value = master

    yosys_dict = {
        "modules": {
            "top": {
                "cells": {
                    "macro_instance": {
                        "type": "macro",
                        "connections": connections,
                    }
                },
                "netnames": {
                    "vccd1": {"bits": [2]},
                    "vssd1": {"bits": [3]},
                },
            }
        }
    }

    module = runpy.run_path(SCRIPT)
    return module["Design"](reader, yosys_dict)


PG_PINS = [("VPWR", "POWER"), ("VGND", "GROUND")]


def test_both_power_ground_ports_connected(monkeypatch):
    design = load_design(
        monkeypatch,
        {"VPWR": [2], "VGND": [3]},
        PG_PINS,
    )

    assert design.extract_pg_pins("top", "macro_instance") == (
        {"VPWR": "vccd1"},
        {"VGND": "vssd1"},
    )


def test_an_explicitly_open_power_ground_port_is_skipped(monkeypatch):
    """
    Upstream PR 991: a macro may legitimately have one of its power or ground
    ports left open, and Yosys writes that as an empty bit list. Treating it
    as an error aborts the whole flow.
    """
    design = load_design(
        monkeypatch,
        {"VPWR": [2], "VGND": []},
        PG_PINS,
    )

    assert design.extract_pg_pins("top", "macro_instance") == (
        {"VPWR": "vccd1"},
        {},
    )


def test_a_multi_bit_power_ground_port_is_still_an_error(monkeypatch):
    """A power pin driven by two bits is a genuinely malformed netlist."""
    design = load_design(
        monkeypatch,
        {"VPWR": [2, 3], "VGND": [3]},
        PG_PINS,
    )

    with pytest.raises(SystemExit):
        design.extract_pg_pins("top", "macro_instance")
