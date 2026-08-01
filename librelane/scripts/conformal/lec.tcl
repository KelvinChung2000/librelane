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
# Placeholder for the `formal_equivalence` job's Conformal.LEC step.
#
# This file intentionally contains no executable Tcl. Conformal.LEC.run()
# (inherited from VendorTclStep) raises NotImplementedError before this
# script would ever be invoked, because nobody with access to Conformal has
# written the commands it should contain.
#
# What this script (a Conformal "dofile", per Hammer's plugin) would need to
# do, once written:
#   - Read the netlist from CURRENT_NL, the environment variable
#     TclStep.prepare_env() sets for this step's declared input (see
#     librelane/steps/tclstep.py:prepare_env), plus the fixed variables it
#     always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS, and
#     one entry per accessible `self.config` key.
#   - Read a golden/reference design (pre-synthesis RTL, or a prior
#     netlist, depending on what this job is checking against) and run
#     Conformal's LEC comparison between it and CURRENT_NL. This step
#     produces no views: Conformal.LEC declares no outputs, and the
#     `formal_equivalence` job itself contracts no metrics.
#
# No counterpart script exists in librelane/scripts/yosys/ with a matching
# name: Yosys.EQY, which implements the same job in the open-source flow,
# drives the external `eqy` tool through its own config-file generator
# rather than a single named Tcl script. This filename describes the job
# instead.
