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
import re
import pathlib

import pytest

pytestmark = pytest.mark.all

_ROOT = pathlib.Path(__file__).parent.parent.parent / "librelane"

# Emissions from Tcl, e.g. write_metric_int "design__die__bbox" $value
_TCL_EMISSION = re.compile(r'write_metric_(?:int|str|num|float)\s+"([^"]+)"')
# Metric-shaped string literals in Python. Anchored on the METRICS2.1 `__`
# separator so it does not go fishing through unrelated strings.
_PY_EMISSION = re.compile(r'"([a-z][a-z0-9_]*__[a-z0-9_]+(?:__[a-z0-9_:${}]+)*)"')


def _emitted_metric_names():
    names = set()
    for path in (_ROOT / "scripts").rglob("*.tcl"):
        names.update(_TCL_EMISSION.findall(path.read_text(encoding="utf8")))
    sources = list((_ROOT / "steps").rglob("*.py"))
    sources += list((_ROOT / "scripts" / "odbpy").rglob("*.py"))
    for path in sources:
        names.update(_PY_EMISSION.findall(path.read_text(encoding="utf8")))
    return names


def _base_name(name):
    from librelane.common.metrics.util import parse_metric_modifiers

    base, _ = parse_metric_modifiers(name)
    # Tcl interpolates the corner into the name, which the modifier parser
    # cannot split because the value is still a `$variable`.
    return base.split("__corner")[0]


@pytest.mark.parametrize(
    "name",
    [
        "design__die__bbox",
        "design__core__bbox",
        "design__critical_disconnected_pin__count",
        "design__power_grid_violation__count",
        "klayout__drc_error__count",
        "klayout__density_error__count",
        "klayout__antenna_error__count",
    ],
)
def test_previously_unregistered_metrics_are_registered(name):
    """Unregistered metrics are silently dropped from aggregation and from
    metric comparison, so a checker can gate the flow on a value CI never
    reports."""
    import librelane.common.metrics.library  # noqa: F401
    from librelane.common.metrics.metric import Metric

    assert name in Metric.by_name


def test_every_emitted_metric_is_registered():
    import librelane.common.metrics.library  # noqa: F401
    from librelane.common.metrics.metric import Metric

    unregistered = sorted(
        {
            base
            for name in _emitted_metric_names()
            # Cell names share the double-underscore shape of a metric name.
            if not (base := _base_name(name)).startswith(("sky130", "gf180", "sg13g2"))
            if base not in Metric.by_name
        }
    )

    assert unregistered == []


def test_the_scan_actually_finds_emissions():
    """Guard against the regexes silently matching nothing."""
    names = _emitted_metric_names()

    assert len(names) > 50
    assert "design__die__bbox" in names
    assert "klayout__drc_error__count" in names
