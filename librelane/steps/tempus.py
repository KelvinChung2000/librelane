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
Cadence Tempus (``tempus``) step scaffolds.

Tempus is Cadence's signoff static timing analysis tool, part of the same
Genus/Innovus/Tempus Tcl-scripting family. No public source shows a native
Python API for it; Hammer's Cadence plugin
(``hammer/timing/tempus/__init__.py``) generates a Tcl file and invokes it
with ``tempus -no_gui -stylus -files <script>``. It shares its base class
with the Genus and Innovus plugins (``hammer/cadence/tool.py``), which only
ever generates Tcl strings, so the same "Tcl only" conclusion Genus and
Innovus rest on extends to Tempus by the same evidence. This module builds on
:class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 6.
"""

from typing import ClassVar

from .step import Step
from .vendor import VendorTclStep
from ..stages.stage import PNR_IN_PLACE_REQUIRES
from ..state import DesignFormat


class TempusStep(VendorTclStep):
    """
    Base class shared by every Tempus step.

    ``tempus`` is Tempus's invocation binary, confirmed by Hammer's Cadence
    plugin. It invokes Tempus as
    ``[tempus_bin, "-no_gui", "-stylus", "-files", timing_script]`` via
    ``run_executable()``, the identical pattern used by the Genus, Innovus
    and Voltus plugins in the same repository.
    """

    binary: ClassVar[str] = "tempus"
    script_dir: ClassVar[str] = "tempus"

    def get_command(self) -> list[str]:
        return [self.binary, "-no_gui", "-stylus", "-files", self.get_script_path()]


@Step.factory.register()
class PrePNRSTA(TempusStep):
    """
    Scaffold for the ``pre_pnr_sta`` stage using Tempus.

    Unimplemented; see ``librelane/scripts/tempus/pre_pnr_sta.tcl``.
    """

    id = "Tempus.PrePNRSTA"
    name = "Pre-PnR Static Timing Analysis (Tempus)"

    script_filename: ClassVar[str] = "pre_pnr_sta.tcl"

    inputs = [DesignFormat.NETLIST]
    outputs = [DesignFormat.SDC]


@Step.factory.register()
class SignoffSTA(TempusStep):
    """
    Scaffold for the ``signoff_sta`` stage using Tempus.

    Unimplemented; see ``librelane/scripts/tempus/signoff_sta.tcl``. A real
    implementation would need to report the four metrics the
    ``signoff_sta`` stage contracts: ``timing__setup_vio__count``,
    ``timing__hold_vio__count``, ``design__max_slew_violation__count`` and
    ``design__max_cap_violation__count``.
    """

    id = "Tempus.SignoffSTA"
    name = "Signoff Static Timing Analysis (Tempus)"

    script_filename: ClassVar[str] = "signoff_sta.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES) + [DesignFormat.SPEF]
    outputs = []


#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module.
_TEMPUS_NAMESPACES = (
    # The specific TEMPUS_* configuration variables a real Tempus flow
    # would read are not enumerated anywhere in the research: no public
    # source lists them, and this scaffold declares none of its own. This
    # prefix reserves the namespace for whoever adds them once tempus is
    # available to test against.
    "TEMPUS_",
)

REGISTRATIONS: list[dict] = [
    {
        "stage": "pre_pnr_sta",
        "provider": "tempus",
        "steps": [PrePNRSTA],
        "namespaces": _TEMPUS_NAMESPACES,
    },
    {
        "stage": "signoff_sta",
        "provider": "tempus",
        "steps": [SignoffSTA],
        "namespaces": _TEMPUS_NAMESPACES,
    },
]
