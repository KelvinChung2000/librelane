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
Stages: the unit of tool substitution, independent gating and flow re-entry.

See ``docs/source/usage/swapping_tools.md`` for user documentation and
``docs/source/usage/writing_tool_backends.md`` for the provider contract.
"""

from .stage import (
    Stage,
    StageError,
    StageContractError,
    StageResolutionError,
    PNR_IN_PLACE_REQUIRES,
    PNR_IN_PLACE_PROVIDES,
)
from .registry import Registration, StageRegistry

__all__ = [
    "Stage",
    "Registration",
    "StageRegistry",
    "StageError",
    "StageContractError",
    "StageResolutionError",
    "PNR_IN_PLACE_REQUIRES",
    "PNR_IN_PLACE_PROVIDES",
]
