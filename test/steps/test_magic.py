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

pytestmark = pytest.mark.all


def test_write_lef_is_pinonly_by_default():
    """A LEF pin larger than the DEF pin fails downstream pin-size prechecks."""
    from librelane.steps.magic import WriteLEF

    assert WriteLEF.Config.model_fields["MAGIC_WRITE_LEF_PINONLY"].default is True
