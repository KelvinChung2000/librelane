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
Cadence Conformal (formal verification) step scaffolds.

Conformal does formal equivalence checking (LEC) as its core use case, but
Hammer's plugin shows it is broader than a pure LEC point tool: it also
covers constraint/CDC checking, power intent checking, and ECO work.
Conformal ships two distinct binaries, selected by check type:

* ``conformal_lec_bin`` for LEC, power, ECO and property checks.
* ``conformal_ccd_bin`` for constraint and CDC checks.

Only ``conformal_lec_bin`` is used here, for the ``formal_equivalence``
stage; ``conformal_ccd_bin`` (constraint/CDC) has no matching stage in this
taxonomy and is not scaffolded.

No public source shows a native Python API for Conformal; Hammer's Cadence
plugin (``hammer/formal/conformal/__init__.py``) generates a Tcl "dofile"
and invokes ``$CONFORMAL_BIN -<LICENSE> -nogui -color -tclmode -dofile
<dofile.tcl>`` (with an optional ``-restart_checkpoint``). The ``-<LICENSE>``
token in that pattern is a placeholder for a license-related flag whose
concrete value is not stated anywhere in the research, so it is omitted here
rather than guessed; :meth:`ConformalStep.get_command` documents the gap.
This module builds on :class:`~librelane.steps.vendor.VendorTclStep`, not
:class:`~librelane.steps.vendor.VendorPythonStep`.

Every step here raises ``NotImplementedError`` from ``run()``, inherited
unmodified from ``VendorTclStep``. See the provenance in
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
section 10.
"""

from typing import ClassVar

from librelane.steps.step import Step
from librelane.steps.vendor import VendorTclStep
from librelane.state import DesignFormat


class ConformalStep(VendorTclStep):
    """
    Base class shared by every Conformal step.

    ``conformal_lec_bin`` is the LEC/power/ECO/property binary confirmed by
    Hammer's Cadence plugin (the other, ``conformal_ccd_bin``, handles
    constraint/CDC checks and is not used by any step in this module). The
    Hammer-confirmed invocation is ``$CONFORMAL_BIN -<LICENSE> -nogui
    -color -tclmode -dofile <dofile.tcl>``. The ``-<LICENSE>`` flag's
    concrete value is not established, so :meth:`get_command` omits it
    rather than guessing a license flag; the rest of the pattern is
    reproduced as confirmed.
    """

    binary: ClassVar[str] = "conformal_lec_bin"
    script_dir: ClassVar[str] = "conformal"

    def get_command(self) -> list[str]:
        return [
            self.binary,
            "-nogui",
            "-color",
            "-tclmode",
            "-dofile",
            self.get_script_path(),
        ]


@Step.factory.register()
class LEC(ConformalStep):
    """
    Scaffold for the ``formal_equivalence`` stage using Conformal's LEC
    binary.

    Unimplemented; see ``librelane/scripts/conformal/lec.tcl``.
    """

    id = "Conformal.LEC"
    name = "Formal Equivalence Checking (Conformal)"

    script_filename: ClassVar[str] = "lec.tcl"

    inputs = [DesignFormat.NETLIST]
    outputs = []


# Cadence RTL lint is deliberately not scaffolded anywhere in this batch of
# seven tools. An early guess named the product "HAL"; the research found
# that unconfirmed on the evidence of a single unfetchable forum thread
# title, with Cadence's actual, currently-documented public offering for
# this being the JasperGold Superlint App instead. Scaffolding a product
# that may not exist under a name nobody could verify is worse than leaving
# the gap open, so no `Cadence.Lint`-shaped module exists here. If RTL lint
# for Cadence is added later, start from JasperGold Superlint App, not
# "HAL". See section 11 of
# .superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md.

#: Registered by ``librelane/stages/providers_vendor.py`` (owned by another
#: agent), not by this module.
REGISTRATIONS: list[dict] = [
    {
        "stage": "formal_equivalence",
        "provider": "conformal",
        "steps": [LEC],
        # The specific CONFORMAL_* configuration variables a real Conformal
        # flow would read are not enumerated anywhere in the research: no
        # public source lists them, and this scaffold declares none of its
        # own. This prefix reserves the namespace for whoever adds them
        # once conformal_lec_bin is available to test against.
        "namespaces": ("CONFORMAL_",),
    },
]
