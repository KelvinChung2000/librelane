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
from librelane.flows.spec import FlowSpec, FlowSpecError
from librelane.flows.spec_validation import validate_against_registry

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
