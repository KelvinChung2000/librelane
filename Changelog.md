<!--

Section Order
-------------

## CLI
## Steps
## Flows
## Tool Updates
## Testing
## Misc. Enhancements/Bugfixes
## API Breaks
## Documentation

Style Notes
------------

* Always list steps alphabetically.

* Always use the past tense for actions (created, added…)

* New steps are always "Created", new variables are always "Added".
  * Variables are "removed" or "deprecated." Always explain why, and for
    deprecated variables, mention the replacement.

-->

# 3.0.6

## Steps

* Created `OpenROAD.RTLMacroPlacer`: automatic macro placement using
  OpenROAD's hierarchical RTL macro placer (RTL-MP). Opt-in via the new
  `RUN_RTLMP` variable; runs in the `macro_placement` job after
  `Odb.ManualMacroPlacement`, placing only macros that were not fixed
  manually. Added `RTLMP_*` variables covering halos, clustering controls
  and cost-function weights.

* `Odb.InsertECOBuffers`, `Odb.InsertECODiodes`: instance targets are now
  split on the last `/`, so instances inside a preserved hierarchy
  (`SYNTH_HIERARCHY_MODE: keep`) can be targeted.

* Replaced the remaining string-keyed `self.config["X"]`/`self.config.get("X")`
  reads in steps with typed attribute access (`self.config.X`), which mypy
  checks against each step's declared `Config` model. `_generate_read_deps`
  (yosys) is now typed against `YosysStep.Config`, which gained the
  `VerilogRtlConfig` mix-in its body always read (no variable changes for any
  concrete step; `Yosys.EQY` already declared it).

* `Netgen.LVS`: removed a read of `SPICE_MODELS`, a variable no step, PDK, or
  flow declares — the lookup predates LibreLane 2 and could only ever return
  `None`. `CELL_SPICE_MODELS`/`EXTRA_SPICE_MODELS`/`PAD_SPICE_MODELS` remain
  the supported spellings.

## Flows

* Registrations may now declare `optional_metrics`: metrics a provider
  writes only when a precondition holds. They count as writes for join
  validation but are exempt from the completion-time contract check.
  `klayout__drc_error__count` is the first: `KLayout.DRC` skips itself on
  PDKs without a `KLAYOUT_DRC_RUNSET` (e.g. gf180mcu), which previously
  failed the flow with a job-contract error at `klayout_drc`.

## Testing

* Added CI design tests for the new features: `spm_hier_keep` (spm with
  `SYNTH_HIERARCHY_MODE: keep`) and `rtlmp_macro_placement`
  (`manual_macro_placement_test` with unplaced macros and `RUN_RTLMP`),
  both in the fastest test set.
* Added unit tests for `min_area_dbu2` (the µm²/DBU² `getArea`
  compatibility shim in `io_place.py`), `OpenROAD.RTLMacroPlacer`'s
  registration and opt-in skip, and `optional_metrics` (contract
  exemption and join-validation visibility).
* Fixed `test_power_utils`: the stubbed `odb` module now carries
  `dbRegion`, which `power_utils.py` references in an annotation.

## Tool Updates

* Updated OpenROAD to `2026-08-05` (`b9a38929`), OpenSTA to `2026-07-22`
  (`31e8fff`, OpenSTA 3) and OpenROAD's abc fork to `2026-06-15`
  (`d527cfa`).
  * Removed `grt_pin_layers.patch`: upstreamed.
  * Rebased the abc `zlib.patch` onto the new abc Makefile layout.
  * The OpenROAD source is now fetched with submodules for
    `third-party/slang-elab`, needed by OpenROAD's new integrated synthesis
    module (`sv_elaborate`/`synthesize`), which the shipped binary now
    includes.
  * `write_timing_model` uses the OpenSTA 3 scene syntax when available.
  * Added `python_metrics_flush.patch`, fixing an upstream regression where
    `-metrics` wrote nothing in `-python` mode: the flush is registered as a
    Tcl exit handler, which neither a normal `Py_RunMain()` return nor the
    `exit()` CPython performs on an uncaught `SystemExit` (how `sys.exit()`
    and every click-based odbpy script terminates) ever invoked. The patch
    registers `Tcl_Finalize` with `atexit`, covering both paths. This
    restores the metrics of every `Odb.*` step under the new binary.

# 3.0.5

## CLI

* Pointed `librelane run` at workflow documents. It now builds a `Workflow`
  over the document `Flow.factory.get` returns, rather than
  instantiating a flow class, so every flow-control option addresses the
  document's jobs.
* Added `librelane open <viewer>`, which loads a finished run into a tool.
  `klayout`, `magic` and `openroad` open a GUI; `openroad-console` and
  `opensta-console` open an interactive console. It replaces the five
  `OpenIn*` flows, which are deleted along with `--flow OpenInKLayout` and its
  four siblings.
  * Opening a run in a viewer was never a flow. It runs one step, produces no
    view and no metric, advances nothing, and waits for a human. As documents
    those five sat on the `--flow` list beside `Classic` and were given a run
    directory, a net, a join and a resume key that none of them used.
  * The run is named by `--run-tag` or `--last-run`, and there is no default:
    a viewer opened on nothing is a window a user closes before finding out
    they mistyped, so the command lists the runs that do exist instead.
  * The state opened is the last one that run wrote, the same file
    `librelane state latest` prints, unless `--with-initial-state` names
    another. This is what `--flow OpenInKLayout` was documented to do.
  * Only the viewer step's own configuration variables are resolved, plus the
    universal ones. Nothing else is going to run, so a design whose unrelated
    variable is malformed still opens.
* Added `librelane flow schema`, which writes a JSON Schema for the workflow
  document surface, for editors to complete and validate a document against
  while it is being written. `-o`/`--output` names a file; the standard output
  is the default.
  * Generated from the same models the loader validates against, so a key
    added to a document's job appears in it without a second file being
    edited, and it carries the key combinations no single field can state:
    that `select` needs `iterations`, that a job declares `until` or
    `select` but never both, that an `until` gate takes exactly one of
    `iterations` or `max`, and the term grammar behind `if` and `until`.
  * The `steps` and `uses` enumerations are the registries of the installation
    that generated it, plugins included, so the schema completes a plugin's
    step ids wherever that plugin is installed.
  * LibreLane itself never validates against it. Whether the graph holds
    together -- that a `needs` names a declared job, that a cycle is a ring
    with one gate -- is still the loader's answer to give.
* Removed `--from` and `--to`. A step window is not expressible over a graph.
  * Added `--target`/`-T`, which runs a job and everything it transitively
    needs and nothing else. The run's final state is the named job's own
    output, so `--target floorplan` returns exactly what floorplan produced.
    May be given more than once.
  * Added `--invalidate`/`-F`, which treats a job and every job downstream of
    it as having no reusable result. Use it when something a resume key cannot
    hash has changed, such as a CAD tool binary or an edited script. It is
    forwards only, so the jobs before it are still reused.
* `--skip` now names a job ID rather than a step ID. A skipped job passes its
  input on unchanged instead of running its steps, and every job after it runs
  as it otherwise would.
* `--reproducible` now accepts `<step ID>` or `<job>/<step ID>`. Step IDs are
  still matched case-insensitively and still accept `fnmatch` wildcards, and a
  near miss is still answered with a suggestion. The `<job>/` form is needed
  when a step ID runs in more than one job, as `Classic` runs the `streamout`
  stage under both `magic_streamout` and `klayout_streamout`.
* Added `--explain`, which prints one row per job the document declares, with
  a `NEEDS` column showing the graph, saying whether this configuration would
  run it and, if not, whether its own `if`, `--skip` or `--target` stopped
  it, then exits without running. Every job gets a row: a job stopped by its
  condition or by `--skip` still fires and passes its input state on, so its
  successors are unaffected, and the table says so rather than omitting it.
  It no longer requires a sequential flow.
* Added `--explain-variables`, which prints one row per configuration variable
  with its value, the layer that supplied it and the jobs that can read it,
  then exits without running. Reach is reported as "universal" for a variable
  every step can read, as the step class that declares it where one class
  explains the whole list, and as the job names otherwise. A variable two jobs
  set differently in their `with` blocks gets a row for each value. It selects
  a second table rather than adding rows to `--explain`'s, and every row is
  printed, including the variables sitting at their defaults.
* An unknown flow name now lists the registered flows, whether it came from
  `--flow` or from the configuration file's `meta.flow`.
* Fixed `librelane <config>` failing for every design with "DESIGN_DIR: Input
  should be an instance of Path". A path variable lost the schema
  `common.Path` carries when it crossed the model-to-`Variable` bridge, leaving
  a bare `pathlib.Path` that rejects the string a command-line path argument
  arrives as.
* Migrated the LibreLane, step, configuration, state, help, and metrics command
  interfaces from Cloup decorators to typed Typer applications.
* Consolidated every command-line frontend into a single `librelane.cli`
  package, one module per console script.
* Unified the separate console scripts into subcommands of `librelane`:
  `librelane run`, `librelane steps`, `librelane config`, `librelane state`,
  `librelane metrics`, `librelane help` and `librelane env-info`.
  * `run` is the default subcommand, so `librelane config.json` still means
    `librelane run config.json`. Reproducibles, the containerized re-entry and
    every documented invocation are unaffected.
  * `librelane.steps`, `librelane.config`, `librelane.state`, `librelane.help`
    and `librelane.env_info` continue to work as deprecated aliases that name
    their replacement on stderr. The equivalent `python3 -m` invocations stay
    silent, as `run_ol.sh` inside every generated reproducible calls
    `python3 -m librelane.steps`.
  * `librelane.config create-config` is now `librelane config create`. The
    deprecated alias translates the old command name.
* Added `python3 -m librelane.cli` as the entry point for the CLI package.
* Split `librelane.cli.flow_opts` into `librelane.cli.options`, which declares
  the shared options and imports nothing from LibreLane, and
  `librelane.cli.runtime`, which holds the behaviour behind them. A `--help` no
  longer pays for loading flows, steps or the PDK machinery.
* Removed the undocumented `.marshalled` configuration-file path. It read a
  parameter dictionary via `marshal.load`, which is unsafe on untrusted input,
  and the code that wrote those files was deleted in 2023 when containerization
  moved to re-executing `python3 -m librelane` with plain arguments.
* Fixed metrics table verbosity values not being compared as their declared
  enum type.
* Fixed standalone reproducible creation ignoring an explicitly supplied
  configuration and input-state pair.
* Made `--state-in` explicitly required for standalone step runs and ejection,
  matching the underlying step loader contract.
* Removed `--only`. It named a single step of a window that no longer exists;
  `--target` names a job and its dependencies instead.

## Steps

* Deleted the `Checker.*` step family, twenty-one steps in all, and gave every
  limit it enforced to the step that took the measurement it read. A step
  declares them as `gates`, a tuple of
  {class}`librelane.steps.MetricGate` or
  {class}`librelane.steps.CornerMetricGate`, and `Step.start` raises them once
  `run` has returned.
  * A checker put the failure in a directory with no evidence for it.
    `Checker.TrDRC` failed a run on `route__drc_errors`, so the error landed
    in `…/checker-trdrc`, which holds nothing else, while the report naming
    the violating shapes sat in `…/openroad-detailedrouting` -- a step the
    flow had already called successful. The gate raises from the step that has
    the report.
  * A gate reads only the metrics its own step just produced, not the
    inherited state. `MetricChecker.run` warned "the metric was not found. Are
    you sure the relevant step was run?" and passed, so a flow that lost the
    measuring step lost the check without failing. A gate has no such state:
    no measurement means nothing to compare, and the step that skipped the
    measurement is the one that logged why.
  * Every `ERROR_ON_*` variable keeps its name, default and deprecated names,
    and is now declared by the step that owns the gate. So do
    `WIRE_LENGTH_THRESHOLD` and the five `*_VIOLATION_CORNERS` variables.
  * `Checker.LintErrors`, `Checker.LintWarnings` and
    `Checker.LintTimingConstructs` became gates on `Verilator.Lint`;
    `Checker.YosysUnmappedCells` and `Checker.YosysSynthChecks` on the shared
    synthesis base of `Yosys.Synthesis`, `Yosys.Resynthesis` and
    `Yosys.VHDLSynthesis`; `Checker.TrDRC` on `OpenROAD.DetailedRouting`;
    `Checker.PowerGridViolations` on `OpenROAD.GeneratePDN`;
    `Checker.DisconnectedPins` on `Odb.ReportDisconnectedPins`;
    `Checker.WireLength` on `Odb.ReportWireLength`; `Checker.MagicDRC` on
    `Magic.DRC`; `Checker.IllegalOverlap` on `Magic.SpiceExtraction`;
    `Checker.KLayoutDRC` on `KLayout.DRC`; `Checker.XOR` on `KLayout.XOR`;
    `Checker.KLayoutDensity` and `Checker.KLayoutAntenna` on `KLayout.Density`
    and `KLayout.Antenna`; `Checker.LVS` on both `Netgen.LVS` and
    `KLayout.LVS`, each carrying its own; and `Checker.SetupViolations`,
    `Checker.HoldViolations`, `Checker.MaxSlewViolations` and
    `Checker.MaxCapViolations` on `OpenROAD.STAPostPNR`.
  * `Checker.NetlistAssignStatements` was never a metric check -- it scanned
    the netlist for `assign` statements -- so it folded into the synthesis
    step's `run`, against the netlist that step just wrote.
    `ERROR_ON_NL_ASSIGN_STATEMENTS` is unchanged, and the per-line
    `file:line` messages that make the check worth having are unchanged too.
  * The timing gates belong to `OpenROAD.STAPostPNR` alone. `MultiCornerSTA`
    measures the same four counts in `STAPrePNR` and in every `STAMidPNR`
    snapshot, where a violation is expected and the next repair step is the
    answer to it. Post-PnR is the last STA in the flow, so it is the one whose
    numbers are the design's.
  * Run directories no longer contain `checker-*` entries, and the jobs that
    held nothing else are gone: `classic.yaml`, `chip.yaml` and
    `vhdl_classic.yaml` lose steps from `post_gpl_checks`, `routing_reports`,
    `xor` and `final_checks`, and `final_checks` is now
    `Misc.ReportManufacturability` alone.
* Migrated all built-in step configuration declarations to nested typed
  `Config` models and static configuration reads to attribute access.
* Migrated dynamically composed and checker-generated step configuration to
  generated typed models.
* Annotated every step's `config` attribute with its own nested `Config` model,
  so attribute reads are checked rather than typed as the empty base model.
* Folded the `librelane.steps.openroad_alerts` module into
  `librelane.steps.openroad.base`, next to the steps that use it.
  `OpenROADAlert`, `OpenROADOutputProcessor` and `SupportsOpenROADAlerts` are
  still exported from `librelane.steps`, so the documented API is unchanged.
* Added `OpenROADAlertMixin`, which carries the alert output processor and the
  `on_alert` logging that `OpenROADStep` and `OdbpyStep` previously duplicated.
  Subclasses suppress known-harmless alerts by setting `ignored_alert_codes`.
* Added `librelane.jobs.providers_vendor`, which registers the sixteen
  commercial CAD tool scaffolds under `librelane/steps/` as job providers.
  Importing it is opt-in; nothing under `librelane.jobs` imports it, so
  `librelane help` and `JobRegistry.providers()` stay unaffected unless a
  caller imports the module themselves. Every provider it registers is a
  scaffold whose steps raise `NotImplementedError`, and no vendor command is
  guessed anywhere in them.

* `FC.Floorplan` and `ICC2.Floorplan`

  * Fixed both steps declaring `DEF` as an input. The `floorplan` job is
    where `DEF` is first produced, not carried in; its own contract requires
    only `NETLIST` and `SDC`, matching `OpenROAD.Floorplan`. The stale input
    surfaced only once these scaffolds were registered as job providers and
    checked against the job contract at import time.

* `Odb.RemovePDNObstructions`

  * Fixed the step reading `ROUTING_OBSTRUCTIONS`, inherited from
    `Odb.RemoveRoutingObstructions`, instead of `PDN_OBSTRUCTIONS`.

* Fixed `VIAS_R` matching the wrong corners. Its corner pattern was handed to
  `Filter` as a bare string rather than a one-element list, and `Filter`
  iterates what it is given, so the pattern became one filter per character.
  A key containing `*` anywhere, such as `nom_*`, therefore applied its via
  resistances to every corner, and a key naming a corner exactly applied to
  none. `LAYERS_RC`, filtered by the line above it, was always correct.

* Fixed `DRT_ANTENNA_REPAIR_MARGIN` having no effect. The post-detailed-routing
  antenna repair read `GRT_ANTENNA_REPAIR_MARGIN` instead, which
  `OpenROAD.DetailedRouting` also has in scope because its configuration
  includes the global routing group. Both default to 10, so this was invisible
  until someone set the DRT one. The jumper-only and diode-only flags beside it
  were already reading their `DRT_` variables.

* Fixed gzipped liberty files crashing `Toolbox.get_lib_voltage` and
  `Toolbox.create_blackbox_model_from_libs`, which reach
  `OpenROAD.IRDropReport` and the linter's macro blackbox generation. Both
  parsed the file directly, and `libparse` reads the file descriptor rather
  than the Python stream, so neither a `gzip` wrapper nor a string buffer can
  be handed to it. Added `Toolbox.decompress_liberty`, which writes an
  uncompressed copy to the run's temporary directory when the input is
  compressed and returns the input unchanged when it is not (#627, partial).

* Removed a stray `wtaf` that Yosys logged on every synthesis run not using the
  slang frontend.
* Removed the unused `_EXTRA_CORNER_TCL_FILE` environment variable. The
  `STA_EXTRA_CORNER_TCL_FILE` feature reaches Tcl under its own name and is
  unaffected.
* Deleted `OpenROAD.WriteViews`. It had no registration and was reachable
  from no flow, along with the `OPENROAD_LEF_BLOAT_OCCUPIED_LAYERS` variable
  it declared.

* `KLayout.Render`

  * `def` and `gds` are now both declared as optional inputs. The step renders
    whichever of the two it is given, preferring `gds`, so requiring `def`
    aborted flows that could have rendered from the `gds` alone. Ported from
    upstream by Leo Moser (librelane/librelane#964).
  * Given neither of its optional inputs, the step now warns and does nothing
    instead of raising. Declaring an input optional and then erring out on its
    absence contradicts the declaration. Ported from upstream by Mohamed Gaber
    (librelane/librelane#973).
  * `Toolbox.render_png` now reads the rendered image out of the step's output
    state instead of a fixed path inside its temporary directory, and returns
    `None` when the step rendered nothing. The fixed path would otherwise raise
    an uncaught `FileNotFoundError` on the case the two changes above make
    reachable.

* `KLayout.StreamOut`, `Magic.StreamOut`

  * A stream-out that is not the PDK's `PRIMARY_GDSII_STREAMOUT_TOOL` now
    writes the neutral `gds` view when nothing else has. A custom flow running
    only one of the two produced no `gds` at all if the PDK named the other as
    primary. The primary tool still always writes it, overwriting whatever a
    non-primary tool left, so a full flow is unchanged (#683).

* `OpenROAD.DiodeInsertion`

  * Registered the step. It was reachable only through
    `OpenROAD.RepairAntennas`, but wrote its own `config.json` naming this ID,
    so a reproducible made from its directory could not be loaded (#920).

* `OpenROAD.DumpRCValues`

  * Removed the `layer_values_after.rpt` report. It read the odb layer store a
    second time after sourcing `common/set_rc.tcl`, but `set_layer_rc` writes
    that store only when `-corner` is absent and `set_rc.tcl` always passes
    `-corner`, so the report was identical to `tlef_values.rpt` while its title
    claimed to show the values after set_rc. Anyone comparing the two while
    debugging RC estimation, which is exactly what the step is for, was being
    told the overrides had not been applied. `resizer_values_after.rpt` is the
    report that shows them, per corner, and is unchanged.

* Created `OpenROAD.RMP`, which resynthesizes clouds of logic in place using
  OpenROAD's `rmp` module and ABC (#558, ported from the unmerged upstream
  #560). Added `RMP_TARGET`, `RMP_CORNER`, `RMP_SLACK_THRESHOLD`,
  `RMP_DEPTH_THRESHOLD` and `RMP_REMOVE_BUFFERS`. The step raises rather than
  restructuring against part of the standard cell library when the selected
  corner resolves to more than one liberty file, because OpenROAD's
  `restructure` hands its single `-liberty_file` to one ABC `read_lib`.

* `OpenROAD.PadRing`

  * Added `PAD_ROTATION_HORIZONTAL`, `PAD_ROTATION_VERTICAL` and
    `PAD_ROTATION_CORNER`, the orientations `make_io_sites` applies to each kind
    of pad site, for PDKs whose pad cells are not drawn for the side they sit
    on. All three default to `R0`, which is what OpenROAD assumes when the flag
    is absent, so a PDK that says nothing gets the ring it already had. Ported
    from upstream by Leo Moser (librelane/librelane#925).
  * Fixed the "no instance found" error path reading `$instance_name`, a
    variable never set, so a padring naming an instance that does not exist
    died with a Tcl error about the error handler rather than naming the
    instance.
  * Added `PAD_SPACING_MULTIPLE`, the granularity the gap between two pad cells
    is rounded down to. Unset means the pad site width, which is the narrowest
    filler cell that can occupy the gap and is what the spacing was rounded to
    before. Upstream instead defaults it to 1 µm, which silently re-spaces the
    ring on any PDK whose pad site is not 1 µm wide. The space left at the ends
    of each side must still be divisible by the pad site width. Ported from
    upstream by Leo Moser (librelane/librelane#965).
  * Added `PAD_TRIM_ROWS`, which skips the I/O filler for whichever of
    `PAD_SOUTH`, `PAD_EAST`, `PAD_NORTH` and `PAD_WEST` is empty and deletes
    each corner cell whose two neighbouring rows are both empty, so a ring can
    populate fewer than four sides. Defaults to off. Ported from upstream by
    Leo Moser (librelane/librelane#965).

* `OpenROAD.GeneratePDN`, `OpenROAD.PadRing`

  * Added `PDN_CORE_RING_CONNECT_TO_PAD_LAYERS`, which restricts the core
    ring's connection to the pad pins to a named set of layers. Unset means
    every layer a pad pin appears on is eligible, which is the previous
    behaviour. Ported from upstream by Leo Moser (librelane/librelane#925).

* `OpenROAD.GlobalPlacement`, `OpenROAD.GlobalPlacementSkipIO`

  * Added `PL_GENERATE_GIF`, which captures the floorplan at every global
    placement iteration into the step's `renders` directory for OpenROAD to
    combine into a gif animation, and `PL_GENERATE_GIF_PAUSE`, the number of
    iterations to run before pausing for inspection. Both default to off and to
    a pause count high enough never to pause. OpenROAD renders these from its
    GUI, so enabling the first forces `-gui` into the OpenROAD command line and
    the run then requires a display. Ported from upstream by Julia Desmazes
    (librelane/librelane#985).

* `OpenROAD.GeneratePDN`

  * `PDN_CFG` is now a PDK variable, so a PDK can ship its own PDN script
    instead of expressing its grid through the `PDN_*` variables (#997).
  * Warns when `PDN_HORIZONTAL_HALO`/`PDN_VERTICAL_HALO` exceeds the
    corresponding `FP_MACRO_*_HALO`, which leaves standard cell rows in a band
    the macro power grid is suppressed in (#947).

* `OpenROAD.AddBuffer`

  * Created. Inserts the buffers on the design's input and output ports, and
    runs before global placement so that global placement knows about them and
    places the logic around them. `Classic` and `VHDLClassic` run it between
    I/O placement and global placement (#917).
  * `DESIGN_REPAIR_BUFFER_INPUT_PORTS` and `DESIGN_REPAIR_BUFFER_OUTPUT_PORTS`
    moved here from `OpenROAD.RepairDesignPostGPL`, which no longer buffers
    ports. The names, the defaults and the deprecated aliases are unchanged, so
    an existing configuration keeps working; the buffering happens earlier.
    **Behaviour change:** a custom flow that runs
    `OpenROAD.RepairDesignPostGPL` without `OpenROAD.AddBuffer` gets no port
    buffering at all.
  * Fixed port buffering letting OpenROAD choose the buffer. The cell named by
    `SYNTH_BUFFER_CELL` is now passed to `buffer_ports` explicitly, because
    OpenROAD would otherwise pick any cell it considers a buffer, which on
    gf180mcu can be a delay buffer. Ported from upstream by Leo Moser
    (librelane/librelane#961).

* `Odb.ReplaceECOCells`

  * Created. Replaces the cell of every instance a regular expression matches,
    optionally only those instances of a named current cell, then legalizes the
    placement and incrementally re-routes the affected nets. Driven by the new
    `REPLACE_ECO_CELLS` list variable, whose entries are `instance`,
    `replace_with` and the optional `current_cell`. A rule matching no instance
    is an error rather than a silent no-op (#967).

* `Odb.SetPowerConnections`

  * Fixed an instance that connects only some of its power and ground ports
    aborting the step. Yosys writes an empty bit list for a port the Verilog
    leaves explicitly open, such as `.VGND()`, and that was reported as
    "more than one bit connected" and treated as fatal. Such a port is now
    skipped and the connected ones are still hooked up. Ported from upstream
    by Leo Moser (librelane/librelane#991).

* `OpenROAD.OpenConsole`

  * Created. Loads the ODB view, the LIBs, the SDC and, if available, the SPEF
    for the current corner, then hands an interactive OpenROAD Tcl console over
    to the user. Same views as `OpenROAD.OpenGUI`, no display required (#532).

* `OpenROAD.OpenSTAConsole`

  * Created. Loads the netlist, the timing models and, if available, the
    parasitics for one corner, then hands an interactive OpenSTA console over to
    the user, so timing paths can be reported by hand (#532).

* Created `OpenROAD.SaveImage`, which renders a PNG of the current layout
  with OpenROAD's `save_image`. Unlike `KLayout.Render`, which needs a DEF or
  a GDS and so only runs once the layout has been streamed out, this reads
  the ODB and can be placed anywhere in the flow -- after floorplanning,
  after CTS, after routing -- and inserted as many times as there are moments
  worth a picture. It writes `<step_dir>/<design>.png` and does not update
  the state, so several instances do not fight over one view. Added
  `SAVE_IMAGE_WIDTH`, `SAVE_IMAGE_RESOLUTION`, `SAVE_IMAGE_AREA` and
  `SAVE_IMAGE_DISPLAY_OPTIONS` (#611).

* `OpenROAD.STAMidPNR`

  * Reports every corner in `STA_CORNERS` instead of one. The resizer steps
    on either side of it already optimize against all of them, so a mid-PnR
    STA reporting a single corner disagreed with the steps it sits between
    (#636). On sky130 that is nine corners rather than one, and the reports
    move from the step directory into one directory per corner, which is where
    the pre-PnR and post-PnR STA steps have always put theirs.
  * Added `STA_MIDPNR_CORNERS`, the step-specific override, for designs where
    reporting every corner four times per flow is not worth the runtime.
    `DEDUPLICATE_CORNERS` also applies, and collapses corners that share their
    libraries and RC values.
  * The power metrics stay on one corner. They aggregate by summing, and a sum
    of one design's power at several corners is not a number that means
    anything; every corner's own numbers are in its `power.rpt`.

* `OpenROAD.CheckMacroInstances`

  * Warns when a macro's `lib` or `spef` covers only some timing corners, or
    resolves to the same view at all of them -- neither of which was reported
    before (#605).

* `KLayout.StreamOut`, `Magic.StreamOut`

  * Added `KLAYOUT_ADD_ISOSUB` and `MAGIC_ADD_ISOSUB`, which draw the isolated
    substrate (subcut) layer over the design's bounding box on the way out.
    Both default to `False`. For a design destined to be integrated into
    another with multiple power domains (#531, #583).
  * Added `ISOSUB_LAYER`, the GDSII layer and datatype pair KLayout draws that
    shape on, supplied per PDK. `81/53` for sky130 and `23/5` for gf180mcu,
    which is what those PDKs' Magic tech files give the CIF layer `SUBCUT` that
    `isosub` maps to. Magic needs no such variable; it knows the layer by name.

* `KLayout.XOR`

  * Added `KLAYOUT_XOR_WRITE_GDS`, which also writes the XOR differences to
    `xor.gds` in the step directory, so they can be opened as a layout rather
    than only as a marker database. Defaults to off (#692).

* `Magic.DRC`

  * Reads GDS with `gds maskhints true`, so DRC rules that check magic's
    generated implant layers run against layers reconciled with the input
    stream (#928, cherry-picked from upstream #930).

* `Magic.WriteLEF`

  * `MAGIC_WRITE_LEF_PINONLY` now defaults to `True`. Metal on a pin's layer
    that is not under a port label becomes an obstruction instead of part of
    the PIN, so the written LEF pin matches the DEF pin. The previous default
    produced oversized pins, which downstream pin-size prechecks reject
    (#948).

* `OpenROAD.*`

  * Suppressed the `DRT-0349` alert (`LEF58_ENCLOSURE with no CUTCLASS is not
    supported`). It reports an OpenROAD limitation, not a design or PDK
    problem, and fired on every sky130 run (#550).
  * Added `report_dont_touch` and `report_dont_use` calls after the
    corresponding `set_` commands, and switched `filler_placement` to
    `-verbose`, so the don't-touch, don't-use and filler sets appear in the
    step logs (#630).
  * Added `OPENROAD_THREADS`, passed as OpenROAD's `-threads` argument, so
    every OpenROAD step can use multiple threads rather than only detailed
    routing. Defaults to the machine's thread count (#521, ported from
    upstream #937).
  * Deprecated `DRT_THREADS` in favour of `OPENROAD_THREADS`. The old name is
    still accepted.
  * Fixed `LAYERS_RC` and `VIAS_R` meaning different things under signoff STA
    and under PnR. `set_layer_rc` reads its arguments in whatever units the
    embedded OpenSTA is in, `set_cmd_units` is called only by the three scripts
    under `scripts/openroad/sta/`, and the other fifteen places that source
    `common/set_rc.tcl` are PnR scripts that leave the units at whatever the
    first liberty file declared. The values are now converted into the active
    units before being applied, as the technology LEF fallback beside them
    already was, and both variables are documented as kΩ/µm, pF/µm and kΩ per
    cut whatever the liberty declares. A PDK whose liberty is already in kOhm
    and pF, sky130 among them, is unaffected. gf180mcu's liberty declares ohm,
    so its resistances were a thousand times too small everywhere except
    signoff (#996).

* `OpenROAD.STAPrePNR`, `OpenROAD.STAMidPNR`, `OpenROAD.STAPostPNR`

  * Added the `timing__clock__fmax` metric and a "Max Frequency (MHz)" column
    in the timing summary, being the clock period less the setup worst slack,
    per corner. The overall figure is the smallest of them, so it reads as the
    frequency the design meets timing at everywhere. The column is red when a
    corner falls short of `1/CLOCK_PERIOD` (#790, ported from upstream #835).
    Only written for a single-clock design, since the setup worst slack is
    design-wide and there is no one period to subtract it from otherwise.

* `Yosys.JsonHeader`, `Yosys.Synthesis`

  * Macro `.lib` views and `EXTRA_LIBS` now reach the liberty set given to
    `dfflibmap` and ABC, not just the blackbox model list, so synthesis sees
    macro area and timing (#940).

* `Yosys.Synthesis`, `Yosys.Resynthesis`, `Yosys.VHDLSynthesis`

  * The ABC delay target is now written into the generated ABC strategy script
    rather than passed as `abc -D`. Yosys substitutes its delay target only
    into the scripts it builds itself, so `-D` was silently dropped for every
    run, which is all of them, since LibreLane always passes `-script`. The
    target now reaches `retime`, `upsize` and `dnsize` (#975, ported from
    upstream #898).
  * Added `SYNTH_ARITH_TREE`, on by default, which runs Yosys' `arith_tree`
    pass after `alumacc` to rewrite chains of arithmetic cells into carry-save
    adder trees. The sky130 APU design regresses on setup and slew under it
    and is dropped from the fastest test set upstream, so it is dropped here
    too; turn the variable off to run that kind of design (#975, ported from
    upstream #986). Requires Yosys 0.65 or newer.
  * Added `SYNTH_ABC_STRATEGY_SCRIPT`, which runs a user-supplied ABC script
    instead of the one generated for `SYNTH_STRATEGY`. Every other
    `SYNTH_ABC_*` variable is then ignored, except `SYNTH_ABC_DFF`, which is a
    flag on the `abc` pass rather than part of the script (#975, ported from
    upstream #899).
  * Every problem counted towards `synthesis__check_error__count` is now logged,
    along with the path of the report it came from. Yosys writes two `check`
    reports per run, the count only ever came from the earlier
    `reports/pre_synth_chk.rpt`, and the problems were logged at a level no
    default run displays, so a nonzero count sent readers to `reports/chk.rpt`,
    which routinely says zero problems (#824).

* `Verilator.Lint`

  * Fixed `LINTER_INCLUDE_PDK_MODELS` having no effect. It now gates
    `CELL_VERILOG_MODELS` and `PAD_VERILOG_MODELS`, and defaults to `True`,
    which is what the step already did unconditionally (#802).
  * Generates port-only Verilog modules from a macro's `lib` views when it has
    no Verilog view at all, instead of failing with "Cannot find file
    containing module" (#579).
  * Added `LINTER_ARGUMENTS`, passed verbatim to Verilator after every
    argument LibreLane builds, for options with no variable of their own --
    `--no-timing` being the motivating case (#492).
  * Added `LINTER_VLTS`, a list of Verilator configuration files, and
    deprecated the scalar `LINTER_VLT` in favour of it. The old name is still
    accepted and becomes a one-element list (#680, ported from upstream #983).

## Flows

* Gave the `odb`-editing steps to the jobs whose `odb` they edit.
  `OpenROAD.CutRows`, `Odb.AddRoutingObstructions` and
  `Odb.ManualGlobalPlacement` were jobs of their own in all three shipped
  documents, each needing only its predecessor, so the place-and-route chain
  read as one job per step. Each edits an `odb`, OpenROAD's native database,
  so none means anything unless its job resolved to OpenROAD, which makes
  them members of the `macro_placement`, `power_grid` and `detailed_placement`
  registrations rather than steps a document lists.
  `Odb.RemoveRoutingObstructions` was already inside `detailed_routing` for
  the same reason.
  * `classic.yaml`, `vhdl_classic.yaml` and `chip.yaml` run the same 82, 74
    and 83 steps in the same order as before, and lose four jobs each.
  * `write_verilog_header` and `sta_mid_pnr_1` were adjacent, inline and
    ungated in all three, and merge into one job named `post_gpl_checks` for
    what it does rather than for its first step. `vhdl_classic.yaml` calls its
    two-step version of that job the same thing, in place of the
    `power_grid_check` it had to invent.
  * `OpenROAD.AddBuffer` edits an `odb` too and stays a job a document lists,
    because `chip.yaml` runs global placement and deliberately does not run
    it: a chip's ports are the pad ring's bumps, and the pad cells have
    buffered them already. A step two documents want and a third refuses is
    the document's choice.
  * Run directories move accordingly, since a step's directory is
    `<run_dir>/<job id>/<n>-<step slug>`. `cut_rows/1-openroad-cutrows`
    becomes `macro_placement/2-openroad-cutrows`, and `write_verilog_header/`
    becomes `post_gpl_checks/`. A run started before this change therefore
    re-runs those steps when resumed, having no entry under the new path.
* Independent jobs run concurrently. A document orders jobs with `needs`, and
  two jobs with no path between them are scheduled together. In `Classic` the
  signoff tail fans out into four branches that previously ran one after
  another in list order, so `xor`, `magic_drc`, `klayout_drc` and the
  `lvs`/`formal_equivalence` chain now overlap and meet again at
  `final_checks`. The order a flat step list happened to be written in was
  never a statement that the steps depended on each other; a graph is what
  lets a flow say which ones do.
  * The two stream-outs are deliberately *not* concurrent. `klayout_streamout`
    needs `magic_streamout`, because each writes the neutral `gds` view if its
    own tool is `PRIMARY_GDSII_STREAMOUT_TOOL` or if nothing has written one
    yet. In series that reproduces "the primary tool owns `gds`" exactly. In
    parallel both would see an empty incoming `gds` and both would write one,
    and a join whose branches disagree on a key raises `JoinConflictError`
    unless the job names a `source` to settle it, which no static entry can do
    when the winner is whichever tool the PDK named.
* Registered `klayout` as a second provider of the `lvs` job, selected with
  `{"TOOLS": {"lvs": "klayout"}}` by a document written for it. On the three
  shipped documents that selection is refused at load — see the selection
  validation entry below — because `OpenROAD.WriteCDL` writes the framework
  metrics onto a branch whose siblings inherit them. Its sequence is
  `OpenROAD.WriteCDL`, `KLayout.LVS`. `KLayout.LVS` was previously reachable
  from no built-in flow at all (#696).
  * It is an *alternative* to the `netgen` provider, not an addition beside it.
    `lvs` is single-provider, so exactly one of the two runs. No default
    changes: `Classic` and `VHDLClassic` still run Magic plus Netgen unless
    `TOOLS` says otherwise.
  * `design__lvs_error__count` is therefore written by whichever provider was
    selected, and the two do not write the same quantity. Netgen reports its
    count of mismatching cells and nets. The KLayout scripts report only
    whether the netlists matched, so that provider writes `0` for a match and
    `1` for a mismatch. Both providers gate `design__lvs_error__count` at
    zero through their own `ERROR_ON_LVS_ERROR` -- `Netgen.LVS` and
    `KLayout.LVS` each declare it -- and behave identically either way; a
    dashboard or a regression comparison reading the number itself does not.
    The producing tool is the `lvs` entry of the run's resolved `TOOLS`.
  * The two checks are also not equally deep. Netgen compares a Magic-extracted
    netlist against the powered Verilog netlist; KLayout compares the GDSII
    against a CDL and is the less complete of the two on hierarchical designs.
  * `KLayout.LVS` supports `ihp-sg13g2` and `ihp-sg13cmos5l` only. On any other
    PDK it warns and emits no metric, and the `lvs` job's contract -- which
    requires `design__lvs_error__count` -- fails the run rather than letting
    an unmeasured design pass.
  * `OpenROAD.WriteCDL` sits inside the provider sequence rather than in the
    flows, for the same reason `Magic.SpiceExtraction` sits inside the `netgen`
    sequence: `KLayout.LVS` hard-requires the `cdl` view, no job promises
    one, and a flow that never selects this provider should not write a CDL it
    has no use for.
  * Issue #696 asked instead for `KLayout.LVS` to run *alongside* Netgen in the
    default `Classic` flow, behind a `RUN_KLAYOUT_LVS` gate. That shape was not
    implemented. Running both means two `lvs` jobs, one per provider, and two
    names would then have two unconditional writers:
    `design__lvs_error__count`, and the `spice` view that
    `Magic.SpiceExtraction` and `KLayout.LVS` both output. Sharing a name is
    not itself the problem, and no rule against it is being proposed:
    `Classic` runs two `streamout` jobs and both write `gds` deliberately.
    What makes that one safe is the explicit precedence rule the two
    stream-out steps implement on the PDK's `PRIMARY_GDSII_STREAMOUT_TOOL`.
    Neither of the `lvs` overlaps has an equivalent, so the winner would be
    decided by job order and be invisible. Two co-running `lvs` jobs therefore
    need an explicit statement of which contributor wins, which is what a
    document's `source` key is for.
  * Co-running both tools would also put a step supporting two IHP PDKs into
    the default flow for every PDK. The maintainer's reply on the issue
    proposes substitution instead, driven by PDK-supplied flow configuration,
    and the reporter asked for it not to be rushed; that redesign is untouched
    by this change, which only makes the substitution expressible.

* Added `RUN_RMP` to `Classic` and `VHDLClassic`, which enables the new
  `OpenROAD.RMP` step after floorplanning. It defaults to `False`, because
  local resynthesis rewrites the netlist every later step works on and the
  upstream pull request it comes from moved critical metrics on twelve of the
  CI designs (#558).

* Runs resume within an existing run tag. A step whose own
  configuration, the contents of every file that configuration names, and whose
  entire input state including metrics are all unchanged reuses the result it
  recorded, provided the views it produced still exist. Everything else
  re-runs, and re-running a step invalidates the steps after it.
  * Identity is content, not paths and not timestamps. Editing a file in place
    invalidates the steps that read it even though every path is byte for byte
    the same, and `touch`-ing a file without editing it invalidates nothing.
    The cascade follows contents too, so a re-run step that produces identical
    output leaves the steps after it reusable.
  * A step directory now records `resume.json`. Its presence is what marks the
    step complete, so a directory left half written by an interrupted run is a
    miss. Anything that cannot be proven is a miss, including an entry
    truncated by `kill -9`.
  * A tool upgraded in place, or a script edited in a development checkout,
    under an unchanged LibreLane version is not detected. `--invalidate` and
    `--overwrite` are the remedies, and {doc}`/usage/resuming_runs` says so.
  * `Optimizing` and `SynthesisExploration` built their steps in
    data-dependent loops and did not participate. Both are removed.
* **Behaviour change:** re-invoking a flow on an existing run tag no longer
  appends a second full pass to it. It previously re-executed every step into
  the same directory under fresh ordinals, seeded with whichever
  `state_out.json` had the latest modification time, which also meant metrics
  accumulated across passes and a step could receive a state produced
  downstream of it. `--overwrite` remains the way to discard a tag.
* A run directory holds one directory per job, and each of those one directory
  per step numbered by its position within that job, as
  `runs/TAG/<job>/<n>-<step>`. Jobs run concurrently, so there is no global
  step order to number against, and a position counted across the whole run
  would move whenever an unrelated edge was added to the document, renaming
  every directory after it and invalidating every result recorded in one. A
  job that is gated off or skipped contributes no directory, and the numbering
  inside the jobs that did run is unaffected.
* Migrated the `Classic` flow's configuration declarations to a nested typed
  `Config` model.
* Created a 27-job taxonomy, so the tool used for a phase can be selected
  rather than hardcoded. A flow names a job and the job expands into whichever
  steps implement it for the provider selected. `Classic`, `VHDLClassic` and
  `Chip` run the same steps as before, except for the DRC step reorder
  described below.
* Moved gating from individual step IDs to the job that owns them, so a
  gating variable applies whichever tool implements the job. A document writes
  one `if` on the job rather than a table mapping step ids to variables, and a
  gate that used to address one tool inside a two-tool phase, such as
  `RUN_MAGIC_DRC`, now sits on that tool's own job.
  * Three gating variables now reach further, each covering a step that was
    previously left running with nothing to consume its output:
    * `RUN_ANTENNA_REPAIR` also skips `Odb.DiodesOnPorts`. Setting it false
      used to insert diodes and then skip the repair pass they were placed for.
    * `RUN_DRT` also skips `Odb.RemoveRoutingObstructions` and the second
      `OpenROAD.CheckAntennas`. Obstructions exist to shape detailed routing,
      and an antenna check on an unrouted design reports nothing meaningful.
    * `RUN_LVS` also skips `Magic.SpiceExtraction`, which carries the
      illegal-overlap gate. The extraction exists to feed LVS, and disabling
      LVS used to still pay for it and still fail the run on a check nobody
      asked for.
* Added `TOOLS`, a mapping from job id to the provider implementing it, so a
  phase's tool can be chosen from configuration instead of by editing the
  flow. `{"synthesis": "yosys"}` on `VHDLClassic` runs the Verilog sequence
  where that document would have run the VHDL one. Unknown jobs and providers
  are rejected by name, with a suggestion for a near miss, and a selection
  the document cannot run is refused at load — see the selection validation
  entry.
  * `TOOLS` must be a literal mapping. It is read by a pre-pass ahead of full
    configuration resolution, because a flow's step set has to be known before
    the configuration those steps declare can be validated, so `expr::`,
    `ref::` and PDK-supplied values cannot appear in it.
  * `TOOLS` is not read from Tcl configuration files, which need process
    information that is not resolved that early. Such a file is reported as
    unconsulted rather than silently treated as empty.
  * `TOOLS` may be written inside a `pdk::` or `scl::` section, which is how
    one configuration selects a different tool per process. Tool selection
    resolves the PDK and the standard cell library first, by calling
    `Config.expand_sources` — the same method `Config.load` calls, and the
    only implementation of that resolution, so the provider a run uses and the
    `TOOLS` `--explain-variables` prints cannot differ. It reads the process
    from `--pdk`, `--scl`, `--pdk-root` and the sources, ranking them as the
    loader does, and an `scl::` section is matched against the library the PDK
    defaults to when nothing names one.
    * Previously the pre-pass read the sources as written, so a scoped `TOOLS`
      was invisible to selection while the loader promoted it: the run used
      one provider and the resolved configuration reported another.
    * Where a source scopes `TOOLS` and a `.tcl` configuration file is passed
      alongside it, the section is refused by name. A Tcl file may itself
      declare the `PDK` and cannot be evaluated this early, so which process
      the section applies under would be a guess.
    * Where no source scopes `TOOLS`, no PDK is resolved and none has to
      exist. `TOOLS` is the only key this pass reads, so a section that cannot
      reach it — `pdk::sky130A: {FP_CORE_UTIL: 40}`, the ordinary use — leaves
      tool selection asking the filesystem nothing.
  * Re-pointing a job at a different provider does not disturb its gating. A
    document's `if` is a property of the job, not of the steps the provider
    happened to contribute, so it applies to whichever tool runs.
* Job contracts are enforced at run time. When the last step of a job
  completes, every view in the job's `provides` must be in the state and every
  metric in its `metrics` must have been emitted, or the run fails. There is no
  warn-and-continue: a backend that does not report `route__drc_errors` must not
  be able to let `OpenROAD.DetailedRouting`'s `ERROR_ON_TR_DRC` gate pass on
  an unexamined design. Metrics are
  compared by exact name. A provider that measures per corner or per net
  satisfies the contract by aggregating its variants into the base-named
  metric, which is what `aggregate_metrics` does with the METRICS2.1
  modifiers; the variants on their own do not satisfy it.
  * A run that did not execute every step it covers, because they were gated,
    skipped, or left outside a `--target`, is not checked. Its views and
    metrics were never attempted.
  * A provider additionally answers for the `provides` and `metrics` its own
    registration declares, checked once its own steps complete rather than
    once the job does. So `RUN_MAGIC_DRC=false` leaves
    KLayout still answerable for `klayout__drc_error__count`, where a single
    job-wide check would have excused it along with Magic. The job's own
    `provides` stay a joint obligation, which is what lets both `streamout`
    tools share the promise of a neutral `gds` view while
    `PRIMARY_GDSII_STREAMOUT_TOOL` decides which of them writes it.
* View availability is checked before any tool runs. Every non-optional view a
  job requires must be produced by one of its predecessors in the document, or
  the flow fails at startup naming the view, the job requiring it, and the
  predecessors it does have. An optional input is satisfiable by absence and is
  not a failure. A view no job in the document produces at all is presumed to
  arrive in the initial state and is left to the run, which is what lets a
  document start mid-flow from `--with-initial-state`.
  * That check reasons over the graph the document declares, so it cannot see a
    `TOOLS` entry. A second pass runs after the providers are selected and the
    configuration is resolved, and refuses a selection that removes the only
    producer of a view some job still requires: `{"synthesis": "yosys_vhdl"}` on
    `Classic` now fails at load naming `json_h` and `set_power_connections`,
    where it used to be accepted and fail during the run at the first step
    reaching for the Verilog header. Use the `VHDLClassic` flow, which makes the
    same selection in the document. See {doc}`/usage/swapping_tools`.
  * The second pass asks only what the *selection* took away, never what the
    document never had, so the presumption above is untouched: a view no job
    produces is still left to the initial state, and a document that starts
    mid-flow still loads.
  * A job's registration `native_views`, such as OpenROAD's `odb`, count as
    requirements there. They are exempt from the registration-time view check
    because a tool-native database cannot be named in a tool-neutral job's
    `requires`; this is where that exemption is now answered for.
  * The second pass also reads the initial state. `--with-initial-state` is the
    one invocation-shaped input it can see, because the command line resolves
    the state before it builds the flow, and the views that state supplies are
    available to every job: a selection that only stops producing views the run
    already holds is not refused, and `{"synthesis": "yosys_vhdl"}` on `Classic`
    loads for a run resuming from a state that carries `json_h`. The
    alternatives a refusal offers are measured under the same state, so a
    provider that works only because the state has the view is still offered. A
    view the state maps to `null` is not supplied, which is the reading the step
    consuming it gives.
* A `TOOLS` selection that would stop the run with a `JoinConflictError` is
  refused at load. The same replay of `librelane.flows.join`'s rule that guards
  the shipped documents now runs over the providers a configuration actually
  selected, and the message names the colliding key, both jobs that write it,
  and every provider that would work instead. `{"magic_drc": "klayout"}`,
  `{"klayout_drc": "magic"}` and `{"lvs": "klayout"}` are the three shipped
  selections it catches, on all three documents.
  * A provider is offered as a remedy only if it would actually run one.
    Added `Step.implemented`, a class attribute that is `True` for every step
    that drives a tool and `False` on the two commercial scaffold bases in
    `librelane.steps.vendor`, whose `run` raises `NotImplementedError` by
    design; `Registration.runnable` derives from it. So a caller who has opted
    into `librelane.jobs.providers_vendor` is not told to fix
    `{"magic_drc": "klayout"}` by selecting `calibre`, `icv` or `pegasus`, all
    of which resolve cleanly and none of which can run. Selecting one directly
    is still permitted: the opt-in exists so those scaffolds can be selected and
    filled in, and whoever fills one in deletes its `implemented = False`.
  * It reads the jobs that will *run*, not every job the document declares. A
    job whose `if` is false fires as a pass-through and writes nothing, so
    `{"magic_drc": "klayout"}` alongside `RUN_MAGIC_DRC: false` — which is what
    the old stage-keyed `{"drc": "klayout"}` migrates to — still loads. A check
    that refused it would be rejecting a flow that runs, which is worse than the
    mid-run failure it replaces.
* Audited step ownership across every provider, against one rule: a step that
  only makes sense when a particular tool was selected belongs inside that
  tool's provider registration, so deselecting the tool removes the step with
  it. A step whose inclusion is the flow's choice, independent of the tool, is
  a step a document lists directly with `steps`.
  * **Fixed:** `Magic.DRC` and `KLayout.DRC` each carry the gate for their own
    metric -- `ERROR_ON_MAGIC_DRC` on `magic__drc_error__count`,
    `ERROR_ON_KLAYOUT_DRC` on `klayout__drc_error__count` -- so each lives
    inside the `drc` job's own provider registration, `magic` or `klayout`,
    and deselecting a provider removes its gate along with it.
    `{"drc": "klayout"}` therefore removes `Magic.DRC` and its gate together;
    no gate is left running on a metric the deselected tool never emitted.
  * `KLayout.XOR` compares the two streamout tools' output against each
    other and gates on its own `ERROR_ON_XOR_ERROR`, so it belongs to neither
    registration and stays a plain step. The view preflight is what
    guarantees both GDSII views were produced.
  * `Magic.WriteLEF` stays a plain step: it consumes the neutral `gds` and `def`
    views rather than Magic's own, so it is Magic-implemented but not
    Magic-dependent, and whether a flow wants a LEF abstract at all is a
    flow-level choice. `Chip` deliberately does not.
  * A step whose own metric the job contracts, such as
    `OpenROAD.DetailedRouting`'s `route__drc_errors`, carries the job's
    gating variable directly rather than through a separate checker:
    membership in the registration is what gives it `ERROR_ON_TR_DRC`.
  * Fourteen plain steps of `Classic` consume OpenROAD's `odb`, so they depend
    on OpenROAD implementing the surrounding jobs. They cannot move into a
    registration, because they sit between jobs: `OpenROAD.STAMidPNR` appears
    four times at different points. A flow selecting a non-OpenROAD place-and-
    route provider must be written as a document that does not list them, and
    the view preflight is what says so.
* A document pins the tool a job runs by writing `uses: synthesis/yosys_vhdl`
  rather than `uses: synthesis`. A pin is the document's default rather than a
  lock: a `TOOLS` entry still overrides it.
* `vhdl_classic.yaml` writes out what `VHDLClassic` runs, rather than deriving
  it from `Classic` by substitution. It repeats `Classic`'s configuration
  declarations, which are genuinely shared, but what it runs is written down in
  one place rather than expressed as edits to another flow's list. The step
  list is unchanged.
  * `Odb.SetPowerConnections` moved out of the `floorplan` job's `openroad`
    provider and into a job `classic.yaml` lists directly. It hard-requires the
    Verilog header, so as a mandatory member of a tool-neutral job it made
    floorplanning impossible for any flow without Verilog sources. Listed
    directly, a flow that cannot run it simply omits it. The step list is
    unchanged.
  * `RUN_LINTER` and `RUN_EQY` are still declared by `vhdl_classic.yaml`, so a
    configuration setting either one keeps loading, but have no effect there,
    since it runs neither job. Their descriptions say so.
* `Workflow.get_help_md` renders the flow's resolved job table, so
  `librelane help Classic` and the documentation build show every job
  alongside the provider selected for it and its registered alternatives, with
  a pointer to the new tool-swapping guide. There is no `--list-jobs` CLI
  flag; `get_help_md` is what both `librelane help` and the documentation
  build already consult, so the same information needs no new CLI surface.
* A provider registration names exactly one job. Gating, contract checking
  and provider selection are all per-job, so a registration covering several
  had no meaning in any of them. See {doc}`/usage/writing_tool_backends` for
  the reasoning and for what a tool with a long-lived session does instead.
* Removed `Substitutions`, `Substitute` and `meta.substituting_steps`. Write a
  document that declares what it runs, as `vhdl_classic.yaml` and `chip.yaml`
  do. The `hold_eco_demo` example and the ECO usage guide are removed with
  them; a flow that inserts `Odb.InsertECOBuffers` is now written as its own
  document.
* `meta.flow` no longer accepts a list of step IDs, and a list is now rejected
  with an error rather than silently falling through to `Classic`. Name a
  registered flow.
* Removed the `Optimizing` and `SynthesisExploration` demo flows. Both built
  their steps in data-dependent loops, which is the one shape per-step resume
  cannot serve; the multi-threading pattern they demonstrated is now written
  out inline in {doc}`/usage/writing_custom_flows`.
* Added `Workflow.explain`, which reports what a prospective invocation would
  do without running it, one row per job the document declares. Resume is
  deliberately not reported, because a resume verdict depends on content
  fingerprints of files that later steps in the same run will rewrite and so
  cannot be known beforehand.
* Gating and skipping are decided before reuse in the run loop, so the two
  mechanisms no longer interfere.
* `--reproducible` naming a step this configuration would never execute,
  because it is gated off or named by `--skip`, now raises rather than
  silently producing nothing.
* `OpenROAD.OpenConsole` and `OpenROAD.OpenSTAConsole`, previously reachable
  from no built-in flow at all, are opened the same way the GUI viewers are:
  `librelane open openroad-console` and
  `librelane open opensta-console --last-run <run folder>/resolved.json`
  (#532).
* **Fixed:** the `PDK`/`SCL`/`PAD`/`meta` reserved-key refusal only walked a
  document's own `with` block, so a job's `with` block could still set `PDK`.
  After the `TOOLS` pre-pass became PDK-aware, that job value would be layered
  into the job's own configuration resolution and could select a different
  process than the one the pre-pass had matched `pdk::`/`scl::` sections
  against, reopening the selector/loader divergence that pre-pass exists to
  rule out. `_check_values_are_not_reserved` now walks the document's `with`
  block and every job's, the same structural pattern
  `_check_values_do_not_select_tools` already used for `TOOLS` (#47).
* Added loops: a document's `needs` may now close a cycle, provided it is a
  simple ring -- every member has exactly one predecessor inside it -- with
  exactly one member, the ring's gate, declaring `until`. The gate's `until`
  is a conjunction of `metric::` terms checked against its own output after
  each pass; the ring reruns, in ring order starting at the gate's successor,
  until `until` holds or the gate's bound is exhausted. The bound is either
  `max`, a plain pass count under which no pass changes any configuration, or
  `iterations`, a value matrix -- each configuration variable mapped to the
  values it takes -- whose points are the passes, layered onto every member's
  configuration, the escalation shape. Naming two variables sweeps their
  product, the variable named last varying fastest. Exhaustion is a deferred
  error naming
  the gate and the bound rather than a hard failure: the run continues with
  the last pass's state and fails at the end. Each pass gets its own run
  directory, `<job id>/<k>/...`. See {doc}`/usage/writing_custom_flows`.
  * A ring member other than the gate is gated fresh each pass by its own
    `if`, exactly as a non-ring job's is. The gate's own `if`, if it
    declares one, is evaluated once, at loop entry, against the tokens the
    ring's predecessors outside it supply, and gates the whole loop instance
    rather than any one pass; it is not asked again pass to pass, so a
    runtime term in it changing truth value as the ring's circulating state
    evolves does not silently drop the gate's own steps mid-loop.
* Added `metric::` terms to `if`, and to a ring gate's `until`:
  `metric::<name> <op> <literal>`, rather than only a configuration variable
  decided at load time. `if`'s runtime terms are evaluated against a job's
  joined *input* state immediately before it would run; `until`'s are
  evaluated against the gate's *output* state after each pass finishes. A
  false runtime term fires the job (or, for the gate, the whole loop
  instance) as a pass-through, logged with the observed value, the same
  value `--explain` reports afterwards; a term whose metric is absent from
  the state it is checked against is a runtime error, since absence is not
  the same measurement as false. `if` may mix `metric::` terms with the
  configuration-variable terms it already accepted; `until` accepts only
  `metric::` terms, since a configuration term is constant across a loop's
  passes and could never make a gate decide differently pass to pass. A
  term's observed value must be a plain number: a Boolean is refused by
  name, since a Boolean is never a quantity despite being an `int` subclass,
  rather than silently read as 0 or 1. The same refusal applies to a sweep
  job's `select` metric below.
* Added sweeps, declared with `select`. A sweep job runs its steps at every
  point of its own `iterations` matrix concurrently, from one joined input,
  and keeps the pass whose `select` metric (a name and a direction, `min` or
  `max`) is best, ties breaking to the lowest pass index. Losing passes'
  outputs stay on disk under their own pass directory but reach nothing
  downstream. A sweep job may not be a ring member.
  * A loop and a sweep are the same passes over the same matrix under
    different rules for which pass wins, so there is no key naming the
    shape: `until` stops at the first pass that satisfies it, `select` runs
    every pass and keeps the best, and a job declaring both, or a matrix
    declaring neither, is refused.
* Added `resources`: a document may declare named pools at the top level,
  each a positive integer capacity or the name of an `int` configuration
  variable resolved once when the flow is constructed, and a job names the
  pools it needs in its own `resources` list. Acquisition is all-or-nothing
  across every pool a job names, so a job never holds one pool while waiting
  on another, and a seat is only ever granted to work already running on a
  worker, so work that cannot get a worker waits holding nothing; together
  these are what keep pools from deadlocking whatever a document declares. A
  capacity below 1 is refused before the run starts. A loop member acquires
  and releases its own pools per pass rather than for the whole loop; a
  sweep's passes acquire independently, so a two-seat pool still runs a
  five-point sweep two passes at a time.

## Tool Updates

* Relaxed version requirement for `rich` to allow rich 15.
* Updated nix-eda to 7.0.0, which moves the Nix environment to NixOS 26.05
  (#854, ported from upstream #977). Magic becomes `8.3.674`, Netgen
  `1.5.320`, Yosys and its eqy/sby plugins `0.66`, Verilator `5.046`, KLayout
  `0.30.9` and GHDL `6.0.0`. Ciel is pinned to `2.5.1`.
  * Dropped the local `lemon-graph` C++20 patch and the local `yamlcore`
    Python package. NixOS 26.05 carries both, and nothing in this fork read
    the nixpkgs `yamlcore` anyway, since the Python environment is built from
    `uv.lock`.
  * `tclint` is now taken as a top-level argument in `nix/openroad.nix` rather
    than out of `python3.pkgs`, matching where NixOS 26.05 puts it, and
    `openroad` no longer needs `llvmPackages_18` pinned.
  * `flake-compat` comes from `github:NixOS/flake-compat` as a non-flake input
    instead of the FlakeHub tarball.
  * `yosys-ghdl` inclusion is decided by `lib.meta.availableOn`, which honours
    `meta.badPlatforms`, rather than by searching `meta.platforms`.

## Tool Updates

* Updated OpenROAD to `aec50a45`
* Updated OpenSTA to `a56edf27`
* Updated OpenROAD-ABC to `17cadca0`

## Misc. Enhancements/Bugfixes

* **Fixed:** a job continues past a deferred error with the deferring step's
  own output. The engine recorded the error and left the running state on the
  previous step's, which was harmless while only `Checker.*` steps deferred --
  they produced nothing -- and is not now that the step raising is the step
  that measured. `OpenROAD.DetailedRouting` reporting DRC violations still
  routed the design, and every later step would otherwise have received the
  views from before it ran. A step that defers from inside `run` still has no
  output and the flow still carries on with the state it had; `Step.start`
  clears `state_out` before running, so the two cases are told apart by
  whether the step got far enough to produce one. Neither writes a resume
  entry, so a resumed run re-runs the step and raises again.
* Added `InstanceArray`, reachable as the `array` attribute of a macro
  instance, which expands one entry into a grid of instances on a regular
  pitch. The instance name is a template taking `{X}`/`{COL}`, `{Y}`/`{ROW}`
  and `{SEQ}`. Giving both `array` and `location` is an error (#893, ported
  from upstream #896).
* Added `VERILOG_FLIST_FILES`, which names F-lists (`*.f`) for the preprocessor
  to unpack. Each listed file's `+incdir+` and `+define+` lines are appended to
  `VERILOG_INCLUDE_DIRS` and `VERILOG_DEFINES`, every other line to
  `VERILOG_FILES`, and the key itself is then dropped, so no step sees it.
  Preprocessor directives work on the paths in `VERILOG_FLIST_FILES` but not
  inside an F-list. Only (System)Verilog is supported (#901, ported from
  upstream #902).
* Fixed `Classic` and `VHDLClassic` failing at the `pre_pnr_sta` job
  boundary, which made them unable to complete a run on this branch. The job
  was contracted to produce an `sdc`, but no OpenSTA script writes one: the
  SDC in the state is the floorplan's, and the SDC these steps read is the
  `PNR_SDC_FILE` configuration variable. The false claim originated in
  `MultiCornerSTA.outputs`, which the job's `provides` was then derived from,
  and which the runtime never checks because a step's declared outputs are not
  enforced the way its inputs are.
  * `MultiCornerSTA` declares `SDF` only, `PrimeTime.STAPrePNR` and
    `OpenROAD.DumpRCValues` declare no outputs, and `FC.Floorplan`,
    `ICC2.Floorplan` and `Innovus.Floorplan` no longer declare an `SDC` input
    that no earlier step in any flow produces.
  * `pre_pnr_sta` now provides nothing and `floorplan` requires only the
    netlist, both of which now describe what the steps do.
  * Two tests check the general form: an OpenROAD step may not declare an
    output that neither its script nor its own `run` ever writes, and a job
    contract may not promise a view whose only declared producer never writes
    it.
* **Fixed:** a `pdk::`/`scl::` section no longer outranks a configuration
  source layered after the file that carried it. The sections were expanded
  after every source had been flattened into one mapping, so which of two
  files won a key was decided by that mapping's insertion order -- and a
  `--config-override` on a key the first file already wrote at the top level
  kept that key's position, above the sections, and was silently discarded.
  `librelane -c CLOCK_PERIOD=20 librelane/examples/spm/config.yaml` ran at the
  shipped example's `CLOCK_PERIOD` of 10 while `--explain-variables` reported
  the value as the command line's.
  * Each source's sections are now expanded into that source before the
    sources are layered, so a section overrides the file that carried it and
    nothing else, and an override beats every file.
  * A key promoted out of a section is now attributed to the file that carried
    the section. `--explain-variables` reported `default` for the example's
    `FP_CORE_UTIL`, or the PDK for a variable the PDK also sets, because the
    attribution was recorded under the section's own key and dropped when that
    key did not survive.
* A matching `pdk::`/`scl::` section now overrides its own file's top-level
  value wherever the block is written, rather than only when it appears below
  the key. Every shipped configuration writes its sections last, so no shipped
  file changes meaning; moving a section within a file no longer changes what
  it resolves to. Documented behaviour before this release said document
  order decided.
* A `--config-override` for a `list`- or `dict`-typed variable is now read as
  JSON, which is what `--override-config`'s own help text and the `TOOLS`
  reader in `librelane.jobs.tools` have always said it is. Every such variable
  was unusable from the command line before: the value was split as a Tcl
  list, so `-c 'TOOLS={"lvs": "netgen"}'` died with `uneven Tcl dictionary`.
  * A scalar variable still takes the text exactly as written, so
    `-c CLOCK_PERIOD=15` is unchanged. A space-separated list, which the
    command line used to accept for a list variable, is now an error naming
    the variable and the syntax: write `-c 'CELL_PAD_EXCLUDE=["*decap*"]'`.
    The `dir::`, `refg::`, `ref::` and `expr::` prefixes still apply to a
    whole override, so `-c 'VERILOG_FILES=dir::src/*.v'` needs no JSON.
* How a string reaching a `list`- or `dict`-typed variable is read is now a
  property of the source that wrote it rather than a flag on the key: Tcl for
  a `.tcl` file, JSON for the command line, and an error for a `.json`,
  `.yaml` or API mapping, whose grammars carry a list as a list. The source
  that wrote a key last decides, so a mapping layered over a `.tcl` file is
  no longer silently held to Tcl's rules, and a value moved onto a variable's
  current name from a deprecated one keeps the syntax it was written in. A
  `.tcl` configuration's values are read exactly as before.
* A variable declaring both a string and a list -- `CLOCK_PORT` and
  `CLOCK_NET`, which are `None | str | list[str]` -- is now coerced instead of
  being handed to Pydantic unshaped. `-c 'CLOCK_PORT=["clk", "clk_i"]'` named
  a single clock port whose name was the literal text of that array, under
  every syntax and in every release that had these variables, because the
  string member matched before anything looked at the brackets.
  * From the command line, a value whose first non-blank character is `[` or
    `{` is now a document and must parse as one; a broken one is an error
    naming the variable and the grammar, never the text as written. Anything
    else is still the string, so `-c CLOCK_PORT=clk` is unchanged.
  * From a `.tcl` file such a value is still the string. Every Tcl value is a
    word list, so `clk_a clk_b` cannot be told from a one-word list, and the
    declared string is what these variables have always resolved to there.
  * From a `.json` or `.yaml` file or an API mapping, a string is a string and
    an array is a list, as those grammars already say which was meant.
  * A union that declares no scalar member at all -- every member a `list`,
    `tuple` or `dict` -- now reports a value it cannot place as an error
    naming the variable and quoting the text, rather than passing it on for
    Pydantic to describe as a bare type mismatch. A union that does offer a
    scalar is unaffected: `None | int | list[str]` still takes
    `-c 'N=4'` as written, because a union offering `int` may not be stricter
    than `int` alone. A value that fits two members equally -- a JSON array
    where both `list` and `tuple` are declared -- is likewise an error, since
    nothing knows which was intended.
* Reworked configuration loading around typed Pydantic models and a staged
  read/layer/process/preprocess/validate pipeline.
* Added structured configuration diagnostics, replayed after flow log sinks
  are active.
* Added forward references and cycle diagnostics to the configuration string
  language.
* Registered seven metrics that steps emit but `library.py` never declared, so
  they were dropped from both aggregation and CI metric comparison. Four of
  them gate the flow through a step's own `gates` (#567).
* Fixed reproducibles created from composite steps failing to run: the
  constituent steps re-read the PDK configuration, which a reproducible's
  copied file tree does not contain (#621).
* Fixed a reproducible created without the PDK being unreadable when its input
  state names a view that lives inside the PDK (#600). The writer stores such a
  view as the unresolved directive `pdk_dir::<relative>`, since a reproducible
  does not carry the PDK, but `State.load` read it as a literal path and
  rejected it as missing. `State.load` and `State.loads` take an optional
  `symbols` mapping and resolve `dir::` and `pdk_dir::` against it through the
  configuration preprocessor, and `Step.load` supplies the same `PDKPATH` and
  `DESIGN_DIR` it resolves the configuration's own directives against. Without
  `symbols` a stored directive is still an error rather than a literal path.
* Fixed later configuration sources not being able to select
  `STD_CELL_LIBRARY` (#827).
* Improved lax union coercion for fields validated by Pydantic.
* Fixed lax union coercion picking a less specific member for `pdk=True`
  variables read from a PDK's `config.tcl`, which is still resolved by the
  legacy Tcl path in `config/legacy.py` rather than by Pydantic (#993).
  * The legacy path refuses to read a Boolean as a quantity. `bool` is a
    subclass of `int`, so `int(True)` was 1 and a numeric union member
    swallowed every Boolean declared after it. `config/types.py` already
    stated the same rule for the Pydantic path.
  * The five `KLAYOUT_*_OPTIONS` variables now declare their value type as
    `int | bool | str` rather than `bool | int | str`. Every value in a PDK's
    `config.tcl` is a string, and with `bool` first the strings `1` and `0`
    became `True` and `False` instead of the numbers they are written as.
    Ordering the members by how much they accept, narrowest first and `str`
    last, is right for every string a PDK can write.
* Fixed multiple globs supplied to a `list[Path]` field (#712).
* Fixed strict validation rejecting whole numbers for `Decimal` fields,
  sequences for tuple fields, and mappings for dataclass fields such as
  `Macro`.
* Fixed declared defaults being validated in their written form rather than
  the shape of their annotation.
* Fixed a deprecated variable name supplied by a design being ignored whenever
  the PDK also supplied the current name. Deprecated names are now translated
  per configuration layer, so the design's value wins under either spelling,
  and the deprecation is still reported.
* Rebuilt the Nix environment around a uv2nix virtual environment: the flake
  now derives the runtime, development, and notebook environments from
  `uv.lock`, and the `librelane` package wraps its entry points so the
  interpreters it shells out to resolve `python3` within that environment.
* Replaced `NIX_PYTHONPATH` with `PYTHONPATH` for Nix plugin injection and for
  the host package mounted by `librelane --dockerized`, since a virtual
  environment's interpreter does not read the former.
* Fixed the resource monitor started for each subprocess outliving its
  process. Its loop only ended when the child died, so a caller that abandoned
  the process left a thread polling for the rest of the session.
* Fixed `Odb.AddPDNObstructions` and `Odb.RemovePDNObstructions` deriving from
  the routing-obstruction steps, so each carried a configuration model for a
  variable it does not read. Both pairs now derive from a shared abstract step.
* Excluded the `test/steps/all` and `test/designs` submodules from linting;
  they are pinned to another repository's commits.
* Fixed a cursor-restoring control code being written to standard output by any
  process that merely imported LibreLane, which corrupted output a caller was
  parsing. The repair now goes to standard error, where terminal control
  belongs.
* Fixed the test suite leaving the global logging options as a CLI invocation
  set them. `--condensed` turns the progress bar off for the whole process, so
  one CLI test disabled the bar every later test rendered into.

## API Breaks

* Flows are YAML documents rather than Python classes. `SequentialFlow` and
  `StagedFlow` are deleted, along with `Classic`, `VHDLClassic`, `Chip`,
  `OpenInKLayout`, `OpenInMagic`, `OpenInOpenROAD`, `OpenInOpenROADConsole`
  and `OpenInOpenSTAConsole` as importable classes. Three of them ship as
  documents, `librelane/flows/chip.yaml`, `classic.yaml` and
  `vhdl_classic.yaml`, each registering under the name its class carried, so
  `--flow`, `meta.flow` and the `{flow}` documentation role are unaffected for
  those three. The five `OpenIn*` flows are not reborn as documents: opening
  a run in a viewer was never a flow, since it runs one step, advances
  nothing and waits for a human, so `librelane open <viewer>` replaces them
  instead -- see the CLI entry above.
  * `Flow.factory.get(name)` returns the
    {class}`librelane.flows.spec.FlowSpec` the document parsed into, rather
    than a `Flow` subclass, and {class}`librelane.flows.engine.Workflow` is
    what runs it. `Flow.factory.list` is unchanged.
  * `Flow.factory.register` takes a `FlowSpec` and is no longer a decorator.
    `@Flow.factory.register()` over a class raises `TypeError`. Register a
    document with `Flow.factory.register(load_flow_spec("./my_flow.yaml"))`.
  * `librelane.steps.checker` is deleted, along with the `Checker` namespace
    exported from `librelane.steps` and every step in it. Nothing replaces the
    module: a limit is now a `MetricGate` or `CornerMetricGate` in the
    `gates` of the step that measured the metric, and `librelane.steps`
    exports both. A configuration naming a `Checker.*` step is rejected by the
    step factory; every `ERROR_ON_*` variable those steps declared still
    resolves, on its new owner.
  * `Flow` itself remains, as machinery rather than as a declaration base. It
    is still an abstract base class whose one abstract method is `run`, and
    `Flow.start_step` and `Flow.start_step_async` keep their signatures. Two
    members did change: `Flow.dir_for_step` returns a `pathlib.Path` rather
    than a `str`, and `Flow.Steps` defaults to `[]` rather than to
    `NotImplemented`, because `Flow.__init__` iterates it before a subclass
    that leaves it to `Workflow` has one. `start_step_async` submits to the
    process-wide pool `Workflow` fills with whole jobs, so a flow that calls
    it from inside a job waits on a worker that will not free up.
    A flow that has to decide what to run
    next from what a step just produced is still written in Python against it,
    which a document cannot yet express; see
    {doc}`/usage/writing_custom_flows`. Such a flow has no registered name and
    is constructed and started directly.
* `SequentialFlow.gating_config_vars` is deleted along with the class, and no
  gating table replaces it. A job carries `if: SOME_VARIABLE`, so a gate names
  the job it turns off rather than a step id or a wildcard over step ids, and
  it applies whichever tool implements that job.
* For code written against the development branch only, since none of these
  names appear in a released version: `Job.using`, `Job.multi_provider`,
  `Job.optional`, `Job.gating_config_var` and `Job.default_providers` are
  deleted, and `Job.default_provider` is one provider name or `None`. A
  document pins with `uses: job/provider`, declares two jobs where two tools
  run the same phase, and omits a job it does not want.
  * Under the same qualifier, `StepDisposition` and the `steps` field of
    `Explanation` are deleted. `Explanation.jobs` is a tuple of
    `JobDisposition`, one per job the document declares, in topological order.
  * `streamout` and `drc` now default to the `magic` provider, where both
    previously defaulted to Magic and KLayout together. A bare
    `uses: streamout` therefore runs Magic alone. `classic.yaml` and
    `chip.yaml` declare `magic_streamout`/`klayout_streamout` and
    `magic_drc`/`klayout_drc`, so what those flows run is unchanged.
* `TOOLS` is keyed by job id rather than by stage id when a flow is run from a
  workflow document. A document names its own jobs, and one stage may run
  under several names, so the stage id is no longer a key any document
  answers to.
  * `{"TOOLS": {"streamout": "klayout"}}` and `{"TOOLS": {"drc": "klayout"}}`
    named a stage and ran one of its two providers. A document declares
    `magic_streamout`/`klayout_streamout` and `magic_drc`/`klayout_drc`
    instead, each gated by its own Boolean, so the replacement is
    `{"RUN_MAGIC_STREAMOUT": false}` and `{"RUN_MAGIC_DRC": false}`.
    Re-pointing `magic_streamout` at `klayout` is accepted and is not the same
    thing: it runs KLayout's stream-out twice.
  * A key that names no job of the flow is rejected with a near-miss
    suggestion, so a stage-keyed configuration fails at startup rather than
    being ignored.
  * A list value is no longer accepted. A list is how one stage ran two tools,
    and two tools is now two jobs. `{"TOOLS": {"streamout": ["magic",
    "klayout"]}}` has no single-job replacement; declare both jobs.
  * A key naming a job that lists its steps inline is rejected. Such a job has
    no provider to override.
  * A `TOOLS` entry still overrides a provider a document pinned with
    `uses: job/provider`. A pin is the document's default, not a lock.
* `KLAYOUT_DENSITY_OPTIONS`, `KLAYOUT_ANTENNA_OPTIONS`, `KLAYOUT_DRC_OPTIONS`,
  `KLAYOUT_LVS_OPTIONS` and `KLAYOUT_FILLER_OPTIONS` read a `1` or a `0`
  written in a PDK's `config.tcl` as the number rather than as `True` or
  `False`, so a step that formats an option into a KLayout `-rd` argument now
  passes `feol=1` where it passed `feol=true` (#993). Of the PDKs ciel
  distributes, only sky130A and sky130B write numeric options, and the
  `sky130A_mr.drc` runset that consumes them tests each against `"0"` and
  `"false"`, so both spellings select the same rule groups. A runset that
  tests an option against the literal word `true`, as ihp-sg13g2's does, must
  be given `true` in the PDK's `config.tcl`, which is what ihp-sg13g2 writes.
* A Boolean supplied for an `int` or `Decimal` variable is rejected rather
  than read as 1 or 0.
* `Flow.start` passes `initial_state_given` to `Flow.run` alongside
  `initial_state` and `starting_ordinal`. A `run` override that accepts
  `**kwargs`, as the abstract signature declares, is unaffected.
* `Flow.start` no longer pre-populates `step_objects` from a resumed run's
  directories, and no longer seeds the initial state from the most recently
  modified `state_out.json`. `Step.load_finished` and
  `librelane.common.get_latest_file` are unchanged and remain supported.
* `CompositeStep` subclasses must declare a non-empty `Steps`. An empty one ran
  nothing and reported success. The class is also no longer marked internal: it
  is the supported way to bind one job to a multi-step tool sequence.
* `FlowError` and `FlowException` moved to `librelane.common.errors` so that
  `librelane.jobs` can derive from them without an import cycle. They are
  re-exported from `librelane.flows` and `librelane.flows.flow`, which remain
  their documented import sites.
* Removed the Cloup-specific `librelane.flows.cloup_flow_opts` decorator and
  `librelane.common.cli` helpers. Reusable Typer option annotations now live in
  `librelane.cli.options` and the CLI resolution helpers in
  `librelane.cli.runtime`.
* Removed `librelane.cli.flow_opts`. Its option annotations moved to
  `librelane.cli.options` and its helpers to `librelane.cli.runtime`.
* Moved the `librelane` command's implementation from `librelane.cli.main` to
  `librelane.cli.run`. `librelane.cli.main` now only assembles the app, and
  still exports `cli`.
* Removed `librelane.flows.cli`, along with the `ResolvedPdkOptions` and
  `resolve_pdk_options` re-exports from `librelane.flows`. Importing
  `librelane.flows` no longer pulls in Typer.
* Removed the `librelane.help` package. Its command is now
  `librelane.cli.help`.
* Removed the `librelane.env_info_cli` re-export from the top-level package.
  The implementation stays in `librelane.env_info`, which remains runnable
  with no dependencies installed.
* Removed `python3 -m librelane.config` and `python3 -m librelane.state`; the
  `librelane.config` and `librelane.state` console scripts are unaffected.
  `python3 -m librelane`, `python3 -m librelane.steps`, and
  `python3 -m librelane.common.metrics` continue to work.
* `MAX_FANOUT_CONSTRAINT` is now optional and no longer defaulted to `10` for
  sky130 and gf180mcu. When it is unset, `set_max_fanout` is not written to the
  SDC file and ABC's `buffer` runs without `-N`, so the liberty file's own
  `max_fanout` applies -- matching how `MAX_TRANSITION_CONSTRAINT` and
  `MAX_CAPACITANCE_CONSTRAINT` already behave. Designs relying on the injected
  `10` must now set it explicitly; timing results will otherwise change (#370).
* References in an earlier configuration source now resolve against values
  from the final merged layer.
* Configuration validation error wording now comes from structured Pydantic
  diagnostics.
* Removed the undocumented `librelane.config.variable` module path. The
  documented `librelane.config.Variable` compatibility export remains.
* Removed `librelane.resources` and its `package_path` accessor. Packaged
  scripts are reached with `importlib.resources.files("librelane")` at the
  point of use; the module's other branch materialized the package into a
  temporary directory, a fallback for a case `importlib.resources` already
  answers.
* Removed `librelane.logging.LogLevels`, `librelane.logging.LevelFilter` and
  `librelane.logging.deregister_additional_sink`. Loguru's own level registry,
  per-sink `level=` and `logger.remove` cover all three; `ALL` is now a
  registered Loguru level rather than a LibreLane-only name.
* Removed the Nix shell arguments `extra-python-packages` and
  `include-librelane`. Plugins are supplied through `librelane-plugins`, and
  the shell's Python environment is selected with `python-env`.
* For code written against the development branch only, since none of these
  names appear in a released version: `librelane.stages` is now
  `librelane.jobs`. `Stage` is `Job`, `StageRegistry` is `JobRegistry`,
  `StageError` is `JobDefinitionError`, `StageResolutionError` is
  `JobResolutionError` and `StageContractError` is `JobContractError`.
  `Registration.stage` is `Registration.job` and `STAGE_ORDER` is `JOB_ORDER`.
  No compatibility aliases are provided: a stage and
  a job were the same thing under two names, and keeping both names would
  preserve the defect.
  Under the same qualifier, `JobRegistry.register` takes `job="x"` rather than
  `stages=["x"]`, and `Registration.stages`/`Registration.spanning` are removed
  in favour of `Registration.job`. `Registration.tagged_steps`, `Resolution`
  and `ResolvedSpan` are removed with them. They existed so that a flow could
  recover which steps belonged to which job from tags attached to the step
  classes; a document's job owns its step list, so there is nothing to
  recover.
* Removed `Job.config_vars` and `Registration.requires_pdk_vars`. Both were
  empty on every shipped job and registration, so the checks reading them
  never checked anything. Provider variable portability is still enforced by
  the `namespaces` allowlist.
* A `Step` that defines `flow_control_variable` now raises `TypeError`.
  Nothing had read the attribute since 2.0, so such a step appeared to gate and
  did not. Gate it from the workflow document instead, with an `if` on the job
  that runs the step.
* A `Step` that assigns `config_vars` in its class body now raises
  `TypeError`. A nested `class Config` is the only spelling an author writes;
  `config_vars` is derived from it.
* Removed `Flow.init_with_config`, `Flow.set_max_stage_count`,
  `Flow.start_stage`, `Flow.end_stage` and `Toolbox.aggregate_metrics`. Use the
  constructor, `flow.progress_bar.*`, and `aggregate_metrics` from
  `librelane.common`. The `FlowProgressBar` methods of the same names are the
  real implementations and are unchanged.
* Removed `DesignFormat.value`, `DesignFormat.name` and `DesignFormat.by_id`.
  Use the `DesignFormat` itself, `.id`, and `DesignFormat.factory.get`.
* `librelane.common.Path` is `Annotated[pathlib.Path, ...]` rather than a
  `UserString` subclass. A value of the type is an ordinary `pathlib.Path`
  object: `isinstance(x, Path)` now raises `TypeError` instead of testing
  membership, and the `.validate()` method and `._dummy_path` class
  attribute are gone (`.exists()` keeps working -- it is `pathlib.Path`'s
  own). The sentinel is the module-level
  `DUMMY_PATH` string, existence checking is the module-level
  `validate_path` function, and spelling a path relative to a start
  directory is `rel_if_child`, all in `librelane.common.types`. Spell the
  type itself as `pathlib.Path` for both.

## Documentation

* Added {doc}`/usage/using_systemverilog`, covering `USE_SLANG`,
  `SLANG_ARGUMENTS`, and the fact that Synlig and Surelog were replaced by
  yosys-slang and that `read_systemverilog` no longer exists. The frontend was
  supported but documented nowhere, so the only way to find it was to read the
  variable list (#793).
* Added {doc}`/usage/resuming_runs`, covering what resuming a run tag reuses,
  that invalidation cascades, how a run directory is laid out, and that a tool
  upgraded in place is not detected.
* Removed the clock period from the arrival-time equations in the timing
  closure guide; arrival time is measured from the launch edge (#974).
* Finished the LVS mismatch guide and added it to the usage toctree; it was
  previously cut off mid-sentence and unreachable from any page (#326).
* Fixed the Sphinx build aborting on any module whose docstring is a single
  summary line with no body.
* Rewrote the Nix section of {doc}`/usage/writing_plugins` around
  `librelane-shell` and `librelane-plugins`, replacing the removed
  `createOpenLaneShell`/`extra-python-packages` interface.
* Rewrote the configuration sections of {doc}`/usage/writing_custom_steps`
  around nested `Config` models and attribute access, replacing the flat
  `config_vars` lists and `self.config[KEY]` reads the typed configuration
  redesign left behind.
* Added {doc}`/usage/swapping_tools`, covering the `TOOLS` configuration
  variable, a document's `uses` pin, how a flow runs two tools for one phase,
  configuration layering across several jobs at once, and the job table now
  rendered by `get_help_md`.
* Added {doc}`/usage/writing_tool_backends`, the provider-authoring reference:
  a minimal `JobRegistry.register` call, the four enforcement points
  (registration, resolution, startup time, run time), `namespaces`,
  `native_views`, and why a registration names exactly one job.
* Rewrote {doc}`/usage/writing_custom_flows` around the workflow document. It
  now opens on a document that lists steps, then on one that names job
  templates with `uses`, then on gating a job with `if`, and treats a Python
  `Flow` subclass as the escape hatch for the one thing a document cannot
  express, a decision taken during a run on data that run produced.
* Added a "Commercial CAD tool scaffolds" section to
  {doc}`/usage/writing_tool_backends`, covering the sixteen unimplemented
  vendor step scaffolds and the opt-in `librelane.jobs.providers_vendor`
  import that registers them as job providers.
* Added an "Editor support" section to {doc}`/usage/writing_custom_flows`,
  covering `librelane flow schema`, the YAML language server comment that
  points an editor at the written file, and the graph-wide checks a schema
  cannot make.
* Removed {doc}`/usage/using_ecos` and the `hold_eco_demo` example, which
  documented step substitution.
* Rewrote the "Which flows participate" section of {doc}`/usage/resuming_runs`:
  every flow LibreLane ships now participates, since the two that could not are
  removed.
* Replaced the multi-threading example in {doc}`/usage/writing_custom_flows`,
  which included the source of a now-removed flow, with an example written out
  in the page, so a future flow deletion cannot break the documentation build.
* Rewrote the "Step directory numbering" section of
  {doc}`/usage/resuming_runs` as "Step directory layout", since a run
  directory now holds one directory per job and numbers steps within their own
  job rather than across the whole run.
* Rewrote the "Conditional Execution" section of
  {doc}`/reference/configuration`, which documented a matching `pdk::`/`scl::`
  section as losing to a top-level key written below it. A section now
  overrides its own file wherever it is written, and the section states what it
  does not outrank: a later configuration file, or a command-line override.

# 3.0.4

## Steps

* `Magic.*`

  * Added `locking disable` to scripts to prevent exceeding max open file descriptor limit.

# 3.0.3

## Steps

* `OpenROAD.STA*`

  * Steps now support versions 3.0 and higher of OpenSTA, which require a
    slightly different invocation for `write_timing_model`.

* `Verilator.Lint`

  * Upgraded warnings on multiply-driven nets to an error that can be disabled
    by setting `LINTER_ERROR_ON_MULTIDRIVEN` to `false`.

* `Yosys.*Synthesis`

  * Removed unused variables `SYNTH_MUX_MAP`/`SYNTH_MUX4_MAP`.
    As a note, Yosys and ABC are able to map multiplexers to SCL cells
    without explicit technology mapping.

## Misc. Enhancements/Bugfixes

* `openlane.config`

  * Applied hack/band-aid for an issue where the default standard cell library's
    variables may clobber those of the current standard cell library because of
    `STD_CELL_LIBRARY_OPT`, a legacy OpenLane variable.

# 3.0.2

## Tool Updates

* OpenROAD: Backported
  [#9975](https://github.com/The-OpenROAD-Project/OpenROAD/pull/9975) to fix a
  bug with a certain PDK and added missing Qt plugins.

# 3.0.1

## Steps

* `Magic.DRC`

  * Set units to internal to fix DRC markers for newer magic versions.

# 3.0.0

## Steps

* `Checker.HoldViolations`

  * Changed default value of `HOLD_VIOLATION_CORNERS` to `['*']`, which will
    raise an error for hold violations on *any* corners.

* Created `Checker.KLayoutDensity`

  * Uses `klayout__density_error__count`

* Created `Checker.KLayoutAntenna`

  * Uses `klayout__antenna_error__count`

* `KLayout.DRC`

  * Added generic implementation.
  * Added support for ihp-sg13g2 and ihp-sg13cmos5l.
  * Added support for gf180mcu.
  * Renamed `.xml` to `.lyrdb`.

* `KLayout.Render`

  * Added `KLAYOUT_RENDER_GRID_VISBLE`
  * Added `KLAYOUT_RENDER_SHOW_RULER`
  * Added `KLAYOUT_RENDER_BACKGROUND_COLOR`
  * Added `KLAYOUT_RENDER_TEXT_VISIBLE`
  * Added `KLAYOUT_RENDER_RESOLUTION`
  * Added `KLAYOUT_RENDER_OVERSAMPLING`

* Created `KLayout.SealRing`

  * Added generic implementation.
  * Added gf180mcu implementation.
  * Added ihp-sg13g2/ihp-sg13cmos5l implementation.

* Created `KLayout.Filler`

  * Added generic implementation.
  * Added ihp-sg13g2/ihp-sg13cmos5l implementation.

* Created `KLayout.Density`

  * Add generic implementation.

* Created `KLayout.Antenna`

  * Add generic implementation.

* Created `KLayout.LVS`

  * Currently only supports ihp-sg13g2/ihp-sg13cmos5l.

* `Netgen.LVS`

  * Display the top-level Verilog file name.
  * Added `LVS_IGNORE_CELLS`: A list of cells to ignore in LVS.

* `KLayout.StreamOut`

  * Added `KLAYOUT_CONFLICT_RESOLUTION` which specifies the
    conflict resolution if a cell name conflict arises. (Default: "RenameCell")

    * Allowed values: "AddToCell", "OverwriteCell", "RenameCell" and "SkipNewCell"

  * Disabled GDS user property production for nets and instances.

* `Magic.*`

  * Updated scripts to annotated GDS with LEF.

* `Magic.DRC`

  * Added `MAGIC_GDS_FLATGLOB`

    * Used to flatten cells in order to prevent false positive DRC errors.

  * Made `DesignFormat.DEF` optional

  * Added `MAGIC_DRC_MAGLEFS`

    * Used to blackbox cells during DRC

* Created `Magic.Filler`

  * Added generic implementation.

* `Magic.StreamOut`

  * Added `MAGIC_GDS_MERGE` to merge tiles into polygons during gds write (Default: True).

  * Set `MAGIC_DEF_LABELS` to False by default.
  
  * Simplified get_bbox and make it more robust

* `Magic.SpiceExtraction`:

  * Added `MAGIC_EXT_UNIQUE` to replace `MAGIC_NO_EXT_UNIQUE`
  
    * Allowed values are: "all", "notopports", "noports", "none"
  
  * Load `CELL_SPICE_MODELS` to annotate stdcell port order

* `Odb.*`

  * Unified error handling with that of OpenROAD steps, i.e., dependent on the
    `[ERROR (code)]` alerts.
  * Metrics emitted from Odb steps are now also aggregated.
  * **API**: instance variable `.alerts` now holds emitted alerts until the next
    `start()`, similar to `.state_out`.

* `Odb.AddPDNObstructions`, `Odb.AddRoutingObstructions`

  * `PDN_OBSTRUCTIONS` and `ROUTING_OBSTRUCTIONS` are now lists of tuples
    instead of variable-length Tcl-style lists (AKA: strings).
  * **Internal**: Unified exit codes.

* `Odb.CustomIOPlacement`

  * All variables prefixed `FP_IO_` have been renamed, now prefixed `IO_PIN_`.

* `Odb.DiodesOnPorts`, `Odb.PortDiodePlacement`

  * Steps no longer assume `DIODE_CELL` exists and fall back to doing nothing.

* `Odb.FuzzyDiodePlacement`, `Odb.HeuristicDiodeInsertion`

  * Steps no longer assume `DIODE_CELL` exists and fall back to doing nothing.

  * `HEURISTIC_ANTENNA_THRESHOLD` has been made optional, steps do nothing if it
    is unset.

* `Odb.InsertECOBuffer`, `Odb.InsertECODiode`

  * Steps now work with hierarchical netlists.

  * Steps are skipped if `INSERT_ECO_BUFFERS` or `INSERT_ECO_DIODES` is
    undefined.

* `OpenROAD.*`

  * Added `PNR_CORNERS` which defaults to `STA_CORNERS`. An override for
    `DEFAULT_CORNER` for PnR steps except those with more specific overrides
    e.g. `RSZ_CORNERS`, `CTS_CORNERS`.

  * Added `LAYERS_RC`, `VIAS_R`: Unlike OpenLane 1.0.0 variables with similar
    names, these are mappings from corners to layer/via RC values.

  * Previously, for resizer steps, corners that end up with the same set of lib
    files and RC values would be culled to reduce runtime. Now, for all steps,
    this behavior is gated by `DEDUPLICATE_CORNERS`, which is `False` by
    default. **This may increase flow runtimes**. In general, it is safe to turn
    this on, however it may be surprising behavior.

    * Just like previously, however, STA steps are unaffected and will always
      run across all corners.

  * Added `SET_RC_VERBOSE`, which (very noisily) logs set-RC-related commands to
    logs.

  * Added `log_cmd` from OpenROAD-flow-scripts -- neat idea for consistency

  * Lib files are now *always* read BEFORE reading database files.

  * **API**: instance variable `.alerts` now holds emitted alerts until the next
    `start()`, similar to `.state_out`.

  * **Internal**: Steps now sensitive to `_OPENROAD_GUI` environment variable --
    coupled with `--only`, it runs a step in OpenROAD then doesn't quit so you
    may inspect the result.

    * This is not part of the OpenLane stable API and may be broken at any
      moment.

  * **Internal**: New convenience methods to append flags to calls based on
    environment variables

  * Better error reporting for unexpected openroad failures.

* `OpenROAD.CTS`

  * Added flags `CTS_OBSTRUCTION_AWARE` and `CTS_BALANCE_LEVELS`
  * Added `CTS_SINK_BUFFER_MAX_CAP_DERATE_PCT`
  * Added `CTS_DELAY_BUFFER_DERATE_PCT`
  * `CTS_CLK_BUFFERS` can now take wildcards.
  * Added `CTS_SINK_CLUSTERING_ENABLE` to control sink clustering (default is
    enabled).
  * Made `CTS_SINK_CLUSTERING_SIZE` and `CTS_SINK_CLUSTERING_MAX_DIAMETER`
    optional. OpenROAD determines the best values.
  * Added `CTS_MACRO_CLUSTERING_SIZE` and `CTS_MACRO_CLUSTERING_MAX_DIAMETER`.
  * Added `CTS_APPLY_NDR` to set the non-default rule strategy.

* `OpenROAD.CutRows`

  * Added `FP_PRUNE_THRESHOLD` to prune rows not meeting the threshold after
    cutting.

* `OpenROAD.DetailedRouting`

  * Added `DRT_SAVE_SNAPSHOTS` which enables saving snapshots of the layout each
    detalied routing iteration.
  * Added `DRT_SAVE_DRC_REPORT_ITERS`
  * Added `DRT_ANTENNA_REPAIR_ITERS`, which, if greater than zero and
    `DIODE_CELL` is set, enables antenna fixing after detailed routing
  * Added `DRT_ANTENNA_REPAIR_MARGIN` which is similar to
    `GRT_ANTENNA_REPAIR_MARGIN` but for the aforementioned antenna repair
    iterations
  * DRC reports are now converted to `xml` and readable by KLayout
  * Removed `DRT_MIN_LAYER` and `DRT_MAX_LAYER` due to an update in OpenROAD.
    `RT_MIN_LAYER`/`RT_MAX_LAYER`/`RT_CLOCK_MIN_LAYER`/`RT_CLOCK_MAX_LAYER` is
    considered instead.
  * Added `DRT_ANTENNA_REPAIR_JUMPER_ONLY`.
  * Added `DRT_ANTENNA_REPAIR_DIODE_ONLY`.
  * Added `NON_DEFAULT_RULES` to specify non-default rules.
  * Added `DRT_ASSIGN_NDR` to assign nets to non-default rules.

* Created `OpenROAD.DumpRCValues`

  * Creates three reports to help verify that the RC values used for estimation
    are set correctly.

* `OpenROAD.Floorplan`

  * Added `FP_FLIP_SITES`: allows sites in floorplans to be flipped. Useful in
    niche alignment scenarios where single-height cells have ground at the south
    side and double-height cells have power at the south side, causing a short.
    In that situation, flipping the sites for single-height cells resolves the
    issue.

  * Make fake I/O sites if `PAD_FAKE_SITES` exists.

* `OpenROAD.GeneratePDN`

  * All variables prefixed `FP_PDN_` have been renamed to be prefixed simply
    `PDN`. Backwards compatibility wrapper code has been added for `PDN_CFG`
    files.

  * Added `PDN_EXTEND_TO` with values "core_ring" and "boundary" (default:
    "core_ring").

  * Added `PDN_CORE_RING_CONNECT_TO_PADS` to connect the core ring to the pads.

  * Added `PDN_CORE_RING_ALLOW_OUT_OF_DIE` (default: True).

  * Added `PDN_CORE_HORIZONTAL_LAYER` and `PDN_CORE_VERTICAL_LAYER`.

  * Added `PDN_ENABLE_PINS` (default: True) since padrings have pins on their
    bondpads.

* `OpenROAD.GlobalPlacement`

  * Added optional variable `PL_ROUTABILITY_MAX_DENSITY_PCT`

  * Added optional variable `PL_KEEP_RESIZE_BELOW_OVERFLOW`

  * Corrected `GPL_CELL_PADDING` to be an integer.

  * Enabled `dont_touch` around GPL as it does not prevent cell placement.

  * Renamed `PL_TIME_DRIVEN` to `PL_TIMING_DRIVEN`.

* `OpenROAD.IOPlacement`

  * Added optional variable `IO_EXCLUDE_PIN_REGION`.

  * Added validator to deprecate `random_equidistant` of
    `IO_PIN_PLACEMENT_MODE`.

  * Added optional variable `IO_PIN_CORNER_AVOIDANCE`.

  * Added optional variable `IO_PIN_MIN_DISTANCE_IN_TRACKS`.

* Created `OpenROAD.PadRing`

  * Added `PAD_*` PDK variables for the default pad config.

  * Added `PAD_CFG` to override the default pad config (`pad_cfg.tcl`).

  * Added `PAD_SOUTH`/`PAD_EAST`/`PAD_NORTH`/`PAD_WEST` to specify the placement of the pad cells.

* `OpenROAD.RepairAntennas`

  * Step no longer assumes `DIODE_CELL` exists and falls back to doing nothing.

  * Renamed `GRT_ANTENNA_ITERS` to `GRT_ANTENNA_REPAIR_ITERS`.

  * Renamed `GRT_ANTENNA_MARGIN` to `GRT_ANTENNA_REPAIR_MARGIN`.

  * Added `GRT_ANTENNA_REPAIR_JUMPER_ONLY`.

  * Added `GRT_ANTENNA_REPAIR_DIODE_ONLY`.

* `OpenROAD.RepairDesignPostGPL`

  * Added optional variable `DESIGN_REPAIR_MAX_UTIL_PCT`

* `OpenROAD.ResizerTimingPostCTS`

  * Renamed `PL_RESIZER_GATE_CLONING` to `PL_RESIZER_SETUP_GATE_CLONING`

  * Fixed `PL_RESIZER_SETUP_GATE_CLONING` incorrectly applied to hold fixing

  * Added the following optional variables

    * `PL_RESIZER_SETUP_BUFFERING`
    * `PL_RESIZER_SETUP_BUFFER_REMOVAL`
    * `PL_RESIZER_SETUP_REPAIR_TNS_PCT`
    * `PL_RESIZER_SETUP_MAX_UTIL_PCT`
    * `PL_RESIZER_HOLD_REPAIR_TNS_PCT`
    * `PL_RESIZER_HOLD_MAX_UTIL_PCT`

* `OpenROAD.RepairDesignPostGRT`

  * Renamed `GRT_RESIZER_GATE_CLONING` to `GRT_RESIZER_SETUP_GATE_CLONING`

  * Fixed `GRT_RESIZER_SETUP_GATE_CLONING` incorrectly applied to hold fixing

  * Added the following optional variables

    * `GRT_RESIZER_SETUP_BUFFERING`
    * `GRT_RESIZER_SETUP_BUFFER_REMOVAL`
    * `GRT_RESIZER_SETUP_REPAIR_TNS_PCT`
    * `GRT_RESIZER_SETUP_MAX_UTIL_PCT`
    * `GRT_RESIZER_HOLD_REPAIR_TNS_PCT`
    * `GRT_RESIZER_HOLD_MAX_UTIL_PCT`

* `OpenROAD.TapDecapInsertion`

  * No longer assumes `WELLTAP_CELL` has a value and skips tap insertion if not.
  * No longer assumes `DECAP_CELL` has a value and skips decap insertion if not.

* Created `OpenROAD.UnplaceAll`

  * Removes the placement status of all instances.

* Created `OpenROAD.WriteCDL`

  * Writes the CDL netlists for a database.

* `Verilator.Lint`

  * Added `LINTER_DISABLE_WARNINGS` to disable linter warnings.

  * Added `LINTER_DISABLE_WARNINGS_BLACKBOX` to disable linter warnings for
    blackbox modules.

  * Added `LINTER_VLT` as a user defined Verilator Configuration format file
    (`.vlt`).

  * Verilator now creates a `_waivers_output.vlt` file based on the encountered
    linter warnings.

* `Yosys.*Synthesis`

  * Added `SYNTH_CORNER`: a step-specific override for `DEFAULT_CORNER`.

  * Added `SYNTH_NORMALIZE_SINGLE_BIT_VECTORS`: `true` by default, it converts
    vectors with the shape `[0:0]` to normal wires for backwards compatibility
    with older designs. See https://github.com/YosysHQ/yosys/pull/5095 for more
    info.

  * Folded `SYNTH_ELABORATE_FLATTEN` into `SYNTH_HIERARCHY_MODE` with new
    translation behavior, i.e.

    * `SYNTH_ELABORATE_FLATTEN` is true: set to `flatten`

    * `SYNTH_ELABORATE_FLATTEN` is false: set to `keep`

  * Integrated new `clockgate` command

    * Replaces Lighter: `USE_LIGHTER` now translates to the new variable
      `SYNTH_CLOCKGATE_MIN_WIDTH` which can be an integer value for a certain
      width of flip-flops to convert to clockgates or `None` to disable
      clock-gating entirely.

  * Added two new PDK variables: `SYNTH_CLOCKGATE_{POS,NEG}EDGE_ICG`: used to
    identify appropriate ICG

    * Removed `LIGHTER_DFF_MAP`: tangentially related to above

* `Yosys.Synthesis`

  * Graphviz DOT file generation, which frequently fails and brings down the
    entire process, is now dependent on the variable `SYNTH_SHOW` and is
    disabled by default

  * `synlig` has been replaced by `yosys-slang` as the alternative frontend for
    superior SystemVerilog support.

    * Added `SLANG_ARGUMENTS`, which is used to pass arguments to the Slang
      frontend at the user's own risk.

    * `USE_SYNLIG` deprecated and replaced with `USE_SLANG`.

  * Added variables to keep the hierarchy during flattening.

    * `SYNTH_KEEP_HIERARCHY_MIN_COST`: Sets the `keep_hierarchy` attribute on
      modules where the gate count is estimated to exceed the specified
      threshold. This prevents larger modules from being flattened.

    * `SYNTH_KEEP_HIERARCHY_INSTANCES`: A list of instances for which to set the
      `keep_hierarchy` attribute.

    * `SYNTH_KEEP_HIERARCHY_MODULES`: A list of modules for which to set the
      `keep_hierarchy` attribute.

* Created `Magic.RCX`

  * Performs full post-layout parasitics extraction using Magic

## Flows

* Classic

  * Added `OpenROAD.DumpRCValues` immediately after floorplanning.
  * Added `KLayout.Render` after both stream-out steps.

* Created "Chip" flow

  * Added `OpenROAD.PadRing` for pad ring generation.
  * Added new KLayout steps (filler, density etc.).
  * Removed `Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties`.

## Tool Updates

* Python requirement bumped up to ≥3.10
  * Does not affect Nix users where Python 3.12 is used anyway.
* Updated nix-eda to 6.11.0
  * Updated nixpkgs to nixos-25.11 (@ `b3aad46`)
  * Updated KLayout to `0.30.7`
    * Added a patch for fixing a performance regression
  * Updated Magic to `8.3.623`
  * Updated Netgen to `1.5.316`
  * Updated Yosys to `0.62`
    * Replaced Synlig with [Slang](https://github.com/povik/yosys-slang)
  * Updated Verilator to `5.044`
* Updated OpenROAD to `dcf36133`
* Updated OpenSTA to `857316ff`
  * Added a patch for fixing cell delays in certain situations
* Nix
  * `librelane` derivation:
    * Added new arguments `yosys-plugin-set` and `extra-yosys-plugins`
    * Added new argument `extra-python-interpreter-packages` for Python
      interpreters built into tools e.g. yosys, openroad, takes a lambda similar
      to `python.withPackages` (click and pyyaml will always be included)
  * `createOpenLaneShell` has been reworked into `pkgs.librelane-shell`,
    which is a derivation supporting `.override` in comparison to
    `createOpenLaneShell` which is a function returning a function that creates
    a derivation:
    ```nix
    # before (librelane 2.4)
    devShells.x86_64-linux.default = pkgs.callPackage (librelane.createOpenLaneShell {
      extra-packages = with pkgs; [quaigh python3.pkgs.nl2bench];
      extra-python-packages = with pkgs.python3.pkgs; [bitarray marshmallow-dataclass];
      librelane-plugins = with pkgs.python3.pkgs; [librelane-plugin-difetto];
    }) {};
    # now
    devShells.x86_64-linux.default = pkgs.librelane-shell.override {
      extra-packages = with pkgs; [quaigh python3.pkgs.nl2bench];
      librelane-extra-python-interpreter-packages = ps: with ps; [bitarray marshmallow-dataclass];
      librelane-plugins = ps: with ps; [librelane-plugin-difetto];
    };
    ```
      * `extra-python-packages` and `librelane-plugins` now take a lambda like
        `python.withPackages`
      * Added new arguments `librelane-extra-python-interpreter-packages` and
        `librelane-extra-yosys-plugins`, which overrides the two relevant
        arguments in the `librelane` derivation used by this shell.

## Testing

* Custom pytest `--step-rx` option replaced with a proper pytest marker,
  `step_impl_tests`.
  * Default option uses the marker `no step_impl_tests`, i.e., all other tests.
  * To run all tests, pass `-m all`.

* Step implementation tests now load the PDK configs first before overriding
  them. This has a minor performance penalty compared to the previous "raw"
  load, but allows unit tests to be updated less frequently (especially to work
  with new PDK variables.)

## Misc. Enhancements/Bugfixes

- Added `--pad` and `PAD_CELL_LIBRARY` variable to load the pad configuration

* `CLI`

  * Multiple initial state JSON files can now be provided which are combined to
    form the initial state for the flow.

  * Paths provided over the terminal that start with a tilde are now rejected
    and result in an error, as they typically mean POSIX shell tilde expansion
    has failed. This is a compromise solution as tilde expansion within
    LibreLane itself would be POSIX-ly incorrect, yet, many users pass quoted
    tildes and then are surprised when it doesn't work.
    * Relative paths that start with a genuine tilde must be provided as
      absolute paths.

* `librelane.common`

  * `_eval_env`: Add support for nested dicts in tcl

  * `Path`: Add support for `write_text` and `read_text`

* `librelane.flows`

  * `SequentialFlow`
    * Substitutions are now to be strictly consumed by the subclass initializer,
      i.e., it can no longer be done on the object-level and only on the class
      level. Additionally, it can provided as a list of tuples instead of a
      dictionary so the same key may be reused multiple times.
    * Step IDs are re-normalized after every substitution, so a substitution for
      `OpenROAD.DetailedPlacement-1` for example would always refer to the
      second `OpenROAD.DetailedPlacement` AFTER applying all previous
      substitutions, instead of the second "original"
      `OpenROAD.DetailedPlacement` in the flow.

* `librelane.config`

  * `meta.substituting_steps` now only apply to the sequential flow declared in
    `meta.flow` and not all flows.

  * `pdk_compat` set some compatibility values only if necessary.

  * `refg::`, `dir::`, `pdk_dir::` now support globs outside the PDK directory
    and the config directory.

* `librelane.state`

  * `DesignFormat`
    * Now a dataclass encapsulating the information about the DesignFormat
      directly.
    * `.factory` is a factory for retrieval of DesignFormats by ID
      * `DesignFormats` may be registered to the factory using `.register()`
      * Registrations for previously included `DesignFormat`s now moved to
        appropriate files.
        * Renamed `POWERED_NETLIST_NO_PHYSICAL_CELLS` to
          `LOGICAL_POWERED_NETLIST`
        * Renamed `POWERED_NETLIST_SDF_FRIENDLY` to
          `SDF_FRIENDLY_POWERED_NETLIST`
  * `State`
    * States initialized with keys that have values that are `None` now remove
      said keys.

* `librelane.steps`

  * `TclStep`
    * All `Decimal` values are now passed to Tcl in exponent notation.

  * `PyosysStep`, `OdbpyStep`
    * LibreLane's `scripts/{pyosys,odbpy}` directory is now always suffixed to
      `PYTHONPATH` so external steps can import `ys_common` or `reader`
      respectively.

* `librelane.config`

  * Moved a number of global variables:
    * `WIRE_LENGTH_THRESHOLD` moved from global variables to
      `Checker.WireLength`
    * `GPIO_PAD_*` removed- no step currently uses them
    * `FP_TRACKS_INFO`, `FP_TAPCELL_DIST` moved to relevant steps
    * `FP_IO_HLAYER` and `FP_IO_VLAYER` renamed to `IO_PIN_{H,V}_LAYER` and
      moved to relevant steps
    * `FILL_CELL` and `DECAP_CELL` renamed to `FILL_CELLS` and `DECAP_CELLS` as
      they are both lists
    * `EXTRA_GDS_FILES` and `FALLBACK_SDC_FILE` renamed to `EXTRA_GDS` and
      `FALLBACK_SDC`: information can be obtained from their typing
  * Changed some `decimal.Decimal` initializations to use integers or strings
    instead of floats.

* Store hashes for each PDK family separately

  * Renamed `open_pdks_rev` to `pdk_hashes.yaml`
  * Add hash for ihp-sg13g2
  * Rename `PDK_ihp-sg13g2` define to `PDK_ihp_sg13g2`
  * Metrics: split `pdk-scl-design_name` triple from the right, since ihp-sg13g2
    contains a `-`

* validators: A customizable validator that is run AFTER type checks and
  conversions.

* global connections: due to an update in OpenROAD, global connections are not
  overriden by default. To match the old behavior as much as possible we now
  create the `PDN_MACRO_CONNECTIONS` before the SCL connections.

* `from_magic_feedback`

  * Added "-" to wordchars so that a string like "box 369787 -1 369789 1" would be correctly split.

## API Breaks

* `CLI`

  * `openlane` alias for entry point no longer exists, please use `librelane`.

  * Paths provided over the terminal that start with a tilde are now rejected
    and result in an error, as they typically mean POSIX shell tilde expansion
    has failed. This is a compromise solution as tilde expansion within
    LibreLane itself would be POSIX-ly incorrect, yet, many users pass quoted
    tildes and then are surprised when it doesn't work.

    * Relative paths that start with a genuine tilde must be provided as
      absolute paths.

* All Steps

  * `{GPL,DPL}_CELL_PADDING`, `PL_MAX_DISPLACEMENT_{X,Y}` now all integers to
    match OpenROAD.
  * `WELLTAP_CELL`, `DECAP_CELL` now optional.

* `Checker.HoldViolations`

  * `HOLD_VIOLATION_CORNERS` now defaulting to all corners will require designs
    that have hold violations at non-typical corners to set its value explicitly
    to `["*tt*"]`.

* `CVCRV.ERC`

  * Removed non-functional step.

* `KLayout.StreamOut` now behaves differently as the default for cell conflict
  resolution has been changed from "AddToCell" to "RenameCell", which is a
  safer.

  * To retain the old behavior, set `KLAYOUT_CONFLICT_RESOLUTION` to
    "AddToCell".
  * It may be necessary to set `KLAYOUT_CONFLICT_RESOLUTION` to "SkipNewCell" to
    match the old macro integration behavior of magic.

* `Magic.StreamOut`

  * `MAGIC_DEF_LABELS` now defaulting to False.

* `Odb.AddRoutingObstructions`, `Odb.AddPDNObstructions`

  * Typing for representation of obstructions has been changed. Designs with a
    meta version of 2 or higher must update their variables from strings to
    tuples.

* `OpenROAD.*`

  * `LAYERS_RC` now uses a new format. Refer to the documentation for a
    description of the new format.
  * `VIAS_RC` removed and replaced by `VIAS_R` with a format similar to
    `LAYERS_RC`.
  * `FP_DEF_TEMPLATE` no longer a variable for all OpenROAD steps and must be
    added to steps that need it.

* `OpenROAD.BasicMacroPlacement`

  * Removed non-functional step.

* `OpenROAD.GeneratePDN`

  * `FP_PDN_CFG`: `add_pdn_ring` calls may require `-allow_out_of_die` as an
    escape hatch for rings that are created outside the die area: See
    https://github.com/The-OpenROAD-Project/OpenROAD/issues/6445

* `Yosys.Synthesis*`

  * `.dot` views of the design are no longer generated by default. You will need
    to set `SYNTH_SHOW` to `true` to recover the previous behavior.

* `openlane.flows`

  * Step IDs are re-normalized after every substitution, so a substitution for
    `OpenROAD.DetailedPlacement-1` for example would always refer to the second
    `OpenROAD.DetailedPlacement` AFTER applying all previous substitutions,
    instead of the second "original" `OpenROAD.DetailedPlacement` in the flow.

* `openlane.steps`

  * `TclStep` now uses the IDs uppercased for `CURRENT_` and `SAVE_`.

  * `OdbpyStep`: `scripts/odbpy` is now suffixed instead of prefixed.

* `openlane.state`

  * `State` no longer includes all `DesignFormat`s as guaranteed keys and `.get`
    must be used to avoide `KeyErrors`
  * `DesignFormat` is no longer an enumeration and is not iterable. However, to
    avoid massive codebase changes, you can still access `DesignFormat`s
    registered to the factory using the dot notation (e.g.
    `DesignFormat.NETLIST`), using either their `id` or any of their `alts`.
  * Removed `DesignFormatObject`: the DesignFormat class itself is now a
    dataclass incorporating these fields, except `name`, which has been renamed
    to `full_name`. The enumeration's name has been added to `alts`, while
    `.name` is now an alias for `.id`.

* `openlane.config`

  * `meta.substituting_steps` now only apply to the sequential flow declared in
    `meta.flow` and not all flows.

  * PDK/SCL variables `WIRE_LENGTH_THRESHOLD`, `GPIO_PAD_*`, `FP_TRACKS_INFO`,
    `FP_TAPCELL_DIST`, `FP_IO_HLAYER`, `FP_IO_VLAYER`, `SIGNAL_WIRE_RC_LAYERS`,
    and `CLOCK_WIRE_RC_LAYERS` are no longer global variables and have been
    moved to relevant steps.

  * Global SCL variable `VDD_PIN_VOLTAGE` has been removed.

  * `FILL_CELL`, `DECAP_CELL`, `EXTRA_GDS_FILES`, `FALLBACK_SDC_FILE` were all
    renamed, see Misc. Enhancements/Bugfixes.

* `openlane.common.drc`

  * `BoundingBox` changed from `Tuple` to `dataclass` with additional optional
    `info` property.

* Nix

  * `createOpenLaneShell` has been reworked into `pkgs.librelane-shell`,
    which is a derivation supporting `.override` in comparison to
    `createOpenLaneShell` which is a function returning a function that creates
    a derivation. See Tool Updates for more information on usage.


## Documentation

* Variable types now link to dataclasses' API reference as appropriate.

# 2.4.13

## Misc. Enhancements/Bugfixes

* Fix loading states if a DesignFormat is a list.

# 2.4.12

## Steps

* `Yosys.VHDLSynthesis`

  * Added `GHDL_ARGUMENTS` to provide arguments to ghdl-yosys, such as `--std=08`.

# 2.4.11

## Steps

* `Yosys.*Synthesis`

  * Removed misleading nonfunctional clock delay propagation to ABC scripts
    pending further investigations.

## Misc. Enhancements/Bugfixes

* Fixed copyright information.

# 2.4.10

## Misc. Enhancements/Bugfixes

* Fixed `common/cli.py` and `pyproject.toml` so click versions 8.2 and higher
  are supported.

# 2.4.9

## Steps

* `KLayout.OpenGUI`

  * Fixed the technology not being registered.

# 2.4.8

## Misc. Enhancements/Bugfixes

* Changed `strip()` on subprocess logs to `rstrip()` to prevent misformatting of
  tables and other elements.

# 2.4.7

## Documentation

* Configuration variables now list deprecated names in a collapsible in the same
  cell as the variable name.
* Configuration variable tables now omit the units if all configuration
  variables lack a unit, to save horizontal real estate.

# 2.4.6

## Misc. Enhancements/Bugfixes

* Fixed an issue where the "-" operand in an `expr::` would perform addition
  instead of subtraction.

# 2.4.5

## Testing

* Added AppImage generation using `nix bundle`. Releases are now created for
  every new tag with the AppImages included as release assets.

## Documentation

* Fixed typos in the ECO guide.

# 2.4.4

## Steps

* `Checker.*`

  * Dynamic docstring now actually assigned in `__init_subclass__` and is not
    exclusive to `.get_help_md()`.

* `OpenROAD.*`

  * Fixed a number of double-represented variables.

## Misc. Enhancements/Bugfixes

* `tkinter` no longer required for any operations that do not require evaluating
  Tcl. Useful for being able to run things like `librelane --version` without
  the entire tool crashing.
* Fixed missing docstrings for a number of steps used in the flow.
* Fixed a crash when a plugin is missing `__version__` at the top level.

## Documentation

* Moved installation into its own separate section.
* Codified API stability policy.
* Updated Contributor's Guide with information about access control and code
  ownership policy.
* Updated `make docs` to only install dependencies if inside a venv.
* Fixed all broken links.
* Replaced nodemon with pymon.
* Added a number of terms to the glossary.

# 2.4.3

## Steps

* `Odb.ApplyDEFTemplate`

  * Fixed a crash when `FP_TEMPLATE_COPY_POWER_PINS` is set to `True` and one or
    more power pin block terminals already exist.

## Misc. Enhancements/Bugfixes

* Updated all flakes to drop usage of URL literals to fix support for Lix, the
  community fork of Nix.
* Fixed an inelegant stack dump when Ciel fails to fetch a PDK and added a small
  warning for `ihp-sg13g2` users to encourage them to switch to the `dev`
  branch.

## Documentation

* Added `--prefer-upstream-nix` to Nix installation steps for now: see
  https://determinate.systems/blog/installer-dropping-upstream/
* Synchronization for step indices in the newcomers' guide (Thanks
  [@Essencia](https://github.com/essencia))

# 2.4.2

## Documentation

* Added VHDL usage guide by [@mole99](https://github.com/mole99)
* Fixed invalid path in PDK porting guide
* Fixed documentation for `FP_IO_{V,H}_LAYER`
* Various updates to the FAQ
* Various docstring formatting fixes

# 2.4.1

## Misc. Enhancements/Bugfixes

* Replaced libparse with a fork maintained by the LibreLane team to fix
  LibreLane not being installable on Python 3.13.

# 2.4.0: Hello, LibreLane

2.4.0 is the first version of LibreLane, a fork of the OpenLane 2 by its
original authors after Efabless Corporation has ceased operations.

## Steps

* `Odb.*`

  * Unified error handling with that of OpenROAD steps, i.e., dependent on the
    `[ERROR (code)]` alerts.
  * Metrics emitted from Odb steps are now also aggregated.
  * **API**: instance variable `.alerts` now holds emitted alerts until the next
    `start()`, similar to `.state_out`.

* Created `Odb.InsertECOBuffer`, `Odb.InsertECODiode`

  * New ECO steps using the variables `INSERT_ECO_BUFFERS` and
    `INSERT_ECO_DIODES` respectively to allow creation of buffers and diodes
    after (and only after global routing,) with an option to run it after
    detailed routing so long as detailed routing is run again afterwards.

* `Magic.*`

  * Unified exits in wrapper.

* `Magic.SpiceExtraction`

  * Added new variable `MAGIC_FEEDBACK_CONVERSION_THRESHOLD`: the number of
    overlap errors that can be in a single feedback file before the step no
    longer attempts to compile it into a KLayout database.

* `OpenROAD.*`

  * **API**: instance variable `.alerts` now holds emitted alerts until the next
    `start()`, similar to `.state_out`.

* `OpenROAD.STAPostPNR`

  * `DesignFormat.ODB` input is now optional. If the input state is missing
    `DesignFormat.ODB`, unannotated net metrics will not be generated.

* `OpenROAD.OpenGUI`

  * The LIBs are now loaded by default and the top-level SPEF if available.

## Documentation

* Variable types now link to dataclasses' API reference as appropriate.

## Tool Updates

* Volare replaced by [Ciel](https://github.com/fossi-foundation/ciel)@2.0.1
* nix-eda replaced by the
  [FOSSi Foundation fork](https://github.com/fossi-foundation/nix-eda)@2.1.3
* OpenLane Cachix replaced by an S3-based cache hosted at
  https://nix-cache.fossi-foundation.org

## Misc. Enhancements/Bugfixes

* `CLI`

  * New command, `librelane.help` that can be supplied with the ID of either a
    flow or step and it prints the full markdown help for the flow or step in
    the terminal.

  * Various fixes to `--ef-save-views-to` to better align with the Caravel User
    Project format: SDFs now save in the right spot and reports are saved
    correctly.

* `librelane.config.Variable`

  * Variables of type `List[Path]` now flatten lists of lists so multiple globs
    may be used within the same configuration variable.

* `librelane.state`

  * `DesignFormat`

    * Added new dynamic property `.value.optional` which cannot be defined for
      new enum members and always returns `False`.
    * Added new method `.mkOptional()` which creates an ephemeral copy of the
      DesignFormat where `.value.optional` returns `True`.

  * `State`

    * Added new method `.metrics_to_csv()` which uses `csv.writer` to dump
      metrics.
    * `.save_snapshot()` now uses `.metrics_to_csv()` internally instead of
      primitive for-loop.

* `librelane.flows.Flow`

  * Added `.display_help()` for consistency with steps.
  * Fixed `.get_help_md()` including MyST anchors even for renderers that do not
    support them, only doing so now if the keyword argument `myst_anchors` is
    set to `True`.

* `librelane.steps.Step`

  * DesignFormats where `.value.optional` is True (i.e. copied with mkOptional)
    no longer cause a `StepException` to be raised if missing from inputs.
  * `display_help` now renders the markdown help with rich in a non-notebook
    environment instead of raising an error.
  * Fixed `.get_help_md()` including MyST anchors even for renderers that do not
    support them, only doing so now if the keyword argument `myst_anchors` is
    set to `True`.
  * Note: Currently, all outputs are technically optional anyway. This will
    change in 3.0.0.

* `librelane.common.ScopedFile`

  * Fixed crash associated with `__del__` when ScopedFile is declared at the
    top-level.

* Enhanced resilience against permission issues with containerized setups.

  * Temporary directories are no longer mounted.

  * Docker and Podman are both tested in CI.

* Worked around an issue with Google Colaboratory where if `PATH` is set,
  Yosys's Python `sitepackages` are replaced with the global ones and everything
  breaks.

* Replaced `functools.reduce` with the C-optimized built-ins wherever possible.

# 2.3.10

## Steps

* `Yosys.Synthesis`
  * `SYNTH_ELABORATE_FLATTEN` now passes the `-noscopeinfo` flag so scopeinfo
    cells are no longer emitted from Synthesis.

# 2.3.9

## Tool Updates

* Backported https://github.com/The-OpenROAD-Project/OpenROAD/pull/6743 to
  OpenROAD to fix GUI crashes on C++ standard libraries that are not libstdc++
  (aka: macOS.)

# 2.3.8

## Misc. Enhancements/Bugfixes

* Fixed substitutions in `config.json` being applied to all flows. It now only
  applies to the flow in meta.flow (which falls back to `Classic` if it's null.)

# 2.3.7

## Tool Updates

* Updated Docker requirement to tested version: 27.3.1
  * Added warning when Docker version is out of date.

## Documentation

* Updated documentation to reflect tested Docker version.
* Updated documentation to stop using a branch of the DetSys Nix Installer.

# 2.3.6

## Steps

* `Verilator.Lint`
  * Fixed missing `VERILOG_INCLUDE_DIRS` variable, which would cause designs
    that synthesize correctly to otherwise fail linting.

# 2.3.5

## Tool Updates

* `nix-eda` updated to 2.1.2
  * Pulls in a Python overlay fix and a fix for `gdstk`.

# 2.3.4

## Tool Updates

* Added patch to Yosys to resolve an early return issue that broke non-const
  asynchronous resets. See https://github.com/YosysHQ/yosys/issues/4712 for more
  info.

# 2.3.3

## Steps

* `OpenROAD.Floorplan`

  * Fixed an issue in `FP_SIZING`: `absolute` mode where if the die area's x0 >
    x1 or y0 > y1, the computed core area would no longer fit in the die area.
    Not that we recommend you ever do that, but technically OpenROAD allows it.

# 2.3.2

## Steps

* `Yosys.*`
  * Fixed blackbox Verilog and lib models causing a crash if they are gzipped
    and/or have the extension `.gz`.

## Tool Updates

* Relaxed requirement on `httpx` to include `0.28.X`, which has no removals
  compared to `0.27.0`.

## Documentation

* Clarified support for gzipped files in the Classic flow.

# 2.3.1

## Tool Updates

* KLayout now compiled with `-qt-binding`, which increases distribution size but
  allows for more features.

# 2.3.0

## Steps

* `OpenROAD.GlobalPlacement`

  * Exposed `-routability_check_overflow` argument as new variable
    `PL_ROUTABILITY_OVERFLOW_THRESHOLD`.

* `Yosys.*Synthesis`

  * Created new variable `SYNTH_HIERARCHY_MODE`, replacing `SYNTH_NO_FLAT`.
    There are three options, `flatten`, `deferred_flatten` and `keep`. The first
    two correspond to `SYNTH_NO_FLAT` being false and true respectively. The
    third keeps the hierarchy in the final netlist.
  * Created new variable `SYNTH_TIE_UNDEFINED` to customize whether undefined
    and undriven values are tied low, high, or left as-is.
  * Created new variable `SYNTH_WRITE_NOATTR` to allow attributes to be
    propagated to the final netlist.

* Created `Yosys.Resynthesis`

  * Like `Yosys.Synthesis`, but uses the current input state netlist as an input
    instead of RTL files

## CLI

* Added new option: `-e`/`--initial-state-element-override`: allows an element
  in the initial state to be overridden straight from the commandline.

# 2.2.9

## Steps

* `Yosys.JsonHeader`, `Yosys.Synthesis`

  * Fixed `VERILOG_INCLUDE_DIRS` being a list of strings instead of a list of
    `Path`s.

# 2.2.8

## Steps

* `Checker.*Violations`

  * Changed `TIMING_VIOLATION_CORNERS` to a PDK variable to avoid breaking PDKs
    without `tt` in corner names.

# 2.2.7

## Steps

* `OpenROAD.WriteViews`

  * Fixed step not being registered to factory object.

# 2.2.6

## Steps

* `OpenROAD.ResizerTimingPostGRT`

  * Fixed `GRT_RESIZER_GATE_CLONING` incorrectly applied to hold fixing instead
    of setup fixing.

* `OpenROAD.ResizerTimingPostCTS`

  * Fixed `PL_RESIZER_GATE_CLONING` incorrectly applied to hold fixing instead
    of setup fixing.

# 2.2.5

## Steps

* `Yosys.JsonHeader`, `Verilator.Lint`, `Odb.WriteVerilogHeader`

  * Fixed `VERILOG_POWER_DEFINE` not being optional which was an unintentional
    break from OpenLane 1.

    * Default value is still `USE_POWER_PINS`, but it can be explicitly unset.

## Misc. Enhancements/Bugfixes

* `openlane.config`: Fixed issue where preprocessor would ignore explicitly-set
  null values in configuration files.

# 2.2.4

## Tool Updates

* `yosys-sby`: Overlaid new hash for `yosys-0.46` tag because of a tag update
  upstream.

# 2.2.3

## Misc. Enhancements/Bugfixes

* Fixed incorrect error message when subtituting a step with one that has a
  nonexistent ID.

# 2.2.2

## Steps

* `Odb.*`

  * Fixed OpenROAD dropping user-set `PYTHONPATH` values.

## Tool Updates

* Use `NIX_PYTHONPATH` instead of `PYTHONPATH` in Docker and devshells to avoid
  collisions with user-set `PYTHONPATH` variables.

# 2.2.1

This patch has no functional changes to OpenLane proper.

## Tool Updates

* `flake.createOpenLaneShell` now gets OpenLane from `python3.pkgs`.
* Fixed issue with `flake.createOpenLaneShell` where plugins would not get
  included due to an operator precedence issue.

# 2.2.0

## CLI

* Exposed Flow.start(overwrite=) as `--overwrite`, which removes a run directory
  before running the flow (if it exists)

## Steps

* Created `Odb.ManualGlobalPlacement`

  * Can create a global placement for instances. Intended for
    manually-instantiated buffers that require a certain regional placement or
    similar.
  * Uses new variable `MANUAL_GLOBAL_PLACEMENTS`, a mapping from instance names
    to the `Instance` class.

* Created `Odb.CellFrequencyTables`

  * Creates a number of tables to show the cell frequencies by:
    * Cells
    * Buffer cells only
    * Cell Function
    * SCL

* `OpenROAD.*`

  * All steps that modify views now update design cell metrics using OpenROAD's
    `report_design_area_metrics`

* `OpenROAD.ResizerTimingPostGRT`

  * Added `GRT_RESIZER_RUN_GRT` to control whether global routing is re-run
    after this step, which is usually required but may be redundant in some
    custom flows.

* `OpenROAD.RepairDesignPostGRT`

  * Added `GRT_DESIGN_REPAIR_RUN_GRT` to control whether global routing is
    re-run after this step, which is usually required but may be redundant in
    some custom flows.

* `OpenROAD.STA*`

  * New report `clock.rpt` created with information about each clock in a
    specific domain

* `OpenROAD.WriteViews`

  * Added `OPENROAD_LEF_BLOAT_OCCUPIED_LAYERS` with a default value of `true`

* `Yosys.*Synthesis`

  * ABC scripts used now created dynamically and dumped as a `.abc` file into
    the step directory.
  * Implemented many of the
    [suggestions by @ravenslofty](https://github.com/efabless/openlane2/issues/524)
    from YosysHQ, some behind flags:
    * `SYNTH_ABC_DFF`: Adds `-dff` to `abc` invocations (except the ones inside
      `synth`)
    * `SYNTH_ABC_BOOTH`: Activates the
      [`booth`](https://yosyshq.readthedocs.io/projects/yosys/en/0.44/cmd/booth.html)
      pass as part of `synth`
    * `SYNTH_ABC_USE_MFS3`: Uses `mfs3` in all strategies before retime
    * `SYNTH_ABC_AREA_USE_NF`: Attempts delay-based mapping with a really high
      delay value instead of area-based mapping.

* `Yosys.JsonHeader`, `Yosys.*Synthesis`

  * **Internal**: * Steps are no longer `TclStep`s: rewritten in Python and now
    use `libyosys`. While there are no functional changes, this enhances the
    codebase's consistency and helps avoid tokenization-related security issues.

## Flows

* `Classic`
  * Emplaced `Odb.ManualGlobalPlacement` immediately preceding
    `OpenROAD.DetailedPlacement`.
  * Emplaced `Odb.CellFrequencyTables` after `OpenROAD.FillInsertion`

## Tool Updates

* OpenROAD -> `bbe940134bddf836894bfd1fe02153f4a38f8ae5`

  * OpenSTA -> `20925bb00965c1199c45aca0318c2baeb4042c5a`
  * Removed "stable" version of OpenSTA

* Updated nix-eda to `0814aa6`: more orthodox approach to managing dependencies
  by overlaying them on top of nixpkgs, which fixes an occasional "repeated
  allocation" issue and helps make override behavior more consistent.

  * Yosys and first-party plugins -> `0.46`
  * `klayout` -> `0.29.4`
  * `magic` -> `8.3.489`
  * `netgen` -> `1.5.278`
  * OpenROAD now used with new `withPythonPackages` features to use Python
    packages specifically for the OpenROAD environment

* OpenLane itself no longer included in `devShells.*.dev`, `devShells.*.docs`

  * These shells are intended to be actual dev shells, i.e. used to develop
    OpenLane, and needing OpenLane to pass tests to run these shells makes no
    sense.

* Open PDKs -> `0fe599b` (Recommended for chipIgnite 2409/2411+ shuttles)

## Misc. Enhancements/Bugfixes

* `openlane.common.metrics`
  * `aggregate_metrics()`: Added support for aggregation of N-modifier levels
* `openlane.config.Config`
  * YAML 1.2 configuration files now accepted using `.yaml` or `.yml`
    extensions, with the same featureset as JSON files.
  * The first configuration (file/dict) supplied no longer needs to be a
    complete configuration so long as any required variables are supplied in
    later configurations. Missing variables are only checked on the complete
    configuration.
  * Internally reworked how config files and command-line overrides are parsed.
* Fixed bug with deprecated variable translations of
  `{CLOCK,SIGNAL}_WIRE_RC_LAYERS`.

## Documentation

* Added info on YAML configuration files.
* Documentation for `Instance` dataclass generalized to include instances of
  cells and not macros.

# 2.1.11

## Steps

* `OpenROAD.STA*PnR`

  * Fixed `timing__*_r2r__ws__corner` metrics reporting the wrong value

# 2.1.10

## Misc. Enhancements/Bugfixes

* `openlane.config.Variable`

  * Fixed an issue when strict type-checking is disabled where empty strings
    would crash iterable objects.

## Tool Updates

* Fixed mypy to 1.9.0 to match NixOS 24.05.

* Checked `poetry.lock` into version control to improve reproducibility.

# 2.1.9

## Steps

* `OpenROAD.CheckAntennas`

  * Fixed table being printed to file with wrong width.

* `OpenROAD.STA*PnR`

  * Fixed table being printed to file with wrong width.

## Flows

* `SynthesisExploration`

  * Fixed table being printed to file with wrong width.

# 2.1.8

## Steps

* `OpenROAD.STA*PnR`

  * Fixed a bug in STA metrics where paths with exactly zero slack are counted
    as violations.

# 2.1.7

## Steps

* `Odb.Remove*Obstructions`

  * Rework obstruction matching code to not use IEEE 754 in any capacity
  * Fixed bug where non-integral obstructions would not be matched correctly
    (thanks @urish!)

# 2.1.6

## Steps

* `Yosys.Synthesis`

  * Fixed bug where `hilomap` command was invoked incorrectly (thanks @htfab!)

# 2.1.5

## Steps

* `Odb.SetPowerConnections`

  * Fixed an issue introduced in `2.1.1` where modules that are defined as part
    of hierarchical netlists would be considered macros and then cause a crash
    when they are inevitably not found in the design database.
    * Explicitly mention that macros that are not on the top level will not be
      connected, and emit warnings if a hierarchical netlist is detected.

## Documentation

* Updated macro documentation to further clarify how instances should be named
  and how names should be added to the configuration.

# 2.1.4

## Steps

* `OpenROAD.STA*PNR`
  * New environment variable made accessible to SDC files used during
    Multi-Corner STA steps, `OPENLANE_SDC_IDEAL_CLOCKS`, set to `1` for pre-PnR.
    Band-aid until the SDC situation is properly discussed and addressed (in a
    potentially breaking change.)
  * Fixed issue where the clock was always propagated after `STAPrePNR`
    regardless the information in the SDC file.
  * For backwards compatibility, `STAPrePNR` unsets all propagated clocks and
    the rest set all propagated clocks IF the SDC file lacks the strings
    `set_propagated_clock` or `unset_propagated_clock`.

# 2.1.3

## Tool Updates

* Bundled an downgraded OpenSTA bundled with OpenLane to work around critical
  bug for hierarchical static timing analysis:
  https://github.com/parallaxsw/OpenSTA/issues/82
  * Version of OpenSTA linked against OpenROAD unchanged.

## Testing

* CI now uses DeterminateSystems Nix Installer for all Nix installations as well
  as the Magic Nix Cache Action instead of the nonfunctional attempt at local
  file-based substituters

## Documentation

* Installation documents now use the less-brittle Determinate Systems Nix
  installer, as well as adding warnings about the `apt` version of Nix.

* Added an OpenROAD Flow Scripts-inspired Diagram to the Readme.

# 2.1.2

## Steps

* `OpenROAD.*`

  * Fixed an issue where the validation for `PDN_MACRO_CONNECTIONS` would
    partially match net names, unlike OpenROAD itself
  * Internal string escaping consistency

# 2.1.1

## Steps

* `Odb.SetPowerConnections`

  * Internally reworked pin detection behavior so power pins are found in the
    LEF first then matched in the Verilog, fixing a corner-cases where
    unconnected buses would be candidates for power pins, then promptly cause a
    crash as they only exist in the layout as separate pins.

* `OpenROAD.IOPlacement`, `OpenROAD.GlobalPlacementSkipIO`

  * `FP_IO_MODE` renamed to `FP_PPL_MODE`: translation behavior for OpenLane
    1-style FP_IO_MODE with integers added behind deprecated name `FP_IO_MODE`.

* `Yosys.*Synthesis`

  * Restored filtering of `defparam` from output netlists to avoid surprisingly
    still extant OpenSTA limitation.

## Testing

* Added file to exclude step unit tests purely to speed-up turnaround time for
  PRs (as sometimes a test would need to be deleted/temporarily disabled without
  updating the submodule, see #475 for a similar situation)

* Mac CI now uses an artifact of the PDK

  * Unlike the Linux runners, Mac runners:
    * Are disproportionately affected by rate-limiting: cannot pull from GitHub
      using Volare
    * Do not support caches created on Ubuntu, even with `enableCrossOsArchive`

# 2.1.0: The "Customization and Control" Update

## CLI

* Overhauled how the PDK commandline options work, using a decorator instead of
  doing everything in a callback
* `--smoke-test/--run-example` are now no longer callbacks, and `--run-example`
  now supports more options (e.g. another PDK, another flow, etc.)
* Docker subprocesses
  * Are now always run interactively and can be interrupted.
  * Are now run using `execlp`, replacing the Python interpreter altogether

## Steps

* Created `Checker.NetlistAssignStatements`

  * Outputs warnings or errors (depending on `ERROR_ON_NL_ASSIGN_STATEMENTS`)
    when `assign` statements are found in the netlist of the input state (assign
    statements cause some issues with some tools)

* `KLayout.OpenGUI`

  * Renamed `KLAYOUT_PRIORITIZE_GDS` to `KLAYOUT_GUI_USE_GDS` to be consistent
    with the Magic steps.
  * Script no longer relies on the `click` library as the internal Python
    interpreter more often than not has trouble finding the site packages (and
    indeed the site packages includes its own pya/klayout which is its own
    headache.)

* `Magic.*`

  * All steps now use a new processor,
    `openlane.steps.magic.MagicOutputProcessor`, to capture and count errors
  * Fixed `magicrc` being `abspath`'d before command invocation (breaks
    reproducibles)
  * `_MAGIC_SCRIPT` is now set in `prepare_env` instead of `run_subprocess` (so
    it can be intercepted for reproducibles)

* New step, `Magic.OpenGUI`, which opens either DEF files or GDS files in magic

* `Magic.SpiceExtraction`:

  * A `feedback.xml` is now created, with the contents being the SPICE
    Extraction feedback in the KLayout marker database format
  * Created `MAGIC_EXT_ABSTRACT_CELLS`: a list of regular expressions that are
    matched against the design's cells names what are abstracted (black-boxed)
    during extraction.

* `Netgen.LVS`:

  * Added `LVS_FLATTEN_CELLS`: A list of cells to flatten in LVS.
  * Added `LVS_INCLUDE_MARCOS_NETLIST`. If enabled macros' netlist are loaded
    when running LVS. Either `pnl` or `nl` or `vh` views are selected.
  * Updated Netgen setup file to equate cells inside macros where the GDS is
    generated with blackbox macro option

* `Odb.ApplyDEFTemplate`: Thanks [@smunaut](https://github.com/smunaut)

  * DEF template pin placement status (e.g. `PLACED`, `FIXED`) now always
    propagated to work around PDN generation removing placed but unconnected
    power pins.
  * Fixed crashes when copying power pins from a template where the net name and
    the power pin name may be different (or one net may be connected to multiple
    power pins.)

* `Odb.ReportDisconnectedPins`

  * Disconnected dummy instances created during CTS, prefixed `clkload`, are now
    ignored.

* `Odb.SetPowerConnections`

  * **Internal**: Restructure `power_utils.py` to provide better error messages
    and use dictionaries instead of oddball iterator-based filtering

* Created `OpenROAD.DEFtoODB`

  * Useful for custom flows, where the DEF is modified but the ODB needs to be
    updated to reflect these modifications

* `OpenROAD.*`

  * OpenROAD scripts now set `set_wire_rc` for the average values of the layers
    grouped by routing direction. All layers in the routing range are used if
    either `SIGNAL_WIRE_RC_LAYERS` or `CLOCK_WIRE_RC_LAYERS` are null.
  * Slight internal Tcl code reorganization.

* `OpenROAD.Floorplan`

  * Added soft placement obstructions via new variable `PL_SOFT_OBSTRUCTIONS`.

* `OpenROAD.RepairDesignPostGPL`

  * Added new variable `DESIGN_REPAIR_REMOVE_BUFFERS`, which will instruct
    OpenROAD to remove synthesis buffers so there's more flexibility during
    design repair: see
    https://github.com/The-OpenROAD-Project/OpenROAD/blob/ad54bbe88b561d1c30451d8a3c85ad11c1692905/src/rsz/README.md?plain=1#L185

* `Yosys.*`

  * Added new variable `YOSYS_LOG_LEVEL`, which controls the verbosity of Yosys
    output

* `Yosys.*Synthesis`

  * Moved the `rename` of top module to before selecting it. This fixes a
    problem DFFRAM where needed modules are optimised away and then synthesis
    fails. (Thanks @donnie-j!)

  * Syntheses with `SYNTH_ELABORATE_ONLY` no longer report undriven nets as a
    check error (frequently for some top-level integrations, output pins are
    left undriven entirely to save space.)

## Flows

* Created new mono-step flow, `OpenInMagic`, which runs `Magic.OpenGUI`
* `VHDLClassic` is now based on `Classic` with appropriate `Substitutions

## Tool Updates

* All tool nix derivations now have `rev`/`version` and `sha256` as one of their
  parameters, allowing them to be easily replaced with `.override`.

* OpenLane 2 now uses [nix-eda](https://github.com/efabless/nix-eda) for some of
  its dependencies

  * `nixpkgs` -> `24.05`
  * `klayout` -> `0.29.1`
  * `magic` -> `8.3.483`/`291ba96`
    * now uses tk with X11 on macOS, to prevent crashes when attempting to use
      the GUI
  * `netgen` -> `bf67d3c`
  * `forAllSystems` built into `nix-eda`, now composes overlays for nixpkgs
    based on the `withInputs` field, allowing for easier overriding

* `volare` -> `0.18.1`

* `ioplace_parser` -> `0.3.0`

* `openroad` -> `b16bda7`

  * Removed OpenLane-specific patch for querying existence of antenna
    information
  * `openroad-abc` -> `ef5389d`
    * `ABC_USE_NAMESPACE` now set, value also injected into header files
  * `opensta` -> `e01d3f1`

* Python build tool changed from `setuptools` to `poetry`, which properly
  verifies that all version ranges are within constraints

  * Updated wrong Python package version ranges that all happen to work

* Nix devshells now use [numtide/devshell](https://github.com/numtide/devshell),
  which creates an executable to enter the environment, allowing for easy
  repacking

* Docker image creation now uses a Nix derivation based on that of the official
  Nix Docker image, which includes a full Nix installation in the image (so
  users may add tools and apps in the container at their leisure.)

* `mdformat` promoted from overlay to `packages`.

## Misc. Enhancements/Bugfixes

* `openlane.flows.SequentialFlow`

  * Substitutions can now
    * be done at the class level by assigning to `Substitutions`
    * be done in `config.json` files using a dictionary in the field
      `.meta.substituting_steps`
    * emplace steps before or after existing steps, e.g. `+STEP`, `-STEP`
  * Step names for `from`, `to`, `skip` and `only` are now fuzzy-matched using
    `rapidfuzz` to give suggestions in error messages
    * If the environment variable
      `_i_want_openlane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks`
      is set to `1`, the suggestions are used automatically (not recommended)
  * Gating config vars are now simply removed if they do not target a valid step
    (so removed steps in a substituted flow do not cause a FlowException)

* `openlane.common`

  * `DRC`: Work around a weird macOS-only bug where boxes in exported KLayout
    marker databases would not function properly: see
    https://github.com/KLayout/klayout/issues/1550
  * `GenericDictEncoder`: Fixed crash when attempting to dump a Decimal of
    infinite value

* `openlane.common.config`

  * Trailing commas are now permitted when converting from a string format
    (which are necessary because of the ambiguity of lists of lists.)

* `openlane.steps.DefaultOutputProcessor`

  * `%OL_METRICS_F` now uses Decimals instead of Floats

* `openlane.steps.Step.create_reproducible`

  * `PDK_ROOT` now included if the PDK is included but not flattened so Magic
    steps can work

* `openlane.steps.TclStep`

  * **Internal**: Internal environment variables prefixed with `_` are no longer
    rerouted to `_env.tcl`, instead being passed raw (to help with creating
    reproducibles)

* Universal flow configuration variable

  * `DATA_WIRE_RC_LAYER` renamed to `SIGNAL_WIRE_RC_LAYERS`,
    `CLOCK_WIRE_RC_LAYER` renamed to `CLOCK_WIRE_RC_LAYERS`, with translation
    behavior and data type changed to `List[str]?`
  * Universal PDK variables `SIGNAL_WIRE_RC_LAYERS`/`CLOCK_WIRE_RC_LAYERS` no
    longer have default values for all PDKs (are null.)

* Fixed new typing inconsistencies exposed by mypy.

* Removed loop header genvar declaration from examples (limited compatibility
  with some tools)

## Documentation

* Created a new document on writing plugins.

* Updated the architecture document to reflect changes and clarify some
  elements.

* Updated documentation of the `state` submodule.

* Updated Usage/Writing Custom Flows to document step substitution

* Fixed a number of broken links.

# 2.0.11

## Misc Enhancements/Bugfixes

* Fixed a deadlock in some situations because of `OpenROAD.STAPrePNR` using the
  global thread-pool for OpenLane, which may be used to run the step itself.

# 2.0.10

## Tool Updates

* Relaxed `rich` version range to allow Rich 13.
  * Matches Volare's version range and allows CACE and OpenLane 2 to be
    installed in the same Python environment.

# 2.0.9

## CLI

* Fixed `--ef-save-views-to` saving to `signoff/<design>/openlane` instead of
  `signoff/<design>/openlane-signoff` (which makes less sense but is the
  established convention at Efabless.)

## Steps

* `OpenROAD.*`

  * Fixed environment contamination with deprecated variables that may be used
    by user-supplied PDN or SDC files.

* `OpenROAD.GeneratePDN`

  * Restored compatibility with some ancient OpenLane PDN config files.

## Tool Updates

* Updated `ioplace_parser` to `0.2.0`
  * Fixes regressions in pin regular expression parsing.

# 2.0.8

## Steps

* `Odb.DiodePortInsertion`, `Odb.DiodesOnPorts`
  * Fixed bug where diodes were never inserted on outputs, and added unit tests
    to that effect.

# 2.0.7

## Misc Enhancements/Bugfixes

* Overhauled Tcl configuration loading code to fix a number of bugs that may
  occur when a Tcl file sources another Tcl file, such as for TinyTapeout
  configs (thanks @htfab)

# 2.0.6

## Misc. Enhancements/Bugfixes

* Fixed a crash on Linux distributions where `/etc/lsb-release` includes
  comments.

# 2.0.5

## Misc. Enhancements/Bugfixes

* The flow warning summary now only shows the first instance of any warning
  emitted, instead showing two numbers for identical warnings in other steps and
  for similar warnings (e.g. same OpenROAD code.)

# 2.0.4

## Steps

* `Odb.SetPowerConnections`

  * Fixed bug where instances with special characters in their name and power
    pins are not equal to those of the SCL would not get connected.
  * Added assertion that exactly one pin is connected for every operation.

* `Yosys.GenerateJSONHeader`

  * Netlist is now flattened so `Odb.SetPowerConnections` can properly set pins
    for nested macros with power pin names not equal to those of the SCL.

# 2.0.3

## Tool Updates

* Updated OpenROAD to `d423155`, OpenSTA to `a7f3421`
  * Addresses an
    [antenna repair bug](https://github.com/efabless/openlane2/issues/459)

## Testing

* Updated a number of unit tests to reflect new OpenROAD error codes.
* Fixed failing design integration tests.

# 2.0.2

## Steps

* `Odb.ReportDisconnectedPins`
  * Fixed table not being written to step directory
  * Fixed bug where table widths were not being set properly
  * Fixed bug where pins with `USE SIGNAL` would be considered power pins

# 2.0.1

## Steps

* `OpenROAD.*`
* Fixed alert about unmatched regexes in `PDN_MACRO_CONNECTIONS` not being
  properly marked as an `[ERROR]`.
* Fixed crash when steps that generate OpenROAD alerts that are suppressed by
  the flow experience a non-zero exit.

# 2.0.0

## Docs

* Updated messaging to be a bit more consistent wrt OpenLane 1 vs OpenLane 2.

# 2.0.0rc3

## CLI

* Resolved bug causing nonexistent mounted volumes to be created as root when
  using a non-rootless container engine with `--dockerized`.
* Fixed issue where PIP versions of OpenLane would not be able to copy examples
  properly.
* Environment detection scripts no longer use `nix-info`, saving time.

## Steps

* `OpenROAD.STAPrePnR`

  * Now performs multicorner STA pre-PnR according to `STA_CORNERS`; although if
    two corners have identical file lists the latter corner is skipped
  * Internally rearranged class structure so STA pre and post PnR share as much
    code as possible

* `Yosys.*`

  * Fixes a bug where synthesis checks were not passed properly when
    `SYNTH_ELABORATE_ONLY` is true.
  * **Internal**:
    * Created new namespace, `yosys_ol`, to encapsulate a number of reusable
      functions for modularity and readability
    * Created two new functions `ol_proc` and `ol_synth`; to encapsulate our
      modified `synth` and `proc` instead of them being strewn across
      `synthesize.tcl`
    * ABC script construction moved to standalone file

## Misc

* `openlane.steps`
  * `Step`
    * `.start()` no longer prints logs at the beginning as it may not
      necessarily exist

# 2.0.0rc2

## CLI

* `openlane.steps`
  * `eject` *now overrides `psutils.Popen()` instead of `run_subprocess`,
    allowing it to run at a lower level
  * `PATH`, `PYTHONPATH` now excluded from `run.sh`

## Steps

* `Checker.PowerGridViolations`

  * Fixed mistakenly added whitespace in `FP_PDN_CHECK_NODES`

* `Magic.WriteLEF`

  * Added new variable `MAGIC_WRITE_LEF_PINONLY`, which writes the LEF with with
    the `-pinonly` option; declaring nets connected to pins on the same metal
    layer as obstructions and not part of the pin

* `OpenROAD.*`, `Odb.*`

  * Outputs now processed first by new class `OpenROADOutputProcessor`, which
    captures warnings and errors from OpenROAD into a data structure and emits
    them using OpenLane's logger

* `OpenROAD.CTS`

  * Made `CTS_MAX_CAP` a non-PDK value, and also optional as the values in the
    PDK configuration are bad and OpenROAD does a better job without it
  * CTS no longer passes `MAX_TRANSITION_CONSTRAINT`, instead using a new
    variable `CTS_MAX_SLEW` if it exists
  * Fixed issue where no arguments were passed to
    `configure_cts_characterization`
  * Fixed bug where an incorrect value was passed to the `-max_slew` option

* `Odb.ApplyDEFTemplate`

  * Added new variable, `FP_TEMPLATE_COPY_POWER_PINS`, that *always* copies
    power pins from the DEF template
  * Power pins are now filtered and exempt from placement otherwise, allowing
    the step to be runnable after PDN generation

* `Odb.CustomIOPlacement`

  * Power pins are now filtered and exempt from placement, allowing the step to
    be runnable after PDN generation
  * `FP_IO_VLENGTH`, `FP_IO_HLENGTH` are now both optional PDK variables
  * The values are now used properly instead of a taking the maximum of both for
    both kinds of pins
  * For PDKs that do not specify them, the script calculates default values
    based on the layers' rules
  * `QUIT_ON_UNMATCHED_IO` now migrates to new variable
    `ERRORS_ON_UNMATCHED_IO`, an enumeration of four variables that controls
    whether errors are emitted in:
    * no situation
    * situations where pins in the design are missing from the config file
      (default, matching openlane 1)
    * situations where pins in the config file are missing from the design (new)
    * either situation
  * Better error message for too many pins on the same side

* `OpenROAD.GlobalPlacement`

  * Added `PL_MIN_PHI_COEFFICIENT`, `PL_MAX_PHI_COEFFICIENT` for when global
    placement diverges

* `OpenROAD.GlobalPlacementSkipIO`

  * `PL_TIMING_DRIVEN` and `PL_ROUTABILITY_DRIVEN` no longer passed (useless
    with `-skip_io`)

* `OpenROAD.IOPlacement`

  * `FP_IO_VLENGTH`, `FP_IO_HLENGTH`, `FP_IO_MIN_DISTANCE` are now all optional
    PDK variables
    * For PDKs that do not specify them, OpenROAD calculates default values
      based on the layers' rules

* `OpenROAD.ManualMacroPlacement`

  * **API Break**: Verilog names of macros are now considered instead of DEF
    names in the event of a mismatch (e.g. for instances with `[]` or `/` in the
    name.)

* `OpenROAD.STAPrePnR`, `OpenROAD.STAPostPnR`

  * Added new configuration variable `EXTRA_SPEFS` ONLY for backwards
    compatibility with OpenLane 1 that should not otherwise be used

* `OpenROAD.STAPrePNR`

  * Unset clock propagation for this step (misleading as the clock should be
    ideal before CTS)

* `Verilator.Lint`

  * Now works with the preprocessor macro `VERILOG_POWER_DEFINE` being defined -
    justification is that most macros come with a powered netlist than a regular
    netlist
  * `CELL_BB_VERILOG_MODELS` is no longer used, with the blackbox models always
    getting generated (so power pins can be included)
  * `__openlane__`, `__pnr__`, `PDK_{pdk_name}` and `SCL_{scl_name}` are all
    always defined as preprocessor macros
  * Fixed issue where the order of files may not be preserved for macros,
    causing linting to fail
  * Internally adjusted how linter flags are set; a `.vlt` file is used to turn
    off certain linting rules for the black-box models instead of copying and
    wrapping the black-box comments in comments

* `Yosys.*`

  * `__openlane__`, `__pnr__`, `PDK_{pdk_name}` and `SCL_{scl_name}` are all
    always defined as preprocessor macros

* `Yosys.JsonHeader`

  * Now reads generated black-boxed models of the standard cells with power pins
    instead of lib files, allowing power pins to be explicitly specified for
    hand-instantiated cells as well without issue

## Flows

* `Classic`
  * Added `Odb.AddRoutingObstructions` before global routing
  * Added `Odb.RemoveRoutingObstructions` after detailed routing
  * Moved PDN generation steps before Global Placement

## Tool Updates

* `magic` -> `8.3.466`/`bfd938b`
  * Addresses a bug with reading DEF files using generated vias
* Updated KLayout to `0.28.17-1`
  * Relaxes PIP version range to accept newer patches (not newer minor versions)

## Testing

* Added an OpenLane 1-compatible configuration for `aes_user_project_wrapper` to
  test back-compat
* Ensured `open_proj_timer` config matches OpenLane 1's as closely as possible
* Updated unit tests because newer versions of flake8 hate `pytest.fixture()`
  for some reason
* Updated step unit tests that look for OpenROAD alerts to use captured alerts
  instead of checking the log.

## Misc. Enhancements/Bugfixes

* `openlane.common`
  * `Toolbox`
    * New method, `get_timing_files_categorized`, returns the three design
      formats in, get this, three separate lists
* `openlane.config`
  * `Config`
    * No longer attempts to migrate `EXTRA_SPEFS` to `MACROS` because of
      side-effects (e.g. the dummy paths)
  * PDK backwards-compatibility script now skips migrating `LIB_*` if `LIB`
    already exists
    * "Default" constraints made exclusive to `sky130` and `gf180mcu`
* `openlane.steps.Step`
  * `run_subprocess`: New concept of "output processors"- classes that may do
    processing on the output of a step to parse it
    * Default output parsing behavior implemented as `DefaultOutputProcessor`
    * `run_subprocess` no longer returns just metrics, rather, metrics are
      returned under the key `generated_metrics` when the
      `DefaultOutputProcessor` is used along with the results of other output
      processors
* Slightly adjusted widths of printed tables across the codebase for
  readability.

## API Breaks

* `OpenROAD.ManualMacroPlacement`

  * Verilog names of macros are now considered instead of DEF names in the event
    of a mismatch (e.g. for instances with `[]` or `/` in the name.)

* `openlane.steps.Step`

  * `run_subprocess` no longer returns just metrics, rather, metrics are
    returned under the key `generated_metrics` when the `DefaultOutputProcessor`
    is used along with the results of other output processors

## Documentation

* Adapted timing closure guide by [@shalan](https://github.com/shalan) to
  OpenLane 2
  * Converted to MyST Markdown
  * All images made dark-mode friendly
  * References to variables all now resolve properly
* Fixed a number of inconsistencies and broken links.

# 2.0.0rc1

## CLI

* Fixed `--ef-save-views-to` not saving `.mag`, `.gds` views

## Steps

* `Checker.*`
  * Created new `ERROR_ON` variables with the removed `QUIT_ON` variables from
    the `Classic` flow being added as deprecated names for these variables.
  * Disabling `ERROR_ON*` (previously `QUIT_ON*`) no longer bypasses a step
    entirely. A warning will be generated and the flow will not quit.
* `Checker.TimingViolations`
  * `TIMING_VIOLATIONS_CORNERS` renamed to `TIMING_VIOLATION_CORNERS`
  * Now creates a new variable `<violation_type>_VIOLATION_CORNERS` for its
    subclasses. This allows for fine-grained control of the IPVT corners checked
    by each subclass.
  * Now generates errors for violations occuring at `TIMING_VIOLATION_CORNERS`
    (unless the subclass variable override is defined) and generates warnings
    for violations in the rest of the IPVT corners.
* `Checker.HoldViolations`
  * Added `HOLD_VIOLATION_CORNERS` which takes precedence over
    `TIMING_VIOLATION_CORNERS`
* `Checker.SetupViolations`
  * Added `SETUP_VIOLATION_CORNERS` acting similar to `HOLD_VIOLATION_CORNERS`.
* Created `Checker.MaxCapViolations`
  * Reports maximum capacitance violations.
  * Added `MAX_CAP_VIOLATION_CORNERS`. It defaults to `[""]` which is the value
    for matching no corners (i.e. all violations are reported as warnings).
* Created `Checker.MaxSlewViolations`
  * Reports maximum slew violations.
  * Added `MAX_SLEW_VIOLATION_CORNERS`. It defaults to `[""]` which is the value
    for matching no corners (i.e. all violations are reported as warnings).
* `OpenROAD.GlobalPlacementSkipIO`
  * Fixed a bug where `PL_TARGET_DENSITY_PCT` is calculated base on
    `FP_CORE_UTIL` in designs with `FP_SIZING` set to `absolute`. The behavior
    now matches `OpenROAD.GlobalPlacement`.
* `Yosys.*`
  * Verilog files are now read with `-noautowire`. This changes the default
    `default_nettype` to `none`, no longer tolerating implicitly declared wires
    unless `default_nettype` is explicitly set to something else in a particular
    source file.

## Flows

* `Classic`, `VHDLClassic`
  * **API Break**: Removed all `QUIT_ON*` variables from the flow itself
  * Added `Checker.MaxSlewViolations`
  * Added `Checker.MaxCapViolations`

## Tool Updates

* Updated `black` to `23` + matching formatting changes to the code
* Makefile no longer creates venvs for most targets
* Default Nix shell no longer includes development-specific tools (jdupes,
  alejandra, pytest…), new devShell `dev` includes these tools and more

## Testing

* Created two coverage commands in the `Makefile`, one for infrastructure unit
  tests and the other for step unit tests

## Misc. Enhancements/Bugfixes

* `openlane.flows.Flow`:
  * All warnings captured are now printed at the end of the flow à la OpenLane
    1\.
* `openlane.flows.SequentialFlow`:
  * Deferred errors are now handled in the same way normal errors are.
* Various internal environment variables changed from `_lower_snake_case` to
  `_UPPER_SNAKE_CASE` for (relative) consistency
* `openlane.common.TclUtils`
  * Empty strings now escaped as `""`
* `openlane.steps.Step`
  * Printing of last 10 lines of a file now uses a ring buffer instead of
    concatenating then splitting then joining
* `openlane.steps.TclStep`
  * Various handcrafted joins in subclasses now use `TclStep.value_to_tcl` or
    `TclUtils.join`
  * **API Break**: `value_to_tcl` no longer converts dataclasses to JSON,
    rather, they're converted to Tcl dicts
  * **API Break**: `run_subprocess` now intercepts and passes most environment
    variables are now passed indirectly, i.e., a file is made and placed under
    the variable `_TCL_ENV_IN`, which is then to be sourced by scripts. This
    helps avoid the 1 MiB args + env limit in macOS / 2 MiB args + env limit in
    Linux.

## API Breaks

* **API Break**: Removed all `QUIT_ON*` variables from the the `Classic`,
  `VHDLClassic` per se, however they are not translated variables.

## Documentation

* Fixed bug with newcomer's guide (thanks @calvbore)

# 2.0.0b17

## CLI

* Multiple configuration files now supported, incl. mixes of JSON and Tcl files
* Added new flag, `--show-progress-bar/--hide-progress-bar`, also
  self-explanatory
* Added new flag, `--run-example`, which instantiates and runs one of the
  example designs
* Added new flag, `--condensed`, which sets `logging.options.condensed_mode` and
  changes the default for showing the progress bar to `False`
* Added new entry script, `openlane.config`, which allows configuration files to
  be interactively generated
* Fixed bug where 0 config files causes a crash

## Steps

* All steps:
  * Change skipped-step `warn`s to `info` if the skip should not necessarily be
    a cause for alarm
  * Suppressed warnings about dead processes when tracking subprocess resource
    usage
  * Fixed crash when subprocesses emit non-UTF-8 output: Now a proper
    `StepException` is raised
* Created `KLayout.DRC`
  * Only compatible with sky130 (skipped for other PDKs)
* Created `Checker.PowerGridViolations`
  * Raises deferred step error if `design__power_grid_violation__count` is
    nonzero
* Created `Checker.SetupViolations `, `Checker.HoldViolations` to check
  setup/hold timing violations
  * Add config variable `TIMING_VIOLATIONS_CORNERS`, which is a list of
    wildcards to match corners those steps will flag an error on.
* `KLayout.OpenGUI`
  * Added a new boolean config var, `KLAYOUT_EDITOR_MODE` to that enables editor
    mode in KLayout
  * Added new variable `KLAYOUT_PRIORITIZE_GDS`, which as the name implies,
    prioritizes GDS over DEF if there's a GDS in the input state.
  * `cwd` for subprocess set to step directory for convenience
  * Fixed bug where viewer mode was not working
* `Odb.*`, `KLayout.*`
  * Subprocesses now inherit `sys.path` in `PYTHONPATH` which allows `nix run`
    to work properly
* `Odb.ApplyDEFTemplate`
  * Added `FP_TEMPLATE_MATCH_MODE`, with values `strict` (default) or
    `permissive` with `strict` raising an error if any pins are missing from
    either the template or the design.
  * Warn when the template DEF die area is different from the design die area.
  * No longer copies the die area from the DEF template file-- floorplanning
    needs to be executed correctly first. `DIE_AREA`
* `Odb.CustomIOPlacement`
  * Completely re-implemented pin placement file parser in Antlr4 for more
    thorough syntax and semantic checking at
    https://github.com/efabless/ioplace_parser
  * Formalized concept of annotations; documented three annotations:
    `@min_distance`, `@bit_major`, and `@bus_major`.
  * Rewrote `openlane/scripts/odbpy/io_place.py` to rely on the new parser +
    general cleanup
* `Odb.ManualMacroPlacement`
  * Instances missing placement information are no longer treated as errors and
    are simply skipped so it can be passed on to other steps (or if is
    information about a nested macro)
* Created new step `Odb.WriteVerilogHeader`
  * Writes a `.vh` file using info from the layout post-PDN generation and the
    Verilog header
* `OpenROAD.*`
  * Updated to handle `EXTRA_EXCLUDED_CELLS`
  * No longer trimming liberty files, relying on `set_dont_use` instead
* `OpenROAD.CheckAntennas`
  * Added new `antenna_summary.rpt` file with a summary table for antennas
    matching that of OpenLane 1
* `OpenROAD.Floorplan`
  * `PL_TARGET_DENSITY_PCT` default calculation now prioritizes using metric
    `design__instance__utilization` if available.
  * Fixed a crash where obstructions were passed as floats instead of database
    unit integers and caused a crash.
* `OpenROAD.GeneratePDN`
  * Renamed `DESIGN_IS_CORE` to `FP_PDN_MULTILAYER`, which is more accurate to
    its functionality
  * Removed comments about assumptions as to the PDN stack config with regards
    to top-level integrations vs macros: macros can have two PDN layers and a
    core ring
  * Fixed issue where a PDN core ring would still be created on two layers even
    if `FP_PDN_MULTILAYER` is set to false- an error is thrown now
  * Fixed issue where `FP_PDN_VSPACING` is not passed to `add_pdn_stripe` when
    `FP_PDN_MULTILAYER` is set to false (thanks @mole99)
  * **API Break**: `FP_PDN_CHECK_NODES` is no longer a config variable for this
    step. The relevant checks are always run now, however, they do not cause the
    flow to exit immediately, rather, they generate
    `design__power_grid_violation__count ` metrics.
* `OpenROAD.GlobalPlacementSkipIO`
  * Updated to do nothing when `FP_DEF_TEMPLATE` is defined
* `OpenROAD.IOPlacement`
  * Updated to do nothing when `FP_DEF_TEMPLATE` is defined.
* `OpenROAD.IRDropReport`
  * Added `VSRC_LOC_FILES` for IR Drop, printing a warning if not given a value
  * Rewrote internal IR drop script
* `OpenROAD.Resizer*`, `OpenROAD.RepairDesign`
  * `RSZ_DONT_USE_CELLS` removed, added as a deprecated name for
    `EXTRA_EXCLUDED_CELLS`
* `OpenROAD.STAPostPNR`
  * Added hold/setup reg-to-reg worst violation to STA summary table.
  * Added hold/setup tns to STA summary table.
  * Slack values of zero are now highlighted green instead of red.
  * Changed summary table column header from `reg-to-reg` to `Reg to Reg Paths`
    for readability
  * Fixed slacks for `Reg to Reg Paths` only showing negative values.
* `Yosys.*`
  * Updated to handle `EXTRA_EXCLUDED_CELLS`
  * Internally replaced various `" ".join`s to `TclUtils.join`
  * Implementation detail: "internal" variables to be lowercase and prefixed
    with an underscore as a pseudo-convention
  * Turned `read_deps` into one sourced script that is generated by Python
    instead of a Tcl function (as was the case for `.EQY`)
  * For maximum compatibility, priority of views used of macros changed, now, in
    that order it's
    * Verilog Header
    * Netlist/Powered Netlist
    * Lib File
  * Fixed bug where Lighter would not be executed properly
* `Yosys.Synthesis`
  * Updated error for bad area/delay format to make a bit more sense
  * Updated internal `stat` calls to Yosys to pass the liberty arguments so the
    area can be consistently calculated
  * Fixed bug where custom technology maps were not properly applied
  * Removed `SYNTH_STRATEGY` value `AREA 4` -- never existed or worked

## Flows

* All flows
  * Added a `flow.log`, logging at a `VERBOSE` log level
  * Properly implemented filtering for `error.log` and `warning.log`
  * Constructors updated to support multiple configuration files
* Universal Flow Configuration Variables
  * Created `TRISTATE_CELLS`, accepting `TRISTATE_CELL_PREFIX` from OpenLane 1
    with translation behavior
  * Created new PDK variable `MAX_CAPACITANCE_CONSTRAINT`
    * Also added to `base.sdc`
  * Created new variable `EXTRA_EXCLUDED_CELLS`, which allows the user to
    exclude more cells throughout the entire flow
  * Renamed `PRIMARY_SIGNOFF_TOOL` to `PRIMARY_GDSII_STREAMOUT_TOOL` with
    translation behavior
  * Renamed `GPIO_PADS_PREFIX` to `GPIO_PAD_CELLS` with translation behavior
  * Renamed `FP_WELLTAP_CELL` to `WELLTAP_CELL` with translation behavior
  * Renamed `FP_ENDCAP_CELL` to `ENDCAP_CELL` with translation behavior
  * Renamed `SYNTH_EXCLUSION_CELL_LIST` to `SYNTH_EXCLUDED_CELL_FILE` with
    translation behavior
  * Renamed `PNR_EXCLUSION_CELL_LIST` to `PNR_EXCLUDED_CELL_FILE` with
    translation behavior
* `SynthesisExploration`
  * Added new flow, `SynthesisExploration`, that tries all synthesis strategies
    in parallel, performs STA and reports key area and delay metrics
* `Classic`
  * `ApplyDEFTemplate` now takes precedence over `CustomIOPlacement`, matching
    OpenLane 1
  * Added `Checker.PowerGridViolations` to the flow, gated by
    `QUIT_ON_PDN_VIOLATIONS` (which has a deprecated name of
    `FP_PDN_CHECK_NODES`) for back-compat with OpenLane 1 configurations
  * Added `Checker.SetupViolations`, `Checker.HoldViolations` to the end of the
    flow
    * Both gated by `QUIT_ON_TIMING_VIOLATIONS`
    * Each gated by `QUIT_ON_SETUP_VIOLATIONS`, `QUIT_ON_HOLD_VIOLATIONS`
      respectively

## Tool Updates

* Repository turned into a [Flake](https://nixos.wiki/wiki/Flakes) with
  `openlane` as the default output package and the previous shell environment as
  the default output devShell
  * `flake-compat` used so `nix-shell` continues to work as you'd expect for
    classic nix
* All package `.nix` files
  * Now follow the `nixpkgs` convention of explicitly listing the dependencies
    instead of taking `pkgs` as an argument
  * Have a `meta` field
* Reformatted all Nix code using
  [alejandra](https://github.com/kamadorueda/alejandra)
* Updated Open PDKs to `bdc9412`
* Updated OpenROAD to `75f2f32`
  * Added some conveniences for manual compilation to the Nix derivation
* Updated Volare to `0.16.0`/`4732594`
  * New class in API, the `Family` class, helps provide more meaningful error
    reporting if the user provides an invalid PDK variant (and resolves to a
    variant if just a PDK name is provided)
* Updated Yosys to `0.38`/`543faed`
  * Added Yosys F4PGA SDC plugin (currently unused)
* Added KLayout's python module to the explicit list of requirements

## Testing

* Added various [IPM](https://github.com/efabless/ipm) designs to the CI
* Added a full caravel user project example (wrapper + example) to the CI
* Greatly expanded unit tests for individual steps

## Misc. Enhancements/Bugfixes

* Created new folder in module, `examples` which contains example designs (of
  which `spm` is used as a smoke test)
* `__main__`
  * Two new commandline flags added
  * `--save-views-to`: Saves all views to a directory in a structure after
    successful flow completion using `State.save_snapshot`
  * `--ef-save-views-to`: Saves all views to a directory in the Efabless
    format/convention, such as the one used by Caravel User Project.
* `openlane.logging`
  * `LogLevels` is now an IntEnum instead of a class with global variables
  * Create a custom formatter for logging output instead of passing the
    formatting options as text to the logger
  * Created new log level, `SUBPROCESS`, between `DEBUG` and `VERBOSE`, and made
    it the new default
  * Create a separate handler for logs with level `SUBPROCESS` that doesn't
    print timestamps, level, etc
  * New global singleton `options` created, which allows to configure both:
    * `condensed_mode`: boolean to make the logs terser and suppress messages
      with `SUBPROCESS` level unconditionally
    * `show_progress_bar`: boolean, self-explanatory
  * **API Break**: Removed `LogLevelsDict`, LogLevels[] now works just fine
  * Changed all instances of `WARN` to `WARNING` for consistency
  * Fixed bug where `VERBOSE` logging in internal plain output mode simply used
    `print`
* `openlane.state`
  * Added new `DesignFormat`: `VERILOG_HEADER`
* `openlane.common`
  * `Toolbox`
    * Objects no longer create a folder immediately upon construction
    * `remove_cells_from_lib` now accepts wildcard patterns to match against
      cells (to match the behavior of OpenROAD steps)
    * `get_macro_views` can now take more than one `DesignFormat` for
      `unless_exist`
  * New `click` type, `IntEnumChoice`, which turns integer enums into a set of
    choices accepting either the enum name or value
  * New function `process_list_file` to process `.gitignore`-style files (list
    element/comment/empty line)
* `openlane.config`
  * Updated to support an arbitrary number of a combination of Tcl files, JSON
    files and python dictionaries (or any object conforming to `Mapping`) to
    create configuration files, each with their own `Meta` values
  * `design_dir` can now be set explicitly, but if unset will take `dirname` of
    last config file passed (if applicable)
  * Internally unified how Tcl-based configurations and others are parsed
  * `Instance` fields `location`, `orientation` now optional
  * `Macro` has two new views now, `vh` and `pnl`
  * New `DesignFormat` added: * `openlane.config.DesignFormat`
* `openlane.steps`
  * `__main__`
    * Use default `--pdk-root` for `run` command
  * `Step`
    * `load()`'s pdk_root flag can now be passed as `None` where it will default
      to `cwd`
    * New method `load_finished()` to load concluded steps (which loads the
      output state and step directory)
    * `factory`
      * New method `from_step_config()` which attempts to load a step from an
        input configuration file
        * Reworked step-loading function to use `from_step_config()` where
          appropriate
    * `create_reproducible()`
      * Added `flatten` to public API, which flattens the file structure with
        the exception of the PDK, which is saved to `pdk/$PDK`
      * Modified behavior of flatten to allow including the PDK (which isn't
        flattened)
      * Generated `run_ol.sh` now passes ARGV to the final command (backwards
        compatible with old behavior)
        * Primary use for this: `run` command now accepts `--pdk-root` flag
    * Added runtime to `*.process_stats.json`
  * `openlane.flows`
    * Added new instance variable, `config_resolved_path`, which contains the
      path to the `resolved.json` of a run
    * Flows resuming existing runs now load previously concluded steps into
      `self.step_objects` so they may be inspected
* Fixed an issue where Docker images did not properly have dependencies of
  dependencies set in `PYTHONPATH`.
* Fixed a corner case where some OpenLane 1 JSON configs that use Tcl-style
  dicts that include paths would fail conversion to a Python dict
* Fixed a bug with ejected reproducible scripts keeping some nix store paths.
* Fixed Docker images not having `TMPDIR` set by default
* Updated Nix overlays to detect Darwin properly, added another fix for `jshon`
* Updated Nix derivation to ignore `__pycache__` files
* Suppressed tracebacks in more situations (too shouty)
* Removed `PYTHONPATH` from `default.nix` - OpenLane now passes its
  `site-packages` to subprocesses (less jank) (but still a bit jank)

## API Breaks

* Universal Flow Configuration Variables
  * `CTS_ROOT_BUFFER`, `CTS_CLK_BUFFERS` and `CTS_MAX_CAP` all moved to
    `OpenROAD.CTS`
  * `IGNORE_DISCONNECTED_MODULES` moved to `Odb.ReportDisconnectedPins`
  * `GPL_CELL_PADDING` moved to `OpenROAD.GlobalPlacement`
  * `DPL_CELL_PADDING` moved to steps that have the rest of the `dpl` variables
  * `GRT_LAYER_ADJUSTMENTS` moved to steps that have the rest of the routing
    layer variables
  * Moved `GRT_OBS` to `Odb.AddRoutingObstructions` as a deprecated name for
    `ROUTING_OBSTRUCTIONS`
  * Removed `FP_CONTEXT_DEF`, `FP_CONTEXT_LEF`, and `FP_PADFRAME_CFG`: To be
    implemented
  * Removed `LVS_INSERT_POWER_PINS`, `RUN_CVC`, `LEC_ENABLE`,
    `CHECK_ASSIGN_STATEMENTS`
* Moved `DesignFormat`, `DesignFormatObject` from `openlane.common` to
  `openlane.state`
* `openlane.common.Toolbox.remove_cells_from_lib` no longer accepts
  `as_cell_lists` as an argument, requiring the use of `process_list_file`
  instead
* Removed `LogLevelsDict`, `LogLevels[]` now works just fine

## Documentation

* Added Glossary
* Added FAQ
* Added note on restarting Nix after configuring the Cachix substituter
* Added a first stab at (conservative) minimum requirements for running
  OpenLane- you can definitely get away with less at your own risk
* Added extensions to make the documentation better to write and use:
  * `sphinx-tippy` for tooltips
  * `sphinx-copybutton` for copying terminal commands
  * `sphinxcontrib-spelling` so we don't write "Verliog"
* Custom extension so Flows, Steps and Variables can be referenced using custom
  MyST roles
* Added a new target to the `Makefile`, `watch-docs`, which watches for changes
  to rebuild the docs (requires `nodemon`)
* Separated the "Getting Started" guide into a tutorial for newcomers and a
  migration guide for OpenLane veterans
* Changed *all* `.png` files to `.webp` (saves considerable space, around 66%
  per image)
* Updated all Microsoft Windows screenshots to a cool 150% UI scale
* Updated generated documentation for steps, flows and universal configuration
  variable
* Updated Readme to reflect `aarch64` support
* Updated docstrings across the board for spelling and terminology mistakes

# 2.0.0b16

## Steps

* All:
  * Changed type of `DIE_AREA` and and `CORE_AREA` to
    `Optional[Tuple[Decimal, Decimal, Decimal, Decimal]]`
* `KLayout.*`:
  * Propagated `venv` sitepackages to `PYTHONPATH`
  * Rewrote scripts to use either the Python API or use arguments passed via
    `KLAYOUT_ARGV` instead of the weird `-rd` pseudo-serialization
* `KLayout.XOR`:
  * Fixed threads not working properly
  * `KLAYOUT_XOR_THREADS` is now optional, with the thread count being equal to
    your thread count by default
  * Added new variable, `KLAYOUT_XOR_TILE_SIZE`, which is the size of the side
    of a tile in microns (the tile size must be sufficiently smaller than the
    design for KLayout to bother threading)
  * Added `info` prints for thread count
* `Magic.*`:
  * Base `MagicStep` no longer overrides `run`, but does override
    `run_subprocess`
  * `openlane/scripts/magic/common/read.tcl` is now a list of read-related Tcl
    functions used across all Magic scripts
  * Added new variable `MAGIC_CAPTURE_ERRORS` to best-effort capture and throw
    errors generated by Magic.
* `Magic.StreamOut`:
  * Internally set `MAGTYPE` to `mag`
  * Change sequence as follows
    * Old sequence:
      1. Read tech LEF
      1. Read macro LEF views (if applicable)
      1. Read design DEF
      1. Read macro GDS views (if applicable)
      1. Write final GDS
    * New sequence:
      1. Read tech LEF
      1. Read PDK SCL/GDS
      1. Depending on the value of `MAGIC_MACRO_STD_CELL_SOURCE`, if applicable:
         * Read macro GDS views as a black-box
         * Read macro GDS views, de-referencing standard cells (i.e. using PDK
           definitions)
      1. Write final GDS
    * Rationale: The old flow triggers a bug where references for cells inside a
      macro's GDS view were broken broken. A workaround was suggested by Tim
      Edwards and the new flow was adapted from his workaround.
      * Additionally, the new flow is just plain more explicit and
        straightforward.
  * Updated to throw errors when `MAGIC_MACRO_STD_CELL_SOURCE` is set to `macro`
    and:
    * Multiple GDS files are defined per macro
    * A macro's GDS file does not have a PR boundary
* `Odb.*`
  * Added `openlane/scripts/odbpy` to `PYTHONPATH`
  * Propagated `venv` sitepackages to `PYTHONPATH`
  * `openlane/scripts/odbpy/defutil.py`:
    * Added validation for obstruction commands
    * Added exit codes for validation errors in obstruction commands
    * Added a command to remove obstructions
    * Enhanced obstructions regex matching to account for >5 items in an
      obstruction definition.
* Created obstruction-related steps
  * `Odb.AddRoutingObstructions`: Step for adding metal-layer obstructions to a
    design
  * `Odb.RemoveRoutingObstructions`: Step for removing metal-layer obstructions
    from a design.
    * The preceding two steps, and their derivatives, should be used in tandem,
      i.e., obstructions should be added then removed later in the flow.
  * `Odb.AddPDNObstructions`: A subclass of `Odb.AddRoutingObstructions` that
    adds routing (metal-layer) obstructions that apply only to the PDN, using
    the variable `PDN_OBSTRUCTIONS`. Runs before PDN generation.
  * `Odb.RemovePDNObstructions`: A subclass `Odb.RemoveRoutingObstructions` that
    removes obstructions added by `Odb.AddPDNObstructions`.
* `Odb.DiodesOnPorts`, `Odb.HeuristicDiodeInsertion`:
  * Now automatically runs DPL and GRT to legalize after insertion
  * Old behavior kept using new steps: `Odb.PortDiodePlacement` and
    `Odb.FuzzyDiodeInsertion`.
  * Updated underlying script to have some more debugging options/be more
    resilient
  * Fixed a bug where attempting to insert another diode of the same name would
    cause a crash
* `OpenROAD.*`:
  * Added three new entries to set of DesignFormats:
    * `POWERED_NETLIST_SDF_FRIENDLY`
    * `POWERED_NETLIST_NO_PHYSICAL_CELLS`
    * `OPENROAD_LEF`
  * Added `openlane/scripts/odbpy` to `PYTHONPATH`
  * Propagated `venv` sitepackages to `PYTHONPATH`
* `OpenROAD.WriteViews`
  * Writes the aforementioned new design formats
* `OpenROAD.CTS`, `CVCRV.ERC` (unused):
  * Replaced legacy calls to `Step.run` causing crashes in some situations
* Created `OpenROAD.CutRows`
* `OpenROAD.CutRows`, `OpenROAD.TapDecapInsertion`:
  * Renamed `FP_TAP_VERTICAL_HALO` to `FP_MACRO_VERTICAL_HALO`,
    `FP_TAP_HORIZONTAL_HALO` to `FP_MACRO_HORIZONTAL_HALO`
    * Rationale: Halo doesn't only affect tap insertion, it also affects cut
      rows generated in the floorplan. This affects cell insertion and power
      rails and anything related to floorplan and std cell placement.
* `OpenROAD.DetailedRouting`:
  * Added `info` prints for thread count
* `OpenROAD.Floorplan`:
  * Added new variable `FP_OBSTRUCTIONS` to specify obstructions during
    floorplanning
  * Added a new PDK variable, `EXTRA_SITES`, which specifies additional sites to
    use for floorplanning (as overlapping rows) even when:
    * Cells without double-heights are not used
    * Double-height cells with missing or mislabeled LEF `SITE`(s) are used
* Part of `OpenROAD.GlobalRouting` spun off as `OpenROAD.RepairAntennas`
  * Added `OpenROAD.RepairAntennas` to `Classic` flow after
    `Odb.HeuristicDiodeInsertion`; gated by `RUN_ANTENNA_REPAIR` (with a
    deprecated name of `GRT_REPAIR_ANTENNAS` for backwards compat)
* `OpenROAD.IOPlacement`, `OpenROAD.GlobalPlacementSkipIO`
  * Added new value for `FP_IO_MODE` which places I/O pins by annealing
* `OpenROAD.ResizerTiming*`:
  * Added `PL_RESIZER_GATE_CLONING` and `GRT_RESIZER_GATE_CLONING` respectively,
    which control OpenROAD's ability to perform gate cloning while running
    `repair_timing` (default: `true`)
* `OpenROAD.STAPostPNR`
  * Added `timing__unannotated_nets__count` to record number of annotated nets
    reports during post-PnR STA
  * Added `timing__unannotated_nets_filtered__count` which filters the former's
    count based on whether a net has a wire. A wire indicates if a net has
    physical implementation. If a net doesn't have a wire then it can be waived
    and filtered out.
* `Verilator.Lint`:
  * Fixed bug where inferred latch warnings were not properly processed
* `Yosys.*Synthesis`:
  * Per comments from Yosys Team
    [(1)](https://github.com/YosysHQ/yosys/issues/4039#issuecomment-1817937447)
    [(2)](https://github.com/The-OpenROAD-Project/OpenLane/pull/2051#issuecomment-1818876410)
    * Replaced instances of ABC command `rewrite` with `drw -l` with new
      variable `SYNTH_ABC_LEGACY_REWRITE` being set to `true` restoring the
      older functionality (`false` by default)
    * Replaced instances of ABC command `refactor` with `drf -l` with new
      variable `SYNTH_ABC_LEGACY_REFACTOR` being set to `true` restoring the
      older functionality (`false` by default)
  * New variable, `USE_SYNLIG`, enables the use of the Synlig frontend in place
    of the Yosys Verilog frontend for files enumerated in `VERILOG_FILES`
    (disabled **by default**)
  * New variable, `SYNLIG_DEFER`, enables the experimental `-defer` feature (see
    [this part of Synlig's readme](https://github.com/chipsalliance/synlig#example-for-parsing-multiple-files))
    (disabled by default)
  * Underlying scripts reworked to unify how Verilog files, preprocessor
    definitions and top level parameters are handled
  * Exempt SystemVerilog `"$assert"s` from "unmapped cells"
  * Metric `design__latch__count` renamed to `design__inferred_latch__count`
  * Fixed `SYNTH_NO_FLAT` not working.

## Flows

* `Classic` flow
  * `Odb.DiodesOnPorts` and `Odb.HeuristicDiodeInsertion` now run after
    `OpenROAD.RepairDesignPostGRT` (as the latter may create some long wires)
    but still before `Odb.ResizerTimingPostGRT` (as timing repairs take
    priority)
  * `OpenROAD.CheckAntennas` added after `OpenROAD.DetailedRouting`
  * `OpenROAD.CutRows` added before `OpenROAD.TapDecapInsertion`
  * `OpenROAD.AddPDNObstructions` and `OpenROAD.RemovePDNObstructions` now
    sandwich `OpenROAD.GeneratePDN`
* Internally updated implementation of `VHDLClassic` flow to dynamically create
  `.Steps` from `Classic`

## Documentation

* `docs/source/index`:
  * Changed markup language from RST to Markdown
  * Better disambiguation between OpenLane 1 and OpenLane 2
  * Removed reference to unused utilities
  * Hid top-level `toctree` polluting the landing page
  * Fixed links to incorrect repository
* Corners and STA: Now indexed; details some violations
* Updated documentation of `openlane.config.Variable.pdk` to make it a bit
  clearer

## Tool Updates

* Nix:
  * Upgraded Nix Package Pin to `3526897`
  * Added support for `aarch64-linux` and `aarch64-darwin`
  * Created new overlays:
    * `cbc`: Use c++14 instead of the default c++17 (`register` declarations)
    * `lemon-graph`: `sed` patch `register` declaration
    * `spdlog-internal-fmt`: `spdlog` but with its internal `fmt` as the
      external `fmt` causes some problems
    * `clp` to support `aarch64-linux`
    * `cairo`: to enable X11 support on macOS
    * `or-tools`: to use a new SDK on `x86-64-darwin` (see
      [this](https://github.com/NixOS/nixpkgs/issues/272156#issuecomment-1839904283)
    * `clp` to support `aarch64-linux`
  * Reworked Nix derivations for the OpenLane shell, OpenLane, and the Docker
    image
    * Made OpenLane 2's `src` derivation allowlist-based rather than
      gitignore-based (smaller `source` derivations)
    * Added a new argument to `default.nix`, `system`, as
      `builtins.currentSystem` is not available when using nix flakes (where in
      documentation it is described as "non-hermetic and impure": see
      https://nixos.wiki/wiki/Flakes). This change allows passing the system as
      argument and thus restores compatibility with nix flakes.
* Completely revamp Notebook
  * Rewrite Nix setup section to be more tolerant of non-Colab setups
  * Rewrite OpenLane dependencies to use a better method of installing
    OpenLane's dependencies/hack in `tkinter` if it's missing (as it will be on
    local environments)
  * Added descriptions for *all steps used*
  * Added RCX, STAPostPNR, LVS and DRC
* Added [Surelog](https://github.com/chipsalliance/surelog) to the included
  utilities
* Extended CI to handle Linux aarch64 builds
* Excluded yosys-ghdl plugin from ARM-based builds and from macOS - never worked
* Upgraded KLayout to `0.28.13`
  * Made KLayout derivation more orthodox- distinct configure, build and install
    steps
  * Made KLayout Python modules available to all Python scripts
  * macOS: All KLayout Mach-O binaries patched to find the correct dylibs
    without `DYLD_LIBRARY_PATH`
* Upgraded Magic to `83ed73a`
  * Enabled `cairo` support on macOS, which allows Mac users to use the Magic
    GUI
  * Removed `mesa_glu` on macOS
* Fixed Yosys plugins propagating Yosys, causing conflicts
* Updated unit tests to work with some env changes in Python 3.11
* Removed `StringEnum`
* Updated OpenPDKs to `e0f692f`
* Updated OpenROAD to `6f9b2bb`
  * OpenSTA is now built **standalone** just like `openroad-abc` for modularity
    purposes
  * Fixes issue where post-GRT resizing run-time and memory consumption got out
    of hand: see
    https://github.com/The-OpenROAD-Project/OpenROAD/issues/4121#issuecomment-1758154668
    for one example
* Updated Verilator to `v5.018` to fix a couple crashes, including a persistent
  one with `spm` on Apple Silicon
* Updated Volare to `0.15.1`
  * OpenLane now doesn't attempt to `enable` when using `volare`- it points the
    `Config` object to the specific version directory for said PDK
* Updated Yosys to `0.34`/`daad9ed`
  * Added the
    [Synlig Yosys SystemVerilog Plugin](https://github.com/chipsalliance/synlig)

## API Breaks

* `openlane.steps.step.Step.load`: Argument `state_in_path` renamed `state_in`,
  also takes `State` objects
* `openlane.config.Config`:
  * For JSON configurations using `meta.version = 2`, `DIE_AREA` and `CORE_AREA`
    can no longer be provided as strings, and must be provided as an array of
    four numeric elements.
  * Removed global state when `Config.interactive` is used, `state_in` now
    explicitly required
    * Rationale: the little convenience offered is far outdone by the annoyance
      of most steps being non re-entrant, so trying to run the same cell twice
      is almost always a crash.
* `OpenROAD.CTS`:
  * Removed `CTS_TOLERANCE`: no longer supported by OpenROAD
* `OpenROAD.Floorplan`:
  * Removed `PLACE_SITE_HEIGHT` and `PLACE_SITE_WIDTH`: redundant
* `OpenROAD.GlobalRouting`:
  * Removed `GRT_REPAIR_ANTENNAS`. See details above.
* `Odb.DiodesOnPorts`, `Odb.HeuristicDiodeInsertion`:
  * Updated `HEURISTIC_ANTENNA_THRESHOLD` to be a non-optional PDK variable with
    default variables added in `openlane/config/pdk_compat.py`
* `Magic.StreamOut`:
  * Removed `MAGIC_GDS_ALLOW_ABSTRACT`: Bad practice
* Removed `openlane.common.StringEnum`: Use `Literal['string1', 'string2', …]`

## Misc. Enhancements/Bugfixes

* Added exit code propagation when a `StepError` is caused by
  `CalledProcessError`
* Added default Toolbox when Toolbox is not defined for a step
* Created a `.process_stats.json` file for every subprocess that has general
  statistics about a process's total elapsed time and resource consumption
* Created method `openlane.common.Path.startswith`
* Expanded `openlane.common.copy_recursive` to support dataclasses
* `openlane.state.State._repr_html_` to better handle recursive outputs.
* `openlane.config.Config`
  * Fixed bug in private methods where `pdkpath` was not being set in some
    scenarios
  * Fixed `_repr_markdown_` to use correct syntax identifier for YAML in
    Markdown
* Fixes and tweaks for step reproducibles:
  * `openlane.steps create-reproducible` has new flag, `--no-include-pdk`, which
    excludes PDK files from reproducibles and make any reference to them utilize
    `pdk_dir::`
  * Slight internal rework for `openlane.steps.Step.create_reproducible` to
    support flattened file structures suitable for testing
  * Reproducibles now no longer include views of the design not explicitly
    declared in step `.inputs`
* Fixed tuple loading for config variables
* Fixed unit test for tuple loading for config variables
* Fixed missing orientations for MACRO variables

## Testing

* Created step unit testing infrastructure, relying on specially-laid out
  folders that provide input data with the ability to add a per-step input data
  preprocessor and output
  * Requires `--step-rx` flag to be passed to `pytest`
  * Created submodule to host step tests
  * Added step to Nix build that utilizes the step unit testing infrastructure
  * Some space/data duplication avoidance measures: Allow missing `state.json`
    for empty state and creation of `.ref` files
* Created a new internal subcommand, `openlane.steps create-test`, which creates
  a flat reproducible that can be more easily added as a step unit
* Ported `aes_user_project_wrapper` from OpenLane 1
* Added `user_proj_timer` from
  https://github.com/efabless/openframe_timer_example/tree/main/openlane/user_proj_timer
* Changed `manual_macro_placement_test` design to have a macro with orientation
  `FN` as a test for the aforemention
* Enable post-GRT resizer for `aes_core`, `spm` and `aes`
* Disabled latch linting for `salsa20`

# 2.0.0b15

* Added IcarusVerilog as a dependency to OpenLane, and GTKWave as a Nix shell
  dependency
* Added power metric reporting to OpenSTA-based steps
* Updated OpenROAD to `bdc8e94`
* Updated Yosys to 0.33 / `2584903`
  * Changed Yosys build process to use an external ABC as ABC takes 8 billion
    years to build (estimate)
  * Patched Yosys and dependent utilities to use BSD libedit
  * Reimplemented how Yosys plugins work in Nix, so they're all loaded with
    Yosys
    * Added derivations for:
      * [SymbiYosys](https://github.com/YosysHQ/sby)
      * [eqy](https://github.com/YosysHQ/eqy)
      * [Lighter](https://github.com/YosysHQ/eqy)
      * [GHDL Yosys Plugin](https://github.com/ghdl/ghdl-yosys-plugin)
  * Created `Yosys.EQY`, a step based on EQY that runs at the very end of the
    flow comparing the RTL inputs and outputs (disabled by default)
  * Modified `Yosys.Synthesis` to support Lighter, which greatly reduces power
    consumption by clock-gating D-flipflops (disabled by default, set
    `USE_LIGHTER` to true to activate)
  * Created new step, `VHDLSynthesis`
    * Created new experimental flow, `VHDLClassic`, incorporating said step and
      removing Verilog-specific steps
* Latches without `always_latch` are now reported as a lint error if the
  variable `LINTER_ERROR_ON_LATCH` is set to `True` (which it is by default)
  * Added latch design to fastest test set for both supported PDKs
* Fixed a race condition with `openlane/steps/step.py::Step::run_subprocess`
* Fixed a bug where `glob` introduced nondeterminism, as glob returns files in
  an arbitrary order on some filesystems:
  https://docs.python.org/3.8/library/glob.html?highlight=sorted
  * All `glob` results were simply sorted.
* Fixed a bug where `openlane/common/toolbox.py::Toolbox::create_blackbox_model`
  constructs and uses an invalid Path.
* Fixed `Checker.YosysSynthChecks` ID to match class name
* Fixed `Odb.SetPowerConnections` missing from step factory
* Fixed `OpenROAD.GlobalRouting` missing `GRT_ANTENNA_MARGIN` from OpenLane 1
* Fixed `Verilator.Lint` incorrectly calling Verilator by appending the list of
  defines to the list of files
* Renamed `SYNTH_DEFINES` to `VERILOG_DEFINES` with translation behavior
* Renamed `SYNTH_POWER_DEFINE` to `VERILOG_POWER_DEFINE` with translation
  behavior
* Removed `SYNTH_READ_BLACKBOX_LIB`, now always loaded

# 2.0.0b14

* Added `PNR_SDC_FILE` to all OpenROAD steps
* Added `SIGNOFF_SDC_FILE` to `OpenROAD.STAPostPNR`
* Added `report_design_area_metrics` to OpenROAD scripts that potentially modify
  the layout
* Added comprehensive documentation on PDKs
* Added documentation for migrating the Macro object
* Added validation for unknown keys for the Macro object
* Added testing for `openlane.common.toolbox::Toolbox::create_blackbox_model`,
  `openlane.common.toolbox::Toolbox::get_lib_voltage`,
  `openlane.flows.sequential::SequentialFlow::__init_subclass__`=
* Updated OpenROAD to `0a6d0fd`: **There is an API break in OpenDB APIs**:
  * `odb.read_def` now takes a `dbTech` and a Path string instead of a
    `dbDatabase` and a Path string.
  * The `dbTech` object can be obtained via the `getTech` method on `dbDatabase`
    objects: `db.getTech()`, for example.
  * Liberty files without default operating conditions break in PSM-
    `libparse-python` added as a workaround until the PDKs are fixed
* `BASE_SDC_FILE` renamed to `FALLBACK_SDC_FILE` with translation
  * Move `FALLBACK_SDC_FILE` to universal flow variables
* OpenROAD scripts internally now always read `SDC_IN` instead of `CURRENT_SDC`
  * SDC_IN set to either `PNR_SDC_FILE` or `SIGNOFF_SDC_FILE` by the appropriate
    steps
* Reimplemented I/O placement in the Classic flow based on the one in ORFS,
  i.e.:
  > "We start the loop in ORFS by ignoring io placement while doing global
  > placement, then do io placement, then re-run global placement considering
  > IOs. Its not perfect but that's the use." - @maliberty
* `open_pdks` -> `dd7771c`
* Volare -> `0.12.8`
* Changed gf180mcu tests to use `gf180mcuD`, the new recommended variant of
  gf180mcu
* Fixed bug with gating config variables with wildcards only affecting the first
  matching step
* Fixed detecting if `PL_TARGET_DENSITY_PCT` is not defined
* Fixed antenna repair: now re-legalizes after repair which was missing
  * Fixed failing designs in Extended Test Set

# 2.0.0b13

* Add Linting
  * Added Nix derivation for:
    [Verilator](https://github.com/verilator/verilator)
  * Added the following steps:
    * `Verilator.Lint`
    * `Checker.LintTimingConstructs`
    * `Checker.LintWarnings`
  * Emplaced the three new steps at the beginning of the flow
  * Added `Classic` flow variable:
    * `RUN_LINTER` w/ deprecated name (`RUN_VERILATOR`)
  * Added step variables:
    * `QUIT_ON_LINTER_ERRORS` -w/ deprecated name (`QUIT_ON_VERILATOR_ERRORS`)
    * `QUIT_ON_LINTER_WARNINGS` w/ deprecated name
      (`QUIT_ON_VERILATOR_WARNINGS`)
    * `QUIT_ON_LINTER_TIMING_CONSTRUCTS`
    * `LINTER_RELATIVE_INCLUDES` w/ deprecated (`VERILATOR_REALTIVE_INCLUDES`)
    * `LINTER_DEFINES`
  * Added metrics:
    * `design__lint_errors__count`
* Added support for `Flow`-specific configuration variables
  * Added a `config_vars` property to `Flow`
  * Added a `gating_config_vars` property to `SequentialFlow`, essentially
    replacing `flow_control_variable` (breaking change) with deprecation
    warnings for the latter
  * Added more consistent runtime handling of "abstract class properties"
  * Folded *all* OpenLane 1-style `RUN_` variables into Classic Flow
* Added an undocumented CVC step- upstream no longer supporting CVC in flows
* open_pdks -> `1341f54`
* yosys -> `14d50a1` to match OL1
* Restored ancient `{DATA,CLOCK}_WIRE_RC_LAYER` variables, with translation
  behavior from `WIRE_RC_LAYER` to `DATA_WIRE_RC_LAYER`
* Created new PDK variable `CELL_SPICE_MODELS` to handle .spice models of the
  SCLs instead of globbing in-step
* Changed default value of `MAGIC_DRC_USE_GDS`
* Fixed an issue where CI would fail when `vars.CACHIX_CACHE` is not defined
  (affected pull requests)
* Fixed an issue with Nix in environment surveys
* Fixed an issue where `openlane/scripts/openroad/pdn.tcl` used a deprecated
  name for a variable
* Fixed a bug where KLayout category names were lacking enclosing single quotes
* Fixed a number of broken links and entries in the documentation

# 2.0.0b12

* Added diode padding to `dpl_cell_pad.tcl`
* Added `FULL_LIBS` to `YosysStep` without any redactions
* Moved all PDN variables to the the `OpenROAD.GeneratePDN` step as
  step-specific PDK variables
* Updated PDN documentation to make sense and added an illustrated diagram of
  values
* Slightly reordered Classic Flow so detailed placement happens right after
  `Odb.HeuristicDiodeInsertion`
* Fixed translation of `FP_PDN_MACRO_HOOKS` when a string is provided (only
  splitting if a `,` is found)
* Removed extraneous `check_placement -verbose` after `common/dpl.tcl` sources
  in OpenROAD scripts

# 2.0.0b11

* Added new `mag` format to design formats, populated by `Magic.StreamOut`
* Added support for `stdin` in reproducibles (mainly for Magic): ejected
  reproducibles now save the input and use it
* Added three new PDK variables to all Magic-based steps: `MAGIC_PDK_SETUP`,
  `CELL_MAGS`, and `CELL_MAGLEFS`, which explicitly list some files Magic
  constructed from `PDK_ROOT`, as well as codifying a convention that variables
  must explicitly list files being used.
* Added new variable to `Magic.SpiceExtraction`, `MAGIC_EXT_ABSTRACT`, which
  allows for cell/submodule-level LVS rather than transistor-level LVS.
* Changed SPEF file saving to only strip asterisks instead of underscores as
  well, matching the folders
* Fixed an issue where OpenLane's type-checking only accepted a single value for
  Literals in violation of
  ["Shortening unions of literals," PEP-586](https://peps.python.org/pep-0586/#shortening-unions-of-literals)
* Fixed an issue where command-line overrides were still treated as strict
  variables
* Fixed an issue where `rule()` would print a line even when log levels would
  not allow it
* Fixed an issue where `PDK_ROOT` was of type `str`
* Updated documentation to provide information on conventions for declaring
  variables
  * Deprecated `StringEnums`, now favoring `Literal['str1', 'str2', …]`

# 2.0.0b10

* Add new commandline options: `--docker-tty/--docker-no-tty`, controlling the
  `-t` flag of Docker and compatible container engines which allocates a virtual
  tty
* Convert CI to use `--dockerized` instead of a plain `docker run`

# 2.0.0b9

* `Flow.start()` now registers two handlers, one for errors and one for
  warnings, and forwards them to `step_dir/{errors,warnings}.log` respectively
* Created `CELL_SPICE_MODELS` as a PDK variable to handle .spice models of the
  SCLs instead of globbing in-step
* Added a "dummy path" for macro translation purposes that always validates and
  is ignored by `self.toolbox.get_macro_views`
* Reduced reliance on absolute paths
  * Special exception carved out for `STEP_DIR`, `SCRIPTS_DIR`
  * Made KLayout scripts more resilient to relative pathing
* Created new "eject" feature, which would make reproducibles for steps relying
  on subprocesses independent of OpenLane
  * `scripts` directory copied in entirety into ejected reproducibles
* Updated Open PDKs to `e3b630d`
* Updated Yosys to `14d50a1`
* Updated CI to handle missing `vars.CACHIX_CACHE`
* Updated Volare to `0.12.3` to use new authentication and user agent
* Downgraded Magic to `0afe4d8` to match OL1
* Restored ancient `{DATA,CLOCK}_WIRE_RC_LAYER` variables, with translation
  behavior from `WIRE_RC_LAYER` to `DATA_WIRE_RC_LAYER`
* Fixed issue with `Step.load()` re-validating values, which affected
  reproducibles
* Timing signoff no longer prints if log level is higher than `VERBOSE`
* Use `parse_float=Decimal` consistently when loading JSON strings to avoid fun
  floating point errors
* Removed dependency on State module from `odb` scripts
* Removed custom PYTHONPATH setting from `OdbStep` (which was mostly to mitigate
  problems fixed in #86)

# 2.0.0b8

* Rename incorrectly-named metric rename `clock__max_slew_violation__count` to
  `design__max_slew_violation__count`
* Fix clock skew metric aggregation by using `-inf` instead of `inf`

# 2.0.0b7

* Internally reworked `Config` module
  * `Variable` objects now have a Boolean property, `.pdk`, which is set to
    `True` if the variable is expected to be provided by the PDK
  * List of common flow variables now incorporate both option config variables
    *and* PDK config variables, with the aforementioned flag used to tell them
    apart.
  * Individual `Step`s may now freely declare PDK variable, with the implication
    that if a `Flow` or one of its constituent `Step`s has one or more variables
    not declared by the current PDK, the `Step` (and `Flow`) are incompatible
    with the PDK.
  * Mutable data structures are used during the construction of `Config` to
    avoid constant copying of immutable dictionaries
    * Multiple private instance methods converted to private `classmethod`s to
      deal with mutable data structures instead of constantly making `Config`
      copies
  * Getting raw values from the PDK memoized to avoid having to call the Tcl
    interpreter repeatedly
  * All `Step` objects, not just those used with an interactive configuration,
    can now be given overrides upon construction using keyword arguments.
* A number of previously-universal PDK variables are now declared by the `Step`s
  and made non-optional, i.e., the `Step` can expect them to be declared by the
  PDK if the configuration is successfully validated.
* `PDK`, `PDK_ROOT` are no longer considered "PDK" variables as PDK variables
  depend on them
* `PRIMARY_SIGNOFF_TOOL` now a PDK variable and a string so OpenLane is not
  limited to two signoff tools
* `Toolbox.render_png()` now relies on a new `Step` called `KLayout.Render`
* `Config.interactive()` fixed, new Nix-based Colab notebook to be uploaded
  Soon™
* Assorted documentation updates and bugfixes

# 2.0.0b6

* Added `Odb.ApplyDEFTemplate` to `Classic` Flow
* Added `RUN_TAP_DECAP_INSERTION` as a deprecated name for
  `RUN_TAP_ENDCAP_INSERTION`

# 2.0.0b5

* Added `refg::` to documentation
* Fixed issue where "worst clock skew" metrics were aggregated incorrectly
* Fixed issue with referencing files outside the design directory

# 2.0.0b4

* Updated documentation for `run_subprocess`
* Updated Volare to `0.11.2`
* Fixed a bug with `Toolbox` method memoization
* Unknown key errors only emit a warning now if the key is used as a Variable's
  name *anywhere* linked to OpenLane. This allows using the same config file
  with multiple flows without errors.

# 2.0.0b3

* Added ability to create reproducible for any step using instance method
  `Step.create_reproducible()`
* Added ability to load and run Step from Config and State JSON files, working
  for both existing step folders and new reproducibles
* Added new CLI- under either the script `openlane.steps` or
  `python3 -m openlane.steps`, exposing the two functionalities above.
* Added internal ability to load a Config without attempting to load the PDK
  configuration data- i.e., only rely on the user's input
* Extended `Meta` objects to support Step ID and OpenLane version.
* Moved tests from source tree to `test/` folder, refactoring as necessary
* Internal `utils` module folded into `common` module, with elements publicly
  documented
* Removed `tcl_reproducible`

# 2.0.0b2

* Updated Magic to `952b20d`
* Added new variable, `MAGIC_EXT_SHORT_RESISTOR` to `Magic.SpiceExtraction`,
  disabled by default

# 2.0.0b1

* Added unit testing and coverage reporting for core infrastructure features
  (80%+)
* Added running unit tests in the CI for different Python versions
* Moved CI designs out-of-tree
* Various documentation improvements
* Common Module
  * Created new TclUtils to handle common Tcl interactions, i.e., evaluating the
    environment and testing
  * Made Tcl environment evaluation no longer rely on the filesystem
  * Made Tcl environment evaluation restore the environment after the fact
  * Moved `Path` from State module to common
  * Moved parsing metric modifiers and such from Toolbox
* Config Module
  * Updated PDK migration script to be a bit more resilient
  * Fixed bug where `meta` did not get copied properly with `Config` copies
  * Rewrote configuration dictionary preprocessor again
* Flow Module
  * Sequential flows now handle duplicate Step IDs by adding a suffix
* Logging Module
  * Logging rewritten to use Python logger with rich handler, the latter of
    which suppressed during unit testing
* State Module
  * `State.save_snapshot()` now also saves a JSON representation of metrics
  * Fixed metric cloning
* Step Module
  * Report start/end locii also end up in the log file
  * Utils
  * DRC module now uses `.` to separate category layer and rule in name

# 2.0.0a55

* Updated OpenROAD to `02ea75b`
* Updated Volare to `0.9.2`
* Added guide on updating utilities with Nix

# 2.0.0a54

* Updated Magic to `0afe4d8`:

```
Corrected an error introduced by the code added recently for support

of command logging, which caused the "select cell <instance>" command
option to become invalid;  this command option is used by the
parameterized cell generator and makes it impossible to edit the
parameterized cells.
```

# 2.0.0a53

* Reworked Tcl unsafe string escaping to use home-cooked functions instead of
  "shlex"

# 2.0.0a52

* Added three designs to the gf180mcu test set
* Magic GDS writes now check log for `Calma output error` before proceeding
  further
* Moved constraint variables to PDK
  * `SYNTH_CAP_LOAD` renamed to `OUTPUT_CAP_LOAD`
* Deprecated names for variables now take priority: allows overriding PDK
  variables properly
* Updated Magic to `8b3bb1a`
* Updated PDK to `78b7bc3`
* Updated Volare to `0.8.0` to support zstd-compressed PDKs
* Temporarily removed `manual_macro_placement_test` from the sky130 test set
  pending a weird bug

# 2.0.0a51

* Updated Netgen to `87d8759`

# 2.0.0a50

* JSON configuration files with `meta.version: 2` and dictionary configurations
  now both subject to stricter validation
  * Strings no longer automatically converted to lists, dicts, numbers,
    Booleans, et cetera
  * Numbers no longer automatically converted to Booleans
  * Unrecognized keys throw an error instead of a warning
* Steps now only keep a copy of configuration variables that are either common
  or explicitly declared
  * Explicitly declare global routing variables for resizer steps
  * Explicitly declare MagicStep variables for DRC step
* `CLOCK_PORT` type changed from `Optional[List[str]]` to
  `Union[str, List[str], None]`
* JSON globs behavior adjusted, now always returns `List` - conversion handled
  after preprocessing
* Rewrote `resolve.py` as a proper preprocessor
  * Proper recursion into Mappings and Sequences (so refs:: may be resolved in
    arbitrarily deep objects)
  * Defer most validation and conversion to `Config` object
* Fixed internal issue where `some_of` of a Union with more than two variables
  of which one is `None` just returns the same Union
* Fixed issue where `expr::` turns results into strings
* `µ`niformity, now all use `U+00B5 MICRO SIGN`
* Removed default values that `ref::`/`expr::` other variables
* Removed unused variable

# 2.0.0a49

* Made designs synthesized by Yosys keep their name after `chparam`

# 2.0.0a48

* Created `openlane.flows.cloup_flow_opts`, which assigns a number of `cloup`
  commandline options to an external function for convenience.
* Moved handling of `last_run` inside `Flow.start`
* Moved handling of volare, setting log level and threadpool count to
  `cloup_flow_opts`

# 2.0.0a47

* Update Magic, Netgen, and Yosys
* Made `SYNTH_ELABORATE_ONLY` functional
* Minor internal rearchitecture of `common` and commandline options

# 2.0.0a46

* Start on API cleanup in preparation for beta
* Common and Logging isolated into own modules
* Improved documentation on various parts of the codebase.
* Delineated `public`, `private` and `protected` class members:
  * If undocumented or starts with `__`, private
  * If decorated with `@openlane.common.protected`, protected
  * Else public
* Class members renamed to reflect the above
* Adjusted documentation generation to use RST and proper titles
* Flow progress bar hooks encapsulated in new `FlowProgressBar` object
  * Old methods still exist, issue a `DeprecationWarning`

## API Breaks

* Top level `import openlane` now only has the version. To get access to `Flow`
  or `Step`, try `from openlane.flows import Flow`
* `Flow.get`/`Step.get` no longer exist: use
  `Flow.factory.get`/`Step.factory.get` instead
* `openlane.common.internal` decorator replaced with `openlane.common.protected`
* `Step` objects no longer hold a reference to parent flow
  * `Step.start` now takes `self.step_dir` as a required argument when running
    non-interactive flows
  * A faster migration method inside a Flow is `step.start()` ->
    `self.start_step(step)`

# 2.0.0a45

* Made Magic DRC report parser more robust, handling multiple rules, etc
* Updated documentation for various related variables
* Fixed bug causing PNR-excluded cells being used during resizer-based OpenROAD
  steps

# 2.0.0a44

* Added support for multiple corners during CTS using the `CTS_CORNERS` variable
* Added support for multiple corners during resizer steps using the
  `RSZ_CORNERS` variable
* Internally reworked OpenROAD resizer and CTS steps to share a common base
  class

# 2.0.0a43

* Added `io_placer` and `manual_macro_placemnt_test` to CI
* Fixed `MAGTYPE` for `Magic.WriteLEF`
* Fixed bug with reading `EXTRA_LEFS` in Magic steps

# 2.0.0a42

* Added support for instances to `RSZ_DONT_TOUCH_RX`
* Added support for `RSZ_DONT_TOUCH_LIST` to resizer steps
* `inverter` design used to configure the above two
* Added ignore for `//` key in JSON config files
* Added two new variables for `Yosys.Synthesis`; `SYNTH_DIRECT_WIRE_BUFFERING`
  and `SYNTH_SPLITNETS`
* Fixed bug with Yosys report parsing
* Fixed issue in `usb_cdc_core` masked by aforementioned bug

# 2.0.0a41

* Updated Magic to `9b131fa`
* Updated Magic LEF writing script
* Ensured consistency of Tcl script logging prefixes

# 2.0.0a40

* Fixed a bug with extracting variables from Tcl config files when the variable
  is already set in the environment
* Fixed a bug with saving lib and SDF files
* Fixed `check_antennas.tcl` being mis-named

# 2.0.0a39

* Added mechanism for subprocesses to write metrics via stdout,
  `%OL_METRIC{,_I,_F}`, used for OpenSTA
* Added violation summary table to post-PNR STA
* Reworked multi-corner STA: now run across N processes with the step being
  responsible for aggregation
* Made handling `Infinity` metrics more robust
* Fixed names of various metrics to abide with conventions:
  * `magic__drc_errors` -> `magic__drc_error__count`
  * `magic__illegal__overlaps` -> `magic__illegal_overlap__count`
* Removed splash messages from OpenROAD, OpenSTA

# 2.0.0a38

* Added full test-suite added to CI
  * Like OpenLane 1, a "fastest test set" runs with every PR and an "extended
    test set" runs daily
* Added Nix building, intra-CI caching and installation as composite actions
  * Nix derivation now cached intra-CI even if running without access to secrets
  * Fixed issue where channel was mis-named
  * Smoke test on all platforms using `nix-shell`
* Docker image re-implemented: One layer with proper settings for PATH and
  PYTHONPATH
  * Docker image smoke-tested independently of Nix
* Fixed bug with Tcl configurations
* Fixed issue with `Yosys.Synthesis` producing false-positive checks
* Updated various design configs

# 2.0.0a37

* Added `MAX_TRANSITION_CONSTRAINT` to `base.sdc` (if set)
* Added `MAX_TRANSITION_CONSTRAINT` -> `SYNTH_MAX_TRAN` translation behavior in
  `base.sdc`
* Removed attempt(s) to calculate a default value for
  `MAX_TRANSITION_CONSTRAINT` in `all.tcl`, `openroad/cts.tcl` and
  `yosys/synth.tcl`

# 2.0.0a36

* Added a commandline option `-j/--jobs` to add a maximum cap on subprocesses.
* Added a global ThreadPoolExecutor object for all subprocesses to `common`.
  * Accessible for external scripts and plugins via `openlane.get_tpe` and
    `openlane.set_tpe`
* Folded `--list-plugins` into `--version`
* Renamed `ROUTING_CORES` to `DRT_THREADS`
* Removed `RCX_CORES`, step now uses global ThreadPoolExecutor

# 2.0.0a35

* Revert magic to
  [`a33d7b7`](https://github.com/RTimothyEdwards/magic/commit/a33d7b78b54d8456769d08236f91f9be31784267),
  last known-good version before a LEF writing bug

# 2.0.0a34

* Added ability to disable reproducibles on a per-class level
* Updated SDF to support N-corners
* Fixed bug with writing LIB/SDF views

# 2.0.0a33

* Bump supported PDK to `af34855`
* Rename 3 PDK variables to match OpenLane 1
  * `FP_PDN_RAILS_LAYER` -> `FP_PDN_RAIL_LAYER`
  * `FP_PDN_UPPER_LAYER` -> `FP_PDN_HORIZONTAL_LAYER`
  * `FP_PDN_LOWER_LAYER` -> `FP_PDN_VERTICAL_LAYER`

# 2.0.0a32

* Better adherence to class structure and mutability principles
  * Create `GenericDict`, `GenericImmutableDict` to better handle immutable
    objects, i.e. `State`, `Config`
  * `State`, `Config` made immutable post-construction
    * Various rewrites to accommodate that
  * `Step`:
    * `.run`:
      * No longer has any default implementation
      * Is expected to return a tuple of **views updates** and **metrics
        updates** which are then applied to copies by `.start` to meet
        mutability requirements
    * `.start`:
      * Handles input checking
      * Handles creating new `State` object based on deltas
  * `Flow`
    * Stateful variables for `.start`, `.run`, and other internal methods made
      private
    * `.start` now only returns the final state object
    * Intermediate steps stored in `self.step_dir`
    * `self.step_dir` and other "mutations" to Flow object have no effect on
      future `.start()` invocations, which are (more or less) idempotent
  * Remove `ConfigBuilder` and fold methods into `Config`
* Added `make host-docs` to Makefile

# 2.0.0a31

* Replace OpenSTA binary name check with an environment variable, `OPENSTA`

# 2.0.0a30

* Added ability to use `--dockerized` without further arguments to drop into a
  shell
* Reimplemented `--dockerized` - needs to be the first argument provided
* Reimplemented `--smoke-test` to not use a subprocess
  * `--smoke-test` doesn't attempt to handle `--dockerized` on its own anymore
* Fixed permissions bug when running a smoke test from a read-only filesystem
* Fixed race condition for temporary directories on macOS (and presumably
  Windows)

# 2.0.0a29

* Added run-time type checkers for `SequentialFlow` `Substitute` dictionary
* Folded `init_with_config` into constructor and deprecate it
* Fixed `SequentialFlow` step substitution bug by moving variable compilation to
  instance instead of class

# 2.0.0a28

* Added missing macro orientations
* Added missing `PDN_CFG` configuration variable
* Fixed crash when defining `SYNTH_READ_BLACKBOX_LIB`
* Streamlined all `read` messages in OpenROAD scripts and macro-related `read`
  messages in Yosys scripts.
* Cleaned up `YosysStep` hierarchy
* Cleaned up `synthesize.tcl`

> Thanks [@smunaut](https://github.com/smunaut) for the bug reports!

# 2.0.0a27

* Added `cloup` library for better argument grouping/prettier `--help` with
  click
* Added ability to substitute steps with a certain `id` in a `SequentialFlow`
  with other Step classes
* Added `--only`, `--skip` to commandline interface for `SequentialFlow`s
* Changed processing of how `--from` and `--to` are done in `SequentialFlow`s
* Better delineation of class vs. instance variables in documentation
* Type checker now also checks functions without typed headers
* Fixed minor bugs with `Decimal` serialization and deserialization
* Class/step registry now case-insensitive
* Moved documentation dependencies to separate requirements file
* Removed `jupyter` from `requirements_dev.txt`- too many dependencies and can
  just be installed with `pip install jupyter`
* Various documentation improvements and fixes

# 2.0.0a26

* Yosys steps now read macro netlists as a black-box if applicable
* Renamed STA steps to avoid ambiguity

# 2.0.0a25

* Made optional/default handling more straightforward to fix issue where the
  default value of an Optional is not None.
* Fixed config var inheritance issue for `OpenROAD.ParasiticsSTA`

# 2.0.0a24

* Add support for gf180mcuC to PDK monkey-patch procedure
* Update some PDK variables to be optional: `GPIO_PADS_LEF`,
  `IGNORE_DISCONNECTED_MODULES`
* Remove unused PDK variable: `CELL_CLK_PORT`

# 2.0.0a23

* Added warning on multiple clocks in `base.sdc`
* Added usage of translation hook for SDC scripts
  * Folded `sdc_reader.tcl` into `io.tcl`
* Fixed calculation issue with I/O delays in `base.sdc`
* Fixed SPEF read invocation to include instance path
* Renamed multiple functions in `io.tcl` for clarity and to avoid aliasing Tcl
  built-in functions
* Tcl reproducibles now add entire environment delta vs. just "extracted"
  variables
  * Better handling of objects inside the design directory

# 2.0.0a22

* Fixed a bug with initializing configurations using dictionaries.
* Added exception message for `InvalidConfig`.

# 2.0.0a21

* Created a (very) rudimentary plugin system
  * Add ability to list detected plugins with flag `--list-plugins`
* Fixed a problem with reading SPEF files for macros
* Various documentation updates

# 2.0.0a20

* Created a `Macro` definition object to replace a litany of variables.
  * `libs`, `spefs` and `sdf` files now use wildcards as keys, which will be
    matched against timing corners for loading, i.e., a SPEF with key `nom_*`
    will match timing corner `nom_tt_025C_1v80`.
    * This has been applied to PDK lib files, RCX rulesets and technology LEF
      files as well.
    * `Toolbox` object now has methods for matching the proper LIB/SPEF files.
* PDKs now list a `DEFAULT_CORNER` for picking LIB files as well as a list of
  `STA_TIMING` corners.
* Expanded the range of valid types for `Variable`: these new classes are
  supported, all with theoretically infinite nesting:
  * `Dict`
  * `Union`
  * `Literal`
* `State` rewritten to support nested dictionaries and type annotations.
  * (Subclass of `Mapping`- Python 3.8 does not support subscripting `UserDict`.
    Yep.)
* Created a `config.json` for the caravel_upw example for testing purposes.
* Updated Magic, add new patch for Clang
* `self.state_in` is now always a future for consistency, but `run()` now takes
  a `state_in` which is guaranteed to be resolved.
* `EXTRA_LEFS`, `EXTRA_LIBS`, etc kept as a fallback for consistency.
* Remove `STA_PRE_CTS`- STA now always propagates clocks

# 2.0.0a19

* Created new metric `synthesis__check_error__count` with a corresponding
  Checker, with said Checker being the new executor of the
  `QUIT_ON_SYNTH_CHECKS` variable
  * Check report parser imported from OpenLane 1
* Created `SYNTH_CHECKS_ALLOW_TRISTATE` to exclude unmapped tribufs from
  previous metric.
* Created new metric `design__xor_difference__count` with a corresponding
  Checker to flag a deferred error on XOR differences.
* Fixed a few typos.

# 2.0.0a18

* Updated the smoke test to support PDK downloads to a different directory.
* Updated config builder to resolve the PDK root much earlier to avoid an issue
  where a crash would affect the issue reproducible.
* Updated `SYNTH_READ_BLACKBOX_LIB` to read the full `LIB` variable instead of
  `LIB_SYNTH`, which also fixes a crash when reading JSON headers.
* Updated post-GRT resizer timing script to re-run GRT before the repair: see
  https://github.com/The-OpenROAD-Project/OpenROAD/issues/3155
* Added a "yosys proc" to the JSON header generator (thanks @smnaut)
* Fixed a bug where random equidistant mode did not work for OpenROAD IO placer.

# 2.0.0a17

* Fixed a crash when the SCL is specified via command-line.
* Fixed a changelog merge nightmare.

# 2.0.0a16

* Reimplement DRC database using `lxml`
* Makefile `venv` creation updated
* Misc. aesthetic bugfixes for sequential flows

# 2.0.0a14

* Add steps to extract, preserve and check power connections:
  * `Checker.DisconnectedPins`: Checker for `ReportDisconnectedPins`.
  * `Odb.ReportDisconnectedPins`: Report disconnected instance pins in a design.
  * `Yosys.JsonHeader`: RTL to a JSON Header.
  * `Odb.SetPowerConnections`: Uses JSON generated in `Yosys/JsonHeader` and
    module information in Odb to add global connections for macros in a design.
* Add `IGNORE_DISCONNECTED_MODULES` as a PDK variable, as some cells need to be
  ignored.
* Rename `SYNTH_USE_PG_PINS_DEFINES` to `SYNTH_POWER_DEFINE`.
* Rename `CHECK_UNMAPPED_CELLS` to `QUIT_ON_UNMAPPED_CELLS`.
* Rename various metrics.
* Change various configuration variables for included `caravel_upw` design.
* Fix `DIODE_INSERTION_STRATEGY` translations
* Allow overriding from CLI when using Tcl configuration files.

# 2.0.0a13

## Documentation

* Built-in flows now have full generated documentation akin to steps.
* Built-in steps now document their inputs, outputs and each built-in step has a
  human-readable text description.
* Rewrite the RTL-to-GDS guides.
* Add an architectural overview of OpenLane 2+.
* Document pin config file format.
* Add guides on writing custom flows AND custom steps.
* Add a migration guide from OpenLane 1.
* Port contributor's guide from OpenLane 1.
* Removed default values from Jupyter Notebook.

## Functional

* `Config` is now immutable, `.copy()` can now take kwargs to override one or
  more values.
* `TapDecapInsertion` -> `TapEndcapInsertion` (more accurate)
* Dropped requirement for description to match between two variables to be
  "equal:" It is sometimes favorable to have a slightly different description in
  another step.
* `OpenInKLayout`/`OpenInOpenROAD` turned into sequential flows with one step
  instead of hacks.
* Fixed a bug where `OpenInKLayout` would exit instantly.
* Updated and fixed `Optimizing` demo flow, as well as delisting it.
* Port https://github.com/The-OpenROAD-Project/OpenLane/pull/1723 to OpenLane 2.
* Remove `Odb.ApplyDEFTemplate` from default flow.

# 2.0.0a12

* Fixes a bug where if OpenLane is invoked from the same directory as the
  design, KLayout stream-outs would break.

# 2.0.0a11

* Update OpenROAD, Add ABC patch to use system zlib
* Adds SDC files as an input to `OpenROADStep`, `NetlistSTA` and `LayoutSTA`
  steps
* Add `sdc_reader.tcl`: a hook script for reading in SDC files while handling
  deprecated variables
* Replace deprecated variables in base.sdc
  * Properly use TIME_DERATING_CONSTRAINT in base.sdc
  * Properly use SYNTH_DRIVING_CELL in base.sdc
  * Properly use SYNTH_CLK_DRIVING_CELL in base.sdc

# 2.0.0a10

* Add `wrapper.tcl` to capture errors in Magic scripts.
* Fix instances of a deprecated variable was used in Magic scripts.

# 2.0.0a9

* Add port diode insertion script.
* Fix formula for calculating `FP_TARGET_DENSITY_PCT`.

# 2.0.0a8

* Update `volare` dependency.
* Update `magic` version + make `magic` nix derivation more resilient.

# 2.0.0a7

* Add the custom diode insertion script as a `Step` (disabled by default).
* `Flow` objects are now passed explicitly to child `Step` objects, removing
  earlier stack inspection code.
* `flow_config_vars` now only affect steps running inside a Flow.

# 2.0.0a6

* Add validation on step exit.

# 2.0.0a5

* Fix a small path resolution issue.

# 2.0.0a4

* Add basic CI that builds for Linux, macOS and Docker
* Various improvements to Dockerization so that `openlane --dockerized` can run
  on Windows

# 2.0.0a3

* Fixed an issue where KLayout scripts exited silently.

# 2.0.0a2

* Handle `PDK_ROOT`, `PDK` and `STD_CELL_LIBRARY` environment variables.
* Unify environment inspection by using `os.environ`- eliminated getenv
* KLayout scripts no longer accept environment variables.
* Updated Docker images for consistency.
* Added ReadTheDocs configuration.

# 2.0.0a1

* Update smoke test
* Fix bug with default variables

# 2.0.0dev15

* `log` -> `info`
* Add mitigation for KLayout None variables.
* `logging` isolated from `common` into its own module
* CLI now accepts either a value or a string for log levels.
* CLI now prints help if no arguments are provided.
* Fix issue where `rich` eats the cursor if it exits by interrupt.

# 2.0.0dev14

* Multiple logging levels specified via CLI. Can also be set via `set_log_level`
  in the API.
* Updated all `run_subprocess` invocations to create a log, named after the
  `Step`'s `id` by default.
* Fixed issue with `ROUTING_CORES` not using the computer's total core count by
  default.
* Fixed an issue with Tcl config files where `DESIGN_DIR` was resolved
  relatively, which greatly confused KLayout.

# 2.0.0dev13

* Add ApplyDEFTemplate step.
* Update most `odbpy` CLIs to accept multiple LEF files.

# 2.0.0dev12

* Cleaned up build system.
* Add support for OpenROAD with `or-tools` on macOS.

# 2.0.0dev11

* Added `QUIT_ON_SYNTH_CHECKS`
* Added `QUIT_ON_UNMAPPED_CELLS`
* Added metric `design__instance_unmapped__count`
* Allowed `MetricChecker` to raise `StepError`

# 2.0.0dev10

* Updated OpenROAD to `6de104d` and KLayout to `0.28.5`.
* OpenROAD builds now use system boost to cut on build times.
* Added new dedicated interactive mode to replace "Step-by-step" API: activated
  by calling `ConfigBuilder.interactive`, which replaced `per_step`.
  * State, Config and Toolbox for `Step`s all become implicit and rely on global
    variables.
  * On the other hand, `config=` must now be passed explicitly to
    non-interactive flows.
* Added Markdown-based IPython previews for `Step` and `Config` objects.
  * Added an API to render `DEF` or `GDS` files to PNG files to help with that.
* Changed API for KLayout Python scripts to be a bit more consistent.
* Renamed a number of variables for consistency.
* Tweaked documentation slightly for consistency.

# 2.0.0dev9

* Moved `State` to its own submodule.
* Fixed bug with loading default SCL.

# 2.0.0dev8

* Added a step-by-step API for OpenLane.
  * Involves new `ConfigBuilder` method, `per_step`, which creates configuration
    files that can be incremented per-step.
  * This mode is far more imperative and calls may have side effects.
* Added an example IPython notebook to use the aforementioned API.
  * Add a number of APIs to display `State` as a part of a notebook.
* Added various default values for `Step` so it can be used without too many
  parameters. (`config` is still required, but `state_in` will become an empty
  state if not provided.)
* Moved various documentation functions to the `Variable` object so they can
  also be used by IPython.
* Updated documentation for `Variable` object.
* Various documentation updates and fixes.

# 2.0.0dev7

* More build fixes.

# 2.0.0dev6

* Added magic builds to macOS
* Fixed KLayout builds on macOS
* Tweaks to Nix build scripts
* Removed hack to make KLayout work on macOS
* Removed NoMagic flow

# 2.0.0dev5

* Fixed commandline `--flow` override.
* Removed call-stack based inference of `state_in` argument for steps: a step
  initialized without a `state_in` will have an empty in-state.
* Changed signature of `Flow.run`, `Flow.start` to return `(State, List[Step])`,
  returning only the last state as the per-step states can be accessed via
  `step[i].state_out`.
* Removed distinction between the `Step.id` and it factory-registered string:
  the ID is now used for the factory, in the format `Category.Step` for the
  built-in steps.
* Fixed `--from` and `--to`, also add validation and case-insensitivity.
* Various bugfixes to Tcl script packager.

# 2.0.0dev4

* Fix `Optimizing` flow.

# 2.0.0dev3

* Remove Mako as requirement, migrate relevant code.

# 2.0.0dev2

* Updated installation instructions.
* Separated variables step-by-step.
* Various fixes to environment variables, especially when using OpenROAD Odb
  Python scripts.
* Add specialized steps to check and/or quit on specific metrics and/or
  variables.

# 2.0.0dev1

* Rewrite OpenLane in Python using a new, Flow-based architecture.
* Add packaging using the Nix Package Manager to replace the Docker
  architecture.
* Added transparent Dockerization using `--dockerized` commandline argument,
  with images also built using Nix.
