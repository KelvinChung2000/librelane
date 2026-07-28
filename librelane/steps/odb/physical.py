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
from decimal import Decimal
from typing import Literal, Optional

from ...common import Path
from ...config import variable
from ...state import State

from ..step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OdbpyStep


@Step.factory.register()
class ApplyDEFTemplate(OdbpyStep):
    """
    Copies the floorplan of a "template" DEF file for a new design, i.e.,
    it will copy the die area, core area, and non-power pin names and locations.
    """

    id = "Odb.ApplyDEFTemplate"
    name = "Apply DEF Template"

    class Config(Step.Config):
        FP_DEF_TEMPLATE: Optional[Path] = variable(
            None,
            description="Points to the DEF file to be used as a template.",
        )

        FP_TEMPLATE_MATCH_MODE: Literal["strict", "permissive"] = variable(
            "strict",
            description="Whether to require that the pin set of the DEF template and the design should be identical. In permissive mode, pins that are in the design and not in the template will be excluded, and vice versa.",
        )

        FP_TEMPLATE_COPY_POWER_PINS: bool = variable(
            False,
            description="Whether to *always* copy all power pins from the DEF template to the design.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath(
            "scripts",
            "odbpy",
            "apply_def_template.py",
        )

    def get_command(self) -> list[str]:
        args = [
            "--def-template",
            self.config.FP_DEF_TEMPLATE,
            f"--{self.config.FP_TEMPLATE_MATCH_MODE}",
        ]
        if self.config.FP_TEMPLATE_COPY_POWER_PINS:
            args.append("--copy-def-power")
        return super().get_command() + args

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.FP_DEF_TEMPLATE is None:
            logger.info(f"No DEF template provided, skipping '{self.id}'…")
            return {}, {}

        views_updates, metrics_updates = super().run(state_in, **kwargs)
        design_area_string = self.state_in.result().metrics.get("design__die__bbox")
        if design_area_string:
            template_area_string = metrics_updates["design__die__bbox"]
            template_area = [Decimal(point) for point in template_area_string.split()]
            design_area = [Decimal(point) for point in design_area_string.split()]
            if template_area != design_area:
                logger.bind(step=self.id).warning(
                    "The die area specificied in FP_DEF_TEMPLATE is different than the design die area. Pin placement may be incorrect."
                )
                logger.bind(step=self.id).warning(
                    f"Design area: {design_area_string}. Template def area: {template_area_string}"
                )
        return views_updates, {}
