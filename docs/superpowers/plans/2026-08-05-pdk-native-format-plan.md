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
| W2 | Converter `tools/pdk_import.py` (config.tcl tree → descriptor tree) | W0 | agent running |
| W3 | ciel fork: `nangate45`, `asap7`, `gt2n` families with trivial builds (pattern: `ciel/build/ihp-sg13g2.py`) | — | agent running |
| W4 | open_pdks fork survey: additive injection recipe for descriptor install rules; auto-bump viability data | — | **done** — see "W4 findings" below |
| W5 | Convert sky130A/gf180mcuD/ihp-sg13g2 with W2, verify identical via W1 harness, commit descriptors into open-pdks fork per W4 recipe | W1, W2, W4 | pending |
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
  correct after 0.25x downscale.
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
