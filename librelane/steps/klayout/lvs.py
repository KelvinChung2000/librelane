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
from loguru import logger

import os
from os.path import abspath
from tempfile import NamedTemporaryFile
from typing import Optional

from ..step import ViewsUpdate, MetricsUpdate, Step

from ...config import variable
from ...state import DesignFormat, State
from ...common import Path, mkdirp

from .base import KLayoutStep


@Step.factory.register()
class LVS(KLayoutStep):
    id = "KLayout.LVS"
    name = "Layout Versus Schematic (KLayout)"

    inputs = [
        DesignFormat.CDL,
        DesignFormat.GDS,
    ]
    outputs = [DesignFormat.SPICE]

    class Config(KLayoutStep.Config):
        KLAYOUT_LVS_SCRIPT: Optional[Path] = variable(
            None,
            description="A path to KLayout LVS script.",
            pdk=True,
        )

        KLAYOUT_LVS_OPTIONS: Optional[dict[str, bool | int | str]] = variable(
            None,
            description="Options passed directly to the KLayout LVS script. They vary from one PDK to another.",
            pdk=True,
        )

    config: Config

    def run_ihp_sg13g2(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        lvs_script_path = self.config.KLAYOUT_LVS_SCRIPT

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lvsdb_report = os.path.join(reports_dir, "lvs.klayout.lvsdb")

        input_view_gds = state_in[DesignFormat.GDS]
        input_view_cdl = state_in[DesignFormat.CDL]
        assert isinstance(input_view_gds, Path)
        assert isinstance(input_view_cdl, Path)

        output_spice = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.SPICE.value.extension}",
        )

        with NamedTemporaryFile("w") as f:
            # Merge all CDL inputs
            cdl_lst = [input_view_cdl]
            cdl_lst.extend(self.config.CELL_CDLS or [])
            cdl_lst.extend(self.config.EXTRA_CDLS or [])
            cdl_lst.extend(self.config.PAD_CDLS or [])

            for fn in cdl_lst:
                with open(fn, "r") as cdl_fh:
                    f.write(cdl_fh.read())

            opts = []
            if self.config.KLAYOUT_LVS_OPTIONS:
                for k, v in self.config.KLAYOUT_LVS_OPTIONS.items():
                    opts.extend(
                        [
                            "-rd",
                            f"{k}={v}",
                        ]
                    )

            # Not pya script - LVS script is not part of LibreLane
            subprocess_result = self.run_subprocess(
                [
                    "klayout",
                    "-b",
                    "-zz",
                    "-r",
                    lvs_script_path,
                    "-rd",
                    f"input={abspath(input_view_gds)}",
                    "-rd",
                    f"schematic={abspath(f.name)}",
                    "-rd",
                    f"report={abspath(lvsdb_report)}",
                    "-rd",
                    f"target_netlist={abspath(output_spice)}",
                ]
                + opts,
                env=env,
            )

            with open(subprocess_result["log_path"]) as fh:
                for line in fh:
                    if "INFO : Congratulations! Netlists match" in line:
                        ok = True
                        break
                    elif "ERROR : Netlists don't match" in line:
                        ok = False
                        break
                else:
                    ok = False

        views_updates: ViewsUpdate = {
            DesignFormat.SPICE: Path(output_spice),
        }
        metrics_updates: MetricsUpdate = {
            "design__lvs_error__count": 0 if ok else 1,
        }

        return views_updates, metrics_updates

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}
        if self.config.PDK in ["ihp-sg13g2", "ihp-sg13cmos5l"]:
            views_updates, metrics_updates = self.run_ihp_sg13g2(state_in, **kwargs)
        else:
            logger.bind(step=self.id).warning(
                f"KLayout LVS is not supported for the {self.config.PDK} PDK. This step will be skipped."
            )

        return views_updates, metrics_updates
