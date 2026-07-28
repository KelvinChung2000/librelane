"""OpenDB-backed implementation steps."""

from .base import OdbpyStep, inf_rx
from .reports import (
    CheckMacroAntennaProperties,
    CheckDesignAntennaProperties,
    ReportWireLength,
    ReportDisconnectedPins,
    CellFrequencyTables,
)
from .placement import (
    ManualMacroPlacement,
    CustomIOPlacement,
    ManualGlobalPlacement,
    _migrate_unmatched_io,
)
from .obstructions import (
    AddRoutingObstructions,
    RemoveRoutingObstructions,
    AddPDNObstructions,
    RemovePDNObstructions,
)
from .power import SetPowerConnections, WriteVerilogHeader
from .diodes import (
    PortDiodePlacement,
    DiodesOnPorts,
    FuzzyDiodePlacement,
    HeuristicDiodeInsertion,
)
from .eco import ECOBuffer, InsertECOBuffers, ECODiode, InsertECODiodes
from .physical import ApplyDEFTemplate

_REEXPORTED_CLASSES = [
    OdbpyStep,
    CheckMacroAntennaProperties,
    CheckDesignAntennaProperties,
    ReportWireLength,
    ReportDisconnectedPins,
    CellFrequencyTables,
    ManualMacroPlacement,
    CustomIOPlacement,
    ManualGlobalPlacement,
    AddRoutingObstructions,
    RemoveRoutingObstructions,
    AddPDNObstructions,
    RemovePDNObstructions,
    SetPowerConnections,
    WriteVerilogHeader,
    PortDiodePlacement,
    DiodesOnPorts,
    FuzzyDiodePlacement,
    HeuristicDiodeInsertion,
    ECOBuffer,
    InsertECOBuffers,
    ECODiode,
    InsertECODiodes,
    ApplyDEFTemplate,
]
for _class in _REEXPORTED_CLASSES:
    _class.__module__ = __name__
del _class
