"""OpenDB-backed implementation steps."""

from librelane.steps.odb.base import OdbpyStep, inf_rx
from librelane.steps.odb.reports import (
    CheckMacroAntennaProperties,
    CheckDesignAntennaProperties,
    ReportWireLength,
    ReportDisconnectedPins,
    CellFrequencyTables,
)
from librelane.steps.odb.placement import (
    ManualMacroPlacement,
    CustomIOPlacement,
    ManualGlobalPlacement,
    _migrate_unmatched_io,
)
from librelane.steps.odb.obstructions import (
    AddRoutingObstructions,
    RemoveRoutingObstructions,
    AddPDNObstructions,
    RemovePDNObstructions,
)
from librelane.steps.odb.power import SetPowerConnections, WriteVerilogHeader
from librelane.steps.odb.diodes import (
    PortDiodePlacement,
    DiodesOnPorts,
    FuzzyDiodePlacement,
    HeuristicDiodeInsertion,
)
from librelane.steps.odb.eco import (
    ECOBuffer,
    InsertECOBuffers,
    ECOCellReplacement,
    ReplaceECOCells,
    ECODiode,
    InsertECODiodes,
)
from librelane.steps.odb.physical import ApplyDEFTemplate

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
    ECOCellReplacement,
    ReplaceECOCells,
    ECODiode,
    InsertECODiodes,
    ApplyDEFTemplate,
]
for _class in _REEXPORTED_CLASSES:
    _class.__module__ = __name__
del _class
