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

## Jobs

A `Flow` built on `StagedFlow`, such as `Classic`, is not written as one fixed
list of steps. It is written as a list of **jobs**. A job is a named phase
of the flow, such as `detailed_routing` or `streamout`, and it never executes
anything by itself. A *provider* registration binds a job to the concrete
steps that actually implement it for one tool. This split is what makes a
job the unit of two things at once, which tool runs a phase and whether that
phase can be turned off independently of every other phase. `Classic` and
`VHDLClassic` are both `StagedFlow`s; their `Stages` lists live in
`librelane/flows/classic.py`.

## The `TOOLS` configuration variable

`TOOLS` is a mapping from job id to the provider that should implement it.
An entry you do not list keeps the provider the flow already chose; you only
need to name the jobs you are changing.

**A job id is the id the flow gives the job, which is not always the id of the
stage it runs.** A `StagedFlow` names each job after its stage, so the two
coincide there. A workflow document names its own jobs, and `classic.yaml`
runs the `streamout` stage under two of them, `magic_streamout` and
`klayout_streamout`. See
[Job ids in a workflow document](#job-ids-in-a-workflow-document).

Synthesizing from VHDL sources instead of Verilog:

```json
{
  "TOOLS": {
    "synthesis": "yosys_vhdl"
  }
}
```

```{important}
This only resolves on a flow whose `Stages` list has no plain
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

An unknown job id or an unknown provider name is rejected by name, with a
suggested correction for a near miss.

(job-ids-in-a-workflow-document)=

## Job ids in a workflow document

A workflow document (`librelane/flows/*.yaml`) declares a graph of named jobs,
each naming the stage it runs with a `uses` key. The name and the stage are
two different things, and `TOOLS` keys on the name:

```yaml
magic_streamout:
  uses: streamout/magic
  if: RUN_MAGIC_STREAMOUT
klayout_streamout:
  needs: [magic_streamout]
  uses: streamout/klayout
  if: RUN_KLAYOUT_STREAMOUT
```

`TOOLS: {magic_streamout: klayout}` runs the `streamout` stage's `klayout`
provider under the job still named `magic_streamout`. The job keeps its name,
because that name is what its `needs` edges, its `if` and its run directory
refer to.

`TOOLS: {streamout: klayout}` is rejected: `streamout` is a stage, and no job
of the document is called that. Two jobs for one stage is how a document
expresses two tools switched by two independent Booleans, which one job with a
list of providers could not: a job carries one `if`.

**So the way to run one stream-out rather than both is the Boolean, not
`TOOLS`.** To keep only KLayout's:

```json
{
  "RUN_MAGIC_STREAMOUT": false
}
```

The same holds for DRC, whose two jobs are `magic_drc` and `klayout_drc`,
gated by `RUN_MAGIC_DRC` and `RUN_KLAYOUT_DRC`. Re-pointing one of the pair at
the other's tool with `TOOLS` does not drop a tool, it runs the same deck
twice.

A `TOOLS` key naming a job that lists its steps inline is also rejected: an
inline job has no provider to override, and accepting the key would silently
do nothing.

## `VHDLClassic`: a flow declared entirely as jobs

`VHDLClassic` is the canonical demonstration of what a `Stages` list looks
like once tool selection is pulled out of it. It is not `Classic` with
`TOOLS` set: `Classic`'s own `Stages` list contains plain steps (the Verilog
header handling above) that a VHDL-only flow cannot run, so `VHDLClassic`
declares its own list rather than being reachable through `Classic`'s
configuration. What it shares with `Classic` is the mechanism: a `Job`
object pinned to a provider with `Job.using`.

```python
Stages = [
    Job.synthesis.using("yosys_vhdl"),
    Job.pre_pnr_sta,
    Job.floorplan,
    Job.macro_placement,
    OpenROAD.CutRows,
    Job.tapcell_insertion,
    Job.power_grid,
    # ...
    Job.streamout,
    Magic.WriteLEF,
    # ...
    Job.drc,
    Job.lvs,
    # ...
]
```

`Job.synthesis.using("yosys_vhdl")` returns a copy of the `synthesis` job
template whose default provider is pinned to `yosys_vhdl`, for use inside this
one flow's list. A pin is the flow's default, not a lock on what a user can
still request: a `TOOLS` entry for the same job overrides the pin, because
resolution consults `TOOLS` before a job's `default_provider`.

A document's `uses: synthesis/yosys_vhdl` is the same pin written in YAML, and
`TOOLS` overrides it the same way. What `TOOLS` never overrides is the stage
half of `uses`: a job keeps both its name and the stage it runs.

## The job table

Every `StagedFlow` renders its resolved job table in `get_help_md`, which
`librelane help <flow>` displays. This is `librelane help Classic`, current as
of this page:

| Job | Default provider | Alternatives |
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
| `lvs` | `netgen` | `klayout` |
| `formal_equivalence` | `yosys` | none |

`post_route_opt` shows `none selected`: it is an optional job with no
default provider, so it contributes no steps unless `TOOLS` names one.

## Multi-provider jobs

`streamout` and `drc` are the two jobs where `Classic` runs two tools by
default rather than one. Both entries in `Job.streamout.default_provider`
and `Job.drc.default_provider` are lists, and `TOOLS` may name a list for
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

```{note}
A list is a `StagedFlow` value only. A workflow document runs one provider per
job and expresses two tools as two jobs, so `TOOLS` names exactly one provider
there and a list is rejected with a message saying so.
```

## The two `lvs` providers write the same metric key

`lvs` is *not* a multi-provider job. Its two providers are alternatives, so
exactly one of them runs, and both write the job's contracted
`design__lvs_error__count`. That is what makes the key safe to share, and it
is also what makes the number's meaning depend on which provider ran.

| Provider | Sequence | What it compares | What the metric holds |
| --- | --- | --- | --- |
| `netgen` (default) | `Magic.SpiceExtraction`, `Checker.IllegalOverlap`, `Netgen.LVS`, `Checker.LVS` | a Magic-extracted SPICE netlist against the powered Verilog netlist | Netgen's count of mismatching cells and nets |
| `klayout` | `OpenROAD.WriteCDL`, `KLayout.LVS`, `Checker.LVS` | the GDSII against a CDL written from the OpenDB database | `0` if KLayout reported "netlists match", `1` otherwise |

So the KLayout number is a verdict, not a count. `Checker.LVS` thresholds at
zero and behaves identically either way, but any consumer that reads the
number itself, a metrics dashboard or a regression comparison, is reading two
different quantities. Which one produced it is recorded as the `lvs` entry of
the run's resolved `TOOLS`.

The two are also not equally deep. Netgen compares a netlist extracted from
the layout with connectivity and device parameters; the KLayout script
compares against a CDL and, for hierarchical designs, is the less complete of
the two. Selecting `klayout` is not a like-for-like substitution.

`KLayout.LVS` ships PDK-specific handling for `ihp-sg13g2` and
`ihp-sg13cmos5l` only. On any other PDK the step warns that it is unsupported
and returns no metric at all, at which point `Checker.LVS` warns that the
metric was not found and the run continues with no LVS result. Nothing selects
this provider for you.

```json
{
  "TOOLS": {
    "lvs": "klayout"
  }
}
```

`OpenROAD.WriteCDL` is part of the `klayout` sequence rather than a plain step
of `Classic`, for the same reason `Magic.SpiceExtraction` is part of the
`netgen` sequence: `KLayout.LVS` hard-requires the `cdl` view, no job
promises one, and a flow that never selects this provider should not be made
to write a CDL it has no use for.

## Setting many jobs at once

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
`TOOLS`, put every job override you want in whichever file is layered last.

## Limitations

* `TOOLS` cannot come from the PDK. It is a literal mapping read ahead of the
  configuration preprocessor that resolves PDK-supplied values, so a PDK
  cannot express "use this vendor tool for floorplanning on this process."
* `TOOLS` cannot come from a Tcl configuration file, for the same reason: Tcl
  evaluation needs process information that is not available this early.
* A job id is what `--target`, `--invalidate` and `--skip` name, so those are
  unaffected by a `TOOLS` change: `--target detailed_routing` means the same
  thing whichever router is selected. `--reproducible` is the exception,
  because it addresses one step inside a job rather than the job, so the step
  ID it names changes when `TOOLS` changes. Write it as
  `<job>/<step ID>` when a step ID runs in more than one job.
* A selection can put two writers of one key on two branches that a workflow
  document runs concurrently, and nothing rejects it before the run. Selecting
  `{"lvs": "klayout"}` is the shipped example: that provider opens with
  `OpenROAD.WriteCDL`, whose framework warning and error counts the `lvs` job's
  concurrent signoff peers carry unchanged from further up, so the join that
  merges them has two values and no rule for choosing. The run stops with a
  `JoinConflictError` naming the key. Re-pointing `magic_drc` at `klayout`, or
  `klayout_drc` at `magic`, does the same thing with that tool's DRC metric.
  `test/flows/test_documents.py` enumerates every such selection for the
  shipped documents.
* View-level compatibility across a provider boundary is guaranteed; semantic
  compatibility is not. The view preflight confirms that the `DEF`, netlist,
  or `SDC` a provider hands off is present, but it cannot confirm that two
  vendors' placements, corners, or extraction models agree closely enough for
  the handoff to be meaningful. That judgment stays with whoever configures
  the mixed flow.

## The `antenna_repair` consequence

Job selection governs which tool runs the *primary* flow of a job, not
what a provider does internally to repair the perturbation its own tool
caused. `OpenROAD.RepairAntennas`, the sole step behind the `openroad`
provider of `antenna_repair` alongside diode insertion, re-runs OpenROAD's own
detailed placement and global routing to legalize the diodes it just
inserted. Selecting a different provider for `detailed_placement`, for
example Innovus, while leaving `antenna_repair` on `openroad` therefore means
OpenROAD's own detailed placement runs again inside antenna repair,
regardless of which tool placed the design the rest of the way. There is no
mechanism that routes a job's internal legalization pass through a
different job's selected provider; each provider is responsible for
whatever internal repair its own tool's pass requires.
