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
``include``: the key with which one workflow document reuses another's.

A document names files under ``include``, and what those files declare is
merged underneath what it declares itself. Merging happens on the raw mapping,
before :class:`librelane.engine.spec.FlowSpec` sees anything, so every structural
rule in that model -- that a ``needs`` names a declared job, that a ring has one
gate -- is checked against the *merged* document and nothing here has to restate
any of them. What this module decides is only which declaration reaches the
model when two files make one.

Two rules decide that, and they are the whole of the semantics:

* **The including document wins.** A job, a variable, a ``with`` entry or a
  pool it declares itself replaces the included one. A job is replaced whole,
  never merged key by key: a job is the unit a document reasons about, and a
  reader who sees ``uses`` in an override should not have to open another file
  to find the ``if`` that survived from underneath it.
* **Two includes may not declare the same thing.** Nothing orders one include
  above another -- they are a set of things being reused, not a stack of
  overrides -- so a key declared by both is an ambiguity this refuses rather
  than resolves.

A file may be included by more than one of the files being merged; it is read
once, and the diamond that produces is not a conflict. What makes it one is
answered by asking which file a declaration came from rather than how many
times it arrived, so a diamond one arm of which overrides the shared file *is*
a conflict, whichever order the arms are written in. An include cycle is an
error.

An included file is a document like any other, and may itself include. It need
not be *runnable*: ``name`` and ``jobs`` are required of the document being
loaded, not of the files it includes, so a file declaring nothing but ``config``
is a legal include and an illegal flow. A fragment's own ``name`` and
``description`` are ignored, which is what lets one carry them for the benefit
of an editor validating it against the schema.

An entry is a path relative to the file that wrote it, an absolute path, or
``common::<file>``, which names a file in the library LibreLane ships in
``librelane/share/common/``. That library is the answer to a question a path
cannot answer: a document in a design's own repository has no way to write
where LibreLane was installed, and the three shipped documents would have to
name their own directory to reach the declarations they share.

Answering that question is what :func:`share_directory` and
:func:`common_directory` below are for, and it is why they live here rather
than in a module of their own: locating a document file on disk is the same
question whether the file is a shipped flow or a fragment one reaches with
``common::``, and both are answered from the same installed directory.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from librelane.common.errors import FlowSpecError
from librelane.config.loading.sources import ConfigSource, read_source

#: The package the share directory sits in, and its name inside it.
#:
#: ``librelane/share/`` holds data and no code: the workflow documents that are
#: this installation's built-in flows, and under ``common/`` the library a
#: document reaches with ``common::``. Keeping them out of the package that
#: reads them is what lets a reader tell the two apart -- a ``.yaml`` beside a
#: ``.py`` reads as configuration *for* that module, which these are not.
_SHARE_PACKAGE = "librelane"
_SHARE_DIRECTORY = "share"

#: The library of shared declarations, inside the share directory.
_COMMON_DIRECTORY = "common"


def share_directory() -> Traversable:
    """
    Returns
    -------
    The directory holding the workflow documents this installation ships.

    Addressed through the ``librelane`` package rather than through
    ``__file__`` so that the directory is found wherever the installation is:
    inside a virtual environment, a Nix store path, a system ``site-packages``.
    """
    return files(_SHARE_PACKAGE).joinpath(_SHARE_DIRECTORY)


def common_directory() -> Traversable:
    """
    Returns
    -------
    The directory holding the fragments a document reaches with ``common::``.
    """
    return share_directory().joinpath(_COMMON_DIRECTORY)


#: The key this module consumes. Never reaches
#: :class:`~librelane.engine.spec.FlowSpec`, which rejects it: by the time a
#: model exists the includes are already merged into the document.
INCLUDE_KEY = "include"

#: The directive naming a file in LibreLane's own library of shared
#: declarations rather than one on disk beside the document.
#:
#: Spelled as the configuration file's ``dir::`` and ``pdk_dir::`` are, and for
#: the same reason they exist: the file being named is somewhere the document
#: cannot write a path to. LibreLane's library lives wherever it was installed
#: -- inside a virtual environment, a Nix store path, a system site-packages --
#: so a document that reached it by path would be a document that only works on
#: the machine it was written on.
COMMON_PREFIX = "common::"

#: Every key a document may declare at its top level.
#:
#: Written out rather than derived from ``FlowSpec.model_fields``, because
#: importing the model here would be a cycle -- ``spec`` imports this module to
#: resolve a document before it can build one. ``test_spec_include`` asserts
#: this tuple is exactly the model's aliases plus :data:`INCLUDE_KEY`, so the
#: two cannot drift apart silently.
_FLOW_KEYS = (
    "name",
    "description",
    "with",
    "config",
    "jobs",
    "final",
    "resources",
    INCLUDE_KEY,
)

#: The keys an include never contributes. They are the identity of the document
#: being loaded: a flow is registered and selected under one name, and taking
#: the name of a file it happens to reuse would make ``--flow`` name whichever
#: fragment sorted last. A fragment may still carry them for itself.
_OWN_KEYS = ("name", "description")

#: The mapping-valued sections, merged key by key. The value type of each is
#: the model's business; this only decides which of two values reaches it.
_MAPPING_KEYS = ("with", "jobs", "resources")

#: The scalar sections an include contributes. A single value, so "the
#: including document wins" is the whole of the rule and two includes declaring
#: it is the conflict.
_SCALAR_KEYS = ("final",)

#: The extensions :func:`~librelane.config.loading.sources.read_source` reads
#: as a mapping, and every extension it reads at all.
_INCLUDE_EXTENSIONS = (".yaml", ".yml", ".json")


@dataclass(frozen=True)
class _Resolution:
    """What one included file merged to, kept so it is merged once."""

    #: The file, as it will be reported.
    name: str
    #: The file and its own includes, merged.
    mapping: Mapping[str, Any]
    #: The file each key of :attr:`mapping` was declared in, which is what a
    #: second reach compares against rather than the fact of the reach.
    declared: Mapping[tuple[str, str], str]


@dataclass(frozen=True)
class ResolvedDocument:
    """A document and everything it included, merged into one mapping."""

    #: The merged document, carrying no :data:`INCLUDE_KEY` of its own.
    mapping: Mapping[str, Any]
    #: The name of the document that was loaded, for error messages.
    name: str
    #: Every file merged into it, in the order they were read. Empty when the
    #: document included nothing.
    included: tuple[str, ...]

    @property
    def origin(self) -> str:
        """
        Returns
        -------
        The document's name, and the files merged into it where there are any:
        the set of files an error found in the merged document could be in.
        """
        if not self.included:
            return f"'{self.name}'"
        merged = ", ".join(f"'{path}'" for path in self.included)
        return f"'{self.name}' (including {merged})"


def resolve_includes(source: ConfigSource) -> ResolvedDocument:
    """
    Reads every document ``source`` includes and merges them underneath it.

    Parameters
    ----------
    source : ConfigSource
        The document as read, before any validation.

    Returns
    -------
    The merged document.

    Raises
    ------
    FlowSpecError
        If an include cannot be read, if a document declares a key no document
        may, or if two of the files being merged declare the same job,
        variable, value or pool. Every message names the file the offending key
        is written in, which is not necessarily the document being loaded.
    """
    from_file = source.kind != "mapping"
    read: dict[str, _Resolution] = {}
    merged, _ = _merge_document(
        _mapping_of(source.mapping, source.name),
        source.name,
        os.path.dirname(source.name) if from_file else None,
        ((os.path.realpath(source.name), source.name),) if from_file else (),
        read,
    )
    return ResolvedDocument(
        merged, source.name, tuple(resolution.name for resolution in read.values())
    )


def _merge_document(
    document: Mapping[str, Any],
    name: str,
    anchor: str | None,
    chain: tuple[tuple[str, str], ...],
    read: dict[str, "_Resolution"],
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    """
    Merges one document's includes underneath it, depth first.

    Parameters
    ----------
    document : Mapping[str, Any]
        The document as written, including its :data:`INCLUDE_KEY`.
    name : str
        Its name, for error messages.
    anchor : str | None
        The directory a relative include is resolved against, or ``None`` for a
        document that came from a mapping and so has no directory of its own.
    chain : tuple[tuple[str, str], ...]
        The documents currently being merged, this one last, each as its real
        path and the name to report it under, so that a cycle is reported as
        the path of includes that closes it.
    read : dict[str, _Resolution]
        What every file included so far merged to, keyed by real path, in the
        order they were read. Mutated: a file reached twice is read once and
        its result reused at both reaches, which is what makes a diamond cost
        one read and still deliver its declarations to both arms.

    Returns
    -------
    The merged mapping, and the file each of its keys was declared in.
    """
    _check_keys(document, name)
    merged: dict[str, Any] = {}
    declared: dict[tuple[str, str], str] = {}
    for entry in _include_entries(document, name):
        path = _resolve_path(entry, name, anchor)
        real = os.path.realpath(path)
        if real in {link for link, _ in chain}:
            closed = " -> ".join([reported for _, reported in chain] + [path])
            raise FlowSpecError(
                f"Workflow document '{name}' includes '{entry}', which is "
                f"already being included: {closed}. An include cycle has no "
                f"document underneath it to merge."
            )
        resolution = read.get(real)
        if resolution is None:
            source = _read_include(path, entry, name)
            included, included_declared = _merge_document(
                _mapping_of(source.mapping, source.name),
                source.name,
                os.path.dirname(source.name),
                chain + ((real, source.name),),
                read,
            )
            resolution = _Resolution(source.name, included, included_declared)
            read[real] = resolution
        _merge_include(merged, declared, resolution.mapping, resolution.declared, name)
    _layer_own(merged, declared, document, name)
    return merged, declared


def _check_keys(document: Mapping[str, Any], name: str) -> None:
    """
    Refuses a top-level key no document may declare.

    ``FlowSpec``'s ``extra="forbid"`` would refuse it too, but only once
    everything is merged, and it would name the document being loaded rather
    than the file the key is written in.
    """
    unknown = [key for key in document if key not in _FLOW_KEYS]
    if unknown:
        raise FlowSpecError(
            f"Workflow document '{name}' declares unknown key(s) "
            f"{sorted(unknown)}. A document accepts exactly "
            f"{list(_FLOW_KEYS)}."
        )


def _mapping_of(document: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise FlowSpecError(
            f"Workflow document '{name}' is not a mapping of keys to values, "
            f"but {type(document).__name__}. A document declares its jobs "
            f"under a top-level 'jobs' key; an empty file declares nothing at "
            f"all."
        )
    return document


def _include_entries(document: Mapping[str, Any], name: str) -> list[str]:
    entries = document.get(INCLUDE_KEY)
    if entries is None:
        return []
    if isinstance(entries, str) or not isinstance(entries, (list, tuple)):
        raise FlowSpecError(
            f"Workflow document '{name}' declares '{INCLUDE_KEY}: "
            f"{entries!r}'. An '{INCLUDE_KEY}' is a list of paths to the "
            f"documents this one reuses, even where there is one of them."
        )
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            raise FlowSpecError(
                f"Workflow document '{name}' includes {entry!r}, which is not "
                f"a path. An '{INCLUDE_KEY}' entry is a path to a "
                f"{', '.join(_INCLUDE_EXTENSIONS)} document."
            )
        # Caught rather than deduplicated: the second mention adds nothing, so
        # a document that has one means something other than what it wrote.
        if entry in seen:
            raise FlowSpecError(
                f"Workflow document '{name}' includes '{entry}' more than "
                f"once. An '{INCLUDE_KEY}' names each document exactly once."
            )
        seen.add(entry)
    return list(entries)


def _resolve_path(entry: str, name: str, anchor: str | None) -> str:
    """
    Resolves one include entry against the document that wrote it.

    A relative path is relative to the *including document's* directory, not to
    the working directory: a document and the fragments it reuses travel
    together, and where they are run from is not their business. A
    :data:`COMMON_PREFIX` entry is relative to nothing and is answered by the
    installation, so it is the one form a document loaded from a mapping can
    still write.
    """
    if entry.startswith(COMMON_PREFIX):
        return _resolve_common(entry, name)
    if os.path.isabs(entry):
        return entry
    if anchor is None:
        raise FlowSpecError(
            f"Workflow document '{name}' includes '{entry}', a relative path, "
            f"but this document was loaded from a mapping and so has no "
            f"directory to resolve it against. Load the document from a file, "
            f"or write the include as an absolute path."
        )
    return os.path.abspath(os.path.join(anchor, entry))


def _resolve_common(entry: str, name: str) -> str:
    """
    Resolves ``common::<file>`` to the file of that name in the library.

    The library is one flat directory of files, not a tree, so the name is one
    file name: a separator or a ``..`` in it would be a document reaching
    somewhere the directive does not go, and is refused rather than followed.
    """
    requested = entry[len(COMMON_PREFIX) :]
    if not requested or os.path.basename(requested) != requested or requested == "..":
        raise FlowSpecError(
            f"Workflow document '{name}' includes '{entry}'. A "
            f"'{COMMON_PREFIX}' entry names one file of LibreLane's common "
            f"library, which is a flat directory: {common_library()}."
        )
    path = common_directory().joinpath(requested)
    if not path.is_file():
        raise FlowSpecError(
            f"Workflow document '{name}' includes '{entry}', which LibreLane's "
            f"common library does not have. It declares: {common_library()}."
        )
    return str(path)


def common_library() -> list[str]:
    """
    Returns
    -------
    Every file the common library holds, for a message to name when a document
    asks for one it does not. Read from the installation rather than written
    out, so it is the library this LibreLane actually ships.
    """
    return sorted(
        entry.name
        for entry in common_directory().iterdir()
        if entry.name.endswith(_INCLUDE_EXTENSIONS)
    )


def _read_include(path: str, entry: str, name: str) -> ConfigSource:
    if not path.endswith(_INCLUDE_EXTENSIONS):
        raise FlowSpecError(
            f"Workflow document '{name}' includes '{entry}', which is not a "
            f"{', '.join(_INCLUDE_EXTENSIONS)} file. A document is written in "
            f"YAML or JSON."
        )
    try:
        return read_source(path)
    except OSError as e:
        raise FlowSpecError(
            f"Workflow document '{name}' includes '{entry}', which could not "
            f"be read: {e.strerror} ('{os.path.abspath(path)}')."
        ) from None


def _merge_include(
    merged: dict[str, Any],
    declared: dict[tuple[str, str], str],
    included: Mapping[str, Any],
    included_declared: Mapping[tuple[str, str], str],
    includer: str,
) -> None:
    """
    Merges one already-resolved include into the accumulator beside its
    siblings, refusing anything two of them both declare.
    """
    for key in _MAPPING_KEYS:
        section = included.get(key)
        if section is None:
            continue
        target = merged.setdefault(key, {})
        for entry, value in section.items():
            if _is_here_already(declared, included_declared, key, entry, includer):
                continue
            target[entry] = value
            declared[(key, entry)] = included_declared[(key, entry)]
    for key in _SCALAR_KEYS:
        if key not in included:
            continue
        if _is_here_already(declared, included_declared, key, key, includer):
            continue
        merged[key] = included[key]
        declared[(key, key)] = included_declared[(key, key)]
    for entry in included.get("config", []):
        name = _variable_name(entry)
        if name is None:
            # Not a declaration this can key on -- the model will say why.
            # Carried through so that it is the model that says it.
            merged.setdefault("config", []).append(entry)
            continue
        if _is_here_already(declared, included_declared, "config", name, includer):
            continue
        merged.setdefault("config", []).append(entry)
        declared[("config", name)] = included_declared[("config", name)]


def _is_here_already(
    declared: dict[tuple[str, str], str],
    incoming: Mapping[tuple[str, str], str],
    key: str,
    entry: str,
    includer: str,
) -> bool:
    """
    Returns
    -------
    Whether this declaration is one already merged, which is the answer for the
    file a diamond reaches down both its arms: one declaration arriving twice,
    to be written once and not merged twice. A ``config`` list would otherwise
    carry the variable two times over.

    Raises
    ------
    FlowSpecError
        If the key is here already but from another file, which is two
        declarations and not one. Asked this way -- by which file a declaration
        came from -- rather than by skipping the second reach of a file, so
        that an arm of a diamond which *overrides* the shared file collides
        with the arm that took it whichever order the two are written in.
    """
    origin = declared.get((key, entry))
    if origin is None:
        return False
    if origin == incoming[(key, entry)]:
        return True
    raise FlowSpecError(
        f"Workflow document '{includer}' includes '{origin}' and "
        f"'{incoming[(key, entry)]}', which both declare {_describe(key, entry)}. "
        f"Nothing orders one include above another, so which of the two is "
        f"meant is unanswerable. Declare it in '{includer}' itself, which "
        f"overrides both, or remove it from one of them."
    )


def _describe(key: str, entry: str) -> str:
    if key == "jobs":
        return f"job '{entry}'"
    if key == "config":
        return f"configuration variable '{entry}'"
    if key == "with":
        return f"a value for '{entry}'"
    if key == "resources":
        return f"resource pool '{entry}'"
    return f"'{key}'"


def _layer_own(
    merged: dict[str, Any],
    declared: dict[tuple[str, str], str],
    document: Mapping[str, Any],
    name: str,
) -> None:
    """
    Lays a document's own declarations over its includes'.

    Nothing here can clash: a document declaring a key its include declares is
    the override the feature exists for.
    """
    for key in _OWN_KEYS:
        if key in document:
            merged[key] = document[key]
    for key in _MAPPING_KEYS:
        section = document.get(key)
        if section is None:
            continue
        if not isinstance(section, Mapping):
            raise FlowSpecError(
                f"Workflow document '{name}' declares '{key}', which is "
                f"{type(section).__name__} rather than a mapping. A '{key}' "
                f"maps each name it declares to one value."
            )
        target = merged.setdefault(key, {})
        for entry, value in section.items():
            target[entry] = value
            declared[(key, entry)] = name
    for key in _SCALAR_KEYS:
        if key in document:
            merged[key] = document[key]
            declared[(key, key)] = name
    entries = document.get("config")
    if entries is not None:
        if not isinstance(entries, list):
            raise FlowSpecError(
                f"Workflow document '{name}' declares 'config', which is "
                f"{type(entries).__name__} rather than a list. A 'config' is "
                f"a list of the variables the document declares."
            )
        for entry in entries:
            _layer_own_variable(merged, declared, entry, name)


def _layer_own_variable(
    merged: dict[str, Any],
    declared: dict[tuple[str, str], str],
    entry: Any,
    name: str,
) -> None:
    """
    Adds one variable declaration, replacing the included one of that name.

    Replaced in place rather than appended, so that a document overriding one
    default does not move the variable to the end of a list its includes
    otherwise order.
    """
    section: list[Any] = merged.setdefault("config", [])
    variable = _variable_name(entry)
    if variable is None:
        section.append(entry)
        return
    for index, existing in enumerate(section):
        if _variable_name(existing) != variable:
            continue
        section[index] = entry
        declared[("config", variable)] = name
        return
    section.append(entry)
    declared[("config", variable)] = name


def _variable_name(entry: Any) -> str | None:
    """
    Returns
    -------
    The name a ``config`` entry declares, or ``None`` where it does not declare
    one this can key on. A malformed entry is carried into the merged document
    unkeyed, so that the model is what reports it and says why.
    """
    if not isinstance(entry, Mapping):
        return None
    name = entry.get("name")
    return name if isinstance(name, str) else None
