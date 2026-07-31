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

The spec says a job and a stage are one dataclass. In implementation they are two types, because one is a library entry and the other is a bound instance, the way a class and an instance are two things. `Job` is the registry entry: the 27 taxonomy templates, the thing `TOOLS` keys on, the thing `uses:` names. `ResolvedJob` is what the engine runs: a `Job` bound to a document's `needs`, `source` and `condition`, with its steps resolved from the selected provider.

This is not the duality the spec removes. That duality was two *authoring* concepts, `Stage.x` entries and bare steps sitting in one list with different gating rules. A document author writes only jobs. `ResolvedJob` is an internal type no author names.

The word "stage" is retired everywhere: types, variables, error classes, messages, docstrings and documentation.

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
- Consumes: `Job`, `resolve_jobs` from phase 2's `librelane/flows/job.py`.
- Produces: `ResolvedJob` with identical fields, and `resolve_jobs(spec: FlowSpec) -> dict[str, ResolvedJob]`.

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

    Never written by hand. ``needs``, ``source`` and ``condition`` come from the
    document; ``requires``, ``provides``, ``metrics`` and ``steps`` come from
    the template, or from the steps themselves for an inline job.
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
- Modify: every file importing from `librelane.stages`

**Interfaces:**
- Produces: `librelane.jobs.Job`, `librelane.jobs.JobRegistry`, `librelane.jobs.JobDefinitionError`, `librelane.jobs.JobResolutionError`, `Registration.job`.

**Context the implementer needs:**

`Job` uses a metaclass, `StageMetaclass`, whose `__getattr__` is what makes `Stage.synthesis` resolve through the factory. Rename it to `JobMetaclass`. Its `__getattr__` raises `AttributeError("Unknown Stage attribute", key, Self)`; the first element of that tuple becomes `"Unknown Job attribute"`.

`Registration.tagged_steps` sets `"_stage_span": (self.stage,)` and `"_stage_provider": self.provider`. Both tag names are read in exactly two places outside the registry, at `librelane/flows/staged.py:234` and `librelane/flows/staged.py:622`. Rename the tags and both readers together, or `StagedFlow` silently loses its boundary map and the stage-contract tests fail with a confusing message rather than a rename error.

- [ ] **Step 1: Move the files**

```bash
cd /home/kelvin/librelane
git mv librelane/stages librelane/jobs
git mv librelane/jobs/stage.py librelane/jobs/job.py
git mv test/stages test/jobs
```

- [ ] **Step 2: Rewrite every reference**

```bash
cd /home/kelvin/librelane
FILES=$(grep -rl "librelane\.stages\|from \.\.stages\|from \.stages\|\bStage\b\|StageRegistry\|StageError\|StageResolutionError\|StageContractError\|_stage_span\|_stage_provider" librelane test docs --include="*.py" --include="*.md")
sed -i \
  -e 's/librelane\.stages/librelane.jobs/g' \
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
```

Order matters. `StageRegistry` and the error classes are rewritten before the bare `Stage`, or `\bStage\b` would not match them anyway but `StageRegistry` would become `JobRegistry` only by luck of ordering. Keeping the specific names first makes the intent explicit.

- [ ] **Step 3: Rename the `stage` field on `Registration`**

`\bStage\b` does not match the lowercase field. Rewrite it separately, because `stage` as a bare word also appears in prose:

```bash
cd /home/kelvin/librelane
sed -i \
  -e 's/\bstage=/job=/g' \
  -e 's/registration\.stage\b/registration.job/g' \
  -e 's/\bstage: str\b/job: str/g' \
  -e 's/self\.stage\b/self.job/g' \
  librelane/jobs/registry.py librelane/jobs/resolution.py
grep -rn "\.stage\b\|stage=" librelane/jobs/ librelane/flows/ --include="*.py"
```

Expected from the `grep`: no output. Anything it prints is a missed reference; fix it by hand before continuing.

- [ ] **Step 4: Sweep the remaining prose**

```bash
cd /home/kelvin/librelane
grep -rin "stage" librelane test docs --include="*.py" --include="*.md" | grep -v "\.pyc"
```

Every remaining hit is a docstring, comment, error message or documentation sentence. Rewrite each so it says "job". There is no automated rewrite for these because "stage" appears in phrases such as "a named phase of a flow" that need rewording rather than substitution.

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
