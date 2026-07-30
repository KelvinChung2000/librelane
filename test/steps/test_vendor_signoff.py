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
Behavioral tests for the six signoff/verification vendor scaffolds: PrimeTime,
StarRC, IC Validator, Formality, VC SpyGlass, and Calibre.

These test what each scaffold actually does (every step and every
get_command() raises), not how it is structured. See librelane/steps/vendor.py
and each tool module's docstring for the provenance behind every assertion
here.
"""

import os

import pytest

from librelane.steps import step
from librelane.steps.calibre import DRC as CalibreDRC
from librelane.steps.calibre import LVS as CalibreLVS
from librelane.steps.fm import FormalEquivalence
from librelane.steps.icv import DRC as ICValidatorDRC
from librelane.steps.icv import LVS as ICValidatorLVS
from librelane.steps.pt import PreSTA, SignoffSTA
from librelane.steps.starrc import Extraction as StarRCExtraction
from librelane.steps.vc_spyglass import Lint as VCSpyGlassLint

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

#: One representative concrete step per tool, plus every stage a tool covers
#: where a tool covers more than one, so the "run() raises" behavior is
#: checked for all nine concrete steps this batch scaffolds.
ALL_STEPS = [
    PreSTA,
    SignoffSTA,
    StarRCExtraction,
    ICValidatorDRC,
    ICValidatorLVS,
    FormalEquivalence,
    VCSpyGlassLint,
    CalibreDRC,
    CalibreLVS,
]

#: Tcl-driven steps only (everything except PrimeTime, which is
#: VendorPythonStep-based and has no script to point at).
TCL_STEPS = [
    StarRCExtraction,
    ICValidatorDRC,
    ICValidatorLVS,
    FormalEquivalence,
    VCSpyGlassLint,
    CalibreDRC,
    CalibreLVS,
]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize("step_cls", ALL_STEPS, ids=lambda cls: cls.id)
def test_signoff_step_run_raises_not_implemented(step_cls, mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = step_cls(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    assert step_obj.id in str(exc_info.value), "Message does not name the step id"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize("step_cls", [PreSTA, SignoffSTA], ids=lambda cls: cls.id)
def test_primetime_step_run_names_the_snps_api_not_a_script(step_cls, mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = step_cls(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.run(State({}))

    message = str(exc_info.value)
    assert "snps" in message, "Message does not name the snps Python API"
    assert ".tcl" not in message, (
        "Message names a script rather than the snps API for a "
        "VendorPythonStep-based step"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize(
    "step_cls",
    [ICValidatorDRC, ICValidatorLVS],
    ids=lambda cls: cls.id,
)
def test_ic_validator_get_command_raises_naming_the_clf_mismatch(step_cls, mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = step_cls(config=mock_config, state_in=State({}))

    # icv is a confirmed binary, and -clf is a confirmed flag, but -clf
    # attaches a file of supplementary command-line arguments, not a rule
    # deck. Using it to attach this step's script would be a guess dressed
    # up in a real flag, so get_command() must raise instead.
    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "icv" in message
    assert "-clf" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_formality_get_command_raises_naming_the_confirmed_binary(mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = FormalEquivalence(config=mock_config, state_in=State({}))

    # fm_shell is a confirmed binary, but no batch-mode flag for handing it
    # a script is established, so a bare ["fm_shell"] would look runnable
    # while actually hanging on an interactive prompt. get_command() must
    # raise rather than return that.
    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "fm_shell" in message
    assert "confirmed" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
@pytest.mark.parametrize(
    "step_cls",
    [CalibreDRC, CalibreLVS],
    ids=lambda cls: cls.id,
)
def test_calibre_get_command_raises_naming_the_confirmed_binary(step_cls, mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = step_cls(config=mock_config, state_in=State({}))

    # calibre is a confirmed binary, but no flag for running it against a
    # rule deck non-interactively is established, so a bare ["calibre"]
    # would look runnable while actually launching an interactive session.
    # get_command() must raise rather than return that.
    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "calibre" in message
    assert "confirmed" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_starrc_get_command_raises_naming_unestablished_binary(mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = StarRCExtraction(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "StarRC" in message
    assert "binary" in message


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_vc_spyglass_get_command_raises_naming_unestablished_binary(mock_config):  # noqa: F811
    from librelane.state import State

    step_obj = VCSpyGlassLint(config=mock_config, state_in=State({}))

    with pytest.raises(NotImplementedError) as exc_info:
        step_obj.get_command()

    message = str(exc_info.value)
    assert "VC SpyGlass" in message
    assert "binary" in message


@pytest.mark.parametrize("step_cls", TCL_STEPS, ids=lambda cls: cls.id)
def test_tcl_driven_step_script_path_resolves_to_a_real_file(step_cls):
    # Deliberately bypasses __init__ (and therefore config/state, and the
    # pyfakefs sandbox other tests in this module use): get_script_path()
    # only touches the class-level script_dir/script_filename attributes,
    # and this check needs to see the real repository filesystem to catch a
    # stub file that was never actually created.
    step_obj = step_cls.__new__(step_cls)

    script_path = step_obj.get_script_path()

    assert os.path.exists(script_path), (
        f"{step_cls.__name__}.get_script_path() resolves to '{script_path}', "
        "which does not exist on disk"
    )


def test_registrations_cover_exactly_the_intended_stages():
    import librelane.stages  # noqa: F401  (registers the stage taxonomy)
    from librelane.stages import Stage
    from librelane.steps import calibre, fm, icv, pt, starrc, vc_spyglass

    modules = [pt, starrc, icv, fm, vc_spyglass, calibre]

    all_stage_ids: set[str] = set()
    for module in modules:
        assert module.REGISTRATIONS, f"{module.__name__} declares no REGISTRATIONS"
        for registration in module.REGISTRATIONS:
            all_stage_ids.add(registration["stage"])

    assert all_stage_ids == {
        "pre_pnr_sta",
        "signoff_sta",
        "extraction",
        "drc",
        "lvs",
        "formal_equivalence",
        "lint",
    }

    known_stage_ids = set(Stage.factory.list())
    for stage_id in all_stage_ids:
        assert stage_id in known_stage_ids, (
            f"Registration names stage '{stage_id}', which is not in the "
            "registered stage taxonomy"
        )
