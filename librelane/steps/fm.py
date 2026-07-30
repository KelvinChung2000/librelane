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
Scaffold provider for Synopsys Formality, formal equivalence checking.

``fm_shell`` is directly confirmed as Formality's invocation binary, stated
plainly by a university/tutorial source describing real usage ("The
``fm_shell`` command starts the Formality shell environment"), which also
gives example interactive Tcl commands (``read_db``, ``read_verilog``,
``set_top``). What that source does not give, and what no other source in
the research report supplies either, is a batch-mode command line, meaning
any flag for pointing ``fm_shell`` at a script file rather than typing
commands interactively. A confirmed binary with no confirmed way to hand it
a script is still a blocking gap, not a partial answer. A command line that
launches ``fm_shell`` and stops there would, in a batch context, hang
waiting on an interactive prompt rather than running this step's script, so
:meth:`FormalityStep.get_command` raises rather than returning that
half-complete, plausible-looking command line. Guessing a flag such as
``-f`` by analogy with other Synopsys shells would be exactly the kind of
default this scaffold exists to avoid; other Synopsys Tcl shells in the
research report that do have a confirmed ``-f``-style flag (``dc_shell``)
have it because an open-source driver was found actually using it, not by
analogy.
"""

from ..state import DesignFormat
from .vendor import VendorTclStep
from .step import Step


class FormalityStep(VendorTclStep):
    """
    Shared base for Formality's one covered stage, formal equivalence
    checking.
    """

    binary = "fm_shell"
    script_dir = "fm"

    def get_command(self) -> list[str]:
        raise NotImplementedError(
            f"{type(self).__name__}: fm_shell is confirmed as Formality's "
            "invocation binary, but no public source establishes how to "
            "point it at a script non-interactively (no -f-style flag, or "
            "equivalent, is confirmed for fm_shell specifically). Someone "
            "with access to the tool needs to establish the actual "
            "invocation before this step can be invoked."
        )


@Step.factory.register()
class FormalEquivalence(FormalityStep):
    """
    Scaffold for RTL-versus-netlist (or netlist-versus-netlist) formal
    equivalence checking using Formality.

    Mirrors ``Yosys.EQY``'s neutral contract for the ``formal_equivalence``
    stage. It consumes the netlist and produces no additional neutral
    views.
    """

    id = "Formality.FormalEquivalence"
    name = "Formal Equivalence Check (Formality)"
    long_name = "Formal Equivalence Checking (Formality)"

    script_filename = "formal_equivalence.tcl"

    inputs = [DesignFormat.NETLIST]
    outputs = []


#: Formality's configuration-variable prefix. The specific variable names
#: are unknown until someone with Formality access enumerates what a real
#: implementation of this step would need to read; "FM_" is reserved for
#: them.
_FM_NAMESPACES = ("FM_",)

#: Registrations for the aggregator to fold into the opt-in vendor-provider
#: module. Not applied here. This module does not call
#: ``StageRegistry.register`` itself.
REGISTRATIONS: list[dict] = [
    {
        "stage": "formal_equivalence",
        "provider": "fm",
        "steps": [FormalEquivalence],
        "namespaces": _FM_NAMESPACES,
    },
]
