# Issue sweep — status

Working record of the pass over every open issue at
<https://github.com/librelane/librelane/issues>, oldest to newest, started
2026-07-28 on branch `issue-sweep` off `librelane-unstable` @ `fd76520` and
merged back into `librelane-unstable`.

All 152 open issues were triaged. Sections A–B are done, C–D are the queue.
One commit per issue.

Before implementing anything from C or D, run `git log HEAD..upstream/dev
--oneline` first — this branch is missing roughly 31 commits merged upstream,
and several open issues are already solved there. Most do not cherry-pick
cleanly, because upstream still has the monolithic `librelane/steps/openroad.py`
and `librelane/config/variable.py` that this fork split into packages, and still
uses `config_vars = [Variable(...)]` lists where this fork uses nested typed
`Config` models. Port by hand and credit the original author with
`git commit --author`.

## A. Fixed — 19 issues, one commit each

| Issue | Commit | What |
|---|---|---|
| 326 | `23fe323` | LVS mismatch guide completed and added to the toctree |
| 370 | `17a301d` | `MAX_FANOUT_CONSTRAINT` optional; the liberty file owns `max_fanout` **(breaking)** |
| 468 | `47f06dc` | `Odb.SetPowerConnections` documented in `pdn.md`, `using_macros.md`, `using_vhdl.md` |
| 492 | `7a10f32` | `LINTER_ARGUMENTS` escape hatch for Verilator |
| 521 | `9dc4c36`, `311cff2` | `OPENROAD_THREADS` (ported from upstream #937), supersedes `DRT_THREADS` **(breaking)** |
| 550 | `43664c9` | DRT-0349 `LEF58_ENCLOSURE` alert suppressed |
| 567 | `8ea9ef0` | 7 emitted-but-unregistered metrics registered, plus a scan test |
| 579 | `2dba783` | Linter blackboxes generated from macro `lib` views |
| 605 | `830d943` | Warn when a macro's LIB or SPEF is not per-corner |
| 611 | `0ec2b9e` | New `OpenROAD.SaveImage` step; reads the ODB so it can sit anywhere in the flow, and forces the offscreen Qt platform |
| 621 | `ab57d84` | Reproducibles created from composite steps actually run |
| 630 | `7f84df7` | `report_dont_touch`, `report_dont_use`, `filler_placement -verbose` |
| 692 | `f80dc33` | `KLAYOUT_XOR_WRITE_GDS` writes the XOR differences to `xor.gds` alongside the marker database |
| 797 | `019e6b3` | Antenna summary pairs each `(VIOLATED)` with the ratio line above it, so CAR/CSR violations report their own cumulative ratio and name the broken rule |
| 802 | `c563a13` | `LINTER_INCLUDE_PDK_MODELS` made functional |
| 812 | `4c03f13` | `runtimes.csv` written per run from `Flow.step_objects`; skipped steps get empty runtime columns rather than being omitted |
| 889 | `9ae8f28` | `flow_run` contextvar scopes every sink a flow registers, so concurrent flows stop cross-contaminating `error.log` / `warning.log` / `flow.log` and the end-of-run issue summary |
| 910 | `1abe0ed` | `Toolbox.check_lib_pins` warns when a macro's `.lib` declares cells with no pins, called from `OpenROAD.CheckMacroInstances` |
| 920 | `07eb1e8` | `OpenROAD.DiodeInsertion` registered so its reproducibles load |
| 924 | `efc7024` | `COLUMNS` propagated to every subprocess, so Rich tables in the odbpy scripts use the real terminal width instead of the 80-column pipe fallback |
| 928 | `d9eff48` | `gds maskhints true` (cherry-picked upstream `9636a6b`, authorship kept) |
| 940 | `09b2313` | Macro libs and `EXTRA_LIBS` reach the synthesis lib set (from PR 943, with its cache bug fixed) |
| 947 | `286a8aa` | Warn when the PDN halo exceeds the row-cutting halo |
| 948 | `6d717bc` | `MAGIC_WRITE_LEF_PINONLY` defaults to `True` **(breaking)** |
| 974 | `869cf4c` | `t_ck` removed from the arrival-time equations |
| 997 | `5d865bb` | `PDN_CFG` marked `pdk=True` |
| 999 | `f0b3f4b` | `KLAYOUT_DEF_LAYER_MAP` optional; `--lym` omitted entirely rather than passed empty, so a `.lyt`-embedded mapping survives |
| — | `865bbe3` | Sphinx build fix; a one-line module docstring crashed the build and blocked verifying any docs change |

Three breaking changes are in here (370, 521, 948). The user confirmed keeping
all of them.

Verified at `5d865bb`: 386 passed / 1 xfailed, `ruff check` clean,
`ruff format --check` clean over 275 files, `mypy` clean over 115 files,
`nix develop --command librelane --smoke-test` passes, `make docs` succeeds
with 250 pre-existing warnings.

## B. Already done — close with the evidence, no code needed

318, 410, 450, 508, 527, 580, 610, 618, 627, 633, 654, 657, 668, 671, 683, 694,
695, 698, 712, 718, 732, 744, 745, 752, 779, 793, 796, 827, 853, 956

Notable: **744** ("DRT running out of iterations doesn't fail the flow") was
empirically disproved. Running spm with `DRT_OPT_ITERS=1` leaves 9 violations,
OpenROAD writes `route__drc_errors: 9`, `Checker.TrDRC` raises a deferred error
and the flow exits 2. The reporter was on OpenLane 2.2.9.

## C. Migrate from upstream

| Issue | Source | Note |
|---|---|---|
| 680 | commit `bf07672` | `LINTER_VLTS` list replaces the scalar `LINTER_VLT` |
| 790 | open PR 835 | fmax metric |
| 854 | commit `4fc4628` | nix-eda 7 / nixos-26.05 bump (qrencode source moved) |
| 893 | commit `cedcd43` | macro array instantiator |
| 901 | open PR 902 | f-list (`*.f`) parser |
| 975 (partial) | commits `b272909`, `dbf73b8`, PR 986 | ABC strategy script, ABC delay target, arith_tree |

Unmerged upstream and issue-adjacent: `acd2341` (GPL GIF), `5b60312` (partial PG
connect), `39a8ada` (`SYNTH_BUFFER_CELL`), `e607def` + `415c7e2` (padring),
`aedda63` + `5fe3db1` (`KLayout.Render`).

## D. Ready to implement — concrete plans, not yet done

| Issue | Size | Summary |
|---|---|---|
| 696 | — | **Blocked on the PDK-meta-config product decision (see E/697).** Not ready to implement. The metric "collision" was mis-triaged; there is none. See below |
| 824 | M | `YosysSynthChecks` counts from `pre_synth_chk.rpt` but users grep `chk.rpt`; report the offending lines and the source path |
| 917 | M | New `OpenROAD.AddBuffer` step (moves the Classic goldens) |
| 993 | M | **Do not fix by "respecting declaration order" — that premise is false.** See below. Changelog corrected in `9c7683c` |
| 599 / 600 / 669 | L | Replace `common.Path` with `pathlib.Path` (see below) |
| 532, 558/560, 583, 636, 967 | M | OpenConsole, RMP resynthesis, isosub, multi-corner STAMidPNR, ReplaceECOCells |

`599` asks for "pathlib.Path **or a subclass of it**". The direct route needs no
subclassing. An earlier revision of this file called the work blocked on 3.12;
that was wrong — *nothing* is blocked. But one **hard design constraint** falls
out of the version floor and governs the whole shape of the migration:

> **`pathlib.Path` cannot be subclassed before Python 3.12, and
> `requires-python = ">=3.10"`.** Subclassing it needs `_flavour`, which is
> private and absent on 3.10/3.11.

So anything that wants to *be* a path has to **compose** one and implement
`os.PathLike`, not inherit. That is why `ScopedFile` was recomposed in
`9fb0886` — a prerequisite, not tidying — and it is why the pydantic behaviour
has to live in an `Annotated` alias rather than in a subclass's
`__get_pydantic_core_schema__`. Anyone reaching for the obvious
`class Path(pathlib.Path)` will get a `TypeError` on the supported floor and
should stop rather than raise the floor to 3.12 to make it work.

`600` (portable states, keeping `dir::` / `pdk_dir::` unresolved and resolving on
access) is the feature `599` was meant to unlock. Also not done.

**Status: the preparation is done; one mechanical step remains.**

Read the audit below with that in mind. It describes the problem as it stood
before any of it was fixed, and a reader who takes it at face value will
over-estimate what is left — which is how this issue has survived three
releases. What is actually outstanding is the **last** item on the list:

> Retype the ~41 `common.Path` annotations to `pathlib.Path` (or an
> `Annotated` alias), fix whatever the swap breaks, and delete the
> `UserString` class.

Everything that made that dangerous has already been dealt with, in
`14874a6`, `4cf5d52`, `3c27a9a`, `e359348`, `7779364`, `c9e6243` and `9fb0886`:

- the scalar-vs-iterable dispatch no longer depends on string-likeness
- the ejected-environment string operations no longer depend on it
- `rel_if_child` no longer depends on it, and its latent bug is fixed
- **the JSON schema acceptance criterion is met** — 40 failures to 0
- the `_dummy_path` sentinel and the `_env.tcl` skip compare as strings
- the twelve `is_string` gates in `config/` ask about path-likeness
- `ScopedFile` composes, so `Path` has **no subclasses left**

The remaining swap is ~129 mechanical edits plus two genuine semantic decisions
(`steps/step/reporting.py:299` and `:341`) and the `frozenset`/`lru_cache`
identity sharing. It is measured and designed under "what the swap actually
costs" below. The test residue turned out to be **empty**.

It is not started. The window opened when the OpenROAD slice landed, but a
129-edit refactor across 33 modules is more than could be completed and
verified in the budget remaining, and a half-applied type migration is worse
than none: the failure mode of stopping midway is a tree that imports but is
silently wrong at the sites not yet reached. The measurements and the design
below are the handover, so the next agent executes rather than re-derives.

#### Audit (2026-07-31), evidence-based

**Correct the premise first.** This file has said, and I repeated, that
`common.Path` "is a string". It is not. `UserString` is **not** a subclass of
`str`, so `isinstance(common.Path("/tmp"), str)` is already `False` today.
Measured:

| expression | `common.Path` | `pathlib.Path` |
|---|---|---|
| `isinstance(x, str)` | **False** | False |
| `is_string(x)` (UserString-aware) | **True** | **False** |
| `x == "/tmp"` | **True** | **False** |
| `x in {"/tmp"}` | **True** | **False** |
| `hash(x) == hash("/tmp")` | True | True (equality still fails) |
| iterable | **True** | False |
| `x + "/y"` | `Path('/tmp/y')` | **TypeError** |

So the break surface is *not* "everything that treats it as a str". It is
precisely: `is_string()` gates, `==`/`in` against plain strings, iterability,
and `+`. Bare `isinstance(x, str)` sites are **already** False for
`common.Path` and are therefore not at risk — that rules out ~20 sites a naive
sweep would flag.

Scale, measured: **373** `Path`-mentioning lines in `librelane/` and **142** in
`test/`; **33** modules in `librelane/` and **11** in `test/` import
`common.Path` — more than the 22 previously recorded, because the `openroad/`
package and `cli/run.py` use multi-line or qualified (`common.Path(...)`)
imports that a single-line grep misses. Note four CLI modules
(`cli/config.py`, `cli/options.py`, `cli/state.py`, `cli/metrics.py`) do
`from pathlib import Path`, so a bare `Path` there is already the stdlib one.

**Risk surface by category** (full list in the categories below; ranked worst
first):

1. `common/toolbox.py:93` — `filter_views` uses `if is_string(value):` to tell
   one view from an iterable of views in `Mapping[str, Path | Iterable[Path]]`.
   After the change a scalar path takes the `else` branch, `list(value)`, and
   `pathlib.Path` is not iterable → **TypeError on the hot path** of every
   timing-aware step. Reached from `steps/openroad/sta.py:168`,
   `flows/flow.py:1062`, `steps/tclstep.py:135`, and `toolbox.py:354/376/395`.
2. `cli/steps.py:306-307` — `.startswith` / `.replace` called on env values that
   are `Path` objects (put there unstringified by `steps/tclstep.py:140`,
   `steps/magic.py:439`, `steps/klayout/physical.py:83/126/268`) →
   **AttributeError** in `--create-reproducible` replay.
3. `common/types.py:96` — `not self == Path._dummy_path` compares against a
   `str` sentinel; becomes permanently False, so `__librelane_dummy_path` stops
   being exempt from existence validation. Same shape at `steps/tclstep.py:249`
   (`env_out[key] == value`), which would re-write every path-valued env var
   into `_env.tcl` instead of skipping it as unchanged.
4. `is_string()` gates that currently permit a coercion and would start raising:
   `config/legacy.py:611`, `:657`, `:663`, `:806`; `config/config.py:395`,
   `:563`, `:598`; `config/preprocessor/legacy.py:196`, `:255`, `:263`, `:315`,
   `:323`.
5. `steps/step/reporting.py:299` returns `Path(f"pdk_dir::{...}")` — a path
   object deliberately holding a *directive*, re-parsed at
   `config/preprocessor/resolve.py:79`; and `:341` returns `Path(f"./{rel}")`,
   where `pathlib` normalises `./x` to `x`. Both are asserted verbatim by
   `test/steps/test_step.py:76/87/88`.
6. Hash-identity: `frozenset`s of paths feed `lru_cache`d toolbox methods
   (`steps/yosys.py:88/94`, `steps/pyosys.py:297/306`,
   `steps/verilator.py:128/136`). Today those share a cache entry with the
   pre-stringified spellings used at `steps/yosys.py:111`,
   `steps/pyosys.py:352`, `steps/openroad/base.py:486`. They stop sharing.

**Categories that turned out to be near-empty, contrary to the old note:**

- *String concatenation*: **no** `Path + str` anywhere in the tree. Everything
  goes through `os.path.join`, `pathlib` `/`, or an explicit `str()`.
- *JSON serialization*: **safe as-is**. `common/generic_dict.py:43` already
  dispatches `isinstance(o, os.PathLike)` *before* the `UserString` arm, and
  `pathlib.Path` is `os.PathLike`. Every consumer inherits that. The
  `UserString` arm just becomes dead.
- *Tcl export*: `common/tcl.py:91` excludes `(str, UserString)` from the
  iterable branch purely because `common.Path` is iterable; `pathlib.Path` is
  not, so it falls through to `str(value)` and is correct — the guard merely
  becomes vestigial. `steps/step/subprocess_exec.py:168` already accepts
  `os.PathLike`.

So the genuinely dangerous surface is **`is_string`, `==`/`in`, and
iterability**, not serialization.

**Pydantic (the acceptance check).** Measured on this branch, not inspected:

- **347** distinct config variable names reachable from `Step.factory`
  (370 including flow classes; 1276 with per-step duplicates). I could not
  reproduce the figure of 389 — recording what I measured rather than
  asserting the other number.
- **40** of them fail `model_json_schema()` with `PydanticInvalidForJsonSchema`,
  and **every one mentions `common.Path`**. 41 variables mention it; the one
  that "passes" is `EXTRA_SPEFS: list[str | Path] | None`, and it passes only
  because the `str` arm of the union gives pydantic a renderable branch — its
  schema is silently incomplete rather than correct.
- **Root cause identified exactly**: `common/types.py:69` returns
  `core_schema.no_info_plain_validator_function(...)`, which is opaque —
  pydantic cannot know the output type, so it refuses
  (`Cannot generate a JsonSchema for core_schema.PlainValidatorFunctionSchema`).
- **`pathlib.Path` alone closes it.** A bare `pathlib.Path` field yields
  `{'type': 'string', 'format': 'path'}`.
- **And the `Annotated` alias keeps it closed** — crucially, no explicit
  `__get_pydantic_json_schema__` is needed. `Annotated[pathlib.Path,
  BeforeValidator(collapse_and_validate)]` still yields
  `{'type': 'string', 'format': 'path'}`, including nested inside `list[...]`,
  because a `BeforeValidator` leaves the core output type visible. That is the
  whole trick: swap the *plain* validator for a *before* validator over a real
  type, and both `validate()` (existence) and the `GlobMatch` one-element
  collapse survive with the schema intact.

**`ScopedFile`.** Confirmed the only subclass — `Path.__subclasses__()` returns
exactly `[ScopedFile]` at runtime. Note its real signature is keyword-only
(`ScopedFile(*, contents="")`, `common/types.py:150`), not positional.
Composition verified working: a plain class holding a `pathlib.Path` and
implementing `__fspath__` is accepted by `open()`, by `pathlib.Path()`, and by
`isinstance(x, os.PathLike)`, and the `weakref.finalize` cleanup still fires on
garbage collection.

**`rel_if_child` — the audit found a live bug.** It has **zero call sites and
zero tests** in the whole tree (only its own definition at
`common/types.py:109`), so this is latent, but the migration *fixes* rather than
preserves it. It tests parentage with `str.startswith` on the abspath, which is
a textual prefix test, not a path-component one. Measured against base
`/tmp/claude-1000`:

| target | current | `pathlib.is_relative_to` |
|---|---|---|
| `/tmp/claude-1000/a/b.txt` | `./a/b.txt` | True → `a/b.txt` |
| `/tmp/claude-1000` | `./.` | True → `.` |
| `/tmp/other/c.txt` | absolute (correct) | False |
| `/tmp/claude-1000-sibling/d.txt` | **`./../claude-1000-sibling/d.txt`** | **False** |

A sibling directory that merely shares a name prefix is wrongly classified as a
child and returned as a `../` escape. `pathlib.is_relative_to` gets it right.
So the answer to "do the semantics match at the boundaries" is **no, and
pathlib's are the correct ones** — the free function should use
`is_relative_to` and this deserves a regression test rather than a
bug-for-bug port.

**Order of work when it is handed over**, cheapest risk-reduction first:

1. ~~Fix `filter_views` to dispatch on `isinstance(value, (str, os.PathLike))`~~
   — **done, `14874a6`.** Correct under both representations, so it landed
   ahead of the type change. Pinned for `str`, `common.Path` and
   `pathlib.Path`; the pathlib case raises `TypeError` against the old
   dispatch.
2. ~~Stringify at the env boundary so `cli/steps.py:306` is safe~~ — **done,
   `4cf5d52`.** Normalises with `os.fspath()` inside a new
   `filter_env_for_script()` helper, which also makes the "already in the
   ambient environment" skip the str-to-str comparison it always meant to be.
   *Trap for the next editor:* that helper must stay **above** the
   `@cli.command()` decorator belonging to `eject`, or typer adopts it as a
   subcommand and dies on its `Mapping` parameters.
3. ~~`rel_if_child`~~ — **done, `3c27a9a`.** Ported to `is_relative_to`; the
   sibling-prefix case is a regression test, and the old `./../` output is
   deliberately not preserved.
4. ~~The pydantic schema acceptance gate~~ — **done, `e359348`. 40 → 0.**
   Note the deviation: the `Annotated[pathlib.Path, BeforeValidator(...)]`
   alias would have required retyping the 40 declarations, which live in
   `librelane/steps/{klayout,magic,netgen}` — the held sweep. The same
   criterion was met inside `common/types.py` alone by rebuilding
   `__get_pydantic_core_schema__` *around* a `str_schema` instead of replacing
   it with an opaque plain validator: collapse the glob and coerce to `str` on
   the way in, construct and existence-check on the way out. The core type
   stays visible so pydantic derives the schema itself — still **no**
   `__get_pydantic_json_schema__`, which is what the audit predicted. Verified
   0 failures at all three levels: 370 variables, 173 `Step.Config`, 6
   `Flow.Config`. Pinned by two tests that *name* offenders rather than
   counting them. The `Annotated` alias remains the shape to adopt when the
   runtime type actually flips.
5. ~~`_dummy_path` and the `steps/tclstep.py:249` twin~~ — **done, `7779364`.**
6. ~~The `is_string` gates in `config/`~~ — **done, `c9e6243`.** New
   `is_string_like()` (str, `UserString` or `os.PathLike`) asks what those
   twelve sites actually mean; `str()` is now explicit where a real `str` is
   needed. `is_string()` is unchanged and still correct where the question
   really is "is this a string", notably `generic_dict.copy_recursive`.
7. ~~`ScopedFile`~~ — **done, `9fb0886`.** Composes `.path` and implements
   `os.PathLike`. `Path.__subclasses__()` is now empty, pinned by a test.
   Breaking for anyone who relied on a `ScopedFile` being a `str`; zero call
   sites in the tree.
8. **Outstanding:** the annotation swap and deleting the `UserString` class.
   Measured and designed below, not started — see "what the swap actually
   costs".

#### What the swap actually costs, measured

Counted on this branch rather than estimated:

| | count |
|---|---|
| `Path` in annotation position (`: Path`, `Optional[Path]`, `list[Path]`, …) | ~110 across 24 files |
| `Path(` runtime constructor calls | 103 |
| `isinstance(…, Path)` | ~26 across 10 files |
| modules importing `common.Path` | 33 |

**The design that minimises the diff.** `Path` cannot stay one name doing both
jobs, because the pydantic behaviour has to live in an `Annotated` alias (see
the 3.10 subclassing constraint above) and an `Annotated` alias is neither
callable nor usable with `isinstance`. Two spellings are unavoidable. Which
name keeps which job decides the size of the diff:

- Keep `Path` as the **Annotated alias** → all ~110 annotation sites are
  untouched; the 103 constructor calls become `pathlib.Path(...)` and the 26
  `isinstance` sites become `isinstance(..., pathlib.Path)`. **~129 mechanical
  edits, each greppable** (`\bPath\(` and `isinstance\(..., Path\)`).
- Keep `Path` as `pathlib.Path` → constructors and `isinstance` are untouched,
  but all ~110 annotations must change. Worse, and easy to miss one silently:
  a missed annotation still *works*, it just quietly loses the existence check
  and the `GlobMatch` collapse.

Prefer the first: its failure mode is a loud `TypeError`, the second's is
silent.

Three things must move off the class before it goes:

- `Path._dummy_path` → a module constant. Used at `common/toolbox.py:301` and
  throughout `test/config/test_variable.py`.
- `Path.validate()` → a free function. Called at `common/types.py:138` and
  **`config/legacy.py:791`**, which the category sweep missed.
- `rel_if_child` → free function. Already correct as of `3c27a9a`, still zero
  call sites.

**Corrections to the audit's categories 5 and 6.** Both were over-stated, and
both were checked at runtime rather than read:

- **"Tests that assert `Path == str` fail immediately" is wrong — that residue
  is empty.** `State` does **not** coerce: given a plain `str` it stores and
  returns a `builtins.str`, so every `assert state[DesignFormat.NETLIST] ==
  "abc"` in `test/state/test_state.py` is `str == str` and is unaffected. The
  reproducible assertions at `test/steps/test_step.py:76/87/88` read
  `json.loads(...)`, so they are also `str == str`. The single test comparing
  against a `Path(...)`, `test/steps/test_script_paths.py:41`, imports
  `from pathlib import Path` — it is already stdlib-to-stdlib. **No test in the
  tree compares a `common.Path` to a `str`.**
- What those `test_step.py` assertions *do* pin is real and must survive: the
  emitted `config.json` has to contain `./files/relative.v` and
  `pdk_dir::tech.lef` verbatim. That is intent about what
  `steps/step/reporting.py:341` and `:299` emit — the `./` prefix that
  `pathlib` would normalise away, and the `pdk_dir::` directive that is not a
  path at all. Those two lines are the genuine semantic decisions in the swap
  and should be settled first; everything else is mechanical.
- `to_raw_dict()` does **not** stringify — it returns the path object as-is, so
  JSON output depends entirely on `common/generic_dict.py:43` dispatching
  `os.PathLike` before `UserString`. It already does, so this survives.

Steps 1–7 are landed. The remaining refactor is much smaller than the audit
describes — every ranked risk site is already neutral to which path
representation is in use, and the acceptance gate that blocked the JSON Schema
work is met *today*, before the type change.

### 696 — there is no collision today, and the feature is deliberately postponed

Two findings.

**1. The metric key is not a collision; it is the single-provider contract.**
`lvs` is a **single-provider** stage (`stages/taxonomy.py:288-299`) with a
stage-level contract `metrics=("design__lvs_error__count",)`. `drc` and
`streamout` are `multi_provider=True`; `lvs` is not. So exactly one LVS provider
runs, and its providers are *alternatives*. `Pegasus.LVS` reuses the same key on
purpose, with the reason written at `steps/pegasus.py:158-161`: it "reuses that
stage-level metric rather than inventing a Pegasus-specific name". `KLayout.LVS`
doing the same is consistent, not a bug. Nothing can overwrite anything today:
`KLayout.LVS` is registered in the step factory but appears in **no flow and no
provider** (only hit is `test/steps/registry_snapshot.json:87`), so it and
`Netgen.LVS` cannot both run.

The tool-prefixed naming the triage expected (`klayout__lvs_error__count`,
mirroring `klayout__drc_error__count`) is correct only under the *run-alongside*
model — which is what the issue asks for and what would make `lvs`
multi_provider. Which naming is right is therefore downstream of a design
decision that is not made yet. Pinned by
`test_providers_that_run_together_do_not_declare_the_same_metric` in
`test/stages/test_providers.py`, which exempts single-provider stages and will
fail loudly the moment `lvs` becomes multi_provider without the rename.

**2. The participants explicitly asked not to rush it.** donn wants a PDK meta
configuration variable to drive flow composition (which would also retire
`PRIMARY_GDSII_STREAMOUT_TOOL`) plus derivative flows via #648; mole99's reply is
"That's a lot to think about and it feels important to get this right. So let's
better not rush this one :)". That is the same "PDK dictates flow defaults"
redesign that already put **697** in section E.

Implementing the `RUN_KLAYOUT_LVS` boolean as specced would also fight the
architecture: adding `KLayout.LVS` to `Classic` as a plain step, emitting a
stage-contracted metric outside any registration, is the exact anti-pattern
`test_a_tool_specific_metric_is_checked_inside_its_own_registration` and
`test_each_drc_provider_owns_its_own_checker` were written to condemn.

**Status: blocked, not ready.** Making `lvs` multi_provider *is* the
PDK-meta-config redesign already sitting in section E as a product decision
(**697**), and donn and mole99 postponed it deliberately. This needs the
maintainer to pick the model; it should be surfaced, not guessed at. Do not
move it back to "ready to implement" without that decision.

A note on the analogy that produced the original triage line: "a metric written
by two steps is the same class of problem as a view written by two steps" is
only true when both steps can actually run. That holds for the `gds` fan-in,
where `Magic.StreamOut` and `KLayout.StreamOut` genuinely both run on a
`multi_provider` stage. It does not hold on a single-provider stage, where the
providers are alternatives. The structural check — `multi_provider` true or
false — is what distinguishes the two cases, and it is now enforced by
`test_providers_that_run_together_do_not_declare_the_same_metric` rather than
left to judgement.

### 611 — save_image aborts the process headlessly unless Qt is told otherwise

`KLayout.Render` already existed but only ever runs at stream-out, because it
needs a DEF or a GDS; it is registered in the `streamout`/klayout provider
(`stages/providers.py:330`). The issue asks for images *throughout* the flow, so
the new `OpenROAD.SaveImage` reads the **ODB** instead and can be inserted at
any point. It deliberately declares no outputs, so several instances in one flow
cannot collide over a single state view.

The load-bearing detail: `save_image` drives Qt, and with no usable display it
does **not** raise a Tcl error that a step could catch. It fails to load the
`xcb` platform plugin and calls `abort()` — SIGABRT, whole OpenROAD process
gone. Reproduced against OpenROAD `dcf3613` (built `+GUI`, `gui::supported`
returns 1). Setting `QT_QPA_PLATFORM=offscreen` makes it work and produces a
real render, so the step sets it unconditionally rather than letting the outcome
depend on whether a `DISPLAY` happens to exist.

Verified by running the exact Tcl the step generates against
`gcd_nangate45.def`: a 1000x1000 PNG, and `-display_option` demonstrably
changes the output. Note the display-control names are the GUI's own and an
unknown one is a clean `GUI-0013` error, not a crash, so a typo fails loudly.

### 999 — the empty-string route would have silently broken it

The obvious implementation, passing `--lym ""` when the PDK has no `.map`, is
wrong, and quietly so. Verified with the `klayout` Python module: a `.lyt` can
embed the LEF/DEF mapping, `tech.load(lyt)` carries it into
`load_layout_options.lefdef_config.map_file`, and assigning `""` over it turns
it into `None` — destroying exactly the mapping asap7 relies on. So the flag has
to be **absent**, not empty, which is why `get_cli_args` omits it rather than
passing a blank value. Same change in all three pya scripts
(`open_design.py`, `render.py`, `stream_out.py`), where `--lym` became
`required=False, default=None` and the assignment is guarded.

`KLAYOUT_TECH` and `KLAYOUT_PROPERTIES` stay required. Making the dead
`if None in [lyp, lyt, lym]` check real again (it could never fire, since all
three were non-optional `Path`s) means it now guards only those two.

### 993 — the triage was wrong, and so was the Changelog

Two separate findings, both reproduced.

**1. The Changelog overclaimed it.** The line "Fixed lax union coercion choosing
a less-specific scalar type (#993)" came from `e225d51`, the big configuration
redesign. That redesign moved *Pydantic-validated* fields to Pydantic's own
union handling. It did not touch `librelane/config/legacy.py:700-723`, the
ordered union loop, which is still the live path for every `pdk=True` variable
read from a PDK's `config.tcl` (`permissive_typing=True`). Corrected in the
Changelog.

**2. But the planned fix does not work either.** The plan was to make the loop
respect the declared member order. Declaration order is not reliably
recoverable. `typing.Union[X, Y]` and `Union[Y, X]` compare equal *and hash
equal*, and `typing`'s `_tp_cache` is an `lru_cache` keyed on the arguments, so
the nested `Optional[Union[...]]` form used throughout this codebase's variable
declarations returns whichever equal union was built first in the process.
Verified on Python 3.14.3:

```
Optional[Union[bool, int]]      args=(bool, int, NoneType)
Optional[Union[int, bool]]      args=(bool, int, NoneType)   <- not as written
Optional[Union[str, int, bool]] args=(str, int, bool, NoneType)
Optional[Union[int, bool, str]] args=(str, int, bool, NoneType)   <- not as written
```

The direct three-argument form `Union[int, bool, None]` *does* keep its order;
only the nested `Optional[Union[...]]` spelling collapses, and that is the
spelling the variables use. So the order the loop sees depends on module import
order, which is not something a fix can stand on.

A correct fix has to rank candidate types by a fixed specificity order
independent of what `get_args` reports, with `str` last as the fallback the
issue asks for. That is a coercion *policy* decision: the issue is labelled a
breaking change and donn explicitly floats "just not doing this and making PDKs
use `meta.version = 2` YAML files" as the alternative. Left in D deliberately —
it needs the maintainer to choose the policy, not a guess.

Reproduction kept out of the tree; the four-line probe is
`Optional[Union[bool, int]]` vs `Optional[Union[int, bool]]` through
`typing.get_args`.

Best next candidate: **696**, investigated, with the exact files and call sites
recorded below. Note `KLayout.LVS` **already exists** at
`librelane/steps/klayout/lvs.py:33`; it is registered but appears in no flow and
no stage provider, and its `run` only does real work for `ihp-sg13g2` /
`ihp-sg13cmos5l`. The metric collision is real and confirmed: `Netgen.LVS`
writes `design__lvs_error__count` at `librelane/steps/netgen.py:97` and
`KLayout.LVS` writes the same key at `librelane/steps/klayout/lvs.py:137`, while
`librelane/stages/taxonomy.py:297` contracts that key for the `lvs` stage. State
metrics are a flat dict, so whichever runs second wins and `Checker.LVS`
(`librelane/steps/checker.py:329`) only ever sees the survivor.

**692** was mis-scoped by the issue title. Uncommenting `target($gds_out, ...)`
would *not* have worked: `target()` and `report()` both claim the single output
channel `output` writes to, and the last call silently wins. Verified with
KLayout 0.30.7 on a two-box test case: `target` after `report` gives a report
database with zero categories and zero items; `report` after `target` gives an
empty layout. `target()` also changes `output`'s signature -- under a layout
target the first argument must be a `LayerInfo` or a layer number, so the
script's `output(layer_info.to_s, description)` raises `TypeError: no implicit
conversion of String into Integer`. The GDS is therefore built directly with
`RBA::Layout` and written at the end, which keeps both outputs.

While fixing **889** it turned out `ProcessStatsThread` is a bare
`threading.Thread`, so its one `logger.warning` had no step or flow attribution
at all and would have been dropped by every scoped sink. It now carries a
`contextvars` copy taken on the constructing thread. Note Python 3.14 added
`Thread(context=...)` and inherits the caller's context when
`sys.flags.thread_inherit_context` is set, but that flag is **0** in this
environment and the project supports 3.10+, so the explicit copy is
load-bearing. Beware: `Thread` itself owns the attribute name `_context` on
3.14, so the copy is stored as `_log_context`.

### Blocked on verification not possible headlessly

- **728** (KLayout tips dialog). The config key is `tip-window-hidden`, confirmed
  in `libklayout_lay.so`, but the value is a list of `<tip-id>=<button>` entries
  (a real klayoutrc reads `editor-mode=4,editor-mode=0`), not a boolean. Guessing
  the button index could silently put KLayout into editor mode. Needs one GUI
  session. A speculative fix was written and then reverted.
- **813** (`TRACKS_INFO_FILE` optional). Plausible via a bare `make_tracks`, but
  needs a sky130 and gf180mcu regression diff of the resulting DEF track pattern.
- **931** (`sky130_fd_sc_hvl`/`hs` in CI). A 12-line change, but hvl was disabled
  with a `# TODO fix` and will likely fail. Enabling a known-failing job needs a
  CI run.

## E. Skipped — architectural or product decision

45, 401, 480, 488, 489, 503, 506, 537, 543, 559, 561, 568, 572, 613, 614, 624,
625, 641, 642, 659, 693, 697, 703, 754, 775, 777, 801, 804, 808, 842, 911, 914,
918, 923, 946, 951, 975, 995, 996, 998

- **697** removing the `PDK` default is one line but breaks every example and CI
  config; tied to the "PDK dictates flow defaults" redesign.
- **754** `variable(unsafe=...)` metadata exists but is never read; needs a
  remote-execution model first.
- **911** (rearchitect the config module) has no acceptance criteria, but this
  fork has already delivered most of it: `e225d51` redesigned configuration
  loading and validation, `70e4917` moved shared configuration groups to typed
  models, `89151ad` made step configuration reads checkable, and `config/` is now
  split into `loading/` and `preprocessor/` packages over typed nested `Config`
  models. Still standing: `config.py` at 1061 lines, `legacy.py` at 870 lines of
  OpenLane back-compat, and the exact hack the issue names by example, a
  one-element `GlobMatch` collapsing to a scalar `Path` at `common/types.py:57`.
  mole99's follow-up, reworking how SCLs are specified so multiple SCLs can be
  loaded for VT-swap optimization, is untouched.
- **951** is only loosely a symptom of 911. `PAD_LIBS` exists (`config/flow.py:430`)
  and its third point, SCLs that lack the three common corners, is partly covered
  by the 605 corner-granularity warning. Its first point is an OpenROAD warning
  about a library already being loaded, and its second is a decision about how
  many corners a PDK should default to.

## F. Skipped — external (upstream tool, PDK data, or needs the reporter)

123, 295, 376, 397, 509, 515, 519, 522, 531, 538, 547, 569, 585, 590, 634, 635,
653, 674, 681, 684, 735, 751, 769, 774, 776, 778, 803, 814, 891, 912, 935, 944,
962

## Triage corrections worth knowing

Subagent verdicts that were checked and found wrong, so re-verify before trusting
a triage line:

1. **550** was reported already-done from a binary string scan. It fires 10 times
   per sky130 run. Fixed for real.
2. **744** was reported fix-now, claiming `route__drc_errors` is never written. It
   is written by OpenROAD, and the flow does fail. Disproved by experiment.
3. **PR 943 (940)** extends an `lru_cache`d list in place; migrated with a copy
   and a test that fails without it.
4. **728**'s config key was right but the value format is not a boolean.
5. The first **521** attempt was wrong about DRT being single-threaded; corrected
   in `311cff2`.
6. **797** was under-stated. The stale ratio is only half of it: the old loop
   also took `Required ratio:` from the *violating* CAR line while taking
   `Partial area ratio:` from the *non-violating* PAR line above it, so the two
   columns came from different checks. On a real IHP-shaped report that yields
   `Partial=12.34, Required=3091.96, P/R=0.0040` where the truth is
   `7298.29 / 3091.96 = 2.36`, which sorted the worst violation to the *bottom*
   of a table sorted worst-first. The original code comment
   (`Partial/Required: 2.36, Required: 3091.96, Partial: 7298.29`) is itself a
   CAR pairing, so the author's own example was a case the code never parsed.
   Ratio kind (`Gate area` / `Cumulative area` / `Side area` /
   `Cumulative side area`) is now a column. Format confirmed against
   `OpenROAD/src/ant/src/AntennaChecker.cc`, which emits the four checks in the
   order PAR, CAR, then PSR, CSR on routing layers.

## Shared counter and golden files

Four worktrees regenerate these from trees lacking each other's commits, so a
regeneration **replaces rather than adds** and whoever merges second silently
reverts the first. Reconcile arithmetically, never by re-running a generator.

What this branch moves, against `5d63684`:

| File | From | To | Commits |
|---|---|---|---|
| `test/config/test_model_registry.py` (declaration count) | `346` | `351` | `610482d` (+1, `KLAYOUT_XOR_WRITE_GDS`, #692), `0ec2b9e` (+4, the `SAVE_IMAGE_*` group, #611) |
| `test/steps/registry_snapshot.json` | 172 entries | 173 entries | `0ec2b9e` — one **addition**, `"OpenROAD.SaveImage"`, no removals |

`test/flows/classic_gating.json` and its `GATING_VARIABLES` list: **not touched**.
`classic_steps.json` / `vhdl_classic_steps.json`: **not touched**.

So this branch's contribution is `+5` to the declaration count and `+1` line to
the registry snapshot. Both are purely additive and can be merged by summing
deltas rather than by regenerating.

## Test baseline

**Verify with plain `uv run pytest`.** `pyproject.toml:117` sets
`addopts = "--strict-markers -m 'not step_impl_test'"`, so the bare command is
already the canonical selection: everything except the step implementation
tests.

The canonical baseline on `librelane-unstable` is
**777 passed / 192 deselected / 1 xfailed**.

Do **not** use `-m all`. It overrides the `addopts` marker expression rather
than adding to it, so it selects a different and smaller set — the 732 passed /
45 deselected figure an earlier revision of this file recorded as the baseline.
Both numbers are real for their own command; only that command was the wrong one
to measure against. `-m all` also silently drops tests that carry no `all`
marker, which is how a real regression survived six commits here: adding
`KLAYOUT_XOR_WRITE_GDS` for **692** broke the deliberate anti-shrinkage counter
in `test/config/test_model_registry.py:45`, and no `-m all` run ever selected
that test. Fixed in `610482d` (346 → 347).

Two things make the numbers differ between the main checkout and a worktree:

- `test/steps/all` is a **git submodule** (`librelane-step-unit-tests`, see
  `.gitmodules`) and **a new worktree does not populate it** — `git worktree
  add` does not check submodules out, so the directory is empty and
  `git ls-tree HEAD test/steps/all` shows a bare `160000 commit` entry. The
  fixture that reads it is `collect_step_tests()` in `test/steps/conftest.py`,
  which globs `test/steps/all/by_id`; with the submodule checked out it finds
  the step-impl directories and `addopts` deselects **192**, with it empty only
  **1**. A worktree reporting "1 deselected" is therefore not a different tree
  and not a marker-filter artefact — it is an unpopulated submodule, and
  `git submodule update --init test/steps/all` is what closes the gap. Both
  causes compound: the marker expression explains 777-vs-732, the submodule
  explains 192-vs-1.
- The passed count moves with the tests each slice adds.

In this worktree after 797, 889, 692, 924, 812, 910, 696, 999, 611 and the
599 preparation (steps 1-7):
**823 passed / 1 deselected / 1 xfailed**, which reconciles exactly against the
canonical baseline as 777 + 46 added tests. `ruff check` clean,
`ruff format --check` clean over 246 files, `mypy` clean over 147 source files.

The dummy PDK in `test/conftest.py` gained `KLAYOUT_TECH`,
`KLAYOUT_PROPERTIES` and `KLAYOUT_DEF_LAYER_MAP` (and the three files they
point at) in `f80dc33`. Without them no KLayout step could be constructed in a
test at all, which is worth knowing before starting **999**.
