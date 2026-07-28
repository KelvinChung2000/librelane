# Copyright 2026 LibreLane Contributors
import json
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast
from collections.abc import Iterator, Mapping

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    TypeAdapter,
    ValidationInfo,
    create_model,
    model_validator,
)
from pydantic.fields import FieldInfo, PydanticUndefined

from .diagnostics import DiagnosticSet
from .types import _shape


BaseConfigModelT = TypeVar("BaseConfigModelT", bound="BaseConfigModel")


@dataclass(frozen=True)
class _DeprecatedNames:
    items: tuple[Any, ...]


@dataclass(frozen=True)
class _LegacyValidator:
    callback: Any


class BaseConfigModel(BaseModel, Mapping[str, Any]):
    """Immutable typed configuration with a compatibility Mapping facade."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        arbitrary_types_allowed=True,
        populate_by_name=True,
        validate_default=True,
    )
    _diagnostics: DiagnosticSet = PrivateAttr(default_factory=DiagnosticSet)
    _meta: Any = PrivateAttr(default=None)
    _deprecation_warnings_enabled: ClassVar[bool] = False

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Normalise declared defaults to the shape of their annotation.

        Defaults are written as plain literals -- ``0`` for a ``Decimal``, a
        list for a tuple -- but ``validate_default`` holds them to the same
        strict rules as user input, so shape them the way input is shaped.
        """
        rebuild = False
        for field in cls.model_fields.values():
            if field.default is PydanticUndefined or field.default is None:
                continue
            shaped = _shape(field.default, field.annotation, split_strings=False)
            if shaped is not field.default:
                field.default = shaped
                rebuild = True
        if rebuild:
            cls.model_rebuild(force=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_shapes(cls, data: Any, info: ValidationInfo) -> Any:
        if not isinstance(data, Mapping):
            return data
        context = info.context or {}
        permissive = bool(context.get("permissive"))
        permissive_keys = frozenset(context.get("permissive_keys", ()))
        output = dict(data)
        for name, field in cls.model_fields.items():
            deprecated = next(
                (item for item in field.metadata if isinstance(item, _DeprecatedNames)),
                None,
            )
            if name not in output and deprecated is not None:
                for alias in deprecated.items:
                    alias_name = alias
                    translate = None
                    if not isinstance(alias, str):
                        alias_name, translate = alias
                    if alias_name not in output:
                        continue
                    output[name] = output[alias_name]
                    if translate is not None and output[name] is not None:
                        output[name] = translate(output[name])
                    break
            if name not in output:
                continue
            value = output[name]
            if value is None:
                continue
            shaped = _shape(
                value,
                field.annotation,
                split_strings=permissive or name in permissive_keys,
            )
            if name in permissive_keys and not permissive:
                shaped = TypeAdapter(field.annotation).validate_python(shaped)
            output[name] = shaped
        return output

    @property
    def diagnostics(self) -> DiagnosticSet:
        return self._diagnostics

    @property
    def meta(self) -> Any:
        return self._meta

    def attach_context(
        self: "BaseConfigModelT",
        *,
        diagnostics: DiagnosticSet | None = None,
        meta: Any = None,
    ) -> "BaseConfigModelT":
        if diagnostics is not None:
            object.__setattr__(self, "_diagnostics", diagnostics)
        if meta is not None:
            object.__setattr__(self, "_meta", meta)
        return self

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return iter(self.to_raw_dict())

    def __len__(self) -> int:
        return len(self.to_raw_dict())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            other_raw = (
                other.to_raw_dict(include_meta=False)
                if hasattr(other, "to_raw_dict")
                else dict(other)
            )
            return self.to_raw_dict() == other_raw
        return super().__eq__(other)

    def to_raw_dict(self, include_meta: bool = False) -> dict[str, Any]:
        output = self.model_dump(mode="python", round_trip=True, warnings=False)
        if include_meta and self.meta is not None:
            output["meta"] = self.meta
        return output

    def dumps(self, include_meta: bool = False, **kwargs) -> str:
        kwargs.setdefault("indent", 4)
        return json.dumps(self.to_raw_dict(include_meta), default=str, **kwargs)


def variable(
    default: Any = PydanticUndefined,
    *,
    description: str,
    units: str | None = None,
    pdk: bool = False,
    unsafe: bool = False,
    deprecated_names: list[Any] | None = None,
    validator: Any = None,
    **kwargs,
) -> Any:
    """Declare a typed LibreLane configuration field."""
    deprecated_names = deprecated_names or []
    plain_aliases = [
        item if isinstance(item, str) else item[0] for item in deprecated_names
    ]
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra.update(
        {
            "units": units,
            "pdk": pdk,
            "unsafe": unsafe,
            "deprecated_names": plain_aliases,
        }
    )
    field = Field(
        default,
        description=description,
        json_schema_extra=extra,
        **kwargs,
    )
    field.metadata.append(_DeprecatedNames(tuple(deprecated_names)))
    if validator is not None:
        field.metadata.append(_LegacyValidator(validator))
    return field


def _field_for_legacy(variable: Any) -> FieldInfo:
    default = variable.default
    if default is None and not variable.optional:
        default = PydanticUndefined
    elif default is not PydanticUndefined:
        default = _shape(default, variable.type, split_strings=True)
    aliases = [
        item if isinstance(item, str) else item[0] for item in variable.deprecated_names
    ]
    validation_alias = (
        AliasChoices(variable.name, *aliases) if aliases else variable.name
    )
    field = Field(
        default,
        description=variable.description,
        validation_alias=validation_alias,
        json_schema_extra={
            "units": variable.units,
            "pdk": variable.pdk,
            "unsafe": False,
            "deprecated_names": aliases,
        },
    )
    field.metadata.append(_DeprecatedNames(tuple(variable.deprecated_names)))
    field.metadata.append(_LegacyValidator(variable.validator))
    return field


def extend_model(
    name: str,
    base: type[BaseConfigModel],
    fields: Mapping[str, tuple[Any, Any]],
) -> type[BaseConfigModel]:
    """
    Derive a model from ``base`` with additional, dynamically named fields.

    :param name: The name of the generated model.
    :param base: The model to derive from.
    :param fields: Field names mapped to ``(annotation, field)`` pairs, in the
        same shape Pydantic's ``create_model`` expects.
    """
    # create_model's overloads describe fields as keyword arguments written out
    # by hand, which a computed set of names cannot be.
    return cast(
        type[BaseConfigModel],
        create_model(name, __base__=base, **fields),  # type: ignore[call-overload]
    )


def variables_to_model(
    name: str,
    variables: list[Any],
    base: type[BaseConfigModel] = BaseConfigModel,
) -> type[BaseConfigModel]:
    return extend_model(
        name,
        base,
        {item.name: (item.type, _field_for_legacy(item)) for item in variables},
    )


def model_to_variables(
    model: type[BaseConfigModel],
    *,
    include_inherited: bool = True,
) -> list[Any]:
    from .legacy import Variable

    result = []
    for name, field in model.model_fields.items():
        if not include_inherited and name not in model.__annotations__:
            continue
        extra: dict[str, Any] = (
            field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        )
        deprecated = next(
            (
                item.items
                for item in field.metadata
                if isinstance(item, _DeprecatedNames)
            ),
            tuple(extra.get("deprecated_names", [])),
        )
        default = None if field.default is PydanticUndefined else field.default
        validator = next(
            (
                item.callback
                for item in field.metadata
                if isinstance(item, _LegacyValidator)
            ),
            None,
        )
        kwargs = {}
        if validator is not None:
            kwargs["validator"] = validator
        result.append(
            Variable(
                name,
                field.annotation,
                field.description or "",
                default=default,
                deprecated_names=list(deprecated),
                units=extra.get("units"),
                pdk=bool(extra.get("pdk")),
                **kwargs,
            )
        )
    return result


__all__ = [
    "BaseConfigModel",
    "model_to_variables",
    "variable",
    "variables_to_model",
]
