# Copyright 2026 LibreLane Contributors
"""
The PDK descriptor format: a typed, declarative replacement for the Tcl program
a PDK ships as ``libs.tech/librelane/config.tcl``.

An installed PDK variant carries one descriptor per layer::

    libs.tech/librelane/pdk.yaml           # the PDK
    libs.tech/librelane/<scl>/scl.yaml     # one per standard cell library
    libs.tech/librelane/<pad>/pad.yaml     # one per IO pad library, optional

Each is a YAML 1.2 document read the way every other non-Tcl source is read, so
a number written in one is a :class:`decimal.Decimal` and a list is a list.
Reading them is the whole of this module: the three are merged in order, later
layer winning, and the merge is also what says where each value came from --
the file that last wrote a key is its origin, with none of the environment
diffing the Tcl path needs to work that out.

The values are native, never Tcl text, which is why a descriptor is compiled
under strict typing: see :meth:`librelane.config.Config._Config__get_pdk_config`.
Strings may still carry the preprocessor's directives (``pdk_dir::``, ``ref::``,
``refg::``, ``expr::``), which is what makes a descriptor writable without
naming an installation path, and those are resolved here so that what this
returns has the same shape -- absolute paths, expanded globs -- as the
environment a ``config.tcl`` evaluates to. Interpolation is spelled ``$VAR``
inside one of those directives and nowhere else, so a string carrying ``${`` is
refused rather than passed through as the literal text it would otherwise
resolve to.

The format is specified in
``docs/superpowers/specs/2026-08-05-pdk-descriptor-format.md``.
"""

import os
from dataclasses import dataclass
from typing import Any, NoReturn
from collections.abc import Mapping

from librelane.config.loading import read_source
from librelane.config.preprocessor import Keys as SpecialKeys, resolve_symbols


#: The one descriptor format this version of LibreLane reads. A descriptor
#: declaring anything else is an error rather than something to read
#: optimistically: the point of a version is that a reader which does not know
#: it cannot know what it is missing.
FORMAT_VERSION = 1

#: Where descriptors live inside an installed PDK variant, mirroring the
#: ``config.tcl`` layout one-to-one so that the open_pdks fork adding them stays
#: additive.
_DESCRIPTOR_DIR = ("libs.tech", "librelane")

_PDK_DESCRIPTOR = "pdk.yaml"
_SCL_DESCRIPTOR = "scl.yaml"
_PAD_DESCRIPTOR = "pad.yaml"


@dataclass(frozen=True)
class PdkDescriptor:
    """
    What reading a PDK's descriptors resolves to.

    Attributes
    ----------
    values : dict[str, Any]
        The merged environment, with every directive resolved. Keys no variable
        declares are carried as they were written, exactly as the Tcl path
        carries whatever a ``config.tcl`` happened to set: they may belong to a
        step or a flow that is not loaded.
    scl : str
        The standard cell library whose descriptor was read.
    pad : str | None
        The IO pad library whose descriptor was read, if the PDK has one.
    origins : dict[str, str]
        Each key mapped to ``<pdk>``, ``<scl>`` or ``<pad>`` -- the layer that
        last wrote it.
    """

    values: dict[str, Any]
    scl: str
    pad: str | None
    origins: dict[str, str]


def descriptor_path(pdkpath: str) -> str:
    """
    Parameters
    ----------
    pdkpath : str
        An installed PDK variant's directory.

    Returns
    -------
    str
        Where that variant's PDK-layer descriptor would be. Its existence is
        what selects the descriptor path over the Tcl one.
    """
    return os.path.join(pdkpath, *_DESCRIPTOR_DIR, _PDK_DESCRIPTOR)


def _fail(errors: list[str]) -> NoReturn:
    # Imported here rather than at the top of the module because
    # 'librelane.config.config' imports this one: a descriptor that cannot be
    # read is an invalid PDK configuration and raises what every other way of
    # saying that raises, and being the module that defines it does not make it
    # importable from here.
    from librelane.config.config import InvalidConfig

    raise InvalidConfig("PDK descriptor", [], errors)


def _read_document(path: str) -> Mapping[str, Any]:
    document = read_source(path).mapping
    if document is None:
        # An empty file parses as None, which is a legal YAML document and not
        # a legal descriptor.
        document = {}
    if not isinstance(document, Mapping):
        _fail([f"'{path}' does not hold a mapping."])
    return document


def _read_meta(document: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    meta = document.get("meta")
    if not isinstance(meta, Mapping):
        _fail([f"'{path}' has no 'meta' section."])
    version = meta.get("format")
    if version != FORMAT_VERSION:
        _fail(
            [
                f"'{path}' declares descriptor format '{version}', which this "
                f"version of LibreLane cannot read: it reads format "
                f"{FORMAT_VERSION}."
            ]
        )
    return meta


def _reject_brace_interpolation(document: Mapping[str, Any], path: str) -> None:
    """
    Refuse a descriptor string containing ``${``.

    Interpolation is spelled ``$VAR`` and exists only inside a ``ref::``,
    ``refg::`` or ``expr::`` value: there is no bare-string interpolation and no
    brace form. A ``${VAR}`` is therefore not a directive the reader fails to
    understand -- it is a string that resolves to itself, so a path written that
    way would reach a tool as the eleven literal characters ``${PDKPATH}`` and
    the first thing to notice would be the tool. It can only be a
    mistranscribed directive, which makes it worth an error at load rather than
    a value nobody looks at twice.

    Every string is checked, including those inside lists and dictionary
    values, because a directive is legal wherever a string is. ``meta`` is not:
    it describes the descriptor rather than configuring anything, and nothing
    resolves directives in it.
    """
    errors: list[str] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, str):
            if "${" in value:
                errors.append(
                    f"'{path}' writes '${{' in '{where}': {value!r}. "
                    f"Interpolation is spelled '$VAR', and only inside a "
                    f"'ref::', 'refg::' or 'expr::' value -- there is no "
                    f"'${{VAR}}' form, and this would be read as literal text."
                )
        elif isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{where}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")

    for key, value in document.items():
        if key == "meta":
            continue
        walk(value, str(key))

    if errors:
        _fail(errors)


def _validate_scls(meta: Mapping[str, Any], librelane_dir: str, path: str) -> None:
    """
    Check ``meta.scls`` against the standard cell libraries actually installed.

    The list is what a caller reads to offer a choice of libraries -- ``--scl``,
    the documentation, a tool listing what a PDK supports -- so a list that does
    not describe the tree is a broken PDK and not a detail to discover later,
    when a library it names turns out to have no descriptor.
    """
    declared = meta.get("scls")
    if declared is None:
        _fail([f"'{path}' does not declare 'meta.scls'."])
    if not isinstance(declared, list) or not all(
        isinstance(name, str) for name in declared
    ):
        _fail([f"'{path}' declares a 'meta.scls' that is not a list of names."])

    installed = set()
    for name in os.listdir(librelane_dir):
        if os.path.exists(os.path.join(librelane_dir, name, _SCL_DESCRIPTOR)):
            installed.add(name)

    if set(declared) == installed:
        return

    errors = []
    for name in sorted(set(declared) - installed):
        errors.append(
            f"'{path}' declares the standard cell library '{name}', which has "
            f"no '{name}/{_SCL_DESCRIPTOR}'."
        )
    for name in sorted(installed - set(declared)):
        errors.append(
            f"The standard cell library '{name}' has a descriptor but is not "
            f"declared in '{path}'."
        )
    _fail(errors)


def read_pdk_descriptor(
    pdkpath: str,
    *,
    pdk_root: str,
    pdk: str,
    scl: str | None = None,
    pad: str | None = None,
) -> PdkDescriptor | None:
    """
    Read an installed PDK's descriptors, if it ships any.

    Parameters
    ----------
    pdkpath : str
        The installed PDK variant's directory.
    pdk_root : str
        Where PDKs are installed.
    pdk : str
        The variant's name.
    scl : str | None
        A standard cell library named by the caller, which outranks the
        ``STD_CELL_LIBRARY`` the PDK's own descriptor defaults to.
    pad : str | None
        An IO pad library named by the caller, handled as ``scl`` is.

    Returns
    -------
    PdkDescriptor | None
        The merged environment, or ``None`` when the PDK ships no ``pdk.yaml``
        at all and is to be read as Tcl.

    Raises
    ------
    librelane.config.InvalidConfig
        If a descriptor exists but cannot be read: an unknown format version, a
        ``meta.scls`` that does not describe the tree, a named library with no
        descriptor, or a directive that does not resolve.
    """
    path = descriptor_path(pdkpath)
    if not os.path.exists(path):
        return None

    librelane_dir = os.path.dirname(path)
    pdk_document = _read_document(path)
    _validate_scls(_read_meta(pdk_document, path), librelane_dir, path)

    values: dict[str, Any] = {}
    origins: dict[str, str] = {}

    def layer(document: Mapping[str, Any], name: str, source: str) -> None:
        """
        Merge one descriptor over what is there, recording what it wrote.

        The values are checked here, before the merge, because that is the last
        point at which a bad string can be reported against the file that wrote
        it rather than against a key in a merged environment.
        """
        _reject_brace_interpolation(document, source)
        for key, value in document.items():
            if key == "meta":
                continue
            values[key] = value
            origins[key] = name

    layer(pdk_document, "<pdk>", path)

    scl_name = scl or values.get(SpecialKeys.scl)
    if scl_name is None:
        _fail([f"'{path}' does not set '{SpecialKeys.scl}'."])
    scl_path = os.path.join(librelane_dir, str(scl_name), _SCL_DESCRIPTOR)
    if not os.path.exists(scl_path):
        _fail([f"'{scl_path}' was not found."])
    scl_document = _read_document(scl_path)
    _read_meta(scl_document, scl_path)
    layer(scl_document, "<scl>", scl_path)

    pad_name = pad or values.get(SpecialKeys.pad)
    if pad_name is not None:
        pad_path = os.path.join(librelane_dir, str(pad_name), _PAD_DESCRIPTOR)
        if not os.path.exists(pad_path):
            _fail([f"'{pad_path}' was not found."])
        pad_document = _read_document(pad_path)
        _read_meta(pad_document, pad_path)
        layer(pad_document, "<pad>", pad_path)

    # The keys the process selection puts in scope rather than any file: a
    # descriptor writes 'pdk_dir::' and never an installation path, so these
    # have to be in the environment before anything is resolved against it.
    # They are written over the merged values, because a caller that named a
    # standard cell library outranks the default the PDK's descriptor carries.
    seeds: dict[str, Any] = {
        SpecialKeys.pdk_root: pdk_root,
        SpecialKeys.pdk: pdk,
        SpecialKeys.pdkpath: pdkpath,
        SpecialKeys.scl: scl_name,
    }
    if pad_name is not None:
        seeds[SpecialKeys.pad] = pad_name
    values.update(seeds)
    for key in seeds:
        # '<pdk>' names the layer and not the file, which is what a seed the
        # caller supplied belongs to: LibreLane has no name for the layer the
        # 'pdk', 'scl' and 'pad' arguments form. A descriptor that wrote the key
        # itself keeps its own attribution.
        origins.setdefault(key, "<pdk>")

    try:
        resolved = resolve_symbols(values, seeds)
    except (KeyError, TypeError, SyntaxError, ValueError) as error:
        _fail([f"Could not resolve the descriptors of '{pdk}': {error}"])

    return PdkDescriptor(resolved, str(scl_name), pad_name, origins)


__all__ = [
    "FORMAT_VERSION",
    "PdkDescriptor",
    "descriptor_path",
    "read_pdk_descriptor",
]
