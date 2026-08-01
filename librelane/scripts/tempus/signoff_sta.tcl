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
# Placeholder for the `signoff_sta` job's Tempus.SignoffSTA step.
#
# This file intentionally contains no executable Tcl. Tempus.SignoffSTA
# .run() (inherited from VendorTclStep) raises NotImplementedError before
# this script would ever be invoked, because nobody with access to Tempus
# has written the commands it should contain.
#
# What this script would need to do, once written:
#   - Read the placed-and-routed design and its parasitics from
#     CURRENT_DEF, CURRENT_NL, CURRENT_SDC and CURRENT_SPEF, the
#     environment variables TclStep.prepare_env() sets for this step's
#     declared inputs (see librelane/steps/tclstep.py:prepare_env), plus
#     the fixed variables it always sets: STEP_ID, SCRIPTS_DIR, STEP_DIR,
#     TECH_LEF, MACRO_LEFS, and one entry per accessible `self.config` key.
#   - Run signoff static timing analysis across every corner and report the
#     four metrics the `signoff_sta` job contracts: timing__setup_vio__count,
#     timing__hold_vio__count, design__max_slew_violation__count and
#     design__max_cap_violation__count. This step produces no views:
#     Tempus.SignoffSTA declares no outputs.
#
# No single named counterpart script exists in librelane/scripts/openroad/:
# OpenROAD.STAPostPNR shares scripts/openroad/sta/corner.tcl with
# OpenROAD.STAPrePNR through subclassing rather than a per-job filename.
# This filename is named for the job it implements instead.
