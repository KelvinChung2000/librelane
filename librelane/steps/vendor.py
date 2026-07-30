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
Shared base classes for commercial ("vendor") CAD tool provider scaffolds.

These are scaffolds, not implementations. The author of this module has no
access to any of the nineteen commercial tools these classes exist to support
(Cadence, Synopsys and Siemens's signoff and implementation tools) and no
licensed vendor documentation for them. Nothing here guesses a vendor command:
where a tool's invocation binary, CLI flags, or scripting API are not
established by a public source, that gap is represented explicitly rather
than papered over with a plausible-looking default.

Every step built on these base classes raises ``NotImplementedError`` from
``run()``. That is the intended state until someone with access to the actual
tool fills in the corresponding script (for :class:`VendorTclStep`
subclasses) or Python API calls (for :class:`VendorPythonStep` subclasses).
It is not a fallback: the step never launches a subprocess with guessed
arguments, never silently no-ops, and never produces output that looks like
it came from a real run. It fails loudly, before doing anything, with a
message that tells the reader exactly what is missing and where to put it.

Provenance for every tool's invocation binary, and for whether it has a
native Python API, is recorded per-tool in the research report at
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``.
Consult that report, not this module, for the evidence behind any given
tool's ``binary`` value (or lack of one).
"""

from abc import abstractmethod
from typing import ClassVar

from importlib.resources import files

from .step import Step, ViewsUpdate, MetricsUpdate
from .tclstep import TclStep
from ..common import protected
from ..state import State


class VendorTclStep(TclStep):
    """
    Base class for a Tcl-driven commercial tool step.

    Eleven of the nineteen tools surveyed in the research report are Tcl-only,
    each shelling out to its own binary with a Tcl script (comparable to how
    :class:`~librelane.steps.magic.MagicStep` drives ``magic``). This class
    holds what is common to all of them and nothing more.

    :cvar binary: The tool's invocation binary, e.g. ``"dc_shell"`` for Design
        Compiler. Defaults to ``None``, meaning no public source establishes
        it. Seven of the nineteen tools are in that state; leaving ``binary``
        unset is how a subclass represents that gap honestly rather than
        guessing a plausible-looking name.
    :cvar script_dir: The subdirectory of ``librelane/scripts`` this tool's
        scripts live in, e.g. ``"innovus"``. Not implemented by default; a
        concrete per-tool step must set it.
    :cvar script_filename: The filename of the Tcl script this step runs
        within ``script_dir``, e.g. ``"floorplan.tcl"``. Not implemented by
        default; a concrete per-tool step must set it.

    Subclasses **must** also override :meth:`get_command`, which is
    abstract here: a subclass that fails to define it cannot be
    instantiated at all, rather than silently inheriting
    :meth:`TclStep.get_command`'s ``["tclsh", script_path]`` default, which is
    wrong for every one of these tools and would never be exercised because
    :meth:`run` raises before ``get_command()`` is ever called. This base
    class deliberately provides no working implementation of its own:
    command-line syntax differs per tool (``dc_shell -f script.tcl`` versus
    ``innovus -nowin -common_ui -files par.tcl``), the research report
    establishes it for some tools and leaves it ``UNKNOWN`` for others, and
    guessing a flag here would look exactly as authoritative as a verified
    one to someone building on top of it. Write ``get_command()`` in the
    per-tool base class, using only what the research report actually
    establishes for that tool; for a tool whose invocation the report leaves
    ``UNKNOWN``, the override should itself raise ``NotImplementedError``
    naming what is unknown, rather than being omitted or guessed.
    """

    binary: ClassVar[str | None] = None
    script_dir: ClassVar[str] = NotImplemented
    script_filename: ClassVar[str] = NotImplemented

    def get_script_path(self) -> str:
        if self.script_dir is NotImplemented:
            raise NotImplementedError(
                f"{type(self).__name__} does not set 'script_dir': every "
                "VendorTclStep subclass must declare which subdirectory of "
                "librelane/scripts its Tcl script lives in before "
                "get_script_path() can compose a path."
            )
        if self.script_filename is NotImplemented:
            raise NotImplementedError(
                f"{type(self).__name__} does not set 'script_filename': "
                "every VendorTclStep subclass must declare the filename of "
                "the Tcl script it runs before get_script_path() can compose "
                "a path."
            )
        return str(
            files("librelane").joinpath(
                "scripts", self.script_dir, self.script_filename
            )
        )

    @protected
    @abstractmethod
    def get_command(self) -> list[str]:
        """
        Must be overridden by every :class:`VendorTclStep` subclass with the
        command line that invokes this specific tool.

        There is no default. Command-line syntax differs per tool, and
        inheriting :meth:`TclStep.get_command`'s ``["tclsh", script_path]``
        would be a wrong answer that looks like a right one. If the research
        report leaves this tool's invocation ``UNKNOWN``, override this
        method to raise ``NotImplementedError`` naming the class and stating
        that the command syntax is unestablished, rather than omitting the
        override.

        :returns: A list of strings representing the command used to run
            this tool against the script returned by :meth:`get_script_path`.
        """
        pass

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        script_path = self.get_script_path()
        message = (
            f"'{self.id}' is a scaffold and has no working implementation: "
            f"the Tcl script it is supposed to run, '{script_path}', has not "
            "been written. No vendor command is guessed here; someone with "
            "access to the tool needs to write that script (and give this "
            "step's class a get_command() that invokes the tool correctly) "
            "before this step can run."
        )
        if self.binary is None:
            message += (
                f" In addition, no public source establishes {type(self).__name__}'s "
                "invocation binary at all (see the provenance table in "
                "vendor-python-apis.md), so writing the script is not "
                "sufficient by itself — the binary name and its invocation "
                "syntax are also unknown and must be established before "
                "get_command() can be written."
            )
        raise NotImplementedError(message)


class VendorPythonStep(Step):
    """
    Base class for a commercial tool step driven by a native Python API,
    rather than a generated Tcl script.

    Of the nineteen tools surveyed, exactly one — Synopsys PrimeTime — is
    publicly documented to have such an API. **Provenance for that claim is
    weak and must be treated as such**: it rests on a single Synopsys blog
    post (``synopsys.com/blogs/chip-design/python-gui-builder-eda-tools.html``,
    dated 2024-07-09), with no third-party or open-source confirmation found
    anywhere (no OSS driver uses it, no Hammer plugin exists for PrimeTime at
    all). Contrast this with the Tcl findings in the same report, most of
    which have two independent sources (an open-source flow driver plus
    either a second driver or a vendor statement). One blog post is the
    entire evidentiary basis for this class existing; do not treat it as more
    solid than that.

    What the API is, per that blog post: a module named ``snps``, imported at
    ``pt_shell`` startup. Commands are invoked as methods on ``snps.cmd``
    (e.g. ``snps.cmd.report_timing()``-shaped calls). Return values are typed:
    ``int``/``float``, ``snps.collection`` (sequences of handles to database
    objects), or ``snps.value`` (Python strings/containers/dicts).

    What the API is **not**, and this is the part a future implementer is
    most likely to get wrong: there is no public evidence of building or
    mutating a design database from scratch the way OpenDB's ``dbDatabase``
    does. The ``snps.cmd`` surface mirrors PrimeTime's existing Tcl command
    set one-to-one; it is a typed-command interface with object-handle return
    values, not a from-scratch object model. Someone who designs this step's
    implementation as though ``snps`` were an OpenDB equivalent — building up
    a design by constructing and wiring together database objects rather
    than calling the equivalent of existing PrimeTime Tcl commands — will
    have designed the wrong thing.
    """

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        message = (
            f"'{self.id}' is a scaffold and has no working implementation: "
            "the PrimeTime 'snps' Python API calls for this stage have not "
            "been written. No API call is guessed here; someone with access "
            "to PrimeTime needs to write them, using snps.cmd.<command>() "
            "calls that mirror the equivalent Tcl commands, before this "
            "step can run."
        )
        raise NotImplementedError(message)
