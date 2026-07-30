# Flow Mechanism Unification

**Status:** Design approved, ready for planning
**Date:** 2026-07-30
**Scope:** Reducing the number of mechanisms that decide whether a step runs,
fixing the defects their overlap causes, and deleting declarative surface that
is dead or self-contradictory. No new capability.

This is the first of four specs. The others are the Petri net execution engine,
loops and conditionals and resource contention, and the YAML workflow document.
None of them is designed here. This spec exists because the engine would
otherwise become the eighteenth mechanism layered on seventeen.

## Problem

Seventeen distinct mechanisms determine whether a given step executes.
Answering "is step X in this flow's step list" requires consulting six of them.
Answering "will step X actually execute" requires all seventeen, spanning five
source files and two data sources. No API answers the question.
`StagedFlow.describe_stages` (`librelane/flows/staged.py:536`) and
`get_help_md` (`librelane/flows/staged.py:552`) report the class-level default
expansion only, before `TOOLS`, gating, `--skip` or resume have had any say.

The seventeen, grouped by the time band in which they act.

At class-definition time.

1. The `Steps` or `Stages` list (`librelane/flows/flow.py:417`,
   `librelane/flows/staged.py:86`).
2. `Stage.default_provider` and `Stage.optional`, which let a stage appear in a
   flow and contribute nothing (`librelane/stages/stage.py:93`).
3. `Stage.using(provider)`, a per-flow default pin
   (`librelane/stages/stage.py:120`).
4. Provider registration step lists (`librelane/stages/providers.py`), the only
   way a step enters a flow without being named by the flow.
5. `Substitutions` and `Substitute()` (`librelane/flows/sequential.py:114`).
6. `Stage.gating_config_var`, lowered into step-level entries
   (`librelane/flows/staged.py:500`).
7. `gating_config_vars`, the step-level layer with wildcard keys
   (`librelane/flows/sequential.py:115`).
8. `Step.flow_control_variable` (`librelane/steps/step/core.py:325`), which no
   code reads.

At flow-construction time.

9. The `TOOLS` configuration key, read by a pre-pass that bypasses the
   configuration system (`librelane/stages/tools.py:93`).
10. `__prune_deselected_gates` (`librelane/flows/staged.py:474`), the only
    mechanism that deletes a gate rather than a step.
11. `meta.flow` and `meta.substituting_steps` (`librelane/cli/run.py:117`).
12. `_preflight_views` and `_preflight_pdk_vars`
    (`librelane/flows/staged.py:208`, `:243`), which do not select steps but
    refuse to construct the flow based on gate values.

At run time.

13. `--from`, `--to`, `--only`, `--skip`, `--reproducible`
    (`librelane/flows/sequential.py:366`).
14. Resume, keyed on content rather than identity
    (`librelane/flows/resume.py:84`).
15. `initial_state_given`, which changes what `--from` means
    (`librelane/flows/sequential.py:502`).
16. Step-internal self-skip, in roughly twenty-five `run()` bodies, for example
    `librelane/steps/klayout/checks.py:79` and
    `librelane/steps/odb/diodes.py:207`.
17. A custom `Flow.run` override, which bypasses mechanisms 5 through 15
    entirely (`librelane/flows/optimizing.py:44`).

### Defects the overlap causes

Four are live and reproducible.

**`--from` fails on any flow with a false gating variable earlier in the list.**
The decision ladder at `librelane/flows/sequential.py:496-533` tests
`not executing` before it tests `skipped_ids or gated`. A step earlier than the
`--from` target is therefore required to have a reusable result, but a step
gated off in the previous run never reached the execute path and so wrote no
resume entry (`librelane/flows/sequential.py:572`). Setting `RUN_KLAYOUT_XOR`
false and then passing `--from Magic.DRC` raises
`FlowException("Cannot start from ...: step ... has no reusable result")`. The
only escape is supplying an initial state.

**`--reproducible` on a gated step silently produces nothing.** The same ladder
tests `elif cls.id in skipped_ids or gated` at `:528` before
`elif cls.id == reproducible_resolved` at `:531`, so the request is discarded
and the rest of the flow runs instead.

**`--flow` silently discards `meta.substituting_steps`.** `librelane/cli/run.py`
applies substitutions at `:134-144` and then reassigns `target_flow` from
`--flow` at `:146-151`. A user passing both gets the substitutions dropped with
no message. Two further hazards sit in the same block. Substitutions are applied
only when the target is a `SequentialFlow` subclass and are otherwise ignored
silently (`:143`), and `Substitute()` runs `__init_subclass__`, which raises
`TypeError` when a substitution removes a gated step, a type `start_flow` does
not catch (`:199-221`), producing a raw traceback.

**An explicit wildcard gating key silently overwrites a generated stage gate.**
`_apply_stage_gating` merges by exact key (`librelane/flows/staged.py:530`), so
a wildcard explicit key never merges with the exact-id generated entries. It
lands later in the dictionary and, at expansion, overwrites them for every step
it matches, because `_expand_gating_config_vars` assigns rather than merges
(`librelane/flows/sequential.py:211-225`). A flow declaring
`{"OpenROAD.CTS*": ["MY_GATE"]}` loses `RUN_CTS` on `OpenROAD.CTS` entirely.

### Dead and self-contradictory declarative surface

`Stage.config_vars` is empty on all twenty-seven registered stages, so the
registration-time check that every provider accepts a stage's canonical
variables (`librelane/stages/registry.py:184-191`) never checks anything.

`Registration.requires_pdk_vars` has no shipped user. Its only consumer is
`_preflight_pdk_vars` and its only exercise is `test/flows/test_staged.py:1044`.

`Registration` accepts a `stages` tuple of length greater than one and exposes a
`spanning` property (`librelane/stages/registry.py:70`), while
`librelane/stages/resolution.py:145-150` rejects every spanning registration
unconditionally. The registry accepts a shape the resolver refuses. No shipped
registration uses it.

`Step.flow_control_variable` is read by nothing. A third-party step defining it
appears to gate and does not.

`CompositeStep`'s docstring (`librelane/steps/step/composite.py:48-51`) calls
itself "the supported way for a `Registration` to bind one stage to several
steps", which is not what registrations do. Twelve of the twenty-nine
open-source registrations bind several plain steps with no composite involved.
The document it points at, `docs/source/usage/writing_tool_backends.md`, never
mentions composites.

`Step.config_vars` and the nested `class Config` are two spellings of one thing,
converted one into the other at `librelane/steps/step/core.py:320-322`.
Eighty-eight step classes use `Config`. Zero use `config_vars`. The four
remaining occurrences are internal machinery.

Five deprecations date from 2.0 alphas and betas and are three majors stale
against the current 3.0.5. One of them, `Flow.set_max_stage_count`, is still
called in tree at `librelane/flows/optimizing.py:51`.
`SequentialFlow.make` is deprecated in favour of `Make`, yet
`librelane/cli/run.py:133` calls the deprecated spelling, so every list-form
`meta.flow` emits a deprecation warning at the user.

`librelane/flows/sequential.py:413` reads
`_i_want_librelane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks` and,
when set, accepts a mistyped `--from` by fuzzy match rather than raising.

## Goals

Make "will step X run" answerable by one call rather than seventeen lookups.

Fix the four live defects, each with a regression test that fails before the
change.

Delete declarative surface that is dead, unenforced, or contradicted by the code
that consumes it.

Leave the stage taxonomy, provider registrations, `TOOLS`, resume and the view
and metric contracts working exactly as they do now, except where a deletion
listed below removes them.

## Non-goals

**The execution engine.** No Petri net, no jobs, no `needs`, no concurrency, no
state join. Spec 2.

**Loops, conditionals and resource contention.** Spec 3.

**The YAML workflow document.** Spec 4.

**Declaring emitted metrics on `Step`.** Nothing links a declared metric to the
step that emits it. `Stage.power_grid` contracts
`design__power_grid_violation__count` (`librelane/stages/taxonomy.py:107`),
which `OpenROAD.GeneratePDN` emits as a string literal in
`librelane/steps/openroad/floorplan.py:505`, and the `power_grid` registration
contains no checker at all. Closing this means declaring forty-five metric names
plus runtime corner-modified variants, and belongs in its own spec.

**Populating `Stage.config_vars`.** The field is deleted rather than filled in.
Reintroducing it with real content, once the vendor providers have been
exercised against a real PDK, is a later decision.

## Design decisions

**A flow declares its own step list rather than patching another flow's.**
`VHDLClassic` already works this way, and the comment at
`librelane/flows/classic.py:260-267` gives the reasoning, that a filter
expression over another flow's list is a substitution map wearing a different
hat and reintroduces the coupling the list exists to remove. `Chip` is converted
to match, and the mechanism is deleted rather than deprecated.

**Gating merges by union, not assignment.** Gate values are already lists whose
members are ANDed (`librelane/flows/sequential.py:485-492`), so a wildcard key
overlapping a generated stage gate has an obvious correct reading, which is that
both must hold. Assignment semantics were never intentional.

**Gating and skipping are decided before reuse.** A step that will not run
cannot be required to have a reusable result. This is the ordering fix, and it
also makes `--reproducible` reachable for a gated step, where it now raises with
a diagnosis instead of silently doing nothing.

**A contradictory request raises rather than being reinterpreted.** Asking for a
reproducible of a step the configuration gates off names the gate and exits, so
the user can decide. Producing the reproducible anyway would package a step this
configuration would never execute.

**Deletions are outright, not deprecated.** A deprecation window keeps the
replay machinery, the gate coupling and the identifier-renaming hazard in the
code for the whole window, which is most of what this spec exists to remove.

## Architecture

### Deletions

Fourteen items, in dependency order.

**1. `Substitutions`.** Delete `Substitutions`, `Substitute`,
`_applied_substitutions`, `_substitute_in_place` and `__substitute_step` from
`librelane/flows/sequential.py`, the instance-time replay at
`librelane/flows/staged.py:187`, and `substituting_steps` from
`librelane/config/config.py:146` and `librelane/cli/run.py:134-144`.

`Chip` (`librelane/flows/chip.py`) declares an explicit `Stages` list. Its
current map removes `OpenROAD.IOPlacement`, `Odb.CustomIOPlacement`,
`Magic.WriteLEF` and `Odb.CheckDesignAntennaProperties`, inserts
`OpenROAD.PadRing` after `Odb.SetPowerConnections`, and appends six finishing
steps after `Checker.XOR`. The hand-written gate filter at
`librelane/flows/chip.py:56-60` goes away with it, because there is no longer a
removed step whose inherited gate matches nothing.

Three of those four removals are whole stage omissions or plain-step omissions
and translate directly. The fourth does not. `OpenROAD.IOPlacement` and
`Odb.CustomIOPlacement` are two of the four steps in the `openroad` provider of
`Stage.io_placement`, whose other two, `OpenROAD.GlobalPlacementSkipIO` and
`Odb.ApplyDEFTemplate`, `Chip` keeps. `Chip` therefore omits `Stage.io_placement`
and lists those two as plain steps between `Odb.AddRoutingObstructions` and
`Stage.global_placement`. It loses the stage boundary, its contract check and any
future `TOOLS` swap of `Chip`'s IO placement, which is accepted rather than
solved by registering a second `io_placement` provider for one flow.

The ECO workflow is deleted with the mechanism, not migrated.
`Odb.InsertECOBuffers` appears in no flow's step list;
`meta.substituting_steps` is the only way it ever enters one, and
`librelane/examples/hold_eco_demo/config.yaml` exists solely to demonstrate that.
The example and `docs/source/usage/using_ecos.md` are deleted. The ECO steps
themselves stay registered, reachable by a flow class that names them. This is a
capability regression accepted deliberately, on the grounds that a config key
that rewrites another flow's step list is the mechanism this spec exists to
remove, and that spec 4's workflow document is where declaring such a flow from
configuration belongs.

**2. `meta.flow` as a list of step identifiers.** `librelane/cli/run.py:132-133`
and the `list[str]` arm of `librelane/config/config.py:145`. `meta.flow` keeps
its string form, naming a registered flow. `SequentialFlow.Make` is retained,
because the test suite uses it to build flows in five places.

**3. `SequentialFlow.make`,** the deprecated lowercase spelling
(`librelane/flows/sequential.py:253-262`). Its only in-tree caller is deleted by
item 2.

**4. `Optimizing`** (`librelane/flows/optimizing.py`) and its entry in
`librelane/flows/builtins.py:15`.

**5. `SynthesisExploration`** (`librelane/flows/synth_explore.py`) and its entry
in `librelane/flows/builtins.py:19`.

**6. `Stage.config_vars`** and the check at
`librelane/stages/registry.py:184-191`. Provider variable portability continues
to be enforced by the namespace allowlist, which is the half that runs today.

**7. `Registration.requires_pdk_vars`** and
`StagedFlow._preflight_pdk_vars` (`librelane/flows/staged.py:208-241`).

**8. Spanning registrations.** `Registration.stages` becomes a single
`stage: str`; the `spanning` property (`librelane/stages/registry.py:70`) and
the rejection branch in `librelane/stages/resolution.py:145-150` are deleted.
All ninety-nine shipped registrations name one stage, so the migration is
mechanical. The comments at `librelane/steps/fc.py:335` and
`librelane/steps/innovus.py:392` that reference spanning are updated.

**9. `Step.flow_control_variable`.** The deprecation branch at
`librelane/steps/step/core.py:324-327` becomes a `TypeError` naming
`gating_config_vars` as the replacement. It is promoted to an error rather than
removed, because a step that defines the attribute silently fails to gate, and
silence is the defect.

**10. Author-written `Step.config_vars`.** `class Config` becomes the only
spelling an author writes. `config_vars` survives as the derived attribute every
consumer reads, populated from `Config` and no longer assignable by a subclass.
No shipped step is affected.

**11. Stale 2.0 deprecations.** `Flow.init_with_config`
(`librelane/flows/flow.py:607`), `Flow.set_max_stage_count`
(`librelane/flows/flow.py:1070`), `Flow.start_stage`
(`librelane/flows/flow.py:1082`), `Flow.end_stage`
(`librelane/flows/flow.py:1094`) and `Toolbox.aggregate_metrics`
(`librelane/common/toolbox.py:59`). The only in-tree caller,
`librelane/flows/optimizing.py:51`, is deleted by item 4.

**12. 3.0.0-era `DesignFormat` deprecations** at
`librelane/state/design_format.py:72`, `:85` and `:103`. `.name` and `.by_id`
have no callers. `.value` has one, `librelane/steps/klayout/lvs.py:77`, which
becomes `DesignFormat.SPICE.extension` in the same change; deleting the property
without it breaks KLayout LVS.

**13. `--only`.** `librelane/cli/options.py` and the fold-in at
`librelane/cli/runtime.py:130-137`, which sets `frm` and `to` to the same value.
`--from X --to X` expresses it.

**14. The fuzzy-match escape hatch.** The
`_i_want_librelane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks`
branches at `librelane/flows/sequential.py:413-419` and `:441-443`. The
suggestion in the error message stays, so a mistyped `--from` still says what
was probably meant; it just no longer proceeds on the guess.

`Flow.start_step_async` (`librelane/flows/flow.py:876`) is deliberately retained
although items 4 and 5 remove its only callers. It is documented public API at
`librelane/steps/step/core.py:87` and it is the seam spec 2 builds on.

### The gating merge rule

`_apply_stage_gating` (`librelane/flows/staged.py:500-534`) currently writes
generated entries into a dictionary and then overwrites with explicit entries by
exact key. `_expand_gating_config_vars`
(`librelane/flows/sequential.py:189-226`) then assigns per matched step
identifier, so the last key in iteration order wins outright.

Both become unions. Where a step is matched by more than one key, whether
generated or explicit, exact or wildcard, its gate list is the union of the
matched lists, deduplicated and order-preserving. Every variable in the union
must be true for the step to execute, which is the semantics the run loop
already implements for a single key's list.

The docstring at `librelane/flows/sequential.py:196-201`, which documents the
assignment behaviour, is rewritten.

### The run-loop ladder

The ladder in `SequentialFlow.run` (`librelane/flows/sequential.py:496-533`) is
reordered so that the gated and explicitly skipped tests come first. The
resulting precedence, highest first.

1. Gated by a false configuration variable, or named by `--skip`.
2. `--reproducible` names this step. If the step is also gated, raise a
   `FlowException` naming the step and the gating variable. Otherwise create the
   reproducible and stop.
3. Outside the `--from` and `--to` window.
4. Reusable from a prior run.
5. Execute.

This makes a gated step never consult resume, which is what fixes `--from` over
a gated flow, and makes `--reproducible` reachable, which is what turns its
silent no-op into a diagnosis.

The three distinct reasons a step is skipped currently emit the identical
`Skipping step '...'` line (`librelane/flows/sequential.py:496-501`). Each gets
its own message naming the cause, which is the gating variable, the `--skip`
argument, or the flow-control window.

### `Flow.explain`

```python
@dataclass(frozen=True)
class StepDisposition:
    """Why one step will or will not run, for one prospective invocation."""

    step_id: str
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class Explanation:
    """What a prospective invocation of this flow would do."""

    steps: tuple[StepDisposition, ...]
    unselected_stages: tuple[str, ...]
```

`mechanism` is `None` when `will_run` is true, and otherwise names the mechanism
that excluded the step, one of `gate`, `skip` or `window`. Those three are the
only values a step entry can carry, because they are the only mechanisms that
exclude a step which is present in the resolved list. A step dropped by a
`TOOLS` selection is not in the list at all and so has no entry, which is why
provider selection is not among them.

`unselected_stages` carries the second case, stages that contribute no steps
because `TOOLS` left them out or because their default provider is `None`. These
cannot be step entries, having no steps, and are today announced only at debug
level (`librelane/flows/staged.py:584`). It is always empty on a flow that
declares `Steps` directly and so has no stages.

```python
def explain(
    self,
    *,
    frm: str | None = None,
    to: str | None = None,
    skip: Iterable[str] | None = None,
) -> Explanation:
    """
    :returns: One entry per step in this flow's resolved step list, in
        execution order, stating whether the step will run under this
        configuration and these flow-control arguments, and if not, which
        mechanism excluded it, together with the stages that contributed no
        steps at all.
    """
```

It is defined on `SequentialFlow`, which is where the three mechanisms it
reports live. `gating_config_vars` and `_expand_gating_config_vars` are
`SequentialFlow` attributes (`librelane/flows/sequential.py:115`, `:189`), and
`frm`, `to` and `skip` are parameters of `SequentialFlow.run`, not of
`Flow.run`. `Flow` gets no implementation, because a `Flow` subclass writes its
own `run` and there is nothing about it to predict. Once items 4 and 5 land,
every flow in the tree is a `SequentialFlow`, so this covers all of them.
`StagedFlow` overrides it to populate `unselected_stages` from
`Resolution.unselected` (`librelane/stages/resolution.py:104`).

`--explain` therefore requires a `SequentialFlow`. A non-sequential flow gets an
error naming the flow and the requirement, not a partial answer.

Resume is excluded from `explain`, deliberately. A resume verdict depends on
content fingerprints of files that later steps in the same run will rewrite, so
it cannot be predicted before the run without executing it. `explain` reports
what the flow will attempt, not which attempts will be served from cache.

Surfaced on the command line as `--explain`, which prints the table and exits
without running. This gives the single answer the problem statement asks for.

## Consequences for work in flight

The per-step resume work in the `per-step-resume` worktree declares resume for
non-sequential flows a non-goal, justified by `Optimizing` and
`SynthesisExploration` having no fixed step list
(`docs/superpowers/specs/2026-07-29-per-step-resume-design.md:107-112`). Items 4
and 5 delete both flows, after which every flow in the tree is sequential and
that non-goal has no remaining subject. The non-goal becomes true vacuously
rather than false, so nothing that spec builds is invalidated, but its text and
the corresponding passages in its plan
(`docs/superpowers/plans/2026-07-29-per-step-resume.md:1036`, `:1901`) and in
`docs/source/usage/resuming_runs.md:105` need updating. This must be sequenced
with that workstream rather than landed blind.

`Flow.dir_for_step` grew a `position` parameter in that worktree specifically so
that flows building steps in data-dependent loops could omit it
(`librelane/flows/flow.py:816-841`). After these deletions no such flow remains.
Whether the parameter stays optional is that spec's call, not this one's.

## Testing

Every defect gets a regression test that fails before the change.

`test/flows/test_sequential.py`

- `--from` succeeds on a flow with a false gating variable earlier in the step
  list. Fails today with `FlowException`.
- `--reproducible` naming a gated step raises `FlowException` naming the gating
  variable. Today it silently produces nothing and runs the flow.
- The three skip reasons emit distinguishable messages.
- A mistyped `--from` raises and suggests, with the environment variable set,
  which no longer changes the outcome.

`test/flows/test_staged.py`

- An explicit wildcard gating key overlapping a generated stage gate yields the
  union, so the step is gated by both. Today the stage gate is discarded.
- Gate union is order-independent across the generated and explicit sources.

`test/flows/test_explain.py`, new

- Every step of a default `Classic` reports `will_run` true.
- Turning off `RUN_CTS` reports the `cts` stage's steps as excluded by `gate`,
  naming `RUN_CTS`.
- `--skip` and the `--from` and `--to` window each attribute correctly.
- `TOOLS` selecting one provider of a multi-provider stage reports the other
  provider's steps as absent rather than excluded, since they are not in the
  resolved list at all.
- A stage with a `None` default provider is reported as unselected on
  `StagedFlow`.

`test/flows/test_chip.py`

- `Chip`'s explicit `Stages` list expands to exactly the step list the
  `Substitutions` map produced. The golden list is captured before the
  conversion and asserted after, in the manner of
  `test/flows/test_staged_equivalence.py`.

`test/stages/test_providers.py`

- The metric-declaration test is extended to cover vendor registrations, which
  it does not reach today because it iterates
  `librelane.stages.providers._REGISTRATIONS` only. This catches
  `librelane/steps/pegasus.py:161`, which declares a metric its stage already
  contracts.

Existing tests that must be updated rather than preserved.

- `test/flows/test_flow.py:157` references `Optimizing` in a flow-listing
  assertion.
- Any test exercising `Substitute`, `Substitutions` or `substituting_steps`.
- `test/flows/test_staged.py:1044`, the sole exercise of
  `requires_pdk_vars`.

## Documentation

`docs/source/usage/writing_custom_flows.md:308` uses `literalinclude` on
`librelane/flows/optimizing.py` as the worked example for its "Multi-Threading"
section. `literalinclude` on a deleted file fails the documentation build, so
this is a hard blocker on item 4 and lands in the same change.

After the deletions no non-sequential flow remains in tree, so there is nothing
to point the directive at. `start_step_async` is retained public API, however, so
the section is kept and its example is written inline in the page rather than
included from a flow. The inline example is a short two-branch fan-out that
submits two steps, blocks on both futures and picks by metric, which is what
`Optimizing` demonstrated minus the synthesis strategy sweep that made it a
shipped flow. Documenting the method with an example that lives in the page also
removes the coupling that caused this breakage, so no future flow deletion can
break the build again.

The section states that flows composed of concurrent jobs are the subject of the
workflow engine, and links forward once spec 2 lands.

`docs/source/additional_material/caravel/macro_first_hardening/index.md:108`
shows a `--flow SynthesisExploration` invocation in a tutorial transcript and
needs revising.

`docs/source/usage/resuming_runs.md:105` names both deleted flows.

`Changelog.md` records every deletion with its migration. For `Substitutions`
the migration is to declare an explicit `Stages` list, as `VHDLClassic` and
`Chip` do. For `meta.flow` as a list it is to name a registered flow. For
`--only` it is `--from X --to X`.

The `CompositeStep` docstring
(`librelane/steps/step/composite.py:48-51`) is corrected. The distinction worth
stating is that a composite hides its constituent steps behind one identifier,
one configuration model, one directory and one resume unit, whereas a
registration keeps them individually addressable, which is precisely what allows
a stage gate to be lowered onto each of them
(`librelane/flows/staged.py:521-527`).
