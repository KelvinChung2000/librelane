# Copyright 2026 LibreLane Contributors
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
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


class CoercionSyntax(Enum):
    """
    How a string that reaches a list-, tuple- or dictionary-typed variable is
    written.

    This is a property of the source the value came from and not of the
    variable it was written for: a PDK's ``config.tcl`` holds Tcl text, a
    ``--config-override`` is text typed at a shell, and a YAML, JSON or Python
    mapping carries a list as a list. A variable's declared type says what the
    value has to end up as, never how it was written.
    """

    #: A Tcl word list: ``a 1 b 2`` is a two-entry dictionary and ``p q r`` a
    #: three-element list.
    TCL = "tcl"
    #: A JSON document, as :data:`librelane.cli.options.ConfigOverridesOption`
    #: has always documented a ``--config-override`` value to be.
    JSON = "json"
    #: Not written as a string at all. A string that reaches a product-typed
    #: variable from such a source is an error, not something to parse.
    TYPED = "typed"


#: Every source kind, mapped to the syntax its strings are written in.
#:
#: No kind maps to :attr:`CoercionSyntax.TCL`. A PDK's ``config.tcl`` is the
#: only Tcl there is, and it is not layered as a source: it is evaluated into an
#: environment and compiled in permissive mode, which is where its strings get
#: read as Tcl.
_SYNTAX_BY_KIND: Mapping[str, CoercionSyntax] = {
    "commandline": CoercionSyntax.JSON,
    "mapping": CoercionSyntax.TYPED,
    "json": CoercionSyntax.TYPED,
    "yaml": CoercionSyntax.TYPED,
}


@dataclass(frozen=True)
class ConfigSource:
    mapping: Mapping[str, Any]
    name: str
    kind: Literal["mapping", "json", "yaml", "commandline"]

    @property
    def syntax(self) -> CoercionSyntax:
        """The syntax in which this source's strings are written."""
        return _SYNTAX_BY_KIND[self.kind]


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
    raise ValueError(f"Unsupported configuration source '{path}'")
