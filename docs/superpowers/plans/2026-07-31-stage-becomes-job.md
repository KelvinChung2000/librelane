# Stage Becomes Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the stage and the job into one concept named `Job`, so that the taxonomy, the registry and the workflow document all use a single word.

**Architecture:** A mechanical rename with one naming decision. `Stage` becomes `Job` and `StageRegistry` becomes `JobRegistry`, because a job is what the document, the `TOOLS` key and the documentation all call it. Phase 2's resolved-unit dataclass, which currently occupies the name `Job`, is renamed to `ResolvedJob`. Both engines consume the renamed registry at once, so nothing is dual-maintained.

**Tech Stack:** Python 3.11+, pytest, uv, `git mv` and scripted rewrites for the bulk renames.

## Global Constraints

- This is phase 3 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phases 1 and 2 having landed.
- The full test suite must stay green at every commit. `StagedFlow` still exists and still works; it is deleted in phase 5.
- This phase changes names, not behaviour. No check is added, removed or relaxed. If a test's expected message changes, only the word "stage" becomes "job" in it.
- Never add a fallback. In particular, do **not** leave `Stage = Job` or `StageRegistry = JobRegistry` aliases behind. A rename with a compatibility alias is two names for one thing, which is the defect this phase exists to remove.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

## The naming decision, and why

The spec says a job and a stage are one dataclass. In implementation they are two types, because one is a library entry and the other is a bound instance, the way a class and an instance are two things. `Job` is the registry entry: the 27 taxonomy templates, the thing `TOOLS` keys on, the thing `uses:` names. `ResolvedJob` is what the engine runs: a `Job` bound to a document's `needs`, `source` and `conditions`, with its steps resolved from the selected provider.

This is not the duality the spec removes. That duality was two *authoring* concepts, `Stage.x` entries and bare steps sitting in one list with different gating rules. A document author writes only jobs. `ResolvedJob` is an internal type no author names.

The word "stage" is retired everywhere: types, variables, error classes, messages, docstrings and documentation.

## The fate of `resolve()`, `ResolvedSpan` and `extract_tools()`

This section exists for the phase 5 agent, whose deletion plan needs to know it and could not tell from the rest of this document. Read `librelane/stages/resolution.py` before touching it; `resolve()` and `ResolvedSpan`, discussed below, are on that file's public surface. `extract_tools()`, also discussed below, is the neighbouring case in `librelane/stages/tools.py`.

Phase 3 does neither of the two things a mechanical rename could plausibly do to `librelane/stages/resolution.py`. It does not merge its logic into anything, and it does not replace it with a fresh implementation. It is a straight rename-in-place move, exactly like every other file in the rename table above: `git mv librelane/stages librelane/jobs` in Task 2 Step 1 carries the whole file over unopened, and Task 2's later steps then apply `Stage` → `Job` to its contents the same as to every other file the sweep touches. `resolve()`, `ResolvedSpan`, `Resolution`, `ProviderContract`, `_selection_for`, `_registration_for` and `_check_tool_keys` all land in `librelane/jobs/resolution.py` with identical logic. Nothing is dropped from it in this phase, span apparatus included: `ResolvedSpan`, `Resolution.spans`, and the `_job_span`/`_job_provider` tags (renamed here from `_stage_span`/`_stage_provider`, see Task 2's context above) all survive fully intact through phase 3 and phase 4, because they are exactly what `StagedFlow` needs to build its boundary map, and `StagedFlow` keeps running until phase 5.

Phase 2's `resolve_jobs()` in `librelane/flows/job.py` is a separate function on a separate module, and this phase does not fold `resolve()` into it or vice versa. This was checked directly against phase 2's plan (`docs/superpowers/plans/2026-07-31-workflow-net-and-engine.md`): `resolve_jobs()` has its own private `_resolve(name, spec)` helper operating on `FlowSpec`/`JobSpec`, the new document model, and it imports `Stage`/`StageRegistry` (renamed `Job`/`JobRegistry` by this phase) directly rather than calling into `resolve()` or reusing `_selection_for`/`_registration_for`/`_check_tool_keys`. The two functions coexist, unmerged, because `resolve()` is what `StagedFlow` calls and `resolve_jobs()` is what `Workflow` calls, and only one of those two engines is new.

Consequence for phase 5: `librelane/jobs/resolution.py` is not dead at the end of this phase — it is exactly as alive as `librelane/stages/resolution.py` is today, just renamed and relocated, and it stays alive through phase 4 for the same reason. But it also does not become part of the new engine at any point; nothing in `resolve_jobs()` or `Workflow` calls anything in it. It goes dead in one step, not by attrition: when phase 5 deletes `StagedFlow` and its sole caller in `librelane/flows/staged.py`, every remaining reference to `resolve()`, `_selection_for`, `_registration_for`, `_check_tool_keys`, `ResolvedSpan`, `Resolution` and `ProviderContract` goes with it, and nothing outside `librelane/jobs/resolution.py` constructs any of those types by then. Phase 5 should delete `librelane/jobs/resolution.py` outright, as one file, at the same time it deletes `StagedFlow` — not migrate parts out of it first, and not delete only `ResolvedSpan`/`Resolution.spans` while keeping the rest of the module on the theory that `resolve()`'s `steps`/`unselected` output feeds the new engine's job graph construction. That theory does not hold: `resolve_jobs()` never calls `resolve()`, as verified above by reading phase 2's plan directly, so there is no such feed to preserve.

`extract_tools()` in `librelane/stages/tools.py` gets the ordinary rename-move treatment, nothing more: relocated to `librelane/jobs/tools.py` by the same `git mv`, same function name (it never contained the word "stage"), same public signature, same behaviour. Internally, `StageResolutionError` becomes `JobResolutionError` (Task 2 Step 2) and the `stage` parameter and loop variable in `_reject_construct` and `_validate` become `job` (Task 2 Step 4, which now says explicitly that this is a code rename, not prose). It has no dependency on `resolve()`, `ResolvedSpan`, or `StagedFlow`, so it is unaffected by whatever phase 5 does with the rest of this file's former neighbour, and it does not go dead at any point in this plan: it is generic over the key name, so both the old engine and the new one are expected to keep calling it, under the same name, from `librelane.jobs.tools` instead of `librelane.stages.tools`.

## Rename table

| Before | After |
| --- | --- |
| `librelane/stages/` (package) | `librelane/jobs/` |
| `librelane/stages/stage.py` | `librelane/jobs/job.py` |
| `librelane/stages/taxonomy.py` | `librelane/jobs/taxonomy.py` |
| `librelane/stages/registry.py` | `librelane/jobs/registry.py` |
| `librelane/stages/resolution.py` | `librelane/jobs/resolution.py` |
| `librelane/stages/tools.py` | `librelane/jobs/tools.py` |
| `class Stage` | `class Job` |
| `Stage.factory` / `StageFactory` | `Job.factory` / `JobFactory` |
| `class StageRegistry` | `class JobRegistry` |
| `StageError` | `JobDefinitionError` |
| `StageResolutionError` | `JobResolutionError` |
| `StageContractError` | `JobContractError` (already introduced in phase 2's `engine.py`; see Task 4) |
| `Registration.stage` | `Registration.job` |
| `Registration.tagged_steps`'s `_stage_span` | `_job_span` |
| `Registration.tagged_steps`'s `_stage_provider` | `_job_provider` |
| `librelane/flows/job.py::Job` (phase 2) | `ResolvedJob` |
| `librelane/flows/job.py::resolve_jobs` | unchanged, now returns `dict[str, ResolvedJob]` |
| `test/stages/` | `test/jobs/` |

`Stage.using`, `Stage.multi_provider` and `Stage.optional` are **not** touched here. They are deleted in phase 5, and deleting them now would break `StagedFlow`, which still runs the shipped flows until phase 4.

---

### Task 1: Rename phase 2's resolved type

**Files:**
- Modify: `librelane/flows/job.py`, `librelane/flows/engine.py`
- Test: `test/flows/test_job.py`, `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `Job`, `resolve_jobs` from phase 2's `librelane/flows/job.py`. Phase 2 landed with `Job.source: dict[str, str]` (a view id or a metric name, never `DesignFormat`, because the join rule is uniform over views and metrics and a metric key like `design__lvs_error__count` has no `DesignFormat`) and `Job.conditions: tuple[str, ...]` (renamed from the singular `condition: str | None`, because the `if` key takes a conjunction — phase 1's `parse_condition(text: str) -> tuple[str, ...]` produces it, phase 2's `resolve_jobs` calls that once per job and stores the result). This phase only renames the class; it does not touch either field's type or name a second time, so `ResolvedJob.source` and `ResolvedJob.conditions` keep exactly the shape phase 2 gives them.
- Produces: `ResolvedJob` with identical fields to phase 2's `Job`, `source: dict[str, str]` and `conditions: tuple[str, ...]` included, and `resolve_jobs(spec: FlowSpec) -> dict[str, ResolvedJob]`.

This goes first so that the name `Job` is free before Task 2 claims it. Doing it in the other order means a window where two different `Job` classes exist.

- [ ] **Step 1: Rewrite the references**

```bash
cd /home/kelvin/librelane
sed -i 's/\bJob\b/ResolvedJob/g' librelane/flows/job.py
sed -i 's/\bJob\b/ResolvedJob/g' librelane/flows/engine.py
sed -i 's/\bJob\b/ResolvedJob/g' test/flows/test_job.py
```

`engine.py` also contains `JobContractError`, which `\bJob\b` does not match because the word boundary requires a non-word character after `Job`. Confirm:

```bash
grep -n "ResolvedJobContractError" librelane/flows/engine.py
```

Expected: no output. If there is any, revert that substring by hand.

- [ ] **Step 2: Update the docstring**

In `librelane/flows/job.py`, replace the class docstring's first line so it names the new type:

```python
@dataclass(frozen=True)
class ResolvedJob:
    """
    A document's job declaration bound to a registered template.

    Never written by hand. ``needs``, ``source`` and ``conditions`` come from
    the document; ``requires``, ``provides``, ``metrics`` and ``steps`` come
    from the template, or from the steps themselves for an inline job.
    """
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest test/flows -v`
Expected: every test that passed before still passes, same count.

- [ ] **Step 4: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 5: Commit**

```bash
git add librelane/flows/job.py librelane/flows/engine.py test/flows/test_job.py test/flows/test_engine.py
git commit -m "refactor: rename the resolved job type to ResolvedJob"
```

---

### Task 2: Move the package and rename the types

**Files:**
- Move: `librelane/stages/` to `librelane/jobs/`, `librelane/stages/stage.py` to `librelane/jobs/job.py`, `test/stages/` to `test/jobs/`
- Modify: every file importing from `librelane.stages`; the sixteen vendor tool modules under `librelane/steps/` that carry a `"stage":` registration key (listed below) even though they never import `librelane.stages` by that name; `test/flows/test_staged.py` and `test/steps/test_vendor_cadence.py`, `test/steps/test_vendor_signoff.py`, `test/steps/test_vendor_synopsys_pnr.py`, none of which move.

**Interfaces:**
- Produces: `librelane.jobs.Job`, `librelane.jobs.JobRegistry`, `librelane.jobs.JobDefinitionError`, `librelane.jobs.JobResolutionError`, `Registration.job`.

**Context the implementer needs:**

`Job` uses a metaclass, `StageMetaclass`, whose `__getattr__` is what makes `Stage.synthesis` resolve through the factory. Rename it to `JobMetaclass`. Its `__getattr__` raises `AttributeError("Unknown Stage attribute", key, Self)`; the first element of that tuple becomes `"Unknown Job attribute"`.

`Registration.tagged_steps` sets `"_stage_span": (self.stage,)` and `"_stage_provider": self.provider`. Both tag names are read in exactly two places outside the registry, at `librelane/flows/staged.py:240` and `librelane/flows/staged.py:647`. Rename the tags and both readers together, or `StagedFlow` silently loses its boundary map and the stage-contract tests fail with a confusing message rather than a rename error.

The registry entry has a second identity beyond `Registration.stage`: every `REGISTRATIONS` list is a list of dict literals with a literal `"stage": "..."` key, splatted into `StageRegistry.register(**entry)`. That key is not the attribute `Registration.stage`; it is a string dict key, and no identifier-based sed pattern matches it. Measured in this checkout, before any rename: 29 occurrences in `librelane/stages/providers.py`, and 70 spread across the sixteen vendor tool modules `providers_vendor.py` aggregates from, all under `librelane/steps/` (`calibre.py` 2, `conformal.py` 1, `dc.py` 1, `fc.py` 18, `fm.py` 1, `genus.py` 1, `icc2.py` 17, `icv.py` 2, `innovus.py` 17, `pegasus.py` 2, `pt.py` 2, `quantus.py` 1, `starrc.py` 1, `tempus.py` 2, `vc_spyglass.py` 1, `voltus.py` 1). `librelane/stages/providers_vendor.py` and `librelane/stages/tools.py` themselves carry none of these keys directly; do not spend time editing them for this. Downstream, some tests read a `REGISTRATIONS` entry as a dict rather than through the dataclass, with the same lowercase key: `entry["stage"]` or `registration["stage"]`, 4 times in `test/stages/test_providers.py`, once in `test/stages/test_providers_vendor.py`, 16 times in `test/steps/test_vendor_cadence.py`, once in `test/steps/test_vendor_signoff.py`, and 6 times in `test/steps/test_vendor_synopsys_pnr.py`. The last three of those files live under `test/steps/`, not `test/stages/`, so they are not moved by Step 1 and are easy to overlook.

The keyword form has the same blind spot at its call sites: `StageRegistry.register(stage=...)` appears 10 times in `test/stages/test_registry.py` and, easy to miss because it is outside the package being moved, 3 times in `test/flows/test_staged.py`.

A third blind spot is the import path, not a dict key: `from librelane.stages.stage import ...` appears in 10 files (`librelane/stages/__init__.py`, `registry.py`, `resolution.py`, `taxonomy.py`, `tools.py`, and `librelane/flows/staged.py`, plus `librelane/steps/innovus.py`, `quantus.py`, `tempus.py`, `voltus.py`). `s/librelane\.stages/librelane.jobs/g` turns this into `from librelane.jobs.stage import ...`, which is a `ModuleNotFoundError` once `stage.py` becomes `job.py`; the `.stage` submodule component needs its own substitution.

- [ ] **Step 1: Move the files**

```bash
cd /home/kelvin/librelane
git mv librelane/stages librelane/jobs
git mv librelane/jobs/stage.py librelane/jobs/job.py
git mv test/stages test/jobs
```

- [ ] **Step 2: Rewrite every reference**

The sweep excludes `docs/superpowers/`, which holds the specs and plans describing this work, including this plan itself and the historical record of earlier phases (measured: 7 files there match the pattern below, and a mechanical sweep must not rewrite its own source of truth). `docs/source/` is the only documentation tree this step touches; scoping to it also matches what Task 5 later re-sweeps.

```bash
cd /home/kelvin/librelane
FILES=$(grep -rl "librelane\.stages\|from \.\.stages\|from \.stages\|\bStage\b\|StageRegistry\|StageError\|StageResolutionError\|StageContractError\|_stage_span\|_stage_provider" librelane test docs/source --include="*.py" --include="*.md")
sed -i \
  -e 's/librelane\.stages/librelane.jobs/g' \
  -e 's/librelane\.jobs\.stage\b/librelane.jobs.job/g' \
  -e 's/from \.\.stages/from ..jobs/g' \
  -e 's/from \.stages/from .jobs/g' \
  -e 's/\bStageRegistry\b/JobRegistry/g' \
  -e 's/\bStageMetaclass\b/JobMetaclass/g' \
  -e 's/\bStageFactory\b/JobFactory/g' \
  -e 's/\bStageResolutionError\b/JobResolutionError/g' \
  -e 's/\bStageContractError\b/JobContractError/g' \
  -e 's/\bStageError\b/JobDefinitionError/g' \
  -e 's/\b_stage_span\b/_job_span/g' \
  -e 's/\b_stage_provider\b/_job_provider/g' \
  -e 's/\bStage\b/Job/g' \
  $FILES
grep -rn "librelane\.jobs\.stage\b\|librelane\.stages\.stage\b" librelane test docs/source --include="*.py" --include="*.md"
```

Order matters. `StageRegistry` and the error classes are rewritten before the bare `Stage`, or `\bStage\b` would not match them anyway but `StageRegistry` would become `JobRegistry` only by luck of ordering. Keeping the specific names first makes the intent explicit. The `librelane.jobs.stage` line must run immediately after the `librelane.stages` → `librelane.jobs` line and before anything else, since it repairs the submodule path left dangling by that first substitution (`stage.py` becomes `job.py`, not `librelane/jobs/stage.py`). The final `grep` must print nothing; any hit is an import that still points at a module that no longer exists.

- [ ] **Step 3: Rename the `stage` field, the registration dict keys, and every call site that names either as a string**

`\bStage\b` does not match the lowercase field, the `"stage":` dict-key literal, the `entry["stage"]` subscript, the `registration.stage` attribute read, or the `stage=` keyword argument at call sites outside `librelane/jobs/`. All five need their own substitution, run after Step 2's move and sweep:

```bash
cd /home/kelvin/librelane

# Registration.stage itself.
sed -i \
  -e 's/\bstage=/job=/g' \
  -e 's/registration\.stage\b/registration.job/g' \
  -e 's/\bstage: str\b/job: str/g' \
  -e 's/self\.stage\b/self.job/g' \
  librelane/jobs/registry.py librelane/jobs/resolution.py

# The "stage": dict-key literal every REGISTRATIONS entry carries, splatted
# into JobRegistry.register(**entry). Computed, not hand-listed, so a
# seventeenth vendor module added later is not silently skipped.
DICT_KEY_FILES=$(grep -rlE '"stage"[[:space:]]*:' librelane/jobs librelane/steps --include="*.py")
sed -i -e 's/"stage":/"job":/g' $DICT_KEY_FILES

# stage= keyword arguments at call sites the move left behind, and the
# registration.stage attribute reads test/jobs/test_registry.py makes on the
# Registration instances StageRegistry.register(...) returns (measured: 2).
sed -i \
  -e 's/\bstage=/job=/g' \
  -e 's/registration\.stage\b/registration.job/g' \
  test/jobs/test_registry.py test/flows/test_staged.py

# entry["stage"] / registration["stage"] subscript reads some tests use
# instead of going through the dataclass.
sed -i -e 's/\["stage"\]/["job"]/g' \
  test/jobs/test_providers.py test/jobs/test_providers_vendor.py \
  test/steps/test_vendor_cadence.py test/steps/test_vendor_signoff.py \
  test/steps/test_vendor_synopsys_pnr.py

grep -rn '"stage"\|\bstage=\|\["stage"\]\|\.stage\b' librelane/jobs librelane/steps librelane/flows test/jobs test/flows test/steps --include="*.py"
```

Expected from the final `grep`: no output. Anything it prints is a missed reference; fix it by hand before continuing. This is a stricter check than the identifier-based one it replaces: it looks for the four string/attribute forms directly, so it would have caught the `providers.py` defect this step exists to fix, rather than only checking that `\.stage\b` and `stage=` are gone from the two files the old check happened to name.

- [ ] **Step 4: Sweep the remaining hits**

```bash
cd /home/kelvin/librelane
grep -rin "stage" librelane test docs/source --include="*.py" --include="*.md" | grep -v "\.pyc"
```

`docs/superpowers/` stays excluded here for the same reason Step 2 excludes it: this plan and its siblings live there, and a case-insensitive sweep would rewrite this very sentence.

Most remaining hits are a docstring, comment, error message or documentation sentence, and get rewritten by hand so they say "job"; there is no automated rewrite for these, because "stage" appears in phrases such as "a named phase of a flow" that need rewording rather than substitution. But not all of them are prose. `STAGE_ORDER` (measured: 20 occurrences — `librelane/stages/__init__.py` 2, `librelane/stages/taxonomy.py` 1, `test/stages/test_taxonomy.py` 15, `test/stages/test_providers.py` 2) is a real exported constant name, case-insensitively matched here because none of Step 2's or Step 3's case-sensitive patterns touch all-caps identifiers; rename it to `JOB_ORDER` at its one definition and every import and use, not just its prose mentions. Likewise `librelane/stages/tools.py` reads `TOOLS` with a local parameter and loop variable literally named `stage`; rename those too, consistently across definition and use, the same way any other code identifier is renamed — "rewrite so it says job" covers code, not only sentences.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures. Test *counts* must be identical to before this task; a change means a test was lost in the move.

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Verify no alias was left behind**

```bash
cd /home/kelvin/librelane
grep -rn "^Stage\b\|^StageRegistry\b\|Stage = \|StageRegistry = " librelane --include="*.py"
```

Expected: no output. A compatibility alias would defeat the purpose of the phase.

- [ ] **Step 8: Commit**

```bash
git add -A librelane test docs
git commit -m "refactor!: a stage is a job"
```

Note: `git add -A` is scoped to `librelane test docs` deliberately. The repository has deliberately untracked personal dotfiles, and a bare `git add -A` fails on `.bash_profile`.

---

### Task 3: Point the workflow modules at the renamed registry

**Files:**
- Modify: `librelane/flows/spec_validation.py`, `librelane/flows/job.py`
- Test: `test/flows/test_spec_validation.py`, `test/flows/test_job.py`

Task 2's sweep already rewrote these, since they import `Stage` and `StageRegistry`. This task confirms the result reads correctly rather than merely compiling, because a mechanical rename can leave a message that is grammatical but wrong.

- [ ] **Step 1: Read the error messages**

```bash
cd /home/kelvin/librelane
grep -n "raise FlowSpecError" -A 6 librelane/flows/spec_validation.py
```

Every message must now say "job" where it said "stage". A message such as `"no job with id 'x' is registered. Registered jobs: [...]"` is correct. A message that still reads `"stage"` was missed by Task 2, Step 4.

- [ ] **Step 2: Confirm `uses` still reads as `<job>/<provider>`**

The document key `uses` named a stage and a provider. It now names a job and a provider, and the error text must say so:

```python
raise FlowSpecError(
    f"Job '{job}' declares uses '{uses}', which is not a job id or "
    f"a 'job/provider' pair."
)
```

- [ ] **Step 3: Run the workflow tests**

Run: `uv run pytest test/flows -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add librelane/flows test/flows
git commit -m "refactor: name jobs, not stages, in workflow document errors"
```

---

### Task 4: Resolve the `JobContractError` collision

**Files:**
- Modify: `librelane/jobs/job.py`, `librelane/flows/engine.py`

**Context the implementer needs:**

Two classes are now called `JobContractError`. Phase 2 introduced one in `librelane/flows/engine.py` for a job that completes without producing its declared views. Task 2 renamed `StageContractError` in `librelane/jobs/job.py` to the same name, for the same condition under the old engine.

They mean the same thing, so there must be one. Keep the one in `librelane/jobs/job.py`, because that is where the contract is declared, and have `engine.py` import it rather than define its own.

- [ ] **Step 1: Delete the duplicate**

In `librelane/flows/engine.py`, remove the `JobContractError` class definition and import it instead:

```python
from librelane.jobs import JobContractError
```

- [ ] **Step 2: Confirm one definition remains**

```bash
cd /home/kelvin/librelane
grep -rn "class JobContractError" librelane --include="*.py"
```

Expected: exactly one line, in `librelane/jobs/job.py`.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed

- [ ] **Step 4: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 5: Commit**

```bash
git add librelane/flows/engine.py librelane/jobs
git commit -m "refactor: one JobContractError, declared where the contract is"
```

---

### Task 5: Documentation and changelog

**Files:**
- Modify: every `docs/source/**/*.md` naming a stage; `Changelog.md`

- [ ] **Step 1: Find the documentation references**

```bash
cd /home/kelvin/librelane
grep -rin "stage" docs/source --include="*.md"
```

- [ ] **Step 2: Rewrite them**

Every occurrence becomes "job". The `TOOLS` documentation is the most important: it currently describes a mapping from stage id to tool name, and must now describe a mapping from job id to tool name.

- [ ] **Step 3: Build the documentation**

Run: `uv run make -C docs html`
Expected: succeeds. The only permitted ERROR is the pre-existing `librelane/steps/vendor.py:docstring of abc.abstractmethod:15: ERROR: Unexpected indentation.`

- [ ] **Step 4: Add the changelog entry**

In `Changelog.md`, under the in-development version's "API Breaks" heading:

```markdown
* `librelane.stages` is now `librelane.jobs`. `Stage` is `Job`, `StageRegistry`
  is `JobRegistry`, `StageError` is `JobDefinitionError`,
  `StageResolutionError` is `JobResolutionError` and `StageContractError` is
  `JobContractError`. `Registration.stage` is `Registration.job`. No
  compatibility aliases are provided: a stage and a job were the same thing
  under two names, and keeping both names would preserve the defect.
```

- [ ] **Step 5: Commit**

```bash
git add docs Changelog.md
git commit -m "docs: a stage is a job"
```

---

## What this phase does not do

`Stage.using`, `multi_provider` and `optional` survive under their new home because `StagedFlow` still needs them. The six flows are still Python classes, the command-line surface still has `--from` and `--to`, and no shipped flow runs on `Workflow`. Those are phases 4 and 5.
