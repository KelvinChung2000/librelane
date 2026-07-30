# Resuming Runs

Hardening a design is expensive, and most of the time you change one thing and
want to see its effect. LibreLane keeps every step's result in the run directory
and reuses the ones your change did not touch.

## The two modes

Naming a run tag that already exists resumes it. Either of these does that:

```console
$ librelane --run-tag my_run ./config.yaml
$ librelane --last-run ./config.yaml
```

Every step whose work is unchanged is reused, and the run picks up wherever the
previous invocation stopped, whether that was a completed flow, a crash or a
`Ctrl+C`.

Adding `--overwrite` deletes the run directory and starts clean:

```console
$ librelane --run-tag my_run --overwrite ./config.yaml
```

There is no third mode. A run tag is either resumed or discarded.

## What counts as unchanged

A step is reused when all of the following hold.

* Its own configuration is unchanged. Each step sees its own variables plus the
  variables common to every flow, so editing a variable no step in your flow
  reads changes nothing.
* The contents of every file that configuration names are unchanged. This is
  contents, not paths and not timestamps. Editing `src/design.v` in place
  invalidates synthesis even though the path is identical, and `touch`-ing it
  without editing does not.
* Its entire input state is unchanged, including metrics. Checker steps read
  metrics, so a changed metric is a changed input.
* The outputs it recorded still exist on disk. Delete a step's `.def` and that
  step runs again.
* The LibreLane version is unchanged.

Anything LibreLane cannot prove is treated as changed, so the step re-runs. That
includes a `resume.json` truncated by an interrupted write.

## Invalidation cascades

Re-running a step changes what the step after it receives, so that step is
re-run too, and so on to the end of the flow.

The cascade follows contents rather than executions. If a re-run step produces
byte-identical output, the steps after it are still valid and are still reused.
Restoring a deleted `.def` costs you that one step, not the rest of the flow.

## Step directory numbering

A step's directory under `runs/TAG/` is named for its position in the flow, not
for how many steps happened to run:

```
runs/my_run/
├── 1-verilator-lint
├── 2-checker-linttimingconstructs
├── 4-yosys-synthesis
...
```

Position `3` is missing there because that step was skipped or gated off. The
gap is deliberate. A step keeps the same directory whether or not the steps
before it ran, which is what lets a resumed run find its own previous result.

## Forcing a step to re-run

One thing the reuse check cannot see is your tools. Upgrading OpenROAD in place,
or editing a `.tcl` script in a development checkout, changes what a step
produces without changing anything LibreLane hashes. The reused result will be
stale and LibreLane will not know.

Two remedies:

```console
$ librelane --last-run --from openroad.globalplacement ./config.yaml
$ librelane --run-tag my_run --overwrite ./config.yaml
```

`--from` re-executes the named step and everything after it, ignoring their
recorded results. The steps before it are taken from their previous results, and
if one of them has none, LibreLane names it and stops rather than continuing on
a state it cannot justify.

Supplying `--with-initial-state` alongside `--from` skips the earlier steps
instead of resolving them, because that state is what stands in for them. This
is the pattern the {doc}`ECO guide <using_ecos>` uses.

`--overwrite` discards everything and is the blunt instrument when you would
rather not reason about it.

## Which flows participate

Resume applies to sequential flows, which includes `Classic` and every flow
built from a fixed list of steps.

`Optimizing` and `SynthesisExploration` build their steps in data-dependent
loops, so a step's position is not knowable in advance and there is nothing
stable to reuse against. They re-run in full.
