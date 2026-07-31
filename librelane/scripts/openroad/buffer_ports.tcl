# Copyright 2026 LibreLane Contributors
#
# Adapted from OpenLane
#
# Copyright 2020-2023 Efabless Corporation
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
source $::env(SCRIPTS_DIR)/openroad/common/resizer.tcl

read_current_odb

unset_propagated_clock [all_clocks]

set_dont_touch_objects

# Set RC values so the buffers the resizer picks are sized against the same
# wire model the later repair steps use. Parasitics are not estimated: the
# cells this step runs before global placement have no locations yet.
source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl

if { $::env(DESIGN_REPAIR_BUFFER_INPUT_PORTS) } {
    log_cmd buffer_ports -inputs
}

if { $::env(DESIGN_REPAIR_BUFFER_OUTPUT_PORTS) } {
    log_cmd buffer_ports -outputs
}

unset_dont_touch_objects

write_views
