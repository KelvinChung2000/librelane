# Copyright 2026 LibreLane Contributors
from dataclasses import dataclass
from typing import Any
from collections.abc import Iterable

from librelane.config.loading.sources import CoercionSyntax, ConfigSource


@dataclass(frozen=True)
class LayeredMapping:
    """
    Attributes
    ----------
    mapping : dict[str, Any]
        The layered values.
    provenance : dict[str, str]
        Each key mapped to the name of the source that last wrote it.
    syntax : dict[str, CoercionSyntax]
        Each key mapped to the syntax that source writes its strings in.
    """

    mapping: dict[str, Any]
    provenance: dict[str, str]
    syntax: dict[str, CoercionSyntax]


def layer_mappings(sources: Iterable[ConfigSource]) -> LayeredMapping:
    """Layer sources in order, recording the last source for each top-level key.

    Only top-level keys are layered, so a source whose ``pdk::``/``scl::``
    sections have not been expanded yet contributes those sections as keys of
    their own and not the values inside them. A caller that wants a section's
    values ranked against the other sources has to expand each source with
    :func:`librelane.config.preprocessor.apply_overlays` first, which needs the
    resolved PDK and SCL.

    Both facts recorded about a key -- who wrote it and in what syntax -- are
    about its last writer, because both describe the value that survived.
    """
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    syntax: dict[str, CoercionSyntax] = {}
    for source in sources:
        for key, value in source.mapping.items():
            merged[key] = value
            provenance[key] = source.name
            # Overwritten with the value, and for the same reason the origin
            # is: how a string is written is a fact about whoever wrote it, so
            # a key a later source rewrote is no longer in the earlier one's
            # syntax.
            syntax[key] = source.syntax
    return LayeredMapping(merged, provenance, syntax)
