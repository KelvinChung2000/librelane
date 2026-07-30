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
# Placeholder for the `lvs` stage's Pegasus.LVS step.
#
# This file intentionally contains no executable Tcl. Pegasus.LVS.run()
# (inherited from VendorTclStep) raises NotImplementedError before this
# script would ever be invoked, because nobody with access to Pegasus has
# written the commands it should contain.
#
# Unlike most scaffolds in this project, writing this script would not be
# sufficient by itself: Pegasus's invocation itself is not fully
# established by any public source (see PegasusStep.get_command in
# librelane/steps/pegasus.py). Cadence's own support portal states only the
# general pattern "pvs/Pegasus command followed by -lvs, followed by
# command-line options and rule file or set of rule files at the end", not
# a complete example, so the exact binary name and full flag set this
# script would need to be invoked with remain unknown.
#
# What this script would need to do, once the invocation is established:
#   - Read the streamed-out layout and its powered netlist from
#     CURRENT_DEF, CURRENT_GDS and CURRENT_PNL, the environment variables
#     TclStep.prepare_env() sets for this step's declared inputs (see
#     librelane/steps/tclstep.py:prepare_env), plus the fixed variables it
#     always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS,
#     and one entry per accessible `self.config` key.
#   - Run a Pegasus LVS deck comparing the layout against the schematic and
#     report the `design__lvs_error__count` metric, which the `lvs` stage
#     itself contracts. This step produces no views: Pegasus.LVS declares
#     no outputs.
#
# No static counterpart script exists in librelane/scripts/netgen/: Netgen
# LVS's Tcl script is generated dynamically by Netgen.LVS.get_script_path()
# rather than being a fixed file. This filename describes the stage
# instead.
