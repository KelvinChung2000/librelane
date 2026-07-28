# Track 2: Ruff Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace black, flake8, and flake8-pytest-style with ruff for both formatting and linting, fix the broken mypy stub path, and modernize legacy typing syntax, without changing runtime behavior.

**Architecture:** Land in three distinct phases with separate blame: first a ruff config that faithfully mirrors the *existing* flake8 policy (so the linter turning on is a no-op), then the formatting sweep as one isolated mechanical commit, then the typing modernization split into a safe half and a behavior-affecting half. The split matters because `librelane/config/variable.py` introspects annotations at runtime.

**Tech Stack:** ruff, mypy.

## Global Constraints

See [the roadmap](2026-07-28-modernization-roadmap.md#global-constraints). Applies in full. Most relevant here:

- **Track 1 must be complete.** This plan invokes tools via `uv run` and edits the `Makefile` `lint` target that Track 1 rewrote.
- **This track must complete before Track 4.** The formatting sweep touches 46 files; if it runs after the step-module splits, every new file is touched twice and the splits stop being reviewable as pure moves.
- Python floor is `>=3.10`, so PEP 585 (`list[str]`) and PEP 604 (`X | None`) are both valid at runtime.

## Measured Baseline (2026-07-28)

Established by running ruff against the tree, not estimated.

| Metric | Value | Command |
|---|---|---|
| Files `ruff format` would change | **46** | `ruff format --diff .` |
| `E`+`F` violations in `librelane/` | 755 raw | `ruff check --select E,F --statistics librelane/` |
| ↳ of which `E501` line-too-long | 626 | already waived by `.flake8`'s `E5` ignore |
| ↳ of which `F401` unused-import | 123, **all in `__init__.py`** | already waived by `.flake8`'s per-file-ignore |
| ↳ genuine backlog | **~6** (`E731`×3, `E721`×2, `E713`×1) | |
| `UP` violations | 1349, 986 auto-fixable | `ruff check --select UP --statistics` |
| ↳ `UP006` non-pep585 (safe) | 612 | |
| ↳ `UP045`+`UP007` non-pep604 (**behavior-affecting**) | 519 | see Task 9 |
| ↳ `UP035` deprecated-import | 158 | |

**The headline number is misleading.** Once ruff mirrors the policy `.flake8` already encodes, the real lint backlog is about six issues. Do not let "755 errors" drive a staged rollout that is not needed.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `pyproject.toml` | ruff config, lint deps | Modify `[tool.ruff]`; swap `[dependency-groups] lint` |
| `.flake8` | flake8 config | Delete (Task 4) |
| `.mypy.ini` | mypy config | Modify `mypy_path`, add `check_untyped_defs` |
| `Makefile` | `lint` target | Modify to ruff |
| `.github/workflows/ci.yml` | `lint` job | Unchanged if `make lint` is the entry point |
| `docs/source/contributors/code.md` | contributor docs | Modify to match the real command |
| `librelane/**/*.py`, `test/**/*.py` | source | Mechanical reformat + typing sweeps |

---

### Task 1: Add ruff with a config that mirrors existing flake8 policy

The current `[tool.ruff]` block sets `lint.ignore = ["E", "F"]`, which disables essentially everything. Turning ruff on without fixing that yields a linter that reports nothing. Turning it on *without* mirroring `.flake8` yields 755 spurious errors. Neither is useful.

**Files:**
- Modify: `pyproject.toml:36-55` (`[dependency-groups] lint`), `:72-76` (`[tool.ruff]`)

**Interfaces:**
- Consumes: Track 1's uv setup.
- Produces: a working `uv run ruff check .`, consumed by Tasks 2, 4, 7, 8, 9.

- [ ] **Step 1: Add ruff to the lint dependency group**

Add `"ruff"` to `[dependency-groups] lint` in `pyproject.toml`. Leave black and flake8 in place for now; Task 4 removes them once ruff is proven equivalent.

- [ ] **Step 2: Replace the `[tool.ruff]` block**

Replace lines 72-76 entirely:

```toml
[tool.ruff]
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = [
  # Formatting is the formatter's job, and .flake8 waived E5/E1/E2/E3 historically.
  "E501",  # line-too-long
  "E731",  # lambda-assignment: 3 deliberate uses
  "E721",  # type-comparison: 2 deliberate uses
  "W291", "W293",  # trailing whitespace: formatter's job
]

[tool.ruff.lint.per-file-ignores]
# Re-exports. Mirrors .flake8's `*/__init__.py:F401`.
"**/__init__.py" = ["F401"]

[tool.ruff.format]
# Match the existing black-formatted style.
quote-style = "double"
indent-style = "space"
```

- [ ] **Step 3: Verify the mirrored config is near-silent on the current tree**

```bash
uv run ruff check . --statistics
```

Expected: at most a handful of violations (`E713` and anything in `test/`, which `.flake8` currently excludes entirely). If you see hundreds, the config does not mirror existing policy — fix the config, do not start fixing code.

- [ ] **Step 4: Confirm the count is small enough to fix inline**

```bash
uv run ruff check . --output-format concise | wc -l
```

Expected: single or low double digits. Record the number.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "lint: add ruff with a config mirroring existing flake8 policy

The previous [tool.ruff] block ignored E and F, disabling nearly every
rule. This mirrors what .flake8 actually waives (E501, E731, E721,
per-file F401 in __init__.py) so enabling ruff is a no-op, not a
755-violation cliff."
```

---

### Task 2: Fix the genuine violations

**Files:**
- Modify: whichever files Task 1 Step 4 listed

- [ ] **Step 1: List the real violations with context**

```bash
uv run ruff check . --output-format full
```

- [ ] **Step 2: Auto-fix what is safely fixable**

```bash
uv run ruff check . --fix
```

Expected: `E713` (`not-in-test`) fixed automatically.

- [ ] **Step 3: Fix anything remaining by hand**

Read each one and fix it. Do not add a blanket ignore to make the count zero.

- [ ] **Step 4: Verify clean and the suite still passes**

```bash
uv run ruff check . && uv run pytest -q
```

Expected: `All checks passed!` and `147 passed, 1 deselected, 1 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "lint: fix remaining ruff violations"
```

---

### Task 3: Run the formatting sweep

One isolated commit, no other changes. 46 files change. Anyone bisecting later needs this to be unambiguous.

**Files:**
- Modify: 46 files across `librelane/` and `test/`

**Interfaces:**
- Consumes: the `[tool.ruff.format]` config from Task 1.
- Produces: a tree that is `ruff format --check` clean. **Track 4 depends on this having landed.**

- [ ] **Step 1: Confirm the working tree is clean before a mechanical sweep**

```bash
git status --short
```

Expected: no modified tracked files. Commit or stash anything outstanding first.

- [ ] **Step 2: Record which files will change**

```bash
uv run ruff format --diff . 2>/dev/null | grep "^---" | wc -l
```

Expected: 46.

- [ ] **Step 3: Apply the format**

```bash
uv run ruff format .
```

- [ ] **Step 4: Verify the reformat is semantically inert**

The suite must be identical, and the only diff must be whitespace and line breaks.

```bash
uv run pytest -q
git diff --stat | tail -1
git diff -w --stat | tail -1
```

Expected: `147 passed, 1 deselected, 1 xfailed`. The `git diff -w` (ignore-whitespace) stat should be dramatically smaller than the plain one. Any file showing substantive non-whitespace change under `-w` deserves a manual read before committing.

- [ ] **Step 5: Commit, and record the hash for `.git-blame-ignore-revs`**

```bash
git add -A
git commit -m "style: reformat with ruff format

Mechanical. No semantic changes; test suite output identical."
git rev-parse HEAD
```

- [ ] **Step 6: Add the sweep to the blame-ignore file**

Create `.git-blame-ignore-revs` with the hash from Step 5:

```
# Mechanical reformat: black -> ruff format
<paste-hash-here>
```

Then:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
git add .git-blame-ignore-revs
git commit -m "chore: ignore the ruff format sweep in git blame"
```

---

### Task 4: Retire black and flake8

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups] lint`), `Makefile` (`lint`), `docs/source/contributors/code.md`
- Delete: `.flake8`

- [ ] **Step 1: Prove ruff format agrees with black before removing black**

```bash
uv run black --check . && echo "BLACK-CLEAN"
uv run ruff format --check . && echo "RUFF-CLEAN"
```

Expected: both print their clean marker. If black disagrees after Task 3's sweep, the two formatters differ on this tree — resolve that before removing black, and record the divergence in the commit message.

- [ ] **Step 2: Remove black, flake8, and flake8-pytest-style from the lint group**

Delete those three entries from `[dependency-groups] lint` in `pyproject.toml`. Keep `ruff`, `mypy`, and the stub packages (Task 6 prunes those).

- [ ] **Step 3: Rewrite the Makefile lint target**

```makefile
.PHONY: lint
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
```

Note `mypy .` without `--check-untyped-defs` — Task 5 moves that flag into `.mypy.ini` so the CLI and the config agree.

- [ ] **Step 4: Delete the flake8 config**

```bash
git rm .flake8
```

- [ ] **Step 5: Update the contributor docs to the real command**

In `docs/source/contributors/code.md`, replace any black/flake8 instructions and the stale "ruff targets Python 3.8" reference with the actual invocation:

````markdown
Run `make lint` to check formatting, linting, and types. To auto-fix:

```console
$ uv run ruff check --fix .
$ uv run ruff format .
```
````

- [ ] **Step 6: Verify lint runs end to end with black and flake8 uninstalled**

```bash
uv sync --all-groups --locked
uv run black --version 2>&1 | head -1   # expect: failure / not found
make lint
```

Expected: black is gone; `make lint` completes. mypy may report pre-existing errors — that is Task 5's territory, note the count and move on.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "lint: retire black and flake8 in favour of ruff

ruff format verified byte-equivalent to black on this tree before
removal. flake8's waivers are mirrored in [tool.ruff.lint]."
```

---

### Task 5: Fix the broken mypy stub path

`.mypy.ini:2` reads `mypy_path = "./mypy_stubs"`. Two independent bugs: the value is quoted, and mypy's INI parser does not strip quotes; and no `mypy_stubs/` directory exists — the real one is `type_stubs/`. The checked-in stubs have never been loaded.

**Files:**
- Modify: `.mypy.ini`

- [ ] **Step 1: Reproduce the failure**

```bash
ls type_stubs/
uv run mypy --config-file .mypy.ini librelane/scripts/pyosys/ys_common.py 2>&1 | head -5
```

Expected: `type_stubs/` exists and contains stub files; mypy reports a missing-stub or missing-import error for a module that `type_stubs/` provides.

- [ ] **Step 2: Fix both bugs**

In `.mypy.ini`, replace line 2 with the unquoted, correct path, and add the flag the Makefile was passing on the CLI:

```ini
[mypy]
mypy_path = ./type_stubs
check_untyped_defs = True
exclude = venv|build|odbpy|scripts/klayout|scripts/pyosys|docs|designs|setup.py|test|sandbox
```

- [ ] **Step 3: Verify the stubs now load**

```bash
uv run mypy --config-file .mypy.ini librelane/scripts/pyosys/ys_common.py 2>&1 | head -5
```

Expected: the missing-stub error from Step 1 is gone.

- [ ] **Step 4: Confirm the whole-tree run is no worse than before**

```bash
uv run mypy . 2>&1 | tail -3
```

Expected: an error count less than or equal to the pre-fix count. Loading stubs should *reduce* errors. If it increases them, the stubs disagree with real usage — read the new errors before proceeding.

- [ ] **Step 5: Commit**

```bash
git add .mypy.ini
git commit -m "types: fix mypy_path and codify check_untyped_defs

mypy_path was both quoted (mypy's ini parser does not strip quotes)
and pointed at a nonexistent mypy_stubs/; the real directory is
type_stubs/. The checked-in stubs had never been loaded.
check_untyped_defs moves from a Makefile CLI flag into config so a
bare `mypy .` matches what CI enforces."
```

---

### Task 6: Prune unused type stub packages

Verified by import search: nine stub packages correspond to zero imports anywhere under `librelane/`.

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups] lint`)

- [ ] **Step 1: Re-verify before deleting**

```bash
for p in six urllib3 setuptools docutils decorator commonmark colorama Pygments typed_ast lxml; do
  printf "%s: " "$p"
  grep -rn "^import $p\|^from $p" librelane/ 2>/dev/null | wc -l
done
```

Expected: `0` for the first nine. **`lxml` also reports 0** — verify that separately before pruning `lxml-stubs`, since `lxml` is a declared runtime dependency and may be imported under an alias or inside a string annotation.

- [ ] **Step 2: Remove the nine confirmed-unused stubs**

Delete these from `[dependency-groups] lint`: `types-six`, `types-urllib3`, `types-setuptools`, `types-docutils`, `types-decorator`, `types-commonmark`, `types-colorama`, `types-Pygments`, `types-typed-ast`.

Keep `types-psutil` (2 imports), `types-PyYAML` (5 imports), `types-Deprecated` (4 imports).

- [ ] **Step 3: Verify mypy's error count did not change**

```bash
uv lock && uv sync --all-groups
uv run mypy . 2>&1 | tail -3
```

Expected: identical to Task 5 Step 4's count. If it rose, one of the pruned stubs was load-bearing — restore it and note why.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "lint: prune 9 type stub packages with zero matching imports

mypy error count unchanged before and after."
```

---

### Task 7: Bring test/ under lint

`.flake8` excludes `test/` entirely (6,341 lines). A consequence is that `flake8-pytest-style`, which only has rules for pytest files, had nothing to check. Ruff's `PT` rules replace it.

Because ruff auto-fixes, this does **not** need the staged rollout a flake8-based un-exclusion would have needed.

**Files:**
- Modify: `pyproject.toml` (`[tool.ruff.lint]`), `test/**/*.py`

- [ ] **Step 1: Measure the backlog with pytest rules on**

```bash
uv run ruff check --select E,F,W,PT test/ --statistics
```

Record the total and how many are auto-fixable.

- [ ] **Step 2: Add `PT` to the selected rules**

In `pyproject.toml`, change `select = ["E", "F", "W"]` to `select = ["E", "F", "W", "PT"]`. Mirror the one waiver `.flake8` had: add `"PT001"` to the `ignore` list.

- [ ] **Step 3: Auto-fix**

```bash
uv run ruff check --fix test/ librelane/
```

- [ ] **Step 4: Fix the remainder by hand and verify**

```bash
uv run ruff check . && uv run pytest -q
```

Expected: `All checks passed!` and `147 passed, 1 deselected, 1 xfailed`. The test count must not change — a lint fix that alters test collection is a bug in the fix.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "lint: bring test/ under ruff, enable pytest-style rules

test/ was excluded from flake8 entirely, which left
flake8-pytest-style with zero files to check. Ruff's PT rules replace
it and auto-fix most of the backlog."
```

---

### Task 8: Modernize builtin generics (safe sweep)

`UP006` converts `Dict[str, int]` → `dict[str, int]`, `List[x]` → `list[x]`, and so on. 612 occurrences, all marked safely fixable. `get_origin()` returns the same value for both spellings, so this does not disturb the runtime type introspection in `librelane/config/variable.py`.

**Files:**
- Modify: `librelane/**/*.py`, `test/**/*.py`

- [ ] **Step 1: Record the pre-sweep test baseline**

```bash
uv run pytest -q
```

Expected: `147 passed, 1 deselected, 1 xfailed`.

- [ ] **Step 2: Apply only UP006 and UP035**

```bash
uv run ruff check --select UP006,UP035 --fix librelane/ test/
```

- [ ] **Step 3: Re-format, since the rewrite changes line lengths**

```bash
uv run ruff format .
```

- [ ] **Step 4: Verify behavior is unchanged, with emphasis on the type-introspection tests**

```bash
uv run pytest -q
uv run pytest test/config/test_variable.py -v
```

Expected: `147 passed, 1 deselected, 1 xfailed`, and every `test_variable.py` test passing. That file is the canary for this whole track.

- [ ] **Step 5: Verify mypy did not regress**

```bash
uv run mypy . 2>&1 | tail -3
```

Expected: error count less than or equal to Task 6's.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "style: adopt PEP 585 builtin generics (UP006, UP035)

Mechanical. get_origin() returns identical values for both spellings,
so config/variable.py's runtime type introspection is unaffected."
```

- [ ] **Step 7: Add this hash to `.git-blame-ignore-revs` too**

```bash
git rev-parse HEAD
```

Append it to `.git-blame-ignore-revs` with a comment, then commit.

---

### Task 9: Modernize union syntax (gated sweep)

**This is the one genuinely risky task in the track.** Read this before running anything.

`UP045`/`UP007` convert `Optional[X]` → `X | None` and `Union[A, B]` → `A | B`. That is not cosmetic here. `librelane/config/variable.py` introspects annotations at runtime:

- `variable.py:225` — `(origin is Union or origin is types.UnionType)`
- `variable.py:241` — `if origin is types.UnionType:`
- `variable.py:567-568` — `get_origin(validating_type)`, `get_args(validating_type)`

`get_origin(Optional[int])` returns `typing.Union`. `get_origin(int | None)` returns `types.UnionType`. These are different objects, and `variable.py` branches on the difference. Converting a `Variable` declaration's annotation flips which branch executes for that variable. The test fixed in Track 1 Task 1 is precisely about this distinction.

**Files:**
- Modify: `librelane/**/*.py` **except** `librelane/config/`, then `librelane/config/` separately

- [ ] **Step 1: Sweep everything except config/ first**

```bash
uv run ruff check --select UP007,UP045 --fix librelane/steps/ librelane/flows/ librelane/common/ librelane/state/ librelane/logging/ test/
uv run ruff format .
```

- [ ] **Step 2: Verify**

```bash
uv run pytest -q && uv run mypy . 2>&1 | tail -3
```

Expected: `147 passed, 1 deselected, 1 xfailed`; mypy no worse.

- [ ] **Step 3: Commit the safe portion before touching config/**

```bash
git add -A
git commit -m "style: adopt PEP 604 union syntax outside config/

config/ is excluded because variable.py branches on
get_origin(...) is types.UnionType vs typing.Union at runtime."
```

- [ ] **Step 4: Write a characterization test for config/ BEFORE converting it**

This test must pass both before and after the conversion. It pins the behavior that the sweep could silently change.

Create `test/config/test_union_syntax_equivalence.py`:

```python
from typing import Optional, Union

from librelane.config.variable import Variable


def test_optional_and_pep604_produce_equivalent_variables():
    """A Variable declared with Optional[int] must behave identically to one
    declared with int | None, since UP045 rewrites the former into the latter."""
    old = Variable("OLD", Optional[int], "legacy spelling", default=None)
    new = Variable("NEW", int | None, "pep604 spelling", default=None)

    assert old.some == new.some, "some_of disagrees across union spellings"
    assert old.required == new.required, "requiredness disagrees"

    for value in (5, None, "7"):
        assert old.compile({"OLD": value}, []) == new.compile(
            {"NEW": value}, []
        ), f"compile disagrees across union spellings for {value!r}"


def test_multi_arg_union_equivalent():
    old = Variable("OLD", Union[int, str], "legacy spelling", default=None)
    new = Variable("NEW", int | str, "pep604 spelling", default=None)

    assert old.some == new.some
    for value in (5, "x"):
        assert old.compile({"OLD": value}, []) == new.compile({"NEW": value}, [])
```

- [ ] **Step 5: Run it against the un-converted config/ to confirm it passes today**

```bash
uv run pytest test/config/test_union_syntax_equivalence.py -v
```

Expected: PASS. If it FAILS, **stop** — the two spellings are genuinely not equivalent in this codebase, and the `config/` conversion must not proceed. Record the failure and leave `librelane/config/` on the legacy spelling permanently, adding a `per-file-ignores` entry for `UP007`/`UP045`.

Note: `Variable.compile`'s exact signature must be confirmed against `librelane/config/variable.py` when you write this — adjust the call if it differs. The assertion structure is what matters.

- [ ] **Step 6: Only if Step 5 passed, convert config/**

```bash
uv run ruff check --select UP007,UP045 --fix librelane/config/
uv run ruff format .
```

- [ ] **Step 7: Verify with the characterization test and the full suite**

```bash
uv run pytest test/config/ -v
uv run pytest -q
uv run mypy . 2>&1 | tail -3
```

Expected: all config tests pass, `148 passed` (the original 147 plus the two new characterization tests, minus collection differences — confirm the delta is exactly the tests you added), mypy no worse.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "style: adopt PEP 604 union syntax in config/

Gated on a characterization test asserting Optional[X] and X | None
produce equivalent Variable behavior, since variable.py branches on
get_origin(...) is types.UnionType vs typing.Union."
```

---

## Track 2 Definition of Done

- [ ] `uv run ruff check .` → `All checks passed!`
- [ ] `uv run ruff format --check .` → clean
- [ ] `make lint` runs ruff and mypy only; black and flake8 are uninstalled
- [ ] `.flake8` is deleted
- [ ] `.mypy.ini` points at `type_stubs/` unquoted and sets `check_untyped_defs`
- [ ] `uv run pytest -q` → `149 passed, 1 deselected, 1 xfailed` (147 baseline + 2 characterization tests)
- [ ] `.git-blame-ignore-revs` lists both mechanical sweeps
- [ ] CI green

## Self-Review Notes

- **The 755-violation number is a trap** and the plan says so explicitly in the baseline table. A reader who does not check the breakdown would design a multi-week staged rollout for roughly six real issues.
- **Task 9 is the only task that can silently change behavior**, and it is the only one gated on a characterization test written *before* the change. Step 5 has an explicit stop-and-abandon branch rather than a "work around it" instruction.
- **Task 3 and Task 8 both end by recording a hash** in `.git-blame-ignore-revs`, because two large mechanical sweeps in one track would otherwise wreck `git blame` for the whole codebase.
- **Ordering dependency on Track 4 is stated in the constraints**, not just implied.
- Task 9 Step 4's test references `Variable.compile`; the plan flags that the signature must be confirmed against the real file rather than assumed.
