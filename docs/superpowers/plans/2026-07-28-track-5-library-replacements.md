# Track 5: Focused Library Replacements Implementation Plan

**Goal:** Replace three small home-grown utilities with standard-library or
already-adopted equivalents, then replace the `expr::` parser with Lark without
changing configuration behavior.

**Architecture:** Land the stdlib and Click changes together because they are
small and independent. Land the Lark parser separately, behind golden
characterization tests for valid results and invalid-expression failures.
Pydantic remains a separately gated project: this plan prepares its exhaustive
comparison harness but does not replace `Variable.__process`.

**Tech Stack:** Python standard library, Click, Lark, pytest, uv/uv2nix.

## Global Constraints

- Preserve Python 3.10 compatibility.
- Preserve public CLI flags and `KLAYOUT_ARGV` handling.
- Preserve `Decimal` evaluation, right-associative exponentiation, variable
  syntax, and exception categories/messages at the `process_string` boundary.
- Build with `uv build` directly; do not delete `dist/` first.
- Keep the `Step.factory` snapshot at 101 entries.
- Do not begin the Pydantic conversion unless the exhaustive golden comparison
  covers every declared repository `Variable`.

---

### Task 1: Characterize the small replacements

**Files:**
- Create: `test/common/test_replacements.py`
- Create: `test/scripts/test_klayout_open_design.py`
- Modify: `test/config/test_preprocessor.py`

- [ ] Cover the `RingBuffer` behavior actually consumed by subprocess logging:
  insertion order, truncation to the newest N entries, length, and iteration.
- [ ] Cover `zip_first` for a shorter, equal, and longer type iterator.
- [ ] Load `open_design.py` with a fake `pya` module and assert the existing
  short/long options, repeated `--input-lef`, positional input, and required
  option failures.
- [ ] Expand expression coverage for precedence, right-associative `**`,
  whitespace, negative literals, nested variable names, missing/non-numeric
  variables, unexpected tokens, missing operands, unmatched parentheses,
  adjacent expressions, and empty input.
- [ ] Run the focused tests and commit the characterization tests separately.

---

### Task 2: Replace `RingBuffer` and `zip_first` with stdlib

**Files:**
- Modify: `librelane/steps/step/subprocess_exec.py`
- Modify: `librelane/config/variable.py`
- Modify: `librelane/common/__init__.py`
- Modify: `librelane/common/misc.py`
- Delete: `librelane/common/ring_buffer.py`

- [ ] Replace the subprocess tail with `collections.deque[str](maxlen=10)` and
  `.append`.
- [ ] Replace `zip_first(raw, type_args, fillvalue=type_args[0])` with
  `zip(raw, chain(type_args, repeat(type_args[0])))`.
- [ ] Remove the obsolete implementations and public re-exports.
- [ ] Run focused tests, `make lint`, and the full test suite.
- [ ] Commit as one stdlib replacement.

---

### Task 3: Convert the KLayout launcher to Click

**Files:**
- Modify: `librelane/scripts/klayout/open_design.py`
- Modify: `test/scripts/test_klayout_open_design.py`

- [ ] Keep `open_design(...)` as the pya-facing implementation.
- [ ] Add a Click command with the same `-l/--input-lef`, `-T/--lyt`,
  `-P/--lyp`, `-M/--lym`, and positional `input` interface.
- [ ] Preserve repeated LEF ordering and parse the `KLAYOUT_ARGV` payload
  without losing quoted paths.
- [ ] Verify focused tests, lint, and the full suite.
- [ ] Commit separately from the stdlib swap.

---

### Task 4: Golden-test the current expression parser

**Files:**
- Create: `test/config/expression_cases.json`
- Modify: `test/config/test_preprocessor.py`

- [ ] Record successful results as exact `Decimal` strings.
- [ ] Record failures by exception type and stable message at both
  `Expr.evaluate` and `process_string("expr::…")`.
- [ ] Include generated combinations of operators, parentheses, numeric
  spellings, whitespace, and declared variable path syntax.
- [ ] Run the golden corpus against the hand-written parser and commit it before
  changing parser code.

---

### Task 5: Replace the expression parser with Lark

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `librelane/config/preprocessor.py`
- Modify: `test/config/test_preprocessor.py`

- [ ] Add a bounded Lark runtime dependency and refresh `uv.lock`.
- [ ] Define the expression grammar in `preprocessor.py`; retain the public
  `Expr.evaluate(expression, symbols) -> Decimal` entry point.
- [ ] Transform number tokens directly to `Decimal`, resolve variables from the
  supplied mapping, and implement the existing arithmetic semantics.
- [ ] Translate Lark parse/visit failures at the public boundary so the golden
  exception contract remains stable.
- [ ] Run the golden corpus, all config tests, `make lint`, and the full suite.
- [ ] Run `uv build`, verify Lark and all split step packages are in the
  resulting environment/wheel as appropriate, and run `nix build .#librelane`.
- [ ] Commit the parser replacement independently.

---

### Task 6: Prepare—but do not execute—the Pydantic gate

**Files:**
- Create: a dedicated follow-up plan after Tasks 1-5

- [ ] Inventory every declared `Variable`, including dynamically assembled
  step and flow variable lists.
- [ ] Specify the old/new comparison matrix for strict and permissive typing,
  Tcl list/dict coercion, path glob unwrapping, enum-by-name lookup,
  required/optional/PDK defaults, and callable deprecated aliases.
- [ ] Require zero unexplained golden-output differences before authorizing any
  `Variable.__process` replacement.
- [ ] Keep `Config.__process_variable_list` out of scope.
