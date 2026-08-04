# Architectural Overview

At its core level, LibreLane is an infrastructure in which **Flows** could be
built out of multiple atomic execution units called **Steps**, and then run with
a **Configuration**.

LibreLane is implemented as a Python module with the following architecture:

```{image} ./architecture.svg
:alt: An architectural view of LibreLane
:align: center
:width: 80%
```

The module is accessible via Python scripts, Jupyter Notebooks and a (limited)
command-line API.

The module consists of four submodules:

* {mod}`librelane.engine`
* {mod}`librelane.steps`
* {mod}`librelane.config`
* {mod}`librelane.state`

…with an assisting module named {mod}`librelane.common`.

## States

A {class}`librelane.state.State` is a snapshot of paths to the various different
views of the design (e.g. Netlist, DEF, GDS, etc.) at any point in time.

Keys must be of the type {class}`librelane.state.DesignFormat` and values must
be either:

* Of the type {class}`librelane.config.Path`.
* N-nested dictionaries with key values such that the leaves are of the type
  {class}`librelane.config.Path` as well.

States also have another property: metrics. This attribute captures design
metrics, which may be read and/or updated by any step.

## Steps

Steps are the primary execution unit of LibreLane.

Each step takes two inputs: a **Configuration Object** and a **State**, and
returns an **output** State.

Steps should align themselves to one principle:

* <u>The same step with the same input configuration and same input state must
  emit the same output.</u>

In other words, for the same version of LibreLane, the output state is strictly
a function of the input configuration and the input state.

(ref-step-strictures)=

This is applied as far as the functionality goes:

* Steps **do NOT** modify files in-place. New files must be created in the
  step's dedicated directory. If the tool does not support out-of-place
  modification, copy the files then modify the copies.
* Steps **do NOT** modify the config_in. This is programmatically enforced.
* Steps **do NOT** rely on external filesystem paths. If a path is not in the
  configuration or in the input state, it effectively does not exist to the
  Step.
  * This applies the other way around as well: Steps **do NOT** create files
    outside of their step directory.
* Steps **do** fix
  [PRNG](https://en.wikipedia.org/wiki/Pseudorandom_number_generator) seeds for
  replicability. They can be exposed as a configuration variable.

More of these strictures may be programatically enforced by the infrastructure
in the future.

Some aspects cannot be made entirely deterministic, such as timestamps in views,
file paths and the like. These are acceptable breaks from this dogma.

The {class}`librelane.steps.Step` class is an
[abstract base class](https://docs.python.org/3/glossary.html#term-abstract-base-class)
from which all other steps inherit and is the implementation of this part of the
LibreLane architecture.

## Flows

Flows are scripts that incorporate multiple `Step`s to achieve a certain
function.

The {class}`librelane.engine.Flow` class is an
[abstract base class](https://docs.python.org/3/glossary.html#term-abstract-base-class)
from which all other flows inherit.

### Workflows

The flow LibreLane ships is not written in Python at all. It is a **workflow
document**: a YAML file declaring a graph of named **jobs** and the edges
between them. {class}`librelane.engine.engine.Workflow` is the one concrete
`Flow` in the codebase, and running a document means handing it to that class.

Within a job, steps run in sequence, sharing one configuration object and
threading a state through, i.e.

```{math}
  State_{i} = Step_{i}(State_{i - 1}, Config)
```

So, for a job of {math}`n` steps, {math}`State_{n}` is what that job
contributes.

Between jobs, the engine runs the graph as a Petri net: a job fires once every
edge into it has delivered a state, and two jobs with no path between them run
concurrently. The run's final state is the join of the leaves.

The default flow of LibreLane when run from the command-line is the workflow
document named [`Classic`](./flows.md#classic), which is based off of OpenLane.
See [Writing Custom Flows](../usage/writing_custom_flows.md) for how to write
one of your own.

## Configuration

### Objects

Configuration objects are a thoroughly-validated dictionary of values assigned
to various configuration variables throughout a flow.

A flow's configuration variables in an aggregate of all its incorporate steps.

The configuration object supports Python's basic scalars (except for `float`),
`Decimal`, `List` and `Dict`, the latter two infinitely nestable. Steps are
given this configuration object as an input.

### Builder

The configuration builder takes a `Flow` and a raw configuration object as an
input, which can be one more of:

* A Python dictionary
* A path to an existent JSON configuration file
* A path to an existent YAML file
* A path to an existent Tcl configuration file

and then validates this configuration, resolving paths, fixing types and other
such tasks along the way, returning the {class}`librelane.config.Config` class
which is essentially a validated and immutable string dictionary.
