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
Cadence Voltus (IR drop / power integrity) step scaffolds.

Voltus is Cadence's IC power integrity solution (IR drop, electromigration,
power grid analysis). No public source shows a native Python API for it;
Hammer's Cadence plugin (``hammer/power/voltus/__init__.py``) generates a Tcl
file and invokes it with ``voltus -no_gui -common_ui -init``, the same
Tcl-script-plus-subprocess pattern as the rest of the Cadence Hammer plugins.
This module builds on :class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 8.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.jobs.job import PNR_IN_PLACE_REQUIRES
from librelane.state import DesignFormat


class VoltusStep(VendorTclStep):
    """
    Base class shared by every Voltus step.

    ``voltus`` is Voltus's invocation binary, confirmed by Hammer's Cadence
    plugin. It invokes Voltus as
    ``[voltus_bin, "-no_gui", "-common_ui", "-init"]`` via
    ``run_executable()``, with a generated Tcl script path appended as an
    argument.
    """

    binary: ClassVar[str] = "voltus"
    script_dir: ClassVar[str] = "voltus"

    def get_command(self) -> list[str]:
        return [self.binary, "-no_gui", "-common_ui", "-init", self.get_script_path()]


@Step.factory.register()
class IRDrop(VoltusStep):
    """
    Scaffold for the ``ir_drop`` job using Voltus.

    Unimplemented; see ``librelane/scripts/voltus/irdrop.tcl``.
    """

    id = "Voltus.IRDrop"
    name = "IR Drop Analysis (Voltus)"

    script_filename: ClassVar[str] = "irdrop.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES) + [DesignFormat.SPEF]
    outputs = []


#: Registered by ``librelane/jobs/providers_vendor.py`` (owned by another
#: agent), not by this module.
REGISTRATIONS: list[dict] = [
    {
        "job": "ir_drop",
        "provider": "voltus",
        "steps": [IRDrop],
        # The specific VOLTUS_* configuration variables a real Voltus flow
        # would read are not enumerated anywhere in the research: no public
        # source lists them, and this scaffold declares none of its own.
        # This prefix reserves the namespace for whoever adds them once
        # voltus is available to test against.
        "namespaces": ("VOLTUS_",),
    },
]
