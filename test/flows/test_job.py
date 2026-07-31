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

import librelane.steps  # noqa: F401  populates Step.factory and StageRegistry

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec
from librelane.stages import Stage, StageRegistry
from librelane.state import DesignFormat
from librelane.steps import Step

pytestmark = pytest.mark.all


def _spec(jobs: dict, config: list | None = None) -> FlowSpec:
    return FlowSpec.model_validate(
        {"name": "Tiny", "config": config or [], "jobs": jobs}
    )


def _bool_var(name: str) -> dict:
    return {"name": name, "type": "bool", "description": name}


def test_a_uses_job_takes_its_steps_from_the_named_provider():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))

    job = jobs["synthesis"]
    assert job.provider == "yosys"
    # Asserted against the registration itself. The provider's steps are
    # Yosys.JsonHeader, Yosys.Synthesis and three Checker.* classes, so a
    # prefix assertion on 'Yosys.' would be false.
    assert job.steps == tuple(StageRegistry.get("synthesis", "yosys").steps)


def test_a_bare_uses_takes_the_stage_default_provider():
    named = resolve_jobs(_spec({"floorplan": {"uses": "floorplan/openroad"}}))
    bare = resolve_jobs(_spec({"floorplan": {"uses": "floorplan"}}))

    assert bare["floorplan"].steps == named["floorplan"].steps
    assert bare["floorplan"].provider == "openroad"


def test_a_bare_uses_on_a_multi_provider_stage_concatenates_every_default():
    # 'streamout' is multi_provider with default_providers ('magic', 'klayout'),
    # so a bare 'uses' means both, in order. Taking only the first would drop
    # KLayout.StreamOut and with it the klayout_gds view the XOR job reads.
    bare = resolve_jobs(_spec({"streamout": {"uses": "streamout"}}))["streamout"]

    assert bare.steps == tuple(StageRegistry.get("streamout", "magic").steps) + tuple(
        StageRegistry.get("streamout", "klayout").steps
    )
    assert bare.provider == "magic+klayout"


def test_a_uses_job_inherits_the_stage_contract():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))
    job = jobs["synthesis"]
    registration = StageRegistry.get("synthesis", "yosys")

    # Stage.synthesis.requires is empty, so an equality assertion against it
    # would be vacuous. Assert the union rule itself instead.
    assert job.requires == Stage.synthesis.requires
    assert set(job.provides) == set(Stage.synthesis.provides) | set(
        registration.provides
    )
    assert set(job.metrics) == set(Stage.synthesis.metrics) | set(registration.metrics)
    assert DesignFormat.nl in job.provides
    assert DesignFormat.json_h in job.provides


def test_an_inline_job_derives_its_contract_from_its_steps():
    jobs = resolve_jobs(_spec({"custom": {"steps": ["Odb.SetPowerConnections"]}}))

    step = Step.factory.get("Odb.SetPowerConnections")
    assert jobs["custom"].steps == (step,)
    assert jobs["custom"].provider is None
    assert set(jobs["custom"].requires) == set(step.inputs)
    assert set(jobs["custom"].provides) == set(step.outputs)
    assert jobs["custom"].metrics == ()


def test_needs_and_a_single_condition_carry_through():
    jobs = resolve_jobs(
        _spec(
            {
                "synthesis": {"uses": "synthesis/yosys"},
                "floorplan": {
                    "needs": ["synthesis"],
                    "uses": "floorplan",
                    "if": "RUN_FLOORPLAN",
                },
            },
            config=[_bool_var("RUN_FLOORPLAN")],
        )
    )

    assert jobs["floorplan"].needs == ("synthesis",)
    assert jobs["floorplan"].conditions == ("RUN_FLOORPLAN",)
    assert jobs["synthesis"].needs == ()
    assert jobs["synthesis"].conditions == ()


def test_a_conjunction_becomes_one_entry_per_conjunct():
    jobs = resolve_jobs(
        _spec(
            {
                "xor": {
                    "steps": ["KLayout.XOR", "Checker.XOR"],
                    "if": (
                        "RUN_KLAYOUT_XOR and RUN_MAGIC_STREAMOUT "
                        "and RUN_KLAYOUT_STREAMOUT"
                    ),
                }
            },
            config=[
                _bool_var("RUN_KLAYOUT_XOR"),
                _bool_var("RUN_MAGIC_STREAMOUT"),
                _bool_var("RUN_KLAYOUT_STREAMOUT"),
            ],
        )
    )

    assert jobs["xor"].conditions == (
        "RUN_KLAYOUT_XOR",
        "RUN_MAGIC_STREAMOUT",
        "RUN_KLAYOUT_STREAMOUT",
    )


def test_source_keys_carry_through_as_declared_strings():
    jobs = resolve_jobs(
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
                    "steps": ["KLayout.XOR", "Checker.XOR"],
                    "source": {"gds": "klayout_streamout"},
                },
            }
        )
    )

    # A source key may name a metric as well as a view, so it stays a string.
    assert jobs["xor"].source == {"gds": "klayout_streamout"}
