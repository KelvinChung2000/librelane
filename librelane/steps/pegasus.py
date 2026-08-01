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
Cadence Pegasus (DRC and LVS signoff) step scaffolds.

Pegasus is Cadence's current-generation physical verification (DRC/LVS)
signoff platform, built for massively parallel/cloud execution. Public forum
discussion indicates it has not simply replaced Assura and PVS outright:
Pegasus targets advanced nodes while PVS and Assura continue to be used for
older/mature nodes, so the three currently coexist in Cadence's lineup rather
than Pegasus having fully superseded the others.

No open-source plugin for Pegasus exists anywhere (no Hammer plugin, no
SiliconCompiler plugin, nothing found in this survey). The only invocation
evidence is a fragment of Cadence's own support portal
(``support1.cadence.com/public/docs/content/20493530.html``, "How to run
PVS-Pegasus LVS from the Command Line?"), which states the general pattern:
"pvs/Pegasus command followed by ``-lvs``, followed by command-line options
and rule file or set of rule files at the end." That confirms ``pvs``
(legacy) and/or ``pegasus`` (current) as the binary name and ``-lvs`` as a
real flag, but no complete example command line was retrievable. This module
therefore treats Pegasus's invocation as unestablished, the same as Quantus,
rather than guessing a full command line from a partial pattern.

Pegasus coexists with Assura and PVS rather than replacing them: Pegasus
targets advanced nodes, and Assura/PVS remain in use for older, mature nodes.

This module builds on :class:`~librelane.steps.vendor.VendorTclStep`, on the
same presumption-of-Tcl basis as Quantus (no source suggests otherwise, but
none confirms it either). See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 9.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.state import DesignFormat


class PegasusStep(VendorTclStep):
    """
    Base class shared by every Pegasus step.

    ``binary`` is deliberately left at ``None``: Cadence's own support
    portal names the general pattern ("pvs/Pegasus command followed by
    -lvs, ...") but no full command line was retrievable, so neither the
    exact binary name (``pvs`` versus ``pegasus``) nor the complete flag set
    is confirmed. ``get_command()`` raises rather than guessing the rest of
    the command line from that partial pattern.
    """

    script_dir: ClassVar[str] = "pegasus"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: Pegasus's invocation is unestablished. "
            "Cadence's support portal states the general pattern "
            "'pvs/Pegasus command followed by -lvs, followed by "
            "command-line options and rule file(s)', which confirms "
            "'pvs' (legacy) or 'pegasus' (current) as the binary and "
            "'-lvs' as a real flag, but no complete command line was "
            "retrievable. See section 9 of "
            ".superpowers/sdd/2026-07-29-cad-tool-abstraction/"
            "vendor-python-apis.md."
        )


@Step.factory.register()
class DRC(PegasusStep):
    """
    Scaffold for the ``drc`` job using Pegasus.

    Unimplemented; see ``librelane/scripts/pegasus/drc.tcl``. Beyond the
    usual scaffold gap, Pegasus's own invocation is unestablished, so
    writing the script would not be sufficient by itself; see
    :meth:`PegasusStep.get_command`.

    Slots in beside ``Magic.DRC`` and ``KLayout.DRC``: Pegasus does not
    replace either open-source provider, it adds a third selectable one. A
    document runs one provider per job, so a flow that wants Pegasus
    alongside one of the others declares a second ``drc`` job pinning it, as
    ``classic.yaml`` does for Magic and KLayout.
    """

    id = "Pegasus.DRC"
    name = "Design Rule Checking (Pegasus)"

    script_filename: ClassVar[str] = "drc.tcl"

    inputs = [DesignFormat.DEF, DesignFormat.GDS]
    outputs = []


@Step.factory.register()
class LVS(PegasusStep):
    """
    Scaffold for the ``lvs`` job using Pegasus.

    Unimplemented; see ``librelane/scripts/pegasus/lvs.tcl``. Beyond the
    usual scaffold gap, Pegasus's own invocation is unestablished, so
    writing the script would not be sufficient by itself; see
    :meth:`PegasusStep.get_command`.

    An alternative to ``Netgen.LVS``: every shipped document declares ``lvs``
    once, so a flow selects one of the two via ``TOOLS``.
    """

    id = "Pegasus.LVS"
    name = "Layout Versus Schematic (Pegasus)"

    script_filename: ClassVar[str] = "lvs.tcl"

    inputs = [DesignFormat.DEF, DesignFormat.GDS, DesignFormat.POWERED_NETLIST]
    outputs = []


#: Registered by ``librelane/jobs/providers_vendor.py`` (owned by another
#: agent), not by this module.
_PEGASUS_NAMESPACES = (
    # The specific PEGASUS_* configuration variables a real Pegasus flow
    # would read are not enumerated anywhere in the research: no public
    # source lists them, and this scaffold declares none of its own. This
    # prefix reserves the namespace for whoever adds them once pegasus is
    # available to test against.
    "PEGASUS_",
)

REGISTRATIONS: list[dict] = [
    {
        "job": "drc",
        "provider": "pegasus",
        "steps": [DRC],
        "namespaces": _PEGASUS_NAMESPACES,
        # The `drc` job itself contracts no metrics (unlike `lvs`, see
        # below), so this registration declares none. Magic and KLayout
        # each contribute their own extra metric on top of their step's
        # DRC checker (magic__drc_error__count, klayout__drc_error__count);
        # Pegasus does not, since no Pegasus-specific metric name is
        # established, and inventing one here would be a guess.
        "metrics": [],
    },
    {
        "job": "lvs",
        "provider": "pegasus",
        "steps": [LVS],
        "namespaces": _PEGASUS_NAMESPACES,
        # The `lvs` job itself already contracts "design__lvs_error__count"
        # (see librelane/jobs/taxonomy.py); this reuses that job-level
        # metric rather than inventing a Pegasus-specific name.
        "metrics": ["design__lvs_error__count"],
    },
]
