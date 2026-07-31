# Workflow Document Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pydantic models, YAML loader and every load-time validation for a LibreLane workflow document, as a pure addition that nothing consumes yet.

**Scale:** Seven tasks. 5 collected tests in `test/flows/test_spec_graph.py`, 29 in `test/flows/test_spec.py` (22 functions, two of them parametrised), 26 in `test/flows/test_spec_validation.py`, for 60 in total. Every "Expected: N passed" line below is a collected count, which is what pytest prints.

**Architecture:** A flow document is a `FlowSpec` pydantic model holding a `dict[str, JobSpec]`. Validation happens in two tiers. Structural checks that need only the document itself run as pydantic model validators, so the Python API and the YAML path get identical errors. Semantic checks that need the stage and step registries run as a separate `validate_against_registry` pass, so the models stay unit-testable without a populated registry. Graph algorithms live in their own module because phase 4 needs `ancestors`/`descendants` for `--target` and `--invalidate`, and because the reachability and sink checks below need `descendants` too.

The two-tier split is real and verified. `from librelane.config import Variable, universal_flow_config_variables` and `from librelane.common.errors import FlowError` leave `librelane.steps` and `librelane.stages` absent from `sys.modules`, so `spec.py` can validate conditions and reserved keys without a populated registry.

**Tech Stack:** Python 3.11+, pydantic 2.13.4, `graphlib` from the standard library for cycle detection and topological order, pyyaml via the existing `librelane.config.loading.sources.read_source`, pytest with pytest-mock, uv for dependency management.

## Global Constraints

- This is phase 1 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. Nothing in this phase may modify `SequentialFlow`, `StagedFlow`, `Stage`, `StageRegistry` or any shipped flow. It is additive only, and the full test suite must stay green.
- Never add a fallback. An unresolvable name, an unsupported type, or an ambiguous join is an error naming the legal alternatives, never a silent default.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Reuse the dependency rather than hand-rolling. Cycle detection and topological order are `graphlib.TopologicalSorter`, not a hand-written DFS. YAML reading is `read_source`, not a bare `yaml.load`.
- The document's six job keys are exactly `needs`, `uses`, `steps`, `source`, `if` and `with`. No others.
- `if` in YAML maps to the Python field `condition` through a pydantic alias, and `with` maps to `values` the same way. Both spellings must work on both models.
- `source` is `dict[str, str]` on `JobSpec`, keyed by a plain string. A key is a view id or a metric name, and metric names such as `design__lvs_error__count` are not `DesignFormat`s, so a `DesignFormat`-keyed mapping cannot express the join rule the spec states for views and metrics alike.
- Every new file carries the Apache 2.0 header used by `librelane/flows/explanation.py`, with the year 2026.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

## File Structure

| File | Responsibility |
| --- | --- |
| `librelane/flows/spec.py` | `VariableSpec`, `JobSpec`, `FlowSpec`, `FlowSpecError`, `parse_condition`, `load_flow_spec`. Field-level and structural validation. |
| `librelane/flows/spec_graph.py` | Pure graph math over `dict[str, list[str]]`. No LibreLane imports. `topological_order`, `ancestors`, `descendants`, `CycleError` passthrough. |
| `librelane/flows/spec_validation.py` | `validate_against_registry`. Every check that needs `Stage.factory`, `StageRegistry`, `Step.factory`, `DesignFormat.factory` or `Metric.by_name`. |
| `test/flows/test_spec_graph.py` | Unit tests for the graph module. |
| `test/flows/test_spec.py` | Unit tests for the models, the loader and structural validation. |
| `test/flows/test_spec_validation.py` | Unit tests for registry-backed validation. |

`spec_graph.py` is separated because phase 4 consumes `ancestors` for `--target` and `descendants` for `--invalidate`, and because pure graph math with no domain imports is the easiest thing in this plan to test exhaustively.

## Verified facts this plan depends on

Every number and name below was produced by running the real registries in this checkout, not recalled, with the single marked exception. Re-run them if you doubt one.

| Fact | Value |
| --- | --- |
| Registered stage ids | 27, listed in `librelane/stages/taxonomy.py` |
| Stages whose `requires` equals a non-empty `provides` | 14, the `PNR_IN_PLACE` contract |
| `Stage.synthesis` | requires `()`, provides `(nl,)`, metrics `('design__instance_unmapped__count', 'synthesis__check_error__count')`, providers `['yosys', 'yosys_vhdl']` |
| `Stage.floorplan` (see the note below) | requires `(nl,)`, provides `(def, nl, sdc)`, providers `['openroad']` |
| `Stage.streamout` | requires `(def, nl, sdc)`, provides `(gds,)`, default providers `('magic', 'klayout')` |
| `Stage.drc` | requires `(def, gds)`, provides `()`, default providers `('magic', 'klayout')` |
| `Stage.lvs` | requires `(def, gds, pnl)`, provides `()`, metrics `('design__lvs_error__count',)`, providers `['netgen']`, becoming `['netgen', 'klayout']` (see the note below) |
| `Stage.cts` | requires `(def, nl, sdc)`, provides `(def, nl, sdc)`, providers `['openroad']` |
| `StageRegistry.get("streamout", "magic").provides` | `(mag_gds,)` |
| `StageRegistry.get("streamout", "klayout").provides` | `(klayout_gds,)` |
| `StageRegistry.get("lvs", "netgen").metrics` | `('magic__illegal_overlap__count',)` |
| `StageRegistry.get("drc", "magic").metrics` | `('magic__drc_error__count',)` |
| `StageRegistry.get("drc", "klayout").metrics` | `('klayout__drc_error__count',)` |
| Metric names declared across all stages and registrations | 15, every one of them present in `Metric.by_name` |
| `Metric.by_name` | 68 entries, populated by importing `librelane.steps` |
| `DesignFormat.factory.list()` | 46 entries, 23 distinct, so error messages must de-duplicate |
| `SYNTH_STRATEGY` declared by | `Yosys.Resynthesis`, `Yosys.Synthesis`, `Yosys.VHDLSynthesis` |
| `FP_CORE_UTIL` declared by | `OpenROAD.Floorplan`, `OpenROAD.GlobalPlacement`, `OpenROAD.GlobalPlacementSkipIO` |
| `universal_flow_config_variables` | 78 entries, containing `DIE_AREA` and `PDK` but **not** `SCL`, `PAD` or `meta`, and containing **no** variable of type `bool` |
| `DIE_AREA` | universal, and additionally declared by `Magic.StreamOut` |

**A second unmerged dependency, on the `lvs` row.** Branch
`worktree-agent-a3d55fc98368cf973` registers `klayout` as a second provider of
the `lvs` stage, so `StageRegistry.providers("lvs")` becomes
`['netgen', 'klayout']`. That order is registration order, not alphabetical:
`providers()` filters `Self._all` in the order entries were appended, and
netgen's entry comes first in `librelane/stages/providers.py`. The stage stays
`multi_provider=False`, so exactly one of the two runs and the stage's
contracted `design__lvs_error__count` still has exactly one writer per run. Any
count this document states for the `lvs` stage must move from one provider to
two when that branch merges; nothing else about the row changes.

**The load-bearing unmerged dependency.** The `Stage.floorplan` row records `requires (nl,)`. That is the value on branch `worktree-agent-a2dad013ce988e29b`, not the value on `librelane-unstable` today, where the stage still declares `(nl, sdc)`. That branch fixes a taxonomy bug that stopped `Classic` from completing a run. `MultiCornerSTA.outputs` claimed an SDC that nothing in the class writes, `Stage.pre_pnr_sta.provides` was derived from that claim, and the stage contract check failed at run time. The fix sets `Stage.pre_pnr_sta.provides` to the empty tuple and `Stage.floorplan.requires` to `(DesignFormat.nl,)`, which is what the provider always declared. `OpenROAD.Floorplan` has `inputs = [DesignFormat.NETLIST]` and its `outputs` are `odb`, `def`, `sdc`, `nl` and `pnl`, verified in this checkout. Floorplan writes the SDC, it never read one. The sweep branches merge before any of this plan is implemented, so the plan is written against the post-fix values. Every other row in the table was executed against the registries here. Two places in this document depend on that fix landing, this row and the reachability argument in Task 6, and both go stale together if it is reverted.

Two consequences fall straight out of that table and are load-bearing below.

`SCL`, `PAD` and `meta` are not configuration variables at all, so the reserved document-level `with` keys are a literal four-name tuple rather than something derived from the universal set.

No universal variable is a `bool`, so an `if` can only ever name a variable the document itself declares. That makes the whole condition check structural, needing no registry.

---

### Task 1: The graph module

**Files:**
- Create: `librelane/flows/spec_graph.py`
- Test: `test/flows/test_spec_graph.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `topological_order(edges: dict[str, list[str]]) -> list[str]` where `edges[node]` lists that node's predecessors. Raises `graphlib.CycleError`.
  - `ancestors(edges: dict[str, list[str]], node: str) -> set[str]` is the transitive predecessors, excluding `node` itself.
  - `descendants(edges: dict[str, list[str]], node: str) -> set[str]` is the transitive successors, excluding `node` itself.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_spec_graph.py`:

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
import graphlib

import pytest

from librelane.flows.spec_graph import ancestors, descendants, topological_order

pytestmark = pytest.mark.all

# streamout fans out to drc and lvs, which fan back in to xor.
_DIAMOND = {
    "streamout": [],
    "drc": ["streamout"],
    "lvs": ["streamout"],
    "xor": ["drc", "lvs"],
}


def test_topological_order_puts_every_predecessor_first():
    order = topological_order(_DIAMOND)

    assert order.index("streamout") < order.index("drc")
    assert order.index("streamout") < order.index("lvs")
    assert order.index("drc") < order.index("xor")
    assert order.index("lvs") < order.index("xor")
    assert sorted(order) == ["drc", "lvs", "streamout", "xor"]


def test_topological_order_raises_on_a_cycle_naming_its_members():
    with pytest.raises(graphlib.CycleError) as exc_info:
        topological_order({"a": ["b"], "b": ["a"]})

    assert set(exc_info.value.args[1]) >= {"a", "b"}


def test_ancestors_are_transitive_and_exclude_the_node():
    assert ancestors(_DIAMOND, "xor") == {"drc", "lvs", "streamout"}
    assert ancestors(_DIAMOND, "drc") == {"streamout"}
    assert ancestors(_DIAMOND, "streamout") == set()


def test_descendants_are_transitive_and_exclude_the_node():
    assert descendants(_DIAMOND, "streamout") == {"drc", "lvs", "xor"}
    assert descendants(_DIAMOND, "drc") == {"xor"}
    assert descendants(_DIAMOND, "xor") == set()


def test_disjoint_branches_are_not_each_other_s_relatives():
    assert "lvs" not in ancestors(_DIAMOND, "drc")
    assert "lvs" not in descendants(_DIAMOND, "drc")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec_graph.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.spec_graph'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/spec_graph.py`:

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
Graph math over a job dependency map, with no LibreLane types involved.

Every function takes ``edges``, a mapping from a node to the list of nodes it
directly depends on. This is the same direction as a workflow document's
``needs`` key, so a ``FlowSpec``'s job map converts without inversion.

Kept free of domain imports so it can be tested exhaustively on its own, and
because the command-line surface consumes :func:`ancestors` for ``--target``
and :func:`descendants` for ``--invalidate``.
"""

import graphlib


def topological_order(edges: dict[str, list[str]]) -> list[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.

    Returns
    -------
    Every node, with each node's dependencies appearing before it.

    Raises
    ------
    graphlib.CycleError
        If the graph contains a cycle. The offending
        nodes are in ``args[1]``.
    """
    return list(graphlib.TopologicalSorter(edges).static_order())


def ancestors(edges: dict[str, list[str]], node: str) -> set[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    node : str
        The node to walk back from.

    Returns
    -------
    Every transitive predecessor of ``node``, excluding ``node``.
    """
    return _reachable(edges, node)


def descendants(edges: dict[str, list[str]], node: str) -> set[str]:
    """
    Parameters
    ----------
    edges : dict[str, list[str]]
        A mapping from each node to the nodes it depends on.
    node : str
        The node to walk forward from.

    Returns
    -------
    Every transitive successor of ``node``, excluding ``node``.
    """
    return _reachable(_reverse(edges), node)


def _reverse(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    inverted: dict[str, list[str]] = {name: [] for name in edges}
    for name, predecessors in edges.items():
        for predecessor in predecessors:
            inverted[predecessor].append(name)
    return inverted


def _reachable(edges: dict[str, list[str]], node: str) -> set[str]:
    found: set[str] = set()
    frontier = list(edges[node])
    while frontier:
        current = frontier.pop()
        if current in found:
            continue
        found.add(current)
        frontier.extend(edges[current])
    found.discard(node)
    return found
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec_graph.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/spec_graph.py test/flows/test_spec_graph.py
git commit -m "feat: add job graph math for the workflow document"
```

---

### Task 2: The document models

**Files:**
- Create: `librelane/flows/spec.py`
- Test: `test/flows/test_spec.py`

**Interfaces:**
- Consumes: nothing from Task 1 yet.
- Produces:
  - `FlowSpecError(FlowError)` is raised for every load-time rejection that is not a raw pydantic field error.
  - `VariableSpec(BaseModel)` with fields `name: str`, `type: str`, `description: str`, `default: Any = None`, `deprecated_names: list[str] = []`, `units: str | None = None`, and a method `to_variable() -> Variable`.
  - `JobSpec(BaseModel)` with fields `needs: list[str] = []`, `uses: str | None = None`, `steps: list[str] | None = None`, `source: dict[str, str] = {}`, `values: dict[str, Any] = {}` aliased to `with`, `condition: str | None = None` aliased to `if`.
  - `FlowSpec(BaseModel)` with fields `name: str`, `description: str = ""`, `values: dict[str, Any] = {}` aliased to `with`, `config: list[VariableSpec] = []`, `jobs: dict[str, JobSpec]`, `final: str | None = None`.

**Context the implementer needs:**

`librelane.config.Variable` is a dataclass declared at `librelane/config/legacy.py:297`. Its constructor is positional-then-keyword, verified as `Variable(name, type, description, default=None, deprecated_names=<factory>, units=None, pdk=False, validator=<lambda>)`. `type` is a real Python type object, not a string, which is why `VariableSpec` needs a name-to-type mapping.

Only five scalar type names are supported. This is not an arbitrary restriction. Across all six shipped flows there are exactly two config-var annotations, `bool` used 22 times and `TOOLS`'s `Optional[dict[str, Union[str, list[str]]]]` used once. `TOOLS` is an engine-level variable declared by the engine, not by any document, so no document needs a product type. Anything outside the five is an error naming the five.

`JobSpec` rejects a job declaring **both** `uses` and `steps`, and nothing more. It deliberately does not reject a job declaring neither, because the spec's implicit rule says a job whose id is itself a registered template id means `uses: <that id>`, and `JobSpec` cannot know the template ids without importing the stage registry. That check lives in Task 5, where the registry is available.

Two pydantic 2.13.4 behaviours were executed against this checkout rather than assumed. A `FlowSpecError` raised inside either a `mode="before"` or a `mode="after"` model validator propagates **unwrapped**, because `FlowError` derives from `RuntimeError` and pydantic only wraps `ValueError` and `AssertionError` into a `ValidationError`. And `ConfigDict(extra="forbid")` on a model with an aliased field rejects the Python field name outright, so `FlowSpec(values=...)` raises `extra_forbidden` unless `populate_by_name=True` is also set.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_spec.py`:

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
import pytest

from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec, VariableSpec

pytestmark = pytest.mark.all


def test_a_job_reads_if_from_yaml_and_condition_from_python():
    from_yaml = JobSpec.model_validate({"uses": "lint", "if": "RUN_LINTER"})
    from_python = JobSpec(uses="lint", condition="RUN_LINTER")

    assert from_yaml.condition == "RUN_LINTER"
    assert from_python.condition == "RUN_LINTER"
    assert from_yaml == from_python


def test_a_job_reads_with_from_yaml_and_values_from_python():
    from_yaml = JobSpec.model_validate(
        {"uses": "floorplan", "with": {"FP_CORE_UTIL": 40}}
    )
    from_python = JobSpec(uses="floorplan", values={"FP_CORE_UTIL": 40})

    assert from_yaml.values == {"FP_CORE_UTIL": 40}
    assert from_yaml == from_python


def test_a_document_reads_with_from_yaml_and_values_from_python():
    from_yaml = FlowSpec.model_validate(
        {
            "name": "T",
            "with": {"FP_SIZING": "absolute"},
            "jobs": {"floorplan": {"uses": "floorplan"}},
        }
    )
    from_python = FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    assert from_yaml.values == {"FP_SIZING": "absolute"}
    assert from_yaml == from_python


def test_a_job_declaring_both_uses_and_steps_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "steps": ["Magic.DRC"]})

    assert "uses" in str(exc_info.value)
    assert "steps" in str(exc_info.value)


def test_an_unknown_job_key_is_rejected_naming_the_six_legal_keys():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "runs-on": "ubuntu-latest"})

    message = str(exc_info.value)
    assert "runs-on" in message
    for key in ("needs", "uses", "steps", "source", "if", "with"):
        assert key in message


def test_a_variable_spec_becomes_a_variable():
    variable = VariableSpec(
        name="RUN_LINTER",
        type="bool",
        description="Whether to run the linter.",
        default=True,
        deprecated_names=["RUN_LINT"],
    ).to_variable()

    assert variable.name == "RUN_LINTER"
    assert variable.type is bool
    assert variable.default is True
    assert variable.description == "Whether to run the linter."
    assert variable.deprecated_names == ["RUN_LINT"]


def test_an_unsupported_variable_type_is_rejected_naming_the_supported_set():
    with pytest.raises(FlowSpecError) as exc_info:
        VariableSpec(
            name="THINGS", type="list[str]", description="x"
        ).to_variable()

    message = str(exc_info.value)
    assert "list[str]" in message
    for name in ("bool", "int", "str", "Decimal", "Path"):
        assert name in message


def test_a_minimal_flow_spec_round_trips_from_a_mapping():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
            },
        }
    )

    assert spec.name == "Tiny"
    assert list(spec.jobs) == ["synthesis", "floorplan"]
    assert spec.jobs["floorplan"].needs == ["synthesis"]
    assert spec.jobs["synthesis"].needs == []
    assert spec.final is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.spec'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/spec.py`:

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
The workflow document: a flow declared as data rather than as a Python class.

A document names jobs and the edges between them. It deliberately says nothing
about what a job's steps require or provide, because that contract belongs with
the steps, in Python, next to the code it describes. A document is a graph over
a library, not a redefinition of one.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.config import Variable


class FlowSpecError(FlowError):
    """
    Raised when a workflow document is malformed. Every instance names the
    offending job or key and the legal alternatives, and is raised before a run
    directory is created.
    """


#: The scalar types a document may declare. Products are deliberately absent.
#: Across every shipped flow the only annotations in use are ``bool`` and the
#: engine-level ``TOOLS``, which no document declares.
_VARIABLE_TYPES: dict[str, type] = {
    "bool": bool,
    "int": int,
    "str": str,
    "Decimal": Decimal,
    "Path": Path,
}

_JOB_KEYS = ("needs", "uses", "steps", "source", "if", "with")

#: The Python field names behind the aliased job keys, accepted so that
#: ``JobSpec(condition=..., values=...)`` works from Python.
_JOB_FIELD_NAMES = ("condition", "values")


class VariableSpec(BaseModel):
    """A configuration variable declared by a document's ``config`` list."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    description: str
    default: Any = None
    deprecated_names: list[str] = []
    units: str | None = None

    def to_variable(self) -> Variable:
        """
        Returns
        -------
        The equivalent :class:`librelane.config.Variable`.

        Raises
        ------
        FlowSpecError
            If :attr:`type` is not a supported scalar.
        """
        resolved = _VARIABLE_TYPES.get(self.type)
        if resolved is None:
            raise FlowSpecError(
                f"Variable '{self.name}' declares type '{self.type}', which a "
                f"workflow document cannot express. Supported types: "
                f"{sorted(_VARIABLE_TYPES)}."
            )
        return Variable(
            self.name,
            resolved,
            self.description,
            default=self.default,
            deprecated_names=list(self.deprecated_names),
            units=self.units,
        )


class JobSpec(BaseModel):
    """One job of a workflow document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    needs: list[str] = []
    uses: str | None = None
    steps: list[str] | None = None
    #: A view id or metric name mapped to the direct predecessor it comes
    #: from. Keyed by a plain string because a metric name such as
    #: ``design__lvs_error__count`` is not a ``DesignFormat``, and the join
    #: rule is one rule for views and metrics alike.
    source: dict[str, str] = {}
    #: Values supplied for configuration variables read only by this job.
    #: Aliased to ``with``, which is a Python keyword.
    values: dict[str, Any] = Field(default_factory=dict, alias="with")
    condition: str | None = Field(default=None, alias="if")

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        legal = set(_JOB_KEYS) | set(_JOB_FIELD_NAMES)
        unknown = [key for key in data if key not in legal]
        if unknown:
            raise FlowSpecError(
                f"Job declares unknown key(s) {sorted(unknown)}. A job accepts "
                f"exactly {list(_JOB_KEYS)}."
            )
        return data

    @model_validator(mode="after")
    def _reject_both_implementations(self) -> "JobSpec":
        # A job declaring *neither* is not rejected here. The implicit rule
        # says a job whose id is a registered template id means that template,
        # and the template ids live in the stage registry, which this module
        # deliberately does not import. spec_validation.py catches it.
        if self.uses is not None and self.steps is not None:
            raise FlowSpecError(
                "A job declares 'uses' and 'steps' together. Use 'uses' to "
                "name a registered stage and provider, or 'steps' to list step "
                "IDs inline, but not both."
            )
        return self


class FlowSpec(BaseModel):
    """A complete workflow document."""

    # populate_by_name is required, not optional. With extra="forbid" and an
    # aliased field, pydantic 2.13.4 rejects the Python field name outright, so
    # FlowSpec(values=...) raises extra_forbidden without it.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: str = ""
    #: Values supplied for configuration variables. Layered between the PDK
    #: and the design configuration, so the design always wins. Aliased to
    #: ``with``, which is a Python keyword, exactly as ``condition`` is
    #: aliased to ``if``.
    values: dict[str, Any] = Field(default_factory=dict, alias="with")
    config: list[VariableSpec] = []
    jobs: dict[str, JobSpec]
    #: The job whose output state is the flow's final state. Absent, the final
    #: state is the join of the sink arcs, which phase 2 computes.
    final: str | None = None

    def edges(self) -> dict[str, list[str]]:
        """
        Returns
        -------
        The job dependency map in the form
        :mod:`librelane.flows.spec_graph` expects.
        """
        return {name: list(job.needs) for name, job in self.jobs.items()}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/spec.py test/flows/test_spec.py
git commit -m "feat: add the workflow document models"
```

---

### Task 3: Structural graph validation and the loader

**Files:**
- Modify: `librelane/flows/spec.py`
- Test: `test/flows/test_spec.py`

**Interfaces:**
- Consumes: `topological_order` from `librelane.flows.spec_graph` (Task 1); `FlowSpec`, `JobSpec`, `FlowSpecError` from Task 2.
- Produces: `load_flow_spec(source: Mapping[str, Any] | str | os.PathLike) -> FlowSpec`.

**Context the implementer needs:**

`librelane.config.loading.sources.read_source(source, *, yaml_loader=OpenLaneYAMLLoader) -> ConfigSource` already handles `.yaml`, `.yml`, `.json` and a plain mapping, and its `OpenLaneYAMLLoader` reads YAML floats as `Decimal` so values round-trip exactly. `ConfigSource` has fields `mapping`, `name` and `kind`. Use it rather than calling `yaml.load` directly; `librelane/stages/tools.py:127` is the existing precedent for reusing it outside `librelane.config`.

**`source` names a direct predecessor, not any ancestor.** This is a decision, recorded here because the alternative was live until it was measured. Phase 2's `join_states` sees only the tokens sitting on the job's own direct input arcs, one arc per entry in `needs`. A loader that accepted a transitive ancestor would therefore admit documents that load cleanly and crash the moment the join runs, because the named producer delivered no token on any arc the join can see. The alternative repair, loosening the runtime to tolerate a `source` entry that resolves to no token, means silently ignoring a declaration the author wrote on purpose, which is a fallback, and fallbacks are forbidden. So the loader is the half that tightens. `source` may only name a job listed in that job's own `needs`.

The three checks in this task need only the document. They belong on `FlowSpec` as an `after` model validator so that constructing a `FlowSpec` in Python raises the same errors as loading YAML.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_spec.py`:

```python
def test_a_needs_naming_an_undeclared_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {"needs": ["typo"], "uses": "floorplan"},
                },
            }
        )

    message = str(exc_info.value)
    assert "floorplan" in message
    assert "typo" in message
    assert "synthesis" in message


def test_a_cycle_is_rejected_naming_its_members():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "a": {"needs": ["b"], "uses": "synthesis"},
                    "b": {"needs": ["a"], "uses": "floorplan"},
                },
            }
        )

    message = str(exc_info.value)
    assert "cycle" in message.lower()
    assert "a" in message and "b" in message


def test_a_source_naming_an_unrelated_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "streamout": {"uses": "streamout/magic"},
                    "elsewhere": {"uses": "drc/klayout"},
                    "xor": {
                        "needs": ["streamout"],
                        "uses": "drc/magic",
                        "source": {"gds": "elsewhere"},
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "elsewhere" in message
    assert "streamout" in message


def test_a_source_naming_a_transitive_ancestor_is_rejected():
    """
    'streamout' is an ancestor of 'xor' but not one of its needs, so no token
    from 'streamout' ever lands on an arc the join at 'xor' can see. Accepting
    this at load would produce a document that crashes at run time.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "streamout": {"uses": "streamout/magic"},
                    "drc": {"needs": ["streamout"], "uses": "drc/magic"},
                    "xor": {
                        "needs": ["drc"],
                        "uses": "drc/klayout",
                        "source": {"gds": "streamout"},
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "streamout" in message
    assert "needs" in message
    assert "drc" in message


def test_load_flow_spec_reads_a_yaml_file(tmp_path):
    from librelane.flows.spec import load_flow_spec

    document = tmp_path / "tiny.yaml"
    document.write_text(
        "name: Tiny\n"
        "jobs:\n"
        "  synthesis:\n"
        "    uses: synthesis/yosys\n"
        "  floorplan:\n"
        "    needs: [synthesis]\n"
        "    uses: floorplan\n"
    )

    spec = load_flow_spec(document)

    assert spec.name == "Tiny"
    assert spec.jobs["floorplan"].needs == ["synthesis"]


def test_load_flow_spec_names_the_file_when_the_document_is_bad(tmp_path):
    from librelane.flows.spec import load_flow_spec

    document = tmp_path / "broken.yaml"
    document.write_text(
        "name: Broken\njobs:\n  floorplan:\n    needs: [typo]\n    uses: floorplan\n"
    )

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "broken.yaml" in str(exc_info.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: the six new tests FAIL. The first four fail because no validator rejects them, the last two with `ImportError: cannot import name 'load_flow_spec'`.

- [ ] **Step 3: Add the structural validator to `FlowSpec`**

In `librelane/flows/spec.py`, extend the imports:

```python
import graphlib
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.config import Variable
from librelane.config.loading.sources import read_source
from librelane.flows.spec_graph import topological_order
```

Add these methods to `FlowSpec`, after `edges`:

```python
    @model_validator(mode="after")
    def _check_structure(self) -> "FlowSpec":
        self._check_needs_are_declared()
        self._check_acyclic()
        self._check_sources_name_direct_predecessors()
        return self

    def _check_needs_are_declared(self) -> None:
        for name, job in self.jobs.items():
            for need in job.needs:
                if need not in self.jobs:
                    raise FlowSpecError(
                        f"Job '{name}' needs '{need}', which this flow does "
                        f"not declare. Declared jobs: {sorted(self.jobs)}."
                    )

    def _check_acyclic(self) -> None:
        try:
            topological_order(self.edges())
        except graphlib.CycleError as e:
            raise FlowSpecError(
                f"The jobs of flow '{self.name}' contain a cycle: "
                f"{' -> '.join(e.args[1])}. A flow document is acyclic."
            ) from None

    def _check_sources_name_direct_predecessors(self) -> None:
        # A transitive ancestor is not enough. The join at a job reads only the
        # tokens on that job's own input arcs, one per entry in 'needs', so a
        # 'source' naming anything else names a token that does not exist.
        for name, job in self.jobs.items():
            for key, producer in job.source.items():
                if producer not in job.needs:
                    raise FlowSpecError(
                        f"Job '{name}' sources '{key}' from '{producer}', "
                        f"which is not one of its needs. A 'source' may only "
                        f"name a direct predecessor, because the join reads "
                        f"only the tokens on this job's own input arcs. "
                        f"needs: {sorted(job.needs)}."
                    )
```

- [ ] **Step 4: Add the loader**

Append to `librelane/flows/spec.py`:

```python
def load_flow_spec(source: Mapping[str, Any] | str | os.PathLike) -> FlowSpec:
    """
    Reads a workflow document from a mapping, a YAML file or a JSON file.

    Parameters
    ----------
    source : Mapping[str, Any] | str | os.PathLike
        A mapping, or a path to a ``.yaml``, ``.yml`` or ``.json``
        file.

    Returns
    -------
    The validated document.

    Raises
    ------
    FlowSpecError
        If the document is malformed. The message names the
        source so a bad file in a directory of documents is identifiable.
    """
    read = read_source(source)
    try:
        return FlowSpec.model_validate(read.mapping)
    except FlowSpecError as e:
        raise FlowSpecError(f"In workflow document '{read.name}': {e}") from None
    except ValidationError as e:
        raise FlowSpecError(f"In workflow document '{read.name}': {e}") from None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: 14 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/spec.py test/flows/test_spec.py
git commit -m "feat: validate workflow document structure and load it from YAML"
```

---

### Task 4: Conditions, `final` and the reserved document keys

**Files:**
- Modify: `librelane/flows/spec.py`
- Test: `test/flows/test_spec.py`

**Interfaces:**
- Consumes: `FlowSpec`, `FlowSpecError` from Task 2.
- Produces: `parse_condition(text: str) -> tuple[str, ...]`, the variable names of a conjunction. `FlowSpec._check_structure` gains three checks.

**Context the implementer needs:**

`if` takes a conjunction, written `A` or `A and B and C`. It is not general expression evaluation, which is spec 3. Parsing it here rather than evaluating a Python expression at run time is what turns a malformed condition into a load error. Evaluation belongs to phase 2.

`parse_condition` is a **cross-phase interface**, not an internal helper. Phase 2's `resolve_jobs` calls it to build `Job.conditions: tuple[str, ...]`, and `Workflow._pass_through_reason` evaluates that tuple. The signature and the tuple return are therefore fixed, and there must be exactly one implementation of the grammar in the tree. A test below pins the return type for that reason.

The conjunction is what keeps the migration honest. `Checker.XOR` and `KLayout.XOR` gate today on `RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT and RUN_KLAYOUT_STREAMOUT`, because a gated producer fires as pass-through and deposits its input state unchanged, so `klayout_streamout` with its condition false carries no `klayout_gds` and `KLayout.XOR` requires `klayout_gds`. Gating `xor` on `RUN_KLAYOUT_XOR` alone would turn a cleanly skipped job into a missing-input crash. The load-time view check cannot catch that, because it reasons over declared contracts and the gated producer does declare the view.

Every name in a conjunction must be declared in the document's own `config` and must be of type `bool`. The `config` list is the right and sufficient place to look, on two pieces of evidence. `universal_flow_config_variables` contains 78 entries and **none of them is of type `bool`**, so no universal variable could ever be a legal condition. And the gating variables the migration carries over, `RUN_MAGIC_STREAMOUT` and `RUN_KLAYOUT_XOR` among them, are declared today on the flow class at `librelane/flows/classic.py:177` and `:195`, not by any step, and become the document's `config` entries in phase 4. Neither the step registry nor the universal set is consulted, so this stays a structural check.

`with` at the document level rejects `PDK`, `SCL`, `PAD` and `meta`. Those keys select the process before any other value is resolved, so a document setting `PDK` would override the `--pdk` argument rather than layer under it. The four are a literal tuple rather than something derived. Only `PDK` is in `universal_flow_config_variables`; `SCL`, `PAD` and `meta` are not configuration variables at all, so there is nothing to derive them from.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_spec.py`:

```python
_RUN_LINTER = {"name": "RUN_LINTER", "type": "bool", "description": "x"}
_RUN_XOR = {"name": "RUN_XOR", "type": "bool", "description": "x"}
_STRATEGY = {"name": "STRATEGY", "type": "str", "description": "x"}


def test_parse_condition_returns_a_tuple_of_conjuncts():
    """
    Phase 2's resolve_jobs assigns this straight to Job.conditions, which is a
    tuple, so the return type is a cross-phase contract rather than a detail.
    """
    from librelane.flows.spec import parse_condition

    assert parse_condition("RUN_LINTER") == ("RUN_LINTER",)
    assert parse_condition("A and B and C") == ("A", "B", "C")


def test_an_if_naming_an_undeclared_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_RUN_LINTER],
                "jobs": {"lint": {"uses": "lint/verilator", "if": "RUN_LINT"}},
            }
        )

    message = str(exc_info.value)
    assert "lint" in message
    assert "RUN_LINT" in message
    assert "RUN_LINTER" in message


def test_an_if_conjunction_of_declared_variables_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_RUN_LINTER, _RUN_XOR],
            "jobs": {
                "lint": {
                    "uses": "lint/verilator",
                    "if": "RUN_LINTER and RUN_XOR",
                }
            },
        }
    )

    assert spec.jobs["lint"].condition == "RUN_LINTER and RUN_XOR"


@pytest.mark.parametrize(
    "condition",
    ["RUN_LINTER or RUN_XOR", "not RUN_LINTER", "RUN_LINTER and", "", "and"],
)
def test_an_if_that_is_not_a_conjunction_is_rejected(condition):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_RUN_LINTER, _RUN_XOR],
                "jobs": {"lint": {"uses": "lint/verilator", "if": condition}},
            }
        )

    message = str(exc_info.value)
    assert "lint" in message
    assert "and" in message


def test_an_if_naming_a_non_boolean_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_STRATEGY],
                "jobs": {"lint": {"uses": "lint/verilator", "if": "STRATEGY"}},
            }
        )

    message = str(exc_info.value)
    assert "STRATEGY" in message
    assert "bool" in message


def test_a_final_naming_an_undeclared_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "final": "typo",
                "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
            }
        )

    message = str(exc_info.value)
    assert "typo" in message
    assert "synthesis" in message


def test_a_final_naming_a_declared_job_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "final": "synthesis",
            "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
        }
    )

    assert spec.final == "synthesis"


@pytest.mark.parametrize("key", ["PDK", "SCL", "PAD", "meta"])
def test_a_document_with_naming_a_process_selection_key_is_rejected(key):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "with": {key: "whatever"},
                "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
            }
        )

    message = str(exc_info.value)
    assert key in message
    assert "PDK" in message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: the new tests FAIL because nothing rejects them, except `test_a_final_naming_a_declared_job_is_accepted` which passes vacuously and `test_parse_condition_returns_a_tuple_of_conjuncts` and `test_an_if_conjunction_of_declared_variables_is_accepted`, which fail with `ImportError: cannot import name 'parse_condition'` and an unrejected condition respectively.

- [ ] **Step 3: Add the condition parser**

In `librelane/flows/spec.py`, add `import re` to the imports, and add the module-level constants next to `_JOB_KEYS`:

```python
#: Keys a document-level ``with`` may never set. They select the process before
#: any other value is resolved, so a document setting one would override the
#: command-line argument rather than layer under it. A literal tuple rather
#: than a derived set: only ``PDK`` is a configuration variable at all.
_RESERVED_VALUE_KEYS = ("PDK", "SCL", "PAD", "meta")

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
```

Add the parser as a module-level function, above `class VariableSpec`:

```python
def parse_condition(text: str) -> tuple[str, ...]:
    """
    Parses a job's ``if`` into the variable names it conjoins.

    The grammar is one or more variable names separated by the literal
    ``and``. General expressions are deliberately out of scope; they are
    spec 3.

    Phase 2 calls this to build ``Job.conditions``, so the return is a tuple
    and this is the only implementation of the grammar. Do not write a second
    one there.

    Parameters
    ----------
    text : str
        The raw ``if`` string.

    Returns
    -------
    The conjoined variable names, in order.

    Raises
    ------
    FlowSpecError
        If ``text`` is not a bare conjunction.
    """
    tokens = text.split()
    names = tokens[0::2]
    joiners = tokens[1::2]
    malformed = (
        len(names) == 0
        or len(joiners) != len(names) - 1
        or any(joiner != "and" for joiner in joiners)
        or any(
            _IDENTIFIER.match(name) is None or name == "and" for name in names
        )
    )
    if malformed:
        raise FlowSpecError(
            f"Condition '{text}' is not a conjunction. An 'if' is one or "
            f"more configuration variable names joined by the literal 'and', "
            f"for example 'A' or 'A and B and C'."
        )
    return tuple(names)
```

- [ ] **Step 4: Add the three checks**

Extend `FlowSpec._check_structure` to call them:

```python
    @model_validator(mode="after")
    def _check_structure(self) -> "FlowSpec":
        self._check_needs_are_declared()
        self._check_acyclic()
        self._check_sources_name_direct_predecessors()
        self._check_conditions_are_declared_booleans()
        self._check_final_names_a_job()
        self._check_values_are_not_reserved()
        return self
```

Add the three methods:

```python
    def _check_conditions_are_declared_booleans(self) -> None:
        declared = {variable.name: variable for variable in self.config}
        for name, job in self.jobs.items():
            if job.condition is None:
                continue
            try:
                variables = parse_condition(job.condition)
            except FlowSpecError as e:
                raise FlowSpecError(f"Job '{name}': {e}") from None
            for variable_name in variables:
                variable = declared.get(variable_name)
                if variable is None:
                    raise FlowSpecError(
                        f"Job '{name}' is conditional on '{variable_name}', "
                        f"which flow '{self.name}' does not declare. Declared "
                        f"variables: {sorted(declared)}."
                    )
                if variable.type != "bool":
                    raise FlowSpecError(
                        f"Job '{name}' is conditional on '{variable_name}', "
                        f"which flow '{self.name}' declares with type "
                        f"'{variable.type}'. An 'if' conjoins variables of "
                        f"type 'bool'."
                    )

    def _check_final_names_a_job(self) -> None:
        if self.final is None:
            return
        if self.final not in self.jobs:
            raise FlowSpecError(
                f"Flow '{self.name}' declares final job '{self.final}', which "
                f"it does not declare. Declared jobs: {sorted(self.jobs)}."
            )

    def _check_values_are_not_reserved(self) -> None:
        for key in self.values:
            if key in _RESERVED_VALUE_KEYS:
                raise FlowSpecError(
                    f"Flow '{self.name}' sets '{key}' in its 'with' block. "
                    f"{list(_RESERVED_VALUE_KEYS)} select the process before "
                    f"any other value is resolved, so a document setting one "
                    f"would override the command line rather than layer under "
                    f"it. Set it on the design or on the command line."
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec.py -v`
Expected: 29 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/spec.py test/flows/test_spec.py
git commit -m "feat: validate workflow document conditions, final and reserved keys"
```

---

### Task 5: Registry-backed name resolution

**Files:**
- Create: `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_validation.py`

**Interfaces:**
- Consumes: `FlowSpec`, `JobSpec`, `FlowSpecError` from Task 2.
- Produces: `validate_against_registry(spec: FlowSpec) -> None`, raising `FlowSpecError`. Internally `_resolved_uses(job_id, job) -> str | None`, consumed by Tasks 6 and 7.

**Context the implementer needs:**

Three registries are involved, all process-wide singletons populated by import side effect.

- `Stage.factory.get(id) -> Stage | None` and `Stage.factory.list() -> list[str]`, from `librelane.stages`. 27 ids, listed in `librelane/stages/taxonomy.py`.
- `StageRegistry.providers(stage: str) -> list[str]`, at `librelane/stages/registry.py:219`, returning every provider registered for a stage in registration order. It already exists. Do not add one, and do not reach into the name-mangled `_by_stage_and_provider`.
- `Step.factory.get(name) -> type[Step] | None` and `Step.factory.list() -> list[str]`, at `librelane/steps/step/factory.py:81` and `:93`. Lookup is case-insensitive; `list()` returns the canonical-cased IDs.

`uses` is `"<stage>"` or `"<stage>/<provider>"`. A bare stage means that stage's default provider, which is `Stage.default_providers`, a tuple that is empty when the stage is unselected by default.

**The implicit `uses` rule.** A job with no `uses` and no `steps` whose id is itself a registered template id means `uses: <that id>`. This is why a Classic document writes `floorplan:` with nothing under it. The rule is unambiguous because template ids are a closed set of 27 known at load. A job declaring neither, whose id names no template, is a load error, and the message says which of the two keys it needs. `_resolved_uses` is the one place that rule is applied, and Tasks 6 and 7 both go through it.

Because these are process-wide singletons, the tests import `librelane.steps` at module scope to populate them, the way `test/stages/test_registry.py` does. Do not try to isolate them per test.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_spec_validation.py`:

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
import pytest

import librelane.steps  # noqa: F401  populates Step.factory and StageRegistry

from librelane.flows.spec import FlowSpec, FlowSpecError
from librelane.flows.spec_validation import validate_against_registry

pytestmark = pytest.mark.all


def _spec(jobs: dict, **extra) -> FlowSpec:
    return FlowSpec.model_validate({"name": "Tiny", "jobs": jobs, **extra})


def test_a_valid_document_passes():
    validate_against_registry(
        _spec(
            {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
            }
        )
    )


def test_an_unregistered_stage_is_rejected_naming_the_registered_ones():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"nope": {"uses": "not_a_stage"}}))

    message = str(exc_info.value)
    assert "not_a_stage" in message
    assert "synthesis" in message


def test_an_unregistered_provider_is_rejected_naming_the_stage_s_providers():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"synthesis": {"uses": "synthesis/not_a_tool"}})
        )

    message = str(exc_info.value)
    assert "not_a_tool" in message
    assert "yosys" in message


def test_a_uses_with_too_many_slashes_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"synthesis": {"uses": "synthesis/yosys/extra"}})
        )

    assert "synthesis/yosys/extra" in str(exc_info.value)


def test_an_unregistered_step_id_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"custom": {"steps": ["Odb.NotAStep"]}})
        )

    assert "Odb.NotAStep" in str(exc_info.value)


def test_a_registered_step_id_is_accepted_case_insensitively():
    validate_against_registry(
        _spec({"custom": {"steps": ["odb.setpowerconnections"]}})
    )


def test_a_job_whose_id_is_a_template_id_needs_no_uses():
    """
    'floorplan' is one of the 27 registered template ids, so an empty job body
    under that key means 'uses: floorplan'.
    """
    validate_against_registry(_spec({"floorplan": {}}))


def test_a_job_with_no_uses_no_steps_and_no_template_id_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"not_a_template": {}}))

    message = str(exc_info.value)
    assert "not_a_template" in message
    assert "uses" in message
    assert "steps" in message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.spec_validation'`

- [ ] **Step 3: Write the validation module**

Create `librelane/flows/spec_validation.py`:

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
The workflow document checks that need a populated registry.

Kept apart from :mod:`librelane.flows.spec` so the document models stay
testable without importing the step and stage packages, whose registries are
process-wide singletons populated by import side effect.
"""

from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec
from librelane.stages import Stage, StageRegistry
from librelane.steps import Step


def validate_against_registry(spec: FlowSpec) -> None:
    """
    Checks every name a document borrows from a registry.

    Parameters
    ----------
    spec : FlowSpec
        A structurally valid document.

    Raises
    ------
    FlowSpecError
        If a stage, provider or step ID does not resolve.
        The message names the legal alternatives.
    """
    for name, job in spec.jobs.items():
        if job.steps is not None:
            _check_steps(name, job.steps)
        else:
            _check_uses(name, _require_implementation(name, job))


def _resolved_uses(job_id: str, job: JobSpec) -> str | None:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ``stage`` or ``stage/provider`` string this job resolves to, or
    ``None`` for an inline ``steps`` job. An omitted ``uses`` resolves to the
    job id, which :func:`_require_implementation` has already confirmed names a
    registered template.
    """
    if job.steps is not None:
        return None
    if job.uses is not None:
        return job.uses
    return job_id


def _require_implementation(job_id: str, job: JobSpec) -> str:
    if job.uses is not None:
        return job.uses
    if Stage.factory.get(job_id) is None:
        raise FlowSpecError(
            f"Job '{job_id}' declares neither 'uses' nor 'steps', and its id "
            f"is not a registered template id, so there is nothing to run. "
            f"Add 'uses' to name a registered stage and provider, or 'steps' "
            f"to list step IDs inline. Registered template ids: "
            f"{sorted(Stage.factory.list())}."
        )
    return job_id


def _check_uses(job: str, uses: str) -> None:
    parts = uses.split("/")
    if len(parts) > 2:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', which is not a stage id or "
            f"a 'stage/provider' pair."
        )
    stage_id = parts[0]
    stage = Stage.factory.get(stage_id)
    if stage is None:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', but no stage with id "
            f"'{stage_id}' is registered. Registered stages: "
            f"{sorted(Stage.factory.list())}."
        )
    if len(parts) == 1:
        if not stage.default_providers:
            raise FlowSpecError(
                f"Job '{job}' declares uses '{uses}', but stage '{stage_id}' "
                f"has no default provider, so the document must name one. "
                f"Available: {StageRegistry.providers(stage_id)}."
            )
        return
    provider = parts[1]
    available = StageRegistry.providers(stage_id)
    if provider not in available:
        raise FlowSpecError(
            f"Job '{job}' declares uses '{uses}', but no provider "
            f"'{provider}' is registered for stage '{stage_id}'. Available: "
            f"{available}."
        )


def _check_steps(job: str, steps: list[str]) -> None:
    for step_id in steps:
        if Step.factory.get(step_id) is None:
            raise FlowSpecError(
                f"Job '{job}' lists step '{step_id}', which is not a "
                f"registered step ID."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/spec_validation.py test/flows/test_spec_validation.py
git commit -m "feat: resolve workflow document names against the registries"
```

---

### Task 6: The view and metric contract checks

**Files:**
- Modify: `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_validation.py`

**Interfaces:**
- Consumes: `validate_against_registry`, `_resolved_uses` from Task 5; `ancestors`, `descendants` from Task 1.
- Produces: no new public names. `validate_against_registry` gains four checks. Internally `_produced_views(job_id, job) -> set[str]` and `_produced_keys(job_id, job) -> set[str]`, consumed by Task 7.

**Context the implementer needs:**

Everything in this task works in **string space**. A view is its id, `"gds"`, and a metric is its name, `"design__lvs_error__count"`. That is not a convenience. The spec states one join rule for views and for metrics, and `source` keys both, so the two have to live in one set. `str(view)` is a `DesignFormat`'s id; there is no `DesignFormat.by_id`.

Each job's produced **views** come from two places. For a `uses` job they are `Stage.provides` union `Registration.provides`, where the registration comes from `StageRegistry.get(stage, provider) -> Registration | None` at `librelane/stages/registry.py:215`. That method already exists; do not add one, and do not reach into the name-mangled `_by_stage_and_provider`. For a `steps` job they are the union of each step class's `outputs`, declared at `librelane/steps/step/core.py:199` as `ClassVar[list[DesignFormat]]`.

Each job's produced **metrics** come from the same two places, `Stage.metrics` at `librelane/stages/stage.py:104` and `Registration.metrics` at `librelane/stages/registry.py:72`. **Metrics are statically declared and this check therefore covers them.** Running the registries in this checkout, 6 of the 27 stages declare metrics and 3 registrations declare metrics beyond their stage's, for 15 distinct names, every one of which is present in `Metric.by_name`. A step class carries no metric declaration, so an inline `steps` job contributes no statically known metrics, and that is a real gap rather than an omission. It is the same gap `StagedFlow` has today, where `staged.py:109` describes a span as carrying "the `provides` and `metrics` of the providers actually selected". Phase 2's runtime `JobContractError` is the backstop for a metric that only a step knows about.

Consumed views are `Stage.requires` for a `uses` job, and the union of each step's `inputs` for a `steps` job. Nothing declares consumed metrics, so requirement reachability is over views only.

A `source` key resolves against **two** global registries. `DesignFormat.factory.get(id) -> DesignFormat | None` for a view, and membership in `Metric.by_name`, a `ClassVar[dict[str, Metric]]` at `librelane/common/metrics/metric.py:127` holding 68 entries once `librelane.steps` is imported. Every metric any stage or registration declares is in it, verified. A key in neither is an error naming both alternatives. `DesignFormat.factory.list()` returns 46 entries of which 23 are distinct, so de-duplicate before printing it.

The four checks:

**Source deliverability.** A `source` entry names a direct predecessor, checked in Task 3. That predecessor's branch, meaning the predecessor plus its own ancestors, must actually produce the key. A predecessor's token carries everything its whole branch produced, so a view the predecessor inherited rather than wrote is legitimate. A key nothing in that branch produces is not, and admitting it would mean phase 2's join looking for a value that is not there. This is the second half of the same decision as `source` naming a direct predecessor.

**Reachability.** Every view a job requires must be produced by some ancestor, or be in the document's implicit initial state. The initial state is not knowable at load time, so the check is scoped to views that some **other job that is not a descendant** of this one produces.

Both exclusions are load-bearing and both were measured.

Excluding the job's own `provides` is essential. 14 of the 27 stages both require and provide the same views, the `PNR_IN_PLACE` contract of `def`/`nl`/`sdc`, which is the identity that made this whole design necessary. `Stage.floorplan` is not one of those 14, because it requires `(nl,)` and provides `(def, nl, sdc)`, but it overlaps them on `nl` and breaks in exactly the same way. If a job's own output counted as evidence that a view is producible, every job whose `provides` intersects its own `requires` would be rejected whenever no ancestor happened to restate the view, which is the common case at the head of a document.

Excluding **descendants** is equally essential and is the less obvious half. A descendant producing a view is no evidence at all that an ancestor can obtain it, because state flows forward only. Without the exclusion, this four-job document is rejected, verified against the real registries:

```yaml
jobs:
  floorplan: {}
  global_placement: {needs: [floorplan]}
  cts: {needs: [global_placement]}
  detailed_placement: {needs: [cts]}
```

`floorplan` requires `nl`, and after the taxonomy fix recorded above it requires nothing else. It has no ancestors here, so `nl` is meant to arrive in the initial state. But `global_placement`, `cts` and `detailed_placement` are all `PNR_IN_PLACE` stages that provide `nl`, and all three are descendants of `floorplan`. Without the descendant exclusion, "some other job produces it" is true three times over, `floorplan` is rejected for `nl`, and the document fails to load. That kills exactly the mid-flow document `--with-initial-state` exists to run. One view carries the whole argument because one rejected view is enough to fail the load, and `nl` is the only view `floorplan` requires. Scoping `elsewhere` to non-descendants makes the document load, and the genuine unreachable case below still raises.

Neither exclusion is a fallback. A view no non-descendant job produces is assumed to come from the initial state, and phase 2's state check catches it if it does not. Three tests below pin all three halves of the scoping.

**Fan-in conflict.** For each job, for each pair of its direct predecessors that are not each other's ancestors, any key both of their subgraphs produce is ambiguous unless `source` names one. "Both subgraphs produce" means the key appears in the produced set of the predecessor or any of its ancestors, restricted to jobs not shared between the two branches. A shared ancestor's key is identical down both branches and is not a conflict.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_spec_validation.py`:

```python
def test_a_fan_in_conflict_is_rejected_naming_both_producers():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                    "xor": {
                        "needs": ["magic_streamout", "klayout_streamout"],
                        "uses": "drc/magic",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "source" in message


def test_a_declared_source_resolves_the_fan_in_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "magic_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/magic",
                },
                "klayout_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/klayout",
                },
                "xor": {
                    "needs": ["magic_streamout", "klayout_streamout"],
                    "uses": "drc/magic",
                    "source": {"gds": "klayout_streamout"},
                },
            }
        )
    )


def test_a_view_from_a_shared_ancestor_is_not_a_conflict():
    """
    'floorplan' provides def, nl and sdc down both branches identically. Were
    the shared subgraph not subtracted, this document would be rejected three
    times over.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "magic_drc": {"needs": ["floorplan"], "uses": "drc/klayout"},
                "lvs": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "join": {"needs": ["magic_drc", "lvs"], "uses": "drc/klayout"},
            }
        )
    )


def test_a_metric_fan_in_conflict_is_rejected_naming_both_producers():
    """
    Two lvs/netgen jobs each declare design__lvs_error__count from the stage
    and magic__illegal_overlap__count from the registration. The join rule is
    the same one views get.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "lvs_a": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                    "lvs_b": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                    "join": {
                        "needs": ["lvs_a", "lvs_b"],
                        "steps": ["Odb.SetPowerConnections"],
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "join" in message
    assert "lvs_a" in message
    assert "lvs_b" in message
    assert "design__lvs_error__count" in message


def test_a_declared_source_resolves_a_metric_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "lvs_a": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "lvs_b": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "join": {
                    "needs": ["lvs_a", "lvs_b"],
                    "steps": ["Odb.SetPowerConnections"],
                    "source": {
                        "design__lvs_error__count": "lvs_a",
                        "magic__illegal_overlap__count": "lvs_a",
                    },
                },
            }
        )
    )


def test_a_required_view_no_ancestor_produces_is_rejected():
    """
    'streamout' produces gds but is not an ancestor of 'drc', so gds is
    producible by the document yet unreachable from drc. 'streamout' needs
    'synthesis' only so that its own def/nl/sdc requirement is not the first
    thing to raise. A view no job at all produces is a different case, pinned
    below.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "streamout": {
                        "needs": ["synthesis"],
                        "uses": "streamout/magic",
                    },
                    "drc": {"needs": ["synthesis"], "uses": "drc/klayout"},
                }
            )
        )

    message = str(exc_info.value)
    assert "drc" in message
    assert "gds" in message


def test_a_descendant_producing_a_view_is_not_evidence_for_its_ancestor():
    """
    'floorplan' requires nl, and takes it from the initial state. Its three
    PNR_IN_PLACE descendants each provide nl as well, and none of them can hand
    anything back to their own ancestor, so none of them is evidence. Drop the
    descendant exclusion and this document is rejected for nl.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {},
                "global_placement": {"needs": ["floorplan"]},
                "cts": {"needs": ["global_placement"]},
                "detailed_placement": {"needs": ["cts"]},
            }
        )
    )


def test_a_source_key_that_is_neither_a_view_nor_a_metric_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                    "xor": {
                        "needs": ["magic_streamout", "klayout_streamout"],
                        "uses": "drc/magic",
                        "source": {"not_a_key": "klayout_streamout"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "not_a_key" in message
    assert "view" in message
    assert "metric" in message


def test_a_source_naming_a_predecessor_that_cannot_deliver_the_key_is_rejected():
    """
    'cts' is a legal direct predecessor but its whole branch provides only
    def, nl and sdc, so no gds token ever arrives from it.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "cts": {"needs": ["floorplan"], "uses": "cts/openroad"},
                    "join": {
                        "needs": ["magic_streamout", "cts"],
                        "uses": "drc/magic",
                        "source": {"gds": "cts"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "join" in message
    assert "cts" in message
    assert "gds" in message


def test_a_view_no_job_produces_is_left_to_the_initial_state():
    """
    A view that no job in the document produces is assumed to arrive in the
    initial state, and is checked at run time rather than at load time. This
    is what lets a document start mid-flow from '--with-initial-state'.
    """
    validate_against_registry(_spec({"drc": {"uses": "drc/magic"}}))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: `test_a_fan_in_conflict_is_rejected_naming_both_producers`, `test_a_metric_fan_in_conflict_is_rejected_naming_both_producers`, `test_a_required_view_no_ancestor_produces_is_rejected`, `test_a_source_key_that_is_neither_a_view_nor_a_metric_is_rejected` and `test_a_source_naming_a_predecessor_that_cannot_deliver_the_key_is_rejected` FAIL because nothing raises. The other five pass vacuously.

- [ ] **Step 3: Add the produced-key helpers**

In `librelane/flows/spec_validation.py`, extend the imports:

```python
from librelane.common.metrics import Metric
from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec
from librelane.flows.spec_graph import ancestors, descendants
from librelane.stages import Stage, StageRegistry
from librelane.state import DesignFormat
from librelane.steps import Step
```

Append these helpers:

```python
def _providers_of(uses: str) -> tuple[str, tuple[str, ...]]:
    stage_id, _, provider = uses.partition("/")
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    if provider:
        return stage_id, (provider,)
    # A bare 'uses' means the stage's default provider, which is a tuple for a
    # multi_provider stage. Every one of them, rather than the first, which
    # would silently drop the rest.
    return stage_id, tuple(stage.default_providers)


def _produced_views(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ids of every view this job declares it produces.
    """
    views: set[str] = set()
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            views.update(str(view) for view in step.outputs)
        return views
    stage_id, providers = _providers_of(uses)
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    views.update(str(view) for view in stage.provides)
    for each in providers:
        registration = StageRegistry.get(stage_id, each)
        if registration is not None:
            views.update(str(view) for view in registration.provides)
    return views


def _produced_metrics(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The names of every metric this job declares it produces. An inline
    ``steps`` job declares none, because a step class carries no metric
    declaration. Phase 2's runtime contract check is what covers those.
    """
    uses = _resolved_uses(job_id, job)
    if uses is None:
        return set()
    stage_id, providers = _providers_of(uses)
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    metrics = set(stage.metrics)
    for each in providers:
        registration = StageRegistry.get(stage_id, each)
        if registration is not None:
            metrics.update(registration.metrics)
    return metrics


def _produced_keys(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    Every view id and metric name this job declares, in one set, because the
    join rule and ``source`` treat the two alike.
    """
    return _produced_views(job_id, job) | _produced_metrics(job_id, job)


def _consumed_views(job_id: str, job: JobSpec) -> set[str]:
    """
    Parameters
    ----------
    job_id : str
        The document's key for this job.
    job : JobSpec
        The job.

    Returns
    -------
    The ids of every view this job requires. Nothing declares a consumed
    metric, so there is no metric equivalent.
    """
    views: set[str] = set()
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            views.update(str(view) for view in step.inputs)
        return views
    stage = Stage.factory.get(uses.split("/")[0])
    assert stage is not None, "checked by _check_uses"
    return {str(view) for view in stage.requires}


def _union(table: dict[str, set[str]], names: set[str]) -> set[str]:
    result: set[str] = set()
    for name in names:
        result.update(table[name])
    return result


def _pairs(items: list[str]):
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            yield first, second
```

- [ ] **Step 4: Add the four checks**

Extend `validate_against_registry` to call them after the existing loop:

```python
    _check_source_keys_resolve(spec)
    views = {name: _produced_views(name, job) for name, job in spec.jobs.items()}
    keys = {name: _produced_keys(name, job) for name, job in spec.jobs.items()}
    _check_sources_can_deliver(spec, keys)
    _check_requirements_are_reachable(spec, views)
    _check_fan_in_is_unambiguous(spec, keys)
```

Append the checks. `_check_source_keys_resolve` comes first, because the three that follow compare against `source` keys and must not do so with an unresolvable one:

```python
def _check_source_keys_resolve(spec: FlowSpec) -> None:
    for name, job in spec.jobs.items():
        for key in job.source:
            if DesignFormat.factory.get(key) is not None:
                continue
            if key in Metric.by_name:
                continue
            raise FlowSpecError(
                f"Job '{name}' sources '{key}', which is neither a registered "
                f"view nor a registered metric. Registered views: "
                f"{sorted(set(DesignFormat.factory.list()))}. Registered "
                f"metrics: {sorted(Metric.by_name)}."
            )


def _check_sources_can_deliver(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        for key, producer in job.source.items():
            # 'producer' is one of this job's needs, checked structurally. Its
            # token carries everything its whole branch produced, so a key it
            # inherited counts, but a key nothing in the branch wrote does not.
            branch = {producer} | ancestors(edges, producer)
            if key in _union(keys, branch):
                continue
            raise FlowSpecError(
                f"Job '{name}' sources '{key}' from '{producer}', but neither "
                f"'{producer}' nor any of its predecessors produces it, so no "
                f"such value ever arrives. '{producer}' and its predecessors "
                f"produce: {sorted(_union(keys, branch))}."
            )


def _check_requirements_are_reachable(
    spec: FlowSpec,
    views: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        predecessors = ancestors(edges, name)
        available = _union(views, predecessors)
        # Views produced somewhere this job could actually have inherited from.
        # Two exclusions, both load-bearing.
        #
        # The job itself, because 14 of the 27 stages both require and provide
        # the same views (the PNR_IN_PLACE contract, def/nl/sdc), so counting a
        # job's own output as evidence would reject every one of them whenever
        # no ancestor happens to restate the view.
        #
        # And this job's descendants, because state flows forward only. A
        # downstream PNR_IN_PLACE job providing nl says nothing about whether
        # an upstream job can obtain nl, and counting it rejects every document
        # that starts mid-flow.
        successors = descendants(edges, name)
        elsewhere = _union(
            views,
            {other for other in spec.jobs if other != name and other not in successors},
        )
        for view in sorted(_consumed_views(name, job) - available):
            # A view nothing upstream-eligible produces is presumed to arrive
            # in the initial state, and is checked at run time against the real
            # state.
            if view not in elsewhere:
                continue
            raise FlowSpecError(
                f"Job '{name}' requires view '{view}', which none of its "
                f"predecessors produce. Predecessors: {sorted(predecessors)}."
            )


def _check_fan_in_is_unambiguous(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        if len(job.needs) < 2:
            continue
        branches = {need: ({need} | ancestors(edges, need)) for need in job.needs}
        for first, second in _pairs(job.needs):
            if second in branches[first] or first in branches[second]:
                continue
            shared = branches[first] & branches[second]
            first_keys = _union(keys, branches[first] - shared)
            second_keys = _union(keys, branches[second] - shared)
            for key in sorted(first_keys & second_keys):
                if key in job.source:
                    continue
                raise FlowSpecError(
                    f"Job '{name}' joins '{first}' and '{second}', which both "
                    f"produce '{key}'. Declare which one it comes from with "
                    f"'source: {{{key}: {first}}}' or "
                    f"'source: {{{key}: {second}}}'."
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: 18 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/spec_validation.py test/flows/test_spec_validation.py
git commit -m "feat: check workflow document view and metric contracts at load time"
```

---

### Task 7: Per-job values and the sink join

**Files:**
- Modify: `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_validation.py`

**Interfaces:**
- Consumes: `_resolved_uses` from Task 5; `_produced_keys`, `_union`, `_pairs` from Task 6; `ancestors` from Task 1.
- Produces: no new public names. `validate_against_registry` gains two checks.

**Context the implementer needs:**

**Per-job `with` is a covering condition, not a count.** A variable may appear in a job's `with` block only if **every job that reads it also sets it**. Equivalently, the set of jobs naming a variable across their `with` blocks must equal that variable's reach exactly, no more and no fewer.

Reach is the set of jobs that can read a variable. It is derived, not declared, from two sources. A variable in `universal_flow_config_variables`, re-exported from `flow_common_variables` at `librelane/config/__init__.py:43` and defined at `librelane/config/flow.py:511`, sits in every step's filtered configuration and is therefore read by every job. Otherwise a variable is read by the jobs whose steps declare it in `Step.config_vars`, at `librelane/steps/step/core.py:201`.

A job's steps are statically knowable, which is what makes this checkable at load. For an inline job they are `job.steps`. For a template job they are `Registration.steps`, a `tuple[type[Step], ...]` at `librelane/stages/registry.py:69`, for each selected provider.

The rule exists because reach is derived rather than declared, which is what makes a partial override invisible. `DIE_AREA` is the worked example. It is universal **and** additionally declared by `Magic.StreamOut`, so a `with` block setting it on `floorplan` alone would floorplan one die while the sealring is drawn around another, silently and with no error anywhere. Requiring every reader to set it turns that silent divergence into a load error naming the jobs that were left out.

**Why a covering condition and not reach one.** An earlier draft restricted `with` to variables of reach one, and that draft rejected the case it was written to serve. Measured in this checkout, a document with two `synthesis/yosys` jobs gives

```
reach(SYNTH_STRATEGY) = ['synth_a', 'synth_b']
```

because `Yosys.Synthesis` appears in both jobs. Reach two, so under reach one **neither** job could set it, and the two-jobs-of-one-stage case the key exists for was the one thing it could not express. `SYNTH_STRATEGY` being declared by `Yosys.Synthesis` alone is a count of declaring steps, and only a count of jobs governs what a job observes. The two measurements are different and the covering condition uses the second. Two Yosys jobs that both set `SYNTH_STRATEGY` now load; a document where only one of them sets it does not.

The same rule covers a matrix with no special case, when spec 3 adds one. An expansion sets its axis on exactly the jobs it generates, so the setters are its reach by construction.

Because the condition is over a variable rather than over a job, this is a **whole-document** check keyed by variable name, not a per-job loop. It has two failure modes and each gets its own message. A reader that does not set it, which is the `DIE_AREA` hazard. And a setter that is not a reader, for instance `SYNTH_STRATEGY` set on `floorplan`, whose value could never take effect. Silently ignoring the second would be a fallback.

**The sink join.** Every job no other job depends on gets its own sink arc, and the flow's final state is the join of the tokens on those arcs under the same rule every other fan-in uses. The sink is not a job, so no job's `source` can resolve a conflict there. `final` names the job whose state is returned instead. A document whose sink join conflicts and which declares no `final` is a load error naming the conflicting keys and the leaf jobs. When `final` is present the sinks are not joined at all, so the check does not run.

One limit of the static form, stated rather than left to be discovered. Under the migrated Classic the sinks are `magic_drc` and `xor`, and running the real registries over that shape finds **no** static conflict, because `magic_drc` inherits `gds` from the shared `magic_streamout` ancestor rather than declaring it. The runtime conflict the spec describes there is a conflict of *values*, two different GDSII files under one key, which no declared contract can express. Phase 2's join is what catches it. The static check catches the declared case, which is the two-sink document below.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_spec_validation.py`:

```python
def test_a_with_on_the_only_reader_is_accepted():
    """
    FP_CORE_UTIL is declared by OpenROAD.Floorplan, OpenROAD.GlobalPlacement
    and OpenROAD.GlobalPlacementSkipIO. This document has only the first, so
    its reach here is the single job 'floorplan', which sets it. Covered.
    """
    validate_against_registry(
        _spec({"floorplan": {"with": {"FP_CORE_UTIL": 40}}})
    )


def test_a_with_set_by_every_reader_of_the_variable_is_accepted():
    """
    Two jobs of one stage with different values, which is the case this key
    exists for. Both run Yosys.Synthesis so both read SYNTH_STRATEGY, and both
    set it, so no reader is left observing a value it did not declare.
    """
    validate_against_registry(
        _spec(
            {
                "synth_a": {
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "AREA 0"},
                },
                "synth_b": {
                    "needs": ["synth_a"],
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "DELAY 0"},
                },
            }
        )
    )


def test_a_with_set_by_only_some_readers_is_rejected():
    """The same document with one of the two readers left uncovered."""
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synth_a": {
                        "uses": "synthesis/yosys",
                        "with": {"SYNTH_STRATEGY": "AREA 0"},
                    },
                    "synth_b": {
                        "needs": ["synth_a"],
                        "uses": "synthesis/yosys",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "SYNTH_STRATEGY" in message
    assert "synth_a" in message
    assert "synth_b" in message


def test_a_with_naming_a_universal_variable_is_rejected():
    """
    DIE_AREA is in flow_common_variables, so every job reads it. Setting it on
    'floorplan' alone would floorplan one die and leave every other job
    reading a different one.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {
                        "needs": ["synthesis"],
                        "with": {"DIE_AREA": "0 0 100 100"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "DIE_AREA" in message
    assert "synthesis" in message


def test_a_with_naming_a_variable_the_setting_job_cannot_read_is_rejected():
    """
    'floorplan' runs no step that declares SYNTH_STRATEGY, so the entry could
    never take effect, and 'synthesis' reads it without setting it.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {
                        "needs": ["synthesis"],
                        "with": {"SYNTH_STRATEGY": "AREA 0"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "SYNTH_STRATEGY" in message
    assert "floorplan" in message
    assert "synthesis" in message


def test_a_with_naming_a_variable_no_job_reads_is_rejected():
    """
    Reach is empty and the setter set is not, so the two are unequal. This is
    the second failure mode, a value that could never take effect.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"floorplan": {"with": {"NOT_A_VARIABLE": 1}}})
        )

    message = str(exc_info.value)
    assert "NOT_A_VARIABLE" in message
    assert "floorplan" in message


def test_a_conflicting_sink_join_with_no_final_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "final" in message


def test_a_final_resolves_the_sink_join_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {},
                "magic_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/magic",
                },
                "klayout_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/klayout",
                },
            },
            final="klayout_streamout",
        )
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: the five rejection tests FAIL because nothing raises. The three positive cases pass vacuously.

- [ ] **Step 3: Add the reach helper and the two checks**

In `librelane/flows/spec_validation.py`, extend the imports:

```python
from librelane.config import universal_flow_config_variables
```

Append the helper and the checks:

```python
def _steps_of(job_id: str, job: JobSpec) -> list[type[Step]]:
    resolved: list[type[Step]] = []
    uses = _resolved_uses(job_id, job)
    if uses is None:
        assert job.steps is not None
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            resolved.append(step)
        return resolved
    stage_id, providers = _providers_of(uses)
    for each in providers:
        registration = StageRegistry.get(stage_id, each)
        if registration is not None:
            resolved.extend(registration.steps)
    return resolved


def _reach(spec: FlowSpec) -> dict[str, set[str]]:
    """
    Parameters
    ----------
    spec : FlowSpec
        A document whose names have already resolved.

    Returns
    -------
    Every configuration variable name mapped to the jobs that can read it. A
    universal variable is read by every job, because it sits in every step's
    filtered configuration. Every other variable is read by the jobs whose
    steps declare it.
    """
    reach: dict[str, set[str]] = {}
    for name, job in spec.jobs.items():
        for step in _steps_of(name, job):
            for variable in step.config_vars:
                reach.setdefault(variable.name, set()).add(name)
    for variable in universal_flow_config_variables:
        reach[variable.name] = set(spec.jobs)
    return reach


def _check_job_values_are_covering(spec: FlowSpec) -> None:
    # Keyed by variable rather than by job, because the condition is over the
    # whole document. The jobs setting a variable must be exactly the jobs
    # that read it.
    reach = _reach(spec)
    setters: dict[str, set[str]] = {}
    for name, job in spec.jobs.items():
        for variable_name in job.values:
            setters.setdefault(variable_name, set()).add(name)
    for variable_name, setting in sorted(setters.items()):
        readers = reach.get(variable_name, set())
        uncovered = readers - setting
        if uncovered:
            raise FlowSpecError(
                f"Jobs {sorted(setting)} set '{variable_name}' in their 'with' "
                f"blocks, but jobs {sorted(uncovered)} also read "
                f"'{variable_name}' and do not set it, so those jobs would "
                f"observe a different value with no error anywhere. Every job "
                f"that reads a variable must set it, or none of them may. Set "
                f"it on the document or on the design instead."
            )
        stray = setting - readers
        if stray:
            raise FlowSpecError(
                f"Jobs {sorted(stray)} set '{variable_name}' in their 'with' "
                f"blocks, but no step of those jobs reads '{variable_name}', "
                f"so the value could never take effect. Jobs that read "
                f"'{variable_name}': {sorted(readers)}."
            )


def _check_sink_join_is_unambiguous(
    spec: FlowSpec,
    keys: dict[str, set[str]],
) -> None:
    if spec.final is not None:
        # 'final' names the state to return, so the sinks are not joined.
        return
    edges = spec.edges()
    needed = {need for job in spec.jobs.values() for need in job.needs}
    sinks = [name for name in spec.jobs if name not in needed]
    branches = {sink: ({sink} | ancestors(edges, sink)) for sink in sinks}
    for first, second in _pairs(sinks):
        shared = branches[first] & branches[second]
        first_keys = _union(keys, branches[first] - shared)
        second_keys = _union(keys, branches[second] - shared)
        for key in sorted(first_keys & second_keys):
            raise FlowSpecError(
                f"The final state of flow '{spec.name}' joins leaf jobs "
                f"'{first}' and '{second}', which both produce '{key}'. No "
                f"job's 'source' can resolve this, because the join is not a "
                f"job. Declare the top-level 'final' key naming the job whose "
                f"state the flow returns, for example 'final: {first}'."
            )
```

- [ ] **Step 4: Wire them into `validate_against_registry`**

Extend the tail of `validate_against_registry`:

```python
    _check_source_keys_resolve(spec)
    views = {name: _produced_views(name, job) for name, job in spec.jobs.items()}
    keys = {name: _produced_keys(name, job) for name, job in spec.jobs.items()}
    _check_sources_can_deliver(spec, keys)
    _check_requirements_are_reachable(spec, views)
    _check_fan_in_is_unambiguous(spec, keys)
    _check_sink_join_is_unambiguous(spec, keys)
    _check_job_values_are_covering(spec)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: 26 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 7: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 8: Commit**

```bash
git add librelane/flows/spec_validation.py test/flows/test_spec_validation.py
git commit -m "feat: check per-job values and the sink join at load time"
```

---

## Load errors this phase implements

Every load error the spec lists, with the task that raises it. This table is the phase's completeness check.

| Spec error | Task | Raised by |
| --- | --- | --- |
| `needs` referencing an undeclared job | 3 | `FlowSpec._check_needs_are_declared` |
| A cycle in `needs` | 3 | `FlowSpec._check_acyclic` |
| `uses` naming an unregistered stage or provider | 5 | `_check_uses` |
| `steps` naming an unregistered step id | 5 | `_check_steps` |
| A job declaring both `uses` and `steps` | 2 | `JobSpec._reject_both_implementations` |
| A job declaring neither, whose id is not a template id | 5 | `_require_implementation` |
| `if` that is not a conjunction | 4 | `parse_condition` |
| `if` naming a variable the flow does not declare | 4 | `FlowSpec._check_conditions_are_declared_booleans` |
| `source` naming a job that is not a direct predecessor | 3 | `FlowSpec._check_sources_name_direct_predecessors` |
| `source` naming a direct predecessor whose branch cannot produce the key | 6 | `_check_sources_can_deliver` |
| A document-level `with` naming `PDK`, `SCL`, `PAD` or `meta` | 4 | `FlowSpec._check_values_are_not_reserved` |
| A job-level `with` naming a variable that some other job reads and does not itself set | 7 | `_check_job_values_are_covering` |
| `final` naming an undeclared job | 4 | `FlowSpec._check_final_names_a_job` |
| A conflicting sink join with no `final` declared | 7 | `_check_sink_join_is_unambiguous` |
| An undeclared fan-in conflict, over views or metrics | 6 | `_check_fan_in_is_unambiguous` |
| An unsatisfiable `requires` | 6 | `_check_requirements_are_reachable` |

One check in this plan is not in the spec's list. A `source` key that is neither a registered view nor a registered metric, in Task 6. It is here because without it the two checks that follow would compare against an unresolvable key.

The spec also states one load **warning**, at
`docs/superpowers/specs/2026-07-31-workflow-engine-design.md:264`. A document
declaring `needs` on a conditional producer without repeating that producer's
condition is a load warning naming both. It is a warning, not an error, so it
correctly does not appear in the table above. No task in this plan implements
it, and no task in any of the other four phases claims it either. This is
recorded here rather than left silent because the gap is not a nitpick. It is
exactly the hazard the spec uses to justify the three-variable conjunction on
the `xor` job. `KLayout.StreamOut` gated on `RUN_KLAYOUT_STREAMOUT` still fires
as a pass-through and deposits its input state unchanged, so with that
variable false it carries no `klayout_gds`, and `KLayout.XOR` requires it. A
document that declared `needs: [klayout_streamout]` on `xor` without also
gating `xor` on `RUN_KLAYOUT_STREAMOUT` would load cleanly today, with only
this unimplemented warning to say otherwise, and would crash at run time on a
missing input where the intent was a clean skip. Deferred, not implemented.

Two entries in that table deserve a note.

`source` naming a direct predecessor whose branch cannot produce the key pairs with a runtime check phase 2 added independently. Phase 2's `_merge` raises `JoinConflictError` when a `source` names a producer that ran but never produced the key, rather than silently dropping it. The two are the declared and the actual form of one condition. This plan catches it from the declared contracts before the run directory exists, and phase 2 catches whatever a provider does beyond its declaration. Neither replaces the other, and neither is a fallback for the other.

The job-level `with` entry is a **whole-document** condition wearing a per-job spelling. The error is attributable to a job's `with` block, but it cannot be decided by looking at that block alone, because whether a variable is covered depends on every other job's `with` block and on the reach of the variable across the whole graph. That is why `_check_job_values_are_covering` iterates variables rather than jobs.

## What this phase does not do

Nothing imports `spec.py` or `spec_validation.py` outside their own tests. `librelane/flows/__init__.py` is deliberately not touched, so the new names are not yet public API and phase 2 can still change them without a deprecation.

Conditions are parsed here and evaluated in phase 2. `final` is validated here and consumed in phase 2. The net, the engine, the `Job` dataclass, the migration of the six flows and the command-line surface are phases 2 through 5.
