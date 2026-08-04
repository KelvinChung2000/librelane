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
import sys
import pathlib
from os.path import abspath

from librelane.steps.step import ViewsUpdate, MetricsUpdate, Step, StepException

from librelane.config import variable
from librelane.state import DesignFormat, State
from librelane.common import Path

from librelane.steps.klayout.base import KLayoutStep


@Step.factory.register()
class SealRing(KLayoutStep):
    """
    Adds a seal ring in the correct size to the GDS.
    """

    id = "KLayout.SealRing"
    name = "Seal Ring Generation"

    inputs = [DesignFormat.GDS]
    outputs = [DesignFormat.GDS]

    class Config(KLayoutStep.Config):
        KLAYOUT_SEALRING_SCRIPT: Path | None = variable(
            None,
            description="A path to KLayout seal ring script.",
            pdk=True,
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}
        if self.config.PDK in ["ihp-sg13g2", "ihp-sg13cmos5l"]:
            views_updates, metrics_updates = self.run_ihp_sg13g2(state_in, **kwargs)
        else:
            views_updates, metrics_updates = self.run_generic(state_in, **kwargs)

        return views_updates, metrics_updates

    def run_generic(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}
        kwargs, env = self.extract_env(kwargs)

        if not self.config.KLAYOUT_SEALRING_SCRIPT:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_SEALRING_SCRIPT is unset. KLayout.SealRing may not be supported for the {self.config.PDK} PDK. This step will be skipped."
            )
            return views_updates, {}

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, pathlib.Path)
        output_gds = os.path.join(
            self.step_dir, f"{self.config.DESIGN_NAME}.{DesignFormat.GDS.extension}"
        )

        script = self.config.KLAYOUT_SEALRING_SCRIPT

        env["PDK_ROOT"] = self.config.PDK_ROOT
        env["PDK"] = self.config.PDK

        die_area = self.config.DIE_AREA
        if die_area is None:
            raise StepException(
                "A sealring can only be drawn around a known die: 'DIE_AREA' is unset."
            )

        self.run_pya_script(
            [
                sys.executable,
                script,
                "--input",
                abspath(input_gds),
                "--output",
                abspath(output_gds),
                "--die-width",
                f"{die_area[2]:f}",
                "--die-height",
                f"{die_area[3]:f}",
            ],
            env=env,
        )

        views_updates[DesignFormat.GDS] = pathlib.Path(output_gds)

        return views_updates, {}

    def run_ihp_sg13g2(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}
        kwargs, env = self.extract_env(kwargs)

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, pathlib.Path)
        output_gds = os.path.join(
            self.step_dir, f"{self.config.DESIGN_NAME}.{DesignFormat.GDS.extension}"
        )

        script = self.config.KLAYOUT_SEALRING_SCRIPT

        env["PDK_ROOT"] = self.config.PDK_ROOT
        env["PDK"] = self.config.PDK

        # Set KLAYOUT_PATH so that KLayout can load the technology definition
        env["KLAYOUT_PATH"] = os.path.join(
            self.config.PDK_ROOT, self.config.PDK, "libs.tech", "klayout"
        )

        die_area = self.config.DIE_AREA
        if die_area is None:
            raise StepException(
                "A sealring can only be drawn around a known die: 'DIE_AREA' is unset."
            )

        self.run_subprocess(
            [
                "klayout",
                "-zz",
                "-nc",
                "-n",
                self.config.PDK.replace("ihp-", ""),
                "-r",
                script,
                "-rd",
                f"width={die_area[3]:f}",
                "-rd",
                f"height={die_area[2]:f}",
                "-rd",
                f"input={abspath(input_gds)}",
                "-rd",
                f"output={abspath(output_gds)}",
            ],
            env=env,
        )

        views_updates[DesignFormat.GDS] = pathlib.Path(output_gds)

        return views_updates, {}


@Step.factory.register()
class Filler(KLayoutStep):
    """
    Generates the filler cells according to the design rules and adds them to the GDS.
    """

    id = "KLayout.Filler"
    name = "Filler Generation"

    inputs = [DesignFormat.GDS]
    outputs = [DesignFormat.GDS]

    class Config(KLayoutStep.Config):
        KLAYOUT_FILLER_SCRIPT: Path | None = variable(
            None,
            description="A path to KLayout filler script.",
            pdk=True,
        )

        KLAYOUT_FILLER_OPTIONS: dict[str, int | bool | str] | None = variable(
            None,
            description="Options passed directly to the KLayout filler script. They vary from one PDK to another.",
            pdk=True,
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}

        if not self.config.KLAYOUT_FILLER_SCRIPT:
            logger.bind(step=self.id).warning(
                f"KLAYOUT_FILLER_SCRIPT is unset. KLayout.Filler may not be supported for the {self.config.PDK} PDK. This step will be skipped."
            )
            return views_updates, metrics_updates

        if self.config.PDK in ["ihp-sg13g2", "ihp-sg13cmos5l"]:
            views_updates, metrics_updates = self.run_ihp_sg13g2(state_in, **kwargs)
        else:
            views_updates, metrics_updates = self.run_generic(state_in, **kwargs)

        return views_updates, metrics_updates

    def run_generic(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}
        kwargs, env = self.extract_env(kwargs)

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, pathlib.Path)
        output_gds = os.path.join(
            self.step_dir, f"{self.config.DESIGN_NAME}.{DesignFormat.GDS.extension}"
        )

        script = self.config.KLAYOUT_FILLER_SCRIPT

        opts = []
        if self.config.KLAYOUT_FILLER_OPTIONS:
            for k, v in self.config.KLAYOUT_FILLER_OPTIONS.items():
                opts.extend(
                    [
                        "-rd",
                        f"{k}={v}",
                    ]
                )

        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                script,
                "-rd",
                f"input={abspath(input_gds)}",
                "-rd",
                f"output={abspath(output_gds)}",
                *opts,
            ],
            env=env,
        )

        views_updates[DesignFormat.GDS] = pathlib.Path(output_gds)

        return views_updates, {}

    def run_ihp_sg13g2(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}
        kwargs, env = self.extract_env(kwargs)

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, pathlib.Path)
        output_gds = os.path.join(
            self.step_dir, f"{self.config.DESIGN_NAME}.{DesignFormat.GDS.extension}"
        )

        script = self.config.KLAYOUT_FILLER_SCRIPT

        env["PDK_ROOT"] = self.config.PDK_ROOT
        env["PDK"] = self.config.PDK

        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                script,
                "-rd",
                f"output_file={abspath(output_gds)}",
                abspath(input_gds),
            ],
            env=env,
        )

        views_updates[DesignFormat.GDS] = pathlib.Path(output_gds)

        return views_updates, {}
