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
Scaffold provider for Siemens Calibre, DRC and LVS signoff.

``calibre`` is confirmed as the tool's invocation binary. Beyond the bare
binary name, no source in the research report states a command-line flag
(check type, rule deck selection, license switches, and so on). A confirmed
binary with no confirmed way to run it against a rule deck is still a
blocking gap. A command line that is just ``["calibre"]`` would launch an
interactive session rather than run this step's check, which is no more
usable than not knowing the binary at all, so :meth:`CalibreStep.get_command`
raises rather than returning that half-complete, plausible-looking command
line, the same choice :mod:`librelane.steps.fm` makes for Formality and for
the same reason. Attaching a guessed flag would misrepresent an unconfirmed
detail as an established one.

Calibre has no native Python API for the verification engine or its result
database. Public documentation shows Python only as an external "trigger"
scripting language for Calibre Interactive, invoked as a subprocess with
filename/parameter arguments, with no access back into Calibre's internal
state. The result database itself (SVDB for LVS, RDB for DRC/LVS results)
is a proprietary, undisclosed binary format, corroborated indirectly by the
KLayout open-source project's own notes that they cannot support Calibre's
RDB format because Siemens has not published its specification.

Worth recording here because it explains why public material on Calibre is
thin relative to Cadence and Synopsys's tools in this survey. Hammer's own
Calibre integration lives in a separate, access-gated repository
(``hammer-mentor-plugins``), distinct from Hammer's public Cadence and
Synopsys plugin repos; UC Berkeley's own documentation states non-affiliates
must request access due to Siemens's (formerly Mentor's) licensing terms.
That even the integration code, not just a hypothetical native API, sits
behind an NDA independently corroborates how walled this tool is.

Calibre is driven by SVRF and rule files, not plain Tcl. No public source
establishes that format's syntax, so this module's Tcl-extensioned script
stubs (``librelane/scripts/calibre/drc.tcl``,
``librelane/scripts/calibre/lvs.tcl``) are placeholders in name only. See
each stub's header comment.
"""

from ..state import DesignFormat
from .vendor import VendorTclStep
from .step import Step


class CalibreStep(VendorTclStep):
    """
    Shared base for Calibre's two covered stages, DRC and LVS.
    """

    binary = "calibre"
    script_dir = "calibre"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: calibre is confirmed as Calibre's "
            "invocation binary, but no public source establishes how to "
            "run it against a rule deck non-interactively (no confirmed "
            "flag for check type, rule deck selection, or license "
            "switches). Someone with access to the tool needs to "
            "establish the actual invocation before this step can be "
            "invoked."
        )


@Step.factory.register()
class DRC(CalibreStep):
    """
    Scaffold for design rule checking using Calibre.

    ``drc`` is a ``multi_provider`` stage already served by Magic and
    KLayout; this step slots in beside them (and beside IC Validator) as
    another provider rather than replacing any of them. Mirrors
    ``Magic.DRC``'s neutral contract, taking DEF optionally and GDS.
    """

    id = "Calibre.DRC"
    name = "DRC (Calibre)"
    long_name = "Design Rule Checks (Calibre)"

    script_filename = "drc.tcl"

    inputs = [DesignFormat.DEF.mkOptional(), DesignFormat.GDS]
    outputs = []


@Step.factory.register()
class LVS(CalibreStep):
    """
    Scaffold for layout-versus-schematic checking using Calibre.

    Mirrors the ``lvs`` stage's neutral contract: DEF, GDS, and the powered
    netlist as the schematic side of the comparison, the same triple
    ``Netgen.LVS`` (by way of ``Magic.SpiceExtraction``) consumes.
    """

    id = "Calibre.LVS"
    name = "LVS (Calibre)"
    long_name = "Layout Versus Schematic (Calibre)"

    script_filename = "lvs.tcl"

    inputs = [DesignFormat.DEF, DesignFormat.GDS, DesignFormat.POWERED_NETLIST]
    outputs = []


#: Calibre's configuration-variable prefix. The specific variable names are
#: unknown until someone with Calibre access enumerates what a real
#: implementation of these steps would need to read; "CALIBRE_" is reserved
#: for them.
_CALIBRE_NAMESPACES = ("CALIBRE_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``StageRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "stages": ["drc"],
        "provider": "calibre",
        "steps": [DRC],
        "namespaces": _CALIBRE_NAMESPACES,
    },
    {
        "stages": ["lvs"],
        "provider": "calibre",
        "steps": [LVS],
        "namespaces": _CALIBRE_NAMESPACES,
    },
]


#: Siemens Questa Lint and Questa AutoCheck (RTL lint / formal bug-hunting)
#: are deliberately NOT scaffolded anywhere in this batch of providers, even
#: though Calibre is this batch's other Siemens tool. The research report
#: found these to be two separate, both-current Siemens products, not
#: alternate names for the same capability. Questa Lint is traditional
#: static RTL lint, and Questa AutoCheck is a separate formal-methods-based
#: bug-hunting tool comparable to Cadence's JasperGold Superlint App rather
#: than to a lint tool. No public source states a binary name for either.
#: Scaffolding a "Siemens RTL lint" provider under either identity would
#: risk conflating two distinct products under one name; recorded here so
#: nobody later assumes that gap was an oversight rather than a choice.
