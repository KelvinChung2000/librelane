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

from librelane.engine.spec import FlowSpec, FlowSpecError, JobSpec, VariableSpec

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
    # A two-job mutual cycle is a well-shaped ring, but neither member
    # declares 'until', so it is rejected as a gate-less ring rather than
    # as an ill-shaped one: test_a_cycle_that_is_not_a_simple_ring_is_rejected
    # covers the other kind.
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
    assert "until" in message
    assert "a" in message
    assert "b" in message


def test_a_cycle_that_is_not_a_simple_ring_is_rejected():
    # a-b-c-a is a simple ring, but 'c' also needs 'a' directly (a chord),
    # so 'c' has two intra-ring predecessors and the cycle is not a ring.
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "a": {"needs": ["c"], "uses": "floorplan"},
                    "b": {"needs": ["a"], "uses": "floorplan"},
                    "c": {"needs": ["b", "a"], "uses": "floorplan"},
                },
            }
        )

    message = str(exc_info.value)
    assert "not a simple ring" in message
    assert "a" in message
    assert "b" in message
    assert "c" in message


def test_a_legal_ring_validates_and_rings_returns_the_pass_order():
    # cts feeds the ring's non-gate member from outside, which is legal:
    # only a *consumer* of a non-gate member is restricted, not a producer.
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "cts": {"uses": "cts"},
                "resize": {"needs": ["cts", "sta"], "uses": "floorplan"},
                "sta": {
                    "needs": ["resize"],
                    "uses": "sta",
                    "until": "metric::timing__setup__ws >= 0",
                    "max": 3,
                },
            },
        }
    )

    # Rotated to start at the gate's intra-ring successor ('resize') and end
    # at the gate ('sta'): the order one pass runs its members in.
    assert spec.rings() == {"sta": ("resize", "sta")}


def test_collapsed_edges_collapses_a_ring_to_its_gate():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "cts": {"uses": "cts"},
                "resize": {"needs": ["cts", "sta"], "uses": "floorplan"},
                "sta": {
                    "needs": ["resize"],
                    "uses": "sta",
                    "until": "metric::timing__setup__ws >= 0",
                    "max": 3,
                },
            },
        }
    )

    # 'resize' has no key of its own: it collapsed into the gate's id 'sta',
    # and the ring's only outside dependency, 'cts', survives once.
    assert spec.collapsed_edges() == {"cts": [], "sta": ["cts"]}


def test_a_self_need_with_until_is_a_legal_ring_of_one():
    # Today a self-need passes _check_needs_are_declared (the need it names
    # is declared) and used to die in _check_acyclic. A self-loop gated by
    # 'until' is now a legal ring of one.
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "resize": {
                    "needs": ["resize"],
                    "uses": "floorplan",
                    "until": "metric::x >= 0",
                    "max": 3,
                }
            },
        }
    )

    assert spec.rings() == {"resize": ("resize",)}


def test_a_ring_with_multiple_until_gates_is_rejected_naming_them():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "a": {
                        "needs": ["b"],
                        "uses": "floorplan",
                        "until": "metric::x >= 0",
                        "max": 2,
                    },
                    "b": {
                        "needs": ["a"],
                        "uses": "floorplan",
                        "until": "metric::y >= 0",
                        "max": 2,
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "a" in message
    assert "b" in message
    assert "until" in message


def test_a_non_gate_ring_member_with_an_outside_consumer_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "resize": {"needs": ["sta"], "uses": "floorplan"},
                    "sta": {
                        "needs": ["resize"],
                        "uses": "sta",
                        "until": "metric::x >= 0",
                        "max": 3,
                    },
                    "outside": {"needs": ["resize"], "uses": "drc/magic"},
                },
            }
        )

    message = str(exc_info.value)
    assert "outside" in message
    assert "resize" in message
    assert "sta" in message


def test_until_on_a_job_with_no_back_edge_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {"sta": {"uses": "sta", "until": "metric::x >= 0", "max": 3}},
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "not part of a cycle" in message


def test_select_on_a_ring_member_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "resize": {
                        "needs": ["sta"],
                        "uses": "floorplan",
                        "iterations": {"FP_CORE_UTIL": [40, 50]},
                        "select": "route__wirelength min",
                    },
                    "sta": {
                        "needs": ["resize"],
                        "uses": "sta",
                        "until": "metric::x >= 0",
                        "max": 3,
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "resize" in message
    assert "sweep" in message


def test_final_naming_a_non_gate_ring_member_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "final": "resize",
                "jobs": {
                    "resize": {"needs": ["sta"], "uses": "floorplan"},
                    "sta": {
                        "needs": ["resize"],
                        "uses": "sta",
                        "until": "metric::x >= 0",
                        "max": 3,
                    },
                },
            }
        )

    message = str(exc_info.value)
    assert "resize" in message
    assert "sta" in message
    assert "final" in message.lower()


def test_final_naming_the_ring_s_gate_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "final": "sta",
            "jobs": {
                "resize": {"needs": ["sta"], "uses": "floorplan"},
                "sta": {
                    "needs": ["resize"],
                    "uses": "sta",
                    "until": "metric::x >= 0",
                    "max": 3,
                },
            },
        }
    )

    assert spec.final == "sta"


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
    from librelane.engine.spec import load_flow_spec

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
    from librelane.engine.spec import load_flow_spec

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


def test_parse_predicate_returns_a_tuple_of_config_terms_for_a_conjunction():
    """
    Phase 2's resolve_jobs assigns config_terms(parse_predicate(...)) straight
    to ResolvedJob.conditions, which is a tuple of names, so the shape is a
    cross-phase contract rather than a detail. The grammar itself,
    predicates.parse_predicate, is pinned in test_predicates.py; this only
    pins spec.py's use of it for 'if'.
    """
    from librelane.engine.predicates import ConfigTerm, config_terms, parse_predicate

    assert parse_predicate("RUN_LINTER") == (ConfigTerm("RUN_LINTER"),)
    assert config_terms(parse_predicate("A and B and C")) == ("A", "B", "C")


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


@pytest.mark.parametrize("key", ["PDK", "SCL", "PAD", "meta"])
def test_a_job_with_naming_a_process_selection_key_is_rejected(key):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "synthesis": {
                        "uses": "synthesis/yosys",
                        "with": {key: "whatever"},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert key in message
    assert "synthesis" in message
    assert "PDK" in message


def test_a_job_with_an_ordinary_variable_is_accepted():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "synthesis": {
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "AREA 0"},
                }
            },
        }
    )

    assert spec.jobs["synthesis"].values == {"SYNTH_STRATEGY": "AREA 0"}


def test_an_unknown_job_key_message_lists_the_new_keys():
    with pytest.raises(FlowSpecError) as exc_info:
        JobSpec.model_validate({"uses": "drc/magic", "runs-on": "ubuntu-latest"})

    message = str(exc_info.value)
    for key in ("until", "iterations", "max", "select", "resources"):
        assert key in message


def test_a_job_using_every_new_key_legally_validates():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "resources": {"drc_seats": 2},
            "jobs": {
                "sta": {
                    "uses": "sta",
                    "needs": ["sta"],
                    "until": "metric::timing__setup__ws >= 0",
                    "max": 3,
                    "resources": ["drc_seats"],
                },
                "place": {
                    "uses": "placement",
                    "iterations": {"PL_TARGET_DENSITY": [0.45, 0.55]},
                    "select": "route__wirelength min",
                },
            },
        }
    )

    assert spec.jobs["sta"].until == "metric::timing__setup__ws >= 0"
    assert spec.jobs["sta"].max_passes == 3
    assert spec.jobs["sta"].resources == ["drc_seats"]
    assert spec.jobs["place"].select == "route__wirelength min"
    assert spec.jobs["place"].schedule() == (
        {"PL_TARGET_DENSITY": 0.45},
        {"PL_TARGET_DENSITY": 0.55},
    )
    assert spec.resources == {"drc_seats": 2}
    assert spec.rings() == {"sta": ("sta",)}


def test_an_until_naming_a_configuration_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "config": [_RUN_LINTER],
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "RUN_LINTER",
                        "max": 3,
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "RUN_LINTER" in message
    assert "metric::" in message


def test_an_until_with_neither_iterations_nor_max_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "iterations" in message
    assert "max" in message


def test_an_until_with_both_iterations_and_max_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "max": 3,
                        "iterations": {"X": [1]},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "both" in message.lower()


def test_iterations_without_until_or_select_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "place": {
                        "uses": "placement",
                        "iterations": {"PL_TARGET_DENSITY": [0.45]},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "place" in message
    assert "until" in message
    assert "select" in message


def test_max_without_until_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {"name": "Tiny", "jobs": {"sta": {"uses": "sta", "max": 3}}}
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "until" in message


def test_max_with_a_sweep_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "place": {
                        "uses": "placement",
                        "iterations": {"PL_TARGET_DENSITY": [0.45]},
                        "select": "route__wirelength min",
                        "max": 3,
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "place" in message
    assert "max" in message
    assert "until" in message


def test_select_without_iterations_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "place": {
                        "uses": "placement",
                        "select": "route__wirelength min",
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "place" in message
    assert "iterations" in message


def test_a_gate_declaring_until_and_select_is_rejected():
    """
    The two keys are the two rules for which pass wins, so a job declaring
    both names two winners. Reachable only on a ring's gate: 'until' off a
    ring is refused by the cycle check, and 'select' on a non-gate member by
    the sweep restriction.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "iterations": {"X": [1, 2]},
                        "select": "route__wirelength min",
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "until" in message
    assert "select" in message


def test_an_empty_iterations_matrix_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "iterations": {},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "empty" in message.lower()


def test_a_scheduled_variable_with_no_values_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "iterations": {"X": []},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "X" in message


def test_iterations_expand_to_every_combination_last_variable_fastest():
    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "place": {
                    "uses": "placement",
                    "iterations": {"A": [1, 2], "B": ["x", "y", "z"]},
                    "select": "route__wirelength min",
                }
            },
        }
    )

    assert spec.jobs["place"].schedule() == (
        {"A": 1, "B": "x"},
        {"A": 1, "B": "y"},
        {"A": 1, "B": "z"},
        {"A": 2, "B": "x"},
        {"A": 2, "B": "y"},
        {"A": 2, "B": "z"},
    )


@pytest.mark.parametrize("key", ["PDK", "SCL", "PAD", "meta"])
def test_an_iterations_entry_naming_a_process_selection_key_is_rejected(key):
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "iterations": {key: ["whatever"]},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert key in message


def test_an_iterations_entry_naming_tools_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "iterations": {"TOOLS": [{"sta": "opensta"}]},
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "TOOLS" in message


def test_a_max_below_one_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "sta": {
                        "uses": "sta",
                        "needs": ["sta"],
                        "until": "metric::x >= 0",
                        "max": 0,
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "sta" in message
    assert "positive" in message.lower()


def test_a_select_that_is_not_two_tokens_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "place": {
                        "uses": "placement",
                        "iterations": {"PL_TARGET_DENSITY": [0.45]},
                        "select": "route__wirelength",
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "place" in message
    assert "min" in message
    assert "max" in message


def test_a_select_with_the_metric_prefix_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "jobs": {
                    "place": {
                        "uses": "placement",
                        "iterations": {"PL_TARGET_DENSITY": [0.45]},
                        "select": "metric::route__wirelength min",
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "place" in message
    assert "metric::" in message


def test_duplicate_job_resources_are_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "resources": {"drc_seats": 2},
                "jobs": {
                    "drc": {
                        "uses": "drc/magic",
                        "resources": ["drc_seats", "drc_seats"],
                    }
                },
            }
        )

    message = str(exc_info.value)
    assert "drc" in message
    assert "more than once" in message


def test_a_resource_pool_capacity_below_one_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "resources": {"drc_seats": 0},
                "jobs": {"drc": {"uses": "drc/magic"}},
            }
        )

    message = str(exc_info.value)
    assert "drc_seats" in message
    assert "0" in message


@pytest.mark.parametrize("capacity", [True, False])
def test_a_boolean_resource_pool_capacity_is_rejected(capacity):
    """
    bool is an int subclass, so dict[str, int | str] admits True/False as 1/0
    under pydantic's lax coercion. A YAML boolean -- however the loader
    spelled it -- is neither a positive integer literal nor a declared
    variable name, and accepting it would silently coerce a document typo
    ('drc_seats: yes') into a capacity of 1.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "resources": {"drc_seats": capacity},
                "jobs": {"drc": {"uses": "drc/magic"}},
            }
        )

    message = str(exc_info.value)
    assert "drc_seats" in message
    assert "boolean" in message.lower()


def test_job_resources_naming_an_undeclared_pool_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Tiny",
                "resources": {"drc_seats": 2},
                "jobs": {"drc": {"uses": "drc/magic", "resources": ["typo_seats"]}},
            }
        )

    message = str(exc_info.value)
    assert "drc" in message
    assert "typo_seats" in message
    assert "drc_seats" in message
