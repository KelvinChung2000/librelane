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
Named resource pools: :class:`librelane.flows.resources.ResourcePools` itself,
all-or-nothing and blocking, and the engine's three admission points --
ordinary jobs and sweep passes admitted with a non-blocking check on the
scheduling thread, loop members admitted with a blocking one on a worker
thread.

Fake steps throughout, no real tools -- the same style ``test_engine.py``,
``test_loops.py`` and ``test_sweep.py`` use.
"""

import pytest

from librelane.flows import flow as flow_module
from librelane.steps import step as step_module

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _int_var(name: str, default: int) -> dict:
    return {"name": name, "type": "int", "description": "x", "default": default}


# ---------------------------------------------------------------------------
# ResourcePools itself: no engine, no threads other than the test's own.
# ---------------------------------------------------------------------------


def test_try_acquire_is_all_or_nothing_across_two_pools():
    from librelane.flows.resources import ResourcePools

    pools = ResourcePools({"a": 1, "b": 1})
    assert pools.try_acquire(["a"]) is True

    # 'a' is taken and 'b' is free: acquiring both together must refuse
    # rather than take 'b' alone, and the refusal must leave 'b' untouched.
    assert pools.try_acquire(["a", "b"]) is False
    assert pools.try_acquire(["b"]) is True


def test_try_acquire_refuses_without_blocking_when_full():
    from librelane.flows.resources import ResourcePools

    pools = ResourcePools({"a": 1})
    assert pools.try_acquire(["a"]) is True
    # Must return, not wait: a refusal is a plain 'no', never a block.
    assert pools.try_acquire(["a"]) is False


def test_acquire_blocks_until_release():
    import threading

    from librelane.flows.resources import ResourcePools

    pools = ResourcePools({"a": 1})
    assert pools.try_acquire(["a"]) is True  # the main thread holds the slot

    acquired = threading.Event()

    def waiter():
        pools.acquire(["a"])
        acquired.set()

    t = threading.Thread(target=waiter)
    t.start()
    try:
        # Every chance to have raced ahead if 'acquire' did not actually
        # block; the event must still be unset.
        assert not acquired.wait(timeout=0.3)

        pools.release(["a"])
        assert acquired.wait(timeout=5)
    finally:
        t.join(timeout=5)


def test_release_wakes_a_blocked_waiter():
    import threading

    from librelane.flows.resources import ResourcePools

    pools = ResourcePools({"a": 1})
    assert pools.try_acquire(["a"]) is True

    first_done = threading.Event()
    second_done = threading.Event()

    t1 = threading.Thread(target=lambda: (pools.acquire(["a"]), first_done.set()))
    t2 = threading.Thread(target=lambda: (pools.acquire(["a"]), second_done.set()))
    t1.start()
    t2.start()
    try:
        # Neither waiter can hold the one slot yet.
        assert not first_done.wait(timeout=0.2)
        assert not second_done.wait(timeout=0.1)

        # One release wakes both (notify_all), but only one of them actually
        # re-fits and takes the slot; the other goes back to waiting.
        pools.release(["a"])
        assert first_done.wait(timeout=5) or second_done.wait(timeout=5)
        winner, loser = (
            (first_done, second_done)
            if first_done.is_set()
            else (second_done, first_done)
        )
        assert not loser.wait(timeout=0.2)

        pools.release(["a"])
        assert loser.wait(timeout=5)
    finally:
        t1.join(timeout=5)
        t2.join(timeout=5)


def test_empty_names_never_touches_the_lock():
    import threading

    from librelane.flows.resources import ResourcePools

    pools = ResourcePools({"a": 1})
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def hold_the_lock():
        with pools._condition:
            holder_ready.set()
            release_holder.wait(timeout=5)

    t = threading.Thread(target=hold_the_lock)
    t.start()
    try:
        assert holder_ready.wait(timeout=5)
        # If any of the three touched 'self._condition', it would block
        # behind the thread above and time out instead of returning at once.
        assert pools.try_acquire([]) is True
        pools.acquire([])
        pools.release([])
    finally:
        release_holder.set()
        t.join(timeout=5)


# ---------------------------------------------------------------------------
# The engine's admission points.
# ---------------------------------------------------------------------------


@pytest.fixture
def two_workers():
    """Pins the process-wide pool to two workers, so two contending jobs
    genuinely have somewhere to run at once and a one-seat pool is what
    serializes them, not a starved executor."""
    from librelane.common import ContextPropagatingThreadPoolExecutor, get_tpe, set_tpe

    previous = get_tpe()
    pool = ContextPropagatingThreadPoolExecutor(max_workers=2)
    set_tpe(pool)
    yield
    set_tpe(previous)
    pool.shutdown()


@pytest.fixture
def five_workers():
    """As :func:`two_workers`, wide enough that a five-point sweep could run
    every pass at once if nothing else held it back."""
    from librelane.common import ContextPropagatingThreadPoolExecutor, get_tpe, set_tpe

    previous = get_tpe()
    pool = ContextPropagatingThreadPoolExecutor(max_workers=5)
    set_tpe(pool)
    yield
    set_tpe(previous)
    pool.shutdown()


@pytest.mark.usefixtures("two_workers")
@mock_variables([flow_module, step_module])
def test_a_one_seat_pool_serializes_two_enabled_jobs(minimal_design, mock_pdk):
    import threading
    import time

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    lock = threading.Lock()
    current = 0
    max_concurrent = 0

    @Step.factory.register()
    class Hold(Step):
        id = "Test.PoolHold"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            nonlocal current, max_concurrent
            with lock:
                current += 1
                max_concurrent = max(max_concurrent, current)
            time.sleep(0.2)
            with lock:
                current -= 1
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "PoolSerial",
            "resources": {"seat": 1},
            "jobs": {
                "a": {"steps": ["Test.PoolHold"], "resources": ["seat"]},
                "b": {"steps": ["Test.PoolHold"], "resources": ["seat"]},
            },
        }
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert max_concurrent == 1


@pytest.mark.usefixtures("two_workers")
@mock_variables([flow_module, step_module])
def test_capacity_from_a_configuration_variable_is_resolved(minimal_design, mock_pdk):
    import threading
    import time

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    lock = threading.Lock()
    current = 0
    max_concurrent = 0

    @Step.factory.register()
    class Hold(Step):
        id = "Test.PoolVarHold"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            nonlocal current, max_concurrent
            with lock:
                current += 1
                max_concurrent = max(max_concurrent, current)
            time.sleep(0.2)
            with lock:
                current -= 1
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "PoolVar",
            "resources": {"seat": "MAX_SEATS"},
            "config": [_int_var("MAX_SEATS", 1)],
            "jobs": {
                "a": {"steps": ["Test.PoolVarHold"], "resources": ["seat"]},
                "b": {"steps": ["Test.PoolVarHold"], "resources": ["seat"]},
            },
        }
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert max_concurrent == 1


@mock_variables([flow_module, step_module])
def test_a_variable_capacity_below_one_names_the_pool_variable_and_value(
    minimal_design, mock_pdk
):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowException
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    @Step.factory.register()
    class NoOp(Step):
        id = "Test.PoolBelowOneNoOp"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "PoolBelowOne",
            "resources": {"seat": "MAX_SEATS"},
            "config": [_int_var("MAX_SEATS", 0)],
            "jobs": {
                "a": {"steps": ["Test.PoolBelowOneNoOp"], "resources": ["seat"]},
            },
        }
    )

    with pytest.raises(FlowException) as exc_info:
        Workflow(spec, minimal_design, **mock_pdk)

    message = str(exc_info.value)
    assert "seat" in message
    assert "MAX_SEATS" in message
    assert "0" in message


@mock_variables([flow_module, step_module])
def test_a_failing_job_releases_its_slot_for_the_next(minimal_design, mock_pdk):
    from librelane.flows.engine import Workflow
    from librelane.flows.flow import FlowError
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step
    from librelane.steps.step.exceptions import StepError

    ran = []

    @Step.factory.register()
    class Fails(Step):
        id = "Test.PoolFails"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            raise StepError("boom")

    @Step.factory.register()
    class Succeeds(Step):
        id = "Test.PoolSucceeds"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            ran.append("succeeds")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "PoolFailRelease",
            "resources": {"seat": 1},
            "jobs": {
                "fails": {"steps": ["Test.PoolFails"], "resources": ["seat"]},
                "succeeds": {"steps": ["Test.PoolSucceeds"], "resources": ["seat"]},
            },
        }
    )
    flow = Workflow(spec, minimal_design, **mock_pdk)

    # A capacity-1 pool means only one of the two jobs ever runs at once,
    # whichever the scheduler happens to admit first; the other parks. If
    # the failing job's slot were not released, the parked job would starve
    # forever and this would hang instead of raising.
    with pytest.raises(FlowError):
        flow.start(tag="t")

    assert ran == ["succeeds"]


@pytest.mark.usefixtures("five_workers")
@mock_variables([flow_module, step_module])
def test_a_two_seat_pool_runs_a_five_point_sweep_two_at_a_time(
    minimal_design, mock_pdk
):
    import threading
    import time

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    lock = threading.Lock()
    current = 0
    max_concurrent = 0

    @Step.factory.register()
    class Meet(Step):
        id = "Test.PoolSweepMeet"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            nonlocal current, max_concurrent
            with lock:
                current += 1
                max_concurrent = max(max_concurrent, current)
            time.sleep(0.2)
            with lock:
                current -= 1
            return {}, {"score": 1}

    spec = FlowSpec.model_validate(
        {
            "name": "PoolSweep",
            "resources": {"seats": 2},
            "jobs": {
                "sweep": {
                    "steps": ["Test.PoolSweepMeet"],
                    "mode": "sweep",
                    "select": "score min",
                    "resources": ["seats"],
                    "iterations": [{}, {}, {}, {}, {}],
                },
            },
        }
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert max_concurrent == 2
