# Copyright 2026 LibreLane Contributors
import types
from enum import Enum
from decimal import Decimal
from typing import Any, Union, get_args, get_origin

from pydantic_core import core_schema

from ..common import Path, TclUtils
from .legacy import Instance, Macro, Orientation
from .preprocessor import GlobMatch


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
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, types.UnionType) and type(None) in args:
        remaining = tuple(item for item in args if item is not type(None))
        if len(remaining) == 1:
            return remaining[0]
    return annotation


def _shape(value: Any, annotation: Any, split_strings: bool) -> Any:
    """Apply structural Tcl and glob coercion without validating scalars."""
    annotation = _unwrap_optional(annotation)
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (list, tuple):
        if split_strings and isinstance(value, str):
            value = value.split(",") if "," in value else TclUtils.split(value)
            if value and value[-1] == "":
                value.pop()
        if isinstance(value, (list, tuple)):
            if args and args[0] is Path:
                value = [
                    item
                    for entry in value
                    for item in (entry if isinstance(entry, GlobMatch) else [entry])
                ]
            if not args:
                return value
            item_type = args[0]
            return [_shape(item, item_type, split_strings) for item in value]
    elif origin is dict:
        if split_strings and isinstance(value, str):
            value = TclUtils.split(value)
        if split_strings and isinstance(value, list):
            if len(value) % 2:
                raise ValueError(f"uneven Tcl dictionary ({len(value)} components)")
            value = dict(zip(value[::2], value[1::2]))
        if isinstance(value, dict) and args:
            return {
                key: _shape(item, args[1], split_strings) for key, item in value.items()
            }
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        if isinstance(value, str):
            try:
                return annotation[value]
            except KeyError:
                pass
    elif annotation is Decimal and isinstance(value, float):
        # Preserve the legacy compiler's exact float-to-Decimal conversion.
        return Decimal(value)
    return value


__all__ = [
    "ByNameEnum",
    "GlobMatch",
    "Instance",
    "Macro",
    "Orientation",
    "Path",
    "_shape",
]
