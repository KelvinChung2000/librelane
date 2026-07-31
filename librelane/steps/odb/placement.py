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
import shutil
from typing import Literal, Optional

from librelane.common import Path
from librelane.config import Instance, Macro, variable
from librelane.state import State

from librelane.steps.common_variables import IoLayerConfig
from librelane.steps.step import (
    MetricsUpdate,
    Step,
    StepException,
    ViewsUpdate,
)

from librelane.steps.odb.base import OdbpyStep

_migrate_unmatched_io = lambda x: "unmatched_design" if x else "none"


@Step.factory.register()
class ManualMacroPlacement(OdbpyStep):
    """
    Performs macro placement using a simple configuration file. The file is
    defined as a line-break delimited list of instances and positions, in the
    format ``instance_name X_pos Y_pos Orientation``.

    If no macro instances are configured, this step is skipped.
    """

    id = "Odb.ManualMacroPlacement"
    name = "Manual Macro Placement"

    class Config(Step.Config):
        MACRO_PLACEMENT_CFG: Optional[Path] = variable(
            None,
            description="Path to an optional override for instance placement instead of the `MACROS` object for compatibility with LibreLane 1. If both are `None`, this step is skipped.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "placers.py")

    def get_subcommand(self) -> list[str]:
        return ["manual-macro-placement"]

    def get_command(self) -> list[str]:
        return super().get_command() + [
            "--config",
            os.path.join(self.step_dir, "placement.cfg"),
            "--fixed",
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        cfg_file = Path(os.path.join(self.step_dir, "placement.cfg"))
        if cfg_ref := self.config.get("MACRO_PLACEMENT_CFG"):
            logger.bind(step=self.id).warning(
                "Using 'MACRO_PLACEMENT_CFG' is deprecated. It is recommended to use the new 'MACROS' configuration variable."
            )
            shutil.copyfile(cfg_ref, cfg_file)
        elif macros := self.config.get("MACROS"):
            instance_count = sum(len(m.instances) for m in macros.values())
            if instance_count >= 1:
                with open(cfg_file, "w") as f:
                    for module, macro in macros.items():
                        if not isinstance(macro, Macro):
                            raise StepException(
                                f"Misconstructed configuration: macro definition for key {module} is not of type 'Macro'."
                            )
                        for name, data in macro.instances.items():
                            if data.location is not None:
                                if data.orientation is None:
                                    raise StepException(
                                        f"Instance {name} of macro {module} has a location configured, but no orientation."
                                    )
                                f.write(
                                    f"{name} {data.location[0]} {data.location[1]} {data.orientation}\n"
                                )
                            else:
                                logger.log(
                                    "VERBOSE",
                                    f"Instance {name} of macro {module} has no location configured, ignoring…",
                                )

        if not cfg_file.exists():
            logger.info(f"No instances found, skipping '{self.id}'…")
            return {}, {}

        return super().run(state_in, **kwargs)


@Step.factory.register()
class CustomIOPlacement(OdbpyStep):
    """
    Places I/O pins using a custom script, which uses a "pin order configuration"
    file.

    Check the reference documentation for the structure of said file.
    """

    id = "Odb.CustomIOPlacement"
    name = "Custom I/O Placement"
    long_name = "Custom I/O Pin Placement Script"

    class Config(IoLayerConfig, OdbpyStep.Config):
        IO_PIN_ORDER_CFG: Optional[Path] = variable(
            None,
            description="Path to a custom pin configuration file.",
            deprecated_names=["FP_PIN_ORDER_CFG"],
        )

        ERRORS_ON_UNMATCHED_IO: Literal[
            "none", "unmatched_design", "unmatched_cfg", "both"
        ] = variable(
            "unmatched_design",
            description="Controls whether to emit an error in: no situation, when pins exist in the design that do not exist in the config file, when pins exist in the config file that do not exist in the design, and both respectively. `both` is recommended, as the default is only for backwards compatibility with LibreLane 1.",
            deprecated_names=[("QUIT_ON_UNMATCHED_IO", _migrate_unmatched_io)],
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "io_place.py")

    def get_command(self) -> list[str]:
        length_args: list[str] = []
        if self.config.IO_PIN_V_LENGTH is not None:
            length_args += ["--ver-length", str(self.config.IO_PIN_V_LENGTH)]
        if self.config.IO_PIN_H_LENGTH is not None:
            length_args += ["--hor-length", str(self.config.IO_PIN_H_LENGTH)]

        assert self.config.IO_PIN_ORDER_CFG is not None, (
            "run() skips a design with no pin order file"
        )
        return (
            super().get_command()
            + [
                "--config",
                str(self.config.IO_PIN_ORDER_CFG),
                "--hor-layer",
                self.config.IO_PIN_H_LAYER,
                "--ver-layer",
                self.config.IO_PIN_V_LAYER,
                "--hor-width-mult",
                str(self.config.IO_PIN_V_THICKNESS_MULT),
                "--ver-width-mult",
                str(self.config.IO_PIN_H_THICKNESS_MULT),
                "--hor-extension",
                str(self.config.IO_PIN_H_EXTENSION),
                "--ver-extension",
                str(self.config.IO_PIN_V_EXTENSION),
                "--unmatched-error",
                self.config.ERRORS_ON_UNMATCHED_IO,
            ]
            + length_args
        )

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.IO_PIN_ORDER_CFG is None:
            logger.info(
                f"No custom I/O placement file configured, skipping '{self.id}'…"
            )
            return {}, {}
        return super().run(state_in, **kwargs)


@Step.factory.register()
class ManualGlobalPlacement(OdbpyStep):
    """
    This is an step to override the placement of one or more instances at
    user-specified locations.

    Alternatively, if this is a custom design with a few cells, this can be used
    in place of the global placement entirely.
    """

    id = "Odb.ManualGlobalPlacement"
    name = "Manual Global Placement"

    class Config(OdbpyStep.Config):
        MANUAL_GLOBAL_PLACEMENTS: Optional[dict[str, Instance]] = variable(
            None,
            description="A dictionary of instances to their global (non-legalized and unfixed) placement location.",
        )

    config: Config

    def get_script_path(self) -> str:
        return str(files("librelane").joinpath("scripts", "odbpy", "placers.py"))

    def get_subcommand(self) -> list[str]:
        return ["manual-global-placement"]

    def get_command(self) -> list[str]:
        assert self.config_path is not None, "get_command called before start()"
        return super().get_command() + [
            "--step-config",
            os.fspath(self.config_path),
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.MANUAL_GLOBAL_PLACEMENTS is None:
            logger.info(f"'MANUAL_GLOBAL_PLACEMENTS' not set. Skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)
