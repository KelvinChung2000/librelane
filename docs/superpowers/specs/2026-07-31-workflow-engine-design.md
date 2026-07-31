# Workflow Engine Design

Spec 2 of four. Forward-referenced at
`docs/superpowers/specs/2026-07-30-flow-mechanism-unification-design.md:162-163`.

## Goal

Replace LibreLane's flow mechanism with a declarative workflow document executed
on a Petri net. A flow stops being a Python class and becomes a YAML document
naming jobs and the edges between them. The stage taxonomy and the workflow job
become one concept. Concurrency follows from the graph rather than being absent
by construction.

## Scope

In scope, the acyclic case. The net, the document schema and its loader, the
job/stage unification, conditions, the state join, run directory layout, resume,
the command-line surface, and the migration of all six shipped flows with no
loss of function.

Out of scope, deferred to spec 3. Loops, general conditional expressions beyond
a Boolean configuration variable, and resource contention. The firing rule is
written for the general case so spec 3 extends the engine rather than replacing
it.

## Motivation

Three defects in the current mechanism motivate this, and each one has direct
evidence in the tree.

A flow's step order is a Python list, and nothing in a step's declared view
contract can reproduce it, because `PNR_IN_PLACE_REQUIRES` and
`PNR_IN_PLACE_PROVIDES` are the identical tuple `(def_, nl, sdc)` for 14 of the
27 stages. Order is therefore real information that lives nowhere except list
position, and list position cannot express that DRC and LVS are independent.

The stage grouping has to be recovered from the flat step list at runtime. The
registry subclasses every step to carry a `_stage_span` and `_stage_provider`
tag, and `StagedFlow` reads those tags back to rebuild the grouping it already
had before flattening. That apparatus is `Boundary`, `_span_for`, `_boundaries`,
`_after_step`, `stage_boundaries`, `provider_boundaries`, `ResolvedSpan` and
`Resolution.spans`, 28 references in `staged.py` alone, and it exists only
because the flow declares a list where it means a graph.

Gating is a side-channel. `Flow.gating_config_vars` is a dictionary keyed by
step-ID wildcards, declared outside the step list it modifies. Its actual
contents are not step gating at all. `Magic.StreamOut` and `KLayout.StreamOut`
are the two providers of one stage, so `RUN_MAGIC_STREAMOUT` is provider
selection wearing a Boolean, duplicating `TOOLS` with no diagnostic when the two
disagree. The three-variable entries are worse. `Checker.XOR` gates on
`RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT and RUN_KLAYOUT_STREAMOUT` because XOR
compares two GDSII files and needs both producers to have run, which is a
hand-maintained encoding of a graph edge.

## Architecture

### The net

Places are arcs, not jobs. A job with two consumers deposits one token on each
of its two outgoing places.

```
Job = transition.   Place = one edge.   Token = a State.

        ┌───────────┐  p:so→drc   ┌─────┐  p:drc→xor  ┌─────┐
  ...──▶│ streamout │────────────▶│ drc │────────────▶│ xor │──▶
        └───────────┘             └─────┘             └─────┘
              │                                          ▲
              │       p:so→lvs   ┌─────┐  p:lvs→xor      │
              └─────────────────▶│ lvs │─────────────────┘
                                 └─────┘
```

A transition is enabled when every input place holds a token. Firing consumes
one token from each input place and deposits one token on each output place.

One place per job rather than per arc would force a producer to deposit N
tokens and the scheduler to know N, leaking the fan-out count into the encoding.
Per-arc keeps the firing rule literally true as stated, and it is the encoding
spec 3 needs unchanged, because a loop genuinely consumes its token and a
resource semaphore is genuinely a shared place with a count above one.

A single source place holds the initial state. Jobs with no `needs` consume from
it, so `--with-initial-state` needs no special case.

### A job is a stage

`Stage` and `Job` are one frozen dataclass, named `Job`. A `Job` is the
*resolved* unit, produced by binding a document's `JobSpec` to a registered
template. It is never written by hand.

```python
@dataclass(frozen=True)
class Job:
    id: str                                 # the document's job key
    full_name: str                          # from the template, or the id for an inline job
    needs: tuple[str, ...]                  # from the JobSpec
    source: dict[DesignFormat, str]         # from the JobSpec
    condition: str | None                   # from the JobSpec
    requires: tuple[DesignFormat, ...]      # from the template
    provides: tuple[DesignFormat, ...]      # from the template
    metrics: tuple[str, ...]                # from the template
    steps: tuple[type[Step], ...]           # resolved from the template's provider, or inline
    provider: str | None                    # None for an inline job
```

The 27 templates are the same dataclass with `needs`, `source` and `condition`
empty and `steps` unresolved, plus a `default_provider` consulted when `uses`
names a stage without a provider.

In implementation these are two types rather than one, because a library entry
and a bound instance are two things the way a class and an instance are. `Job`
is the registry entry: the 27 templates, the thing `TOOLS` keys on, the thing
`uses` names. `ResolvedJob` is what the engine runs, a `Job` bound to a
document's `needs`, `source` and `condition` with its steps resolved from the
selected provider. This is not the duality the unification removes. That duality
was two *authoring* concepts, `Stage.x` entries and bare steps sharing one list
under different gating rules. A document author writes only jobs, and never
names `ResolvedJob` at all.

`needs` and `requires` are not redundant. `requires` and `provides` cannot order
anything, for the `PNR_IN_PLACE` reason above. `needs` orders, `requires`
validates.

`optional` is deleted along with `multi_provider` and `gating_config_var`. It
meant that a stage could be left unselected and contribute no steps, which was
only ever needed because a flow's `Stages` list had to mention every stage.
A job that should not run is simply absent from the document. Consequently
`Explanation.unselected_stages` and its `--explain` footer are deleted too, and
`test_explain.py::test_an_unselected_stage_is_reported_separately` is removed
rather than migrated, because it pins a concept that no longer exists.

`Stage.using()` already returns an unregistered copy carrying the same id, placed
in a flow's `Stages` list, so a stage in a flow is already a per-flow
instantiation of a global template. Naming that relationship is the whole
unification. The 27 stage constants become job templates in Python, next to the
steps they name, carrying `requires`, `provides`, `metrics` and the registered
provider set. A document supplies `needs`, `uses`, `source` and `if`.

`multi_provider` is deleted. It existed only to model running several providers
of one stage, which is now two jobs.

`gating_config_var` is deleted from the template. Whether CTS runs is a property
of a flow, not of the CTS stage.

### The document is the flow

A flow is a YAML document validated by a pydantic model. There is no
subclassable `Flow` base for declaring flows, and no custom `run()`. After spec
1 no shipped flow overrides `run()`. `flow.py:786` is the abstract method and
`sequential.py:337` is its only implementation, so every flow LibreLane ships is
already pure data wearing a class. Keeping an escape hatch for a custom `run()`
would mean the engine supports two execution models forever, which is the
duality spec 1 spent ten commits removing.

```yaml
# librelane/flows/classic.yaml
name: Classic
description: A general-purpose RTL-to-GDSII flow.

with:
  FP_SIZING: absolute

config:
  - name: RUN_LINTER
    type: bool
    default: true
    description: Whether to run the linter.

jobs:
  lint:
    if: RUN_LINTER
  synthesis:
    needs: [lint]
    uses: synthesis/yosys
  floorplan:
    needs: [synthesis]
  set_power_connections:
    needs: [floorplan]
    steps: [Odb.SetPowerConnections]
  magic_streamout:
    needs: [signoff]
    uses: streamout/magic
    if: RUN_MAGIC_STREAMOUT
  klayout_streamout:
    needs: [signoff]
    uses: streamout/klayout
    if: RUN_KLAYOUT_STREAMOUT
  magic_drc:
    needs: [magic_streamout]
    uses: drc/magic
    if: RUN_MAGIC_DRC
  xor:
    needs: [magic_streamout, klayout_streamout]
    if: RUN_KLAYOUT_XOR
    source: {gds: klayout_streamout}
```

Five keys per job, all declarative, none of them positional.

`needs` declares the incoming edges. There is no rule making an omitted `needs`
mean "after the previous list entry". An implicit-previous rule would make list
order semantic again, which is the thing being removed.

`uses` names what implements the job, as `<stage>/<provider>` or as `<stage>`
for that stage's default provider. The named stage supplies the view and metric
contract. Because the job id is free-form, one stage may appear under several
job names, which is what `streamout` in fact does today.

`steps` names step ids inline, resolved through `Step.factory`, for a job with no
registered template. This is how Classic's thirteen registry-less steps such as
`Odb.SetPowerConnections`, `OpenROAD.CutRows` and `Checker.PowerGridViolations`
are expressed. An inline job takes its `requires`, `provides` and `metrics` from
the union of its steps' own declarations, since it has no template to inherit
them from. A job declares `uses` or `steps`, never both.

`if` names a Boolean configuration variable. This is the whole of gating.

`source` resolves a fan-in conflict, mapping a view to the predecessor it comes
from.

### The programmatic API is the same document

The Python API is the schema itself, not a builder. `.using(...).after(...)`
chaining was rejected because it reads as a sequence of operations against a
hidden global, and the order of calls carries no meaning while visually implying
one.

```python
class JobSpec(BaseModel):
    needs: list[str] = []
    uses: str | None = None
    steps: list[str] | None = None
    source: dict[str, str] = {}
    condition: str | None = Field(default=None, alias="if")

class FlowSpec(BaseModel):
    name: str
    description: str = ""
    values: dict[str, Any] = Field(default_factory=dict, alias="with")
    config: list[VariableSpec] = []
    jobs: dict[str, JobSpec]
```

`VariableSpec` is a pydantic model mirroring the fields of `librelane.config.
Variable`, so a YAML `config` entry validates into a `Variable` with the same
diagnostics a Python declaration gets. This is what replaces the
`Flow.config_vars` class attribute.

`config` declares variables. `with` supplies values for variables anyone
declares, and is covered in the next section. The two are deliberately separate
keys, because a document that both declares `RUN_LINTER` and sets `FP_SIZING`
is doing two unrelated things.

```python
Classic = FlowSpec(
    name="Classic",
    jobs={
        "lint":      JobSpec(condition="RUN_LINTER"),
        "synthesis": JobSpec(needs=["lint"], uses="synthesis/yosys"),
        "xor":       JobSpec(needs=["magic_streamout", "klayout_streamout"],
                             source={"gds": "klayout_streamout"}),
    },
)
```

YAML loading is `FlowSpec.model_validate(yaml.safe_load(text))`. Both surfaces
produce the same model with the same validation and the same errors. The
`if`/`condition` clash with the Python keyword is a pydantic alias, so the YAML
keyword and the Python identifier are one field. pydantic 2.13 is already a
direct dependency backing the configuration system.

`Flow.factory.get("Classic")` returns a `FlowSpec` rather than a class.

### Configuration values

A document's `with` block supplies values for configuration variables. It is one
more layer in the ordering `Config.load` already builds, inserted between the
PDK and the design.

```
PDK -> SCL -> document `with` -> design configuration -> --config-override
```

Most specific wins, and the design always beats the document. A flow that could
override the design would not be reusable across designs. There is no way for a
document to pin a value against the design. A flow that is only correct at a
particular setting states that where the knowledge lives, in the step that
cannot handle the alternative, which already raises on configurations it
rejects.

Mechanically this is one additional `ConfigSource` in the list assembled at
`config.py:591-636`. `layer_mappings` records provenance per key, so the origin
of every value is already reportable without new bookkeeping.

There is no per-job `with`. The reason is that a value's *reach*, meaning the
set of jobs that can read it, is derived rather than declared. `DIE_AREA` sits
in `option_variables`, so `flow_common_variables` places it in every step's
filtered configuration, and `Magic.StreamOut` and the KLayout sealring genuinely
read it. A per-job override on `floorplan` alone would floorplan one die and
stream out another, silently and with no error anywhere.

The case that wants a locally overridden global is a matrix, and a matrix does
not have this problem. A matrix instance is a parallel copy of a whole subgraph,
so floorplan and streamout fall inside the same instance and observe the same
value by construction. Scope becomes structural instead of declared. A
hand-written per-job override is a manual encoding of what a matrix states
structurally, which is the same category of defect as `gating_config_vars`
encoding a graph edge across three Booleans. Per-job values therefore arrive
with loops in spec 3 or not at all, and no reach validation is needed to keep
intent and reach aligned.

### Reach is reportable

`--explain` reports, for each variable in `get_all_config_variables()`, its
value, the layer the value came from, and the jobs that can read it. Reach is
every job for a variable in `flow_common_variables`, and otherwise the jobs
whose steps declare it.

```
DIE_AREA = [0, 0, 550, 550]        Classic document
  universal, read by all 24 jobs
FP_CORE_UTIL = 40                  spm/config.yaml
  reach: floorplan
CTS_SINK_CLUSTERING_SIZE = 16      default
  reach: cts
```

This makes the scope that has always existed visible for the first time. It
needs no new concepts, only the provenance `layer_mappings` already keeps and
the step lists the resolved jobs already hold.

### What survives of `Flow`

`Flow` is deleted as a subclassable base for declaring flows. One concrete
engine class consumes any `FlowSpec` and inherits the machinery that is not
about declaration, specifically `FlowProgressBar`, `get_all_config_variables`,
`start`, `dir_for_step`, `start_step`, `start_step_async`, `_save_snapshot_ef`,
`get_help_md` and the factory. `start_step_async` already exists, so the
concurrency primitive does not need inventing.

## Data flow

### Conditions fire as pass-through

A job whose `if` evaluates false still fires. It consumes its input tokens and
deposits its input state unchanged on each output place, running no steps.

This is not an optimisation. A false condition that suppressed firing would
leave the job's output places empty and block every descendant forever. It is
also exactly today's semantics, in which state flows past a gated step, and it
makes `--skip` the same mechanism rather than a second one.

### The join rule

One rule for views and for metrics. Equal values merge silently. Unequal values
are a conflict requiring `source` to name the producer.

A view or metric inherited from a common ancestor is byte-identical down both
branches and needs no declaration. A key that two branches wrote differently is
genuinely ambiguous. No provenance tagging is needed because path equality
answers the question, a rewritten view having landed in a different job
directory by construction.

The same conflict is caught statically at load, from the stages' declared
`provides` and `metrics`, before the run directory exists. The runtime check
remains as the backstop for whatever a provider declares beyond its stage.

### Run directories

`runs/<tag>/<job-id>/<n>-<step-slug>/`.

The job id is author-chosen, unique within the flow, and unaffected by adding an
edge elsewhere in the graph. Position within a job is well defined because a
job's step list is ordered. The flat global numbering is removed, because under
concurrency there is no global order and printing one would be false. `--explain`
prints the graph instead.

### Resume

`resume_key()` is unchanged, a BLAKE2b over `{schema, step, librelane_version,
config, state_in}`. It already keys on a step's own input state, which is
correct for a DAG without modification. Only the directory changes.

## Command-line surface

`--target <job>`, repeatable. Runs the named job and its transitive ancestors,
nothing else. This is `make` semantics and it is the only way to say "I care
about this output right now" without editing the document. It replaces `--to`,
whose "stop at this step" was an approximation of a target on a list.

`--invalidate <job>`. Treats the named job and its transitive descendants as
having no reusable result. It replaces `--from`, under a name that says what it
does. `--from`'s own help text describes cache invalidation and nothing else. It
is necessary because `resume_key` cannot hash the things that actually go stale,
namely the tool binary, an edited TCL script and the PDK files, so a manual
invalidation is the only recourse when one of those changes.

On the graph both are exact. `--from` on a list over-runs, re-executing steps
that do not depend on the named step at all.

`--skip <job>`, repeatable. A debug escape hatch. The job fires as pass-through,
releasing its token with nothing run. It is retained deliberately as an escape
hatch and not as a modelling mechanism. The declarative way to make a job
optional is to give it an `if`.

`--reproducible <step>` is unchanged in meaning. It runs the ancestors of the
step's job and then emits the reproducible.

`--explain` reports jobs rather than steps, with mechanisms `condition`, `skip`
and `not-in-target`.

```
JOB                RUN  MECHANISM  NEEDS                              REASON
lint               yes             -                                  will run
synthesis          yes             lint                               will run
magic_streamout    yes             signoff                            will run
klayout_streamout  no   condition  signoff                            RUN_KLAYOUT_STREAMOUT is false
xor                no   condition  magic_streamout klayout_streamout  RUN_KLAYOUT_XOR is false
```

The three job-selection options compose in a fixed order. `--target` restricts
the graph to the union of the named jobs' ancestor sets. `--skip` and
`--invalidate` then apply only within that restriction, and naming a job outside
it is an error rather than a silent no-op.

`TOOLS` is re-keyed from stage id to job id, because with two jobs on one stage a
stage-keyed `TOOLS` is ambiguous. It overrides the *provider* half of that job's
`uses` and never the stage half, so `TOOLS: {magic_streamout: klayout}` runs the
`streamout` stage's `klayout` provider under the job named `magic_streamout`.
The job keeps the name the document gave it. This breaks existing configurations
that set `TOOLS`.

`-j` is unchanged. The scheduler fires every enabled transition up to the cap.
Steps within a job remain sequential.

## Error handling

### Load time

Every check below runs before the run directory is created, and each error names
the offending job and the legal alternatives. pydantic supplies the field-level
errors, and the graph checks are a model validator over the assembled document.

- `needs` referencing an undeclared job.
- A cycle in `needs`. Spec 2 is acyclic, and spec 3 lifts this deliberately.
- `uses` naming an unregistered stage or provider.
- `steps` naming an unregistered step id.
- A job declaring both `uses` and `steps`, or neither.
- `if` naming a configuration variable the flow does not declare.
- `source` naming a job that is not a predecessor.
- An undeclared fan-in conflict, where two predecessors on disjoint branches both
  declare a view or metric and `source` names neither. The error names the key
  and both producers.
- An unsatisfiable `requires`, where no ancestor produces a view the job
  consumes. This is `_preflight_views` promoted from a linear scan to graph
  reachability, which is strictly stronger.

### Run time

A step raising fails its job. The engine then stops enabling new transitions,
lets in-flight jobs finish, and raises naming every job that failed. Cancelling
immediately would discard work already completed and hide a second independent
failure, which under concurrency is exactly the information wanted.

A job completing without its declared `provides` or `metrics` raises
`JobContractError`, naming job, view and provider. This is today's
`StageContractError`, checked structurally at the job boundary rather than at a
recovered span.

Two invariants are asserted rather than assumed, because they are what a spec 3
bug will trip first. A place never holds two tokens. The run never reaches a
state with no enabled transition and no token at the sink. Neither can occur on
a validated acyclic graph with pass-through firing, which is precisely why they
are worth asserting.

## Testing

Unit tests against the document and the net, with no tools involved.

- One test per load error above, asserting the message names the job and the
  legal alternatives.
- Firing. A diamond runs both branches. A false `if` deposits its input state
  unchanged. A skipped job does likewise.
- The join rule. Equal values merge. Unequal values raise naming both producers.
  `source` resolves the conflict.
- Ancestor and descendant closure for `--target` and `--invalidate`.

Integration tests as the no-regression pin.

- The Classic document resolves to the same step set as today's `Classic.Steps`,
  in an order consistent with a topological sort of the graph. The same for Chip
  and VHDLClassic.
- Resume. A second run with an unchanged configuration reuses every job. With one
  variable changed, that job and its descendants re-run and nothing else does.

The existing `test/flows/` suite migrates rather than being rewritten.
`test_resume.py`, `test_flow.py`, `test_resume_key.py` and `test_explain.py` all
test behaviour that survives.

## Deletions

- `SequentialFlow` and `StagedFlow`.
- `Flow` as a subclassable base, and `Flow.Steps`, `Flow.Stages`.
- `Stage` as a type distinct from `Job`, and `Stage.gating_config_var`,
  `Stage.multi_provider`, `Stage.using`.
- `Flow.gating_config_vars`, `_explicit_gating_config_vars`,
  `_expand_gating_config_vars`, `__gates_by_step_id`, `_apply_stage_gating`,
  `__prune_deselected_gates`.
- `Boundary`, `_span_for`, `_boundaries`, `_after_step`, `stage_boundaries`,
  `provider_boundaries`, `ResolvedSpan`, `Resolution.spans`.
- `Registration.tagged_steps` and the `_stage_span` / `_stage_provider` subclass
  tags, read in exactly one place outside the registry, at `staged.py:234` and
  `staged.py:622`.
- The `--from`, `--to` options, replaced by `--invalidate` and `--target`.

## Migration

Six registered flows become six documents. Classic and VHDLClassic in
`classic.py`, Chip in `chip.py`, and OpenInKLayout, OpenInOpenROAD and
OpenInMagic in `misc.py`, the last three being single-job documents.

`StageRegistry` becomes `JobRegistry`, keyed by `(job id, provider)`.
`Registration.stage` becomes `Registration.job`.

VHDLClassic currently subclasses Classic for its configuration variables while
declaring its own `Stages` in full. As a document it declares its own `jobs` in
full and its own `config`, with no inheritance mechanism, consistent with the
comment already in `classic.py` that a flow is a self-contained declaration of
what it runs.

Documentation naming `TOOLS` keys as stage ids is rewritten to name them as job
ids.

## Implementation phasing

The design is one spec because the decisions interlock. Designing the document
without the net, or the migration without both, produces a worse design. The
implementation is phased into sequenced plans rather than one plan.

The order is constrained by one dependency that is easy to miss. Deleting
`gating_config_var` requires documents to already exist, because the `if` key is
what carries gating afterwards. Renaming `Stage` to `Job` before the engine
exists would also mean adapting `StagedFlow` to the new name, which phase 5
then deletes. Both problems disappear if the new code lands as pure addition
first and the old mechanism is removed last.

1. `FlowSpec`, `JobSpec`, the YAML loader and every load-time validation.
   A pure addition that nothing consumes yet, testable in isolation.
2. The net and the engine, including firing, pass-through, the join rule and
   contract checking. Also a pure addition, exercised against synthetic
   documents and fake steps while the shipped flows still run on `StagedFlow`.
3. `Stage` becomes `Job`, `StageRegistry` becomes `JobRegistry`, and
   `Registration.stage` becomes `Registration.job`. A rename, consumed by both
   engines at once.
4. The six flows become documents and run on the new engine. Run directory
   layout, resume, and the command-line surface port with them. The `with`
   block becomes a configuration layer and `--explain` gains variable reach,
   both pure additions that no shipped document exercises yet.
5. Deletion of `SequentialFlow`, `StagedFlow`, `Flow` as a base, the span
   apparatus, the gating tables, `multi_provider` and `optional`.

The tree stays green at every phase boundary, and no phase produces work that a
later phase discards.
