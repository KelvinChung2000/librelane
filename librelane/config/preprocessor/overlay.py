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
    """Promote the keys of every matching pdk::/scl:: section into the mapping.

    A section is a statement about the mapping that carried it, so its values
    override that mapping's plain values wherever the block is written: the
    matching sections are merged after the plain keys rather than in document
    order. Two matching sections at the same level are merged in the order they
    were written, and a section nested inside one is merged after it, so an
    ``scl::`` block inside a ``pdk::`` block wins over that block's own keys.

    A section matching neither the resolved PDK nor the resolved SCL is dropped
    along with everything under it, before any of it is resolved. A ``pdk::`` or
    ``scl::`` key whose value is not a mapping is not a section and is left
    alone.

    The caller expands each configuration source on its own, before the sources
    are layered, so that a section never outranks a source layered after the
    one that carried it.
    """

    result: dict[str, Any] = {}
    sections: list[Mapping[str, Any]] = []
    for key, value in mapping.items():
        if key.startswith("pdk::") and isinstance(value, Mapping):
            if fnmatch.fnmatch(pdk, key[len("pdk::") :]):
                sections.append(value)
            continue
        if key.startswith("scl::") and isinstance(value, Mapping):
            if scl is not None and fnmatch.fnmatch(scl, key[len("scl::") :]):
                sections.append(value)
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
    for section in sections:
        result.update(apply_overlays(section, pdk=pdk, scl=scl))
    return result
