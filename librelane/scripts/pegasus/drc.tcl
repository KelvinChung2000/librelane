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
# Placeholder for the `drc` job's Pegasus.DRC step.
#
# This file intentionally contains no executable Tcl. Pegasus.DRC.run()
# (inherited from VendorTclStep) raises NotImplementedError before this
# script would ever be invoked, because nobody with access to Pegasus has
# written the commands it should contain.
#
# Unlike most scaffolds in this project, writing this script would not be
# sufficient by itself: Pegasus's invocation itself is not fully
# established by any public source (see PegasusStep.get_command in
# librelane/steps/pegasus.py). Cadence's own support portal confirms
# "pvs" or "pegasus" as the binary and "-lvs" as a real flag for the LVS
# case, but states no equivalent DRC invocation pattern, so even the flag
# this script would need to be invoked with is unknown, not only its
# contents.
#
# What this script would need to do, once the invocation is established:
#   - Read the streamed-out layout from CURRENT_DEF and CURRENT_GDS, the
#     environment variables TclStep.prepare_env() sets for this step's
#     declared inputs (see librelane/steps/tclstep.py:prepare_env), plus
#     the fixed variables it always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR,
#     TECH_LEF, MACRO_LEFS, and one entry per accessible `self.config` key.
#   - Run a Pegasus DRC deck against the layout and report the results.
#     This step produces no views: Pegasus.DRC declares no outputs, and the
#     `drc` job itself contracts no metrics.
#
# Mirrors librelane/scripts/magic/drc.tcl, which performs the same job
# with Magic.
