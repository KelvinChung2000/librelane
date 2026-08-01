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

from importlib.resources import files
import os
import re
import shutil
import sys
import pathlib
from os.path import abspath
from decimal import Decimal
from abc import abstractmethod
from typing import Any, Literal, Optional

from librelane.steps.step import (
    DefaultOutputProcessor,
    MetricGate,
    OutputProcessor,
    StepError,
    StepException,
    ViewsUpdate,
    MetricsUpdate,
    Step,
)
from librelane.steps.tclstep import TclStep
from librelane.state import DesignFormat, State

from librelane.config import variable
from librelane.common import DRC as DRCObject, Path, mkdirp, count_occurences


DesignFormat(
    "mag",
    "mag",
    "Magic VLSI View",
    alts=["MAG"],
).register()


DesignFormat(
    "mag_gds",
    "magic.gds",
    "GDSII Stream (Magic)",
    alts=["MAG_GDS"],
).register()


class MagicOutputProcessor(OutputProcessor):
    _error_patterns = [
        re.compile(rx)
        for rx in [
            r"DEF read.*\(Error\).*",
            r"LEF read.*\(Error\).*",
            r"Error while reading cell(?!.*Warning:).*",
            r".*Calma output error.*",
            r".*is an abstract view.*",
        ]
    ]

    key = "magic_output"

    def __init__(self, step: Step, report_dir: str, silent: bool) -> None:
        super().__init__(step, report_dir, silent)
        self.fatal_error_count = 0

    def process_line(self, line: str) -> bool:
        for pattern in self._error_patterns:
            if pattern.match(line):
                self.fatal_error_count += 1
                logger.bind(step=self.step.id).error(line)
                return True
        return False

    def result(self) -> Any:
        return {"fatal_error_count": self.fatal_error_count}


class MagicStep(TclStep):
    inputs = [DesignFormat.GDS]
    outputs = []

    output_processors = [MagicOutputProcessor, DefaultOutputProcessor]

    class Config(Step.Config):
        MAGIC_DEF_LABELS: bool = variable(
            False,
            description="A flag to choose whether labels are read with DEF files or not. From magic docs: \"The '-labels' option to the 'def read' command causes each net in the NETS and SPECIALNETS sections of the DEF file to be annotated with a label having the net name as the label text.\" If LVS fails, try disabling this option.",
        )

        MAGIC_GDS_POLYGON_SUBCELLS: bool = variable(
            False,
            description='A flag to enable polygon subcells in magic for gds read potentially speeding up magic. From magic docs: "Put non-Manhattan polygons. This prevents interations with other polygons on the same plane and so reduces tile splitting."',
        )

        MAGIC_GDS_MERGE: bool = variable(
            True,
            description='A flag to enable merging of connected tiles into polygons during gds write. From magic docs: "Depending on the tile geometry, this may make the output file up to four times smaller, at the cost of speed in generating the output file."',
        )

        MAGIC_DEF_NO_BLOCKAGES: bool = variable(
            True,
            description="If set to true, blockages in DEF files are ignored. Otherwise, they are read as sheets of metal by Magic.",
        )

        MAGIC_INCLUDE_GDS_POINTERS: bool = variable(
            False,
            description="A flag to choose whether to include GDS pointers in the generated mag files or not.",
        )

        MAGICRC: Path = variable(
            description="A path to the `.magicrc` file which is sourced before running magic in the flow.",
            deprecated_names=["MAGIC_MAGICRC"],
            pdk=True,
        )

        MAGIC_TECH: Path = variable(
            description="A path to a Magic tech file which, mainly, has DRC rules.",
            deprecated_names=["MAGIC_TECH_FILE"],
            pdk=True,
        )

        MAGIC_PDK_SETUP: Path = variable(
            description="A path to a PDK-specific setup file sourced by `.magicrc`.",
            pdk=True,
        )

        CELL_MAGS: Optional[list[Path]] = variable(
            None,
            description="A list of pre-processed concrete views for cells. Read as a fallback for undefined cells.",
            pdk=True,
        )

        CELL_MAGLEFS: Optional[list[Path]] = variable(
            None,
            description="A list of pre-processed abstract LEF views for cells. Read as a fallback for undefined cells in scripts where cells are black-boxed.",
            pdk=True,
        )

        MAGIC_CAPTURE_ERRORS: bool = variable(
            True,
            description="Capture errors print by Magic and quit when a fatal error is encountered."
            + " Fatal errors are determined heuristically. It is not guaranteed that they are fatal errors."
            + " Hence this is function is gated by a variable."
            + " This function is needed because Magic does not throw errors.",
        )

    config: Config

    @abstractmethod
    def get_script_path(self) -> str:
        pass

    def get_command(self) -> list[str]:
        return [
            "magic",
            "-dnull",
            "-noconsole",
            "-rcfile",
            str(self.config.MAGICRC),
            str(files("librelane").joinpath("scripts", "magic", "wrapper.tcl")),
        ]

    def prepare_env(self, env: dict, state: State) -> dict:
        env = super().prepare_env(env, state)

        env["_MAGIC_SCRIPT"] = self.get_script_path()
        env["MACRO_GDS_FILES"] = ""
        for gds in self.toolbox.get_macro_views(self.config, DesignFormat.GDS):
            env["MACRO_GDS_FILES"] += f" {gds}"

        return env

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env = self.prepare_env(env, state_in)

        check = False
        if "check" in kwargs:
            check = kwargs.pop("check")

        command = self.get_command()

        subprocess_result = self.run_subprocess(
            command,
            env=env,
            check=check,
            **kwargs,
        )

        if (
            self.config.MAGIC_CAPTURE_ERRORS
            and subprocess_result["magic_output"]["fatal_error_count"]
        ):
            raise StepError("Encountered one or more fatal errors while running Magic.")

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

        return views_updates, generated_metrics


@Step.factory.register()
class WriteLEF(MagicStep):
    """
    Writes a LEF view of the design using the GDS using Magic.
    """

    id = "Magic.WriteLEF"
    name = "Write LEF (Magic)"

    inputs = [DesignFormat.GDS, DesignFormat.DEF]
    outputs = [DesignFormat.LEF]

    class Config(MagicStep.Config):
        MAGIC_LEF_WRITE_USE_GDS: bool = variable(
            False,
            description="A flag to choose whether to use GDS for LEF writing. If not, then the extraction will be done using abstract LEF views.",
        )

        MAGIC_WRITE_FULL_LEF: bool = variable(
            False,
            description="A flag to specify whether or not the output LEF should include all shapes inside the macro or an abstracted view of the macro LEF view via magic.",
        )

        MAGIC_WRITE_LEF_PINONLY: bool = variable(
            True,
            description="If true, the LEF write will mark only areas that are port labels as pins, while marking the rest of each related net as an obstruction. Otherwise, the labeled port and the any connected metal on the same layer are marked as a pin, which makes the LEF pin larger than the pin declared in the DEF.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "lef.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env["MAGTYPE"] = "mag"
        return super().run(state_in, **kwargs)


@Step.factory.register()
class StreamOut(MagicStep):
    """
    Converts DEF views into GDSII streams using Magic.

    If ``PRIMARY_GDSII_STREAMOUT_TOOL`` is set to ``"magic"``, both GDS and MAG_GDS
    will be updated, and if set to another tool, only ``MAG_GDS`` will be
    updated.
    """

    id = "Magic.StreamOut"
    name = "GDSII Stream Out (Magic)"

    inputs = [DesignFormat.DEF]
    outputs = [DesignFormat.GDS, DesignFormat.MAG_GDS, DesignFormat.MAG]

    class Config(MagicStep.Config):
        DIE_AREA: Optional[tuple[Decimal, Decimal, Decimal, Decimal]] = variable(
            None,
            description='Specific die area to be used in floorplanning when `FP_SIZING` is set to `absolute`. Specified as a 4-corner rectangle "x0 y0 x1 y1".',
            units="µm",
        )

        MAGIC_ZEROIZE_ORIGIN: bool = variable(
            False,
            description="A flag to move the layout such that it's origin in the lef generated by magic is 0,0.",
        )

        MAGIC_DISABLE_CIF_INFO: bool = variable(
            True,
            description="A flag to disable writing Caltech Intermediate Format (CIF) hierarchy and subcell array information to the GDSII file.",
            deprecated_names=["MAGIC_DISABLE_HIER_GDS"],
        )

        MAGIC_ADD_ISOSUB: bool = variable(
            False,
            description="Draws the isolated substrate (subcut) layer over the design's bounding box. Useful when the design is to be integrated into another design with multiple power domains. The PDK's Magic tech file must define an `isosub` layer.",
        )

        MAGIC_MACRO_STD_CELL_SOURCE: Literal["PDK", "macro"] = variable(
            "macro",
            description="If set to PDK, magic will use the PDK definition of the STD cells for macros inside the design."
            + " Otherwise, the macro is completely treated as a blackbox and magic will use the existing cell definition inside"
            + " the macro gds."
            + " This mode is only supported for macros specified in MACROS variable",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "def", "mag_gds.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        env = self.prepare_env(env, state_in)
        if die_area := state_in.metrics.get("design__die__bbox"):
            env["DIE_AREA"] = die_area

        env["MAGTYPE"] = "mag"

        if (
            self.config.MACROS is not None
            and self.config.MAGIC_MACRO_STD_CELL_SOURCE == "macro"
        ):
            macro_gds = []
            env_copy = env.copy()
            for macro in self.config.MACROS.keys():
                macro_gdses = [str(path) for path in self.config.MACROS[macro].gds]
                if len(macro_gdses) > 1:
                    raise StepException(
                        "Multiple GDSII files in one Macro currently unsupported when MAGIC_MACRO_STD_CELL_SOURCE is set to 'macro'."
                    )
                env_copy["_GDS_IN"] = macro_gdses[0]
                env_copy["_MACRO_NAME_IN"] = macro
                env_copy["_MAGIC_SCRIPT"] = files("librelane").joinpath(
                    "scripts", "magic", "get_bbox.tcl"
                )

                subprocess_result = super().run_subprocess(
                    self.get_command(),
                    env=env_copy,
                    log_to=os.path.join(self.step_dir, f"{macro}.get_bbox.log"),
                )
                generated_metrics = subprocess_result["generated_metrics"]

                if generated_metrics == {}:
                    raise StepError(
                        f"Failed to extract PR boundary from GDSII view of macro '{macro}'. Ensure that the GDSII view has a PR boundary layer."
                    )
                macro_gds.append([macro, macro_gdses, generated_metrics.values()])

            env["__MACRO_GDS"] = TclStep.value_to_tcl(macro_gds)

        views_updates, metrics_updates = super().run(
            state_in,
            env=env,
            **kwargs,
        )

        # The primary tool always writes the neutral view, overwriting a
        # non-primary tool's. A non-primary tool writes it only when nothing
        # has, so a flow running just one stream-out still produces a GDS
        # whatever the PDK names as primary.
        if (
            self.config.PRIMARY_GDSII_STREAMOUT_TOOL == "magic"
            or state_in.get_by_df(DesignFormat.GDS) is None
        ):
            magic_gds_out = str(views_updates[DesignFormat.MAG_GDS])
            gds_path = os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.gds")
            shutil.copy(magic_gds_out, gds_path)
            views_updates[DesignFormat.GDS] = pathlib.Path(gds_path)

        views_updates[DesignFormat.MAG] = pathlib.Path(
            os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.mag")
        )

        return views_updates, metrics_updates


@Step.factory.register()
class Filler(Step):
    """
    Generates the filler cells according to the design rules and adds them to the GDS.
    """

    id = "Magic.Filler"
    name = "Filler Generation"

    inputs = [DesignFormat.GDS]
    outputs = [DesignFormat.GDS]

    class Config(Step.Config):
        MAGIC_FILLER_SCRIPT: Optional[Path] = variable(
            None,
            description="Path to the magic filler script.",
            pdk=True,
        )

        MAGIC_FILLER_OPTIONS: Optional[list[str]] = variable(
            None,
            description="Options passed directly to the magic filler script.",
            pdk=True,
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        metrics_updates: MetricsUpdate = {}
        views_updates: ViewsUpdate = {}

        if not self.config.MAGIC_FILLER_SCRIPT:
            logger.bind(step=self.id).warning(
                f"MAGIC_FILLER_SCRIPT is unset. Magic.Filler may not be supported for the {self.config.PDK} PDK. This step will be skipped."
            )
            return views_updates, metrics_updates

        views_updates, metrics_updates = self.run_generic(state_in, **kwargs)

        return views_updates, metrics_updates

    def run_generic(
        self, state_in: State, **kwargs
    ) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}
        kwargs, env = self.extract_env(kwargs)

        input_gds = state_in[DesignFormat.GDS]
        assert isinstance(input_gds, pathlib.Path)

        fill_gds = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}_fill.{DesignFormat.GDS.extension}",
        )
        output_gds = os.path.join(
            self.step_dir, f"{self.config.DESIGN_NAME}.{DesignFormat.GDS.extension}"
        )

        filler_script = self.config.MAGIC_FILLER_SCRIPT
        if filler_script is None:
            raise StepException(
                "The PDK declares no 'MAGIC_FILLER_SCRIPT' to generate fill with."
            )
        script = abspath(filler_script)
        opts = self.config.MAGIC_FILLER_OPTIONS or []

        env["PDK_ROOT"] = self.config.PDK_ROOT
        env["PDK"] = self.config.PDK

        # Run filler generation
        self.run_subprocess(
            [
                sys.executable,
                script,
                input_gds,
                fill_gds,
                *opts,
            ],
            env=env,
        )

        # Combine fill and layout
        self.run_subprocess(
            [
                "klayout",
                "-b",
                "-zz",
                "-r",
                files("librelane").joinpath(
                    "scripts",
                    "klayout",
                    "insert_cell.py",
                ),
                "-rd",
                f"input={abspath(input_gds)}",
                "-rd",
                f"insert={abspath(fill_gds)}",
                "-rd",
                f"output={abspath(output_gds)}",
            ],
            env=env,
        )

        views_updates[DesignFormat.GDS] = pathlib.Path(output_gds)

        return views_updates, {}


@Step.factory.register()
class DRC(MagicStep):
    """
    Performs `design rule checking <https://en.wikipedia.org/wiki/Design_rule_checking>`_
    on the GDSII stream using Magic.

    This also converts the results to a KLayout database, which can be loaded.

    The metrics will be updated with ``magic__drc_error__count``. This step's
    ``gates`` raise if that number is nonzero.
    """

    id = "Magic.DRC"
    name = "DRC"
    long_name = "Design Rule Checks"

    inputs = [DesignFormat.DEF.mkOptional(), DesignFormat.GDS]
    outputs = []

    gates = (
        MetricGate(
            "magic__drc_error__count",
            "Magic DRC errors",
            error_on_var="ERROR_ON_MAGIC_DRC",
        ),
    )

    class Config(MagicStep.Config):
        ERROR_ON_MAGIC_DRC: bool = variable(
            True,
            description="Checks for DRC violations after magic DRC is executed and exits the flow if any was found.",
            deprecated_names=["QUIT_ON_MAGIC_DRC"],
        )

        MAGIC_DRC_USE_GDS: bool = variable(
            True,
            description="A flag to choose whether to run the Magic DRC checks on GDS or not. If not, then the checks will be done on the DEF view of the design, which is a bit faster, but may be less accurate as some DEF/LEF elements are abstract.",
        )

        MAGIC_GDS_FLATGLOB: Optional[list[str]] = variable(
            None,
            description="Flatten cells by name pattern on input. May be used to avoid false positive DRC errors. The strings may use standard shell-type glob patterns, with * for any length string match, ? for any single character match, \\ for special characters, and [] for matching character sets or ranges.",
        )

        MAGIC_DRC_MAGLEFS: Optional[list[Path]] = variable(
            None,
            description="A list of pre-processed abstract LEF views for cells. They are read in before the design and act as blackboxes during DRC.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "drc.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        reports_dir = os.path.join(self.step_dir, "reports")
        mkdirp(reports_dir)

        # Check that the DEF exists if needed
        if not self.config.MAGIC_DRC_USE_GDS:
            assert state_in.get(DesignFormat.DEF)

        views_updates, metrics_updates = super().run(state_in, **kwargs)

        report_path = os.path.join(reports_dir, "drc.magic.rpt")
        klayout_db_path = os.path.join(reports_dir, "drc.magic.lyrdb")

        # report_stats = os.stat(report_path)
        # drc_db_file = None
        # if report_stats.st_size >= 0:  # 134217728:
        #     drc_db_file = os.path.join(reports_dir, "drc.db")

        drc, bbox_count = DRCObject.from_magic(
            open(report_path, encoding="utf8"),
            # db_file=drc_db_file,
        )

        drc.to_klayout_xml(open(klayout_db_path, "wb"))

        metrics_updates["magic__drc_error__count"] = bbox_count

        return views_updates, metrics_updates


@Step.factory.register()
class SpiceExtraction(MagicStep):
    """
    Extracts a SPICE netlist from the GDSII stream. Used in Layout vs. Schematic
    checks.

    Note that the resultant SPICE netlist is blackboxed, and *only* suitable for abstract LVS.
    If you want to perform a full parasitics extraction (RCX), you should use the Magic.RCX step.

    Also, the metrics will be updated with ``magic__illegal_overlap__count``.
    This step's ``gates`` raise if that number is nonzero.
    """

    id = "Magic.SpiceExtraction"
    name = "SPICE Extraction"
    long_name = "SPICE Model Extraction"

    inputs = [DesignFormat.GDS, DesignFormat.DEF]
    outputs = [DesignFormat.SPICE]

    gates = (
        MetricGate(
            "magic__illegal_overlap__count",
            "Magic illegal overlap errors",
            error_on_var="ERROR_ON_ILLEGAL_OVERLAPS",
        ),
    )

    class Config(MagicStep.Config):
        ERROR_ON_ILLEGAL_OVERLAPS: bool = variable(
            True,
            description="Checks for illegal overlaps during Magic extraction. In some cases, these imply existing undetected shorts in the design. It raises an error at the end of the flow if so.",
            deprecated_names=["QUIT_ON_ILLEGAL_OVERLAPS"],
        )

        MAGIC_EXT_USE_GDS: bool = variable(
            False,
            description="A flag to choose whether to use GDS for spice extraction or not. If not, then the extraction will be done using the DEF/LEF, which is faster.",
        )

        MAGIC_EXT_ABSTRACT_CELLS: Optional[list[str]] = variable(
            None,
            description="A list of regular expressions which are matched against the cells of a "
            + "the design. Matches are abstracted (black-boxed) during SPICE extraction.",
        )

        MAGIC_EXT_UNIQUE: Literal["all", "notopports", "noports", "none"] = variable(
            "all",
            description='Runs `extract unique` with the specified option. The default is "all", and "none" disables `extract unique`, allowing connections between separate nets by label in LVS.',
            deprecated_names=[
                ("MAGIC_NO_EXT_UNIQUE", lambda o: "none" if o else "all"),
                ("LVS_CONNECT_BY_LABEL", lambda o: "none" if o else "all"),
            ],
        )

        MAGIC_EXT_SHORT_RESISTOR: bool = variable(
            False,
            description="Enables adding resistors to shorts- resolves LVS issues if more than one top-level pin is connected to the same net, but may increase runtime and break some designs. Proceed with caution.",
        )

        MAGIC_EXT_ABSTRACT: bool = variable(
            False,
            description="Extracts a SPICE netlist based on black-boxed standard cells and macros (basically, anything with a LEF) rather than transistors. An error will be thrown if both this and `MAGIC_EXT_USE_GDS` is set to ``True``.",
        )

        MAGIC_FEEDBACK_CONVERSION_THRESHOLD: int = variable(
            10000,
            description="If Magic provides more feedback items than this threshold, conversion to KLayout databases is skipped (as something has gone horribly wrong.)",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "extract_spice.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        if self.config.MAGIC_EXT_USE_GDS and self.config.MAGIC_EXT_ABSTRACT:
            raise StepException(
                "'MAGIC_EXT_USE_GDS' and 'MAGIC_EXT_ABSTRACT' cannot be both set to 'True'. The step cannot run."
            )

        kwargs, env = self.extract_env(kwargs)

        env["MAGTYPE"] = "maglef" if self.config.MAGIC_EXT_ABSTRACT else "mag"

        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)

        feedback_path = os.path.join(self.step_dir, "feedback.txt")
        with open(feedback_path, encoding="utf8") as f:
            illegal_overlap_count = count_occurences(f, "Illegal overlap")

        metrics_updates["magic__illegal_overlap__count"] = illegal_overlap_count
        threshold = self.config.MAGIC_FEEDBACK_CONVERSION_THRESHOLD
        if illegal_overlap_count > threshold:
            logger.warning(
                f"Not converting the feedback to the KLayout database format: {illegal_overlap_count} > MAGIC_FEEDBACK_CONVERSION_THRESHOLD ({threshold}). You may manually increase the threshold, but it might take forever."
            )
            return views_updates, metrics_updates

        cif_scale = Decimal(open(os.path.join(self.step_dir, "cif_scale.txt")).read())
        try:
            se_feedback, _ = DRCObject.from_magic_feedback(
                open(feedback_path, encoding="utf8"),
                cif_scale,
                self.config.DESIGN_NAME,
            )
            illegal_overlap_count = sum(
                len(v.bounding_boxes)
                for v in se_feedback.violations.values()
                if "Illegal overlap" in v.description
            )
            with open(os.path.join(self.step_dir, "feedback.xml"), "wb") as f:
                se_feedback.to_klayout_xml(f)
            metrics_updates["magic__illegal_overlap__count"] = illegal_overlap_count
        except ValueError as e:
            logger.bind(step=self.id).warning(
                f"Failed to convert SPICE extraction feedback to KLayout database format: {e}"
            )
        return views_updates, metrics_updates


@Step.factory.register()
class OpenGUI(MagicStep):
    """
    Opens the DEF view in the Magic GUI.
    """

    id = "Magic.OpenGUI"
    name = "Open In GUI"

    inputs = [DesignFormat.DEF]
    outputs = []

    class Config(MagicStep.Config):
        MAGIC_GUI_USE_GDS: bool = variable(
            True,
            description="Whether to prioritize GDS (if found) when running this step.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "open.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        env = self.prepare_env(env, state_in)
        env = self._reroute_env(env)

        if DesignFormat.GDS in state_in:
            env["CURRENT_GDS"] = self.value_to_tcl(state_in[DesignFormat.GDS])

        cmd = [
            "magic",
            "-rcfile",
            self.config.MAGICRC,
            self.get_script_path(),
        ]

        # Not run_subprocess- need stdin, stdout, stderr to be accessible to the
        # user normally
        self.run_interactive_subprocess(cmd, env=env)

        return {}, {}


@Step.factory.register()
class RCX(MagicStep):
    """
    Performs a full parasitics extraction (RCX) using Magic. This step is suitable for performing full
    analogue post-layout simulation of your design. The SPICE netlist will be flattened, and refer to the raw
    n-type/p-type transistor models for your PDK.

    If you want to do device level simulation *without* parasitics, this can be done in the
    Magic.SpiceExtraction step by setting `MAGIC_EXT_USE_GDS` to True and `MAGIC_EXT_ABSTRACT` to False.
    """

    id = "Magic.RCX"
    name = "RCX"
    long_name = "Full Parasitics Extraction"

    inputs = [DesignFormat.GDS]
    outputs = [DesignFormat.SPICE_RCX]

    class Config(MagicStep.Config):
        MAGIC_RCX_CTHRESH: float = variable(
            0.1,
            description="Capacitance threshold value.",
            units="femtofarads",
        )

        MAGIC_RCX_DO_CAPACITANCE: bool = variable(
            True,
            description="Whether to extract local capacitance values.",
        )

        MAGIC_RCX_DO_RESISTANCE: bool = variable(
            True,
            description="Whether to perform detailed (i.e. non-lumped) resistance extraction.",
        )

        MAGIC_RCX_EXTRACT_STYLE: str = variable(
            "ngspice()",
            description="Capacitance extraction corner. For open PDKs, the options are generally: 'ngspice(lrlc)', low resistance, low capacitance; 'ngspice(hrlc)', high resistance, low capacitance; 'ngspice(lrhc)', low resistance, high capacitance; 'ngspice(hrhc)', high resistance, low capacitance. 'ngspice(hrhc)' is typically the slowest corner, and 'ngspice(lrlc) is typically the fastest corner. Defaults to 'ngspice()', which is the default typical extraction corner.",
        )

    config: Config

    def get_script_path(self):
        return files("librelane").joinpath("scripts", "magic", "spice_rcx.tcl")

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)

        # always 'mag', since we'll never define the abstract setting like the original SpiceExtraction step
        # did
        env["MAGTYPE"] = "mag"

        views_updates, metrics_updates = super().run(state_in, env=env, **kwargs)

        return views_updates, metrics_updates
