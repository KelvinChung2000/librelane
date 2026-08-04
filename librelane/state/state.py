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

import io
import os
import csv
import sys
import json
import shutil
import pathlib
from decimal import Decimal
from typing import Any
from collections.abc import Callable, Mapping

from librelane.state.design_format import (
    DesignFormat,
)

from librelane.common import (
    Path,
    GenericImmutableDict,
    copy_recursive,
)


class InvalidState(RuntimeError):
    pass


type StateElement = Path | list[Path] | dict[str, Path | list[Path]] | None


class State(GenericImmutableDict[str, StateElement]):
    """
    Basically, a dictionary from :class:`DesignFormat`\\s and values
    of (nested dictionaries of) :class:`pathlib.Path`\\.

    The state is the only thing that can be altered by steps other than the
    filesystem.

    States are **immutable**. To construct a new state with some modifications,
    you may do so as follows::

        state_b = State(
            copying=state_a,
            overrides={
                …
            },
            metrics=GenericImmutableDict(copying=state_a.metrics, overrides={
                …
            })
        )

    Though in the majority of cases, you do not have to construct States on your
    own: after executing a Step, you only return your deltas and then the Flow
    is responsible for the creation of a new Step object.

    Parameters
    ----------
    copying : Mapping[str, StateElement] | Mapping[DesignFormat, StateElement] | None
        A mutable or immutable mapping to use as the starting
        value for this State.
    overrides : Mapping[str, StateElement] | Mapping[DesignFormat, StateElement] | None
        A mutable or immutable mapping to override the starting
        values with.
    metrics : Mapping[str, Any] | None
        A dictionary that carries statistics about the design: area,
        wire length, et cetera, but also miscellaneous data, for example, whether
        it passed a certain check or not.
    """

    def __init__(
        self,
        copying: Mapping[str, StateElement]
        | Mapping[DesignFormat, StateElement]
        | None = None,
        *args,
        overrides: Mapping[str, StateElement]
        | Mapping[DesignFormat, StateElement]
        | None = None,
        metrics: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        copying_resolved: dict[str, StateElement] = {}
        if c_mapping := copying:
            for key, value in c_mapping.items():
                if isinstance(key, DesignFormat):
                    copying_resolved[key.id] = value
                else:
                    copying_resolved[key] = value

        overrides_resolved = {}
        if o_mapping := overrides:
            for k, value in o_mapping.items():
                if isinstance(k, DesignFormat):
                    k = k.id
                overrides_resolved[k] = value

        self.metrics = GenericImmutableDict(metrics or {})
        for key in list(copying_resolved.keys()):
            if copying_resolved[key] is None:
                del copying_resolved[key]

        super().__init__(
            copying_resolved,
            *args,
            overrides=overrides_resolved,
            **kwargs,
        )

    def get_by_df(self, key: DesignFormat) -> StateElement:
        return self.get(key.id)

    def __getitem__(self, key: DesignFormat | str) -> StateElement:
        if isinstance(key, DesignFormat):
            id: str = key.id
            key = id
        return super().__getitem__(key)

    def __setitem__(self, key: DesignFormat | str, item: StateElement):
        if isinstance(key, DesignFormat):
            id: str = key.id
            key = id
        return super().__setitem__(key, item)

    def __delitem__(self, key: DesignFormat | str):
        if isinstance(key, DesignFormat):
            id: str = key.id
            key = id
        return super().__delitem__(key)

    def to_raw_dict(self, metrics: bool = True) -> dict[str, Any]:
        final = super().to_raw_dict()
        if metrics:
            final["metrics"] = self.metrics.to_raw_dict()
        return final

    def copy(self: "State") -> "State":
        metrics: GenericImmutableDict[str, Any] = GenericImmutableDict(
            copy_recursive(self.metrics)
        )
        new = State(self, metrics=metrics)
        return new

    def _walk(
        self,
        views: dict | "State",
        save_directory: str | os.PathLike,
        visit: Callable[
            [str, StateElement, str, str | os.PathLike[str], int], StateElement
        ],
        key_path: str = "",
        depth: int = 0,
        top_key: str | None = None,
    ):
        for key, value in views.items():
            current_top_key = top_key
            if current_top_key is None:
                current_top_key = key
            current_folder = key.strip("_*")
            if df := DesignFormat.factory.get(key):
                current_folder = df.folder

            target_dir = pathlib.Path(save_directory) / current_folder

            current_key_path = f"{key_path}.{key}"
            visit(current_key_path, value, current_top_key, target_dir, depth)
            if isinstance(value, dict):
                self._walk(
                    value,
                    target_dir,
                    visit,
                    current_key_path,
                    depth + 1,
                    current_top_key,
                )
            if isinstance(value, list):
                for i, element in enumerate(value):
                    element_key_path = f"{current_key_path}[{i}]"
                    visit(
                        element_key_path,
                        element,
                        current_top_key,
                        target_dir,
                        depth + 1,
                    )

    def save_snapshot(self, path: str | os.PathLike):
        """
        Validates the current state then saves all views to a folder by
        design format, including the metrics.

        Parameters
        ----------
        path : str | os.PathLike
            The folder that would contain other folders.
        """

        def visitor(key, value, top_key, save_directory, depth):
            if not isinstance(value, pathlib.Path):
                return
            save_directory.mkdir(parents=True, exist_ok=True)
            target_path = save_directory / pathlib.Path(value).name
            shutil.copyfile(value, target_path, follow_symlinks=True)

        self.validate()
        snapshot_path = pathlib.Path(path).resolve()
        logger.info(f"Saving views to '{snapshot_path}'…")
        snapshot_path.mkdir(parents=True, exist_ok=True)
        self._walk(self, snapshot_path, visitor)
        with (snapshot_path / "metrics.csv").open("w", encoding="utf8") as f:
            self.metrics_to_csv(f)

        with (snapshot_path / "metrics.json").open("w", encoding="utf8") as f:
            f.write(self.metrics.dumps())

    def metrics_to_csv(
        self, fp: io.TextIOWrapper, metrics_object: dict[str, Any] | None = None
    ):
        w = csv.writer(fp)
        w.writerow(("Metric", "Value"))
        for entry in (metrics_object or self.metrics).items():
            w.writerow(entry)

    def validate(self):
        """
        Ensures that all paths exist in a State.
        """

        def visitor(key, value, top_key, _, depth):
            if (
                depth == 0
                and DesignFormat.factory.get(top_key) is None
                and value is not None
            ):
                raise InvalidState(
                    f"Key '{top_key}' does not match a known design format."
                )
            if value is None:
                return
            if not (
                isinstance(value, pathlib.Path)
                or isinstance(value, dict)
                or isinstance(value, list)
            ):
                raise InvalidState(
                    f"Value at '{key}' is not a Path nor a dictionary/list of Paths: '{value}'."
                )

        self._walk(self.to_raw_dict(metrics=False), "", visit=visitor)

    @staticmethod
    def __resolve_directive(
        value: Any,
        symbols: Mapping[str, Any],
        key_path: str,
    ) -> Any:
        """Resolve a preprocessor directive stored in place of a path.

        :meth:`librelane.steps.Step.create_reproducible` writes
        ``pdk_dir::<relative>`` for a view that lives inside the PDK, because a
        reproducible does not carry the PDK with it. Where the PDK is, is
        something only the reader knows, so the directive is left unresolved in
        the file and resolved here, against symbols the reader supplies.
        """
        # librelane.config imports librelane.state, so the preprocessor cannot
        # be imported at module scope.
        from librelane.config.preprocessor import (
            GlobMatch,
            parse_directive,
            resolve_directive,
        )

        if not isinstance(value, str):
            return value
        directive = parse_directive(value)
        if directive is None:
            return value

        resolved = resolve_directive(directive, lambda name: symbols[name])
        if not isinstance(resolved, GlobMatch):
            return resolved
        if len(resolved) != 1:
            raise ValueError(
                f"Directive '{value}' for design format '{key_path}' matched "
                f"{len(resolved)} files: a view names exactly one."
            )
        return resolved[0]

    @classmethod
    def __load_recursive(
        Self,
        views: dict,
        validate_path: bool = True,
        key_path: str = "",
        symbols: Mapping[str, Any] | None = None,
    ) -> dict:
        target: dict = {}
        for key, value in views.items():
            current_key_path = f"{key_path}.{key}"
            if value is None:
                target[key] = value
                continue

            if isinstance(value, dict):
                target[key] = Self.__load_recursive(
                    value,
                    validate_path,
                    key_path=current_key_path,
                    symbols=symbols,
                )
            elif isinstance(value, list):
                target[key] = []
                for entry in value:
                    if symbols is not None:
                        entry = Self.__resolve_directive(
                            entry, symbols, current_key_path
                        )
                    if validate_path and not pathlib.Path(entry).exists():
                        raise ValueError(
                            f"Provided path '{entry}' to design format '{current_key_path}' does not exist."
                        )
                    target[key].append(pathlib.Path(entry))
            else:
                if symbols is not None:
                    value = Self.__resolve_directive(value, symbols, current_key_path)
                if validate_path and not pathlib.Path(value).exists():
                    raise ValueError(
                        f"Provided path '{value}' to design format '{current_key_path}' does not exist."
                    )
                target[key] = pathlib.Path(value)
        return target

    @classmethod
    def load(
        Self,
        dict_in: dict,
        validate_path: bool = True,
        symbols: Mapping[str, Any] | None = None,
    ) -> "State":
        """
        Parameters
        ----------
        dict_in : dict
            The raw state, as read from JSON.
        validate_path : bool
            Whether to check that every path named by the state exists.
        symbols : Mapping[str, Any] | None
            Values for the configuration variables a stored preprocessor
            directive may name, chiefly ``PDKPATH`` for ``pdk_dir::`` and
            ``DESIGN_DIR`` for ``dir::``. Without it, a directive is read as
            the literal path it is not, which is what makes a state specific
            to the filesystem it was written on.
        """
        metrics = dict_in.get("metrics")
        if metrics is not None:
            del dict_in["metrics"]

        views = Self.__load_recursive(dict_in, validate_path, symbols=symbols)
        return Self(views, metrics=metrics)

    @classmethod
    def loads(
        Self,
        json_in: str,
        validate_path: bool = True,
        symbols: Mapping[str, Any] | None = None,
    ) -> "State":
        try:
            raw = json.loads(json_in, parse_float=Decimal)
        except json.JSONDecodeError as e:
            raise InvalidState(f"Invalid JSON string provided for state: {e}")

        if not isinstance(raw, dict):
            raise InvalidState("Failed to load state: JSON result is not a dictionary")

        return Self.load(raw, validate_path=validate_path, symbols=symbols)

    def __mapping_to_html_rec(
        self,
        mapping: Mapping[str, Any],
        header_optional: tuple[str, str] | None = None,
    ):
        result = """
        <table style="grid-column-start: 1; grid-column-end: 2; ">
        """
        if header := header_optional:
            key_h, value_h = header
            result += f"""
                <tr>
                    <th style="text-align: left;">{key_h}</th>
                    <th style="text-align: left;">{value_h}</th>
                </tr>
            """

        for id, value in mapping.items():
            if value is None:
                continue

            key_content = id
            if format := DesignFormat.factory.get(id):
                key_content = format.id

            value_content = str(value)
            if isinstance(value, Mapping):
                value_content = self.__mapping_to_html_rec(value)
            elif isinstance(value, pathlib.Path):
                value_rel = os.path.relpath(value, ".")

                value_content = f'<a href="{value_rel}">{value_rel}</a>'
                if "google.colab" in sys.modules:
                    # Can't link in colab
                    value_content = value_rel

            result += f"""
                <tr>
                    <td style="text-align: left;">{key_content}</td>
                    <td style="text-align: left;">{value_content}</td>
                </tr>
            """

        result += """
        </table>
        """
        return result

    def _repr_html_(self) -> str:
        return (
            '<div style="display: grid; grid-auto-columns: minmax(0, 1fr); grid-auto-rows: minmax(0, 1fr); grid-auto-flow: column;">'
            + self.__mapping_to_html_rec(
                self.to_raw_dict(metrics=False),
                ("Format", "Path"),
            )
            + "</div>"
        )
