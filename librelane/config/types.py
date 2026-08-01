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


def _parse_json(value: str) -> Any:
    """
    Parse text a source wrote as a JSON document, naming it if it will not.

    Parameters
    ----------
    value : str
        The text as the source wrote it. It is quoted back in the error
        because the key alone does not say which of several sources wrote the
        value that failed.
    """
    try:
        return json.loads(value, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise CoercionError(f"not valid JSON ({error}): {value}") from None


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
    parsed = _parse_json(value)
    if not isinstance(parsed, container):
        expected = "object" if container is dict else "array"
        raise CoercionError(f"not a JSON {expected}: {value}")
    return parsed


#: The origins whose values a source may have had to write as text.
_PRODUCT_ORIGINS = (list, tuple, dict)


def _product_origin(annotation: Any) -> Any:
    """The container an annotation builds, or ``None`` if it builds a scalar."""
    origin = get_origin(unwrap_annotated(annotation))
    return origin if origin in _PRODUCT_ORIGINS else None


def _sole_member(candidates: list, description: str, value: Any) -> Any:
    """
    The one union member a value's shape calls for.

    A value that fits several members is not resolved by picking one: the
    union declares both readings as equally intended, so there is nothing here
    that knows which was meant.

    Parameters
    ----------
    candidates : list
        The members whose shape the value could be read into.
    description : str
        What the value was read as, named as the source's own grammar names
        it, e.g. ``a JSON object``.
    value : Any
        The text as the source wrote it, quoted back for the same reason
        :func:`_parse_json` quotes it: the key alone does not say which of
        several layered sources wrote the value that failed.
    """
    if not candidates:
        raise CoercionError(f"no member of the union takes {description}: {value}")
    if len(candidates) > 1:
        members = ", ".join(str(unwrap_annotated(item)) for item in candidates)
        raise CoercionError(
            f"{description} fits more than one member of the union"
            f" ({members}), so it cannot be told which was meant: {value}"
        )
    return candidates[0]


def _shape_union(value: Any, args: tuple, syntax: CoercionSyntax) -> Any:
    """
    Shape a value towards the member of a union it was written as.

    A union is the one annotation that does not say on its own whether an
    incoming string is text or a document -- ``CLOCK_PORT`` is
    ``None | str | list[str]``, so both readings are declared. Left alone, the
    string reaches Pydantic, whose smart union keeps it a string and quietly
    makes ``'["a","b"]'`` the name of one clock port. The member is therefore
    chosen here, before validation, as it is for every other annotation.

    The syntaxes deliberately disagree on which members may claim a bare
    string, because their grammars do. Under JSON a value with no leading
    bracket is unambiguously not a document, so *any* scalar member may take
    it as written, exactly as a non-union scalar would -- a union offering
    ``int`` may not be stricter than ``int`` alone. Under Tcl every value is a
    word list, so a bare token and a one-word list are the same text, and only
    a declared ``str`` can claim it; a non-``str`` scalar cannot, because
    nothing distinguishes the two readings. ``None | int | list[str]``
    therefore reads ``4`` as the text ``'4'`` from the command line but as
    ``['4']`` from a ``.tcl`` file. No shipped variable has that shape; both
    cases are pinned in ``test/config/test_union_coercion.py``.
    """
    members = [member for member in args if member is not type(None)]
    products = [member for member in members if _product_origin(member)]
    if not products:
        # Nothing in the union has a syntax, so every member takes the value as
        # its source wrote it and the choice is Pydantic's to make.
        return value
    if not isinstance(value, str):
        # Already the shape it was written as, so there is no syntax to apply
        # and nothing that can fail -- but the member's own contents still need
        # shaping, or a union would skip the glob expansion and the exact
        # Decimal conversion the same product type gets on its own. A value
        # that fits no member, or fits several, is left for Pydantic: only a
        # parse has to commit to one member, and this is not a parse.
        if isinstance(value, Mapping):
            wanted: tuple = (dict,)
        elif isinstance(value, (list, tuple)):
            wanted = (list, tuple)
        else:
            return value
        matching = [item for item in products if _product_origin(item) in wanted]
        return _shape(value, matching[0], syntax) if len(matching) == 1 else value
    scalars = [member for member in members if not _product_origin(member)]
    if syntax is CoercionSyntax.JSON:
        if not value.strip().startswith(("[", "{")):
            # Not written as a document, so it is the text a scalar member
            # takes as written, exactly as a non-union scalar would.
            if scalars:
                return value
            raise CoercionError(
                f"no member of the union takes text, and this is not a JSON"
                f" array or object: {value}"
            )
        # The bracket committed the value to being a document. Reading the
        # text as a scalar when it fails to parse is the fallback this design
        # exists to remove.
        parsed = _parse_json(value)
        wanted = (dict,) if isinstance(parsed, dict) else (list, tuple)
        kind = "a JSON object" if isinstance(parsed, dict) else "a JSON array"
        member = _sole_member(
            [item for item in products if _product_origin(item) in wanted],
            kind,
            value,
        )
        return _shape(parsed, member, syntax)
    if syntax is CoercionSyntax.TCL:
        if any(unwrap_annotated(member) is str for member in members):
            # A union that declares ``str`` has declared the text itself. The
            # alias is unwrapped because ``Annotated[str, ...]`` is still a
            # string to every source; ``Path``, which is also an alias, is not.
            return value
        return _shape(value, _sole_member(products, "a Tcl word list", value), syntax)
    if scalars:
        return value
    raise CoercionError(
        f"no member of the union takes text, and this source carries a list as"
        f" a list: {value}"
    )


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
    if origin in (Union, types.UnionType):
        # Only a union of two or more members reaches here: _unwrap_optional
        # has already replaced a lone member's Optional with the member.
        return _shape_union(value, args, syntax)
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
