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
Scaffold provider for Synopsys IC Validator, DRC and LVS signoff.

``icv`` is directly confirmed as IC Validator's invocation binary by
Hammer's own public documentation
(``hammer-vlsi.readthedocs.io/en/stable/CAD-Tools/ICV.html``). That page
also mentions a real, quotable flag, ``-clf``, but not for the purpose an
earlier version of this module used it for. The page's own words are
"Extensibility is enabled by passing a file to the icv command with
``-clf``. This file contains additional command line arguments, and is
generated in the ``generate_<drc/lvs>_args_file`` step (can be
overridden)." ``-clf`` therefore attaches a file of *supplementary*
command-line arguments, not a rule deck or script; it is not "how you tell
icv what to check." No source in the research report establishes the flag
(or flags) that actually hand icv a DRC or LVS rule deck non-interactively,
so :meth:`ICValidatorStep.get_command` raises rather than attaching this
step's script to ``-clf``, which would have been the same mistake as
guessing a flag, dressed up in a real one borrowed for the wrong job.

IC Validator's rule decks are its own runset format, not Tcl. No public
source establishes that format's syntax, so this module's Tcl-extensioned
script stubs (``librelane/scripts/icv/drc.tcl``,
``librelane/scripts/icv/lvs.tcl``) are placeholders in name only. See each
stub's header comment.
"""

from ..state import DesignFormat
from .vendor import VendorTclStep
from .step import Step


class ICValidatorStep(VendorTclStep):
    """
    Shared base for IC Validator's two covered stages, DRC and LVS.
    """

    binary = "icv"
    script_dir = "icv"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: icv is confirmed as IC Validator's "
            "invocation binary, but no public source establishes how to "
            "invoke it against a DRC or LVS rule deck non-interactively. "
            "The one flag IC Validator's own Hammer documentation "
            "confirms, -clf, attaches a file of supplementary "
            "command-line arguments, not a rule deck or script, so it "
            "cannot stand in for that gap. Someone with access to the "
            "tool needs to establish the actual invocation before this "
            "step can be invoked."
        )


@Step.factory.register()
class DRC(ICValidatorStep):
    """
    Scaffold for design rule checking using IC Validator.

    ``drc`` is a ``multi_provider`` stage already served by Magic and
    KLayout; this step slots in beside them as a third provider rather than
    replacing either. Mirrors ``Magic.DRC``'s neutral contract, taking DEF
    optionally and GDS.
    """

    id = "ICValidator.DRC"
    name = "DRC (IC Validator)"
    long_name = "Design Rule Checks (IC Validator)"

    script_filename = "drc.tcl"

    inputs = [DesignFormat.DEF.mkOptional(), DesignFormat.GDS]
    outputs = []


@Step.factory.register()
class LVS(ICValidatorStep):
    """
    Scaffold for layout-versus-schematic checking using IC Validator.

    Mirrors the ``lvs`` stage's neutral contract: DEF, GDS, and the powered
    netlist as the schematic side of the comparison, the same triple
    ``Netgen.LVS`` (by way of ``Magic.SpiceExtraction``) consumes.
    """

    id = "ICValidator.LVS"
    name = "LVS (IC Validator)"
    long_name = "Layout Versus Schematic (IC Validator)"

    script_filename = "lvs.tcl"

    inputs = [DesignFormat.DEF, DesignFormat.GDS, DesignFormat.POWERED_NETLIST]
    outputs = []


#: IC Validator's configuration-variable prefix. The specific variable
#: names are unknown until someone with IC Validator access enumerates what
#: a real implementation of these steps would need to read; "ICV_" is
#: reserved for them.
_ICV_NAMESPACES = ("ICV_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``StageRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "stage": "drc",
        "provider": "icv",
        "steps": [DRC],
        "namespaces": _ICV_NAMESPACES,
    },
    {
        "stage": "lvs",
        "provider": "icv",
        "steps": [LVS],
        "namespaces": _ICV_NAMESPACES,
    },
]
