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
Cadence Genus (``genus``) step scaffolds.

Genus is Cadence's logic synthesis tool. For the classic (non-"Innovus+")
product, no public source shows a native Python API for it; Hammer's Cadence
plugin (``hammer/synthesis/genus/__init__.py``) generates a Tcl file and
invokes it with ``genus -f <script> -no_gui``, using no Python import or
``-python`` flag anywhere. Cadence markets a Python scripting mode for
"Innovus+", a newer unified platform, but the only public wording found is an
unfetchable white paper snippet, so its shape is unverified and not acted on
here. This module builds on
:class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 2.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.state import DesignFormat


class GenusStep(VendorTclStep):
    """
    Base class shared by every Genus step.

    ``genus`` is Genus's invocation binary, confirmed by Hammer's Cadence
    plugin, which is a real, currently-maintained production flow (UC
    Berkeley Chipyard's commercial tapeout path). It invokes Genus as
    ``[genus_bin, "-f", syn_tcl_filename, "-no_gui"]`` via ``run_executable()``,
    building the script through string concatenation rather than any typed
    API.
    """

    binary: ClassVar[str] = "genus"
    script_dir: ClassVar[str] = "genus"

    def get_command(self) -> list[str]:
        return [self.binary, "-f", self.get_script_path(), "-no_gui"]


@Step.factory.register()
class Synthesis(GenusStep):
    """
    Scaffold for the ``synthesis`` job using Genus.

    Unimplemented. ``run()`` (inherited from ``VendorTclStep``) raises
    ``NotImplementedError`` before ``librelane/scripts/genus/synthesis.tcl``
    is ever invoked. Fill in that script and, if Genus's actual synthesis
    flow needs configuration variables beyond what ``TclStep.prepare_env``
    already provides, add them to a ``Config`` here under the ``GENUS_``
    namespace.
    """

    id = "Genus.Synthesis"
    name = "Synthesis (Genus)"

    script_filename: ClassVar[str] = "synthesis.tcl"

    # The input RTL is part of the configuration (VERILOG_FILES and
    # friends), read directly by the real script rather than passed as a
    # state view, matching how Yosys.Synthesis declares no state inputs
    # either.
    inputs = []
    outputs = [DesignFormat.NETLIST]


#: Registered by ``librelane/jobs/providers_vendor.py`` (owned by another
#: agent), not by this module: opt-in to a commercial provider must be a
#: separate, explicit step from importing this module. See
#: ``librelane/jobs/providers.py`` for the shape this list mirrors.
REGISTRATIONS: list[dict] = [
    {
        "job": "synthesis",
        "provider": "genus",
        "steps": [Synthesis],
        # The specific GENUS_* configuration variables a real Genus
        # synthesis script would read are not enumerated anywhere in the
        # research: no public source lists them, and this scaffold declares
        # none of its own. This prefix reserves the namespace for whoever
        # adds them once genus is available to test against.
        "namespaces": ("GENUS_",),
    },
]
