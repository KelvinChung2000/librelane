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
# Placeholder for VCSpyGlass.Lint (job "lint").
#
# No open-source counterpart script name exists to mirror here. The
# job's other provider, Verilator.Lint, is not a TclStep and does not
# drive Verilator with a generated Tcl file at all. "lint.tcl" was chosen
# to describe the job plainly rather than to imply an established VC
# SpyGlass naming convention.
#
# TclStep.prepare_env() (librelane/steps/tclstep.py) would populate this
# script's environment with, among others: STEP_ID, SCRIPTS_DIR, STEP_DIR,
# TECH_LEF, MACRO_LEFS, and every accessible self.config variable (as its
# Tcl representation). This step declares no inputs and no outputs, matching
# job "lint"'s own empty contract; the design's RTL is expected to be
# read from the VERILOG_FILES (and equivalent) configuration variables, the
# same way Verilator.Lint reads it.
#
# This script contains no commands. It was not written because VC SpyGlass
# was unavailable to the author, who had no licensed access to the tool or
# its documentation. This is not the only gap. No public source establishes
# VC SpyGlass's invocation binary or command-line syntax at all (see
# librelane/steps/vc_spyglass.py and get_command(), which raises rather
# than guessing one), so even once this script exists, there would still be
# no established way to run VC SpyGlass against it.
