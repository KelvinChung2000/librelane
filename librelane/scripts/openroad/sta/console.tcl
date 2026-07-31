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

# Loads one corner of the design into OpenSTA and then leaves the interpreter
# to the user: the step invokes OpenSTA without -exit.

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl

set_cmd_units\
    -time ns\
    -capacitance pF\
    -current mA\
    -voltage V\
    -resistance kOhm\
    -distance um

set sta_report_default_digits 6

read_timing_info
read_spefs

foreach {corner_name corner_object} [lln::get_corner_dict] {
    lln::set_sta_cmd_corner $corner_name
    puts "Design '$::env(DESIGN_NAME)' is loaded for the '$corner_name' corner."
    break
}

puts "Type 'exit' or press Ctrl+D to end the session."
