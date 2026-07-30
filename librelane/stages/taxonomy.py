# Copyright 2026 LibreLane Contributors
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
The stage taxonomy.

Stage boundaries are derived from ``Classic.gating_config_vars``
(``librelane/flows/classic.py:245-287``), which contains 22 distinct ``RUN_*``
variables. Each is a place where users already demanded the ability to turn one
phase off independently, which makes it a place where they would plausibly want
to change tools or re-enter the flow. Fifteen of those variables become stage
gates here; the remaining seven gate one tool within a stage and stay
step-level.

``requires`` and ``provides`` values are literals, not computed. See the
implementation plan for how they were derived.
"""

from ..state import DesignFormat

from .stage import Stage, PNR_IN_PLACE_PROVIDES, PNR_IN_PLACE_REQUIRES

_NO_VIEWS: tuple[DesignFormat, ...] = ()


Stage(
    id="lint",
    full_name="RTL Linting",
    default_provider="verilator",
    requires=_NO_VIEWS,
    provides=_NO_VIEWS,
    metrics=(
        "design__lint_error__count",
        "design__lint_warning__count",
        "design__lint_timing_construct__count",
    ),
    gating_config_var="RUN_LINTER",
    optional=True,
).register()

Stage(
    id="synthesis",
    full_name="Synthesis",
    default_provider="yosys",
    requires=_NO_VIEWS,
    provides=(DesignFormat.nl,),
    metrics=(
        "design__instance_unmapped__count",
        "synthesis__check_error__count",
    ),
).register()

Stage(
    id="pre_pnr_sta",
    full_name="Pre-PnR Static Timing Analysis",
    default_provider="openroad",
    requires=(DesignFormat.nl,),
    # OpenROAD.STAPrePNR emits sdf and sdc; it does not re-emit the netlist,
    # which reaches floorplan from synthesis instead.
    provides=(DesignFormat.sdc,),
).register()

Stage(
    id="floorplan",
    full_name="Floorplanning",
    default_provider="openroad",
    requires=(DesignFormat.nl, DesignFormat.sdc),
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="macro_placement",
    full_name="Macro Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    # Odb.ManualMacroPlacement rewrites the layout only; nl and sdc pass
    # through untouched from floorplan.
    provides=(DesignFormat.def_,),
).register()

Stage(
    id="tapcell_insertion",
    full_name="Tap and Endcap Cell Insertion",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_TAP_ENDCAP_INSERTION",
    optional=True,
).register()

Stage(
    id="power_grid",
    full_name="Power Distribution Network Generation",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    metrics=("design__power_grid_violation__count",),
).register()

Stage(
    id="io_placement",
    full_name="I/O Pin Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="global_placement",
    full_name="Global Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="post_gpl_repair",
    full_name="Post-Global-Placement Design Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GPL_DESIGN_REPAIR",
    optional=True,
).register()

Stage(
    id="detailed_placement",
    full_name="Detailed Placement",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
).register()

Stage(
    id="cts",
    full_name="Clock Tree Synthesis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_CTS",
    optional=True,
).register()

Stage(
    id="post_cts_opt",
    full_name="Post-CTS Timing Optimization",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_CTS_RESIZER_TIMING",
    optional=True,
).register()

Stage(
    id="global_routing",
    full_name="Global Routing",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    # OpenROAD.GlobalRouting overrides OpenROADStep.outputs down to odb and
    # def; it does not re-emit nl or sdc.
    provides=(DesignFormat.def_,),
).register()

Stage(
    id="post_grt_repair",
    full_name="Post-Global-Routing Design Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GRT_DESIGN_REPAIR",
    optional=True,
).register()

Stage(
    id="antenna_repair",
    full_name="Antenna Violation Repair",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_ANTENNA_REPAIR",
    optional=True,
).register()

Stage(
    id="post_grt_opt",
    full_name="Post-Global-Routing Timing Optimization",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_POST_GRT_RESIZER_TIMING",
    optional=True,
).register()

Stage(
    id="detailed_routing",
    full_name="Detailed Routing",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    metrics=("route__drc_errors",),
    gating_config_var="RUN_DRT",
    optional=True,
).register()

Stage(
    id="post_route_opt",
    full_name="Post-Route Optimization",
    default_provider=None,
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    optional=True,
).register()

Stage(
    id="fill_insertion",
    full_name="Fill Cell Insertion",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=PNR_IN_PLACE_PROVIDES,
    gating_config_var="RUN_FILL_INSERTION",
    optional=True,
).register()

Stage(
    id="extraction",
    full_name="Parasitics Extraction",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES,
    provides=(DesignFormat.spef,),
    gating_config_var="RUN_SPEF_EXTRACTION",
    optional=True,
).register()

Stage(
    id="signoff_sta",
    full_name="Signoff Static Timing Analysis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES + (DesignFormat.spef,),
    provides=_NO_VIEWS,
    metrics=(
        "timing__setup_vio__count",
        "timing__hold_vio__count",
        "design__max_slew_violation__count",
        "design__max_cap_violation__count",
    ),
    gating_config_var="RUN_MCSTA",
    optional=True,
).register()

Stage(
    id="ir_drop",
    full_name="IR Drop Analysis",
    default_provider="openroad",
    requires=PNR_IN_PLACE_REQUIRES + (DesignFormat.spef,),
    provides=_NO_VIEWS,
    gating_config_var="RUN_IRDROP_REPORT",
    optional=True,
).register()

Stage(
    id="streamout",
    full_name="Layout Stream-Out",
    default_provider=("magic", "klayout"),
    requires=PNR_IN_PLACE_REQUIRES,
    provides=(DesignFormat.gds,),
    multi_provider=True,
).register()

Stage(
    id="drc",
    full_name="Design Rule Checking",
    default_provider=("magic", "klayout"),
    # Magic.DRC reads the DEF alongside the stream; KLayout.DRC needs only gds.
    requires=(DesignFormat.def_, DesignFormat.gds),
    provides=_NO_VIEWS,
    multi_provider=True,
).register()

Stage(
    id="lvs",
    full_name="Layout Versus Schematic",
    default_provider="netgen",
    # The schematic side of the comparison is the powered netlist, not the
    # plain one; Magic.SpiceExtraction additionally reads the DEF.
    requires=(DesignFormat.def_, DesignFormat.gds, DesignFormat.pnl),
    provides=_NO_VIEWS,
    metrics=("design__lvs_error__count",),
    gating_config_var="RUN_LVS",
    optional=True,
).register()

Stage(
    id="formal_equivalence",
    full_name="Formal Equivalence Checking",
    default_provider="yosys",
    requires=(DesignFormat.nl,),
    provides=_NO_VIEWS,
    gating_config_var="RUN_EQY",
    optional=True,
).register()


#: The canonical reference order of every stage, and the order a ``StagedFlow``
#: is expected to declare its own stages in. A flow may omit stages and may
#: interleave plain steps. Nothing enforces the order itself: ``resolve()``
#: expands a ``Stages`` list exactly as written, and two stages swapped relative
#: to each other are caught only if the swap strands a view consumer, which the
#: view preflight then reports.
STAGE_ORDER: tuple[str, ...] = (
    "lint",
    "synthesis",
    "pre_pnr_sta",
    "floorplan",
    "macro_placement",
    "tapcell_insertion",
    "power_grid",
    "io_placement",
    "global_placement",
    "post_gpl_repair",
    "detailed_placement",
    "cts",
    "post_cts_opt",
    "global_routing",
    "post_grt_repair",
    "antenna_repair",
    "post_grt_opt",
    "detailed_routing",
    "post_route_opt",
    "fill_insertion",
    "extraction",
    "signoff_sta",
    "ir_drop",
    "streamout",
    "drc",
    "lvs",
    "formal_equivalence",
)
