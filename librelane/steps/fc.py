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
Synopsys Fusion Compiler (``fc_shell``) step scaffolds.

Fusion Compiler genuinely unifies RTL synthesis and place-and-route on one
shared data model; this is vendor-confirmed (Synopsys's own product blog and
datasheet describe it as integrating "all synthesis, place-and-route and
signoff engines on a single data model"), not marketing gloss this module is
merely repeating. That is why this module registers for the ``synthesis``
job as well as the seventeen place-and-route jobs that IC Compiler II
also covers.

``fc_shell`` is Fusion Compiler's invocation binary, but its provenance is
weaker than Design Compiler's ``dc_shell``: it is well-attested by consistent
usage across tutorial and community material, not directly quoted from a
Synopsys primary source the way ``dc_shell`` and ``pt_shell`` were. Treat it
as well-attested by convention, not vendor-confirmed to the same standard.

No public source shows a native Python API for Fusion Compiler. This module
therefore builds on :class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 12.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.state import DesignFormat

# Mirrors PNR_IN_PLACE_REQUIRES / PNR_IN_PLACE_PROVIDES in
# librelane/jobs/job.py: the view contract shared by every in-place
# place-and-route transform. Restated here rather than imported, because
# librelane.steps is the lower layer that librelane.jobs is built on (no
# module under librelane/steps/ imports librelane.jobs, and
# librelane/jobs/providers.py imports librelane.steps at module load time,
# so importing the other way round here would invert that layering and risk
# a circular import).
_PNR_IN_PLACE_REQUIRES = [DesignFormat.DEF, DesignFormat.NETLIST, DesignFormat.SDC]
_PNR_IN_PLACE_PROVIDES = [DesignFormat.DEF, DesignFormat.NETLIST, DesignFormat.SDC]


class FCStep(VendorTclStep):
    """
    Base class shared by every Fusion Compiler step.

    ``fc_shell`` is Fusion Compiler's invocation binary (see the module
    docstring for the provenance caveat). No public source states the flags
    it is invoked with, so :meth:`get_command` raises rather than guessing
    one, the same reasoning applied to IC Compiler II's ``icc2_shell`` in
    ``librelane/steps/icc2.py``.
    """

    binary: ClassVar[str] = "fc_shell"
    script_dir: ClassVar[str] = "fc"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: 'fc_shell' is well-attested by "
            "tutorial/community convention as Fusion Compiler's invocation "
            "binary, but no public source (vendor-quoted or otherwise) "
            "states the command-line flags it is invoked with. Guessing a "
            "flag syntax here would look exactly as authoritative as a "
            "verified one; get_command() must be written by someone with "
            "fc_shell access instead."
        )


class FCPNRStep(FCStep):
    """
    Shared input/output contract for the seventeen in-place place-and-route
    jobs Fusion Compiler covers (``floorplan`` through ``fill_insertion``),
    on top of ``synthesis`` (see :class:`Synthesis`). A concrete subclass
    need only set ``id``, ``name`` and ``script_filename``.
    """

    inputs = _PNR_IN_PLACE_REQUIRES
    outputs = _PNR_IN_PLACE_PROVIDES


@Step.factory.register()
class Synthesis(FCStep):
    """
    Scaffold for the ``synthesis`` job using Fusion Compiler. Unimplemented;
    see ``librelane/scripts/fc/synthesis.tcl``.
    """

    id = "FC.Synthesis"
    name = "Synthesis (Fusion Compiler)"
    script_filename: ClassVar[str] = "synthesis.tcl"

    # The input RTL is part of the configuration (VERILOG_FILES and
    # friends), read directly by the real script rather than passed as a
    # state view, matching how Yosys.Synthesis and DC.Synthesis declare no
    # state inputs either.
    inputs = []
    outputs = [DesignFormat.NETLIST]


@Step.factory.register()
class Floorplan(FCPNRStep):
    """
    Scaffold for the ``floorplan`` job using Fusion Compiler. Unimplemented;
    see ``librelane/scripts/fc/floorplan.tcl``.
    """

    id = "FC.Floorplan"
    name = "Floorplan (Fusion Compiler)"
    script_filename: ClassVar[str] = "floorplan.tcl"

    # Unlike every later job in this span, floorplan is where DEF and SDC
    # are produced for the first time, not carried in: the floorplan job's
    # own contract requires only DesignFormat.NETLIST (see librelane/jobs/
    # taxonomy.py), matching OpenROAD.Floorplan. Inheriting the base step's
    # inputs unmodified would claim DEF as an input the job never promises,
    # which the registration-time view check correctly rejects.
    inputs = [DesignFormat.NETLIST]


@Step.factory.register()
class MacroPlacement(FCPNRStep):
    """
    Scaffold for the ``macro_placement`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/macro_placement.tcl``.
    """

    id = "FC.MacroPlacement"
    name = "Macro Placement (Fusion Compiler)"
    script_filename: ClassVar[str] = "macro_placement.tcl"


@Step.factory.register()
class TapcellInsertion(FCPNRStep):
    """
    Scaffold for the ``tapcell_insertion`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/tapcell.tcl``.
    """

    id = "FC.TapcellInsertion"
    name = "Tap/Endcap Insertion (Fusion Compiler)"
    script_filename: ClassVar[str] = "tapcell.tcl"


@Step.factory.register()
class PowerGrid(FCPNRStep):
    """
    Scaffold for the ``power_grid`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/pdn.tcl``.
    """

    id = "FC.PowerGrid"
    name = "Power Distribution Network (Fusion Compiler)"
    script_filename: ClassVar[str] = "pdn.tcl"


@Step.factory.register()
class IOPlacement(FCPNRStep):
    """
    Scaffold for the ``io_placement`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/ioplacer.tcl``.
    """

    id = "FC.IOPlacement"
    name = "I/O Placement (Fusion Compiler)"
    script_filename: ClassVar[str] = "ioplacer.tcl"


@Step.factory.register()
class GlobalPlacement(FCPNRStep):
    """
    Scaffold for the ``global_placement`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/gpl.tcl``.
    """

    id = "FC.GlobalPlacement"
    name = "Global Placement (Fusion Compiler)"
    script_filename: ClassVar[str] = "gpl.tcl"


@Step.factory.register()
class PostGPLRepair(FCPNRStep):
    """
    Scaffold for the ``post_gpl_repair`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/repair_design.tcl``.
    """

    id = "FC.PostGPLRepair"
    name = "Post-Global-Placement Design Repair (Fusion Compiler)"
    script_filename: ClassVar[str] = "repair_design.tcl"


@Step.factory.register()
class DetailedPlacement(FCPNRStep):
    """
    Scaffold for the ``detailed_placement`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/dpl.tcl``.
    """

    id = "FC.DetailedPlacement"
    name = "Detailed Placement (Fusion Compiler)"
    script_filename: ClassVar[str] = "dpl.tcl"


@Step.factory.register()
class CTS(FCPNRStep):
    """
    Scaffold for the ``cts`` job using Fusion Compiler. Unimplemented; see
    ``librelane/scripts/fc/cts.tcl``.
    """

    id = "FC.CTS"
    name = "Clock Tree Synthesis (Fusion Compiler)"
    script_filename: ClassVar[str] = "cts.tcl"


@Step.factory.register()
class PostCTSOpt(FCPNRStep):
    """
    Scaffold for the ``post_cts_opt`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/rsz_timing_postcts.tcl``.
    """

    id = "FC.PostCTSOpt"
    name = "Post-CTS Timing Optimization (Fusion Compiler)"
    script_filename: ClassVar[str] = "rsz_timing_postcts.tcl"


@Step.factory.register()
class GlobalRouting(FCPNRStep):
    """
    Scaffold for the ``global_routing`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/grt.tcl``.
    """

    id = "FC.GlobalRouting"
    name = "Global Routing (Fusion Compiler)"
    script_filename: ClassVar[str] = "grt.tcl"


@Step.factory.register()
class PostGRTRepair(FCPNRStep):
    """
    Scaffold for the ``post_grt_repair`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/repair_design_postgrt.tcl``.
    """

    id = "FC.PostGRTRepair"
    name = "Post-Global-Routing Design Repair (Fusion Compiler)"
    script_filename: ClassVar[str] = "repair_design_postgrt.tcl"


@Step.factory.register()
class AntennaRepair(FCPNRStep):
    """
    Scaffold for the ``antenna_repair`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/antenna_repair.tcl``.
    """

    id = "FC.AntennaRepair"
    name = "Antenna Violation Repair (Fusion Compiler)"
    script_filename: ClassVar[str] = "antenna_repair.tcl"


@Step.factory.register()
class PostGRTOpt(FCPNRStep):
    """
    Scaffold for the ``post_grt_opt`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/rsz_timing_postgrt.tcl``.
    """

    id = "FC.PostGRTOpt"
    name = "Post-Global-Routing Timing Optimization (Fusion Compiler)"
    script_filename: ClassVar[str] = "rsz_timing_postgrt.tcl"


@Step.factory.register()
class DetailedRouting(FCPNRStep):
    """
    Scaffold for the ``detailed_routing`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/drt.tcl``.
    """

    id = "FC.DetailedRouting"
    name = "Detailed Routing (Fusion Compiler)"
    script_filename: ClassVar[str] = "drt.tcl"


@Step.factory.register()
class PostRouteOpt(FCPNRStep):
    """
    Scaffold for the ``post_route_opt`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/post_route_opt.tcl``.
    """

    id = "FC.PostRouteOpt"
    name = "Post-Route Optimization (Fusion Compiler)"
    script_filename: ClassVar[str] = "post_route_opt.tcl"


@Step.factory.register()
class FillInsertion(FCPNRStep):
    """
    Scaffold for the ``fill_insertion`` job using Fusion Compiler.
    Unimplemented; see ``librelane/scripts/fc/fill.tcl``.
    """

    id = "FC.FillInsertion"
    name = "Fill Cell Insertion (Fusion Compiler)"
    script_filename: ClassVar[str] = "fill.tcl"


#: Registered by ``librelane/jobs/providers_vendor.py`` (owned by another
#: agent), not by this module: opt-in to a commercial provider must be a
#: separate, explicit step from importing this module. See
#: ``librelane/jobs/providers.py`` for the shape this list mirrors.
#:
#: A registration names exactly one job, so each job below gets its own
#: entry. A real Fusion Compiler backend would use ``native_views`` between
#: its own steps to get the single-data-model benefit. Fusion Compiler carries a
#: proprietary in-memory design database across jobs, the same way
#: OpenROAD's live ``odb`` database does, but no public source establishes
#: its view name or on-disk format (see vendor-python-apis.md, section 12),
#: so no ``DesignFormat`` is invented for it here, and every registration
#: below leaves ``native_views`` at its default empty tuple. Declaring it,
#: once someone with ``fc_shell`` access determines the real format, is the
#: correct future change: it is the mechanism that would let a real
#: implementation pass a live database between Fusion Compiler's own steps
#: across all eighteen jobs below instead of re-reading DEF, netlist and
#: every LEF at each boundary.
REGISTRATIONS: list[dict] = [
    {
        "job": "synthesis",
        "provider": "fc",
        "steps": [Synthesis],
        "namespaces": ("FC_",),
    },
    {
        "job": "floorplan",
        "provider": "fc",
        "steps": [Floorplan],
        "namespaces": ("FC_",),
    },
    {
        "job": "macro_placement",
        "provider": "fc",
        "steps": [MacroPlacement],
        "namespaces": ("FC_",),
    },
    {
        "job": "tapcell_insertion",
        "provider": "fc",
        "steps": [TapcellInsertion],
        "namespaces": ("FC_",),
    },
    {
        "job": "power_grid",
        "provider": "fc",
        "steps": [PowerGrid],
        "namespaces": ("FC_",),
    },
    {
        "job": "io_placement",
        "provider": "fc",
        "steps": [IOPlacement],
        "namespaces": ("FC_",),
    },
    {
        "job": "global_placement",
        "provider": "fc",
        "steps": [GlobalPlacement],
        "namespaces": ("FC_",),
    },
    {
        "job": "post_gpl_repair",
        "provider": "fc",
        "steps": [PostGPLRepair],
        "namespaces": ("FC_",),
    },
    {
        "job": "detailed_placement",
        "provider": "fc",
        "steps": [DetailedPlacement],
        "namespaces": ("FC_",),
    },
    {
        "job": "cts",
        "provider": "fc",
        "steps": [CTS],
        "namespaces": ("FC_",),
    },
    {
        "job": "post_cts_opt",
        "provider": "fc",
        "steps": [PostCTSOpt],
        "namespaces": ("FC_",),
    },
    {
        "job": "global_routing",
        "provider": "fc",
        "steps": [GlobalRouting],
        "namespaces": ("FC_",),
    },
    {
        "job": "post_grt_repair",
        "provider": "fc",
        "steps": [PostGRTRepair],
        "namespaces": ("FC_",),
    },
    {
        "job": "antenna_repair",
        "provider": "fc",
        "steps": [AntennaRepair],
        "namespaces": ("FC_",),
    },
    {
        "job": "post_grt_opt",
        "provider": "fc",
        "steps": [PostGRTOpt],
        "namespaces": ("FC_",),
    },
    {
        "job": "detailed_routing",
        "provider": "fc",
        "steps": [DetailedRouting],
        "namespaces": ("FC_",),
    },
    {
        "job": "post_route_opt",
        "provider": "fc",
        "steps": [PostRouteOpt],
        "namespaces": ("FC_",),
    },
    {
        "job": "fill_insertion",
        "provider": "fc",
        "steps": [FillInsertion],
        "namespaces": ("FC_",),
    },
]
