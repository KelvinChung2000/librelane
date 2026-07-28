# Copyright 2026 LibreLane Contributors
from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

from .graph import SymbolCycleError, resolve_symbols
from .legacy import Expr
from .overlay import apply_overlays
from .resolve import GlobMatch, parse_directive, resolve_directive


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
    from .legacy import process_string as legacy_process_string

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
    processed = process_config_dict(config_dict, seeds)
    return extract_process_vars(processed) if only_extract_process_info else processed


__all__ = [
    "Expr",
    "GlobMatch",
    "Keys",
    "SymbolCycleError",
    "apply_overlays",
    "parse_directive",
    "preprocess_dict",
    "process_config_dict",
    "process_string",
    "resolve_symbols",
]
