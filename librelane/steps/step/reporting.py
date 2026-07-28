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
from __future__ import annotations

from loguru import logger

import os
import json
import shutil
import textwrap
import pathlib
from concurrent.futures import Future
from itertools import zip_longest
from typing import (
    Any,
    ClassVar,
    TypeVar,
)
from collections.abc import Callable


from ...config import (
    BaseConfigModel,
    Variable,
)
from ...state import DesignFormat, State
from ...common import (
    GenericDict,
    GenericDictEncoder,
    Path,
    slugify,
    copy_recursive,
)
from ...__version__ import __version__

from .exceptions import StepException

VT = TypeVar("VT")


class ReportingMixin:
    id: str
    inputs: ClassVar[list[DesignFormat]]
    outputs: ClassVar[list[DesignFormat]]
    config_vars: ClassVar[list[Variable]]
    config: BaseConfigModel
    state_in: Future[State]
    state_out: State | None
    start_time: float | None
    end_time: float | None
    step_dir: pathlib.Path
    get_implementation_id: ClassVar[Callable[[], str]]

    @classmethod
    def __get_desc(Self) -> str:  # pragma: no cover
        if hasattr(Self, "long_name"):
            return Self.long_name
        elif hasattr(Self, "name"):
            return Self.name
        return Self.__name__

    @classmethod
    def get_help_md(
        Self,
        *,
        docstring_override: str = "",
        use_dropdown: bool = False,
        myst_anchors: bool = False,
    ):  # pragma: no cover
        """
        Renders Markdown help for this step to a string.
        """
        doc_string = docstring_override
        if Self.__doc__:
            doc_string = textwrap.dedent(Self.__doc__)

        result = (
            textwrap.dedent(
                f"""
                ```{{eval-rst}}
                %s
                ```

                {":::{dropdown} Importing" if use_dropdown else "#### Importing"}
                ```python
                from {Self.__module__} import {Self.__name__}

                # or

                from librelane.steps import Step

                {Self.__name__} = Step.factory.get("{Self.id}")
                ```
                {":::" if use_dropdown else ""}
                """
            )
            % doc_string
        )
        if len(Self.inputs) + len(Self.outputs):
            result += textwrap.dedent(
                """
                #### Inputs and Outputs

                | Inputs | Outputs |
                | - | - |
                """
            )
            for input, output in zip_longest(Self.inputs, Self.outputs):
                input_str = ""
                if input is not None:
                    optional = "?" if input.optional else ""
                    input_str = f"{input.id}{optional} (.{input.extension})"

                output_str = ""
                if output is not None:
                    if not isinstance(output, DesignFormat):
                        raise StepException(
                            f"Output '{output}' is not a valid DesignFormat enum object."
                        )
                    output_str = f"{output.full_name} (.{output.extension})"
                result += f"| {input_str} | {output_str} |\n"

        if len(Self.config_vars):
            config_var_anchors = f"({Self.id.lower()}-configuration-variables)="
            result += textwrap.dedent(
                f"""
                {config_var_anchors * myst_anchors}
                #### Configuration Variables
                """
            )
            result += Variable._render_table_md(
                Self.config_vars, myst_anchor_owner_id=Self.id if myst_anchors else None
            )

        step_anchor = f"(step-{slugify(Self.id.lower())})="
        result = (
            textwrap.dedent(
                f"""
                {step_anchor * myst_anchors}
                ### {Self.__get_desc()}
                """
            )
            + result
        )

        return result

    @classmethod
    def display_help(Self):  # pragma: no cover
        """
        Displays Markdown help for this Step.

        If in an IPython environment, it's rendered using ``IPython.display``.
        Otherwise, it's rendered using ``rich.markdown``.
        """
        try:
            get_ipython()  # type: ignore

            import IPython.display

            IPython.display.display(IPython.display.Markdown(Self.get_help_md()))
        except NameError:
            from ...logging import console
            from rich.markdown import Markdown

            console.log(Markdown(Self.get_help_md()))

    def _repr_markdown_(self) -> str:  # pragma: no cover
        """
        Only one _ because this is used by IPython.
        """
        if self.state_out is None:
            return """
                ### Step not yet executed.
            """
        state_in = self.state_in.result()

        assert self.start_time is not None, (
            "Start time not set even though self.state_out exists"
        )
        assert self.end_time is not None, (
            "End time not set even though self.state_out exists"
        )
        result = f"#### Time Elapsed: {'%.2f' % (self.end_time - self.start_time)}s\n"

        views_updated = []
        for id, value in dict(self.state_out).items():
            if value is None:
                continue

            if state_in.get(id) != value:
                df = DesignFormat.factory.get(id)
                assert df is not None
                views_updated.append(df.full_name)

        if len(views_updated):
            result += "#### Views updated:\n"
            for view in views_updated:
                result += f"* {view}\n"

        if preview := self.layout_preview():
            result += "#### Preview:\n"
            result += preview

        return result

    def layout_preview(self) -> str | None:  # pragma: no cover
        """
        :returns: An HTML tag that could act as a preview for a specific stage
            or ``None`` if a preview is unavailable for this step.
        """
        return None

    def display_result(self):  # pragma: no cover
        """
        IPython-only. Displays the results of a given step.
        """
        import IPython.display

        IPython.display.display(IPython.display.Markdown(self._repr_markdown_()))

    def create_reproducible(
        self,
        target_dir: str | os.PathLike[str],
        include_pdk: bool = True,
        flatten: bool = False,
    ):
        """
        Creates a folder that, given a specific version of LibreLane being
        installed, makes a portable reproducible of that step's execution.

        ..note

            Reproducibles are limited on Magic and Netgen, as their RC files
            form an indirect dependency on many `.mag` files or similar that
            cannot be enumerated by LibreLane.

        :param target_dir: The directory in which to create the reproducible
        :param include_pdk: Include PDK files. If set to false, Path pointing
            to PDK files will be prefixed with ``pdk_dir::`` instead of being
            copied.
        :param flatten: Creates a reproducible with a flat (single-directory)
            file structure, except for the PDK which will maintain its internal
            folder structure (as it is sensitive to it.)
        """
        # 0. Create Directories
        target_path = pathlib.Path(target_dir)
        try:
            shutil.rmtree(target_path, ignore_errors=False)
        except FileNotFoundError:
            pass
        target_path.mkdir(parents=True)

        files_path = target_path if flatten else target_path / "files"
        pdk_root_flat_dirname = pathlib.Path("pdk")
        pdk_flat_dirname = pdk_root_flat_dirname / self.config["PDK"]
        pdk_flat_path = target_path / pdk_flat_dirname
        if flatten and include_pdk:
            pdk_flat_path.mkdir(parents=True)

        pdk_path = (
            pathlib.Path(str(self.config["PDK_ROOT"])) / self.config["PDK"]
        ).resolve()

        def visitor(x: Any) -> Any:
            if not isinstance(x, Path):
                return x

            source_path = pathlib.Path(str(x))
            source_resolved = source_path.resolve()
            try:
                pdk_relative = source_resolved.relative_to(pdk_path)
                in_pdk = True
            except ValueError:
                pdk_relative = None
                in_pdk = False

            if not include_pdk and in_pdk:
                assert pdk_relative is not None
                return Path(f"pdk_dir::{pdk_relative}")

            source_relative = source_path
            if source_path.is_absolute():
                source_relative = source_path.relative_to(source_path.anchor)
            target_relpath = pathlib.Path("files") / source_relative
            target_abspath = files_path / source_relative

            if flatten:
                if include_pdk and in_pdk:
                    assert pdk_relative is not None
                    target_relpath = pdk_flat_dirname / pdk_relative
                    target_abspath = target_path / target_relpath
                else:
                    counter = 0
                    filename = source_path.name

                    def filename_with_counter() -> str:
                        nonlocal counter, filename
                        if counter == 0:
                            return filename
                        else:
                            return f"{counter}-{filename}"

                    while True:
                        current = filename_with_counter()
                        target_relpath = pathlib.Path(current)
                        target_abspath = files_path / current
                        counter += 1
                        if not target_abspath.exists():
                            break

            target_abspath.parent.mkdir(parents=True, exist_ok=True)

            if source_path.is_dir():
                if not flatten:
                    target_abspath.mkdir(parents=True, exist_ok=True)
            else:
                shutil.copy(source_path, target_abspath)
                if hasattr(os, "chmod"):
                    target_abspath.chmod(0o755)

            return Path(f"./{target_relpath}")

        # 1. Config
        dumpable_config: dict = copy_recursive(self.config, translator=visitor)
        dumpable_config["meta"] = {
            "librelane_version": __version__,
            "step": self.__class__.get_implementation_id(),
        }

        del dumpable_config["DESIGN_DIR"]

        if include_pdk:
            pdk_dirname = dumpable_config["PDK_ROOT"]
            if flatten:
                pdk_dirname = pdk_root_flat_dirname

            # So it's always the first one:
            dumpable_config = {"PDK_ROOT": pdk_dirname, **dumpable_config}

        else:
            # If not including the PDK, pdk_root is going to have to be
            # passed to the config when running the reproducible.
            del dumpable_config["PDK_ROOT"]

        dumpable_config = {
            k: dumpable_config[k] for k in sorted(dumpable_config)
        }  # sort dict

        config_path = target_path / "config.json"
        config_path.write_text(json.dumps(dumpable_config, cls=GenericDictEncoder))

        # 2. State
        state_in: GenericDict[str, Any] = self.state_in.result().copy_mut()
        for format_id in state_in:
            format = DesignFormat.factory.get(format_id)
            assert format is not None
            if format not in self.__class__.inputs and not (
                format == DesignFormat.DEF
                and DesignFormat.ODB
                in self.__class__.inputs  # hack to write tests a bit more easily
            ):
                state_in[format.id] = None
        state_in["metrics"] = self.state_in.result().metrics.copy_mut()
        dumpable_state = copy_recursive(state_in, translator=visitor)
        state_path = target_path / "state_in.json"
        state_path.write_text(json.dumps(dumpable_state, cls=GenericDictEncoder))

        # 3. Runner (LibreLane)
        script_path = target_path / "run_ol.sh"
        script_path.write_text(
            textwrap.dedent(
                """
                #!/bin/sh
                set -e
                python3 -m librelane --version
                if [ "$?" != "0" ]; then
                    echo "Failed to run 'python3 -m librelane --version'."
                    exit -1
                fi

                ARGS="$@"
                if [ "$1" != "eject" ] && [ "$1" != "run" ]; then
                    ARGS="run $@"
                fi
                python3 -m librelane.steps $ARGS\\
                    --config ./config.json\\
                    --state-in ./state_in.json
                """
            ).strip()
        )
        if hasattr(os, "chmod"):
            script_path.chmod(0o755)
        hyperlinks = (
            os.getenv(
                "_i_want_librelane_to_hyperlink_things_for_some_reason",
                None,
            )
            == "1"
        )
        link_start = ""
        link_end = ""
        if hyperlinks:
            link_start = f"[link=file://{target_path.resolve()}]"
            link_end = "[/link]"

        logger.info(f"Reproducible created at: {link_start}'{target_path}'{link_end}")
