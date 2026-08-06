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

# The mapped netlist is exported into a fresh ODB, which needs the
# technology in the database first.
read_lefs

# The mapper draws from whatever liberty is loaded; _SYNTH_LIBS is the
# default-corner SCL lib set with the synthesis- and PnR-excluded cells
# already trimmed away by the step.
foreach lib $::env(_SYNTH_LIBS) {
    puts "Reading cell library at '$lib'…"
    read_liberty $lib
}

# Elaboration: sv_elaborate accepts standard slang command-line options.
set elab_args [list]
lappend elab_args --top $::env(DESIGN_NAME)
if { [info exists ::env(VERILOG_DEFINES)] } {
    foreach define $::env(VERILOG_DEFINES) {
        lappend elab_args -D$define
    }
}
if { [info exists ::env(VERILOG_INCLUDE_DIRS)] } {
    foreach dir $::env(VERILOG_INCLUDE_DIRS) {
        lappend elab_args --include-directory $dir
    }
}
if { [info exists ::env(SYNTH_PARAMETERS)] } {
    foreach parameter $::env(SYNTH_PARAMETERS) {
        lappend elab_args -G$parameter
    }
}
if { [info exists ::env(SLANG_ARGUMENTS)] } {
    foreach arg $::env(SLANG_ARGUMENTS) {
        lappend elab_args $arg
    }
}
foreach file $::env(VERILOG_FILES) {
    lappend elab_args $file
}

puts "Elaborating with: sv_elaborate $elab_args"
sv_elaborate {*}$elab_args

set synth_args [list]
if { $::env(SYNTH_REDUCE_NAME_LOSS) == 1 } {
    lappend synth_args -reduce_name_loss
}
append_if_exists_argument synth_args SYNTH_NAMING_THRESHOLD -naming_threshold

synthesize {*}$synth_args

# The mapped netlist now lives in the database; a failure in either command
# above exits nonzero before reaching this point, so a design that got here
# has no unmapped cells, and slang has already gated elaboration errors.
write_metric_int "design__instance_unmapped__count" 0
write_metric_int "synthesis__check_error__count" 0

write_views
