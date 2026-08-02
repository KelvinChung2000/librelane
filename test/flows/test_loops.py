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
The loop driver: a ring runs as sequential passes with an ``until`` gate.

Fake steps throughout, no real tools -- the same style ``test_engine.py``
uses, extended with a metric-counting member/gate pair that lets a ring's
convergence be observed without a real STA run.
"""

import pytest

from librelane.flows import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _bool_var(name: str, default: bool) -> dict:
    return {
        "name": name,
        "type": "bool",
        "description": "x",
        "default": default,
    }


@pytest.fixture
def loop_steps():
    """
    The step vocabulary every test below composes a ring's document out of.

    Returns
    -------
    A namespace object exposing:

    - ``calls``: every step instance's own ``id`` (not the class id), in the
      order it ran, so a test can assert a step ran a given number of times
      and that its id carried the pass it ran on.
    - ``Increment``: reads metric ``x`` (default 0) and writes ``x + 1``, or,
      if the step's configuration sets ``TEST_LOOP_KNOB``, writes that value
      instead -- the iteration-schedule case, where the schedule and not the
      step decides the metric.
    - ``Measure``: a no-op that passes its input through unchanged, standing
      in for a gate whose own steps just observe what the ring produced.
    - ``NeverConverges``: like ``Measure``, but a document pairs it with an
      ``until`` no configuration of ``Increment``'s bound could ever satisfy,
      to exercise exhaustion.
    - ``Produce``: writes a fixed view (``json_h``) and nothing else, an
      external producer for a ring's non-gate member.
    - ``Require``: requires that view, writes nothing new; records having
      received it into ``calls`` under its own id, so a later pass's absence
      or presence is checkable.
    - ``Downstream``: a plain step for a job outside the ring, so exhaustion
      and pass-through tests have something to prove still ran.
    - ``GateIfSeed``/``GateIfBody``/``GateIfGate``: the gate-own-``if``
      regression fixture. ``GateIfSeed`` seeds ``gate_ok: 1`` from outside
      the ring; ``GateIfBody`` flips it to ``0`` starting its second
      invocation; ``GateIfGate`` increments ``y`` and touches nothing else,
      so whether ``y`` reaches ``until``'s bound is a direct observation of
      whether the gate's own step ran on a given pass.
    """
    from librelane.config import variable
    from librelane.state import DesignFormat
    from librelane.steps import Step

    class _Namespace:
        pass

    ns = _Namespace()
    ns.calls = []

    @Step.factory.register()
    class Increment(Step):
        id = "Test.LoopIncrement"
        inputs = []
        outputs = []

        class Config(Step.Config):
            TEST_LOOP_KNOB: int = variable(description="x", default=-1)

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            knob = self.config["TEST_LOOP_KNOB"]
            if knob != -1:
                return {}, {"x": knob}
            return {}, {"x": state_in.metrics.get("x", 0) + 1}

    @Step.factory.register()
    class Measure(Step):
        id = "Test.LoopMeasure"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {}

    @Step.factory.register()
    class NeverConverges(Step):
        id = "Test.LoopNeverConverges"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {}

    json_h = DesignFormat.factory.get("json_h")
    assert json_h is not None, "json_h is a shipped design format"

    @Step.factory.register()
    class Produce(Step):
        id = "Test.LoopProduce"
        inputs = []
        outputs = [json_h]

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            import pathlib

            out = pathlib.Path(self.step_dir) / "whatever.json"
            out.write_text("{}")
            return {json_h: out}, {}

    @Step.factory.register()
    class Require(Step):
        id = "Test.LoopRequire"
        inputs = [json_h]
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {}

    @Step.factory.register()
    class Downstream(Step):
        id = "Test.LoopDownstream"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {}

    @Step.factory.register()
    class SeedZero(Step):
        id = "Test.LoopSeedZero"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {"x": 0}

    @Step.factory.register()
    class GateIfSeed(Step):
        id = "Test.GateIfSeed"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {"gate_ok": 1}

    @Step.factory.register()
    class GateIfBody(Step):
        """
        Runs unconditionally every pass. True on its own first invocation
        (tracked via 'body_runs', not the pass index, so this step needs no
        knowledge of which pass it is on) and false on every one after,
        which is what flips the gate's own 'if' term underneath it.
        """

        id = "Test.GateIfBody"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            runs = state_in.metrics.get("body_runs", 0)
            gate_ok = 1 if runs == 0 else 0
            return {}, {"body_runs": runs + 1, "gate_ok": gate_ok}

    @Step.factory.register()
    class GateIfGate(Step):
        """
        The gate's own step: increments 'y'. Nothing else in the ring
        touches 'y', so whether 'y' reaches the 'until' bound is a direct
        observation of whether this step ran on a given pass.
        """

        id = "Test.GateIfGate"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ns.calls.append(self.id)
            return {}, {"y": state_in.metrics.get("y", 0) + 1}

    ns.Increment = Increment
    ns.Measure = Measure
    ns.NeverConverges = NeverConverges
    ns.Produce = Produce
    ns.Require = Require
    ns.SeedZero = SeedZero
    ns.Downstream = Downstream
    ns.GateIfSeed = GateIfSeed
    ns.GateIfBody = GateIfBody
    ns.GateIfGate = GateIfGate
    return ns


def _two_member_ring(*, bound_key: str = "max", bound=3, extra_jobs=None):
    """
    A 2-member ring: 'resize' increments metric 'x' each pass, 'sta' is the
    gate and just measures it. 'until' is ``metric::x >= 2``, so this
    converges on pass 2 under the default ``max: 3``.
    """
    jobs = {
        "resize": {"needs": ["sta"], "steps": ["Test.LoopIncrement"]},
        "sta": {
            "needs": ["resize"],
            "steps": ["Test.LoopMeasure"],
            "until": "metric::x >= 2",
            bound_key: bound,
        },
    }
    if extra_jobs:
        jobs.update(extra_jobs)
    return {"name": "Loop", "jobs": jobs}


@mock_variables([flow_module, step_module])
def test_a_ring_converges_on_pass_2_running_each_member_once_per_pass(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_member_ring())
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert loop_steps.calls.count("Test.LoopIncrement (resize/1)") == 1
    assert loop_steps.calls.count("Test.LoopIncrement (resize/2)") == 1
    assert loop_steps.calls.count("Test.LoopMeasure (sta/1)") == 1
    assert loop_steps.calls.count("Test.LoopMeasure (sta/2)") == 1
    # Never a third pass: 'until' held at the end of pass 2.
    assert "Test.LoopIncrement (resize/3)" not in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_a_ring_writes_its_pass_directories(loop_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_member_ring())
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # slugify("Test.LoopIncrement") is "test-loopincrement".
    assert (flow.run_dir / "resize" / "1" / "1-test-loopincrement").is_dir()
    assert (flow.run_dir / "resize" / "2" / "1-test-loopincrement").is_dir()
    assert (flow.run_dir / "sta" / "1" / "1-test-loopmeasure").is_dir()
    assert (flow.run_dir / "sta" / "2" / "1-test-loopmeasure").is_dir()


@mock_variables([flow_module, step_module])
def test_a_self_loop_ring_of_one_converges(loop_steps, minimal_design, mock_pdk):
    """
    A single job that needs itself, gated by its own 'until': a ring of one,
    where the gate's intra-ring successor is itself.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "SelfLoop",
            "jobs": {
                "resize": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopIncrement"],
                    "until": "metric::x >= 2",
                    "max": 3,
                }
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    assert loop_steps.calls.count("Test.LoopIncrement (resize/1)") == 1
    assert loop_steps.calls.count("Test.LoopIncrement (resize/2)") == 1
    assert final.metrics["x"] == 2


@mock_variables([flow_module, step_module])
def test_exhaustion_defers_downstream_still_runs_and_the_flow_fails_at_the_end(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Exhausts",
            "jobs": {
                "resize": {"needs": ["sta"], "steps": ["Test.LoopIncrement"]},
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopNeverConverges"],
                    # 'x' never reaches 1000 in 2 passes.
                    "until": "metric::x >= 1000",
                    "max": 2,
                },
                "downstream": {
                    "needs": ["sta"],
                    "steps": ["Test.LoopDownstream"],
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    message = str(exc_info.value)
    assert "Job 'sta'" in message
    assert "exhausted its 2 passes" in message
    assert "metric::x >= 1000" in message
    assert "last observed 2" in message
    # The downstream job ran with the loop's last-pass output, and only the
    # flow as a whole failed, at the end -- a deferred error, not a raise
    # from inside the loop.
    assert "Test.LoopDownstream (downstream)" in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_iteration_values_are_visible_in_each_pass_and_the_provenance_names_the_pass(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Scheduled",
            "jobs": {
                "resize": {"needs": ["sta"], "steps": ["Test.LoopIncrement"]},
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "iterations": [
                        {"TEST_LOOP_KNOB": 1},
                        {"TEST_LOOP_KNOB": 2},
                        {"TEST_LOOP_KNOB": 3},
                    ],
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    # Converges on pass 2, where the schedule sets TEST_LOOP_KNOB to 2.
    assert final.metrics["x"] == 2

    config_1 = flow.iteration_configs[("resize", 1)]
    config_2 = flow.iteration_configs[("resize", 2)]
    assert config_1["TEST_LOOP_KNOB"] == 1
    assert config_2["TEST_LOOP_KNOB"] == 2
    assert config_2.provenance["TEST_LOOP_KNOB"] == "<flow document: sta, iteration 2>"


@mock_variables([flow_module, step_module])
def test_an_external_token_is_joined_on_pass_1_and_carried_by_every_later_pass(
    loop_steps, minimal_design, mock_pdk
):
    """
    'produce' feeds 'resize', the ring's non-gate entry member. Its view
    reaches 'resize' once, on pass 1, and the circulating state carries it
    forward: 'require', a second ring member reading the same view, still
    sees it on pass 2 without 'produce' having run again.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "ExternalJoin",
            "jobs": {
                "produce": {"steps": ["Test.LoopProduce"]},
                "resize": {
                    "needs": ["produce", "sta"],
                    "steps": ["Test.LoopIncrement"],
                },
                "require": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopRequire"],
                },
                "sta": {
                    "needs": ["require"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "max": 3,
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    assert loop_steps.calls.count("Test.LoopProduce (produce)") == 1
    assert loop_steps.calls.count("Test.LoopRequire (require/1)") == 1
    assert loop_steps.calls.count("Test.LoopRequire (require/2)") == 1


@mock_variables([flow_module, step_module])
def test_a_member_s_config_term_if_passes_through_on_every_pass(
    loop_steps, minimal_design, mock_pdk
):
    """
    'resize' is gated off by a config term the document never sets true, so
    it is a pass-through on every pass and 'x' is never written -- 'until'
    then reads a missing metric, which is a runtime error, not a false term:
    proof the member was genuinely skipped throughout, not merely
    unproductive.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "MemberGated",
            "config": [_bool_var("RUN_RESIZE", False)],
            "jobs": {
                "resize": {
                    "needs": ["sta"],
                    "steps": ["Test.LoopIncrement"],
                    "if": "RUN_RESIZE",
                },
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "max": 2,
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    assert "'x'" in str(exc_info.value) or "x" in str(exc_info.value)
    assert "Test.LoopIncrement" not in "".join(loop_steps.calls)


@mock_variables([flow_module, step_module])
def test_a_member_s_runtime_term_if_flips_per_pass(
    loop_steps, minimal_design, mock_pdk
):
    """
    'seed' is an external (non-ring) producer setting 'x' to 0 before the
    ring starts. 'resize' runs only while 'metric::x < 1': true on pass 1
    (x=0, seeded), false from pass 2 on (x=1, resize's own pass-1 output) --
    the same term evaluated fresh each pass against that pass's own input,
    flipping as the circulating state changes under it. 'until' never holds
    (bound low enough that the schedule exhausts), which is fine: the point
    here is which passes ran 'resize', not whether the loop converges.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "RuntimeGatedMember",
            "jobs": {
                "seed": {"steps": ["Test.LoopSeedZero"]},
                "resize": {
                    "needs": ["seed", "sta"],
                    "steps": ["Test.LoopIncrement"],
                    "if": "metric::x < 1",
                },
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 100",
                    "max": 3,
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    with pytest.raises(FlowError) as exc_info:
        flow.start(tag="t")

    assert "exhausted its 3 passes" in str(exc_info.value)
    # Pass 1: x=0 (seeded) < 1 -- resize runs, x becomes 1.
    assert "Test.LoopIncrement (resize/1)" in loop_steps.calls
    # Pass 2 and 3: x=1, not < 1 -- resize passes through on both.
    assert "Test.LoopIncrement (resize/2)" not in loop_steps.calls
    assert "Test.LoopIncrement (resize/3)" not in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_target_on_a_ring_member_selects_the_whole_ring(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _two_member_ring(
            extra_jobs={
                "downstream": {"needs": ["sta"], "steps": ["Test.LoopDownstream"]}
            }
        )
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t", target=["resize"])

    # 'resize' names a non-gate member; the whole ring ran, 'downstream' did
    # not (it is not an ancestor of the named member).
    assert "Test.LoopIncrement (resize/1)" in loop_steps.calls
    assert "Test.LoopMeasure (sta/1)" in loop_steps.calls
    assert "Test.LoopDownstream (downstream)" not in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_skip_naming_a_ring_member_is_refused(loop_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_member_ring())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", skip=["resize"])

    message = str(exc_info.value)
    assert "resize" in message
    assert "sta" in message
    assert "if" in message


@mock_variables([flow_module, step_module])
def test_skip_naming_the_gate_is_also_refused(loop_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_member_ring())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", skip=["sta"])

    assert "sta" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_reproducible_naming_a_ring_member_s_step_is_refused(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_member_ring())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException) as exc_info:
        flow.start(tag="t", reproducible="Test.LoopIncrement")

    message = str(exc_info.value)
    assert "resize" in message
    assert "sta" in message
    assert "v1" in message


@mock_variables([flow_module, step_module])
def test_an_unchanged_rerun_reuses_every_pass(loop_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    def make():
        return Workflow(
            FlowSpec.model_validate(_two_member_ring()), minimal_design, **mock_pdk
        )

    make().start(tag="t")
    first_run_calls = list(loop_steps.calls)
    assert first_run_calls  # sanity: something ran the first time

    loop_steps.calls.clear()
    make().start(tag="t")

    # Every pass's resume key is unchanged (same config, same input state),
    # so the rerun reuses every one and runs nothing.
    assert loop_steps.calls == []


@mock_variables([flow_module, step_module])
def test_a_false_gate_config_term_fires_the_whole_ring_as_one_pass_through(
    loop_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "GateGated",
            "config": [_bool_var("RUN_LOOP", False)],
            "jobs": {
                "resize": {"needs": ["sta"], "steps": ["Test.LoopIncrement"]},
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "max": 2,
                    "if": "RUN_LOOP",
                },
                "downstream": {
                    "needs": ["sta"],
                    "steps": ["Test.LoopDownstream"],
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    flow.start(tag="t")

    # Neither member ran a single step -- the whole loop instance fired as
    # one pass-through -- and downstream still ran.
    assert "Test.LoopIncrement" not in "".join(loop_steps.calls)
    assert "Test.LoopMeasure" not in "".join(loop_steps.calls)
    assert "Test.LoopDownstream (downstream)" in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_the_gate_s_own_if_is_decided_once_at_entry_not_re_evaluated_per_pass(
    loop_steps, minimal_design, mock_pdk
):
    """
    Regression: the gate's own 'if' must be decided once, at entry, by
    run()'s pre-submission check (the join of every member's external
    tokens under the gate's own source) -- never re-asked inside
    _run_loop. 'body' flips 'gate_ok' false starting its second pass; 'y'
    is incremented only by the gate's own step, so if _run_loop wrongly
    re-checked the gate's 'if' every pass, 'y' would freeze at 1 once
    'gate_ok' went false and the loop would exhaust instead of converging.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "GateIf",
            "jobs": {
                "seed": {"steps": ["Test.GateIfSeed"]},
                "body": {
                    "needs": ["seed", "gate"],
                    "steps": ["Test.GateIfBody"],
                },
                "gate": {
                    "needs": ["body"],
                    "steps": ["Test.GateIfGate"],
                    "if": "metric::gate_ok == 1",
                    "until": "metric::y >= 2",
                    "max": 3,
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    final = flow.start(tag="t")

    # Converges on pass 2: the gate's own step ran on both passes, despite
    # 'gate_ok' going false between them.
    assert final.metrics["y"] == 2
    assert loop_steps.calls.count("Test.GateIfGate (gate/1)") == 1
    assert loop_steps.calls.count("Test.GateIfGate (gate/2)") == 1
    assert "Test.GateIfGate (gate/3)" not in loop_steps.calls


@mock_variables([flow_module, step_module])
def test_explain_variables_reports_each_pass_of_a_scheduled_variable(
    loop_steps, minimal_design, mock_pdk
):
    """
    The design spec promises that '--explain-variables' attributes a
    scheduled value to the pass that set it. A variable the schedule does
    not touch (here, the universal 'DESIGN_NAME') is unaffected: still one
    row, reach unchanged.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "ScheduledExplain",
            "jobs": {
                "resize": {"needs": ["sta"], "steps": ["Test.LoopIncrement"]},
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "iterations": [
                        {"TEST_LOOP_KNOB": 1},
                        {"TEST_LOOP_KNOB": 2},
                        {"TEST_LOOP_KNOB": 3},
                    ],
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    explanation = flow.explain(variables=True)

    knob_rows = {
        row.reach: (row.value, row.origin)
        for row in explanation.variables
        if row.name == "TEST_LOOP_KNOB"
    }
    assert knob_rows[("resize (pass 1)",)] == (
        1,
        "<flow document: sta, iteration 1>",
    )
    assert knob_rows[("resize (pass 2)",)] == (
        2,
        "<flow document: sta, iteration 2>",
    )
    assert knob_rows[("resize (pass 3)",)] == (
        3,
        "<flow document: sta, iteration 3>",
    )

    design_name_rows = [
        row for row in explanation.variables if row.name == "DESIGN_NAME"
    ]
    assert len(design_name_rows) == 1
    assert design_name_rows[0].reach == ("resize", "sta")
    assert design_name_rows[0].value == "WHATEVER"


@mock_variables([flow_module, step_module])
def test_a_ring_member_acquires_and_releases_its_pool_per_pass(
    loop_steps, minimal_design, mock_pdk, mocker
):
    """
    A ring runs as one worker submission (:meth:`Workflow._run_loop`), so its
    pool use cannot go through the scheduling thread's try-and-park
    admission the way an ordinary job's or a sweep pass's does; it blocks on
    :meth:`ResourcePools.acquire` instead, once per member per pass. Spying
    on the flow's own ``pools`` object counts exactly that, without needing
    a second contender to prove serialization against.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "LoopPool",
            "resources": {"seat": 1},
            "jobs": {
                "resize": {
                    "needs": ["sta"],
                    "steps": ["Test.LoopIncrement"],
                    "resources": ["seat"],
                },
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.LoopMeasure"],
                    "until": "metric::x >= 2",
                    "max": 3,
                    "resources": ["seat"],
                },
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)
    acquire_spy = mocker.spy(flow.pools, "acquire")
    release_spy = mocker.spy(flow.pools, "release")
    flow.start(tag="t")

    # _two_member_ring's own docstring: 'until' is 'metric::x >= 2', which
    # this ring (the same two jobs, same steps) converges on at pass 2, so
    # each of the two members ran exactly twice -- one acquire and one
    # release per member per pass, four of each, every one for the ring's
    # one declared pool. 'release' is also called once more, with (),  when
    # the ring's own future settles on Workflow.run's scheduling thread --
    # its pool use is internal to _run_loop, so that call is the documented
    # empty-names no-op and is filtered out here rather than asserted away.
    assert acquire_spy.call_count == 4
    for call in acquire_spy.call_args_list:
        assert call.args[0] == ("seat",)
    seat_releases = [call for call in release_spy.call_args_list if call.args[0]]
    assert len(seat_releases) == 4
    for call in seat_releases:
        assert call.args[0] == ("seat",)
