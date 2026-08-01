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
# Placeholder for the `post_cts_opt` job's Innovus.PostCTSOpt step.
#
# This file intentionally contains no executable Tcl. Innovus.PostCTSOpt
# .run() (inherited from VendorTclStep) raises NotImplementedError before
# this script would ever be invoked, because nobody with access to Innovus
# has written the commands it should contain.
#
# What this script would need to do, once written:
#   - Read the placed-or-routed design from CURRENT_DEF, CURRENT_NL and
#     CURRENT_SDC, the environment variables TclStep.prepare_env() sets for
#     this step's declared inputs (see librelane/steps/tclstep.py:
#     prepare_env), plus the fixed variables it always sets: STEP_ID,
#     SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS, and one entry per
#     accessible `self.config` key.
#   - Optimize timing after clock tree synthesis and write DEF, netlist and
#     SDC views to the paths in SAVE_DEF, SAVE_NL and SAVE_SDC, which
#     prepare_env() sets because Innovus.PostCTSOpt declares all three as
#     outputs.
#
# Mirrors librelane/scripts/openroad/rsz_timing_postcts.tcl, which performs
# the same job with OpenROAD.
