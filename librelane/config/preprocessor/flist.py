# Copyright 2026 LibreLane Contributors
import re
from typing import Any
from collections.abc import Mapping

FLIST_KEY = "VERILOG_FLIST_FILES"

# `+incdir+/some/path`, `+define+SOME_MACRO`. The directive name never contains
# a `+`, so anchoring on that keeps a value that does, such as
# `+define+A=B+C`, in one piece.
_DIRECTIVE = re.compile(r"^\+([^+]+)\+(.*)$")

_DIRECTIVE_TARGETS = {
    "incdir": "VERILOG_INCLUDE_DIRS",
    "define": "VERILOG_DEFINES",
}


def _append(mapping: dict[str, Any], key: str, value: str) -> None:
    """Add one entry to a list-valued key, which may not be a list yet.

    A list variable can be written as a bare string in a configuration file, so
    an existing scalar is widened rather than appended to.
    """
    existing = mapping.get(key)
    if existing is None:
        mapping[key] = [value]
    elif isinstance(existing, list):
        mapping[key] = list(existing) + [value]
    else:
        mapping[key] = [existing, value]


def _read_flist(path: str, into: dict[str, Any]) -> None:
    with open(path, encoding="utf8") as f:
        for line in f:
            entry = line.strip()
            if not entry:
                continue
            match = _DIRECTIVE.match(entry)
            if match is None:
                _append(into, "VERILOG_FILES", entry)
                continue
            directive, contents = match.groups()
            target = _DIRECTIVE_TARGETS.get(directive)
            if target is None:
                raise RuntimeError(
                    f"Unknown F-list directive '{directive}' in {path}: {entry}"
                )
            _append(into, target, contents)


def _flatten(value: Any) -> list[str]:
    if isinstance(value, list):
        return [entry for item in value for entry in _flatten(item)]
    return [str(value)]


def expand_flists(
    config_in: Mapping[str, Any],
    resolve_paths,
) -> dict[str, Any]:
    """Fold every ``VERILOG_FLIST_FILES`` entry into the keys it names.

    An F-list (``*.f``) is the file list format Verilog tools take on the
    command line. Each line is either a ``+incdir+`` or ``+define+`` directive
    or the path of a source file, and each becomes an entry in
    ``VERILOG_INCLUDE_DIRS``, ``VERILOG_DEFINES`` or ``VERILOG_FILES``
    respectively.

    Parameters
    ----------
    config_in
        The configuration as read, before any directives are resolved.
    resolve_paths
        Called with the raw value of ``VERILOG_FLIST_FILES`` to turn
        preprocessor directives such as ``dir::rtl/files.f`` into paths.

    Returns
    -------
    dict
        A copy of the configuration with the F-lists folded in and
        ``VERILOG_FLIST_FILES`` removed, since nothing downstream knows it.
    """
    if config_in.get(FLIST_KEY) is None:
        return dict(config_in)

    expanded = dict(config_in)
    for path in _flatten(resolve_paths(expanded.pop(FLIST_KEY))):
        _read_flist(path, expanded)
    return expanded
