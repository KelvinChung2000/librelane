# Copyright 2025 LibreLane Contributors
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
Runtime debug tracking for async job execution.

Provides detailed visibility into job lifecycle, resource usage, and potential
deadlocks. Enabled via LIBRELANE_DEBUG_TRACKING=1 environment variable.
"""

import os
import json
import time
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ProcessPoolExecutor


@dataclass
class JobMetric:
    """Metrics for a single async job."""

    job_id: str
    step_id: str
    submit_time: float
    start_time: Optional[float] = None
    complete_time: Optional[float] = None

    @property
    def wait_duration(self) -> Optional[float]:
        """Time spent waiting in queue."""
        if self.start_time:
            return self.start_time - self.submit_time
        return None

    @property
    def execution_duration(self) -> Optional[float]:
        """Time spent executing."""
        if self.complete_time and self.start_time:
            return self.complete_time - self.start_time
        return None

    @property
    def total_duration(self) -> Optional[float]:
        """Total time from submit to complete."""
        if self.complete_time:
            return self.complete_time - self.submit_time
        return None


@dataclass
class ResourceSample:
    """Resource usage sample at a point in time."""

    timestamp: float
    pending_jobs: int
    active_jobs: int
    completed_jobs: int


class DebugTracker:
    """
    Thread-safe debug tracker for async job execution.

    Tracks:
    - Job lifecycle: submission, start, completion timestamps
    - Resource usage: queue depth, active workers (sampled periodically)
    - Deadlock detection: long wait times, potential hangs
    - File I/O: (Future: lock contention tracking)

    Usage:
        tracker = DebugTracker(executor)
        tracker.track_submit("job-1", "synthesis")
        # ... job runs ...
        tracker.export_report("debug_report.json")
    """

    def __init__(self, executor: Optional[ProcessPoolExecutor] = None):
        """
        Initialize debug tracker.

        :param executor: ProcessPoolExecutor to monitor (optional)
        """
        self.enabled = os.getenv("LIBRELANE_DEBUG_TRACKING") == "1"
        if not self.enabled:
            return

        self.executor = executor
        self.jobs: Dict[str, JobMetric] = {}
        self.resource_samples: List[ResourceSample] = []
        self.warnings: List[str] = []
        self.lock = threading.Lock()
        self._stop_sampling = False

        # Start resource sampling thread
        self.sampling_thread = threading.Thread(
            target=self._sample_loop, daemon=True
        )
        self.sampling_thread.start()

    def track_submit(self, job_id: str, step_id: str) -> None:
        """
        Track job submission.

        :param job_id: Unique job identifier
        :param step_id: Step ID being executed
        """
        if not self.enabled:
            return

        with self.lock:
            self.jobs[job_id] = JobMetric(job_id, step_id, time.time())

    def track_start(self, job_id: str) -> None:
        """
        Track job start (when it begins executing).

        :param job_id: Job identifier
        """
        if not self.enabled:
            return

        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].start_time = time.time()

                # Check for long wait times (potential queuing issues)
                wait = self.jobs[job_id].wait_duration
                if wait and wait > 60:  # More than 1 minute wait
                    self.warnings.append(
                        f"Job {job_id} waited {wait:.1f}s in queue (potential queuing bottleneck)"
                    )

    def track_complete(self, job_id: str) -> None:
        """
        Track job completion.

        :param job_id: Job identifier
        """
        if not self.enabled:
            return

        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].complete_time = time.time()

    def _sample_loop(self) -> None:
        """Periodically sample resource metrics (runs in background thread)."""
        while not self._stop_sampling:
            time.sleep(1.0)  # Sample every second

            with self.lock:
                try:
                    pending = len(
                        [j for j in self.jobs.values() if j.start_time is None]
                    )
                    active = len(
                        [
                            j
                            for j in self.jobs.values()
                            if j.start_time and not j.complete_time
                        ]
                    )
                    completed = len(
                        [j for j in self.jobs.values() if j.complete_time]
                    )

                    sample = ResourceSample(
                        timestamp=time.time(),
                        pending_jobs=pending,
                        active_jobs=active,
                        completed_jobs=completed,
                    )
                    self.resource_samples.append(sample)

                    # Deadlock detection: if many jobs pending for long time
                    if pending > 10:
                        long_pending = [
                            j
                            for j in self.jobs.values()
                            if j.start_time is None
                            and (time.time() - j.submit_time) > 300  # 5 minutes
                        ]
                        if long_pending:
                            self.warnings.append(
                                f"Potential deadlock: {len(long_pending)} jobs pending for >5min"
                            )

                except Exception:
                    # Ignore errors in sampling thread
                    pass

    def stop(self) -> None:
        """Stop background sampling thread."""
        if self.enabled:
            self._stop_sampling = True
            if self.sampling_thread.is_alive():
                self.sampling_thread.join(timeout=2.0)

    def export_report(self, path: str) -> None:
        """
        Export debug report to JSON file.

        :param path: Output file path
        """
        if not self.enabled:
            return

        self.stop()  # Stop sampling before export

        with self.lock:
            # Calculate summary statistics
            completed_jobs = [j for j in self.jobs.values() if j.complete_time]
            if completed_jobs:
                avg_wait = sum(j.wait_duration or 0 for j in completed_jobs) / len(
                    completed_jobs
                )
                avg_exec = sum(
                    j.execution_duration or 0 for j in completed_jobs
                ) / len(completed_jobs)
                max_wait = max((j.wait_duration or 0 for j in completed_jobs), default=0)
                max_exec = max(
                    (j.execution_duration or 0 for j in completed_jobs), default=0
                )
            else:
                avg_wait = avg_exec = max_wait = max_exec = 0

            report = {
                "summary": {
                    "total_jobs": len(self.jobs),
                    "completed_jobs": len(completed_jobs),
                    "avg_wait_time_seconds": round(avg_wait, 2),
                    "avg_execution_time_seconds": round(avg_exec, 2),
                    "max_wait_time_seconds": round(max_wait, 2),
                    "max_execution_time_seconds": round(max_exec, 2),
                },
                "jobs": [asdict(j) for j in self.jobs.values()],
                "resource_samples": [asdict(s) for s in self.resource_samples],
                "warnings": self.warnings,
            }

        with open(path, "w") as f:
            json.dump(report, f, indent=2)

    def __del__(self):
        """Cleanup: stop sampling thread on deletion."""
        self.stop()
