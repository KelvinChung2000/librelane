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


def test_pdn_cfg_can_come_from_the_pdk():
    """A PDK whose grid is better expressed as a script than as PDN_* variables
    needs to be able to supply the script itself."""
    from librelane.steps.openroad.floorplan import GeneratePDN

    extra = GeneratePDN.Config.model_fields["PDN_CFG"].json_schema_extra

    assert extra["pdk"] is True
