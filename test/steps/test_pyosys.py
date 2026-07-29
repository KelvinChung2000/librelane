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
import json
import os

import pytest

from librelane.steps import step

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _json_header(mock_config, mocker, macro_libs=(), extra_libs=None):
    from librelane.state import DesignFormat, State
    from librelane.steps.pyosys import JsonHeader

    instance = JsonHeader(config=mock_config, state_in=State())

    raw = instance.config.to_raw_dict()
    raw.setdefault("CELL_VERILOG_MODELS", None)
    raw.setdefault("PAD_VERILOG_MODELS", None)
    raw.setdefault("EXTRA_VERILOG_MODELS", None)
    raw.setdefault("LIB", {"*": ["/pdk/scl.lib"]})
    raw.setdefault("SYNTH_CORNER", None)
    raw.setdefault("EXTRA_EXCLUDED_CELLS", None)
    # process_list_file opens these unconditionally, so they must be real.
    with open("/cwd/excluded.txt", "w") as f:
        f.write("")
    raw.setdefault("SYNTH_EXCLUDED_CELL_FILE", "/cwd/excluded.txt")
    raw.setdefault("PNR_EXCLUDED_CELL_FILE", "/cwd/excluded.txt")
    raw["EXTRA_LIBS"] = extra_libs
    instance.config = type(instance.config).model_construct(**raw)

    instance.step_dir = "/cwd/jsonheader"
    os.makedirs(instance.step_dir, exist_ok=True)

    mocker.patch.object(instance, "toolbox", mocker.MagicMock())
    instance.toolbox.filter_views.return_value = ["/pdk/scl.lib"]
    instance.toolbox.get_macro_views_by_priority.return_value = [
        (lib, DesignFormat.LIB) for lib in macro_libs
    ]
    # The real method is lru_cache'd, so every caller gets this same object.
    instance.toolbox.remove_cells_from_lib.return_value = _SHARED_TRIMMED

    instance.get_command(State())

    with open(os.path.join(instance.step_dir, "extra.json")) as f:
        return json.load(f)


_SHARED_TRIMMED = ["/tmp/trimmed-scl.lib"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_macro_lib_views_reach_the_synthesis_lib_set(mock_config, mocker):
    """ABC and dfflibmap only ever saw the SCL, so macros had no area/timing."""
    extra = _json_header(mock_config, mocker, macro_libs=["/macros/sram.lib"])

    assert "/macros/sram.lib" in extra["libs_synth"]
    # Still a blackbox model as well -- the priority order is unchanged.
    assert "/macros/sram.lib" in extra["blackbox_models"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_extra_libs_reach_the_synthesis_lib_set(mock_config, mocker):
    extra = _json_header(mock_config, mocker, extra_libs=["/extra/pads.lib"])

    assert "/extra/pads.lib" in extra["libs_synth"]


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables([step])
def test_the_memoized_lib_list_is_not_mutated(mock_config, mocker):
    """remove_cells_from_lib is lru_cache'd; extending its result in place
    would leak one step's macros into every later step's lib set."""
    global _SHARED_TRIMMED
    _SHARED_TRIMMED = ["/tmp/trimmed-scl.lib"]

    _json_header(mock_config, mocker, macro_libs=["/macros/first.lib"])
    second = _json_header(mock_config, mocker, macro_libs=["/macros/second.lib"])

    assert _SHARED_TRIMMED == ["/tmp/trimmed-scl.lib"]
    assert "/macros/first.lib" not in second["libs_synth"]
