# Copyright 2020-2022 Efabless Corporation
# Copyright 2021 The American University in Cairo and the Cloud V Project
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
import os
import sys
from typing import Optional

import click
import pya  # Must be run inside KLayout-- the library version of pya does not include "Application"
from click.shell_completion import split_arg_string


def open_design(
    input_lefs: tuple[str, ...],
    lyt: str,
    lyp: str,
    lym: Optional[str],
    input: str,
):
    try:
        main_window = pya.Application.instance().main_window()

        tech = pya.Technology()
        tech.load(lyt)
        # Register the technology.
        # Throws an exception if a technology
        # with the same name already exists.
        try:
            pya.Technology().register_technology(tech)
        except Exception:
            print(f"Could not register the technology: {tech.name}.")

        layout_options = tech.load_layout_options
        layout_options.keep_other_cells = True
        layout_options.lefdef_config.macro_resolution_mode = 1
        layout_options.lefdef_config.read_lef_with_def = False
        layout_options.lefdef_config.lef_files = list(input_lefs)
        # Left alone when no .map was given, so the mapping the .lyt embeds
        # survives; assigning an empty value clears it.
        if lym is not None:
            layout_options.lefdef_config.map_file = lym

        cell_view = main_window.load_layout(input, layout_options, tech.name, False)
        layout_view = cell_view.view()
        layout_view.load_layer_props(lyp)
    except Exception as e:
        print(e, file=sys.stderr)
        pya.Application.instance().exit(1)


@click.command()
@click.option(
    "-l",
    "--input-lef",
    "input_lefs",
    multiple=True,
    help="KLayout .lef files",
)
@click.option("-T", "--lyt", required=True, help="KLayout .lyt file")
@click.option("-P", "--lyp", required=True, help="KLayout .lyp file")
@click.option(
    "-M",
    "--lym",
    required=False,
    default=None,
    help="KLayout .map (LEF/DEF layer map) file. Omit when the .lyt embeds the mapping.",
)
@click.argument("input")
def cli(
    input_lefs: tuple[str, ...], lyt: str, lyp: str, lym: Optional[str], input: str
):
    """Open a layout in the KLayout GUI."""
    open_design(input_lefs, lyt, lyp, lym, input)


if __name__ == "__main__":
    try:
        cli.main(
            args=split_arg_string(os.environ["KLAYOUT_ARGV"]),
            prog_name="open_design.py",
            standalone_mode=False,
        )
    except click.ClickException as e:
        e.show()
        raise SystemExit(e.exit_code) from None
