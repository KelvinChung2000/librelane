# Native PDK format: execution plan

Format spec: `docs/superpowers/specs/2026-08-05-pdk-descriptor-format.md`
(final for v1 — all workstreams build against it).

Strategy recap (decided in design discussion):

- One source format (our descriptor), one distribution path (ciel).
- Fork open_pdks **additively only** — descriptors are new files next to
  upstream's, so unattended auto-bump of manufacturable PDKs stays viable;
  extensions (non-real PDKs) live as vendored ciel families instead.
- No runtime importer. The converter is a repo tool (`tools/`, unpackaged);
  `--manual-pdk` users run it once and commit the output.
- Local clones: ciel at `/Users/kelvin/Documents/ciel`, open_pdks at
  `/Users/kelvin/Documents/open-pdks`.

## Workstreams

| # | Work | Depends on | Status |
|---|---|---|---|
| W0 | Descriptor format spec | — | **done** |
| W1 | Descriptor loader in `Config.__get_pdk_raw` (YAML-first, Tcl fallback, strict typing, origins from layering) + Tcl-vs-YAML diff harness | W0 | **done** — `librelane/config/descriptor.py`, parity harness `test/config/test_pdk_parity.py` (self-armed via synthetic dual-tree PDK; real PDKs skip until W5). Spec erratum fixed: interpolation is `$VAR` inside `ref::`/`refg::`/`expr::` only; `${` is rejected |
| W2 | Converter `tools/pdk_import.py` (config.tcl tree → descriptor tree) | W0 | **done** — parity gate passes for sky130A, gf180mcuD, ihp-sg13g2 (after the `pdk_compat.py` `Decimal("0.15")` fix). See "W5 notes" |
| W3 | ciel fork: `nangate45`, `asap7`, `gt2n` families with trivial builds (pattern: `ciel/build/ihp-sg13g2.py`) | — | **done** — branch `native-families` (7 commits, `1166265..9a7556b`), all three families built/installed/enabled end-to-end; sparse+blobless clones keep asap7 at 241 MB. See "W6 notes" |
| W4 | open_pdks fork survey: additive injection recipe for descriptor install rules; auto-bump viability data | — | **done** — see "W4 findings" below |
| W5 | Convert sky130A/gf180mcuD/ihp-sg13g2 with W2, verify identical via W1 harness, commit descriptors into open-pdks fork per W4 recipe | W1, W2, W4 | **done** — descriptors installed in all three local trees, parity 5/5 no skips; open-pdks branch `librelane-descriptors` (4 commits on `026824c`) carries TECHNAME-neutral sources, the `descriptors-%` make rules, the two EOF includes, and `.librelane-fork/` lint+additive-check tooling (additive check green: 1759 added, 0 deleted). Deviations recorded by the agent: `libs.tech/librelane` paths (upstream already renamed), corrected excluded-cell filenames (fixes both "broken upstream" SCLs — upstream had renamed the files, the ciel tree predates it), `#ifdef RERAM` around sky130's RCX rulesets (B ships no calibre rules), `test -f` loops, STAGING_PATH guard. **Follow-up: coverage is partial** — 2/8 sky130 SCLs, 2/6 gf180mcu, no pad.yaml; the rest need a converter run inside a real open_pdks build |
| W6 | NanGate45, ASAP7 (4x scale: `meta.dbu_per_micron`/`gds_scale`), gt2n as **native ciel families** with hand-written descriptors, plus librelane-side support: family entries in `pdk_hashes.yaml`, `cli/runtime.py` fetch path, docs. No capabilities machinery (decision 2026-08-05): `meta.capabilities` stays informational; users gate DRC/LVS/signoff steps off in their own flow specs — ship a documented example flow spec per family instead | W1, W3 | pending |
| W7 | Delete the Tcl path: `_eval_env`, `CoercionSyntax.TCL`, `permissive_typing` threading (11 recursive sites in `variable.py`), `pdk_compat.py`, PDK `deprecated_names`, `_migrate_diode_strategy`. Converter keeps private copies of the migration tables it still needs | W5 | pending |
| W8 | Distribution: fork `ciel-releases` (GitHub Pages), make `librelane/cli/runtime.py` honour `CIEL_DATA_SOURCE` (today hardcoded), drop `--volare-pdk` alias, auto-bump bot with additive-only CI check | W3, W5 | pending |

## Verification gates

- **W5 gate**: for each of the three shipped PDKs, resolved config via
  descriptor path == resolved config via Tcl path (modulo origin labels).
  Same standard as the legacy-removal work (byte-identical resolved PDK
  config against base `8df2c66`).
- **W6 gate**: a smoke design hardens on NanGate45 and gt2n using the
  documented example flow spec (magic/netgen signoff steps gated off by the
  user-side flow, not by librelane); ASAP7 GDS streamout is dimensionally
  correct — **no downscale**: only 1x cell GDS ships, 1x views are used
  throughout (as current ORFS does), and the streamed GDS decodes correct.
- **W7 gate**: full test suite green; `grep -r "permissive_typing\|_eval_env"
  librelane/` empty; wheel does not contain `tools/`.

## Vendored-PDK sources (W3/W6)

| Family | Source | Notes |
|---|---|---|
| nangate45 | `The-OpenROAD-Project/OpenROAD-flow-scripts` `flow/platforms/nangate45` | frozen; license fine |
| asap7 | `The-OpenROAD-Project/asap7` | 4x-drawn LEF at 4000 DBU; GDS downscale 0.25x post-P&R; no magic/netgen |
| gt2n | `siliconcompiler/lambdapdk` `lambdapdk/gt2n` + its stdcell lib | 2nm GAAFET + BSPDN, ISCAS 2026; OpenROAD/KLayout only — exercises `meta.capabilities`; cite paper in docs |

Licensing of vendored families: accepted as workable, deferred (user
decision 2026-08-04).

## W6 status (2026-08-05)

- **gt2n: DONE.** SPM green through KLayout streamout at a 0.5 ns clock:
  setup +0.148 ns / hold +0.032 ns, TNS 0, 0 antenna, 0 power-grid
  violations, GDS 438 KB. Ten SCLs (w13/w31 nanosheet widths × five VTs),
  single tt corner. Frontside-mesh PDN override in the example (upstream
  DRT crashes on backside geometry); `ERROR_ON_TR_DRC: false` waives the
  rect-only self-reports (56 here; GT2N's own AES runs show 97/16), with
  the justification written into the example.
- **asap7: DONE.** SPM green through KLayout streamout: setup/hold/slew/cap
  all zero at three corners, 0 route DRCs, 0 antenna, fmax 3.4 GHz TT at a
  0.65 ns clock. SCL `asap7sc7p5t_28_rvt` (each VT flavour is its own SCL —
  separate LEF/GDS). 1x views, `gds_scale: 1`, no downscale. Liberty: .7z
  unpacked and five cell-group files merged to one per corner (guarded
  merge, raises on template conflict) — LibreLane has no compressed-liberty
  support. ORFS DONT_USE verbatim + tap-with-filler. KLayout-only streamout.
  Future: no IO cells at the pin (newer main has them), NLDM only, no
  antenna diode cell (repair no-ops).
- **nangate45: DONE.** Hand-written descriptors (six files incl. tracks.info
  and exclude lists, no magic/netgen), KLayout DRC wired
  (`freepdk45_drc.drc`), SPM green with no workarounds: 0 DRC / 0 antenna,
  setup +3.601 ns, fmax 715 MHz. Descriptors ship via
  `ciel/build/descriptors/nangate45/` merged in at build time (`93f8bda`).
  `DIODE_CELL` deliberately omitted: ANTENNA_X1's LEF says
  `ANTENNADIFFAREA 0.0  # unknown` and OpenROAD rejects it (GRT-0244).
- **Converter caveat found**: `pdk_dir::` is glob-expanding (`refg::`) and
  resolves to a one-element *list* — illegal for string-typed variables
  (e.g. inside `KLAYOUT_DRC_OPTIONS`). Hand-written descriptors use
  `ref::$PDKPATH/...` there; `tools/pdk_import.py` should pick the prefix by
  the variable's declared type (latent — no shipped conversion hits it).
- **SDC unit assumption found**: `base.sdc`'s impl path divides
  `OUTPUT_CAP_LOAD` by 1000 assuming a pF liberty; an fF liberty (confirmed:
  nangate45 and asap7 both declare fF) makes the PnR-time output load 1000x
  small while signoff STA stays correct — signoff pins pF via
  `sta/corner.tcl`, PnR never calls `set_cmd_units` so it inherits the
  liberty's unit. **Proper fix identified**: PnR scripts should
  `set_cmd_units` the way `corner.tcl` does, which would also make
  `LAYERS_RC`'s conversion factors unconditional. Descriptors carry the
  honest fF value (correct at signoff; benign under-buffering on SPM).
  **RESOLVED (12901b5)**: `common/io.tcl` now pins the same
  `set_cmd_units` block signoff always pinned — configuration values are
  read in their documented units (ns/pF) in every session on every PDK.
  No-op for sky130/gf180mcu/ihp (their liberties already declare ns/pF,
  verified); a 1000x correctness fix for ps/fF PDKs, where signoff STA was
  reading `CLOCK_PERIOD` 1000x relaxed. asap7/gt2n descriptor and example
  values are ns-denominated as the variables document.
- **asap7 scaling RESOLVED by artifact**: the streamed GDS decodes to
  0.25 nm/dbu (4000/µm) with dimensionally correct 1x geometry at a DEF
  written at 1000 dbu/µm — `meta.dbu_per_micron` is the LEF/DEF database
  unit, the GDS grid is the cell-GDS drawing grid, and they legitimately
  differ. `meta.gds_scale` stays 1; the feared 0.25x post-P&R downscale is
  not needed at all. Distinction documented in the descriptor.
- **Resizer slack margins are absolute ns** (`PL_RESIZER_HOLD_SLACK_MARGIN`
  0.1, setup 0.05): ~1%/0.5% of a sky130 clock but 15%/8% of asap7's
  0.65 ns — post-CTS hold repair chased 100 ps of overfix and died on
  RSZ-0060. Masked before the unit fix (margins read as 0.1 *ps* ≈ zero).
  asap7/gt2n examples carry rescaled values. **Follow-up decision**: make
  the margins `None`-default and compute a percent-of-clock at runtime,
  the `MAX_TRANSITION_CONSTRAINT` pattern — not changed now because it
  would alter behavior for already-verified PDKs mid-milestone. Applies to
  `GRT_RESIZER_*` too.
- **Yosys liberty-cache race (found via asap7, fixed 4c747cd)**: yosys's
  merged-liberty SCL cache (`passes/techmap/liberty_cache.h`) uses a 32-bit
  path hash, second-granularity mtime freshness, and a shared non-unique
  `.tmp` staging file — concurrent conversions can publish a merge silently
  missing an input library; ABC then segfaults with no buffer/inverter.
  librelane now confines the cache per-step via TMPDIR. asap7 additionally
  ships one merged liberty per corner (the shape every other PDK has).
  Worth an upstream yosys issue (mkstemp + content hashing).
- **gt2n BSPDN limit (upstream OpenROAD)**: detailed_route segfaults in
  `drt::FlexTAWorker::initFixedObjs` if *any* backside geometry exists
  (bisected: BPR rails, BM mesh, BV vias each individually crash it; GT2N's
  own authors stub pdngen and materialize the backside grid post-GDS with
  KLayout). gt2n's example therefore overrides the PDK PDN with a frontside
  M10/M11 mesh. Not a descriptor bug; revisit when upstream DRT learns
  backside layers.

## W6 notes (from W3 family builds, 2026-08-05)

Pinned upstreams: nangate45 = ORFS `f4b9d7d`; asap7 superproject `d24f8b8`
(sc6t `390b499`, sc7p5t `f970bd3`, pdk_r1p7 `58d72c9`, sram `522eecc`);
gt2n = lambdapdk `1aac92f` → GT2N data repo `54f81fe`.

- **gt2n's PDK data lives in a third repo** (`azadnaeemi/GT2N`); lambdapdk
  holds only tool setup (klayout, pdngen/tapcell tcl), installed under
  `gt2n/lambdapdk/`. Descriptors address both.
- **gt2n has exactly one corner** (`tt`, `_tt_0p7v25c` liberty). `STA_CORNERS`
  and `LIB` get a single entry; more corners are "under development" upstream.
- **asap7 ships 1x AND pre-scaled LEF** (`LEF/*_1x_*.lef` vs `LEF/scaled/`).
  The descriptor's choice decides whether `meta.dbu_per_micron`/`gds_scale`
  are needed. NLDM liberty only (no CCS/QRC in the build — saves 6.4 GiB);
  **no IO cells at the pinned sc7p5t commit** (exist on newer main — bump if
  wanted).
- **nangate45's fakeram45 is 22 independent LEF/lib macro pairs** — descriptor
  enumerates or globs; no aggregate file.
- **Descriptor delivery path**: the builds create `libs.tech/librelane/` with
  a README placeholder (empty dirs don't survive ciel's tarballing; fetch uses
  `libs.tech` to detect installs). W6 must decide where descriptor sources
  live in the ciel fork and have the build modules copy them in.
- `Family.monolithic` (new) marks all three: one tree, no per-library
  tarballs; `--include-libraries` is inert for them.
- ciel's CI `ls-remote` test will fail for the new families until W8 lands
  the forked ciel-releases manifest — known, deliberate.

## W5 notes (from W2 conversion, 2026-08-05)

- **Ownership rule** (accepted): sky130's `config.tcl` `source`s the SCL's
  file itself and interpolates the library name into paths, so the Tcl path
  attributes library-derived keys (`CELL_LEFS`, `LIB`, `TECH_LEFS`, …) to
  `<pdk>`; descriptors put them in the library's own file. The parity harness
  reports but does not fail on these origin moves — deliberate.
- **Convert inside the open_pdks build, not from a partial ciel install**: a
  ciel install only carries fetched libraries (5 of sky130A's 7 SCLs were
  absent locally), and a conversion there would ship a truncated but
  self-consistent `meta.scls`.
- **Two SCLs are broken upstream and convert broken** (same failure on the
  Tcl path today): `sky130_fd_sc_hvl` references `no_synth.cells` /
  `drc_exclude.cells` its directory does not contain; `gf180mcu_fd_sc_mcu9t5v0`
  is missing `drc_exclude.cells`. Decide: fix in the open_pdks fork (good
  upstream PR candidates) or ship failing values.
- **gf180mcu's `DIODE_INSERTION_STRATEGY 4` is inert**: it expands to three
  variables none of which is `pdk=True`, so they never reach the config.
  Relevant when W7 deletes `_migrate_diode_strategy`.
- **`RT_CLOCK_MIN_LAYER` (sky130A sets `met3`) and `CTS_MAX_CAP` are silently
  dropped** because they are real variables not marked `pdk=True`. Decide
  whether that is intended; one-word fixes if not.
- **Expanded globs are the bulk of the diff**: sky130_fd_sc_hd's `scl.yaml`
  is ~923 `pdk_dir::` lines (`CELL_MAGS`/`CELL_MAGLEFS`); W8's auto-bump will
  see it churn whenever a library gains a cell (regenerable data, expected).
- `IGNORE_DISCONNECTED_MODULES: [sky130_fd_sc_hd__conb_1]` is duplicated into
  every sky130 `scl.yaml` by the ownership rule — faithful to today's values,
  visibly odd in `sky130_fd_sc_hvl`.
- `meta.dbu_per_micron` is not auto-populated (source `DEF_UNITS_PER_MICRON`
  exists) — W6 decision.

## W4 findings: open_pdks additive injection (surveyed 2026-08-05)

**Verdict: GO for unattended auto-bump.** Full detail in the survey report;
essentials:

- Upstream **already renamed `openlane` → `librelane`** (commit `24f6a02`,
  2026-02-08): sources live in `sky130/librelane/` and `gf180mcu/librelane/`,
  installed to `libs.tech/librelane/`. No `libs.tech/openlane` remains — the
  loader's `openlane` fallback paths only matter for old ciel-installed trees.
- Descriptor sources are pure new files in directories upstream only adds to.
  All build logic goes in fork-only `sky130/librelane-descriptors.mk` and
  `gf180mcu/librelane-descriptors.mk` (`descriptors-%: librelane-%` + hook
  lines `tools-A: descriptors-A` …; gf180mcu has variants A–D).
- **Total upstream-file edit surface: one `include librelane-descriptors.mk`
  line appended at EOF of `sky130/Makefile.in` and `gf180mcu/Makefile.in`.**
  Both EOF regions untouched upstream since 2022/2023. No `configure.ac`,
  `tools.txt`, top-level Makefile, or `staging_install.py` edits —
  `configure` auto-discovers `Makefile.in` files at run time, and
  `staging_install.py` copytrees the whole staging tree.
- Keep the fork's diff as **one commit** on top of upstream; auto-bump =
  `git rebase upstream/master` + additive-only CI check:
  `git diff --numstat upstream/master...HEAD -- . ':!sky130/librelane'
  ':!gf180mcu/librelane' ':!*librelane-descriptors.mk'` must show exactly
  `1 0 sky130/Makefile.in` and `1 0 gf180mcu/Makefile.in`.

Hazards to encode (CI assertions / lint, not blockers):
1. **Ordering**: `descriptors-%` must depend on `librelane-%` — the upstream
   rules `rm -rf` staging SCL dirs (gf180mcu) / custom_cells (sky130) and
   would wipe descriptors under `make -j`.
2. **`preproc.py` token substitution**: descriptor *sources* in the fork pass
   through open_pdks' CPP; bare tokens `TECHNAME MIM RERAM METAL5 METALS3/4/5
   THICKMET* HRPOLY1K REDISTRIBUTION REVISION STAGING_PATH` get substituted,
   and `###`-prefixed lines are dropped. Lint descriptor sources against this
   reserved-word list. (`TECHNAME` substitution is *useful* — it is how one
   source serves sky130A/B and gf180mcuA–D.)
3. **SCL drift**: `-quiet` CPP silently skips missing inputs — CI must assert
   descriptor count matches SCL dir count in the built tree.
4. **Avalon gap**: gf180mcu's `gf180mcu_as_sc_mcu7t3v3` is copied wholesale
   from the Avalon vendor repo during `vendor-%`, not `librelane-%` — no
   injection point in open_pdks. Decide in W5: skip it, post-`vendor-%` rule,
   or upstream PR to Avalon.
5. ihp-sg13g2 is **not in open_pdks** — its descriptors go via the
   IHP-Open-PDK path / ciel ihp build, not this recipe.
