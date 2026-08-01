# Copyright 2026 LibreLane Contributors
from decimal import Decimal

import pytest
from pydantic import ValidationError


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


@pytest.mark.parametrize("given", [0, 10])
def test_whole_numbers_are_accepted_for_decimals(given):
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        VALUE: Decimal = variable(given, description="Value.")

    assert Example.model_validate({}, strict=True).VALUE == Decimal(given)
    assert Example.model_validate({"VALUE": given}, strict=True).VALUE == Decimal(given)


def test_booleans_are_not_accepted_for_decimals():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        VALUE: Decimal = variable(description="Value.")

    with pytest.raises(ValidationError):
        Example.model_validate({"VALUE": True}, strict=True)


def test_sequences_are_shaped_into_tuples():
    from librelane.config import BaseConfigModel, variable

    class Example(BaseConfigModel):
        OBSTRUCTIONS: list[tuple[str, Decimal, Decimal]] = variable(
            description="Obstructions.",
        )

    model = Example.model_validate(
        {"OBSTRUCTIONS": [["met2", 0, 1]]},
        strict=True,
    )
    assert model.OBSTRUCTIONS == [("met2", Decimal(0), Decimal(1))]


def test_dataclass_mappings_are_shaped_into_instances(tmp_path):
    """Dumping a config flattens Macros to dicts; re-validating must rebuild them."""
    from librelane.config import BaseConfigModel, variable
    from librelane.config.legacy import Macro

    gds = tmp_path / "a.gds"
    lef = tmp_path / "a.lef"
    gds.touch()
    lef.touch()

    class Example(BaseConfigModel):
        MACROS: dict[str, Macro] | None = variable(None, description="Macros.")

    raw = {
        "MACROS": {
            "spm": {
                "gds": [str(gds)],
                "lef": [str(lef)],
                "instances": {"i1": {"location": [1, 2], "orientation": "N"}},
            }
        }
    }
    model = Example.model_validate(raw, strict=True)
    assert isinstance(model.MACROS["spm"], Macro)
    assert [str(view) for view in model.MACROS["spm"].lef] == [str(lef)]

    round_tripped = Example.model_validate(model.to_raw_dict(), strict=True)
    assert isinstance(round_tripped.MACROS["spm"], Macro)


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


def test_a_path_variable_still_accepts_a_string_after_the_model_bridge(tmp_path):
    """
    Pydantic splits ``Annotated[T, m]`` into ``annotation=T`` and
    ``metadata=[m]``, so a bridge that read ``field.annotation`` alone handed
    `Variable` a bare ``pathlib.Path`` and lost the schema
    :data:`librelane.common.Path` carries. Rebuilding a model from that
    `Variable` and validating it strictly -- which is what
    :func:`librelane.config.validation.validate_mapping` does for a
    non-permissive configuration -- then rejected the string every
    command-line path argument arrives as.
    """
    from librelane.common import Path
    from librelane.config import BaseConfigModel, model_to_variables, variable
    from librelane.config.validation import validate_mapping

    class Example(BaseConfigModel):
        DIRECTORY: Path = variable(description="Somewhere.")

    variables = model_to_variables(Example)
    final, _ = validate_mapping(
        {"DIRECTORY": str(tmp_path)}, variables, permissive=False
    )

    assert final["DIRECTORY"] == tmp_path


def test_the_model_bridge_leaves_a_plain_annotation_plain():
    """
    ``variable()`` appends a deprecated-names marker to every field, and
    `Variable` carries deprecated names in a field of its own. Reattaching all
    metadata indiscriminately would make even a `bool` an ``Annotated`` alias,
    which the gating-variable checks in
    :class:`librelane.flows.SequentialFlow` and
    :mod:`librelane.flows.spec` compare against a bare type with ``==``.
    """
    from librelane.config import BaseConfigModel, model_to_variables, variable

    class Example(BaseConfigModel):
        FLAG: bool = variable(False, description="A flag.")

    [bridged] = model_to_variables(Example)

    assert bridged.type is bool


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


def test_validating_a_mapping_keeps_dataclass_values(tmp_path):
    """Steps read config values directly, so validation must not flatten them."""
    from librelane.config.legacy import Macro, Variable
    from librelane.config.validation import validate_mapping

    gds = tmp_path / "a.gds"
    lef = tmp_path / "a.lef"
    gds.touch()
    lef.touch()

    variables = [
        Variable("MACROS", dict[str, Macro] | None, "Macros.", default=None),
    ]
    final, diagnostics = validate_mapping(
        {
            "MACROS": {
                "spm": {
                    "gds": [str(gds)],
                    "lef": [str(lef)],
                    "instances": {"i1": {"location": [1, 2], "orientation": "N"}},
                }
            }
        },
        variables,
        permissive=True,
    )
    assert diagnostics.rendered_errors() == []
    assert isinstance(final["MACROS"]["spm"], Macro)


def test_instance_placement_fields_are_optional():
    """'Leave empty for automatic placement' -- so an empty instance is valid."""
    from pydantic import TypeAdapter

    from librelane.config.legacy import Instance

    instance = TypeAdapter(Instance).validate_python({})
    assert instance.location is None
    assert instance.orientation is None
