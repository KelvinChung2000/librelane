# PDK Descriptor Format (v1)

Status: **final for v1** — implementation may refine details, but the decisions
below are settled and any deviation must be recorded here.

## Motivation

The PDK layer is the last place the configuration system executes a Tcl program
(`TclUtils._eval_env` in `librelane/config/config.py`) and the only reason
`permissive_typing` and `CoercionSyntax.TCL` exist. Every PDK we support will
ship through our own ciel manifest (fork of `fossi-foundation/ciel-releases`,
built from our open_pdks fork), so we control the artifact — the PDK can ship a
*typed, declarative* descriptor instead of a program, and the Tcl-reading path
leaves the package.

## File layout

Inside an installed PDK variant (e.g. `$PDK_ROOT/sky130A/`):

```
libs.tech/librelane/pdk.yaml           # PDK layer
libs.tech/librelane/<scl>/scl.yaml     # one per standard-cell library
libs.tech/librelane/<pad>/pad.yaml     # one per IO pad library (optional)
```

This mirrors the existing `config.tcl` layout one-to-one, which keeps the
open_pdks fork additive: descriptors are *new files next to* the Tcl sources,
never edits to them.

## Document structure

A descriptor is a YAML 1.2 document read with `LibreLaneYAMLLoader`
(`librelane/config/loading/sources.py` — floats parse as `Decimal`).

Two kinds of top-level keys:

- **`meta`** (lowercase, reserved): descriptor metadata. Any future lowercase
  key is reserved for the format; UPPERCASE is forever the variable namespace.
- **UPPERCASE keys**: configuration variables, exactly the names declared by
  the variable models (`PdkConfig`/`SclConfig` in `librelane/config/flow.py`,
  `PadConfig`, plus any step-declared `pdk=True` variables). *Current* names
  only — `deprecated_names` never appear in a descriptor.

### `meta` (in `pdk.yaml`)

```yaml
meta:
  format: 1                  # required; loader rejects versions it doesn't know
  family: sky130             # ciel family name
  variant: sky130A
  scls: [sky130_fd_sc_hd, sky130_fd_sc_hs, ...]   # available SCLs; each must
                                                  # have <scl>/scl.yaml
  pads: [sky130_fd_io]       # available pad libraries, may be omitted
  dbu_per_micron: 1000       # reserved for ASAP7's 4x-scaled views
  gds_scale: 1               # reserved; 0.25 for ASAP7 post-streamout downscale
  capabilities: [magic-drc, klayout-drc, netgen-lvs, rcx]
                             # informational only (decision 2026-08-05):
                             # librelane does NOT act on it. A PDK lacking a
                             # signoff tool (ASAP7/NanGate45/gt2n have no
                             # magic/netgen) documents that here; users gate
                             # the corresponding steps off in their own flow
                             # spec. No RUN_*-gating machinery will be built.
```

`scl.yaml`/`pad.yaml` need only `meta: {format: 1}`.

The **default SCL** is the `STD_CELL_LIBRARY` variable in `pdk.yaml` (it is
already a required `pdk=True` variable) — not a meta key. Likewise the default
pad library is `PAD_CELL_LIBRARY` if the PDK has one.

### Values

Values are native YAML: lists are lists, dicts are dicts, numbers are numbers
(`Decimal`). **No Tcl word lists, ever** — a descriptor is a
`CoercionSyntax.TYPED` source and is validated with `permissive_typing=False`.

String values may use the existing preprocessor directives, which already cover
everything `config.tcl` does:

| Directive | Meaning |
|---|---|
| `pdk_dir::<path>` | `refg::$PDKPATH/<path>` — path inside the PDK variant |
| `ref::<path>` / `refg::<path>` | path reference (glob-expanded for `refg::`) |
| `expr::<expr>` | arithmetic on other variables |

Variable interpolation is spelled `$VAR` and exists **only inside**
`ref::`/`refg::`/`expr::` values — there is no bare-string interpolation and
no `${VAR}` brace form. A descriptor string containing `${` is rejected at
load time (it can only be a mistranscribed directive that would otherwise
pass through literally and silently).

`pdk_dir::` is glob-based and resolves to a **list** — use it only for
Path-typed (and list/dict-of-Path) variables. A path inside a string-typed
variable is written `ref::$PDKPATH/<path>`.

### Unit-fixed variables

Two variables have units fixed by the scripts that consume them, regardless
of what the PDK's liberty declares. Descriptor authors converting from a PDK
whose liberty uses fF must convert:

- `LAYERS_RC` resistance/capacitance values are **kΩ/µm and pF/µm**
  (`scripts/openroad/common/set_rc.tcl`). Unconverted fF/µm values make the
  resizer see every wire as 1000x too capacitive — the symptom is absurd
  buffer counts followed by detailed-placement failure, with no hint of the
  cause.
- `OUTPUT_CAP_LOAD` is declared in fF, but the implementation SDC divides it
  by 1000 assuming a pF liberty; on an fF liberty the PnR-time load is 1000x
  small while signoff STA (which pins pF) stays right. Known issue — needs a
  unit-aware fix.

Directives are legal inside list elements and dict values. Paths in a
descriptor should always be `pdk_dir::`-relative; absolute paths are a
conversion bug.

Example (`sg13g2_stdcell/scl.yaml` excerpt):

```yaml
meta: {format: 1}
CELL_LEFS: [pdk_dir::libs.ref/sg13g2_stdcell/lef/sg13g2_stdcell.lef]
LIB:
  "*tt*": [pdk_dir::libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib]
DECAP_CELLS: [sg13g2_decap_*]
CLOCK_UNCERTAINTY_CONSTRAINT: 0.25
```

## Loading semantics

Replaces the three `_eval_env` sites in `Config.__get_pdk_raw`:

1. Read `pdk.yaml`; take `STD_CELL_LIBRARY` (caller's `--scl` overrides), read
   `<scl>/scl.yaml`; if `PAD_CELL_LIBRARY` resolves, read `<pad>/pad.yaml`.
2. Merge the three mappings in order (later layer wins). **Origins fall out of
   the merge for free**: each key's origin is the file that last wrote it. The
   `_written_by` diffing, `migrate_old_config` attribution dance, and the
   `STD_CELL_LIBRARY_OPT` hack (issue #932) all exist only for the Tcl path.
3. Seed `PDK_ROOT`, `PDK`, `PDKPATH`, `STD_CELL_LIBRARY`, `PAD_CELL_LIBRARY`
   and run the existing preprocessor resolve step so directives expand — the
   merged result has the same shape (absolute paths, expanded globs) as the
   Tcl path's output.
4. Validate contract variables strictly (`permissive_typing=False`). Unknown
   UPPERCASE keys are preserved raw, exactly as today — they may belong to
   steps or flows not currently loaded.

`meta.format` unknown → hard error. `meta.scls` not matching the on-disk
`scl.yaml` set → hard error at load.

## Transition and removal

- While descriptors are being brought up, `__get_pdk_raw` prefers `pdk.yaml`
  and falls back to `config.tcl`. The bring-up gate is a diff harness proving
  the YAML path's resolved config is identical to the Tcl path's for
  sky130A, gf180mcuD, and ihp-sg13g2 (modulo origin labels).
- Once the three shipped PDKs are converted and verified, the Tcl path is
  deleted: `_eval_env`, `CoercionSyntax.TCL`, `permissive_typing` threading,
  `pdk_compat.py`, PDK `deprecated_names`, `_migrate_diode_strategy`.
  (`TclUtils.join/split/escape` stay — `steps/` writes Tcl to tools.)
- The one-time converter lives at `tools/pdk_import.py`, in the repo but
  **not in the wheel**. It is the bootstrap for the three shipped PDKs and the
  documented ramp for proprietary PDKs (`--manual-pdk` users run it once and
  commit the output).
