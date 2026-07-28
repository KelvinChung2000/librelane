# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane
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
import os
import sys
import site
from os.path import abspath
from typing import Any
from collections.abc import Sequence

from ..step import Step, StepError, StepException

from ...config import Variable
from ...state import DesignFormat
from ...common import Path


DesignFormat(
    "klayout_gds",
    "klayout.gds",
    "GDSII Stream (KLayout)",
    alts=["KLAYOUT_GDS"],
).register()


class KLayoutStep(Step):
    config_vars = [
        Variable(
            "KLAYOUT_TECH",
            Path,
            "A path to the KLayout layer technology (.lyt) file.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_PROPERTIES",
            Path,
            "A path to the KLayout layer properties (.lyp) file.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_DEF_LAYER_MAP",
            Path,
            "A path to the KLayout LEF/DEF layer mapping (.map) file.",
            pdk=True,
        ),
    ]

    def run_pya_script(
        self,
        cmd: Sequence[str | os.PathLike],
        log_to: str | os.PathLike | None = None,
        silent: bool = False,
        report_dir: str | os.PathLike | None = None,
        env: dict[str, Any] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        env = env or os.environ.copy()
        # Pass site packages
        python_path_elements = site.getsitepackages() + sys.path
        if current_pythonpath := env.get("PYTHONPATH"):
            python_path_elements.append(current_pythonpath)

        env["PYTHONPATH"] = ":".join(python_path_elements)
        return super().run_subprocess(cmd, log_to, silent, report_dir, env, **kwargs)

    def get_cli_args(
        self,
        *,
        layer_info: bool = True,
        include_lefs: bool = False,
        include_gds: bool = False,
    ) -> list[str]:
        result = []
        if layer_info:
            lyp = abspath(self.config["KLAYOUT_PROPERTIES"])
            lyt = abspath(self.config["KLAYOUT_TECH"])
            lym = abspath(self.config["KLAYOUT_DEF_LAYER_MAP"])
            if None in [lyp, lyt, lym]:
                raise StepError(
                    "Cannot open design in KLayout as the PDK does not appear to support KLayout."
                )
            result += ["--lyp", lyp, "--lyt", lyt, "--lym", lym]

        if include_lefs:
            tech_lefs = self.toolbox.filter_views(self.config, self.config["TECH_LEFS"])
            if len(tech_lefs) != 1:
                raise StepException(
                    "Misconfigured SCL: 'TECH_LEFS' must return exactly one Tech LEF for its default timing corner."
                )

            lef_args = [
                "--input-lef",
                abspath(tech_lefs[0]),
            ]

            for lef in self.config["CELL_LEFS"]:
                lef_args.append("--input-lef")
                lef_args.append(abspath(lef))

            macro_lefs = self.toolbox.get_macro_views(self.config, DesignFormat.LEF)
            for lef in macro_lefs:
                lef_args.append("--input-lef")
                lef_args.append(abspath(lef))

            if extra_lefs := self.config["EXTRA_LEFS"]:
                for lef in extra_lefs:
                    lef_args.append("--input-lef")
                    lef_args.append(abspath(lef))

            if io_pad_lefs := self.config["PAD_LEFS"]:
                for lef in io_pad_lefs:
                    lef_args.append("--input-lef")
                    lef_args.append(abspath(lef))

            result += lef_args

        if include_gds:
            gds_args: list[str] = []

            for gds in self.config["CELL_GDS"]:
                gds_args.append("--with-gds-file")
                gds_args.append(gds)

            for gds in self.toolbox.get_macro_views(self.config, DesignFormat.GDS):
                gds_args.append("--with-gds-file")
                gds_args.append(str(gds))

            if extra_gds := self.config["EXTRA_GDS"]:
                for gds in extra_gds:
                    gds_args.append("--with-gds-file")
                    gds_args.append(gds)

            if io_pads_gds := self.config["PAD_GDS"]:
                for gds in io_pads_gds:
                    gds_args.append("--with-gds-file")
                    gds_args.append(gds)

            result += gds_args

        return result
