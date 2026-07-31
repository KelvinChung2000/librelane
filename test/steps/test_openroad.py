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
from types import SimpleNamespace

import pytest

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _threaded_step_instance(mock_config, **overrides):
    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep

    class ThreadProbe(OpenROADStep):
        id = "Test.ThreadProbe"
        inputs = []
        outputs = []

        def get_script_path(self):
            return "/cwd/probe.tcl"

    instance = ThreadProbe(config=mock_config, state_in=State(), **overrides)
    instance.step_dir = "/cwd/step"
    return instance


def _threaded_step(mock_config, **overrides):
    instance = _threaded_step_instance(mock_config, **overrides)
    return [str(arg) for arg in instance.get_command()]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_openroad_uses_the_machine_thread_count_by_default(mock_config):
    from librelane.common import _get_process_limit

    argv = _threaded_step(mock_config)

    assert argv[argv.index("-threads") + 1] == str(_get_process_limit())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_openroad_thread_count_is_configurable(mock_config):
    argv = _threaded_step(mock_config, OPENROAD_THREADS=4)

    assert argv[argv.index("-threads") + 1] == "4"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_drt_threads_still_selects_the_thread_count(mock_config):
    """DRT_THREADS is deprecated in favour of the global variable."""
    argv = _threaded_step(mock_config, DRT_THREADS=6)

    assert argv[argv.index("-threads") + 1] == "6"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_threads_precede_the_script(mock_config):
    """-threads is an OpenROAD option, so it must come before the script path."""
    argv = _threaded_step(mock_config)

    assert argv.index("-threads") < argv.index("/cwd/probe.tcl")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize(
    ("code", "logged"),
    [
        # OpenROAD not implementing a LEF construct is not the design's problem.
        ("DRT-0349", False),
        ("ODB-0220", False),
        ("STA-1256", False),
        ("DRT-0004", True),
    ],
)
def test_suppressed_alerts_are_not_logged(mock_config, mocker, code, logged):
    from librelane.steps import OpenROADAlert

    instance = _threaded_step_instance(mock_config)
    warning = mocker.patch("librelane.steps.openroad.base.logger")

    instance.on_alert(OpenROADAlert(cls="warning", code=code, message="whatever"))

    assert warning.bind.called is logged


def _check_halos(**halos):
    """Exercise the real method with a minimal self.

    GeneratePDN cannot be instantiated against the mock PDK -- it requires the
    full PdnConfig set -- and the check reads nothing but these four values.
    """
    from decimal import Decimal
    from types import SimpleNamespace

    from librelane.steps.openroad.floorplan import GeneratePDN

    defaults = {
        "PDN_HORIZONTAL_HALO": 10,
        "PDN_VERTICAL_HALO": 10,
        "FP_MACRO_HORIZONTAL_HALO": 10,
        "FP_MACRO_VERTICAL_HALO": 10,
    }
    defaults.update(halos)
    config = SimpleNamespace(**{k: Decimal(v) for k, v in defaults.items()})
    GeneratePDN._GeneratePDN__check_halos(SimpleNamespace(config=config))


@pytest.mark.parametrize(
    ("halos", "expected"),
    [
        # The trap: rows are cut back less far than the grid is held off, so
        # cells land in a band the macro power grid avoids.
        (
            {"PDN_HORIZONTAL_HALO": 10, "FP_MACRO_HORIZONTAL_HALO": 2},
            ["PDN_HORIZONTAL_HALO"],
        ),
        (
            {"PDN_VERTICAL_HALO": 10, "FP_MACRO_VERTICAL_HALO": 2},
            ["PDN_VERTICAL_HALO"],
        ),
        # Both axes wrong is reported twice.
        (
            {
                "PDN_HORIZONTAL_HALO": 10,
                "FP_MACRO_HORIZONTAL_HALO": 2,
                "PDN_VERTICAL_HALO": 10,
                "FP_MACRO_VERTICAL_HALO": 2,
            },
            ["PDN_HORIZONTAL_HALO", "PDN_VERTICAL_HALO"],
        ),
        # Equal is fine, and so is a smaller PDN halo.
        ({"PDN_HORIZONTAL_HALO": 5, "FP_MACRO_HORIZONTAL_HALO": 5}, []),
        ({"PDN_HORIZONTAL_HALO": 2, "FP_MACRO_HORIZONTAL_HALO": 10}, []),
        # Defaults are equal on both axes.
        ({}, []),
    ],
)
def test_pdn_halo_trap_is_reported(mocker, halos, expected):
    warning = mocker.patch("librelane.steps.openroad.floorplan.logger").warning

    _check_halos(**halos)

    messages = [str(call.args[0]) for call in warning.call_args_list]
    assert len(messages) == len(expected)
    for message, fragment in zip(messages, expected):
        assert fragment in message


def test_diode_insertion_is_resolvable_by_id():
    """It writes its own config.json naming this ID, so a reproducible made
    from that directory has to be able to look it up."""
    import librelane.steps  # noqa: F401
    from librelane.steps import Step

    resolved = Step.factory.get("OpenROAD.DiodeInsertion")

    assert resolved is not None
    assert resolved.id == "OpenROAD.DiodeInsertion"


def test_repair_antennas_still_runs_diode_insertion():
    from librelane.steps.openroad.routing import RepairAntennas

    assert [child.id for child in RepairAntennas.Steps] == [
        "OpenROAD.DiodeInsertion",
        "OpenROAD.CheckAntennas",
    ]


def _rmp_instance(mock_config, mocker, trimmed_libs, **overrides):
    from librelane.state import State
    from librelane.steps.openroad.restructure import RMP

    instance = RMP(config=mock_config, state_in=State(), **overrides)

    raw = instance.config.to_raw_dict()
    raw.setdefault("LIB", {"*": ["/pdk/scl.lib"]})
    raw.setdefault("EXTRA_EXCLUDED_CELLS", None)
    # process_list_file opens these unconditionally, so they must be real.
    with open("/cwd/excluded.txt", "w") as f:
        f.write("")
    raw.setdefault("SYNTH_EXCLUDED_CELL_FILE", "/cwd/excluded.txt")
    raw.setdefault("PNR_EXCLUDED_CELL_FILE", "/cwd/excluded.txt")
    instance.config = type(instance.config).model_construct(**raw)

    instance.step_dir = "/cwd/rmp"

    mocker.patch.object(instance, "toolbox", mocker.MagicMock())
    instance.toolbox.filter_views.return_value = ["/pdk/scl.lib"]
    instance.toolbox.remove_cells_from_lib.return_value = trimmed_libs

    return instance


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_rmp_hands_abc_a_single_liberty_file(mock_config, mocker):
    """restructure passes -liberty_file straight to one ABC read_lib."""
    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep

    instance = _rmp_instance(mock_config, mocker, ["/tmp/trimmed-scl.lib"])
    captured: dict = {}
    mocker.patch.object(
        OpenROADStep,
        "run",
        lambda self, state_in, env, **kwargs: (captured.update(env), ({}, {}))[1],
    )

    instance.run(State())

    assert captured["_RMP_LIB"] == "/tmp/trimmed-scl.lib"
    assert captured["_RMP_ABC_LOG"] == "/cwd/rmp/abc.log"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize("trimmed_libs", [[], ["/tmp/a.lib", "/tmp/b.lib"]])
def test_rmp_refuses_a_corner_without_exactly_one_liberty_file(
    mock_config, mocker, trimmed_libs
):
    """A Tcl list would reach ABC as one filename, so it must not be built."""
    from librelane.state import State
    from librelane.steps.step import StepError

    instance = _rmp_instance(mock_config, mocker, trimmed_libs)

    with pytest.raises(StepError, match="exactly one liberty file"):
        instance.run(State())


def test_rmp_target_matches_what_openroad_accepts():
    """OpenROAD's Restructure::setMode compares against "timing" and "area";
    anything else only warns and silently restructures for area."""
    from librelane.steps.openroad.restructure import RMP

    annotation = RMP.Config.model_fields["RMP_TARGET"].annotation

    assert set(annotation.__args__) == {"timing", "area"}


def test_rmp_is_off_by_default_in_classic():
    from librelane.flows.classic import Classic

    assert Classic.Config.model_fields["RUN_RMP"].default is False
    assert Classic.gating_config_vars["OpenROAD.RMP"] == ["RUN_RMP"]


_CORNERS = ["nom_tt_025C_1v80", "min_ff_n40C_1v95", "max_ss_100C_1v60"]


def _corner_rc_env(mock_config, mocker, **overrides):
    """Drives OpenROADStep.run far enough to capture the per-corner RC env."""
    import os

    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep

    instance = _threaded_step_instance(mock_config)
    os.makedirs(instance.step_dir, exist_ok=True)

    raw = instance.config.to_raw_dict()
    raw["PNR_CORNERS"] = _CORNERS
    raw["LAYERS_RC"] = None
    raw["VIAS_R"] = None
    raw["DEDUPLICATE_CORNERS"] = False
    raw.update(overrides)
    instance.config = type(instance.config).model_construct(**raw)

    instance.toolbox = mocker.MagicMock()
    instance.toolbox.get_timing_files_categorized.return_value = ([], [], [], [])
    instance.toolbox.filter_views.return_value = []
    instance.toolbox.get_macro_views.return_value = []
    mocker.patch.object(OpenROADStep, "prepare_env", side_effect=lambda env, state: env)

    run_subprocess = mocker.patch.object(
        instance,
        "run_subprocess",
        return_value={"generated_metrics": {}, "returncode": 0},
    )

    instance.run(State())
    return run_subprocess.call_args.kwargs["env"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vias_r_wildcard_selects_only_matching_corners(mock_config, mocker):
    """`Filter(str)` iterates the string into one pattern per character, so the
    '*' in 'nom_*' became its own match-everything pattern."""
    env = _corner_rc_env(
        mock_config,
        mocker,
        VIAS_R={"nom_*": {"via1": {"res": 5}}},
    )

    emitted = [value for key, value in env.items() if key.startswith("_VIA_R_")]

    assert len(emitted) == 1
    assert "nom_tt_025C_1v80" in emitted[0]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vias_r_exact_corner_key_is_honoured(mock_config, mocker):
    """A key naming one corner exactly matched nothing at all before."""
    env = _corner_rc_env(
        mock_config,
        mocker,
        VIAS_R={"max_ss_100C_1v60": {"via1": {"res": 5}}},
    )

    emitted = [value for key, value in env.items() if key.startswith("_VIA_R_")]

    assert len(emitted) == 1
    assert "max_ss_100C_1v60" in emitted[0]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vias_r_and_layers_rc_agree_on_the_same_wildcard(mock_config, mocker):
    """The two are filtered by adjacent lines and must not disagree."""
    env = _corner_rc_env(
        mock_config,
        mocker,
        VIAS_R={"nom_*": {"via1": {"res": 5}}},
        LAYERS_RC={"nom_*": {"met1": {"res": 1, "cap": 2}}},
    )

    vias = [v for k, v in env.items() if k.startswith("_VIA_R_")]
    layers = [v for k, v in env.items() if k.startswith("_LAYER_RC_")]

    assert len(vias) == len(layers) == 1


def test_post_drt_antenna_repair_reads_the_drt_margin():
    """DetailedRouting.Config pulls in GrtConfig, so both margins are in the
    environment and reading the wrong one is silent."""
    from importlib.resources import files

    from librelane.steps.openroad.routing import DetailedRouting

    script = files("librelane").joinpath("scripts", "openroad", "drt.tcl").read_text()
    repair_block = script[script.index("post-DRT antenna repair") :]

    assert "$::env(DRT_ANTENNA_REPAIR_MARGIN)" in repair_block
    assert "$::env(GRT_ANTENNA_REPAIR_MARGIN)" not in repair_block
    assert "DRT_ANTENNA_REPAIR_MARGIN" in DetailedRouting.Config.model_fields


def test_pdn_cfg_can_come_from_the_pdk():
    """A PDK whose grid is better expressed as a script than as PDN_* variables
    needs to be able to supply the script itself."""
    from librelane.steps.openroad.floorplan import GeneratePDN

    extra = GeneratePDN.Config.model_fields["PDN_CFG"].json_schema_extra

    assert extra["pdk"] is True


# Issue 532: launching tools interactively.


def _console_instance(StepClass, mock_config):
    from librelane.state import State

    instance = StepClass(config=mock_config, state_in=State())
    instance.step_dir = "/cwd/step"
    return instance


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_openroad_console_keeps_the_interpreter_alive(mock_config):
    """-exit would run the script and quit, which is the opposite of a console."""
    from librelane.steps.openroad import OpenConsole

    argv = [
        str(arg) for arg in _console_instance(OpenConsole, mock_config).get_command()
    ]

    assert "-exit" not in argv
    assert "-gui" not in argv
    assert argv[-1].endswith("gui.tcl")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_opensta_console_keeps_the_interpreter_alive(mock_config):
    from librelane.steps.openroad import OpenSTAConsole

    argv = [
        str(arg) for arg in _console_instance(OpenSTAConsole, mock_config).get_command()
    ]

    assert argv[0] == "sta"
    assert "-exit" not in argv
    assert argv[-1].endswith("sta/console.tcl")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_consoles_hand_the_terminal_over(mock_config, mocker):
    """A console the output processors read from is not a console: the user
    needs the subprocess to inherit stdin, stdout and stderr."""
    from librelane.state import State
    from librelane.steps.openroad import OpenConsole, OpenSTAConsole

    for StepClass in (OpenConsole, OpenSTAConsole):
        instance = _console_instance(StepClass, mock_config)
        popen = mocker.patch("subprocess.Popen")
        popen.return_value.wait.return_value = 0
        mocker.patch.object(instance, "prepare_env", side_effect=lambda env, state: env)
        mocker.patch.object(
            instance,
            "_get_corner_files",
            return_value=(
                "nom_tt_025C_1v80",
                OpenSTAConsole.CornerFileList(libs=(), netlists=(), spefs=()),
            ),
        )
        run_subprocess = mocker.patch.object(instance, "run_subprocess")

        instance.run(State())

        assert popen.call_count == 1
        assert not run_subprocess.called
        for stream in ("stdin", "stdout", "stderr"):
            assert stream not in popen.call_args.kwargs


# Issue 917: port buffering moved ahead of global placement.


def _script_text(step_id: str) -> str:
    from pathlib import Path

    from librelane.steps import Step

    step_class = Step.factory.get(step_id)
    assert step_class is not None, f"{step_id} is not a registered step"
    return Path(str(object.__new__(step_class).get_script_path())).read_text()


def test_add_buffer_buffers_the_ports():
    script = _script_text("OpenROAD.AddBuffer")

    assert "buffer_ports -inputs" in script
    assert "buffer_ports -outputs" in script
    assert "DESIGN_REPAIR_BUFFER_INPUT_PORTS" in script
    assert "DESIGN_REPAIR_BUFFER_OUTPUT_PORTS" in script


def test_post_gpl_repair_no_longer_buffers_the_ports():
    """Otherwise every port would be buffered twice."""
    assert "buffer_ports" not in _script_text("OpenROAD.RepairDesignPostGPL")


def test_the_port_buffering_variables_live_on_the_step_that_uses_them():
    from librelane.steps.openroad import AddBuffer, RepairDesignPostGPL

    for name in (
        "DESIGN_REPAIR_BUFFER_INPUT_PORTS",
        "DESIGN_REPAIR_BUFFER_OUTPUT_PORTS",
    ):
        assert name in AddBuffer.Config.model_fields
        assert name not in RepairDesignPostGPL.Config.model_fields


# Issue 636: mid-PnR STA reported one corner while the resizer steps around it
# optimized against all of them.


def test_sta_midpnr_reports_every_sta_corner(mocker, tmp_path):
    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep
    from librelane.steps.openroad import STAMidPNR

    instance = object.__new__(STAMidPNR)
    instance.config = SimpleNamespace(
        STA_MIDPNR_CORNERS=None,
        STA_CORNERS=["nom_tt_025C_1v80", "nom_ss_100C_1v60"],
    )
    instance.step_dir = str(tmp_path)
    parent = mocker.patch.object(OpenROADStep, "run", return_value=({}, {}))

    instance.run(State())

    assert parent.call_args.kwargs["corners"] == [
        "nom_tt_025C_1v80",
        "nom_ss_100C_1v60",
    ]
    # The output processor opens the report files; it does not create the
    # directories the script names.
    for corner in instance.config.STA_CORNERS:
        assert (tmp_path / corner).is_dir()


def test_sta_midpnr_corners_are_overridable(mocker, tmp_path):
    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep
    from librelane.steps.openroad import STAMidPNR

    instance = object.__new__(STAMidPNR)
    instance.config = SimpleNamespace(
        STA_MIDPNR_CORNERS=["nom_tt_025C_1v80"],
        STA_CORNERS=["nom_tt_025C_1v80", "nom_ss_100C_1v60"],
    )
    instance.step_dir = str(tmp_path)
    parent = mocker.patch.object(OpenROADStep, "run", return_value=({}, {}))

    instance.run(State())

    assert parent.call_args.kwargs["corners"] == ["nom_tt_025C_1v80"]


def test_the_corner_script_reports_every_defined_corner():
    """It used to break out of the corner loop after the first iteration."""
    script = _script_text("OpenROAD.STAMidPNR")

    body = script.split("foreach {corner_name corner_object}")[1]
    assert "\n    break\n" not in body
    assert "%OL_CREATE_REPORT $corner_name/min.rpt" in body
    assert "%OL_CREATE_REPORT $corner_name/violator_list.rpt" in body


def test_multi_corner_sta_reports_land_where_they_always_have():
    """
    The script now names its reports '<corner>/<report>', so the per-corner
    step has to hand the output processor the step directory, not the corner
    directory, or the reports move a level deeper.
    """
    import inspect

    from librelane.steps.openroad import MultiCornerSTA

    source = inspect.getsource(MultiCornerSTA.run_corner)

    assert "report_dir=self.step_dir" in source
