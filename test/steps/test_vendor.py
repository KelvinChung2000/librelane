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


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_tcl_step_with_known_binary_raises_and_names_script(mock_config):  # noqa: F811
    from librelane.steps.vendor import VendorTclStep
    from librelane.state import State

    class VendorTclStepTest(VendorTclStep):
        inputs = []
        outputs = []
        id = "Test.VendorTclStepKnownBinary"
        binary = "dc_shell"
        script_dir = "design_compiler"
        script_filename = "synthesis.tcl"

        def get_command(self):
            return [self.binary, "-f", self.get_script_path()]

    step_obj = VendorTclStepTest(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert step_obj.id in message, "Message does not name the step id"
    assert step_obj.get_script_path() in message, (
        "Message does not name the script path"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_tcl_step_with_unknown_binary_mentions_unestablished_invocation(
    mock_config,  # noqa: F811
):
    from librelane.steps.vendor import VendorTclStep
    from librelane.state import State

    class VendorTclStepTest(VendorTclStep):
        inputs = []
        outputs = []
        id = "Test.VendorTclStepUnknownBinary"
        # binary intentionally left at its default of None: this is one of
        # the seven tools whose invocation binary no public source
        # establishes.
        script_dir = "calibre"
        script_filename = "drc.tcl"

        def get_command(self):
            # Per VendorTclStep's contract: a tool whose invocation the
            # research report leaves UNKNOWN must have its get_command()
            # raise, naming what is unknown, rather than being omitted.
            raise NotImplementedError(
                f"{type(self).__name__}: no public source establishes "
                "Calibre's invocation binary or command-line syntax."
            )

    assert VendorTclStepTest.binary is None

    step_obj = VendorTclStepTest(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert step_obj.id in message, "Message does not name the step id"
    assert step_obj.get_script_path() in message, (
        "Message does not name the script path"
    )
    assert "no public source" in message, (
        "Message does not explain that the invocation binary is unestablished"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_tcl_step_get_script_path_composes_scripts_directory(mock_config):  # noqa: F811
    from importlib.resources import files

    from librelane.steps.vendor import VendorTclStep
    from librelane.state import State

    class VendorTclStepTest(VendorTclStep):
        inputs = []
        outputs = []
        id = "Test.VendorTclStepScriptPath"
        binary = "innovus"
        script_dir = "innovus"
        script_filename = "floorplan.tcl"

        def get_command(self):
            return [self.binary, "-nowin", "-files", self.get_script_path()]

    step_obj = VendorTclStepTest(config=mock_config, state_in=State({}))

    expected = str(files("librelane").joinpath("scripts", "innovus", "floorplan.tcl"))
    assert step_obj.get_script_path() == expected


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_tcl_step_without_get_command_cannot_be_instantiated(mock_config):  # noqa: F811
    from librelane.steps.vendor import VendorTclStep
    from librelane.state import State

    class VendorTclStepTest(VendorTclStep):
        inputs = []
        outputs = []
        id = "Test.VendorTclStepMissingGetCommand"
        binary = "dc_shell"
        script_dir = "design_compiler"
        script_filename = "synthesis.tcl"
        # get_command() deliberately not overridden.

    with pytest.raises(TypeError, match="get_command"):
        VendorTclStepTest(config=mock_config, state_in=State({}))


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_tcl_step_get_script_path_raises_when_script_dir_unset(mock_config):  # noqa: F811
    from librelane.steps.vendor import VendorTclStep
    from librelane.state import State

    class VendorTclStepTest(VendorTclStep):
        inputs = []
        outputs = []
        id = "Test.VendorTclStepUnsetScriptDir"
        binary = "dc_shell"
        # script_dir deliberately left at its default of NotImplemented.
        script_filename = "synthesis.tcl"

        def get_command(self):
            return [self.binary, "-f", self.get_script_path()]

    step_obj = VendorTclStepTest(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_script_path()

    message = str(exc_info.value)
    assert "VendorTclStepTest" in message, "Message does not name the class"
    assert "script_dir" in message, "Message does not name the missing attribute"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vendor_python_step_raises_not_implemented(mock_config):  # noqa: F811
    from librelane.steps.vendor import VendorPythonStep
    from librelane.state import State

    class VendorPythonStepTest(VendorPythonStep):
        inputs = []
        outputs = []
        id = "Test.VendorPythonStep"

    step_obj = VendorPythonStepTest(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert step_obj.id in message, "Message does not name the step id"
