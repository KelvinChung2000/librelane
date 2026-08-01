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
Scaffold provider for Synopsys StarRC, parasitic (RC) extraction.

StarRC's function is well established by Synopsys's own product pages. It
is described there as the "golden" extraction engine feeding both PrimeTime
and Fusion Compiler. Its invocation is not. No public source fetched for
the research report states a CLI binary name for StarRC, unlike
``dc_shell``, ``pt_shell``, ``icv``, or ``fm_shell``, each of which a source
names directly. A third-party academic PDK-enablement repository uses
``starRC`` only as a Makefile tool-selector string, which is not the same
thing as a documented binary name and is not treated as one here.

Because the binary is unestablished, :class:`StarRCStep.get_command` raises
rather than returning a guessed command line, per the contract
:class:`~librelane.steps.vendor.VendorTclStep` documents for exactly this
situation.
"""

from librelane.state import DesignFormat
from librelane.steps.vendor import VendorTclStep
from librelane.steps.step import Step


class StarRCStep(VendorTclStep):
    """
    Shared base for StarRC's one covered job, parasitic extraction.

    ``binary`` is left at :class:`VendorTclStep`'s default of ``None``. No
    public source establishes StarRC's invocation binary at all, so leaving
    it unset is how that gap is represented honestly here, matching what
    the research report found (or rather, did not find).
    """

    script_dir = "starrc"


@Step.factory.register()
class Extraction(StarRCStep):
    """
    Scaffold for parasitic extraction using StarRC.

    Mirrors ``OpenROAD.RCX``'s neutral contract for the ``extraction``
    job. Both consume the placed-and-routed DEF and produce SPEF.
    """

    id = "StarRC.Extraction"
    name = "Parasitics Extraction (StarRC)"
    long_name = "Parasitic Resistance/Capacitance Extraction (StarRC)"

    script_filename = "rcx.tcl"

    inputs = [DesignFormat.DEF]
    outputs = [DesignFormat.SPEF]

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: no public source establishes StarRC's "
            "invocation binary or command-line syntax. Even if the Tcl "
            "script this step is supposed to run were written, there would "
            "be no established way to invoke StarRC against it; both gaps "
            "need to be closed by someone with access to the tool."
        )


#: StarRC's configuration-variable prefix. The specific variable names are
#: unknown until someone with StarRC access enumerates what a real
#: implementation of this step would need to read; "STARRC_" is reserved
#: for them.
_STARRC_NAMESPACES = ("STARRC_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``JobRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "job": "extraction",
        "provider": "starrc",
        "steps": [Extraction],
        "namespaces": _STARRC_NAMESPACES,
    },
]
