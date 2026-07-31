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

from loguru import logger

import sys
import psutil
import contextvars
import datetime
from threading import Event, Thread
from typing import (
    TypeVar,
)


from librelane.common import (
    format_size,
    format_elapsed_time,
)

VT = TypeVar("VT")


class ProcessStatsThread(Thread):
    def __init__(self, process: psutil.Popen, interval: float = 0.1):
        Thread.__init__(
            self,
        )
        self.process = process
        self.result = None
        self.interval = interval
        self._stopping = Event()
        # Before Python 3.14 a new thread starts with an empty context, so the
        # step and flow-run bindings that attribute this thread's one warning
        # would be lost. Captured here, on the thread that constructs the
        # monitor, because ``run`` executes on the new thread where they are
        # already gone. 3.14 inherits the context itself when
        # ``thread_inherit_context`` is set, which makes this redundant but not
        # harmful -- and the flag is not guaranteed. Note the name: ``Thread``
        # itself owns ``_context`` on 3.14.
        self._log_context = contextvars.copy_context()
        self.time = {
            "cpu_time_user": 0.0,
            "cpu_time_system": 0.0,
            "runtime": 0.0,
        }
        if sys.platform == "linux":
            self.time["cpu_time_iowait"] = 0.0

        self.peak_resources = {
            "cpu_percent": 0.0,
            "memory_rss": 0.0,
            "memory_vms": 0.0,
            "threads": 0.0,
        }
        self.avg_resources = {
            "cpu_percent": 0.0,
            "memory_rss": 0.0,
            "memory_vms": 0.0,
            "threads": 0.0,
        }

    def run(self):
        self._log_context.run(self._run)

    def _run(self):
        try:
            count = 1
            status = self.process.status()
            now = datetime.datetime.now()
            while status not in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]:
                with self.process.oneshot():
                    cpu = self.process.cpu_percent()
                    memory = self.process.memory_info()
                    cpu_time = self.process.cpu_times()
                    threads = self.process.num_threads()

                    runtime = datetime.datetime.now() - now
                    self.time["runtime"] = runtime.total_seconds()
                    self.time["cpu_time_user"] = cpu_time.user
                    self.time["cpu_time_system"] = cpu_time.system
                    if sys.platform == "linux":
                        self.time["cpu_time_iowait"] = cpu_time.iowait  # type: ignore

                    current: dict[str, float] = {}
                    current["cpu_percent"] = cpu
                    current["memory_rss"] = memory.rss
                    current["memory_vms"] = memory.vms
                    current["threads"] = threads

                    for key in self.peak_resources.keys():
                        self.peak_resources[key] = max(
                            current[key], self.peak_resources[key]
                        )

                        # moving average
                        self.avg_resources[key] = (
                            (count * self.avg_resources[key]) + current[key]
                        ) / (count + 1)

                    count += 1
                    if self._stopping.wait(self.interval):
                        return
                    status = self.process.status()
        except psutil.Error as e:
            message = e.msg  # type: ignore[attr-defined]
            for normal in ["process no longer exists", "but it's a zombie"]:
                if normal in message:
                    return
            logger.warning(f"Process resource tracker encountered an error: {e}")

    def stop(self) -> None:
        """
        Asks the monitor to return at its next tick.

        The loop otherwise runs until the process it watches dies, so a caller
        abandoning the process -- because reading its output failed, say --
        would leave the monitor polling forever.
        """
        self._stopping.set()

    def stats_as_dict(self):
        return {
            "time": {k: format_elapsed_time(self.time[k]) for k in self.time},
            "peak_resources": {
                k: (
                    self.peak_resources[k]
                    if "memory" not in k
                    else format_size(int(self.peak_resources[k]))
                )
                for k in self.peak_resources
            },
            "avg_resources": {
                k: (
                    self.avg_resources[k]
                    if "memory" not in k
                    else format_size(int(self.avg_resources[k]))
                )
                for k in self.avg_resources
            },
        }
