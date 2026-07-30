# Flow Mechanism Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the seventeen mechanisms that decide whether a step runs to a set small enough to reason about, fix the four defects their overlap causes, and add one API that answers "will step X run".

**Architecture:** Fourteen deletions applied in dependency order, three behavioural fixes to `SequentialFlow.run` and `SequentialFlow._expand_gating_config_vars`, and a new `SequentialFlow.explain` returning a frozen `Explanation` dataclass, overridden by `StagedFlow` to add unselected stages. No new capability, no execution engine, no concurrency.

**Tech Stack:** Python 3.11+, pytest with pytest-mock, pyfakefs, typer for the CLI, ruff for lint, uv for every invocation.

**Spec:** `docs/superpowers/specs/2026-07-30-flow-mechanism-unification-design.md`

## Global Constraints

- Every Python and pytest invocation goes through `uv run`. Never call `python` or `pytest` directly.
- Mocking uses `pytest-mock`'s `mocker` fixture. Do not import `unittest.mock` in new test code.
- Do not write `from __future__ import annotations`. Write types directly.
- Never add a fallback path. When something is deleted, the code that used it either changes to the replacement or raises. There is no "if the new way is unavailable, try the old way".
- Deletions are outright. No `@deprecated` shims, no compatibility aliases, no deprecation window.
- Do not create summary markdown files. The only markdown this plan writes is the documentation changes each task names explicitly.
- Test IDs for ephemeral steps use the `Test.` prefix, which `test/steps/test_registry_snapshot.py` excludes from its comparison.
- Fixtures that register a `Stage` or a `StageRegistry` entry must be `scope="module"`, because both registries are process-wide singletons and a function-scoped fixture fails on second use with "already registered".
- Lint after every task with `make lint`, which runs `uv run ruff check .` and `uv run ruff format --check .`.
- Full suite command: `uv run pytest -n auto`. `-m 'not step_impl_test'` is already in `addopts`, so tool-dependent tests are excluded by default. Flow tests do not need `--pdk-root`.
- Fish is the shell. Quote any glob passed to a command, for example `--include='*.py'`.
- `test/steps/registry_snapshot.json` records step IDs only. No task in this plan adds or removes a step class, so the snapshot never needs regenerating. If `test_step_registry_matches_snapshot` fails, a step was deleted by mistake.

---

## File Structure

**New files**

- `librelane/flows/explanation.py`, the `StepDisposition` and `Explanation` frozen dataclasses. Their own module rather than an addition to `sequential.py`, which is already 588 lines and is losing 200 of them in Task 6. Two flow classes and the CLI import from here.
- `test/flows/test_explain.py`, every `explain` and `--explain` test.

**Files losing code**

- `librelane/flows/sequential.py`, loses `Substitution`, `SubstitutionsObject`, `_substitution_pairs`, `Substitutions`, `_applied_substitutions`, `Substitute`, `_substitute_in_place`, `__substitute_step`, `make`, and the fuzzy-match branches. Gains `_step_ids_by_lowercase`, `_resolve_step_id`, `explain`, and a reordered run loop.
- `librelane/flows/staged.py`, loses `_preflight_pdk_vars` and the substitution replay. Gains `explain`.
- `librelane/flows/chip.py`, `Substitutions` map becomes an explicit `Stages` list.
- `librelane/stages/registry.py`, `Registration.stages: tuple[str, ...]` becomes `stage: str`; `spanning`, `requires_pdk_vars` and the canonical-variable check go.
- `librelane/stages/stage.py`, loses `config_vars`.
- `librelane/stages/resolution.py`, loses the spanning rejection branch.
- `librelane/steps/step/core.py`, `flow_control_variable` warning becomes `TypeError`; the `config_vars` escape in `__init_subclass__` goes.
- `librelane/state/design_format.py`, loses `value`, `name`, `by_id`.
- `librelane/config/config.py`, `Meta.flow` narrows to `None | str`; `Meta.substituting_steps` goes.
- `librelane/cli/run.py`, `librelane/cli/options.py` and `librelane/cli/runtime.py` lose `--only` and the substitution and list-flow branches, and gain `--explain`.
- `librelane/common/toolbox.py` and `librelane/flows/flow.py` lose the five stale 2.0 deprecations.

**Files deleted outright**

- `librelane/flows/optimizing.py`
- `librelane/flows/synth_explore.py`
- `librelane/examples/hold_eco_demo/config.yaml` and `librelane/examples/hold_eco_demo/demo.v`
- `docs/source/usage/using_ecos.md`

---

## Task Ordering and Why

Tasks 1 through 4 are independent behavioural changes that touch no deleted surface, so they land first and their regression tests stay green through everything after. Task 5 converts `Chip` and must precede Task 6, which deletes the mechanism `Chip` currently uses. Task 8 deletes `Optimizing`, the only caller of three of the five stale deprecations in the same task. Task 13 depends on Task 3, which extracts the step-ID resolver `explain` needs, and on Task 2, whose union semantics `explain` reports.

---

## Task 1: Reorder the run-loop ladder

Fixes two of the four live defects. `--from` currently fails on any flow with a false gating variable earlier in the step list, because the ladder tests `not executing` before it tests `gated`, so a gated step is required to have a resume entry it never wrote. And `--reproducible` naming a gated step is currently discarded silently, because the gated branch comes first and does not consider it.

**Files:**
- Modify: `librelane/flows/sequential.py:485-533`
- Test: `test/flows/test_sequential.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the run loop computes a local `gated_by: list[str]`, the names of the gating variables that evaluated false for this step. Task 13 recomputes the same list in `explain` and must produce identical wording.

- [ ] **Step 1: Write the failing test for `--from` over a gated step**

Append to `test/flows/test_sequential.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_from_works_when_an_earlier_step_is_gated(MetricIncrementer):
    """
    A gated step never reached the execute path, so it wrote no resume entry.
    Requiring one from it made --from unusable on any flow with a gate turned
    off, which is every real configuration.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.Gated"
        counter_name = "gated_counter"

    class Later(MetricIncrementer):
        id = "Test.Later"
        counter_name = "later_counter"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated, Later]

        config_vars = [
            Variable("TEST_GATE", bool, description="x", default=False)
        ]

        gating_config_vars = {"Test.Gated": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    flow.start(tag="GATED_FROM")

    state = flow.start(tag="GATED_FROM", frm="Test.Later")
    assert state.metrics["later_counter"] == 2
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest test/flows/test_sequential.py::test_from_works_when_an_earlier_step_is_gated -v`

Expected: FAIL with `FlowException: Cannot start from 'Test.Later': step 'Test.Gated' comes earlier and has no reusable result`.

- [ ] **Step 3: Write the failing test for `--reproducible` on a gated step**

Append to `test/flows/test_sequential.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_reproducible_of_a_gated_step_raises_naming_the_gate(MetricIncrementer):
    """
    Packaging a reproducible for a step this configuration would never execute
    is a contradiction. It used to be resolved by discarding the request and
    running the whole flow instead, with no message.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow, FlowException

    class Gated(MetricIncrementer):
        id = "Test.GatedRepro"
        counter_name = "gated_counter"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated]

        config_vars = [
            Variable("TEST_GATE", bool, description="x", default=False)
        ]

        gating_config_vars = {"Test.GatedRepro": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    with pytest.raises(FlowException, match="TEST_GATE"):
        flow.start(reproducible="Test.GatedRepro")
```

- [ ] **Step 4: Write the failing test for distinguishable skip messages**

Append to `test/flows/test_sequential.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_each_skip_reason_names_its_cause(MetricIncrementer, caplog):
    """
    Three unrelated mechanisms used to emit the identical 'Skipping step' line,
    so a user reading a log could not tell which one had fired.
    """
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.GatedReason"

    class Skipped(MetricIncrementer):
        id = "Test.SkippedReason"

    class Windowed(MetricIncrementer):
        id = "Test.WindowedReason"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated, Skipped, Windowed]

        config_vars = [
            Variable("TEST_GATE", bool, description="x", default=False)
        ]

        gating_config_vars = {"Test.GatedReason": ["TEST_GATE"]}

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    flow.start(skip=["Test.SkippedReason"], to="Test.SkippedReason")

    assert "TEST_GATE" in caplog.text
    assert "--skip" in caplog.text
    assert "--to" in caplog.text
```

- [ ] **Step 5: Run all three and confirm they fail**

Run: `uv run pytest test/flows/test_sequential.py -v -k "gated or skip_reason"`

Expected: three FAILs. The first raises `FlowException`, the second raises nothing at all (the flow runs to completion, so `pytest.raises` fails with `DID NOT RAISE`), the third fails on the `TEST_GATE` assertion.

- [ ] **Step 6: Replace the gating computation and the ladder**

In `librelane/flows/sequential.py`, replace lines 485 through 533, which currently read:

```python
            gated = False
            if gating_cvars := gating_cvars_expanded.get(step.id):
                for variable in gating_cvars:
                    if not self.config[variable]:
                        logger.info(
                            f"Gating variable for step '{step.id}' set to 'False'- the step will be skipped."
                        )
                        gated = True

            self.progress_bar.start_stage(step.name)
            executed = True
            if stopped:
```

with:

```python
            gated_by = [
                variable
                for variable in gating_cvars_expanded.get(step.id, [])
                if not self.config[variable]
            ]
            explicitly_skipped = cls.id in skipped_ids

            self.progress_bar.start_stage(step.name)
            executed = True
            if cls.id == reproducible_resolved:
                # Ahead of every skip test, so that a request for a step this
                # configuration would never execute is diagnosed rather than
                # silently discarded.
                if gated_by:
                    raise FlowException(
                        f"Cannot create a reproducible for step '{step.id}': it "
                        f"is gated off by {', '.join(gated_by)}, so this "
                        f"configuration would never execute it. Set "
                        f"{' and '.join(gated_by)} to true, or name another step."
                    )
                if explicitly_skipped:
                    raise FlowException(
                        f"Cannot create a reproducible for step '{step.id}': it "
                        f"is named by --skip, so this run would never execute "
                        f"it. Drop it from --skip, or name another step."
                    )
                step.create_reproducible(step_dir / "reproducible")
                break
            elif gated_by:
                logger.info(
                    f"Skipping step '{step.name}': gated off by "
                    f"{', '.join(gated_by)}."
                )
                executed = False
            elif explicitly_skipped:
                logger.info(f"Skipping step '{step.name}': named by --skip.")
                executed = False
            elif stopped:
                # Past --to. Nothing downstream will ask for this step's output,
                # so unlike the steps before --from it does not have to be
                # resolved at all.
                logger.info(
                    f"Skipping step '{step.name}': after --to '{to_resolved}'."
                )
                executed = False
            elif not executing and initial_state_given:
                # Before --from, but the caller handed us the state that stands
                # in for these steps. Resolving them would discard it.
                logger.info(
                    f"Skipping step '{step.name}': before --from "
                    f"'{frm_resolved}', and an initial state was supplied."
                )
                executed = False
            elif not executing:
```

- [ ] **Step 7: Delete the two now-dead branches further down the ladder**

The old ladder had `elif cls.id in skipped_ids or gated:` and `elif cls.id == reproducible_resolved:` after the reuse-or-raise branch. Both are now unreachable and must go. In `librelane/flows/sequential.py`, delete these six lines, which sat between the `raise FlowException("Cannot start from ...")` block and the final `else:`:

```python
            elif cls.id in skipped_ids or gated:
                logger.info(f"Skipping step '{step.name}'…")
                executed = False
            elif cls.id == reproducible_resolved:
                step.create_reproducible(step_dir / "reproducible")
                break
```

The branch that remains immediately before the final `else:` is the one ending:

```python
                step_list.append(step)
                reused_count += 1
```

- [ ] **Step 8: Run the three new tests**

Run: `uv run pytest test/flows/test_sequential.py -v -k "gated or skip_reason"`

Expected: PASS.

- [ ] **Step 9: Run the whole flow suite for regressions**

Run: `uv run pytest -n auto test/flows/ -v`

Expected: PASS. `test_flow_control` at `test/flows/test_sequential.py:306` exercises `--from`, `--to` and `--skip` together and is the main guard that the reordering did not change ordinary behaviour.

- [ ] **Step 10: Lint and commit**

```bash
make lint
git add librelane/flows/sequential.py test/flows/test_sequential.py
git commit -m "fix: decide gating and skipping before reuse in the run loop"
```

---

## Task 2: Union semantics for gating expansion

Fixes the third live defect. An explicit wildcard gating key silently overwrites a generated stage gate, because `_expand_gating_config_vars` assigns per matched step ID and the last key in iteration order wins. A flow declaring `{"OpenROAD.CTS*": ["MY_GATE"]}` loses `RUN_CTS` on `OpenROAD.CTS` entirely.

Note for the implementer: `_apply_stage_gating` at `librelane/flows/staged.py:529-533` already unions, via `dict.fromkeys(merged.get(key, []) + list(value))`. It is correct as written and needs no change. The bug is entirely downstream of it, because a wildcard explicit key never equals an exact generated key, so the two survive as separate dictionary entries and only collide at expansion. Step 4 below asserts that both entries survive, which is what makes the union in `_expand_gating_config_vars` reachable.

**Files:**
- Modify: `librelane/flows/sequential.py:189-226`
- Test: `test/flows/test_sequential.py`, `test/flows/test_staged.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SequentialFlow._expand_gating_config_vars(gating_config_vars, step_ids) -> dict[str, list[str]]`, unchanged signature, now returning the deduplicated union of every key that matched a given step ID. Task 13's `explain` calls it.

- [ ] **Step 1: Write the failing test for wildcard and exact union**

Append to `test/flows/test_sequential.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_overlapping_gating_keys_union_rather_than_overwrite(MetricIncrementer):
    """
    A wildcard key and an exact key matching the same step both apply. Taking
    the last one in iteration order silently dropped the other, which on a
    StagedFlow means dropping the stage gate a flow never wrote by hand and
    cannot see.
    """
    from librelane.flows import SequentialFlow

    expanded = SequentialFlow._expand_gating_config_vars(
        {
            "Test.Alpha": ["EXACT_GATE"],
            "Test.Alph*": ["WILDCARD_GATE"],
        },
        ["Test.Alpha", "Test.Beta"],
    )

    assert expanded["Test.Alpha"] == ["EXACT_GATE", "WILDCARD_GATE"]
    assert "Test.Beta" not in expanded


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_gating_union_is_order_independent():
    from librelane.flows import SequentialFlow

    forward = SequentialFlow._expand_gating_config_vars(
        {"Test.Alph*": ["WILDCARD_GATE"], "Test.Alpha": ["EXACT_GATE"]},
        ["Test.Alpha"],
    )

    assert sorted(forward["Test.Alpha"]) == ["EXACT_GATE", "WILDCARD_GATE"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_gating_union_deduplicates():
    from librelane.flows import SequentialFlow

    expanded = SequentialFlow._expand_gating_config_vars(
        {"Test.Alpha": ["SHARED_GATE"], "Test.Alph*": ["SHARED_GATE"]},
        ["Test.Alpha"],
    )

    assert expanded["Test.Alpha"] == ["SHARED_GATE"]
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest test/flows/test_sequential.py -v -k "union or overwrite"`

Expected: FAIL. The first asserts `["EXACT_GATE", "WILDCARD_GATE"]` and gets `["WILDCARD_GATE"]`.

- [ ] **Step 3: Rewrite the expansion**

In `librelane/flows/sequential.py`, replace the body and docstring of `_expand_gating_config_vars`, lines 189 through 226, with:

```python
    @staticmethod
    def _expand_gating_config_vars(
        gating_config_vars: dict[str, list[str]],
        step_ids: Iterable[str],
    ) -> dict[str, list[str]]:
        """
        Expands gating keys, which may be exact step IDs or wildcards, against
        a concrete step ID list.

        A step matched by more than one key, whether exact or wildcard, is
        gated by the deduplicated union of their lists, order-preserving. The
        run loop requires every variable in a step's list to be true, so the
        union reads as "all of the conditions that named this step apply",
        which is the only reading under which a wildcard a flow author wrote
        cannot silently displace a stage gate generated for the same step.

        Shared between :meth:`run`, :meth:`explain` and
        :meth:`librelane.flows.StagedFlow._preflight_views`, so that none of
        them can evaluate a different set of gates than the others.

        :raises FlowException: If a gating key matches no step in ``step_ids``.
        """
        step_id_list = list(step_ids)
        expanded: dict[str, list[str]] = {}
        for key, value in gating_config_vars.items():
            if key in step_id_list:
                matched = [key]
            else:
                matched = list(Filter([key]).filter(step_id_list))
                if not matched:
                    # Checked per key rather than against `expanded`, whose
                    # entries are matched step IDs and so never contain a
                    # wildcard key even when it matched.
                    raise FlowException(
                        f"Gating key '{key}' matches no step in this run. A "
                        f"gating key that matches nothing silently fails to "
                        f"gate anything."
                    )
            for id in matched:
                expanded[id] = list(
                    dict.fromkeys(expanded.get(id, []) + list(value))
                )
        return expanded
```

- [ ] **Step 4: Run the three tests**

Run: `uv run pytest test/flows/test_sequential.py -v -k "union or overwrite"`

Expected: PASS.

- [ ] **Step 5: Write the end-to-end test on a StagedFlow**

Append to `test/flows/test_staged.py`:

```python
def test_a_wildcard_explicit_gate_does_not_displace_the_stage_gate():
    """
    _apply_stage_gating merges by exact key, so a wildcard explicit key lands
    as a separate entry and only collides with the generated one at expansion.
    Both entries must survive the merge for the union there to be reachable.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Both(StagedFlow):
        Stages = [Stage.cts]
        gating_config_vars = {"OpenROAD.CTS*": ["MY_GATE"]}

        class Config(StagedFlow.Config):
            RUN_CTS: bool = variable(True, description="test gate")
            MY_GATE: bool = variable(True, description="test gate")

    assert Both.gating_config_vars["OpenROAD.CTS"] == ["RUN_CTS"]
    assert Both.gating_config_vars["OpenROAD.CTS*"] == ["MY_GATE"]

    expanded = StagedFlow._expand_gating_config_vars(
        Both.gating_config_vars,
        [step.id for step in Both.Steps],
    )
    assert expanded["OpenROAD.CTS"] == ["RUN_CTS", "MY_GATE"]
```

- [ ] **Step 6: Run it**

Run: `uv run pytest test/flows/test_staged.py::test_a_wildcard_explicit_gate_does_not_displace_the_stage_gate -v`

Expected: PASS.

- [ ] **Step 7: Run the flow suite and commit**

Run: `uv run pytest -n auto test/flows/ -v`

Expected: PASS. `test_wildcard_gating` at `test/flows/test_sequential.py:365` is the guard that single-key wildcard gating still works.

```bash
make lint
git add librelane/flows/sequential.py test/flows/test_sequential.py test/flows/test_staged.py
git commit -m "fix: union overlapping gating keys instead of overwriting"
```

---

## Task 3: Extract the step-ID resolver and delete the fuzzy-match escape hatch

`resolve_step` is a closure inside `run`, which is why `explain` cannot reach it. Extracting it is a precondition for Task 13. The escape hatch environment variable goes at the same time, because it lives in exactly the lines being moved.

**Files:**
- Modify: `librelane/flows/sequential.py:408-457`
- Test: `test/flows/test_sequential.py`

**Interfaces:**
- Produces:
  - `SequentialFlow._step_ids_by_lowercase(self) -> dict[str, str]`, mapping each step's lowercased ID to its real ID.
  - `SequentialFlow._resolve_step_id(self, matchable: str | None, multiple_ok: bool = False) -> str | list[str] | None`. Returns `None` for a `None` input, a `list[str]` when `multiple_ok`, a `str` otherwise. Raises `FlowException` on no match, with a `Did you mean` suggestion appended when the fuzzy matcher finds one above the score cutoff. Task 13 calls both.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_sequential.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_a_mistyped_step_id_raises_and_suggests(MetricIncrementer, monkeypatch):
    """
    The suggestion stays; proceeding on the guess does not. The environment
    variable that used to make a near miss run anyway is gone, so setting it
    changes nothing.
    """
    from librelane.flows import SequentialFlow, FlowException

    monkeypatch.setenv(
        "_i_want_librelane_to_fuzzy_match_steps_and_im_willing_to_accept_the_risks",
        "1",
    )

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    with pytest.raises(FlowException, match="Did you mean"):
        flow.start(frm="Test.MetricIncrementerr")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_flow_module, step_module])
def test_resolve_step_id_is_reachable_without_running(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    flow = Dummy(
        {"DESIGN_NAME": "WHATEVER", "VERILOG_FILES": ["/cwd/src/a.v"]},
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    assert flow._resolve_step_id("test.metricincrementer") == "Test.MetricIncrementer"
    assert flow._resolve_step_id(None) is None
    assert flow._resolve_step_id("test.*", multiple_ok=True) == [
        "Test.MetricIncrementer"
    ]
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/flows/test_sequential.py -v -k "mistyped or resolve_step_id"`

Expected: FAIL. The first passes the fuzzy match and runs the flow, so `pytest.raises` reports `DID NOT RAISE`. The second fails with `AttributeError: 'Dummy' object has no attribute '_resolve_step_id'`.

- [ ] **Step 3: Add the two methods**

Insert into `librelane/flows/sequential.py`, immediately before `def run(`:

```python
    def _step_ids_by_lowercase(self) -> dict[str, str]:
        """
        :returns: A mapping from each step's lowercased ID to the real one.
            Built in reverse so that the first step wins any collision, which
            duplicate-ID normalization should already have made impossible.
        """
        return {cls.id.lower(): cls.id for cls in reversed(self.Steps)}

    def _resolve_step_id(
        self,
        matchable: str | None,
        multiple_ok: bool = False,
    ) -> str | list[str] | None:
        """
        Resolves one ``--from``, ``--to``, ``--skip`` or ``--reproducible``
        argument against this flow's step list. Matching is case-insensitive
        and accepts wildcards.

        :param matchable: The argument, or ``None``.
        :param multiple_ok: Whether a key matching several steps is legal, as
            it is for ``--skip``.
        :returns: ``None``, a step ID, or a list of them when ``multiple_ok``.
        :raises FlowException: If the argument matches no step, or matches
            several when ``multiple_ok`` is false. A near miss above the fuzzy
            score cutoff is named in the message as a suggestion, and is not
            acted on: a flow that ran a step the user did not name is worse
            than one that stopped.
        """
        if matchable is None:
            return None
        step_ids = self._step_ids_by_lowercase()
        ids = list(Filter([matchable.lower()]).filter(step_ids))
        if len(ids) > 0:
            if multiple_ok:
                return [step_ids[id] for id in ids]
            if len(ids) > 1:
                raise FlowException(f"{matchable} matched multiple steps.")
            return step_ids[ids[0]]

        match_tuple = process.extractOne(
            matchable,
            step_ids,
            scorer=fuzz.partial_ratio,
            score_cutoff=80,
            processor=utils.default_process,
        )
        suggestion = ""
        if match_tuple is not None:
            match, _, _ = match_tuple
            suggestion = f" Did you mean: '{match}'?"
        raise FlowException(
            f"Failed to process '{matchable}': no step(s) with ID "
            f"'{matchable}' found in flow.{suggestion}"
        )
```

- [ ] **Step 4: Delete the closure and call the method**

In `librelane/flows/sequential.py`, inside `run`, delete the whole `def resolve_step(...)` closure, lines 411 through 447, and the `step_ids = {...}` assignment at line 408 that only it used. Then replace the four call sites, lines 449 through 457, which read:

```python
        frm_resolved = resolve_step(frm)

        to_resolved = resolve_step(to)

        reproducible_resolved = resolve_step(reproducible)

        if skipped_steps := skip:
            for skipped_step in skipped_steps:
                skipped_ids += resolve_step(skipped_step, multiple_ok=True)
```

with:

```python
        frm_resolved = self._resolve_step_id(frm)

        to_resolved = self._resolve_step_id(to)

        reproducible_resolved = self._resolve_step_id(reproducible)

        if skipped_steps := skip:
            for skipped_step in skipped_steps:
                skipped_ids += self._resolve_step_id(skipped_step, multiple_ok=True)
```

- [ ] **Step 5: Fix the one remaining reference to the deleted local**

`gating_cvars_expanded` at line 473 passes `step_ids.values()`. Replace:

```python
        gating_cvars_expanded = self._expand_gating_config_vars(
            self.gating_config_vars, step_ids.values()
        )
```

with:

```python
        gating_cvars_expanded = self._expand_gating_config_vars(
            self.gating_config_vars,
            [cls.id for cls in self.Steps],
        )
```

- [ ] **Step 6: Delete the now-unused import**

`os` was imported for `os.getenv` alone. Confirm with `grep -n 'os\.' librelane/flows/sequential.py`, which must return nothing, then delete the `import os` line.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest -n auto test/flows/ -v`

Expected: PASS, including the two new tests.

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add librelane/flows/sequential.py test/flows/test_sequential.py
git commit -m "refactor: extract _resolve_step_id and drop the fuzzy-match escape hatch"
```

---

## Task 4: Delete `--only`

`--from X --to X` expresses it. Deleting it removes one CLI-level mechanism and the normalizer that folds it in.

**Files:**
- Modify: `librelane/cli/options.py:171-177`, `librelane/cli/runtime.py:130-137`, `librelane/cli/run.py:61`, `:82`, `:360`, `:409`
- Modify: `test/cli/test_runtime.py:29`, `:79`, `:183-192`
- Modify: `docs/source/getting_started/migrants/index.md:26`

**Interfaces:**
- Removes `normalize_sequential_controls` entirely. Nothing else calls it.

- [ ] **Step 1: Delete the option definition**

In `librelane/cli/options.py`, delete:

```python
OnlyOption = Annotated[
    str | None,
    typer.Option(
        "--only",
        help="Set both --from and --to to this step ID.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
```

- [ ] **Step 2: Delete the normalizer**

In `librelane/cli/runtime.py`, delete:

```python
def normalize_sequential_controls(
    frm: str | None,
    to: str | None,
    only: str | None,
) -> tuple[str | None, str | None]:
    if only is not None:
        return only, only
    return frm, to
```

- [ ] **Step 3: Unwire it from `run`**

In `librelane/cli/run.py`, delete `OnlyOption,` from the options import at line 61, delete `normalize_sequential_controls,` from the runtime import at line 82, delete the parameter `only: OnlyOption = None,` at line 360, and delete the line `frm, to = normalize_sequential_controls(frm, to, only)` at line 409.

- [ ] **Step 4: Update the CLI tests**

In `test/cli/test_runtime.py`, delete `normalize_sequential_controls,` from the import at line 29, delete the assertion at line 79 that calls it, and delete the `"--only", "this-step",` argument pair and the two `captured["request"]` assertions at lines 183 through 192, together with whatever test function wrapped them if it tested nothing else. Read the surrounding function before deleting so the right amount goes.

- [ ] **Step 5: Update the migration guide**

In `docs/source/getting_started/migrants/index.md:26`, the sentence reads `` `--skip` and `--only`, with the ability to resume from a snapshot of your ``. Remove the `` and `--only` `` clause so the sentence names only `--skip`.

- [ ] **Step 6: Confirm nothing references it**

Run: `grep -rn -- '--only\|OnlyOption\|normalize_sequential_controls' librelane/ test/ docs/source/`

Expected: no output.

- [ ] **Step 7: Test, lint and commit**

Run: `uv run pytest -n auto test/cli/ -v`

Expected: PASS.

```bash
make lint
git add librelane/cli/ test/cli/test_runtime.py docs/source/getting_started/migrants/index.md
git commit -m "feat!: remove --only in favour of --from X --to X"
```

---

## Task 5: Convert `Chip` to an explicit `Stages` list

Must land before Task 6, which deletes the mechanism `Chip` uses. The conversion is validated by capturing `Chip.Steps` before the change and asserting the same list after, in the manner of `test/flows/test_staged_equivalence.py`.

`Chip` currently differs from `Classic` by four removals, one insertion and six appends. Three of the removals are whole-stage or plain-step omissions. The fourth is not: `OpenROAD.IOPlacement` and `Odb.CustomIOPlacement` are two of the four steps of `io_placement/openroad`, whose other two, `OpenROAD.GlobalPlacementSkipIO` and `Odb.ApplyDEFTemplate`, `Chip` keeps. `Chip` therefore omits `Stage.io_placement` and lists those two as plain steps, accepting the loss of that stage's boundary and contract for this flow.

**Files:**
- Modify: `librelane/flows/chip.py`
- Create: `test/flows/test_chip.py`

**Interfaces:**
- Produces: `Chip.Stages`, a list of 48 entries. `Chip.gating_config_vars` becomes an empty class body entry, because the filter that existed only to drop `Magic.WriteLEF`'s inherited gate is no longer needed.

- [ ] **Step 1: Capture the golden step list**

Run:

```bash
uv run --no-sync python -c "
import json
import librelane.flows.builtins
from librelane.flows import Flow
steps = [step.id for step in Flow.factory.get('Chip').Steps]
print(len(steps))
print(json.dumps(steps, indent=2))
"
```

Expected: `83`, then a list beginning with `Verilator.Lint` and ending with `Misc.ReportManufacturability`. Keep this output; Step 5 compares against it.

- [ ] **Step 2: Write the golden test**

Create `test/flows/test_chip.py`:

```python
import pytest

pytestmark = pytest.mark.all

#: Chip's step list as the Substitutions map produced it, captured before the
#: conversion to an explicit Stages list. Any difference between this and what
#: the explicit list expands to is a conversion error, not an improvement.
GOLDEN = [
    "Verilator.Lint",
    "Checker.LintTimingConstructs",
    "Checker.LintErrors",
    "Checker.LintWarnings",
    "Yosys.JsonHeader",
    "Yosys.Synthesis",
    "Checker.YosysUnmappedCells",
    "Checker.YosysSynthChecks",
    "OpenROAD.CheckSDCFiles",
    "OpenROAD.STAPrePNR",
    "OpenROAD.CheckMacroInstances",
    "OpenROAD.Floorplan",
    "Odb.CheckMacroAntennaProperties",
    "Odb.SetPowerConnections",
    "OpenROAD.PadRing",
    "Odb.ManualMacroPlacement",
    "OpenROAD.CutRows",
    "OpenROAD.TapEndcapInsertion",
    "Odb.AddPDNObstructions",
    "OpenROAD.GeneratePDN",
    "Odb.RemovePDNObstructions",
    "Odb.AddRoutingObstructions",
    "OpenROAD.GlobalPlacementSkipIO",
    "Odb.ApplyDEFTemplate",
    "OpenROAD.GlobalPlacement",
    "Odb.WriteVerilogHeader",
    "Checker.PowerGridViolations",
    "OpenROAD.STAMidPNR",
    "OpenROAD.RepairDesignPostGPL",
    "Odb.ManualGlobalPlacement",
    "OpenROAD.DetailedPlacement",
    "OpenROAD.CTS",
    "OpenROAD.STAMidPNR-1",
    "OpenROAD.ResizerTimingPostCTS",
    "OpenROAD.STAMidPNR-2",
    "OpenROAD.GlobalRouting",
    "OpenROAD.CheckAntennas",
    "OpenROAD.RepairDesignPostGRT",
    "Odb.DiodesOnPorts",
    "Odb.HeuristicDiodeInsertion",
    "OpenROAD.RepairAntennas",
    "OpenROAD.ResizerTimingPostGRT",
    "OpenROAD.STAMidPNR-3",
    "OpenROAD.DetailedRouting",
    "Odb.RemoveRoutingObstructions",
    "OpenROAD.CheckAntennas-1",
    "Checker.TrDRC",
    "Odb.ReportDisconnectedPins",
    "Checker.DisconnectedPins",
    "Odb.ReportWireLength",
    "Checker.WireLength",
    "OpenROAD.FillInsertion",
    "Odb.CellFrequencyTables",
    "OpenROAD.RCX",
    "OpenROAD.STAPostPNR",
    "OpenROAD.IRDropReport",
    "Magic.StreamOut",
    "KLayout.StreamOut",
    "KLayout.Render",
    "KLayout.XOR",
    "Checker.XOR",
    "KLayout.Antenna",
    "Checker.KLayoutAntenna",
    "KLayout.SealRing",
    "KLayout.Filler",
    "KLayout.Density",
    "Checker.KLayoutDensity",
    "Magic.DRC",
    "Checker.MagicDRC",
    "KLayout.DRC",
    "Checker.KLayoutDRC",
    "Magic.SpiceExtraction",
    "Checker.IllegalOverlap",
    "Netgen.LVS",
    "Checker.LVS",
    "Yosys.EQY",
    "Checker.SetupViolations",
    "Checker.HoldViolations",
    "Checker.MaxSlewViolations",
    "Checker.MaxCapViolations",
    "Misc.ReportManufacturability",
]


def test_chip_expands_to_the_same_steps_the_substitution_map_produced():
    from librelane.flows import Flow

    Chip = Flow.factory.get("Chip")
    assert [step.id for step in Chip.Steps] == GOLDEN


def test_chip_declares_its_own_stages_rather_than_patching_classic():
    from librelane.flows import Flow

    Chip = Flow.factory.get("Chip")
    Classic = Flow.factory.get("Classic")
    assert "Stages" in Chip.__dict__, (
        "Chip must declare its own Stages list, not inherit Classic's"
    )
    assert Chip.Stages != Classic.Stages
```

Replace the `GOLDEN` list above with the exact contents of `/tmp/claude/chip_golden.json` from Step 1 if the two disagree. The capture is authoritative.

- [ ] **Step 3: Run it against the current `Chip` and confirm it passes**

Run: `uv run pytest test/flows/test_chip.py::test_chip_expands_to_the_same_steps_the_substitution_map_produced -v`

Expected: PASS. This proves the golden list is right before anything changes. The second test is expected to FAIL at this point, because `Chip` has no `Stages` of its own yet.

- [ ] **Step 4: Rewrite `librelane/flows/chip.py`**

Replace the whole file below the licence header with:

```python
from .flow import Flow
from .classic import Classic
from ..stages import Stage
from ..steps import (
    OpenROAD,
    KLayout,
    Odb,
    Checker,
    Misc,
)


@Flow.factory.register()
class Chip(Classic):
    """
    A flow of type :class:`librelane.flows.SequentialFlow` that is used
    to implement complete chip designs. This includes pad ring generation,
    seal ring generation, filler insertion, and density check.

    It subclasses :class:`Classic` for the configuration variables, which are
    genuinely shared, but declares its own ``Stages``.
    """

    #: Written out in full rather than derived from ``Classic.Stages``, for the
    #: reason given on ``VHDLClassic.Stages``. The differences from ``Classic``
    #: are ``OpenROAD.PadRing`` after ``Odb.SetPowerConnections``, the six
    #: finishing steps after ``Checker.XOR``, and three omissions:
    #: ``Magic.WriteLEF`` and ``Odb.CheckDesignAntennaProperties``, which a chip
    #: does not need because it is not a macro, and ``Stage.io_placement``,
    #: whose pins are the pad ring's bumps.
    #:
    #: ``Stage.io_placement`` is omitted rather than pinned to another provider,
    #: and the two steps of it a chip still needs are listed here as plain
    #: steps. ``OpenROAD.GlobalPlacementSkipIO`` seeds placement before the pins
    #: exist and ``Odb.ApplyDEFTemplate`` copies a pin arrangement from a
    #: template, neither of which places a pin itself. The cost is that this
    #: flow has no ``io_placement`` boundary and so cannot swap that stage's
    #: tool from ``TOOLS``.
    Stages = [
        Stage.lint,
        Stage.synthesis,
        Stage.pre_pnr_sta,
        Stage.floorplan,
        Odb.SetPowerConnections,
        OpenROAD.PadRing,
        Stage.macro_placement,
        OpenROAD.CutRows,
        Stage.tapcell_insertion,
        Stage.power_grid,
        Odb.AddRoutingObstructions,
        OpenROAD.GlobalPlacementSkipIO,
        Odb.ApplyDEFTemplate,
        Stage.global_placement,
        Odb.WriteVerilogHeader,
        Checker.PowerGridViolations,
        OpenROAD.STAMidPNR,
        Stage.post_gpl_repair,
        Odb.ManualGlobalPlacement,
        Stage.detailed_placement,
        Stage.cts,
        OpenROAD.STAMidPNR,
        Stage.post_cts_opt,
        OpenROAD.STAMidPNR,
        Stage.global_routing,
        Stage.post_grt_repair,
        Stage.antenna_repair,
        Stage.post_grt_opt,
        OpenROAD.STAMidPNR,
        Stage.detailed_routing,
        Odb.ReportDisconnectedPins,
        Checker.DisconnectedPins,
        Odb.ReportWireLength,
        Checker.WireLength,
        Stage.post_route_opt,
        Stage.fill_insertion,
        Odb.CellFrequencyTables,
        Stage.extraction,
        Stage.signoff_sta,
        Stage.ir_drop,
        Stage.streamout,
        KLayout.XOR,
        Checker.XOR,
        KLayout.Antenna,
        Checker.KLayoutAntenna,
        KLayout.SealRing,
        KLayout.Filler,
        KLayout.Density,
        Checker.KLayoutDensity,
        Stage.drc,
        Stage.lvs,
        Stage.formal_equivalence,
        Checker.SetupViolations,
        Checker.HoldViolations,
        Checker.MaxSlewViolations,
        Checker.MaxCapViolations,
        Misc.ReportManufacturability,
    ]

    #: ``Classic`` gates ``Magic.WriteLEF`` with ``RUN_MAGIC_WRITE_LEF``, and
    #: this flow has no such step, so that entry is dropped. The rest are
    #: restated rather than inherited because ``_explicit_gating_config_vars``
    #: is what a subclass inherits and a gating key naming no step raises.
    gating_config_vars = {
        "Odb.HeuristicDiodeInsertion": ["RUN_HEURISTIC_DIODE_INSERTION"],
        "Magic.StreamOut": ["RUN_MAGIC_STREAMOUT"],
        "KLayout.StreamOut": ["RUN_KLAYOUT_STREAMOUT"],
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

- [ ] **Step 5: Run the golden test**

Run: `uv run pytest test/flows/test_chip.py -v`

Expected: both PASS. If the step list differs, the diff names the exact position. The likely causes are the position of `OpenROAD.PadRing` relative to `Stage.macro_placement`, and whether `Odb.WriteVerilogHeader` precedes or follows the two plain io_placement steps. Compare against the Step 1 output and move the `Stages` entry rather than editing the golden list.

- [ ] **Step 6: Run the existing staged tests**

Run: `uv run pytest -n auto test/flows/ -v`

Expected: `test/flows/test_staged.py:362-372`, which asserts `Chip._applied_substitutions` grows by one under `Substitute`, still passes because `Substitutions` still exists at this point. It is deleted in Task 6.

- [ ] **Step 7: Lint and commit**

```bash
make lint
git add librelane/flows/chip.py test/flows/test_chip.py
git commit -m "refactor: give Chip an explicit Stages list"
```

---

## Task 6: Delete `Substitutions` and `substituting_steps`

The largest deletion. Removes the fourth live defect with it, `--flow` silently discarding `meta.substituting_steps`, by removing the field that was discarded.

This deletes the ECO workflow. `Odb.InsertECOBuffers` appears in no flow's step list and `meta.substituting_steps` was the only way it ever entered one. That is accepted, per the spec. The step classes stay registered and remain usable from a flow class that names them.

**Files:**
- Modify: `librelane/flows/sequential.py:40-58`, `:75-112`, `:114`, `:117-123`, `:142-146`, `:264-345`
- Modify: `librelane/flows/staged.py:83`, `:97`, `:143`, `:161`, `:181-187`, `:391`, `:628`
- Modify: `librelane/stages/registry.py:80`
- Modify: `librelane/config/config.py:146-148`
- Modify: `librelane/cli/run.py:134-144`
- Delete: `librelane/examples/hold_eco_demo/config.yaml`, `librelane/examples/hold_eco_demo/demo.v`
- Delete: `docs/source/usage/using_ecos.md`
- Modify: `docs/source/usage/writing_custom_flows.md:17-68`
- Modify: `test/flows/test_sequential.py:150-300`, `test/flows/test_staged.py:73-76`, `:320-400`, `:435`, `test/flows/test_staged_equivalence.py:54`

**Interfaces:**
- Removes `SequentialFlow.Substitute`, `SequentialFlow.Substitutions`, `SequentialFlow._applied_substitutions`, `SequentialFlow._substitute_in_place`, `Substitution`, `SubstitutionsObject`, `_substitution_pairs`, and `Meta.substituting_steps`. Nothing replaces them.

- [ ] **Step 1: Delete the module-level types**

In `librelane/flows/sequential.py`, delete lines 40 through 58, which are `Substitution`, `SubstitutionsObject` and `_substitution_pairs`. Then remove `Union` from the `typing` import if nothing else in the file uses it, which `grep -n 'Union' librelane/flows/sequential.py` will tell you.

- [ ] **Step 2: Delete the class attributes and the docstring paragraphs**

In `librelane/flows/sequential.py`, delete from the `SequentialFlow` docstring the `:param Substitute:` block at lines 75 through 80 and the `:cvar Substitutions:` block at lines 89 through 111. Delete the `Substitutions: SubstitutionsObject | None = None` line at 114, and the `_applied_substitutions` comment and declaration at lines 117 through 123.

- [ ] **Step 3: Delete the application in `__init_subclass__`**

In `librelane/flows/sequential.py`, delete lines 140 and 142 through 146:

```python
        Self._applied_substitutions = list(Self._applied_substitutions)
```

and

```python
        if Self.Substitutions:
            pairs = _substitution_pairs(Self.Substitutions)
            Self._substitute_in_place(Self, pairs)
            Self._applied_substitutions += pairs
            Self.Substitutions = None
```

What remains in `__init_subclass__` after `super().__init_subclass__(**kwargs)` is the three `.copy()` lines, `Self._normalize_step_ids(Self)`, and `Self._validate_gating_config_vars(Self)`.

- [ ] **Step 4: Delete the three substitution methods**

In `librelane/flows/sequential.py`, delete `Substitute` at lines 264 through 274, `_substitute_in_place` at 276 through 289, and `__substitute_step` at 291 through 345. What remains between `Make` and `_normalize_step_ids` is nothing. Do not delete `_normalize_step_ids`, which the duplicate-ID logic still needs. Note that `__substitute_step` ended with a call to `target._normalize_step_ids(target)`; that call goes with it, and `__init_subclass__` already calls it once.

- [ ] **Step 5: Delete the `fnmatch` import if it is now unused**

Run `grep -n 'fnmatch' librelane/flows/sequential.py`. If the only hit is the import, delete it.

- [ ] **Step 6: Delete the replay in `StagedFlow.__init__`**

In `librelane/flows/staged.py`, inside the `if reexpanded:` block, delete the comment at lines 180 through 186 and the call at 187:

```python
            # In the same order the class definition used: normalize, then
            # substitute. resolve() knows nothing about Substitutions, so the
            # freshly expanded list has none of them, and the class no longer
            # holds Substitutions to consult - __init_subclass__ cleared it after
            # applying it. A substitution key naming a step this provider
            # selection removed raises here, which is correct: it named a step
            # that is not in the flow.
            self._substitute_in_place(self, self._applied_substitutions)
```

What remains inside `if reexpanded:` is the `self.Steps = resolution.steps` assignment, `self._normalize_step_ids(self)`, `self._apply_stage_gating(self)` and `self.__prune_deselected_gates(self)`.

- [ ] **Step 7: Correct the four comments that name the mechanism**

- `librelane/flows/staged.py:83` reads ``` ``Substitute``, ``get_help_md``, step IDs and step directory names. ``` Change to ``` ``get_help_md``, step IDs and step directory names. ```
- `librelane/flows/staged.py:97` explains why generated gating entries are rebuilt per subclass by reference to `Substitutions`. Rewrite the reason as: generated entries name concrete step IDs, and a subclass declaring its own `Stages` produces different ones, so an inherited entry would name a step that is not in the flow.
- `librelane/flows/staged.py:161` reads `# directly, no Stages) or a Substitute()'d one has a self.Steps that`. Drop the `or a Substitute()'d one` clause.
- `librelane/flows/staged.py:391` and `:628`, and `librelane/stages/registry.py:80`, each name `Substitutions` as a thing the tagging survives. Replace with `duplicate-ID normalization` alone, which is the other half of each sentence and remains true.

- [ ] **Step 8: Delete the config field**

In `librelane/config/config.py`, delete from `Meta`:

```python
    substituting_steps: None | dict[str, str | None] | list[tuple[str, str | None]] = (
        None
    )
```

- [ ] **Step 9: Delete the CLI branch**

In `librelane/cli/run.py`, inside `select_flow`, delete lines 134 through 144:

```python
            if meta.substituting_steps is not None:
                if meta.flow is None:
                    logger.error(
                        "Configuration has substituting_steps set with no flow."
                    )
                    raise typer.Exit(1)
                assert target_flow is not None, (
                    "run failed to deduce a target flow; please file an issue"
                )
                if issubclass(target_flow, SequentialFlow):
                    target_flow = target_flow.Substitute(meta.substituting_steps)  # type: ignore
```

- [ ] **Step 10: Delete the ECO example and its documentation**

```bash
git rm -r librelane/examples/hold_eco_demo
git rm docs/source/usage/using_ecos.md
```

Then remove every reference to it. Find them with `grep -rn 'using_ecos' docs/source/`. There are at least two: the toctree entry that lists the page, and a `{doc}` cross-reference at `docs/source/usage/resuming_runs.md:95`, which reads `` is the pattern the {doc}`ECO guide <using_ecos>` uses. `` A `{doc}` role pointing at a deleted page fails the documentation build, so both must go in this commit. Read the sentence at `resuming_runs.md:93-95` and rewrite it to describe the pattern without the cross-reference.

- [ ] **Step 11: Delete the substitution section of the custom-flows guide**

In `docs/source/usage/writing_custom_flows.md`, delete the section anchored `(config-substituting-steps)=` at line 17 through the paragraph ending at line 68, which is everything up to the `(config-by-listing-steps)=` anchor. That anchor is itself deleted in Task 7, so leave it for now.

- [ ] **Step 12: Delete the tests that exercise the mechanism**

- `test/flows/test_sequential.py`: delete every test using `.Substitute(`. Read each function fully before deleting so that a test asserting something unrelated in the same body is preserved. The call sites are at lines 159, 194, 239, 242, 244, 261, 281 and 294.
- `test/flows/test_staged.py`: delete the `Substituted = SmallStaged.Substitute(...)` test at lines 73 through 76, the `_applied_substitutions` test at lines 362 through 372, and the `Substitutions = {"+Test.Alpha": Extra}` test around line 397. Update the docstring at lines 328 and 435 that explain behaviour in terms of `Substitutions`.
- `test/flows/test_staged_equivalence.py:54`: the comment says the step list "until now took a Substitutions map to produce". Rewrite as a statement about the step list itself.

- [ ] **Step 13: Confirm nothing references it**

Run: `grep -rn 'Substitut\|substituting_steps' librelane/ test/ docs/source/`

Expected: no output. `Changelog.md` and `docs/superpowers/` are excluded deliberately; historical entries stay.

- [ ] **Step 14: Test, lint and commit**

Run: `uv run pytest -n auto`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat!: remove Substitutions and meta.substituting_steps"
```

---

## Task 7: Delete `meta.flow` as a step-ID list and `SequentialFlow.make`

`SequentialFlow.Make` is retained, because the test suite builds flows with it in five places.

**Files:**
- Modify: `librelane/config/config.py:145`
- Modify: `librelane/cli/run.py:132-133`
- Modify: `librelane/flows/sequential.py:255-262`
- Modify: `docs/source/usage/writing_custom_flows.md:70-100`

- [ ] **Step 1: Narrow the config field**

In `librelane/config/config.py`, change:

```python
    flow: None | str | list[str] = None
```

to:

```python
    flow: None | str = None
```

- [ ] **Step 2: Reject the list form explicitly in the CLI**

`Meta.from_dict` at `librelane/config/config.py:153-158` is `Self(**meta_dict_copy)` on a plain dataclass, so it validates nothing. Narrowing the annotation in Step 1 does not by itself reject a list; it would arrive as a list, fail the surviving `isinstance(meta.flow, str)` test, fall through, and silently run `Classic`. Silently running a different flow than the configuration named is worse than the feature being gone, so the rejection is explicit.

In `librelane/cli/run.py`, inside `select_flow`, replace lines 123 through 133:

```python
            if isinstance(meta.flow, str):
                if found := Flow.factory.get(meta.flow):
                    target_flow = found
                else:
                    logger.error(
                        f"Unknown flow '{meta.flow}' specified in the "
                        "configuration file's 'meta' object."
                    )
                    raise typer.Exit(1)
            elif isinstance(meta.flow, list):
                target_flow = SequentialFlow.make(meta.flow)
```

with:

```python
            if meta.flow is not None:
                if not isinstance(meta.flow, str):
                    logger.error(
                        f"'meta.flow' must name a registered flow, but got a "
                        f"{type(meta.flow).__name__}. Building an anonymous "
                        f"flow from a list of step IDs is no longer supported; "
                        f"declare a flow class and name it here instead."
                    )
                    raise typer.Exit(1)
                if found := Flow.factory.get(meta.flow):
                    target_flow = found
                else:
                    logger.error(
                        f"Unknown flow '{meta.flow}' specified in the "
                        "configuration file's 'meta' object."
                    )
                    raise typer.Exit(1)
```

Then delete the `SequentialFlow` import from `librelane/cli/run.py` if nothing else in the file uses it. Check with `grep -n 'SequentialFlow' librelane/cli/run.py`. Note that Task 14 adds a `SequentialFlow` import back for the `--explain` guard, so if these tasks land out of order the import may legitimately still be needed.

- [ ] **Step 3: Delete the deprecated `make`**

In `librelane/flows/sequential.py`, delete:

```python
    @classmethod
    @deprecated(
        "use .Make",
        version="3.0.0",
        action="once",
    )
    def make(Self, step_ids: list[str]) -> type[SequentialFlow]:
        return Self.Make(step_ids)
```

Check whether `deprecated` is still imported for another use in the file with `grep -n 'deprecated' librelane/flows/sequential.py`, and delete the import if not.

- [ ] **Step 4: Delete the documentation section**

In `docs/source/usage/writing_custom_flows.md`, delete the `(config-by-listing-steps)=` anchor, the `#### By Listing Steps` heading, its prose and the fifteen-step JSON example, lines 69 through 100. Then search the docs tree for references to that anchor with `grep -rn 'config-by-listing-steps' docs/source/` and remove or retarget each.

- [ ] **Step 5: Write the test that the list form is rejected**

Append to `test/cli/test_runtime.py`:

```python
def test_meta_flow_as_a_step_list_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    meta.flow names a registered flow. A list of step IDs used to build an
    anonymous one; now it must fail loudly, because falling through to the
    default flow would run something the configuration did not ask for.
    """
    import librelane.cli.run as run_module

    config = tmp_path / "config.json"
    config.write_text(
        '{"meta": {"version": 2, "flow": ["Yosys.Synthesis"]}}',
        encoding="utf8",
    )
    monkeypatch.setattr(run_module, "start_flow", lambda request: None)

    result = runner.invoke(
        cli,
        [
            "--manual-pdk",
            "--pdk-root",
            str(tmp_path),
            str(config),
        ],
    )

    assert result.exit_code == 1, result.output
```

The `runner`, `cli` and `--manual-pdk` idioms are the ones already used by the request-capturing test at `test/cli/test_runtime.py:165-192`. Read that test first and mirror its setup exactly.

- [ ] **Step 6: Test, lint and commit**

Run: `uv run pytest -n auto test/config/ test/cli/ test/flows/ -v`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat!: remove the step-list form of meta.flow and SequentialFlow.make"
```

---

## Task 8: Delete the non-sequential flows and the stale 2.0 deprecations

`Optimizing` is the only in-tree caller of `set_max_stage_count`, `start_stage` and `end_stage` in their deprecated `Flow` spellings, so both deletions go together. `init_with_config` and `Toolbox.aggregate_metrics` have no callers at all.

`Flow.start_step_async` is deliberately retained even though this task removes its only callers. It is documented public API and is the seam the workflow engine builds on.

**Files:**
- Delete: `librelane/flows/optimizing.py`, `librelane/flows/synth_explore.py`
- Modify: `librelane/flows/builtins.py:15`, `:19`
- Modify: `librelane/flows/flow.py:607-618`, `:828`, `:1070-1104`
- Modify: `librelane/common/toolbox.py:59-69`
- Modify: `test/flows/test_flow.py:157`
- Modify: `docs/source/usage/writing_custom_flows.md:295-315`
- Modify: `docs/source/usage/resuming_runs.md:105`
- Modify: `docs/source/additional_material/caravel/macro_first_hardening/index.md:108`

- [ ] **Step 1: Delete the two flow modules**

```bash
git rm librelane/flows/optimizing.py librelane/flows/synth_explore.py
```

- [ ] **Step 2: Unregister them**

In `librelane/flows/builtins.py`, delete `from .optimizing import Optimizing` and `from .synth_explore import SynthesisExploration`. The file keeps its `# flake8: noqa` line and the three remaining imports.

- [ ] **Step 3: Fix the docstring cross-reference**

`librelane/flows/flow.py:828` refers to `:class:`librelane.flows.Optimizing`` as the example of a flow that builds steps in a data-dependent loop. Rewrite the sentence so it describes the case without naming a class, for example "a flow that builds its steps in a data-dependent loop, and so has no fixed position for a step".

- [ ] **Step 4: Delete the five deprecated methods**

In `librelane/flows/flow.py`, delete `init_with_config` with its decorator, lines 607 through 618, and `set_max_stage_count`, `start_stage` and `end_stage` with their decorators, lines 1070 through 1104. Do **not** touch `FlowProgressBar.set_max_stage_count` at line 225, `FlowProgressBar.start_stage` at 236 or `FlowProgressBar.end_stage` at 248. Those are the real implementations and are called throughout.

In `librelane/common/toolbox.py`, delete the `aggregate_metrics` method and its `@deprecated` decorator, lines 59 through 69. The module-level `from .metrics import aggregate_metrics` import at line 37 must stay only if something else in the file uses it; check with `grep -n 'aggregate_metrics' librelane/common/toolbox.py` after the deletion, and delete the import if the method was the only user.

- [ ] **Step 5: Update the factory test**

In `test/flows/test_flow.py:157`, remove `"Optimizing",` from the list of flows asserted present in `Flow.factory.list()`. The remaining entries are `"Classic"`, `"OpenInKLayout"` and `"OpenInOpenROAD"`.

- [ ] **Step 6: Rewrite the Multi-Threading section of the custom-flows guide**

In `docs/source/usage/writing_custom_flows.md`, the section at lines 295 through 315 introduces `start_step_async` and then `literalinclude`s `librelane/flows/optimizing.py`. A `literalinclude` of a deleted file fails the documentation build, so this must land in the same commit.

Delete the `literalinclude` block:

````markdown
```{literalinclude} ../../../librelane/flows/optimizing.py
---
language: python
start-after: "@Flow.factory.register()"
---
```
````

and the three bullet points above it describing the two stages of that demo. Replace them with an inline example, written in the page rather than included from a flow, so that no future flow deletion can break the build again:

````markdown
Here is a flow built on exactly this principle. It runs two floorplanning
attempts concurrently and keeps whichever produced the smaller die.

```python
@Flow.factory.register()
class TryTwoUtilizations(Flow):
    Steps = [Yosys.Synthesis, OpenROAD.Floorplan]

    def run(self, initial_state, **kwargs):
        synthesized = self.start_step(
            Yosys.Synthesis(config=self.config, state_in=initial_state),
        )

        attempts = [
            self.start_step_async(
                OpenROAD.Floorplan(
                    config=self.config.copy(FP_CORE_UTIL=utilization),
                    state_in=synthesized,
                    id=f"floorplan-{utilization}",
                ),
            )
            for utilization in (60, 40)
        ]

        # Inspecting a Future blocks until that chain has run, so the two
        # floorplans run in parallel and both are complete after this line.
        results = [attempt.result() for attempt in attempts]
        best = min(results, key=lambda state: state.metrics["design__die__area"])
        return best, []
```

A flow whose steps depend on each other's results this way is what the
{meth}`librelane.flows.Flow.start_step_async` seam exists for. Note that the
`Flow` object is not thread-safe, so everything above happens on one thread and
only the steps themselves run concurrently.
````

- [ ] **Step 7: Update the two remaining documentation references**

In `docs/source/usage/resuming_runs.md`, replace the whole "Which flows participate" section, lines 101 through 107, which reads:

```markdown
## Which flows participate

Resume applies to sequential flows, which includes `Classic` and every flow
built from a fixed list of steps.

`Optimizing` and `SynthesisExploration` build their steps in data-dependent
loops, so a step's position is not knowable in advance and there is nothing
stable to reuse against. They re-run in full.
```

with:

```markdown
## Which flows participate

Every flow LibreLane ships. Resume needs a step's position in the flow to be
knowable before the flow runs, which is true of any flow built from a fixed list
of steps, and every built-in flow is built that way.

A flow that builds its steps in a data-dependent loop, deciding what to run next
from what the last step produced, has no such position and cannot be resumed.
None ships today.
```

- `docs/source/additional_material/caravel/macro_first_hardening/index.md:108` shows a `librelane ... --flow SynthesisExploration` invocation in a tutorial transcript. Read the surrounding tutorial step and remove or rewrite it, since the flow no longer exists.

- [ ] **Step 8: Confirm nothing references either flow**

Run: `grep -rn 'Optimizing\|SynthesisExploration\|init_with_config' librelane/ test/ docs/source/`

Expected: no output. Note that `docs/source/reference/flows.md` is generated and untracked; it regenerates without them.

- [ ] **Step 9: Build the documentation**

Run: `make docs`

Expected: no `literalinclude` error and no broken cross-reference warning for `librelane.flows.Optimizing`.

- [ ] **Step 10: Test, lint and commit**

Run: `uv run pytest -n auto`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat!: remove Optimizing, SynthesisExploration and the stale 2.0 deprecations"
```

---

## Task 9: Delete `Stage.config_vars` and `Registration.requires_pdk_vars`

Both are dead declarative surface. `Stage.config_vars` is empty on all twenty-seven registered stages, so the registration-time check that every provider accepts a stage's canonical variables never checks anything. `requires_pdk_vars` has no shipped user.

Provider variable portability continues to be enforced by the namespace allowlist at `librelane/stages/registry.py:194-209`, which is the half of `__check_contract` that actually runs today. Do not delete that.

**Files:**
- Modify: `librelane/stages/stage.py:79-80`, `:96`
- Modify: `librelane/stages/registry.py:48-50`, `:65`, `:115`, `:131`, `:178-191`, `:195`
- Modify: `librelane/flows/staged.py:205`, `:208-240`
- Modify: `test/stages/test_registry.py:105-120`
- Modify: `test/flows/test_staged.py:1017-1074`
- Modify: `docs/source/usage/writing_tool_backends.md:35`, `:54`, `:100`

- [ ] **Step 1: Delete the `Stage` field**

In `librelane/stages/stage.py`, delete the `:param config_vars:` lines 79 and 80 from the class docstring and the field declaration at line 96:

```python
    config_vars: tuple[Variable, ...] = field(default=())
```

Then check whether `Variable` and `field` are still used in the module with `grep -n 'Variable\|field(' librelane/stages/stage.py` and remove either import if not.

- [ ] **Step 2: Delete the canonical-variable check**

In `librelane/stages/registry.py`, inside `__check_contract`, delete lines 178 through 191, which build `canonical` and check coverage. Then at line 195, the namespace loop begins:

```python
        for variable in union.config_vars:
            if variable.name in canonical:
                continue
            if variable.name in _COMMON_VARIABLE_NAMES:
```

Delete the two lines referring to `canonical`, leaving:

```python
        for variable in union.config_vars:
            if variable.name in _COMMON_VARIABLE_NAMES:
```

Then update the error message at lines 203 through 209, which says the variable is "neither canonical for these stages, nor a common flow variable, nor prefixed with any of". Remove the "neither canonical for these stages" clause so it reads "which is neither a common flow variable nor prefixed with any of".

`__check_contract` still takes its `stages` argument, which the view-plausibility and provides checks below still use. Do not change its signature.

- [ ] **Step 3: Delete `requires_pdk_vars`**

In `librelane/stages/registry.py`, delete the `:param requires_pdk_vars:` docstring lines 48 through 50, the field at line 65, the `register` keyword at line 115, and the constructor argument at line 131.

- [ ] **Step 4: Delete the preflight**

In `librelane/flows/staged.py`, delete the call `self._preflight_pdk_vars()` at line 205 and the whole `_preflight_pdk_vars` method, lines 208 through 240. `self._preflight_views()` at line 206 stays and becomes the only preflight.

- [ ] **Step 5: Delete the two tests**

- `test/stages/test_registry.py`: delete `test_missing_canonical_variable_raises` in full, the function containing lines 112 and 117.
- `test/flows/test_staged.py`: delete the `PdkHungryStage` fixture and `test_missing_pdk_variable_names_stage_provider_variable_and_pdk`, lines 1017 through 1074.

- [ ] **Step 6: Update the tool-backend guide**

In `docs/source/usage/writing_tool_backends.md`, delete `requires_pdk_vars=(),` from the example at line 35, the bullet describing it at line 54, and the sentence at line 100 that says `StagedFlow._preflight_pdk_vars` checks every entry.

- [ ] **Step 7: Confirm nothing references either**

Run: `grep -rn 'requires_pdk_vars\|_preflight_pdk_vars' librelane/ test/ docs/source/` and `grep -n 'config_vars' librelane/stages/stage.py librelane/stages/taxonomy.py`

Expected: the first returns nothing. The second returns only the `Classic.gating_config_vars` reference in the `taxonomy.py` module docstring, which is about a different attribute and stays.

- [ ] **Step 8: Test, lint and commit**

Run: `uv run pytest -n auto test/stages/ test/flows/ -v`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat!: delete Stage.config_vars and Registration.requires_pdk_vars"
```

---

## Task 10: Collapse spanning registrations to a single stage

The registry accepts a `stages` tuple of length greater than one and exposes a `spanning` property, while resolution rejects every spanning registration unconditionally. All 103 shipped registrations name exactly one stage, so this is mechanical.

**Files:**
- Modify: `librelane/stages/registry.py:38-40`, `:61`, `:70-72`, `:90`, `:111`, `:127`, `:137-165`, `:188`, `:205`, `:225`, `:238`, `:255`
- Modify: `librelane/stages/resolution.py:145-150`
- Modify: `librelane/flows/staged.py:302`, `:312`
- Modify: `librelane/stages/providers.py` (29 entries), `librelane/steps/fc.py` (18), `icc2.py` (17), `innovus.py` (17), `calibre.py` (2), `pegasus.py` (2), `pt.py` (2), `icv.py` (2), `tempus.py` (2), `conformal.py` (1), `voltus.py` (1), `dc.py` (1), `genus.py` (1), `quantus.py` (1), `fm.py` (1), `starrc.py` (1), `vc_spyglass.py` (1)
- Modify: `librelane/steps/fc.py:334-336`, `librelane/steps/innovus.py:391-392`, `librelane/steps/step/composite.py:48-51`
- Modify: `test/stages/test_registry.py`, `test/flows/test_staged.py`
- Modify, for the `entry["stages"]` dict key: `test/stages/test_providers.py:95`, `:105`, `:126`, `:135`; `test/stages/test_providers_vendor.py:119`; `test/steps/test_vendor_cadence.py:289-378` (15 uses); `test/steps/test_vendor_synopsys_pnr.py:196-224` (8 uses); `test/steps/test_vendor_signoff.py:228`
- Modify: `docs/source/usage/writing_tool_backends.md:31`, `:41-44`, `:175`, `:178-207`

**Interfaces:**
- `Registration.stages: tuple[str, ...]` becomes `Registration.stage: str`.
- `StageRegistry.register(*, stages: Sequence[str], ...)` becomes `StageRegistry.register(*, stage: str, ...)`.
- `Registration.spanning` is removed.
- `Registration.tagged_steps()` sets `_stage_span` to `(self.stage,)`, keeping the tuple shape that `StagedFlow.stage_boundaries` scans for. Do not change `_stage_span` to a bare string; the boundary recovery compares tag equality across contiguous steps and the tuple is what it compares.

- [ ] **Step 1: Write the failing test**

Append to `test/stages/test_registry.py`:

```python
def test_registration_names_exactly_one_stage(alpha_stage, mock_steps):
    """
    The registry used to accept a stages tuple the resolver rejected outright.
    A shape no consumer accepts is not a feature.
    """
    from librelane.stages import Registration, StageRegistry

    MockPlace, _ = mock_steps
    registration = StageRegistry.register(
        stage="registry_alpha",
        provider="single",
        steps=[MockPlace],
        namespaces=["TEST_"],
    )

    assert registration.stage == "registry_alpha"
    assert not hasattr(registration, "stages")
    assert not hasattr(registration, "spanning")
    assert not hasattr(Registration, "spanning")
```

Read the existing `alpha_stage` and `mock_steps` fixtures in `test/stages/test_registry.py` and `test/stages/conftest.py` before writing this, and match the provider name to one not already registered in that module, since `StageRegistry` is a process-wide singleton and a duplicate raises.

- [ ] **Step 2: Run it and confirm failure**

Run: `uv run pytest test/stages/test_registry.py::test_registration_names_exactly_one_stage -v`

Expected: FAIL with `TypeError: register() got an unexpected keyword argument 'stage'`.

- [ ] **Step 3: Change the dataclass**

In `librelane/stages/registry.py`:

Replace the `:param stages:` docstring lines 38 through 40 with:

```python
    :param stage: The stage id this registration implements. Exactly one. A
        provider that cannot decompose a span of stages has no way to say so,
        deliberately: gating, contract checking and provider selection are all
        per-stage.
```

Replace the field at line 61:

```python
    stages: tuple[str, ...]
```

with:

```python
    stage: str
```

Delete the `spanning` property at lines 70 through 72.

At line 90, inside `tagged_steps`, replace `"_stage_span": self.stages,` with `"_stage_span": (self.stage,),`.

- [ ] **Step 4: Change `register`**

In `librelane/stages/registry.py`, replace the keyword `stages: Sequence[str],` at line 111 with `stage: str,`, and the constructor argument `stages=tuple(stages),` at line 127 with `stage=stage,`.

Delete the empty-stages check at lines 137 and 138:

```python
        if len(registration.stages) == 0:
            raise StageError(f"Provider '{provider}' registered against no stages.")
```

It is unreachable once `stage` is a single required string.

Replace the resolution loop at lines 146 through 160:

```python
        resolved: builtins.list[Stage] = []
        for stage_id in registration.stages:
            stage = Stage.factory.get(stage_id)
            if stage is None:
                raise StageError(
                    f"Provider '{provider}': no stage with id '{stage_id}' is "
                    f"registered. Known stages: {sorted(Stage.factory.list())}"
                )
            key = (stage_id, provider)
            if key in Self._by_stage_and_provider:
                raise StageError(
                    f"Provider '{provider}' is already registered for stage "
                    f"'{stage_id}'."
                )
            resolved.append(stage)
```

with:

```python
        resolved_stage = Stage.factory.get(registration.stage)
        if resolved_stage is None:
            raise StageError(
                f"Provider '{provider}': no stage with id "
                f"'{registration.stage}' is registered. Known stages: "
                f"{sorted(Stage.factory.list())}"
            )
        key = (registration.stage, provider)
        if key in Self._by_stage_and_provider:
            raise StageError(
                f"Provider '{provider}' is already registered for stage "
                f"'{registration.stage}'."
            )
```

Replace `Self.__check_contract(registration, resolved)` at line 162 with `Self.__check_contract(registration, resolved_stage)`, and the registration loop at lines 164 and 165:

```python
        for stage_id in registration.stages:
            Self._by_stage_and_provider[(stage_id, provider)] = registration
```

with:

```python
        Self._by_stage_and_provider[key] = registration
```

- [ ] **Step 5: Change `__check_contract` to take one stage**

In `librelane/stages/registry.py`, change the signature from `stages: Sequence[Stage]` to `stage: Stage`, and replace each `for stage in stages:` loop with a direct use. After Task 9 removed the canonical block, three uses remain: `allowed_inputs.update(stage.requires)`, `promised.update(stage.provides)`, and the four error messages that interpolate `{list(registration.stages)}`. Replace every one of those with `'{registration.stage}'`, quoted as a single id rather than a list.

- [ ] **Step 6: Change `providers`**

In `librelane/stages/registry.py`, replace line 255, `if stage in registration.stages`, with `if registration.stage == stage`.

- [ ] **Step 7: Delete the resolver rejection**

In `librelane/stages/resolution.py`, delete lines 145 through 150:

```python
    if registration.spanning:
        raise StageResolutionError(
            f"stage '{stage.id}': provider '{provider}' is a spanning "
            f"registration covering {list(registration.stages)}, which is not "
            f"supported: no provider may cover more than one stage."
        )
```

- [ ] **Step 8: Fix the two diagnostic comprehensions**

In `librelane/flows/staged.py`, the two producer diagnostics at lines 302 and 312 read:

```python
                for registration in StageRegistry.list()
                for stage_id in registration.stages
                if view in registration.provides
```

Replace the two-level comprehension with one level in each, binding `registration.stage` directly:

```python
                f"provider '{registration.provider}' of stage "
                f"'{registration.stage}'"
                for registration in StageRegistry.list()
                if view in registration.provides
```

and the corresponding change in the `native_views` comprehension below it.

- [ ] **Step 9: Rewrite every registration entry**

Every shipped registration is a dict literal with a `"stages": ["x"]` key. Change each to `"stage": "x"`. Apply with a scripted edit and then verify by eye:

```bash
uv run --no-sync python - <<'PY'
import re, pathlib
pattern = re.compile(r'"stages": \[("(?:[a-z_]+)")\]')
paths = list(pathlib.Path("librelane").rglob("*.py"))
for path in paths:
    text = path.read_text()
    new, count = pattern.subn(r'"stage": \1', text)
    if count:
        path.write_text(new)
        print(f"{path}: {count}")
PY
```

Expected output: `librelane/stages/providers.py: 29`, plus the sixteen vendor step modules, totalling 103.

Then confirm no multi-element list survived:

```bash
grep -rn '"stages"' librelane/
```

Expected: no output. If any hit remains, it is a registration naming more than one stage and must be split into one registration per stage by hand.

- [ ] **Step 10: Update the source comments that describe spanning**

- `librelane/steps/fc.py:334-336` and `librelane/steps/innovus.py:391-392` each explain that the module registers per-stage rather than spanning, citing "Spanning is declared, not implemented". Rewrite both to state that a registration names one stage, without referring to a spanning alternative that no longer exists in the type.
- `librelane/steps/step/composite.py:48-51` claims a `CompositeStep` is "the supported way for a `Registration` to bind one stage to several steps", which registrations do directly. Replace with the true distinction: a composite hides its constituent steps behind one identifier, one configuration model, one directory and one resume unit, whereas a registration keeps them individually addressable, which is what allows a stage gate to be lowered onto each of them.

- [ ] **Step 11: Update the registration keyword in tests**

Replace `stages=["x"]` with `stage="x"` at `test/flows/test_staged.py:168`, `:476`, `:517`, `:632`, and at `test/stages/test_registry.py:42`, `:75`, `:87`, `:94`, `:118`, `:142`, `:164`, `:185`, `:209`, `:221`. Line numbers shift as you edit, so re-locate with `grep -rn 'stages=' test/` after each file.

Delete `test_spanning_registration_covers_every_stage` at `test/stages/test_registry.py:53-64` in full, and change the `assert registration.spanning is False` at line 50 to `assert registration.stage == "registry_alpha"`, matching whichever stage that fixture registers.

- [ ] **Step 12: Update the `entry["stages"]` dict key in tests**

Twenty-eight test sites read the registration dict's `"stages"` key, which Step 9 renamed. They are not caught by `stages=` because they index a literal dict rather than call `register`. Apply:

```bash
uv run --no-sync python - <<'PY'
import re, pathlib
paths = [
    "test/stages/test_providers.py",
    "test/stages/test_providers_vendor.py",
    "test/steps/test_vendor_cadence.py",
    "test/steps/test_vendor_synopsys_pnr.py",
    "test/steps/test_vendor_signoff.py",
]
for name in paths:
    path = pathlib.Path(name)
    text = path.read_text()
    new = text.replace('entry["stages"]', 'entry["stage"]')
    new = new.replace("entry['stages']", "entry['stage']")
    new = new.replace('registration["stages"]', 'registration["stage"]')
    if new != text:
        path.write_text(new)
        print(name)
PY
```

The rename alone leaves five kinds of site broken, because `entry["stage"]` is now a string where a list was expected. Fix each by hand:

- Comprehensions of the form `{stage for entry in REGISTRATIONS for stage in entry["stage"]}` now iterate the characters of a string. Rewrite as `{entry["stage"] for entry in REGISTRATIONS}`. These are at `test/steps/test_vendor_cadence.py:289`, `:300`, `:312`, `:323`, `:334`, `:345`, `:356` and `test/steps/test_vendor_synopsys_pnr.py:196`, `:207`, `:219`.
- Loops of the form `for stage_id in entry["stage"]:` become `stage_id = entry["stage"]` with the loop body de-indented, at `test/steps/test_vendor_cadence.py:293`, `:305`, `:316`, `:327`, `:338`, `:349`, `:360`, `test/steps/test_vendor_synopsys_pnr.py:200`, `:212`, `:224`, `test/stages/test_providers.py:95`, `:126`, and `test/stages/test_providers_vendor.py:119`.
- Assertions `assert len(entry["stage"]) == 1, "each registration should cover one stage"` at `test/steps/test_vendor_cadence.py:304` and `test/steps/test_vendor_synopsys_pnr.py:211`, `:223` are now vacuously true of any non-empty string. Delete them; the type says it.
- Comparisons `next(e for e in REGISTRATIONS if e["stage"] == ["drc"])` at `test/steps/test_vendor_cadence.py:371` and `:378` compare a string to a list. Change the right-hand side to `"drc"` and `"lvs"`.
- `all_stage_ids.update(registration["stage"])` at `test/steps/test_vendor_signoff.py:228` would add each character. Change to `all_stage_ids.add(registration["stage"])`.

- [ ] **Step 13: Extend the metric-declaration test to vendor registrations**

`test_a_tool_specific_metric_is_checked_inside_its_own_registration` at `test/stages/test_providers.py:73` iterates `librelane.stages.providers._REGISTRATIONS` only, so it has never held a vendor registration to the invariant it enforces on the open-source ones. Extend it while you are already editing the loop.

Replace, inside that test:

```python
    from librelane.stages.providers import _REGISTRATIONS

    for entry in _REGISTRATIONS:
```

with:

```python
    from librelane.stages.providers import _REGISTRATIONS
    from librelane.stages.providers_vendor import (
        _REGISTRATIONS as _VENDOR_REGISTRATIONS,
    )

    for entry in _REGISTRATIONS + _VENDOR_REGISTRATIONS:
```

and change the `contracted_by_stage` comprehension to use the single stage:

```python
        contracted_by_stage = set(Stage.factory.get(entry["stage"]).metrics)
```

- [ ] **Step 14: Run it and fix what it catches**

Run: `uv run pytest test/stages/test_providers.py::test_a_tool_specific_metric_is_checked_inside_its_own_registration -v`

Expected: FAIL naming the `pegasus` provider. `librelane/steps/pegasus.py:161` declares a metric its stage already contracts, so the metric is not tool-specific and the declaration is redundant. Delete that entry from the registration's `"metrics"` tuple, then re-run. If the failure names a different provider or a genuinely tool-specific metric with no checker, stop and report it rather than deleting the declaration; that case means a real check is missing.

- [ ] **Step 15: Update the tool-backend guide**

In `docs/source/usage/writing_tool_backends.md`, change the example at line 31 from `stages=["synthesis"],` to `stage="synthesis",`. Rewrite the bullet at lines 41 through 44 to describe a single stage id. Delete the whole "Spanning is declared, not implemented" section, its `(spanning-is-declared-not-implemented)=` anchor at line 178 and the paragraph at line 175 that links to it, and remove or retarget the cross-reference at line 44. The comparison bullets at lines 198 through 207 discuss how other tools handle spanning; read them and keep whatever remains true about tool comparison once LibreLane no longer has the concept.

- [ ] **Step 16: Run the tests**

Run: `uv run pytest -n auto`

Expected: PASS, including `test/steps/test_registry_snapshot.py`, which must be unchanged because no step class was added or removed.

- [ ] **Step 17: Build docs, lint and commit**

Run: `make docs` then `make lint`

```bash
git add -A
git commit -m "feat!: a registration names exactly one stage"
```

---

## Task 11: Promote `flow_control_variable` to an error and remove author-written `Step.config_vars`

A step defining `flow_control_variable` today gets a warning and no gating, so it silently fails to gate. Silence is the defect, so it becomes a `TypeError`.

`class Config` becomes the only spelling an author writes. `config_vars` survives as the derived attribute every consumer reads, and `CompositeStep` keeps assigning it, so the change is to the escape clause in `__init_subclass__`, not to the attribute.

**Files:**
- Modify: `librelane/steps/step/core.py:320-327`
- Modify: `test/steps/test_composition.py:17`, `:26`, `:67`, `test/steps/test_step.py:582`, `test/stages/test_registry.py:135`
- Modify: `test/steps/all/by_id/odb.portdiodeplacement/001-success_both/verify.py:12`, `test/steps/all/by_id/openroad.floorplan/002-success-obstructions/verify.py:15`, `test/steps/all/by_id/openroad.rcx/003-success-disconnected-ios/handler.py:13`, `test/steps/all/by_id/odb.addpdnobstructions/001-success/verify.py:13`
- Modify: `docs/source/usage/writing_custom_steps.md:85`

- [ ] **Step 1: Write the failing tests**

Append to `test/steps/test_step.py`:

```python
def test_flow_control_variable_raises():
    """
    Nothing has read this attribute since 2.0. A step defining it appeared to
    gate and did not, which is worse than a step that refuses to define.
    """
    from librelane.steps import Step

    with pytest.raises(TypeError, match="gating_config_vars"):

        class Gating(Step):
            id = "Test.FlowControlVariable"
            inputs = []
            outputs = []
            flow_control_variable = "RUN_WHATEVER"

            def run(self, state_in, **kwargs):
                return {}, {}


def test_author_written_config_vars_raises():
    """
    'class Config' and 'config_vars' were two spellings of one thing, converted
    one into the other. Eighty-eight shipped steps use Config and none uses
    config_vars.
    """
    from librelane.config import Variable
    from librelane.steps import Step

    with pytest.raises(TypeError, match="class Config"):

        class Author(Step):
            id = "Test.AuthorWrittenConfigVars"
            inputs = []
            outputs = []
            config_vars = [Variable("TEST_VAR", int, "desc", default=1)]

            def run(self, state_in, **kwargs):
                return {}, {}
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/steps/test_step.py -v -k "flow_control_variable or author_written"`

Expected: two FAILs, both `DID NOT RAISE`.

- [ ] **Step 3: Rewrite `__init_subclass__`**

In `librelane/steps/step/core.py`, replace lines 320 through 327:

```python
    def __init_subclass__(cls):
        if "Config" in cls.__dict__ and "config_vars" not in cls.__dict__:
            cls.config_vars = model_to_variables(cls.Config)
        cls._config_model_cache = None
        if hasattr(cls, "flow_control_variable"):
            logger.warning(
                f"Step '{cls.__name__}' uses deprecated property 'flow_control_variable'. Flow control should now be done using the Flow class's 'gating_config_vars' property."
            )
```

with:

```python
    def __init_subclass__(cls):
        if "config_vars" in cls.__dict__:
            raise TypeError(
                f"Step '{cls.__name__}' assigns 'config_vars' directly. Declare "
                f"a nested 'class Config' instead, which is the only spelling "
                f"an author writes; 'config_vars' is derived from it and is "
                f"read-only to a subclass."
            )
        if "Config" in cls.__dict__:
            cls.config_vars = model_to_variables(cls.Config)
        cls._config_model_cache = None
        if hasattr(cls, "flow_control_variable"):
            raise TypeError(
                f"Step '{cls.__name__}' defines 'flow_control_variable', which "
                f"nothing has read since 2.0, so the step silently failed to "
                f"gate. Gate it from the flow instead, with an entry in that "
                f"flow's 'gating_config_vars'."
            )
```

- [ ] **Step 4: Confirm the derived writers are unaffected**

Two places in shipped code assign `config_vars` outside a class body, and neither trips the check. Verify rather than assume.

`librelane/steps/step/composite.py:80` assigns `Self.config_vars = union.config_vars` inside `CompositeStep.__init_subclass__`, which calls `super().__init_subclass__()` on its first line, at `composite.py:63`. `Step.__init_subclass__` therefore runs, and the check with it, before the assignment exists. The class body of a `CompositeStep` subclass declares `Steps`, not `config_vars`.

`Step.with_id` at `librelane/steps/step/core.py:725-729` builds a subclass with `type(name, (Self,), {"id": ..., "_implementation_id": ...})`. `config_vars` is not in that namespace, so the new subclass inherits it.

Confirm both by running the composite and flow suites in Step 6. If a composite does trip the check, do not weaken it; the cause would be a composite whose class body assigns `config_vars`, which is the thing being removed.

- [ ] **Step 5: Convert the test steps that assign `config_vars`**

Six step subclasses in the test suite assign `config_vars` at class level and must become `class Config`. For each, read the existing `Variable` list and write the equivalent nested model using `librelane.config.variable`, following the pattern at `test/flows/test_staged.py:123-126`.

- `test/steps/test_composition.py:17`, `config_vars = [Variable("A_VAR", int, "desc", default=1)]` becomes:

```python
        class Config(Step.Config):
            A_VAR: int = variable(1, description="desc")
```

- `test/steps/test_composition.py:26`, the same shape with `B_VAR`, `int`, default `2`.
- `test/steps/test_composition.py:67`, inside `test_contradictory_config_vars_raise`, `A_VAR` as `str` with default `"x"` and description `"different"`. The test asserts that composing two steps whose `A_VAR` disagree raises; keep that assertion.
- `test/steps/test_step.py:582`, `class BadStep(Step)` sets `config_vars = []`. An empty list is the default, so delete the line entirely rather than converting it. Read the test to confirm the empty list was not the thing under test.
- `test/stages/test_registry.py:135`, `class Rogue(Step)` sets `config_vars = [Variable("WIDGET_COUNT", int, "desc", default=3)]` to drive `test_unnamespaced_variable_raises`. Convert to a `class Config` declaring `WIDGET_COUNT: int = variable(3, description="desc")`.
- `test/steps/all/by_id/odb.addpdnobstructions/001-success/verify.py:13`, this one is different. It reads `config_vars = AddPDNObstructions.config_vars`, aliasing the parent's derived list, then indexes it at lines 22 and 26. Since `config_vars` is now inherited automatically, delete the assignment; the reads at `self.config_vars[0]` keep working through inheritance.

The three remaining files, `odb.portdiodeplacement/001-success_both/verify.py:12`, `openroad.floorplan/002-success-obstructions/verify.py:15` and `openroad.rcx/003-success-disconnected-ios/handler.py:13`, are `step_impl_test` fixtures excluded from the default run. Convert them the same way and note that they are not covered by `uv run pytest -n auto`; they run only in the Nix-based CI jobs.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -n auto test/steps/ test/stages/ test/config/ -v`

Expected: PASS, including `test/steps/test_composite.py` and `test/steps/test_composition.py`.

- [ ] **Step 7: Update the custom-steps guide**

`docs/source/usage/writing_custom_steps.md:85` describes `config_vars` as a thing an author writes. Rewrite it to say `config_vars` is derived from the nested `class Config` and is what consumers read, and that an author declares `Config`.

- [ ] **Step 8: Lint and commit**

```bash
make lint
git add -A
git commit -m "feat!: reject flow_control_variable and author-written Step.config_vars"
```

---

## Task 12: Delete the 3.0.0-era `DesignFormat` deprecations

`.name` and `.by_id` have no callers. `.value` has one, which changes in the same commit; deleting the property without it breaks KLayout LVS at runtime.

**Files:**
- Modify: `librelane/state/design_format.py:71-78`, `:84-91`, `:102-109`, `:126`
- Modify: `librelane/steps/klayout/lvs.py:77`
- Test: `test/state/test_state.py`

- [ ] **Step 1: Fix the caller first**

In `librelane/steps/klayout/lvs.py:77`, change:

```python
            f"{self.config.DESIGN_NAME}.{DesignFormat.SPICE.value.extension}",
```

to:

```python
            f"{self.config.DESIGN_NAME}.{DesignFormat.SPICE.extension}",
```

- [ ] **Step 2: Write the failing test**

Append to `test/state/test_state.py`:

```python
def test_removed_design_format_accessors():
    """
    Three 3.0.0-era deprecations. The DesignFormat is returned directly, so
    .value was an identity; .name duplicated .id; .by_id duplicated the factory.
    """
    from librelane.state import DesignFormat

    assert not hasattr(DesignFormat.GDS, "value")
    assert not hasattr(DesignFormat.GDS, "name")
    assert not hasattr(DesignFormat, "by_id")
```

- [ ] **Step 3: Run and confirm failure**

Run: `uv run pytest test/state/test_state.py::test_removed_design_format_accessors -v`

Expected: FAIL on the first assertion.

- [ ] **Step 4: Delete the three members**

In `librelane/state/design_format.py`, delete the `value` property with its decorators at lines 71 through 78, the `name` property with its decorators at lines 84 through 91, and the `by_id` static method with its decorators at lines 102 through 109. Keep `folder`, `optional`, `register`, `__str__` and `__hash__`.

Then check whether `deprecated` is still imported for another use with `grep -n 'deprecated' librelane/state/design_format.py`, and delete the import if not.

- [ ] **Step 5: Fix the stale docstring**

`librelane/state/design_format.py:126` is the docstring of `DesignFormatFactory.register` and reads ``` :attr:`DesignFormat.id`, :attr:`DesignFormat.name` and ```. `register` at lines 129 through 133 uses only `df.id` and `df.alts`. Rewrite the sentence to name `id` and `alts`.

- [ ] **Step 6: Test, lint and commit**

Run: `uv run pytest -n auto test/state/ test/steps/ -v`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat!: delete the 3.0.0-era DesignFormat deprecations"
```

---

## Task 13: `SequentialFlow.explain`

The single API that answers the question the problem statement asks. Depends on Task 3 for `_resolve_step_id` and on Task 2 for union gating.

`explain` is defined on `SequentialFlow`, not on `Flow`. `gating_config_vars` and `_expand_gating_config_vars` are `SequentialFlow` attributes, and `frm`, `to` and `skip` are parameters of `SequentialFlow.run`, not of `Flow.run`. A `Flow` subclass writes its own `run` and there is nothing about it to predict. After Task 8 every flow in the tree is a `SequentialFlow`.

Resume is deliberately excluded. A resume verdict depends on content fingerprints of files that later steps in the same run will rewrite, so it cannot be predicted before the run without executing it. `explain` reports what the flow will attempt, not which attempts will be served from cache.

**Files:**
- Create: `librelane/flows/explanation.py`
- Create: `test/flows/test_explain.py`
- Modify: `librelane/flows/sequential.py`, `librelane/flows/staged.py`, `librelane/flows/__init__.py`

**Interfaces:**
- Produces:
  - `librelane.flows.StepDisposition(step_id: str, will_run: bool, reason: str, mechanism: str | None)`, frozen.
  - `librelane.flows.Explanation(steps: tuple[StepDisposition, ...], unselected_stages: tuple[str, ...])`, frozen.
  - `SequentialFlow.explain(self, *, frm=None, to=None, skip=None) -> Explanation`.
  - `StagedFlow.explain`, same signature, filling `unselected_stages`.
- Task 14 imports `Explanation` to format the CLI table.

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_explain.py`:

```python
import pytest

from librelane.flows import flow as flow_module, sequential as sequential_module
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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_every_step_of_an_unconstrained_flow_will_run(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain()

    assert [d.step_id for d in explanation.steps] == ["Test.MetricIncrementer"]
    assert all(d.will_run for d in explanation.steps)
    assert all(d.mechanism is None for d in explanation.steps)
    assert explanation.unselected_stages == ()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_gated_step_names_its_gate(MetricIncrementer):
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.ExplainGated"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated]

        config_vars = [
            Variable("TEST_GATE", bool, description="x", default=False)
        ]

        gating_config_vars = {"Test.ExplainGated": ["TEST_GATE"]}

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain()

    gated = explanation.steps[1]
    assert gated.step_id == "Test.ExplainGated"
    assert gated.will_run is False
    assert gated.mechanism == "gate"
    assert "TEST_GATE" in gated.reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_skip_and_window_attribute_correctly(MetricIncrementer):
    from librelane.flows import SequentialFlow

    class Second(MetricIncrementer):
        id = "Test.ExplainSecond"

    class Third(MetricIncrementer):
        id = "Test.ExplainThird"

    class Fourth(MetricIncrementer):
        id = "Test.ExplainFourth"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Second, Third, Fourth]

    explanation = Dummy(_MINIMAL_DESIGN, **_MOCK_PDK).explain(
        frm="Test.ExplainSecond",
        to="Test.ExplainThird",
        skip=["Test.ExplainSecond"],
    )

    by_id = {d.step_id: d for d in explanation.steps}
    assert by_id["Test.MetricIncrementer"].mechanism == "window"
    assert "--from" in by_id["Test.MetricIncrementer"].reason
    assert by_id["Test.ExplainSecond"].mechanism == "skip"
    assert by_id["Test.ExplainThird"].will_run is True
    assert by_id["Test.ExplainFourth"].mechanism == "window"
    assert "--to" in by_id["Test.ExplainFourth"].reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_deselected_provider_s_steps_are_absent_not_excluded(mock_config):
    """
    A step dropped by TOOLS is not in the resolved list at all, so it has no
    entry. Provider selection is therefore not among the mechanisms a step
    entry can carry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values.update({"RUN_KLAYOUT_XOR": False, "TOOLS": {"streamout": "klayout"}})
    flow = Classic(mock_config.copy(**values))

    explanation = flow.explain()
    ids = [d.step_id for d in explanation.steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_turning_off_run_cts_excludes_every_step_of_the_stage(mock_config):
    """
    A stage gate is lowered onto each step of the stage, so all three of the
    cts stage's steps report the same gate. This is the case a user actually
    hits, and the one describe_stages cannot answer.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values["RUN_CTS"] = False
    flow = Classic(mock_config.copy(**values))

    cts = [
        d
        for d in flow.explain().steps
        if d.mechanism == "gate" and "RUN_CTS" in d.reason
    ]
    assert [d.step_id for d in cts] == ["OpenROAD.CTS"]
    assert all(d.will_run is False for d in cts)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_an_unselected_stage_is_reported_separately():
    """
    Stage.post_route_opt has a None default provider, so it contributes no
    steps and cannot be a step entry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = Classic(_MINIMAL_DESIGN, **_MOCK_PDK)

    assert "post_route_opt" in flow.explain().unselected_stages
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/flows/test_explain.py -v`

Expected: every test FAILs with `AttributeError: 'Dummy' object has no attribute 'explain'`.

- [ ] **Step 3: Create the dataclass module**

Create `librelane/flows/explanation.py`:

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
"""What a prospective invocation of a flow would do, without running it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDisposition:
    """
    Why one step will or will not run, for one prospective invocation.

    :param step_id: The step's ID, as it appears in the resolved step list.
    :param will_run: Whether this invocation would execute the step.
    :param reason: A sentence naming the cause, suitable for printing.
    :param mechanism: ``None`` when :attr:`will_run` is true, and otherwise
        one of ``gate``, ``skip`` or ``window``.

        Those three are the only values a step entry can carry, because they
        are the only mechanisms that exclude a step which is present in the
        resolved list. A step dropped by a ``TOOLS`` selection is not in the
        list at all and so has no entry, which is why provider selection is
        not among them.
    """

    step_id: str
    will_run: bool
    reason: str
    mechanism: str | None


@dataclass(frozen=True)
class Explanation:
    """
    What a prospective invocation of this flow would do.

    :param steps: One entry per step in the resolved step list, in execution
        order.
    :param unselected_stages: Stages that contributed no steps, because
        ``TOOLS`` left them out or because their default provider is ``None``.
        These cannot be step entries, having no steps. Always empty for a flow
        that declares ``Steps`` directly and so has no stages.
    """

    steps: tuple[StepDisposition, ...]
    unselected_stages: tuple[str, ...]
```

- [ ] **Step 4: Implement `SequentialFlow.explain`**

Add to `librelane/flows/sequential.py`, immediately after `_resolve_step_id`, and add `from .explanation import Explanation, StepDisposition` to the imports:

```python
    def explain(
        self,
        *,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
    ) -> Explanation:
        """
        :param frm: As :meth:`run`.
        :param to: As :meth:`run`.
        :param skip: As :meth:`run`.
        :returns: One entry per step in this flow's resolved step list, in
            execution order, stating whether the step will run under this
            configuration and these flow-control arguments, and if not, which
            mechanism excluded it, together with the stages that contributed no
            steps at all.

        Resume is deliberately not reported. A resume verdict depends on
        content fingerprints of files that later steps in the same run will
        rewrite, so it cannot be known before the run. This says what the flow
        will attempt, not which attempts will be served from cache.
        """
        frm_resolved = self._resolve_step_id(frm)
        to_resolved = self._resolve_step_id(to)
        skipped_ids: list[str] = []
        for skipped_step in skip or []:
            skipped_ids += self._resolve_step_id(skipped_step, multiple_ok=True)

        gating = self._expand_gating_config_vars(
            self.gating_config_vars,
            [cls.id for cls in self.Steps],
        )

        dispositions: list[StepDisposition] = []
        executing = frm is None
        stopped = False
        for cls in self.Steps:
            if frm_resolved is not None and frm_resolved == cls.id:
                executing = True

            gated_by = [
                variable
                for variable in gating.get(cls.id, [])
                if not self.config[variable]
            ]
            if gated_by:
                disposition = StepDisposition(
                    cls.id,
                    False,
                    f"gated off by {', '.join(gated_by)}",
                    "gate",
                )
            elif cls.id in skipped_ids:
                disposition = StepDisposition(
                    cls.id, False, "named by --skip", "skip"
                )
            elif stopped:
                disposition = StepDisposition(
                    cls.id, False, f"after --to '{to_resolved}'", "window"
                )
            elif not executing:
                disposition = StepDisposition(
                    cls.id, False, f"before --from '{frm_resolved}'", "window"
                )
            else:
                disposition = StepDisposition(cls.id, True, "will run", None)
            dispositions.append(disposition)

            if to_resolved and to_resolved == cls.id:
                executing = False
                stopped = True

        return Explanation(tuple(dispositions), ())
```

- [ ] **Step 5: Override it on `StagedFlow`**

Add to `librelane/flows/staged.py`, next to `describe_stages`, with `from dataclasses import replace` and `from .explanation import Explanation` added to the imports:

```python
    def explain(
        self,
        *,
        frm: str | None = None,
        to: str | None = None,
        skip: Iterable[str] | None = None,
    ) -> Explanation:
        """
        As :meth:`librelane.flows.SequentialFlow.explain`, additionally
        reporting the stages that contributed no steps. Those are announced
        only at debug level during construction, so nothing else surfaces them.
        """
        return replace(
            super().explain(frm=frm, to=to, skip=skip),
            unselected_stages=tuple(self._resolution.unselected),
        )
```

Confirm `Iterable` is imported in `staged.py`; add `from collections.abc import Iterable` if not.

- [ ] **Step 6: Re-export the dataclasses**

In `librelane/flows/__init__.py`, add to the imports:

```python
from .explanation import Explanation, StepDisposition
```

Place it after the `from .flow import ...` line and before `from .sequential import SequentialFlow`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest test/flows/test_explain.py -v`

Expected: PASS.

- [ ] **Step 8: Run the whole suite, lint and commit**

Run: `uv run pytest -n auto`

Expected: PASS.

```bash
make lint
git add -A
git commit -m "feat: add SequentialFlow.explain"
```

---

## Task 14: Surface `explain` as `--explain`

Prints the table and exits without running.

**Files:**
- Modify: `librelane/cli/options.py`, `librelane/cli/run.py`
- Test: `test/cli/test_runtime.py`, `test/flows/test_explain.py`

**Interfaces:**
- Consumes: `Explanation` and `StepDisposition` from Task 13.
- Adds `FlowRequest.explain: bool`.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_explain.py`:

```python
def test_format_explanation_renders_every_row():
    from librelane.cli.run import format_explanation
    from librelane.flows import Explanation, StepDisposition

    rendered = format_explanation(
        Explanation(
            steps=(
                StepDisposition("Test.Alpha", True, "will run", None),
                StepDisposition(
                    "Test.Beta", False, "gated off by RUN_BETA", "gate"
                ),
            ),
            unselected_stages=("post_route_opt",),
        )
    )

    assert "Test.Alpha" in rendered
    assert "Test.Beta" in rendered
    assert "RUN_BETA" in rendered
    assert "gate" in rendered
    assert "post_route_opt" in rendered
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest test/flows/test_explain.py::test_format_explanation_renders_every_row -v`

Expected: FAIL with `ImportError: cannot import name 'format_explanation'`.

- [ ] **Step 3: Add the option**

In `librelane/cli/options.py`, next to `ToOption`:

```python
ExplainOption = Annotated[
    bool,
    typer.Option(
        "--explain",
        help="Print which steps this configuration would run, and why each of the rest would not, then exit without running. Requires a sequential flow.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
```

- [ ] **Step 4: Add the formatter**

In `librelane/cli/run.py`, next to `start_flow`:

```python
def format_explanation(explanation: Explanation) -> str:
    """
    Renders an :class:`librelane.flows.Explanation` as a fixed-width table.

    :param explanation: What the flow reported.
    :returns: The table, without a trailing newline.
    """
    width = max((len(d.step_id) for d in explanation.steps), default=0)
    lines = [f"{'STEP'.ljust(width)}  RUN  MECHANISM  REASON"]
    for disposition in explanation.steps:
        mark = "yes" if disposition.will_run else "no "
        mechanism = (disposition.mechanism or "").ljust(9)
        lines.append(
            f"{disposition.step_id.ljust(width)}  {mark}  {mechanism}  "
            f"{disposition.reason}"
        )
    if explanation.unselected_stages:
        lines.append("")
        lines.append(
            "Stages contributing no steps: "
            + ", ".join(explanation.unselected_stages)
        )
    return "\n".join(lines)
```

Add `from ..flows import Explanation, SequentialFlow` to the imports of `librelane/cli/run.py`, or extend the existing `flows` import.

- [ ] **Step 5: Wire it into `start_flow`**

In `librelane/cli/run.py`, inside `start_flow`, immediately after the `flow = target_flow(...)` construction succeeds and before the `try:` that calls `flow.start(...)`:

```python
    if request.explain:
        if not isinstance(flow, SequentialFlow):
            logger.error(
                f"--explain requires a sequential flow; '{type(flow).__name__}' "
                f"writes its own run() and has no step list to predict."
            )
            raise typer.Exit(1)
        typer.echo(
            format_explanation(
                flow.explain(
                    frm=request.frm,
                    to=request.to,
                    skip=list(request.skip),
                )
            )
        )
        raise typer.Exit(0)
```

- [ ] **Step 6: Add the field and the parameter**

Add `explain: bool` to the `FlowRequest` dataclass in `librelane/cli/run.py`, next to `frm` and `to`. Add `explain: ExplainOption = False,` to the `run` function's parameters, and `explain=explain,` to the `FlowRequest(...)` construction.

Then add `explain=False,` to the `replace(request, ...)` call in `run_included_example` at `librelane/cli/run.py:270-283`, alongside the other steering options the smoke test drops.

- [ ] **Step 7: Add the CLI wiring test**

Note that `--explain` short-circuits inside `start_flow`, which this test replaces, so it asserts the flag reaches the request rather than the printed output. The table itself is covered by Step 1's `format_explanation` test.

Append to `test/cli/test_runtime.py`, mirroring the request-capturing test at `test/cli/test_runtime.py:165-192`:

```python
def test_explain_reaches_the_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import librelane.cli.run as run_module

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf8")
    captured = {}

    monkeypatch.setattr(
        run_module, "start_flow", lambda request: captured.update(request=request)
    )
    result = runner.invoke(
        cli,
        [
            "--manual-pdk",
            "--pdk-root",
            str(tmp_path),
            "--explain",
            str(config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["request"].explain is True
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest -n auto test/cli/ test/flows/test_explain.py -v`

Expected: PASS.

- [ ] **Step 9: Try it by hand**

Run: `uv run librelane --explain librelane/examples/spm/config.yaml`

Expected: a table of every `Classic` step with `yes` in the RUN column, no `--explain`-related error, and exit code 0 without a run directory being created.

- [ ] **Step 10: Lint and commit**

```bash
make lint
git add -A
git commit -m "feat: add --explain"
```

---

## Task 15: Changelog and the final documentation sweep

Every deletion gets a Changelog entry naming its migration, and the last two documentation corrections land.

**Files:**
- Modify: `Changelog.md`
- Modify: `librelane/steps/step/composite.py:48-51` if Task 10 Step 10 did not already cover it

- [ ] **Step 1: Write the Changelog entry**

Add a new section at the top of `Changelog.md`, matching the format of the existing entries. Read the most recent released section first for the exact heading style and bullet conventions. It must name, for each removal, what replaces it:

- `Substitutions`, `Substitute` and `meta.substituting_steps` are removed. Declare an explicit `Stages` list, as `VHDLClassic` and `Chip` do. The `hold_eco_demo` example and the ECO usage guide are removed with them; a flow that inserts `Odb.InsertECOBuffers` is now written as a flow class.
- `meta.flow` no longer accepts a list of step IDs. Name a registered flow.
- `SequentialFlow.make` is removed. Use `SequentialFlow.Make`.
- The `Optimizing` and `SynthesisExploration` demo flows are removed.
- `--only` is removed. Use `--from X --to X`.
- `Stage.config_vars` and `Registration.requires_pdk_vars` are removed.
- A `Registration` names exactly one stage. `stages=["x"]` becomes `stage="x"`.
- A `Step` defining `flow_control_variable` now raises `TypeError`. Gate it from the flow's `gating_config_vars`.
- A `Step` assigning `config_vars` now raises `TypeError`. Declare a nested `class Config`.
- `Flow.init_with_config`, `Flow.set_max_stage_count`, `Flow.start_stage`, `Flow.end_stage` and `Toolbox.aggregate_metrics` are removed. Use the constructor, `flow.progress_bar.*`, and `aggregate_metrics` from `librelane.common`.
- `DesignFormat.value`, `DesignFormat.name` and `DesignFormat.by_id` are removed. Use the `DesignFormat` itself, `.id`, and `DesignFormat.factory.get`.
- `SequentialFlow.explain` and `--explain` are added.
- `--from` now works on a flow with a gating variable turned off, `--reproducible` on a gated step raises instead of silently doing nothing, and overlapping gating keys union rather than overwrite.

- [ ] **Step 2: Verify every deleted name is gone from shipped code and docs**

Run:

```bash
grep -rn 'Substitut\|substituting_steps\|requires_pdk_vars\|flow_control_variable\|spanning\|--only\|Optimizing\|SynthesisExploration\|init_with_config' librelane/ test/ docs/source/
```

Expected: no output. Every historical mention lives in `Changelog.md`, which is excluded, and in `docs/superpowers/`, which is planning material.

- [ ] **Step 3: Build the documentation**

Run: `make docs`

Expected: no errors. Check the output for warnings naming any of the deleted symbols, which would be a stale cross-reference.

- [ ] **Step 4: Run the full suite one last time**

Run: `uv run pytest -n auto`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint
git add -A
git commit -m "docs: changelog for the flow mechanism unification"
```

---

## Relationship to per-step resume

Per-step resume has landed on this branch. Its spec declares resume for non-sequential flows a non-goal, justified entirely by `Optimizing` and `SynthesisExploration` having no fixed step list. Task 8 deletes both, after which every flow in the tree is sequential and that non-goal has no remaining subject. It becomes true vacuously rather than false, so nothing it built is invalidated.

Its two planning documents are annotated with that outcome already, at `docs/superpowers/specs/2026-07-29-per-step-resume-design.md` and `docs/superpowers/plans/2026-07-29-per-step-resume.md`. Nothing further is owed to them. The user-facing consequence, `docs/source/usage/resuming_runs.md`, is rewritten by Task 8 Step 7 with the exact replacement text given there, in the same commit as the deletion, so the page is never briefly false.

`Flow.dir_for_step`'s `position` parameter (`librelane/flows/flow.py:816-841`) is optional specifically so that a flow building steps in a data-dependent loop could omit it. After Task 8 no such flow remains. **Leave it optional.** The workflow engine reintroduces exactly that kind of flow, and removing the parameter now means adding it back in spec 2.
