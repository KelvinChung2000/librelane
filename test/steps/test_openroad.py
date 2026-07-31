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


def test_pdn_cfg_can_come_from_the_pdk():
    """A PDK whose grid is better expressed as a script than as PDN_* variables
    needs to be able to supply the script itself."""
    from librelane.steps.openroad.floorplan import GeneratePDN

    extra = GeneratePDN.Config.model_fields["PDN_CFG"].json_schema_extra

    assert extra["pdk"] is True


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
