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
A step's ``outputs`` are a promise, and nothing in the runtime makes a step keep
it: :meth:`librelane.steps.Step.start` enforces declared *inputs* only. A step
that declares an output it never writes therefore fails silently, and this
fork's stage contracts then promise that view to the next stage on the step's
behalf, which is how ``pre_pnr_sta`` came to be contracted to produce an SDC
that no OpenSTA script ever wrote.

This checks the promise against the two places an OpenROAD step can keep it:
its Tcl script, and its own ``run``.
"""

import inspect
from pathlib import Path

import pytest

import librelane.steps  # noqa: F401
from librelane.steps import Step
from librelane.steps.openroad.base import OpenROADStep

pytestmark = pytest.mark.all


def _openroad_steps() -> list[type[Step]]:
    result = []
    for step_id in sorted(Step.factory.list()):
        step = Step.factory.get(step_id)
        assert step is not None
        if not issubclass(step, OpenROADStep):
            continue
        if not step.outputs:
            continue
        result.append(step)
    return result


def _script_of(step: type[Step]) -> str:
    # These implementations return a constant, so a bare instance suffices;
    # building a real one would require a complete configuration.
    return Path(str(object.__new__(step).get_script_path())).read_text()


def _run_sources(step: type[Step]) -> str:
    """Every ``run`` in the step's MRO, so a view a base class adds counts."""
    sources = ""
    for klass in step.__mro__:
        if "run" in klass.__dict__:
            sources += inspect.getsource(klass.__dict__["run"])
    return sources


def test_openroad_steps_write_the_views_they_declare():
    """
    An OpenROAD step's outputs reach the state one of two ways: the script
    writes the file the base ``run`` then picks up out of ``SAVE_<VIEW>``, or
    the step's own ``run`` puts the view in its views update. A declared output
    with neither behind it is a promise the step cannot keep.
    """
    unbacked = {}
    for step in _openroad_steps():
        script = _script_of(step)
        # write_views (scripts/openroad/common/io.tcl) writes every view the
        # base mechanism knows about; a script may also write one by name.
        if "write_views" in script:
            continue
        run_sources = _run_sources(step)
        for view in step.outputs:
            if f"SAVE_{view.id.upper()}" in script or f".{view.extension}" in script:
                continue
            if f"DesignFormat.{view.id.upper()}" in run_sources:
                continue
            unbacked.setdefault(step.id, []).append(view.id)

    assert unbacked == {}, (
        "these steps declare outputs that neither their script nor their run() "
        f"ever writes: {unbacked}"
    )


def test_stage_contracts_only_promise_views_a_step_writes():
    """
    The stage-level consequence of the same lie. ``StageRegistry`` already
    checks a stage's ``provides`` against its provider's *declared* outputs at
    import time, so it is only as truthful as those declarations; this checks
    them against the step behaviour above.
    """
    from librelane.stages.registry import StageRegistry
    from librelane.stages.stage import Stage

    unbacked = {}
    for registration in StageRegistry.list():
        stage = Stage.factory.get(registration.stage)
        assert stage is not None
        promised = set(stage.provides) | set(registration.provides)
        for view in promised:
            producers = [
                step
                for step in registration.steps
                if view in step.outputs and issubclass(step, OpenROADStep)
            ]
            for step in producers:
                script = _script_of(step)
                if "write_views" in script:
                    break
                if (
                    f"SAVE_{view.id.upper()}" in script
                    or f".{view.extension}" in script
                    or f"DesignFormat.{view.id.upper()}" in _run_sources(step)
                ):
                    break
            else:
                if producers:
                    unbacked.setdefault(
                        (registration.stage, registration.provider), []
                    ).append(view.id)

    assert unbacked == {}, (
        "these stage contracts promise a view whose only declared producer "
        f"never writes it: {unbacked}"
    )
