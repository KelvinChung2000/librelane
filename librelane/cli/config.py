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
"""The ``librelane config`` subcommand group."""

from decimal import Decimal
import json
import os
from pathlib import Path
import shlex
from typing import Annotated

import typer

from librelane.config import Config
from librelane.flows.flow import universal_flow_config_variables
from librelane.steps.pyosys import verilog_rtl_cfg_vars
from librelane.cli._app import make_group
from librelane.cli.options import (
    CondensedOption,
    JobsOption,
    LogLevelOption,
    PadOption,
    PdkOption,
    PdkRootOption,
    SclOption,
    ShowProgressBarOption,
    UseCielOption,
)
from librelane.cli.runtime import (
    DEFAULT_JOBS,
    apply_runtime_options,
    resolve_pdk_options,
)


cli = make_group(help="Create and inspect LibreLane design configurations.")


@cli.command()
def create(
    design_name: Annotated[
        str,
        typer.Option(
            "--design-name",
            "--top-module",
            prompt=("Enter the design name (equal to the HDL name of your top module)"),
            help="The top-level HDL module name.",
        ),
    ],
    clock_port: Annotated[
        str,
        typer.Option(
            "--clock-port",
            prompt="Enter the name of your design's clock port",
            help="The clock-port identifier.",
        ),
    ],
    clock_period: Annotated[
        Decimal,
        typer.Option(
            "--clock-period",
            parser=Decimal,
            prompt="Enter your desired clock period in nanoseconds",
            help="The clock period in nanoseconds.",
        ),
    ],
    source_rtl: Annotated[
        list[Path] | None,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Verilog or SystemVerilog source files.",
        ),
    ] = None,
    file_name: Annotated[
        Path,
        typer.Option(
            "--file-name",
            file_okay=True,
            dir_okay=False,
            prompt="Please input the file name for the configuration file",
            help="The output configuration file.",
        ),
    ] = Path("config.json"),
    design_dir: Annotated[
        Path,
        typer.Option(
            "--design-dir",
            exists=True,
            file_okay=False,
            dir_okay=True,
            prompt="Enter the base directory for your design",
            help="The top-level design directory.",
        ),
    ] = Path("."),
    use_ciel: UseCielOption = True,
    pdk_root: PdkRootOption = None,
    pdk: PdkOption = "sky130A",
    scl: SclOption = None,
    pad: PadOption = None,
    log_level: LogLevelOption = None,
    show_progress_bar: ShowProgressBarOption = None,
    condensed: CondensedOption = False,
    jobs: JobsOption = DEFAULT_JOBS,
) -> None:
    """Generate a LibreLane JSON configuration interactively."""
    apply_runtime_options(
        log_level=log_level,
        show_progress_bar=show_progress_bar,
        condensed=condensed,
        jobs=jobs,
    )
    resolved_pdk = resolve_pdk_options(
        use_ciel=use_ciel,
        pdk_root=pdk_root,
        pdk=pdk,
        scl=scl,
        pad=pad,
    )

    sources = list(source_rtl or [])
    if not sources:
        try:
            while True:
                source = Path(
                    input(f"Input RTL source file #{len(sources)} (Ctrl+D to stop): ")
                )
                if not source.is_file():
                    typer.echo(f"Invalid file {source}.", err=True)
                    raise typer.Exit(1)
                sources.append(source)
        except EOFError:
            typer.echo()
            if not sources:
                typer.echo("At least one source RTL file is required.", err=True)
                raise typer.Exit(1)

    if not all(source.suffix in {".sv", ".v"} for source in sources):
        typer.echo(
            "Only Verilog/SystemVerilog files are supported by 'config create'.",
            err=True,
        )
        raise typer.Exit(-1)

    source_rtl_rel = [
        f"dir::{os.path.relpath(source, design_dir)}" for source in sources
    ]
    config_dict = {
        "DESIGN_NAME": design_name,
        "CLOCK_PORT": clock_port,
        "CLOCK_PERIOD": clock_period,
        "VERILOG_FILES": source_rtl_rel,
        "meta": {"version": 2},
    }
    config, _ = Config.load(
        config_dict,
        universal_flow_config_variables + verilog_rtl_cfg_vars,
        design_dir=str(design_dir),
        pdk=resolved_pdk.pdk,
        pdk_root=resolved_pdk.pdk_root,
        scl=resolved_pdk.scl,
    )
    with file_name.open("w", encoding="utf8") as output:
        json.dump(config_dict, output, cls=config.get_encoder(), indent=4)
        output.write("\n")

    arguments = ["librelane"]
    if design_dir.resolve() != file_name.parent.resolve():
        arguments.extend(["--design-dir", str(design_dir)])
    arguments.append(str(file_name))

    typer.echo(f"Wrote config to '{file_name}'.")
    typer.echo("To run this design, invoke:")
    typer.echo(f"\t{shlex.join(arguments)}")


if __name__ == "__main__":
    cli()
