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
import copy
from importlib.resources import files
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry
from librelane.flows.spec import FlowSpecError, VariableSpec, load_flow_spec
from librelane.flows.spec_schema import (
    JSON_SCHEMA_DIALECT,
    workflow_document_schema,
)
from librelane.flows.spec_validation import validate_against_registry

pytestmark = pytest.mark.all


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return Draft202012Validator(workflow_document_schema())


#: The document every case below patches. Two jobs, so that a case can add a
#: key to the second one and still have an edge to reason about.
_BASE: dict[str, Any] = {
    "name": "Tiny",
    "jobs": {
        "synthesis": {"steps": ["Yosys.Synthesis"]},
        "floorplan": {"needs": ["synthesis"], "steps": ["OpenROAD.Floorplan"]},
    },
}


def _document(job: dict[str, Any] | None = None, **flow: Any) -> dict[str, Any]:
    """
    Parameters
    ----------
    job : dict[str, Any] | None
        Keys to set on the ``floorplan`` job.
    flow : Any
        Keys to set on the document itself.

    Returns
    -------
    A copy of :data:`_BASE` with the patches applied.
    """
    document = copy.deepcopy(_BASE)
    document.update(flow)
    if job is not None:
        document["jobs"]["floorplan"].update(job)
    return document


def _librelane_accepts(document: dict[str, Any]) -> bool:
    """
    Whether LibreLane's own load-time passes accept a document.

    Both passes, because they split the checks between them: ``load_flow_spec``
    runs the structural ones and ``validate_against_registry`` the ones needing
    a populated registry, and a schema keyword can mirror either.
    """
    try:
        validate_against_registry(load_flow_spec(document))
        return True
    except FlowSpecError:
        return False


def _schema_accepts(validator: Draft202012Validator, document: dict[str, Any]) -> bool:
    return not list(validator.iter_errors(document))


def _shipped_documents() -> list[str]:
    return sorted(
        path.name
        for path in files("librelane.flows").iterdir()
        if path.name.endswith(".yaml")
    )


def test_the_schema_is_a_well_formed_document():
    schema = workflow_document_schema()

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == JSON_SCHEMA_DIALECT


@pytest.mark.parametrize("name", _shipped_documents())
def test_every_shipped_document_satisfies_the_schema(
    validator: Draft202012Validator, name: str
):
    document = yaml.safe_load(
        files("librelane.flows").joinpath(name).read_text(encoding="utf8")
    )

    assert list(validator.iter_errors(document)) == []


#: Documents LibreLane refuses that the schema must refuse too. A document an
#: editor calls legal and the loader then rejects is worse than no schema at
#: all, so every keyword added to the generator belongs here as a case.
_REFUSED: dict[str, dict[str, Any]] = {
    "an unknown job key": _document(job={"nonsense": 1}),
    "an unregistered step id": _document(job={"steps": ["Nope.Step"]}),
    "an unregistered uses": _document(job={"steps": None, "uses": "nope/openroad"}),
    "uses and steps together": _document(job={"uses": "floorplan/openroad"}),
    "a matrix with no rule for which pass wins": _document(
        job={"iterations": {"A": [1]}}
    ),
    "select without a matrix": _document(job={"select": "x min"}),
    "until and select together": _document(
        job={
            "until": "metric::a > 0",
            "iterations": {"A": [1]},
            "select": "x min",
        }
    ),
    "max without until": _document(job={"max": 2}),
    "until with no bound": _document(job={"until": "metric::a > 0"}),
    "until with both bounds": _document(
        job={"until": "metric::a > 0", "max": 2, "iterations": {"A": [1]}}
    ),
    "an empty matrix": _document(job={"iterations": {}, "select": "x min"}),
    "a scheduled variable with no values": _document(
        job={"iterations": {"A": []}, "select": "x min"}
    ),
    "a pass bound below one": _document(job={"until": "metric::a > 0", "max": 0}),
    "a select with no direction": _document(
        job={"iterations": {"A": [1]}, "select": "wns"}
    ),
    "a select carrying a metric prefix": _document(
        job={"iterations": {"A": [1]}, "select": "metric::x min"}
    ),
    "a malformed if": _document(job={"if": "a or b"}),
    "an until over a configuration variable": _document(job={"until": "A", "max": 2}),
    "a source key naming neither a view nor a metric": _document(
        job={"source": {"nonsense": "synthesis"}}
    ),
    "a repeated need": _document(job={"needs": ["synthesis", "synthesis"]}),
    "a repeated pool": _document(resources={"p": 2}, job={"resources": ["p", "p"]}),
    "a capacity below one": _document(resources={"p": 0}),
    "a boolean capacity": _document(resources={"p": True}),
    "a reserved key in a with block": _document(**{"with": {"PDK": "sky130A"}}),
    "a tool selection in a schedule": _document(
        job={"select": "x min", "iterations": {"TOOLS": ["x"]}}
    ),
}


#: Documents LibreLane accepts, which the schema must not flag. The explicit
#: nulls case is the one the presence rules are written around: the models test
#: ``is not None``, so a key written out as null is an absent key.
_ACCEPTED: dict[str, dict[str, Any]] = {
    "a minimal document": _document(),
    "keys written out as null": _document(job={"uses": None, "select": None}),
    "a repeated step": _document(
        job={"steps": ["OpenROAD.Floorplan", "OpenROAD.IOPlacement"]}
    ),
    "a loop bounded by a pass count": {
        "name": "Tiny",
        "jobs": {
            "synthesis": {"steps": ["Yosys.Synthesis"]},
            "repair": {
                "needs": ["synthesis", "sta"],
                "steps": ["OpenROAD.ResizerTimingPostGRT"],
            },
            "sta": {
                "needs": ["repair"],
                "steps": ["OpenROAD.STAMidPNR"],
                "until": "metric::timing__hold__ws >= 0",
                "max": 3,
            },
        },
    },
    "a sweep matrix with a pool and a runtime condition": {
        "name": "Tiny",
        "resources": {"seats": 2},
        "jobs": {
            "synthesis": {"steps": ["Yosys.Synthesis"]},
            "placement": {
                "needs": ["synthesis"],
                "steps": ["OpenROAD.GlobalPlacement"],
                "select": "route__wirelength__max min",
                "iterations": {"PL_TARGET_DENSITY_PCT": [45, 55]},
                "resources": ["seats"],
            },
            "antennas": {
                "needs": ["placement"],
                "steps": ["OpenROAD.RepairAntennas"],
                "if": "metric::antenna__violating__nets > 0",
            },
        },
    },
}


@pytest.mark.parametrize("document", _REFUSED.values(), ids=list(_REFUSED))
def test_the_schema_refuses_what_librelane_refuses(
    validator: Draft202012Validator, document: dict[str, Any]
):
    assert not _librelane_accepts(document), "the case no longer tests anything"
    assert not _schema_accepts(validator, document)


@pytest.mark.parametrize("document", _ACCEPTED.values(), ids=list(_ACCEPTED))
def test_the_schema_accepts_what_librelane_accepts(
    validator: Draft202012Validator, document: dict[str, Any]
):
    assert _librelane_accepts(document), "the case no longer tests anything"
    assert _schema_accepts(validator, document)


def test_the_step_enumeration_is_this_installation_s_registry(
    validator: Draft202012Validator,
):
    from librelane.steps import Step

    enumerated = validator.schema["$defs"]["JobSpec"]["properties"]["steps"]
    values = [
        branch for branch in enumerated["anyOf"] if branch.get("type") == "array"
    ][0]["items"]["enum"]

    assert sorted(values) == sorted(Step.factory.list())


def test_the_uses_enumeration_carries_bare_ids_and_provider_pairs(
    validator: Draft202012Validator,
):
    enumerated = validator.schema["$defs"]["JobSpec"]["properties"]["uses"]
    values = [
        branch for branch in enumerated["anyOf"] if branch.get("type") == "string"
    ][0]["enum"]

    assert "synthesis/yosys" in values
    assert "synthesis" in values
    assert "synthesis/nonsense" not in values


def test_a_variable_type_the_schema_refuses_cannot_reach_a_run():
    """
    The one place the schema is stricter than the load-time passes.

    A ``type`` outside the supported scalars survives both of them, because it
    is only resolved when the flow's variables are built, so refusing it in an
    editor is refusing a document that could never have run.
    """
    document = _document(config=[{"name": "A", "type": "float", "description": "d"}])
    assert _librelane_accepts(document)

    with pytest.raises(FlowSpecError) as exc_info:
        VariableSpec(name="A", type="float", description="d").to_variable()

    assert "float" in str(exc_info.value)
