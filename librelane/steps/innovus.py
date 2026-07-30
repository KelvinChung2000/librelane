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
Cadence Innovus (``innovus``) step scaffolds.

Innovus is Cadence's place-and-route tool. For the classic product, no public
source shows a native Python API for it; Hammer's Cadence plugin
(``hammer/par/innovus/__init__.py``) generates a Tcl file and invokes it with
``innovus -nowin -common_ui -files <script>``, using no Python import or
``-python`` flag anywhere. Cadence markets a Python scripting mode for
"Innovus+", a newer unified platform that reportedly merges synthesis and
place-and-route; the only public wording found for it is an unfetchable white
paper snippet ("Innovus+ platform supports common database, TCL and Python
scripting, and GUI across the whole RTL synthesis and implementation flow").
That is existence-only marketing copy, not a module name, an entry point, or
evidence of an OpenDB-style object model, and it is recorded here as a gap
rather than acted on. This module builds on
:class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 3.

Innovus carries a proprietary in-memory design database across its own
place-and-route steps, the way ``openroad`` carries ``odb`` (declared as
``native_views=(DesignFormat.odb,)`` on sixteen of its registrations in
``librelane/stages/providers.py``). No public source establishes a
``DesignFormat`` for Innovus's database, so no ``native_views`` are declared
on any registration below, and none of these steps consumes one. Declaring
one, once its format is established, is the correct future change; inventing
a placeholder ``DesignFormat`` now would be exactly the kind of guess this
scaffold exists to avoid.
"""

from typing import ClassVar

from .step import Step
from .vendor import VendorTclStep
from ..stages.stage import PNR_IN_PLACE_PROVIDES, PNR_IN_PLACE_REQUIRES
from ..state import DesignFormat


class InnovusStep(VendorTclStep):
    """
    Base class shared by every Innovus step.

    ``innovus`` is Innovus's invocation binary, confirmed by Hammer's Cadence
    plugin, which is a real, currently-maintained production flow (UC
    Berkeley Chipyard's commercial tapeout path). It invokes Innovus as
    ``[innovus_bin, "-nowin", "-common_ui", "-files", par_tcl_filename]`` via
    ``run_executable()``. The shared base class behind that plugin
    (``hammer/cadence/tool.py``) only ever generates Tcl strings; there is no
    ``-python`` flag or API import anywhere in it.
    """

    binary: ClassVar[str] = "innovus"
    script_dir: ClassVar[str] = "innovus"

    def get_command(self) -> list[str]:
        return [self.binary, "-nowin", "-common_ui", "-files", self.get_script_path()]


@Step.factory.register()
class Floorplan(InnovusStep):
    """
    Scaffold for the ``floorplan`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/floorplan.tcl``. Mirrors
    ``librelane/scripts/openroad/floorplan.tcl``.
    """

    id = "Innovus.Floorplan"
    name = "Floorplanning (Innovus)"

    script_filename: ClassVar[str] = "floorplan.tcl"

    inputs = [DesignFormat.NETLIST, DesignFormat.SDC]
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class MacroPlacement(InnovusStep):
    """
    Scaffold for the ``macro_placement`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/macro_placement.tcl``. No
    OpenROAD Tcl counterpart exists: ``Odb.ManualMacroPlacement`` is a Python
    (odbpy) step, not a Tcl script.
    """

    id = "Innovus.MacroPlacement"
    name = "Macro Placement (Innovus)"

    script_filename: ClassVar[str] = "macro_placement.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    # Only the layout changes; nl and sdc pass through, matching
    # Odb.ManualMacroPlacement's contract.
    outputs = [DesignFormat.DEF]


@Step.factory.register()
class TapEndcapInsertion(InnovusStep):
    """
    Scaffold for the ``tapcell_insertion`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/tapcell.tcl``. Mirrors
    ``librelane/scripts/openroad/tapcell.tcl``.
    """

    id = "Innovus.TapEndcapInsertion"
    name = "Tap and Endcap Cell Insertion (Innovus)"

    script_filename: ClassVar[str] = "tapcell.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class PowerGrid(InnovusStep):
    """
    Scaffold for the ``power_grid`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/pdn.tcl``. Mirrors
    ``librelane/scripts/openroad/pdn.tcl``.
    """

    id = "Innovus.PowerGrid"
    name = "Power Distribution Network Generation (Innovus)"

    script_filename: ClassVar[str] = "pdn.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class IOPlacement(InnovusStep):
    """
    Scaffold for the ``io_placement`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/ioplacer.tcl``. Mirrors
    ``librelane/scripts/openroad/ioplacer.tcl``.
    """

    id = "Innovus.IOPlacement"
    name = "I/O Pin Placement (Innovus)"

    script_filename: ClassVar[str] = "ioplacer.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class GlobalPlacement(InnovusStep):
    """
    Scaffold for the ``global_placement`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/gpl.tcl``. Mirrors
    ``librelane/scripts/openroad/gpl.tcl``.
    """

    id = "Innovus.GlobalPlacement"
    name = "Global Placement (Innovus)"

    script_filename: ClassVar[str] = "gpl.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class PostGPLRepair(InnovusStep):
    """
    Scaffold for the ``post_gpl_repair`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/repair_design.tcl``.
    Mirrors ``librelane/scripts/openroad/repair_design.tcl``.
    """

    id = "Innovus.PostGPLRepair"
    name = "Post-Global-Placement Design Repair (Innovus)"

    script_filename: ClassVar[str] = "repair_design.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class DetailedPlacement(InnovusStep):
    """
    Scaffold for the ``detailed_placement`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/dpl.tcl``. Mirrors
    ``librelane/scripts/openroad/dpl.tcl``.
    """

    id = "Innovus.DetailedPlacement"
    name = "Detailed Placement (Innovus)"

    script_filename: ClassVar[str] = "dpl.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class CTS(InnovusStep):
    """
    Scaffold for the ``cts`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/cts.tcl``. Mirrors
    ``librelane/scripts/openroad/cts.tcl``.
    """

    id = "Innovus.CTS"
    name = "Clock Tree Synthesis (Innovus)"

    script_filename: ClassVar[str] = "cts.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class PostCTSOpt(InnovusStep):
    """
    Scaffold for the ``post_cts_opt`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/rsz_timing_postcts.tcl``.
    Mirrors ``librelane/scripts/openroad/rsz_timing_postcts.tcl``.
    """

    id = "Innovus.PostCTSOpt"
    name = "Post-CTS Timing Optimization (Innovus)"

    script_filename: ClassVar[str] = "rsz_timing_postcts.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class GlobalRouting(InnovusStep):
    """
    Scaffold for the ``global_routing`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/grt.tcl``. Mirrors
    ``librelane/scripts/openroad/grt.tcl``.
    """

    id = "Innovus.GlobalRouting"
    name = "Global Routing (Innovus)"

    script_filename: ClassVar[str] = "grt.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    # Only the layout changes; nl and sdc do not get re-emitted, matching
    # OpenROAD.GlobalRouting's contract.
    outputs = [DesignFormat.DEF]


@Step.factory.register()
class PostGRTRepair(InnovusStep):
    """
    Scaffold for the ``post_grt_repair`` stage using Innovus.

    Unimplemented; see
    ``librelane/scripts/innovus/repair_design_postgrt.tcl``. Mirrors
    ``librelane/scripts/openroad/repair_design_postgrt.tcl``.
    """

    id = "Innovus.PostGRTRepair"
    name = "Post-Global-Routing Design Repair (Innovus)"

    script_filename: ClassVar[str] = "repair_design_postgrt.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class AntennaRepair(InnovusStep):
    """
    Scaffold for the ``antenna_repair`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/antenna_repair.tcl``.
    Mirrors ``librelane/scripts/openroad/antenna_repair.tcl``.
    """

    id = "Innovus.AntennaRepair"
    name = "Antenna Violation Repair (Innovus)"

    script_filename: ClassVar[str] = "antenna_repair.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class PostGRTOpt(InnovusStep):
    """
    Scaffold for the ``post_grt_opt`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/rsz_timing_postgrt.tcl``.
    Mirrors ``librelane/scripts/openroad/rsz_timing_postgrt.tcl``.
    """

    id = "Innovus.PostGRTOpt"
    name = "Post-Global-Routing Timing Optimization (Innovus)"

    script_filename: ClassVar[str] = "rsz_timing_postgrt.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class DetailedRouting(InnovusStep):
    """
    Scaffold for the ``detailed_routing`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/drt.tcl``. Mirrors
    ``librelane/scripts/openroad/drt.tcl``.
    """

    id = "Innovus.DetailedRouting"
    name = "Detailed Routing (Innovus)"

    script_filename: ClassVar[str] = "drt.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class PostRouteOpt(InnovusStep):
    """
    Scaffold for the ``post_route_opt`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/post_route_opt.tcl``. No
    OpenROAD Tcl counterpart exists: this stage has no ``openroad`` provider
    at all in the taxonomy (its ``default_provider`` is ``None``), so there is
    nothing to mirror. This filename describes the stage instead.
    """

    id = "Innovus.PostRouteOpt"
    name = "Post-Route Optimization (Innovus)"

    script_filename: ClassVar[str] = "post_route_opt.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


@Step.factory.register()
class FillInsertion(InnovusStep):
    """
    Scaffold for the ``fill_insertion`` stage using Innovus.

    Unimplemented; see ``librelane/scripts/innovus/fill.tcl``. Mirrors
    ``librelane/scripts/openroad/fill.tcl``.
    """

    id = "Innovus.FillInsertion"
    name = "Fill Cell Insertion (Innovus)"

    script_filename: ClassVar[str] = "fill.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = list(PNR_IN_PLACE_PROVIDES)


#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module. A registration names exactly one stage, so each
#: entry below is separate, even though Innovus's real database persists across
#: all seventeen of these steps in a real run.
_INNOVUS_NAMESPACES = (
    # The specific INNOVUS_* configuration variables a real Innovus flow
    # would read are not enumerated anywhere in the research: no public
    # source lists them, and this scaffold declares none of its own. This
    # prefix reserves the namespace for whoever adds them once innovus is
    # available to test against.
    "INNOVUS_",
)

REGISTRATIONS: list[dict] = [
    {
        "stage": "floorplan",
        "provider": "innovus",
        "steps": [Floorplan],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "macro_placement",
        "provider": "innovus",
        "steps": [MacroPlacement],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "tapcell_insertion",
        "provider": "innovus",
        "steps": [TapEndcapInsertion],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "power_grid",
        "provider": "innovus",
        "steps": [PowerGrid],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "io_placement",
        "provider": "innovus",
        "steps": [IOPlacement],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "global_placement",
        "provider": "innovus",
        "steps": [GlobalPlacement],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "post_gpl_repair",
        "provider": "innovus",
        "steps": [PostGPLRepair],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "detailed_placement",
        "provider": "innovus",
        "steps": [DetailedPlacement],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "cts",
        "provider": "innovus",
        "steps": [CTS],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "post_cts_opt",
        "provider": "innovus",
        "steps": [PostCTSOpt],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "global_routing",
        "provider": "innovus",
        "steps": [GlobalRouting],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "post_grt_repair",
        "provider": "innovus",
        "steps": [PostGRTRepair],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "antenna_repair",
        "provider": "innovus",
        "steps": [AntennaRepair],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "post_grt_opt",
        "provider": "innovus",
        "steps": [PostGRTOpt],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "detailed_routing",
        "provider": "innovus",
        "steps": [DetailedRouting],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "post_route_opt",
        "provider": "innovus",
        "steps": [PostRouteOpt],
        "namespaces": _INNOVUS_NAMESPACES,
    },
    {
        "stage": "fill_insertion",
        "provider": "innovus",
        "steps": [FillInsertion],
        "namespaces": _INNOVUS_NAMESPACES,
    },
]
