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
The workflow document: a flow declared as data rather than as a Python class.

A document names jobs and the edges between them. It deliberately says nothing
about what a job's steps require or provide, because that contract belongs with
the steps, in Python, next to the code it describes. A document is a graph over
a library, not a redefinition of one.
"""

import graphlib
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.config import Variable
from librelane.config.loading.sources import read_source
from librelane.flows.spec_graph import topological_order


class FlowSpecError(FlowError):
    """
    Raised when a workflow document is malformed. Every instance names the
    offending job or key and the legal alternatives, and is raised before a run
    directory is created.
    """


#: The scalar types a document may declare. Products are deliberately absent.
#: Across every shipped flow the only annotations in use are ``bool`` and the
#: engine-level ``TOOLS``, which no document declares.
#:
#: Typed ``Any`` rather than ``type`` because ``common.Path`` is an
#: ``Annotated`` alias of ``pathlib.Path``, not a class.
_VARIABLE_TYPES: dict[str, Any] = {
    "bool": bool,
    "int": int,
    "str": str,
    "Decimal": Decimal,
    "Path": Path,
}

_JOB_KEYS = ("needs", "uses", "steps", "source", "if", "with")

#: The Python field names behind the aliased job keys, accepted so that
#: ``JobSpec(condition=..., values=...)`` works from Python.
_JOB_FIELD_NAMES = ("condition", "values")

#: Keys a document-level ``with`` may never set. They select the process before
#: any other value is resolved, so a document setting one would override the
#: command-line argument rather than layer under it. A literal tuple rather
#: than a derived set: only ``PDK`` is a configuration variable at all.
_RESERVED_VALUE_KEYS = ("PDK", "SCL", "PAD", "meta")

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def parse_condition(text: str) -> tuple[str, ...]:
    """
    Parses a job's ``if`` into the variable names it conjoins.

    The grammar is one or more variable names separated by the literal
    ``and``. General expressions are deliberately out of scope; they are
    spec 3.

    Phase 2 calls this to build ``Job.conditions``, so the return is a tuple
    and this is the only implementation of the grammar. Do not write a second
    one there.

    Parameters
    ----------
    text : str
        The raw ``if`` string.

    Returns
    -------
    The conjoined variable names, in order.

    Raises
    ------
    FlowSpecError
        If ``text`` is not a bare conjunction.
    """
    tokens = text.split()
    names = tokens[0::2]
    joiners = tokens[1::2]
    malformed = (
        len(names) == 0
        or len(joiners) != len(names) - 1
        or any(joiner != "and" for joiner in joiners)
        or any(_IDENTIFIER.match(name) is None or name == "and" for name in names)
    )
    if malformed:
        raise FlowSpecError(
            f"Condition '{text}' is not a conjunction. An 'if' is one or "
            f"more configuration variable names joined by the literal 'and', "
            f"for example 'A' or 'A and B and C'."
        )
    return tuple(names)


class VariableSpec(BaseModel):
    """A configuration variable declared by a document's ``config`` list."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    description: str
    default: Any = None
    deprecated_names: list[str] = []
    units: str | None = None

    def to_variable(self) -> Variable:
        """
        Returns
        -------
        The equivalent :class:`librelane.config.Variable`.

        Raises
        ------
        FlowSpecError
            If :attr:`type` is not a supported scalar.
        """
        resolved = _VARIABLE_TYPES.get(self.type)
        if resolved is None:
            raise FlowSpecError(
                f"Variable '{self.name}' declares type '{self.type}', which a "
                f"workflow document cannot express. Supported types: "
                f"{sorted(_VARIABLE_TYPES)}."
            )
        return Variable(
            self.name,
            resolved,
            self.description,
            default=self.default,
            deprecated_names=list(self.deprecated_names),
            units=self.units,
        )


class JobSpec(BaseModel):
    """One job of a workflow document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    needs: list[str] = []
    uses: str | None = None
    steps: list[str] | None = None
    #: A view id or metric name mapped to the direct predecessor it comes
    #: from. Keyed by a plain string because a metric name such as
    #: ``design__lvs_error__count`` is not a ``DesignFormat``, and the join
    #: rule is one rule for views and metrics alike.
    source: dict[str, str] = {}
    #: Values supplied for configuration variables read only by this job.
    #: Aliased to ``with``, which is a Python keyword.
    values: dict[str, Any] = Field(default_factory=dict, alias="with")
    condition: str | None = Field(default=None, alias="if")

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        legal = set(_JOB_KEYS) | set(_JOB_FIELD_NAMES)
        unknown = [key for key in data if key not in legal]
        if unknown:
            raise FlowSpecError(
                f"Job declares unknown key(s) {sorted(unknown)}. A job accepts "
                f"exactly {list(_JOB_KEYS)}."
            )
        return data

    @model_validator(mode="after")
    def _reject_both_implementations(self) -> "JobSpec":
        # A job declaring *neither* is not rejected here. The implicit rule
        # says a job whose id is a registered template id means that template,
        # and the template ids live in the stage registry, which this module
        # deliberately does not import. spec_validation.py catches it.
        if self.uses is not None and self.steps is not None:
            raise FlowSpecError(
                "A job declares 'uses' and 'steps' together. Use 'uses' to "
                "name a registered stage and provider, or 'steps' to list step "
                "IDs inline, but not both."
            )
        return self


class FlowSpec(BaseModel):
    """A complete workflow document."""

    # populate_by_name is required, not optional. With extra="forbid" and an
    # aliased field, pydantic 2.13.4 rejects the Python field name outright, so
    # FlowSpec(values=...) raises extra_forbidden without it.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: str = ""
    #: Values supplied for configuration variables. Layered between the PDK
    #: and the design configuration, so the design always wins. Aliased to
    #: ``with``, which is a Python keyword, exactly as ``condition`` is
    #: aliased to ``if``.
    values: dict[str, Any] = Field(default_factory=dict, alias="with")
    config: list[VariableSpec] = []
    jobs: dict[str, JobSpec]
    #: The job whose output state is the flow's final state. Absent, the final
    #: state is the join of the sink arcs, which phase 2 computes.
    final: str | None = None

    def edges(self) -> dict[str, list[str]]:
        """
        Returns
        -------
        The job dependency map in the form
        :mod:`librelane.flows.spec_graph` expects.
        """
        return {name: list(job.needs) for name, job in self.jobs.items()}

    @model_validator(mode="after")
    def _check_structure(self) -> "FlowSpec":
        self._check_needs_are_declared()
        self._check_acyclic()
        self._check_sources_name_direct_predecessors()
        self._check_conditions_are_declared_booleans()
        self._check_final_names_a_job()
        self._check_values_are_not_reserved()
        return self

    def _check_needs_are_declared(self) -> None:
        for name, job in self.jobs.items():
            for need in job.needs:
                if need not in self.jobs:
                    raise FlowSpecError(
                        f"Job '{name}' needs '{need}', which this flow does "
                        f"not declare. Declared jobs: {sorted(self.jobs)}."
                    )

    def _check_acyclic(self) -> None:
        try:
            topological_order(self.edges())
        except graphlib.CycleError as e:
            raise FlowSpecError(
                f"The jobs of flow '{self.name}' contain a cycle: "
                f"{' -> '.join(e.args[1])}. A flow document is acyclic."
            ) from None

    def _check_sources_name_direct_predecessors(self) -> None:
        # A transitive ancestor is not enough. The join at a job reads only the
        # tokens on that job's own input arcs, one per entry in 'needs', so a
        # 'source' naming anything else names a token that does not exist.
        for name, job in self.jobs.items():
            for key, producer in job.source.items():
                if producer not in job.needs:
                    raise FlowSpecError(
                        f"Job '{name}' sources '{key}' from '{producer}', "
                        f"which is not one of its needs. A 'source' may only "
                        f"name a direct predecessor, because the join reads "
                        f"only the tokens on this job's own input arcs. "
                        f"needs: {sorted(job.needs)}."
                    )

    def _check_conditions_are_declared_booleans(self) -> None:
        declared = {variable.name: variable for variable in self.config}
        for name, job in self.jobs.items():
            if job.condition is None:
                continue
            try:
                variables = parse_condition(job.condition)
            except FlowSpecError as e:
                raise FlowSpecError(f"Job '{name}': {e}") from None
            for variable_name in variables:
                variable = declared.get(variable_name)
                if variable is None:
                    raise FlowSpecError(
                        f"Job '{name}' is conditional on '{variable_name}', "
                        f"which flow '{self.name}' does not declare. Declared "
                        f"variables: {sorted(declared)}."
                    )
                if variable.type != "bool":
                    raise FlowSpecError(
                        f"Job '{name}' is conditional on '{variable_name}', "
                        f"which flow '{self.name}' declares with type "
                        f"'{variable.type}'. An 'if' conjoins variables of "
                        f"type 'bool'."
                    )

    def _check_final_names_a_job(self) -> None:
        if self.final is None:
            return
        if self.final not in self.jobs:
            raise FlowSpecError(
                f"Flow '{self.name}' declares final job '{self.final}', which "
                f"it does not declare. Declared jobs: {sorted(self.jobs)}."
            )

    def _check_values_are_not_reserved(self) -> None:
        for key in self.values:
            if key in _RESERVED_VALUE_KEYS:
                raise FlowSpecError(
                    f"Flow '{self.name}' sets '{key}' in its 'with' block. "
                    f"{list(_RESERVED_VALUE_KEYS)} select the process before "
                    f"any other value is resolved, so a document setting one "
                    f"would override the command line rather than layer under "
                    f"it. Set it on the design or on the command line."
                )


def load_flow_spec(source: Mapping[str, Any] | str | os.PathLike) -> FlowSpec:
    """
    Reads a workflow document from a mapping, a YAML file or a JSON file.

    Parameters
    ----------
    source : Mapping[str, Any] | str | os.PathLike
        A mapping, or a path to a ``.yaml``, ``.yml`` or ``.json``
        file.

    Returns
    -------
    The validated document.

    Raises
    ------
    FlowSpecError
        If the document is malformed. The message names the
        source so a bad file in a directory of documents is identifiable.
    """
    read = read_source(source)
    try:
        return FlowSpec.model_validate(read.mapping)
    except FlowSpecError as e:
        raise FlowSpecError(f"In workflow document '{read.name}': {e}") from None
    except ValidationError as e:
        raise FlowSpecError(f"In workflow document '{read.name}': {e}") from None
