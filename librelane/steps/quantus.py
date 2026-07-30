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
Cadence Quantus (parasitic/RC extraction) step scaffolds.

Quantus is Cadence's parasitic extraction solution, producing a binary RCDB
format consumed by Tempus and Innovus, per Cadence's own datasheet. Unlike
Genus, Innovus, Tempus and Voltus, Quantus has no Hammer plugin at all (it is
absent from the ``hammer-cadence-plugins`` file tree that does contain the
other four), so there is no open-source integration to confirm its
invocation from. The only public evidence found of a binary name is a
third-party academic enablement repository
(``github.com/ABKGroup/NanGate45-Synopsys-Enablement``) that uses
``PEX_TOOL1=quantus`` as a Makefile tool-selector string alongside
``PEX_TOOL2=starRC``. That is suggestive but not a confirmed CLI invocation
with flags, so this module treats Quantus's binary as unestablished rather
than guessing that the selector string is also the correct invocation.

This module builds on :class:`~librelane.steps.vendor.VendorTclStep`,
because Quantus is presumed Tcl-scripted like the rest of the Cadence
implementation/signoff family (no source suggests otherwise), even though its
invocation cannot be confirmed. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 7.
"""

from typing import ClassVar

from .step import Step
from .vendor import VendorTclStep
from ..stages.stage import PNR_IN_PLACE_REQUIRES
from ..state import DesignFormat


class QuantusStep(VendorTclStep):
    """
    Base class shared by every Quantus step.

    ``binary`` is deliberately left at ``None``: no public source confirms
    Quantus's invocation binary or command-line syntax, only a Makefile
    tool-selector string in a third-party repository that names the string
    ``quantus`` without ever showing it invoked with flags. ``get_command()``
    raises rather than guessing that this selector string is also the real
    invocation.
    """

    script_dir: ClassVar[str] = "quantus"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: Quantus's invocation is unestablished. "
            "The only public evidence found is a `PEX_TOOL1=quantus` "
            "Makefile tool-selector string in a third-party academic "
            "enablement repository, not a confirmed CLI binary name or "
            "flag set. See section 7 of "
            ".superpowers/sdd/2026-07-29-cad-tool-abstraction/"
            "vendor-python-apis.md."
        )


@Step.factory.register()
class Extraction(QuantusStep):
    """
    Scaffold for the ``extraction`` stage using Quantus.

    Unimplemented; see ``librelane/scripts/quantus/rcx.tcl``. Beyond the
    usual scaffold gap (the script is unwritten), Quantus's own invocation
    is unestablished, so writing the script would not be sufficient by
    itself; see :meth:`QuantusStep.get_command`.
    """

    id = "Quantus.Extraction"
    name = "Parasitics Extraction (Quantus)"

    script_filename: ClassVar[str] = "rcx.tcl"

    inputs = list(PNR_IN_PLACE_REQUIRES)
    outputs = [DesignFormat.SPEF]


#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module.
REGISTRATIONS: list[dict] = [
    {
        "stages": ["extraction"],
        "provider": "quantus",
        "steps": [Extraction],
        # The specific QUANTUS_* configuration variables a real Quantus
        # flow would read are not enumerated anywhere in the research: no
        # public source lists them, and this scaffold declares none of its
        # own. This prefix reserves the namespace for whoever adds them
        # once quantus is available to test against.
        "namespaces": ("QUANTUS_",),
    },
]
