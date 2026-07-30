# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane 2
#
# Copyright 2023 Efabless Corporation
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
Every command-line option shared by more than one LibreLane frontend.

This module is pure declaration: it names options, documents them and sorts
them into help panels, and does nothing else. The behaviour behind them lives
in :mod:`librelane.cli.runtime`.

Keeping the two apart means importing an option costs nothing but Typer, so a
``--help`` never pays for loading flows, steps or the PDK machinery.
"""

from pathlib import Path
from typing import Annotated

import typer


FLOW_OPTIONS = "Flow configuration options"
RUN_OPTIONS = "Run options"
SEQUENTIAL_OPTIONS = "Sequential flow controls"
PDK_OPTIONS = "PDK options"
DISPLAY_OPTIONS = "Logging and display options"
COPY_OPTIONS = "Copy final views"
CONTAINER_OPTIONS = "Containerization options"
ACTION_OPTIONS = "Actions"
DEBUG_OPTIONS = "Debug options"


ConfigFilesArgument = Annotated[
    list[Path] | None,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        help="One or more LibreLane configuration files.",
    ),
]
FlowNameOption = Annotated[
    str | None,
    typer.Option(
        "--flow",
        "-f",
        help="The built-in LibreLane flow to use for this run.",
        rich_help_panel=FLOW_OPTIONS,
    ),
]
ConfigOverridesOption = Annotated[
    list[str] | None,
    typer.Option(
        "--override-config",
        "-c",
        help=(
            "Override a configuration variable for this run, in KEY=VALUE "
            "format. May be specified multiple times; values must be valid JSON."
        ),
        rich_help_panel=FLOW_OPTIONS,
    ),
]
InitialStateFilesOption = Annotated[
    list[Path] | None,
    typer.Option(
        "--with-initial-state",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help=(
            "Use these JSON files as an initial state. Multiple files are merged "
            "in order, with later keys overriding earlier keys."
        ),
        rich_help_panel=RUN_OPTIONS,
    ),
]
InitialStateElementOption = Annotated[
    list[str] | None,
    typer.Option(
        "--initial-state-element-override",
        "-e",
        help=(
            "Override an initial-state element in DESIGN_FORMAT_ID=PATH format. "
            "May be specified multiple times."
        ),
        rich_help_panel=RUN_OPTIONS,
    ),
]
DesignDirOption = Annotated[
    Path | None,
    typer.Option(
        "--design-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help=(
            "The top-level design directory that configuration paths may resolve "
            "relative to."
        ),
        rich_help_panel=RUN_OPTIONS,
    ),
]
RunTagOption = Annotated[
    str | None,
    typer.Option(
        "--run-tag",
        help="An optional name for this flow run.",
        rich_help_panel=RUN_OPTIONS,
    ),
]
LastRunOption = Annotated[
    bool,
    typer.Option(
        "--last-run",
        help="Use the last run as the run tag.",
        rich_help_panel=RUN_OPTIONS,
    ),
]
OverwriteOption = Annotated[
    bool,
    typer.Option(
        "--overwrite",
        help="Overwrite the run if it already exists.",
        rich_help_panel=RUN_OPTIONS,
    ),
]
JobsOption = Annotated[
    int,
    typer.Option(
        "--jobs",
        "-j",
        min=1,
        help="The maximum number of threads or processes LibreLane may use.",
        rich_help_panel=RUN_OPTIONS,
    ),
]
FromOption = Annotated[
    str | None,
    typer.Option(
        "--from",
        "-F",
        help="Force re-execution from this step ID onward, ignoring any reusable result for it and the steps after it. Earlier steps are taken from their previous results, and it is an error if one of them has none. Supported by sequential flows.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
ToOption = Annotated[
    str | None,
    typer.Option(
        "--to",
        "-T",
        help="Stop at this step ID. Supported by sequential flows.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
ExplainOption = Annotated[
    bool,
    typer.Option(
        "--explain",
        help="Print which steps this configuration would run, and why each of the rest would not, then exit without running. Requires a sequential flow.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
SkipOption = Annotated[
    list[str] | None,
    typer.Option(
        "--skip",
        "-S",
        help="Skip this step ID. May be specified multiple times.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
ReproducibleOption = Annotated[
    str | None,
    typer.Option(
        "--reproducible",
        help="Create a reproducible for this step ID, then abort the flow.",
        rich_help_panel=SEQUENTIAL_OPTIONS,
    ),
]
LogLevelOption = Annotated[
    str | None,
    typer.Option(
        "--log-level",
        metavar="LEVEL",
        help=(
            "Logging level name or number. VERBOSE and higher silence subprocess "
            "logs. [default: unchanged from SUBPROCESS]"
        ),
        rich_help_panel=DISPLAY_OPTIONS,
    ),
]
ShowProgressBarOption = Annotated[
    bool | None,
    typer.Option(
        "--show-progress-bar/--hide-progress-bar",
        help="Whether to show the progress bar while running flows.",
        rich_help_panel=DISPLAY_OPTIONS,
    ),
]
CondensedOption = Annotated[
    bool,
    typer.Option(
        "--condensed/--full",
        help=(
            "Use terse log messages, suppress subprocess logs, and hide the "
            "progress bar by default."
        ),
        rich_help_panel=DISPLAY_OPTIONS,
    ),
]
UseCielOption = Annotated[
    bool,
    typer.Option(
        "--volare-pdk/--manual-pdk",
        "--ciel-pdk/--manual-pdk",
        help="Automatically install and enable the requested PDK with Ciel.",
        rich_help_panel=PDK_OPTIONS,
    ),
]
PdkRootOption = Annotated[
    Path | None,
    typer.Option(
        "--pdk-root",
        envvar="PDK_ROOT",
        file_okay=False,
        dir_okay=True,
        help="Override the Ciel PDK root directory.",
        rich_help_panel=PDK_OPTIONS,
    ),
]
PdkOption = Annotated[
    str,
    typer.Option(
        "--pdk",
        "-p",
        envvar="PDK",
        help="The process design kit to use.",
        rich_help_panel=PDK_OPTIONS,
    ),
]
SclOption = Annotated[
    str | None,
    typer.Option(
        "--scl",
        "-s",
        envvar="STD_CELL_LIBRARY",
        help="The standard cell library to use.",
        rich_help_panel=PDK_OPTIONS,
    ),
]
PadOption = Annotated[
    str | None,
    typer.Option(
        "--pad",
        envvar="PAD_CELL_LIBRARY",
        help="The standard pad library to use.",
        rich_help_panel=PDK_OPTIONS,
    ),
]
SaveViewsOption = Annotated[
    Path | None,
    typer.Option(
        "--save-views-to",
        file_okay=False,
        dir_okay=True,
        help="Copy final views here, with each format stored under its corner ID.",
        rich_help_panel=COPY_OPTIONS,
    ),
]
EfSaveViewsOption = Annotated[
    Path | None,
    typer.Option(
        "--ef-save-views-to",
        file_okay=False,
        dir_okay=True,
        help="Copy final views here in the Efabless Caravel-compatible format.",
        rich_help_panel=COPY_OPTIONS,
    ),
]
ContainerMountsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--docker-mount",
        "--container-mount",
        "-m",
        help=(
            "Mount an additional directory or pass a mount specification to the "
            "container engine. May be specified multiple times."
        ),
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
ContainerTtyOption = Annotated[
    bool,
    typer.Option(
        "--docker-tty/--docker-no-tty",
        "--container-tty/--container-no-tty",
        help="Control virtual-terminal allocation for the container.",
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
ContainerizedOption = Annotated[
    bool,
    typer.Option(
        "--dockerized",
        "--containerized",
        help="Run this invocation in the matching LibreLane container image.",
        rich_help_panel=CONTAINER_OPTIONS,
    ),
]
SmokeTestOption = Annotated[
    bool,
    typer.Option(
        "--smoke-test",
        help="Run the bundled smoke test and discard its results.",
        rich_help_panel=ACTION_OPTIONS,
    ),
]
RunExampleOption = Annotated[
    str | None,
    typer.Option(
        "--run-example",
        help="Copy and run a bundled LibreLane example.",
        rich_help_panel=ACTION_OPTIONS,
    ),
]
VersionOption = Annotated[
    bool,
    typer.Option(
        "--version",
        help="Print version and license information, then exit.",
        is_eager=True,
    ),
]
BareVersionOption = Annotated[
    bool,
    typer.Option("--bare-version", hidden=True, is_eager=True),
]
ForceRunDirOption = Annotated[
    Path | None,
    typer.Option(
        "--force-run-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        hidden=True,
        rich_help_panel=DEBUG_OPTIONS,
    ),
]
