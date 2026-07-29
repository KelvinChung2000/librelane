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
| 621 | `ab57d84` | Reproducibles created from composite steps actually run |
| 630 | `7f84df7` | `report_dont_touch`, `report_dont_use`, `filler_placement -verbose` |
| 802 | `c563a13` | `LINTER_INCLUDE_PDK_MODELS` made functional |
| 920 | `07eb1e8` | `OpenROAD.DiodeInsertion` registered so its reproducibles load |
| 928 | `d9eff48` | `gds maskhints true` (cherry-picked upstream `9636a6b`, authorship kept) |
| 940 | `09b2313` | Macro libs and `EXTRA_LIBS` reach the synthesis lib set (from PR 943, with its cache bug fixed) |
| 947 | `286a8aa` | Warn when the PDN halo exceeds the row-cutting halo |
| 948 | `6d717bc` | `MAGIC_WRITE_LEF_PINONLY` defaults to `True` **(breaking)** |
| 974 | `869cf4c` | `t_ck` removed from the arrival-time equations |
| 997 | `5d865bb` | `PDN_CFG` marked `pdk=True` |
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
| 692 | S | XOR: add a variable to save the GDS; `target($gds_out,...)` is commented out in `xor.drc` |
| 696 | S | Add `KLayout.LVS` to Classic behind `RUN_KLAYOUT_LVS`. Caveat: it shares the metric key `design__lvs_error__count` with `Netgen.LVS` |
| 797 | S | `CheckAntennas.__summarize_antenna_report` has no regex for `Cumulative area ratio:`, so CAR/CSR violations carry a stale partial ratio and are mislabelled |
| 812 | S | Write an aggregate `runtimes.csv` from `Flow.step_objects` |
| 824 | M | `YosysSynthChecks` counts from `pre_synth_chk.rpt` but users grep `chk.rpt`; report the offending lines and the source path |
| 889 | M | `error.log` / `warning.log` sinks filter by level only, so concurrent flows cross-contaminate. Needs a `flow_run` contextvar in the sink filters |
| 910 | S | Warn when a macro's `.lib` has cells with no pins |
| 917 | M | New `OpenROAD.AddBuffer` step (moves the Classic goldens) |
| 924 | S | Propagate `COLUMNS` to subprocesses so rich tables are not clamped to 80 |
| 993 | M | The Changelog overclaims this. Fixed for the Pydantic path, but `legacy.py`'s ordered union loop still coerces `'1'` to `True` for every `pdk=True` variable before Pydantic sees it |
| 999 | M | Make `KLAYOUT_DEF_LAYER_MAP` optional (4 files) |
| 599 / 600 / 669 | L | Replace `common.Path` with `pathlib.Path` (see below) |
| 532, 558/560, 583, 611, 636, 967 | M | OpenConsole, RMP resynthesis, isosub, layout images, multi-corner STAMidPNR, ReplaceECOCells |

`599` asks for "pathlib.Path **or a subclass of it**", so the direct route needs
no subclassing and `requires-python = ">=3.10"` blocks nothing. An earlier
revision of this file called it blocked on 3.12; that was wrong. Nothing has
migrated yet: `common/types.py:39` still defines `class Path(UserString,
os.PathLike)`, imported by 22 modules, 345 `Path` mentions across 52 files.

The work, none of it blocking:

- `common.Path` **is a string**, so it survives Tcl export, JSON state
  serialization and `str` concatenation for free. `pathlib.Path` does not, so
  every such site needs auditing.
- `validate()` (the existence check) and the `GlobMatch` one-element collapse
  live in the class's `__get_pydantic_core_schema__`. They move into an
  `Annotated[pathlib.Path, ...]` alias, which is what pydantic is for.
- `ScopedFile` is the only subclass and would compose rather than inherit.
- `rel_if_child` becomes a free function over `Path.relative_to`.

`600` (portable states, keeping `dir::` / `pdk_dir::` unresolved and resolving on
access) is the feature `599` was meant to unlock. Also not done.

Best next candidates: **797** (antenna violations are currently mislabelled) and
**889** (concurrent flows cross-contaminate each other's `error.log`).

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
