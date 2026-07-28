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
from pathlib import Path
from typing import cast

import pytest
import typer

from librelane.common.metrics.__main__ import parse_table_verbosity
from librelane.common.metrics.util import TableVerbosity
from librelane.steps import __main__ as steps_cli


pytestmark = pytest.mark.all


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("none", TableVerbosity.NONE),
        ("ALL", TableVerbosity.ALL),
        ("2", TableVerbosity.WORSE),
    ],
)
def test_parse_table_verbosity(value: str, expected: TableVerbosity):
    assert parse_table_verbosity(value) is expected


def test_create_reproducible_uses_explicit_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = tmp_path / "config.json"
    state_in = tmp_path / "state_in.json"
    output = tmp_path / "reproducible"
    calls = {}

    class FakeStep:
        def create_reproducible(self, output, include_pdk, *, flatten):
            calls["create"] = (output, include_pdk, flatten)

    def fake_load(ctx, id, config, state_in, pdk_root=None):
        calls["load"] = (config, state_in)
        return FakeStep()

    monkeypatch.setattr(steps_cli, "load_step_from_inputs", fake_load)

    steps_cli.create_reproducible(
        ctx=cast(typer.Context, None),
        step_dir_arg=None,
        output=output,
        step_dir=None,
        id=None,
        config=config,
        state_in=state_in,
        include_pdk=False,
        flatten=True,
    )

    assert calls["load"] == (config, state_in)
    assert calls["create"] == (output, False, True)
