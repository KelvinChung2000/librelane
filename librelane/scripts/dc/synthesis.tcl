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
# Design Compiler (dc_shell) -- synthesis job scaffold.
#
# Implements: the 'synthesis' job (librelane/jobs/taxonomy.py), for the
# DC.Synthesis step (librelane/steps/dc.py).
#
# No OpenROAD Tcl script implements this job: OpenROAD does not run
# synthesis. This filename was chosen to describe the job rather than
# mirror an existing one.
#
# This script contains no commands. Design Compiler was not available to the
# author of this scaffold, so no dc_shell command in this file has been
# tested, and none is guessed here. DC.Synthesis.run() (inherited from
# VendorTclStep) raises NotImplementedError before this script would ever be
# invoked; this file exists purely to document what the real script needs to
# do once someone with dc_shell access writes it.
#
# Environment variables TclStep.prepare_env (librelane/steps/tclstep.py) will
# supply, once this script actually runs:
#   - every DC_* and common flow configuration variable, as an
#     environment variable of the same name (the specific DC_*
#     variables this job would need are not yet enumerated; see
#     librelane/steps/dc.py)
#   - TECH_LEF, MACRO_LEFS: PDK and macro LEF views
#   - SAVE_NL: the path this script must write its output netlist to
#
# View this script must produce, once written: a gate-level Verilog netlist
# (DesignFormat.NETLIST / 'nl'), written to $::env(SAVE_NL).
