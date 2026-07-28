# Track 1: uv Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the poetry-export-to-pip install pipeline with uv as the single dependency and build toolchain, without changing any declared dependency or shipped wheel content.

**Architecture:** `pyproject.toml` is already pure PEP 621 with PEP 735 `[dependency-groups]` and zero `[tool.poetry]` fields, so this is a toolchain swap, not a metadata rewrite. Replace `poetry.lock` with `uv.lock`, swap the build backend from `poetry-core` to `hatchling`, and collapse the three-command export dance into a single `uv sync` at every install site. The shipped wheel must be byte-for-byte equivalent in file listing before and after.

**Tech Stack:** uv 0.10.11, hatchling, Nix, GitHub Actions.

## Global Constraints

See [the roadmap](2026-07-28-modernization-roadmap.md#global-constraints). Applies in full. Most relevant here:

- `requires-python = ">=3.10"`. Do not add an upper bound.
- Local interpreter is Python 3.14.3; uv resolves to it by default.
- `default.nix` uses `format = "pyproject"` and lists `poetry-core` at lines 38 and 80. Any `[build-system]` change requires a matching `default.nix` change **in the same commit**.
- Run tooling via `uv run`.

## Build Backend Decision

**Use `hatchling`, not `uv_build`.**

Rationale: `hatchling` is packaged in nixpkgs as `python3Packages.hatchling`, so `default.nix` can swap `poetry-core` for it directly. `uv_build` is uv's own backend and is newer; if it is not in the pinned nixpkgs revision, `default.nix` cannot build and Track 1 stalls on a packaging problem unrelated to its goal. uv-the-workflow-tool and hatchling-the-build-backend compose fine — using uv does not require using its backend.

To switch to `uv_build` later, it is a two-line change in `[build-system]` plus the matching `default.nix` input, gated on confirming nixpkgs availability.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `test/config/test_variable.py` | `some_of` unit tests | Modify lines 127-134: identity → equality for Union comparisons |
| `pyproject.toml` | Package metadata, deps, tool config | Modify `[build-system]`; add `[tool.hatch.build.targets.wheel]`; add `docs` dependency group |
| `uv.lock` | Resolved dependency graph with hashes | Create |
| `poetry.lock` | Superseded | Delete |
| `docs/requirements.txt` | Superseded by the `docs` group | Delete |
| `Makefile` | Dev entry points | Modify `venv`, `lint`, `docs`, `coverage-*`, `dist` targets |
| `.github/workflows/ci.yml` | CI | Modify install steps at lines 47-51 and the `lint` job at 111-115 |
| `default.nix` | Nix package build | Modify build backend (38, 80) and deps (45, 105) |
| `.gitignore` | Ignore rules | Add `requirements_tmp.txt`, `result` |

---

### Task 1: Fix the Python 3.14 Union identity test

This is a genuine pre-existing bug, not a uv problem, and it must be green before the toolchain changes so that any later failure is unambiguously attributable to the migration.

`some_of(Optional[Union[Dict, List]])` returns a `typing.Union` object that is *equal to* but not *identical to* a separately constructed one. On CPython <3.14 the interning happened to make `is` hold; on 3.14 it does not. `is` was never a guaranteed relationship here.

**Files:**
- Modify: `test/config/test_variable.py:127-134`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a green baseline. Later tasks assert `147 passed`.

- [ ] **Step 1: Run the test to observe the current failure**

```bash
uv run --frozen pytest test/config/test_variable.py::test_some_of -v
```

Expected: FAIL with `AssertionError: some of failed to properly handle optional union` at `test/config/test_variable.py:128`, showing `assert typing.Dict | typing.List is typing.Dict | typing.List`.

- [ ] **Step 2: Change the two Union comparisons from identity to equality**

Only the two assertions that compare *Union objects* change. The `is int` assertions on lines 121, 126, and 136 are correct as-is, because `int` is a real class and identity does hold.

Replace lines 127-134 with:

```python
    assert (
        some_of(Optional[Union[Dict, List]]) == Union[Dict, List]
    ), "some of failed to properly handle optional union"

    assert (
        some_of(Union[Dict, List, None]) == Union[Dict, List]
    ), "some of failed to properly handle flattened optional union"
```

- [ ] **Step 3: Run the test to verify it passes**

```bash
uv run --frozen pytest test/config/test_variable.py::test_some_of -v
```

Expected: PASS.

- [ ] **Step 4: Run the whole suite to confirm a clean baseline**

```bash
uv run --frozen pytest -q
```

Expected: `147 passed, 1 deselected, 1 xfailed`. Record this number; every later task compares against it.

- [ ] **Step 5: Commit**

```bash
git add test/config/test_variable.py
git commit -m "fix(test): compare Union types by equality, not identity

typing.Union objects are equal but not identical across separate
constructions. CPython <3.14 interned them such that `is` happened to
hold; 3.14 does not. Identity was never a guaranteed relationship here."
```

---

### Task 2: Generate uv.lock and verify dependency parity

**Files:**
- Create: `uv.lock`
- Test: shell comparison of resolved package sets

**Interfaces:**
- Consumes: green baseline from Task 1.
- Produces: `uv.lock`, consumed by every later task and by CI.

- [ ] **Step 1: Record the poetry-resolved dependency set as the reference**

```bash
uv run --with poetry poetry export --all-groups --without-hashes --format=requirements.txt 2>/dev/null \
  | grep -v '^#' | grep -v '^$' | sed 's/ ;.*//' | cut -d= -f1 | tr 'A-Z_.' 'a-z--' | sort -u > /tmp/poetry-deps.txt
wc -l /tmp/poetry-deps.txt
```

- [ ] **Step 2: Generate the uv lockfile**

```bash
uv lock
```

Expected: `uv.lock` created. This resolves against `requires-python = ">=3.10"`, so the lock covers 3.10 through 3.14.

- [ ] **Step 3: Record the uv-resolved dependency set**

```bash
uv export --all-groups --no-hashes --format requirements-txt 2>/dev/null \
  | grep -v '^#' | grep -v '^$' | sed 's/ ;.*//' | cut -d= -f1 | tr 'A-Z_.' 'a-z--' | sort -u > /tmp/uv-deps.txt
wc -l /tmp/uv-deps.txt
```

- [ ] **Step 4: Diff the two sets and account for every difference**

```bash
diff /tmp/poetry-deps.txt /tmp/uv-deps.txt
```

Expected: empty, or differences you can explain individually. A package present under poetry but absent under uv means a dependency was silently dropped — stop and investigate, do not proceed. Extra packages under uv are usually resolver differences on optional/marker-gated deps and are acceptable if each one is traced to a real marker.

- [ ] **Step 5: Verify the suite still passes against the uv-resolved environment**

```bash
uv sync --all-groups && uv run pytest -q
```

Expected: `147 passed, 1 deselected, 1 xfailed`.

- [ ] **Step 6: Commit**

```bash
git add uv.lock
git commit -m "build: add uv.lock

Resolved dependency set verified identical to poetry export."
```

---

### Task 3: Swap the build backend to hatchling

The risk here is not the backend itself, it is **package data**. `librelane/` ships non-Python files that must land in the wheel: `librelane/pdk_hashes.yaml`, `librelane/py.typed`, and the whole of `librelane/scripts/` (TCL, Python, and config files consumed at flow runtime). A wheel that silently drops them installs fine and fails at flow execution. The verification step below is the point of this task.

**Files:**
- Modify: `pyproject.toml:86-88` (`[build-system]`), add `[tool.hatch.build.targets.wheel]`
- Test: wheel and sdist content listing comparison

**Interfaces:**
- Consumes: `uv.lock` from Task 2.
- Produces: a wheel with content identical to the poetry-core wheel. Task 7 depends on the backend name.

- [ ] **Step 1: Build the reference wheel and sdist with the current backend**

Do this **before** editing anything.

```bash
rm -rf dist/
uv build
ls dist/
unzip -l dist/librelane-*.whl | awk '{print $4}' | grep -v '^$' | sort > /tmp/wheel-poetry.txt
tar tzf dist/librelane-*.tar.gz | sed 's|^[^/]*/||' | sort > /tmp/sdist-poetry.txt
wc -l /tmp/wheel-poetry.txt /tmp/sdist-poetry.txt
```

- [ ] **Step 2: Confirm the reference wheel actually contains the package data**

If this fails, the current build is already broken and that is a separate bug to fix first.

```bash
grep -c 'librelane/scripts/' /tmp/wheel-poetry.txt
grep -E 'pdk_hashes\.yaml|py\.typed' /tmp/wheel-poetry.txt
```

Expected: a non-zero count for `scripts/`, and both `librelane/pdk_hashes.yaml` and `librelane/py.typed` present.

- [ ] **Step 3: Swap the build backend**

In `pyproject.toml`, replace:

```toml
[build-system]
requires = ["poetry-core>=2.0.0,<3"]
build-backend = "poetry.core.masonry.api"
```

with:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["librelane"]

[tool.hatch.build.targets.sdist]
include = [
  "librelane/",
  "test/",
  "Readme.md",
  "License",
  "Changelog.md",
]
```

- [ ] **Step 4: Rebuild and diff the wheel contents**

```bash
rm -rf dist/
uv build
unzip -l dist/librelane-*.whl | awk '{print $4}' | grep -v '^$' | sort > /tmp/wheel-hatch.txt
diff /tmp/wheel-poetry.txt /tmp/wheel-hatch.txt
```

Expected: empty diff, ignoring `.dist-info/` metadata filenames which legitimately differ between backends. Any missing `librelane/` path is a blocker — fix the `[tool.hatch.build.targets.wheel]` config until the diff is clean.

- [ ] **Step 5: Verify the built wheel actually works when installed**

A clean file listing is necessary but not sufficient. Install it into a throwaway environment and exercise the entry point.

```bash
uv run --isolated --no-project --with dist/librelane-*.whl python -c "
import librelane, importlib.resources as r
print('version:', librelane.__version__)
print('pdk_hashes:', (r.files('librelane') / 'pdk_hashes.yaml').is_file())
print('py.typed:', (r.files('librelane') / 'py.typed').is_file())
print('scripts:', (r.files('librelane') / 'scripts').is_dir())
"
```

Expected: version printed, and all three checks `True`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml
git commit -m "build: switch build backend from poetry-core to hatchling

Wheel content listing verified identical, and package data
(pdk_hashes.yaml, py.typed, scripts/) confirmed present in an
isolated install of the built wheel."
```

---

### Task 4: Fold docs/requirements.txt into a dependency group

`docs/requirements.txt` is the one dependency surface not captured by any lockfile. Folding it in puts it under `uv.lock`.

Version bumps are deliberately **out of scope** for this task — moving the file and changing the pins in one commit makes a docs build failure ambiguous between the two causes. Bump in Task 4b.

**Files:**
- Modify: `pyproject.toml` (`[dependency-groups]`)
- Delete: `docs/requirements.txt`
- Modify: `Makefile` docs target (also touched in Task 5; do the docs-specific part here)

**Interfaces:**
- Consumes: `uv.lock` from Task 2.
- Produces: a `docs` dependency group, consumed by `make docs` and by Track 3's docs CI job.

- [ ] **Step 1: Add the docs group to `[dependency-groups]`, pins unchanged**

Append to the `[dependency-groups]` table in `pyproject.toml`, copying the pins verbatim from `docs/requirements.txt`:

```toml
docs = [
    "furo==2023.8.19",
    "docutils>=0.17,<1",
    "sphinx>=7.2.2",
    "sphinx-autobuild>=2021.3.14",
    "sphinx-autodoc-typehints>=1.24.0",
    "sphinx-design>=0.5.0,<1",
    "myst-parser>=2.0.0,<3",
    "docstring-parser>=0.15,<1",
    "sphinx-tippy>=0.4.1,<1",
    "sphinx-copybutton>=0.5.2,<1",
    "sphinxcontrib-spelling>=8.0.0,<9",
    "sphinxcontrib-bibtex>=2.6.0,<3",
    "sphinx-subfigure>=0.2.4,<1",
]
```

- [ ] **Step 2: Re-lock and build the docs to verify the group works**

```bash
uv lock
uv run --group docs make -C docs html
```

Expected: Sphinx completes and `docs/build/html/index.html` exists.

```bash
test -f docs/build/html/index.html && echo OK
```

- [ ] **Step 3: Delete the superseded requirements file**

```bash
git rm docs/requirements.txt
```

- [ ] **Step 4: Rebuild docs from the group alone to confirm nothing still reads the deleted file**

```bash
rm -rf docs/build && uv run --group docs make -C docs html && test -f docs/build/html/index.html && echo OK
```

Expected: `OK`. If Sphinx fails on a missing package, that package was in `docs/requirements.txt` but not copied into the group — add it.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: fold docs/requirements.txt into the docs dependency group

Docs dependencies are now covered by uv.lock. Pins unchanged; bumps
are a separate commit so a docs failure is unambiguous."
```

---

### Task 4b: Bump the stale docs and runtime pins

Separate commit, separate blame, so a break is attributable.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Bump the clearly stale docs pins**

In the `docs` group: `furo==2023.8.19` → `furo>=2024.8.6`, and `myst-parser>=2.0.0,<3` → `myst-parser>=2.0.0,<5` (the `<3` cap already excludes released 4.x and 5.x). Leave `sphinx>=7.2.2` uncapped as-is unless the build breaks.

- [ ] **Step 2: Add the missing upper bounds on runtime deps**

`lxml` and `psutil` have no upper bound while their neighbours do. Make the policy consistent:

```toml
  "lxml>=4.9.0,<7",
  "psutil>=5.9.0,<8",
```

- [ ] **Step 3: Re-lock and run the full verification**

```bash
uv lock && uv sync --all-groups && uv run pytest -q && uv run --group docs make -C docs html
```

Expected: `147 passed, 1 deselected, 1 xfailed`, and the docs build succeeds.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: bump stale docs pins and bound lxml/psutil

furo was ~2 years behind; myst-parser's <3 cap excluded released 4.x.
lxml and psutil were the only unbounded runtime deps."
```

---

### Task 5: Replace the Makefile install pipeline with uv

The current `venv/manifest.txt` target installs poetry and poetry-plugin-export, exports without hashes, and pip-installs the result. `uv sync` replaces all of it and keeps hash verification.

**Files:**
- Modify: `Makefile` (`dist`, `venv`, `lint`, `docs`, `coverage-infrastructure`, `coverage-steps`, `veryclean` targets)

**Interfaces:**
- Consumes: `uv.lock` (Task 2), hatchling backend (Task 3), `docs` group (Task 4).
- Produces: `make lint`, `make docs`, `make dist` entry points that CI reuses in Task 6.

- [ ] **Step 1: Replace the venv bootstrap and the targets that depend on it**

Replace the `dist` target, the `venv`/`venv/manifest.txt` targets, and update the targets that assumed `./venv/bin/`:

```makefile
all: dist
.PHONY: dist
dist:
	uv build

.PHONY: venv
venv:
	uv sync --all-groups
	@echo ">> Environment prepared. Use 'uv run <command>'."
```

Update the tool-invoking targets to go through uv:

```makefile
.PHONY: lint
lint:
	uv run black --check .
	uv run flake8 .
	uv run mypy --check-untyped-defs .

.PHONY: docs
docs:
	uv run --group docs $(MAKE) -C docs html

.PHONY: host-docs
host-docs:
	uv run python3 -m http.server --directory ./docs/build/html

.PHONY: coverage-infrastructure
coverage-infrastructure:
	uv run pytest -n auto \
		--cov=librelane --cov-config=.coveragerc --cov-report html:htmlcov_infra --cov-report term

.PHONY: coverage-steps
coverage-steps:
	uv run pytest -n auto \
		--cov=librelane.steps --cov-config=.coveragerc-steps --cov-report html:htmlcov_steps --cov-report term \
		-k test_all_steps
```

Note: `lint` still runs black and flake8 here. Track 2 replaces them with ruff. Do not conflate the two changes.

Remove the `veryclean` target's `rm -rf venv/`, since there is no longer a `venv/` directory to remove:

```makefile
.PHONY: veryclean
veryclean: clean
	rm -rf .venv/
```

- [ ] **Step 2: Verify each rewritten target actually runs**

```bash
make venv
make lint
make dist && ls dist/
rm -rf docs/build && make docs && test -f docs/build/html/index.html && echo DOCS-OK
```

Expected: `make venv` syncs, `make lint` runs all three linters (it may report existing violations — that is fine and is Track 2's problem, what matters is that the tools *run*), `make dist` produces a wheel and sdist, `DOCS-OK` prints.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build: drive all Makefile targets through uv

Replaces the poetry-export-to-pip bootstrap, which discarded
poetry.lock's hashes via --without-hashes at every install site."
```

---

### Task 6: Switch CI to uv

**Files:**
- Modify: `.github/workflows/ci.yml:47-51` (the `prepare-test-matrices` install block) and `:111-115` (the `lint` job)

**Interfaces:**
- Consumes: the Makefile targets from Task 5.
- Produces: a CI that installs via uv. Track 3 modifies the same file, so land this first.

- [ ] **Step 1: Replace the install block in `prepare-test-matrices`**

Lines 49-51 currently read:

```yaml
          pip3 install poetry poetry-plugin-export
          poetry export --all-groups --without-hashes --format=requirements.txt --output=requirements_tmp.txt
          pip3 install -r requirements_tmp.txt
```

Replace the whole step with the official uv setup action plus a sync. Add before the step that needs dependencies:

```yaml
      - name: Set Up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install Dependencies
        run: uv sync --all-groups --locked
```

`--locked` fails the build if `uv.lock` is out of date with `pyproject.toml`, which is the integrity property the old `--without-hashes` export threw away.

- [ ] **Step 2: Replace the `lint` job's install and invocation**

Lines 111-115 currently install via `make venv` then prepend `venv/bin` to `PATH`. Replace with:

```yaml
      - name: Set Up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Lint
        run: make lint
```

The `actions/setup-python@v6` step at 107-110 can stay; uv honours the interpreter it provides.

- [ ] **Step 3: Find and replace every other `make venv` / poetry reference**

```bash
grep -n "make venv\|poetry\|requirements_tmp\|venv/bin" .github/workflows/ci.yml
```

Every hit must either be converted to `uv sync --all-groups --locked` or explained. Note line 495 uses `perl` to scrape the `ciel` version out of `poetry.lock` — that must be repointed at `uv.lock` or, better, at `pyproject.toml`. Line 627 (`python3 -m pip install -e .`) can become `uv pip install -e .`.

- [ ] **Step 4: Validate the workflow file parses**

```bash
uv run --with pyyaml python -c "
import yaml, sys
d = yaml.safe_load(open('.github/workflows/ci.yml'))
print('jobs:', len(d['jobs']))
print(sorted(d['jobs']))
"
```

Expected: 11 jobs listed, no parse error.

- [ ] **Step 5: Confirm no poetry references survive**

```bash
grep -n "poetry" .github/workflows/ci.yml Makefile || echo "CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 6: Commit and push to observe a real CI run**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: install dependencies with uv sync --locked

Replaces the poetry export-to-pip pipeline. --locked restores the
integrity checking that --without-hashes discarded."
git push origin librelane-unstalbe
```

Then watch the run. This is the first task whose verification is not fully local:

```bash
gh run watch
```

Expected: `lint` and `prepare-test-matrices` green. If a nix-based job fails, that is Task 7's territory.

---

### Task 7: Update default.nix

Must land with Task 3's backend change to keep the nix build working. If you are executing tasks strictly in order, the nix build is broken between Task 3 and here — that is expected and is why this task follows immediately.

**Files:**
- Modify: `default.nix:38,80` (build backend), `:45,105` (dependencies)

**Interfaces:**
- Consumes: the `hatchling` backend from Task 3.
- Produces: a working `nix build`.

- [ ] **Step 1: Swap the build backend input**

At `default.nix:38`, replace the `poetry-core,` argument with `hatchling,`. At line 80, replace `poetry-core` in `nativeBuildInputs` with `hatchling`. Leave `format = "pyproject";` at line 75 unchanged — it is correct for both backends.

- [ ] **Step 2: Fix the drifted dependency list**

At `default.nix:45`, replace the `requests,` argument with `httpx,`. At line 105, replace `requests` with `httpx` in the propagated dependency list.

`requests` is imported nowhere (`grep -rn "import requests" librelane/` returns nothing). `httpx` is imported unconditionally in `librelane/container.py`, `librelane/common/misc.py`, and `librelane/common/metrics/__main__.py`, and currently only resolves because `ciel` pulls it in transitively.

- [ ] **Step 3: Verify the claim before trusting it**

```bash
grep -rn "import requests" librelane/ || echo "requests: UNUSED, safe to drop"
grep -rn "^import httpx\|^from httpx" librelane/
```

Expected: `requests: UNUSED, safe to drop`, and three or more `httpx` import sites.

- [ ] **Step 4: Build the nix package**

```bash
nix build .#librelane -L 2>&1 | tail -30
```

Expected: build succeeds. If `hatchling` is not available in the pinned nixpkgs, this is where you find out — fall back to keeping `poetry-core` in `[build-system]` and re-evaluate the backend decision rather than pinning a newer nixpkgs mid-track.

- [ ] **Step 5: Verify the nix-built package imports and has its data files**

```bash
nix build .#librelane --no-link --print-out-paths
uv run --isolated --no-project python -c "print('see nix result path above')"
nix run .#librelane -- --version
```

Expected: version prints.

- [ ] **Step 6: Commit**

```bash
git add default.nix
git commit -m "nix: use hatchling backend; fix drifted dependency list

requests was declared but imported nowhere; httpx is imported
unconditionally in three modules and only resolved transitively
through ciel."
```

---

### Task 8: Remove poetry.lock and tidy ignores

**Files:**
- Delete: `poetry.lock`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm nothing still reads poetry.lock**

```bash
grep -rn "poetry.lock" . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=docs/build || echo "NO REFERENCES"
```

Expected: `NO REFERENCES`. If `ci.yml:495`'s ciel-version scrape still points at it, Task 6 Step 3 was incomplete — go back and fix it.

- [ ] **Step 2: Delete the lockfile**

```bash
git rm poetry.lock
```

- [ ] **Step 3: Ignore the build artifacts that currently sit untracked in the working tree**

Append to `.gitignore`:

```
# uv
.venv/

# stale poetry export artifact
requirements_tmp.txt

# nix build symlink
result
```

- [ ] **Step 4: Confirm a clean working tree and a green suite**

```bash
git status --short
uv sync --all-groups --locked && uv run pytest -q
```

Expected: no untracked build artifacts reported; `147 passed, 1 deselected, 1 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "build: drop poetry.lock, ignore uv and nix artifacts"
```

---

## Track 1 Definition of Done

- [ ] `uv sync --all-groups --locked && uv run pytest -q` → `147 passed, 1 deselected, 1 xfailed`
- [ ] `make lint`, `make docs`, `make dist` all run without poetry installed
- [ ] `nix build .#librelane -L` succeeds
- [ ] `grep -rn poetry . --exclude-dir=.git` returns nothing outside this plan document
- [ ] CI is green on `librelane-unstalbe`
- [ ] The built wheel contains `librelane/scripts/`, `librelane/pdk_hashes.yaml`, and `librelane/py.typed`

## Self-Review Notes

- **Backend risk is real and is checked.** Task 3 Steps 4 and 5 verify wheel contents *and* an isolated install, because a dropped `librelane/scripts/` directory installs cleanly and fails only at flow runtime.
- **Task 3 and Task 7 are coupled.** The nix build is broken between them. If you need every commit to be independently green, squash them.
- **Task 1 is not optional and not cosmetic.** With system Python at 3.14.3, uv resolves there by default, so the suite is red before this fix and there would be no clean signal to migrate against.
- **Version bumps are isolated** in Task 4b so a docs break is attributable to the bump rather than to the group move.
