# Delete The Old Flow Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `SequentialFlow`, `StagedFlow`, `Flow`-as-a-declaration-base and every mechanism that existed only to recover a graph from a list.

**Architecture:** Deletion in dependency order, innermost consumer first. The Python flow classes go before the base they subclass; the span apparatus goes once nothing reads the tags; the gating machinery goes once no flow declares a gating table. Each task ends green, so a deletion that breaks something is attributable to that task alone.

**Tech Stack:** Python 3.11+, pytest, uv, `git rm`.

## Global Constraints

- This is phase 5 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phases 1 through 4 having landed, so all eight flows are YAML documents running on `Workflow` and the command line uses `--target` and `--invalidate`.
- The full test suite must stay green at every commit.
- Never add a fallback. No deprecation shim, no `SequentialFlow = Workflow` alias, no re-export of a deleted name. This branch is not bound by what upstream would merge, and a compatibility alias for a deleted execution model is a second execution model.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields. `librelane/flows/sequential.py:14` currently has one; it is deleted with the file, so nothing needs to be done about it beyond not reintroducing it.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.
- `git add -A` fails on deliberately untracked personal dotfiles. Always stage explicitly: `git add librelane test docs Changelog.md`.

**The one unmerged dependency.** This plan is written against branch `worktree-agent-a2dad013ce988e29b`, not against `librelane-unstable` as it stands. Its commit `6870f74`, "launch OpenROAD and OpenSTA interactively (#532)", adds two more single-job flows to `librelane/flows/misc.py`: `OpenInOpenROADConsole` (one step, `OpenROAD.OpenConsole`) and `OpenInOpenSTAConsole` (one step, `OpenROAD.OpenSTAConsole`), inserted between `OpenInOpenROAD` and `OpenInMagic`. Verified by reading `librelane/flows/misc.py` on that branch: it has five classes, at `OpenInKLayout:22`, `OpenInOpenROAD:39`, `OpenInOpenROADConsole:57` (new), `OpenInOpenSTAConsole:75` (new) and `OpenInMagic:94` (moved from `:57`). `librelane/flows/builtins.py` is untouched by that commit; it still imports only `OpenInKLayout` and `OpenInOpenROAD` by name, so all three of `OpenInOpenROADConsole`, `OpenInOpenSTAConsole` and `OpenInMagic` are registered the same way, as a side effect of importing a module that never binds their names anywhere else. This branch is expected to merge before phase 5 is implemented, so the six flows/classes this plan counted in an earlier draft are eight throughout: the deletion inventory below, Task 1's design notes and Step 8's grep, Task 7's final grep, and the changelog entry in Task 6 all name the two new classes.

## Deletion inventory

Everything below is deleted, with nothing left in its place.

| What | Where |
| --- | --- |
| `SequentialFlow` | `librelane/flows/sequential.py` (whole file) |
| `StagedFlow` | `librelane/flows/staged.py` (whole file) |
| `Classic`, `VHDLClassic` | `librelane/flows/classic.py` (whole file) |
| `Chip` | `librelane/flows/chip.py` (whole file) |
| `OpenInKLayout`, `OpenInOpenROAD`, `OpenInOpenROADConsole`, `OpenInOpenSTAConsole`, `OpenInMagic` | `librelane/flows/misc.py` (whole file, five classes at lines 22, 39, 57, 75 and 94 on the merged tree; see "The one unmerged dependency" above) |
| `Flow.Steps`, `Flow.Stages`, `Flow.__init_subclass__`'s `Config` handling | `librelane/flows/flow.py` |
| `FlowFactory.register`, `FlowFactory.get` (the class registry) | `librelane/flows/flow.py`, `register` at 1136, `get` at 1161 |
| `Boundary`, `_span_for`, `_boundaries`, `_after_step`, `stage_boundaries`, `provider_boundaries` | `librelane/flows/staged.py`, deleted with the file |
| `resolve()`, `Resolution`, `ResolvedSpan`, `ProviderContract` (whole file, deleted in Task 2 alongside `staged.py`, its only caller) | `librelane/jobs/resolution.py` |
| `Registration.tagged_steps`, `_job_span`, `_job_provider` (Task 3, once `resolve()` above is gone) | `librelane/jobs/registry.py` |
| `Job.using`, `Job.multi_provider`, `Job.optional` | `librelane/jobs/job.py` |
| `gating_config_vars` and its five helpers | deleted with `sequential.py` and `staged.py` |
| `librelane/flows/builtins.py` (whole file) | its only job is importing `classic.py`, `chip.py` and `misc.py` for their registration side effects; nothing once those three are gone |
| `StepDisposition`, `Explanation.steps`, `Explanation.unselected_stages` | `librelane/flows/explanation.py`; `Explanation.jobs` (added additively by phase 4's Task 10, "`--explain` reports jobs") is kept |
| the old `format_explanation` steps/unselected_stages rendering and the `isinstance(flow, SequentialFlow)` `--explain` branch | `librelane/cli/run.py`, kept additively through phase 4 for the same reason |

**Note on line numbers in this table and below:** verified against this checkout, which does not yet have phases 1-4 applied (`librelane/jobs/` does not exist yet; today's equivalent is `librelane/stages/`, and today's tag names are `_stage_span`/`_stage_provider`, not `_job_span`/`_job_provider`). Where this plan cites a `librelane/jobs/...` path or a `_job_*` name, that assumes phase 3 ("Stage becomes Job") has already renamed the `stages` package to `jobs` and the tags accordingly, preserving line numbers. This was spot-checked against `test/stages/test_registry.py:176-177` and `test/stages/test_resolution.py:34`, today's exact locations of the `_stage_span`/`_stage_provider` assertions this plan deletes as `test/jobs/test_registry.py:176-177` (Task 3) and `test/jobs/test_resolution.py:34` (Task 2, as part of that whole file); the line numbers matched.

---

### Task 1: Delete the eight Python flow classes

**Files:**
- Delete: `librelane/flows/classic.py`, `librelane/flows/chip.py`, `librelane/flows/misc.py`, `librelane/flows/builtins.py`
- Delete: `test/flows/test_chip.py`, `test/flows/test_staged_equivalence.py`, `test/flows/classic_steps.json`, `test/flows/vhdl_classic_steps.json`, `test/flows/classic_gating.json`
- Modify: `librelane/flows/__init__.py`, `test/flows/test_documents.py`, `test/flows/test_staged.py`, `test/flows/test_flow.py`, `test/config/test_model_registry.py`

**Design notes the implementer needs:**

`test/flows/test_documents.py` compares each document against the Python flow it replaces. That comparison is what made phase 4 safe, and it must be removed in the same commit as the classes it compares against, because a test asserting equality with a deleted class cannot be kept and must not be silently weakened.

What replaces it is a test that the documents still resolve and still declare the jobs the flow is known for. That is weaker, and deliberately so: once there is one mechanism, the thing worth pinning is that the document is valid, not that it matches something that no longer exists.

The eight classes are not imported where you would expect. `librelane/flows/__init__.py` does not import `Classic`, `Chip` or any `OpenIn*` name; it does `from librelane.flows import builtins` (line 26), and it is `librelane/flows/builtins.py` (lines 15-17) that imports `Classic`/`VHDLClassic` from `classic.py`, `Chip` from `chip.py`, and `OpenInKLayout`/`OpenInOpenROAD` from `misc.py`. `builtins.py` never imports `OpenInOpenROADConsole`, `OpenInOpenSTAConsole` or `OpenInMagic` by name at all; all three are registered anyway, because `from librelane.flows.misc import OpenInKLayout, OpenInOpenROAD` executes the whole `misc.py` module, including all three names' `@Flow.factory.register()` decorators, even though none of the three is ever bound outside `misc.py`. `builtins.py` has no purpose once `classic.py`, `chip.py` and `misc.py` are gone, since importing it for side effect is all it does, so it is deleted along with them; `librelane/flows/__init__.py` loses its `from librelane.flows import builtins` line. `librelane/flows/__init__.py` has no `__all__`, so there is nothing to prune there.

Four test files reference the classes this task deletes directly, by name, through `Flow.factory.get(...)` or a direct import, not just through the grep in Step 6. Each is handled below:

- `test/flows/test_chip.py` tests only `Chip`: a golden step-ID list (`test_chip_expands_to_the_same_steps_the_substitution_map_produced`) and a check that `Chip` declares its own `Stages` rather than inheriting `Classic`'s (`test_chip_declares_its_own_stages_rather_than_patching_classic`). Both lose their subject when `Chip` is deleted, and both are superseded by the document-resolution tests Step 1 adds to `test/flows/test_documents.py`. Delete the file.
- `test/flows/test_staged_equivalence.py` tests only `Classic` and `VHDLClassic`, comparing their step lists and gating tables against golden snapshots in `test/flows/classic_steps.json`, `test/flows/vhdl_classic_steps.json` and `test/flows/classic_gating.json`. These three JSON files have no other consumer (verified by grep across `test` and `librelane`). Delete the test file and the three snapshots, for the same reason as `test/flows/test_documents.py`'s comparison tests: a golden-snapshot test of a deleted class cannot be kept.
- `test/config/test_model_registry.py` has one test, `test_classic_flow_config_model_bridge` (around line 139), that does `from librelane.flows.classic import Classic` to check that `Classic.Config` bridges correctly to `BaseConfigModel`. This is a direct import of the module being deleted, so it fails at import time regardless of what it asserts. The mechanism it tests, a `Config` class nested in a `Flow` subclass, is itself deleted in Task 4 (`Flow.__init_subclass__`'s `Config` handling), so there is no other flow class to substitute it with. Delete the test.
- `test/flows/test_staged.py` is `StagedFlow`'s own test file and is not deleted until Task 2, but 14 of its tests (scattered through the back two-thirds of the file, not a contiguous block) instantiate the real `Classic` or `Chip` class via `Flow.factory.get("Classic")` / `Flow.factory.get("Chip")` to exercise `TOOLS` re-expansion, gating and preflight behaviour against a real flow rather than a synthetic one. Those tests break the moment this task deletes `classic.py`/`chip.py`, before Task 2 ever runs. Step 6 below removes exactly that subset by name; the remaining synthetic-subclass tests (`SmallStaged`, `Doubled`, `Gated`, `ModifiedGate`, `Bypassed`, the `ContractTestStage`/`MultiProviderContractStages`/`PreflightSteps` fixtures and the tests built on them) test `StagedFlow` itself, are unaffected by this task, and are Task 2's concern, audited there the same way `test_sequential.py` is.

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
        "open_in_openroad_console.yaml",
        "open_in_opensta_console.yaml",
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

`open_in_openroad_console.yaml` and `open_in_opensta_console.yaml` follow the naming pattern the three existing Open-In documents already use, one document name lowercased with underscores per class (`open_in_klayout.yaml` from `OpenInKLayout`, `open_in_openroad.yaml` from `OpenInOpenROAD`, `open_in_magic.yaml` from `OpenInMagic`), applied to `OpenInOpenROADConsole` and `OpenInOpenSTAConsole`. Phase 4's Task 4 is what actually creates these two documents and is authoritative on their filenames. It names them `open_in_openroad_console.yaml` and `open_in_opensta_console.yaml`, so the two entries above are already correct and need no adjustment.

Do not rely on this list staying complete. It is a literal, and a literal cannot fail for a flow nobody remembered to add to it, which is the exact hole that put these two documents here in the first place. Phase 4's Task 5 carries `test_every_registered_flow_class_has_a_document_standing_in_for_it`, which derives both sets from the registries and asserts the difference is empty. That test is the real guard; this list only pins the names.

- [ ] **Step 2: Delete the files**

```bash
cd /home/kelvin/librelane
git rm librelane/flows/classic.py librelane/flows/chip.py librelane/flows/misc.py librelane/flows/builtins.py
```

- [ ] **Step 3: Clean up the package exports**

In `librelane/flows/__init__.py`, remove the line `from librelane.flows import builtins`. There is no `__all__` in this file to prune.

- [ ] **Step 4: Delete the golden-comparison test files**

```bash
cd /home/kelvin/librelane
git rm test/flows/test_chip.py test/flows/test_staged_equivalence.py test/flows/classic_steps.json test/flows/vhdl_classic_steps.json test/flows/classic_gating.json
```

- [ ] **Step 5: Delete the direct-import test in test_model_registry.py**

In `test/config/test_model_registry.py`, delete `test_classic_flow_config_model_bridge`, which does `from librelane.flows.classic import Classic`.

- [ ] **Step 6: Remove the Classic/Chip-dependent tests from test_staged.py**

In `test/flows/test_staged.py`, delete every function and helper that calls `Flow.factory.get("Classic")` or `Flow.factory.get("Chip")`, directly or through the two helpers below, since their subject is deleted by this task:

- Helpers: `_flow_with_tools`, `_classic_with_tools`, and the `_NO_XOR` constant (all three become unused once the functions below are gone).
- Tests: `test_tools_reexpands_at_instance_time`, `test_reexpansion_regenerates_gating_for_the_selected_provider`, `test_default_run_does_not_reexpand`, `test_gates_for_a_deselected_tool_are_dropped_not_rejected`, `test_chip_with_tools_keeps_its_own_step_list`, `test_unknown_provider_is_rejected_with_the_registered_names`, `test_unknown_stage_key_is_rejected_with_a_suggestion`, `test_gating_one_real_tool_leaves_the_other_s_contract_checked` (and the `_ONE_TOOL_GATED` constant and `@pytest.mark.parametrize` that only feed it), `test_default_classic_passes_the_preflight`, `test_klayout_only_streamout_needs_the_xor_disabled`, `test_every_single_provider_selection_leaves_no_orphaned_step` (and the `_ORPHANING_SELECTIONS` constant and `_stages_with_several_providers` helper that only feed it), `test_vhdl_synthesis_on_classic_fails_the_preflight`, `test_help_lists_stages_and_their_providers` (`test/flows/test_staged.py:1022`; phase 4's Task 14 reproduces this coverage against `Workflow`, so nothing is lost, but it is already in this list for the same `Flow.factory.get("Classic")` reason as the rest), `test_describe_stages_reports_the_default_selection`.

`_MINIMAL_DESIGN` and `_MOCK_PDK` stay: the surviving synthetic-subclass tests use them too. The file is not deleted here; what remains is `StagedFlow`'s own test file, Task 2's concern.

- [ ] **Step 7: Fix test_flow.py's factory test**

`test_factory` in `test/flows/test_flow.py` asserts `Flow.factory.list()` contains `"Classic"`, `"OpenInKLayout"` and `"OpenInOpenROAD"` (around lines 156-163). Those names come from the class registry entries this task deletes, so the assertion fails as soon as Step 2 runs. Delete that assertion (the `assert all(... for flow in Flow.factory.list()) ...` block). The rest of `test_factory`, which registers and retrieves a `Dummy` flow through `Flow.factory.register()`/`Flow.factory.get()`, exercises the class registry itself and is Task 4's concern, since that is where `FlowFactory.register`/`get` are deleted.

- [ ] **Step 8: Find every remaining reference**

```bash
cd /home/kelvin/librelane
grep -rn "Classic\|OpenInKLayout\|OpenInOpenROAD\|OpenInOpenROADConsole\|OpenInOpenSTAConsole\|OpenInMagic\|\bChip\b" librelane test docs --include="*.py" --include="*.md"
```

Every hit that names the Python class must become a document name string. `Flow.factory.get_document("Classic")` is correct; `from librelane.flows import Classic` is not. A hit that is a bare string, such as a `--flow Classic` CLI argument or a `meta.flow: Classic` YAML value, is fine as is: those name a document, not a Python symbol, and phase 4 is what makes that lookup resolve through `get_document`.

`test/stages/test_providers_vendor.py:31` and `:39` call `Flow.factory.get("Classic").get_help_md()`, to check that an opt-in vendor provider appears in a flow's rendered help. Phase 4's Task 14, "`get_help_md` reads the document's jobs", owns this file's migration explicitly (as `test/jobs/test_providers_vendor.py` once phase 3 has renamed the package), together with defining `Workflow.get_help_md` and the static `help_md_for_document` it adds for the three callers that have no configuration, and the `cli/help.py` and Sphinx-generator migrations that go with them. Task 4 below explains why the replacement cannot stay on `Flow`, and deletes the two old classmethods. By the time this task runs, Step 8's grep should show no hit here. If it still does, phase 4's Task 14 has not landed; stop and say so rather than inventing a document-based `.get_help_md()` that no plan defines.

- [ ] **Step 9: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: delete the Python flow classes, superseded by documents"
```

---

### Task 2: Delete `SequentialFlow` and `StagedFlow`

**Files:**
- Delete: `librelane/flows/sequential.py`, `librelane/flows/staged.py`, `librelane/jobs/resolution.py` (whole file)
- Modify: `librelane/flows/__init__.py`, `librelane/flows/explanation.py`, `librelane/cli/run.py`
- Delete: `test/flows/test_sequential.py`, `test/jobs/test_resolution.py` (whole file), `test/flows/test_explain.py`'s old tests, and any other `test/flows/` module testing only `SequentialFlow`/`StagedFlow`, including the remainder of `test/flows/test_staged.py` left after Task 1's Step 6

**Design notes the implementer needs:**

`librelane/jobs/resolution.py` (`resolve()`, `Resolution`, `ResolvedSpan`, `ProviderContract` and their helpers) is deleted here, whole, not partially. Confirmed by the phase 3 agent, who read phase 2's plan directly: this module survives phase 3's `stages`→`jobs` rename fully intact and unmerged, because `StagedFlow` needs all of it (not just the span fields) through phase 4, and phase 2's `resolve_jobs()` is an independent algorithm that never calls `resolve()`. The two do not touch. `staged.py` is `resolve()`'s only caller, so once it is deleted here, the whole file is dead, and `test/jobs/test_resolution.py` (today's `test/stages/test_resolution.py`, 15 tests; 13 of them exercise `resolve()` directly, and the other two, `test_using_a_list_on_a_single_provider_stage_is_rejected` and `test_using_an_empty_list_is_rejected`, exercise `Stage.using` instead, which Task 5 deletes anyway) goes with it in the same commit, not just the one test that pins the span tags. This corrects an earlier draft of this plan, which assumed `jobs/resolution.py` was shared with the new engine and tried to delete only `ResolvedSpan`/`Resolution.spans` from it in Task 3; that assumption was wrong, and Task 3 below now only touches `librelane/jobs/registry.py`.

This is also where `gating_config_vars` and the entire span apparatus die, because both live in these two files. `Boundary`, `_span_for`, `_boundaries`, `_after_step`, `stage_boundaries`, `provider_boundaries`, `__gates_by_step_id`, `_apply_job_gating`, `__prune_deselected_gates` and `_expand_gating_config_vars` all go with the files. No part of any of them is moved anywhere.

`StagedFlow.get_help_md` (`librelane/flows/staged.py:549`) goes with the file for the same reason as everything above: it overrides `Flow.get_help_md` to append a `#### Stages` section, and both the override and the method it overrides are superseded by phase 4's Task 14, "`get_help_md` reads the document's jobs" (Task 4 below deletes the `Flow` half).

Before deleting `test_sequential.py`, read it for tests of behaviour that survives. Resume semantics, `--skip` semantics and reproducible creation are all still real, and any such test moves to `test/flows/test_engine.py` rather than being deleted. A test that only exercises list-walking goes. Apply the same audit to what is left of `test/flows/test_staged.py` after Task 1's Step 6 removed its `Classic`/`Chip`-dependent tests: the remaining tests exercise `Stages`-list expansion, stage gating, per-boundary contract checking and the view preflight, all `StagedFlow`-specific, and whichever of those still describe something `Workflow`'s job resolution does (contract checking and the view preflight are the likely candidates, since job resolution still has to validate a job's inputs are producible and its contract is met) port to `test/flows/test_engine.py` the same way; the rest, especially anything asserting on `Boundary`/`_boundaries`/`gating_config_vars` directly, goes. `test/flows/test_explain.py` is not entirely about `SequentialFlow.explain`/`StagedFlow` by the time this task runs. Its original seven tests are (`Classic` there is used only as a stand-in `SequentialFlow`/`StagedFlow` instance, not tested for its own sake), but phase 4's Task 10 appends `test_explain_names_the_condition_that_stops_a_job` and `test_explain_marks_jobs_outside_the_target_subgraph`, which build a `Workflow` directly from a `FlowSpec` and assert on `Explanation.jobs`, and phase 4's Task 13 appends five tests of `Explanation.variables`/`VariableDisposition`, also against a `Workflow`; Task 10 also rewrites the file's original seven tests onto the `minimal_design`/`mock_pdk` fixtures. Audit and delete only what is `SequentialFlow`/`StagedFlow`-based: the original seven tests, including `test_an_unselected_stage_is_reported_separately`, and Task 10's own `test_explain_still_answers_for_a_sequential_flow`, which explicitly builds a `SequentialFlow` subclass and says in its own docstring that it "ships until phase 5 deletes the engine that backs it". The two `Workflow`-based `explain` tests and the five `VariableDisposition` tests stay, since they test what `Workflow`, `Explanation.jobs` and `Explanation.variables` still do; fold this audit into the same pass as `test_sequential.py` and the remainder of `test_staged.py` rather than treating it separately.

**Precondition before deleting `staged.py`: `TOOLS` support must already exist on the new engine.** Today, `TOOLS` (declared on `StagedFlow.Config` at `librelane/flows/staged.py:115`) is served by two things this task's Files list does not otherwise touch:

1. `extract_tools()` in `librelane/stages/tools.py`, a pre-pass that reads the raw `TOOLS` mapping (`dict[str, str | list[str]]`) out of layered configuration sources ahead of the configuration preprocessor and ahead of validation, because the step set has to be known before configuration can be validated. It is generic over the key name (it does not know "stage"), so it is expected to survive unchanged and be reused by the new engine's job-id-keyed `TOOLS`; this plan does not delete it, and no step below should.
2. Per-entry provider selection and validation in `resolve()`, today at `librelane/stages/resolution.py` and, per phase 3's confirmed unmerged rename, still at `librelane/jobs/resolution.py` immediately before this task deletes it: choosing a provider per stage from `TOOLS`, falling back to `default_provider`, and raising on an unknown key (with a fuzzy-match suggestion), an unknown provider, or an empty provider list for a non-multi-provider entry. This is `StagedFlow`-only and is deleted whole by this task's Step 3, not carried anywhere.

Before this task's Step 3 (deleting the files), confirm `Workflow`'s job graph construction already performs the equivalent of both, re-keyed to job ids: reads `TOOLS` early via a job-id-keyed pre-pass, and rejects an unknown job key / unknown provider / empty list the same way `StageResolutionError` does today. If either is missing, deleting `staged.py` here would silently drop `TOOLS` support with nothing to replace it, which is the exact defect this plan exists to avoid. This is phase 4's addition to land first; if it is not in place when this task is executed, stop and say so rather than deleting the file.

- [ ] **Step 1: Audit the tests being deleted**

```bash
cd /home/kelvin/librelane
grep -n "^def test_" test/flows/test_sequential.py test/flows/test_staged.py test/flows/test_explain.py
```

For each, decide: does it test something `Workflow` still does? If yes, port it to `test/flows/test_engine.py` against a document. If no, it goes. Record the count of ported and dropped tests in the commit message so the loss is visible.

- [ ] **Step 2: Port the surviving tests**

Move them into `test/flows/test_engine.py`, converting each flow class into a `FlowSpec` built with `FlowSpec.model_validate`.

- [ ] **Step 3: Delete the files**

```bash
cd /home/kelvin/librelane
git rm librelane/flows/sequential.py librelane/flows/staged.py librelane/jobs/resolution.py test/flows/test_sequential.py test/jobs/test_resolution.py
```

If `test/flows/test_staged.py` and/or `test/flows/test_explain.py` have nothing left after Step 1/2's audit, `git rm` them here too; otherwise leave the survivors in place.

- [ ] **Step 4: Clean up the package exports**

In `librelane/flows/__init__.py`, remove `SequentialFlow` and `StagedFlow` from the imports and `__all__`.

- [ ] **Step 5: Delete the old `Explanation` shape**

In `librelane/flows/explanation.py`, delete `StepDisposition` and the `steps` and `unselected_stages` fields of `Explanation`, keeping only the `jobs` field phase 4's Task 10 (`--explain` reports jobs) added.

In `librelane/cli/run.py`: remove `SequentialFlow` from the `from librelane.flows import ...` line; remove the `isinstance(flow, SequentialFlow)` branch guarding `--explain` (every flow is a `Workflow` now) so only the `jobs`-based rendering path remains; and delete `format_explanation`'s old body, the one indexing `explanation.steps` and `explanation.unselected_stages`, if phase 4's additive Task 10 (`--explain` reports jobs) left it in place alongside the new one rather than already folding the two into a single function. Today, before phases 1-4, this is the whole of `format_explanation` (line 42 for the import, lines 178-206 for the function, lines 192/201 for the two old-shape reads), but phase 4 is expected to change this file's shape; re-locate by content (`explanation.steps`, `explanation.unselected_stages`, `isinstance(flow, SequentialFlow)`) rather than by these line numbers when this task is executed.

- [ ] **Step 6: Find every remaining reference**

```bash
cd /home/kelvin/librelane
grep -rn "SequentialFlow\|StagedFlow\|gating_config_vars\|stage_boundaries\|provider_boundaries\|StepDisposition\|\.unselected_stages\b\|ResolvedSpan\|ProviderContract" librelane test docs --include="*.py" --include="*.md"
```

Expected after fixing: no output, except a stray `resolve` substring match unrelated to this `resolve()` (`resolve_jobs`, `StageResolutionError`, etc. are fine; `from librelane.jobs.resolution import resolve` or `from librelane.stages.resolution import resolve` is not).

- [ ] **Step 7: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test docs
git commit -m "feat!: delete SequentialFlow, StagedFlow and the gating tables"
```

---

### Task 3: Delete the now-unused step tagging from the registry

**Files:**
- Modify: `librelane/jobs/registry.py`
- Test: `test/jobs/test_registry.py`

**Design notes the implementer needs:**

`librelane/jobs/resolution.py` (`resolve()`, `Resolution`, `ResolvedSpan`, `ProviderContract`) is already gone by this point, deleted whole in Task 2, because it was `StagedFlow`-only. This task is what that deletion leaves behind: `Registration.tagged_steps`, in `librelane/jobs/registry.py`, subclasses every step class to attach `_job_span` and `_job_provider`. Its only production caller was `resolve()` (today's `librelane/stages/resolution.py:231`, `steps.extend(registration.tagged_steps())`), which Task 2 just deleted along with the file it lived in. The only readers of the tags it attaches were `staged.py:240` and `staged.py:647` (today's `getattr(step, "_stage_span", None)` sites; verified by opening both lines in this checkout), also gone. So `tagged_steps` has no caller left at all, not "returns less than it used to": delete the whole method, not just the span-building part of it.

One test pins the tags directly and must be deleted, not adjusted: `test/jobs/test_registry.py:176-177` (today's `test/stages/test_registry.py:176-177`) asserts `tagged[0]._job_span` and `tagged[0]._job_provider`. The sibling test that used to pin the tags from the resolution side, `test/jobs/test_resolution.py:34` (today's `test/stages/test_resolution.py:34`, `not hasattr(resolution.steps[1], "_job_span")`), is already gone with the rest of that file in Task 2, since every test in it exercised `resolve()` directly.

- [ ] **Step 1: Delete the tagging**

In `librelane/jobs/registry.py`, delete the `tagged_steps` method entirely. Grep for `.tagged_steps(` first to confirm it truly has no other caller by this point in the checkout being modified; if one turns up outside the now-deleted `resolve()`, replace that call with `registration.steps` before deleting the method.

- [ ] **Step 2: Delete the test that pins the tags**

```bash
cd /home/kelvin/librelane
grep -rn "_job_span\|_job_provider" librelane test --include="*.py"
```

Delete the test naming them (`test/jobs/test_registry.py`'s `test_tagged_steps_carry_span_and_provider`, today's name). Any remaining production hit is a missed reference.

- [ ] **Step 3: Run the suite, lint, commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: delete the now-unused step tagging in the registry"
```

---

### Task 4: Delete `Flow` as a declaration base

**Files:**
- Modify: `librelane/flows/flow.py`
- Test: `test/flows/test_flow.py`

**Design notes the implementer needs:**

`Flow` keeps everything that is machinery and loses everything that is declaration. Kept: `run_dir`, `toolbox`, `fingerprinter`, `FlowProgressBar`, `get_all_config_variables`, `start`, `start_step`, `start_step_async`, `_save_snapshot_ef` and `FlowFactory.register_document` / `get_document` / `list`. Deleted: `Flow.Steps`, `Flow.Stages`, the abstract `run`, `__init_subclass__`'s handling of a subclass `Config`, `dir_for_step`, `FlowFactory.register` / `get` (the class registry), `get_help_md` and `display_help`.

`get_help_md` cannot stay a `Flow` classmethod: `librelane/flows/flow.py:564` and `:566` read `Self.Steps` directly (`if len(Self.Steps): ... for step in Self.Steps:`) to list a flow's included steps, and `Self.Steps` is deleted by this same task. Its replacement needs the job set, not a class attribute, so it belongs on `Workflow`, reading `self.jobs`. Phase 4's Task 14, "`get_help_md` reads the document's jobs", defines that replacement, plus a static `help_md_for_document` (see Task 1's Step 8 above); this task deletes both old classmethods and reimplements neither. There are two to delete, not one: `Flow.get_help_md` at `flow.py:508`, and `StagedFlow.get_help_md` at `librelane/flows/staged.py:549`, which overrides it to append a `#### Stages` section (`staged.py:549-556`) and goes with the rest of `staged.py` in Task 2, superseded by the same Task 14 replacement. `display_help` (`flow.py:579`-`594`) has no content of its own: both of its branches call `Self.get_help_md()` (`:591`, `:595`) to get the string they print. It goes for the same reason, at the same time.

`dir_for_step` goes because `Workflow.dir_for_job_step` replaced it in phase 2, and its positional numbering is meaningless under concurrency.

`Flow` stops being abstract. It has exactly one subclass, `Workflow`, and phase 5's whole point is that there will not be a second. Consider merging `Flow` into `Workflow` rather than keeping a one-subclass hierarchy; if the merged file exceeds roughly 800 lines, keep them separate and say so in the commit message, because a single unreadable file is a worse outcome than a shallow hierarchy.

`test_factory` in `test/flows/test_flow.py` registers and retrieves a `Dummy` flow through `Flow.factory.register()`/`Flow.factory.get()`; Task 1's Step 7 already removed its `Classic`/`OpenInKLayout`/`OpenInOpenROAD` membership assertion, since that broke earlier when the classes were deleted. What is left of `test_factory` here exercises exactly the class registry this task deletes, so delete it (or the whole function, if nothing else in it survives) in Step 3 below.

- [ ] **Step 1: Delete the declaration surface**

Remove `Steps`, `Stages`, the abstract `run`, `dir_for_step`, `get_help_md`, `display_help`, and the `Config` branch of `__init_subclass__`. Remove `ABC` from `Flow`'s bases.

- [ ] **Step 2: Delete the class registry**

Remove `FlowFactory.register` and `FlowFactory.get`. `FlowFactory.list` now lists document names.

- [ ] **Step 3: Fix the tests**

```bash
cd /home/kelvin/librelane
grep -rn "Flow.factory.register()\|Flow.factory.get(\|\.Steps\b\|\.Stages\b\|dir_for_step\|get_help_md\|display_help" librelane test docs --include="*.py" --include="*.md"
```

Every hit becomes `Flow.factory.get_document(...)`, a document, `dir_for_job_step`, or a call into `Workflow`'s job-based help renderer, phase 4's replacement for `get_help_md`/`display_help`.

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
- Modify: `librelane/jobs/job.py`, `librelane/jobs/taxonomy.py`, `librelane/jobs/registry.py`, `librelane/flows/job.py`
- Test: `test/jobs/`

`librelane/jobs/resolution.py` is not in this list: Task 2 already deleted it whole, since it was `StagedFlow`-only and never shared with the new engine. An earlier draft of this plan listed it here too, on the assumption it survived and needed its provider-selection logic narrowed for the tuple-to-single-provider change; that assumption is now known to be wrong, so there is nothing left in that file for this task to touch.

**Design notes the implementer needs:**

All three existed to serve a `Stages` list that no longer exists.

`Job.using` returned an unregistered copy with a pinned provider, for use in a flow's list. A document says `uses: job/provider` instead.

`multi_provider` allowed one entry to run several providers' step sequences concatenated. A document says two jobs instead, which is strictly clearer: `streamout` becomes `magic_streamout` and `klayout_streamout`, each independently switchable, which is what the two `RUN_*_STREAMOUT` booleans were emulating.

`optional` allowed a job to be left unselected and contribute no steps, which was only needed because a list had to mention every job. A document omits it.

Deleting `multi_provider` means `default_provider` is always a single `str | None`, and `default_providers` collapses to `(default_provider,)` or `()`. Update `_resolve` in `librelane/flows/job.py`, whose provider loop was written for the tuple case, and the taxonomy entries that declare a tuple default. In this checkout, before phase 3's rename, that is two entries in `librelane/stages/taxonomy.py` (`streamout` and `drc`, both `default_provider=("magic", "klayout")`, lines 273 and 282), not four; re-run the grep below against `librelane/jobs/taxonomy.py` once phase 3 has landed in case it adds more multi-provider entries, and update the count here if so.

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
  `OpenInOpenROAD`, `OpenInOpenROADConsole`, `OpenInOpenSTAConsole` and
  `OpenInMagic` as importable classes. The eight flows ship
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
* `StepDisposition` and the `steps`/`unselected_stages` fields of `Explanation`
  are deleted. `--explain` reports `Explanation.jobs`, one `JobDisposition`
  per job, added in phase 4.
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
grep -rn "SequentialFlow\|StagedFlow\|gating_config_vars\|tagged_steps\|ResolvedSpan\|multi_provider\|\.using(\|dir_for_step\|\-\-from\|\-\-to\b\|StepDisposition\|\.unselected_stages\b\|\bChip\b\|VHDLClassic\|OpenInKLayout\|OpenInOpenROAD\|OpenInOpenROADConsole\|OpenInOpenSTAConsole\|OpenInMagic" librelane test docs --include="*.py" --include="*.md"
```

Expected: no output, except a bare `"Classic"`/`"Chip"`/etc. string naming a document (a `--flow` argument, a `meta.flow` value, a document's own `name:` field) and the changelog entries these deletions themselves added. Any hit that is a Python symbol (an import, a class reference, an attribute access) is a missed deletion.

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
