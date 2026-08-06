# Copyright 2026 LibreLane Contributors
import ast
import pathlib


def _document_config_variables():
    """
    Every configuration variable a shipped workflow document accepts, in the
    order :meth:`librelane.flows.engine.Workflow.__init__` composes them.

    The engine's own variables come first because ``TOOLS`` is declared by the
    engine and by no document, exactly as ``Workflow.__init__`` and
    ``help_md_for_document`` compose the two halves. Until phase 5 this was read
    off the ``config_vars`` of the flow class the same name resolved to; the
    flow classes are gone and the documents that replaced them are what declare
    these variables now.
    """
    from librelane.flows import Flow
    from librelane.flows.engine import Workflow

    yield from Workflow.config_vars
    listed = Flow.factory.list()
    assert listed, "no workflow documents were registered"
    for flow_id in listed:
        document = Flow.factory.get(flow_id)
        assert document is not None, flow_id
        for declared in document.config:
            yield declared.to_variable()


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
    assert len(declarations) == 386

    for index, legacy in enumerate(declarations.values()):
        model = variables_to_model(f"HarvestedConfig{index}", [legacy])
        [round_tripped] = model_to_variables(model)
        assert round_tripped.name == legacy.name
        assert round_tripped.type == legacy.type
        assert round_tripped.default == legacy.default


def test_every_registered_variable_has_a_json_schema():
    """Acceptance gate for issue 599.

    A JSON Schema for the configuration is blocked behind this: 40 of the
    path-typed variables used to raise ``PydanticInvalidForJsonSchema``,
    because ``common.Path`` described itself with an opaque plain validator
    that told Pydantic nothing about the resulting type. Naming the offenders
    rather than counting them, so a regression says which variable broke.
    """
    import librelane.steps  # noqa: F401
    from librelane.config import variables_to_model
    from librelane.steps import Step

    variables = {}
    for step_id in Step.factory.list():
        for variable in Step.factory.get(step_id).config_vars:
            variables.setdefault(variable.name, variable)
    for variable in _document_config_variables():
        variables.setdefault(variable.name, variable)

    assert len(variables) > 300, "enumeration collapsed; the gate would be vacuous"

    failed = {}
    for name, variable in sorted(variables.items()):
        try:
            variables_to_model(
                f"JSONSchemaProbe_{name}", [variable]
            ).model_json_schema()
        except Exception as e:
            failed[name] = f"{type(e).__name__}: {str(e).splitlines()[0]}"

    assert failed == {}, (
        f"{len(failed)} of {len(variables)} variables cannot produce a JSON "
        f"schema: {failed}"
    )


def test_every_step_and_document_config_model_has_a_json_schema():
    """The per-variable gate above would not catch a model whose *combination*
    of fields is undescribable.

    A step carries its combination as a nested ``Config`` model. A document
    carries no model at all: the engine builds one per run out of its declared
    variables and its own, so the model is built the same way here.
    """
    import librelane.steps  # noqa: F401
    from librelane.config import variables_to_model
    from librelane.flows import Flow
    from librelane.flows.engine import Workflow
    from librelane.steps import Step

    failed = {}
    for step_id in Step.factory.list():
        try:
            Step.factory.get(step_id).Config.model_json_schema()
        except Exception as e:
            failed[step_id] = f"{type(e).__name__}: {str(e).splitlines()[0]}"
    listed = Flow.factory.list()
    assert listed, "no workflow documents were registered"
    for flow_id in listed:
        document = Flow.factory.get(flow_id)
        assert document is not None, flow_id
        variables = [
            *Workflow.config_vars,
            *(declared.to_variable() for declared in document.config),
        ]
        try:
            variables_to_model(
                f"DocumentConfig_{flow_id}", variables
            ).model_json_schema()
        except Exception as e:
            failed[flow_id] = f"{type(e).__name__}: {str(e).splitlines()[0]}"

    assert failed == {}, f"config models without a JSON schema: {failed}"


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


def test_builtin_steps_use_typed_declarations():
    """
    Swept ``librelane/flows/classic.py`` too until phase 5 deleted it. The
    shipped flows are YAML documents now, which have no Python declaration to
    sweep: ``FlowSpec`` parses their ``config`` block into typed declarations at
    load, and ``test/flows/test_documents.py`` is what exercises that.
    """
    import librelane

    package = pathlib.Path(librelane.__file__).parent
    paths = list((package / "steps").rglob("*.py"))
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
