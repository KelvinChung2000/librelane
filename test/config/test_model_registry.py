# Copyright 2026 LibreLane Contributors
import ast
import pathlib


def test_every_registered_variable_builds_a_model_field():
    import librelane.steps  # noqa: F401
    from librelane.config import BaseConfigModel, model_to_variables, variables_to_model
    from librelane.steps import Step

    declarations = {}
    for step_id in Step.factory.list():
        step = Step.factory.get(step_id)
        assert step is not None
        assert issubclass(step.Config, BaseConfigModel)
        assert step._get_config_model() is step.Config

        bridged = model_to_variables(step.Config)
        assert [
            (item.name, item.type, item.default, item.description, item.units, item.pdk)
            for item in step.config_vars
        ] == [
            (item.name, item.type, item.default, item.description, item.units, item.pdk)
            for item in bridged
        ]
        for variable in step.config_vars:
            key = (
                variable.name,
                repr(variable.type),
                repr(variable.default),
                variable.description,
                variable.units,
                variable.pdk,
                repr(
                    [
                        item if isinstance(item, str) else item[0]
                        for item in variable.deprecated_names
                    ]
                ),
            )
            declarations[key] = variable

    # Anti-silent-shrinkage baseline for distinct fields reachable from the
    # registry. Update deliberately when adding/removing or changing fields.
    assert len(declarations) == 353

    for index, legacy in enumerate(declarations.values()):
        model = variables_to_model(f"HarvestedConfig{index}", [legacy])
        [round_tripped] = model_to_variables(model)
        assert round_tripped.name == legacy.name
        assert round_tripped.type == legacy.type
        assert round_tripped.default == legacy.default


def test_registered_variable_defaults_match_legacy_compiler():
    import librelane.steps  # noqa: F401
    from pydantic import ValidationError

    from librelane.common import GenericDict
    from librelane.config import variables_to_model
    from librelane.config.legacy import MissingRequiredVariable
    from librelane.steps import Step

    variables = []
    seen = set()
    for step_id in Step.factory.list():
        step = Step.factory.get(step_id)
        assert step is not None
        for variable in step.config_vars:
            if id(variable) not in seen:
                seen.add(id(variable))
                variables.append(variable)

    differences = []
    for index, legacy in enumerate(variables):
        try:
            _, old_value = legacy.compile(
                GenericDict(),
                [],
                permissive_typing=True,
            )
            old_result = ("value", old_value, type(old_value))
        except MissingRequiredVariable:
            old_result = ("missing",)

        model = variables_to_model(f"DefaultConfig{index}", [legacy])
        try:
            instance = model.model_validate(
                {},
                context={"permissive": True},
            )
            new_value = instance[legacy.name]
            new_result = ("value", new_value, type(new_value))
        except ValidationError as error:
            if any(item["type"] == "missing" for item in error.errors()):
                new_result = ("missing",)
            else:
                new_result = ("error", str(error))

        if old_result != new_result:
            differences.append((legacy.name, old_result, new_result))

    assert differences == []


def test_builtin_steps_and_classic_flow_use_typed_declarations():
    import librelane

    package = pathlib.Path(librelane.__file__).parent
    paths = list((package / "steps").rglob("*.py"))
    paths.append(package / "flows" / "classic.py")
    legacy_declarations = []
    static_mapping_accesses = []

    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Variable"
            ):
                legacy_declarations.append(f"{path}:{node.lineno}")
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
                and node.value.attr == "config"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                static_mapping_accesses.append(f"{path}:{node.lineno}")

    assert legacy_declarations == []
    assert static_mapping_accesses == []


def test_classic_flow_config_model_bridge():
    from librelane.config import BaseConfigModel, model_to_variables
    from librelane.flows.classic import Classic

    assert issubclass(Classic.Config, BaseConfigModel)
    assert [(item.name, item.type, item.default) for item in Classic.config_vars] == [
        (item.name, item.type, item.default)
        for item in model_to_variables(Classic.Config)
    ]
