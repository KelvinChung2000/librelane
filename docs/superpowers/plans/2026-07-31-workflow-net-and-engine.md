# Workflow Net and Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Petri net, the state join and the engine that runs a `FlowSpec`, as a pure addition that the shipped flows do not yet use.

**Architecture:** A net holds one place per arc and fires a transition when every input place holds a token. The engine resolves a `FlowSpec` into concrete `Job` objects, builds a net from the job graph, and fires jobs in topological order, merging the input tokens into one `State` per job. A job whose condition is false fires as a pass-through, depositing its input state unchanged. Concurrency and failure semantics are the last task, so every earlier task is testable with a deterministic single-threaded run.

**Tech Stack:** Python 3.11+, `concurrent.futures` through the existing `librelane.common.get_tpe()`, pytest with pytest-mock, uv.

## Global Constraints

- This is phase 2 of 5 from `docs/superpowers/specs/2026-07-31-workflow-engine-design.md`. It depends on phase 1 (`docs/superpowers/plans/2026-07-31-workflow-document-loader.md`) having landed.
- Nothing in this phase may modify `SequentialFlow`, `StagedFlow`, `Stage`, `StageRegistry` or any shipped flow. It is additive only, and the full test suite must stay green.
- Never add a fallback. An ambiguous join, a missing view or a failed step is an error naming what went wrong, never a silent default.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute. Write `from librelane.flows.spec import FlowSpec`, never `from .spec import FlowSpec`. The relative form was converted project-wide before this phase.
- Docstrings are NumPy style, parsed by `sphinx.ext.napoleon`. Write a `Parameters` / `Returns` / `Raises` section with dashed underlines, not reST `:param:` / `:returns:` / `:raises:` fields.
- Use `uv run` for every command. Tests are pytest; mocking is pytest-mock.
- The firing rule must be written for the general case, not specialised to the acyclic one. Spec 3 adds loops and resource places by adding arcs, not by rewriting `Net.fire`.
- Every new file carries the Apache 2.0 header used by `librelane/flows/explanation.py`, with the year 2026.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. `make lint` is broken by a sandbox permission error on `.claude/loop.md`; do not use it.

## Interfaces inherited from phase 1

These exist before this plan starts. Do not redefine them.

- `librelane.flows.spec.FlowSpec` with `name: str`, `description: str`, `config: list[VariableSpec]`, `jobs: dict[str, JobSpec]`, and `edges() -> dict[str, list[str]]`.
- `librelane.flows.spec.JobSpec` with `needs: list[str]`, `uses: str | None`, `steps: list[str] | None`, `source: dict[str, str]`, `condition: str | None`.
- `librelane.flows.spec.FlowSpecError(FlowError)`.
- `librelane.flows.spec.load_flow_spec(source) -> FlowSpec`.
- `librelane.flows.spec_graph.topological_order(edges) -> list[str]`, `ancestors(edges, node) -> set[str]`, `descendants(edges, node) -> set[str]`.
- `librelane.flows.spec_validation.validate_against_registry(spec) -> None`.
- `librelane.stages.StageRegistry.providers(stage) -> list[str]` and `StageRegistry.get(stage, provider) -> Registration | None`.

## Existing APIs this phase consumes

- `librelane.flows.resume.resume_key(step: Step, state_in: State, fingerprinter: Fingerprinter) -> str`
- `librelane.flows.resume.reusable_state(step_dir, key: str, fingerprinter: Fingerprinter) -> State | None` — returns `None` for every way a hit cannot be proven.
- `librelane.flows.resume.write_entry(step_dir, step: Step, key: str) -> None` — call only after the step returns without raising.
- `Step.start(toolbox=..., step_dir=...) -> State`. Raises `StepException` (fatal), `StepError` (fatal), or `DeferredStepError` (collect and continue).
- `State(copying=..., overrides=..., metrics=...)`, an immutable mapping from `DesignFormat` to `StateElement`, with `.metrics: dict[str, Any]` and `.to_raw_dict(metrics: bool = True)`.
- `librelane.common.get_tpe()` returns the process-wide `ThreadPoolExecutor`.

## File Structure

| File | Responsibility |
| --- | --- |
| `librelane/flows/net.py` | `Arc`, `Net`. Places, marking, enablement, firing. Tokens are `Any`, so the module has no domain imports. |
| `librelane/flows/join.py` | `join_states(tokens, source) -> State`. The equal-merges rule and the conflict error. |
| `librelane/flows/job.py` | The resolved `Job` dataclass and `resolve_jobs(spec) -> dict[str, Job]`. |
| `librelane/flows/engine.py` | `Workflow`. Builds the net, fires jobs, checks contracts, handles failure and concurrency. |
| `test/flows/test_net.py` | Net unit tests with string tokens. |
| `test/flows/test_join.py` | Join rule unit tests. |
| `test/flows/test_job.py` | Job resolution unit tests. |
| `test/flows/test_engine.py` | Engine tests with fake steps. |

---

### Task 1: The net

**Files:**
- Create: `librelane/flows/net.py`
- Test: `test/flows/test_net.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Arc` frozen dataclass with `producer: str | None` and `consumer: str | None`. `None` on `producer` means the source place holding the initial token; `None` on `consumer` means the sink.
  - `NetError(RuntimeError)`.
  - `Net(jobs: Sequence[str], edges: dict[str, list[str]])` with `arcs: tuple[Arc, ...]`, `inputs_of(job) -> tuple[Arc, ...]`, `outputs_of(job) -> tuple[Arc, ...]`, `put(arc, token) -> None`, `enabled() -> list[str]`, `consume(job) -> list[Any]`, `fire(job, token) -> None`, `fired: set[str]`, `is_complete() -> bool`, `stalled() -> list[str]`.

**Design notes the implementer needs:**

One place per arc, not per job. A job with two consumers deposits one token on each of its two outgoing places. With one place per job, fan-out would force the producer to deposit N tokens and the scheduler to know N, leaking the fan-out count into the encoding. Per-arc keeps the firing rule literally "consume one token from each input place, deposit one on each output place", which is what spec 3 extends without rewriting.

`fire` takes a single token and deposits a copy of it on every output arc, because a job produces one output state regardless of how many consumers read it.

`consume` removes the tokens rather than peeking, so a place never silently feeds two firings. Depositing onto an occupied place raises `NetError`. Neither can happen on an acyclic graph, which is exactly why both are asserted now: they are what a spec 3 marking bug trips first.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_net.py`:

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

from librelane.flows.net import Arc, Net, NetError

pytestmark = pytest.mark.all

_DIAMOND_EDGES = {
    "streamout": [],
    "drc": ["streamout"],
    "lvs": ["streamout"],
    "xor": ["drc", "lvs"],
}
_DIAMOND_JOBS = ["streamout", "drc", "lvs", "xor"]


def _diamond() -> Net:
    return Net(_DIAMOND_JOBS, _DIAMOND_EDGES)


def test_a_job_with_no_needs_takes_its_input_from_the_source_place():
    net = _diamond()

    assert net.inputs_of("streamout") == (Arc(None, "streamout"),)


def test_a_job_with_no_dependents_deposits_on_the_sink():
    net = _diamond()

    assert net.outputs_of("xor") == (Arc("xor", None),)


def test_a_fan_out_job_has_one_output_arc_per_consumer():
    net = _diamond()

    assert set(net.outputs_of("streamout")) == {
        Arc("streamout", "drc"),
        Arc("streamout", "lvs"),
    }


def test_nothing_is_enabled_until_the_source_is_marked():
    net = _diamond()

    assert net.enabled() == []

    net.put(Arc(None, "streamout"), "initial")

    assert net.enabled() == ["streamout"]


def test_firing_a_fan_out_enables_both_branches():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    assert sorted(net.enabled()) == ["drc", "lvs"]


def test_a_join_is_enabled_only_when_every_input_place_is_marked():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    net.consume("drc")
    net.fire("drc", "drc-out")
    assert net.enabled() == ["lvs"]

    net.consume("lvs")
    net.fire("lvs", "lvs-out")
    assert net.enabled() == ["xor"]


def test_consume_returns_one_token_per_input_place_and_empties_them():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")
    net.consume("drc")
    net.fire("drc", "drc-out")
    net.consume("lvs")
    net.fire("lvs", "lvs-out")

    assert sorted(net.consume("xor")) == ["drc-out", "lvs-out"]
    assert net.enabled() == []


def test_depositing_onto_an_occupied_place_raises():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")

    with pytest.raises(NetError) as exc_info:
        net.put(Arc(None, "streamout"), "again")

    assert "already holds a token" in str(exc_info.value)


def test_the_run_is_complete_when_every_job_has_fired():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")

    assert not net.is_complete()

    for job in ["streamout", "drc", "lvs", "xor"]:
        net.consume(job)
        net.fire(job, f"{job}-out")

    assert net.is_complete()
    assert net.fired == {"streamout", "drc", "lvs", "xor"}


def test_stalled_names_the_jobs_that_never_became_enabled():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")
    net.consume("drc")
    net.fire("drc", "drc-out")

    assert sorted(net.stalled()) == ["lvs", "xor"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_net.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.net'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/net.py`:

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
The Petri net a workflow runs on.

There is one place per *arc*, not per job. A job with two consumers deposits one
token on each of its two outgoing places. The alternative, one place per job,
would force a producer to deposit as many tokens as it has consumers and the
scheduler to know that count, leaking fan-out into the encoding. Per-arc keeps
the firing rule literally true as stated: consume one token from each input
place, deposit one on each output place.

Tokens are opaque here, so this module has no domain imports and the engine is
free to make a token whatever it needs. In practice a token is a
:class:`librelane.state.State`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


class NetError(RuntimeError):
    """
    Raised when the marking violates an invariant. On an acyclic graph this
    cannot happen, which is why it is checked: it is what a marking bug in a
    later, cyclic engine trips first.
    """


@dataclass(frozen=True)
class Arc:
    """
    One place, identified by the edge it represents.

    Parameters
    ----------
    producer
        The job that deposits here, or ``None`` for the source
        place that holds the run's initial state.
    consumer
        The job that consumes here, or ``None`` for the sink.
    """

    producer: str | None
    consumer: str | None


class Net:
    """
    A marked Petri net over a job graph.

    Parameters
    ----------
    jobs
        Every job, in any order.
    edges
        A mapping from each job to the jobs it depends on.
    """

    def __init__(self, jobs: Sequence[str], edges: dict[str, list[str]]) -> None:
        self._jobs = tuple(jobs)
        arcs: list[Arc] = []
        has_consumer = {job: False for job in self._jobs}
        for job in self._jobs:
            predecessors = edges.get(job, [])
            if not predecessors:
                arcs.append(Arc(None, job))
            for predecessor in predecessors:
                arcs.append(Arc(predecessor, job))
                has_consumer[predecessor] = True
        for job in self._jobs:
            if not has_consumer[job]:
                arcs.append(Arc(job, None))
        self.arcs = tuple(arcs)
        self._marking: dict[Arc, Any] = {}
        self.fired: set[str] = set()

    def inputs_of(self, job: str) -> tuple[Arc, ...]:
        """Every place this job consumes from."""
        return tuple(arc for arc in self.arcs if arc.consumer == job)

    def outputs_of(self, job: str) -> tuple[Arc, ...]:
        """Every place this job deposits onto."""
        return tuple(arc for arc in self.arcs if arc.producer == job)

    def put(self, arc: Arc, token: Any) -> None:
        """
        Deposits one token on one place.

        Raises
        ------
        NetError
            If the place already holds a token.
        """
        if arc in self._marking:
            raise NetError(
                f"Place {arc} already holds a token. A place holds at most one "
                f"token, so this is a scheduling bug rather than a "
                f"configuration error."
            )
        self._marking[arc] = token

    def enabled(self) -> list[str]:
        """
        Returns
        -------
        Every job whose input places all hold a token and which has
        not already fired, in the order the jobs were declared.
        """
        return [
            job
            for job in self._jobs
            if job not in self.fired
            and all(arc in self._marking for arc in self.inputs_of(job))
        ]

    def consume(self, job: str) -> list[Any]:
        """
        Removes and returns one token from each of this job's input places.

        Raises
        ------
        NetError
            If any input place is unmarked.
        """
        tokens = []
        for arc in self.inputs_of(job):
            if arc not in self._marking:
                raise NetError(
                    f"Job '{job}' cannot consume: place {arc} holds no token."
                )
            tokens.append(self._marking.pop(arc))
        return tokens

    def fire(self, job: str, token: Any) -> None:
        """
        Deposits ``token`` on each of this job's output places and records the
        firing. Call after :meth:`consume`.
        """
        for arc in self.outputs_of(job):
            self.put(arc, token)
        self.fired.add(job)

    def is_complete(self) -> bool:
        """Whether every job has fired."""
        return self.fired == set(self._jobs)

    def stalled(self) -> list[str]:
        """
        Returns
        -------
        Every job that has not fired, for the error raised when no
        transition is enabled and the run is not complete.
        """
        return [job for job in self._jobs if job not in self.fired]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_net.py -v`
Expected: 10 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/net.py test/flows/test_net.py
git commit -m "feat: add the workflow Petri net"
```

---

### Task 2: The state join

**Files:**
- Create: `librelane/flows/join.py`
- Test: `test/flows/test_join.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `join_states(tokens: dict[str, State], source: dict[DesignFormat, str], job: str) -> State`, raising `JoinConflictError(FlowError)`.

**Design notes the implementer needs:**

One rule covers views and metrics both. **Equal values merge silently; unequal values are a conflict.** A view or metric inherited from a common ancestor is identical down both branches and needs no declaration. A key that two branches wrote differently is genuinely ambiguous, and `source` must name the producer.

No provenance tagging is needed. Path equality answers the question, because a rewritten view lands in a different job directory by construction.

`tokens` is keyed by the producing job so the error can name both producers and so `source` can select one. A job with a single predecessor never conflicts, so the single-token path returns that token unchanged.

`State` is an immutable mapping from `DesignFormat` to `StateElement` with a separate `.metrics` dict. Build the result with `State(copying=merged_views, metrics=merged_metrics)`.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_join.py`:

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

from librelane.common import Path
from librelane.flows.join import JoinConflictError, join_states
from librelane.state import DesignFormat, State

pytestmark = pytest.mark.all


def test_a_single_token_is_returned_unchanged():
    only = State({DesignFormat.nl: Path("/a/design.nl.v")}, metrics={"x": 1})

    joined = join_states({"synthesis": only}, {}, "floorplan")

    assert joined[DesignFormat.nl] == Path("/a/design.nl.v")
    assert joined.metrics == {"x": 1}


def test_identical_values_from_two_branches_merge_silently():
    shared = Path("/a/design.def")
    left = State({DesignFormat.def_: shared}, metrics={"shared": 1, "left": 2})
    right = State({DesignFormat.def_: shared}, metrics={"shared": 1, "right": 3})

    joined = join_states({"drc": left, "lvs": right}, {}, "xor")

    assert joined[DesignFormat.def_] == shared
    assert joined.metrics == {"shared": 1, "left": 2, "right": 3}


def test_differing_views_conflict_naming_both_producers():
    left = State({DesignFormat.gds: Path("/a/magic.gds")})
    right = State({DesignFormat.gds: Path("/a/klayout.gds")})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {"magic_streamout": left, "klayout_streamout": right}, {}, "xor"
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "source" in message


def test_a_declared_source_selects_one_producer():
    left = State({DesignFormat.gds: Path("/a/magic.gds")})
    right = State({DesignFormat.gds: Path("/a/klayout.gds")})

    joined = join_states(
        {"magic_streamout": left, "klayout_streamout": right},
        {DesignFormat.gds: "klayout_streamout"},
        "xor",
    )

    assert joined[DesignFormat.gds] == Path("/a/klayout.gds")


def test_differing_metrics_conflict_under_the_same_rule():
    left = State({}, metrics={"design__instance__count": 100})
    right = State({}, metrics={"design__instance__count": 200})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states({"a": left, "b": right}, {}, "join")

    message = str(exc_info.value)
    assert "design__instance__count" in message
    assert "a" in message and "b" in message


def test_a_source_naming_a_producer_that_did_not_run_raises():
    left = State({DesignFormat.gds: Path("/a/magic.gds")})
    right = State({DesignFormat.gds: Path("/a/klayout.gds")})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {"magic_streamout": left, "klayout_streamout": right},
            {DesignFormat.gds: "nonexistent"},
            "xor",
        )

    assert "nonexistent" in str(exc_info.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_join.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.join'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/join.py`:

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
Merging the states a job's predecessors produced into the one state it runs on.

One rule covers views and metrics both: equal values merge silently, unequal
values are a conflict the document must resolve with ``source``. A view or
metric inherited from a common ancestor is identical down both branches and
needs no declaration; a key two branches wrote differently is genuinely
ambiguous, and guessing would silently pick one tool's output over another's.
"""

from typing import Any

from librelane.common.errors import FlowError
from librelane.state import DesignFormat, State


class JoinConflictError(FlowError):
    """
    Raised when two of a job's predecessors produced different values for one
    view or metric and the document did not declare which to use.
    """


def join_states(
    tokens: dict[str, State],
    source: dict[DesignFormat, str],
    job: str,
) -> State:
    """
    Parameters
    ----------
    tokens : dict[str, State]
        Each predecessor's output state, keyed by the producing job.
    source : dict[DesignFormat, str]
        The job's declared per-view resolution.
    job : str
        The consuming job, named in errors.

    Returns
    -------
    The merged state.

    Raises
    ------
    JoinConflictError
        On an undeclared conflict, or on a ``source``
        naming a job that did not produce a token.
    """
    for view, producer in source.items():
        if producer not in tokens:
            raise JoinConflictError(
                f"Job '{job}' sources view '{view}' from '{producer}', which "
                f"produced no state for this run. Producers: "
                f"{sorted(tokens)}."
            )
    if len(tokens) == 1:
        return next(iter(tokens.values()))

    views = _merge(
        {name: dict(state) for name, state in tokens.items()},
        {str(view): producer for view, producer in source.items()},
        job,
        "view",
    )
    metrics = _merge(
        {name: dict(state.metrics) for name, state in tokens.items()},
        {},
        job,
        "metric",
    )
    return State(views, metrics=metrics)


def _merge(
    contributions: dict[str, dict[Any, Any]],
    selected: dict[str, str],
    job: str,
    kind: str,
) -> dict[Any, Any]:
    merged: dict[Any, Any] = {}
    origin: dict[Any, str] = {}
    for producer, mapping in contributions.items():
        for key, value in mapping.items():
            chosen = selected.get(str(key))
            if chosen is not None:
                if producer == chosen:
                    merged[key] = value
                    origin[key] = producer
                continue
            if key not in merged:
                merged[key] = value
                origin[key] = producer
                continue
            if merged[key] == value:
                continue
            raise JoinConflictError(
                f"Job '{job}' joins '{origin[key]}' and '{producer}', which "
                f"produced different values for {kind} '{key}'. Declare which "
                f"one it comes from with "
                f"'source: {{{key}: {origin[key]}}}' or "
                f"'source: {{{key}: {producer}}}'."
            )
    return merged
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_join.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/join.py test/flows/test_join.py
git commit -m "feat: add the workflow state join"
```

---

### Task 3: Job resolution

**Files:**
- Create: `librelane/flows/job.py`
- Test: `test/flows/test_job.py`

**Interfaces:**
- Consumes: `FlowSpec`, `JobSpec` from phase 1; `Stage`, `StageRegistry` from `librelane.stages`; `Step` from `librelane.steps`.
- Produces:
  - `Job` frozen dataclass with `id: str`, `needs: tuple[str, ...]`, `source: dict[DesignFormat, str]`, `condition: str | None`, `requires: tuple[DesignFormat, ...]`, `provides: tuple[DesignFormat, ...]`, `metrics: tuple[str, ...]`, `steps: tuple[type[Step], ...]`, `provider: str | None`.
  - `resolve_jobs(spec: FlowSpec) -> dict[str, Job]`.

**Design notes the implementer needs:**

`resolve_jobs` binds each `JobSpec` to its registered template and produces the concrete unit the engine runs. It assumes `validate_against_registry` already passed, so every name resolves; assertions rather than errors guard that assumption.

For a `uses` job, `steps` comes from `StageRegistry.get(stage, provider).steps`, `requires` from `Stage.requires`, and `provides`/`metrics` from the stage's union the registration's. A bare `uses` names the stage's `default_providers`, which is a tuple for a `multi_provider` stage, so concatenate every one of their step sequences in order rather than taking the first.

For a `steps` job there is no template, so `requires` is the union of the steps' `inputs`, `provides` the union of their `outputs`, `metrics` empty, and `provider` `None`.

`source` keys arrive as strings and become `DesignFormat` through `DesignFormat.factory.get`. There is no `DesignFormat.by_id`.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_job.py`:

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

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec
from librelane.state import DesignFormat

pytestmark = pytest.mark.all


def _spec(jobs: dict) -> FlowSpec:
    return FlowSpec.model_validate({"name": "Tiny", "jobs": jobs})


def test_a_uses_job_takes_its_steps_from_the_named_provider():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))

    job = jobs["synthesis"]
    assert job.provider == "yosys"
    assert len(job.steps) > 0
    assert all(step.id.startswith("Yosys.") for step in job.steps)


def test_a_bare_uses_takes_the_stage_default_provider():
    named = resolve_jobs(_spec({"floorplan": {"uses": "floorplan/openroad"}}))
    bare = resolve_jobs(_spec({"floorplan": {"uses": "floorplan"}}))

    assert bare["floorplan"].steps == named["floorplan"].steps


def test_a_uses_job_inherits_the_stage_contract():
    from librelane.stages import Stage

    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))

    assert set(jobs["synthesis"].requires) == set(Stage.synthesis.requires)
    assert set(jobs["synthesis"].provides) >= set(Stage.synthesis.provides)


def test_an_inline_job_derives_its_contract_from_its_steps():
    from librelane.steps import Step

    jobs = resolve_jobs(
        _spec({"custom": {"steps": ["Odb.SetPowerConnections"]}})
    )

    step = Step.factory.get("Odb.SetPowerConnections")
    assert jobs["custom"].steps == (step,)
    assert jobs["custom"].provider is None
    assert set(jobs["custom"].requires) == set(step.inputs)
    assert set(jobs["custom"].provides) == set(step.outputs)


def test_needs_and_condition_carry_through():
    jobs = resolve_jobs(
        _spec(
            {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {
                    "needs": ["synthesis"],
                    "uses": "floorplan",
                    "if": "RUN_FLOORPLAN",
                },
            }
        )
    )

    assert jobs["floorplan"].needs == ("synthesis",)
    assert jobs["floorplan"].condition == "RUN_FLOORPLAN"
    assert jobs["synthesis"].needs == ()
    assert jobs["synthesis"].condition is None


def test_source_keys_become_design_formats():
    jobs = resolve_jobs(
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

    assert jobs["xor"].source == {DesignFormat.gds: "klayout_streamout"}
```

Note: `test_a_minimal_flow_spec_round_trips_from_a_mapping` in phase 1 already
pins that `FlowSpec` validation runs on construction, so these specs are
structurally valid by the time `resolve_jobs` sees them. `resolve_jobs` does not
call `validate_against_registry` itself; the engine does, in Task 4.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_job.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.job'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/job.py`:

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
Binding a document's jobs to the registry, producing the units the engine runs.
"""

from dataclasses import dataclass

from librelane.stages import Stage, StageRegistry
from librelane.state import DesignFormat
from librelane.steps import Step
from librelane.flows.spec import FlowSpec, JobSpec


@dataclass(frozen=True)
class Job:
    """
    A resolved job: a document's declaration bound to a registered template.

    Never written by hand. ``needs``, ``source`` and ``condition`` come from the
    document; ``requires``, ``provides``, ``metrics`` and ``steps`` come from
    the template, or from the steps themselves for an inline job.
    """

    id: str
    needs: tuple[str, ...]
    source: dict[DesignFormat, str]
    condition: str | None
    requires: tuple[DesignFormat, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...]
    steps: tuple[type[Step], ...]
    provider: str | None


def resolve_jobs(spec: FlowSpec) -> dict[str, Job]:
    """
    Parameters
    ----------
    spec : FlowSpec
        A document that has passed ``validate_against_registry``.

    Returns
    -------
    Each job id mapped to its resolved :class:`Job`, in document
    order.
    """
    return {name: _resolve(name, job) for name, job in spec.jobs.items()}


def _resolve(name: str, spec: JobSpec) -> Job:
    source = {}
    for key, producer in spec.source.items():
        view = DesignFormat.factory.get(key)
        assert view is not None, "checked by _check_source_views_exist"
        source[view] = producer

    if spec.steps is not None:
        steps = []
        for step_id in spec.steps:
            step = Step.factory.get(step_id)
            assert step is not None, "checked by _check_steps"
            steps.append(step)
        requires: set[DesignFormat] = set()
        provides: set[DesignFormat] = set()
        for step in steps:
            requires.update(step.inputs)
            provides.update(step.outputs)
        return Job(
            id=name,
            needs=tuple(spec.needs),
            source=source,
            condition=spec.condition,
            requires=tuple(sorted(requires, key=str)),
            provides=tuple(sorted(provides, key=str)),
            metrics=(),
            steps=tuple(steps),
            provider=None,
        )

    assert spec.uses is not None, "checked by JobSpec validation"
    stage_id, _, named = spec.uses.partition("/")
    stage = Stage.factory.get(stage_id)
    assert stage is not None, "checked by _check_uses"
    providers = (named,) if named else stage.default_providers

    steps = []
    provides = set(stage.provides)
    metrics = set(stage.metrics)
    for provider in providers:
        registration = StageRegistry.get(stage_id, provider)
        assert registration is not None, "checked by _check_uses"
        steps.extend(registration.steps)
        provides.update(registration.provides)
        metrics.update(registration.metrics)

    return Job(
        id=name,
        needs=tuple(spec.needs),
        source=source,
        condition=spec.condition,
        requires=tuple(stage.requires),
        provides=tuple(sorted(provides, key=str)),
        metrics=tuple(sorted(metrics)),
        steps=tuple(steps),
        provider="+".join(providers),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_job.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/job.py test/flows/test_job.py
git commit -m "feat: resolve workflow document jobs against the registry"
```

---

### Task 4: The engine, sequentially

**Files:**
- Create: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `Net`, `Arc` (Task 1); `join_states`, `JoinConflictError` (Task 2); `Job`, `resolve_jobs` (Task 3); `resume_key`, `reusable_state`, `write_entry` from `librelane.flows.resume`.
- Produces:
  - `JobContractError(FlowError)`.
  - `Workflow(Flow)` with `__init__(self, spec: FlowSpec, *args, **kwargs)` and `run(self, initial_state, **kwargs) -> tuple[State, list[Step]]`.

**Design notes the implementer needs:**

`Workflow` subclasses the existing `Flow` so it inherits `run_dir`, `toolbox`, `fingerprinter`, `progress_bar`, `config` and `start_step`. Phase 5 removes `Flow` as a *subclassable declaration* base; the machinery stays, and `Workflow` is its one concrete consumer.

Fire in `topological_order`. Concurrency is Task 5; keeping this task single-threaded means every behaviour below is testable deterministically.

**Pass-through is the critical detail.** A job whose condition is false, or which is named by `--skip`, still fires. It consumes its input tokens, joins them, and deposits the joined state unchanged, running no steps. Suppressing the firing instead would leave its output places empty and block every descendant forever. This is also exactly today's semantics, in which state flows past a gated step.

The run directory for a job's step is `self.run_dir / job.id / f"{n + 1}-{slugify(step.id)}"`, where `n` is the step's index within the job. Do not use `Flow.dir_for_step`, whose positional numbering is global and meaningless once jobs can run concurrently.

After a job's steps run, check the contract: every view in `job.provides` must be present in the output state, and every name in `job.metrics` must be in `state.metrics`. A pass-through job is exempt, because it ran nothing.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_engine.py`:

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

from librelane.flows import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

_MINIMAL_DESIGN = {
    "DESIGN_NAME": "WHATEVER",
    "VERILOG_FILES": ["/cwd/src/a.v"],
}
_MOCK_PDK = {
    "design_dir": "/cwd",
    "pdk": "dummy",
    "scl": "dummy_scl",
    "pdk_root": "/pdk",
}


@pytest.fixture()
def counting_steps():
    """
    Two trivially registered steps that record the order they ran in, so a
    test can assert the engine's firing order without invoking a real tool.
    """
    from librelane.state import State
    from librelane.steps import Step

    order: list[str] = []

    @Step.factory.register()
    class First(Step):
        id = "Test.EngineFirst"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            order.append(self.id)
            return {}, {"first": 1}

    @Step.factory.register()
    class Second(Step):
        id = "Test.EngineSecond"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            order.append(self.id)
            return {}, {"second": 1}

    assert State is not None
    return order, First, Second


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_jobs_fire_in_topological_order(counting_steps, tmp_path):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
                "first": {"steps": ["Test.EngineFirst"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start(tag="t")

    assert order == ["Test.EngineFirst", "Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_false_condition_passes_state_through_without_running(
    counting_steps, tmp_path
):
    from librelane.config import Variable
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
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
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )
    assert Variable is not None

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start(tag="t")

    # 'first' did not run, but 'second' still did: the token was released.
    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_skipped_job_passes_state_through_without_running(counting_steps):
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
    flow.start(tag="t", skip=["first"])

    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_step_writes_into_its_job_s_directory(counting_steps):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start(tag="t")

    assert (flow.run_dir / "first" / "1-test-enginefirst").is_dir()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_that_does_not_produce_its_contract_raises(counting_steps):
    from librelane.flows.engine import JobContractError, Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class Liar(Step):
        id = "Test.EngineLiar"
        inputs = []
        outputs = [DesignFormat.nl]

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"liar": {"steps": ["Test.EngineLiar"]}}}
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    with pytest.raises(JobContractError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "liar" in message
    assert "nl" in message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.engine'`

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/engine.py`:

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
"""The engine that runs a workflow document on a Petri net."""

import pathlib
import shutil
from collections.abc import Iterable

from loguru import logger

from librelane.common import slugify
from librelane.state import State
from librelane.steps import DeferredStepError, Step, StepError, StepException
from librelane.flows.flow import Flow, FlowError, FlowException
from librelane.flows.job import Job, resolve_jobs
from librelane.flows.join import join_states
from librelane.flows.net import Arc, Net
from librelane.flows.resume import resume_key, reusable_state, write_entry
from librelane.flows.spec import FlowSpec
from librelane.flows.spec_graph import topological_order
from librelane.flows.spec_validation import validate_against_registry


class JobContractError(FlowError):
    """
    Raised when a job completes without having produced a view or metric it
    declared.
    """


class Workflow(Flow):
    """
    Runs a :class:`librelane.flows.spec.FlowSpec`.

    Parameters
    ----------
    spec
        The document to run. Validated against the registries here, so
        a document constructed in Python gets the same checks a loaded one does.
    """

    Steps: list[type[Step]] = []

    def __init__(self, spec: FlowSpec, *args, **kwargs) -> None:
        validate_against_registry(spec)
        self.spec = spec
        self.jobs = resolve_jobs(spec)
        self.Steps = [step for job in self.jobs.values() for step in job.steps]
        super().__init__(*args, **kwargs)

    def run(
        self,
        initial_state: State,
        skip: Iterable[str] | None = None,
        **kwargs,
    ) -> tuple[State, list[Step]]:
        """
        Parameters
        ----------
        initial_state : State
            The state deposited on the source place.
        skip : Iterable[str] | None
            Job ids to pass through without running.

        Returns
        -------
        ``(final_state, steps_run)``
        """
        skipped = set(skip or ())
        for name in skipped:
            if name not in self.jobs:
                raise FlowException(
                    f"--skip names '{name}', which flow '{self.spec.name}' "
                    f"does not declare. Declared jobs: {sorted(self.jobs)}."
                )

        net = Net(list(self.jobs), self.spec.edges())
        for arc in net.arcs:
            if arc.producer is None:
                net.put(arc, initial_state)

        self.progress_bar.set_max_stage_count(len(self.jobs))
        steps_run: list[Step] = []
        deferred: list[str] = []
        final = initial_state

        for name in topological_order(self.spec.edges()):
            job = self.jobs[name]
            tokens = self._tokens_for(net, job)
            state_in = join_states(tokens, job.source, name)

            self.progress_bar.start_stage(name)
            reason = self._pass_through_reason(job, name in skipped)
            if reason is not None:
                logger.info(f"Skipping job '{name}': {reason}.")
                state_out = state_in
            else:
                state_out = self._run_job(job, state_in, steps_run, deferred)
                self._check_contract(job, state_out)
            self.progress_bar.end_stage()

            net.fire(name, state_out)
            final = state_out

        if not net.is_complete():
            raise FlowException(
                f"Flow '{self.spec.name}' stalled: no job is enabled and "
                f"{sorted(net.stalled())} never ran."
            )
        if deferred:
            raise FlowError("\n".join(deferred))
        return final, steps_run

    def _tokens_for(self, net: Net, job: Job) -> dict[str, State]:
        arcs = net.inputs_of(job.id)
        tokens = net.consume(job.id)
        return {
            (arc.producer if arc.producer is not None else "<initial state>"): token
            for arc, token in zip(arcs, tokens)
        }

    def _pass_through_reason(self, job: Job, skipped: bool) -> str | None:
        if skipped:
            return "named by --skip"
        if job.condition is not None and not self.config[job.condition]:
            return f"'{job.condition}' is false"
        return None

    def _run_job(
        self,
        job: Job,
        state_in: State,
        steps_run: list[Step],
        deferred: list[str],
    ) -> State:
        current = state_in
        for index, cls in enumerate(job.steps):
            step = cls(config=self.config, state_in=current)
            step_dir = self.dir_for_job_step(job, index, step)
            assert self.fingerprinter is not None
            key = resume_key(step, current, self.fingerprinter)
            reused = reusable_state(step_dir, key, self.fingerprinter)
            if reused is not None:
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                steps_run.append(step)
                current = reused
                continue
            shutil.rmtree(step_dir, ignore_errors=True)
            steps_run.append(step)
            try:
                current = step.start(toolbox=self.toolbox, step_dir=step_dir)
            except StepException as e:
                raise FlowException(str(e)) from None
            except DeferredStepError as e:
                deferred.append(str(e))
            except StepError as e:
                raise FlowError(str(e)) from None
            else:
                write_entry(step_dir, step, key)
        return current

    def dir_for_job_step(self, job: Job, index: int, step: Step) -> pathlib.Path:
        """
        Returns
        -------
        ``<run_dir>/<job id>/<n>-<step slug>``.

        Keyed by the job rather than by a global counter, because under
        concurrency there is no global step order and a positional prefix would
        change whenever an unrelated edge was added, invalidating resume for
        every step after it.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to name a step directory before the flow started."
            )
        width = len(str(len(job.steps)))
        return self.run_dir / job.id / f"{index + 1:0{width}d}-{slugify(step.id)}"

    def _check_contract(self, job: Job, state: State) -> None:
        for view in job.provides:
            if state.get(view) is None:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing view "
                    f"'{view}', which it declares. Provider: "
                    f"{job.provider or 'inline steps'}."
                )
        for metric in job.metrics:
            if metric not in state.metrics:
                raise JobContractError(
                    f"Job '{job.id}' completed without producing metric "
                    f"'{metric}', which it declares. Provider: "
                    f"{job.provider or 'inline steps'}."
                )
```

Note on `Arc`: it is imported for the source-place loop above and for the type
of `net.inputs_of`. If ruff reports it unused after your edit, the loop is
wrong — the source arcs are the ones with `producer is None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/engine.py test/flows/test_engine.py
git commit -m "feat: run a workflow document on the net"
```

---

### Task 5: Concurrency and failure

**Files:**
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: no new public names. `Workflow.run` gains concurrent firing and multi-failure reporting.

**Design notes the implementer needs:**

Replace the `topological_order` loop with a marking loop. While the net is not complete, take `net.enabled()`, submit each to `get_tpe()` up to the cap, and fire each as its future completes. `librelane.common.get_tpe()` returns the process-wide `ThreadPoolExecutor` already sized from `-j`, so there is no new pool to manage.

Two ordering details matter. `net.consume(job)` and `net.fire(job, state)` must both happen on the main thread, not inside the worker, because the marking is not thread-safe and making it so would be a lock protecting one dictionary against a scheduler that does not need to contend. Consume before submitting, fire when the future resolves.

**On failure, stop enabling new jobs but let in-flight jobs finish.** Cancelling immediately discards work already completed and hides a second, independent failure, which under concurrency is exactly the information wanted. Collect every failure and raise once, naming every failed job.

`DeferredStepError` keeps its existing meaning: the job continues, the error is collected, and the flow raises at the end.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_independent_branches_both_run():
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    ran: list[str] = []

    @Step.factory.register()
    class Left(Step):
        id = "Test.EngineLeft"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("left")
            return {}, {}

    @Step.factory.register()
    class Right(Step):
        id = "Test.EngineRight"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("right")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Diamond",
            "jobs": {
                "left": {"steps": ["Test.EngineLeft"]},
                "right": {"steps": ["Test.EngineRight"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start(tag="t")

    assert sorted(ran) == ["left", "right"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_failure_reports_every_failed_job_not_just_the_first():
    from librelane.common.errors import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step
    from librelane.steps.step.exceptions import StepError

    @Step.factory.register()
    class BadLeft(Step):
        id = "Test.EngineBadLeft"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("left exploded")

    @Step.factory.register()
    class BadRight(Step):
        id = "Test.EngineBadRight"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("right exploded")

    spec = FlowSpec.model_validate(
        {
            "name": "Diamond",
            "jobs": {
                "left": {"steps": ["Test.EngineBadLeft"]},
                "right": {"steps": ["Test.EngineBadRight"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "left" in message
    assert "right" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_downstream_of_a_failure_does_not_run():
    from librelane.common.errors import FlowError
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step
    from librelane.steps.step.exceptions import StepError

    ran: list[str] = []

    @Step.factory.register()
    class Exploder(Step):
        id = "Test.EngineExploder"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("boom")

    @Step.factory.register()
    class Downstream(Step):
        id = "Test.EngineDownstream"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("downstream")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Chain",
            "jobs": {
                "boom": {"steps": ["Test.EngineExploder"]},
                "after": {"needs": ["boom"], "steps": ["Test.EngineDownstream"]},
            },
        }
    )

    flow = Workflow(spec, _MINIMAL_DESIGN, **_MOCK_PDK)
    with pytest.raises(FlowError):
        flow.start(tag="t")

    assert ran == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: `test_a_failure_reports_every_failed_job_not_just_the_first` FAILS, because the sequential loop raises on the first failure and never reaches the second job. The other two pass under the sequential implementation.

- [ ] **Step 3: Replace the run loop**

In `librelane/flows/engine.py`, replace the body of `run` between the progress-bar line and the `if not net.is_complete()` check with a marking loop:

```python
        self.progress_bar.set_max_stage_count(len(self.jobs))
        steps_run: list[Step] = []
        deferred: list[str] = []
        failures: list[str] = []
        final = initial_state
        pending: dict[Future[State], str] = {}

        while True:
            if not failures:
                for name in net.enabled():
                    job = self.jobs[name]
                    tokens = self._tokens_for(net, job)
                    state_in = join_states(tokens, job.source, name)
                    self.progress_bar.start_stage(name)
                    reason = self._pass_through_reason(job, name in skipped)
                    if reason is not None:
                        logger.info(f"Skipping job '{name}': {reason}.")
                        net.fire(name, state_in)
                        final = state_in
                        self.progress_bar.end_stage()
                        continue
                    pending[
                        get_tpe().submit(
                            self._run_job, job, state_in, steps_run, deferred
                        )
                    ] = name
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                name = pending.pop(future)
                try:
                    state_out = future.result()
                except FlowError as e:
                    failures.append(f"Job '{name}': {e}")
                    self.progress_bar.end_stage()
                    continue
                self._check_contract(self.jobs[name], state_out)
                net.fire(name, state_out)
                final = state_out
                self.progress_bar.end_stage()

        if failures:
            raise FlowError("\n".join(failures))
```

Extend the imports at the top of the file:

```python
from concurrent.futures import FIRST_COMPLETED, Future, wait

from librelane.common import get_tpe, slugify
```

Delete the now-unused `topological_order` import. The net's enablement replaces
it: a job becomes enabled exactly when its predecessors have fired, which is a
topological order computed incrementally rather than up front.

The `if not net.is_complete()` stall check stays where it is, and now has real
work to do: a failure leaves descendants unfired, and the check names them.
Move it below the `if failures` raise so a genuine failure is reported as a
failure rather than as a stall.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 6: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/engine.py test/flows/test_engine.py
git commit -m "feat: fire independent workflow jobs concurrently"
```

---

## What this phase does not do

No shipped flow runs on `Workflow` yet, and `librelane/flows/__init__.py` is deliberately not touched. `Stage` is still `Stage`, the six flows are still Python classes on `StagedFlow`, and the command-line surface still has `--from` and `--to`. Those are phases 3, 4 and 5.
