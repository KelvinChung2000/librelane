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
The ``librelane.env_info`` console script.

The implementation stays in :mod:`librelane.env_info` on purpose. That module
carries no third-party imports so it can survey an environment in which
LibreLane's dependencies failed to install, which is exactly the situation the
bug-report template asks users to run it in. This module only gives the
console script a home inside :mod:`librelane.cli`.
"""

from ..env_info import env_info_cli as cli


__all__ = ["cli"]
