# Migrate Flows To Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the eight shipped flows into YAML documents running on the workflow engine, replace `--from`/`--to` with `--invalidate`/`--target`, carry `TOOLS`, `--reproducible` and the run's final artefacts across to the new engine, and let a document supply configuration values through a `with` block whose reach `--explain` reports.

**Architecture:** Each flow becomes a YAML document beside the code. The migration is done in two movements. First a faithful translation that preserves today's exact step order as a linear chain, pinned by a test comparing against `Classic.Steps`. Then a small, separately reviewable set of edge relaxations that introduce the real parallelism. Splitting them means a regression in the translation cannot hide behind a regression in the parallelisation.

**Tech Stack:** Python 3.11+, YAML documents loaded through `load_flow_spec`, Typer for the command line, pytest, uv.

**Scale:** 14 tasks. Every factual claim below about a step id, a stage id, a provider, a view or a gating variable was produced by running code against this checkout. The commands that produced them are quoted in the tasks that depend on them, so a reviewer can re-run any of them.

## Global Constraints

- This is phase 4 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phases 1, 2 and 3 having landed, so the registry is `librelane.jobs.JobRegistry`, the template type is `Job`, and the engine's resolved type is `ResolvedJob`.
- **Every code block in this plan is written in post-phase-3 names**, and so is every prose reference to a class, an attribute or a registration key. Phase 3's rename table is the authority; the entries that appear here are `Stage` to `Job`, `Stage.factory` to `Job.factory`, `StageRegistry` to `JobRegistry`, `StageResolutionError` to `JobResolutionError`, `StageError` to `JobDefinitionError`, and the `"stage":` key of every `REGISTRATIONS` entry to `"job":`. Note that `Flow.Stages` keeps its name through this phase, because `\bStage\b` does not match `Stages`; phase 5 deletes it.
- **Paths** are the one exception, and they are covered by a blanket rule rather than rewritten. A path under `librelane/stages/` in this plan reads `librelane/jobs/` by the time this phase runs, and a path under `test/stages/` reads `test/jobs/`, per phase 3's `git mv`. `librelane/stages/stage.py` in particular reads `librelane/jobs/job.py`.
- Every `console` block in this plan, wherever it appears, is a transcript of a command run against this checkout **before any phase landed**, so it is in the pre-phase-3 names on purpose and its output is the value measured then. Re-running one during phase 4 means applying the two rules above to it first. Every `bash` block inside a task, by contrast, is a step to execute during phase 4, and those are already in post-phase-3 names.
- The full test suite must stay green at every commit, and no commit may leave a command-line option silently accepted and ignored.
- Never add a fallback. A `--target`, `--invalidate` or `--reproducible` naming an unknown job is an error listing the document's jobs, never a no-op.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Documents are `librelane/flows/*.yaml`, shipped as package data. No `pyproject.toml` change is needed, and Task 2 Step 6 verifies that rather than assuming it.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

**The unmerged dependency, and it lands whole.** This plan is written against branch `worktree-agent-a2dad013ce988e29b`, not against `librelane-unstable` as it stands. That branch is complete and verified end to end under `nix develop` with sky130, suite green at 801 passed, and it lands as one unit. **Every count, line number and step list in this plan is the post-branch value.** Anyone re-measuring against `librelane-unstable` will get different numbers, and the difference is the branch, not an error.

Measured with `git log --oneline librelane-unstable..worktree-agent-a2dad013ce988e29b`, it carries five commits. Four of them change something this plan transcribes.

| Commit | What it changes | Where this plan accounts for it |
| --- | --- | --- |
| `9e2edc4` fix: stop contracting a view no OpenSTA script writes | The SDC contract fix, tabulated below. | The `ir_drop` bullet in Task 3's "What is deliberately not relaxed". |
| `457c060` feat: buffer the ports before global placement (#917) | Inserts the bare step `OpenROAD.AddBuffer` into `Classic.Stages` and `VHDLClassic.Stages`, between `Job.io_placement` and `Job.global_placement`, ungated. `Chip.Stages` is untouched, because `Chip` declares its own list. | Classic is 81 steps and VHDLClassic 73, both stated below. `classic.yaml` and `vhdl_classic.yaml` each carry an `add_buffer` job. The bare-step count below is 22, not 21. |
| `6870f74` feat: launch OpenROAD and OpenSTA interactively (#532) | Adds `OpenInOpenROADConsole` and `OpenInOpenSTAConsole` to `librelane/flows/misc.py`, one step each. `OpenInMagic` moves from `misc.py:57` to `misc.py:94`. | Eight shipped flows in the table below, eight documents, and Task 4 writes seven of them. |
| `741ac67` feat: add an ECO step that replaces cells (#967) | Registers `Odb.ReplaceECOCells`. | Nothing. It belongs to no flow, so no document names it. |
| `c15b74c` feat: report every corner in mid-PnR STA (#636) | Changes what `OpenROAD.STAMidPNR` reports. Its `outputs` stay `[]` and it adds no step id. | Nothing directly, but it reinforces Task 3's reason for keeping the four `sta_mid_pnr_*` jobs on the chain, which already rests on those four producing the same metric names with different values. |

The SDC contract fix, `9e2edc4`, deserves its own table because five of this plan's arguments read one of these values. `MultiCornerSTA.outputs` declared an SDC that nothing in the class writes, and the stage contract derived from that declaration failed at run time; `Step.start` validates declared inputs only, at `librelane/steps/step/core.py:656-661`, and never checks outputs, so the false claim had nowhere else to surface.

| Name | On `librelane-unstable` | On the fix branch |
| --- | --- | --- |
| `MultiCornerSTA.outputs` | `[SDF, SDC]` | `[SDF]` |
| `OpenROAD.STAPrePNR.outputs` | `['sdf', 'sdc']` | `['sdf']` |
| `OpenROAD.STAPostPNR.outputs` | `['sdf', 'sdc', 'lib']` | `['sdf', 'lib']` |
| `PrimeTime.STAPrePNR.outputs` | `[SDC]` | `[]` |
| `OpenROAD.DumpRCValues.outputs` | inherited, `['odb', 'def', 'sdc', 'nl', 'pnl']` | `[]` |
| `Stage.pre_pnr_sta.provides` | `(sdc,)` | `_NO_VIEWS` |
| `Stage.floorplan.requires` | `(nl, sdc)` | `(nl,)` |
| `FC.Floorplan`, `ICC2.Floorplan`, `Innovus.Floorplan` `inputs` | `[NETLIST, SDC]` | `[NETLIST]` |

The general lesson is worth carrying. A declared `outputs` list had never been checked against what the code writes, so every claim in this plan that reads an `outputs` list stood on the same ground. The branch adds general-form tests in `test/steps/test_declared_outputs.py` that close it; re-run them before trusting any `outputs`-derived claim here that a later change touches.

**Line numbers this plan cites in the two files the branch edits.** `457c060` inserts three lines into `librelane/flows/classic.py` at 57-59, so every landmark below them shifts by three, and `6870f74` inserts 37 lines into `librelane/flows/misc.py` at 56. The values on the right are the post-branch ones, read from `git show worktree-agent-a2dad013ce988e29b:<path>`, and are what this plan uses throughout.

| Landmark | On `librelane-unstable` | Used here |
| --- | --- | --- |
| `Classic.Stages` | `classic.py:42-97` | `classic.py:42-100` |
| `Job.post_route_opt` in `Classic.Stages` | `classic.py:78` | `classic.py:81` |
| `Classic.Config` | `classic.py:99-219` | `classic.py:102-222` |
| `VHDLClassic.Stages` | `classic.py:268-316` | `classic.py:271-320` |
| The `#:` note above `VHDLClassic.Stages` | `classic.py:260-267` | `classic.py:263-270` |
| `OpenInMagic` | `misc.py:57` | `misc.py:94` |

`librelane/flows/classic.py:22-29`, the `librelane.steps` import, is unchanged, and so is every `librelane/flows/chip.py`, `librelane/flows/misc.py:22`, `misc.py:39` and `librelane/stages/providers.py` line number this plan cites. The branch does not touch `chip.py` or `providers.py` at all, which was checked with `git diff --stat` rather than assumed.

## The eight flows

Each row cites the flow's `Stages` or `Steps` line, not its `class` line.

| Flow | Source today | Document |
| --- | --- | --- |
| Classic | `librelane/flows/classic.py:42` | `librelane/flows/classic.yaml` |
| VHDLClassic | `librelane/flows/classic.py:271` | `librelane/flows/vhdl_classic.yaml` |
| Chip | `librelane/flows/chip.py:52` | `librelane/flows/chip.yaml` |
| OpenInKLayout | `librelane/flows/misc.py:22` | `librelane/flows/open_in_klayout.yaml` |
| OpenInOpenROAD | `librelane/flows/misc.py:39` | `librelane/flows/open_in_openroad.yaml` |
| OpenInOpenROADConsole | `librelane/flows/misc.py:57` | `librelane/flows/open_in_openroad_console.yaml` |
| OpenInOpenSTAConsole | `librelane/flows/misc.py:75` | `librelane/flows/open_in_opensta_console.yaml` |
| OpenInMagic | `librelane/flows/misc.py:94` | `librelane/flows/open_in_magic.yaml` |

The last three rows are the post-`6870f74` positions. `OpenInOpenROADConsole` runs `OpenROAD.OpenConsole` and `OpenInOpenSTAConsole` runs `OpenROAD.OpenSTAConsole`, one step each, both confirmed present in `test/steps/registry_snapshot.json` on the branch.

## Measured facts the translation rests on

Every statement in this section was produced by running the command beside it. Re-run any that a task depends on before trusting it.

**The registered stages.** 27 stages, of which exactly one has no default provider.

```console
$ uv run python -c "
import librelane.steps
from librelane.stages.stage import Stage
from librelane.stages.registry import StageRegistry
for sid in sorted(Stage.factory.list()):
    st = Stage.factory.get(sid)
    print(sid, st.default_provider, st.optional, st.multi_provider,
          st.gating_config_var, StageRegistry.providers(sid))
"
```

`post_route_opt` is the only stage with `default_provider=None`, `optional=True` and an empty provider list. `drc` and `streamout` are the only `multi_provider` stages, both defaulting to `('magic', 'klayout')`. `synthesis` is the only stage with two providers, `['yosys', 'yosys_vhdl']`.

**Classic's step list.** 81 entries, and VHDLClassic's 73. Both counts include the `OpenROAD.AddBuffer` that `457c060` inserts, and both were read from the pinned files on the branch, `test/flows/classic_steps.json` and `test/flows/vhdl_classic_steps.json`. `AddBuffer` sits at index 27 of Classic's list and index 21 of VHDLClassic's, in both cases immediately after `Odb.ApplyDEFTemplate`, which is `io_placement`'s last step, and immediately before `OpenROAD.GlobalPlacement`. It is ungated: it appears in neither pinned gating table, which stay at 35 and 30 entries.

```console
$ uv run python -c "
import librelane.steps
from librelane.flows import Flow
C = Flow.factory.get('Classic')
for i, s in enumerate(C.Steps):
    print(i, s.id, s.get_implementation_id())
"
```

`SequentialFlow._normalize_step_ids` (`librelane/flows/sequential.py:198`) subclasses repeated steps and renames them, so `Classic.Steps` contains `OpenROAD.STAMidPNR`, `OpenROAD.STAMidPNR-1`, `-2` and `-3`, and `OpenROAD.CheckAntennas` alongside `OpenROAD.CheckAntennas-1`. Steps resolved from a document carry plain registry ids. **Every step comparison in this plan is therefore on `get_implementation_id()`, never on `id`.** That method is pinned at `test/stages/test_registry.py:179`.

**Classic contains no `post_route_opt` step.** `Job.post_route_opt` sits in `Classic.Stages` at `classic.py:81` and contributes nothing, which `test/stages/test_resolution.py:38` pins. A bare `uses: post_route_opt` is also a load error under phase 1's `_check_uses`, which rejects a stage with no default provider. The job is therefore absent from every document in this plan, and `fill_insertion` needs `routing_reports` directly.

**Gating.**

```console
$ uv run python -c "
import librelane.steps
from librelane.flows import Flow
C = Flow.factory.get('Classic')
print(C._expand_gating_config_vars(C.gating_config_vars, [c.id for c in C.Steps]))
"
```

Three results shape the documents.

- `OpenROAD.STAPostPNR` is gated by `RUN_MCSTA`, which is `signoff_sta`'s taxonomy gate. `signoff_sta` therefore carries `if: RUN_MCSTA`.
- `Odb.HeuristicDiodeInsertion` expands to `['RUN_ANTENNA_REPAIR', 'RUN_HEURISTIC_DIODE_INSERTION']` while the other two steps of the same registration expand to `['RUN_ANTENNA_REPAIR']` alone. Task 3 splits that job.
- `KLayout.Render` does not appear at all, while `KLayout.StreamOut`, which sits in the same registration, is gated by `RUN_KLAYOUT_STREAMOUT`. Task 1 takes `KLayout.Render` out of that registration.

`OpenROAD.CheckAntennas` appears twice in `Classic.Steps`, ungated inside `global_routing` and gated by `RUN_DRT` inside `detailed_routing`. A flat set of step ids cannot represent that, so the gating tests in this plan compare `(job id, implementation id)` pairs.

**Views.**

```console
$ uv run python -c "
import librelane.steps
from librelane.steps import Step
for sid in ['Magic.StreamOut', 'KLayout.StreamOut', 'Magic.WriteLEF',
            'Magic.DRC', 'KLayout.DRC', 'Magic.SpiceExtraction',
            'Odb.CheckDesignAntennaProperties', 'KLayout.XOR', 'Yosys.EQY']:
    c = Step.factory.get(sid)
    print(sid, [(v.id, v.optional) for v in c.inputs], [v.id for v in c.outputs])
"
```

| Step | Inputs | Outputs |
| --- | --- | --- |
| `Magic.StreamOut` | `def` | `gds`, `mag_gds`, `mag` |
| `KLayout.StreamOut` | `def` | `gds`, `klayout_gds` |
| `Magic.WriteLEF` | `gds`, `def` | `lef` |
| `Magic.DRC` | `def` (optional), `gds` | none |
| `KLayout.DRC` | `gds` | none |
| `Magic.SpiceExtraction` | `gds`, `def` | `spice` |
| `Odb.CheckDesignAntennaProperties` | `odb`, `lef` | none |
| `KLayout.XOR` | `mag_gds`, `klayout_gds` | none |
| `Yosys.EQY` | `nl` | none |

**Who reads whose `gds` today.** This is the single most consequential measurement in the plan, and it is not what the step names suggest.

```console
$ uv run python -c "
import librelane.steps
from librelane.flows import Flow
for name in ['Classic', 'VHDLClassic', 'Chip']:
    last = {}
    for i, s in enumerate(Flow.factory.get(name).Steps):
        for v in s.inputs:
            print(name, i, s.id, v.id, '<-', last.get(v.id, '<initial>'))
        for v in s.outputs:
            last[v.id] = f'{i}:{s.id}'
"
```

`SequentialFlow` threads one state linearly, so the last writer of a view wins. In Classic, `Magic.StreamOut` is at position 59 and `KLayout.StreamOut` at 60, so **every later `gds` consumer reads KLayout's GDSII, including `Magic.WriteLEF` at 62, `Magic.DRC` at 66 and `Magic.SpiceExtraction` at 70.** In Chip, `KLayout.SealRing` and `KLayout.Filler` rewrite `gds` after the streamouts, so `Magic.DRC`, `KLayout.DRC` and `Magic.SpiceExtraction` all read the filled GDSII.

Two further measurements from the same command contradict claims that earlier drafts of this plan made.

- `Yosys.EQY` reads `nl` from `OpenROAD.FillInsertion`, not from `Yosys.Synthesis`. It compares the RTL against the **post-place-and-route** netlist. Re-pointing `formal_equivalence` at `synthesis` would change what it checks, so this plan does not do it.
- `Odb.CheckDesignAntennaProperties` reads `lef` from `Magic.WriteLEF`, so `check_antenna_properties` needs `write_lef` and not a streamout.

**Metrics `Misc.ReportManufacturability` reads.** `librelane/steps/misc.py:56-140` reads `design__lvs_error__count`, `klayout__drc_error__count`, `magic__drc_error__count` and the antenna metrics out of `state_in.metrics`, warning "may have been skipped" for each one it does not find. `final_checks` therefore has to join every job that produces those metrics, or the report degrades into a wall of warnings with nothing to say.

## Two facts about Classic that shape the translation

`OpenROAD.STAMidPNR` appears **four times** in `Classic.Stages`. Job ids are unique within a document, so the four occurrences become four jobs, `sta_mid_pnr_1` through `sta_mid_pnr_4`. This is not a workaround. They are four distinct runs at four points in the flow, and giving them distinct names makes their four run directories distinguishable, which the positional numbering did only by accident.

Twenty-two distinct step classes are bare entries belonging to no registered stage: `Odb.SetPowerConnections`, `OpenROAD.CutRows`, `Odb.AddRoutingObstructions`, `OpenROAD.AddBuffer`, `Odb.WriteVerilogHeader`, `Checker.PowerGridViolations`, `OpenROAD.STAMidPNR`, `Odb.ManualGlobalPlacement`, `Odb.ReportDisconnectedPins`, `Checker.DisconnectedPins`, `Odb.ReportWireLength`, `Checker.WireLength`, `Odb.CellFrequencyTables`, `Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties`, `KLayout.XOR`, `Checker.XOR`, `Checker.SetupViolations`, `Checker.HoldViolations`, `Checker.MaxSlewViolations`, `Checker.MaxCapViolations` and `Misc.ReportManufacturability`. Each becomes a job with inline `steps`. Adjacent bare steps that always run together are one job, not several, because a job is the unit of the graph and splitting them adds edges that say nothing.

## The join rule this plan depends on

`source` names the producer a view or metric comes from when a fan-in is ambiguous. This plan needs one point of the rule stated precisely, because the shipped documents cannot be written without it.

**`source` is consulted only for a key whose contributing predecessors do not all carry the same value.** A key that only one predecessor carries is unambiguous, and the join takes it without consulting `source`.

That is what makes the documents in this plan equivalent to today's flows under **every** combination of `RUN_MAGIC_STREAMOUT` and `RUN_KLAYOUT_STREAMOUT`, not only the default one. A gated-off producer fires as pass-through and carries no `gds`, so `magic_drc`'s `source: {gds: klayout_streamout}` contributes nothing and the join takes Magic's GDSII, which is exactly what the linear flow's last-writer rule does when KLayout's streamout is switched off.

| `RUN_MAGIC_STREAMOUT` | `RUN_KLAYOUT_STREAMOUT` | `Magic.DRC` reads today | `magic_drc` reads under the document |
| --- | --- | --- | --- |
| true | true | KLayout's `gds` | KLayout's `gds`, named by `source` |
| true | false | Magic's `gds` | Magic's `gds`, the only contributor |
| false | true | KLayout's `gds` | KLayout's `gds`, the only contributor |
| false | false | fails, no `gds` | fails, no `gds` |

The alternative reading, in which a `source` naming a producer that carried no such key raises, would turn row two into a run-time failure and force every `gds` consumer to repeat `RUN_KLAYOUT_STREAMOUT` in its `if`. That would change the gating surface of three shipped flows for no gain. **Phase 2's `join_states` must implement the rule as stated here**, and the controller has been told so.

## The Magic DRC decision, recorded on purpose

> **RETRACTED 2026-08-01, during task 3.** Everything below the line was written on a
> false premise and the instruction it gives would silently change results. It is kept
> rather than deleted because tasks 2 and 3 were dispatched against it and the reader
> needs to know what they were answering. **Do not act on it.**
>
> The premise was that `Magic.DRC` reads KLayout's GDSII. It does not, on any open PDK.
> Both stream-out steps write the neutral `gds` only when
> `PRIMARY_GDSII_STREAMOUT_TOOL` names them **or** nothing has written one yet
> (`librelane/steps/magic.py:368-370`, `librelane/steps/klayout/views.py:236-238`).
> `librelane/config/pdk_compat.py:340-342` defaults that variable to `"magic"` for
> `sky130*` and `gf180mcu*`, and `librelane/config/flow.py:58` declares it `pdk=True`
> with no fallback default. So Magic writes `gds`, KLayout **declines to clobber it**,
> and every later consumer reads **Magic's** GDSII. `test/steps/test_klayout.py:90`
> already pinned this: "Magic is primary and already wrote it; KLayout must not clobber
> it." There is no emergent bug here to make explicit, and
> `source: {gds: klayout_streamout}` would have *introduced* one on every sky130 run.
>
> The deeper reason the instruction cannot be salvaged: once the two stream-outs run
> concurrently, each sees `state_in` with no `gds`, so both write it unconditionally and
> the join must choose **statically**. `source` maps a view to a **job name**, so no
> static entry can express "whichever job `PRIMARY_GDSII_STREAMOUT_TOOL` names".
> Parallel stream-outs are not behaviour-preserving under the current mechanism for any
> static choice. Letting `source` name a configuration variable is spec 3's problem.
>
> **What task 3 landed instead**, and what tasks 4 and 7 must follow: keep the single
> edge `klayout_streamout: needs: [magic_streamout]`, relax everything else, carry no
> `source` anywhere. That preserves semantics for both settings of the variable — with
> `PRIMARY=magic` Magic writes and KLayout declines; with `PRIMARY=klayout` Magic writes
> because nothing has, then KLayout overwrites — and still yields six concurrent
> branches, which is where the wall-clock win actually is. See
> `librelane/flows/classic.yaml` and its comment on `klayout_streamout`.

---

`Magic.DRC` reads KLayout's GDSII today. That is almost certainly not what anybody intended when they named the step, and it is invisible in `classic.py` because it is an emergent property of list position.

This plan **preserves** it, which is also the spec's position. `magic_drc` gets `source: {gds: klayout_streamout}`, the equivalence tests pass unchanged, and the oddity stops being emergent and becomes one reviewable line of YAML that a reader can object to.

Pointing `magic_drc` at `magic_streamout` is very likely the correct long-term behaviour, and it belongs in its own change with its own justification and its own regression run. A migration whose entire claim is equivalence is the wrong place to land a silent change in which layout gets design-rule checked. A wrong result finally written down in one reviewable line is better than a migration that changes results while claiming it changed none. The win available here is making the bug explicit, and this plan takes it.

The same reasoning covers `write_lef` and `lvs`, which read KLayout's GDSII today for the same positional reason, and Chip's `magic_drc`, `klayout_drc` and `lvs`, which read the sealed and filled GDSII that `chip_finishing` produces.

## No shipped document uses `with`

Neither the document-level `with` nor the job-level one appears in any of the eight documents. The flows set no configuration values today, so a document that set one would be adding behaviour under cover of a migration. Task 12 builds the layering and Task 13 makes its reach reportable, both exercised by synthetic documents in the tests and by none of the shipped ones.

That is worth stating because the job-level rule has changed once already. It now requires that every job reading a variable also sets it, rather than that the variable have reach one. Nothing here depends on either form, so the change costs this plan nothing, and a later change that wants two synthesis jobs with different `SYNTH_STRATEGY` has a clean place to add it.

---

### Task 1: Take `KLayout.Render` out of the `streamout` contract

**Files:**
- Modify: `librelane/stages/providers.py` (the `streamout` / `klayout` registration, around line 330)
- Modify: `librelane/flows/classic.py`, `librelane/flows/chip.py`
- Test: `test/stages/test_resolution.py`, `test/flows/test_staged_equivalence.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a `streamout` / `klayout` registration whose steps are `[KLayout.StreamOut]` alone, and a bare `KLayout.Render` entry in `Classic.Stages`, `VHDLClassic.Stages` and `Chip.Stages`.

**Why this comes first:**

`KLayout.Render` is registered as part of the `streamout` stage's `klayout` provider, and it is ungated, while `KLayout.StreamOut` in the same registration is gated by `RUN_KLAYOUT_STREAMOUT`. A document expresses gating as a job-level `if`, so `uses: streamout/klayout` with `if: RUN_KLAYOUT_STREAMOUT` would gate `KLayout.Render` as well. That is both a set mismatch in Task 2's gating test and an unacknowledged change of behaviour.

`KLayout.Render` does not belong to `streamout`. It consumes `def` and produces nothing, so it satisfies no part of the stage's `gds` contract and carries no view across the stage boundary. It was grouped there because the old model had nowhere else to put a KLayout step. Moving it out is the root-cause fix and leaves both engines running the identical step list, which Step 4 proves.

The alternative, splitting `klayout_streamout` into two inline `steps:` jobs, would destroy the `streamout` stage boundary and with it the ability to swap that job's tool from `TOOLS`. That is a real loss for a step that was never part of the stage.

- [ ] **Step 1: Record the step lists before touching anything**

```bash
cd /home/kelvin/librelane
uv run python -c "
import json, librelane.steps
from librelane.flows import Flow
print(json.dumps({
    name: [s.id for s in Flow.factory.get(name).Steps]
    for name in ['Classic', 'VHDLClassic', 'Chip']
}, indent=2))
" > /tmp/steps-before.json
```

- [ ] **Step 2: Remove `KLayout.Render` from the registration**

In `librelane/stages/providers.py`, the `streamout` / `klayout` entry becomes:

```python
    {
        "job": "streamout",
        "provider": "klayout",
        "steps": [KLayout.StreamOut],
        "namespaces": ("KLAYOUT_",),
        "provides": [DesignFormat.klayout_gds],
    },
```

- [ ] **Step 3: Add it back as a bare step in all three flows**

In `librelane/flows/classic.py`, in both `Classic.Stages` and `VHDLClassic.Stages`, and in `librelane/flows/chip.py` in `Chip.Stages`, insert `KLayout.Render` directly after `Job.streamout`:

```python
        Job.streamout,
        # Not part of the streamout stage: it consumes only 'def', produces
        # nothing, and satisfies no part of the stage's 'gds' contract. It is
        # also ungated where KLayout.StreamOut is gated, which a job-level 'if'
        # cannot express while the two share a registration.
        KLayout.Render,
```

`Classic` and `Chip` already import `KLayout`. `librelane/flows/classic.py:22-29` imports `OpenROAD, Magic, KLayout, Odb, Checker, Misc`, so no import change is needed.

- [ ] **Step 4: Prove the step lists are unchanged**

```bash
cd /home/kelvin/librelane
uv run python -c "
import json, librelane.steps
from librelane.flows import Flow
after = {
    name: [s.id for s in Flow.factory.get(name).Steps]
    for name in ['Classic', 'VHDLClassic', 'Chip']
}
before = json.load(open('/tmp/steps-before.json'))
assert after == before, [
    (n, [x for x in zip(before[n], after[n]) if x[0] != x[1]])
    for n in after if after[n] != before[n]
]
print('identical')
"
```

Expected: `identical`. Anything else means the insertion point is wrong.

- [ ] **Step 5: Update the two resolution tests that name the registration's steps**

`test/stages/test_resolution.py:106` and `test/stages/test_resolution.py:176` both assert that resolving `streamout` with the providers listed as `["klayout", "magic"]` yields `["KLayout.StreamOut", "KLayout.Render", "Magic.StreamOut"]`. Drop `"KLayout.Render"` from both lists, leaving `["KLayout.StreamOut", "Magic.StreamOut"]`.

`test/flows/test_chip.py:83` lists `KLayout.Render` at the same position in Chip's step list and does not change, which Step 4 already proved.

- [ ] **Step 6: Run the suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed. `test/flows/test_staged_equivalence.py` compares against the pinned `test/flows/classic_steps.json`, `test/flows/classic_gating.json` and `test/flows/vhdl_classic_steps.json`. None of the three changes, because the step ids, the implementation ids, the gating table and the configuration variable names are all unaffected. A failure there means Step 3 put the step in the wrong place.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/stages/providers.py librelane/flows/classic.py librelane/flows/chip.py test/stages/test_resolution.py
git commit -m "refactor: KLayout.Render is not part of the streamout stage"
```

---

### Task 2: The Classic document, translated faithfully

**Files:**
- Create: `librelane/flows/classic.yaml`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Consumes: `load_flow_spec` (phase 1), `resolve_jobs` (phase 2), `KLayout.Render` as a bare step (Task 1).
- Produces: a document whose resolved implementation-id sequence equals `Classic.Steps`'s, and `_implementation_ids`, `_jobs_of_each_step` and `_gated_pairs` helpers in `test/flows/test_documents.py` that Task 4 reuses.

**Design notes the implementer needs:**

This task translates, it does not improve. Every job needs exactly the job before it, reproducing today's linear order. The parallelism arrives in Task 3, where each relaxed edge is individually visible in the diff. A translation error and a parallelisation error look identical in a step-order test, so they must not land together.

The gating tables move here as `if` keys. `Job.lint`'s `RUN_LINTER`, `Job.cts`'s `RUN_CTS` and the other taxonomy gates become `if` on the job. `Classic.gating_config_vars` entries become `if` on the corresponding job, and the three-variable `KLayout.XOR` and `Checker.XOR` entries stay a three-variable conjunction, because `KLayout.XOR` genuinely consumes `mag_gds` from one producer and `klayout_gds` from the other and cannot run unless both fired.

`streamout` is `multi_provider` with default `('magic', 'klayout')`. Today one `Job.streamout` entry runs both providers and two booleans switch them independently. That becomes two jobs, `magic_streamout` and `klayout_streamout`, each with its own `uses` and its own `if`. Likewise `drc`.

`antenna_repair` becomes three inline jobs rather than one `uses` job, for the reason given in Task 3's notes. The split lands here, in the faithful translation, because it changes no step and no gate.

The document declares all 22 of `Classic.config_vars`'s variables, including `RUN_LINTER` and `RUN_EQY`. `Flow.config_vars` for Classic has 23 entries, the twenty-two plus `TOOLS`, which Task 7 declares on the engine rather than in any document.

- [ ] **Step 1: Write the failing test**

Create `test/flows/test_documents.py`:

```python
# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The no-regression pin for the migration. Each document must resolve to the same
steps, under the same gates, as the Python flow it replaces.
"""

from importlib.resources import files

import pytest

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import load_flow_spec

pytestmark = pytest.mark.all


def _document(name: str):
    return load_flow_spec(str(files("librelane.flows").joinpath(name)))


def _jobs_of_each_step(name: str) -> list[tuple[str, str]]:
    """
    Returns
    -------
    list[tuple[str, str]]
        One ``(job id, implementation id)`` pair per resolved step, in the
        order the document declares its jobs.

    Declaration order is not semantic to the engine, which runs the graph. It
    is used here only to line the document up against the flat list the Python
    flow declares, so that a step appearing in several jobs, as
    ``OpenROAD.STAMidPNR`` does four times, is still attributable to one job.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return [
        (job_id, step.get_implementation_id())
        for job_id in spec.jobs
        for step in jobs[job_id].steps
    ]


def _implementation_ids(name: str) -> list[str]:
    return [implementation for _, implementation in _jobs_of_each_step(name)]


def _gated_pairs(name: str) -> set[tuple[str, str]]:
    """
    Every ``(job id, implementation id)`` the document gates behind an ``if``.

    ``ResolvedJob.conditions`` is a ``tuple[str, ...]``, the ``if`` conjunction
    already split into variable names, so an ungated job carries the empty
    tuple rather than ``None``. Test emptiness, not ``is not None``.
    """
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return {
        (job_id, step.get_implementation_id())
        for job_id, job in jobs.items()
        if job.conditions
        for step in job.steps
    }


def _flow_gated_pairs(name: str, flow) -> set[tuple[str, str]]:
    """
    The same set, derived from the Python flow, by pairing its flat step list
    with the document's jobs position by position.
    """
    pairs = _jobs_of_each_step(name)
    assert [implementation for _, implementation in pairs] == [
        step.get_implementation_id() for step in flow.Steps
    ], "the document and the flow do not run the same steps in the same order"

    gating = flow._expand_gating_config_vars(
        flow.gating_config_vars, [step.id for step in flow.Steps]
    )
    return {
        (job_id, implementation)
        for (job_id, implementation), step in zip(pairs, flow.Steps)
        if step.id in gating
    }


def test_the_classic_document_declares_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert _implementation_ids("classic.yaml") == [
        step.get_implementation_id() for step in Classic.Steps
    ]


def test_the_classic_document_gates_exactly_what_the_classic_flow_gates():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert _gated_pairs("classic.yaml") == _flow_gated_pairs("classic.yaml", Classic)


def test_the_classic_document_declares_the_classic_flow_s_variables():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    declared = {variable.name for variable in _document("classic.yaml").config}

    # TOOLS is declared by the engine, not by any document.
    assert declared | {"TOOLS"} == {v.name for v in Classic.config_vars}


def test_the_classic_document_omits_the_unimplemented_post_route_opt_stage():
    """
    Job.post_route_opt has no default provider and no registered provider, so
    it contributes no step to Classic.Steps and a bare 'uses' naming it is a
    load error. It is the only such stage.
    """
    assert "post_route_opt" not in _document("classic.yaml").jobs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: all four FAIL with `FileNotFoundError` or `ValueError: Unsupported configuration source`, because `classic.yaml` does not exist.

- [ ] **Step 3: Write the document**

Create `librelane/flows/classic.yaml`. The `config` block transcribes `Classic.Config` at `librelane/flows/classic.py:102-222`, keeping every default, description and `deprecated_names` list. The `jobs` block transcribes `Classic.Stages` at `classic.py:42-100` in order, one job per entry, each needing the one before it.

```yaml
name: Classic
description: A general-purpose RTL-to-GDSII flow.

config:
  - name: RUN_TAP_ENDCAP_INSERTION
    type: bool
    default: true
    description: Enables the OpenROAD.TapEndcapInsertion step.
    deprecated_names: [TAP_DECAP_INSERTION, RUN_TAP_DECAP_INSERTION]
  - name: RUN_POST_GPL_DESIGN_REPAIR
    type: bool
    default: true
    description: >-
      Enables resizer design repair after global placement using the
      OpenROAD.RepairDesignPostGPL step.
    deprecated_names: [PL_RESIZER_DESIGN_OPTIMIZATIONS, RUN_REPAIR_DESIGN]
  - name: RUN_POST_GRT_DESIGN_REPAIR
    type: bool
    default: false
    description: >-
      Enables resizer design repair after global routing using the
      OpenROAD.RepairDesignPostGRT step. This is experimental and may result in
      hangs and/or extended run times.
  - name: RUN_CTS
    type: bool
    default: true
    description: Enables clock tree synthesis using the OpenROAD.CTS step.
    deprecated_names: [CLOCK_TREE_SYNTH]
  - name: RUN_POST_CTS_RESIZER_TIMING
    type: bool
    default: true
    description: >-
      Enables resizer timing optimizations after clock tree synthesis using the
      OpenROAD.ResizerTimingPostCTS step.
    deprecated_names: [PL_RESIZER_TIMING_OPTIMIZATIONS]
  - name: RUN_POST_GRT_RESIZER_TIMING
    type: bool
    default: false
    description: >-
      Enables resizer timing optimizations after global routing using the
      OpenROAD.ResizerTimingPostGRT step. This is experimental and may result in
      hangs and/or extended run times.
    deprecated_names: [GLB_RESIZER_TIMING_OPTIMIZATIONS]
  - name: RUN_HEURISTIC_DIODE_INSERTION
    type: bool
    default: false
    description: Enables the Odb.HeuristicDiodeInsertion step.
  - name: RUN_ANTENNA_REPAIR
    type: bool
    default: true
    description: Enables the OpenROAD.RepairAntennas step.
    deprecated_names: [GRT_REPAIR_ANTENNAS]
  - name: RUN_DRT
    type: bool
    default: true
    description: Enables the OpenROAD.DetailedRouting step.
  - name: RUN_FILL_INSERTION
    type: bool
    default: true
    description: Enables the OpenROAD.FillInsertion step.
  - name: RUN_MCSTA
    type: bool
    default: true
    description: >-
      Enables multi-corner static timing analysis using the
      OpenROAD.STAPostPNR step.
    deprecated_names: [RUN_SPEF_STA]
  - name: RUN_SPEF_EXTRACTION
    type: bool
    default: true
    description: Enables parasitics extraction using the OpenROAD.RCX step.
  - name: RUN_IRDROP_REPORT
    type: bool
    default: true
    description: >-
      Enables generation of an IR Drop report using the OpenROAD.IRDropReport
      step.
  - name: RUN_LVS
    type: bool
    default: true
    description: Enables the Netgen.LVS step.
  - name: RUN_MAGIC_STREAMOUT
    type: bool
    default: true
    description: Enables the Magic.StreamOut step to generate GDSII.
    deprecated_names: [RUN_MAGIC]
  - name: RUN_KLAYOUT_STREAMOUT
    type: bool
    default: true
    description: Enables the KLayout.StreamOut step to generate GDSII.
    deprecated_names: [RUN_KLAYOUT]
  - name: RUN_MAGIC_WRITE_LEF
    type: bool
    default: true
    description: Enables the Magic.WriteLEF step.
    deprecated_names: [MAGIC_GENERATE_LEF]
  - name: RUN_KLAYOUT_XOR
    type: bool
    default: true
    description: >-
      Enables running the KLayout.XOR step on the two GDSII files generated by
      Magic and Klayout. Stream-outs for both KLayout and Magic should have
      already run, and the PDK must support both signoff tools.
  - name: RUN_MAGIC_DRC
    type: bool
    default: true
    description: Enables the Magic.DRC step.
  - name: RUN_KLAYOUT_DRC
    type: bool
    default: true
    description: Enables the KLayout.DRC step.
  - name: RUN_EQY
    type: bool
    default: false
    description: >-
      Enables the formal equivalence stage, i.e. the Yosys.EQY step. Has no
      effect in VHDLClassic, which does not run that stage.
  - name: RUN_LINTER
    type: bool
    default: true
    description: >-
      Enables the lint stage, i.e. the Verilator.Lint step and associated
      checker steps. Has no effect in VHDLClassic, which does not run that
      stage.
    deprecated_names: [RUN_VERILATOR]

jobs:
  lint:
    uses: lint
    if: RUN_LINTER
  synthesis:
    needs: [lint]
    uses: synthesis/yosys
  pre_pnr_sta:
    needs: [synthesis]
    uses: pre_pnr_sta
  floorplan:
    needs: [pre_pnr_sta]
    uses: floorplan
  set_power_connections:
    needs: [floorplan]
    steps: [Odb.SetPowerConnections]
  macro_placement:
    needs: [set_power_connections]
    uses: macro_placement
  cut_rows:
    needs: [macro_placement]
    steps: [OpenROAD.CutRows]
  tapcell_insertion:
    needs: [cut_rows]
    uses: tapcell_insertion
    if: RUN_TAP_ENDCAP_INSERTION
  power_grid:
    needs: [tapcell_insertion]
    uses: power_grid
  add_routing_obstructions:
    needs: [power_grid]
    steps: [Odb.AddRoutingObstructions]
  io_placement:
    needs: [add_routing_obstructions]
    uses: io_placement
  add_buffer:
    needs: [io_placement]
    steps: [OpenROAD.AddBuffer]
  global_placement:
    needs: [add_buffer]
    uses: global_placement
  write_verilog_header:
    needs: [global_placement]
    steps: [Odb.WriteVerilogHeader, Checker.PowerGridViolations]
  sta_mid_pnr_1:
    needs: [write_verilog_header]
    steps: [OpenROAD.STAMidPNR]
  post_gpl_repair:
    needs: [sta_mid_pnr_1]
    uses: post_gpl_repair
    if: RUN_POST_GPL_DESIGN_REPAIR
  manual_global_placement:
    needs: [post_gpl_repair]
    steps: [Odb.ManualGlobalPlacement]
  detailed_placement:
    needs: [manual_global_placement]
    uses: detailed_placement
  cts:
    needs: [detailed_placement]
    uses: cts
    if: RUN_CTS
  sta_mid_pnr_2:
    needs: [cts]
    steps: [OpenROAD.STAMidPNR]
  post_cts_opt:
    needs: [sta_mid_pnr_2]
    uses: post_cts_opt
    if: RUN_POST_CTS_RESIZER_TIMING
  sta_mid_pnr_3:
    needs: [post_cts_opt]
    steps: [OpenROAD.STAMidPNR]
  global_routing:
    needs: [sta_mid_pnr_3]
    uses: global_routing
  post_grt_repair:
    needs: [global_routing]
    uses: post_grt_repair
    if: RUN_POST_GRT_DESIGN_REPAIR
  diodes_on_ports:
    needs: [post_grt_repair]
    steps: [Odb.DiodesOnPorts]
    if: RUN_ANTENNA_REPAIR
  heuristic_diode_insertion:
    needs: [diodes_on_ports]
    steps: [Odb.HeuristicDiodeInsertion]
    if: RUN_ANTENNA_REPAIR and RUN_HEURISTIC_DIODE_INSERTION
  repair_antennas:
    needs: [heuristic_diode_insertion]
    steps: [OpenROAD.RepairAntennas]
    if: RUN_ANTENNA_REPAIR
  post_grt_opt:
    needs: [repair_antennas]
    uses: post_grt_opt
    if: RUN_POST_GRT_RESIZER_TIMING
  sta_mid_pnr_4:
    needs: [post_grt_opt]
    steps: [OpenROAD.STAMidPNR]
  detailed_routing:
    needs: [sta_mid_pnr_4]
    uses: detailed_routing
    if: RUN_DRT
  routing_reports:
    needs: [detailed_routing]
    steps:
      - Odb.ReportDisconnectedPins
      - Checker.DisconnectedPins
      - Odb.ReportWireLength
      - Checker.WireLength
  fill_insertion:
    needs: [routing_reports]
    uses: fill_insertion
    if: RUN_FILL_INSERTION
  cell_frequency_tables:
    needs: [fill_insertion]
    steps: [Odb.CellFrequencyTables]
  extraction:
    needs: [cell_frequency_tables]
    uses: extraction
    if: RUN_SPEF_EXTRACTION
  signoff_sta:
    needs: [extraction]
    uses: signoff_sta
    if: RUN_MCSTA
  ir_drop:
    needs: [signoff_sta]
    uses: ir_drop
    if: RUN_IRDROP_REPORT
  magic_streamout:
    needs: [ir_drop]
    uses: streamout/magic
    if: RUN_MAGIC_STREAMOUT
  klayout_streamout:
    needs: [magic_streamout]
    uses: streamout/klayout
    if: RUN_KLAYOUT_STREAMOUT
  render:
    needs: [klayout_streamout]
    steps: [KLayout.Render]
  write_lef:
    needs: [render]
    steps: [Magic.WriteLEF]
    if: RUN_MAGIC_WRITE_LEF
  check_antenna_properties:
    needs: [write_lef]
    steps: [Odb.CheckDesignAntennaProperties]
  xor:
    needs: [check_antenna_properties]
    steps: [KLayout.XOR, Checker.XOR]
    if: RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT and RUN_KLAYOUT_STREAMOUT
  magic_drc:
    needs: [xor]
    uses: drc/magic
    if: RUN_MAGIC_DRC
  klayout_drc:
    needs: [magic_drc]
    uses: drc/klayout
    if: RUN_KLAYOUT_DRC
  lvs:
    needs: [klayout_drc]
    uses: lvs
    if: RUN_LVS
  formal_equivalence:
    needs: [lvs]
    uses: formal_equivalence
    if: RUN_EQY
  final_checks:
    needs: [formal_equivalence]
    steps:
      - Checker.SetupViolations
      - Checker.HoldViolations
      - Checker.MaxSlewViolations
      - Checker.MaxCapViolations
      - Misc.ReportManufacturability
```

Two notes on that document.

**No job carries a `source` key here, and that is deliberate.** Phase 1 requires a `source` entry to name a **direct predecessor** whose branch can produce the key, and it splits that into two checks. `FlowSpec._check_sources_name_direct_predecessors` (phase 1 Task 3, structural) enforces the direct-predecessor half, and `_check_sources_can_deliver` (phase 1 Task 6, registry-backed) enforces the branch-capability half. The one that matters here is the first. In a chain every job has exactly one direct predecessor, so a `source: {gds: klayout_streamout}` on `magic_drc` would name a job three edges upstream and the document would not load. It would also say nothing, because a single predecessor is not a fan-in. The chain reproduces today's last-writer-wins behaviour on its own, since `klayout_streamout` runs after `magic_streamout` and its output state carries KLayout's `gds` and Magic's `mag_gds` forward. Task 3 adds the `needs` and the `source` together, which is where the decision recorded in "The Magic DRC decision" above becomes a reviewable line.

`heuristic_diode_insertion`'s two-variable `if` is exactly what `_expand_gating_config_vars` produces for `Odb.HeuristicDiodeInsertion`, which is `['RUN_ANTENNA_REPAIR', 'RUN_HEURISTIC_DIODE_INSERTION']`. Splitting the job is what lets a job-level `if` say that.

- [ ] **Step 4: Run the tests until they pass**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: 4 passed. A mismatch in the first test prints the two implementation-id lists, and the first differing index names the job transcribed wrongly.

- [ ] **Step 5: Check every other job for a stage with no default provider**

```bash
cd /home/kelvin/librelane
uv run python -c "
import librelane.steps
from librelane.jobs.job import Job
from librelane.jobs.registry import JobRegistry
bad = [j for j in sorted(Job.factory.list())
       if not Job.factory.get(j).default_providers]
print('templates a bare uses cannot name:', bad)
print('their providers:', {j: JobRegistry.providers(j) for j in bad})
"
```

Expected: `['post_route_opt']` and `{'post_route_opt': []}`. That is the whole list, measured against this checkout under the pre-phase-3 names, and no document in this plan names it. If the list ever grows, every bare `uses` naming a new member has to gain an explicit provider or be dropped.

- [ ] **Step 6: Confirm the YAML ships in the wheel**

`pyproject.toml` uses hatchling with `packages = ["librelane"]` and no `include` or `exclude` under `[tool.hatch.build.targets.wheel]`, so every file under `librelane/` ships. `librelane/pdk_hashes.yaml` and `librelane/examples/spm/config.yaml` are already shipped that way, which is the evidence that no configuration change is needed. Prove it for the new file rather than trusting the argument:

```bash
cd /home/kelvin/librelane
uv build
python3 -c "
import glob, zipfile
names = zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]).namelist()
print([n for n in names if n.endswith('.yaml')])
"
```

Expected: the list contains `librelane/flows/classic.yaml`. If it does not, add `librelane/flows/*.yaml` to the wheel target's `include` and re-run.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows/classic.yaml test/flows/test_documents.py
git commit -m "feat: translate Classic into a workflow document"
```

---

### Task 3: Relax Classic's edges into the real graph

**Files:**
- Modify: `librelane/flows/classic.yaml`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Consumes: `_implementation_ids`, `_gated_pairs`, `_flow_gated_pairs` from Task 2.
- Produces: `classic.yaml` with `final_checks` as its single sink.

**Design notes the implementer needs:**

Task 2's chain is correct but sequential. This task removes the edges that only existed because a list has no way to say "independent".

`test_the_classic_document_declares_the_same_steps_as_the_classic_flow` is **replaced** here, not kept. Once the graph is a real DAG the document's declaration order is no longer a claim about execution order, so the pin becomes a set comparison plus explicit edge assertions. `_flow_gated_pairs` keeps working, because it lines the two sides up by declaration order rather than by execution order, and declaration order does not change.

**What is relaxed, and why each one is safe.** Every relaxation below moves a job off the chain onto a real data edge, and the measurement that justifies it is named.

- `magic_streamout` and `klayout_streamout` both need `ir_drop`. Both consume `def` only, and they are the two independent producers of `gds`.
- `render` needs `ir_drop`. `KLayout.Render` consumes `def` and produces nothing.
- `write_lef`, `xor`, `magic_drc`, `klayout_drc` and `lvs` each need **both** streamouts. Each consumes `gds`, `mag_gds` or `klayout_gds`, so each joins the two producers, and the fan-in on `gds` is what makes the `source` line load-bearing rather than decorative.
- `check_antenna_properties` needs `write_lef`, because `Odb.CheckDesignAntennaProperties` consumes `lef` and `Magic.WriteLEF` is the only producer of it.
- `formal_equivalence` needs `lvs` for ordering only. Its `nl` comes from `fill_insertion`, a common ancestor.
- `final_checks` needs every job that would otherwise be a leaf.

**What is deliberately not relaxed.** Four edges that an earlier draft of this plan relaxed are kept, each because a measurement says the relaxation changes behaviour.

- **`formal_equivalence` does not move to `synthesis`.** `Yosys.EQY` consumes `nl`, and in the linear flow the last writer of `nl` before it is `OpenROAD.FillInsertion`. It compares the RTL against the post-place-and-route netlist, not the synthesised one. Moving it would change what it checks.
- **The four `sta_mid_pnr_*` jobs stay on the chain.** `OpenROAD.STAMidPNR` consumes `odb` and produces no view, so it looks independent. It produces metrics, and all four produce the *same* metric names with different values. The linear flow lets each one overwrite the last. Four parallel branches would meet at a join with four unequal values for one metric name, which is a conflict no `source` on a view can resolve.
- **`ir_drop` stays after `signoff_sta`.** The relaxation on offer is to move `ir_drop` onto `extraction`, which is where its `spef` comes from. That makes `signoff_sta` and `ir_drop` two parallel branches, and since `final_checks` needs every leaf, they meet again there. The view that makes it unsafe is `sdf`.

  `OpenROAD.STAPostPNR.outputs` is `[SDF, LIB]`, and the SDF is written in `STAPrePNR.run`, which `STAPostPNR` inherits. That method copies the incoming corner-to-path dictionary and sets one entry per corner in `STA_CORNERS` to a path under its own `step_dir`. `OpenROAD.STAPrePNR` writes `sdf` by the same method, in the ungated `pre_pnr_sta` job, which is an ancestor of both branches. So both branches carry an `sdf`, with the same corner keys and different paths, always. The join of the two has two unequal values for one key and no `source` that could choose between them without asserting which STA the flow believes.

  **`lib` does not carry the argument**, even though `signoff_sta` writes it. `OpenROAD.STAPostPNR` is the only step in Classic that writes `lib`, so the bypassing branch carries none. A key only one predecessor carries is unambiguous, and the join takes it, which is the rule stated under "The join rule this plan depends on" above.

  **`sdc` does not carry it either, and an earlier draft of this plan said it did.** That draft was written against `MultiCornerSTA.outputs = [SDF, SDC]`, which claimed an SDC no code in the class writes. Branch `worktree-agent-a2dad013ce988e29b` removes the claim, so `STAPostPNR` writes no `sdc`, both branches carry `fill_insertion`'s SDC unchanged, and they agree on it. The conclusion was right and the stated reason was wrong.

  **This is a run-time conflict, not a load-time one, and the plan should not pretend otherwise.** `Stage.signoff_sta.provides` is the empty tuple, measured in this checkout, so phase 1's `_check_fan_in_is_unambiguous` reasons over declared contracts and sees no fan-in to object to. Phase 2's `join_states` is what would raise `JoinConflictError`, on the first run, after the tools had already been invoked. That asymmetry is itself a reason to keep the edge rather than to relax it and rely on a check that fires late.
- **`final_checks` does not need `signoff_sta` alone.** `Misc.ReportManufacturability` reads LVS, DRC and antenna metrics out of `state_in.metrics` and warns for each one it cannot find. Narrowing its `needs` would turn the manufacturability report into five warnings.

**Why `final_checks` is the single sink.** The spec gives a document an optional top-level `final` key for the case where the sink join conflicts. Making `final_checks` need every other leaf removes that case by construction, and it makes the flow's final state the state today's linear flow ends with, which is what `runs/<tag>/final` snapshots. It also costs nothing, because `final_checks` runs last today anyway.

- [ ] **Step 1: Replace the order test with graph tests**

In `test/flows/test_documents.py`, delete `test_the_classic_document_declares_the_same_steps_as_the_classic_flow` and add:

```python
def test_the_classic_document_runs_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert sorted(_implementation_ids("classic.yaml")) == sorted(
        step.get_implementation_id() for step in Classic.Steps
    )


def test_classic_s_two_streamouts_are_independent():
    from librelane.flows.spec_graph import ancestors

    edges = _document("classic.yaml").edges()

    assert "klayout_streamout" not in ancestors(edges, "magic_streamout")
    assert "magic_streamout" not in ancestors(edges, "klayout_streamout")


def test_classic_s_signoff_checks_are_independent_of_each_other():
    from librelane.flows.spec_graph import ancestors

    edges = _document("classic.yaml").edges()

    assert "klayout_drc" not in ancestors(edges, "magic_drc")
    assert "magic_drc" not in ancestors(edges, "klayout_drc")
    assert "magic_drc" not in ancestors(edges, "lvs")
    assert "xor" not in ancestors(edges, "magic_drc")


def test_every_classic_gds_consumer_joins_both_producers():
    edges = _document("classic.yaml").edges()

    for job in ["write_lef", "xor", "magic_drc", "klayout_drc", "lvs"]:
        assert set(edges[job]) == {"magic_streamout", "klayout_streamout"}, job


def test_every_classic_gds_consumer_names_the_producer_it_reads():
    """
    Magic.DRC, Magic.WriteLEF and Magic.SpiceExtraction all read KLayout's
    GDSII today, because KLayout.StreamOut is the last writer of 'gds' before
    any of them. See "The Magic DRC decision" in this plan.
    """
    jobs = _document("classic.yaml").jobs

    for job in ["write_lef", "xor", "magic_drc", "klayout_drc", "lvs"]:
        assert jobs[job].source["gds"] == "klayout_streamout", job


def test_classic_s_final_checks_is_the_only_sink():
    edges = _document("classic.yaml").edges()

    needed = {need for needs in edges.values() for need in needs}
    assert set(edges) - needed == {"final_checks"}


def test_classic_s_final_checks_waits_for_every_metric_it_reports():
    """
    Misc.ReportManufacturability reads LVS, DRC and antenna metrics out of
    state_in.metrics and warns for each one it cannot find, so final_checks has
    to descend from every job that produces them.
    """
    from librelane.flows.spec_graph import ancestors

    edges = _document("classic.yaml").edges()

    assert {
        "signoff_sta",
        "xor",
        "magic_drc",
        "klayout_drc",
        "lvs",
    } <= ancestors(edges, "final_checks")
```

The last test is written against ancestry rather than direct edges, because `signoff_sta` and `lvs` reach `final_checks` through `ir_drop` and `formal_equivalence` respectively.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: `test_the_classic_document_runs_the_same_steps_as_the_classic_flow` and `test_classic_s_final_checks_is_the_only_sink` pass, since a chain has one sink and the same step set. The other four FAIL, because Task 2's chain makes every job an ancestor of every later job.

- [ ] **Step 3: Apply the relaxations**

In `librelane/flows/classic.yaml`, change these `needs` lists and add the five `source` entries. Leave every `if`, `uses` and `steps` exactly as Task 2 wrote them.

```yaml
  magic_streamout:
    needs: [ir_drop]
  klayout_streamout:
    needs: [ir_drop]
  render:
    needs: [ir_drop]
  write_lef:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  check_antenna_properties:
    needs: [write_lef]
  xor:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  magic_drc:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  klayout_drc:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  lvs:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  formal_equivalence:
    needs: [lvs]
  final_checks:
    needs:
      - render
      - check_antenna_properties
      - xor
      - magic_drc
      - klayout_drc
      - formal_equivalence
```

Every `source` entry names `klayout_streamout`, which is a direct predecessor of the job that names it and whose branch produces `gds`, so all five satisfy both halves of phase 1's `source` checking, `_check_sources_name_direct_predecessors` and `_check_sources_can_deliver`. `final_checks` needs no `source`, because none of the six jobs it joins declares a `provides`, so the branches carry no key any two of them wrote differently. That was checked with the same command Step 6 of Task 4 uses, and the check is what would say otherwise.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: all pass. `test_the_classic_document_gates_exactly_what_the_classic_flow_gates` must still pass unchanged, because no `if` moved.

- [ ] **Step 5: Commit**

```bash
git add librelane/flows/classic.yaml test/flows/test_documents.py
git commit -m "feat: give Classic its real dependency graph"
```

---

### Task 4: The remaining seven documents

**Files:**
- Create: `librelane/flows/vhdl_classic.yaml`, `librelane/flows/chip.yaml`, `librelane/flows/open_in_klayout.yaml`, `librelane/flows/open_in_openroad.yaml`, `librelane/flows/open_in_openroad_console.yaml`, `librelane/flows/open_in_opensta_console.yaml`, `librelane/flows/open_in_magic.yaml`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Consumes: `_document`, `_implementation_ids`, `_gated_pairs`, `_flow_gated_pairs` from Task 2.
- Produces: seven more documents, and a parametrized equivalence test covering all eight.

**Design notes the implementer needs:**

**VHDLClassic.** Read `librelane/flows/classic.py:271-320`. The differences from `Classic` are a pinned synthesis provider and four omitted entries: `Job.lint`, `Odb.SetPowerConnections`, `Odb.WriteVerilogHeader` and **`Job.formal_equivalence`**. It **keeps** `Checker.PowerGridViolations`, which sits on its own directly after `Job.global_placement`. The `#:` note above the list, at `classic.py:263-270`, states this correctly, and it was verified against the list itself:

```console
$ uv run python -c "
import librelane.steps
from librelane.flows import Flow
print([s.id for s in Flow.factory.get('VHDLClassic').Steps])
"
```

The document is written out **in full**, not derived from Classic. `classic.py:263-266` records why. A filter expression over another flow's list is a substitution map wearing a different hat, and the same reasoning applies to an `extends:` key, which is why the document schema has none.

VHDLClassic keeps all 22 configuration variables, including `RUN_LINTER` and `RUN_EQY`. Both are inherited from `Classic.Config` today, so a configuration setting either one is accepted by VHDLClassic today and must stay accepted. Their descriptions already say "Has no effect in VHDLClassic". Dropping them would turn an accepted key into an unknown-key error.

**Chip.** Read `librelane/flows/chip.py:52-110`. The differences from Classic are `OpenROAD.PadRing` after `Odb.SetPowerConnections`, the six chip finishing steps after `Checker.XOR`, and three omissions: `Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties` and `Job.io_placement`, whose two still-needed steps `OpenROAD.GlobalPlacementSkipIO` and `Odb.ApplyDEFTemplate` appear as bare entries.

Chip's `gds` fan-in is one step further along than Classic's. `KLayout.SealRing` and `KLayout.Filler` both consume and produce `gds`, so the six finishing steps become one `chip_finishing` job that reads KLayout's GDSII and rewrites it, and Chip's `magic_drc`, `klayout_drc` and `lvs` read **`chip_finishing`'s** GDSII, which the measurement confirms.

**The Open-In flows** are five single-job documents with one inline step each and no `config`. Their registered names are their class names, `OpenInKLayout` and so on, while `SequentialFlow.name` carries a display string such as "Opening in KLayout". The document's `name` is the registration key, so it is the class name, and the display string becomes `description`.

Two of the five, `OpenInOpenROADConsole` and `OpenInOpenSTAConsole`, arrive with `6870f74`. They are the same shape as the three GUI ones, one step each, `OpenROAD.OpenConsole` and `OpenROAD.OpenSTAConsole`. Their job is named `open_console` rather than `open_gui`, because the step opens an interactive console and not a GUI, and a job id that lies about what it runs is a run directory that lies about it too.

**The document filename rule, stated here because it is authoritative.** A document's file is the snake-case of the class it replaces, and its `name:` key is that class name character for character. `OpenInOpenROADConsole` becomes `open_in_openroad_console.yaml` with `name: OpenInOpenROADConsole`, and `OpenInOpenSTAConsole` becomes `open_in_opensta_console.yaml` with `name: OpenInOpenSTAConsole`. `OpenROAD` lowercases to `openroad` and `OpenSTA` to `opensta`, which is the convention `open_in_openroad.yaml` already set.

The `name:` half is not a convention, it is a requirement: it is the key `Flow.factory.get_document` looks up and the string a user types after `--flow`, so it has to survive the migration unchanged or every existing invocation breaks. The filename half is a convention, and the reason to keep it a strict one-to-one transliteration rather than naming the file after what the flow does is that it makes "every class has a document" a mechanical check rather than a judgement call. Task 5 Step 1 turns it into an executable one.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_documents.py`:

```python
@pytest.mark.parametrize(
    "document,flow_name",
    [
        ("classic.yaml", "Classic"),
        ("vhdl_classic.yaml", "VHDLClassic"),
        ("chip.yaml", "Chip"),
        ("open_in_klayout.yaml", "OpenInKLayout"),
        ("open_in_openroad.yaml", "OpenInOpenROAD"),
        ("open_in_openroad_console.yaml", "OpenInOpenROADConsole"),
        ("open_in_opensta_console.yaml", "OpenInOpenSTAConsole"),
        ("open_in_magic.yaml", "OpenInMagic"),
    ],
)
def test_each_document_runs_the_same_steps_as_the_flow_it_replaces(
    document, flow_name
):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert sorted(_implementation_ids(document)) == sorted(
        step.get_implementation_id() for step in flow.Steps
    )


@pytest.mark.parametrize(
    "document,flow_name",
    [
        ("classic.yaml", "Classic"),
        ("vhdl_classic.yaml", "VHDLClassic"),
        ("chip.yaml", "Chip"),
    ],
)
def test_each_document_gates_exactly_what_the_flow_it_replaces_gates(
    document, flow_name
):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert _gated_pairs(document) == _flow_gated_pairs(document, flow)


@pytest.mark.parametrize(
    "document,flow_name",
    [
        ("classic.yaml", "Classic"),
        ("vhdl_classic.yaml", "VHDLClassic"),
        ("chip.yaml", "Chip"),
    ],
)
def test_each_document_declares_the_flow_s_variables(document, flow_name):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)
    declared = {variable.name for variable in _document(document).config}

    assert declared | {"TOOLS"} == {v.name for v in flow.config_vars}


def test_vhdl_classic_pins_the_vhdl_synthesis_provider():
    assert _document("vhdl_classic.yaml").jobs["synthesis"].uses == (
        "synthesis/yosys_vhdl"
    )


def test_vhdl_classic_omits_the_four_jobs_it_cannot_run():
    """
    classic.py:263-270 names them: the lint stage, Odb.SetPowerConnections,
    Odb.WriteVerilogHeader and the formal equivalence stage. Checker.
    PowerGridViolations is NOT among them and must survive.
    """
    jobs = _document("vhdl_classic.yaml").jobs

    assert "lint" not in jobs
    assert "set_power_connections" not in jobs
    assert "formal_equivalence" not in jobs
    assert "Checker.PowerGridViolations" in jobs["power_grid_check"].steps


def test_chip_reads_the_sealed_and_filled_gds_for_signoff():
    """
    KLayout.SealRing and KLayout.Filler both rewrite 'gds', and they run before
    DRC and LVS today, so those read the finished layout rather than the raw
    stream-out.
    """
    jobs = _document("chip.yaml").jobs

    for job in ["magic_drc", "klayout_drc", "lvs"]:
        assert jobs[job].source["gds"] == "chip_finishing", job


def test_chip_omits_the_three_entries_a_chip_does_not_need():
    jobs = _document("chip.yaml").jobs

    assert "write_lef" not in jobs
    assert "check_antenna_properties" not in jobs
    assert "io_placement" not in jobs
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: the Classic cases pass; every other parametrized case and the five specific cases FAIL, because those documents do not exist.

- [ ] **Step 3: Write the five Open-In documents**

`librelane/flows/open_in_klayout.yaml`:

```yaml
name: OpenInKLayout
description: >-
  Opens the LEF/DEF from the initial state object in the KLayout GUI. Intended
  for use with a run tag that has already been run with another flow.
jobs:
  open_gui:
    steps: [KLayout.OpenGUI]
```

`librelane/flows/open_in_openroad.yaml`:

```yaml
name: OpenInOpenROAD
description: >-
  Opens the ODB from the initial state object in the OpenROAD GUI. Intended for
  use with a run tag that has already been run with another flow.
jobs:
  open_gui:
    steps: [OpenROAD.OpenGUI]
```

`librelane/flows/open_in_openroad_console.yaml`:

```yaml
name: OpenInOpenROADConsole
description: >-
  Opens the ODB from the initial state object in an interactive OpenROAD
  console. Intended for use with a run tag that has already been run with
  another flow.
jobs:
  open_console:
    steps: [OpenROAD.OpenConsole]
```

`librelane/flows/open_in_opensta_console.yaml`:

```yaml
name: OpenInOpenSTAConsole
description: >-
  Opens the netlist from the initial state object, and its parasitics if it has
  any, in an interactive OpenSTA console. Intended for use with a run tag that
  has already been run with another flow.
jobs:
  open_console:
    steps: [OpenROAD.OpenSTAConsole]
```

`librelane/flows/open_in_magic.yaml`:

```yaml
name: OpenInMagic
description: >-
  Opens the GDS or DEF from the initial state object in Magic. Intended for use
  with a run tag that has already been run with another flow.
jobs:
  open_gui:
    steps: [Magic.OpenGUI]
```

- [ ] **Step 4: Write `vhdl_classic.yaml`**

Copy `classic.yaml` in full, keeping the entire `config` block unchanged, then make exactly five changes to `jobs`. The `add_buffer` job copies across unchanged, because `457c060` adds `OpenROAD.AddBuffer` to `VHDLClassic.Stages` in the same position it adds it to `Classic.Stages`, between `Job.io_placement` and `Job.global_placement`.

1. Set `synthesis`'s `uses` to `synthesis/yosys_vhdl` and its `needs` to `[]`.
2. Delete the `lint` job.
3. Delete the `set_power_connections` job and re-point `macro_placement`'s `needs` to `[floorplan]`.
4. Replace the `write_verilog_header` job with a `power_grid_check` job that runs only the checker, since `Odb.WriteVerilogHeader` is gone and `Checker.PowerGridViolations` is not:

```yaml
  power_grid_check:
    needs: [global_placement]
    steps: [Checker.PowerGridViolations]
```

   and re-point `sta_mid_pnr_1`'s `needs` to `[power_grid_check]`.
5. Delete the `formal_equivalence` job, re-point `final_checks`'s `needs` from `formal_equivalence` to `lvs`, and leave the `RUN_EQY` variable declared.

- [ ] **Step 5: Write `chip.yaml`**

Transcribe `Chip.Stages` from `librelane/flows/chip.py:52` using Task 2's method, then apply Task 3's relaxations. The `config` block is identical to `classic.yaml`'s. The differences from `classic.yaml`'s `jobs` are:

```yaml
  pad_ring:
    needs: [set_power_connections]
    steps: [OpenROAD.PadRing]
  macro_placement:
    needs: [pad_ring]
    uses: macro_placement
  # Job.io_placement is omitted. The two steps of it a chip still needs are
  # listed inline: OpenROAD.GlobalPlacementSkipIO seeds placement before the
  # pins exist, and Odb.ApplyDEFTemplate copies a pin arrangement from a
  # template. Neither places a pin, so this flow has no io_placement boundary
  # and cannot swap that job's tool from TOOLS. chip.py:44-51 records why.
  placement_seed:
    needs: [add_routing_obstructions]
    steps: [OpenROAD.GlobalPlacementSkipIO, Odb.ApplyDEFTemplate]
  global_placement:
    needs: [placement_seed]
    uses: global_placement
```

and, after the streamouts:

```yaml
  xor:
    needs: [magic_streamout, klayout_streamout]
    steps: [KLayout.XOR, Checker.XOR]
    if: RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT and RUN_KLAYOUT_STREAMOUT
    source: {gds: klayout_streamout}
  chip_finishing:
    needs: [klayout_streamout]
    steps:
      - KLayout.Antenna
      - Checker.KLayoutAntenna
      - KLayout.SealRing
      - KLayout.Filler
      - KLayout.Density
      - Checker.KLayoutDensity
  magic_drc:
    needs: [magic_streamout, chip_finishing]
    uses: drc/magic
    if: RUN_MAGIC_DRC
    source: {gds: chip_finishing}
  klayout_drc:
    needs: [magic_streamout, chip_finishing]
    uses: drc/klayout
    if: RUN_KLAYOUT_DRC
    source: {gds: chip_finishing}
  lvs:
    needs: [magic_streamout, chip_finishing]
    uses: lvs
    if: RUN_LVS
    source: {gds: chip_finishing}
  formal_equivalence:
    needs: [lvs]
    uses: formal_equivalence
    if: RUN_EQY
  final_checks:
    needs: [render, xor, magic_drc, klayout_drc, formal_equivalence]
    steps:
      - Checker.SetupViolations
      - Checker.HoldViolations
      - Checker.MaxSlewViolations
      - Checker.MaxCapViolations
      - Misc.ReportManufacturability
```

Delete the `write_lef` and `check_antenna_properties` jobs. `chip_finishing` is ungated, exactly as its six steps are today.

- [ ] **Step 6: Sweep both new documents for undeclared fan-in**

The two checks phase 1 runs at load are the ones that catch a wrong `needs`, so run them directly against each document before running the suite:

```bash
cd /home/kelvin/librelane
uv run python -c "
from importlib.resources import files
import librelane.steps
from librelane.flows.spec import load_flow_spec
from librelane.flows.spec_validation import validate_against_registry
for name in ['classic.yaml', 'vhdl_classic.yaml', 'chip.yaml',
             'open_in_klayout.yaml', 'open_in_openroad.yaml',
             'open_in_openroad_console.yaml', 'open_in_opensta_console.yaml',
             'open_in_magic.yaml']:
    validate_against_registry(
        load_flow_spec(str(files('librelane.flows').joinpath(name)))
    )
    print(name, 'ok')
"
```

Expected: eight `ok` lines. A `FlowSpecError` naming a view and two producers is an undeclared fan-in, and the fix is a `source` entry naming whichever producer the linear flow's last-writer measurement says wins. Re-run the measurement rather than guessing.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: all pass.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows test/flows/test_documents.py
git commit -m "feat: translate the remaining seven flows into documents"
```

---

### Task 5: Register documents in the flow factory

**Files:**
- Modify: `librelane/flows/__init__.py`, `librelane/flows/flow.py`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Consumes: the eight documents from Tasks 2 and 4.
- Produces: `Flow.factory.register_document(spec) -> FlowSpec`, `Flow.factory.get_document(name) -> FlowSpec | None`, `Flow.factory.list()` returning class and document names together, and `test_every_registered_flow_class_has_a_document_standing_in_for_it`, the guard that no flow class reaches phase 5 without a document.

**Design notes the implementer needs:**

`Flow.factory` maps a name to a `type[Flow]`, registered by the `@Flow.factory.register()` decorator defined at `librelane/flows/flow.py:1136`, with `get` at `:1161` and `list` at `:1173`. The registry itself is the name-mangled `FlowFactory.__registry` at `:1133`.

Keep the class-based registration path working. Phase 5 deletes it. Removing it here would break `test_documents.py`, which compares each document against the Python flow it replaces, and that comparison is what makes phase 5's deletions safe.

`test_every_registered_flow_class_has_a_document_standing_in_for_it` is why this task, rather than Task 4, is where the completeness guard lands. It needs both registries populated, and Task 4 has only one. It imports `librelane.flows.builtins` explicitly rather than relying on import order, because that module is what pulls in `classic.py`, `chip.py` and `misc.py` for their registration side effects. Note that `builtins.py` imports only `OpenInKLayout` and `OpenInOpenROAD` from `misc`, not all five classes; executing the module is what runs all five `@Flow.factory.register()` decorators, which is already how `OpenInMagic` gets registered today. That was read on the branch and is unchanged by it, so no import there needs updating for `6870f74`'s two new flows, and a test that counted the names in that import statement would be measuring the wrong thing.

The two therefore coexist under one name, so use two registries behind one lookup. `get_document` consults the document registry and `get` consults the class registry, while `list` returns the union, because `list()` is what error messages offer the user and a document the user can run has to appear in it. During this phase the two sets happen to be equal; after phase 5 only the documents remain, and `list()` needs no further change.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_documents.py`:

```python
def test_every_document_is_registered_under_its_name():
    from librelane.flows import Flow
    from librelane.flows.spec import FlowSpec

    for name in [
        "Classic",
        "VHDLClassic",
        "Chip",
        "OpenInKLayout",
        "OpenInOpenROAD",
        "OpenInOpenROADConsole",
        "OpenInOpenSTAConsole",
        "OpenInMagic",
    ]:
        registered = Flow.factory.get_document(name)
        assert isinstance(registered, FlowSpec)
        assert registered.name == name


def test_the_factory_lists_documents_and_classes_together():
    from librelane.flows import Flow

    listed = Flow.factory.list()

    assert "Classic" in listed
    assert len(listed) == len(set(listed)), "a name was listed twice"


def test_every_registered_flow_class_has_a_document_standing_in_for_it():
    """
    The completeness guard, derived from the registries rather than from a
    literal list, because a literal list cannot fail for a flow nobody
    remembered to add to it.

    A class with no document is the one failure this phase and the next are
    arranged to prevent: this phase would convert every flow but that one, and
    the next would delete its class with nothing in its place, removing a
    working flow from the product. The test above pins the names that exist;
    this one pins that no name is missing.
    """
    import librelane.flows.builtins  # noqa: F401  registers every flow class

    from librelane.flows import Flow

    listed = Flow.factory.list()
    classes = {name for name in listed if Flow.factory.get(name) is not None}
    documents = {
        name for name in listed if Flow.factory.get_document(name) is not None
    }

    assert classes - documents == set(), (
        "these flow classes have no document standing in for them, so phase 5 "
        "would delete them with nothing in their place"
    )


def test_a_document_is_rejected_at_import_if_it_is_malformed(tmp_path):
    from librelane.flows.spec import FlowSpecError, load_flow_spec

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\njobs:\n  a:\n    needs: [nope]\n    uses: lint\n")

    with pytest.raises(FlowSpecError):
        load_flow_spec(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest test/flows/test_documents.py::test_every_document_is_registered_under_its_name -v`
Expected: FAIL with `AttributeError: type object 'FlowFactory' has no attribute 'get_document'`

- [ ] **Step 3: Add document registration**

In `librelane/flows/flow.py`, inside the `FlowFactory` class, add:

```python
        _documents: ClassVar[dict[str, "FlowSpec"]] = {}

        @classmethod
        def register_document(Self, spec: "FlowSpec") -> "FlowSpec":
            """
            Registers a workflow document under its own ``name``.

            Parameters
            ----------
            spec : FlowSpec
                The loaded document.

            Returns
            -------
            FlowSpec
                The same document, so this reads as a pipeline step.

            Raises
            ------
            FlowException
                If a document with that name is already registered.
            """
            if spec.name in Self._documents:
                raise FlowException(
                    f"A flow document named '{spec.name}' is already "
                    f"registered."
                )
            Self._documents[spec.name] = spec
            return spec

        @classmethod
        def get_document(Self, name: str) -> "FlowSpec | None":
            """
            Parameters
            ----------
            name : str
                The document's ``name``. Case-sensitive, as
                :meth:`get` is.

            Returns
            -------
            FlowSpec | None
                The document registered under this name, or ``None``.
            """
            return Self._documents.get(name)
```

and change `list` to return both registries:

```python
        @classmethod
        def list(Self) -> builtins.list[str]:
            """
            Returns
            -------
            builtins.list[str]
                Every runnable flow name, documents and classes together.
                Sorted, because this is what error messages offer the user and
                two registries have no shared insertion order to preserve.
            """
            return sorted(set(Self.__registry) | set(Self._documents))
```

In `librelane/flows/__init__.py`, after the existing flow imports, load every shipped document:

```python
from importlib.resources import files

from librelane.flows.spec import load_flow_spec

for _document in sorted(files(__name__).iterdir(), key=lambda entry: entry.name):
    if _document.name.endswith(".yaml"):
        Flow.factory.register_document(load_flow_spec(str(_document)))
```

Sorting by name makes the registration order deterministic, so a duplicate-name error names the same document on every machine. `load_flow_spec` runs only the structural checks, which do not touch the step or stage registries, so this import does not pull `librelane.steps` into `librelane.flows`'s import graph. `Workflow.__init__` is where `validate_against_registry` runs.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/flows -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows test/flows/test_documents.py
git commit -m "feat: register shipped workflow documents in the flow factory"
```

---

### Task 6: `--target`, `--invalidate` and `--skip` in the engine

**Files:**
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `ancestors`, `descendants` from `librelane.flows.spec_graph`; the `counting_steps`, `minimal_design` and `mock_pdk` fixtures from `test/flows/conftest.py` (phase 2).
- Produces: `Workflow.run(self, initial_state, target=None, invalidate=None, skip=None, **kwargs)` and `Workflow._require_declared(names, option)`.

**Design notes the implementer needs:**

This task changes the engine only. The command-line options move in Task 11, together with the switch to `Workflow`. Renaming `--from` to `--invalidate` while the CLI still builds a `SequentialFlow` would put `invalidate=` into `SequentialFlow.run`'s `**kwargs`, where it would be swallowed without a word. A silently accepted option is exactly what this plan is not allowed to produce, even for one commit.

`--from` was never flow control. Its own help text says it ignores any reusable result for a step and everything after it, which is entirely a statement about the cache. It exists because `resume_key` hashes `{schema, step, librelane_version, config, state_in}` and cannot hash the tool binary, an edited TCL script or a PDK file. `--invalidate` is that behaviour under a name that says so.

`--to` was an approximation on a list of what `make X` is on a graph. `--target` runs the named job and its transitive ancestors, and repeats.

The three compose in a fixed order. `--target` restricts the graph first; `--skip` and `--invalidate` apply within the restriction, and naming a job outside it is an error rather than a silent no-op.

`--skip` is kept deliberately as a debug escape hatch, not as a modelling mechanism. The declarative way to make a job optional is to give it an `if`.

**On the fixtures these tests use.** `_mock_conf_fs` is defined at `test/conftest.py:69` and `mock_variables` at `test/conftest.py:231`, exposed as `pytest.mock_variables` by `pytest_configure` at `test/conftest.py:395`. `test/flows/test_flow.py:180-193` is the pattern every flow test follows.

Phase 2 puts `counting_steps`, `minimal_design` and `mock_pdk` into `test/flows/conftest.py`, all three as function-scoped **fixtures** rather than module constants, and every test in this plan takes them as arguments. They are fixtures for a measured reason. `test/flows`, `test/steps` and `test/ioplace_parser` each hold a `conftest.py` and none of the three has an `__init__.py`, so under pytest's default `prepend` import mode all three are imported under the single module name `conftest`, and `from conftest import _MOCK_PDK` resolves to whichever sibling was imported first. Do not reintroduce a module-level `_MOCK_PDK` or `_MINIMAL_DESIGN` anywhere in `test/flows/`.

- `minimal_design` returns `{"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]}`.
- `mock_pdk` returns `{"design_dir": "/cwd", "pdk": "dummy", "scl": "dummy_scl", "pdk_root": "/pdk"}`.
- `counting_steps` returns `(order, First, Second)`, registering `Test.EngineFirst` and `Test.EngineSecond`.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_target_runs_only_the_named_job_and_its_ancestors(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="target", target=["first"])

    assert order == ["Test.EngineFirst"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_target_naming_an_unknown_job_is_an_error(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="unknown", target=["nope"])

    message = str(exc_info.value)
    assert "nope" in message
    assert "first" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_skip_outside_the_target_subgraph_is_an_error(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="outside", target=["first"], skip=["second"])

    assert "second" in str(exc_info.value)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_invalidate_forces_a_job_and_its_descendants_to_rerun(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    Workflow(spec, minimal_design, **mock_pdk).start(tag="invalidate")
    order.clear()

    Workflow(spec, minimal_design, **mock_pdk).start(
        tag="invalidate", invalidate=["first"]
    )

    # 'first' is forced, and 'second' re-runs because its input state changed.
    assert order == ["Test.EngineFirst", "Test.EngineSecond"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: the four new tests FAIL with `TypeError` about unexpected keyword arguments.

- [ ] **Step 3: Implement the three options in the engine**

In `librelane/flows/engine.py`, extend the imports with `from librelane.flows.spec_graph import ancestors, descendants`, and change `run`'s signature and the net construction:

```python
    def run(
        self,
        initial_state: State,
        target: Iterable[str] | None = None,
        invalidate: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        Parameters
        ----------
        initial_state : State
            The state deposited on every source place.
        target : Iterable[str] | None
            Run only these jobs and their transitive
            ancestors. ``None`` runs the whole graph.
        invalidate : Iterable[str] | None
            Treat these jobs and their transitive
            descendants as having no reusable result.
        skip : Iterable[str] | None
            Job ids to fire as pass-through without running.

        Returns
        -------
        tuple[State, list[Step]]
            ``(final_state, steps_run)``

        Raises
        ------
        FlowException
            If any named job is not declared, or lies outside
            the ``target`` subgraph.
        """
        edges = self.spec.edges()

        selected = set(self.jobs)
        if target is not None:
            targets = list(target)
            self._require_declared(targets, "--target")
            selected = set()
            for name in targets:
                selected.add(name)
                selected |= ancestors(edges, name)

        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")
        invalidated = set(invalidate or ())
        self._require_declared(sorted(invalidated), "--invalidate")

        outside = (skipped | invalidated) - selected
        if outside:
            raise FlowException(
                f"{sorted(outside)} lie outside the --target subgraph "
                f"{sorted(selected)}, so naming them would do nothing."
            )

        forced: set[str] = set()
        for name in invalidated:
            forced.add(name)
            forced |= descendants(edges, name) & selected

        edges = {
            name: [need for need in needs if need in selected]
            for name, needs in edges.items()
            if name in selected
        }
        net = Net([name for name in self.jobs if name in selected], edges)
```

Add the helper:

```python
    def _require_declared(self, names: Iterable[str], option: str) -> None:
        """
        Raises
        ------
        FlowException
            If any name is not a job of this document. The
            message lists the declared jobs, so a typo is correctable without
            opening the document.
        """
        for name in names:
            if name not in self.jobs:
                raise FlowException(
                    f"{option} names '{name}', which flow "
                    f"'{self.spec.name}' does not declare. Declared jobs: "
                    f"{sorted(self.jobs)}."
                )
```

Thread `forced` through to the resume lookup. `_run_job` takes it as a required parameter rather than one defaulting to `False`, so that a future caller cannot forget it and silently consult the cache:

```python
    def _run_job(
        self,
        job: ResolvedJob,
        state_in: State,
        steps_run: list[Step],
        deferred: list[str],
        forced: bool,
    ) -> State:
        ...
            reused = (
                None
                if forced
                else reusable_state(step_dir, key, self.fingerprinter)
            )
```

and amend the one call site, the `get_tpe().submit(...)` in phase 2's marking loop, where `name` is the job id and `forced` is the set computed above:

```python
                    pending[
                        get_tpe().submit(
                            self._run_job,
                            job,
                            state_in,
                            steps_run,
                            deferred,
                            name in forced,
                        )
                    ] = name
```

Task 8 extends this same signature and this same call site once more, with `reproducible_at`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows/engine.py test/flows/test_engine.py
git commit -m "feat: the workflow engine takes target, invalidate and skip"
```

---

### Task 7: `TOOLS` re-keyed from stage ids to job ids

**Files:**
- Modify: `librelane/flows/engine.py`, `librelane/flows/job.py`
- Modify: `docs/source/usage/swapping_tools.md`, `docs/source/usage/writing_tool_backends.md`, `docs/source/usage/writing_custom_flows.md`, the three files under `docs/source/usage/` that mention `TOOLS` (measured with `grep -rln TOOLS docs/source/usage/`)
- Test: `test/flows/test_engine.py`, `test/flows/test_job.py`

**Interfaces:**
- Consumes: `extract_tools` from `librelane/stages/tools.py`; `resolve_jobs` from phase 2.
- Produces:
  - `resolve_jobs(spec: FlowSpec, tools: Mapping[str, str] | None = None) -> dict[str, ResolvedJob]`.
  - `Workflow.Config.TOOLS`, declaring the variable on the engine.
  - `Workflow.__init__(self, spec, config, *, config_override_strings=None, **kwargs)`.

**Design notes the implementer needs:**

`TOOLS` is a real subsystem and no other task in these five plans implements it, so without this task it vanishes when phase 5 deletes `staged.py`. `StagedFlow.Config.TOOLS` declares the variable at `librelane/flows/staged.py:115`, `StagedFlow.__selected_tools` at `staged.py:428-448` reads it, and `librelane/stages/resolution.py:121-149` consumes it.

**What this task provides against phase 5's precondition.** Phase 5's deletion of `staged.py` is guarded by a precondition that TOOLS support exists on the new engine, and it names two modules. This task answers both, and the answers are different.

| Module | What phase 5 recorded | What this task actually does |
| --- | --- | --- |
| `librelane/stages/tools.py` | `extract_tools()` survives unchanged | Confirmed. `Workflow._selected_tools` calls it with the same arguments `StagedFlow.__selected_tools` passes, and no line of the module changes. |
| `librelane/stages/resolution.py` | Deleted whole, in Task 2, alongside `staged.py`, its only caller | Agreed. Nothing in that module survives. `resolve_jobs(spec, tools)` replaces `resolve(entries, tools)` outright. |

The second row is stated because a plan that expected `resolve()` to survive would keep a module nothing calls. An earlier draft of phase 5 did expect that, and this row recorded the contradiction; phase 5 has since been corrected at its lines 37, 181 and 341 and now says the same thing this task does, so the row records agreement rather than a conflict. `resolve()` takes a `Stages` list, walks it interleaving `Job` objects with bare `Step` classes, and rebuilds a grouping from `Registration.tagged_steps`. A document supplies the job set directly, `JobRegistry.get(job, provider)` supplies each job's steps, and `ResolvedJob` carries the `requires`, `provides`, `metrics` and `provider` that `ResolvedSpan` and `ProviderContract` carried. So `resolve`, `Resolution`, `ResolvedSpan`, `ProviderContract`, `StageEntry`, `_selection_for` and `_registration_for` all become unreachable the moment `StagedFlow` goes.

One function in that module is worth keeping, in a different form. `_check_tool_keys` at `librelane/stages/resolution.py:166-185` builds the rapidfuzz suggestion for a `TOOLS` key that names nothing. It cannot be reused as it stands, because it checks against a list of stage ids and the new key is a job id, so this task re-implements it in `librelane/flows/job.py` against `spec.jobs`. That is a re-implementation of eighteen lines, not a dependency, and the plan says so rather than leaving phase 5 to discover it.

**An assumption this rests on.** Phase 3's rename table lists `librelane/stages/resolution.py` moving to `librelane/jobs/resolution.py` as a pure rename, so this task assumes `librelane/jobs/resolution.py` is today's module under a new name and is still consumed only by `StagedFlow`. If phase 3 instead writes a fresh module and leaves the old one in place, the conclusion is unchanged and the dead module is simply the other one. Nothing in this task's design depends on which.

**Whether the pre-pass still has to exist.** It does, and a document does not dissolve the constraint. `librelane/stages/tools.py:17-21` states the constraint as a flow's step set having to be known before its configuration can be validated, because the steps declare the variables. What a document fixes at load is the **job** set, not the step set. `TOOLS` re-points a job's provider, a provider is a different `Registration` with a different step sequence, and those steps declare different variables. The circularity is therefore identical, and the evidence is in `Workflow.__init__` itself, which must assign `self.Steps` before calling `super().__init__` because `Flow.__init__` at `librelane/flows/flow.py:492-501` passes `self.get_all_config_variables()` into `Config.load`, and that reads `self.Steps`.

The one design that would dissolve it is to validate against the union of every registered provider's variables for every job's stage, so that the variable set no longer depends on the selection. That is rejected. It would accept variables belonging to tools the run does not use, which is the opposite of the namespace discipline `JobRegistry.__check_contract` enforces, and it would silently accept a typo in a variable that only the unselected tool declares.

So the pre-pass survives verbatim, and with it the two rules `tools.py` documents: `TOOLS` must be a literal mapping, and it cannot come from the PDK or pass through the configuration preprocessor. `_reject_construct` at `librelane/stages/tools.py:51-59` continues to enforce the first.

**Why the pre-pass exists, and whether it still has to.** `librelane/stages/tools.py:17-21` states the reason. A flow's step set must be known before its configuration can be validated, because the steps are what declare the variables, and when configuration is also what selects the steps that is circular. `extract_tools` breaks the cycle by reading one key out of the raw sources with no preprocessing and no validation.

That constraint holds unchanged for a document-driven flow, and the evidence is in phase 2's own `Workflow.__init__`, which assigns `self.Steps` from `resolve_jobs(spec)` **before** calling `super().__init__`, because `Flow.__init__` at `librelane/flows/flow.py:492-501` passes `self.get_all_config_variables()` into `Config.load`, and that reads `self.Steps`. `TOOLS` changes which provider a job uses, hence which steps run, hence which variables exist. So the pre-pass stays, and `Workflow.__init__` calls it exactly where `StagedFlow.__init__` does.

**What changes is the key.** `TOOLS` is keyed by job id, not stage id, because a document may run one stage under several job names and `streamout` in fact does. `TOOLS: {magic_streamout: klayout}` runs the `streamout` stage's `klayout` provider under the job named `magic_streamout`. The job keeps the name the document gave it. This breaks existing configurations that set `TOOLS`, which the changelog has to say.

Three things are errors rather than accommodations.

- A key naming a job the document does not declare. `librelane/stages/resolution.py:166-185` already builds the rapidfuzz suggestion for this; reuse the same shape.
- A key naming a job that lists `steps` inline. An inline job has no provider to override, and pretending otherwise would silently do nothing.
- A list value. `multi_provider` is how one stage ran two tools, and two tools is now two jobs. The message says so.

`extract_tools`'s `_validate` still accepts a list, because `StagedFlow` needs it until phase 5. `Workflow` rejects it. Phase 5 can then narrow `_validate` itself.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_job.py`:

```python
def test_tools_overrides_the_provider_half_of_uses():
    from librelane.flows.job import resolve_jobs
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {"magic_streamout": {"uses": "streamout/magic"}},
        }
    )

    jobs = resolve_jobs(spec, {"magic_streamout": "klayout"})

    assert jobs["magic_streamout"].provider == "klayout"
    assert [step.id for step in jobs["magic_streamout"].steps] == [
        "KLayout.StreamOut"
    ]


def test_tools_naming_an_undeclared_job_is_rejected():
    from librelane.flows.job import resolve_jobs
    from librelane.flows.spec import FlowSpec
    from librelane.jobs import JobResolutionError

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"synthesis": {"uses": "synthesis/yosys"}}}
    )

    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(spec, {"synthesys": "yosys_vhdl"})

    assert "synthesys" in str(exc_info.value)
    assert "synthesis" in str(exc_info.value)


def test_tools_naming_an_inline_job_is_rejected():
    from librelane.flows.job import resolve_jobs
    from librelane.flows.spec import FlowSpec
    from librelane.jobs import JobResolutionError

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"xor": {"steps": ["KLayout.XOR"]}}}
    )

    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(spec, {"xor": "klayout"})

    assert "xor" in str(exc_info.value)
    assert "steps" in str(exc_info.value)


def test_tools_naming_a_list_is_rejected():
    from librelane.flows.job import resolve_jobs
    from librelane.flows.spec import FlowSpec
    from librelane.jobs import JobResolutionError

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"streamout": {"uses": "streamout/magic"}}}
    )

    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(spec, {"streamout": ["magic", "klayout"]})

    assert "streamout" in str(exc_info.value)
```

`JobResolutionError` is phase 3's rename of `StageResolutionError`, exported from
`librelane.jobs` alongside `Job`, `JobRegistry` and `JobDefinitionError`. It is
the class the implementation in Step 3 raises.

and append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_engine_reads_tools_before_resolving_its_configuration(
    minimal_design, mock_pdk
):
    """
    The pre-pass exists because the step set has to be known before the
    configuration is validated. This pins that TOOLS taken from the raw
    configuration mapping changes self.Steps.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {"magic_streamout": {"uses": "streamout/magic"}},
        }
    )

    flow = Workflow(
        spec,
        dict(minimal_design, TOOLS={"magic_streamout": "klayout"}),
        **mock_pdk,
    )

    assert [step.id for step in flow.Steps] == ["KLayout.StreamOut"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_job.py test/flows/test_engine.py -v`
Expected: the five new tests FAIL, four with `TypeError` on `resolve_jobs`'s second argument and one with an unknown-key error for `TOOLS`.

- [ ] **Step 3: Take the mapping in `resolve_jobs`**

In `librelane/flows/job.py`:

```python
def resolve_jobs(
    spec: FlowSpec,
    tools: Mapping[str, str | list[str]] | None = None,
) -> dict[str, ResolvedJob]:
    """
    Binds every ``JobSpec`` to its registered template and resolves its steps.

    Parameters
    ----------
    spec : FlowSpec
        A document that has already passed
        :func:`librelane.flows.spec_validation.validate_against_registry`.
    tools : Mapping[str, str | list[str]] | None
        The ``TOOLS`` mapping, keyed by **job
        id**. It overrides the provider half of that job's ``uses`` and never
        the stage half, so a job keeps the name the document gave it.

    Returns
    -------
    dict[str, ResolvedJob]
        One resolved job per document job, in declaration order.

    Raises
    ------
    JobResolutionError
        If ``tools`` names a job the document does not
        declare, a job that lists its steps inline, or a list of providers.
    """
    selections = dict(tools or {})
    _check_tool_keys(selections, spec)
    ...
```

and the checker, which mirrors `librelane/stages/resolution.py:166-185`:

```python
def _check_tool_keys(
    tools: Mapping[str, str | list[str]],
    spec: FlowSpec,
) -> None:
    for key, value in tools.items():
        job = spec.jobs.get(key)
        if job is None:
            suggestion = ""
            match = process.extractOne(
                key,
                list(spec.jobs),
                scorer=fuzz.partial_ratio,
                score_cutoff=80,
                processor=utils.default_process,
            )
            if match is not None:
                suggestion = f" Did you mean: '{match[0]}'?"
            raise JobResolutionError(
                f"TOOLS names '{key}', which is not a job of flow "
                f"'{spec.name}'.{suggestion} Declared jobs: "
                f"{sorted(spec.jobs)}."
            )
        if job.steps is not None:
            raise JobResolutionError(
                f"TOOLS names job '{key}', which lists its steps inline and "
                f"so has no provider to override. Only a job with a 'uses' "
                f"key can be re-pointed at another tool."
            )
        if not isinstance(value, str):
            raise JobResolutionError(
                f"TOOLS['{key}'] is a list. One job runs one provider; to run "
                f"two tools, declare two jobs with the same 'uses' stage and "
                f"different providers, as classic.yaml does for streamout."
            )
```

In the body that resolves a `uses` job, the provider becomes:

```python
        template_id, _, declared_provider = job_spec.uses.partition("/")
        template = Job.factory.get(template_id)
        assert template is not None, "checked by validate_against_registry"
        provider = selections.get(name) or declared_provider
        if not provider:
            # A bare 'uses' means the template's default. _check_uses already
            # rejected a template with no default provider, so this is
            # non-empty.
            provider = template.default_providers[0]
        registration = JobRegistry.get(template_id, provider)
        if registration is None:
            raise JobResolutionError(
                f"Job '{name}': no provider named '{provider}' is registered "
                f"for '{template_id}'. Registered providers: "
                f"{JobRegistry.providers(template_id)}."
            )
```

`Job`, `JobRegistry` and `JobResolutionError` come from `librelane.jobs`. They are
phase 3's renames of `Stage`, `StageRegistry` and `StageResolutionError`, and
phase 3 also frees the name `Job` by renaming phase 2's resolved dataclass to
`ResolvedJob`. Phase 2 wrote this body with `stage_id` and `stage` locals; they
are renamed here to `template_id` and `template`, which is the word this plan's
Global Constraints already use for the registered type, so nothing in the file
still says "stage" after phase 3's sweep.

`default_providers[0]` rather than a concatenation of all of them, because `multi_provider` is what two jobs replace, and `classic.yaml` names both providers explicitly. Phase 5 deletes `multi_provider` and this line becomes `template.default_provider`.

**This narrows what a bare `uses` runs, relative to what phase 1 validates it against, for the duration of phase 4.** Phase 1's `_providers_of` and phase 2's `_resolve` both take every entry of `default_providers`, on the reasoning that taking the first would silently drop the rest. Two templates have more than one, measured in this checkout:

```console
$ uv run python -c "
import librelane.steps
from librelane.stages.stage import Stage
for sid in sorted(Stage.factory.list()):
    st = Stage.factory.get(sid)
    if len(st.default_providers) > 1:
        print(sid, st.default_providers)
"
drc ('magic', 'klayout')
streamout ('magic', 'klayout')
```

No shipped document writes a bare `uses: drc` or `uses: streamout`. Only three of the eight name either template at all, `classic.yaml`, `vhdl_classic.yaml` and `chip.yaml`, and all three name their provider explicitly, as `uses: drc/magic` and `uses: streamout/klayout`, precisely because two providers are now two jobs. The five Open-In documents name neither. So nothing in this repository is affected. A hand-written document with a bare `uses: drc` would, for the duration of phase 4, be validated by phase 1 against both providers' contracts and then run only Magic's. Phase 5 Task 5 collapses `default_providers` to a single `default_provider` and the two re-converge. This is recorded rather than fixed here because fixing it would mean either weakening phase 1's check or reintroducing concatenation, and both are undone a phase later.

- [ ] **Step 4: Read `TOOLS` in `Workflow.__init__`**

Give `Workflow.__init__` an explicit signature rather than `*args, **kwargs`, because it now has to look at two of the arguments it forwards. **The signature is the only thing that changes.** Phase 2's body already assigns four things before `super().__init__`, and all four stay. `self.config_vars` and `self.name` are load-bearing and easy to lose in a rewrite, so the whole body is given here rather than a diff. `Flow.config_vars` defaults to `[]` at `librelane/flows/flow.py:443` and `Flow.__init__` at `:464` builds the `Config` from `self.get_all_config_variables()`, so without the `config_vars` line a document's `config:` block never reaches the configuration and `self.config[variable]` in `_pass_through_reason` raises `KeyError`. The same constructor derives `self.name` from the class name at `:483-484` when the instance has not set one, so without the `name` line every document would be called "Workflow" and its run directory would say so.

```python
    def __init__(
        self,
        spec: FlowSpec,
        config: AnyConfigs,
        *,
        config_override_strings: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        spec : FlowSpec
            The document to run. Validated against the registries
            here, so a document constructed in Python gets the same checks a
            loaded one does.
        config : AnyConfigs
            As :meth:`librelane.flows.Flow.__init__`.
        config_override_strings : Sequence[str] | None
            As
            :meth:`librelane.flows.Flow.__init__`. Read twice, once here for
            ``TOOLS`` and once by the loader, for the reason given on
            :mod:`librelane.jobs.tools`.
        """
        validate_against_registry(spec)
        self.spec = spec
        self.jobs = resolve_jobs(
            spec,
            self._selected_tools(config, config_override_strings),
        )
        self.Steps = [step for job in self.jobs.values() for step in job.steps]
        self.config_vars = [v.to_variable() for v in spec.config]
        self.name = spec.name
        super().__init__(
            config,
            config_override_strings=config_override_strings,
            **kwargs,
        )

    @staticmethod
    def _selected_tools(
        config: AnyConfigs,
        config_override_strings: Sequence[str] | None,
    ) -> Mapping[str, str | list[str]]:
        """
        Returns
        -------
        Mapping[str, str | list[str]]
            The ``TOOLS`` mapping, taken straight from an
            already-resolved configuration, or read out of the raw sources by
            the pre-pass.
        """
        if isinstance(config, Config):
            return dict(config.get("TOOLS") or {})
        sources = list(config) if isinstance(config, (list, tuple)) else [config]
        return extract_tools(
            sources,
            config_override_strings=config_override_strings,
        )
```

and declare the variable on the engine, replacing what `staged.py:115` declares today:

```python
    class Config(Flow.Config):
        TOOLS: Optional[dict[str, Union[str, list[str]]]] = variable(
            None,
            description=(
                "A mapping from job id to the provider (tool) implementing "
                "it, for example {'synthesis': 'genus'}. Only overrides need "
                "listing; an unnamed job uses the provider its 'uses' key "
                "names. Must be a literal mapping, as it is read before the "
                "configuration preprocessor runs, and so cannot come from the "
                "PDK."
            ),
        )
```

The annotation keeps `list[str]` so that a list reaches `_check_tool_keys` and is rejected with a message that explains the replacement, rather than being rejected by pydantic with a type error that does not.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest test/flows -v`
Expected: all pass

- [ ] **Step 6: Rewrite the documentation that calls a `TOOLS` key a stage id**

```bash
cd /home/kelvin/librelane
grep -rn "TOOLS" docs --include="*.md" | grep -v "docs/build"
```

Every hit that describes the key as a stage id becomes a job id, and the example becomes a job name from `classic.yaml`. Add a changelog entry under the breaking-change heading stating that `TOOLS` is now keyed by job id, that `TOOLS: {streamout: klayout}` becomes `TOOLS: {klayout_streamout: klayout}`, and that a list value is no longer accepted.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs Changelog.md
git commit -m "feat!: TOOLS selects a provider per job rather than per stage"
```

---

### Task 8: `--reproducible` on the workflow engine

**Files:**
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `_require_declared`, the target restriction, and the `_run_job(self, job, state_in, steps_run, deferred, forced)` signature, all from Task 6.
- Produces:
  - `Workflow.run(..., reproducible: str | None = None)`.
  - `Workflow._resolve_reproducible(name) -> tuple[str, int]`.
  - `_run_job(self, job, state_in, steps_run, deferred, forced, reproducible_at)`, Task 6's signature with one more required parameter, and the amended `get_tpe().submit(...)` call site that feeds it.
  - `_ReproducibleCreated`, a private control-flow exception carrying the path it wrote.

**Design notes the implementer needs:**

`--reproducible` survives as a CLI field at `librelane/cli/run.py:107` and is passed through at `:278`. Phase 2's `Workflow.run` ends in `**kwargs`, so after Task 11 the flag would be accepted and do nothing, and say nothing. That is a silent failure, which this repository forbids, so it is implemented here, before the CLI switches.

**What it does today**, from `librelane/flows/sequential.py:371-495`. The flow runs normally, reusing what it can, until it reaches the named step. At that step it calls `step.create_reproducible(step_dir / "reproducible")` and breaks out of the loop. Steps after it never run. Two configurations are refused rather than worked around, at `sequential.py:481-493`: a step gated off by a false variable, and a step named by `--skip`. Both messages name the step and say what to change. Resolution is case-insensitive with wildcards through `Filter`, and a near miss above the fuzzy cutoff is offered as a suggestion and not acted on.

**What it does on the graph.** The spec says it is unchanged in meaning and runs the ancestors of the step's job. That is exactly `--target <that job>`, so this reuses the restriction rather than adding a second one.

**Addressing a step.** Run directories are now `runs/<tag>/<job>/<n>-<slug>`, so the natural address for a step is `<job>/<step id>`. A bare step id is accepted when it is unambiguous. `OpenROAD.STAMidPNR` appears in four jobs of `classic.yaml`, so a bare `OpenROAD.STAMidPNR` is an error naming the four jobs and the `<job>/<step>` form. Guessing one of the four would be a fallback.

**Composing with `--target`.** Passing both is an error. `--reproducible` already answers the question "what should run", and two different answers is not something to resolve silently.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_reproducible_runs_the_ancestors_and_stops(counting_steps, minimal_design, mock_pdk, mocker):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, First, _ = counting_steps
    created = mocker.patch.object(First, "create_reproducible")
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="repro", reproducible="first/Test.EngineFirst")

    assert order == []
    assert created.call_count == 1


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_reproducible_for_a_step_in_several_jobs_is_ambiguous(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "once": {"steps": ["Test.EngineFirst"]},
                "twice": {"needs": ["once"], "steps": ["Test.EngineFirst"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="ambiguous", reproducible="Test.EngineFirst")

    message = str(exc_info.value)
    assert "once" in message
    assert "twice" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_reproducible_for_a_job_a_false_condition_stops_is_refused(
    counting_steps,
    minimal_design,
    mock_pdk,
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [
                {
                    "name": "RUN_FIRST",
                    "type": "bool",
                    "description": "x",
                    "default": False,
                }
            ],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="gated", reproducible="first/Test.EngineFirst")

    assert "RUN_FIRST" in str(exc_info.value)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_reproducible_and_target_together_are_refused(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowException) as exc_info:
        flow.start(
            tag="both",
            target=["first"],
            reproducible="first/Test.EngineFirst",
        )

    assert "--reproducible" in str(exc_info.value)
    assert "--target" in str(exc_info.value)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: the four new tests FAIL, three because `reproducible` lands in `**kwargs` and the run completes normally, and the `--target` one because no error is raised.

- [ ] **Step 3: Resolve the address**

In `librelane/flows/engine.py`:

```python
    def _resolve_reproducible(self, name: str) -> tuple[str, int]:
        """
        Parameters
        ----------
        name : str
            Either ``<step id>`` or ``<job id>/<step id>``. Step ids
            are matched case-insensitively, as the old ``--reproducible``
            matched them.

        Returns
        -------
        tuple[str, int]
            The job that runs the step, and the step's index within
            that job's sequence.

        Raises
        ------
        FlowException
            If no job runs that step, or if several do and the
            argument named no job. Naming one of several would run a step the
            user did not ask for.
        """
        job_id, separator, step_id = name.rpartition("/")
        if separator:
            self._require_declared([job_id], "--reproducible")
        wanted = step_id.lower()

        matches = [
            (candidate, index)
            for candidate, job in self.jobs.items()
            if not separator or candidate == job_id
            for index, step in enumerate(job.steps)
            if step.id.lower() == wanted
        ]
        if not matches:
            raise FlowException(
                f"--reproducible names step '{step_id}', which flow "
                f"'{self.spec.name}' does not run"
                + (f" in job '{job_id}'." if separator else ".")
            )
        if len(matches) > 1:
            raise FlowException(
                f"--reproducible names step '{step_id}', which runs in "
                f"{sorted({candidate for candidate, _ in matches})}. Name one "
                f"of them as '<job>/{step_id}'."
            )
        return matches[0]
```

- [ ] **Step 4: Wire it into `run`**

Add `reproducible: str | None = None` to `run`'s signature, after `skip`, and initialise `reproducible_at: tuple[str, int] | None = None` beside `forced`. Then, immediately after the `--target` block from Task 6:

```python
        if reproducible is not None:
            if target is not None:
                raise FlowException(
                    "--reproducible and --target both say what should run. "
                    "--reproducible already runs the named step's job and its "
                    "ancestors, so drop --target."
                )
            job_id, step_index = self._resolve_reproducible(reproducible)
            # Ahead of every skip test, so that a request for a step this
            # configuration would never execute is diagnosed rather than
            # silently discarded. This mirrors sequential.py:477-493.
            if job_id in skipped:
                raise FlowException(
                    f"Cannot create a reproducible for a step of job "
                    f"'{job_id}': it is named by --skip, so this run would "
                    f"never execute it. Drop it from --skip, or name another "
                    f"step."
                )
            reason = self._pass_through_reason(self.jobs[job_id], skipped=False)
            if reason is not None:
                raise FlowException(
                    f"Cannot create a reproducible for a step of job "
                    f"'{job_id}': {reason}, so this configuration would never "
                    f"execute it. Name another step, or change the condition."
                )
            selected = {job_id} | ancestors(edges, job_id)
            reproducible_at = (job_id, step_index)
```

`_run_job` has to be told where to stop, and Task 6 deliberately gave it a signature with no defaulted parameters, so that a future caller cannot forget one and silently get the wrong behaviour. Extend that signature rather than defaulting the new parameter:

```python
    def _run_job(
        self,
        job: ResolvedJob,
        state_in: State,
        steps_run: list[Step],
        deferred: list[str],
        forced: bool,
        reproducible_at: tuple[str, int] | None,
    ) -> State:
```

and amend the one call site, the `get_tpe().submit(...)` in phase 2's marking loop, which Task 6 already amended once:

```python
                    pending[
                        get_tpe().submit(
                            self._run_job,
                            job,
                            state_in,
                            steps_run,
                            deferred,
                            name in forced,
                            reproducible_at,
                        )
                    ] = name
```

Inside `_run_job`, stop at the requested index:

```python
        for index, cls in enumerate(job.steps):
            step = cls(config=self.config, state_in=current)
            step_dir = self.dir_for_job_step(job, index, step)
            if (job.id, index) == reproducible_at:
                step.create_reproducible(step_dir / "reproducible")
                raise _ReproducibleCreated(step_dir / "reproducible")
```

`_ReproducibleCreated` is a private exception `Workflow.run` catches, because the reproducible's job is a leaf of the restricted graph and there is nothing else to run once it is written. It is raised inside a worker, so it arrives at `future.result()` in the marking loop. Catch it there, beside the existing `except FlowError`, and leave the loop:

```python
                try:
                    state_out = future.result()
                    self._check_contract(self.jobs[name], state_out)
                except _ReproducibleCreated as created:
                    logger.success(f"Wrote a reproducible to '{created.path}'.")
                    return self._final_state(net, outputs), steps_run
                except FlowError as e:
                    ...
```

`_ReproducibleCreated` derives from `Exception` and not from `FlowError`, so the `except FlowError` clause below it cannot swallow it, and the ordering above makes that explicit rather than incidental. Do not let it escape `run`; a private control-flow exception reaching the CLI would be reported as a flow failure.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: all pass

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows/engine.py test/flows/test_engine.py
git commit -m "feat: --reproducible addresses a step by job on the workflow engine"
```

---

### Task 9: Port the run's final artefacts to the workflow engine

**Files:**
- Modify: `librelane/flows/engine.py`, `librelane/flows/flow.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `Workflow._final_state` from phase 2.
- Produces: `runs/<tag>/final` written by `Workflow.run`, and `Flow.final_state`, which `Flow._save_snapshot_ef` reads instead of guessing.

**Design notes the implementer needs:**

A step-order test and a gating test both pass for an engine that runs the right steps and then writes none of the files the old one wrote. This task closes that gap, and it lands before the command line switches over, so no shipped flow ever runs on an engine that quietly stops producing something.

The sweep that found these was mechanical. `Flow.start` is inherited unchanged, so everything it writes still happens: the run directory, `resolved.json` at `librelane/flows/flow.py:790-791`, and `flow.log`, `warning.log` and `error.log` from the sink stack at `:756-778`. What `SequentialFlow.run` does **after** its step loop is not inherited, and that is where all three findings are.

**One. The final snapshot.** `librelane/flows/sequential.py:597-601` writes `State.save_snapshot(self.run_dir / "final")`, which copies every view into a directory tree by design format and writes `metrics.csv` and `metrics.json` beside them. `test/flows/test_resume.py:104` excludes `final` when it lists a run's directories, which is the evidence that it is an expected member of every run directory rather than an accident. Phase 2's `Workflow.run` does not write it, and phase 2 recorded that as phase 4's to port.

The snapshot is written **before** the deferred-error raise, exactly as `sequential.py:597-607` orders it, so a run that defers an error still leaves a snapshot of what it produced. Preserve that order.

**This amends phase 2, on purpose.** Phase 2's Task 6 places `self._final_state(net, outputs)` after all three failure paths, the `if failures` raise, the stall check and the `if deferred` raise, so that it is reached only on a run that neither failed, stalled nor deferred. That is right for the first two and wrong for the third. A deferred error is by definition one the run continued past, so the run produced views, and `sequential.py` snapshots them. This task therefore moves `_final_state` and the `runs/<tag>/final` snapshot ahead of the `if deferred` raise and leaves the other two where phase 2 put them. Phase 2 has been told, and its Task 6 now records this ordering as superseding its own.

**Two. `_save_snapshot_ef` guesses the final state.** `librelane/flows/flow.py:951-971` takes `self.step_objects[-1]` and reads its `state_out`. On a list, the last step to run is the last step in the flow, so that guess is correct by accident. On a graph it is whichever leaf happened to finish last, and the flow's final state is the **join** of every leaf, which phase 2 computes in `Workflow._final_state`. So `--ef-save-views-to` would snapshot one arbitrary branch.

The fix belongs on `Flow` rather than on `Workflow`, because `Flow.start` already has the value. It receives `final_state` from `self.run(...)` at `flow.py:798` and returns it, without ever storing it. Store it, and read it in `_save_snapshot_ef`. That also removes a second latent bug on the old engine: `step_objects` accumulates across `start()` calls at `flow.py:808`, so after two runs `step_objects[-1]` belongs to the second run while the caller may be snapshotting the first.

**Three. The end-of-run report.** `sequential.py:609-615` logs how many steps were reused and how many executed, then `logger.success("Flow complete.")`. Both are user-facing output that a user would notice missing, and the reuse count is the only feedback the resume machinery gives.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_run_writes_a_final_snapshot(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="snapshot")

    assert flow.run_dir is not None
    assert (flow.run_dir / "final" / "metrics.json").exists()
    assert (flow.run_dir / "final" / "metrics.csv").exists()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_flow_remembers_the_state_it_returned(
    counting_steps, minimal_design, mock_pdk
):
    """
    Two leaves, so the last step to fire carries one branch's metrics and the
    flow's final state carries the join of both. _save_snapshot_ef must use the
    second, and on a list the two coincided.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "left": {"steps": ["Test.EngineFirst"]},
                "right": {"steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    state_out = flow.start(tag="two-leaves")

    assert flow.final_state is state_out
    assert {"first", "second"} <= set(state_out.metrics)
    assert flow.step_objects is not None
    assert set(flow.step_objects[-1].state_out.metrics) != set(state_out.metrics)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_run_reports_what_it_reused(
    caplog, counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    Workflow(spec, minimal_design, **mock_pdk).start(tag="reuse")
    caplog.clear()
    Workflow(spec, minimal_design, **mock_pdk).start(tag="reuse")

    assert "Reused 1 step(s)" in caplog.text
    assert "Flow complete." in caplog.text
```

`caplog` is the loguru-backed fixture at `test/conftest.py:46`, not pytest's built-in one.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: the first fails on the missing `final` directory, the second with `AttributeError` on `Flow.final_state`, the third because neither message is logged.

- [ ] **Step 3: Write the snapshot in `Workflow.run`**

At the end of `run`, after `_final_state` and **before** the deferred-error raise:

```python
        final = self._final_state(net, outputs)

        assert self.run_dir is not None
        try:
            final.save_snapshot(self.run_dir / "final")
        except Exception as error:
            raise FlowException(f"Failed to save final views: {error}")

        if reused_count:
            logger.info(
                f"Reused {reused_count} step(s) from a previous run; "
                f"executed {executed_count}."
            )

        if deferred:
            raise FlowError(
                "One or more deferred errors were encountered:\n"
                + "\n".join(deferred)
            )

        logger.success("Flow complete.")
        return final, steps_run
```

`reused_count` and `executed_count` are incremented in `_run_job` beside the existing `reusable_state` branch, on the same two paths `sequential.py:553` and `:582` count. `sequential.py` has a third increment, at `:538`, on its "before `--from`, so it must come from cache" branch. That branch has no counterpart here, because `--invalidate` forces a re-run rather than requiring an earlier result, so there is no third path to port.

- [ ] **Step 4: Store the final state on `Flow`**

In `librelane/flows/flow.py`, add the attribute beside `step_objects` at `:448`:

```python
    #: The state the last :meth:`start` returned. Assigned there rather than in
    #: a subclass's ``run`` so that every engine has it, and read by
    #: :meth:`_save_snapshot_ef`, which cannot ask the step list for it: on a
    #: graph the last step to finish is an arbitrary leaf, and the flow's final
    #: state is the join of all of them.
    final_state: State | None = None
```

Assign it in `start`, immediately after `self.step_objects += step_objects` at `flow.py:808`:

```python
                self.final_state = final_state
```

and rewrite the head of `_save_snapshot_ef`:

```python
        if (
            self.final_state is None
            or self.toolbox is None
            or self.config_resolved_path is None
        ):
            raise RuntimeError(
                "Flow was not run before attempting to save views in the "
                "Efabless format."
            )
        last_state = self.final_state
```

The `len(self.step_objects) == 0` early return at `flow.py:961-963` stays, because a flow that ran nothing still has nothing to copy, and so does the loop over `self.step_objects` further down, which copies per-step logs and reports and is genuinely per-step.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed. `test/flows/test_resume.py` and `test/flows/test_flow.py` both exercise `_save_snapshot_ef`'s neighbours on `SequentialFlow`, and the change is behaviour-preserving there because the last step of a list *is* the flow's final state.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: the workflow engine writes the final snapshot and reports its reuse"
```

---

### Task 10: `--explain` reports jobs

**Files:**
- Modify: `librelane/flows/explanation.py`, `librelane/flows/engine.py`, `librelane/flows/__init__.py`
- Test: `test/flows/test_explain.py`

**Interfaces:**
- Consumes: the selection logic from Tasks 6 and 8.
- Produces: `JobDisposition`, `Explanation.jobs`, and `Workflow.explain(target=None, skip=None) -> Explanation`.

**Design notes the implementer needs:**

**This task is purely additive.** `StepDisposition`, `Explanation.steps` and `Explanation.unselected_stages` all survive it untouched, and so do the existing tests in `test/flows/test_explain.py`. That is not caution, it is a hard requirement:

- `librelane/flows/sequential.py:23` imports `Explanation` and `StepDisposition`, and constructs `Explanation(tuple(dispositions), ())` at `sequential.py:369`.
- `librelane/flows/staged.py:41` imports `Explanation` and passes `unselected_stages=` at `staged.py:526`.
- `librelane/cli/run.py:42` imports `Explanation`, and `format_explanation` reads `explanation.steps` at `:192` and `explanation.unselected_stages` at `:201`.

Renaming or deleting any of those here makes `librelane.flows` unimportable and the suite fails at collection. The new fields therefore go **after** the existing ones and carry defaults, so `Explanation(tuple(dispositions), ())` keeps working positionally.

Phase 5 is where `StepDisposition`, `unselected_stages`, `format_explanation` and the `SequentialFlow` explain tests are deleted, together with the engine that produces them. The controller has been asked to confirm plan 5 does that.

Mechanisms on the job side are `condition`, `skip` and `not-in-target`.

- [ ] **Step 1: Write the failing tests**

**Append** to `test/flows/test_explain.py`. Do not replace the file; its existing tests cover `SequentialFlow.explain`, which still ships.

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_explain_names_the_condition_that_stops_a_job(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [
                {
                    "name": "RUN_FIRST",
                    "type": "bool",
                    "description": "x",
                    "default": False,
                }
            ],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    first = explanation.jobs[0]
    assert first.job_id == "first"
    assert first.will_run is False
    assert first.mechanism == "condition"
    assert "RUN_FIRST" in first.reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_explain_marks_jobs_outside_the_target_subgraph(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(
        target=["first"]
    )

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is True
    assert by_id["second"].mechanism == "not-in-target"
    assert by_id["second"].needs == ("first",)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_explain_still_answers_for_a_sequential_flow(MetricIncrementer, minimal_design, mock_pdk):
    """
    SequentialFlow.explain ships until phase 5 deletes the engine that backs
    it. This task must not disturb it.
    """
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    explanation = Dummy(minimal_design, **mock_pdk).explain()

    assert [d.step_id for d in explanation.steps] == ["Test.MetricIncrementer"]
    assert explanation.jobs == ()
```

`test/flows/test_explain.py` already imports `flow_module`, `sequential_module` and `step_module`. It also defines `_MINIMAL_DESIGN` at `test/flows/test_explain.py:23-26` and `_MOCK_PDK` at `:27-32` as module constants. Delete both in this edit and rewrite the file's existing tests to take the `minimal_design` and `mock_pdk` fixtures, so the file has one source for each and no module-level constant that a sibling `conftest.py` could shadow.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest test/flows/test_explain.py -v`
Expected: the two new document tests FAIL with `AttributeError` on `Explanation.jobs`; the third and every existing test pass.

- [ ] **Step 3: Extend `explanation.py` additively**

```python
@dataclass(frozen=True)
class JobDisposition:
    """
    Why one job will or will not run, for one prospective invocation.

    Parameters
    ----------
    job_id : str
        The document's job key.
    needs : tuple[str, ...]
        The job's declared incoming edges, so the table can show
        the graph without a second query.
    will_run : bool
        Whether this invocation would execute the job's steps.
    reason : str
        A sentence naming the cause, suitable for printing.
    mechanism : str | None
        ``None`` when :attr:`will_run` is true, and otherwise
        one of ``condition``, ``skip`` or ``not-in-target``.
    """

    job_id: str
    needs: tuple[str, ...]
    will_run: bool
    reason: str
    mechanism: str | None
```

and add the field to `Explanation`, after the existing two:

```python
    steps: tuple[StepDisposition, ...]
    unselected_stages: tuple[str, ...]
    #: One entry per job, in topological order. Empty for a SequentialFlow,
    #: which has jobs no more than a Workflow has stages. Both halves live here
    #: until phase 5 deletes the first.
    jobs: tuple[JobDisposition, ...] = ()
```

Export `JobDisposition` from `librelane/flows/__init__.py` beside `StepDisposition`.

- [ ] **Step 4: Add `Workflow.explain`**

Mirror `run`'s selection logic without executing anything, returning one `JobDisposition` per job in `topological_order`:

```python
    def explain(
        self,
        *,
        target: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
    ) -> Explanation:
        """
        Parameters
        ----------
        target : Iterable[str] | None
            As :meth:`run`.
        skip : Iterable[str] | None
            As :meth:`run`.

        Returns
        -------
        Explanation
            One entry per job, in topological order, stating whether
            the job will run under this configuration and these arguments, and
            if not, which mechanism excluded it.

        Resume is deliberately not reported, for the reason given on
        :meth:`librelane.flows.SequentialFlow.explain`. A resume verdict depends
        on content fingerprints of files that later jobs in the same run will
        rewrite, so it cannot be known before the run.
        """
        edges = self.spec.edges()
        selected = set(self.jobs)
        if target is not None:
            targets = list(target)
            self._require_declared(targets, "--target")
            selected = set()
            for name in targets:
                selected.add(name)
                selected |= ancestors(edges, name)
        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")

        dispositions: list[JobDisposition] = []
        for job_id in topological_order(edges):
            job = self.jobs[job_id]
            needs = tuple(job.needs)
            if job_id not in selected:
                dispositions.append(
                    JobDisposition(
                        job_id, needs, False, "not in the --target subgraph",
                        "not-in-target",
                    )
                )
                continue
            reason = self._pass_through_reason(job, job_id in skipped)
            if reason is None:
                dispositions.append(
                    JobDisposition(job_id, needs, True, "will run", None)
                )
            else:
                mechanism = "skip" if job_id in skipped else "condition"
                dispositions.append(
                    JobDisposition(job_id, needs, False, reason, mechanism)
                )
        return Explanation(steps=(), unselected_stages=(), jobs=tuple(dispositions))
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: the workflow engine explains its jobs"
```

---

### Task 11: Point the command line at documents

**Files:**
- Modify: `librelane/cli/run.py`, `librelane/cli/options.py:153-195`
- Test: `test/cli/test_entry_points.py`, `test/flows/test_explain.py`

**Interfaces:**
- Consumes: `Flow.factory.get_document` (Task 5), `Workflow.run`'s new arguments (Tasks 6 and 8), `Explanation.jobs` (Task 10).
- Produces: `select_flow(request) -> FlowSpec`, `format_job_explanation(explanation) -> str`, `FlowRequest.target` and `FlowRequest.invalidate`.

**Design notes the implementer needs:**

This is the atomic switch, and it is one task because every part of it has to land together. Replacing `--from` with `--invalidate` while the CLI still builds a `SequentialFlow` would put `invalidate=` into that flow's `**kwargs` and lose it silently. Removing the `isinstance(flow, SequentialFlow)` guard at `librelane/cli/run.py:252-258` before the CLI builds a `Workflow` would break `--explain`. Rewriting `format_explanation` in place would break the tests that still cover the sequential path.

`format_explanation` at `librelane/cli/run.py:178` is therefore left alone and `format_job_explanation` is added beside it. Phase 5 deletes the first with the engine that feeds it.

- [ ] **Step 1: Write the failing test**

Append to `test/cli/test_entry_points.py`, following the file's existing invocation pattern:

```python
def test_explain_prints_a_job_table(tmp_path):
    from librelane.cli.run import format_job_explanation
    from librelane.flows import Explanation, JobDisposition

    rendered = format_job_explanation(
        Explanation(
            steps=(),
            unselected_stages=(),
            jobs=(
                JobDisposition("lint", (), True, "will run", None),
                JobDisposition(
                    "synthesis", ("lint",), True, "will run", None
                ),
                JobDisposition(
                    "klayout_streamout",
                    ("ir_drop",),
                    False,
                    "'RUN_KLAYOUT_STREAMOUT' is false",
                    "condition",
                ),
            ),
        )
    )

    assert "JOB" in rendered
    assert "NEEDS" in rendered
    assert "klayout_streamout" in rendered
    assert "condition" in rendered
    assert "Stages contributing no steps" not in rendered
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest test/cli/test_entry_points.py -v`
Expected: FAIL with `ImportError` on `format_job_explanation`

- [ ] **Step 3: Replace the command-line options**

In `librelane/cli/options.py`, delete `FromOption` and `ToOption` and add:

```python
TargetOption = Annotated[
    list[str] | None,
    typer.Option(
        "--target",
        "-T",
        help="Run this job and everything it transitively needs, and nothing else. May be specified multiple times.",
        rich_help_panel=WORKFLOW_OPTIONS,
    ),
]
InvalidateOption = Annotated[
    list[str] | None,
    typer.Option(
        "--invalidate",
        "-F",
        help="Treat this job and every job downstream of it as having no reusable result, forcing them to re-run. Use this when something a resume key cannot hash has changed, such as a CAD tool binary or an edited script.",
        rich_help_panel=WORKFLOW_OPTIONS,
    ),
]
```

Rename the panel constant `SEQUENTIAL_OPTIONS = "Sequential flow controls"` to `WORKFLOW_OPTIONS = "Workflow controls"` and update `SkipOption`, `ReproducibleOption` and `ExplainOption` to use it. Update `SkipOption`'s help to say "job ID" rather than "step ID", `ReproducibleOption`'s to say `<job>/<step ID>`, and `ExplainOption`'s to drop "Requires a sequential flow."

- [ ] **Step 4: Update `FlowRequest`**

In `librelane/cli/run.py`, replace the `frm: str | None` and `to: str | None` fields at `:102-103` with:

```python
    target: tuple[str, ...]
    invalidate: tuple[str, ...]
```

Update every construction site and every pass-through into `flow.start`. `grep -rn "frm\b\|\bto=" librelane/cli/` finds them all. `run_included_example` at `librelane/cli/run.py:297` builds a `FlowRequest` with `reproducible=None` at `:325` and needs the two new fields.

- [ ] **Step 5: Change `select_flow` to return a document**

```python
def select_flow(request: FlowRequest) -> FlowSpec:
    """
    Picks the flow document named by ``--flow``, else by the configuration
    file's ``meta`` object, else Classic.

    Returns
    -------
    FlowSpec
        The document to run.
    """
    target_flow: FlowSpec | None = Flow.factory.get_document("Classic")
    ...
```

Every failure path keeps its current shape. An unknown name is an error listing `Flow.factory.list()`, which Task 5 made return documents as well, and a non-string `meta.flow` is the error already at `:127-134`. Replace the two `Flow.factory.get(...)` lookups at `:135` and `:145` with `Flow.factory.get_document(...)`.

- [ ] **Step 6: Construct a `Workflow` at the call site**

At `librelane/cli/run.py:219`, where `start_flow` instantiates the selected class:

```python
        flow = Workflow(
            select_flow(request),
            list(request.config_files),
            pdk_root=request.pdk.pdk_root,
            pdk=request.pdk.pdk,
            scl=request.pdk.scl,
            pad=request.pdk.pad,
            config_override_strings=list(request.config_overrides),
            design_dir=request.design_dir,
        )
```

and at `:271-281`, pass the new arguments through:

```python
        state_out = flow.start(
            tag=request.tag,
            last_run=request.last_run,
            target=list(request.target) or None,
            invalidate=list(request.invalidate) or None,
            skip=request.skip,
            with_initial_state=initial_state,
            reproducible=request.reproducible,
            _force_run_dir=request.force_run_dir,
            overwrite=request.overwrite,
        )
```

- [ ] **Step 7: Add `format_job_explanation` and switch `--explain` to it**

```python
def format_job_explanation(explanation: Explanation) -> str:
    """
    Renders the job half of an :class:`librelane.flows.Explanation` as a
    fixed-width table.

    Parameters
    ----------
    explanation : Explanation
        What the workflow reported.

    Returns
    -------
    str
        The table, without a trailing newline.
    """
    width = max((len(d.job_id) for d in explanation.jobs), default=0)
    needs_width = max(
        (len(" ".join(d.needs) or "-") for d in explanation.jobs), default=0
    )
    lines = [
        f"{'JOB'.ljust(width)}  RUN  MECHANISM     "
        f"{'NEEDS'.ljust(needs_width)}  REASON"
    ]
    for disposition in explanation.jobs:
        mark = "yes" if disposition.will_run else "no "
        mechanism = (disposition.mechanism or "").ljust(13)
        needs = (" ".join(disposition.needs) or "-").ljust(needs_width)
        lines.append(
            f"{disposition.job_id.ljust(width)}  {mark}  {mechanism} "
            f"{needs}  {disposition.reason}"
        )
    return "\n".join(lines)
```

At `librelane/cli/run.py:252-268`, delete the `isinstance(flow, SequentialFlow)` guard, which is dead now that every flow the CLI builds is a `Workflow`, and call the new formatter:

```python
    if request.explain:
        typer.echo(
            format_job_explanation(
                flow.explain(
                    target=list(request.target) or None,
                    skip=list(request.skip),
                )
            )
        )
        raise typer.Exit(0)
```

Drop `SequentialFlow` from the import at `librelane/cli/run.py:42` if nothing else in the module uses it, and add `Workflow` and `FlowSpec`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed. Tests in `test/cli/` referring to `--from` or `--to` must be updated to the new options in the same commit; `grep -rn "\-\-from\|\-\-to\b" test/` finds them.

- [ ] **Step 9: Run the flow end to end by hand**

Run: `uv run librelane --explain librelane/examples/spm/config.yaml`
Expected: a job table with a `NEEDS` column and no `Stages contributing no steps` footer.

Run: `uv run librelane --target signoff_sta librelane/examples/spm/config.yaml`
Expected: the run stops after signoff STA, and no `magic_streamout`, `klayout_streamout`, `magic_drc`, `klayout_drc` or `lvs` directory exists under the run tag.

Run: `uv run librelane --reproducible floorplan/OpenROAD.Floorplan librelane/examples/spm/config.yaml`
Expected: the run stops at the floorplan job and writes `runs/<tag>/floorplan/1-openroad-floorplan/reproducible`.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: run workflow documents from the command line"
```

---

### Task 12: The document's `with` block layers into the configuration

**Files:**
- Modify: `librelane/config/config.py` (`Config.load` at `:502`, the source list at `:591-634`)
- Modify: `librelane/flows/flow.py:489-501`
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_document_values.py`

**Interfaces:**
- Consumes: `FlowSpec.values` from phase 1, `Workflow` from phase 2.
- Produces:
  - `Config.load(..., flow_values: Mapping[str, Any] | None = None)`. When given, it becomes the first `ConfigSource` in the layered list, named `<flow document>`.
  - `Flow.values: dict[str, Any]`, a class attribute defaulting to `{}`, which `Workflow.__init__` assigns from `spec.values` before calling `super().__init__`.

**Context the implementer needs:**

`Config.load` builds an ordered `list[ConfigSource]` at `config.py:591-634` and hands it to `layer_mappings` at `:636`, which merges in order and records the last source to write each top-level key in `LayeredMapping.provenance`. The design configuration files are that list today. Inserting the document's values at the **front** makes the design override the document, which is the required precedence.

The PDK is merged separately. `Config.__load_dict` seeds `mutable` from `__get_pdk_config` at `config.py:740` and then applies the layered design mapping on top with `mutable.update(design_values)` at `config.py:763`. So a value in the document beats a PDK default without any further change, and the full order comes out as PDK, then SCL, then the document, then the design, then `--config-override`.

Do not fold the document values into `configs_validated`. That loop also computes `meta` and `file_design_dir`, and the document is neither a design directory nor a source of `meta`.

One consequence worth knowing rather than testing for. `preprocess_dict` at `config.py:752-760` runs over the merged mapping, so `dir::` and `expr::` work inside a document's `with` block, resolved against the design's `DESIGN_DIR` like any other value.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_document_values.py`:

```python
# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import pytest

from librelane.flows import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _spec():
    from librelane.flows.spec import FlowSpec, JobSpec

    return FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_document_value_is_used_when_the_design_is_silent(minimal_design, mock_pdk):
    from librelane.config import Config
    from librelane.flows.engine import Workflow

    workflow = Workflow(_spec(), minimal_design, **mock_pdk)

    assert workflow.config["FP_SIZING"] == "absolute"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_design_overrides_a_document_value(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow

    workflow = Workflow(
        _spec(),
        dict(minimal_design, FP_SIZING="relative"),
        **mock_pdk,
    )

    assert workflow.config["FP_SIZING"] == "relative"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_document_value_naming_an_undeclared_variable_is_rejected(minimal_design, mock_pdk):
    from librelane.config import InvalidConfig
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(
        name="T",
        values={"NOT_A_VARIABLE": 1},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    with pytest.raises(InvalidConfig) as exc_info:
        Workflow(spec, minimal_design, **mock_pdk)

    assert "NOT_A_VARIABLE" in str(exc_info.value)
    assert "<flow document>" in str(exc_info.value)
```

The three tests go through `Workflow` rather than calling `Config.load` directly, because the point being pinned is that a document's `with` block reaches the loader, and a direct `Config.load(flow_values=...)` call would pass while `Workflow` still dropped them. `minimal_design` and `mock_pdk` are the fixtures phase 2 adds to `test/flows/conftest.py`. Take them as arguments rather than reinventing a PDK.

The third test needs no new code beyond the plumbing. `validate_mapping` runs with `on_unknown_key="error"` and a `provenance` map, verified by:

```console
$ uv run pytest test/flows/test_document_values.py -k undeclared -q
```

which reports `<flow document>:NOT_A_VARIABLE: Unknown key 'NOT_A_VARIABLE' provided.` once the plumbing is in. The provenance prefix is what makes the diagnostic point at the document rather than at the design, and `config.py:646` already writes `<command line>` the same way, so this follows an established convention rather than inventing one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_document_values.py -v`
Expected: the first two FAIL with `KeyError` or a validation error on `FP_SIZING`, and the third FAILs because nothing raises.

- [ ] **Step 3: Add the parameter to `Config.load`**

Add `flow_values: Mapping[str, Any] | None = None` to the keyword-only part of the signature, and seed the source list before the `configs_validated` loop at `config.py:591`:

```python
        sources: list[ConfigSource] = []
        if flow_values is not None:
            sources.append(
                ConfigSource(dict(flow_values), "<flow document>", "mapping")
            )
        meta = Meta()
        for config_validated in configs_validated:
```

Document the parameter in the NumPy `Parameters` block, stating the precedence in one line: the document layers under the design and over the PDK.

- [ ] **Step 4: Carry the values from the document to the loader**

Add `values: dict[str, Any] = {}` to `Flow` beside `Steps` at `librelane/flows/flow.py:442`. In `Flow.__init__`, pass `flow_values=self.values` to `Config.load` at `:492-501`. In `Workflow.__init__`, assign `self.values = dict(spec.values)` before calling `super().__init__`. This is a fifth line added to the four Task 7 Step 4 already lists, not a replacement for any of them. `self.spec`, `self.jobs`, `self.Steps`, `self.config_vars` and `self.name` all stay, and all five precede `super().__init__`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_document_values.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest test -m all`
Expected: no new failures. The eight shipped documents set no values, so every existing test layers an empty document.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: a workflow document supplies configuration values"
```

---

### Task 13: `--explain` reports variable reach

**Files:**
- Modify: `librelane/flows/explanation.py`, `librelane/flows/engine.py`, `librelane/config/config.py`, `librelane/cli/run.py`, `librelane/cli/options.py`
- Test: `test/flows/test_explain.py`

**Interfaces:**
- Consumes: `Explanation` and `Workflow.explain` from Task 10, `Config.load(flow_values=...)` from Task 12.
- Produces:
  - `VariableDisposition` frozen dataclass with `name: str`, `value: Any`, `origin: str`, `universal: bool`, `reach: tuple[str, ...]`.
  - `Explanation.variables: tuple[VariableDisposition, ...]`, defaulting to `()`.
  - `Config.provenance`, a read-only property.
  - `format_variable_explanation(explanation) -> str` and `--explain-variables`.

**Context the implementer needs:**

A variable's reach has never been visible anywhere, which is exactly why a per-job `with` block was rejected in the spec. This task makes it visible.

Reach is every job for a universal variable, because `Step.get_all_config_variables` seeds its dict from that list unconditionally. For every other variable it is the jobs whose steps declare it in `Step.config_vars`. Set `universal` rather than listing 24 job ids, because a universal variable reaching everything is a different fact from a variable that happens to be read by every job.

**The list is called `universal_flow_config_variables` everywhere it is imported.** `librelane/config/__init__.py:43` reads `from librelane.config.flow import flow_common_variables as universal_flow_config_variables`, and the alias is the only name the package exports; `from librelane.config import flow_common_variables` raises `ImportError`. `librelane/flows/flow.py:56` and `librelane/steps/step/__init__.py:3` both import the alias. Use the alias in `engine.py` too.

`origin` comes from `LayeredMapping.provenance`, which `layer_mappings` already records per top-level key. `Config.load` builds the map at `config.py:636-646` and hands it to `validate_mapping` for diagnostics, but never keeps it. A variable no source wrote has no provenance entry, and its origin is the string `default`.

**Two notes on writing these tests.**

First, `mock_variables` replaces the universal variable list with `test/conftest.py:228`'s `COMMON_FLOW_VARS`, which does **not** contain `DIE_AREA`. Measured in this checkout, the real list holds 78 names including `DIE_AREA` and excluding `DIODE_ON_PORTS`, and `COMMON_FLOW_VARS` is the other way round. A test asserting that `DIE_AREA` is universal therefore fails under the very fixture it needs to run at all. Use a variable that is in `COMMON_FLOW_VARS`, such as `DIODE_ON_PORTS`, and pin the real `DIE_AREA` behaviour with a comment rather than an assertion.

Second, **`mock_variables` only patches the modules it is handed.** `test/conftest.py:231-257` loops over `patch_in_objects` and substitutes any attribute named `flow_common_variables` or `universal_flow_config_variables` that the object actually has. `librelane.config.config` is appended for free; nothing else is. The reader added in Step 5 lives in `engine.py`, so `engine` has to be in the list or `engine.py`'s own imported name keeps the real 78-name list while `Flow.get_all_config_variables` uses the substituted one, and `test_explain_reports_a_universal_variable_as_reaching_everything` fails on `DIODE_ON_PORTS` with `universal` false. Every one of the five tests below therefore uses `@mock_variables([flow_module, engine_module, step_module])`, and the file's import line at `test/flows/test_explain.py:16` gains `engine as engine_module`.

The step-declared variables below were checked against the real classes:

```console
$ uv run python -c "
import librelane.steps
from librelane.steps import Step
for sid in ['OpenROAD.Floorplan', 'OpenROAD.GlobalPlacement', 'Yosys.Synthesis']:
    own = {v.name for v in Step.factory.get(sid).config_vars}
    print(sid, 'FP_SIZING' in own, 'FP_CORE_UTIL' in own, 'SYNTH_STRATEGY' in own)
"
```

`FP_SIZING` is declared by `OpenROAD.Floorplan` alone, `FP_CORE_UTIL` by `OpenROAD.Floorplan` and `OpenROAD.GlobalPlacement`, and `SYNTH_STRATEGY` by `Yosys.Synthesis` alone.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_explain.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_a_universal_variable_as_reaching_everything(
    minimal_design, mock_pdk
):
    """
    DIODE_ON_PORTS stands in for DIE_AREA here. mock_variables replaces the
    universal variable list with test/conftest.py's COMMON_FLOW_VARS, which
    contains DIODE_ON_PORTS and not DIE_AREA, and the property under test is
    membership of that list rather than the identity of the variable.

    engine_module is in the list because the reader is in engine.py.
    mock_variables patches only the modules it is handed, so without it
    engine.py keeps the real list and this assertion fails.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(name="T", jobs={"floorplan": JobSpec(uses="floorplan")})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()
    variable = next(
        v for v in explanation.variables if v.name == "DIODE_ON_PORTS"
    )

    assert variable.universal
    assert set(variable.reach) == {job.job_id for job in explanation.jobs}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, engine_module, step_module])
def test_explain_scopes_a_step_variable_to_the_jobs_that_read_it(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(
        name="T",
        jobs={
            "synthesis": JobSpec(uses="synthesis/yosys"),
            "floorplan": JobSpec(needs=["synthesis"], uses="floorplan"),
        },
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()
    strategy = next(
        v for v in explanation.variables if v.name == "SYNTH_STRATEGY"
    )

    assert not strategy.universal
    assert strategy.reach == ("synthesis",)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_a_variable_read_by_several_jobs(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(
        name="T",
        jobs={
            "floorplan": JobSpec(uses="floorplan"),
            "global_placement": JobSpec(
                needs=["floorplan"], uses="global_placement"
            ),
        },
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()
    util = next(v for v in explanation.variables if v.name == "FP_CORE_UTIL")

    assert not util.universal
    assert set(util.reach) == {"floorplan", "global_placement"}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_the_document_as_the_origin_of_a_document_value(
    minimal_design,
    mock_pdk,
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()
    sizing = next(v for v in explanation.variables if v.name == "FP_SIZING")

    assert sizing.value == "absolute"
    assert sizing.origin == "<flow document>"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, engine_module, step_module])
def test_a_variable_no_source_wrote_reports_default_as_its_origin(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec, JobSpec

    spec = FlowSpec(name="T", jobs={"floorplan": JobSpec(uses="floorplan")})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()
    sizing = next(v for v in explanation.variables if v.name == "FP_SIZING")

    assert sizing.origin == "default"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_explain.py -v`
Expected: the five new tests FAIL with `AttributeError` on `Explanation.variables`

- [ ] **Step 3: Add `VariableDisposition`**

```python
@dataclass(frozen=True)
class VariableDisposition:
    """
    One configuration variable's value, where it came from, and which jobs can
    read it.

    Parameters
    ----------
    name : str
        The variable's name.
    value : Any
        Its resolved value.
    origin : str
        The layer that supplied the value, or ``default`` if none
        did.
    universal : bool
        True when the variable is in
        :data:`librelane.config.universal_flow_config_variables` and so is
        readable by every step regardless of what any step declares.
    reach : tuple[str, ...]
        The jobs that can read it. Every job when
        :attr:`universal` is set.
    """

    name: str
    value: Any
    origin: str
    universal: bool
    reach: tuple[str, ...]
```

Add `variables: tuple[VariableDisposition, ...] = ()` to `Explanation`, after `jobs`, and export the class from `librelane/flows/__init__.py`.

- [ ] **Step 4: Keep the provenance map on `Config`**

`Config.load` computes `provenance` at `config.py:638-646` and passes it into `__load_dict`, which forwards it to `validate_mapping` for diagnostics and then discards it. Carry it onto the object instead. `Config.__init__` takes it as a keyword argument alongside `meta` and `diagnostics`, stores it as a private mapping, and exposes it:

```python
    @property
    def provenance(self) -> Mapping[str, str]:
        """
        Returns
        -------
        Mapping[str, str]
            The name of the source that last wrote each top-level
            key. Keys no source wrote are absent, which is what makes their
            origin ``default``.
        """
        return self.__provenance
```

- [ ] **Step 5: Compute reach in `Workflow.explain`**

Import the list into `engine.py` as `from librelane.config import universal_flow_config_variables`, the alias `librelane/config/__init__.py:43` establishes and the only name the package exports.

```python
    def _variable_dispositions(self) -> tuple[VariableDisposition, ...]:
        universal = {
            variable.name for variable in universal_flow_config_variables
        }
        readers: dict[str, list[str]] = {}
        for job_id, job in self.jobs.items():
            for step in job.steps:
                for variable in step.config_vars:
                    readers.setdefault(variable.name, []).append(job_id)

        every_job = tuple(self.jobs)
        dispositions = []
        for variable in self.get_all_config_variables():
            is_universal = variable.name in universal
            dispositions.append(
                VariableDisposition(
                    name=variable.name,
                    value=self.config[variable.name],
                    origin=self.config.provenance.get(variable.name, "default"),
                    universal=is_universal,
                    reach=every_job
                    if is_universal
                    else tuple(dict.fromkeys(readers.get(variable.name, []))),
                )
            )
        return tuple(dispositions)
```

`dict.fromkeys` deduplicates while keeping declaration order, because a job's steps commonly declare the same variable more than once. Return it from `explain` as `variables=self._variable_dispositions()`.

- [ ] **Step 6: Render it in `librelane/cli/run.py`**

Add `format_variable_explanation`, printing a second table under the job table with columns `VARIABLE`, `VALUE`, `ORIGIN` and `REACH`. `REACH` shows `universal, read by all N jobs` when `universal` is set and a comma-separated job list otherwise. Suppress rows whose origin is `default`, so the table shows what somebody actually chose.

Add `--explain-variables` to `librelane/cli/options.py`, in the `WORKFLOW_OPTIONS` panel, to show every row including defaults. A variable sitting at its default is exactly what somebody debugging an unexpected value wants to see, and it is also the noisiest thing to print unasked.

- [ ] **Step 7: Run the tests, lint and commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: --explain reports configuration variable reach and origin"
```

---

### Task 14: `get_help_md` reads the document's jobs

**Files:**
- Modify: `librelane/flows/engine.py`, `librelane/cli/help.py`, `docs/_ext/generate_configvar_docs.py`, `docs/_templates/generate_configvar_docs/flows.md`
- Test: `test/jobs/test_providers_vendor.py`, `test/flows/test_documents.py`

**Interfaces:**
- Consumes: `Flow.factory.get_document` (Task 5), `resolve_jobs(spec, tools)` (Task 7), `validate_against_registry` (phase 1), `JobRegistry.providers` (`librelane.jobs`).
- Produces:
  - `Workflow.get_help_md(self, myst_anchors: bool = False) -> str`, the instance form, reading `self.spec` and `self.jobs`.
  - `Workflow.help_md_for_document(spec: FlowSpec, myst_anchors: bool = False) -> str`, the static form, for the three callers that have no configuration.
  - `_document_help_md(spec, jobs, myst_anchors)` in `librelane/flows/engine.py`, the one renderer both call.

**This is the task phase 5 points at.** Phase 5's Task 4 deletes `Flow.Steps` and must delete `Flow.get_help_md` with it. This task is where the replacement is defined, so phase 5 deletes the old one and references this task by name rather than deferring to "whatever the document-based equivalent is by then".

**Design notes the implementer needs:**

`Flow.get_help_md` is declared at `librelane/flows/flow.py:508` and reads `Self.Steps` at `:564-566`, inside `if len(Self.Steps):`. `StagedFlow.get_help_md` at `librelane/flows/staged.py:549` extends it with the `#### Stages` table, built from `describe_stages` at `:530` and `JobRegistry.providers(...)` at `:565`. Both halves die with the classes, and both halves have to come back on the document side.

**It has to read the job set, so it cannot stay a classmethod.** A document's step list, its providers and its per-job structure are all facts about the resolved jobs, and a class attribute has none of them. So the renderer takes a resolved job mapping.

**It must not require a configuration.** This is measured, not assumed. All three callers construct nothing:

- `librelane/cli/help.py:38`, `librelane help Classic`, which the user runs without a design.
- `docs/_templates/generate_configvar_docs/flows.md:33`, `${flow.get_help_md(myst_anchors=True)}`, driven by `docs/_ext/generate_configvar_docs.py:65-77`, which builds the flow list from `Flow.factory.list()` during a Sphinx build.
- `test/jobs/test_providers_vendor.py:31` and `:39`.

`Workflow.__init__` needs a configuration, because it reads `TOOLS` out of it. `resolve_jobs(spec)` with no `tools` argument does not. That is the whole reason there are two entry points rather than one, and they are not two implementations. `get_help_md` renders the jobs a constructed workflow actually resolved, `TOOLS` overrides included; `help_md_for_document` resolves the document's declared providers and renders those. Both call the same renderer with a different job mapping.

**The template id is on the spec, not on the resolved job.** `ResolvedJob` carries `provider` but not the id of the template it came from, so the "Template" column reads `spec.jobs[job_id].uses`, and the renderer therefore takes both the spec and the jobs. `ResolvedJob.provider` is `None` for a job that lists its `steps` inline, which is how the renderer tells the two kinds apart.

**The docs generator needs the same switch.** `docs/_ext/generate_configvar_docs.py:72-76` calls `flow_factory.get(key)` for every `key` in `flow_factory.list()` and filters on `__doc__ is not None`. Task 5 made `list()` return documents and classes together, and during phase 4 every name is both, so `get(key)` still returns a class and the docs still build. Phase 5 deletes the classes and `get(key)` starts returning `None` for every name. Switch the generator here, in the same task that gives it something to switch to, rather than leaving phase 5 a broken docs build to discover.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_documents.py`:

```python
def test_help_for_a_document_lists_its_jobs_and_their_providers():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Jobs" in help_md
    assert "| `detailed_routing` | `detailed_routing` | `openroad` |" in help_md
    assert "| `magic_streamout` | `streamout` | `magic` |" in help_md
    assert "| `xor` | inline steps | | |" in help_md


def test_help_for_a_document_lists_its_steps():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Included Steps" in help_md
    assert "`Yosys.Synthesis`" in help_md


def test_help_for_a_document_declares_its_own_variables():
    from librelane.flows.engine import Workflow

    help_md = Workflow.help_md_for_document(_document("classic.yaml"))

    assert "#### Flow-specific Configuration Variables" in help_md
    assert "RUN_LINTER" in help_md
```

The three assertions in the first test mirror `test/flows/test_staged.py:1022`'s `test_help_lists_stages_and_their_providers`, which phase 5 deletes with `StagedFlow`. `post_route_opt` has no row here, because it is not a job of any document, which is the same fact that test recorded as `| post_route_opt | none selected |`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: the three new tests FAIL with `AttributeError: type object 'Workflow' has no attribute 'help_md_for_document'`

- [ ] **Step 3: Write the renderer**

In `librelane/flows/engine.py`. It needs three names the module does not import yet: `textwrap`, `Variable` from `librelane.config`, and `JobRegistry` from `librelane.jobs`. `slugify` arrives with phase 2's marking loop and `Mapping` with Task 7's `_selected_tools`, so neither import is new here.

```python
def _document_help_md(
    spec: FlowSpec,
    jobs: Mapping[str, ResolvedJob],
    myst_anchors: bool,
) -> str:
    """
    Renders a workflow document's help as Markdown.

    Parameters
    ----------
    spec : FlowSpec
        The document. Supplies the name, the description, the
        declared configuration variables and each job's ``uses``.
    jobs : Mapping[str, ResolvedJob]
        The document's resolved jobs. Supplies each
        job's selected provider and its steps.
    myst_anchors : bool
        Emit MyST anchors and cross-references, for the
        documentation build. Off for terminal output.

    Returns
    -------
    str
        The rendered Markdown.
    """
    anchor = f"(flow-{slugify(spec.name, lower=True)})=" if myst_anchors else ""
    result = textwrap.dedent(
        f"""\
        {anchor}
        ### {spec.name}

        {spec.description}

        #### Using from the CLI

        ```sh
        librelane --flow {spec.name} [...]
        ```

        #### Importing

        ```python
        from librelane.flows import Flow
        from librelane.flows.engine import Workflow

        {spec.name} = Flow.factory.get_document("{spec.name}")
        ```
        """
    )

    config_vars = [declared.to_variable() for declared in spec.config]
    if config_vars:
        if myst_anchors:
            result += f"\n({slugify(spec.name, lower=True)}-config-vars)=\n"
        result += "\n#### Flow-specific Configuration Variables\n"
        result += Variable._render_table_md(
            config_vars,
            myst_anchor_owner_id=spec.name if myst_anchors else None,
        )
        result += "\n"

    result += "\n#### Jobs\n\n"
    result += (
        "Set the `TOOLS` configuration variable to change the tool used for "
        "any of these. The key is the job id in the left-hand column. See "
        "[Swapping Tools](./swapping_tools.md).\n\n"
    )
    result += "| Job | Template | Provider | Alternatives |\n"
    result += "| --- | --- | --- | --- |\n"
    for job_id, job in jobs.items():
        if job.provider is None:
            result += f"| `{job_id}` | inline steps | | |\n"
            continue
        template_id = (spec.jobs[job_id].uses or job_id).partition("/")[0]
        others = [
            provider
            for provider in JobRegistry.providers(template_id)
            if provider != job.provider
        ]
        others_cell = ", ".join(f"`{name}`" for name in others) if others else "none"
        result += (
            f"| `{job_id}` | `{template_id}` | `{job.provider}` | {others_cell} |\n"
        )

    result += "\n#### Included Steps\n\n"
    for job_id, job in jobs.items():
        result += f"* `{job_id}`\n"
        for step in job.steps:
            implementation = step.get_implementation_id()
            if myst_anchors:
                result += (
                    f"  * [`{step.id}`](./step_config_vars.md#step-"
                    f"{slugify(implementation, lower=True)})\n"
                )
            elif implementation != step.id:
                result += f"  * `{step.id}` (implementation: `{implementation}`)\n"
            else:
                result += f"  * `{step.id}`\n"
    return result
```

`(spec.jobs[job_id].uses or job_id)` is not a fallback. It is phase 1's implicit rule spelled out: a job that declares neither `uses` nor `steps` means the template its own id names, which `_require_implementation` already checked, so the two forms are one declared form with two spellings.

- [ ] **Step 4: Add the two entry points**

On `Workflow`:

```python
    def get_help_md(self, myst_anchors: bool = False) -> str:
        """
        Parameters
        ----------
        myst_anchors : bool
            Emit MyST anchors and cross-references.

        Returns
        -------
        str
            Rendered Markdown help for this workflow, describing the
            jobs it actually resolved, so a ``TOOLS`` override is visible in the
            provider column.
        """
        return _document_help_md(self.spec, self.jobs, myst_anchors)

    @staticmethod
    def help_md_for_document(spec: FlowSpec, myst_anchors: bool = False) -> str:
        """
        Renders a document's help without constructing a workflow.

        Parameters
        ----------
        spec : FlowSpec
            The document to describe.
        myst_anchors : bool
            Emit MyST anchors and cross-references.

        Returns
        -------
        str
            Rendered Markdown help, describing the providers the
            document declares. A configuration is not needed and is not read,
            so ``TOOLS`` plays no part.
        """
        validate_against_registry(spec)
        return _document_help_md(spec, resolve_jobs(spec), myst_anchors)
```

- [ ] **Step 5: Point `librelane help` at documents**

In `librelane/cli/help.py`, replace the `Flow.factory.get` lookup at `:38`:

```python
    if target_flow := Flow.factory.get_document(step_or_flow):
        help_md = Workflow.help_md_for_document(target_flow)
    elif target_step := Step.factory.get(step_or_flow):
        help_md = target_step.get_help_md()
```

and add `from librelane.flows.engine import Workflow` to the imports.

Run: `uv run librelane help Classic`
Expected: the job table, with `synthesis` showing `yosys` and `yosys_vhdl` as its alternative.

- [ ] **Step 6: Point the documentation build at documents**

In `docs/_ext/generate_configvar_docs.py`, the flow list at `:72-76` becomes documents:

```python
                    flows=[
                        flow_factory.get_document(key)
                        for key in flow_factory.list()
                        if flow_factory.get_document(key) is not None
                    ],
```

and `docs/_templates/generate_configvar_docs/flows.md:33` becomes:

```
${Workflow.help_md_for_document(flow, myst_anchors=True)}
```

with `Workflow` passed into `template.render(...)` beside `slugify`. The `__doc__ is not None` filter goes, because a document's `description` defaults to the empty string rather than to `None` and every one of the eight sets it.

- [ ] **Step 7: Migrate the vendor opt-in test**

`test/jobs/test_providers_vendor.py` (today `test/stages/test_providers_vendor.py`, moved by phase 3's `git mv test/stages test/jobs`) calls `Flow.factory.get("Classic").get_help_md()` at `:31` and `:39`, inside a throwaway subprocess. It still passes during phase 4, because the `Classic` class is still registered, and it breaks in phase 5. Migrate it here, in the task that supplies the replacement. Replace the two calls and their surrounding lookups:

```python
        import librelane.steps  # noqa: F401  populates Step.factory
        from librelane.jobs import JobRegistry
        from librelane.flows import Flow
        from librelane.flows.engine import Workflow

        classic = Flow.factory.get_document("Classic")

        before = set(JobRegistry.providers("synthesis"))
        assert before == {"yosys", "yosys_vhdl"}, before
        assert not ({"dc", "fc", "genus"} & before), before

        before_help = Workflow.help_md_for_document(classic)
        assert "`dc`" not in before_help, "vendor provider leaked before opt-in"

        import librelane.jobs.providers_vendor  # noqa: F401  (the opt-in)

        after = set(JobRegistry.providers("synthesis"))
        assert {"dc", "fc", "genus"} <= after, after

        after_help = Workflow.help_md_for_document(classic)
        assert "`dc`" in after_help, "vendor provider did not appear after opt-in"

        print("OK")
```

The docstring above it explains that the registries are process-wide singletons and that both halves therefore run in one throwaway subprocess. That reasoning is unchanged and the docstring stays, with `StageRegistry` reading `JobRegistry`. What changes is only where the help comes from. The assertion still works for the same reason it worked before: `dc` reaches the rendered help through the Alternatives column, which lists `JobRegistry.providers("synthesis")` minus the selected provider, and `classic.yaml` selects `yosys`.

Measured against this checkout, before the opt-in `JobRegistry.providers("synthesis")` is `['yosys', 'yosys_vhdl']`, and `synthesis` is the only template with more than one provider registered by default.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed.

- [ ] **Step 9: Build the documentation**

Run: `uv run make -C docs html`
Expected: `docs/build/html/reference/flows.html` exists and contains a Jobs table for Classic. This is the only check that the Sphinx extension change is right, because nothing in the pytest suite drives it.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat: a workflow document renders its own help"
```

---

## What this phase does not do

`SequentialFlow`, `StagedFlow` and `Flow`-as-a-base still exist, and `test_documents.py` still compares each document against the Python flow it replaces. That comparison is what makes phase 5's deletions safe, so it must survive until phase 5 removes both sides together.

The following survive this phase deliberately, and phase 5 owns their deletion.

- `StepDisposition`, `Explanation.steps` and `Explanation.unselected_stages`, imported by `sequential.py:23`, `staged.py:41` and `cli/run.py:42`.
- `format_explanation` in `librelane/cli/run.py`, and the `SequentialFlow` tests in `test/flows/test_explain.py` that cover it, including `test_an_unselected_stage_is_reported_separately`.
- `StagedFlow.Config.TOOLS` at `staged.py:115`, superseded by `Workflow.Config.TOOLS` but still read by `StagedFlow`.
- `extract_tools`'s acceptance of a list value, which `StagedFlow` needs while `multi_provider` exists.
- `Job.multi_provider`, `Job.optional` and `Job.using`.
- The whole of `librelane/stages/resolution.py`. Task 7 explains why nothing in it survives once `StagedFlow` goes, including `resolve`, `Resolution`, `ResolvedSpan` and `ProviderContract`.
- `Flow.get_help_md` at `librelane/flows/flow.py:508` and `StagedFlow.get_help_md` at `staged.py:549`. Task 14 supplies the replacement, `Workflow.get_help_md` and `Workflow.help_md_for_document`, and moves every caller onto it, so phase 5 deletes both old ones with no caller left to repoint. That is the corresponding half of phase 5's Task 4, which lists `get_help_md` as kept while deleting the `Flow.Steps` it reads.
- `test/flows/test_staged.py:1022`'s `test_help_lists_stages_and_their_providers`, whose coverage Task 14 reproduces on the document side in `test/flows/test_documents.py`.

`Magic.DRC` continues to read KLayout's GDSII, faithfully. Changing that is a behaviour change with its own justification and its own regression run, and it does not belong in a migration whose claim is equivalence.

One check genuinely weakens, and it is the spec's decision rather than this plan's. `StagedFlow._preflight_views` walked the resolved step list with the gating variables evaluated, so a configuration that switched off a producer whose consumer still ran failed before any tool was invoked. Phase 1's `_check_requirements_are_reachable` reasons over the declared graph and does not evaluate conditions, so that class of mistake now surfaces as a missing-input error at run time rather than at load. The spec calls the replacement "strictly stronger" because it is reachability rather than a linear scan, which is true of the structural half and not of the gating half. Recovering the gating half needs the condition variables resolved at load, which needs the configuration, which needs the step set. That is the same circularity `librelane/stages/tools.py` documents, and unpicking it is not part of this migration.
