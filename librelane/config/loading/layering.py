# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from .sources import ConfigSource


@dataclass(frozen=True)
class LayeredMapping:
    mapping: dict[str, Any]
    provenance: dict[str, str]


def layer_mappings(sources: Iterable[ConfigSource]) -> LayeredMapping:
    """Layer sources in order, recording the last source for each top-level key."""
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for source in sources:
        for key, value in source.mapping.items():
            merged[key] = value
            provenance[key] = source.name
    return LayeredMapping(merged, provenance)
