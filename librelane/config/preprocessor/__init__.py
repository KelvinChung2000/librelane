# Copyright 2026 LibreLane Contributors
from typing import Any
from collections.abc import Mapping

from librelane.config.preprocessor.flist import FLIST_KEY, expand_flists


# ``Keys`` and ``PROCESS_INFO_ALLOWLIST`` are defined in ``expr`` and imported
# here rather than the other way round, and not because they belong there:
# ``expr.process_string`` reads ``Keys`` and this module already imports that
# module, so a definition here would have to be duplicated there to avoid an
# import cycle -- which is what it used to be, two identical copies that nothing
# kept in step.
#
# ``process_string`` is re-exported rather than wrapped. The wrapper this
# replaces did nothing but forward, behind a function-local import guarding
# against a cycle that does not exist: ``expr`` imports nothing from this
# package.
from librelane.config.preprocessor.expr import (
    PROCESS_INFO_ALLOWLIST,
    SPECIAL_KEYS,
    Expr,
    Keys,
    process_string,
)
from librelane.config.preprocessor.overlay import apply_overlays
from librelane.config.preprocessor.resolve import (
    GlobMatch,
    SymbolCycleError,
    parse_directive,
    resolve_directive,
    resolve_symbols,
)


def process_config_dict(
    config_in: Mapping[str, Any],
    exposed_variables: dict[str, Any],
) -> dict[str, Any]:
    pdk = str(exposed_variables.get(Keys.pdk) or "")
    scl = exposed_variables.get(Keys.scl)
    overlaid = apply_overlays(config_in, pdk=pdk, scl=scl)
    resolved = resolve_symbols(overlaid, exposed_variables)
    return {**exposed_variables, **resolved}


def extract_process_vars(config_in: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: config_in[key]
        for key in PROCESS_INFO_ALLOWLIST
        if config_in.get(key) not in (None, "")
    }


def preprocess_dict(
    config_dict: Mapping[str, Any],
    design_dir: str,
    only_extract_process_info: bool = False,
    pdk: str | None = None,
    pdkpath: str | None = None,
    scl: str | None = None,
    pad: str | None = None,
) -> dict[str, Any]:
    if None in (pdk, pdkpath, scl):
        if only_extract_process_info:
            pdkpath = ""
            scl = ""
            pdk = ""
        else:
            raise TypeError(
                "pdk, pdkpath and scl all need to be non-None unless "
                "only_extract_process_info is passed"
            )
    seeds = {
        Keys.pdk: pdk,
        Keys.pdkpath: pdkpath,
        Keys.scl: scl,
        Keys.pad: pad,
        Keys.design_dir: design_dir,
    }
    if only_extract_process_info:
        # This pass runs before the PDK is known and keeps only the PDK and SCL
        # keys, so reading the F-lists here would be work thrown away, against
        # seeds that cannot resolve a path under the PDK yet.
        return extract_process_vars(process_config_dict(config_dict, seeds))

    def resolve_flist_paths(raw: Any) -> Any:
        return process_config_dict({FLIST_KEY: raw}, seeds)[FLIST_KEY]

    return process_config_dict(expand_flists(config_dict, resolve_flist_paths), seeds)


__all__ = [
    "Expr",
    "FLIST_KEY",
    "GlobMatch",
    "Keys",
    "SPECIAL_KEYS",
    "SymbolCycleError",
    "apply_overlays",
    "expand_flists",
    "parse_directive",
    "preprocess_dict",
    "process_config_dict",
    "process_string",
    # With 'GlobMatch' and 'parse_directive' above it: librelane.state.state
    # imports all three together, from this package, to resolve a directive in
    # a state file.
    "resolve_directive",
    "resolve_symbols",
]
