# Writing Custom Flows

As configurable as the default ("Classic") flow may be, there are some designs
that would simply be too complex to implement using the existing flow.

For example, hardening a macro + padframe for a top level design is too complex
using the Classic flow, and may require you to write your own custom-based flow.

**_First of all_**, please review LibreLane's high-level architecture [at this link](../reference/architecture.md).

This defines many of the terms used and enumerates strictures mentioned in this document.

## Custom Sequential Flows

### In Configuration Files

(config-substituting-steps)=
#### By Substituting Steps

If you're constructing a flow that is largely based on another flow, albeit
with some substitutions or removals, you may declare your base flow and
substitutions as follows:

<table>
<tr>
  <th>JSON</th>
  <th>YAML</th>
</tr>
<tr>
  <td>

```json
{
  "meta": {
    "flow": "Classic",
    "substituting_steps": {
      "OpenROAD.STAMidPNR*": null,
      "Magic.DRC": "KLayout.DRC",
    }
  }
}
```

  </td>
  <td>

```yaml
meta:
  flow: Classic
  substituting_steps:
    "OpenROAD.STAMidPnR*": null
    "Magic.DRC": "KLayout.DRC"
```

  </td>
</tr>
</table>

This replaces `Magic.DRC` with *another* `KLayout.DRC` step (which is
useless but this is just for demonstration); and removes all steps starting
with `OpenROAD.STAMidPNR` from the `Classic` flow.

Instead of replacing, you can also emplace steps before or after steps. Simply
put a `-` before the target step ID to place before, and a `+` to place after.

Substitutions are more useful if you have custom steps registered in
[LibreLane Plugins](./writing_plugins.md).

(config-by-listing-steps)=
#### By Listing Steps

If your custom sequential flow entirely relies on built-in steps, you can
actually specify a flow entirely in the `config.json` file, with no API access
needed:

```json
{
  "meta": {
    "version": 2,
    "flow": [
      "Yosys.Synthesis",
      "OpenROAD.CheckSDCFiles",
      "OpenROAD.Floorplan",
      "OpenROAD.TapEndcapInsertion",
      "OpenROAD.GeneratePDN",
      "OpenROAD.IOPlacement",
      "OpenROAD.GlobalPlacement",
      "OpenROAD.DetailedPlacement",
      "OpenROAD.GlobalRouting",
      "OpenROAD.DetailedRouting",
      "OpenROAD.FillInsertion",
      "Magic.StreamOut",
      "Magic.DRC",
      "Magic.SpiceExtraction",
      "Netgen.LVS"
    ]
  }
}
```

### Using the API

#### By Listing Steps

You'll need to import the `Flow` class as well as any steps you intend to use.

An equivalent flow to the one in {ref}`config-by-listing-steps` would look
something like this:

```python
from librelane.flows import SequentialFlow
from librelane.steps import Yosys, Misc, OpenROAD, Magic, Netgen


class MyFlow(SequentialFlow):
    Steps = [
        Yosys.Synthesis,
        OpenROAD.CheckSDCFiles,
        OpenROAD.Floorplan,
        OpenROAD.TapEndcapInsertion,
        OpenROAD.GeneratePDN,
        OpenROAD.IOPlacement,
        OpenROAD.GlobalPlacement,
        OpenROAD.DetailedPlacement,
        OpenROAD.GlobalRouting,
        OpenROAD.DetailedRouting,
        OpenROAD.FillInsertion,
        Magic.StreamOut,
        Magic.DRC,
        Magic.SpiceExtraction,
        Netgen.LVS,
    ]
```

You may then instantiate and start the flow as shown:

```python
flow = MyFlow(
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

The {py:meth}`librelane.flows.Flow.start` method will return a tuple comprised of:

* The final output state ({math}`State_{n}`).
* A list of all step objects created during the running of this flow object.

```{important}
Do NOT call the `run` method of any `Flow` from outside of `Flow` and its
subclasses- consider it a protected method. `start` is class-independent and
does some incredibly important processing.

You should not be overriding `start` either.
```

## Declaring a Flow as Stages

`Classic` and `VHDLClassic` are both built on {class}`librelane.flows.StagedFlow`,
a `SequentialFlow` whose `Steps` list is expanded from a `Stages` list rather
than written out directly. A `Stages` entry is either a `Stage` object, which
expands into whichever concrete steps implement it for the tool it selects, or
a plain `Step` class, for a provider-neutral utility or a step that sits at a
stage boundary. This is a third way to build a sequential flow, alongside
substituting and listing steps above, and the one `Classic` itself uses.

```python
from librelane.flows import StagedFlow
from librelane.stages import Stage


class MyStagedFlow(StagedFlow):
    Stages = [
        Stage.synthesis,
        Stage.pre_pnr_sta,
        Stage.floorplan,
        Stage.macro_placement,
        Stage.power_grid,
        Stage.io_placement,
        Stage.global_placement,
        Stage.detailed_placement,
        Stage.global_routing,
        Stage.streamout,
        Stage.drc,
    ]
```

Every stage here happens to have no gating variable of its own, which keeps
the example self-contained. A stage that does declare one, such as `cts` or
`detailed_routing`, needs the matching Boolean declared in the flow's own
`Config`, exactly as any other configuration variable a step reads would; see
`Classic`'s `Config` in `librelane/flows/classic.py` for a complete example.

`Steps` is populated from `Stages` at class-definition time, using each
stage's default provider, so every existing `SequentialFlow` facility -
`Substitute`, `get_help_md`, step IDs and step directory names - keeps working
unchanged.

What a `Stages` list buys over a plain `Steps` list is that the tool behind
each stage becomes a configuration choice instead of a hardcoded step class.
A user sets the `TOOLS` configuration variable to pick a different provider
for one or more stages, for example `{"streamout": "klayout"}` to run only
KLayout's stream-out instead of both Magic's and KLayout's. A flow author can
also pin a stage to a specific provider from inside the `Stages` list itself
with `Stage.using`, as `VHDLClassic` does for `synthesis`; a pin is the flow's
default, not a lock, since a matching `TOOLS` entry still overrides it.

See [Swapping Tools](./swapping_tools.md) for the full `TOOLS` reference,
including multi-provider stages and its limitations, and
[Writing Tool Backends](./writing_tool_backends.md) for how to register a new
provider.

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

Another advantage of this over sequential flows is that you can handle Step failures
more elegantly, i.e., by trying something else when a particular Step (or set of steps) fail.
There are a lot of possibilities.

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

They are to be called from inside the `run` method. In Sequential Flows,
{math}`|Steps| = |Stages| = n`, but in custom flows, stages can incorporate any
number of steps. This is useful for example when running series of steps in parallel
as shown in the next section, where incrementing by step is not exactly viable.

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

Here is a demo flow built on exactly this principle. It works across two stages:

* The Synthesis Exploration - tries multiple synthesis strategies in _parallel_.
  The best-performing strategy in terms of minimizing the area makes it to the
  next stage.
* Floorplanning and Placement - tries FP and placement with a high utilization.
  * If the high utilization fails, a lower is fallen back to as a suggestion.

```{literalinclude} ../../../librelane/flows/optimizing.py
---
language: python
start-after: "@Flow.factory.register()"
---
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

* {exc}`librelane.flows.FlowError`
  * {exc}`librelane.flows.FlowException`

Which share a similar hierarchy. Here is how `SequentialFlow`, for example, handles
its `StepError`s:

```{literalinclude} ../../../librelane/flows/sequential.py
---
language: python
start-after: "step_list.append(step)"
end-before: "self.progress_bar.end_stage(increment_ordinal=increment_ordinal)"
---
```

As you may see, the deferred errors are saved for later, but the other two are
forwarded pretty much-as is. If no other errors are encountered, the deferred
errors are logged then reported as a `StepException`.
