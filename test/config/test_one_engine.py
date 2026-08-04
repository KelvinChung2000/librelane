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
One set of rules for what a configuration value may be, whichever door it
came in by.

A value reaches LibreLane through a design file, through a PDK's ``config.tcl``
or through a keyword argument to a step, and those used to be validated by two
different implementations: the merged design sources went through
``validate_mapping`` and Pydantic, while the other two went through
``Variable.compile``. The two did not agree -- ``"yes"`` was a Boolean to one
and a type error to the other -- so whether a configuration was legal depended
on which of the three had carried it.
"""

import pytest

from librelane.config import Variable
from librelane.config import config

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


#: One of each shape whose reading differed between the two implementations.
_VARIABLES = [
    Variable("TEST_BOOL", bool, description="x", default=False),
    Variable("TEST_INT", int, description="x", default=0),
]


def _through_a_layer(values):
    """
    The path a PDK's compiled values and a step's keyword arguments take.

    Returns
    -------
    tuple[dict, list[str]]
        The processed values and the errors raised.
    """
    from librelane.common import GenericDict
    from librelane.config import Config

    processed, _, errors, _ = Config._Config__process_variable_list(
        GenericDict(values),
        _VARIABLES,
        on_unknown_key=None,
        permissive_typing=True,
    )
    return dict(processed), errors


def _through_the_loader(values):
    """
    The path a design configuration takes, on an openlane-era document, where
    every string is Tcl text exactly as the PDK layer's are.

    Returns
    -------
    tuple[dict, list[str]]
        The processed values and the errors raised.
    """
    from librelane.config.validation import validate_mapping

    processed, diagnostics, _ = validate_mapping(
        values,
        _VARIABLES,
        permissive=True,
        on_unknown_key=None,
    )
    return processed, diagnostics.rendered_errors()


@pytest.mark.parametrize(
    "values",
    [
        # The repro: 'compile' took 1/true/True and nothing else, while
        # Pydantic's lax mode takes every spelling a shell does.
        {"TEST_BOOL": "yes"},
        {"TEST_BOOL": "on"},
        {"TEST_BOOL": "1"},
        {"TEST_BOOL": "false"},
        {"TEST_INT": "4"},
        # Booleans are ints in Python and a boolean is never a quantity, which
        # both implementations had to say separately.
        {"TEST_INT": True},
    ],
)
def test_every_door_reads_a_value_the_same_way(values):
    layered, layered_errors = _through_a_layer(values)
    loaded, load_errors = _through_the_loader(values)

    assert bool(layered_errors) == bool(load_errors), (
        f"{values} is legal through one entry point and not the other: "
        f"{layered_errors} vs {load_errors}"
    )
    if not layered_errors:
        assert layered == loaded, f"{values} was read differently"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_a_step_increment_reads_a_value_the_way_the_file_did():
    """
    The same rule at the boundary a user actually meets: a value legal in a
    design file has to remain legal when a step is handed it directly -- and a
    value illegal in one has to be illegal in the other.

    'yes' used to be a Boolean in a document declaring ``meta.version`` 1,
    whose strings were Tcl text. That reading is gone, so neither side takes
    it and both sides take a real Boolean.
    """
    from librelane.config import Config, InvalidConfig

    variables = config.flow_common_variables + [
        Variable("RUN_TEST", bool, description="x", default=False)
    ]

    def load(run_test):
        resolved, _ = Config.load(
            {
                "DESIGN_NAME": "whatever",
                "VERILOG_FILES": "dir::src/*.v",
                "RUN_TEST": run_test,
            },
            variables,
            design_dir="/cwd",
            pdk="dummy",
            scl="dummy_scl",
            pdk_root="/pdk",
        )
        return resolved

    with pytest.raises(InvalidConfig):
        load("yes")

    resolved = load(True)
    assert resolved["RUN_TEST"] is True

    # The step boundary agrees with the file on both counts.
    with pytest.raises(InvalidConfig):
        resolved.with_increment(variables, {"RUN_TEST": "no"})

    assert resolved.with_increment(variables, {"RUN_TEST": False})["RUN_TEST"] is False
