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

from librelane.flows.job import resolve_jobs
from librelane.flows.spec import FlowSpec
from librelane.jobs import Job, JobRegistry, JobResolutionError
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
    # Asserted against the registration itself rather than by name, so that
    # the test says "whatever the provider registered" and not a second copy
    # of the list.
    assert job.steps == tuple(JobRegistry.get("synthesis", "yosys").steps)


def test_a_bare_uses_takes_the_template_default_provider():
    named = resolve_jobs(_spec({"floorplan": {"uses": "floorplan/openroad"}}))
    bare = resolve_jobs(_spec({"floorplan": {"uses": "floorplan"}}))

    assert bare["floorplan"].steps == named["floorplan"].steps
    assert bare["floorplan"].provider == "openroad"


def test_a_job_that_omits_uses_resolves_against_its_own_id():
    # The document's central convenience rule, and the reason the spec's own
    # sample 'classic.yaml' writes 'lint:' and 'floorplan:' with nothing under
    # them. JobSpec deliberately does not reject a job declaring neither 'uses'
    # nor 'steps' -- the template ids live in the job registry, which the
    # model layer does not import -- and spec_validation._require_implementation
    # admits it whenever the id resolves, so 'uses' really is still None here.
    implicit = resolve_jobs(_spec({"floorplan": {}}))
    explicit = resolve_jobs(_spec({"floorplan": {"uses": "floorplan"}}))

    assert implicit["floorplan"].steps == explicit["floorplan"].steps
    assert implicit["floorplan"].provider == explicit["floorplan"].provider
    assert implicit["floorplan"].provides == explicit["floorplan"].provides
    assert implicit["floorplan"].metrics == explicit["floorplan"].metrics


def test_a_uses_job_inherits_the_template_contract():
    jobs = resolve_jobs(_spec({"synthesis": {"uses": "synthesis/yosys"}}))
    job = jobs["synthesis"]
    registration = JobRegistry.get("synthesis", "yosys")

    # Job.synthesis.requires is empty, so an equality assertion against it
    # would be vacuous. Assert the union rule itself instead.
    assert job.requires == Job.synthesis.requires
    assert set(job.provides) == set(Job.synthesis.provides) | set(registration.provides)
    assert set(job.metrics) == set(Job.synthesis.metrics) | set(registration.metrics)
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
                    "steps": ["KLayout.XOR"],
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


def test_tools_overrides_the_provider_half_of_uses():
    """
    The pin is the document's default, not a lock. The Python flows' own pin
    had the same property -- it kept the job's id, so a ``TOOLS`` entry naming
    that id still won -- and the document's ``uses`` inherits it. The template
    half is never overridden: the job keeps the name the document gave it.
    """
    jobs = resolve_jobs(
        _spec({"magic_streamout": {"uses": "streamout/magic"}}),
        {"magic_streamout": "klayout"},
    )

    assert jobs["magic_streamout"].provider == "klayout"
    assert [step.id for step in jobs["magic_streamout"].steps] == ["KLayout.StreamOut"]


def test_tools_overrides_a_job_that_omits_uses():
    # An omitted 'uses' resolves against the job id, so the override has to
    # reach that path too rather than only the explicit one.
    jobs = resolve_jobs(_spec({"lvs": {}}), {"lvs": "klayout"})

    assert jobs["lvs"].provider == "klayout"
    assert [step.id for step in jobs["lvs"].steps] == [
        "OpenROAD.WriteCDL",
        "KLayout.LVS",
    ]


def test_a_job_tools_does_not_name_keeps_the_provider_it_declared():
    jobs = resolve_jobs(
        _spec(
            {
                "magic_streamout": {"uses": "streamout/magic"},
                "klayout_streamout": {"uses": "streamout/klayout"},
            }
        ),
        {"klayout_streamout": "klayout"},
    )

    assert jobs["magic_streamout"].provider == "magic"


def test_tools_naming_an_undeclared_job_is_rejected():
    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(
            _spec({"synthesis": {"uses": "synthesis/yosys"}}),
            {"synthesys": "yosys_vhdl"},
        )

    assert "synthesys" in str(exc_info.value)
    assert "synthesis" in str(exc_info.value)


def test_tools_naming_a_stage_id_that_is_no_job_of_the_document_is_rejected():
    """
    The consequence of one stage running under two job names. ``classic.yaml``
    declares ``magic_streamout`` and ``klayout_streamout``, so the template id
    ``streamout`` is no job's id and a configuration written against the old
    stage-keyed TOOLS names nothing. Rejected with the near-miss suggestion,
    rather than being spread over both jobs: the two are gated by two
    independent booleans and re-pointing both at one tool is not what the
    old key meant.
    """
    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(
            _spec(
                {
                    "magic_streamout": {"uses": "streamout/magic"},
                    "klayout_streamout": {"uses": "streamout/klayout"},
                }
            ),
            {"streamout": "klayout"},
        )

    message = str(exc_info.value)
    assert "streamout" in message
    assert "Did you mean" in message


def test_tools_naming_an_inline_job_is_rejected():
    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(_spec({"xor": {"steps": ["KLayout.XOR"]}}), {"xor": "klayout"})

    assert "xor" in str(exc_info.value)
    assert "steps" in str(exc_info.value)


def test_tools_naming_a_list_is_rejected():
    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(
            _spec({"streamout": {"uses": "streamout/magic"}}),
            {"streamout": ["magic", "klayout"]},
        )

    assert "streamout" in str(exc_info.value)


def test_tools_naming_an_unregistered_provider_is_rejected():
    """
    Nothing validates a TOOLS-supplied provider before this point:
    ``validate_against_registry`` checks the providers the *document* names.
    So the lookup raises rather than asserting, and never falls back to the
    provider the document declared.
    """
    with pytest.raises(JobResolutionError) as exc_info:
        resolve_jobs(
            _spec({"synthesis": {"uses": "synthesis/yosys"}}),
            {"synthesis": "no_such_tool"},
        )

    message = str(exc_info.value)
    assert "no_such_tool" in message
    assert "yosys" in message


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
                    "steps": ["KLayout.XOR"],
                    "source": {"gds": "klayout_streamout"},
                },
            }
        )
    )

    # A source key may name a metric as well as a view, so it stays a string.
    assert jobs["xor"].source == {"gds": "klayout_streamout"}
