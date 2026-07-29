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
The dotted console scripts that predate ``librelane``'s subcommands.

``librelane.steps``, ``librelane.config``, ``librelane.state``,
``librelane.help`` and ``librelane.env_info`` are now spelled as subcommands of
``librelane``. The old names keep working and print where to find the new one.

The equivalent ``python3 -m`` module invocations are deliberately silent: they
are machine-facing contracts. ``run_ol.sh`` inside every reproducible ever
generated calls ``python3 -m librelane.steps``, and warning on each of those
would be noise nobody can act on.
"""

import sys


def _announce(old: str, new: str) -> None:
    print(
        f"warning: `{old}` is deprecated and will be removed in a future "
        f"release. Use `{new}` instead.",
        file=sys.stderr,
    )


def steps() -> None:
    _announce("librelane.steps", "librelane steps")
    from .steps import cli

    cli()


def config() -> None:
    _announce("librelane.config", "librelane config")
    from .config import cli

    # The subcommand dropped the redundant `-config` suffix when it moved under
    # `librelane config`; the old spelling is translated rather than kept.
    if len(sys.argv) > 1 and sys.argv[1] == "create-config":
        sys.argv[1] = "create"

    cli()


def state() -> None:
    _announce("librelane.state", "librelane state")
    from .state import cli

    cli()


def help() -> None:
    _announce("librelane.help", "librelane help")
    from .help import cli

    cli()


def env_info() -> None:
    _announce("librelane.env_info", "librelane env-info")
    from .env_info import cli

    cli()


__all__ = ["steps", "config", "state", "help", "env_info"]
