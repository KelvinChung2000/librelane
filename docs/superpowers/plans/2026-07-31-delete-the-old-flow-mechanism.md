# Delete The Old Flow Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `SequentialFlow`, `StagedFlow`, `Flow`-as-a-declaration-base and every mechanism that existed only to recover a graph from a list.

**Architecture:** Deletion in dependency order, innermost consumer first. The Python flow classes go before the base they subclass; the span apparatus goes once nothing reads the tags; the gating machinery goes once no flow declares a gating table. Each task ends green, so a deletion that breaks something is attributable to that task alone.

**Tech Stack:** Python 3.11+, pytest, uv, `git rm`.

## Global Constraints

- This is phase 5 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phases 1 through 4 having landed, so all six flows are YAML documents running on `Workflow` and the command line uses `--target` and `--invalidate`.
- The full test suite must stay green at every commit.
- Never add a fallback. No deprecation shim, no `SequentialFlow = Workflow` alias, no re-export of a deleted name. This branch is not bound by what upstream would merge, and a compatibility alias for a deleted execution model is a second execution model.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields. `librelane/flows/sequential.py:14` currently has one; it is deleted with the file, so nothing needs to be done about it beyond not reintroducing it.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.
- `git add -A` fails on deliberately untracked personal dotfiles. Always stage explicitly: `git add librelane test docs Changelog.md`.

## Deletion inventory

Everything below is deleted, with nothing left in its place.

| What | Where |
| --- | --- |
| `SequentialFlow` | `librelane/flows/sequential.py` (whole file) |
| `StagedFlow` | `librelane/flows/staged.py` (whole file) |
| `Classic`, `VHDLClassic` | `librelane/flows/classic.py` (whole file) |
| `Chip` | `librelane/flows/chip.py` (whole file) |
| `OpenInKLayout`, `OpenInOpenROAD`, `OpenInMagic` | `librelane/flows/misc.py` (whole file) |
| `Flow.Steps`, `Flow.Stages`, `Flow.__init_subclass__`'s `Config` handling | `librelane/flows/flow.py` |
| `FlowFactory.register`, `FlowFactory.get` (the class registry) | `librelane/flows/flow.py:1067-1098` |
| `Boundary`, `_span_for`, `_boundaries`, `_after_step`, `stage_boundaries`, `provider_boundaries` | `librelane/flows/staged.py`, deleted with the file |
| `ResolvedSpan`, `Resolution.spans` | `librelane/jobs/resolution.py` |
| `Registration.tagged_steps`, `_job_span`, `_job_provider` | `librelane/jobs/registry.py` |
| `Job.using`, `Job.multi_provider`, `Job.optional` | `librelane/jobs/job.py` |
| `gating_config_vars` and its five helpers | deleted with `sequential.py` and `staged.py` |

---

### Task 1: Delete the six Python flow classes

**Files:**
- Delete: `librelane/flows/classic.py`, `librelane/flows/chip.py`, `librelane/flows/misc.py`
- Modify: `librelane/flows/__init__.py`, `test/flows/test_documents.py`

**Design notes the implementer needs:**

`test/flows/test_documents.py` compares each document against the Python flow it replaces. That comparison is what made phase 4 safe, and it must be removed in the same commit as the classes it compares against, because a test asserting equality with a deleted class cannot be kept and must not be silently weakened.

What replaces it is a test that the documents still resolve and still declare the jobs the flow is known for. That is weaker, and deliberately so: once there is one mechanism, the thing worth pinning is that the document is valid, not that it matches something that no longer exists.

- [ ] **Step 1: Replace the comparison tests**

In `test/flows/test_documents.py`, delete `test_the_classic_document_runs_the_same_steps_as_the_classic_flow` and `test_each_document_runs_the_same_steps_as_the_flow_it_replaces`, and add:

```python
@pytest.mark.parametrize(
    "document",
    [
        "classic.yaml",
        "vhdl_classic.yaml",
        "chip.yaml",
        "open_in_klayout.yaml",
        "open_in_openroad.yaml",
        "open_in_magic.yaml",
    ],
)
def test_every_shipped_document_resolves(document):
    from librelane.flows.spec_validation import validate_against_registry

    spec = _document(document)
    validate_against_registry(spec)
    jobs = resolve_jobs(spec)

    assert jobs
    assert all(job.steps for job in jobs.values())


def test_classic_declares_the_jobs_it_is_known_for():
    jobs = _document("classic.yaml").jobs

    for name in [
        "synthesis",
        "floorplan",
        "cts",
        "detailed_routing",
        "magic_streamout",
        "klayout_streamout",
        "magic_drc",
        "lvs",
        "signoff_sta",
    ]:
        assert name in jobs
```

- [ ] **Step 2: Delete the files**

```bash
cd /home/kelvin/librelane
git rm librelane/flows/classic.py librelane/flows/chip.py librelane/flows/misc.py
```

- [ ] **Step 3: Clean up the package exports**

In `librelane/flows/__init__.py`, remove the imports of `Classic`, `VHDLClassic`, `Chip`, `OpenInKLayout`, `OpenInOpenROAD` and `OpenInMagic`, and any `__all__` entries naming them.

- [ ] **Step 4: Find every remaining reference**

```bash
cd /home/kelvin/librelane
grep -rn "Classic\|OpenInKLayout\|OpenInOpenROAD\|OpenInMagic\|\bChip\b" librelane test docs --include="*.py" --include="*.md"
```

Every hit that names the Python class must become a document name string. `Flow.factory.get_document("Classic")` is correct; `from librelane.flows import Classic` is not.

- [ ] **Step 5: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: delete the Python flow classes, superseded by documents"
```

---

### Task 2: Delete `SequentialFlow` and `StagedFlow`

**Files:**
- Delete: `librelane/flows/sequential.py`, `librelane/flows/staged.py`
- Modify: `librelane/flows/__init__.py`
- Delete: `test/flows/test_sequential.py` and any `test/flows/` module testing only these two

**Design notes the implementer needs:**

This is where `gating_config_vars` and the entire span apparatus die, because both live in these two files. `Boundary`, `_span_for`, `_boundaries`, `_after_step`, `stage_boundaries`, `provider_boundaries`, `__gates_by_step_id`, `_apply_job_gating`, `__prune_deselected_gates` and `_expand_gating_config_vars` all go with the files. No part of any of them is moved anywhere.

Before deleting `test_sequential.py`, read it for tests of behaviour that survives. Resume semantics, `--skip` semantics and reproducible creation are all still real, and any such test moves to `test/flows/test_engine.py` rather than being deleted. A test that only exercises list-walking goes.

- [ ] **Step 1: Audit the tests being deleted**

```bash
cd /home/kelvin/librelane
grep -n "^def test_" test/flows/test_sequential.py
```

For each, decide: does it test something `Workflow` still does? If yes, port it to `test/flows/test_engine.py` against a document. If no, it goes. Record the count of ported and dropped tests in the commit message so the loss is visible.

- [ ] **Step 2: Port the surviving tests**

Move them into `test/flows/test_engine.py`, converting each flow class into a `FlowSpec` built with `FlowSpec.model_validate`.

- [ ] **Step 3: Delete the files**

```bash
cd /home/kelvin/librelane
git rm librelane/flows/sequential.py librelane/flows/staged.py test/flows/test_sequential.py
```

- [ ] **Step 4: Clean up the package exports**

In `librelane/flows/__init__.py`, remove `SequentialFlow` and `StagedFlow` from the imports and `__all__`.

- [ ] **Step 5: Find every remaining reference**

```bash
cd /home/kelvin/librelane
grep -rn "SequentialFlow\|StagedFlow\|gating_config_vars\|stage_boundaries\|provider_boundaries" librelane test docs --include="*.py" --include="*.md"
```

Expected after fixing: no output.

- [ ] **Step 6: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: delete SequentialFlow, StagedFlow and the gating tables"
```

---

### Task 3: Delete the span apparatus from the registry

**Files:**
- Modify: `librelane/jobs/registry.py`, `librelane/jobs/resolution.py`
- Test: `test/jobs/test_registry.py`, `test/jobs/test_resolution.py`

**Design notes the implementer needs:**

`Registration.tagged_steps` subclasses every step class to attach `_job_span` and `_job_provider`. Task 2 deleted the only two readers, at what was `staged.py:234` and `staged.py:622`. The tagging now costs a subclass per step per registration and is read by nothing.

`Resolution.spans` and `ResolvedSpan` exist for the same reason. `resolve()` keeps returning `steps` and `unselected`; it stops returning `spans`.

Two tests pin the tags directly and must be deleted, not adjusted: `test/jobs/test_registry.py:176-177` asserts `tagged[0]._job_span` and `tagged[0]._job_provider`, and `test/jobs/test_resolution.py:34` asserts `not hasattr(resolution.steps[1], "_job_span")`.

- [ ] **Step 1: Delete the tagging**

In `librelane/jobs/registry.py`, delete the `tagged_steps` method entirely. Wherever `registration.tagged_steps()` was called, use `registration.steps` directly.

- [ ] **Step 2: Delete the spans**

In `librelane/jobs/resolution.py`, delete `ResolvedSpan` and the `spans` field of `Resolution`, and remove the code that builds them.

- [ ] **Step 3: Delete the tests that pin the tags**

```bash
cd /home/kelvin/librelane
grep -rn "_job_span\|_job_provider\|ResolvedSpan\|\.spans\b" librelane test --include="*.py"
```

Delete the tests naming them. Any remaining production hit is a missed reference.

- [ ] **Step 4: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: delete the job span apparatus, which nothing reads"
```

---

### Task 4: Delete `Flow` as a declaration base

**Files:**
- Modify: `librelane/flows/flow.py`
- Test: `test/flows/test_flow.py`

**Design notes the implementer needs:**

`Flow` keeps everything that is machinery and loses everything that is declaration. Kept: `run_dir`, `toolbox`, `fingerprinter`, `FlowProgressBar`, `get_all_config_variables`, `start`, `start_step`, `start_step_async`, `_save_snapshot_ef`, `get_help_md`, `display_help` and `FlowFactory.register_document` / `get_document` / `list`. Deleted: `Flow.Steps`, `Flow.Stages`, the abstract `run`, `__init_subclass__`'s handling of a subclass `Config`, `dir_for_step`, and `FlowFactory.register` / `get`, the class registry.

`dir_for_step` goes because `Workflow.dir_for_job_step` replaced it in phase 2, and its positional numbering is meaningless under concurrency.

`Flow` stops being abstract. It has exactly one subclass, `Workflow`, and phase 5's whole point is that there will not be a second. Consider merging `Flow` into `Workflow` rather than keeping a one-subclass hierarchy; if the merged file exceeds roughly 800 lines, keep them separate and say so in the commit message, because a single unreadable file is a worse outcome than a shallow hierarchy.

- [ ] **Step 1: Delete the declaration surface**

Remove `Steps`, `Stages`, the abstract `run`, `dir_for_step`, and the `Config` branch of `__init_subclass__`. Remove `ABC` from `Flow`'s bases.

- [ ] **Step 2: Delete the class registry**

Remove `FlowFactory.register` and `FlowFactory.get`. `FlowFactory.list` now lists document names.

- [ ] **Step 3: Fix the tests**

```bash
cd /home/kelvin/librelane
grep -rn "Flow.factory.register()\|Flow.factory.get(\|\.Steps\b\|\.Stages\b\|dir_for_step" librelane test docs --include="*.py" --include="*.md"
```

Every hit becomes `Flow.factory.get_document(...)`, a document, or `dir_for_job_step`.

- [ ] **Step 4: Decide on the merge**

```bash
cd /home/kelvin/librelane
wc -l librelane/flows/flow.py librelane/flows/engine.py
```

If the sum is under 800, merge `engine.py` into `flow.py` and delete `engine.py`. Otherwise leave them separate and record the line counts in the commit message.

- [ ] **Step 5: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: Flow is machinery, not a declaration base"
```

---

### Task 5: Delete `using`, `multi_provider` and `optional`

**Files:**
- Modify: `librelane/jobs/job.py`, `librelane/jobs/taxonomy.py`, `librelane/jobs/registry.py`, `librelane/jobs/resolution.py`
- Test: `test/jobs/`

**Design notes the implementer needs:**

All three existed to serve a `Stages` list that no longer exists.

`Job.using` returned an unregistered copy with a pinned provider, for use in a flow's list. A document says `uses: job/provider` instead.

`multi_provider` allowed one entry to run several providers' step sequences concatenated. A document says two jobs instead, which is strictly clearer: `streamout` becomes `magic_streamout` and `klayout_streamout`, each independently switchable, which is what the two `RUN_*_STREAMOUT` booleans were emulating.

`optional` allowed a job to be left unselected and contribute no steps, which was only needed because a list had to mention every job. A document omits it.

Deleting `multi_provider` means `default_provider` is always a single `str | None`, and `default_providers` collapses to `(default_provider,)` or `()`. Update `_resolve` in `librelane/flows/job.py`, whose provider loop was written for the tuple case, and the four taxonomy entries that declare a tuple default.

- [ ] **Step 1: Find the affected taxonomy entries**

```bash
cd /home/kelvin/librelane
grep -n "multi_provider\|optional=True\|default_provider=(" librelane/jobs/taxonomy.py
```

Each tuple default becomes a single provider name; the second provider's job is declared separately in each document that wants it. Each `optional=True` entry simply loses the flag.

- [ ] **Step 2: Delete the fields and the method**

In `librelane/jobs/job.py`, delete `using`, `multi_provider` and `optional`, narrow `default_provider` to `str | None`, and remove the `register()` checks that referenced them.

- [ ] **Step 3: Simplify the provider resolution**

In `librelane/flows/job.py`, replace the provider loop in `_resolve` with a single provider, since there can now only be one.

- [ ] **Step 4: Fix the tests**

```bash
cd /home/kelvin/librelane
grep -rn "using(\|multi_provider\|optional" librelane test docs --include="*.py" --include="*.md"
```

- [ ] **Step 5: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: delete using, multi_provider and optional"
```

---

### Task 6: Documentation and changelog

**Files:**
- Modify: `docs/source/**/*.md`, `Changelog.md`

- [ ] **Step 1: Rewrite the flow authoring documentation**

```bash
cd /home/kelvin/librelane
grep -rln "SequentialFlow\|Stages = \|Steps = \|meta.flow" docs/source
```

Every page teaching a reader to declare a flow by subclassing must now teach the YAML document. The `literalinclude` directives pointing at `classic.py` must point at `classic.yaml`.

- [ ] **Step 2: Build the documentation**

Run: `uv run make -C docs html`
Expected: succeeds. The only permitted ERROR is the pre-existing `librelane/steps/vendor.py:docstring of abc.abstractmethod:15: ERROR: Unexpected indentation.`

- [ ] **Step 3: Write the changelog**

Under the in-development version's "API Breaks":

```markdown
* Flows are YAML documents, not Python classes. `SequentialFlow`, `StagedFlow`,
  `Flow.Steps`, `Flow.Stages` and the class-based `Flow.factory.register` are
  deleted, along with `Classic`, `VHDLClassic`, `Chip`, `OpenInKLayout`,
  `OpenInOpenROAD` and `OpenInMagic` as importable classes. The six flows ship
  as `librelane/flows/*.yaml` and are looked up with
  `Flow.factory.get_document(name)`.
* `gating_config_vars` is deleted. A job declares `if: SOME_VARIABLE`.
* `Job.using`, `Job.multi_provider` and `Job.optional` are deleted. A document
  writes `uses: job/provider`, declares two jobs where two providers both ran,
  and omits a job it does not want.
* `Registration.tagged_steps`, `ResolvedSpan` and `Resolution.spans` are
  deleted. A job owns its step list, so the grouping no longer has to be
  recovered from tags.
* `--from` and `--to` are deleted, replaced by `--invalidate` and `--target`.
* `TOOLS` is keyed by job id rather than by stage id.
```

Under "Flows":

```markdown
* Independent jobs now run concurrently. In `Classic`, Magic and KLayout
  streamout, both DRC providers, LVS and formal equivalence are no longer
  serialised behind one another.
```

- [ ] **Step 4: Commit**

```bash
git add docs Changelog.md
git commit -m "docs: flows are documents"
```

---

### Task 7: Final verification

- [ ] **Step 1: Confirm nothing survives**

```bash
cd /home/kelvin/librelane
grep -rn "SequentialFlow\|StagedFlow\|gating_config_vars\|tagged_steps\|ResolvedSpan\|multi_provider\|\.using(\|dir_for_step\|\-\-from\|\-\-to\b" librelane test docs --include="*.py" --include="*.md"
```

Expected: no output. Any hit is either a missed deletion or a changelog entry, and a changelog entry is the only acceptable one.

- [ ] **Step 2: Run everything**

```bash
uv run pytest test -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
uv run make -C docs html
```

- [ ] **Step 3: Run a real design end to end**

```bash
uv run librelane librelane/examples/spm/config.yaml
```

Expected: completes, and `runs/<tag>/` contains one directory per job rather than a flat numbered list of steps.

- [ ] **Step 4: Confirm the concurrency is real**

```bash
uv run librelane --target magic_drc librelane/examples/spm/config.yaml
```

Expected: `klayout_drc`, `lvs` and `formal_equivalence` do not appear in the run directory, because none of them is an ancestor of `magic_drc`.
