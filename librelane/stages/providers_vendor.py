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
Provider registrations for the commercial ("vendor") CAD tool scaffolds.

Importing this module is the opt-in gesture. Nothing under
``librelane.stages`` registers these providers on its own: ``librelane/stages/
providers.py`` registers the open-source toolchain as a side effect of
``librelane/stages/__init__.py`` importing it, every time LibreLane starts.
This module is never imported from there, and must not be. A caller who wants
one of the sixteen commercial tools scaffolded here to appear as a stage
provider, for example in ``librelane help Classic`` or in ``StageRegistry.
providers("synthesis")``, has to write ``import librelane.stages.
providers_vendor`` themselves, once, before asking either question. Nothing
else in the package does that for them.

Every provider registered here is a scaffold. Its steps are built on
``VendorTclStep`` or ``VendorPythonStep`` (see ``librelane/steps/vendor.py``),
both of which raise ``NotImplementedError`` from ``run()`` unconditionally:
none of these sixteen tools has been exercised, because the authors of these
scaffolds had no access to any of them. No vendor command is guessed anywhere
in this module or in the sixteen modules it imports from. Where a tool's
invocation binary, CLI flags, or scripting API are not established by a
public source, that gap is represented explicitly, as documented per-tool in
the modules under ``librelane/steps/``.

Provenance for every tool surveyed lives in the research report at
``.superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md``,
a path outside the ``librelane`` package and not shipped with it. Consult
that report, not this module, for the evidence behind any given tool's
binary name or the presence or absence of a native Python API.

The registrations themselves are declared as data by each tool module and
applied here in a loop, the same shape ``librelane/stages/providers.py`` uses
for the open-source set. Keeping them as data in the tool modules, rather
than duplicating the shape here, is what let each tool's own module stay the
single owner of what it registers.
"""

from librelane.steps import (
    calibre,
    conformal,
    dc,
    fc,
    fm,
    genus,
    icc2,
    icv,
    innovus,
    pegasus,
    pt,
    quantus,
    starrc,
    tempus,
    vc_spyglass,
    voltus,
)

from librelane.stages.registry import StageRegistry

#: One module per commercial tool, each exporting its own ``REGISTRATIONS``.
#: Order is alphabetical by module name and carries no other meaning.
_VENDOR_MODULES = (
    calibre,
    conformal,
    dc,
    fc,
    fm,
    genus,
    icc2,
    icv,
    innovus,
    pegasus,
    pt,
    quantus,
    starrc,
    tempus,
    vc_spyglass,
    voltus,
)

_REGISTRATIONS: list[dict] = [
    entry for module in _VENDOR_MODULES for entry in module.REGISTRATIONS
]


for _entry in _REGISTRATIONS:
    StageRegistry.register(**_entry)
