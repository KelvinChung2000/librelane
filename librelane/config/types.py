# Copyright 2026 LibreLane Contributors
import dataclasses
import json
import types
from collections.abc import Mapping
from enum import Enum
from decimal import Decimal
from typing import Any, Union, get_args, get_origin

from pydantic import TypeAdapter
from pydantic_core import core_schema

from librelane.common import Path, TclUtils, is_path_annotation, unwrap_annotated
from librelane.config.legacy import Instance, InstanceArray, Macro, Orientation
from librelane.config.loading.sources import CoercionSyntax
from librelane.config.preprocessor import GlobMatch


class CoercionError(ValueError):
    """
    A string that does not parse in the syntax its source writes.

    Raised rather than a plain :class:`ValueError` so that the caller that
    knows which key is being shaped can name it without also catching the
    :class:`pydantic.ValidationError` a nested value may raise -- Pydantic's is
    a ``ValueError`` too.
    """


class ByNameEnum(Enum):
    """Enum base that accepts member names as well as values."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validate(value):
            if isinstance(value, cls):
                return value
            try:
                return cls[value]
            except (KeyError, TypeError):
                return cls(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value.value,
                when_used="json",
            ),
        )


def _unwrap_optional(annotation: Any) -> Any:
    annotation = unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType) and type(None) in args:
        remaining = tuple(item for item in args if item is not type(None))
        if len(remaining) == 1:
            return remaining[0]
    return annotation


def _shape_tuple(value: Any, args: tuple, syntax: CoercionSyntax) -> tuple:
    """Shape a sequence into a tuple, honouring per-position element types."""
    if not args:
        return tuple(value)
    if Ellipsis in args:
        return tuple(_shape(item, args[0], syntax) for item in value)
    if len(value) != len(args):
        # Leave the arity mismatch for Pydantic to report.
        return tuple(value)
    return tuple(
        _shape(item, item_type, syntax) for item, item_type in zip(value, args)
    )


def _read_json(value: str, container: type) -> Any:
    """
    Read a whole product-typed value written as JSON.

    Parameters
    ----------
    value : str
        The text as the source wrote it.
    container : type
        ``list`` or ``dict``, whichever the annotation calls for. A JSON
        document that parses into anything else is rejected here rather than
        left to Pydantic, which would report it as a bare type error and say
        nothing about the syntax the value was read in.
    """
    try:
        parsed = json.loads(value, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise CoercionError(f"not valid JSON: {error}") from None
    if not isinstance(parsed, container):
        expected = "object" if container is dict else "array"
        raise CoercionError(f"not a JSON {expected}: {value}")
    return parsed


def _shape(value: Any, annotation: Any, syntax: CoercionSyntax) -> Any:
    """Apply structural string and glob coercion without validating scalars.

    Parameters
    ----------
    value : Any
        The value as its source supplied it.
    annotation : Any
        The declared type the value is being shaped towards.
    syntax : CoercionSyntax
        The syntax the source writes its strings in. Which one applies is
        decided by the source before the value is looked at, so a value that
        does not parse is an error and never something to try another syntax
        on.
    """
    annotation = _unwrap_optional(annotation)
    origin, args = get_origin(annotation), get_args(annotation)
    # A JSON document is parsed whole, so nothing inside one is text left to
    # parse: a string nested in it was written as a string and stays one.
    inner = CoercionSyntax.TYPED if syntax is CoercionSyntax.JSON else syntax
    if origin in (list, tuple):
        if isinstance(value, str):
            if syntax is CoercionSyntax.TCL:
                value = value.split(",") if "," in value else TclUtils.split(value)
                if value and value[-1] == "":
                    value.pop()
            elif syntax is CoercionSyntax.JSON:
                value = _read_json(value, list)
        if isinstance(value, (list, tuple)):
            if args and is_path_annotation(args[0]):
                value = [
                    item
                    for entry in value
                    for item in (entry if isinstance(entry, GlobMatch) else [entry])
                ]
            if origin is tuple:
                return _shape_tuple(value, args, inner)
            if not args:
                return list(value)
            return [_shape(item, args[0], inner) for item in value]
    elif origin is dict:
        if isinstance(value, str):
            if syntax is CoercionSyntax.TCL:
                value = TclUtils.split(value)
            elif syntax is CoercionSyntax.JSON:
                value = _read_json(value, dict)
        if syntax is CoercionSyntax.TCL and isinstance(value, list):
            if len(value) % 2:
                raise CoercionError(f"uneven Tcl dictionary ({len(value)} components)")
            value = dict(zip(value[::2], value[1::2]))
        if isinstance(value, dict) and args:
            return {key: _shape(item, args[1], inner) for key, item in value.items()}
    elif (
        isinstance(annotation, type)
        and dataclasses.is_dataclass(annotation)
        and isinstance(value, Mapping)
    ):
        # Dumping a configuration flattens dataclasses such as Macro back into
        # plain mappings, which strict typing will not accept on the way in.
        return TypeAdapter(annotation).validate_python(value)
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        if isinstance(value, str):
            try:
                return annotation[value]
            except KeyError:
                pass
    elif annotation is Decimal and isinstance(value, (int, float)):
        # Preserve the legacy compiler's exact float-to-Decimal conversion.
        # Booleans are ints in Python, but a boolean is never a quantity.
        if not isinstance(value, bool):
            return Decimal(value)
    return value


__all__ = [
    "ByNameEnum",
    "CoercionError",
    "CoercionSyntax",
    "GlobMatch",
    "Instance",
    "InstanceArray",
    "Macro",
    "Orientation",
    "Path",
    "_shape",
]
