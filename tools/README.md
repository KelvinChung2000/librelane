# Repository tools

Scripts that are part of this repository but not part of the `librelane`
package: `pyproject.toml` builds the wheel from `packages = ["librelane"]` and
lists the sdist's contents explicitly, so nothing here ships to users.

## `pdk_import.py`

Converts an installed PDK variant's Tcl configuration tree into the v1
descriptor tree specified in
`docs/superpowers/specs/2026-08-05-pdk-descriptor-format.md`:

```
libs.tech/{librelane,openlane}/config.tcl   ->  libs.tech/librelane/pdk.yaml
libs.tech/{librelane,openlane}/<scl>/…      ->  libs.tech/librelane/<scl>/scl.yaml
libs.tech/{librelane,openlane}/<pad>/…      ->  libs.tech/librelane/<pad>/pad.yaml
```

This is a **one-time bootstrap, not a supported runtime path.** LibreLane does
not read a `config.tcl` once descriptors exist, and it will never run this
converter for you. It exists to produce the descriptors that get committed —
into the open_pdks fork for the PDKs we ship, or into their own tree for a
`--manual-pdk` user's proprietary PDK, who runs it once and commits the output.

```console
$ python tools/pdk_import.py --pdk-root ~/.ciel --pdk sky130A --out /tmp/review
$ python tools/pdk_import.py --pdk-root ~/.ciel --pdk ihp-sg13g2
```

`--pdk-root` takes either the directory the variant sits directly inside (what
LibreLane calls `PDK_ROOT`) or the Ciel home above it. Without `--out` the
descriptors are written into the PDK tree, alongside the Tcl files rather than
over them; `--out` redirects the whole `libs.tech/librelane/` subtree elsewhere
for review.

Paths are written `pdk_dir::`-relative, never absolute. The converter emits no
variable interpolation at all, and refuses to write a string containing `${` —
interpolation is spelled `$VAR` and only inside a `ref::`, `refg::` or `expr::`
value, so a brace form could only be literal text the reader would reject.

Every conversion checks itself three ways and prints what it found: each
descriptor is read back through the loader, the layers are merged and compared
against the environment they were split from, and the merged descriptors are
resolved and compared against what the Tcl path evaluates to. Warnings are
reported but do not fail the run — the ones seen so far are defects in the PDK
being converted, which the Tcl path rejects just as loudly.

Converting in place leaves a PDK carrying both trees, which is what
`assert_paths_agree` in `test/config/test_pdk_parity.py` needs to hold the
output to the real gate: the descriptors must resolve to what the `config.tcl`
does.

Converting every standard cell library needs a PDK install that actually has
them all. A Ciel install fetched with the default `include_libraries` has the
data for one or two, and the rest are skipped with the glob error that says so.
