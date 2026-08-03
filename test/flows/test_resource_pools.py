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

The tests from the bottom of this file down (from
``test_c1_...`` onward) are the fix-round-1 regression tests for the task 6
review: C1 (a deadlock the engine's original admission scheme allowed, fixed
by bounding how many jobs it hands the executor at once), the free-worker
bound's own invariant, and I1 (a parked job waiting out an entire multi-pass
ring instead of being woken as soon as any one pass releases a pool).

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

    from librelane.config import variable
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

        class Config(Step.Config):
            POOL_SWEEP_POINT: int = variable(description="point", default=0)

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
                    "select": "score min",
                    "resources": ["seats"],
                    "iterations": {"POOL_SWEEP_POINT": [1, 2, 3, 4, 5]},
                },
            },
        }
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert max_concurrent == 2


# ---------------------------------------------------------------------------
# Fix round 1 (task 6 review): C1 (deadlock), the free-worker bound it is
# fixed with, and I1 (a parked job outliving a ring's per-pass releases).
# ---------------------------------------------------------------------------


@mock_variables([flow_module, step_module])
def test_c1_a_ring_and_a_job_sharing_a_pool_on_a_one_worker_executor_does_not_deadlock(
    minimal_design, mock_pdk, mocker
):
    """
    Task 6 review, finding C1: before the fix, an ordinary job's
    ``try_acquire`` succeeded and consumed a pool grant on the *main*
    thread, strictly before the job was ever handed to the executor --
    independent of whether a worker was actually free there. With a single
    worker already occupied by a ring's own submission, the job's task sat
    queued behind it: holding the grant, but never running to release it.
    Meanwhile the ring's worker thread, once it reached its own pool-owning
    member, blocked in ``acquire()`` waiting on exactly that grant. Neither
    side could make progress: the job needed a worker only the ring's own
    (permanently blocked) task occupied, and the ring needed a release only
    the job could perform.

    Reproduced deterministically rather than by timing luck:

    - ``Net.enabled`` is patched to always place the ring ahead of the
      ordinary job. Which of the two the scheduler tries to admit first
      otherwise depends on set-iteration order in
      ``FlowSpec.collapsed_edges()`` -- hash-seed-dependent, per the review
      -- and only the ring-first order is the one that risked deadlocking
      pre-fix; the other order never contended the pool this way regardless
      of the fix, so leaving it to chance would make this test's outcome
      arbitrary rather than a real regression guard.
    - ``Workflow._run_loop`` is patched to sleep briefly at its own entry,
      before doing anything else. This runs on the ring's worker thread, so
      it guarantees the *main* thread has long finished admitting the
      ordinary job -- taking the pool grant, pre-fix -- before the ring's
      worker ever reaches its own pool-acquiring member; the two are
      otherwise racing a synchronous main-thread check against a freshly
      spawned OS thread; the delay removes that race rather than hoping to
      win it.

    Run on a background thread with a generous join timeout, so that a
    regression here fails this one test rather than hanging the whole
    session.
    """
    import threading
    import time

    from librelane.common import ContextPropagatingThreadPoolExecutor, get_tpe, set_tpe
    from librelane.flows.engine import Workflow
    from librelane.flows.net import Net
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    @Step.factory.register()
    class RingMember(Step):
        id = "Test.C1RingMember"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {"x": state_in.metrics.get("x", 0) + 1}

    @Step.factory.register()
    class RingGate(Step):
        id = "Test.C1RingGate"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    @Step.factory.register()
    class Job(Step):
        id = "Test.C1Job"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "C1",
            "resources": {"seat": 1},
            "jobs": {
                "resize": {
                    "needs": ["sta"],
                    "steps": ["Test.C1RingMember"],
                    "resources": ["seat"],
                },
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.C1RingGate"],
                    # Converges cleanly at pass 2 (the same shape
                    # test_loops.py's own two-member ring uses), so the run
                    # either completes or hangs -- no deferred-error path to
                    # tell apart from the deadlock this test is checking for.
                    "until": "metric::x >= 2",
                    "max": 3,
                },
                "job": {
                    "steps": ["Test.C1Job"],
                    "resources": ["seat"],
                },
            },
        }
    )

    real_enabled = Net.enabled

    def ordered_enabled(self):
        # The ring's gate id ('sta') is what net.enabled() actually returns
        # for the whole ring; forcing it ahead of the plain job 'job' is
        # what forces ring-first admission on every call.
        order = {"sta": 0, "job": 1}
        return sorted(real_enabled(self), key=lambda n: order.get(n, 2))

    mocker.patch.object(Net, "enabled", ordered_enabled)

    real_run_loop = Workflow._run_loop

    def delayed_run_loop(self, *args, **kwargs):
        time.sleep(0.3)
        return real_run_loop(self, *args, **kwargs)

    mocker.patch.object(Workflow, "_run_loop", delayed_run_loop)

    previous = get_tpe()
    pool = ContextPropagatingThreadPoolExecutor(max_workers=1)
    set_tpe(pool)

    caught: list[Exception] = []

    def target():
        try:
            Workflow(spec, minimal_design, **mock_pdk).start(tag="t")
        except Exception as e:
            caught.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=15)

    set_tpe(previous)
    pool.shutdown(wait=False)

    assert not thread.is_alive(), (
        "the run did not complete within 15s -- this is the C1 deadlock "
        "(task 6 review): the ring blocked in pools.acquire() waiting on a "
        "grant the ordinary job held but was never given a worker to run "
        "and release it from"
    )
    assert caught == []


@pytest.mark.usefixtures("two_workers")
@mock_variables([flow_module, step_module])
def test_the_engine_never_submits_more_jobs_than_it_has_workers_for(
    minimal_design, mock_pdk, mocker
):
    """
    The invariant the C1 fix depends on: the engine never hands
    ``get_tpe().submit`` more work than the executor has workers for, so a
    submitted future is never merely queued behind another -- it starts
    running as soon as it is submitted.

    Five independent jobs (no ``needs`` between them) are all enabled at
    once against a two-worker executor, each holding its worker for 0.3s --
    long enough that the main thread's own submission loop (a handful of
    synchronous Python statements per job) cannot possibly outrun it. A spy
    wrapping the executor's own ``submit`` asserts, at the moment of every
    call, that fewer than two futures returned by *earlier* calls are still
    outstanding. Before the fix (no free-worker check at all), all five
    would be submitted in the same pass and this would fail on the third
    call, with two still-running futures already outstanding.
    """
    import time

    from librelane.common import get_tpe
    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    @Step.factory.register()
    class Slow(Step):
        id = "Test.OversubscribeSlow"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            time.sleep(0.3)
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Oversubscribe",
            "jobs": {
                f"job{i}": {"steps": ["Test.OversubscribeSlow"]} for i in range(5)
            },
        }
    )

    pool = get_tpe()
    real_submit = pool.submit
    submitted_futures = []

    def spy_submit(fn, *args, **kwargs):
        still_outstanding = sum(1 for f in submitted_futures if not f.done())
        assert still_outstanding < 2, (
            f"get_tpe().submit was called with {still_outstanding} "
            f"earlier-submitted futures still outstanding against a "
            f"2-worker executor -- the engine oversubscribed it (task 6 "
            f"review, finding C1)"
        )
        future = real_submit(fn, *args, **kwargs)
        submitted_futures.append(future)
        return future

    mocker.patch.object(pool, "submit", side_effect=spy_submit)

    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    assert len(submitted_futures) == 5


@mock_variables([flow_module, step_module])
def test_i1_a_parked_job_is_admitted_before_a_multi_pass_ring_s_future_resolves(
    minimal_design, mock_pdk
):
    """
    Task 6 review, finding I1: only a ring's own, one, multi-pass future
    ever sits in ``pending``; its members' per-pass acquire/release cycling
    inside ``_run_loop`` is invisible to a plain ``wait(pending)``. Before
    the wakeup sentinel, a job parked behind a pool a ring also uses would
    not be reconsidered until the ring's *entire* run finished, not as soon
    as some pass released the pool.

    ``seed`` fires after a short, pool-free delay so ``job`` (which needs
    it) becomes enabled only once the ring's worker has had a substantial
    head start -- long enough to have already acquired the pool for its
    first pass, so ``job`` is guaranteed to find it taken and park at least
    once, genuinely exercising the wakeup path rather than winning the seat
    outright. Each ring pass holds the pool for much longer than ``job``
    itself takes to run, so if the wakeup fires promptly -- on the first
    pass's release -- ``job``'s own call is recorded long before the ring's
    later, still-slow passes are. Without the fix, ``job`` would only be
    admitted once the whole ring's future resolves, i.e. after every pass,
    and its call would be recorded last instead.
    """
    import threading
    import time

    from librelane.flows.engine import Workflow
    from librelane.flows.spec import FlowSpec
    from librelane.steps import Step

    calls: list[str] = []
    calls_lock = threading.Lock()

    @Step.factory.register()
    class Seed(Step):
        id = "Test.WakeupSeed"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            time.sleep(0.15)
            with calls_lock:
                calls.append("seed")
            return {}, {}

    @Step.factory.register()
    class RingMember(Step):
        id = "Test.WakeupRingMember"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            with calls_lock:
                calls.append("member")
            time.sleep(0.2)
            return {}, {"x": state_in.metrics.get("x", 0) + 1}

    @Step.factory.register()
    class RingGate(Step):
        id = "Test.WakeupRingGate"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            return {}, {}

    @Step.factory.register()
    class Job(Step):
        id = "Test.WakeupJob"
        inputs = []
        outputs = []

        def run(self, state_in, **kwargs):
            with calls_lock:
                calls.append("job")
            return {}, {}

    spec = FlowSpec.model_validate(
        {
            "name": "Wakeup",
            "resources": {"seat": 1},
            "jobs": {
                "seed": {"steps": ["Test.WakeupSeed"]},
                "resize": {
                    "needs": ["sta"],
                    "steps": ["Test.WakeupRingMember"],
                    "resources": ["seat"],
                },
                "sta": {
                    "needs": ["resize"],
                    "steps": ["Test.WakeupRingGate"],
                    # Converges cleanly at pass 3 (x increments by 1 per
                    # pass), rather than exhausting: a deferred error would
                    # fail the run at the end for a reason unrelated to what
                    # this test checks.
                    "until": "metric::x >= 3",
                    "max": 3,
                },
                "job": {
                    "needs": ["seed"],
                    "steps": ["Test.WakeupJob"],
                    "resources": ["seat"],
                },
            },
        }
    )
    Workflow(spec, minimal_design, **mock_pdk).start(tag="t")

    job_index = calls.index("job")
    last_member_index = len(calls) - 1 - calls[::-1].index("member")
    assert job_index < last_member_index, (
        f"'job' ran at position {job_index}, no earlier than the ring's "
        f"last pass at {last_member_index}: it was not admitted until the "
        f"ring's whole (3-pass) future resolved, the I1 bug (task 6 "
        f"review) the wakeup sentinel is meant to fix"
    )
