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
# Placeholder for the `extraction` stage's Quantus.Extraction step.
#
# This file intentionally contains no executable Tcl. Quantus.Extraction
# .run() (inherited from VendorTclStep) raises NotImplementedError before
# this script would ever be invoked, because nobody with access to Quantus
# has written the commands it should contain.
#
# Unlike the other scaffolds in this project, writing this script would not
# be sufficient by itself: Quantus's invocation binary itself is not
# established by any public source (see QuantusStep.get_command in
# librelane/steps/quantus.py), so the command line that would run this
# script is also unknown, not only its contents.
#
# What this script would need to do, once the invocation is established:
#   - Read the placed-and-routed design from CURRENT_DEF, CURRENT_NL and
#     CURRENT_SDC, the environment variables TclStep.prepare_env() sets for
#     this step's declared inputs (see librelane/steps/tclstep.py:
#     prepare_env), plus the fixed variables it always sets: STEP_ID,
#     SCRIPTS_DIR, STEP_DIR, TECH_LEF, MACRO_LEFS, and one entry per
#     accessible `self.config` key.
#   - Run parasitic extraction and write one SPEF file per timing corner.
#     DesignFormat.SPEF is a "multiple" view (see design_format.py), so
#     TclStep.prepare_env() does not set a SAVE_SPEF variable for it; a real
#     Quantus.Extraction.run() would need to override run() to place the
#     per-corner files itself and report them as views, the way
#     OpenROAD.RCX (librelane/steps/openroad/finishing.py) does.
#
# Mirrors librelane/scripts/openroad/rcx.tcl, which performs the same stage
# with OpenROAD.
