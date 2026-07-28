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

from ...resources import package_path
import os
from os.path import abspath
from typing import Optional

from ..step import ViewsUpdate, MetricsUpdate, Step

from ...config import Variable
from ...state import DesignFormat, State
from ...common import Path, mkdirp, _get_process_limit

from .base import KLayoutStep


@Step.factory.register()
class XOR(KLayoutStep):
    """
    Performs an XOR operation on the Magic and KLayout GDS views. The idea is:
    if there's any difference between the GDSII streams between the two tools,
    one of them have it wrong and that may lead to ambiguity.
    """

    id = "KLayout.XOR"
    name = "KLayout vs. Magic XOR"

    inputs = [
        DesignFormat.MAG_GDS,
        DesignFormat.KLAYOUT_GDS,
    ]
    outputs = []

    config_vars = KLayoutStep.config_vars + [
        Variable(
            "KLAYOUT_XOR_THREADS",
            Optional[int],
            "Specifies number of threads used in the KLayout XOR check. If unset, this will be equal to your machine's thread count.",
        ),
        Variable(
            "KLAYOUT_XOR_IGNORE_LAYERS",
            Optional[list[str]],
            "KLayout layers to ignore during XOR operations.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_XOR_TILE_SIZE",
            Optional[int],
            "The tile size to parallelize the XOR process with.",
            pdk=True,
            units="µm",
        ),
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        ignored = ""
        if ignore_list := self.config["KLAYOUT_XOR_IGNORE_LAYERS"]:
            ignored = ";".join(ignore_list)

        layout_a = state_in[DesignFormat.MAG_GDS]
        if layout_a is None:
            logger.bind(step=self.id).warning(
                "No Magic stream-out has been performed. Skipping XOR process…"
            )
            return {}, {}
        layout_b = state_in[DesignFormat.KLAYOUT_GDS]
        if layout_b is None:
            logger.bind(step=self.id).warning(
                "No KLayout stream-out has been performed. Skipping XOR process…"
            )
            return {}, {}

        assert isinstance(layout_a, Path)
        assert isinstance(layout_b, Path)

        kwargs, env = self.extract_env(kwargs)

        tile_size_options = []
        if tile_size := self.config["KLAYOUT_XOR_TILE_SIZE"]:
            tile_size_options += ["--tile-size", str(tile_size)]

        thread_count = self.config["KLAYOUT_XOR_THREADS"] or _get_process_limit()
        logger.info(f"Running XOR with {thread_count} threads…")

        subprocess_result = self.run_subprocess(
            [
                "ruby",
                package_path().joinpath(
                    "scripts",
                    "klayout",
                    "xor.drc",
                ),
                "--output",
                abspath(os.path.join(self.step_dir, "xor.xml")),
                "--top",
                self.config["DESIGN_NAME"],
                "--threads",
                thread_count,
                "--ignore",
                ignored,
                abspath(layout_a),
                abspath(layout_b),
            ]
            + tile_size_options,
            env=env,
        )

        return {}, subprocess_result["generated_metrics"]


@Step.factory.register()
class Density(KLayoutStep):
    """
    Runs the density check on the GDS.
    """

    id = "KLayout.Density"
    name = "Density Check"

    inputs = [DesignFormat.GDS]
    outputs = []

    config_vars = KLayoutStep.config_vars + [
        Variable(
            "KLAYOUT_DENSITY_RUNSET",
            Optional[Path],
            "A path to KLayout density runset.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_DENSITY_OPTIONS",
            Optional[dict[str, bool | int | str]],
            "Options passed directly to the KLayout density runset. They vary from one PDK to another.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_DENSITY_THREADS",
            Optional[int],
            "Specifies the number of threads to be used in KLayout density check."
            + "If unset, this will be equal to your machine's thread count.",
        ),
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}

        metrics_updates = self.run_generic(state_in, **kwargs)

        return views_updates, metrics_updates

    def run_generic(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)

        if not self.config["KLAYOUT_DENSITY_RUNSET"]:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_DENSITY_RUNSET is unset. KLayout.Density may not be supported for the {self.config['PDK']} PDK. This step will be skipped."
            )
            return {}

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, Path)

        script = self.config["KLAYOUT_DENSITY_RUNSET"]

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lyrdb_report = os.path.join(reports_dir, "density.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "density.klayout.json")

        opts = []
        if self.config["KLAYOUT_DENSITY_OPTIONS"]:
            for k, v in self.config["KLAYOUT_DENSITY_OPTIONS"].items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        threads = self.config["KLAYOUT_DENSITY_THREADS"] or str(_get_process_limit())
        if threads != "1":
            opts.extend(
                [
                    "-rd",
                    f"thr={threads}",
                ]
            )

        logger.info(f"Running KLayout density check with {threads} threads…")

        # Not a pya script
        subprocess_result = self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                script,
                "-rd",
                f"input={abspath(input_gds)}",
                "-rd",
                f"topcell={self.config['DESIGN_NAME']}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
            ]
            + opts,
            env=env,
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    package_path().joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__density_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]


@Step.factory.register()
class Antenna(KLayoutStep):
    """
    Runs the antenna check on the GDS.
    """

    id = "KLayout.Antenna"
    name = "Antenna Check"

    inputs = [DesignFormat.GDS]
    outputs = []

    config_vars = KLayoutStep.config_vars + [
        Variable(
            "KLAYOUT_ANTENNA_RUNSET",
            Optional[Path],
            "A path to KLayout antenna runset.",
            pdk=True,
        ),
        Variable(
            "KLAYOUT_ANTENNA_OPTIONS",
            Optional[dict[str, bool | int | str]],
            "Options passed directly to the KLayout density runset. They vary from one PDK to another.",
            pdk=True,
        ),
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}

        metrics_updates = self.run_generic(state_in, **kwargs)

        return views_updates, metrics_updates

    def run_generic(self, state_in: State, **kwargs) -> MetricsUpdate:
        kwargs, env = self.extract_env(kwargs)

        if not self.config["KLAYOUT_ANTENNA_RUNSET"]:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_ANTENNA_RUNSET is unset. KLayout.Antenna may not be supported for the {self.config['PDK']} PDK. This step will be skipped."
            )
            return {}

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, Path)

        script = self.config["KLAYOUT_ANTENNA_RUNSET"]

        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)
        lyrdb_report = os.path.join(reports_dir, "antenna.klayout.lyrdb")
        json_report = os.path.join(reports_dir, "antenna.klayout.json")

        opts = []
        if self.config["KLAYOUT_ANTENNA_OPTIONS"]:
            for k, v in self.config["KLAYOUT_ANTENNA_OPTIONS"].items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        logger.info("Running KLayout antenna check…")

        # Not a pya script
        subprocess_result = self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                script,
                "-rd",
                f"input={abspath(input_gds)}",
                "-rd",
                f"topcell={self.config['DESIGN_NAME']}",
                "-rd",
                f"report={abspath(lyrdb_report)}",
            ]
            + opts,
            env=env,
        )

        subprocess_result = self.run_pya_script(
            [
                "python3",
                str(
                    package_path().joinpath(
                        "scripts", "klayout", "xml_drc_report_to_json.py"
                    )
                ),
                f"--xml-file={abspath(lyrdb_report)}",
                f"--json-file={abspath(json_report)}",
                "--metric=klayout__antenna_error__count",
            ],
            env=env,
            log_to=os.path.join(self.step_dir, "xml_drc_report_to_json.log"),
        )
        return subprocess_result["generated_metrics"]
