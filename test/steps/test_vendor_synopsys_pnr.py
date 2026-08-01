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
Behavioral tests for the Design Compiler, Fusion Compiler and IC Compiler II
step scaffolds (librelane/steps/dc.py, fc.py, icc2.py).

These test behavior, not structure: that the scaffold fails loudly and
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


# ----------------------------------------------------------------------
# DC.Synthesis: run() raises, naming the step id and the script path
# ----------------------------------------------------------------------
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_dc_synthesis_run_raises_not_implemented_naming_script(mock_config):  # noqa: F811
    from librelane.steps.dc import Synthesis
    from librelane.state import State

    step_obj = Synthesis(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert step_obj.id in message
    assert step_obj.get_script_path() in message


# ----------------------------------------------------------------------
# get_command(): the confirmed invocation for each of the three tools
# ----------------------------------------------------------------------
def test_dc_get_command_uses_confirmed_dc_shell_invocation():
    from librelane.steps.dc import Synthesis

    step_obj = object.__new__(Synthesis)
    command = step_obj.get_command()

    assert command == ["dc_shell", "-f", step_obj.get_script_path()]


def test_icc2_get_command_raises_naming_binary_as_known_but_syntax_unknown():
    from librelane.steps.icc2 import Floorplan

    step_obj = object.__new__(Floorplan)

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "icc2_shell" in message
    assert "flag" in message or "syntax" in message


def test_fc_get_command_raises_naming_binary_as_known_but_syntax_unknown():
    from librelane.steps.fc import Floorplan

    step_obj = object.__new__(Floorplan)

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "fc_shell" in message
    assert "flag" in message or "syntax" in message


# ----------------------------------------------------------------------
# get_script_path(): resolves to a file that actually exists on disk
# ----------------------------------------------------------------------
DC_STEP_IDS = ["DC.Synthesis"]
ICC2_STEP_IDS = [
    f"ICC2.{cls}"
    for cls in [
        "Floorplan",
        "MacroPlacement",
        "TapcellInsertion",
        "PowerGrid",
        "IOPlacement",
        "GlobalPlacement",
        "PostGPLRepair",
        "DetailedPlacement",
        "CTS",
        "PostCTSOpt",
        "GlobalRouting",
        "PostGRTRepair",
        "AntennaRepair",
        "PostGRTOpt",
        "DetailedRouting",
        "PostRouteOpt",
        "FillInsertion",
    ]
]
FC_STEP_IDS = ["FC.Synthesis"] + [
    f"FC.{cls}"
    for cls in [
        "Floorplan",
        "MacroPlacement",
        "TapcellInsertion",
        "PowerGrid",
        "IOPlacement",
        "GlobalPlacement",
        "PostGPLRepair",
        "DetailedPlacement",
        "CTS",
        "PostCTSOpt",
        "GlobalRouting",
        "PostGRTRepair",
        "AntennaRepair",
        "PostGRTOpt",
        "DetailedRouting",
        "PostRouteOpt",
        "FillInsertion",
    ]
]


@pytest.mark.parametrize("step_id", DC_STEP_IDS + ICC2_STEP_IDS + FC_STEP_IDS)
def test_script_path_resolves_to_a_real_file(step_id):
    from librelane.steps import Step

    step_class = Step.factory.get(step_id)
    assert step_class is not None, f"{step_id} is not a registered step"

    step_obj = object.__new__(step_class)
    script_path = str(step_obj.get_script_path())

    assert os.path.isfile(script_path), f"{step_id}: {script_path} is not a file"


# ----------------------------------------------------------------------
# Every step id in these registrations is a real, registered Step
# ----------------------------------------------------------------------
@pytest.mark.parametrize("step_id", DC_STEP_IDS + ICC2_STEP_IDS + FC_STEP_IDS)
def test_step_is_registered_in_step_factory(step_id):
    from librelane.steps import Step

    assert Step.factory.get(step_id) is not None, (
        f"{step_id} did not register in Step.factory"
    )


# ----------------------------------------------------------------------
# REGISTRATIONS covers exactly the job ids intended, and every job id
# named is a real, registered Job.
# ----------------------------------------------------------------------
def test_dc_registrations_cover_exactly_synthesis():
    from librelane.steps.dc import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == ["synthesis"]
    for entry in REGISTRATIONS:
        assert entry["provider"] == "dc"
        assert entry["job"] in Job.factory.list()


def test_icc2_registrations_cover_exactly_the_seventeen_pnr_jobs():
    from librelane.steps.icc2 import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == sorted(PNR_JOB_IDS)
    for entry in REGISTRATIONS:
        assert entry["provider"] == "icc2"
        assert entry["job"] in Job.factory.list()


def test_fc_registrations_cover_synthesis_and_the_seventeen_pnr_jobs():
    from librelane.steps.fc import REGISTRATIONS

    covered = sorted({entry["job"] for entry in REGISTRATIONS})
    assert covered == sorted(["synthesis"] + PNR_JOB_IDS)
    for entry in REGISTRATIONS:
        assert entry["provider"] == "fc"
        assert entry["job"] in Job.factory.list()


# ----------------------------------------------------------------------
# Namespaces are declared and tool-specific
# ----------------------------------------------------------------------
def test_dc_namespace_is_dc_prefixed():
    from librelane.steps.dc import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry["namespaces"] == ("DC_",)


def test_icc2_namespace_is_icc2_prefixed():
    from librelane.steps.icc2 import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry["namespaces"] == ("ICC2_",)


def test_fc_namespace_is_fc_prefixed():
    from librelane.steps.fc import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry["namespaces"] == ("FC_",)


# ----------------------------------------------------------------------
# No registration declares a native view: no public source establishes one
# for either tool's proprietary database.
# ----------------------------------------------------------------------
def test_icc2_registrations_declare_no_native_views():
    from librelane.steps.icc2 import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry.get("native_views", ()) == ()


def test_fc_registrations_declare_no_native_views():
    from librelane.steps.fc import REGISTRATIONS

    for entry in REGISTRATIONS:
        assert entry.get("native_views", ()) == ()
