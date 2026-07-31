# Migrate Flows To Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the six shipped flows into YAML documents running on the workflow engine, replace `--from`/`--to` with `--invalidate`/`--target`, and let a document supply configuration values through a `with` block whose reach `--explain` reports.

**Architecture:** Each flow becomes a YAML document beside the code. The migration is done in two movements: first a faithful translation that preserves today's exact step order as a linear chain, pinned by a test comparing against `Classic.Steps`; then a small, separately reviewable set of edge relaxations that introduce the real parallelism. Splitting them means a regression in the translation cannot hide behind a regression in the parallelisation.

**Tech Stack:** Python 3.11+, YAML documents loaded through `load_flow_spec`, Typer for the command line, pytest, uv.

## Global Constraints

- This is phase 4 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phases 1, 2 and 3 having landed, so the registry is `librelane.jobs.JobRegistry`, the template type is `Job`, and the engine's resolved type is `ResolvedJob`.
- The full test suite must stay green at every commit.
- Never add a fallback. A `--target` or `--invalidate` naming an unknown job is an error listing the document's jobs, never a no-op.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Documents are `librelane/flows/*.yaml`, shipped as package data. Confirm `pyproject.toml`'s package-data configuration includes `*.yaml` under `librelane/flows`, and add it if it does not, or an installed wheel will have no flows.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

## The six flows

| Flow | Source today | Document |
| --- | --- | --- |
| Classic | `librelane/flows/classic.py:42` | `librelane/flows/classic.yaml` |
| VHDLClassic | `librelane/flows/classic.py:268` | `librelane/flows/vhdl_classic.yaml` |
| Chip | `librelane/flows/chip.py:52` | `librelane/flows/chip.yaml` |
| OpenInKLayout | `librelane/flows/misc.py:35` | `librelane/flows/open_in_klayout.yaml` |
| OpenInOpenROAD | `librelane/flows/misc.py:53` | `librelane/flows/open_in_openroad.yaml` |
| OpenInMagic | `librelane/flows/misc.py:71` | `librelane/flows/open_in_magic.yaml` |

## Two facts about Classic that shape the translation

`OpenROAD.STAMidPNR` appears **four times** in `Classic.Stages`. Job ids are unique within a document, so the four occurrences become four jobs, `sta_mid_pnr_1` through `sta_mid_pnr_4`. This is not a workaround: they are four distinct runs at four points in the flow, and giving them distinct names makes their four run directories distinguishable, which the positional numbering did only by accident.

Thirteen entries are bare steps belonging to no registered job: `Odb.SetPowerConnections`, `OpenROAD.CutRows`, `Odb.AddRoutingObstructions`, `Odb.WriteVerilogHeader`, `Checker.PowerGridViolations`, `Odb.ManualGlobalPlacement`, `Odb.ReportDisconnectedPins`, `Checker.DisconnectedPins`, `Odb.ReportWireLength`, `Checker.WireLength`, `Odb.CellFrequencyTables`, `Magic.WriteLEF`, `Odb.CheckDesignAntennaProperties`, plus `KLayout.XOR`, `Checker.XOR`, the four `Checker.*Violations` and `Misc.ReportManufacturability`. Each becomes a job with inline `steps`. Adjacent bare steps that always run together are one job, not several, because a job is the unit of the graph and splitting them adds edges that say nothing.

---

### Task 1: The Classic document, translated faithfully

**Files:**
- Create: `librelane/flows/classic.yaml`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Consumes: `load_flow_spec` (phase 1), `resolve_jobs` (phase 2).
- Produces: a document whose resolved step sequence equals today's `Classic.Steps`.

**Design notes the implementer needs:**

This task translates, it does not improve. Every job needs exactly the job before it, reproducing today's linear order. The parallelism arrives in Task 2, where each relaxed edge is individually visible in the diff. A translation error and a parallelisation error look identical in a step-order test, so they must not land together.

The gating tables move here as `if` keys. `Stage.lint`'s `RUN_LINTER`, `Stage.cts`'s `RUN_CTS` and the other 13 template gates become `if` on the job. `Classic.gating_config_vars` entries become `if` on the corresponding job, and the three-variable `KLayout.XOR` / `Checker.XOR` entries become **edges**, because `RUN_MAGIC_STREAMOUT and RUN_KLAYOUT_STREAMOUT` was a hand-maintained encoding of "XOR needs both producers".

`streamout` is `multi_provider` with default `('magic', 'klayout')`. Today one `Stage.streamout` entry runs both providers and two booleans switch them independently. That becomes two jobs, `magic_streamout` and `klayout_streamout`, each with its own `uses` and its own `if`. Likewise `drc`.

- [ ] **Step 1: Write the failing test**

Create `test/flows/test_documents.py`:

```python
# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The no-regression pin for the migration: each document must resolve to the same
steps the Python flow it replaces declared.
"""

from importlib.resources import files

import pytest

import librelane.steps  # noqa: F401  populates the registries

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import load_flow_spec
from librelane.flows.spec_graph import topological_order

pytestmark = pytest.mark.all


def _document(name: str):
    return load_flow_spec(str(files("librelane.flows").joinpath(name)))


def _resolved_step_ids(name: str) -> list[str]:
    spec = _document(name)
    jobs = resolve_jobs(spec)
    return [
        step.id
        for job in topological_order(spec.edges())
        for step in jobs[job].steps
    ]


def test_the_classic_document_declares_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    expected = [step.id for step in Classic.Steps]

    assert _resolved_step_ids("classic.yaml") == expected


def test_the_classic_document_gates_every_step_the_classic_flow_gated():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)

    gated_by_document = {
        step.id
        for job in jobs.values()
        if job.condition is not None
        for step in job.steps
    }
    gated_by_flow = set(Classic._expand_gating_config_vars(
        Classic.gating_config_vars, [cls.id for cls in Classic.Steps]
    ))

    assert gated_by_document == gated_by_flow
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: FAIL with `FileNotFoundError` or `ValueError: Unsupported configuration source`, because `classic.yaml` does not exist.

- [ ] **Step 3: Write the document**

Create `librelane/flows/classic.yaml`. Transcribe `Classic.Stages` in order, one job per entry, each needing the one before it. The head and the fan-in region are given in full below; the middle is the same pattern repeated.

```yaml
name: Classic
description: A general-purpose RTL-to-GDSII flow.

config:
  - name: RUN_LINTER
    type: bool
    default: true
    description: Enables the lint job.
  - name: RUN_TAP_ENDCAP_INSERTION
    type: bool
    default: true
    description: Enables the tapcell insertion job.
    deprecated_names: [TAP_DECAP_INSERTION, RUN_TAP_DECAP_INSERTION]
  # ...one entry per variable in Classic.Config, transcribed with the same
  # default, description and deprecated_names.

jobs:
  lint:
    uses: lint
    if: RUN_LINTER
  synthesis:
    needs: [lint]
    uses: synthesis
  pre_pnr_sta:
    needs: [synthesis]
    uses: pre_pnr_sta
  floorplan:
    needs: [pre_pnr_sta]
    uses: floorplan
  set_power_connections:
    needs: [floorplan]
    steps: [Odb.SetPowerConnections]
  macro_placement:
    needs: [set_power_connections]
    uses: macro_placement
  cut_rows:
    needs: [macro_placement]
    steps: [OpenROAD.CutRows]
  tapcell_insertion:
    needs: [cut_rows]
    uses: tapcell_insertion
    if: RUN_TAP_ENDCAP_INSERTION
  power_grid:
    needs: [tapcell_insertion]
    uses: power_grid
  add_routing_obstructions:
    needs: [power_grid]
    steps: [Odb.AddRoutingObstructions]
  io_placement:
    needs: [add_routing_obstructions]
    uses: io_placement
  global_placement:
    needs: [io_placement]
    uses: global_placement
  write_verilog_header:
    needs: [global_placement]
    steps: [Odb.WriteVerilogHeader, Checker.PowerGridViolations]
  sta_mid_pnr_1:
    needs: [write_verilog_header]
    steps: [OpenROAD.STAMidPNR]
  post_gpl_repair:
    needs: [sta_mid_pnr_1]
    uses: post_gpl_repair
    if: RUN_POST_GPL_DESIGN_REPAIR
  manual_global_placement:
    needs: [post_gpl_repair]
    steps: [Odb.ManualGlobalPlacement]
  detailed_placement:
    needs: [manual_global_placement]
    uses: detailed_placement
  cts:
    needs: [detailed_placement]
    uses: cts
    if: RUN_CTS
  sta_mid_pnr_2:
    needs: [cts]
    steps: [OpenROAD.STAMidPNR]
  post_cts_opt:
    needs: [sta_mid_pnr_2]
    uses: post_cts_opt
    if: RUN_POST_CTS_RESIZER_TIMING
  sta_mid_pnr_3:
    needs: [post_cts_opt]
    steps: [OpenROAD.STAMidPNR]
  global_routing:
    needs: [sta_mid_pnr_3]
    uses: global_routing
  post_grt_repair:
    needs: [global_routing]
    uses: post_grt_repair
    if: RUN_POST_GRT_DESIGN_REPAIR
  antenna_repair:
    needs: [post_grt_repair]
    uses: antenna_repair
    if: RUN_ANTENNA_REPAIR
  post_grt_opt:
    needs: [antenna_repair]
    uses: post_grt_opt
    if: RUN_POST_GRT_RESIZER_TIMING
  sta_mid_pnr_4:
    needs: [post_grt_opt]
    steps: [OpenROAD.STAMidPNR]
  detailed_routing:
    needs: [sta_mid_pnr_4]
    uses: detailed_routing
    if: RUN_DRT
  routing_reports:
    needs: [detailed_routing]
    steps:
      - Odb.ReportDisconnectedPins
      - Checker.DisconnectedPins
      - Odb.ReportWireLength
      - Checker.WireLength
  post_route_opt:
    needs: [routing_reports]
    uses: post_route_opt
  fill_insertion:
    needs: [post_route_opt]
    uses: fill_insertion
    if: RUN_FILL_INSERTION
  cell_frequency_tables:
    needs: [fill_insertion]
    steps: [Odb.CellFrequencyTables]
  extraction:
    needs: [cell_frequency_tables]
    uses: extraction
    if: RUN_SPEF_EXTRACTION
  signoff_sta:
    needs: [extraction]
    uses: signoff_sta
  ir_drop:
    needs: [signoff_sta]
    uses: ir_drop
    if: RUN_IRDROP_REPORT
  magic_streamout:
    needs: [ir_drop]
    uses: streamout/magic
    if: RUN_MAGIC_STREAMOUT
  klayout_streamout:
    needs: [magic_streamout]
    uses: streamout/klayout
    if: RUN_KLAYOUT_STREAMOUT
  write_lef:
    needs: [klayout_streamout]
    steps: [Magic.WriteLEF]
    if: RUN_MAGIC_WRITE_LEF
  check_antenna_properties:
    needs: [write_lef]
    steps: [Odb.CheckDesignAntennaProperties]
  xor:
    needs: [check_antenna_properties]
    steps: [KLayout.XOR, Checker.XOR]
    if: RUN_KLAYOUT_XOR
    source: {gds: klayout_streamout}
  magic_drc:
    needs: [xor]
    uses: drc/magic
    if: RUN_MAGIC_DRC
  klayout_drc:
    needs: [magic_drc]
    uses: drc/klayout
    if: RUN_KLAYOUT_DRC
  lvs:
    needs: [klayout_drc]
    uses: lvs
    if: RUN_LVS
  formal_equivalence:
    needs: [lvs]
    uses: formal_equivalence
    if: RUN_EQY
  final_checks:
    needs: [formal_equivalence]
    steps:
      - Checker.SetupViolations
      - Checker.HoldViolations
      - Checker.MaxSlewViolations
      - Checker.MaxCapViolations
      - Misc.ReportManufacturability
```

The `source: {gds: klayout_streamout}` on `xor` is required even in this linear
form, because `magic_streamout` and `klayout_streamout` both declare `gds` in
`provides`, and the fan-in check from phase 1 sees `magic_streamout` as an
ancestor of `xor` through `klayout_streamout`. Naming the source is what the
document says today only implicitly, by ordering.

- [ ] **Step 4: Run the tests until they pass**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: both pass. A mismatch prints the two step lists; the first differing index names the job you transcribed wrongly.

- [ ] **Step 5: Add the YAML to the package data**

In `pyproject.toml`, confirm the package-data configuration ships `librelane/flows/*.yaml`. If it does not, add it. Then:

Run: `uv build && python3 -c "import zipfile,glob; print([n for n in zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]).namelist() if n.endswith('.yaml')])"`
Expected: `classic.yaml` appears in the list.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows/classic.yaml test/flows/test_documents.py pyproject.toml
git commit -m "feat: translate Classic into a workflow document"
```

---

### Task 2: Relax Classic's edges into the real graph

**Files:**
- Modify: `librelane/flows/classic.yaml`
- Test: `test/flows/test_documents.py`

**Design notes the implementer needs:**

Task 1's chain is correct but sequential. This task removes the edges that only existed because a list has no way to say "independent". Each relaxation below is justified by what the jobs actually consume, and the test pins the resulting concurrency rather than the order.

`test_the_classic_document_declares_the_same_steps_as_the_classic_flow` must be **replaced** here, not kept: once the graph is a real DAG there is no single topological order, so comparing against a list is comparing against one arbitrary linearisation. Replace it with a set comparison plus explicit edge assertions.

The relaxations:

- `magic_streamout` and `klayout_streamout` both need `ir_drop`, not each other. They are independent producers of `gds`.
- `magic_drc` needs `magic_streamout`. `klayout_drc` needs `klayout_streamout`. Each DRC tool reads its own producer's GDSII, which is the whole reason both streamouts exist.
- `lvs` needs `magic_streamout`, being a `gds` consumer.
- `formal_equivalence` needs `synthesis`, not the routing chain. It compares the RTL against the synthesised netlist and reads nothing produced after synthesis.
- `xor` needs both streamouts, which is what the three-variable gate encoded.
- `write_lef` needs `magic_streamout`, being a Magic job.
- `final_checks` needs `signoff_sta`, the source of the timing metrics the four checkers read.

- [ ] **Step 1: Replace the order test with a graph test**

In `test/flows/test_documents.py`, delete `test_the_classic_document_declares_the_same_steps_as_the_classic_flow` and add:

```python
def test_the_classic_document_runs_the_same_steps_as_the_classic_flow():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")

    assert sorted(_resolved_step_ids("classic.yaml")) == sorted(
        step.id for step in Classic.Steps
    )


def test_classic_s_signoff_checks_are_independent_of_each_other():
    from librelane.flows.spec_graph import ancestors

    edges = _document("classic.yaml").edges()

    assert "klayout_drc" not in ancestors(edges, "magic_drc")
    assert "magic_drc" not in ancestors(edges, "klayout_drc")
    assert "magic_drc" not in ancestors(edges, "lvs")
    assert "lvs" not in ancestors(edges, "formal_equivalence")


def test_classic_s_xor_needs_both_streamouts():
    edges = _document("classic.yaml").edges()

    assert set(edges["xor"]) == {"magic_streamout", "klayout_streamout"}


def test_formal_equivalence_does_not_wait_for_routing():
    from librelane.flows.spec_graph import ancestors

    edges = _document("classic.yaml").edges()

    assert "detailed_routing" not in ancestors(edges, "formal_equivalence")
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: the three graph tests FAIL, because Task 1's chain makes every job an ancestor of every later job.

- [ ] **Step 3: Apply the relaxations**

In `librelane/flows/classic.yaml`, change only these `needs`:

```yaml
  magic_streamout:
    needs: [ir_drop]
  klayout_streamout:
    needs: [ir_drop]
  write_lef:
    needs: [magic_streamout]
  check_antenna_properties:
    needs: [magic_streamout]
  xor:
    needs: [magic_streamout, klayout_streamout]
    source: {gds: klayout_streamout}
  magic_drc:
    needs: [magic_streamout]
  klayout_drc:
    needs: [klayout_streamout]
  lvs:
    needs: [magic_streamout]
  formal_equivalence:
    needs: [synthesis]
  final_checks:
    needs: [signoff_sta]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add librelane/flows/classic.yaml test/flows/test_documents.py
git commit -m "feat: give Classic its real dependency graph"
```

---

### Task 3: The remaining five documents

**Files:**
- Create: `librelane/flows/vhdl_classic.yaml`, `librelane/flows/chip.yaml`, `librelane/flows/open_in_klayout.yaml`, `librelane/flows/open_in_openroad.yaml`, `librelane/flows/open_in_magic.yaml`
- Test: `test/flows/test_documents.py`

**Design notes the implementer needs:**

VHDLClassic differs from Classic by a pinned synthesis provider and four omitted entries: `Stage.lint`, `Odb.SetPowerConnections`, `Odb.WriteVerilogHeader` and `Checker.PowerGridViolations`. It is written out **in full**, not derived from Classic. `classic.py:277-285` already records why: a filter expression over another flow's list is a substitution map wearing a different hat. The same reasoning applies to an `extends:` key, which is why the document schema has none.

The three Open-In flows are single-job documents with one inline step each and no `config`.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_documents.py`:

```python
@pytest.mark.parametrize(
    "document,flow_name",
    [
        ("vhdl_classic.yaml", "VHDLClassic"),
        ("chip.yaml", "Chip"),
        ("open_in_klayout.yaml", "OpenInKLayout"),
        ("open_in_openroad.yaml", "OpenInOpenROAD"),
        ("open_in_magic.yaml", "OpenInMagic"),
    ],
)
def test_each_document_runs_the_same_steps_as_the_flow_it_replaces(
    document, flow_name
):
    from librelane.flows import Flow

    flow = Flow.factory.get(flow_name)

    assert sorted(_resolved_step_ids(document)) == sorted(
        step.id for step in flow.Steps
    )


def test_vhdl_classic_pins_the_vhdl_synthesis_provider():
    assert _document("vhdl_classic.yaml").jobs["synthesis"].uses == (
        "synthesis/yosys_vhdl"
    )


def test_vhdl_classic_omits_the_verilog_only_jobs():
    jobs = _document("vhdl_classic.yaml").jobs

    assert "lint" not in jobs
    assert "set_power_connections" not in jobs
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: the five parametrised cases and the two VHDL cases FAIL, because the documents do not exist.

- [ ] **Step 3: Write the three Open-In documents**

`librelane/flows/open_in_klayout.yaml`:

```yaml
name: OpenInKLayout
description: Opens the design in the KLayout GUI.
jobs:
  open_gui:
    steps: [KLayout.OpenGUI]
```

`librelane/flows/open_in_openroad.yaml`:

```yaml
name: OpenInOpenROAD
description: Opens the design in the OpenROAD GUI.
jobs:
  open_gui:
    steps: [OpenROAD.OpenGUI]
```

`librelane/flows/open_in_magic.yaml`:

```yaml
name: OpenInMagic
description: Opens the design in Magic.
jobs:
  open_gui:
    steps: [Magic.OpenGUI]
```

- [ ] **Step 4: Write `vhdl_classic.yaml`**

Copy `classic.yaml` in full. Then make exactly four changes: set `synthesis`'s `uses` to `synthesis/yosys_vhdl`; delete the `lint` job and re-point `synthesis`'s `needs` to `[]`; delete the `set_power_connections` job and re-point `macro_placement`'s `needs` to `[floorplan]`; and delete `Odb.WriteVerilogHeader` and `Checker.PowerGridViolations` from the `write_verilog_header` job, which leaves it empty, so delete that job too and re-point `sta_mid_pnr_1`'s `needs` to `[global_placement]`. Also delete `RUN_LINTER` from `config`, since no job references it and phase 1's `_check_conditions_are_declared` only rejects the reverse.

- [ ] **Step 5: Write `chip.yaml`**

Transcribe `Chip.Stages` from `librelane/flows/chip.py:52` using the same method as Task 1, then apply the same relaxations as Task 2 to whichever of those jobs Chip declares.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest test/flows/test_documents.py -v`
Expected: all pass

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows test/flows/test_documents.py
git commit -m "feat: translate the remaining five flows into documents"
```

---

### Task 4: Register documents in the flow factory

**Files:**
- Modify: `librelane/flows/__init__.py`, `librelane/flows/flow.py`
- Test: `test/flows/test_documents.py`

**Interfaces:**
- Produces: `Flow.factory.get(name) -> FlowSpec`, `Flow.factory.list() -> list[str]`.

**Design notes the implementer needs:**

`Flow.factory` currently maps a name to a `type[Flow]`, registered by the `@Flow.factory.register()` decorator at `librelane/flows/flow.py:1067`. It must now map a name to a `FlowSpec`. Load every `librelane/flows/*.yaml` at import and register it under the document's `name`.

Keep the class-based registration path working for this task. Phase 5 deletes it. Removing it here would break `test_documents.py`, which compares each document against the Python flow it replaces.

The two must therefore coexist under one name, so use two registries behind one lookup: the document registry is consulted first, then the class registry. That is a migration state, not a shipped one; phase 5 deletes the second half.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_documents.py`:

```python
def test_every_document_is_registered_under_its_name():
    from librelane.flows import Flow
    from librelane.flows.spec import FlowSpec

    for name in ["Classic", "VHDLClassic", "Chip", "OpenInKLayout"]:
        registered = Flow.factory.get_document(name)
        assert isinstance(registered, FlowSpec)
        assert registered.name == name


def test_a_document_is_rejected_at_import_if_it_is_malformed(tmp_path):
    from librelane.flows.spec import FlowSpecError, load_flow_spec

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Bad\njobs:\n  a:\n    needs: [nope]\n    uses: lint\n")

    with pytest.raises(FlowSpecError):
        load_flow_spec(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest test/flows/test_documents.py::test_every_document_is_registered_under_its_name -v`
Expected: FAIL with `AttributeError: type object 'FlowFactory' has no attribute 'get_document'`

- [ ] **Step 3: Add document registration**

In `librelane/flows/flow.py`, inside the `FlowFactory` class, add:

```python
        _documents: ClassVar[dict[str, "FlowSpec"]] = {}

        @classmethod
        def register_document(Self, spec: "FlowSpec") -> "FlowSpec":
            """
            Registers a workflow document under its own ``name``.

            Raises
            ------
            FlowException
                If a document with that name is already
                registered.
            """
            if spec.name in Self._documents:
                raise FlowException(
                    f"A flow document named '{spec.name}' is already "
                    f"registered."
                )
            Self._documents[spec.name] = spec
            return spec

        @classmethod
        def get_document(Self, name: str) -> "FlowSpec | None":
            """The document registered under this name, or ``None``."""
            return Self._documents.get(name)
```

In `librelane/flows/__init__.py`, after the existing flow imports, load every shipped document:

```python
from importlib.resources import files

from librelane.flows.flow import Flow
from librelane.flows.spec import load_flow_spec

for _document in sorted(files(__name__).iterdir(), key=lambda p: p.name):
    if _document.name.endswith(".yaml"):
        Flow.factory.register_document(load_flow_spec(str(_document)))
```

Sorting by name makes the registration order deterministic, so a duplicate-name error names the same document on every machine.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest test/flows -v`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane/flows test/flows/test_documents.py
git commit -m "feat: register shipped workflow documents in the flow factory"
```

---

### Task 5: `--target`, `--invalidate` and the new `--skip`

**Files:**
- Modify: `librelane/cli/options.py:153-195`, `librelane/cli/run.py:88-115`, `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`, `test/cli/test_entry_points.py`

**Interfaces:**
- Consumes: `ancestors`, `descendants` from `librelane.flows.spec_graph`.
- Produces: `Workflow.run(self, initial_state, target=None, invalidate=None, skip=None, **kwargs)`.

**Design notes the implementer needs:**

`--from` is not flow control. Its own help text says it ignores any reusable result for a step and everything after it, which is entirely a statement about the cache. It exists because `resume_key` hashes `{schema, step, librelane_version, config, state_in}` and cannot hash the tool binary, an edited TCL script or a PDK file. `--invalidate` is that behaviour under a name that says so.

`--to` was an approximation on a list of what `make X` is on a graph. `--target` runs the named job and its transitive ancestors, and repeats.

The three compose in a fixed order. `--target` restricts the graph first; `--skip` and `--invalidate` apply within the restriction, and naming a job outside it is an error rather than a silent no-op.

`--skip` is kept deliberately as a debug escape hatch, not as a modelling mechanism. The declarative way to make a job optional is to give it an `if`.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_target_runs_only_the_named_job_and_its_ancestors(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start(tag="t", target=["first"])

    assert order == ["Test.EngineFirst"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_target_naming_an_unknown_job_is_an_error(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.flows.flow import FlowException

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", target=["nope"])

    message = str(exc_info.value)
    assert "nope" in message
    assert "first" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_skip_outside_the_target_subgraph_is_an_error(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.flows.flow import FlowException

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", target=["first"], skip=["second"])

    assert "second" in str(exc_info.value)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_invalidate_forces_a_job_and_its_descendants_to_rerun(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    first = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    first.start(tag="t")
    order.clear()

    second = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    second.start(tag="t", invalidate=["first"])

    # 'first' is forced, and 'second' re-runs because its input state changed.
    assert order == ["Test.EngineFirst", "Test.EngineSecond"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: the four new tests FAIL with `TypeError` about unexpected keyword arguments.

- [ ] **Step 3: Implement the three options in the engine**

In `librelane/flows/engine.py`, change `run`'s signature and add the restriction, before the net is built:

```python
    def run(
        self,
        initial_state: State,
        target: Iterable[str] | None = None,
        invalidate: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        edges = self.spec.edges()
        selected = set(self.jobs)
        if target is not None:
            targets = list(target)
            self._require_declared(targets, "--target")
            selected = set()
            for name in targets:
                selected.add(name)
                selected |= ancestors(edges, name)

        skipped = set(skip or ())
        self._require_declared(sorted(skipped), "--skip")
        forced: set[str] = set()
        for name in invalidate or ():
            self._require_declared([name], "--invalidate")
            forced.add(name)
            forced |= descendants(edges, name)

        outside = (skipped | set(invalidate or ())) - selected
        if outside:
            raise FlowException(
                f"{sorted(outside)} lie outside the --target subgraph "
                f"{sorted(selected)}, so naming them would do nothing."
            )

        edges = {
            name: [need for need in needs if need in selected]
            for name, needs in edges.items()
            if name in selected
        }
        net = Net([name for name in self.jobs if name in selected], edges)
```

Add the helper:

```python
    def _require_declared(self, names: Iterable[str], option: str) -> None:
        for name in names:
            if name not in self.jobs:
                raise FlowException(
                    f"{option} names '{name}', which flow "
                    f"'{self.spec.name}' does not declare. Declared jobs: "
                    f"{sorted(self.jobs)}."
                )
```

Thread `forced` into `_run_job` so an invalidated job does not consult the cache:

```python
    def _run_job(self, job, state_in, steps_run, deferred, forced=False):
        ...
            reused = None if forced else reusable_state(step_dir, key, self.fingerprinter)
```

Extend the imports with `from .spec_graph import ancestors, descendants`.

- [ ] **Step 4: Replace the command-line options**

In `librelane/cli/options.py`, delete `FromOption` and `ToOption` and add:

```python
TargetOption = Annotated[
    list[str] | None,
    typer.Option(
        "--target",
        "-T",
        help="Run this job and everything it transitively needs, and nothing else. May be specified multiple times.",
        rich_help_panel=WORKFLOW_OPTIONS,
    ),
]
InvalidateOption = Annotated[
    list[str] | None,
    typer.Option(
        "--invalidate",
        "-F",
        help="Treat this job and every job downstream of it as having no reusable result, forcing them to re-run. Use this when something a resume key cannot hash has changed, such as a CAD tool binary or an edited script.",
        rich_help_panel=WORKFLOW_OPTIONS,
    ),
]
```

Rename the panel constant `SEQUENTIAL_OPTIONS = "Sequential flow controls"` to `WORKFLOW_OPTIONS = "Workflow controls"` and update `SkipOption`, `ReproducibleOption` and `ExplainOption` to use it. Update `SkipOption`'s help to say "job ID" rather than "step ID", and `ExplainOption` to drop "Requires a sequential flow."

- [ ] **Step 5: Update `FlowRequest`**

In `librelane/cli/run.py`, replace the `frm: str | None` and `to: str | None` fields of `FlowRequest` with:

```python
    target: tuple[str, ...]
    invalidate: tuple[str, ...]
```

Update every construction site and every pass-through into `flow.start`. `grep -rn "frm\|\.to\b" librelane/cli/` finds them all.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed. Tests in `test/cli/` referring to `--from` or `--to` must be updated to the new options in the same commit.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: replace --from and --to with --invalidate and --target"
```

---

### Task 6: `--explain` reports jobs

**Files:**
- Modify: `librelane/flows/explanation.py`, `librelane/flows/engine.py`, `librelane/cli/run.py`
- Test: `test/flows/test_explain.py`

**Design notes the implementer needs:**

`StepDisposition` becomes `JobDisposition`, gaining a `needs: tuple[str, ...]` field. `Explanation.unselected_stages` is deleted, along with `test_an_unselected_stage_is_reported_separately`: a job that should not run is simply absent from the document, so there is no such thing as an unselected job to report.

Mechanisms become `condition`, `skip` and `not-in-target`.

- [ ] **Step 1: Write the failing test**

Replace the contents of `test/flows/test_explain.py` with tests against the document engine:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_explain_names_the_condition_that_stops_a_job(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [
                {
                    "name": "RUN_FIRST",
                    "type": "bool",
                    "description": "x",
                    "default": False,
                }
            ],
            "jobs": {"first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}},
        }
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain()

    first = explanation.jobs[0]
    assert first.job_id == "first"
    assert first.will_run is False
    assert first.mechanism == "condition"
    assert "RUN_FIRST" in first.reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_explain_marks_jobs_outside_the_target_subgraph(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain(
        target=["first"]
    )

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is True
    assert by_id["second"].mechanism == "not-in-target"
    assert by_id["second"].needs == ("first",)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest test/flows/test_explain.py -v`
Expected: FAIL with `AttributeError` on `Explanation.jobs`

- [ ] **Step 3: Rewrite `explanation.py`**

```python
@dataclass(frozen=True)
class JobDisposition:
    job_id: str
    needs: tuple[str, ...]
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class Explanation:
    jobs: tuple[JobDisposition, ...]
```

- [ ] **Step 4: Add `Workflow.explain`**

Mirror `run`'s selection logic without executing anything, returning one `JobDisposition` per job in `topological_order`.

- [ ] **Step 5: Rewrite `format_explanation` in `librelane/cli/run.py`**

Columns become `JOB`, `RUN`, `MECHANISM`, `NEEDS`, `REASON`. Delete the `unselected_stages` footer. Remove the `isinstance(flow, SequentialFlow)` guard, since every flow is a `Workflow` now.

- [ ] **Step 6: Run the tests, lint and commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: --explain reports jobs and their edges"
```

---

### Task 7: Point the command line at documents

**Files:**
- Modify: `librelane/cli/run.py:117-160`
- Test: `test/cli/test_entry_points.py`

- [ ] **Step 1: Change `select_flow` to return a document**

```python
def select_flow(request: FlowRequest) -> FlowSpec:
    """Pick the flow document named by --flow, else by the config file's meta object."""
    target: FlowSpec | None = Flow.factory.get_document("Classic")
    ...
```

Every failure path keeps its current shape: an unknown name is an error listing `Flow.factory.list()`, and a non-string `meta.flow` is an error.

- [ ] **Step 2: Construct a `Workflow` at the call site**

Where `start_flow` currently instantiates the selected class, instantiate `Workflow(spec, ...)` instead.

- [ ] **Step 3: Run the CLI tests**

Run: `uv run pytest test/cli -v`
Expected: all pass

- [ ] **Step 4: Run the flow end to end by hand**

Run: `uv run librelane --explain librelane/examples/spm/config.yaml`
Expected: a job table with a `NEEDS` column and no `Stages contributing no steps` footer.

Run: `uv run librelane --target signoff_sta librelane/examples/spm/config.yaml`
Expected: the run stops after signoff STA, and no streamout, DRC or LVS directory exists under the run tag.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat!: run workflow documents from the command line"
```

---

### Task 8: The document's `with` block layers into the configuration

**Files:**
- Modify: `librelane/config/config.py:560-640`
- Modify: `librelane/flows/flow.py:491-501`
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_document_values.py`

**Interfaces:**
- Consumes: `FlowSpec.values` from phase 1, `Workflow` from phase 2.
- Produces:
  - `Config.load(..., flow_values: Mapping[str, Any] | None = None)`. When given, it becomes the first `ConfigSource` in the layered list, named `<flow document>`.
  - `Flow.values: dict[str, Any]`, a class attribute defaulting to `{}`, which `Workflow.__init__` assigns from `spec.values` before calling `super().__init__`.

**Context the implementer needs:**

`Config.load` builds an ordered `list[ConfigSource]` at `config.py:591-634` and hands it to `layer_mappings`, which merges in order and records the last source to write each top-level key in `LayeredMapping.provenance`. The design configuration files are that list today. Inserting the document's values at the **front** makes the design override the document, which is the required precedence.

The PDK is merged separately. `Config.__from_mapping` seeds `mutable` from `__get_pdk_config` and then applies the layered design mapping on top at `config.py:764`. So a value in the document beats a PDK default without any further change, and the full order comes out as PDK, then SCL, then the document, then the design, then `--config-override`.

Do not fold the document values into `configs_validated`. That loop also computes `meta` and `file_design_dir`, and the document is neither a design directory nor a source of `meta`.

One consequence worth knowing rather than testing for: `preprocess_dict` runs over the merged mapping, so `dir::` and `expr::` work inside a document's `with` block, resolved against the design's `DESIGN_DIR` like any other value.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_document_values.py`:

```python
import pytest

from librelane.config import Config
from librelane.flows.spec import FlowSpec, JobSpec
from librelane.flows.engine import Workflow

pytestmark = pytest.mark.all


def test_a_document_value_is_used_when_the_design_is_silent(tmp_path):
    config, _ = Config.load(
        config_in={"DESIGN_NAME": "t", "CLOCK_PORT": "clk", "CLOCK_PERIOD": 10},
        flow_config_vars=Workflow(_spec()).get_all_config_variables(),
        flow_values={"FP_SIZING": "absolute"},
        design_dir=str(tmp_path),
        **_MOCK_PDK,
    )

    assert config["FP_SIZING"] == "absolute"


def test_the_design_overrides_a_document_value(tmp_path):
    config, _ = Config.load(
        config_in={
            "DESIGN_NAME": "t",
            "CLOCK_PORT": "clk",
            "CLOCK_PERIOD": 10,
            "FP_SIZING": "relative",
        },
        flow_config_vars=Workflow(_spec()).get_all_config_variables(),
        flow_values={"FP_SIZING": "absolute"},
        design_dir=str(tmp_path),
        **_MOCK_PDK,
    )

    assert config["FP_SIZING"] == "relative"


def test_a_document_value_naming_an_undeclared_variable_is_rejected(tmp_path):
    from librelane.config import InvalidConfig

    with pytest.raises(InvalidConfig) as exc_info:
        Config.load(
            config_in={"DESIGN_NAME": "t", "CLOCK_PORT": "clk", "CLOCK_PERIOD": 10},
            flow_config_vars=Workflow(_spec()).get_all_config_variables(),
            flow_values={"NOT_A_VARIABLE": 1},
            design_dir=str(tmp_path),
            **_MOCK_PDK,
        )

    assert "NOT_A_VARIABLE" in str(exc_info.value)


def _spec() -> FlowSpec:
    return FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )
```

`_MOCK_PDK` is the fixture the existing flow tests use. Copy it from `test/flows/conftest.py` rather than reinventing a PDK.

The third test needs no new code. `validate_mapping` already runs with `on_unknown_key="error"`, so an unknown key in any layered source is rejected, and the `provenance` map names `<flow document>` in the diagnostic. This test pins that the document gets the same treatment as a design file, which is the whole reason for making it a `ConfigSource` rather than a separate merge.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_document_values.py -v`
Expected: FAIL with `TypeError: load() got an unexpected keyword argument 'flow_values'`

- [ ] **Step 3: Add the parameter to `Config.load`**

Add `flow_values: Mapping[str, Any] | None = None` to the signature, and seed the source list before the `configs_validated` loop:

```python
        sources: list[ConfigSource] = []
        if flow_values is not None:
            sources.append(
                ConfigSource(dict(flow_values), "<flow document>", "mapping")
            )
        meta = Meta()
        for config_validated in configs_validated:
```

Document the parameter in the NumPy `Parameters` block, stating the precedence in one line.

- [ ] **Step 4: Carry the values from the document to the loader**

Add `values: dict[str, Any] = {}` to `Flow` beside `Steps`. In `Workflow.__init__`, assign `self.values = dict(spec.values)` before `super().__init__(...)`. In `Flow.__init__`, pass `flow_values=self.values` to `Config.load`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_document_values.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest test -m all`
Expected: no new failures. The six shipped documents set no values, so every existing test layers an empty document.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: a workflow document supplies configuration values"
```

---

### Task 9: `--explain` reports variable reach

**Files:**
- Modify: `librelane/flows/explanation.py`
- Modify: `librelane/flows/engine.py`
- Modify: `librelane/cli/run.py`
- Test: `test/flows/test_explain.py`

**Interfaces:**
- Consumes: `Explanation` and `Workflow.explain` from Task 6, `Config.load(flow_values=...)` from Task 8.
- Produces:
  - `VariableDisposition` frozen dataclass with `name: str`, `value: Any`, `origin: str`, `universal: bool`, `reach: tuple[str, ...]`.
  - `Explanation.variables: tuple[VariableDisposition, ...]`.

**Context the implementer needs:**

A variable's reach has never been visible anywhere, which is exactly why a per-job `with` block was rejected in the spec. This task makes it visible.

Reach is every job for a variable in `flow_common_variables`, since `Step.get_all_config_variables` (`steps/step/core.py:528`) seeds its dict from that list unconditionally. For every other variable it is the jobs whose steps declare it in `Step.config_vars`. Set `universal` rather than listing 24 job ids, because a universal variable reaching everything is a different fact from a variable that happens to be read by every job.

`origin` comes from `LayeredMapping.provenance`, which `layer_mappings` already records per top-level key. A variable no source wrote has no provenance entry, and its origin is the string `default`.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_explain.py`:

```python
def test_explain_reports_a_universal_variable_as_reaching_everything(counting_steps):
    spec = FlowSpec(
        name="T",
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain()
    die_area = next(v for v in explanation.variables if v.name == "DIE_AREA")

    assert die_area.universal
    assert set(die_area.reach) == {job.job_id for job in explanation.jobs}


def test_explain_scopes_a_step_variable_to_the_jobs_that_read_it(counting_steps):
    spec = FlowSpec(
        name="T",
        jobs={
            "synthesis": JobSpec(uses="synthesis"),
            "floorplan": JobSpec(needs=["synthesis"], uses="floorplan"),
        },
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain()
    strategy = next(v for v in explanation.variables if v.name == "SYNTH_STRATEGY")

    assert not strategy.universal
    assert strategy.reach == ("synthesis",)


def test_explain_reports_a_variable_read_by_several_jobs(counting_steps):
    spec = FlowSpec(
        name="T",
        jobs={
            "floorplan": JobSpec(uses="floorplan"),
            "global_placement": JobSpec(needs=["floorplan"], uses="global_placement"),
        },
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain()
    util = next(v for v in explanation.variables if v.name == "FP_CORE_UTIL")

    assert not util.universal
    assert set(util.reach) == {"floorplan", "global_placement"}


def test_explain_names_the_document_as_the_origin_of_a_document_value(counting_steps):
    spec = FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    explanation = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK).explain()
    sizing = next(v for v in explanation.variables if v.name == "FP_SIZING")

    assert sizing.value == "absolute"
    assert sizing.origin == "<flow document>"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_explain.py -v`
Expected: FAIL with `AttributeError` on `Explanation.variables`

- [ ] **Step 3: Add `VariableDisposition`**

```python
@dataclass(frozen=True)
class VariableDisposition:
    name: str
    value: Any
    #: The layer that supplied the value, or ``default`` if none did.
    origin: str
    #: True when the variable is in ``flow_common_variables`` and so is
    #: readable by every step regardless of what any step declares.
    universal: bool
    reach: tuple[str, ...]
```

Add `variables: tuple[VariableDisposition, ...]` to `Explanation`.

- [ ] **Step 4: Compute reach in `Workflow.explain`**

```python
    def _variable_dispositions(self) -> tuple[VariableDisposition, ...]:
        universal = {variable.name for variable in flow_common_variables}
        readers: dict[str, list[str]] = {}
        for job_id, job in self.jobs.items():
            for step in job.steps:
                for variable in step.config_vars:
                    readers.setdefault(variable.name, []).append(job_id)

        every_job = tuple(self.jobs)
        dispositions = []
        for variable in self.get_all_config_variables():
            is_universal = variable.name in universal
            dispositions.append(
                VariableDisposition(
                    name=variable.name,
                    value=self.config[variable.name],
                    origin=self.config.provenance.get(variable.name, "default"),
                    universal=is_universal,
                    reach=every_job
                    if is_universal
                    else tuple(dict.fromkeys(readers.get(variable.name, []))),
                )
            )
        return tuple(dispositions)
```

`dict.fromkeys` deduplicates while keeping declaration order, because a job's steps commonly declare the same variable more than once.

`Config` does not expose `provenance` today. `Config.load` computes the map at `config.py:636-646` and passes it to `validate_mapping` for diagnostics, but never keeps it. Store it on the `Config` object and expose it as a read-only property. Note that `config.py:646` already writes `<command line>` for `--config-override` keys, so `<flow document>` follows an established naming convention rather than inventing one.

- [ ] **Step 5: Render it in `librelane/cli/run.py`**

Print a second table under the job table, `VARIABLE`, `VALUE`, `ORIGIN`, `REACH`, with `REACH` showing `universal, read by all N jobs` when `universal` is set and a comma-separated job list otherwise. Suppress rows whose origin is `default`, so the table shows what someone actually chose. Add `--explain-variables` to show every row including defaults, since a variable sitting at its default is exactly what someone debugging an unexpected value wants to see.

- [ ] **Step 6: Run the tests, lint and commit**

```bash
uv run pytest test -x -q
uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .
git add librelane test
git commit -m "feat: --explain reports configuration variable reach and origin"
```

---

## What this phase does not do

`SequentialFlow`, `StagedFlow` and `Flow`-as-a-base still exist, and `test_documents.py` still compares each document against the Python flow it replaces. That comparison is what makes phase 5's deletions safe, so it must survive until phase 5 removes both sides together.
