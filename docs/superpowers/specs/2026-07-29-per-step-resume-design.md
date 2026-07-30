# Per-Step Resume

**Status:** Design approved, ready for planning
**Date:** 2026-07-29
**Scope:** Reuse of completed step output within a single run directory.
Cross-run and cross-design caching is deliberately out of scope.

## Problem

LibreLane has no caching system, and what it calls resuming a run does not
resume anything.

The only things in the tree named "cache" are two in-process memoizations that
die with the process. `Step._config_model_cache`
(`librelane/steps/step/core.py:207`) memoizes a class's Pydantic config model,
keyed on a fingerprint of its variable list. `Toolbox.remove_cells_from_lib` and
`Toolbox.create_blackbox_model` are wrapped in `lru_cache(16)`
(`librelane/common/toolbox.py:56-57`). Neither has anything to do with step
output. No content hashing exists anywhere in the package.

`Flow.start` (`librelane/flows/flow.py:615-743`) reuses a run directory when
given `--last-run` or a `--run-tag` naming an existing tag. It scans the `NN-slug`
entries, calls `Step.load_finished` on each, sets
`starting_ordinal = max(ordinal) + 1`, and seeds the initial state from the
newest `state_out.json` anywhere under the run directory by modification time
(`get_latest_file`, `librelane/common/misc.py:327`).

`SequentialFlow.run` then computes `executing = frm is None`
(`librelane/flows/sequential.py:367`). No step is ever tested for having already
completed. With no `--from`, every step runs again.

### Observed behaviour

A four step flow (`StepB, StepA, StepA-1, StepA-2`) run against tag `T`:

```
RUN1  --to StepA-1               dirs: 1-test-stepb 2-test-stepa 3-test-stepa-1
                                 step metric: 2
RUN2  --last-run                 dirs: + 4-test-stepb 5-test-stepa
                                        6-test-stepa-1 7-test-stepa-2
                                 step metric: 6
RUN3  --last-run --from StepA-2  dirs: + 8-test-stepa-2
                                 step metric: 7
```

RUN2 re-executed all four steps and appended four new directories, seeded with
RUN1's final state. `test/flows/test_flow.py:338-345` asserts exactly this
behaviour today, via `state.metrics["step"] == 3` after a second
`start(tag="MY_TAG2")`.

### Defects this causes

1. **Upstream steps receive a downstream state.** RUN2's first step was handed
   RUN1's final state. A step declaring `inputs` will consume views produced by
   later steps of the previous pass.
2. **Metrics accumulate across passes.** The `step` counter went 2, 6, 7. The
   final state's metrics are a blend of every pass.
3. **`step_objects` double counts.** Steps loaded from disk are appended
   alongside freshly run ones (`librelane/flows/flow.py:679`, `:711`, `:801`), so
   RUN2 ended with seven entries for a four step flow. `_save_snapshot_ef`
   iterates `self.step_objects` (`:1019`) and copies the same step's DRC and LVS
   reports more than once, and `step_objects[-1]` becomes ambiguous.
4. **`load_finished` loses duplicate ID suffixes.** Directory
   `3-test-stepa-1` loaded back with id `Test.StepA` rather than `Test.StepA-1`,
   because `config.json` records the implementation id. Any per-id lookup over
   loaded steps is wrong.
5. **Ordinal drift produces duplicate directories.** RUN3 created
   `8-test-stepa-2` beside `7-test-stepa-2` for the same step. Combined with
   modification time selection in `get_latest_file`, a stale `state_out.json`
   that happens to be touched later can win.
6. **Partial step directories are silently accepted.** `Flow.start` swallows
   `FileNotFoundError` from `Step.load_finished` (`:721-722`), so a step
   directory left half written by an interrupted run is indistinguishable from
   an absent one.

The only escape today is `--overwrite`, which deletes the run directory.

## Goals

Reuse a completed step's output when nothing it depended on has changed, so that
re-invoking a flow after a crash, an interrupt, or an edit late in the flow costs
only the work that is actually stale.

Be correct in the presence of edited input files, not merely of changed
configuration values.

Leave `runs/TAG` a clean mirror of the flow rather than an accumulation of
passes.

Remove the defects listed above rather than working around them.

## Non-goals

**Cross-run or cross-design reuse.** No shared store, no artifact copying or
hardlinking, no path rewriting in a reused state, no garbage collection, no
concurrency safety across runs. Reuse is confined to a step's own directory
inside one run directory.

**Detecting an in-place CAD tool upgrade.** The key records LibreLane's version
and the step's implementation id, both of which are already written to
`config.json`. Upgrading `openroad` in place, or editing a `.tcl` script in a
development checkout, without changing LibreLane's version, will not invalidate
anything. The documented remedy is `--from` or `--overwrite`. Introducing a
uniform `Step` hook for tool and script identity was considered and rejected as
a separate piece of work.

**Resume for non-sequential flows.** `Optimizing`
(`librelane/flows/optimizing.py:121-170`) retries floorplanning in a
data-dependent loop and `SynthesisExploration`
(`librelane/flows/synth_explore.py:96`) fans out per strategy. Neither has a
fixed step list, so neither can have stable step directories. They keep the
existing running counter and are never offered a resume candidate.

## Design decisions

**Reuse is scoped to one run directory.** A step's candidate is its own prior
output at its own stable path. Nothing is copied.

**Step directories become positional for sequential flows.** Step *i* always
occupies `runs/TAG/<i+1>-<slug>`. A hit leaves the directory untouched; a miss
deletes and rewrites that one directory.

**File identity is a content hash, memoized on stat.** Not a stat fingerprint
alone. Nix store paths carry epoch normalized mtimes, so a rebuild can leave
mtime unchanged while content differs, and a bare `touch` would otherwise
invalidate everything for no reason.

**Directories contribute identity, never content.** `DESIGN_DIR` and `PDK_ROOT`
are `Path` typed but are directories, and they appear in every step's config
because they are universal flow variables. Content hashing `DESIGN_DIR` would
hash `DESIGN_DIR/runs/`, which contains the run in progress, so the key would
never stabilise. This is safe because every PDK file that matters is enumerated
explicitly as a file path: `LIB`, `TECH_LEFS`, `CELL_LEFS`, `CELL_GDS`,
`CELL_VERILOG_MODELS`, `CELL_SPICE_MODELS`, `CELL_CDLS`, and the `EXTRA_*` and
`PAD_*` families.

**The whole input state participates, metrics included.** Checker steps read
`state_in.metrics`, so excluding metrics would be wrong. Including them costs
nothing, because a step reused from cache reproduces its metrics exactly.

**Resume is the default and the append behaviour is deleted.** Two coherent
modes remain: resume into an existing tag, or `--overwrite` to start clean. A
third mode that re-executes a whole flow into a populated directory serves no
purpose.

**The decision is made in `SequentialFlow.run`.** Placing it in `Step.start`
would apply it to flows whose directories are not stable enough for a hit to be
meaningful, and would grow an already long `@final` method with a concern the
step cannot validate.

## Architecture

### New module `librelane/common/fingerprint.py`

```python
class Fingerprinter:
    """Content identity for files referenced by configurations and states."""

    def __init__(self) -> None:
        self.__memo: dict[tuple[str, int, int], str] = {}

    def of_path(self, path: str | os.PathLike[str]) -> str:
        """
        :returns: An identity string for ``path``:

            * ``file:<digest>`` for a regular file, where the digest is a
              128-bit BLAKE2b over its bytes
            * ``dir:<abspath>`` for a directory
            * ``absent:<abspath>`` when nothing exists at the path
        """
```

The memo is keyed on `(fspath, st_size, st_mtime_ns)`, so each file is read at
most once per run even though the same PDK views appear in many steps' configs.
`Flow` gains a `fingerprinter: Fingerprinter | None` attribute, assigned in
`Flow.start` alongside `toolbox` and living for the duration of the run. This is
what `SequentialFlow.run` reads as `self.fingerprinter` below.

An absent path yields a distinct identity rather than raising, which is what
turns a deleted output view into a miss with no special casing.

### New module `librelane/flows/resume.py`

```python
RESUME_ENTRY_FILENAME = "resume.json"
RESUME_SCHEMA_VERSION = 1


def resume_key(step: Step, state_in: State, fingerprinter: Fingerprinter) -> str:
    document = {
        "schema": RESUME_SCHEMA_VERSION,
        "step": type(step).get_implementation_id(),
        "librelane_version": __version__,
        "config": _substitute_paths(step.config.to_raw_dict(), fingerprinter),
        "state_in": _substitute_paths(
            state_in.to_raw_dict(metrics=True), fingerprinter
        ),
    }
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), cls=GenericDictEncoder
    )
    return hashlib.blake2b(canonical.encode("utf8"), digest_size=16).hexdigest()
```

`_substitute_paths` walks nested mappings, sequences and dataclasses, replacing
every `librelane.common.Path` instance with `fingerprinter.of_path(...)` and
leaving other scalars alone.

Two traps in that walk are worth stating, because getting either wrong produces a
key that looks plausible and is silently wrong.

**It must recurse into dataclasses.** `MACROS` is `dict[str, Macro]`, and `Macro`
(`librelane/config/legacy.py:96`) is a dataclass whose fields are `list[Path]` and
`dict[str, list[Path]]`: `gds`, `lef`, `vh`, `nl`, `pnl`, `spef`, `lib`, `spice`,
`sdf`, `json_h`. A walk that only descends mappings and lists would leave those
`Path` objects untouched, `GenericDictEncoder` would stringify them
(`librelane/common/generic_dict.py:43-44`), and editing a macro's GDS would fail
to invalidate the steps that consume it. Hierarchical designs are a core use
case, so this is not an edge case.

**`Path` must be tested before any sequence check.** `Path` subclasses
`UserString` (`librelane/common/types.py:39`), so it satisfies
`isinstance(x, Sequence)`. A sequence branch reached first would iterate a path
character by character and fingerprint each one. The `Path` branch comes first,
and the sequence branch matches `(list, tuple)` explicitly rather than
`Sequence`.

Two properties of the existing code make this cheap and precise:

`step.config` is already filtered to the step's own `config_vars` plus the
universal flow variables (`librelane/steps/step/core.py:290-302`), so the key
covers exactly what the step can read and nothing more.

`BaseConfigModel.to_raw_dict` calls `model_dump(mode="python")`
(`librelane/config/model.py:153-157`), which preserves `Path` instances,
including inside lists. `State.__load_recursive` likewise reconstructs `Path`
objects. So `isinstance(value, Path)` is a sound test in both structures.

### The entry file

`step_dir/resume.json`:

```json
{
  "schema": 1,
  "key": "<digest>",
  "step": "OpenROAD.Floorplan",
  "librelane_version": "..."
}
```

Written by the flow only after `step.start()` returns without raising.

Its presence is therefore also the marker for "this step completed", which
replaces the current practice of inferring completion from the presence of three
JSON files and swallowing `FileNotFoundError` when they are incomplete.

A step that raised `DeferredStepError` never gets an entry, so it re-executes on
the next resume and raises again. No deferred failure bookkeeping is needed.

### Hit condition

All of the following, or else it is a miss:

1. `resume.json` exists, parses, and its `schema` equals
   `RESUME_SCHEMA_VERSION`
2. its `key` equals the freshly computed key
3. `state_out.json` exists and parses
4. every `Path` in the loaded output state exists on disk

Condition 4 is an existence test only. The output views are deliberately not
fingerprinted: their content is what the key attests to, and re-hashing a
multi-gigabyte GDS to confirm what the entry already asserts would cost more than
the step it is trying to avoid. A user who edits a step's output by hand and
expects that to be noticed is outside what this design promises.

### `SequentialFlow.run`

```python
step = cls(config=self.config, state_in=current_state)
step_dir = self.dir_for_step(step, position=i)
key = resume_key(step, current_state, self.fingerprinter)

if _hit(step_dir, key):
    step.step_dir = step_dir
    step.state_out = State.loads((step_dir / "state_out.json").read_text())
    current_state = step.state_out
    step_list.append(step)
else:
    shutil.rmtree(step_dir, ignore_errors=True)
    current_state = step.start(toolbox=self.toolbox, step_dir=step_dir)
    step_list.append(step)
    _write_entry(step_dir, key)
```

### A reused step counts as executed

`SequentialFlow.run` calls `self._after_step(step, current_state, executed)`
(`librelane/flows/sequential.py:429`), and `StagedFlow._after_step`
(`librelane/flows/staged.py:183`) uses it to enforce the stage contract, skipping
the check for any stage not all of whose steps executed. `Classic` is a
`StagedFlow` (`librelane/flows/classic.py:35`), so this governs the default flow.

A resumed step must therefore be reported with `executed=True`. It genuinely
produced the contracted views and metrics, and they are present in the state being
checked. Reporting a hit as not executed would silently disable contract
enforcement for every stage containing a reused step, which is precisely the
regression the contract was added to catch.

This also means `executed` stops being derivable from `increment_ordinal`, which
today doubles as the executed signal (`librelane/flows/sequential.py:403-429`).
The two are separated: `executed` covers "ran or was reused", and the progress
bar's ordinal bookkeeping is left to the progress bar.

### Positional step directories

`Flow.dir_for_step` gains an optional `position` parameter. When given, the
prefix is `position + 1` zero padded to `len(str(len(self.Steps)))`. When
omitted, the existing running counter behaviour is retained, which is what
`Optimizing` and `SynthesisExploration` continue to use.

The padding width is unchanged from today, so for a clean full `Classic` run with
no gated steps the directory names are byte identical to current output. Runs
with gated or skipped steps will differ: positional numbering leaves a gap where
today's dense counter does not. That is the intended trade, because a step's path
must not depend on how many earlier steps happened to run.

#### When the step list changes between runs

`SequentialFlow` supports `Substitutions`
(`librelane/flows/sequential.py:98`, applied at `:117-119` via
`__substitute_in_place` at `:211`), and a user may resume a tag with a
different flow or a substituted step list. Positions then shift, so a step
finding a different step's directory at its position will compute a different key
and miss. The `step` field recorded in `resume.json` is not consulted for the hit
decision, because the key already covers the implementation id; it is recorded for
diagnosis.

Directories left behind by a longer previous step list are not deleted. They
belong to no current position, so they are never read, and a later run of the
longer list re-checks them normally. This is the same property that makes `--to Y`
followed by a plain resume continue rather than restart.

### Deletions from `Flow.start`

The `Step.load_finished` loop that pre-populates `step_objects`
(`librelane/flows/flow.py:708-724`) and the `_no_load_previous_steps` parameter
are removed.

The `get_latest_file(self.run_dir, "state_out.json")` initial state seeding
(`:726-733`) is removed.

Both become unreachable in intent once each step resolves its own state, and
removing them retires defects 1, 2, 3 and 4 directly: no step receives a
downstream state, metrics no longer accumulate, `step_objects` holds each step
once, and no step loses its duplicate ID suffix because the object is
constructed by the flow rather than reconstructed from `config.json`.

`starting_ordinal` is retained and still seeds the progress bar counter, but only
flows using the running counter consume it. `with_initial_state` is still
honoured, and because it feeds step 1's `state_in`, passing a different initial
state correctly invalidates the run.

One behaviour change follows for non-sequential flows: `Optimizing` re-run into
an existing tag now begins from an empty state rather than a stale state derived
from modification times.

## Flow control options under resume

**`--from X` means force re-execution from X onward.** Steps before X resolve
from cache and must hit. A stale predecessor raises `FlowException` naming it,
rather than proceeding with an empty state and failing later on a missing input.
Steps from X onward execute unconditionally, their directories deleted first,
whether or not their keys match.

This redefinition is required, not incidental: the state that today's `--from`
relies upon is the modification time seeding being removed. It is also the
documented remedy for the non-goal above, an in-place tool upgrade.

**`--to Y` is unchanged.** Directories past Y are left alone. A later resume
re-checks them normally, so `--to` followed by a plain resume continues the flow.

**`--skip S` and gating variables** pass the state through untouched. Downstream
steps therefore see a different `state_in` than in a non-skipped run and
correctly miss.

## Error handling

An unparseable `resume.json` or `state_out.json`, a schema mismatch, or a missing
output view is classified as a miss and logged at `VERBOSE`. A truncated file
after `kill -9` is an expected condition, and a miss is the correct reading of
"cannot prove a hit".

Interruption during a step leaves no entry, so that step misses next time.

`--from X` with a stale predecessor raises `FlowException` identifying the step.

A run directory path that exists as a file keeps the current
`NotADirectoryError` handling.

## Testing

Tests are written before implementation.

### `test/common/test_fingerprint.py`

Content change alters the digest. Identical content at a different path yields
the same digest. A `touch` that preserves content yields the same digest despite
the memo miss. The memo causes one read per file, asserted with a spy. A
directory is never read. An absent path yields an identity distinct from any
file's.

### `test/flows/test_resume.py`

Using the existing pyfakefs and dummy step pattern from
`test/flows/test_flow.py`, with an execution counter on the dummy steps:

- clean run then resume performs zero executions and leaves directories untouched
- a config change at step *k* leaves steps before *k* hit and executes *k* onward
- an edited input file with every path unchanged causes a miss, which is the case
  a path equality design gets wrong
- a crash at *k* leads a resume to execute only *k* onward
- a `DeferredStepError` at *k* leaves no entry, so *k* re-executes and raises again
- a deleted output view causes a miss
- `--from X` forces re-execution and raises when a predecessor is stale
- `--skip` invalidates downstream steps
- directory names are stable across resumes, and a gated step leaves a gap
- `--overwrite` deletes the run directory

### Existing tests

`test/flows/test_flow.py::test_run_tags` asserts the append behaviour via
`state.metrics["step"] == 3`. It is rewritten to assert reuse.

## Documentation

A resume section in the usage documentation covering the two modes, what
invalidates a step, and the tool upgrade caveat with its `--from` and
`--overwrite` remedies.

A `Changelog.md` entry.
