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
Stages: the unit of tool substitution and independent gating.

See ``docs/source/usage/swapping_tools.md`` for user documentation and
``docs/source/usage/writing_tool_backends.md`` for the provider contract.
"""

from librelane.stages.stage import (
    Stage,
    StageError,
    StageContractError,
    StageResolutionError,
    PNR_IN_PLACE_REQUIRES,
    PNR_IN_PLACE_PROVIDES,
)
from librelane.stages.registry import Registration, StageRegistry
from librelane.stages import taxonomy as taxonomy  # noqa: F401  (registration side effects)
from librelane.stages.taxonomy import STAGE_ORDER
from librelane.stages import providers as providers  # noqa: F401  (registration side effects)
from librelane.stages.tools import extract_tools

__all__ = [
    "Stage",
    "Registration",
    "StageRegistry",
    "STAGE_ORDER",
    "extract_tools",
    "StageError",
    "StageContractError",
    "StageResolutionError",
    "PNR_IN_PLACE_REQUIRES",
    "PNR_IN_PLACE_PROVIDES",
]
