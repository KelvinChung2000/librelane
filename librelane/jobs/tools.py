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
narrow pre-pass that reads one key and validates nothing else, reusing the
two-phase read that already recovers ``PDK`` and ``DESIGN_NAME`` early.

Reusing rather than mirroring is the point. Where a source scopes ``TOOLS``
under a ``pdk::`` or ``scl::`` section, deciding which section applies means
resolving the process, and a second implementation of that would be free to
resolve it differently than the loader does -- so this calls
:meth:`librelane.config.Config.expand_sources`, which is what
:meth:`librelane.config.Config.load` calls. The two therefore cannot disagree
about what a configuration says ``TOOLS`` is, which is the disagreement
``--explain-variables`` used to be able to show.

This lives under ``jobs`` rather than ``config.loading`` because it raises a
job-level error: ``jobs`` depends on ``config``, so the reverse would be a
cycle.
"""

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any


from librelane.config import Config
from librelane.config.loading import (
    ConfigSource,
    LayeredMapping,
    LibreLaneYAMLLoader,
    layer_mappings,
    read_source,
)

from librelane.jobs.job import JobResolutionError

TOOLS_KEY = "TOOLS"

#: The prefixes :func:`librelane.config.preprocessor.apply_overlays` treats as
#: scoped sections. A source carrying one cannot be read for ``TOOLS`` until the
#: process it is matched against is resolved.
_SECTION_PREFIXES = ("pdk::", "scl::")

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


def _first_section(mapping: Mapping[str, Any]) -> str | None:
    """
    Returns
    -------
    The first ``pdk::`` or ``scl::`` section anywhere inside this mapping, or
    ``None`` if it carries none.

    The search follows :func:`librelane.config.preprocessor.apply_overlays`
    exactly -- into every nested mapping, and into the mappings inside a list --
    because a section anywhere it would look is a section that changes what
    expanding this mapping produces.
    """
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            if key.startswith(_SECTION_PREFIXES):
                return key
            if nested := _first_section(value):
                return nested
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping) and (nested := _first_section(item)):
                    return nested
    return None


def _promotes_tools(section: Mapping[str, Any]) -> bool:
    """
    Returns
    -------
    Whether expanding this section could put a ``TOOLS`` key in the mapping that
    carries it.

    What a section promotes is its own keys, plus the keys of the sections
    nested directly inside it -- an ``scl::`` block inside a ``pdk::`` one
    reaches two levels up. A ``TOOLS`` under any *other* key of the section
    ends up under that key and not at the top level, so it is not this.
    """
    if TOOLS_KEY in section:
        return True
    return any(
        key.startswith(_SECTION_PREFIXES)
        and isinstance(value, Mapping)
        and _promotes_tools(value)
        for key, value in section.items()
    )


def _scoped_tools(mapping: Mapping[str, Any]) -> str | None:
    """
    Returns
    -------
    The key of the first section whose expansion could change this mapping's
    ``TOOLS``, or ``None`` if none can.

    Two shapes qualify and nothing else does: a section that promotes a
    ``TOOLS`` of its own, and a section written *inside* a ``TOOLS`` value.
    ``TOOLS`` is the only key read here, so a section that cannot reach it --
    which is most of them, since scoping ``FP_CORE_UTIL`` per PDK is the
    ordinary use -- is no reason to resolve a process.
    """
    for key, value in mapping.items():
        if not isinstance(value, Mapping):
            # A section is a mapping-valued key, so no other value can be one.
            # This is where the claim above stops being exact: a *list*-valued
            # ``TOOLS`` whose items carried sections would not be detected. It
            # is safe because a list ``TOOLS`` is not a selection either
            # consumer accepts -- ``_validate`` refuses it here and the
            # variable's own type refuses it in the loader -- so there is no
            # value left for the two to disagree about.
            continue
        if key.startswith(_SECTION_PREFIXES):
            if _promotes_tools(value):
                return key
        elif key == TOOLS_KEY:
            if nested := _first_section(value):
                return nested
    return None


def _first_scoped_source(sources: Sequence[ConfigSource]) -> tuple[str, str] | None:
    """
    Returns
    -------
    The name of the first source that scopes ``TOOLS`` and the section's key,
    or ``None`` if no source scopes it.
    """
    for source in sources:
        if section := _scoped_tools(source.mapping):
            return (source.name, section)
    return None


def _layer_for_selection(
    sources: Sequence[ConfigSource],
    *,
    design_dir: str | None,
    pdk: str | None,
    pdk_root: str | None,
    scl: str | None,
    pad: str | None,
) -> LayeredMapping:
    """
    Layers the sources the way the loader will, resolving the process and
    expanding their sections first where one of them scopes ``TOOLS``.

    Parameters
    ----------
    sources : Sequence[ConfigSource]
        Every source, including the command line's, unexpanded.
    design_dir : str | None
        The design directory, or ``None`` if neither an argument nor a file
        path supplied one.

    Raises
    ------
    ValueError
        If a section has to be resolved and no PDK is named, or no design
        directory is known. Both messages are
        :meth:`librelane.config.Config.load`'s own.
    """
    scoped = _first_scoped_source(sources)
    if scoped is None:
        # Nothing here can move TOOLS, so expanding would return the same
        # mapping and this layering is the one the loader produces. Resolving
        # the PDK anyway would put a question to the filesystem whose answer
        # could not change the result, and would make a missing or uninstalled
        # PDK surface from tool selection instead of from the loader that
        # actually needs it.
        return layer_mappings(sources)

    if design_dir is None:
        raise ValueError(
            "The design_dir argument is required when configuration dictionaries are used."
        )
    return Config.expand_sources(
        sources,
        design_dir,
        pdk=pdk,
        pdk_root=pdk_root,
        scl=scl,
        pad=pad,
    ).layered


def extract_tools(
    config_in: Sequence[Mapping[str, Any] | str | os.PathLike],
    *,
    config_override_strings: Sequence[str] | None = None,
    design_dir: str | None = None,
    pdk: str | None = None,
    pdk_root: str | None = None,
    scl: str | None = None,
    pad: str | None = None,
    yaml_loader=LibreLaneYAMLLoader,
) -> dict[str, str | list[str]]:
    """
    Reads only the ``TOOLS`` key out of a set of layered configuration sources,
    without preprocessing or validating anything else.

    Layering follows the same precedence as :meth:`librelane.config.Config.load`:
    later sources win, and command line overrides win over every source.

    A ``TOOLS`` key inside a ``pdk::`` or ``scl::`` section is read: where a
    source scopes ``TOOLS``, this resolves the process first, through
    :meth:`librelane.config.Config.expand_sources` -- the one implementation
    the loader itself runs, so the selection and the run cannot disagree about
    which ``TOOLS`` the configuration states. Where none does, no process is
    resolved and none has to exist, because no expansion of those sources could
    move the only key read here.

    Parameters
    ----------
    config_in : Sequence[Mapping[str, Any] | str | os.PathLike]
        The same sequence :meth:`librelane.config.Config.load`
        receives.
    config_override_strings : Sequence[str] | None
        ``NAME=VALUE`` strings from the command
        line. A ``TOOLS=`` override must be a JSON object.
    design_dir : str | None
        As :meth:`librelane.config.Config.load`: the directory holding the last
        file in ``config_in`` when it is not given.
    pdk : str | None
        As :meth:`librelane.config.Config.load`.
    pdk_root : str | None
        As :meth:`librelane.config.Config.load`.
    scl : str | None
        As :meth:`librelane.config.Config.load`.
    pad : str | None
        As :meth:`librelane.config.Config.load`.

    Raises
    ------
    JobResolutionError
        If ``TOOLS`` is present but malformed.
    ValueError
        If a scoped section has to be resolved and no source and no argument
        names a PDK. Raised by the loader's own resolution, so the message is
        the one running the flow would produce.
    """
    sources: list[ConfigSource] = []
    file_design_dir: str | None = None
    for entry in config_in:
        source = read_source(entry, yaml_loader=yaml_loader)
        if not isinstance(entry, Mapping):
            file_design_dir = os.path.dirname(source.name)
        sources.append(source)

    overrides: dict[str, Any] = {}
    for string in config_override_strings or []:
        key, _, value = string.partition("=")
        overrides[key] = value
    # A layer of its own, last, exactly as Config.load builds it. It carries
    # 'TOOLS' as the unparsed string the shell supplied, which the loop at the
    # end replaces with the parsed object; it is here because a '--config-override
    # PDK=' outranks every file and so decides which sections match.
    sources.append(ConfigSource(overrides, "<command line>", "commandline"))

    layered = _layer_for_selection(
        sources,
        design_dir=design_dir or file_design_dir,
        pdk=pdk,
        pdk_root=pdk_root,
        scl=scl,
        pad=pad,
    )
    raw = layered.mapping.get(TOOLS_KEY)

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
