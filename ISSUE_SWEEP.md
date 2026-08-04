# Issue sweep — status

Working record of the pass over every open issue at
<https://github.com/librelane/librelane/issues>, oldest to newest, started
2026-07-28 on branch `issue-sweep` off `librelane-unstable` @ `fd76520` and
merged back into `librelane-unstable`.

All 152 open issues were triaged. Sections A–B are done, C–D are the queue.
One commit per issue.

Counting them is not as simple as adding up the buckets, so the arithmetic is
written out here once, and every figure below was counted out of this file
rather than carried forward from a previous revision.

The lists hold A 27, A2 21, B 31, C 6, D 2, E 40 and F 33. That is 160 entries
but only **149 distinct numbers**, because a fixed issue keeps its row in the
bucket that first classified it. The overlaps are deliberate and are the whole
set: A2 with C on all six of 680, 790, 854, 893, 901 and 975, since C was the
migrate-from-upstream queue and it is now empty; A2 with B on 627, 683 and 793,
which were filed as already-done and turned out to need code after all; A2 with
F on 531; and 975 in both C and E, as it always was. The other three issues,
728, 813 and 931, are triaged in prose under D rather than in a list, which is
why any bucket-based count comes out three short. 149 plus those three is 152.

Two traps in doing this count yourself. Issue **45** is two digits, so a regex
of `\d{3}` silently drops it and lands you on 151. And section A grew from 19
rows to 27 as later work was appended to it, so its old header count is not a
safe input.

One correction is folded into the figures. 571 appeared nowhere in this file at
all on the first pass and has since been triaged into section B, which is what
takes B from 30 to 31. B has also been recorded elsewhere as holding 28; it
never did, and that list has not been edited since it was first written, so the
28 was a transcription slip in a summary rather than drift in this record.

Before implementing anything from C or D, run `git log HEAD..upstream/dev
--oneline` first — this branch is missing roughly 31 commits merged upstream,
and several open issues are already solved there. Most do not cherry-pick
cleanly, because upstream still has the monolithic `librelane/steps/openroad.py`
and `librelane/config/variable.py` that this fork split into packages, and still
uses `config_vars = [Variable(...)]` lists where this fork uses nested typed
`Config` models. Port by hand and credit the original author with
`git commit --author`.

## A. Fixed in the serial sweep — 27 issues, one commit each

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

## A2. Fixed in the parallel wave — 21 further issues

Section A was one agent working serially. This wave was five working disjoint
slices in their own worktrees, merged branch by branch onto `sweep-merge`.

| Issue | Commit | What |
|---|---|---|
| 531, 583 | `a014131` | Option to stream out the isolated substrate layer |
| 532 | `6870f74` | Launch OpenROAD and OpenSTA interactively |
| 558, 560 | `0184e35` | OpenROAD local resynthesis |
| 599, 669 | `bd25aea` and six preparatory commits | `common.Path` becomes `pathlib.Path` |
| 627 | `c50f500` | Liberty readers accept gzipped `.lib` files (partial) |
| 636 | `c15b74c` | Every corner reported in mid-PnR STA |
| 680 | `6c7cb9e` | A list of Verilator configuration files |
| 683 | `ad7433d` | A non-primary stream-out writes the GDS if nothing else did |
| 696 | `9a9cec0` | `KLayout.LVS` selectable as the `lvs` job's second provider |
| 790 | `b51db85` | Maximum frequency per STA corner |
| 793 | `5c08c58` | The SystemVerilog frontend documented |
| 824 | `5102dd6` | The synthesis check problems the count refers to are logged |
| 854 | `1f843b6` | nix-eda 7 / NixOS 26.05 |
| 893 | `8d3dafc` | Macro instances expand into arrays |
| 901 | `681149a` | F-lists (`*.f`) parsed in the preprocessor |
| 917 | `457c060` | Ports buffered before global placement |
| 967 | `741ac67` | An ECO step that replaces cells |
| 975 | `67724ec`, `f31dd77` | ABC delay target, custom strategy script, `arith_tree` |

Three further one-line bugs surfaced by the section B re-audit carry no issue
number: a corner filter that ignored the pattern `VIAS_R` names (`461c886`), a
`DRT_ANTENNA_REPAIR_MARGIN` that was declared and never honoured (`256ca82`),
and a debug log line with a dead environment variable (`4378fd5`).

Verified at the merge of all five branches: 906 passed, 1 deselected,
1 xfailed, `ruff check`, `ruff format --check` and `mypy` clean. The single
deselection is `test/steps/all`, a submodule a fresh worktree does not
populate. The nix closure builds and the built binary runs, with the limits of
that claim written out under section C.

Four of the twenty-one were not the change the issue asked for. 627 could not
be done the way the issue preferred, because `libparse` reads from the file
descriptor and cannot be handed a decompressed stream. 683's reporter proposed
the implemented fix and the issue text did not. 696 implements the prerequisite
for a substitution the maintainers were still discussing, not the co-running
shape the issue describes. 797's real defect was twice what was reported. In
each case the evidence is in the commit message.

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

### C2. The upstream backlog no open issue covered — done

This stood as a single line naming six unmerged upstream commits with no issue
number between them. All six are ported, by hand rather than cherry-picked,
with the original authors credited.

| Upstream | Commit here | What |
|---|---|---|
| `39a8ada` (#961) | `92f9992` | `SYNTH_BUFFER_CELL` names the buffer used when buffering ports |
| `5b60312` (#991) | `133506f` | An instance may leave some power/ground ports open |
| `aedda63` + `5fe3db1` (#964, #973) | `1d5f3d0` | `KLayout.Render` takes either of its views, or neither |
| `acd2341` (#985) | `f41bdaa` | Global placement captured as a GIF animation |
| `e607def` (#925) | `e76507b` | Pad site rotation and the core ring's pad layers (partial) |
| `415c7e2` (#965) | `4f3a210` | Configurable pad spacing, and pad rings with empty sides |

Three things were deliberately not ported, and each would otherwise look like
an oversight.

The `LIB` to `CELL_LIBS` rename carried by `e607def` is a cross-cutting rename
across nine modules plus `pdk_compat`, `toolbox` and two test files, and it
also moves `PAD_LIBS` into the Python-side lib lists so pad liberties reach
Yosys blackboxing. Upstream files it under miscellaneous bugfixes; it is a
feature of comparable size to this entire slice, and half-porting it would be
worse than not starting.

The `pdk_hashes.yaml` and submodule bumps are PDK data. The sky130 half of
upstream #925 also needs `RTimothyEdwards/open_pdks#506`, which this branch
cannot supply or check.

Upstream's `PAD_SPACING_MULTIPLE` default of 1 µm replaces rounding to the pad
site width, so it silently re-spaces the ring on any PDK whose pad site is not
1 µm wide, gf180mcu included. The variable is optional here, with unset meaning
the pad site width, which is the previous arithmetic exactly. That is a
documented null-behaviour of the kind `PL_TARGET_DENSITY_PCT` and `PDN_CFG`
already use, not a fallback.

Two upstream defects were found rather than reproduced. `acd2341`'s
`get_command` binds `mode_options` only inside `if "-gui" not in cmd` and then
uses it unconditionally, so an interactive run raises; it also assumes the
binary is spelled `openroad`, which `_LLN_OVERRIDE_OPENROAD` makes false. And
`aedda63` leaves `Toolbox.render_png` reading an image file back
unconditionally, which becomes a `FileNotFoundError` the surrounding
`except StepError` does not catch as soon as the step can legitimately render
nothing. Upstream has the same hole; it is just not reachable from their only
caller.

Not validated, and not claimed: that the OpenROAD GUI comes up, that
per-iteration images are written, that a real pad ring is correct on a PDK
needing rotation, or that a trimmed ring abuts. Those need an X display, pad
LEFs and a padring design. What is verified is the argv, the guards and
ordering, the existence of every flag in the pinned OpenROAD, and that the
default path produces byte-identical tool invocations to before.

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

## D. Ready to implement — what is left of the queue

Both remaining entries have since been worked. What is left of 600 is stated
below and is a maintainer's call, not an implementation task.

| Issue | Size | Summary |
|---|---|---|
| 600 | M | **Reader half done.** `State.load`/`loads` take an optional `symbols` mapping and resolve `pdk_dir::` through the preprocessor, which fixes a live bug: the reproducible writer emitted directives into `state_in.json` that nothing could read back. The writer half for ordinary `state_out.json` is **not** done and needs a decision; see below |
| 993 | — | **Done.** The five `KLAYOUT_*_OPTIONS` unions are now `int \| bool \| str`, and the legacy numeric branch refuses a Boolean. See below; this entry was wrong twice before it was right. Changelog corrected in `9c7683c` |

`599` asks for "pathlib.Path **or a subclass of it**". The direct route needs no
subclassing. An earlier revision of this file called the work blocked on 3.12;
that was wrong — *nothing* is blocked. One **hard design constraint** used to
fall out of the version floor and governed the whole shape of the migration:

> **`pathlib.Path` could not be subclassed before Python 3.12, and
> `requires-python` was `">=3.10"`.** Subclassing it needs `_flavour`, which is
> private and absent on 3.10/3.11.

So anything that wanted to *be* a path had to **compose** one and implement
`os.PathLike`, not inherit. That is why `ScopedFile` was recomposed in
`9fb0886` — a prerequisite, not tidying — and it is why the pydantic behaviour
lives in an `Annotated` alias rather than in a subclass's
`__get_pydantic_core_schema__`.

**This constraint has since been lifted.** `requires-python` is now `">=3.13"`,
so `class Path(pathlib.Path)` is legal on every supported version and the
`TypeError` this section warned about can no longer happen. Nothing below was
rewritten on that account: the composed design works, is shipped, and is
covered, so the constraint is now a *reason the code looks as it does* rather
than a rule constraining what may be written next. A future revision of `599`
may subclass if subclassing genuinely reads better — that is now an open design
choice and not a forbidden one.

`600` (portable states, keeping `dir::` / `pdk_dir::` unresolved and resolving on
access) is the feature `599` was meant to unlock. It is now half done, and the
half that was done was a **live bug rather than a missing feature**, which this
entry previously understated.

`create_reproducible` runs one visitor over both the configuration and the input
state (`reporting.py:283`), so `pdk_dir::<relative>` was already being written
into `state_in.json` as well as `config.json`. But `Config.load` resolved those
directives through the preprocessor while `State.load` only did
`pathlib.Path(value)` plus an existence check. A `--no-include-pdk` reproducible
whose input state named a PDK-resident view therefore wrote
`{"gds": "pdk_dir::cells.gds"}` and then could not read it back, failing with
`ValueError: Provided path 'pdk_dir::cells.gds' ... does not exist`. A writer
with no matching reader, producing a reproducible that could not be run.

`State.load` and `State.loads` now take an optional `symbols` mapping and
resolve through the preprocessor's own `parse_directive` / `resolve_directive`,
with `Step.load` supplying `PDKPATH` and `DESIGN_DIR`. Without `symbols` the
behaviour is byte-identical, so the other three call sites are untouched.

**What is left needs a decision, not an implementation.** Ordinary
`state_out.json` still stores absolute paths, and that is the larger half of the
issue. It needs a root to be relative to, and none of the three that exist will
do: there is no `run_dir::` directive, `DESIGN_DIR` stops containing the run
directory as soon as `--run-tag` or `-o` moves it, and `PDKPATH` is irrelevant
to a step's outputs. Adding a directive and changing the on-disk format of every
state file is the breaking change the issue is labelled with.

**Status of `599`: done.** `1dbc187` moved the three members that could not
survive off the class; `bd25aea` performed the swap. The preparation list and
the cost measurement below describe the problem *before* the swap and are kept
for the reasoning, not as a to-do list. The preparation landed in `14874a6`,
`4cf5d52`, `3c27a9a`, `e359348`, `7779364`, `c9e6243` and `9fb0886`.

#### What landed

`common.Path` is now `Annotated[pathlib.Path, _PathAnnotation]`. Values are
ordinary `pathlib.Path` objects; the glob collapse and the existence check live
in the `Annotated` metadata, because of the subclassing constraint above, which
held when this landed and has since been lifted.
Three members moved off the old class first, since nothing can be added to
`pathlib.Path`: `Path._dummy_path` → `common.DUMMY_PATH`, `Path.validate()` →
`common.validate_path()`, `Path.rel_if_child()` → `common.rel_if_child()`
(which now returns `str`, because `relative_prefix` is a property of the
*spelling* and a path object cannot carry a leading `./`).

Keeping the name `Path` for the alias left all ~110 annotation sites untouched
and moved ~105 constructor and `isinstance` sites to `pathlib.Path`.

**A correction to the design rationale.** The failure mode is *not* symmetric
the way this file predicted. `typing._AnnotatedAlias` forwards `__call__` to its
origin, so `Path("x")` does **not** raise — it quietly returns
`pathlib.Path("x")`, which is the right object. Only `isinstance(x, Path)`
raises (`TypeError: Subscripted generics cannot be used with class and instance
checks`). So the `isinstance` sites were the ones that genuinely had to be
found; a missed constructor would have been harmless. The asymmetry is pinned by
`test_path_is_an_annotated_alias_that_rejects_isinstance` in
`test/common/test_types.py`, because if a future typing release made the alias
`isinstance`-able, a missed site would start silently answering the wrong
question.

#### The two semantic decisions, and how they were settled

Both are in `steps/step/reporting.py`, and both came out the same way: **emit a
`str`, not a path.**

- `pdk_dir::<relative>` is a preprocessor directive naming a file the
  reproducible does not carry. It is not a path at all, and resolving it is the
  reader's job. This is also exactly what `600` needs.
- `./files/<relative>` says the emitted config is read from *inside* the
  reproducible directory. `pathlib.Path` normalises the `./` away and cannot
  carry it back.

Both still appear verbatim in the emitted `config.json`, pinned by
`test_create_reproducible_uses_portable_paths`. `GenericDictEncoder` was already
correct for either representation, so nothing else had to change.

#### Three things the swap broke that were not on anyone's list

- **Runtime type tests must not compare to `pathlib.Path` by identity.**
  Annotations are captured when a module is imported; `pyfakefs` replaces
  `pathlib.Path` afterwards, and the configuration tests run under it. An
  identity test then answered "not a path" for a genuine path variable, skipped
  validation entirely, and fell through to `__process`'s generic
  `validating_type(value)` — the exact silent wrongness this migration was
  supposed to avoid. `common.is_path_annotation()` asks about `os.PathLike`
  instead, which no test double swaps out.
- **Pydantic strips `Annotated` metadata from top-level field annotations**
  (`field.annotation` becomes bare `pathlib.Path`, metadata moves to
  `field.metadata`) but leaves it intact inside `list[...]` and `Optional[...]`.
  Both spellings therefore occur, which is why `unwrap_annotated()` exists. It
  also meant `config/model.py` rebuilding a `TypeAdapter` from
  `field.annotation` alone validated against a bare `pathlib.Path`, losing the
  glob collapse and the existence check; `_annotation_of()` reattaches the
  metadata.
- **Two mypy errors the old type had been hiding.** `abspath()` of the old path
  type returned `Any` and poisoned list inference at two call sites, so a
  `Traversable` and a list of `bool`/`int` in `Sequence[str | os.PathLike]`
  argument lists both type-checked by accident.

#### And one correction to this file's own claim

The previous revision said the test residue was **empty** — that "no test in the
tree compares a `common.Path` to a `str`". That was wrong. The claim was checked
only for `State`, which indeed does not coerce, and then generalised. Eleven
tests compared a path to a `str` *transitively* — a `list[Path]` against a
`list[str]`, a `Config` against a dict of `str` — and passed only because
`UserString` compares equal to `str`. All are fixed by comparing paths to paths,
or `str()` to `str()`, whichever the test was actually about.

#### Known regression

`librelane.common.Path` no longer appears in the generated API reference.
`docs/_ext/generate_module_autodocs.py` selects members by
`inspect.getfile(attr)` landing inside the tree, which an alias over
`pathlib.Path` does not. Type aliases were never documented by that generator
(`AnyPath` is not either), so this is a gap in the generator rather than in the
migration; the semantics are written out inline in
`docs/source/usage/writing_custom_steps.md`. The docs build is otherwise clean.

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
   `os.PathLike`. Nothing subclasses the path type any more, pinned by
   `test_no_librelane_type_subclasses_pathlib_path`. Breaking for anyone who
   relied on a `ScopedFile` being a `str`; zero call sites in the tree.
8. ~~The annotation swap and deleting the `UserString` class~~ — **done,
   `1dbc187` and `bd25aea`.** See "what landed" above.

#### What the swap actually costs, measured

*Historical: this is the pre-swap measurement and the design argument that chose
the shape. Two of its claims turned out to be wrong; both are corrected inline
below and in "what landed" above.*

Counted on this branch rather than estimated:

| | count |
|---|---|
| `Path` in annotation position (`: Path`, `Optional[Path]`, `list[Path]`, …) | ~110 across 24 files |
| `Path(` runtime constructor calls | 103 |
| `isinstance(…, Path)` | ~26 across 10 files |
| modules importing `common.Path` | 33 |

**The design that minimises the diff.** `Path` cannot stay one name doing both
jobs, because the pydantic behaviour has to live in an `Annotated` alias (see
the subclassing constraint above, since lifted) and an `Annotated` alias is neither
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

The first was taken, and it was the right call — but *not* for the reason given.
**Correction:** an `Annotated` alias **is** callable; `typing._AnnotatedAlias`
forwards `__call__` to its origin, so `Path("x")` silently returns the correct
`pathlib.Path`. Only `isinstance` raises. The first option was still right,
because the `isinstance` sites are the ones where a miss would change meaning,
and those are exactly the ones that fail loudly.

Three things must move off the class before it goes:

- `Path._dummy_path` → a module constant. Used at `common/toolbox.py:301` and
  throughout `test/config/test_variable.py`.
- `Path.validate()` → a free function. Called at `common/types.py:138` and
  **`config/legacy.py:791`**, which the category sweep missed.
- `rel_if_child` → free function. Already correct as of `3c27a9a`, still zero
  call sites.

**Corrections to the audit's categories 5 and 6.** Both were over-stated, and
both were checked at runtime rather than read:

- ~~**"Tests that assert `Path == str` fail immediately" is wrong — that residue
  is empty.**~~ **This correction was itself wrong; see "one correction to this
  file's own claim" above.** `State` does indeed not coerce, so the direct
  `assert state[DesignFormat.NETLIST] == "abc"` cases are unaffected — but that
  finding was generalised without checking the *transitive* comparisons, and
  eleven tests compared a `list[Path]` to a `list[str]` or a `Config` to a dict
  of `str`. They all broke.
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

Steps 1–7 landed in the preparation commits, and the swap itself landed in
`bd25aea`. The acceptance gate that blocked the JSON Schema work was met before
the type change and is still met after it, pinned by the two tests in
`test/config/test_model_registry.py` that name the offending variables.

### 696 — there is no collision today, and the feature is deliberately postponed

Two findings.

**1. The metric key is not a collision; it is the single-provider contract.**
`lvs` is a **single-provider** job (`librelane/jobs/taxonomy.py`) with a
job-level contract `metrics=("design__lvs_error__count",)`. `drc` and
`streamout` are `multi_provider=True`; `lvs` is not. So exactly one LVS provider
runs, and its providers are *alternatives*. `Pegasus.LVS` reuses the same key on
purpose, with the reason written at `steps/pegasus.py:158-161`: it "reuses that
job-level metric rather than inventing a Pegasus-specific name". `KLayout.LVS`
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
`test/jobs/test_providers.py`, which exempts single-provider jobs and will
fail loudly the moment `lvs` becomes multi_provider without the rename.

**2. The participants explicitly asked not to rush it.** donn wants a PDK meta
configuration variable to drive flow composition (which would also retire
`PRIMARY_GDSII_STREAMOUT_TOOL`) plus derivative flows via #648; mole99's reply is
"That's a lot to think about and it feels important to get this right. So let's
better not rush this one :)". That is the same "PDK dictates flow defaults"
redesign that already put **697** in section E.

Implementing the `RUN_KLAYOUT_LVS` boolean as specced would also fight the
architecture: adding `KLayout.LVS` to `Classic` as a plain step, emitting a
job-contracted metric outside any registration, is the exact anti-pattern
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
`multi_provider` job. It does not hold on a single-provider job, where the
providers are alternatives. The structural check — `multi_provider` true or
false — is what distinguishes the two cases, and it is now enforced by
`test_providers_that_run_together_do_not_declare_the_same_metric` rather than
left to judgement.

### 611 — save_image aborts the process headlessly unless Qt is told otherwise

`KLayout.Render` already existed but only ever runs at stream-out, because it
needs a DEF or a GDS; it is a bare step placed immediately after the `streamout`
job (`librelane/flows/classic.py`). The issue asks for images *throughout* the flow, so
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

**2. The planned fix does work, and the claim that it could not was wrong.**
This entry previously said declaration order is not recoverable, so a fix could
not stand on it. That was checked again and it is false for this codebase. It
was stated as fact in four agent briefs and deterred work on the issue, so the
correction is written out in full rather than quietly edited.

The typing behaviour behind the claim is real. `typing.Union[X, Y]` and
`Union[Y, X]` compare and hash equal, and `_tp_cache` is keyed on the argument
tuple, so the **nested** `Optional[Union[...]]` spelling does collapse, on
Python 3.14.3:

```
Optional[Union[bool, int]]      args=(bool, int, NoneType)
Optional[Union[int, bool]]      args=(bool, int, NoneType)   <- not as written
```

The error was the next step, the assertion that this "is the spelling the
variables use". It is not. An AST pass over every `variable()` declaration in
`librelane/` finds **zero** using `Optional[Union[...]]` and nine using a
direct union, and every one of those spellings keeps its order:

```
bool | int | str            -> ('bool', 'int', 'str')
int | bool | str            -> ('int', 'bool', 'str')
Union[None, str, list[str]] -> (NoneType, str, list[str])
```

The only two `Optional[Union[...]]` sites in the tree are type comments in
`env_info.py:208-209`, neither of them a configuration variable. The PEP 604
`X | Y` spelling that the `KLAYOUT_*_OPTIONS` variables use is a
`types.UnionType` and never went through `_tp_cache` at all.

So `librelane/config/legacy.py:821` iterates `get_args(validating_type)` in the
order written and returns the first member that accepts the value, which means
declaration order is not merely recoverable, it is already the entire
resolution rule.

What remains is genuinely a *policy* choice, and a much smaller one than
"impossible": which order to declare, and whether changing it is acceptable
given the issue is labelled breaking and donn floats making PDKs use
`meta.version = 2` YAML instead. That is a decision this fork can take.

**3. And the correction above was itself incomplete.** It said the nine direct
unions all preserve order, so the caching hazard does not apply here. The count
is right and the safety conclusion is wrong.

The five variables that matter are spelled `Optional[dict[str, bool | int | str]]`.
`Optional[X]` *is* `typing.Union[X, None]`, so it goes through `_tp_cache` like
any other; and `types.UnionType` hashes on a frozenset of its members, so the
inner unions compare equal in either order. The consequence, measured:

```
(bool|int|str) == (int|bool|str)                               True
dict[str, bool|int|str] == dict[str, int|bool|str]             True
Optional[dict[str, bool|int|str]] is Optional[dict[str, int|bool|str]]   True
```

Both spellings are the **same object**, and `get_args` reports whichever was
built first in the process. Declaration order survives today only because all
five of these variables agree with each other. Declaring a sixth in a different
order would silently alias to the existing one. So the five have to move
together, and any test must read the type off the registered step rather than
rebuilding the annotation, or it compares a type against itself and reports
success.

That means the original "`_tp_cache` destroys order" warning was closer to
correct than my correction of it allowed. It just does not bite at present.

**The general lesson, now that this entry has been wrong three times.** Each
version was wrong in the same shape: a true fact carried one step further than
it was checked. The first carried a real typing behaviour into "so a fix cannot
work". The second carried a correct AST count into "so the hazard is absent".
The third is only trustworthy because someone ran the three-line probe above
instead of reasoning about it. When the next claim about this file starts with
"X is true of Python, therefore this codebase ...", run the therefore.

Best next candidate: **696**, investigated, with the exact files and call sites
recorded below. Note `KLayout.LVS` **already exists** at
`librelane/steps/klayout/lvs.py:33`; it is registered but appears in no flow and
no job provider, and its `run` only does real work for `ihp-sg13g2` /
`ihp-sg13cmos5l`. The metric collision is real and confirmed: `Netgen.LVS`
writes `design__lvs_error__count` at `librelane/steps/netgen.py:97` and
`KLayout.LVS` writes the same key at `librelane/steps/klayout/lvs.py:137`, while
`librelane/jobs/taxonomy.py:302` contracts that key for the `lvs` job. State
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
environment and the project supports 3.13+, so the explicit copy is
load-bearing. Beware: `Thread` itself owns the attribute name `_context` on
3.14, so the copy is stored as `_log_context`. Both facts were re-checked on
3.14 when it joined the tested matrix and both still hold.

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

### E-review — re-triage of the skip list against this fork's latitude

The E list above was produced quickly and is systematically too conservative in
one direction. It applies upstream's standard for "a maintainer must decide"
without asking whether *this fork* has to wait for that maintainer. This fork
is not bound by what upstream would merge, and several E entries turn out to be
decisions the fork can simply take, decisions already taken in the issue thread,
or premises that are false.

Every one of the 43 numbers was read in full with `gh issue view`. Where an
issue makes a claim about the code, the code was checked; where it claims
something is impossible, it was tried. Four buckets follow. **Fourteen move to
"actionable".** The list is not padded, and what was judged from issue text
alone rather than from code is named at the end.

The existing E list above is unchanged and is not renumbered. This subsection
only reclassifies.

#### Bucket 4 — mis-scoped, the stated premise is false

- **918** (recursive step substitution). `Substitutions` **no longer exists in
  this fork**. Commit `883b67f` ("feat!: remove Substitutions and
  meta.substituting_steps", an ancestor of HEAD) deleted `Substitutions`,
  `Substitute` and `meta.substituting_steps`, 852 lines across 16 files.
  `grep -rn Substitut librelane/` returns nothing; `Changelog.md:506` records
  the removal and points at explicit `Stages` lists instead. There is nothing
  left to make recursive. The issue's stated dependency, #787, appears nowhere
  in the log or in this file either. What the reporter actually wants, typed
  step references an IDE can check rather than ID strings, should be re-stated
  against `Stages` and `TOOLS`, which are already typed.
- **993** (union conversion). Both premises fail. First, the blocker recorded
  for this issue, that `Union[X, Y]` and `Union[Y, X]` hash equal so declaration
  order is not recoverable, is disproved by the code itself. `legacy.py:792`
  iterates `get_args(validating_type)`, which preserves declaration order, and
  the two orderings demonstrably produce different results. With
  `permissive_typing`, `Union[int, bool, str]` maps `'true'`, `'1'`, `'0'` to
  `True`, `1`, `0`, while `Union[bool, int, str]` maps the same three inputs to
  `True`, `True`, `False`. Order is not merely recoverable, it is already the
  whole resolution rule. Second, the issue's own example is wrong. It claims
  `"true"` is "coerced into 1 because it checks if it's convertible into an int
  first"; `int("true")` raises, so `bool` wins and the answer is `True`, which
  is what the reporter wanted. The real defect is the converse case the issue
  mentions second. So the fix is not to recover order but to stop resolving by
  order, in the 24-line loop at `legacy.py:789-812`. That is a policy the fork
  can pick, which also puts 993 in bucket 2.
- **543** (inject custom Verilog). The stated blocker was donn's "this would be
  a breaking change and can arrive in OpenLane 3 at the minimum". This fork is
  at 3.0.5 (`pyproject.toml:3`) and has shipped `feat!` removals in this cycle
  already (`883b67f`, `2928a42`). The blocker has expired. The design is
  otherwise unobstructed, `DesignFormat` is an open registry rather than an
  `enum` (`state/design_format.py:26-91`, members registered by module-level
  calls at `:144-266`), so adding an RTL source format needs no core change.
- **506** (auto macro placement). The one-line fix proposed in the thread,
  re-pointing `BasicMacroPlacement.get_script_path` at `basic_mp.tcl`, cannot be
  applied. The step was removed (`Changelog.md:1470`, "Removed non-functional
  step"), no `basic_mp.tcl` exists, and donn confirms upstream dropped the
  command. Nothing named `mpl`, `mpl2` or `rtl_macro_placer` exists in
  `librelane/`; the only registered `macro_placement` provider is
  `Odb.ManualMacroPlacement` (`librelane/jobs/providers.py`). The live work is
  porting upstream PR 537, which is a different thing from what the issue asks.
- **946** (relocatable tarball). The proposal's comparison table asserts the
  AppImage is "per-tool (one AppImage per binary)" and that "composition is on
  the user". donn disproved this in-thread; the AppImage is a full bundle with
  `--appimage-extract`. He also contests the core mechanism, since Nix store
  paths are baked into Qt resource files and the Yosys share directory, not just
  into ELF headers, so `patchelf` plus `ld.so` wrappers is not sufficient. The
  remainder is bucket 1.

#### Bucket 3 — already done, moot, or filed in the wrong section

- **537** and **669** are not issues. Both are **open upstream pull requests**
  mirrored into this tracker by `ohl-bot`; `gh issue view 537` reports
  `"state": "OPEN"`, `"title": "[PR] feat: openroad hierarchical macro placer"`,
  and 669 is the `pathlib_path` PR carrying the actual diff for 599. Neither is
  a product decision. They belong in section C, migrate from upstream.
- **975** is a ten-point synthesis review, not one issue, and point 9 has already
  landed here as `f31dd77` ("feat: run the arith_tree pass in Yosys (#975)").
  Its dual listing in C and E is right, but E's heading is wrong for most of the
  remaining nine points, which are individually actionable rather than blocked.
- **995** (ASAP7 support) is an umbrella tracker, not a decision. Its five
  sub-items already have distinct homes. Item 1 is open-pdks #533 and external;
  item 2 is 999, already in section D; item 3 is 998, below; item 4 is 997,
  **already fixed** on this branch as `5d865bb` in section A; item 5 is 996,
  below. Nothing about 995 itself is blocked.
- **599** and **600** confirmed as the D section already states. `common.Path`
  still exists at `common/types.py:39`, and the issue asks for "pathlib.Path
  **or a subclass of it**", so no subclassing is required either way. The
  earlier "blocked on 3.12" premise was false. `requires-python` has since
  moved to `>=3.13`, so subclassing is now available as well — an option, not
  a requirement. In flight.
- **808** (GUI) asks for a Logisim-Evolution-style schematic editor shipped as a
  single Windows executable. No decision is pending; this is section F, external
  or out of scope, not section E.
- **914** question 2 is answerable today from the code. `pkgutil.iter_modules()`
  over a `librelane_plugin_*` prefix (`plugins.py:17-21`) plus
  `docs/source/usage/writing_plugins.md` is the supported pattern, and the
  reporter guessed right. Questions 1 and 3 remain bucket 1.

#### Bucket 2 — actionable on this fork

| Issue | Size | What to do |
|---|---|---|
| 996 | S to document, M to fix | Make `LAYERS_RC` units unambiguous; see below |
| 641 | S | Stop rendering `None` as the default for `pdk=True` variables |
| 572 | S | Author retracted the hard part; only the doc change remains |
| 923 | M–L | One `sta` process over all corners; the capability is present |
| 488 | S | Setting both `VERILOG_FILES` and `VHDL_FILES` silently drops the VHDL |
| 480 | S | Name the report file in the `MetricChecker` message |
| 489 | S–M | Persist the `Explanation` a run already computes |
| 998 | S–M | Extend the tracks grammar; the decision was taken in the thread |
| 693 | M | `MANUAL_PIN_PLACEMENTS`, by analogy with `MANUAL_GLOBAL_PLACEMENTS` |
| 775 | XS | A furo `footer_icons` entry pointing at a prefilled `issues/new` |
| 543 | M | Blocker expired; see bucket 4 |
| 993 | — | Done; see the 993 subsection under D |
| 568 | M | Additive schema change, least certain of these calls |
| 842 (slice) | XS | Deduplicate three verbatim-duplicated variable declarations |

**996 is the strongest of these and is not the documentation problem it is filed
as.** There is a provable inconsistency. `set_rc.tcl:37-41` passes the user's
`LAYERS_RC` values to `set_layer_rc` verbatim, while `set_rc.tcl:76-77` scales
the tech-LEF fallback for the same command by `sta::unit_scale`. `set_cmd_units`
is called in exactly three files, all under `scripts/openroad/sta/`
(`corner.tcl:26`, `console.tcl:20`, `check_macro_instances.tcl:16`), and
`set_rc.tcl` is sourced from 16 places, 15 of which are PnR scripts that never
call it. So one and the same `LAYERS_RC` dict is read as kΩ/µm plus pF/µm under
signoff STA and as liberty-native units under PnR. That matches the reporter's
833x discrepancy exactly. Documenting it is small; `Variable` already supports a
`units=` kwarg (`legacy.py:476`) that `LAYERS_RC` does not use
(`steps/openroad/base.py:345-354`), and the unit statement is buried in prose at
the end of the description.

**Done, and the "needs a sky130 RC regression" caveat above turned out to be
avoidable.** The factor was measured against the pinned OpenROAD rather than
inferred: a `LAYERS_RC` resistance of 0.1 stores as 1e8 ohm/m under a `1kohm`
liberty and 1e5 under a `1ohm` one, so the true factor is exactly **1000**. The
reporter's 833 is that 1000 diluted by gf180's own values and its technology LEF
disagreeing by about 20%. Fixed by converting the user's values into the active
units, mirroring the fallback, with kΩ/µm the canonical unit because the signoff
scripts already pin it.

The other candidate fix, dropping the scaling from the fallback so neither path
scales, is wrong rather than merely different, and is now pinned by a test:
`est::dblayer_wire_rc` returns SI ohm/m, which is what odb holds, so feeding it
back unscaled would have it read as kΩ/µm and multiplied by 1e9.

**The one risk this left is smaller than it looked, and the check is worth
recording.** The fix is only correct if `LAYERS_RC` values in the wild are
authored in kΩ/µm; if they were in ohm/µm this would move the 1000x error into
signoff, which is worse than leaving it in PnR. Every PDK installed through ciel
was checked, and **none of them ships a non-empty `LAYERS_RC`**. sky130 does not
set it in any `config.tcl`. gf180mcu has it commented out, under a heading
calling it a "Temporary Override Because OpenROAD can't read techlefs properly".
ihp-sg13g2 sets it to an empty `dict create`. So the path this change alters is
not exercised by any shipped PDK today, and only the tech-LEF fallback runs,
which the fix leaves alone. The remaining exposure is out-of-tree PDKs and
hand-written configurations.

Found while checking 996 and worth its own line. `dump_rc.tcl` writes
`layer_values_after.rpt` from `est::dblayer_wire_rc`, which reads the odb
tech-layer objects. `set_layer_rc` does not write there. So that report is
identical to `tlef_values.rpt` apart from its heading and does not show what its
title, "Layer Values (After Set RC)", claims. Only `resizer_values_after.rpt`
reflects the overrides.

Confirmed by running the real `dump_rc.tcl` against stubs and finding the two
report bodies identical. `est::set_dblayer_wire_rc` is reached only when
`-corner` is absent, and `set_rc.tcl` passes `-corner` on every call. The report
is deleted rather than repaired, because there was nothing behind it to show.

Two more found beside it, neither fixed and neither anyone's slice yet.
`OpenROAD.LayoutSTA` returns `scripts/openroad/sta.tcl` from `finishing.py:67`,
and no such file exists anywhere in the tree; the step is registered and
exported but appears in no flow, so nothing reaches it. Deleting the step or
pointing it at `sta/corner.tcl` is a maintainer's choice. And issue 995 is
narrower than it looks where metrics are concerned: `write_metric_num` appears
outside `scripts/openroad/sta/` only in its own definition in `io.tcl`, so no
PnR script writes a time-valued metric in liberty-native units. The 995 exposure
is in report text, not in the metrics.

**641** is one line in each of two branches. `legacy.py:569` renders
`` `{var.default}` `` unconditionally, and PDK variables carry no Python default
(`config/flow.py:36-77`), so the docs print `None`, which is the reported bug.
Rendering "supplied by the PDK" for `var.pdk` removes the defect without
deciding donn's larger question about where PDK support files should live.

**572** was descoped by its own author. donn's 2025-09-30 comment retracts the
hard part, "the variables shouldn't be removed, but it should be made clear that
these only affect the default SDC file." The `file::` directive, the migration
tool and the Tcl subset parser are all off the table by that comment. What is
left is a description change on the clock variables.

**923** has a wrong version premise and a correct conclusion. The pinned OpenSTA
is **2.7.0**, not 3 (`nix/opensta.nix:20-22`, confirmed by running
`sta::version` in the pinned build), and `::sta::set_thread_count` **exists** in
it, verified by probing `info commands ::sta::*thread*`, which returns
`::sta::set_thread_count ::sta::thread_count`. It is namespaced rather than
exported globally, which is why a bare `set_thread_count` errors. Single-process
multi-corner is also already proven inside this repo by `read_pnr_libs`
(`scripts/openroad/common/io.tcl:319-357`), which calls `define_corners` and
then `read_liberty -corner` per corner. `MultiCornerSTA` instead runs one `sta`
subprocess per corner over a thread pool (`steps/openroad/sta.py:409-440`, and
`get_command` at `:119-120` passes no thread flag). The restructure is available
today. It should be benchmarked rather than assumed faster.

**488** is worse than "unsupported" today. `scripts/pyosys/synthesize.py:284-311`
is an `if`/`elif`/`elif` chain, so a config that sets both `VERILOG_FILES` and
`VHDL_FILES` silently synthesises only the Verilog and discards the VHDL with no
diagnostic at all. Making that combination an error is small and clearly
correct, independent of whether full mixed-language support is ever added.

**480** does not need to breach the architecture donn was protecting.
`Checker.YosysSynthChecks` raises `f"{metric_value} {self.metric_description}
found."` with no path (`steps/checker.py:113-141`), while the synthesis step
already logs `f"Yosys reported {len(counted)} problem(s) in '{report_path}':"`
(`steps/pyosys.py:108`) and a sibling checker in the same file already emits
`file:line` (`steps/checker.py:57-72`). Adding the report path to the checker
message is a per-checker constant, not a step reading another step's directory.
Overlaps D item 824. The general model, a producing-step field on every metric,
stays in bucket 1.

**489** wants a data structure that already exists and is simply never persisted.
`SequentialFlow.explain` builds `Explanation` and `StepDisposition` with
`will_run`, `reason` and a `mechanism` of gate, skip or window
(`flows/explanation.py:19-64`, `flows/sequential.py:286-369`), but `--explain`
short-circuits and never runs the flow, and the run loop emits only free-text
INFO lines (`flows/sequential.py:475-520`). Writing the post-run dispositions
into the run directory is purely additive. Caveat, this covers flow-level skips
only; the roughly 25 step-internal "Returning state unaltered" sites need a
separate signal.

**998** is not waiting on anyone. donn already decided in-thread, "for now
though I think we should just support this as an experimental variable to
unblock you", and benreynwar replied "I'm happy to extend the format rather than
add a tcl script". The remaining work is `old_to_new_tracks`
(`steps/openroad/base.py:219-241`), which accepts exactly four whitespace-
separated tokens per line, has no comment syntax, matches `X`/`Y` as exact
literals, and raises bare `ValueError`/`KeyError` with no file context. Honest
caveat, the ASAP7 track data is not in this repository, so the exact grammar
extension needs it.

**693** has a reference implementation and an in-repo precedent. Nothing accepts
per-pin coordinates today; `Odb.CustomIOPlacement` is ordering-only
(`scripts/odbpy/ioplace_parser/parse.py:32-37` has no x, y, layer or width per
pin), layer and width are global multipliers (`scripts/odbpy/io_place.py:195-221`)
and OpenROAD's per-pin `place_pin` is never invoked. But
`Odb.ManualGlobalPlacement` with `MANUAL_GLOBAL_PLACEMENTS: Optional[dict[str,
Instance]]` (`steps/odb/placement.py:204`) is exactly the shape wanted, in the
same file, and mole99 has a working fork implementation to port.

**775** is cheaper than the E list implies but not free. The theme is furo
(`docs/source/conf.py:108`), so `use_issues_button` and `repository_url`, which
are sphinx-book-theme options, do not apply. Furo's `footer_icons` is already in
use for the GitHub logo (`conf.py:116-127`) and takes arbitrary HTML, so a
second entry linking to a prefilled `issues/new` is about ten lines.

**568** is the least certain call in this bucket. Nothing anywhere passes `-min`
or `-max` to `read_liberty` (zero hits) and `Macro.lib` is
`dict[str, list[Path]]` (`config/legacy.py:236`). Making the value polymorphic
is a config-schema change with a migration cost, but it is additive, contained
to `Macro.lib`, `Toolbox.get_timing_files` and `io.tcl:232`/`:340`, and the
semantics the reporter wants, min for hold and max for setup, are standard.

**842** is bucket 1 overall, see below, but one slice is independent of the
debate. `PDN_MACRO_CONNECTIONS`, `PDN_CONNECT_MACROS_TO_GRID` and
`PDN_ENABLE_GLOBAL_CONNECTIONS` are declared twice, verbatim, at
`steps/openroad/base.py:382-398` and `steps/openroad/floorplan.py:200-212`.

#### Bucket 1 — genuinely blocked on a decision this fork cannot take unilaterally

- **45** (remote execution). The fork owner has to decide whether LibreLane
  grows a client/server split at all. A programme, not a decision point. 754 is
  downstream of it.
- **754** (unsafe variables). Confirms the existing E note, and adds that more
  is already plumbed than that note implies. `variable(unsafe=...)` exists and is
  written into `json_schema_extra` (`config/model.py:170,185,220`), but **no
  variable anywhere passes `unsafe=True`** and nothing reads the field. What is
  missing is the enforcement model, which is 45.
- **401** (warning severity). kareefardi argued in-thread that severity is too
  subjective, and donn deferred to a meeting that produced nothing. The fork
  owner has to decide whether warnings get a taxonomy at all. The substrate is
  thin, the only structured warning identifier in the tree is
  `logger.bind(step=self.id, key=alert.code)` at `steps/openroad/base.py:200`.
  One slice is not blocked though. Config diagnostics already carry a four-value
  severity (`config/diagnostics.py:10-14`) that `flows/flow.py:782-788`
  collapses, mapping both warning and deprecation onto `logger.warning`, so a
  deprecation is indistinguishable from a real warning in `warning.log`.
- **503** (fuzzing Yosys inputs). Ravenslofty and oharboe explicitly disagree in
  the thread about whether to embrace or fight the nondeterminism. Someone has
  to decide whether LibreLane ships a deliberately nondeterministic synthesis
  mode. Also gated on 613.
- **559** (DRiLLS). A two-line issue that is a research pointer. The decision is
  whether a reinforcement-learning ABC script generator is in scope.
- **561, 614, 625**. All three are studies, not code changes. They need designs,
  runs, and a sweep harness that does not exist. 625 is closest to actionable,
  since it names ORFS `correlateRC.py`, but its output is a suggestion and
  someone must decide what LibreLane does with one.
- **613** (migrate `run_designs`). Nothing exists; `sweep`, `run_designs` and
  `synth_explore` are all zero hits under `librelane/`, and every registered
  flow is strictly one config in, one run directory out
  (`flows/builtins.py:15-17`). The blocker is the shape, since a fan-out
  primitive touches the Flow API, the run-directory layout and the CLI at once.
  It is the keystone for 503, 561, 614 and 625.
- **642** (PDK onboarding tool). The decision is whether LibreLane ships
  PDK-authoring tooling at all, rather than open-pdks doing it.
- **659 / 804** (signoff regression). Blocked, and now precisely so. CI does run
  about 40 designs end to end and does extract and compare metrics
  (`.github/workflows/ci.yml:544-668`, `.github/scripts/compare_metrics.js`,
  `librelane/cli/metrics.py:121,281,322`). Two things are missing and both are
  policy. The baseline is `github.base_ref` in an external `METRICS_REPO` rather
  than a committed golden, and the comparison **never fails the build**, it only
  posts a PR comment. Someone must decide which signoff metrics may move, by how
  much, and what happens when they do.
- **697** (do not assume the PDK). Confirms the existing E note, with one
  correction of emphasis. It is three hard-coded `"sky130A"` sites
  (`config/flow.py:317`, `cli/run.py:418`, `cli/config.py:111`) and `Config.load`
  already raises a clean error when no PDK is supplied
  (`config/config.py:737,825`). But all three bundled examples omit `PDK` and
  `--smoke-test` relies on the default. So it is cheap to do and expensive to
  decide, and the decision is narrower than "tied to the PDK dictates flow
  defaults redesign" suggests. The owner has to accept breaking existing configs.
- **703** (CLI Driver). The premise is stale in a way that does not help. There
  is no click or cloup decorator any more; this fork is on Typer, with
  `make_app`/`make_group` (`cli/_app.py:64,78`) and 30 reusable option aliases
  (`cli/options.py`). But `_app` is private and `cli/__init__.py` states
  "Nothing under `librelane` outside this package may import from it." The gap is
  real and the decision is which surface becomes public API. Small once decided.
- **777** (check dependencies). donn's objection holds and the substrate
  confirms it. There is no `Tool` class and no version registry; `--smoke-test`
  runs the entire flow; `env_info.py` covers only host, Docker and Nix. Three
  tools carry `rev`/`rev-date` in-repo (`nix/opensta.nix:19-21`,
  `nix/openroad.nix:46-48`, `nix/openroad-abc.nix:10-12`) with `version =
  rev-date`, a date string rather than a semver, and every other tool's version
  lives in the `nix-eda` flake input. Version ranges would have to be
  double-represented. The decision is whether the project supports non-Nix
  installs enough to own a version matrix.
- **801** (hierarchical flows). The issue itself states the blocker, that flows
  within flows are contrary to the architecture. Whether a flow may nest is the
  decision.
- **842** (rework global connections). None of it has landed;
  `SCL_GLOBAL_CONNECTIONS` and `PAD_GLOBAL_CONNECTIONS` do not exist anywhere in
  the repo. The issue is mid-debate, since mole99 proposes deprecating
  `PDN_MACRO_CONNECTIONS` and then edits the same comment to note that wildcards
  are a reason to keep it. mole99 and donn have to settle whether macro PG
  connections move into the `MACRO` variable.
- **911** (rearchitect config). The existing E entry is accurate and
  well-evidenced; nothing to add except that mole99's follow-up, multiple SCLs
  for VT-swap optimization, is the live requirement and is itself a product
  decision.
- **914** questions 1 and 3. Whether to upstream a `librelane.steps.fusesoc`,
  and whether LibreLane adopts a convention for artifacts that persist across
  runs, are both product decisions. Question 2 is bucket 3.
- **946** remainder. Whether to own a fifth distribution channel, given that the
  Nix-store-path problem is unsolved, is a maintainer call.
- **951** (`STA_CORNERS` and IO libraries). Confirms the existing E note. One
  addition, jeras's follow-up narrows point 1 usefully; the "library already
  exists" warning fires for the second and third interconnect corner of the same
  liberty, which is consistent with mole99's ODB-persistence explanation and
  makes it cosmetic. Points 2 and 3 are corner-policy decisions.
- **480 / 624** general case. A producing-step field on every metric is a real
  architecture change. `MetricsUpdate` is a bare dict merged flat in
  `Step.__start` (`steps/step/core.py:673-677`), so a later step overwrites an
  earlier one with no record of either writer, and `aggregate_metrics` discards
  which modifiers contributed (`common/metrics/util.py:99-101`). The cheap slice
  is in bucket 2.

#### What was not verified against code

Judged from the issue text plus the absence of the relevant machinery, not from
reading a candidate implementation: **45, 503, 559, 561, 614, 625, 642, 808**.
For 561, 614 and 625 in particular, no attempt was made to size porting ORFS
`correlateRC.py`, so "blocked" there is a statement about the missing decision
and the missing sweep harness, not a claim that the port is large.

Not attempted at all: nothing. All 43 numbers were read in full.

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

1. **`Classic` could not complete a run.** The `pre_pnr_sta` job was
   contracted to produce an `sdc` that no OpenSTA script writes, so every run
   died at that job boundary with "completed without producing views
   ['sdc']". Reproduced on the bundled spm example with no local changes
   applied. Root cause was `MultiCornerSTA.outputs` declaring a view the class
   never writes, which `Job(pre_pnr_sta).provides` was then derived from and
   which `JobRegistry` accepted because it checks *declared* outputs. A
   step's declared outputs are not enforced anywhere else, so the lie had
   nowhere to surface until job contracts started reading it. The same
   pattern was in `PrimeTime.STAPrePNR` (`SDC`, copied from the comment),
   `OpenROAD.DumpRCValues` (five views, script writes only reports) and the
   three vendor `Floorplan` scaffolds (an `SDC` *input* nothing produces).
   Fixed at the root, with two tests for the general class of bug rather than
   for the instance.
## Facts worth not rediscovering

Found while implementing; none of them are written down anywhere else.

- **A job provider's config variables are namespace-checked at import time.**
  `librelane/jobs/registry.py` rejects a variable declared on a provider step
  that is neither a common flow variable nor prefixed with one of the provider's
  namespaces, raising `JobDefinitionError` when the module is imported. So an
  unprefixed name on, say, `KLayout.StreamOut` is not merely bad style, it fails
  to import:
  `Provider 'klayout' for job 'streamout' declares variable 'ISOSUB_LAYER',
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
  defeated. Where it would go here is also open: Classic is a job list,
  `Job.drc` is atomic so upstream's "between `KLayout.DRC` and
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

### How it actually went, now that all six branches are merged

The declaration count in `test/config/test_model_registry.py` started at 346
and finished at **367**, by base plus the sum of the deltas:

| Branch | Delta | Running |
|---|---|---|
| upstream migrations and nix-eda 7 | +2 | 348 |
| OpenROAD steps | +2 | 350 |
| synthesis and the section B audit | +7 | 357 |
| the pathlib migration | +5 | 362 |
| `KLayout.LVS` as a second provider | 0 | 362 |
| the upstream backlog | +5 | 367 |

Every one of those was confirmed by running the test on the merged tree, not
by trusting the arithmetic. They agreed every time.

**The failure mode is worse than described above, because it is silent.** Two
branches each raised the count from 346 and both wrote the literal `348`. Git
saw identical content on both sides, merged without a conflict, and one of the
two deltas simply vanished. The same thing happened again at the last merge,
where two branches had independently arrived at `362`. A conflict is the good
case here; no conflict is the dangerous one. So after any merge that touches a
counter, set the reconciled value deliberately and re-run the test, whether or
not git asked you to.

The lesson generalises past this file. A shared counter regenerated from a
partial world is a **replacement**, and two replacements that happen to agree
are indistinguishable from one. Anything regenerated rather than edited has
this property: the registry snapshot, the step-list goldens, the gating list.

## Test baseline

**Verify with plain `uv run pytest`.** `pyproject.toml:117` sets
`addopts = "--strict-markers -m 'not step_impl_test'"`, so the bare command is
already the canonical selection: everything except the step implementation
tests.

The canonical baseline on `librelane-unstable` is
**777 passed / 192 deselected / 1 xfailed**. With all six sweep branches merged
it is **929 passed / 1 deselected / 1 xfailed**.

Those two deselection counts look irreconcilable and are not. `test/steps/all`
is a git submodule. A populated checkout has it and deselects 192 step
implementation tests; a fresh worktree does not, and deselects one. So the
deselected figure tells you which kind of tree you are in, not whether anything
is wrong. Compare the passed count against a baseline measured in the same kind
of tree, or you will chase a difference that is only the submodule.

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

After the 599 swap itself: **824 passed / 1 deselected / 1 xfailed**. 823 + 2
new tests in `test/common/test_types.py` (the `isinstance` asymmetry and a
validated round trip) − 1, because
`test_filter_views_treats_any_path_like_as_one_view` lost its `common.Path`
parametrisation: that spelling and `pathlib.Path` are now the same thing.

The dummy PDK in `test/conftest.py` gained `KLAYOUT_TECH`,
`KLAYOUT_PROPERTIES` and `KLAYOUT_DEF_LAYER_MAP` (and the three files they
point at) in `f80dc33`. Without them no KLayout step could be constructed in a
test at all, which is worth knowing before starting **999**.
