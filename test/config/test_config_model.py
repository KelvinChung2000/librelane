# Copyright 2026 LibreLane Contributors
from decimal import Decimal

import pytest


def test_typed_model_mapping_and_schema():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        TRACKS: list[str] = variable(
            description="Routing tracks.",
            pdk=True,
            units="µm",
        )
        MODE: str = variable("default", description="Mode.")

    model = Example.model_validate(
        {"TRACKS": "a b"},
        context={"permissive": True},
    )
    assert model.TRACKS == ["a", "b"]
    assert model["MODE"] == "default"
    assert dict(model.items()) == {"TRACKS": ["a", "b"], "MODE": "default"}
    schema = Example.model_json_schema()
    assert schema["properties"]["TRACKS"]["pdk"] is True
    assert schema["properties"]["TRACKS"]["units"] == "µm"


def test_per_key_permissiveness_and_smart_union():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        COUNT: int = variable(description="Count.")
        VALUE: int | bool | str = variable(description="Value.")

    model = Example.model_validate(
        {"COUNT": "2", "VALUE": "true"},
        context={"permissive_keys": {"COUNT"}},
        strict=True,
    )
    assert model.COUNT == 2
    assert model.VALUE == "true"  # issue #993


def test_translating_deprecated_name():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        CELLS: list[str] | None = variable(
            None,
            description="Cells.",
            deprecated_names=[("CELL_PREFIX", lambda value: [f"{value}*"])],
        )

    model = Example.model_validate({"CELL_PREFIX": "buf"})
    assert model.CELLS == ["buf*"]


def test_shape_coercion_nested_tcl_dictionary():
    from librelane.common import Path
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        LIBS: dict[str, list[Path]] = variable(description="Libraries.")

    with pytest.raises(ValueError, match="uneven Tcl dictionary"):
        Example.model_validate(
            {"LIBS": "corner a.lib orphan"},
            context={"permissive": True},
        )


def test_diagnostics_collection():
    from librelane.config import Diagnostic, DiagnosticSet, Severity

    diagnostics = DiagnosticSet(
        [
            Diagnostic(Severity.WARNING, "unknown-key", "warning"),
            Diagnostic(Severity.ERROR, "type-error", "error"),
        ]
    )
    assert [item.message for item in diagnostics.warnings()] == ["warning"]
    assert diagnostics.rendered_errors() == ["error"]


def test_decimal_is_preserved():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        VALUE: Decimal = variable(description="Value.")

    value = Example.model_validate({"VALUE": Decimal("1.25")}, strict=True)
    assert value.VALUE == Decimal("1.25")


def test_legacy_validator_survives_model_bridge():
    from librelane.config import BaseConfigModel, model_to_variables, variable

    def validate(variable, value, warnings):
        warnings.append(variable.name)
        return value + 1

    class Example(BaseConfigModel):
        VALUE: int = variable(
            1,
            description="Value.",
            validator=validate,
        )

    [legacy] = model_to_variables(Example)
    warnings = []
    assert legacy.validator(legacy, 2, warnings) == 3
    assert warnings == ["VALUE"]


def test_model_bridge_can_select_only_declared_fields():
    from librelane.config import BaseConfigModel, model_to_variables, variable

    class Parent(BaseConfigModel):
        PARENT: int = variable(1, description="Parent.")

    class Child(Parent):
        CHILD: int = variable(2, description="Child.")

    assert [item.name for item in model_to_variables(Child)] == ["PARENT", "CHILD"]
    assert [
        item.name for item in model_to_variables(Child, include_inherited=False)
    ] == ["CHILD"]
