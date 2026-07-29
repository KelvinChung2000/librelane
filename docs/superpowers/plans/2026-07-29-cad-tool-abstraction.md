# CAD Tool Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user select the tool for each phase of a LibreLane flow from configuration, with an enforced contract at every phase boundary, without writing a new `Flow` subclass.

**Architecture:** A new `librelane/stages/` package defines a `Stage` (a named, contract-carrying phase) and a `StageRegistry` (a mapping from a span of consecutive stages plus a provider name to an ordered sequence of concrete `Step` classes). A new `StagedFlow` subclass of `SequentialFlow` expands a `Stages` list into the flat `Steps` list that `SequentialFlow` already runs, at class-definition time using stage defaults and again at instance time when the `TOOLS` configuration key selects a non-default provider. `Classic` is converted in place to a `StagedFlow`, and a golden-file equivalence test proves its expanded step list is byte-identical to today's.

**Tech Stack:** Python 3.10+, pydantic config models, pytest with pytest-mock, `uv` for dependency management.

**Spec:** `docs/superpowers/specs/2026-07-29-cad-tool-abstraction-design.md`

## Global Constraints

- **No fallbacks.** Every failure path raises with a precise message. There is no default value, no silent skip, and no warn-and-continue for any contract, resolution or registration check. This is the single most important rule in this plan: the abstraction exists to make an unmet contract loud.
- **No `from __future__ import annotations`** in new files. Write types directly. (Existing files that already have it keep it; do not remove it from files you are only editing.)
- **pytest and pytest-mock only.** No `unittest.mock` in new tests except through the existing `test/conftest.py` helpers.
- **`uv` for all dependency management.** Run tests with `uv run pytest`.
- **No new runtime dependencies.** Everything needed (`rapidfuzz`, pydantic, `loguru`) is already a dependency.
- Every new file starts with the LibreLane Apache-2.0 header used by `librelane/config/loading/sources.py`: `# Copyright 2026 LibreLane Contributors`.
- New tests carry `pytestmark = pytest.mark.all`, matching `test/flows/test_sequential.py:20`.
- Markdown documentation uses markdown syntax, not HTML tags.
- Do not create summary markdown files. The only documentation deliverables are the two files named in Task 15.

## Vocabulary

Used precisely throughout this plan. Do not interchange these.

- **Stage** — a named phase of the flow (`detailed_routing`). Carries the contract. Never executes anything itself.
- **Provider** — a tool name (`openroad`, `innovus`). Not a vendor name.
- **Registration** — the object binding one span of stages plus one provider to one ordered list of step classes.
- **Span** — the tuple of stage ids a single registration covers. Length 1 for ordinary registrations.
- **Expansion** — turning a `Stages` list into a flat `Steps` list.
- **Resolution** — choosing a provider per stage from `TOOLS`, then expanding.
- **Boundary** — the point after the last step of a span, where the runtime contract is checked.

## File Structure

**New package `librelane/stages/`**

| File | Responsibility |
| --- | --- |
| `librelane/stages/__init__.py` | Public exports: `Stage`, `StageRegistry`, `Registration`, `StageContractError`, `StageResolutionError`. Imports `taxonomy` and `providers` for their registration side effects. |
| `librelane/stages/stage.py` | The `Stage` frozen dataclass, its metaclass and factory, and the shared view/metric contract constants. No knowledge of steps. |
| `librelane/stages/registry.py` | The `Registration` frozen dataclass, the `StageRegistry` singleton, registration-time contract checks, and the step-tagging helper. |
| `librelane/stages/taxonomy.py` | The 27 `Stage` definitions. Data only. |
| `librelane/stages/providers.py` | Every open-source provider registration (`verilator`, `yosys`, `yosys_vhdl`, `openroad`, `magic`, `klayout`, `netgen`). Data only, but imports step classes. |
| `librelane/stages/resolution.py` | `resolve()`: `TOOLS` mapping plus a `Stages` list to a flat step list plus a span map. Pure function, no `Flow` knowledge, so it is testable alone. |

**New module in an existing package**

| File | Responsibility |
| --- | --- |
| `librelane/steps/step/composition.py` | `compose_step_sequence()`, the running union of unmet inputs, outputs and config variables across an ordered step list. Extracted from `CompositeStep.__init_subclass__` and used by both it and `StageRegistry.register`. |
| `librelane/flows/staged.py` | `StagedFlow`. Class-definition-time expansion, instance-time re-expansion, the `TOOLS` pre-pass, stage gating, preflight checks and the runtime contract check. |

**Modified**

| File | Change |
| --- | --- |
| `librelane/steps/step/composite.py:52-85` | Delegate the union logic to `compose_step_sequence`. |
| `librelane/flows/sequential.py:340-385` | Add the `_after_step` hook to the run loop; reject gating keys matching no step. |
| `librelane/flows/classic.py` | `Classic` becomes a `StagedFlow` with a `Stages` list; `VHDLClassic` keeps working but is documented as expressible in configuration. |
| `librelane/flows/__init__.py` | Export `StagedFlow`. |
| `librelane/config/loading/__init__.py` | Export `extract_tools`. |
| `librelane/cli/steps.py` | `--list-stages`. |

**Tests**

| File | Covers |
| --- | --- |
| `test/flows/test_staged_equivalence.py` | The golden-file `Classic` and `VHDLClassic` equivalence tests and the gating equivalence matrix. |
| `test/flows/classic_steps.json`, `test/flows/vhdl_classic_steps.json`, `test/flows/classic_gating.json` | Golden files. |
| `test/stages/conftest.py` | The mock provider fixture. |
| `test/stages/test_stage.py`, `test_registry.py`, `test_resolution.py` | Unit tests for the three core modules. |
| `test/flows/test_staged.py` | `StagedFlow` behaviour: expansion, `TOOLS`, gating, contract enforcement, spanning, partial execution. |
| `test/steps/test_composition.py` | The extracted union helper. |

## Task Ordering Rationale

Task 1 captures the safety net before anything changes. Tasks 2 to 6 build the parts bottom-up with no behaviour change to any existing flow. Task 7 introduces `StagedFlow` validated against a synthetic flow. Task 8 is the load-bearing one: `Classic` converts and the Task 1 goldens must still pass. Tasks 9 to 14 add the capabilities that only matter once a non-default provider exists. Task 15 is documentation and CLI.

**If Task 8 cannot be made to pass, stop and report.** Do not adjust the golden file to match the new output. The golden file is the specification of correct behaviour; a mismatch means the taxonomy or a provider sequence is wrong.

---

### Task 1: Capture golden files for `Classic` and `VHDLClassic`

This runs **before any production code changes**. It records today's behaviour so Task 8 can prove it is preserved.

**Files:**
- Create: `test/flows/test_staged_equivalence.py`
- Create (generated): `test/flows/classic_steps.json`, `test/flows/vhdl_classic_steps.json`, `test/flows/classic_gating.json`

**Interfaces:**
- Consumes: nothing.
- Produces: three golden JSON files, and the test module that asserts against them. Task 8 does not modify this test module or these files.

- [ ] **Step 1: Write the generator script**

Create `test/flows/test_staged_equivalence.py`:

```python
# Copyright 2026 LibreLane Contributors
import json
import os

import pytest

from librelane.flows import Flow

pytestmark = pytest.mark.all

GOLDEN_DIR = os.path.dirname(__file__)


def _step_ids(FlowClass) -> list[str]:
    return [step.id for step in FlowClass.Steps]


def _implementation_ids(FlowClass) -> list[str]:
    return [step.get_implementation_id() for step in FlowClass.Steps]


def _snapshot(FlowClass) -> dict:
    return {
        "step_ids": _step_ids(FlowClass),
        "implementation_ids": _implementation_ids(FlowClass),
        "gating_config_vars": {
            key: list(value)
            for key, value in sorted(FlowClass.gating_config_vars.items())
        },
        "config_var_names": sorted(
            variable.name for variable in FlowClass.config_vars
        ),
    }


def _load_golden(name: str) -> dict:
    with open(os.path.join(GOLDEN_DIR, name), encoding="utf8") as stream:
        return json.load(stream)


def test_classic_steps_match_golden():
    Classic = Flow.factory.get("Classic")
    assert _snapshot(Classic) == _load_golden("classic_steps.json")


def test_vhdl_classic_steps_match_golden():
    VHDLClassic = Flow.factory.get("VHDLClassic")
    assert _snapshot(VHDLClassic) == _load_golden("vhdl_classic_steps.json")
```

- [ ] **Step 2: Generate the two golden files**

Run this once, from the repository root, using the **unmodified** tree:

```bash
uv run python -c '
import json, os
from librelane.flows import Flow
import test.flows.test_staged_equivalence as m
for flow_name, filename in (("Classic", "classic_steps.json"), ("VHDLClassic", "vhdl_classic_steps.json")):
    path = os.path.join("test/flows", filename)
    with open(path, "w", encoding="utf8") as f:
        json.dump(m._snapshot(Flow.factory.get(flow_name)), f, indent=2)
        f.write("\n")
    print("wrote", path)
'
```

- [ ] **Step 3: Inspect the generated files**

Read `test/flows/classic_steps.json`. It must contain 80 entries under `step_ids`, with `OpenROAD.STAMidPNR`, `OpenROAD.STAMidPNR-1` … `OpenROAD.STAMidPNR-4` and `OpenROAD.CheckAntennas`, `OpenROAD.CheckAntennas-1` showing the duplicate-ID normalization. If the count differs from 80, that is fine, but record the actual number in the commit message. Do not hand-edit either file.

- [ ] **Step 4: Capture the gating matrix**

Append to `test/flows/test_staged_equivalence.py`:

```python
GATING_VARIABLES = [
    "RUN_TAP_ENDCAP_INSERTION",
    "RUN_POST_GPL_DESIGN_REPAIR",
    "RUN_POST_GRT_DESIGN_REPAIR",
    "RUN_CTS",
    "RUN_POST_CTS_RESIZER_TIMING",
    "RUN_POST_GRT_RESIZER_TIMING",
    "RUN_HEURISTIC_DIODE_INSERTION",
    "RUN_ANTENNA_REPAIR",
    "RUN_DRT",
    "RUN_FILL_INSERTION",
    "RUN_MCSTA",
    "RUN_SPEF_EXTRACTION",
    "RUN_IRDROP_REPORT",
    "RUN_LVS",
    "RUN_MAGIC_STREAMOUT",
    "RUN_KLAYOUT_STREAMOUT",
    "RUN_MAGIC_WRITE_LEF",
    "RUN_KLAYOUT_XOR",
    "RUN_MAGIC_DRC",
    "RUN_KLAYOUT_DRC",
    "RUN_EQY",
    "RUN_LINTER",
]


def _gated_step_ids(FlowClass, disabled: str) -> list[str]:
    """Step IDs that would be skipped if exactly `disabled` were False."""
    from librelane.common import Filter

    step_ids = [step.id for step in FlowClass.Steps]
    gated = set()
    for key, variables in FlowClass.gating_config_vars.items():
        if disabled not in variables:
            continue
        if key in step_ids:
            gated.add(key)
            continue
        gated.update(Filter([key]).filter(step_ids))
    return sorted(gated)


def test_classic_gating_matches_golden():
    Classic = Flow.factory.get("Classic")
    observed = {
        variable: _gated_step_ids(Classic, variable)
        for variable in GATING_VARIABLES
    }
    assert observed == _load_golden("classic_gating.json")
```

- [ ] **Step 5: Generate the gating golden file**

```bash
uv run python -c '
import json
from librelane.flows import Flow
import test.flows.test_staged_equivalence as m
Classic = Flow.factory.get("Classic")
observed = {v: m._gated_step_ids(Classic, v) for v in m.GATING_VARIABLES}
with open("test/flows/classic_gating.json", "w", encoding="utf8") as f:
    json.dump(observed, f, indent=2)
    f.write("\n")
'
```

Every one of the 22 variables must map to a non-empty list. If any maps to `[]`, that variable gates nothing today and you have found a pre-existing bug: record it in the commit message and continue.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_staged_equivalence.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add test/flows/test_staged_equivalence.py test/flows/classic_steps.json test/flows/vhdl_classic_steps.json test/flows/classic_gating.json
git commit -m "test: capture Classic and VHDLClassic step lists as golden files"
```

---

### Task 2: Extract the step-sequence union helper

`CompositeStep.__init_subclass__` (`librelane/steps/step/composite.py:52-85`) already computes the running union of unmet inputs, outputs and config variables across an ordered step list. `StageRegistry.register` needs exactly the same computation. Extract it once.

**Files:**
- Create: `librelane/steps/step/composition.py`
- Modify: `librelane/steps/step/composite.py:52-85`
- Test: `test/steps/test_composition.py`

**Interfaces:**
- Consumes: `Step`, `DesignFormat`, `Variable`.
- Produces:
  - `class StepSequenceUnion` with fields `unmet_inputs: list[DesignFormat]`, `outputs: list[DesignFormat]`, `config_vars: list[Variable]`.
  - `def compose_step_sequence(steps: Sequence[type[Step]]) -> StepSequenceUnion`, raising `TypeError` on contradictory config variable declarations.
  - Task 4 calls `compose_step_sequence`.

- [ ] **Step 1: Write the failing test**

Create `test/steps/test_composition.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


@pytest.fixture
def steps():
    from librelane.config import Variable
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class A(Step):
        id = "Composition.A"
        inputs = [DesignFormat.nl]
        outputs = [DesignFormat.odb]
        config_vars = [Variable("A_VAR", int, "desc", default=1)]

        def run(self, state_in, **kwargs):
            return {}, {}

    class B(Step):
        id = "Composition.B"
        inputs = [DesignFormat.odb]
        outputs = [DesignFormat.def_]
        config_vars = [Variable("B_VAR", int, "desc", default=2)]

        def run(self, state_in, **kwargs):
            return {}, {}

    return A, B


def test_unmet_inputs_exclude_views_produced_earlier(steps):
    from librelane.state import DesignFormat
    from librelane.steps.step.composition import compose_step_sequence

    A, B = steps
    union = compose_step_sequence([A, B])

    assert union.unmet_inputs == [DesignFormat.nl]
    assert set(union.outputs) == {DesignFormat.odb, DesignFormat.def_}
    assert [v.name for v in union.config_vars] == ["A_VAR", "B_VAR"]


def test_unmet_inputs_preserve_first_appearance_order(steps):
    from librelane.state import DesignFormat
    from librelane.steps.step.composition import compose_step_sequence

    A, B = steps
    union = compose_step_sequence([B, A])

    assert union.unmet_inputs == [DesignFormat.odb, DesignFormat.nl]


def test_contradictory_config_vars_raise(steps):
    from librelane.config import Variable
    from librelane.steps import Step
    from librelane.steps.step.composition import compose_step_sequence

    A, _ = steps

    class Conflicting(Step):
        id = "Composition.Conflicting"
        inputs = []
        outputs = []
        config_vars = [Variable("A_VAR", str, "different", default="x")]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(TypeError, match="contradicts an earlier declaration"):
        compose_step_sequence([A, Conflicting])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/steps/test_composition.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'librelane.steps.step.composition'`

- [ ] **Step 3: Write the implementation**

Create `librelane/steps/step/composition.py`:

```python
# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from collections.abc import Sequence

from ...config import Variable
from ...state import DesignFormat

from .core import Step


@dataclass(frozen=True)
class StepSequenceUnion:
    """
    The aggregate view and configuration contract of an ordered sequence of
    steps, treated as if it ran as a unit.

    :param unmet_inputs: Views the sequence consumes that no earlier step in
        the sequence produces, in order of first appearance.
    :param outputs: Every view any step in the sequence produces.
    :param config_vars: Every configuration variable any step in the sequence
        declares, deduplicated, in order of first appearance.
    """

    unmet_inputs: list[DesignFormat]
    outputs: list[DesignFormat]
    config_vars: list[Variable]


def compose_step_sequence(steps: Sequence[type[Step]]) -> StepSequenceUnion:
    """
    Walks an ordered step sequence, accumulating the views it needs from
    outside, the views it produces, and the configuration variables it
    declares.

    :param steps: The ordered step sequence.
    :raises TypeError: If two steps declare a variable of the same name with
        differing definitions.
    """
    available: set[DesignFormat] = set()
    unmet_inputs: list[DesignFormat] = []
    outputs: list[DesignFormat] = []
    config_vars: dict[str, Variable] = {}

    for step in steps:
        for input in step.inputs:
            if input not in available:
                unmet_inputs.append(input)
                available.add(input)
        for output in step.outputs:
            if output not in available:
                available.add(output)
            if output not in outputs:
                outputs.append(output)
        for cvar in step.config_vars:
            existing = config_vars.get(cvar.name)
            if existing is None:
                config_vars[cvar.name] = cvar
            elif existing != cvar:
                raise TypeError(
                    f"Step sequence has mismatching config_vars: {cvar.name} "
                    f"contradicts an earlier declaration"
                )

    return StepSequenceUnion(unmet_inputs, outputs, list(config_vars.values()))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/steps/test_composition.py -v`
Expected: 3 passed.

- [ ] **Step 5: Make `CompositeStep` use the helper**

In `librelane/steps/step/composite.py`, add to the imports:

```python
from .composition import compose_step_sequence
```

and replace the body of `__init_subclass__` (lines 52 through 85) with:

```python
    def __init_subclass__(Self):
        super().__init_subclass__()
        union = compose_step_sequence(Self.Steps)
        Self.inputs = union.unmet_inputs
        if Self.outputs == NotImplemented:  # Allow for setting explicit outputs
            Self.outputs = union.outputs
        Self.config_vars = union.config_vars
        Self.install_config_model(
            variables_to_model(
                f"{Self.__name__}Config",
                Self.config_vars,
                base=Step.Config,
            )
        )
```

Then delete the now-unused `DesignFormat` and `Variable` imports from `composite.py` only if nothing else in the file uses them. `DesignFormat` is still used at line 111, so keep it; `Variable` becomes unused, so remove it from the `...config` import.

- [ ] **Step 6: Run the full step and flow test suites**

Run: `uv run pytest test/steps test/flows -q`
Expected: all pass, including `test/flows/test_staged_equivalence.py` from Task 1. The union order changed from set iteration to first-appearance order, so if any `CompositeStep`-derived step's `inputs` ordering is asserted anywhere, that assertion now sees a deterministic order. Ordering is not semantically meaningful for `inputs`, so update any such assertion to compare sets.

- [ ] **Step 7: Commit**

```bash
git add librelane/steps/step/composition.py librelane/steps/step/composite.py test/steps/test_composition.py
git commit -m "refactor: extract the step-sequence union out of CompositeStep"
```

---

### Task 3: The `Stage` dataclass and its factory

**Files:**
- Create: `librelane/stages/__init__.py`, `librelane/stages/stage.py`
- Test: `test/stages/__init__.py`, `test/stages/test_stage.py`

**Interfaces:**
- Consumes: `DesignFormat`, `Variable`.
- Produces:
  - `Stage` frozen dataclass with fields `id: str`, `full_name: str`, `default_provider: str | tuple[str, ...] | None`, `requires: tuple[DesignFormat, ...]`, `provides: tuple[DesignFormat, ...]`, `config_vars: tuple[Variable, ...] = ()`, `metrics: tuple[str, ...] = ()`, `gating_config_var: str | None = None`, `multi_provider: bool = False`, `optional: bool = False`.
  - `Stage.default_providers -> tuple[str, ...]`, the default normalized to a tuple (empty when unselected).

`default_provider` is a tuple for the two `multi_provider` stages, because `Classic` streams out with **both** Magic and KLayout by default and runs **both** DRC decks. A single-string default cannot express that, and expressing it in `TOOLS` instead would mean the default flow depends on a configuration key being present.
  - `Stage.register() -> Stage`, `Stage.factory.get(id) -> Stage | None`, `Stage.factory.list() -> list[str]`, and attribute access `Stage.detailed_routing`.
  - `StageError`, `StageContractError`, `StageResolutionError` exception classes.
  - Shared contract constants `PNR_IN_PLACE_REQUIRES` and `PNR_IN_PLACE_PROVIDES`.
  - Tasks 4, 5, 6, 7 all import from here.

Fields are tuples rather than lists so the dataclass can stay `frozen=True` and hashable, matching `DesignFormat`'s use as a dict key.

- [ ] **Step 1: Write the failing test**

Create `test/stages/__init__.py` (empty) and `test/stages/test_stage.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_stage_registers_and_is_retrievable():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    stage = Stage(
        id="test_stage_alpha",
        full_name="Test Stage Alpha",
        default_provider="mock",
        requires=(DesignFormat.nl,),
        provides=(DesignFormat.def_,),
    ).register()

    assert Stage.factory.get("test_stage_alpha") is stage
    assert Stage.test_stage_alpha is stage
    assert "test_stage_alpha" in Stage.factory.list()


def test_unknown_stage_attribute_raises():
    from librelane.stages import Stage

    with pytest.raises(AttributeError):
        Stage.no_such_stage_exists


def test_duplicate_registration_raises():
    from librelane.stages import Stage, StageError
    from librelane.state import DesignFormat

    def make():
        return Stage(
            id="test_stage_duplicate",
            full_name="Test Stage Duplicate",
            default_provider="mock",
            requires=(DesignFormat.nl,),
            provides=(DesignFormat.nl,),
        )

    make().register()
    with pytest.raises(StageError, match="already registered"):
        make().register()


def test_optional_stage_may_have_no_default_provider():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    Stage(
        id="test_stage_optional",
        full_name="Test Stage Optional",
        default_provider=None,
        requires=(DesignFormat.def_,),
        provides=(DesignFormat.def_,),
        optional=True,
    ).register()


def test_non_optional_stage_without_default_provider_raises():
    from librelane.stages import Stage, StageError
    from librelane.state import DesignFormat

    with pytest.raises(StageError, match="marked optional"):
        Stage(
            id="test_stage_bad",
            full_name="Test Stage Bad",
            default_provider=None,
            requires=(DesignFormat.def_,),
            provides=(DesignFormat.def_,),
        ).register()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/stages/test_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'librelane.stages'`

- [ ] **Step 3: Write the implementation**

Create `librelane/stages/stage.py`:

```python
# Copyright 2026 LibreLane Contributors
import builtins
from dataclasses import dataclass, field
from typing import ClassVar

from ..config import Variable
from ..flows.flow import FlowError
from ..state import DesignFormat


class StageError(RuntimeError):
    """
    Raised when a stage or a stage registration is itself malformed. This is a
    programming error in a provider package and surfaces at import time.
    """


class StageResolutionError(FlowError):
    """
    Raised when a configuration cannot be resolved to a concrete step list:
    an unknown provider, an inconsistent span selection, a missing PDK
    variable, or an unsatisfiable view dependency.
    """


class StageContractError(FlowError):
    """
    Raised at runtime when a stage completes without having produced every
    view or metric it declared.
    """


class StageMetaclass(type):
    def __getattr__(Self, key: str):
        stage = Self.factory.get(key)
        if stage is not None:
            return stage
        raise AttributeError("Unknown Stage attribute", key, Self)


@dataclass(frozen=True)
class Stage(metaclass=StageMetaclass):
    """
    A named phase of a flow. A stage is the unit of tool substitution,
    independent gating, and flow re-entry. It never executes anything: a
    provider registration binds it to a sequence of concrete steps.

    :param id: A lowercase alphanumeric/underscore identifier, for example
        ``detailed_routing``. This is what appears in the ``TOOLS``
        configuration key and in ``--from``/``--to``.
    :param full_name: A human-readable name.
    :param default_provider: The provider used when ``TOOLS`` does not name
        one. A tuple of provider names is legal only for a
        :attr:`multi_provider` stage. ``None`` is legal only when
        :attr:`optional` is ``True``, in which case the stage is unselected and
        contributes no steps.
    :param requires: The neutral views the stage consumes at its boundary.
        A provider may additionally consume its own native views, declared on
        the registration.
    :param provides: The neutral views every provider of this stage must have
        produced by the time the stage completes. Enforced at runtime.
    :param config_vars: The canonical, portable configuration variables. Every
        provider must accept all of them; this is checked at registration.
    :param metrics: The metric names every provider of this stage must have
        produced by the time it completes. Enforced at runtime.
    :param gating_config_var: A Boolean flow configuration variable that, when
        false, skips every step of this stage.
    :param multi_provider: Whether ``TOOLS`` may name a list of providers for
        this stage, whose sequences are concatenated in listed order.
    :param optional: Whether the stage may be left unselected. Only legal for
        stages whose :attr:`provides` no later stage requires.
    """

    id: str
    full_name: str
    default_provider: str | tuple[str, ...] | None
    requires: tuple[DesignFormat, ...]
    provides: tuple[DesignFormat, ...]
    config_vars: tuple[Variable, ...] = field(default=())
    metrics: tuple[str, ...] = field(default=())
    gating_config_var: str | None = None
    multi_provider: bool = False
    optional: bool = False

    def __hash__(self):
        return hash(self.id)

    def __str__(self) -> str:
        return self.id

    @property
    def default_providers(self) -> tuple[str, ...]:
        """
        :returns: :attr:`default_provider` normalized to a tuple. Empty when
            the stage is unselected by default.
        """
        if self.default_provider is None:
            return ()
        if isinstance(self.default_provider, str):
            return (self.default_provider,)
        return tuple(self.default_provider)

    def register(self) -> "Stage":
        """
        Adds this stage to the registry. Raises :class:`StageError` if a stage
        with the same id is already registered, or if the stage is internally
        inconsistent.
        """
        if self.default_provider is None and not self.optional:
            raise StageError(
                f"Stage '{self.id}' has no default_provider but is not marked "
                f"optional. Only optional stages may be left unselected."
            )
        if len(self.default_providers) > 1 and not self.multi_provider:
            raise StageError(
                f"Stage '{self.id}' defaults to several providers "
                f"{list(self.default_providers)} but is not multi_provider."
            )
        self.__class__.factory.register(self)
        return self

    class StageFactory(object):
        """
        A factory singleton for Stages, allowing them to be registered and
        then retrieved by a string id.
        """

        _registry: ClassVar[dict[str, "Stage"]] = {}

        @classmethod
        def register(Self, stage: "Stage") -> "Stage":
            if stage.id in Self._registry:
                raise StageError(f"Stage '{stage.id}' is already registered.")
            Self._registry[stage.id] = stage
            return stage

        @classmethod
        def get(Self, id: str) -> "Stage | None":
            return Self._registry.get(id)

        @classmethod
        def list(Self) -> builtins.list[str]:
            return list(Self._registry.keys())

    factory: ClassVar = StageFactory


#: The view contract shared by every in-place place-and-route transform: a
#: stage that takes a placed-or-routed design and returns one, changing the
#: layout but not the set of views. Declared once and reused rather than
#: restated on each of the fifteen stages that share it.
PNR_IN_PLACE_REQUIRES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)

PNR_IN_PLACE_PROVIDES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)
```

Create `librelane/stages/__init__.py`:

```python
# Copyright 2026 LibreLane Contributors
"""
Stages: the unit of tool substitution, independent gating and flow re-entry.

See ``docs/source/usage/swapping_tools.md`` for user documentation and
``docs/source/usage/writing_tool_backends.md`` for the provider contract.
"""

from .stage import (
    Stage,
    StageError,
    StageContractError,
    StageResolutionError,
    PNR_IN_PLACE_REQUIRES,
    PNR_IN_PLACE_PROVIDES,
)

__all__ = [
    "Stage",
    "StageError",
    "StageContractError",
    "StageResolutionError",
    "PNR_IN_PLACE_REQUIRES",
    "PNR_IN_PLACE_PROVIDES",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/stages/test_stage.py -v`
Expected: 5 passed.

If the `from ..flows.flow import FlowError` import produces a circular import (`librelane.flows` imports `librelane.steps` which may import `librelane.stages` later), move `FlowError` out of the picture by having `StageResolutionError` and `StageContractError` inherit from `RuntimeError` here and re-deriving them in `librelane/flows/staged.py`. Prefer the direct import; only fall back to this if the import actually fails, and note it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add librelane/stages test/stages
git commit -m "feat: add the Stage dataclass and its factory"
```

---

### Task 4: `Registration`, `StageRegistry`, and registration-time contract checks

**Files:**
- Create: `librelane/stages/registry.py`
- Modify: `librelane/stages/__init__.py`
- Create: `test/stages/conftest.py`
- Test: `test/stages/test_registry.py`

**Interfaces:**
- Consumes: `Stage`, `StageError`, `compose_step_sequence` from Task 2.
- Produces:
  - `Registration` frozen dataclass: `stages: tuple[str, ...]`, `provider: str`, `steps: tuple[type[Step], ...]`, `namespaces: tuple[str, ...]`, `requires_pdk_vars: tuple[str, ...] = ()`, `provides: tuple[DesignFormat, ...] = ()`, `metrics: tuple[str, ...] = ()`, `native_views: tuple[DesignFormat, ...] = ()`. Property `spanning: bool`.
  - `StageRegistry.register(*, stages, provider, steps, namespaces, requires_pdk_vars=(), provides=(), metrics=(), native_views=()) -> Registration`
  - `StageRegistry.get(stage: str, provider: str) -> Registration | None`
  - `StageRegistry.providers(stage: str) -> list[str]`
  - `StageRegistry.list() -> list[Registration]`
  - `tag_steps(steps, span, provider) -> list[type[Step]]`, attaching `_stage_span` and `_stage_provider` class attributes via subclassing.
  - `mock_provider` pytest fixture, used by Tasks 7, 10, 11, 12, 14.
  - Task 6 calls `StageRegistry.register`; Task 7 calls `get`/`providers`; Task 11 reads `Registration.metrics` and `provides`; Task 13 reads `requires_pdk_vars`; Task 12 reads `native_views`.

**Why `Registration` carries its own `provides` and `metrics`.** The spec put the whole contract on `Stage`. That does not survive the `drc` stage, where `magic` produces `magic__drc_error__count` and `klayout` produces `klayout__drc_error__count` and neither can promise the other's. So `Stage.metrics` is the floor every provider must meet, `Registration.metrics` is what this provider additionally guarantees, and the set enforced at a boundary is the union over the selected registrations. Same for `provides`. Record this as a deviation from the spec in the commit message.

**Why `native_views` exists.** `OpenROADStep.inputs` is `[odb]` (`librelane/steps/openroad/base.py:288`), and `odb` is a tool-native view registered by OpenROAD itself (`librelane/steps/openroad/base.py:225`). Every `openroad` registration after `floorplan` therefore has an unmet input that is not in any stage's neutral `requires`. `native_views` is the declaration that the provider carries this view across boundaries itself. Views listed there are exempt from the registration-time view check and are validated instead by Task 12's static availability check.

- [ ] **Step 1: Write the mock provider fixture**

Create `test/stages/conftest.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest


@pytest.fixture
def mock_steps():
    """
    Two trivial steps that pass views through and emit one metric each.
    Registered with the Step factory so they can be named by ID.
    """
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class MockPlace(Step):
        id = "Mock.Place"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {"mock__placed": 1}

    @Step.factory.register()
    class MockRoute(Step):
        id = "Mock.Route"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {"mock__routed": 1}

    return MockPlace, MockRoute
```

- [ ] **Step 2: Write the failing tests**

Create `test/stages/test_registry.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


@pytest.fixture
def alpha_stage():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    return Stage(
        id="registry_alpha",
        full_name="Registry Alpha",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
    ).register()


@pytest.fixture
def beta_stage():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    return Stage(
        id="registry_beta",
        full_name="Registry Beta",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
    ).register()


def test_registration_is_retrievable(alpha_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="mock",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert StageRegistry.get("registry_alpha", "mock") is registration
    assert StageRegistry.providers("registry_alpha") == ["mock"]
    assert registration.spanning is False


def test_spanning_registration_covers_every_stage(alpha_stage, beta_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha", "registry_beta"],
        provider="mock_span",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )

    assert registration.spanning is True
    assert StageRegistry.get("registry_alpha", "mock_span") is registration
    assert StageRegistry.get("registry_beta", "mock_span") is registration


def test_unknown_stage_id_raises(mock_steps):
    from librelane.stages import StageError, StageRegistry

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="no stage with id 'not_a_stage'"):
        StageRegistry.register(
            stages=["not_a_stage"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_duplicate_provider_for_stage_raises(alpha_stage, mock_steps):
    from librelane.stages import StageError, StageRegistry

    MockPlace, MockRoute = mock_steps
    StageRegistry.register(
        stages=["registry_alpha"],
        provider="dup",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )
    with pytest.raises(StageError, match="already registered"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="dup",
            steps=[MockRoute],
            namespaces=["MOCK_"],
        )


def test_missing_canonical_variable_raises(mock_steps):
    from librelane.config import Variable
    from librelane.stages import Stage, StageError, StageRegistry
    from librelane.state import DesignFormat

    Stage(
        id="registry_canonical",
        full_name="Registry Canonical",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        config_vars=(Variable("TARGET_DENSITY_PCT", float, "desc", default=50.0),),
    ).register()

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="does not declare canonical variable"):
        StageRegistry.register(
            stages=["registry_canonical"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_unnamespaced_variable_raises(alpha_stage):
    from librelane.config import Variable
    from librelane.stages import StageError, StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class Rogue(Step):
        id = "Mock.Rogue"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        config_vars = [Variable("WIDGET_COUNT", int, "desc", default=3)]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(StageError, match="WIDGET_COUNT"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="rogue",
            steps=[Rogue],
            namespaces=["MOCK_"],
        )


def test_unmet_input_outside_requires_raises(alpha_stage):
    from librelane.stages import StageError, StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsGDS(Step):
        id = "Mock.NeedsGDS"
        inputs = [DesignFormat.gds]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    with pytest.raises(StageError, match="consumes view 'gds'"):
        StageRegistry.register(
            stages=["registry_alpha"],
            provider="needsgds",
            steps=[NeedsGDS],
            namespaces=["MOCK_"],
        )


def test_native_view_exempts_an_unmet_input(alpha_stage):
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class NeedsODB(Step):
        id = "Mock.NeedsODB"
        inputs = [DesignFormat.odb]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {}

    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="needsodb",
        steps=[NeedsODB],
        namespaces=["MOCK_"],
        native_views=[DesignFormat.odb],
    )
    assert registration.native_views == (DesignFormat.odb,)


def test_unprovided_view_raises(mock_steps):
    from librelane.stages import Stage, StageError, StageRegistry
    from librelane.state import DesignFormat

    Stage(
        id="registry_provides_gds",
        full_name="Registry Provides GDS",
        default_provider="mock",
        requires=(DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc),
        provides=(DesignFormat.gds,),
    ).register()

    MockPlace, _ = mock_steps
    with pytest.raises(StageError, match="never produces view 'gds'"):
        StageRegistry.register(
            stages=["registry_provides_gds"],
            provider="mock",
            steps=[MockPlace],
            namespaces=["MOCK_"],
        )


def test_tagged_steps_carry_span_and_provider(alpha_stage, mock_steps):
    from librelane.stages import StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stages=["registry_alpha"],
        provider="tagged",
        steps=[MockPlace],
        namespaces=["MOCK_"],
    )
    tagged = registration.tagged_steps()

    assert tagged[0]._stage_span == ("registry_alpha",)
    assert tagged[0]._stage_provider == "tagged"
    assert tagged[0].id == "Mock.Place"
    assert tagged[0].get_implementation_id() == "Mock.Place"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest test/stages/test_registry.py -v`
Expected: FAIL with `ImportError: cannot import name 'StageRegistry'`

- [ ] **Step 4: Write the implementation**

Create `librelane/stages/registry.py`:

```python
# Copyright 2026 LibreLane Contributors
import builtins
from dataclasses import dataclass
from typing import ClassVar
from collections.abc import Sequence

from ..config import Variable
from ..config.flow import flow_common_variables
from ..state import DesignFormat
from ..steps import Step
from ..steps.step.composition import compose_step_sequence

from .stage import Stage, StageError

_COMMON_VARIABLE_NAMES = frozenset(
    variable.name for variable in flow_common_variables
)


@dataclass(frozen=True)
class Registration:
    """
    Binds a span of one or more consecutive stages, plus one provider, to an
    ordered sequence of concrete steps.

    :param stages: The stage ids covered, in flow order. Length greater than
        one means the provider cannot decompose this span; see the
        "Spanning providers" section of the design document.
    :param provider: The tool name, for example ``openroad``. Not a vendor
        name.
    :param steps: The ordered step sequence that implements the span.
    :param namespaces: Accepted configuration variable prefixes for steps in
        this sequence. New providers declare exactly one, tool-named prefix;
        the ``openroad`` provider declares the several legacy prefixes that
        predate this design.
    :param requires_pdk_vars: Configuration variable names that must be
        non-``None`` in the resolved configuration for this provider to run.
        Checked by the PDK view preflight.
    :param provides: Views this provider guarantees beyond the stage's own
        ``provides``.
    :param metrics: Metric names this provider guarantees beyond the stage's
        own ``metrics``.
    :param native_views: Tool-native views this provider carries across stage
        boundaries itself, for example OpenROAD's ``odb``. Exempt from the
        registration-time view check; validated instead by the static view
        availability check at resolution.
    """

    stages: tuple[str, ...]
    provider: str
    steps: tuple[type[Step], ...]
    namespaces: tuple[str, ...]
    requires_pdk_vars: tuple[str, ...] = ()
    provides: tuple[DesignFormat, ...] = ()
    metrics: tuple[str, ...] = ()
    native_views: tuple[DesignFormat, ...] = ()

    @property
    def spanning(self) -> bool:
        return len(self.stages) > 1

    def tagged_steps(self) -> builtins.list[type[Step]]:
        """
        Returns the step sequence with each class subclassed to carry
        ``_stage_span`` and ``_stage_provider``.

        Tagging by subclass rather than by index range is what makes the
        boundary map survive duplicate-ID normalization and ``Substitutions``:
        ``Step.with_id`` also subclasses, so the tag is inherited, while a
        substituted-in step class carries no tag and is correctly treated as a
        plain step.
        """
        return [
            type(
                step.__name__,
                (step,),
                {
                    "_stage_span": self.stages,
                    "_stage_provider": self.provider,
                },
            )
            for step in self.steps
        ]


class StageRegistry(object):
    """
    A factory singleton mapping (stage id, provider) pairs to
    :class:`Registration` objects.
    """

    _by_stage_and_provider: ClassVar[dict[tuple[str, str], Registration]] = {}
    _all: ClassVar[builtins.list[Registration]] = []

    @classmethod
    def register(
        Self,
        *,
        stages: Sequence[str],
        provider: str,
        steps: Sequence[type[Step]],
        namespaces: Sequence[str],
        requires_pdk_vars: Sequence[str] = (),
        provides: Sequence[DesignFormat] = (),
        metrics: Sequence[str] = (),
        native_views: Sequence[DesignFormat] = (),
    ) -> Registration:
        """
        Registers a provider implementation for a span of stages, running
        every registration-time contract check. Violations raise
        :class:`StageError`, which surfaces as an import error in the
        offending provider package.
        """
        registration = Registration(
            stages=tuple(stages),
            provider=provider,
            steps=tuple(steps),
            namespaces=tuple(namespaces),
            requires_pdk_vars=tuple(requires_pdk_vars),
            provides=tuple(provides),
            metrics=tuple(metrics),
            native_views=tuple(native_views),
        )

        if len(registration.stages) == 0:
            raise StageError(
                f"Provider '{provider}' registered against no stages."
            )
        if len(registration.steps) == 0:
            raise StageError(
                f"Provider '{provider}' registered for "
                f"{list(registration.stages)} with no steps. A provider that "
                f"runs nothing cannot satisfy a stage contract."
            )

        resolved: builtins.list[Stage] = []
        for stage_id in registration.stages:
            stage = Stage.factory.get(stage_id)
            if stage is None:
                raise StageError(
                    f"Provider '{provider}': no stage with id '{stage_id}' is "
                    f"registered. Known stages: "
                    f"{sorted(Stage.factory.list())}"
                )
            key = (stage_id, provider)
            if key in Self._by_stage_and_provider:
                raise StageError(
                    f"Provider '{provider}' is already registered for stage "
                    f"'{stage_id}'."
                )
            resolved.append(stage)

        Self.__check_contract(registration, resolved)

        for stage_id in registration.stages:
            Self._by_stage_and_provider[(stage_id, provider)] = registration
        Self._all.append(registration)
        return registration

    @classmethod
    def __check_contract(
        Self,
        registration: Registration,
        stages: Sequence[Stage],
    ) -> None:
        union = compose_step_sequence(registration.steps)
        declared = {variable.name for variable in union.config_vars}

        canonical: dict[str, Variable] = {}
        for stage in stages:
            for variable in stage.config_vars:
                canonical[variable.name] = variable

        # Canonical variable coverage.
        for name in canonical:
            if name not in declared:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"{list(registration.stages)} does not declare canonical "
                    f"variable '{name}'. A user who set it would have that "
                    f"setting silently discarded."
                )

        # Namespace discipline.
        for variable in union.config_vars:
            if variable.name in canonical:
                continue
            if variable.name in _COMMON_VARIABLE_NAMES:
                continue
            if any(
                variable.name.startswith(prefix)
                for prefix in registration.namespaces
            ):
                continue
            raise StageError(
                f"Provider '{registration.provider}' for "
                f"{list(registration.stages)} declares variable "
                f"'{variable.name}', which is neither canonical for these "
                f"stages, nor a common flow variable, nor prefixed with any "
                f"of {list(registration.namespaces)}."
            )

        # View plausibility.
        allowed_inputs = set(registration.native_views)
        for stage in stages:
            allowed_inputs.update(stage.requires)
        for view in union.unmet_inputs:
            if view not in allowed_inputs:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"{list(registration.stages)} consumes view '{view.id}', "
                    f"which is neither in the stages' 'requires' nor declared "
                    f"as one of its native_views."
                )

        promised = set(registration.provides)
        for stage in stages:
            promised.update(stage.provides)
        produced = set(union.outputs)
        for view in promised:
            if view not in produced:
                raise StageError(
                    f"Provider '{registration.provider}' for "
                    f"{list(registration.stages)} never produces view "
                    f"'{view.id}', which it is contracted to provide."
                )

    @classmethod
    def get(Self, stage: str, provider: str) -> Registration | None:
        return Self._by_stage_and_provider.get((stage, provider))

    @classmethod
    def providers(Self, stage: str) -> builtins.list[str]:
        """
        :returns: Provider names registered for this stage, in registration
            order.
        """
        return [
            registration.provider
            for registration in Self._all
            if stage in registration.stages
        ]

    @classmethod
    def list(Self) -> builtins.list[Registration]:
        return list(Self._all)
```

- [ ] **Step 5: Export from the package**

In `librelane/stages/__init__.py`, add after the `.stage` import:

```python
from .registry import Registration, StageRegistry
```

and add `"Registration"` and `"StageRegistry"` to `__all__`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest test/stages -v`
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add librelane/stages test/stages
git commit -m "feat: add StageRegistry with registration-time contract checks"
```

---

### Task 5: The stage taxonomy

**Files:**
- Create: `librelane/stages/taxonomy.py`
- Modify: `librelane/stages/__init__.py`
- Test: `test/stages/test_taxonomy.py`

**Interfaces:**
- Consumes: `Stage`, `PNR_IN_PLACE_REQUIRES`, `PNR_IN_PLACE_PROVIDES`.
- Produces: 27 registered stages, and the module-level constant `STAGE_ORDER: tuple[str, ...]` giving their canonical flow order. Task 6 registers against these ids; Task 7 validates a flow's `Stages` list against `STAGE_ORDER`.

**How `requires` and `provides` are determined.** They are written as literals in this file, not computed. The values come from Task 6's derivation step, which prints the actual view union of each `openroad` provider sequence. For version one the contract is therefore descriptive: it says what the open flow already guarantees at each boundary. That is the only defensible basis available, because no commercial tool is present to argue for a different one. Task 5 lands with `requires` and `provides` set to the shared `PNR_IN_PLACE_*` constants or to obvious values, and **Task 6 corrects them from the derivation output**. The stage ids, names, defaults, gates, metrics, `multi_provider` and `optional` flags below are final and evidence-backed; do not change them in Task 6.

**Metric contracts are derived from the `MetricChecker` steps.** `MetricChecker.metric_name` (`librelane/steps/checker.py:78`) names exactly the metrics something downstream reads. Each such metric is assigned to the stage that produces it, verified by grep. Metrics whose producer is a plain step rather than a stage (`route__wirelength__max` from `Odb.ReportWireLength`, `design__critical_disconnected_pin__count` from `Odb.ReportDisconnectedPins`, `design__xor_difference__count` from `KLayout.XOR`) are deliberately **not** in any stage contract, because those steps sit between stages.

- [ ] **Step 1: Write the failing test**

Create `test/stages/test_taxonomy.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_stage_in_order_is_registered():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    for stage_id in STAGE_ORDER:
        assert Stage.factory.get(stage_id) is not None, stage_id


def test_taxonomy_has_twenty_seven_stages():
    from librelane.stages.taxonomy import STAGE_ORDER

    assert len(STAGE_ORDER) == 27
    assert len(set(STAGE_ORDER)) == 27


def test_only_post_route_opt_is_unselected():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    unselected = [
        stage_id
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).default_provider is None
    ]
    assert unselected == ["post_route_opt"]


def test_optional_stages_provide_nothing_a_later_stage_requires():
    """
    An optional stage may be skipped, so anything it provides that a later
    stage requires would produce a downstream contract failure.
    """
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    for index, stage_id in enumerate(STAGE_ORDER):
        stage = Stage.factory.get(stage_id)
        if not stage.optional:
            continue
        later_requirements = set()
        for later_id in STAGE_ORDER[index + 1 :]:
            later_requirements.update(Stage.factory.get(later_id).requires)
        exclusive = set(stage.provides) - {
            view
            for earlier_id in STAGE_ORDER[:index]
            for view in Stage.factory.get(earlier_id).provides
        }
        assert not (exclusive & later_requirements), stage_id


def test_gating_variables_are_unique():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    gates = [
        Stage.factory.get(stage_id).gating_config_var
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).gating_config_var is not None
    ]
    assert len(gates) == len(set(gates))
    assert len(gates) == 15


def test_multi_provider_stages():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    multi = [
        stage_id
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).multi_provider
    ]
    assert multi == ["streamout", "drc"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/stages/test_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'librelane.stages.taxonomy'`

- [ ] **Step 3: Write the taxonomy**

Create `librelane/stages/taxonomy.py`. The file is long but entirely declarative. Write every stage in this exact order:

```python
# Copyright 2026 LibreLane Contributors
"""
The stage taxonomy.

Stage boundaries are derived from ``Classic.gating_config_vars``
(``librelane/flows/classic.py:245-287``), which contains 22 distinct ``RUN_*``
variables. Each is a place where users already demanded the ability to turn one
phase off independently, which makes it a place where they would plausibly want
to change tools or re-enter the flow. Fifteen of those variables become stage
gates here; the remaining seven gate one tool within a stage and stay
step-level.

``requires`` and ``provides`` values are literals, not computed. See the
implementation plan for how they were derived.
"""

from ..config import Variable
from ..state import DesignFormat

from .stage import Stage, PNR_IN_PLACE_PROVIDES, PNR_IN_PLACE_REQUIRES

_NO_VIEWS: tuple[DesignFormat, ...] = ()


Stage(
    id="lint",
    full_name="RTL Linting",
    default_provider="verilator",
    requires=_NO_VIEWS,
    provides=_NO_VIEWS,
    metrics=(
        "design__lint_error__count",
        "design__lint_warning__count",
        "design__lint_timing_construct__count",
    ),
    gating_config_var="RUN_LINTER",
    optional=True,
).register()

Stage(
    id="synthesis",
    full_name="Synthesis",
    default_provider="yosys",
    requires=_NO_VIEWS,
    provides=(DesignFormat.nl,),
    metrics=(
        "design__instance_unmapped__count",
        "synthesis__check_error__count",
    ),
).register()

Stage(
    id="pre_pnr_sta",
    full_name="Pre-PnR Static Timing Analysis",
    default_provider="openroad",
    requires=(DesignFormat.nl,),
    provides=(DesignFormat.nl, DesignFormat.sdc),
).register()

Stage(
    id="floorplan",
    full_name="Floorplanning",
    default_provider="openroad",
    requires=(DesignFormat.nl, DesignFormat.sdc),
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="macro_placement",
    full_name="Macro Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="tapcell_insertion",
    full_name="Tap and Endcap Cell Insertion",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_TAP_ENDCAP_INSERTION",
    optional=True,
).register()

Stage(
    id="power_grid",
    full_name="Power Distribution Network Generation",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    metrics=("design__power_grid_violation__count",),
).register()

Stage(
    id="io_placement",
    full_name="I/O Pin Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="global_placement",
    full_name="Global Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="post_gpl_repair",
    full_name="Post-Global-Placement Design Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GPL_DESIGN_REPAIR",
    optional=True,
).register()

Stage(
    id="detailed_placement",
    full_name="Detailed Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="cts",
    full_name="Clock Tree Synthesis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_CTS",
    optional=True,
).register()

Stage(
    id="post_cts_opt",
    full_name="Post-CTS Timing Optimization",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_CTS_RESIZER_TIMING",
    optional=True,
).register()

Stage(
    id="global_routing",
    full_name="Global Routing",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="post_grt_repair",
    full_name="Post-Global-Routing Design Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GRT_DESIGN_REPAIR",
    optional=True,
).register()

Stage(
    id="antenna_repair",
    full_name="Antenna Violation Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_ANTENNA_REPAIR",
    optional=True,
).register()

Stage(
    id="post_grt_opt",
    full_name="Post-Global-Routing Timing Optimization",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GRT_RESIZER_TIMING",
    optional=True,
).register()

Stage(
    id="detailed_routing",
    full_name="Detailed Routing",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    metrics=("route__drc_errors",),
    gating_config_var="RUN_DRT",
    optional=True,
).register()

Stage(
    id="post_route_opt",
    full_name="Post-Route Optimization",
    default_provider=None,
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    optional=True,
).register()

Stage(
    id="fill_insertion",
    full_name="Fill Cell Insertion",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_FILL_INSERTION",
    optional=True,
).register()

Stage(
    id="extraction",
    full_name="Parasitics Extraction",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=(DesignFormat.spef,),
    gating_config_var="RUN_SPEF_EXTRACTION",
    optional=True,
).register()

Stage(
    id="signoff_sta",
    full_name="Signoff Static Timing Analysis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES + (DesignFormat.spef,),
    provides=_NO_VIEWS,
    metrics=(
        "timing__setup_vio__count",
        "timing__hold_vio__count",
        "design__max_slew_violation__count",
        "design__max_cap_violation__count",
    ),
    gating_config_var="RUN_MCSTA",
    optional=True,
).register()

Stage(
    id="ir_drop",
    full_name="IR Drop Analysis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES + (DesignFormat.spef,),
    provides=_NO_VIEWS,
    gating_config_var="RUN_IRDROP_REPORT",
    optional=True,
).register()

Stage(
    id="streamout",
    full_name="Layout Stream-Out",
    default_provider=("magic", "klayout"),
    requires=PNR_IN_PLACE_REQUIRES,
    provides=(DesignFormat.gds,),
    multi_provider=True,
).register()

Stage(
    id="drc",
    full_name="Design Rule Checking",
    default_provider=("magic", "klayout"),
    requires=(DesignFormat.gds,),
    provides=_NO_VIEWS,
    multi_provider=True,
).register()

Stage(
    id="lvs",
    full_name="Layout Versus Schematic",
    default_provider="netgen",
    requires=(DesignFormat.gds, DesignFormat.nl),
    provides=_NO_VIEWS,
    metrics=("design__lvs_error__count",),
    gating_config_var="RUN_LVS",
    optional=True,
).register()

Stage(
    id="formal_equivalence",
    full_name="Formal Equivalence Checking",
    default_provider="yosys",
    requires=(DesignFormat.nl,),
    provides=_NO_VIEWS,
    gating_config_var="RUN_EQY",
    optional=True,
).register()


#: The canonical flow order of every stage. A ``StagedFlow`` may omit stages
#: and may interleave plain steps, but may not reorder these relative to one
#: another.
STAGE_ORDER: tuple[str, ...] = (
    "lint",
    "synthesis",
    "pre_pnr_sta",
    "floorplan",
    "macro_placement",
    "tapcell_insertion",
    "power_grid",
    "io_placement",
    "global_placement",
    "post_gpl_repair",
    "detailed_placement",
    "cts",
    "post_cts_opt",
    "global_routing",
    "post_grt_repair",
    "antenna_repair",
    "post_grt_opt",
    "detailed_routing",
    "post_route_opt",
    "fill_insertion",
    "extraction",
    "signoff_sta",
    "ir_drop",
    "streamout",
    "drc",
    "lvs",
    "formal_equivalence",
)
```

Note that `Variable` is imported but unused until a canonical variable is added in a later change. Remove the import if the linter objects.

- [ ] **Step 4: Import the taxonomy for its side effects**

In `librelane/stages/__init__.py`, after the registry import, add:

```python
from . import taxonomy as taxonomy  # noqa: F401  (registration side effects)
from .taxonomy import STAGE_ORDER
```

and add `"STAGE_ORDER"` to `__all__`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/stages -v`
Expected: all pass. If `test_gating_variables_are_unique` reports a count other than 15, recount against the `Gate` column of the spec's taxonomy table before changing anything.

- [ ] **Step 6: Commit**

```bash
git add librelane/stages/taxonomy.py librelane/stages/__init__.py test/stages/test_taxonomy.py
git commit -m "feat: define the 27-stage taxonomy"
```

---

### Task 6: Open-source provider registrations

This task writes the sequences that must reproduce `Classic` exactly. The sequences below are not a guess: they are today's `Classic.Steps` partitioned in place, so the concatenation of all stage sequences and the plain steps between them, in `STAGE_ORDER`, is the same 80-entry list Task 1 captured.

**Files:**
- Create: `librelane/stages/providers.py`
- Modify: `librelane/stages/__init__.py`, `librelane/stages/taxonomy.py`
- Test: `test/stages/test_providers.py`

**Interfaces:**
- Consumes: `StageRegistry.register`, every step class in `librelane.steps`.
- Produces: registrations for providers `verilator`, `yosys`, `yosys_vhdl`, `openroad`, `magic`, `klayout`, `netgen`. Task 8 relies on these being exactly right.

**Two ordering findings, discovered while partitioning `Classic`.** Both are corrections to the spec's taxonomy table; record them in the commit message.

1. `Magic.WriteLEF` cannot be inside the `streamout` stage. `Classic` orders stream-out as `Magic.StreamOut`, `KLayout.StreamOut`, `KLayout.Render`, `Magic.WriteLEF`. Since a multi-provider stage concatenates whole per-provider sequences, putting `WriteLEF` in the `magic` sequence would emit it before `KLayout.StreamOut`. `Magic.WriteLEF` writes an abstract LEF, a different deliverable from a GDSII stream, so it becomes a **plain step** after the `streamout` boundary. Its `RUN_MAGIC_WRITE_LEF` gate stays step-level, as the spec already says.

2. The two DRC checkers cannot be inside the `drc` stage, for the same reason: `Classic` runs `Magic.DRC`, `KLayout.DRC`, `Checker.MagicDRC`, `Checker.KLayoutDRC`, both tools before either checker. So the `drc` stage holds only `Magic.DRC` and `KLayout.DRC`, and the two checkers become plain steps after the boundary. The metrics they read move onto the two registrations, which is what `Registration.metrics` exists for. This is the overlap between the stage contract and the checker architecture that the spec flagged as deferred work: here the stage contract guarantees the metric exists and the checker only compares it to a threshold.

**One gating finding.** `OpenROAD.CutRows` is a plain step between `macro_placement` and `tapcell_insertion`, not part of the `tapcell_insertion` sequence, even though the spec's taxonomy table groups them. Row cutting around macros affects placement legality whether or not tap cells are inserted, so folding it into the stage would make `RUN_TAP_ENDCAP_INSERTION: false` silently change placement. It sits exactly on a stage boundary, so keeping it plain costs nothing.

- [ ] **Step 1: Write the provider module**

Create `librelane/stages/providers.py`. Leave `namespaces` as `[]` and `native_views` as `[]` for now; Step 3 fills them from the derivation output.

```python
# Copyright 2026 LibreLane Contributors
"""
Provider registrations for the open-source toolchain.

Every sequence here is a partition of today's ``Classic.Steps``. The golden
equivalence test in ``test/flows/test_staged_equivalence.py`` is what pins
them down; if a sequence is wrong, that test fails.
"""

from ..steps import (
    Checker,
    KLayout,
    Magic,
    Netgen,
    Odb,
    OpenROAD,
    Verilator,
    Yosys,
)

from .registry import StageRegistry

StageRegistry.register(
    stages=["lint"],
    provider="verilator",
    steps=[
        Verilator.Lint,
        Checker.LintTimingConstructs,
        Checker.LintErrors,
        Checker.LintWarnings,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["synthesis"],
    provider="yosys",
    steps=[
        Yosys.JsonHeader,
        Yosys.Synthesis,
        Checker.YosysUnmappedCells,
        Checker.YosysSynthChecks,
        Checker.NetlistAssignStatements,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["synthesis"],
    provider="yosys_vhdl",
    steps=[
        Yosys.VHDLSynthesis,
        Checker.YosysUnmappedCells,
        Checker.YosysSynthChecks,
        Checker.NetlistAssignStatements,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["pre_pnr_sta"],
    provider="openroad",
    steps=[
        OpenROAD.CheckSDCFiles,
        OpenROAD.CheckMacroInstances,
        OpenROAD.STAPrePNR,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["floorplan"],
    provider="openroad",
    steps=[
        OpenROAD.Floorplan,
        OpenROAD.DumpRCValues,
        Odb.CheckMacroAntennaProperties,
        Odb.SetPowerConnections,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["macro_placement"],
    provider="openroad",
    steps=[Odb.ManualMacroPlacement],
    namespaces=[],
)

StageRegistry.register(
    stages=["tapcell_insertion"],
    provider="openroad",
    steps=[OpenROAD.TapEndcapInsertion],
    namespaces=[],
)

StageRegistry.register(
    stages=["power_grid"],
    provider="openroad",
    steps=[
        Odb.AddPDNObstructions,
        OpenROAD.GeneratePDN,
        Odb.RemovePDNObstructions,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["io_placement"],
    provider="openroad",
    steps=[
        OpenROAD.GlobalPlacementSkipIO,
        OpenROAD.IOPlacement,
        Odb.CustomIOPlacement,
        Odb.ApplyDEFTemplate,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["global_placement"],
    provider="openroad",
    steps=[OpenROAD.GlobalPlacement],
    namespaces=[],
)

StageRegistry.register(
    stages=["post_gpl_repair"],
    provider="openroad",
    steps=[OpenROAD.RepairDesignPostGPL],
    namespaces=[],
)

StageRegistry.register(
    stages=["detailed_placement"],
    provider="openroad",
    steps=[OpenROAD.DetailedPlacement],
    namespaces=[],
)

StageRegistry.register(
    stages=["cts"],
    provider="openroad",
    steps=[OpenROAD.CTS],
    namespaces=[],
)

StageRegistry.register(
    stages=["post_cts_opt"],
    provider="openroad",
    steps=[OpenROAD.ResizerTimingPostCTS],
    namespaces=[],
)

StageRegistry.register(
    stages=["global_routing"],
    provider="openroad",
    steps=[OpenROAD.GlobalRouting, OpenROAD.CheckAntennas],
    namespaces=[],
)

StageRegistry.register(
    stages=["post_grt_repair"],
    provider="openroad",
    steps=[OpenROAD.RepairDesignPostGRT],
    namespaces=[],
)

StageRegistry.register(
    stages=["antenna_repair"],
    provider="openroad",
    steps=[
        Odb.DiodesOnPorts,
        Odb.HeuristicDiodeInsertion,
        OpenROAD.RepairAntennas,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["post_grt_opt"],
    provider="openroad",
    steps=[OpenROAD.ResizerTimingPostGRT],
    namespaces=[],
)

StageRegistry.register(
    stages=["detailed_routing"],
    provider="openroad",
    steps=[
        OpenROAD.DetailedRouting,
        Odb.RemoveRoutingObstructions,
        OpenROAD.CheckAntennas,
        Checker.TrDRC,
    ],
    namespaces=[],
)

StageRegistry.register(
    stages=["fill_insertion"],
    provider="openroad",
    steps=[OpenROAD.FillInsertion],
    namespaces=[],
)

StageRegistry.register(
    stages=["extraction"],
    provider="openroad",
    steps=[OpenROAD.RCX],
    namespaces=[],
)

StageRegistry.register(
    stages=["signoff_sta"],
    provider="openroad",
    steps=[OpenROAD.STAPostPNR],
    namespaces=[],
)

StageRegistry.register(
    stages=["ir_drop"],
    provider="openroad",
    steps=[OpenROAD.IRDropReport],
    namespaces=[],
)

StageRegistry.register(
    stages=["streamout"],
    provider="magic",
    steps=[Magic.StreamOut],
    namespaces=[],
)

StageRegistry.register(
    stages=["streamout"],
    provider="klayout",
    steps=[KLayout.StreamOut, KLayout.Render],
    namespaces=[],
)

StageRegistry.register(
    stages=["drc"],
    provider="magic",
    steps=[Magic.DRC],
    namespaces=[],
    metrics=["magic__drc_error__count"],
)

StageRegistry.register(
    stages=["drc"],
    provider="klayout",
    steps=[KLayout.DRC],
    namespaces=[],
    metrics=["klayout__drc_error__count"],
)

StageRegistry.register(
    stages=["lvs"],
    provider="netgen",
    steps=[
        Magic.SpiceExtraction,
        Checker.IllegalOverlap,
        Netgen.LVS,
        Checker.LVS,
    ],
    namespaces=[],
    metrics=["magic__illegal_overlap__count"],
)

StageRegistry.register(
    stages=["formal_equivalence"],
    provider="yosys",
    steps=[Yosys.EQY],
    namespaces=[],
)
```

- [ ] **Step 2: Write the derivation script**

Registration will fail on the first namespace or view violation. Rather than guessing prefixes, print what each sequence actually declares. Create `/tmp/derive_contracts.py` (a scratch file, not committed):

```python
import json

from librelane.config.flow import flow_common_variables
from librelane.stages import Stage
from librelane.stages import providers  # noqa: F401  (may raise; see below)
from librelane.stages.registry import StageRegistry
from librelane.steps.step.composition import compose_step_sequence

common = {v.name for v in flow_common_variables}
report = {}
for registration in StageRegistry.list():
    union = compose_step_sequence(registration.steps)
    stages = [Stage.factory.get(s) for s in registration.stages]
    canonical = {v.name for stage in stages for v in stage.config_vars}
    allowed_in = {v for stage in stages for v in stage.requires}
    report["+".join(registration.stages) + ":" + registration.provider] = {
        "unmet_inputs": [v.id for v in union.unmet_inputs],
        "unmet_inputs_outside_requires": [
            v.id for v in union.unmet_inputs if v not in allowed_in
        ],
        "outputs": [v.id for v in union.outputs],
        "missing_provides": [
            v.id
            for stage in stages
            for v in stage.provides
            if v not in set(union.outputs)
        ],
        "variables": sorted(
            v.name
            for v in union.config_vars
            if v.name not in canonical and v.name not in common
        ),
    }
print(json.dumps(report, indent=2))
```

Because `providers.py` raises on the first violation, run the derivation with the checks temporarily disabled: add an early `return registration` at the top of `StageRegistry.__check_contract` before running the script, and **remove it immediately afterwards**. Note in the commit message that the derivation was run this way.

Run: `uv run python /tmp/derive_contracts.py > /tmp/contracts.json`

- [ ] **Step 3: Fill in `namespaces`, `native_views`, `provides` and correct the taxonomy**

From `/tmp/contracts.json`:

- For each registration, set `namespaces` to the smallest set of prefixes that covers every name in its `variables` list. Group by common prefix; a variable with no shared prefix gets its full name as its own entry, which is legal and honest. The `openroad` registrations are expected to need several legacy prefixes (`FP_`, `PL_`, `GPL_`, `DPL_`, `CTS_`, `GRT_`, `DRT_`, `RSZ_`, `RT_`, `PDN_`, `RCX_`, `STA_`, `IR_`); do not rename any variable.
- For each registration whose `unmet_inputs_outside_requires` is non-empty, decide per view: if it is a tool-native view (`odb`, `mag`, `json_h`), add it to `native_views`. If it is a neutral view the stage genuinely consumes, add it to that **stage's** `requires` in `taxonomy.py` instead. `odb` is the expected case for every `openroad` registration after `floorplan`.
- For each registration with a non-empty `missing_provides`, remove that view from the stage's `provides` in `taxonomy.py`. The contract cannot promise what the reference implementation does not produce. Record every such removal in the commit message, because each one is a boundary guarantee the design assumed and the code does not deliver.
- Add `Registration.provides` entries for tool-native outputs a same-provider successor relies on: `json_h` on the `yosys` synthesis registration (and deliberately **not** on `yosys_vhdl`, which is the whole point of Task 12), `mag_gds` on `magic` streamout, `klayout_gds` on `klayout` streamout.

- [ ] **Step 4: Write the tests**

Create `test/stages/test_providers.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_selectable_stage_has_its_default_provider_registered():
    from librelane.stages import Stage, StageRegistry
    from librelane.stages.taxonomy import STAGE_ORDER

    for stage_id in STAGE_ORDER:
        stage = Stage.factory.get(stage_id)
        for provider in stage.default_providers:
            assert (
                StageRegistry.get(stage_id, provider) is not None
            ), f"{stage_id}: default provider '{provider}' is not registered"


def test_post_route_opt_has_no_provider():
    from librelane.stages import StageRegistry

    assert StageRegistry.providers("post_route_opt") == []


def test_multi_provider_stages_have_two_providers():
    from librelane.stages import StageRegistry

    assert sorted(StageRegistry.providers("streamout")) == ["klayout", "magic"]
    assert sorted(StageRegistry.providers("drc")) == ["klayout", "magic"]


def test_synthesis_has_two_providers():
    from librelane.stages import StageRegistry

    assert sorted(StageRegistry.providers("synthesis")) == ["yosys", "yosys_vhdl"]


def test_yosys_vhdl_does_not_provide_the_json_header():
    """
    Odb.SetPowerConnections and Odb.WriteVerilogHeader both take json_h as a
    hard input (librelane/steps/odb/power.py:49 and :74). Yosys.JsonHeader is a
    VerilogStep and cannot run on VHDL sources. This asymmetry is what Task 12
    turns into a precise error rather than a runtime surprise.
    """
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat

    assert DesignFormat.json_h in StageRegistry.get("synthesis", "yosys").provides
    assert (
        DesignFormat.json_h
        not in StageRegistry.get("synthesis", "yosys_vhdl").provides
    )
```

- [ ] **Step 5: Import providers for their side effects**

In `librelane/stages/__init__.py`, after the taxonomy import:

```python
from . import providers as providers  # noqa: F401  (registration side effects)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest test/stages -v`
Expected: all pass. Any `StageError` at import means a namespace or view value from Step 3 is still wrong; the message names the offending variable or view.

- [ ] **Step 7: Commit**

```bash
git add librelane/stages test/stages
git commit -m "feat: register the open-source provider sequences"
```

---

### Task 7: `resolve()` and `StagedFlow` class-definition-time expansion

**Files:**
- Create: `librelane/stages/resolution.py`, `librelane/flows/staged.py`
- Modify: `librelane/stages/__init__.py`, `librelane/flows/__init__.py`
- Test: `test/stages/test_resolution.py`, `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `Stage`, `StageRegistry`, `Registration`, `StageResolutionError`, `SequentialFlow`.
- Produces:
  - `ResolvedSpan` frozen dataclass: `stage_ids: tuple[str, ...]`, `provider: str`, `provides: tuple[DesignFormat, ...]`, `metrics: tuple[str, ...]`, `gating_config_var: str | None`.
  - `Resolution` frozen dataclass: `steps: list[type[Step]]`, `spans: list[ResolvedSpan]`, `unselected: tuple[str, ...]`.
  - `resolve(entries: Sequence[Stage | type[Step]], tools: Mapping[str, str | Sequence[str]]) -> Resolution`.
  - `StagedFlow` with class attribute `Stages: list[Stage | type[Step]]` and classmethod `stage_boundaries(steps) -> list[Boundary]`.
  - `Boundary` frozen dataclass: `stage_ids: tuple[str, ...]`, `provider: str`, `step_ids: tuple[str, ...]`, `last_step_id: str`.
  - Task 8 sets `Classic.Stages`; Tasks 9 to 14 extend `StagedFlow`.

Spanning registrations are rejected here with an explicit internal error and implemented in Task 14. No spanning registration exists until then, so nothing is left half-working.

- [ ] **Step 1: Write the failing resolution tests**

Create `test/stages/test_resolution.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_defaults_expand_every_stage():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    entries = [Stage.factory.get("global_placement"), Stage.factory.get("cts")]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.CTS",
    ]
    assert [span.provider for span in resolution.spans] == ["openroad", "openroad"]
    assert resolution.unselected == ()


def test_plain_steps_pass_through_untagged():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve
    from librelane.steps import OpenROAD

    entries = [Stage.factory.get("cts"), OpenROAD.STAMidPNR]
    resolution = resolve(entries, {})

    assert [step.id for step in resolution.steps] == [
        "OpenROAD.CTS",
        "OpenROAD.STAMidPNR",
    ]
    assert not hasattr(resolution.steps[1], "_stage_span")
    assert len(resolution.spans) == 1


def test_unselected_optional_stage_contributes_nothing():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve([Stage.factory.get("post_route_opt")], {})

    assert resolution.steps == []
    assert resolution.unselected == ("post_route_opt",)


def test_naming_a_provider_activates_an_unselected_stage():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="post_route_opt"):
        resolve(
            [Stage.factory.get("post_route_opt")],
            {"post_route_opt": "nonexistent_tool"},
        )


def test_tools_override_selects_a_different_provider():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve(
        [Stage.factory.get("synthesis")],
        {"synthesis": "yosys_vhdl"},
    )

    assert [step.id for step in resolution.steps][0] == "Yosys.VHDLSynthesis"


def test_unknown_provider_lists_the_registered_ones():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="yosys_vhdl"):
        resolve([Stage.factory.get("synthesis")], {"synthesis": "genus"})


def test_unknown_stage_key_suggests_a_correction():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="Did you mean: 'synthesis'"):
        resolve([Stage.factory.get("synthesis")], {"synthsis": "yosys"})


def test_list_value_on_single_provider_stage_is_rejected():
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    with pytest.raises(StageResolutionError, match="does not accept a list"):
        resolve([Stage.factory.get("cts")], {"cts": ["openroad", "openroad"]})


def test_multi_provider_stage_concatenates_in_listed_order():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve(
        [Stage.factory.get("streamout")],
        {"streamout": ["klayout", "magic"]},
    )

    assert [step.id for step in resolution.steps] == [
        "KLayout.StreamOut",
        "KLayout.Render",
        "Magic.StreamOut",
    ]


def test_multi_provider_stage_accepts_a_single_provider():
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    resolution = resolve([Stage.factory.get("drc")], {"drc": "klayout"})

    assert [step.id for step in resolution.steps] == ["KLayout.DRC"]
    assert resolution.spans[0].metrics == ("klayout__drc_error__count",)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/stages/test_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'librelane.stages.resolution'`

- [ ] **Step 3: Write `resolution.py`**

Create `librelane/stages/resolution.py`:

```python
# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from typing import Union
from collections.abc import Mapping, Sequence

from rapidfuzz import fuzz, process, utils

from ..state import DesignFormat
from ..steps import Step

from .registry import Registration, StageRegistry
from .stage import Stage, StageResolutionError

#: An entry in a flow's ``Stages`` list: either a stage to be expanded, or a
#: plain step that sits at a stage boundary.
StageEntry = Union[Stage, type[Step]]

#: A ``TOOLS`` value: one provider, or several for a multi-provider stage.
ToolSelection = Union[str, Sequence[str]]


@dataclass(frozen=True)
class ResolvedSpan:
    """
    One stage, or one contiguous span of stages, bound to the provider chosen
    for it and to the contract that must hold when it completes.
    """

    stage_ids: tuple[str, ...]
    provider: str
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]
    gating_config_var: str | None


@dataclass(frozen=True)
class Resolution:
    steps: list[type[Step]]
    spans: list[ResolvedSpan]
    unselected: tuple[str, ...]


def _selection_for(
    stage: Stage,
    tools: Mapping[str, ToolSelection],
) -> tuple[str, ...] | None:
    """
    :returns: The provider names chosen for this stage, or ``None`` if the
        stage is unselected.
    """
    if stage.id not in tools:
        return stage.default_providers or None

    value = tools[stage.id]
    if isinstance(value, str):
        return (value,)
    if not stage.multi_provider:
        raise StageResolutionError(
            f"stage '{stage.id}' does not accept a list of providers: it runs "
            f"exactly one tool. Got {list(value)}."
        )
    if len(value) == 0:
        raise StageResolutionError(
            f"stage '{stage.id}': TOOLS names an empty provider list. To skip "
            f"a stage, use its gating variable; there is no way to select "
            f"nothing."
        )
    return tuple(value)


def _registration_for(stage: Stage, provider: str) -> Registration:
    registration = StageRegistry.get(stage.id, provider)
    if registration is None:
        available = StageRegistry.providers(stage.id)
        if available:
            detail = f"Registered providers for this stage: {sorted(available)}."
        else:
            detail = "No provider is registered for this stage."
        raise StageResolutionError(
            f"stage '{stage.id}': no provider named '{provider}' is "
            f"registered. {detail}"
        )
    if registration.spanning:
        raise StageResolutionError(
            f"stage '{stage.id}': provider '{provider}' is a spanning "
            f"registration covering {list(registration.stages)}, which is not "
            f"yet supported."
        )
    return registration


def _check_tool_keys(
    tools: Mapping[str, ToolSelection],
    known: Sequence[str],
) -> None:
    for key in tools:
        if key in known:
            continue
        suggestion = ""
        match = process.extractOne(
            key,
            list(known),
            scorer=fuzz.partial_ratio,
            score_cutoff=80,
            processor=utils.default_process,
        )
        if match is not None:
            suggestion = f" Did you mean: '{match[0]}'?"
        raise StageResolutionError(
            f"TOOLS names '{key}', which is not a stage in this flow.{suggestion}"
        )


def resolve(
    entries: Sequence[StageEntry],
    tools: Mapping[str, ToolSelection],
) -> Resolution:
    """
    Expands a flow's ``Stages`` list into a flat list of concrete step classes,
    choosing a provider per stage from ``tools`` and falling back to each
    stage's ``default_provider`` where ``tools`` is silent.

    :param entries: The flow's ``Stages`` list: ``Stage`` objects interleaved
        with plain ``Step`` classes.
    :param tools: The resolved ``TOOLS`` mapping.
    :raises StageResolutionError: On any unknown stage key, unknown provider,
        or misuse of a list value.
    """
    stage_ids = [entry.id for entry in entries if isinstance(entry, Stage)]
    _check_tool_keys(tools, stage_ids)

    steps: list[type[Step]] = []
    spans: list[ResolvedSpan] = []
    unselected: list[str] = []

    for entry in entries:
        if not isinstance(entry, Stage):
            steps.append(entry)
            continue

        providers = _selection_for(entry, tools)
        if providers is None:
            unselected.append(entry.id)
            continue

        span_steps: list[type[Step]] = []
        provides = set(entry.provides)
        metrics = set(entry.metrics)
        for provider in providers:
            registration = _registration_for(entry, provider)
            span_steps.extend(registration.tagged_steps())
            provides.update(registration.provides)
            metrics.update(registration.metrics)

        steps.extend(span_steps)
        spans.append(
            ResolvedSpan(
                stage_ids=(entry.id,),
                provider="+".join(providers),
                provides=tuple(sorted(provides, key=lambda view: view.id)),
                metrics=tuple(sorted(metrics)),
                gating_config_var=entry.gating_config_var,
            )
        )

    return Resolution(steps, spans, tuple(unselected))
```

The `provider` field of a multi-provider span joins the names with `+`, so a log line reads `stage 'streamout': magic+klayout`. `tagged_steps()` tags with `registration.stages`, so both `magic` and `klayout` steps carry the same `_stage_span` of `("streamout",)` and form one boundary. Their `_stage_provider` values differ, so the boundary scanner in Step 5 must group on `_stage_span` alone.

- [ ] **Step 4: Run the resolution tests to verify they pass**

Run: `uv run pytest test/stages/test_resolution.py -v`
Expected: 10 passed.

- [ ] **Step 5: Write `StagedFlow`**

Create `librelane/flows/staged.py`:

```python
# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass

from loguru import logger

from ..stages.resolution import Resolution, StageEntry, resolve
from ..stages.stage import Stage
from ..steps import Step

from .sequential import SequentialFlow


@dataclass(frozen=True)
class Boundary:
    """
    A contiguous run of resolved steps belonging to one stage or span, and the
    contract that must hold once its last step completes.
    """

    stage_ids: tuple[str, ...]
    step_ids: tuple[str, ...]
    provides: tuple
    metrics: tuple[str, ...]

    @property
    def last_step_id(self) -> str:
        return self.step_ids[-1]


class StagedFlow(SequentialFlow):
    """
    A :class:`SequentialFlow` whose step list is expanded from a list of
    :class:`librelane.stages.Stage` objects, so the tool used for each phase
    can be chosen from configuration rather than by subclassing the flow.

    :cvar Stages: The flow in stage terms. Entries are either ``Stage``
        objects, which expand to whichever provider is selected, or plain
        ``Step`` classes, which are provider-neutral utilities and boundary
        observations. A plain step entry is only meaningful at a stage
        boundary.

    ``Steps`` is expanded from ``Stages`` at class-definition time using each
    stage's ``default_provider``, so it is a fully populated list at import and
    every existing ``SequentialFlow`` facility keeps working unchanged:
    ``Substitute``, ``get_help_md``, step IDs and step directory names.
    """

    Stages: list[StageEntry] = []

    def __init_subclass__(Self, scm_type=None, name=None, **kwargs):
        if "Stages" in Self.__dict__:
            Self.Stages = list(Self.Stages)
            resolution = resolve(Self.Stages, {})
            Self.Steps = resolution.steps
            Self.__report_unselected(resolution)
        super().__init_subclass__(scm_type=scm_type, name=name, **kwargs)

    @staticmethod
    def __report_unselected(resolution: Resolution) -> None:
        for stage_id in resolution.unselected:
            logger.debug(f"stage '{stage_id}': no provider selected, skipped")

    @classmethod
    def stage_boundaries(Self, steps: list[type[Step]]) -> list[Boundary]:
        """
        Recovers the stage boundary map from a final step list by scanning for
        contiguous runs of steps carrying the same ``_stage_span`` tag.

        Reading the tags off the classes rather than remembering index ranges
        is what makes this survive duplicate-ID normalization and
        ``Substitutions``: ``Step.with_id`` subclasses, so the tag is
        inherited, while a substituted-in step carries no tag and correctly
        falls outside every boundary.
        """
        boundaries: list[Boundary] = []
        current_span: tuple[str, ...] | None = None
        current_ids: list[str] = []

        def flush():
            if current_span is None:
                return
            provides: set = set()
            metrics: set = set()
            for stage_id in current_span:
                stage = Stage.factory.get(stage_id)
                provides.update(stage.provides)
                metrics.update(stage.metrics)
            boundaries.append(
                Boundary(
                    stage_ids=current_span,
                    step_ids=tuple(current_ids),
                    provides=tuple(sorted(provides, key=lambda v: v.id)),
                    metrics=tuple(sorted(metrics)),
                )
            )

        for step in steps:
            span = getattr(step, "_stage_span", None)
            if span != current_span:
                flush()
                current_span = span
                current_ids = []
            if span is not None:
                current_ids.append(step.id)
        flush()

        return [boundary for boundary in boundaries if boundary.stage_ids]
```

`Boundary.provides` and `.metrics` are recomputed from the taxonomy rather than carried from `Resolution`, because substitution may have changed which steps are present. Task 11 replaces this with the union that includes `Registration.provides` and `Registration.metrics`, threaded through from the resolution.

- [ ] **Step 6: Write the `StagedFlow` tests**

Create `test/flows/test_staged.py`:

```python
# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


@pytest.fixture
def SmallStaged():
    from librelane.flows import StagedFlow
    from librelane.stages import Stage
    from librelane.steps import OpenROAD

    class SmallStaged(StagedFlow):
        Stages = [
            Stage.factory.get("global_placement"),
            OpenROAD.STAMidPNR,
            Stage.factory.get("detailed_placement"),
            Stage.factory.get("cts"),
        ]

    return SmallStaged


def test_steps_are_populated_at_class_definition(SmallStaged):
    assert [step.id for step in SmallStaged.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.STAMidPNR",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_boundaries_exclude_plain_steps(SmallStaged):
    boundaries = SmallStaged.stage_boundaries(SmallStaged.Steps)

    assert [b.stage_ids for b in boundaries] == [
        ("global_placement",),
        ("detailed_placement",),
        ("cts",),
    ]
    assert [b.last_step_id for b in boundaries] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_substitute_still_works(SmallStaged):
    Substituted = SmallStaged.Substitute({"OpenROAD.CTS": None})

    assert "OpenROAD.CTS" not in [step.id for step in Substituted.Steps]
    assert [b.stage_ids for b in Substituted.stage_boundaries(Substituted.Steps)] == [
        ("global_placement",),
        ("detailed_placement",),
    ]


def test_duplicate_normalization_preserves_tags():
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Doubled(StagedFlow):
        Stages = [
            Stage.factory.get("global_placement"),
            Stage.factory.get("global_placement"),
        ]

    assert [step.id for step in Doubled.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    ]
    boundaries = Doubled.stage_boundaries(Doubled.Steps)
    assert len(boundaries) == 1
    assert boundaries[0].step_ids == (
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    )
```

The last test documents a real consequence: listing the same stage twice produces one boundary, not two, because the tags are indistinguishable. That is correct for a flow that genuinely repeats a phase, and `Classic` does not repeat any stage.

- [ ] **Step 7: Export and run**

In `librelane/flows/__init__.py`, add `from .staged import StagedFlow` next to the existing `SequentialFlow` export, and add `"StagedFlow"` to `__all__` if that module defines one.

Run: `uv run pytest test/flows/test_staged.py test/stages -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add librelane/stages/resolution.py librelane/flows/staged.py librelane/flows/__init__.py librelane/stages/__init__.py test/stages/test_resolution.py test/flows/test_staged.py
git commit -m "feat: add stage resolution and StagedFlow class-time expansion"
```

---

### Task 8: Convert `Classic` to a `StagedFlow`

The load-bearing task. `Classic` is converted in place rather than forked, so there is one flow to maintain. The Task 1 goldens are the acceptance criterion and must not be edited.

**Files:**
- Modify: `librelane/flows/classic.py:31-121` (the `Steps` list becomes `Stages`)
- Test: `test/flows/test_staged_equivalence.py` (unchanged, must still pass)

**Interfaces:**
- Consumes: `StagedFlow`, `Stage.factory`, every provider registration from Task 6.
- Produces: `Classic.Stages`. Tasks 9 and 12 modify `Classic.gating_config_vars` and `Classic.Config`; nothing else consumes this.

`gating_config_vars` is left exactly as it is in this task. Migrating it to stage gating is Task 9, and keeping the two changes apart means a failure of `test_classic_gating_matches_golden` unambiguously identifies which one caused it.

- [ ] **Step 1: Rewrite the class header and step list**

In `librelane/flows/classic.py`, change the import of `SequentialFlow` to `StagedFlow`:

```python
from .flow import Flow
from .staged import StagedFlow
from ..config import variable
from ..stages import Stage
from ..steps import (
    Yosys,
    OpenROAD,
    Magic,
    KLayout,
    Odb,
    Netgen,
    Checker,
    Verilator,
    Misc,
)


def _stage(id: str) -> Stage:
    stage = Stage.factory.get(id)
    assert stage is not None, f"Unregistered stage '{id}' named by Classic"
    return stage
```

Replace `class Classic(SequentialFlow)` with `class Classic(StagedFlow)`, replace the `Steps = [...]` list (lines 40 to 121) with the following, and change `class Config(SequentialFlow.Config)` to `class Config(StagedFlow.Config)`:

```python
    Stages = [
        _stage("lint"),
        _stage("synthesis"),
        _stage("pre_pnr_sta"),
        _stage("floorplan"),
        _stage("macro_placement"),
        OpenROAD.CutRows,
        _stage("tapcell_insertion"),
        _stage("power_grid"),
        Odb.AddRoutingObstructions,
        _stage("io_placement"),
        _stage("global_placement"),
        Odb.WriteVerilogHeader,
        Checker.PowerGridViolations,
        OpenROAD.STAMidPNR,
        _stage("post_gpl_repair"),
        Odb.ManualGlobalPlacement,
        _stage("detailed_placement"),
        _stage("cts"),
        OpenROAD.STAMidPNR,
        _stage("post_cts_opt"),
        OpenROAD.STAMidPNR,
        _stage("global_routing"),
        _stage("post_grt_repair"),
        _stage("antenna_repair"),
        _stage("post_grt_opt"),
        OpenROAD.STAMidPNR,
        _stage("detailed_routing"),
        Odb.ReportDisconnectedPins,
        Checker.DisconnectedPins,
        Odb.ReportWireLength,
        Checker.WireLength,
        _stage("post_route_opt"),
        _stage("fill_insertion"),
        Odb.CellFrequencyTables,
        _stage("extraction"),
        _stage("signoff_sta"),
        _stage("ir_drop"),
        _stage("streamout"),
        Magic.WriteLEF,
        Odb.CheckDesignAntennaProperties,
        KLayout.XOR,
        Checker.XOR,
        _stage("drc"),
        Checker.MagicDRC,
        Checker.KLayoutDRC,
        _stage("lvs"),
        _stage("formal_equivalence"),
        Checker.SetupViolations,
        Checker.HoldViolations,
        Checker.MaxSlewViolations,
        Checker.MaxCapViolations,
        Misc.ReportManufacturability,
    ]
```

Twenty-seven stages, all of them, with `post_route_opt` unselected. Note where the plain steps sit: `Odb.AddRoutingObstructions` between `power_grid` and `io_placement`, the five `OpenROAD.STAMidPNR` observations, `Magic.WriteLEF` and the two DRC checkers after their stages, and the four final timing checkers.

- [ ] **Step 2: Run the equivalence test**

Run: `uv run pytest test/flows/test_staged_equivalence.py -v`
Expected: 3 passed.

**If `test_classic_steps_match_golden` fails, read the diff carefully.** pytest prints the two lists. The failure is almost certainly one of:

- A step in the wrong stage sequence, showing as two adjacent entries swapped.
- A step assigned to a stage that should be a plain entry, or vice versa, showing as a step moving across a boundary.
- A duplicate-ID suffix differing, meaning the number of instances of a step changed. `OpenROAD.STAMidPNR` should appear five times and `OpenROAD.CheckAntennas` twice.

Fix `librelane/stages/providers.py` or the `Stages` list. **Do not regenerate the golden file.**

- [ ] **Step 3: Verify `VHDLClassic` still works**

`VHDLClassic` is unchanged in this task: it is still a subclass with a `Substitutions` map, and because `Classic.Steps` is populated at class-definition time, every one of its substitution keys still matches.

Run: `uv run pytest test/flows/test_staged_equivalence.py::test_vhdl_classic_steps_match_golden -v`
Expected: PASS.

- [ ] **Step 4: Run the whole test suite**

Run: `uv run pytest test -q -x`
Expected: no new failures. Pay attention to `test/cli/test_steps.py` and any test that enumerates flow steps.

- [ ] **Step 5: Verify the help output is unchanged**

```bash
uv run librelane --flow Classic --help > /tmp/classic_help_after.txt
git stash && uv run librelane --flow Classic --help > /tmp/classic_help_before.txt && git stash pop
diff /tmp/classic_help_before.txt /tmp/classic_help_after.txt
```

Expected: no differences. `Flow.get_help_md` (`librelane/flows/flow.py:547-552`) iterates `Self.Steps` as a classmethod, which class-definition-time expansion keeps populated.

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/classic.py
git commit -m "feat: convert Classic to a StagedFlow

Classic.Steps is now expanded from a 27-entry Stages list at class
definition time. The golden equivalence test proves the expansion
reproduces the previous 80-step list exactly."
```

---

### Task 9: Stage-level gating

`Classic.gating_config_vars` maps OpenROAD-specific step IDs to Boolean variables. Keys matching no step are skipped without complaint, at class definition (`librelane/flows/sequential.py:130-133`) and at run time (`librelane/flows/sequential.py:340-347`). Under a non-default provider that fails silently: `RUN_CTS: false` with `"cts": "innovus"` would leave Innovus running, because no step named `OpenROAD.CTS` exists to gate.

**Files:**
- Modify: `librelane/flows/staged.py`, `librelane/flows/sequential.py:130-133` and `:340-347`, `librelane/flows/classic.py`
- Test: `test/flows/test_staged.py`, `test/flows/test_staged_equivalence.py`

**Interfaces:**
- Consumes: `Boundary`, `Stage.gating_config_var`.
- Produces: `StagedFlow` populates `gating_config_vars` from stage gates during expansion, reusing the existing step-level gating machinery unchanged. Nothing new is exported.

**Three deliberate behaviour changes.** Gating a stage skips every step in it, and three stages contain steps that today's step-level keys do not reach. Each is an improvement, and each must be recorded in `Changelog.md` and asserted by a test.

| Variable | Additionally skipped now | Why this is correct |
| --- | --- | --- |
| `RUN_DRT` | `Odb.RemoveRoutingObstructions`, `OpenROAD.CheckAntennas-1` | Obstructions exist to shape detailed routing. With routing off they have no consumer, and the DEF that retains them was never routed and is not a signoff artifact. Checking antennas on an unrouted design reports nothing meaningful. |
| `RUN_ANTENNA_REPAIR` | `Odb.DiodesOnPorts`, `Odb.HeuristicDiodeInsertion` | Today, setting this false still inserts diodes and merely skips the repair pass, which places cells for a repair that never happens. |
| `RUN_LVS` | `Magic.SpiceExtraction`, `Checker.IllegalOverlap` | The extraction exists to feed LVS. Today, disabling LVS still pays for the extraction and still fails the run on an illegal overlap found by a check nobody asked for. |

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_staged_equivalence.py`:

```python
#: Gating variables whose reach changed when gating moved to the stage level.
#: Each entry is the full set of step IDs skipped after the change. See the
#: implementation plan for why each is correct.
WIDENED_GATES = {
    "RUN_DRT": [
        "Checker.TrDRC",
        "Odb.RemoveRoutingObstructions",
        "OpenROAD.CheckAntennas-1",
        "OpenROAD.DetailedRouting",
    ],
    "RUN_ANTENNA_REPAIR": [
        "Odb.DiodesOnPorts",
        "Odb.HeuristicDiodeInsertion",
        "OpenROAD.RepairAntennas",
    ],
    "RUN_LVS": [
        "Checker.IllegalOverlap",
        "Checker.LVS",
        "Magic.SpiceExtraction",
        "Netgen.LVS",
    ],
}


def test_unchanged_gates_still_match_golden():
    Classic = Flow.factory.get("Classic")
    golden = _load_golden("classic_gating.json")
    for variable in GATING_VARIABLES:
        if variable in WIDENED_GATES:
            continue
        assert _gated_step_ids(Classic, variable) == golden[variable], variable


def test_widened_gates_have_their_documented_reach():
    Classic = Flow.factory.get("Classic")
    for variable, expected in WIDENED_GATES.items():
        assert _gated_step_ids(Classic, variable) == expected, variable
```

Delete `test_classic_gating_matches_golden`, which the two tests above replace: it now asserts something known to be false for three of the 22 variables. Keep `classic_gating.json`, which the first test still reads.

Append to `test/flows/test_staged.py`:

```python
def test_stage_gate_applies_to_every_step_of_the_stage():
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Gated(StagedFlow):
        Stages = [Stage.factory.get("antenna_repair")]

        class Config(StagedFlow.Config):
            RUN_ANTENNA_REPAIR: bool = __import__(
                "librelane.config", fromlist=["variable"]
            ).variable(True, description="test gate")

    assert Gated.gating_config_vars == {
        "Odb.DiodesOnPorts": ["RUN_ANTENNA_REPAIR"],
        "Odb.HeuristicDiodeInsertion": ["RUN_ANTENNA_REPAIR"],
        "OpenROAD.RepairAntennas": ["RUN_ANTENNA_REPAIR"],
    }


def test_gating_key_matching_no_step_is_rejected():
    from librelane.flows import SequentialFlow
    from librelane.steps import OpenROAD

    with pytest.raises(TypeError, match="matches no step"):

        class Bad(SequentialFlow):
            Steps = [OpenROAD.CTS]
            gating_config_vars = {"OpenROAD.NotAStep": ["RUN_CTS"]}

            class Config(SequentialFlow.Config):
                RUN_CTS: bool = __import__(
                    "librelane.config", fromlist=["variable"]
                ).variable(True, description="test gate")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_staged.py test/flows/test_staged_equivalence.py -v`
Expected: `test_widened_gates_have_their_documented_reach`, `test_stage_gate_applies_to_every_step_of_the_stage` and `test_gating_key_matching_no_step_is_rejected` fail.

- [ ] **Step 3: Generate stage gating in `StagedFlow`**

In `librelane/flows/staged.py`, add a method and call it from `__init_subclass__` after `Self.Steps` is assigned but before `super().__init_subclass__()`, so the validation in `SequentialFlow.__init_subclass__` sees the generated entries:

```python
    @classmethod
    def _apply_stage_gating(Self) -> None:
        """
        Turns each stage's ``gating_config_var`` into step-level gating entries
        covering every step the resolved provider produced.

        Reusing the existing step-level mechanism rather than adding a parallel
        one means gating behaves identically whichever provider is selected,
        which is the whole point: ``RUN_CTS`` gates the ``cts`` stage no matter
        what implements it.
        """
        generated: dict[str, list[str]] = {}
        for boundary in Self.stage_boundaries(Self.Steps):
            for stage_id in boundary.stage_ids:
                stage = Stage.factory.get(stage_id)
                if stage.gating_config_var is None:
                    continue
                for step_id in boundary.step_ids:
                    generated.setdefault(step_id, []).append(
                        stage.gating_config_var
                    )
        merged = dict(generated)
        for key, value in Self.gating_config_vars.items():
            merged.setdefault(key, [])
            merged[key] = list(dict.fromkeys(merged[key] + list(value)))
        Self.gating_config_vars = merged
```

`dict.fromkeys` deduplicates while preserving order, so a variable that is both a stage gate and a leftover explicit entry appears once.

- [ ] **Step 4: Make unmatched gating keys an error**

In `librelane/flows/sequential.py`, replace lines 130 to 133:

```python
        for id, variable_names in Self.gating_config_vars.items():
            matching_steps = list(Filter([id]).filter(step_id_set))
            if id not in step_id_set and len(matching_steps) < 1:
                continue
```

with:

```python
        for id, variable_names in Self.gating_config_vars.items():
            matching_steps = list(Filter([id]).filter(step_id_set))
            if id not in step_id_set and len(matching_steps) < 1:
                raise TypeError(
                    f"Gating key '{id}' in Flow '{Self.__qualname__}' matches "
                    f"no step in the flow. A gating key that matches nothing "
                    f"silently fails to gate anything."
                )
```

and in `run` (lines 340 to 347), after the expansion loop, add:

```python
        for key in self.gating_config_vars:
            if key not in gating_cvars_expanded:
                raise FlowException(
                    f"Gating key '{key}' matches no step in this run. A gating "
                    f"key that matches nothing silently fails to gate anything."
                )
```

- [ ] **Step 5: Migrate `Classic.gating_config_vars`**

In `librelane/flows/classic.py`, delete these 15 entries, which are now generated from stage gates:

`OpenROAD.RepairDesignPostGPL`, `OpenROAD.RepairDesignPostGRT`, `OpenROAD.ResizerTimingPostCTS`, `OpenROAD.ResizerTimingPostGRT`, `OpenROAD.CTS`, `OpenROAD.RCX`, `OpenROAD.TapEndcapInsertion`, `OpenROAD.RepairAntennas`, `OpenROAD.DetailedRouting`, `OpenROAD.FillInsertion`, `OpenROAD.STAPostPNR`, `OpenROAD.IRDropReport`, `Netgen.LVS`, `Checker.TrDRC`, `Checker.LVS`, and the four `Verilator.Lint` / `Checker.Lint*` entries, and `Yosys.EQY`.

Keep exactly these, which gate one tool inside a stage or a plain step:

```python
    gating_config_vars = {
        "Odb.HeuristicDiodeInsertion": ["RUN_HEURISTIC_DIODE_INSERTION"],
        "Magic.StreamOut": ["RUN_MAGIC_STREAMOUT"],
        "KLayout.StreamOut": ["RUN_KLAYOUT_STREAMOUT"],
        "Magic.WriteLEF": ["RUN_MAGIC_WRITE_LEF"],
        "Magic.DRC": ["RUN_MAGIC_DRC"],
        "KLayout.DRC": ["RUN_KLAYOUT_DRC"],
        "Checker.MagicDRC": ["RUN_MAGIC_DRC"],
        "Checker.KLayoutDRC": ["RUN_KLAYOUT_DRC"],
        "KLayout.XOR": [
            "RUN_KLAYOUT_XOR",
            "RUN_MAGIC_STREAMOUT",
            "RUN_KLAYOUT_STREAMOUT",
        ],
        "Checker.XOR": [
            "RUN_KLAYOUT_XOR",
            "RUN_MAGIC_STREAMOUT",
            "RUN_KLAYOUT_STREAMOUT",
        ],
    }
```

Seven distinct variables, matching the spec's split of 15 migrated and 7 retained.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest test/flows -v`
Expected: all pass. `test_unchanged_gates_still_match_golden` proves the other 19 variables are untouched.

- [ ] **Step 7: Record the behaviour changes**

Add to `Changelog.md`, under the unreleased section, one bullet per row of the table above, each naming the variable and the newly skipped steps.

- [ ] **Step 8: Commit**

```bash
git add librelane/flows test/flows Changelog.md
git commit -m "feat: move flow gating from step IDs to stage IDs

RUN_CTS now gates the cts stage regardless of which tool implements it.
Gating keys that match no step are rejected rather than ignored, which
is what made the previous behaviour fail silently under a non-default
provider."
```

---

### Task 10: The `TOOLS` pre-pass and instance-time re-expansion

`Flow.__init__` (`librelane/flows/flow.py:466-487`) reads `self.Steps` to build `get_all_config_variables()` before it calls `Config.load`. The step set must therefore be known before configuration is validated, which is circular because configuration is what selects the steps. This is resolved with a narrow pre-pass over the raw, unvalidated configuration, mirroring the two-phase read that already extracts `PDK` and `DESIGN_NAME` ahead of full validation (`librelane/config/config.py:668-674`).

**Files:**
- Create: `librelane/config/loading/tools.py`
- Modify: `librelane/config/loading/__init__.py`, `librelane/flows/staged.py`, `librelane/flows/sequential.py`
- Test: `test/config/test_tools_extraction.py`, `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `read_source`, `layer_mappings`, `ConfigSource`.
- Produces:
  - `extract_tools(config_in, *, config_override_strings=None, yaml_loader) -> dict[str, str | list[str]]`
  - `StagedFlow.Config.TOOLS`, an optional mapping variable.
  - `SequentialFlow._normalize_step_ids(target)`, a protected alias for the existing name-mangled static method.
  - Tasks 11 to 14 all run after this resolution.

`TOOLS` must be a literal mapping. `expr::`, `ref::` and every other preprocessor construct is rejected inside it, and its values may not be derived from the PDK. This keeps the pre-pass from re-entering the preprocessor before configuration is resolved, and it is why "`TOOLS` cannot be supplied by the PDK" is a stated limitation rather than an oversight.

- [ ] **Step 1: Write the failing extraction tests**

Create `test/config/test_tools_extraction.py`:

```python
# Copyright 2026 LibreLane Contributors
import json

import pytest

pytestmark = pytest.mark.all


def _extract(*sources, overrides=None):
    import yaml

    from librelane.config.loading.tools import extract_tools

    return extract_tools(
        list(sources),
        config_override_strings=overrides,
        yaml_loader=yaml.SafeLoader,
    )


def test_absent_tools_yields_an_empty_mapping():
    assert _extract({"DESIGN_NAME": "a"}) == {}


def test_mapping_source_is_read():
    assert _extract({"TOOLS": {"synthesis": "genus"}}) == {"synthesis": "genus"}


def test_later_sources_win():
    result = _extract(
        {"TOOLS": {"synthesis": "yosys"}},
        {"TOOLS": {"synthesis": "genus"}},
    )
    assert result == {"synthesis": "genus"}


def test_override_strings_win_over_every_source():
    result = _extract(
        {"TOOLS": {"synthesis": "yosys"}},
        overrides=[f'TOOLS={json.dumps({"synthesis": "genus"})}'],
    )
    assert result == {"synthesis": "genus"}


def test_list_values_are_preserved():
    assert _extract({"TOOLS": {"streamout": ["magic", "klayout"]}}) == {
        "streamout": ["magic", "klayout"]
    }


def test_non_mapping_tools_is_rejected():
    from librelane.stages import StageResolutionError

    with pytest.raises(StageResolutionError, match="must be a mapping"):
        _extract({"TOOLS": "genus"})


def test_preprocessor_constructs_are_rejected():
    from librelane.stages import StageResolutionError

    with pytest.raises(StageResolutionError, match="must be a literal"):
        _extract({"TOOLS": {"synthesis": "ref::$SYNTH_TOOL"}})


def test_non_string_provider_is_rejected():
    from librelane.stages import StageResolutionError

    with pytest.raises(StageResolutionError, match="must be a string"):
        _extract({"TOOLS": {"synthesis": 3}})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/config/test_tools_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the extractor**

Create `librelane/config/loading/tools.py`:

```python
# Copyright 2026 LibreLane Contributors
import json
import os
from typing import Any
from collections.abc import Mapping, Sequence

from loguru import logger

from ...stages.stage import StageResolutionError

from .layering import layer_mappings
from .sources import ConfigSource, read_source

TOOLS_KEY = "TOOLS"

#: Prefixes the configuration preprocessor treats specially. None of them may
#: appear inside TOOLS, because the pre-pass runs before the preprocessor.
_PREPROCESSOR_PREFIXES = ("ref::", "expr::", "refg::", "dir::")


def _reject_construct(stage: str, value: str) -> None:
    for prefix in _PREPROCESSOR_PREFIXES:
        if value.startswith(prefix):
            raise StageResolutionError(
                f"TOOLS['{stage}'] is '{value}'. TOOLS must be a literal "
                f"mapping: tool selection is read before the configuration "
                f"preprocessor runs, so '{prefix}' and other constructs "
                f"cannot be evaluated there."
            )


def _validate(raw: Any) -> dict[str, str | list[str]]:
    if not isinstance(raw, Mapping):
        raise StageResolutionError(
            f"TOOLS must be a mapping from stage id to provider name, got "
            f"{type(raw).__name__}."
        )
    result: dict[str, str | list[str]] = {}
    for stage, value in raw.items():
        if isinstance(value, str):
            _reject_construct(str(stage), value)
            result[str(stage)] = value
            continue
        if isinstance(value, Sequence):
            providers = []
            for element in value:
                if not isinstance(element, str):
                    raise StageResolutionError(
                        f"TOOLS['{stage}'] contains "
                        f"{type(element).__name__}; every provider name must "
                        f"be a string."
                    )
                _reject_construct(str(stage), element)
                providers.append(element)
            result[str(stage)] = providers
            continue
        raise StageResolutionError(
            f"TOOLS['{stage}'] is {type(value).__name__}; a provider "
            f"selection must be a string, or a list of strings for a "
            f"multi-provider stage."
        )
    return result


def extract_tools(
    config_in: Sequence[Mapping[str, Any] | str | os.PathLike],
    *,
    config_override_strings: Sequence[str] | None = None,
    yaml_loader,
) -> dict[str, str | list[str]]:
    """
    Reads only the ``TOOLS`` key out of a set of layered configuration
    sources, without preprocessing or validating anything else.

    Layering follows the same precedence as :meth:`librelane.config.Config.load`:
    later sources win, and command line overrides win over every source.

    Tcl configuration files are not evaluated here, because evaluating one
    requires process information that is not yet resolved. A ``.tcl`` source
    therefore contributes no ``TOOLS`` entries, and this is reported so it is
    never mistaken for the file having been read and found empty.

    :param config_in: The same sequence ``Config.load`` receives.
    :param config_override_strings: ``NAME=VALUE`` strings from the command
        line. A ``TOOLS=`` override must be a JSON object.
    :raises StageResolutionError: If ``TOOLS`` is present but malformed.
    """
    sources: list[ConfigSource] = []
    for entry in config_in:
        if isinstance(entry, Mapping):
            sources.append(ConfigSource(entry, "<mapping>", "mapping"))
            continue
        source = read_source(entry, yaml_loader=yaml_loader)
        if source.kind == "tcl":
            logger.info(
                f"TOOLS is not read from Tcl configuration files; "
                f"'{os.path.relpath(source.name)}' was not consulted for tool "
                f"selection and stage defaults apply."
            )
        sources.append(source)

    merged = layer_mappings(sources).mapping
    raw = merged.get(TOOLS_KEY)

    for string in config_override_strings or []:
        key, value = string.split("=", 1)
        if key != TOOLS_KEY:
            continue
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as error:
            raise StageResolutionError(
                f"TOOLS override on the command line is not valid JSON: "
                f"{error}"
            ) from None

    if raw is None:
        return {}
    return _validate(raw)
```

Export it from `librelane/config/loading/__init__.py`.

- [ ] **Step 4: Run the extraction tests to verify they pass**

Run: `uv run pytest test/config/test_tools_extraction.py -v`
Expected: 8 passed.

- [ ] **Step 5: Add the protected normalization alias**

In `librelane/flows/sequential.py`, immediately after the definition of `__normalize_step_ids` (line 250 onward), add:

```python
    @staticmethod
    def _normalize_step_ids(target):
        """
        Protected alias for subclasses that rebuild ``Steps`` after class
        definition. ``StagedFlow`` needs this when instance-level ``TOOLS``
        selects a non-default provider.
        """
        SequentialFlow._SequentialFlow__normalize_step_ids(target)
```

If the name mangling makes that unreadable, instead rename `__normalize_step_ids` to `_normalize_step_ids` throughout `sequential.py` (four call sites: lines 116, 248, and the two in `__substitute_step`). Prefer the rename; it is clearer and the method was never public.

- [ ] **Step 6: Write the failing `StagedFlow` instance tests**

Append to `test/flows/test_staged.py`:

```python
from librelane.flows import flow as flow_module, sequential as sequential_flow_module
from librelane.steps import step as step_module

mock_variables = pytest.mock_variables


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_tools_reexpands_at_instance_time():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = Classic(
        {
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": ["/cwd/src/a.v"],
            "TOOLS": {"streamout": "klayout"},
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    ids = [step.id for step in flow.Steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids
    assert Classic.Steps != flow.Steps, "class-level Steps must not be mutated"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_default_run_does_not_reexpand():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = Classic(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    assert [step.id for step in flow.Steps] == [
        step.id for step in Classic.Steps
    ]
```

- [ ] **Step 7: Implement instance-time re-expansion**

In `librelane/flows/staged.py`, add the `TOOLS` variable to the flow config and override `__init__`:

```python
    class Config(SequentialFlow.Config):
        TOOLS: Optional[dict] = variable(
            None,
            description=(
                "A mapping from stage id to the provider (tool) that should "
                "implement it, for example {\"synthesis\": \"genus\"}. Only "
                "overrides need listing; unnamed stages use their default "
                "provider. Must be a literal mapping: it is read before the "
                "configuration preprocessor runs."
            ),
        )

    def __init__(
        self,
        config,
        *,
        config_override_strings=None,
        **kwargs,
    ):
        tools = {}
        if not isinstance(config, Config):
            sources = config if isinstance(config, list) else [config]
            tools = extract_tools(
                sources,
                config_override_strings=config_override_strings,
                yaml_loader=_OpenLaneYAMLLoader,
            )
        elif config.get("TOOLS"):
            tools = dict(config["TOOLS"])

        if tools:
            resolution = resolve(self.Stages, tools)
            self.Steps = resolution.steps
            self._normalize_step_ids(self)
            self.gating_config_vars = dict(self.__class__.gating_config_vars)
            self._apply_stage_gating(self)
            self.__resolution = resolution

        super().__init__(
            config,
            config_override_strings=config_override_strings,
            **kwargs,
        )
```

`_apply_stage_gating` from Task 9 must be changed from a classmethod on `Self` to a staticmethod taking a `target`, so it works on both a class and an instance. Update its Task 9 call site accordingly.

Note the ordering: re-expansion happens before `super().__init__()`, so `get_all_config_variables()` sees the step set the user actually selected. That is the whole reason the pre-pass exists.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest test/flows test/config test/stages -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add librelane/config/loading librelane/flows test/config/test_tools_extraction.py test/flows/test_staged.py
git commit -m "feat: select a tool per stage from the TOOLS configuration key"
```

---

### Task 11: Runtime stage contract enforcement

After the last step of a stage completes, every view in the stage's `provides` must be present in the state and every name in its `metrics` must be present in `state.metrics`. There is no default, no skip and no warn-and-continue: a backend that does not report `route__drc_errors` must not be permitted to let `Checker.TrDRC` pass on an unexamined design.

**Files:**
- Modify: `librelane/flows/sequential.py:349-388`, `librelane/flows/staged.py`
- Test: `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `Boundary`, `StageContractError`, `parse_metric_modifiers`.
- Produces: `SequentialFlow._after_step(self, step, state, executed: bool) -> None`, a no-op hook called once per step in the run loop. `StagedFlow` overrides it. Task 14 extends the same override for spans.

The check runs in the run loop against the boundary map, not as synthetic check steps in the flow. Twenty-six extra step directories would be noise, the mechanism would reproduce the checker pattern this project intends to replace, and only the in-loop form can tell that a stage did not run every one of its steps.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_staged.py`:

```python
@pytest.fixture
def BrokenProviderStage():
    """A stage whose only provider fails to emit a metric it contracted."""
    from librelane.stages import Stage, StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class Silent(Step):
        id = "Mock.Silent"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Stage(
        id="contract_test",
        full_name="Contract Test",
        default_provider="silent",
        requires=(),
        provides=(),
        metrics=("mock__required",),
    ).register()

    StageRegistry.register(
        stages=["contract_test"],
        provider="silent",
        steps=[Silent],
        namespaces=["MOCK_"],
    )
    return Stage.factory.get("contract_test")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_missing_contracted_metric_raises(BrokenProviderStage):
    from librelane.flows import StagedFlow
    from librelane.stages import StageContractError

    class Broken(StagedFlow):
        Stages = [BrokenProviderStage]

    flow = Broken(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    with pytest.raises(StageContractError, match="mock__required"):
        flow.start()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_skipped_stage_is_not_contract_checked(BrokenProviderStage):
    from librelane.flows import StagedFlow

    class Broken(StagedFlow):
        Stages = [BrokenProviderStage]

    flow = Broken(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    flow.start(skip=["Mock.Silent"])  # must not raise


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_metric_modifiers_satisfy_the_contract():
    """
    GeneratePDN emits design__power_grid_violation__count__net:VPWR alongside
    the aggregate. The contract compares base names, so a provider that only
    emits modified variants of a contracted metric still satisfies it.
    """
    from librelane.common import parse_metric_modifiers

    base, modifiers = parse_metric_modifiers(
        "design__power_grid_violation__count__net:VPWR"
    )
    assert base == "design__power_grid_violation__count"
    assert modifiers == {"net": "VPWR"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_staged.py -v -k contract`
Expected: `test_missing_contracted_metric_raises` fails because nothing raises.

- [ ] **Step 3: Add the hook to the run loop**

In `librelane/flows/sequential.py`, add a no-op hook to `SequentialFlow`:

```python
    def _after_step(self, step: Step, state: State, executed: bool) -> None:
        """
        Called once for every step in ``Steps``, after it has run or been
        skipped. ``executed`` is False when the step was gated, skipped, or
        excluded by ``--from``/``--to``.

        The base implementation does nothing. ``StagedFlow`` uses it to check
        the stage contract at each boundary.
        """
```

In `run`, call it at the end of each loop iteration, after the `to_resolved` check:

```python
            self._after_step(step, current_state, increment_ordinal)
```

`increment_ordinal` is already False for every non-executing path (line 365) and True only when the step actually ran, so it is exactly the `executed` signal, with no new bookkeeping.

Note that `create_reproducible` breaks out of the loop before this point, which is correct: a reproducible run does not execute the flow.

- [ ] **Step 4: Implement the override**

In `librelane/flows/staged.py`:

```python
    def _after_step(self, step, state, executed: bool) -> None:
        if executed:
            self.__executed_step_ids.add(step.id)
        boundary = self.__boundary_by_last_step.get(step.id)
        if boundary is None:
            return
        if not all(
            step_id in self.__executed_step_ids for step_id in boundary.step_ids
        ):
            logger.debug(
                f"stage {list(boundary.stage_ids)}: not every step ran, "
                f"contract not checked"
            )
            return
        self.__check_contract(boundary, state)

    @staticmethod
    def __check_contract(boundary: Boundary, state: State) -> None:
        missing_views = [
            view.id for view in boundary.provides if state.get(view.id) is None
        ]
        produced = {
            parse_metric_modifiers(name)[0] for name in state.metrics
        }
        missing_metrics = [
            name for name in boundary.metrics if name not in produced
        ]
        if not missing_views and not missing_metrics:
            return
        parts = []
        if missing_views:
            parts.append(f"views {missing_views}")
        if missing_metrics:
            parts.append(f"metrics {missing_metrics}")
        raise StageContractError(
            f"stage {list(boundary.stage_ids)} completed without producing "
            f"{' and '.join(parts)}. Every provider of these stages is "
            f"contracted to produce them; a stage whose contract is not met "
            f"cannot be handed to the next stage."
        )
```

Build `self.__boundary_by_last_step` and `self.__executed_step_ids` in `__init__`, after the step list is final:

```python
        self.__executed_step_ids: set[str] = set()
        self.__boundary_by_last_step = {
            boundary.last_step_id: boundary
            for boundary in self.stage_boundaries(self.Steps)
        }
```

Replace the placeholder in `Boundary` construction (Task 7, Step 5) so `provides` and `metrics` come from the resolution's spans rather than being recomputed from the taxonomy, since only the resolution knows which providers were selected and therefore which `Registration.provides` and `Registration.metrics` apply. Thread the resolution through by storing it on the instance and matching spans to boundaries by `stage_ids`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows -v`
Expected: all pass, including the `Classic` equivalence tests.

- [ ] **Step 6: Commit**

```bash
git add librelane/flows test/flows/test_staged.py
git commit -m "feat: enforce the stage contract at each stage boundary"
```

---

### Task 12: Static view availability preflight, `RUN_POWER_HEADERS`, and `VHDLClassic` as configuration

This is the task that proves the abstraction works. `VHDLClassic` (`librelane/flows/classic.py:291`) exists today purely as a `Substitutions` map swapping one synthesis tool. It is precisely the "write a whole Flow subclass to change one tool" problem this design removes, and it is a real tool swap between two real tools rather than a mock.

**The unresolved detail from the spec is now resolved, with evidence.** `VHDLClassic` also removes `Odb.SetPowerConnections`, `Odb.WriteVerilogHeader` and `Yosys.JsonHeader`, which live outside the `synthesis` stage. The spec offered two candidate resolutions and said planning must check whether the view dependency is real. It is: `Yosys.JsonHeader` outputs `json_h` (`librelane/steps/pyosys.py:383`) and is a `VerilogStep`, so it cannot run on VHDL; and both `Odb.SetPowerConnections` (`librelane/steps/odb/power.py:49`) and `Odb.WriteVerilogHeader` (`librelane/steps/odb/power.py:74`) take `json_h` as a hard, non-optional input.

The spec's second candidate was to let the view contract remove those steps automatically. **That is rejected here.** Automatic dependency-driven pruning silently reshapes the flow, and a chain of steps can vanish without the user asking. The chosen resolution is the first candidate, a Boolean gate, made safe by a static check: forgetting the gate produces a precise preflight error naming the view, its would-be producer and its consumer, instead of a runtime crash deep in the flow. The check is generally valuable, because it validates any mixed-tool configuration, not just this one.

**Files:**
- Modify: `librelane/flows/staged.py`, `librelane/flows/classic.py`
- Test: `test/flows/test_staged.py`, `test/flows/test_staged_equivalence.py`

**Interfaces:**
- Consumes: `Step.inputs`, `Step.outputs`, `DesignFormat.optional`, the resolved `Config`.
- Produces: `StagedFlow._preflight_views()`, called at the end of `__init__`; `Classic.Config.RUN_POWER_HEADERS`.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_staged.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_vhdl_synthesis_without_the_gate_fails_preflight():
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    Classic = Flow.factory.get("Classic")
    with pytest.raises(StageResolutionError, match="json_h"):
        Classic(
            {
                "DESIGN_NAME": "WHATEVER",
                "VHDL_FILES": ["/cwd/src/a.vhd"],
                "TOOLS": {"synthesis": "yosys_vhdl"},
                "RUN_LINTER": False,
                "RUN_EQY": False,
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )
```

Append to `test/flows/test_staged_equivalence.py`:

```python
VHDL_CLASSIC_AS_CONFIG = {
    "TOOLS": {"synthesis": "yosys_vhdl"},
    "RUN_LINTER": False,
    "RUN_EQY": False,
    "RUN_POWER_HEADERS": False,
}


@pytest.mark.usefixtures("_mock_conf_fs")
def test_classic_with_vhdl_config_reproduces_vhdl_classic():
    """
    The strongest available validation that the abstraction does its job: a
    real tool swap between two real tools, expressed entirely in
    configuration, reproducing a flow that exists today only as a subclass.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = Classic(
        dict(
            DESIGN_NAME="WHATEVER",
            VHDL_FILES=["/cwd/src/a.vhd"],
            **VHDL_CLASSIC_AS_CONFIG,
        ),
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    golden = _load_golden("vhdl_classic_steps.json")
    executed = [
        step.id
        for step in flow.Steps
        if all(flow.config[v] for v in flow.gating_config_vars.get(step.id, []))
    ]
    assert executed == golden["step_ids"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows -v -k "vhdl"`
Expected: both new tests fail.

- [ ] **Step 3: Implement the preflight**

In `librelane/flows/staged.py`:

```python
    def _preflight_views(self) -> None:
        """
        Walks the resolved step list checking that every non-optional input a
        step consumes is produced by some earlier step.

        Steps whose gating variables are false in the resolved configuration
        are excluded, because they will not run. Gating is evaluated here
        rather than at run time so that a configuration which removes a
        producer, such as selecting a synthesis provider that emits no Verilog
        header, fails before any tool is invoked.
        """
        available: set[str] = set()
        last_stage = "<start of flow>"

        for step in self.Steps:
            gates = self.gating_config_vars.get(step.id, [])
            if any(not self.config[gate] for gate in gates):
                continue
            span = getattr(step, "_stage_span", None)
            for view in step.inputs:
                if view.optional or view.id in available:
                    continue
                raise StageResolutionError(
                    f"step '{step.id}' consumes view '{view.id}', which no "
                    f"earlier step in this configuration produces. The last "
                    f"stage before it is {last_stage}. Either a provider "
                    f"selected in TOOLS does not emit this view, or a gating "
                    f"variable removed the step that would have."
                )
            for view in step.outputs:
                available.add(view.id)
            if span is not None:
                last_stage = (
                    f"'{span[-1]}' (provider "
                    f"'{getattr(step, '_stage_provider', '?')}')"
                )
```

Call it as the last statement of `StagedFlow.__init__`, after `super().__init__()`, so `self.config` is populated.

- [ ] **Step 4: Add `RUN_POWER_HEADERS`**

In `librelane/flows/classic.py`, add to `Classic.Config`:

```python
        RUN_POWER_HEADERS: bool = variable(
            True,
            description=(
                "Enables the Yosys.JsonHeader, Odb.SetPowerConnections and "
                "Odb.WriteVerilogHeader steps, which propagate power intent "
                "from the RTL. Requires Verilog sources: Yosys.JsonHeader "
                "cannot run on VHDL."
            ),
        )
```

and to `gating_config_vars`:

```python
        "Yosys.JsonHeader": ["RUN_POWER_HEADERS"],
        "Odb.SetPowerConnections": ["RUN_POWER_HEADERS"],
        "Odb.WriteVerilogHeader": ["RUN_POWER_HEADERS"],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows -v`
Expected: all pass.

If `test_classic_with_vhdl_config_reproduces_vhdl_classic` fails on step ordering rather than membership, the difference is a step `VHDLClassic` removes that this configuration retains, or vice versa. Compare the two lists and fix the configuration or the gating, never the golden.

If the preflight fails on **default** `Classic`, stop and report. That would mean a step in today's flow consumes a view nothing produces, which is a pre-existing bug worth its own fix, not something to weaken the check for.

- [ ] **Step 6: Document `VHDLClassic` as superseded**

In `librelane/flows/classic.py`, extend the `VHDLClassic` docstring:

```python
    """
    A variant of Classic that accepts VHDL files for Synthesis instead of
    Verilog files (and removes Verilog linting/equivalence steps.)

    This flow is retained for backwards compatibility. The same result is now
    expressible as configuration against ``Classic``::

        "TOOLS": { "synthesis": "yosys_vhdl" },
        "RUN_LINTER": false,
        "RUN_EQY": false,
        "RUN_POWER_HEADERS": false
    """
```

Do not delete the class. It is public API.

- [ ] **Step 7: Commit**

```bash
git add librelane/flows test/flows
git commit -m "feat: preflight view availability and express VHDLClassic as configuration"
```

---

### Task 13: PDK view preflight

A provider that needs a PDK view the PDK does not define must fail before any tool runs, naming the stage, the provider, the variable and the PDK. This check is also the seam at which the PDK ingestion spec plugs in.

**Files:**
- Modify: `librelane/flows/staged.py`
- Test: `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `Registration.requires_pdk_vars`, the resolved `Config`, the resolution's spans.
- Produces: `StagedFlow._preflight_pdk_vars()`, called from `__init__` immediately before `_preflight_views()`.

For the resolution's spans to be available at preflight time, `StagedFlow.__init__` must keep the resolution even for a default expansion. Change Task 10's `__init__` so `resolve` is always called on the instance rather than only when `tools` is non-empty, and only reassign `self.Steps` when the result differs from the class-level list. That keeps the "default run does not re-expand" guarantee, which the Task 10 test asserts, while giving every run a resolution to read.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_staged.py`:

```python
@pytest.fixture
def PdkHungryStage():
    from librelane.stages import Stage, StageRegistry
    from librelane.steps import Step

    @Step.factory.register()
    class Hungry(Step):
        id = "Mock.Hungry"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Stage(
        id="pdk_hungry",
        full_name="PDK Hungry",
        default_provider="hungry",
        requires=(),
        provides=(),
    ).register()

    StageRegistry.register(
        stages=["pdk_hungry"],
        provider="hungry",
        steps=[Hungry],
        namespaces=["MOCK_"],
        requires_pdk_vars=["QRC_TECHFILE"],
    )
    return Stage.factory.get("pdk_hungry")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_missing_pdk_variable_names_stage_provider_variable_and_pdk(
    PdkHungryStage,
):
    from librelane.flows import StagedFlow
    from librelane.stages import StageResolutionError

    class Hungry(StagedFlow):
        Stages = [PdkHungryStage]

    with pytest.raises(StageResolutionError) as excinfo:
        Hungry(
            {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    message = str(excinfo.value)
    assert "pdk_hungry" in message
    assert "hungry" in message
    assert "QRC_TECHFILE" in message
    assert "dummy" in message
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest test/flows/test_staged.py -v -k pdk`
Expected: FAIL, no exception raised.

- [ ] **Step 3: Implement the check**

In `librelane/flows/staged.py`:

```python
    def _preflight_pdk_vars(self) -> None:
        """
        Checks each selected provider's ``requires_pdk_vars`` against the
        resolved configuration. A variable that is absent or ``None`` fails the
        run before any tool is invoked.
        """
        pdk = self.config.get("PDK", "<unknown>")
        for span in self.__resolution.spans:
            for provider in span.provider.split("+"):
                registration = StageRegistry.get(span.stage_ids[0], provider)
                if registration is None:
                    continue
                for name in registration.requires_pdk_vars:
                    if self.config.get(name) is not None:
                        continue
                    raise StageResolutionError(
                        f"{span.stage_ids[0]}: provider '{provider}' requires "
                        f"{name}, which PDK '{pdk}' does not define"
                    )
```

Call it from `__init__` after `super().__init__()` and before `_preflight_views()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add librelane/flows test/flows/test_staged.py
git commit -m "feat: check each provider's required PDK variables before running"
```

---

### Task 14: Spanning providers

A provider may cover several consecutive stages with one registration, for the case where decomposition is impossible rather than merely inconvenient. The motivating case is Innovus routing: antenna repair there is not a command but a router mode (`setNanoRouteMode -drouteFixAntenna true`) set before `globalDetailRoute`, so there is no point at which such a flow could hand a partially-antenna-repaired design to another tool.

**Files:**
- Modify: `librelane/stages/resolution.py`, `librelane/flows/staged.py`
- Test: `test/stages/test_resolution.py`, `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `Registration.spanning`, `Registration.stages`.
- Produces: `resolve()` handles spanning registrations; `ResolvedSpan.stage_ids` may have length greater than one. `StagedFlow` rejects gating a stage inside a span.

Every rule is enforced, not assumed.

- [ ] **Step 1: Write the failing tests**

Append to `test/stages/test_resolution.py`:

```python
@pytest.fixture
def spanning_registration():
    from librelane.stages import StageRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class SpanAll(Step):
        id = "Mock.SpanAll"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {"route__drc_errors": 0}

    return StageRegistry.register(
        stages=[
            "global_routing",
            "post_grt_repair",
            "antenna_repair",
            "post_grt_opt",
            "detailed_routing",
        ],
        provider="mock_router",
        steps=[SpanAll],
        namespaces=["MOCK_"],
    )


def test_span_resolves_to_one_step_and_one_span(spanning_registration):
    from librelane.stages import Stage
    from librelane.stages.resolution import resolve

    entries = [
        Stage.factory.get(id)
        for id in (
            "global_routing",
            "post_grt_repair",
            "antenna_repair",
            "post_grt_opt",
            "detailed_routing",
        )
    ]
    tools = {id.id: "mock_router" for id in entries}
    resolution = resolve(entries, tools)

    assert [step.id for step in resolution.steps] == ["Mock.SpanAll"]
    assert len(resolution.spans) == 1
    assert resolution.spans[0].stage_ids == (
        "global_routing",
        "post_grt_repair",
        "antenna_repair",
        "post_grt_opt",
        "detailed_routing",
    )
    assert "route__drc_errors" in resolution.spans[0].metrics


def test_partial_span_selection_is_an_error(spanning_registration):
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve

    entries = [
        Stage.factory.get(id)
        for id in ("global_routing", "post_grt_repair", "antenna_repair",
                   "post_grt_opt", "detailed_routing")
    ]
    with pytest.raises(StageResolutionError, match="every stage in that span"):
        resolve(entries, {"global_routing": "mock_router"})


def test_non_contiguous_span_is_an_error(spanning_registration):
    from librelane.stages import Stage, StageResolutionError
    from librelane.stages.resolution import resolve
    from librelane.steps import OpenROAD

    entries = [
        Stage.factory.get("global_routing"),
        OpenROAD.STAMidPNR,
        Stage.factory.get("post_grt_repair"),
        Stage.factory.get("antenna_repair"),
        Stage.factory.get("post_grt_opt"),
        Stage.factory.get("detailed_routing"),
    ]
    tools = {
        id: "mock_router"
        for id in (
            "global_routing", "post_grt_repair", "antenna_repair",
            "post_grt_opt", "detailed_routing",
        )
    }
    with pytest.raises(StageResolutionError, match="contiguous"):
        resolve(entries, tools)
```

Append to `test/flows/test_staged.py`:

```python
def test_gating_a_stage_inside_a_span_is_an_error(spanning_registration):
    from librelane.flows import StagedFlow
    from librelane.stages import Stage, StageResolutionError

    class Spanned(StagedFlow):
        Stages = [
            Stage.factory.get(id)
            for id in (
                "global_routing", "post_grt_repair", "antenna_repair",
                "post_grt_opt", "detailed_routing",
            )
        ]

    with pytest.raises(StageResolutionError, match="not independently controllable"):
        Spanned(
            {
                "DESIGN_NAME": "WHATEVER",
                "VERILOG_FILES": ["/cwd/src/a.v"],
                "TOOLS": {
                    id: "mock_router"
                    for id in (
                        "global_routing", "post_grt_repair", "antenna_repair",
                        "post_grt_opt", "detailed_routing",
                    )
                },
                "RUN_POST_GRT_DESIGN_REPAIR": False,
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )
```

Move the `spanning_registration` fixture into `test/stages/conftest.py` so both modules can use it, and make `test/flows/test_staged.py` import it via a `conftest.py` in `test/flows/` that re-exports it, or duplicate the fixture. Prefer moving it to the top-level `test/conftest.py` next to the existing shared fixtures.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/stages/test_resolution.py test/flows/test_staged.py -v -k span`
Expected: all four fail. Three raise the Task 7 "not yet supported" error.

- [ ] **Step 3: Implement span resolution**

In `librelane/stages/resolution.py`, delete the `registration.spanning` rejection from `_registration_for`, and restructure the main loop of `resolve` to consume a span when it meets one:

```python
    index = 0
    while index < len(entries):
        entry = entries[index]
        if not isinstance(entry, Stage):
            steps.append(entry)
            index += 1
            continue

        providers = _selection_for(entry, tools)
        if providers is None:
            unselected.append(entry.id)
            index += 1
            continue

        if len(providers) == 1:
            registration = _registration_for(entry, providers[0])
            if registration.spanning:
                index = _consume_span(
                    entries, index, registration, tools, steps, spans
                )
                continue

        span_steps: list[type[Step]] = []
        provides = set(entry.provides)
        metrics = set(entry.metrics)
        for provider in providers:
            registration = _registration_for(entry, provider)
            span_steps.extend(registration.tagged_steps())
            provides.update(registration.provides)
            metrics.update(registration.metrics)

        steps.extend(span_steps)
        spans.append(
            ResolvedSpan(
                stage_ids=(entry.id,),
                provider="+".join(providers),
                provides=tuple(sorted(provides, key=lambda view: view.id)),
                metrics=tuple(sorted(metrics)),
                gating_config_var=entry.gating_config_var,
                unavailable_gates=(),
            )
        )
        index += 1
```

and add the span consumer:

```python
def _consume_span(
    entries: Sequence[StageEntry],
    index: int,
    registration: Registration,
    tools: Mapping[str, ToolSelection],
    steps: list[type[Step]],
    spans: list[ResolvedSpan],
) -> int:
    """
    Consumes a spanning registration's whole span starting at ``index``,
    verifying that the flow lists exactly those stages, contiguously, and that
    ``TOOLS`` selects the same provider for every one of them.
    """
    expected = registration.stages
    window = entries[index : index + len(expected)]
    actual = tuple(
        entry.id if isinstance(entry, Stage) else f"<step {entry.id}>"
        for entry in window
    )
    if actual != expected:
        raise StageResolutionError(
            f"provider '{registration.provider}' spans {list(expected)}, but "
            f"this flow lists {list(actual)} at that position. A span must be "
            f"contiguous in the flow's Stages order, with no intervening "
            f"plain step entries."
        )

    for stage_id in expected:
        selection = _selection_for(Stage.factory.get(stage_id), tools)
        if selection != (registration.provider,):
            raise StageResolutionError(
                f"provider '{registration.provider}' implements "
                f"{list(expected)} as one indivisible span, so TOOLS must "
                f"select it for every stage in that span. Stage '{stage_id}' "
                f"resolves to {list(selection or ())} instead. The span is "
                f"neither split nor widened silently."
            )

    steps.extend(registration.tagged_steps())

    provides: set = set(registration.provides)
    metrics: set = set(registration.metrics)
    gates: list[str] = []
    for stage_id in expected:
        stage = Stage.factory.get(stage_id)
        provides.update(stage.provides)
        metrics.update(stage.metrics)
        if stage.gating_config_var is not None:
            gates.append(stage.gating_config_var)

    spans.append(
        ResolvedSpan(
            stage_ids=expected,
            provider=registration.provider,
            provides=tuple(sorted(provides, key=lambda view: view.id)),
            metrics=tuple(sorted(metrics)),
            gating_config_var=None,
        )
    )
    return index + len(expected)
```

`ResolvedSpan.gating_config_var` is `None` for a span, because no single variable gates it. `StagedFlow` must therefore learn which gates are unavailable; add a field `unavailable_gates: tuple[str, ...]` to `ResolvedSpan`, set to `tuple(gates)` here and to `()` on the single-stage path.

The contract is checked once at the end of the span, against the union of the spanned stages' `provides` and `metrics`. Intermediate stage contracts are not checked, because the intermediate states do not exist as artifacts. This falls out of the boundary scanner already: every step of the span carries the same `_stage_span`, so it forms one boundary.

- [ ] **Step 4: Reject gating inside a span**

In `librelane/flows/staged.py`, add to `_preflight_pdk_vars`'s caller chain a new check, run right after resolution:

```python
    def _preflight_span_gating(self) -> None:
        """
        A stage inside a span is not independently controllable, so asking for
        it is an error rather than a no-op. This is a real property of the tool
        being used, not an artifact of the framework, so it is surfaced.
        """
        for span in self.__resolution.spans:
            for gate in span.unavailable_gates:
                if self.config[gate]:
                    continue
                raise StageResolutionError(
                    f"{gate} is false, but the stage it gates is inside the "
                    f"span {list(span.stage_ids)} implemented by provider "
                    f"'{span.provider}'. That stage is not independently "
                    f"controllable under the selected provider."
                )
```

Also make `_apply_stage_gating` skip stages whose span length exceeds one, so a span never receives partial gating entries.

`--from` a mid-span stage resolves to the span's first step because the span expands to a single contiguous run of steps and `--from` names a step ID; the first step of that run is the only reachable entry point. No code is needed for this, but assert it in a test.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/stages test/flows -v`
Expected: all pass, including `Classic` equivalence. No open-source provider spans, so `Classic` is untouched.

- [ ] **Step 6: Commit**

```bash
git add librelane/stages/resolution.py librelane/flows/staged.py test
git commit -m "feat: support providers that span several consecutive stages"
```

---

### Task 15: Stage listing and documentation

**Files:**
- Modify: `librelane/flows/staged.py`
- Create: `docs/source/usage/swapping_tools.md`, `docs/source/usage/writing_tool_backends.md`
- Modify: `docs/source/usage/index.md`, `Changelog.md`
- Test: `test/flows/test_staged.py`

**Interfaces:**
- Consumes: `Stage`, `StageRegistry`, `Flow.get_help_md`.
- Produces: `StagedFlow.get_help_md` gains a stage table; `StagedFlow.describe_stages() -> list[tuple[str, str]]`.

**Deviation from the spec, recorded deliberately.** The spec said unselected stages appear in `--list-stages`. There is no `--list-stages` flag and no `--list-flows` to model one on, and the CLI is being restructured on this branch (`librelane/cli/_app.py`, `options.py`, `run.py` and `runtime.py` are all new or modified). Adding a flag there would conflict for no benefit. Instead the stage table goes into `get_help_md`, which `librelane help Classic` already renders (`librelane/cli/help.py:38`) and which the documentation build already consumes. Same information, no new CLI surface.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_staged.py`:

```python
def test_help_lists_stages_and_their_providers():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    help_md = Classic.get_help_md()

    assert "#### Stages" in help_md
    assert "| `detailed_routing` | `openroad` |" in help_md
    assert "| `streamout` | `magic`, `klayout` |" in help_md
    assert "| `post_route_opt` | none selected |" in help_md


def test_describe_stages_reports_the_default_selection():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    described = dict(Classic.describe_stages())

    assert described["cts"] == "openroad"
    assert described["post_route_opt"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_staged.py -v -k "help or describe"`
Expected: FAIL with `AttributeError: describe_stages`.

- [ ] **Step 3: Implement**

In `librelane/flows/staged.py`:

```python
    @classmethod
    def describe_stages(Self) -> list[tuple[str, str | None]]:
        """
        :returns: One entry per stage in ``Stages``, in flow order, pairing the
            stage id with the provider selected for it by default. The provider
            is ``None`` for an unselected optional stage, and several names
            joined by ", " for a multi-provider stage.
        """
        described: list[tuple[str, str | None]] = []
        for entry in Self.Stages:
            if not isinstance(entry, Stage):
                continue
            providers = entry.default_providers
            described.append(
                (entry.id, ", ".join(providers) if providers else None)
            )
        return described

    @classmethod
    def get_help_md(Self, myst_anchors: bool = False) -> str:  # pragma: no cover
        result = super().get_help_md(myst_anchors=myst_anchors)
        if not Self.Stages:
            return result
        result += "\n#### Stages\n\n"
        result += (
            "Set the `TOOLS` configuration variable to change the tool used "
            "for any of these. See "
            "[Swapping Tools](./swapping_tools.md).\n\n"
        )
        result += "| Stage | Default provider | Alternatives |\n"
        result += "| --- | --- | --- |\n"
        for stage_id, default in Self.describe_stages():
            selected = set((default or "").split(", "))
            others = [
                provider
                for provider in StageRegistry.providers(stage_id)
                if provider not in selected
            ]
            default_cell = (
                ", ".join(f"`{name}`" for name in default.split(", "))
                if default
                else "none selected"
            )
            others_cell = (
                ", ".join(f"`{name}`" for name in others) if others else "none"
            )
            result += f"| `{stage_id}` | {default_cell} | {others_cell} |\n"
        return result
```

Placing this after the "Included Steps" section keeps the existing output byte-identical up to that point, which the Task 8 help diff already established.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows -v`
Expected: all pass.

- [ ] **Step 5: Write the user documentation**

Create `docs/source/usage/swapping_tools.md`, user-facing, covering in this order:

1. What a stage is, in one paragraph: the unit of tool choice, gating and re-entry.
2. The `TOOLS` key, with the two worked examples that actually run today: `{"synthesis": "yosys_vhdl"}` and `{"streamout": "klayout"}`.
3. The full `VHDLClassic`-as-configuration example from Task 12, presented as the canonical demonstration.
4. The stage table, generated by pasting the output of `uv run librelane help Classic`.
5. Multi-provider stages: why `streamout` and `drc` run two tools, and what `PRIMARY_GDSII_STREAMOUT_TOOL` decides.
6. Setting many stages at once through configuration layering, since `librelane/config/loading/layering.py:15` already merges ordered sources with provenance.
7. The three limitations, stated plainly: `TOOLS` cannot come from the PDK or from a Tcl configuration; view-level compatibility is guaranteed but semantic compatibility across a vendor boundary is not; and a stage inside a spanning provider's span cannot be gated or re-entered.
8. The `antenna_repair` consequence: stage selection governs the primary flow, not a provider's internal repair of the perturbation it caused, so selecting Innovus for `detailed_placement` and OpenROAD for `antenna_repair` means OpenROAD detailed placement runs inside antenna repair.

Create `docs/source/usage/writing_tool_backends.md`, alongside `writing_custom_steps.md` and `writing_plugins.md`, covering:

1. A minimal complete registration, with `StageRegistry.register` and every argument explained.
2. The three enforcement points and what each catches: registration time (canonical variable coverage, namespace discipline, view plausibility), resolution time (unknown provider, list misuse, unknown stage key, PDK variables, view availability), and runtime (the stage contract).
3. `namespaces`: declare one tool-named prefix. The several legacy prefixes on the `openroad` provider are grandfathered, not a pattern to copy.
4. `native_views`: what they are for, using `odb` as the worked example, and the rule that correctness must never depend on the native path.
5. How finely to decompose a sequence, with the tool session cost stated: each step is a separate subprocess paying startup, license checkout and a database round trip.
6. When to register a span instead, with the `setNanoRouteMode -drouteFixAntenna` case as the worked example, and the explicit warning that a span forfeits per-stage gating and re-entry.
7. Packaging: a backend is an ordinary `librelane_plugin_*` module, auto-imported by `librelane/plugins.py:17-21`, so registration at import time needs no new discovery mechanism.
8. The honest scope statement: no commercial backend ships with LibreLane, none has been tested, and the first author of one should expect to correct parts of this contract.

Add both files to the toctree in `docs/source/usage/index.md`.

Use markdown syntax throughout, not HTML tags.

- [ ] **Step 6: Update the changelog**

Add to `Changelog.md`, under the unreleased section: the `TOOLS` key, the stage taxonomy, `RUN_POWER_HEADERS`, that `VHDLClassic` is now expressible as configuration, and a pointer to the three gating behaviour changes recorded in Task 9.

- [ ] **Step 7: Build the documentation**

Run: `uv run make -C docs html`
Expected: no new warnings. Check that both new pages render and that the stage table in `librelane help Classic` output is correct.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest test -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add librelane/flows/staged.py docs test/flows/test_staged.py Changelog.md
git commit -m "docs: document tool swapping and the provider contract"
```

---

## Self-Review Notes

Recorded so a reader knows what was checked and what is deliberately open.

**Spec coverage.** Every section of the design document maps to a task: the `Stage` object and factory to Task 3, `StageRegistry` and its M:N registration to Task 4, the taxonomy to Task 5, the `openroad` provider set to Task 6, resolution order and class-definition-time expansion to Task 7, `Classic` backward compatibility to Task 8, stage gating to Task 9, the `TOOLS` pre-pass to Task 10, runtime contract enforcement to Task 11, the `VHDLClassic` equivalence test and its unresolved detail to Task 12, PDK view preflight to Task 13, spanning providers to Task 14, and documentation to Task 15. The shared `CompositeStep` union helper is Task 2.

**Four deviations from the spec, each with a reason.**

1. `Registration` carries its own `provides` and `metrics` in addition to the stage's. Without this the `drc` stage cannot be contracted at all, because `magic` and `klayout` produce differently named metrics and neither can promise the other's (Task 4).
2. `Registration.native_views` was not in the spec. It is forced by `OpenROADStep.inputs` being `[odb]`, a tool-native view; without it every `openroad` registration after `floorplan` fails the registration-time view check (Task 4).
3. `Stage.default_provider` may be a tuple. `Classic` streams out with both Magic and KLayout by default and runs both DRC decks, which a single-string default cannot express (Task 3).
4. `--list-stages` became a section in `get_help_md`. There is no comparable CLI flag to model one on and the CLI is being restructured on this branch (Task 15).

**Three ordering corrections to the spec's taxonomy table**, all discovered by partitioning `Classic` rather than by reasoning: `Magic.WriteLEF` and the two DRC checkers leave their stages to become plain steps at boundaries, and `OpenROAD.CutRows` leaves `tapcell_insertion` so that `RUN_TAP_ENDCAP_INSERTION` does not silently change placement (Task 6).

**The spec's one open question is resolved with evidence** in Task 12: the `json_h` view dependency is real, so `Yosys.JsonHeader`, `Odb.SetPowerConnections` and `Odb.WriteVerilogHeader` are gated on a new `RUN_POWER_HEADERS` variable, and a static preflight turns a forgotten gate into a precise error rather than a runtime crash. The spec's alternative, letting the view contract remove those steps automatically, is rejected because silent flow reshaping is the failure mode this design exists to prevent.

**Three deliberate behaviour changes** are introduced by stage gating and are tabulated in Task 9, each with its justification and each requiring a changelog entry.

**Known gap, not addressed by this plan.** LibreLane has no step that imports a DEF into an OpenDB database. An `openroad` stage therefore cannot follow a non-OpenROAD stage: the `odb` native view would be absent and Task 12's preflight would reject the configuration by name. This is correct behaviour rather than a silent failure, but it means a mixed flow can currently hand off *out of* OpenROAD and not back *into* it. Closing the gap means adding a DEF import step to the head of the affected `openroad` sequences, which is work for whoever writes the first commercial backend and needs that direction to function. It is recorded in `writing_tool_backends.md`.
