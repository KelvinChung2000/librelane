# Copyright 2023 Efabless Corporation
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
import os
import pathlib
from collections.abc import Callable

import pytest

from librelane.flows import flow
from librelane.config import Variable, variable as config_variable
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def variable():
    return Variable("DUMMY_VARIABLE", type=str, description="x")


@pytest.fixture
def MockStepTuple(variable: Variable):
    from librelane.steps import Step
    from librelane.state import DesignFormat, State

    class StepA(Step):
        id = "Test.StepA"
        inputs = [DesignFormat.JSON_HEADER]
        outputs = [DesignFormat.JSON_HEADER]

        class Config(Step.Config):
            DUMMY_VARIABLE: str = config_variable(description="x")

        def run(self, state_in: State, **kwargs):
            import json

            out_file = os.path.join(self.step_dir, "whatever.json")
            json.dump(
                {
                    "not_really_a_valid_header": True,
                    "cfg_var_value": str(self.config["DUMMY_VARIABLE"]),
                },
                open(out_file, "w", encoding="utf8"),
            )

            return {
                DesignFormat.JSON_HEADER: pathlib.Path(out_file),
            }, {"step": state_in.metrics.get("step", -1) + 1}

    class StepB(Step):
        id = "Test.StepB"
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]

        def run(self, state_in: State, **kwargs):
            import json

            out_file = os.path.join(self.step_dir, "whatever.json")
            json.dump(
                {
                    "probably_a_valid_header": False,
                    "previous_invalid_header": str(
                        state_in.get(DesignFormat.JSON_HEADER)
                    ),
                },
                open(out_file, "w", encoding="utf8"),
            )
            return {
                DesignFormat.JSON_HEADER: pathlib.Path(out_file),
            }, {"step": state_in.metrics.get("step", -1) + 1}

    class StepC(Step):
        id = "Test.StepC"
        inputs = [DesignFormat.JSON_HEADER]
        outputs = [DesignFormat.JSON_HEADER]

        class Config(Step.Config):
            DUMMY_VARIABLE: int = config_variable(description="x")

        def run(self, state_in: State, **kwargs):
            import json

            out_file = os.path.join(self.step_dir, "whatever.json")
            json.dump(
                {
                    "not_really_a_valid_header": True,
                    "cfg_var_value": self.config["DUMMY_VARIABLE"],
                },
                open(out_file, "w", encoding="utf8"),
            )
            return {
                DesignFormat.JSON_HEADER: pathlib.Path(out_file),
            }, {"step": state_in.metrics.get("step", -1) + 1}

    return (StepA, StepB, StepC)


@pytest.fixture
def DummyFlow(MockStepTuple):
    from librelane.flows import Flow

    StepA, StepB, _ = MockStepTuple

    class Dummy(Flow):
        Steps = [
            StepA,
            StepB,
        ]

        def __init__(
            self,
            *args,
            run_override: Callable | None = None,
            **kwargs,
        ):
            self.run_override = run_override
            super().__init__(*args, **kwargs)

        def run(self, initial_state, **kwargs):
            if self.run_override is not None:
                return self.run_override(self, initial_state, **kwargs)
            return initial_state.copy(), []

    return Dummy


# ---


def test_flow_abc_init():
    """
    ``Flow`` stays abstract now that it is machinery rather than a declaration
    base, because :meth:`librelane.flows.Flow.start` -- which is ``@final`` --
    calls ``self.run``. Dropping ``ABC`` would make ``Flow()`` construct and
    ``Flow().start()`` raise ``AttributeError`` deep inside a run instead.
    """
    from librelane.flows import Flow

    with pytest.raises(TypeError, match="Can't instantiate abstract class") as e:
        Flow()

    assert e is not None, "Flow ABC instantiated successfully"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow])
def test_init_and_config_vars(DummyFlow: type[flow.Flow], variable: Variable):
    flow = DummyFlow(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "PINGAS",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    assert flow.get_all_config_variables() == pytest.COMMON_FLOW_VARS + [variable], (
        "flow config variables did not match"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow])
def test_clashing_variables(DummyFlow: type[flow.Flow], MockStepTuple):
    from librelane.flows import FlowException

    StepA, StepB, StepC = MockStepTuple

    class DummierFlow(DummyFlow):
        Steps = [StepA, StepB, StepC]

    with pytest.raises(
        FlowException,
        match=r"Unrelated variables in \w+ and \w+ share a name",
    ) as e:
        DummierFlow(
            {
                "DESIGN_NAME": "WHATEVER",
                "DUMMY_VARIABLE": "PINGAS",
                "VERILOG_FILES": ["/cwd/src/a.v"],
            },
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )

    assert e is not None, "clashing variables did not generate a FlowException"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow])
def test_progress_bar(DummyFlow: type[flow.Flow]):
    def run_override(self: DummyFlow, initial_state, **kwargs):
        assert self.progress_bar.started, (
            ".start() did not start the progress bar rendering"
        )

        assert self.progress_bar._FlowProgressBar__progress.start_called_count == 1, (
            "start called more than once"
        )

        self.progress_bar.set_max_stage_count(2)
        assert self.progress_bar._FlowProgressBar__progress.total == 2, (
            ".set_max_stage_count() failed to set progress bar total"
        )

        self.progress_bar.start_stage("literally whatever")

        self.progress_bar.end_stage()

        assert self.progress_bar._FlowProgressBar__progress.update_called_count == 3, (
            "unexpected progress bar update count"
        )

        assert self.progress_bar._FlowProgressBar__progress.completed == 1, (
            "task complete count out of sync"
        )

        self.progress_bar.get_ordinal_prefix() == "2-", "incorrect ordinal returned"

        return initial_state.copy(), []

    flow = DummyFlow(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "PINGAS",
            "VERILOG_FILES": ["/cwd/src/a.v"],
        },
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
        run_override=run_override,
    )

    flow.start()


@mock_variables([flow, step])
def test_run_tags(
    caplog: pytest.LogCaptureFixture,
    MockStepTuple,
    monkeypatch,
    mock_conf_dir,
):
    import importlib

    from librelane.flows import FlowException
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    StepA, StepB, _ = MockStepTuple
    Step.factory.register()(StepA)
    Step.factory.register()(StepB)

    runs_dir = pathlib.Path(mock_conf_dir.cwd) / "runs"

    subject = Workflow(
        FlowSpec.model_validate(
            {
                "name": "Tagged",
                "jobs": {
                    "b": {"steps": ["Test.StepB"]},
                    "a": {"needs": ["b"], "steps": ["Test.StepA"]},
                },
            }
        ),
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "PINGAS",
            "VERILOG_FILES": [os.path.join(mock_conf_dir.cwd, "src", "a.v")],
        },
        design_dir=mock_conf_dir.cwd,
        pdk="dummy",
        scl="dummy_scl",
        pdk_root=mock_conf_dir.pdk_root,
    )

    flow_module = importlib.import_module("librelane.flows.flow")
    with monkeypatch.context() as patch:
        patch.setattr(
            flow_module,
            "additional_sink",
            lambda *args, **kwargs: pytest.fail(
                "sink registered before flow arguments were validated"
            ),
        )
        with pytest.raises(
            FlowException, match="tag and last_run cannot be used simultaneously"
        ):
            subject.start(tag="NotNone", last_run=True)

        with pytest.raises(
            FlowException, match="last_run used without any existing runs"
        ):
            subject.start(last_run=True)

    (runs_dir / "MY_TAG").mkdir(parents=True)
    subject.start(tag="MY_TAG")
    assert "Starting a new run of the" in caplog.text, (
        ".start() with an empty folder did not print a message about a new run"
    )
    caplog.clear()

    subject.start(tag="MY_TAG2")
    caplog.clear()

    state = subject.start(tag="MY_TAG2")
    assert "Using existing run at" in caplog.text, (
        ".start() with a non-empty folder did not print a message about an existing run"
    )
    assert state.metrics["step"] == 1, (
        ".start() using an existing run re-executed instead of reusing"
    )
    caplog.clear()

    subject.start(last_run=True)
    assert subject.run_dir is not None
    assert subject.run_dir.name == "MY_TAG2", (
        ".start() with last_run failed to return latest run"
    )

    (runs_dir / "MY_TAG3").write_text("")
    with pytest.raises(
        FlowException, match="already exists as a file and not a directory"
    ):
        subject.start(tag="MY_TAG3")


@mock_variables([flow, step])
def test_flow_log_artifacts(mock_conf_dir):
    from loguru import logger

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    @Step.factory.register()
    class LoggingStep(Step):
        id = "Test.LoggingStep"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            step_logger = logger.bind(step=self.id)
            step_logger.info("info artifact marker")
            step_logger.warning("warning artifact marker")
            step_logger.error("error artifact marker")
            return {}, {}

    logging_flow = Workflow(
        FlowSpec.model_validate(
            {"name": "Logging", "jobs": {"logging": {"steps": ["Test.LoggingStep"]}}}
        ),
        {
            # Version 1 puts the loader in permissive mode, which downgrades
            # the unknown key below from an error to the warning this test
            # reads out of the logs.
            "meta": {"version": 1},
            "DESIGN_NAME": "WHATEVER",
            "VERILOG_FILES": [os.path.join(mock_conf_dir.cwd, "src", "a.v")],
            "UNKNOWN_DIAGNOSTIC_KEY": "marker",
        },
        design_dir=mock_conf_dir.cwd,
        pdk="dummy",
        scl="dummy_scl",
        pdk_root=mock_conf_dir.pdk_root,
    )
    logging_flow.start(tag="LOGGING")

    run_dir = pathlib.Path(logging_flow.run_dir)
    flow_log = (run_dir / "flow.log").read_text()
    warning_log = (run_dir / "warning.log").read_text()
    error_log = (run_dir / "error.log").read_text()

    assert "info artifact marker" in flow_log
    assert "warning artifact marker" in flow_log
    assert "error artifact marker" in flow_log
    assert "warning artifact marker" in warning_log
    assert "info artifact marker" not in warning_log
    assert "error artifact marker" in error_log
    assert "warning artifact marker" not in error_log
    assert "unknown key 'UNKNOWN_DIAGNOSTIC_KEY'" in flow_log
    assert "unknown key 'UNKNOWN_DIAGNOSTIC_KEY'" in warning_log
