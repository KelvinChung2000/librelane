# Copyright 2026 LibreLane Contributors
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from collections.abc import Mapping

import yaml
from yamlcore import CCoreLoader


class OpenLaneYAMLLoader(CCoreLoader):
    """
    A YAML 1.2 core loader that reads floats as ``Decimal``, so that a value
    written in a configuration file round-trips exactly rather than through
    binary floating point.

    Lives here rather than in :mod:`librelane.config.config` because it is a
    source-reading concern that :func:`read_source` needs, and
    :mod:`librelane.config.config` imports this package.
    """

    def construct_yaml_float(self, node: yaml.ScalarNode) -> Decimal:  # type: ignore
        value = str(self.construct_scalar(node))
        value = value.replace("_", "").lower()
        sign = +1
        if value[0] == "-":
            sign = -1
        if value[0] in "+-":
            value = value[1:]
        if value == ".inf":
            return sign * Decimal("Infinity")
        elif value == ".nan":
            return Decimal("nan")
        else:
            return sign * Decimal(value)

    def __init__(self, stream) -> None:
        super().__init__(stream)
        self.add_constructor(
            "tag:yaml.org,2002:float",
            constructor=OpenLaneYAMLLoader.construct_yaml_float,
        )


@dataclass(frozen=True)
class ConfigSource:
    mapping: Mapping[str, Any]
    name: str
    kind: Literal["mapping", "json", "yaml", "tcl"]


def read_source(
    source: Mapping[str, Any] | str | os.PathLike,
    *,
    yaml_loader=OpenLaneYAMLLoader,
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
