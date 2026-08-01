# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from librelane.config.loading.sources import ConfigSource


@dataclass(frozen=True)
class LayeredMapping:
    mapping: dict[str, Any]
    provenance: dict[str, str]


def layer_mappings(sources: Iterable[ConfigSource]) -> LayeredMapping:
    """Layer sources in order, recording the last source for each top-level key.

    Only top-level keys are layered, so a source whose ``pdk::``/``scl::``
    sections have not been expanded yet contributes those sections as keys of
    their own and not the values inside them. A caller that wants a section's
    values ranked against the other sources has to expand each source with
    :func:`librelane.config.preprocessor.apply_overlays` first, which needs the
    resolved PDK and SCL.
    """
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for source in sources:
        for key, value in source.mapping.items():
            merged[key] = value
            provenance[key] = source.name
    return LayeredMapping(merged, provenance)
