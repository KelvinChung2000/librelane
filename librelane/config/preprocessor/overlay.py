# Copyright 2026 LibreLane Contributors
import fnmatch
from typing import Any
from collections.abc import Mapping


def apply_overlays(
    mapping: Mapping[str, Any],
    *,
    pdk: str,
    scl: str | None,
) -> dict[str, Any]:
    """Merge matching pdk::/scl:: sections in document order."""

    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if key.startswith("pdk::") and isinstance(value, Mapping):
            if fnmatch.fnmatch(pdk, key[len("pdk::") :]):
                result.update(apply_overlays(value, pdk=pdk, scl=scl))
            continue
        if key.startswith("scl::") and isinstance(value, Mapping):
            if scl is not None and fnmatch.fnmatch(scl, key[len("scl::") :]):
                result.update(apply_overlays(value, pdk=pdk, scl=scl))
            continue
        if isinstance(value, Mapping):
            result[key] = apply_overlays(value, pdk=pdk, scl=scl)
        elif isinstance(value, list):
            result[key] = [
                apply_overlays(item, pdk=pdk, scl=scl)
                if isinstance(item, Mapping)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
