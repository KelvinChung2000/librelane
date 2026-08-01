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
# IC Compiler II (icc2_shell) -- io_placement job scaffold.
#
# Implements: the 'io_placement' job (librelane/jobs/taxonomy.py), for the
# ICC2.IOPlacement step (librelane/steps/icc2.py).
#
# Filename mirrors librelane/scripts/openroad/ioplacer.tcl, which
# implements the same job for the OpenROAD provider; no command or
# structure is carried over from that file.
#
# This script contains no commands. IC Compiler II was not available to the
# author of this scaffold, so no icc2_shell command in this file has been
# tested, and none is guessed here. ICC2.IOPlacement.run() (inherited from
# VendorTclStep) raises NotImplementedError before this script would ever be
# invoked; this file exists purely to document what the real script needs to
# do once someone with icc2_shell access writes it.
#
# Environment variables TclStep.prepare_env (librelane/steps/tclstep.py) will
# supply, once this script actually runs:
#   - CURRENT_DEF, CURRENT_NL, CURRENT_SDC: paths to this job's input views
#   - SAVE_DEF, SAVE_NL, SAVE_SDC: paths this script must write its output
#     views to
#   - TECH_LEF, MACRO_LEFS: PDK and macro LEF views
#   - every ICC2_* and common flow configuration variable, as an
#     environment variable of the same name (the specific ICC2_*
#     variables this job would need are not yet enumerated; see
#     librelane/steps/icc2.py)
#
# Views this script must produce, once written: DEF, netlist and SDC (see
# PNR_IN_PLACE_PROVIDES in librelane/jobs/job.py). IC Compiler II also
# carries a proprietary in-memory database across jobs, but its format is
# not publicly established (see librelane/steps/icc2.py and
# .superpowers/sdd/2026-07-29-cad-tool-abstraction/vendor-python-apis.md,
# section 13); declaring it as a DesignFormat is future work, not
# done here.
