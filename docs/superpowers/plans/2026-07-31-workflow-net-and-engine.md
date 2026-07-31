# Workflow Net and Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Petri net, the state join and the engine that runs a `FlowSpec`, as a pure addition that the shipped flows do not yet use.

**Architecture:** A net holds one place per arc and fires a transition when every input place holds a token. The engine resolves a `FlowSpec` into concrete `Job` objects, builds a net from the job graph, and fires jobs as their input places fill, merging the input tokens into one `State` per job. A job whose condition is false fires as a pass-through, depositing its input state unchanged. The flow's final state is the join of the tokens left on the sink places, or the output of the job the document's `final` key names. Concurrency and failure semantics are the last task, so every earlier task is testable with a deterministic single-threaded run.

**Tech Stack:** Python 3.11+, `concurrent.futures` through the existing `librelane.common.get_tpe()`, pytest with pytest-mock, uv.

**Six tasks, 41 new tests.** 12 in `test/flows/test_net.py`, 8 in `test/flows/test_join.py`, 7 in `test/flows/test_job.py`, 14 in `test/flows/test_engine.py`.

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

- `librelane.flows.spec.FlowSpec` with `name: str`, `description: str`, `config: list[VariableSpec]`, `jobs: dict[str, JobSpec]`, `final: str | None`, and `edges() -> dict[str, list[str]]`.
- `librelane.flows.spec.JobSpec` with `needs: list[str]`, `uses: str | None`, `steps: list[str] | None`, `source: dict[str, str]`, `condition: str | None`.
- `librelane.flows.spec.VariableSpec.to_variable() -> librelane.config.Variable`.
- `librelane.flows.spec.parse_condition(text: str) -> tuple[str, ...]`, which splits an `if` conjunction into its variable names and raises `FlowSpecError` on anything that is not `A` or `A and B and C`.
- `librelane.flows.spec.FlowSpecError(FlowError)`.
- `librelane.flows.spec.load_flow_spec(source) -> FlowSpec`.
- `librelane.flows.spec_graph.topological_order(edges) -> list[str]`, `ancestors(edges, node) -> set[str]`, `descendants(edges, node) -> set[str]`.
- `librelane.flows.spec_validation.validate_against_registry(spec) -> None`.
- `librelane.stages.StageRegistry.providers(stage) -> list[str]` (`librelane/stages/registry.py:219`) and `StageRegistry.get(stage, provider) -> Registration | None` (`librelane/stages/registry.py:215`).

`JobSpec.source` and the resolved `Job.source` are both `dict[str, str]`. The key is a view id **or** a metric name, because the join rule is one rule over views and metrics and a metric name such as `magic__drc_error__count` is not a `DesignFormat`. Do not convert the key to a `DesignFormat`.

## Existing APIs this phase consumes

Every line number below was opened in this checkout.

- `librelane.flows.resume.resume_key(step: Step, state_in: State, fingerprinter: Fingerprinter) -> str`
- `librelane.flows.resume.reusable_state(step_dir, key: str, fingerprinter: Fingerprinter) -> State | None`, which returns `None` for every way a hit cannot be proven.
- `librelane.flows.resume.write_entry(step_dir, step: Step, key: str) -> None`, called only after the step returns without raising.
- `Step.start(toolbox=..., step_dir=...) -> State`. Raises `StepException` (fatal), `StepError` (fatal), or `DeferredStepError` (collect and continue). It enforces declared **inputs** only (`librelane/steps/step/core.py:656-661`) and never checks that a step produced its declared outputs, which is why the job contract check in Task 4 has real work to do.
- `State(copying=..., overrides=..., metrics=...)`, an immutable mapping whose keys are stored as view **id strings**. `dict(state)` therefore yields `{"nl": Path(...)}`, not `{DesignFormat.nl: ...}`. `state[DesignFormat.nl]` and `state.get(DesignFormat.nl)` both work because `__getitem__` normalises a `DesignFormat` to its id, and `state.get_by_df(view)` is the explicit spelling.
- `Flow.config_vars` defaults to `[]` (`librelane/flows/flow.py:443`) and `Flow.get_all_config_variables` (`librelane/flows/flow.py:597`) unions the universal set, `self.config_vars` and every step's `config_vars`.
- `Flow.__init__` (`librelane/flows/flow.py:464`) calls `self.get_all_config_variables()` to build the `Config`, so anything a subclass wants in the configuration must be assigned **before** the `super().__init__` call.
- `Flow.start` calls `self.run(initial_state=..., initial_state_given=..., starting_ordinal=..., **kwargs)` and returns the first element of the pair `run` returns.
- `librelane.common.get_tpe()` returns the process-wide `ThreadPoolExecutor`.
- `librelane.common.slugify("Test.EngineFirst")` returns `"test-enginefirst"`.

## File Structure

| File | Responsibility |
| --- | --- |
| `librelane/flows/net.py` | `Arc`, `Net`. Places, marking, enablement, firing, sink tokens. Tokens are `Any`, so the module has no domain imports. |
| `librelane/flows/join.py` | `join_states(tokens, source, job) -> State`. The equal-merges rule and the conflict error. |
| `librelane/flows/job.py` | The resolved `Job` dataclass and `resolve_jobs(spec) -> dict[str, Job]`. |
| `librelane/flows/engine.py` | `Workflow`. Builds the net, fires jobs, checks contracts, joins the sinks, handles failure and concurrency. |
| `test/flows/conftest.py` | Modified. Gains the `counting_steps`, `mock_pdk` and `minimal_design` fixtures phases 2 and 4 share. |
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
  - `Net(jobs: Sequence[str], edges: dict[str, list[str]])` with `arcs: tuple[Arc, ...]`, `inputs_of(job) -> tuple[Arc, ...]`, `outputs_of(job) -> tuple[Arc, ...]`, `put(arc, token) -> None`, `enabled() -> list[str]`, `consume(job) -> list[Any]`, `fire(job, token) -> None`, `sink_tokens() -> dict[str, Any]`, `fired: set[str]`, `is_complete() -> bool`, `stalled() -> list[str]`.

**Design notes the implementer needs:**

One place per arc, not per job. A job with two consumers deposits one token on each of its two outgoing places. With one place per job, fan-out would force the producer to deposit N tokens and the scheduler to know N, leaking the fan-out count into the encoding. Per-arc keeps the firing rule literally "consume one token from each input place, deposit one on each output place", which is what spec 3 extends without rewriting.

`fire` takes a single token and deposits a copy of it on every output arc, because a job produces one output state regardless of how many consumers read it.

`consume` removes the tokens rather than peeking, so a place never silently feeds two firings. Depositing onto an occupied place raises `NetError`. Neither can happen on an acyclic graph, and that is exactly why both are asserted now. They are what a spec 3 marking bug trips first.

`sink_tokens` exists because the flow's final state is the join of the sink places, not whichever leaf happened to sort last. Nothing consumes a sink place, so the tokens are still there when the run finishes and the net is the authority on the marking. It raises rather than skipping an unmarked sink, so a caller that asks before the run completes gets an error instead of a short dictionary.

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


def _run_diamond(net: Net) -> None:
    for job in _DIAMOND_JOBS:
        net.consume(job)
        net.fire(job, f"{job}-out")


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

    _run_diamond(net)

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


def test_sink_tokens_names_every_leaf_and_the_token_it_left():
    # Two leaves, so the flow's final state is a join rather than one token.
    net = Net(["streamout", "drc", "lvs"], {"streamout": [], "drc": ["streamout"], "lvs": ["streamout"]})
    net.put(Arc(None, "streamout"), "initial")
    for job in ["streamout", "drc", "lvs"]:
        net.consume(job)
        net.fire(job, f"{job}-out")

    assert net.sink_tokens() == {"drc": "drc-out", "lvs": "lvs-out"}


def test_sink_tokens_raises_while_a_leaf_has_not_fired():
    net = _diamond()
    net.put(Arc(None, "streamout"), "initial")
    net.consume("streamout")
    net.fire("streamout", "gds")

    with pytest.raises(NetError) as exc_info:
        net.sink_tokens()

    assert "xor" in str(exc_info.value)
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
the firing rule literally true as stated, namely consume one token from each
input place and deposit one on each output place.

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
    cannot happen, and that is why it is checked. It is what a marking bug in a
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

    def sink_tokens(self) -> dict[str, Any]:
        """
        Returns
        -------
        The token each leaf job left on its sink place, keyed by that
        job. Nothing consumes a sink place, so these are the tokens the flow's
        final state is joined from.

        Raises
        ------
        NetError
            If any sink place is unmarked, which means the job
            that feeds it has not fired.
        """
        tokens: dict[str, Any] = {}
        for arc in self.arcs:
            if arc.consumer is not None:
                continue
            assert arc.producer is not None, "a sink arc always names a producer"
            if arc not in self._marking:
                raise NetError(
                    f"Sink place {arc} holds no token, so job "
                    f"'{arc.producer}' has not fired."
                )
            tokens[arc.producer] = self._marking[arc]
        return tokens

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
Expected: 12 passed

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
- Produces: `join_states(tokens: dict[str, State], source: dict[str, str], job: str) -> State`, raising `JoinConflictError(FlowError)`.

**Design notes the implementer needs:**

One rule covers views and metrics both. **Equal values merge silently; unequal values are a conflict.** A view or metric inherited from a common ancestor is identical down both branches and needs no declaration. A key that two branches wrote differently is genuinely ambiguous, and `source` must name the producer.

**`source` is consulted only for a key whose contributing predecessors do not all carry the same value.** A key exactly one predecessor carries is unambiguous, and the join takes it without reading `source` at all. This is the scope of the rule, not a softening of it. The spec's words are that `source` resolves a fan-in conflict, and where there is no conflict there is nothing to resolve. Treating `source` as a mandatory routing directive instead is a strictly stronger rule that the shipped documents do not satisfy.

The case that settles it is `magic_drc` in phase 4's `classic.yaml`, which needs both streamouts and carries `source: {gds: klayout_streamout}`. With `RUN_KLAYOUT_STREAMOUT` false, `klayout_streamout` still fires as a pass-through and deposits its input state unchanged, carrying no `gds`. Only `magic_streamout` contributes `gds`, so there is no conflict and the join takes Magic's. Under the stronger rule the flow would die at run time on an ordinary configuration, and every `gds` consumer would have to repeat `RUN_KLAYOUT_STREAMOUT` in its `if`. Phase 4's truth table for the four combinations of `RUN_MAGIC_STREAMOUT` and `RUN_KLAYOUT_STREAMOUT` is at `docs/superpowers/plans/2026-07-31-migrate-flows-to-documents.md:156-161`.

This removes nothing from load time. Phase 1's `_check_sources_can_deliver` asks whether the named predecessor's branch **can** produce the key, which is a static property of the declared `provides` and is unaffected. Static capability and run-time presence are different questions, and only the first is answerable before the run.

Because `source` is now read only inside the conflict branch, there is no unconditional pre-check that the named producer is a predecessor at all. Phase 1's `_check_sources_name_direct_predecessors` already requires a direct predecessor at load, and a bogus name that does reach a real conflict is still diagnosed, by the `for`/`else` in `_merge`.

No provenance tagging is needed. Path equality answers the question, because a rewritten view lands in a different job directory by construction.

`source` is `dict[str, str]` and its key is a view id **or** a metric name. One rule over both namespaces means one lookup table over both, and a metric name is not a `DesignFormat`, so a `dict[DesignFormat, str]` could not express the metric half at all. `_merge` is therefore handed the whole `source` for the view pass and again for the metric pass. A key addressed at the other namespace simply matches nothing in that pass, which is why the unresolved-selection check below is guarded on the key having been produced at all.

`State` stores its keys as view id strings, so `dict(state)` already yields `{"gds": Path(...)}` and no `DesignFormat`-to-string conversion is needed anywhere in this module.

`tokens` is keyed by the producing job so the error can name both producers and so `source` can select one. A job with a single predecessor never conflicts, so the single-token path returns that token unchanged.

The realistic conflict this exists for is `Magic.StreamOut` and `KLayout.StreamOut`. Verified in this checkout, `Magic.StreamOut.outputs` is `[gds, mag_gds, mag]` and `KLayout.StreamOut.outputs` is `[gds, klayout_gds]`, so two streamout jobs joining at `xor` genuinely disagree on `gds` while agreeing on nothing else. Two of the tests below use that shape rather than an invented one.

`DesignFormat.mag_gds` and `DesignFormat.klayout_gds` are registered by the step packages, not declared on the class. Verified in this checkout, `getattr(DesignFormat, "mag_gds")` raises until `librelane.steps` has been imported, which is why the test module imports it. `gds`, `nl`, `def_` and `sdc` resolve without it.

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

import librelane.steps  # noqa: F401  registers mag_gds and klayout_gds

from librelane.common import Path
from librelane.flows.join import JoinConflictError, join_states
from librelane.state import DesignFormat, State

pytestmark = pytest.mark.all


def _magic_streamout() -> State:
    """The views Magic.StreamOut declares, as it would leave them."""
    return State(
        {
            DesignFormat.gds: Path("/runs/t/magic_streamout/1-magic-streamout/a.gds"),
            DesignFormat.mag_gds: Path(
                "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
            ),
        }
    )


def _klayout_streamout() -> State:
    """The views KLayout.StreamOut declares, as it would leave them."""
    return State(
        {
            DesignFormat.gds: Path(
                "/runs/t/klayout_streamout/1-klayout-streamout/a.gds"
            ),
            DesignFormat.klayout_gds: Path(
                "/runs/t/klayout_streamout/1-klayout-streamout/a.klayout.gds"
            ),
        }
    )


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


def test_the_two_streamout_providers_conflict_on_gds():
    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
            },
            {},
            "xor",
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "source" in message


def test_a_declared_source_picks_one_gds_and_keeps_both_native_views():
    joined = join_states(
        {
            "magic_streamout": _magic_streamout(),
            "klayout_streamout": _klayout_streamout(),
        },
        {"gds": "klayout_streamout"},
        "xor",
    )

    assert joined[DesignFormat.gds] == Path(
        "/runs/t/klayout_streamout/1-klayout-streamout/a.gds"
    )
    # mag_gds and klayout_gds are what KLayout.XOR actually consumes, and
    # neither is in conflict, so selecting gds must not drop either.
    assert joined[DesignFormat.mag_gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
    )
    assert joined[DesignFormat.klayout_gds] == Path(
        "/runs/t/klayout_streamout/1-klayout-streamout/a.klayout.gds"
    )


def test_differing_metrics_conflict_under_the_same_rule():
    left = State({}, metrics={"magic__drc_error__count": 100})
    right = State({}, metrics={"magic__drc_error__count": 200})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states({"early_drc": left, "late_drc": right}, {}, "signoff")

    message = str(exc_info.value)
    assert "magic__drc_error__count" in message
    assert "early_drc" in message and "late_drc" in message


def test_a_declared_source_selects_one_producer_of_a_metric():
    left = State({}, metrics={"magic__drc_error__count": 100})
    right = State({}, metrics={"magic__drc_error__count": 200})

    joined = join_states(
        {"early_drc": left, "late_drc": right},
        {"magic__drc_error__count": "late_drc"},
        "signoff",
    )

    assert joined.metrics == {"magic__drc_error__count": 200}


def test_a_source_is_ignored_when_only_one_predecessor_carries_the_key():
    # phase 4's classic.yaml, with RUN_KLAYOUT_STREAMOUT false. Both
    # predecessors fired, but the gated one passed its input state through and
    # carries no gds, so nothing is in conflict and Magic's gds is taken even
    # though 'source' names the other job.
    gated_off = State({})

    joined = join_states(
        {"magic_streamout": _magic_streamout(), "klayout_streamout": gated_off},
        {"gds": "klayout_streamout"},
        "magic_drc",
    )

    assert joined[DesignFormat.gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.gds"
    )
    assert joined[DesignFormat.mag_gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
    )


def test_a_source_naming_a_job_that_contributed_nothing_to_the_conflict_raises():
    # Two producers genuinely disagree on gds, so 'source' is read, and it
    # names a third predecessor that carried no gds at all. Nothing selects it,
    # and silently dropping the view would be worse than saying so.
    gated_off = State({})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
                "render": gated_off,
            },
            {"gds": "render"},
            "xor",
        )

    message = str(exc_info.value)
    assert "render" in message
    assert "gds" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
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

One rule covers views and metrics both. Equal values merge silently, unequal
values are a conflict the document must resolve with ``source``. A view or
metric inherited from a common ancestor is identical down both branches and
needs no declaration; a key two branches wrote differently is genuinely
ambiguous, and guessing would silently pick one tool's output over another's.

``source`` is a tie-breaker, not a routing directive. It is read only for a key
whose contributing predecessors disagree. A key exactly one predecessor carries
is unambiguous and is taken without ``source`` entering into it, which is what
lets a gated-off producer pass through carrying nothing while a consumer that
names it in ``source`` still runs.

``source`` keys are plain strings for the same reason the rule is one rule. A
view is addressed by its id and a metric by its name, and one rule over both
namespaces cannot be expressed by a mapping keyed on
:class:`librelane.state.DesignFormat`.
"""

from typing import Any

from librelane.common.errors import FlowError
from librelane.state import State


class JoinConflictError(FlowError):
    """
    Raised when two of a job's predecessors produced different values for one
    view or metric and the document did not declare which to use, or when a
    declared ``source`` cannot be honoured.
    """


def join_states(
    tokens: dict[str, State],
    source: dict[str, str],
    job: str,
) -> State:
    """
    Parameters
    ----------
    tokens : dict[str, State]
        Each predecessor's output state, keyed by the producing job.
    source : dict[str, str]
        The job's declared per-key resolution. A key is a view id or
        a metric name.
    job : str
        The consuming job, named in errors.

    Returns
    -------
    The merged state.

    Raises
    ------
    JoinConflictError
        On a conflict the document did not declare a ``source``
        for, or on a ``source`` that names a job which contributed no value to
        the conflict it was meant to resolve.
    """
    if len(tokens) == 1:
        return next(iter(tokens.values()))

    views = _merge(
        {name: dict(state) for name, state in tokens.items()},
        source,
        job,
        "view",
    )
    metrics = _merge(
        {name: dict(state.metrics) for name, state in tokens.items()},
        source,
        job,
        "metric",
    )
    return State(views, metrics=metrics)


def _merge(
    contributions: dict[str, dict[str, Any]],
    selected: dict[str, str],
    job: str,
    kind: str,
) -> dict[str, Any]:
    """
    Merges one namespace, either the views or the metrics.

    Gathers each key's contributors first, then decides per key. ``selected``
    is read only for a key whose contributors disagree, because a key exactly
    one predecessor carries is not ambiguous and there is nothing for a
    conflict-resolution parameter to resolve.

    ``selected`` is the job's whole ``source`` mapping, covering both
    namespaces. An entry addressed at the other namespace matches no key here
    and is left to that namespace's own pass.
    """
    contributors: dict[str, list[tuple[str, Any]]] = {}
    for producer, mapping in contributions.items():
        for key, value in mapping.items():
            contributors.setdefault(key, []).append((producer, value))

    merged: dict[str, Any] = {}
    for key, produced in contributors.items():
        first = produced[0][1]
        if all(value == first for _, value in produced):
            merged[key] = first
            continue

        producers = [producer for producer, _ in produced]
        chosen = selected.get(key)
        if chosen is None:
            raise JoinConflictError(
                f"Job '{job}' joins {producers}, which produced different "
                f"values for {kind} '{key}'. Declare which one it comes from "
                f"with 'source: {{{key}: {producers[0]}}}' or "
                f"'source: {{{key}: {producers[1]}}}'."
            )
        for producer, value in produced:
            if producer == chosen:
                merged[key] = value
                break
        else:
            raise JoinConflictError(
                f"Job '{job}' sources {kind} '{key}' from '{chosen}', which "
                f"contributed no value for it to this join. The predecessors "
                f"that disagree on '{key}' are {producers}."
            )
    return merged
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_join.py -v`
Expected: 8 passed

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
- Consumes: `FlowSpec`, `JobSpec`, `parse_condition` from phase 1; `Stage`, `StageRegistry` from `librelane.stages`; `Step` from `librelane.steps`.
- Produces:
  - `Job` frozen dataclass with `id: str`, `needs: tuple[str, ...]`, `source: dict[str, str]`, `conditions: tuple[str, ...]`, `requires: tuple[DesignFormat, ...]`, `provides: tuple[DesignFormat, ...]`, `metrics: tuple[str, ...]`, `steps: tuple[type[Step], ...]`, `provider: str | None`.
  - `resolve_jobs(spec: FlowSpec) -> dict[str, Job]`.

**Design notes the implementer needs:**

`resolve_jobs` binds each `JobSpec` to its registered template and produces the concrete unit the engine runs. It assumes `validate_against_registry` already passed, so every name resolves; assertions rather than errors guard that assumption.

For a `uses` job, `steps` comes from `StageRegistry.get(stage, provider).steps`, `requires` from `Stage.requires`, and `provides`/`metrics` from the stage's union the registration's. A bare `uses` names the stage's `default_providers`, which is a tuple for a `multi_provider` stage, so concatenate every one of their step sequences in order rather than taking the first.

For a `steps` job there is no template, so `requires` is the union of the steps' `inputs`, `provides` the union of their `outputs`, `metrics` empty, and `provider` `None`.

`source` is carried through as `dict[str, str]` with no conversion, because its key may be a metric name as well as a view id. See Task 2.

**`conditions`, not `condition`.** The spec's `if` is a conjunction, written `A` or `A and B and C`, and the job runs only when every named variable is true. Phase 1 owns the grammar and rejects anything else at load, exposing `parse_condition`. This module calls it once so the engine never re-parses, and a job with no `if` gets the empty tuple rather than a `None` the engine would have to test for separately.

**`full_name` is deliberately not carried.** The spec's job dataclass lists it, and this plan drops it on the following evidence, gathered in this checkout. `Stage.full_name` is declared at `librelane/stages/stage.py:100` and read in no Python file under `librelane/` or `test/`; the only `.full_name` readers are `librelane/steps/step/reporting.py:133` and `:207`, and both read `DesignFormat.full_name`. Neither phase 3, 4 nor 5 names it, and phase 4's `--explain` table keys every row on `job_id`. The one plausible run-time consumer, `FlowProgressBar.start_stage(name)` at `librelane/flows/flow.py:244`, would be made worse by it, because a stage's `full_name` is not unique across jobs. `magic_streamout` and `klayout_streamout` are both the `streamout` stage, so both would display "Layout Stream-Out" while their job ids are already distinct and already correct. Nothing is lost from the registry, since the template keeps the field. If a consumer ever appears, it reaches the template through `uses`.

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
from librelane.stages import Stage, StageRegistry
from librelane.state import DesignFormat
from librelane.steps import Step

pytestmark = pytest.mark.all


def _spec(jobs: dict) -> FlowSpec:
    return FlowSpec.model_validate({"name": "Tiny", "jobs": jobs})


def test_a_uses_job_takes_its_steps_from_the_named_provider():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))

    job = jobs["synthesis"]
    assert job.provider == "yosys"
    # Asserted against the registration itself. The provider's steps are
    # Yosys.JsonHeader, Yosys.Synthesis and three Checker.* classes, so a
    # prefix assertion on 'Yosys.' would be false.
    assert job.steps == tuple(StageRegistry.get("synthesis", "yosys").steps)


def test_a_bare_uses_takes_the_stage_default_provider():
    named = resolve_jobs(_spec({"floorplan": {"uses": "floorplan/openroad"}}))
    bare = resolve_jobs(_spec({"floorplan": {"uses": "floorplan"}}))

    assert bare["floorplan"].steps == named["floorplan"].steps
    assert bare["floorplan"].provider == "openroad"


def test_a_uses_job_inherits_the_stage_contract():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))
    job = jobs["synthesis"]
    registration = StageRegistry.get("synthesis", "yosys")

    # Stage.synthesis.requires is empty, so an equality assertion against it
    # would be vacuous. Assert the union rule itself instead.
    assert job.requires == Stage.synthesis.requires
    assert set(job.provides) == set(Stage.synthesis.provides) | set(
        registration.provides
    )
    assert set(job.metrics) == set(Stage.synthesis.metrics) | set(
        registration.metrics
    )
    assert DesignFormat.nl in job.provides
    assert DesignFormat.json_h in job.provides


def test_an_inline_job_derives_its_contract_from_its_steps():
    jobs = resolve_jobs(_spec({"custom": {"steps": ["Odb.SetPowerConnections"]}}))

    step = Step.factory.get("Odb.SetPowerConnections")
    assert jobs["custom"].steps == (step,)
    assert jobs["custom"].provider is None
    assert set(jobs["custom"].requires) == set(step.inputs)
    assert set(jobs["custom"].provides) == set(step.outputs)
    assert jobs["custom"].metrics == ()


def test_needs_and_a_single_condition_carry_through():
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
    assert jobs["floorplan"].conditions == ("RUN_FLOORPLAN",)
    assert jobs["synthesis"].needs == ()
    assert jobs["synthesis"].conditions == ()


def test_a_conjunction_becomes_one_entry_per_conjunct():
    jobs = resolve_jobs(
        _spec(
            {
                "xor": {
                    "steps": ["KLayout.XOR", "Checker.XOR"],
                    "if": (
                        "RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT "
                        "and RUN_KLAYOUT_STREAMOUT"
                    ),
                }
            }
        )
    )

    assert jobs["xor"].conditions == (
        "RUN_KLAYOUT_XOR",
        "RUN_MAGIC_STREAMOUT",
        "RUN_KLAYOUT_STREAMOUT",
    )


def test_source_keys_carry_through_as_declared_strings():
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
                    "steps": ["KLayout.XOR", "Checker.XOR"],
                    "source": {"gds": "klayout_streamout"},
                },
            }
        )
    )

    # A source key may name a metric as well as a view, so it stays a string.
    assert jobs["xor"].source == {"gds": "klayout_streamout"}
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
from librelane.flows.spec import FlowSpec, JobSpec, parse_condition


@dataclass(frozen=True)
class Job:
    """
    A resolved job, a document's declaration bound to a registered template.

    Never written by hand. ``needs``, ``source`` and ``conditions`` come from
    the document; ``requires``, ``provides``, ``metrics`` and ``steps`` come
    from the template, or from the steps themselves for an inline job.

    ``source`` is keyed by string rather than by
    :class:`librelane.state.DesignFormat` because the join rule is one rule
    over views and metrics and a metric name is not a view.

    ``conditions`` is the ``if`` conjunction already split into its variable
    names, empty when the job declares no ``if``. The job runs when every named
    variable is true.
    """

    id: str
    needs: tuple[str, ...]
    source: dict[str, str]
    conditions: tuple[str, ...]
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
    conditions = () if spec.condition is None else parse_condition(spec.condition)

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
            source=dict(spec.source),
            conditions=conditions,
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
        source=dict(spec.source),
        conditions=conditions,
        requires=tuple(stage.requires),
        provides=tuple(sorted(provides, key=str)),
        metrics=tuple(sorted(metrics)),
        steps=tuple(steps),
        provider="+".join(providers),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_job.py -v`
Expected: 7 passed

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
- Modify: `test/flows/conftest.py`
- Create: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `Net` (Task 1); `join_states`, `JoinConflictError` (Task 2); `Job`, `resolve_jobs` (Task 3); `resume_key`, `reusable_state`, `write_entry` from `librelane.flows.resume`.
- Produces:
  - `JobContractError(FlowError)`.
  - `Workflow(Flow)` with `__init__(self, spec: FlowSpec, *args, **kwargs)` and `run(self, initial_state, **kwargs) -> tuple[State, list[Step]]`.
  - Shared pytest fixtures `counting_steps`, `mock_pdk` and `minimal_design` in `test/flows/conftest.py`, which phase 4's `test_engine.py` and `test_explain.py` additions also use.

**Design notes the implementer needs:**

`Workflow` subclasses the existing `Flow` so it inherits `run_dir`, `toolbox`, `fingerprinter`, `progress_bar`, `config` and `start_step`. Phase 5 removes `Flow` as a *subclassable declaration* base; the machinery stays, and `Workflow` is its one concrete consumer.

**Two things must be assigned before `super().__init__`.** `Flow.__init__` at `librelane/flows/flow.py:464` builds the `Config` from `self.get_all_config_variables()`, which unions the universal variables, `self.config_vars` and every step's own. `Flow.config_vars` defaults to `[]` at `librelane/flows/flow.py:443`, so a document's `config` block reaches the configuration only if `self.config_vars` is populated first, and `self.config[variable]` in the condition test raises `KeyError` otherwise. The same constructor resolves `self.name` from the class name when the instance has not already set one, so `self.name = spec.name` must also precede the call or every document would be called "Workflow" and the run directory would say so.

Fire in `topological_order`. Concurrency is Task 6; keeping this task single-threaded means every behaviour below is testable deterministically.

**Pass-through is the critical detail.** A job whose conjunction has a false conjunct, or which is named by `--skip`, still fires. It consumes its input tokens, joins them, and deposits the joined state unchanged, running no steps. Suppressing the firing instead would leave its output places empty and block every descendant forever. This is also exactly today's semantics, in which state flows past a gated step.

The run directory for a job's step is `self.run_dir / job.id / f"{n + 1}-{slugify(step.id)}"`, where `n` is the step's index within the job. Do not use `Flow.dir_for_step`, whose positional numbering is global and meaningless once jobs can run concurrently.

After a job's steps run, check the contract. Every view in `job.provides` must be present in the output state, and every name in `job.metrics` must be in `state.metrics`. A pass-through job is exempt, because it ran nothing. This check has real work to do because `Step.start` validates declared inputs only (`librelane/steps/step/core.py:656-661`) and never checks outputs.

**Why the fixtures move to `conftest.py`.** Phase 4 needs the same fake steps and the same mock PDK, and a fixture defined in `test/flows/test_engine.py` is invisible to `test/flows/test_explain.py`. Module-level constants are no better here. Verified in this checkout, `test/flows`, `test/ioplace_parser` and `test/steps` each hold a `conftest.py` and none of them holds an `__init__.py`, so all three are imported under the single module name `conftest`; after a full collection `sys.modules["conftest"]` is `test/steps/conftest.py`. A `from conftest import _MOCK_PDK` would therefore depend on collection order. Fixtures are the mechanism pytest supplies for exactly this, so `_MOCK_PDK` and `_MINIMAL_DESIGN` become the fixtures `mock_pdk` and `minimal_design` and the call sites take them as arguments.

- [ ] **Step 1: Add the shared fixtures to `test/flows/conftest.py`**

Append to `test/flows/conftest.py`, below the existing `MetricIncrementer` fixture, which is all the file holds today:

```python
@pytest.fixture
def minimal_design():
    """
    The smallest design configuration ``_mock_conf_fs`` supports. Paired with
    :func:`mock_pdk`, which supplies the keyword half of a flow constructor.
    """
    return {
        "DESIGN_NAME": "WHATEVER",
        "VERILOG_FILES": ["/cwd/src/a.v"],
    }


@pytest.fixture
def mock_pdk():
    """
    The PDK keyword arguments that resolve against the fake filesystem
    ``_mock_conf_fs`` builds. Spread into a flow constructor as ``**mock_pdk``.
    """
    return {
        "design_dir": "/cwd",
        "pdk": "dummy",
        "scl": "dummy_scl",
        "pdk_root": "/pdk",
    }


@pytest.fixture
def counting_steps():
    """
    Two trivially registered steps that record the order they ran in, so a
    test can assert the engine's firing order without invoking a real tool.

    Returns
    -------
    ``(order, First, Second)``, where ``order`` is the list the
    steps append their ids to as they run.
    """
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

    return order, First, Second
```

`Step.factory.register` overwrites by id (`librelane/steps/step/factory.py:75`), so re-registering these on every test that asks for the fixture is intentional and harmless.

- [ ] **Step 2: Write the failing tests**

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


def _bool_var(name: str, default: bool) -> dict:
    return {
        "name": name,
        "type": "bool",
        "description": "x",
        "default": default,
    }


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_jobs_fire_in_topological_order(counting_steps, minimal_design, mock_pdk):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineFirst", "Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_document_name_is_the_flow_name(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)

    assert flow.name == "Tiny"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_false_condition_passes_state_through_without_running(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # 'first' did not run, but 'second' still did: the token was released.
    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_conjunction_runs_the_job_only_when_every_variable_is_true(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_A", True), _bool_var("RUN_B", False)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_A and RUN_B"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_conjunction_whose_variables_are_all_true_runs_the_job(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    order, _, _ = counting_steps
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_A", True), _bool_var("RUN_B", True)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_A and RUN_B"},
            },
        }
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert order == ["Test.EngineFirst"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_skipped_job_passes_state_through_without_running(
    counting_steps, minimal_design, mock_pdk
):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t", skip=["first"])

    assert order == ["Test.EngineSecond"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_step_writes_into_its_job_s_directory(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # slugify("Test.EngineFirst") is "test-enginefirst".
    assert (flow.run_dir / "first" / "1-test-enginefirst").is_dir()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_that_does_not_produce_its_contract_raises(
    minimal_design, mock_pdk
):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(JobContractError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "liar" in message
    assert "nl" in message
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'librelane.flows.engine'`

- [ ] **Step 4: Write the implementation**

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
from librelane.flows.net import Net
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
        # Flow.__init__ builds the Config from get_all_config_variables(), which
        # reads config_vars, and resolves the flow name from the class when the
        # instance has not set one. Both assignments must precede it.
        self.config_vars = [
            variable.to_variable() for variable in spec.config
        ]
        self.name = spec.name
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
            The state deposited on every source place.
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
        outputs: dict[str, State] = {}

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
            outputs[name] = state_out

        if not net.is_complete():
            raise FlowException(
                f"Flow '{self.spec.name}' stalled: no job is enabled and "
                f"{sorted(net.stalled())} never ran."
            )
        if deferred:
            raise FlowError("\n".join(deferred))
        return self._final_state(net, outputs), steps_run

    def _final_state(self, net: Net, outputs: dict[str, State]) -> State:
        """
        Returns
        -------
        The flow's final state, either the output of the job the
        document's ``final`` key names, or the join of every leaf's token.

        Raises
        ------
        JoinConflictError
            If two leaves disagree and no ``final`` is declared.
        """
        if self.spec.final is not None:
            assert (
                self.spec.final in outputs
            ), "checked by FlowSpec._check_final_names_a_job"
            return outputs[self.spec.final]
        return join_states(
            net.sink_tokens(),
            {},
            f"the final state of flow '{self.spec.name}'",
        )

    def _tokens_for(self, net: Net, job: Job) -> dict[str, State]:
        arcs = net.inputs_of(job.id)
        tokens = net.consume(job.id)
        return {
            (arc.producer if arc.producer is not None else "<initial state>"): token
            for arc, token in zip(arcs, tokens)
        }

    def _pass_through_reason(self, job: Job, skipped: bool) -> str | None:
        """
        Returns
        -------
        Why this job fires without running, or ``None`` if it runs.
        A conjunction is false when any one of its variables is false, and the
        reason names every false one so a document author does not have to
        flip them one at a time.
        """
        if skipped:
            return "named by --skip"
        false_variables = [
            variable for variable in job.conditions if not self.config[variable]
        ]
        if false_variables:
            names = ", ".join(f"'{variable}'" for variable in false_variables)
            verb = "is" if len(false_variables) == 1 else "are"
            return f"{names} {verb} false"
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
            if state.get_by_df(view) is None:
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

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 7: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 8: Commit**

```bash
git add librelane/flows/engine.py test/flows/test_engine.py test/flows/conftest.py
git commit -m "feat: run a workflow document on the net"
```

---

### Task 5: The final state, from the sink join or `final:`

**Files:**
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: `Net.sink_tokens` (Task 1), `join_states` and `JoinConflictError` (Task 2), `Workflow._final_state` (Task 4).
- Produces: no new public names. This task pins the behaviour Task 4 implemented.

**Design notes the implementer needs:**

`_final_state` is written in Task 4 because `run` cannot return without it. This task is where it is pinned, and it is a separate task because the shapes it needs are heavier than the single-job documents above.

The flow's final state was previously whichever leaf happened to sort last in the topological order, which is undefined behaviour dressed as a value. It is now the join of the sink arcs under the same rule every other fan-in uses, so equal values merge and unequal values conflict. The optional top-level `final` key names a single job whose output becomes the final state instead, and it is the only way to resolve a sink conflict, because the sink is not a job and no job's `source` addresses it.

Phase 1 catches a conflicting sink join at load, from the declared contracts. This is the run-time backstop for what a provider produces beyond what its stage declares, which is exactly the streamout case. `Stage.streamout.provides` is `(gds,)` while `streamout/magic` additionally provides `mag_gds` and `streamout/klayout` additionally provides `klayout_gds`, all verified in this checkout.

The two fake streamout steps below write a real file into their own `step_dir`, the way `Test.StepA` in `test/flows/test_flow.py` does, so the two `gds` paths differ by job directory and the conflict is the genuine one rather than a hand-placed string.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.fixture
def gds_writers():
    """
    Two steps that each write their own GDSII, so two leaves disagree on 'gds'
    exactly as Magic.StreamOut and KLayout.StreamOut do.
    """
    import os

    from librelane.common import Path
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class MagicLike(Step):
        id = "Test.EngineMagicStreamOut"
        inputs = []
        outputs = [DesignFormat.gds]

        def run(self, state_in, **kwargs):
            out = os.path.join(self.step_dir, "a.gds")
            open(out, "w", encoding="utf8").write("magic")
            return {DesignFormat.gds: Path(out)}, {}

    @Step.factory.register()
    class KLayoutLike(Step):
        id = "Test.EngineKLayoutStreamOut"
        inputs = []
        outputs = [DesignFormat.gds]

        def run(self, state_in, **kwargs):
            out = os.path.join(self.step_dir, "a.gds")
            open(out, "w", encoding="utf8").write("klayout")
            return {DesignFormat.gds: Path(out)}, {}

    return MagicLike, KLayoutLike


def _two_streamouts(final: str | None = None) -> dict:
    document: dict = {
        "name": "Streamout",
        "jobs": {
            "magic_streamout": {"steps": ["Test.EngineMagicStreamOut"]},
            "klayout_streamout": {"steps": ["Test.EngineKLayoutStreamOut"]},
        },
    }
    if final is not None:
        document["final"] = final
    return document


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_the_final_state_is_the_join_of_the_leaves(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    # Two leaves whose metrics differ in name but not in value, so the join
    # merges rather than conflicting and the result carries both.
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"steps": ["Test.EngineSecond"]},
            },
        }
    )

    final = Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert final.metrics["first"] == 1
    assert final.metrics["second"] == 1


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_two_leaves_with_conflicting_views_are_a_run_time_conflict(
    gds_writers, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.join import JoinConflictError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_streamouts())

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(JoinConflictError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "gds" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_final_names_the_job_whose_state_is_returned(
    gds_writers, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.state import DesignFormat

    spec = FlowSpec.model_validate(_two_streamouts(final="klayout_streamout"))

    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert str(final[DesignFormat.gds]).startswith(
        str(flow.run_dir / "klayout_streamout")
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: the three new tests fail. `test_final_names_the_job_whose_state_is_returned` and `test_two_leaves_with_conflicting_views_are_a_run_time_conflict` fail at `FlowSpec.model_validate` with a `final` extra-key rejection if phase 1 has not landed the `final` field, which is the signal to fix phase 1 rather than to work around it here.

- [ ] **Step 3: Confirm no implementation change is needed**

`_final_state` in Task 4 already implements both halves. If a test fails for any reason other than a missing phase 1 `final` field, the defect is in `_final_state` or in `Net.sink_tokens`, and it is fixed there rather than in the test.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: 11 passed

- [ ] **Step 5: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add test/flows/test_engine.py
git commit -m "test: pin the workflow sink join and the final key"
```

---

### Task 6: Concurrency and failure

**Files:**
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_engine.py`

**Interfaces:**
- Consumes: everything from Tasks 4 and 5.
- Produces: no new public names. `Workflow.run` gains concurrent firing and multi-failure reporting.

**Design notes the implementer needs:**

Replace the `topological_order` loop with a marking loop. While work remains, take `net.enabled()`, submit each job to `get_tpe()`, and fire each as its future completes. `librelane.common.get_tpe()` returns the process-wide `ThreadPoolExecutor` already sized from `-j`, so there is no new pool to manage.

Two ordering details matter. `net.consume(job)` and `net.fire(job, state)` must both happen on the main thread, not inside the worker, because the marking is not thread-safe and making it so would be a lock protecting one dictionary against a scheduler that does not need to contend. Consume before submitting, fire when the future resolves.

**A pass-through firing must restart the sweep.** `net.enabled()` is a snapshot. For the document `first (if false) -> second` the snapshot is `["first"]`, and firing `first` as a pass-through enables `second` after the snapshot was taken, so a loop that falls straight through to the pending check finds nothing pending, breaks, and reports a stall that did not happen. Track whether any pass-through fired during the sweep and `continue` the while loop before the pending check when one did. The loop still terminates, because `net.fired` only grows and is bounded by the job count.

**On failure, stop enabling new jobs but let in-flight jobs finish.** Cancelling immediately discards work already completed and hides a second, independent failure, which under concurrency is exactly the information wanted. Collect every failure and raise once, naming every failed job.

The contract check moves inside the same failure collection. Under the sequential loop it could raise straight out, but under concurrency raising immediately would abandon futures still running, so a contract miss now fails its job the way a step error does. The consequence is that `test_a_job_that_does_not_produce_its_contract_raises` must expect `FlowError` rather than `JobContractError`; `JobContractError` is still what `_check_contract` raises and it is still a `FlowError`, so the amended assertion is strictly weaker only in type, not in message.

`DeferredStepError` keeps its existing meaning. The job continues, the error is collected, and the flow raises at the end.

- [ ] **Step 1: Amend the contract test for collected failures**

In `test/flows/test_engine.py`, change `test_a_job_that_does_not_produce_its_contract_raises` to expect the collected error:

```python
    from librelane.flows.engine import Workflow
    from librelane.common.errors import FlowError
    ...
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")
```

The two message assertions stay as they are. Drop the now-unused `JobContractError` import from that test.

- [ ] **Step 2: Write the failing tests**

Append to `test/flows/test_engine.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_independent_branches_both_run(minimal_design, mock_pdk):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert sorted(ran) == ["left", "right"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_failure_reports_every_failed_job_not_just_the_first(
    minimal_design, mock_pdk
):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "left exploded" in message
    assert "right exploded" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, step_module])
def test_a_job_downstream_of_a_failure_does_not_run(minimal_design, mock_pdk):
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

    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError):
        flow.start(tag="t")

    assert ran == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: `test_a_failure_reports_every_failed_job_not_just_the_first` FAILS, because the sequential loop raises on the first failure and never reaches the second job. `test_a_job_that_does_not_produce_its_contract_raises` still passes, because `JobContractError` is a `FlowError`. The other two new tests pass under the sequential implementation.

- [ ] **Step 4: Replace the run loop**

In `librelane/flows/engine.py`, replace the body of `run` between the progress-bar line and the `if not net.is_complete()` check with a marking loop:

```python
        self.progress_bar.set_max_stage_count(len(self.jobs))
        steps_run: list[Step] = []
        deferred: list[str] = []
        failures: list[str] = []
        outputs: dict[str, State] = {}
        pending: dict[Future[State], str] = {}

        while True:
            fired_pass_through = False
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
                        outputs[name] = state_in
                        self.progress_bar.end_stage()
                        fired_pass_through = True
                        continue
                    pending[
                        get_tpe().submit(
                            self._run_job, job, state_in, steps_run, deferred
                        )
                    ] = name
            if fired_pass_through:
                # net.enabled() was a snapshot. A pass-through just enabled its
                # descendants, and they are not in it.
                continue
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                name = pending.pop(future)
                try:
                    state_out = future.result()
                    self._check_contract(self.jobs[name], state_out)
                except FlowError as e:
                    failures.append(f"Job '{name}': {e}")
                    self.progress_bar.end_stage()
                    continue
                net.fire(name, state_out)
                outputs[name] = state_out
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
it. A job becomes enabled exactly when its predecessors have fired, which is a
topological order computed incrementally rather than up front.

The `if not net.is_complete()` stall check stays, and now has real work to do,
because a failure leaves descendants unfired and the check names them. Move it
below the `if failures` raise so a genuine failure is reported as a failure
rather than as a stall. The `if deferred` raise keeps its place after the stall
check, and `self._final_state(net, outputs)` stays at the end, after all
three, so it is reached only on a run that neither failed, stalled, nor
deferred. Phase 4 Task 9 amends this ordering for the deferred case
specifically. It moves `_final_state` to run **before** the `if deferred`
raise, citing `sequential.py:597-607`, so a deferred run still leaves a
final-state snapshot rather than skipping straight to the raise. That
amendment is correct, and this plan's ordering above should be read as
superseded by it rather than contradicting it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_engine.py -v`
Expected: 14 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest test -x -q`
Expected: all pass, 1 xfailed, no new failures

- [ ] **Step 7: Lint**

Run: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`
Expected: no findings

- [ ] **Step 8: Commit**

```bash
git add librelane/flows/engine.py test/flows/test_engine.py
git commit -m "feat: fire independent workflow jobs concurrently"
```

---

## What this phase does not do

No shipped flow runs on `Workflow` yet, and `librelane/flows/__init__.py` is deliberately not touched. `Stage` is still `Stage`, the six flows are still Python classes on `StagedFlow`, and the command-line surface still has `--from` and `--to`. Those are phases 3, 4 and 5.

`Workflow.run` also does not write the `runs/<tag>/final` snapshot that
`SequentialFlow.run` writes with `State.save_snapshot`. That is a real function
of the old engine and phase 4 has to port it when the shipped flows move over.
It is out of scope here because no shipped flow runs on `Workflow` yet and
nothing reads the snapshot of a synthetic test document.
