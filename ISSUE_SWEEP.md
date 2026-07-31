# Issue sweep — status

Working record of the pass over every open issue at
<https://github.com/librelane/librelane/issues>, oldest to newest, started
2026-07-28 on branch `issue-sweep` off `librelane-unstable` @ `fd76520` and
merged back into `librelane-unstable`.

All 152 open issues were triaged. Sections A–B are done, C–D are the queue.
One commit per issue.

Counting them is not as simple as adding up the buckets, so the arithmetic is
written out here once. The A–F lists hold 149 distinct numbers (A 19, B 31,
C 6, D 21, E 40, F 33, with 975 deliberately appearing in both C and E). The
other three, 728, 813 and 931, are triaged in the prose under D rather than in
a list, which is why any bucket-based count comes out three short. 149 plus
those three is 152.

Two corrections are folded into those figures. 571 appeared nowhere in this
file at all on the first pass and has since been triaged into section B, which
is what takes B from 30 to 31. Separately, B has been recorded elsewhere as
holding 28; it never did. That list has not been edited since it was first
written, so the 28 is a transcription slip in the summary rather than drift in
this record.

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

318, 410, 450, 508, 527, 571, 580, 610, 618, 627, 633, 654, 657, 668, 671, 683,
694, 695, 698, 712, 718, 732, 744, 745, 752, 779, 793, 796, 827, 853, 956

Notable: **571** ("review usage of `set_propagated_clock`") reports that the
command is "forced inside OR tcl scripts" when it belongs in the SDC. Reviewed,
and the premise is largely false. There are eleven sites in three roles. The
one that decides what signoff STA reports is `io.tcl:121-128`, which applies a
default only when the SDC mentions neither `set_propagated_clock` nor
`unset_propagated_clock`, so it defers to the user rather than overriding them.
Nothing under `scripts/openroad/sta/` touches propagation at all. The eight
unconditional calls do run after the SDC is read and do override it, but they
are in the per-stage PnR scripts and they split on physical state, not on
preference: `unset` before CTS, where there is no clock tree to propagate, and
`set` after it, where optimising against an ideal clock would size and buffer
for the wrong slack. Removing them would let pre-CTS repair optimise against a
clock tree that does not exist. Close as answered.

One secondary fragility, found while checking and not worth fixing on its own:
the `io.tcl` guard is `string_in_file`, a raw substring search. A
`set_propagated_clock` in a comment suppresses the default, and one in a file
the SDC `source`s is missed entirely. Fixing it means parsing Tcl. Worth
knowing if propagation ever behaves unexpectedly.

Notable: **744** ("DRT running out of iterations doesn't fail the flow") was
empirically disproved. Running spm with `DRT_OPT_ITERS=1` leaves 9 violations,
OpenROAD writes `route__drc_errors: 9`, `Checker.TrDRC` raises a deferred error
and the flow exits 2. The reporter was on OpenLane 2.2.9.

## C. Migrate from upstream

| Issue | Source | Note |
|---|---|---|
| 680 | commit `bf07672` | `LINTER_VLTS` list replaces the scalar `LINTER_VLT` |
| 790 | open PR 835 | fmax metric |
| 854 | commit `4fc4628` | nix-eda 7 / nixos-26.05 bump (qrencode source moved). Built and run, not just evaluated: see below |
| 893 | commit `cedcd43` | macro array instantiator |
| 901 | open PR 902 | f-list (`*.f`) parser |
| 975 (partial) | commits `b272909`, `dbf73b8`, PR 986 | ABC strategy script, ABC delay target, arith_tree |

Unmerged upstream and issue-adjacent: `acd2341` (GPL GIF), `5b60312` (partial PG
connect), `39a8ada` (`SYNTH_BUFFER_CELL`), `e607def` + `415c7e2` (padring),
`aedda63` + `5fe3db1` (`KLayout.Render`).

### What the nix-eda 7 bump (854) has actually been shown to do

Recorded because "the nix bump was verified" is the kind of claim that grows in
the retelling, and the gap between what was checked and what people will later
assume was checked is where the next surprise comes from.

Shown, on x86_64-linux:

- The flake evaluates and both `librelane` and the default dev shell
  instantiate, so no attribute was renamed out from under the fork.
- The closure builds. KLayout 0.30.9, `yosys-with-plugins` 0.66, `tkinter`,
  librelane itself and the C extensions all compiled. OpenROAD did not compile
  and should not have: it substituted from `nix-cache.fossi-foundation.org`,
  which is stronger evidence than a local rebuild, because a cache hit proves
  the derivation hashes match upstream's exactly.
- The built artefact runs. `bin/librelane --version` reports v3.0.5, and the
  Yosys in that closure answers `help arith_tree`, which closes the chain from
  the version bump to the pass `SYNTH_ARITH_TREE` depends on, on the binary
  rather than inferred from a version string.

Not shown, and not to be claimed:

- Only x86_64-linux was built. ciel 2.5.x dropping Intel Macs, and the
  `lib.meta.availableOn` change to the `yosys-ghdl` gate, are untested.
- Nothing was run through an actual flow. This establishes that the toolchain
  builds and launches, not that a design hardens against it.

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

## G. Defects found on the branch, not in the issue tracker

Unreleased-branch breakage, i.e. introduced by work that lives only on
`librelane-unstable`. None of it is a shipped regression and none of it has an
upstream issue number.

1. **`Classic` could not complete a run.** The `pre_pnr_sta` stage was
   contracted to produce an `sdc` that no OpenSTA script writes, so every run
   died at that stage boundary with "completed without producing views
   ['sdc']". Reproduced on the bundled spm example with no local changes
   applied. Root cause was `MultiCornerSTA.outputs` declaring a view the class
   never writes, which `Stage(pre_pnr_sta).provides` was then derived from and
   which `StageRegistry` accepted because it checks *declared* outputs. A
   step's declared outputs are not enforced anywhere else, so the lie had
   nowhere to surface until stage contracts started reading it. The same
   pattern was in `PrimeTime.STAPrePNR` (`SDC`, copied from the comment),
   `OpenROAD.DumpRCValues` (five views, script writes only reports) and the
   three vendor `Floorplan` scaffolds (an `SDC` *input* nothing produces).
   Fixed at the root, with two tests for the general class of bug rather than
   for the instance.
## Facts worth not rediscovering

Found while implementing; none of them are written down anywhere else.

- **A stage provider's config variables are namespace-checked at import time.**
  `librelane/stages/registry.py` rejects a variable declared on a provider step
  that is neither a common flow variable nor prefixed with one of the provider's
  namespaces, raising `StageError` when the module is imported. So an unprefixed
  name on, say, `KLayout.StreamOut` is not merely bad style, it fails to import:
  `Provider 'klayout' for stage 'streamout' declares variable 'ISOSUB_LAYER',
  which is neither a common flow variable nor prefixed with any of
  ['KLAYOUT_']`. A variable two tools both need belongs in `config/flow.py`,
  not on one of them.
- **OpenROAD's `rmp` README documents a `-target` value the code rejects.**
  `src/rmp/README.md` says `-target area|delay`, but `Restructure::setMode`
  compares against `"timing"` and `"area"` only, and on anything else emits
  `utl::warn RMP 10` and leaves area mode selected. Passing the documented
  `delay` therefore silently optimizes for area. `RMP_TARGET` is
  `Literal["timing", "area"]` for this reason. Upstream documentation bug, not
  fixed here.
- **`test/steps/all` is a git submodule** (`librelane-step-unit-tests`). A fresh
  worktree does not populate it, so the 192 `step_impl_test` cases are never
  collected and `uv run pytest` reports 777 passed / 1 deselected instead of
  777 passed / 192 deselected. The passed count is the invariant.

## Blocked on a maintainer decision, not on code

- **531 / 583** (isosub). The two stream-out options are implemented. The
  standalone `Magic.AddIsosub` step from upstream PR 583 is not, and should not
  be until someone decides what it is for. In that patch the step's script is
  gated on `MAGIC_ADD_ISOSUB`, the same variable that gates the painting inside
  `Magic.StreamOut`, so enabling either enables both and the step's only reason
  to exist -- applying isosub after signoff DRC rather than before -- is
  defeated. Where it would go here is also open: Classic is a stage list,
  `Stage.drc` is atomic so upstream's "between `KLayout.DRC` and
  `Checker.MagicDRC`" has no equivalent, and a full-die SUBCUT rectangle would
  reach LVS extraction and XOR. Issue 531's body is two sentences and the
  maintainer's request for a rationale was never answered.

## Section B re-audit — the "already done" list does not hold

Every one of the 30 entries in section B was re-checked against the code.
**Twelve do not hold up.** Section B is not safe to close as a batch.

Not resolved at all:

- **683** `PRIMARY_GDSII_STREAMOUT_TOOL`. Fixed here.
- **718** KLayout DRC for gf180mcu. See below; the root cause is PDK data.
- **793** SystemVerilog frontend. The capability existed but was documented
  nowhere. Documented here.
- **853** DRC inspection guide. Does not exist. The newcomers section predates
  the issue and cites filenames the flow no longer produces.

Partial: **410** (three deprecation warnings still emitted before any log sink
exists, including the `.tcl`-config one every OpenLane 1 migrant hits), **508**
(`OpenROAD.PadRing` and the `Chip` flow exist, but no documentation, no example,
and `config/removals.py:41` still says `FP_PADFRAME_CFG: "To be implemented."`),
**580** (both mounts guarded, but the warning the issue also asked for was never
added), **610**, **618**, **627** (fixed for the Toolbox here; Yosys still cannot
read gzipped SCL dotlibs), **657**, **668**, **745**, **956**.

Genuinely resolved, with commits: 318, 450, 527, 633, 654, 671, 694, 695, 698,
712, 732, 744, 752, 779, 796, 827.

### 718 belongs to the PDK, not here

The reporter is right that gf180mcu ships a KLayout DRC runset. It is at
`libs.tech/klayout/tech/drc/gf180mcu.drc`. The PDK's own
`libs.tech/openlane/config.tcl:126` points at
`libs.tech/klayout/drc/gf180mcu.drc`, missing the `tech/` component, and no such
file exists. LibreLane then deletes `KLAYOUT_DRC_TECH_SCRIPT` for gf180mcu at
`config/pdk_compat.py:184-185`, under a heading reading "Invalid Variables
(gf180mcu)", which is why the step is skipped rather than failing on a missing
file.

`pdk_compat.py` is the designed place to correct a broken PDK config, so
rewriting the path here would work. It is deliberately not done, because it
would switch on a signoff check that has never run in this repository against a
PDK whose runset LibreLane's invocation has never been tested with, and that
cannot be verified headlessly. Same category as 931. The durable fix is in the
gf180mcu PDK's `config.tcl`.
