<!--
Copyright 2026 LibreLane Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Swapping Tools

**_First of all_**, please review LibreLane's high-level architecture [at this
link](../reference/architecture.md). This page assumes you already know what a
`Flow` and a `Step` are.

## Stages

A `Flow` built on `StagedFlow`, such as `Classic`, is not written as one fixed
list of steps. It is written as a list of **stages**. A stage is a named phase
of the flow, such as `detailed_routing` or `streamout`, and it never executes
anything by itself. A *provider* registration binds a stage to the concrete
steps that actually implement it for one tool. This split is what makes a
stage the unit of three things at once: which tool runs a phase, whether that
phase can be turned off independently of every other phase, and where a flow
can be re-entered after handing off to a different tool. `Classic` and
`VHDLClassic` are both `StagedFlow`s; their `Stages` lists live in
`librelane/flows/classic.py`.

## The `TOOLS` configuration variable

`TOOLS` is a mapping from stage id to the provider that should implement it.
An entry you do not list keeps the stage's default provider; you only need to
name the stages you are changing.

Dropping Magic's stream-out and keeping only KLayout's:

```json
{
  "TOOLS": {
    "streamout": "klayout"
  }
}
```

Synthesizing from VHDL sources instead of Verilog:

```json
{
  "TOOLS": {
    "synthesis": "yosys_vhdl"
  }
}
```

```{important}
This second example only resolves on a flow whose `Stages` list has no plain
step that hard-requires a Verilog-only view. `Classic` does: several of its
steps consume the Verilog header that only `Yosys.JsonHeader` produces, so
`{"synthesis": "yosys_vhdl"}` on `Classic` is rejected at startup, naming the
missing view. Use the `VHDLClassic` flow instead, described below.
```

`TOOLS` is read by a pre-pass ahead of full configuration resolution, because
a flow's step set has to be known before the configuration those steps
declare can be validated. Two consequences follow from that ordering:

* `TOOLS` must be a literal mapping. `expr::`, `ref::` and other constructs
  the configuration preprocessor understands cannot appear inside it, because
  the preprocessor has not run yet.
* `TOOLS` is not read from Tcl configuration files, which need process
  information that is not resolved this early. Such a file is reported as
  unconsulted for tool selection rather than silently treated as empty.

An unknown stage id or an unknown provider name is rejected by name, with a
suggested correction for a near miss.

## `VHDLClassic`: a flow declared entirely as stages

`VHDLClassic` is the canonical demonstration of what a `Stages` list looks
like once tool selection is pulled out of it. It is not `Classic` with
`TOOLS` set: `Classic`'s own `Stages` list contains plain steps (the Verilog
header handling above) that a VHDL-only flow cannot run, so `VHDLClassic`
declares its own list rather than being reachable through `Classic`'s
configuration. What it shares with `Classic` is the mechanism: a `Stage`
object pinned to a provider with `Stage.using`.

```python
Stages = [
    Stage.synthesis.using("yosys_vhdl"),
    Stage.pre_pnr_sta,
    Stage.floorplan,
    Stage.macro_placement,
    OpenROAD.CutRows,
    Stage.tapcell_insertion,
    Stage.power_grid,
    # ...
    Stage.streamout,
    Magic.WriteLEF,
    # ...
    Stage.drc,
    Stage.lvs,
    # ...
]
```

`Stage.synthesis.using("yosys_vhdl")` returns a copy of the `synthesis` stage
whose default provider is pinned to `yosys_vhdl`, for use inside this one
flow's list. A pin is the flow's default, not a lock on what a user can still
request: a `TOOLS` entry for the same stage overrides the pin, because
resolution consults `TOOLS` before a stage's `default_provider`.

## The stage table

Every `StagedFlow` renders its resolved stage table in `get_help_md`, which
`librelane help <flow>` displays. This is `librelane help Classic`, current as
of this page:

| Stage | Default provider | Alternatives |
| --- | --- | --- |
| `lint` | `verilator` | none |
| `synthesis` | `yosys` | `yosys_vhdl` |
| `pre_pnr_sta` | `openroad` | none |
| `floorplan` | `openroad` | none |
| `macro_placement` | `openroad` | none |
| `tapcell_insertion` | `openroad` | none |
| `power_grid` | `openroad` | none |
| `io_placement` | `openroad` | none |
| `global_placement` | `openroad` | none |
| `post_gpl_repair` | `openroad` | none |
| `detailed_placement` | `openroad` | none |
| `cts` | `openroad` | none |
| `post_cts_opt` | `openroad` | none |
| `global_routing` | `openroad` | none |
| `post_grt_repair` | `openroad` | none |
| `antenna_repair` | `openroad` | none |
| `post_grt_opt` | `openroad` | none |
| `detailed_routing` | `openroad` | none |
| `post_route_opt` | none selected | none |
| `fill_insertion` | `openroad` | none |
| `extraction` | `openroad` | none |
| `signoff_sta` | `openroad` | none |
| `ir_drop` | `openroad` | none |
| `streamout` | `magic`, `klayout` | none |
| `drc` | `magic`, `klayout` | none |
| `lvs` | `netgen` | none |
| `formal_equivalence` | `yosys` | none |

`post_route_opt` shows `none selected`: it is an optional stage with no
default provider, so it contributes no steps unless `TOOLS` names one.

## Multi-provider stages

`streamout` and `drc` are the two stages where `Classic` runs two tools by
default rather than one. Both entries in `Stage.streamout.default_provider`
and `Stage.drc.default_provider` are lists, and `TOOLS` may name a list for
either, whose sequences are concatenated in listed order.

For `streamout`, both Magic and KLayout convert the routed `DEF` into a GDSII
stream, but only one of the two results becomes the neutral `gds` view that
every later step (`Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties`,
signoff) actually consumes; the other stays only as `mag_gds` or
`klayout_gds`. The `PRIMARY_GDSII_STREAMOUT_TOOL` configuration variable
decides which one is copied into `gds`. `KLayout.XOR` then compares the two
tools' GDSII outputs against each other, which is why dropping one streamout
provider without also disabling `RUN_KLAYOUT_XOR` fails the view preflight:
there is no second GDSII left to compare.

For `drc`, both providers run their own independent DRC deck and each
contracts its own metric (`magic__drc_error__count`,
`klayout__drc_error__count`). There is no "primary" concept here: dropping one
provider from `TOOLS` simply runs one deck instead of two, with no downstream
comparison step depending on the other.

## Setting many stages at once

A `Flow` accepts a sequence of configuration sources, layered in order with
later sources winning per top-level key
({func}`librelane.config.loading.layer_mappings`). Since `TOOLS` is a single
top-level key, a whole tool profile can be kept in one JSON file and passed
alongside a design's own configuration:

```json
// vendor_tools.json
{
  "TOOLS": {
    "synthesis": "genus",
    "detailed_placement": "innovus",
    "cts": "innovus",
    "detailed_routing": "innovus"
  }
}
```

```sh
librelane config.json vendor_tools.json
```

This replaces `config.json`'s `TOOLS` entirely rather than merging it
key-by-key with `vendor_tools.json`'s, because `layer_mappings` records the
last source for each top-level key as a whole; if `config.json` also sets
`TOOLS`, put every stage override you want in whichever file is layered last.

## Limitations

* `TOOLS` cannot come from the PDK. It is a literal mapping read ahead of the
  configuration preprocessor that resolves PDK-supplied values, so a PDK
  cannot express "use this vendor tool for floorplanning on this process."
* `TOOLS` cannot come from a Tcl configuration file, for the same reason: Tcl
  evaluation needs process information that is not available this early.
* View-level compatibility across a provider boundary is guaranteed; semantic
  compatibility is not. The view preflight confirms that the `DEF`, netlist,
  or `SDC` a provider hands off is present, but it cannot confirm that two
  vendors' placements, corners, or extraction models agree closely enough for
  the handoff to be meaningful. That judgment stays with whoever configures
  the mixed flow.

## The `antenna_repair` consequence

Stage selection governs which tool runs the *primary* flow of a stage, not
what a provider does internally to repair the perturbation its own tool
caused. `OpenROAD.RepairAntennas`, the sole step behind the `openroad`
provider of `antenna_repair` alongside diode insertion, re-runs OpenROAD's own
detailed placement and global routing to legalize the diodes it just
inserted. Selecting a different provider for `detailed_placement`, for
example Innovus, while leaving `antenna_repair` on `openroad` therefore means
OpenROAD's own detailed placement runs again inside antenna repair,
regardless of which tool placed the design the rest of the way. There is no
mechanism that routes a stage's internal legalization pass through a
different stage's selected provider; each provider is responsible for
whatever internal repair its own tool's pass requires.
