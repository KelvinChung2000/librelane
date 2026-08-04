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
``Step.gates``, which replaced the ``Checker.*`` step family.

This is the half of ``test_checker.py`` that survived the move: a limit
passes, a limit fails, and it fails deferred or immediately as declared. What
is new here is everything that follows from the limit living on the step that
measured the metric rather than on a step downstream of it -- which set of
metrics is read, and what is on disk by the time it raises.
"""

from decimal import Decimal

import pytest

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _potato_step(gates, **produced):
    """
    A step that produces ``produced`` and raises ``gates`` against it.

    Written as a factory rather than a fixture because almost every test here
    varies both, and a fixture parameterised on both is just this function with
    more ceremony.
    """
    from librelane.config import variable
    from librelane.steps.step import MetricsUpdate, Step, ViewsUpdate

    class PotatoesBurnt(Step):
        id = "Test.PotatoesBurnt"
        name = "Burnt Potato Count"
        inputs = []
        outputs = []

        class Config(Step.Config):
            ERROR_ON_BURNT_POTATOES: bool = variable(
                True,
                description="Whether burnt potatoes end the meal.",
            )
            BURNT_POTATO_THRESHOLD: Decimal | None = variable(
                None,
                description="How many burnt potatoes are tolerable.",
            )

        config: Config

        def run(self, state_in, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
            return {}, dict(produced)

    PotatoesBurnt.gates = gates
    return PotatoesBurnt


def _start(Step_, mock_config, state_in, overrides=None):
    from librelane.common import Toolbox

    config = mock_config
    if overrides is not None:
        config = mock_config.copy(**overrides)
    instance = Step_(config=config, state_in=state_in)
    instance.start(step_dir="/cwd/step", toolbox=Toolbox(tmp_dir="/cwd"))
    return instance


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_metric_within_the_limit_passes(
    mock_config, caplog: pytest.LogCaptureFixture
):
    from librelane.state import State
    from librelane.steps.step import MetricGate

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes"),),
        design__burnt_potato__count=0,
    )

    _start(Potatoes, mock_config, State())

    assert "Check for burnt potatoes clear" in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_metric_over_the_limit_raises_immediately_when_declared_so(mock_config):
    from librelane.state import State
    from librelane.steps.step import MetricGate
    from librelane.steps import DeferredStepError, StepError

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes", deferred=False),),
        design__burnt_potato__count=1,
    )

    with pytest.raises(StepError, match="1 burnt potatoes found") as raised:
        _start(Potatoes, mock_config, State())

    assert not isinstance(raised.value, DeferredStepError)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_metric_over_the_limit_defers_by_default(mock_config):
    from librelane.state import State
    from librelane.steps.step import MetricGate
    from librelane.steps import DeferredStepError

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes"),),
        design__burnt_potato__count=1,
    )

    with pytest.raises(DeferredStepError):
        _start(Potatoes, mock_config, State())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_remedy_is_appended_to_the_error(mock_config):
    from librelane.state import State
    from librelane.steps.step import MetricGate
    from librelane.steps import StepError

    Potatoes = _potato_step(
        (
            MetricGate(
                "design__burnt_potato__count",
                "burnt potatoes",
                deferred=False,
                remedy="Turn the oven down.",
            ),
        ),
        design__burnt_potato__count=1,
    )

    with pytest.raises(StepError, match="Turn the oven down."):
        _start(Potatoes, mock_config, State())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_false_error_on_var_downgrades_the_failure_to_a_warning(
    mock_config, caplog: pytest.LogCaptureFixture
):
    """
    The ``ERROR_ON_*`` variables, formerly ``QUIT_ON_*``. A user who has read
    the report and decided to proceed sets one to false, and the number is
    still reported.
    """
    from librelane.state import State
    from librelane.steps.step import MetricGate

    Potatoes = _potato_step(
        (
            MetricGate(
                "design__burnt_potato__count",
                "burnt potatoes",
                error_on_var="ERROR_ON_BURNT_POTATOES",
            ),
        ),
        design__burnt_potato__count=1,
    )

    _start(Potatoes, mock_config, State(), overrides={"ERROR_ON_BURNT_POTATOES": False})

    assert "1 burnt potatoes found" in caplog.text
    assert "ERROR_ON_BURNT_POTATOES" in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_configured_threshold_is_the_limit(mock_config):
    """
    ``Odb.ReportWireLength`` is the only gate shaped this way: the limit on a
    wire's length is the PDK's business, not a fixed zero.
    """
    from librelane.state import State
    from librelane.steps.step import MetricGate
    from librelane.steps import DeferredStepError

    gate = MetricGate(
        "design__burnt_potato__count",
        "burnt potatoes",
        threshold_var="BURNT_POTATO_THRESHOLD",
    )
    Potatoes = _potato_step((gate,), design__burnt_potato__count=5)

    _start(Potatoes, mock_config, State(), overrides={"BURNT_POTATO_THRESHOLD": 5})

    with pytest.raises(DeferredStepError):
        _start(Potatoes, mock_config, State(), overrides={"BURNT_POTATO_THRESHOLD": 4})


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_an_unset_threshold_limits_nothing_and_says_so(
    mock_config, caplog: pytest.LogCaptureFixture
):
    """
    A PDK that names no limit has not set one to zero: nothing is out of
    bounds, and the run says which variable would have to be set for anything
    to be.
    """
    from librelane.state import State
    from librelane.steps.step import MetricGate

    Potatoes = _potato_step(
        (
            MetricGate(
                "design__burnt_potato__count",
                "burnt potatoes",
                threshold_var="BURNT_POTATO_THRESHOLD",
            ),
        ),
        design__burnt_potato__count=99,
    )

    _start(Potatoes, mock_config, State())

    assert "BURNT_POTATO_THRESHOLD" in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_metric_the_step_did_not_measure_raises_nothing(
    mock_config, caplog: pytest.LogCaptureFixture
):
    """
    The whole point of moving the limit onto the measuring step. A checker
    whose metric was missing warned "are you sure the relevant step was run?"
    and passed, which is a check that silently stops checking. A gate has no
    such state to be in: if the step returned no number, the step is the one
    that already said why, and there is nothing here to compare.
    """
    from librelane.state import State
    from librelane.steps.step import MetricGate

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes"),),
        design__raw_potato__count=3,
    )

    _start(Potatoes, mock_config, State())

    assert "burnt potatoes" not in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_gate_reads_this_run_s_metrics_not_the_incoming_state_s(mock_config):
    """
    A gate speaks only for what its own step measured. An inherited number is
    some earlier step's measurement, and failing this step on it would put the
    error right back in the directory that has no evidence for it -- which is
    what the ``Checker.*`` steps did by construction.
    """
    from librelane.state import State
    from librelane.steps.step import MetricGate

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes"),),
    )

    _start(
        Potatoes,
        mock_config,
        State(metrics={"design__burnt_potato__count": 7}),
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_the_step_s_output_is_on_disk_before_a_gate_raises(mock_config):
    """
    The engine continues a deferring flow from ``step.state_out``, and a
    resumed run reads ``state_out.json``. A gate that raised before either
    existed would strand every later step on the views from before the step
    ran, so the ordering inside ``start()`` is load-bearing.
    """
    import os

    from librelane.state import State
    from librelane.steps.step import MetricGate
    from librelane.steps import DeferredStepError

    Potatoes = _potato_step(
        (MetricGate("design__burnt_potato__count", "burnt potatoes"),),
        design__burnt_potato__count=1,
    )
    instance = Potatoes(config=mock_config, state_in=State())

    from librelane.common import Toolbox

    with pytest.raises(DeferredStepError):
        instance.start(step_dir="/cwd/step", toolbox=Toolbox(tmp_dir="/cwd"))

    assert instance.state_out is not None
    assert instance.state_out.metrics["design__burnt_potato__count"] == 1
    assert os.path.exists("/cwd/step/state_out.json")


def _timing_step(gates, **produced):
    from librelane.config import variable
    from librelane.steps.step import MetricsUpdate, Step, ViewsUpdate

    class Timing(Step):
        id = "Test.TimingPotatoes"
        name = "Timing Potatoes"
        inputs = []
        outputs = []

        class Config(Step.Config):
            TIMING_VIOLATION_CORNERS: list[str] = variable(
                ["*"],
                description="Corners every violation type is checked at.",
            )
            BURN_VIOLATION_CORNERS: list[str] | None = variable(
                None,
                description="Corners burn violations are checked at.",
            )

        config: Config

        def run(self, state_in, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
            return {}, dict(produced)

    Timing.gates = gates
    return Timing


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_violation_at_a_matched_corner_fails_the_run(mock_config):
    from librelane.state import State
    from librelane.steps.step import CornerMetricGate
    from librelane.steps import DeferredStepError

    Timing = _timing_step(
        (CornerMetricGate("burn__vio__count", "burn", "BURN_VIOLATION_CORNERS"),),
        **{
            "burn__vio__count__corner:nom_tt_025C_1v80": 3,
            "burn__vio__count__corner:min_ff_n40C_1v95": 0,
        },
    )

    with pytest.raises(DeferredStepError, match="nom_tt_025C_1v80"):
        _start(
            Timing,
            mock_config,
            State(),
            overrides={"BURN_VIOLATION_CORNERS": ["nom_*"]},
        )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_violation_at_an_unmatched_corner_only_warns(
    mock_config, caplog: pytest.LogCaptureFixture
):
    """
    How a PDK says "measure this, report it, do not fail on it". The empty
    string matches no corner, which is the setting max cap and max slew ship
    with.
    """
    from librelane.state import State
    from librelane.steps.step import CornerMetricGate

    Timing = _timing_step(
        (CornerMetricGate("burn__vio__count", "burn", "BURN_VIOLATION_CORNERS"),),
        **{"burn__vio__count__corner:nom_tt_025C_1v80": 3},
    )

    _start(Timing, mock_config, State(), overrides={"BURN_VIOLATION_CORNERS": [""]})

    assert "nom_tt_025C_1v80" in caplog.text


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_an_unset_corner_variable_falls_through_to_the_shared_one(mock_config):
    """
    ``SETUP_VIOLATION_CORNERS`` is unset by default, and setup is then checked
    wherever ``TIMING_VIOLATION_CORNERS`` says the design is signed off.
    """
    from librelane.state import State
    from librelane.steps.step import CornerMetricGate
    from librelane.steps import DeferredStepError

    Timing = _timing_step(
        (CornerMetricGate("burn__vio__count", "burn", "BURN_VIOLATION_CORNERS"),),
        **{"burn__vio__count__corner:nom_tt_025C_1v80": 3},
    )

    with pytest.raises(DeferredStepError, match="nom_tt_025C_1v80"):
        _start(Timing, mock_config, State())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_a_wildcard_matching_no_corner_at_all_fails_the_run(mock_config):
    """
    A signoff corner named in the configuration that the STA run never
    produced. Silently checking nothing is the failure mode this catches.
    """
    from librelane.state import State
    from librelane.steps.step import CornerMetricGate
    from librelane.steps import DeferredStepError

    Timing = _timing_step(
        (CornerMetricGate("burn__vio__count", "burn", "BURN_VIOLATION_CORNERS"),),
        **{"burn__vio__count__corner:nom_tt_025C_1v80": 0},
    )

    with pytest.raises(DeferredStepError, match="did not match any corners"):
        _start(
            Timing,
            mock_config,
            State(),
            overrides={"BURN_VIOLATION_CORNERS": ["sky130_*"]},
        )


def test_every_gate_in_the_registry_names_a_real_metric_and_real_variables():
    """
    A gate that names a metric no step emits, or a variable no step declares,
    is a limit that never fires: the metric lookup misses and ``check``
    returns, and nothing anywhere says so. That is the one failure mode this
    mechanism can have, and a typo is all it takes, so the whole registry is
    swept rather than each gate spot-checked at its own step.
    """
    import librelane.steps  # noqa: F401  populates Step.factory
    import librelane.common.metrics.library  # noqa: F401  populates by_name

    from librelane.common.metrics.metric import Metric
    from librelane.steps import Step
    from librelane.steps.step import MetricGate

    known_metrics = set(Metric.by_name)
    gated = 0

    for step_id in Step.factory.list():
        Step_ = Step.factory.get(step_id)
        declared = {variable.name for variable in Step_.config_vars}
        for gate in Step_.gates:
            gated += 1
            assert gate.metric in known_metrics, f"{step_id}: {gate.metric}"
            if isinstance(gate, MetricGate):
                named = (gate.error_on_var, gate.threshold_var)
            else:
                named = (gate.corner_var, gate.fallback_corner_var)
            for variable_name in named:
                if variable_name is None:
                    continue
                assert variable_name in declared, f"{step_id}: {variable_name}"

    # The sweep is only worth anything if it swept something, and a refactor
    # that emptied every 'gates' tuple would otherwise pass it silently.
    assert gated >= 20
