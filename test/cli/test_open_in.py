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
``librelane open``, which replaced the five one-job ``OpenIn*`` documents.

What is pinned here is the half that used to be pinned in
``test/flows/test_documents.py``: that every viewer a user could reach is still
reachable, and that it still runs the step it says it does.
"""

import json
from pathlib import Path

import pytest
import typer

import librelane.steps  # noqa: F401  populates Step.factory

from librelane.cli.open_in import VIEWERS, ViewerName, resolve_run_dir, resolve_state
from librelane.state import State
from librelane.steps import Step

pytestmark = pytest.mark.all


def test_every_viewer_names_a_registered_step():
    """
    The table is the only registration, so a typo in it is a command that
    exists in ``--help`` and dies on use.
    """
    for name in ViewerName:
        assert Step.factory.get(VIEWERS[name].step_id) is not None, name


def test_the_table_covers_every_viewer_name():
    """
    :data:`ViewerName` is what Typer offers and :data:`VIEWERS` is what the
    command reads, so a member added to one and not the other is a choice the
    help advertises and a ``KeyError`` on use.
    """
    assert set(VIEWERS) == set(ViewerName)


def test_the_console_viewers_run_the_console_steps():
    """
    Issue 532: the interactive sessions stay reachable, and stay distinct from
    the GUI ones. This was ``test_the_console_documents_run_the_console_steps``
    against ``open_in_openroad_console.yaml`` and its OpenSTA sibling, and
    before that it read ``OpenInOpenROADConsole.Steps``.
    """
    assert VIEWERS[ViewerName.openroad_console].step_id == "OpenROAD.OpenConsole"
    assert VIEWERS[ViewerName.opensta_console].step_id == "OpenROAD.OpenSTAConsole"


def test_the_gui_viewers_run_the_gui_steps():
    assert VIEWERS[ViewerName.klayout].step_id == "KLayout.OpenGUI"
    assert VIEWERS[ViewerName.magic].step_id == "Magic.OpenGUI"
    assert VIEWERS[ViewerName.openroad].step_id == "OpenROAD.OpenGUI"


def test_no_viewer_declares_an_output():
    """
    The command discards whatever the step returns. A viewer that produced a
    view would need the run directory's ordering rules to record it, and this
    is the check that says none of them does.
    """
    for name in ViewerName:
        step = Step.factory.get(VIEWERS[name].step_id)
        assert step.outputs == [], name


def test_a_viewer_name_is_spelled_the_way_a_command_line_is():
    """
    The documents registered as ``OpenInOpenSTAConsole``, which was the Python
    class name. What a user types now is lowercase and dashed, like every other
    argument the CLI takes.
    """
    for name in ViewerName:
        assert name.value == name.value.lower()
        assert "_" not in name.value


class TestRunDirResolution:
    def _design(self, tmp_path: Path, *tags: str) -> Path:
        for tag in tags:
            (tmp_path / "runs" / tag).mkdir(parents=True)
        return tmp_path

    def test_a_named_tag_is_used(self, tmp_path: Path):
        design = self._design(tmp_path, "RUN_A", "RUN_B")

        assert resolve_run_dir(design, "RUN_A", False) == design / "runs" / "RUN_A"

    def test_last_run_picks_the_most_recent(self, tmp_path: Path):
        design = self._design(tmp_path, "RUN_OLD", "RUN_NEW")
        import os

        os.utime(design / "runs" / "RUN_OLD", (1, 1))

        assert resolve_run_dir(design, None, True) == design / "runs" / "RUN_NEW"

    def test_neither_option_is_refused(self, tmp_path: Path):
        """
        There is no default run. A viewer opened on nothing is a window a user
        has to close before finding out they mistyped, so the command says
        which runs exist instead.
        """
        design = self._design(tmp_path, "RUN_A")

        with pytest.raises(typer.Exit) as raised:
            resolve_run_dir(design, None, False)

        assert raised.value.exit_code == 1

    def test_an_unknown_tag_is_refused(self, tmp_path: Path):
        design = self._design(tmp_path, "RUN_A")

        with pytest.raises(typer.Exit) as raised:
            resolve_run_dir(design, "RUN_NOPE", False)

        assert raised.value.exit_code == 1

    def test_last_run_without_any_runs_is_refused(self, tmp_path: Path):
        with pytest.raises(typer.Exit) as raised:
            resolve_run_dir(tmp_path, None, True)

        assert raised.value.exit_code == 1


class TestStateResolution:
    def _state_file(self, directory: Path, name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(json.dumps({"metrics": {}}), encoding="utf8")
        return path

    def test_an_explicit_state_wins(self, tmp_path: Path):
        self._state_file(tmp_path / "01-step", "state_out.json")
        given = State()

        assert resolve_state(tmp_path, given) is given

    def test_the_latest_state_in_the_run_is_the_default(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """
        What makes the bare form open the design as the run left it, and the
        same file ``librelane state latest`` prints.

        The chosen path is read out of the log because that is the only place
        it surfaces; asserting merely that a State came back would pass just as
        well on the wrong one.
        """
        import os

        old = self._state_file(tmp_path / "01-first", "state_out.json")
        new = self._state_file(tmp_path / "02-second", "state_out.json")
        os.utime(old, (1, 1))

        assert isinstance(resolve_state(tmp_path, None), State)
        assert str(new) in caplog.text
        assert str(old) not in caplog.text

    def test_a_run_with_no_state_is_refused(self, tmp_path: Path):
        with pytest.raises(typer.Exit) as raised:
            resolve_state(tmp_path, None)

        assert raised.value.exit_code == 1
