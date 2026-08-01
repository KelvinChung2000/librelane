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
LibreLane's own flows -- `Classic`, `VHDLClassic`, `Chip` and the five
open-in flows -- are exactly this and nothing else; they live in
`librelane/flows/*.yaml`.

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
from librelane.flows import load_flow_spec
from librelane.flows.engine import Workflow

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

{py:meth}`librelane.flows.Flow.start` returns the final output state. The step
objects the run created are left on the flow instance as `step_objects`.

`--flow` on the command line takes a *registered* name, not a path, so to run
your document that way register it at import time and load your module as a
[plugin](./writing_plugins.md):

```python
from librelane.flows import Flow, load_flow_spec

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
including multi-provider jobs and its limitations, and
[Writing Tool Backends](./writing_tool_backends.md) for how to register a new
provider.

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

See `librelane/flows/classic.yaml` for a complete example: half of its
forty-eight jobs carry an `if`, and the variables they name are declared in its
own `config` section.

## Fully Customized Flows

Each `Flow` subclass must:

* Declare the steps used in the `Steps` attribute.
  * The steps are examined so their configuration variables can be validated ahead of time.
* Implement the {meth}`librelane.flows.Flow.run` method.
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
Classic - Stage 17 - CTS ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 16/37 0:00:20
```

The Flow object has methods to manage this progress bar:

* {py:meth}`librelane.flows.Flow.progress_bar.set_max_stage_count`
* {py:meth}`librelane.flows.Flow.progress_bar.start_stage`
* {py:meth}`librelane.flows.Flow.progress_bar.end_stage`.

They are to be called from inside the `run` method. A workflow advances the bar
once per step, so {math}`|Steps| = n`, but in a custom flow one bar stage can
incorporate any number of steps. This is useful for example when running series
of steps in parallel as shown in the next section, where incrementing by step is
not exactly viable.

### Multi-Threading

```{important}
The `Flow` object is NOT thread-safe. If you're going to run one or more steps
in parallel, please follow this guide on how to do so.
```

The `Flow` object offers a method to run steps asynchronously, {meth}`librelane.flows.Flow.start_step_async`.
This method returns a [`Future`](https://en.wikipedia.org/wiki/Futures_and_promises)
encapsulating a State object, which can then be used as an input to future Steps.

This approach creates a dependency chain between steps, so if you attempt to
inspect the last Future from a set of asynchronous steps, it will automatically
run the required steps, in parallel if need be.

Here is a flow built on exactly this principle. It runs two floorplanning
attempts concurrently and keeps whichever produced the smaller die.

```python
@Flow.factory.register()
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
{meth}`librelane.flows.Flow.start_step_async` seam exists for. Note that the
`Flow` object is not thread-safe, so everything above happens on one thread and
only the steps themselves run concurrently.

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

* {exc}`librelane.flows.FlowError`
  * {exc}`librelane.flows.FlowException`

Which share a similar hierarchy. Here is how the workflow engine handles a
step's errors:

```{literalinclude} ../../../librelane/flows/engine.py
---
language: python
start-after: "shutil.rmtree(step_dir, ignore_errors=True)"
end-before: "submitted.executed += 1"
---
```

As you may see, the deferred errors are saved for later, but the other two are
forwarded pretty much-as is. If no other errors are encountered, the deferred
errors are logged then reported as a `StepException`.
