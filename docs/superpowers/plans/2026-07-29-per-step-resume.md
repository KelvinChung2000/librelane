# Per-Step Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make re-invoking a flow against an existing run directory reuse every step whose configuration and input state are unchanged, instead of re-executing the whole flow into that directory.

**Architecture:** Two new leaf modules, then surgery on two existing ones. `librelane/common/fingerprint.py` answers "what is this path's content identity", memoized on stat. `librelane/flows/resume.py` turns a step plus its input state into a digest and reads and writes a `resume.json` entry in the step directory. `SequentialFlow.run` then consults that entry per step, reusing `state_out.json` on a match and wiping and re-running the directory otherwise. `Flow.start` loses the `Step.load_finished` pre-population and the modification-time state seeding that the old append behaviour depended on.

**Tech Stack:** Python 3.11+, pytest, pytest-mock, pyfakefs, uv for dependency management, ruff for lint and format.

**Spec:** `docs/superpowers/specs/2026-07-29-per-step-resume-design.md`. Read it before starting. Everything below implements it.

## Global Constraints

- All commands run through `uv`: `uv run pytest`, `uv run ruff`. Never call a bare `pytest` or `python`.
- Do not write `from __future__ import annotations`. Type expressions are written directly, using `X | None` rather than `Optional[X]`.
- Lint and format gate: `uv run ruff check <files>` and `uv run ruff format <files>` must both be clean before every commit.
- The full suite must stay green at every commit. Baseline is **489 passed, 1 deselected, 1 xfailed**. Verify with `uv run pytest test/ -q`.
- `git add -A` is forbidden in this repository. The sandbox bind-mounts `/dev/null` over `.bashrc`, `.gitconfig`, `.zshrc`, `.claude/` and other paths, and they appear as untracked entries. Stage explicit paths only.
- Never add a fallback path. When the code cannot prove something, it must say so or classify honestly, not guess.
- New files carry the repository's license header, copied verbatim from an existing 2026 file such as `librelane/cli/runtime.py` lines 1-13, with the year 2026 and holder "LibreLane Contributors".
- Docstrings use the Sphinx field style already in the codebase (`:param x:`, `:returns:`, `:raises X:`).
- Do not delete `Step.load_finished` (`librelane/steps/step/core.py:461`) or `get_latest_file` (`librelane/common/misc.py:327`). Both are public API and `get_latest_file` still has a live caller at `librelane/cli/state.py:51`. Only the call sites inside `Flow.start` are removed.

## File Structure

| Path | Responsibility |
|---|---|
| `librelane/common/fingerprint.py` | **Create.** `Fingerprinter`, content identity for a path, memoized on stat. |
| `librelane/common/__init__.py` | **Modify.** Re-export `Fingerprinter`. |
| `librelane/flows/resume.py` | **Create.** Key computation, entry read/write, hit decision. |
| `librelane/flows/flow.py` | **Modify.** Own a `Fingerprinter`; `dir_for_step` gains `position`; drop the `load_finished` loop and the mtime state seeding. |
| `librelane/flows/sequential.py` | **Modify.** Per-step hit/miss decision; positional dirs; `executed` separated from `increment_ordinal`; `--from` redefined. |
| `test/common/test_fingerprint.py` | **Create.** `Fingerprinter` unit tests. |
| `test/flows/test_resume_key.py` | **Create.** Key computation and entry read/write, in isolation from any flow. |
| `test/flows/test_resume.py` | **Create.** End-to-end resume behaviour on dummy steps. |
| `test/flows/test_flow.py` | **Modify.** `test_run_tags` asserts reuse instead of re-execution. |
| `docs/source/usage/` | **Modify.** Resume semantics documentation. |
| `Changelog.md` | **Modify.** Entry. |

---

### Task 1: `Fingerprinter`

**Files:**
- Create: `librelane/common/fingerprint.py`
- Modify: `librelane/common/__init__.py`
- Test: `test/common/test_fingerprint.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Fingerprinter`, with `of_path(path: str | os.PathLike[str]) -> str` returning `"file:<hex>"`, `"dir:<abspath>"` or `"absent:<abspath>"`. Importable as `from librelane.common import Fingerprinter` and `from librelane.common.fingerprint import Fingerprinter`.

- [ ] **Step 1: Write the failing tests**

Create `test/common/test_fingerprint.py`:

```python
import os

import pytest

from librelane.common import Fingerprinter

pytestmark = pytest.mark.all


def test_content_determines_the_identity_not_the_path(tmp_path):
    a = tmp_path / "a.v"
    b = tmp_path / "b.v"
    a.write_text("module top(); endmodule")
    b.write_text("module top(); endmodule")

    fingerprinter = Fingerprinter()

    assert fingerprinter.of_path(a) == fingerprinter.of_path(b)
    assert fingerprinter.of_path(a).startswith("file:")


def test_editing_a_file_changes_its_identity(tmp_path):
    target = tmp_path / "a.v"
    target.write_text("module top(); endmodule")
    before = Fingerprinter().of_path(target)

    target.write_text("module top(); wire w; endmodule")

    assert Fingerprinter().of_path(target) != before


def test_a_touch_that_preserves_content_preserves_the_identity(tmp_path):
    target = tmp_path / "a.v"
    target.write_text("module top(); endmodule")
    before = Fingerprinter().of_path(target)

    os.utime(target, (0, 0))

    assert Fingerprinter().of_path(target) == before


def test_a_file_is_read_once_per_fingerprinter(tmp_path, mocker):
    """
    The same PDK views appear in many steps' configurations. Re-reading a
    30MB liberty file once per step is the difference between a sub-second
    resume check and a multi-second one.
    """
    target = tmp_path / "a.lib"
    target.write_text("library(x) {}")
    fingerprinter = Fingerprinter()
    fingerprinter.of_path(target)

    spy = mocker.spy(fingerprinter, "_read_digest")
    for _ in range(5):
        fingerprinter.of_path(target)

    assert spy.call_count == 0


def test_a_changed_file_is_reread_despite_the_memo(tmp_path):
    target = tmp_path / "a.lib"
    target.write_text("library(x) {}")
    fingerprinter = Fingerprinter()
    before = fingerprinter.of_path(target)

    target.write_text("library(x) { cell(y) {} }")

    assert fingerprinter.of_path(target) != before


def test_a_directory_is_identified_without_being_read(tmp_path):
    """
    DESIGN_DIR and PDK_ROOT are Path-typed directories in every step's
    configuration. DESIGN_DIR contains runs/, so hashing its contents would
    make the key depend on the run in progress and never stabilise.
    """
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "junk").write_text("changes constantly")

    identity = Fingerprinter().of_path(tmp_path)
    (tmp_path / "runs" / "junk").write_text("changed again")

    assert identity == f"dir:{tmp_path}"
    assert Fingerprinter().of_path(tmp_path) == identity


def test_an_absent_path_gets_its_own_identity(tmp_path):
    missing = tmp_path / "nope.v"

    identity = Fingerprinter().of_path(missing)

    assert identity == f"absent:{missing}"


def test_an_absent_path_differs_from_the_same_path_once_created(tmp_path):
    target = tmp_path / "a.v"
    fingerprinter = Fingerprinter()
    absent = fingerprinter.of_path(target)

    target.write_text("module top(); endmodule")

    assert fingerprinter.of_path(target) != absent
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/common/test_fingerprint.py -q`

Expected: collection error, `ImportError: cannot import name 'Fingerprinter' from 'librelane.common'`.

- [ ] **Step 3: Write the implementation**

Create `librelane/common/fingerprint.py`. Copy the 13-line license header from `librelane/cli/runtime.py` verbatim, then:

```python
"""
Content identity for the files a step depends on.

A step's configuration and input state name files by path. A path is not an
identity: editing ``src/design.v`` leaves every path in both structures byte for
byte the same, so a resume decision made on paths alone would reuse stale
synthesis output. This module answers the question paths cannot.
"""

import hashlib
import os
import stat

#: Read granularity. Large enough that a 30MB liberty file is a handful of
#: reads, small enough not to hold a GDS in memory.
_CHUNK_SIZE = 1 << 20


class Fingerprinter:
    """
    Answers what a path's contents are, memoizing on cheap metadata.

    One instance is created per flow run. The same PDK views appear in many
    steps' configurations, and the memo is what keeps them read once rather than
    once per step.

    The memo is keyed on size and modification time, but the identity it caches
    is always a content hash. Using size and mtime as the identity itself would
    be wrong in both directions: Nix store paths carry epoch-normalized mtimes,
    so a rebuild can leave mtime untouched while contents differ, and a bare
    ``touch`` would otherwise invalidate a whole run for no reason.
    """

    def __init__(self) -> None:
        self.__memo: dict[tuple[str, int, int], str] = {}

    def _read_digest(self, path: str) -> str:
        """
        Hashes a file's contents.

        Separate from :meth:`of_path` so tests can assert the memo prevented a
        read rather than infer it from timing.

        :param path: An absolute path to a regular file.
        :returns: A 128-bit BLAKE2b digest, hex encoded.
        """
        digest = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as file:
            while chunk := file.read(_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    def of_path(self, path: str | os.PathLike[str]) -> str:
        """
        :param path: Any path, existing or not, file or directory.
        :returns: An identity string, one of:

            * ``file:<digest>`` for a regular file
            * ``dir:<abspath>`` for a directory, whose contents are deliberately
              not read
            * ``absent:<abspath>`` when nothing exists at the path

            An absent path yields an identity rather than raising, which is what
            turns a deleted view into an ordinary cache miss.
        """
        resolved = os.path.abspath(os.fspath(path))
        try:
            status = os.stat(resolved)
        except (FileNotFoundError, NotADirectoryError):
            return f"absent:{resolved}"

        if stat.S_ISDIR(status.st_mode):
            return f"dir:{resolved}"

        memo_key = (resolved, status.st_size, status.st_mtime_ns)
        if (cached := self.__memo.get(memo_key)) is not None:
            return cached

        identity = f"file:{self._read_digest(resolved)}"
        self.__memo[memo_key] = identity
        return identity
```

- [ ] **Step 4: Re-export it**

In `librelane/common/__init__.py`, add next to the existing `from .toolbox import Toolbox` line:

```python
from .fingerprint import Fingerprinter
```

If the module defines `__all__`, add `"Fingerprinter"` to it. Check with `grep -n "__all__" librelane/common/__init__.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/common/test_fingerprint.py -q`

Expected: 8 passed.

- [ ] **Step 6: Verify nothing else broke, then lint**

```bash
uv run pytest test/ -q
uv run ruff check librelane/common/fingerprint.py librelane/common/__init__.py test/common/test_fingerprint.py
uv run ruff format librelane/common/fingerprint.py librelane/common/__init__.py test/common/test_fingerprint.py
```

Expected: 497 passed, 1 deselected, 1 xfailed. All ruff checks pass.

- [ ] **Step 7: Commit**

```bash
git add librelane/common/fingerprint.py librelane/common/__init__.py test/common/test_fingerprint.py
git commit -m "feat: add content fingerprinting for resume keys

A path is not an identity. Editing src/design.v leaves every path in a
step's config and input state unchanged, so a resume decision made on
paths alone would reuse stale output.

Memoize on size and mtime but always cache a content hash: Nix store
paths carry epoch-normalized mtimes, so a rebuild can leave mtime
untouched while contents differ, and a bare touch would otherwise
invalidate a run for no reason.

Directories report their path rather than their contents, because
DESIGN_DIR contains runs/ and hashing it would make the key depend on
the run in progress."
```

---

### Task 2: Resume key and entry file

**Files:**
- Create: `librelane/flows/resume.py`
- Test: `test/flows/test_resume_key.py`

**Interfaces:**
- Consumes: `Fingerprinter.of_path` from Task 1.
- Produces, all importable from `librelane.flows.resume`:
  - `RESUME_ENTRY_FILENAME: str` = `"resume.json"`
  - `RESUME_SCHEMA_VERSION: int` = `1`
  - `resume_key(step: Step, state_in: State, fingerprinter: Fingerprinter) -> str`
  - `write_entry(step_dir: pathlib.Path, step: Step, key: str) -> None`
  - `reusable_state(step_dir: pathlib.Path, key: str, fingerprinter: Fingerprinter) -> State | None` returning the reusable output state, or `None` for a miss

- [ ] **Step 1: Write the failing tests**

Create `test/flows/test_resume_key.py`:

```python
import json
import pathlib

import pytest

from librelane.common import Fingerprinter
from librelane.config import Variable
from librelane.flows import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def KeyStep():
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    class KeyStep(Step):
        id = "Test.KeyStep"
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]
        config_vars = [
            Variable("DUMMY_VARIABLE", type=str, description="x"),
        ]

        def run(self, state_in: State, **kwargs):
            out_file = pathlib.Path(self.step_dir) / "whatever.json"
            out_file.write_text("{}")
            return {DesignFormat.JSON_HEADER: Path(out_file)}, {}

    return KeyStep


def _make_step(KeyStep, overrides=None):
    from librelane.config import Config

    cfg, _ = Config.load(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "PINGAS",
            "VERILOG_FILES": ["/cwd/src/a.v"],
            **(overrides or {}),
        },
        KeyStep.get_all_config_variables(),
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    from librelane.state import State

    return KeyStep(config=cfg, state_in=State())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_same_step_and_state_give_the_same_key(KeyStep):
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    first = resume_key(_make_step(KeyStep), State(), fingerprinter)
    second = resume_key(_make_step(KeyStep), State(), fingerprinter)

    assert first == second


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_config_value_changes_the_key(KeyStep):
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    before = resume_key(_make_step(KeyStep), State(), fingerprinter)
    after = resume_key(
        _make_step(KeyStep, {"DUMMY_VARIABLE": "DIFFERENT"}), State(), fingerprinter
    )

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_edited_input_file_changes_the_key_though_paths_are_identical(KeyStep):
    """
    The case a path-equality design gets wrong. VERILOG_FILES still names
    exactly /cwd/src/a.v; only its contents moved.
    """
    from librelane.flows.resume import resume_key
    from librelane.state import State

    pathlib.Path("/cwd/src/a.v").write_text("module top(); endmodule")
    before = resume_key(_make_step(KeyStep), State(), Fingerprinter())

    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")
    after = resume_key(_make_step(KeyStep), State(), Fingerprinter())

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_input_metric_changes_the_key(KeyStep):
    """Checker steps read state_in.metrics, so metrics are part of the key."""
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    before = resume_key(
        _make_step(KeyStep), State(metrics={"design__area": 1}), fingerprinter
    )
    after = resume_key(
        _make_step(KeyStep), State(metrics={"design__area": 2}), fingerprinter
    )

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_path_is_not_walked_as_a_sequence(KeyStep):
    """
    Path subclasses UserString, so a sequence branch reached before the Path
    branch would fingerprint a path character by character. Two different
    paths with identical contents must collide; per-character walking would
    make them differ.
    """
    from librelane.flows.resume import _substitute_paths
    from librelane.common import Path

    fingerprinter = Fingerprinter()
    pathlib.Path("/cwd/src/a.v").write_text("same")
    pathlib.Path("/cwd/src/b.v").write_text("same")

    assert _substitute_paths(Path("/cwd/src/a.v"), fingerprinter) == _substitute_paths(
        Path("/cwd/src/b.v"), fingerprinter
    )
    assert isinstance(_substitute_paths(Path("/cwd/src/a.v"), fingerprinter), str)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_paths_inside_a_dataclass_are_fingerprinted():
    """
    MACROS is dict[str, Macro] and Macro is a dataclass of Path lists. A walk
    that skips dataclasses would let a macro's GDS change go unnoticed.
    """
    from librelane.config.legacy import Macro
    from librelane.common import Path
    from librelane.flows.resume import _substitute_paths

    pathlib.Path("/cwd/src/m.gds").write_text("gds-one")
    pathlib.Path("/cwd/src/m.lef").write_text("lef")
    macro = Macro(gds=[Path("/cwd/src/m.gds")], lef=[Path("/cwd/src/m.lef")])

    before = _substitute_paths({"m": macro}, Fingerprinter())
    pathlib.Path("/cwd/src/m.gds").write_text("gds-two")
    after = _substitute_paths({"m": macro}, Fingerprinter())

    assert before != after


def test_a_missing_entry_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    assert reusable_state(tmp_path, "any-key", Fingerprinter()) is None


def test_a_mismatched_key_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 1, "key": "recorded", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {}}))

    assert reusable_state(tmp_path, "different", Fingerprinter()) is None


def test_a_truncated_entry_is_a_miss_not_an_error(tmp_path):
    """kill -9 mid-write is expected. It means miss, not crash."""
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text('{"schema": 1, "key": "reco')

    assert reusable_state(tmp_path, "recorded", Fingerprinter()) is None


def test_a_future_schema_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 99, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {}}))

    assert reusable_state(tmp_path, "k", Fingerprinter()) is None


def test_a_deleted_output_view_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state, write_entry

    view = tmp_path / "out.json"
    view.write_text("{}")
    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 1, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(
        json.dumps({"json_h": str(view), "metrics": {}})
    )
    assert reusable_state(tmp_path, "k", Fingerprinter()) is not None

    view.unlink()

    assert reusable_state(tmp_path, "k", Fingerprinter()) is None


def test_a_matching_entry_returns_the_output_state(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 1, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(
        json.dumps({"metrics": {"design__area": 5}})
    )

    state = reusable_state(tmp_path, "k", Fingerprinter())

    assert state is not None
    assert state.metrics["design__area"] == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_resume_key.py -q`

Expected: every test fails with `ModuleNotFoundError: No module named 'librelane.flows.resume'`.

- [ ] **Step 3: Write the implementation**

Create `librelane/flows/resume.py`. License header first, then:

```python
"""
The resume decision for a single step.

A step's directory records everything needed to judge whether its output can be
reused: ``config.json`` is its filtered configuration, ``state_in.json`` its
input, ``state_out.json`` its result. This module turns the first two into a
digest, stores that digest beside them, and compares.
"""

import dataclasses
import hashlib
import json
import os
import pathlib
from collections.abc import Mapping

from loguru import logger

from ..__version__ import __version__
from ..common import Fingerprinter, Path
from ..common.generic_dict import GenericDictEncoder
from ..state import State
from ..steps import Step

#: Written into a step directory once the step has completed successfully. Its
#: presence is the completion marker: a directory left half written by an
#: interrupted run has no entry and is therefore a miss.
RESUME_ENTRY_FILENAME = "resume.json"

#: Bumped whenever the key's inputs change meaning. An entry recording any other
#: version is a miss, which is how an upgrade invalidates stale entries without
#: needing to understand them.
RESUME_SCHEMA_VERSION = 1


def _substitute_paths(value, fingerprinter: Fingerprinter):
    """
    Replaces every :class:`librelane.common.Path` with its content identity.

    The ``Path`` branch comes first on purpose. ``Path`` subclasses
    ``UserString``, so it is a ``Sequence``, and a sequence branch reached first
    would walk a path character by character. For the same reason the sequence
    branch matches ``list`` and ``tuple`` explicitly rather than ``Sequence``.

    Dataclasses are walked because ``MACROS`` is ``dict[str, Macro]`` and
    :class:`librelane.config.legacy.Macro` holds its GDS, LEF and LIB views in
    ``list[Path]`` and ``dict[str, list[Path]]`` fields. Skipping them would let
    an edited macro view go unnoticed.
    """
    if isinstance(value, Path):
        return fingerprinter.of_path(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _substitute_paths(getattr(value, field.name), fingerprinter)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _substitute_paths(item, fingerprinter)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_substitute_paths(item, fingerprinter) for item in value]
    return value


def resume_key(step: Step, state_in: State, fingerprinter: Fingerprinter) -> str:
    """
    :param step: An instantiated step. Its ``config`` is already filtered to the
        step's own variables plus the universal flow variables, so the key covers
        exactly what the step can read.
    :param state_in: The state the step would receive.
    :param fingerprinter: Supplies content identity for referenced files.
    :returns: A hex digest identifying this step's work.
    """
    document = {
        "schema": RESUME_SCHEMA_VERSION,
        "step": type(step).get_implementation_id(),
        "librelane_version": __version__,
        "config": _substitute_paths(step.config.to_raw_dict(), fingerprinter),
        "state_in": _substitute_paths(
            state_in.to_raw_dict(metrics=True), fingerprinter
        ),
    }
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        cls=GenericDictEncoder,
    )
    return hashlib.blake2b(canonical.encode("utf8"), digest_size=16).hexdigest()


def write_entry(step_dir: str | os.PathLike[str], step: Step, key: str) -> None:
    """
    Records that this step completed with this key.

    Call only after the step returned without raising. ``step`` and
    ``librelane_version`` are recorded for diagnosis; only ``schema`` and ``key``
    take part in the decision.
    """
    entry = {
        "schema": RESUME_SCHEMA_VERSION,
        "key": key,
        "step": type(step).get_implementation_id(),
        "librelane_version": __version__,
    }
    (pathlib.Path(step_dir) / RESUME_ENTRY_FILENAME).write_text(
        json.dumps(entry, indent=4)
    )


def reusable_state(
    step_dir: str | os.PathLike[str],
    key: str,
    fingerprinter: Fingerprinter,
) -> State | None:
    """
    :returns: The output state to reuse, or ``None`` if this step must run.

    ``None`` covers every way a hit cannot be proven: no entry, an unreadable or
    truncated entry, a schema this version does not speak, a different key, an
    unreadable output state, or an output view that no longer exists. A truncated
    file after ``kill -9`` is an expected condition, so it is logged and treated
    as a miss rather than raised.
    """
    directory = pathlib.Path(step_dir)
    entry_path = directory / RESUME_ENTRY_FILENAME
    state_out_path = directory / "state_out.json"

    try:
        entry = json.loads(entry_path.read_text())
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        logger.log("VERBOSE", f"Unreadable resume entry at '{entry_path}': {error}")
        return None

    if entry.get("schema") != RESUME_SCHEMA_VERSION:
        logger.log(
            "VERBOSE",
            f"Resume entry at '{entry_path}' has schema {entry.get('schema')!r}, "
            f"expected {RESUME_SCHEMA_VERSION}.",
        )
        return None

    if entry.get("key") != key:
        return None

    try:
        state_out = State.loads(state_out_path.read_text(), validate_path=False)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, ValueError) as error:
        logger.log("VERBOSE", f"Unreadable output state at '{state_out_path}': {error}")
        return None

    missing = _missing_views(state_out)
    if missing:
        logger.log(
            "VERBOSE",
            f"Output views for '{directory.name}' are gone: {missing}.",
        )
        return None

    return state_out


def _missing_views(state: State) -> list[str]:
    """
    :returns: Paths in ``state`` that no longer exist.

    Existence only. The key already attests to the content, and re-hashing a
    multi-gigabyte GDS to confirm what the entry asserts would cost more than the
    step being avoided.
    """
    missing: list[str] = []

    def walk(value) -> None:
        if isinstance(value, Path):
            if not os.path.exists(value):
                missing.append(str(value))
            return
        if isinstance(value, Mapping):
            for item in value.values():
                walk(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(state.to_raw_dict(metrics=False))
    return missing
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_resume_key.py -q`

Expected: 12 passed.

If `State.loads` rejects `validate_path=False` as an unknown argument, check its
signature with `grep -n "def loads" -A 6 librelane/state/state.py` and pass the
equivalent. Paths must not be validated on load here, because a missing view is a
miss to be reported by `_missing_views`, not an exception.

- [ ] **Step 5: Verify nothing else broke, then lint**

```bash
uv run pytest test/ -q
uv run ruff check librelane/flows/resume.py test/flows/test_resume_key.py
uv run ruff format librelane/flows/resume.py test/flows/test_resume_key.py
```

Expected: 509 passed, 1 deselected, 1 xfailed.

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/resume.py test/flows/test_resume_key.py
git commit -m "feat: add the resume key and its step-directory entry

A step directory already records everything needed to judge reuse: the
filtered config, the input state and the result. Turn the first two into
a digest, store it beside them, compare.

The path walk recurses into dataclasses because MACROS is
dict[str, Macro] and Macro keeps its GDS, LEF and LIB views in Path
fields; skipping them would let an edited macro view go unnoticed. Path
is tested before any sequence because it subclasses UserString and would
otherwise be walked character by character.

Every way a hit cannot be proven is a miss, including a truncated entry:
kill -9 mid-write is expected, and a miss is the honest reading."
```

---

### Task 3: Positional step directories

**Files:**
- Modify: `librelane/flows/flow.py` (`dir_for_step`, currently at `:834`)
- Test: `test/flows/test_resume.py` (create; extended in Task 5)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Flow.dir_for_step(self, step: Step, position: int | None = None) -> pathlib.Path`. With `position=i`, the directory is `run_dir / f"{i + 1:0{width}d}-{slugify(step.id)}"` where `width = len(str(len(self.Steps)))`. With `position=None`, behaviour is unchanged from today.

- [ ] **Step 1: Write the failing test**

Create `test/flows/test_resume.py`:

```python
import pathlib

import pytest

from librelane.config import Variable
from librelane.flows import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def ResumeSteps():
    """
    Three steps that record how many times each has executed, so a test can
    assert reuse directly rather than inferring it.
    """
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    runs: dict[str, int] = {}

    class Base(Step):
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]

        def run(self, state_in: State, **kwargs):
            runs[self.id] = runs.get(self.id, 0) + 1
            out_file = pathlib.Path(self.step_dir) / "whatever.json"
            out_file.write_text('{"produced_by": "%s"}' % self.id)
            return {DesignFormat.JSON_HEADER: Path(out_file)}, {}

    class First(Base):
        id = "Test.First"
        config_vars = [Variable("DUMMY_VARIABLE", type=str, description="x")]

    class Second(Base):
        id = "Test.Second"
        inputs = [DesignFormat.JSON_HEADER]

    class Third(Base):
        id = "Test.Third"
        inputs = [DesignFormat.JSON_HEADER]

    return (First, Second, Third), runs


@pytest.fixture
def ResumeFlow(ResumeSteps):
    from librelane.flows import SequentialFlow

    (First, Second, Third), runs = ResumeSteps

    class ResumeFlow(SequentialFlow):
        Steps = [First, Second, Third]

    def make():
        return ResumeFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    return make, runs


def step_dirs(tag="T"):
    return sorted(
        entry.name
        for entry in pathlib.Path(f"/cwd/runs/{tag}").iterdir()
        if entry.is_dir() and entry.name != "final" and entry.name != "tmp"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_step_directories_are_positional(ResumeFlow):
    """
    A step's directory must not depend on how many earlier steps happened to
    run, or a resumed run cannot find its own prior output.
    """
    make, _ = ResumeFlow
    make().start(tag="T")

    assert step_dirs() == ["1-test-first", "2-test-second", "3-test-third"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_skipped_step_leaves_its_position_empty(ResumeFlow):
    """
    Today's dense counter would name the third step 2-. Positional numbering
    leaves the gap, which is the point: Test.Third keeps its directory whether
    or not Test.Second ran.
    """
    make, _ = ResumeFlow
    make().start(tag="T", skip=["Test.Second"])

    assert step_dirs() == ["1-test-first", "3-test-third"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: `test_step_directories_are_positional` fails because the current dense counter names the directories without zero padding differences only when steps are skipped, and `test_a_skipped_step_leaves_its_position_empty` fails with `["1-test-first", "2-test-third"]`.

If the first test passes at this point, that is expected and fine: with no skipped steps, positional and dense numbering agree. The second test is the one that must fail.

- [ ] **Step 3: Change `dir_for_step`**

In `librelane/flows/flow.py`, replace the body of `dir_for_step`:

```python
    @protected
    def dir_for_step(self, step: Step, position: int | None = None) -> pathlib.Path:
        """
        May only be called while :attr:`run_dir` is not None, i.e., the flow
        has started. Otherwise, a :class:`FlowException` is raised.

        :param step: The step to name a directory for.
        :param position: The step's index in :attr:`Steps`, if the flow has a
            fixed step list. Passing it makes the directory depend on the step's
            position rather than on how many earlier steps happened to run, which
            is what lets a resumed run find its own prior output.

            Flows that build steps in data-dependent loops, such as
            :class:`librelane.flows.Optimizing`, omit it and keep the running
            counter.
        :returns: A directory within the run directory for a specific step.
        """
        if self.run_dir is None:
            raise FlowException(
                "Attempted to call dir_for_step on a flow that has not been started."
            )
        if position is None:
            prefix = self.progress_bar.get_ordinal_prefix()
        else:
            width = len(str(len(self.Steps)))
            prefix = f"{position + 1:0{width}d}-"
        return self.run_dir / f"{prefix}{slugify(step.id)}"
```

- [ ] **Step 4: Pass the position from `SequentialFlow.run`**

In `librelane/flows/sequential.py`, change the loop header at `:388` and both
`dir_for_step` call sites (`:408` and `:415`):

```python
        for position, cls in enumerate(self.Steps):
            step = cls(config=self.config, state_in=current_state)
            step_dir = self.dir_for_step(step, position=position)
```

Then use `step_dir` at both call sites, replacing `self.dir_for_step(step)`:

```python
            elif cls.id == reproducible_resolved:
                step.create_reproducible(step_dir / "reproducible")
                break
```

```python
                    current_state = step.start(
                        toolbox=self.toolbox,
                        step_dir=step_dir,
                    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: 2 passed.

- [ ] **Step 6: Verify nothing else broke, then lint**

```bash
uv run pytest test/ -q
uv run ruff check librelane/flows/flow.py librelane/flows/sequential.py test/flows/test_resume.py
uv run ruff format librelane/flows/flow.py librelane/flows/sequential.py test/flows/test_resume.py
```

Expected: 511 passed, 1 deselected, 1 xfailed.

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/flow.py librelane/flows/sequential.py test/flows/test_resume.py
git commit -m "feat: name sequential step directories by position

A step's directory currently depends on how many earlier steps happened
to run, so skipping or gating one shifts every later directory. A
resumed run cannot find its own prior output that way.

Name them by index in Steps instead. A gated step now leaves a gap,
which is the trade being made: Test.Third keeps its directory whether or
not Test.Second ran. For a full run with nothing gated the names are
unchanged, since the padding width is the same.

Flows that build steps in data-dependent loops, Optimizing and
SynthesisExploration, omit the position and keep the running counter."
```

---

### Task 4: `Flow` owns a `Fingerprinter`

**Files:**
- Modify: `librelane/flows/flow.py` (class attributes near `:420`, and `Flow.start` near `:746`)
- Test: `test/flows/test_resume.py`

**Interfaces:**
- Consumes: `Fingerprinter` from Task 1.
- Produces: `Flow.fingerprinter: Fingerprinter | None`, assigned in `Flow.start` next to `self.toolbox` and readable as `self.fingerprinter` from `run`.

- [ ] **Step 1: Write the failing test**

Append to `test/flows/test_resume.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_flow_owns_one_fingerprinter_per_run(ResumeFlow):
    """
    The memo is what keeps a PDK's liberty files read once rather than once
    per step, so the instance has to outlive a single step.
    """
    from librelane.common import Fingerprinter

    make, _ = ResumeFlow
    subject = make()
    assert subject.fingerprinter is None

    subject.start(tag="T")

    assert isinstance(subject.fingerprinter, Fingerprinter)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest test/flows/test_resume.py::test_the_flow_owns_one_fingerprinter_per_run -q`

Expected: FAIL with `AttributeError: 'ResumeFlow' object has no attribute 'fingerprinter'`.

- [ ] **Step 3: Add the attribute**

In `librelane/flows/flow.py`, beside the existing `step_objects: list[Step] | None = None` class attribute, add:

```python
    #: Content identity for files this run's steps depend on. Assigned by
    #: :meth:`start` and shared by every step, so a PDK view referenced by
    #: twenty steps is read once.
    fingerprinter: Fingerprinter | None = None
```

Add `Fingerprinter` to the existing import from `..common` at the top of the file. Check the current import block with `grep -n "from ..common import" -A 12 librelane/flows/flow.py`.

Then in `Flow.start`, immediately after the `self.toolbox = Toolbox(...)` line:

```python
        self.fingerprinter = Fingerprinter()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: 3 passed.

- [ ] **Step 5: Verify nothing else broke, then lint**

```bash
uv run pytest test/ -q
uv run ruff check librelane/flows/flow.py test/flows/test_resume.py
uv run ruff format librelane/flows/flow.py test/flows/test_resume.py
```

Expected: 512 passed, 1 deselected, 1 xfailed.

- [ ] **Step 6: Commit**

```bash
git add librelane/flows/flow.py test/flows/test_resume.py
git commit -m "feat: give a flow run a shared Fingerprinter

Its memo is what keeps a PDK liberty file referenced by twenty steps
read once per run rather than twenty times, so the instance is owned by
the flow alongside its Toolbox."
```

---

### Task 5: The resume decision

This is the task that changes behaviour. It replaces the append-a-full-pass path with per-step reuse, so the deletions and the additions have to land together or the tree is incoherent in between.

**Files:**
- Modify: `librelane/flows/sequential.py` (the run loop, `:387-432`)
- Modify: `librelane/flows/flow.py` (delete the `load_finished` loop `:708-722` and the mtime seeding `:726-733`; drop the `_no_load_previous_steps` parameter at `:621`)
- Modify: `test/flows/test_flow.py` (`test_run_tags`, `:338-345`)
- Test: `test/flows/test_resume.py`

**Interfaces:**
- Consumes: `resume_key`, `write_entry`, `reusable_state` from Task 2; `dir_for_step(step, position=...)` from Task 3; `self.fingerprinter` from Task 4.
- Produces: no new public API. `SequentialFlow.run` reuses or executes each step; `_after_step` receives `executed=True` for a reused step.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_resume.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_resumed_run_executes_nothing(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")
    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_resumed_run_adds_no_directories(ResumeFlow):
    """The old behaviour appended a whole second pass into the same tag."""
    make, _ = ResumeFlow
    make().start(tag="T")
    before = step_dirs()

    make().start(last_run=True)

    assert step_dirs() == before


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_config_reruns_from_that_step_onward(ResumeFlow):
    """
    DUMMY_VARIABLE belongs to Test.First only, but re-running it changes
    Test.Second's input state, so the invalidation has to cascade.
    """
    from librelane.flows import SequentialFlow

    make, runs = ResumeFlow
    make().start(tag="T")

    (First, Second, Third) = make().Steps

    class Changed(SequentialFlow):
        Steps = [First, Second, Third]

    Changed(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "DIFFERENT",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    ).start(tag="T")

    assert runs == {"Test.First": 2, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_edited_input_file_reruns_the_flow(ResumeFlow):
    """
    Every path is unchanged; only the bytes of /cwd/src/a.v moved. This is
    the case a path-equality design reuses wrongly.
    """
    make, runs = ResumeFlow
    pathlib.Path("/cwd/src/a.v").write_text("module top(); endmodule")
    make().start(tag="T")

    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")
    make().start(tag="T")

    assert runs["Test.First"] == 2


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_crash_resumes_at_the_failing_step(ResumeSteps):
    from librelane.flows import FlowError, SequentialFlow
    from librelane.steps import StepError

    (First, Second, Third), runs = ResumeSteps
    fail = {"now": True}

    class Flaky(Second):
        id = "Test.Second"

        def run(self, state_in, **kwargs):
            if fail["now"]:
                raise StepError("boom")
            return super().run(state_in, **kwargs)

    class CrashFlow(SequentialFlow):
        Steps = [First, Flaky, Third]

    def make():
        return CrashFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs == {"Test.First": 1}

    fail["now"] = False
    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_deleted_output_view_reruns_only_its_step(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")
    pathlib.Path("/cwd/runs/T/2-test-second/whatever.json").unlink()

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_reused_step_counts_as_executed_for_the_stage_contract(ResumeFlow):
    """
    StagedFlow._after_step skips the contract check unless every step in the
    stage executed. A reused step really did produce its views, so reporting
    it as not executed would disable the check the contract exists for.
    """
    make, _ = ResumeFlow
    make().start(tag="T")

    seen = []
    subject = make()
    original = type(subject)._after_step

    def record(self, step, state, executed):
        seen.append((step.id, executed))
        return original(self, step, state, executed)

    type(subject)._after_step = record
    try:
        subject.start(last_run=True)
    finally:
        type(subject)._after_step = original

    assert seen == [
        ("Test.First", True),
        ("Test.Second", True),
        ("Test.Third", True),
    ]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_overwrite_discards_the_run_directory(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", overwrite=True)

    assert runs == {"Test.First": 2, "Test.Second": 2, "Test.Third": 2}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: `test_a_resumed_run_executes_nothing`, `test_a_resumed_run_adds_no_directories`, `test_a_crash_resumes_at_the_failing_step` and `test_a_deleted_output_view_reruns_only_its_step` all fail because every step re-executes. `test_overwrite_discards_the_run_directory` and the config-change test may already pass, which is fine.

- [ ] **Step 3: Add the decision to the run loop**

In `librelane/flows/sequential.py`, add to the imports at the top:

```python
from .resume import resume_key, reusable_state, write_entry
```

Replace the body of the loop from `self.progress_bar.start_stage(step.name)` (`:402`) through `self._after_step(...)` (`:429`) with:

```python
            self.progress_bar.start_stage(step.name)
            executed = True
            if not executing or cls.id in skipped_ids or gated:
                logger.info(f"Skipping step '{step.name}'…")
                executed = False
            elif cls.id == reproducible_resolved:
                step.create_reproducible(step_dir / "reproducible")
                break
            else:
                assert self.fingerprinter is not None
                key = resume_key(step, current_state, self.fingerprinter)
                reused = reusable_state(step_dir, key, self.fingerprinter)
                if reused is not None:
                    logger.info(f"Reusing '{step.name}' from a previous run…")
                    step.step_dir = step_dir
                    step.state_out = reused
                    current_state = reused
                    step_list.append(step)
                    reused_count += 1
                else:
                    shutil.rmtree(step_dir, ignore_errors=True)
                    step_list.append(step)
                    try:
                        current_state = step.start(
                            toolbox=self.toolbox,
                            step_dir=step_dir,
                        )
                    except StepException as e:
                        raise FlowException(str(e)) from None
                    except DeferredStepError as e:
                        deferred_errors.append(str(e))
                    except StepError as e:
                        raise FlowError(str(e)) from None
                    else:
                        # Only on a clean return. A step that deferred an error
                        # gets no entry, so it runs again next time and raises
                        # again, with no bookkeeping needed to remember that.
                        write_entry(step_dir, step, key)
                    executed_count += 1

            self.progress_bar.end_stage(increment_ordinal=executed)

            # A reused step produced its views and metrics as surely as one that
            # just ran, and they are in the state being checked, so the stage
            # contract still applies to it.
            self._after_step(step, current_state, executed)
```

Add `import shutil` to the imports if absent, and initialise the counters beside
`deferred_errors = []`:

```python
        reused_count = 0
        executed_count = 0
```

After the loop, beside the existing `logger.success("Flow complete.")`, report what happened:

```python
        if reused_count:
            logger.info(
                f"Reused {reused_count} step(s) from a previous run; "
                f"executed {executed_count}."
            )
```

- [ ] **Step 4: Delete the old resume machinery from `Flow.start`**

In `librelane/flows/flow.py`:

1. Delete the `_no_load_previous_steps: bool = False,` parameter (`:621`) and its `:param` documentation entry if one exists.
2. Replace the whole `for entry in entries_sorted:` loop body (`:700-724`) so it only computes the ordinal, dropping the `Step.load_finished` call:

```python
            for entry in entries_sorted:
                try:
                    extracted_ordinal = int(entry.split("-", maxsplit=1)[0])
                except ValueError:
                    continue
                starting_ordinal = max(starting_ordinal, extracted_ordinal + 1)
```

3. Delete the `# Extract Maximum State` block (`:726-733`) entirely. Each step now resolves its own input, so seeding from whichever `state_out.json` was touched most recently is both unnecessary and the cause of upstream steps receiving downstream states.

4. Remove now-unused imports. `Step.load_finished` and `get_latest_file` both stay in their own modules, but `flow.py` may no longer need `get_latest_file` or `StepNotFound`. Confirm with `uv run ruff check librelane/flows/flow.py`, which reports unused imports, and remove only what it flags.

- [ ] **Step 5: Update `test_run_tags`**

In `test/flows/test_flow.py`, the assertion at `:342` locks in the deleted behaviour:

```python
    state = flow.start(tag="MY_TAG2")
    assert "Using existing run at" in caplog.text, (
        ".start() with a non-empty folder did not print a message about an existing run"
    )
    assert state.metrics["step"] == 3, (
        ".start() using existing run failed to return latest state"
    )
```

`step` counted 3 because the whole flow ran a second time on top of the first
pass's metrics. With resume, both steps are reused and the metric keeps the value
the first pass produced. Replace the second assertion with:

```python
    assert state.metrics["step"] == 1, (
        ".start() using an existing run re-executed instead of reusing"
    )
```

Then run `uv run pytest test/flows/test_flow.py::test_run_tags -q -s` and, if the
value differs, read the printed metric and set the assertion to what reuse
actually yields, keeping the message. Do not change it back to a re-execution
assertion.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest test/flows/test_resume.py -q
uv run pytest test/flows/test_flow.py -q
```

Expected: all pass.

- [ ] **Step 7: Verify the whole suite, in random order, then lint**

```bash
uv run pytest test/ -q
uv run pytest test/ -q
uv run ruff check librelane/flows/sequential.py librelane/flows/flow.py test/flows/test_resume.py test/flows/test_flow.py
uv run ruff format librelane/flows/sequential.py librelane/flows/flow.py test/flows/test_resume.py test/flows/test_flow.py
```

Expected: 520 passed, 1 deselected, 1 xfailed, both times.

- [ ] **Step 8: Commit**

```bash
git add librelane/flows/sequential.py librelane/flows/flow.py test/flows/test_resume.py test/flows/test_flow.py
git commit -m "feat: reuse a step's output when its key still matches

Reusing a run directory re-executed the whole flow into it, seeded with
the previous pass's final state. Nothing ever tested a step for having
already completed.

Consult each step's recorded key instead: reuse state_out.json on a
match, wipe and re-run the directory otherwise. A step that deferred an
error gets no entry, so it runs and raises again with no bookkeeping.

Deleting the load_finished pre-population and the modification-time
state seeding retires four defects at once. No step receives a
downstream state, metrics no longer accumulate across passes,
step_objects holds each step exactly once, and no step loses its
duplicate-ID suffix, because the objects are built by the flow rather
than reconstructed from config.json.

A reused step is reported to _after_step as executed. It produced the
contracted views and metrics, so StagedFlow must still hold its stage
to the contract."
```

---

### Task 6: `--from` forces re-execution

**Files:**
- Modify: `librelane/flows/sequential.py` (the run loop and the `run` docstring)
- Test: `test/flows/test_resume.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: no new API. `--from X` re-executes X onward unconditionally and raises `FlowException` when a step before X cannot be reused.

- [ ] **Step 1: Write the failing tests**

Append to `test/flows/test_resume.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_reruns_that_step_even_though_its_key_matches(ResumeFlow):
    """
    The remedy for the one thing the key does not cover: a CAD tool upgraded
    in place under an unchanged LibreLane version.
    """
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(last_run=True, frm="Test.Second")

    assert runs == {"Test.First": 1, "Test.Second": 2, "Test.Third": 2}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_refuses_when_an_earlier_step_is_stale(ResumeFlow):
    """
    Better to name the stale step than to proceed with an empty state and
    fail later on a missing input.
    """
    from librelane.flows import FlowException

    make, _ = ResumeFlow
    make().start(tag="T")
    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")

    with pytest.raises(FlowException, match="Test.First"):
        make().start(last_run=True, frm="Test.Second")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_from_on_a_fresh_tag_refuses(ResumeFlow):
    from librelane.flows import FlowException

    make, _ = ResumeFlow

    with pytest.raises(FlowException, match="Test.First"):
        make().start(tag="FRESH", frm="Test.Second")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest test/flows/test_resume.py -q -k from`

Expected: `test_from_reruns_that_step_even_though_its_key_matches` fails because
the step is reused rather than re-run. The two refusal tests fail because no
exception is raised.

- [ ] **Step 3: Implement it**

In the run loop, the `not executing` branch currently just skips. A step before
`--from` must instead be resolved from cache, because the next step needs its
state. Replace the branch:

```python
            if not executing or cls.id in skipped_ids or gated:
                logger.info(f"Skipping step '{step.name}'…")
                executed = False
```

with:

```python
            if not executing:
                # Before --from. The step is not re-run, but the next step needs
                # its output, so it has to come from cache. There is nowhere else
                # for it to come from now that a run's state is not reconstructed
                # by modification time.
                assert self.fingerprinter is not None
                key = resume_key(step, current_state, self.fingerprinter)
                reused = reusable_state(step_dir, key, self.fingerprinter)
                if reused is None:
                    raise FlowException(
                        f"Cannot start from '{frm_resolved}': step '{step.id}' "
                        f"comes earlier and has no reusable result, so its "
                        f"output state is unavailable. Re-run without --from, "
                        f"or use --overwrite to start the tag clean."
                    )
                logger.info(f"Reusing '{step.name}' from a previous run…")
                step.step_dir = step_dir
                step.state_out = reused
                current_state = reused
                step_list.append(step)
                reused_count += 1
                executed = True
            elif cls.id in skipped_ids or gated:
                logger.info(f"Skipping step '{step.name}'…")
                executed = False
```

Then make `--from` force execution. In the `else` branch from Task 5, the reuse
lookup must be bypassed for the step named by `--from` and everything after it.
Track that with a flag set when `--from` matches, initialised beside the counters:

```python
        forced = False
```

and set where `executing` is turned on (`:390`):

```python
            if frm_resolved is not None and frm_resolved == step.id:
                executing = True
                forced = True
```

In the `else` branch, guard the lookup:

```python
                reused = (
                    None
                    if forced
                    else reusable_state(step_dir, key, self.fingerprinter)
                )
```

- [ ] **Step 4: Update the `run` docstring**

`SequentialFlow.run` documents `frm` as where to start. Say what it now means:

```python
        :param frm: Force re-execution from this step onward, ignoring any
            reusable result for it and every step after it.

            Steps before it are taken from their previous results. If any of them
            has no reusable result, a :class:`FlowException` is raised naming it,
            because its output state is then unavailable and there is nothing
            honest to run the rest of the flow on.

            This is the remedy for the one thing a resume key does not cover: a
            CAD tool upgraded in place, or a script edited in a development
            checkout, under an unchanged LibreLane version.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: all pass.

- [ ] **Step 6: Verify the whole suite, then lint**

```bash
uv run pytest test/ -q
uv run ruff check librelane/flows/sequential.py test/flows/test_resume.py
uv run ruff format librelane/flows/sequential.py test/flows/test_resume.py
```

Expected: 523 passed, 1 deselected, 1 xfailed.

Note: `test/flows/test_sequential.py` exercises `--from` and `--to`. If any of its
tests now fail, read each one before changing it. A test asserting that `--from`
skips earlier steps is asserting the old contract and should be updated to the new
one. A test asserting `--to` behaviour should still pass unchanged; if it does
not, the implementation is wrong, not the test.

- [ ] **Step 7: Commit**

```bash
git add librelane/flows/sequential.py test/flows/test_resume.py
git commit -m "feat: make --from force re-execution from a step onward

--from used to skip earlier steps and rely on the run's state being
reconstructed from whichever state_out.json was touched most recently.
That seeding is gone, so the option needs a meaning that does not depend
on it.

It now forces re-execution of the named step and everything after it,
ignoring their keys, and takes earlier steps from their previous
results. A stale earlier step raises and names itself rather than
letting the flow proceed on an empty state and fail later on a missing
input.

This is also the documented remedy for the one thing the key does not
cover: a tool upgraded in place under an unchanged LibreLane version."
```

---

### Task 7: The remaining invalidation behaviours

The spec commits to four behaviours that fall out of Tasks 5 and 6 rather than
needing new code. Each is a claim a reader of the spec is entitled to rely on, so
each gets a test. If any of them fails, the implementation is wrong, not the test.

**Files:**
- Test: `test/flows/test_resume.py`
- Modify: `librelane/flows/sequential.py`, only if a test reveals a defect

**Interfaces:**
- Consumes: everything from Tasks 5 and 6.
- Produces: no new API.

- [ ] **Step 1: Write the tests**

Append to `test/flows/test_resume.py`:

```python
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_deferred_error_step_runs_again_and_raises_again(ResumeSteps):
    """
    A step that deferred an error never wrote an entry, so it re-runs. That is
    what keeps a deferred failure from being silently reused as a success.
    """
    from librelane.flows import FlowError, SequentialFlow
    from librelane.steps import DeferredStepError

    (First, Second, Third), runs = ResumeSteps

    class Deferring(Second):
        id = "Test.Second"

        def run(self, state_in, **kwargs):
            runs[self.id] = runs.get(self.id, 0) + 1
            raise DeferredStepError("deferred boom")

    class DeferFlow(SequentialFlow):
        Steps = [First, Deferring, Third]

    def make():
        return DeferFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    with pytest.raises(FlowError):
        make().start(tag="T")
    assert runs["Test.Second"] == 1

    with pytest.raises(FlowError):
        make().start(last_run=True)

    assert runs["Test.Second"] == 2, (
        "a deferred-error step was reused instead of re-run"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_skipping_a_step_invalidates_the_steps_after_it(ResumeFlow):
    """
    Skipping changes what the next step receives, so it cannot be reused.
    """
    make, runs = ResumeFlow
    make().start(tag="T")

    make().start(tag="T", skip=["Test.Second"])

    assert runs["Test.First"] == 1, "the step before the skip should be reused"
    assert runs["Test.Second"] == 1, "the skipped step should not run"
    assert runs["Test.Third"] == 2, "the step after the skip must not be reused"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_to_then_resume_continues_rather_than_restarting(ResumeFlow):
    make, runs = ResumeFlow
    make().start(tag="T", to="Test.Second")
    assert runs == {"Test.First": 1, "Test.Second": 1}

    make().start(last_run=True)

    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_shorter_step_list_leaves_the_orphaned_directory_alone(ResumeSteps):
    """
    Resuming a tag with a different step list shifts positions. Directories
    belonging to no current position are never read and never deleted.
    """
    from librelane.flows import SequentialFlow

    (First, Second, Third), runs = ResumeSteps

    class Long(SequentialFlow):
        Steps = [First, Second, Third]

    class Short(SequentialFlow):
        Steps = [First, Second]

    config = {
        "DESIGN_NAME": "WHATEVER",
        "DUMMY_VARIABLE": "PINGAS",
        "VERILOG_FILES": ["/cwd/src/a.v"],
    }
    kwargs = dict(
        design_dir="/cwd", pdk="dummy", scl="dummy_scl", pdk_root="/pdk"
    )

    Long(config, **kwargs).start(tag="T")
    Short(config, **kwargs).start(tag="T")

    assert pathlib.Path("/cwd/runs/T/3-test-third").is_dir(), (
        "an orphaned step directory must not be deleted"
    )
    assert runs == {"Test.First": 1, "Test.Second": 1, "Test.Third": 1}, (
        "the shorter list must reuse the steps it still has"
    )
```

- [ ] **Step 2: Run them**

Run: `uv run pytest test/flows/test_resume.py -q`

Expected: all pass. Tasks 5 and 6 should already produce these behaviours.

If `test_a_shorter_step_list_leaves_the_orphaned_directory_alone` fails on the
padding width, note why: `Long` has three steps so its width is 1, and `Short` has
two so its width is also 1. Both produce `1-`, `2-`, `3-`. Should a future flow
cross ten steps, the width changes and positions renumber, which is a legitimate
miss rather than a bug. Do not add padding-compensation logic; a changed step list
invalidating is correct.

If any other test fails, fix `librelane/flows/sequential.py`. Do not weaken the
test to match the implementation.

- [ ] **Step 3: Lint and verify the suite**

```bash
uv run pytest test/ -q
uv run ruff check test/flows/test_resume.py librelane/flows/sequential.py
uv run ruff format test/flows/test_resume.py librelane/flows/sequential.py
```

Expected: 527 passed, 1 deselected, 1 xfailed.

- [ ] **Step 4: Commit**

```bash
git add test/flows/test_resume.py librelane/flows/sequential.py
git commit -m "test: pin the resume invalidation behaviours the spec promises

A deferred-error step re-runs rather than being reused as a success.
Skipping a step invalidates everything after it, because it changes what
they receive. --to followed by a plain resume continues instead of
restarting. A step list that no longer reaches a directory leaves it
alone rather than deleting it.

All four follow from the resume decision itself, but each is a claim the
spec makes, so each gets a test that would catch its loss."
```

---

### Task 8: Documentation and changelog

**Files:**
- Modify: a usage page under `docs/source/usage/`
- Modify: `Changelog.md`

- [ ] **Step 1: Find the right documentation home**

```bash
grep -rn "run-tag\|last-run\|runs/" docs/source/usage/*.md | head -20
ls docs/source/usage/
```

Add the section to the page that already documents run tags and the `runs/`
directory. If no page covers it, create `docs/source/usage/resuming_runs.md` and
add it to the `toctree` in `docs/source/usage/index.md`.

- [ ] **Step 2: Write the section**

Markdown syntax, no HTML tags. Cover exactly this:

- The two modes. Naming an existing tag, via `--run-tag` or `--last-run`, resumes it. `--overwrite` discards it and starts clean. There is no third mode.
- What is reused. A step is reused when its own configuration, the contents of every file that configuration names, and its entire input state including metrics are unchanged, and its recorded outputs still exist.
- That invalidation cascades. Re-running a step changes the input state of every step after it.
- That `runs/TAG/<n>-<step>` is positional, so a gated or skipped step leaves a gap in the numbering.
- The caveat, stated plainly: upgrading a CAD tool in place, or editing a `.tcl`
  script in a development checkout, without changing LibreLane's version, is not
  detected. Use `--from` to force re-execution from a step onward, or
  `--overwrite` to discard the run.
- That resume applies to sequential flows. `Optimizing` and
  `SynthesisExploration` build their steps in data-dependent loops and do not
  participate.

- [ ] **Step 3: Add the changelog entry**

Read the top of `Changelog.md` for the current in-progress version heading and
match the existing bullet style exactly. Add entries covering: per-step resume on
an existing run tag; positional step directories for sequential flows; the
redefinition of `--from`; and the removal of the append-a-full-pass behaviour.

Flag the last two as behaviour changes, since users and CI may depend on them.

- [ ] **Step 4: Verify the docs build**

```bash
grep -rn "sphinx\|myst" pyproject.toml | head
```

If a docs build command exists, for example a `docs` extra or a `Makefile` target,
run it and confirm no warnings for the new file. If no docs toolchain is
installed in this environment, say so rather than claiming the build passed.

- [ ] **Step 5: Commit**

```bash
git add docs/source/usage Changelog.md
git commit -m "docs: document resume semantics and the tool-upgrade caveat

State the two modes, what invalidates a step, that invalidation
cascades, and that step directory numbering is positional so a gated
step leaves a gap.

Say plainly that a CAD tool upgraded in place under an unchanged
LibreLane version is not detected, and that --from and --overwrite are
the remedies. A caveat a user cannot find is a trap."
```

---

## Final verification

- [ ] Full suite, five consecutive runs with random ordering:

```bash
for i in 1 2 3 4 5; do uv run pytest test/ -q | tail -1; done
```

All five must report the same count with zero failures.

- [ ] Lint and format across everything touched:

```bash
uv run ruff check librelane/ test/
uv run ruff format --check librelane/ test/
```

- [ ] Confirm the spec's own claims hold, by re-reading
`docs/superpowers/specs/2026-07-29-per-step-resume-design.md` against the
implementation. Anything the implementation had to do differently is a spec
correction, not a silent divergence: amend the spec and say so.

- [ ] Report honestly. State the test counts, name anything left undone, and do
not describe the tool-upgrade caveat as fixed. It is a documented non-goal.
