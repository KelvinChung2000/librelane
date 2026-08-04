# Copyright 2023 Efabless Corporation
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
The Engine Module
-----------------

An API for implementing new flows using the LibreLane infrastructure, as well
as the engine that runs them. The flows themselves are workflow documents, and
the ones LibreLane ships live in ``librelane/share/``.
"""

from librelane.engine.flow import FlowError, FlowException, FlowProgressBar, Flow
from librelane.engine.explanation import (
    Explanation,
    JobDisposition,
    VariableDisposition,
)
from librelane.engine.spec import load_flow_spec
from librelane.engine.spec_include import share_directory

# Every workflow document shipped in ``librelane/share/``, registered by
# importing this package.
#
# That directory only: the documents there include fragments out of
# ``share/common/``, the library a document reaches with ``common::``, which
# declare no name and are nobody's flow. ``iterdir`` does not descend, so they
# are skipped by construction rather than by a filter someone has to maintain
# -- and a fragment put beside the documents by mistake would fail this loop
# loudly, which is the right outcome.
#
# Sorted by name so the registration order is the same on every machine, which
# makes a duplicate-name error name the same document everywhere.
# ``load_flow_spec`` runs the structural checks only -- they do not touch the
# step or job registries -- so this does not pull ``librelane.steps`` into
# this package's import graph. ``Workflow.__init__`` is where
# ``validate_against_registry`` runs.
for _document in sorted(share_directory().iterdir(), key=lambda entry: entry.name):
    if _document.name.endswith(".yaml"):
        Flow.factory.register(load_flow_spec(str(_document)))
