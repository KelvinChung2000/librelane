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
    """RMP is experimental and rewrites the netlist every later step works on,
    so the Classic document has to ship it gated off. Read off the document
    since phase 5 deleted the ``Classic`` class it used to be read off."""
    from librelane.flows import Flow

    classic = Flow.factory.get("Classic")

    [run_rmp] = [entry for entry in classic.config if entry.name == "RUN_RMP"]
    assert run_rmp.default is False
    assert classic.jobs["rmp"].steps == ["OpenROAD.RMP"]
    assert classic.jobs["rmp"].condition == "RUN_RMP"


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


# Upstream PR 961: left to itself, OpenROAD picks any buffer it likes for port
# buffering, and on gf180mcu that is sometimes a delay buffer.


def test_port_buffering_names_the_pdk_buffer_cell():
    import re

    script = _script_text("OpenROAD.AddBuffer")

    # OpenROAD's -buffer_cell takes a lib cell name, and SYNTH_BUFFER_CELL is
    # '{cell}/{input_port}/{output_port}', so only the head is the cell.
    assert 'set buffer_cell [lindex [split $::env(SYNTH_BUFFER_CELL) "/"] 0]' in script

    invocations = re.findall(r"^\s*log_cmd buffer_ports .*$", script, re.MULTILINE)
    assert len(invocations) == 2

    for invocation in invocations:
        assert "-buffer_cell $buffer_cell" in invocation


# Upstream PR 925: pad rings on PDKs whose pad cells need rotating, and whose
# core ring must reach the pads on only some layers.


def _pad_cfg_text() -> str:
    from importlib.resources import files

    return (
        files("librelane")
        .joinpath("scripts", "openroad", "common", "pad_cfg.tcl")
        .read_text()
    )


def test_pad_rows_are_built_with_the_pdk_rotations():
    """A PDK whose pad cells are drawn for a different orientation gets a ring
    of pads facing the wrong way without these."""
    script = _pad_cfg_text()

    sites = script[script.index("make_io_sites") :].split("\n\n")[0]
    for axis in ("horizontal", "vertical", "corner"):
        assert f"-rotation_{axis} $::env(PAD_ROTATION_{axis.upper()})" in sites


def test_the_pad_rotations_default_to_no_rotation():
    """R0 is what OpenROAD's make_io_sites assumes when the flag is absent, so
    a PDK that says nothing keeps the ring it had."""
    from librelane.config.flow import PadConfig

    for axis in ("HORIZONTAL", "VERTICAL", "CORNER"):
        field = PadConfig.model_fields[f"PAD_ROTATION_{axis}"]
        assert field.default == "R0"
        assert field.json_schema_extra["pdk"] is True


def test_a_missing_pad_instance_is_reported_by_name():
    """The error path read a variable that was never set, so a padring naming
    an instance that does not exist died with a Tcl error about the error
    handler rather than about the instance."""
    script = _pad_cfg_text()

    assert "$instance_name" not in script
    assert script.count("No instance $inst_name found.") == 4


def test_the_core_ring_can_be_restricted_to_some_pad_layers():
    from importlib.resources import files

    from librelane.steps.openroad import GeneratePDN

    script = (
        files("librelane")
        .joinpath("scripts", "openroad", "common", "pdn_cfg.tcl")
        .read_text()
    )

    assert (
        "append_if_exists_argument arg_list PDN_CORE_RING_CONNECT_TO_PAD_LAYERS -connect_to_pad_layers"
        in script
    )
    assert "PDN_CORE_RING_CONNECT_TO_PAD_LAYERS" in GeneratePDN.Config.model_fields


# Upstream PR 965: configurable pad spacing, and pad rings with fewer than four
# populated sides.


def test_pad_spacing_defaults_to_the_pad_site_width():
    """That is the narrowest filler that can occupy the gap, and it is what the
    spacing was rounded to before the variable existed."""
    script = _pad_cfg_text()

    assert "set spacing_multiple $pad_site_width" in script
    assert (
        "set space_between_pads_multiple [round_um_nm [expr floor($space_between_pads / $spacing_multiple) * $spacing_multiple]]"
        in script
    )
    assert "$space_between_pads_multiple + $width" in script


def test_the_leftover_side_space_is_still_checked_against_the_site_width():
    """The gap between pads is the user's to choose, but what is left at the
    ends still has to be a whole number of filler cells."""
    script = _pad_cfg_text()

    assert (
        "if { $space_side != [round_um_nm [expr floor($space_side / $pad_site_width) * $pad_site_width]] } {"
        in script
    )


def test_trimming_rows_skips_the_fill_on_every_empty_side():
    script = _pad_cfg_text()

    for side in ("NORTH", "SOUTH", "WEST", "EAST"):
        assert (
            f'if {{!$::env(PAD_TRIM_ROWS) || ($::env(PAD_{side}) ne "")}} {{ place_io_fill -row IO_{side} {{*}}$::env(PAD_FILLERS) }}'
            in script
        )


def test_trimming_rows_deletes_only_the_corners_between_two_empty_sides():
    """A corner between one populated and one empty side still carries the ring
    signals around, so deleting it would break the abutment."""
    script = _pad_cfg_text()

    for vertical, horizontal in (
        ("NORTH", "WEST"),
        ("NORTH", "EAST"),
        ("SOUTH", "WEST"),
        ("SOUTH", "EAST"),
    ):
        # The instance name is OpenROAD's: the corner row names are
        # IO_CORNER_<V>_<H> and pad::place_corner suffixes them with _INST.
        assert (
            f'if {{$::env(PAD_TRIM_ROWS) && ($::env(PAD_{vertical}) eq "") '
            f'&& ($::env(PAD_{horizontal}) eq "")}} '
            f"{{ odb::dbInst_destroy "
            f"[$block findInst IO_CORNER_{vertical}_{horizontal}_INST] }}" in script
        )


def test_the_pad_spacing_variables_live_on_the_padring_step():
    from librelane.steps.openroad import PadRing

    for name in ("PAD_SPACING_MULTIPLE", "PAD_TRIM_ROWS"):
        assert name in PadRing.Config.model_fields


# Upstream PR 985: OpenROAD.GlobalPlacement can capture the placement's
# evolution as a gif, which OpenROAD only renders from its GUI.


def _gpl_argv(monkeypatch, tmp_path, generate_gif, openroad_gui="0"):
    from librelane.steps.openroad import GlobalPlacement

    monkeypatch.setenv("_OPENROAD_GUI", openroad_gui)

    instance = object.__new__(GlobalPlacement)
    instance.config = SimpleNamespace(
        OPENROAD_THREADS=1,
        PL_GENERATE_GIF=generate_gif,
    )
    instance.step_dir = str(tmp_path)

    return [str(arg) for arg in instance.get_command()]


def test_global_placement_does_not_open_a_gui_by_default(monkeypatch, tmp_path):
    argv = _gpl_argv(monkeypatch, tmp_path, generate_gif=False)

    assert "-gui" not in argv
    assert "-exit" in argv


def test_generating_a_gif_forces_the_gui_open(monkeypatch, tmp_path):
    """global_placement_debug renders through the GUI, so a headless -exit run
    would capture nothing."""
    argv = _gpl_argv(monkeypatch, tmp_path, generate_gif=True)

    assert argv[1] == "-gui"
    # -exit has to survive, or the run never ends on its own.
    assert "-exit" in argv


def test_generating_a_gif_under_an_interactive_run_adds_no_second_gui(
    monkeypatch, tmp_path
):
    """_OPENROAD_GUI=1 already puts -gui in the command."""
    argv = _gpl_argv(monkeypatch, tmp_path, generate_gif=True, openroad_gui="1")

    assert argv.count("-gui") == 1


def test_gpl_script_captures_renders_only_when_asked():
    script = _script_text("OpenROAD.GlobalPlacement")

    assert "if { $::env(PL_GENERATE_GIF) } {" in script
    debug = script[script.index("PL_GENERATE_GIF") :].split("\n}")[0]
    assert "global_placement_debug" in debug
    assert "-pause $::env(PL_GENERATE_GIF_PAUSE)" in debug
    assert "-generate_images" in debug
    assert "-images_path" in debug
    # The debug renderer has to be armed before the placement it observes.
    assert script.index("global_placement_debug") < script.index(
        "log_cmd global_placement {*}$arg_list"
    )


def test_the_gif_variables_live_on_the_global_placement_steps():
    from librelane.steps.openroad import GlobalPlacement, GlobalPlacementSkipIO

    for step_class in (GlobalPlacement, GlobalPlacementSkipIO):
        for name in ("PL_GENERATE_GIF", "PL_GENERATE_GIF_PAUSE"):
            assert name in step_class.Config.model_fields


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


# OpenROAD's ``check_antennas -verbose`` emits, per net/pin/layer, a
# calculated/required pair for each of PAR (Gate area), CAR (Cumulative area),
# PSR (Side area) and CSR (Cumulative side area). The ``(VIOLATED)`` marker sits
# on the ``Required ratio:`` line, and the calculated value is always the line
# immediately above it.
_CAR_VIOLATION_REPORT = """\
Net: net384
  Pin:   _22354_/A (sky130_fd_sc_hd__inv_2)
    Layer: met5
      Partial area ratio:   12.34
      Required ratio:  400.00 (Gate area)
      Cumulative area ratio: 7298.29
      Required ratio: 3091.96 (Cumulative area) (VIOLATED)
      Partial area ratio:    5.00
      Required ratio:  100.00 (Side area)
      Cumulative area ratio:   45.67
      Required ratio:  200.00 (Cumulative side area)

"""


def _parse(tmp_path, text):
    from librelane.steps.openroad.routing import parse_antenna_report

    report = tmp_path / "antenna.rpt"
    report.write_text(text, encoding="utf8")
    return parse_antenna_report(str(report))


def test_antenna_summary_reports_the_cumulative_ratio_that_violated(tmp_path):
    """Issue 797: with no regex for ``Cumulative area ratio:``, a CAR violation
    carried the partial ratio left over from the PAR check above it, so the
    reported ratio and its P/R column were both wrong."""
    violations = _parse(tmp_path, _CAR_VIOLATION_REPORT)

    assert len(violations) == 1
    violation = violations[0]
    assert violation.calculated_ratio == 7298.29
    assert violation.required_ratio == 3091.96
    assert violation.check == "Cumulative area"
    assert violation.net == "net384"
    assert violation.layer == "met5"


def test_antenna_summary_still_reports_partial_area_violations(tmp_path):
    report = _CAR_VIOLATION_REPORT.replace(
        "Required ratio:  400.00 (Gate area)",
        "Required ratio:  400.00 (Gate area) (VIOLATED)",
    ).replace(
        "Required ratio: 3091.96 (Cumulative area) (VIOLATED)",
        "Required ratio: 3091.96 (Cumulative area)",
    )

    violations = _parse(tmp_path, report)

    assert len(violations) == 1
    assert violations[0].calculated_ratio == 12.34
    assert violations[0].required_ratio == 400.00
    assert violations[0].check == "Gate area"


def test_antenna_summary_sorts_the_worst_violation_first(tmp_path):
    report = _CAR_VIOLATION_REPORT + _CAR_VIOLATION_REPORT.replace(
        "Cumulative area ratio: 7298.29", "Cumulative area ratio: 4000.00"
    ).replace("Net: net384", "Net: net999")

    violations = _parse(tmp_path, report)

    assert [v.net for v in violations] == ["net384", "net999"]
    assert violations[0].calculated_to_required > violations[1].calculated_to_required


def test_antenna_summary_rejects_a_report_it_cannot_attribute(tmp_path):
    """A VIOLATED marker with no calculated ratio above it means the report
    format changed; guessing a number would silently mislabel a violation."""
    import pytest

    with pytest.raises(ValueError, match="antenna report"):
        _parse(
            tmp_path,
            "Net: net384\n  Pin:   a/A (cell)\n    Layer: met5\n"
            "      Required ratio: 3091.96 (Cumulative area) (VIOLATED)\n",
        )


def _save_image_env(mocker, mock_config, **overrides):
    """Runs OpenROAD.SaveImage with the OpenROAD invocation stubbed, returns env."""
    from librelane.state import State
    from librelane.steps.openroad.base import OpenROADStep
    from librelane.steps.openroad.finishing import SaveImage

    instance = SaveImage(config=mock_config, state_in=State(), **overrides)
    instance.step_dir = "/cwd/step"

    parent = mocker.patch.object(OpenROADStep, "run", return_value=({}, {}))
    instance.run(State())

    return parent.call_args.kwargs["env"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_save_image_forces_the_offscreen_qt_platform(mocker, mock_config):
    """Issue 611: with no usable display, save_image does not raise a catchable
    Tcl error. It fails to load the "xcb" Qt platform plugin and aborts the
    whole OpenROAD process with SIGABRT, taking the step with it. Verified
    against OpenROAD dcf3613, which is built +GUI."""
    env = _save_image_env(mocker, mock_config)

    assert env["QT_QPA_PLATFORM"] == "offscreen"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_save_image_writes_a_png_into_its_own_step_dir(mocker, mock_config):
    """Several instances in one flow must not fight over one path."""
    env = _save_image_env(mocker, mock_config)

    assert env["_SAVE_IMAGE_OUTPUT"] == "/cwd/step/whatever.png"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_save_image_passes_display_options_as_tcl_pairs(mocker, mock_config):
    """save_image takes -display_option repeatedly, each a {control value}
    two-element list."""
    env = _save_image_env(
        mocker,
        mock_config,
        SAVE_IMAGE_DISPLAY_OPTIONS={"Nets/Power": False, "Nets/Ground": True},
    )

    assert env["_SAVE_IMAGE_DISPLAY_OPTIONS"] == "{Nets/Power false} {Nets/Ground true}"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_save_image_leaves_optional_knobs_empty_when_unset(mocker, mock_config):
    """The Tcl only appends -resolution and -area when non-empty, so an unset
    variable must not become the string "None"."""
    env = _save_image_env(mocker, mock_config)

    assert env["_SAVE_IMAGE_RESOLUTION"] == ""
    assert env["_SAVE_IMAGE_AREA"] == ""
    assert env["_SAVE_IMAGE_DISPLAY_OPTIONS"] == ""


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_save_image_rejects_an_area_that_is_not_four_numbers(mocker, mock_config):
    from librelane.steps.step import StepException

    with pytest.raises(StepException, match="four elements"):
        _save_image_env(mocker, mock_config, SAVE_IMAGE_AREA=[0, 0, 10])


def test_save_image_reads_the_odb_so_it_can_run_anywhere():
    """KLayout.Render needs a DEF or GDS and so only runs after stream-out.
    Reading the ODB is what lets this one sit mid-flow."""
    from librelane.state import DesignFormat
    from librelane.steps.openroad.finishing import SaveImage

    assert SaveImage.inputs == [DesignFormat.ODB]
    # It must not claim a view, or two instances would collide in the state.
    assert SaveImage.outputs == []


def test_rtl_macro_placer_is_resolvable_by_id():
    import librelane.steps  # noqa: F401
    from librelane.steps import Step

    resolved = Step.factory.get("OpenROAD.RTLMacroPlacer")

    assert resolved is not None
    assert resolved.id == "OpenROAD.RTLMacroPlacer"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_rtl_macro_placer_skips_unless_opted_in(mock_config):
    """RUN_RTLMP defaults to false: a design that placed all its macros
    manually must not have them second-guessed, so the step's default is a
    no-op that touches neither views nor metrics."""
    from librelane.state import State
    from librelane.steps.openroad.placement import RTLMacroPlacer

    instance = RTLMacroPlacer(config=mock_config, state_in=State())

    assert instance.config.RUN_RTLMP is False
    assert instance.run(State()) == ({}, {})


def test_psm_error_count_reads_the_inline_srcs_format():
    """PSM's 2026 report format writes 'srcs: net:VPWR' inline, which parses
    as a YAML string; counting len() of it counts characters, which inflated
    998 real violations into 69360 in a step-test reproducible."""
    import io

    from librelane.steps.openroad.floorplan import get_psm_error_count

    report = io.StringIO(
        "violation type: Unconnected shape\n"
        "\tsrcs: net:VPWR\n"
        "\tbbox = (5.7660, 48.8700) - (9.1790, 49.3500) on Layer met1\n"
        "violation type: Unconnected instance\n"
        "\tsrcs: inst:_476_\n"
        "\tbbox = (9.5040, 27.9050) - (9.5040, 27.9050) on Layer met1\n"
    )
    assert get_psm_error_count(report) == 2


def test_psm_error_count_still_reads_the_list_srcs_format():
    """The pre-2026 format lists one source per line, which parses as a YAML
    list; every listed source counts."""
    import io

    from librelane.steps.openroad.floorplan import get_psm_error_count

    report = io.StringIO(
        "violation type: Unconnected node\n"
        "\tsrcs:\n"
        "\t  - inst:_100_\n"
        "\t  - inst:_101_\n"
        "\tbbox = (1.0, 1.0) - (2.0, 2.0) on Layer met1\n"
    )
    assert get_psm_error_count(report) == 2


def test_psm_error_count_of_an_empty_report_is_zero():
    import io

    from librelane.steps.openroad.floorplan import get_psm_error_count

    assert get_psm_error_count(io.StringIO("\n")) == 0


def test_the_metric_locus_carries_string_values_with_spaces():
    """The odbpy scripts emit metrics over the %OL_METRIC stdout channel
    (OpenROAD's -metrics JSON is never written in -python mode), and
    design__die__bbox's value is four space-separated coordinates."""
    from types import SimpleNamespace

    from librelane.steps.step.output_processor import DefaultOutputProcessor

    processor = DefaultOutputProcessor(
        step=SimpleNamespace(step_dir=None), report_dir=".", silent=True
    )
    processor.process_line("%OL_METRIC design__die__bbox 0.0 0.0 101.205 111.925\n")
    processor.process_line("%OL_METRIC_I design__disconnected_pin__count 0\n")
    processor.process_line("%OL_METRIC_F route__wirelength__max 148.05\n")

    from decimal import Decimal

    assert processor.result() == {
        "design__die__bbox": "0.0 0.0 101.205 111.925",
        "design__disconnected_pin__count": 0,
        "route__wirelength__max": Decimal("148.05"),
    }
