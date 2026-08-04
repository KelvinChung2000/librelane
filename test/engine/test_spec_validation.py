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

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry
from librelane.engine.spec import FlowSpec, FlowSpecError
from librelane.engine.spec_validation import validate_against_registry

pytestmark = pytest.mark.all


def _spec(jobs: dict, **extra) -> FlowSpec:
    return FlowSpec.model_validate({"name": "Tiny", "jobs": jobs, **extra})


def test_a_valid_document_passes():
    validate_against_registry(
        _spec(
            {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
            }
        )
    )


def test_an_unregistered_job_is_rejected_naming_the_registered_ones():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"nope": {"uses": "not_a_job"}}))

    message = str(exc_info.value)
    assert "not_a_job" in message
    assert "synthesis" in message


def test_an_unregistered_provider_is_rejected_naming_the_job_s_providers():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"synthesis": {"uses": "synthesis/not_a_tool"}})
        )

    message = str(exc_info.value)
    assert "not_a_tool" in message
    assert "yosys" in message


def test_a_uses_with_too_many_slashes_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec({"synthesis": {"uses": "synthesis/yosys/extra"}})
        )

    assert "synthesis/yosys/extra" in str(exc_info.value)


def test_an_unregistered_step_id_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"custom": {"steps": ["Odb.NotAStep"]}}))

    assert "Odb.NotAStep" in str(exc_info.value)


def test_a_registered_step_id_is_accepted_case_insensitively():
    validate_against_registry(_spec({"custom": {"steps": ["odb.setpowerconnections"]}}))


def test_a_job_whose_id_is_a_template_id_needs_no_uses():
    """
    'floorplan' is one of the 27 registered template ids, so an empty job body
    under that key means 'uses: floorplan'.
    """
    validate_against_registry(_spec({"floorplan": {}}))


def test_a_job_with_no_uses_no_steps_and_no_template_id_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"not_a_template": {}}))

    message = str(exc_info.value)
    assert "not_a_template" in message
    assert "uses" in message
    assert "steps" in message


def test_a_fan_in_conflict_is_rejected_naming_both_producers():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                    "xor": {
                        "needs": ["magic_streamout", "klayout_streamout"],
                        "uses": "drc/magic",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "source" in message


def test_a_declared_source_resolves_the_fan_in_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "magic_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/magic",
                },
                "klayout_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/klayout",
                },
                "xor": {
                    "needs": ["magic_streamout", "klayout_streamout"],
                    "uses": "drc/magic",
                    "source": {"gds": "klayout_streamout"},
                },
            }
        )
    )


def test_a_view_from_a_shared_ancestor_is_not_a_conflict():
    """
    'floorplan' provides def, nl and sdc down both branches identically. Were
    the shared subgraph not subtracted, this document would be rejected three
    times over.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "magic_drc": {"needs": ["floorplan"], "uses": "drc/klayout"},
                "lvs": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "join": {"needs": ["magic_drc", "lvs"], "uses": "drc/klayout"},
            }
        )
    )


def test_a_metric_fan_in_conflict_is_rejected_naming_both_producers():
    """
    Two lvs/netgen jobs each declare design__lvs_error__count from the
    template and magic__illegal_overlap__count from the registration. The join
    rule is the same one views get.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "lvs_a": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                    "lvs_b": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                    "join": {
                        "needs": ["lvs_a", "lvs_b"],
                        "steps": ["Odb.SetPowerConnections"],
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "join" in message
    assert "lvs_a" in message
    assert "lvs_b" in message
    assert "design__lvs_error__count" in message


def test_a_declared_source_resolves_a_metric_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "lvs_a": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "lvs_b": {"needs": ["floorplan"], "uses": "lvs/netgen"},
                "join": {
                    "needs": ["lvs_a", "lvs_b"],
                    "steps": ["Odb.SetPowerConnections"],
                    "source": {
                        "design__lvs_error__count": "lvs_a",
                        "magic__illegal_overlap__count": "lvs_a",
                    },
                },
            }
        )
    )


def test_a_required_view_no_ancestor_produces_is_rejected():
    """
    'streamout' produces gds but is not an ancestor of 'drc', so gds is
    producible by the document yet unreachable from drc. 'streamout' needs
    'synthesis' only so that its own def/nl/sdc requirement is not the first
    thing to raise. A view no job at all produces is a different case, pinned
    below.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "streamout": {
                        "needs": ["synthesis"],
                        "uses": "streamout/magic",
                    },
                    "drc": {"needs": ["synthesis"], "uses": "drc/klayout"},
                }
            )
        )

    message = str(exc_info.value)
    assert "drc" in message
    assert "gds" in message


def test_an_optional_input_no_ancestor_produces_is_accepted():
    """
    Both of KLayout.Render's inputs are optional, so it runs on whatever
    arrives and requires nothing. 'klayout_streamout' produces gds elsewhere in
    the document, which is what makes this the interesting case: the rejection
    above fires only for a view some other job produces, so an optional input
    escapes notice until something else produces it.

    DesignFormat.mkOptional() returns a copy with a flag set, so the flag has
    to be read off the view itself, before it is reduced to its id.
    """
    validate_against_registry(
        _spec(
            {
                "synthesis": {"uses": "synthesis/yosys"},
                "render": {"needs": ["synthesis"], "steps": ["KLayout.Render"]},
                "klayout_streamout": {
                    "needs": ["synthesis"],
                    "uses": "streamout/klayout",
                },
            }
        )
    )


def test_a_descendant_producing_a_view_is_not_evidence_for_its_ancestor():
    """
    'floorplan' requires nl, and takes it from the initial state. Its three
    PNR_IN_PLACE descendants each provide nl as well, and none of them can hand
    anything back to their own ancestor, so none of them is evidence. Drop the
    descendant exclusion and this document is rejected for nl.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {},
                "global_placement": {"needs": ["floorplan"]},
                "cts": {"needs": ["global_placement"]},
                "detailed_placement": {"needs": ["cts"]},
            }
        )
    )


def test_a_source_key_that_is_neither_a_view_nor_a_metric_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                    "xor": {
                        "needs": ["magic_streamout", "klayout_streamout"],
                        "uses": "drc/magic",
                        "source": {"not_a_key": "klayout_streamout"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "not_a_key" in message
    assert "view" in message
    assert "metric" in message


def test_a_source_naming_a_predecessor_that_cannot_deliver_the_key_is_rejected():
    """
    'cts' is a legal direct predecessor but its whole branch provides only
    def, nl and sdc, so no gds token ever arrives from it.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "cts": {"needs": ["floorplan"], "uses": "cts/openroad"},
                    "join": {
                        "needs": ["magic_streamout", "cts"],
                        "uses": "drc/magic",
                        "source": {"gds": "cts"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "join" in message
    assert "cts" in message
    assert "gds" in message


def test_a_view_no_job_produces_is_left_to_the_initial_state():
    """
    A view that no job in the document produces is assumed to arrive in the
    initial state, and is checked at run time rather than at load time. This
    is what lets a document start mid-flow from '--with-initial-state'.
    """
    validate_against_registry(_spec({"drc": {"uses": "drc/magic"}}))


def test_a_with_on_the_only_reader_is_accepted():
    """
    FP_CORE_UTIL is declared by OpenROAD.Floorplan, OpenROAD.GlobalPlacement
    and OpenROAD.GlobalPlacementSkipIO. This document has only the first, so
    its reach here is the single job 'floorplan', which sets it. Covered.
    """
    validate_against_registry(_spec({"floorplan": {"with": {"FP_CORE_UTIL": 40}}}))


def test_a_with_set_by_every_reader_of_the_variable_is_accepted():
    """
    Two jobs of one template with different values, which is the case this key
    exists for. Both run Yosys.Synthesis so both read SYNTH_STRATEGY, and both
    set it, so no reader is left observing a value it did not declare.
    """
    validate_against_registry(
        _spec(
            {
                "synth_a": {
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "AREA 0"},
                },
                "synth_b": {
                    "needs": ["synth_a"],
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "DELAY 0"},
                },
            }
        )
    )


def test_a_with_set_by_only_some_readers_is_rejected():
    """The same document with one of the two readers left uncovered."""
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synth_a": {
                        "uses": "synthesis/yosys",
                        "with": {"SYNTH_STRATEGY": "AREA 0"},
                    },
                    "synth_b": {
                        "needs": ["synth_a"],
                        "uses": "synthesis/yosys",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "SYNTH_STRATEGY" in message
    assert "synth_a" in message
    assert "synth_b" in message


def test_a_with_naming_a_universal_variable_is_rejected():
    """
    DIE_AREA is in flow_common_variables, so every job reads it. Setting it on
    'floorplan' alone would floorplan one die and leave every other job
    reading a different one.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {
                        "needs": ["synthesis"],
                        "with": {"DIE_AREA": "0 0 100 100"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "DIE_AREA" in message
    assert "synthesis" in message


def test_a_with_naming_a_variable_the_setting_job_cannot_read_is_rejected():
    """
    'floorplan' runs no step that declares SYNTH_STRATEGY, so the entry could
    never take effect, and 'synthesis' reads it without setting it.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "floorplan": {
                        "needs": ["synthesis"],
                        "with": {"SYNTH_STRATEGY": "AREA 0"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "SYNTH_STRATEGY" in message
    assert "floorplan" in message
    assert "synthesis" in message


def test_a_with_naming_a_variable_no_job_reads_is_rejected():
    """
    Reach is empty and the setter set is not, so the two are unequal. This is
    the second failure mode, a value that could never take effect.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(_spec({"floorplan": {"with": {"NOT_A_VARIABLE": 1}}}))

    message = str(exc_info.value)
    assert "NOT_A_VARIABLE" in message
    assert "floorplan" in message


def test_a_conflicting_sink_join_with_no_final_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {},
                    "magic_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/magic",
                    },
                    "klayout_streamout": {
                        "needs": ["floorplan"],
                        "uses": "streamout/klayout",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "final" in message


def test_a_final_resolves_the_sink_join_conflict():
    validate_against_registry(
        _spec(
            {
                "floorplan": {},
                "magic_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/magic",
                },
                "klayout_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/klayout",
                },
            },
            final="klayout_streamout",
        )
    )


def test_a_ring_document_passes_validate_against_registry():
    """
    The Task 2 guard ("loops are not executable yet") is deleted by Task 4,
    now that the engine runs a ring: a document declaring one legal ring and
    nothing else wrong passes the registry-backed checks exactly as any other
    well-formed document does. That the engine actually constructs and runs
    a ring is pinned in test/engine/test_loops.py, which is where the
    execution-level assertion this guard's own test used to make now
    belongs.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {
                    "needs": ["floorplan"],
                    "uses": "floorplan",
                    "until": "metric::x >= 0",
                    "max": 3,
                }
            }
        )
    )


def test_a_schedule_variable_read_outside_the_ring_is_rejected():
    """
    'floorplan' is a legal ring of one (a self-loop gated by itself) that
    schedules FP_CORE_UTIL. 'global_placement' also reads FP_CORE_UTIL and
    sits outside the ring.

    Exercised through the public validate_against_registry: the "loops are
    not executable yet" guard runs last, so this document's real load error
    (the schedule covering violation) surfaces before the guard would ever
    get a say.
    """
    spec = _spec(
        {
            "floorplan": {
                "needs": ["floorplan"],
                "uses": "floorplan",
                "until": "metric::x >= 0",
                "iterations": {"FP_CORE_UTIL": [40, 50]},
            },
            "global_placement": {
                "needs": ["floorplan"],
                "uses": "global_placement",
            },
        }
    )

    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(spec)

    message = str(exc_info.value)
    assert "floorplan" in message
    assert "FP_CORE_UTIL" in message
    assert "global_placement" in message
    assert "loops are not executable yet" not in message.lower()


def test_a_universal_variable_in_a_ring_schedule_is_rejected():
    """
    DIE_AREA is universal (every job reads it), so scheduling it inside a
    ring is refused as soon as the document has any job outside that ring,
    the same "reach ⊆ scope" rule as the non-universal case above. Exercised
    through the public entry point, same reasoning as above.
    """
    spec = _spec(
        {
            "floorplan": {
                "needs": ["floorplan"],
                "uses": "floorplan",
                "until": "metric::x >= 0",
                "iterations": {"DIE_AREA": ["0 0 100 100"]},
            },
            "global_placement": {
                "needs": ["floorplan"],
                "uses": "global_placement",
            },
        }
    )

    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(spec)

    message = str(exc_info.value)
    assert "DIE_AREA" in message
    assert "global_placement" in message
    assert "loops are not executable yet" not in message.lower()


def test_a_sweep_schedule_variable_read_outside_the_sweep_job_is_rejected():
    """
    A sweep is not a ring, so the "loops are not executable yet" guard does
    not apply, and this is exercised through the public entry point.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "floorplan": {"uses": "floorplan"},
                    "global_placement": {
                        "needs": ["floorplan"],
                        "uses": "global_placement",
                        "iterations": {"FP_CORE_UTIL": [40, 50]},
                        "select": "route__wirelength min",
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "global_placement" in message
    assert "FP_CORE_UTIL" in message
    assert "floorplan" in message


def test_a_str_resource_capacity_naming_an_undeclared_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {"drc": {"uses": "drc/magic"}},
                resources={"drc_seats": "MAX_DRC_SEATS"},
            )
        )

    message = str(exc_info.value)
    assert "drc_seats" in message
    assert "MAX_DRC_SEATS" in message


def test_a_str_resource_capacity_naming_a_non_int_variable_is_rejected():
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {"drc": {"uses": "drc/magic"}},
                resources={"drc_seats": "RUN_LINTER"},
                config=[
                    {
                        "name": "RUN_LINTER",
                        "type": "bool",
                        "description": "x",
                        "default": True,
                    }
                ],
            )
        )

    message = str(exc_info.value)
    assert "drc_seats" in message
    assert "RUN_LINTER" in message
    assert "bool" in message


def test_a_str_resource_capacity_naming_a_declared_int_variable_is_accepted():
    validate_against_registry(
        _spec(
            {"drc": {"uses": "drc/magic"}},
            resources={"drc_seats": "MAX_DRC_SEATS"},
            config=[
                {
                    "name": "MAX_DRC_SEATS",
                    "type": "int",
                    "description": "x",
                    "default": 2,
                }
            ],
        )
    )


def test_a_source_naming_a_framework_metric_is_accepted():
    """
    Every OpenROAD invocation writes the framework metrics and no registration
    mentions them, so two OpenROAD-backed branches meeting at one consumer
    disagree about them and
    :func:`librelane.engine.selection_validation.validate_selection` refuses the
    document naming the metric. ``source`` is the remedy that check honours, so
    the two checks here -- the registry check, which sees an unregistered
    metric, and the delivery check, which sees an undeclared one -- must both
    let it through, or the refusal has no answer.
    """
    validate_against_registry(
        _spec(
            {
                "floorplan": {"uses": "floorplan"},
                "cts": {"needs": ["floorplan"], "uses": "cts/openroad"},
                "magic_streamout": {
                    "needs": ["floorplan"],
                    "uses": "streamout/magic",
                },
                "join": {
                    "needs": ["cts", "magic_streamout"],
                    "uses": "drc/magic",
                    "source": {"flow__errors__count": "cts"},
                },
            }
        )
    )


def test_a_source_naming_a_framework_metric_no_branch_writes_is_rejected():
    """
    The exemption is not a blanket one: a branch with no OpenROAD- or
    Odbpy-backed step never writes the framework metrics, so sourcing one from
    it still names a value that never arrives.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        validate_against_registry(
            _spec(
                {
                    "synthesis": {"uses": "synthesis/yosys"},
                    "lint": {"uses": "lint/verilator"},
                    "join": {
                        "needs": ["synthesis", "lint"],
                        "uses": "floorplan",
                        "source": {"flow__errors__count": "lint"},
                    },
                }
            )
        )

    message = str(exc_info.value)
    assert "flow__errors__count" in message
    assert "lint" in message
