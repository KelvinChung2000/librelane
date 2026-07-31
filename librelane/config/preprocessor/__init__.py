# Copyright 2026 LibreLane Contributors
from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

from librelane.config.preprocessor.flist import FLIST_KEY, expand_flists
from librelane.config.preprocessor.graph import SymbolCycleError, resolve_symbols
from librelane.config.preprocessor.legacy import Expr
from librelane.config.preprocessor.overlay import apply_overlays
from librelane.config.preprocessor.resolve import (
    GlobMatch,
    parse_directive,
    resolve_directive,
)


Keys = SimpleNamespace(
    pdk_root="PDK_ROOT",
    pdk="PDK",
    pdkpath="PDKPATH",
    scl="STD_CELL_LIBRARY",
    pad="PAD_CELL_LIBRARY",
    design_dir="DESIGN_DIR",
)
PROCESS_INFO_ALLOWLIST = [Keys.pdk, Keys.scl, Keys.pad, f"{Keys.scl}_OPT"]


def process_string(value: str, symbols: Mapping[str, Any]) -> Any:
    # Keep the directly-callable compatibility facade's historical exception
    # wording and zero-glob fallback. The staged loader uses the AST resolver.
    from librelane.config.preprocessor.legacy import (
        process_string as legacy_process_string,
    )

    return legacy_process_string(value, symbols)


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
    "SymbolCycleError",
    "apply_overlays",
    "expand_flists",
    "parse_directive",
    "preprocess_dict",
    "process_config_dict",
    "process_string",
    "resolve_symbols",
]
