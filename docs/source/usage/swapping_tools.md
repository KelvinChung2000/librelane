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

A flow, such as `Classic`, is not written as one fixed list of steps. It is
written as a graph of **jobs**. A job is a named phase of the flow, such as
`detailed_routing` or `streamout`, and it never executes anything by itself.
A *provider* registration binds a job's template to the concrete steps that
actually implement it for one tool. This split is what makes a job the unit of
two things at once, which tool runs a phase and whether that phase can be
turned off independently of every other phase. `Classic` and `VHDLClassic` are
workflow documents; they live in `librelane/flows/classic.yaml` and
`librelane/flows/vhdl_classic.yaml`.

## The `TOOLS` configuration variable

`TOOLS` is a mapping from job id to the provider that should implement it.
An entry you do not list keeps the provider the flow already chose; you only
need to name the jobs you are changing.

**A job id is the id the document gives the job, which is not always the id of
the stage it runs.** A document names its own jobs, and `classic.yaml` runs the
`streamout` stage under two of them, `magic_streamout` and `klayout_streamout`.
See [Job ids in a workflow document](#job-ids-in-a-workflow-document).

Synthesizing from VHDL sources instead of Verilog:

```json
{
  "TOOLS": {
    "synthesis": "yosys_vhdl"
  }
}
```

```{important}
`Classic` cannot run that selection. `Odb.SetPowerConnections` and
`Odb.WriteVerilogHeader` consume the `json_h` view that only
`Yosys.JsonHeader` produces, and that step belongs to the `synthesis` job's
`yosys` provider rather than to `yosys_vhdl`. Use the `VHDLClassic` flow,
described below: it is the same selection, made by the document instead of by a
configuration.

`Classic` refuses the entry at load, naming `json_h` and the job that requires
it. Earlier versions accepted it and failed during the run at the first step
that could not find the header.
```

Every refusal on this page describes a run that starts from nothing. A run given
`--with-initial-state` starts from the views that state holds, and a selection
that only drops views the state already carries is not refused: see
[What is checked, and when](#what-is-checked-when).

**What can be selected at all is the Alternatives column of
[the job table](#the-job-table)**, which is every registered provider of a
job's template other than the one the flow already resolves to. It is a short
list, because LibreLane ships one open-source provider for most phases.

Two cautions before reaching for an entry in it. Several of the alternatives
collide with the shipped documents' job graph rather than with the tool, and
those are enumerated under
[Selections the shipped documents refuse](#selections-the-shipped-documents-refuse).
Every one of them is refused while the flow loads, so the caution is about which
entries are worth writing, not about what a bad one costs. And the sixteen
commercial providers are scaffolds whose steps raise `NotImplementedError`;
nothing registers them until your own code imports
`librelane.jobs.providers_vendor`, so until it does they are absent from the
table below and from `librelane help`. Once it does, they are selectable but
still not runnable, so a refusal never offers one as the alternative that
would work. See
[Commercial CAD tool scaffolds](./writing_tool_backends.md#commercial-cad-tool-scaffolds).

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

(what-is-checked-when)=

## What is checked, and when

Three passes run before any tool does, in this order.

1. **The document's own structure**, against the registries. Every job id,
   provider name and step ID must resolve, every job's non-optional inputs must
   be produced somewhere above it, and no fan-in may leave two producers of one
   key unresolved. This reads what the *document* declares, so it says nothing
   about `TOOLS`.
2. **The configuration**, resolved against the variables the selected steps
   declare. `TOOLS` is read by a pre-pass ahead of this, because the step set
   decides which variables exist.
3. **The selection**, against what actually resolved. This is the only pass that
   can see a `TOOLS` entry, and it is the one that refuses the selections below.

The third pass asks two questions:

* **Did the selection remove a view something still needs?** A view the
  document's own providers produce upstream of a job, and the selected ones do
  not, is refused, naming the view, the job that needs it and the job that used
  to produce it. A registration's `native_views`, such as OpenROAD's `odb`,
  count here exactly as a declared requirement does.
* **Did the selection put two writers of one key on concurrent branches?** If
  so the run would stop with a `JoinConflictError` when those branches met, so
  it stops now instead, naming the key, both jobs and every provider that would
  work in place of the one selected.

Both questions are asked of the jobs that *will run*. A job whose `if` is false
fires as a pass-through and writes nothing, so turning one side of a collision
off with its Boolean makes the selection loadable — which matters, because that
Boolean is usually the real answer.

The first question is also asked of the state the run starts from. The views
`--with-initial-state` supplies are available to every job, so a selection that
stops producing one of them has taken nothing away and is not refused: resuming
a `Classic` run with a `json_h` in the state makes `{"synthesis": "yosys_vhdl"}`
loadable, and the alternatives a refusal offers are measured with that state in
hand too. A view the state maps to `null` is not supplied, which is the same
reading the step that consumes it gives.

Two things it deliberately does not know about. It cannot see `--target`,
`--skip` or `--reproducible`, which shape one invocation rather than the
configuration and, unlike the initial state, are not known when the flow is
constructed; and it reasons about views and keys, never about whether two tools'
results are *semantically* compatible.

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

## `VHDLClassic`: a document that pins a provider

`VHDLClassic` is the canonical demonstration of a document choosing a tool for
itself. It is not `Classic` with `TOOLS` set: `Classic`'s graph contains jobs
(the Verilog header handling above) that a VHDL-only flow cannot run, so
`VHDLClassic` declares its own graph rather than being reachable through
`Classic`'s configuration. What it shares with `Classic` is the mechanism, a
`uses` naming a provider as well as a template:

```yaml
jobs:
  synthesis:
    uses: synthesis/yosys_vhdl
  pre_pnr_sta:
    needs: [synthesis]
    uses: pre_pnr_sta
  floorplan:
    needs: [pre_pnr_sta]
    uses: floorplan
  # ...
```

`uses: synthesis/yosys_vhdl` runs the `synthesis` template's `yosys_vhdl`
provider. A pin is the document's default, not a lock on what a user can still
request: a `TOOLS` entry for the same job overrides it, because resolution
consults `TOOLS` before a job's `default_provider`. What `TOOLS` never overrides
is the template half of `uses`: a job keeps both its name and the phase it
implements.

## The job table

`librelane help <flow>` prints the flow's resolved job table, which is what
`Workflow.get_help_md` renders from the document. This is `librelane help
Classic`, current as of this page:

| Job | Template | Provider | Alternatives |
| --- | --- | --- | --- |
| `lint` | `lint` | `verilator` | none |
| `synthesis` | `synthesis` | `yosys` | `yosys_vhdl` |
| `pre_pnr_sta` | `pre_pnr_sta` | `openroad` | none |
| `floorplan` | `floorplan` | `openroad` | none |
| `rmp` | inline steps | | |
| `set_power_connections` | inline steps | | |
| `macro_placement` | `macro_placement` | `openroad` | none |
| `tapcell_insertion` | `tapcell_insertion` | `openroad` | none |
| `power_grid` | `power_grid` | `openroad` | none |
| `io_placement` | `io_placement` | `openroad` | none |
| `add_buffer` | inline steps | | |
| `global_placement` | `global_placement` | `openroad` | none |
| `post_gpl_checks` | inline steps | | |
| `post_gpl_repair` | `post_gpl_repair` | `openroad` | none |
| `detailed_placement` | `detailed_placement` | `openroad` | none |
| `cts` | `cts` | `openroad` | none |
| `sta_mid_pnr_2` | inline steps | | |
| `post_cts_opt` | `post_cts_opt` | `openroad` | none |
| `sta_mid_pnr_3` | inline steps | | |
| `global_routing` | `global_routing` | `openroad` | none |
| `post_grt_repair` | `post_grt_repair` | `openroad` | none |
| `diodes_on_ports` | inline steps | | |
| `heuristic_diode_insertion` | inline steps | | |
| `repair_antennas` | inline steps | | |
| `post_grt_opt` | `post_grt_opt` | `openroad` | none |
| `sta_mid_pnr_4` | inline steps | | |
| `detailed_routing` | `detailed_routing` | `openroad` | none |
| `routing_reports` | inline steps | | |
| `fill_insertion` | `fill_insertion` | `openroad` | none |
| `cell_frequency_tables` | inline steps | | |
| `extraction` | `extraction` | `openroad` | none |
| `signoff_sta` | `signoff_sta` | `openroad` | none |
| `ir_drop` | `ir_drop` | `openroad` | none |
| `magic_streamout` | `streamout` | `magic` | `klayout` |
| `klayout_streamout` | `streamout` | `klayout` | `magic` |
| `render` | inline steps | | |
| `write_lef` | inline steps | | |
| `check_antenna_properties` | inline steps | | |
| `xor` | inline steps | | |
| `magic_drc` | `drc` | `magic` | `klayout` |
| `klayout_drc` | `drc` | `klayout` | `magic` |
| `lvs` | `lvs` | `netgen` | `klayout` |
| `formal_equivalence` | `formal_equivalence` | `yosys` | none |
| `final_checks` | inline steps | | |

Three things about this table follow from a document naming its own jobs. The
**Job** column is the id the document chose, so one template appears under two
names wherever the flow runs it twice, as
`streamout` and `drc` do. The **Template** column is the phase that job
implements, which is what a provider registers against. And a job that lists
its steps inline has no provider to name, so `TOOLS` cannot address it and its
two right-hand cells are empty.

`post_route_opt` has no row at all. It is a registered template with no
provider, so no document declares a job for it, and a template no job uses
cannot appear in a table of jobs.

## Two tools for one phase

A job runs one provider. A template has one `default_provider`, `uses` names
one, and `TOOLS` overrides it with one; a list value is rejected with a message
saying so. A flow that wants two tools for the same phase declares **two jobs**
against the same template, pinning a provider on each, which is what `Classic`
does for `streamout` and `drc`:

```yaml
  magic_streamout:
    uses: streamout/magic
    if: RUN_MAGIC_STREAMOUT
  klayout_streamout:
    needs: [magic_streamout]
    uses: streamout/klayout
    if: RUN_KLAYOUT_STREAMOUT
```

Two jobs rather than one is what makes `RUN_MAGIC_STREAMOUT` and
`RUN_KLAYOUT_STREAMOUT` independent: an `if` is a property of a job, so one
job could carry only one of them. It is also what puts both tools in the job
table under their own names, each separately re-pointable by `TOOLS`.

For `streamout`, both Magic and KLayout convert the routed `DEF` into a GDSII
stream, but only one of the two results becomes the neutral `gds` view that
every later step (`Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties`,
signoff) actually consumes; the other stays only as `mag_gds` or
`klayout_gds`. The `PRIMARY_GDSII_STREAMOUT_TOOL` configuration variable
decides which one is copied into `gds`. `KLayout.XOR` then compares the two
tools' GDSII outputs against each other, and requires both. Turning a
stream-out off with its Boolean is safe, because the documents gate `xor` on
all three of `RUN_KLAYOUT_XOR`, `RUN_MAGIC_STREAMOUT` and
`RUN_KLAYOUT_STREAMOUT`, so the comparison goes with the thing it compares.
Re-pointing one stream-out at the other's tool is not: `xor` still runs and
there is no second GDSII left for it, which is why that selection is refused at
load.

For `drc`, both jobs run their own independent DRC deck and each contracts its
own metric (`magic__drc_error__count`, `klayout__drc_error__count`). There is
no "primary" concept here: turning one off simply runs one deck instead of
two, with no downstream comparison step depending on the other.

Both templates default to `magic`, so a document that declares `streamout` or
`drc` once and pins nothing gets Magic. No shipped document does that.

## The two `lvs` providers write the same metric key

Every shipped document declares `lvs` once, so its two providers are
alternatives: exactly one of them runs, and both write the job's contracted
`design__lvs_error__count`. That is what makes the key safe to share, and it
is also what makes the number's meaning depend on which provider ran.

| Provider | Sequence | What it compares | What the metric holds |
| --- | --- | --- | --- |
| `netgen` (default) | `Magic.SpiceExtraction`, `Netgen.LVS` | a Magic-extracted SPICE netlist against the powered Verilog netlist | Netgen's count of mismatching cells and nets |
| `klayout` | `OpenROAD.WriteCDL`, `KLayout.LVS` | the GDSII against a CDL written from the OpenDB database | `0` if KLayout reported "netlists match", `1` otherwise |

So the KLayout number is a verdict, not a count. `Netgen.LVS` and `KLayout.LVS`
each gate the metric they wrote at zero and behave identically either way, but
any consumer that reads the number itself, a metrics dashboard or a regression
comparison, is reading two different quantities. Which one produced it is
recorded as the `lvs` entry of the run's resolved `TOOLS`.

The two are also not equally deep. Netgen compares a netlist extracted from
the layout with connectivity and device parameters; the KLayout script
compares against a CDL and, for hierarchical designs, is the less complete of
the two. Selecting `klayout` is not a like-for-like substitution.

`KLayout.LVS` ships PDK-specific handling for `ihp-sg13g2` and
`ihp-sg13cmos5l` only. On any other PDK the step warns that it is unsupported
and returns no metric at all. Its own gate has nothing to compare against, so
it raises nothing either: the warning naming the unsupported PDK is the only
record, and the run continues with no LVS result. Nothing selects this
provider for you.

```json
{
  "TOOLS": {
    "lvs": "klayout"
  }
}
```

```{important}
On all three shipped documents this selection is refused at load, before any
tool runs: `OpenROAD.WriteCDL` writes the framework metrics onto a branch
whose siblings inherit them, and the final join would receive two values (see
[Selections the shipped documents refuse](#selections-the-shipped-documents-refuse)).
Select it from a document written for it, or set `RUN_LVS` to `false` on the
shipped ones — the refusal message lists the working alternatives.
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

(selections-the-shipped-documents-refuse)=

## Selections the shipped documents refuse

The Alternatives column lists eighteen single-key selections across the three
shipped documents. Seventeen of them are refused at load, which is a fact about
those documents' graphs rather than about the tools: each one either drops a
view something downstream hard-requires, or puts a second writer of one key on a
branch that runs beside another writer's. `test/flows/test_selection_validation.py`
measures the whole list and is the source of this table. Every row assumes a run
that starts from nothing; see
[What is checked, and when](#what-is-checked-when) for what
`--with-initial-state` changes.

| Selection | Refused because | What to write instead |
| --- | --- | --- |
| `{"synthesis": "yosys_vhdl"}` on `Classic` or `Chip` | `json_h` is lost, and `set_power_connections` and `post_gpl_checks` require it | use the `VHDLClassic` flow |
| `{"magic_streamout": "klayout"}` | `mag_gds` is lost, and `KLayout.XOR` requires it | `RUN_MAGIC_STREAMOUT: false` to run one stream-out |
| `{"klayout_streamout": "magic"}` | `klayout_gds` is lost, same step | `RUN_KLAYOUT_STREAMOUT: false` |
| `{"magic_drc": "klayout"}` | both DRC jobs then write `klayout__drc_error__count`, concurrently | `RUN_MAGIC_DRC: false` |
| `{"klayout_drc": "magic"}` | both then write `magic__drc_error__count` | `RUN_KLAYOUT_DRC: false` |
| `{"lvs": "klayout"}` | the provider opens with `OpenROAD.WriteCDL`, whose framework warning and error counts the `lvs` job's concurrent signoff peers carry unchanged from further up | `RUN_LVS: false`, or keep `netgen` |

The one that runs is `{"synthesis": "yosys"}` on `VHDLClassic`: that document
declares no job needing the Verilog header, so restoring the Verilog front end
takes nothing away.

Three of these are Booleans wearing a `TOOLS` disguise. The migration from the
old stage-keyed selection is the reason: `{"drc": "klayout"}` does not become
`{"magic_drc": "klayout"}`, it becomes `RUN_MAGIC_DRC: false`, because the two
jobs are what the two Booleans gate. Each refusal names the Boolean.

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
* View-level compatibility across a provider boundary is guaranteed; semantic
  compatibility is not. The view preflight confirms that the `DEF`, netlist,
  or `SDC` a provider hands off is present, but it cannot confirm that two
  vendors' placements, corners, or extraction models agree closely enough for
  the handoff to be meaningful. That judgment stays with whoever configures
  the mixed flow.

## The `antenna_repair` consequence

Job selection governs which tool runs the *primary* flow of a job, not
what a step does internally to repair the perturbation its own tool
caused. `OpenROAD.RepairAntennas` re-runs OpenROAD's own detailed placement
and global routing to legalize the diodes it just inserted.

The shipped documents run that step as `repair_antennas`, a job listing its
step inline rather than naming a provider, so `TOOLS` cannot address it — as
[the previous section](#the-job-table) says of every inline job. Selecting a
different provider for `detailed_placement`, for example Innovus, therefore
means OpenROAD's own detailed placement still runs again inside antenna
repair, regardless of which tool placed the design the rest of the way, and
no `TOOLS` entry can change that.

The point survives the mechanism: there is no way to route a step's internal
legalization pass through another job's selected provider, and there would
not be one even if `repair_antennas` named a provider. Each tool is
responsible for whatever internal repair its own pass requires.
