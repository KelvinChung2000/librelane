import json
import pathlib

import pytest

from librelane.common import Fingerprinter
from librelane.config import Variable
from librelane.flows import flow
from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


@pytest.fixture
def KeyStep():
    from librelane.common import Path
    from librelane.state import DesignFormat, State
    from librelane.steps import Step

    class KeyStep(Step):
        id = "Test.KeyStep"
        inputs = []
        outputs = [DesignFormat.JSON_HEADER]
        config_vars = [
            Variable("DUMMY_VARIABLE", type=str, description="x"),
        ]

        def run(self, state_in: State, **kwargs):
            out_file = pathlib.Path(self.step_dir) / "whatever.json"
            out_file.write_text("{}")
            return {DesignFormat.JSON_HEADER: Path(out_file)}, {}

    return KeyStep


def _make_step(KeyStep, overrides=None):
    from librelane.config import Config
    from librelane.state import State

    cfg, _ = Config.load(
        {
            "DESIGN_NAME": "WHATEVER",
            "DUMMY_VARIABLE": "PINGAS",
            "VERILOG_FILES": ["/cwd/src/a.v"],
            **(overrides or {}),
        },
        KeyStep.get_all_config_variables(),
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )

    return KeyStep(config=cfg, state_in=State())


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_the_same_step_and_state_give_the_same_key(KeyStep):
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    first = resume_key(_make_step(KeyStep), State(), fingerprinter)
    second = resume_key(_make_step(KeyStep), State(), fingerprinter)

    assert first == second


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_config_value_changes_the_key(KeyStep):
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    before = resume_key(_make_step(KeyStep), State(), fingerprinter)
    after = resume_key(
        _make_step(KeyStep, {"DUMMY_VARIABLE": "DIFFERENT"}), State(), fingerprinter
    )

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_an_edited_input_file_changes_the_key_though_paths_are_identical(KeyStep):
    """
    The case a path-equality design gets wrong. VERILOG_FILES still names
    exactly /cwd/src/a.v; only its contents moved.
    """
    from librelane.flows.resume import resume_key
    from librelane.state import State

    pathlib.Path("/cwd/src/a.v").write_text("module top(); endmodule")
    before = resume_key(_make_step(KeyStep), State(), Fingerprinter())

    pathlib.Path("/cwd/src/a.v").write_text("module top(); wire w; endmodule")
    after = resume_key(_make_step(KeyStep), State(), Fingerprinter())

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_changed_input_metric_changes_the_key(KeyStep):
    """Checker steps read state_in.metrics, so metrics are part of the key."""
    from librelane.flows.resume import resume_key
    from librelane.state import State

    fingerprinter = Fingerprinter()
    before = resume_key(
        _make_step(KeyStep), State(metrics={"design__area": 1}), fingerprinter
    )
    after = resume_key(
        _make_step(KeyStep), State(metrics={"design__area": 2}), fingerprinter
    )

    assert before != after


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_a_path_is_not_walked_as_a_sequence(KeyStep):
    """
    Path subclasses UserString, so a sequence branch reached before the Path
    branch would fingerprint a path character by character. Two different
    paths with identical contents must collide; per-character walking would
    make them differ.
    """
    from librelane.common import Path
    from librelane.flows.resume import _substitute_paths

    fingerprinter = Fingerprinter()
    pathlib.Path("/cwd/src/a.v").write_text("same")
    pathlib.Path("/cwd/src/b.v").write_text("same")

    assert _substitute_paths(Path("/cwd/src/a.v"), fingerprinter) == _substitute_paths(
        Path("/cwd/src/b.v"), fingerprinter
    )
    assert isinstance(_substitute_paths(Path("/cwd/src/a.v"), fingerprinter), str)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([flow, step])
def test_paths_inside_a_dataclass_are_fingerprinted():
    """
    MACROS is dict[str, Macro] and Macro is a dataclass of Path lists. A walk
    that skips dataclasses would let a macro's GDS change go unnoticed.
    """
    from librelane.common import Path
    from librelane.config.legacy import Macro
    from librelane.flows.resume import _substitute_paths

    pathlib.Path("/cwd/src/m.gds").write_text("gds-one")
    pathlib.Path("/cwd/src/m.lef").write_text("lef")
    macro = Macro(gds=[Path("/cwd/src/m.gds")], lef=[Path("/cwd/src/m.lef")])

    before = _substitute_paths({"m": macro}, Fingerprinter())
    pathlib.Path("/cwd/src/m.gds").write_text("gds-two")
    after = _substitute_paths({"m": macro}, Fingerprinter())

    assert before != after


def test_a_missing_entry_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    assert reusable_state(tmp_path, "any-key", Fingerprinter()) is None


def test_a_mismatched_key_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps(
            {"schema": 1, "key": "recorded", "step": "X", "librelane_version": "0"}
        )
    )
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {}}))

    assert reusable_state(tmp_path, "different", Fingerprinter()) is None


def test_a_truncated_entry_is_a_miss_not_an_error(tmp_path):
    """kill -9 mid-write is expected. It means miss, not crash."""
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text('{"schema": 1, "key": "reco')

    assert reusable_state(tmp_path, "recorded", Fingerprinter()) is None


def test_a_future_schema_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 99, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {}}))

    assert reusable_state(tmp_path, "k", Fingerprinter()) is None


def test_a_deleted_output_view_is_a_miss(tmp_path):
    from librelane.flows.resume import reusable_state

    view = tmp_path / "out.json"
    view.write_text("{}")
    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 1, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(
        json.dumps({"json_h": str(view), "metrics": {}})
    )
    assert reusable_state(tmp_path, "k", Fingerprinter()) is not None

    view.unlink()

    assert reusable_state(tmp_path, "k", Fingerprinter()) is None


def test_a_matching_entry_returns_the_output_state(tmp_path):
    from librelane.flows.resume import reusable_state

    (tmp_path / "resume.json").write_text(
        json.dumps({"schema": 1, "key": "k", "step": "X", "librelane_version": "0"})
    )
    (tmp_path / "state_out.json").write_text(
        json.dumps({"metrics": {"design__area": 5}})
    )

    state = reusable_state(tmp_path, "k", Fingerprinter())

    assert state is not None
    assert state.metrics["design__area"] == 5
