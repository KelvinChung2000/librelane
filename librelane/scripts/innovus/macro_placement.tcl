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
# Placeholder for the `macro_placement` job's Innovus.MacroPlacement step.
#
# This file intentionally contains no executable Tcl. Innovus.MacroPlacement
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
#   - Place macro instances and write only the updated DEF view to the path
#     in SAVE_DEF, which prepare_env() sets because Innovus.MacroPlacement
#     declares DesignFormat.DEF as its only output; the netlist and
#     constraints pass through unchanged.
#
# No counterpart script exists in librelane/scripts/openroad/: macro
# placement there is Odb.ManualMacroPlacement, a Python (odbpy) step, not a
# Tcl script. This filename describes the job instead.
