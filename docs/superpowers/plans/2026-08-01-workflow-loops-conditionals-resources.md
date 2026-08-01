# Workflow Loops, Conditionals and Resources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement spec 3, `docs/superpowers/specs/2026-08-01-workflow-loops-conditionals-resources-design.md`: loops as well-formed cycles in `needs`, `metric::` runtime predicate terms in `if` and `until`, sweep mode with `select`, and named resource pools. The spec is the authority; where this plan and the spec disagree, the spec governs, and the disagreement is reported rather than silently resolved.

**Architecture:** The Net class is untouched. Each legal cycle (a simple ring with one `until` gate) collapses into one synthetic node, identified by the gate's job id, so the graph the net runs stays acyclic and every spec 2 invariant holds literally. A loop instance runs its passes sequentially inside one worker submission; a sweep fans its executions out as sibling futures from the main scheduling thread; resource pools are a lock-protected counter set consulted at submission and by blocking loop passes. Runtime `if` terms are evaluated on the scheduling thread against the joined input state, exactly where the configuration terms are read today.

**Tech Stack:** Python 3.11+, pydantic 2.13, `concurrent.futures` via `librelane.common.get_tpe()`, `threading.Condition`, pytest with pytest-mock, uv.

## Global Constraints

- The spec for this plan is `docs/superpowers/specs/2026-08-01-workflow-loops-conditionals-resources-design.md`. Read it before implementing; every semantic question this plan leaves open is answered there.
- No shipped document declares a loop, a sweep, a runtime term or a pool. Every existing document, run directory and resume entry must be byte-for-byte unaffected. The full suite stays green after every task.
- Never add a fallback. A missing metric, a non-numeric comparison, a malformed term or an unsatisfiable pool is an error naming what went wrong, never a silent default.
- Do not use `from __future__ import annotations`. Write types directly.
- Imports are absolute (`from librelane.flows.spec import FlowSpec`).
- Docstrings are NumPy style (`Parameters` / `Returns` / `Raises` with dashed underlines).
- Every new file carries the Apache 2.0 header used by `librelane/flows/net.py`, year 2026.
- Tests are pytest + pytest-mock, run with `uv run pytest`. The repo's default addopts already deselect `step_impl_test` and ignore `test/designs`.
- Lint gate for every commit: `uv run ruff check librelane test && uv run ruff format --check librelane test && uv run mypy .`. Do not use `make lint`.
- Error messages name the offending job (or pool, or term) and the remedy or the legal alternatives, in the house style visible throughout `librelane/flows/spec.py`.
- Do not modify `librelane/flows/net.py`. If a task appears to need to, stop and report NEEDS_CONTEXT.

## Interfaces that already exist (do not redefine)

Line numbers were opened in this checkout at commit `e503ac77`.

- `librelane.flows.spec.FlowSpec` / `JobSpec` / `VariableSpec` / `FlowSpecError` / `parse_condition` / `load_flow_spec` (`librelane/flows/spec.py`). `_JOB_KEYS` at spec.py:61, `_RESERVED_VALUE_KEYS` at spec.py:72, `_PRE_PASS_VALUE_KEY` at spec.py:80.
- `librelane.flows.spec_graph.topological_order` / `ancestors` / `descendants` (`librelane/flows/spec_graph.py`). `ancestors`/`descendants` are visited-set walks and already terminate on cycles; `topological_order` raises `graphlib.CycleError` on one.
- `librelane.flows.job.ResolvedJob` (job.py:36) and `resolve_jobs` (job.py:71). `ResolvedJob.conditions: tuple[str, ...]` is the parsed `if` conjunction today.
- `librelane.flows.net.Net` — one place per arc, `enabled()`, `consume(job)`, `fire(job, token)`, `sink_tokens()`, `is_complete()`, `stalled()`.
- `librelane.flows.join.join_states(tokens, source, job)` and `join_sink_states`.
- `librelane.flows.engine.Workflow`: the scheduling loop at engine.py:692-751, `_run_job` at :1554, `dir_for_job_step` at :1674, `_pass_through_reason` at :1525, `_enabled_jobs` at :1505, `_plan` at :1133, `_resolve_reproducible` at :1350, `_resolve_job_configs` at :440, `_check_contract` at :1707, `explain` at :852, `_final_state` at :1443. `_InFlight` at :305.
- `librelane.flows.selection_validation.validate_selection(spec, jobs, enabled, initial_views)` (selection_validation.py:211), which walks `topological_order(spec.edges())`.
- `librelane.flows.spec_validation.validate_against_registry(spec)` (spec_validation.py:38), `_reach(spec)` at :402 (which jobs can read each variable), `_check_job_values_are_covering` at :426.
- `librelane.config.Config.load(config_in, flow_config_vars, *, flow_values=None, job_values=None, config_override_strings=None, pdk=None, pdk_root=None, scl=None, pad=None, design_dir=None)` (config.py:687). `flow_values` and `job_values` become `ConfigSource` entries at config.py:799-812, layered *before* the design sources so the design wins.
- `librelane.state.State(views_mapping, metrics=...)`; `state.metrics` is the metrics mapping.
- Metrics values may be `int`, `float`, `Decimal` or strings; corner-qualified metric names contain `:` but never whitespace.

## File Structure

| File | Responsibility |
| --- | --- |
| `librelane/flows/predicates.py` (new) | The predicate term grammar: dataclasses, parser, evaluator. No spec.py import. |
| `librelane/flows/resources.py` (new) | `ResourcePools`, the lock-protected counter set. No engine import. |
| `librelane/flows/spec.py` | New `JobSpec`/`FlowSpec` fields, field-level combination checks, ring legality checks, `rings()`, `collapsed_edges()`. |
| `librelane/flows/spec_graph.py` | `nontrivial_sccs`, `ring_order`, `collapse`. Still domain-free. |
| `librelane/flows/spec_validation.py` | Schedule covering check, pool capacity variable check. |
| `librelane/flows/selection_validation.py` | Collapsed-graph traversal, ring pseudo-jobs, runtime-term consumer warning. |
| `librelane/flows/job.py` | `ResolvedJob` carries parsed terms and the new keys. |
| `librelane/flows/engine.py` | Runtime `if`, the loop driver, sweep execution, pool admission, refusals, explain rows. |
| `librelane/config/config.py` | `iteration_values` layer in `Config.load`. |
| `docs/source/usage/writing_custom_flows.md` | Author-facing sections for loops, sweeps, runtime conditions, pools. |
| `Changelog.md` | One bullet per user-visible feature. |
| `test/flows/test_predicates.py` (new), `test/flows/test_resources.py` (new), `test/flows/test_loops.py` (new), `test/flows/test_sweep.py` (new) | New-feature suites. |
| `test/flows/test_spec.py`, `test/flows/test_spec_graph.py`, `test/flows/test_engine.py`, `test/flows/test_selection_validation.py`, `test/flows/test_explain.py` | Extended. |

---

### Task 1: The predicate grammar and the new document keys

**Files:**
- Create: `librelane/flows/predicates.py`, `test/flows/test_predicates.py`
- Modify: `librelane/flows/spec.py`, `librelane/flows/job.py` (import site only), `test/flows/test_spec.py`

**Interfaces produced (later tasks consume these exactly):**

```python
# librelane/flows/predicates.py
class PredicateError(FlowError): ...

@dataclass(frozen=True)
class ConfigTerm:
    name: str

@dataclass(frozen=True)
class MetricTerm:
    metric: str
    op: str                      # one of _OPERATORS, textual
    literal: int | Decimal

Term = Union[ConfigTerm, MetricTerm]

def parse_predicate(text: str) -> tuple[Term, ...]: ...
def evaluate_metric_term(term: MetricTerm, metrics: Mapping[str, Any], owner: str) -> bool: ...
def config_terms(terms: Iterable[Term]) -> tuple[str, ...]: ...
def metric_terms(terms: Iterable[Term]) -> tuple[MetricTerm, ...]: ...
```

```python
# JobSpec additions (spec.py); all aliased keys join _JOB_KEYS, all field
# names join _JOB_FIELD_NAMES
until: str | None = None
iterations: list[dict[str, Any]] | None = None
max_passes: int | None = Field(default=None, alias="max")
mode: Literal["escalate", "sweep"] = "escalate"
select: str | None = None
resources: list[str] = []

# FlowSpec addition
resources: dict[str, int | str] = {}
```

**Requirements:**

1. Grammar, exactly as the spec's "Predicates" section defines it. `parse_predicate` splits the conjunction on the literal `and` exactly as `parse_condition` does today (whitespace tokens, odd positions are joiners). Each conjunct is then one term: a bare identifier matching the existing `_IDENTIFIER` regex becomes `ConfigTerm`; a conjunct whose first whitespace-token starts with `metric::` must consist of exactly three whitespace-tokens (prefix+name, operator, literal), the prefix stripped once from the front. Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`. Literals: optionally signed integer or decimal, parsed to `int` or `Decimal`; anything else is `PredicateError` quoting the term. A `metric::` with an empty name, a term of two or four tokens, an unknown operator — each is a distinct `PredicateError` quoting the predicate and stating the legal shape. Note the ambiguity trap: the conjunction splitter must treat a three-token metric term as ONE conjunct; split on ` and ` occurrences at the token level first (a token equal to `and`), and only the *segments between* `and` tokens are terms. A segment of one token is a config term; of three tokens starting `metric::`, a metric term; anything else, an error.
2. `evaluate_metric_term`: missing metric raises `FlowError` naming `owner`, the metric and `sorted(metrics)` (spec: absence is not false). Observed values compared numerically: accept `int`, `float`, `Decimal`; convert through `Decimal(str(value))` so `float` and `Decimal` compare exactly; a value that is not one of those three types (or a `str` that is one of them — do NOT parse strings, a string metric is not a number) raises `FlowError` naming the metric, the value and its type, for `==`/`!=` as much as the orderings.
3. `spec.py`'s `parse_condition` is replaced by `parse_predicate`; `parse_condition` is deleted, its two callers (spec.py `_check_conditions_are_declared_booleans`, job.py `_resolve`) updated. `PredicateError` raised during document validation is wrapped into `FlowSpecError` with the job name, exactly as the current `except FlowSpecError` re-raise does.
4. `_check_conditions_are_declared_booleans` checks only the `ConfigTerm`s of an `if` (name declared, type bool — unchanged wording); `MetricTerm`s pass through it unchecked (their names are not a closed set — the spec says so).
5. New field-level checks on `JobSpec`/`FlowSpec` (model validators; these need no graph and no registry):
   - `until` parses; every term is a `MetricTerm`, else the error states that a configuration variable is constant across passes.
   - `until` requires exactly one of `iterations`/`max` (neither and both are distinct errors).
   - `iterations` requires `until` or `mode: sweep`; `max_passes` requires `until` and is refused with `mode: sweep`; `select` requires `mode: sweep`; `mode: sweep` requires both `iterations` and `select` and refuses `until`.
   - `iterations` non-empty; every entry rejects `_RESERVED_VALUE_KEYS` and `_PRE_PASS_VALUE_KEY` with the existing messages' shape, naming the job and the entry index (1-based, as passes are).
   - `max_passes` ≥ 1.
   - `select` is exactly `<metric-name> min` or `<metric-name> max` (two whitespace tokens; the name bare, no `metric::` prefix — refuse the prefix with a message saying the field admits only metrics).
   - `JobSpec.resources`: duplicates refused (mirror the duplicate-`needs` message).
   - `FlowSpec.resources`: an `int` capacity below 1 refused naming the pool; a `str` capacity is checked in Task 2 (it needs the declared variables). A job's `resources` naming a pool absent from `FlowSpec.resources` refused, listing the declared pools (FlowSpec-level validator).
6. `_reject_unknown_keys` keeps rejecting anything outside the extended `_JOB_KEYS`, and its message still prints the whole legal list.

- [ ] **Step 1:** Write `test/flows/test_predicates.py`: parse each operator; signed and decimal literals; a config term, a metric term, a mixed conjunction `A and metric::x >= 0 and B`; a corner-qualified name `metric::timing__setup__ws:corner:nom parses` — wait, that name contains no whitespace so it parses; malformed shapes (two tokens, four tokens, unknown op `=>`, literal `abc`, empty name `metric:: > 1`, `and` at an edge); `evaluate_metric_term` for each op true and false; missing metric names owner and present metrics; string observed value refused for `==`; `float` vs `Decimal` literal compares exactly. ~20 tests.
- [ ] **Step 2:** Run them; they fail on import.
- [ ] **Step 3:** Implement `predicates.py`.
- [ ] **Step 4:** Extend `test/flows/test_spec.py` with one test per field-level refusal in requirement 5 (each asserting the job name and the remedy appear), plus: existing `if` conjunctions still validate; a job using every new key legally validates; the unknown-key message lists the new keys. ~16 tests.
- [ ] **Step 5:** Implement the spec.py changes; update job.py's import.
- [ ] **Step 6:** `uv run pytest test/flows/ -q`, then the full suite, then the lint gate.
- [ ] **Step 7:** Commit: `feat: predicate term grammar and the loop/sweep/resource document keys`.

---

### Task 2: Ring analysis and the graph-level validations

**Files:**
- Modify: `librelane/flows/spec_graph.py`, `librelane/flows/spec.py`, `librelane/flows/spec_validation.py`
- Test: `test/flows/test_spec_graph.py`, `test/flows/test_spec.py`, `test/flows/test_spec_validation.py` (or wherever `validate_against_registry` is tested — find it)

**Interfaces produced:**

```python
# spec_graph.py — still domain-free
def nontrivial_sccs(edges: dict[str, list[str]]) -> list[list[str]]:
    """SCCs of size >= 2, plus size-1 SCCs whose node lists itself in its
    own edges (a self-loop). Deterministic order: sorted by smallest member."""

def ring_order(edges: dict[str, list[str]], scc: list[str]) -> list[str] | None:
    """The members in ring order (each node followed by the node that needs
    it) if every member has exactly one intra-scc predecessor and the
    intra-scc edges form a single cycle; None otherwise. A self-loop is a
    ring of one. Starting point: the sorted-first member, so the order is
    deterministic; callers rotate it."""

def collapse(edges: dict[str, list[str]], member_ring: dict[str, str]) -> dict[str, list[str]]:
    """The edge map with every member replaced by its ring id, self-edges
    dropped, duplicates deduplicated preserving first-seen order."""
```

```python
# FlowSpec methods
def rings(self) -> dict[str, tuple[str, ...]]:
    """Gate id -> members in ring order rotated to START at the gate's
    intra-ring successor and END at the gate (the pass execution order).
    Computed during validation and cached on the instance."""

def collapsed_edges(self) -> dict[str, list[str]]:
    """spec_graph.collapse over edges() with every ring member mapped to
    its gate's id. Acyclic by construction."""
```

**Requirements:**

1. `_check_acyclic` is replaced by `_check_cycles_are_loops`. For each nontrivial SCC: `ring_order` returning None is an error (the old cycle wording, extended to state what a legal loop is: a simple ring with exactly one `until` gate). A ring with zero or several `until` members: distinct errors naming the members. A non-gate member with a consumer outside the ring: error naming both jobs and both remedies (spec wording). `until` on a job in no ring: error saying `until` is a loop gate. `mode: sweep` on any ring member: error. `final` naming a non-gate ring member: error (extend `_check_final_names_a_job`). A self-loop (`needs: [self]` plus `until` on the same job) is a legal ring of one, gate = the job; add it to `_check_needs_are_declared`'s tests as legal (today a self-need passes that check and dies in `_check_acyclic`).
2. The `until` gate's terms were already checked to be metric terms in Task 1; here check what needed the graph: nothing more for `until` itself.
3. Ordering: run `_check_cycles_are_loops` where `_check_acyclic` ran, and make `topological_order` callers inside spec.py use `collapsed_edges()` (only `_check_acyclic` used it there).
4. `spec_validation.py`, needing the registry: the schedule covering check. Every variable named by any `iterations` entry of a gate must have reach (per `_reach(spec)` at spec_validation.py:402, which returns the jobs that can read each variable) a subset of that gate's ring members. A universal variable's reach is every job, so it is refused whenever the document has any job outside the ring; the message names the variable, the outside readers, and states the divergence rationale (the spec's "Iterations and max" section). The same check applies to a **sweep** job's `iterations`: reach must be a subset of `{job}` itself.
5. `spec_validation.py`: a `str` pool capacity must name a variable the flow's `config` declares with `type: int`; anything else (undeclared, or another type) is an error naming the pool, the name and the declared variables. (The value check, ≥ 1, is construction-time — Task 6.)
6. `Workflow.__init__` does not change in this task; the engine still refuses cyclic documents until Task 4 — so `_check_cycles_are_loops` accepting a ring means `topological_order(self.spec.edges())` calls in engine.py and selection_validation.py would now crash on a ring document. To keep the tree green mid-plan: in this task, have `validate_against_registry` (spec_validation.py:38) raise a clear `FlowSpecError` "loops are not executable yet" for any document with a ring, removed in Task 4. Write it as one `if spec.rings(): raise` at the top so Task 4 deletes one statement.

- [ ] **Step 1:** Write the spec_graph tests: a 2-ring and a 3-ring found and ordered; a self-loop; a figure-eight SCC (two cycles sharing a node) returns None from `ring_order`; an SCC with a chord returns None; `collapse` on a ring with one external producer and one external consumer yields the collapsed acyclic map, deduplicated. ~8 tests.
- [ ] **Step 2:** Implement `spec_graph.py` additions (Tarjan or Kosaraju; no external dependency).
- [ ] **Step 3:** Write the spec.py tests: legal 3-ring document validates and `rings()` returns the rotated order; each error in requirement 1 with its message asserted; `collapsed_edges()` shape. The spec_validation tests: schedule variable read outside the ring refused; universal variable in a schedule refused; str capacity naming an undeclared or non-int variable refused; the loops-not-executable-yet guard fires. ~14 tests.
- [ ] **Step 4:** Implement; run `test/flows/`, full suite, lint gate.
- [ ] **Step 5:** Commit: `feat: rings are legal cycles; graph-level loop validation`.

---

### Task 3: Runtime conditions in the engine

**Files:**
- Modify: `librelane/flows/job.py`, `librelane/flows/engine.py`, `librelane/flows/explanation.py` (only if a mechanism literal needs adding), `librelane/flows/selection_validation.py`
- Test: `test/flows/test_engine.py`, `test/flows/test_explain.py`, `test/flows/test_selection_validation.py`

**Interfaces produced:**

- `ResolvedJob.conditions: tuple[Term, ...]` (was `tuple[str, ...]`); new passthrough fields `until_terms: tuple[MetricTerm, ...]`, `iterations: tuple[Mapping[str, Any], ...]`, `max_passes: int | None`, `mode: str`, `select: tuple[str, str] | None` (metric, direction), `resources: tuple[str, ...]` — all copied off the `JobSpec` in `_resolve`, parsed once (`parse_predicate` for `until`, the two-token split for `select`).
- `Workflow._runtime_pass_through_reason(job: ResolvedJob, state_in: State) -> str | None` — evaluates the job's `MetricTerm`s against `state_in.metrics`; a false term's reason is `"metric::<name> <op> <literal> is false: observed <value>"`; raises the `evaluate_metric_term` error on a missing/non-numeric metric.

**Requirements:**

1. `_pass_through_reason` (engine.py:1525) evaluates only `ConfigTerm`s (via `predicates.config_terms`), keeping its wording; `_enabled_jobs` and `explain` therefore treat a job whose `if` has only runtime terms as enabled, which is the spec's optimistic rule.
2. The scheduling loop (engine.py:709-722): after `join_states` and after the existing `_pass_through_reason` check, call `_runtime_pass_through_reason(job, state_in)`; a non-None reason fires the same pass-through path (log, `net.fire(name, state_in)`, `outputs[name] = state_in`, `fired_pass_through = True`). The evaluation error propagates into the existing `except Exception` collector, which already fails the job by name.
3. `explain`: a job with runtime terms that the config terms did not already stop gets `will run` replaced by a disposition with mechanism `condition (runtime)` and reason naming the terms and stating the verdict is decided at run time against the input state. `--skip` and config-false still win (they are decided now; the runtime term is not).
4. `selection_validation.py`: (a) every `topological_order(spec.edges())` / `ancestors(spec.edges(), ...)` call switches to the **collapsed** edges (`spec.collapsed_edges()`), so ring documents stop crashing it — with rings still refused by the Task 2 guard this is unobservable until Task 4, but it belongs with this file's changes; keep `jobs` keyed per member and, for this task, treat a collapsed node id (which is a gate id, hence present in `jobs`) exactly as before — Task 4 introduces the ring pseudo-job view. (b) New check, warning not error: for each job J with a producer P in `needs` where P's `if` has metric terms not all syntactically present (dataclass equality) in J's `if` terms, `logger.warning` naming P, J and the unrepeated terms, with the pass-through rationale. Mirror the check on config terms if one exists; if none exists for config terms, add only the runtime half (the spec text covers only the extension).
5. `test_explain.py` and `test_engine.py` currently pin dispositions; update only what requirement 3 changes.

- [ ] **Step 1:** Write the tests: a fake-step document where `if: "metric::x == 0"` runs when the initial state carries `x: 0` and passes through with the observed value in the log/reason when `x: 3`; missing metric fails the job naming it; mixed `RUN_A and metric::x == 0` needs both; explain shows `condition (runtime)`; the consumer warning fires for an unrepeated term and stays silent for a repeated one. ~9 tests.
- [ ] **Step 2:** Implement job.py, engine.py, selection_validation.py changes.
- [ ] **Step 3:** `uv run pytest test/flows/ -q`, full suite, lint gate.
- [ ] **Step 4:** Commit: `feat: metric:: runtime conditions gate jobs against their input state`.

---

### Task 4: The loop driver

**Files:**
- Modify: `librelane/flows/engine.py`, `librelane/config/config.py`, `librelane/flows/selection_validation.py`, `librelane/flows/spec_validation.py` (delete the Task 2 guard)
- Test: `test/flows/test_loops.py` (new), `test/flows/test_engine.py`, `test/flows/test_selection_validation.py`

**Interfaces produced:**

- `Config.load(..., iteration_values: tuple[str, int, Mapping[str, Any]] | None = None)`: `(gate id, pass k, entry)`, appended as a `ConfigSource(dict(entry), f"<flow document: {gate_id}, iteration {k}>", "mapping")` **after** the design sources and before `config_override_strings` are applied — the spec's deliberate break of design-wins, documented in the parameter docstring with the spec's rationale.
- `Workflow._execute_steps(job, state_in, submitted, forced, reproducible_at, *, pass_index: int | None, config: _ResolvedConfig) -> State`: the body of today's `_run_job` with the directory and the step-instance id parameterized. `_run_job` becomes a thin wrapper passing `pass_index=None` and the job's own config.
- `dir_for_job_step(job, index, step, pass_index: int | None = None)`: inserts `/{pass_index}/` between the job id and the step ordinal when not None. Step instance id gains the pass: `f"{cls.id} ({job.id}/{pass_index})"` when not None.
- `Workflow._run_loop(gate: str, members: tuple[str, ...], tokens: dict[str, dict[str, State]], submitted: _InFlight, forced: bool) -> State` — the driver; `tokens` is keyed member -> that member's external tokens.

**Requirements:**

1. Delete the Task 2 "loops are not executable yet" guard.
2. Construction: `self.rings = spec.rings()`; `self.member_of = {member: gate for gate, members in ... for member in members}`. `_resolve_job_configs` additionally resolves, for every gate with a non-empty `iterations`, one config per `(member, k)`: `Config.load` with the flow values, that member's `job_values` (when it has any) and `iteration_values=(gate, k, entry)`. Stored as `self.iteration_configs: dict[tuple[str, int], _ResolvedConfig]`. The existing already-resolved-Config refusal extends to documents with `iterations` (same message shape, naming the gate). Sweeps resolve identically in Task 5 — build the mechanism keyed by the job that declares `iterations`, not by ring-ness.
3. Net and plan run on the collapsed graph. `edges = self.spec.collapsed_edges()` in `run()` and `explain()`. `_plan` still validates *member* names: `--target`/`--invalidate` naming any member maps it to its gate id before the subgraph math, and the returned `selected` set is then re-expanded to contain every member of each selected ring (explain iterates members; `progress_bar.set_max_stage_count` counts collapsed nodes). `--skip` naming any ring member is a `FlowException` naming the ring and the `if`-on-the-gate remedy (spec wording). `_resolve_reproducible` refuses a step whose job is a ring member (and, Task 5, a sweep job), stating v1 and the pass-directory remedy.
4. Scheduling: for a collapsed ring node (id = gate id), `_tokens_for` is replaced by a member-attributed collection: consume the node's input arcs; each arc's producer feeds the member(s) whose `needs` name it (from the *original* `spec.edges()`); build `tokens[member][producer] = state`. Submission goes to `_run_loop` instead of `_run_job`. An `if` on the **gate** with a false config term or false runtime term fires the whole node as pass-through, evaluated against the join of ALL external tokens (this is the one place a ring node joins across members: use `join_states` with the gate's `source` and the node id).
5. The driver, per the spec's "loop driver" section, all inside the worker:
   - `bound = len(gate.iterations) or gate.max_passes`.
   - Circulating state starts as the join of the ring-entry member's external tokens (the ring-entry member is `members[0]`, the gate's intra-ring successor). For k in 1..bound: run members in order; each member's input is `join_states({**({'<loop>': circulating} if k > 1 or member != members[0] else {})..., **external tokens if k == 1})` — precisely: pass 1, member's input = join of circulating state (under key `<loop>`) with that member's external tokens, member's own `source` resolving conflicts; pass ≥ 2, input = circulating state alone. For `members[0]` on pass 1 the circulating state IS its external join (no double-join).
   - Member config: `self.iteration_configs.get((member, k))` when the gate schedules, else `self.job_configs.get(member, self.config)`.
   - Member `if`: config terms constant (pass-through every pass); metric terms per pass against the member's input state. A passed-through member contributes its input unchanged as the circulating state, exactly like a top-level pass-through.
   - Members run via `_execute_steps(..., pass_index=k, config=...)`, sharing `submitted` so steps/reused/executed/deferred aggregate on the one `_InFlight`.
   - After the gate's steps on pass k: every `until` term evaluated via `evaluate_metric_term` against the gate's output metrics. All true: return the gate's output. Any false and k < bound: circulate. Any false and k == bound: append to `submitted.deferred` a message naming the gate, the failing term(s) with observed values, and the bound (`"Job 'sta': the loop exhausted its 3 passes without satisfying metric::timing__setup__ws >= 0 (last observed -0.12)"`), and return the last state. The existing deferred plumbing then withholds the contract check and fails the flow at the end — assert both in tests, and that downstream jobs ran first.
6. `validate_selection` sees rings as pseudo-jobs: build, in engine.py before calling it, a jobs-view where each ring is one entry keyed by the gate id with `requires` = the union over members of views required but not provided by any member, `provides`/`metrics` = the gate's, `needs` = the collapsed node's needs, `conditions` = the gate's, `source` = the entry member's; pass the collapsed spec view. Simplest implementation: give selection_validation an optional `rings` parameter and do the folding there, where the graph already lives — implementer's choice, but ONE of the two owns it and says so in its docstring. `_enabled_jobs` counts a ring enabled iff the gate's config terms hold.
7. `explain`: one row per member, topological over collapsed graph then ring order within; mechanism `loop` with reason `loop gated by '<gate>', at most <bound> passes` on every member (the gate's row says `gate of the loop, at most <bound> passes`); a config-false gate `if` reports `condition` as today.
8. Resume across passes needs no code, but needs the test: rerun with nothing changed reuses every pass (the driver's `_execute_steps` path already consults `reusable_state`).

- [ ] **Step 1:** Write `test/flows/test_loops.py` with the fake-step machinery `test_engine.py` uses: a 2-member ring (body increments metric `x`, gate measures) converging on pass 2 — assert pass count, final state, directory layout `runs/<tag>/<member>/<k>/…`, step ids carry `/k`; exhaustion defers, downstream ran, flow failed at end; iteration values visible in each pass's config and provenance (`<flow document: gate, iteration 2>`); external token joined on pass 1 only; a self-loop ring of one; a member config-`if` passes through every pass; a member runtime-`if` flips per pass; `--target` on a member selects the ring; `--skip` and `--reproducible` refusals; unchanged rerun reuses every pass; gate `if` false fires the whole ring as one pass-through. ~15 tests.
- [ ] **Step 2:** Write the `Config.load` test in `test/config/`: `iteration_values` beats a design-source value and loses to `config_override_strings`; provenance string exact. 2 tests.
- [ ] **Step 3:** Implement `Config.load`, then the engine changes, then the selection_validation folding; delete the Task 2 guard and its test.
- [ ] **Step 4:** `uv run pytest test/flows/ test/config/ -q`, full suite, lint gate.
- [ ] **Step 5:** Commit: `feat: loops — rings run as sequential passes with an until gate`.

---

### Task 5: Sweep mode

**Files:**
- Modify: `librelane/flows/engine.py`
- Test: `test/flows/test_sweep.py` (new), `test/flows/test_explain.py`

**Requirements:**

1. A `mode: sweep` job's iteration configs come from the Task 4 mechanism (keyed by the declaring job). The already-resolved-Config refusal covers it identically.
2. Scheduling, on the main thread (never nest submissions inside a worker — a worker waiting on child futures deadlocks a saturated pool): when a sweep job is enabled, consume and join its tokens once, then submit N futures, one per `iterations` entry, each `_execute_steps(..., pass_index=k, config=iteration_configs[(job, k)])` with its **own** `_InFlight` record (named `f"{job} (pass {k})"`). Track them in a `_SweepProgress` (job id, expected count, per-pass results/records/errors) keyed so the `wait()` loop routes resolved futures to it. Only when all N have resolved does the sweep settle:
   - Any pass raised: the job fails once, naming the failing pass(es); other results are discarded (already-finished work, nothing to cancel).
   - Contract check per pass output (skipped for a pass with deferrals, the existing rule).
   - Any pass missing the `select` metric: failure naming job, pass and metric.
   - Winner per the spec: `min`/`max` by the metric compared as `evaluate_metric_term` compares (Decimal-through-str), ties to the lowest pass index. `net.fire(job, winner_state)`; `outputs[job] = winner_state`.
   - The winner's `_InFlight` merges into the run's totals (steps_run, deferred, counts); losing passes' steps merge into `steps_run` and counts, but their `deferred` entries become `logger.warning(f"Sweep pass {k} of '{job}' (discarded) deferred: {msg}")` and are NOT added to `deferred`.
3. The progress bar counts the sweep job once (`start_stage` at submission, `end_stage` at settlement).
4. `--skip` fires the sweep as one ordinary pass-through. `--reproducible` refuses it (extend the Task 4 refusal). `--target`/`--invalidate` treat it as the single job it is.
5. `explain`: reason `sweep of <N> points, keeps <metric> <min|max>`, mechanism None (it runs).
6. Pass directories and step ids exactly as loops (`pass_index=k`).

- [ ] **Step 1:** Write `test/flows/test_sweep.py`: winner by min and by max (fake steps write metric = f(entry value)); tie goes to pass 1; missing select metric fails naming the pass; a losing pass's deferral warns and does not fail, the winner's does fail; every pass contract-checked (a fake provider that drops a view on one pass fails); pass directories on disk; concurrent execution observable (all N ran); `--skip` pass-through; explain row. ~10 tests.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** `uv run pytest test/flows/ -q`, full suite, lint gate.
- [ ] **Step 4:** Commit: `feat: sweep mode — run a job at N settings, keep the best by a metric`.

---

### Task 6: Resource pools, documentation and changelog

**Files:**
- Create: `librelane/flows/resources.py`, `test/flows/test_resources.py`
- Modify: `librelane/flows/engine.py`, `docs/source/usage/writing_custom_flows.md`, `Changelog.md`
- Test: `test/flows/test_resources.py`, `test/flows/test_engine.py`

**Interfaces produced:**

```python
# librelane/flows/resources.py
class ResourcePools:
    def __init__(self, capacities: Mapping[str, int]) -> None: ...
    def try_acquire(self, names: Sequence[str]) -> bool:
        """All-or-nothing, non-blocking. True and all taken, or False and none."""
    def acquire(self, names: Sequence[str]) -> None:
        """All-or-nothing, blocking on an internal Condition until it can."""
    def release(self, names: Sequence[str]) -> None: ...
```

One `threading.Condition`; `release` notifies all. `try_acquire`/`acquire` check every name has a free slot under the lock and decrement together, or touch nothing.

**Requirements:**

1. Construction: `Workflow.__init__` after `super().__init__` resolves capacities: literal ints as-is; a `str` capacity reads `self.config[name]` (declared `int` by the Task 2 check); a resolved value below 1 is a `FlowException` naming the pool, the variable and the value. `self.pools = ResourcePools(resolved)`; absent `resources`, an empty pools object, and every acquisition path skips on an empty names tuple without touching the lock.
2. Ordinary jobs, on the scheduling thread: pool admission happens AFTER the pass-through decisions (a pass-through acquires nothing) and therefore after tokens are consumed. A job whose `try_acquire` fails is **parked**: its name, joined state and readiness are held on a `parked` list; every scheduler wake (after `wait()` returns, and after a pass-through sweep) retries parked entries before reading `net.enabled()`. Parked jobs hold tokens already consumed but no slots, so nothing deadlocks; the run cannot stall parked, because slots are only ever held by running work whose completion wakes the loop. Release in the `finally` of future settlement.
3. Loop members: `_execute_steps` calls inside `_run_loop` are wrapped by blocking `pools.acquire(member_resources)` / `release` per member per pass, where `member_resources` is that member's own `resources` tuple. (Blocking on a worker is safe: waiters hold no slots, and holders are executions on other workers whose completion releases.)
4. Sweep passes: each of the N futures is admitted from the main thread with the same `try_acquire`-or-park rule, so a two-seat pool runs a five-point sweep two at a time — assert exactly that.
5. Docs: `writing_custom_flows.md` gains four sections — Loops, Sweeps, Runtime conditions, Resource pools — each with a YAML example lifted from the spec, written against the shipped grammar, markdown only. Changelog: one bullet per feature under the unreleased heading, following the file's existing voice.
6. `--explain` needs no pools table (the spec asks none); the job table is unchanged.

- [ ] **Step 1:** Write `test/flows/test_resources.py`: try_acquire all-or-nothing across two pools; acquire blocks until release (thread + event); release notifies; empty names never blocks. ~5 tests. And in `test_engine.py`/`test_loops.py`: a one-seat pool serializes two enabled fake jobs (observe via a shared list appended at step start under a lock — max concurrent == 1); capacity from a variable; below-1 construction error names pool and value; slots released on a failing job (a second job then runs); a five-point sweep on a two-seat pool never exceeds two concurrent. ~6 tests.
- [ ] **Step 2:** Implement `resources.py`, then the engine admission points.
- [ ] **Step 3:** Write the docs sections and the Changelog bullets.
- [ ] **Step 4:** `uv run pytest test/flows/ -q`, full suite, lint gate. Build nothing doc-side beyond markdown validity (the docs build is not part of the test gate).
- [ ] **Step 5:** Commit: `feat: named resource pools bound concurrent tool use`.

---

## Self-review notes (already applied)

- Type consistency: `Term`, `MetricTerm`, `parse_predicate`, `evaluate_metric_term`, `pass_index`, `iteration_configs` keyed `(job, k)`, `_execute_steps` signature, `ResourcePools` methods are each defined once above and referenced identically across tasks.
- The Task 2 executable-guard exists so Tasks 2 and 3 land green while the engine cannot yet run rings; Task 4 deletes it. No other task depends on partial behaviour.
- Sweep fan-out is main-thread by design (deadlock note in Task 5); loop passes are worker-side by design (safety note in Task 6, requirement 3). These are deliberate and asymmetric.
