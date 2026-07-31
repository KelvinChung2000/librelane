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
import tkinter
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any
from collections import UserString
from collections.abc import Iterable, Mapping


class TclUtils(object):
    """
    A collection of useful Tcl utilities.
    """

    def __init__(self):
        raise TypeError(f"Cannot create instances of '{self.__class__.__name__}'")

    @staticmethod
    def escape(s: str) -> str:
        """
        Returns
        -------
        str
            The input string serialized as one Tcl list element.
        """
        return TclUtils.join([s])

    @staticmethod
    def join(ss: Iterable[str]) -> str:
        """
        Parameters
        ----------
        ss : Iterable[str]
            Input list

        Returns
        -------
        str
            The input list converted to a Tcl-compatible list where each
            element is interpreted by Tcl as a single element.
        """
        interpreter = tkinter.Tcl()
        interpreter.tk.wantobjects(False)
        return str(interpreter.call("list", *ss))

    @staticmethod
    def split(s: str) -> list[str]:
        """
        Returns
        -------
        list[str]
            The input Tcl-compatible list string split into its elements.
        """
        interpreter = tkinter.Tcl()
        try:
            return list(interpreter.splitlist(s))
        except tkinter.TclError as e:
            raise ValueError(f"Invalid Tcl list: {s}") from e

    @staticmethod
    def to_tcl(value: Any) -> str:
        """
        Returns
        -------
        str
            A Python value serialized as a Tcl scalar, list, or dictionary.
        """
        if not isinstance(value, type) and is_dataclass(value):
            return TclUtils.to_tcl(asdict(value))  # type: ignore[arg-type]
        if isinstance(value, Mapping):
            elements: list[str] = []
            for key, item in value.items():
                elements.extend((TclUtils.to_tcl(key), TclUtils.to_tcl(item)))
            return TclUtils.join(elements)
        if isinstance(value, Iterable) and not isinstance(value, (str, UserString)):
            return TclUtils.join(TclUtils.to_tcl(item) for item in value)
        if isinstance(value, Enum):
            return value.name
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    @staticmethod
    def _eval_env(env_in: Mapping[str, Any], tcl_in: str) -> dict[str, Any]:
        interpreter = tkinter.Tcl()

        interpreter.eval("array unset ::env")
        serialized_in = {}
        original_in = {}
        for key, value in env_in.items():
            if value is None:
                continue
            key = str(key)
            serialized_in[key] = TclUtils.to_tcl(value)
            original_in[key] = value
            interpreter.setvar(f"env({key})", serialized_in[key])

        interpreter.eval(tcl_in)

        env_items = TclUtils.split(interpreter.eval("array get ::env"))
        env_out = {env_items[i]: env_items[i + 1] for i in range(0, len(env_items), 2)}

        for key, original in original_in.items():
            if env_out.get(key) == serialized_in[key]:
                env_out[key] = original

        return env_out
