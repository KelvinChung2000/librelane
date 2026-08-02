# Workflow Loops, Conditionals and Resources Design

Spec 3 of four. Spec 2, `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`,
deferred three things here by name: loops, general conditional expressions
beyond a Boolean configuration variable, and resource contention. All three
land in this spec, on the engine spec 2 built and without rewriting it.

## Goal

A workflow document can declare a loop that reruns part of the graph until a
metric satisfies a predicate, a sweep that runs one job at several settings and
keeps the best result, a runtime condition that gates a job on a metric of its
input state, and a named resource pool that bounds how many jobs use a scarce
tool at once.

## Scope

In scope. Cycles in `needs` with a single `until` gate per cycle, an explicit
value schedule (`iterations`) or a pass bound (`max`), the sweep mode with a
`select` rule, `metric::` predicate terms in `if` and `until`, and top-level
`resources` pools with per-job acquisition.

Out of scope, deliberately. Computed or generated iteration values (the
schedule is a literal list). Sweep bodies of more than one job. Nested or
overlapping cycles, and cycles that are not simple rings. Negation and
disjunction in predicates (`and` remains the only connective). Pool priorities
or fairness beyond first-enabled-first-served. Each of these is a real feature
someone may someday want, and each is omitted because the shipped flows and the
motivating cases below need none of them, and every one of them can be added
later without changing what this spec defines.

## Motivation

The reason a loop needs more than a back edge is the observation that shaped
this design: rerunning a job changes nothing unless something changed. A step's
resume key hashes its configuration and its input state, so a pass that repeats
both would reuse the previous result and the loop would spin without effect.
Exactly two things can legitimately differ between passes, and the design makes
each one explicit rather than implied.

The first is the circulating state. In an incremental-repair loop, each pass
consumes the previous pass's output, so the input state differs by
construction. Resizing cells to fix setup violations and re-running STA to
count what remains is this shape, and it needs no configuration change at all,
only a bound so it cannot spin forever.

The second is the configuration. In an escalation loop, each pass runs at the
next entry of an explicit value schedule, so pass 3 differs from pass 2 because
the document says pass 3 sets `PL_TARGET_DENSITY: 0.7`. The schedule is a
literal list in the document, reviewable in one place, rather than an
expression evaluated somewhere the author cannot see.

Sweeps are the same schedule under a different rule. An escalation stops at the
first pass that satisfies the gate; a sweep runs every entry and keeps the best
by a stated metric. Both are declared with the same `iterations` key because
they are the same list, and they differ only in `mode`.

Resource pools exist because concurrency arrived in spec 2 and some tools
cannot take it. A licensed DRC tool with two seats, or a step that maps a whole
chip into memory, must not be run at `-j` parallelism just because the graph
allows it. Today the only recourse is lowering `-j`, which serializes the whole
flow to protect one tool.

## Architecture

### A loop is a cycle in `needs`

Spec 2 made a cycle a load error. This spec makes a *well-formed* cycle a loop
and keeps everything else an error, with a message that says what well-formed
means.

A well-formed cycle is a simple ring: a strongly connected component of the
job graph in which every member has exactly one predecessor inside the
component. Exactly one member of the ring declares `until`; that member is the
**gate**. Only the gate may have consumers outside the ring, so every result
that leaves the loop leaves through the job that decided the loop was done. A
non-gate member with an outside consumer is a load error naming both jobs and
both remedies (move the consumer's `needs` to the gate, or move `until` to the
member). Because rings are strongly connected components, no job can belong to
two of them, so nesting and overlap are structurally impossible rather than
checked.

```yaml
jobs:
  cts:
    ...
  resize:
    needs: [cts, sta]          # the back edge: sta -> resize closes the ring
  sta:
    needs: [resize]
    until: "metric::timing__setup__ws >= 0"
    iterations:
      - {PL_RESIZER_HOLD_SLACK_MARGIN: 0.1}
      - {PL_RESIZER_HOLD_SLACK_MARGIN: 0.2}
      - {PL_RESIZER_HOLD_SLACK_MARGIN: 0.4}
```

### The net stays acyclic

The engine does not run a cyclic net. At resolution time each ring collapses
into one synthetic node, the **loop instance**, whose input arcs are every
external edge into any member and whose output arcs are the gate's external
edges. The `Net` class is untouched: one place per arc, one token per place, a
transition fires once. Every invariant spec 2 asserts remains literally true,
because the graph the net sees is acyclic by construction.

Spec 2 anticipated the opposite, saying its one-token assertion would become a
per-place capacity check when spec 3 arrived. That expectation is amended here
rather than honoured, for a reason spec 2 could not see: iterations of an
escalation loop are sequential by definition (pass k+1 consumes pass k's
output), so at no instant does any place hold two tokens, and encoding the back
edge as a marked place would only reintroduce the entry problem every textbook
cyclic marking has, of a back-edge place that is empty on the first pass. The
loop driver below is the honest encoding of "sequential by definition".

### The loop driver

The loop instance is scheduled exactly like a job: it becomes enabled when all
its input places hold tokens, it is submitted to the worker pool, and it fires
its output arcs once with a single state. Inside, it runs passes.

External tokens are consumed once, at entry. On pass 1, each member's input is
the join of the circulating state with that member's own external tokens, under
the ordinary join rule and the member's own `source`. On every later pass a
member receives only the circulating state, which by then already carries every
view the external producers contributed, so nothing is lost and nothing is
consumed twice.

One pass runs the members in ring order starting from the gate's intra-ring
successor and ending at the gate. After the gate completes pass k, the driver
evaluates `until` against the gate's output metrics:

- True: the loop exits. The gate's output state is deposited on the loop
  instance's output arcs.
- False, and k is below the bound: pass k+1 begins with the gate's output as
  the circulating state.
- False, and k is the bound: the schedule is exhausted. The loop exits with the
  last pass's state **and** records a deferred error naming the gate, the
  predicate, the observed value and the bound. Deferred, not fatal, for the
  same reason a checker gate defers: the run continued past the disappointment
  and produced real views, and downstream signoff on those views is exactly the
  information wanted when a loop gives up. The flow fails at the end, as every
  deferred error makes it fail, after the remaining jobs have run.

A step failing inside any pass fails the loop instance the way it fails a job.
The contract check applies to the gate's output on the pass that exits, because
that is the state the loop's consumers receive.

### `iterations` and `max`

The gate declares exactly one of the two; `until` alone is a load error because
it declares no bound and an unbounded loop is not accepted from any document.

`iterations` is a non-empty list of value mappings. Pass k layers entry k onto
the configuration of **every member** for that pass. The bound is the list's
length. An entry may be the empty mapping `{}`, meaning pass k changes no
value, which is how a schedule expresses "try once more unchanged before
escalating". Entries obey the same refusals as any `with` block: no `PDK`,
`SCL`, `PAD`, `meta`, no `TOOLS`.

`max` is a positive integer and nothing more. The bound is `max` and no pass
changes any value, which is the incremental-repair shape.

Iteration values layer **above the design configuration** and below
`--config-override`. This deliberately breaks the design-always-wins rule that
governs `with` blocks, and the break is the feature: the schedule is the loop's
algorithm, not a default, and a design that pinned the scheduled variable would
otherwise reduce every escalation loop to `max` passes at one setting, silently.
The command-line override still wins because it is the operator's explicit last
word. Provenance records the layer as `<flow document: sta, iteration 3>`, so
`--explain-variables` attributes the value to the pass that set it.

The covering rule for job-level `with` blocks extends to schedules with the
same justification. A variable named by any `iterations` entry must be read
only by jobs inside the ring. A reader outside the ring would resolve the
design's value while the ring resolved the schedule's, which is the silent
divergence the covering rule exists to make a load error, and the error names
the variable and the outside reader.

### Predicates: one grammar for `if` and `until`

A predicate is a conjunction of terms joined by the literal `and`, exactly as
`if` is today. What changes is what a term may be:

- A bare identifier remains a Boolean configuration variable the flow declares,
  with the exact load-time checks that exist today. Every shipped document is
  unchanged and unchanged in meaning.
- `metric::<name> <op> <literal>` is a runtime term. The namespace prefix
  follows the established `ref::`/`expr::`/`pdk::` idiom, and it exists because
  a bare name must keep meaning a configuration variable; without the prefix,
  the grammar could not tell the two apart and neither could a reader. `<op>`
  is one of `==`, `!=`, `<`, `<=`, `>`, `>=`. `<literal>` is an optionally
  signed integer or decimal number. A term splits on whitespace into exactly
  three parts. Metric names contain no whitespace but may contain colons, as
  corner-qualified metrics do, which is why whitespace and not `:` is the
  delimiter and why the `metric::` prefix is stripped once from the front
  rather than split on.

`until` accepts only `metric::` terms. A configuration variable is constant
across passes, so a gate conjoining one is either always exiting on pass 1 or
never exiting at all, and both are documents saying something they cannot mean.
The load error states this.

`if` accepts both kinds mixed. Configuration terms are evaluated at
construction, exactly as today. Runtime terms are evaluated when the job's
input places are full, against the metrics of the joined input state, on the
scheduling thread before submission. A false runtime term fires the job as a
pass-through, and the reason names the term and the observed value
(`metric::antenna__violating__nets == 0 is false: observed 3`), so `--explain`
after the fact and the log during the run say the same thing. A runtime term
whose metric is absent from the input state fails the job with an error naming
the job, the metric and the metrics that were present. Absence is not false;
false is a measurement and absence is a missing measurement.

Metric names are not a closed set at load time, so a misspelt metric cannot be
a load error; it surfaces as the missing-metric failure on the first firing.
The grammar itself is fully checked at load: a malformed term, an unknown
operator or a non-numeric literal is a load error quoting the predicate.

A job with runtime terms counts as *enabled* for construction-time selection
validation, because the answer is genuinely unknown before the run. The
existing load warning about a consumer of a conditional producer extends to
runtime terms: a job that `needs` a producer gated by a runtime term and does
not repeat that exact term in its own `if` gets the same warning naming both
jobs, since a passed-through producer contributes no views.

Inside a ring, configuration terms are legal on any member and constant across
passes; runtime terms on non-gate members are evaluated each pass against the
circulating state. An `if` on the gate gates the whole loop instance, firing
it as one pass-through, because a loop whose gate never runs can never decide
to exit; this is also the declarative way to make a loop optional.

Comparisons are numeric. A runtime term whose observed metric value is not a
number is a runtime error naming the metric and the value, for `==` and `!=`
as much as for the orderings, because a predicate that silently compared a
string to a number would be false for a reason no message states.

### Sweep mode

`mode` on a job is `escalate` or `sweep`, defaulting to `escalate`. The default
is only meaningful on a ring, where it names the sequential semantics above.
`sweep` is v1-restricted to a single job that is not a ring member.

```yaml
jobs:
  placement:
    needs: [floorplan]
    mode: sweep
    select: "route__wirelength min"
    iterations:
      - {PL_TARGET_DENSITY: 0.45}
      - {PL_TARGET_DENSITY: 0.55}
      - {PL_TARGET_DENSITY: 0.65}
```

A sweep declares `iterations` (the sweep points; `max` is meaningless and a
load error) and `select`, and never `until`: it does not stop early, it runs
every point and chooses. `select` is a metric name and a direction, `min` or
`max`. The name is bare, without the `metric::` prefix, because this field
admits nothing but metrics and a disambiguating prefix with nothing to
disambiguate from would be noise.

When the job's input places fill, the tokens are consumed once and joined once.
The engine then runs N independent executions of the job's steps, all from that
same input state, each layering its `iterations` entry, concurrently up to `-j`
and subject to the job's resource pools per execution. Each execution writes
under its own pass directory. When all have finished, the engine reads the
`select` metric off every output state; an execution whose output lacks it is
an error naming the job, the pass and the metric, because a sweep that cannot
compare its results has no result. The winner is the minimum or maximum; ties
break to the lowest pass index, so a tie is deterministic and reruns pick the
same winner. The winner's state is deposited on the output arcs. Losing
outputs stay on disk under their pass directories, reviewable but not
propagated. Each execution's step instances carry the pass in their id,
`Step.Id (job/3)`, because the logging layer keys live steps by id and two
concurrent executions of one step class under one job id would otherwise share
a key; ring members carry the pass the same way, so pass 3 is distinguishable
from pass 2 in the log.

A losing execution's deferred errors are logged as warnings naming the pass and
are not raised, because the flow does not use that state and failing the run
over a result it discarded would punish the sweep for exploring. The winner's
deferred errors propagate exactly as a job's do. Every execution's output,
winner or loser, is contract-checked, because a provider that only sometimes
honours its contract is precisely what the contract check exists to catch.

A step raising in any execution fails the job; the other executions finish
(they are already running) and their results are discarded with the failure
reported once.

### Resource pools

A document declares pools at the top level; a job names the pools it needs.

```yaml
resources:
  drc_seats: 2
  heavy_memory: MAX_HEAVY_JOBS

jobs:
  drc:
    resources: [drc_seats]
```

A capacity is a positive integer literal or the name of a configuration
variable the flow declares with type `int`. A variable capacity is resolved
once, at construction, and a resolved value below 1 is a construction error
naming the variable and the value, because a pool nothing can ever enter is a
flow that stalls by declaration.

Pools live in the scheduler, not in the net. Spec 2 sketched a semaphore as a
place with capacity above one; this spec deviates, and the reason is what a
token is. The net's tokens are `State` objects, deposited by a producer and
joined by a consumer. A pool token is anonymous, carries nothing and is
returned rather than consumed. Modelling it as a place would thread a second
token kind through every marking operation so that the join can ignore it,
which is machinery in service of a diagram. The scheduler already decides,
single-threaded, which enabled transitions to submit; pools are counters it
checks at that decision.

Concretely, the pools are one lock-protected set of counters shared by
everything that runs work. The scheduler consults it without blocking: an
enabled job whose pools are full is simply not submitted this round, and is
reconsidered when any running work completes or any pool slot frees. Loop
passes run on worker threads and *block*-acquire through the same object,
waiting on its condition until their slots free; sweep executions are admitted
like ordinary jobs, each of the N passes non-blockingly on the scheduling
thread. Both paths take all named pools together under the one lock or take
nothing.

The scheduler also never submits more work than the executor has workers. This
is not a throughput choice but the second half of the safety argument: a pool
slot is granted only to work that starts running immediately, so a granted
slot is always held by an execution that is making progress toward releasing
it. Without this, a slot could be granted to a job still queued for a worker
while every worker is a loop pass blocked on that same slot — a cycle between
pool grants and worker threads that the pool object alone cannot see. Work
that cannot get a worker parks, unadmitted, holding nothing.

The rules:

- Acquisition is all-or-nothing, and a slot is only ever granted to work
  actively running on a worker. A waiter holds no slots while it waits, so
  hold-and-wait never arises among pools; and every holder is running, so
  every wait is on work that finishes and releases. Together these are why
  pools cannot deadlock, whatever the document declares. A pool can still
  *serialize*, which is its purpose.
- A per-pass release inside a loop wakes the scheduler, so a parked job
  sharing a pool with a ring is admitted between passes, not after the whole
  ring.
- Slots are released when the execution finishes, on success and on failure
  alike.
- A pass-through firing acquires nothing, because it runs nothing.
- Loop members acquire per pass and release per pass, so a ten-pass loop does
  not hold a seat while its STA member runs. Sweep executions acquire
  independently, so a two-seat pool runs a five-point sweep two points at a
  time.

`resources` on a job naming an undeclared pool is a load error listing the
declared pools. A duplicate name in one job's list is a load error, as a
duplicate `needs` entry is. A declared pool no job names is legal and inert; a
document that grows a pool before its second user is not wrong.

In this grammar a job's demand on each pool it names is exactly one slot —
`resources` is a list of names, with no per-job weight. Since a capacity below
1 is already a construction error, a demand can never exceed a capacity, and
no over-capacity refusal exists because nothing can express the condition it
would refuse. A future weighted grammar would need that check.

### Run directories and resume

Executions that can happen more than once per run get a pass level in their
directory: `runs/<tag>/<job id>/<k>/<n>-<step-slug>/`, with `k` the 1-based
pass index, for ring members and sweep jobs. Ordinary jobs keep the spec 2
layout unchanged, so no existing run directory or resume entry moves.

Resume needs no new mechanism. A pass's resume key already differs from the
previous pass's through its input state (incremental repair) or its
configuration (the iteration layer), and an unchanged rerun of a loop replays
pass by pass out of the cache until the first divergence, exactly as a linear
flow does. Exhaustion's deferred error, like every deferred error, withholds
nothing: the passes that ran are reusable.

### The command-line surface

`--target` and `--invalidate` treat a ring atomically: naming any member names
the loop instance, so the selection includes every member and the loop's
ancestors or descendants follow from the collapsed graph. `ancestors` and
`descendants` operate on the collapsed graph, which is acyclic, so they need no
cycle guard.

`--skip` refuses a ring member, naming the ring and explaining that a loop
whose gate never runs cannot decide to exit; a loop is skipped the way a job
is, by gating it with `if` on the gate. `--skip` on a sweep job skips the whole
sweep as an ordinary pass-through.

`--reproducible` refuses a step inside a ring or a sweep job in v1, saying
which pass would be ambiguous. This is a real loss accepted knowingly: the
escape hatch for debugging a loop pass is the pass directory itself, which
holds the step's config and state like any step directory.

`--explain` reports a ring as its members with a `loop` mechanism column entry
on each, the gate marked, and the bound stated in the reason
(`loop gated by 'sta', at most 3 passes`). A sweep job's reason states the
point count and the rule (`sweep of 3 points, keeps route__wirelength min`).
Runtime-conditional jobs report `condition (runtime)` with the term, and
whether it held is knowable only after the run, which the reason says.

## Document schema changes

`JobSpec` grows `until: str | None`, `iterations: list[dict[str, Any]] | None`,
`max: int | None`, `mode: Literal["escalate", "sweep"] = "escalate"`,
`select: str | None`, and `resources: list[str] = []`. `FlowSpec` grows
`resources: dict[str, int | str] = {}`. `_JOB_KEYS` extends accordingly, so
the unknown-key error stays exhaustive.

`parse_condition` becomes the parser of the shared term grammar, returning
structured terms rather than bare names, and remains the only implementation of
it; `until` reuses its term parsing rather than growing its own. `select` is
not a predicate — it is a two-token `<metric> min|max` shape with no operator
or literal, so it is validated as that shape directly rather than through the
term grammar. `ResolvedJob` carries the parsed forms.

## Load-time errors

Every rule above that says "load error" lands in the existing validator chain,
before any run directory exists, with a message naming the job and the remedy.
Enumerated, the new refusals:

- A cycle that is not a simple ring.
- A ring with no `until`, or more than one.
- A non-gate ring member with a consumer outside the ring.
- `until` with neither `iterations` nor `max`, or with both.
- `until`, `iterations`, `max`, `mode: sweep` or `select` on a job where the
  combination is meaningless: `until` off a ring gate, `iterations` without
  `until` or `mode: sweep`, `max` without `until`, `select` without
  `mode: sweep`, `mode: sweep` without `iterations` or `select`, `mode: sweep`
  on a ring member.
- An empty `iterations` list, or an entry naming `PDK`, `SCL`, `PAD`, `meta`
  or `TOOLS`.
- A schedule variable read by a job outside the ring.
- A malformed predicate term, an unknown operator, a non-numeric literal, or a
  configuration-variable term in `until`.
- `resources` naming an undeclared pool, a duplicate pool, or a literal
  capacity below 1. A capacity naming a variable that is not declared by the
  flow with type `int`.
- `final` naming a non-gate ring member, whose output never leaves the loop.

Construction-time (the configuration exists, the run directory still does
not): a variable capacity resolving below 1.

## Runtime errors

- A runtime `if` term whose metric the joined input state lacks: the job
  fails, naming job, metric and the metrics present.
- An `until` term whose metric the gate's output lacks: the loop fails on that
  pass, same naming.
- A sweep execution whose output lacks the `select` metric: the sweep fails,
  naming the pass.
- Schedule exhaustion: a deferred error, raised with the others at flow end.

## Testing

Unit tests against documents and fake steps, no tools, extending the existing
`test/flows/` suites.

- One test per load error above, asserting the message names the job and the
  remedy.
- The grammar: each operator parses and evaluates; each malformed shape raises;
  a metric name containing `::` internal colons parses; mixed
  configuration-and-metric conjunctions evaluate both halves.
- The loop driver: a ring that converges on pass 2 exits with pass 2's state
  and ran pass 1's members once each; the iteration layer is visible in each
  pass's step configuration and provenance; external tokens join on pass 1
  only; exhaustion defers and the flow fails at the end with downstream jobs
  having run; a rerun with nothing changed reuses every pass.
- Sweep: the winner by `min` and by `max`; the tie to the lowest index; a
  missing `select` metric fails; a losing pass's deferral warns without
  failing; every pass is contract-checked.
- Pools: a one-seat pool serializes two enabled jobs (observable through
  submission order with a controlled pool); capacity from a variable; the
  below-1 construction error; release on failure.
- Runtime `if`: true runs, false passes through with the observed value in the
  reason, missing metric fails, the consumer warning fires on an unrepeated
  runtime term.
- CLI composition: `--target` on a ring member selects the ring; `--skip` and
  `--reproducible` refusals.

Integration: the shipped documents load unchanged and resolve to unchanged step
sets, pinning that nothing here altered spec 2 behaviour for documents that use
none of it.

## Migration

None. No shipped document declares a loop, a sweep, a runtime term or a pool,
and every existing key keeps its meaning. This spec is additive at the document
surface; the only shipped-behaviour change is that the cycle error's wording
now describes what a legal cycle is.

`docs/source/usage/writing_custom_flows.md` gains sections for loops, sweeps,
runtime conditions and pools, written against the shipped grammar.
