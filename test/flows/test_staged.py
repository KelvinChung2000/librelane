# Copyright 2026 LibreLane Contributors
import pytest

from librelane.flows import flow as flow_module, sequential as sequential_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables

#: The minimum a StagedFlow instance needs to reach the point where Steps are
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
    from librelane.jobs import Job
    from librelane.steps import OpenROAD

    class SmallStaged(StagedFlow):
        Stages = [
            Job.global_placement,
            OpenROAD.STAMidPNR,
            Job.detailed_placement,
            Job.cts,
        ]

        class Config(StagedFlow.Config):
            # The cts job declares RUN_CTS as its gate, so any flow including
            # that job has to declare the variable.
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
    boundaries = SmallStaged.job_boundaries(SmallStaged.Steps)

    assert [b.job_ids for b in boundaries] == [
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
    from librelane.jobs import Job

    class Doubled(StagedFlow):
        Stages = [
            Job.factory.get("global_placement"),
            Job.factory.get("global_placement"),
        ]

    assert [step.id for step in Doubled.Steps] == [
        "OpenROAD.GlobalPlacement",
        "OpenROAD.GlobalPlacement-1",
    ]
    boundaries = Doubled.job_boundaries(Doubled.Steps)
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


def test_job_gate_applies_to_every_step_of_the_job():
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.jobs import Job

    class Gated(StagedFlow):
        Stages = [Job.antenna_repair]

        class Config(StagedFlow.Config):
            RUN_ANTENNA_REPAIR: bool = variable(True, description="test gate")

    assert Gated.gating_config_vars == {
        "Odb.DiodesOnPorts": ["RUN_ANTENNA_REPAIR"],
        "Odb.HeuristicDiodeInsertion": ["RUN_ANTENNA_REPAIR"],
        "OpenROAD.RepairAntennas": ["RUN_ANTENNA_REPAIR"],
    }


@pytest.fixture(scope="module")
def ProbeJob():
    """
    A job whose gating variable can be overridden via dataclasses.replace.

    Module-scoped because Job.factory and JobRegistry are process-wide
    singletons. The step ID uses the Test. prefix the repository reserves for
    ephemeral test steps.
    """
    from librelane.jobs import Job, JobRegistry
    from librelane.steps import Step

    @Step.factory.register()
    class Probe(Step):
        id = "Test.ProbeStep"
        name = "Probe Step"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Job(
        id="probe_job",
        full_name="Probe Job",
        default_provider="probe",
        requires=(),
        provides=(),
        gating_config_var="RUN_PROBE_JOB",
    ).register()

    JobRegistry.register(
        job="probe_job",
        provider="probe",
        steps=[Probe],
        namespaces=["PROBE_"],
    )
    return Job.factory.get("probe_job")


def test_modified_job_gating_variable_is_respected(ProbeJob):
    """
    When a flow places a modified copy of a job in its Stages list with
    dataclasses.replace(job, gating_config_var="NEW_VAR"), the modified
    gating variable is used, not the one from Job.factory.

    Regression test: under the old code that re-derived the gating variable
    from Job.factory, this would have produced ["RUN_PROBE_JOB"] instead
    of the correct ["MY_GATE"]. ResolvedSpan.gating_config_var must remain
    authoritative.
    """
    import dataclasses

    from librelane.config import variable
    from librelane.flows import StagedFlow

    class ModifiedGate(StagedFlow):
        Stages = [dataclasses.replace(ProbeJob, gating_config_var="MY_GATE")]

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
    assert Bypassed.job_boundaries(Bypassed.Steps) == []


@pytest.fixture(scope="module")
def ContractTestJob():
    """
    A job whose only provider fails to emit a metric it contracted.

    Module-scoped because Job.factory and JobRegistry are process-wide
    singletons: a function-scoped fixture would fail on the second use with
    "already registered". The step ID uses the Test. prefix the repository
    reserves for ephemeral test steps, which test_registry_snapshot.py excludes.
    """
    from librelane.jobs import Job, JobRegistry
    from librelane.steps import Step

    @Step.factory.register()
    class Silent(Step):
        id = "Test.SilentContract"
        name = "Silent Contract"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    Job(
        id="contract_test",
        full_name="Contract Test",
        default_provider="silent",
        requires=(),
        provides=(),
        metrics=("test__required",),
    ).register()

    JobRegistry.register(
        job="contract_test",
        provider="silent",
        steps=[Silent],
        namespaces=["TEST_"],
    )
    return Job.factory.get("contract_test")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_missing_contracted_metric_raises(ContractTestJob):
    from librelane.flows import StagedFlow
    from librelane.jobs import JobContractError

    class Broken(StagedFlow):
        Stages = [ContractTestJob]

    flow = Broken(_MINIMAL_DESIGN, **_MOCK_PDK)

    with pytest.raises(JobContractError, match="test__required"):
        flow.start()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_skipped_job_is_not_contract_checked(ContractTestJob):
    """
    A job that did not run every step cannot be held to its contract: the
    views and metrics were never attempted.
    """
    from librelane.flows import StagedFlow

    class Broken(StagedFlow):
        Stages = [ContractTestJob]

    flow = Broken(_MINIMAL_DESIGN, **_MOCK_PDK)

    flow.start(skip=["Test.SilentContract"])


@pytest.fixture(scope="module")
def MultiProviderContractJobs():
    """
    Two multi_provider jobs, both shaped like a real one:

    * ``per_provider_contract`` is shaped like ``drc``. Each provider runs its
      own deck and contracts its own metric, and neither emits it.
    * ``joint_contract`` is shaped like ``streamout``. The obligation belongs to
      the job rather than to either provider, and exactly one of the two
      satisfies it, the way ``PRIMARY_GDSII_STREAMOUT_TOOL`` decides which
      stream-out result becomes the neutral ``gds`` view.

    Module-scoped because Job.factory and JobRegistry are process-wide
    singletons. The step IDs use the Test. prefix the repository reserves for
    ephemeral test steps, which test_registry_snapshot.py excludes.
    """
    from librelane.jobs import Job, JobRegistry
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

    Job(
        id="per_provider_contract",
        full_name="Per Provider Contract",
        default_provider=("first", "second"),
        requires=(),
        provides=(),
        multi_provider=True,
    ).register()
    Job(
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
    for job_id, provider, step, metrics in registrations:
        JobRegistry.register(
            job=job_id,
            provider=provider,
            steps=[step],
            namespaces=["TEST_"],
            metrics=metrics,
        )
    return Job.factory.get("per_provider_contract"), Job.factory.get("joint_contract")


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_gating_one_tool_leaves_the_other_s_contract_enforced(
    MultiProviderContractJobs,
):
    """
    Both providers of a multi_provider job used to be collapsed into one
    boundary, and a boundary whose steps did not all run is not held to its
    contract. So gating one tool off - RUN_MAGIC_DRC=false being the real,
    documented case - excused the *other* tool from producing its metric, on a
    job whose whole point is that each provider checks the design
    independently. Since MetricChecker.run warns and returns success when its
    metric is absent, that is a DRC check passing on an unexamined design.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.jobs import JobContractError

    PerProvider, _ = MultiProviderContractJobs

    class Both(StagedFlow):
        Stages = [PerProvider]
        gating_config_vars = {"Test.FirstSilent": ["RUN_FIRST"]}

        class Config(StagedFlow.Config):
            RUN_FIRST: bool = variable(False, description="test gate")

    flow = Both(_MINIMAL_DESIGN, **_MOCK_PDK)

    with pytest.raises(JobContractError, match="test__second"):
        flow.start()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow_module, sequential_module, step_module])
def test_a_job_level_contract_stays_joint_across_its_providers(
    MultiProviderContractJobs,
):
    """
    The converse of the test above, and the reason a provider's contract cannot
    simply be the job's contract repeated per provider.

    A job's own ``provides``/``metrics`` are what the job owes once it
    completes, and a multi_provider job may satisfy them with any one of its
    providers. ``streamout`` is the live case: both tools stream out, but only
    the one named by PRIMARY_GDSII_STREAMOUT_TOOL writes the neutral ``gds``
    view. Holding each provider to the job's obligation separately would fail
    the flow at the first provider's boundary.
    """
    from librelane.flows import StagedFlow

    _, Joint = MultiProviderContractJobs

    class Both(StagedFlow):
        Stages = [Joint]

    flow = Both(_MINIMAL_DESIGN, **_MOCK_PDK)

    flow.start()


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
    from librelane.jobs import JobResolutionError

    _, WantsHeader = PreflightSteps

    class Broken(StagedFlow):
        Steps = [WantsHeader]

    with pytest.raises(JobResolutionError, match="json_h"):
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
    from librelane.jobs import JobResolutionError

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

    with pytest.raises(JobResolutionError, match="json_h"):
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
    is false - OpenROAD carries 'odb' natively across several of its jobs.
    The remedial half of the message must instead name an OpenROAD provider.
    """
    from librelane.flows import StagedFlow
    from librelane.jobs import JobResolutionError

    class Orphan(StagedFlow):
        Steps = [OdbConsumerStep]

    with pytest.raises(JobResolutionError) as excinfo:
        Orphan(_MINIMAL_DESIGN, **_MOCK_PDK)

    message = str(excinfo.value)
    assert "odb" in message
    assert "No provider registration declares view" not in message
    assert "provider 'openroad'" in message


def test_a_wildcard_explicit_gate_does_not_displace_the_job_gate():
    """
    _apply_job_gating merges by exact key, so a wildcard explicit key lands
    as a separate entry and only collides with the generated one at expansion.
    Both entries must survive the merge for the union there to be reachable.
    """
    from librelane.config import variable
    from librelane.flows import StagedFlow
    from librelane.jobs import Job

    class Both(StagedFlow):
        Stages = [Job.cts]
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
