# Copyright 2026 LibreLane Contributors
import pytest

from librelane.flows import flow as flow_module, sequential as sequential_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

#: The minimum a Classic instance needs to reach the point where Steps are
#: expanded, under the mock PDK the conftest fixture installs.
_MINIMAL_DESIGN = {
    "DESIGN_NAME": "WHATEVER",
    "VERILOG_FILES": ["/cwd/src/a.v"],
}
_MOCK_PDK = {
    "design_dir": "/cwd",
    "pdk": "dummy",
    "scl": "dummy_scl",
    "pdk_root": "/pdk",
}


@pytest.fixture
def SmallStaged():
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage
    from librelane.steps import OpenROAD

    class SmallStaged(StagedFlow):
        Stages = [
            Stage.global_placement,
            OpenROAD.STAMidPNR,
            Stage.detailed_placement,
            Stage.cts,
        ]

        class Config(StagedFlow.Config):
            # The cts stage declares RUN_CTS as its gate, so any flow including
            # that stage has to declare the variable.
            RUN_CTS: bool = variable(True, description="test gate")

    return SmallStaged


def test_steps_are_populated_at_class_definition(SmallStaged):
    assert [step.id for step in SmallStaged.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.STAMidPNR",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_boundaries_exclude_plain_steps(SmallStaged):
    boundaries = SmallStaged.stage_boundaries(SmallStaged.Steps)

    assert [b.stage_ids for b in boundaries] == [
        ("global_placement",),
        ("detailed_placement",),
        ("cts",),
    ]
    assert [b.last_step_id for b in boundaries] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.DetailedPlacement",
        "OpenROAD.CTS",
    ]


def test_duplicate_normalization_preserves_tags():
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Doubled(StagedFlow):
        Stages = [
            Stage.factory.get("global_placement"),
            Stage.factory.get("global_placement"),
        ]

    assert [step.id for step in Doubled.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    ]
    boundaries = Doubled.stage_boundaries(Doubled.Steps)
    assert len(boundaries) == 1
    assert boundaries[0].step_ids == (
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    )


def test_subclass_declaring_neither_stages_nor_steps_is_rejected():
    """
    StagedFlow.Steps defaults to [] so that defining StagedFlow itself does
    not trip SequentialFlow.__init_subclass__. Without this check that default
    would silently produce a flow that runs nothing.
    """
    from librelane.flows import StagedFlow

    with pytest.raises(TypeError, match="declares neither 'Stages' nor 'Steps'"):

        class Empty(StagedFlow):
            pass


def test_stage_gate_applies_to_every_step_of_the_stage():
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Gated(StagedFlow):
        Stages = [Stage.antenna_repair]

        class Config(StagedFlow.Config):
            RUN_ANTENNA_REPAIR: bool = variable(True, description="test gate")

    assert Gated.gating_config_vars == {
        "Odb.DiodesOnPorts": ["RUN_ANTENNA_REPAIR"],
        "Odb.HeuristicDiodeInsertion": ["RUN_ANTENNA_REPAIR"],
        "OpenROAD.RepairAntennas": ["RUN_ANTENNA_REPAIR"],
    }


@pytest.fixture(scope="module")
def ProbeStage():
    """
    A stage whose gating variable can be overridden via dataclasses.replace.

    Module-scoped because Stage.factory and StageRegistry are process-wide
    singletons. The step ID uses the Test. prefix the repository reserves for
    ephemeral test steps.
    """
    from librelane.stages import Stage, StageRegistry
    from librelane.steps import Step

    @Step.factory.register()
    class Probe(Step):
        id = "Test.ProbeStep"
        name = "Probe Step"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Stage(
        id="probe_stage",
        full_name="Probe Stage",
        default_provider="probe",
        requires=(),
        provides=(),
        gating_config_var="RUN_PROBE_STAGE",
    ).register()

    StageRegistry.register(
        stage="probe_stage",
        provider="probe",
        steps=[Probe],
        namespaces=["PROBE_"],
    )
    return Stage.factory.get("probe_stage")


def test_modified_stage_gating_variable_is_respected(ProbeStage):
    """
    When a flow places a modified copy of a stage in its Stages list with
    dataclasses.replace(stage, gating_config_var="NEW_VAR"), the modified
    gating variable is used, not the one from Stage.factory.

    Regression test: under the old code that re-derived the gating variable
    from Stage.factory, this would have produced ["RUN_PROBE_STAGE"] instead
    of the correct ["MY_GATE"]. ResolvedSpan.gating_config_var must remain
    authoritative.
    """
    import dataclasses

    from librelane.config import variable
    from librelane.flows import StagedFlow

    class ModifiedGate(StagedFlow):
        Stages = [dataclasses.replace(ProbeStage, gating_config_var="MY_GATE")]

        class Config(StagedFlow.Config):
            MY_GATE: bool = variable(True, description="test gate")

    assert ModifiedGate.gating_config_vars == {
        "Test.ProbeStep": ["MY_GATE"],
    }


def test_gating_key_matching_no_step_is_rejected():
    from librelane.config import variable
    from librelane.flows import SequentialFlow
    from librelane.steps import OpenROAD

    with pytest.raises(TypeError, match="matches no step"):

        class Bad(SequentialFlow):
            Steps = [OpenROAD.CTS]
            gating_config_vars = {"OpenROAD.NotAStep": ["RUN_CTS"]}

            class Config(SequentialFlow.Config):
                RUN_CTS: bool = variable(True, description="test gate")


def test_subclass_may_declare_steps_directly():
    from librelane.flows import StagedFlow
    from librelane.steps import OpenROAD

    class Bypassed(StagedFlow):
        Steps = [OpenROAD.STAMidPNR]

    assert [step.id for step in Bypassed.Steps] == ["OpenROAD.STAMidPNR"]
    assert Bypassed.stage_boundaries(Bypassed.Steps) == []


def _flow_with_tools(mock_config, FlowClass, tools, **overrides):
    """
    Instantiates a real flow from an already-resolved configuration, which skips
    Config.load. The mock variable set the fixtures install collides with real
    step variables (DIODE_ON_PORTS), so the real flow cannot be validated under
    them; the pre-pass that reads TOOLS out of raw sources is covered by
    test/stages/test_tools_extraction.py instead.

    Skipping Config.load also means nothing put the flow's own variables into the
    configuration, so its declared defaults are supplied here, with ``overrides``
    applied on top. The view preflight reads the gating variables, and a flow is
    entitled to assume its own variables are present.
    """
    values = {variable.name: variable.default for variable in FlowClass.config_vars}
    values.update(overrides)
    values["TOOLS"] = tools
    return FlowClass(mock_config.copy(**values))


def _classic_with_tools(mock_config, tools, **overrides):
    from librelane.flows import Flow

    return _flow_with_tools(
        mock_config, Flow.factory.get("Classic"), tools, **overrides
    )


#: Selecting klayout alone for the streamout stage removes Magic.StreamOut, and
#: KLayout.XOR compares the two tools' GDSII against each other, so it hard-
#: requires a Magic GDS that nothing then produces. The view preflight says so
#: at startup; see test_klayout_only_streamout_needs_the_xor_disabled. Tests
#: below that select klayout streamout for unrelated reasons turn the XOR off.
_NO_XOR = {"RUN_KLAYOUT_XOR": False}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_tools_reexpands_at_instance_time(mock_config):
    from librelane.flows import Flow

    flow = _classic_with_tools(mock_config, {"streamout": "klayout"}, **_NO_XOR)

    ids = [step.id for step in flow.Steps]
    assert "Magic.StreamOut" not in ids
    assert "KLayout.StreamOut" in ids
    assert [step.id for step in Flow.factory.get("Classic").Steps] != ids, (
        "class-level Steps must not be mutated"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_reexpansion_regenerates_gating_for_the_selected_provider(mock_config):
    flow = _classic_with_tools(mock_config, {"streamout": "klayout"}, **_NO_XOR)

    assert "Magic.StreamOut" not in flow.gating_config_vars
    assert flow.gating_config_vars["KLayout.StreamOut"] == ["RUN_KLAYOUT_STREAMOUT"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_default_run_does_not_reexpand(mock_config):
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    flow = _classic_with_tools(mock_config, {})

    assert [step.id for step in flow.Steps] == [step.id for step in Classic.Steps]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_gates_for_a_deselected_tool_are_dropped_not_rejected(mock_config):
    """
    Selecting one tool of a multi_provider stage removes the other's steps,
    leaving Classic's hand-written per-tool gates with nothing to name. That
    makes them moot, not wrong: rejecting them would make TOOLS unusable for
    exactly the stages it exists to serve.

    The tool's checker goes with it. Checker.MagicDRC belongs to the drc stage's
    magic provider, so deselecting magic removes the step and its gate together,
    rather than leaving a checker demanding a metric no selected tool emitted.
    """
    flow = _classic_with_tools(mock_config, {"drc": "klayout"})

    step_ids = [step.id for step in flow.Steps]
    assert "Magic.DRC" not in step_ids
    assert "Checker.MagicDRC" not in step_ids
    assert "Magic.DRC" not in flow.gating_config_vars
    assert "Checker.MagicDRC" not in flow.gating_config_vars
    assert flow.gating_config_vars["KLayout.DRC"] == ["RUN_KLAYOUT_DRC"]
    assert flow.gating_config_vars["Checker.KLayoutDRC"] == ["RUN_KLAYOUT_DRC"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_chip_with_tools_keeps_its_own_step_list(mock_config):
    """
    Instance-time re-expansion rebuilds ``Steps`` from ``Stages``. Chip declares
    its own ``Stages``, so the rebuilt list must still be Chip's and not
    Classic's, or setting TOOLS on Chip silently runs plain Classic.

    Magic.WriteLEF is the sharpest case: Chip has no such step and so drops the
    gate Classic declares for it, which means a WriteLEF that comes back is a
    step running with a gating variable that no longer reaches it.
    """
    from librelane.flows import Flow

    flow = _flow_with_tools(
        mock_config, Flow.factory.get("Chip"), {"drc": "klayout"}, **_NO_XOR
    )

    ids = [step.id for step in flow.Steps]
    assert "OpenROAD.PadRing" in ids
    assert "Magic.WriteLEF" not in ids
    assert "OpenROAD.IOPlacement" not in ids
    assert "Odb.CustomIOPlacement" not in ids
    assert "Odb.CheckDesignAntennaProperties" not in ids
    assert "Checker.KLayoutDensity" in ids
    # The selection itself still took effect.
    assert "Magic.DRC" not in ids
    assert "KLayout.DRC" in ids


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_unknown_provider_is_rejected_with_the_registered_names():
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    Classic = Flow.factory.get("Classic")
    with pytest.raises(StageResolutionError, match="no provider named 'genus'"):
        Classic({**_MINIMAL_DESIGN, "TOOLS": {"synthesis": "genus"}}, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_unknown_stage_key_is_rejected_with_a_suggestion():
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    Classic = Flow.factory.get("Classic")
    with pytest.raises(StageResolutionError, match="Did you mean: 'synthesis'"):
        Classic({**_MINIMAL_DESIGN, "TOOLS": {"synthesys": "yosys"}}, **_MOCK_PDK)


@pytest.fixture(scope="module")
def ContractTestStage():
    """
    A stage whose only provider fails to emit a metric it contracted.

    Module-scoped because Stage.factory and StageRegistry are process-wide
    singletons: a function-scoped fixture would fail on the second use with
    "already registered". The step ID uses the Test. prefix the repository
    reserves for ephemeral test steps, which test_registry_snapshot.py excludes.
    """
    from librelane.stages import Stage, StageRegistry
    from librelane.steps import Step

    @Step.factory.register()
    class Silent(Step):
        id = "Test.SilentContract"
        name = "Silent Contract"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Stage(
        id="contract_test",
        full_name="Contract Test",
        default_provider="silent",
        requires=(),
        provides=(),
        metrics=("test__required",),
    ).register()

    StageRegistry.register(
        stage="contract_test",
        provider="silent",
        steps=[Silent],
        namespaces=["TEST_"],
    )
    return Stage.factory.get("contract_test")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_missing_contracted_metric_raises(ContractTestStage):
    from librelane.flows import StagedFlow
    from librelane.stages import StageContractError

    class Broken(StagedFlow):
        Stages = [ContractTestStage]

    flow = Broken(_MINIMAL_DESIGN, **_MOCK_PDK)

    with pytest.raises(StageContractError, match="test__required"):
        flow.start()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_skipped_stage_is_not_contract_checked(ContractTestStage):
    """
    A stage that did not run every step cannot be held to its contract: the
    views and metrics were never attempted.
    """
    from librelane.flows import StagedFlow

    class Broken(StagedFlow):
        Stages = [ContractTestStage]

    flow = Broken(_MINIMAL_DESIGN, **_MOCK_PDK)

    flow.start(skip=["Test.SilentContract"])


@pytest.fixture(scope="module")
def MultiProviderContractStages():
    """
    Two multi_provider stages, both shaped like a real one:

    * ``per_provider_contract`` is shaped like ``drc``. Each provider runs its
      own deck and contracts its own metric, and neither emits it.
    * ``joint_contract`` is shaped like ``streamout``. The obligation belongs to
      the stage rather than to either provider, and exactly one of the two
      satisfies it, the way ``PRIMARY_GDSII_STREAMOUT_TOOL`` decides which
      stream-out result becomes the neutral ``gds`` view.

    Module-scoped because Stage.factory and StageRegistry are process-wide
    singletons. The step IDs use the Test. prefix the repository reserves for
    ephemeral test steps, which test_registry_snapshot.py excludes.
    """
    from librelane.stages import Stage, StageRegistry
    from librelane.steps import Step

    class Quiet(Step):
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    @Step.factory.register()
    class FirstSilent(Quiet):
        id = "Test.FirstSilent"
        name = "First Silent"

    @Step.factory.register()
    class SecondSilent(Quiet):
        id = "Test.SecondSilent"
        name = "Second Silent"

    @Step.factory.register()
    class JointSilent(Quiet):
        id = "Test.JointSilent"
        name = "Joint Silent"

    @Step.factory.register()
    class JointEmitter(Quiet):
        id = "Test.JointEmitter"
        name = "Joint Emitter"

        def run(self, state_in, **kwargs):
            return {}, {"test__joint": 0}

    Stage(
        id="per_provider_contract",
        full_name="Per Provider Contract",
        default_provider=("first", "second"),
        requires=(),
        provides=(),
        multi_provider=True,
    ).register()
    Stage(
        id="joint_contract",
        full_name="Joint Contract",
        default_provider=("silent", "emitter"),
        requires=(),
        provides=(),
        metrics=("test__joint",),
        multi_provider=True,
    ).register()

    registrations = (
        ("per_provider_contract", "first", FirstSilent, ["test__first"]),
        ("per_provider_contract", "second", SecondSilent, ["test__second"]),
        ("joint_contract", "silent", JointSilent, []),
        ("joint_contract", "emitter", JointEmitter, []),
    )
    for stage_id, provider, step, metrics in registrations:
        StageRegistry.register(
            stage=stage_id,
            provider=provider,
            steps=[step],
            namespaces=["TEST_"],
            metrics=metrics,
        )
    return Stage.factory.get("per_provider_contract"), Stage.factory.get(
        "joint_contract"
    )


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_gating_one_tool_leaves_the_other_s_contract_enforced(
    MultiProviderContractStages,
):
    """
    Both providers of a multi_provider stage used to be collapsed into one
    boundary, and a boundary whose steps did not all run is not held to its
    contract. So gating one tool off - RUN_MAGIC_DRC=false being the real,
    documented case - excused the *other* tool from producing its metric, on a
    stage whose whole point is that each provider checks the design
    independently. Since MetricChecker.run warns and returns success when its
    metric is absent, that is a DRC check passing on an unexamined design.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import StageContractError

    PerProvider, _ = MultiProviderContractStages

    class Both(StagedFlow):
        Stages = [PerProvider]
        gating_config_vars = {"Test.FirstSilent": ["RUN_FIRST"]}

        class Config(StagedFlow.Config):
            RUN_FIRST: bool = variable(False, description="test gate")

    flow = Both(_MINIMAL_DESIGN, **_MOCK_PDK)

    with pytest.raises(StageContractError, match="test__second"):
        flow.start()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_stage_level_contract_stays_joint_across_its_providers(
    MultiProviderContractStages,
):
    """
    The converse of the test above, and the reason a provider's contract cannot
    simply be the stage's contract repeated per provider.

    A stage's own ``provides``/``metrics`` are what the stage owes once it
    completes, and a multi_provider stage may satisfy them with any one of its
    providers. ``streamout`` is the live case: both tools stream out, but only
    the one named by PRIMARY_GDSII_STREAMOUT_TOOL writes the neutral ``gds``
    view. Holding each provider to the stage's obligation separately would fail
    the flow at the first provider's boundary.
    """
    from librelane.flows import StagedFlow

    _, Joint = MultiProviderContractStages

    class Both(StagedFlow):
        Stages = [Joint]

    flow = Both(_MINIMAL_DESIGN, **_MOCK_PDK)

    flow.start()


#: The four ways an ordinary user turns off one tool of one of `Classic`'s two
#: multi-provider stages: the gating variable, the stage, the provider it
#: removes, and the provider that must stay answerable for its own contract.
_ONE_TOOL_GATED = [
    ("RUN_MAGIC_DRC", "drc", "magic", "klayout"),
    ("RUN_KLAYOUT_DRC", "drc", "klayout", "magic"),
    ("RUN_MAGIC_STREAMOUT", "streamout", "magic", "klayout"),
    ("RUN_KLAYOUT_STREAMOUT", "streamout", "klayout", "magic"),
]


@pytest.mark.parametrize(("gate", "stage_id", "gated", "kept"), _ONE_TOOL_GATED)
@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_gating_one_real_tool_leaves_the_other_s_contract_checked(
    mock_config, gate, stage_id, gated, kept
):
    """
    The same defect as test_gating_one_tool_leaves_the_other_s_contract_enforced,
    read off the real flow rather than an ephemeral stage, for all four ways a
    user can turn one tool of a multi-provider stage off.

    The stage-wide boundary is legitimately not checked here, since a run that
    skipped steps cannot be held to an obligation those steps would have met.
    That is exactly why the surviving provider needs a boundary of its own.
    """
    flow = _classic_with_tools(mock_config, {}, **{gate: False})
    gates = flow._expand_gating_config_vars(
        flow.gating_config_vars, [step.id for step in flow.Steps]
    )

    def runs(step_id: str) -> bool:
        return all(flow.config[name] for name in gates.get(step_id, []))

    boundaries = {
        (boundary.stage_ids, boundary.provider): boundary
        for boundary in flow._boundaries(flow)
    }
    whole_stage = boundaries[((stage_id,), "magic+klayout")]
    assert not all(runs(step_id) for step_id in whole_stage.step_ids)

    assert not all(
        runs(step_id) for step_id in boundaries[((stage_id,), gated)].step_ids
    )
    surviving = boundaries[((stage_id,), kept)]
    assert all(runs(step_id) for step_id in surviving.step_ids)
    assert surviving.provides or surviving.metrics, (
        "the surviving provider must have something of its own to answer for, "
        "or this configuration proves nothing"
    )


@pytest.fixture(scope="module")
def PreflightSteps():
    """
    Two ephemeral steps consuming the same view, one optionally and one not.

    Module-scoped because Step.factory is a process-wide singleton. The IDs use
    the Test. prefix the repository reserves for ephemeral test steps, which
    test_registry_snapshot.py excludes.
    """
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class WantsOptionalHeader(Step):
        id = "Test.WantsOptionalHeader"
        name = "Wants Optional Header"
        inputs = [DesignFormat.json_h.mkOptional()]
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    @Step.factory.register()
    class WantsHeader(Step):
        id = "Test.WantsHeader"
        name = "Wants Header"
        inputs = [DesignFormat.json_h]
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    return WantsOptionalHeader, WantsHeader


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_preflight_rejects_an_input_no_earlier_step_produces(PreflightSteps):
    from librelane.flows import StagedFlow
    from librelane.stages import StageResolutionError

    _, WantsHeader = PreflightSteps

    class Broken(StagedFlow):
        Steps = [WantsHeader]

    with pytest.raises(StageResolutionError, match="json_h"):
        Broken(_MINIMAL_DESIGN, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_preflight_accepts_an_optional_input_nothing_produces(PreflightSteps):
    """
    An optional input is satisfiable by absence, so its being unproduced is not
    a preflight failure. DesignFormat.mkOptional() returns a copy that compares
    unequal to the base view, so the flag has to be tested before membership.
    """
    from librelane.flows import StagedFlow

    WantsOptionalHeader, _ = PreflightSteps

    class Fine(StagedFlow):
        Steps = [WantsOptionalHeader]

    Fine(_MINIMAL_DESIGN, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_preflight_ignores_a_step_its_gating_excludes(PreflightSteps):
    """
    A step gated off in the resolved configuration will not run, so its inputs
    are not requirements. Gating is evaluated in the preflight rather than left
    to run time precisely so that this stays true of both halves: a gate that
    removes a producer must fail here, and a gate that removes a consumer must
    not.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow

    _, WantsHeader = PreflightSteps

    class Gated(StagedFlow):
        Steps = [WantsHeader]
        gating_config_vars = {"Test.WantsHeader": ["RUN_HEADER_CONSUMER"]}

        class Config(StagedFlow.Config):
            RUN_HEADER_CONSUMER: bool = variable(False, description="test gate")

    Gated(_MINIMAL_DESIGN, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_preflight_honours_a_wildcard_gating_key(PreflightSteps):
    """
    Gating keys may be wildcards, and every other reader of them expands
    wildcards. The preflight has to as well, or it rejects a configuration that
    would in fact run.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow

    _, WantsHeader = PreflightSteps

    class Gated(StagedFlow):
        Steps = [WantsHeader]
        gating_config_vars = {"Test.Wants*": ["RUN_HEADER_CONSUMER"]}

        class Config(StagedFlow.Config):
            RUN_HEADER_CONSUMER: bool = variable(False, description="test gate")

    Gated(_MINIMAL_DESIGN, **_MOCK_PDK)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_default_classic_passes_the_preflight(mock_config):
    """
    Nothing in the default expansion consumes a view no earlier step produces.
    A failure here would be a pre-existing bug in Classic, not a reason to
    weaken the check.
    """
    _classic_with_tools(mock_config, {})


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_klayout_only_streamout_needs_the_xor_disabled(mock_config):
    """
    KLayout.XOR compares Magic's GDSII against KLayout's, so selecting klayout
    alone for the streamout stage leaves it hard-requiring a view nothing
    produces. Its gate is RUN_KLAYOUT_XOR plus the two per-tool streamout
    variables, and TOOLS is not one of them, so the gate does not fire and the
    step really would run. This configuration was already broken before the
    preflight existed; the difference is that it now fails at startup naming the
    view instead of crashing once routing is done.
    """
    from librelane.stages import StageResolutionError

    with pytest.raises(StageResolutionError) as raised:
        _classic_with_tools(mock_config, {"streamout": "klayout"})

    message = str(raised.value)
    assert "KLayout.XOR" in message
    assert "mag_gds" in message
    # The error has to name the provider that would have produced the view, or
    # the reader is left to work out for themselves which tool they dropped.
    assert "provider 'magic' of stage 'streamout'" in message


#: The single-provider selections of `Classic` that legitimately fail the view
#: preflight, and the step, view and producer their message must name.
#:
#: Every other selection must construct cleanly. That is the step-ownership
#: invariant: a step that only makes sense when a particular tool was selected
#: belongs inside that tool's provider registration, so deselecting the tool
#: takes the step with it. A step left behind consuming a view no selected
#: provider produces is the bug this pins.
#:
#: The two entries here are not fixable by moving a step, which is why they are
#: listed rather than removed:
#:
#: * KLayout.XOR compares the two streamout tools' GDSII against each other, so
#:   it belongs to neither registration and must stay a plain step. The preflight
#:   reporting it precisely *is* the fix.
#: * Classic's own Stages list runs steps needing the Verilog header, which VHDL
#:   synthesis cannot emit. Omitting them is a different flow, which is what
#:   VHDLClassic is.
_ORPHANING_SELECTIONS = {
    ("streamout", "magic"): (
        "KLayout.XOR",
        "klayout_gds",
        "provider 'klayout' of stage 'streamout'",
    ),
    ("streamout", "klayout"): (
        "KLayout.XOR",
        "mag_gds",
        "provider 'magic' of stage 'streamout'",
    ),
    ("synthesis", "yosys_vhdl"): (
        "Odb.SetPowerConnections",
        "json_h",
        "provider 'yosys' of stage 'synthesis'",
    ),
}


def _stages_with_several_providers(FlowClass) -> dict[str, list[str]]:
    from librelane.stages import Stage, StageRegistry

    return {
        entry.id: StageRegistry.providers(entry.id)
        for entry in FlowClass.Stages
        if isinstance(entry, Stage) and len(StageRegistry.providers(entry.id)) > 1
    }


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_every_single_provider_selection_leaves_no_orphaned_step(mock_config):
    """
    Drives the view preflight across `Classic` once per provider of every stage
    that has more than one, which is what a vendor provider added later gets
    checked by for free: register it, and this test says whether selecting it
    leaves somebody else's tool steps behind.
    """
    from librelane.flows import Flow
    from librelane.stages import StageResolutionError

    selections = _stages_with_several_providers(Flow.factory.get("Classic"))
    assert selections == {
        "synthesis": ["yosys", "yosys_vhdl"],
        "streamout": ["magic", "klayout"],
        "drc": ["magic", "klayout"],
    }, "a stage gained or lost a provider; extend _ORPHANING_SELECTIONS if so"

    for stage_id, providers in selections.items():
        for provider in providers:
            expected = _ORPHANING_SELECTIONS.get((stage_id, provider))
            if expected is None:
                _classic_with_tools(mock_config, {stage_id: provider})
                continue
            with pytest.raises(StageResolutionError) as raised:
                _classic_with_tools(mock_config, {stage_id: provider})
            for fragment in expected:
                assert fragment in str(raised.value), (stage_id, provider, fragment)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_vhdl_synthesis_on_classic_fails_the_preflight(mock_config):
    """
    Classic's own Stages list contains steps that hard-require the Verilog
    header only Yosys.JsonHeader produces, and the yosys_vhdl provider does not
    include that step. Selecting it therefore has to fail at startup naming the
    view, rather than crash deep in the flow. Dropping those steps is what makes
    VHDLClassic a different flow rather than a differently configured Classic.
    """
    from librelane.stages import StageResolutionError

    with pytest.raises(StageResolutionError, match="json_h"):
        _classic_with_tools(mock_config, {"synthesis": "yosys_vhdl"})


def test_metric_modifiers_satisfy_the_contract():
    """
    GeneratePDN emits design__power_grid_violation__count__net:VPWR alongside
    the aggregate. The contract compares base names, so a provider emitting only
    modified variants of a contracted metric still satisfies it.
    """
    from librelane.common import parse_metric_modifiers

    base, modifiers = parse_metric_modifiers(
        "design__power_grid_violation__count__net:VPWR"
    )
    assert base == "design__power_grid_violation__count"
    assert modifiers == {"net": "VPWR"}


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_preflight_gate_expansion_matches_the_real_run_for_a_colliding_key(
    PreflightSteps,
):
    """
    The preflight and the real run must expand a colliding exact and wildcard
    gating key identically, or the preflight predicts a run that does not
    happen. Both go through ``SequentialFlow._expand_gating_config_vars``,
    which unions the two lists, so a step named by both keys is gated off when
    either variable is false.

    In the first two flows below the exact key sets a false gate and the
    wildcard key a true one. The union is ['RUN_A', 'RUN_B'], the false RUN_A
    gates the step off, and that verdict shows up on both sides:

    * With a hard-required input nothing produces, the preflight agrees the
      step never runs and so never walks the input, and construction succeeds.
    * With a satisfiable input, construction succeeds too, and the real run
      confirms the shared verdict by never executing the step.

    The third flow is the control. Turning RUN_A true leaves both members of
    the union true, the step runs, and the preflight raises on the input
    nothing produces - so the silence above is the gate, not a preflight that
    has stopped looking.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import StageResolutionError

    WantsOptionalHeader, WantsHeader = PreflightSteps

    class RequiredCollision(StagedFlow):
        Steps = [WantsHeader]
        gating_config_vars = {
            "Test.WantsHeader": ["RUN_A"],
            "Test.Wants*": ["RUN_B"],
        }

        class Config(StagedFlow.Config):
            RUN_A: bool = variable(False, description="test gate, false")
            RUN_B: bool = variable(True, description="test gate, true")

    RequiredCollision(_MINIMAL_DESIGN, **_MOCK_PDK)

    class OptionalCollision(StagedFlow):
        Steps = [WantsOptionalHeader]
        gating_config_vars = {
            "Test.WantsOptionalHeader": ["RUN_A"],
            "Test.Wants*": ["RUN_B"],
        }

        class Config(StagedFlow.Config):
            RUN_A: bool = variable(False, description="test gate, false")
            RUN_B: bool = variable(True, description="test gate, true")

    flow = OptionalCollision(_MINIMAL_DESIGN, **_MOCK_PDK)
    flow.start()
    assert "Test.WantsOptionalHeader" not in [step.id for step in flow.step_objects]

    class BothTrue(StagedFlow):
        Steps = [WantsHeader]
        gating_config_vars = {
            "Test.WantsHeader": ["RUN_A"],
            "Test.Wants*": ["RUN_B"],
        }

        class Config(StagedFlow.Config):
            RUN_A: bool = variable(True, description="test gate, true")
            RUN_B: bool = variable(True, description="test gate, true")

    with pytest.raises(StageResolutionError, match="json_h"):
        BothTrue(_MINIMAL_DESIGN, **_MOCK_PDK)


@pytest.fixture(scope="module")
def OdbConsumerStep():
    """
    An ephemeral step hard-requiring 'odb', which no registration's
    ``provides`` ever names: it is exclusively a ``native_views`` entry of
    several OpenROAD provider registrations. Module-scoped because
    ``Step.factory`` is a process-wide singleton.
    """
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class WantsOdb(Step):
        id = "Test.WantsOdb"
        name = "Wants Odb"
        inputs = [DesignFormat.odb]
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    return WantsOdb


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_orphaned_native_view_consumer_names_a_native_provider(OdbConsumerStep):
    """
    Pins the fix for a Task 12 review finding: '__how_to_produce' only
    searched 'provides', so an orphaned consumer of a tool-native view such as
    'odb' fell into the "no provider registration declares view" branch, which
    is false - OpenROAD carries 'odb' natively across several of its stages.
    The remedial half of the message must instead name an OpenROAD provider.
    """
    from librelane.flows import StagedFlow
    from librelane.stages import StageResolutionError

    class Orphan(StagedFlow):
        Steps = [OdbConsumerStep]

    with pytest.raises(StageResolutionError) as excinfo:
        Orphan(_MINIMAL_DESIGN, **_MOCK_PDK)

    message = str(excinfo.value)
    assert "odb" in message
    assert "No provider registration declares view" not in message
    assert "provider 'openroad'" in message


def test_help_lists_stages_and_their_providers():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    help_md = Classic.get_help_md()

    assert "#### Stages" in help_md
    assert "| `detailed_routing` | `openroad` |" in help_md
    assert "| `streamout` | `magic`, `klayout` |" in help_md
    assert "| `post_route_opt` | none selected |" in help_md


def test_describe_stages_reports_the_default_selection():
    from librelane.flows import Flow

    Classic = Flow.factory.get("Classic")
    described = dict(Classic.describe_stages())

    assert described["cts"] == "openroad"
    assert described["post_route_opt"] is None


def test_a_wildcard_explicit_gate_does_not_displace_the_stage_gate():
    """
    _apply_stage_gating merges by exact key, so a wildcard explicit key lands
    as a separate entry and only collides with the generated one at expansion.
    Both entries must survive the merge for the union there to be reachable.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.stages import Stage

    class Both(StagedFlow):
        Stages = [Stage.cts]
        gating_config_vars = {"OpenROAD.CTS*": ["MY_GATE"]}

        class Config(StagedFlow.Config):
            RUN_CTS: bool = variable(True, description="test gate")
            MY_GATE: bool = variable(True, description="test gate")

    assert Both.gating_config_vars["OpenROAD.CTS"] == ["RUN_CTS"]
    assert Both.gating_config_vars["OpenROAD.CTS*"] == ["MY_GATE"]

    expanded = StagedFlow._expand_gating_config_vars(
        Both.gating_config_vars,
        [step.id for step in Both.Steps],
    )
    assert expanded["OpenROAD.CTS"] == ["RUN_CTS", "MY_GATE"]
