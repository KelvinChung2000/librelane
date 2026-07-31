# Workflow Document Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pydantic models, YAML loader and every load-time validation for a LibreLane workflow document, as a pure addition that nothing consumes yet.

**Architecture:** A flow document is a `FlowSpec` pydantic model holding a `dict[str, JobSpec]`. Validation happens in two tiers. Structural checks that need only the document itself run as pydantic model validators, so the Python API and the YAML path get identical errors. Semantic checks that need the stage and step registries run as a separate `validate_against_registry` pass, so the models stay unit-testable without a populated registry. Graph algorithms live in their own module because phase 4 needs `ancestors`/`descendants` for `--target` and `--invalidate`.

**Tech Stack:** Python 3.11+, pydantic 2.13, `graphlib` from the standard library for cycle detection and topological order, pyyaml via the existing `librelane.config.loading.sources.read_source`, pytest with pytest-mock, uv for dependency management.

## Global Constraints

- This is phase 1 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. Nothing in this phase may modify `SequentialFlow`, `StagedFlow`, `Stage`, `StageRegistry` or any shipped flow. It is additive only, and the full test suite must stay green.
- Never add a fallback. An unresolvable name, an unsupported type, or an ambiguous join is an error naming the legal alternatives, never a silent default.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- Reuse the dependency rather than hand-rolling. Cycle detection and topological order are `graphlib.TopologicalSorter`, not a hand-written DFS. YAML reading is `read_source`, not a bare `yaml.load`.
- The document's five job keys are exactly `needs`, `uses`, `steps`, `source` and `if`. No others.
- `if` in YAML maps to the Python field `condition` through a pydantic alias. Both spellings must work.
- Every new file carries the Apache 2.0 header used by `librelane/flows/explanation.py`, with the year 2026.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

## File Structure

| File | Responsibility |
| --- | --- |
| `librelane/flows/spec.py` | `VariableSpec`, `JobSpec`, `FlowSpec`, `FlowSpecError`, `load_flow_spec`. Field-level and structural validation. |
| `librelane/flows/spec_graph.py` | Pure graph math over `dict[str, list[str]]`. No LibreLane imports. `topological_order`, `ancestors`, `descendants`, `CycleError` passthrough. |
| `librelane/flows/spec_validation.py` | `validate_against_registry`. Every check that needs `Stage.factory`, `StageRegistry` or `Step.factory`. |
| `test/flows/test_spec_graph.py` | Unit tests for the graph module. |
| `test/flows/test_spec.py` | Unit tests for the models, the loader and structural validation. |
| `test/flows/test_spec_validation.py` | Unit tests for registry-backed validation. |

`spec_graph.py` is separated because phase 4 consumes `ancestors` for `--target` and `descendants` for `--invalidate`, and because pure graph math with no domain imports is the easiest thing in this plan to test exhaustively.

---

### Task 1: The graph module

**Files:**
- Create: `librelane/flows/spec_graph.py`
- Test: `test/flows/test_spec_graph.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `topological_order(edges: dict[str, list[str]]) -> list[str]` where `edges[node]` lists that node's predecessors. Raises `graphlib.CycleError`.
  - `ancestors(edges: dict[str, list[str]], node: str) -> set[str]` — the transitive predecessors, excluding `node` itself.
  - `descendants(edges: dict[str, list[str]], node: str) -> set[str]` — the transitive successors, excluding `node` itself.

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
    reverse: dict[str, list[str]] = {name: [] for name in edges}
    for name, predecessors in edges.items():
        for predecessor in predecessors:
            reverse[predecessor].append(name)
    return _reachable(reverse, node)


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
  - `FlowSpecError(FlowError)` — raised for every load-time rejection that is not a raw pydantic field error.
  - `VariableSpec(BaseModel)` with fields `name: str`, `type: str`, `description: str`, `default: Any = None`, `deprecated_names: list[str] = []`, `units: str | None = None`, and a method `to_variable() -> Variable`.
  - `JobSpec(BaseModel)` with fields `needs: list[str] = []`, `uses: str | None = None`, `steps: list[str] | None = None`, `source: dict[str, str] = {}`, `condition: str | None = None` aliased to `if`.
  - `FlowSpec(BaseModel)` with fields `name: str`, `description: str = ""`, `values: dict[str, Any] = {}` aliased to `with`, `config: list[VariableSpec] = []`, `jobs: dict[str, JobSpec]`.

**Context the implementer needs:**

`librelane.config.Variable` is a dataclass declared at `librelane/config/legacy.py:282`. Its constructor is positional-then-keyword: `Variable(name, type, description, default=..., deprecated_names=..., units=..., pdk=...)`. `type` is a real Python type object, not a string, which is why `VariableSpec` needs a name-to-type mapping.

Only five scalar type names are supported. This is not an arbitrary restriction: across all six shipped flows there are exactly two config-var annotations, `bool` used 22 times and `TOOLS`'s `Optional[dict[str, Union[str, list[str]]]]` used once. `TOOLS` is an engine-level variable declared by the engine, not by any document, so no document needs a product type. Anything outside the five is an error naming the five.

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
    from_yaml = JobSpec.model_validate({"if": "RUN_LINTER"})
    from_python = JobSpec(condition="RUN_LINTER")

    assert from_yaml.condition == "RUN_LINTER"
    assert from_python.condition == "RUN_LINTER"
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


def test_a_job_declaring_neither_uses_nor_steps_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"needs": ["synthesis"]})

    assert "uses" in str(exc_info.value)
    assert "steps" in str(exc_info.value)


def test_an_unknown_job_key_is_rejected_naming_the_five_legal_keys():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "runs-on": "ubuntu-latest"})

    message = str(exc_info.value)
    assert "runs-on" in message
    for key in ("needs", "uses", "steps", "source", "if"):
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


#: The scalar types a document may declare. Products are deliberately absent:
#: across every shipped flow the only annotations in use are ``bool`` and the
#: engine-level ``TOOLS``, which no document declares.
_VARIABLE_TYPES: dict[str, type] = {
    "bool": bool,
    "int": int,
    "str": str,
    "Decimal": Decimal,
    "Path": Path,
}

_JOB_KEYS = ("needs", "uses", "steps", "source", "if")


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
    source: dict[str, str] = {}
    condition: str | None = Field(default=None, alias="if")

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        unknown = [
            key for key in data if key not in _JOB_KEYS and key != "condition"
        ]
        if unknown:
            raise FlowSpecError(
                f"Job declares unknown key(s) {sorted(unknown)}. A job accepts "
                f"exactly {list(_JOB_KEYS)}."
            )
        return data

    @model_validator(mode="after")
    def _require_exactly_one_implementation(self) -> "JobSpec":
        if (self.uses is None) == (self.steps is None):
            raise FlowSpecError(
                f"A job must declare exactly one of 'uses' or 'steps', but "
                f"this one declares "
                f"{'both' if self.uses is not None else 'neither'}. Use 'uses' "
                f"to name a registered stage and provider, or 'steps' to list "
                f"step IDs inline."
            )
        return self


class FlowSpec(BaseModel):
    """A complete workflow document."""

    # populate_by_name is required, not optional. With extra="forbid" and an
    # aliased field, pydantic 2.13 rejects the Python field name outright, so
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

### Task 3: Structural validation and the loader

**Files:**
- Modify: `librelane/flows/spec.py`
- Test: `test/flows/test_spec.py`

**Interfaces:**
- Consumes: `topological_order` from `librelane.flows.spec_graph` (Task 1); `FlowSpec`, `JobSpec`, `FlowSpecError` from Task 2.
- Produces: `load_flow_spec(source: Mapping[str, Any] | str | os.PathLike) -> FlowSpec`.

**Context the implementer needs:**

`librelane.config.loading.sources.read_source(source, *, yaml_loader=OpenLaneYAMLLoader) -> ConfigSource` already handles `.yaml`, `.yml`, `.json` and a plain mapping, and its `OpenLaneYAMLLoader` reads YAML floats as `Decimal` so values round-trip exactly. `ConfigSource` has fields `mapping`, `name` and `kind`. Use it rather than calling `yaml.load` directly; `librelane/stages/tools.py:97` is the existing precedent for reusing it outside `librelane.config`.

The four checks in this task are the ones that need only the document. They belong on `FlowSpec` as an `after` model validator so that constructing a `FlowSpec` in Python raises the same errors as loading YAML.

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


def test_a_source_naming_a_non_predecessor_is_rejected():
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


def test_an_if_naming_an_undeclared_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [
                    {"name": "RUN_LINTER", "type": "bool", "description": "x"}
                ],
                "jobs": {"lint": {"uses": "lint/verilator", "if": "RUN_LINT"}},
            }
        )

    message = str(exc_info.value)
    assert "lint" in message
    assert "RUN_LINT" in message
    assert "RUN_LINTER" in message


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

from librelane.flows.spec_graph import topological_order
from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.config import Variable
from librelane.config.loading.sources import read_source
```

Add these methods to `FlowSpec`, after `edges`:

```python
    @model_validator(mode="after")
    def _check_structure(self) -> "FlowSpec":
        self._check_needs_are_declared()
        self._check_acyclic()
        self._check_sources_are_predecessors()
        self._check_conditions_are_declared()
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

    def _check_sources_are_predecessors(self) -> None:
        from librelane.flows.spec_graph import ancestors

        edges = self.edges()
        for name, job in self.jobs.items():
            reachable = ancestors(edges, name)
            for view, producer in job.source.items():
                if producer not in reachable:
                    raise FlowSpecError(
                        f"Job '{name}' sources view '{view}' from "
                        f"'{producer}', which is not one of its predecessors. "
                        f"Predecessors: {sorted(reachable)}."
                    )

    def _check_conditions_are_declared(self) -> None:
        declared = {variable.name for variable in self.config}
        for name, job in self.jobs.items():
            if job.condition is None:
                continue
            if job.condition not in declared:
                raise FlowSpecError(
                    f"Job '{name}' is conditional on '{job.condition}', which "
                    f"flow '{self.name}' does not declare. Declared "
                    f"variables: {sorted(declared)}."
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
Expected: 13 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/spec.py test/flows/test_spec.py
git commit -m "feat: validate workflow document structure and load it from YAML"
```

---

### Task 4: Registry-backed name resolution

**Files:**
- Create: `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_validation.py`

**Interfaces:**
- Consumes: `FlowSpec`, `FlowSpecError` from Task 2.
- Produces: `validate_against_registry(spec: FlowSpec) -> None`, raising `FlowSpecError`.

**Context the implementer needs:**

Three registries are involved, all process-wide singletons populated by import side effect.

- `Stage.factory.get(id) -> Stage | None` and `Stage.factory.list() -> list[str]`, from `librelane.stages`.
- `StageRegistry.providers(stage: str) -> list[str]`, at `librelane/stages/registry.py:210`, returning every provider registered for a stage in registration order. It already exists. Do not add one, and do not reach into the name-mangled `_by_stage_and_provider`.
- `Step.factory.get(name) -> type[Step] | None` and `Step.factory.list() -> list[str]`, from `librelane/steps/step/factory.py:81`. Lookup is case-insensitive; `list()` returns the canonical-cased IDs.

`uses` is `"<stage>"` or `"<stage>/<provider>"`. A bare stage means that stage's `default_provider`, which is `Stage.default_providers`, a tuple that is empty when the stage is unselected by default.

Because these are process-wide singletons, the tests import `librelane.steps` and `librelane.stages` at module scope to populate them, the way `test/stages/test_registry.py` does. Do not try to isolate them per test.

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


def _spec(jobs: dict) -> FlowSpec:
    return FlowSpec.model_validate({"name": "Tiny", "jobs": jobs})


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

from librelane.stages import Stage, StageRegistry
from librelane.steps import Step
from librelane.flows.spec import FlowSpec, FlowSpecError


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
        if job.uses is not None:
            _check_uses(name, job.uses)
        if job.steps is not None:
            _check_steps(name, job.steps)


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
Expected: 6 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/spec_validation.py test/flows/test_spec_validation.py
git commit -m "feat: resolve workflow document names against the registries"
```

---

### Task 5: The view contract checks

**Files:**
- Modify: `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_validation.py`

**Interfaces:**
- Consumes: `validate_against_registry` from Task 4; `ancestors` from Task 1.
- Produces: no new public names. `validate_against_registry` gains two checks.

**Context the implementer needs:**

Each job's produced views come from two places. For a `uses` job they are `Stage.provides` union `Registration.provides`, where the registration comes from `StageRegistry.get(stage, provider) -> Registration | None` at `librelane/stages/registry.py:206`. That method already exists; do not add one, and do not reach into the name-mangled `_by_stage_and_provider`. For a `steps` job they are the union of each step class's `outputs`, declared at `librelane/steps/step/core.py:190` as `ClassVar[list[DesignFormat]]`.

Two stage facts matter for the test documents below, and both were verified against the tree. There is **no `xor` stage and no `signoff` stage**; the 27 registered ids are the ones in `librelane/stages/taxonomy.py`, and the nearest real names are `drc`, `lvs`, `streamout` and `signoff_sta`. And `streamout` and `drc` are both `multi_provider` with default `('magic', 'klayout')`, so a bare `uses: streamout` runs both providers' step sequences concatenated. A job id is free-form and need not match its stage, which is why the fan-in tests below name a job `xor` while it `uses: drc/magic`.

Consumed views are `Stage.requires` for a `uses` job, and the union of each step's `inputs` for a `steps` job.

A `source` key is a view ID string, resolved with `DesignFormat.factory.get(id) -> DesignFormat | None`. There is no `DesignFormat.by_id`. `str(view)` is the view's ID, which is why the messages below interpolate the view directly and the sorts use `key=str`.

The two checks:

**Reachability.** Every view a job requires must be produced by some ancestor, or be in the document's implicit initial state. The initial state is not knowable at load time, so the check is scoped to views that at least one *other* job in the document produces.

Excluding the job's own `provides` is essential, not an optimisation. 14 of the 27 stages both require and provide the same views — the `PNR_IN_PLACE` contract, `def`/`nl`/`sdc`, which is the identity that made this whole design necessary. `Stage.floorplan` requires `nl, sdc` and provides `def, nl, sdc`. If a job's own output counted as evidence that a view is producible, every such job would be rejected whenever no ancestor happened to restate the view, which is the common case at the head of a document. A view no other job produces is assumed to come from the initial state; the runtime state check catches it if it does not. This is a deliberate scoping decision, not a fallback, and two tests below pin both halves of it.

**Fan-in conflict.** For each job, for each pair of its direct predecessors that are not each other's ancestors, any view both of their subgraphs produce is ambiguous unless `source` names one. "Both subgraphs produce" means the view appears in the produced set of the predecessor or any of its ancestors, restricted to jobs not shared between the two branches. A shared ancestor's view is identical down both branches and is not a conflict.

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


def test_a_required_view_no_ancestor_produces_is_rejected():
    """
    'streamout' produces gds but is not an ancestor of 'drc', so gds is
    producible by the document yet unreachable from drc. A view no job at all
    produces is a different case, pinned by the test below.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "streamout": {"uses": "streamout/magic"},
                    "drc": {"needs": ["synthesis"], "uses": "drc/klayout"},
                }
            )
        )

    message = str(exc_info.value)
    assert "drc" in message
    assert "gds" in message


def test_a_source_naming_an_unknown_view_is_rejected():
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
                        "source": {"not_a_view": "klayout_streamout"},
                    },
                }
            )
        )

    assert "not_a_view" in str(exc_info.value)


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
Expected: `test_a_fan_in_conflict_is_rejected_naming_both_producers`, `test_a_required_view_no_ancestor_produces_is_rejected` and `test_a_source_naming_an_unknown_view_is_rejected` FAIL because nothing raises. The other three pass vacuously.

- [ ] **Step 3: Add the contract checks**

In `librelane/flows/spec_validation.py`, extend the imports:

```python
from librelane.state import DesignFormat
from librelane.stages import Stage, StageRegistry
from librelane.steps import Step
from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec
from librelane.flows.spec_graph import ancestors
```

Extend `validate_against_registry` to call the new checks after the existing loop:

```python
    _check_source_views_exist(spec)
    produced = {name: _produces(job) for name, job in spec.jobs.items()}
    _check_requirements_are_reachable(spec, produced)
    _check_fan_in_is_unambiguous(spec, produced)
```

Append this check first, because the two that follow compare against `source`
keys and must not do so with an unresolvable one:

```python
def _check_source_views_exist(spec: FlowSpec) -> None:
    for name, job in spec.jobs.items():
        for view in job.source:
            if DesignFormat.factory.get(view) is None:
                raise FlowSpecError(
                    f"Job '{name}' sources view '{view}', which is not a "
                    f"registered design format. Registered formats: "
                    f"{sorted(DesignFormat.factory.list())}."
                )
```

Append these functions:

```python
def _produces(job: JobSpec) -> set[DesignFormat]:
    if job.steps is not None:
        views: set[DesignFormat] = set()
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            views.update(step.outputs)
        return views
    assert job.uses is not None, "checked by JobSpec validation"
    stage_id, _, provider = job.uses.partition("/")
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    views = set(stage.provides)
    # A bare 'uses' means the stage's default provider, which is a tuple for a
    # multi_provider stage. Union every one of them rather than picking the
    # first, which would silently drop the rest.
    providers = (provider,) if provider else stage.default_providers
    for each in providers:
        registration = StageRegistry.get(stage_id, each)
        if registration is not None:
            views.update(registration.provides)
    return views


def _consumes(job: JobSpec) -> set[DesignFormat]:
    if job.steps is not None:
        views: set[DesignFormat] = set()
        for step_id in job.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            views.update(step.inputs)
        return views
    assert job.uses is not None, "checked by JobSpec validation"
    stage = Stage.factory.get(job.uses.split("/")[0])
    assert stage is not None, "checked by _check_uses"
    return set(stage.requires)


def _check_requirements_are_reachable(
    spec: FlowSpec,
    produced: dict[str, set[DesignFormat]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        available: set[DesignFormat] = set()
        for ancestor in ancestors(edges, name):
            available.update(produced[ancestor])
        # Views some *other* job produces. A job's own provides are excluded
        # because 14 of the 27 stages both require and provide the same views
        # (the PNR_IN_PLACE contract, def/nl/sdc), so counting a job's own
        # output as evidence that the view is producible would reject every
        # one of them whenever no ancestor happens to restate it.
        elsewhere: set[DesignFormat] = set()
        for other, views in produced.items():
            if other != name:
                elsewhere.update(views)
        for view in sorted(_consumes(job) - available, key=str):
            # A view no other job produces is presumed to arrive in the
            # initial state, and is checked at run time against the real state.
            if view not in elsewhere:
                continue
            raise FlowSpecError(
                f"Job '{name}' requires view '{view}', which none of its "
                f"predecessors produce. Predecessors: "
                f"{sorted(ancestors(edges, name))}."
            )


def _check_fan_in_is_unambiguous(
    spec: FlowSpec,
    produced: dict[str, set[DesignFormat]],
) -> None:
    edges = spec.edges()
    for name, job in spec.jobs.items():
        if len(job.needs) < 2:
            continue
        branches = {
            need: ({need} | ancestors(edges, need)) for need in job.needs
        }
        for first, second in _pairs(job.needs):
            if second in branches[first] or first in branches[second]:
                continue
            shared = branches[first] & branches[second]
            first_views = _union(produced, branches[first] - shared)
            second_views = _union(produced, branches[second] - shared)
            declared = {DesignFormat.factory.get(key) for key in job.source}
            for view in sorted(first_views & second_views, key=str):
                if view in declared:
                    continue
                raise FlowSpecError(
                    f"Job '{name}' joins '{first}' and '{second}', which both "
                    f"produce view '{view}'. Declare which one it comes from "
                    f"with 'source: {{{view}: {first}}}' or "
                    f"'source: {{{view}: {second}}}'."
                )


def _pairs(items: list[str]):
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            yield first, second


def _union(
    produced: dict[str, set[DesignFormat]],
    names: set[str],
) -> set[DesignFormat]:
    result: set[DesignFormat] = set()
    for name in names:
        result.update(produced[name])
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_spec_validation.py -v`
Expected: 12 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/spec_validation.py test/flows/test_spec_validation.py
git commit -m "feat: check workflow document view contracts at load time"
```

---

## What this phase does not do

Nothing imports `spec.py` or `spec_validation.py` outside their own tests. `librelane/flows/__init__.py` is deliberately not touched, so the new names are not yet public API and phase 2 can still change them without a deprecation. The net, the engine, the `Job` dataclass, the migration of the six flows and the command-line surface are phases 2 through 5.
