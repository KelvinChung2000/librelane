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
The load-time refusal of a provider selection a document cannot run.

Two halves, and both are needed. The rule is exercised against the *shipped*
documents, because the selections worth pinning are the ones a real user can
write and every one of them was measured rather than predicted. The engine
*wiring* is exercised against a synthetic document, because a shipped one needs
a PDK supplying some 55 variables the mock tree does not have, so
``Workflow(Flow.factory.get("Classic"), ...)`` cannot be constructed here at all.
"""

import subprocess
import sys
import textwrap

import pytest

import librelane.steps  # noqa: F401  populates Step.factory and JobRegistry

from librelane.flows import flow as flow_module
from librelane.flows.job import resolve_jobs
from librelane.flows.selection_validation import (
    SINK_JOIN,
    join_conflicts,
    lost_views,
    produced_keys,
    validate_selection,
)
from librelane.jobs import JobResolutionError
from librelane.steps import step as step_module

from test.flows.test_documents import (
    _alternate_providers,
    _document,
    _shipped_documents,
)

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _default_enabled(document: str) -> set[str]:
    """
    Parameters
    ----------
    document : str
        A shipped document's file name.

    Returns
    -------
    set[str]
        The jobs a stock configuration of it runs, read off the defaults its own
        ``config`` block declares rather than written down here.

    Derived, not literal, because the point of every test below is *which*
    selections a user meets, and a hand-written enabled set would be pinning the
    author's belief about the defaults rather than the defaults. Four to five
    jobs per document are off in stock form -- ``rmp``, ``post_grt_repair``,
    ``post_grt_opt``, ``heuristic_diode_insertion`` and, where it exists,
    ``formal_equivalence`` -- so this is not the same set as "every job", and
    the difference is the whole subject of
    :func:`test_gating_a_job_off_makes_its_selection_loadable`.
    """
    spec = _document(document)
    defaults = {declared.name: declared.default for declared in spec.config}
    return {
        job_id
        for job_id, job in resolve_jobs(spec).items()
        if all(defaults[condition] for condition in job.conditions)
    }


def _refusal(document: str, tools: dict[str, str]) -> str | None:
    """
    Parameters
    ----------
    document : str
        A shipped document's file name.
    tools : dict[str, str]
        The ``TOOLS`` selection to validate.

    Returns
    -------
    str | None
        The message :func:`validate_selection` refuses this selection with, or
        ``None`` if it accepts it. Under the document's own default gating,
        which is the configuration a user who sets only ``TOOLS`` has.
    """
    spec = _document(document)
    try:
        validate_selection(spec, resolve_jobs(spec, tools), _default_enabled(document))
    except JobResolutionError as refused:
        return str(refused)
    return None


#: Every single-key ``TOOLS`` selection the shipped documents admit, mapped to
#: whether it can run, and for the ones that cannot, to a fragment of the
#: refusal naming what breaks.
#:
#: Measured, not predicted: the enumeration is
#: :func:`test_documents._alternate_providers` over every shipped document, and
#: :func:`test_every_single_key_selection_is_classified` pins that this literal
#: covers exactly it, so a provider registered later cannot slip past by being
#: unlisted.
#:
#: Seventeen of the eighteen are refused, which is a fact about the documents
#: rather than about this check. Three shapes:
#:
#: * ``synthesis`` to ``yosys_vhdl`` on a Verilog document drops ``json_h``,
#:   which ``Odb.SetPowerConnections`` and ``Odb.WriteVerilogHeader`` hard-require.
#:   This is the case ``Changelog.md`` and ``docs/usage/swapping_tools.md``
#:   described as accepted-at-load-and-fatal-mid-run.
#: * Re-pointing either stream-out at the other's tool leaves ``KLayout.XOR``
#:   with one GDSII instead of two, and both its inputs are non-optional.
#: * Re-pointing either DRC job at the other's tool, or ``lvs`` at ``klayout``,
#:   puts a second writer of one key on a concurrent branch. These are the nine
#:   ``test_documents._SELECTIONS_A_DOCUMENT_DOES_NOT_SURVIVE`` already measured.
#:
#: The one that runs is ``vhdl_classic.yaml``'s ``synthesis`` back to ``yosys``:
#: that document declares no job needing the Verilog header, so restoring the
#: Verilog front end takes nothing away.
_SINGLE_KEY_SELECTIONS: dict[tuple[str, str, str], str | None] = {
    ("chip.yaml", "synthesis", "yosys_vhdl"): "requires view 'json_h'",
    ("chip.yaml", "magic_streamout", "klayout"): "requires view 'mag_gds'",
    ("chip.yaml", "klayout_streamout", "magic"): "requires view 'klayout_gds'",
    ("chip.yaml", "magic_drc", "klayout"): "both write 'klayout__drc_error__count'",
    ("chip.yaml", "klayout_drc", "magic"): "both write 'magic__drc_error__count'",
    ("chip.yaml", "lvs", "klayout"): "both write 'flow__errors__count'",
    ("classic.yaml", "synthesis", "yosys_vhdl"): "requires view 'json_h'",
    ("classic.yaml", "magic_streamout", "klayout"): "requires view 'mag_gds'",
    ("classic.yaml", "klayout_streamout", "magic"): "requires view 'klayout_gds'",
    ("classic.yaml", "magic_drc", "klayout"): "both write 'klayout__drc_error__count'",
    ("classic.yaml", "klayout_drc", "magic"): "both write 'magic__drc_error__count'",
    ("classic.yaml", "lvs", "klayout"): "both write 'flow__errors__count'",
    ("vhdl_classic.yaml", "synthesis", "yosys"): None,
    ("vhdl_classic.yaml", "magic_streamout", "klayout"): "requires view 'mag_gds'",
    ("vhdl_classic.yaml", "klayout_streamout", "magic"): (
        "requires view 'klayout_gds'"
    ),
    ("vhdl_classic.yaml", "magic_drc", "klayout"): (
        "both write 'klayout__drc_error__count'"
    ),
    ("vhdl_classic.yaml", "klayout_drc", "magic"): (
        "both write 'magic__drc_error__count'"
    ),
    ("vhdl_classic.yaml", "lvs", "klayout"): "both write 'flow__errors__count'",
}


def test_every_single_key_selection_is_classified():
    """
    The literal above is written out and the enumeration is derived, so this is
    what stops the two drifting: a provider registered for a job some shipped
    document declares gains a row here or fails.

    Both directions matter. An unlisted selection would go untested while the
    table still read as coverage, and a listed one that no longer exists would
    be a claim about a configuration nobody can write.
    """
    enumerated = {
        (document, job_id, provider)
        for document in _shipped_documents()
        for job_id, provider in _alternate_providers(document)
    }

    assert enumerated == set(_SINGLE_KEY_SELECTIONS)


@pytest.mark.parametrize(
    ("document", "job_id", "provider", "expected"),
    [(*key, value) for key, value in sorted(_SINGLE_KEY_SELECTIONS.items())],
)
def test_a_single_key_selection_is_refused_exactly_when_it_cannot_run(
    document, job_id, provider, expected
):
    """
    The primary claim: every selection that would fail during a run is refused
    while the flow is being constructed, and every selection that would run is
    not.

    The second half is the one that needs saying. A load-time refusal is a
    strictly worse outcome than a mid-run failure whenever it is wrong, so the
    row asserting ``None`` is not filler -- it is the whole no-false-rejection
    property, applied to the one selection that has it.
    """
    refusal = _refusal(document, {job_id: provider})

    if expected is None:
        assert refusal is None
        return
    assert refusal is not None
    assert expected in refusal


@pytest.mark.parametrize("document", _shipped_documents())
def test_a_shipped_document_loads_clean_with_no_selection_at_all(document):
    """
    The other half of the no-false-rejection property, and the one that would
    break loudest: a stock configuration of a shipped document must reach the
    engine unchanged.

    Derived over the package's contents rather than named, for the reason
    ``test_documents._shipped_documents`` gives: a document added later is
    covered without anyone remembering to add it.
    """
    assert _refusal(document, {}) is None


def test_gating_a_job_off_makes_its_selection_loadable():
    """
    The soundness property that decides whether this check may exist at all.

    ``{"magic_drc": "klayout"}`` collides with ``klayout_drc`` only because both
    jobs run. ``RUN_MAGIC_DRC: false`` is what the old stage-keyed
    ``{"drc": "klayout"}`` actually migrates to, so a user writing both is
    writing a configuration that runs one KLayout DRC deck and nothing else --
    and a check that refused it would be rejecting a working flow, which is
    worse than the mid-run failure it replaces.

    Asserted against the same selection the test above asserts is refused, so
    the two rows cannot both be satisfied by a check that ignores its
    ``enabled`` argument.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec, {"magic_drc": "klayout"})
    enabled = _default_enabled("classic.yaml")

    assert "magic_drc" in enabled
    validate_selection(spec, jobs, enabled - {"magic_drc"})


def test_gating_the_consumer_off_makes_a_lost_view_loadable():
    """
    The same property for the view half. ``KLayout.XOR`` is what needs both
    stream-outs' GDSII, so a configuration that has already turned the XOR off
    can re-point a stream-out freely.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec, {"magic_streamout": "klayout"})
    enabled = _default_enabled("classic.yaml")

    assert "xor" in enabled
    validate_selection(spec, jobs, enabled - {"xor"})


def test_the_refusal_names_the_key_the_two_jobs_and_a_working_alternative():
    """
    What the message has to carry to be worth raising instead of letting the run
    discover it: the key that collides, both jobs that write it, and the
    ``TOOLS`` value that would work instead.

    The alternative is measured rather than assumed -- every other registered
    provider is re-resolved and re-checked, and only the ones that come out
    clean are offered -- so this also pins that the search found the obvious
    answer, which is the provider the document already had.
    """
    refusal = _refusal("classic.yaml", {"magic_drc": "klayout"})

    assert refusal is not None
    assert "klayout__drc_error__count" in refusal
    assert "'magic_drc'" in refusal
    assert "'klayout_drc'" in refusal
    assert "set TOOLS['magic_drc'] to 'magic'" in refusal
    assert "set 'RUN_MAGIC_DRC' to false" in refusal


def test_every_open_source_registration_is_runnable():
    """
    The baseline the scaffold filter is measured against, and what stops it
    quietly swallowing a real provider: nothing LibreLane registers by default
    is a scaffold, so the filter subtracts nothing from a stock installation.

    Reads :attr:`librelane.jobs.registry.Registration.runnable`, which is
    derived from every step's ``implemented``, so a step class that acquires a
    raising ``run`` without saying so is caught here rather than by a user whose
    remedy list silently shortened.
    """
    from librelane.jobs import JobRegistry

    not_runnable = [
        (registration.job, registration.provider)
        for registration in JobRegistry.list()
        if not registration.runnable
    ]

    assert not_runnable == []


def test_a_scaffold_declares_itself_unimplemented_and_an_ordinary_step_does_not():
    """
    Where the datum lives, pinned at its two ends.

    ``implemented`` is declared on the two commercial bases rather than
    inferred from them, and this is what would fail if someone replaced it with
    an ``issubclass`` test: a licensed backend built by filling one of these in
    is still a ``VendorTclStep``, and the only thing that may distinguish it is
    this line.

    Importing :mod:`librelane.steps.vendor` in-process is safe. It defines
    classes and registers no provider; the opt-in that does is
    :mod:`librelane.jobs.providers_vendor`, which the test below runs in a
    subprocess for exactly that reason.
    """
    from librelane.steps import Step
    from librelane.steps.vendor import VendorPythonStep, VendorTclStep

    assert Step.implemented is True
    assert VendorTclStep.implemented is False
    assert VendorPythonStep.implemented is False

    magic_drc = Step.factory.get("Magic.DRC")
    assert magic_drc is not None
    assert magic_drc.implemented is True


def test_a_remedy_never_names_a_commercial_scaffold():
    """
    The failure this guards: with the commercial opt-in taken, ``drc`` gains
    ``calibre``, ``icv`` and ``pegasus``. All three resolve and replay
    perfectly cleanly -- they contribute the right steps with the right
    contracts -- so a remedy search that only asks "does the document come out
    clean" offers all three, and every one of them raises
    ``NotImplementedError`` the moment it runs. The reader is sent from an error
    they could act on to one they cannot.

    Run in a throwaway subprocess, following
    ``test/jobs/test_providers_vendor.py``: ``JobRegistry`` is a process-wide
    singleton with no way to unregister, so importing the aggregator here would
    add sixteen providers to every later test in the session and break the
    18-row enumeration above depending on order under ``pytest-randomly``.

    The subprocess asserts the opt-in actually happened before asserting what
    the message says, because a remedy list with no scaffold in it is exactly
    what a *failed* import would also produce.
    """
    script = textwrap.dedent(
        """
        import librelane.steps  # noqa: F401  populates Step.factory
        import librelane.jobs.providers_vendor  # noqa: F401  the opt-in
        from importlib.resources import files

        from librelane.flows.job import resolve_jobs
        from librelane.flows.selection_validation import validate_selection
        from librelane.flows.spec import load_flow_spec
        from librelane.flows.spec_validation import validate_against_registry
        from librelane.jobs import JobRegistry, JobResolutionError

        scaffolds = {"calibre", "icv", "pegasus"}
        providers = set(JobRegistry.providers("drc"))
        assert scaffolds <= providers, (
            f"the opt-in did not take effect, so this proves nothing: {providers}"
        )

        spec = load_flow_spec(str(files("librelane.flows").joinpath("classic.yaml")))
        validate_against_registry(spec)
        defaults = {declared.name: declared.default for declared in spec.config}
        enabled = {
            job_id
            for job_id, job in resolve_jobs(spec).items()
            if all(defaults[condition] for condition in job.conditions)
        }

        try:
            validate_selection(
                spec, resolve_jobs(spec, {"magic_drc": "klayout"}), enabled
            )
        except JobResolutionError as refused:
            message = str(refused)
        else:
            raise AssertionError("{'magic_drc': 'klayout'} was not refused")

        named = {name for name in scaffolds if name in message}
        assert not named, f"remedy names unrunnable scaffolds {sorted(named)}"
        assert "set TOOLS['magic_drc'] to 'magic'" in message, message

        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"subprocess check failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_the_refusal_for_a_lost_view_names_the_view_and_the_producer():
    """
    The ``{"synthesis": "yosys_vhdl"}`` on ``Classic`` case, which is what
    ``Changelog.md`` and ``docs/usage/swapping_tools.md`` both described as
    accepted at load and fatal during the run.

    The remedy offered is a provider swap and not a gate: dropping the
    *producer* of a missing view changes nothing, and ``set_power_connections``
    carries no ``if`` to drop, so ``Classic`` genuinely cannot make this
    selection and the message says only the one true thing.
    """
    refusal = _refusal("classic.yaml", {"synthesis": "yosys_vhdl"})

    assert refusal is not None
    assert "json_h" in refusal
    assert "'set_power_connections'" in refusal
    assert "'synthesis'" in refusal
    assert "set TOOLS['synthesis'] to 'yosys'" in refusal
    assert "RUN_" not in refusal


def test_the_vhdl_document_makes_the_same_selection_and_is_accepted():
    """
    The recommendation the message above leaves standing, checked rather than
    asserted in prose: ``VHDLClassic`` runs ``yosys_vhdl`` for ``synthesis`` and
    loads clean, because it declares no job that needs the Verilog header.
    """
    assert resolve_jobs(_document("vhdl_classic.yaml"))["synthesis"].provider == (
        "yosys_vhdl"
    )
    assert _refusal("vhdl_classic.yaml", {}) is None


def test_a_registration_s_native_views_are_a_requirement_the_check_reads():
    """
    ``Registration.native_views`` used to buy a registration-time exemption and
    be re-validated nowhere, because the resolution-time preflight it deferred
    to was deleted with ``librelane/jobs/resolution.py``. This is the check that
    now answers for it, so the datum has to reach the check: a resolved job
    carries its selected registration's ``native_views``, and
    :func:`lost_views` treats them exactly as it treats ``requires``.

    ``lvs``'s ``klayout`` provider is the one that makes the two distinguishable
    -- it declares ``odb`` native while the job's own ``requires`` does not
    mention it -- so an implementation reading only ``requires`` passes every
    other assertion in this file and fails this one.
    """
    spec = _document("classic.yaml")

    assert resolve_jobs(spec)["lvs"].native_views == ()
    native = resolve_jobs(spec, {"lvs": "klayout"})["lvs"].native_views
    assert [view.id for view in native] == ["odb"]
    assert "odb" not in {str(view) for view in resolve_jobs(spec)["lvs"].requires}


def test_the_framework_metrics_are_modelled_as_written_by_openroad_jobs():
    """
    The three ``flow__*`` counts OpenROAD's logger fills in are declared by no
    step, template or registration, so nothing reading contracts can see them,
    and they are the entire reason ``{"lvs": "klayout"}`` is fatal. Pinned here
    against the resolved jobs so that a step family gaining or losing its
    OpenROAD base changes this rather than silently changing a verdict.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)
    produced = produced_keys(jobs, set(jobs))

    assert "flow__errors__count" in produced["floorplan"]
    assert "flow__errors__count" not in produced["magic_streamout"]

    selected = resolve_jobs(spec, {"lvs": "klayout"})
    assert "flow__errors__count" not in produced_keys(jobs, set(jobs))["lvs"]
    assert "flow__errors__count" in produced_keys(selected, set(selected))["lvs"]


def test_a_disabled_job_writes_nothing():
    """
    The modelling that the whole gating argument rests on. A job whose ``if`` is
    false fires as a pass-through and its output token is its input token, so it
    contributes no writer for any key.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)

    assert produced_keys(jobs, set(jobs))["magic_drc"]
    assert produced_keys(jobs, set(jobs) - {"magic_drc"})["magic_drc"] == set()


def test_a_view_no_job_produces_is_still_presumed_to_arrive_in_the_state():
    """
    The presumption ``spec_validation`` makes and this check must not revoke: a
    document may start mid-flow, so a view nothing in it produces is left to the
    run. ``lost_views`` is a differential against the document's own providers
    precisely so that it never has an opinion about such a view.

    ``classic.yaml``'s ``synthesis`` job requires nothing and every document
    starts from an initial state, so the honest way to pin this is to ask the
    baseline of itself: with no selection, nothing is lost, however many views
    the document leaves to the state.
    """
    spec = _document("classic.yaml")
    jobs = resolve_jobs(spec)

    assert lost_views(spec, jobs, set(jobs)) == []


#: A two-job document whose jobs run concurrently and whose providers write one
#: metric each. ``TOOLS`` pointing ``left`` at ``beta`` makes both write
#: ``probe__beta``, which is the ``magic_drc``/``klayout_drc`` collision in
#: miniature -- and, like it, one that ``spec_validation`` cannot see, because
#: the *document* still declares two providers writing two different metrics.
_PROBE_SPEC = {
    "name": "Probe",
    "config": [
        {"name": "RUN_LEFT", "type": "bool", "description": "x", "default": True}
    ],
    "jobs": {
        "left": {"uses": "selection_probe/alpha", "if": "RUN_LEFT"},
        "right": {"uses": "selection_probe/beta"},
    },
}


@pytest.fixture(scope="module")
def probe_job():
    """
    A job template with two providers writing one metric each, for the engine
    tests below.

    Module-scoped: ``Job.factory`` and ``JobRegistry`` are process-wide
    singletons, so registering the same ids once per test would raise on the
    second use.

    The metrics are declared on the *registrations* and not on the template. A
    template metric is written by every provider, so two jobs of one template
    would collide on it with no ``TOOLS`` entry at all and the document would
    never load -- which would test the check against a document, where what is
    wanted is a document that loads until a selection is made.
    """
    from librelane.jobs import Job, JobRegistry
    from librelane.steps import Step

    Job(
        id="selection_probe",
        full_name="Selection Probe",
        default_provider="alpha",
        requires=(),
        provides=(),
        metrics=(),
    ).register()

    class Base(Step):
        inputs = []
        outputs = []

    @Step.factory.register()
    class Alpha(Base):
        id = "Test.SelectionAlpha"

        def run(self, state_in, **kwargs):
            return {}, {"probe__alpha": 1}

    @Step.factory.register()
    class Beta(Base):
        id = "Test.SelectionBeta"

        def run(self, state_in, **kwargs):
            return {}, {"probe__beta": 1}

    for provider, step, metric in (
        ("alpha", Alpha, "probe__alpha"),
        ("beta", Beta, "probe__beta"),
    ):
        JobRegistry.register(
            job="selection_probe",
            provider=provider,
            steps=[step],
            namespaces=["SELECTION_PROBE_"],
            metrics=[metric],
        )


def test_the_replay_reports_the_final_state_join_under_its_own_name(probe_job):
    """
    A conflict where two leaves meet has no consumer job to name, because the
    implicit join that forms a flow's final state is not a job. Every shipped
    document has one sink and so cannot exercise it; the probe document has two
    and declares no ``final``.
    """
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_PROBE_SPEC)
    jobs = resolve_jobs(spec, {"left": "beta"})

    assert spec.final is None
    conflicts = join_conflicts(spec, jobs, set(jobs))
    assert [conflict.consumer for conflict in conflicts] == [SINK_JOIN]
    assert conflicts[0].key == "probe__beta"
    assert conflicts[0].origins == ("left", "right")


@mock_variables([flow_module, step_module])
def test_the_document_alone_still_loads(probe_job, minimal_design, mock_pdk):
    """
    The baseline the two tests below are measured against, and the thing that
    makes them about ``TOOLS`` rather than about a malformed document.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    workflow = Workflow(
        FlowSpec.model_validate(_PROBE_SPEC), minimal_design, **mock_pdk
    )

    assert sorted(workflow.jobs) == ["left", "right"]


@mock_variables([flow_module, step_module])
def test_constructing_a_workflow_refuses_a_fatal_selection(
    probe_job, minimal_design, mock_pdk
):
    """
    The wiring: the refusal happens while the flow is being constructed, not
    when it is run, so ``librelane`` stops before it has made a run directory.

    ``TOOLS`` is passed the way a design configuration passes it, through the
    same pre-pass ``Workflow._selected_tools`` runs, rather than by calling the
    validator directly -- which is the only way to show that the constructor
    reaches it at all.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    with pytest.raises(JobResolutionError) as refused:
        Workflow(
            FlowSpec.model_validate(_PROBE_SPEC),
            {**minimal_design, "TOOLS": {"left": "beta"}},
            **mock_pdk,
        )

    message = str(refused.value)
    assert "probe__beta" in message
    assert "'left'" in message
    assert "'right'" in message
    assert "set TOOLS['left'] to 'alpha'" in message


@mock_variables([flow_module, step_module])
def test_constructing_a_workflow_accepts_the_same_selection_gated_off(
    probe_job, minimal_design, mock_pdk
):
    """
    The gating half, through the engine rather than through the validator, so
    that what is pinned is that the constructor hands the check the *resolved*
    configuration's answer and not a set of every declared job.

    This is why the check runs after ``super().__init__``: before it, there is
    no configuration to ask, and a check that ran earlier would have to refuse
    this.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    workflow = Workflow(
        FlowSpec.model_validate(_PROBE_SPEC),
        {**minimal_design, "TOOLS": {"left": "beta"}, "RUN_LEFT": False},
        **mock_pdk,
    )

    assert workflow.jobs["left"].provider == "beta"
    assert workflow._enabled_jobs() == {"right"}
