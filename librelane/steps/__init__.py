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
# limitations under the License.

"""
The Step Module
---------------

This modules includes various functions for importing and/or generating LibreLane
configuration objects. Configuration objects are the primary input to a flow.
"""

from librelane.steps.step import (
    StepError,
    DeferredStepError,
    StepException,
    StepNotFound,
    Step,
    OutputProcessor,
    DefaultOutputProcessor,
    MetricsUpdate,
    ViewsUpdate,
)
from librelane.steps.tclstep import TclStep
from librelane.steps import checker as Checker

# You'll notice some TclStep subclasses are exposed separately-
# this is for documentation.
from librelane.steps import yosys as Yosys
from librelane.steps.yosys import YosysStep

from librelane.steps import openroad as OpenROAD
from librelane.steps.openroad import (
    OpenROADAlert,
    OpenROADAlertMixin,
    OpenROADOutputProcessor,
    OpenROADStep,
    SupportsOpenROADAlerts,
)

from librelane.steps import odb as Odb
from librelane.steps.odb import OdbpyStep, ECOBuffer, ECOCellReplacement, ECODiode

from librelane.steps import magic as Magic
from librelane.steps.magic import MagicStep

from librelane.steps import netgen as Netgen
from librelane.steps.netgen import NetgenStep

from librelane.steps import klayout as KLayout
from librelane.steps import misc as Misc
from librelane.steps import verilator as Verilator

# Commercial ("vendor") CAD tool provider scaffolds. See librelane/steps/
# vendor.py for what these are (and are not): every step built on them
# raises NotImplementedError from run() until someone with access to the
# actual tool fills in the corresponding script or API calls.
from librelane.steps import pt as PrimeTime
from librelane.steps.pt import PrimeTimeStep

from librelane.steps import starrc as StarRC
from librelane.steps.starrc import StarRCStep

from librelane.steps import icv as ICValidator
from librelane.steps.icv import ICValidatorStep

from librelane.steps import fm as Formality
from librelane.steps.fm import FormalityStep

from librelane.steps import vc_spyglass as VCSpyGlass
from librelane.steps.vc_spyglass import VCSpyGlassStep

from librelane.steps import calibre as Calibre
from librelane.steps.calibre import CalibreStep

# Commercial ("vendor") tool scaffolds. Every step registers in Step.factory
# by being imported here, exactly like the open-source tool modules above;
# none of them is opted into any Job by this module, which happens instead
# at the provider-registration layer.
from librelane.steps import dc as DC
from librelane.steps.dc import DCStep

from librelane.steps import fc as FC
from librelane.steps.fc import FCStep

from librelane.steps import icc2 as ICC2
from librelane.steps.icc2 import ICC2Step

from librelane.steps import genus as Genus
from librelane.steps.genus import GenusStep

from librelane.steps import innovus as Innovus
from librelane.steps.innovus import InnovusStep

from librelane.steps import tempus as Tempus
from librelane.steps.tempus import TempusStep

from librelane.steps import quantus as Quantus
from librelane.steps.quantus import QuantusStep

from librelane.steps import voltus as Voltus
from librelane.steps.voltus import VoltusStep

from librelane.steps import pegasus as Pegasus
from librelane.steps.pegasus import PegasusStep

from librelane.steps import conformal as Conformal
from librelane.steps.conformal import ConformalStep
