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
one or more of the jobs listed in [Swapping Tools](./swapping_tools.md)). It
assumes you have already read that page and {doc}`/usage/writing_custom_steps`,
since a provider is built out of ordinary `Step` subclasses.

## A minimal complete registration

```python
from librelane.jobs import JobRegistry
from librelane.state import DesignFormat

JobRegistry.register(
    job="synthesis",
    provider="genus",
    steps=[Genus.Synthesis],
    namespaces=("GENUS_",),
    provides=(),
    metrics=(),
    native_views=(),
)
```

* `job`: the id of the one job this registration implements. A
  registration names exactly one; see
  [One registration, one job](#one-registration-one-job) for why.
* `provider`: the tool name, for example `genus`, not a vendor name. This is
  what a `TOOLS` entry names to select the registration.
* `steps`: the ordered concrete `Step` classes that implement the job. Must
  be non-empty: a provider that runs nothing cannot satisfy a job's
  contract.
* `namespaces`: the configuration variable prefixes this registration's steps
  are allowed to declare beyond the common flow variables. See
  [`namespaces`](#namespaces) below.
* `provides`: neutral views this provider guarantees beyond what the job
  itself already promises. Most registrations leave this empty because the
  job's own `provides` already covers it; `synthesis`/`yosys` uses it to add
  `json_h`, a view only the Verilog frontend produces.
* `metrics`: metric names this provider guarantees beyond the job's own,
  for a metric that is genuinely tool-specific rather than portable across
  every provider of the job. For example, `magic__drc_error__count` on the `drc` job's
  `magic` provider is the existing example, since `klayout` could never
  promise the same name.
* `native_views`: tool-native views this provider carries across its own
  job boundaries rather than through the neutral view contract. See
  [`native_views`](#native_views) below.

## The four enforcement points

**Registration time**, inside `JobRegistry.register`, runs three checks the
moment your module is imported, so a broken registration fails loudly at
import rather than quietly at run time:

* *Canonical variable coverage.* Every configuration variable the job
  declares as canonical must be declared by your step sequence. A user who
  set a canonical variable your steps never read would have that setting
  silently discarded, which this check exists to prevent.
* *Namespace discipline.* Every variable your steps declare must be either
  canonical for the job, a common flow variable, or prefixed with one of
  your declared `namespaces`. This is what stops one provider's variables
  from leaking into a name another provider might plausibly want.
* *View plausibility.* Every non-optional input your steps consume must
  either be in the job's `requires` or declared as one of your
  `native_views`. Every view your registration or its job promises in
  `provides` must actually appear in some step's `outputs`.

**Resolution time** runs once a document's job set and its `TOOLS` selection are
both known, and before any configuration exists. `resolve_jobs()` works from the
document's jobs and rejects an unknown provider name, an unknown key in `TOOLS`,
a list value, and a key naming a job that lists its steps inline.

**Load time** is where the document's own structural check runs, over the
declared graph rather than over a resolved step list. `_check_requirements_are_reachable`
in `librelane/engine/spec_validation.py` checks that every view a job `requires`
is `provide`d by some job upstream of it. This is what makes an untested
document safe to attempt, because a graph that leaves a consumer stranded is
refused before the run starts, naming the view and the job, rather than crashing
once some tool reaches for a file that was never written.

Note what this does *not* cover, and why: re-pointing a job at another provider
with `TOOLS` does not change the declared graph, so a selection whose steps stop
producing a view the graph promised is not caught here. It surfaces during the
run, at the first step that cannot find the view.

**Run time**, inside `Workflow`, enforces the job contract. A gate only checks
a metric that is present, so a backend that never emits `route__drc_errors`
would otherwise let its own gate silently pass an unexamined design; this
contract is what catches that instead.

Once a job completes, every view in its `provides` must be in the state it
produced and every metric in its `metrics` must have been emitted. The union of
the job's template and your registration is what it owes: the template's
entries are the phase's obligations whichever tool implements it, and yours are
the ones only your tool can be held to.

A document runs one provider per job, so this one check is both the job's and
your registration's. Two tools of one phase are two jobs, each contract-checked
against its own provider, which is what lets both `streamout` jobs share the
obligation to produce a neutral `gds` while `PRIMARY_GDSII_STREAMOUT_TOOL`
decides which of them writes it.

The check is skipped for a job that did not run -- one an `if` turned off, or
one outside a `--target` -- since views and metrics that were never attempted
cannot be owed. That is what allows `RUN_MAGIC_STREAMOUT=false`. It is also
skipped for a job that deferred an error, so that the deferred message is what
you see rather than a contract failure that follows from it.

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
in `librelane/jobs/providers.py` declare `native_views=(DesignFormat.odb,)`,
because every OpenROAD place-and-route step after `floorplan` takes the
previous step's live database as input rather than re-reading `DEF` and every
LEF from scratch.

Declaring a view as native is only an exemption from the registration-time
*consumption* check: it lets your steps consume that view at a job boundary
without the job's own `requires` naming it. It is never an exemption from
the *production* side of the contract. The rule to hold onto is: **correctness
must never depend on the native path.** Your registration must still emit
every neutral view your job promises (`DEF`, netlist, `SDC`) through the
ordinary `outputs` mechanism, exactly as if the native shortcut did not exist,
so that a flow which switches providers at the next job boundary, or a
`--target` invocation that stops partway through the graph, still
has something to consume. The native view is a performance path between your
own steps, not a second, silent contract with the rest of the flow.

## How finely to decompose a sequence

Each step in your `steps` list is a separate subprocess: a fresh interpreter
start, a licence checkout if your tool needs one, and (unless you carry a
native view between your own steps) a full read of the technology LEF and
every standard-cell LEF. Decomposing finely, one step per logical operation,
is what makes gating, `--reproducible`, and native-view boundaries between
different providers all work uniformly; it is also what pays that startup
cost repeatedly. Weigh the two: a vendor tool with a fast, persistent-session
mode should still expose that session as one subprocess per job from
LibreLane's point of view. The session lives *inside* your step's `run()`,
not across job boundaries. Registering one provider across several jobs is
not an available way to avoid the cost. See the next section for why.

(one-registration-one-job)=
## One registration, one job

`Registration.job` is a single job id, and there is no way to say that a
provider covers several. Gating, contract checking and provider selection are
all per-job, so a registration covering more than one has no meaning in any
of them. If you are tempted to register one provider across several jobs to
avoid the subprocess cost above, this section explains why that shape was not
built rather than merely deferred.

The evidence comes from a study of
[SiliconCompiler](https://github.com/siliconcompiler/siliconcompiler), an
open-source EDA framework whose maintainers confirm they hold Cadence and
Synopsys tool enablement privately and cannot publish it, but whose public
framework and OpenROAD flow are a close analogue to this problem. Three
findings from that study, attributed to the SiliconCompiler project rather
than presented as this project's own conclusion:

* SiliconCompiler has no multi-step primitive at all. Its `node(step, task,
  index)` binds exactly one tool and task to one node; there is no construct
  that lets one node cover more than one step.
* Its closest analogue to a proprietary tool whose native mode is one long
  interactive session is Vivado, which natively covers synthesis through
  bitstream generation in a single session. SiliconCompiler still splits it
  into four separate nodes (`syn_fpga`, `place`, `route`, `bitstream`), each
  a cold `vivado -mode batch` process, stitched together by Vivado's own
  `.dcp` checkpoint format declared as ordinary node output and input. There
  is no persistent session and no multi-step node.
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
distribution and per-node caching. Starting a vendor tool once per job is a
real cost (one licence checkout and one technology/LEF read per job) that
SiliconCompiler's own execution model is built to amortize across a cluster.
For a single-machine flow, that cost is smaller in absolute terms, but the
answer to it is a persistent tool session held open *inside* a step across
however many jobs that step's `run()` chooses to cover internally, not a
registration covering several jobs in LibreLane's own bookkeeping. The job
boundary, the gate, and the contract check all still need to know where one
provider's responsibility ends and the next job's begins.

## Packaging

A backend is an ordinary `librelane_plugin_*` Python module or package,
auto-imported by `librelane/plugins.py:17-21` alongside every other LibreLane
plugin. Calling `JobRegistry.register` at import time, the same way
`librelane/jobs/providers.py` does for the open-source toolchain, needs no
new discovery mechanism: whatever your module's top level does at import
already runs before anything asks for its jobs.

## Commercial CAD tool scaffolds

`librelane/steps/` includes step scaffolds for sixteen commercial CAD tools
(Cadence, Synopsys and Siemens implementation and signoff tools). Every step
in them raises `NotImplementedError` from `run()`: nobody who wrote these
scaffolds had access to the tool in question, so no vendor command is guessed
anywhere in them. They exist to hold the shape of a real backend, for someone
with a license and the tool's own documentation to fill in.

These scaffolds register with `Step.factory` unconditionally, the same as
any other step, but they do not register as job providers by default. That
registration is opt-in, behind importing `librelane.jobs.providers_vendor`.
Nothing under `librelane.jobs` imports that module for you; until your own
code does, `JobRegistry.providers()` and `librelane help` know nothing
about any of these sixteen tools. Import it once to make them visible, the
same way a real backend from the previous sections would.

A scaffold says so, in one line. `VendorTclStep` and `VendorPythonStep` both
declare `implemented = False`, which is what `Registration.runnable` derives
from and what stops a scaffold being recommended: when LibreLane refuses a
`TOOLS` selection it names the providers that would work instead, and a
provider whose `run()` raises is never on that list. Selecting one directly is
still permitted — the opt-in exists so that these can be selected, inspected
and filled in.

**So filling one in has a last step.** Once `run()` drives the real tool,
delete `implemented = False` from the class you finished. It is declared
rather than inferred from the base class precisely so that you can: a
completed Innovus backend is still a `VendorTclStep`, and nothing about the
hierarchy distinguishes it from the scaffold it grew out of.

## Scope

No commercial backend ships with LibreLane in working order, and none has
been tested against a real tool invocation. Everything on this page describes
the enforcement machinery as it exists today, exercised by the open-source
providers in `librelane/jobs/providers.py` and, at the registration-contract
level only, by the scaffolds in the previous section. The first person to
write a commercial backend against it should expect to find and correct parts
of this contract that a purely open-source toolchain never exercised. For
example, LibreLane
currently has no step that imports a `DEF` file into a fresh OpenDB database,
so an `openroad` job cannot yet follow a non-OpenROAD job: the `odb`
native view would be absent, and the view preflight correctly rejects such a
configuration by name rather than failing silently. Closing that gap, by
adding a `DEF`-to-`odb` import step to the head of the affected `openroad`
sequences, is left for whoever writes the first backend that needs a
non-OpenROAD provider to hand off back into OpenROAD.
