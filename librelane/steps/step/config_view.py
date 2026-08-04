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
What one step may read out of the configuration its whole flow shares.
"""

import json
from typing import Any
from collections.abc import Iterator, Mapping

from librelane.config import BaseConfigModel


class UndeclaredVariable(AttributeError):
    """
    Raised when a step reads a configuration variable it does not declare.

    The variable exists and holds a value -- it is simply another step's. See
    :class:`StepConfigView` for why reading it anyway is not harmless.
    """

    def __init__(self, step_id: str, name: str) -> None:
        self.step_id = step_id
        self.name = name
        super().__init__(
            f"Step '{step_id}' read the configuration variable '{name}', which "
            f"it does not declare. Add it to the step's 'Config' to read it. "
            f"(It is set for this flow, by another step's declaration, but a "
            f"step only ever runs with the variables it declares when it is "
            f"run on its own -- from a reproducible, or by 'Step.load'.)"
        )


class StepConfigView(Mapping[str, Any]):
    """
    One step's view of the configuration model its flow resolved.

    Every step running under a :class:`librelane.config.ConfigScope` reads one
    model, built from the union of every step's variables, so that no step pays
    to re-validate what another has already validated. The union is wider than
    any one step, though, and that difference is not cosmetic: a step run on
    its own -- :meth:`librelane.steps.Step.load`, which is how a reproducible
    and a re-run are built -- is handed a configuration narrowed to its own
    declarations, where reading another step's variable raises. Left
    unguarded, a step could read one, work for as long as it ran inside a
    flow, and fail the first time somebody tried to reproduce it.

    So the model is shared and the *view* of it is not: this narrows reads to
    the names the step declares, and says so when one falls outside. It holds
    no values of its own and validates nothing -- the sharing it exists to
    protect is the entire point of it.

    It is also what a step is recorded as having read. Iterating it, or
    dumping it, yields the step's own variables, which is what the ``config``
    a Tcl step exports and
    :meth:`librelane.steps.Step.own_config_dict` both need.

    Attributes
    ----------
    shared : BaseConfigModel
        The model this narrows, which every step in the scope holds.
    declared : frozenset[str]
        The names this step declared.
    """

    __slots__ = ("shared", "declared", "_step_id")

    def __init__(
        self,
        shared: BaseConfigModel,
        declared: frozenset[str],
        step_id: str,
    ) -> None:
        self.shared = shared
        self.declared = declared
        self._step_id = step_id

    def __getattr__(self, name: str) -> Any:
        # Reached only for a name that is not a slot or a method of this class,
        # which every configuration variable is.
        shared = object.__getattribute__(self, "shared")
        if name in object.__getattribute__(self, "declared"):
            return getattr(shared, name)
        if name in type(shared).model_fields or name in (shared.model_extra or {}):
            raise UndeclaredVariable(object.__getattribute__(self, "_step_id"), name)
        # Not a configuration variable at all: 'meta', 'diagnostics', and
        # whatever else a caller reads off a model.
        return getattr(shared, name)

    def __getitem__(self, key: str) -> Any:
        if key not in self.declared:
            raise KeyError(key)
        try:
            return self.shared[key]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        for key in self.shared:
            if key in self.declared:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.to_raw_dict() == (
                other.to_raw_dict() if hasattr(other, "to_raw_dict") else dict(other)  # type: ignore[call-overload]
            )
        return NotImplemented

    def __repr__(self) -> str:  # pragma: no cover
        return f"StepConfigView({self._step_id}, {len(self.declared)} variables)"

    def to_raw_dict(self, include_meta: bool = False) -> dict[str, Any]:
        output = {
            key: value
            for key, value in self.shared.to_raw_dict().items()
            if key in self.declared
        }
        if include_meta and self.shared.meta is not None:
            output["meta"] = self.shared.meta
        return output

    def dumps(self, include_meta: bool = False, **kwargs) -> str:
        kwargs.setdefault("indent", 4)
        return json.dumps(self.to_raw_dict(include_meta), default=str, **kwargs)


__all__ = ["StepConfigView", "UndeclaredVariable"]
