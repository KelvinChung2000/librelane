# Copyright 2026 LibreLane Contributors


def test_every_registered_variable_builds_a_model_field():
    import librelane.steps  # noqa: F401
    from librelane.config import model_to_variables, variables_to_model
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

    # Anti-silent-shrinkage baseline for declarations reachable from the
    # registry. Update deliberately when adding/removing declarations.
    assert len(variables) == 373

    for index, legacy in enumerate(variables):
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
