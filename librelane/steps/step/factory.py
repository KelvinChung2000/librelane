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

import os
import json
from typing import (
    ClassVar,
    TYPE_CHECKING,
    TypeVar,
)
from collections.abc import Callable


from librelane.config import (
    Config,
)
import builtins

if TYPE_CHECKING:
    from librelane.steps.step.core import Step

VT = TypeVar("VT")


class StepFactory(object):
    """
    A factory singleton for Steps, allowing steps types to be registered and then
    retrieved by name.

    See
    `Factory (object-oriented programming) on Wikipedia <https://en.wikipedia.org/wiki/Factory_(object-oriented_programming)>`_
    a primer.
    """

    __registry: ClassVar[dict[str, type[Step]]] = {}

    @classmethod
    def from_step_config(
        Self, step_config_path: Config | str | os.PathLike
    ) -> tuple[str | None, type[Step] | None]:
        if isinstance(step_config_path, Config):
            step_id = Config.meta.step
        else:
            config_dict = json.load(open(step_config_path, encoding="utf8"))
            meta = config_dict.get("meta") or {}
            step_id = meta.get("step")
        if step_id is None:
            return (None, None)
        step_id = str(step_id)
        return (step_id, Self.get(step_id))

    @classmethod
    def register(Self) -> Callable[[type[Step]], type[Step]]:
        """
        Adds a step type to the registry using its :attr:`Step.id` attribute.
        """

        def decorator(cls: type[Step]) -> type[Step]:
            if cls.id == NotImplemented:
                raise RuntimeError(
                    f"Abstract step {cls} without property .id cannot be registered."
                )
            Self.__registry[cls.id.lower()] = cls
            return cls

        return decorator

    @classmethod
    def get(Self, name: str) -> type[Step] | None:
        """
        Retrieves a Step type from the registry using a lookup string.

        Parameters
        ----------
        name : str
            The registered name of the Step. Case-insensitive.
        """
        return Self.__registry.get(name.lower())

    @classmethod
    def list(Self) -> builtins.list[str]:
        """
        Returns
        -------
        builtins.list[str]
            A list of IDs of all registered names.
        """
        return [cls.id for cls in Self.__registry.values()]
