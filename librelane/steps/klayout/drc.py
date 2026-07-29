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

from importlib.resources import files
import os
from os.path import abspath
from typing import Optional

from ..step import ViewsUpdate, MetricsUpdate, Step, StepException

from ...config import variable
from ...state import DesignFormat, State
from ...common import Path, mkdirp, _get_process_limit

from .base import KLayoutStep


@Step.factory.register()
class DRC(KLayoutStep):
    """
    Runs DRC using KLayout.

    Unlike most steps, the KLayout scripts vary quite wildly by PDK. If a PDK
    is not supported by this step, it will simply be skipped.

    Currently, only sky130A and sky130B are supported.
    """

    id = "KLayout.DRC"
    name = "Design Rule Check (KLayout)"

    inputs = [
        DesignFormat.GDS,
    ]
    outputs = []

    class Config(KLayoutStep.Config):
        KLAYOUT_DRC_RUNSET: Optional[Path] = variable(
            None,
            description="A path to KLayout DRC runset.",
            pdk=True,
            deprecated_names=["KLAYOUT_DRC_TECH_SCRIPT"],
        )

        KLAYOUT_DRC_OPTIONS: Optional[dict[str, bool | int | str]] = variable(
            None,
            description="Options passed directly to the KLayout DRC runset. They vary from one PDK to another.",
            pdk=True,
        )

        KLAYOUT_DRC_THREADS: Optional[int] = variable(
            None,
            description="Specifies the number of threads to be used in KLayout DRC."
            + "If unset, this will be equal to your machine's thread count.",
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        if self.config.PDK in ["sky130A", "sky130B"]:
            metrics_updates = self.run_sky130(state_in, **kwargs)
        elif self.config.PDK in ["gf180mcuA", "gf180mcuB", "gf180mcuC", "gf180mcuD"]:
            metrics_updates = self.run_gf180mcu(state_in, **kwargs)
        elif self.config.PDK in ["ihp-sg13g2", "ihp-sg13cmos5l"]:
            metrics_updates = self.run_ihp_sg13g2(state_in, **kwargs)
        else:
            metrics_updates = self.run_generic(state_in, **kwargs)

        return {}, metrics_updates

    def run_generic(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)

        if not self.config.KLAYOUT_DRC_RUNSET:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_DRC_RUNSET is unset. KLayout.DRC may not be supported for the {self.config.PDK} PDK. This step will be skipped."
            )
            return {}

        drc_script_path = self.config.KLAYOUT_DRC_RUNSET

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lyrdb_report = os.path.join(reports_dir, "drc.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "drc.klayout.json")

        input_view = state_in[DesignFormat.GDS]
        assert isinstance(input_view, Path)

        opts = []
        if self.config.KLAYOUT_DRC_OPTIONS:
            for k, v in self.config.KLAYOUT_DRC_OPTIONS.items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        threads = self.config.KLAYOUT_DRC_THREADS or str(_get_process_limit())
        if threads != "1":
            opts.extend(
                [
                    "-rd",
                    f"thr={threads}",
                    # Use "threads" if possible
                    "-rd",
                    f"threads={threads}",
                ]
            )

        logger.info(f"Running KLayout DRC with {threads} threads…")

        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                drc_script_path,
                "-rd",
                f"input={abspath(input_view)}",
                "-rd",
                f"topcell={self.config.DESIGN_NAME}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
                *opts,
            ]
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    files("librelane").joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__drc_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]

    def run_sky130(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)
        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        drc_script_path = self.config.KLAYOUT_DRC_RUNSET
        lyrdb_report = os.path.join(reports_dir, "drc.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "drc.klayout.json")
        options = self.config.KLAYOUT_DRC_OPTIONS
        if options is None:
            raise StepException(
                "The sky130 KLayout DRC runset is driven by 'KLAYOUT_DRC_OPTIONS', which the PDK does not declare."
            )
        feol = str(options["feol"]).lower()
        beol = str(options["beol"]).lower()
        floating_metal = str(options["floating_metal"]).lower()
        offgrid = str(options["offgrid"]).lower()
        seal = str(options["seal"]).lower()
        threads = self.config.KLAYOUT_DRC_THREADS or _get_process_limit()
        logger.info(f"Running KLayout DRC with {threads} threads…")

        input_view = state_in[DesignFormat.GDS]
        assert isinstance(input_view, Path)

        # Not pya script - DRC script is not part of LibreLane
        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                drc_script_path,
                "-rd",
                f"input={abspath(input_view)}",
                "-rd",
                f"topcell={self.config.DESIGN_NAME}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
                "-rd",
                f"feol={feol}",
                "-rd",
                f"beol={beol}",
                "-rd",
                f"floating_metal={floating_metal}",
                "-rd",
                f"offgrid={offgrid}",
                "-rd",
                f"seal={seal}",
                "-rd",
                f"threads={threads}",
            ],
            env=env,
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    files("librelane").joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__drc_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]

    def run_gf180mcu(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)

        if not self.config.KLAYOUT_DRC_RUNSET:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_DRC_RUNSET is unset. KLayout.DRC may not be supported for the {self.config.PDK} PDK. This step will be skipped."
            )
            return {}

        drc_script_path = self.config.KLAYOUT_DRC_RUNSET

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lyrdb_report = os.path.join(reports_dir, "drc.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "drc.klayout.json")

        input_view = state_in[DesignFormat.GDS]
        assert isinstance(input_view, Path)

        opts = []
        if self.config.KLAYOUT_DRC_OPTIONS:
            for k, v in self.config.KLAYOUT_DRC_OPTIONS.items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        threads = self.config.KLAYOUT_DRC_THREADS or str(_get_process_limit())
        if threads != "1":
            opts.extend(
                [
                    "-rd",
                    f"thr={threads}",
                ]
            )

        logger.info(f"Running KLayout DRC with {threads} threads…")

        # Not pya script - DRC script is not part of OpenLane
        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                drc_script_path,
                "-rd",
                f"input={abspath(input_view)}",
                "-rd",
                f"topcell={self.config.DESIGN_NAME}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
                *opts,
            ]
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    files("librelane").joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__drc_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]

    def run_ihp_sg13g2(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)

        drc_script_path = self.config.KLAYOUT_DRC_RUNSET

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lyrdb_report = os.path.join(reports_dir, "drc.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "drc.klayout.json")

        input_view = state_in[DesignFormat.GDS]
        assert isinstance(input_view, Path)

        opts = []
        if self.config.KLAYOUT_DRC_OPTIONS:
            for k, v in self.config.KLAYOUT_DRC_OPTIONS.items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        threads = self.config.KLAYOUT_DRC_THREADS or str(_get_process_limit())
        if threads != "1":
            opts.extend(
                [
                    "-rd",
                    f"thr={threads}",
                ]
            )

        logger.info(f"Running KLayout DRC with {threads} threads…")

        # Not pya script - DRC script is not part of OpenLane
        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                drc_script_path,
                "-rd",
                f"input={abspath(input_view)}",
                "-rd",
                f"topcell={self.config.DESIGN_NAME}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
                *opts,
            ]
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    files("librelane").joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__drc_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]
