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
# limitations under the License.
from loguru import logger

import os
import json
import re
import pathlib
from abc import abstractmethod
from base64 import b64encode
from dataclasses import dataclass
from decimal import Decimal
from math import inf
from typing import (
    ClassVar,
    Literal,
    Optional,
    Protocol,
    runtime_checkable,
)


from librelane.common import (
    Path,
    Filter,
    TclUtils,
    _get_process_limit,
    aggregate_metrics,
    process_list_file,
)
from librelane.config import variable
from librelane.config.flow import option_variables
from librelane.state import DesignFormat, State
from librelane.steps.step import (
    DefaultOutputProcessor,
    MetricsUpdate,
    OutputProcessor,
    Step,
    StepError,
    StepException,
    ViewsUpdate,
)
from librelane.steps.tclstep import TclStep

openroad_alert_rx = re.compile(r"^\[(WARNING|ERROR)(?:\s+([A-Z]+\-\d+))?\]\s*(.+)")


@dataclass
class OpenROADAlert:
    """
    Data structure encapsulating an alert (warning or error) from OpenROAD.
    """

    cls: Literal["warning", "error"]
    code: str | None
    message: str

    def __str__(self) -> str:
        code_prefix = ""
        if self.code is not None:
            code_prefix = f"[{self.code}] "
        return f"{code_prefix}{self.message}"


@runtime_checkable
class SupportsOpenROADAlerts(Protocol):
    """
    A listener for ``OpenROADOutputProcessor``. Fires whenever a line contains
    an alert.
    """

    def on_alert(self, alert: OpenROADAlert) -> OpenROADAlert:
        """
        Parameters
        ----------
        alert : OpenROADAlert
            The alert found in the processed line

        Returns
        -------
        OpenROADAlert
            The alert once again, modified at the step object's leisure
        """
        ...


class OpenROADOutputProcessor(OutputProcessor):
    """
    A special output processor for steps leveraging OpenROAD-based subprocesses.

    It captures `[ERROR]` and `[WARNING]` lines into a data structure where they
    can be further processed by the step itself rather than simply printed to
    the terminal.
    """

    key = "openroad_alerts"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.alerts: list[OpenROADAlert] = []
        if not isinstance(self.step, SupportsOpenROADAlerts):
            raise ValueError(
                "OpenROADOutputProcessor is only compatible with steps implementing the SupportsOpenROADAlerts protocol"
            )

    def process_line(self, line: str):
        """
        If a line contains an OpenROAD error/warning, it is processed and handed
        over to the step's ``on_alert`` method.

        Parameters
        ----------
        line : str
            The line in question

        Returns
        -------
        ``True`` if the line has alerts, ``False`` if the line has
        no alerts
        """
        if match := openroad_alert_rx.match(line):
            cls = match[1].lower()
            code = None
            if match[2] is not None:
                code = match[2]
            message = match[3]
            alert = OpenROADAlert(cls, code, message)  # type: ignore
            assert isinstance(self.step, SupportsOpenROADAlerts)
            alert = self.step.on_alert(alert)
            self.alerts.append(alert)

            return True  # munch
        return False  # pass on to next output processor

    def result(self) -> list[OpenROADAlert]:
        """
        Returns
        -------
        list[OpenROADAlert]
            A list of OpenROAD alerts captured by this output processor
        """
        return self.alerts


class OpenROADAlertMixin:
    """
    A mixin for steps invoking OpenROAD-based subprocesses, which routes
    ``[ERROR]``/``[WARNING]`` lines through :class:`OpenROADOutputProcessor`
    and echoes them to the logger.

    Attributes
    ----------
    ignored_alert_codes : ClassVar[frozenset[str]]
        Alert codes that are captured in :attr:`alerts`
        but not echoed to the logger, i.e., known-harmless noise.
    alerts : list[OpenROADAlert] | None
        The alerts emitted by the last subprocess run, or ``None`` if
        no subprocess has been run yet.
    """

    id: str  # provided by Step

    ignored_alert_codes: ClassVar[frozenset[str]] = frozenset()

    output_processors = [OpenROADOutputProcessor, DefaultOutputProcessor]

    alerts: list[OpenROADAlert] | None = None

    def on_alert(self, alert: OpenROADAlert) -> OpenROADAlert:
        """
        Parameters
        ----------
        alert : OpenROADAlert
            The alert found by :class:`OpenROADOutputProcessor`

        Returns
        -------
        OpenROADAlert
            The alert, unmodified
        """
        if alert.code in self.ignored_alert_codes:
            return alert
        if alert.cls == "error":
            logger.bind(step=self.id, key=alert.code).error(str(alert))
        elif alert.cls == "warning":
            logger.bind(step=self.id, key=alert.code).warning(str(alert))
        return alert


EXAMPLE_INPUT = """
li1 X 0.23 0.46
li1 Y 0.17 0.34
met1 X 0.17 0.34
met1 Y 0.17 0.34
met2 X 0.23 0.46
met2 Y 0.23 0.46
met3 X 0.34 0.68
met3 Y 0.34 0.68
met4 X 0.46 0.92
met4 Y 0.46 0.92
met5 X 1.70 3.40
met5 Y 1.70 3.40
"""


def old_to_new_tracks(old_tracks: str) -> str:
    """
    >>> old_to_new_tracks(EXAMPLE_INPUT)
    'make_tracks li1 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.17 -y_pitch 0.34\\nmake_tracks met1 -x_offset 0.17 -x_pitch 0.34 -y_offset 0.17 -y_pitch 0.34\\nmake_tracks met2 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.23 -y_pitch 0.46\\nmake_tracks met3 -x_offset 0.34 -x_pitch 0.68 -y_offset 0.34 -y_pitch 0.68\\nmake_tracks met4 -x_offset 0.46 -x_pitch 0.92 -y_offset 0.46 -y_pitch 0.92\\nmake_tracks met5 -x_offset 1.70 -x_pitch 3.40 -y_offset 1.70 -y_pitch 3.40\\n'
    """
    layers: dict[str, dict[str, tuple[str, str]]] = {}

    for line in old_tracks.splitlines():
        if line.strip() == "":
            continue
        layer, cardinal, offset, pitch = line.split()
        layers[layer] = layers.get(layer) or {}
        layers[layer][cardinal] = (offset, pitch)

    final_str = ""
    for layer, data in layers.items():
        x_offset, x_pitch = data["X"]
        y_offset, y_pitch = data["Y"]
        final_str += f"make_tracks {layer} -x_offset {x_offset} -x_pitch {x_pitch} -y_offset {y_offset} -y_pitch {y_pitch}\n"

    return final_str


def pdn_macro_migrator(x):
    if not isinstance(x, str):
        return x
    if "," in x:
        return [el.strip() for el in x.split(",")]
    else:
        return [x.strip()]


DesignFormat(
    "odb",
    "odb",
    "OpenDB Database",
    alts=["ODB"],
).register()

DesignFormat(
    "openroad_lef",
    "openroad.lef",
    "Library Exchange Format Generated by OpenROAD",
    alts=["OPENROAD_LEF"],
    folder_override="lef",
).register()


@Step.factory.register()
class CheckSDCFiles(Step):
    """
    Checks that the two variables used for SDC files by OpenROAD steps,
    namely, ``PNR_SDC_FILE`` and ``SIGNOFF_SDC_FILE``, are explicitly set to
    valid paths by the users, and emits a warning that the fallback will be
    utilized otherwise.
    """

    id = "OpenROAD.CheckSDCFiles"
    name = "Check SDC Files"
    inputs = []
    outputs = []

    class Config(Step.Config):
        PNR_SDC_FILE: Optional[Path] = variable(
            None,
            description="Specifies the SDC file used during all implementation (PnR) steps",
        )

        SIGNOFF_SDC_FILE: Optional[Path] = variable(
            None,
            description="Specifies the SDC file for STA during signoff",
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        default_sdc_file = [
            var for var in option_variables if var.name == "FALLBACK_SDC"
        ][0]
        assert default_sdc_file is not None

        is_generic_fallback = default_sdc_file.default
        fallback_descriptor = "generic" if is_generic_fallback else "user-defined"
        if self.config.PNR_SDC_FILE is None:
            logger.bind(step=self.id).warning(
                f"'PNR_SDC_FILE' is not defined. Using {fallback_descriptor} fallback SDC for OpenROAD PnR steps."
            )
        if self.config.SIGNOFF_SDC_FILE is None:
            logger.bind(step=self.id).warning(
                f"'SIGNOFF_SDC_FILE' is not defined. Using {fallback_descriptor} fallback SDC for OpenROAD PnR steps."
            )
        return {}, {}


class OpenROADStep(OpenROADAlertMixin, TclStep):
    inputs = [DesignFormat.ODB]
    outputs = [
        DesignFormat.ODB,
        DesignFormat.DEF,
        DesignFormat.SDC,
        DesignFormat.NETLIST,
        DesignFormat.POWERED_NETLIST,
    ]

    ignored_alert_codes = frozenset(
        {
            "ORD-0039",  # .openroad ignored with -python
            "ODB-0220",  # lef parsing/NOWIREEXTENSIONATPIN statement is obsolete in version 5.6 or later.
            "STA-1256",  # table template \\w+ not found
            "DRT-0349",  # LEF58_ENCLOSURE with no CUTCLASS is not supported. Skipping for layer \\w+
        }
    )

    class Config(Step.Config):
        PNR_CORNERS: Optional[list[str]] = variable(
            None,
            description="A list of fully-qualified IPVT corners to use during PnR. If unspecified, the value for `STA_CORNERS` from the PDK will be used.",
            pdk=True,
        )

        SET_RC_VERBOSE: bool = variable(
            False,
            description="If set to true, set_rc commands are echoed. Quite noisy, but may be useful for debugging.",
        )

        LAYERS_RC: Optional[dict[str, dict[str, dict[str, Decimal]]]] = variable(
            None,
            description="Used during PNR steps, Specific custom resistance and capacitance values for metal layers."
            + " For each IPVT corner, a mapping for each metal layer is provided."
            + " Each mapping describes custom resistance and capacitance values."
            + " Usage of wildcards for specifying IPVT corners is allowed."
            + " `res` is in kOhm per um of wire and `cap` in pF per um of wire, whatever units the PDK's liberty files declare.",
            units="kΩ/µm, pF/µm",
            pdk=True,
        )

        VIAS_R: Optional[dict[str, dict[str, dict[str, Decimal]]]] = variable(
            None,
            description="Used during PNR steps, Specific custom resistance values for via layers."
            + " For each IPVT corner, a mapping for each via layer is provided."
            + " Each mapping describes custom resistance values."
            + " Usage of wildcards for specifying IPVT corners is allowed."
            + " `res` is in kOhm per cut/via, whatever units the PDK's liberty files declare.",
            units="kΩ",
            pdk=True,
        )

        SIGNAL_WIRE_RC_LAYERS: Optional[list[str]] = variable(
            None,
            description="Sets estimated signal wire RC values to the average of these layers'. If you provide more than two, the averages are grouped by preferred routing direction and you must provide at least one layer for each routing direction.",
            pdk=True,
            deprecated_names=[
                ("WIRE_RC_LAYER", lambda x: [x]),
                ("DATA_WIRE_RC_LAYER", lambda x: [x]),
            ],
        )

        CLOCK_WIRE_RC_LAYERS: Optional[list[str]] = variable(
            None,
            description="Sets estimated clock wire RC values to the average of these layers'. If you provide more than two, the averages are grouped by preferred routing direction and you must provide at least one layer for each routing direction.",
            pdk=True,
            deprecated_names=[("CLOCK_WIRE_RC_LAYER", lambda x: [x])],
        )

        PDN_CONNECT_MACROS_TO_GRID: bool = variable(
            True,
            description="Enables the connection of macros to the top level power grid.",
            deprecated_names=["FP_PDN_ENABLE_MACROS_GRID"],
        )

        PDN_MACRO_CONNECTIONS: Optional[list[str]] = variable(
            None,
            description="Specifies explicit power connections of internal macros to the top level power grid, in the format: regex matching macro instance names, power domain vdd and ground net names, and macro vdd and ground pin names `<instance_name_rx> <vdd_net> <gnd_net> <vdd_pin> <gnd_pin>`.",
            deprecated_names=[("FP_PDN_MACRO_HOOKS", pdn_macro_migrator)],
        )

        PDN_ENABLE_GLOBAL_CONNECTIONS: bool = variable(
            True,
            description="Enables the creation of global connections in PDN generation.",
            deprecated_names=["FP_PDN_ENABLE_GLOBAL_CONNECTIONS"],
        )

        PNR_SDC_FILE: Optional[Path] = variable(
            None,
            description="Specifies the SDC file used during all implementation (PnR) steps",
        )

        STA_EXTRA_CORNER_TCL_FILE: Optional[Path] = variable(
            None,
            description="Experimental: specifies a additional configuration .tcl file to be called during (PnR) steps.",
        )

        DEDUPLICATE_CORNERS: bool = variable(
            False,
            description="Cull duplicate IPVT corners during PNR, i.e. corners that share the same set of lib files and values for LAYERS_RC and VIAS_R as another corner are not considered outside of STA.",
        )

        OPENROAD_THREADS: Optional[int] = variable(
            None,
            description="The number of threads OpenROAD may use. If unset, this will be equal to the machine's thread count by default.",
            deprecated_names=["DRT_THREADS", "ROUTING_CORES"],
        )

    config: Config

    @classmethod
    def get_openroad_path(Self) -> str:
        return os.getenv("_LLN_OVERRIDE_OPENROAD", "openroad")

    @abstractmethod
    def get_script_path(self) -> str:
        pass

    def prepare_env(self, env: dict, state: State) -> dict:
        env = super().prepare_env(env, state)

        lib_list = self.toolbox.filter_views(self.config, self.config.LIB)
        lib_list += self.toolbox.get_macro_views(self.config, DesignFormat.LIB)

        env["_SDC_IN"] = self.config.PNR_SDC_FILE or self.config.FALLBACK_SDC
        env["_PNR_LIBS"] = TclStep.value_to_tcl(lib_list)
        env["_MACRO_LIBS"] = TclStep.value_to_tcl(
            self.toolbox.get_macro_views(self.config, DesignFormat.LIB)
        )
        excluded_cells: set[str] = set(self.config.EXTRA_EXCLUDED_CELLS or [])
        excluded_cells.update(process_list_file(self.config.PNR_EXCLUDED_CELL_FILE))
        env["_PNR_EXCLUDED_CELLS"] = TclUtils.join(excluded_cells)

        return env

    def run(self, state_in, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        """
        The `run()` override for the OpenROADStep class handles two things:

        1. Before the `super()` call: Process _LIB_CORNER_<i> for liberty/corner
        pairs.

        2. After the `super()` call: Processes the `or_metrics_out.json` file and
        updates the State's `metrics` property with any new metrics in that object.
        """
        self.alerts = None
        kwargs, env = self.extract_env(kwargs)
        env = self.prepare_env(env, state_in)

        corners: list[str] = self.config.PNR_CORNERS or [self.config.DEFAULT_CORNER]

        @dataclass
        class IPVTCorner:
            name: str
            libs: list[Path]
            layers_rc: dict[str, dict[str, Decimal]] | None
            vias_r: dict[str, dict[str, Decimal]] | None

            def __eq__(self, other):
                if not isinstance(other, IPVTCorner):
                    return False
                return (
                    self.libs == other.libs
                    and self.layers_rc == other.layers_rc
                    and self.vias_r == other.vias_r
                )

            def __hash__(self):
                return hash(
                    (
                        frozenset([str(lib) for lib in self.libs]),
                        TclStep.value_to_tcl(self.layers_rc),
                        TclStep.value_to_tcl(self.vias_r),
                    )
                )

        if "corners" in kwargs:
            corners = kwargs.pop("corners")
            logger.debug(f"Corners Override {corners}")

        count = 0
        ipvt_corners = {}
        for corner in corners:
            _, libs, _, _ = self.toolbox.get_timing_files_categorized(
                self.config, corner
            )
            ipvt_corners[corner] = IPVTCorner(corner, libs, None, None)
            # logger.debug(f"Liberty files for '{corner}' added: {libs}")
            count += 1

        check = False
        if "check" in kwargs:
            check = kwargs.pop("check")

        layers_rc = self.config.LAYERS_RC
        if layers_rc is not None:
            for corner_wildcard, metal_layers in layers_rc.items():
                for corner in Filter([corner_wildcard]).filter(corners):
                    ipvt_corners[corner].layers_rc = metal_layers

        vias_r = self.config.VIAS_R
        if vias_r is not None:
            for corner_wildcard, metal_layers in vias_r.items():
                for corner in Filter([corner_wildcard]).filter(corners):
                    ipvt_corners[corner].vias_r = metal_layers

        filtered_ipvt_corners_names_sorted = corners
        if self.config.DEDUPLICATE_CORNERS:
            filtered_ipvt_corners = {
                k: v
                for k, v in ipvt_corners.items()
                if k in [corner.name for corner in set(ipvt_corners.values())]
            }
            filtered_ipvt_corners_names_sorted = [
                x for _, x in sorted(zip(corners, filtered_ipvt_corners.keys()))
            ]
        count = 0
        for corner_name in filtered_ipvt_corners_names_sorted:
            corner_vias_r = ipvt_corners[corner_name].vias_r
            if corner_vias_r is not None:
                for via, rc in corner_vias_r.items():
                    res = rc["res"]
                    env[f"_VIA_R_{count}"] = TclStep.value_to_tcl(
                        [corner_name, via, res]
                    )
                    count += 1
        count = 0
        for corner_name in filtered_ipvt_corners_names_sorted:
            corner_layers_rc = ipvt_corners[corner_name].layers_rc
            if corner_layers_rc is not None:
                for layer, rc in corner_layers_rc.items():
                    res = rc["res"]
                    cap = rc["cap"]
                    env[f"_LAYER_RC_{count}"] = TclStep.value_to_tcl(
                        [corner_name, layer, res, cap]
                    )
                    count += 1

        count = 0
        for corner_name in filtered_ipvt_corners_names_sorted:
            env[f"_LIB_CORNER_{count}"] = TclStep.value_to_tcl(
                [corner_name] + ipvt_corners[corner_name].libs
            )
            count += 1

        command = self.get_command()

        subprocess_result = self.run_subprocess(
            command,
            env=env,
            check=check,
            **kwargs,
        )

        generated_metrics = subprocess_result["generated_metrics"]

        views_updates: ViewsUpdate = {}
        for output in self.outputs:
            if output.multiple:
                # Too step-specific.
                continue
            path = pathlib.Path(env[f"SAVE_{output.id.upper()}"])
            if not path.exists():
                continue
            views_updates[output] = path

        # 1. Parse warnings and errors
        self.alerts = subprocess_result.get("openroad_alerts") or []
        if subprocess_result["returncode"] != 0:
            error_strings = [
                str(alert) for alert in self.alerts if alert.cls == "error"
            ]
            if len(error_strings):
                error_string = "\n".join(error_strings)
                raise StepError(
                    f"{self.id} failed with the following errors:\n{error_string}"
                )
            else:
                step_exception_message = f"{self.id} failed with an unexpected error."
                log_path = self.get_log_path()
                if os.path.isfile(log_path):
                    step_exception_message += f" Please check {repr(os.path.relpath(log_path))} and unless you wrote the step yourself, file an issue.\n"
                    with open(log_path, "r", encoding="utf8") as f:
                        last_n_lines = f.readlines()[-10:]
                        step_exception_message += f"Last {len(last_n_lines)} lines:\n"
                        for line in last_n_lines:
                            step_exception_message += "\t" + line
                else:
                    step_exception_message += f" Please check the logs in {repr(self.step_dir)} and unless you wrote the step yourself, file an issue."
                raise StepException(step_exception_message)
        # 2. Metrics
        metrics_path = os.path.join(self.step_dir, "or_metrics_out.json")
        if os.path.exists(metrics_path):
            or_metrics_out = json.loads(open(metrics_path).read(), parse_float=Decimal)
            for key, value in or_metrics_out.items():
                if value == "Infinity":
                    or_metrics_out[key] = inf
                elif value == "-Infinity":
                    or_metrics_out[key] = -inf
            generated_metrics.update(or_metrics_out)

        metric_updates_with_aggregates = aggregate_metrics(generated_metrics)

        return views_updates, metric_updates_with_aggregates

    def get_command(self) -> list[str]:
        metrics_path = os.path.join(self.step_dir, "or_metrics_out.json")
        threads = str(self.config.OPENROAD_THREADS or _get_process_limit())
        logger.log("VERBOSE", f"OpenROAD will use {threads} threads")
        return [
            self.get_openroad_path(),
            ("-gui" if os.getenv("_OPENROAD_GUI", "0") == "1" else "-exit"),
            "-threads",
            threads,
            "-no_splash",
            "-metrics",
            metrics_path,
            self.get_script_path(),
        ]

    def layout_preview(self) -> str | None:
        if self.state_out is None:
            return None

        state_in = self.state_in.result()
        if self.state_out.get("def") == state_in.get("def"):
            return None

        if image := self.toolbox.render_png(self.config, self.state_out):
            image_encoded = b64encode(image).decode("utf8")
            return f'<img src="data:image/png;base64,{image_encoded}" />'

        return None
