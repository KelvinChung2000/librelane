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
Thresholds a step raises against the metrics it has just measured.

LibreLane used to express these as a separate step family, ``Checker.*``: one
step per threshold, reading a metric out of the incoming state and failing if
it was too large. That put the failure in the wrong place. ``Checker.TrDRC``
reported the routing DRC violations, so the run directory that held the error
was ``…/checker-trdrc``, which contains nothing but the error, while the
report naming the violating shapes sat in ``…/openroad-detailedrouting`` --
a directory the flow had already declared successful. It also meant a
threshold could outlive its measurement: a checker whose metric was absent
warned and passed, so a flow that dropped the measuring step lost the check
silently.

A gate is the same threshold attached to the step that took the measurement.
It runs after :meth:`librelane.steps.Step.run` returns, against that call's
own metrics, so the error is raised by the step that has the evidence, in the
directory that holds it. A metric the step did not produce has no gate to
apply -- not because the threshold is optional, but because there is no
measurement to compare against, and the step that skipped the measurement is
the one that says why.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

from librelane.common import Filter, parse_metric_modifiers
from librelane.steps.step.exceptions import DeferredStepError, StepError

if TYPE_CHECKING:
    from librelane.steps.step.core import Step


def _raise(step: "Step", deferred: bool, message: str) -> None:
    bound = logger.bind(step=step.id)
    if deferred:
        bound.error(f"{message} - deferred")
        raise DeferredStepError(message)
    bound.error(message)
    raise StepError(message)


@dataclass(frozen=True)
class MetricGate:
    """
    A limit on one metric, enforced by the step that measured it.

    Parameters
    ----------
    metric : str
        The exact metric name, as the step reports it.
    description : str
        The metric in words, used in the log line and the error, e.g.
        ``"routing DRC errors"``. Read as "<n> <description> found."
    error_on_var : str | None
        The name of a boolean configuration variable that decides whether
        exceeding the limit is an error or a warning. These are the
        ``ERROR_ON_*`` variables, and each is declared by the step that owns
        the gate. ``None`` means the limit is unconditional.
    deferred : bool
        Whether exceeding the limit lets the rest of the flow run and fails at
        the end (a :class:`DeferredStepError`) or stops it where it stands.
        Deferred suits a measurement whose result nothing downstream depends
        on, such as a DRC count; immediate suits one that invalidates the
        views the step just wrote, such as unmapped cells in a netlist.
    threshold_var : str | None
        The name of a configuration variable holding the limit, for the gates
        whose limit is a PDK's business rather than a fixed zero. ``None``
        means the limit is zero -- the gate fires on any nonzero count.
    remedy : str | None
        A sentence appended to the error telling the user what to do about it,
        for the gates where that is not obvious from the count alone.
    """

    metric: str
    description: str
    error_on_var: str | None = None
    deferred: bool = True
    threshold_var: str | None = None
    remedy: str | None = None

    def threshold(self, step: "Step") -> Decimal | None:
        if self.threshold_var is None:
            return Decimal(0)
        configured = step.config[self.threshold_var]
        assert configured is None or isinstance(configured, Decimal), (
            f"'{self.threshold_var}' is a gate threshold and must be declared "
            f"as an Optional[Decimal] variable, not {type(configured)}."
        )
        return configured

    def check(self, step: "Step", metrics: dict) -> None:
        value = metrics.get(self.metric)
        if value is None:
            return

        threshold = self.threshold(step)
        if threshold is None:
            logger.bind(step=step.id).warning(
                f"No '{self.threshold_var}' is configured, so {self.description} "
                f"are reported but not limited."
            )
            return

        if value <= threshold:
            logger.info(f"Check for {self.description} clear.")
            return

        message = f"{value} {self.description} found."
        if self.remedy is not None:
            message = f"{message} {self.remedy}"
        if self.error_on_var is not None and not step.config[self.error_on_var]:
            logger.bind(step=step.id).warning(
                f"{message} '{self.error_on_var}' is false, so this is not an error."
            )
            return

        _raise(step, self.deferred, message)


@dataclass(frozen=True)
class CornerMetricGate:
    """
    A limit on a per-corner metric, enforced by the step that measured it.

    A timing violation count exists once per IPVT corner, and which corners a
    design is signed off at is a PDK's decision, so the limit applies to the
    corners a set of wildcards matches and merely warns about the rest.

    Parameters
    ----------
    metric : str
        The metric's base name, without the ``__corner:`` modifier the step
        appends, e.g. ``"timing__setup_vio__count"``.
    violation_type : str
        The violation in words, used in the log lines, e.g. ``"setup"``.
    corner_var : str
        The name of a configuration variable holding the wildcards for this
        violation type specifically. An unset value falls through to
        ``fallback_corner_var``.
    fallback_corner_var : str
        The name of the configuration variable holding the wildcards shared by
        every violation type.
    """

    metric: str
    violation_type: str
    corner_var: str
    fallback_corner_var: str = "TIMING_VIOLATION_CORNERS"

    #: A wildcard that matches no corner. It is how a PDK says "measure this,
    #: report it, but do not fail on it": the corner list is not empty, so the
    #: variable is set, and nothing matches, so every violation is a warning.
    match_none_wildcard: str = field(default="", init=False)

    def wildcards(self, step: "Step") -> list[str]:
        configured = (
            step.config[self.corner_var] or step.config[self.fallback_corner_var]
        )
        assert configured is not None, (
            f"neither '{self.corner_var}' nor '{self.fallback_corner_var}' is "
            f"set, and the latter has no default."
        )
        return [
            wildcard for wildcard in configured if wildcard != self.match_none_wildcard
        ]

    def check(self, step: "Step", metrics: dict) -> None:
        basename = f"{self.metric}__corner"
        measured = {key: value for key, value in metrics.items() if basename in key}
        if not measured:
            return

        corners = {parse_metric_modifiers(key)[1]["corner"] for key in measured.keys()}
        wildcards = set(self.wildcards(step))
        corner_filter = Filter(wildcards)

        matched_wildcards: set[str] = set()
        for corner in corners:
            matched_wildcards.update(corner_filter.get_matching_wildcards(corner))
        unmatched_wildcards = wildcards - matched_wildcards

        matched_corners = set(corner_filter.filter(corners))
        violating = {
            corner
            for corner in corners
            if measured[f"{basename}:{corner}"] > Decimal(0)
        }
        failing = violating.intersection(matched_corners)
        warning = violating - failing

        errors: list[str] = []
        if unmatched_wildcards:
            errors.append(
                f"One or more wildcards specified in {self.corner_var} did not "
                f"match any corners:"
            )
            errors.extend(f"- {wildcard}" for wildcard in sorted(unmatched_wildcards))

        if warning:
            warnings = [
                f"{self.violation_type.title()} violations found in the following corners:"
            ]
            warnings.extend(f"* {corner}" for corner in sorted(warning))
            logger.bind(step=step.id).warning("\n".join(warnings))

        if failing:
            errors.append(
                f"{self.violation_type.title()} violations found in the following corners:"
            )
            errors.extend(f"* {corner}" for corner in sorted(failing))
        else:
            logger.log("VERBOSE", f"No {self.violation_type} violations found")

        if errors:
            _raise(step, True, "\n".join(errors))


#: What a step's ``gates`` may hold. The two kinds share no base class because
#: they share no behaviour: one compares a number against a limit, the other
#: partitions a set of corners. They share only the point at which they run.
Gate = MetricGate | CornerMetricGate
