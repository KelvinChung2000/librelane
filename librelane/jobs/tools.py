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
Reading the ``TOOLS`` key ahead of full configuration resolution.

A flow's step set must be known before its configuration can be validated,
because the steps are what declare the variables. When configuration is also
what selects the steps, that is circular. This module breaks the cycle with a
narrow pre-pass that reads one key and validates nothing else, mirroring the
two-phase read that already recovers ``PDK`` and ``DESIGN_NAME`` early.

This lives under ``jobs`` rather than ``config.loading`` because it raises a
job-level error: ``jobs`` depends on ``config``, so the reverse would be a
cycle.
"""

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from loguru import logger

from librelane.config.loading import (
    ConfigSource,
    OpenLaneYAMLLoader,
    layer_mappings,
    read_source,
)

from librelane.jobs.job import JobResolutionError

TOOLS_KEY = "TOOLS"

#: Prefixes the configuration preprocessor treats specially. None may appear
#: inside TOOLS, because this pre-pass runs before the preprocessor does.
_PREPROCESSOR_PREFIXES = ("ref::", "expr::", "refg::", "dir::")


def _reject_construct(job: str, value: str) -> None:
    for prefix in _PREPROCESSOR_PREFIXES:
        if value.startswith(prefix):
            raise JobResolutionError(
                f"TOOLS['{job}'] is '{value}'. TOOLS must be a literal "
                f"mapping: tool selection is read before the configuration "
                f"preprocessor runs, so '{prefix}' and other constructs "
                f"cannot be evaluated there."
            )


def _validate(raw: Any) -> dict[str, str | list[str]]:
    if not isinstance(raw, Mapping):
        raise JobResolutionError(
            f"TOOLS must be a mapping from job id to provider name, got "
            f"{type(raw).__name__}."
        )
    result: dict[str, str | list[str]] = {}
    for job, value in raw.items():
        if isinstance(value, str):
            _reject_construct(str(job), value)
            result[str(job)] = value
            continue
        if isinstance(value, Sequence):
            providers = []
            for element in value:
                if not isinstance(element, str):
                    raise JobResolutionError(
                        f"TOOLS['{job}'] contains {type(element).__name__}; "
                        f"every provider name must be a string."
                    )
                _reject_construct(str(job), element)
                providers.append(element)
            result[str(job)] = providers
            continue
        raise JobResolutionError(
            f"TOOLS['{job}'] is {type(value).__name__}; a provider selection "
            f"must be a string naming one provider."
        )
    return result


def extract_tools(
    config_in: Sequence[Mapping[str, Any] | str | os.PathLike],
    *,
    config_override_strings: Sequence[str] | None = None,
    yaml_loader=OpenLaneYAMLLoader,
) -> dict[str, str | list[str]]:
    """
    Reads only the ``TOOLS`` key out of a set of layered configuration sources,
    without preprocessing or validating anything else.

    Layering follows the same precedence as :meth:`librelane.config.Config.load`:
    later sources win, and command line overrides win over every source.

    Tcl configuration files are not evaluated here, because evaluating one
    requires process information that is not yet resolved. A ``.tcl`` source
    therefore contributes no ``TOOLS`` entries, and this is reported so it is
    never mistaken for the file having been read and found empty.

    Parameters
    ----------
    config_in : Sequence[Mapping[str, Any] | str | os.PathLike]
        The same sequence :meth:`librelane.config.Config.load`
        receives.
    config_override_strings : Sequence[str] | None
        ``NAME=VALUE`` strings from the command
        line. A ``TOOLS=`` override must be a JSON object.

    Raises
    ------
    JobResolutionError
        If ``TOOLS`` is present but malformed.
    """
    sources: list[ConfigSource] = []
    for entry in config_in:
        source = read_source(entry, yaml_loader=yaml_loader)
        if source.kind == "tcl":
            logger.info(
                f"TOOLS is not read from Tcl configuration files; "
                f"'{source.name}' was not consulted for tool selection and "
                f"job defaults apply."
            )
        sources.append(source)

    raw = layer_mappings(sources).mapping.get(TOOLS_KEY)

    for string in config_override_strings or []:
        key, _, value = string.partition("=")
        if key != TOOLS_KEY:
            continue
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as error:
            raise JobResolutionError(
                f"TOOLS override on the command line is not valid JSON: {error}"
            ) from None

    if raw is None:
        return {}
    return _validate(raw)
