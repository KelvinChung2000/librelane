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

from .step import (
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
from .tclstep import TclStep
from . import checker as Checker

# You'll notice some TclStep subclasses are exposed separately-
# this is for documentation.
from . import yosys as Yosys
from .yosys import YosysStep

from . import openroad as OpenROAD
from .openroad import (
    OpenROADAlert,
    OpenROADAlertMixin,
    OpenROADOutputProcessor,
    OpenROADStep,
    SupportsOpenROADAlerts,
)

from . import odb as Odb
from .odb import OdbpyStep, ECOBuffer, ECODiode

from . import magic as Magic
from .magic import MagicStep

from . import netgen as Netgen
from .netgen import NetgenStep

from . import klayout as KLayout
from . import misc as Misc
from . import verilator as Verilator

# Commercial ("vendor") CAD tool provider scaffolds. See librelane/steps/
# vendor.py for what these are (and are not): every step built on them
# raises NotImplementedError from run() until someone with access to the
# actual tool fills in the corresponding script or API calls.
from . import pt as PrimeTime
from .pt import PrimeTimeStep

from . import starrc as StarRC
from .starrc import StarRCStep

from . import icv as ICValidator
from .icv import ICValidatorStep

from . import fm as Formality
from .fm import FormalityStep

from . import vc_spyglass as VCSpyGlass
from .vc_spyglass import VCSpyGlassStep

from . import calibre as Calibre
from .calibre import CalibreStep

# Commercial ("vendor") tool scaffolds. Every step registers in Step.factory
# by being imported here, exactly like the open-source tool modules above;
# none of them is opted into any Stage by this module, which happens instead
# at the provider-registration layer.
from . import dc as DC
from .dc import DCStep

from . import fc as FC
from .fc import FCStep

from . import icc2 as ICC2
from .icc2 import ICC2Step

from . import genus as Genus
from .genus import GenusStep

from . import innovus as Innovus
from .innovus import InnovusStep

from . import tempus as Tempus
from .tempus import TempusStep

from . import quantus as Quantus
from .quantus import QuantusStep

from . import voltus as Voltus
from .voltus import VoltusStep

from . import pegasus as Pegasus
from .pegasus import PegasusStep

from . import conformal as Conformal
from .conformal import ConformalStep
