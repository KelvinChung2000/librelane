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
from importlib.resources import files
import os
import sys
import shlex
import shutil
import subprocess
from os.path import abspath
from base64 import b64encode
from typing import Optional, Literal

from librelane.steps.step import ViewsUpdate, MetricsUpdate, Step

from librelane.config import variable
from librelane.state import DesignFormat, State
from librelane.common import Path

from librelane.steps.klayout.base import KLayoutStep


@Step.factory.register()
class Render(KLayoutStep):
    """
    Renders a PNG of the layout using KLayout.

    DEF is required as an input, but if a GDS-II view
    exists in the input state, it will be used instead.
    """

    id = "KLayout.Render"
    name = "Render Image (w/ KLayout)"

    inputs = [DesignFormat.DEF]
    outputs = []

    class Config(KLayoutStep.Config):
        KLAYOUT_RENDER_GRID_VISBLE: bool = variable(
            False,
            description="Render the grid in the image.",
        )

        KLAYOUT_RENDER_SHOW_RULER: bool = variable(
            False,
            description="Enable the ruler in the image.",
        )

        KLAYOUT_RENDER_BACKGROUND_COLOR: Literal["white", "black"] = variable(
            "white",
            description="The background color of the image.",
        )

        KLAYOUT_RENDER_TEXT_VISIBLE: bool = variable(
            False,
            description="Enable text in the image.",
        )

        KLAYOUT_RENDER_RESOLUTION: int = variable(
            1000,
            description="The horizontal resolution of the image in pixel.",
        )

        KLAYOUT_RENDER_OVERSAMPLING: int = variable(
            0,
            description="The oversampling factor (1..3), or 0 for disabling oversampling.",
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}

        input_view = state_in[DesignFormat.DEF]
        if gds := state_in.get(DesignFormat.GDS):
            input_view = gds

        assert isinstance(input_view, Path)

        klayout_render = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.KLAYOUT_RENDER.extension}",
        )

        self.run_pya_script(
            [
                sys.executable,
                files("librelane").joinpath("scripts", "klayout", "render.py"),
                abspath(input_view),
                "--output",
                abspath(klayout_render),
                "--grid-visible",
                self.config.KLAYOUT_RENDER_GRID_VISBLE,
                "--grid-show-ruler",
                self.config.KLAYOUT_RENDER_SHOW_RULER,
                "--text-visible",
                self.config.KLAYOUT_RENDER_TEXT_VISIBLE,
                "--background-color",
                self.config.KLAYOUT_RENDER_BACKGROUND_COLOR,
                "--resolution",
                self.config.KLAYOUT_RENDER_RESOLUTION,
                "--oversampling",
                self.config.KLAYOUT_RENDER_OVERSAMPLING,
            ]
            + self.get_cli_args(include_lefs=True),
            silent=True,
        )

        views_updates[DesignFormat.KLAYOUT_RENDER] = Path(klayout_render)

        return views_updates, {}


@Step.factory.register()
class StreamOut(KLayoutStep):
    """
    Converts DEF views into GDSII streams using KLayout.

    The PDK must support KLayout for this step to work, otherwise
    it will be skipped.

    If ``PRIMARY_GDSII_STREAMOUT_TOOL`` is set to ``"klayout"``, both GDS and KLAYOUT_GDS
    will be updated, and if set to another tool, only ``KLAYOUT_GDS`` will be
    updated.
    """

    id = "KLayout.StreamOut"
    name = "GDSII Stream Out (KLayout)"

    inputs = [DesignFormat.DEF]
    outputs = [DesignFormat.GDS, DesignFormat.KLAYOUT_GDS]

    class Config(KLayoutStep.Config):
        KLAYOUT_CONFLICT_RESOLUTION: Optional[
            Literal["AddToCell", "OverwriteCell", "RenameCell", "SkipNewCell"]
        ] = variable(
            "RenameCell",
            description="Specifies the conflict resolution if a cell name conflict arises.",
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        views_updates: ViewsUpdate = {}

        klayout_gds_out = os.path.join(
            self.step_dir,
            f"{self.config.DESIGN_NAME}.{DesignFormat.KLAYOUT_GDS.extension}",
        )
        kwargs, env = self.extract_env(kwargs)

        input_def = state_in[DesignFormat.DEF.id]
        assert isinstance(input_def, Path)

        conflict_resolution = self.config.KLAYOUT_CONFLICT_RESOLUTION
        assert conflict_resolution is not None, (
            "'KLAYOUT_CONFLICT_RESOLUTION' has no null behaviour to fall back on"
        )

        self.run_pya_script(
            [
                sys.executable,
                str(
                    files("librelane").joinpath(
                        "scripts",
                        "klayout",
                        "stream_out.py",
                    )
                ),
                str(input_def),
                "--output",
                abspath(klayout_gds_out),
                "--top",
                self.config.DESIGN_NAME,
                "--conflict-resolution",
                conflict_resolution,
            ]
            + self.get_cli_args(include_lefs=True, include_gds=True),
            env=env,
        )

        views_updates[DesignFormat.KLAYOUT_GDS] = Path(klayout_gds_out)

        if self.config.PRIMARY_GDSII_STREAMOUT_TOOL == "klayout":
            gds_path = os.path.join(self.step_dir, f"{self.config.DESIGN_NAME}.gds")
            shutil.copy(klayout_gds_out, gds_path)
            views_updates[DesignFormat.GDS] = Path(gds_path)

        return views_updates, {}

    def layout_preview(self) -> str | None:
        if self.state_out is None:
            return None
        assert self.toolbox is not None

        if image := self.toolbox.render_png(self.config, self.state_out):
            image_encoded = b64encode(image).decode("utf8")
            return f'<img src="data:image/png;base64,{image_encoded}" />'

        return None


@Step.factory.register()
class OpenGUI(KLayoutStep):
    """
    Opens the DEF view in the KLayout GUI, with layers loaded and mapped
    properly. Useful to inspect ``.klayout.xml`` database files and the like.
    """

    id = "KLayout.OpenGUI"
    name = "Open In GUI"

    inputs = [DesignFormat.DEF]
    outputs = []

    class Config(KLayoutStep.Config):
        KLAYOUT_EDITOR_MODE: bool = variable(
            False,
            description="Whether to run the KLayout GUI in editor mode or in viewer mode.",
        )

        KLAYOUT_GUI_USE_GDS: bool = variable(
            True,
            description="Whether to prioritize GDS (if found) when running this step.",
            deprecated_names=["KLAYOUT_PRIORITIZE_GDS"],
        )

    config: Config

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        mode_args = []
        if self.config.KLAYOUT_EDITOR_MODE:
            mode_args.append("--editor")

        layout = state_in[DesignFormat.DEF]
        if self.config.KLAYOUT_GUI_USE_GDS:
            if gds := state_in.get(DesignFormat.GDS):
                layout = gds
        assert isinstance(layout, Path)

        env["KLAYOUT_ARGV"] = shlex.join(
            [
                abspath(layout),
            ]
            + self.get_cli_args(include_lefs=True)
        )

        cmd = (
            [
                shutil.which("klayout") or "klayout",
            ]
            + mode_args
            + [
                "-rm",
                str(
                    files("librelane").joinpath("scripts", "klayout", "open_design.py")
                ),
            ]
        )

        # Not run_subprocess- need stdin, stdout, stderr to be accessible to the
        # user normally
        subprocess.check_call(
            cmd,
            env=env,
            cwd=self.step_dir,
        )

        return {}, {}
