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

from librelane.flows import engine as engine_module, flow as flow_module
from librelane.steps import step as step_module
from test.conftest import COMMON_FLOW_VARS, MockConfTree

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _bool_var(name: str, default: bool) -> dict:
    return {
        "name": name,
        "type": "bool",
        "description": "x",
        "default": default,
    }


@mock_variables([flow_module, step_module])
def test_explain_names_the_condition_that_stops_a_job(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {"first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}},
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    first = explanation.jobs[0]
    assert first.job_id == "first"
    assert first.will_run is False
    assert first.mechanism == "condition"
    assert "RUN_FIRST" in first.reason


@mock_variables([flow_module, step_module])
def test_explain_marks_jobs_outside_the_target_subgraph(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(target=["first"])

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is True
    assert by_id["second"].mechanism == "not-in-target"
    assert by_id["second"].needs == ("first",)


@mock_variables([flow_module, step_module])
def test_explain_names_skip_as_the_mechanism_that_stopped_a_job(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``--skip`` and a false ``if`` both fire the job as pass-through, so the
    two are told apart by the mechanism and not by the outcome. A skipped job
    with a true condition would otherwise be indistinguishable from one whose
    condition happened to be false.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", True)],
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(skip=["first"])

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is False
    assert by_id["first"].mechanism == "skip"
    assert "--skip" in by_id["first"].reason
    # The skipped job still fires, so its successor is untouched. Nothing in
    # the graph is suppressed by a skip, only the job's own steps.
    assert by_id["second"].will_run is True
    assert by_id["second"].mechanism is None


@mock_variables([flow_module, step_module])
def test_explain_reports_a_row_for_every_job_the_document_declares(
    counting_steps, minimal_design, mock_pdk
):
    """
    The shape of the sample table in the workflow engine design document, job
    for job. Every declared job has a row, including the two that will not
    run: an explanation that reported only the jobs that will run could not
    answer the question the sample is there to answer, which is why a job the
    author expected is missing from the run.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Sample",
            "config": [
                _bool_var("RUN_KLAYOUT_STREAMOUT", False),
                _bool_var("RUN_KLAYOUT_XOR", False),
            ],
            "jobs": {
                "lint": {"steps": ["Test.EngineFirst"]},
                "synthesis": {"needs": ["lint"], "steps": ["Test.EngineSecond"]},
                "magic_streamout": {
                    "needs": ["synthesis"],
                    "steps": ["Test.EngineFirst"],
                },
                "klayout_streamout": {
                    "needs": ["magic_streamout"],
                    "steps": ["Test.EngineSecond"],
                    "if": "RUN_KLAYOUT_STREAMOUT",
                },
                "xor": {
                    "needs": ["magic_streamout", "klayout_streamout"],
                    "steps": ["Test.EngineFirst"],
                    "if": "RUN_KLAYOUT_XOR",
                },
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    rows = {
        d.job_id: (d.will_run, d.mechanism, d.needs, d.reason) for d in explanation.jobs
    }
    assert rows == {
        "lint": (True, None, (), "will run"),
        "synthesis": (True, None, ("lint",), "will run"),
        "magic_streamout": (True, None, ("synthesis",), "will run"),
        "klayout_streamout": (
            False,
            "condition",
            ("magic_streamout",),
            "'RUN_KLAYOUT_STREAMOUT' is false",
        ),
        "xor": (
            False,
            "condition",
            ("magic_streamout", "klayout_streamout"),
            "'RUN_KLAYOUT_XOR' is false",
        ),
    }


@mock_variables([flow_module, step_module])
def test_explain_orders_its_rows_topologically(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
                "first": {"steps": ["Test.EngineFirst"]},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain()

    assert [d.job_id for d in explanation.jobs] == ["first", "second"]


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_skip_that_the_target_already_excluded(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``run`` refuses the same pair, and an explanation that answered where the
    run would raise would be describing an invocation that cannot happen.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "jobs": {
                "first": {"steps": ["Test.EngineFirst"]},
                "second": {"needs": ["first"], "steps": ["Test.EngineSecond"]},
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="outside the --target subgraph"):
        flow.explain(target=["first"], skip=["second"])


@mock_variables([flow_module, step_module])
def test_explain_refuses_an_undeclared_job(counting_steps, minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="--target names 'nope'"):
        flow.explain(target=["nope"])


@mock_variables([flow_module, step_module])
def test_explain_suggests_a_near_miss_for_a_misspelled_job(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``TOOLS`` already suggests the job a typo was reaching for, and the two
    options name jobs from the same document: a suggestion for one spelling
    mistake and none for the other is an accident of where the check lives.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"synthesis": {"steps": ["Test.EngineFirst"]}}}
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="Did you mean: 'synthesis'\\?"):
        flow.explain(target=["syntheis"])


def _repro_spec() -> dict:
    """
    Returns
    -------
    dict
        Three chained jobs, the first of which runs two steps, so that a
        reproducible can be asked for at the head of a job's step list and in
        the middle of it and the two answers can be told apart.
    """
    return {
        "name": "Tiny",
        "jobs": {
            "first": {"steps": ["Test.EngineFirst", "Test.EngineSecond"]},
            "second": {"needs": ["first"], "steps": ["Test.EngineFirst"]},
            "third": {"needs": ["second"], "steps": ["Test.EngineSecond"]},
        },
    }


@mock_variables([flow_module, step_module])
def test_explain_restricts_the_graph_to_the_reproducible_s_subgraph(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``--reproducible`` runs the named step's job and its ancestors and stops,
    so every other job is out of the run. An explanation that reported them as
    running would be describing an invocation nobody can make.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(
        reproducible="second/Test.EngineFirst"
    )

    by_id = {d.job_id: d for d in explanation.jobs}
    assert by_id["first"].will_run is True
    assert by_id["first"].mechanism is None
    assert by_id["second"].mechanism == "reproducible"
    assert by_id["third"].will_run is False
    assert by_id["third"].mechanism == "not-in-reproducible"
    assert "second" in by_id["third"].reason


@mock_variables([flow_module, step_module])
def test_explain_reports_the_reproducible_s_own_job_stopping_at_the_step(
    counting_steps, minimal_design, mock_pdk
):
    """
    The named job runs the steps ahead of the named one and then writes the
    reproducible instead of running it, so it neither runs in full nor is
    excluded. Both facts are in the row.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(
        reproducible="first/Test.EngineSecond"
    )

    first = explanation.jobs[0]
    assert first.job_id == "first"
    # Its first step runs; the second is the one being packaged.
    assert first.will_run is True
    assert first.mechanism == "reproducible"
    assert "Test.EngineSecond" in first.reason


@mock_variables([flow_module, step_module])
def test_explain_reports_no_step_running_when_the_reproducible_is_the_first_step(
    counting_steps, minimal_design, mock_pdk
):
    """
    A reproducible for a job's first step packages that step and runs nothing
    of the job at all, which is a different answer from the row above.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(
        reproducible="first/Test.EngineFirst"
    )

    first = explanation.jobs[0]
    assert first.job_id == "first"
    assert first.will_run is False
    assert first.mechanism == "reproducible"
    assert "Test.EngineFirst" in first.reason


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_reproducible_alongside_a_target(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="both say what should run"):
        flow.explain(reproducible="first/Test.EngineFirst", target=["first"])


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_reproducible_for_a_skipped_job(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="it is named by --skip"):
        flow.explain(reproducible="first/Test.EngineFirst", skip=["first"])


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_reproducible_for_a_job_a_condition_stops(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "Tiny",
            "config": [_bool_var("RUN_FIRST", False)],
            "jobs": {"first": {"steps": ["Test.EngineFirst"], "if": "RUN_FIRST"}},
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="'RUN_FIRST' is false"):
        flow.explain(reproducible="first/Test.EngineFirst")


@mock_variables([flow_module, step_module])
def test_explain_refuses_a_reproducible_naming_a_step_no_job_runs(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="which flow 'Tiny' does not run"):
        flow.explain(reproducible="Test.NotAStep")


@mock_variables([flow_module, step_module])
def test_explain_refuses_an_undeclared_invalidate(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``run`` refuses the same typo, and an explanation that answered where the
    run would raise would be describing an invocation that cannot happen.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "Tiny", "jobs": {"first": {"steps": ["Test.EngineFirst"]}}}
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="--invalidate names 'nope'"):
        flow.explain(invalidate=["nope"])


@mock_variables([flow_module, step_module])
def test_explain_refuses_an_invalidate_outside_the_target_subgraph(
    counting_steps, minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    with pytest.raises(FlowException, match="outside the --target subgraph"):
        flow.explain(target=["first"], invalidate=["second"])


@mock_variables([flow_module, step_module])
def test_explain_leaves_every_row_alone_for_an_invalidate_it_accepts(
    counting_steps, minimal_design, mock_pdk
):
    """
    ``--invalidate`` says a cached result may not be reused, and reuse is the
    one verdict an explanation does not report. It is still refused when it
    names nothing, which is why it is a parameter at all.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(_repro_spec())
    flow = Workflow(spec, minimal_design, **mock_pdk)

    assert flow.explain(invalidate=["first"]).jobs == flow.explain().jobs


def _classic_workflow(mock_conf_dir: MockConfTree):
    """
    The shipped ``classic.yaml`` bound to a stock configuration.

    Built here rather than from the ``mock_config`` fixture because that
    fixture resolves against pyfakefs, and a test that constructs a
    ``Workflow`` may not use pyfakefs at all: the engine runs its jobs on a
    thread pool and pyfakefs is single-threaded by design.

    Parameters
    ----------
    mock_conf_dir : MockConfTree
        The real-filesystem mock tree.

    Returns
    -------
    librelane.flows.engine.Workflow
        The Classic document, configured with every declared variable at its
        default.
    """
    from librelane.config import Config
    from librelane.flows import Flow
    from librelane.flows.engine import Workflow

    base, _ = Config.load(
        {"DESIGN_NAME": "whatever", "VERILOG_FILES": "dir::src/*.v"},
        COMMON_FLOW_VARS,
        design_dir=mock_conf_dir.cwd,
        pdk="dummy",
        scl="dummy_scl",
        pdk_root=mock_conf_dir.pdk_root,
    )
    spec = Flow.factory.get("Classic")
    # The engine's own variables ahead of the document's, exactly as
    # Workflow.__init__ composes the two: TOOLS is the whole of the engine's
    # half and no document declares it.
    declared = [
        *Workflow.config_vars,
        *(entry.to_variable() for entry in spec.config),
    ]
    defaults = {variable.name: variable.default for variable in declared}
    return Workflow(spec, base.copy(**defaults))


@mock_variables([flow_module, step_module])
def test_explain_reports_every_job_of_the_classic_document(mock_conf_dir):
    """
    The no-suppression guard, on a real 48-job document rather than a
    hand-built pair. A row per declared job is what makes the table answer
    "why is this job not in my run", and the tests above could all pass while
    a filter quietly dropped the jobs a user is looking for.
    """
    from librelane.flows import Flow

    spec = Flow.factory.get("Classic")
    explanation = _classic_workflow(mock_conf_dir).explain()

    # Sorted, not in document order: the rows are topologically ordered, which
    # test_explain_orders_its_rows_topologically pins. What is asserted here is
    # that no job is missing and none is reported twice.
    assert sorted(d.job_id for d in explanation.jobs) == sorted(spec.jobs)
    gated = {d.job_id: d for d in explanation.jobs if d.mechanism == "condition"}
    assert gated, "a stock Classic configuration leaves RUN_RMP and RUN_EQY off"
    assert all(d.will_run is False for d in gated.values())


@mock_variables([flow_module, step_module])
def test_explain_keeps_every_row_when_a_target_narrows_the_classic_document(
    mock_conf_dir,
):
    """
    ``--target`` narrows what runs and not what is reported. A job it excluded
    is exactly the job someone is about to ask after.

    ``--skip`` is passed with it, naming a job inside the subgraph, because
    that pair is legal and the only committed coverage of the two together was
    the refusal. The rows are counted rather than only keyed by job id: a
    duplicated row collapses into a dictionary without a trace.
    """
    from librelane.flows import Flow

    spec = Flow.factory.get("Classic")
    explanation = _classic_workflow(mock_conf_dir).explain(
        target=["floorplan"], skip=["lint"]
    )

    assert len(explanation.jobs) == len(spec.jobs)
    by_id = {d.job_id: d for d in explanation.jobs}
    assert set(by_id) == set(spec.jobs)
    assert by_id["floorplan"].will_run is True
    assert by_id["lint"].will_run is False
    assert by_id["lint"].mechanism == "skip"
    assert by_id["final_checks"].mechanism == "not-in-target"


def _pnr_jobs() -> dict:
    """
    Returns
    -------
    dict
        Three chained jobs over real shipped steps: Yosys synthesis, the
        OpenROAD floorplan and OpenROAD global placement.

        Real jobs rather than registered test doubles, because a variable's
        reach is a fact about what the shipped step classes declare and about
        where in their hierarchy they declare it. A document of test steps
        would pin only what the test itself wrote down.
    """
    return {
        "synthesis": {"uses": "synthesis/yosys"},
        "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
        "global_placement": {"needs": ["floorplan"], "uses": "global_placement"},
    }


def _rows(explanation, name: str) -> list:
    """
    Parameters
    ----------
    explanation : librelane.flows.Explanation
        What the workflow reported.
    name : str
        The variable to look up.

    Returns
    -------
    list[librelane.flows.VariableDisposition]
        Every row for that variable. More than one only when the document's
        jobs resolved it differently, which is the case a single row cannot
        report.
    """
    return [row for row in explanation.variables if row.name == name]


def _row(explanation, name: str):
    """
    Returns
    -------
    librelane.flows.VariableDisposition
        The single row for ``name``.
    """
    rows = _rows(explanation, name)
    assert len(rows) == 1, f"expected one row for '{name}', got {rows}"
    return rows[0]


@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_a_universal_variable_as_reaching_everything(
    minimal_design, mock_pdk
):
    """
    DIODE_ON_PORTS stands in for DIE_AREA here. mock_variables replaces the
    universal variable list with test/conftest.py's COMMON_FLOW_VARS, which
    contains DIODE_ON_PORTS and not DIE_AREA, and the property under test is
    membership of that list rather than the identity of the variable.

    engine_module is in the list because the reader is in engine.py.
    mock_variables patches only the modules it is handed, so without it
    engine.py keeps the real list and this assertion fails.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    variable = _row(explanation, "DIODE_ON_PORTS")

    assert variable.universal
    assert set(variable.reach) == {job.job_id for job in explanation.jobs}


@mock_variables([flow_module, engine_module, step_module])
def test_explain_scopes_a_step_variable_to_the_jobs_that_read_it(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    strategy = _row(explanation, "SYNTH_STRATEGY")

    assert not strategy.universal
    assert strategy.reach == ("synthesis",)


@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_a_variable_read_by_several_jobs(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    util = _row(explanation, "FP_CORE_UTIL")

    assert not util.universal
    assert set(util.reach) == {"floorplan", "global_placement"}


@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_the_class_that_declares_an_inherited_variable(
    minimal_design, mock_pdk
):
    """
    OPENROAD_THREADS is declared once, on OpenROADStep, and inherited by every
    OpenROAD step below it. Naming the family is the same fact as listing its
    members and is the one a reader can act on.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    threads = _row(explanation, "OPENROAD_THREADS")

    assert threads.declared_by == "OpenROADStep"
    assert set(threads.reach) == {"floorplan", "global_placement"}


@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_a_declaring_class_by_its_step_id_when_it_has_one(
    minimal_design, mock_pdk
):
    """
    OpenROADStep above is abstract and so has no step ID to be named by. A
    concrete step does, and its ID is what a reader recognises: two step
    classes may share a Python name, and no two share an ID.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)

    assert _row(explanation, "FP_SIZING").declared_by == "OpenROAD.Floorplan"


@mock_variables([flow_module, engine_module, step_module])
def test_a_variable_two_classes_declare_separately_has_no_declaring_class(
    minimal_design, mock_pdk
):
    """
    FP_CORE_UTIL is declared by the floorplan step and, independently, by the
    global placement step: neither inherits it from the other. There is no one
    class to name, so the jobs are the whole answer.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)

    assert _row(explanation, "FP_CORE_UTIL").declared_by is None


@mock_variables([flow_module, engine_module, step_module])
def test_a_variable_no_step_declares_reaches_no_job(minimal_design, mock_pdk):
    """
    TOOLS is declared by the engine and read by it, before any job exists. An
    empty reach is the honest answer and not a missing one, and a row that
    claimed otherwise would say a job could change the provider selection from
    its own 'with' block.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    tools = _row(explanation, "TOOLS")

    assert not tools.universal
    assert tools.reach == ()
    assert tools.declared_by is None


@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_the_document_as_the_origin_of_a_document_value(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "T", "with": {"FP_SIZING": "absolute"}, "jobs": _pnr_jobs()}
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    sizing = _row(explanation, "FP_SIZING")

    assert sizing.value == "absolute"
    assert sizing.origin == "<flow document>"


@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_the_design_as_the_origin_of_a_design_value(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(
        spec, dict(minimal_design, FP_SIZING="absolute"), **mock_pdk
    ).explain(variables=True)

    assert _row(explanation, "FP_SIZING").origin == "<mapping>"


@mock_variables([flow_module, engine_module, step_module])
def test_explain_names_the_command_line_as_the_origin_of_an_override(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {"name": "T", "with": {"FP_SIZING": "absolute"}, "jobs": _pnr_jobs()}
    )

    explanation = Workflow(
        spec,
        minimal_design,
        config_override_strings=["FP_SIZING=relative"],
        **mock_pdk,
    ).explain(variables=True)

    assert _row(explanation, "FP_SIZING").origin == "<command line>"


@mock_variables([flow_module, engine_module, step_module])
def test_a_variable_no_source_wrote_reports_default_as_its_origin(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)

    assert _row(explanation, "FP_SIZING").origin == "default"


@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_both_values_when_two_jobs_set_a_variable_differently(
    minimal_design, mock_pdk
):
    """
    The case the per-job 'with' exists for, and the one a single row cannot
    answer. Reading the flow's own configuration would report one value for a
    variable that demonstrably has two, and would name whichever of the two
    jobs the reader was not asking about.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "T",
            "jobs": {
                "synth_area": {
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "AREA 0"},
                },
                "synth_delay": {
                    "needs": ["synth_area"],
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "DELAY 0"},
                },
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)

    assert {
        (row.value, row.origin, row.reach)
        for row in _rows(explanation, "SYNTH_STRATEGY")
    } == {
        ("AREA 0", "<flow document: synth_area>", ("synth_area",)),
        ("DELAY 0", "<flow document: synth_delay>", ("synth_delay",)),
    }


@mock_variables([flow_module, engine_module, step_module])
def test_a_job_with_block_does_not_reattribute_a_document_value(
    minimal_design, mock_pdk
):
    """
    The document's own 'with' and a job's are two layers, not one. A job that
    sets some other variable must not make every value the document supplied
    read as though that job had supplied it, which is what merging the two
    into a single source named for the job would do.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "T",
            "with": {"DIODE_ON_PORTS": "in"},
            "jobs": {
                "synthesis": {
                    "uses": "synthesis/yosys",
                    "with": {"SYNTH_STRATEGY": "DELAY 0"},
                },
                "floorplan": {"needs": ["synthesis"], "uses": "floorplan"},
            },
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    diodes = _row(explanation, "DIODE_ON_PORTS")

    assert diodes.value == "in"
    assert diodes.origin == "<flow document>"


@mock_variables([flow_module, engine_module, step_module])
def test_explain_reports_a_row_for_every_configuration_variable(
    minimal_design, mock_pdk
):
    """
    The no-suppression guard for the variables table, matching the one the job
    table has. A variable sitting at its default is exactly what somebody
    debugging an unexpected value is looking for, and the sample output in the
    workflow engine design document uses a default row to demonstrate the
    'default' origin.
    """
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate({"name": "T", "jobs": _pnr_jobs()})
    workflow = Workflow(spec, minimal_design, **mock_pdk)

    explanation = workflow.explain(variables=True)

    assert {row.name for row in explanation.variables} == {
        variable.name for variable in workflow.get_all_config_variables()
    }
    assert any(row.origin == "default" for row in explanation.variables)


def _variables(*rows):
    from librelane.flows import Explanation

    return Explanation(variables=rows)


def test_format_variable_explanation_renders_every_row():
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition(
                "FP_CORE_UTIL", 40, "<mapping>", False, ("floorplan",), None
            ),
            VariableDisposition(
                "CTS_SINK_CLUSTERING_SIZE", 16, "default", False, ("cts",), None
            ),
        )
    )

    assert "VARIABLE" in rendered
    assert "FP_CORE_UTIL" in rendered
    assert "<mapping>" in rendered
    # A row at its default is kept, not filtered out: it is the row that
    # answers "why is this not the value I set".
    assert "CTS_SINK_CLUSTERING_SIZE" in rendered
    assert "default" in rendered


def test_format_variable_explanation_rolls_a_universal_variable_up():
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition(
                "DIE_AREA",
                "0 0 550 550",
                "<flow document>",
                True,
                tuple(f"job{n}" for n in range(24)),
                None,
            )
        )
    )

    assert "universal, read by all 24 jobs" in rendered
    assert "job0" not in rendered


def test_format_variable_explanation_rolls_up_by_declaring_class():
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition(
                "OPENROAD_THREADS",
                None,
                "default",
                False,
                tuple(f"job{n}" for n in range(31)),
                "OpenROADStep",
            )
        )
    )

    assert "read by all 31 OpenROADStep-based jobs" in rendered
    assert "job0" not in rendered


def test_format_variable_explanation_names_the_jobs_of_a_short_reach():
    """
    A roll-up replaces a list that is too long to read. Two job names are not,
    and naming them is strictly more information than naming their class.
    """
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition(
                "PNR_SDC_FILE",
                None,
                "default",
                False,
                ("floorplan", "global_placement"),
                "OpenROADStep",
            )
        )
    )

    assert "floorplan, global_placement" in rendered
    assert "OpenROADStep" not in rendered


def test_format_variable_explanation_says_when_no_job_reads_a_variable():
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(VariableDisposition("RUN_CTS", True, "default", False, (), None))
    )

    assert "the flow itself" in rendered


def test_format_variable_explanation_truncates_a_value_that_would_set_the_width():
    """
    A handful of PDK variables hold nested tables thousands of characters
    long, and one of them would otherwise set the value column's width for
    every other row in the table.
    """
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition(
                "LAYERS_RC", "x" * 4000, "<pdk>", False, ("cts",), None
            ),
            VariableDisposition(
                "FP_SIZING", "relative", "default", False, ("fp",), None
            ),
        )
    )

    assert "…" in rendered
    assert max(len(line) for line in rendered.split("\n")) < 120
    # Truncating the one row must not cost the others their alignment.
    assert "FP_SIZING" in rendered
    assert "relative" in rendered


def test_format_variable_explanation_does_not_say_all_1_jobs():
    from librelane.cli.run import format_variable_explanation
    from librelane.flows import VariableDisposition

    rendered = format_variable_explanation(
        _variables(
            VariableDisposition("DIE_AREA", None, "default", True, ("only",), None)
        )
    )

    assert "universal, read by the only job" in rendered
    assert "all 1 jobs" not in rendered


@mock_variables([flow_module, engine_module, step_module])
def test_the_rendered_table_reports_what_the_engine_resolved(minimal_design, mock_pdk):
    """
    The seam between the two halves. Both are covered on their own -- the
    engine's rows against real steps, the renderer's columns against
    hand-built rows -- and neither notices if the field the renderer reads
    stops being the field the engine fills.
    """
    from librelane.cli.run import format_variable_explanation
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec

    spec = FlowSpec.model_validate(
        {
            "name": "T",
            "with": {"FP_SIZING": "absolute"},
            "jobs": _pnr_jobs(),
        }
    )

    explanation = Workflow(spec, minimal_design, **mock_pdk).explain(variables=True)
    rendered = format_variable_explanation(explanation)
    rows = {line.split("  ")[0].strip(): line for line in rendered.split("\n")}

    assert "VARIABLE" in rows
    # The value, the origin and the reach the engine resolved, in the row the
    # renderer produced for them.
    assert "absolute" in rows["FP_SIZING"]
    assert "<flow document>" in rows["FP_SIZING"]
    assert "floorplan" in rows["FP_SIZING"]
    assert "universal, read by all 3 jobs" in rows["DIODE_ON_PORTS"]
    assert "the flow itself" in rows["TOOLS"]
    # Every variable the engine reported has a row: the renderer filters
    # nothing, defaults included.
    assert len(rows) == len(explanation.variables) + 1
