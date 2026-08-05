#!/usr/bin/env python3
# Copyright 2026 LibreLane Contributors
"""One-time converter from a PDK's ``config.tcl`` tree to a descriptor tree.

Reads an installed PDK variant's Tcl configuration -- ``libs.tech/librelane/``
or ``libs.tech/openlane/`` -- and writes the v1 descriptors specified in
``docs/superpowers/specs/2026-08-05-pdk-descriptor-format.md``::

    libs.tech/librelane/pdk.yaml
    libs.tech/librelane/<scl>/scl.yaml
    libs.tech/librelane/<pad>/pad.yaml

This is a repo tool and is deliberately not part of the wheel: it is the
bootstrap for the PDKs LibreLane ships and the documented ramp for a
proprietary PDK, whose owner runs it once and commits the result. Nothing at
runtime reads a ``config.tcl`` once the descriptors exist.
"""

import argparse
import os
import sys
from decimal import Decimal
from functools import lru_cache
from pathlib import PurePath
from typing import Any
from collections.abc import Iterable, Mapping, Sequence

import yaml

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from librelane.common.tcl import TclUtils
from librelane.config.descriptor import FORMAT_VERSION
from librelane.config.flow import pdk_variables, scl_variables, pad_variables
from librelane.config.loading.sources import read_source
from librelane.config.model import variables_to_model
from librelane.config.pdk_compat import migrate_old_config
from librelane.config.variable import Variable

# Private because they are migrations, not API: nothing outside the
# configuration system should be applying them. This tool is the exception the
# removal plan (W7) names -- once the Tcl path is deleted these move here as
# private copies, because a descriptor never needs them again.
from librelane.config.validation import (
    _migrate_diode_strategy,
    _prepare_deprecated_names,
)
from librelane.config.diagnostics import DiagnosticSet


#: Set by the loader from the PDK selection, never read out of a descriptor.
#: ``STD_CELL_LIBRARY`` is not here: the spec makes it the descriptor's own
#: statement of which library is the default.
SEED_KEYS = frozenset({"PDK_ROOT", "PDK", "PDKPATH"})


class ConversionError(Exception):
    pass


class Report:
    """Warnings and counters for one PDK variant's conversion."""

    def __init__(self, variant: str) -> None:
        self.variant = variant
        self.warnings: list[str] = []
        self.unresolved_paths = 0
        self.skipped_scls: dict[str, str] = {}

    def warn(self, message: str) -> None:
        # Deduplicated: a layer is typed more than once -- for emission and for
        # the merge check -- and the same complaint reported twice reads as two
        # problems.
        if message not in self.warnings:
            self.warnings.append(message)


# --------------------------------------------------------------------------
# Declared variables
# --------------------------------------------------------------------------


@lru_cache(1)
def declared_pdk_variables() -> dict[str, Variable]:
    """Every variable a PDK layer may set, by name.

    The three models in ``librelane.config.flow`` plus whatever the steps
    declare ``pdk=True``, which is where two thirds of them live -- ``LIB``,
    ``LAYERS_RC``, the ``PDN_*`` family and the cell lists are all a step's.
    Mirrors how ``Config.__load_dict`` builds ``flow_pdk_vars``, except that it
    unions over every registered step rather than one flow's, because a
    descriptor is written once and read by flows this process never loads.
    """
    # Importing this registers the steps of every installed
    # 'librelane_plugin_*' package, which is how a proprietary PDK's own
    # 'pdk=True' variables become visible to the converter. Without it they
    # would be unclaimed keys and dropped.
    import librelane.plugins  # noqa: F401
    from librelane.steps import Step

    declared: dict[str, Variable] = {}
    for variable in pdk_variables + scl_variables + pad_variables:
        declared[variable.name] = variable
    for id in Step.factory.list():
        step = Step.factory.get(id)
        if step is None:
            continue
        for variable in step.get_all_config_variables():
            if variable.pdk and variable.name not in declared:
                declared[variable.name] = variable
    return declared


@lru_cache(1)
def deprecated_pdk_names() -> frozenset[str]:
    """Every spelling a PDK variable has been retired under."""
    return frozenset(
        name if isinstance(name, str) else name[0]
        for variable in declared_pdk_variables().values()
        for name in variable.deprecated_names
    )


@lru_cache(None)
def _coercion_model(name: str) -> Any:
    """A one-field model, so a key is typed without its neighbours.

    A PDK layer is a fragment -- the standard cell library supplies half of
    what the PDK's own file does not -- so validating one against the whole
    variable list reports every variable the *other* layers were going to
    supply as missing and returns nothing at all. One field at a time asks the
    only question conversion has: what does this variable's declared type make
    of this string?
    """
    return variables_to_model("PdkImport", [declared_pdk_variables()[name]])


def coerce_typed(name: str, value: Any) -> Any:
    """Validate a value that arrived already typed, as a descriptor's has.

    The reading the loader gives a descriptor: no permissive fallback, so a
    string reaching a list-typed variable is an error rather than something to
    split on whitespace.
    """
    validated = _coercion_model(name).model_validate(
        {name: value},
        context={"permissive": False, "syntaxes": {}},
        # 'strict' tracks 'permissive' the way 'validate_mapping' pairs them,
        # so this is the same judgement the loader will pass.
        strict=True,
    )
    return getattr(validated, name)


def coerce(name: str, value: Any) -> Any:
    """Read one Tcl string as its variable's declared type.

    ``permissive=True`` is what puts :class:`CoercionSyntax.TCL` in play, which
    is the whole point: it is how ``a 1 b 2`` becomes a two-entry dictionary
    and ``p q r`` a three-element list. The descriptor records the result, so
    the loader never has to.

    The legacy per-variable validator hooks are deliberately *not* run here. A
    validator normalises a value on the way into a configuration and the loader
    still runs it on what a descriptor holds; running it at conversion time as
    well would apply it twice.
    """
    model = _coercion_model(name)
    validated = model.model_validate(
        {name: _decimalize(value)},
        context={"permissive": True, "syntaxes": {}},
        strict=False,
    )
    return getattr(validated, name)


def _decimalize(value: Any) -> Any:
    """Read a Python ``float`` as the decimal it was written as.

    Everything a ``config.tcl`` sets arrives as a string, so the only floats
    here are the constants :func:`migrate_old_config` assigns in Python --
    ``CLOCK_TRANSITION_CONSTRAINT = 0.15`` and its neighbours. Coercing one
    straight to ``Decimal`` keeps the binary expansion, and
    ``Decimal(0.15)`` is 0.1499999999999999944488848768742172978818416595458984375.

    That number cannot be written down in a descriptor in any case: the loader
    builds a ``Decimal`` and multiplies it by its sign, which rounds to the
    28 digits of the default context, so it reads back as something else no
    matter how it is spelled. Emitting 0.15 -- what the source says, to the
    17 significant figures a float carries -- is both the honest value and the
    only one that survives a round trip.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return {key: _decimalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decimalize(item) for item in value]
    return value


# --------------------------------------------------------------------------
# Layer separation
# --------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf8") as stream:
        return stream.read()


def canonicalize(env: Mapping[str, Any]) -> dict[str, Any]:
    """Rename an evaluated environment onto the names in use today.

    Three migrations, in the order the configuration system runs them:
    :func:`migrate_old_config` (``TECH_LEF`` to ``TECH_LEFS``, the synthesised
    ``CELL_*`` globs, the per-PDK constants), ``DIODE_INSERTION_STRATEGY``
    becoming three keys, and each variable's ``deprecated_names``.

    Run on a whole environment rather than on a layer's diff, because
    :func:`migrate_old_config` reads ``PDK_ROOT``, ``PDK`` and
    ``STD_CELL_LIBRARY`` to synthesise paths, and because a rename seen against
    a complete mapping cannot be confused by a name a *later* layer happens to
    write. Layers are separated below by diffing environments that have all
    been through this, which is the same reason ``Config.__get_pdk_raw``
    compares migrated environments and not raw ones.
    """
    migrated = migrate_old_config(env)
    diagnostics = DiagnosticSet()
    _migrate_diode_strategy(migrated, diagnostics)
    # 'outranks': a PDK environment is merged by evaluation order and keeps no
    # record of which file wrote what, so a deprecated name that is present is
    # the later word -- sky130A's standard cell library writes SYNTH_TIEHI_PORT
    # over a PDK that writes SYNTH_TIEHI_CELL.
    _prepare_deprecated_names(
        migrated,
        list(declared_pdk_variables().values()),
        diagnostics,
        outranks=True,
    )
    # '_prepare_deprecated_names' copies a retired spelling's value onto the
    # current name and leaves the old key where it was, because the caller it
    # was written for drops every key no variable claims a moment later. Here
    # nothing does, and the spec is explicit that a descriptor carries current
    # names only.
    for name in deprecated_pdk_names():
        migrated.pop(name, None)
    return migrated


def claimed(env: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only what some variable declares, which is all a PDK can deliver.

    ``Config.__get_pdk_config`` compiles a PDK environment against the flow's
    ``pdk=True`` variables and returns those, so an unclaimed key -- sky130A's
    ``PROCESS``, ``GPIO_PADS_LEF``, ``CVC_SCRIPTS_DIR``, the ``*_OPT`` family
    the ``STD_CELL_LIBRARY_OPT`` hack computes -- already reaches no
    configuration. Emitting one would put a key in the resolved configuration
    that the Tcl path never produced.

    They are also, and not by coincidence, the keys that cannot be written
    relative to the PDK: they hold Tcl word lists of absolute paths, and a
    ``pdk_dir::`` directive addresses a whole value, not a word inside one.
    """
    declared = declared_pdk_variables()
    return {
        key: value
        for key, value in env.items()
        # PAD_CELL_LIBRARY is no variable's -- it is a selection key, like PDK
        # -- but it is how a descriptor names the pad library whose 'pad.yaml'
        # the loader reads next, so it is the one unclaimed key that stays.
        if key in declared or key == "PAD_CELL_LIBRARY"
    }


class TclTree:
    """The Tcl configuration of one installed PDK variant."""

    def __init__(self, pdk_root: str, pdk: str, report: Report) -> None:
        self.pdk_root = pdk_root
        self.pdk = pdk
        self.pdkpath = os.path.join(pdk_root, pdk)
        self.report = report

        self.tech_dir = self._find_tech_dir()
        self.config_tcl = os.path.join(self.tech_dir, "config.tcl")

        self.seed = {"PDK_ROOT": pdk_root, "PDK": pdk}
        self.default_env = self._eval(self.seed, self.config_tcl)

        default_scl = self.default_env.get("STD_CELL_LIBRARY")
        if default_scl is None:
            raise ConversionError(f"{self.config_tcl} sets no STD_CELL_LIBRARY.")
        self.default_scl: str = default_scl
        self.default_pad: str | None = self.default_env.get("PAD_CELL_LIBRARY")

    def _find_tech_dir(self) -> str:
        for name in ("librelane", "openlane"):
            candidate = os.path.join(self.pdkpath, "libs.tech", name)
            if os.path.isfile(os.path.join(candidate, "config.tcl")):
                return candidate
        raise ConversionError(
            f"Neither libs.tech/librelane/config.tcl nor "
            f"libs.tech/openlane/config.tcl was found under '{self.pdkpath}'."
        )

    def _eval(self, env: Mapping[str, Any], path: str) -> dict[str, Any]:
        return TclUtils._eval_env(env, _read(path))

    def library_dirs(self) -> list[str]:
        """Every subdirectory of the tech directory that carries a config.tcl."""
        return sorted(
            entry
            for entry in os.listdir(self.tech_dir)
            if os.path.isfile(os.path.join(self.tech_dir, entry, "config.tcl"))
        )

    def evaluate_scl(self, scl: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """The environment a PDK and one standard cell library evaluate to.

        The library is seeded rather than left to default because every PDK's
        own ``config.tcl`` reads ``STD_CELL_LIBRARY`` -- sky130A interpolates
        it into two dozen paths and ``source``\\ s the library's file itself --
        so "the PDK layer" is not something one evaluation can show you. It
        falls out of comparing these, one per library.

        ``STD_CELL_LIBRARY_OPT`` is seeded alongside it for the reason
        ``Config.__get_pdk_raw`` seeds it (issue #932): left to default it
        stays at the PDK's first library and drags ``TECH_LEF_OPT`` and its
        siblings back to that library's files.

        Returns
        -------
        tuple[dict[str, Any], dict[str, Any]]
            The environment before and after the library's own ``config.tcl``
            runs. The pair is what shows which keys that file wrote, which is
            one of the three things layer separation asks -- and the only one
            that can be answered for a PDK shipping a single library.
        """
        seed = dict(self.seed, STD_CELL_LIBRARY=scl, STD_CELL_LIBRARY_OPT=scl)
        before = self._eval(seed, self.config_tcl)
        after = self._eval(before, os.path.join(self.tech_dir, scl, "config.tcl"))
        return before, after

    def evaluate_pad(self, env: Mapping[str, Any], pad: str) -> dict[str, Any]:
        return self._eval(env, os.path.join(self.tech_dir, pad, "config.tcl"))


def separate_layers(
    tree: TclTree,
    scls: Sequence[str],
    envs: Mapping[str, Mapping[str, Any]],
    before: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split per-library environments into a shared layer and per-library ones.

    A key is the PDK's only when no library has a claim on it. A library claims
    a key three ways, and all three are needed:

    - its own ``config.tcl`` wrote or changed it;
    - the libraries disagree about its value;
    - its value names the library, which is how the PDK's own file marks
      everything it derived from ``$::env(STD_CELL_LIBRARY)``.

    Either of the first two would do on its own for a PDK that shipped several
    libraries and kept their files apart, and no PDK we ship does both.
    ihp-sg13g2 has one library, so nothing ever disagrees, and going by
    disagreement alone puts its ``CELL_LEFS`` and ``LIB`` in ``pdk.yaml``,
    where a second library would have to override them. sky130A's own file
    ``source``\\ s the library's, so by the time the library's file runs on its
    own it has nothing left to change, and going by authorship alone sees an
    empty layer.

    Whatever a library claims, *every* library writes: a key kept out of
    ``pdk.yaml`` has to be in each ``scl.yaml`` or reading one of them would
    lose it. :func:`check_merge` is what holds this to account.
    """
    claimed_by_library: set[str] = set()
    for scl in scls:
        env = envs[scl]
        for key, value in env.items():
            if key not in before[scl] or not _same(before[scl][key], value):
                claimed_by_library.add(key)
            elif _mentions(value, scl):
                claimed_by_library.add(key)
        for other in scls:
            for key in set(env) | set(envs[other]):
                if not _same(env.get(key), envs[other].get(key)):
                    claimed_by_library.add(key)

    first = envs[scls[0]]
    shared: dict[str, Any] = {
        key: value
        for key, value in first.items()
        if key not in claimed_by_library and all(key in envs[scl] for scl in scls[1:])
    }

    # Neither of these is something a comparison can recover -- every library's
    # environment names itself -- and both are how the loader finds the file to
    # read next.
    shared["STD_CELL_LIBRARY"] = tree.default_scl
    if tree.default_pad:
        shared["PAD_CELL_LIBRARY"] = tree.default_pad

    per_scl: dict[str, dict[str, Any]] = {}
    for scl in scls:
        env = envs[scl]
        per_scl[scl] = {
            key: value
            for key, value in env.items()
            if key not in shared or not _same(shared[key], value)
        }
    return shared, per_scl


def _mentions(value: Any, name: str) -> bool:
    """Whether a library's name appears anywhere inside a value."""
    if isinstance(value, PurePath):
        return name in str(value)
    if isinstance(value, str):
        return name in value
    if isinstance(value, Mapping):
        return any(
            _mentions(key, name) or _mentions(item, name) for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_mentions(item, name) for item in value)
    return False


def _same(left: Any, right: Any) -> bool:
    """Value equality that does not care that a Path is not a str."""
    return _comparable(left) == _comparable(right)


def _comparable(value: Any) -> Any:
    """One shape for values that differ only in how they were spelled.

    ``Decimal("13")``, ``13`` and ``13.0`` are the same number and a YAML
    round-trip may return any of them; a ``Path`` and the string it was built
    from name the same file. Neither difference is a conversion error, and
    comparing without collapsing them reports dozens that are not.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (Decimal, int, float)):
        return Decimal(str(value)).normalize()
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _comparable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparable(item) for item in value]
    return value


# --------------------------------------------------------------------------
# Typing and path un-resolution
# --------------------------------------------------------------------------


def type_layer(layer: Mapping[str, Any], report: Report, where: str) -> dict[str, Any]:
    """Coerce every key to its variable's declared type."""
    declared = declared_pdk_variables()
    typed: dict[str, Any] = {}
    for key, value in layer.items():
        if key not in declared:
            typed[key] = value
            continue
        try:
            typed[key] = coerce(key, value)
        except Exception as error:
            # Kept verbatim rather than dropped. The PDK wrote it, the loader
            # will read it under the same declaration and reach the same
            # verdict, and a value the Tcl path rejects is not one conversion
            # should quietly make disappear.
            report.warn(
                f"{where}: '{key}' is not a valid value for its declared type "
                f"({_first_line(error)}). Written as the PDK spelled it."
            )
            typed[key] = value
    return typed


def _first_line(error: Exception) -> str:
    """The one sentence in a Pydantic error that says what went wrong."""
    from pydantic import ValidationError

    if isinstance(error, ValidationError):
        return "; ".join(detail["msg"] for detail in error.errors(include_url=False))
    return str(error).strip().splitlines()[0]


def unresolve_paths(
    layer: Mapping[str, Any],
    pdkpath: str,
    report: Report,
    where: str,
) -> dict[str, Any]:
    """Rewrite absolute paths inside the PDK tree as ``pdk_dir::`` references.

    Every path in an evaluated environment is absolute, because that is what
    ``$::env(PDK_ROOT)/$::env(PDK)/...`` interpolates to. A descriptor that
    kept them would only load on the machine that converted it.

    Globs are *not* reconstructed. Tcl expanded them at evaluation time and
    there is no way back to the pattern that produced a given list; the
    expansion is emitted as a list, which is committed data the PDK build can
    regenerate. ``pdk_dir::`` still glob-expands on the way in, but
    :func:`resolve_directive` short-circuits on a path that exists, so a
    literal file name is returned as itself whatever characters it contains.
    """
    prefixes = {os.path.join(pdkpath, ""), os.path.join(os.path.realpath(pdkpath), "")}

    def rewrite(value: Any, key: str) -> Any:
        if isinstance(value, PurePath):
            value = str(value)
        if isinstance(value, Mapping):
            return {item: rewrite(entry, key) for item, entry in value.items()}
        if isinstance(value, (list, tuple)):
            return [rewrite(entry, key) for entry in value]
        if not isinstance(value, str):
            return value
        for prefix in prefixes:
            if value.startswith(prefix):
                relative = value[len(prefix) :]
                report.unresolved_paths += 1
                if not os.path.exists(value):
                    # An entry of a list that does not exist is dropped by the
                    # glob rather than kept, unlike a scalar, which falls back
                    # to its literal. Worth saying out loud: it is a value the
                    # Tcl path carries and the descriptor would not.
                    report.warn(
                        f"{where}: '{key}' references '{relative}', which is "
                        f"not in the PDK tree."
                    )
                return f"pdk_dir::{relative}"
        if os.path.isabs(value) and os.path.exists(value):
            report.warn(
                f"{where}: '{key}' holds the absolute path '{value}', which is "
                f"outside the PDK. Kept as-is; it will not survive being "
                f"installed anywhere else."
            )
        return value

    return {key: rewrite(value, key) for key, value in layer.items()}


# --------------------------------------------------------------------------
# Emission
# --------------------------------------------------------------------------


class DescriptorDumper(yaml.SafeDumper):
    """A dumper whose output the descriptor loader reads back unchanged.

    ``SafeDumper`` alone writes a ``Decimal`` as ``!!python/object/apply`` and
    a ``Path`` not at all, and it anchors any object it sees twice -- which for
    a PDK means every path string that two variables share.
    """

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_decimal(dumper: yaml.SafeDumper, data: Decimal) -> yaml.Node:
    # str() of a Decimal is the text it was built from, near enough: it keeps
    # the trailing zeroes of "1.60" and the exponent of "1E-10", both of which
    # the YAML 1.2 core schema reads back as the same number.
    #
    # The tag is chosen to match what the scalar resolves to on its own, or
    # PyYAML writes it out explicitly -- 'FP_TAPCELL_DIST: !!float "13"' -- and
    # a descriptor full of those is unreadable. Nothing is lost by letting
    # '13' be an integer: the loader coerces it to the variable's declared type
    # either way.
    text = str(data)
    if "." not in text and "e" not in text.lower() and "N" not in text:
        return dumper.represent_scalar("tag:yaml.org,2002:int", text)
    # PyYAML resolves scalars by YAML 1.1's rules, which want a decimal point
    # in an exponential's mantissa: it writes '1E-10' out as
    # "!!float '1E-10'", tag and all. '1.0E-10' is the same number to every
    # reader and reads as a number to both.
    mantissa, marker, exponent = text.partition("E")
    if marker and "." not in mantissa:
        text = f"{mantissa}.0{marker}{exponent}"
    return dumper.represent_scalar("tag:yaml.org,2002:float", text)


def _represent_path(dumper: yaml.SafeDumper, data: PurePath) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data))


DescriptorDumper.add_representer(Decimal, _represent_decimal)
DescriptorDumper.add_multi_representer(PurePath, _represent_path)


def _assert_no_brace_interpolation(document: Mapping[str, Any], path: str) -> None:
    """Refuse to write a descriptor string containing ``${``.

    Interpolation is spelled ``$VAR`` and only inside a ``ref::``, ``refg::`` or
    ``expr::`` value; there is no brace form, and the reader rejects one on
    sight. This tool never writes interpolation at all -- a path inside the PDK
    becomes ``pdk_dir::``, which needs none -- so anything matching here came
    out of the PDK's own Tcl as literal text, and it would be read as literal
    text. Caught at conversion, where the ``config.tcl`` that wrote it is still
    in hand, rather than at load.
    """
    offenders: list[str] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, str):
            if "${" in value:
                offenders.append(f"{where}: {value!r}")
        elif isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{where}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")

    for key, value in document.items():
        if key != "meta":
            walk(value, str(key))

    if offenders:
        raise ConversionError(
            f"'{path}' would contain '${{', which the descriptor reader "
            f"refuses: " + "; ".join(offenders)
        )


def write_descriptor(path: str, meta: Mapping[str, Any], values: Mapping[str, Any]):
    """Write one descriptor and read it back, asserting nothing changed."""
    document: dict[str, Any] = {"meta": dict(meta)}
    for key in sorted(values):
        document[key] = values[key]

    _assert_no_brace_interpolation(document, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8") as stream:
        yaml.dump(
            document,
            stream,
            Dumper=DescriptorDumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=100000,
        )

    reread = read_source(path).mapping
    if _comparable(reread) != _comparable(document):
        differing = sorted(
            key
            for key in set(document) | set(reread)
            if _comparable(document.get(key)) != _comparable(reread.get(key))
        )
        raise ConversionError(
            f"'{path}' did not survive a round-trip through the descriptor "
            f"loader. Keys that differ: {', '.join(differing)}"
        )


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------


def check_merge(
    scl: str,
    expected: Mapping[str, Any],
    layers: Iterable[Mapping[str, Any]],
    report: Report,
) -> None:
    """Assert the layers merge back into the environment they were split from.

    The gate the whole conversion rests on. Layer separation is a diff, and a
    diff can be wrong in ways nothing downstream would catch until a design
    hardened differently: a key credited to the PDK that one library disagrees
    about, or a rename applied to a layer whose value another layer overrides.
    """
    merged: dict[str, Any] = {}
    for layer in layers:
        merged.update(layer)
    for key in sorted(set(expected) | set(merged)):
        if key in SEED_KEYS:
            continue
        if not _same(merged.get(key), expected.get(key)):
            report.warn(
                f"<{scl}>: merging the descriptors gives "
                f"{key}={merged.get(key)!r}, but the Tcl configuration "
                f"evaluates to {expected.get(key)!r}."
            )


def check_resolution(
    tree: "TclTree",
    root: str,
    scl: str,
    expected: Mapping[str, Any],
    report: Report,
) -> None:
    """Read the written descriptors back and resolve them as the loader will.

    The end-to-end statement, and the only one that covers the two things the
    merge check cannot see: whether ``pdk_dir::`` finds the file the Tcl path
    interpolated an absolute path to, and whether the values survive being
    typed *without* the permissive reading -- a descriptor is a
    ``CoercionSyntax.TYPED`` source, so anything still relying on a Tcl word
    list being split would fail here and nowhere earlier.
    """
    from librelane.config.preprocessor import process_config_dict

    merged: dict[str, Any] = {}
    files = [os.path.join(root, "pdk.yaml"), os.path.join(root, scl, "scl.yaml")]
    if tree.default_pad:
        files.append(os.path.join(root, tree.default_pad, "pad.yaml"))
    for path in files:
        document = dict(read_source(path).mapping)
        document.pop("meta", None)
        merged.update(document)

    seeds = {
        "PDK_ROOT": tree.pdk_root,
        "PDK": tree.pdk,
        "PDKPATH": tree.pdkpath,
        "STD_CELL_LIBRARY": scl,
        "PAD_CELL_LIBRARY": tree.default_pad,
        "DESIGN_DIR": tree.pdkpath,
    }
    resolved = process_config_dict(merged, seeds)

    declared = declared_pdk_variables()
    for key in sorted(merged):
        if key in SEED_KEYS:
            continue
        value = resolved.get(key)
        if key in declared:
            try:
                value = coerce_typed(key, value)
            except Exception as error:
                report.warn(
                    f"<{scl}>: the descriptor's '{key}' does not validate "
                    f"without permissive typing: {_first_line(error)}"
                )
                continue
        if not _same(value, expected.get(key)):
            report.warn(
                f"<{scl}>: '{key}' resolves out of the descriptors as "
                f"{value!r}, but the Tcl configuration evaluates to "
                f"{expected.get(key)!r}."
            )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def resolve_variant(pdk_root: str, pdk: str) -> tuple[str, str, str | None]:
    """Locate a variant, and name the family it was found under.

    Accepts either the ``PDK_ROOT`` LibreLane itself would use -- the directory
    the variant sits directly inside -- or the Ciel home above it, since
    ``~/.ciel`` holds one directory per family and it is the path anyone
    actually has to hand.
    """
    pdk_root = os.path.abspath(os.path.expanduser(pdk_root))
    # Carrying a configuration is what makes a directory the variant, not
    # merely existing under that name: ihp-sg13g2's family directory and its
    # single variant are both called 'ihp-sg13g2', so '~/.ciel/ihp-sg13g2'
    # answers to the first test and holds no config.tcl at all.
    if _is_variant(os.path.join(pdk_root, pdk)):
        return pdk_root, pdk, os.path.basename(pdk_root)
    for entry in sorted(os.listdir(pdk_root)):
        candidate = os.path.join(pdk_root, entry)
        if _is_variant(os.path.join(candidate, pdk)):
            return candidate, pdk, entry
    raise ConversionError(f"The PDK variant '{pdk}' was not found under '{pdk_root}'.")


def _is_variant(path: str) -> bool:
    return any(
        os.path.isfile(os.path.join(path, "libs.tech", name, "config.tcl"))
        for name in ("librelane", "openlane")
    )


def convert(
    pdk_root: str,
    pdk: str,
    out: str | None,
    family: str | None,
) -> Report:
    pdk_root, pdk, found_family = resolve_variant(pdk_root, pdk)
    family = family or found_family
    report = Report(pdk)
    tree = TclTree(pdk_root, pdk, report)

    pads = [tree.default_pad] if tree.default_pad else []
    candidates = [entry for entry in tree.library_dirs() if entry not in pads]

    envs: dict[str, dict[str, Any]] = {}
    raw_envs: dict[str, dict[str, Any]] = {}
    before: dict[str, dict[str, Any]] = {}
    for scl in candidates:
        try:
            pdk_only, full = tree.evaluate_scl(scl)
            raw_envs[scl] = canonicalize(full)
            envs[scl] = claimed(raw_envs[scl])
            before[scl] = claimed(canonicalize(pdk_only))
        except Exception as error:
            # Overwhelmingly an install that fetched only some libraries: the
            # PDK's file globs libs.ref/<scl>/lef/*.lef and Tcl raises when
            # nothing matches. Converting for real needs every library present.
            report.skipped_scls[scl] = str(error).strip().splitlines()[0]
    if not envs:
        raise ConversionError(
            f"No standard cell library of '{pdk}' could be evaluated. "
            f"Tried: {', '.join(candidates)}."
        )
    scls = sorted(envs)

    shared, per_scl = separate_layers(tree, scls, envs, before)

    pad_layers: dict[str, dict[str, Any]] = {}
    for pad in pads:
        by_scl = {}
        for scl in scls:
            merged = claimed(canonicalize(tree.evaluate_pad(raw_envs[scl], pad)))
            by_scl[scl] = {
                key: value
                for key, value in merged.items()
                if key not in envs[scl] or not _same(envs[scl][key], value)
            }
        reference = by_scl[tree.default_scl if tree.default_scl in by_scl else scls[0]]
        for scl, layer in by_scl.items():
            if not _same(layer, reference):
                report.warn(
                    f"<{pad}>: the pad library's configuration depends on the "
                    f"standard cell library ({scl} differs from the default). "
                    f"Only the default library's reading was emitted."
                )
        pad_layers[pad] = reference

    typed_shared = type_layer(shared, report, "<pdk>")
    typed_scls = {
        scl: type_layer(layer, report, f"<{scl}>") for scl, layer in per_scl.items()
    }
    typed_pads = {
        pad: type_layer(layer, report, f"<{pad}>") for pad, layer in pad_layers.items()
    }

    resolved_envs = {}
    for scl in scls:
        expected = type_layer(envs[scl], report, f"<{scl}>")
        if tree.default_pad:
            expected.update(typed_pads[tree.default_pad])
        resolved_envs[scl] = expected
        check_merge(
            scl,
            expected,
            [typed_shared, typed_scls[scl]] + [typed_pads[pad] for pad in pads],
            report,
        )

    root = out or os.path.join(tree.pdkpath, "libs.tech", "librelane")
    root = os.path.abspath(os.path.expanduser(root))

    def emit(path: str, meta: Mapping[str, Any], layer: Mapping[str, Any], where: str):
        without_seeds = {
            key: value for key, value in layer.items() if key not in SEED_KEYS
        }
        write_descriptor(
            path, meta, unresolve_paths(without_seeds, tree.pdkpath, report, where)
        )

    meta: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "family": family,
        "variant": pdk,
        "scls": scls,
    }
    if pads:
        meta["pads"] = pads
    emit(os.path.join(root, "pdk.yaml"), meta, typed_shared, "<pdk>")
    for scl in scls:
        emit(
            os.path.join(root, scl, "scl.yaml"),
            {"format": FORMAT_VERSION},
            typed_scls[scl],
            f"<{scl}>",
        )
    for pad in pads:
        emit(
            os.path.join(root, pad, "pad.yaml"),
            {"format": FORMAT_VERSION},
            typed_pads[pad],
            f"<{pad}>",
        )

    for scl in scls:
        check_resolution(tree, root, scl, resolved_envs[scl], report)

    dropped = sorted(
        set(raw_envs[scls[0]]) - set(envs[scls[0]]) - SEED_KEYS - {"STD_CELL_LIBRARY"}
    )

    print(f"{pdk}: wrote {root}")
    print(f"  pdk layer:          {len(typed_shared)} keys")
    for scl in scls:
        print(f"  {scl}: {len(typed_scls[scl])} keys")
    for pad in pads:
        print(f"  {pad}: {len(typed_pads[pad])} keys")
    for scl, reason in sorted(report.skipped_scls.items()):
        print(f"  skipped {scl}: {reason}")
    print(f"  pdk_dir:: rewrites: {report.unresolved_paths}")
    print(f"  unclaimed, dropped: {len(dropped)} ({', '.join(dropped)})")
    print(f"  warnings:           {len(report.warnings)}")
    for warning in report.warnings:
        print(f"    - {warning}")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdk_import.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pdk-root",
        required=True,
        help="The directory holding the PDK variant, or the Ciel home above it.",
    )
    parser.add_argument("--pdk", required=True, help="The PDK variant, e.g. sky130A.")
    parser.add_argument(
        "--out",
        default=None,
        help="Write the libs.tech/librelane/ subtree here instead of into the PDK.",
    )
    parser.add_argument(
        "--family",
        default=None,
        help="The Ciel family name, when it cannot be read off the PDK root.",
    )
    arguments = parser.parse_args(argv)

    try:
        convert(arguments.pdk_root, arguments.pdk, arguments.out, arguments.family)
    except ConversionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    # Warnings do not fail the run. Every one this tool has raised so far is a
    # defect in the PDK it was handed -- a cell list the standard cell library
    # does not ship -- which the Tcl path rejects just as loudly, and which
    # converting is how you find.
    return 0


if __name__ == "__main__":
    sys.exit(main())
