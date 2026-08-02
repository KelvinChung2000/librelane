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
Named resource pools that bound how many jobs use a scarce tool at once.

A pool lives in the scheduler, not on the net. The net's tokens are
:class:`~librelane.state.State` objects, deposited by a producer and joined by
a consumer; a pool's tokens are anonymous, carry nothing and are returned
rather than consumed. Modelling a pool as a place with capacity above one
would thread a second token kind through every marking operation so the join
rule can ignore it, machinery in service of a diagram. A pool is instead a
lock-protected set of counters that whatever runs work -- the scheduler
itself, a loop pass, a sweep execution -- checks or blocks on directly.

See "Resource pools" in
``docs/superpowers/specs/2026-08-01-workflow-loops-conditionals-resources-design.md``
for the design this module implements.
"""

import threading
from collections import Counter
from collections.abc import Mapping, Sequence


class ResourcePools:
    """
    A set of named counters, acquired and released all-or-nothing under one
    lock.

    Acquisition is all-or-nothing: a caller either takes every pool it named
    at once or takes none of them, so a waiter never holds one pool while it
    waits on another. That is what makes the pools deadlock-free whatever a
    document declares -- hold-and-wait cannot arise if nothing is ever held
    while waiting, whatever order jobs happen to name their pools in.

    Parameters
    ----------
    capacities : Mapping[str, int]
        Each pool's total capacity, already resolved to a concrete positive
        integer by the caller -- :meth:`librelane.flows.engine.Workflow._resolve_resource_pools`
        is the one caller, and it is where a variable capacity is read out of
        the flow's configuration and a literal one is refused below 1, so
        this class itself trusts every value it is given. Empty for a
        document that declares no ``resources``, which is also the shape
        every method below is fastest for: called for every job whether or
        not it names a pool, an empty ``names`` sequence returns without
        acquiring the lock at all.
    """

    def __init__(self, capacities: Mapping[str, int]) -> None:
        self._capacities = dict(capacities)
        self._available = dict(capacities)
        self._condition = threading.Condition()

    def try_acquire(self, names: Sequence[str]) -> bool:
        """
        Non-blocking, all-or-nothing acquisition.

        Parameters
        ----------
        names : Sequence[str]
            The pools to take one slot from each of. A name repeated in the
            sequence takes that many slots from that one pool, though no
            caller in the engine repeats one: a job's own ``resources`` is
            already refused a duplicate at load time.

        Returns
        -------
        bool
            ``True``, and every named pool now holds one fewer free slot; or
            ``False``, and nothing was taken from any of them. Never a
            partial grant.
        """
        if not names:
            return True
        with self._condition:
            if not self._fits(names):
                return False
            self._take(names)
            return True

    def acquire(self, names: Sequence[str]) -> None:
        """
        Blocking, all-or-nothing acquisition.

        Parameters
        ----------
        names : Sequence[str]
            As :meth:`try_acquire`.

        Blocks on the internal condition until every named pool has a free
        slot, then takes every one of them at once. Safe to call from a
        worker thread that holds no slot of its own while it waits: the only
        callers of this method are loop passes and sweep executions, and a
        waiter here is never itself the holder something else is waiting on,
        so this cannot deadlock against :meth:`try_acquire`'s callers on the
        scheduling thread either.
        """
        if not names:
            return
        with self._condition:
            self._condition.wait_for(lambda: self._fits(names))
            self._take(names)

    def release(self, names: Sequence[str]) -> None:
        """
        Returns slots taken by an earlier :meth:`try_acquire` or
        :meth:`acquire` call, and wakes every waiter to re-check whether it
        now fits.

        Parameters
        ----------
        names : Sequence[str]
            The pools to return one slot to each of -- exactly the sequence
            that was acquired. Called from the ``finally`` of whatever
            acquired it, on every exit path, success or failure alike, so a
            slot is never leaked.
        """
        if not names:
            return
        with self._condition:
            for name, count in Counter(names).items():
                self._available[name] += count
            self._condition.notify_all()

    def _fits(self, names: Sequence[str]) -> bool:
        """
        Whether every pool named in ``names`` currently has enough free
        slots to satisfy every occurrence of its name. Called under
        ``self._condition`` only.
        """
        counts = Counter(names)
        return all(self._available[name] >= count for name, count in counts.items())

    def _take(self, names: Sequence[str]) -> None:
        """
        Decrements every pool named in ``names`` by how many times it
        occurs. Called under ``self._condition`` only, and only once
        :meth:`_fits` has already confirmed every one of them has room --
        this method does not itself check.
        """
        for name, count in Counter(names).items():
            self._available[name] -= count
