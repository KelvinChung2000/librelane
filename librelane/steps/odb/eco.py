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
from importlib.resources import files
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

from librelane.config import variable
from librelane.state import State

from librelane.steps.common_variables import DplConfig, GrtConfig
from librelane.steps.step import (
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from librelane.steps.odb.base import OdbpyStep


@dataclass
class ECOBuffer:
    """
    Parameters
    ----------
    target : str
        The driver to insert an ECO buffer after or sink to insert an
        ECO buffer before, in the format instance_name/pin_name.
    buffer : str
        The kind of buffer cell to use.
    placement : tuple[Decimal, Decimal] | None
        The coarse placement for this buffer (to be legalized.)
        If unset, depending on whether the target is a driver or a sink:

        - Driver: The placement will be the average of the driver and all sinks.

        - Sink: The placement will be the average of the sink and all drivers.
    """

    target: str
    buffer: str
    placement: tuple[Decimal, Decimal] | None = None


@Step.factory.register()
class InsertECOBuffers(OdbpyStep):
    """
    Experimental step to insert ECO buffers on either drivers or sinks after
    global or detailed routing. The placement is legalized and global routing is
    incrementally re-run for affected nets. Useful for manually fixing some hold
    violations.

    If run after detailed routing, detailed routing must be re-run as affected
    nets that are altered are removed and require re-routing.

    INOUT and FEEDTHRU ports are not supported.
    """

    id = "Odb.InsertECOBuffers"
    name = "Insert ECO Buffers"

    class Config(GrtConfig, DplConfig, OdbpyStep.Config):
        INSERT_ECO_BUFFERS: Optional[list[ECOBuffer]] = variable(
            None,
            description="List of buffers to insert",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "eco_buffer.py")

    def get_command(self) -> list[str]:
        assert self.config_path is not None, "get_command called before start()"
        return super().get_command() + [
            "--step-config",
            os.fspath(self.config_path),
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.INSERT_ECO_BUFFERS is None:
            logger.info(f"'INSERT_ECO_BUFFERS' not set. Skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)


@dataclass
class ECOCellReplacement:
    """
    Parameters
    ----------
    instance : str
        A regular expression. Instances whose name it matches are considered
        for replacement.
    replace_with : str
        The cell every matched instance is replaced with. It must have the same
        terminals as the cell being replaced, otherwise the step fails.
    current_cell : str | None
        If set, only instances of this cell are matched.
    """

    instance: str
    replace_with: str
    current_cell: str | None = None


@Step.factory.register()
class ReplaceECOCells(OdbpyStep):
    """
    Experimental step to replace the cell of matching instances after global or
    detailed routing, e.g. to swap a buffer type or resize a cell. The placement
    is legalized and global routing is incrementally re-run for affected nets.

    If run after detailed routing, detailed routing must be re-run as affected
    nets that are altered are removed and require re-routing.

    A rule that matches no instance is an error: an ECO that silently does
    nothing is worse than one that fails.
    """

    id = "Odb.ReplaceECOCells"
    name = "Replace ECO Cells"

    class Config(GrtConfig, DplConfig, OdbpyStep.Config):
        REPLACE_ECO_CELLS: Optional[list[ECOCellReplacement]] = variable(
            None,
            description="List of cell replacements to perform",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "eco_replace_cell.py")

    def get_command(self) -> list[str]:
        assert self.config_path is not None, "get_command called before start()"
        return super().get_command() + [
            "--step-config",
            os.fspath(self.config_path),
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.REPLACE_ECO_CELLS is None:
            logger.info(f"'REPLACE_ECO_CELLS' not set. Skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)


@dataclass
class ECODiode:
    """
    Parameters
    ----------
    target : str
        The sink whose net gets a diode connected, in the format
        instance_name/pin_name.
    placement : tuple[Decimal, Decimal] | None
        The coarse placement for this diode (to be legalized.)
        If unset, the diode is placed at the same location as the target
        instance, with legalization later moving it to a valid location.
    """

    target: str
    placement: tuple[Decimal, Decimal] | None = None


@Step.factory.register()
class InsertECODiodes(OdbpyStep):
    """
    Experimental step to create and attach ECO diodes to the nets of sinks after
    global or detailed routing. The placement is legalized and global routing is
    incrementally re-run for affected nets. Useful for manually fixing some
    antenna violations.

    If run after detailed routing, detailed routing must be re-run as affected
    nets that are altered are removed and require re-routing.
    """

    id = "Odb.InsertECODiodes"
    name = "Insert ECO Diodes"

    class Config(DplConfig, GrtConfig, OdbpyStep.Config):
        INSERT_ECO_DIODES: Optional[list[ECODiode]] = variable(
            None,
            description="List of sinks to insert diodes for.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "odbpy", "eco_diode.py")

    def get_command(self) -> list[str]:
        assert self.config_path is not None, "get_command called before start()"
        return super().get_command() + [
            "--step-config",
            os.fspath(self.config_path),
        ]

    def run(self, state_in: State, **kwargs):
        if self.config.DIODE_CELL is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}
        if self.config.INSERT_ECO_DIODES is None:
            logger.info(f"'INSERT_ECO_DIODES' not set. Skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)
