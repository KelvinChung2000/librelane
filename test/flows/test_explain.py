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

from librelane.flows import flow as flow_module, sequential as sequential_module
from librelane.steps import step as step_module
from test.conftest import COMMON_FLOW_VARS, MockConfTree

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _bool_var(name: str, default: bool) -> dict:
    return {
        "name": name,
        "type": "bool",
        "description": "x",
        "default": default,
    }


@mock_variables([flow_module, sequential_module, step_module])
def test_every_step_of_an_unconstrained_flow_will_run(
    MetricIncrementer, minimal_design, mock_pdk
):
    from librelane.flows import SequentialFlow

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer]

    explanation = Dummy(minimal_design, **mock_pdk).explain()

    assert [d.step_id for d in explanation.steps] == ["Test.MetricIncrementer"]
    assert all(d.will_run for d in explanation.steps)
    assert all(d.mechanism is None for d in explanation.steps)
    assert explanation.unselected_jobs == ()
    # A SequentialFlow has jobs no more than a Workflow has stages, and the new
    # field defaults so that the two halves can ship side by side until phase 5
    # deletes this one.
    assert explanation.jobs == ()


@mock_variables([flow_module, sequential_module, step_module])
def test_a_gated_step_names_its_gate(MetricIncrementer, minimal_design, mock_pdk):
    from librelane.config import Variable
    from librelane.flows import SequentialFlow

    class Gated(MetricIncrementer):
        id = "Test.ExplainGated"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Gated]

        config_vars = [Variable("TEST_GATE", bool, description="x", default=False)]

        gating_config_vars = {"Test.ExplainGated": ["TEST_GATE"]}

    explanation = Dummy(minimal_design, **mock_pdk).explain()

    gated = explanation.steps[1]
    assert gated.step_id == "Test.ExplainGated"
    assert gated.will_run is False
    assert gated.mechanism == "gate"
    assert "TEST_GATE" in gated.reason


@mock_variables([flow_module, sequential_module, step_module])
def test_skip_and_window_attribute_correctly(
    MetricIncrementer, minimal_design, mock_pdk
):
    from librelane.flows import SequentialFlow

    class Second(MetricIncrementer):
        id = "Test.ExplainSecond"

    class Third(MetricIncrementer):
        id = "Test.ExplainThird"

    class Fourth(MetricIncrementer):
        id = "Test.ExplainFourth"

    class Dummy(SequentialFlow):
        Steps = [MetricIncrementer, Second, Third, Fourth]

    explanation = Dummy(minimal_design, **mock_pdk).explain(
        frm="Test.ExplainSecond",
        to="Test.ExplainThird",
        skip=["Test.ExplainSecond"],
    )

    by_id = {d.step_id: d for d in explanation.steps}
    assert by_id["Test.MetricIncrementer"].mechanism == "window"
    assert "--from" in by_id["Test.MetricIncrementer"].reason
    assert by_id["Test.ExplainSecond"].mechanism == "skip"
    assert by_id["Test.ExplainThird"].will_run is True
    assert by_id["Test.ExplainFourth"].mechanism == "window"
    assert "--to" in by_id["Test.ExplainFourth"].reason


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_deselected_provider_s_steps_are_absent_not_excluded(mock_config):
    """
    A step dropped by TOOLS is not in the resolved list at all, so it has no
    entry. Provider selection is therefore not among the mechanisms a step
    entry can carry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values.update({"RUN_KLAYOUT_XOR": False, "TOOLS": {"streamout": "klayout"}})
    flow = Classic(mock_config.copy(**values))

    explanation = flow.explain()
    ids = [d.step_id for d in explanation.steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_turning_off_run_cts_excludes_every_step_of_the_job(mock_config):
    """
    A job gate is lowered onto each step of the job, so every step of the
    cts job reports the same gate. This is the case a user actually hits,
    and the one describe_jobs cannot answer.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    values["RUN_CTS"] = False
    flow = Classic(mock_config.copy(**values))

    cts = [
        d
        for d in flow.explain().steps
        if d.mechanism == "gate" and "RUN_CTS" in d.reason
    ]
    assert [d.step_id for d in cts] == ["OpenROAD.CTS"]
    assert all(d.will_run is False for d in cts)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_an_unselected_job_is_reported_separately(mock_config):
    """
    Job.post_route_opt has a None default provider, so it contributes no
    steps and cannot be a step entry.
    """
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    values = {v.name: v.default for v in Classic.config_vars}
    flow = Classic(mock_config.copy(**values))

    assert "post_route_opt" in flow.explain().unselected_jobs


def test_format_explanation_renders_every_row():
    from librelane.cli.run import format_explanation
    from librelane.flows import Explanation, StepDisposition

    rendered = format_explanation(
        Explanation(
            steps=(
                StepDisposition("Test.Alpha", True, "will run", None),
                StepDisposition("Test.Beta", False, "gated off by RUN_BETA", "gate"),
            ),
            unselected_jobs=("post_route_opt",),
        )
    )

    assert "Test.Alpha" in rendered
    assert "Test.Beta" in rendered
    assert "RUN_BETA" in rendered
    assert "gate" in rendered
    assert "post_route_opt" in rendered


@mock_variables([flow_module, step_module])
def test_explain_names_the_condition_that_stops_a_job(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {"first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}},
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    first = explanation.jobs[0]
    assert first.job_id == "first"
    assert first.will_run is False
    assert first.mechanism == "condition"
    assert "RUN_FIRST" in first.reason


@mock_variables([flow_module, step_module])
def test_explain_marks_jobs_outside_the_target_subgraph(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(target=["first"])

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is True
    assert by_id["second"].mechanism == "not-in-target"
    assert by_id["second"].needs == ("first",)


@mock_variables([flow_module, step_module])
def test_explain_names_skip_as_the_mechanism_that_stopped_a_job(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``--skip`` and a false ``if`` both fire the job as pass-through, so the
    two are told apart by the mechanism and not by the outcome. A skipped job
    with a true condition would otherwise be indistinguishable from one whose
    condition happened to be false.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", True)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(skip=["first"])

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is False
    assert by_id["first"].mechanism == "skip"
    assert "--skip" in by_id["first"].reason
    # The skipped job still fires, so its successor is untouched. Nothing in
    # the graph is suppressed by a skip, only the job's own steps.
    assert by_id["second"].will_run is True
    assert by_id["second"].mechanism is None


@mock_variables([flow_module, step_module])
def test_explain_reports_a_row_for_every_job_the_document_declares(
    counting_steps, minimal_design, mock_pdk
):
    """
    The shape of the sample table in the workflow engine design document, job
    for job. Every declared job has a row, including the two that will not
    run: an explanation that reported only the jobs that will run could not
    answer the question the sample is there to answer, which is why a job the
    author expected is missing from the run.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Sample",
            "config": [
                _bool_var("RUN_KLAYOUT_STREAMOUT", False),
                _bool_var("RUN_KLAYOUT_XOR", False),
            ],
            "jobs": {
                "lint": {"steps": ["Test.EngineFirst"]},
                "synthesis": {"needs": ["lint"], "steps": ["Test.EngineSecond"]},
                "magic_streamout": {
                    "needs": ["synthesis"],
                    "steps": ["Test.EngineFirst"],
                },
                "klayout_streamout": {
                    "needs": ["magic_streamout"],
                    "steps": ["Test.EngineSecond"],
                    "if": "RUN_KLAYOUT_STREAMOUT",
                },
                "xor": {
                    "needs": ["magic_streamout", "klayout_streamout"],
                    "steps": ["Test.EngineFirst"],
                    "if": "RUN_KLAYOUT_XOR",
                },
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    rows = {
        d.job_id: (d.will_run, d.mechanism, d.needs, d.reason) for d in explanation.jobs
    }
    assert rows == {
        "lint": (True, None, (), "will run"),
        "synthesis": (True, None, ("lint",), "will run"),
        "magic_streamout": (True, None, ("synthesis",), "will run"),
        "klayout_streamout": (
            False,
            "condition",
            ("magic_streamout",),
            "'RUN_KLAYOUT_STREAMOUT' is false",
        ),
        "xor": (
            False,
            "condition",
            ("magic_streamout", "klayout_streamout"),
            "'RUN_KLAYOUT_XOR' is false",
        ),
    }


@mock_variables([flow_module, step_module])
def test_explain_orders_its_rows_topologically(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
                "first": {"steps": ["Test.EngineFirst"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    assert [d.job_id for d in explanation.jobs] == ["first", "second"]


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_skip_that_the_target_already_excluded(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``run`` refuses the same pair, and an explanation that answered where the
    run would raise would be describing an invocation that cannot happen.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="outside the --target subgraph"):
        flow.explain(target=["first"], skip=["second"])


@mock_variables([flow_module, step_module])
def test_explain_refuses_an_undeclared_job(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="--target names 'nope'"):
        flow.explain(target=["nope"])


def _classic_workflow(mock_conf_dir: MockConfTree):
    """
    The shipped ``classic.yaml`` bound to a stock configuration.

    Built here rather than from the ``mock_config`` fixture because that
    fixture resolves against pyfakefs, and a test that constructs a
    ``Workflow`` may not use pyfakefs at all: the engine runs its jobs on a
    thread pool and pyfakefs is single-threaded by design.

    Parameters
    ----------
    mock_conf_dir : MockConfTree
        The real-filesystem mock tree.

    Returns
    -------
    librelane.flows.engine.Workflow
        The Classic document, configured with every declared variable at its
        default.
    """
    from librelane.config import Config
    from librelane.flows import Flow
    from librelane.flows.engine import Workflow

    base, _ = Config.load(
        {"DESIGN_NAME": "whatever", "VERILOG_FILES": "dir::src/*.v"},
        COMMON_FLOW_VARS,
        design_dir=mock_conf_dir.cwd,
        pdk="dummy",
        scl="dummy_scl",
        pdk_root=mock_conf_dir.pdk_root,
    )
    Classic = Flow.factory.get("Classic")
    defaults = {variable.name: variable.default for variable in Classic.config_vars}
    return Workflow(Flow.factory.get_document("Classic"), base.copy(**defaults))


@mock_variables([flow_module, sequential_module, step_module])
def test_explain_reports_every_job_of_the_classic_document(mock_conf_dir):
    """
    The no-suppression guard, on a real 48-job document rather than a
    hand-built pair. A row per declared job is what makes the table answer
    "why is this job not in my run", and the tests above could all pass while
    a filter quietly dropped the jobs a user is looking for.
    """
    from librelane.flows import Flow

    spec = Flow.factory.get_document("Classic")
    explanation = _classic_workflow(mock_conf_dir).explain()

    # Sorted, not in document order: the rows are topologically ordered, which
    # test_explain_orders_its_rows_topologically pins. What is asserted here is
    # that no job is missing and none is reported twice.
    assert sorted(d.job_id for d in explanation.jobs) == sorted(spec.jobs)
    gated = {d.job_id: d for d in explanation.jobs if d.mechanism == "condition"}
    assert gated, "a stock Classic configuration leaves RUN_RMP and RUN_EQY off"
    assert all(d.will_run is False for d in gated.values())


@mock_variables([flow_module, sequential_module, step_module])
def test_explain_keeps_every_row_when_a_target_narrows_the_classic_document(
    mock_conf_dir,
):
    """
    ``--target`` narrows what runs and not what is reported. A job it excluded
    is exactly the job someone is about to ask after.
    """
    from librelane.flows import Flow

    spec = Flow.factory.get_document("Classic")
    explanation = _classic_workflow(mock_conf_dir).explain(target=["floorplan"])

    by_id = {d.job_id: d for d in explanation.jobs}
    assert set(by_id) == set(spec.jobs)
    assert by_id["floorplan"].will_run is True
    assert by_id["lint"].will_run is True
    assert by_id["final_checks"].mechanism == "not-in-target"
