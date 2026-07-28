# Copyright 2026 LibreLane Contributors
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from collections.abc import Mapping

import yaml


@dataclass(frozen=True)
class ConfigSource:
    mapping: Mapping[str, Any]
    name: str
    kind: Literal["mapping", "json", "yaml", "tcl"]


def read_source(
    source: Mapping[str, Any] | str | os.PathLike,
    *,
    yaml_loader,
) -> ConfigSource:
    """Read a non-Tcl source without preprocessing or validation."""
    if isinstance(source, Mapping):
        return ConfigSource(source, "<mapping>", "mapping")
    path = os.path.abspath(os.fspath(source))
    if path.endswith(".json"):
        with open(path, encoding="utf8") as stream:
            return ConfigSource(
                json.load(stream, parse_float=Decimal),
                path,
                "json",
            )
    if path.endswith((".yaml", ".yml")):
        with open(path, encoding="utf8") as stream:
            return ConfigSource(yaml.load(stream, Loader=yaml_loader), path, "yaml")
    if path.endswith(".tcl"):
        # Tcl needs process information and is evaluated by Config's two-pass
        # compatibility reader.
        return ConfigSource({}, path, "tcl")
    raise ValueError(f"Unsupported configuration source '{path}'")
