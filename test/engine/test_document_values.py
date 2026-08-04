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
The ``with`` block, at both levels a document has one.

No shipped document sets a value, so these tests carry the whole weight of the
feature: a document that set one would be adding behaviour under cover of a
migration, and the migration's own no-regression pin would stop being a pin.
"""

import pytest

from librelane.engine import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def valued_steps():
    """
    Two steps reading one configuration variable, and one reading a gate.

    Both halves are needed because the covering rule
    (``_check_job_values_are_covering``) is a rule about the document as a
    whole: a job may set a variable in its ``with`` only if every job whose
    steps read that variable also sets it, and only if its own steps read it.
    So a per-job value cannot be exercised by one job in isolation.

    Returns
    -------
    dict[str, str]
        What each step class saw in ``TEST_WITH_VALUE`` when it last ran,
        keyed by the class's id. The class's, not the instance's:
        :class:`librelane.engine.engine.Workflow` names the job in each
        instance's id, and which step read which value is the question.
    """
    from librelane.config import variable
    from librelane.steps import Step

    seen: dict[str, str] = {}

    class Base(Step):
        inputs = []
        outputs = []

        class Config(Step.Config):
            TEST_WITH_VALUE: str = variable("unset", description="x")

        def run(self, state_in, **kwargs):
            seen[type(self).id] = self.config["TEST_WITH_VALUE"]
            return {}, {}

    @Step.factory.register()
    class Left(Base):
        id = "Test.WithLeft"

    @Step.factory.register()
    class Right(Base):
        id = "Test.WithRight"

    @Step.factory.register()
    class Gated(Step):
        # Declares the gate as a *step* variable as well as the document
        # declaring it, because a job's 'with' may only name a variable its own
        # steps read. The two declarations must agree: Flow.get_all_config_variables
        # rejects two unequal variables sharing a name.
        id = "Test.WithGated"
        inputs = []
        outputs = []

        class Config(Step.Config):
            TEST_WITH_GATE: bool = variable(False, description="x")

        def run(self, state_in, **kwargs):
            seen[type(self).id] = "ran"
            return {}, {}

    return seen


def _one_job_document(**document) -> dict:
    """
    Parameters
    ----------
    document
        Keys layered over the one-job skeleton.

    Returns
    -------
    dict
        A document running ``Test.WithLeft`` alone, for the document-level
        ``with``, which has no covering rule to satisfy.
    """
    return {
        "name": "T",
        "jobs": {"left": {"steps": ["Test.WithLeft"]}},
        **document,
    }


def _two_job_document(left: str, right: str, **document) -> dict:
    """
    Parameters
    ----------
    left : str
        The value job ``left`` sets in its ``with``.
    right : str
        The value job ``right`` sets in its ``with``.
    document
        Keys layered over the skeleton.

    Returns
    -------
    dict
        Two chained jobs setting the same variable to different values, which
        is the case the per-job ``with`` exists for and the case no single
        flattened mapping can express.
    """
    return {
        "name": "T",
        "jobs": {
            "left": {
                "steps": ["Test.WithLeft"],
                "with": {"TEST_WITH_VALUE": left},
            },
            "right": {
                "needs": ["left"],
                "steps": ["Test.WithRight"],
                "with": {"TEST_WITH_VALUE": right},
            },
        },
        **document,
    }


@mock_variables([flow_module, step_module])
def test_a_document_value_is_used_when_the_design_is_silent(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _one_job_document(**{"with": {"TEST_WITH_VALUE": "from the document"}})
    )

    workflow = Workflow(spec, minimal_design, **mock_pdk)

    assert workflow.config["TEST_WITH_VALUE"] == "from the document"


@mock_variables([flow_module, step_module])
def test_the_design_overrides_a_document_value(valued_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _one_job_document(**{"with": {"TEST_WITH_VALUE": "from the document"}})
    )

    workflow = Workflow(
        spec,
        dict(minimal_design, TEST_WITH_VALUE="from the design"),
        **mock_pdk,
    )

    assert workflow.config["TEST_WITH_VALUE"] == "from the design"


@mock_variables([flow_module, step_module])
def test_a_command_line_override_beats_a_document_value(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _one_job_document(**{"with": {"TEST_WITH_VALUE": "from the document"}})
    )

    workflow = Workflow(
        spec,
        minimal_design,
        config_override_strings=["TEST_WITH_VALUE=from the command line"],
        **mock_pdk,
    )

    assert workflow.config["TEST_WITH_VALUE"] == "from the command line"


@mock_variables([flow_module, step_module])
def test_a_document_value_naming_an_undeclared_variable_is_rejected(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.config import InvalidConfig
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(_one_job_document(**{"with": {"NOT_A_VARIABLE": 1}}))

    with pytest.raises(InvalidConfig) as exc_info:
        Workflow(spec, minimal_design, **mock_pdk)

    assert "NOT_A_VARIABLE" in str(exc_info.value)
    assert "<flow document>" in str(exc_info.value)


@mock_variables([flow_module, step_module])
def test_each_job_reads_the_value_its_own_with_block_sets(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_job_document("for left", "for right"))

    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert valued_steps == {
        "Test.WithLeft": "for left",
        "Test.WithRight": "for right",
    }


@mock_variables([flow_module, step_module])
def test_a_job_value_stays_out_of_the_flow_configuration(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _two_job_document(
            "for left",
            "for right",
            **{"with": {"TEST_WITH_VALUE": "for the flow"}},
        )
    )

    workflow = Workflow(spec, minimal_design, **mock_pdk)

    # Two jobs hold two values for one key, so no single mapping can carry
    # both. The flow's own configuration answers for the flow.
    assert workflow.config["TEST_WITH_VALUE"] == "for the flow"


@mock_variables([flow_module, step_module])
def test_a_job_value_overrides_a_document_value(valued_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        _two_job_document(
            "for left",
            "for right",
            **{"with": {"TEST_WITH_VALUE": "for the flow"}},
        )
    )

    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert valued_steps == {
        "Test.WithLeft": "for left",
        "Test.WithRight": "for right",
    }


@mock_variables([flow_module, step_module])
def test_the_design_overrides_a_job_value(valued_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_job_document("for left", "for right"))

    Workflow(
        spec,
        dict(minimal_design, TEST_WITH_VALUE="from the design"),
        **mock_pdk,
    ).start(tag="t")

    assert valued_steps == {
        "Test.WithLeft": "from the design",
        "Test.WithRight": "from the design",
    }


@mock_variables([flow_module, step_module])
def test_a_command_line_override_beats_a_job_value(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(_two_job_document("for left", "for right"))

    Workflow(
        spec,
        minimal_design,
        config_override_strings=["TEST_WITH_VALUE=from the command line"],
        **mock_pdk,
    ).start(tag="t")

    assert valued_steps == {
        "Test.WithLeft": "from the command line",
        "Test.WithRight": "from the command line",
    }


@mock_variables([flow_module, step_module])
def test_a_job_cannot_switch_its_own_gate_on(valued_steps, minimal_design, mock_pdk):
    from librelane.engine.engine import Workflow
    from librelane.engine.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "T",
            "config": [
                {
                    "name": "TEST_WITH_GATE",
                    "type": "bool",
                    "description": "x",
                    "default": False,
                }
            ],
            "jobs": {
                "gated": {
                    "steps": ["Test.WithGated"],
                    "if": "TEST_WITH_GATE",
                    "with": {"TEST_WITH_GATE": True},
                }
            },
        }
    )

    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    # 'if' is the engine's question about whether to fire the job, asked of
    # the flow configuration before the job exists to answer for itself.
    assert "Test.WithGated" not in valued_steps


@mock_variables([flow_module, step_module])
def test_a_document_value_is_refused_over_a_resolved_configuration(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowException
    from librelane.engine.spec import FlowSpec

    resolved = Workflow(
        FlowSpec.model_validate(_one_job_document()),
        minimal_design,
        **mock_pdk,
    ).config

    with pytest.raises(FlowException, match="TEST_WITH_VALUE"):
        Workflow(
            FlowSpec.model_validate(
                _one_job_document(**{"with": {"TEST_WITH_VALUE": "from the document"}})
            ),
            resolved,
            **mock_pdk,
        )


@mock_variables([flow_module, step_module])
def test_a_job_value_is_refused_over_a_resolved_configuration(
    valued_steps, minimal_design, mock_pdk
):
    from librelane.engine.engine import Workflow
    from librelane.engine.flow import FlowException
    from librelane.engine.spec import FlowSpec

    resolved = Workflow(
        FlowSpec.model_validate(_one_job_document()),
        minimal_design,
        **mock_pdk,
    ).config

    with pytest.raises(FlowException, match="'left'"):
        Workflow(
            FlowSpec.model_validate(_two_job_document("for left", "for right")),
            resolved,
            **mock_pdk,
        )


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            _one_job_document(**{"with": {"TOOLS": {"left": "yosys"}}}),
            id="document-level",
        ),
        pytest.param(
            {
                "name": "T",
                "jobs": {
                    "left": {
                        "steps": ["Test.WithLeft"],
                        "with": {"TOOLS": {"left": "yosys"}},
                    }
                },
            },
            id="job-level",
        ),
    ],
)
def test_a_with_block_may_not_select_a_tool(document):
    from librelane.engine.spec import FlowSpec, FlowSpecError

    # The provider selection fixes the step set, and is therefore read out of
    # the raw sources before a configuration exists to read it from. A 'with'
    # block naming it would resolve into the configuration and change nothing.
    with pytest.raises(FlowSpecError, match="TOOLS"):
        FlowSpec.model_validate(document)
