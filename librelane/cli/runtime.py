# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane 2
#
# Copyright 2023 Efabless Corporation
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
What the shared options in :mod:`librelane.cli.options` actually do.

Typer validates option syntax; these helpers turn the validated values into
process state: a log level, a thread pool, a downloaded PDK, a loaded state.
They run after parsing and are the only place in the CLI layer that reaches out
to the network or mutates the environment.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path

from loguru import logger
import typer

from librelane.common import (
    ContextPropagatingThreadPoolExecutor,
    _get_process_limit,
    get_pdk_hash,
    set_tpe,
)
from librelane.engine.flow import Flow
from librelane.logging import options, set_log_level
from librelane.state import InvalidState, State


DEFAULT_JOBS = _get_process_limit()


@dataclass(frozen=True)
class ResolvedPdkOptions:
    pdk_root: str | None
    pdk: str
    scl: str | None
    pad: str | None


def validate_flow_name(flow_name: str | None) -> str | None:
    """Resolve a flow ID case-insensitively while preserving its registered name."""
    if flow_name is None:
        return None
    for candidate in Flow.factory.list():
        if candidate.casefold() == flow_name.casefold():
            return candidate
    choices = ", ".join(Flow.factory.list())
    raise typer.BadParameter(f"unknown flow {flow_name!r}; choose from: {choices}")


def apply_runtime_options(
    *,
    log_level: str | None,
    show_progress_bar: bool | None,
    condensed: bool,
    jobs: int | None,
) -> None:
    """Apply process-wide execution options after Typer has validated them."""
    if log_level is not None:
        level: str | int = log_level
        try:
            level = int(log_level)
        except ValueError:
            pass
        try:
            set_log_level(level)
        except ValueError as error:
            raise typer.BadParameter(
                f"invalid logging level {log_level!r}: {error}",
                param_hint="--log-level",
            ) from error

    if condensed:
        options.set_condensed_mode(True)
        options.set_show_progress_bar(False)
    if show_progress_bar is not None:
        options.set_show_progress_bar(show_progress_bar)

    if jobs is not None:
        set_tpe(ContextPropagatingThreadPoolExecutor(max_workers=jobs))


def load_initial_state(state_files: list[Path] | None) -> State | None:
    """Load and merge state JSON files in command-line order."""
    if not state_files:
        return None

    raw: dict = {}
    for state_file in state_files:
        try:
            with state_file.open(encoding="utf8") as file:
                state_dict = json.load(file)
            if not isinstance(state_dict, dict):
                raise ValueError(f"JSON data in {state_file} is not a dictionary")
            raw.update(state_dict)
        except json.JSONDecodeError as error:
            logger.error(f"Invalid JSON file {state_file}: {error}")
            raise typer.Exit(-1) from error
        except OSError as error:
            logger.error(f"Failed to read initial state {state_file}: {error}")
            raise typer.Exit(-1) from error
        except ValueError as error:
            logger.error(error)
            raise typer.Exit(-1) from error

    try:
        return State.load(raw, validate_path=True)
    except InvalidState as error:
        logger.error(error)
        raise typer.Exit(-1) from error


def resolve_pdk_options(
    *,
    use_ciel: bool,
    pdk_root: Path | None,
    pdk: str,
    scl: str | None,
    pad: str | None,
) -> ResolvedPdkOptions:
    """Resolve manual or Ciel-managed PDK inputs and consume their environment."""
    for variable in ("PDK_ROOT", "PDK", "STD_CELL_LIBRARY", "PAD_CELL_LIBRARY"):
        os.environ.pop(variable, None)

    pdk_root_string = str(pdk_root) if pdk_root is not None else None
    if not use_ciel:
        if pdk_root_string is None:
            logger.error("Argument --pdk-root must be present with --manual-pdk.")
            raise typer.Exit(1)
        return ResolvedPdkOptions(pdk_root_string, pdk, scl, pad)

    import ciel
    from ciel.source import DataSource

    # The same spelling and default the ciel CLI uses, so pointing a fork's
    # release channel at LibreLane is one environment variable and not a code
    # change.
    data_source_spec = os.getenv(
        "CIEL_DATA_SOURCE",
        "static-web:https://fossi-foundation.github.io/ciel-releases",
    )
    scheme, _, target = data_source_spec.partition(":")
    data_source_cls = DataSource.factory.get(scheme)
    if not target or data_source_cls is None:
        logger.error(
            f"CIEL_DATA_SOURCE {data_source_spec!r} is not in the format "
            f"'class:argument' with a class among: " + ", ".join(DataSource.factory)
        )
        raise typer.Exit(1)

    opdks_rev = get_pdk_hash(pdk)
    ciel_home = ciel.get_ciel_home(pdk_root_string)

    include_libraries = ["default"]
    if scl is not None:
        include_libraries.append(scl)
    if pad is not None:
        include_libraries.append(pad)

    pdk_family = None
    if family := ciel.Family.by_name.get(pdk):
        pdk = family.default_variant
        pdk_family = family.name
        logger.log("VERBOSE", f"Resolved PDK variant {family.default_variant}.")
    else:
        for family in ciel.Family.by_name.values():
            if pdk in family.variants:
                pdk_family = family.name
                break

    if pdk_family is None:
        logger.error(f"Could not resolve the PDK '{pdk}'.")
        raise typer.Exit(1)

    try:
        version = ciel.fetch(
            ciel_home,
            pdk_family,
            opdks_rev,
            data_source=data_source_cls(target),
            include_libraries=include_libraries,
        )
        pdk_root_string = version.get_dir(ciel_home)
    except ValueError as error:
        logger.error(f"Failed to download PDK: {error}")
        raise typer.Exit(1) from error

    return ResolvedPdkOptions(pdk_root_string, pdk, scl, pad)
