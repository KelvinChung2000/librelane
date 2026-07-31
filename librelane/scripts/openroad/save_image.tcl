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

set args [list]

lappend args -width $::env(_SAVE_IMAGE_WIDTH)

if { [info exists ::env(_SAVE_IMAGE_RESOLUTION)] && $::env(_SAVE_IMAGE_RESOLUTION) != "" } {
    lappend args -resolution $::env(_SAVE_IMAGE_RESOLUTION)
}

if { [info exists ::env(_SAVE_IMAGE_AREA)] && $::env(_SAVE_IMAGE_AREA) != "" } {
    lappend args -area $::env(_SAVE_IMAGE_AREA)
}

# Each entry is a {control value} pair, e.g. {Nets/Power false}. save_image
# accepts -display_option repeatedly and folds them into one map.
foreach option $::env(_SAVE_IMAGE_DISPLAY_OPTIONS) {
    lappend args -display_option $option
}

save_image {*}$args $::env(_SAVE_IMAGE_OUTPUT)
puts "Wrote $::env(_SAVE_IMAGE_OUTPUT)."
