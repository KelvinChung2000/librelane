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
# Placeholder for Formality.FormalEquivalence (job "formal_equivalence").
#
# No open-source counterpart script name exists to mirror here. The
# job's other provider, Yosys.EQY, either uses a user-supplied script
# path or generates one at run time rather than shipping a static file
# under librelane/scripts. "formal_equivalence.tcl" was chosen to describe
# the job plainly rather than to imply an established Formality naming
# convention.
#
# TclStep.prepare_env() (librelane/steps/tclstep.py) would populate this
# script's environment with, among others: STEP_ID, SCRIPTS_DIR, STEP_DIR,
# TECH_LEF, MACRO_LEFS, every accessible self.config variable (as its Tcl
# representation), and CURRENT_NL (this step's one declared input). This
# step declares no outputs beyond job "formal_equivalence"'s own
# contract, which requires none; a real implementation's result is a
# pass/fail equivalence verdict, not a design-format view.
#
# This script contains no commands. It was not written because Formality
# was unavailable to the author, who had no licensed access to the tool or
# its documentation.
