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

# Writing Tool Backends

This page is for whoever registers a new **provider** (a tool implementing
one or more of the stages listed in [Swapping Tools](./swapping_tools.md)). It
assumes you have already read that page and {doc}`/usage/writing_custom_steps`,
since a provider is built out of ordinary `Step` subclasses.

## A minimal complete registration

```python
from librelane.stages import StageRegistry
from librelane.state import DesignFormat

StageRegistry.register(
    stages=["synthesis"],
    provider="genus",
    steps=[Genus.Synthesis, Checker.GenusSynthChecks],
    namespaces=("GENUS_",),
    requires_pdk_vars=(),
    provides=(),
    metrics=(),
    native_views=(),
)
```

* `stages`: the stage ids this registration covers, in flow order. Every
  registration seen in LibreLane's own providers covers exactly one stage;
  see [Spanning is declared, not implemented](#spanning-is-declared-not-implemented)
  for why that is the only supported shape.
* `provider`: the tool name, for example `genus`, not a vendor name. This is
  what a `TOOLS` entry names to select the registration.
* `steps`: the ordered concrete `Step` classes that implement the stage. Must
  be non-empty: a provider that runs nothing cannot satisfy a stage's
  contract.
* `namespaces`: the configuration variable prefixes this registration's steps
  are allowed to declare beyond the stage's own canonical variables and the
  common flow variables. See [`namespaces`](#namespaces) below.
* `requires_pdk_vars`: PDK-supplied configuration variable names that must be
  non-`None` for this provider to run at all, for example a vendor
  characterization file the open-source PDKs do not ship. Checked once per
  flow instantiation, before any tool runs.
* `provides`: neutral views this provider guarantees beyond what the stage
  itself already promises. Most registrations leave this empty because the
  stage's own `provides` already covers it; `synthesis`/`yosys` uses it to add
  `json_h`, a view only the Verilog frontend produces.
* `metrics`: metric names this provider guarantees beyond the stage's own,
  for a metric that is genuinely tool-specific rather than portable across
  every provider of the stage. For example, `magic__drc_error__count` on the `drc` stage's
  `magic` provider is the existing example, since `klayout` could never
  promise the same name.
* `native_views`: tool-native views this provider carries across its own
  stage boundaries rather than through the neutral view contract. See
  [`native_views`](#native_views) below.

## The four enforcement points

**Registration time**, inside `StageRegistry.register`, runs three checks the
moment your module is imported, so a broken registration fails loudly at
import rather than quietly at run time:

* *Canonical variable coverage.* Every configuration variable the stage
  declares as canonical must be declared by your step sequence. A user who
  set a canonical variable your steps never read would have that setting
  silently discarded, which this check exists to prevent.
* *Namespace discipline.* Every variable your steps declare must be either
  canonical for the stage, a common flow variable, or prefixed with one of
  your declared `namespaces`. This is what stops one provider's variables
  from leaking into a name another provider might plausibly want.
* *View plausibility.* Every non-optional input your steps consume must
  either be in the stage's `requires` or declared as one of your
  `native_views`. Every view your registration or its stage promises in
  `provides` must actually appear in some step's `outputs`.

**Resolution time**, inside `resolve()`, runs once a flow's `Stages` list and
its `TOOLS` selection are both known, and before any configuration exists. It
rejects an unknown provider name, a list supplied for a stage that is not
`multi_provider`, and an unknown key in `TOOLS`.

**Startup time**, inside `StagedFlow.__init__` once `Config.load` has produced
a resolved configuration, runs the two preflights. These need a configuration
and so cannot live in `resolve()`; if you are chasing one of their messages,
they are the place to look.

* `StagedFlow._preflight_pdk_vars` checks every `requires_pdk_vars` entry of
  every selected provider, and fails naming the stage, the provider, the
  variable and the PDK.
* `StagedFlow._preflight_views` walks the resolved step list and checks that
  every non-optional input a step consumes is actually produced by an earlier
  step, with steps whose gating variables are false excluded. This is what
  makes an untested `TOOLS` combination safe to attempt, because a provider
  selection that leaves a consumer stranded fails at flow construction, naming
  the view, the step, and the last stage before it, rather than crashing once
  some tool reaches for a file that was never written.

**Run time**, inside `StagedFlow`, enforces the stage contract at two
granularities. A backend that does not actually emit `route__drc_errors` must
not be able to let a downstream checker pass on an unexamined design.

* Once the last step of *your registration* completes, every view in your
  registration's own `provides` must be in the state and every metric in its
  own `metrics` must have been emitted. Your contract is yours alone, so on a
  `multi_provider` stage it still holds when the other tool of that stage is
  gated off.
* Once the last step of the *whole stage* completes, every view in the stage's
  `provides` and every metric in the stage's `metrics` must likewise be there.
  This one the selected providers satisfy jointly, which is what lets both
  `streamout` tools share the obligation to produce a neutral `gds` while
  `PRIMARY_GDSII_STREAMOUT_TOOL` decides which of them writes it.

Either check is skipped when the run it covers did not execute every one of its
steps, since views and metrics that were never attempted cannot be owed. That
is what allows `RUN_MAGIC_STREAMOUT=false`.

(namespaces)=
## `namespaces`

Declare exactly one prefix, named after your tool: `GENUS_`, `INNOVUS_`, and
so on. The several legacy prefixes declared on the `openroad` provider
(`FP_`, `PL_`, `CTS_`, `GRT_`, `DRT_`, and a dozen more) predate this design
and are grandfathered because OpenROAD's per-phase variables were never
namespaced by tool in the first place. They are not a pattern to copy for a
new provider; a new backend should not need more than one prefix.

(native_views)=
## `native_views`

A native view is a tool-native artifact one step of your sequence hands to
the next step of the same sequence, instead of going through a portable
format. OpenROAD's `odb` (its live OpenDB database) is the worked example
already in the codebase: sixteen of the `openroad` provider's registrations
in `librelane/stages/providers.py` declare `native_views=(DesignFormat.odb,)`,
because every OpenROAD place-and-route step after `floorplan` takes the
previous step's live database as input rather than re-reading `DEF` and every
LEF from scratch.

Declaring a view as native is only an exemption from the registration-time
*consumption* check: it lets your steps consume that view at a stage boundary
without the stage's own `requires` naming it. It is never an exemption from
the *production* side of the contract. The rule to hold onto is: **correctness
must never depend on the native path.** Your registration must still emit
every neutral view your stage promises (`DEF`, netlist, `SDC`) through the
ordinary `outputs` mechanism, exactly as if the native shortcut did not exist,
so that a flow which switches providers at the next stage boundary, or a
`--from`/`--to` invocation that starts partway through your sequence, still
has something to consume. The native view is a performance path between your
own steps, not a second, silent contract with the rest of the flow.

## How finely to decompose a sequence

Each step in your `steps` list is a separate subprocess: a fresh interpreter
start, a licence checkout if your tool needs one, and (unless you carry a
native view between your own steps) a full read of the technology LEF and
every standard-cell LEF. Decomposing finely, one step per logical operation,
is what makes gating, `--from`/`--to`, and native-view boundaries between
different providers all work uniformly; it is also what pays that startup
cost repeatedly. Weigh the two: a vendor tool with a fast, persistent-session
mode should still expose that session as one subprocess per stage from
LibreLane's point of view. The session lives *inside* your step's `run()`,
not across stage boundaries. A spanning registration is not an available way
to avoid the cost. See the next section for why.

(spanning-is-declared-not-implemented)=
## Spanning is declared, not implemented

`Registration.stages` accepts more than one stage id, and a registration
whose `stages` covers several stages is called *spanning*. However, resolution
rejects one outright, naming the stages it would have covered. Nothing in
LibreLane decomposes a spanning registration back into per-stage steps, gates
part of one, or re-enters a flow in the middle of one. If you are tempted to
register one provider across several stages to avoid the subprocess cost
above, that path does not exist today, and this section explains why it was
not built rather than merely deferred.

The evidence comes from a study of
[SiliconCompiler](https://github.com/siliconcompiler/siliconcompiler), an
open-source EDA framework whose maintainers confirm they hold Cadence and
Synopsys tool enablement privately and cannot publish it, but whose public
framework and OpenROAD flow are a close analogue to this problem. Three
findings from that study, attributed to the SiliconCompiler project rather
than presented as this project's own conclusion:

* SiliconCompiler has no spanning primitive at all. Its `node(step, task,
  index)` binds exactly one tool and task to one node; there is no construct
  that lets one node cover more than one step.
* Its closest analogue to a proprietary tool whose native mode is one long
  interactive session is Vivado, which natively covers synthesis through
  bitstream generation in a single session. SiliconCompiler still splits it
  into four separate nodes (`syn_fpga`, `place`, `route`, `bitstream`), each
  a cold `vivado -mode batch` process, stitched together by Vivado's own
  `.dcp` checkpoint format declared as ordinary node output and input. There
  is no persistent session and no spanning node.
* In its OpenROAD flow, antenna repair is its own node between global and
  detailed route, and the detailed-route task carries no antenna options at
  all. That separation works because the upstream node hands over
  `.odb.gz` (OpenROAD's own native database) losslessly across the node
  boundary. The mechanism that makes fine-grained decomposition affordable is
  a native database carried between steps, which is the same mechanism this
  project already has in [`native_views`](#native_views): for OpenROAD it is
  not merely analogous, it is the same `odb` database.

The honest counter-argument: SiliconCompiler's fine granularity is partly
driven by needs LibreLane does not share, particularly cloud-scale
distribution and per-node caching. Starting a vendor tool once per stage is a
real cost (one licence checkout and one technology/LEF read per stage) that
SiliconCompiler's own execution model is built to amortize across a cluster.
For a single-machine flow, that cost is smaller in absolute terms, but the
answer to it is a persistent tool session held open *inside* a step across
however many stages that step's `run()` chooses to cover internally, not a
registration that spans stages in LibreLane's own bookkeeping. The stage
boundary, the gate, and the contract check all still need to know where one
provider's responsibility ends and the next stage's begins.

## Packaging

A backend is an ordinary `librelane_plugin_*` Python module or package,
auto-imported by `librelane/plugins.py:17-21` alongside every other LibreLane
plugin. Calling `StageRegistry.register` at import time, the same way
`librelane/stages/providers.py` does for the open-source toolchain, needs no
new discovery mechanism: whatever your module's top level does at import
already runs before anything asks for its stages.

## Scope

No commercial backend ships with LibreLane, and none has been tested against
this contract. Everything on this page describes the enforcement machinery as
it exists today, exercised entirely by the open-source providers in
`librelane/stages/providers.py`. The first person to write a commercial
backend against it should expect to find and correct parts of this contract
that a purely open-source toolchain never exercised. For example, LibreLane
currently has no step that imports a `DEF` file into a fresh OpenDB database,
so an `openroad` stage cannot yet follow a non-OpenROAD stage: the `odb`
native view would be absent, and the view preflight correctly rejects such a
configuration by name rather than failing silently. Closing that gap, by
adding a `DEF`-to-`odb` import step to the head of the affected `openroad`
sequences, is left for whoever writes the first backend that needs a
non-OpenROAD provider to hand off back into OpenROAD.
