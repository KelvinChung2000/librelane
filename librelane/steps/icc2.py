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
Synopsys IC Compiler II (``icc2_shell``) step scaffolds.

IC Compiler II is Synopsys's place-and-route tool, positioned by Synopsys as
a separate product from Fusion Compiler rather than superseded by it; both
are marketed today. ``icc2_shell`` is confirmed as its invocation binary by
consistent naming across multiple tutorial/training sources, though (unlike
``dc_shell``) no source states the exact command-line flags it is invoked
with. No public source shows a native Python API for the digital ``icc2_shell``
flow (a "Python and Tcl programming support" claim exists for Synopsys's
separate Custom Design Platform, an analog/custom-layout environment, but
extending that claim to ``icc2_shell`` would be a guess this module does not
make). This module therefore builds on
:class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 13.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.state import DesignFormat

# Mirrors PNR_IN_PLACE_REQUIRES / PNR_IN_PLACE_PROVIDES in
# librelane/stages/stage.py: the view contract shared by every in-place
# place-and-route transform. Restated here rather than imported, because
# librelane.steps is the lower layer that librelane.stages is built on (no
# module under librelane/steps/ imports librelane.stages, and
# librelane/stages/providers.py imports librelane.steps at module load time,
# so importing the other way round here would invert that layering and risk
# a circular import).
_PNR_IN_PLACE_REQUIRES = [DesignFormat.DEF, DesignFormat.NETLIST, DesignFormat.SDC]
_PNR_IN_PLACE_PROVIDES = [DesignFormat.DEF, DesignFormat.NETLIST, DesignFormat.SDC]


class ICC2Step(VendorTclStep):
    """
    Base class shared by every IC Compiler II step.

    ``icc2_shell`` is confirmed as IC Compiler II's binary name (see the
    module docstring), but no public source states the flags it is invoked
    with: unlike Design Compiler's confirmed ``dc_shell -f script.tcl``,
    nothing here establishes whether ``icc2_shell`` follows that same
    ``-f``-style convention or something else (Cadence's own Tcl tools
    disagree with each other on this, per the research report, so the
    pattern cannot be assumed to carry over from either family).
    :meth:`get_command` therefore raises rather than guessing a flag.
    """

    binary: ClassVar[str] = "icc2_shell"
    script_dir: ClassVar[str] = "icc2"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: 'icc2_shell' is confirmed as IC "
            "Compiler II's invocation binary, but no public source "
            "establishes the command-line flags it is invoked with. "
            "Guessing a flag syntax here would look exactly as authoritative "
            "as a verified one; get_command() must be written by someone "
            "with icc2_shell access instead."
        )


class ICC2PNRStep(ICC2Step):
    """
    Shared input/output contract for the seventeen in-place place-and-route
    stages IC Compiler II covers (``floorplan`` through ``fill_insertion``).
    A concrete subclass need only set ``id``, ``name`` and
    ``script_filename``.
    """

    inputs = _PNR_IN_PLACE_REQUIRES
    outputs = _PNR_IN_PLACE_PROVIDES


@Step.factory.register()
class Floorplan(ICC2PNRStep):
    """
    Scaffold for the ``floorplan`` stage using IC Compiler II. Unimplemented;
    see ``librelane/scripts/icc2/floorplan.tcl``.
    """

    id = "ICC2.Floorplan"
    name = "Floorplan (ICC2)"
    script_filename: ClassVar[str] = "floorplan.tcl"

    # Unlike every later stage in this span, floorplan is where DEF and SDC
    # are produced for the first time, not carried in: the floorplan stage's
    # own contract requires only DesignFormat.NETLIST (see librelane/stages/
    # taxonomy.py), matching OpenROAD.Floorplan. Inheriting the base step's
    # inputs unmodified would claim DEF as an input the stage never promises,
    # which the registration-time view check correctly rejects.
    inputs = [DesignFormat.NETLIST]


@Step.factory.register()
class MacroPlacement(ICC2PNRStep):
    """
    Scaffold for the ``macro_placement`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/macro_placement.tcl``.
    """

    id = "ICC2.MacroPlacement"
    name = "Macro Placement (ICC2)"
    script_filename: ClassVar[str] = "macro_placement.tcl"


@Step.factory.register()
class TapcellInsertion(ICC2PNRStep):
    """
    Scaffold for the ``tapcell_insertion`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/tapcell.tcl``.
    """

    id = "ICC2.TapcellInsertion"
    name = "Tap/Endcap Insertion (ICC2)"
    script_filename: ClassVar[str] = "tapcell.tcl"


@Step.factory.register()
class PowerGrid(ICC2PNRStep):
    """
    Scaffold for the ``power_grid`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/pdn.tcl``.
    """

    id = "ICC2.PowerGrid"
    name = "Power Distribution Network (ICC2)"
    script_filename: ClassVar[str] = "pdn.tcl"


@Step.factory.register()
class IOPlacement(ICC2PNRStep):
    """
    Scaffold for the ``io_placement`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/ioplacer.tcl``.
    """

    id = "ICC2.IOPlacement"
    name = "I/O Placement (ICC2)"
    script_filename: ClassVar[str] = "ioplacer.tcl"


@Step.factory.register()
class GlobalPlacement(ICC2PNRStep):
    """
    Scaffold for the ``global_placement`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/gpl.tcl``.
    """

    id = "ICC2.GlobalPlacement"
    name = "Global Placement (ICC2)"
    script_filename: ClassVar[str] = "gpl.tcl"


@Step.factory.register()
class PostGPLRepair(ICC2PNRStep):
    """
    Scaffold for the ``post_gpl_repair`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/repair_design.tcl``.
    """

    id = "ICC2.PostGPLRepair"
    name = "Post-Global-Placement Design Repair (ICC2)"
    script_filename: ClassVar[str] = "repair_design.tcl"


@Step.factory.register()
class DetailedPlacement(ICC2PNRStep):
    """
    Scaffold for the ``detailed_placement`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/dpl.tcl``.
    """

    id = "ICC2.DetailedPlacement"
    name = "Detailed Placement (ICC2)"
    script_filename: ClassVar[str] = "dpl.tcl"


@Step.factory.register()
class CTS(ICC2PNRStep):
    """
    Scaffold for the ``cts`` stage using IC Compiler II. Unimplemented; see
    ``librelane/scripts/icc2/cts.tcl``.
    """

    id = "ICC2.CTS"
    name = "Clock Tree Synthesis (ICC2)"
    script_filename: ClassVar[str] = "cts.tcl"


@Step.factory.register()
class PostCTSOpt(ICC2PNRStep):
    """
    Scaffold for the ``post_cts_opt`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/rsz_timing_postcts.tcl``.
    """

    id = "ICC2.PostCTSOpt"
    name = "Post-CTS Timing Optimization (ICC2)"
    script_filename: ClassVar[str] = "rsz_timing_postcts.tcl"


@Step.factory.register()
class GlobalRouting(ICC2PNRStep):
    """
    Scaffold for the ``global_routing`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/grt.tcl``.
    """

    id = "ICC2.GlobalRouting"
    name = "Global Routing (ICC2)"
    script_filename: ClassVar[str] = "grt.tcl"


@Step.factory.register()
class PostGRTRepair(ICC2PNRStep):
    """
    Scaffold for the ``post_grt_repair`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/repair_design_postgrt.tcl``.
    """

    id = "ICC2.PostGRTRepair"
    name = "Post-Global-Routing Design Repair (ICC2)"
    script_filename: ClassVar[str] = "repair_design_postgrt.tcl"


@Step.factory.register()
class AntennaRepair(ICC2PNRStep):
    """
    Scaffold for the ``antenna_repair`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/antenna_repair.tcl``.
    """

    id = "ICC2.AntennaRepair"
    name = "Antenna Violation Repair (ICC2)"
    script_filename: ClassVar[str] = "antenna_repair.tcl"


@Step.factory.register()
class PostGRTOpt(ICC2PNRStep):
    """
    Scaffold for the ``post_grt_opt`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/rsz_timing_postgrt.tcl``.
    """

    id = "ICC2.PostGRTOpt"
    name = "Post-Global-Routing Timing Optimization (ICC2)"
    script_filename: ClassVar[str] = "rsz_timing_postgrt.tcl"


@Step.factory.register()
class DetailedRouting(ICC2PNRStep):
    """
    Scaffold for the ``detailed_routing`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/drt.tcl``.
    """

    id = "ICC2.DetailedRouting"
    name = "Detailed Routing (ICC2)"
    script_filename: ClassVar[str] = "drt.tcl"


@Step.factory.register()
class PostRouteOpt(ICC2PNRStep):
    """
    Scaffold for the ``post_route_opt`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/post_route_opt.tcl``.
    """

    id = "ICC2.PostRouteOpt"
    name = "Post-Route Optimization (ICC2)"
    script_filename: ClassVar[str] = "post_route_opt.tcl"


@Step.factory.register()
class FillInsertion(ICC2PNRStep):
    """
    Scaffold for the ``fill_insertion`` stage using IC Compiler II.
    Unimplemented; see ``librelane/scripts/icc2/fill.tcl``.
    """

    id = "ICC2.FillInsertion"
    name = "Fill Cell Insertion (ICC2)"
    script_filename: ClassVar[str] = "fill.tcl"


#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module: opt-in to a commercial provider must be a
#: separate, explicit step from importing this module. See
#: ``librelane/stages/providers.py`` for the shape this list mirrors.
#:
#: IC Compiler II carries a proprietary in-memory design database across
#: stages, the same way OpenROAD's live ``odb`` database does (sixteen of the
#: ``openroad`` provider's registrations in ``librelane/stages/providers.py``
#: declare ``native_views=(DesignFormat.odb,)`` for exactly that reason). No
#: public source establishes ICC2's database's view name or on-disk format
#: (see vendor-python-apis.md, section 13), so no ``DesignFormat`` is invented
#: for it here, and every registration below leaves ``native_views`` at its
#: default empty tuple. Declaring it, once someone with ``icc2_shell`` access
#: determines the real format, is the correct future change: it is the
#: mechanism that would let a real implementation pass a live database
#: between ICC2's own steps instead of re-reading DEF and every LEF at each
#: of the seventeen stage boundaries below.
REGISTRATIONS: list[dict] = [
    {
        "stage": "floorplan",
        "provider": "icc2",
        "steps": [Floorplan],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "macro_placement",
        "provider": "icc2",
        "steps": [MacroPlacement],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "tapcell_insertion",
        "provider": "icc2",
        "steps": [TapcellInsertion],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "power_grid",
        "provider": "icc2",
        "steps": [PowerGrid],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "io_placement",
        "provider": "icc2",
        "steps": [IOPlacement],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "global_placement",
        "provider": "icc2",
        "steps": [GlobalPlacement],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "post_gpl_repair",
        "provider": "icc2",
        "steps": [PostGPLRepair],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "detailed_placement",
        "provider": "icc2",
        "steps": [DetailedPlacement],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "cts",
        "provider": "icc2",
        "steps": [CTS],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "post_cts_opt",
        "provider": "icc2",
        "steps": [PostCTSOpt],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "global_routing",
        "provider": "icc2",
        "steps": [GlobalRouting],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "post_grt_repair",
        "provider": "icc2",
        "steps": [PostGRTRepair],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "antenna_repair",
        "provider": "icc2",
        "steps": [AntennaRepair],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "post_grt_opt",
        "provider": "icc2",
        "steps": [PostGRTOpt],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "detailed_routing",
        "provider": "icc2",
        "steps": [DetailedRouting],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "post_route_opt",
        "provider": "icc2",
        "steps": [PostRouteOpt],
        "namespaces": ("ICC2_",),
    },
    {
        "stage": "fill_insertion",
        "provider": "icc2",
        "steps": [FillInsertion],
        "namespaces": ("ICC2_",),
    },
]
