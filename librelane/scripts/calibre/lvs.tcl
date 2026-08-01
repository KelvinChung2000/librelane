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
#
# Placeholder for Calibre.LVS (job "lvs").
#
# This file uses a ".tcl" extension only because Calibre's actual rule
# deck format is SVRF (Standard Verification Rule Format), not Tcl, and no
# public source establishes its syntax well enough to write correctly.
# ".tcl" was chosen, per the project's convention for this situation,
# because no correct extension could be established either; treat it as a
# placeholder, not a claim that a working Tcl script belongs here.
#
# TclStep.prepare_env() (librelane/steps/tclstep.py) would populate this
# file's environment with, among others: STEP_ID, SCRIPTS_DIR, STEP_DIR,
# TECH_LEF, MACRO_LEFS, every accessible self.config variable (as its Tcl
# representation), and CURRENT_DEF / CURRENT_GDS / CURRENT_PNL for this
# step's three declared inputs (DEF, GDS, and the powered netlist as the
# schematic side of the comparison). This step declares no outputs beyond
# job "lvs"'s own contract, which requires none.
#
# This file contains no rule-deck content. It was not written because
# Calibre was unavailable to the author, who had no licensed access to the
# tool or its documentation. Even Hammer's own Calibre integration code
# lives in a separate, access-gated repository rather than a public one
# (see librelane/steps/calibre.py's module docstring), which independently
# corroborates how little of this tool is publicly inspectable.
