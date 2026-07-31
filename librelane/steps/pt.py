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
Scaffold provider for Synopsys PrimeTime, signoff static timing analysis.

PrimeTime is the only one of the nineteen commercial tools surveyed for this
project with a publicly documented native Python API, so its steps are built
on :class:`~librelane.steps.vendor.VendorPythonStep` rather than
:class:`~librelane.steps.vendor.VendorTclStep`. There is deliberately no
``librelane/scripts/pt/`` directory. A PrimeTime step's eventual
implementation is a sequence of ``snps.cmd.<command>()`` calls written
directly in this module's ``run()`` overrides (there are none yet, since
``VendorPythonStep.run()`` already raises with the correct message), not a
generated Tcl file handed to a shell with ``-f``.

Provenance, repeated from ``vendor.py`` because it matters enough not to
lose in a docstring nobody reads twice. The existence of the ``snps`` module
rests on a single Synopsys blog post
(``synopsys.com/blogs/chip-design/python-gui-builder-eda-tools.html``,
2024-07-09), with no third-party or open-source confirmation found anywhere.
``pt_shell`` itself, as the binary that launches PrimeTime (and, per that
blog post, is where ``import snps`` happens), is corroborated more broadly
by tutorial and Hammer-adjacent material, so it is treated as confirmed here
even though the Python API layered on top of it is not.

The second thing worth restating plainly. ``snps.cmd`` mirrors PrimeTime's
existing Tcl command set one command at a time. It is not a from-scratch
object model comparable to OpenDB's ``dbDatabase``. An implementation that
tries to build or mutate a design database directly, rather than calling the
equivalent of an existing PrimeTime Tcl command through ``snps.cmd``, is
solving a problem PrimeTime's Python API was never shown to support.
"""

from librelane.state import DesignFormat
from librelane.steps.vendor import VendorPythonStep
from librelane.steps.step import Step


class PrimeTimeStep(VendorPythonStep):
    """
    Shared base for PrimeTime's two signoff stages.

    Both subclasses below are left with :meth:`VendorPythonStep.run`'s
    inherited ``NotImplementedError``. There is no script to point at, and no
    ``snps.cmd`` calls have been written, because the author had no access to
    PrimeTime. When someone with access implements one of these steps, the
    implementation belongs directly in an overridden ``run()`` here, built
    from ``snps.cmd.<command>()`` calls (see the module docstring above and
    :class:`~librelane.steps.vendor.VendorPythonStep` for what that surface
    is and, just as importantly, is not).
    """


@Step.factory.register()
class PreSTA(PrimeTimeStep):
    """
    Scaffold for pre-PnR static timing analysis using PrimeTime.

    Mirrors the neutral contract of the ``pre_pnr_sta`` stage.
    ``OpenROAD.STAPrePNR`` consumes the netlist and produces SDC, and this
    step is scaffolded to the same boundary so it is a drop-in alternative
    provider rather than one with a narrower or wider contract.
    """

    id = "PrimeTime.STAPrePNR"
    name = "STA (Pre-PnR, PrimeTime)"
    long_name = "Static Timing Analysis, Pre-PnR (PrimeTime)"

    inputs = [DesignFormat.NETLIST]
    outputs = [DesignFormat.SDC]


@Step.factory.register()
class SignoffSTA(PrimeTimeStep):
    """
    Scaffold for signoff static timing analysis using PrimeTime.

    Mirrors the neutral contract of the ``signoff_sta`` stage.
    ``OpenROAD.STAPostPNR`` consumes the placed-and-routed design plus
    extracted parasitics and produces no additional neutral views (its
    output is metrics and reports, not a view this stage's contract
    tracks).
    """

    id = "PrimeTime.SignoffSTA"
    name = "STA (Signoff, PrimeTime)"
    long_name = "Static Timing Analysis, Signoff (PrimeTime)"

    inputs = [
        DesignFormat.DEF,
        DesignFormat.NETLIST,
        DesignFormat.SDC,
        DesignFormat.SPEF,
    ]
    outputs = []


#: See the "Established facts" section of the research report and the
#: team's design discussion for the full reasoning; recorded here because
#: this is the Synopsys signoff module a reader auditing STA/power coverage
#: is most likely to check first.
#:
#: Synopsys PrimeRail (IR drop / power integrity signoff) is deliberately
#: NOT scaffolded anywhere in this batch of providers. Synopsys completed
#: its acquisition of Ansys on 2025-07-17, and Synopsys's own current public
#: product pages foreground Ansys's RedHawk-SC (and RedHawk-SC
#: Electrothermal) as the go-forward power-integrity signoff platform, with
#: planned integration into PrimeTime/Fusion Compiler/"PrimeClosure" rather
#: than PrimeRail. No public source states whether PrimeRail is being
#: retired, kept separate, or folded into RedHawk-SC. Scaffolding a provider
#: for the ``ir_drop`` stage under either product identity right now would
#: bake in a guess about an acquisition-driven product consolidation that is
#: still unresolved a few months after close; the stage already has a
#: working OpenROAD provider, so nothing is lost by waiting for that
#: question to actually resolve before adding a Synopsys one.

#: PrimeTime's configuration-variable prefix. The specific variable names
#: are unknown until someone with PrimeTime access enumerates what a real
#: implementation of these steps would need to read (corner selection,
#: report thresholds, and so on); "PT_" is reserved for them.
_PT_NAMESPACES = ("PT_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``StageRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "stage": "pre_pnr_sta",
        "provider": "pt",
        "steps": [PreSTA],
        "namespaces": _PT_NAMESPACES,
    },
    {
        "stage": "signoff_sta",
        "provider": "pt",
        "steps": [SignoffSTA],
        "namespaces": _PT_NAMESPACES,
    },
]
