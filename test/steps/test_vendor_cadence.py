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
Behavioral tests for the seven Cadence step scaffolds (librelane/steps/
genus.py, innovus.py, tempus.py, quantus.py, voltus.py, pegasus.py,
conformal.py).

These test behavior, not structure: that each scaffold fails loudly and
informatively rather than guessing, that every script path it names actually
resolves to a real file, and that each module's REGISTRATIONS list covers
exactly the jobs it is supposed to.
"""

import os

import pytest

from librelane.steps import step
from librelane.jobs import Job

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


PNR_JOB_IDS = [
    "floorplan",
    "macro_placement",
    "tapcell_insertion",
    "power_grid",
    "io_placement",
    "global_placement",
    "post_gpl_repair",
    "detailed_placement",
    "cts",
    "post_cts_opt",
    "global_routing",
    "post_grt_repair",
    "antenna_repair",
    "post_grt_opt",
    "detailed_routing",
    "post_route_opt",
    "fill_insertion",
]

INNOVUS_STEP_IDS = [
    "Innovus.Floorplan",
    "Innovus.MacroPlacement",
    "Innovus.TapEndcapInsertion",
    "Innovus.PowerGrid",
    "Innovus.IOPlacement",
    "Innovus.GlobalPlacement",
    "Innovus.PostGPLRepair",
    "Innovus.DetailedPlacement",
    "Innovus.CTS",
    "Innovus.PostCTSOpt",
    "Innovus.GlobalRouting",
    "Innovus.PostGRTRepair",
    "Innovus.AntennaRepair",
    "Innovus.PostGRTOpt",
    "Innovus.DetailedRouting",
    "Innovus.PostRouteOpt",
    "Innovus.FillInsertion",
]

ALL_STEP_IDS = (
    ["Genus.Synthesis"]
    + INNOVUS_STEP_IDS
    + ["Tempus.PrePNRSTA", "Tempus.SignoffSTA"]
    + ["Quantus.Extraction"]
    + ["Voltus.IRDrop"]
    + ["Pegasus.DRC", "Pegasus.LVS"]
    + ["Conformal.LEC"]
)


# ----------------------------------------------------------------------
# run() raises NotImplementedError, naming the step id and the script path,
# for one representative step per tool.
# ----------------------------------------------------------------------
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize(
    ("modpath", "clsname"),
    [
        ("librelane.steps.genus", "Synthesis"),
        ("librelane.steps.innovus", "Floorplan"),
        ("librelane.steps.tempus", "PrePNRSTA"),
        ("librelane.steps.quantus", "Extraction"),
        ("librelane.steps.voltus", "IRDrop"),
        ("librelane.steps.pegasus", "DRC"),
        ("librelane.steps.conformal", "LEC"),
    ],
)
def test_run_raises_not_implemented_naming_script(modpath, clsname, mock_config):  # noqa: F811
    import importlib

    from librelane.state import State

    step_class = getattr(importlib.import_module(modpath), clsname)
    step_obj = step_class(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert step_obj.id in message
    assert step_obj.get_script_path() in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_quantus_run_message_also_names_binary_as_unestablished(mock_config):  # noqa: F811
    from librelane.steps.quantus import Extraction
    from librelane.state import State

    step_obj = Extraction(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    assert "invocation binary" in str(exc_info.value)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_pegasus_run_message_also_names_binary_as_unestablished(mock_config):  # noqa: F811
    from librelane.steps.pegasus import DRC
    from librelane.state import State

    step_obj = DRC(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    assert "invocation binary" in str(exc_info.value)


# ----------------------------------------------------------------------
# get_command(): the confirmed invocation for the five tools that have one.
# ----------------------------------------------------------------------
def test_genus_get_command_uses_confirmed_invocation():
    from librelane.steps.genus import Synthesis

    step_obj = object.__new__(Synthesis)
    command = step_obj.get_command()

    assert command == ["genus", "-f", step_obj.get_script_path(), "-no_gui"]


def test_innovus_get_command_uses_confirmed_invocation():
    from librelane.steps.innovus import Floorplan

    step_obj = object.__new__(Floorplan)
    command = step_obj.get_command()

    assert command == [
        "innovus",
        "-nowin",
        "-common_ui",
        "-files",
        step_obj.get_script_path(),
    ]


def test_tempus_get_command_uses_confirmed_invocation():
    from librelane.steps.tempus import PrePNRSTA

    step_obj = object.__new__(PrePNRSTA)
    command = step_obj.get_command()

    assert command == [
        "tempus",
        "-no_gui",
        "-stylus",
        "-files",
        step_obj.get_script_path(),
    ]


def test_voltus_get_command_uses_confirmed_invocation():
    from librelane.steps.voltus import IRDrop

    step_obj = object.__new__(IRDrop)
    command = step_obj.get_command()

    assert command == [
        "voltus",
        "-no_gui",
        "-common_ui",
        "-init",
        step_obj.get_script_path(),
    ]


def test_conformal_get_command_uses_confirmed_invocation():
    from librelane.steps.conformal import LEC

    step_obj = object.__new__(LEC)
    command = step_obj.get_command()

    assert command == [
        "conformal_lec_bin",
        "-nogui",
        "-color",
        "-tclmode",
        "-dofile",
        step_obj.get_script_path(),
    ]


# ----------------------------------------------------------------------
# get_command(): raises for Quantus and Pegasus, naming what is unestablished.
# ----------------------------------------------------------------------
def test_quantus_get_command_raises_naming_unestablished_invocation():
    from librelane.steps.quantus import Extraction

    step_obj = object.__new__(Extraction)

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "Quantus" in message
    assert "unestablished" in message
    assert "PEX_TOOL1=quantus" in message


def test_pegasus_get_command_raises_naming_unestablished_invocation():
    from librelane.steps.pegasus import DRC

    step_obj = object.__new__(DRC)

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "Pegasus" in message
    assert "unestablished" in message
    assert "-lvs" in message


# ----------------------------------------------------------------------
# get_script_path(): resolves to a file that actually exists on disk.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("step_id", ALL_STEP_IDS)
def test_script_path_resolves_to_a_real_file(step_id):
    from librelane.steps import Step

    step_class = Step.factory.get(step_id)
    assert step_class is not None, f"{step_id} is not a registered step"

    step_obj = object.__new__(step_class)
    script_path = str(step_obj.get_script_path())

    assert os.path.isfile(script_path), f"{step_id}: {script_path} is not a file"


# ----------------------------------------------------------------------
# Every step id in these registrations is a real, registered Step.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("step_id", ALL_STEP_IDS)
def test_step_is_registered_in_step_factory(step_id):
    from librelane.steps import Step

    assert Step.factory.get(step_id) is not None, (
        f"{step_id} did not register in Step.factory"
    )


# ----------------------------------------------------------------------
# REGISTRATIONS covers exactly the job ids intended, and every job id
# named is a real, registered Job.
# ----------------------------------------------------------------------
def test_genus_registrations_cover_exactly_synthesis():
    from librelane.steps.genus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == ["synthesis"]
    for entry in REGISTRATIONS:
        assert entry["provider"] == "genus"
        assert entry["job"] in Job.factory.list()


def test_innovus_registrations_cover_exactly_the_seventeen_pnr_jobs():
    from librelane.steps.innovus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == sorted(PNR_JOB_IDS)
    for entry in REGISTRATIONS:
        assert entry["provider"] == "innovus"
        assert entry["job"] in Job.factory.list()


def test_tempus_registrations_cover_exactly_pre_and_signoff_sta():
    from librelane.steps.tempus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == sorted(["pre_pnr_sta", "signoff_sta"])
    for entry in REGISTRATIONS:
        assert entry["provider"] == "tempus"
        assert entry["job"] in Job.factory.list()


def test_quantus_registrations_cover_exactly_extraction():
    from librelane.steps.quantus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == ["extraction"]
    for entry in REGISTRATIONS:
        assert entry["provider"] == "quantus"
        assert entry["job"] in Job.factory.list()


def test_voltus_registrations_cover_exactly_ir_drop():
    from librelane.steps.voltus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == ["ir_drop"]
    for entry in REGISTRATIONS:
        assert entry["provider"] == "voltus"
        assert entry["job"] in Job.factory.list()


def test_pegasus_registrations_cover_exactly_drc_and_lvs():
    from librelane.steps.pegasus import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == sorted(["drc", "lvs"])
    for entry in REGISTRATIONS:
        assert entry["provider"] == "pegasus"
        assert entry["job"] in Job.factory.list()


def test_conformal_registrations_cover_exactly_formal_equivalence():
    from librelane.steps.conformal import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == ["formal_equivalence"]
    for entry in REGISTRATIONS:
        assert entry["provider"] == "conformal"
        assert entry["job"] in Job.factory.list()


# ----------------------------------------------------------------------
# Pegasus's drc/lvs metrics reuse the job's own contracted metric rather
# than inventing a Pegasus-specific name.
# ----------------------------------------------------------------------
def test_pegasus_drc_declares_no_extra_metrics():
    from librelane.steps.pegasus import REGISTRATIONS

    drc_entry = next(e for e in REGISTRATIONS if e["job"] == "drc")
    assert drc_entry.get("metrics", []) == []


def test_pegasus_lvs_declares_only_the_job_s_own_metric():
    from librelane.steps.pegasus import REGISTRATIONS

    lvs_entry = next(e for e in REGISTRATIONS if e["job"] == "lvs")
    assert lvs_entry.get("metrics", []) == ["design__lvs_error__count"]


# ----------------------------------------------------------------------
# Namespaces are declared and tool-specific.
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("modpath", "expected_prefix"),
    [
        ("librelane.steps.genus", "GENUS_"),
        ("librelane.steps.innovus", "INNOVUS_"),
        ("librelane.steps.tempus", "TEMPUS_"),
        ("librelane.steps.quantus", "QUANTUS_"),
        ("librelane.steps.voltus", "VOLTUS_"),
        ("librelane.steps.pegasus", "PEGASUS_"),
        ("librelane.steps.conformal", "CONFORMAL_"),
    ],
)
def test_namespace_is_tool_prefixed(modpath, expected_prefix):
    import importlib

    registrations = importlib.import_module(modpath).REGISTRATIONS
    for entry in registrations:
        assert entry["namespaces"] == (expected_prefix,)


# ----------------------------------------------------------------------
# Innovus declares no native views: no public source establishes a
# DesignFormat for its proprietary database.
# ----------------------------------------------------------------------
def test_innovus_registrations_declare_no_native_views():
    from librelane.steps.innovus import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry.get("native_views", ()) == ()


# ----------------------------------------------------------------------
# Cadence RTL lint ("HAL") was deliberately not scaffolded.
# ----------------------------------------------------------------------
def test_no_hal_or_cadence_lint_step_was_registered():
    from librelane.steps import Step

    for step_id in Step.factory.list():
        assert "HAL" not in step_id
