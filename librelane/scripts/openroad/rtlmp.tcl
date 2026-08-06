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
source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
read_current_odb

set macro_placement_needed 0
foreach inst [$::block getInsts] {
    if { [[$inst getMaster] isBlock] && ![$inst isFixed] } {
        set macro_placement_needed 1
        break
    }
}

if { !$macro_placement_needed } {
    puts "\[INFO\] No unfixed macro instances found in the design."
    puts "\[INFO\] Skipping…"
    write_views
    exit_unless_gui
}

set report_dir $::env(STEP_DIR)/reports
file mkdir $report_dir

set arg_list [list]
if { [string length [namespace which set_macro_base_halo]] != 0 } {
    log_cmd set_macro_base_halo $::env(RTLMP_HALO_WIDTH) $::env(RTLMP_HALO_HEIGHT)
} else {
    lappend arg_list -halo_width $::env(RTLMP_HALO_WIDTH)
    lappend arg_list -halo_height $::env(RTLMP_HALO_HEIGHT)
}
lappend arg_list -report_directory $report_dir
append_if_exists_argument arg_list RTLMP_MAX_LEVEL -max_num_level
append_if_exists_argument arg_list RTLMP_TARGET_UTIL -target_util
append_if_exists_argument arg_list RTLMP_MIN_AR -min_ar
append_if_exists_argument arg_list RTLMP_TOLERANCE -tolerance
append_if_exists_argument arg_list RTLMP_COARSENING_RATIO -coarsening_ratio
append_if_exists_argument arg_list RTLMP_LARGE_NET_THRESHOLD -large_net_threshold
append_if_exists_argument arg_list RTLMP_AREA_WEIGHT -area_weight
append_if_exists_argument arg_list RTLMP_OUTLINE_WEIGHT -outline_weight
append_if_exists_argument arg_list RTLMP_WIRELENGTH_WEIGHT -wirelength_weight
append_if_exists_argument arg_list RTLMP_GUIDANCE_WEIGHT -guidance_weight
append_if_exists_argument arg_list RTLMP_FENCE_WEIGHT -fence_weight
append_if_exists_argument arg_list RTLMP_BOUNDARY_WEIGHT -boundary_weight
append_if_exists_argument arg_list RTLMP_NOTCH_WEIGHT -notch_weight
append_if_exists_argument arg_list RTLMP_MACRO_BLOCKAGE_WEIGHT -macro_blockage_weight

log_cmd rtl_macro_placer {*}$arg_list

write_views

report_design_area_metrics
