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
# Placeholder for the `pre_pnr_sta` job's Tempus.PrePNRSTA step.
#
# This file intentionally contains no executable Tcl. Tempus.PrePNRSTA
# .run() (inherited from VendorTclStep) raises NotImplementedError before
# this script would ever be invoked, because nobody with access to Tempus
# has written the commands it should contain.
#
# What this script would need to do, once written:
#   - Read the netlist from CURRENT_NL, the environment variable
#     TclStep.prepare_env() sets for this step's declared input (see
#     librelane/steps/tclstep.py:prepare_env), plus the fixed variables it
#     always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS, and
#     one entry per accessible `self.config` key.
#   - Run pre-placement static timing analysis and write an SDC view (the
#     derived/propagated constraints) to the path in SAVE_SDC, which
#     prepare_env() sets because Tempus.PrePNRSTA declares DesignFormat.SDC
#     as its only output.
#
# No single named counterpart script exists in librelane/scripts/openroad/:
# OpenROAD.STAPrePNR shares scripts/openroad/sta/corner.tcl with
# OpenROAD.STAPostPNR through subclassing rather than a per-job filename.
# This filename is named for the job it implements instead.
