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
from os.path import abspath
from typing import Any
from collections.abc import Sequence

from librelane.steps.step import Step, StepError, StepException

from librelane.config import variable
from librelane.state import DesignFormat
from librelane.common import Path


DesignFormat(
    "klayout_gds",
    "klayout.gds",
    "GDSII Stream (KLayout)",
    alts=["KLAYOUT_GDS"],
).register()


class KLayoutStep(Step):
    class Config(Step.Config):
        KLAYOUT_TECH: Path = variable(
            description="A path to the KLayout layer technology (.lyt) file.",
            pdk=True,
        )

        KLAYOUT_PROPERTIES: Path = variable(
            description="A path to the KLayout layer properties (.lyp) file.",
            pdk=True,
        )

        KLAYOUT_DEF_LAYER_MAP: Path | None = variable(
            None,
            description="A path to the KLayout LEF/DEF layer mapping (.map) file. Optional: a PDK whose .lyt file already embeds the mapping, as asap7 does, should leave this unset so the embedded one is used.",
            pdk=True,
        )

    config: Config

    def run_pya_script(
        self,
        cmd: Sequence[str | os.PathLike],
        log_to: str | os.PathLike | None = None,
        silent: bool = False,
        report_dir: str | os.PathLike | None = None,
        env: dict[str, Any] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        # Every caller invokes this with cmd[0] == sys.executable, so the
        # child is the same interpreter that is running this code: it
        # resolves its own site-packages the same way the parent did, and
        # inherits PYTHONPATH from the current environment (os.environ, or
        # the caller's env override) like any other subprocess. No explicit
        # propagation is needed.
        env = env or os.environ.copy()
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
            if (
                self.config.KLAYOUT_PROPERTIES is None
                or self.config.KLAYOUT_TECH is None
            ):
                raise StepError(
                    "Cannot open design in KLayout as the PDK does not appear to support KLayout."
                )
            result += [
                "--lyp",
                abspath(self.config.KLAYOUT_PROPERTIES),
                "--lyt",
                abspath(self.config.KLAYOUT_TECH),
            ]
            # Omitted entirely when the PDK has no separate .map file, so the
            # mapping the .lyt embeds survives. Passing an empty --lym would
            # not: assigning "" to lefdef_config.map_file clears the loaded
            # technology's own setting.
            if self.config.KLAYOUT_DEF_LAYER_MAP is not None:
                result += ["--lym", abspath(self.config.KLAYOUT_DEF_LAYER_MAP)]

        if include_lefs:
            tech_lefs = self.toolbox.filter_views(self.config, self.config.TECH_LEFS)
            if len(tech_lefs) != 1:
                raise StepException(
                    "Misconfigured SCL: 'TECH_LEFS' must return exactly one Tech LEF for its default timing corner."
                )

            lef_args = [
                "--input-lef",
                abspath(tech_lefs[0]),
            ]

            for lef in self.config.CELL_LEFS:
                lef_args.append("--input-lef")
                lef_args.append(abspath(lef))

            macro_lefs = self.toolbox.get_macro_views(self.config, DesignFormat.LEF)
            for lef in macro_lefs:
                lef_args.append("--input-lef")
                lef_args.append(abspath(lef))

            if extra_lefs := self.config.EXTRA_LEFS:
                for lef in extra_lefs:
                    lef_args.append("--input-lef")
                    lef_args.append(abspath(lef))

            if io_pad_lefs := self.config.PAD_LEFS:
                for lef in io_pad_lefs:
                    lef_args.append("--input-lef")
                    lef_args.append(abspath(lef))

            result += lef_args

        if include_gds:
            gds_args: list[str] = []

            for gds in self.config.CELL_GDS:
                gds_args.append("--with-gds-file")
                gds_args.append(str(gds))

            for gds in self.toolbox.get_macro_views(self.config, DesignFormat.GDS):
                gds_args.append("--with-gds-file")
                gds_args.append(str(gds))

            if extra_gds := self.config.EXTRA_GDS:
                for gds in extra_gds:
                    gds_args.append("--with-gds-file")
                    gds_args.append(str(gds))

            if io_pads_gds := self.config.PAD_GDS:
                for gds in io_pads_gds:
                    gds_args.append("--with-gds-file")
                    gds_args.append(str(gds))

            result += gds_args

        return result
