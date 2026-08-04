# Writing Custom Flows

As configurable as the default ("Classic") flow may be, there are some designs
that would simply be too complex to implement using the existing flow.

For example, hardening a macro + padframe for a top level design is too complex
using the Classic flow, and may require you to write your own custom-based flow.

**_First of all_**, please review LibreLane's high-level architecture [at this link](../reference/architecture.md).

This defines many of the terms used and enumerates strictures mentioned in this document.

## Writing a Workflow Document

A flow is a YAML file. It declares a graph of named **jobs**, each of which
runs some steps, and the edges between them. Nothing about it is Python, and
LibreLane's own flows -- `Classic`, `VHDLClassic` and `Chip` -- are exactly
this and nothing else; they live in `librelane/share/*.yaml`. Opening a run
in a viewer is not a flow and has no document: that is
`librelane open <viewer>`.

### Listing steps

The smallest document names itself and gives one job a list of step ids:

```yaml
name: MyFlow
description: A hand-listed place-and-route flow.

jobs:
  synthesis:
    steps: [Yosys.Synthesis, OpenROAD.CheckSDCFiles]
  floorplan:
    needs: [synthesis]
    steps:
      - OpenROAD.Floorplan
      - OpenROAD.TapEndcapInsertion
      - OpenROAD.GeneratePDN
      - OpenROAD.IOPlacement
  placement:
    needs: [floorplan]
    steps: [OpenROAD.GlobalPlacement, OpenROAD.DetailedPlacement]
  routing:
    needs: [placement]
    steps:
      - OpenROAD.GlobalRouting
      - OpenROAD.DetailedRouting
      - OpenROAD.FillInsertion
  signoff:
    needs: [routing]
    steps: [Magic.StreamOut, Magic.DRC, Magic.SpiceExtraction, Netgen.LVS]
```

`needs` is what orders the run. Two jobs with no path between them run
concurrently, so splitting a chain into branches is how a document says
"these are independent" -- something a flat list of steps had no way to
express.

Load and run it from Python:

```python
from librelane.engine import load_flow_spec
from librelane.engine.engine import Workflow

flow = Workflow(
    load_flow_spec("./my_flow.yaml"),
    {
        "PDK": "sky130A",
        "DESIGN_NAME": "spm",
        "VERILOG_FILES": ["./src/spm.v"],
        "CLOCK_PORT": "clk",
        "CLOCK_PERIOD": 10,
    },
    design_dir=".",
)
flow.start()
```

{py:meth}`librelane.engine.Flow.start` returns the final output state. The step
objects the run created are left on the flow instance as `step_objects`.

`--flow` on the command line takes a *registered* name, not a path, so to run
your document that way register it at import time and load your module as a
[plugin](./writing_plugins.md):

```python
from librelane.engine import Flow, load_flow_spec

Flow.factory.register(load_flow_spec("./my_flow.yaml"))
```

```{important}
Do NOT call the `run` method of any `Flow` from outside of `Flow` and its
subclasses- consider it a protected method. `start` is class-independent and
does some incredibly important processing.

You should not be overriding `start` either.
```

### Naming jobs instead of steps

A job may name a **job template** with `uses` rather than list steps. The
template expands into whichever concrete steps implement that phase for the
tool selected for it:

```yaml
name: MyFlow
description: A place-and-route flow written as job templates.

jobs:
  synthesis:
    uses: synthesis
  pre_pnr_sta:
    needs: [synthesis]
    uses: pre_pnr_sta
  floorplan:
    needs: [pre_pnr_sta]
    uses: floorplan
  macro_placement:
    needs: [floorplan]
    uses: macro_placement
  power_grid:
    needs: [macro_placement]
    uses: power_grid
  io_placement:
    needs: [power_grid]
    uses: io_placement
  global_placement:
    needs: [io_placement]
    uses: global_placement
  detailed_placement:
    needs: [global_placement]
    uses: detailed_placement
  global_routing:
    needs: [detailed_placement]
    uses: global_routing
  streamout:
    needs: [global_routing]
    uses: streamout
  drc:
    needs: [streamout]
    uses: drc
```

What `uses` buys over a `steps` list is that the tool behind each job becomes a
configuration choice instead of a hardcoded step class. A user sets the `TOOLS`
configuration variable to pick a different provider for one or more jobs, for
example `{"streamout": "klayout"}` to run KLayout's stream-out instead of
Magic's. The key is the job's name in *this* document, which need not be the
name of the template it uses: `classic.yaml` runs the `streamout` template
under two jobs, `magic_streamout` and `klayout_streamout`.

A document may also pin a provider itself, by writing `uses: synthesis/yosys_vhdl`
rather than `uses: synthesis`, as `vhdl_classic.yaml` does. A pin is the
document's default, not a lock: a matching `TOOLS` entry still overrides it.

See [Swapping Tools](./swapping_tools.md) for the full `TOOLS` reference,
including how a flow runs two tools for one phase and what `TOOLS` cannot do,
and [Writing Tool Backends](./writing_tool_backends.md) for how to register a
new provider.

### Turning a job off

A job may carry an `if` naming a Boolean configuration variable. When that
variable is false the job fires without running anything: it passes its input
state straight through, so every job downstream of it still runs.

The variable has to exist, which a document declares in its own `config`
section:

```yaml
config:
  - name: RUN_CTS
    type: bool
    default: true
    description: Enables clock tree synthesis using the OpenROAD.CTS step.

jobs:
  cts:
    needs: [detailed_placement]
    uses: cts
    if: RUN_CTS
```

See `librelane/share/classic.yaml` for a complete example: half of its
forty-eight jobs carry an `if`, and the variables they name are declared in its
own `config` section.

### Loops

`needs` may close a cycle, provided the cycle is a *simple ring*: every
member has exactly one predecessor inside it, and exactly one member -- the
**gate** -- declares `until`. Only the gate may have consumers outside the
ring; every result the loop hands downstream leaves through the job that
decided the loop was done.

```yaml
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
  floorplan:
    needs: [synthesis]
    steps: [OpenROAD.Floorplan]
  resize:
    needs: [floorplan, sta]
    steps: [OpenROAD.RepairDesign]
  sta:
    needs: [resize]
    steps: [OpenROAD.STAPrePNR]
    until: "metric::timing__hold__ws >= 0"
    max: 5
```

`resize` needing both `floorplan` and `sta` is the ring's back edge; `sta` is
the gate. On each pass the engine runs `resize` then `sta`, in ring order
starting from the gate's successor and ending at the gate, and checks `until`
against the gate's own output metrics. `metric::timing__hold__ws >= 0` true
stops the loop and hands `sta`'s output downstream; false runs another pass,
up to the bound.

The gate declares exactly one bound:

* `max: 5` above -- a plain pass count, and no pass changes any
  configuration. Each pass differs only because it consumes the previous
  pass's output state, the shape an incremental-repair loop needs.
* `iterations`, a value matrix: each configuration variable mapped to the
  values it takes, layered onto every ring member's configuration for that
  pass.

  ```yaml
  sta:
    needs: [resize]
    steps: [OpenROAD.STAPrePNR]
    until: "metric::timing__hold__ws >= 0"
    iterations:
      PL_RESIZER_HOLD_SLACK_MARGIN: [0.1, 0.2, 0.4]
  ```

  This is the escalation shape: pass 3 tries a wider hold margin because the
  document says so, reviewable in one place, rather than a value computed
  somewhere the reader cannot see. The bound is the number of points, and
  naming a second variable multiplies them, every combination being a pass:

  ```yaml
  iterations:
    PL_RESIZER_HOLD_SLACK_MARGIN: [0.1, 0.2, 0.4]
    GRT_ADJUSTMENT: [0.3, 0.5]
  ```

  is six passes, the variable named last varying fastest: `(0.1, 0.3)`,
  `(0.1, 0.5)`, `(0.2, 0.3)`, and so on.

If the schedule runs out without `until` ever holding, the loop exits with
the last pass's state and a deferred error naming the gate and the bound --
the run continues with whatever the loop produced and fails at the end, the
same way a step's own deferred error does.

Each pass gets its own run directory, `runs/<tag>/<job id>/<k>/...` with `k`
the 1-based pass, so pass 3 does not overwrite pass 2's.

### Sweeps

`select` runs one job's steps at every point of its matrix, concurrently, and
keeps the best result by a metric, rather than stopping at the first pass that
satisfies a gate:

```yaml
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
  floorplan:
    needs: [synthesis]
    steps: [OpenROAD.Floorplan]
  placement:
    needs: [floorplan]
    steps: [OpenROAD.GlobalPlacement]
    select: "route__wirelength__estimated min"
    iterations:
      PL_TARGET_DENSITY: [0.45, 0.55, 0.65]
```

`iterations` is the same matrix a loop's schedule is; the rule attached to it
is what differs. A sweep runs every point rather than stopping early, so it
declares `select` -- a metric name and a direction, `min` or `max` -- where a
loop declares `until`. There is no third key naming the shape: a job's keys
already say which it is.

Once `placement`'s input is ready, the engine runs all three settings, each in
its own pass directory (`runs/<tag>/placement/<k>/...`), and keeps whichever
pass's `route__wirelength__estimated` is lowest; ties break to the lowest pass
index, so a rerun picks the same winner. The losing passes' outputs stay on
disk, reviewable, but nothing downstream of `placement` sees them.

A sweep job may not be a ring member, and never declares `until` or `max`:
`select` is what tells the engine how to end it. Sweeping two variables at
once sweeps their product, so

```yaml
    select: "route__wirelength__estimated min"
    iterations:
      PL_TARGET_DENSITY: [0.45, 0.55, 0.65]
      GRT_ADJUSTMENT: [0.3, 0.5]
```

is a six-point sweep, and the best of those six wins.

### Runtime conditions

`if` may test a metric of the job's own input state rather than only a
configuration variable, with a `metric::` term:

```yaml
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
  repair_antennas:
    needs: [synthesis]
    steps: [OpenROAD.RepairAntennas]
    if: "metric::design__antenna__violating__nets > 0"
```

A term is `metric::<name> <op> <literal>`, where `<op>` is one of `==`,
`!=`, `<`, `<=`, `>`, `>=` and `<literal>` is a number. `if` may mix
`metric::` terms with the plain-variable terms it already accepted, joined
with `and` as any `if` is. A configuration term is still decided when the
document is loaded; a runtime term is decided once the job's inputs are
joined, against that state's metrics, immediately before the job would run.
A false runtime term fires the job as a pass-through, logged with the term
and the observed value, the same way `--explain` reports it afterwards. A
term whose metric is missing from the input state is a runtime error --
absence is not false, it is a measurement that never happened.

A loop's gate uses the same term grammar for `until`, but against a
different state: not the gate's *input*, but its *output* after each pass
finishes -- see Loops, above. `until` accepts only `metric::` terms: a plain
configuration variable is constant across a loop's passes, so a gate
conjoining one would either always exit on pass 1 or never exit at all.

### Resource pools

A document may declare named pools at the top level and have a job name the
ones it needs, to bound how many jobs use a scarce tool -- a licensed DRC
seat, a memory-heavy step -- at once, without lowering `-j` for the whole
flow:

```yaml
resources:
  drc_seats: 2

jobs:
  synthesis:
    steps: [Yosys.Synthesis]
  drc_a:
    needs: [synthesis]
    steps: [Magic.DRC]
    resources: [drc_seats]
  drc_b:
    needs: [synthesis]
    steps: [Magic.DRC]
    resources: [drc_seats]
```

`drc_a` and `drc_b` have no path between them, so the graph alone would run
them at once; `drc_seats: 2` still permits that here, but lowering it to `1`
would serialize the two without changing `needs` at all. A pool's capacity is
a positive integer literal, as above, or the name of a configuration variable
the document declares with type `int`, resolved once when the flow is
constructed; a capacity below 1, however it is spelled, is refused before the
run starts, because a pool nothing can ever enter is a flow that stalls by
declaration.

Acquisition is all-or-nothing across every pool a job names: a job takes
every seat it needs at once or none of them, so a job waiting on a pool never
holds a different one meanwhile, and a seat is only ever granted to work
already running on a worker; work that cannot get a worker waits holding
nothing. Together these are what keep pools from deadlocking whatever a
document declares. A loop member acquires and releases its own pools per
pass, not for the whole loop; a sweep's passes acquire independently, so a
two-seat pool still runs a five-point sweep two passes at a time rather than
one point or all five.

### Sharing declarations between documents

Two documents that declare the same thing may write it once, in a third file,
and name that file under `include`:

```yaml
# gates.yaml
config:
  - name: RUN_CTS
    type: bool
    default: true
    description: Enables clock tree synthesis using the OpenROAD.CTS step.

jobs:
  cts:
    needs: [detailed_placement]
    uses: cts
    if: RUN_CTS
```

```yaml
# my_flow.yaml
name: MyFlow
include: [./gates.yaml]

jobs:
  synthesis:
    steps: [Yosys.Synthesis]
  detailed_placement:
    needs: [synthesis]
    uses: detailed_placement
```

Each path is relative to the file that writes it, not to where LibreLane is
run from, so a document and the files it reuses travel together. An included
file may include others in turn; one reached down two paths at once is read
once, and that is not an error.

An included file need not be runnable. `name` and `jobs` are required of the
document being *loaded* and of nothing it includes, so a file declaring
nothing but `config` -- or nothing but a `with` block, or a set of resource
pools -- is a legal include. It is merged as data and never registered, so it
never appears under `--flow`; a `name` or `description` written in one is
ignored, which is what lets it carry them for an editor to validate against
the schema.

#### The common library

An entry written `common::<file>` names a file LibreLane itself ships, in
`librelane/share/common/`:

```yaml
name: MyClassicVariant
include: [common::classic_config.yaml, common::classic_jobs.yaml]

jobs:
  synthesis:
    uses: synthesis/yosys_vhdl
  # ...the front end and finishing this flow does differently
```

The directive exists because that library has no path a document can write.
LibreLane lives wherever it was installed -- a virtual environment, a Nix store
path, a system `site-packages` -- so a document in a design's own repository
that reached it by path would be a document that works on one machine.
`common::` is answered by the installation instead, and is the one form that
still works for a document loaded from a Python mapping, which has no
directory of its own for a relative path to be relative to. The error for a
name the library does not have lists the names it does.

`classic.yaml`, `chip.yaml` and `vhdl_classic.yaml` are written this way: what
all three declare identically -- their configuration variables, and the runs
of jobs from synthesis to the render -- is in that library, and each of them
includes it with `common::`, exactly as your own document would.

Two rules decide what the merged document says:

* **The including document wins.** A job, variable, `with` entry, pool or
  `final` it declares itself replaces the included one. A job is replaced
  whole and never merged key by key, so an override is readable without
  opening the file it overrides -- writing `uses` over an included job that
  carried an `if` leaves no `if` behind.
* **Two includes may not declare the same thing.** Nothing orders one include
  above another, so a job, variable, value or pool declared by both is refused
  by name rather than resolved. Declaring it in the document that includes
  them both, which overrides either, is the way to say which was meant.

There is no `extends` and no way to *remove* what an include declares. A flow
is a self-contained statement of what it runs, and a filter expression over
another flow's jobs is a substitution map wearing a different hat; a document
that needs most of another's graph but not all of it shares the part it agrees
with and writes the rest itself.

Everything else is checked after merging, on the one document the merge
produces: a `needs` may name a job another file declares, and the error for one
that names nothing is the same error it always was.

### Editor support

`librelane flow schema` writes a JSON Schema for everything above, so an
editor can complete step ids and flag mistakes while a document is being
written rather than when it is run:

```console
$ librelane flow schema -o workflow.schema.json
Wrote the workflow document schema to 'workflow.schema.json'.
```

Point the YAML language server at it with a comment on the document's first
line:

```yaml
# yaml-language-server: $schema=./workflow.schema.json
name: MyFlow

jobs:
  synthesis:
    steps: [Yosys.Synthesis]
```

The schema is generated from the same models the loader validates against,
and the names it enumerates are the ones *this installation* has registered:
`steps` completes with every registered step id, `uses` with every
`job/provider` pair, and both include any [plugin](./writing_plugins.md)
installed alongside LibreLane. Regenerate it after installing one.

It also carries the rules a single key cannot state on its own -- that `select`
means nothing without `iterations`, that a job declares `until` or `select` but
never both, that an `until` gate takes exactly one of `iterations` or `max` --
and the term grammar `if` and `until` are written in.

What it cannot carry is anything that needs the whole graph: that a `needs`
names a declared job, that a cycle is a simple ring with one gate, that some
job's required view is produced upstream of it. A document the editor calls
clean can still be refused at load time, with a better message than a
validator would give.

For the same reason it does not require `name` or `jobs`: an editor has no way
to tell a document being written from a fragment being written, and a schema
that guessed would flag every fragment. Both are written against it, and the
loader is where the requirement can be stated without guessing.

## Fully Customized Flows

A document declares a graph and the engine runs it, which is how every flow
LibreLane ships is written. What a document cannot yet express is a decision
taken *during* a run, on data that run produced -- running two variants and
keeping the better one, or retrying a step with different settings after it
failed. For that there is still Python, and {class}`librelane.engine.Flow` is
still the abstract base to write it against.

Treat this as an escape hatch rather than as the flow surface. `--flow` takes
the name of a registered *document*, and `Flow.factory.register` takes a
{class}`librelane.engine.spec.FlowSpec`, so a `Flow` subclass has no registered
name and is constructed and started directly from your own code.

A `Flow` subclass must:

* Declare the steps used in the `Steps` attribute.
  * The steps are examined so their configuration variables can be validated ahead of time.
* Implement the {meth}`librelane.engine.Flow.run` method.
  * This step is responsible for the core logic of the flow, i.e., instantiating
    steps and calling them.
  * This method must return the final state and a list of step objects created.

You may notice you are allowed to do pretty much anything inside the `run` method.
While that may indeed enable you to perform arbitrary logic in a Flow, it is
recommended that you write Steps, keeping the logic in the Flow to a minimum.

You may instantiate and use steps inside flows as follows:

```python
synthesis = Yosys.Synthesis(
    config=self.config,
    state_in=...,
)
synthesis.start()

sdc_load = OpenROAD.CheckSDCFiles(
    config=self.config,
    state_in=synthesis.state_out,
)
```

While you may not modify the configuration object (in `self.config`),
you can slightly modify the configuration used by each step using the config object's
{py:meth}`librelane.config.Config.copy` method, which allows you to supply overrides as follows:

```python3
config_altered = config.copy(FP_CORE_UTIL=9)
```

Which will create a new configuration object with one or more attributes modified.
You can pass these to steps as you desire.

An advantage of this over a document is that you can handle Step failures more
elegantly, i.e., by trying something else when a particular Step (or set of
steps) fail. There are a lot of possibilities.

### Reporting Progress

Correctly-written steps will by default output a log to the terminal, but, running
in a flow, there will always be a progress bar at the bottom of the terminal:

```
Classic - Stage 19 - cts ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 18/43 0:00:20
```

The Flow object has methods to manage this progress bar:

* {py:meth}`librelane.engine.Flow.progress_bar.set_max_stage_count`
* {py:meth}`librelane.engine.Flow.progress_bar.start_stage`
* {py:meth}`librelane.engine.Flow.progress_bar.end_stage`.

They are to be called from inside the `run` method. A workflow advances the bar
once per job it selects and labels each stage with that job's name, so a stage
covers however many steps that job owns. The denominator counts *selected*
jobs, which is why `Classic` shows 43 above rather than the forty-eight its
document declares; the other five are gated off at the default configuration.
A custom flow chooses its own granularity, which is what makes
the next section's parallel steps expressible at all -- incrementing once per
step is not viable when several are in flight.

### Multi-Threading

```{important}
The `Flow` object is NOT thread-safe. If you're going to run one or more steps
in parallel, please follow this guide on how to do so.
```

The `Flow` object offers a method to run steps asynchronously, {meth}`librelane.engine.Flow.start_step_async`.
This method returns a [`Future`](https://en.wikipedia.org/wiki/Futures_and_promises)
encapsulating a State object, which can then be used as an input to future Steps.

This approach creates a dependency chain between steps, so if you attempt to
inspect the last Future from a set of asynchronous steps, it will automatically
run the required steps, in parallel if need be.

Here is a flow built on exactly this principle. It runs two floorplanning
attempts concurrently and keeps whichever produced the smaller die.

This is the case a document cannot express today. `needs` orders jobs but
carries no branch, so a document has no way to say "run both of these and
continue from the one whose metric is lower". The choice below is made in
Python, on metrics that only exist once both attempts have finished.

```python
class TryTwoUtilizations(Flow):
    Steps = [Yosys.Synthesis, OpenROAD.Floorplan]

    def run(self, initial_state, **kwargs):
        synthesized = self.start_step(
            Yosys.Synthesis(config=self.config, state_in=initial_state),
        )

        attempts = [
            self.start_step_async(
                OpenROAD.Floorplan(
                    config=self.config.copy(FP_CORE_UTIL=utilization),
                    state_in=synthesized,
                    id=f"floorplan-{utilization}",
                ),
            )
            for utilization in (60, 40)
        ]

        # Inspecting a Future blocks until that chain has run, so the two
        # floorplans run in parallel and both are complete after this line.
        results = [attempt.result() for attempt in attempts]
        best = min(results, key=lambda state: state.metrics["design__die__area"])
        return best, []
```

A flow whose steps depend on each other's results this way is what the
{meth}`librelane.engine.Flow.start_step_async` seam exists for. Note that the
`Flow` object is not thread-safe, so everything above happens on one thread and
only the steps themselves run concurrently. `start_step_async` submits to the
same process-wide pool the workflow engine fills with whole jobs, which is why
it must be called from the flow's own thread and never from inside a step.

Since the class has no registered name, run it the way you would any other
Python object.

```python
flow = TryTwoUtilizations(
    {
        "PDK": "sky130A",
        "DESIGN_NAME": "spm",
        "VERILOG_FILES": ["./src/spm.v"],
        "CLOCK_PORT": "clk",
        "CLOCK_PERIOD": 10,
    },
    design_dir=".",
)
flow.start()
```

## Error Throwing and Handling

Steps may throw one of these hierarchy of errors, namely:

* {exc}`librelane.steps.StepError`: For when there is an error in running one of the
  tools or the input data.
  * {exc}`librelane.steps.DeferredStepError`: A `StepError` that suggests that the
    Flow continue anyway and only report this error when the flow finishes. This
    is useful for errors that are not "show-stoppers," i.e. a timing violation
    for example.
  * {exc}`librelane.steps.StepException`: A `StepError` when there is a
    higher-level step failure, such as the step object itself generating an
    invalid state or a state input to a `Step` has missing inputs.

As a rule of thumb, it is sufficient to forward these errors as one of these two:

* {exc}`librelane.engine.FlowError`
  * {exc}`librelane.engine.FlowException`

Which share a similar hierarchy. Here is how the workflow engine handles a
step's errors:

```{literalinclude} ../../../librelane/engine/engine.py
---
language: python
start-after: "shutil.rmtree(step_dir, ignore_errors=True)"
end-before: "submitted.executed += 1"
---
```

As you may see, the deferred errors are saved for later, but the other two are
forwarded pretty much-as is. If no other errors are encountered, the deferred
errors are logged then reported as a `StepException`.
