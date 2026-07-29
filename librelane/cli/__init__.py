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
The LibreLane command-line frontends.

Every console script declared in ``[project.scripts]`` is defined in this
package, one module per frontend:

* :mod:`librelane.cli.main` -- ``librelane``
* :mod:`librelane.cli.steps` -- ``librelane.steps``
* :mod:`librelane.cli.config` -- ``librelane.config``
* :mod:`librelane.cli.state` -- ``librelane.state``
* :mod:`librelane.cli.help` -- ``librelane.help``
* :mod:`librelane.cli.env_info` -- ``librelane.env_info``
* :mod:`librelane.cli.metrics` -- ``python3 -m librelane.common.metrics``

Nothing under ``librelane`` outside this package may import from it: the
dependency runs one way, so the library stays usable without a terminal.

This module is deliberately kept free of imports. Each console script pays
only for the frontend it actually runs.
"""
