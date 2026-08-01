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
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from librelane.common import Path
from librelane.common.errors import FlowError
from librelane.config import Variable
from librelane.config.loading.sources import read_source
from librelane.flows import predicates
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

_JOB_KEYS = (
    "needs",
    "uses",
    "steps",
    "source",
    "if",
    "with",
    "until",
    "iterations",
    "max",
    "mode",
    "select",
    "resources",
)

#: The Python field names behind the aliased job keys, accepted so that
#: ``JobSpec(condition=..., values=..., max_passes=...)`` works from Python.
_JOB_FIELD_NAMES = ("condition", "values", "max_passes")

#: Keys no ``with`` block at either level may set. They select the process
#: before any other value is resolved, so a document setting one would
#: override the command-line argument rather than layer under it. A literal
#: tuple rather than a derived set: only ``PDK`` is a configuration variable
#: at all.
_RESERVED_VALUE_KEYS = ("PDK", "SCL", "PAD", "meta")

#: The key no ``with`` block at either level may set. ``TOOLS`` decides which
#: provider implements each job, and the engine reads it out of the raw sources
#: *before* the configuration exists, because the providers it names are what
#: fix the step set the configuration is then validated against. A document
#: setting it would therefore be read too late to change anything, and the
#: resolved configuration would report a provider selection that did not happen.
_PRE_PASS_VALUE_KEY = "TOOLS"


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
    #: The gate of a loop's ring: a predicate of ``metric::`` terms only,
    #: evaluated against the gate's output after each pass. ``None`` on every
    #: job outside a ring.
    until: str | None = None
    #: The explicit value schedule for an escalation loop's gate or a sweep.
    #: Pass ``k`` (1-based) layers entry ``k`` onto every ring member's (or
    #: the sweep job's) configuration for that pass.
    iterations: list[dict[str, Any]] | None = None
    #: The pass bound for an incremental-repair loop: no schedule, just a
    #: count. Aliased to ``max``, which shadows the builtin.
    max_passes: int | None = Field(default=None, alias="max")
    #: ``escalate`` stops at the first pass ``until`` accepts; ``sweep`` runs
    #: every ``iterations`` entry and keeps the best by ``select``.
    mode: Literal["escalate", "sweep"] = "escalate"
    #: A sweep's keep rule: a bare metric name and a direction, ``min`` or
    #: ``max``. ``None`` off ``mode: sweep``.
    select: str | None = None
    #: The named resource pools this job must hold a seat in for the
    #: duration of its execution (or, inside a ring, each pass).
    resources: list[str] = []

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
        # and the template ids live in the job registry, which this module
        # deliberately does not import. spec_validation.py catches it.
        if self.uses is not None and self.steps is not None:
            raise FlowSpecError(
                "A job declares 'uses' and 'steps' together. Use 'uses' to "
                "name a registered job and provider, or 'steps' to list step "
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
    #: Named resource pools, each a positive integer capacity or the name of
    #: a configuration variable the flow declares with type ``int``. A job
    #: names the pools it needs in its own ``resources``.
    resources: dict[str, int | str] = {}

    @model_validator(mode="before")
    @classmethod
    def _reject_boolean_resource_capacities(cls, data: Any) -> Any:
        # Caught here, before pydantic parses 'resources' against
        # dict[str, int | str]: bool is an int subclass, so a lax union
        # coerces True/False to 1/0 silently, and by the time an
        # 'after' validator sees the field the observed value is already
        # indistinguishable from a literal '1' or '0' in the document. This
        # is the only point at which the actual YAML/mapping value -- a
        # Python bool, however the loader spelled it (true/false, yes/no,
        # on/off) -- is still visible.
        if not isinstance(data, dict):
            return data
        resources = data.get("resources")
        if not isinstance(resources, dict):
            return data
        for pool, capacity in resources.items():
            if isinstance(capacity, bool):
                raise FlowSpecError(
                    f"Resource pool '{pool}' declares capacity "
                    f"{capacity!r}, a boolean. A pool's capacity is a "
                    f"positive integer or the name of a configuration "
                    f"variable the flow declares with type 'int'; a "
                    f"boolean is neither."
                )
        return data

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
        self._check_values_do_not_select_tools()
        self._check_until_terms_are_metrics()
        self._check_until_requires_one_bound()
        self._check_schedule_combinations()
        self._check_iterations_entries()
        self._check_max_passes_positive()
        self._check_select_shape()
        self._check_job_resources_have_no_duplicates()
        self._check_resource_pool_literal_capacities()
        self._check_job_resources_are_declared_pools()
        return self

    def _check_needs_are_declared(self) -> None:
        for name, job in self.jobs.items():
            seen: set[str] = set()
            for need in job.needs:
                if need not in self.jobs:
                    raise FlowSpecError(
                        f"Job '{name}' needs '{need}', which this flow does "
                        f"not declare. Declared jobs: {sorted(self.jobs)}."
                    )
                # One entry per predecessor, because 'needs' is a set of edges
                # written as a list. A repeat gives the job two input places on
                # the same edge, which is not expressible as a marking: the
                # producer deposits one token per outgoing place and there is
                # only one such place. Caught here rather than deduplicated,
                # because a document that says 'a' twice means something the
                # graph cannot express and should be told so.
                if need in seen:
                    raise FlowSpecError(
                        f"Job '{name}' needs '{need}' more than once. A "
                        f"'needs' list names each predecessor exactly once."
                    )
                seen.add(need)

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
        # Only the ConfigTerms of an 'if' are checked here: their names are a
        # closed set, the declared configuration, and checkable at load time.
        # MetricTerms pass through unchecked, because metric names are not a
        # closed set -- a misspelt one surfaces as a runtime failure on the
        # job's first firing, not here.
        declared = {variable.name: variable for variable in self.config}
        for name, job in self.jobs.items():
            if job.condition is None:
                continue
            try:
                terms = predicates.parse_predicate(job.condition)
            except predicates.PredicateError as e:
                raise FlowSpecError(f"Job '{name}': {e}") from None
            for variable_name in predicates.config_terms(terms):
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
        blocks = [("Flow", self.name, self.values)] + [
            ("Job", name, job.values) for name, job in self.jobs.items()
        ]
        for kind, owner, values in blocks:
            for key in values:
                if key not in _RESERVED_VALUE_KEYS:
                    continue
                raise FlowSpecError(
                    f"{kind} '{owner}' sets '{key}' in its 'with' block. "
                    f"{list(_RESERVED_VALUE_KEYS)} select the process before "
                    f"any other value is resolved, so a document setting one "
                    f"would override the command line rather than layer under "
                    f"it. Set it on the design or on the command line."
                )

    def _check_values_do_not_select_tools(self) -> None:
        blocks = [("Flow", self.name, self.values)] + [
            ("Job", name, job.values) for name, job in self.jobs.items()
        ]
        for kind, owner, values in blocks:
            if _PRE_PASS_VALUE_KEY not in values:
                continue
            raise FlowSpecError(
                f"{kind} '{owner}' sets '{_PRE_PASS_VALUE_KEY}' in a 'with' "
                f"block. It selects the provider implementing each job, and "
                f"is read before any configuration is resolved, so a value "
                f"set here would be read too late to change which steps run "
                f"while still appearing in the resolved configuration. Set it "
                f"on the design."
            )

    def _check_until_terms_are_metrics(self) -> None:
        # 'until' accepts only 'metric::' terms: a configuration variable is
        # constant across passes, so a gate conjoining one either always
        # exits on pass 1 or never exits at all, and both are documents
        # saying something they cannot mean.
        for name, job in self.jobs.items():
            if job.until is None:
                continue
            try:
                terms = predicates.parse_predicate(job.until)
            except predicates.PredicateError as e:
                raise FlowSpecError(f"Job '{name}': {e}") from None
            config_names = predicates.config_terms(terms)
            if config_names:
                raise FlowSpecError(
                    f"Job '{name}' declares 'until: {job.until}', which "
                    f"conjoins configuration variable(s) {list(config_names)}. "
                    f"A configuration variable is constant across passes, so "
                    f"an 'until' gate on one either always exits on pass 1 or "
                    f"never exits at all. 'until' accepts only 'metric::' "
                    f"terms."
                )

    def _check_until_requires_one_bound(self) -> None:
        for name, job in self.jobs.items():
            if job.until is None:
                continue
            has_iterations = job.iterations is not None
            has_max = job.max_passes is not None
            if not has_iterations and not has_max:
                raise FlowSpecError(
                    f"Job '{name}' declares 'until' with neither "
                    f"'iterations' nor 'max'. An 'until' gate declares "
                    f"exactly one bound: an explicit value schedule "
                    f"('iterations') or a pass count ('max'); an unbounded "
                    f"loop is not accepted from any document."
                )
            if has_iterations and has_max:
                raise FlowSpecError(
                    f"Job '{name}' declares 'until' with both 'iterations' "
                    f"and 'max'. An 'until' gate declares exactly one bound, "
                    f"not both."
                )

    def _check_schedule_combinations(self) -> None:
        for name, job in self.jobs.items():
            is_sweep = job.mode == "sweep"
            if job.iterations is not None and job.until is None and not is_sweep:
                raise FlowSpecError(
                    f"Job '{name}' declares 'iterations' without 'until' or "
                    f"'mode: sweep'. 'iterations' is a value schedule: either "
                    f"an escalation loop's, gated by 'until', or a sweep's, "
                    f"declared with 'mode: sweep'."
                )
            if job.max_passes is not None:
                if is_sweep:
                    raise FlowSpecError(
                        f"Job '{name}' declares 'max' with 'mode: sweep'. A "
                        f"sweep runs every 'iterations' entry and keeps the "
                        f"best rather than stopping at a pass count; 'max' "
                        f"is meaningless with 'mode: sweep'."
                    )
                if job.until is None:
                    raise FlowSpecError(
                        f"Job '{name}' declares 'max' without 'until'. "
                        f"'max' bounds an 'until' gate's passes and is "
                        f"meaningless without one."
                    )
            if job.select is not None and not is_sweep:
                raise FlowSpecError(
                    f"Job '{name}' declares 'select' without 'mode: sweep'. "
                    f"'select' names a sweep's keep rule and is meaningless "
                    f"without 'mode: sweep'."
                )
            if is_sweep:
                if job.iterations is None or job.select is None:
                    raise FlowSpecError(
                        f"Job '{name}' declares 'mode: sweep' without both "
                        f"'iterations' and 'select'. A sweep needs its "
                        f"points ('iterations') and its keep rule "
                        f"('select')."
                    )
                if job.until is not None:
                    raise FlowSpecError(
                        f"Job '{name}' declares 'mode: sweep' with 'until'. "
                        f"A sweep does not stop early: it runs every point "
                        f"and keeps the best, so 'until' is meaningless with "
                        f"'mode: sweep'."
                    )

    def _check_iterations_entries(self) -> None:
        for name, job in self.jobs.items():
            if job.iterations is None:
                continue
            if len(job.iterations) == 0:
                raise FlowSpecError(
                    f"Job '{name}' declares an empty 'iterations' list. A "
                    f"schedule needs at least one entry."
                )
            for index, entry in enumerate(job.iterations, start=1):
                for key in entry:
                    if key in _RESERVED_VALUE_KEYS:
                        raise FlowSpecError(
                            f"Job '{name}' iteration {index} sets '{key}'. "
                            f"{list(_RESERVED_VALUE_KEYS)} select the "
                            f"process before any other value is resolved, "
                            f"so a document setting one would override the "
                            f"command line rather than layer under it. Set "
                            f"it on the design or on the command line."
                        )
                    if key == _PRE_PASS_VALUE_KEY:
                        raise FlowSpecError(
                            f"Job '{name}' iteration {index} sets "
                            f"'{_PRE_PASS_VALUE_KEY}'. It selects the "
                            f"provider implementing each job, and is read "
                            f"before any configuration is resolved, so a "
                            f"value set here would be read too late to "
                            f"change which steps run while still appearing "
                            f"in the resolved configuration. Set it on the "
                            f"design."
                        )

    def _check_max_passes_positive(self) -> None:
        for name, job in self.jobs.items():
            if job.max_passes is not None and job.max_passes < 1:
                raise FlowSpecError(
                    f"Job '{name}' declares 'max: {job.max_passes}'. 'max' "
                    f"is a positive integer bound on the loop's passes."
                )

    def _check_select_shape(self) -> None:
        for name, job in self.jobs.items():
            if job.select is None:
                continue
            tokens = job.select.split()
            if len(tokens) != 2 or tokens[1] not in ("min", "max"):
                raise FlowSpecError(
                    f"Job '{name}' declares 'select: {job.select}', which is "
                    f"not '<metric-name> min' or '<metric-name> max'. "
                    f"'select' is a bare metric name and a keep direction, "
                    f"two whitespace-separated tokens."
                )
            metric_name = tokens[0]
            if metric_name.startswith("metric::"):
                raise FlowSpecError(
                    f"Job '{name}' declares 'select: {job.select}', whose "
                    f"metric name carries a 'metric::' prefix. 'select' "
                    f"admits nothing but metrics, so a disambiguating prefix "
                    f"with nothing to disambiguate from is refused."
                )

    def _check_job_resources_have_no_duplicates(self) -> None:
        for name, job in self.jobs.items():
            seen: set[str] = set()
            for resource in job.resources:
                if resource in seen:
                    raise FlowSpecError(
                        f"Job '{name}' resources '{resource}' more than "
                        f"once. A 'resources' list names each pool exactly "
                        f"once."
                    )
                seen.add(resource)

    def _check_resource_pool_literal_capacities(self) -> None:
        # A str capacity names a configuration variable, checked against the
        # declared configuration in a later pass of this design; nothing here
        # rejects one.
        for pool, capacity in self.resources.items():
            if isinstance(capacity, int) and capacity < 1:
                raise FlowSpecError(
                    f"Resource pool '{pool}' declares capacity {capacity}. "
                    f"A pool's capacity is a positive integer literal or the "
                    f"name of a configuration variable the flow declares "
                    f"with type 'int'; a pool nothing can ever enter is a "
                    f"flow that stalls by declaration."
                )

    def _check_job_resources_are_declared_pools(self) -> None:
        for name, job in self.jobs.items():
            for resource in job.resources:
                if resource not in self.resources:
                    raise FlowSpecError(
                        f"Job '{name}' resources '{resource}', which flow "
                        f"'{self.name}' does not declare. Declared pools: "
                        f"{sorted(self.resources)}."
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
