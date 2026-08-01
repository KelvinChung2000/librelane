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
import pytest

from librelane.flows.spec import FlowSpec, FlowSpecError, JobSpec, VariableSpec

pytestmark = pytest.mark.all


def test_a_job_reads_if_from_yaml_and_condition_from_python():
    from_yaml = JobSpec.model_validate({"uses": "lint", "if": "RUN_LINTER"})
    from_python = JobSpec(uses="lint", condition="RUN_LINTER")

    assert from_yaml.condition == "RUN_LINTER"
    assert from_python.condition == "RUN_LINTER"
    assert from_yaml == from_python


def test_a_job_reads_with_from_yaml_and_values_from_python():
    from_yaml = JobSpec.model_validate(
        {"uses": "floorplan", "with": {"FP_CORE_UTIL": 40}}
    )
    from_python = JobSpec(uses="floorplan", values={"FP_CORE_UTIL": 40})

    assert from_yaml.values == {"FP_CORE_UTIL": 40}
    assert from_yaml == from_python


def test_a_document_reads_with_from_yaml_and_values_from_python():
    from_yaml = FlowSpec.model_validate(
        {
            "name": "T",
            "with": {"FP_SIZING": "absolute"},
            "jobs": {"floorplan": {"uses": "floorplan"}},
        }
    )
    from_python = FlowSpec(
        name="T",
        values={"FP_SIZING": "absolute"},
        jobs={"floorplan": JobSpec(uses="floorplan")},
    )

    assert from_yaml.values == {"FP_SIZING": "absolute"}
    assert from_yaml == from_python


def test_a_job_declaring_both_uses_and_steps_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "steps": ["Magic.DRC"]})

    assert "uses" in str(exc_info.value)
    assert "steps" in str(exc_info.value)


def test_an_unknown_job_key_is_rejected_naming_the_six_legal_keys():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "runs-on": "ubuntu-latest"})

    message = str(exc_info.value)
    assert "runs-on" in message
    for key in ("needs", "uses", "steps", "source", "if", "with"):
        assert key in message


def test_a_variable_spec_becomes_a_variable():
    variable = VariableSpec(
        name="RUN_LINTER",
        type="bool",
        description="Whether to run the linter.",
        default=True,
        deprecated_names=["RUN_LINT"],
    ).to_variable()

    assert variable.name == "RUN_LINTER"
    assert variable.type is bool
    assert variable.default is True
    assert variable.description == "Whether to run the linter."
    assert variable.deprecated_names == ["RUN_LINT"]


def test_an_unsupported_variable_type_is_rejected_naming_the_supported_set():
    with pytest.raises(FlowSpecError) as exc_info:
        VariableSpec(name="THINGS", type="list[str]", description="x").to_variable()

    message = str(exc_info.value)
    assert "list[str]" in message
    for name in ("bool", "int", "str", "Decimal", "Path"):
        assert name in message


def test_a_minimal_flow_spec_round_trips_from_a_mapping():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
            },
        }
    )

    assert spec.name == "Tiny"
    assert list(spec.jobs) == ["synthesis", "floorplan"]
    assert spec.jobs["floorplan"].needs == ["synthesis"]
    assert spec.jobs["synthesis"].needs == []
    assert spec.final is None


def test_a_needs_naming_an_undeclared_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {"needs": ["typo"], "uses": "floorplan"},
                },
            }
        )

    message = str(exc_info.value)
    assert "floorplan" in message
    assert "typo" in message
    assert "synthesis" in message


def test_a_needs_naming_the_same_job_twice_is_rejected():
    # A duplicate used to load cleanly and die mid-run: edges() returned
    # ["synthesis", "synthesis"], Net built two equal arcs, and the second
    # deposit raised NetError -- whose message asserted this was "a scheduling
    # bug rather than a configuration error", which is precisely backwards.
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {
                        "needs": ["synthesis", "synthesis"],
                        "uses": "floorplan",
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "floorplan" in message
    assert "synthesis" in message
    assert "more than once" in message


def test_a_cycle_is_rejected_naming_its_members():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "a": {"needs": ["b"], "uses": "synthesis"},
                    "b": {"needs": ["a"], "uses": "floorplan"},
                },
            }
        )

    message = str(exc_info.value)
    assert "cycle" in message.lower()
    assert "a" in message
    assert "b" in message


def test_a_source_naming_an_unrelated_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "streamout": {"uses": "streamout/magic"},
                    "elsewhere": {"uses": "drc/klayout"},
                    "xor": {
                        "needs": ["streamout"],
                        "uses": "drc/magic",
                        "source": {"gds": "elsewhere"},
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "elsewhere" in message
    assert "streamout" in message


def test_a_source_naming_a_transitive_ancestor_is_rejected():
    """
    'streamout' is an ancestor of 'xor' but not one of its needs, so no token
    from 'streamout' ever lands on an arc the join at 'xor' can see. Accepting
    this at load would produce a document that crashes at run time.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "streamout": {"uses": "streamout/magic"},
                    "drc": {"needs": ["streamout"], "uses": "drc/magic"},
                    "xor": {
                        "needs": ["drc"],
                        "uses": "drc/klayout",
                        "source": {"gds": "streamout"},
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "streamout" in message
    assert "needs" in message
    assert "drc" in message


def test_load_flow_spec_reads_a_yaml_file(tmp_path):
    from librelane.flows.spec import load_flow_spec

    document = tmp_path / "tiny.yaml"
    document.write_text(
        "name: Tiny\n"
        "jobs:\n"
        "  synthesis:\n"
        "    uses: synthesis/yosys\n"
        "  floorplan:\n"
        "    needs: [synthesis]\n"
        "    uses: floorplan\n"
    )

    spec = load_flow_spec(document)

    assert spec.name == "Tiny"
    assert spec.jobs["floorplan"].needs == ["synthesis"]


def test_load_flow_spec_names_the_file_when_the_document_is_bad(tmp_path):
    from librelane.flows.spec import load_flow_spec

    document = tmp_path / "broken.yaml"
    document.write_text(
        "name: Broken\njobs:\n  floorplan:\n    needs: [typo]\n    uses: floorplan\n"
    )

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "broken.yaml" in str(exc_info.value)


_RUN_LINTER = {"name": "RUN_LINTER", "type": "bool", "description": "x"}
_RUN_XOR = {"name": "RUN_XOR", "type": "bool", "description": "x"}
_STRATEGY = {"name": "STRATEGY", "type": "str", "description": "x"}


def test_parse_condition_returns_a_tuple_of_conjuncts():
    """
    Phase 2's resolve_jobs assigns this straight to Job.conditions, which is a
    tuple, so the return type is a cross-phase contract rather than a detail.
    """
    from librelane.flows.spec import parse_condition

    assert parse_condition("RUN_LINTER") == ("RUN_LINTER",)
    assert parse_condition("A and B and C") == ("A", "B", "C")


def test_an_if_naming_an_undeclared_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_RUN_LINTER],
                "jobs": {"lint": {"uses": "lint/verilator", "if": "RUN_LINT"}},
            }
        )

    message = str(exc_info.value)
    assert "lint" in message
    assert "RUN_LINT" in message
    assert "RUN_LINTER" in message


def test_an_if_conjunction_of_declared_variables_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_RUN_LINTER, _RUN_XOR],
            "jobs": {
                "lint": {
                    "uses": "lint/verilator",
                    "if": "RUN_LINTER and RUN_XOR",
                }
            },
        }
    )

    assert spec.jobs["lint"].condition == "RUN_LINTER and RUN_XOR"


@pytest.mark.parametrize(
    "condition",
    ["RUN_LINTER or RUN_XOR", "not RUN_LINTER", "RUN_LINTER and", "", "and"],
)
def test_an_if_that_is_not_a_conjunction_is_rejected(condition):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_RUN_LINTER, _RUN_XOR],
                "jobs": {"lint": {"uses": "lint/verilator", "if": condition}},
            }
        )

    message = str(exc_info.value)
    assert "lint" in message
    assert "and" in message


def test_an_if_naming_a_non_boolean_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_STRATEGY],
                "jobs": {"lint": {"uses": "lint/verilator", "if": "STRATEGY"}},
            }
        )

    message = str(exc_info.value)
    assert "STRATEGY" in message
    assert "bool" in message


def test_a_final_naming_an_undeclared_job_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "final": "typo",
                "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
            }
        )

    message = str(exc_info.value)
    assert "typo" in message
    assert "synthesis" in message


def test_a_final_naming_a_declared_job_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "final": "synthesis",
            "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
        }
    )

    assert spec.final == "synthesis"


@pytest.mark.parametrize("key", ["PDK", "SCL", "PAD", "meta"])
def test_a_document_with_naming_a_process_selection_key_is_rejected(key):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "with": {key: "whatever"},
                "jobs": {"synthesis": {"uses": "synthesis/yosys"}},
            }
        )

    message = str(exc_info.value)
    assert key in message
    assert "PDK" in message
