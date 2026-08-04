# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
The JSON Schema for a workflow document, for editors rather than for LibreLane.

LibreLane never validates a document against this schema.
:func:`librelane.engine.spec.load_flow_spec` validates against the pydantic
models, and :mod:`librelane.engine.spec_validation` and
:mod:`librelane.engine.selection_validation` then check everything a schema
cannot express. The schema exists so an editor can complete step ids and flag
the common mistakes while a document is being *written*, before it is ever run.

It is generated from the same models the loader validates against rather than
written by hand, so a field added to :class:`~librelane.engine.spec.JobSpec`
appears in it without anyone having to remember a second file. What is added on
top of pydantic's output is the part a type annotation cannot carry: the
registry enumerations, the predicate grammar, and the combinations of keys
:meth:`~librelane.engine.spec.FlowSpec._check_schedule_combinations` refuses.

One thing it deliberately does not say is that a document has a ``name`` and
``jobs``. Both are required of a document being *loaded* and neither is
required of one being *included*, and no keyword can tell which of the two a
file open in an editor is. A schema that guessed would flag every fragment as
malformed, so the requirement stays with the loader, which knows.

The enumerations are *this installation's*. ``steps`` and ``uses`` enumerate the
registries as they stand once every plugin has been imported, so a schema
generated where a plugin is installed accepts that plugin's steps and rejects
them where it is not -- which is exactly what the loader does with the same
document.

A document that satisfies this schema still has to load. Nothing here can say
that a ``needs`` names a declared job, that a cycle is a simple ring with one
gate, or that some job's required view is reachable; those are the loader's,
and it says them with better messages than a validator would.
"""

from typing import Any

from librelane.common.metrics import Metric
from librelane.engine.selection_validation import FRAMEWORK_METRICS

# The document's own rules, imported rather than restated: a key added to the
# reserved list in spec.py must not need a second edit here to be refused by the
# schema too.
from librelane.engine.spec import (
    _PRE_PASS_VALUE_KEY,
    _RESERVED_VALUE_KEYS,
    _VARIABLE_TYPES,
    FlowSpec,
)
from librelane.engine.spec_include import COMMON_PREFIX, INCLUDE_KEY, common_library
from librelane.jobs import Job, JobRegistry
from librelane.state import DesignFormat
from librelane.steps import Step


#: The dialect pydantic generates, and the one the ``$schema`` key declares.
#: Stated rather than left out, because a schema with no dialect is read as
#: whichever draft the consuming editor defaults to.
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: Mirrors ``librelane.engine.predicates._IDENTIFIER``: a bare configuration
#: variable name, which is the whole of a config term.
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"

#: An optionally signed integer or decimal literal, the right-hand side of a
#: metric term. Mirrors ``predicates._INTEGER_LITERAL`` and
#: ``predicates._DECIMAL_LITERAL``.
_LITERAL = r"[+-]?[0-9]+(\.[0-9]+)?"

#: Mirrors ``predicates._OPERATORS``. Ordered longest-first so that ``<=`` is
#: never matched as ``<`` with a stray ``=`` left over.
_OPERATOR = r"(==|!=|<=|>=|<|>)"

#: A metric term: three whitespace-separated tokens. The metric name is any
#: run of non-whitespace, because a corner-qualified name carries ``:``
#: characters of its own.
_METRIC_TERM = rf"metric::\S+\s+{_OPERATOR}\s+{_LITERAL}"


def _conjunction(term: str) -> str:
    """
    Parameters
    ----------
    term : str
        The pattern one term of the conjunction matches.

    Returns
    -------
    An anchored pattern matching one or more ``term`` joined by the literal
    ``and``, which is the whole of the predicate grammar
    :func:`librelane.engine.predicates.parse_predicate` accepts.
    """
    return rf"^\s*{term}(\s+and\s+{term})*\s*$"


#: ``if`` conjoins config terms and metric terms alike.
_IF_PATTERN = _conjunction(f"({_IDENTIFIER}|{_METRIC_TERM})")

#: ``until`` conjoins metric terms only: a configuration variable is constant
#: across a loop's passes.
_UNTIL_PATTERN = _conjunction(_METRIC_TERM)

#: A bare metric name and a keep direction. The lookahead is
#: ``_check_select_shape``'s refusal of a ``metric::`` prefix: ``select`` admits
#: nothing but metrics, so a disambiguating prefix has nothing to disambiguate
#: from.
_SELECT_PATTERN = r"^\s*(?!metric::)\S+\s+(min|max)\s*$"


def _node(owner: dict[str, Any], key: str) -> dict[str, Any]:
    """
    Parameters
    ----------
    owner : dict[str, Any]
        A generated object schema.
    key : str
        The property to annotate.

    Returns
    -------
    The subschema pydantic generated for ``key``, for the caller to add
    keywords to in place.
    """
    properties = owner["properties"]
    assert key in properties, (
        f"'{key}' is not a property of the generated schema, so the models and "
        f"this generator have diverged. Generated: {sorted(properties)}."
    )
    return properties[key]


def _branch(node: dict[str, Any], type: str) -> dict[str, Any]:
    """
    Parameters
    ----------
    node : dict[str, Any]
        The subschema of a property.
    type : str
        The JSON type whose branch the caller means to constrain.

    Returns
    -------
    The branch a value of ``type`` is validated against. An optional field is
    generated as ``anyOf: [{"type": <type>}, {"type": "null"}]``, and a
    keyword written beside that ``anyOf`` would constrain nothing: ``pattern``
    on the union is satisfied by the null branch. It belongs on the branch.
    """
    branches = node.get("anyOf")
    if branches is None:
        return node
    matching = [branch for branch in branches if branch.get("type") == type]
    assert len(matching) == 1, (
        f"expected exactly one '{type}' branch to constrain, found "
        f"{len(matching)} in {node}"
    )
    return matching[0]


def _present(key: str) -> dict[str, Any]:
    """
    Parameters
    ----------
    key : str
        The key whose presence is being tested.

    Returns
    -------
    A subschema matching an object that declares ``key`` with a value other
    than null. The models test ``is not None`` rather than membership, so a
    ``select: null`` written out in full is an absent ``select``, and a rule
    keyed on ``required`` alone would refuse a document the loader accepts.
    """
    return {"required": [key], "properties": {key: {"not": {"type": "null"}}}}


def _unreserved_keys() -> dict[str, Any]:
    """
    Returns
    -------
    The ``propertyNames`` constraint every block of configuration values
    carries: the keys that select the process, and so would override the
    command line rather than layer under it, are refused wherever a document
    could set them.
    """
    refused = sorted({*_RESERVED_VALUE_KEYS, _PRE_PASS_VALUE_KEY})
    return {"not": {"enum": refused}}


def _step_ids() -> list[str]:
    return sorted(Step.factory.list())


def _uses_values() -> list[str]:
    """
    Returns
    -------
    Every string a ``uses`` may name: ``job/provider`` for each registration,
    plus the bare id of each template that has a default provider to fall back
    on. Mirrors ``spec_validation._check_uses``.
    """
    values = {
        f"{registration.job}/{registration.provider}"
        for registration in JobRegistry.list()
    }
    for job_id in Job.factory.list():
        template = Job.factory.get(job_id)
        assert template is not None, "listed by the same factory"
        if template.default_provider is not None:
            values.add(job_id)
    return sorted(values)


def _source_keys() -> list[str]:
    """
    Returns
    -------
    Every key a ``source`` may name: a registered view, a registered metric, or
    one of the framework metrics nothing declares. Mirrors
    ``spec_validation._check_source_keys_resolve``.
    """
    return sorted(
        {*DesignFormat.factory.list(), *Metric.by_name, *FRAMEWORK_METRICS},
    )


def workflow_document_schema() -> dict[str, Any]:
    """
    Builds the JSON Schema for a workflow document against the registries as
    they stand in this process.

    Returns
    -------
    A JSON Schema document, ready to be serialized. Every call rebuilds it, so
    a plugin imported in between is reflected.
    """
    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DIALECT,
        **FlowSpec.model_json_schema(by_alias=True),
    }
    schema["title"] = "LibreLane workflow document"
    schema["description"] = (
        "A LibreLane flow declared as data: jobs, the 'needs' edges between "
        "them, and the configuration they read. Structure is checked here; "
        "whether the graph holds together is checked when LibreLane loads it."
    )

    job = schema["$defs"]["JobSpec"]
    variable = schema["$defs"]["VariableSpec"]

    _add_include(schema)
    _relax_document_requirements(schema)
    _annotate_flow(schema)
    _annotate_job(job)
    _annotate_variable(variable)
    job["allOf"] = _job_key_combinations()

    return schema


def _add_include(schema: dict[str, Any]) -> None:
    """
    Adds the one key pydantic cannot generate.

    ``include`` is not a field of :class:`~librelane.engine.spec.FlowSpec` and
    should not be: :mod:`librelane.engine.spec_include` resolves it into the
    document before a model is built, so a model carrying it would carry a key
    that never means anything by the time it could be read. An editor still has
    to know it is legal.
    """
    assert INCLUDE_KEY not in schema["properties"], (
        f"'{INCLUDE_KEY}' is generated now, so the model resolves its own "
        f"includes and this can go."
    )
    schema["properties"][INCLUDE_KEY] = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "uniqueItems": True,
        "description": (
            "Documents whose declarations this one reuses, each a path "
            f"relative to this file, an absolute path, or '{COMMON_PREFIX}' "
            f"and one of {common_library()}, which are the files LibreLane "
            "ships for documents to share. What they declare is merged "
            "underneath what this document declares, which overrides it; two "
            "of them declaring the same job, variable, value or pool is an "
            "error."
        ),
    }


def _relax_document_requirements(schema: dict[str, Any]) -> None:
    """
    Drops ``name`` and ``jobs`` from the required keys.

    They are required of a document being loaded and not of one being
    included, and which of the two a file is, is not a property of the file.
    Keeping them required would flag every fragment; the loader is where the
    requirement can be stated without guessing.
    """
    required = [
        key for key in schema.get("required", []) if key not in ("name", "jobs")
    ]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)


def _annotate_flow(schema: dict[str, Any]) -> None:
    _node(schema, "name").update(
        {
            "minLength": 1,
            "description": (
                "The name this document is registered and selected under: "
                "'librelane --flow <name>'. Required of a document being run, "
                "and ignored where a document is included by another."
            ),
        }
    )
    _node(schema, "description")["description"] = (
        "Prose describing the flow, shown wherever flows are listed. Ignored "
        "where a document is included by another, as 'name' is."
    )
    _node(schema, "with").update(
        {
            "description": (
                "Values for configuration variables, layered between the PDK "
                "and the design's own configuration, so a design always wins."
            ),
            "propertyNames": _unreserved_keys(),
        }
    )
    _node(schema, "config")["description"] = (
        "Configuration variables this document declares for itself, on top of "
        "the ones its steps declare."
    )
    _node(schema, "jobs")["description"] = (
        "The jobs, keyed by job id. A job that declares neither 'uses' nor "
        "'steps' runs the registered job template whose id is its key. A "
        "document being run has jobs, from here or from what it includes; one "
        "written to be included need not."
    )
    _branch(_node(schema, "final"), "string")["description"] = (
        "The job whose output state is the flow's final state. Absent, the "
        "final state is the join of every sink job."
    )
    capacities = _node(schema, "resources")
    capacities["description"] = (
        "Named resource pools, each capping how many jobs holding a seat in it "
        "run at once. A job names the pools it needs in its own 'resources'."
    )
    capacities["additionalProperties"] = {
        "description": (
            "A positive integer capacity, or the name of a configuration "
            "variable this document declares with type 'int'."
        ),
        "anyOf": [{"type": "integer", "minimum": 1}, {"type": "string"}],
    }


def _annotate_job(job: dict[str, Any]) -> None:
    _node(job, "needs").update(
        {
            "uniqueItems": True,
            "description": (
                "The jobs whose output state this one consumes, each named "
                "exactly once."
            ),
        }
    )
    uses = _branch(_node(job, "uses"), "string")
    uses["enum"] = _uses_values()
    uses["description"] = (
        "The registered job template to run, as 'job' or 'job/provider'. A "
        "bare id takes the template's default provider. Mutually exclusive "
        "with 'steps'."
    )
    steps = _branch(_node(job, "steps"), "array")
    steps["items"] = {"type": "string", "enum": _step_ids()}
    steps["description"] = (
        "Step ids to run inline, in order. Mutually exclusive with 'uses'."
    )
    source = _node(job, "source")
    source["description"] = (
        "For a view or metric that two of this job's inputs both carry, the "
        "direct predecessor whose value wins."
    )
    source["propertyNames"] = {"enum": _source_keys()}
    source["additionalProperties"] = {
        "type": "string",
        "description": "The job this key is taken from, one of this job's 'needs'.",
    }
    _node(job, "with").update(
        {
            "description": (
                "Values for configuration variables, applied to this job only."
            ),
            "propertyNames": _unreserved_keys(),
        }
    )
    _branch(_node(job, "if"), "string").update(
        {
            "pattern": _IF_PATTERN,
            "description": (
                "The condition under which this job runs, as terms joined by "
                "'and'. A term is a bare boolean configuration variable, "
                "decided when the document is loaded, or "
                "'metric::<name> <op> <literal>', decided at run time against "
                "the job's input state. A job whose condition does not hold "
                "passes its input through unchanged."
            ),
        }
    )
    _branch(_node(job, "until"), "string").update(
        {
            "pattern": _UNTIL_PATTERN,
            "description": (
                "A loop gate's exit condition, of 'metric::' terms only, "
                "evaluated against this job's output after each pass. Needs a "
                "'needs' edge closing a ring back to this job, and exactly one "
                "of 'iterations' or 'max' to bound it."
            ),
        }
    )
    iterations = _branch(_node(job, "iterations"), "object")
    iterations["minProperties"] = 1
    iterations["propertyNames"] = _unreserved_keys()
    iterations["additionalProperties"] = {"type": "array", "minItems": 1}
    iterations["description"] = (
        "A value matrix: each configuration variable mapped to the values it "
        "takes. The passes are every combination of them, each layered onto "
        "the configuration for that pass -- an escalation loop's schedule, "
        "gated by 'until', or a sweep's points."
    )
    _branch(_node(job, "max"), "integer")["minimum"] = 1
    _node(job, "max")["description"] = (
        "The pass bound for an 'until' loop that escalates nothing, and so "
        "declares no schedule."
    )
    _branch(_node(job, "select"), "string").update(
        {
            "pattern": _SELECT_PATTERN,
            "description": (
                "A sweep's keep rule: a bare metric name and a direction, "
                "'min' or 'max'. Declaring it runs every combination of "
                "'iterations' and keeps the best, where 'until' instead "
                "stops at the first pass that satisfies it."
            ),
        }
    )
    _node(job, "resources").update(
        {
            "uniqueItems": True,
            "description": (
                "The pools this job holds a seat in for the duration of its "
                "execution, or of each pass inside a loop or sweep. Each pool "
                "is named exactly once, and must be declared by the flow."
            ),
        }
    )


def _annotate_variable(variable: dict[str, Any]) -> None:
    _node(variable, "name")["description"] = "The variable's name."
    _node(variable, "type").update(
        {
            "enum": sorted(_VARIABLE_TYPES),
            "description": "The variable's type.",
        }
    )
    _node(variable, "description")["description"] = (
        "What the variable means, shown by 'librelane run --explain-variables'."
    )
    _node(variable, "default")["description"] = (
        "The value used when nothing else supplies one. Null makes the "
        "variable optional rather than defaulted."
    )
    _node(variable, "deprecated_names")["description"] = (
        "Former names still accepted, each warned about when it is used."
    )
    _branch(_node(variable, "units"), "string")["description"] = (
        "The unit the value is in, for documentation only."
    )


def _job_key_combinations() -> list[dict[str, Any]]:
    """
    Returns
    -------
    The combinations of keys a job may and may not declare together, as
    ``if``/``then`` pairs. One entry per rule
    :meth:`~librelane.engine.spec.FlowSpec._check_schedule_combinations` and
    ``JobSpec._reject_both_implementations`` enforce, so an editor refuses the
    same documents the loader does -- with a worse message, sooner.
    """
    return [
        # A job runs a registered template or a list of steps, not both.
        {"not": {"allOf": [_present("uses"), _present("steps")]}},
        # One rule for which pass wins, not two.
        {"not": {"allOf": [_present("until"), _present("select")]}},
        # 'until' takes exactly one bound.
        {
            "if": _present("until"),
            "then": {"oneOf": [_present("iterations"), _present("max")]},
        },
        # 'max' bounds an 'until' gate's passes and means nothing without one.
        {"if": _present("max"), "then": _present("until")},
        # A value matrix needs a rule for which of its passes wins.
        {
            "if": _present("iterations"),
            "then": {"anyOf": [_present("until"), _present("select")]},
        },
        # 'select' keeps the best of the passes a matrix declares.
        {"if": _present("select"), "then": _present("iterations")},
    ]
