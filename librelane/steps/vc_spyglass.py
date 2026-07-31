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
Scaffold provider for Synopsys VC SpyGlass, RTL lint.

VC SpyGlass was originally Atrenta's SpyGlass product. Synopsys acquired
Atrenta on 2015-06-07 (Synopsys's own press release) and kept the SpyGlass
brand rather than retiring it. It is now positioned more broadly than a
lint point tool, sold as part of an "RTL Static Signoff" platform in which
lint is one capability among several ("VC SpyGlass Lint").

No public source states VC SpyGlass's invocation binary. Because the
binary is unestablished, :class:`VCSpyGlassStep.get_command` raises rather
than returning a guessed command line, per the contract
:class:`~librelane.steps.vendor.VendorTclStep` documents for exactly this
situation.
"""

from librelane.steps.vendor import VendorTclStep
from librelane.steps.step import Step


class VCSpyGlassStep(VendorTclStep):
    """
    Shared base for VC SpyGlass's one covered stage, RTL lint.

    ``binary`` is left at :class:`VendorTclStep`'s default of ``None``. No
    public source establishes VC SpyGlass's invocation binary at all, so
    leaving it unset is how that gap is represented honestly here, matching
    what the research report found (or rather, did not find).
    """

    script_dir = "vc_spyglass"


@Step.factory.register()
class Lint(VCSpyGlassStep):
    """
    Scaffold for RTL linting using VC SpyGlass.

    Mirrors ``Verilator.Lint``'s neutral contract for the ``lint`` stage.
    The input RTL is read from the ``VERILOG_FILES`` (and equivalent)
    configuration variables rather than a design-format view, so this step
    declares no ``inputs``, matching the stage's own empty ``requires``.
    """

    id = "VCSpyGlass.Lint"
    name = "RTL Lint (VC SpyGlass)"
    long_name = "RTL Lint (VC SpyGlass)"

    script_filename = "lint.tcl"

    inputs = []
    outputs = []

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: no public source establishes VC "
            "SpyGlass's invocation binary or command-line syntax. Even if "
            "the Tcl script this step is supposed to run were written, "
            "there would be no established way to invoke VC SpyGlass "
            "against it; both gaps need to be closed by someone with "
            "access to the tool."
        )


#: VC SpyGlass's configuration-variable prefix. The specific variable names
#: are unknown until someone with VC SpyGlass access enumerates what a real
#: implementation of this step would need to read; "VC_SPYGLASS_" is
#: reserved for them.
_VC_SPYGLASS_NAMESPACES = ("VC_SPYGLASS_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``StageRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "stage": "lint",
        "provider": "vc_spyglass",
        "steps": [Lint],
        "namespaces": _VC_SPYGLASS_NAMESPACES,
    },
]
