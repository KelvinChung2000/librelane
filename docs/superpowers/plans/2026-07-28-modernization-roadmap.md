# LibreLane Modernization Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each track's plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize the `librelane-unstalbe` fork across five tracks: uv toolchain, ruff-only linting, hardened modular CI, oversized step modules split into packages, and hand-rolled code replaced with permissively licensed libraries.

**Architecture:** Five independent tracks, deliberately sequenced so that toolchain changes (which touch every file's formatting and every CI install step) land *before* structural refactors (which produce large mechanical diffs). Each track is its own plan document and produces working, testable software on its own.

**Tech Stack:** Python >=3.10, uv, ruff, mypy, pytest, Nix flakes, GitHub Actions, Sphinx/MyST.

## Global Constraints

Every task in every track implicitly includes these.

- **License:** LibreLane is Apache-2.0 and is distributed as a *library*. GPL and LGPL dependencies are not acceptable. MIT, BSD, Apache-2.0, ISC are fine.
- **Python floor:** `requires-python = ">=3.10"`. Do not raise it without an explicit decision. Do not add an upper bound to paper over a test bug.
- **Local interpreter is Python 3.14.3.** `uv` will resolve to it unless pinned. Any test relying on CPython implementation details will surface here first.
- **No `from __future__ import annotations` in new code.** Type things directly. (Note: `librelane/steps/step.py` already has it; leave existing usage alone.)
- **Nix consumes the Python build.** `default.nix` reads `pyproject.toml` for the version (`default.nix:74`) and uses `format = "pyproject"` with `poetry-core` in `nativeBuildInputs` (`default.nix:38,80`). Any `[build-system]` change requires a matching `default.nix` change in the same commit.
- **Never let the `Step.factory` registry shrink silently.** A missing re-export removes a step with no import error. Any change under `librelane/steps/` must be gated on a registry-equality check.
- **Fork context:** `origin` is `KelvinChung2000/librelane`, `upstream` is `librelane/librelane`. This branch is not constrained by what upstream would merge. Do not add upstreaming steps.
- **Run tooling through uv:** `uv run <tool>`, not `.venv/bin/<tool>`.
- **Commit frequently.** One commit per completed step where the plan says so; never batch unrelated changes.

---

## Verified Baseline (2026-07-28)

Established by direct execution, not inference. Re-verify if resuming much later.

| Fact | Value | How verified |
|---|---|---|
| Test suite | `1 failed, 146 passed, 1 deselected, 1 xfailed` | `uv run --frozen pytest -q` |
| The one failure | `test/config/test_variable.py::test_some_of` at line 128 | Fails only on Python 3.14; `is` comparison of `types.UnionType` |
| uv | 0.10.11, installed at `/home/kelvin/.local/bin/uv` | `uv --version` |
| System Python | 3.14.3 | `python3 --version` |
| `poetry.lock` | present; `pyproject.toml` has **zero** `[tool.poetry]` fields | `grep -c "tool.poetry" pyproject.toml` → 0 |
| ruff | configured at `pyproject.toml:72-76`, absent from `[dependency-groups] lint`, absent from `make lint`, absent from `ci.yml` | grep |
| `ci.yml` | 783 lines, 11 jobs | `wc -l`, `grep -n "^  [a-z_-]*:"` |
| `.github/actions/check_space` | exists, **never referenced** | `grep -rn check_space .github/` |
| Untracked (NOT repo problems) | `requirements_tmp.txt`, `result`, shell rc files, `.idea/`, `.vscode/` | `git ls-files` |
| Tracked | `.dockerignore`, `notebook.ipynb` | `git ls-files` |

---

## Track Sequencing

The order is load-bearing. Rationale for each constraint:

```
Track 1: uv migration
    │  (gates everything: every later track edits CI install steps or the Makefile.
    │   Doing this first means later tracks are written against the final toolchain.)
    ▼
Track 2: ruff consolidation  ──► includes a repo-wide reformat
    │  (HARD CONSTRAINT: the reformat must precede Track 4. If it runs after,
    │   every one of the ~20 new files from the splits gets touched twice and the
    │   splits stop being reviewable as pure moves.)
    ▼
Track 3: CI hardening (minimal)
    │  (green CI is the only safety net for Track 4's mechanical refactor.
    │   Fix the cache-key bug and the missing fail-fast BEFORE relying on it.)
    ▼
Track 4: step module splits  ──► openroad.py, then step.py, then klayout.py/odb.py
    │  (largest diff, purely mechanical, needs the registry-equality check from Track 3)
    ▼
Track 5: library replacements  ──► stdlib swaps, lark, click, then pydantic separately
    │  (behavioral risk rather than mechanical risk; wants a stable post-Track-4 CI history)
    ▼
Track 6: Loguru migration  ──► native Loguru calls and preserved flow artifacts
    │  (characterize output, levels, metadata, pytest capture, and per-flow sinks first)
    ▼
Track 7: pathlib + package resources  ──► resource API first, then typed path domains
       (broadest API migration; land incrementally with wheel and Nix installation tests)
```

**Tracks 1-3 are ready to execute.** Their plans are written and verified.

**Tracks 4 and 5 are deliberately not yet written in bite-sized form.** Writing exact per-class move steps for a 2,989-line file now would mean inventing line numbers that Track 2's reformat is about to change. Their plans get written just-in-time, after Track 2 lands, when the class inventory can be re-derived against the actual post-reformat tree. The task-level shape of both is recorded below so nothing is lost.

---

## Track Index

| Track | Plan | Status | Est. |
|---|---|---|---|
| 1 | [uv migration](2026-07-28-track-1-uv-migration.md) | Complete | 1-2 days |
| 2 | [ruff consolidation](2026-07-28-track-2-ruff-consolidation.md) | Complete | 1-2 days |
| 3 | [CI hardening](2026-07-28-track-3-ci-hardening.md) | Complete; CI failure debug parked | 1 day |
| 4 | step module splits | Complete | 3-4 weeks |
| 5 | [library replacements](2026-07-28-track-5-library-replacements.md) | Core replacements complete; Pydantic gate deferred | 1 week + pydantic separately |
| 6 | [Loguru migration](2026-07-28-track-6-loguru-migration.md) | Complete | 2-3 days |
| 7 | [pathlib and package resources](2026-07-28-track-7-pathlib-resources.md) | In progress | 2-3 weeks |

---

## Track 4 Shape (plan to be written after Track 2)

Three PRs, in this order. `openroad.py` first to prove the pattern on a file nothing else imports; `step.py` second because every other step module depends on it; `klayout.py`/`odb.py` last, in parallel with each other.

**Preconditions before starting:**
- A `Step.factory` registry-equality script exists and runs in CI (Track 3, Task 9).
- Track 2's reformat has landed, so the splits are pure moves.

**Per-file target layouts** (from the migration-plan workflow, re-verify class inventory at write time):

- `librelane/steps/openroad/` → `__init__.py`, `base.py`, `sta.py`, `floorplan.py`, `placement.py`, `routing.py`, `resizer.py`, `resizer_timing.py`, `finishing.py`
- `librelane/steps/step/` → `__init__.py`, `exceptions.py`, `output_processor.py`, `process_stats.py`, `factory.py`, `composite.py`, `reporting.py`, `subprocess_exec.py`, `core.py`
- `librelane/steps/klayout/` → `__init__.py`, `base.py`, `views.py`, `drc.py`, `checks.py`, `lvs.py`, `physical.py`
- `librelane/steps/odb/` → `__init__.py`, `base.py`, `reports.py`, `placement.py`, `obstructions.py`, `power.py`, `diodes.py`, `eco.py`

**Known landmines, confirmed by direct read:**
- `tclstep.py:273` overrides `run_subprocess` and calls `super().run_subprocess(...)`. `run_subprocess`, `get_log_path`, and `extract_env` must remain overridable `Step` methods with thin delegators, never bare free functions.
- `checker.py:21` imports `State` from `.step`, but `step.py` never defines it — it is an accidental transitive re-export from `..state`. Fix `checker.py` to import from `..state` directly in the same PR.
- `StepFactory.__registry` name-mangles on class name, not nesting depth, so promoting it to module level is safe.
- `WriteViews` in `openroad.py` is dead code: defined, never registered, never referenced. Delete separately.
- Every moved file needs one extra leading dot on relative imports (`..common` → `...common`). Fails loudly at import time.
- Missing an `__init__.py` re-export fails **silently**. This is the reason for the registry check.
- Reassign `__module__` back to the flat package name on all re-exports so `Step.get_help_md()`'s "Importing" sample does not leak internal submodule paths. Do this consistently across all four packages.
- Accept `sta.py` (~580 lines) and `core.py` (~570 lines) over the 200-500 target rather than fragmenting strict inheritance chains.

---

## Track 5 Shape (plan to be written after Track 4)

Ten candidates were audited; five approved after license and fit verification.

**Approved, low risk — do together in one PR:**

| What | Location | Replace with | License |
|---|---|---|---|
| `RingBuffer` fixed-size circular buffer | `librelane/common/` | `collections.deque(maxlen=n)` | stdlib |
| `zip_first` iterator class | `librelane/common/` | `zip(a, itertools.chain(b, itertools.repeat(fill)))` | stdlib |
| argparse + shlex CLI parsing | `librelane/scripts/klayout/open_design.py:16-19,53-70` | `click` (already a dependency, used by 3 sibling scripts) | BSD-3-Clause |

**Approved, own PR:**

| What | Location | Replace with | License | Saves |
|---|---|---|---|---|
| `expr::` arithmetic tokenizer + shunting-yard parser | `librelane/config/preprocessor.py:46-208` | `lark` | MIT | ~100-120 of 163 lines |

**Approved but gated — treat as its own multi-week project, not a refactor:**

`Variable.__process` (`librelane/config/variable.py:526-801`) → `pydantic.TypeAdapter` with `strict=not permissive_typing`. Saves ~120-150 of 276 lines.

Gate: a golden-output comparison of old vs new across **every** declared `Variable` in the repo (~500+), not sampled test cases. Rated medium confidence by the verifier. These stay hand-written regardless: Tcl-style string-to-list/dict coercion, `Path` glob-unwrap, enum lookup **by name** (pydantic defaults to by-value — a real divergence), the three-way None/required/PDK-default state machine, and callable `deprecated_names` aliasing. `Config.__process_variable_list` (`config.py:966-1070`) is out of scope entirely.

**Rejected — do not re-propose:**
- **attrs + cattrs** as a pydantic alternative for the same swap. No built-in strict/lax duality, no Tcl-string/glob/enum-by-name behavior; needs nearly the same volume of custom hooks as today.
- The **custom Decimal-precision YAML loader**, the **IO-placement pin-language parser**, and the **LEF ORIGIN/RECT regex rewriter**. All three are thin, correct, deliberate code. The IO-placement parser already has a documented history of trying and rejecting ANTLR4 for this exact grammar on performance and dependency-count grounds; that decision does not need reopening.

The earlier rejection of a logging replacement is superseded by explicit
maintainer direction. Track 6 uses Loguru natively throughout application code
while preserving observable logging behavior.

---

## Tracks 6 and 7 Shape

Track 6 replaces the 324-line standard-library/Rich backend and its application
facade with native Loguru calls. `librelane.logging` remains only for
initialization, settings, sinks, filters, and the shared Rich console. The
migration preserves `DEBUG`, `SUBPROCESS`, `VERBOSE`, `INFO`, `SUCCESS`,
`WARNING`, `ERROR`, and `CRITICAL` thresholds; condensed subprocess
suppression; Rich rules; `step` and `key` context; pytest `caplog`; warning
aggregation; and `flow.log`, `warning.log`, and `error.log`.

Track 7 begins with resource sourcing because it has a crisp boundary:
`importlib.resources.files("librelane")` for packaged data and
`as_file()`/a managed extraction lifetime when an external tool requires a real
filesystem path. Only after that boundary is tested in source, wheel, and Nix
installs does it migrate path-owning APIs from `str`/`os.path` to
`pathlib.Path`. The existing `librelane.common.Path(UserString)` is a
configuration value type with serialization and coercion semantics; replacing
it is a dedicated late phase, not a blind alias change.

---

## Deferred Indefinitely (do not build)

Recorded so they are not re-proposed as "obvious" modernization.

- **GitHub reusable workflows (`workflow_call`) split of `ci.yml`.** The repo's existing cross-repo reuse is *composite action* reuse (step-level, same runner, cheap). Reusable workflows are job-level, with per-call runner spin-up and explicit secret plumbing. There is no second consumer today. Revisit when one exists.
- **`nix flake check` as the local-CI mechanism.** Unresolved contradiction: PDK data comes from `ciel` at runtime, not a hermetic derivation. Wrapping the unit and smoke tests in `checks` would require `--impure` or network-enabled derivations, defeating the point. Revisit only with a real design for a fixed-output PDK derivation.
- **`act`.** Two jobs run on `macos-15`, which `act` cannot emulate, and the workflow needs live AWS/S3 credentials that should not be handed to a local run.
- **Forcing `step_impl_test` to run in `build-py`.** That job runs on a bare `actions/setup-python` runner with none of the OpenROAD/Magic/Netgen/Yosys binaries, and nothing outside the Nix closure provides them. Forcing it breaks the job rather than surfacing signal. The real fix is in Track 3, Task 8: rename the job so a green check does not imply step coverage.

**The local-CI mechanism we are adopting instead** (Track 3): a discipline, not a tool. No `run:` step anywhere under `.github/` may contain more than one call into a script or a nix target. Branching, parsing, and decision logic never live inline in YAML. The repo already does this with `determine_test_set.py`, `generate_tag.py`, and `get_pdk_hash.py`, and `.github/scripts/gh.py:98-121` already switches between writing `$GITHUB_ENV` and setting `os.environ` based on whether `GITHUB_ACTIONS` is set. That is the existing, working local/CI dual-mode pattern; extend it rather than adopt a new tool.
