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
The Flow Module
---------------

An API for implementing new flows using the LibreLane infrastructure, as well
as a number of built-in flows.
"""

from importlib.resources import files

from librelane.flows.flow import FlowError, FlowException, FlowProgressBar, Flow
from librelane.flows.explanation import Explanation, StepDisposition
from librelane.flows.sequential import SequentialFlow
from librelane.flows.spec import load_flow_spec
from librelane.flows.staged import Boundary, StagedFlow
from librelane.flows import builtins

# Every workflow document shipped inside this package, registered the way the
# flow classes above register themselves: by importing the package.
#
# Sorted by name so the registration order is the same on every machine, which
# makes a duplicate-name error name the same document everywhere.
# ``load_flow_spec`` runs the structural checks only -- they do not touch the
# step or stage registries -- so this does not pull ``librelane.steps`` into
# this package's import graph. ``Workflow.__init__`` is where
# ``validate_against_registry`` runs.
for _document in sorted(files(__name__).iterdir(), key=lambda entry: entry.name):
    if _document.name.endswith(".yaml"):
        Flow.factory.register_document(load_flow_spec(str(_document)))
