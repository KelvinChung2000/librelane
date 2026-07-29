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
The LibreLane command line.

``librelane`` is one app with one subcommand per area, assembled in
:mod:`librelane.cli.main`:

===================== ==============================================
``librelane run``     :mod:`librelane.cli.run`
``librelane steps``   :mod:`librelane.cli.steps`
``librelane config``  :mod:`librelane.cli.config`
``librelane state``   :mod:`librelane.cli.state`
``librelane metrics`` :mod:`librelane.cli.metrics`
``librelane help``    :mod:`librelane.cli.help`
``librelane env-info`` :mod:`librelane.cli.env_info`
===================== ==============================================

``run`` is the default: ``librelane config.json`` and ``librelane run
config.json`` are the same command, which is what keeps every reproducible,
container re-entry and documented invocation working. See
:class:`librelane.cli._app.DefaultToRunGroup`.

The pre-subcommand console scripts (``librelane.steps`` and friends) survive as
deprecated aliases in :mod:`librelane.cli._deprecated`.

Supporting modules:

* :mod:`librelane.cli._app` -- the shared Typer configuration
* :mod:`librelane.cli.options` -- shared option declarations, no behaviour
* :mod:`librelane.cli.runtime` -- the behaviour behind those options

Nothing under ``librelane`` outside this package may import from it: the
dependency runs one way, so the library stays usable without a terminal.

This module is deliberately kept free of imports. Each console script pays
only for the frontend it actually runs.
"""
