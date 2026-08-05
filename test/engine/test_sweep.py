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
Sweeps: a job declaring ``select`` runs its steps at every point of its
``iterations`` matrix, concurrently, and keeps the best pass by that metric.

Fake steps throughout, no real tools -- the same style ``test_loops.py`` and
``test_engine.py`` use.
"""

import pytest

from librelane.engine import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def sweep_steps():
    """
    The step vocabulary every test below composes a sweep document out of.

    Returns
    -------
    A namespace object exposing:

    - ``calls``: every step instance's own ``id`` (not the class id), in the
      order it ran, so a test can assert a pass ran and which pass it carried
      in its id.
    - ``Score``: writes metric ``score`` from configuration
      ``SWEEP_SCORE``, unless ``SWEEP_WRITE_SCORE`` is false, in which case it
      writes nothing -- the missing-select-metric case. Also writes metric
      ``tag`` from ``SWEEP_TAG``, so a winning pass is identifiable by
      something the metric comparison itself does not touch.
    - ``MaybeDefer``: a no-op unless configuration ``SWEEP_DEFER`` is true, in
      which case it defers an error. Ordered after ``Score`` in every job that
      uses both, so a pass that defers still carries the metric ``Score``
      already wrote.
    - ``MaybeFail``: a no-op unless configuration ``SWEEP_FAIL`` is true, in
      which case it raises, failing the pass (and the whole sweep) outright.
    """
    from librelane.config import variable
    from librelane.steps import DeferredStepError, Step
    from librelane.steps.step.exceptions import StepError

    class _Namespace:
        pass

    ns = _Namespace()
    ns.calls = []

    @Step.factory.register()
    class Score(Step):
        id = "Test.SweepScore"
        inputs = []
        outputs = []

        class Config(Step.Config):
            SWEEP_SCORE: int = variable(description="x", default=0)
            SWEEP_TAG: str = variable(description="tag", default="")
            SWEEP_WRITE_SCORE: bool = variable(
                description="whether to write the select metric", default=True
            )

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            metrics = {"tag": self.config["SWEEP_TAG"]}
            if self.config["SWEEP_WRITE_SCORE"]:
                metrics["score"] = self.config["SWEEP_SCORE"]
            return {}, metrics

    @Step.factory.register()
    class MaybeDefer(Step):
        id = "Test.SweepMaybeDefer"
        inputs = []
        outputs = []

        class Config(Step.Config):
            SWEEP_DEFER: bool = variable(description="defer", default=False)

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            if self.config["SWEEP_DEFER"]:
                raise DeferredStepError("deferred on purpose")
            return {}, {}

    @Step.factory.register()
    class MaybeFail(Step):
        id = "Test.SweepMaybeFail"
        inputs = []
        outputs = []

        class Config(Step.Config):
            SWEEP_FAIL: bool = variable(description="fail", default=False)

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            if self.config["SWEEP_FAIL"]:
                raise StepError("failed on purpose")
            return {}, {}

    @Step.factory.register()
    class BoolScore(Step):
        """
        Writes the select metric 'score' as a literal Python ``bool``, not
        derived from a configuration variable: an ``int``-typed variable
        already refuses a ``bool`` value on the way in
        (:class:`librelane.config.variable.Variable`), so this is the only way
        to get one into a state's metrics at all, the way a hand-written
        ``metrics.json`` containing JSON ``true`` would.
        """

        id = "Test.SweepBoolScore"
        inputs = []
        outputs = []

        class Config(Step.Config):
            # Read by nothing but the sweep matrix: a sweep declares points,
            # and a point is a value of some variable the job reads.
            SWEEP_BOOL_POINT: int = variable(description="point", default=0)

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {"score": True}

    ns.Score = Score
    ns.MaybeDefer = MaybeDefer
    ns.MaybeFail = MaybeFail
    ns.BoolScore = BoolScore
    return ns


@pytest.fixture
def sweep_contract_job():
    """
    A ``uses`` job template, with one provider whose promised view
    (``DesignFormat.nl``) is withheld whenever configuration
    ``SWEEP_CONTRACT_DROP_VIEW`` is true -- so a document can drop it on
    exactly one sweep pass and exercise the per-pass contract check.

    Registered fresh (function-scoped, unlike ``test_engine.py``'s module-
    scoped ``contract_job``) because only one test in this module needs it.
    """
    import pathlib

    from librelane.config import variable
    from librelane.jobs import Job, JobRegistry
    from librelane.state import DesignFormat
    from librelane.steps import Step

    Job(
        id="sweep_contract",
        full_name="Sweep Contract",
        default_provider="varies",
        requires=(),
        provides=(DesignFormat.nl,),
        metrics=(),
    ).register()

    @Step.factory.register()
    class Varies(Step):
        id = "Test.SweepContractVaries"
        inputs = []
        outputs = [DesignFormat.nl]

        class Config(Step.Config):
            SWEEP_CONTRACT_SCORE: int = variable(description="x", default=0)
            SWEEP_CONTRACT_DROP_VIEW: bool = variable(
                description="drop the promised view", default=False
            )

        def run(self, state_in, **kwargs):
            metrics = {"score": self.config["SWEEP_CONTRACT_SCORE"]}
            if self.config["SWEEP_CONTRACT_DROP_VIEW"]:
                return {}, metrics
            out = pathlib.Path(self.step_dir) / "design.nl.v"
            out.write_text("module top(); endmodule")
            return {DesignFormat.nl: out}, metrics

    JobRegistry.register(
        job="sweep_contract",
        provider="varies",
        steps=[Varies],
        namespaces=["SWEEP_CONTRACT_"],
    )
    return Varies


@pytest.fixture
def three_workers():
    """
    Pins the process-wide pool to three workers for one test: enough to run
    a 3-point sweep's passes at once, which is exactly what the concurrency
    test below needs to observe.
    """
    from librelane.common import ContextPropagatingThreadPoolExecutor, get_tpe, set_tpe

    previous = get_tpe()
    pool = ContextPropagatingThreadPoolExecutor(max_workers=3)
    set_tpe(pool)
    yield
    set_tpe(previous)
    pool.shutdown()


def _sweep_spec(iterations, select="score min", steps=None, name="Sweep"):
    return {
        "name": name,
        "jobs": {
            "sweep": {
                "steps": steps or ["Test.SweepScore"],
                "select": select,
                "iterations": iterations,
            },
        },
    }


@mock_variables([flow_module, step_module])
def test_sweep_keeps_the_pass_with_the_minimum_select_metric(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [30, 10, 20]}, select="score min")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert final.metrics["score"] == 10


@mock_variables([flow_module, step_module])
def test_sweep_keeps_the_pass_with_the_maximum_select_metric(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [30, 10, 20]}, select="score max")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert final.metrics["score"] == 30


@mock_variables([flow_module, step_module])
def test_sweep_tie_breaks_to_the_lowest_pass_index(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [5], "SWEEP_TAG": ["first", "second"]},
            select="score min",
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert final.metrics["tag"] == "first"


@mock_variables([flow_module, step_module])
def test_a_missing_select_metric_fails_naming_job_pass_and_metric(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowError
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [1], "SWEEP_WRITE_SCORE": [True, False]},
            select="score min",
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "sweep" in message
    assert "pass 2" in message
    assert "score" in message


@mock_variables([flow_module, step_module])
def test_a_boolean_select_metric_fails_naming_the_pass_and_metric(
    sweep_steps, minimal_design, mock_pdk
):
    """
    bool is an int subclass, so a boolean 'select' metric would otherwise
    pass the numeric-type check and reach Decimal(str(True)) below it,
    raising a raw, unnamed decimal.InvalidOperation instead of the named
    refusal this pins.
    """
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowError
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_BOOL_POINT": [1]},
            select="score min",
            steps=["Test.SweepBoolScore"],
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "sweep" in message
    assert "pass 1" in message
    assert "score" in message
    assert "bool" in message


@mock_variables([flow_module, step_module])
def test_a_raised_pass_fails_the_sweep_naming_the_pass(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowError
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [1], "SWEEP_FAIL": [False, True]},
            select="score min",
            steps=["Test.SweepScore", "Test.SweepMaybeFail"],
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "sweep" in message
    assert "pass 2" in message
    assert "failed on purpose" in message


@mock_variables([flow_module, step_module])
def test_a_losing_pass_s_deferral_warns_and_does_not_fail_the_flow(
    caplog, sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [1], "SWEEP_DEFER": [False, True]},
            select="score min",
            steps=["Test.SweepScore", "Test.SweepMaybeDefer"],
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    # Both passes score 1, so the tie breaks to pass 1 and pass 2's deferral
    # never reaches the run's own deferred list: the flow completes.
    assert final.metrics["score"] == 1
    assert "Sweep pass 2 of 'sweep' (discarded) deferred" in caplog.text
    assert "deferred on purpose" in caplog.text


@mock_variables([flow_module, step_module])
def test_the_winning_pass_s_deferral_fails_the_flow(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowError
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [1], "SWEEP_DEFER": [True, False]},
            select="score min",
            steps=["Test.SweepScore", "Test.SweepMaybeDefer"],
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    # Both passes score 1, so the tie breaks to pass 1, which is the one that
    # deferred.
    assert "deferred on purpose" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_every_pass_is_contract_checked_even_a_losing_one(
    sweep_contract_job, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowError
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "SweepContract",
            "jobs": {
                "sweep": {
                    "uses": "sweep_contract/varies",
                    "select": "score max",
                    # Four points. The two that drop the promised view
                    # include the lowest-scoring one, which could never win
                    # the sweep: every pass is contract-checked, not just the
                    # winner.
                    "iterations": {
                        "SWEEP_CONTRACT_SCORE": [1, 2],
                        "SWEEP_CONTRACT_DROP_VIEW": [False, True],
                    },
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "sweep" in message
    assert "'nl'" in message
    assert "Provider: varies" in message


@mock_variables([flow_module, step_module])
def test_sweep_writes_a_pass_directory_per_point(sweep_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [1, 2, 3]}, select="score min")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # slugify("Test.SweepScore") is "test-sweepscore".
    for k in (1, 2, 3):
        assert (flow.run_dir / "1-sweep" / str(k) / "1-test-sweepscore").is_dir()


@mock_variables([flow_module, step_module])
def test_a_two_variable_matrix_sweeps_every_combination(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_SCORE": [10, 20], "SWEEP_TAG": ["a", "b"]},
            select="score max",
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    # Four points, the variable named last varying fastest: (10, a), (10, b),
    # (20, a), (20, b). Two of them score 20, and the tie breaks to the
    # earlier, so the winner is the one tagged 'a'.
    assert len(sweep_steps.calls) == 4
    assert final.metrics["score"] == 20
    assert final.metrics["tag"] == "a"
    for k in (1, 2, 3, 4):
        assert (flow.run_dir / "1-sweep" / str(k) / "1-test-sweepscore").is_dir()


@pytest.mark.usefixtures("three_workers")
@mock_variables([flow_module, step_module])
def test_sweep_runs_every_pass_concurrently(minimal_design, mock_pdk):
    import threading

    from librelane.config import variable
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec
    from librelane.steps import Step

    # A barrier sized to the sweep's point count, not a sleep: every pass
    # blocks until all three have arrived, so the run completes if and only
    # if the three really did run at once. A sweep fanned out sequentially
    # would have the first pass wait alone until the barrier's timeout broke
    # it and the run raised.
    barrier = threading.Barrier(3, timeout=30)

    @Step.factory.register()
    class Meet(Step):
        id = "Test.SweepMeet"
        inputs = []
        outputs = []

        class Config(Step.Config):
            SWEEP_MEET_POINT: int = variable(description="point", default=0)

        def run(self, state_in, **kwargs):
            barrier.wait()
            return {}, {"score": 1}

    spec = FlowSpec.model_validate(
        _sweep_spec(
            {"SWEEP_MEET_POINT": [1, 2, 3]},
            select="score min",
            steps=["Test.SweepMeet"],
        )
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert not barrier.broken


@mock_variables([flow_module, step_module])
def test_skip_on_a_sweep_job_is_a_whole_job_pass_through(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [1, 2]}, select="score min")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t", skip=["sweep"])

    # No pass of the sweep ran a single step.
    assert sweep_steps.calls == []


@mock_variables([flow_module, step_module])
def test_reproducible_naming_a_sweep_job_s_step_is_refused(
    sweep_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowException
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [1, 2]}, select="score min")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", reproducible="Test.SweepScore")

    message = str(exc_info.value)
    assert "sweep" in message
    assert "v1" in message


@mock_variables([flow_module, step_module])
def test_explain_reports_a_sweep_row(sweep_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _sweep_spec({"SWEEP_SCORE": [1, 2, 3]}, select="score min")
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    explanation = flow.explain()

    row = next(d for d in explanation.jobs if d.job_id == "sweep")
    assert row.will_run
    assert row.mechanism is None
    assert row.reason == "sweep of 3 points, keeps score min"
