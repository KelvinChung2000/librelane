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
# Placeholder for the `synthesis` stage's Genus.Synthesis step.
#
# This file intentionally contains no executable Tcl. Genus.Synthesis.run()
# (inherited from VendorTclStep) raises NotImplementedError before this
# script would ever be invoked, because nobody with access to Genus has
# written the commands it should contain.
#
# What this script would need to do, once written:
#   - Read RTL, liberty and constraint locations from the configuration
#     variables TclStep.prepare_env() exports as environment variables (one
#     entry per accessible `self.config` key; see
#     librelane/steps/tclstep.py:prepare_env), plus the fixed variables it
#     always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS.
#   - Run Genus's synthesis flow (elaborate/synthesize to the target
#     library) and write a mapped Verilog netlist to the path given in the
#     SAVE_NL environment variable, which prepare_env() sets because
#     Genus.Synthesis declares DesignFormat.NETLIST as an output.
#
# No counterpart script exists in librelane/scripts/openroad/: synthesis is
# Yosys's domain in the open-source flow, and OpenROAD has no synthesis
# script to mirror. This filename describes the stage instead.
