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

import librelane.steps  # noqa: F401  registers mag_gds and klayout_gds

from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.engine.join import (
    JoinConflictError,
    join_sink_states,
    join_states,
)
from librelane.state import DesignFormat, State

pytestmark = pytest.mark.all


def _magic_streamout() -> State:
    """The views Magic.StreamOut declares, as it would leave them."""
    return State(
        {
            DesignFormat.gds: Path("/runs/t/magic_streamout/1-magic-streamout/a.gds"),
            DesignFormat.mag_gds: Path(
                "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
            ),
        }
    )


def _klayout_streamout() -> State:
    """The views KLayout.StreamOut declares, as it would leave them."""
    return State(
        {
            DesignFormat.gds: Path(
                "/runs/t/klayout_streamout/1-klayout-streamout/a.gds"
            ),
            DesignFormat.klayout_gds: Path(
                "/runs/t/klayout_streamout/1-klayout-streamout/a.klayout.gds"
            ),
        }
    )


def test_a_single_token_is_returned_unchanged():
    only = State({DesignFormat.nl: Path("/a/design.nl.v")}, metrics={"x": 1})

    joined = join_states({"synthesis": only}, {}, "floorplan")

    assert joined[DesignFormat.nl] == Path("/a/design.nl.v")
    assert joined.metrics == {"x": 1}


def test_identical_values_from_two_branches_merge_silently():
    shared = Path("/a/design.def")
    left = State({DesignFormat.def_: shared}, metrics={"shared": 1, "left": 2})
    right = State({DesignFormat.def_: shared}, metrics={"shared": 1, "right": 3})

    joined = join_states({"drc": left, "lvs": right}, {}, "xor")

    assert joined[DesignFormat.def_] == shared
    assert joined.metrics == {"shared": 1, "left": 2, "right": 3}


def test_the_two_streamout_providers_conflict_on_gds():
    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
            },
            {},
            "xor",
        )

    message = str(exc_info.value)
    assert "xor" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    assert "gds" in message
    assert "source" in message


def test_a_declared_source_picks_one_gds_and_keeps_both_native_views():
    joined = join_states(
        {
            "magic_streamout": _magic_streamout(),
            "klayout_streamout": _klayout_streamout(),
        },
        {"gds": "klayout_streamout"},
        "xor",
    )

    assert joined[DesignFormat.gds] == Path(
        "/runs/t/klayout_streamout/1-klayout-streamout/a.gds"
    )
    # mag_gds and klayout_gds are what KLayout.XOR actually consumes, and
    # neither is in conflict, so selecting gds must not drop either.
    assert joined[DesignFormat.mag_gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
    )
    assert joined[DesignFormat.klayout_gds] == Path(
        "/runs/t/klayout_streamout/1-klayout-streamout/a.klayout.gds"
    )


def test_differing_metrics_conflict_under_the_same_rule():
    left = State({}, metrics={"magic__drc_error__count": 100})
    right = State({}, metrics={"magic__drc_error__count": 200})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states({"early_drc": left, "late_drc": right}, {}, "signoff")

    message = str(exc_info.value)
    assert "magic__drc_error__count" in message
    assert "early_drc" in message
    assert "late_drc" in message


def test_a_declared_source_selects_one_producer_of_a_metric():
    left = State({}, metrics={"magic__drc_error__count": 100})
    right = State({}, metrics={"magic__drc_error__count": 200})

    joined = join_states(
        {"early_drc": left, "late_drc": right},
        {"magic__drc_error__count": "late_drc"},
        "signoff",
    )

    assert joined.metrics == {"magic__drc_error__count": 200}


def test_a_source_is_ignored_when_only_one_predecessor_carries_the_key():
    # phase 4's classic.yaml, with RUN_KLAYOUT_STREAMOUT false. Both
    # predecessors fired, but the gated one passed its input state through and
    # carries no gds, so nothing is in conflict and Magic's gds is taken even
    # though 'source' names the other job.
    gated_off = State({})

    joined = join_states(
        {"magic_streamout": _magic_streamout(), "klayout_streamout": gated_off},
        {"gds": "klayout_streamout"},
        "magic_drc",
    )

    assert joined[DesignFormat.gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.gds"
    )
    assert joined[DesignFormat.mag_gds] == Path(
        "/runs/t/magic_streamout/1-magic-streamout/a.magic.gds"
    )


def test_a_source_naming_a_job_that_contributed_nothing_to_the_conflict_raises():
    # Two producers genuinely disagree on gds, so 'source' is read, and it
    # names a third predecessor that carried no gds at all. Nothing selects it,
    # and silently dropping the view would be worse than saying so.
    gated_off = State({})

    with pytest.raises(JoinConflictError) as exc_info:
        join_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
                "render": gated_off,
            },
            {"gds": "render"},
            "xor",
        )

    message = str(exc_info.value)
    assert "render" in message
    assert "gds" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message


def test_a_join_of_no_tokens_names_the_job_rather_than_returning_nothing():
    # Unreachable from a document today -- every job has at least one input
    # place -- but an empty State returned here is a silently defaulted input,
    # and a silent default is the one thing this phase does not do.
    with pytest.raises(FlowError) as exc_info:
        join_states({}, {}, "floorplan")

    assert "floorplan" in str(exc_info.value)


def test_a_sink_join_of_no_tokens_names_the_flow_rather_than_returning_nothing():
    with pytest.raises(FlowError) as exc_info:
        join_sink_states({}, "Classic")

    assert "Classic" in str(exc_info.value)


def test_a_single_sink_token_is_returned_unchanged():
    only = State({DesignFormat.nl: Path("/a/design.nl.v")}, metrics={"x": 1})

    joined = join_sink_states({"synthesis": only}, "Classic")

    assert joined[DesignFormat.nl] == Path("/a/design.nl.v")


def test_two_sinks_that_agree_merge_exactly_as_a_job_join_does():
    shared = Path("/a/design.def")
    left = State({DesignFormat.def_: shared}, metrics={"left": 2})
    right = State({DesignFormat.def_: shared}, metrics={"right": 3})

    joined = join_sink_states({"drc": left, "lvs": right}, "Classic")

    assert joined[DesignFormat.def_] == shared
    assert joined.metrics == {"left": 2, "right": 3}


def test_a_sink_conflict_prescribes_final_and_not_source():
    with pytest.raises(JoinConflictError) as exc_info:
        join_sink_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
            },
            "Classic",
        )

    message = str(exc_info.value)
    assert "gds" in message
    assert "magic_streamout" in message
    assert "klayout_streamout" in message
    # The remedy has to be the one that exists. No job's 'source' can settle a
    # sink conflict, because the sink is not a job and has no 'source' to read;
    # the document's top-level 'final' key is the only thing that can.
    assert "final: magic_streamout" in message
    assert "source: {" not in message
    assert "Job '" not in message
    assert "flow 'Classic'" in message


def test_a_sink_conflict_under_a_target_says_the_final_was_excluded():
    """
    A document that already declares ``final: signoff``, run with ``--target``
    narrowed away from it, hits this join with its declared remedy in place and
    unusable. Prescribing a ``final`` the document has and the run excluded
    would send the reader to a line of YAML that is already correct.
    """
    with pytest.raises(JoinConflictError) as exc_info:
        join_sink_states(
            {
                "magic_streamout": _magic_streamout(),
                "klayout_streamout": _klayout_streamout(),
            },
            "Classic",
            excluded_final="signoff",
        )

    message = str(exc_info.value)
    assert "signoff" in message
    assert "--target" in message
    # The document's own remedy is not repeated: it is already declared.
    assert "final: magic_streamout" not in message


def test_a_sink_conflict_on_a_metric_reads_the_same_way():
    left = State({}, metrics={"magic__drc_error__count": 100})
    right = State({}, metrics={"magic__drc_error__count": 200})

    with pytest.raises(JoinConflictError) as exc_info:
        join_sink_states({"early_drc": left, "late_drc": right}, "Classic")

    message = str(exc_info.value)
    assert "metric 'magic__drc_error__count'" in message
    assert "final: " in message
