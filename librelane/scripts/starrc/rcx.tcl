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
# Placeholder for StarRC.Extraction (stage "extraction").
#
# Named "rcx.tcl" to mirror librelane/scripts/openroad/rcx.tcl, the
# open-source counterpart for the same stage.
#
# TclStep.prepare_env() (librelane/steps/tclstep.py) would populate this
# script's environment with, among others: STEP_ID, SCRIPTS_DIR, STEP_DIR,
# TECH_LEF, MACRO_LEFS, every accessible self.config variable (as its Tcl
# representation), CURRENT_DEF (this step's one declared input), and
# SAVE_SPEF (this step's one declared output, the path this script would be
# expected to write a SPEF file to).
#
# This script contains no commands. It was not written because StarRC was
# unavailable to the author, who had no licensed access to the tool or its
# documentation. This is not the only gap. No public source establishes
# StarRC's invocation binary or command-line syntax at all (see
# librelane/steps/starrc.py and get_command(), which raises rather than
# guessing one), so even once this script exists, there would still be no
# established way to run StarRC against it.
