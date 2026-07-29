# CAD Tool Abstraction

**Status:** Design approved, ready for planning
**Date:** 2026-07-29
**Scope:** Part 1 of 2. Part 2 (proprietary PDK ingestion) is a separate spec and
is deliberately not covered here.

**Verification limits.** No commercial EDA tool and no licensed vendor
documentation is available to this project. Everything about the framework, the
`openroad` provider set and the `Classic` and `VHDLClassic` conversions is
buildable and verifiable here. Everything stated about Innovus, Genus, ICC2 and
Calibre is drawn from the public sources listed under "References" and is
**unverified**. Commercial provider registrations, their step decompositions,
their `namespaces` and their `requires_pdk_vars` are illustrative throughout,
and no commercial backend is delivered. The abstraction is validated against
open tools only, and the first author of a real commercial backend should expect
to correct parts of the contract.

## Problem

LibreLane hardcodes its tool choices into flow definitions. `Classic`
(`librelane/flows/classic.py:40`) is a list of roughly 80 concrete step classes,
naming `Yosys.Synthesis`, `OpenROAD.GlobalPlacement`, `Magic.StreamOut` and so
on directly. Using a commercial tool for any part of the flow today means
writing a new `Flow` subclass.

`SequentialFlow` already has a substitution mechanism
(`librelane/flows/sequential.py:169-248`), but it only runs at class definition
time via `__init_subclass__`, so it cannot be driven by a user's configuration.

Three things are therefore missing.

**Tool choice is not configurable.** A user who has Genus and wants to keep the
rest of the open flow has no configuration-level way to express that.

**There is no contract a replacement tool must satisfy.** Nothing states what a
placement implementation must consume, produce, accept as configuration, or
report as metrics. Without such a contract, an alternative backend that fails to
emit `route__drc_errors__count` would make `Checker.TrDRC` pass vacuously, and
the run would report success on an unverified design.

**There is no named, contract-checked point to resume or restart from.** `--from`
and `--to` address individual steps, which are implementation details of a
particular toolchain. An ECO flow that wants to re-run detailed routing without
global routing has to name OpenROAD-specific step IDs to do it.

### On tool command granularity

An earlier draft of this design claimed the substitution unit had to be coarse
because commercial tools expose coarse commands, citing Innovus
`place_opt_design` covering what LibreLane splits across five steps. That
reasoning was wrong and is recorded here so it is not re-derived.

`place_opt_design` is a wrapper. The decomposition is confirmed from public
sources.

- Innovus `place_opt_design` is the consolidation of `place_design` followed by
  `opt_design -pre_cts`, which were previously issued separately.
- `ccopt_design` accepts `-cts` to perform clock tree synthesis without
  concurrent datapath optimization, with post-CTS optimization then issued
  separately as `optDesign -postCTS`.
- ICC2 `place_opt` and `clock_opt` accept `-from` and `-to` over named internal
  phases, for example `place_opt -from final_place -to final_opto` and
  `clock_opt -from build_clock -to route_clock`. The `place_opt` phases are
  initial placement, high-fanout net synthesis, initial DRC, initial
  optimization, final placement and final optimization.
- Real published Innovus flows already separate macro placement from placement
  proper, issuing `place_design -concurrent_macros` before `place_opt_design`.

Commercial tools can therefore be driven at fine granularity. Exact flag
spellings still need confirming against the licensed documentation for the
specific tool version in use, since public sources disagree on details such as
`-cts` versus `-cts_only` and legacy versus Stylus command names
(`routeDesign` versus `route_design`, `optDesign` versus `opt_design`).

The constraint is therefore not architectural but operational, and is discussed
under "Cost of fine granularity".

### What other frameworks chose

Two tool-agnostic frameworks have already made this decision, and their
granularity is evidence worth recording.

**Hammer** (UC Berkeley) decomposes Innovus place-and-route into fifteen steps,
which double as its resume points. Its `init_design`, `floorplan_design`,
`place_bumps`, `place_tap_cells`, `power_straps`, `place_pins`,
`place_opt_design`, `clock_tree`, `add_fillers`, `route_opt_design`,
`opt_signoff`, `write_design` sequence independently separates tap cell
insertion, power straps, pin placement and filler insertion, matching this
design's `tapcell_insertion`, `power_grid`, `io_placement` and `fill_insertion`
stages.

**mflowgen** uses seven Innovus nodes: design initialization, placement, clock
tree synthesis, post-CTS hold fixing, route, postroute, signoff.

Both are **coarser than this design** for the placement, CTS and routing trio.
Hammer keeps `place_opt_design`, `clock_tree` and `route_opt_design` as single
steps where this design defines eleven stages across the same span.

That counter-evidence was resolved by checking separability case by case rather
than by deferring to Hammer's choice. Placement and CTS turned out to be
separable, so the fine stages stand there. Routing turned out not to be, so
"Spanning providers" exists for it. Hammer's coarseness is therefore taken as a
signal worth checking, not as a conclusion, since a framework may keep a
super-command whole for convenience as easily as for necessity.

## Goals

1. Let a user select the tool for each phase of the flow from configuration,
   without writing a new `Flow` subclass.
2. Allow arbitrary cross-vendor mixing, for example Verilator lint feeding Genus
   synthesis feeding OpenROAD placement feeding Innovus routing.
3. Define an enforceable contract that any alternative backend must satisfy,
   covering input views, output views, configuration variables and metrics.
4. Provide named, tool-independent entry points so that resume and ECO flows can
   re-enter at, for example, detailed routing without naming OpenROAD step IDs.
5. Make failures loud and early. A missing tool, an unsupported PDK, or an unmet
   contract must stop the run with a precise message, never degrade silently.
6. Preserve the existing behaviour of `Classic` exactly.

## Non-goals

- **Job farm submission.** Backends invoke tools locally through
  `Step.run_subprocess` (`librelane/steps/step/subprocess_exec.py:66`) exactly as
  OpenROAD steps do. That method is already the single funnel for process
  execution, so a future LSF, SGE or Slurm layer is a new implementation behind
  an existing seam rather than a refactor.
- **PDK-supplied tool defaults.** See "Known limitations".
- **The PDK converter.** Separate spec.
- **License availability checking** beyond the PDK view preflight described
  below.
- **Reworking the checker architecture.** Acknowledged as unsatisfactory and
  deferred. See "Deferred work that interacts with this design".
- **Shipping commercial backends.** This spec delivers the abstraction and the
  `openroad` provider set. Commercial backends are separate packages.

## Design decisions

Recorded with rationale, because several were chosen over plausible
alternatives.

**A stage is the unit of substitution, independent control, and re-entry.** Not
the unit of execution. A provider implements a stage with an ordered sequence of
steps that may be as fine as it likes.

**Stage boundaries are derived from evidence, not taste.**
`Classic.gating_config_vars` (`librelane/flows/classic.py:245-287`) contains 22
distinct `RUN_*` variables. Each is a place where users already demanded the
ability to turn one phase off independently, which makes it a place where they
would plausibly want to change tools or re-enter the flow. The taxonomy below is
derived by taking those boundaries and adding the few phases that are separately
swappable but happen never to have been made optional.

**Providers are named after tools, not vendors.** `genus`, `innovus`, `icc2`,
`primetime`, `calibre`, `openroad`, `yosys`, `magic`. A vendor name cannot
distinguish Genus from Joules, or Design Compiler from Fusion Compiler, and
naming a vendor makes a per-stage choice read as a company-wide commitment.

**Stage boundaries carry neutral views only.** Every stage declares what it
requires and provides in existing `DesignFormat` terms such as `nl`, `def`,
`sdc`, `spef`, `gds`. A backend may additionally emit a tool-native view (an
Innovus database, an OpenAccess library) and a following step from the same tool
may prefer it to skip a DEF round trip, but correctness must never depend on the
native path. `DesignFormat` is an open registry
(`librelane/state/design_format.py:111-151`), so a plugin registers native views
without touching core.

**Canonical variables plus namespaced extras.** A stage declares portable
variables that every provider must accept. A provider may add its own, but only
under its registered prefixes.

**Not everything becomes a stage.** `StagedFlow.Stages` accepts both `Stage`
objects and plain `Step` classes. Provider-neutral utilities and boundary
observations remain plain steps between stages. Stages are cut only where a real
tool or control boundary exists.

## Architecture

### New module `librelane/stages/`

Two focused files, following the factory conventions already used by
`StepFactory` (`librelane/steps/step/factory.py:37-94`) and
`DesignFormatFactory`.

#### `stage.py`

```python
@dataclass(frozen=True)
class Stage:
    id: str
    full_name: str
    default_provider: str | None
    requires: list[DesignFormat]
    provides: list[DesignFormat]
    config_vars: list[Variable]
    metrics: list[str]
    gating_config_var: str | None = None
    multi_provider: bool = False
    optional: bool = False
```

`requires` and `provides` are the neutral handoff contract. `config_vars` are
the canonical, portable variables. `metrics` are the metric names the stage must
have produced by the time it completes. `gating_config_var` and `multi_provider`
are discussed below.

Stages register into a factory in the same style as `DesignFormat`, so
`Stage.factory.get("detailed_routing")` and `Stage.detailed_routing` both work.

#### `registry.py`

A registration maps a **span of one or more consecutive stages** to a
**sequence of one or more steps**. Both sides are many-valued, which makes one
mechanism cover every case.

```python
# One stage, one step.
StageRegistry.register(
    stages=["global_placement"],
    provider="openroad",
    steps=[OpenROAD.GlobalPlacement],
    namespaces=["PL_", "GPL_"],
)

# One stage, several steps.
StageRegistry.register(
    stages=["io_placement"],
    provider="openroad",
    steps=[OpenROAD.GlobalPlacementSkipIO, OpenROAD.IOPlacement,
           Odb.CustomIOPlacement, Odb.ApplyDEFTemplate],
    namespaces=["FP_", "PL_"],
)

# Several stages, one step. See "Spanning providers".
StageRegistry.register(
    stages=["io_placement", "global_placement",
            "post_gpl_repair", "detailed_placement"],
    provider="innovus",
    steps=[Innovus.PlaceOptDesign],
    namespaces=["INNOVUS_"],
    requires_pdk_vars=["QRC_TECHFILE", "INNOVUS_TECH_LEF"],
)
```

Lookup surface is `StageRegistry.get(stage, provider)`, which returns the
registration covering that stage, `StageRegistry.providers(stage)` and
`StageRegistry.list()`.

The `openroad` sequences shown throughout this document are illustrative. The
authoritative sequences are whatever reproduces `Classic` exactly, and the
golden file equivalence test described under "Testing" is what pins them down.

`namespaces` is a list of accepted variable prefixes rather than a single tool
name, because the existing OpenROAD steps predate this design and use
established prefixes such as `FP_`, `PL_`, `CTS_`, `GRT_`, `DRT_` and `RSZ_`.
Requiring a single `OPENROAD_` prefix would fail the `openroad` provider's own
registration, and renaming several hundred user-facing variables is out of
scope. New providers are expected to declare one tool-named prefix.

Registration happens at import time. `librelane/plugins.py:17-21` already
imports every installed `librelane_plugin_*` module, so a plugin needs no new
discovery mechanism. Whether a backend lives in `librelane/steps/cadence/` or in
an out-of-tree `librelane_plugin_cadence` is therefore a packaging decision with
no architectural consequence, and can be changed later without touching this
design.

### Selection configuration

```json
"TOOLS": {
  "synthesis": "genus",
  "detailed_routing": "innovus"
}
```

Only overrides are listed. Unnamed stages use `Stage.default_provider`. There is
no `"*"` wildcard entry, because with tool-named providers no single value is
meaningful across all stages.

Setting many stages at once is handled by configuration layering rather than by
framework machinery. `librelane/config/loading/layering.py:15` already merges
ordered sources and records provenance per key, so a shipped `cadence.json`
fragment composes naturally.

### Multi-provider stages

Some stages legitimately run more than one tool at once. `Classic` streams out
GDSII with **both** Magic and KLayout and then XORs the results, and runs
**both** Magic DRC and KLayout DRC. `PdkConfig.PRIMARY_GDSII_STREAMOUT_TOOL`
(`librelane/config/flow.py`) already exists to say which output is authoritative.

This is a deliberate cross-checking methodology, not an accident, so the model
accommodates it rather than flattening it. A `Stage` may set
`multi_provider = True`, and its `TOOLS` entry may then be a list:

```json
"TOOLS": { "streamout": ["magic", "klayout"] }
```

Sequences from each selected provider are concatenated in listed order. For
single-provider stages a list value is rejected at resolution time.

This requirement was invisible at the coarse taxonomy of the previous draft and
surfaced only when the stages were cut finely enough to name `streamout` and
`drc` separately.

## Stage taxonomy

Twenty-seven stages. `Classic` lists all of them, with `post_route_opt` unselected. The `Gate` column shows the existing `Classic` variable that
becomes the stage's `gating_config_var`; blank means the phase is not currently
optional.

| Stage | `openroad` provider covers | Gate | Commercial equivalents |
| --- | --- | --- | --- |
| `lint` | `Verilator.Lint` and its three checkers | `RUN_LINTER` | `spyglass` |
| `synthesis` | `Yosys.JsonHeader`, `Yosys.Synthesis`, synthesis checkers | | `genus`, `dc`, `fusion_compiler` |
| `pre_pnr_sta` | `CheckSDCFiles`, `CheckMacroInstances`, `STAPrePNR` | | `tempus`, `primetime` |
| `floorplan` | `Floorplan`, `DumpRCValues`, `CheckMacroAntennaProperties`, `SetPowerConnections` | | `innovus`, `icc2` |
| `macro_placement` | `Odb.ManualMacroPlacement` | | `innovus`, `icc2` |
| `tapcell_insertion` | `CutRows`, `TapEndcapInsertion` | `RUN_TAP_ENDCAP_INSERTION` | `innovus`, `icc2` |
| `power_grid` | `AddPDNObstructions`, `GeneratePDN`, `RemovePDNObstructions` | | `innovus`, `icc2` |
| `io_placement` | `GlobalPlacementSkipIO`, `IOPlacement`, `CustomIOPlacement`, `ApplyDEFTemplate` | | `innovus`, `icc2` |
| `global_placement` | `OpenROAD.GlobalPlacement` | | `innovus`, `icc2` |
| `post_gpl_repair` | `RepairDesignPostGPL` | `RUN_POST_GPL_DESIGN_REPAIR` | `innovus`, `icc2` |
| `detailed_placement` | `OpenROAD.DetailedPlacement` | | `innovus`, `icc2` |
| `cts` | `OpenROAD.CTS` | `RUN_CTS` | `innovus`, `icc2` |
| `post_cts_opt` | `ResizerTimingPostCTS` | `RUN_POST_CTS_RESIZER_TIMING` | `innovus`, `icc2` |
| `global_routing` | `GlobalRouting`, `CheckAntennas` | | `innovus`, `icc2` |
| `post_grt_repair` | `RepairDesignPostGRT` | `RUN_POST_GRT_DESIGN_REPAIR` | `innovus`, `icc2` |
| `antenna_repair` | `DiodesOnPorts`, `HeuristicDiodeInsertion`, `RepairAntennas` | `RUN_ANTENNA_REPAIR` | `innovus`, `icc2` |
| `post_grt_opt` | `ResizerTimingPostGRT` | `RUN_POST_GRT_RESIZER_TIMING` | `innovus`, `icc2` |
| `detailed_routing` | `DetailedRouting`, `RemoveRoutingObstructions`, `CheckAntennas`, `Checker.TrDRC` | `RUN_DRT` | `innovus`, `icc2` |
| `post_route_opt` | none, see below | | `innovus`, `icc2` |
| `fill_insertion` | `OpenROAD.FillInsertion` | `RUN_FILL_INSERTION` | `innovus`, `icc2` |
| `extraction` | `OpenROAD.RCX` | `RUN_SPEF_EXTRACTION` | `quantus`, `starrc` |
| `signoff_sta` | `OpenROAD.STAPostPNR` | `RUN_MCSTA` | `tempus`, `primetime` |
| `ir_drop` | `OpenROAD.IRDropReport` | `RUN_IRDROP_REPORT` | `voltus`, `redhawk` |
| `streamout` | `Magic.StreamOut`, `KLayout.StreamOut`, `KLayout.Render`, `Magic.WriteLEF` | | `innovus`, `icc2` |
| `drc` | `Magic.DRC`, `KLayout.DRC` and their checkers | | `calibre`, `pegasus`, `icv` |
| `lvs` | `Magic.SpiceExtraction`, `Checker.IllegalOverlap`, `Netgen.LVS`, `Checker.LVS` | `RUN_LVS` | `calibre`, `pegasus` |
| `formal_equivalence` | `Yosys.EQY` | `RUN_EQY` | `conformal`, `formality` |

`post_route_opt` has **no `openroad` provider**, because LibreLane has no
post-detailed-route optimization. Both Hammer (`opt_signoff`, backed by
`time_design_signoff` and `opt_signoff`) and mflowgen (`postroute`) have one, as
does Innovus via `optDesign -postRoute` and ICC2 via `route_opt`.

`Classic.Stages` lists it anyway, in an **unselected** state. Its
`default_provider` is `None`, which is legal only for a stage marked
`optional = True`. An unselected stage contributes no steps, is reported as
`stage 'post_route_opt': no provider selected, skipped` in the resolution log
and in `--list-stages`, and is not contract-checked. Naming a provider for it in
`TOOLS` activates it.

This is deliberately not a no-op provider. No `openroad` registration exists
that would run nothing and then satisfy the contract, because a silently
satisfied contract is the exact failure mode this design exists to prevent. The
distinction is that an unselected stage is *visibly absent*, whereas a no-op
provider would be *invisibly hollow*.

Keeping the stage in `Classic` rather than omitting it means a user with a
commercial router turns it on with one `TOOLS` entry instead of subclassing the
flow, which is the same problem `VHDLClassic` illustrates.

`optional` is restricted to stages whose `provides` adds nothing its successors
require. `post_route_opt` qualifies: it takes `def` plus `nl` and returns `def`
plus `nl`. A stage that produces a view later stages need may not be optional,
so skipping one can never produce a downstream contract failure.

`streamout` and `drc` are `multi_provider`. Their per-tool gates
(`RUN_MAGIC_STREAMOUT`, `RUN_KLAYOUT_DRC` and so on) remain step-level gating
variables inside the `magic` and `klayout` sequences.

Everything else stays a plain step entry between stages, notably the five
`OpenROAD.STAMidPNR` invocations, `Odb.AddRoutingObstructions`,
`Odb.WriteVerilogHeader`, `Checker.PowerGridViolations`,
`Odb.ManualGlobalPlacement`, `Odb.ReportDisconnectedPins`,
`Odb.ReportWireLength`, `Odb.CellFrequencyTables`,
`Odb.CheckDesignAntennaProperties`, `KLayout.XOR` and the four final timing
checkers.

`STAMidPNR` is worth calling out. Placing it as a plain step between stages
rather than inside them makes it a tool-independent timing observation at a
contract-checked boundary, which is exactly what it is. The consequence is that
an all-Innovus flow still invokes OpenSTA between stages. That is defensible as
independent verification, and the stage contract guarantees the neutral views it
needs are present, but it costs time and a user may reasonably skip it.

A plain step entry is only legal at a stage boundary. A checker that `Classic`
currently places mid-phase belongs inside that stage's provider sequence
instead. The equivalence test determines which steps fall on which side of each
boundary.

## Cost of fine granularity

Recorded because twenty-seven stages is a deliberate trade and its costs should be
visible.

**Tool session count.** Each LibreLane step is a separate subprocess, so a
finely decomposed commercial provider means many tool sessions, each paying
startup, license checkout and a database save and restore. Innovus startup on a
large design is minutes, and splitting a super-command discards the in-memory
timing graph and congestion maps it carries across its internal phases, which
can move QoR. The native-database fast path is therefore not an optimization at
this granularity, it is what makes the granularity affordable. A provider that
judges the trade unfavourable registers a spanning implementation instead.

**Contract surface.** Twenty-seven stages each declaring required views, provided
views, canonical variables and canonical metrics is a large surface. It is
manageable because most stages are in-place transforms with identical
`requires` and `provides` (`def` plus `nl`), and because the optimization stages
share one canonical timing metric bundle. Shared contract constants are defined
once in `stage.py` and reused, rather than restated twenty-seven times.

**Boundary count.** Up to twenty-six potential DEF round trips in a mixed-tool
flow. Same-provider adjacent stages avoid this through the native fast path.

## Spanning providers

A provider may cover several consecutive stages with one registration.

The justification is one specific case where decomposition is not merely
inconvenient but impossible, rather than a general preference for coarseness.
The test applied was: if a vendor super-command is known to be separable, the
fine stages stand and spanning is unnecessary; if it is not, spanning is
required.

**Placement and CTS are separable, so they do not justify spanning.** Innovus
exposes `editPin`, `place_design`, `opt_design -pre_cts` and `refinePlace`
covering this taxonomy's `io_placement`, `global_placement`, `post_gpl_repair`
and `detailed_placement`, and `ccopt_design -cts` with `optDesign -postCTS`
covering `cts` and `post_cts_opt`.

**Routing is not separable.** Antenna repair in Innovus is not a command. It is
a router mode: `setNanoRouteMode -drouteFixAntenna true`, with
`-routeInsertAntennaDiode` and `-routeAntennaDiodeCellName`, set before
`globalDetailRoute`. NanoRoute repairs violations by layer hopping during
search-and-repair and post-route optimization, inserting diode cells for
whatever remains. There is no point at which an Innovus flow could hand a
partially-antenna-repaired design to another tool, so `global_routing`,
`post_grt_repair`, `antenna_repair`, `post_grt_opt` and `detailed_routing`
cannot be independently implemented by an Innovus provider. It must span them.

This is exactly the situation spanning exists for, and it is a property of the
tool rather than a shortcut. Note that it is also unverified, per the
verification limits above.

Rules, all enforced rather than assumed.

**The span must be contiguous** in the flow's `Stages` order, with no
intervening plain step entries. A gap means the registration is rejected at
import.

**Selection must be consistent.** If `TOOLS` names a spanning provider for any
stage in its span, every other stage in that span must resolve to the same
provider. A configuration selecting `innovus` for `global_placement` but
`openroad` for `detailed_placement`, where `innovus` only offers a spanning
implementation covering both, is a resolution-time error naming the span. It is
not silently split and it is not silently widened.

**The contract is checked at the end of the span**, against the union of the
spanned stages' `provides` and `metrics`. Intermediate stage contracts are not
checked, because the intermediate states do not exist as artifacts.

**Gating and re-entry within a span are unavailable**, and asking for them is an
error rather than a no-op. Setting `RUN_POST_GPL_DESIGN_REPAIR` to `false` while
`post_gpl_repair` is inside an Innovus span fails with a message explaining that
the stage is not independently controllable under the selected provider.
Likewise `--from detailed_placement` resolves to the start of the span. This is
a real property of the tool being used, not an artifact of the framework, so it
is surfaced rather than hidden.

The cost of spanning is precisely the capability the fine taxonomy was chosen
for. A user who wants per-phase control and ECO re-entry within placement must
select a provider that decomposes; a user who wants the vendor's cross-phase
optimization accepts the span. Making that a per-provider registration decision
puts the trade in the hands of the person who knows the tool.

## Relationship to `CompositeStep`

`CompositeStep` (`librelane/steps/step/composite.py:35`) already composes steps,
so the overlap deserves a precise answer rather than an implicit one.

They compose at different levels and both are needed.

**`CompositeStep` is provider-internal composition.** Its three current users,
`Odb.DiodesOnPorts`, `Odb.HeuristicDiodeInsertion` and `OpenROAD.RepairAntennas`,
all bundle an action with the legalization that action requires:

```
DiodesOnPorts           = [PortDiodePlacement,  DetailedPlacement, GlobalRouting]
HeuristicDiodeInsertion = [FuzzyDiodePlacement, DetailedPlacement, GlobalRouting]
RepairAntennas          = [_DiodeInsertion,     CheckAntennas]
```

Inserting a diode perturbs placement, so placement must be legalized and routing
refreshed before the result is meaningful. Re-entering between the insertion and
its legalization is not a coherent thing to want, so making the sub-steps
individually addressable would be wrong. Atomic composition is correct here.

**A stage is cross-provider composition.** It names a phase that a user may swap
tools for, gate off, or re-enter at. Its provider sequence is therefore
flattened into the flow's step list rather than wrapped, so every step keeps its
own directory, metrics and `--from`/`--to` addressability.

Flattening is additionally required for backward compatibility. `Classic.Steps`
is a flat list of roughly 80 steps today. Wrapping stages as composites would
make it a list of 27, breaking the equivalence test, `Classic.Substitute` and
every existing step directory path.

The genuine overlap is the running union of inputs, outputs and config variables
across an ordered step list, which `CompositeStep.__init_subclass__` implements
and stage registration needs. That is extracted into one shared helper used by
both.

### Consequence for the `antenna_repair` stage

Because `DiodesOnPorts` and `HeuristicDiodeInsertion` internally re-run
`OpenROAD.DetailedPlacement` and `OpenROAD.GlobalRouting`, the `antenna_repair`
stage invokes steps that belong to the `detailed_placement` and `global_routing`
stages. Under a mixed configuration such as
`{"detailed_placement": "innovus", "antenna_repair": "openroad"}`, OpenROAD
detailed placement runs inside antenna repair even though the user selected
Innovus for the placement stage.

This is permitted, and the rule is stated explicitly so it is not mistaken for a
bug. **Stage selection governs the primary flow, not a provider's internal
repair of the perturbation it caused.** A provider legalizes with its own tools;
that is part of what implementing the stage means. An Innovus `antenna_repair`
would legalize with Innovus.

The rule needs stating because the surprise is real. A user selecting Innovus
for placement may not expect any OpenROAD invocation to touch placement
afterwards. It is documented in `swapping_tools.md`, and it is the reason
`stage.provides` for `antenna_repair` includes a legalized `def` rather than
leaving legalization implicit.

## Resolution order

`Flow.__init__` (`librelane/flows/flow.py:466-487`) reads `self.Steps` to build
`get_all_config_variables()` before it calls `Config.load`. The step set must
therefore be known before configuration is validated, which is a chicken and egg
problem because configuration is what selects the steps.

It is resolved with a narrow pre-pass, mirroring the existing two-phase read
that already extracts `PDK` and `DESIGN_NAME` ahead of full validation
(`librelane/config/config.py:671` calling
`preprocessor.preprocess_dict(..., only_extract_process_info=True)`).

`StagedFlow.__init__` performs the following before delegating to
`super().__init__()`.

1. **Extract `TOOLS` only** from the layered raw configuration and from
   `config_override_strings`. Precedence follows normal layering, with command
   line overrides last.
2. **Expand** `Stages` into a flat list of concrete step classes through
   `StageRegistry`, with `Stage.default_provider` filling any stage `TOOLS` does
   not name.
3. **Normalize** duplicate step IDs. `SequentialFlow.__normalize_step_ids`
   (`librelane/flows/sequential.py:250`) already accepts an instance as its
   target, so no change is required there.
4. **Record** the stage boundary map, from stage id to the resolved step ids it
   owns, for use by gating and contract enforcement.
5. **Assign** `self.Steps`, then call `super().__init__()`, which proceeds
   unchanged.

`TOOLS` must be a literal mapping. `expr::`, `ref::` and other preprocessor
constructs are rejected inside it, and its values may not be derived from the
PDK. This keeps the pre-pass from re-entering the preprocessor before the
configuration is resolved.

`StagedFlow.__init_subclass__` runs the same expansion at class definition time
using stage defaults. This is what keeps `Classic.Steps` populated at import.

### Interaction with `Substitutions`

Stage expansion happens first, `Substitutions` second. A substitution naming a
step that the selected providers did not produce raises the existing
`FlowException` in `__substitute_step`
(`librelane/flows/sequential.py:220-227`). This is the desired behaviour, since
a substitution written against OpenROAD step IDs is meaningless once placement
is running on Innovus, and silently ignoring it would be worse than failing.

### PDK view preflight

After `Config.load` completes and before any step runs, each selected provider's
`requires_pdk_vars` is checked against the resolved configuration. A missing or
`None` value fails the run with a message naming the stage, the provider, the
variable and the PDK:

```
detailed_routing: provider 'innovus' requires QRC_TECHFILE,
which PDK 'sky130A' does not define
```

This check is also the seam at which the PDK ingestion spec plugs in.

## Contract enforcement

Three checks at three distinct times.

### Registration time

Performed inside `StageRegistry.register`, so violations surface as import
errors in the offending plugin rather than as runtime surprises.

**Canonical variable coverage.** Every name in `stage.config_vars` must be
declared by at least one step in the provider's sequence. Without this check, a
user who set `PL_TARGET_DENSITY_PCT` and then switched placement providers would
have that setting silently discarded.

**Namespace discipline.** Every variable declared by a step in the sequence must
be one of the following: a canonical variable of the stage, a member of
`flow_common_variables` (`librelane/config/flow.py:511`), a PDK or SCL variable,
or carrying one of the provider's registered `namespaces` prefixes. All four
sets are computable at registration time. Canonical stage variables are tested
first, so a portable variable such as `PL_TARGET_DENSITY_PCT` is exempt from the
prefix rule even though it shares a prefix with namespaced ones.

**View plausibility.** The sequence's unmet inputs must fall within
`stage.requires`, and `stage.provides` must fall within the union of the
sequence's outputs. `CompositeStep.__init_subclass__`
(`librelane/steps/step/composite.py:52-78`) already implements exactly this
running union of inputs, outputs and config variables across an ordered step
list. That logic is extracted into a shared helper and used by both, rather than
written twice.

### Resolution time

- The requested provider is registered for that stage. The error lists the
  providers that are.
- A list value is used only for a `multi_provider` stage.
- Every key in `TOOLS` names a stage present in the flow. Misspellings get a
  suggestion, reusing the `rapidfuzz` pattern already used for step IDs in
  `SequentialFlow.run` (`librelane/flows/sequential.py:302-315`).
- PDK view preflight, as above.

### Runtime

After the last step of a stage completes, assert that every view in
`stage.provides` is present in the state and every name in `stage.metrics` is
present in `state.metrics`. On failure, raise `StageContractError`, a subclass of
`FlowError`.

There is no default value, no skip and no warn-and-continue for this check. A
backend that does not report `route__drc_errors__count` must not be permitted to
let `Checker.TrDRC` pass on an unexamined design.

The check is performed inside the run loop against the stage boundary map
recorded at resolution, not by inserting synthetic check steps into the flow.
Twenty-six extra step directories would be substantial noise, and the mechanism
would be reproducing the checker pattern this project already intends to
replace. The in-loop form is also the only one that handles partial execution
correctly: a stage that did not run every one of its steps, because `--from`,
`--to`, `--skip` or gating excluded some, is not contract-checked, since
asserting a contract against a phase that was deliberately not run would produce
a false failure.

## Stage gating

`Classic.gating_config_vars` maps OpenROAD-specific step IDs to boolean
variables, for example `"OpenROAD.CTS": ["RUN_CTS"]`. Keys that match no step in
the flow are skipped without complaint, both at class definition
(`librelane/flows/sequential.py:130-133`) and at run time
(`librelane/flows/sequential.py:340-347`).

Under a non-default provider this fails silently. A user setting `RUN_CTS` to
`false` with `"cts": "innovus"` selected would find that Innovus still runs,
because no step named `OpenROAD.CTS` exists to gate.

Gating therefore moves to the stage level. A `Stage` declares
`gating_config_var`, and `StagedFlow` applies it to whichever steps the resolved
provider produced. `RUN_CTS` gates the `cts` stage regardless of provider. The
`Gate` column of the taxonomy table is this migration, and it accounts for
fifteen of the twenty-two existing variables.

The remaining seven stay step-level because they gate one tool within a stage
rather than the stage itself: `RUN_HEURISTIC_DIODE_INSERTION` within the
`openroad` `antenna_repair` sequence, and `RUN_MAGIC_STREAMOUT`,
`RUN_KLAYOUT_STREAMOUT`, `RUN_MAGIC_WRITE_LEF`, `RUN_KLAYOUT_XOR`,
`RUN_MAGIC_DRC` and `RUN_KLAYOUT_DRC` inside the `multi_provider` `streamout`
and `drc` stages.
To prevent the silent-skip hazard recurring, `StagedFlow` rejects a
`gating_config_vars` key matching no resolved step rather than ignoring it.

## Backward compatibility

`Classic` is converted in place rather than forked into a parallel staged flow,
so there is one flow to maintain rather than two.

The mechanism that makes this safe is the class-definition-time expansion. Since
`StagedFlow.__init_subclass__` expands with stage defaults, `Classic.Steps` is a
fully populated list at import, identical to today's. Therefore:

- `Classic.Substitute({...})` keeps working.
- `Flow.get_help_md` (`librelane/flows/flow.py:547-552`), which iterates
  `Self.Steps` as a classmethod, keeps working.
- Existing `Classic` subclasses in the wild keep working.
- Step IDs, step directory names and run artifacts are unchanged for a default
  run.

Instance level re-expansion happens only when `TOOLS` selects a non-default
provider.

`Flow.__init__` checks `self.__class__.Steps == NotImplemented`
(`librelane/flows/flow.py:462`), which the class level expansion satisfies.

The fifteen `RUN_*` variables that migrate from step gating to stage gating keep
their names and their meanings, so no user configuration changes.

## Testing

Tests are written before implementation, using pytest and pytest-mock.

**Mock provider.** A test fixture registers a trivial provider for every stage
that passes views through and emits the canonical metrics. This makes the entire
framework testable with no EDA tool installed, commercial or open.

**`Classic` equivalence.** The load-bearing regression test. Today's 80 step
`Classic.Steps` list is captured into a golden file
(`test/flows/classic_steps.json`) generated before any change, and the converted
`StagedFlow` is asserted to reproduce it exactly. This is the proof that the
conversion preserves behaviour, and at twenty-seven stages it is what makes the
decomposition safe to attempt at all.

**`VHDLClassic` equivalence.** The strongest available validation that the
abstraction actually does its job, because it is a real tool swap between two
open tools rather than a mock. `VHDLClassic` (`librelane/flows/classic.py:291`)
exists today purely as a `Substitutions` map that replaces `Yosys.Synthesis`
with `Yosys.VHDLSynthesis` and deletes the Verilog-only steps. It is precisely
the "define a whole new flow class to change one tool" problem this design
exists to remove. After the change it must be expressible as configuration:

```json
"TOOLS": { "synthesis": "yosys_vhdl" },
"RUN_LINTER": false,
"RUN_EQY": false
```

and that configuration against `Classic` must reproduce today's
`VHDLClassic.Steps` exactly, via a second golden file. If it does not, the
abstraction is wrong.

One unresolved detail, to be settled during planning rather than glossed here.
`VHDLClassic` also removes `Odb.SetPowerConnections`, `Odb.WriteVerilogHeader`
and `Yosys.JsonHeader`, which live outside the `synthesis` stage. So choosing a
synthesis provider has consequences beyond its own stage. The candidate
resolutions are to gate those steps on new boolean variables in the manner of
`RUN_LINTER`, or to have the `yosys_vhdl` provider declare that it does not
provide the Verilog-header view those steps consume and let the view contract
remove them. The second is more principled if the view dependency turns out to
be real, and that is what planning must check.

**Gating equivalence.** For each of the twenty-two existing variables, fifteen
migrated and seven unchanged, setting it to `false` must skip exactly the same
steps before and after the change.

**Registration failures**, each asserting its specific error: a provider
sequence missing a canonical variable, a step declaring an un-namespaced
variable, a sequence whose unmet inputs exceed `stage.requires`.

**Resolution failures**: unknown provider for a stage, misspelled stage key
producing a suggestion, a list value on a single-provider stage, a provider
whose `requires_pdk_vars` the PDK does not satisfy.

**Contract violation**: a mock provider deliberately omitting a canonical metric
must raise `StageContractError`. This test is the reason the enforcement exists
and must not be skipped.

**Partial execution**: a stage excluded by `--skip` or by its gating variable is
not contract-checked, and a stage entered mid-way via `--from` is not
contract-checked.

**Multi-provider**: `streamout` with both `magic` and `klayout` concatenates
sequences in listed order and satisfies the stage contract.

**Spanning**: a mock provider registered across four consecutive stages resolves
to one step; a non-contiguous span is rejected at registration; a `TOOLS` map
selecting the spanning provider for only part of its span is a resolution error;
gating a stage inside a span is an error; `--from` a mid-span stage resolves to
the span's first step; the contract is checked once at the span's end against
the union of the spanned stages' `provides` and `metrics`.

**Re-entry**: `--from detailed_routing` resolves to the correct first step under
both the default and a non-default provider.

CI scope is stated honestly. Core is fully covered through the mock provider.
Correctness of any commercial backend is the responsibility of that backend's
package and cannot be exercised in CI.

## Known limitations

**`TOOLS` cannot be supplied by the PDK.** PDK configuration is not loaded until
after step resolution, so a PDK that implies a particular toolchain cannot
declare it. Users must set `TOOLS` in the design configuration or on the command
line. Revisiting this requires a second resolution pass and is deferred to the
PDK ingestion spec, where the motivating case lives.

**Semantic compatibility across a vendor boundary is not guaranteed.** The
framework guarantees view level compatibility, in that a DEF is a DEF. It cannot
guarantee that SDC written by Genus is interpreted identically by OpenSTA, or
that DEF written by Innovus uses only constructs OpenROAD's parser accepts.
These are backend implementation concerns. The runtime stage contract check
causes them to fail at the boundary rather than silently corrupt results.

**Stage boundaries are expensive to move once backends depend on them.**
Twenty-seven is a commitment. The derivation from existing gating variables is the
argument that these are the boundaries that matter, but it is an argument from
the open flow's history and may not survive contact with a commercial one.

## Deferred work that interacts with this design

**The checker architecture.** `Checker.*` steps as a mechanism are unsatisfactory
and are intended to be reworked separately. Two points of contact. First, this
design deliberately does not add to them: the stage contract check runs in the
flow loop rather than as inserted checker steps. Second, several stages currently
own checker steps in their `openroad` sequences (`Checker.TrDRC` inside
`detailed_routing`, `Checker.LVS` inside `lvs`), so a checker rework will need to
decide whether those responsibilities move into the stage contract's `metrics`
declaration, which is arguably where they belong. The stage contract is a
plausible replacement for a portion of what checkers do today, and that overlap
should be resolved deliberately rather than left to accumulate.

## Rejected alternatives

**Per-step roles.** Tag each existing `Step` with a role and swap one for one.
Rejected because it conflates the substitution boundary with the execution
boundary, forcing every provider to decompose identically to OpenROAD.

**Coarse eleven-stage taxonomy.** An earlier draft grouped placement, CTS and
routing into single stages on the incorrect premise that commercial
super-commands could not be decomposed. Rejected for the reasons in "On tool
command granularity", and because coarse stages give up per-phase variable
control and named ECO re-entry points.

**Exposing `Substitutions` to configuration, with no stage layer.** Cheap to
build and infinitely flexible, but it provides a mechanism rather than an
abstraction. Swapping placement becomes a hand written map that only someone
fluent in both flows can produce, and nothing enforces canonical variables or
metrics.

**Whole flow tool selection.** One backend for the entire implementation flow.
Simplest to make correct, since no cross-vendor handoff arises, but it forbids
the mixing that motivates the work.

**Native-database-first with auto-inserted converters.** Highest fidelity within
a single vendor, but the converter graph is substantial complexity and its
failures land in framework code rather than in a step that a backend author can
fix.

**Synthetic `StageContractCheck` steps.** Would have needed no changes to
`SequentialFlow.run`, but adds twenty-six step directories, reproduces the
checker pattern this project intends to replace, and cannot correctly detect
partial stage execution.

## Documentation

- `docs/source/usage/swapping_tools.md`, user facing, covering `TOOLS`, the
  stage taxonomy, multi-provider stages and configuration layering.
- `docs/source/usage/writing_tool_backends.md`, alongside the existing
  `writing_custom_steps.md` and `writing_plugins.md`, covering the registration
  contract, its three enforcement points, spanning registrations, and guidance
  on how finely to decompose a provider sequence.

## References

Vendor command structure was taken from public sources, since Cadence Support
and SolvNetPlus documentation is not publicly accessible. Flag spellings must
still be confirmed against the licensed documentation for the tool version in
use.

- [MacroPlacement, TILOS AI Institute, Cadence Genus and Innovus SP&R scripts](https://tilos-ai-institute.github.io/MacroPlacement/Flows/scripts/cadence/)
  for verbatim `place_design -concurrent_macros`, `place_opt_design`,
  `ccopt_design`, `routeDesign` flow order.
- [Hammer Innovus place-and-route plugin, UC Berkeley](https://github.com/ucb-bar/hammer/blob/master/hammer/par/innovus/__init__.py)
  for the fifteen-step decomposition and its command mapping.
- [mflowgen Innovus foundation flow](https://mflowgen.readthedocs.io/en/latest/stdlib-innovus-flowsetup.html)
  for the seven-node decomposition.
- [Hammer CAD tool plugin setup](https://hammer-vlsi.readthedocs.io/en/stable/CAD-Tools/Tool-Plugin-Setup.html)
  for the plugin packaging precedent.
- [EDI System Text Command Reference, `setNanoRouteMode`](https://free-online-ebooks.appspot.com/enc/14.17/fetxtcmdref/setNanoRouteMode.html)
  for `-drouteFixAntenna` being a router mode rather than a command, which is
  the basis of the "Spanning providers" justification.
