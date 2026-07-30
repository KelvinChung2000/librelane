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
Synopsys Design Compiler (``dc_shell``) step scaffolds.

Design Compiler is Synopsys's logic synthesis tool. No public source shows a
native Python API for it; both open-source flow drivers that were found
(SiliconCompiler's fork and Hammer's Synopsys plugin) generate a Tcl file and
invoke ``dc_shell -f`` on it. This module therefore builds on
:class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``: nobody with access to Design Compiler has
exercised this code, so it does not run anything. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 1.
"""

from typing import ClassVar

from .step import Step
from .vendor import VendorTclStep
from ..state import DesignFormat


class DCStep(VendorTclStep):
    """
    Base class shared by every Design Compiler step.

    ``dc_shell`` is Design Compiler's invocation binary. This is the most
    solidly established binary name in the whole vendor-tool survey: two
    independent open-source flow drivers confirm it (the SiliconCompiler
    fork's ``siliconcompiler/tools/dc/__init__.py`` and
    ``syn_asic.py``, and Hammer's Synopsys plugin's
    ``hammer/synthesis/dc/__init__.py``), and both invoke it the same way,
    writing a Tcl script and running ``dc_shell -f <script>``. Neither driver
    uses any Python API; Design Compiler's Tcl-only status is correspondingly
    solid.
    """

    binary: ClassVar[str] = "dc_shell"
    script_dir: ClassVar[str] = "dc"

    def get_command(self) -> list[str]:
        return [self.binary, "-f", self.get_script_path()]


@Step.factory.register()
class Synthesis(DCStep):
    """
    Scaffold for the ``synthesis`` stage using Design Compiler.

    Unimplemented. ``run()`` (inherited from ``VendorTclStep``) raises
    ``NotImplementedError`` before ``librelane/scripts/dc/synthesis.tcl`` is
    ever invoked. Fill in that script and, if ``dc_shell``'s actual
    synthesis flow needs configuration variables beyond what
    ``TclStep.prepare_env`` already provides, add them to a ``Config`` here
    under the ``DC_`` namespace.
    """

    id = "DC.Synthesis"
    name = "Synthesis (Design Compiler)"

    script_filename: ClassVar[str] = "synthesis.tcl"

    # The input RTL is part of the configuration (VERILOG_FILES and
    # friends), read directly by the real script rather than passed as a
    # state view, matching how Yosys.Synthesis declares no state inputs
    # either.
    inputs = []
    outputs = [DesignFormat.NETLIST]


#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module: opt-in to a commercial provider must be a
#: separate, explicit step from importing this module. See
#: ``librelane/stages/providers.py`` for the shape this list mirrors.
REGISTRATIONS: list[dict] = [
    {
        "stage": "synthesis",
        "provider": "dc",
        "steps": [Synthesis],
        # The specific DC_* configuration variables a real Design Compiler
        # synthesis script would read are not enumerated anywhere in the
        # research: no public source lists them, and this scaffold declares
        # none of its own. This prefix reserves the namespace for whoever
        # adds them once dc_shell is available to test against.
        "namespaces": ("DC_",),
    },
]
