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
from decimal import Decimal
from typing import Literal, Optional

from ...config import Variable
from ...state import State

from ..openroad import DetailedPlacement, GlobalRouting
from ..step import (
    CompositeStep,
    MetricsUpdate,
    Step,
    ViewsUpdate,
)

from .base import OdbpyStep


@Step.factory.register()
class PortDiodePlacement(OdbpyStep):
    """
    Unconditionally inserts diodes on design ports diodes on ports,
    to mitigate the `antenna effect <https://en.wikipedia.org/wiki/Antenna_effect>`_.

    Useful for hardening macros, where ports may get long wires that are
    unaccounted for when hardening a top-level chip.

    The placement is **not legalized**.
    """

    id = "Odb.PortDiodePlacement"
    name = "Port Diode Placement Script"

    config_vars = [
        Variable(
            "DIODE_ON_PORTS",
            Literal["none", "in", "out", "both"],
            "Always insert diodes on ports with the specified polarities.",
            default="none",
        ),
        Variable(
            "GPL_CELL_PADDING",
            int,
            "Cell padding value (in sites) for global placement. Used by this step only to emit a warning if it's 0.",
            units="sites",
            pdk=True,
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath("scripts", "odbpy", "diodes.py")

    def get_subcommand(self) -> list[str]:
        return ["place"]

    def get_command(self) -> list[str]:
        cell, pin = self.config["DIODE_CELL"].split("/")

        return super().get_command() + [
            "--diode-cell",
            cell,
            "--diode-pin",
            pin,
            "--port-protect",
            self.config["DIODE_ON_PORTS"],
            "--threshold",
            "Infinity",
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config["DIODE_ON_PORTS"] == "none":
            logger.info(f"'DIODE_ON_PORTS' is set to 'none': skipping '{self.id}'…")
            return {}, {}

        if self.config["DIODE_CELL"] is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}

        if self.config["GPL_CELL_PADDING"] == 0:
            logger.bind(step=self.id).warning(
                "'GPL_CELL_PADDING' is set to 0. This step may cause overlap failures."
            )

        return super().run(state_in, **kwargs)


@Step.factory.register()
class DiodesOnPorts(CompositeStep):
    """
    Unconditionally inserts diodes on design ports diodes on ports,
    to mitigate the `antenna effect <https://en.wikipedia.org/wiki/Antenna_effect>`_.

    Useful for hardening macros, where ports may get long wires that are
    unaccounted for when hardening a top-level chip.

    The placement is legalized by performing detailed placement and global
    routing after inserting the diodes.

    Prior to beta 16, this step did not legalize its placement: if you would
    like to retain the old behavior without legalization, try
    ``Odb.PortDiodePlacement``.
    """

    id = "Odb.DiodesOnPorts"
    name = "Diodes on Ports"
    long_name = "Diodes on Ports Protection Routine"

    Steps = [
        PortDiodePlacement,
        DetailedPlacement,
        GlobalRouting,
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config["DIODE_ON_PORTS"] == "none":
            logger.info(f"'DIODE_ON_PORTS' is set to 'none': skipping '{self.id}'…")
            return {}, {}
        if self.config["DIODE_CELL"] is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}
        return super().run(state_in, **kwargs)


@Step.factory.register()
class FuzzyDiodePlacement(OdbpyStep):
    """
    Runs a custom diode placement script to mitigate the `antenna effect <https://en.wikipedia.org/wiki/Antenna_effect>`_.

    This script uses the `Manhattan length <https://en.wikipedia.org/wiki/Manhattan_distance>`_
    of a (non-existent) wire at the global placement stage, and places diodes
    if they exceed a certain threshold. This, however, requires some padding:
    `GPL_CELL_PADDING` and `DPL_CELL_PADDING` must be higher than 0 for this
    script to work reliably.

    The placement is *not* legalized.

    The original script was written by `Sylvain "tnt" Munaut <https://github.com/smunaut>`_.
    """

    id = "Odb.FuzzyDiodePlacement"
    name = "Fuzzy Diode Placement"

    config_vars = [
        Variable(
            "HEURISTIC_ANTENNA_THRESHOLD",
            Optional[Decimal],
            "A Manhattan distance above which a diode is recommended to be inserted by the heuristic inserter. If not specified, the heuristic algorithm.",
            units="µm",
            pdk=True,
        ),
        Variable(
            "GPL_CELL_PADDING",
            int,
            "Cell padding value (in sites) for global placement. Used by this step only to emit a warning if it's 0.",
            units="sites",
            pdk=True,
        ),
    ]

    def get_script_path(self):
        return package_path().joinpath("scripts", "odbpy", "diodes.py")

    def get_subcommand(self) -> list[str]:
        return ["place"]

    def get_command(self) -> list[str]:
        cell, pin = self.config["DIODE_CELL"].split("/")

        return super().get_command() + [
            "--diode-cell",
            cell,
            "--diode-pin",
            pin,
            "--threshold",
            str(self.config["HEURISTIC_ANTENNA_THRESHOLD"]),
        ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config["GPL_CELL_PADDING"] == 0:
            logger.bind(step=self.id).warning(
                "'GPL_CELL_PADDING' is set to 0. This step may cause overlap failures."
            )

        if self.config["DIODE_CELL"] is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}

        if self.config["HEURISTIC_ANTENNA_THRESHOLD"] is None:
            logger.info(f"'HEURISTIC_ANTENNA_THRESHOLD' not set. Skipping '{self.id}'…")
            return {}, {}

        return super().run(state_in, **kwargs)


@Step.factory.register()
class HeuristicDiodeInsertion(CompositeStep):
    """
    Runs a custom diode insertion routine to mitigate the `antenna effect <https://en.wikipedia.org/wiki/Antenna_effect>`_.

    This script uses the `Manhattan length <https://en.wikipedia.org/wiki/Manhattan_distance>`_
    of a (non-existent) wire at the global placement stage, and places diodes
    if they exceed a certain threshold. This, however, requires some padding:
    `GPL_CELL_PADDING` and `DPL_CELL_PADDING` must be higher than 0 for this
    script to work reliably.

    The placement is then legalized by performing detailed placement and global
    routing after inserting the diodes.

    The original script was written by `Sylvain "tnt" Munaut <https://github.com/smunaut>`_.

    Prior to beta 16, this step did not legalize its placement: if you would
    like to retain the old behavior without legalization, try
    ``Odb.FuzzyDiodePlacement``.
    """

    id = "Odb.HeuristicDiodeInsertion"
    name = "Heuristic Diode Insertion"
    long_name = "Heuristic Diode Insertion Routine"

    Steps = [
        FuzzyDiodePlacement,
        DetailedPlacement,
        GlobalRouting,
    ]

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config["DIODE_CELL"] is None:
            logger.info(f"'DIODE_CELL' not set. Skipping '{self.id}'…")
            return {}, {}
        if self.config["HEURISTIC_ANTENNA_THRESHOLD"] is None:
            logger.info(f"'HEURISTIC_ANTENNA_THRESHOLD' not set. Skipping '{self.id}'…")
            return {}, {}

        return super().run(state_in, **kwargs)
