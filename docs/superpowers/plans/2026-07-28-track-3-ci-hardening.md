# Track 3: CI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix real bugs in `ci.yml`, remove duplication via composite actions, close supply-chain gaps, and add the `Step.factory` registry check that Track 4 depends on as its safety net.

**Architecture:** No reusable-workflow split and no `nix flake check` wrapping — both are deferred with reasons recorded in [the roadmap](2026-07-28-modernization-roadmap.md#deferred-indefinitely-do-not-build). What lands instead is a mechanical cleanup pass plus one durable discipline: no `run:` step under `.github/` may contain more than one call into a script or nix target, extending the pattern `.github/scripts/gh.py:98-121` already establishes for local/CI dual-mode execution.

**Tech Stack:** GitHub Actions, composite actions, Dependabot.

## Global Constraints

See [the roadmap](2026-07-28-modernization-roadmap.md#global-constraints). Applies in full. Most relevant:

- **Track 1 must be complete** — it already rewrote the install steps in `ci.yml`, and this track edits the same file.
- **Track 4 depends on Task 9 of this plan.** Do not start the step-module splits until the registry check is running in CI.
- Do not force `step_impl_test` into `build-py`. See Task 8.

## Verified Baseline (2026-07-28)

Every item below was confirmed by reading the file, not inferred.

| Finding | Evidence |
|---|---|
| **Darwin PDK cache key is broken** | `ci.yml:243` uses `steps.set-rev.outputs.opdks_rev`. `build-darwin` has no `set-rev` step (it is in `prepare-test-matrices` at :62), and `opdks_rev` was never an output name — the declared outputs are `sky130_hash`, `gf180mcu_hash`, `ihp-sg13g2_hash` (`:41-44`). Key silently degrades to the constant `cache-sky130-pdk-`. |
| **`get_test_matrix.py` runs twice** | `ci.yml:59` runs it and discards stdout; `:60` runs the identical command again to capture it. |
| **`build-appimages` lacks `fail-fast: false`** | Present on five jobs (`:122, 222, 391, 451, 553`); `build-appimages` (`:262`) is the only matrix job without it. |
| **`check_space` action is dead** | `.github/actions/check_space/action.yml` exists; `grep -rn check_space .github/` finds no reference. |
| **`remove-unwanted-software@v5` duplicated 6×** | `:287, 348, 397, 455, 558, 678` |
| **Unpinned third-party actions** | `fossi-foundation/...@main` ×3 (`:161, 193, 253`), `DeterminateSystems/nix-installer-action@main` (`.github/actions/setup_nix/action.yml:35`), `remove-unwanted-software@v5` ×6, `tvdias/github-tagger@v0.0.1` (`:762`), `softprops/action-gh-release@v2` (`:768`) |
| **One `permissions:` block in 783 lines** | `:672`, in `publish`, `id-token: write` only |
| **No governance files** | `SECURITY.md`, `CONTRIBUTING.md`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `.github/dependabot.yml` all absent |
| **Docs never built in CI** | `make docs` exists; no job invokes it |

The three `@main` refs are the sharpest exposure: `nix_sign_cache_s3@main` receives `NIX_PRIVATE_KEY`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` at `:253-260`.

---

### Task 1: Fix the Darwin PDK cache key

**Files:**
- Modify: `.github/workflows/ci.yml:243`

- [ ] **Step 1: Confirm the bug**

```bash
sed -n '240,245p' .github/workflows/ci.yml
grep -n "id: set-rev" .github/workflows/ci.yml
sed -n '41,44p' .github/workflows/ci.yml
```

Expected: the cache key references `steps.set-rev.outputs.opdks_rev`; the only `set-rev` step is at line 62 inside `prepare-test-matrices`; the declared outputs are the three `*_hash` names.

- [ ] **Step 2: Fix both halves of the bug**

`build-darwin` already declares `needs: [lint, prepare-test-matrices]` (`:224`), so the cross-job reference is available. Replace line 243:

```yaml
          key: cache-sky130-pdk-${{ needs.prepare-test-matrices.outputs.sky130_hash }}
```

- [ ] **Step 3: Verify no other job has the same mistake**

```bash
grep -n "steps.set-rev" .github/workflows/ci.yml
```

Expected: only hits inside `prepare-test-matrices` (lines 62-76), where `steps.` is the correct context.

- [ ] **Step 4: Validate the workflow parses**

```bash
uv run --with pyyaml python -c "
import yaml
d = yaml.safe_load(open('.github/workflows/ci.yml'))
print('jobs:', sorted(d['jobs']))
"
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: fix the darwin sky130 PDK cache key

Referenced steps.set-rev.outputs.opdks_rev from build-darwin, but
set-rev lives in prepare-test-matrices and opdks_rev was never an
output name. The key silently resolved to the constant
'cache-sky130-pdk-', so the cache never invalidated on a PDK bump."
```

---

### Task 2: Remove the duplicated matrix computation and fix fail-fast

**Files:**
- Modify: `.github/workflows/ci.yml:57-60`, `:262-263`

- [ ] **Step 1: Confirm the double invocation**

```bash
sed -n '56,61p' .github/workflows/ci.yml
```

Expected: two `run:` lines invoking `get_test_matrix.py` with identical arguments, the first discarding output.

- [ ] **Step 2: Delete the discarded invocation**

Remove line 59 entirely, keeping only the line that writes to `$GITHUB_OUTPUT`.

- [ ] **Step 3: Add the missing `fail-fast: false` to `build-appimages`**

In the `build-appimages` job's `strategy:` block, add `fail-fast: false` alongside `matrix:`, matching the other five matrix jobs. Without it, one architecture failing cancels the other's in-flight nix build.

- [ ] **Step 4: Verify all matrix jobs now agree**

```bash
grep -c "fail-fast: false" .github/workflows/ci.yml
```

Expected: `6`.

- [ ] **Step 5: Validate and commit**

```bash
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"
git add .github/workflows/ci.yml
git commit -m "ci: drop duplicated matrix computation, add missing fail-fast

get_test_matrix.py ran twice with the first result discarded.
build-appimages was the only matrix job without fail-fast: false."
```

---

### Task 3: Extract the disk-space composite action

Six verbatim copies of the same block. This is the single largest duplication in the file.

**Files:**
- Create: `.github/actions/maximize_space/action.yml`
- Modify: `.github/workflows/ci.yml` at `:287, 348, 397, 455, 558, 678`

- [ ] **Step 1: Read one copy to capture its exact inputs**

```bash
sed -n '286,294p' .github/workflows/ci.yml
```

- [ ] **Step 2: Confirm all six copies are actually identical**

```bash
for l in 287 348 397 455 558 678; do
  echo "--- line $l ---"
  sed -n "$((l-1)),$((l+7))p" .github/workflows/ci.yml
done
```

If any copy differs in its `with:` inputs, the composite action needs those as parameters. Do not assume uniformity — read the output.

- [ ] **Step 3: Create the composite action**

Write `.github/actions/maximize_space/action.yml`, substituting the real `with:` values observed in Step 2:

```yaml
name: "Maximize Build Space"
description: "Frees runner disk space by removing preinstalled toolchains not used by this build."
runs:
  using: "composite"
  steps:
    - uses: AdityaGarg8/remove-unwanted-software@v5
      with:
        remove-android: "true"
        remove-dotnet: "true"
        remove-haskell: "true"
        remove-codeql: "true"
```

- [ ] **Step 4: Replace all six call sites**

Each becomes:

```yaml
      - name: Maximize Build Space
        uses: ./.github/actions/maximize_space
```

- [ ] **Step 5: Verify no direct references remain**

```bash
grep -c "remove-unwanted-software" .github/workflows/ci.yml
grep -c "remove-unwanted-software" .github/actions/maximize_space/action.yml
```

Expected: `0` in the workflow, `1` in the action.

- [ ] **Step 6: Validate and commit**

```bash
uv run --with pyyaml python -c "
import yaml
yaml.safe_load(open('.github/workflows/ci.yml'))
yaml.safe_load(open('.github/actions/maximize_space/action.yml'))
print('OK')
"
git add .github/actions/maximize_space/action.yml .github/workflows/ci.yml
git commit -m "ci: extract maximize_space composite action

Replaces 6 verbatim copies of the remove-unwanted-software block."
```

---

### Task 4: Resolve the dead check_space action

`.github/actions/check_space/action.yml` exists and is referenced nowhere. Either wire it in or delete it; leaving a dead action beside hand-rolled equivalents is the worst of both.

**Files:**
- Modify or delete: `.github/actions/check_space/action.yml`
- Possibly modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read what it does and find the hand-rolled equivalents**

```bash
cat .github/actions/check_space/action.yml
grep -n "du -\|df -\|tree " .github/workflows/ci.yml
```

- [ ] **Step 2: Decide, based on Step 1's output**

If the hand-rolled blocks do substantively the same thing, replace them with `uses: ./.github/actions/check_space`. If they do not, or if the debug output is no longer wanted, `git rm -r .github/actions/check_space`.

Record the decision in the commit message either way.

- [ ] **Step 3: Verify consistency**

```bash
grep -rn "check_space" .github/
```

Expected: either every reference resolves to the action, or zero references and no action directory.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "ci: resolve the unused check_space action"
```

---

### Task 5: Pin third-party actions to commit SHAs

A floating `@main` ref combined with `AWS_SECRET_ACCESS_KEY` and `NIX_PRIVATE_KEY` is the most concrete security exposure in the repo. `docker/login-action` at `:693` is already SHA-pinned, so the precedent exists.

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/actions/setup_nix/action.yml:35`

- [ ] **Step 1: Resolve the current SHA for each unpinned action**

```bash
gh api repos/fossi-foundation/nix-eda/commits/main --jq .sha
gh api repos/DeterminateSystems/nix-installer-action/commits/main --jq .sha
gh api repos/AdityaGarg8/remove-unwanted-software/commits/v5 --jq .sha
gh api repos/tvdias/github-tagger/commits/v0.0.1 --jq .sha
gh api repos/softprops/action-gh-release/commits/v2 --jq .sha
```

- [ ] **Step 2: Apply each pin with the tag preserved as a trailing comment**

The comment is what makes the pin maintainable and what Dependabot updates:

```yaml
        uses: fossi-foundation/nix-eda/.github/actions/nix_sign_cache_s3@<sha>  # main
```

Apply to: `ci.yml:161, 193, 253` (fossi-foundation), `setup_nix/action.yml:35` (nix-installer), `maximize_space/action.yml` (remove-unwanted-software, now single-site thanks to Task 3), `ci.yml:762` (github-tagger), `ci.yml:768` (action-gh-release).

Leave `actions/*` and `pypa/gh-action-pypi-publish` on tags — first-party GitHub and PyPA actions are conventionally trusted by tag.

- [ ] **Step 3: Verify no floating refs remain on third-party actions**

```bash
grep -n "uses:.*@main\|uses:.*@master" .github/workflows/ci.yml .github/actions/*/action.yml
```

Expected: no output.

- [ ] **Step 4: Validate and commit**

```bash
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"
git add -A
git commit -m "ci: pin third-party actions to commit SHAs

nix_sign_cache_s3 was on a floating @main ref while receiving
NIX_PRIVATE_KEY and AWS credentials. Tags retained as comments so
Dependabot can bump them."
```

---

### Task 6: Add least-privilege token permissions

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Confirm the current state**

```bash
grep -n "permissions:" .github/workflows/ci.yml
```

Expected: exactly one hit, at `:672`.

- [ ] **Step 2: Add a restrictive workflow-level default**

Insert after the `concurrency:` block (around line 35), before `jobs:`:

```yaml
permissions:
  contents: read
```

- [ ] **Step 3: Grant back only what individual jobs need**

The workflow-level default applies to every job, so any job that writes needs an explicit grant. Audit for jobs that push tags, create releases, comment on PRs, or push containers:

```bash
grep -n "github-tagger\|action-gh-release\|github-script\|docker/login\|GITHUB_TOKEN" .github/workflows/ci.yml
```

At minimum: `publish` keeps its `id-token: write` and additionally needs `contents: write` (tagging and releases); `upload_metrics` needs `pull-requests: write` if it comments via `actions/github-script` at `:635`; the container-publishing job needs `packages: write`.

Add a `permissions:` block to each such job listing only what it needs.

- [ ] **Step 4: Validate and push to exercise it**

A too-restrictive permission fails at runtime, not at parse time, so this task's real verification is a CI run.

```bash
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('OK')"
git add .github/workflows/ci.yml
git commit -m "ci: default GITHUB_TOKEN to contents:read, grant per job

Only the publish job previously declared any permissions block; every
other job ran with the default unrestricted token scope."
git push origin librelane-unstalbe
gh run watch
```

Expected: green. A `Resource not accessible by integration` error means a job needs a grant added — fix and re-push.

---

### Task 7: Add Dependabot

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Create the config**

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "ci"

  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "build"
    groups:
      dev-dependencies:
        patterns: ["ruff", "mypy", "pytest*", "types-*"]
```

The `github-actions` entry is what keeps Task 5's SHA pins current instead of frozen forever. The `uv` ecosystem entry requires Track 1's `uv.lock` to exist.

- [ ] **Step 2: Verify it parses and that uv.lock exists**

```bash
uv run --with pyyaml python -c "import yaml; print(yaml.safe_load(open('.github/dependabot.yml'))['version'])"
test -f uv.lock && echo "uv.lock present"
```

Expected: `2` and `uv.lock present`.

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot for actions and uv dependencies"
```

---

### Task 8: Make the build-py job's scope honest

The step-implementation tests are deselected by default (`pyproject.toml:80`, `addopts = "--strict-markers -m 'not step_impl_test'"`) and only run inside the Nix jobs. `build-py` runs on a bare `actions/setup-python` runner with no OpenROAD, Magic, Netgen, or Yosys binaries, and nothing outside the Nix closure provides them.

**Do not "fix" this by removing the marker exclusion.** That breaks the job for everyone without surfacing any new signal. The problem is that a green `build-py` check reads as "steps are tested" when it is not. Fix the labelling.

**Files:**
- Modify: `.github/workflows/ci.yml` (`build-py` job `name:`), `pyproject.toml:80` (comment)

- [ ] **Step 1: Rename the job to state its actual scope**

In the `build-py` job (`:116`), change the `name:` to make the exclusion visible in the checks list:

```yaml
    name: Unit Tests (no step-impl) / Python ${{ matrix.python-version }}
```

- [ ] **Step 2: Document why the marker exists, at the marker**

In `pyproject.toml`, above the `[tool.pytest.ini_options]` `addopts` line:

```toml
[tool.pytest.ini_options]
pythonpath = "."
# step_impl_test is deselected by default: those tests shell out to
# OpenROAD/Magic/Netgen/Yosys, which only exist inside the Nix closure.
# They run in the build-linux-*/build-darwin jobs. Do not remove this
# exclusion to "increase coverage" -- it breaks every non-Nix runner.
addopts = "--strict-markers -m 'not step_impl_test'"
```

- [ ] **Step 3: Verify the deselection still behaves as documented**

```bash
uv run pytest -q 2>&1 | tail -1
uv run pytest -m step_impl_test --collect-only -q 2>&1 | tail -3
```

Expected: the default run reports `1 deselected`; the explicit marker run collects the step tests (they will not pass locally without the toolchain, which is the point).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml pyproject.toml
git commit -m "ci: name build-py for what it actually covers

A green 'Build and Unit Test' check implied step-implementation
coverage it structurally cannot provide."
```

- [ ] **Step 5: Confirm a Nix job is a required status check**

This is a repository settings change, not a file change:

```bash
gh api repos/KelvinChung2000/librelane/branches/librelane-unstalbe/protection --jq '.required_status_checks.contexts' 2>&1 | head
```

If branch protection is absent or no Nix job is listed, add one via repository settings. Without this, nothing enforces that the only jobs running step tests actually pass.

---

### Task 9: Add the Step.factory registry check

**This task is Track 4's safety net and its blocking precondition.** A missing `__init__.py` re-export during the module splits removes a step from the registry with no import error and no test failure. Nothing currently detects that.

**Files:**
- Create: `.github/scripts/check_step_registry.py`
- Create: `test/steps/test_registry_snapshot.py`
- Modify: `.github/workflows/ci.yml` (add to the `lint` job)

- [ ] **Step 1: Find the real registry enumeration API**

Do not guess the method name. Read it:

```bash
grep -n "class StepFactory" -A 40 librelane/steps/step.py | head -60
grep -rn "StepFactory.get\|StepFactory.list\|__registry" librelane/steps/step.py
```

Record the exact call that enumerates registered step IDs. The steps below write it as `StepFactory.list()`; substitute the real name.

- [ ] **Step 2: Write the failing test first**

Create `test/steps/test_registry_snapshot.py`. It pins the registry against a checked-in snapshot so any accidental removal fails loudly:

```python
import json
from pathlib import Path

import librelane.steps  # noqa: F401  -- ensures every step module is imported
from librelane.steps.step import StepFactory

SNAPSHOT = Path(__file__).parent / "registry_snapshot.json"


def test_step_registry_matches_snapshot():
    """Guards against a step silently vanishing from the factory registry,
    which is the silent failure mode of splitting step modules into packages."""
    current = sorted(StepFactory.list())

    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=2) + "\n")
        raise AssertionError(
            f"Wrote initial snapshot with {len(current)} steps. Re-run to verify."
        )

    expected = json.loads(SNAPSHOT.read_text())

    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))

    assert not missing, (
        f"{len(missing)} step(s) disappeared from the registry: {missing}. "
        "If intentional, update test/steps/registry_snapshot.json."
    )
    assert not added, (
        f"{len(added)} new step(s) registered: {added}. "
        "If intentional, update test/steps/registry_snapshot.json."
    )
```

- [ ] **Step 3: Run it to generate the snapshot, then run again to verify**

```bash
uv run pytest test/steps/test_registry_snapshot.py -v
uv run pytest test/steps/test_registry_snapshot.py -v
```

Expected: the first run FAILS with "Wrote initial snapshot with N steps"; the second PASSES. Record N.

- [ ] **Step 4: Prove the check actually catches a removal**

A guard that has never been seen to fail is not a guard. Temporarily break it:

```bash
python3 -c "
import json, pathlib
p = pathlib.Path('test/steps/registry_snapshot.json')
d = json.loads(p.read_text())
d.append('Fake.NonexistentStep')
p.write_text(json.dumps(d, indent=2) + '\n')
"
uv run pytest test/steps/test_registry_snapshot.py -q
```

Expected: FAIL, reporting `Fake.NonexistentStep` as missing. Then restore:

```bash
git checkout test/steps/registry_snapshot.json
uv run pytest test/steps/test_registry_snapshot.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify the full suite and commit**

```bash
uv run pytest -q
```

Expected: the baseline count plus one.

```bash
git add test/steps/test_registry_snapshot.py test/steps/registry_snapshot.json
git commit -m "test: pin the Step.factory registry against a snapshot

Guards the silent failure mode of the upcoming step module splits: a
missing __init__.py re-export removes a step from the registry with
no import error and no other test failure."
```

---

### Task 10: Add a docs CI job

`make docs` works but nothing invokes it; Sphinx only builds post-merge via ReadTheDocs' own webhook, so a docs-breaking PR merges green.

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the job**

Insert after the `lint` job:

```yaml
  docs:
    name: Docs
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v6
      - name: Set Up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Build Docs
        run: make docs
      - name: Verify Output
        run: test -f docs/build/html/index.html
```

Deliberately no `-W` yet. Turning warnings into errors on a docs tree that has never been gated will fail immediately on pre-existing warnings. Land the job first; ratchet to `-W` in a follow-up once the existing warnings are cleared.

- [ ] **Step 2: Verify locally before pushing**

```bash
rm -rf docs/build && make docs && test -f docs/build/html/index.html && echo DOCS-OK
```

Expected: `DOCS-OK`.

- [ ] **Step 3: Validate, commit, push**

```bash
uv run --with pyyaml python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print('docs' in d['jobs'])"
git add .github/workflows/ci.yml
git commit -m "ci: build the docs on every PR

make docs existed but no job called it, so docs breakage was only
discovered post-merge by ReadTheDocs."
git push origin librelane-unstalbe
gh run watch
```

---

### Task 11: Add governance files

LibreLane executes third-party tool binaries and downloads PDKs over the network. A vulnerability disclosure path is not optional.

**Files:**
- Create: `SECURITY.md`, `CONTRIBUTING.md`, `.github/CODEOWNERS`, `.github/pull_request_template.md`

- [ ] **Step 1: Write `SECURITY.md`**

State supported versions and a private reporting channel. Prefer GitHub private vulnerability reporting over publishing an email address:

```markdown
# Security Policy

## Reporting a Vulnerability

Report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/KelvinChung2000/librelane/security/advisories/new).
Please do not open a public issue for a security report.

LibreLane executes external tool binaries and downloads PDK data over
the network. Issues in either area are in scope.

We aim to acknowledge reports within 7 days.

## Supported Versions

Only the latest released minor version receives security fixes.
```

- [ ] **Step 2: Write `CONTRIBUTING.md` with the actual dev setup**

The single most valuable thing here is one working command, which Track 1 made true:

````markdown
# Contributing

## Development Environment

```console
$ uv sync --all-groups
```

That is the whole setup. Run tooling through uv:

```console
$ uv run pytest          # tests
$ make lint              # ruff + mypy
$ make docs              # build documentation
```

## Before Opening a Pull Request

- `make lint` passes
- `uv run pytest` passes
- New behavior has a test

Step implementation tests (`-m step_impl_test`) need the full EDA
toolchain and run only in the Nix-based CI jobs. You are not expected
to run them locally.
````

- [ ] **Step 3: Write a narrow `.github/CODEOWNERS`**

```
*                       @KelvinChung2000
/librelane/steps/       @KelvinChung2000
/nix/                   @KelvinChung2000
/.github/workflows/     @KelvinChung2000
```

- [ ] **Step 4: Write a short PR template**

```markdown
## What

<!-- What does this change do? -->

## Why

<!-- What problem does it solve? -->

## Verification

<!-- Commands run and their output. -->

- [ ] `make lint` passes
- [ ] `uv run pytest` passes
```

- [ ] **Step 5: Verify the files are where GitHub expects them**

```bash
ls -1 SECURITY.md CONTRIBUTING.md .github/CODEOWNERS .github/pull_request_template.md
```

Expected: all four listed.

- [ ] **Step 6: Commit**

```bash
git add SECURITY.md CONTRIBUTING.md .github/CODEOWNERS .github/pull_request_template.md
git commit -m "docs: add SECURITY, CONTRIBUTING, CODEOWNERS, and PR template"
```

---

### Task 12: Codify the one-definition-per-check discipline

The durable outcome of this track. Without it, inline YAML logic creeps back and local and CI paths drift apart again.

**Files:**
- Modify: `CONTRIBUTING.md`
- Possibly modify: `.github/actions/setup_env/action.yml`

- [ ] **Step 1: Find remaining inline decision logic**

```bash
grep -n "if \[\|&&\|||" .github/workflows/ci.yml | grep -v "^\s*#" | head -20
sed -n '14,35p' .github/actions/setup_env/action.yml
```

- [ ] **Step 2: Extract `setup_env`'s publish decision into a script**

`setup_env/action.yml:14-35` chains four `if:` shell steps to decide publish versus no-publish. Move that decision into `.github/scripts/`, following the dual-mode pattern `.github/scripts/gh.py:98-121` already uses — it switches between writing `$GITHUB_ENV` and setting `os.environ` based on whether `GITHUB_ACTIONS` is set, which is what makes these scripts runnable locally.

- [ ] **Step 3: Verify the script runs locally, outside Actions**

```bash
uv run python .github/scripts/<new_script>.py --help
```

Expected: runs without requiring `$GITHUB_ENV` to exist.

- [ ] **Step 4: Record the rule in CONTRIBUTING.md**

```markdown
## CI Conventions

No `run:` step under `.github/` may contain more than one call into a
script or a nix target. Branching, parsing, and decision logic live in
`.github/scripts/`, never inline in YAML.

This is what keeps CI runnable locally: every script detects whether it
is running under Actions and writes to `$GITHUB_ENV` or plain
`os.environ` accordingly (see `.github/scripts/gh.py`). Logic inlined
into YAML cannot be run locally and will drift from what developers run.
```

- [ ] **Step 5: Validate, commit, push**

```bash
uv run --with pyyaml python -c "
import yaml
yaml.safe_load(open('.github/workflows/ci.yml'))
yaml.safe_load(open('.github/actions/setup_env/action.yml'))
print('OK')
"
git add -A
git commit -m "ci: extract the publish decision into a script

Codifies one definition per check: decision logic lives in
.github/scripts/ where it can run locally, never inline in YAML."
git push origin librelane-unstalbe
gh run watch
```

---

## Track 3 Definition of Done

- [ ] Darwin PDK cache key resolves to a real hash, not a constant
- [ ] `grep -c "fail-fast: false"` → 6
- [ ] `grep -c "remove-unwanted-software" .github/workflows/ci.yml` → 0
- [ ] No third-party action on `@main` or `@master`
- [ ] Workflow-level `permissions: contents: read`, with per-job grants
- [ ] `.github/dependabot.yml` exists and covers both `github-actions` and `uv`
- [ ] The registry snapshot test passes, and **has been observed to fail** when a step is removed
- [ ] Docs build on every PR
- [ ] `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, PR template exist
- [ ] CI green on `librelane-unstalbe`

## Self-Review Notes

- **Task 9 is the gate for Track 4** and says so in the constraints. Step 4 deliberately breaks the guard to prove it fires, because an assertion that has never failed is not evidence of anything.
- **Task 8 explicitly forbids the tempting wrong fix** (removing the marker exclusion) and explains the structural reason.
- **Task 6 cannot be verified locally.** Over-restrictive permissions fail at runtime, so its verification is a real CI run, and the expected failure message is given.
- **Task 10 deliberately omits `-W`.** Enabling it on a never-gated docs tree fails on pre-existing warnings and would make the job useless on day one.
- **Task 3 Step 2 checks whether the six copies are identical** rather than assuming it. If they differ, the composite action needs parameters.
- Task 9's snapshot test writes itself on first run, which is a mild TDD deviation. It is deliberate: hand-authoring a list of every registered step ID into the plan would be inventing data. The two-run bootstrap plus the Step 4 falsification check is the honest equivalent.
