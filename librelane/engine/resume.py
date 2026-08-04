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

from librelane.__version__ import __version__
from librelane.common import Fingerprinter
from librelane.common.generic_dict import GenericDictEncoder
from librelane.state import InvalidState, State
from librelane.steps import Step

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
    Replaces every :class:`pathlib.Path` with its content identity.

    The path branch comes first on purpose, and the sequence branch matches
    ``list`` and ``tuple`` explicitly rather than ``Sequence``. Both guard
    against a path being walked element by element, which is what the old
    ``UserString``-based path type would have done under a ``Sequence`` branch.

    Dataclasses are walked because ``MACROS`` is ``dict[str, Macro]`` and
    :class:`librelane.config.legacy.Macro` holds its GDS, LEF and LIB views in
    ``list[Path]`` and ``dict[str, list[Path]]`` fields. Skipping them would let
    an edited macro view go unnoticed.

    Parameters
    ----------
    value
        Any value from a configuration or state.
    fingerprinter : Fingerprinter
        Supplies content identity for referenced files.

    Returns
    -------
    ``value`` with every path replaced by its content identity.
    """
    if isinstance(value, pathlib.Path):
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
    Parameters
    ----------
    step : Step
        An instantiated step. Its ``own_config_dict`` narrows the scope's
        shared configuration to the step's own variables plus the universal
        flow variables, so the key covers exactly what the step can read --
        and an edit to a variable this step does not declare leaves its entry
        valid.
    state_in : State
        The state the step would receive.
    fingerprinter : Fingerprinter
        Supplies content identity for referenced files.

    Returns
    -------
    str
        A hex digest identifying this step's work.
    """
    document = {
        "schema": RESUME_SCHEMA_VERSION,
        "step": type(step).get_implementation_id(),
        "librelane_version": __version__,
        "config": _substitute_paths(step.own_config_dict(), fingerprinter),
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

    Parameters
    ----------
    step_dir : str | os.PathLike[str]
        The step's directory within the run directory.
    step : Step
        The step that just completed.
    key : str
        The key it completed with.
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
    Parameters
    ----------
    step_dir : str | os.PathLike[str]
        The step's directory within the run directory.
    key : str
        The key the step would complete with now.
    fingerprinter : Fingerprinter
        Supplies content identity for referenced files.

    Returns
    -------
    State | None
        The output state to reuse, or ``None`` if this step must run.

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
    except (InvalidState, OSError, ValueError) as error:
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
    Parameters
    ----------
    state : State
        A state loaded from a step directory.

    Returns
    -------
    list[str]
        Paths in ``state`` that no longer exist.

    Existence only. The key already attests to the content, and re-hashing a
    multi-gigabyte GDS to confirm what the entry asserts would cost more than the
    step being avoided.
    """
    missing: list[str] = []

    def walk(value) -> None:
        if isinstance(value, pathlib.Path):
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
