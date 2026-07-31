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
import runpy
import sys
from types import SimpleNamespace
from unittest import mock

import click
import pytest


SCRIPT = "librelane/scripts/odbpy/eco_replace_cell.py"


def fake_instance(name: str, master: str):
    """An ODB instance with just enough surface for the script."""
    instance = mock.Mock()
    instance.getName.return_value = name
    instance.getMaster.return_value = SimpleNamespace(getName=lambda: master)
    instance.getITerms.return_value = []
    instance.getPlacementStatus.return_value = "PLACED"

    def swap_master(replacement):
        instance.getMaster.return_value = SimpleNamespace(
            getName=lambda: replacement.name
        )
        return True

    instance.swapMaster.side_effect = swap_master
    return instance


def load_script(monkeypatch, instances, config, masters=("buf_1",)):
    """
    Runs the script with the OpenROAD-only modules stubbed out, and returns its
    ``cli`` callback and the fake reader it is meant to be called with.
    """
    monkeypatch.setitem(
        sys.modules,
        "reader",
        SimpleNamespace(click_odb=lambda function: function, click=click, odb=None),
    )
    monkeypatch.setitem(
        sys.modules, "grt", SimpleNamespace(IncrementalGRoute=mock.Mock())
    )

    reader = mock.Mock()
    reader.config = config
    reader.block.getInsts.return_value = instances
    reader.db.findMaster.side_effect = lambda name: (
        SimpleNamespace(name=name) if name in masters else None
    )
    reader.rows = [
        SimpleNamespace(
            getSite=lambda: SimpleNamespace(getWidth=lambda: 1, getHeight=lambda: 1)
        )
    ]
    reader.design.micronToDBU.side_effect = lambda value: int(value)

    module = runpy.run_path(SCRIPT)
    return module["cli"].callback, reader


BASE_CONFIG = {
    "PL_MAX_DISPLACEMENT_X": 5,
    "PL_MAX_DISPLACEMENT_Y": 5,
}


def test_replaces_every_instance_the_regex_matches(monkeypatch):
    instances = [
        fake_instance("fanout_0", "dlyb_1"),
        fake_instance("fanout_1", "dlyb_1"),
        fake_instance("other", "dlyb_1"),
    ]
    cli, reader = load_script(
        monkeypatch,
        instances,
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[{"instance": "^fanout.*", "replace_with": "buf_1"}],
        ),
    )

    cli(reader)

    assert [instance.getMaster().getName() for instance in instances] == [
        "buf_1",
        "buf_1",
        "dlyb_1",
    ]


def test_current_cell_narrows_the_match(monkeypatch):
    instances = [
        fake_instance("fanout_0", "dlyb_1"),
        fake_instance("fanout_1", "inv_2"),
    ]
    cli, reader = load_script(
        monkeypatch,
        instances,
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[
                {
                    "instance": "^fanout.*",
                    "current_cell": "dlyb_1",
                    "replace_with": "buf_1",
                }
            ],
        ),
    )

    cli(reader)

    assert [instance.getMaster().getName() for instance in instances] == [
        "buf_1",
        "inv_2",
    ]


def test_a_rule_that_matches_nothing_fails(monkeypatch):
    """An ECO that silently does nothing is worse than one that fails."""
    instances = [fake_instance("fanout_0", "dlyb_1")]
    cli, reader = load_script(
        monkeypatch,
        instances,
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[{"instance": "^nothing.*", "replace_with": "buf_1"}],
        ),
    )

    with pytest.raises(SystemExit):
        cli(reader)


def test_an_unknown_replacement_cell_fails(monkeypatch):
    instances = [fake_instance("fanout_0", "dlyb_1")]
    cli, reader = load_script(
        monkeypatch,
        instances,
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[
                {"instance": "^fanout.*", "replace_with": "nonexistent"}
            ],
        ),
    )

    with pytest.raises(SystemExit):
        cli(reader)


def test_an_incompatible_swap_fails(monkeypatch):
    """swapMaster returns False when the two cells' terminals differ."""
    instance = fake_instance("fanout_0", "dlyb_1")
    instance.swapMaster.side_effect = lambda replacement: False
    cli, reader = load_script(
        monkeypatch,
        [instance],
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[{"instance": "^fanout.*", "replace_with": "buf_1"}],
        ),
    )

    with pytest.raises(SystemExit):
        cli(reader)


def test_only_the_replacements_are_left_movable(monkeypatch):
    """Legalization has to move the resized cell, not re-place the design."""
    replaced = fake_instance("fanout_0", "dlyb_1")
    untouched = fake_instance("other", "dlyb_1")
    cli, reader = load_script(
        monkeypatch,
        [replaced, untouched],
        dict(
            BASE_CONFIG,
            REPLACE_ECO_CELLS=[{"instance": "^fanout.*", "replace_with": "buf_1"}],
        ),
    )

    cli(reader)

    assert not replaced.setPlacementStatus.called
    assert [call.args[0] for call in untouched.setPlacementStatus.call_args_list] == [
        "LOCKED",
        "PLACED",
    ]
