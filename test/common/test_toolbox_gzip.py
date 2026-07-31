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
"""Liberty files may be shipped gzipped, and `remove_cells_from_lib` already
reads them that way. The other two liberty readers did not."""

import gzip
from decimal import Decimal

import pytest

pytestmark = pytest.mark.all


_LIB = """\
library (test) {
  default_operating_conditions : "tt_025C_1v80";
  operating_conditions ("tt_025C_1v80") {
    process : 1;
    temperature : 25;
    voltage : 1.8;
  }
  cell ("test_cell") {
    area : 1;
    pin ("A") {
      direction : input;
    }
    pin ("Y") {
      direction : output;
      function : "A";
    }
  }
}
"""


def _write(tmp_path, name, gzipped):
    path = tmp_path / name
    if gzipped:
        with gzip.open(path, "wt", encoding="utf8") as f:
            f.write(_LIB)
    else:
        path.write_text(_LIB)
    return str(path)


@pytest.mark.parametrize("gzipped", [False, True])
def test_get_lib_voltage_reads_plain_and_gzipped_libs(tmp_path, gzipped):
    from librelane.common.toolbox import Toolbox

    toolbox = Toolbox(str(tmp_path / "tmp"))
    lib = _write(tmp_path, "scl.lib.gz" if gzipped else "scl.lib", gzipped)

    assert toolbox.get_lib_voltage(lib) == Decimal("1.8")


@pytest.mark.parametrize("gzipped", [False, True])
def test_blackbox_models_from_plain_and_gzipped_libs(tmp_path, gzipped):
    from librelane.common.toolbox import Toolbox

    toolbox = Toolbox(str(tmp_path / "tmp"))
    lib = _write(tmp_path, "scl.lib.gz" if gzipped else "scl.lib", gzipped)

    out = toolbox.create_blackbox_model_from_libs(frozenset([lib]))

    assert "test_cell" in open(out, encoding="utf8").read()
