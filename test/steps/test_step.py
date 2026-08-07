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
import json
import sys
import textwrap
import pathlib

import pytest

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def test_create_reproducible_uses_portable_paths(tmp_path, monkeypatch):
    from concurrent.futures import Future

    from librelane.config import BaseConfigModel
    from librelane.state import State
    from librelane.steps.step.reporting import ReportingMixin

    monkeypatch.chdir(tmp_path)

    design_file = tmp_path / "design.v"
    design_file.write_text("module design; endmodule\n")
    relative_file = tmp_path / "relative.v"
    relative_file.write_text("module relative; endmodule\n")
    pdk_root = tmp_path / "pdks"
    pdk_file = pdk_root / "dummy" / "tech.lef"
    pdk_file.parent.mkdir(parents=True)
    pdk_file.write_text("VERSION 5.8 ;\n")

    from librelane.state import DesignFormat

    pdk_view = pdk_root / "dummy" / "cells.gds"
    pdk_view.write_text("gds\n")

    class ReproducibleStep(ReportingMixin):
        inputs = [DesignFormat.GDS]

        @classmethod
        def get_implementation_id(cls):
            return "Test.Reproducible"

    state_in: Future[State] = Future()
    state_in.set_result(State({DesignFormat.GDS: pathlib.Path(pdk_view)}))
    target = ReproducibleStep()
    target.state_in = state_in
    target.config = BaseConfigModel.model_validate(
        {
            "DESIGN_DIR": pathlib.Path(tmp_path),
            "DESIGN_NAME": "design",
            "PDK": "dummy",
            "PDK_ROOT": pathlib.Path(pdk_root),
            "DESIGN_FILE": pathlib.Path(design_file),
            "RELATIVE_FILE": pathlib.Path("relative.v"),
            "TECH_FILE": pathlib.Path(pdk_file),
        }
    )

    output = tmp_path / "reproducible"
    target.create_reproducible(output)

    config = json.loads((output / "config.json").read_text())
    assert config["DESIGN_FILE"].startswith("./files/")
    assert config["RELATIVE_FILE"] == "./files/relative.v"
    assert config["TECH_FILE"].startswith("./files/")
    assert (output / config["DESIGN_FILE"]).read_text() == design_file.read_text()
    assert (output / config["RELATIVE_FILE"]).read_text() == relative_file.read_text()
    assert (output / config["TECH_FILE"]).read_text() == pdk_file.read_text()
    assert (output / "run_ol.sh").stat().st_mode & 0o111

    flat_output = tmp_path / "flat-reproducible"
    target.create_reproducible(flat_output, include_pdk=False, flatten=True)

    flat_config = json.loads((flat_output / "config.json").read_text())
    assert flat_config["DESIGN_FILE"] == "./design.v"
    assert flat_config["TECH_FILE"] == "pdk_dir::tech.lef"
    assert (flat_output / "design.v").read_text() == design_file.read_text()
    assert not (flat_output / "pdk").exists()

    # The same visitor writes the state, so a view inside the PDK is left
    # unresolved there too, and the reader has to be able to resolve it
    # (issue 600).
    flat_state = json.loads((flat_output / "state_in.json").read_text())
    assert flat_state["gds"] == "pdk_dir::cells.gds"
    assert State.loads(
        (flat_output / "state_in.json").read_text(),
        symbols={"PDKPATH": str(pdk_root / "dummy")},
    )["gds"] == pathlib.Path(pdk_view)


@pytest.fixture
def mock_run():
    def run(self, state_in, **kwargs):
        views_update = {}
        metrics = {}
        return views_update, metrics

    return run


# ---
def test_step_init_empty():
    from librelane.steps import Step

    with pytest.raises(TypeError, match="Can't instantiate abstract class Step"):
        Step()


def test_step_init_missing_id(mock_run):
    from librelane.steps import Step

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run

    with pytest.raises(
        NotImplementedError,
        match="does not implement the .id property and cannot be initialized",
    ):
        TestStep()


def test_step_inputs_not_implemented(mock_run):
    from librelane.steps import Step

    class TestStep(Step):
        id = "Dummy"
        outputs = []
        run = mock_run

    with pytest.raises(
        NotImplementedError,
        match="does not implement the .inputs property and cannot be initialized",
    ):
        TestStep.assert_concrete()


def test_step_outputs_not_implemented(mock_run):
    from librelane.steps import Step

    class TestStep(Step):
        id = "Dummy"
        inputs = []
        run = mock_run

    with pytest.raises(
        NotImplementedError,
        match="does not implement the .outputs property and cannot be initialized",
    ):
        TestStep.assert_concrete()


def test_step_missing_config(mock_run):
    from librelane.steps import Step

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    with pytest.raises(TypeError, match="Missing required argument 'config'"):
        TestStep()


def test_step_missing_state_in(mock_run):
    from librelane.steps import Step
    from librelane.config import Config

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    with pytest.raises(TypeError, match="Missing required argument 'state_in'"):
        TestStep(config=Config({"abc": "abc"}))


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_create(mock_run, mock_config):
    from librelane.steps import Step
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=State({DesignFormat.NETLIST: "abc"}),
    )
    assert step.id == "TestStep", "Wrong step id"
    assert step.long_name == "longname", "Wrong step longname"
    assert step.config == mock_config, "Wrong step config"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_typed_config_model(mock_run, mock_config):
    from librelane.config import variable
    from librelane.steps import Step
    from librelane.state import State

    class TypedStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "Test.TypedStep"

        class Config(Step.Config):
            RETRIES: int = variable(2, description="Retry count.")

    instance = TypedStep(
        config=mock_config,
        state_in=State(),
        RETRIES=4,
    )
    assert instance.config.RETRIES == 4
    assert TypedStep.config_vars[0].name == "RETRIES"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_optional_inputs(mock_run, mock_config):
    from librelane.steps import Step, StepException
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = [DesignFormat.NETLIST, DesignFormat.DEF.mkOptional()]
        outputs = []
        run = mock_run
        id = "TestStep"

    test_file = "test.nl.v"
    with open(test_file, "w") as f:
        f.write("\n")

    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=State({DesignFormat.NETLIST: pathlib.Path(test_file)}),
    )
    assert step.id == "TestStep", "Wrong step id"
    assert step.long_name == "longname", "Wrong step longname"
    assert step.config == mock_config, "Wrong step config"

    step.start(step_dir=".")

    with pytest.raises(StepException, match="missing required input"):
        TestStep(
            id="TestStep",
            long_name="longname",
            config=mock_config,
            state_in=State({DesignFormat.DEF: pathlib.Path(test_file)}),
        ).start(step_dir=".")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_mock_run(mock_run, mock_config):
    from librelane.steps import Step
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    state_in = State({DesignFormat.NETLIST: "abc"})
    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=state_in,
    )
    views_update, metrics_update = step.run(state_in)
    assert step.id == "TestStep", "Wrong step id"
    assert step.long_name == "longname", (
        "Wrong step long_name, declared via constructor"
    )
    assert step.config == mock_config, "Wrong step config"
    assert views_update == {}, "Wrong step run -- tainted views_update"
    assert metrics_update == {}, "Wrong step run -- tainted metrics_update"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_start_missing_step_dir(mock_run, mock_config):
    from librelane.steps import Step
    from librelane.common import Toolbox
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    state_in = State({DesignFormat.NETLIST: "abc"})
    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=state_in,
    )
    with pytest.raises(TypeError, match="Missing required argument 'step_dir'"):
        step.start(toolbox=Toolbox(tmp_dir="/cwd"))


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_start_invalid_state(mock_run, mock_config):
    from librelane.common import Toolbox
    from librelane.steps import Step, StepException
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"

    state_in = State({DesignFormat.NETLIST: "abc"})
    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=state_in,
    )
    with pytest.raises(StepException, match="generated invalid state"):
        step.start(toolbox=Toolbox(tmp_dir="/cwd"), step_dir="/cwd")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_start(mock_config):
    from librelane.common import Toolbox
    from librelane.state import DesignFormat, State
    from librelane.steps import Step, MetricsUpdate, ViewsUpdate

    test_file = "test.nl.v"
    with open(test_file, "w") as f:
        f.write("\n")

    test_file_out = "test2.nl.v"
    with open(test_file_out, "w") as f:
        f.write("\n")

    new_metric: MetricsUpdate = {"new_metric": "abc"}
    new_view: ViewsUpdate = {DesignFormat.NETLIST: pathlib.Path(test_file_out)}

    class TestStep(Step):
        inputs = []
        outputs = []
        id = "TestStep"

        def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
            return new_view, new_metric

    metrics_in = {"metric": "123"}
    state_in = State(
        {DesignFormat.NETLIST: pathlib.Path(test_file)}, metrics=metrics_in
    )
    step = TestStep(
        id="TestStep",
        long_name="longname",
        config=mock_config,
        state_in=state_in,
    )
    state_out = step.start(toolbox=Toolbox(tmp_dir="/cwd"), step_dir="/cwd")
    assert state_out[DesignFormat.NETLIST] == pathlib.Path(test_file_out), (
        "Wrong step state_out"
    )
    assert state_out.metrics == {
        **new_metric,
        **metrics_in,
    }, "Wrong step state_out metrics"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_longname(mock_run, mock_config):
    from librelane.steps import Step
    from librelane.state import DesignFormat, State

    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"
        long_name = "longname2"

    step = TestStep(
        id="TestStep",
        config=mock_config,
        state_in=State({DesignFormat.NETLIST: "abc"}),
    )
    assert step.long_name == "longname2", "Wrong long_name declared via class"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_step_factory(mock_run):
    from librelane.steps import Step

    @Step.factory.register()
    class TestStep(Step):
        inputs = []
        outputs = []
        run = mock_run
        id = "TestStep"
        long_name = "longname2"

    assert "TestStep" in Step.factory.list(), (
        "Step factory did not register step used for testing: TestStep"
    )
    assert Step.factory.get("TestStep") == TestStep, (
        "Wrong type registered by StepFactor"
    )


# Do NOT use the Fake FS for this test.
# The Configuration should NOT be re-validated.
@pytest.mark.usefixtures("_chdir_tmp")
@mock_variables([step])
def test_run_subprocess(mock_run, caplog, monkeypatch):
    import subprocess
    from librelane.config import Config
    from librelane.steps import Step, StepException
    from librelane.state import DesignFormat, State

    state_in = State({DesignFormat.NETLIST: "abc"})

    dir = os.getcwd()

    class StepTest(Step):
        inputs = [DesignFormat.NETLIST]
        outputs = [DesignFormat.NETLIST]
        id = "TclStepTest"
        step_dir = dir
        run = mock_run

    config_dict = {
        "DESIGN_NAME": "whatever",
        "DESIGN_DIR": dir,
        "EXAMPLE_PDK_VAR": "bla",
        "PDK_ROOT": "/pdk",
        "PDK": "dummy",
        "STD_CELL_LIBRARY": "dummy_scl",
        "VERILOG_FILES": ["/cwd/src/a.v", "/cwd/src/b.v"],
        "GRT_REPAIR_ANTENNAS": True,
        "RUN_HEURISTIC_DIODE_INSERTION": False,
        "MACROS": None,
        "DIODE_ON_PORTS": None,
        "TECH_LEFS": {
            "nom_*": "/pdk/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef"
        },
        "DEFAULT_CORNER": "nom_tt_025C_1v80",
        "RANDOM_ARRAY": None,
    }
    step = StepTest(
        config=Config(config_dict),
        state_in=state_in,
        _no_revalidate_conf=True,
    )
    out_file = "out.txt"
    first_line = "Hello World"
    second_line = "Bye World"
    subprocess_log_file = "test.log"
    # Nothing travels over stdout anymore: metrics arrive via the JSONL
    # sidecar (tested on its own) and reports are written by the subprocess
    # itself. Output is simply logged.
    subprocess_result = {
        "returncode": 0,
        "generated_metrics": {},
        "log_path": subprocess_log_file,
    }
    out_data = textwrap.dedent(
        f"""
        {first_line}
        {second_line}
        """
    ).strip()

    with open(out_file, "w") as f:
        f.write(out_data)

    actual_result = step.run_subprocess(
        ["cat", out_file], silent=True, log_to=subprocess_log_file
    )
    actual_out_data = ""
    with open(subprocess_log_file) as f:
        actual_out_data = f.read()
    assert actual_result == subprocess_result, (
        ".run_subprocess() generated invalid metrics"
    )

    monkeypatch.setenv("LIBRELANE_EMPTY_ENV_TEST", "parent value")
    empty_env_log = "empty-env.log"
    step.run_subprocess(
        [
            sys.executable,
            "-c",
            "import os; print(os.getenv('LIBRELANE_EMPTY_ENV_TEST', 'missing'))",
        ],
        env={},
        log_to=empty_env_log,
        silent=True,
    )
    with open(empty_env_log) as f:
        assert f.read() == "missing\n"

    owned_files = {}
    original_path_open = pathlib.Path.open

    def track_log_file(path, *args, **kwargs):
        file = original_path_open(path, *args, **kwargs)
        if path.name == "failed-process.log":
            owned_files["log"] = file
        return file

    def fail_to_start(*args, **kwargs):
        owned_files["stdin"] = kwargs["stdin"]
        raise RuntimeError("failed to start")

    with monkeypatch.context() as patch:
        patch.setattr(pathlib.Path, "open", track_log_file)
        with pytest.raises(RuntimeError, match="failed to start"):
            step.run_subprocess(
                ["unused"],
                log_to="failed-process.log",
                _popen_callable=fail_to_start,
            )

    assert owned_files["log"].closed
    assert owned_files["stdin"].closed
    assert actual_out_data == out_data, (
        ".run_subprocess() generated mis-matched log file"
    )

    with pytest.raises(subprocess.CalledProcessError):
        step.run_subprocess(["false"])

    with pytest.raises(subprocess.CalledProcessError):
        step.run_subprocess(
            [
                "python3",
                "-c",
                "import sys; print('\\n'.join(f'tail-{i}' for i in range(15))); sys.exit(1)",
            ],
            silent=True,
        )
    assert "tail-5" in caplog.text
    assert "tail-14" in caplog.text
    assert "tail-4\n" not in caplog.text

    class BadStep(Step):
        id = "Test.BadStep"

        inputs = []
        outputs = []

        def run(self, *args, **kwargs):
            self.run_subprocess(
                [
                    "python3",
                    "-c",
                    "import sys; stdout_b = sys.stdout.buffer; stdout_b.write(bytes([0xfa]))",
                ],
            )

    step = BadStep(
        config=Config(config_dict),
        state_in=State(),
        _no_revalidate_conf=True,
    )

    with pytest.raises(StepException, match="non-UTF-8"):
        step.start(step_dir=".")

    # Issue 924: a subprocess writes to a pipe, so Rich inside it sees no
    # terminal, falls back to 80 columns and clamps the tables the odbpy
    # scripts print. Only the parent knows the real width.
    from librelane.logging import console

    columns_log = "columns.log"
    step = StepTest(
        config=Config(config_dict),
        state_in=state_in,
        _no_revalidate_conf=True,
    )
    step.run_subprocess(
        [sys.executable, "-c", "import os; print(os.environ['COLUMNS'])"],
        log_to=columns_log,
        silent=True,
    )
    with open(columns_log) as f:
        assert f.read().strip() == str(console.width)

    # A caller that set one explicitly keeps it.
    step.run_subprocess(
        [sys.executable, "-c", "import os; print(os.environ['COLUMNS'])"],
        env={"COLUMNS": "42"},
        log_to=columns_log,
        silent=True,
    )
    with open(columns_log) as f:
        assert f.read().strip() == "42"


@pytest.mark.usefixtures("_chdir_tmp")
@mock_variables([step])
def test_a_failed_subprocess_leaves_no_monitor_thread_running():
    """
    The resource monitor polls the child through psutil on a timer, so one left
    running keeps touching the filesystem long after its step is over -- which
    corrupts the view of any later test that fakes the filesystem.
    """
    import threading

    from librelane.config import Config
    from librelane.state import State
    from librelane.steps import Step, StepException
    from librelane.steps.step.process_stats import ProcessStatsThread

    class StepTest(Step):
        inputs = []
        outputs = []
        id = "Test.MonitorLeak"
        step_dir = os.getcwd()

        def run(self, *args, **kwargs):
            return {}, {}

    step_object = StepTest(
        config=Config(
            {
                "DESIGN_NAME": "whatever",
                "DESIGN_DIR": os.getcwd(),
                "EXAMPLE_PDK_VAR": "bla",
                "PDK_ROOT": "/pdk",
                "PDK": "dummy",
                "STD_CELL_LIBRARY": "dummy_scl",
                "VERILOG_FILES": ["/cwd/src/a.v"],
                "GRT_REPAIR_ANTENNAS": True,
                "RUN_HEURISTIC_DIODE_INSERTION": False,
                "MACROS": None,
                "DIODE_ON_PORTS": None,
                "TECH_LEFS": {
                    "nom_*": "/pdk/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef"
                },
                "DEFAULT_CORNER": "nom_tt_025C_1v80",
                "RANDOM_ARRAY": None,
            }
        ),
        state_in=State(),
        _no_revalidate_conf=True,
    )

    before = {
        thread
        for thread in threading.enumerate()
        if isinstance(thread, ProcessStatsThread)
    }

    with pytest.raises(StepException, match="non-UTF-8"):
        step_object.run_subprocess(
            [
                "python3",
                "-c",
                "import sys; sys.stdout.buffer.write(bytes([0xfa]))",
            ],
            silent=True,
        )

    leaked = [
        thread
        for thread in threading.enumerate()
        if isinstance(thread, ProcessStatsThread) and thread not in before
    ]
    assert leaked == []


def test_steps_only_read_config_variables_they_declare():
    """A step whose Config omits the variable it reads raises KeyError at run time."""
    import librelane.steps  # noqa: F401
    from librelane.steps import Step

    undeclared = []
    for step_id in Step.factory.list():
        step = Step.factory.get(step_id)
        name = getattr(step, "obstruction_variable", None)
        if name is None:
            continue
        if name not in step._get_config_model().model_fields:
            undeclared.append(f"{step_id} reads '{name}'")
    assert undeclared == []


def test_flow_control_variable_raises():
    """
    Nothing has read this attribute since 2.0. A step defining it appeared to
    gate and did not, which is worse than a step that refuses to define.
    """
    from librelane.steps import Step

    with pytest.raises(TypeError, match="'if' on the job that runs it"):

        class Gating(Step):
            id = "Test.FlowControlVariable"
            inputs = []
            outputs = []
            flow_control_variable = "RUN_WHATEVER"

            def run(self, state_in, **kwargs):
                return {}, {}


def test_author_written_config_vars_raises():
    """
    'class Config' and 'config_vars' were two spellings of one thing, converted
    one into the other. Every shipped step uses Config and none uses
    config_vars.
    """
    from librelane.config import Variable
    from librelane.steps import Step

    with pytest.raises(TypeError, match="class Config"):

        class Author(Step):
            id = "Test.AuthorWrittenConfigVars"
            inputs = []
            outputs = []
            config_vars = [Variable("TEST_VAR", int, "desc", default=1)]

            def run(self, state_in, **kwargs):
                return {}, {}
