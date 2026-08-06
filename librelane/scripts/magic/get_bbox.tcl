drc off
crashbackups disable
locking disable

gds read $::env(_GDS_IN)
load $::env(_MACRO_NAME_IN)
set curunits [units]
units internal
set bbox [property list FIXED_BBOX]
proc lln_metric_int {name value} {
    # One {"name": ..., "value": ...} JSON object per line, appended to the
    # sidecar file librelane reads back after this process exits.
    set f [open $::env(_LLN_METRICS_JSONL) a]
    puts $f "{\"name\": \"$name\", \"value\": $value}"
    close $f
}
if {$bbox != {}} {
    lln_metric_int llx [lindex $bbox 0]
    lln_metric_int lly [lindex $bbox 1]
    lln_metric_int urx [lindex $bbox 2]
    lln_metric_int ury [lindex $bbox 3]
}
units {*}$curunits
