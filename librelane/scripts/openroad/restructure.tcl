# Copyright 2024 Efabless Corporation
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
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl

read_current_odb

# Timing-driven restructuring picks the paths to work on by slack and depth, so
# it needs the wire RC estimates the area target has no use for.
if { $::env(RMP_TARGET) == "timing" } {
    source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl
    estimate_parasitics -placement
}

set arg_list [list]
lappend arg_list -liberty_file $::env(_RMP_LIB)
lappend arg_list -target $::env(RMP_TARGET)
lappend arg_list -tiehi_port $::env(SYNTH_TIEHI_CELL)
lappend arg_list -tielo_port $::env(SYNTH_TIELO_CELL)
lappend arg_list -work_dir $::env(STEP_DIR)
lappend arg_list -abc_logfile $::env(_RMP_ABC_LOG)
if { [info exists ::env(RMP_SLACK_THRESHOLD)] } {
    lappend arg_list -slack_threshold $::env(RMP_SLACK_THRESHOLD)
}
if { [info exists ::env(RMP_DEPTH_THRESHOLD)] } {
    lappend arg_list -depth_threshold $::env(RMP_DEPTH_THRESHOLD)
}
log_cmd restructure {*}$arg_list

# ABC maps the cloud of logic it was handed without any notion of the buffering
# the netlist arrived with, so what survives is a mixture of two buffer trees.
# The repair and resizer steps rebuild it from the placed design.
if { $::env(RMP_REMOVE_BUFFERS) } {
    log_cmd remove_buffers
}

write_views
